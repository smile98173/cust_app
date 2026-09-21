import re
from typing import Any, Optional


CONTRACT_LOOKUP_LOGIN_REQUIRED_REPLY = (
    "為保障您的個人資料安全，個人帳務及方案等資訊需登入會員後才能查詢，"
    "您可以至官網或行動客服 APP 登入後查看相關資料。"
)


def normalize_tel(tel: Any) -> Optional[str]:
    if tel is None:
        return None

    digits = re.sub(r"\D", "", str(tel))
    return digits or None


def validate_name(name: Any) -> bool:
    if not name:
        return False

    value = str(name).strip()

    if len(value) < 2 or len(value) > 50:
        return False

    return bool(re.fullmatch(r"[\u4e00-\u9fffA-Za-z .·]+", value))


def validate_tel(tel: Any) -> bool:
    digits = normalize_tel(tel)
    if not digits:
        return False

    return bool(re.fullmatch(r"09\d{8}|0[2-8]\d{7,8}|[2-9]\d{6,7}", digits))


def normalize_customer_number(value: Any) -> Optional[str]:
    if value is None:
        return None

    customer_number = str(value).strip()
    if not re.fullmatch(r"[1-9]\d{3,29}", customer_number):
        return None

    return customer_number


def valid_name_tel(data: dict) -> bool:
    return validate_name(data.get("name")) and validate_tel(data.get("phone"))


def has_authenticated_web_custnum(memory: dict) -> bool:
    """Return whether the customer number came from an authenticated web session."""
    known_info = (memory or {}).get("known_info") or {}
    return bool(
        normalize_customer_number(known_info.get("custnum"))
        and known_info.get("custnum_source") == "web_authenticated"
        and (known_info.get("is_logged_in") or (memory or {}).get("is_logged_in"))
    )


def has_custnum_secondary_verification(memory: dict) -> bool:
    """Manual identity lookups require both a valid name and phone number."""
    known_info = (memory or {}).get("known_info") or {}
    return validate_name(known_info.get("name")) and validate_tel(known_info.get("phone"))
