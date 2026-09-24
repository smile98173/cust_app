import re
from typing import Any, Dict, Iterable, Literal, Optional

from pydantic import BaseModel, Field


def dump_model(model: BaseModel) -> Dict[str, Any]:
    if hasattr(model, "model_dump"):
        return model.model_dump()
    return model.dict()


RouterRoute = Literal[
    "continue_current_flow",
    "switch_topic",
    "troubleshooting",
    "tool_action",
    "knowledge_query",
    "company_info",
    "direct_reply",
    "clarify",
    "unsupported_flow",
    "smalltalk",
    "unknown",
]

PromotionScope = Literal[
    "tv_network",
    "pure_network",
    "pure_tv",
    "unspecified",
]

PromotionQueryKind = Literal[
    "scope_clarification",
    "catalog",
    "campaign_detail",
]

ROUTER_ROUTES = {
    "continue_current_flow",
    "switch_topic",
    "troubleshooting",
    "tool_action",
    "knowledge_query",
    "company_info",
    "direct_reply",
    "clarify",
    "unsupported_flow",
    "smalltalk",
    "unknown",
}

ROUTER_SLOT_KEYS = (
    "name",
    "phone",
    "custnum",
    "contact_name",
    "contact_phone",
    "service_address",
    "issue_description",
    "preferred_date",
    "preferred_time_range",
    "service_area",
    "channel_name",
    "addon_name",
    "install_service",
    "desired_plan",
    "repair_ticket_id",
)


class RouterSlots(BaseModel):
    name: Optional[str] = None
    phone: Optional[str] = None
    custnum: Optional[str] = None
    contact_name: Optional[str] = None
    contact_phone: Optional[str] = None
    service_address: Optional[str] = None
    issue_description: Optional[str] = None
    preferred_date: Optional[str] = None
    preferred_time_range: Optional[str] = None
    service_area: Optional[str] = None
    channel_name: Optional[str] = None
    addon_name: Optional[str] = None
    install_service: Optional[str] = None
    desired_plan: Optional[str] = None
    repair_ticket_id: Optional[str] = None


class RouterDecision(BaseModel):
    route: RouterRoute = "unknown"
    intent: str = "other"
    tool_name: Optional[str] = None
    topic: Optional[str] = None
    should_cancel_current_flow: bool = False
    should_call_tool: bool = False
    should_retrieve_knowledge: bool = False
    knowledge_query: Optional[str] = None
    # These two fields are the semantic retrieval contract produced by the
    # router model.  They are deliberately descriptive rather than a fixed
    # taxonomy, so newly added products do not require another keyword route.
    service_scope: Optional[str] = None
    requested_information: Optional[str] = None
    # Promotion retrieval uses a closed service taxonomy. The model owns the
    # semantic choice; application code only validates and enforces it.
    promotion_scope: Optional[PromotionScope] = None
    promotion_query_kind: Optional[PromotionQueryKind] = None
    social_discount_requested: bool = False
    # For a follow-up to a dynamic option list, the model identifies the
    # option while the application validates and hydrates its authoritative
    # retrieval target.  The model must never invent document identifiers.
    selected_option_id: Optional[str] = None
    target_document_id: Optional[str] = None
    target_knowledge_base: Optional[str] = None
    # Keep clarification choices structured so display does not depend on the
    # model producing flawless Markdown numbering in ``reply``.
    clarification_question: Optional[str] = None
    clarification_options: list[str] = Field(default_factory=list)
    reply: str = ""
    extracted_slots: RouterSlots = Field(default_factory=RouterSlots)
    reason: str = ""
    matched_rule_id: Optional[str] = None

    @classmethod
    def from_raw(
        cls,
        data: Dict[str, Any],
        supported_tools: Iterable[str],
    ) -> "RouterDecision":
        raw = data if isinstance(data, dict) else {}
        normalized: Dict[str, Any] = dict(raw)

        route = normalized.get("route", "unknown")
        if route not in ROUTER_ROUTES:
            route = "unknown"
        normalized["route"] = route

        tool_name = normalized.get("tool_name")
        if tool_name not in set(supported_tools):
            tool_name = None
        normalized["tool_name"] = tool_name

        slots = normalized.get("extracted_slots")
        if not isinstance(slots, dict):
            slots = {}
        normalized["extracted_slots"] = {
            key: slots.get(key)
            for key in ROUTER_SLOT_KEYS
        }

        should_call_tool = bool(normalized.get("should_call_tool", False))
        if route != "tool_action":
            should_call_tool = False
        if should_call_tool and not tool_name:
            should_call_tool = False
        normalized["should_call_tool"] = should_call_tool

        should_retrieve_knowledge = bool(normalized.get("should_retrieve_knowledge", False))
        if route == "knowledge_query":
            should_retrieve_knowledge = True
        if route == "company_info" and normalized.get("topic") == "promotion_activity":
            should_retrieve_knowledge = True
            normalized["knowledge_query"] = normalized.get("knowledge_query") or "優惠方案"
        elif route in ["company_info", "direct_reply", "clarify", "unsupported_flow", "smalltalk"]:
            should_retrieve_knowledge = False
        normalized["should_retrieve_knowledge"] = should_retrieve_knowledge

        if not isinstance(normalized.get("reply"), str):
            normalized["reply"] = ""

        if not normalized.get("intent"):
            normalized["intent"] = "other"

        if normalized.get("promotion_scope") not in {
            "tv_network",
            "pure_network",
            "pure_tv",
            "unspecified",
        }:
            normalized["promotion_scope"] = None
        if normalized.get("promotion_query_kind") not in {
            "scope_clarification",
            "catalog",
            "campaign_detail",
        }:
            normalized["promotion_query_kind"] = None
        normalized["social_discount_requested"] = (
            normalized.get("social_discount_requested") is True
        )

        selected_option_id = normalized.get("selected_option_id")
        normalized["selected_option_id"] = (
            selected_option_id.strip()
            if isinstance(selected_option_id, str) and selected_option_id.strip()
            else None
        )
        # Retrieval targets are application-owned. Ignore any identifiers a
        # model may emit; validated conversation context hydrates them later.
        normalized["target_document_id"] = None
        normalized["target_knowledge_base"] = None

        clarification_question = normalized.get("clarification_question")
        normalized["clarification_question"] = (
            clarification_question.strip()[:240]
            if route == "clarify"
            and isinstance(clarification_question, str)
            and clarification_question.strip()
            else None
        )
        raw_options = normalized.get("clarification_options")
        normalized["clarification_options"] = (
            [
                option.strip()[:120]
                for option in raw_options[:8]
                if isinstance(option, str) and option.strip()
            ]
            if route == "clarify" and isinstance(raw_options, list)
            else []
        )

        matched_rule_id = normalized.get("matched_rule_id")
        if not isinstance(matched_rule_id, str) or not matched_rule_id.strip():
            reason = normalized.get("reason")
            if isinstance(reason, str) and re.fullmatch(r"[A-Za-z0-9_:-]+", reason.strip()):
                matched_rule_id = reason.strip()
            else:
                matched_rule_id = None
        normalized["matched_rule_id"] = matched_rule_id

        return cls(**normalized)

    def to_router_dict(self) -> Dict[str, Any]:
        data = dump_model(self)
        data["extracted_slots"] = dump_model(self.extracted_slots)
        return data
