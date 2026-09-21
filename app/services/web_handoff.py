import base64
import html
import time
from urllib.parse import quote

from cryptography.hazmat.primitives import padding
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

from app.config.settings import WEB_HUMAN_HANDOFF_TOKEN_KEY
from app.services.company_profile import DEFAULT_TV_CABLE


WEB_HUMAN_HANDOFF_SYSTEM_CODES = {
    "pktv": "P",       # 北港
    "wctv": "W",       # 台灣佳光
    "cltv": "L",       # 佳聯
    "tdtv": "T",       # 大屯
    "cnt": "N",        # 中投
    "toplight": "A",   # 台灣佳光（跨區）
    "hya": "J",        # 新永安
    "tycable": "K",    # 大揚
    "tinp": "Y",       # 台基科
}


def get_web_handoff_identifier(memory: dict) -> str:
    known = memory.get("known_info") or {}
    channel_context = memory.get("channel_context") or {}
    value = (
        known.get("custnum")
        or known.get("member_id")
        or known.get("external_user_id")
        or memory.get("member_id")
        or memory.get("external_user_id")
        or channel_context.get("member_id")
        or channel_context.get("external_user_id")
        or memory.get("customer_key")
        or "0"
    )
    text = str(value or "0").strip()
    if ":" in text:
        text = text.rsplit(":", 1)[-1]
    return text or "0"


def get_web_handoff_system_code(memory: dict) -> str:
    company_code = str(memory.get("company_code") or DEFAULT_TV_CABLE).strip().lower()
    return WEB_HUMAN_HANDOFF_SYSTEM_CODES.get(company_code, "T")


def _openssl_aes_128_key(key: str) -> bytes:
    key_bytes = str(key or "").encode("utf-8")
    return (key_bytes + (b"\0" * 16))[:16]


def create_web_handoff_token(
    identifier: str,
    *,
    now: int | None = None,
    key: str | None = None,
) -> str:
    timestamp = int(time.time() if now is None else now)
    plaintext = f"{identifier}+{timestamp}".encode("utf-8")

    padder = padding.PKCS7(algorithms.AES.block_size).padder()
    padded_plaintext = padder.update(plaintext) + padder.finalize()
    encryptor = Cipher(
        algorithms.AES(_openssl_aes_128_key(key or WEB_HUMAN_HANDOFF_TOKEN_KEY)),
        modes.ECB(),
    ).encryptor()
    encrypted = encryptor.update(padded_plaintext) + encryptor.finalize()
    return base64.urlsafe_b64encode(encrypted).decode("ascii").rstrip("=")


def build_web_handoff_url(
    memory: dict,
    *,
    now: int | None = None,
    key: str | None = None,
) -> str:
    raw_identifier = get_web_handoff_identifier(memory)
    identifier = quote(raw_identifier, safe="")
    system_code = quote(get_web_handoff_system_code(memory), safe="")
    token = quote(
        create_web_handoff_token(raw_identifier, now=now, key=key),
        safe="",
    )
    return (
        "http://pweb.topmso.com.tw:96/smartCustomerService/real/"
        f"{identifier}/0/{system_code}?token={token}"
    )


def build_web_human_handoff_reply(
    memory: dict,
    *,
    now: int | None = None,
    key: str | None = None,
) -> str:
    url = html.escape(build_web_handoff_url(memory, now=now, key=key), quote=True)
    return (
        "此項需由真人文字客服協助處理。<br>"
        f'請按 <a href="{url}">轉真人文字客服</a><br>'
        "或者繼續提問"
    )


def build_internal_test_human_handoff_reply() -> str:
    return (
        "此項需由真人文字客服協助處理。<br>"
        '請按 <a href="#internal-human-handoff" data-internal-human-handoff="1">'
        "轉真人文字客服</a><br>"
        "或者繼續提問"
    )
