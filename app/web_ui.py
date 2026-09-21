import base64
import difflib
import html
import json
import logging
import os
import re
import sys
import time
import uuid
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import parse_qsl, quote, urlencode, urlsplit, urlunsplit

import requests
import streamlit as st
import streamlit.components.v1 as components


class _ComponentsHtmlDeprecationFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        return "st.components.v1.html" not in record.getMessage()


logging.getLogger("streamlit.deprecation_util").addFilter(_ComponentsHtmlDeprecationFilter())


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.config.env_loader import load_app_environment  # noqa: E402


WEB_UI_ENV_FILE = load_app_environment(PROJECT_ROOT)

from app.services.company_profile import (  # noqa: E402
    INSTALL_REPORT_URL,
    LINE_TV_HELP_URL,
    REPAIR_REPORT_URL,
)
from app.config.settings import WEB_AUTH_ENABLED  # noqa: E402
from app.services.web_account_service import (  # noqa: E402
    PERMISSION_ACCOUNT_MANAGEMENT,
    PERMISSION_COMPANY_PROFILES,
    PERMISSION_FEEDBACK,
    PERMISSION_IMAGE_OCR,
    PERMISSION_KNOWLEDGE_BASE,
    ROLE_DEVELOPER,
    ROLE_STAFF,
    ROLE_SUPERVISOR,
    ROLE_LABELS,
    VALID_ROLES,
    WebAccountError,
    WebAccountService,
    can_manage_knowledge_base,
    can_view_knowledge_base,
    has_permission,
    role_label,
)
from app.services.knowledge_base_policy import (  # noqa: E402
    CENTRAL_COMMON_KNOWLEDGE_BASE,
    LEGACY_COMMON_KNOWLEDGE_BASE,
    REGIONAL_COMMON_KNOWLEDGE_BASES,
    normalize_knowledge_base_name,
)
from app.services.text_rendering import (  # noqa: E402
    escape_streamlit_markdown_literals,
    html_anchors_to_markdown,
    text_linebreaks_to_html,
)

API_BASE = os.getenv("WEB_BACKEND_API_BASE_URL", "http://127.0.0.1:8123").rstrip("/")
WEB_BACKEND_API_TOKEN = (
    os.getenv("WEB_BACKEND_API_TOKEN", "").strip()
    or os.getenv("API_AUTH_TOKEN", "").strip()
)
WEB_BACKEND_API_AUTH_HEADER = (
    os.getenv("WEB_BACKEND_API_AUTH_HEADER", "").strip()
    or os.getenv("API_AUTH_HEADER", "X-API-Token").strip()
    or "X-API-Token"
)
WEB_BACKEND_API_AUTH_NAME = (
    os.getenv("WEB_BACKEND_API_AUTH_NAME", "").strip()
    or os.getenv("API_AUTH_NAME", "").strip()
)
WEB_BACKEND_API_AUTH_PASSWORD = (
    os.getenv("WEB_BACKEND_API_AUTH_PASSWORD", "").strip()
    or os.getenv("API_AUTH_PASSWORD", "").strip()
)
_BACKEND_API_TOKEN_CACHE = {
    "token": "",
    "expires_at": 0,
}


def normalize_public_api_base(url: str) -> str:
    value = str(url or "").strip().rstrip("/")
    return value


PUBLIC_API_BASE = normalize_public_api_base(os.getenv("WEB_PUBLIC_API_BASE_URL", "")) or API_BASE
DEFAULT_TV_CABLE = "tdtv"
WEB_AUTH_STORAGE_KEY = "custAppWebAuthToken"
WEB_AUTH_QUERY_PARAM = "web_auth_token"
UI_THEME_STORAGE_KEY = "custAppUiThemeMode"
UI_THEME_QUERY_PARAM = "ui_theme"
KB_DOWNLOAD_SCROLL_STORAGE_KEY = "custAppKbDownloadScrollPosition"
DISPLAY_TIMEZONE = timezone(timedelta(hours=8))
FALLBACK_COMPANIES = [
    {"code": "tdtv", "label": "tdtv - 大屯有線", "company_name": "大屯有線", "class": "大屯"},
]
BASE_DISPLAY_ALIASES = {
    "西海岸": "台灣佳光",
    LEGACY_COMMON_KNOWLEDGE_BASE: CENTRAL_COMMON_KNOWLEDGE_BASE,
}
BASE_DISPLAY_ORDER = [
    *REGIONAL_COMMON_KNOWLEDGE_BASES,
    "大屯",
    "台灣佳光",
    "佳光市區",
    "中投",
    "佳聯",
    "北港",
    "大揚",
    "新永安",
    "台基科",
]


def display_base_name(name: str) -> str:
    clean_name = str(name or "").strip()
    return BASE_DISPLAY_ALIASES.get(clean_name, clean_name)


def base_display_order_index(name: str) -> int:
    display_name = display_base_name(name)
    try:
        return BASE_DISPLAY_ORDER.index(display_name)
    except ValueError:
        return len(BASE_DISPLAY_ORDER)


def render_hidden_html(source: str, height: int = 0, width: int = 0):
    return components.html(source, height=height, width=width)


def get_query_param_value(name: str) -> str:
    try:
        value = st.query_params.get(name)
    except Exception:
        try:
            params = st.experimental_get_query_params()
            value = params.get(name)
        except Exception:
            return ""

    if isinstance(value, list):
        return str(value[0] if value else "").strip()
    return str(value or "").strip()


def set_query_param_value(name: str, value: str) -> None:
    clean_value = str(value or "").strip()
    try:
        if clean_value:
            st.query_params[name] = clean_value
        elif name in st.query_params:
            del st.query_params[name]
        return
    except Exception:
        pass

    try:
        params = st.experimental_get_query_params()
        if clean_value:
            params[name] = clean_value
        else:
            params.pop(name, None)
        st.experimental_set_query_params(**params)
    except Exception:
        pass


def remember_web_auth_token(token: str) -> None:
    st.session_state.web_auth_token_to_persist = str(token or "")
    st.session_state.web_auth_clear_storage = False
    set_query_param_value(WEB_AUTH_QUERY_PARAM, token)


def clear_persisted_web_auth_token() -> None:
    st.session_state.web_auth_token_to_persist = ""
    st.session_state.web_auth_clear_storage = True
    set_query_param_value(WEB_AUTH_QUERY_PARAM, "")


def normalize_ui_theme_mode(value: str) -> str:
    clean_value = str(value or "").strip().lower()
    return clean_value if clean_value in {"dark", "light"} else ""


def set_ui_theme_mode(mode: str) -> None:
    normalized = normalize_ui_theme_mode(mode) or "dark"
    st.session_state.ui_theme_mode = normalized
    set_query_param_value(UI_THEME_QUERY_PARAM, normalized)


def render_ui_theme_storage_bridge() -> None:
    current_theme = normalize_ui_theme_mode(st.session_state.get("ui_theme_mode")) or "dark"
    render_hidden_html(
        f"""
        <script>
        (() => {{
            const parentWindow = window.parent;
            const storageKey = {json.dumps(UI_THEME_STORAGE_KEY)};
            const queryParam = {json.dumps(UI_THEME_QUERY_PARAM)};
            const currentTheme = {json.dumps(current_theme)};
            const validThemes = new Set(["dark", "light"]);

            const url = new URL(parentWindow.location.href);
            const urlTheme = (url.searchParams.get(queryParam) || "").toLowerCase();
            const storedTheme = (parentWindow.localStorage.getItem(storageKey) || "").toLowerCase();

            const updateQueryParam = (theme, shouldReload) => {{
                if (!validThemes.has(theme)) {{
                    return;
                }}
                const nextUrl = new URL(parentWindow.location.href);
                if (nextUrl.searchParams.get(queryParam) === theme) {{
                    return;
                }}
                nextUrl.searchParams.set(queryParam, theme);
                const nextPath = `${{nextUrl.pathname}}${{nextUrl.search}}${{nextUrl.hash}}`;
                if (shouldReload) {{
                    parentWindow.location.replace(nextPath);
                }} else {{
                    parentWindow.history.replaceState(null, "", nextPath);
                }}
            }};

            if (validThemes.has(urlTheme)) {{
                parentWindow.localStorage.setItem(storageKey, urlTheme);
                return;
            }}

            if (validThemes.has(storedTheme)) {{
                updateQueryParam(storedTheme, true);
                return;
            }}

            if (validThemes.has(currentTheme)) {{
                parentWindow.localStorage.setItem(storageKey, currentTheme);
                updateQueryParam(currentTheme, false);
            }}
        }})();
        </script>
        """,
        height=0,
        width=0,
    )


def render_web_auth_storage_bridge() -> None:
    if not WEB_AUTH_ENABLED:
        return

    persist_token = str(st.session_state.get("web_auth_token_to_persist") or "")
    session_token = str(st.session_state.get("web_auth_token") or "")
    clear_storage = bool(st.session_state.get("web_auth_clear_storage"))
    render_hidden_html(
        f"""
        <script>
        (() => {{
            const parentWindow = window.parent;
            const storageKey = {json.dumps(WEB_AUTH_STORAGE_KEY)};
            const queryParam = {json.dumps(WEB_AUTH_QUERY_PARAM)};
            const persistToken = {json.dumps(persist_token)};
            const sessionToken = {json.dumps(session_token)};
            const clearStorage = {json.dumps(clear_storage)};

            const updateAuthQueryParam = (token) => {{
                const url = new URL(parentWindow.location.href);
                const currentToken = url.searchParams.get(queryParam) || "";
                if (!token) {{
                    if (!currentToken) {{
                        return;
                    }}
                    url.searchParams.delete(queryParam);
                }} else {{
                    if (currentToken === token) {{
                        return;
                    }}
                    url.searchParams.set(queryParam, token);
                }}
                const nextUrl = `${{url.pathname}}${{url.search}}${{url.hash}}`;
                parentWindow.history.replaceState(null, "", nextUrl);
            }};

            const redirectWithAuthQueryParam = (token) => {{
                const url = new URL(parentWindow.location.href);
                if (url.searchParams.get(queryParam) === token) {{
                    return;
                }}
                url.searchParams.set(queryParam, token);
                parentWindow.location.replace(`${{url.pathname}}${{url.search}}${{url.hash}}`);
            }};

            if (clearStorage) {{
                parentWindow.localStorage.removeItem(storageKey);
                updateAuthQueryParam("");
                return;
            }}

            if (persistToken) {{
                parentWindow.localStorage.setItem(storageKey, persistToken);
                updateAuthQueryParam(persistToken);
                return;
            }}

            if (sessionToken) {{
                parentWindow.localStorage.setItem(storageKey, sessionToken);
                updateAuthQueryParam(sessionToken);
                return;
            }}

            const storedToken = parentWindow.localStorage.getItem(storageKey) || "";
            if (!storedToken) {{
                return;
            }}

            redirectWithAuthQueryParam(storedToken);
        }})();
        </script>
        """,
        height=0,
        width=0,
    )
    if persist_token:
        st.session_state.web_auth_token_to_persist = ""


def render_kb_download_scroll_memory_bridge(skip_initial_record: bool = False) -> None:
    render_hidden_html(
        f"""
        <script>
        (() => {{
            const parentWindow = window.parent;
            const parentDocument = parentWindow.document;
            const storageKey = {json.dumps(KB_DOWNLOAD_SCROLL_STORAGE_KEY)};
            const frozenStorageKey = `${{storageKey}}:frozen`;
            const skipInitialRecord = {json.dumps(bool(skip_initial_record))};

            const scrollTargets = () => [
                parentDocument.scrollingElement,
                parentDocument.documentElement,
                parentDocument.body,
                parentDocument.querySelector('[data-testid="stAppViewContainer"]'),
                parentDocument.querySelector('[data-testid="stMain"]'),
                parentDocument.querySelector('section.main')
            ].filter(Boolean);

            const currentPosition = () => {{
                const tops = [parentWindow.scrollY || 0];
                const lefts = [parentWindow.scrollX || 0];
                scrollTargets().forEach((element) => {{
                    tops.push(element.scrollTop || 0);
                    lefts.push(element.scrollLeft || 0);
                }});
                return {{
                    top: Math.max(...tops),
                    left: Math.max(...lefts),
                    updatedAt: Date.now()
                }};
            }};

            const findDocumentMarker = (button) => {{
                const card = button?.closest?.('[data-testid="stVerticalBlockBorderWrapper"]');
                if (card) {{
                    const marker = card.querySelector(".kb-doc-card-marker[data-kb-doc-id]");
                    if (marker) {{
                        return marker;
                    }}
                }}
                return Array.from(
                    parentDocument.querySelectorAll(".kb-doc-card-marker[data-kb-doc-id]")
                ).find((marker) => {{
                    const wrapper = marker.closest('[data-testid="stVerticalBlockBorderWrapper"]');
                    return wrapper?.contains(button);
                }}) || null;
            }};

            const recordPosition = () => {{
                try {{
                    parentWindow.sessionStorage.setItem(storageKey, JSON.stringify(currentPosition()));
                }} catch (error) {{
                    // Session storage may be unavailable in restricted browser modes.
                }}
            }};

            const freezePosition = (button) => {{
                const saved = currentPosition();
                const marker = findDocumentMarker(button);
                if (marker) {{
                    saved.anchorId = marker.dataset.kbDocId || "";
                    saved.anchorViewportTop = marker.getBoundingClientRect().top;
                }}
                try {{
                    parentWindow.sessionStorage.setItem(
                        frozenStorageKey,
                        JSON.stringify(saved)
                    );
                }} catch (error) {{
                    // Session storage may be unavailable in restricted browser modes.
                }}
            }};

            const restorePosition = () => {{
                let saved = null;
                try {{
                    saved = JSON.parse(
                        parentWindow.sessionStorage.getItem(frozenStorageKey)
                        || parentWindow.sessionStorage.getItem(storageKey)
                        || "null"
                    );
                }} catch (error) {{
                    saved = null;
                }}
                if (!saved || typeof saved.top !== "number") {{
                    return;
                }}

                const savedAnchorId = String(saved.anchorId || "");
                const anchor = savedAnchorId
                    ? Array.from(
                        parentDocument.querySelectorAll(".kb-doc-card-marker[data-kb-doc-id]")
                    ).find((marker) => marker.dataset.kbDocId === savedAnchorId)
                    : null;

                if (anchor && Number.isFinite(saved.anchorViewportTop)) {{
                    const delta = anchor.getBoundingClientRect().top - saved.anchorViewportTop;
                    if (Math.abs(delta) >= 1) {{
                        const scrollableTarget = scrollTargets().find((element) => (
                            element.scrollHeight > element.clientHeight + 1
                            && element.scrollTop > 0
                        ));
                        if (
                            !scrollableTarget
                            || scrollableTarget === parentDocument.scrollingElement
                            || scrollableTarget === parentDocument.documentElement
                            || scrollableTarget === parentDocument.body
                        ) {{
                            parentWindow.scrollBy({{ top: delta, left: 0, behavior: "instant" }});
                        }} else {{
                            scrollableTarget.scrollTop += delta;
                        }}
                    }}
                }} else {{
                    const top = Math.max(0, saved.top || 0);
                    const left = Math.max(0, saved.left || 0);
                    parentWindow.scrollTo({{ top, left, behavior: "instant" }});
                    scrollTargets().forEach((element) => {{
                        element.scrollTop = top;
                        element.scrollLeft = left;
                    }});
                }}
                try {{
                    parentWindow.sessionStorage.removeItem(frozenStorageKey);
                }} catch (error) {{
                    // Session storage may be unavailable in restricted browser modes.
                }}
            }};

            parentWindow.__custAppRecordKbScrollPosition = recordPosition;
            parentWindow.__custAppFreezeKbScrollPosition = freezePosition;
            parentWindow.__custAppRestoreKbScrollPosition = restorePosition;

            if (!parentDocument.__custAppKbDownloadScrollMemoryBridgeV3) {{
                parentDocument.__custAppKbDownloadScrollMemoryBridgeV3 = true;
                parentWindow.addEventListener("scroll", recordPosition, {{ passive: true }});
                parentDocument.addEventListener("scroll", recordPosition, true);
                parentWindow.addEventListener("resize", recordPosition, {{ passive: true }});
                parentDocument.addEventListener("click", (event) => {{
                    const button = event.target?.closest?.("button");
                    if (!button) {{
                        return;
                    }}
                    const label = (button.textContent || "").trim().replace(/\\s+/g, " ");
                    if (["下載", "重建", "刪除", "全部重建索引"].includes(label)) {{
                        freezePosition(button);
                    }}
                }}, true);
            }}

            if (!skipInitialRecord) {{
                recordPosition();
            }}
        }})();
        </script>
        """,
        height=0,
        width=0,
    )


def render_internal_handoff_click_bridge() -> None:
    render_hidden_html(
        """
        <script>
        (() => {
            const parentWindow = window.parent;
            const parentDocument = parentWindow.document;
            if (parentDocument.__custAppInternalHandoffClickBridgeV2) {
                return;
            }
            parentDocument.__custAppInternalHandoffClickBridgeV2 = true;

            const showToast = () => {
                parentDocument
                    .querySelectorAll('[data-testid="cust-app-internal-human-mode-message"]')
                    .forEach((element) => element.remove());

                const existing = parentDocument.querySelector('[data-testid="cust-app-internal-human-mode-toast"]');
                if (existing) {
                    parentWindow.clearTimeout(existing.__custAppRemoveTimer);
                    existing.remove();
                }

                const toast = parentDocument.createElement("div");
                toast.setAttribute("data-testid", "cust-app-internal-human-mode-toast");
                toast.textContent = "轉真人模式";
                toast.style.cssText = `
                    position: fixed;
                    left: 50%;
                    top: 50%;
                    transform: translate(-50%, -50%);
                    z-index: 2147483647;
                    padding: 0.85rem 1.15rem;
                    border-radius: 0.65rem;
                    background: var(--cust-surface, rgba(31, 41, 55, 0.96));
                    color: var(--cust-text, #f9fafb);
                    border: 1px solid var(--cust-border, rgba(148, 163, 184, 0.35));
                    font-weight: 800;
                    line-height: 1.6;
                    box-shadow: 0 16px 42px rgba(0, 0, 0, 0.36);
                    pointer-events: none;
                    opacity: 1;
                    transition: opacity 0.45s ease, transform 0.45s ease;
                `;

                parentDocument.body.appendChild(toast);
                toast.__custAppRemoveTimer = parentWindow.setTimeout(() => {
                    toast.style.opacity = "0";
                    toast.style.transform = "translate(-50%, -54%)";
                    parentWindow.setTimeout(() => toast.remove(), 500);
                }, 2500);
            };

            parentDocument.addEventListener("click", (event) => {
                const link = event.target.closest?.('a[data-internal-human-handoff="1"]');
                if (!link) {
                    return;
                }
                event.preventDefault();
                event.stopPropagation();
                showToast();
            }, true);
        })();
        </script>
        """,
        height=0,
        width=0,
    )


def api_headers(extra: dict | None = None) -> dict:
    headers = dict(extra or {})
    token = get_backend_api_token()
    if token:
        headers[WEB_BACKEND_API_AUTH_HEADER] = token
    return headers


def current_actor_label() -> str:
    account = st.session_state.get("web_auth_account") or {}
    display_name = str(account.get("display_name") or "").strip()
    username = str(account.get("username") or "").strip()
    return display_name or username or "system"


def current_actor_username() -> str:
    account = st.session_state.get("web_auth_account") or {}
    return str(account.get("username") or "").strip() or "system"


def actor_api_headers(extra: dict | None = None) -> dict:
    headers = dict(extra or {})
    headers["X-Actor-Username"] = quote(current_actor_username(), safe="")
    headers["X-Actor-Display-Name"] = quote(current_actor_label(), safe="")
    web_auth_token = str(st.session_state.get("web_auth_token") or "").strip()
    if web_auth_token:
        headers["X-Web-Auth-Token"] = web_auth_token
    return api_headers(headers)


def fetch_backend_api_token() -> tuple[str, int]:
    if not WEB_BACKEND_API_AUTH_NAME or not WEB_BACKEND_API_AUTH_PASSWORD:
        return "", 0

    try:
        response = requests.post(
            f"{API_BASE}/api/auth/token",
            json={
                "name": WEB_BACKEND_API_AUTH_NAME,
                "password": WEB_BACKEND_API_AUTH_PASSWORD,
            },
            timeout=15,
        )
        if response.status_code != 200:
            return "", 0

        data = response.json()
        token = str(data.get("access_token") or "").strip()
        expires_at = int(data.get("expires_at") or 0)
        return token, expires_at
    except Exception:
        return "", 0


def clear_backend_api_token_cache() -> None:
    _BACKEND_API_TOKEN_CACHE["token"] = ""
    _BACKEND_API_TOKEN_CACHE["expires_at"] = 0


def get_backend_api_token(force_refresh: bool = False) -> str:
    if WEB_BACKEND_API_TOKEN:
        return WEB_BACKEND_API_TOKEN

    now = int(time.time())
    cached_token = _BACKEND_API_TOKEN_CACHE.get("token") or ""
    cached_expires_at = int(_BACKEND_API_TOKEN_CACHE.get("expires_at") or 0)
    if not force_refresh and cached_token and cached_expires_at - 60 > now:
        return cached_token

    token, expires_at = fetch_backend_api_token()
    _BACKEND_API_TOKEN_CACHE["token"] = token
    _BACKEND_API_TOKEN_CACHE["expires_at"] = expires_at
    return token


def is_invalid_api_token_response(response: requests.Response) -> bool:
    if response.status_code != 401:
        return False

    detail = response.text or ""
    try:
        payload = response.json()
        if isinstance(payload, dict):
            detail = str(payload.get("detail") or payload.get("message") or detail)
    except ValueError:
        pass

    return "invalid or missing api token" in detail.lower()


def backend_error_message(response: requests.Response) -> str:
    if is_invalid_api_token_response(response):
        return "後端登入憑證已失效，系統已嘗試重新取得 token，請重新整理頁面後再試一次。"
    return response.text


def backend_request(method: str, url: str, *, headers: dict | None = None, actor: bool = False, **kwargs):
    header_builder = actor_api_headers if actor else api_headers
    response = requests.request(
        method,
        url,
        headers=header_builder(headers),
        **kwargs,
    )
    if is_invalid_api_token_response(response) and not WEB_BACKEND_API_TOKEN:
        clear_backend_api_token_cache()
        response = requests.request(
            method,
            url,
            headers=header_builder(headers),
            **kwargs,
        )
    return response


def backend_api_token_for_direct_url() -> str:
    if WEB_BACKEND_API_TOKEN:
        return WEB_BACKEND_API_TOKEN

    now = int(time.time())
    cached_expires_at = int(_BACKEND_API_TOKEN_CACHE.get("expires_at") or 0)
    force_refresh = cached_expires_at - 600 <= now
    return get_backend_api_token(force_refresh=force_refresh)

st.set_page_config(
    page_title="智慧客服測試系統",
    page_icon="🤖",
    layout="wide",
    initial_sidebar_state="expanded",
    menu_items={
        "Get Help": None,
        "Report a bug": None,
        "About": None,
    },
)

WEB_ACCOUNT_SERVICE = WebAccountService()
WEB_ACCOUNT_INIT_ERROR = None
if WEB_AUTH_ENABLED:
    try:
        WEB_ACCOUNT_SERVICE.init_schema()
        WEB_ACCOUNT_SERVICE.bootstrap_from_env()
    except Exception as exc:
        WEB_ACCOUNT_INIT_ERROR = str(exc)

# =========================
# 1. 樣式
# =========================

st.markdown("""
<style>
.block-container {
    padding-top: 4.5rem;
    padding-bottom: 12rem;
    max-width: 1400px;
    min-height: 100vh;
    overflow-anchor: none;
}

[data-testid="stAppViewContainer"] {
    padding-top: 0rem;
    overflow-anchor: none;
    overscroll-behavior-y: contain;
    scrollbar-gutter: stable;
}

[data-testid="stMain"],
[data-testid="stVerticalBlock"],
[data-testid="stBottomBlockContainer"] {
    overflow-anchor: none;
    overscroll-behavior-y: contain;
}

[data-testid="stBottomBlockContainer"] {
    min-height: 7rem;
    padding-bottom: max(1.25rem, env(safe-area-inset-bottom));
}

.chat-input-spacer {
    height: 1.5rem;
}

.chat-input-bottom-spacer {
    height: 1.75rem;
}

.page-bottom-safe-area {
    display: block;
    width: 100%;
    height: max(4rem, calc(env(safe-area-inset-bottom, 0px) + 2.5rem));
    min-height: 4rem;
    clear: both;
    pointer-events: none;
}

.image-ocr-panel-marker,
.feedback-panel-marker {
    display: block;
    width: 100%;
    height: 0;
    overflow: hidden;
    pointer-events: none;
}

[data-testid="stExpander"]:has(.image-ocr-panel-marker),
[data-testid="stExpander"]:has(.feedback-panel-marker) {
    scroll-margin-top: 4rem;
    scroll-margin-bottom: 3rem;
}

[data-testid="stForm"]:has(input[aria-label="客服訊息"]) {
    border: 1px solid rgba(148, 163, 184, 0.3);
    background: rgba(17, 24, 39, 0.72);
    box-shadow: 0 10px 28px rgba(0, 0, 0, 0.16);
    -webkit-backdrop-filter: blur(14px) saturate(115%);
    backdrop-filter: blur(14px) saturate(115%);
}

[data-testid="stTextInput"]:has(input[aria-label="客服訊息"]) input {
    border: 1px solid rgba(245, 158, 11, 0.72) !important;
    background: #171a22 !important;
    color: #f8fbff !important;
    box-shadow: none !important;
}

[data-testid="stTextInput"]:has(input[aria-label="客服訊息"]) [data-baseweb="input"],
[data-testid="stTextInput"]:has(input[aria-label="客服訊息"]) [data-baseweb="input"] > div {
    border-color: rgba(245, 158, 11, 0.72) !important;
    box-shadow: none !important;
}

[data-testid="stTextInput"]:has(input[aria-label="客服訊息"]) [data-baseweb="input"]:focus-within,
[data-testid="stTextInput"]:has(input[aria-label="客服訊息"]) [data-baseweb="input"]:focus-within > div {
    border-color: #f59e0b !important;
    box-shadow: none !important;
}

[data-testid="stTextInput"]:has(input[aria-label="客服訊息"]) input::placeholder {
    color: #f8d7a0 !important;
    opacity: 0.9;
}

[data-testid="stTextInput"]:has(input[aria-label="客服訊息"]) input:focus {
    border-color: #f59e0b !important;
    box-shadow: none !important;
}

[data-testid="stForm"]:has(input[aria-label="客服訊息"]) button[kind="secondaryFormSubmit"] {
    border-color: rgba(217, 119, 6, 0.88) !important;
    background: #b45309 !important;
    color: #fffaf0 !important;
    font-weight: 700 !important;
}

[data-testid="stForm"]:has(input[aria-label="客服訊息"]) button[kind="secondaryFormSubmit"]:hover:not(:disabled) {
    border-color: #f59e0b !important;
    background: #c2610b !important;
}

[data-testid="stHeader"] {
    background: transparent;
}

[data-testid="stChatMessage"] {
    padding-top: 0.35rem;
    padding-bottom: 0.35rem;
}

[data-testid="stChatMessage"] code {
    background: transparent !important;
    color: inherit !important;
    border: 0 !important;
    border-radius: 0 !important;
    padding: 0 !important;
    font-family: inherit !important;
    font-size: inherit !important;
    white-space: inherit !important;
}

.chat-role-marker-user {
    display: none;
}

[data-testid="stChatMessage"]:has(.chat-role-marker-user) {
    width: 100% !important;
    max-width: 100%;
    margin-left: 0;
    margin-right: 0;
    padding: 0.35rem 0 !important;
    background: transparent !important;
    flex-direction: row-reverse;
    justify-content: flex-start;
    align-items: center;
}

[data-testid="stChatMessage"]:has(.chat-role-marker-user) .chat-text {
    display: inline-block;
    width: auto;
    max-width: min(78vw, 900px);
    margin-left: 0;
    margin-right: 0;
    padding: 0.75rem 1rem;
    border-radius: 0.6rem;
    background: #1b202b;
    text-align: left;
}

[data-testid="stChatMessage"]:has(.chat-role-marker-user) [data-testid="stMarkdownContainer"] {
    display: flex;
    justify-content: flex-end;
    margin-top: 0 !important;
    margin-bottom: 0 !important;
}

[data-testid="stChatMessage"]:has(.chat-role-marker-user) [data-testid="stMarkdownContainer"]:has(.chat-role-marker-user) {
    display: none;
}

[data-testid="stChatMessage"]:has(.chat-role-marker-user) .message-meta,
[data-testid="stChatMessage"]:has(.chat-role-marker-user) .message-meta-detail {
    text-align: right;
}

@media (max-width: 760px) {
    [data-testid="stChatMessage"]:has(.chat-role-marker-user) {
        max-width: 100%;
    }

    [data-testid="stChatMessage"]:has(.chat-role-marker-user) .chat-text {
        max-width: calc(100vw - 5rem);
    }
}

.message-meta {
    margin-top: 0.25rem;
    color: #9ca3af;
    font-size: 0.78rem;
    font-weight: 600;
}

.message-meta-detail {
    margin-top: 0.12rem;
    color: #8b949e;
    font-size: 0.74rem;
    font-weight: 500;
    line-height: 1.45;
}

.chat-text {
    white-space: pre-wrap;
    overflow-wrap: break-word;
    word-break: normal;
    line-height: 1.75;
}

.chat-text a {
    color: #fb7185;
    text-decoration: none;
    border-bottom: 1px solid rgba(251, 113, 133, 0.45);
}

.chat-text a:hover {
    color: #fecdd3;
}

a:focus,
a:focus-visible {
    color: var(--cust-text) !important;
    outline: 2px solid color-mix(in srgb, var(--cust-accent) 32%, transparent);
    outline-offset: 2px;
}

.chat-title {
    font-size: 2.3rem;
    font-weight: 800;
    margin-top: 0.2rem;
    margin-bottom: 0.4rem;
    line-height: 1.2;
}

.chat-subtitle {
    color: #9aa0a6;
    margin-bottom: 1rem;
}

.sidebar-title {
    font-size: 1.1rem;
    font-weight: 700;
    margin-bottom: 0.4rem;
}

.kb-summary {
    border: 1px solid rgba(148, 163, 184, 0.3);
    border-radius: 8px;
    padding: 0.75rem 0.9rem;
    background: rgba(148, 163, 184, 0.08);
}

.kb-summary-label {
    color: #9aa0a6;
    font-size: 0.8rem;
}

.kb-summary-value {
    font-size: 1.25rem;
    font-weight: 800;
}

.kb-doc-title {
    font-size: 1.05rem;
    font-weight: 800;
    margin-bottom: 0.25rem;
}

.kb-doc-meta {
    color: #9aa0a6;
    font-size: 0.86rem;
}

.kb-doc-audit {
    color: #9aa0a6;
    font-size: 0.78rem;
    line-height: 1.55;
    margin-top: 0.3rem;
}

.kb-doc-audit strong {
    color: #cbd5e1;
}

.kb-pill {
    display: inline-flex;
    align-items: center;
    min-height: 28px;
    padding: 0 10px;
    border-radius: 999px;
    border: 1px solid rgba(148, 163, 184, 0.35);
    background: rgba(148, 163, 184, 0.08);
    font-size: 0.86rem;
    font-weight: 700;
}

.kb-pill-ok {
    border-color: rgba(34, 197, 94, 0.45);
    background: rgba(34, 197, 94, 0.12);
    color: #86efac;
}

.kb-pill-warn {
    border-color: rgba(245, 158, 11, 0.5);
    background: rgba(245, 158, 11, 0.12);
    color: #facc15;
}

.kb-preview-link {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    width: 100%;
    min-height: 38px;
    padding: 0 12px;
    border: 1px solid var(--cust-accent);
    border-radius: 6px;
    background: color-mix(in srgb, var(--cust-accent) 10%, transparent);
    color: var(--cust-accent) !important;
    text-decoration: none;
    font-size: 14px;
    font-weight: 800;
}

.kb-download-link {
    border-color: var(--cust-button-accent);
    background: color-mix(in srgb, var(--cust-button-accent) 12%, transparent);
    color: var(--cust-button-accent) !important;
}

.kb-preview-link.is-disabled {
    pointer-events: none;
    cursor: not-allowed;
    border-color: var(--cust-border);
    background: var(--cust-button-disabled-bg);
    color: var(--cust-button-disabled-text) !important;
    opacity: 1;
}

.kb-preview-link:hover,
.kb-preview-link:focus,
.kb-preview-link:focus-visible,
.kb-download-link:hover,
.kb-download-link:focus,
.kb-download-link:focus-visible {
    border-color: var(--cust-accent);
    background: var(--cust-button-hover);
    color: var(--cust-text) !important;
    outline: 2px solid color-mix(in srgb, var(--cust-accent) 32%, transparent);
    outline-offset: 2px;
}

.account-table-wrap {
    width: 100%;
    overflow-x: auto;
    border: 1px solid var(--cust-border);
    border-radius: 8px;
    background: var(--cust-surface);
}

.account-table {
    width: 100%;
    min-width: 820px;
    border-collapse: collapse;
    color: var(--cust-text);
}

.account-table th,
.account-table td {
    padding: 0.72rem 0.78rem;
    border-right: 1px solid var(--cust-border);
    border-bottom: 1px solid var(--cust-border);
    text-align: left;
    vertical-align: middle;
    font-size: 0.92rem;
}

.account-table th:last-child,
.account-table td:last-child {
    border-right: 0;
}

.account-table tr:last-child td {
    border-bottom: 0;
}

.account-table thead th {
    background: var(--cust-table-header-bg);
    color: var(--cust-muted);
    font-weight: 800;
}

.account-table tbody tr {
    background: var(--cust-table-row-bg);
}

.account-table tbody tr:nth-child(even) {
    background: var(--cust-table-row-alt-bg);
}

hr {
    margin-top: 0.8rem;
    margin-bottom: 0.8rem;
}
</style>
""", unsafe_allow_html=True)


# =========================
# 2. Session 初始化
# =========================

if "user_id" not in st.session_state:
    st.session_state.user_id = str(uuid.uuid4())

if "chat_history" not in st.session_state:
    st.session_state.chat_history = []

if "last_state" not in st.session_state:
    st.session_state.last_state = {}

if "pending_user_message" not in st.session_state:
    st.session_state.pending_user_message = None

if "pending_receipt_image_evidence_token" not in st.session_state:
    st.session_state.pending_receipt_image_evidence_token = None

if "is_generating" not in st.session_state:
    st.session_state.is_generating = False

if "scroll_to_chat_bottom" not in st.session_state:
    st.session_state.scroll_to_chat_bottom = False

if "focus_chat_input" not in st.session_state:
    st.session_state.focus_chat_input = False

if "chat_prompt_widget_version" not in st.session_state:
    st.session_state.chat_prompt_widget_version = 0

if "clear_chat_input_draft" not in st.session_state:
    st.session_state.clear_chat_input_draft = False

if "selected_tv_cable" not in st.session_state:
    st.session_state.selected_tv_cable = DEFAULT_TV_CABLE

if "simulate_web_authenticated_custnum" not in st.session_state:
    st.session_state.simulate_web_authenticated_custnum = False

if "simulated_web_custnum" not in st.session_state:
    st.session_state.simulated_web_custnum = ""

if "confirmed_web_custnum" not in st.session_state:
    st.session_state.confirmed_web_custnum = ""

if "web_custnum_error" not in st.session_state:
    st.session_state.web_custnum_error = ""

if "active_chat_identity_context" not in st.session_state:
    st.session_state.active_chat_identity_context = None

if "current_page" not in st.session_state:
    st.session_state.current_page = "chat"

query_theme_mode = normalize_ui_theme_mode(get_query_param_value(UI_THEME_QUERY_PARAM))
if query_theme_mode:
    st.session_state.ui_theme_mode = query_theme_mode
elif "ui_theme_mode" not in st.session_state:
    st.session_state.ui_theme_mode = "dark"

if "company_options" not in st.session_state:
    st.session_state.company_options = FALLBACK_COMPANIES

if "last_feedback_result" not in st.session_state:
    st.session_state.last_feedback_result = None

if "pending_feedback_notice" not in st.session_state:
    st.session_state.pending_feedback_notice = None

if "image_ocr_uploader_nonce" not in st.session_state:
    st.session_state.image_ocr_uploader_nonce = 0

if "image_ocr_panel_expanded" not in st.session_state:
    st.session_state.image_ocr_panel_expanded = False

if "scroll_to_image_ocr_panel" not in st.session_state:
    st.session_state.scroll_to_image_ocr_panel = False

if "is_image_ocr_processing" not in st.session_state:
    st.session_state.is_image_ocr_processing = False

if "pending_image_ocr" not in st.session_state:
    st.session_state.pending_image_ocr = None

if "last_kb_admin_result" not in st.session_state:
    st.session_state.last_kb_admin_result = None

if "last_kb_batch_results" not in st.session_state:
    st.session_state.last_kb_batch_results = []

if "last_kb_reindex_all_result" not in st.session_state:
    st.session_state.last_kb_reindex_all_result = None

if "is_kb_reindex_all_processing" not in st.session_state:
    st.session_state.is_kb_reindex_all_processing = False

if "kb_reindex_document_processing_id" not in st.session_state:
    st.session_state.kb_reindex_document_processing_id = ""

if "kb_delete_document_processing_id" not in st.session_state:
    st.session_state.kb_delete_document_processing_id = ""

if "is_kb_upload_processing" not in st.session_state:
    st.session_state.is_kb_upload_processing = False

if "kb_upload_widget_version" not in st.session_state:
    st.session_state.kb_upload_widget_version = 0

if "pending_kb_download" not in st.session_state:
    st.session_state.pending_kb_download = None

if "pending_kb_scroll_restore" not in st.session_state:
    st.session_state.pending_kb_scroll_restore = False

if "last_company_profile_result" not in st.session_state:
    st.session_state.last_company_profile_result = None

if "company_profile_processing_code" not in st.session_state:
    st.session_state.company_profile_processing_code = ""

if "web_auth_token" not in st.session_state:
    st.session_state.web_auth_token = ""

if "web_auth_account" not in st.session_state:
    st.session_state.web_auth_account = None

if "web_auth_token_to_persist" not in st.session_state:
    st.session_state.web_auth_token_to_persist = ""

if "web_auth_clear_storage" not in st.session_state:
    st.session_state.web_auth_clear_storage = False

if "last_account_admin_result" not in st.session_state:
    st.session_state.last_account_admin_result = None

theme_mode = st.session_state.ui_theme_mode if st.session_state.ui_theme_mode in {"dark", "light"} else "dark"
theme_vars = {
    "dark": {
        "app_bg": "#080c12",
        "surface": "#111827",
        "surface_2": "#1b202b",
        "surface_3": "#171a22",
        "sidebar_bg": "#262832",
        "text": "#f8fafc",
        "muted": "#9aa0a6",
        "border": "rgba(148, 163, 184, 0.35)",
        "input_bg": "#171a22",
        "input_text": "#f8fbff",
        "input_placeholder": "#f8d7a0",
        "input_hint": "#f8d7a0",
        "input_caret": "#fbbf24",
        "readonly_bg": "#111827",
        "readonly_text": "#e5e7eb",
        "readonly_border": "rgba(148, 163, 184, 0.42)",
        "user_bubble": "#1b202b",
        "assistant_bubble": "transparent",
        "accent": "#e11d48",
        "accent_2": "#fb7185",
        "accent_soft": "rgba(244, 63, 94, 0.16)",
        "button_bg": "#141b26",
        "button_hover": "#2a1820",
        "button_accent": "#b45309",
        "button_accent_2": "#d97706",
        "button_accent_text": "#fffaf0",
        "button_disabled_bg": "#111827",
        "button_disabled_text": "#a7b0bf",
        "table_header_bg": "#171a22",
        "table_row_bg": "#0f141d",
        "table_row_alt_bg": "#151b25",
        "code_bg": "#1f2937",
        "code_text": "#bbf7d0",
        "code_border": "rgba(148, 163, 184, 0.32)",
        "json_key": "#93c5fd",
        "json_string": "#bbf7d0",
        "json_primitive": "#fbbf24",
        "json_text": "#e5e7eb",
        "card_bg": "#080c12",
        "card_border": "rgba(148, 163, 184, 0.35)",
        "card_inner_border": "rgba(255, 255, 255, 0.03)",
        "tooltip_bg": "#111827",
        "tooltip_text": "#f8fafc",
        "tooltip_border": "rgba(148, 163, 184, 0.35)",
        "uploader_bg": "#1f2029",
        "uploader_button_bg": "#141b26",
        "notice_bg": "rgba(14, 165, 233, 0.13)",
        "notice_border": "rgba(56, 189, 248, 0.28)",
        "status_ok_bg": "rgba(22, 163, 74, 0.18)",
        "status_ok_text": "#86efac",
        "status_ok_border": "rgba(34, 197, 94, 0.58)",
        "glass_bg": "rgba(17, 24, 39, 0.7)",
        "glass_bg_strong": "rgba(17, 24, 39, 0.84)",
        "glass_border": "rgba(148, 163, 184, 0.28)",
        "shadow": "0 10px 28px rgba(0, 0, 0, 0.18)",
    },
    "light": {
        "app_bg": "#e8edf2",
        "surface": "#f2f5f7",
        "surface_2": "#f3eee8",
        "surface_3": "#e9dfd4",
        "sidebar_bg": "#dfe6ec",
        "text": "#1d2939",
        "muted": "#596779",
        "border": "rgba(71, 85, 105, 0.32)",
        "input_bg": "#f3eee8",
        "input_text": "#172337",
        "input_placeholder": "#8a4b12",
        "input_hint": "#8a4b12",
        "input_caret": "#7c2d12",
        "readonly_bg": "#e8edf1",
        "readonly_text": "#1d2939",
        "readonly_border": "rgba(51, 65, 85, 0.34)",
        "user_bubble": "#d6e1ea",
        "assistant_bubble": "#d6e1ea",
        "accent": "#e11d48",
        "accent_2": "#fb7185",
        "accent_soft": "rgba(244, 63, 94, 0.12)",
        "button_bg": "#f3f5f6",
        "button_hover": "#ebe4e3",
        "button_accent": "#f59e0b",
        "button_accent_2": "#fbbf24",
        "button_accent_text": "#3b2300",
        "button_disabled_bg": "#d7dfe6",
        "button_disabled_text": "#5f6b7a",
        "table_header_bg": "#d9e2ea",
        "table_row_bg": "#eef2f5",
        "table_row_alt_bg": "#e7edf2",
        "code_bg": "#f1ece6",
        "code_text": "#166534",
        "code_border": "rgba(15, 23, 42, 0.28)",
        "json_key": "#1e3a8a",
        "json_string": "#166534",
        "json_primitive": "#9a3412",
        "json_text": "#1d2939",
        "card_bg": "#f2efea",
        "card_border": "rgba(31, 41, 55, 0.5)",
        "card_inner_border": "rgba(255, 255, 255, 0.52)",
        "tooltip_bg": "#f1ece6",
        "tooltip_text": "#1d2939",
        "tooltip_border": "rgba(15, 23, 42, 0.28)",
        "uploader_bg": "#edf1f4",
        "uploader_button_bg": "#e4eaf0",
        "notice_bg": "#d6e4ef",
        "notice_border": "rgba(59, 91, 122, 0.24)",
        "status_ok_bg": "#bbf7d0",
        "status_ok_text": "#14532d",
        "status_ok_border": "rgba(22, 163, 74, 0.72)",
        "glass_bg": "rgba(240, 243, 245, 0.68)",
        "glass_bg_strong": "rgba(244, 246, 247, 0.82)",
        "glass_border": "rgba(51, 65, 85, 0.3)",
        "shadow": "0 10px 28px rgba(15, 23, 42, 0.08)",
    },
}[theme_mode]

st.markdown(f"""
<style>
:root {{
    color-scheme: {theme_mode};
    --cust-app-bg: {theme_vars["app_bg"]};
    --cust-surface: {theme_vars["surface"]};
    --cust-surface-2: {theme_vars["surface_2"]};
    --cust-surface-3: {theme_vars["surface_3"]};
    --cust-sidebar-bg: {theme_vars["sidebar_bg"]};
    --cust-text: {theme_vars["text"]};
    --cust-muted: {theme_vars["muted"]};
    --cust-border: {theme_vars["border"]};
    --cust-input-bg: {theme_vars["input_bg"]};
    --cust-input-text: {theme_vars["input_text"]};
    --cust-input-placeholder: {theme_vars["input_placeholder"]};
    --cust-input-hint: {theme_vars["input_hint"]};
    --cust-input-caret: {theme_vars["input_caret"]};
    --cust-readonly-bg: {theme_vars["readonly_bg"]};
    --cust-readonly-text: {theme_vars["readonly_text"]};
    --cust-readonly-border: {theme_vars["readonly_border"]};
    --cust-user-bubble: {theme_vars["user_bubble"]};
    --cust-assistant-bubble: {theme_vars["assistant_bubble"]};
    --cust-accent: {theme_vars["accent"]};
    --cust-accent-2: {theme_vars["accent_2"]};
    --cust-accent-soft: {theme_vars["accent_soft"]};
    --cust-button-bg: {theme_vars["button_bg"]};
    --cust-button-hover: {theme_vars["button_hover"]};
    --cust-button-accent: {theme_vars["button_accent"]};
    --cust-button-accent-2: {theme_vars["button_accent_2"]};
    --cust-button-accent-text: {theme_vars["button_accent_text"]};
    --cust-button-disabled-bg: {theme_vars["button_disabled_bg"]};
    --cust-button-disabled-text: {theme_vars["button_disabled_text"]};
    --cust-table-header-bg: {theme_vars["table_header_bg"]};
    --cust-table-row-bg: {theme_vars["table_row_bg"]};
    --cust-table-row-alt-bg: {theme_vars["table_row_alt_bg"]};
    --cust-code-bg: {theme_vars["code_bg"]};
    --cust-code-text: {theme_vars["code_text"]};
    --cust-code-border: {theme_vars["code_border"]};
    --cust-json-key: {theme_vars["json_key"]};
    --cust-json-string: {theme_vars["json_string"]};
    --cust-json-primitive: {theme_vars["json_primitive"]};
    --cust-json-text: {theme_vars["json_text"]};
    --cust-card-bg: {theme_vars["card_bg"]};
    --cust-card-border: {theme_vars["card_border"]};
    --cust-card-inner-border: {theme_vars["card_inner_border"]};
    --cust-tooltip-bg: {theme_vars["tooltip_bg"]};
    --cust-tooltip-text: {theme_vars["tooltip_text"]};
    --cust-tooltip-border: {theme_vars["tooltip_border"]};
    --cust-uploader-bg: {theme_vars["uploader_bg"]};
    --cust-uploader-button-bg: {theme_vars["uploader_button_bg"]};
    --cust-notice-bg: {theme_vars["notice_bg"]};
    --cust-notice-border: {theme_vars["notice_border"]};
    --cust-status-ok-bg: {theme_vars["status_ok_bg"]};
    --cust-status-ok-text: {theme_vars["status_ok_text"]};
    --cust-status-ok-border: {theme_vars["status_ok_border"]};
    --cust-glass-bg: {theme_vars["glass_bg"]};
    --cust-glass-bg-strong: {theme_vars["glass_bg_strong"]};
    --cust-glass-border: {theme_vars["glass_border"]};
    --cust-shadow: {theme_vars["shadow"]};
}}

.stApp,
[data-testid="stAppViewContainer"],
[data-testid="stMain"] {{
    background: var(--cust-app-bg) !important;
    color: var(--cust-text) !important;
}}

[data-testid="stHeader"] {{
    background: transparent !important;
    height: 3rem !important;
    display: flex !important;
    visibility: visible !important;
    pointer-events: none !important;
}}

[data-testid="stToolbarActions"],
[data-testid="stStatusWidget"],
[data-testid="stMainMenu"],
[data-testid="stDeployButton"],
[data-testid="stDecoration"],
.stDeployButton {{
    display: none !important;
    visibility: hidden !important;
    pointer-events: none !important;
}}

[data-testid="stToolbar"] {{
    display: flex !important;
    visibility: visible !important;
    pointer-events: none !important;
}}

[data-testid="stExpandSidebarButton"] {{
    display: inline-flex !important;
    visibility: visible !important;
    align-items: center !important;
    justify-content: center !important;
    min-width: 2.5rem !important;
    min-height: 2.5rem !important;
    margin: 0.25rem 0 0 0.35rem !important;
    border: 1px solid var(--cust-glass-border) !important;
    border-radius: 8px !important;
    background: var(--cust-glass-bg-strong) !important;
    color: var(--cust-text) !important;
    box-shadow: var(--cust-shadow) !important;
    -webkit-backdrop-filter: blur(14px) saturate(115%);
    backdrop-filter: blur(14px) saturate(115%);
    pointer-events: auto !important;
}}

[data-testid="stExpandSidebarButton"]:hover {{
    border-color: var(--cust-button-accent) !important;
    background: var(--cust-button-hover) !important;
}}

[data-testid="stExpandSidebarButton"],
[data-testid="stExpandSidebarButton"] button,
[data-testid="stExpandSidebarButton"] span,
[data-testid="stExpandSidebarButton"] [data-testid="stIconMaterial"],
[data-testid="stExpandSidebarButton"] svg,
[data-testid="stExpandSidebarButton"] svg path {{
    color: var(--cust-text) !important;
    -webkit-text-fill-color: var(--cust-text) !important;
    fill: currentColor !important;
    stroke: currentColor;
    opacity: 1 !important;
    filter: none !important;
}}

::selection {{
    background: color-mix(in srgb, var(--cust-input-caret) 28%, transparent);
    color: var(--cust-input-text);
}}

[data-testid="stSidebar"],
[data-testid="stSidebarContent"] {{
    background: color-mix(in srgb, var(--cust-sidebar-bg) 88%, transparent) !important;
    color: var(--cust-text) !important;
    -webkit-backdrop-filter: blur(16px) saturate(110%);
    backdrop-filter: blur(16px) saturate(110%);
}}

[data-testid="stMarkdownContainer"],
[data-testid="stMarkdownContainer"] p,
[data-testid="stMarkdownContainer"] li,
[data-testid="stMarkdownContainer"] label,
[data-testid="stSidebar"] p,
[data-testid="stSidebar"] label,
[data-testid="stSidebar"] span {{
    color: var(--cust-text);
}}

[data-baseweb="modal"],
[data-baseweb="modal"] > div,
[data-baseweb="modal"] > div > div,
[data-baseweb="modal"] [role="dialog"],
[data-baseweb="modal"] [role="document"],
[data-testid="stDialog"],
[data-testid="stDialog"] > div,
[data-testid="stDialogContent"],
[role="dialog"][aria-modal="true"],
[role="dialog"][aria-modal="true"] > div {{
    background: var(--cust-surface) !important;
    color: var(--cust-text) !important;
    border-color: var(--cust-border) !important;
}}

[data-baseweb="modal"] [role="dialog"],
[data-baseweb="modal"] [role="document"],
[data-testid="stDialogContent"],
[role="dialog"][aria-modal="true"] {{
    border: 1px solid var(--cust-glass-border) !important;
    border-radius: 18px !important;
    background: var(--cust-glass-bg-strong) !important;
    box-shadow: var(--cust-shadow) !important;
    -webkit-backdrop-filter: blur(18px) saturate(115%);
    backdrop-filter: blur(18px) saturate(115%);
    overflow: hidden !important;
}}

[data-baseweb="modal"] [data-testid="stVerticalBlock"],
[data-baseweb="modal"] [data-testid="stMarkdownContainer"],
[data-testid="stDialog"] [data-testid="stVerticalBlock"],
[data-testid="stDialog"] [data-testid="stMarkdownContainer"],
[role="dialog"][aria-modal="true"] [data-testid="stVerticalBlock"],
[role="dialog"][aria-modal="true"] [data-testid="stMarkdownContainer"] {{
    background: transparent !important;
    color: var(--cust-text) !important;
}}

[data-baseweb="modal"] h1,
[data-baseweb="modal"] h2,
[data-baseweb="modal"] h3,
[data-baseweb="modal"] p,
[data-baseweb="modal"] li,
[data-baseweb="modal"] label,
[data-baseweb="modal"] span,
[data-testid="stDialog"] h1,
[data-testid="stDialog"] h2,
[data-testid="stDialog"] h3,
[data-testid="stDialog"] p,
[data-testid="stDialog"] li,
[data-testid="stDialog"] label,
[data-testid="stDialog"] span,
[role="dialog"][aria-modal="true"] h1,
[role="dialog"][aria-modal="true"] h2,
[role="dialog"][aria-modal="true"] h3,
[role="dialog"][aria-modal="true"] p,
[role="dialog"][aria-modal="true"] li,
[role="dialog"][aria-modal="true"] label,
[role="dialog"][aria-modal="true"] span {{
    color: var(--cust-text) !important;
}}

[data-baseweb="modal"] svg,
[data-baseweb="modal"] path,
[data-testid="stDialog"] svg,
[data-testid="stDialog"] path,
[role="dialog"][aria-modal="true"] svg,
[role="dialog"][aria-modal="true"] path {{
    color: var(--cust-text) !important;
    fill: currentColor !important;
    stroke: currentColor !important;
}}

[data-testid="stMarkdownContainer"] code,
[data-testid="stCaptionContainer"] code,
[data-testid="stExpander"] code,
[data-testid="stExpanderDetails"] code,
[data-testid="stExpander"] [data-testid="stMarkdownContainer"] code,
[data-testid="stExpanderDetails"] [data-testid="stMarkdownContainer"] code,
[data-testid="stCodeBlock"],
[data-testid="stCodeBlock"] pre,
[data-testid="stCodeBlock"] code {{
    background: var(--cust-code-bg) !important;
    color: var(--cust-code-text) !important;
    border-color: var(--cust-code-border) !important;
}}

[data-testid="stMarkdownContainer"] code,
[data-testid="stCaptionContainer"] code,
[data-testid="stExpander"] code,
[data-testid="stExpanderDetails"] code,
[data-testid="stExpander"] [data-testid="stMarkdownContainer"] code,
[data-testid="stExpanderDetails"] [data-testid="stMarkdownContainer"] code {{
    border: 1px solid var(--cust-code-border) !important;
    border-radius: 4px;
    padding: 0.08rem 0.28rem;
    box-shadow: none;
}}

.kb-debug-source-content {{
    margin: 0.35rem 0 1rem;
    padding: 0.85rem 1rem;
    color: var(--cust-code-text);
    background: var(--cust-code-bg);
    border: 1px solid var(--cust-code-border);
    border-radius: 6px;
    white-space: pre-wrap;
    overflow-wrap: anywhere;
    line-height: 1.65;
}}

[data-testid="stJson"],
[data-testid="stJson"] > div,
[data-testid="stSidebar"] [data-testid="stJson"],
[data-testid="stSidebar"] [data-testid="stJson"] > div,
.react-json-view {{
    background: var(--cust-code-bg) !important;
    color: var(--cust-json-text) !important;
    border: 1px solid var(--cust-code-border) !important;
    border-radius: 8px !important;
}}

[data-testid="stJson"] *,
[data-testid="stSidebar"] [data-testid="stJson"] *,
.react-json-view * {{
    color: var(--cust-json-text) !important;
    background-color: transparent !important;
    border-color: var(--cust-code-border) !important;
}}

[data-testid="stJson"] [class*="key"],
[data-testid="stJson"] [class*="object-key"],
[data-testid="stJson"] [class*="string-key"],
.react-json-view [class*="key"],
.react-json-view [class*="object-key"],
.react-json-view [class*="string-key"] {{
    color: var(--cust-json-key) !important;
}}

[data-testid="stJson"] [class*="string-value"],
.react-json-view [class*="string-value"] {{
    color: var(--cust-json-string) !important;
}}

[data-testid="stJson"] [class*="null"],
[data-testid="stJson"] [class*="boolean"],
[data-testid="stJson"] [class*="integer"],
[data-testid="stJson"] [class*="float"],
.react-json-view [class*="null"],
.react-json-view [class*="boolean"],
.react-json-view [class*="integer"],
.react-json-view [class*="float"] {{
    color: var(--cust-json-primitive) !important;
}}

[data-testid="stJson"] svg,
[data-testid="stJson"] path,
.react-json-view svg,
.react-json-view path {{
    color: var(--cust-json-key) !important;
    fill: currentColor !important;
}}

[data-testid="stChatMessage"] code {{
    background: transparent !important;
    color: inherit !important;
    border: 0 !important;
    padding: 0 !important;
}}

.chat-subtitle,
.message-meta,
.message-meta-detail,
.kb-summary-label,
.kb-doc-meta,
.kb-doc-audit {{
    color: var(--cust-muted) !important;
}}

[data-testid="stChatMessage"] {{
    background: transparent !important;
}}

[data-testid="stChatMessage"] .chat-text {{
    display: inline-block;
    width: fit-content;
    max-width: min(86vw, 1200px);
    padding: 0.75rem 1rem;
    border-radius: 0.6rem;
    background: var(--cust-assistant-bubble) !important;
    color: var(--cust-text) !important;
}}

[data-testid="stChatMessage"]:has(.chat-role-marker-user) .chat-text {{
    background: var(--cust-user-bubble) !important;
    color: var(--cust-text) !important;
}}

[data-testid="stForm"],
[data-testid="stExpander"],
[data-testid="stExpanderDetails"],
.kb-summary {{
    border-color: var(--cust-glass-border) !important;
    background: var(--cust-glass-bg) !important;
    color: var(--cust-text) !important;
    -webkit-backdrop-filter: blur(14px) saturate(112%);
    backdrop-filter: blur(14px) saturate(112%);
}}

[data-testid="stExpander"] details,
[data-testid="stExpander"] summary,
[data-testid="stExpander"] summary:hover {{
    border-color: var(--cust-glass-border) !important;
    background: transparent !important;
    color: var(--cust-text) !important;
}}

[data-testid="stFileUploader"],
[data-testid="stFileUploader"] section,
[data-testid="stFileUploader"] section > div,
[data-testid="stFileUploaderDropzone"] {{
    background: var(--cust-uploader-bg) !important;
    color: var(--cust-text) !important;
    border-color: var(--cust-border) !important;
}}

[data-testid="stFileUploader"] small,
[data-testid="stFileUploader"] span,
[data-testid="stFileUploader"] p {{
    color: var(--cust-muted) !important;
}}

[data-testid="stFileUploader"] button {{
    background: var(--cust-uploader-button-bg) !important;
    border-color: var(--cust-border) !important;
    color: var(--cust-text) !important;
}}

[data-testid="stForm"]:has(input[aria-label="客服訊息"]) {{
    border-color: var(--cust-glass-border) !important;
    background: var(--cust-glass-bg-strong) !important;
    box-shadow: var(--cust-shadow) !important;
    -webkit-backdrop-filter: blur(16px) saturate(115%);
    backdrop-filter: blur(16px) saturate(115%);
}}

[data-testid="stTextInput"] input,
[data-testid="stNumberInput"] input,
[data-testid="stTextArea"] textarea,
[data-baseweb="select"] > div,
[data-baseweb="textarea"],
[data-baseweb="input"] {{
    border-color: var(--cust-border) !important;
    background: var(--cust-surface-2) !important;
    color: var(--cust-text) !important;
}}

[data-testid="stTextInput"] input,
[data-testid="stNumberInput"] input,
[data-testid="stTextArea"] textarea,
[data-baseweb="input"] input,
[data-baseweb="textarea"] textarea,
input,
textarea {{
    caret-color: var(--cust-input-caret) !important;
}}

[data-testid="stTextInput"] input:not(:disabled):not([readonly]),
[data-testid="stNumberInput"] input:not(:disabled):not([readonly]),
[data-testid="stTextArea"] textarea:not(:disabled):not([readonly]),
[data-baseweb="input"] input:not(:disabled):not([readonly]),
[data-baseweb="textarea"] textarea:not(:disabled):not([readonly]) {{
    background: var(--cust-input-bg) !important;
    color: var(--cust-input-text) !important;
    -webkit-text-fill-color: var(--cust-input-text) !important;
    caret-color: var(--cust-input-caret) !important;
    opacity: 1 !important;
}}

[data-testid="stTextInput"] input:focus,
[data-testid="stNumberInput"] input:focus,
[data-testid="stTextArea"] textarea:focus,
[data-baseweb="input"] input:focus,
[data-baseweb="textarea"] textarea:focus {{
    color: var(--cust-input-text) !important;
    -webkit-text-fill-color: var(--cust-input-text) !important;
    caret-color: var(--cust-input-caret) !important;
    opacity: 1 !important;
}}

[data-testid="stTextInput"] input:-webkit-autofill,
[data-testid="stTextInput"] input:-webkit-autofill:hover,
[data-testid="stTextInput"] input:-webkit-autofill:focus,
[data-testid="stTextInput"] input:-webkit-autofill:active {{
    -webkit-text-fill-color: var(--cust-input-text) !important;
    caret-color: var(--cust-input-caret) !important;
    box-shadow: 0 0 0 1000px var(--cust-input-bg) inset !important;
    transition: background-color 9999s ease-out 0s;
    opacity: 1 !important;
}}

input:disabled,
textarea:disabled,
input[disabled],
textarea[disabled],
input[readonly],
textarea[readonly],
[data-testid="stTextInput"]:has(input:disabled) [data-baseweb="input"],
[data-testid="stTextInput"]:has(input:disabled) [data-baseweb="input"] > div,
[data-testid="stTextInput"]:has(input:disabled) [data-baseweb="base-input"],
[data-testid="stTextInput"]:has(input:disabled) [data-baseweb="base-input"] > div,
[data-testid="stTextArea"]:has(textarea:disabled) [data-baseweb="textarea"],
[data-testid="stTextArea"]:has(textarea:disabled) [data-baseweb="textarea"] > div,
[data-testid="stTextArea"]:has(textarea:disabled) textarea,
[data-baseweb="textarea"] textarea:disabled,
[data-baseweb="input"] input:disabled {{
    background: var(--cust-readonly-bg) !important;
    border-color: var(--cust-readonly-border) !important;
    color: var(--cust-readonly-text) !important;
    -webkit-text-fill-color: var(--cust-readonly-text) !important;
    opacity: 1 !important;
}}

input:disabled::placeholder,
textarea:disabled::placeholder,
input[disabled]::placeholder,
textarea[disabled]::placeholder {{
    color: var(--cust-muted) !important;
    -webkit-text-fill-color: var(--cust-muted) !important;
    opacity: 0.86 !important;
}}

[data-testid="stTextInput"] [data-baseweb="input"] > div,
[data-testid="stTextInput"] [data-baseweb="input"] input,
[data-testid="stTextInput"] [data-baseweb="base-input"],
[data-testid="stTextInput"] [data-baseweb="base-input"] > div,
[data-testid="stNumberInput"] [data-baseweb="input"],
[data-testid="stNumberInput"] [data-baseweb="input"] > div,
[data-testid="stNumberInput"] [data-baseweb="input"] input,
[data-testid="stNumberInput"] [data-baseweb="base-input"],
[data-testid="stNumberInput"] [data-baseweb="base-input"] > div {{
    background: var(--cust-surface-2) !important;
    color: var(--cust-text) !important;
    border-color: var(--cust-border) !important;
}}

[data-testid="stNumberInput"] button,
[data-testid="stNumberInput"] [role="button"],
[data-testid="stNumberInput"] [data-baseweb="input"] button,
[data-testid="stNumberInput"] [data-baseweb="input"] [role="button"],
[data-testid="stNumberInput"] [data-baseweb="input"] > div > div:last-child:not(:first-child) {{
    background: var(--cust-surface-3) !important;
    color: var(--cust-text) !important;
    border-color: var(--cust-border) !important;
}}

[data-testid="stNumberInput"] svg,
[data-testid="stNumberInput"] button svg,
[data-testid="stNumberInput"] [role="button"] svg {{
    color: var(--cust-text) !important;
    fill: currentColor !important;
}}

[data-testid="stTextInput"]:has(input[type="password"]) [data-baseweb="input"],
[data-testid="stTextInput"]:has(input[type="password"]) [data-baseweb="input"] > div,
[data-testid="stTextInput"]:has(input[type="password"]) [data-baseweb="base-input"],
[data-testid="stTextInput"]:has(input[type="password"]) [data-baseweb="base-input"] > div,
[data-testid="stTextInput"]:has(input[type="password"]) input {{
    background: var(--cust-input-bg) !important;
    color: var(--cust-input-text) !important;
    caret-color: var(--cust-input-caret) !important;
    border-color: var(--cust-border) !important;
}}

[data-baseweb="select"] span,
[data-baseweb="select"] svg,
[data-baseweb="input"] input,
[data-baseweb="textarea"] textarea {{
    color: var(--cust-text) !important;
}}

[data-baseweb="select"],
[data-baseweb="select"] > div,
[data-baseweb="select"] > div > div,
[data-baseweb="select"] [role="combobox"] {{
    background: var(--cust-input-bg) !important;
    border-color: var(--cust-border) !important;
    color: var(--cust-input-text) !important;
}}

[data-baseweb="select"] > div *,
[data-baseweb="select"] [role="combobox"] * {{
    color: var(--cust-input-text) !important;
    -webkit-text-fill-color: var(--cust-input-text) !important;
    opacity: 1 !important;
}}

[data-baseweb="select"] input,
[data-baseweb="select"] input:focus,
[data-baseweb="select"] [role="combobox"],
[data-baseweb="select"] [role="combobox"] * {{
    color: var(--cust-input-text) !important;
    -webkit-text-fill-color: var(--cust-input-text) !important;
    caret-color: var(--cust-input-caret) !important;
    opacity: 1 !important;
}}

[data-baseweb="select"] input::placeholder {{
    color: var(--cust-input-placeholder) !important;
    -webkit-text-fill-color: var(--cust-input-placeholder) !important;
    opacity: 1 !important;
}}

[data-baseweb="select"] [aria-disabled="true"],
[data-baseweb="select"] [aria-disabled="true"] *,
[data-testid="stSelectbox"]:has([aria-disabled="true"]) [data-baseweb="select"] > div,
[data-testid="stMultiSelect"]:has([aria-disabled="true"]) [data-baseweb="select"] > div {{
    background: var(--cust-readonly-bg) !important;
    border-color: var(--cust-readonly-border) !important;
    color: var(--cust-readonly-text) !important;
    -webkit-text-fill-color: var(--cust-readonly-text) !important;
    opacity: 1 !important;
}}

[data-baseweb="select"] [data-baseweb="tag"] {{
    background: var(--cust-accent-soft) !important;
    color: var(--cust-text) !important;
    -webkit-text-fill-color: var(--cust-text) !important;
    opacity: 1 !important;
}}

[data-baseweb="select"] [data-baseweb="tag"] * {{
    background: transparent !important;
    color: var(--cust-text) !important;
    -webkit-text-fill-color: var(--cust-text) !important;
}}

[data-testid="stTextInput"]:has(input:disabled) [data-baseweb="input"],
[data-testid="stTextInput"]:has(input:disabled) [data-baseweb="input"] > div,
[data-testid="stTextInput"]:has(input:disabled) [data-baseweb="base-input"],
[data-testid="stTextInput"]:has(input:disabled) [data-baseweb="base-input"] > div,
[data-testid="stTextInput"]:has(input:disabled) input,
[data-testid="stTextArea"]:has(textarea:disabled) [data-baseweb="textarea"],
[data-testid="stTextArea"]:has(textarea:disabled) [data-baseweb="textarea"] > div,
[data-testid="stTextArea"]:has(textarea:disabled) textarea,
[data-baseweb="textarea"] textarea:disabled,
[data-baseweb="input"] input:disabled {{
    background: var(--cust-readonly-bg) !important;
    border-color: var(--cust-readonly-border) !important;
    color: var(--cust-readonly-text) !important;
    -webkit-text-fill-color: var(--cust-readonly-text) !important;
    opacity: 1 !important;
}}

[data-baseweb="popover"],
[data-baseweb="popover"] ul,
[data-baseweb="menu"],
[role="listbox"] {{
    background: var(--cust-surface) !important;
    color: var(--cust-text) !important;
    border-color: var(--cust-border) !important;
}}

[role="option"],
[role="option"] *,
[data-baseweb="menu"] li,
[data-baseweb="menu"] li * {{
    background: var(--cust-surface) !important;
    color: var(--cust-text) !important;
    -webkit-text-fill-color: var(--cust-text) !important;
    opacity: 1 !important;
}}

[role="option"]:hover,
[role="option"]:hover *,
[data-baseweb="menu"] li:hover,
[data-baseweb="menu"] li:hover * {{
    background: var(--cust-button-hover) !important;
}}

[data-testid="stAlert"] {{
    background: var(--cust-notice-bg) !important;
    border-color: var(--cust-notice-border) !important;
    color: var(--cust-text) !important;
}}

[data-testid="stToast"],
[data-testid="stToast"] > div,
[data-testid="stToastContainer"] [data-baseweb="notification"],
[data-baseweb="toast"] {{
    background: var(--cust-glass-bg-strong) !important;
    color: var(--cust-text) !important;
    border: 1px solid var(--cust-glass-border) !important;
    box-shadow: var(--cust-shadow) !important;
    backdrop-filter: blur(14px) saturate(120%) !important;
    -webkit-backdrop-filter: blur(14px) saturate(120%) !important;
}}

[data-testid="stToast"] *,
[data-testid="stToastContainer"] [data-baseweb="notification"] *,
[data-baseweb="toast"] * {{
    color: var(--cust-text) !important;
    -webkit-text-fill-color: var(--cust-text) !important;
    opacity: 1 !important;
}}

[data-testid="stToast"] button,
[data-testid="stToastContainer"] [data-baseweb="notification"] button,
[data-baseweb="toast"] button {{
    background: transparent !important;
    color: var(--cust-text) !important;
}}

[data-testid="stToast"] button svg,
[data-testid="stToastContainer"] [data-baseweb="notification"] button svg,
[data-baseweb="toast"] button svg {{
    color: var(--cust-text) !important;
    fill: currentColor !important;
}}

[data-testid="stWidgetLabel"],
[data-testid="stWidgetLabel"] *,
[data-testid="stCaptionContainer"],
[data-testid="stCaptionContainer"] *,
[data-testid="stSelectbox"] label,
[data-testid="stSelectbox"] label *,
[data-testid="stMultiSelect"] label,
[data-testid="stMultiSelect"] label * {{
    color: var(--cust-text) !important;
    -webkit-text-fill-color: var(--cust-text) !important;
    opacity: 1 !important;
}}

[data-testid="stWidgetLabel"] svg,
[data-testid="stSelectbox"] svg,
[data-testid="stMultiSelect"] svg {{
    color: var(--cust-text) !important;
    fill: currentColor !important;
}}

[data-testid="stTooltipIcon"],
[data-testid="stTooltipIcon"] button,
[data-testid="stTooltipHoverTarget"] {{
    background: transparent !important;
    color: var(--cust-text) !important;
    opacity: 1 !important;
}}

[data-testid="stTooltipIcon"] svg,
[data-testid="stTooltipHoverTarget"] svg {{
    color: var(--cust-text) !important;
    fill: none !important;
    stroke: currentColor !important;
    opacity: 0.9 !important;
}}

.kb-pill-ok {{
    background: var(--cust-status-ok-bg) !important;
    color: var(--cust-status-ok-text) !important;
    -webkit-text-fill-color: var(--cust-status-ok-text) !important;
    border-color: var(--cust-status-ok-border) !important;
    opacity: 1 !important;
}}

[data-testid="stTooltipContent"],
[data-testid="stTooltipContent"] div,
[data-baseweb="tooltip"],
[data-baseweb="tooltip"] > div,
[data-baseweb="tooltip"] [class*="inner"],
[data-baseweb="popover"] [role="tooltip"],
[role="tooltip"],
[role="tooltip"] * {{
    background: var(--cust-tooltip-bg) !important;
    color: var(--cust-tooltip-text) !important;
    border-color: var(--cust-tooltip-border) !important;
}}

[data-testid="stTooltipContent"],
[data-baseweb="tooltip"],
[data-baseweb="tooltip"] > div,
[data-baseweb="popover"] [role="tooltip"],
[role="tooltip"] {{
    border: 1px solid var(--cust-tooltip-border) !important;
    box-shadow: var(--cust-shadow) !important;
}}

[data-testid="stVerticalBlockBorderWrapper"] {{
    border-color: var(--cust-glass-border) !important;
    background: var(--cust-glass-bg) !important;
    box-shadow: none !important;
    -webkit-backdrop-filter: blur(14px) saturate(112%);
    backdrop-filter: blur(14px) saturate(112%);
}}

.kb-doc-card-marker {{
    display: block;
    width: 100%;
    height: 0;
    overflow: hidden;
}}

.kb-sort-action-spacer {{
    height: 1.72rem;
}}

[data-testid="stVerticalBlockBorderWrapper"]:has(.kb-doc-card-marker) {{
    border: 1px solid var(--cust-glass-border) !important;
    border-radius: 8px !important;
    background: var(--cust-glass-bg) !important;
    box-shadow: none !important;
    -webkit-backdrop-filter: blur(14px) saturate(112%);
    backdrop-filter: blur(14px) saturate(112%);
}}

[data-testid="stVerticalBlockBorderWrapper"]:has(.kb-doc-card-marker) > div,
[data-testid="stVerticalBlock"]:has(.kb-doc-card-marker) {{
    background: transparent !important;
}}

[data-testid="stVerticalBlock"]:has(.kb-doc-card-marker) {{
    border: 1px solid var(--cust-glass-border) !important;
    border-radius: 8px !important;
    background: var(--cust-glass-bg) !important;
    box-shadow: none !important;
    -webkit-backdrop-filter: blur(14px) saturate(112%);
    backdrop-filter: blur(14px) saturate(112%);
    padding: 1rem 1.15rem !important;
    margin-bottom: 1.25rem !important;
}}

[data-testid="stTextInput"] input::placeholder,
[data-testid="stTextArea"] textarea::placeholder,
[data-testid="stNumberInput"] input::placeholder {{
    color: var(--cust-input-placeholder) !important;
    -webkit-text-fill-color: var(--cust-input-placeholder) !important;
    opacity: 1 !important;
}}

[data-testid="stTextInput"]:has(input[aria-label="客服訊息"]) input {{
    border-color: rgba(245, 158, 11, 0.72) !important;
    background: var(--cust-input-bg) !important;
    color: var(--cust-input-text) !important;
    caret-color: var(--cust-input-caret) !important;
}}

[data-testid="stTextInput"]:has(input[aria-label="客服訊息"]) [data-baseweb="input"] div,
[data-testid="stTextInput"]:has(input[aria-label="客服訊息"]) [data-baseweb="input"] span {{
    color: var(--cust-input-hint) !important;
}}

[data-testid="stTextInput"]:has(input[aria-label="客服訊息"]) [data-baseweb="input"] input {{
    color: var(--cust-input-text) !important;
    caret-color: var(--cust-input-caret) !important;
}}

[data-testid="stTextInput"]:has(input[aria-label="客服訊息"]) [data-baseweb="input"],
[data-testid="stTextInput"]:has(input[aria-label="客服訊息"]) [data-baseweb="input"] > div {{
    border-color: rgba(245, 158, 11, 0.72) !important;
    box-shadow: none !important;
}}

[data-testid="stTextInput"]:has(input[aria-label="客服訊息"]) [data-baseweb="input"]:focus-within,
[data-testid="stTextInput"]:has(input[aria-label="客服訊息"]) [data-baseweb="input"]:focus-within > div {{
    border-color: #f59e0b !important;
    box-shadow: none !important;
}}

[data-testid="stTextInput"]:has(input[aria-label="客服訊息"]) input::placeholder {{
    color: var(--cust-input-placeholder) !important;
}}

[data-testid="stTextInput"]:has(input[aria-label="客服訊息"]) input:focus {{
    border-color: #f59e0b !important;
    box-shadow: none !important;
}}

[data-testid="stTextInput"] [data-baseweb="input"] button,
[data-testid="stTextInput"] [data-baseweb="input"] [role="button"],
[data-testid="stTextInput"]:has(input[type="password"]) [data-baseweb="input"] button,
[data-testid="stTextInput"]:has(input[type="password"]) [data-baseweb="input"] [role="button"],
[data-testid="stTextInput"] [data-baseweb="input"] > div > div:last-child:not(:first-child) {{
    background: var(--cust-surface-3) !important;
    color: var(--cust-text) !important;
    border-color: var(--cust-border) !important;
}}

[data-testid="stTextInput"] [data-baseweb="input"] button svg,
[data-testid="stTextInput"] [data-baseweb="input"] [role="button"] svg,
[data-testid="stTextInput"]:has(input[type="password"]) [data-baseweb="input"] button svg,
[data-testid="stTextInput"]:has(input[type="password"]) [data-baseweb="input"] [role="button"] svg,
[data-testid="stTextInput"] [data-baseweb="input"] > div > div:last-child:not(:first-child) svg {{
    color: var(--cust-text) !important;
    fill: currentColor !important;
}}

[data-testid="stButton"] button,
[data-testid="stFormSubmitButton"] button {{
    border-color: var(--cust-border) !important;
    color: var(--cust-text) !important;
}}

[data-testid="stButton"] button *,
[data-testid="stFormSubmitButton"] button * {{
    color: inherit !important;
    -webkit-text-fill-color: currentColor !important;
    opacity: 1 !important;
}}

[data-testid="stButton"] button[kind="secondary"],
[data-testid="stFormSubmitButton"] button[kind="secondaryFormSubmit"] {{
    background: var(--cust-button-bg) !important;
    color: var(--cust-text) !important;
}}

[data-testid="stButton"] button[kind="secondary"]:hover:not(:disabled),
[data-testid="stFormSubmitButton"] button[kind="secondaryFormSubmit"]:hover:not(:disabled) {{
    background: var(--cust-button-hover) !important;
    border-color: var(--cust-button-accent) !important;
}}

[data-testid="stButton"] button[kind="primary"],
[data-testid="stFormSubmitButton"] button[kind="primaryFormSubmit"] {{
    border-color: var(--cust-button-accent) !important;
    background: var(--cust-button-accent) !important;
    color: var(--cust-button-accent-text) !important;
    font-weight: 800 !important;
}}

[data-testid="stButton"] button[kind="primary"]:hover:not(:disabled),
[data-testid="stFormSubmitButton"] button[kind="primaryFormSubmit"]:hover:not(:disabled) {{
    background: var(--cust-button-accent-2) !important;
}}

[data-testid="stButton"] button:disabled,
[data-testid="stFormSubmitButton"] button:disabled,
[data-testid="stButton"] button[disabled],
[data-testid="stFormSubmitButton"] button[disabled] {{
    background: var(--cust-button-disabled-bg) !important;
    border-color: var(--cust-border) !important;
    color: var(--cust-button-disabled-text) !important;
    opacity: 1 !important;
}}

[data-testid="stSegmentedControl"] button[kind="segmented_control"] {{
    background: var(--cust-button-bg) !important;
    border-color: var(--cust-border) !important;
    color: var(--cust-text) !important;
}}

[data-testid="stSegmentedControl"] button[kind="segmented_control"]:hover:not(:disabled),
[data-testid="stSegmentedControl"] button[kind="segmented_control"]:focus-visible:not(:disabled) {{
    background: var(--cust-button-hover) !important;
    border-color: var(--cust-button-accent) !important;
}}

[data-testid="stSegmentedControl"] button[kind="segmented_controlActive"] {{
    background: var(--cust-button-accent) !important;
    border-color: var(--cust-button-accent) !important;
    color: var(--cust-button-accent-text) !important;
}}

[data-testid="stSegmentedControl"] button[kind^="segmented_control"] *,
[data-testid="stSegmentedControl"] button[kind^="segmented_control"] span {{
    color: inherit !important;
    -webkit-text-fill-color: currentColor !important;
    opacity: 1 !important;
}}

[data-testid="stButtonGroup"] button[kind="segmented_control"] {{
    background: var(--cust-button-bg) !important;
    border-color: var(--cust-border) !important;
    color: var(--cust-text) !important;
}}

[data-testid="stButtonGroup"] button[kind="segmented_control"]:hover:not(:disabled),
[data-testid="stButtonGroup"] button[kind="segmented_control"]:focus-visible:not(:disabled) {{
    background: var(--cust-button-hover) !important;
    border-color: var(--cust-button-accent) !important;
}}

[data-testid="stButtonGroup"] button[kind="segmented_controlActive"] {{
    background: var(--cust-button-accent) !important;
    border-color: var(--cust-button-accent) !important;
    color: var(--cust-button-accent-text) !important;
}}

[data-testid="stButtonGroup"] button[kind^="segmented_control"] *,
[data-testid="stButtonGroup"] button[kind^="segmented_control"] span {{
    color: inherit !important;
    -webkit-text-fill-color: currentColor !important;
    opacity: 1 !important;
}}

[data-testid="stMarkdownContainer"] a {{
    overflow-wrap: anywhere;
    word-break: break-word;
}}

[data-testid="stForm"]:has(input[aria-label="客服訊息"]) button[kind="secondaryFormSubmit"] {{
    border-color: var(--cust-button-accent) !important;
    background: var(--cust-button-accent) !important;
    color: var(--cust-button-accent-text) !important;
    font-weight: 800 !important;
}}

hr {{
    border-color: var(--cust-border) !important;
}}
</style>
""", unsafe_allow_html=True)

render_hidden_html(
    """
    <script>
    (() => {
        const parentWindow = window.parent;
        const parentDocument = parentWindow.document;
        const navKey = `cust-app:${parentWindow.location.pathname}:${parentWindow.performance.timeOrigin}`;
        const storageKey = "custAppInitialScrollTopNavKey";
        const shouldScrollTop = parentWindow.sessionStorage.getItem(storageKey) !== navKey;
        const navigationEntry = parentWindow.performance
            .getEntriesByType("navigation")?.[0];

        parentWindow.history.scrollRestoration = "manual";
        if (!shouldScrollTop || navigationEntry?.type !== "navigate") {
            return;
        }
        parentWindow.sessionStorage.setItem(storageKey, navKey);

        const scrollTargets = () => [
            parentDocument.scrollingElement,
            parentDocument.documentElement,
            parentDocument.body,
            parentDocument.querySelector('[data-testid="stAppViewContainer"]'),
            parentDocument.querySelector('[data-testid="stMain"]'),
            parentDocument.querySelector('section.main')
        ].filter(Boolean);

        const scrollToTop = () => {
            const targets = scrollTargets();
            const alreadyAtTop = (
                Math.abs(parentWindow.scrollY || 0) <= 1
                && targets.every((element) => Math.abs(element.scrollTop || 0) <= 1)
            );
            if (alreadyAtTop) {
                return;
            }
            parentWindow.scrollTo({ top: 0, left: 0, behavior: "instant" });
            targets.forEach((element) => {
                element.scrollTop = 0;
                element.scrollLeft = 0;
            });
        };

        parentWindow.requestAnimationFrame(scrollToTop);
    })();
    </script>
    """,
    height=0,
    width=0,
)

# =========================
# 3. API 工具
# =========================

def test_web_user_id(user_id: str) -> str:
    value = (user_id or "").strip()
    if value.startswith("test_web:"):
        return value
    return f"test_web:{value}"


def simulated_web_custnum() -> str | None:
    if not st.session_state.simulate_web_authenticated_custnum:
        return None
    value = st.session_state.confirmed_web_custnum
    return value or None


def confirm_web_custnum() -> None:
    if st.session_state.confirmed_web_custnum:
        return
    value = str(st.session_state.simulated_web_custnum or "")
    if not re.fullmatch(r"[0-9]+", value):
        st.session_state.web_custnum_error = "API 預帶客編只能輸入 0～9 的數字，不可留空或包含空白、中文、英文字母及符號。"
        return
    st.session_state.confirmed_web_custnum = value
    st.session_state.web_custnum_error = ""


def unlock_web_custnum() -> None:
    st.session_state.confirmed_web_custnum = ""
    st.session_state.simulated_web_custnum = ""
    st.session_state.web_custnum_error = ""


def chat_backend_user_id(user_id: str, web_custnum: str | None = None) -> str:
    test_user_id = test_web_user_id(user_id)
    return f"web:{test_user_id}" if web_custnum else test_user_id


def fetch_state(user_id: str, tv_cable: str, web_custnum: str | None = None):
    backend_user_id = chat_backend_user_id(user_id, web_custnum)
    try:
        resp = backend_request(
            "GET",
            f"{API_BASE}/state/{backend_user_id}",
            params={"tv_cable": tv_cable},
            timeout=15,
        )
        if resp.status_code == 200:
            return resp.json()
        return {
            "status": "error",
            "message": backend_error_message(resp)
        }
    except Exception as e:
        return {
            "status": "error",
            "message": str(e)
        }


def fetch_companies():
    try:
        resp = backend_request("GET", f"{API_BASE}/companies", timeout=15)
        if resp.status_code == 200:
            data = resp.json()
            companies = data.get("companies", [])
            if companies:
                return sort_company_options(companies)
    except Exception:
        pass

    return sort_company_options(FALLBACK_COMPANIES)


def fetch_feedback_tracker_overview(start_date: str = "2026-08-24"):
    try:
        response = backend_request(
            "GET",
            f"{API_BASE}/api/feedback-tracker/overview",
            params={"start_date": start_date},
            timeout=30,
            actor=True,
        )
        if response.status_code == 200:
            return response.json()
        return {"status": "error", "message": backend_error_message(response)}
    except Exception as exc:
        return {"status": "error", "message": str(exc)}


def sync_feedback_tracker(action: str):
    try:
        response = backend_request(
            "POST",
            f"{API_BASE}/api/feedback-tracker/sync/{action}",
            timeout=30,
            actor=True,
        )
        if response.status_code == 200:
            return response.json()
        return {"status": "error", "message": backend_error_message(response)}
    except Exception as exc:
        return {"status": "error", "message": str(exc)}


def feedback_tracker_sync_message(action: str, result: dict) -> str:
    if result.get("status") != "success":
        return str(result.get("message") or "同步失敗。")
    if action == "pull":
        message = (
            f"已拉取 {result.get('imported', 0)} 筆線上回饋、"
            f"{result.get('conversation_logs_imported', 0)} 則客戶與 AI 對話，"
            f"{result.get('latency_logs_imported', 0)} 筆處理紀錄，"
            f"以及 {result.get('tracking_updates_applied', 0)} 筆較新的線上追蹤狀態。"
        )
        if not result.get("tracking_updates_available", False):
            message += " 線上端版本尚未提供追蹤狀態，請先更新線上程式。"
        if (
            result.get("feedback_truncated")
            or result.get("conversation_logs_truncated")
            or result.get("latency_logs_truncated")
        ):
            message += " 資料量超過單次上限，下次拉取會接續處理。"
        return message
    return (
        f"已發布 {result.get('case_definitions', 0)} 個回歸驗證案例、"
        f"{result.get('feedback_states', 0)} 筆回饋與 "
        f"{result.get('case_states', 0)} 筆案例的追蹤狀態。"
    )


def run_feedback_tracker_sync(action: str) -> None:
    with st.spinner("同步中..."):
        result = sync_feedback_tracker(action)
    st.session_state.tracker_sync_notice = {
        "action": action,
        "result": result,
    }
    st.rerun()


@st.dialog("確認拉取線上資料", dismissible=False)
def confirm_pull_feedback_tracker():
    st.info(
        "這會從線上讀取新增的回饋、客戶與 AI 對話、處理紀錄，"
        "並合併較新的追蹤狀態。線上資料不會被修改。"
    )
    confirm_cols = st.columns(2)
    if confirm_cols[0].button("確認拉取", type="primary", width="stretch", key="confirm_tracker_pull"):
        run_feedback_tracker_sync("pull")
    if confirm_cols[1].button("取消", width="stretch", key="cancel_tracker_pull"):
        st.rerun()


@st.dialog("確認更新線上追蹤頁", dismissible=False)
def confirm_publish_feedback_tracker():
    st.warning("這會將本機的回歸驗證案例與追蹤狀態發布到線上。線上較新的追蹤狀態會保留，不會被舊資料覆蓋。")
    confirm_cols = st.columns(2)
    if confirm_cols[0].button("確認更新", type="primary", width="stretch", key="confirm_tracker_publish"):
        run_feedback_tracker_sync("publish")
    if confirm_cols[1].button("取消", width="stretch", key="cancel_tracker_publish"):
        st.rerun()


def save_feedback_tracker_item(feedback_id: str, payload: dict):
    try:
        response = backend_request(
            "PUT",
            f"{API_BASE}/api/feedback-tracker/feedback/{quote(feedback_id, safe='')}",
            json=payload,
            timeout=20,
            actor=True,
        )
        if response.status_code == 200:
            return response.json()
        return {"status": "error", "message": backend_error_message(response)}
    except Exception as exc:
        return {"status": "error", "message": str(exc)}


def save_regression_case_tracker_item(case_id: str, payload: dict):
    try:
        response = backend_request(
            "PUT",
            f"{API_BASE}/api/feedback-tracker/cases/{quote(case_id, safe='')}",
            json=payload,
            timeout=20,
            actor=True,
        )
        if response.status_code == 200:
            return response.json()
        return {"status": "error", "message": backend_error_message(response)}
    except Exception as exc:
        return {"status": "error", "message": str(exc)}


COMPANY_PROFILE_EDIT_FIELDS = [
    ("address", "地址"),
    ("phone", "電話"),
    ("business_hours", "營業時間"),
    ("service_area", "服務地區"),
    ("service_products", "目前服務產品"),
    ("area_outage", "區域故障"),
    ("promotion_activity", "優惠活動"),
    ("urls", "公司網址"),
    ("value_added_urls", "加值服務網址"),
]

COMPANY_PROFILE_CONFIRM_LABELS = {
    "address_phone": "地址電話",
    "business_hours": "營業時間",
    "service_area": "服務地區",
    "service_products": "目前服務產品",
    "area_outage": "區域故障",
    "promotion_activity": "優惠活動",
    "urls": "公司網址",
    "value_added_urls": "加值服務網址",
}

COMPANY_PROFILE_READONLY_FIELDS = [
    ("company_name", "公司名稱"),
    ("class", "系統台類別"),
    ("tv_cable", "系統台代碼"),
    ("service_items", "服務範圍（系統判斷）"),
    ("app_name", "App"),
    ("tax_id", "統一編號"),
]


def company_option_label(item: dict) -> str:
    class_name = display_base_name(item.get("class"))
    company_name = item.get("company_name")
    if class_name and company_name and class_name not in company_name:
        return f"{class_name} - {company_name}"
    return company_name or class_name or item.get("label") or item.get("code", "")


def sort_company_options(companies: list[dict]) -> list[dict]:
    return sorted(
        companies,
        key=lambda item: (
            base_display_order_index(item.get("class") or item.get("company_name") or ""),
            company_option_label(item).casefold(),
            str(item.get("code") or "").casefold(),
        ),
    )


def split_company_address_phone(address_phone: str) -> tuple[str, str]:
    text = str(address_phone or "").strip()
    for separator in ["，市內電話：", "，市內電話:", "，電話：", "，電話:", "，"]:
        if separator in text:
            address, phone = text.split(separator, 1)
            return address.strip(), phone.strip()
    return text, ""


def join_company_address_phone(address: str, phone: str) -> str:
    clean_address = str(address or "").strip()
    clean_phone = str(phone or "").strip()
    if clean_address and clean_phone:
        return f"{clean_address}，市內電話：{clean_phone}"
    return clean_address or clean_phone


def render_inline_diff(old_value: str, new_value: str) -> str:
    old_value = old_value or ""
    new_value = new_value or ""
    matcher = difflib.SequenceMatcher(None, old_value, new_value)
    old_parts = []
    new_parts = []

    for tag, old_start, old_end, new_start, new_end in matcher.get_opcodes():
        old_text = html.escape(old_value[old_start:old_end]).replace("\n", "<br>")
        new_text = html.escape(new_value[new_start:new_end]).replace("\n", "<br>")
        if tag == "equal":
            old_parts.append(old_text)
            new_parts.append(new_text)
        elif tag == "delete":
            old_parts.append(f'<span class="company-diff-delete">{old_text}</span>')
        elif tag == "insert":
            new_parts.append(f'<span class="company-diff-add">{new_text}</span>')
        elif tag == "replace":
            old_parts.append(f'<span class="company-diff-delete">{old_text}</span>')
            new_parts.append(f'<span class="company-diff-add">{new_text}</span>')

    old_html = "".join(old_parts) or '<span class="company-diff-empty">空白</span>'
    new_html = "".join(new_parts) or '<span class="company-diff-empty">空白</span>'
    return f"""
    <div class="company-diff-lines">
      <div><span class="company-diff-label">原本：</span>{old_html}</div>
      <div><span class="company-diff-label">更新後：</span>{new_html}</div>
    </div>
    """


def fetch_company_profiles():
    try:
        resp = backend_request("GET", f"{API_BASE}/api/company-profiles", timeout=30)
        if resp.status_code == 200:
            return resp.json()
        return {
            "status": "error",
            "message": backend_error_message(resp),
            "profiles": [],
        }
    except Exception as e:
        return {
            "status": "error",
            "message": str(e),
            "profiles": [],
        }


def update_company_profile(company_code: str, payload: dict):
    try:
        resp = backend_request(
            "PUT",
            f"{API_BASE}/api/company-profiles/{company_code}",
            json=payload,
            timeout=30,
        )
        if resp.status_code == 200:
            return resp.json()
        return {
            "status": "error",
            "message": backend_error_message(resp),
        }
    except Exception as e:
        return {
            "status": "error",
            "message": str(e),
        }


def reset_backend_state(user_id: str, web_custnum: str | None = None):
    backend_user_id = chat_backend_user_id(user_id, web_custnum)
    try:
        resp = backend_request(
            "POST",
            f"{API_BASE}/reset/{backend_user_id}",
            timeout=15,
        )
        if resp.status_code == 200:
            return resp.json()
        return {
            "status": "error",
            "message": backend_error_message(resp),
        }
    except Exception as e:
        return {
            "status": "error",
            "message": str(e),
        }


def send_message(
    user_id: str,
    message: str,
    tv_cable: str,
    web_custnum: str | None = None,
    receipt_evidence_token: str | None = None,
):
    backend_user_id = test_web_user_id(user_id)
    started = time.perf_counter()
    try:
        if web_custnum:
            resp = backend_request(
                "POST",
                f"{API_BASE}/api/v1/chat",
                json={
                    "request_id": f"test-web-custnum-{uuid.uuid4().hex}",
                    "channel": "web",
                    "user_id": backend_user_id,
                    "member_id": backend_user_id,
                    "custnum": web_custnum,
                    "is_logged_in": True,
                    "company_code": tv_cable,
                    "msg": message,
                    "metadata": {"source": "test_web_custnum_simulator"},
                    "receipt_evidence_token": receipt_evidence_token,
                },
                timeout=300,
            )
        else:
            resp = backend_request(
                "POST",
                f"{API_BASE}/chat",
                json={
                    "user_id": backend_user_id,
                    "user_input": message,
                    "tv_cable": tv_cable,
                    "receipt_evidence_token": receipt_evidence_token,
                },
                timeout=300,
            )
        request_time_sec = round(time.perf_counter() - started, 3)
        if resp.status_code == 200:
            data = resp.json()
            if web_custnum:
                data["ai_response"] = data.get("msg") or "系統沒有回應"
            data["request_time_sec"] = request_time_sec
            latency = data.get("latency") or {}
            if data.get("cust_api_time_sec") is None and latency.get("cust_api") is not None:
                data["cust_api_time_sec"] = latency.get("cust_api")
            if data.get("response_time_sec") is None:
                data["response_time_sec"] = request_time_sec
            return data
        return {
            "status": "error",
            "ai_response": f"API 錯誤：{backend_error_message(resp)}",
            "response_time_sec": request_time_sec,
            "request_time_sec": request_time_sec,
        }
    except Exception as e:
        request_time_sec = round(time.perf_counter() - started, 3)
        return {
            "status": "error",
            "ai_response": f"後端連線失敗：{e}",
            "response_time_sec": request_time_sec,
            "request_time_sec": request_time_sec,
        }


def analyze_image_with_ocr(
    image_bytes: bytes,
    mime_type: str | None,
    prompt: str | None = None,
    user_id: str | None = None,
):
    started = time.perf_counter()
    try:
        resp = backend_request(
            "POST",
            f"{API_BASE}/api/ocr/image",
            json={
                "image_base64": base64.b64encode(image_bytes).decode("ascii"),
                "mime_type": mime_type,
                "prompt": prompt.strip() if prompt and prompt.strip() else None,
                "source": "web_ui",
                "user_id": user_id,
            },
            timeout=180,
        )
        request_time_sec = round(time.perf_counter() - started, 3)
        if resp.status_code == 200:
            result = resp.json()
            result["request_time_sec"] = request_time_sec
            result.setdefault("ocr_time_sec", request_time_sec)
            return result
        return {
            "status": "error",
            "message": normalize_ocr_error_message(resp),
            "raw_message": backend_error_message(resp),
            "request_time_sec": request_time_sec,
        }
    except Exception as e:
        request_time_sec = round(time.perf_counter() - started, 3)
        return {
            "status": "error",
            "message": f"OCR 後端連線失敗：{e}",
            "request_time_sec": request_time_sec,
        }


def normalize_ocr_error_message(resp) -> str:
    if is_invalid_api_token_response(resp):
        return backend_error_message(resp)

    raw_text = getattr(resp, "text", "") or ""
    status_code = getattr(resp, "status_code", None)
    detail = raw_text

    try:
        payload = resp.json()
        if isinstance(payload, dict):
            detail = payload.get("detail") or payload.get("message") or raw_text
    except ValueError:
        pass

    detail_text = str(detail)
    detail_lower = detail_text.lower()

    if status_code == 503 or "503 unavailable" in detail_lower or "high demand" in detail_lower:
        return "圖片辨識服務目前忙碌，請稍後再試一次。"
    if "gemini_api_key" in detail_lower:
        return "OCR 金鑰尚未設定，請確認後端環境變數 GEMINI_API_KEY。"
    if "image_base64" in detail_lower or "base64" in detail_lower:
        return "圖片上傳格式不正確，請重新選擇圖片後再試一次。"
    if "無法辨識圖片格式" in detail_text:
        return "無法辨識圖片格式，請確認檔案是否為有效圖片。"
    if "沒有產生可用文字" in detail_text:
        return "圖片辨識沒有產生可用文字，請換一張較清楚的圖片再試。"

    return f"OCR API 錯誤：{detail_text}"


def fetch_kb_documents(status: str = "active"):
    try:
        resp = backend_request(
            "GET",
            f"{API_BASE}/api/kb/documents",
            params={"status": status},
            actor=True,
            timeout=30,
        )
        if resp.status_code == 200:
            return resp.json()
        return {
            "status": "error",
            "message": backend_error_message(resp),
            "documents": [],
        }
    except Exception as e:
        return {
            "status": "error",
            "message": str(e),
            "documents": [],
        }


def upload_kb_document(file_obj, title: str, knowledge_base: str):
    try:
        resp = backend_request(
            "POST",
            f"{API_BASE}/api/kb/documents",
            json={
                "file_name": file_obj.name,
                "file_base64": base64.b64encode(file_obj.getvalue()).decode("ascii"),
                "title": title.strip() if title and title.strip() else None,
                "knowledge_base": knowledge_base.strip() or "通用",
                "category": None,
                "status": "active",
            },
            actor=True,
            timeout=300,
        )
        if resp.status_code == 200:
            result = resp.json()
            result["action"] = "upload"
            return result
        return {
            "status": "error",
            "action": "upload",
            "message": backend_error_message(resp),
        }
    except Exception as e:
        return {
            "status": "error",
            "action": "upload",
            "message": str(e),
        }


def upload_kb_documents(file_objs: list, title_prefix: str, knowledge_base: str):
    results = []
    total = len(file_objs)
    progress = st.progress(0)

    for index, file_obj in enumerate(file_objs, start=1):
        title = ""
        if title_prefix and title_prefix.strip():
            if total == 1:
                title = title_prefix.strip()
            else:
                title = f"{title_prefix.strip()} - {file_obj.name}"

        result = upload_kb_document(file_obj, title, knowledge_base)
        result["file_name"] = file_obj.name
        results.append(result)
        progress.progress(index / total)

    progress.empty()
    return results


def sort_kb_base_names(names: list[str]) -> list[str]:
    unique_by_display: dict[str, str] = {}
    for name in names:
        clean_name = normalize_knowledge_base_name(name)
        if not clean_name:
            continue
        unique_by_display.setdefault(display_base_name(clean_name), clean_name)
    return sorted(
        unique_by_display.values(),
        key=lambda name: (base_display_order_index(name), display_base_name(name), name),
    )


def build_kb_base_options(company_options: list[dict]) -> list[str]:
    options = list(REGIONAL_COMMON_KNOWLEDGE_BASES)
    for item in company_options:
        class_name = item.get("class") or item.get("company_name")
        if class_name and class_name not in options:
            options.append(class_name)
    return sort_kb_base_names(options)


def manageable_kb_base_options(account: dict, options: list[str]) -> list[str]:
    if account.get("role") == ROLE_DEVELOPER:
        return list(options)
    return [
        knowledge_base for knowledge_base in options
        if can_manage_knowledge_base(account, knowledge_base)
    ]


def viewable_kb_base_options(account: dict, options: list[str]) -> list[str]:
    if not can_view_knowledge_base(account):
        return []
    return list(options)


def assignable_kb_base_options(options: list[str]) -> list[str]:
    return sort_kb_base_names(options)


def format_managed_kb_bases(account: dict) -> str:
    if account.get("role") == ROLE_DEVELOPER:
        return "全部"
    if account.get("role") != ROLE_SUPERVISOR:
        return "-"
    values = account.get("managed_knowledge_bases") or []
    return "、".join(display_base_name(value) for value in values) or "未設定"


KB_CATEGORY_LABELS = {
    "": "不指定",
    "billing": "帳務",
    "network_support": "網路支援",
    "set_top_box": "電視/機上盒",
    "value_added_service": "加值服務",
    "policy": "規定/政策",
    "sop": "內部流程",
}

KB_DOCUMENT_SORT_OPTIONS = [
    "上傳日期：新到舊",
    "上傳日期：舊到新",
    "檔案名稱：A-Z",
    "檔案名稱：Z-A",
]


def reindex_kb_document(document_id: str):
    try:
        resp = backend_request(
            "POST",
            f"{API_BASE}/api/kb/documents/{document_id}/reindex",
            actor=True,
            timeout=300,
        )
        if resp.status_code == 200:
            result = resp.json()
            result["action"] = "reindex"
            return result
        return {
            "status": "error",
            "action": "reindex",
            "message": backend_error_message(resp),
        }
    except Exception as e:
        return {
            "status": "error",
            "action": "reindex",
            "message": str(e),
        }


def reindex_all_kb_documents():
    try:
        resp = backend_request(
            "POST",
            f"{API_BASE}/api/kb/documents/reindex-all",
            actor=True,
            timeout=1800,
        )
        if resp.status_code == 200:
            result = resp.json()
            result["action"] = "reindex_all"
            return result
        return {
            "status": "error",
            "action": "reindex_all",
            "message": backend_error_message(resp),
        }
    except Exception as e:
        return {
            "status": "error",
            "action": "reindex_all",
            "message": str(e),
        }


def chat_search_kb_documents(plan_name: str, knowledge_base: str, limit: int = 8):
    payload = {
        "plan_name": plan_name,
        "knowledge_base": knowledge_base.strip() or "通用",
        "category": None,
        "limit": limit,
    }
    try:
        resp = backend_request(
            "POST",
            f"{API_BASE}/api/kb/chat-search",
            json=payload,
            timeout=120,
        )
        if resp.status_code == 200:
            result = resp.json()
            result["diagnostic_mode"] = "聊天同款檢索"
            return result
        if resp.status_code == 404:
            fallback_resp = backend_request(
                "POST",
                f"{API_BASE}/api/kb/search",
                json=payload,
                timeout=120,
            )
            if fallback_resp.status_code == 200:
                result = fallback_resp.json()
                result["diagnostic_mode"] = "舊版直接搜尋"
                result["chat_search_unavailable"] = True
                result["warning"] = (
                    "後端找不到 /api/kb/chat-search。這通常代表遠端後端尚未部署最新版，"
                    "或前端連到舊後端；目前暫時顯示舊版直接搜尋結果，不含聊天實際使用的關鍵字補強與合併邏輯。"
                )
                return result
            return {
                "status": "error",
                "message": (
                    "後端找不到 /api/kb/chat-search，且舊版 /api/kb/search 也測試失敗。"
                    f"chat-search 回應：{backend_error_message(resp)}；search 回應：{backend_error_message(fallback_resp)}"
                ),
                "sources": [],
            }
        return {
            "status": "error",
            "message": backend_error_message(resp),
            "sources": [],
        }
    except Exception as e:
        return {
            "status": "error",
            "message": str(e),
            "sources": [],
        }


def delete_kb_document(document_id: str):
    try:
        resp = backend_request(
            "DELETE",
            f"{API_BASE}/api/kb/documents/{document_id}",
            actor=True,
            timeout=180,
        )
        if resp.status_code == 200:
            result = resp.json()
            result["action"] = "delete"
            return result
        return {
            "status": "error",
            "action": "delete",
            "message": backend_error_message(resp),
        }
    except Exception as e:
        return {
            "status": "error",
            "action": "delete",
            "message": str(e),
        }


def fetch_kb_audit_logs(limit: int = 200):
    try:
        resp = backend_request(
            "GET",
            f"{API_BASE}/api/kb/audit-logs",
            params={"action": "delete_kb_document", "limit": limit},
            actor=True,
            timeout=30,
        )
        if resp.status_code == 200:
            return resp.json()
        return {
            "status": "error",
            "message": backend_error_message(resp),
            "records": [],
        }
    except Exception as exc:
        return {
            "status": "error",
            "message": str(exc),
            "records": [],
        }


def kb_preview_url(document_id: str) -> str:
    url = f"{PUBLIC_API_BASE}/api/kb/documents/{document_id}/preview"
    token = backend_api_token_for_direct_url()
    parsed = urlsplit(url)
    query_items = parse_qsl(parsed.query, keep_blank_values=True)
    if token:
        query_items.append(("api_token", token))
    web_auth_token = str(st.session_state.get("web_auth_token") or "").strip()
    if web_auth_token:
        query_items.append(("web_auth_token", web_auth_token))
    return urlunsplit((
        parsed.scheme,
        parsed.netloc,
        parsed.path,
        urlencode(query_items),
        parsed.fragment,
    ))


def kb_file_download_url(document_id: str) -> str:
    url = f"{PUBLIC_API_BASE}/api/kb/documents/{document_id}/file"
    token = backend_api_token_for_direct_url()
    parsed = urlsplit(url)
    query_items = parse_qsl(parsed.query, keep_blank_values=True)
    query_items.append(("download", "true"))
    if token:
        query_items.append(("api_token", token))
    web_auth_token = str(st.session_state.get("web_auth_token") or "").strip()
    if web_auth_token:
        query_items.append(("web_auth_token", web_auth_token))
    return urlunsplit((
        parsed.scheme,
        parsed.netloc,
        parsed.path,
        urlencode(query_items),
        parsed.fragment,
    ))


def render_preview_link(document_id: str, disabled: bool = False):
    if disabled or not document_id:
        st.markdown(
            '<span class="kb-preview-link is-disabled" aria-disabled="true">查看</span>',
            unsafe_allow_html=True,
        )
        return

    url = kb_preview_url(document_id)
    st.markdown(
        f"""
        <a class="kb-preview-link" href="{url}" target="_blank" rel="noopener noreferrer">查看</a>
        """,
        unsafe_allow_html=True,
    )


def render_download_link(document_id: str, file_name: str, disabled: bool = False, label: str = "下載"):
    if disabled or not document_id:
        st.markdown(
            f'<span class="kb-preview-link kb-download-link is-disabled" aria-disabled="true">{html.escape(label, quote=False)}</span>',
            unsafe_allow_html=True,
        )
        return

    url = kb_file_download_url(document_id)
    safe_file_name = html.escape(str(file_name or "knowledge-file"), quote=True)
    safe_label = html.escape(label, quote=False)
    st.markdown(
        f"""
        <a class="kb-preview-link kb-download-link" href="{url}" download="{safe_file_name}" rel="noopener noreferrer">{safe_label}</a>
        """,
        unsafe_allow_html=True,
    )


def kb_status_label(status: str) -> str:
    labels = {
        "indexed": "已索引",
        "processing": "處理中",
        "queued": "佇列中",
        "failed": "失敗",
        "deleted": "已刪除",
    }
    return labels.get(str(status or ""), str(status or "未知"))


def kb_status_class(status: str) -> str:
    return "kb-pill-ok" if status == "indexed" else "kb-pill-warn"


def format_kb_audit_time(value: str | None) -> str:
    text = str(value or "").strip()
    if not text:
        return "-"
    try:
        iso_text = text.replace("Z", "+00:00")
        parsed = datetime.fromisoformat(iso_text)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        local_time = parsed.astimezone(DISPLAY_TIMEZONE)
        return local_time.strftime("%Y-%m-%d %H:%M:%S UTC+8")
    except ValueError:
        text = text.replace("T", " ")
        text = re.sub(r"\.\d+", "", text)
        text = text.replace("+00:00", " UTC+8")
        return text


def parse_kb_sort_time(value: str | None) -> datetime:
    text = str(value or "").strip()
    if not text:
        return datetime.min.replace(tzinfo=timezone.utc)
    try:
        iso_text = text.replace("Z", "+00:00")
        parsed = datetime.fromisoformat(iso_text)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)
    except ValueError:
        return datetime.min.replace(tzinfo=timezone.utc)


def kb_document_sort_name(doc: dict) -> str:
    text = str(doc.get("file_name") or doc.get("title") or "").strip()
    return text.casefold()


def kb_document_sort_uploaded_at(doc: dict) -> datetime:
    return parse_kb_sort_time(doc.get("uploaded_at") or doc.get("created_at"))


def sort_kb_documents(documents: list[dict], sort_mode: str) -> list[dict]:
    if sort_mode == "上傳日期：舊到新":
        return sorted(documents, key=lambda doc: (kb_document_sort_uploaded_at(doc), kb_document_sort_name(doc)))
    if sort_mode == "檔案名稱：A-Z":
        return sorted(documents, key=lambda doc: (kb_document_sort_name(doc), kb_document_sort_uploaded_at(doc)))
    if sort_mode == "檔案名稱：Z-A":
        return sorted(documents, key=lambda doc: (kb_document_sort_name(doc), kb_document_sort_uploaded_at(doc)), reverse=True)
    return sorted(documents, key=lambda doc: (kb_document_sort_uploaded_at(doc), kb_document_sort_name(doc)), reverse=True)


def render_kb_audit_line(doc: dict) -> str:
    uploaded_by = html.escape(
        str(doc.get("uploaded_by_display_name") or doc.get("uploaded_by") or "-"),
        quote=False,
    )
    uploaded_at = html.escape(format_kb_audit_time(doc.get("uploaded_at") or doc.get("created_at")), quote=False)
    indexed_by = html.escape(
        str(doc.get("last_indexed_by_display_name") or doc.get("last_indexed_by") or "-"),
        quote=False,
    )
    indexed_at = html.escape(format_kb_audit_time(doc.get("last_indexed_at") or doc.get("processed_at")), quote=False)
    return (
        "<div class=\"kb-doc-audit\">"
        f"<strong>上傳</strong>：{uploaded_by} / {uploaded_at}<br>"
        f"<strong>索引</strong>：{indexed_by} / {indexed_at}"
        "</div>"
    )


def kb_tab_label(name: str, count: int) -> str:
    return f"{name} ({count})"


def render_kb_summary(documents: list[dict]):
    indexed_count = sum(1 for doc in documents if doc.get("processing_status") == "indexed")
    kb_count = len({doc.get("knowledge_base") or "通用" for doc in documents})
    chunk_count = sum(int(doc.get("indexed_chunk_count") or 0) for doc in documents)

    summary_cols = st.columns(3)
    for col, label, value in [
        (summary_cols[0], "文件數", len(documents)),
        (summary_cols[1], "已索引", indexed_count),
        (summary_cols[2], "索引片段", chunk_count),
    ]:
        col.markdown(
            f"""
            <div class="kb-summary">
              <div class="kb-summary-label">{label}</div>
              <div class="kb-summary-value">{value}</div>
            </div>
            """,
            unsafe_allow_html=True,
        )
    st.caption(
        f"目前維護 {kb_count} 個知識庫分類。跨系統台規則請依服務區域放入"
        "「通用-中區」或「通用-嘉南區」，各系統台分頁則放個別 SOP 或方案。"
    )


def render_kb_document_row(doc: dict, key_prefix: str = ""):
    doc_id = doc.get("id")
    safe_doc_id = html.escape(str(doc_id or ""), quote=True)
    title = doc.get("title") or "-"
    file_name = doc.get("file_name") or "-"
    knowledge_base = display_base_name(doc.get("knowledge_base") or "通用")
    category = KB_CATEGORY_LABELS.get(doc.get("category") or "", "未分類")
    status = doc.get("processing_status") or "unknown"
    chunks = doc.get("indexed_chunk_count", 0)
    campaign_profile = doc.get("campaign_profile") if isinstance(doc.get("campaign_profile"), dict) else {}
    campaign_validation = (
        campaign_profile.get("validation")
        if isinstance(campaign_profile.get("validation"), dict)
        else {}
    )
    campaign_note = ""
    if doc.get("document_type") == "promotion_campaign" or campaign_profile:
        campaign_status = str(campaign_validation.get("status") or doc.get("campaign_validation_status") or "")
        if campaign_status == "complete":
            campaign_note = '<div class="kb-doc-meta">方案欄位：已結構化</div>'
        else:
            missing_fields = campaign_validation.get("missing_fields") or []
            missing_text = "、".join(str(value) for value in missing_fields if value)
            campaign_note = (
                '<div class="kb-doc-meta">方案欄位：建議檢查'
                f'{html.escape("（" + missing_text + "）", quote=False) if missing_text else ""}</div>'
            )
    can_write_doc = can_manage_knowledge_base(
        CURRENT_WEB_ACCOUNT,
        doc.get("knowledge_base") or LEGACY_COMMON_KNOWLEDGE_BASE,
    )
    access_note = "" if can_write_doc else '<div class="kb-doc-meta">權限：唯讀</div>'

    with st.container(border=True):
        st.markdown(
            f'<span class="kb-doc-card-marker" data-kb-doc-id="{safe_doc_id}"></span>',
            unsafe_allow_html=True,
        )
        info_cols = st.columns([3.4, 1.15, 1.15, 1.1, 1.05])
        info_cols[0].markdown(
            f"""
            <div class="kb-doc-title">{title}</div>
            <div class="kb-doc-meta">{file_name}</div>
            {campaign_note}
            {access_note}
            {render_kb_audit_line(doc)}
            """,
            unsafe_allow_html=True,
        )
        info_cols[1].markdown(f'<span class="kb-pill">{knowledge_base}</span>', unsafe_allow_html=True)
        info_cols[2].markdown(f'<span class="kb-pill">{category}</span>', unsafe_allow_html=True)
        info_cols[3].markdown(f'<span class="kb-pill">{chunks} chunks</span>', unsafe_allow_html=True)
        info_cols[4].markdown(
            f'<span class="kb-pill {kb_status_class(status)}">{kb_status_label(status)}</span>',
            unsafe_allow_html=True,
        )

        is_any_kb_write_processing = kb_write_operation_in_progress()
        can_view_doc = bool(doc_id) and not st.session_state.is_generating
        can_operate_doc = can_view_doc and can_write_doc and not is_any_kb_write_processing
        action_cols = st.columns([1, 1, 1, 1, 3.6])
        key_suffix = f"{key_prefix}_{doc_id}"
        if action_cols[0].button(
            "重建",
            key=f"reindex_{key_suffix}",
            width="stretch",
            disabled=not can_operate_doc,
            help=(
                "重新抽取此文件並更新索引"
                if can_write_doc
                else "此知識庫未授權修改；您仍可查看或下載原始文件"
            ),
        ):
            confirm_reindex_kb_document(doc)
        with action_cols[1]:
            render_preview_link(doc_id, disabled=not can_view_doc)
        if action_cols[2].button(
            "下載",
            key=f"download_{key_suffix}",
            width="stretch",
            disabled=not can_view_doc,
            help="下載原始檔前會再次確認",
        ):
            confirm_download_kb_document(doc)
        if action_cols[3].button(
            "刪除",
            key=f"delete_{key_suffix}",
            type="primary",
            width="stretch",
            disabled=not can_operate_doc,
            help=(
                "刪除原始檔與索引前會再次確認"
                if can_write_doc
                else "此知識庫未授權修改；您仍可查看或下載原始文件"
            ),
        ):
            confirm_delete_kb_document(doc)


def render_kb_document_tabs(documents: list[dict], kb_base_options: list[str]):
    base_counts: dict[str, int] = {}
    for doc in documents:
        base = display_base_name(doc.get("knowledge_base") or "通用")
        base_counts[base] = base_counts.get(base, 0) + 1

    tab_names = ["全部"]
    ordered_base_options = sort_kb_base_names(kb_base_options)
    for base in ordered_base_options:
        display_base = display_base_name(base)
        if display_base in base_counts and display_base not in tab_names:
            tab_names.append(display_base)
    for base in sort_kb_base_names(list(base_counts)):
        display_base = display_base_name(base)
        if display_base not in tab_names:
            tab_names.append(display_base)

    tabs = st.tabs([
        kb_tab_label(name, len(documents) if name == "全部" else base_counts.get(name, 0))
        for name in tab_names
    ])

    for tab, name in zip(tabs, tab_names):
        with tab:
            visible_docs = documents if name == "全部" else [
                doc for doc in documents
                if display_base_name(doc.get("knowledge_base") or "通用") == name
            ]
            if not visible_docs:
                st.info("這個知識庫目前沒有 active 文件。")
                continue
            for doc in visible_docs:
                render_kb_document_row(doc, key_prefix=name)


@st.dialog("確認刪除知識文件", dismissible=False)
def confirm_delete_kb_document(doc: dict):
    doc_id = doc.get("id")
    title = doc.get("title") or doc.get("file_name") or "-"
    file_name = doc.get("file_name") or "-"
    knowledge_base = display_base_name(doc.get("knowledge_base") or "-")
    indexed_chunk_count = doc.get("indexed_chunk_count", 0)

    st.warning("刪除後會移除原始檔與索引，客服對話將不會再查到這份文件。")
    st.write(f"**文件：** {title}")
    st.write(f"**檔名：** {file_name}")
    st.write(f"**知識庫：** {knowledge_base}")
    st.write(f"**索引片段：** {indexed_chunk_count} chunks")

    is_processing = (
        bool(doc_id)
        and st.session_state.kb_delete_document_processing_id == str(doc_id)
    )
    if is_processing:
        st.info("文件正在刪除，完成前不可重複送出或關閉此視窗。")

    confirm_cols = st.columns([1, 1])
    confirm_cols[0].button(
        "確認刪除",
        type="primary",
        width="stretch",
        disabled=not doc_id or is_processing,
        on_click=start_delete_kb_document,
        args=(doc_id,),
    )

    if confirm_cols[1].button(
        "取消",
        width="stretch",
        disabled=is_processing,
    ):
        st.session_state.pending_kb_scroll_restore = True
        st.rerun()

    if is_processing:
        with st.spinner("刪除中..."):
            try:
                st.session_state.last_kb_admin_result = delete_kb_document(doc_id)
                st.session_state.last_kb_batch_results = []
                st.session_state.last_kb_reindex_all_result = None
            finally:
                st.session_state.kb_delete_document_processing_id = ""
        st.rerun()

@st.dialog("確認下載原始文件", dismissible=False)
def confirm_download_kb_document(doc: dict):
    doc_id = doc.get("id")
    title = doc.get("title") or doc.get("file_name") or "-"
    file_name = doc.get("file_name") or "-"
    knowledge_base = display_base_name(doc.get("knowledge_base") or "-")

    st.info("請確認要下載的是這份原始文件。")
    st.write(f"**文件：** {title}")
    st.write(f"**檔名：** {file_name}")
    st.write(f"**知識庫：** {knowledge_base}")

    confirm_cols = st.columns([1, 1])
    if confirm_cols[0].button(
        "確認下載",
        type="primary",
        width="stretch",
        disabled=not doc_id,
    ):
        st.session_state.pending_kb_download = {
            "url": kb_file_download_url(doc_id),
            "file_name": file_name,
        }
        st.rerun()
    if confirm_cols[1].button("取消", width="stretch"):
        st.session_state.pending_kb_scroll_restore = True
        st.rerun()


def start_reindex_kb_document(doc_id: str):
    st.session_state.kb_reindex_document_processing_id = str(doc_id or "")
    st.session_state.pending_kb_scroll_restore = True


def start_delete_kb_document(doc_id: str):
    st.session_state.kb_delete_document_processing_id = str(doc_id or "")
    st.session_state.pending_kb_scroll_restore = True


def start_upload_kb_documents():
    st.session_state.is_kb_upload_processing = True


def kb_write_operation_in_progress() -> bool:
    return bool(
        st.session_state.is_kb_reindex_all_processing
        or st.session_state.kb_reindex_document_processing_id
        or st.session_state.kb_delete_document_processing_id
        or st.session_state.is_kb_upload_processing
    )


@st.dialog("確認重建知識索引", dismissible=False)
def confirm_reindex_kb_document(doc: dict):
    doc_id = doc.get("id")
    title = doc.get("title") or doc.get("file_name") or "-"
    file_name = doc.get("file_name") or "-"
    knowledge_base = display_base_name(doc.get("knowledge_base") or "-")
    indexed_chunk_count = doc.get("indexed_chunk_count", 0)

    st.warning("這會重新抽取此文件內容並更新索引。重建期間客服對話可能暫時查到舊片段。")
    st.write(f"**文件：** {title}")
    st.write(f"**檔名：** {file_name}")
    st.write(f"**知識庫：** {knowledge_base}")
    st.write(f"**目前索引片段：** {indexed_chunk_count} chunks")

    is_processing = (
        bool(doc_id)
        and st.session_state.kb_reindex_document_processing_id == str(doc_id)
    )
    if is_processing:
        st.info("此文件的知識索引正在重建，完成前不可重複送出或關閉此視窗。")

    confirm_cols = st.columns([1, 1])
    confirm_cols[0].button(
        "確認重建",
        type="primary",
        width="stretch",
        disabled=not doc_id or is_processing,
        on_click=start_reindex_kb_document,
        args=(doc_id,),
    )

    if confirm_cols[1].button(
        "取消",
        width="stretch",
        disabled=is_processing,
    ):
        st.session_state.pending_kb_scroll_restore = True
        st.rerun()

    if is_processing:
        with st.spinner("重建索引中..."):
            try:
                st.session_state.last_kb_admin_result = reindex_kb_document(doc_id)
                st.session_state.last_kb_batch_results = []
                st.session_state.last_kb_reindex_all_result = None
            finally:
                st.session_state.kb_reindex_document_processing_id = ""
        st.rerun()


def start_reindex_all_kb_documents():
    st.session_state.is_kb_reindex_all_processing = True
    st.session_state.pending_kb_scroll_restore = True


@st.dialog("確認全部重建索引", dismissible=False)
def confirm_reindex_all_kb_documents(document_count: int):
    st.warning("這會重新抽取所有 active 文件並重建整個向量索引。文件多時可能需要幾分鐘。")
    st.write(f"**將處理文件數：** {document_count}")

    is_processing = bool(st.session_state.is_kb_reindex_all_processing)
    if is_processing:
        st.info("全部索引正在重建，完成前不可重複送出或關閉此視窗。")

    confirm_cols = st.columns([1, 1])
    confirm_cols[0].button(
        "確認全部重建",
        type="primary",
        width="stretch",
        disabled=document_count <= 0 or is_processing,
        on_click=start_reindex_all_kb_documents,
    )

    if confirm_cols[1].button(
        "取消",
        width="stretch",
        disabled=is_processing,
    ):
        st.session_state.pending_kb_scroll_restore = True
        st.rerun()

    if is_processing:
        with st.spinner("全部索引重建中..."):
            try:
                st.session_state.last_kb_reindex_all_result = reindex_all_kb_documents()
                st.session_state.last_kb_admin_result = None
                st.session_state.last_kb_batch_results = []
            finally:
                st.session_state.is_kb_reindex_all_processing = False
        st.rerun()


@st.dialog("確認上傳並建立索引", dismissible=False)
def confirm_upload_kb_documents(file_objs: list, title_prefix: str, knowledge_base: str):
    total = len(file_objs or [])
    title_text = title_prefix.strip() if title_prefix and title_prefix.strip() else "未指定，將使用檔名"
    total_size = sum(len(file_obj.getvalue()) for file_obj in file_objs or [])

    st.info("建立索引後，客服對話的 RAG 會開始查詢這些文件內容。")
    st.write(f"**檔案數：** {total}")
    st.write(f"**總大小：** {total_size / 1024:.1f} KB")
    st.write(f"**文件標題：** {title_text}")
    st.write(f"**知識庫分類：** {display_base_name(knowledge_base)}")

    st.markdown("**將上傳的檔案**")
    for file_obj in file_objs or []:
        st.write(f"- {file_obj.name}（{len(file_obj.getvalue()) / 1024:.1f} KB）")

    if total > 1 and title_prefix and title_prefix.strip():
        st.warning("一次上傳多個檔案且有填文件標題時，系統會自動在標題後加上檔名，避免標題重複。")

    is_processing = bool(st.session_state.is_kb_upload_processing)
    if is_processing:
        st.info("檔案正在上傳並建立索引，完成前不可重複送出或關閉此視窗。")

    confirm_cols = st.columns([1, 1])
    confirm_cols[0].button(
        "確認建立索引",
        type="primary",
        width="stretch",
        disabled=total <= 0 or is_processing,
        on_click=start_upload_kb_documents,
    )

    if confirm_cols[1].button(
        "取消",
        width="stretch",
        disabled=is_processing,
    ):
        st.rerun()

    if is_processing:
        with st.spinner("建立知識庫索引中..."):
            try:
                st.session_state.last_kb_batch_results = upload_kb_documents(
                    file_objs,
                    title_prefix,
                    knowledge_base,
                )
                st.session_state.last_kb_admin_result = (
                    st.session_state.last_kb_batch_results[-1]
                    if st.session_state.last_kb_batch_results
                    else None
                )
                st.session_state.last_kb_reindex_all_result = None
                st.session_state.kb_upload_widget_version += 1
            finally:
                st.session_state.is_kb_upload_processing = False
        st.rerun()


def start_update_company_profile(company_code: str):
    st.session_state.company_profile_processing_code = str(company_code or "")


@st.dialog("確認更新公司資訊", dismissible=False)
def confirm_update_company_profile(company_code: str, original: dict, updates: dict):
    changed_items = []
    for field, label in COMPANY_PROFILE_CONFIRM_LABELS.items():
        old_value = str(original.get(field) or "").strip()
        new_value = str(updates.get(field) or "").strip()
        if old_value != new_value:
            changed_items.append((label, old_value, new_value))

    if not changed_items:
        st.info("目前沒有偵測到變更。")
        if st.button("關閉", width="stretch"):
            st.rerun()
        return

    st.markdown(
        """
        <style>
        .company-diff-lines {
            line-height: 1.75;
            color: inherit;
            overflow-wrap: anywhere;
        }
        .company-diff-label {
            color: #9ca3af;
            font-weight: 700;
            margin-right: 0.25rem;
        }
        [data-baseweb="modal"] span.company-diff-add,
        [data-testid="stDialog"] span.company-diff-add,
        [role="dialog"][aria-modal="true"] span.company-diff-add,
        span.company-diff-add {
            color: #22c55e !important;
            background: rgba(34, 197, 94, 0.14);
            border-radius: 3px;
            padding: 0 0.12rem;
            font-weight: 800;
        }
        [data-baseweb="modal"] span.company-diff-delete,
        [data-testid="stDialog"] span.company-diff-delete,
        [role="dialog"][aria-modal="true"] span.company-diff-delete,
        span.company-diff-delete {
            color: #ef4444 !important;
            background: rgba(239, 68, 68, 0.14);
            border-radius: 3px;
            padding: 0 0.12rem;
            font-weight: 800;
            text-decoration: line-through;
            text-decoration-thickness: 2px;
        }
        .company-diff-empty {
            color: #9ca3af;
            font-style: italic;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )
    st.warning("儲存後，後續 AI 回覆、服務地區判斷與公司資訊查詢會使用新資料。")
    st.write(f"**系統台代碼：** {company_code}")
    st.markdown("**本次變更**")
    for label, old_value, new_value in changed_items:
        with st.container(border=True):
            st.write(f"**{label}**")
            st.markdown(render_inline_diff(old_value, new_value), unsafe_allow_html=True)

    is_processing = (
        bool(company_code)
        and st.session_state.company_profile_processing_code == str(company_code)
    )
    if is_processing:
        st.info("公司資訊正在更新，完成前不可重複送出或關閉此視窗。")

    confirm_cols = st.columns([1, 1])
    confirm_cols[0].button(
        "確認儲存",
        type="primary",
        width="stretch",
        disabled=is_processing,
        on_click=start_update_company_profile,
        args=(company_code,),
    )

    if confirm_cols[1].button("取消", width="stretch", disabled=is_processing):
        st.rerun()

    if is_processing:
        with st.spinner("公司資訊更新中..."):
            try:
                result = update_company_profile(company_code, updates)
                st.session_state.last_company_profile_result = result
                if result.get("status") == "success":
                    st.session_state.company_options = fetch_companies()
            finally:
                st.session_state.company_profile_processing_code = ""
        st.rerun()



def send_feedback(
    user_id: str,
    tv_cable: str,
    feedback_type: str,
    suggestion: str,
    user_message: str | None,
    ai_response: str | None,
    conversation: list[dict],
):
    backend_user_id = test_web_user_id(user_id)
    try:
        resp = backend_request(
            "POST",
            f"{API_BASE}/feedback",
            json={
                "user_id": backend_user_id,
                "tv_cable": tv_cable,
                "feedback_type": feedback_type,
                "suggestion": suggestion,
                "user_message": user_message,
                "ai_response": ai_response,
                "conversation": conversation,
            },
            timeout=30,
        )
        if resp.status_code == 200:
            return resp.json()
        return {
            "status": "error",
            "message": backend_error_message(resp),
        }
    except Exception as e:
        return {
            "status": "error",
            "message": str(e),
        }


def get_last_feedback_target():
    last_user = None
    last_assistant = None

    for message in st.session_state.chat_history:
        role = message.get("role")
        content = message.get("content", "")
        if role == "user":
            last_user = content
        elif role == "assistant":
            last_assistant = content

    return last_user, last_assistant


def format_response_time(seconds) -> str | None:
    if seconds is None:
        return None

    try:
        value = float(seconds)
    except (TypeError, ValueError):
        return None

    if value < 0:
        return None
    if value < 10:
        return f"{value:.2f} 秒"
    return f"{value:.1f} 秒"


def format_latency_task_name(task: str) -> str:
    labels = {
        "primary": "LLM 意圖/主回覆",
        "rag_summary": "LLM RAG摘要",
        "fallback": "LLM fallback",
    }
    return labels.get(str(task or "").strip(), str(task or "LLM").strip() or "LLM")


def render_latency_details(latency: dict) -> str:
    if not isinstance(latency, dict) or not latency:
        return ""

    detail_parts = []
    for key, label in [
        ("llm_total", "LLM總計"),
        ("rag", "RAG檢索"),
        ("tool_call", "工具調用"),
        ("cust_api", "CUST API"),
    ]:
        formatted = format_response_time(latency.get(key))
        if formatted:
            detail_parts.append(f"{label}：{formatted}")

    events = latency.get("llm_events")
    if isinstance(events, list):
        for index, event in enumerate(events, start=1):
            if not isinstance(event, dict):
                continue
            duration = format_response_time(event.get("duration_sec"))
            if not duration:
                continue
            task = format_latency_task_name(str(event.get("task") or f"LLM{index}"))
            provider = str(event.get("provider") or "").strip()
            model = str(event.get("model") or "").strip()
            name = " ".join(part for part in [task, provider, model] if part)
            detail_parts.append(f"{name}：{duration}")

    return "　|　".join(detail_parts)


def render_message_meta_html(message: dict) -> str:
    meta_parts = []
    detail_text = ""

    if message.get("role") == "assistant":
        response_time = format_response_time(message.get("response_time_sec"))
        if response_time:
            meta_parts.append(f"回覆時間：{response_time}")
        cust_api_time = format_response_time(message.get("cust_api_time_sec"))
        if cust_api_time:
            meta_parts.append(f"CUST API：{cust_api_time}")
        detail_text = render_latency_details(message.get("latency") or {})
    else:
        ocr_time = format_response_time(message.get("ocr_time_sec"))
        if ocr_time:
            meta_parts.append(f"圖片辨識時間：{ocr_time}")

    if not meta_parts and not detail_text:
        return ""

    parts = []
    if meta_parts:
        parts.append(f'<div class="message-meta">{html.escape("　|　".join(meta_parts))}</div>')
    if detail_text:
        parts.append(f'<div class="message-meta-detail">{html.escape(detail_text)}</div>')
    return "".join(parts)


def render_message_meta(message: dict):
    rendered = render_message_meta_html(message)
    if rendered:
        st.markdown(rendered, unsafe_allow_html=True)


def refresh_side_data():
    st.session_state.last_state = fetch_state(
        st.session_state.user_id,
        st.session_state.selected_tv_cable,
        simulated_web_custnum(),
    )


def scroll_to_chat_bottom():
    render_hidden_html(
        """
        <script>
        (() => {
            const parentWindow = window.parent;
            const parentDocument = parentWindow.document;

            const scrollTargets = () => [
                parentDocument.scrollingElement,
                parentDocument.documentElement,
                parentDocument.body,
                parentDocument.querySelector('[data-testid="stAppViewContainer"]'),
                parentDocument.querySelector('[data-testid="stMain"]')
            ].filter(Boolean);

            const scrollBottom = () => {
                parentWindow.scrollTo({ top: parentDocument.body.scrollHeight, left: 0, behavior: "instant" });
                scrollTargets().forEach((element) => {
                    element.scrollTop = element.scrollHeight;
                });
            };

            parentWindow.requestAnimationFrame(() => {
                parentWindow.requestAnimationFrame(scrollBottom);
            });
        })();
        </script>
        """,
        height=0,
        width=0,
    )


def scroll_to_image_ocr_panel():
    render_hidden_html(
        """
        <script>
        (() => {
            const parentWindow = window.parent;
            const parentDocument = parentWindow.document;

            const scrollPanel = () => {
                const marker = parentDocument.querySelector(".image-ocr-panel-marker");
                const expander = marker?.closest('[data-testid="stExpander"]');
                if (!expander) {
                    return;
                }
                const controller = parentDocument.__custAppContextualFocusController;
                if (controller?.focus) {
                    controller.focus(expander, "rerun");
                    return;
                }
                if (attempts < 12) {
                    attempts += 1;
                    parentWindow.setTimeout(scrollPanel, 25);
                }
            };

            let attempts = 0;
            parentWindow.requestAnimationFrame(() => {
                parentWindow.requestAnimationFrame(scrollPanel);
            });
        })();
        </script>
        """,
        height=0,
        width=0,
    )


def bind_contextual_expander_focus():
    render_hidden_html(
        """
        <script>
        (() => {
            const parentWindow = window.parent;
            const parentDocument = parentWindow.document;
            parentDocument.documentElement.setAttribute(
                "data-cust-context-focus-version",
                "16"
            );
            const previousController =
                parentDocument.__custAppContextualFocusController;
            try {
                previousController?.destroy?.();
            } catch (_) {
                // The previous Streamlit component iframe may already be gone.
            }
            const state = {
                sequence: 0,
                timer: null,
                frame: null,
                settleTimer: null,
                cancelled: false,
                active: false
            };

            const isAutoFocusExpander = (expander) => {
                if (!expander) {
                    return false;
                }
                const header = expander.querySelector(
                    "summary, button[aria-expanded], [role='button'][aria-expanded]"
                );
                const headerText = header?.textContent || "";
                return Boolean(
                    expander.querySelector(".image-ocr-panel-marker")
                    || expander.querySelector(".feedback-panel-marker")
                    || headerText.includes("上傳圖片辨識")
                    || headerText.includes("測試回饋")
                );
            };

            const isExpanded = (expander) => {
                if (!expander?.isConnected) {
                    return false;
                }
                const details = expander.matches("details")
                    ? expander
                    : expander.querySelector("details");
                if (details) {
                    return details.open;
                }
                const trigger = expander.querySelector(
                    "button[aria-expanded], [role='button'][aria-expanded]"
                );
                return trigger?.getAttribute("aria-expanded") === "true";
            };

            const documentScroller = () => (
                parentDocument.scrollingElement
                || parentDocument.documentElement
                || parentDocument.body
            );

            const isScrollable = (element) => {
                if (!element) {
                    return false;
                }
                const style = parentWindow.getComputedStyle(element);
                return (
                    /(auto|scroll|overlay)/.test(style.overflowY || "")
                    && element.scrollHeight > element.clientHeight + 2
                );
            };

            const findScroller = (element) => {
                let current = element?.parentElement || null;
                while (current && current !== parentDocument.body) {
                    if (
                        isScrollable(current)
                        && current.clientHeight >= Math.min(240, parentWindow.innerHeight / 3)
                    ) {
                        return current;
                    }
                    current = current.parentElement;
                }
                return documentScroller();
            };

            const isDocumentScroller = (element) => (
                element === parentDocument.scrollingElement
                || element === parentDocument.documentElement
                || element === parentDocument.body
            );

            const viewportFor = (scroller) => {
                if (isDocumentScroller(scroller)) {
                    return {
                        top: 16,
                        bottom: parentWindow.innerHeight - 16
                    };
                }
                const rect = scroller.getBoundingClientRect();
                return {
                    top: Math.max(16, rect.top + 16),
                    bottom: Math.min(parentWindow.innerHeight - 16, rect.bottom - 16)
                };
            };

            const targetTopFor = (panelRect, viewport) => {
                const viewportHeight = Math.max(0, viewport.bottom - viewport.top);
                if (panelRect.height >= viewportHeight - 32) {
                    return viewport.top;
                }
                return viewport.top + Math.max(
                    0,
                    (viewportHeight - panelRect.height) / 2
                );
            };

            const releaseScrollRoom = (expander) => {
                if (!isAutoFocusExpander(expander)) {
                    return;
                }
                const safeArea = parentDocument.querySelector(".page-bottom-safe-area");
                safeArea?.style.removeProperty("height");
            };

            const reserveScrollRoom = (expander) => {
                if (!isAutoFocusExpander(expander)) {
                    return;
                }
                const safeArea = parentDocument.querySelector(".page-bottom-safe-area");
                if (!safeArea) {
                    return;
                }

                // Always measure from the CSS baseline. Reusing the previous inline
                // height makes repeated click/toggle/mutation events grow the page.
                safeArea.style.removeProperty("height");
                const baseHeight = Math.max(
                    64,
                    safeArea.getBoundingClientRect().height
                );

                const scroller = findScroller(expander);
                const viewport = viewportFor(scroller);
                const panelRect = expander.getBoundingClientRect();
                const targetTop = targetTopFor(panelRect, viewport);
                const requiredDelta = Math.max(0, panelRect.top - targetTop);
                let currentScroll = 0;
                let maxScroll = 0;

                if (isDocumentScroller(scroller)) {
                    currentScroll = (
                        parentWindow.scrollY
                        || parentDocument.documentElement.scrollTop
                        || parentDocument.body.scrollTop
                        || 0
                    );
                    maxScroll = Math.max(
                        0,
                        documentScroller().scrollHeight - parentWindow.innerHeight
                    );
                } else {
                    currentScroll = scroller.scrollTop;
                    maxScroll = Math.max(
                        0,
                        scroller.scrollHeight - scroller.clientHeight
                    );
                }

                const shortage = requiredDelta - Math.max(0, maxScroll - currentScroll);
                if (shortage <= 2) {
                    return;
                }
                safeArea.style.height = `${Math.ceil(baseHeight + shortage + 24)}px`;
            };

            const cancelPending = () => {
                if (
                    !state.active
                    && !state.timer
                    && !state.frame
                    && !state.settleTimer
                ) {
                    return;
                }
                state.cancelled = true;
                state.sequence += 1;
                if (state.timer) {
                    parentWindow.clearTimeout(state.timer);
                    state.timer = null;
                }
                if (state.frame) {
                    parentWindow.cancelAnimationFrame(state.frame);
                    state.frame = null;
                }
                if (state.settleTimer) {
                    parentWindow.clearTimeout(state.settleTimer);
                    state.settleTimer = null;
                }
                state.active = false;
            };

            const alignOnce = (expander, behavior = "smooth") => {
                if (!isAutoFocusExpander(expander) || !isExpanded(expander)) {
                    return false;
                }

                const scroller = findScroller(expander);
                const viewport = viewportFor(scroller);
                const panelRect = expander.getBoundingClientRect();
                const targetTop = targetTopFor(panelRect, viewport);
                const delta = panelRect.top - targetTop;
                if (Math.abs(delta) < 2) {
                    return true;
                }

                if (isDocumentScroller(scroller)) {
                    const current = (
                        parentWindow.scrollY
                        || parentDocument.documentElement.scrollTop
                        || parentDocument.body.scrollTop
                        || 0
                    );
                    const maxScroll = Math.max(
                        0,
                        documentScroller().scrollHeight - parentWindow.innerHeight
                    );
                    const target = Math.min(maxScroll, Math.max(0, current + delta));
                    parentWindow.scrollTo({
                        top: target,
                        left: 0,
                        behavior
                    });
                    return true;
                }

                const maxScroll = Math.max(0, scroller.scrollHeight - scroller.clientHeight);
                const target = Math.min(
                    maxScroll,
                    Math.max(0, scroller.scrollTop + delta)
                );
                if (typeof scroller.scrollTo === "function") {
                    scroller.scrollTo({
                        top: target,
                        left: scroller.scrollLeft,
                        behavior
                    });
                } else {
                    scroller.scrollTop = target;
                }
                return true;
            };

            const scheduleFocus = (expander) => {
                if (!isAutoFocusExpander(expander)) {
                    return;
                }
                cancelPending();
                state.cancelled = false;
                state.active = true;
                const sequence = ++state.sequence;
                let previousHeight = -1;
                let stableFrames = 0;
                let attempts = 0;

                const waitForStableLayout = () => {
                    if (
                        state.cancelled
                        || sequence !== state.sequence
                        || !expander.isConnected
                    ) {
                        state.active = false;
                        return;
                    }
                    if (!isExpanded(expander)) {
                        state.active = false;
                        return;
                    }

                    const height = Math.round(expander.getBoundingClientRect().height);
                    stableFrames = Math.abs(height - previousHeight) <= 1
                        ? stableFrames + 1
                        : 0;
                    previousHeight = height;
                    attempts += 1;

                    if (stableFrames >= 3 || attempts >= 18) {
                        state.frame = null;
                        // The expanded panel must reach its final height before
                        // calculating scroll room. Two frames let the new safe-area
                        // height participate in layout before the single scroll.
                        reserveScrollRoom(expander);
                        state.frame = parentWindow.requestAnimationFrame(() => {
                            state.frame = parentWindow.requestAnimationFrame(() => {
                                state.frame = null;
                                // Let the browser finish its native details/summary
                                // scroll anchoring before applying our own alignment.
                                // Without this short settle window, a panel below a
                                // long chat can ignore the first smooth scroll.
                                state.settleTimer = parentWindow.setTimeout(() => {
                                    state.settleTimer = null;
                                    state.active = false;
                                    if (
                                        !state.cancelled
                                        && sequence === state.sequence
                                        && isExpanded(expander)
                                    ) {
                                        alignOnce(expander, "smooth");
                                    }
                                }, 140);
                            });
                        });
                        return;
                    }
                    state.frame = parentWindow.requestAnimationFrame(waitForStableLayout);
                };

                state.timer = parentWindow.setTimeout(() => {
                    state.timer = null;
                    state.frame = parentWindow.requestAnimationFrame(waitForStableLayout);
                }, 80);
            };

            const expanderFromTarget = (target) => (
                target instanceof parentWindow.Element
                    ? target.closest('[data-testid="stExpander"]')
                    : null
            );

            const isHeaderInteraction = (expander, target) => {
                const header = expander?.querySelector(
                    "summary, button[aria-expanded], [role='button'][aria-expanded]"
                );
                return Boolean(header && (header === target || header.contains(target)));
            };

            const handleExpanderClick = (event) => {
                const expander = expanderFromTarget(event.target);
                if (
                    !isAutoFocusExpander(expander)
                    || !isHeaderInteraction(expander, event.target)
                ) {
                    return;
                }
                parentWindow.setTimeout(() => {
                    if (isExpanded(expander)) {
                        scheduleFocus(expander);
                    } else {
                        releaseScrollRoom(expander);
                    }
                }, 0);
            };

            const handleExpanderToggle = (event) => {
                const details = event.target;
                if (details?.tagName !== "DETAILS") {
                    return;
                }
                const expander = details.closest('[data-testid="stExpander"]');
                if (details.open && isAutoFocusExpander(expander)) {
                    scheduleFocus(expander);
                } else if (!details.open) {
                    releaseScrollRoom(expander);
                }
            };

            const handleUserKeydown = (event) => {
                if (
                    ["ArrowUp", "ArrowDown", "PageUp", "PageDown", "Home", "End", " "]
                        .includes(event.key)
                ) {
                    cancelPending();
                }
            };

            parentDocument.addEventListener("click", handleExpanderClick, true);
            parentDocument.addEventListener("toggle", handleExpanderToggle, true);

            ["wheel", "touchmove"].forEach((eventName) => {
                parentDocument.addEventListener(eventName, cancelPending, {
                    capture: true,
                    passive: true
                });
            });
            parentDocument.addEventListener("keydown", handleUserKeydown, true);

            parentDocument.__custAppContextualFocusController = {
                focus: scheduleFocus,
                cancel: cancelPending,
                destroy: () => {
                    cancelPending();
                    parentDocument.removeEventListener(
                        "click",
                        handleExpanderClick,
                        true
                    );
                    parentDocument.removeEventListener(
                        "toggle",
                        handleExpanderToggle,
                        true
                    );
                    ["wheel", "touchmove"].forEach((eventName) => {
                        parentDocument.removeEventListener(
                            eventName,
                            cancelPending,
                            true
                        );
                    });
                    parentDocument.removeEventListener(
                        "keydown",
                        handleUserKeydown,
                        true
                    );
                }
            };
            parentDocument.documentElement.setAttribute(
                "data-cust-context-focus-ready",
                "true"
            );
        })();
        </script>
        """,
        height=0,
        width=0,
    )


def focus_chat_input():
    render_hidden_html(
        """
        <script>
        (() => {
            const parentWindow = window.parent;
            const parentDocument = parentWindow.document;

            const findInput = () => {
                const directMatch = parentDocument.querySelector('input[aria-label="客服訊息"]');
                if (directMatch) {
                    return directMatch;
                }
                return Array.from(parentDocument.querySelectorAll('input')).find((element) => {
                    return (element.placeholder || "").includes("請輸入您的問題");
                });
            };

            const focusInput = () => {
                const input = findInput();
                if (!input || input.disabled) {
                    return;
                }
                input.focus({ preventScroll: true });
            };

            parentWindow.requestAnimationFrame(() => {
                parentWindow.requestAnimationFrame(focusInput);
            });
        })();
        </script>
        """,
        height=0,
        width=0,
    )


def sync_chat_input_draft(clear: bool = False):
    storage_key = f"custAppChatDraft:{st.session_state.user_id}"
    clear_js = "true" if clear else "false"
    render_hidden_html(
        f"""
        <script>
        (() => {{
            const parentWindow = window.parent;
            const parentDocument = parentWindow.document;
            const storageKey = {json.dumps(storage_key)};
            const shouldClear = {clear_js};

            const findInput = () => {{
                const directMatch = parentDocument.querySelector('input[aria-label="客服訊息"]');
                if (directMatch) {{
                    return directMatch;
                }}
                return Array.from(parentDocument.querySelectorAll('input')).find((element) => {{
                    return (element.placeholder || "").includes("請輸入您的問題");
                }});
            }};

            const writeInputValue = (input, value) => {{
                const setter = Object.getOwnPropertyDescriptor(
                    parentWindow.HTMLInputElement.prototype,
                    "value"
                ).set;
                setter.call(input, value);
                input.dispatchEvent(new Event("input", {{ bubbles: true }}));
                input.dispatchEvent(new Event("change", {{ bubbles: true }}));
            }};

            const bindDraft = () => {{
                const input = findInput();
                if (!input) {{
                    return;
                }}

                if (shouldClear) {{
                    parentWindow.sessionStorage.removeItem(storageKey);
                    if (input.value) {{
                        writeInputValue(input, "");
                    }}
                    return;
                }}

                const draft = parentWindow.sessionStorage.getItem(storageKey) || "";
                if (draft && !input.value) {{
                    writeInputValue(input, draft);
                }}

                if (input.dataset.chatDraftBound !== "1") {{
                    input.dataset.chatDraftBound = "1";
                    input.addEventListener("input", () => {{
                        parentWindow.sessionStorage.setItem(storageKey, input.value || "");
                    }});
                    input.addEventListener("keydown", (event) => {{
                        if (event.key === "Enter" && !event.isComposing && input.value.trim()) {{
                            parentWindow.sessionStorage.removeItem(storageKey);
                        }}
                    }});
                }}

                const buttons = Array.from(parentDocument.querySelectorAll('button'));
                buttons.forEach((button) => {{
                    if (button.textContent.trim() !== "送出" || button.dataset.chatDraftSubmitBound === "1") {{
                        return;
                    }}
                    button.dataset.chatDraftSubmitBound = "1";
                    button.addEventListener("click", () => {{
                        if (!button.disabled && input.value.trim()) {{
                            parentWindow.sessionStorage.removeItem(storageKey);
                        }}
                    }});
                }});
            }};

            bindDraft();
            parentWindow.requestAnimationFrame(bindDraft);
            [100, 300, 700].forEach((delay) => parentWindow.setTimeout(bindDraft, delay));
            let lastSeenValue = null;
            const intervalId = parentWindow.setInterval(() => {{
                const input = findInput();
                if (!input) {{
                    return;
                }}

                if (shouldClear) {{
                    parentWindow.sessionStorage.removeItem(storageKey);
                    if (input.value) {{
                        writeInputValue(input, "");
                    }}
                    parentWindow.clearInterval(intervalId);
                    return;
                }}

                const draft = parentWindow.sessionStorage.getItem(storageKey) || "";
                if (draft && !input.value) {{
                    writeInputValue(input, draft);
                    lastSeenValue = draft;
                    return;
                }}

                if (input.value !== lastSeenValue) {{
                    lastSeenValue = input.value;
                    parentWindow.sessionStorage.setItem(storageKey, input.value || "");
                }}
            }}, 250);
            parentWindow.setTimeout(() => parentWindow.clearInterval(intervalId), 180000);
        }})();
        </script>
        """,
        height=0,
        width=0,
    )


def render_pending_kb_download_bridge() -> None:
    pending_download = st.session_state.get("pending_kb_download")
    if not isinstance(pending_download, dict):
        return

    url = str(pending_download.get("url") or "").strip()
    file_name = str(pending_download.get("file_name") or "knowledge-file").strip() or "knowledge-file"
    if not url:
        st.session_state.pending_kb_download = None
        return

    st.session_state.pending_kb_download = None
    render_hidden_html(
        f"""
        <script>
        (() => {{
            const parentWindow = window.parent;
            const parentDocument = parentWindow.document;
            const link = parentDocument.createElement("a");
            link.href = {json.dumps(url)};
            link.target = "_blank";
            link.rel = "noopener noreferrer";
            link.setAttribute("aria-label", {json.dumps(f"下載 {file_name}")});
            link.style.display = "none";
            parentDocument.body.appendChild(link);
            link.click();
            window.setTimeout(() => link.remove(), 1000);
            const restoreScroll = () => {{
                if (typeof parentWindow.__custAppRestoreKbScrollPosition === "function") {{
                    parentWindow.__custAppRestoreKbScrollPosition();
                }}
            }};
            parentWindow.requestAnimationFrame(() => {{
                parentWindow.requestAnimationFrame(restoreScroll);
            }});
        }})();
        </script>
        """,
        height=0,
        width=0,
    )


def render_kb_scroll_restore_bridge_once() -> None:
    render_hidden_html(
        """
        <script>
        (() => {
            const parentWindow = window.parent;
            const restoreScroll = () => {
                if (typeof parentWindow.__custAppRestoreKbScrollPosition === "function") {
                    parentWindow.__custAppRestoreKbScrollPosition();
                }
            };
            parentWindow.requestAnimationFrame(() => {
                parentWindow.requestAnimationFrame(restoreScroll);
            });
        })();
        </script>
        """,
        height=0,
        width=0,
    )


def render_pending_kb_scroll_restore_bridge() -> None:
    if not st.session_state.get("pending_kb_scroll_restore"):
        return

    st.session_state.pending_kb_scroll_restore = False
    render_kb_scroll_restore_bridge_once()


def clear_local_conversation():
    st.session_state.chat_history = []
    st.session_state.last_state = {}
    st.session_state.pending_user_message = None
    st.session_state.pending_receipt_image_evidence_token = None
    st.session_state.is_generating = False
    st.session_state.scroll_to_chat_bottom = False
    st.session_state.focus_chat_input = False
    st.session_state.chat_prompt_widget_version += 1
    st.session_state.clear_chat_input_draft = True
    st.session_state.last_feedback_result = None


def reset_local_conversation():
    st.session_state.user_id = str(uuid.uuid4())
    clear_local_conversation()


def unauthenticated_developer_account() -> dict:
    return {
        "username": "local-dev",
        "display_name": "Local Dev",
        "role": ROLE_DEVELOPER,
        "role_label": role_label(ROLE_DEVELOPER),
        "is_active": True,
    }


def current_web_account() -> dict | None:
    if not WEB_AUTH_ENABLED:
        return unauthenticated_developer_account()
    if WEB_ACCOUNT_INIT_ERROR:
        return None

    token = str(st.session_state.get("web_auth_token") or "")
    if not token:
        token = get_query_param_value(WEB_AUTH_QUERY_PARAM)
        if token:
            st.session_state.web_auth_token = token
    if not token:
        return None

    account = WEB_ACCOUNT_SERVICE.validate_session_token(token)
    if not account:
        st.session_state.web_auth_token = ""
        st.session_state.web_auth_account = None
        clear_persisted_web_auth_token()
        return None

    st.session_state.web_auth_account = account
    return account


def web_has_permission(permission: str) -> bool:
    return has_permission(st.session_state.get("web_auth_account"), permission)


def bind_login_autofill_metadata():
    render_hidden_html(
        """
        <script>
        (() => {
          const parentWindow = window.parent;
          const parentDocument = parentWindow.document;
          const storageKey = "custAppLastLoginUsername";

          const setInputValue = (input, value) => {
            const setter = Object.getOwnPropertyDescriptor(
              parentWindow.HTMLInputElement.prototype,
              "value"
            )?.set;
            if (setter) {
              setter.call(input, value);
            } else {
              input.value = value;
            }
            input.dispatchEvent(new Event("input", { bubbles: true }));
            input.dispatchEvent(new Event("change", { bubbles: true }));
          };

          const bindLoginFields = () => {
            const username = parentDocument.querySelector(
              'input[aria-label="帳號"][autocomplete="username"]'
            );
            const password = parentDocument.querySelector(
              'input[aria-label="密碼"][autocomplete="current-password"]'
            );
            if (!username || !password) return false;

            username.setAttribute("name", "username");
            username.setAttribute("autocapitalize", "none");
            username.setAttribute("spellcheck", "false");
            username.setAttribute("data-cust-app-login-field", "username");
            password.setAttribute("name", "password");
            password.setAttribute("data-cust-app-login-field", "password");

            const loginContainer = username.closest('[data-testid="stForm"]');
            if (loginContainer) {
              loginContainer.setAttribute("role", "form");
              loginContainer.setAttribute("aria-label", "智慧客服後台登入");
              loginContainer.setAttribute("data-cust-app-login-form", "true");
            }

            if (!username.value) {
              try {
                const savedUsername = parentWindow.localStorage.getItem(storageKey);
                if (savedUsername) setInputValue(username, savedUsername);
              } catch (_) {
                // Browsers can disable local storage in strict privacy modes.
              }
            }

            const rememberUsername = () => {
              const value = username.value.trim();
              if (!value) return;
              try {
                parentWindow.localStorage.setItem(storageKey, value);
              } catch (_) {
                // Keep login usable even when storage is unavailable.
              }
            };

            if (username.dataset.custAppRememberBound !== "true") {
              username.dataset.custAppRememberBound = "true";
              username.addEventListener("change", rememberUsername);
              username.addEventListener("blur", rememberUsername);
            }

            const loginButton = loginContainer
              ? Array.from(loginContainer.querySelectorAll("button")).find(
                  (button) => button.textContent.trim() === "登入"
                )
              : null;
            if (loginButton && loginButton.dataset.custAppRememberBound !== "true") {
              loginButton.dataset.custAppRememberBound = "true";
              loginButton.addEventListener("click", rememberUsername, true);
            }
            return true;
          };

          let attempts = 0;
          const bindWhenReady = () => {
            if (bindLoginFields() || attempts >= 30) return;
            attempts += 1;
            parentWindow.setTimeout(bindWhenReady, 100);
          };
          bindWhenReady();
        })();
        </script>
        """,
        height=0,
        width=0,
    )


def render_login_page():
    st.markdown('<div class="chat-title">智慧客服後台登入</div>', unsafe_allow_html=True)
    st.caption("請使用後台帳號登入後再進行客服測試或資料維護。")

    if WEB_ACCOUNT_INIT_ERROR:
        st.error(f"後台帳號系統初始化失敗：{WEB_ACCOUNT_INIT_ERROR}")
        st.stop()

    if WEB_ACCOUNT_SERVICE.account_count() == 0:
        st.warning(
            "目前沒有任何後台帳號。請先在環境檔設定 "
            "`WEB_AUTH_BOOTSTRAP_USERNAME` 與 `WEB_AUTH_BOOTSTRAP_PASSWORD`，"
            "再重新啟動 Streamlit。"
        )
        st.stop()

    with st.form("web_login_form"):
        username = st.text_input("帳號", value="", autocomplete="username")
        password = st.text_input("密碼", value="", type="password", autocomplete="current-password")
        submitted = st.form_submit_button("登入", type="primary", width="stretch")

    bind_login_autofill_metadata()

    if submitted:
        account = WEB_ACCOUNT_SERVICE.authenticate(username, password)
        if not account:
            st.error("帳號或密碼不正確，或此帳號已停用。")
            return

        st.session_state.web_auth_token = WEB_ACCOUNT_SERVICE.create_session_token(account)
        st.session_state.web_auth_account = account
        remember_web_auth_token(st.session_state.web_auth_token)
        st.rerun()

    st.stop()


def require_web_account() -> dict:
    account = current_web_account()
    if account:
        st.session_state.web_auth_account = account
        return account
    render_login_page()
    st.stop()


def clear_web_login():
    st.session_state.web_auth_token = ""
    st.session_state.web_auth_account = None
    clear_persisted_web_auth_token()
    st.rerun()


def page_labels_for_account(account: dict) -> dict[str, str]:
    labels = {"chat": "客服對話"}
    if has_permission(account, PERMISSION_FEEDBACK):
        labels["feedback_tracker"] = "回饋追蹤"
    if has_permission(account, PERMISSION_COMPANY_PROFILES):
        labels["company_profiles"] = "公司資訊維護"
    if has_permission(account, PERMISSION_KNOWLEDGE_BASE):
        labels["knowledge_base"] = "知識庫維護"
    if WEB_AUTH_ENABLED and has_permission(account, PERMISSION_ACCOUNT_MANAGEMENT):
        labels["account_management"] = "帳號管理"
    return labels


def render_account_management_page(current_account: dict):
    st.markdown("### 👥 帳號管理")
    st.caption(
        "只有系統管理者（研發）可以新增帳號、調整角色、設定主管可修改的知識庫、"
        "設定通用知識庫適用範圍、停用帳號或重設密碼。"
        "主管可檢視全部知識庫，但只能修改這裡授權的系統台。"
    )

    account_admin_result = st.session_state.pop("last_account_admin_result", None)
    if account_admin_result:
        result_status = account_admin_result.get("status")
        if result_status == "success":
            result_message = account_admin_result.get("message", "帳號已更新。")
            st.toast(result_message, icon="✅")
            st.success(result_message)
        else:
            result_message = account_admin_result.get("message", "帳號操作失敗。")
            st.toast(result_message, icon="⚠️")
            st.error(result_message)

    accounts = WEB_ACCOUNT_SERVICE.list_accounts()
    all_kb_scope_options = assignable_kb_base_options(
        build_kb_base_options(
            st.session_state.get("company_options") or fetch_companies()
        )
    )
    common_scopes = WEB_ACCOUNT_SERVICE.get_common_knowledge_base_scopes()
    common_scope_member_options = [
        value
        for value in all_kb_scope_options
        if value not in REGIONAL_COMMON_KNOWLEDGE_BASES
    ]
    for members in common_scopes.values():
        for member in members:
            if member not in common_scope_member_options:
                common_scope_member_options.append(member)
    common_scope_member_options = sort_kb_base_names(common_scope_member_options)

    with st.expander("通用知識庫適用範圍", expanded=False):
        st.caption(
            "設定各通用知識庫會提供給哪些系統台檢索使用。"
            "這不會改變主管權限；主管是否能新增、重建或刪除，仍由下方帳號授權控制。"
        )
        with st.form("common_knowledge_base_scope_form"):
            scope_columns = st.columns(2)
            edited_common_scopes: dict[str, list[str]] = {}
            for column, common_base in zip(
                scope_columns,
                REGIONAL_COMMON_KNOWLEDGE_BASES,
            ):
                with column:
                    edited_common_scopes[common_base] = st.multiselect(
                        f"{display_base_name(common_base)}適用系統台",
                        options=common_scope_member_options,
                        default=[
                            member
                            for member in common_scopes.get(common_base, [])
                            if member in common_scope_member_options
                        ],
                        format_func=display_base_name,
                        key=f"common_scope_members_{common_base}",
                        placeholder="請選擇要套用此通用知識庫的系統台",
                    )
            submitted_common_scopes = st.form_submit_button(
                "儲存通用知識庫適用範圍",
                type="primary",
                width="stretch",
            )

        if submitted_common_scopes:
            try:
                WEB_ACCOUNT_SERVICE.update_common_knowledge_base_scopes(
                    edited_common_scopes,
                    actor_username=current_account.get("username", ""),
                )
                st.session_state.last_account_admin_result = {
                    "status": "success",
                    "message": "已更新通用知識庫適用範圍，後續 RAG 查詢會立即套用。",
                }
            except WebAccountError as exc:
                st.session_state.last_account_admin_result = {
                    "status": "error",
                    "message": str(exc),
                }
            st.rerun()

    rows = [
        {
            "帳號": item["username"],
            "顯示名稱": item["display_name"],
            "角色": item["role_label"],
            "可修改知識庫": format_managed_kb_bases(item),
            "狀態": "啟用" if item["is_active"] else "停用",
            "最後登入": item.get("last_login_at") or "-",
            "更新時間": item.get("updated_at") or "-",
        }
        for item in accounts
    ]
    table_headers = ["帳號", "顯示名稱", "角色", "可修改知識庫", "狀態", "最後登入", "更新時間"]
    table_head = "".join(f"<th>{html.escape(header)}</th>" for header in table_headers)
    table_body = "".join(
        "<tr>"
        + "".join(f"<td>{html.escape(str(row.get(header, '') or '-'))}</td>" for header in table_headers)
        + "</tr>"
        for row in rows
    )
    st.markdown(
        f"""
        <div class="account-table-wrap">
            <table class="account-table">
                <thead><tr>{table_head}</tr></thead>
                <tbody>{table_body}</tbody>
            </table>
        </div>
        """,
        unsafe_allow_html=True,
    )

    create_col, edit_col = st.columns(2)

    with create_col:
        st.markdown("**新增帳號**")
        with st.form("create_web_account_form", clear_on_submit=True):
            new_username = st.text_input("帳號", key="new_account_username")
            new_display_name = st.text_input("顯示名稱", key="new_account_display_name")
            new_role = st.selectbox(
                "角色",
                options=list(VALID_ROLES),
                format_func=lambda value: ROLE_LABELS.get(value, value),
                key="new_account_role",
            )
            new_managed_kb_bases = st.multiselect(
                "可修改知識庫（主管適用）",
                options=all_kb_scope_options,
                format_func=display_base_name,
                key="new_account_managed_kb_bases",
                placeholder="請選擇主管可修改的一個或多個系統台",
                help=(
                    "可複選；主管可檢視全部知識庫，但只可修改授權系統台。"
                    "通用-中區與通用-嘉南區也可授權給指定主管；"
                    "一般職員無知識庫維護權限。"
                ),
            )
            new_password = st.text_input("初始密碼", type="password", key="new_account_password")
            submitted_create = st.form_submit_button("新增帳號", type="primary", width="stretch")

        if submitted_create:
            try:
                WEB_ACCOUNT_SERVICE.create_account(
                    username=new_username,
                    password=new_password,
                    role=new_role,
                    display_name=new_display_name,
                    managed_knowledge_bases=new_managed_kb_bases,
                    actor_username=current_account.get("username", ""),
                )
                st.session_state.last_account_admin_result = {
                    "status": "success",
                    "message": f"已新增帳號：{new_username.strip().lower()}",
                }
            except WebAccountError as exc:
                st.session_state.last_account_admin_result = {
                    "status": "error",
                    "message": str(exc),
                }
            st.rerun()

    with edit_col:
        st.markdown("**修改帳號**")
        account_options = [item["username"] for item in accounts]
        if not account_options:
            st.info("目前沒有可修改的帳號。")
            return

        selected_username = st.selectbox("選擇帳號", options=account_options, key="edit_account_username")
        selected_account = next(
            (item for item in accounts if item["username"] == selected_username),
            accounts[0],
        )
        edit_widget_suffix = re.sub(r"[^a-zA-Z0-9_-]+", "_", selected_username)
        with st.form("edit_web_account_form"):
            edited_display_name = st.text_input(
                "顯示名稱",
                value=selected_account.get("display_name") or selected_username,
                key=f"edit_account_display_name_{edit_widget_suffix}",
            )
            edited_role = st.selectbox(
                "角色",
                options=list(VALID_ROLES),
                index=list(VALID_ROLES).index(selected_account.get("role")),
                format_func=lambda value: ROLE_LABELS.get(value, value),
                key=f"edit_account_role_{edit_widget_suffix}",
            )
            edited_active = st.checkbox(
                "啟用帳號",
                value=bool(selected_account.get("is_active")),
                key=f"edit_account_active_{edit_widget_suffix}",
            )
            selected_managed_bases = [
                value for value in selected_account.get("managed_knowledge_bases", [])
                if value in all_kb_scope_options
            ]
            edited_managed_kb_bases = st.multiselect(
                "可修改知識庫（主管適用）",
                options=all_kb_scope_options,
                default=selected_managed_bases,
                format_func=display_base_name,
                key=f"edit_account_managed_kb_bases_{edit_widget_suffix}",
                placeholder="請選擇這位主管可修改的系統台",
                help=(
                    "主管仍可檢視未授權的其他區知識庫；此處只控制新增、重建與刪除。"
                    "通用-中區與通用-嘉南區也可分別授權給指定主管。"
                ),
            )
            edited_password = st.text_input(
                "重設密碼（留空代表不變更）",
                type="password",
                key=f"edit_account_password_{edit_widget_suffix}",
            )
            submitted_edit = st.form_submit_button("儲存帳號變更", type="primary", width="stretch")

        if submitted_edit:
            try:
                WEB_ACCOUNT_SERVICE.update_account(
                    selected_username,
                    display_name=edited_display_name,
                    role=edited_role,
                    is_active=edited_active,
                    password=edited_password or None,
                    managed_knowledge_bases=edited_managed_kb_bases,
                    actor_username=current_account.get("username", ""),
                )
                if selected_username == current_account.get("username"):
                    refreshed_account = WEB_ACCOUNT_SERVICE.get_account_by_username(selected_username)
                    if refreshed_account:
                        st.session_state.web_auth_account = refreshed_account
                        st.session_state.web_auth_token = WEB_ACCOUNT_SERVICE.create_session_token(refreshed_account)
                st.session_state.last_account_admin_result = {
                    "status": "success",
                    "message": f"已更新帳號「{selected_username}」的權限與帳號設定。",
                }
            except WebAccountError as exc:
                st.session_state.last_account_admin_result = {
                    "status": "error",
                    "message": str(exc),
                }
            st.rerun()


def stream_text(text: str, placeholder, delay: float = 0.008, role: str = "assistant"):
    rendered = ""
    for ch in text:
        rendered += ch
        render_chat_message({"role": role, "content": rendered}, placeholder=placeholder)
        time.sleep(delay)
    return rendered


render_ui_theme_storage_bridge()
render_web_auth_storage_bridge()
render_kb_download_scroll_memory_bridge(
    skip_initial_record=(
        isinstance(st.session_state.get("pending_kb_download"), dict)
        or bool(st.session_state.get("pending_kb_scroll_restore"))
    )
)
render_internal_handoff_click_bridge()

CURRENT_WEB_ACCOUNT = require_web_account()
AVAILABLE_PAGE_LABELS = page_labels_for_account(CURRENT_WEB_ACCOUNT)
if st.session_state.current_page not in AVAILABLE_PAGE_LABELS:
    st.session_state.current_page = "chat"

if not st.session_state.last_state:
    refresh_side_data()


def preserve_markdown_linebreaks(text: str, linkify_links: bool = True) -> str:
    if text is None:
        return ""
    rendered = html.unescape(str(text))
    rendered = re.sub(r"</?code(?:\s[^>]*)?>", "", rendered, flags=re.IGNORECASE)
    rendered = re.sub(r"[`｀ˋ`‵]", "", rendered)
    rendered = rendered.replace("$", r"\$")
    if not linkify_links:
        # Chat bubbles are plain source text; a date range such as 6/05~9/30
        # must not turn all intervening content into Markdown strikethrough.
        rendered = rendered.replace("~", r"\~")
    if linkify_links:
        rendered = re.sub(
            r"[［【]([^］】]+🔗)[］】](https?://[^\s，。；、]+)",
            r"[\1](\2)",
            rendered,
        )
        known_link_targets = {
            "LINE TV客服中心🔗": LINE_TV_HELP_URL,
            "LINE TV官方客服中心🔗": LINE_TV_HELP_URL,
            "維修申告🔗": html.unescape(REPAIR_REPORT_URL),
            "裝機申告🔗": html.unescape(INSTALL_REPORT_URL),
        }
        for label, url in known_link_targets.items():
            rendered = rendered.replace(f"［{label}］", f"[{label}]({url})")
            rendered = rendered.replace(f"【{label}】", f"[{label}]({url})")
    return rendered.replace("\n", "  \n")


TRACKER_URL_BODY = r"https?://[A-Za-z0-9\-._~:/?#\[\]@!$&'()*+=%]+"
TRACKER_PLAIN_URL_PATTERN = re.compile(rf"(?<!\]\(){TRACKER_URL_BODY}")
TRACKER_BRACKETED_LINK_PATTERN = re.compile(
    rf"[［【]\s*(?P<label>[^］】\n]{{1,60}}?🔗)\s*[］】]\s*(?P<url>{TRACKER_URL_BODY})"
)
TRACKER_NAMED_LINK_PATTERN = re.compile(
    rf"(?P<label>台基科官網|維修申告(?:🔗)?|裝機申告(?:🔗)?|LINE TV(?:官方)?客服中心(?:🔗)?)\s*(?P<url>{TRACKER_URL_BODY})"
)


def tracker_display_markdown(text: str, auto_sentence_breaks: bool = False) -> str:
    # API responses already contain HTML anchors. The feedback tracker uses a
    # Markdown renderer, so normalise anchors before scanning plain URLs; this
    # prevents a URL inside href="..." from being linkified a second time.
    raw = html_anchors_to_markdown(html.unescape(str(text or "")))

    def link_separator(end: int) -> str:
        next_character = raw[end:end + 1]
        return (
            " "
            if next_character
            and not next_character.isspace()
            and next_character not in "，。；、,.;:：)]】"
            else ""
        )

    def format_named_url(match: re.Match) -> str:
        label = match.group("label").strip()
        url = match.group("url")
        return f"[{label}]({url}){link_separator(match.end())}"

    raw = TRACKER_BRACKETED_LINK_PATTERN.sub(format_named_url, raw)
    raw = TRACKER_NAMED_LINK_PATTERN.sub(format_named_url, raw)

    def format_url(match: re.Match) -> str:
        url = match.group(0)
        return f"[開啟連結]({url}){link_separator(match.end())}"

    raw = TRACKER_PLAIN_URL_PATTERN.sub(format_url, raw)
    if auto_sentence_breaks:
        raw = auto_break_chat_sentences(raw)
    return preserve_markdown_linebreaks(raw, linkify_links=False)


def linkify_plain_urls(rendered: str) -> str:
    url_pattern = re.compile(r"(?<![\"'=])\bhttps?://[^\s<\"']+")

    def url_repl(match):
        raw_url = match.group(0)
        trailing = ""
        while raw_url and raw_url[-1] in ".,，。；;、)）]】":
            trailing = raw_url[-1] + trailing
            raw_url = raw_url[:-1]
        if not raw_url:
            return match.group(0)

        safe_url = raw_url
        safe_label = raw_url
        return (
            f'<a href="{safe_url}" target="_blank" rel="noopener noreferrer">'
            f'{safe_label}</a>{trailing}'
        )

    return url_pattern.sub(url_repl, rendered)


def auto_break_chat_sentences(text: str) -> str:
    if not text:
        return ""

    normalized = str(text)
    lines = normalized.split("\n")
    broken_lines = []
    for line in lines:
        if len(line.strip()) < 28:
            broken_lines.append(line)
            continue
        broken_lines.append(re.sub(r"([。！？；])(?=\S)", r"\1\n", line))
    return "\n".join(broken_lines)


def render_chat_text_html(text: str, auto_sentence_breaks: bool = False) -> str:
    internal_handoff_marker = "CUST_APP_INTERNAL_HUMAN_HANDOFF_LINK_MARKER"
    raw = html.unescape(str(text or ""))
    raw = re.sub(r"<br\s*/?>", "\n", raw, flags=re.IGNORECASE)
    raw = re.sub(
        r"<a\b[^>]*data-internal-human-handoff=[\"']1[\"'][^>]*>.*?</a>",
        internal_handoff_marker,
        raw,
        flags=re.IGNORECASE | re.DOTALL,
    )
    if auto_sentence_breaks:
        raw = auto_break_chat_sentences(raw)

    rendered = html.escape(raw, quote=False)
    rendered = re.sub(r"</?code(?:\s[^>]*)?>", "", rendered, flags=re.IGNORECASE)
    rendered = re.sub(r"[`｀ˋ`‵]", "", rendered)

    link_pattern = re.compile(r"[［【]([^］】]+🔗)[］】](https?://[^\s，。；、<]+)")

    def link_repl(match):
        label = html.escape(match.group(1), quote=False)
        url = html.escape(match.group(2), quote=True)
        return f'<a href="{url}" target="_blank" rel="noopener noreferrer">{label}</a>'

    rendered = link_pattern.sub(link_repl, rendered)
    known_link_targets = {
        "LINE TV客服中心🔗": LINE_TV_HELP_URL,
        "LINE TV官方客服中心🔗": LINE_TV_HELP_URL,
        "維修申告🔗": html.unescape(REPAIR_REPORT_URL),
        "裝機申告🔗": html.unescape(INSTALL_REPORT_URL),
    }
    for label, url in known_link_targets.items():
        safe_label = html.escape(label, quote=False)
        safe_url = html.escape(url, quote=True)
        anchor = f'<a href="{safe_url}" target="_blank" rel="noopener noreferrer">{safe_label}</a>'
        rendered = rendered.replace(f"［{safe_label}］", anchor)
        rendered = rendered.replace(f"【{safe_label}】", anchor)

    rendered = linkify_plain_urls(rendered)
    rendered = rendered.replace(
        internal_handoff_marker,
        '<a href="#internal-human-handoff" data-internal-human-handoff="1" role="button">'
        "轉真人文字客服</a>",
    )
    return text_linebreaks_to_html(rendered)


def render_chat_text(text: str, placeholder=None, auto_sentence_breaks: bool = False):
    rendered = render_chat_text_html(text, auto_sentence_breaks=auto_sentence_breaks)
    block = f'<div class="chat-text">{rendered}</div>'
    target = placeholder or st
    target.markdown(block, unsafe_allow_html=True)


def render_chat_message(message: dict, placeholder=None):
    role = "user" if message.get("role") == "user" else "assistant"
    if placeholder is not None:
        with placeholder.container():
            with st.chat_message(role):
                if role == "user":
                    st.markdown('<span class="chat-role-marker-user"></span>', unsafe_allow_html=True)
                render_chat_text(message.get("content") or "", auto_sentence_breaks=(role == "assistant"))
                render_message_meta(message)
        return

    with st.chat_message(role):
        if role == "user":
            st.markdown('<span class="chat-role-marker-user"></span>', unsafe_allow_html=True)
        render_chat_text(message.get("content") or "", auto_sentence_breaks=(role == "assistant"))
        render_message_meta(message)


def parse_kb_result_display(item: dict) -> dict:
    answer = str(item.get("answer") or "")
    question = item.get("question")
    company = item.get("company")

    match = re.match(
        r"^\s*question:\s*(?P<question>.*?)\s*；\s*answer:\s*(?P<answer>.*?)\s*；\s*company:\s*(?P<company>.*?)\s*$",
        answer,
        flags=re.DOTALL,
    )
    if match:
        question = match.group("question").strip() or question
        answer = match.group("answer").strip()
        company = match.group("company").strip() or company

    return {
        "question": question,
        "answer": answer,
        "company": company,
    }


def activate_image_ocr_panel():
    st.session_state.image_ocr_panel_expanded = True
    st.session_state.scroll_to_image_ocr_panel = True


def render_uploaded_image_preview(image_bytes: bytes, mime_type: str | None, filename: str):
    image_base64 = base64.b64encode(image_bytes).decode("ascii")
    safe_mime_type = html.escape(mime_type or "image/jpeg", quote=True)
    safe_filename = html.escape(filename or "uploaded image", quote=False)
    safe_alt = html.escape(filename or "uploaded image", quote=True)

    st.markdown(
        f"""
        <style>
        .ocr-image-preview {{
            margin-top: 16px;
            overflow: hidden;
            border: 1px solid var(--cust-border, rgba(148, 163, 184, 0.22));
            border-radius: 8px;
            background: var(--cust-surface, #080c12);
        }}
        .ocr-image-preview img {{
            display: block;
            width: 100%;
            max-height: min(460px, 52vh);
            object-fit: contain;
            background: var(--cust-surface-2, #080c12);
        }}
        .ocr-image-preview-caption {{
            padding: 10px 12px 12px;
            color: var(--cust-muted, rgba(226, 232, 240, 0.68));
            text-align: center;
            font-size: 0.9rem;
        }}
        </style>
        <div class="ocr-image-preview">
            <img src="data:{safe_mime_type};base64,{image_base64}" alt="{safe_alt}">
            <div class="ocr-image-preview-caption">{safe_filename}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_image_ocr_panel():
    upload_key = f"image_ocr_upload_{st.session_state.image_ocr_uploader_nonce}"
    has_selected_image = st.session_state.get(upload_key) is not None
    expanded = bool(st.session_state.image_ocr_panel_expanded or has_selected_image)
    ocr_busy = bool(st.session_state.is_image_ocr_processing)

    st.markdown('<div id="image-ocr-panel-anchor"></div>', unsafe_allow_html=True)
    with st.expander("🖼️ 上傳圖片辨識", expanded=expanded):
        st.markdown('<span class="image-ocr-panel-marker"></span>', unsafe_allow_html=True)
        st.caption("上傳圖片後會呼叫後端 `POST /api/ocr/image`，可用來測試 LINE 圖片 OCR 或帳單/截圖辨識。")

        uploaded_image = st.file_uploader(
            "選擇圖片",
            type=["png", "jpg", "jpeg", "webp"],
            accept_multiple_files=False,
            disabled=st.session_state.is_generating or ocr_busy,
            key=upload_key,
            on_change=activate_image_ocr_panel,
        )

        if uploaded_image is not None:
            st.session_state.image_ocr_panel_expanded = True
            image_bytes = uploaded_image.getvalue()
            render_uploaded_image_preview(image_bytes, uploaded_image.type, uploaded_image.name)

        st.markdown('<div id="image-ocr-action-anchor"></div>', unsafe_allow_html=True)
        if st.button(
            "分析圖片",
            width="stretch",
            disabled=uploaded_image is None or st.session_state.is_generating or ocr_busy,
            type="primary",
        ):
            st.session_state.image_ocr_panel_expanded = True
            st.session_state.scroll_to_image_ocr_panel = True
            st.session_state.is_image_ocr_processing = True
            st.session_state.pending_image_ocr = {
                "bytes": uploaded_image.getvalue(),
                "mime_type": uploaded_image.type,
                "filename": uploaded_image.name,
            }
            st.rerun()

        ocr_status_slot = st.empty()
        if ocr_busy:
            ocr_status_slot.info("圖片辨識中，您可以先輸入下一則訊息，但需等辨識完成後才能送出。")

    return ocr_status_slot


def process_pending_image_ocr(ocr_status_slot):
    pending_image = st.session_state.pending_image_ocr
    if not st.session_state.is_image_ocr_processing:
        return

    if not pending_image:
        st.session_state.is_image_ocr_processing = False
        st.session_state.image_ocr_panel_expanded = True
        st.warning("找不到待辨識圖片，請重新上傳。")
        return

    try:
        with ocr_status_slot.container():
            with st.spinner("圖片辨識中..."):
                ocr_result = analyze_image_with_ocr(
                    pending_image["bytes"],
                    pending_image.get("mime_type"),
                    None,
                    user_id=chat_backend_user_id(
                        st.session_state.user_id,
                        simulated_web_custnum(),
                    ),
                )
    except Exception as exc:
        ocr_result = {
            "status": "error",
            "message": f"圖片辨識失敗：{exc}",
        }
    finally:
        st.session_state.is_image_ocr_processing = False
        st.session_state.pending_image_ocr = None
        st.session_state.image_ocr_uploader_nonce += 1

    if ocr_result.get("status") == "success":
        ocr_text = ocr_result.get("text", "")
        ocr_time_sec = ocr_result.get("ocr_time_sec") or ocr_result.get("request_time_sec")

        if ocr_text:
            user_message = f"我上傳了一張圖片，辨識內容如下：\n{ocr_text}"
            st.session_state.chat_history.append({
                "role": "user",
                "content": user_message,
                "ocr_time_sec": ocr_time_sec,
                "ocr_request_time_sec": ocr_result.get("request_time_sec"),
            })
            st.session_state.pending_user_message = user_message
            st.session_state.pending_receipt_image_evidence_token = (
                ocr_result.get("receipt_evidence_token")
            )
            st.session_state.is_generating = True
            st.session_state.scroll_to_chat_bottom = True
            st.session_state.scroll_to_image_ocr_panel = False
            st.session_state.image_ocr_panel_expanded = False
            st.rerun()

        st.session_state.image_ocr_panel_expanded = True
        with ocr_status_slot.container():
            st.success("圖片辨識完成，但沒有取得可送入對話的文字。")
            ocr_time = format_response_time(ocr_time_sec)
            if ocr_time:
                st.caption(f"圖片辨識時間：{ocr_time}")
        st.rerun()

    st.session_state.image_ocr_panel_expanded = True
    with ocr_status_slot.container():
        st.warning(ocr_result.get("message", "圖片辨識失敗，請重新選擇圖片後再試。"))
        ocr_time = format_response_time(ocr_result.get("ocr_time_sec") or ocr_result.get("request_time_sec"))
        if ocr_time:
            st.caption(f"圖片辨識等待時間：{ocr_time}")
    st.rerun()


def render_feedback_panel(last_user_message: str | None, last_ai_response: str | None):
    with st.expander("📝 測試回饋：標記回答不好的地方", expanded=False):
        st.markdown('<span class="feedback-panel-marker"></span>', unsafe_allow_html=True)
        if not last_ai_response or st.session_state.is_generating:
            st.info("目前尚無可回饋的 AI 回覆。")
            return

        st.caption("送出後會儲存目前對話、最後一輪問答、客服建議與後端狀態，並追加到 CSV。")

        feedback_options = {
            "bad_answer": "回答不正確",
            "loop": "多輪卡住/重複回覆",
            "wrong_route": "意圖判斷錯誤",
            "tool_flow": "工具或報修流程錯誤",
            "knowledge": "知識庫答案不佳",
            "tone": "語氣或文字需調整",
            "other": "其他",
        }

        with st.form("feedback_form", clear_on_submit=True):
            selected_feedback_type = st.selectbox(
                "問題類型",
                options=list(feedback_options.keys()),
                format_func=lambda key: feedback_options.get(key, key),
            )
            st.text_area(
                "最後一輪使用者訊息",
                value=last_user_message or "",
                height=90,
                disabled=True,
            )
            st.text_area(
                "最後一輪 AI 回覆",
                value=last_ai_response or "",
                height=140,
                disabled=True,
            )
            suggestion = st.text_area(
                "客服建議 / 預期應該怎麼回",
                placeholder="例如：這裡不應該直接報修，應先詢問是否所有頻道都黑屏，並引導重開機上盒。",
                height=120,
            )
            submitted = st.form_submit_button("送出回饋", width="stretch", type="primary")

        if submitted:
            if not suggestion.strip():
                st.warning("請先輸入客服建議，這樣後續才有辦法分析修正方向。")
            else:
                feedback_result = send_feedback(
                    st.session_state.user_id,
                    st.session_state.selected_tv_cable,
                    selected_feedback_type,
                    suggestion,
                    last_user_message,
                    last_ai_response,
                    st.session_state.chat_history,
                )
                st.session_state.last_feedback_result = feedback_result
                if feedback_result.get("status") == "success":
                    reset_result = reset_backend_state(st.session_state.user_id)
                    notice = {
                        "feedback_id": feedback_result.get("feedback_id"),
                        "csv_path": feedback_result.get("csv_path"),
                        "db_saved": feedback_result.get("db_saved"),
                        "reset_status": reset_result.get("status"),
                        "reset_message": reset_result.get("message"),
                    }
                    reset_local_conversation()
                    st.session_state.pending_feedback_notice = notice
                    refresh_side_data()
                    st.rerun()
                else:
                    st.error(f"回饋儲存失敗：{feedback_result.get('message')}")

        if st.session_state.last_feedback_result:
            result = st.session_state.last_feedback_result
            if result.get("status") == "success":
                st.info(f"最近一次回饋：{result.get('feedback_id')}")


TRACKING_PROCESSING_LABELS = {
    "pending": "待修正",
    "processed": "已修正",
}
TRACKING_REVIEW_LABELS = {
    "organizing": "待整理",
    "merged": "已合併來源",
    "pending": "待驗收",
    "passed": "驗收通過",
    "failed": "驗收退回",
}
TRACKING_STAGE_LABELS = {
    "pending_fix": "待修正",
    "pending_organization": "待整理",
    "pending_acceptance": "待驗收",
    "accepted": "驗收通過",
    "rejected": "驗收退回",
}
LEGACY_TRACKING_PROCESSING_STATUS = {
    "passed": "processed",
    "closed": "processed",
    "in_progress": "processed",
    "pending_verification": "processed",
    "failed": "pending",
    "needs_rework": "pending",
    "ready_for_review": "pending",
}
LEGACY_TRACKING_REVIEW_STATUS = {"needs_adjustment": "failed"}


def tracker_processing_status(item: dict, default: str = "pending") -> str:
    status = str(item.get("status") or default)
    status = LEGACY_TRACKING_PROCESSING_STATUS.get(status, status)
    return status if status in TRACKING_PROCESSING_LABELS else default


def tracker_review_status(item: dict) -> str:
    status = str(item.get("review_status") or "pending")
    status = LEGACY_TRACKING_REVIEW_STATUS.get(status, status)
    return status if status in TRACKING_REVIEW_LABELS else "pending"


def tracker_option_label(value: str) -> str:
    return TRACKING_PROCESSING_LABELS.get(value, TRACKING_REVIEW_LABELS.get(value, value))


def tracker_stage(item: dict) -> str:
    review_status = tracker_review_status(item)
    if review_status == "passed":
        return "accepted"
    if review_status == "failed":
        return "rejected"
    if review_status == "organizing":
        return "pending_organization"
    if review_status == "merged":
        return "merged"
    if tracker_processing_status(item) == "processed":
        return "pending_acceptance"
    return "pending_fix"


def tracker_stage_label(value: str) -> str:
    return TRACKING_STAGE_LABELS.get(value, value)


def tracker_stage_payload(value: str) -> dict:
    if value == "accepted":
        return {"status": "processed", "review_status": "passed"}
    if value == "rejected":
        return {"status": "pending", "review_status": "failed"}
    if value == "pending_organization":
        return {"status": "processed", "review_status": "organizing"}
    if value == "pending_acceptance":
        return {"status": "processed", "review_status": "pending"}
    return {"status": "pending", "review_status": "pending"}


def feedback_context(item: dict) -> str:
    messages = item.get("conversation") or []
    user_messages = [
        " ".join(str(message.get("content") or "").split())
        for message in messages
        if message.get("role") == "user" and str(message.get("content") or "").strip()
    ]
    original_question = max(user_messages, key=len, default="")
    return original_question or " ".join(str(item.get("user_message") or "未提供問題").split())


def feedback_option_label(item: dict) -> str:
    context = feedback_context(item)
    label = (
        f"{str(item.get('created_at') or '')[:10]}  |  "
        f"{item.get('company_code') or '-'}  |  {context[:34]}"
    )
    return escape_streamlit_markdown_literals(label)


def case_option_label(item: dict) -> str:
    return f"{item.get('case_id')}  |  {item.get('group_name') or '-'}"


REGRESSION_SIGNAL_LABELS = {
    "PASS_CANDIDATE": "測試符合",
    "REVIEW": "需人工判讀",
    "DEPENDENCY": "受外部服務影響",
    "ERROR": "測試未完成",
}


def regression_evidence_label(feedback_id: str, source: dict | None, result: dict | None) -> str:
    company_code = (source or result or {}).get("company_code") or "-"
    suggestion = " ".join(str((source or {}).get("suggestion") or "").split())
    created_at = str((source or {}).get("created_at") or "")[:10]
    return f"{created_at or feedback_id[-6:]}  |  {company_code}  |  {suggestion[:22] or feedback_id}"


def tracker_month_from_feedback_id(feedback_id: str) -> str:
    match = re.search(r"FB-(\d{4})(\d{2})", str(feedback_id or ""))
    return f"{match.group(1)}-{match.group(2)}" if match else ""


def tracker_month_from_source(feedback_id: str, source: dict | None = None) -> str:
    created_at = str((source or {}).get("created_at") or "")
    if re.match(r"\d{4}-\d{2}", created_at):
        return created_at[:7]
    return tracker_month_from_feedback_id(feedback_id)


def tracker_month_label(value: str) -> str:
    if re.match(r"\d{4}-\d{2}$", str(value or "")):
        year, month = value.split("-", 1)
        return f"{year} 年 {month} 月"
    return "未標月份"


def regression_case_months(item: dict) -> list[str]:
    months: set[str] = set()
    sources_by_id = {
        str(source.get("feedback_id") or ""): source
        for source in item.get("source_feedback") or []
        if source.get("feedback_id")
    }
    for source_id in item.get("source_feedback_ids") or []:
        month = tracker_month_from_source(str(source_id), sources_by_id.get(str(source_id)))
        if month:
            months.add(month)
    for test_result in item.get("test_results") or []:
        feedback_id = str(test_result.get("feedbackId") or "")
        month = tracker_month_from_source(feedback_id, sources_by_id.get(feedback_id))
        if month:
            months.add(month)
    return sorted(months, reverse=True)


def tracker_viewer_name() -> str:
    account = globals().get("CURRENT_WEB_ACCOUNT") or {}
    return str(account.get("display_name") or account.get("username") or "")


def compact_tracker_text(value: str, limit: int = 700) -> str:
    text = " ".join(str(value or "").split())
    if len(text) <= limit:
        return text
    return f"{text[:limit].rstrip()}..."


def tracker_original_reply(item: dict) -> str:
    original_reply = str(item.get("ai_response") or "").strip()
    if original_reply:
        return original_reply
    assistant_messages = [
        str(message.get("content") or "").strip()
        for message in item.get("conversation") or []
        if message.get("role") == "assistant" and str(message.get("content") or "").strip()
    ]
    return assistant_messages[-1] if assistant_messages else ""


def tracker_result_reply(test_result: dict | None) -> str:
    responses = (test_result or {}).get("responses") or []
    replies = [
        str(response.get("reply") or "").strip()
        for response in responses
        if str(response.get("reply") or "").strip()
    ]
    return replies[-1] if replies else ""


def tracker_conversation_turns(messages: list[dict]) -> list[dict[str, str]]:
    turns: list[dict[str, str]] = []
    current: dict[str, str] | None = None
    for message in messages or []:
        role = str(message.get("role") or "").lower()
        content = str(message.get("content") or message.get("message") or "").strip()
        if not content:
            continue
        if role == "user":
            if current:
                turns.append(current)
            current = {"user": content, "assistant": ""}
        elif role == "assistant":
            if current is None:
                current = {"user": "", "assistant": content}
            elif current.get("assistant"):
                current["assistant"] = f"{current['assistant']}\n\n{content}"
            else:
                current["assistant"] = content
    if current:
        turns.append(current)
    return turns


def tracker_review_note_reply(review_note: str) -> str:
    match = re.search(r"(?:最後回答|調整後回答)[:：]\s*(.+)$", str(review_note or ""), re.S)
    return match.group(1).strip() if match else ""


def find_feedback_regression_case(feedback_id: str, regression_cases: list[dict]) -> tuple[dict | None, dict | None]:
    for case in regression_cases:
        source_ids = [str(source_id) for source_id in case.get("source_feedback_ids") or []]
        results = case.get("test_results") or []
        result = next(
            (
                test_result for test_result in results
                if str(test_result.get("feedbackId") or "") == feedback_id
            ),
            None,
        )
        if result or feedback_id in source_ids:
            return case, result
    return None, None


def tracker_plain_review_note(review_note: str) -> str:
    text = " ".join(str(review_note or "").split())
    if not text:
        return ""

    final_reply = tracker_review_note_reply(text)
    text = re.sub(r"；?(?:最後回答|調整後回答)[:：].*$", "", text)
    text = text.replace("AI 真實模型驗證", "重新測試")
    text = text.replace("真實模型驗證", "重新測試")
    text = text.replace("批次驗證執行失敗", "重新測試失敗")
    text = text.replace("以短期 token 呼叫 /chat，", "")
    text = text.replace("短期 token", "測試登入")
    text = text.replace("/chat", "客服回覆服務")
    text = text.replace("net_check_scope", "先確認影響範圍")
    text = text.replace("判讀：pass", "結果：符合期待")
    text = text.replace("判讀：fail", "結果：仍需調整")
    text = text.replace("判讀：error", "結果：測試失敗")
    text = text.replace("符合客服回饋，已處理", "調整後已符合客服回饋")
    text = text.replace("尚未符合客服回饋，待處理", "調整後仍未符合客服回饋")
    text = text.replace("尚未發布線上", "尚未同步到線上追蹤頁")
    text = re.sub(r"\s*\([a-zA-Z0-9_./:-]+\)", "", text)
    text = re.sub(r"（[a-zA-Z0-9_./:-]+）", "", text)
    text = re.sub(r"\s+", " ", text).strip("； ")

    if final_reply:
        text = f"{text}。完整修正後案例可在左側頁籤查看。"
    return text


def render_feedback_before_after(item: dict, regression_cases: list[dict]) -> None:
    case, test_result = find_feedback_regression_case(str(item.get("feedback_id") or ""), regression_cases)
    before_conversation = item.get("conversation") or []
    after_conversation = item.get("adjusted_conversation") or []

    if not after_conversation:
        after_reply = tracker_result_reply(test_result) or tracker_review_note_reply(str(item.get("review_note") or ""))
        if after_reply:
            before_turns = tracker_conversation_turns(before_conversation)
            last_user_message = before_turns[-1]["user"] if before_turns else ""
            if last_user_message:
                after_conversation = [
                    {"role": "user", "content": last_user_message},
                    {"role": "assistant", "content": after_reply},
                ]
            else:
                after_conversation = [{"role": "assistant", "content": after_reply}]

    if not before_conversation and not after_conversation:
        return

    if not after_conversation:
        st.markdown("**原始案例**")
        if before_conversation:
            render_tracker_conversation(before_conversation)
        else:
            st.info("沒有留下原始案例。")
    else:
        original_tab, adjusted_tab = st.tabs(["原始案例", "修正後案例"])
        with original_tab:
            if before_conversation:
                render_tracker_conversation(before_conversation)
            else:
                st.info("沒有留下原始案例。")
        with adjusted_tab:
            render_tracker_conversation(after_conversation)
    if case:
        st.caption(f"對應測試案例：{case.get('case_id')} · {case.get('group_name') or '-'}")


def render_regression_test_conversation(test_result: dict):
    turns = test_result.get("turns") or []
    responses = test_result.get("responses") or []
    if not responses:
        st.info("這個情境沒有可顯示的測試回答。")
        return
    for response in responses:
        turn_number = int(response.get("turn") or 0)
        user_text = turns[turn_number - 1] if 0 < turn_number <= len(turns) else ""
        if user_text:
            with st.chat_message("user"):
                st.markdown(preserve_markdown_linebreaks(str(user_text), linkify_links=False))
        with st.chat_message("assistant"):
            st.markdown(preserve_markdown_linebreaks(str(response.get("reply") or ""), linkify_links=False))
            decision_type = response.get("decisionType")
            if decision_type:
                st.caption(f"回覆類型：{decision_type}")


def render_regression_test_summary(test_result: dict | None):
    if not test_result:
        st.info("這個來源回饋尚未有對應的測試結果。")
        return
    signal = test_result.get("signal") or {}
    signal_code = str(signal.get("signal") or "REVIEW")
    label = REGRESSION_SIGNAL_LABELS.get(signal_code, signal_code)
    reasons = "；".join(str(reason) for reason in signal.get("reasons") or [])
    message = f"自動初判：{label}"
    if reasons:
        message = f"{message}\n\n{reasons}"
    if signal_code == "PASS_CANDIDATE":
        st.success(message)
    elif signal_code in {"DEPENDENCY", "ERROR"}:
        st.warning(message)
    else:
        st.info(message)
    if test_result.get("error"):
        st.error(f"測試錯誤：{test_result['error']}")
    elif test_result.get("durationSec"):
        st.caption(
            f"測試耗時：{float(test_result['durationSec']):.1f} 秒"
            f" · 環境：{WEB_UI_ENV_FILE.name}"
        )


def render_tracker_conversation(messages: list[dict]):
    if not messages:
        st.info("沒有可顯示的對話內容。")
        return
    for item in messages:
        role = "user" if item.get("role") == "user" else "assistant"
        with st.chat_message(role):
            st.markdown(
                tracker_display_markdown(
                    str(item.get("content") or ""),
                    auto_sentence_breaks=(role == "assistant"),
                )
            )


def render_feedback_tracker_page():
    tracker_notice = st.session_state.pop("tracker_sync_notice", None)
    if tracker_notice:
        result = tracker_notice.get("result") or {}
        message = feedback_tracker_sync_message(str(tracker_notice.get("action") or ""), result)
        if result.get("status") == "success":
            st.success(message)
        else:
            st.error(message)

    result = fetch_feedback_tracker_overview()
    if result.get("status") != "success":
        st.error(f"追蹤資料讀取失敗：{result.get('message')}")
        return

    feedback_items = result.get("feedback_items") or []
    regression_cases = result.get("regression_cases") or []
    tracking_stages = [tracker_stage(item) for item in feedback_items]
    pending_count = tracking_stages.count("pending_fix")
    organization_count = tracking_stages.count("pending_organization")
    acceptance_count = tracking_stages.count("pending_acceptance")
    passed_count = tracking_stages.count("accepted")
    failed_count = tracking_stages.count("rejected")
    organizing_cases = [
        item for item in regression_cases
        if tracker_stage(item) == "pending_organization"
    ]

    header_col, action_col = st.columns([1.8, 1])
    with header_col:
        st.markdown("### 回饋追蹤")
    with action_col:
        if CURRENT_WEB_ACCOUNT.get("role") == ROLE_DEVELOPER:
            with st.expander("線上同步"):
                if st.button("拉取線上回饋與紀錄", width="stretch", key="tracker_pull_online_feedback"):
                    confirm_pull_feedback_tracker()
                if st.button("更新線上追蹤頁", type="primary", width="stretch", key="tracker_publish_updates"):
                    confirm_publish_feedback_tracker()

    metrics = st.columns(5)
    metrics[0].metric("待修正", pending_count)
    metrics[1].metric("待整理", organization_count)
    metrics[2].metric("待驗收", acceptance_count)
    metrics[3].metric("驗收通過", passed_count)
    metrics[4].metric("驗收退回", failed_count)
    if organization_count and organizing_cases:
        st.caption(f"待整理已精簡為 {organization_count} 筆代表案例。")

    feedback_tab, case_tab = st.tabs(["回饋清單", "已驗證案例"])
    with feedback_tab:
        filter_cols = st.columns([1.1, 1, 1])
        selected_range = filter_cols[0].selectbox(
            "回饋期間", ["全部", "最近 7 天", "自訂期間"], key="tracker_feedback_range"
        )
        selected_tracking_stage = filter_cols[1].selectbox(
            "追蹤狀態", [""] + list(TRACKING_STAGE_LABELS),
            format_func=lambda value: "全部" if not value else tracker_stage_label(value),
            key="tracker_feedback_stage",
        )
        company_options = [""] + sorted({str(item.get("company_code") or "") for item in feedback_items if item.get("company_code")})
        selected_company = filter_cols[2].selectbox("系統台", company_options, format_func=lambda value: "全部" if not value else value, key="tracker_feedback_company")

        start_date = date(2026, 8, 24)
        end_date = date.today()
        if selected_range == "最近 7 天":
            start_date = end_date - timedelta(days=6)
        elif selected_range == "自訂期間":
            date_cols = st.columns(2)
            start_date = date_cols[0].date_input("開始日期", value=start_date, key="tracker_feedback_start_date")
            end_date = date_cols[1].date_input("結束日期", value=end_date, key="tracker_feedback_end_date")

        filtered_feedback = [
            item for item in feedback_items
            if start_date.isoformat() <= str(item.get("created_at") or "")[:10] <= end_date.isoformat()
            and (
                tracker_stage(item) == selected_tracking_stage
                if selected_tracking_stage
                else tracker_stage(item) != "merged"
            )
            and (not selected_company or item.get("company_code") == selected_company)
        ]
        if st.session_state.pop("tracker_clear_selected_feedback_after_save", False):
            st.session_state["tracker_selected_feedback"] = None
            st.session_state.pop("tracker_last_opened_feedback", None)
        previous_tracking_filter = st.session_state.get("tracker_previous_stage_filter")
        if (
            previous_tracking_filter is not None
            and previous_tracking_filter != selected_tracking_stage
        ):
            st.session_state["tracker_selected_feedback"] = None
            st.session_state.pop("tracker_last_opened_feedback", None)
        st.session_state["tracker_previous_stage_filter"] = selected_tracking_stage
        if not filtered_feedback:
            st.info("目前篩選條件下沒有回饋。")
        else:
            feedback_by_id = {item["feedback_id"]: item for item in filtered_feedback}
            if st.session_state.get("tracker_selected_feedback") not in feedback_by_id:
                st.session_state["tracker_selected_feedback"] = None
                st.session_state.pop("tracker_last_opened_feedback", None)
            selected_feedback_id = st.selectbox(
                f"回饋項目（{len(filtered_feedback)} 筆）",
                options=list(feedback_by_id),
                index=None,
                format_func=lambda value: feedback_option_label(feedback_by_id[value]),
                placeholder="請先選擇要查看的回饋項目",
                key="tracker_selected_feedback",
            )
            previous_feedback_id = st.session_state.get("tracker_last_opened_feedback")
            should_scroll_to_feedback = bool(
                selected_feedback_id and selected_feedback_id != previous_feedback_id
            )
            if selected_feedback_id:
                st.session_state["tracker_last_opened_feedback"] = selected_feedback_id
            else:
                st.session_state.pop("tracker_last_opened_feedback", None)
            if not selected_feedback_id:
                st.info("請先選擇一筆回饋項目，再查看情境與客服驗收。")
            else:
                item = feedback_by_id[selected_feedback_id]
                organized_case, _ = find_feedback_regression_case(
                    selected_feedback_id,
                    regression_cases,
                )
                is_organized_representative = bool(
                    tracker_stage(item) == "pending_organization"
                    and organized_case
                    and str(organized_case.get("case_id") or "").startswith("ORG-202609-")
                )
                st.markdown('<div id="tracker-feedback-details"></div>', unsafe_allow_html=True)
                st.markdown(f"#### {str(item.get('created_at') or '')[:10]} · {item.get('company_code') or '-'}")
                st.markdown("**情境重點**")
                st.markdown(
                    preserve_markdown_linebreaks(
                        (
                            str(organized_case.get("script") or "-")
                            if is_organized_representative
                            else feedback_context(item)
                        ),
                        linkify_links=False,
                    )
                )
                st.markdown("**客服回饋**")
                st.markdown(
                    tracker_display_markdown(
                        (
                            organized_case.get("expected_behavior") or "-"
                            if is_organized_representative
                            else item.get("suggestion") or "-"
                        ),
                        auto_sentence_breaks=True,
                    )
                )
                st.caption(
                    f"類型：{item.get('feedback_type') or '-'} · "
                    f"目前路由：{item.get('decision_type') or '-'} · ID：{selected_feedback_id}"
                )
                render_feedback_before_after(item, regression_cases)
                st.divider()
                st.markdown("#### 客服驗收")
                current_stage = tracker_stage(item)
                original_review_note = str(item.get("review_note") or "")
                if original_review_note:
                    st.caption("最近一次調整紀錄")
                    st.write(tracker_plain_review_note(original_review_note))
                if current_stage == "merged":
                    st.info("此筆已併入代表案例，僅保留來源供追溯，不需單獨驗收。")
                elif current_stage == "pending_fix":
                    st.info("目前正在待修正。完成調整並重新測試後，系統會送回待驗收。")
                else:
                    if current_stage == "pending_organization":
                        st.info("本案目前暫停重測與驗收，等待線上資料與回答規則整理完成後再安排驗證。")
                    tracking_stage = st.segmented_control(
                        "追蹤狀態",
                        ["pending_organization", "pending_acceptance", "accepted", "rejected"],
                        default=(
                            current_stage
                            if current_stage in {
                                "pending_organization", "pending_acceptance", "accepted", "rejected"
                            }
                            else "pending_acceptance"
                        ),
                        format_func=lambda value: {
                            "pending_organization": "待整理",
                            "pending_acceptance": "待驗收",
                            "accepted": "驗收通過",
                            "rejected": "退回修改",
                        }[value],
                        key=f"tracker_review_decision_{selected_feedback_id}",
                    )
                    decision_state_key = f"tracker_last_review_decision_{selected_feedback_id}"
                    previous_review_decision = st.session_state.get(decision_state_key)
                    should_scroll_to_return_feedback = bool(
                        previous_review_decision is not None
                        and previous_review_decision != "rejected"
                        and tracking_stage == "rejected"
                    )
                    st.session_state[decision_state_key] = tracking_stage
                    acceptance_issue = ""
                    acceptance_feedback = ""
                    if tracking_stage == "rejected":
                        st.markdown('<div id="tracker-return-feedback"></div>', unsafe_allow_html=True)
                        with st.form(f"tracker_feedback_editor_{selected_feedback_id}"):
                            st.caption("請說明這次回答哪裡不符合期待，處理人員會依此重新調整。")
                            return_issue_options = [
                                "回答內容不完整",
                                "回答不正確",
                                "流程或引導不符合",
                                "語氣或用詞不合適",
                                "其他",
                            ]
                            existing_issue = str(item.get("acceptance_issue") or "")
                            acceptance_issue = st.selectbox(
                                "退回原因",
                                return_issue_options,
                                index=(
                                    return_issue_options.index(existing_issue)
                                    if existing_issue in return_issue_options else 0
                                ),
                            )
                            acceptance_feedback = st.text_area(
                                "退回說明",
                                value=str(item.get("acceptance_feedback") or ""),
                                height=120,
                                placeholder="例：已能引導檢查設備，但還需要先回答客戶是否能報修，並避免直接轉真人客服。",
                            )
                            saved = st.form_submit_button("送出退回回饋", type="primary", width="stretch")
                    else:
                        action_label = (
                            "確認驗收通過"
                            if tracking_stage == "accepted"
                            else "儲存追蹤狀態"
                        )
                        saved = st.button(
                            action_label,
                            type="primary",
                            key=f"tracker_feedback_save_{selected_feedback_id}",
                        )
                    if saved:
                        if tracking_stage == "rejected" and not acceptance_feedback.strip():
                            st.error("請填寫驗收退回說明，讓處理人員知道需要怎麼調整。")
                        else:
                            changes = {
                                **tracker_stage_payload(tracking_stage),
                                "owner": tracker_viewer_name(),
                                "review_note": original_review_note,
                            }
                            if tracking_stage == "rejected":
                                changes.update({
                                    "acceptance_issue": acceptance_issue,
                                    "acceptance_feedback": acceptance_feedback,
                                })
                            saved_result = save_feedback_tracker_item(selected_feedback_id, changes)
                            if saved_result.get("status") == "success":
                                st.session_state["tracker_clear_selected_feedback_after_save"] = True
                                st.success("已儲存客服驗收結果。")
                                st.rerun()
                            else:
                                st.error(f"儲存失敗：{saved_result.get('message')}")
                    if should_scroll_to_return_feedback:
                        render_hidden_html(
                            """
                            <script>
                            const target = window.parent.document.getElementById('tracker-return-feedback');
                            if (target) {
                                target.scrollIntoView({ behavior: 'smooth', block: 'start' });
                            }
                            </script>
                            """
                        )
                if should_scroll_to_feedback:
                    render_hidden_html(
                        """
                        <script>
                        const target = window.parent.document.getElementById('tracker-feedback-details');
                        if (target) {
                            target.scrollIntoView({ behavior: 'smooth', block: 'start' });
                        }
                        </script>
                        """
                    )

    with case_tab:
        verified_cases = [
            item for item in regression_cases
            if tracker_stage(item) == "accepted" and item.get("test_results")
        ]
        if not verified_cases:
            st.info("目前還沒有可放入回歸案例庫的案例。請先在回饋清單確認調整前後內容，通過後就會收進這裡。")
            return
        st.caption("這裡只收已驗收通過的案例，作為之後檢查新規則是否影響舊回答的基準。")

        case_filters = st.columns(3)
        month_options = [""] + sorted({
            month
            for item in verified_cases
            for month in regression_case_months(item)
        }, reverse=True)
        selected_case_month = case_filters[0].selectbox(
            "案例月份",
            month_options,
            format_func=lambda value: "全部" if not value else tracker_month_label(value),
            key="tracker_case_month",
        )
        suite_options = [""] + sorted({
            str(item.get("suite") or "未分類案例") for item in verified_cases
        })
        selected_case_suite = case_filters[1].selectbox(
            "案例分類",
            suite_options,
            format_func=lambda value: "全部" if not value else value,
            key="tracker_case_suite",
        )
        group_options = [""] + sorted({str(item.get("group_name") or "") for item in verified_cases if item.get("group_name")})
        selected_case_group = case_filters[2].selectbox("主題", group_options, format_func=lambda value: "全部" if not value else value, key="tracker_case_group")
        filtered_cases = [
            item for item in verified_cases
            if (not selected_case_month or selected_case_month in regression_case_months(item))
            and (not selected_case_suite or str(item.get("suite") or "未分類案例") == selected_case_suite)
            and (not selected_case_group or item.get("group_name") == selected_case_group)
        ]
        if not filtered_cases:
            st.info("目前篩選條件下沒有已驗證案例。")
        else:
            case_by_id = {item["case_id"]: item for item in filtered_cases}
            if st.session_state.get("tracker_selected_case") not in case_by_id:
                st.session_state.pop("tracker_selected_case", None)
            selected_case_id = st.selectbox(
                f"回歸案例（{len(filtered_cases)} 筆）",
                options=list(case_by_id),
                format_func=lambda value: case_option_label(case_by_id[value]),
                key="tracker_selected_case",
            )
            item = case_by_id[selected_case_id]
            source_by_id = {source["feedback_id"]: source for source in item.get("source_feedback") or []}
            results_by_feedback_id = {
                str(test_result.get("feedbackId") or ""): test_result
                for test_result in item.get("test_results") or []
                if test_result.get("feedbackId")
            }
            evidence_ids = [
                feedback_id for feedback_id in results_by_feedback_id
                if not selected_case_month
                or tracker_month_from_source(feedback_id, source_by_id.get(feedback_id)) == selected_case_month
            ]
            if not evidence_ids:
                st.info("這筆已驗證案例目前沒有可顯示的測試結果。")
                return
            if st.session_state.get(f"tracker_case_evidence_{selected_case_id}") not in evidence_ids:
                st.session_state.pop(f"tracker_case_evidence_{selected_case_id}", None)
            selected_evidence_id = st.selectbox(
                "選擇客服原始回饋",
                evidence_ids,
                format_func=lambda feedback_id: regression_evidence_label(
                    feedback_id, source_by_id.get(feedback_id), results_by_feedback_id.get(feedback_id)
                ),
                key=f"tracker_case_evidence_{selected_case_id}",
            )
            source = source_by_id.get(selected_evidence_id)
            test_result = results_by_feedback_id.get(selected_evidence_id)

            source_col, summary_col = st.columns([1.55, 1])
            with source_col:
                st.markdown("**客服原始建議**")
                st.write((source or {}).get("suggestion") or "找不到這筆回饋的原始建議。")
                if source:
                    st.caption(
                        f"{str(source.get('created_at') or '')[:10]} · "
                        f"{source.get('company_code') or '-'} · {selected_evidence_id}"
                    )
            with summary_col:
                st.markdown("**最近一次測試**")
                render_regression_test_summary(test_result)

            original_tab, result_tab, criteria_tab = st.tabs([
                "原始對話", "調整後回答", "判斷依據"
            ])
            with original_tab:
                if source:
                    render_tracker_conversation(source.get("conversation") or [])
                else:
                    st.info("沒有可顯示的原始對話。")
            with result_tab:
                if test_result:
                    render_regression_test_conversation(test_result)
                else:
                    st.info("這個來源回饋尚未有對應的測試結果。")
            with criteria_tab:
                st.markdown("**這題要確認什麼**")
                st.write(item.get("expected_behavior") or "-")
                rule_cols = st.columns(2)
                rule_cols[0].markdown("**回答應有**")
                rule_cols[0].write(item.get("must_include") or "未指定")
                rule_cols[1].markdown("**回答避免**")
                rule_cols[1].write(item.get("must_not_include") or "未指定")
                st.caption(
                    f"分類：{item.get('suite') or '未分類案例'} · 主題：{item.get('group_name') or '-'} · "
                    f"題型：{item.get('case_kind') or '-'} · "
                    f"優先級：{item.get('priority') or '-'}"
                )


# =========================
# 4. Header
# =========================

st.markdown('<div class="chat-title">智慧客服測試系統（RAG 版）</div>', unsafe_allow_html=True)
st.markdown(
    '<div class="chat-subtitle">可由側邊導覽切換可使用的客服測試與維護功能。</div>',
    unsafe_allow_html=True
)

top1, top2, top3, top4 = st.columns([1.2, 1.2, 1.2, 4])

with top1:
    if st.button("🔄 重新整理狀態", width="stretch"):
        refresh_side_data()
        st.rerun()

with top2:
    if st.button("🧹 清除對話", width="stretch"):
        reset_result = reset_backend_state(
            st.session_state.user_id,
            simulated_web_custnum(),
        )

        st.session_state.chat_history = []
        st.session_state.pending_user_message = None
        st.session_state.is_generating = False
        st.session_state.last_state = {}

        refresh_side_data()

        if reset_result.get("status") != "success":
            st.warning(f"後端重置失敗：{reset_result.get('message')}")

        st.rerun()

with top3:
    if st.button("🆔 重建 User ID", width="stretch"):
        reset_local_conversation()
        refresh_side_data()
        st.rerun()

with top4:
    st.caption(
        f"目前 User ID：`{st.session_state.user_id}`；"
        f"測試儲存 ID：`{test_web_user_id(st.session_state.user_id)}`"
    )

st.markdown("---")


# =========================
# 5. Sidebar
# =========================

with st.sidebar:
    if WEB_AUTH_ENABLED:
        st.markdown('<div class="sidebar-title">登入帳號</div>', unsafe_allow_html=True)
        st.write(f"**帳號：** {CURRENT_WEB_ACCOUNT.get('display_name') or CURRENT_WEB_ACCOUNT.get('username')}")
        st.write(f"**角色：** {CURRENT_WEB_ACCOUNT.get('role_label')}")
        if st.button("登出", width="stretch"):
            clear_web_login()
        st.markdown("---")

    st.markdown('<div class="sidebar-title">外觀模式</div>', unsafe_allow_html=True)
    current_theme_label = "深色模式" if st.session_state.ui_theme_mode == "dark" else "淺色模式"
    next_theme_mode = "light" if st.session_state.ui_theme_mode == "dark" else "dark"
    next_theme_label = "切換淺色模式" if next_theme_mode == "light" else "切換深色模式"
    st.caption(f"目前：{current_theme_label}")
    st.button(
        next_theme_label,
        width="stretch",
        on_click=set_ui_theme_mode,
        args=(next_theme_mode,),
    )
    st.markdown("---")

    page_labels = AVAILABLE_PAGE_LABELS
    st.markdown('<div class="sidebar-title">導覽</div>', unsafe_allow_html=True)
    current_page = st.radio(
        "頁面",
        options=list(page_labels.keys()),
        format_func=lambda key: page_labels.get(key, key),
        label_visibility="collapsed",
        key="current_page",
    )
    st.markdown("---")

    st.session_state.company_options = fetch_companies()
    company_options = st.session_state.company_options
    company_codes = [item["code"] for item in company_options]
    company_label_map = {
        item["code"]: company_option_label(item)
        for item in company_options
    }

    if st.session_state.selected_tv_cable not in company_codes:
        st.session_state.selected_tv_cable = DEFAULT_TV_CABLE

    current_company_index = company_codes.index(st.session_state.selected_tv_cable)
    selected_tv_cable = st.selectbox(
        "測試系統台",
        options=company_codes,
        index=current_company_index,
        format_func=lambda code: company_label_map.get(code, code),
    )

    if selected_tv_cable != st.session_state.selected_tv_cable:
        reset_backend_state(st.session_state.user_id, simulated_web_custnum())
        st.session_state.selected_tv_cable = selected_tv_cable
        reset_local_conversation()
        refresh_side_data()
        st.rerun()

    st.caption(f"目前系統台：{company_label_map.get(st.session_state.selected_tv_cable, st.session_state.selected_tv_cable)}")

    if current_page == "chat":
        st.markdown("---")
        st.markdown("**Web 帶入身分**")
        st.toggle(
            "模擬 API 已帶入客編",
            key="simulate_web_authenticated_custnum",
            disabled=bool(st.session_state.confirmed_web_custnum),
        )
        custnum_locked = bool(st.session_state.confirmed_web_custnum)
        with st.form("web_custnum_form", border=False):
            st.text_input(
                "API 預帶客編",
                key="simulated_web_custnum",
                disabled=not st.session_state.simulate_web_authenticated_custnum or custnum_locked,
            )
            st.form_submit_button(
                "確認 API 客編",
                on_click=confirm_web_custnum,
                disabled=not st.session_state.simulate_web_authenticated_custnum or custnum_locked,
            )
        st.markdown(
            """
            <style>
            .st-key-simulated_web_custnum [data-testid="InputInstructions"] {
                display: none;
            }
            </style>
            """,
            unsafe_allow_html=True,
        )
        if st.session_state.simulate_web_authenticated_custnum:
            if custnum_locked:
                st.success("API 預帶客編已確認並鎖定。")
                st.button("解除 API 客編", on_click=unlock_web_custnum)
            else:
                st.caption("僅供測試模擬 API 登入參數；正式對話不要求客戶自行提供客編。")
                if st.session_state.web_custnum_error:
                    st.error(st.session_state.web_custnum_error)
                else:
                    st.warning("尚未套用 API 預帶客編，請輸入後確認。")

        current_identity_context = (
            st.session_state.simulate_web_authenticated_custnum,
            simulated_web_custnum() or "",
        )
        previous_identity_context = st.session_state.active_chat_identity_context
        if previous_identity_context is None:
            st.session_state.active_chat_identity_context = current_identity_context
        elif previous_identity_context != current_identity_context:
            previous_custnum = previous_identity_context[1] if previous_identity_context[0] else None
            current_custnum = current_identity_context[1] if current_identity_context[0] else None
            reset_backend_state(st.session_state.user_id, previous_custnum)
            reset_backend_state(st.session_state.user_id, current_custnum)
            st.session_state.active_chat_identity_context = current_identity_context
            clear_local_conversation()
            st.rerun()

    st.markdown("---")

    state = st.session_state.last_state or {}

    service = state.get("service")
    issue_type = state.get("issue_type")
    company = state.get("company", company_label_map.get(st.session_state.selected_tv_cable, "共用"))
    company_code = state.get("company_code", st.session_state.selected_tv_cable)
    next_goal = state.get("next_goal")
    need_dispatch = state.get("need_dispatch")
    known_info = state.get("known_info", {})
    available_slots = state.get("available_slots", [])
    last_knowledge_results = state.get("last_knowledge_results", [])

    st.markdown('<div class="sidebar-title">📊 目前狀態</div>', unsafe_allow_html=True)
    st.write(f"**服務類型：** {service if service else '未判定'}")
    st.write(f"**問題類型：** {issue_type if issue_type else '未判定'}")
    st.write(f"**公司：** {company if company else '共用'}")
    st.write(f"**系統台代碼：** {company_code}")

    if need_dispatch is None:
        st.write("**是否需要派工：** 未判定")
    elif need_dispatch is True:
        st.write("**是否需要派工：** 需要")
    else:
        st.write("**是否需要派工：** 暫不需要")

    st.write("**下一步目標：**")
    if next_goal:
        st.success(next_goal)
    else:
        st.info("尚未設定")

    st.markdown("---")

    st.markdown('<div class="sidebar-title">🧾 已收集資訊</div>', unsafe_allow_html=True)
    if not known_info:
        st.info("尚無資訊")
    else:
        for key, value in known_info.items():
            st.write(f"**{key}**：{value}")

    if available_slots:
        st.markdown("**可預約時段**")
        for slot in available_slots:
            st.write(f"- {slot}")

    st.markdown("---")

    st.markdown('<div class="sidebar-title">🔎 知識庫命中結果</div>', unsafe_allow_html=True)
    if not last_knowledge_results:
        st.info("本輪尚無知識庫命中結果")
    else:
        for i, item in enumerate(last_knowledge_results, start=1):
            with st.expander(f"{i}. {item.get('id', 'unknown')} | {item.get('category', '')}"):
                display_item = parse_kb_result_display(item)
                st.write(f"**company：** {display_item.get('company')}")
                st.write(f"**question：** {display_item.get('question')}")
                st.markdown("**answer：**")
                st.markdown(
                    preserve_markdown_linebreaks(
                        display_item.get("answer", ""),
                        linkify_links=False,
                    )
                )
                st.write(f"**distance：** {item.get('_distance')}")

    st.markdown("---")

    with st.expander("🛠️ 除錯資訊"):
        st.json(state)


# =========================
# 6. 主聊天區
# =========================

if current_page == "chat" and st.session_state.pending_feedback_notice:
    feedback_notice = st.session_state.pending_feedback_notice
    st.session_state.pending_feedback_notice = None
    st.success(
        f"已儲存回饋：{feedback_notice.get('feedback_id')}，並已建立新的用戶對話。"
    )
    if feedback_notice.get("db_saved") is False:
        st.warning("回饋已保存到 CSV，但資料庫備份寫入失敗；後端已記錄錯誤 log。")
    if feedback_notice.get("reset_status") not in (None, "success"):
        st.warning(f"舊對話後端狀態重置失敗：{feedback_notice.get('reset_message')}")

if current_page == "chat" and not st.session_state.chat_history:
    st.info("請在下方輸入訊息開始對話，例如：家裡網路不能上網、我想退租、固定IP怎麼申請。")

if current_page == "feedback_tracker":
    render_feedback_tracker_page()

if current_page == "company_profiles":
    st.markdown("### 🏢 公司資訊維護")
    st.caption("修改既有系統台基本資訊；儲存後會影響後續 AI 回覆、服務地區判斷與公司資訊查詢。")

    profiles_result = fetch_company_profiles()
    profiles = sort_company_options(profiles_result.get("profiles", []))
    profile_by_code = {
        item.get("tv_cable"): item
        for item in profiles
        if item.get("tv_cable")
    }

    if profiles_result.get("status") != "success":
        st.error(f"公司資料讀取失敗：{profiles_result.get('message')}")
    elif not profiles:
        st.info("目前沒有可維護的公司資料。")
    else:
        profile_codes = [item.get("tv_cable") for item in profiles]
        selected_profile_code = st.selectbox(
            "選擇系統台",
            options=profile_codes,
            format_func=lambda code: company_label_map.get(code, code),
            key="company_profile_editor_code",
        )
        current_profile = profile_by_code.get(selected_profile_code, {})
        current_address, current_phone = split_company_address_phone(current_profile.get("address_phone", ""))

        with st.form("company_profile_editor_form"):
            st.markdown("**開放維護欄位**")
            edit_cols = st.columns(2)
            edited_address = edit_cols[0].text_area(
                "地址",
                value=current_address,
                height=90,
                key=f"company_profile_{selected_profile_code}_address",
            )
            edited_phone = edit_cols[1].text_input(
                "電話",
                value=current_phone,
                key=f"company_profile_{selected_profile_code}_phone",
            )
            edited_business_hours = edit_cols[0].text_area(
                "營業時間",
                value=current_profile.get("business_hours", ""),
                height=110,
                key=f"company_profile_{selected_profile_code}_business_hours",
            )
            edited_service_area = edit_cols[1].text_area(
                "服務地區",
                value=current_profile.get("service_area", ""),
                height=110,
                key=f"company_profile_{selected_profile_code}_service_area",
            )
            edited_service_products = st.text_area(
                "目前服務產品",
                value=current_profile.get("service_products") or current_profile.get("service_items", ""),
                height=120,
                placeholder="例如：有線電視\n寬頻網路\nLINE TV",
                key=f"company_profile_{selected_profile_code}_service_products",
            )
            edited_area_outage = st.text_area(
                "區域故障",
                value=current_profile.get("area_outage", ""),
                height=110,
                placeholder="例如：大里區部分用戶寬頻連線不穩，工程搶修中。留空代表目前無公告。",
                key=f"company_profile_{selected_profile_code}_area_outage",
            )
            edited_promotion_activity = st.text_area(
                "優惠活動",
                value=current_profile.get("promotion_activity", ""),
                height=130,
                placeholder="例如：目前寬頻新申裝優惠請洽真人客服確認適用地區與申辦條件。留空代表目前無公告。",
                key=f"company_profile_{selected_profile_code}_promotion_activity",
            )
            edited_urls = st.text_area(
                "公司網址",
                value=current_profile.get("urls", ""),
                height=120,
                placeholder="例如：［官網🔗］https://example.com/\n［維修申告🔗］http://...",
                key=f"company_profile_{selected_profile_code}_urls",
            )
            edited_value_added_urls = st.text_area(
                "加值服務網址",
                value=current_profile.get("value_added_urls", ""),
                height=90,
                placeholder="例如：［LINE TV客服中心🔗］https://help.linetv.tw/hc/zh-tw",
                key=f"company_profile_{selected_profile_code}_value_added_urls",
            )
            edited_profile = {
                "address_phone": join_company_address_phone(edited_address, edited_phone),
                "business_hours": edited_business_hours,
                "service_area": edited_service_area,
                "service_products": edited_service_products,
                "area_outage": edited_area_outage,
                "promotion_activity": edited_promotion_activity,
                "urls": edited_urls,
                "value_added_urls": edited_value_added_urls,
            }

            st.markdown("**其他公司資訊（唯讀）**")
            readonly_cols = st.columns(2)
            for index, (field, label) in enumerate(COMPANY_PROFILE_READONLY_FIELDS):
                value = str(current_profile.get(field) or "")
                target_col = readonly_cols[index % 2]
                if field in {"urls", "service_items"}:
                    target_col.text_area(
                        label,
                        value=value,
                        height=80,
                        disabled=True,
                        key=f"company_profile_{selected_profile_code}_{field}_readonly",
                    )
                else:
                    target_col.text_input(
                        label,
                        value=value,
                        disabled=True,
                        key=f"company_profile_{selected_profile_code}_{field}_readonly",
                    )

            submitted_profile = st.form_submit_button("儲存公司資訊", type="primary", width="stretch")

        if submitted_profile:
            missing_required = []
            if not edited_address.strip():
                missing_required.append("地址")
            if not edited_phone.strip():
                missing_required.append("電話")
            if not edited_business_hours.strip():
                missing_required.append("營業時間")
            if not edited_service_area.strip():
                missing_required.append("服務地區")
            if missing_required:
                st.warning(f"請先填寫必要欄位：{'、'.join(missing_required)}")
            else:
                confirm_update_company_profile(
                    selected_profile_code,
                    current_profile,
                    edited_profile,
                )

        if st.session_state.last_company_profile_result:
            result = st.session_state.last_company_profile_result
            if result.get("status") == "success":
                st.success("已更新，後續 AI 回覆會使用新公司資料。")
            else:
                st.error(f"公司資料儲存失敗：{result.get('message')}")

if current_page == "knowledge_base":
    st.markdown("### 📚 知識庫維護")
    st.caption("上傳文件後會抽取文字、切成片段並寫入本地 ChromaDB；客服對話的 RAG 會直接查這裡。")

    docs_result = fetch_kb_documents(status="active")
    documents = docs_result.get("documents", [])
    existing_kb_bases = [
        str(document.get("knowledge_base") or LEGACY_COMMON_KNOWLEDGE_BASE).strip()
        for document in documents
    ]
    all_kb_base_options = sort_kb_base_names([
        *build_kb_base_options(st.session_state.company_options),
        *existing_kb_bases,
    ])
    view_kb_base_options = viewable_kb_base_options(
        CURRENT_WEB_ACCOUNT,
        all_kb_base_options,
    )
    writable_kb_base_options = manageable_kb_base_options(
        CURRENT_WEB_ACCOUNT,
        build_kb_base_options(st.session_state.company_options),
    )

    if CURRENT_WEB_ACCOUNT.get("role") == ROLE_DEVELOPER:
        st.info(
            "目前為系統管理者權限：可檢視與修改全部知識庫，"
            "並可在帳號管理中指定各主管可修改的系統台與通用分區。"
        )
    else:
        writable_labels = "、".join(
            display_base_name(value) for value in writable_kb_base_options
        )
        if writable_labels:
            st.info(
                f"主管可檢視全部知識庫；目前可修改：{writable_labels}。"
                "其他未授權的知識庫為唯讀。"
            )
        else:
            st.info(
                "主管可檢視全部知識庫；目前尚未授權可修改的系統台，"
                "如需新增、重建或刪除，請由系統管理者設定。"
            )

    if writable_kb_base_options:
        kb_write_busy = kb_write_operation_in_progress()
        kb_files = st.file_uploader(
            "上傳知識文件",
            type=["txt", "md", "html", "htm", "csv", "jsonl", "pdf", "docx"],
            accept_multiple_files=True,
            disabled=st.session_state.is_generating or kb_write_busy,
            key=f"kb_file_upload_{st.session_state.kb_upload_widget_version}",
        )
        kb_cols = st.columns([1.2, 1])
        with kb_cols[0]:
            kb_title = st.text_input("文件標題", value="")
        with kb_cols[1]:
            kb_base = st.selectbox(
                "知識庫分類",
                options=writable_kb_base_options,
                index=0,
                format_func=display_base_name,
            )
        st.caption("主題分類會由系統依文件內容自動判斷；查詢時不使用主題分類過濾，避免漏查。")

        if st.button(
            "上傳並建立索引",
            width="stretch",
            disabled=not kb_files or st.session_state.is_generating or kb_write_busy,
            type="primary",
        ):
            confirm_upload_kb_documents(kb_files, kb_title, kb_base)
    else:
        st.caption("此帳號目前為知識庫唯讀權限，仍可查看、下載與執行檢索診斷。")

    if not st.session_state.get("kb_debug_query_default_cleared_v1"):
        st.session_state["kb_debug_query"] = ""
        st.session_state["kb_debug_query_default_cleared_v1"] = True

    with st.expander("檢索診斷", expanded=False):
        st.caption("這裡會走聊天實際使用的檢索流程，用來確認問題會命中哪些知識片段。")
        debug_cols = st.columns([2.2, 1, 0.8])
        with debug_cols[0]:
            debug_query = st.text_input(
                "測試問題",
                value="",
                key="kb_debug_query",
            )
        with debug_cols[1]:
            debug_base = st.selectbox(
                "測試知識庫",
                options=view_kb_base_options,
                index=view_kb_base_options.index("大屯") if "大屯" in view_kb_base_options else 0,
                format_func=display_base_name,
                key="kb_debug_base",
            )
        with debug_cols[2]:
            debug_limit = st.number_input(
                "筆數",
                min_value=1,
                max_value=20,
                value=8,
                step=1,
                key="kb_debug_limit",
            )

        if st.button("測試聊天檢索", width="stretch", disabled=not debug_query.strip()):
            debug_result = chat_search_kb_documents(debug_query, debug_base, int(debug_limit))
            if debug_result.get("status") != "success":
                st.error(debug_result.get("message") or "檢索測試失敗")
            else:
                if debug_result.get("warning"):
                    st.warning(debug_result.get("warning"))
                st.info(
                    f"診斷模式：{debug_result.get('diagnostic_mode') or '-'}；"
                    f"檢索後端：{debug_result.get('rag_backend') or '-'}；"
                    f"檢索命中 {debug_result.get('count', 0)} 筆；"
                    f"回答守門保留 "
                    f"{debug_result.get('answerable_count', debug_result.get('count', 0))} 筆。"
                )
                campaign_match = debug_result.get("indexed_campaign_match")
                if campaign_match:
                    st.success(
                        "聊天路由已辨識索引活動別名："
                        f"{campaign_match.get('matched_alias') or '-'}"
                        f"（活動：{campaign_match.get('campaign_name') or '-'}；"
                        f"知識庫：{display_base_name(campaign_match.get('knowledge_base') or '-')}）"
                    )
                elif debug_result.get("guard_rejected_count"):
                    st.warning(
                        f"前段雖有命中，但回答守門淘汰了 "
                        f"{debug_result.get('guard_rejected_count')} 筆；"
                        "請檢查查詢意圖與片段內容是否一致。"
                    )
                sources = debug_result.get("sources") or []
                if not sources:
                    st.warning("沒有命中任何知識片段。")
                for index, source in enumerate(sources, start=1):
                    source_meta = source.get("source") if isinstance(source.get("source"), dict) else {}
                    title = source.get("question") or source_meta.get("title") or "-"
                    file_name = source_meta.get("source") or "-"
                    section = source_meta.get("section") or "-"
                    score = source.get("_score") or source_meta.get("score")
                    distance = source.get("_distance") or source_meta.get("distance")
                    st.markdown(f"**#{index} {title}**")
                    st.caption(f"{file_name} / {section} / score={score} / distance={distance}")
                    source_content = (source.get("answer") or source.get("content") or "")[:1200]
                    st.markdown(
                        f'<div class="kb-debug-source-content">{html.escape(source_content)}</div>',
                        unsafe_allow_html=True,
                    )

    if st.session_state.last_kb_reindex_all_result:
        result = st.session_state.last_kb_reindex_all_result
        if result.get("status") in {"success", "partial_success"}:
            total_count = int(result.get("total_count") or 0)
            indexed_count = int(result.get("indexed_count") or 0)
            failed_count = int(result.get("failed_count") or 0)
            chunk_count = int(result.get("chunk_count") or 0)
            if failed_count:
                st.warning(
                    f"全部重建完成：{indexed_count}/{total_count} 成功，"
                    f"{failed_count} 失敗，索引片段 {chunk_count}。"
                )
                for document in result.get("documents") or []:
                    if document.get("processing_status") == "failed":
                        st.error(
                            f"{document.get('title') or document.get('file_name') or '-'}："
                            f"{document.get('processing_error') or '索引失敗'}"
                        )
            else:
                st.success(
                    f"全部重建完成：{indexed_count}/{total_count} 成功，"
                    f"索引片段 {chunk_count}。"
                )
        else:
            st.error(result.get("message") or "全部重建索引失敗")
    elif st.session_state.last_kb_batch_results:
        success_count = sum(
            1 for item in st.session_state.last_kb_batch_results
            if item.get("status") == "success"
        )
        total_count = len(st.session_state.last_kb_batch_results)
        st.info(f"最近一次上傳結果：{success_count}/{total_count} 成功")

        for result in st.session_state.last_kb_batch_results:
            document = result.get("document") or {}
            file_name = result.get("file_name") or document.get("file_name") or "-"
            if result.get("status") == "success":
                st.success(
                    f"{file_name}：已建立索引，片段數 {document.get('indexed_chunk_count', 0)}"
                )
            else:
                error_text = document.get("processing_error") or result.get("message") or "知識庫處理失敗"
                st.error(f"{file_name}：{error_text}")
    elif st.session_state.last_kb_admin_result:
        result = st.session_state.last_kb_admin_result
        document = result.get("document") or {}
        action = result.get("action") or ""
        document_title = document.get("title") or document.get("file_name") or "-"
        if result.get("status") == "success":
            if action == "delete":
                st.success(f"已刪除文件：{document_title}")
            elif action == "reindex":
                st.success(
                    f"已重建索引：{document_title}，"
                    f"片段數 {document.get('indexed_chunk_count', 0)}"
                )
            else:
                st.success(
                    f"已建立索引：{document_title}，"
                    f"片段數 {document.get('indexed_chunk_count', 0)}"
                )
        else:
            error_text = document.get("processing_error") or result.get("message") or "知識庫處理失敗"
            if action == "delete":
                st.error(f"刪除失敗：{error_text}")
            elif action == "reindex":
                st.error(f"重建索引失敗：{error_text}")
            else:
                st.error(error_text)

    with st.expander("刪除紀錄", expanded=False):
        st.caption("保留刪除人員、時間、文件與知識庫分類，重新上傳同名文件也不會覆蓋這筆紀錄。")
        delete_logs_result = fetch_kb_audit_logs()
        if delete_logs_result.get("status") != "success":
            st.error(delete_logs_result.get("message") or "刪除紀錄讀取失敗。")
        else:
            delete_records = delete_logs_result.get("records") or []
            if not delete_records:
                st.info("目前沒有可查看的刪除紀錄。")
            else:
                delete_rows = []
                for record in delete_records:
                    detail = record.get("detail") or {}
                    actor_display = str(detail.get("actor_display_name") or "").strip()
                    actor_username = str(record.get("actor_username") or "").strip()
                    actor_text = actor_display or actor_username or "-"
                    if actor_display and actor_username and actor_display != actor_username:
                        actor_text = f"{actor_display}（{actor_username}）"
                    delete_rows.append({
                        "刪除時間": format_kb_audit_time(record.get("created_at")),
                        "刪除人員": actor_text,
                        "文件": detail.get("title") or "-",
                        "檔名": detail.get("file_name") or "-",
                        "知識庫": display_base_name(detail.get("knowledge_base") or "-"),
                    })
                st.dataframe(
                    delete_rows,
                    width="stretch",
                    hide_index=True,
                    column_order=["刪除時間", "刪除人員", "文件", "檔名", "知識庫"],
                )

    st.markdown("**目前文件**")
    if docs_result.get("status") != "success":
        st.error(docs_result.get("message") or "知識文件讀取失敗。")
    if not documents:
        st.info("目前沒有 active 知識文件。")
    else:
        render_kb_summary(documents)

        list_toolbar_cols = st.columns([2.2, 1.1, 1.6])
        with list_toolbar_cols[0]:
            st.markdown("**文件列表**")
            st.caption("排序會套用到全部與各知識庫分類分頁。")
        with list_toolbar_cols[1]:
            kb_document_sort_mode = st.selectbox(
                "排序方式",
                options=KB_DOCUMENT_SORT_OPTIONS,
                index=0,
                key="kb_document_sort_mode",
            )
        with list_toolbar_cols[2]:
            st.markdown('<div class="kb-sort-action-spacer"></div>', unsafe_allow_html=True)
            if st.button(
                "全部重建索引",
                width="stretch",
                disabled=(
                    st.session_state.is_generating
                    or kb_write_operation_in_progress()
                    or CURRENT_WEB_ACCOUNT.get("role") != ROLE_DEVELOPER
                ),
                help=(
                    "重新抽取所有 active 文件並重建整個向量索引"
                    if CURRENT_WEB_ACCOUNT.get("role") == ROLE_DEVELOPER
                    else "全部重建會影響所有系統台，僅限研發人員；主管仍可逐份重建授權範圍內的文件。"
                ),
            ):
                confirm_reindex_all_kb_documents(len(documents))

        sorted_documents = sort_kb_documents(documents, kb_document_sort_mode)
        render_kb_document_tabs(sorted_documents, view_kb_base_options)

    # Restore only after the document list has finished rendering, so the saved
    # scroll position is valid and the confirmation dialog transition stays still.
    render_pending_kb_download_bridge()
    render_pending_kb_scroll_restore_bridge()

if current_page == "account_management":
    render_account_management_page(CURRENT_WEB_ACCOUNT)

if current_page != "chat":
    st.stop()

for message in st.session_state.chat_history:
    render_chat_message(message)

assistant_generation_slot = st.empty()

if st.session_state.scroll_to_chat_bottom:
    scroll_to_chat_bottom()
    st.session_state.scroll_to_chat_bottom = False

st.markdown("---")
st.markdown('<div class="chat-input-spacer"></div>', unsafe_allow_html=True)

with st.form(
    f"chat_prompt_form_{st.session_state.chat_prompt_widget_version}",
    clear_on_submit=True,
):
    chat_send_disabled = (
        st.session_state.is_generating
        or st.session_state.is_image_ocr_processing
        or (
            st.session_state.simulate_web_authenticated_custnum
            and not simulated_web_custnum()
        )
    )
    prompt_cols = st.columns([10, 1])
    prompt = prompt_cols[0].text_input(
        "客服訊息",
        placeholder="請輸入您的問題，例如：家裡網路不能上網",
        label_visibility="collapsed",
        disabled=False,
    )
    submitted_prompt = prompt_cols[1].form_submit_button(
        "送出",
        disabled=chat_send_disabled,
        width="stretch",
    )
    clean_prompt = (prompt or "").strip()

st.markdown('<div class="chat-input-bottom-spacer"></div>', unsafe_allow_html=True)

sync_chat_input_draft(clear=st.session_state.clear_chat_input_draft)
st.session_state.clear_chat_input_draft = False

if st.session_state.focus_chat_input:
    focus_chat_input()
    st.session_state.focus_chat_input = False

if submitted_prompt and clean_prompt and not st.session_state.is_generating and not st.session_state.is_image_ocr_processing:
    st.session_state.chat_history.append({
        "role": "user",
        "content": clean_prompt
    })
    st.session_state.chat_prompt_widget_version += 1
    st.session_state.pending_user_message = clean_prompt
    st.session_state.pending_receipt_image_evidence_token = None
    st.session_state.is_generating = True
    st.session_state.scroll_to_chat_bottom = True
    st.session_state.focus_chat_input = True
    st.rerun()


image_ocr_status_slot = render_image_ocr_panel()
bind_contextual_expander_focus()

if st.session_state.is_image_ocr_processing:
    process_pending_image_ocr(image_ocr_status_slot)

if st.session_state.scroll_to_image_ocr_panel:
    scroll_to_image_ocr_panel()
    st.session_state.scroll_to_image_ocr_panel = False

last_user_message, last_ai_response = get_last_feedback_target()
st.markdown("---")
render_feedback_panel(last_user_message, last_ai_response)
st.markdown('<div class="page-bottom-safe-area" aria-hidden="true"></div>', unsafe_allow_html=True)


# =========================
# 8. AI 生成階段
# =========================

if st.session_state.is_generating and st.session_state.pending_user_message:
    pending_msg = st.session_state.pending_user_message

    with assistant_generation_slot.container():
        thinking_placeholder = st.empty()
        render_chat_message({"role": "assistant", "content": "思考中..."}, placeholder=thinking_placeholder)

        result = send_message(
            st.session_state.user_id,
            pending_msg,
            st.session_state.selected_tv_cable,
            simulated_web_custnum(),
            st.session_state.pending_receipt_image_evidence_token,
        )
        ai_msg = result.get("ai_response", "系統沒有回應")

        thinking_placeholder.empty()

        stream_placeholder = st.empty()
        final_text = stream_text(ai_msg, stream_placeholder, delay=0.008)
        response_time_sec = result.get("response_time_sec")
        render_chat_message({
            "role": "assistant",
            "content": final_text,
            "response_time_sec": response_time_sec,
            "cust_api_time_sec": result.get("cust_api_time_sec"),
            "latency": result.get("latency"),
        }, placeholder=stream_placeholder)

    st.session_state.chat_history.append({
        "role": "assistant",
        "content": final_text,
        "response_time_sec": result.get("response_time_sec"),
        "cust_api_time_sec": result.get("cust_api_time_sec"),
        "request_time_sec": result.get("request_time_sec"),
        "latency": result.get("latency"),
    })

    st.session_state.pending_user_message = None
    st.session_state.pending_receipt_image_evidence_token = None
    st.session_state.is_generating = False
    st.session_state.scroll_to_chat_bottom = True
    st.session_state.focus_chat_input = True

    refresh_side_data()
    st.rerun()
