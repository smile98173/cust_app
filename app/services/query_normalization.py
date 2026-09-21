import re
import unicodedata
from typing import Optional


CHANNEL_QUERY_SUFFIXES = (
    "在哪個頻道",
    "在哪一個頻道",
    "在哪一台",
    "是哪一台",
    "在第幾台",
    "是第幾台",
    "在幾台",
    "是幾台",
    "第幾台",
    "頻道位置",
    "哪一台",
    "哪台",
    "幾台",
    "頻道",
)

CHANNEL_QUERY_NOISE_TERMS = (
    "我想知道",
    "想知道",
    "我要找",
    "想看",
    "請問",
    "查詢",
    "找不到",
    "查不到",
    "沒有",
)

CHANNEL_NAME_ALIASES = {
    "霹靂": "霹靂台灣台",
    "霹靂台": "霹靂台灣台",
    "霹靂電視": "霹靂台灣台",
}


def normalize_text_width(text: str) -> str:
    return unicodedata.normalize("NFKC", text or "")


def normalize_channel_name_from_query(text: str) -> Optional[str]:
    value = normalize_text_width(text).strip()
    if not value:
        return None

    for suffix in CHANNEL_QUERY_SUFFIXES:
        value = value.replace(suffix, "")
    for noise in CHANNEL_QUERY_NOISE_TERMS:
        value = value.replace(noise, "")

    value = re.sub(r"\s+", " ", value).strip(" ?？。,.，、")
    while value.endswith(("在", "是", "的")):
        value = value[:-1].strip(" ?？。,.，、")

    compact = value.replace(" ", "").replace("　", "")
    return CHANNEL_NAME_ALIASES.get(compact, value) or None


def is_technical_ip_address_query(text: str) -> bool:
    compact = (
        normalize_text_width(text)
        .lower()
        .replace(" ", "")
        .replace("　", "")
        .replace("-", "")
        .replace("_", "")
    )
    if not compact:
        return False

    return (
        "ip地址" in compact
        or "ipaddress" in compact
        or ("固定ip" in compact and "地址" in compact)
    )
