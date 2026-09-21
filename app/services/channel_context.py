import hmac
import base64
import hashlib
import html
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

import requests

from app.config.settings import LINE_BOT_CONFIGS, LINE_HUMAN_MODE_TIMEOUT_SECONDS
from app.services.company_profile import (
    DEFAULT_TV_CABLE,
    TV_DICT,
    apply_company_to_memory,
    extract_company_links,
    get_all_company_profiles,
    get_company_profile,
    get_company_options,
)
from app.services.memory_service import (
    get_customer_profile as load_customer_profile,
    save_customer_profile,
)


@dataclass
class CompanyResolution:
    company_code: str
    company_name: str
    area: Optional[str] = None
    source: str = "unknown"
    matched_text: Optional[str] = None
    match_start: int = -1


def _find_identifier_start(text: str, identifier: str) -> int:
    """Find a company identifier without matching one-letter codes inside words."""
    haystack = str(text or "").lower()
    needle = str(identifier or "").strip().lower()
    if not needle:
        return -1
    if re.fullmatch(r"[a-z0-9]+", needle):
        match = re.search(rf"(?<![a-z0-9]){re.escape(needle)}(?![a-z0-9])", haystack)
        return match.start() if match else -1
    return haystack.find(needle)


SERVICE_AVAILABILITY_ACTION_TERMS = (
    "能申辦",
    "可以申辦",
    "可申辦",
    "想申辦",
    "要申辦",
    "想裝",
    "要裝",
    "想安裝",
    "要安裝",
    "申裝",
    "能裝",
    "可以裝",
    "可裝",
    "能安裝",
    "可以安裝",
    "可安裝",
    "裝得到",
    "有服務到",
    "服務到",
)

GENERIC_LOCATION_QUERY_TERMS = (
    "其他縣市",
    "別的縣市",
    "外縣市",
    "哪個縣市",
    "哪些縣市",
)

COUNTY_CITY_LOCATION_PATTERN = re.compile(
    r"(?P<location>[\u4e00-\u9fff]{2,4}(?:縣|市)(?:[\u4e00-\u9fff]{1,4}(?:區|鄉|鎮|市))?)"
)

SERVICE_AVAILABILITY_SERVICE_TERMS = (
    "寬頻",
    "網路",
    "上網",
    "有線電視",
    "第四台",
    "電視",
    "裝機",
)


def get_line_bot_config(bot_code: str | None) -> Dict[str, Any]:
    normalized = (bot_code or "top").strip().lower()
    return LINE_BOT_CONFIGS.get(normalized) or LINE_BOT_CONFIGS.get("top") or {
        "bot_code": normalized,
        "display_name": normalized,
        "default_tv_cable": "",
        "default_area": "",
        "channel_access_token": "",
        "channel_secret": "",
        "human_group_id": "",
        "human_access_token": "",
    }


def normalize_channel_user_id(channel: str, user_id: str) -> str:
    channel_name = (channel or "web").strip().lower()
    raw_user_id = (user_id or "").strip()
    if not raw_user_id:
        return f"{channel_name}:anonymous"
    if raw_user_id.startswith(f"{channel_name}:"):
        return raw_user_id
    return f"{channel_name}:{raw_user_id}"


def build_line_customer_key(line_user_id: str | None) -> Optional[str]:
    raw_user_id = (line_user_id or "").strip()
    if not raw_user_id or raw_user_id == "unknown":
        return None
    if raw_user_id.startswith("line:"):
        return raw_user_id
    return f"line:{raw_user_id}"


def get_customer_profile(customer_key: str | None) -> Optional[Dict[str, Any]]:
    return load_customer_profile(customer_key)


def save_customer_profile_from_memory(
    customer_key: str | None,
    user_id: str | None,
    bot_config: Optional[Dict[str, Any]],
    memory: Dict[str, Any],
) -> None:
    if not customer_key or not memory.get("company_code"):
        return

    channel_context = memory.get("channel_context", {})
    if channel_context.get("company_confirmed") is not True:
        return

    now = _now_taipei().isoformat()
    save_customer_profile({
        "customer_key": customer_key,
        "last_company_code": memory.get("company_code"),
        "last_company": memory.get("company"),
        "last_area": channel_context.get("area"),
        "last_user_id": user_id,
        "last_line_bot_code": (bot_config or {}).get("bot_code") or channel_context.get("line_bot_code"),
        "resolution_source": channel_context.get("resolution_source"),
        "updated_at": now,
    })


def build_company_prompt() -> str:
    return (
        "請問您位於哪一個服務地區呢？"
        "可以回覆居住行政區或附近地標，例如：沙鹿區、西屯區、清水區、北屯區、大甲區。"
        "如果您知道系統台名稱，也可以直接告訴我。"
    )


def _now_taipei() -> datetime:
    return datetime.now(timezone(timedelta(hours=8)))


def _parse_iso_datetime(value: Any) -> Optional[datetime]:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value))
    except Exception:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone(timedelta(hours=8)))
    return parsed


def activate_human_mode(
    memory: Dict[str, Any],
    bot_config: Optional[Dict[str, Any]] = None,
    now: Optional[datetime] = None,
) -> Dict[str, Any]:
    now = now or _now_taipei()
    until = now + timedelta(seconds=LINE_HUMAN_MODE_TIMEOUT_SECONDS)
    channel_context = memory.setdefault("channel_context", {})
    channel_context.update({
        "channel": "line",
        "line_bot_code": (bot_config or {}).get("bot_code"),
        "line_bot_name": (bot_config or {}).get("display_name"),
        "human_mode": True,
        "human_mode_started_at": now.isoformat(),
        "human_mode_last_activity_at": now.isoformat(),
        "human_mode_until": until.isoformat(),
    })
    return memory


def deactivate_human_mode(memory: Dict[str, Any]) -> Dict[str, Any]:
    channel_context = memory.setdefault("channel_context", {})
    channel_context["human_mode"] = False
    channel_context["human_mode_until"] = None
    channel_context["human_mode_last_activity_at"] = None
    return memory


def is_human_mode_active(
    memory: Dict[str, Any],
    now: Optional[datetime] = None,
) -> bool:
    channel_context = memory.setdefault("channel_context", {})
    if not channel_context.get("human_mode"):
        return False

    now = now or _now_taipei()
    until = _parse_iso_datetime(channel_context.get("human_mode_until"))
    if until and now >= until:
        deactivate_human_mode(memory)
        return False

    next_until = now + timedelta(seconds=LINE_HUMAN_MODE_TIMEOUT_SECONDS)
    channel_context["human_mode_last_activity_at"] = now.isoformat()
    channel_context["human_mode_until"] = next_until.isoformat()
    return True


def _profile_to_code(profile_class: str) -> str:
    for code, class_name in TV_DICT.items():
        if class_name == profile_class:
            return code
    return DEFAULT_TV_CABLE


def area_aliases(area: str) -> list[str]:
    value = (area or "").strip()
    if not value:
        return []

    aliases = [value]
    if value[-1:] in {"區", "市", "鄉", "鎮"}:
        base = value[:-1].strip()
        if len(base) >= 2:
            aliases.append(base)
    return aliases


def is_service_availability_query(text: str) -> bool:
    value = (text or "").strip()
    if not value:
        return False

    has_service = any(term in value for term in SERVICE_AVAILABILITY_SERVICE_TERMS)
    has_location = bool(detect_company_mentions(value)) or any(term in value for term in GENERIC_LOCATION_QUERY_TERMS)
    asks_availability = any(term in value for term in (
        "能申辦",
        "可以申辦",
        "可申辦",
        "能裝",
        "可以裝",
        "可裝",
        "能安裝",
        "可以安裝",
        "可安裝",
        "裝得到",
        "有服務到",
        "服務到",
        "服務區",
        "服務範圍",
    ))
    if (
        any(term in value for term in SERVICE_AVAILABILITY_ACTION_TERMS)
        and has_service
        and (has_location or asks_availability)
    ):
        return True

    # "沙鹿區可以申請網路裝機嗎" is primarily asking whether that
    # location can be served.  Keep the explicit location ahead of generic
    # new-install plan replies.
    has_install_application = (
        any(term in value for term in ("申請", "辦理", "申告"))
        and any(term in value for term in ("裝機", "安裝", "申裝"))
    )
    return has_service and has_install_application and has_location


def detect_company_mentions(text: str) -> List[CompanyResolution]:
    """Return every explicitly mentioned company or service area in text order."""
    value = (text or "").strip()
    normalized = value.lower()
    if not normalized:
        return []

    matches: List[CompanyResolution] = []
    seen: set[tuple[str, Optional[str], int]] = set()

    for option in get_company_options():
        names = {
            str(option.get("code") or "").strip(),
            str(option.get("class") or "").strip(),
            str(option.get("company_name") or "").strip(),
        }
        for name in sorted((item for item in names if item), key=len, reverse=True):
            start = _find_identifier_start(normalized, name)
            if start < 0:
                continue
            key = (option["code"], None, start)
            if key in seen:
                continue
            seen.add(key)
            matches.append(CompanyResolution(
                company_code=option["code"],
                company_name=option["company_name"],
                source="company_name",
                matched_text=value[start:start + len(name)],
                match_start=start,
            ))
            break

    for profile in get_all_company_profiles():
        code = _profile_to_code(profile["class"])
        service_area = profile.get("service_area", "")
        for area in [item.strip() for item in service_area.split("、") if item.strip()]:
            found_alias = None
            found_start = -1
            for alias in sorted(area_aliases(area), key=len, reverse=True):
                start = value.find(alias)
                if start >= 0 and (found_start < 0 or start < found_start):
                    found_alias = alias
                    found_start = start
            if found_start < 0:
                continue
            key = (code, area, found_start)
            if key in seen:
                continue
            seen.add(key)
            matches.append(CompanyResolution(
                company_code=code,
                company_name=profile["company_name"],
                area=area,
                source="service_area",
                matched_text=found_alias,
                match_start=found_start,
            ))

    matches.sort(key=lambda item: (item.match_start, -(len(item.matched_text or ""))))
    return matches


def resolve_service_availability_target(text: str) -> Dict[str, Any]:
    mentions = detect_company_mentions(text)
    if not mentions:
        value = (text or "").strip()
        if not any(term in value for term in GENERIC_LOCATION_QUERY_TERMS):
            location_match = COUNTY_CITY_LOCATION_PATTERN.search(value)
            if location_match:
                location = location_match.group("location")
                return {
                    "status": "unmapped",
                    "location": location,
                    "candidates": [],
                }
        return {"status": "missing", "candidates": []}

    unique: List[CompanyResolution] = []
    seen_targets: set[tuple[str, Optional[str]]] = set()
    for mention in mentions:
        key = (mention.company_code, mention.area)
        if key in seen_targets:
            continue
        seen_targets.add(key)
        unique.append(mention)

    # A company name followed by one of its service areas describes one target,
    # for example "新永安永康區". Prefer the area-specific mention so it is not
    # mistaken for two different installation locations.
    area_specific_codes = {item.company_code for item in unique if item.area}
    unique = [
        item
        for item in unique
        if item.area or item.company_code not in area_specific_codes
    ]

    # In phrases such as "我住大里，想幫永康的爸媽問能不能裝網路",
    # the location after 幫/替 is the installation destination, not the caller's home.
    helper_markers = [text.rfind(marker) for marker in ("幫", "替")]
    helper_start = max(helper_markers)
    if helper_start >= 0:
        assisted_targets = [item for item in unique if item.match_start > helper_start]
        if len(assisted_targets) == 1:
            unique = assisted_targets

    # "朋友住大里，那邊可以裝嗎" refers to the last location before the deixis.
    if len(unique) > 1 and any(term in text for term in ("那邊", "那裡", "該地區")):
        unique = [unique[-1]]

    candidates = [
        {
            "company_code": item.company_code,
            "company_name": item.company_name,
            "area": item.area,
            "matched_text": item.matched_text,
        }
        for item in unique
    ]
    if len(candidates) > 1:
        return {"status": "ambiguous", "candidates": candidates}
    return {"status": "resolved", "target": candidates[0], "candidates": candidates}


def detect_company_from_text(text: str) -> Optional[CompanyResolution]:
    normalized = (text or "").strip().lower()
    if not normalized:
        return None

    for option in get_company_options():
        code = option["code"]
        class_name = option["class"]
        company_name = option["company_name"]
        identifiers = (company_name, class_name, code)
        matched = [
            (start, identifier)
            for identifier in identifiers
            if (start := _find_identifier_start(normalized, identifier)) >= 0
        ]
        if matched:
            match_start, matched_text = min(matched, key=lambda item: item[0])
            return CompanyResolution(
                company_code=code,
                company_name=company_name,
                source="company_name",
                matched_text=matched_text,
                match_start=match_start,
            )

    for profile in get_all_company_profiles():
        service_area = profile.get("service_area", "")
        for area in [item.strip() for item in service_area.split("、") if item.strip()]:
            if any(alias and alias in text for alias in area_aliases(area)):
                return CompanyResolution(
                    company_code=_profile_to_code(profile["class"]),
                    company_name=profile["company_name"],
                    area=area,
                    source="service_area",
                    matched_text=next(
                        alias for alias in area_aliases(area) if alias and alias in text
                    ),
                    match_start=min(
                        text.find(alias) for alias in area_aliases(area) if alias and alias in text
                    ),
                )

    return None


def apply_web_channel_context(
    memory: Dict[str, Any],
    tv_cable: str,
    user_text: str = "",
    channel: str = "web",
) -> Dict[str, Any]:
    selected = apply_company_to_memory({}, tv_cable or DEFAULT_TV_CABLE)
    selected_code = str(selected.get("company_code") or "")
    previous_context = dict(memory.get("channel_context") or {})
    previous_selected_code = str(previous_context.get("web_selected_company_code") or "")
    override_code = str(previous_context.get("conversation_company_override_code") or "")

    # A deliberate sidebar change starts a new company scope.
    if previous_selected_code and previous_selected_code != selected_code:
        override_code = ""

    availability_query = is_service_availability_query(user_text)
    if availability_query:
        memory["service_availability_context"] = resolve_service_availability_target(user_text)
        target_code = override_code or selected_code
        resolution_source = "web_conversation_override" if override_code else "web_request"
    else:
        memory.pop("service_availability_context", None)
        resolution = detect_company_from_text(user_text)
        if resolution:
            target_code = resolution.company_code
            override_code = resolution.company_code
            resolution_source = resolution.source
        elif override_code:
            target_code = override_code
            resolution_source = "web_conversation_override"
        else:
            target_code = selected_code
            resolution_source = "web_request"

    memory = apply_company_to_memory(memory, target_code or selected_code or DEFAULT_TV_CABLE)
    channel_context = memory.setdefault("channel_context", {})
    channel_context.update({
        "channel": channel,
        "company_confirmed": True,
        "area": None,
        "resolution_source": resolution_source,
        "web_selected_company_code": selected_code,
        "conversation_company_override_code": override_code or None,
    })
    return memory


def apply_line_channel_context(
    memory: Dict[str, Any],
    user_text: str,
    bot_config: Optional[Dict[str, Any]] = None,
    customer_key: Optional[str] = None,
    user_id: Optional[str] = None,
) -> tuple[Dict[str, Any], Optional[str]]:
    bot_config = bot_config or get_line_bot_config(None)
    channel_context = memory.setdefault("channel_context", {})
    channel_context["channel"] = "line"
    channel_context["line_bot_code"] = bot_config.get("bot_code")
    channel_context["line_bot_name"] = bot_config.get("display_name")
    if customer_key:
        memory["customer_key"] = customer_key
        channel_context["customer_key"] = customer_key

    availability_query = is_service_availability_query(user_text)
    if availability_query:
        memory["service_availability_context"] = resolve_service_availability_target(user_text)
        resolution = None
    else:
        memory.pop("service_availability_context", None)
        resolution = detect_company_from_text(user_text)
    if resolution:
        memory = apply_company_to_memory(memory, resolution.company_code)
        channel_context = memory.setdefault("channel_context", {})
        channel_context.update({
            "channel": "line",
            "line_bot_code": bot_config.get("bot_code"),
            "line_bot_name": bot_config.get("display_name"),
            "customer_key": customer_key,
            "company_confirmed": True,
            "area": resolution.area,
            "resolution_source": resolution.source,
        })
        save_customer_profile_from_memory(customer_key, user_id, bot_config, memory)
        return memory, None

    profile = get_customer_profile(customer_key)
    if profile and profile.get("last_company_code"):
        memory = apply_company_to_memory(memory, profile["last_company_code"])
        channel_context = memory.setdefault("channel_context", {})
        channel_context.update({
            "channel": "line",
            "line_bot_code": bot_config.get("bot_code"),
            "line_bot_name": bot_config.get("display_name"),
            "customer_key": customer_key,
            "company_confirmed": True,
            "area": profile.get("last_area"),
            "resolution_source": "customer_profile",
        })
        return memory, None

    if channel_context.get("company_confirmed") and memory.get("company_code"):
        memory = apply_company_to_memory(memory, memory.get("company_code"))
        save_customer_profile_from_memory(customer_key, user_id, bot_config, memory)
        return memory, None

    default_tv_cable = (bot_config.get("default_tv_cable") or "").strip()
    if default_tv_cable:
        memory = apply_company_to_memory(memory, default_tv_cable)
        channel_context = memory.setdefault("channel_context", {})
        channel_context.update({
            "channel": "line",
            "line_bot_code": bot_config.get("bot_code"),
            "line_bot_name": bot_config.get("display_name"),
            "customer_key": customer_key,
            "company_confirmed": True,
            "area": bot_config.get("default_area") or None,
            "resolution_source": "line_bot_config",
        })
        save_customer_profile_from_memory(customer_key, user_id, bot_config, memory)
        return memory, None

    channel_context["company_confirmed"] = False
    if availability_query:
        return memory, None
    return memory, build_company_prompt()


def validate_line_signature(
    body: bytes,
    signature: str | None,
    bot_config: Optional[Dict[str, Any]] = None,
) -> bool:
    channel_secret = (bot_config or {}).get("channel_secret", "")
    if not channel_secret:
        return True
    if not signature:
        return False

    digest = hmac.new(
        channel_secret.encode("utf-8"),
        body,
        hashlib.sha256,
    ).digest()
    expected = base64.b64encode(digest).decode("utf-8")
    return hmac.compare_digest(expected, signature)


def extract_line_message(event: Dict[str, Any]) -> Dict[str, Any]:
    source = event.get("source") or {}
    message = event.get("message") or {}
    message_type = message.get("type")

    if event.get("type") != "message":
        return {
            "supported": False,
            "reason": "unsupported_event",
            "user_id": source.get("userId", "unknown"),
            "reply_token": event.get("replyToken"),
            "text": "",
            "message_type": event.get("type"),
        }

    if message_type == "text":
        return {
            "supported": True,
            "user_id": source.get("userId", "unknown"),
            "reply_token": event.get("replyToken"),
            "text": message.get("text", ""),
            "message_type": "text",
            "message_id": message.get("id"),
        }

    if message_type == "image":
        return {
            "supported": True,
            "user_id": source.get("userId", "unknown"),
            "reply_token": event.get("replyToken"),
            "text": "",
            "message_type": "image",
            "message_id": message.get("id"),
        }

    return {
        "supported": False,
        "reason": "unsupported_message",
        "user_id": source.get("userId", "unknown"),
        "reply_token": event.get("replyToken"),
        "text": "",
        "message_type": message_type,
        "message_id": message.get("id"),
    }


def get_line_message_content(
    message_id: str | None,
    bot_config: Optional[Dict[str, Any]] = None,
) -> tuple[bytes, str]:
    channel_access_token = (bot_config or {}).get("channel_access_token", "")
    if not channel_access_token:
        raise RuntimeError("LINE channel access token 尚未設定。")
    if not message_id:
        raise RuntimeError("LINE image message id 不存在。")

    response = requests.get(
        f"https://api-data.line.me/v2/bot/message/{message_id}/content",
        headers={"Authorization": f"Bearer {channel_access_token}"},
        timeout=30,
    )
    if response.status_code != 200:
        raise RuntimeError(f"LINE 圖片下載失敗：{response.status_code} {response.text}")

    return response.content, response.headers.get("Content-Type", "")


def push_line_message(
    to: str | None,
    text: str,
    bot_config: Optional[Dict[str, Any]] = None,
    use_human_token: bool = False,
) -> bool:
    bot_config = bot_config or {}
    channel_access_token = (
        bot_config.get("human_access_token")
        if use_human_token
        else bot_config.get("channel_access_token")
    ) or bot_config.get("channel_access_token", "")
    if not channel_access_token or not to or not text:
        return False

    response = requests.post(
        "https://api.line.me/v2/bot/message/push",
        headers={
            "Authorization": f"Bearer {channel_access_token}",
            "Content-Type": "application/json",
        },
        json={
            "to": to,
            "messages": [{"type": "text", "text": text}],
        },
        timeout=15,
    )
    return response.status_code == 200


def format_reply_for_line(text: str, company_code: Optional[str] = None) -> str:
    value = html.unescape(str(text or ""))
    link_icon = "\U0001f517"
    profile = get_company_profile(company_code or DEFAULT_TV_CABLE)

    def clean_label(raw_label: str) -> str:
        return re.sub(r"\s+", " ", raw_label.replace(link_icon, "")).strip()

    def line_link(label: str, url: str) -> str:
        cleaned_label = clean_label(label)
        cleaned_url = html.unescape(str(url or "")).strip().rstrip("。．,，；;")
        if not cleaned_label or not cleaned_url:
            return ""
        return f"\n[{cleaned_label}]\n{cleaned_url}\n"

    value = re.sub(
        rf"[［【\[]\s*(?P<label>[^］】\]]*?)\s*{link_icon}?\s*[］】\]]\s*(?P<url>https?://[^\s，。；、]+)",
        lambda match: line_link(match.group("label"), match.group("url")),
        value,
    )

    known_links = dict(extract_company_links(profile))
    if "LINE TV客服中心" in known_links:
        known_links.setdefault("LINE TV官方客服中心", known_links["LINE TV客服中心"])
    for label, url in known_links.items():
        if not url:
            continue
        value = re.sub(
            rf"[［【\[]\s*{re.escape(label)}\s*{link_icon}?\s*[］】\]](?!\s*https?://)",
            lambda _match, link_label=label, link_url=url: line_link(link_label, link_url),
            value,
        )

    value = re.sub(
        r"<a\b[^>]*href=[\"'](?P<url>[^\"']+)[\"'][^>]*>(?P<label>.*?)</a>",
        lambda match: line_link(
            re.sub(r"<[^>]+>", "", match.group("label")),
            match.group("url"),
        ),
        value,
        flags=re.IGNORECASE | re.DOTALL,
    )

    value = re.sub(r"[ \t]+\n", "\n", value)
    value = re.sub(r"\n[ \t]+", "\n", value)
    value = re.sub(r"\n{3,}", "\n\n", value)
    return value.strip()


def reply_line_message(
    reply_token: str | None,
    text: str,
    bot_config: Optional[Dict[str, Any]] = None,
) -> bool:
    channel_access_token = (bot_config or {}).get("channel_access_token", "")
    if not channel_access_token or not reply_token or not text:
        return False
    formatted_text = format_reply_for_line(text, (bot_config or {}).get("default_tv_cable"))

    response = requests.post(
        "https://api.line.me/v2/bot/message/reply",
        headers={
            "Authorization": f"Bearer {channel_access_token}",
            "Content-Type": "application/json",
        },
        json={
            "replyToken": reply_token,
            "messages": [{"type": "text", "text": formatted_text}],
        },
        timeout=15,
    )
    return response.status_code == 200
