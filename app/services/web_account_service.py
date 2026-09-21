import base64
import hashlib
import hmac
import json
import secrets
import sqlite3
import time
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any

from app.config.settings import (
    WEB_AUTH_BOOTSTRAP_PASSWORD,
    WEB_AUTH_BOOTSTRAP_USERNAME,
    WEB_AUTH_DB_PATH,
    WEB_AUTH_SECRET,
)
from app.services.error_logging import get_error_logger
from app.services.knowledge_base_policy import (
    LEGACY_COMMON_KNOWLEDGE_BASE,
    REGIONAL_COMMON_KNOWLEDGE_BASES,
    REGIONAL_COMMON_MEMBERS,
    normalize_knowledge_base_name,
)


ROLE_DEVELOPER = "developer"
ROLE_SUPERVISOR = "supervisor"
ROLE_STAFF = "staff"

ROLE_LABELS = {
    ROLE_DEVELOPER: "系統管理者（研發）",
    ROLE_SUPERVISOR: "主管",
    ROLE_STAFF: "客服同仁／一般職員",
}

PERMISSION_CHAT = "chat"
PERMISSION_IMAGE_OCR = "image_ocr"
PERMISSION_FEEDBACK = "feedback"
PERMISSION_COMPANY_PROFILES = "company_profiles"
PERMISSION_KNOWLEDGE_BASE = "knowledge_base"
PERMISSION_ACCOUNT_MANAGEMENT = "account_management"

ROLE_PERMISSIONS = {
    ROLE_DEVELOPER: {
        PERMISSION_CHAT,
        PERMISSION_IMAGE_OCR,
        PERMISSION_FEEDBACK,
        PERMISSION_COMPANY_PROFILES,
        PERMISSION_KNOWLEDGE_BASE,
        PERMISSION_ACCOUNT_MANAGEMENT,
    },
    ROLE_SUPERVISOR: {
        PERMISSION_CHAT,
        PERMISSION_IMAGE_OCR,
        PERMISSION_FEEDBACK,
        PERMISSION_COMPANY_PROFILES,
        PERMISSION_KNOWLEDGE_BASE,
    },
    ROLE_STAFF: {
        PERMISSION_CHAT,
        PERMISSION_IMAGE_OCR,
        PERMISSION_FEEDBACK,
    },
}

VALID_ROLES = tuple(ROLE_LABELS.keys())
PASSWORD_ITERATIONS = 260_000
SESSION_TTL_SECONDS = 3 * 60 * 60
class WebAccountError(ValueError):
    pass


def utcnow_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def base64url_encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def base64url_decode(value: str) -> bytes:
    padding = "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode((value + padding).encode("ascii"))


def normalize_username(username: str) -> str:
    return str(username or "").strip().lower()


def normalize_knowledge_base(value: str) -> str:
    return normalize_knowledge_base_name(value)


def normalize_managed_knowledge_bases(values: list[str] | tuple[str, ...] | None) -> list[str]:
    normalized = []
    for value in values or []:
        name = normalize_knowledge_base(value)
        if name and name not in normalized:
            normalized.append(name)
    return normalized


def is_placeholder_secret(value: str) -> bool:
    text = str(value or "").strip()
    return not text or (text.startswith("<") and text.endswith(">"))


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256",
        str(password or "").encode("utf-8"),
        salt,
        PASSWORD_ITERATIONS,
    )
    return "pbkdf2_sha256${}${}${}".format(
        PASSWORD_ITERATIONS,
        base64url_encode(salt),
        base64url_encode(digest),
    )


def verify_password(password: str, password_hash: str) -> bool:
    try:
        algorithm, iterations_text, salt_b64, digest_b64 = str(password_hash or "").split("$", 3)
        if algorithm != "pbkdf2_sha256":
            return False
        iterations = int(iterations_text)
        salt = base64url_decode(salt_b64)
        expected_digest = base64url_decode(digest_b64)
    except Exception:
        return False

    actual_digest = hashlib.pbkdf2_hmac(
        "sha256",
        str(password or "").encode("utf-8"),
        salt,
        iterations,
    )
    return secrets.compare_digest(actual_digest, expected_digest)


class WebAccountService:
    def __init__(self, db_path: str = WEB_AUTH_DB_PATH, secret: str = WEB_AUTH_SECRET):
        self.db_path = str(db_path)
        self.secret = str(secret or "local-web-auth-secret")

    def connect(self):
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self.db_path, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        return conn

    @contextmanager
    def connection(self):
        conn = self.connect()
        try:
            yield conn
        finally:
            conn.close()

    def init_schema(self) -> None:
        with self.connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
            CREATE TABLE IF NOT EXISTS web_accounts (
                id TEXT PRIMARY KEY,
                username TEXT NOT NULL UNIQUE,
                display_name TEXT NOT NULL,
                password_hash TEXT NOT NULL,
                role TEXT NOT NULL,
                is_active INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                last_login_at TEXT
            )
            """)
            cursor.execute("""
            CREATE TABLE IF NOT EXISTS web_account_audit_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                actor_username TEXT,
                action TEXT NOT NULL,
                target_username TEXT,
                detail_json TEXT,
                created_at TEXT NOT NULL
            )
            """)
            cursor.execute("""
            CREATE TABLE IF NOT EXISTS knowledge_base_common_scopes (
                common_knowledge_base TEXT PRIMARY KEY,
                member_knowledge_bases_json TEXT NOT NULL,
                updated_by TEXT,
                updated_at TEXT NOT NULL
            )
            """)
            columns = {
                row["name"]
                for row in cursor.execute("PRAGMA table_info(web_accounts)").fetchall()
            }
            if "managed_knowledge_bases_json" not in columns:
                cursor.execute(
                    """
                    ALTER TABLE web_accounts
                    ADD COLUMN managed_knowledge_bases_json TEXT NOT NULL DEFAULT '[]'
                    """
                )
            now = utcnow_iso()
            existing_common_scopes = {
                row["common_knowledge_base"]
                for row in cursor.execute(
                    """
                    SELECT common_knowledge_base
                    FROM knowledge_base_common_scopes
                    """
                ).fetchall()
            }
            for common_base, members in REGIONAL_COMMON_MEMBERS.items():
                if common_base in existing_common_scopes:
                    continue
                cursor.execute(
                    """
                    INSERT INTO knowledge_base_common_scopes (
                        common_knowledge_base,
                        member_knowledge_bases_json,
                        updated_by,
                        updated_at
                    )
                    VALUES (?, ?, ?, ?)
                    """,
                    (
                        common_base,
                        json.dumps(sorted(members), ensure_ascii=False),
                        "system",
                        now,
                    ),
                )
            conn.commit()

    def account_count(self) -> int:
        with self.connection() as conn:
            row = conn.execute("SELECT COUNT(*) AS count FROM web_accounts").fetchone()
        return int(row["count"] if row else 0)

    def bootstrap_from_env(self) -> bool:
        username = normalize_username(WEB_AUTH_BOOTSTRAP_USERNAME)
        password = str(WEB_AUTH_BOOTSTRAP_PASSWORD or "")
        if self.account_count() > 0:
            return False
        if is_placeholder_secret(username) or is_placeholder_secret(password):
            return False

        self.create_account(
            username=username,
            password=password,
            role=ROLE_DEVELOPER,
            display_name=username,
            actor_username="system",
        )
        return True

    def create_account(
        self,
        *,
        username: str,
        password: str,
        role: str,
        display_name: str = "",
        managed_knowledge_bases: list[str] | None = None,
        actor_username: str = "",
    ) -> dict[str, Any]:
        username = normalize_username(username)
        display_name = str(display_name or username).strip()
        if not username:
            raise WebAccountError("帳號不可空白。")
        if not password:
            raise WebAccountError("密碼不可空白。")
        if role not in VALID_ROLES:
            raise WebAccountError("角色不正確。")
        managed_bases = normalize_managed_knowledge_bases(managed_knowledge_bases)

        account_id = secrets.token_urlsafe(16)
        now = utcnow_iso()
        try:
            with self.connection() as conn:
                conn.execute(
                    """
                    INSERT INTO web_accounts (
                        id, username, display_name, password_hash,
                        role, managed_knowledge_bases_json, is_active,
                        created_at, updated_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, 1, ?, ?)
                    """,
                    (
                        account_id,
                        username,
                        display_name,
                        hash_password(password),
                        role,
                        json.dumps(managed_bases, ensure_ascii=False),
                        now,
                        now,
                    ),
                )
                conn.commit()
        except sqlite3.IntegrityError as exc:
            raise WebAccountError("帳號已存在。") from exc

        self.log_audit(
            actor_username,
            "create_account",
            username,
            {"role": role, "managed_knowledge_bases": managed_bases},
        )
        return self.get_account_by_username(username) or {}

    def list_accounts(self) -> list[dict[str, Any]]:
        with self.connection() as conn:
            rows = conn.execute(
                """
                SELECT id, username, display_name, role,
                       managed_knowledge_bases_json, is_active,
                       created_at, updated_at, last_login_at
                FROM web_accounts
                ORDER BY is_active DESC, role ASC, username ASC
                """
            ).fetchall()
        return [self.account_from_row(row) for row in rows]

    def get_account_by_username(self, username: str) -> dict[str, Any] | None:
        with self.connection() as conn:
            row = conn.execute(
                """
                SELECT id, username, display_name, role,
                       managed_knowledge_bases_json, is_active,
                       created_at, updated_at, last_login_at
                FROM web_accounts
                WHERE username = ?
                """,
                (normalize_username(username),),
            ).fetchone()
        return self.account_from_row(row) if row else None

    def get_password_record(self, username: str) -> sqlite3.Row | None:
        with self.connection() as conn:
            row = conn.execute(
                """
                SELECT id, username, display_name, password_hash, role,
                       managed_knowledge_bases_json, is_active,
                       created_at, updated_at, last_login_at
                FROM web_accounts
                WHERE username = ?
                """,
                (normalize_username(username),),
            ).fetchone()
        return row

    def authenticate(self, username: str, password: str) -> dict[str, Any] | None:
        username = normalize_username(username)
        row = self.get_password_record(username)
        if not row or not int(row["is_active"] or 0):
            self.log_audit(username, "login_failed", username, {"reason": "missing_or_inactive"})
            return None
        if not verify_password(password, row["password_hash"]):
            self.log_audit(username, "login_failed", username, {"reason": "bad_password"})
            return None

        now = utcnow_iso()
        with self.connection() as conn:
            conn.execute(
                "UPDATE web_accounts SET last_login_at = ?, updated_at = ? WHERE username = ?",
                (now, now, username),
            )
            conn.commit()

        self.log_audit(username, "login_success", username, {})
        return self.get_account_by_username(username)

    def update_account(
        self,
        username: str,
        *,
        display_name: str | None = None,
        role: str | None = None,
        is_active: bool | None = None,
        password: str | None = None,
        managed_knowledge_bases: list[str] | None = None,
        actor_username: str = "",
    ) -> dict[str, Any]:
        username = normalize_username(username)
        account = self.get_account_by_username(username)
        if not account:
            raise WebAccountError("找不到帳號。")

        new_role = role if role is not None else account["role"]
        new_active = bool(account["is_active"]) if is_active is None else bool(is_active)
        if new_role not in VALID_ROLES:
            raise WebAccountError("角色不正確。")
        if self.would_remove_last_active_developer(username, new_role, new_active):
            raise WebAccountError("不能停用或移除最後一個研發人員帳號。")

        fields = []
        values: list[Any] = []
        if display_name is not None:
            fields.append("display_name = ?")
            values.append(str(display_name or username).strip() or username)
        if role is not None:
            fields.append("role = ?")
            values.append(new_role)
        if is_active is not None:
            fields.append("is_active = ?")
            values.append(1 if new_active else 0)
        if password:
            fields.append("password_hash = ?")
            values.append(hash_password(password))
        if managed_knowledge_bases is not None:
            fields.append("managed_knowledge_bases_json = ?")
            values.append(json.dumps(
                normalize_managed_knowledge_bases(managed_knowledge_bases),
                ensure_ascii=False,
            ))

        if not fields:
            return account

        fields.append("updated_at = ?")
        values.append(utcnow_iso())
        values.append(username)

        with self.connection() as conn:
            conn.execute(
                f"UPDATE web_accounts SET {', '.join(fields)} WHERE username = ?",
                tuple(values),
            )
            conn.commit()

        self.log_audit(
            actor_username,
            "update_account",
            username,
            {
                "role": new_role,
                "is_active": new_active,
                "password_changed": bool(password),
                "managed_knowledge_bases": (
                    normalize_managed_knowledge_bases(managed_knowledge_bases)
                    if managed_knowledge_bases is not None
                    else account.get("managed_knowledge_bases", [])
                ),
            },
        )
        return self.get_account_by_username(username) or {}

    def get_common_knowledge_base_scopes(self) -> dict[str, list[str]]:
        defaults = {
            common_base: sorted(
                normalize_managed_knowledge_bases(list(members))
            )
            for common_base, members in REGIONAL_COMMON_MEMBERS.items()
        }
        try:
            with self.connection() as conn:
                rows = conn.execute(
                    """
                    SELECT common_knowledge_base, member_knowledge_bases_json
                    FROM knowledge_base_common_scopes
                    """
                ).fetchall()
        except sqlite3.OperationalError:
            return defaults

        scopes = dict(defaults)
        for row in rows:
            common_base = normalize_knowledge_base(row["common_knowledge_base"])
            if common_base not in REGIONAL_COMMON_KNOWLEDGE_BASES:
                continue
            try:
                members = json.loads(row["member_knowledge_bases_json"] or "[]")
            except Exception:
                members = []
            if not isinstance(members, list):
                members = []
            scopes[common_base] = [
                member
                for member in normalize_managed_knowledge_bases(members)
                if member not in REGIONAL_COMMON_KNOWLEDGE_BASES
            ]
        return scopes

    def update_common_knowledge_base_scopes(
        self,
        scopes: dict[str, list[str] | tuple[str, ...]],
        *,
        actor_username: str = "",
    ) -> dict[str, list[str]]:
        if not isinstance(scopes, dict):
            raise WebAccountError("通用知識庫適用範圍格式不正確。")

        current = self.get_common_knowledge_base_scopes()
        updated = dict(current)
        for raw_common_base, raw_members in scopes.items():
            common_base = normalize_knowledge_base(raw_common_base)
            if common_base not in REGIONAL_COMMON_KNOWLEDGE_BASES:
                raise WebAccountError("只能設定通用-中區或通用-嘉南區的適用範圍。")
            members = [
                member
                for member in normalize_managed_knowledge_bases(raw_members)
                if member not in {
                    LEGACY_COMMON_KNOWLEDGE_BASE,
                    *REGIONAL_COMMON_KNOWLEDGE_BASES,
                }
            ]
            updated[common_base] = members

        member_owners: dict[str, list[str]] = {}
        for common_base in REGIONAL_COMMON_KNOWLEDGE_BASES:
            for member in updated.get(common_base, []):
                member_owners.setdefault(member, []).append(common_base)
        conflicts = {
            member: owners
            for member, owners in member_owners.items()
            if len(owners) > 1
        }
        if conflicts:
            conflict_text = "、".join(sorted(conflicts))
            raise WebAccountError(
                f"同一系統台不可同時套用中區與嘉南區通用規則：{conflict_text}。"
            )

        now = utcnow_iso()
        actor = normalize_username(actor_username)
        with self.connection() as conn:
            for common_base in REGIONAL_COMMON_KNOWLEDGE_BASES:
                conn.execute(
                    """
                    INSERT INTO knowledge_base_common_scopes (
                        common_knowledge_base,
                        member_knowledge_bases_json,
                        updated_by,
                        updated_at
                    )
                    VALUES (?, ?, ?, ?)
                    ON CONFLICT(common_knowledge_base) DO UPDATE SET
                        member_knowledge_bases_json = excluded.member_knowledge_bases_json,
                        updated_by = excluded.updated_by,
                        updated_at = excluded.updated_at
                    """,
                    (
                        common_base,
                        json.dumps(updated.get(common_base, []), ensure_ascii=False),
                        actor,
                        now,
                    ),
                )
            conn.commit()

        self.log_audit(
            actor,
            "update_common_knowledge_base_scopes",
            "",
            {"scopes": updated},
        )
        return self.get_common_knowledge_base_scopes()

    def would_remove_last_active_developer(self, username: str, new_role: str, new_active: bool) -> bool:
        with self.connection() as conn:
            rows = conn.execute(
                "SELECT username, role, is_active FROM web_accounts WHERE role = ? AND is_active = 1",
                (ROLE_DEVELOPER,),
            ).fetchall()
        active_developers = [row["username"] for row in rows]
        if username not in active_developers:
            return False
        remaining = [
            item for item in active_developers
            if item != username
        ]
        target_still_developer = new_active and new_role == ROLE_DEVELOPER
        return not target_still_developer and not remaining

    def create_session_token(self, account: dict[str, Any]) -> str:
        now = int(time.time())
        payload = {
            "sub": account.get("username"),
            "role": account.get("role"),
            "iat": now,
            "exp": now + SESSION_TTL_SECONDS,
            "nonce": secrets.token_urlsafe(12),
        }
        payload_b64 = base64url_encode(json.dumps(payload, separators=(",", ":")).encode("utf-8"))
        signature = hmac.new(
            self.secret.encode("utf-8"),
            payload_b64.encode("ascii"),
            "sha256",
        ).digest()
        return f"aicustweb.{payload_b64}.{base64url_encode(signature)}"

    def validate_session_token(self, token: str) -> dict[str, Any] | None:
        parts = str(token or "").split(".")
        if len(parts) != 3 or parts[0] != "aicustweb":
            return None

        _, payload_b64, signature_b64 = parts
        expected_signature = base64url_encode(
            hmac.new(
                self.secret.encode("utf-8"),
                payload_b64.encode("ascii"),
                "sha256",
            ).digest()
        )
        if not secrets.compare_digest(signature_b64, expected_signature):
            return None

        try:
            payload = json.loads(base64url_decode(payload_b64).decode("utf-8"))
            if int(payload.get("exp") or 0) < int(time.time()):
                return None
        except Exception:
            return None

        account = self.get_account_by_username(str(payload.get("sub") or ""))
        if not account or not account.get("is_active"):
            return None
        return account

    def log_audit(self, actor_username: str, action: str, target_username: str, detail: dict[str, Any]) -> None:
        created_at = utcnow_iso()
        actor = normalize_username(actor_username)
        target = normalize_username(target_username)
        with self.connection() as conn:
            conn.execute(
                """
                INSERT INTO web_account_audit_logs (
                    actor_username, action, target_username, detail_json, created_at
                )
                VALUES (?, ?, ?, ?, ?)
                """,
                (actor, action, target, json.dumps(detail or {}, ensure_ascii=False), created_at),
            )
            conn.commit()

        record = {
            "timestamp": created_at,
            "level": "INFO",
            "operation": "web_account_audit",
            "actor_username": actor,
            "action": action,
            "target_username": target,
            "detail": detail or {},
        }
        try:
            get_error_logger().error(json.dumps(record, ensure_ascii=False))
        except Exception:
            pass

    def list_audit_logs(
        self,
        *,
        action: str | None = None,
        limit: int = 200,
    ) -> list[dict[str, Any]]:
        safe_limit = max(1, min(int(limit or 200), 1000))
        query = """
            SELECT id, actor_username, action, target_username, detail_json, created_at
            FROM web_account_audit_logs
        """
        params: list[Any] = []
        if action:
            query += " WHERE action = ?"
            params.append(str(action))
        query += " ORDER BY id DESC LIMIT ?"
        params.append(safe_limit)

        with self.connection() as conn:
            rows = conn.execute(query, tuple(params)).fetchall()

        records = []
        for row in rows:
            try:
                detail = json.loads(row["detail_json"] or "{}")
            except Exception:
                detail = {}
            records.append({
                "id": row["id"],
                "actor_username": row["actor_username"] or "",
                "action": row["action"],
                "target": row["target_username"] or "",
                "detail": detail if isinstance(detail, dict) else {},
                "created_at": row["created_at"],
            })
        return records

    @staticmethod
    def account_from_row(row) -> dict[str, Any]:
        try:
            managed_bases = json.loads(row["managed_knowledge_bases_json"] or "[]")
        except Exception:
            managed_bases = []
        return {
            "id": row["id"],
            "username": row["username"],
            "display_name": row["display_name"],
            "role": row["role"],
            "role_label": role_label(row["role"]),
            "is_active": bool(row["is_active"]),
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
            "last_login_at": row["last_login_at"],
            "managed_knowledge_bases": normalize_managed_knowledge_bases(
                managed_bases if isinstance(managed_bases, list) else []
            ),
        }


def role_label(role: str) -> str:
    return ROLE_LABELS.get(role, str(role or "未知"))


def has_permission(account: dict[str, Any] | None, permission: str) -> bool:
    if not account:
        return False
    role = account.get("role")
    return permission in ROLE_PERMISSIONS.get(role, set())


def can_manage_knowledge_base(account: dict[str, Any] | None, knowledge_base: str) -> bool:
    if not has_permission(account, PERMISSION_KNOWLEDGE_BASE):
        return False
    if account.get("role") == ROLE_DEVELOPER:
        return True
    target = normalize_knowledge_base(knowledge_base)
    allowed = normalize_managed_knowledge_bases(account.get("managed_knowledge_bases"))
    return bool(target) and target in allowed


def can_view_knowledge_base(account: dict[str, Any] | None, knowledge_base: str = "") -> bool:
    if not has_permission(account, PERMISSION_KNOWLEDGE_BASE):
        return False
    return account.get("role") in {ROLE_DEVELOPER, ROLE_SUPERVISOR}
