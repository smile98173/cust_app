from typing import Dict, Any, List, Optional
import json
import re

from langchain_core.prompts import ChatPromptTemplate

from app.services.controller_service import (
    normalize_phone_value,
    parse_preferred_date,
    normalize_time_range,
)
from app.config.settings import BAD_NAME_VALUES
from app.config.slot_prompts import SLOT_EXTRACTOR_RULES
from app.services.customer_validation import (
    CONTRACT_LOOKUP_LOGIN_REQUIRED_REPLY,
    has_authenticated_web_custnum,
    normalize_customer_number,
    validate_name,
)
from app.services.query_normalization import normalize_channel_name_from_query


INVALID_NAME_VALUES = {
    "好", "可以", "是", "ok", "OK",
    "你好", "您好",
    "查詢帳單", "查帳單", "我要查帳單", "我要查詢帳單",
    "補寄帳單", "補發帳單", "恢復網路", "恢復電視",
    "電視不能看", "家裡電視不能看", "不能看",
    "網路不能用", "不能上網",
    "有亮燈", "亮燈", "沒亮燈", "紅燈", "無訊號",
    "找真人", "找真人客服", "轉真人", "轉真人客服",
    "人工客服", "轉人工", "轉人工客服",
}
INVALID_NAME_VALUES.update(BAD_NAME_VALUES)


TROUBLESHOOTING_STATUS_NAME_BLOCKLIST = {
    "一樣",
    "還是一樣",
    "依樣",
    "還是不行",
    "還是不能",
    "還是沒用",
    "不行",
    "不能",
    "沒用",
    "沒有用",
    "沒改善",
    "沒有改善",
    "沒恢復",
    "沒有恢復",
    "無法恢復",
    "沒好",
    "還沒好",
    "一樣沒好",
    "一樣不行",
    "一樣不能",
}

TROUBLESHOOTING_STATUS_NAME_KEYWORDS = (
    "還是不行",
    "還是不能",
    "一樣",
    "沒改善",
    "沒有改善",
    "沒恢復",
    "沒有恢復",
    "沒用",
    "沒有用",
)

NON_PERSON_NAME_KEYWORDS = (
    "出現",
    "系統",
    "繁忙",
    "忙碌",
    "錯誤",
    "失敗",
    "成功",
    "異常",
    "無法",
    "不能",
    "不會",
    "目前",
    "本期",
    "金額",
    "資料",
    "資訊",
    "提供",
    "重新",
    "輸入",
    "確認",
    "查不到",
    "查詢不到",
    "回覆",
    "客服",
    "客戶",
    "編號",
    "客編",
)

EXPLICIT_NAME_SIGNALS = (
    "聯絡人",
    "姓名",
    "名字",
    "我叫",
    "我是",
)


TOOL_SLOT_SCHEMA = {
    "search_bill": {
        "required": ["identity_pair"],
        "labels": {
            "identity_pair": "客戶編號、戶名、登記電話任兩項",
            "name": "戶名",
            "phone": "聯絡電話",
            "custnum": "客戶編號",
        },
    },
    "send_message": {
        "required": ["name", "phone"],
        "labels": {
            "name": "戶名",
            "phone": "聯絡電話",
            "custnum": "客戶編號",
        },
    },
    "payment_bill_batch": {
        "required": ["receipt_image_evidence"],
        "labels": {
            "receipt_image_evidence": "超商繳費收據圖片",
        },
    },
    "bill_return_line_internet": {
        "required": ["identity_pair"],
        "labels": {
            "identity_pair": "客戶編號、戶名、登記電話任兩項",
            "name": "戶名",
            "phone": "聯絡電話",
            "custnum": "客戶編號",
        },
    },
    "bill_return_line_tv": {
        "required": ["identity_pair"],
        "labels": {
            "identity_pair": "客戶編號、戶名、登記電話任兩項",
            "name": "戶名",
            "phone": "聯絡電話",
            "custnum": "客戶編號",
        },
    },
    "create_repair_ticket": {
        "required": [
            "contact_name",
            "contact_phone",
            "service_address",
            "issue_description",
            "preferred_date",
            "preferred_time_range",
        ],
        "labels": {
            "contact_name": "聯絡人",
            "contact_phone": "聯絡電話",
            "service_address": "服務地址",
            "issue_description": "故障問題描述",
            "preferred_date": "預約日期",
            "preferred_time_range": "預約時段",
        },
    },
    "search_contract_info": {
        "required": ["authenticated_web_custnum"],
        "labels": {
            "custnum": "客戶編號",
            "authenticated_web_custnum": "登入會員",
        },
    },
    "search_channel_no": {
        "required": ["channel_name"],
        "labels": {
            "channel_name": "頻道名稱",
        },
    },
    "search_service_availability": {
        "required": ["service_address"],
        "labels": {
            "service_address": "服務地址或鄉鎮市區",
            "install_service": "申辦服務",
        },
    },
    "apply_new_install": {
        "required": [
            "contact_name",
            "contact_phone",
            "service_address",
            "install_service",
        ],
        "labels": {
            "contact_name": "聯絡人",
            "contact_phone": "聯絡電話",
            "service_address": "服務地址",
            "install_service": "申辦服務",
            "desired_plan": "希望方案",
        },
    },
    "search_addon_plans": {
        "required": ["service_area", "addon_name"],
        "labels": {
            "service_area": "服務地區",
            "addon_name": "加值服務名稱",
        },
    },
    "cancel_repair_ticket": {
        "required": ["repair_ticket_id", "contact_phone"],
        "labels": {
            "repair_ticket_id": "報修單號",
            "contact_phone": "聯絡電話",
        },
    },
}


def safe_json_loads(text: str) -> Dict[str, Any]:
    if not text:
        return {}

    cleaned = text.strip().replace("```json", "").replace("```", "").strip()
    start = cleaned.find("{")
    end = cleaned.rfind("}")

    if start != -1 and end != -1 and end > start:
        cleaned = cleaned[start:end + 1]

    try:
        data = json.loads(cleaned)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def get_tool_required_slots(tool_name: str) -> List[str]:
    return TOOL_SLOT_SCHEMA.get(tool_name, {}).get("required", [])


def get_tool_slot_labels(tool_name: str) -> Dict[str, str]:
    return TOOL_SLOT_SCHEMA.get(tool_name, {}).get("labels", {})


def is_valid_person_name(text: str) -> bool:
    text = (text or "").strip()
    compact_text = text.replace(" ", "").replace("　", "")

    if not text:
        return False

    # ❌ 明確排除
    INVALID = {
        "有", "沒有", "好", "可以", "是", "不是",
        "ok", "OK",
        "你好", "您好",
        "都有插好", "都插好", "插好了", "有插好",
        "可以派人嗎", "派人", "請派人",
        "電視不能看", "不能看",
        "不想看了", "不看了", "不要看了",
        "網路不能用", "不能上網",
        "有亮燈", "沒亮燈",
        "一樣", "還是一樣", "依樣",
        "還是不行", "還是不能", "不行", "不能",
        "沒改善", "沒有改善", "沒恢復", "沒有恢復",
        "沒用", "沒有用", "沒好", "還沒好",
    }
    if (
            text in INVALID
            or text in INVALID_NAME_VALUES
            or compact_text in TROUBLESHOOTING_STATUS_NAME_BLOCKLIST
    ):
        return False

    if any(keyword in compact_text for keyword in TROUBLESHOOTING_STATUS_NAME_KEYWORDS):
        return False

    # ❌ 有數字
    if any(c.isdigit() for c in text):
        return False

    # ❌ 故障/設備關鍵字
    BLOCKED = [
        "電視", "網路", "機上盒", "訊號", "畫面",
        "亮燈", "紅燈", "故障", "報修",
        "插好", "派人", "檢查", "排錯",
        "查詢", "查帳單", "帳單", "帳務", "繳費",
        "斷訊", "斷線", "復線", "欠費", "收看",
        "申請", "裝機", "移機", "退租", "解約",
        "客服", "真人客服", "合約", "密碼", "方案",
        "網速", "頻道", "加購", "上傳圖片",
        "恢復", "改善", "不行", "不能", "沒用", "一樣",
        *NON_PERSON_NAME_KEYWORDS,
    ]
    if any(k in text for k in BLOCKED):
        return False

    return validate_name(text)


def is_slot_requested(memory: Dict[str, Any], slot_name: str, tool_name: str) -> bool:
    if memory.get("pending_tool") != tool_name:
        return False
    pending_args = memory.get("pending_tool_args") or []
    return slot_name in pending_args


def has_explicit_name_signal(text: str) -> bool:
    return any(signal in (text or "") for signal in EXPLICIT_NAME_SIGNALS)


def extract_explicit_person_name(text: str) -> Optional[str]:
    value = (text or "").strip()
    if not value:
        return None

    pattern = (
        r"(?:聯絡人|姓名|名字|我叫|我是)"
        r"\s*(?:是|為)?\s*[:：]?\s*"
        r"(?P<name>[\u4e00-\u9fffA-Za-z .·]{2,20}?)"
        r"(?=\s*(?:聯絡電話|電話|手機|地址|$|[0-9]))"
    )
    match = re.search(pattern, value)
    if not match:
        return None

    name = match.group("name").strip()
    return name if is_valid_person_name(name) else None


def extract_service_area(text: str) -> Optional[str]:
    value = (text or "").strip()
    area_terms = [
        "彰化縣和美鎮",
        "彰化和美",
        "和美鎮",
        "台中市大里區",
        "台中大里",
        "大里區",
        "太平區",
        "烏日區",
        "霧峰區",
        "台中",
        "大屯",
    ]
    for term in area_terms:
        if term in value:
            return term
    return None


def extract_install_service(text: str) -> Optional[str]:
    value = (text or "").strip()
    if any(term in value for term in ["網路", "寬頻", "上網"]):
        return "寬頻上網"
    if any(term in value for term in ["有線電視", "第四台", "電視"]):
        return "有線電視"
    return None


def extract_channel_name(text: str) -> Optional[str]:
    return normalize_channel_name_from_query(text)


def extract_addon_name(text: str) -> Optional[str]:
    value = (text or "").strip()
    if "line tv" in value.lower():
        return "LINE TV"
    if "哈tv" in value.lower() or "哈TV" in value:
        return "哈TV"
    if "hbo" in value.lower():
        return "HBO GO"
    return None


def extract_desired_plan(text: str) -> Optional[str]:
    value = (text or "").strip()
    if "有線電視加網路" in value or "電視加網路" in value:
        return "有線電視加網路"
    match = re.search(r"\d+\s*[mM]", value)
    if match:
        return match.group(0).replace(" ", "").upper()
    return None


def extract_repair_ticket_id(text: str) -> Optional[str]:
    value = (text or "").strip()
    match = re.search(r"(NT\d{8}-[A-Za-z0-9]{6}|MOCK-[A-Za-z0-9-]+)", value)
    return match.group(1).upper() if match else None


def extract_receipt_barcodes(text: str) -> Dict[str, Any]:
    value = text or ""
    label_aliases = {
        "一": "first_barcode",
        "1": "first_barcode",
        "二": "second_barcode",
        "2": "second_barcode",
        "三": "third_barcode",
        "3": "third_barcode",
    }
    labeled_bills = []
    current_bill: Dict[str, str] = {}
    labeled_barcode_pattern = (
        r"第\s*([一二三123])\s*段(?:\s*條碼)?\s*[:：]?\s*"
        r"([A-Za-z0-9][A-Za-z0-9\-]{5,})"
    )
    for match in re.finditer(
        labeled_barcode_pattern,
        value,
        flags=re.IGNORECASE,
    ):
        key = label_aliases.get(match.group(1))
        if not key:
            continue
        if key == "first_barcode" and all(
            current_bill.get(item)
            for item in ["first_barcode", "second_barcode", "third_barcode"]
        ):
            labeled_bills.append(current_bill)
            current_bill = {}
        current_bill[key] = match.group(2).strip()

    if all(current_bill.get(item) for item in ["first_barcode", "second_barcode", "third_barcode"]):
        labeled_bills.append(current_bill)

    if len(labeled_bills) > 1:
        first_bill = labeled_bills[0]
        return {
            "bills": labeled_bills,
            "first_barcode": first_bill["first_barcode"],
            "second_barcode": first_bill["second_barcode"],
            "third_barcode": first_bill["third_barcode"],
        }
    if len(labeled_bills) == 1:
        return labeled_bills[0]

    patterns = {
        "first_barcode": r"第\s*[一1]\s*段(?:\s*條碼)?\s*[:：]?\s*([A-Za-z0-9][A-Za-z0-9\-]{5,})",
        "second_barcode": r"第\s*[二2]\s*段(?:\s*條碼)?\s*[:：]?\s*([A-Za-z0-9][A-Za-z0-9\-]{5,})",
        "third_barcode": r"第\s*[三3]\s*段(?:\s*條碼)?\s*[:：]?\s*([A-Za-z0-9][A-Za-z0-9\-]{5,})",
    }
    result: Dict[str, str] = {}
    for key, pattern in patterns.items():
        match = re.search(pattern, value, flags=re.IGNORECASE)
        if match:
            result[key] = match.group(1).strip()

    if len(result) == 3:
        return result

    lines = [line.strip() for line in value.splitlines() if line.strip()]
    candidates = []
    for line in lines:
        if "條碼" not in line:
            continue
        pieces = re.findall(r"[A-Za-z0-9][A-Za-z0-9\-]{5,}", line)
        if pieces:
            candidates.append(pieces[-1])

    if len(candidates) >= 6:
        bills = []
        for start in range(0, len(candidates) - 2, 3):
            bills.append({
                "first_barcode": candidates[start],
                "second_barcode": candidates[start + 1],
                "third_barcode": candidates[start + 2],
            })
        first_bill = bills[0]
        return {
            "bills": bills,
            "first_barcode": first_bill["first_barcode"],
            "second_barcode": first_bill["second_barcode"],
            "third_barcode": first_bill["third_barcode"],
        }

    if len(candidates) >= 3:
        return {
            "first_barcode": candidates[0],
            "second_barcode": candidates[1],
            "third_barcode": candidates[2],
        }

    return result


def extract_phone_from_text(text: str) -> Optional[str]:
    value = (text or "").strip()
    match = re.search(r"(09[\d\-\s]{8,12}|0[2-8][\d\-\s]{7,12})", value)
    if not match:
        return None
    return normalize_phone_value(match.group(1))


def extract_explicit_customer_number(text: str) -> Optional[str]:
    """Extract a customer number only when the user labels it explicitly."""
    value = (text or "").strip()
    if not value:
        return None

    patterns = [
        r"(?:客戶\s*編號|客編|客戶\s*號碼|客號)\s*(?:是|為)?\s*[:：]?\s*(\d{4,30})",
        r"(?:cust\s*(?:no|num|number)|custNo|custnum)\s*(?:is|=)?\s*[:：]?\s*(\d{4,30})",
        r"(?<!\d)(\d{4,30})\s*(?:客戶\s*編號|客編|客戶\s*號碼|客號)",
        r"(?<!\d)(\d{4,30})\s*(?:cust\s*(?:no|num|number)|custNo|custnum)",
    ]
    for pattern in patterns:
        match = re.search(pattern, value, flags=re.IGNORECASE)
        if match:
            return normalize_customer_number(match.group(1))

    return None


def extract_customer_number(text: str) -> Optional[str]:
    value = (text or "").strip()
    if not value:
        return None

    explicit = extract_explicit_customer_number(value)
    if explicit:
        return explicit

    compact = re.sub(r"\s+", "", value)
    if re.fullmatch(r"\d{4,30}", compact) and not normalize_phone_value(compact):
        return normalize_customer_number(compact)

    return None


def has_invalid_customer_number_format(text: str) -> bool:
    """Return whether text looks like a customer number but violates its format."""
    value = (text or "").strip()
    if not value or extract_customer_number(value):
        return False

    compact = re.sub(r"\s+", "", value)
    has_customer_number_cue = bool(
        re.search(r"客戶編號|客編|客戶號碼|客號|cust(?:no|num|number)", compact, re.IGNORECASE)
    )
    candidate = re.sub(
        r"^(?:客戶編號|客編|客戶號碼|客號|cust(?:no|num|number))(?:是|為|is|=|[:：])?",
        "",
        compact,
        flags=re.IGNORECASE,
    )

    if re.fullmatch(r"[+-]\d{4,30}", candidate):
        return True

    if re.fullmatch(r"0\d{3,29}", candidate):
        return bool(has_customer_number_cue or not normalize_phone_value(candidate))

    return bool(
        has_customer_number_cue
        and re.search(r"\d{4,30}", candidate)
        and not re.fullmatch(r"\d{4,30}", candidate)
    )


def remove_phone_like_text(text: str) -> str:
    return re.sub(r"(09[\d\-\s]{8,12}|0[2-8][\d\-\s]{7,12})", " ", text or "")


def extract_requested_person_name(text: str) -> Optional[str]:
    value = remove_phone_like_text(text)
    value = re.sub(r"(聯絡人|姓名|名字|戶名|電話|手機|是|為|[:：])", " ", value)
    value = re.sub(r"[，,、。；;／/()（）\[\]【】]", " ", value)

    for part in value.split():
        part = part.strip()
        if is_valid_person_name(part):
            return part

    compact = value.strip()
    return compact if is_valid_person_name(compact) else None


def validate_slot_fields(fields: Dict[str, Any]) -> Dict[str, Any]:
    out = dict(fields or {})

    contact_phone = out.get("contact_phone") or out.get("phone")
    if contact_phone is not None:
        out["contact_phone"] = normalize_phone_value(contact_phone)

    contact_name = out.get("contact_name") or out.get("name")
    if isinstance(contact_name, str):
        contact_name = contact_name.strip()
        out["contact_name"] = contact_name if is_valid_person_name(contact_name) else None

    name = out.get("name")
    if isinstance(name, str):
        name = name.strip()
        out["name"] = name if is_valid_person_name(name) else None

    phone = out.get("phone")
    if phone is not None:
        out["phone"] = normalize_phone_value(phone)

    custnum = out.get("custnum")
    if custnum is not None:
        out["custnum"] = normalize_customer_number(custnum)

    service_address = out.get("service_address")
    if isinstance(service_address, str):
        service_address = service_address.strip()
        out["service_address"] = service_address if service_address else None

    issue_description = out.get("issue_description")
    if isinstance(issue_description, str):
        issue_description = issue_description.strip()
        out["issue_description"] = issue_description if issue_description else None

    preferred_date = out.get("preferred_date")
    if preferred_date is not None:
        parsed = parse_preferred_date(str(preferred_date))
        out["preferred_date"] = parsed if parsed else None

    preferred_time_range = out.get("preferred_time_range")
    if preferred_time_range is not None:
        normalized = normalize_time_range(preferred_time_range)
        out["preferred_time_range"] = normalized if normalized in ["morning", "afternoon", "evening"] else None

    return out


def llm_extract_slots(user_text: str, tool_name: str, llm) -> Dict[str, Any]:
    # 短回覆通常是排錯回答，不應該讓 LLM 猜姓名或聯絡人
    if len((user_text or "").strip()) <= 3:
        return {}
    prompt = ChatPromptTemplate.from_template(
        "{rules}\n\n"
        "目前工具名稱：\n"
        "{tool_name}\n\n"
        "使用者最新訊息：\n"
        "{user_text}\n"
    )

    chain = prompt | llm
    resp = chain.invoke({
        "rules": SLOT_EXTRACTOR_RULES,
        "tool_name": tool_name,
        "user_text": user_text,
    })

    data = safe_json_loads(resp.content)
    validated = validate_slot_fields(data)

    result: Dict[str, Any] = {}

    if validated.get("contact_name"):
        result["contact_name"] = validated["contact_name"]

    if validated.get("contact_phone"):
        result["contact_phone"] = validated["contact_phone"]

    if validated.get("name"):
        result["name"] = validated["name"]

    if validated.get("phone"):
        result["phone"] = validated["phone"]

    if validated.get("custnum"):
        result["custnum"] = validated["custnum"]

    if validated.get("service_address"):
        result["service_address"] = validated["service_address"]

    if validated.get("issue_description"):
        result["issue_description"] = validated["issue_description"]

    if validated.get("preferred_date"):
        result["preferred_date"] = validated["preferred_date"]

    if validated.get("preferred_time_range"):
        result["preferred_time_range"] = validated["preferred_time_range"]

    return result


def rule_extract_slots_from_text(user_text: str, memory: Dict[str, Any], tool_name: str) -> Dict[str, Any]:
    text = (user_text or "").strip()
    known_info = memory.setdefault("known_info", {})
    extracted: Dict[str, Any] = {}

    phone = normalize_phone_value(text) or extract_phone_from_text(text)
    if phone:
        if tool_name in ["create_repair_ticket", "apply_new_install", "cancel_repair_ticket"]:
            extracted["contact_phone"] = phone
        else:
            extracted["phone"] = phone

    customer_number = extract_customer_number(text)
    if customer_number and tool_name in {
        "search_bill",
        "send_message",
        "bill_return_line_internet",
        "bill_return_line_tv",
        "search_contract_info",
    }:
        extracted["custnum"] = customer_number

    is_troubleshooting = known_info.get("troubleshooting_started") == "yes"
    contact_name_requested = is_slot_requested(memory, "contact_name", tool_name)
    name_requested = is_slot_requested(memory, "name", tool_name)
    explicit_name_signal = has_explicit_name_signal(text)
    explicit_name = extract_explicit_person_name(text)

    if explicit_name:
        if tool_name in ["create_repair_ticket", "apply_new_install"] and not known_info.get("contact_name"):
            extracted["contact_name"] = explicit_name
        elif tool_name not in ["create_repair_ticket", "apply_new_install", "cancel_repair_ticket"] and not known_info.get("name"):
            extracted["name"] = explicit_name

    if tool_name in ["create_repair_ticket", "apply_new_install"]:
        if (
                not is_troubleshooting
                and not phone
                and not known_info.get("contact_name")
                and not extracted.get("contact_name")
                and contact_name_requested
                and is_valid_person_name(text)
                and len(text.split()) <= 2
        ):
            extracted["contact_name"] = text
    elif tool_name != "cancel_repair_ticket":
        if (
                not is_troubleshooting
                and not phone
                and not known_info.get("name")
                and not extracted.get("name")
                and name_requested
                and is_valid_person_name(text)
        ):
            extracted["name"] = text

    if (
            not is_troubleshooting
            and not extracted.get("custnum")
            and not extracted.get("contact_name")
            and not extracted.get("name")
    ):
        requested_name = extract_requested_person_name(text)
        if requested_name:
            if (
                    tool_name in ["create_repair_ticket", "apply_new_install"]
                    and contact_name_requested
                    and not known_info.get("contact_name")
            ):
                extracted["contact_name"] = requested_name
            elif (
                    tool_name not in ["create_repair_ticket", "apply_new_install", "cancel_repair_ticket"]
                    and name_requested
                    and not known_info.get("name")
            ):
                extracted["name"] = requested_name

    can_extract_name_from_parts = (
        not is_troubleshooting
        and not extracted.get("custnum")
        and " " in text
        and (
            contact_name_requested
            or name_requested
            or explicit_name_signal
        )
    )

    if can_extract_name_from_parts:
        parts = text.split()
        for p in parts:
            p = p.strip()
            if is_valid_person_name(p):
                if (
                        tool_name in ["create_repair_ticket", "apply_new_install"]
                        and not known_info.get("contact_name")
                        and not extracted.get("contact_name")
                ):
                    extracted["contact_name"] = p
                elif (
                        tool_name not in ["create_repair_ticket", "apply_new_install", "cancel_repair_ticket"]
                        and not known_info.get("name")
                        and not extracted.get("name")
                ):
                    extracted["name"] = p
                break

    parsed_date = parse_preferred_date(text)
    if parsed_date:
        extracted["preferred_date"] = parsed_date

    normalized_time = normalize_time_range(text)
    if normalized_time in ["morning", "afternoon", "evening"]:
        extracted["preferred_time_range"] = normalized_time

    service_area = extract_service_area(text)
    if service_area:
        extracted["service_area"] = service_area

    install_service = extract_install_service(text)
    if install_service:
        extracted["install_service"] = install_service

    desired_plan = extract_desired_plan(text)
    if desired_plan:
        extracted["desired_plan"] = desired_plan

    if tool_name == "search_channel_no" and not known_info.get("channel_name"):
        channel_name = extract_channel_name(text)
        if channel_name and not extract_service_area(channel_name):
            extracted["channel_name"] = channel_name

    addon_name = extract_addon_name(text)
    if addon_name:
        extracted["addon_name"] = addon_name

    repair_ticket_id = extract_repair_ticket_id(text)
    if repair_ticket_id:
        extracted["repair_ticket_id"] = repair_ticket_id

    address_requested = is_slot_requested(memory, "service_address", tool_name)
    address_like = any(k in text for k in ["縣", "市", "區", "鎮", "鄉", "路", "街", "巷", "號"])
    if (
            tool_name in ["search_service_availability", "apply_new_install"]
            and not known_info.get("service_address")
            and not extracted.get("service_address")
            and (address_requested or address_like)
    ):
        extracted["service_address"] = text

    if tool_name == "create_repair_ticket":
        detail_keywords = [
            "無訊號", "無信號", "沒信號", "沒有信號", "沒有畫面", "黑畫面", "畫面異常", "畫面停住",
            "馬賽克", "機上盒紅燈", "亮紅燈", "錯誤代碼",
            "遙控器", "斷線", "閃爍", "燈號",
        ]
        if any(k in text for k in detail_keywords):
            extracted["issue_description"] = text

    return extracted


def extract_slots_from_text(user_text: str, memory: Dict[str, Any], tool_name: str, llm=None) -> Dict[str, Any]:
    llm_slots: Dict[str, Any] = {}

    if llm is not None:
        try:
            llm_slots = llm_extract_slots(user_text, tool_name, llm)
        except Exception:
            llm_slots = {}

    rule_slots = rule_extract_slots_from_text(user_text, memory, tool_name)

    merged = dict(rule_slots)
    for k, v in llm_slots.items():
        if v not in [None, ""] and k not in merged:
            merged[k] = v

    return merged


def merge_slots_into_memory(memory: Dict[str, Any], slots: Dict[str, Any]) -> Dict[str, Any]:
    known_info = memory.setdefault("known_info", {})
    recent_slot_status: Dict[str, str] = {}

    is_repair_flow = (
        memory.get("pending_tool") == "create_repair_ticket"
        or memory.get("pending_tool") == "apply_new_install"
        or memory.get("last_tool") == "create_repair_ticket"
        or memory.get("last_tool") == "apply_new_install"
        or known_info.get("repair_ready") == "yes"
    )

    for k, v in slots.items():
        if v is None or v == "":
            continue

        if k in {"phone", "contact_phone"}:
            v = normalize_phone_value(v)
            if not v:
                continue
        elif k == "custnum":
            v = normalize_customer_number(v)
            if not v:
                continue

        # 報修流程只使用 contact_name/contact_phone，不使用舊欄位
        if is_repair_flow and k in ["name", "phone", "customer_name"]:
            continue

        # 最後防線：避免姓名污染
        if k in ["contact_name", "name"]:
            text_v = str(v).strip()

            if len(text_v) <= 1:
                continue

            if any(x in text_v for x in [
                "插好", "派人", "排錯", "檢查", "可以", "不用", "沒事",
                "亮燈", "無訊號", "無信號", "畫面", "電視", "網路", "報修"
            ]):
                continue

            if not is_valid_person_name(text_v):
                continue

        previous_value = known_info.get(k)
        if previous_value in [None, ""]:
            recent_slot_status[k] = "received"
        elif str(previous_value).strip() == str(v).strip():
            recent_slot_status[k] = "unchanged"
        else:
            recent_slot_status[k] = "updated"
        known_info[k] = v

    memory["_recent_slot_status"] = recent_slot_status

    memory["known_info"] = known_info
    return memory


def is_issue_description_sufficient(value: Any) -> bool:
    if not value:
        return False

    text = str(value).strip()

    too_generic = {
        "電視不能看",
        "家裡電視不能看",
        "不能看",
        "網路不能用",
        "不能上網",
        "故障",
        "壞了",
    }

    if text in too_generic:
        return False

    detail_keywords = [
        "無訊號", "無信號", "沒信號", "沒有信號", "沒有畫面", "黑畫面", "畫面停住", "畫面異常",
        "馬賽克", "機上盒紅燈", "亮紅燈", "錯誤代碼",
        "遙控器", "斷線", "閃爍", "燈號",
    ]

    return any(k in text for k in detail_keywords) or len(text) >= 12


def get_missing_slots(tool_name: str, memory: Dict[str, Any]) -> List[str]:
    required = get_tool_required_slots(tool_name)
    known_info = memory.get("known_info", {})

    # Contract data is never verified from chat-entered identity fields. Only
    # an authenticated website session may authorize this lookup.
    if tool_name == "search_contract_info":
        custnum = normalize_customer_number(known_info.get("custnum"))
        if custnum:
            known_info["custnum"] = custnum
        return [] if has_authenticated_web_custnum(memory) else ["authenticated_web_custnum"]

    if tool_name == "payment_bill_batch":
        evidence = known_info.get("receipt_image_evidence")
        if isinstance(evidence, dict) and evidence.get("verified"):
            return []

    if tool_name in [
        "search_bill",
        "bill_return_line_internet",
        "bill_return_line_tv",
    ]:
        custnum = str(known_info.get("custnum") or "").strip()
        custnum = normalize_customer_number(custnum)
        if custnum:
            known_info["custnum"] = custnum
            if has_authenticated_web_custnum(memory):
                return []
        else:
            known_info.pop("custnum", None)
            known_info.pop("custnum_source", None)

        valid_identity_count = sum([
            bool(custnum),
            is_valid_person_name(str(known_info.get("name") or "").strip()),
            bool(normalize_phone_value(known_info.get("phone"))),
        ])
        return [] if valid_identity_count >= 2 else ["identity_pair"]

    if tool_name == "send_message":
        custnum = str(known_info.get("custnum") or "").strip()
        custnum = normalize_customer_number(custnum)
        if custnum:
            known_info["custnum"] = custnum
            if has_authenticated_web_custnum(memory):
                return [] if normalize_phone_value(known_info.get("phone")) else ["phone"]
        else:
            known_info.pop("custnum", None)
            known_info.pop("custnum_source", None)

    missing = []

    for slot in required:
        if slot == "contact_name":
            if not is_valid_person_name(str(known_info.get("contact_name") or "").strip()):
                missing.append(slot)

        elif slot == "contact_phone":
            if not normalize_phone_value(known_info.get("contact_phone")):
                missing.append(slot)

        elif slot == "name":
            if not is_valid_person_name(str(known_info.get("name") or "").strip()):
                missing.append(slot)

        elif slot == "phone":
            if not normalize_phone_value(known_info.get("phone")):
                missing.append(slot)

        elif slot == "issue_description":
            if not is_issue_description_sufficient(known_info.get("issue_description")):
                missing.append(slot)

        else:
            if not known_info.get(slot):
                missing.append(slot)

    return missing


def build_slot_question(
    tool_name: str,
    missing_slots: List[str],
    memory: Optional[Dict[str, Any]] = None,
) -> str:
    labels = get_tool_slot_labels(tool_name)

    if tool_name == "create_repair_ticket":
        if "contact_name" in missing_slots and "contact_phone" in missing_slots:
            return "為了建立報修工單，請提供聯絡人與聯絡電話。"

        if "contact_name" in missing_slots:
            return "請提供聯絡人姓名。"

        if "contact_phone" in missing_slots:
            return "請提供聯絡電話。"

        if "service_address" in missing_slots:
            return "請提供需要報修的服務地址。"

        if "issue_description" in missing_slots:
            return "請簡單描述目前的故障狀況，例如：機上盒亮紅燈、無訊號、沒有畫面、畫面停住或出現錯誤代碼。"

        if "preferred_date" in missing_slots and "preferred_time_range" in missing_slots:
            return "請問您希望安排哪一天、上午或下午哪個時段到府檢查？例如：明天上午。"

        if "preferred_date" in missing_slots:
            return "請問您希望安排哪一天到府檢查？例如：明天。"

        if "preferred_time_range" in missing_slots:
            return "請問您希望安排上午、下午，還是晚上到府檢查？"

    if tool_name == "search_bill" and "identity_pair" in missing_slots:
        known = (memory or {}).get("known_info") or {}
        if normalize_customer_number(known.get("custnum")):
            slot_status = ((memory or {}).get("_recent_slot_status") or {}).get("custnum")
            if slot_status == "updated":
                prefix = "已更新客戶編號。"
            elif slot_status == "unchanged":
                prefix = "已收到這個客戶編號。"
            else:
                prefix = "已收到客戶編號。"
            return f"{prefix}為完成核對，請再提供戶名或登記電話其中一項。"
        if is_valid_person_name(str(known.get("name") or "").strip()):
            return "已收到戶名。為完成核對，請再提供客戶編號或登記電話其中一項。"
        if normalize_phone_value(known.get("phone")):
            return "已收到登記電話。為完成核對，請再提供客戶編號或戶名其中一項。"
        return "可以，我幫您查詢帳單。請提供客戶編號、戶名、登記電話任兩項。"

    if tool_name == "send_message":
        if missing_slots == ["name", "phone"]:
            return (
                "可以，我幫您補發簡訊帳單。"
                "請提供戶名與登記電話供核對；簡訊帳單無法指定寄送到其他電話。"
            )
        if missing_slots == ["name"]:
            return "可以，我幫您補發簡訊帳單。請提供戶名。"
        if missing_slots == ["phone"]:
            return "可以，我幫您補發簡訊帳單。請提供登記電話供核對；簡訊帳單無法指定寄送到其他電話。"

    if tool_name == "payment_bill_batch":
        return (
            "請上傳清楚、完整的超商繳費收據圖片。"
            "圖片需包含超商名稱、繳費完成資訊、代收項目及三段條碼；"
            "我會依圖片辨識結果確認後再處理復線，無法接受手動輸入三段條碼。"
        )

    if tool_name == "bill_return_line_internet" and "identity_pair" in missing_slots:
        return "可以，我幫您送出網路復機申請。請提供客戶編號、戶名、登記電話任兩項。"

    if tool_name == "bill_return_line_tv" and "identity_pair" in missing_slots:
        return "可以，我幫您送出電視復機申請。請提供客戶編號、戶名、登記電話任兩項。"

    if tool_name == "search_contract_info":
        return CONTRACT_LOOKUP_LOGIN_REQUIRED_REPLY

    if tool_name == "search_channel_no":
        if "channel_name" in missing_slots:
            return "請提供想查詢的頻道名稱。"

    if tool_name == "search_service_availability":
        return "我可以用模擬服務範圍 API 查詢。請提供服務地址或鄉鎮市區。"

    if tool_name == "apply_new_install":
        if "contact_name" in missing_slots and "contact_phone" in missing_slots:
            return "我可以建立模擬裝機申請。請提供聯絡人與聯絡電話。"
        if "contact_name" in missing_slots:
            return "請提供聯絡人姓名。"
        if "contact_phone" in missing_slots:
            return "請提供聯絡電話。"
        if "service_address" in missing_slots:
            return "請提供申裝服務地址。"
        if "install_service" in missing_slots:
            return "請問您要申辦寬頻上網，還是有線電視？"

    if tool_name == "search_addon_plans":
        if "service_area" in missing_slots and "addon_name" in missing_slots:
            return "我可以用模擬加值方案 API 查詢。請提供服務地區與加值服務名稱，例如：大里區、LINE TV。"
        if "service_area" in missing_slots:
            return "請提供服務地區，我再查詢加值方案。"
        if "addon_name" in missing_slots:
            return "請提供想查詢的加值服務名稱，例如：哈TV 或 LINE TV。"

    if tool_name == "cancel_repair_ticket":
        if "repair_ticket_id" in missing_slots and "contact_phone" in missing_slots:
            return "我可以用模擬取消報修 API 測試流程。請提供報修單號與聯絡電話。"
        if "repair_ticket_id" in missing_slots:
            return "請提供報修單號。"
        if "contact_phone" in missing_slots:
            return "請提供聯絡電話，以便核對報修資料。"

    zh_fields = [labels.get(slot, slot) for slot in missing_slots]
    return f"為了幫您處理，請先提供：{'、'.join(zh_fields)}。"


def get_missing_tool_args(tool_name: str, memory: Dict[str, Any]) -> List[str]:
    return get_missing_slots(tool_name, memory)


def build_missing_args_question(
    tool_name: str,
    missing_slots: List[str],
    memory: Optional[Dict[str, Any]] = None,
) -> str:
    return build_slot_question(tool_name, missing_slots, memory=memory)


def normalize_pending_tool_args(memory: Dict[str, Any]) -> Dict[str, Any]:
    pending_tool = str(memory.get("pending_tool") or "").strip()
    if not pending_tool:
        memory["pending_tool_args"] = []
        return memory

    memory["pending_tool_args"] = get_missing_slots(pending_tool, memory)
    return memory
