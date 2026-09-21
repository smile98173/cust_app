"""
Legacy controller helpers.

目前 Router 架構已不再使用 run_decision_engine / llm_extract_fields 作為主決策流程。
本檔仍暫時保留 normalize_phone_value、parse_preferred_date、normalize_time_range、
merge_memory_update 等工具函式，供 slot_manager / chat_handler 使用。

未來可拆成：
- app/services/normalizers.py
- app/services/memory_utils.py
"""

import json
import re
from datetime import datetime, timedelta
from typing import Optional, Dict, Any, List

from langchain_core.prompts import ChatPromptTemplate

from app.config.legacy_prompts import SYSTEM_RULES, EXTRACTOR_RULES
from app.config.settings import BAD_NAME_VALUES, SLOT_LABELS
from app.services.customer_validation import normalize_tel, validate_name, validate_tel


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


def validate_extracted_fields(fields: Dict[str, Any]) -> Dict[str, Any]:
    out = dict(fields or {})

    phone = out.get("phone")
    if phone is not None:
        out["phone"] = normalize_phone_value(phone)

    name = out.get("name")
    if isinstance(name, str):
        name = name.strip()
        if not validate_name(name) or name in BAD_NAME_VALUES:
            out["name"] = None
        else:
            out["name"] = name

    custnum = out.get("custnum")
    if custnum is not None:
        custnum = str(custnum).strip()
        out["custnum"] = custnum if custnum else None

    if out.get("service") not in ["billing", "network", "television", None]:
        out["service"] = None

    if out.get("issue_type") not in ["slow_speed", "no_internet", None]:
        out["issue_type"] = None

    allowed_intents = {
        "search_bill",
        "send_message",
        "bill_return_line_internet",
        "bill_return_line_tv",
        "faq",
        "other",
        None,
    }
    if out.get("intent") not in allowed_intents:
        out["intent"] = "other"

    return out


def llm_extract_fields(user_input: str, llm) -> Dict[str, Any]:
    prompt = ChatPromptTemplate.from_template(
        "{rules}\n\n"
        "使用者最新訊息：\n"
        "{user_input}\n"
    )

    chain = prompt | llm
    resp = chain.invoke({
        "rules": EXTRACTOR_RULES,
        "user_input": user_input,
    })

    data = safe_json_loads(resp.content)
    validated = validate_extracted_fields(data)

    result: Dict[str, Any] = {}

    if validated.get("name"):
        result["name"] = validated["name"]
        result["customer_name"] = validated["name"]

    if validated.get("phone"):
        result["phone"] = validated["phone"]
        result["contact_phone"] = validated["phone"]

    if validated.get("custnum"):
        result["custnum"] = validated["custnum"]

    if validated.get("service"):
        result["service"] = validated["service"]

    if validated.get("issue_type"):
        result["issue_type"] = validated["issue_type"]

    result["_extract_meta"] = validated
    return result


def build_known_info_text(memory: Dict[str, Any]) -> str:
    info = memory.get("known_info", {})
    if not info:
        return "目前尚無已知資訊"

    return "\n".join([f"- {SLOT_LABELS.get(k, k)}: {v}" for k, v in info.items()])


def run_decision_engine(
    user_input: str,
    memory: Dict[str, Any],
    history: List[Dict[str, str]],
    retrieved_knowledge_text: str,
    tool_result_text: str,
    llm,
    available_functions: List[Dict[str, Any]],
) -> Dict[str, Any]:
    history_text = "\n".join(
        [f"{'使用者' if m['role'] == 'user' else '客服'}: {m['content']}" for m in history[-6:]]
    ) if history else "無"

    available_functions_text = json.dumps(available_functions, ensure_ascii=False, indent=2)

    prompt = ChatPromptTemplate.from_template(
        "{system_rules}\n\n"
        "目前 session memory:\n"
        "- service: {service}\n"
        "- issue_type: {issue_type}\n"
        "- company: {company}\n"
        "- need_dispatch: {need_dispatch}\n"
        "- next_goal: {next_goal}\n"
        "- available_slots: {available_slots}\n"
        "- pending_tool: {pending_tool}\n"
        "- pending_tool_args: {pending_tool_args}\n\n"
        "目前已知資訊:\n"
        "{known_info_text}\n\n"
        "最近對話:\n"
        "{history_text}\n\n"
        "可用工具 schema:\n"
        "{available_functions}\n\n"
        "知識庫檢索結果:\n"
        "{retrieved_knowledge}\n\n"
        "上一次工具結果:\n"
        "{tool_result}\n\n"
        "使用者最新訊息:\n"
        "{user_input}\n"
    )

    chain = prompt | llm
    resp = chain.invoke({
        "system_rules": SYSTEM_RULES,
        "service": memory.get("service"),
        "issue_type": memory.get("issue_type"),
        "company": memory.get("company", "共用"),
        "need_dispatch": memory.get("need_dispatch"),
        "next_goal": memory.get("next_goal"),
        "available_slots": memory.get("available_slots", []),
        "pending_tool": memory.get("pending_tool"),
        "pending_tool_args": memory.get("pending_tool_args", []),
        "known_info_text": build_known_info_text(memory),
        "history_text": history_text,
        "available_functions": available_functions_text,
        "retrieved_knowledge": retrieved_knowledge_text,
        "tool_result": tool_result_text,
        "user_input": user_input,
    })

    data = safe_json_loads(resp.content)
    if not data:
        return {
            "reply": "抱歉，我先重新確認一下您的需求。請問您是想了解規定、辦理方式，還是要我幫您直接處理呢？",
            "decision_type": "clarify",
            "intent": "other",
            "service": memory.get("service"),
            "issue_type": memory.get("issue_type"),
            "memory_update": {},
            "next_goal": memory.get("next_goal"),
            "need_dispatch": memory.get("need_dispatch"),
            "should_retrieve_knowledge": False,
            "knowledge_query": user_input,
            "should_call_tool": False,
            "tool_name": None,
            "tool_call_reason": "",
            "need_account_data": False,
        }

    return data
