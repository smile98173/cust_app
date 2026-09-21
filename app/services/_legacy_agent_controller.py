import json
from typing import Dict, Any, List

from langchain_core.prompts import ChatPromptTemplate

from app.config.legacy_prompts import AGENT_CONTROLLER_RULES
from app.config.settings import SERVICE_TYPES, NETWORK_ISSUE_TYPES


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


def build_known_info_text(memory: Dict[str, Any]) -> str:
    known = memory.get("known_info", {})
    if not known:
        return "無"
    return json.dumps(known, ensure_ascii=False, indent=2)


def validate_agent_plan(plan: Dict[str, Any]) -> Dict[str, Any]:
    out = dict(plan or {})

    allowed_intents = {
        "smalltalk",
        "faq",
        "search_bill",
        "send_message",
        "bill_return_line_internet",
        "bill_return_line_tv",
        "create_repair_ticket",
        "network_repair",
        "other",
    }

    allowed_decisions = {
        "smalltalk",
        "faq_answer",
        "tool_call",
        "clarify",
        "direct_reply",
    }

    allowed_tools = {
        "search_bill",
        "send_message",
        "bill_return_line_internet",
        "bill_return_line_tv",
        "create_repair_ticket",
        None,
    }

    if out.get("intent") not in allowed_intents:
        out["intent"] = "other"

    if out.get("decision_type") not in allowed_decisions:
        out["decision_type"] = "clarify"

    if out.get("service") not in set(SERVICE_TYPES) | {None}:
        out["service"] = None

    if out.get("issue_type") not in set(NETWORK_ISSUE_TYPES) | {None}:
        out["issue_type"] = None

    if out.get("tool_name") not in allowed_tools:
        out["tool_name"] = None

    out["should_call_tool"] = bool(out.get("should_call_tool", False))
    out["should_retrieve_knowledge"] = bool(out.get("should_retrieve_knowledge", False))

    if out.get("should_call_tool") and not out.get("tool_name"):
        out["should_call_tool"] = False

    if not isinstance(out.get("reply"), str):
        out["reply"] = ""

    if not isinstance(out.get("next_goal"), str):
        out["next_goal"] = "none"

    extracted_slots = out.get("extracted_slots")
    if not isinstance(extracted_slots, dict):
        extracted_slots = {}

    out["extracted_slots"] = {
        "contact_name": extracted_slots.get("contact_name"),
        "contact_phone": extracted_slots.get("contact_phone"),
        "service_address": extracted_slots.get("service_address"),
        "issue_description": extracted_slots.get("issue_description"),
        "preferred_date": extracted_slots.get("preferred_date"),
        "preferred_time_range": extracted_slots.get("preferred_time_range"),
    }

    if out.get("knowledge_query") in ["", None]:
        out["knowledge_query"] = None

    if out.get("need_dispatch") not in [True, False, None]:
        out["need_dispatch"] = None

    return out


def default_agent_plan(user_input: str, memory: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "intent": "other",
        "decision_type": "clarify",
        "service": memory.get("service"),
        "issue_type": memory.get("issue_type"),
        "should_call_tool": False,
        "tool_name": None,
        "should_retrieve_knowledge": False,
        "knowledge_query": user_input,
        "extracted_slots": {
            "contact_name": None,
            "contact_phone": None,
            "service_address": None,
            "issue_description": None,
            "preferred_date": None,
            "preferred_time_range": None,
        },
        "reply": "抱歉，我先確認一下，您是想了解規定說明，還是要我直接幫您處理呢？",
        "next_goal": "none",
        "need_dispatch": None,
    }


def run_agent_controller(
    user_input: str,
    memory: Dict[str, Any],
    history: List[Dict[str, str]],
    llm,
    available_functions: List[Dict[str, Any]],
) -> Dict[str, Any]:
    history_text = "\n".join(
        [f"{m['role']}: {m['content']}" for m in history[-6:]]
    ) if history else "無"

    prompt = ChatPromptTemplate.from_template(
        "{rules}\n\n"
        "目前 session memory:\n"
        "service: {service}\n"
        "issue_type: {issue_type}\n"
        "company: {company}\n"
        "need_dispatch: {need_dispatch}\n"
        "next_goal: {next_goal}\n"
        "pending_tool: {pending_tool}\n"
        "pending_tool_args: {pending_tool_args}\n\n"
        "目前已知資訊:\n"
        "{known_info}\n\n"
        "最近對話:\n"
        "{history_text}\n\n"
        "可用工具 schema:\n"
        "{available_functions}\n\n"
        "使用者最新訊息:\n"
        "{user_input}\n"
    )

    chain = prompt | llm
    resp = chain.invoke({
        "rules": AGENT_CONTROLLER_RULES,
        "service": memory.get("service"),
        "issue_type": memory.get("issue_type"),
        "company": memory.get("company", "共用"),
        "need_dispatch": memory.get("need_dispatch"),
        "next_goal": memory.get("next_goal"),
        "pending_tool": memory.get("pending_tool"),
        "pending_tool_args": memory.get("pending_tool_args", []),
        "known_info": build_known_info_text(memory),
        "history_text": history_text,
        "available_functions": json.dumps(available_functions, ensure_ascii=False, indent=2),
        "user_input": user_input,
    })

    data = safe_json_loads(resp.content)

    if not data:
        return default_agent_plan(user_input, memory)

    validated = validate_agent_plan(data)

    if not validated.get("knowledge_query") and validated.get("should_retrieve_knowledge"):
        validated["knowledge_query"] = user_input

    return validated
