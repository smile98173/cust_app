import sys
import types
from unittest.mock import patch

from app.config.settings import (
    CUSTOMER_TOOL_FLOW_DISABLED_MESSAGE,
)

try:
    import app.services.kb_service  # noqa: F401
except Exception:
    kb_service_stub = types.ModuleType("app.services.kb_service")
    kb_service_stub.VALUE_ADDED_PRODUCT_QUERY_ALIASES = {}
    kb_service_stub.VALUE_ADDED_PRODUCT_NAMES = {}
    kb_service_stub.retrieve_knowledge = lambda *args, **kwargs: []
    kb_service_stub.detect_query_facets = lambda *args, **kwargs: {}
    kb_service_stub.detect_value_added_product_keys = lambda *args, **kwargs: []
    kb_service_stub.suggest_knowledge_entity = lambda *args, **kwargs: None
    kb_service_stub.value_added_query_aliases = lambda *args, **kwargs: []
    kb_service_stub.is_restricted_channel_purchase_query = lambda *args, **kwargs: False
    sys.modules["app.services.kb_service"] = kb_service_stub

from app.handlers.chat_handler import disable_repair_ticket_flow, handle_chat_message, run_tool_or_rag_flow
from app.handlers.chat_handler import build_repair_ticket_flow_disabled_reply
from app.services.troubleshooting_engine import apply_troubleshooting_engine


def test_create_repair_ticket_flow_is_disabled_without_collecting_slots():
    memory = {
        "known_info": {
            "contact_name": "王大明",
            "contact_phone": "0912345678",
            "service_address": "台中市測試路1號",
            "issue_description": "網路不能用",
            "repair_ready": "yes",
        },
        "pending_tool": None,
        "pending_tool_args": [],
    }
    plan = {
        "should_call_tool": True,
        "tool_name": "create_repair_ticket",
        "reply": "了解，我幫您安排報修。",
    }
    router = {"route": "tool_action", "tool_name": "create_repair_ticket"}

    reply, updated = run_tool_or_rag_flow(
        user_text="我要報修",
        memory=memory,
        plan=plan,
        router=router,
        latency={},
    )

    assert "排除後仍無法恢復" in reply
    assert "維修申告" in reply
    assert "是否需要幫您轉接真人文字客服" in reply
    assert updated["pending_tool"] is None
    assert updated["pending_tool_args"] == []
    assert updated["known_info"]["issue_description"] == "網路不能用"


def test_cancel_repair_ticket_flow_is_disabled_without_slot_prompt():
    memory = {
        "known_info": {},
        "pending_tool": "cancel_repair_ticket",
        "pending_tool_args": ["repair_ticket_id", "contact_phone"],
    }
    plan = {
        "should_call_tool": True,
        "tool_name": "cancel_repair_ticket",
        "reply": "",
    }
    router = {"route": "tool_action", "tool_name": "cancel_repair_ticket"}

    reply, updated = run_tool_or_rag_flow(
        user_text="NT20260513-ABC123 0912345678",
        memory=memory,
        plan=plan,
        router=router,
        latency={},
    )

    assert reply == build_repair_ticket_flow_disabled_reply(updated)
    assert updated["pending_tool"] is None
    assert updated["pending_tool_args"] == []
    assert updated["last_tool"] is None
    assert updated["last_tool_result"]["tool_name"] == "cancel_repair_ticket"
    assert updated["last_tool_result"]["data"]["disabled"] is True


def test_disabled_repair_keeps_short_failed_followup_in_repair_context():
    memory = disable_repair_ticket_flow(
        {
            "known_info": {
                "issue_description": "網路重開後還是不能用",
                "repair_ready": "yes",
            }
        },
        "create_repair_ticket",
    )

    plan = apply_troubleshooting_engine(
        "還是沒恢復。",
        memory,
        {"should_call_tool": False, "tool_name": "", "reply": ""},
    )

    assert plan["should_call_tool"] is False
    assert plan["tool_name"] is None
    assert plan["intent"] == "human_handoff_offer"
    assert "是否需要幫您轉接真人文字客服" in plan["reply"]
    assert "想查詢資料" not in plan["reply"]


def test_active_troubleshooting_handoff_offer_includes_repair_form():
    memory = {
        "company_code": "tdtv",
        "known_info": {
            "troubleshooting_started": "yes",
            "troubleshooting_type": "network",
            "troubleshooting_step": "net_reboot_modem",
            "issue_description": "網路完全斷線",
        },
    }
    router_result = {
        "route": "clarify",
        "intent": "human_handoff_offer",
        "tool_name": None,
        "topic": "網路故障",
        "should_cancel_current_flow": False,
        "should_call_tool": False,
        "should_retrieve_knowledge": False,
        "reply": "重新啟動後仍無法恢復，請問是否需要幫您轉接真人文字客服？",
        "reason": "model_confirmed_troubleshooting_failure",
    }

    with patch(
        "app.handlers.chat_handler.run_intent_router",
        return_value=router_result,
    ):
        result = handle_chat_message(
            "test:repair-offer",
            "數據機已重新啟動，還是完全不能上網",
            memory,
            [],
            llm=None,
            persist=False,
        )

    assert "維修申告" in result["ai_response"]
    assert "是否需要幫您轉接真人文字客服" in result["ai_response"]
    assert "smartCustomerService/real/" not in result["ai_response"]
    assert result["memory"]["known_info"]["troubleshooting_failed"] == "yes"
    assert result["memory"]["known_info"]["repair_ready"] == "yes"
    assert result["memory"]["clarify_context"]["type"] == "human_handoff_offer"


def test_repeated_same_issue_after_repair_offer_returns_only_escalation_choices():
    memory = {
        "company_code": "tdtv",
        "clarify_context": {"type": "human_handoff_offer"},
        "known_info": {
            "troubleshooting_started": "no",
            "troubleshooting_type": "set_top_box_network",
            "troubleshooting_failed": "yes",
            "repair_ready": "yes",
            "issue_description": "哈TV機上盒的網路連線有問題",
        },
    }
    history = [
        {"role": "user", "content": "還是不行"},
        {
            "role": "assistant",
            "content": "請填寫維修申告，或選擇轉真人文字客服。",
        },
    ]

    with patch(
        "app.handlers.chat_handler.run_intent_router",
        return_value={
            "route": "troubleshooting",
            "intent": "tv_set_top_box_network_connection_issue",
            "service_scope": "哈TV機上盒聯網",
            "should_cancel_current_flow": False,
            "should_call_tool": False,
            "should_retrieve_knowledge": False,
            "reply": "",
            "reason": "same_set_top_box_fault",
        },
    ):
        result = handle_chat_message(
            "test:repeat-repair-escalation",
            "網路正常，是哈TV機上盒的網路連線有問題",
            memory,
            history,
            llm=None,
            persist=False,
        )

    reply = result["ai_response"]
    assert result["plan"]["intent"] == "human_handoff_offer"
    assert "您的問題需進一步協助處理" in reply
    assert "請填寫申告維修單" in reply
    assert "維修申告" in reply
    assert "或選擇轉真人服務" in reply
    assert "不會再要求" not in reply
    assert "請先" not in reply


def test_disabled_repair_keeps_symptom_followups_in_repair_context():
    memory = disable_repair_ticket_flow(
        {
            "company_code": "tdtv",
            "known_info": {
                "issue_description": "長期網路不穩，手機與電腦都不穩",
                "troubleshooting_type": "network",
                "troubleshooting_started": "no",
                "repair_ready": "yes",
            },
            "pending_tool": None,
            "pending_tool_args": [],
        },
        "create_repair_ticket",
    )
    history = [
        {"role": "user", "content": "兩邊都不穩"},
        {"role": "assistant", "content": build_repair_ticket_flow_disabled_reply(memory)},
    ]

    with patch(
        "app.handlers.chat_handler.run_intent_router",
        return_value={
            "route": "troubleshooting",
            "intent": "internet_connection_issue",
            "service_scope": "network",
            "tool_name": None,
            "should_call_tool": False,
            "should_retrieve_knowledge": False,
            "reply": "",
            "reason": "same_network_repair_context",
        },
    ) as router_mock:
        first = handle_chat_message(
            "test:repair-context",
            "紅燈有亮，一直閃",
            memory,
            history,
            llm=None,
            persist=False,
        )

    router_mock.assert_called_once()
    assert first["plan"]["should_call_tool"] is False
    assert first["plan"]["tool_name"] is None
    assert first["plan"]["intent"] == "human_handoff_offer"
    assert "是否需要幫您轉接真人文字客服" in first["ai_response"]
    assert "想查詢資料" not in first["ai_response"]

    memory = first["memory"]
    history.extend([
        {"role": "user", "content": "紅燈有亮，一直閃"},
        {"role": "assistant", "content": first["ai_response"]},
    ])

    with patch(
        "app.handlers.chat_handler.run_intent_router",
        return_value={
            "route": "troubleshooting",
            "intent": "tv_picture_quality_issue",
            "service_scope": "tv",
            "tool_name": None,
            "should_call_tool": False,
            "should_retrieve_knowledge": False,
            "reply": "",
            "reason": "switch_from_network_repair_to_tv_issue",
        },
    ) as router_mock:
        second = handle_chat_message(
            "test:repair-context",
            "是可以上網，但是一樓電視常訊號不穩",
            memory,
            history,
            llm=None,
            persist=False,
        )

    router_mock.assert_called_once()
    assert second["plan"]["should_call_tool"] is False
    assert second["plan"]["tool_name"] is None
    assert second["memory"]["known_info"]["troubleshooting_type"] == "tv"
    assert second["memory"]["known_info"]["troubleshooting_started"] == "yes"


def test_disabled_customer_tool_does_not_collect_slots():
    memory = {
        "known_info": {
            "service_address": "彰化縣和美鎮",
            "install_service": "寬頻上網",
        },
        "pending_tool": "search_service_availability",
        "pending_tool_args": ["service_address"],
    }
    plan = {
        "should_call_tool": True,
        "tool_name": "search_service_availability",
        "reply": "",
    }
    router = {"route": "tool_action", "tool_name": "search_service_availability"}

    reply, updated = run_tool_or_rag_flow(
        user_text="彰化縣和美鎮",
        memory=memory,
        plan=plan,
        router=router,
        latency={},
    )

    assert reply == CUSTOMER_TOOL_FLOW_DISABLED_MESSAGE
    assert updated["pending_tool"] is None
    assert updated["pending_tool_args"] == []
    assert updated["last_tool"] is None
    assert updated["last_tool_result"]["data"]["disabled"] is True
    assert updated["known_info"]["disabled_tool"] == "search_service_availability"
    assert "service_address" not in updated["known_info"]
    assert "install_service" not in updated["known_info"]
