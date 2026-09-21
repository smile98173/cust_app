import os
import json
from pathlib import Path

from app.config.env_loader import load_app_environment

BASE_DIR = Path(__file__).resolve().parent.parent.parent
APP_DIR = BASE_DIR / "app"
DATA_DIR = BASE_DIR / "data"

ACTIVE_ENV_FILE = load_app_environment(BASE_DIR)


def env_value(name: str, default: str = "") -> str:
    value = os.getenv(name)
    if value is None or not str(value).strip():
        return default
    return str(value).strip()


def app_path(value: str | Path, base_dir: Path = BASE_DIR) -> Path:
    path = Path(value)
    if path.is_absolute():
        return path
    return base_dir / path


RUNTIME_DIR = app_path(env_value("CUST_APP_RUNTIME_DIR", str(BASE_DIR.parent / "cust_app_runtime")))
LOG_DIR = app_path(env_value("APP_LOG_DIR", str(RUNTIME_DIR / "logs")))
FEEDBACK_DIR = app_path(env_value("FEEDBACK_DIR", str(RUNTIME_DIR / "feedback")))

TEST_DEFAULTS = {
    "OPENAI_API_KEY": "test-openai-api-key",
    "GEMINI_API_KEY": "test-gemini-api-key",
}

DB_PATH = str(DATA_DIR / "customer_state.db")
FEEDBACK_TRACKER_DB_PATH = str(
    app_path(env_value("FEEDBACK_TRACKER_DB_PATH", str(RUNTIME_DIR / "feedback_tracker.db")))
)
FEEDBACK_TRACKER_ONLINE_RUNTIME_DIR = env_value("FEEDBACK_TRACKER_ONLINE_RUNTIME_DIR", "")
FEEDBACK_TRACKER_ONLINE_API_BASE_URL = env_value(
    "FEEDBACK_TRACKER_ONLINE_API_BASE_URL", ""
).rstrip("/")
FEEDBACK_TRACKER_SYNC_TOKEN = env_value("FEEDBACK_TRACKER_SYNC_TOKEN", "")
FEEDBACK_CSV_PATH = str(app_path(env_value("FEEDBACK_CSV_PATH", str(FEEDBACK_DIR / "ai_feedback.csv"))))
FEEDBACK_CSV_DAILY = os.getenv("FEEDBACK_CSV_DAILY", "true").lower() in ["1", "true", "yes", "on"]
APP_ERROR_LOG_PATH = str(app_path(env_value("APP_ERROR_LOG_PATH", str(LOG_DIR / "app_errors.log"))))
APP_ERROR_LOG_DAILY = os.getenv("APP_ERROR_LOG_DAILY", "true").lower() in ["1", "true", "yes", "on"]
CHAT_LATENCY_LOG_PATH = str(app_path(env_value("CHAT_LATENCY_LOG_PATH", str(LOG_DIR / "chat_latency.log"))))
CHAT_LATENCY_LOG_DAILY = os.getenv("CHAT_LATENCY_LOG_DAILY", "true").lower() in ["1", "true", "yes", "on"]
CUST_API_DIAGNOSTIC_LOG_PATH = str(
    app_path(env_value("CUST_API_DIAGNOSTIC_LOG_PATH", str(LOG_DIR / "cust_api_diagnostic.log")))
)
CUST_API_DIAGNOSTIC_LOG_DAILY = os.getenv("CUST_API_DIAGNOSTIC_LOG_DAILY", "true").lower() in [
    "1",
    "true",
    "yes",
    "on",
]
PUBLIC_ERROR_MESSAGE = os.getenv(
    "PUBLIC_ERROR_MESSAGE",
    "抱歉，系統目前暫時無法完成處理，請稍後再試一次。",
)
COMPANY_PROFILE_PATH = str(app_path(env_value("COMPANY_PROFILE_PATH", str(RUNTIME_DIR / "company_profiles.json"))))
REGIONAL_POLICY_PATH = str(app_path(env_value("REGIONAL_POLICY_PATH", str(RUNTIME_DIR / "regional_policies.json"))))

WEB_AUTH_ENABLED = os.getenv("WEB_AUTH_ENABLED", "false").lower() in ["1", "true", "yes", "on"]
WEB_AUTH_DB_PATH = str(app_path(env_value("WEB_AUTH_DB_PATH", str(RUNTIME_DIR / "web_accounts.db"))))
WEB_AUTH_SECRET = env_value("WEB_AUTH_SECRET", env_value("API_AUTH_SECRET", "local-web-auth-secret"))
WEB_AUTH_BOOTSTRAP_USERNAME = env_value("WEB_AUTH_BOOTSTRAP_USERNAME", "")
WEB_AUTH_BOOTSTRAP_PASSWORD = env_value("WEB_AUTH_BOOTSTRAP_PASSWORD", "")

WEB_BACKEND_API_BASE_URL = os.getenv("WEB_BACKEND_API_BASE_URL", "http://127.0.0.1:8123").rstrip("/")
WEB_PUBLIC_API_BASE_URL = os.getenv("WEB_PUBLIC_API_BASE_URL", "").strip().rstrip("/")
API_AUTH_TOKEN = env_value("API_AUTH_TOKEN", "")
API_AUTH_HEADER = env_value("API_AUTH_HEADER", "X-API-Token")
API_AUTH_NAME = env_value("API_AUTH_NAME", "")
API_AUTH_PASSWORD = env_value("API_AUTH_PASSWORD", "")
API_AUTH_SECRET = env_value("API_AUTH_SECRET", API_AUTH_TOKEN)
API_AUTH_TOKEN_TTL_SECONDS = int(env_value("API_AUTH_TOKEN_TTL_SECONDS", "86400"))
API_AUTH_EXEMPT_PATH_PREFIXES = [
    item.strip()
    for item in env_value("API_AUTH_EXEMPT_PATH_PREFIXES", "/api/line/,/api/auth/token").split(",")
    if item.strip()
]
STATE_REPOSITORY_BACKEND = os.getenv("STATE_REPOSITORY_BACKEND", "sqlite").lower()
MONGODB_URI = os.getenv("MONGODB_URI", "mongodb://localhost:27017")
MONGODB_DATABASE = os.getenv("MONGODB_DATABASE", "aicust_service")
MONGODB_WEB_COLLECTION = os.getenv("MONGODB_WEB_COLLECTION", "web_conversations")
MONGODB_TEST_WEB_COLLECTION = os.getenv("MONGODB_TEST_WEB_COLLECTION", "test_web_conversations")
MONGODB_LINE_COLLECTION = os.getenv("MONGODB_LINE_COLLECTION", "line_conversations")

LLM_PROVIDER = os.getenv("LLM_PROVIDER", "openai").lower()
LLM_FALLBACK_PROVIDER = os.getenv("LLM_FALLBACK_PROVIDER", "ollama").lower()
LLM_ENABLE_FALLBACK = os.getenv("LLM_ENABLE_FALLBACK", "false").lower() in ["1", "true", "yes", "on"]

OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "gemma4:e4b")
OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "")
OLLAMA_TEMPERATURE = float(os.getenv("OLLAMA_TEMPERATURE", "0.5"))

OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-5.5")
OPENAI_API_KEY = env_value("OPENAI_API_KEY", "")
if OPENAI_API_KEY == TEST_DEFAULTS["OPENAI_API_KEY"]:
    OPENAI_API_KEY = ""
OPENAI_TEMPERATURE = float(os.getenv("OPENAI_TEMPERATURE", "0.4"))
OPENAI_BASE_URL = os.getenv("OPENAI_BASE_URL", "")

LLM_RAG_SUMMARY_PROVIDER = os.getenv("LLM_RAG_SUMMARY_PROVIDER", "openai").lower()
LLM_RAG_SUMMARY_MODEL = env_value(
    "LLM_RAG_SUMMARY_MODEL",
    OPENAI_MODEL if LLM_RAG_SUMMARY_PROVIDER == "openai" else OLLAMA_MODEL,
)
LLM_RAG_SUMMARY_BASE_URL = env_value(
    "LLM_RAG_SUMMARY_BASE_URL",
    OPENAI_BASE_URL if LLM_RAG_SUMMARY_PROVIDER == "openai" else OLLAMA_BASE_URL,
)
LLM_RAG_SUMMARY_TEMPERATURE = float(os.getenv("LLM_RAG_SUMMARY_TEMPERATURE", "0.3"))
LLM_RAG_SUMMARY_TIMEOUT_SECONDS = float(os.getenv("LLM_RAG_SUMMARY_TIMEOUT_SECONDS", "20"))
LLM_RAG_SUMMARY_ENABLE_FALLBACK = os.getenv("LLM_RAG_SUMMARY_ENABLE_FALLBACK", "false").lower() in [
    "1",
    "true",
    "yes",
    "on",
]
RAG_SUMMARY_MAX_DOCS = int(os.getenv("RAG_SUMMARY_MAX_DOCS", "5"))
RAG_SUMMARY_MAX_CHARS_PER_DOC = int(os.getenv("RAG_SUMMARY_MAX_CHARS_PER_DOC", "900"))

RAG_API_URL = os.getenv("RAG_API_URL", "")
RAG_API_TIMEOUT_SECONDS = float(os.getenv("RAG_API_TIMEOUT_SECONDS", "15"))
RAG_API_INCLUDE_EXPIRED = os.getenv("RAG_API_INCLUDE_EXPIRED", "false").lower() in [
    "1",
    "true",
    "yes",
    "on",
]
RAG_BACKEND = os.getenv("RAG_BACKEND", "local").lower()
RAG_LOCAL_PERSIST_DIR = str(app_path(env_value("RAG_LOCAL_PERSIST_DIR", str(RUNTIME_DIR / "chroma_db"))))
RAG_LOCAL_COLLECTION = os.getenv("RAG_LOCAL_COLLECTION", "company_kb")
RAG_LOCAL_DOCS_DIR = str(app_path(env_value("RAG_LOCAL_DOCS_DIR", str(RUNTIME_DIR / "kb_documents"))))
RAG_LOCAL_MANIFEST_PATH = str(app_path(env_value(
    "RAG_LOCAL_MANIFEST_PATH",
    str(RUNTIME_DIR / "kb_documents" / "documents.json"),
)))
RAG_LOCAL_EMBED_MODEL = os.getenv("RAG_LOCAL_EMBED_MODEL", "BAAI/bge-m3")
RAG_LOCAL_EMBED_DEVICE = os.getenv("RAG_LOCAL_EMBED_DEVICE", "").strip() or None
RAG_CHUNK_SIZE = int(os.getenv("RAG_CHUNK_SIZE", "1200"))
RAG_CHUNK_OVERLAP = int(os.getenv("RAG_CHUNK_OVERLAP", "200"))
RAG_LOCAL_MAX_DISTANCE = float(os.getenv("RAG_LOCAL_MAX_DISTANCE", "0.65"))
KB_INDEX_SHUTDOWN_WAIT_SECONDS = float(os.getenv("KB_INDEX_SHUTDOWN_WAIT_SECONDS", "300"))

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", TEST_DEFAULTS["GEMINI_API_KEY"])
GEMINI_IMAGE_TEXT_MODEL = os.getenv("GEMINI_IMAGE_TEXT_MODEL", "gemini-2.5-pro")
IMAGE_TEXT_MAX_SIZE = int(os.getenv("IMAGE_TEXT_MAX_SIZE", "1024"))
LINE_HUMAN_MODE_TIMEOUT_SECONDS = int(os.getenv("LINE_HUMAN_MODE_TIMEOUT_SECONDS", "1200"))
WEB_HUMAN_HANDOFF_TOKEN_KEY = env_value(
    "WEB_HUMAN_HANDOFF_TOKEN_KEY",
    "local-token-key!",
)

REPAIR_TICKET_FLOW_ENABLED = os.getenv("REPAIR_TICKET_FLOW_ENABLED", "false").lower() in [
    "1",
    "true",
    "yes",
    "on",
]
REPAIR_TICKET_FLOW_DISABLED_MESSAGE = os.getenv(
    "REPAIR_TICKET_FLOW_DISABLED_MESSAGE",
    (
        "您好，為更完整了解您的需求，建議轉由真人客服協助確認及安排。\n"
        "您也可填寫［維修申告🔗］http://stb.topmso.com.tw:8080/csr_mobile_client_web/Move_serviceAction.do?method=go_cust_con_fix_main&amp;cust_no_con=0&amp;accountNo=&amp;password= "
        "送出需求，我們將安排專人與您聯繫協助處理，謝謝。"
    ),
)
CUSTOMER_TOOL_FLOW_DISABLED_MESSAGE = os.getenv(
    "CUSTOMER_TOOL_FLOW_DISABLED_MESSAGE",
    "目前這項線上服務暫停服務，請您改由真人客服協助確認與安排。",
)
PROMOTION_QUERY_UNAVAILABLE_MESSAGE = os.getenv(
    "PROMOTION_QUERY_UNAVAILABLE_MESSAGE",
    "目前線上客服暫不提供優惠或促銷方案查詢，請您改由真人客服或官方客服管道確認最新方案。",
)

DEFAULT_LINE_BOT_CONFIGS = {
    "top": {
        "display_name": "台數科",
        "default_tv_cable": "",
        "default_area": "",
    },
    "test_bot": {
        "display_name": "測試 Bot",
        "default_tv_cable": "",
        "default_area": "",
    },
    "tdtv": {
        "display_name": "大屯",
        "default_tv_cable": "tdtv",
        "default_area": "大屯",
    },
    "cltv": {
        "display_name": "佳聯",
        "default_tv_cable": "cltv",
        "default_area": "佳聯",
    },
    "pktv": {
        "display_name": "北港",
        "default_tv_cable": "pktv",
        "default_area": "北港",
    },
}


def _build_line_bot_configs():
    configs = {}
    for bot_code, base_config in DEFAULT_LINE_BOT_CONFIGS.items():
        prefix = bot_code.upper()
        config = dict(base_config)
        config["bot_code"] = bot_code
        config["channel_access_token"] = os.getenv(
            f"LINE_{prefix}_CHANNEL_ACCESS_TOKEN",
            f"test-{bot_code}-channel-access-token",
        )
        config["channel_secret"] = os.getenv(
            f"LINE_{prefix}_CHANNEL_SECRET",
            f"test-{bot_code}-channel-secret",
        )
        config["human_group_id"] = os.getenv(
            f"LINE_{prefix}_HUMAN_GROUP_ID",
            f"test-{bot_code}-human-group-id",
        )
        config["human_access_token"] = os.getenv(
            f"LINE_{prefix}_HUMAN_ACCESS_TOKEN",
            config["channel_access_token"],
        )
        configs[bot_code] = config

    raw_json = os.getenv("LINE_BOT_CONFIGS_JSON", "").strip()
    if raw_json:
        try:
            for bot_code, override in json.loads(raw_json).items():
                current = dict(configs.get(bot_code, {}))
                current.update(override or {})
                current["bot_code"] = bot_code
                configs[bot_code] = current
        except Exception:
            pass

    return configs


LINE_BOT_CONFIGS = _build_line_bot_configs()

SERVICE_TYPES = ["network", "television", "billing"]
NETWORK_ISSUE_TYPES = ["slow_speed", "no_internet"]

FAQ_KEYWORDS = [
    "什麼是", "代表什麼", "是什麼", "如何", "怎麼", "怎麼辦", "怎麼辦理",
    "流程", "步驟", "規定", "規則", "帶什麼", "要帶", "需要帶", "文件", "證件",
    "設備", "多少錢", "費用", "月租", "違約金", "櫃台", "地址", "網址", "連結",
    "ibon", "famiport", "發票", "載具", "退租", "退費", "固定ip", "靜態ip",
    "speedtest", "紅燈", "綠燈", "沒收到帳單", "收不到帳單", "帳單沒收到",
]

BAD_NAME_VALUES = {
    "查詢帳單", "查帳單", "我要查帳單", "我要查詢帳單", "幫我查帳單", "幫我查詢帳單",
    "補寄帳單", "幫我補寄帳單", "補發帳單", "發簡訊帳單",
    "恢復網路", "恢復電視", "退租", "我要退租", "沒收到帳單", "帳單沒收到",
    "你好", "您好", "帳單", "網路", "電視"
}

SLOT_LABELS = {
    "service": "服務類型",
    "issue_type": "問題類型",
    "company": "公司",
    "connection_type": "連線方式",
    "speedtest_done": "是否測速",
    "download_speed": "下載速度",
    "upload_speed": "上傳速度",
    "affected_scope": "影響範圍",
    "router_exists": "是否有分享器",
    "router_reboot_done": "分享器是否重開",
    "modem_reboot_done": "數據機是否重開",
    "modem_light_status": "數據機燈號",
    "wifi_visible": "Wi-Fi 是否可見",
    "device_network_status": "裝置連線狀態",
    "customer_name": "姓名",
    "contact_phone": "聯絡電話",
    "service_address": "服務地址",
    "preferred_date": "偏好日期",
    "preferred_time_range": "偏好時段",
    "appointment_slot": "預約時段",
    "appointment_confirmed": "是否確認預約",
    "custnum": "客戶編號",
    "account_no": "帳號",
    "bill_month": "帳單月份",
    "name": "姓名",
    "phone": "電話",
}
