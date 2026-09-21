import json
import sqlite3
from abc import ABC, abstractmethod
from datetime import datetime
from typing import Any, Dict, List, Optional

from app.config.settings import (
    DB_PATH,
    MONGODB_DATABASE,
    MONGODB_LINE_COLLECTION,
    MONGODB_TEST_WEB_COLLECTION,
    MONGODB_URI,
    MONGODB_WEB_COLLECTION,
    STATE_REPOSITORY_BACKEND,
)
from app.services.error_logging import log_exception


class CustomerStateRepository(ABC):
    """Storage boundary for session-like customer state."""

    @abstractmethod
    def init_schema(self) -> None:
        pass

    @abstractmethod
    def get_session_document(self, user_id: str) -> Optional[Dict[str, Any]]:
        pass

    @abstractmethod
    def save_session_document(
        self,
        user_id: str,
        memory: Dict[str, Any],
        customer_key: Optional[str] = None,
    ) -> None:
        pass

    @abstractmethod
    def append_chat_log(
        self,
        user_id: str,
        role: str,
        message: str,
        customer_key: Optional[str] = None,
    ) -> None:
        pass

    @abstractmethod
    def get_recent_chat_history(self, user_id: str, limit: int = 12) -> List[Dict[str, str]]:
        pass

    @abstractmethod
    def list_chat_logs_since(
        self, start_date: str, limit: int = 20000, after: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Return customer/AI conversation entries for secured tracker export."""
        pass

    @abstractmethod
    def delete_user_state(self, user_id: str) -> None:
        pass

    @abstractmethod
    def get_customer_profile(self, customer_key: str) -> Optional[Dict[str, Any]]:
        pass

    @abstractmethod
    def save_customer_profile(self, profile: Dict[str, Any]) -> None:
        pass


class SQLiteCustomerStateRepository(CustomerStateRepository):
    """SQLite implementation that exposes MongoDB-like document operations."""

    def __init__(self, db_path: str = DB_PATH):
        self.db_path = db_path

    def connect(self):
        conn = sqlite3.connect(self.db_path, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        return conn

    def init_schema(self) -> None:
        conn = self.connect()
        cursor = conn.cursor()

        cursor.execute("""
        CREATE TABLE IF NOT EXISTS sessions (
            user_id TEXT PRIMARY KEY,
            customer_key TEXT,
            memory_json TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """)
        self._ensure_column(cursor, "sessions", "customer_key", "TEXT")

        cursor.execute("""
        CREATE TABLE IF NOT EXISTS chat_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT NOT NULL,
            customer_key TEXT,
            role TEXT NOT NULL,
            message TEXT NOT NULL,
            created_at TEXT NOT NULL
        )
        """)
        self._ensure_column(cursor, "chat_logs", "customer_key", "TEXT")

        cursor.execute("""
        CREATE TABLE IF NOT EXISTS customer_profiles (
            customer_key TEXT PRIMARY KEY,
            last_company_code TEXT,
            last_company TEXT,
            last_area TEXT,
            last_user_id TEXT,
            last_line_bot_code TEXT,
            resolution_source TEXT,
            updated_at TEXT NOT NULL
        )
        """)

        conn.commit()
        conn.close()

    def get_session_document(self, user_id: str) -> Optional[Dict[str, Any]]:
        conn = self.connect()
        cursor = conn.cursor()
        cursor.execute(
            "SELECT user_id, customer_key, memory_json, updated_at FROM sessions WHERE user_id = ?",
            (user_id,),
        )
        row = cursor.fetchone()
        conn.close()
        if not row:
            return None

        try:
            memory = json.loads(row["memory_json"])
        except Exception:
            memory = {}

        return {
            "user_id": row["user_id"],
            "customer_key": row["customer_key"],
            "memory": memory,
            "updated_at": row["updated_at"],
        }

    def save_session_document(
        self,
        user_id: str,
        memory: Dict[str, Any],
        customer_key: Optional[str] = None,
    ) -> None:
        now = datetime.now().isoformat()
        conn = self.connect()
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO sessions (user_id, customer_key, memory_json, updated_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(user_id) DO UPDATE SET
                customer_key=excluded.customer_key,
                memory_json=excluded.memory_json,
                updated_at=excluded.updated_at
            """,
            (
                user_id,
                customer_key,
                json.dumps(memory, ensure_ascii=False),
                now,
            ),
        )
        conn.commit()
        conn.close()

    def append_chat_log(
        self,
        user_id: str,
        role: str,
        message: str,
        customer_key: Optional[str] = None,
    ) -> None:
        conn = self.connect()
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO chat_logs (user_id, customer_key, role, message, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (user_id, customer_key, role, message, datetime.now().isoformat()),
        )
        conn.commit()
        conn.close()

    def get_recent_chat_history(self, user_id: str, limit: int = 12) -> List[Dict[str, str]]:
        conn = self.connect()
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT role, message
            FROM chat_logs
            WHERE user_id = ?
            ORDER BY id DESC
            LIMIT ?
            """,
            (user_id, limit),
        )
        rows = list(cursor.fetchall())
        conn.close()

        rows.reverse()
        return [{"role": row["role"], "content": row["message"]} for row in rows]

    def list_chat_logs_since(
        self, start_date: str, limit: int = 20000, after: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        conn = self.connect()
        try:
            clauses = ["substr(created_at, 1, 10) >= ?"]
            params: list[Any] = [start_date]
            if after:
                clauses.append("created_at > ?")
                params.append(after)
            params.append(max(1, min(int(limit), 50000)))
            rows = conn.execute(
                f"""
                SELECT id, user_id, customer_key, role, message, created_at
                FROM chat_logs
                WHERE {' AND '.join(clauses)}
                ORDER BY created_at ASC, id ASC
                LIMIT ?
                """,
                params,
            ).fetchall()
        finally:
            conn.close()
        return [dict(row) for row in rows]

    def delete_user_state(self, user_id: str) -> None:
        conn = self.connect()
        cursor = conn.cursor()
        cursor.execute("DELETE FROM sessions WHERE user_id = ?", (user_id,))
        cursor.execute("DELETE FROM chat_logs WHERE user_id = ?", (user_id,))
        conn.commit()
        conn.close()

    def get_customer_profile(self, customer_key: str) -> Optional[Dict[str, Any]]:
        conn = self.connect()
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT customer_key, last_company_code, last_company, last_area,
                   last_user_id, last_line_bot_code, resolution_source, updated_at
            FROM customer_profiles
            WHERE customer_key = ?
            """,
            (customer_key,),
        )
        row = cursor.fetchone()
        conn.close()
        return dict(row) if row else None

    def save_customer_profile(self, profile: Dict[str, Any]) -> None:
        customer_key = profile.get("customer_key")
        if not customer_key:
            return

        conn = self.connect()
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO customer_profiles (
                customer_key, last_company_code, last_company, last_area,
                last_user_id, last_line_bot_code, resolution_source, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(customer_key) DO UPDATE SET
                last_company_code=excluded.last_company_code,
                last_company=excluded.last_company,
                last_area=excluded.last_area,
                last_user_id=excluded.last_user_id,
                last_line_bot_code=excluded.last_line_bot_code,
                resolution_source=excluded.resolution_source,
                updated_at=excluded.updated_at
            """,
            (
                customer_key,
                profile.get("last_company_code"),
                profile.get("last_company"),
                profile.get("last_area"),
                profile.get("last_user_id"),
                profile.get("last_line_bot_code"),
                profile.get("resolution_source"),
                profile.get("updated_at") or datetime.now().isoformat(),
            ),
        )
        conn.commit()
        conn.close()

    def _ensure_column(self, cursor, table_name: str, column_name: str, column_type: str) -> None:
        cursor.execute(f"PRAGMA table_info({table_name})")
        existing = {row["name"] for row in cursor.fetchall()}
        if column_name not in existing:
            cursor.execute(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {column_type}")


class MongoCustomerStateRepository(CustomerStateRepository):
    """MongoDB implementation using separate Web and LINE collections."""

    def __init__(
        self,
        uri: str = MONGODB_URI,
        database_name: str = MONGODB_DATABASE,
        web_collection_name: str = MONGODB_WEB_COLLECTION,
        test_web_collection_name: str = MONGODB_TEST_WEB_COLLECTION,
        line_collection_name: str = MONGODB_LINE_COLLECTION,
        client: Any = None,
    ):
        if client is None:
            try:
                from pymongo import MongoClient
            except ImportError as exc:
                raise RuntimeError(
                    "STATE_REPOSITORY_BACKEND=mongodb 需要安裝 pymongo。"
                ) from exc
            client = MongoClient(uri)

        self.client = client
        self.database = client[database_name]
        self.web_collection = self.database[web_collection_name]
        self.test_web_collection = self.database[test_web_collection_name]
        self.line_collection = self.database[line_collection_name]

    def init_schema(self) -> None:
        try:
            self._ensure_unique_id_index(self.web_collection)
            self._ensure_unique_id_index(self.test_web_collection)
            self._ensure_unique_id_index(self.line_collection)
        except Exception as exc:
            log_exception("mongodb.init_schema", exc)
            raise

    def _ensure_unique_id_index(self, collection) -> None:
        try:
            for index in collection.list_indexes():
                key = list(index.get("key", {}).items())
                if key == [("id", 1)] and index.get("unique") is True:
                    return
        except AttributeError:
            pass

        collection.create_index("id", unique=True, name="id_unique")

    def _now(self) -> str:
        return datetime.now().isoformat()

    def _line_fields_from_user_id(self, user_id: str) -> Dict[str, Any]:
        parts = (user_id or "").split(":")
        if len(parts) >= 3 and parts[0] == "line":
            return {
                "channel": "line",
                "line_bot_code": parts[1],
                "line_user_id": parts[-1],
            }
        if len(parts) >= 2 and parts[0] == "web":
            return {
                "channel": "web",
            }
        if len(parts) >= 2 and parts[0] == "test_web":
            return {
                "channel": "test_web",
            }
        return {
            "channel": "unknown",
        }

    def _collection_for_user_id(self, user_id: str):
        if str(user_id or "").startswith("line:"):
            return self.line_collection
        if str(user_id or "").startswith("test_web:"):
            return self.test_web_collection
        if str(user_id or "").startswith("web:"):
            return self.web_collection
        return self.web_collection

    def _collection_for_customer_key(self, customer_key: str):
        if str(customer_key or "").startswith("line:"):
            return self.line_collection
        if str(customer_key or "").startswith("test_web:"):
            return self.test_web_collection
        if str(customer_key or "").startswith("web:"):
            return self.web_collection
        return self.line_collection

    def get_session_document(self, user_id: str) -> Optional[Dict[str, Any]]:
        try:
            document = self._collection_for_user_id(user_id).find_one({"id": user_id})
        except Exception as exc:
            log_exception("mongodb.get_session_document", exc, user_id=user_id)
            raise
        if not document:
            return None

        memory = document.get("ai_state") or document.get("memory") or {}
        return {
            "user_id": document.get("user_id") or user_id,
            "customer_key": document.get("customer_key"),
            "memory": memory,
            "updated_at": document.get("updated_at"),
        }

    def save_session_document(
        self,
        user_id: str,
        memory: Dict[str, Any],
        customer_key: Optional[str] = None,
    ) -> None:
        now = self._now()
        line_fields = self._line_fields_from_user_id(user_id)
        known_info = memory.get("known_info") or {}
        try:
            self._collection_for_user_id(user_id).update_one(
                {"id": user_id},
                {
                    "$set": {
                        "id": user_id,
                        "user_id": user_id,
                        "doc_type": "conversation",
                        "customer_key": customer_key,
                        "member_id": memory.get("member_id") or known_info.get("member_id"),
                        "is_logged_in": memory.get("is_logged_in") if memory.get("is_logged_in") is not None else known_info.get("is_logged_in"),
                        "ai_state": memory,
                        "memory": memory,
                        "updated_at": now,
                        **line_fields,
                    },
                    "$setOnInsert": {
                        "_id": user_id,
                        "chat_logs": [],
                        "created_at": now,
                    },
                },
                upsert=True,
            )
        except Exception as exc:
            log_exception(
                "mongodb.save_session_document",
                exc,
                user_id=user_id,
                extra={"customer_key": customer_key},
            )
            raise

    def append_chat_log(
        self,
        user_id: str,
        role: str,
        message: str,
        customer_key: Optional[str] = None,
    ) -> None:
        now = self._now()
        line_fields = self._line_fields_from_user_id(user_id)
        try:
            self._collection_for_user_id(user_id).update_one(
                {"id": user_id},
                {
                    "$set": {
                        "id": user_id,
                        "user_id": user_id,
                        "doc_type": "conversation",
                        "customer_key": customer_key,
                        "updated_at": now,
                        "last_message_at": now,
                        **line_fields,
                    },
                    "$setOnInsert": {
                        "_id": user_id,
                        "ai_state": {},
                        "memory": {},
                        "created_at": now,
                    },
                    "$push": {
                        "chat_logs": {
                            "role": role,
                            "message": message,
                            "created_at": now,
                        }
                    },
                },
                upsert=True,
            )
        except Exception as exc:
            log_exception(
                "mongodb.append_chat_log",
                exc,
                user_id=user_id,
                extra={"customer_key": customer_key, "role": role},
            )
            raise

    def get_recent_chat_history(self, user_id: str, limit: int = 12) -> List[Dict[str, str]]:
        try:
            document = self._collection_for_user_id(user_id).find_one({"id": user_id}, {"chat_logs": {"$slice": -limit}})
        except Exception as exc:
            log_exception(
                "mongodb.get_recent_chat_history",
                exc,
                user_id=user_id,
                extra={"limit": limit},
            )
            raise
        if not document:
            return []

        logs = document.get("chat_logs") or []
        return [
            {
                "role": item.get("role", ""),
                "content": item.get("message", ""),
            }
            for item in logs
        ]

    def list_chat_logs_since(
        self, start_date: str, limit: int = 20000, after: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        records: List[Dict[str, Any]] = []
        capped_limit = max(1, min(int(limit), 50000))
        collections = (
            ("web", self.web_collection),
            ("test_web", self.test_web_collection),
            ("line", self.line_collection),
        )
        try:
            for channel, collection in collections:
                match: Dict[str, Any] = {"$gte": start_date}
                if after:
                    match["$gt"] = after
                pipeline = [
                    {"$unwind": "$chat_logs"},
                    {"$match": {"chat_logs.created_at": match}},
                    {"$sort": {"chat_logs.created_at": 1, "id": 1}},
                    {"$limit": capped_limit},
                    {"$project": {
                        "id": 1, "user_id": 1, "customer_key": 1, "chat_log": "$chat_logs",
                    }},
                ]
                documents = collection.aggregate(pipeline)
                for document in documents:
                    user_id = str(document.get("user_id") or document.get("id") or "")
                    item = document.get("chat_log") or {}
                    created_at = str(item.get("created_at") or "")
                    records.append({
                        "id": f"{channel}:{user_id}:{created_at}:{item.get('role') or ''}",
                        "user_id": user_id,
                        "customer_key": document.get("customer_key"),
                        "role": item.get("role") or "",
                        "message": item.get("message") or "",
                        "created_at": created_at,
                    })
        except Exception as exc:
            log_exception("mongodb.list_chat_logs_since", exc, extra={"start_date": start_date})
            raise
        return sorted(records, key=lambda record: str(record.get("created_at") or ""))[:capped_limit]

    def delete_user_state(self, user_id: str) -> None:
        try:
            self._collection_for_user_id(user_id).delete_one({"id": user_id})
        except Exception as exc:
            log_exception("mongodb.delete_user_state", exc, user_id=user_id)
            raise

    def get_customer_profile(self, customer_key: str) -> Optional[Dict[str, Any]]:
        try:
            document = self._collection_for_customer_key(customer_key).find_one({"id": customer_key})
        except Exception as exc:
            log_exception(
                "mongodb.get_customer_profile",
                exc,
                extra={"customer_key": customer_key},
            )
            raise
        if not document:
            return None

        profile = document.get("customer_profile") or {}
        if profile:
            return profile

        ai_state = document.get("ai_state") or {}
        profile = ai_state.get("customer_profile") or {}
        return profile or None

    def save_customer_profile(self, profile: Dict[str, Any]) -> None:
        customer_key = profile.get("customer_key")
        if not customer_key:
            return

        now = profile.get("updated_at") or self._now()
        try:
            self._collection_for_customer_key(customer_key).update_one(
                {"id": customer_key},
                {
                    "$set": {
                        "id": customer_key,
                        "doc_type": "line_customer_profile",
                        "customer_key": customer_key,
                        "customer_profile": profile,
                        "ai_state": {
                            "customer_profile": profile,
                        },
                        "updated_at": now,
                    },
                    "$setOnInsert": {
                        "_id": customer_key,
                        "chat_logs": [],
                        "created_at": now,
                    },
                },
                upsert=True,
            )
        except Exception as exc:
            log_exception(
                "mongodb.save_customer_profile",
                exc,
                extra={"customer_key": customer_key},
            )
            raise


_repository: Optional[CustomerStateRepository] = None


def get_state_repository() -> CustomerStateRepository:
    global _repository
    if _repository is None:
        if STATE_REPOSITORY_BACKEND == "sqlite":
            _repository = SQLiteCustomerStateRepository()
        elif STATE_REPOSITORY_BACKEND == "mongodb":
            _repository = MongoCustomerStateRepository()
        else:
            raise RuntimeError(f"不支援的 STATE_REPOSITORY_BACKEND：{STATE_REPOSITORY_BACKEND}")
    return _repository


def set_state_repository_for_tests(repository: Optional[CustomerStateRepository]) -> None:
    global _repository
    _repository = repository
