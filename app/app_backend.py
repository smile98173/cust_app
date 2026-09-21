import asyncio
import base64
import csv
import hmac
import html
import json
import mimetypes
import re
import secrets
import threading
import time
from io import StringIO
from typing import Optional
from urllib.parse import quote, unquote, urlencode

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse

from app.schemas.chat import (
    ApiTokenRequest,
    ChatRequest,
    CompanyProfileUpdateRequest,
    ExternalChatRequest,
    FeedbackRequest,
    ImageTextRequest,
    KnowledgeSearchRequest,
    KnowledgeUploadRequest,
    WebChatRequest,
)
from app.schemas.feedback_tracker import (
    FeedbackTrackerUpdateRequest,
    RegressionCaseUpdateRequest,
)
from app.services.memory_service import (
    init_db,
    default_memory,
    get_session_memory,
    save_session_memory,
    save_chat_log,
    get_recent_chat_history,
    reset_user_session,
)
from app.handlers.chat_handler import handle_chat_message
from app.services.feedback_service import get_feedback_csv_path, save_feedback
from app.services.feedback_tracker_service import (
    apply_tracking_update_bundle,
    bootstrap_tracker_data,
    build_tracking_state_bundle,
    list_feedback_items,
    list_regression_cases,
    load_conversation_log_records,
    load_feedback_csv_records,
    load_latency_log_records,
    pull_online_feedback,
    publish_tracking_updates,
    update_feedback_item,
    update_regression_case,
)
from app.services.company_profile import (
    apply_company_to_memory,
    extract_company_links,
    get_company_profile,
    get_company_options,
    get_company_profile_payload,
    save_company_profile,
)
from app.services.channel_context import (
    activate_human_mode,
    apply_line_channel_context,
    apply_web_channel_context,
    build_line_customer_key,
    is_human_mode_active,
    extract_line_message,
    get_line_message_content,
    get_line_bot_config,
    normalize_channel_user_id,
    push_line_message,
    reply_line_message,
    validate_line_signature,
)
from app.services.web_handoff import (
    build_internal_test_human_handoff_reply,
    build_web_human_handoff_reply,
)
from app.services.reply_safety import sanitize_human_handoff_keyword_instruction
from app.services.image_text_service import ImageTextError, extract_text_from_image_bytes
from app.services.receipt_image_evidence import (
    build_line_receipt_image_attempt,
    build_line_receipt_image_evidence,
    issue_receipt_image_evidence_token,
    verify_receipt_image_evidence_token,
)
from app.services.error_logging import log_exception, public_error_response
from app.services.customer_validation import normalize_tel
from app.services.kb_admin_service import (
    create_document,
    delete_document,
    get_document,
    get_document_chunks,
    get_document_file_path,
    list_documents,
    migrate_legacy_common_documents,
    read_text_with_fallback,
    reindex_all_documents,
    reindex_document,
    release_chroma_runtime_handles,
)
from app.services.kb_index_lock import active_index_operation_count, wait_for_no_active_index_operations
from app.services.kb_service import (
    filter_docs_to_active_manifest_sources,
    normalize_rag_source,
    prewarm_local_searcher_async,
    reset_local_searcher_cache,
)
from app.services.model_manager import ModelManager, SUPPORTED_PROVIDERS
from app.services.web_account_service import (
    PERMISSION_FEEDBACK,
    PERMISSION_KNOWLEDGE_BASE,
    ROLE_DEVELOPER,
    WebAccountService,
    can_manage_knowledge_base,
    can_view_knowledge_base,
    has_permission,
)
from app.config.settings import (
    ACTIVE_ENV_FILE,
    API_AUTH_EXEMPT_PATH_PREFIXES,
    API_AUTH_HEADER,
    API_AUTH_NAME,
    API_AUTH_PASSWORD,
    API_AUTH_SECRET,
    API_AUTH_TOKEN,
    API_AUTH_TOKEN_TTL_SECONDS,
    FEEDBACK_TRACKER_SYNC_TOKEN,
    KB_INDEX_SHUTDOWN_WAIT_SECONDS,
    WEB_AUTH_ENABLED,
)


# =========================
# 1. 基本初始化
# =========================

model_manager = ModelManager()
llm = model_manager.get_llm()
rag_summary_llm = model_manager.get_llm(task="rag_summary")

init_db()
web_account_service = WebAccountService()
web_account_service.init_schema()


def is_model_status_query(text: str) -> bool:
    normalized = (text or "").strip().lower().replace(" ", "")
    if not normalized:
        return False

    status_phrases = [
        "使用的模型",
        "用的模型",
        "目前模型",
        "現在模型",
        "哪個模型",
        "什麼模型",
        "model",
    ]
    provider_phrases = [
        "是不是openai",
        "有跑openai",
        "跑openai",
        "用openai",
        "走openai",
        "是不是gpt",
        "用gpt",
        "跑gpt",
        "用ollama",
        "跑ollama",
        "本地模型",
        "雲端模型",
    ]

    has_model_word = "模型" in normalized or "model" in normalized
    if has_model_word and any(phrase in normalized for phrase in status_phrases):
        return True

    return any(phrase in normalized for phrase in provider_phrases)


def build_model_status_reply() -> str:
    status = model_manager.status()
    provider = status.get("provider", "ollama")
    last_provider = status.get("last_provider")
    models = status.get("models", {})
    provider_info = models.get(provider, {})

    provider_label = {
        "ollama": "Ollama 備援服務",
        "openai": "OpenAI 雲端",
    }.get(provider, provider)

    lines = [
        f"目前主要 provider 是 {provider_label}，模型是 {provider_info.get('model', '未設定')}。",
    ]

    if last_provider:
        last_provider_info = models.get(last_provider, provider_info)
        last_provider_label = {
            "ollama": "Ollama 備援服務",
            "openai": "OpenAI 雲端",
        }.get(last_provider, last_provider)
        lines.append(
            f"最近一次實際呼叫的是 {last_provider_label}，"
            f"模型是 {last_provider_info.get('model', '未設定')}。"
        )
    else:
        lines.append(
            "這次後端重載後尚未記錄到 LLM 實際呼叫；"
            f"下一次需要 LLM 時會優先使用 {provider_label}。"
        )

    openai_info = models.get("openai", {})
    if openai_info.get("api_key_configured"):
        if provider == "openai":
            lines.append("OpenAI API key 已設定，而且目前主要 provider 已切到 OpenAI。")
        else:
            lines.append("OpenAI API key 已設定，但目前主要 provider 仍是 Ollama 服務。")
    else:
        lines.append("OpenAI API key 目前尚未設定。")

    fallback_provider = status.get("fallback_provider")
    if status.get("fallback_enabled") and fallback_provider:
        fallback_label = {
            "ollama": "遠端 Ollama",
            "openai": "OpenAI 雲端",
        }.get(fallback_provider, fallback_provider)
        lines.append(f"fallback provider 是 {fallback_label}。")

    if status.get("last_error"):
        lines.append(f"最近一次模型錯誤：{status['last_error']}")

    return "\n".join(lines)


def build_customer_safe_model_status_reply() -> str:
    return "抱歉，這個問題目前無法回答。請問還有其他服務需要我協助嗎？"


AI_STATE_FIELDS = [
    "conversation_state",
    "service",
    "issue_type",
    "company_code",
    "company",
    "known_info",
    "next_goal",
    "need_dispatch",
    "available_slots",
    "decision_type",
    "pending_tool",
    "pending_tool_args",
    "last_tool_result",
    "last_extracted_fields",
    "clarify_context",
    "customer_key",
    "channel_context",
]


def build_ai_state(memory: dict) -> dict:
    return {
        key: memory.get(key)
        for key in AI_STATE_FIELDS
        if key in memory
    }


def build_external_actions(result: dict) -> list[dict]:
    memory = result.get("memory", {})
    tool_result = memory.get("last_tool_result") or {}
    tool_data = tool_result.get("data") or {}
    actions = []
    if tool_data.get("disabled"):
        actions.append({
            "type": "human_handoff",
            "reason": "service_disabled",
            "tool_name": tool_result.get("tool_name"),
        })

    router = result.get("router") or {}
    if router.get("intent") in {"human_handoff_request", "human_agent"}:
        actions.append({
            "type": "human_handoff",
            "reason": "user_requested",
        })

    return actions


def is_human_handoff_result(result: dict) -> bool:
    router = result.get("router") or {}
    return router.get("intent") in {"human_handoff_request", "human_agent"}


def get_external_user_id(request: ExternalChatRequest) -> str:
    if request.user_id:
        return request.user_id
    if request.user and request.user.user_id:
        return request.user.user_id
    raise HTTPException(status_code=400, detail="缺少 user_id。")


def get_external_company_code(request: ExternalChatRequest) -> str:
    if request.company_code:
        return request.company_code
    if request.tv_cable:
        return request.tv_cable
    if request.company and request.company.company_code:
        return request.company.company_code
    return "tdtv"


def get_external_message_text(request: ExternalChatRequest) -> str:
    if request.msg:
        return request.msg
    if request.message:
        if request.message.type != "text":
            raise HTTPException(status_code=400, detail="目前僅支援 text message。")
        return request.message.text
    raise HTTPException(status_code=400, detail="缺少 msg。")


def get_external_is_logged_in(request: ExternalChatRequest) -> bool:
    if request.is_logged_in is not None:
        return bool(request.is_logged_in)
    if request.user and request.user.is_logged_in is not None:
        return bool(request.user.is_logged_in)
    return bool(get_external_member_id(request, ""))


def get_external_member_id(request: ExternalChatRequest, raw_user_id: str) -> Optional[str]:
    if request.member_id:
        return request.member_id
    if request.user and request.user.member_id:
        return request.user.member_id
    if (request.is_logged_in is True or (request.user and request.user.is_logged_in is True)) and raw_user_id:
        return raw_user_id
    return None


def get_external_custnum(request: ExternalChatRequest) -> Optional[str]:
    for key in ["custnum", "custNo", "cust_no", "customerNo", "customer_number"]:
        value = getattr(request, key, None)
        if value:
            return str(value).strip()

    if request.user:
        for key in ["custnum", "custNo", "cust_no", "customerNo", "customer_number"]:
            value = getattr(request.user, key, None)
            if value:
                return str(value).strip()

    metadata = request.metadata or {}
    for key in ["custnum", "custNo", "cust_no", "customerNo", "customer_number"]:
        value = metadata.get(key)
        if value:
            return str(value).strip()

    return None


def get_external_name(request: ExternalChatRequest) -> Optional[str]:
    if request.name:
        return str(request.name).strip()
    if request.user and request.user.name:
        return str(request.user.name).strip()

    metadata = request.metadata or {}
    for key in ["name", "custCName", "customer_name", "customerName"]:
        value = metadata.get(key)
        if value:
            return str(value).strip()

    return None


def get_external_phone(request: ExternalChatRequest) -> Optional[str]:
    if request.phone:
        return normalize_tel(request.phone)
    if request.user and request.user.phone:
        return normalize_tel(request.user.phone)

    metadata = request.metadata or {}
    for key in ["phone", "custTel", "tel", "customer_phone", "customerPhone"]:
        value = metadata.get(key)
        if value:
            return normalize_tel(value)

    return None


def apply_external_user_context(
    memory: dict,
    request: ExternalChatRequest,
    raw_user_id: str,
    user_id: str,
) -> dict:
    member_id = get_external_member_id(request, raw_user_id)
    is_logged_in = get_external_is_logged_in(request)
    explicit_custnum = get_external_custnum(request)
    explicit_name = get_external_name(request)
    explicit_phone = get_external_phone(request)

    known_info = memory.setdefault("known_info", {})
    known_info["external_user_id"] = raw_user_id
    known_info["is_logged_in"] = is_logged_in

    if member_id:
        known_info["member_id"] = member_id

    if explicit_custnum and is_logged_in:
        known_info["custnum"] = explicit_custnum
        known_info["custnum_source"] = "web_authenticated"
    elif member_id and is_logged_in:
        known_info["custnum"] = member_id
        known_info["custnum_source"] = "web_authenticated"
    elif not is_logged_in:
        known_info.pop("custnum", None)
        known_info.pop("custnum_source", None)
    if explicit_name:
        known_info["name"] = explicit_name
    if explicit_phone:
        known_info["phone"] = explicit_phone

    memory["external_user_id"] = raw_user_id
    memory["member_id"] = member_id
    memory["is_logged_in"] = is_logged_in
    memory["customer_key"] = memory.get("customer_key") or user_id
    return memory


def memory_from_external_state(request: ExternalChatRequest, user_id: str) -> dict:
    memory = get_session_memory(user_id)
    company_code = get_external_company_code(request)
    user_text = get_external_message_text(request)
    memory = apply_web_channel_context(
        memory,
        company_code,
        user_text,
        channel=request.channel or "web",
    )
    raw_user_id = get_external_user_id(request)
    memory = apply_external_user_context(memory, request, raw_user_id, user_id)
    resolved_context = dict(memory.get("channel_context") or {})
    memory["channel_context"] = {
        "channel": request.channel or "web",
        "company_confirmed": resolved_context.get("company_confirmed", True),
        "area": resolved_context.get("area"),
        "resolution_source": resolved_context.get("resolution_source") or "api_request",
        "web_selected_company_code": resolved_context.get("web_selected_company_code") or company_code,
        "conversation_company_override_code": resolved_context.get("conversation_company_override_code"),
        "metadata": request.metadata,
        "external_user_id": raw_user_id,
        "member_id": memory.get("member_id"),
        "is_logged_in": memory.get("is_logged_in"),
        "customer_key": memory.get("customer_key"),
    }
    return memory


def normalize_external_history(request: ExternalChatRequest) -> list[dict]:
    return [
        {
            "role": item.role,
            "content": item.content,
        }
        for item in request.history
    ]


def attach_verified_receipt_image_evidence(
    memory: dict,
    token: str | None,
    user_id: str,
    user_text: str,
) -> dict:
    evidence = verify_receipt_image_evidence_token(token or "", user_id, user_text)
    if evidence:
        memory.setdefault("known_info", {})["receipt_image_evidence"] = evidence
    return memory


def run_core_chat(
    user_id: str,
    user_input: str,
    memory: dict,
    persist: bool = True,
    history: Optional[list[dict]] = None,
) -> dict:
    if persist:
        save_chat_log(user_id, "user", user_input)

    if is_model_status_query(user_input):
        reply = build_customer_safe_model_status_reply()
        memory["decision_type"] = "model_status"
        memory["last_knowledge_results"] = []
        if persist:
            save_session_memory(user_id, memory)
            save_chat_log(user_id, "assistant", reply)

        return {
            "status": "success",
            "ai_response": reply,
            "memory": memory,
        }

    if history is None:
        history = get_recent_chat_history(user_id, limit=12)

    result = handle_chat_message(
        user_id=user_id,
        user_text=user_input,
        memory=memory,
        history=history,
        llm=llm,
        rag_summary_llm=rag_summary_llm,
        persist=persist,
    )
    result["ai_response"] = sanitize_human_handoff_keyword_instruction(result.get("ai_response", ""))
    return result


def build_chat_response(result: dict) -> dict:
    memory = result["memory"]
    latency = result.get("latency") or {}
    response_time_sec = latency.get("total")
    cust_api_time_sec = latency.get("cust_api")
    formatted_reply = (
        build_web_human_handoff_reply(memory)
        if is_human_handoff_result(result)
        else format_reply_for_external_web(result["ai_response"], memory)
    )
    return {
        "status": result["status"],
        "ai_response": formatted_reply,
        "links": extract_reply_links_for_external_web(result["ai_response"], memory),
        "response_time_sec": round(float(response_time_sec), 3) if response_time_sec is not None else None,
        "cust_api_time_sec": round(float(cust_api_time_sec), 3) if cust_api_time_sec is not None else None,
        "latency": latency,
        "actions": build_external_actions(result),
        "known_info": memory.get("known_info"),
        "decision_type": memory.get("decision_type"),
        "company_code": memory.get("company_code"),
        "company": memory.get("company"),
        "channel_context": memory.get("channel_context", {}),
    }


def known_link_url_map(memory: Optional[dict] = None) -> dict[str, str]:
    profile = get_company_profile((memory or {}).get("company_code", ""))
    links = {label: url for label, url in extract_company_links(profile)}
    if "官網" in links:
        links.setdefault("公司官網", links["官網"])
        links.setdefault("官方網站", links["官網"])
    if "LINE TV客服中心" in links:
        links.setdefault("LINE TV官方客服中心", links["LINE TV客服中心"])
    return links


def fill_external_web_known_link_urls(reply: str, memory: Optional[dict] = None) -> str:
    text = html.unescape(str(reply or ""))
    link_urls = known_link_url_map(memory)
    left_bracket = "\uff3b"
    right_bracket = "\uff3d"
    left_corner_bracket = "\u3010"
    right_corner_bracket = "\u3011"
    link_icon = "\U0001f517"
    for label, url in link_urls.items():
        if not url:
            continue
        label_pattern = (
            rf"([{left_bracket}{left_corner_bracket}\[]\s*"
            rf"{re.escape(label)}\s*{link_icon}?\s*"
            rf"[{right_bracket}{right_corner_bracket}\]])"
        )
        known_url = html.unescape(url)
        # Company links may be followed immediately by customer-facing prose,
        # e.g. "［裝機申告］https://...填寫需求".  Mark the configured URL
        # boundary before generic linkification so that prose never becomes
        # part of the href.
        text = re.sub(
            rf"({label_pattern}\s*{re.escape(known_url)})(?=\S)",
            r"\1 ",
            text,
        )
        text = re.sub(
            rf"{label_pattern}(?!\s*https?://)",
            lambda match, link_url=url: f"{match.group(1)} {link_url} ",
            text,
        )

    return text


def render_external_web_links_as_anchors(text: str) -> str:
    pattern = r"[\[\uff3b\u3010]\s*(?P<label>[^\]\uff3d\u3011\n]+?)\s*[\]\uff3d\u3011]\s*(?P<url>https?://[^\s]+)"
    parts = []
    last_end = 0

    def render_plain_text_with_links(value: str) -> str:
        url_pattern = re.compile(r"\bhttps?://[^\s<\"']+")
        rendered_parts = []
        segment_last_end = 0

        for url_match in url_pattern.finditer(value):
            rendered_parts.append(html.escape(value[segment_last_end:url_match.start()]))
            raw_url = url_match.group(0)
            cleaned_url = clean_external_link_url(raw_url)
            trailing = raw_url[len(cleaned_url):]
            if cleaned_url:
                safe_url = html.escape(cleaned_url, quote=True)
                safe_label = html.escape(cleaned_url)
                rendered_parts.append(
                    f'<a href="{safe_url}" target="_blank" rel="noopener noreferrer">{safe_label}</a>'
                )
                rendered_parts.append(html.escape(trailing))
            else:
                rendered_parts.append(html.escape(raw_url))
            segment_last_end = url_match.end()

        rendered_parts.append(html.escape(value[segment_last_end:]))
        return "".join(rendered_parts)

    def replace_link(match: re.Match) -> str:
        label = normalize_external_link_label(match.group("label"))
        url = clean_external_link_url(match.group("url"))
        if not label or not url:
            return render_plain_text_with_links(match.group(0))
        safe_label = html.escape(label)
        safe_url = html.escape(url, quote=True)
        return f'<a href="{safe_url}" target="_blank" rel="noopener noreferrer">{safe_label}</a>'

    for match in re.finditer(pattern, text):
        parts.append(render_plain_text_with_links(text[last_end:match.start()]))
        parts.append(replace_link(match))
        last_end = match.end()

    parts.append(render_plain_text_with_links(text[last_end:]))
    return "".join(parts)


def format_reply_for_external_web(reply: str, memory: Optional[dict] = None) -> str:
    text = fill_external_web_known_link_urls(reply, memory)
    return render_external_web_links_as_anchors(text)


def normalize_external_link_label(label: str) -> str:
    link_icon = "\U0001f517"
    return re.sub(r"\s+", " ", str(label or "").replace(link_icon, "")).strip()


def clean_external_link_url(url: str) -> str:
    value = html.unescape(str(url or "")).strip()
    # LLM prose can follow an ASCII URL without whitespace. Full-width Chinese
    # punctuation is a reliable boundary and must never become part of href.
    value = re.split(r"[，。；、、「」『』【】（）]", value, maxsplit=1)[0]
    return value.rstrip("。．,，；;")


def extract_reply_links_for_external_web(reply: str, memory: Optional[dict] = None) -> list[dict]:
    text = fill_external_web_known_link_urls(reply, memory)
    links = []
    seen = set()
    pattern = r"[\[\uff3b\u3010]\s*(?P<label>[^\]\uff3d\u3011\n]+?)\s*[\]\uff3d\u3011]\s*(?P<url>https?://[^\s]+)"
    link_spans = []

    def add_link(label: str, url: str) -> None:
        label = normalize_external_link_label(label)
        url = clean_external_link_url(url)
        if not label or not url:
            return
        key = (label, url)
        if key in seen:
            return
        seen.add(key)
        links.append({
            "label": label,
            "url": url,
        })

    for match in re.finditer(pattern, text):
        add_link(match.group("label"), match.group("url"))
        link_spans.append(match.span("url"))

    plain_url_pattern = re.compile(r"\bhttps?://[^\s<\"']+")
    for match in plain_url_pattern.finditer(text):
        if any(start <= match.start() < end for start, end in link_spans):
            continue
        url = clean_external_link_url(match.group(0))
        add_link(url, url)

    return links


def user_id_from_payload(payload) -> Optional[str]:
    if payload is None:
        return None
    return getattr(payload, "user_id", None) or getattr(payload, "member_id", None)


def raise_internal_error(
    operation: str,
    exc: BaseException,
    *,
    user_id: Optional[str] = None,
    request_path: Optional[str] = None,
    extra: Optional[dict] = None,
):
    log_exception(
        operation,
        exc,
        user_id=user_id,
        request_path=request_path,
        extra=extra,
    )
    raise HTTPException(status_code=500, detail=public_error_response())


KB_PREVIEW_FIELD_LABELS = {
    "question": "問題",
    "answer": "答案",
    "content": "內容",
    "company": "知識庫",
    "knowledge_base": "知識庫",
    "category": "分類",
    "source": "來源",
    "title": "標題",
}


def render_kb_preview_content(content: str) -> str:
    text = str(content or "").strip()
    if not text:
        return "<p class='empty'>此片段沒有文字內容。</p>"

    pattern = re.compile(
        r"(?i)(question|answer|content|company|knowledge_base|category|source|title)\s*[:：]"
    )
    matches = list(pattern.finditer(text))
    if not matches:
        return f"<pre>{html.escape(text)}</pre>"

    blocks = []
    for index, match in enumerate(matches):
        key = match.group(1).lower()
        start = match.end()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        value = text[start:end].strip(" \t\r\n;；,，")
        if not value:
            continue

        label = KB_PREVIEW_FIELD_LABELS.get(key, key)
        value_html = html.escape(value).replace("\n", "<br>")
        blocks.append(
            f"<div class='field-block'>"
            f"<div class='field-label'>{html.escape(label)}：</div>"
            f"<div class='field-value'>{value_html}</div>"
            f"</div>"
        )

    if not blocks:
        return f"<pre>{html.escape(text)}</pre>"
    return "<div class='fields'>" + "\n".join(blocks) + "</div>"


def render_kb_preview_field_block(label: str, value: str) -> str:
    normalized_value = str(value or "").replace("\r\n", "\n").replace("\r", "\n").strip()
    if not normalized_value:
        return ""

    value_html = html.escape(normalized_value).replace("\n", "<br>")
    return (
        f"<div class='field-block'>"
        f"<div class='field-label'>{html.escape(label)}：</div>"
        f"<div class='field-value'>{value_html}</div>"
        f"</div>"
    )


def render_campaign_profile_preview(document: dict) -> str:
    profile = document.get("campaign_profile")
    if not isinstance(profile, dict) or profile.get("document_type") != "promotion_campaign":
        return ""

    validation = profile.get("validation") if isinstance(profile.get("validation"), dict) else {}
    status = str(validation.get("status") or "needs_review")
    is_complete = status == "complete"
    status_label = "欄位完整" if is_complete else "建議檢查"
    status_class = "complete" if is_complete else "review"
    missing_labels = {
        "campaign_name": "方案名稱",
        "service_or_speed": "服務類型或速率",
        "price": "費率",
        "eligibility_or_contract": "適用資格或綁約條件",
    }

    def display_list(value) -> str:
        if not isinstance(value, list):
            return ""
        return "、".join(str(item).strip() for item in value if str(item).strip())

    fields = [
        ("方案名稱", str(profile.get("campaign_name") or "")),
        ("方案別名", display_list(profile.get("aliases"))),
        ("服務類型", display_list(profile.get("service_types"))),
        ("速率", display_list(profile.get("speeds"))),
        (
            "綁約期間",
            "、".join(
                f"{value} 個月"
                for value in (profile.get("contract_months") or [])
                if str(value).strip()
            ),
        ),
        ("繳別", display_list(profile.get("payment_terms"))),
        ("適用對象", display_list(profile.get("customer_types"))),
        ("活動期間", str(profile.get("valid_period") or "")),
        ("節慶關聯", display_list(profile.get("occasion_terms"))),
        ("贈品內容", display_list(profile.get("gift_items"))),
        ("抽獎內容", display_list(profile.get("lottery_details"))),
        ("已辨識內容", display_list(profile.get("section_types"))),
    ]
    field_html = "".join(
        (
            "<div class='campaign-field'>"
            f"<div class='campaign-field-label'>{html.escape(label)}</div>"
            f"<div class='campaign-field-value'>{html.escape(value)}</div>"
            "</div>"
        )
        for label, value in fields
        if value
    )

    missing_fields = [
        missing_labels.get(str(field), str(field))
        for field in (validation.get("missing_fields") or [])
    ]
    review_html = ""
    if missing_fields:
        review_html = (
            "<div class='campaign-review-note'>"
            f"重建索引前建議確認：{html.escape('、'.join(missing_fields))}。"
            "這不會阻擋索引，但可能影響方案問句的完整回答。"
            "</div>"
        )

    return (
        "<section class='campaign-profile'>"
        "<div class='campaign-profile-heading'>"
        "<div><div class='campaign-eyebrow'>優惠活動標準化結果</div>"
        "<h2>方案結構化摘要</h2></div>"
        f"<span class='campaign-status {status_class}'>{status_label}</span>"
        "</div>"
        f"<div class='campaign-grid'>{field_html}</div>"
        f"{review_html}"
        "</section>"
    )


def render_csv_preview_content(document_id: str) -> str:
    file_path = get_document_file_path(document_id)
    raw = read_text_with_fallback(file_path)
    reader = csv.DictReader(StringIO(raw))
    rows = list(reader)

    if not rows:
        return render_kb_preview_content(raw)

    content_blocks = []
    for index, row in enumerate(rows, start=1):
        field_blocks = []
        for key, value in row.items():
            if value is None:
                continue
            label_key = str(key or "其他").strip()
            label = KB_PREVIEW_FIELD_LABELS.get(label_key.lower(), label_key)
            block = render_kb_preview_field_block(label, str(value))
            if block:
                field_blocks.append(block)

        if field_blocks:
            content_blocks.append(
                f"<section class='chunk'>"
                f"<div class='chunk-label'>原始 CSV / row {index}</div>"
                f"<div class='fields'>{''.join(field_blocks)}</div>"
                f"</section>"
            )

    return "\n".join(content_blocks) or "<p class='empty'>沒有可預覽的 CSV 內容。</p>"


def kb_document_file_url(
    document_id: str,
    api_token: str = "",
    web_auth_token: str = "",
) -> str:
    url = f"/api/kb/documents/{quote(str(document_id), safe='')}/file"
    query_items = []
    token = str(api_token or "").strip()
    session_token = str(web_auth_token or "").strip()
    if token:
        query_items.append(("api_token", token))
    if session_token:
        query_items.append(("web_auth_token", session_token))
    if query_items:
        url = f"{url}?{urlencode(query_items)}"
    return url


def render_kb_preview_error_page(
    message: str,
    status_code: int = 404,
    *,
    title: str = "文件無法預覽",
    action_message: str = "請回到知識庫維護列表重新整理後，再點最新文件的「查看」。",
) -> HTMLResponse:
    safe_message = html.escape(str(message or "文件不存在。"))
    safe_title = html.escape(str(title or "文件無法預覽"))
    safe_action_message = html.escape(str(action_message or ""))
    action_block = f"    <p>{safe_action_message}</p>\n" if safe_action_message else ""
    return HTMLResponse(
        content=f"""<!doctype html>
<html lang="zh-Hant">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{safe_title}</title>
  <style>
    body {{
      margin: 0;
      min-height: 100vh;
      display: grid;
      place-items: center;
      background: #f6f8fb;
      color: #172033;
      font-family: "Microsoft JhengHei", "Noto Sans TC", Arial, sans-serif;
      line-height: 1.7;
    }}
    main {{
      max-width: 640px;
      margin: 24px;
      padding: 28px;
      border: 1px solid #d8e0ec;
      border-radius: 8px;
      background: #fff;
    }}
    h1 {{
      margin: 0 0 12px;
      font-size: 24px;
    }}
    p {{
      margin: 8px 0 0;
      color: #536179;
    }}
  </style>
</head>
<body>
  <main>
    <h1>{safe_title}</h1>
    <p>{safe_message}</p>
{action_block.rstrip()}
  </main>
</body>
</html>""",
        status_code=status_code,
    )


def is_kb_document_direct_file_path(path: str) -> bool:
    return bool(re.match(r"^/api/kb/documents/[^/]+/(?:preview|file)$", str(path or "")))


def render_kb_document_auth_error_page(
    message: str = "文件連結憑證已過期或失效。",
) -> HTMLResponse:
    return render_kb_preview_error_page(
        message,
        status_code=401,
        title="文件連結已失效",
        action_message="請回到知識庫維護頁重新整理後，再重新點選文件的「查看」或「下載」。",
    )


def build_human_alert_text(
    bot_config: dict,
    line_user_id: str,
    user_text: str,
    history: list[dict],
) -> str:
    history_lines = []
    for item in history[-2:]:
        role = item.get("role", "")
        content = item.get("content", "")
        label = "User" if role == "user" else "AI"
        history_lines.append(f"{label}: {content}")

    history_text = "\n".join(history_lines) if history_lines else "無"
    bot_name = bot_config.get("display_name") or bot_config.get("bot_code")

    return (
        f"{bot_name} 用戶要求真人客服\n"
        f"LINE User ID: {line_user_id}\n"
        f"最新訊息: {user_text}\n\n"
        f"最近對話:\n{history_text}"
    )


def build_human_forward_text(
    bot_config: dict,
    line_user_id: str,
    user_text: str,
) -> str:
    bot_name = bot_config.get("display_name") or bot_config.get("bot_code")
    return (
        f"{bot_name} 真人模式訊息\n"
        f"LINE User ID: {line_user_id}\n"
        f"訊息: {user_text}"
    )


# =========================
# 2. FastAPI
# =========================

app = FastAPI(title="AI 客服後端", version="1.6.0")
KB_DOCUMENT_MUTATION_LOCK = threading.Lock()


@app.on_event("startup")
async def startup_prewarm_local_rag():
    migration = await asyncio.to_thread(
        migrate_legacy_common_documents,
        "system",
    )
    if migration.get("migrated_count"):
        print(
            "[KB] migrated legacy common documents to 通用-中區: "
            f"{migration.get('migrated_count')} document(s), "
            f"{migration.get('failed_count')} failed"
        )
    prewarm_local_searcher_async()


def wait_for_kb_document_mutation_lock(timeout_seconds: float) -> bool:
    timeout = max(0.0, float(timeout_seconds or 0))
    acquired = KB_DOCUMENT_MUTATION_LOCK.acquire(timeout=timeout)
    if not acquired:
        return False
    KB_DOCUMENT_MUTATION_LOCK.release()
    return True


@app.on_event("shutdown")
async def shutdown_wait_for_local_kb_index():
    timeout = max(0.0, float(KB_INDEX_SHUTDOWN_WAIT_SECONDS or 0))
    if timeout <= 0:
        release_chroma_runtime_handles()
        return

    started_at = time.monotonic()
    print(f"[KB] shutdown waiting for local index operations: timeout={timeout:.1f}s")
    mutation_idle = await asyncio.to_thread(wait_for_kb_document_mutation_lock, timeout)
    remaining = max(0.0, timeout - (time.monotonic() - started_at))
    index_idle = await asyncio.to_thread(wait_for_no_active_index_operations, remaining)

    if mutation_idle and index_idle:
        print("[KB] shutdown local index operations completed")
    else:
        print(
            "[KB] shutdown local index wait timed out: "
            f"mutation_idle={mutation_idle}, "
            f"active_index_operations={active_index_operation_count()}"
        )
    release_chroma_runtime_handles()


app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def is_api_auth_exempt_path(path: str) -> bool:
    return any(path.startswith(prefix) for prefix in API_AUTH_EXEMPT_PATH_PREFIXES)


def get_api_auth_token_from_request(request: Request) -> str:
    configured_header = API_AUTH_HEADER or "X-API-Token"
    token = request.headers.get(configured_header, "").strip()
    if token:
        return token

    authorization = request.headers.get("Authorization", "").strip()
    scheme, _, value = authorization.partition(" ")
    if scheme.lower() == "bearer" and value.strip():
        return value.strip()

    query_token = request.query_params.get("api_token", "").strip()
    if query_token:
        return query_token

    return ""


def api_auth_enabled() -> bool:
    return bool(API_AUTH_TOKEN or (API_AUTH_SECRET and API_AUTH_NAME and API_AUTH_PASSWORD))


def base64url_encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def base64url_decode(value: str) -> bytes:
    padding = "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode((value + padding).encode("ascii"))


def sign_api_token_payload(payload_b64: str) -> str:
    signature = hmac.new(
        API_AUTH_SECRET.encode("utf-8"),
        payload_b64.encode("ascii"),
        "sha256",
    ).digest()
    return base64url_encode(signature)


def create_api_access_token(subject: str) -> tuple[str, int]:
    now = int(time.time())
    ttl = max(60, int(API_AUTH_TOKEN_TTL_SECONDS or 86400))
    expires_at = now + ttl
    payload = {
        "sub": subject,
        "iat": now,
        "exp": expires_at,
        "nonce": secrets.token_urlsafe(16),
    }
    payload_b64 = base64url_encode(json.dumps(payload, separators=(",", ":")).encode("utf-8"))
    signature_b64 = sign_api_token_payload(payload_b64)
    return f"aicust.{payload_b64}.{signature_b64}", expires_at


def validate_signed_api_token(token: str) -> bool:
    if not API_AUTH_SECRET or not token.startswith("aicust."):
        return False

    parts = token.split(".")
    if len(parts) != 3:
        return False

    _, payload_b64, signature_b64 = parts
    expected_signature = sign_api_token_payload(payload_b64)
    if not secrets.compare_digest(signature_b64, expected_signature):
        return False

    try:
        payload = json.loads(base64url_decode(payload_b64).decode("utf-8"))
        expires_at = int(payload.get("exp") or 0)
    except Exception:
        return False

    return expires_at >= int(time.time())


def validate_api_auth_token(token: str) -> bool:
    if API_AUTH_TOKEN and secrets.compare_digest(token, API_AUTH_TOKEN):
        return True
    return validate_signed_api_token(token)


def get_actor_username_from_request(request: Request) -> str:
    actor = str(
        request.headers.get("X-Actor-Username")
        or request.headers.get("X-Web-Username")
        or ""
    ).strip()
    actor = unquote(actor)
    actor = re.sub(r"[\r\n\t]+", " ", actor).strip()
    return actor[:80] if actor else "system"


def kb_actor_display_name_map() -> dict[str, str]:
    try:
        accounts = web_account_service.list_accounts()
    except Exception:
        return {}

    return {
        str(account.get("username") or "").strip().casefold(): (
            str(account.get("display_name") or account.get("username") or "").strip()
        )
        for account in accounts
        if str(account.get("username") or "").strip()
    }


def with_kb_actor_display_names(
    document: dict,
    display_names: Optional[dict[str, str]] = None,
) -> dict:
    result = dict(document or {})
    actor_names = display_names if display_names is not None else kb_actor_display_name_map()
    for actor_field, display_field in (
        ("uploaded_by", "uploaded_by_display_name"),
        ("last_indexed_by", "last_indexed_by_display_name"),
    ):
        actor = str(result.get(actor_field) or "").strip()
        result[display_field] = actor_names.get(actor.casefold(), actor)
    return result


def with_kb_documents_actor_display_names(documents: list[dict]) -> list[dict]:
    display_names = kb_actor_display_name_map()
    return [with_kb_actor_display_names(document, display_names) for document in documents]


def get_web_account_from_request(request: Request) -> Optional[dict]:
    token = str(
        request.headers.get("X-Web-Auth-Token")
        or request.query_params.get("web_auth_token")
        or ""
    ).strip()
    if not token:
        if WEB_AUTH_ENABLED:
            raise HTTPException(status_code=401, detail="缺少網頁登入憑證，請重新登入。")
        return None
    account = web_account_service.validate_session_token(token)
    if not account:
        raise HTTPException(status_code=401, detail="登入狀態已失效，請重新登入。")
    return account


def require_kb_permission(
    request: Request,
    knowledge_base: Optional[str] = None,
    *,
    developer_only: bool = False,
    write: bool = False,
) -> Optional[dict]:
    account = get_web_account_from_request(request)
    if account is None:
        # 沒有 Web 工作階段的呼叫視為後端整合服務，仍由 API token 保護。
        return None
    if not has_permission(account, PERMISSION_KNOWLEDGE_BASE):
        raise HTTPException(status_code=403, detail="此帳號沒有知識庫維護權限。")
    if developer_only and account.get("role") != ROLE_DEVELOPER:
        raise HTTPException(status_code=403, detail="此操作僅限研發人員。")
    if knowledge_base and not can_view_knowledge_base(account, knowledge_base):
        raise HTTPException(status_code=403, detail="此帳號不可檢視知識庫。")
    if write and knowledge_base and not can_manage_knowledge_base(account, knowledge_base):
        raise HTTPException(
            status_code=403,
            detail=f"此帳號不可修改「{knowledge_base}」知識庫。",
        )
    return account


def require_feedback_permission(request: Request) -> Optional[dict]:
    account = get_web_account_from_request(request)
    if account is None:
        return None
    if not has_permission(account, PERMISSION_FEEDBACK):
        raise HTTPException(status_code=403, detail="此帳號沒有回饋追蹤權限。")
    return account


def require_developer_feedback_permission(request: Request) -> Optional[dict]:
    account = require_feedback_permission(request)
    if account is not None and account.get("role") != ROLE_DEVELOPER:
        raise HTTPException(status_code=403, detail="此操作僅限系統管理者。")
    return account


TRACKER_SYNC_REMOTE_PREFIX = "/api/feedback-tracker/sync/remote/"
TRACKER_SYNC_HEADER = "X-Feedback-Tracker-Sync-Token"


def valid_tracker_sync_token(request: Request) -> bool:
    configured = str(FEEDBACK_TRACKER_SYNC_TOKEN or "")
    received = str(request.headers.get(TRACKER_SYNC_HEADER) or "")
    return bool(configured and received and hmac.compare_digest(received, configured))


def require_tracker_sync_token(request: Request) -> None:
    if not FEEDBACK_TRACKER_SYNC_TOKEN:
        raise HTTPException(status_code=503, detail="追蹤同步權杖尚未設定。")
    if not valid_tracker_sync_token(request):
        raise HTTPException(status_code=401, detail="追蹤同步權杖無效。")


@app.middleware("http")
async def api_token_auth_middleware(request: Request, call_next):
    if not api_auth_enabled():
        return await call_next(request)

    if request.method.upper() == "OPTIONS" or is_api_auth_exempt_path(request.url.path):
        return await call_next(request)

    if request.url.path.startswith(TRACKER_SYNC_REMOTE_PREFIX) and valid_tracker_sync_token(request):
        return await call_next(request)

    request_token = get_api_auth_token_from_request(request)
    if not request_token or not validate_api_auth_token(request_token):
        if is_kb_document_direct_file_path(request.url.path):
            return render_kb_document_auth_error_page()
        return JSONResponse(
            status_code=401,
            content={"detail": "Invalid or missing API token."},
        )

    return await call_next(request)


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.post("/api/auth/token")
async def issue_api_token(request: ApiTokenRequest):
    if not API_AUTH_SECRET or not API_AUTH_NAME or not API_AUTH_PASSWORD:
        raise HTTPException(status_code=503, detail="API token service is not configured.")

    name_ok = secrets.compare_digest(
        str(request.name or "").encode("utf-8"),
        API_AUTH_NAME.encode("utf-8"),
    )
    password_ok = secrets.compare_digest(
        str(request.password or "").encode("utf-8"),
        API_AUTH_PASSWORD.encode("utf-8"),
    )
    if not name_ok or not password_ok:
        raise HTTPException(status_code=401, detail="Invalid name or password.")

    access_token, expires_at = create_api_access_token(API_AUTH_NAME)
    return {
        "status": "success",
        "token_type": "Bearer",
        "access_token": access_token,
        "expires_at": expires_at,
        "expires_in": max(0, expires_at - int(time.time())),
        "header_name": API_AUTH_HEADER or "X-API-Token",
    }


@app.get("/llm/status")
async def llm_status():
    return {
        "status": "success",
        "active_env_file": str(ACTIVE_ENV_FILE),
        "llm": model_manager.status(),
    }


@app.post("/llm/provider/{provider}")
async def switch_llm_provider(provider: str):
    if provider not in SUPPORTED_PROVIDERS:
        raise HTTPException(
            status_code=400,
            detail=f"不支援的模型 provider: {provider}",
        )

    return {
        "status": "success",
        "llm": model_manager.set_provider(provider),
    }


@app.post("/llm/fallback/{provider}")
async def switch_llm_fallback(provider: str):
    if provider not in SUPPORTED_PROVIDERS:
        raise HTTPException(
            status_code=400,
            detail=f"不支援的 fallback provider: {provider}",
        )

    return {
        "status": "success",
        "llm": model_manager.set_fallback_provider(provider),
    }


@app.get("/companies")
async def companies():
    return {
        "status": "success",
        "companies": get_company_options(),
    }


@app.get("/api/company-profiles")
async def company_profiles():
    return {
        "status": "success",
        **get_company_profile_payload(),
    }


@app.get("/api/company-profiles/{company_code}")
async def company_profile_detail(company_code: str):
    profile = get_company_profile(company_code)
    if profile.get("tv_cable") != company_code:
        raise HTTPException(status_code=404, detail="找不到指定系統台。")
    return {
        "status": "success",
        "profile": profile,
    }


@app.put("/api/company-profiles/{company_code}")
async def update_company_profile(company_code: str, request: CompanyProfileUpdateRequest):
    try:
        profile = save_company_profile(
            company_code,
            request.model_dump(exclude_unset=True)
            if hasattr(request, "model_dump")
            else request.dict(exclude_unset=True),
        )
        return {
            "status": "success",
            "message": "已更新公司基本資訊。",
            "profile": profile,
        }
    except KeyError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise_internal_error(
            "update_company_profile",
            e,
            request_path=f"/api/company-profiles/{company_code}",
            extra={"company_code": company_code},
        )


@app.get("/state/{user_id}")
async def get_state(user_id: str, tv_cable: Optional[str] = None):
    try:
        memory = get_session_memory(user_id)
        if tv_cable:
            memory = apply_company_to_memory(memory, tv_cable)
        return {
            "status": "success",
            "user_id": user_id,
            "service": memory.get("service"),
            "issue_type": memory.get("issue_type"),
            "company_code": memory.get("company_code", "tdtv"),
            "company": memory.get("company", "共用"),
            "company_profile": memory.get("company_profile", {}),
            "known_info": memory.get("known_info", {}),
            "next_goal": memory.get("next_goal"),
            "need_dispatch": memory.get("need_dispatch"),
            "available_slots": memory.get("available_slots", []),
            "last_knowledge_results": memory.get("last_knowledge_results", []),
            "decision_type": memory.get("decision_type"),
            "pending_tool": memory.get("pending_tool"),
            "pending_tool_args": memory.get("pending_tool_args", []),
            "last_tool_result": memory.get("last_tool_result"),
            "last_extracted_fields": memory.get("last_extracted_fields"),
            "conversation_state": memory.get("conversation_state", {}),
        }
    except Exception as e:
        raise_internal_error("get_state", e, user_id=user_id, request_path=f"/state/{user_id}")


@app.post("/reset/{user_id}")
async def reset_state(user_id: str):
    """
    重置指定 user_id 的 session memory 與 chat logs。
    """
    try:
        result = reset_user_session(user_id=user_id)

        return {
            "status": "success",
            "user_id": user_id,
            "message": "已重置使用者對話狀態。",
            "memory": result.get("memory"),
        }

    except Exception as e:
        raise_internal_error("reset_state", e, user_id=user_id, request_path=f"/reset/{user_id}")


@app.post("/chat")
async def chat(request: ChatRequest):
    try:
        user_id = normalize_channel_user_id("test_web", request.user_id)
        save_chat_log(user_id, "user", request.user_input)

        memory = get_session_memory(user_id)
        memory = apply_web_channel_context(
            memory,
            request.tv_cable,
            request.user_input,
            channel="test_web",
        )
        memory.setdefault("channel_context", {})["source"] = "web_ui"
        memory.setdefault("channel_context", {})["external_user_id"] = request.user_id
        memory = attach_verified_receipt_image_evidence(
            memory,
            request.receipt_evidence_token,
            user_id,
            request.user_input,
        )

        if is_model_status_query(request.user_input):
            reply = build_customer_safe_model_status_reply()
            memory["decision_type"] = "model_status"
            memory["last_knowledge_results"] = []
            save_session_memory(user_id, memory)
            save_chat_log(user_id, "assistant", reply)

            return {
                "status": "success",
                "ai_response": reply,
                "known_info": memory.get("known_info"),
                "decision_type": memory.get("decision_type"),
                "company_code": memory.get("company_code"),
                "company": memory.get("company"),
            }

        history = get_recent_chat_history(user_id, limit=12)

        result = handle_chat_message(
            user_id=user_id,
            user_text=request.user_input,
            memory=memory,
            history=history,
            llm=llm,
            rag_summary_llm=rag_summary_llm,
        )
        latency = result.get("latency") or {}
        response_time_sec = latency.get("total")
        cust_api_time_sec = latency.get("cust_api")
        formatted_reply = (
            build_internal_test_human_handoff_reply()
            if is_human_handoff_result(result)
            else result["ai_response"]
        )

        return {
            "status": result["status"],
            "ai_response": formatted_reply,
            "response_time_sec": round(float(response_time_sec), 3) if response_time_sec is not None else None,
            "cust_api_time_sec": round(float(cust_api_time_sec), 3) if cust_api_time_sec is not None else None,
            "latency": latency,
            "actions": build_external_actions(result),
            "known_info": result["memory"].get("known_info"),
            "decision_type": result["memory"].get("decision_type"),
            "company_code": result["memory"].get("company_code"),
            "company": result["memory"].get("company"),
        }

    except Exception as e:
        raise_internal_error("chat", e, user_id=request.user_id, request_path="/chat")


@app.post("/api/web/chat")
async def web_chat(request: WebChatRequest):
    try:
        user_id = normalize_channel_user_id("web", request.user_id)
        memory = get_session_memory(user_id)
        memory = apply_web_channel_context(memory, request.tv_cable, request.user_input)
        memory.setdefault("channel_context", {})["metadata"] = request.metadata
        memory.setdefault("channel_context", {})["external_user_id"] = request.user_id
        memory = attach_verified_receipt_image_evidence(
            memory,
            request.receipt_evidence_token,
            user_id,
            request.user_input,
        )

        result = run_core_chat(user_id, request.user_input, memory)
        return build_chat_response(result)

    except Exception as e:
        raise_internal_error("web_chat", e, user_id=request.user_id, request_path="/api/web/chat")


@app.post("/api/v1/chat")
async def external_chat(request: ExternalChatRequest):
    try:
        raw_user_id = get_external_user_id(request)
        user_text = get_external_message_text(request)
        user_id = normalize_channel_user_id(request.channel or "web", raw_user_id)
        memory = memory_from_external_state(request, user_id)
        memory = attach_verified_receipt_image_evidence(
            memory,
            request.receipt_evidence_token,
            user_id,
            user_text,
        )
        supplied_history = normalize_external_history(request)

        result = run_core_chat(
            user_id,
            user_text,
            memory,
            persist=True,
            history=supplied_history or None,
        )
        formatted_msg = (
            build_web_human_handoff_reply(result["memory"])
            if is_human_handoff_result(result)
            else format_reply_for_external_web(result["ai_response"], result["memory"])
        )

        return {
            "status": result["status"],
            "request_id": request.request_id,
            "user_id": user_id,
            "msg": formatted_msg,
            "links": extract_reply_links_for_external_web(result["ai_response"], result["memory"]),
            "actions": build_external_actions(result),
        }

    except HTTPException:
        raise
    except Exception as e:
        raw_user_id = None
        try:
            raw_user_id = get_external_user_id(request)
        except Exception:
            raw_user_id = user_id_from_payload(request)
        raise_internal_error(
            "external_chat",
            e,
            user_id=raw_user_id,
            request_path="/api/v1/chat",
            extra={"request_id": request.request_id, "channel": request.channel},
        )


@app.post("/api/ocr/image")
async def image_text(request: ImageTextRequest):
    started = time.perf_counter()
    try:
        try:
            image_bytes = base64.b64decode(request.image_base64, validate=True)
        except Exception as exc:
            raise HTTPException(status_code=400, detail="image_base64 格式無效") from exc

        result = extract_text_from_image_bytes(
            image_bytes=image_bytes,
            mime_type=request.mime_type,
            prompt=request.prompt,
        )

        return {
            "status": "success",
            "source": request.source,
            "text": result.text,
            "model": result.model,
            "mime_type": result.mime_type,
            "width": result.width,
            "height": result.height,
            "ocr_time_sec": round(time.perf_counter() - started, 3),
            # A custom OCR prompt may be useful for ordinary image analysis,
            # but it cannot create proof for an account-side payment action.
            "receipt_evidence_token": (
                None
                if request.prompt
                else issue_receipt_image_evidence_token(
                    result.text,
                    request.user_id or "",
                )
            ),
        }
    except HTTPException:
        raise
    except ImageTextError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise_internal_error("image_text", e, request_path="/api/ocr/image", extra={"source": request.source})


@app.get("/api/kb/status")
async def kb_status(request: Request):
    require_kb_permission(request)
    documents = list_documents(status="all")
    return {
        "status": "success",
        "document_count": len([item for item in documents if item.get("status") == "active"]),
        "indexed_count": len([
            item for item in documents
            if item.get("status") == "active" and item.get("processing_status") == "indexed"
        ]),
        "documents": with_kb_documents_actor_display_names(documents[:10]),
    }


@app.get("/api/kb/documents")
async def kb_documents(
    request: Request,
    status: str = "active",
    knowledge_base: Optional[str] = None,
):
    require_kb_permission(request, knowledge_base)
    documents = list_documents(status=status, knowledge_base=knowledge_base)
    return {
        "status": "success",
        "documents": with_kb_documents_actor_display_names(documents),
    }


@app.post("/api/kb/documents")
async def kb_upload_document(payload: KnowledgeUploadRequest, request: Request):
    try:
        require_kb_permission(request, payload.knowledge_base, write=True)
        try:
            file_bytes = base64.b64decode(payload.file_base64, validate=True)
        except Exception as exc:
            raise HTTPException(status_code=400, detail="file_base64 格式無效") from exc

        if not KB_DOCUMENT_MUTATION_LOCK.acquire(blocking=False):
            raise HTTPException(
                status_code=409,
                detail="知識庫正在處理其他寫入作業，請等待完成後再試。",
            )
        try:
            document = await asyncio.to_thread(
                create_document,
                file_name=payload.file_name,
                content=file_bytes,
                title=payload.title,
                knowledge_base=payload.knowledge_base,
                category=payload.category,
                status=payload.status,
                uploaded_by=get_actor_username_from_request(request),
            )
            reset_local_searcher_cache()
            return {
                "status": "success" if document.get("processing_status") == "indexed" else "error",
                "document": with_kb_actor_display_names(document),
            }
        finally:
            KB_DOCUMENT_MUTATION_LOCK.release()
    except HTTPException:
        raise
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise_internal_error(
            "kb_upload_document",
            e,
            request_path="/api/kb/documents",
            extra={"file_name": payload.file_name, "knowledge_base": payload.knowledge_base},
        )


@app.post("/api/kb/documents/reindex-all")
async def kb_reindex_all_documents(request: Request):
    try:
        require_kb_permission(request, developer_only=True)
        if not KB_DOCUMENT_MUTATION_LOCK.acquire(blocking=False):
            raise HTTPException(
                status_code=409,
                detail="知識索引正在重建中，請等待完成後再試。",
            )
        try:
            result = await asyncio.to_thread(
                reindex_all_documents,
                indexed_by=get_actor_username_from_request(request),
            )
            reset_local_searcher_cache()
            result["documents"] = with_kb_documents_actor_display_names(result.get("documents") or [])
            return {
                "status": "success" if result.get("failed_count", 0) == 0 else "partial_success",
                **result,
            }
        finally:
            KB_DOCUMENT_MUTATION_LOCK.release()
    except HTTPException:
        raise
    except Exception as e:
        raise_internal_error(
            "kb_reindex_all_documents",
            e,
            request_path="/api/kb/documents/reindex-all",
        )


@app.get("/api/kb/documents/{document_id}")
async def kb_document_detail(document_id: str, request: Request):
    document = get_document(document_id)
    if not document:
        raise HTTPException(status_code=404, detail="找不到指定文件。")
    require_kb_permission(request, document.get("knowledge_base") or "通用")
    return {
        "status": "success",
        "document": with_kb_actor_display_names(document),
    }


@app.get("/api/kb/documents/{document_id}/file")
async def kb_document_file(document_id: str, request: Request, download: bool = False):
    try:
        document = get_document(document_id)
        if not document:
            raise HTTPException(status_code=404, detail="找不到指定文件。")
        require_kb_permission(request, document.get("knowledge_base") or "通用")
        file_path = get_document_file_path(document_id)
        media_type = mimetypes.guess_type(str(file_path))[0] or "application/octet-stream"
        return FileResponse(
            str(file_path),
            media_type=media_type,
            filename=document.get("file_name") or file_path.name,
            content_disposition_type="attachment" if download else "inline",
        )
    except HTTPException as exc:
        if exc.status_code == 401:
            return render_kb_document_auth_error_page(str(exc.detail or "登入狀態已失效。"))
        raise
    except (ValueError, FileNotFoundError) as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise_internal_error(
            "kb_document_file",
            e,
            request_path=f"/api/kb/documents/{document_id}/file",
            extra={"document_id": document_id},
        )


@app.get("/api/kb/documents/{document_id}/preview", response_class=HTMLResponse)
async def kb_document_preview(document_id: str, request: Request):
    try:
        document = get_document(document_id)
        if not document:
            return render_kb_preview_error_page("找不到指定文件，可能是舊連結或文件已被刪除。")
        require_kb_permission(request, document.get("knowledge_base") or "通用")

        title = html.escape(str(document.get("title") or document.get("file_name") or "知識文件"))
        file_name = html.escape(str(document.get("file_name") or "-"))
        knowledge_base = html.escape(str(document.get("knowledge_base") or "-"))
        category = html.escape(str(document.get("category") or "未分類"))
        file_type = str(document.get("file_type") or "").lower()
        content_blocks = []
        original_file_block = ""
        campaign_profile_block = render_campaign_profile_preview(document)

        if file_type == "pdf":
            file_url = html.escape(
                kb_document_file_url(
                    document_id,
                    request.query_params.get("api_token", ""),
                    request.query_params.get("web_auth_token", ""),
                ),
                quote=True,
            )
            original_file_block = f"""
    <section class="pdf-preview">
      <div class="chunk-label">
        <span>原始 PDF 內容</span>
        <span class="pdf-actions">
          <a href="{file_url}" target="_blank" rel="noopener noreferrer">開啟原始 PDF</a>
          <a href="{file_url}" download>下載</a>
        </span>
      </div>
      <iframe src="{file_url}#view=FitH" title="原始 PDF 預覽"></iframe>
    </section>
    <h2>文字索引內容</h2>
"""

        if file_type == "csv":
            body = render_csv_preview_content(document_id)
        else:
            chunks = get_document_chunks(document_id)
            for chunk in chunks:
                label_parts = [f"片段 {chunk.get('chunk_index')}"]
                if chunk.get("page_no"):
                    label_parts.append(f"頁 {chunk.get('page_no')}")
                if chunk.get("section"):
                    label_parts.append(str(chunk.get("section")))
                label = html.escape(" / ".join(label_parts))
                content = render_kb_preview_content(str(chunk.get("content") or ""))
                content_blocks.append(
                    f"<section class='chunk'><div class='chunk-label'>{label}</div>{content}</section>"
                )

            body = "\n".join(content_blocks) or "<p class='empty'>沒有可預覽的文字內容。</p>"
        return HTMLResponse(
            content=f"""<!doctype html>
<html lang="zh-Hant">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{title}</title>
  <style>
    body {{
      margin: 0;
      padding: 32px;
      background: #f6f8fb;
      color: #172033;
      font-family: "Microsoft JhengHei", "Noto Sans TC", Arial, sans-serif;
      line-height: 1.7;
    }}
    main {{
      max-width: 1120px;
      margin: 0 auto;
    }}
    h1 {{
      margin: 0 0 8px;
      font-size: 28px;
      line-height: 1.3;
    }}
    .meta {{
      display: flex;
      flex-wrap: wrap;
      gap: 10px;
      margin: 0 0 24px;
      color: #536179;
      font-size: 14px;
    }}
    .pill {{
      border: 1px solid #d8e0ec;
      border-radius: 999px;
      background: #fff;
      padding: 4px 12px;
    }}
    .chunk {{
      margin: 16px 0;
      border: 1px solid #d8e0ec;
      border-radius: 8px;
      background: #fff;
      overflow: hidden;
    }}
    .campaign-profile {{
      margin: 18px 0 26px;
      padding: 20px;
      border: 1px solid #cbd7e6;
      border-radius: 8px;
      background: #fff;
    }}
    .campaign-profile-heading {{
      display: flex;
      align-items: flex-start;
      justify-content: space-between;
      gap: 16px;
      margin-bottom: 16px;
    }}
    .campaign-profile-heading h2 {{
      margin: 2px 0 0;
    }}
    .campaign-eyebrow {{
      color: #536179;
      font-size: 13px;
      font-weight: 700;
    }}
    .campaign-status {{
      flex: 0 0 auto;
      padding: 4px 11px;
      border: 1px solid;
      border-radius: 999px;
      font-size: 13px;
      font-weight: 800;
    }}
    .campaign-status.complete {{
      color: #146c43;
      border-color: #8fd4b0;
      background: #eaf8f0;
    }}
    .campaign-status.review {{
      color: #8a4b08;
      border-color: #e7bf80;
      background: #fff7e8;
    }}
    .campaign-grid {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
      gap: 12px;
    }}
    .campaign-field {{
      min-width: 0;
      padding: 12px 14px;
      border: 1px solid #e2e8f0;
      border-radius: 6px;
      background: #f8fafc;
    }}
    .campaign-field-label {{
      margin-bottom: 3px;
      color: #536179;
      font-size: 12px;
      font-weight: 700;
    }}
    .campaign-field-value {{
      overflow-wrap: anywhere;
      font-weight: 700;
    }}
    .campaign-review-note {{
      margin-top: 14px;
      padding: 10px 12px;
      border-left: 3px solid #d58b20;
      background: #fff7e8;
      color: #74410b;
    }}
    .pdf-preview {{
      margin: 16px 0 24px;
      border: 1px solid #d8e0ec;
      border-radius: 8px;
      background: #fff;
      overflow: hidden;
    }}
    .pdf-preview iframe {{
      display: block;
      width: 100%;
      height: min(78vh, 880px);
      border: 0;
      background: #fff;
    }}
    h2 {{
      margin: 28px 0 10px;
      font-size: 20px;
    }}
    .chunk-label {{
      padding: 10px 14px;
      border-bottom: 1px solid #e7edf5;
      color: #536179;
      font-size: 13px;
      background: #fbfcfe;
    }}
    .pdf-preview .chunk-label {{
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 12px;
      flex-wrap: wrap;
    }}
    .pdf-actions {{
      display: inline-flex;
      gap: 8px;
      flex-wrap: wrap;
    }}
    .pdf-actions a {{
      color: #31557f;
      text-decoration: none;
      border: 1px solid #bfd0e5;
      border-radius: 6px;
      background: #fff;
      padding: 2px 10px;
      font-weight: 700;
    }}
    .pdf-actions a:hover {{
      background: #eef4fb;
    }}
    pre {{
      margin: 0;
      padding: 16px;
      white-space: pre-wrap;
      word-break: break-word;
      font: inherit;
    }}
    .fields {{
      padding: 4px 0;
    }}
    .field-block {{
      padding: 14px 16px;
      border-bottom: 1px solid #edf1f7;
    }}
    .field-block:last-child {{
      border-bottom: 0;
    }}
    .field-label {{
      margin-bottom: 6px;
      color: #31557f;
      font-weight: 700;
    }}
    .field-value {{
      white-space: pre-wrap;
      word-break: break-word;
    }}
    .empty {{
      color: #536179;
      padding: 16px;
    }}
  </style>
</head>
<body>
  <main>
    <h1>{title}</h1>
    <div class="meta">
      <span class="pill">檔名：{file_name}</span>
      <span class="pill">知識庫：{knowledge_base}</span>
      <span class="pill">分類：{category}</span>
    </div>
    {campaign_profile_block}
    {original_file_block}
    {body}
  </main>
</body>
</html>""",
            status_code=200,
        )
    except HTTPException as exc:
        if exc.status_code == 401:
            return render_kb_document_auth_error_page(str(exc.detail or "登入狀態已失效。"))
        raise
    except (ValueError, FileNotFoundError) as e:
        return render_kb_preview_error_page(str(e))
    except Exception as e:
        raise_internal_error(
            "kb_document_preview",
            e,
            request_path=f"/api/kb/documents/{document_id}/preview",
            extra={"document_id": document_id},
        )


@app.get("/api/kb/documents/{document_id}/chunks")
async def kb_document_chunks(document_id: str, request: Request):
    try:
        document = get_document(document_id)
        if not document:
            raise ValueError("找不到指定文件。")
        require_kb_permission(request, document.get("knowledge_base") or "通用")
        return {
            "status": "success",
            "chunks": get_document_chunks(document_id),
        }
    except HTTPException:
        raise
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise_internal_error(
            "kb_document_chunks",
            e,
            request_path=f"/api/kb/documents/{document_id}/chunks",
            extra={"document_id": document_id},
        )


@app.post("/api/kb/documents/{document_id}/reindex")
async def kb_reindex_document(document_id: str, request: Request):
    try:
        existing_document = get_document(document_id)
        if not existing_document:
            raise ValueError("找不到指定文件。")
        require_kb_permission(
            request,
            existing_document.get("knowledge_base") or "通用",
            write=True,
        )
        if not KB_DOCUMENT_MUTATION_LOCK.acquire(blocking=False):
            raise HTTPException(
                status_code=409,
                detail="知識索引正在重建中，請等待完成後再試。",
            )
        try:
            document = await asyncio.to_thread(
                reindex_document,
                document_id,
                indexed_by=get_actor_username_from_request(request),
            )
            reset_local_searcher_cache()
            return {
                "status": "success" if document.get("processing_status") == "indexed" else "error",
                "document": with_kb_actor_display_names(document),
            }
        finally:
            KB_DOCUMENT_MUTATION_LOCK.release()
    except HTTPException:
        raise
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise_internal_error(
            "kb_reindex_document",
            e,
            request_path=f"/api/kb/documents/{document_id}/reindex",
            extra={"document_id": document_id},
        )


@app.delete("/api/kb/documents/{document_id}")
async def kb_delete_document(document_id: str, request: Request):
    try:
        existing_document = get_document(document_id)
        if not existing_document:
            raise ValueError("找不到指定文件。")
        account = require_kb_permission(
            request,
            existing_document.get("knowledge_base") or "通用",
            write=True,
        )
        actor_username = (
            str(account.get("username") or "")
            if account
            else get_actor_username_from_request(request)
        )
        if not KB_DOCUMENT_MUTATION_LOCK.acquire(blocking=False):
            raise HTTPException(
                status_code=409,
                detail="知識庫正在處理其他寫入作業，請等待完成後再試。",
            )
        try:
            document = await asyncio.to_thread(
                delete_document,
                document_id,
                deleted_by=actor_username,
            )
            web_account_service.log_audit(
                actor_username,
                "delete_kb_document",
                document_id,
                {
                    "document_id": document_id,
                    "title": existing_document.get("title") or "",
                    "file_name": existing_document.get("file_name") or "",
                    "knowledge_base": existing_document.get("knowledge_base") or "通用",
                    "uploaded_by": existing_document.get("uploaded_by") or "",
                    "actor_display_name": (
                        str(account.get("display_name") or "") if account else actor_username
                    ),
                },
            )
            reset_local_searcher_cache()
            return {
                "status": "success",
                "document": with_kb_actor_display_names(document),
            }
        finally:
            KB_DOCUMENT_MUTATION_LOCK.release()
    except HTTPException:
        raise
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise_internal_error(
            "kb_delete_document",
            e,
            request_path=f"/api/kb/documents/{document_id}",
            extra={"document_id": document_id},
        )


@app.get("/api/kb/audit-logs")
async def kb_audit_logs(
    request: Request,
    action: str = "delete_kb_document",
    limit: int = 200,
):
    require_kb_permission(request)
    records = web_account_service.list_audit_logs(action=action or None, limit=limit)
    return {
        "status": "success",
        "records": records,
        "count": len(records),
    }


@app.post("/api/kb/search")
async def kb_search(request: KnowledgeSearchRequest):
    try:
        from app.services.kb_service import load_local_searcher

        searcher = load_local_searcher()
        docs = searcher.search(
            request.plan_name,
            top_k=max(1, min(request.limit, 20)),
            knowledge_base=request.knowledge_base,
            category=request.category,
        )
        sources = [
            normalize_rag_source(
                {
                    "document_id": doc.get("document_id"),
                    "chunk_id": doc.get("id"),
                    "source": doc.get("source"),
                    "title": doc.get("title") or doc.get("question"),
                    "knowledge_base": doc.get("company") or request.knowledge_base,
                    "category": doc.get("category"),
                    "record_type": doc.get("record_type"),
                    "document_type": doc.get("document_type"),
                    "campaign_name": doc.get("campaign_name"),
                    "campaign_aliases": doc.get("campaign_aliases"),
                    "campaign_sections": doc.get("campaign_sections"),
                    "service_types": doc.get("service_types"),
                    "speeds": doc.get("speeds"),
                    "contract_months": doc.get("contract_months"),
                    "payment_terms": doc.get("payment_terms"),
                    "customer_types": doc.get("customer_types"),
                    "valid_period": doc.get("valid_period"),
                    "occasion_terms": doc.get("occasion_terms"),
                    "gift_items": doc.get("gift_items"),
                    "lottery_details": doc.get("lottery_details"),
                    "score": doc.get("_score"),
                    "content": doc.get("answer"),
                    "page_no": doc.get("page_no"),
                    "section": doc.get("section"),
                },
                request.plan_name,
                request.knowledge_base,
            )
            for doc in docs
        ]
        sources = filter_docs_to_active_manifest_sources(
            sources,
            [request.knowledge_base],
        )
        return {
            "status": "success",
            "retrieval_pipeline_version": "faq-fallback-v2",
            "plan_name": request.plan_name,
            "knowledge_base": request.knowledge_base,
            "limit": request.limit,
            "count": len(sources),
            "sources": sources,
        }
    except Exception as e:
        raise_internal_error(
            "kb_search",
            e,
            request_path="/api/kb/search",
            extra={"plan_name": request.plan_name, "knowledge_base": request.knowledge_base},
        )


@app.post("/api/kb/chat-search")
async def kb_chat_search(request: KnowledgeSearchRequest):
    try:
        from app.config.settings import RAG_BACKEND
        from app.services.kb_answer_guard import filter_answerable_docs
        from app.services.kb_service import match_active_campaign_alias, retrieve_knowledge

        knowledge_base = (request.knowledge_base or "通用").strip() or "通用"
        # Keep the explicitly selected knowledge base as the source of truth
        # so station-scoped diagnostics include their configured common area.
        # Display names and aliases (for example 台灣佳光 / 西海岸) can then
        # resolve their shared common scope through the normal KB policy.
        memory = {"knowledge_base": knowledge_base}
        if knowledge_base != "通用":
            memory["company"] = knowledge_base

        docs = retrieve_knowledge(
            request.plan_name,
            memory,
            {"knowledge_query": request.plan_name},
            top_k=max(1, min(request.limit, 20)),
        )
        answerable_docs = filter_answerable_docs(request.plan_name, docs)
        campaign_match = match_active_campaign_alias(request.plan_name, memory)
        return {
            "status": "success",
            "retrieval_pipeline_version": "faq-fallback-v3",
            "plan_name": request.plan_name,
            "knowledge_base": knowledge_base,
            "rag_backend": RAG_BACKEND,
            "limit": request.limit,
            "count": len(docs),
            "answerable_count": len(answerable_docs),
            "guard_rejected_count": max(0, len(docs) - len(answerable_docs)),
            "indexed_campaign_match": campaign_match,
            "sources": docs,
            "answerable_sources": answerable_docs,
        }
    except Exception as e:
        raise_internal_error(
            "kb_chat_search",
            e,
            request_path="/api/kb/chat-search",
            extra={"plan_name": request.plan_name, "knowledge_base": request.knowledge_base},
        )


@app.post("/api/line/{bot_code}/webhook")
async def line_webhook(request: Request, bot_code: str):
    bot_config = get_line_bot_config(bot_code)
    body = await request.body()
    signature = request.headers.get("X-Line-Signature")

    if not validate_line_signature(body, signature, bot_config):
        raise HTTPException(status_code=403, detail="Invalid LINE signature")

    try:
        payload = json.loads(body.decode("utf-8") or "{}")
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=400, detail="Invalid JSON payload") from exc

    events = payload.get("events", [])
    results = []

    for event in events:
        line_message = extract_line_message(event)
        line_user_id = line_message.get("user_id") or "unknown"
        user_id = normalize_channel_user_id(f"line:{bot_config['bot_code']}", line_user_id)
        customer_key = build_line_customer_key(line_user_id)
        reply_token = line_message.get("reply_token")

        if not line_message.get("supported"):
            reason = line_message.get("reason")
            reply = "抱歉，目前這個 LINE 入口先支援文字與圖片訊息。"

            reply_line_message(reply_token, reply, bot_config)
            results.append({
                "user_id": user_id,
                "line_bot_code": bot_config["bot_code"],
                "status": "ignored",
                "reason": reason,
                "reply_sent": bool(reply_token),
                "ai_response": reply,
            })
            continue

        user_text = (line_message.get("text") or "").strip()
        line_receipt_evidence = None
        line_receipt_attempt = None
        if line_message.get("message_type") == "image":
            try:
                image_bytes, mime_type = get_line_message_content(
                    line_message.get("message_id"),
                    bot_config,
                )
                image_result = extract_text_from_image_bytes(
                    image_bytes=image_bytes,
                    mime_type=mime_type,
                )
                user_text = image_result.text
                line_receipt_evidence = build_line_receipt_image_evidence(user_text)
                line_receipt_attempt = build_line_receipt_image_attempt(user_text)
            except Exception as exc:
                log_exception(
                    "line_image_ocr",
                    exc,
                    user_id=user_id,
                    request_path=f"/api/line/{bot_code}/webhook",
                    extra={"line_bot_code": bot_config.get("bot_code")},
                )
                reply = f"圖片分析失敗：{exc}"
                reply_line_message(reply_token, reply, bot_config)
                results.append({
                    "user_id": user_id,
                    "line_bot_code": bot_config["bot_code"],
                    "status": "image_ocr_failed",
                    "ai_response": reply,
                })
                continue

        if not user_text:
            reply = "抱歉，我沒有讀到文字內容，請再傳一次。"
            reply_line_message(reply_token, reply, bot_config)
            results.append({
                "user_id": user_id,
                "line_bot_code": bot_config["bot_code"],
                "status": "empty_message",
                "ai_response": reply,
            })
            continue

        memory = get_session_memory(user_id)
        if customer_key:
            memory["customer_key"] = customer_key
        channel_context = memory.setdefault("channel_context", {})
        channel_context.update({
            "channel": "line",
            "line_bot_code": bot_config.get("bot_code"),
            "line_bot_name": bot_config.get("display_name"),
            "customer_key": customer_key,
        })

        if is_human_mode_active(memory):
            save_chat_log(user_id, "user", user_text)
            forward_sent = push_line_message(
                bot_config.get("human_group_id"),
                build_human_forward_text(bot_config, line_user_id, user_text),
                bot_config,
                use_human_token=True,
            )
            save_session_memory(user_id, memory)

            results.append({
                "user_id": user_id,
                "line_bot_code": bot_config["bot_code"],
                "status": "human_mode_forwarded",
                "human_forward_sent": forward_sent,
                "channel_context": memory.get("channel_context", {}),
            })
            continue

        memory, company_prompt = apply_line_channel_context(
            memory,
            user_text,
            bot_config,
            customer_key=customer_key,
            user_id=user_id,
        )

        if line_receipt_attempt:
            memory.setdefault("known_info", {})["receipt_image_ocr_attempt"] = line_receipt_attempt
        if line_receipt_evidence:
            memory.setdefault("known_info", {})["receipt_image_evidence"] = line_receipt_evidence

        if company_prompt:
            save_chat_log(user_id, "user", user_text)
            save_session_memory(user_id, memory)
            save_chat_log(user_id, "assistant", company_prompt)
            reply_line_message(reply_token, company_prompt, bot_config)
            results.append({
                "user_id": user_id,
                "line_bot_code": bot_config["bot_code"],
                "status": "needs_company",
                "ai_response": company_prompt,
                "company_code": memory.get("company_code"),
                "channel_context": memory.get("channel_context", {}),
            })
            continue

        result = run_core_chat(user_id, user_text, memory, persist=False)

        if is_human_handoff_result(result):
            save_chat_log(user_id, "user", user_text)
            memory = activate_human_mode(result.get("memory") or memory, bot_config)
            save_session_memory(user_id, memory)

            history = get_recent_chat_history(user_id, limit=10)
            alert_sent = push_line_message(
                bot_config.get("human_group_id"),
                build_human_alert_text(bot_config, line_user_id, user_text, history),
                bot_config,
                use_human_token=True,
            )

            reply = "已為您切換真人客服模式。"
            save_chat_log(user_id, "assistant", reply)
            reply_line_message(reply_token, reply, bot_config)

            results.append({
                "user_id": user_id,
                "line_bot_code": bot_config["bot_code"],
                "status": "human_mode_activated",
                "human_alert_sent": alert_sent,
                "ai_response": reply,
                "channel_context": memory.get("channel_context", {}),
            })
            continue

        save_chat_log(user_id, "user", user_text)
        save_session_memory(user_id, result.get("memory") or memory)
        save_chat_log(user_id, "assistant", result.get("ai_response", ""))
        response = build_chat_response(result)
        reply_line_message(reply_token, result.get("ai_response", ""), bot_config)

        results.append({
            "user_id": user_id,
            "line_bot_code": bot_config["bot_code"],
            **response,
        })

    return {
        "status": "ok",
        "line_bot_code": bot_config["bot_code"],
        "line_bot_name": bot_config.get("display_name"),
        "events": len(events),
        "results": results,
    }


@app.post("/feedback")
async def feedback(request: FeedbackRequest):
    try:
        memory = get_session_memory(request.user_id)
        memory = apply_company_to_memory(memory, request.tv_cable)

        result = save_feedback(
            user_id=request.user_id,
            tv_cable=request.tv_cable,
            feedback_type=request.feedback_type,
            suggestion=request.suggestion,
            user_message=request.user_message,
            ai_response=request.ai_response,
            conversation=request.conversation,
            memory=memory,
        )

        return {
            "status": "success",
            "message": "已儲存回饋。",
            **result,
        }
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise_internal_error("feedback", e, user_id=request.user_id, request_path="/feedback")


@app.get("/api/feedback-tracker/overview")
async def feedback_tracker_overview(
    request: Request,
    start_date: str = "2026-08-24",
    end_date: Optional[str] = None,
    feedback_status: Optional[str] = None,
    feedback_review_status: Optional[str] = None,
    company_code: Optional[str] = None,
    feedback_type: Optional[str] = None,
    case_status: Optional[str] = None,
    case_review_status: Optional[str] = None,
    case_priority: Optional[str] = None,
):
    require_feedback_permission(request)
    bootstrap = bootstrap_tracker_data(start_date)
    feedback_items = list_feedback_items(
        start_date=start_date,
        end_date=end_date,
        status=feedback_status,
        review_status=feedback_review_status,
        company_code=company_code,
        feedback_type=feedback_type,
        include_merged=False,
    )
    regression_cases = list_regression_cases(
        status=case_status,
        review_status=case_review_status,
        priority=case_priority,
    )
    return {
        "status": "success",
        "bootstrap": bootstrap,
        "feedback_items": feedback_items,
        "regression_cases": regression_cases,
    }


@app.put("/api/feedback-tracker/feedback/{feedback_id}")
async def update_feedback_tracker_item(
    feedback_id: str,
    payload: FeedbackTrackerUpdateRequest,
    request: Request,
):
    account = require_feedback_permission(request)
    actor = str((account or {}).get("username") or "system")
    return update_feedback_item(feedback_id, payload.model_dump(), actor)


@app.put("/api/feedback-tracker/cases/{case_id}")
async def update_feedback_tracker_case(
    case_id: str,
    payload: RegressionCaseUpdateRequest,
    request: Request,
):
    account = require_feedback_permission(request)
    actor = str((account or {}).get("username") or "system")
    return update_regression_case(case_id, payload.model_dump(), actor)


@app.post("/api/feedback-tracker/sync/pull")
async def pull_feedback_tracker_updates(request: Request):
    require_developer_feedback_permission(request)
    try:
        return pull_online_feedback()
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@app.post("/api/feedback-tracker/sync/publish")
async def publish_feedback_tracker_updates(request: Request):
    require_developer_feedback_permission(request)
    try:
        return publish_tracking_updates()
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@app.get("/api/feedback-tracker/sync/remote/feedback")
async def remote_feedback_tracker_source(
    request: Request,
    start_date: str = "2026-08-24",
    feedback_after: Optional[str] = None,
    conversation_after: Optional[str] = None,
    latency_after: Optional[str] = None,
):
    require_tracker_sync_token(request)
    feedback_records = load_feedback_csv_records(start_date, after=feedback_after, limit=20000)
    conversation_logs = load_conversation_log_records(start_date, after=conversation_after)
    latency_logs = load_latency_log_records(start_date, after=latency_after)
    return {
        "status": "success",
        "feedback_records": feedback_records,
        "feedback_cursor": max(
            (str(record.get("created_at") or "") for record in feedback_records), default=None,
        ),
        "feedback_truncated": len(feedback_records) >= 20000,
        "conversation_logs": conversation_logs,
        "conversation_logs_total": len(conversation_logs),
        "conversation_logs_truncated": len(conversation_logs) >= 20000,
        "conversation_cursor": max(
            (str(record.get("created_at") or "") for record in conversation_logs), default=None,
        ),
        "latency_logs": latency_logs,
        "latency_logs_total": len(latency_logs),
        "latency_logs_truncated": len(latency_logs) >= 20000,
        "latency_cursor": max(
            (str(record.get("timestamp") or "") for record in latency_logs), default=None,
        ),
        "tracking_updates": build_tracking_state_bundle(),
    }


@app.post("/api/feedback-tracker/sync/remote/states")
async def receive_remote_feedback_tracker_states(request: Request):
    require_tracker_sync_token(request)
    try:
        payload = await request.json()
        return {"status": "success", "applied": apply_tracking_update_bundle(payload)}
    except (ValueError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@app.get("/feedback/export")
async def export_feedback_csv():
    csv_path = get_feedback_csv_path()
    return FileResponse(
        csv_path,
        media_type="text/csv",
        filename="ai_feedback.csv",
    )


if __name__ == "__main__":
    import uvicorn
    print("啟動後端服務：http://127.0.0.1:8123")
    uvicorn.run("app.app_backend:app", host="127.0.0.1", port=8123, reload=False)
