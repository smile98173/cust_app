"""Shared slot normalization and memory update helpers."""

import re
from datetime import datetime, timedelta
from typing import Optional, Dict, Any

from app.services.customer_validation import normalize_tel, validate_tel


def parse_speed_value(text: str) -> Optional[float]:
    if not text:
        return None

    m = re.search(r"(\d+(?:\.\d+)?)", str(text))
    if m:
        try:
            return float(m.group(1))
        except Exception:
            return None
    return None


def normalize_phone_value(phone: Any) -> Optional[str]:
    digits = normalize_tel(phone)
    if digits and validate_tel(digits):
        return digits
    return None


def parse_preferred_date(text: str) -> Optional[str]:
    if not text:
        return None

    text = str(text).strip()
    today = datetime.now().date()

    if "今天" in text:
        return today.isoformat()
    if "明天" in text:
        return (today + timedelta(days=1)).isoformat()
    if "後天" in text:
        return (today + timedelta(days=2)).isoformat()

    m = re.search(r"(\d{4})[-/](\d{1,2})[-/](\d{1,2})", text)
    if m:
        y, mo, d = map(int, m.groups())
        return f"{y:04d}-{mo:02d}-{d:02d}"

    return None


def normalize_time_range(value: Any) -> Any:
    if not isinstance(value, str):
        return value

    text = value.strip().lower()

    if "上午" in text or "早上" in text:
        return "morning"
    if "下午" in text:
        return "afternoon"
    if "晚上" in text or "晚間" in text:
        return "evening"

    return value


def normalize_value(key: str, value: Any) -> Any:
    if key in ["download_speed", "upload_speed"]:
        parsed = parse_speed_value(str(value))
        return parsed if parsed is not None else value

    if key in ["contact_phone", "phone"]:
        parsed = normalize_phone_value(value)
        return parsed if parsed else value

    if key == "preferred_date":
        parsed = parse_preferred_date(str(value))
        return parsed if parsed else value

    if key == "preferred_time_range":
        return normalize_time_range(value)

    return value


def merge_memory_update(memory: Dict[str, Any], memory_update: Dict[str, Any]) -> Dict[str, Any]:
    known_info = dict(memory.get("known_info", {}))

    for key, value in memory_update.items():
        if key == "service":
            memory["service"] = value
            continue

        if key == "issue_type":
            memory["issue_type"] = value
            continue

        if key == "need_dispatch":
            memory["need_dispatch"] = value
            continue

        if key == "company":
            memory["company"] = value
            continue

        if value is None or value == "":
            continue

        known_info[key] = normalize_value(key, value)

    memory["known_info"] = known_info
    return memory
