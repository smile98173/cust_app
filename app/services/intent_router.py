import json
import re
from typing import Any, Dict, List, Optional

from langchain_core.prompts import ChatPromptTemplate

from app.schemas.router import RouterDecision
from app.services.kb_answer_guard import is_definition_query
from app.services.kb_service import (
    detect_value_added_product_keys,
)
from app.services.company_profile import (
    DEFAULT_TV_CABLE,
    build_company_context,
    build_company_info_reply,
    get_company_profile,
    is_contextual_website_page_request,
    is_explicit_company_website_request,
)
from app.services.router_catalog import (
    DEFAULT_UNKNOWN_REPLY,
    MODEL_ROUTER_UNAVAILABLE_REPLY,
    SUPPORTED_TOOLS,
    UNSUPPORTED_REPLY,
)
from app.services.router_prompt import (
    build_contextual_runtime_intent_router_rules,
    select_runtime_policy_keys,
    select_runtime_prompt_modules,
)
from app.services.troubleshooting_engine import (
    is_tv_authorization_issue,
)
from app.services.query_normalization import (
    is_technical_ip_address_query,
    normalize_text_width,
    normalize_channel_name_from_query,
)
from app.services.regional_policy import build_policy_prompt
from app.services.channel_context import (
    resolve_service_availability_target,
)
from app.services.receipt_image_evidence import (
    RECEIPT_IMAGE_REQUIRED_REPLY,
    RECEIPT_IMAGE_REUPLOAD_REPLY,
    current_verified_receipt_image_evidence,
    is_receipt_image_submission,
)
from app.services.customer_validation import CONTRACT_LOOKUP_LOGIN_REQUIRED_REPLY


COMPANY_INFO_CLARIFY_TERMS = (
    "在哪",
    "在哪裡",
    "在哪邊",
    "哪裡",
    "哪邊",
    "位置",
)

COMPANY_ADDRESS_TERMS = (
    "地址",
    "公司地址",
    "櫃台地址",
    "門市地址",
    "營業處",
)

SERVICE_AREA_TERMS = (
    "服務範圍",
    "服務區域",
    "服務地區",
    "經營區",
    "服務哪裡",
    "有服務到",
)

BUSINESS_HOUR_TERMS = (
    "營業時間",
    "上班時間",
    "幾點開",
    "幾點關",
)

VALUE_ADDED_URL_TERMS = (
    "加值服務網址",
    "加值服務網站",
    "LINE TV客服中心",
    "LINE TV網址",
    "LINE TV網站",
    "linetv網址",
    "linetv網站",
)

CONTACT_PHONE_TERMS = (
    "客服電話",
    "公司電話",
    "聯絡電話",
)
PAPER_BILL_TERMS = ("紙本帳單", "紙本繳費單", "紙本帳款", "紙本帳務")
PAPER_BILL_REQUEST_TERMS = (
    "我要", "想要", "我想", "幫我", "協助", "申請", "辦理", "補寄", "補發",
    "寄送", "郵寄", "改寄", "改成", "改為", "換成", "索取", "沒收到", "未收到",
    "沒有收到", "不見", "遺失", "弄丟", "怎麼辦", "如何", "怎麼", "可以", "能不能",
    "可不可以", "哪裡", "哪邊", "哪兒", "?", "？",
)
PAPER_BILL_EXCLUSION_TERMS = (
    "我上傳了一張圖片", "辨識內容如下", "圖片辨識", "OCR", "ocr", "需要由真人客服",
    "由真人客服協助", "超商收據", "繳費收據", "便利商店收據", "收據條碼",
    "第一段條碼", "第二段條碼", "第三段條碼", "第1段條碼", "第2段條碼", "第3段條碼",
    "barCode", "barcode", "7-11", "全家", "萊爾富", "ibon", "IBON", "FamiPort", "復線",
    "恢復訊號", "斷訊", "欠費",
)
RECONNECTION_PROBLEM_TERMS = (
    "斷訊",
    "斷線",
    "欠費斷",
    "被斷",
    "停訊",
    "停用",
)

RECONNECTION_PAYMENT_TERMS = (
    "忘了繳費",
    "未繳",
    "欠費",
    "已繳費",
    "繳費",
)

PAID_RECONNECTION_TERMS = (
    "已經繳費",
    "已繳費",
    "繳費完成",
    "繳費了",
    "繳費成功",
    "付款成功",
    "已付款",
    "剛繳",
    "繳了",
    "付費了",
)

ONLINE_PAYMENT_TERMS = (
    "線上繳費",
    "線上付款",
    "線上刷卡",
    "網路繳費",
    "網路付款",
    "我要線上繳費",
    "要線上繳費",
)

PAYMENT_RECEIPT_TERMS = (
    "超商收據",
    "繳費收據",
    "便利商店收據",
    "7-11",
    "全家",
    "萊爾富",
    "OK",
    "第一段條碼",
    "第二段條碼",
    "第三段條碼",
)

NETWORK_RECONNECTION_TERMS = (
    "網路",
    "寬頻",
    "上網",
)

TV_RECONNECTION_TERMS = (
    "電視",
    "第四台",
    "收看",
    "訊號",
)

WEB_HUMAN_HANDOFF_REPLY = "此項可由真人文字客服協助處理。"
MEMBER_LOGIN_GUIDANCE_REPLY = (
    "官網與哈TV行動客服 APP 的登入資料是分開的，不能共用。\n"
    "1. 官網：使用用戶編號登入，用戶編號可從近期帳單查看。\n"
    "2. 哈TV行動客服 APP：使用雲端帳號登入，通常為申請服務時留存的手機號碼。\n"
    "若忘記密碼，請分別使用官網或 APP 登入頁的「忘記密碼」功能重設。"
)
ACCOUNT_HOLDER_CHANGE_FEE_REPLY = (
    "變更使用者不需收取費用，需由原使用者與新使用者攜帶相關證件與印章，"
    "至門市臨櫃辦理。"
)
ACCOUNT_HOLDER_CHANGE_DOCUMENTS_REPLY = (
    "辦理變更使用者，請準備原使用者與新使用者雙方的身分證正本、"
    "第二證件（健保卡或駕照）及印章，至門市臨櫃辦理即可。"
)
LINE_TV_CANCELLATION_REPLY = (
    "您可在收視到期前停止繳納續期費用；"
    "系統於到期日未收到款項後，即會自動停用 LINE TV 服務。"
    "您可安心使用至當期最後一天。"
)
BROADBAND_SUSPENSION_GUIDANCE_REPLY = (
    "寬頻暫停服務無法由線上 AI 直接代辦。"
    "是否可辦理、可暫停期間、合約影響與可能費用，"
    "需由客服依您目前的服務資料確認。"
)
MODEM_DS_LIGHT_STATUS_REPLY = (
    "數據機重新啟動後，DS 燈短暫閃爍通常表示正在同步下行訊號。"
    "若等待 3 到 5 分鐘後仍持續閃爍且無法上網，"
    "表示尚未完成同步，需由客服協助確認線路或檢修。"
)
NETWORK_SPEED_TEST_GUIDANCE_REPLY = (
    "請先重新啟動數據機，以電腦有線連接數據機，並暫停其他大量用網。"
    "接著可使用台基科官網 https://www.tinp.net.tw/ 的「網速測試」，"
    "或 https://www.speedtest.net/ 測試，再回覆下載與上傳結果。"
)
ONLINE_PAYMENT_ACCOUNT_HELP_REPLY = (
    "用戶編號可從紙本帳單、簡訊帳單，或哈TV行動客服 APP 的帳務資料查看。"
    "若仍無法確認，再由真人客服協助核對。"
)
ONLINE_PAYMENT_SUBMISSION_ISSUE_REPLY = (
    "請先確認卡號、有效期限、安全碼末三碼與 3D 驗證是否正確，"
    "再重新整理頁面、改用其他瀏覽器或稍後重試。"
    "仍無法送出時，可改用超商、ATM 或臨櫃等繳費管道；"
    "不可在聊天室提供完整卡號、安全碼或驗證碼。"
)
PAYMENT_POSTING_CONFIRMATION_REPLY = (
    "繳費入帳或重新授權可能需要短暫作業時間。"
    "請將對應的數據機、分享器或機上盒關機重開，等待約 2 分鐘後再確認；"
    "入帳明細可至官網或哈TV行動客服 APP 查詢。"
)
WIFI_ROUTER_SETTINGS_HELP_REPLY = (
    "請先連上目前 Wi-Fi，以瀏覽器開啟分享器管理網址並登入，"
    "再至「Wi-Fi／無線網路／Wireless／WLAN」的安全性設定修改名稱或密碼。"
    "儲存套用後，請讓各裝置使用新資料重新連線；"
    "管理網址、帳密與選單名稱依品牌型號而異，請參閱原廠說明書。"
)
IDENTITY_DOCUMENT_UPLOAD_GUIDANCE_REPLY = (
    "這個聊天服務不會代收身分證或雙證件照片。"
    "為保護個人資料，請使用哈TV行動客服 APP 的雙證件上傳功能。"
)
SELF_OWNED_ROUTER_COMPATIBILITY_REPLY = (
    "可以，公司沒有指定分享器品牌或型號，一般自備路由器都可使用。"
    "請將路由器的上網方式設為「DHCP／自動取得 IP」即可。"
)
SELF_OWNED_ROUTER_SETUP_REPLY = (
    "更換新路由器時，請將數據機的 LAN 埠連接至路由器的 WAN／Internet 埠，"
    "並將上網方式設為「DHCP／自動取得 IP」。"
    "公司採自動註冊機制，接上後通常可直接使用；Wi-Fi 名稱與密碼則依路由器說明書設定。"
)
MODEM_DUAL_ROUTER_DHCP_REPLY = (
    "原則上可以，數據機 LAN1、LAN2 可分別連接不同路由器。"
    "兩台路由器都請設為「DHCP／自動取得 IP」；若無法使用，再由真人客服協助確認。"
)
DYNAMIC_IP_ALLOCATION_COUNT_REPLY = (
    "一般方案原則上提供 8 組浮動 IP；特殊方案的可用數量需另外確認。"
)
ROUTER_MANUAL_REGISTRATION_REPLY = (
    "新路由器通常會自動完成設備註冊，接上後即可使用。"
    "若已確認使用 DHCP／自動取得 IP 仍無法上網，請至台基科官網 "
    "https://www.tinp.net.tw/ → 會員專區 →「電腦網卡更換註冊」完成手動註冊。"
    "完成後若仍無法上網，我可以再協助您轉接真人文字客服。"
)

MODEL_HUMAN_HANDOFF_INTENT_ALIASES = {
    "internet_service_cancellation_request",
    "internet_service_termination_request",
    "internet_service_cancellation_handoff",
    "broadband_service_cancellation_request",
    "broadband_termination_handoff",
    "cable_tv_termination_handoff",
    "service_termination_handoff",
    "promotion_application_handoff",
}

MODEL_HUMAN_HANDOFF_FOLLOWUP_INTENTS = {
    "broadband_termination_guidance",
    "internet_cancellation_guidance",
    "broadband_cancellation_guidance",
    "internet_service_cancellation_guidance",
    "service_termination_guidance",
}

MODEL_MEMBER_LOGIN_INTENTS = {
    "member_login_guidance",
    "member_account_login_guidance",
}

MODEL_ACCOUNT_HOLDER_CHANGE_FEE_INTENTS = {
    "account_holder_change_fee_query",
    "account_user_change_fee_query",
}

MODEL_ACCOUNT_HOLDER_CHANGE_DOCUMENT_INTENTS = {
    "account_user_change_required_documents",
    "account_holder_change_required_documents",
}

MODEL_SELF_OWNED_ROUTER_COMPATIBILITY_INTENTS = {
    "self_owned_router_compatibility_guidance",
    "customer_owned_router_compatibility",
    "third_party_router_compatibility",
}

MODEL_SELF_OWNED_ROUTER_SETUP_INTENTS = {
    "self_owned_router_setup_guidance",
    "router_initial_setup_guidance",
}

MODEL_MODEM_DUAL_ROUTER_INTENTS = {
    "modem_dual_router_dhcp_guidance",
    "modem_multiple_router_guidance",
}

MODEL_DYNAMIC_IP_COUNT_INTENTS = {
    "dynamic_ip_allocation_count",
    "floating_ip_count_guidance",
}

MODEL_ROUTER_MANUAL_REGISTRATION_INTENTS = {
    "router_manual_registration_guidance",
    "network_device_manual_registration_guidance",
}

BROADBAND_TERMINATION_GUIDANCE_REPLY = (
    "您好，寬頻網路退租須由客服依您的合約狀態、設備歸還及可能費用確認。\n"
    "若仍在綁約期間，提前退租可能會有違約金。\n"
    "設備部分通常需歸還數據機及實際租借的相關配件，實際項目仍以客服查詢與現場設備為準。"
)

MODEL_APPROVED_DIRECT_REPLY_CONTRACTS = {
    "broadband_termination_guidance": (
        "寬頻網路退租",
        BROADBAND_TERMINATION_GUIDANCE_REPLY,
    ),
    "broadband_service_suspension_guidance": (
        "寬頻暫停服務",
        BROADBAND_SUSPENSION_GUIDANCE_REPLY,
    ),
    "identity_document_upload": (
        "身分證件上傳",
        IDENTITY_DOCUMENT_UPLOAD_GUIDANCE_REPLY,
    ),
    "line_tv_cancellation_guidance": (
        "LINE TV 取消與到期停用",
        LINE_TV_CANCELLATION_REPLY,
    ),
    "modem_ds_light_status_guidance": (
        "數據機 DS 燈狀態",
        MODEM_DS_LIGHT_STATUS_REPLY,
    ),
    "network_speed_test_guidance": (
        "網路測速操作",
        NETWORK_SPEED_TEST_GUIDANCE_REPLY,
    ),
    "online_payment_account_help": (
        "線上繳費用戶編號",
        ONLINE_PAYMENT_ACCOUNT_HELP_REPLY,
    ),
    "online_payment_submission_issue": (
        "線上繳費無法送出",
        ONLINE_PAYMENT_SUBMISSION_ISSUE_REPLY,
    ),
    "payment_posting_confirmation_guidance": (
        "已入帳但服務未恢復",
        PAYMENT_POSTING_CONFIRMATION_REPLY,
    ),
    "personal_contract_info_lookup": (
        "本人合約資訊查詢",
        CONTRACT_LOOKUP_LOGIN_REQUIRED_REPLY,
    ),
    "wifi_router_settings_help": (
        "Wi-Fi 名稱與密碼設定",
        WIFI_ROUTER_SETTINGS_HELP_REPLY,
    ),
}
REPAIR_VISIT_EXPECTATION_REPLY = (
    "若您已完成預約，工程人員通常會依排程或預約時段與您聯繫。"
    "請您耐心等候；如已超過約定時段，歡迎再與我們聯繫，謝謝。"
)
POINTS_ACCOUNT_MERGE_REPLY = (
    "您好，不同用戶編號的哈 Point 點數是分開累積的，目前無法合併或轉移，敬請見諒，謝謝。"
)
HUMAN_HANDOFF_TRIAGE_REPLY = (
    "可以，請先告訴我遇到什麼問題，我會先協助確認；"
    "若仍需要真人客服，我會提供轉接方式。"
)
HUMAN_HANDOFF_CONFIRM_REPLY = HUMAN_HANDOFF_TRIAGE_REPLY
WIFI_VALUE_ADDED_YOUTUBE_REPLY = (
    "WiFi 加值服務主要是提供無線網路設備與 WiFi 訊號延伸，本身不是 YouTube 或影音 App 功能。\n"
    "加值 WiFi 後，手機、平板、智慧電視或支援 YouTube 的設備可透過網路使用 YouTube；"
    "若是數位機上盒能否直接開 YouTube，仍需依機型與系統支援確認。"
)
PURE_TV_INSTALL_KNOWLEDGE_QUERY = (
    "純有線電視 單辦有線電視 第四台 基本收費標準 基本收視費 "
    "月繳 季繳 半年繳 年繳 裝機費 機上盒押金 分機費"
)
PROMOTION_SERVICE_SCOPE_CLARIFY_REPLY = (
    "請問您想了解哪一類優惠方案？\n"
    "1. 有線電視＋網路\n"
    "2. 純網路\n"
    "3. 純有線電視"
)
BASIC_CHANNEL_TABLE_REPLY = (
    "基本頻道就是有線電視頻道。您可以到系統台官網的頻道查詢頁面查看最新頻道表；"
    "實際可收視頻道仍以您所在地區與系統台公告為準。"
)
VIRTUAL_HOSTING_UNSUPPORTED_REPLY = (
    "您好，目前本公司未提供「虛擬主機」服務，抱歉無法協助辦理。"
)
HUMAN_HANDOFF_REQUEST_PATTERNS = (
    "找真人",
    "找真人客服",
    "轉真人",
    "轉真人客服",
    "真人處理",
    "真人客服處理",
    "真人接手",
    "真人客服接手",
    "真人協助",
    "真人客服協助",
    "請真人客服",
    "找人工客服",
    "請人工客服",
    "轉人工",
    "轉人工客服",
    "人工處理",
    "人工客服處理",
    "人工接手",
    "人工客服接手",
    "人工協助",
    "人工客服協助",
    "找專人",
    "轉專人",
    "專人協助",
    "專人處理",
    "專人接手",
    "不要ai",
    "不要AI",
    "不想跟ai",
    "不想跟AI",
    "不要機器人",
)

HUMAN_HANDOFF_CONFIRMATION_PATTERNS = (
    "有沒有真人",
    "有真人嗎",
    "真人在嗎",
    "有人工嗎",
    "真人客服",
    "人工客服",
    "專人客服",
)

HUMAN_HANDOFF_CONTACT_INFO_TERMS = (
    "電話",
    "聯絡",
    "營業時間",
    "上班時間",
    "地址",
    "怎麼找",
    "怎麼聯絡",
)

HUMAN_HANDOFF_CONFIRM_YES_VALUES = {
    "是",
    "是的",
    "對",
    "對的",
    "好",
    "好的",
    "好喔",
    "好哦",
    "ok",
    "okay",
    "可以",
    "要",
    "麻煩",
    "麻煩你",
    "請轉",
}

HUMAN_HANDOFF_CONFIRM_NO_VALUES = {
    "不是",
    "不用",
    "不用了",
    "不要",
    "先不用",
    "不需要",
    "否",
    "沒關係",
}

PERSONAL_ACCOUNT_QUERY_TERMS = (
    "合約到期",
    "合約期限",
    "合約什麼時候到期",
)

CURRENT_PLAN_QUERY_TERMS = (
    "我的網路",
    "我家網路",
    "我的網路是幾m",
    "我的網路是幾M",
    "我家網路是幾m",
    "我家網路是幾M",
    "目前網速",
    "現在網速",
    "申請網速",
    "申辦網速",
    "目前方案",
    "現在方案",
    "我的方案",
)

RENEWAL_PROCESS_TERMS = (
    "續約",
    "重新續約",
    "續訂",
    "重新訂購",
    "約滿",
    "合約到期後",
    "合約到期了",
)

RENEWAL_PROCESS_ACTION_TERMS = (
    "怎麼",
    "如何",
    "辦理",
    "申請",
    "方式",
    "流程",
    "要去哪",
    "去哪",
)

NEW_INSTALL_FAULT_CONTEXT_TERMS = (
    "不能用",
    "不能上網",
    "無法上網",
    "沒網路",
    "斷線",
    "故障",
    "不通",
    "燈號",
    "裝好後",
    "安裝後",
)

SET_TOP_BOX_MULTI_FEE_DEVICE_TERMS = (
    "機上盒",
    "stb",
    "STB",
    "分機",
    "多台電視",
    "多台",
)

SET_TOP_BOX_MULTI_FEE_COUNT_TERMS = (
    "多台",
    "2台",
    "二台",
    "兩台",
    "3台",
    "三台",
    "第二台",
    "第2台",
    "第三台",
    "第3台",
    "第六台",
    "第6台",
    "以上",
    "加裝",
    "申裝",
)

SET_TOP_BOX_MULTI_FEE_COST_TERMS = (
    "費用",
    "收費",
    "費",
    "押金",
    "裝機費",
    "分機費",
    "施工費",
    "怎麼算",
    "多少錢",
)

COMBO_PLAN_TERMS = (
    "同時申裝有線網路",
    "同時申裝有線電視網路",
    "同時申裝電視網路",
    "有線電視加網路",
    "有線電視+網路",
    "有線電視＋網路",
    "電視加網路",
    "電視+網路",
    "電視＋網路",
    "電視跟網路",
    "電視和網路",
    "電視與網路",
    "第四台加網路",
    "第四台+網路",
    "第四台＋網路",
    "第四台跟網路",
    "第四台和網路",
    "第四台與網路",
    "電視 網路",
)

PROMOTION_QUERY_TERMS = (
    "促銷",
    "優惠",
    "最新優惠",
    "優惠方案",
    "優惠活動",
    "活動方案",
    "推薦方案",
    "方案推薦",
    "最新方案",
)

PROMOTION_DISCOVERY_OCCASION_TERMS = (
    "春節", "過年", "新春", "元宵", "清明", "兒童節", "勞動節",
    "母親節", "媽媽節", "媽咪", "端午", "父親節", "爸爸節", "爸氣",
    "七夕", "情人節", "中秋", "國慶", "雙十", "聖誕", "耶誕", "跨年",
    "開學", "暑期", "暑假", "週年慶", "周年慶", "年終", "歲末", "尾牙",
)

PROMOTION_FOLLOWUP_DETAIL_TERMS = (
    "這個方案",
    "此方案",
    "這優惠",
    "這個優惠",
    "活動內容",
    "方案內容",
    "到何時",
    "到什麼時候",
    "到哪時候",
    "優惠期限",
    "活動期限",
    "贈品",
    "家電",
    "電視機",
    "壁掛",
    "保固",
    "配送",
    "品牌",
    "廠牌",
    "可以選",
    "有哪些",
    "總共費用",
    "總費用",
    "總金額",
    "合計",
    "裝到好",
    "裝機費",
    "設備押金",
    "押金",
    "LINE TV",
    "LINETV",
    "LITV",
    "贈幾個月",
    "送幾個月",
    "POINT",
    "POINTS",
    "點數",
    "抽獎",
    "中獎",
    "違約金",
    "綁約",
    "活動期間",
    "如何申請",
    "怎麼申請",
    "怎麼辦理",
    "申請方式",
)

SPECIFIC_PROMOTION_QUERY_TERMS = ()

PROMOTION_COMPANY_INFO_BLOCK_TERMS = (
    "優惠",
    "優惠方案",
    "優惠活動",
    "活動",
    "方案",
    "送家電",
    "送電視",
    "贈品",
    "家電",
    "冰箱",
    "投影機",
)

PERSONAL_SERVICE_FEE_SUBJECT_TERMS = (
    "我家",
    "我家的",
    "我的",
    "目前",
    "現在",
    "目前使用",
    "現在使用",
    "家裡",
)

PERSONAL_SERVICE_FEE_TARGET_TERMS = (
    "網路費用",
    "寬頻費用",
    "電視費用",
    "第四台費用",
    "有線電視費用",
    "月租",
    "月繳",
    "費用",
    "收費",
    "費率",
    "多少錢",
)

PERSONAL_SERVICE_FEE_EXCLUDE_TERMS = (
    "優惠",
    "優惠方案",
    "促銷",
    "活動",
    "方案",
    "新申辦",
    "新裝",
    "申請",
    "申辦",
    "單辦",
    "只要網路",
    "單裝網路",
)

INSTALLED_SERVICE_TROUBLE_TERMS = (
    "無法使用",
    "不能使用",
    "無法上網",
    "不能上網",
    "不能用",
    "用不了",
    "沒有網路",
    "沒網路",
    "網路不穩",
    "不穩",
    "斷線",
    "視訊",
    "需要協助",
    "協助",
    "故障",
)

INSTALLED_SERVICE_CONTEXT_TERMS = (
    "最近剛申辦",
    "剛申辦",
    "剛裝",
    "申辦",
    "裝機",
    "家裡",
    "家中",
    "我家",
    "二樓",
    "一樓",
    "房間",
    "客廳",
    "手機",
    "wifi",
    "WiFi",
    "WIFI",
    "wi-fi",
    "Wi-Fi",
    "網路",
    "寬頻",
    "電視",
)

PROMOTION_PRICE_DIFFERENCE_TERMS = (
    "隔壁",
    "鄰居",
    "別人",
    "其他人",
    "朋友",
    "同事",
)

PROMOTION_PRICE_COMPARISON_TERMS = (
    "比較便宜",
    "比我便宜",
    "比我低",
    "價格不一樣",
    "費用不一樣",
    "費率不一樣",
    "收費不一樣",
    "為什麼比較貴",
    "為何比較貴",
    "為什麼比較便宜",
    "為何比較便宜",
)

PROMOTION_PRICE_DIFFERENCE_REPLY = (
    "您好，了解您想確認是否有更優惠的方案。"
    "優惠內容會依客戶資格及申辦時間條件有所不同，"
    "我們可協助轉由文字客服專人為您查詢目前適用的優惠方案，"
    "並提供進一步說明，謝謝。"
)

GENERAL_CHANNEL_E004_REPLY = (
    "若一般基本頻道也顯示 E004、授權到期或未授權，請先確認收視費是否已繳清。\n"
    "若尚未繳費，我可以先協助您進行電視暫時復線；請問需要我現在協助嗎？"
)

APP_PAYMENT_RECEIPT_REPLY = (
    "使用 APP 或官網線上繳費後，不會另外寄送實體收據到府。"
    "費用入帳後，發票號碼會於營業日以簡訊通知用戶。\n"
    "您也可自行查詢：\n"
    "1. 官網：客戶服務 → 發票查詢 → 輸入客編及密碼即可查詢。\n"
    "2. 哈TV行動客服 APP：註冊後登入帳密 → 歷史帳單即可查詢。\n"
    "若需要申請發票號碼載具歸戶，可到公司官網的客戶服務 → 發票查詢，"
    "輸入用戶帳號密碼後點選「用戶歸戶」，並連結財政部網站進行歸戶。"
)

INVOICE_ISSUE_TIMING_REPLY = (
    "1. 電子發票會在入帳後的第二天，以發送簡訊方式通知客戶。\n"
    "2. 紙本發票通常會在入帳後的 16 天內寄出。\n"
    "如果您需要申請發票號碼載具，可到公司官網，進入客戶服務 → 發票查詢，"
    "輸入您的用戶帳號密碼，點選「用戶歸戶」，並連結財政部網站進行歸戶。"
)

CLOUD_ACCOUNT_APP_GUIDE_REPLY = (
    "您可以先下載並安裝行動客服 APP，再使用雲端帳號與密碼登入。\n"
    "登入後可使用線上報修、帳單查詢、紅利點數查詢及繳費等功能。\n"
    "若無法登入或忘記密碼，請依 APP 登入頁的指示處理，或由客服協助核對帳號資料。"
)

WIFI_VALUE_ADDED_SERVICE_REPLY = (
    "WiFi 加值服務目前可參考：\n"
    "WiFi 5 系列分享器：月均價 25 元，限半年繳 150 元或年繳 300 元。\n"
    "WiFi 6 系列分享器：月均價 50 元，限半年繳 300 元或年繳 600 元。"
)

NETWORK_SIMPLE_TROUBLESHOOTING_REPLY = (
    "可以，我先帶您做簡單排除：\n"
    "1. 請將數據機電源拔掉約 10 秒後重新插上，等待 3 到 5 分鐘。\n"
    "2. 確認數據機燈號是否正常亮起，並重新連線 Wi-Fi 或網路線。\n"
    "3. 若手機、電腦等多台設備都仍然不穩，請回覆目前燈號狀態，我再協助您判斷是否需要報修。"
)

CONNECTED_STB_YOUTUBE_REPLY = (
    "您好，目前公司提供的機上盒分為聯網型及非聯網型。"
    "如有聯網需求，可加購每月 60 元換裝聯網型機上盒，聯網型機上盒可使用 YouTube、LINE TV 等數位串流功能。\n"
    "實際是否符合申辦及換裝條件，需由客服依您的地址、合約狀態及適用方案進行確認，謝謝您。"
)

CNT_SEASONAL_AUTHORIZATION_REPLY = (
    "目前無費用需繳納，如您已繳費，請記得將機上盒電源關機約 10 秒後重新開機再確認。\n"
    "有線電視季繳可享優惠二擇一：\n"
    "1. 頻道優惠：免費收視 HBO 頻道 CH221 + 博斯頻道 CH244。\n"
    "2. 現金折扣 45 元。\n"
    "季繳收視費為 1,695 元；如果當初選的是現金折扣，就不會同時贈送 HBO。"
    "實際適用狀態仍需由客服協助確認。"
)

CANCEL_TV_KEEP_INTERNET_TERMS = (
    "停掉第四台",
    "停用第四台",
    "取消第四台",
    "退掉第四台",
    "不要第四台",
    "停掉有線電視",
    "停用有線電視",
    "取消有線電視",
    "退掉有線電視",
    "不要有線電視",
)

KEEP_INTERNET_TERMS = (
    "保留網路",
    "只保留網路",
    "留網路",
    "網路保留",
    "只留網路",
)

CANCEL_TV_KEEP_INTERNET_REPLY = (
    "您好，若您希望停用有線電視服務並保留網路，"
    "將由文字客服專人協助確認您的服務內容及後續辦理方式，"
    "謝謝。"
)

CLEAR_CHANNEL_GROUP_TERM = "清冰組"


def is_clear_channel_group_query(text: str) -> bool:
    """Identify explicit questions about the pure-network gifted channels.

    This only selects the maintained knowledge entry. Customer-facing facts
    remain in the knowledge base so they can be updated without changing the
    router prompt or adding a fixed reply.
    """
    return CLEAR_CHANNEL_GROUP_TERM in normalize_text_width(text or "").strip()


def build_clear_channel_group_knowledge_decision(text: str) -> Dict[str, Any]:
    return build_knowledge_query_decision(
        intent="clear_channel_group_query",
        topic=CLEAR_CHANNEL_GROUP_TERM,
        knowledge_query=f"{CLEAR_CHANNEL_GROUP_TERM} {str(text or '').strip()}".strip(),
        reason="clear_channel_group_knowledge_rule",
    )

SPORTS_BROADCAST_EVENT_TERMS = (
    "世足",
    "世界盃",
    "世界杯",
    "FIFA",
    "fifa",
    "足球賽",
    "足球台",
)

SPORTS_BROADCAST_QUERY_TERMS = (
    "轉播",
    "播出",
    "哪裡看",
    "哪裡可以看",
    "哪個頻道",
    "在哪一台",
    "哪一台",
    "哪台",
    "幾台",
    "頻道",
)

FIXED_IP_KNOWLEDGE_TERMS = (
    "固定ip",
    "固定 ip",
)

FIXED_IP_ACTION_TERMS = (
    "幫我申請",
    "幫忙申請",
    "替我申請",
    "我要申請",
)

FIXED_IP_INFO_TERMS = (
    "費用",
    "多少",
    "服務",
    "提供",
    "設定",
    "綁定",
    "步驟",
    "方式",
    "怎麼",
    "如何",
    "地址",
    "申請",
)

HATV_ADDON_TERMS = (
    "哈tv",
    "哈TV",
    "line tv",
    "LINE TV",
)

ADDON_TERMS = (
    "加購",
    "套餐",
    "數位套餐",
)

ADDON_ACTION_TERMS = (
    "幫我加購",
    "幫忙加購",
    "替我加購",
    "我要加購",
    "直接加購",
    "幫我辦",
    "幫忙辦",
    "替我辦",
    "我要辦",
    "直接辦",
    "幫我申請",
    "幫忙申請",
    "替我申請",
    "我要申請",
)

ADDON_KNOWLEDGE_TERMS = (
    "內容",
    "費用",
    "收費",
    "月租",
    "價格",
    "價錢",
    "多少錢",
    "怎麼",
    "如何",
    "方式",
    "說明",
    "查詢",
    "有哪些",
)

APP_BILL_GUIDE_TERMS = (
    "哈tv行動客服怎麼查帳單",
    "哈TV行動客服怎麼查帳單",
    "行動客服怎麼查帳單",
    "app怎麼查帳單",
    "APP怎麼查帳單",
    "用app查帳單",
    "用APP查帳單",
)

BILL_CONTENT_QUERY_TERMS = (
    "查帳單",
    "查詢帳單",
    "帳單查詢",
    "帳單金額",
    "本期帳單",
    "本期帳單金額",
    "帳單內容",
    "帳單明細",
    "帳務查詢",
    "帳務內容",
    "費用明細",
    "帳款查詢",
    "應繳金額",
    "繳費金額",
)

DIRECT_FAULT_REPORT_TERMS = (
    "故障",
    "報故障",
    "報修",
    "維修",
    "線上報修",
    "我要報修",
    "回報故障",
    "回傳故障",
    "我要回報故障",
    "故障報修",
)

BILL_LOST_OR_PAYMENT_TERMS = (
    "帳單不見",
    "帳單遺失",
    "沒收到帳單",
    "沒有收到帳單",
    "超商可以印帳單",
    "如何繳費",
    "怎麼繳費",
)

PAYMENT_METHOD_QUERY_TERMS = (
    "繳費方式",
    "繳費方式查詢",
    "繳款方式",
    "繳款方式查詢",
    "付款方式",
    "付款方式查詢",
    "如何繳費",
    "怎麼繳費",
    "繳款管道",
    "付款管道",
    "線上繳費",
    "線上付款",
    "線上刷卡",
    "app繳費",
    "APP繳費",
    "App繳費",
    "哈TV行動客服APP繳費",
    "行動客服APP繳費",
    "linepay繳費",
    "LINEPay繳費",
    "LINE Pay繳費",
    "Line pay繳費",
    "信用卡怎麼繳",
    "信用卡繳費",
    "信用卡付款",
    "信用卡刷卡",
)

PAYMENT_METHOD_ACTION_TERMS = (
    "怎麼",
    "如何",
    "方式",
    "管道",
    "線上",
    "刷卡",
    "哪裡",
    "哪邊",
    "去哪",
    "哪裡繳",
    "哪邊繳",
)

PAYMENT_METHOD_SUBJECT_TERMS = (
    "繳費",
    "繳款",
    "付款",
    "付費",
    "繳帳單",
    "繳帳款",
)

CARD_AUTOPAY_BINDING_TERMS = (
    "信用卡",
    "刷卡",
    "扣繳",
    "自動扣款",
    "循環扣款",
)

CARD_AUTOPAY_BINDING_STATUS_TERMS = (
    "綁定",
    "設定",
    "申請",
    "成功",
    "確認",
    "查詢",
    "有沒有",
    "是否",
)

CONVENIENCE_STORE_PAYMENT_MACHINE_TERMS = (
    "超商繳費機",
    "超商機台",
    "便利商店機台",
    "便利商店繳費機",
    "ibon",
    "IBON",
    "FamiPort",
    "FAMIPORT",
    "famiport",
)

CONVENIENCE_STORE_PAYMENT_GUIDE_TERMS = (
    "操作",
    "教學",
    "怎麼",
    "如何",
    "流程",
    "步驟",
    "使用",
)

PAYMENT_METHOD_REPLY = (
    "目前可用繳費方式：\n"
    "1. 線上繳費／信用卡刷卡：至官方網站「線上繳費專區」，輸入用戶編號與密碼後依指示繳費。\n"
    "2. 臨櫃繳費：至公司櫃台辦理。\n"
    "3. APP 繳費：下載哈TV行動客服 APP，註冊或登入後依指示繳費。\n"
    "4. 超商繳費：持帳單條碼至 7-11 ibon、全家 FamiPort 等通路繳費。\n"
    "5. 其他代收通路：依帳單列示的金融機構或代收方式辦理。\n"
    "實際可用方式仍以帳單與客服確認為準。"
)

SMS_BILL_REGISTERED_PHONE_REPLY = (
    "簡訊帳單只能寄送到登記電話，無法改寄或指定寄送到其他電話。\n"
    "若要補發簡訊帳單，請提供戶名與登記電話供核對；"
    "若需變更登記電話，需由真人客服協助確認。"
)

TV_PASSWORD_PROMPT_REPLY = (
    "若機上盒畫面要求輸入密碼，請先輸入預設密碼「0000」。\n"
    "若輸入後顯示「未授權」，請先按頻道向下鍵切換至一般收視頻道確認。"
)
TV_UNAUTHORIZED_PAID_CHANNEL_REPLY = (
    "您可能誤按到需加購的付費頻道。200 台以後通常為付費頻道，需另行訂閱才能觀看。"
    "您可使用遙控器按頻道向下鍵，切換至正常收視頻道即可。"
)

SERVICE_ACCOUNT_TRANSFER_REPLY = (
    "【申請方式】\n"
    "資料未提供「第四台及光纖更換用戶」的具體流程或應備文件，"
    "需由客服依帳戶與合約狀態確認。"
)

AREA_REPAIR_STATUS_REPLY = (
    "目前線上無法即時確認特定路段或個案維修是否已完成，也不能直接判斷工程人員今天是否會到府。\n"
    "建議由真人客服依報修紀錄、地址與聯絡電話協助查詢最新維修進度。"
)

INVOICE_CARRIER_REPLY = (
    "您可以透過以下步驟在我們的官網完成發票手機條碼載具歸戶：\n"
    "1. 前往官方網站。\n"
    "2. 點擊「線上繳費」。\n"
    "3. 輸入您的帳號及密碼。\n"
    "4. 點擊「用戶歸戶」。\n"
    "5. 選擇「用戶歸戶2」。\n"
    "6. 連結至財政部網站進行歸戶操作。\n"
    "7. 確認後，輸入您的手機號碼及驗證碼。\n"
    "8. 最後點擊「確定」完成綁定。"
)
INVOICE_CARRIER_BINDING_CONFIRMATION_REPLY = "請問您是想將發票歸戶到手機條碼載具嗎？"
SERVICE_SUSPENSION_REPLY = (
    "若您說的「停機」是暫停服務／暫停收看，通常需由登記人辦理，並由客服確認目前合約、設備與費用狀態。\n"
    "暫停收視通常需保留至少 1 個月以上月租；3 個月內復機一般免收復機費，超過 3 個月復機費為 200 元。"
    "辦理方式以臨櫃為主，登記人需帶雙證件與印章；代辦則需雙方雙證件與印章。\n"
    "若您其實是要退租／終止服務，流程與費用會不同，需要另外由客服確認。"
)
CABLE_TV_TERMINATION_CALCULATION_REPLY = (
    "有線電視退租的費用或退費沒有固定公式，需依目前合約、繳別、已使用期間、"
    "帳務及設備歸還狀況確認；若仍在合約期間，提前解約可能產生違約金。\n"
    "退租請至服務櫃檯辦理，並攜帶身分證明、印章、機上盒及所有配件"
    "（遙控器、HDMI 線、AV 傳輸線與電源線）。\n"
    "本人可攜帶本人身分證正本或護照正本；若由他人代辦，需備妥代辦人與用戶雙方證件正本、"
    "印章及委託書。實際退費方式與金額請以櫃檯確認結果為準。"
)

CONTRACT_CHANGE_AFTER_TERMINATION_REPLY = (
    "不一定需要先退約再重新約定。\n"
    "若目前沒有合約，部分方案可直接申辦或換約；若合約尚未到期，中途換約或升級通常會將"
    "原剩餘合約期間加上新方案合約期間，而不是先退約重辦。\n"
    "若選擇提前退租或解約，可能會產生違約金。實際是否可換約、適用方案與新約期，"
    "仍需依目前合約狀態由客服確認。"
)

POINTS_USAGE_FALLBACK_REPLY = (
    "哈POINT 使用方式如下：\n"
    "- 哈POINT 1 點可折抵 1 元。\n"
    "- 可用於購買加值商品、折抵連線費與收視費。\n"
    "- 可透過哈TV行動客服 APP 查詢點數，並在線上刷卡繳費時折抵。\n"
    "- 也可持有行動客服 APP 的手機到櫃台折抵繳費。\n"
    "- 若已設定定期自動扣款，需提前聯絡客服申請點數抵扣。"
)

VALUE_ADDED_SERVICE_QUERY_TERMS = (
    "單品銷售",
    "熱門單品",
    "更多熱門單品",
    "加值服務",
    "加值套餐",
    "加值數位套餐",
    "數位電視套餐",
    "加值商品",
    "加購服務",
    "加購商品",
)

VALUE_ADDED_CATALOG_OVERVIEW_TERMS = (
    "更多熱門單品",
    "熱門單品",
    "單品銷售",
    "有哪些",
    "有什麼",
    "清單",
    "全部",
    "所有",
    "種類",
    "項目",
    "內容",
    "介紹",
)

VALUE_ADDED_ROUTER_HINTS = (
    "value_added",
    "value added",
    "add_on",
    "addon",
    "加值服務",
    "加值產品",
    "加購服務",
    "加值商品",
    "單品銷售",
    "額外服務",
)

VALUE_ADDED_SERVICE_CLARIFY_REPLY = (
    "請問您想了解哪一項加值服務？\n"
    "1. LINE TV\n"
    "2. WiFi 加值服務\n"
    "3. 居家智慧攝影機\n"
    "4. 熊搭心\n"
    "也可以回覆「全部」，查看目前可查詢的加值服務。"
)

VALUE_ADDED_SEMANTIC_RECHECK_RULES = """
你是客服意圖複判器。第一層路由目前無法確定使用者需求，請只判斷最新訊息是否在詢問
「既有有線電視／寬頻服務之外，可另外申請、租借、加購或付費使用的服務」，但尚未說出具體產品。

公司可查詢的加值服務包含 LINE TV、WiFi 加值服務、居家智慧攝影機、熊搭心。

請依整句語意判斷，不可只因單一字詞就成立：
- unspecified_value_added_service：想知道還有沒有其他可加購、額外付費或附加服務，但未指定產品。
- value_added_catalog：明確要求查看全部、清單、種類或有哪些加值服務。
- not_value_added_service：帳務、故障、核心有線電視／寬頻方案、申裝、退租、真人客服、閒聊，或仍無法合理確認。

只輸出 JSON：
{"classification":"unspecified_value_added_service|value_added_catalog|not_value_added_service","reason":"簡短理由"}
""".strip()

INVOICE_CARRIER_TERMS = (
    "載具歸戶",
    "發票載具",
    "發票號碼載具",
    "用戶歸戶",
    "設定載具",
    "載具設定",
    "重新綁定載具",
    "載具重新綁定",
    "發票加入手機條碼",
    "發票綁定手機條碼",
    "手機條碼歸戶",
    "手機條碼載具",
)

TERMINATION_FOLLOWUP_TERMS = (
    "就是結束",
    "結束",
    "不續約",
    "不要續約",
    "不續了",
    "不續",
    "停掉",
    "退租",
    "退掉",
    "取消服務",
)

TERMINATION_CONTEXT_TERMS = (
    "續約",
    "重新續約",
    "約滿",
    "合約",
    "到期",
    "方案",
    "訂購",
    "申辦",
)

SERVICE_SUSPENSION_TERMS = (
    "停機",
    "暫停機",
    "暫時中斷",
    "暫時停止",
    "暫停收視",
    "暫停收看",
    "暫停第四台",
    "暫停有線電視",
    "暫停網路",
    "暫停寬頻",
)

SERVICE_SUSPENSION_ACTION_TERMS = (
    "我要",
    "想要",
    "申請",
    "辦理",
    "如何",
    "怎麼",
    "流程",
    "方式",
    "要帶",
    "需要帶",
    "準備",
    "證件",
    "文件",
)

LOW_INCOME_DISABILITY_TERMS = (
    "低收入戶",
    "低收",
    "中低收入",
    "中低收",
    "殘障手冊",
    "身心障礙",
    "身障",
)

SOCIAL_DISCOUNT_NEGATION_TERMS = (
    "沒有低收",
    "沒低收",
    "沒有中低收",
    "沒中低收",
    "沒有低收入",
    "沒低收入",
    "沒有中低收入",
    "沒中低收入",
    "無法申請低收",
    "不能申請低收",
    "不符合低收",
    "低收過期",
    "低收入過期",
    "中低收過期",
    "中低收入過期",
    "沒有證明",
    "沒證明",
)

SOCIAL_DISCOUNT_ALTERNATIVE_PROMOTION_TERMS = (
    "其他優惠",
    "其他方案",
    "其他活動",
    "還有其他",
    "還有優惠",
    "現在有什麼優惠",
    "現在有甚麼優惠",
    "有什麼優惠",
    "有甚麼優惠",
    "一般優惠",
    "一般報價",
    "電視報價",
    "TV報價",
    "tv報價",
    "寬頻報價",
    "網路報價",
)

TV_AUTHORIZATION_TERMS = (
    "E004",
    "e004",
    "授權到期",
    "未授權",
    "沒有授權",
    "無授權",
    "只有四台可看",
    "只能看四台",
    "只剩四台",
    "只有4台可看",
    "只能看4台",
    "只剩4台",
)

APPLY_PLAN_TERMS = (
    "申請",
    "申辦",
    "辦理",
    "想辦",
    "我要辦",
    "我要申請",
    "我要申辦",
)

PROMOTION_APPLICATION_TERMS = (
    "優惠",
    "優惠方案",
    "優惠活動",
    "促銷",
)

PROMOTION_APPLICATION_SERVICE_TERMS = (
    "網路",
    "寬頻",
    "有線電視",
    "第四台",
    "電視",
    "300m",
    "300M",
    "500m",
    "500M",
    "100m",
    "100M",
)

CONTRACT_LOOKUP_TERMS = (
    "查詢合約",
    "查合約",
    "合約查詢",
    "我的合約",
    "合約",
    "目前服務",
    "服務內容",
)

MABOW_TERMS = (
    "瑪帛",
    "瑪柏",
    "熊搭心",
)

MABOW_ACTION_TERMS = (
    "申裝",
    "購買",
    "安裝",
    "設定",
    "使用",
    "鏡頭",
    "費用",
    "收費",
    "月租",
    "價格",
    "價錢",
    "多少錢",
    "怎",
    "如何",
)


def is_service_content_query(text: str) -> bool:
    compact = (text or "").replace(" ", "").replace("　", "")
    if not compact:
        return False

    video_service_terms = ("linetv", "LINETV", "LineTV", "LINE TV", "哈tv", "哈TV")
    expiry_terms = ("到期", "期限", "效期", "何時結束", "什麼時候結束")
    addon_package_terms = ("加值數位套餐", "數位套餐", "加值套餐", "加值服務")
    service_detail_terms = ("內容", "明細", "目前", "有哪些", "查詢")
    network_contract_terms = ("網路合約", "寬頻合約", "網路到期", "寬頻到期")
    speed_terms = ("申辦速率", "申請速率", "申辦網速", "網路速度", "網速")

    if any(term in compact for term in network_contract_terms):
        return True

    if any(term in compact for term in speed_terms) and any(
        term in compact for term in ("幾M", "幾m", "多少", "申辦", "申請", "目前", "現在")
    ):
        return True

    if any(term in compact for term in video_service_terms) and any(term in compact for term in expiry_terms):
        return True

    if any(term in compact for term in addon_package_terms) and (
        any(term in compact for term in expiry_terms)
        or any(term in compact for term in service_detail_terms)
    ):
        return True

    return False


def is_contract_lookup_request(text: str) -> bool:
    """Recognize a personal contract or current-plan request across active flows."""
    compact = (text or "").replace(" ", "").replace("　", "")
    if not compact:
        return False
    return any(
        term.replace(" ", "").replace("　", "") in compact
        for term in (
            *CONTRACT_LOOKUP_TERMS,
            *PERSONAL_ACCOUNT_QUERY_TERMS,
            *CURRENT_PLAN_QUERY_TERMS,
        )
    ) or is_service_content_query(text)


def is_personal_service_fee_lookup_query(text: str) -> bool:
    compact = (text or "").replace(" ", "").replace("　", "")
    if not compact:
        return False

    has_personal_subject = any(term.replace(" ", "").replace("　", "") in compact for term in PERSONAL_SERVICE_FEE_SUBJECT_TERMS)
    has_fee_target = any(term.replace(" ", "").replace("　", "") in compact for term in PERSONAL_SERVICE_FEE_TARGET_TERMS)
    if not (has_personal_subject and has_fee_target):
        return False

    return not any(term.replace(" ", "").replace("　", "") in compact for term in PERSONAL_SERVICE_FEE_EXCLUDE_TERMS)


def is_basic_tv_fee_query(text: str) -> bool:
    compact = (text or "").replace(" ", "").replace("　", "")
    if not compact:
        return False

    has_tv = any(term in compact for term in ("第四台", "有線電視", "基本收費", "純tv", "純TV"))
    has_fee = any(
        term in compact
        for term in ("一個月", "每月", "月租", "月費", "收視費", "多少錢", "費用", "收費", "價格", "價錢")
    )
    has_combo = any(term in compact for term in ("網路", "寬頻", "同裝", "電視加網路", "電視跟網路"))
    return has_tv and has_fee and not has_combo


def is_restricted_channel_purchase_query(text: str) -> bool:
    compact = (text or "").replace(" ", "").replace("　", "").lower()
    if not compact:
        return False
    has_restricted = any(term in compact for term in ("限制級", "成人頻道", "成人節目", "鎖碼頻道"))
    has_purchase = any(term in compact for term in ("購買", "加購", "訂購", "怎麼買", "如何買", "授權到期"))
    return has_restricted and has_purchase


def is_pure_tv_install_query(text: str) -> bool:
    compact = (text or "").replace(" ", "").replace("　", "")
    if not compact:
        return False
    has_tv = any(term in compact for term in ("有線電視", "第四台", "純TV", "純tv"))
    has_install = any(term in compact for term in ("裝機", "申裝", "申請", "新裝", "新申辦", "想裝", "要裝", "裝有線電視"))
    has_network = any(term in compact for term in ("網路", "寬頻", "同裝"))
    return has_tv and has_install and not has_network


def is_network_install_option_query(text: str) -> bool:
    compact = (text or "").replace(" ", "").replace("　", "")
    if not compact:
        return False
    if any(term in compact for term in NEW_INSTALL_FAULT_CONTEXT_TERMS):
        return False
    if compact in {
        "網路裝機申請",
        "寬頻裝機申請",
        "網路新裝申請",
        "寬頻新裝申請",
        "網路新裝機",
        "寬頻新裝機",
        "申請網路裝機",
        "申請寬頻裝機",
        "我要申請網路裝機",
        "我要申請寬頻裝機",
    }:
        return True
    has_network = any(term in compact for term in ("網路", "寬頻", "上網"))
    has_install = any(
        term in compact
        for term in (
            "裝機申請",
            "新裝申請",
            "申請裝機",
            "申請安裝",
            "網路裝機",
            "寬頻裝機",
            "新裝機",
            "申裝",
            "新申辦",
            "想裝",
            "安裝",
        )
    )
    has_tv = any(term in compact for term in ("有線電視", "第四台", "電視"))
    return has_network and has_install and not has_tv


def is_pure_network_plan_query(text: str) -> bool:
    compact = (text or "").replace(" ", "").replace("　", "")
    if not compact:
        return False
    has_network = any(term in compact for term in ("網路", "寬頻", "上網", "純網", "純寬頻"))
    wants_network_only = any(
        term in compact
        for term in (
            "只上網",
            "只要網路",
            "只裝網路",
            "單辦網路",
            "單裝網路",
            "單一網路",
            "單純網路",
            "單辦寬頻",
            "單裝寬頻",
            "純網",
            "純寬頻",
            "只有網路",
            "不用第四台",
            "不要第四台",
            "不含第四台",
            "不用有線電視",
            "不要有線電視",
            "不含有線電視",
        )
    )
    asks_plan_or_fee = any(
        term in compact
        for term in (
            "方案",
            "優惠",
            "費用",
            "收費",
            "多少錢",
            "月租",
            "價格",
            "價錢",
            "最便宜",
            "申請",
            "申辦",
            "裝機",
            "可以",
            "可不可以",
            "能不能",
            "嗎",
        )
    )
    return has_network and wants_network_only and asks_plan_or_fee


def is_tv_network_install_option_query(text: str) -> bool:
    compact = (text or "").replace(" ", "").replace("　", "")
    if not compact:
        return False
    if any(term in compact for term in NEW_INSTALL_FAULT_CONTEXT_TERMS):
        return False
    if compact in {"同時申裝有線網路", "同時申裝有線電視網路", "同時申裝電視網路"}:
        return True
    has_simultaneous_install = any(term in compact for term in ("同時申裝", "同時裝", "一起申裝", "一起裝", "同裝"))
    has_tv = any(term in compact for term in ("有線電視", "第四台", "電視", "有線"))
    has_network = any(term in compact for term in ("網路", "寬頻"))
    has_install = any(
        term in compact
        for term in ("裝機申請", "新裝申請", "申請裝機", "申裝", "新裝", "新申辦", "想裝", "要裝", "安裝")
    )
    has_existing_tv = has_tv and any(term in compact for term in ("已有", "已經有", "目前有", "本來有", "有裝"))
    has_add_network = has_network and any(term in compact for term in ("加裝", "加申請", "加辦", "申辦", "申請", "想裝", "要裝", "辦"))
    return (
        has_tv
        and has_network
        and (has_simultaneous_install or has_install or (has_existing_tv and has_add_network))
    )


def is_network_line_ownership_query(text: str) -> bool:
    compact = (text or "").replace(" ", "").replace("　", "")
    has_network = any(term in compact for term in ("網路", "寬頻", "光纖"))
    has_ownership = any(term in compact for term in ("獨立", "共用", "區域共用", "共享", "共線"))
    return has_network and has_ownership


def is_app_convenience_store_barcode_query(text: str) -> bool:
    compact = (text or "").replace(" ", "").replace("　", "").lower()
    has_app = "app" in compact or "行動客服" in compact
    has_store_barcode = any(term in compact for term in ("超商", "便利商店", "條碼", "barcode"))
    has_bill_payment = any(term in compact for term in ("繳費", "帳單", "待繳"))
    return has_app and has_store_barcode and has_bill_payment


def is_convenience_store_payment_failed_query(text: str) -> bool:
    compact = (text or "").replace(" ", "").replace("　", "")
    has_store = any(term in compact for term in ("便利商店", "超商", "ibon", "IBON", "FamiPort", "famiport"))
    has_payment = "繳費" in compact or "繳款" in compact
    has_failed = any(term in compact for term in ("無法", "不能", "不行", "繳不了", "沒辦法"))
    return has_store and has_payment and has_failed


def is_basic_vs_digital_channel_query(text: str) -> bool:
    compact = (text or "").replace(" ", "").replace("　", "")
    has_basic = any(term in compact for term in ("基本頻道", "一般頻道"))
    has_digital = any(term in compact for term in ("數位頻道", "數位電視", "數位套餐"))
    has_compare = any(term in compact for term in ("區別", "差別", "差異", "不同", "是什麼"))
    return has_basic and has_digital and has_compare


def is_outbound_call_lookup_query(text: str) -> bool:
    compact = (text or "").replace(" ", "").replace("　", "")
    has_call = any(term in compact for term in ("打電話給我", "來電", "打給我", "電話給我"))
    has_reason = any(term in compact for term in ("什麼事", "甚麼事", "原因", "為什麼", "幹嘛", "有什麼事"))
    return has_call and has_reason


def is_bare_line_tv_topic_query(text: str) -> bool:
    compact = (text or "").replace(" ", "").replace("　", "").lower()
    return compact in {"linetv", "line電視", "line-tv", "line_tv"} or compact == "linetv"


def is_stb_tutorial_stuck_query(text: str) -> bool:
    compact = (text or "").replace(" ", "").replace("　", "")
    has_box_or_tv = any(term in compact for term in ("機上盒", "電視盒", "電視"))
    has_tutorial = "教學" in compact
    has_stuck = any(term in compact for term in ("卡在", "一直卡", "停在", "一直停"))
    return has_box_or_tv and has_tutorial and has_stuck


def is_address_service_plan_lookup_query(text: str) -> bool:
    compact = (text or "").replace(" ", "").replace("　", "")
    has_address = "地址" in compact or "住址" in compact
    has_plan_or_speed = any(term in compact for term in ("網路速率", "速率", "速度", "目前方案", "方案", "網路方案"))
    has_lookup = any(term in compact for term in ("查", "查詢", "知道", "確認", "可以依"))
    return has_address and has_plan_or_speed and has_lookup


def is_contract_change_or_plan_switch_query(text: str) -> bool:
    compact = (text or "").replace(" ", "").replace("　", "")
    if any(term in compact for term in ("載具", "手機條碼", "發票")):
        return False
    has_contract_or_plan = any(term in compact for term in ("合約", "方案"))
    has_change = any(term in compact for term in ("轉換", "換約", "轉約", "轉方案", "更換方案", "換方案", "升級"))
    return has_contract_or_plan and has_change


def is_generic_fee_lookup_query(text: str) -> bool:
    compact = (text or "").replace(" ", "").replace("　", "")
    return compact in {"費用查詢", "查費用", "費用", "價格查詢", "價錢查詢"}


def is_next_tier_plan_fee_query(text: str) -> bool:
    compact = (text or "").replace(" ", "").replace("　", "")
    has_next_tier = any(term in compact for term in ("再高一階", "高一階", "升一階", "升級一階", "上一階"))
    has_fee = any(term in compact for term in ("多少錢", "費用", "月租", "差多少", "價格", "價錢"))
    return has_next_tier and has_fee


def is_existing_customer_speed_upgrade_eligibility_query(text: str) -> bool:
    """Whether an existing customer can upgrade is an account lookup, not a plan list."""
    compact = (text or "").replace(" ", "").replace("　", "")
    has_upgrade = any(term in compact for term in ("升級", "升速"))
    has_network_speed = any(term in compact for term in ("網速", "速率", "網路"))
    has_eligibility_question = any(
        term in compact
        for term in ("是否", "可否", "可以", "能否", "能不能", "可不可以", "可申請")
    )
    return (
        has_upgrade
        and has_network_speed
        and has_eligibility_question
        and not is_next_tier_plan_fee_query(text)
    )


def is_counter_service_account_transfer_hours_query(text: str) -> bool:
    """Match a counter-hours question that is part of a household-name change."""
    compact = (text or "").replace(" ", "").replace("　", "")
    has_transfer = any(term in compact for term in ("變更戶名", "變更用戶", "更換用戶", "換戶名", "過戶", "更名"))
    has_counter_time = any(
        term in compact
        for term in ("營業", "上班", "櫃台", "禮拜六", "星期六", "週六", "周六", "假日")
    )
    return has_transfer and has_counter_time


def build_counter_service_account_transfer_clarify_reply(memory: Dict[str, Any]) -> str:
    hours_reply = build_company_info_reply(
        "business_hours",
        memory.get("company_code", DEFAULT_TV_CABLE),
    )
    return (
        f"{hours_reply}\n"
        "若您要到櫃台辦理變更戶名，建議先確認需攜帶的證件與文件，避免白跑一趟。\n"
        "請問您要辦理有線電視更名還是寬頻網路更名？"
    )


def is_tv_only_promotion_query(text: str) -> bool:
    compact = (text or "").replace(" ", "").replace("　", "")
    has_tv_only = any(term in compact for term in ("只要裝有線電視", "只裝有線電視", "只申裝有線電視", "單辦有線電視", "有線電視"))
    has_promotion = any(term in compact for term in ("優惠", "方案", "活動", "促銷"))
    has_network = any(term in compact for term in ("網路", "寬頻", "哈net", "hanet"))
    return has_tv_only and has_promotion and not has_network


def is_broad_promotion_service_scope_query(text: str) -> bool:
    """Return true only when a promotion question lacks a service scope."""
    compact = (text or "").replace(" ", "").replace("　", "")
    if not compact:
        return False

    if any(term.replace(" ", "").replace("　", "") in compact for term in LOW_INCOME_DISABILITY_TERMS):
        return False

    if not any(term in compact for term in PROMOTION_QUERY_TERMS):
        return False

    has_explicit_scope = (
        is_tv_network_install_option_query(text)
        or any(term in text for term in COMBO_PLAN_TERMS)
        or is_pure_network_plan_query(text)
        or is_tv_only_promotion_query(text)
    )
    return not has_explicit_scope


def is_install_contact_or_quote_followup(text: str) -> bool:
    compact = (text or "").replace(" ", "").replace("　", "")
    if not compact:
        return False
    has_install = any(term in compact for term in ("裝機", "申裝", "申請裝", "新裝", "裝第四台", "裝有線電視", "裝網路"))
    has_contact_or_quote = any(term in compact for term in ("聯繫", "連繫", "聯絡", "連絡", "報價", "牽線", "估價", "請與我聯繫", "請跟我聯絡"))
    has_followup_context = any(term in compact for term in ("上週", "上周", "有過去看", "過去看", "現勘", "看我家", "我家那邊", "地址"))
    return has_install and has_contact_or_quote and has_followup_context


def is_network_fee_overdue_query(text: str) -> bool:
    compact = (text or "").replace(" ", "").replace("　", "")
    if not compact:
        return False
    has_network_fee = any(term in compact for term in ("網路費", "寬頻費", "網路帳單", "寬頻帳單"))
    has_overdue = any(term in compact for term in ("過期", "逾期", "超過期限", "忘記繳", "欠費"))
    return has_network_fee and has_overdue


def is_channel_number_gap_query(text: str) -> bool:
    compact = (text or "").replace(" ", "").replace("　", "").lower()
    if not compact:
        return False
    return any(term in compact for term in (
        "沒有500之後的頻道",
        "500之後沒有頻道",
        "輸入的頻道不存在",
        "頻道不存在",
        "頻道號不存在",
    ))


def is_two_set_top_box_monthly_total_query(text: str) -> bool:
    compact = (text or "").replace(" ", "").replace("　", "")
    if not compact:
        return False
    has_monthly = "月繳" in compact
    has_two_boxes = any(term in compact for term in ("二台機上盒", "兩台機上盒", "2台機上盒", "裝二台", "裝兩台"))
    has_total = any(term in compact for term in ("共要付", "總共", "合計", "多少錢", "多少"))
    return has_monthly and has_two_boxes and has_total


def is_hatv_addon_query(text: str) -> bool:
    compact = (text or "").replace(" ", "").replace("　", "")
    if not compact:
        return False
    return any(term.replace(" ", "").replace("　", "") in compact for term in HATV_ADDON_TERMS) and any(
        term.replace(" ", "").replace("　", "") in compact for term in ADDON_TERMS
    )


def detect_hatv_package_key(text: str) -> Optional[str]:
    compact = (text or "").replace(" ", "").replace("　", "").replace("-", "").lower()
    for key in ("a", "b", "c"):
        if f"{key}套餐" in compact or f"哈tv{key}套餐" in compact:
            return key.upper()
    return None


def is_addon_action_request(text: str) -> bool:
    compact = (text or "").replace(" ", "").replace("　", "")
    return any(term.replace(" ", "").replace("　", "") in compact for term in ADDON_ACTION_TERMS)


def is_addon_knowledge_query(text: str) -> bool:
    compact = (text or "").replace(" ", "").replace("　", "")
    if not is_hatv_addon_query(compact):
        return False
    return not is_addon_action_request(compact) or any(
        term.replace(" ", "").replace("　", "") in compact for term in ADDON_KNOWLEDGE_TERMS
    )


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


def validate_router_result(data: Dict[str, Any]) -> Dict[str, Any]:
    return RouterDecision.from_raw(
        data=data,
        supported_tools=SUPPORTED_TOOLS,
    ).to_router_dict()


def build_company_info_decision(info_type: str, reason: str) -> Dict[str, Any]:
    return validate_router_result({
        "route": "company_info",
        "intent": "company_info",
        "tool_name": None,
        "topic": info_type,
        "should_cancel_current_flow": False,
        "should_call_tool": False,
        "should_retrieve_knowledge": False,
        "knowledge_query": None,
        "reply": "",
        "extracted_slots": {},
        "reason": reason,
    })


def build_promotion_activity_decision(reason: str, knowledge_query: str = "優惠方案") -> Dict[str, Any]:
    decision = build_company_info_decision("promotion_activity", reason=reason)
    decision["should_retrieve_knowledge"] = True
    decision["knowledge_query"] = knowledge_query
    return validate_router_result(decision)


def build_direct_reply_decision(
    intent: str,
    topic: str,
    reply: str,
    reason: str,
) -> Dict[str, Any]:
    return validate_router_result({
        "route": "direct_reply",
        "intent": intent,
        "tool_name": None,
        "topic": topic,
        "should_cancel_current_flow": False,
        "should_call_tool": False,
        "should_retrieve_knowledge": False,
        "knowledge_query": None,
        "reply": reply,
        "extracted_slots": {},
        "reason": reason,
    })


def is_human_handoff_query(text: str) -> bool:
    value = (text or "").strip()
    if not value:
        return False
    compact = re.sub(r"\s+", "", value)
    return any(pattern in compact for pattern in HUMAN_HANDOFF_REQUEST_PATTERNS)


def has_human_handoff_issue_details(text: str) -> bool:
    """Return whether a handoff request includes an actual service issue."""
    compact = re.sub(r"\s+", "", str(text or ""))
    if not compact:
        return False

    issue_text = compact
    for pattern in (
        *HUMAN_HANDOFF_REQUEST_PATTERNS,
        *HUMAN_HANDOFF_CONFIRMATION_PATTERNS,
        "請幫我",
        "幫我",
        "請",
        "我要",
        "我想",
        "我不想跟ai講了",
        "不想跟ai講",
        "不要機器人",
        "不要ai",
        "客服",
        "真人",
        "人工",
        "專人",
        "處理",
        "轉接",
    ):
        issue_text = issue_text.replace(pattern, "")

    return any(
        term in issue_text
        for term in (
            "網路", "寬頻", "電視", "第四台", "收視", "頻道", "機上盒",
            "遙控器", "帳單", "帳務", "繳費", "發票", "合約", "帳號",
            "戶名", "更名", "退租", "停機", "裝機", "搬家", "報修",
            "故障", "斷線", "不能", "無法", "很慢", "費用", "優惠", "方案",
            "點數", "載具", "電子帳單", "紙本帳單", "更改電話", "變更電話", "修改電話",
        )
    )


def has_human_handoff_issue_context(memory: Optional[Dict[str, Any]]) -> bool:
    known_info = (memory or {}).get("known_info") or {}
    return known_info.get("human_handoff_issue_described") == "yes"


def has_human_handoff_triage_context(history: Optional[List[Dict[str, str]]] = None) -> bool:
    for message in reversed(history or []):
        if str(message.get("role") or "").lower() != "assistant":
            continue
        return HUMAN_HANDOFF_TRIAGE_REPLY in str(message.get("content") or "")
    return False


def is_personal_project_points_status_query(text: str) -> bool:
    """Identify a points entitlement that only staff can verify per account."""
    compact = re.sub(r"\s+", "", str(text or "")).casefold()
    if not compact:
        return False

    has_points = any(term in compact for term in ("點數", "point", "紅利"))
    has_project = any(term in compact for term in ("專案", "方案", "活動"))
    has_account_status = any(
        term in compact
        for term in (
            "未得到", "沒得到", "未收到", "沒收到", "沒拿到", "未入帳", "沒入帳",
            "未發放", "沒發放", "何時入帳", "何時發放", "資格", "入帳狀況",
        )
    )
    return has_points and has_project and has_account_status


def has_unresolved_handoff_context(history: Optional[List[Dict[str, str]]] = None) -> bool:
    """Allow a handoff only after the AI has stated the issue needs staff help."""
    for message in reversed(history or []):
        if str(message.get("role") or "").lower() != "assistant":
            continue
        reply = str(message.get("content") or "")
        return any(
            marker in reply
            for marker in (
                "目前我無法",
                "無法直接",
                "需由真人客服",
                "請由真人客服",
                "建議由真人客服",
            )
        )
    return False


def build_human_handoff_triage_decision(reason: str) -> Dict[str, Any]:
    return build_clarify_decision(
        intent="human_handoff_triage",
        topic="真人客服問題",
        reply=HUMAN_HANDOFF_TRIAGE_REPLY,
        reason=reason,
    )


def build_human_handoff_request_decision(
    reason: str,
    topic: str = "真人客服",
) -> Dict[str, Any]:
    return build_direct_reply_decision(
        intent="human_handoff_request",
        topic=topic,
        reply=WEB_HUMAN_HANDOFF_REPLY,
        reason=reason,
    )


def is_promotion_application_request(text: str) -> bool:
    value = text or ""
    compact = re.sub(r"\s+", "", value)
    normalized = compact.lower()
    has_apply = any(term in value for term in APPLY_PLAN_TERMS)
    has_promotion = any(term in value for term in PROMOTION_APPLICATION_TERMS)
    has_service = any(term.lower() in normalized for term in PROMOTION_APPLICATION_SERVICE_TERMS)
    return has_apply and has_promotion and has_service


def is_human_handoff_confirmation_query(text: str) -> bool:
    value = (text or "").strip()
    if not value:
        return False
    compact = re.sub(r"\s+", "", value)
    if any(term in compact for term in HUMAN_HANDOFF_CONTACT_INFO_TERMS):
        return False
    return any(pattern in compact for pattern in HUMAN_HANDOFF_CONFIRMATION_PATTERNS)


def normalize_human_handoff_confirmation_reply(text: str) -> str:
    return re.sub(r"[\s　。！!？?～~，,]+", "", str(text or "")).lower()


def is_human_handoff_confirmation_yes(text: str) -> bool:
    compact = normalize_human_handoff_confirmation_reply(text)
    if not compact or len(compact) > 8:
        return False
    return compact in HUMAN_HANDOFF_CONFIRM_YES_VALUES


def is_human_handoff_confirmation_no(text: str) -> bool:
    compact = normalize_human_handoff_confirmation_reply(text)
    if not compact or len(compact) > 8:
        return False
    return compact in HUMAN_HANDOFF_CONFIRM_NO_VALUES


def build_tool_action_decision(
    intent: str,
    tool_name: str,
    topic: str,
    reply: str,
    reason: str,
    extracted_slots: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    return validate_router_result({
        "route": "tool_action",
        "intent": intent,
        "tool_name": tool_name,
        "topic": topic,
        "should_cancel_current_flow": False,
        "should_call_tool": True,
        "should_retrieve_knowledge": False,
        "knowledge_query": None,
        "reply": reply,
        "extracted_slots": extracted_slots or {},
        "reason": reason,
    })


def build_knowledge_query_decision(
    intent: str,
    topic: str,
    knowledge_query: str,
    reason: str,
) -> Dict[str, Any]:
    return validate_router_result({
        "route": "knowledge_query",
        "intent": intent,
        "tool_name": None,
        "topic": topic,
        "should_cancel_current_flow": False,
        "should_call_tool": False,
        "should_retrieve_knowledge": True,
        "knowledge_query": knowledge_query,
        "reply": "",
        "extracted_slots": {},
        "reason": reason,
    })


def build_contextual_website_page_decision(text: str, reason: str) -> Dict[str, Any]:
    return build_knowledge_query_decision(
        intent="contextual_website_page_lookup",
        topic="官網頁面介紹",
        knowledge_query=f"{text} 官網 頁面 介紹 服務內容",
        reason=reason,
    )


VALUE_ADDED_PRODUCT_INFO_TERMS = (
    "多少錢",
    "多少",
    "價格",
    "費用",
    "收費",
    "月租",
    "月繳",
    "半年繳",
    "年繳",
    "一年",
    "押金",
    "賠償",
    "有哪些",
    "有什麼",
    "內容",
    "方案",
    "加值服務",
    "加購",
    "購買",
    "租借",
    "申辦",
    "申請",
    "規格",
    "差別",
    "是什麼",
    "介紹",
    "功能",
    "做什麼",
)

VALUE_ADDED_PRODUCT_FAULT_TERMS = (
    "不能用",
    "無法使用",
    "連不上",
    "斷線",
    "掉線",
    "不穩",
    "速度慢",
    "沒網路",
    "沒有網路",
    "訊號差",
    "燈號異常",
    "紅燈",
    "故障",
    "壞了",
    "lag",
    "延遲",
)

VALUE_ADDED_PRODUCT_PRICE_TERMS = (
    "多少錢",
    "多少",
    "價格",
    "費用",
    "收費",
    "月租",
    "月繳",
    "半年繳",
    "年繳",
    "押金",
    "賠償",
)


def build_clarify_decision(
    intent: str,
    topic: str,
    reply: str,
    reason: str,
) -> Dict[str, Any]:
    return validate_router_result({
        "route": "clarify",
        "intent": intent,
        "tool_name": None,
        "topic": topic,
        "should_cancel_current_flow": False,
        "should_call_tool": False,
        "should_retrieve_knowledge": False,
        "knowledge_query": None,
        "reply": reply,
        "extracted_slots": {},
        "reason": reason,
    })


def build_troubleshooting_decision(text: str, reason: str) -> Dict[str, Any]:
    return validate_router_result({
        "route": "troubleshooting",
        "intent": "troubleshooting",
        "tool_name": None,
        "topic": text,
        "should_cancel_current_flow": False,
        "should_call_tool": False,
        "should_retrieve_knowledge": False,
        "knowledge_query": None,
        "reply": "",
        "extracted_slots": {},
        "reason": reason,
    })


def extract_channel_name_from_query(text: str) -> Optional[str]:
    return normalize_channel_name_from_query(text)


def detect_sports_broadcast_query(text: str) -> Optional[Dict[str, Any]]:
    text = (text or "").strip()
    if not text:
        return None

    if not any(term in text for term in SPORTS_BROADCAST_EVENT_TERMS):
        return None

    if not any(term in text for term in SPORTS_BROADCAST_QUERY_TERMS):
        return None

    return build_knowledge_query_decision(
        intent="sports_broadcast_query",
        topic="世足賽轉播頻道",
        knowledge_query=f"2026 FIFA 世界盃足球賽 世足賽 轉播頻道 {text}",
        reason="sports_broadcast_knowledge_rule",
    )


def build_service_availability_reply(text: str, memory: Dict[str, Any]) -> str:
    context = memory.get("service_availability_context")
    if not isinstance(context, dict):
        context = resolve_service_availability_target(text)

    status = context.get("status")
    candidates = context.get("candidates") or []
    if status == "missing":
        profile = get_company_profile(memory.get("company_code") or DEFAULT_TV_CABLE)
        service_area = str(profile.get("service_area") or "").strip()
        first_area = next((item.strip() for item in service_area.split("、") if item.strip()), "")
        example = f"例如「{first_area}」" if first_area else "例如提供縣市與行政區"
        return (
            "可以，請提供想申裝地點的縣市與行政區，"
            f"{example}，我再幫您確認所屬服務區域。"
        )
    if status == "ambiguous":
        labels = [item.get("area") or item.get("matched_text") or item.get("company_name") for item in candidates]
        return (
            f"您這句提到「{'、'.join(label for label in labels if label)}」。"
            "請問實際想申裝的是哪一個地區？請回覆縣市與行政區，我再幫您確認。"
        )
    if status == "unmapped":
        location = str(context.get("location") or "該地區").strip()
        return (
            f"目前資料未列出「{location}」的服務範圍，因此無法直接確認能否施工。"
            "請提供完整裝機地址，由客服協助查詢線路與施工條件。"
        )

    target = context.get("target") or (candidates[0] if candidates else {})
    company_code = target.get("company_code")
    if not company_code:
        return "請提供想申裝地點的縣市與行政區，我再幫您確認所屬服務區域。"

    profile = get_company_profile(company_code)
    company = profile["company_name"]
    area = target.get("area")
    if area:
        return (
            f"您詢問的「{area}」屬於「{company}」目前列示的服務地區。"
            "實際能否安裝仍需以完整地址查詢線路與施工條件為準。"
        )

    return (
        f"{company}目前列示的服務地區是：{profile['service_area']}。"
        "若要確認特定地址是否可申辦，仍需要用完整地址由正式申裝查詢或客服確認，"
        "避免只用行政區誤判是否可施工。"
    )


def normalize_mabow_query(text: str) -> str:
    value = (text or "").strip().replace("瑪柏", "瑪帛")
    if "瑪帛電話" in value and "瑪帛電視電話" not in value:
        value = value.replace("瑪帛電話", "瑪帛電視電話")
    return value


def build_mabow_knowledge_decision(text: str, reason: str) -> Dict[str, Any]:
    query = normalize_mabow_query(text)
    compact_query = query.replace(" ", "").replace("　", "")
    product_only_terms = {"瑪帛", "瑪帛電視電話", "熊搭心"}

    if (
        compact_query in product_only_terms
        and not is_definition_query(query)
        and not any(term in compact_query for term in MABOW_ACTION_TERMS)
    ):
        query = f"什麼是{query}"

    return validate_router_result({
        "route": "knowledge_query",
        "intent": "mabow_knowledge",
        "tool_name": None,
        "topic": "瑪帛電視電話",
        "should_cancel_current_flow": False,
        "should_call_tool": False,
        "should_retrieve_knowledge": True,
        "knowledge_query": query,
        "reply": "",
        "extracted_slots": {},
        "reason": reason,
    })


def is_period_or_occasion_promotion_query(text: str) -> bool:
    compact = re.sub(r"\s+", "", str(text or ""))
    if not compact:
        return False

    has_occasion = any(term in compact for term in PROMOTION_DISCOVERY_OCCASION_TERMS)
    has_month = bool(re.search(r"(?<!\d)(?:1[0-2]|0?[1-9])月", compact)) or any(
        month in compact
        for month in (
            "一月", "二月", "三月", "四月", "五月", "六月",
            "七月", "八月", "九月", "十月", "十一月", "十二月",
        )
    )
    has_promotion = any(term in compact for term in PROMOTION_QUERY_TERMS) or any(
        term in compact for term in ("活動", "方案")
    )
    return has_promotion and (has_occasion or has_month)


def detect_promotion_activity_query(
    text: str,
    memory: Optional[Dict[str, Any]] = None,
) -> Optional[Dict[str, Any]]:
    text = (text or "").strip()
    memory = memory or {}
    known = memory.get("known_info", {})

    if not text:
        return None

    indexed_campaign = detect_indexed_campaign_activity_query(text, memory)
    if indexed_campaign:
        return indexed_campaign

    if memory.get("pending_tool") or known.get("troubleshooting_started") == "yes":
        return None

    if any(term in text for term in COMBO_PLAN_TERMS):
        return build_promotion_activity_decision(
            reason="direct_combo_plan_company_profile_rule",
            knowledge_query=(
                f"{text} 有線電視 網路 同裝 優惠方案 最新有效活動 "
                "方案名稱 活動期間 月租 速率 贈品"
            ),
        )

    if any(term in text for term in SPECIFIC_PROMOTION_QUERY_TERMS):
        return build_promotion_activity_decision(
            reason="direct_specific_promotion_query_company_profile_rule",
            knowledge_query=f"優惠方案 {text}",
        )

    if is_broad_promotion_service_scope_query(text):
        return build_clarify_decision(
            intent="promotion_service_scope_clarification",
            topic="優惠方案服務類型",
            reply=PROMOTION_SERVICE_SCOPE_CLARIFY_REPLY,
            reason="promotion_service_scope_clarification_rule",
        )

    has_promotion = any(term in text for term in PROMOTION_QUERY_TERMS)
    if is_period_or_occasion_promotion_query(text):
        return build_promotion_activity_decision(
            reason="direct_period_or_occasion_promotion_query_rule",
            knowledge_query=(
                f"{text} 優惠活動 節慶 活動期間 方案名稱 售價 速率 繳別 "
                "贈品 LINE TV POINTS 抽獎資格 抽獎獎項"
            ),
        )

    if has_promotion:
        return build_promotion_activity_decision(
            reason="direct_promotion_query_company_profile_rule",
            knowledge_query=(
                f"{text} 優惠方案 目前有效活動 完整方案 活動期間 方案名稱 "
                "適用對象 速率 月租 季繳 半年繳 年繳 綁約 裝機費 設備押金"
            ),
        )

    return None


def detect_indexed_campaign_activity_query(
    text: str,
    memory: Optional[Dict[str, Any]] = None,
) -> Optional[Dict[str, Any]]:
    text = (text or "").strip()
    if not text:
        return None

    try:
        from app.services.kb_service import match_active_campaign_alias

        campaign_match = match_active_campaign_alias(text, memory or {})
    except Exception:
        campaign_match = None

    if not campaign_match:
        return None

    campaign_name = campaign_match.get("campaign_name") or campaign_match.get("matched_alias") or text
    return build_promotion_activity_decision(
        reason="indexed_campaign_alias_rule",
        knowledge_query=f"{campaign_name} 優惠方案 {text}",
    )


def is_social_discount_alternative_promotion_query(text: str) -> bool:
    compact = (text or "").replace(" ", "").replace("　", "")
    if not compact:
        return False

    has_social_context = any(term.replace(" ", "").replace("　", "") in compact for term in LOW_INCOME_DISABILITY_TERMS)
    has_negation = any(term.replace(" ", "").replace("　", "") in compact for term in SOCIAL_DISCOUNT_NEGATION_TERMS)
    asks_alternative = any(
        term.replace(" ", "").replace("　", "") in compact
        for term in SOCIAL_DISCOUNT_ALTERNATIVE_PROMOTION_TERMS
    )
    return has_social_context and has_negation and asks_alternative


def is_low_income_500m_year_fee_query(text: str) -> bool:
    compact = (text or "").replace(" ", "").replace("　", "").lower()
    if not compact:
        return False
    has_low_income = any(term.replace(" ", "").replace("　", "").lower() in compact for term in LOW_INCOME_DISABILITY_TERMS)
    has_500m = "500m" in compact or "500M" in text
    has_year = any(term in compact for term in ("一年", "年費", "年繳", "一年多少", "一年是多少"))
    has_fee = any(term in compact for term in ("費用", "多少", "收費", "價格", "錢"))
    return has_low_income and has_500m and has_year and has_fee


def is_payment_method_query(text: str) -> bool:
    value = (text or "").strip()
    if not value:
        return False

    compact = value.replace(" ", "").replace("　", "")
    if any(term.replace(" ", "").replace("　", "") in compact for term in PAYMENT_METHOD_QUERY_TERMS):
        return True

    has_subject = any(term.replace(" ", "").replace("　", "") in compact for term in PAYMENT_METHOD_SUBJECT_TERMS)
    has_action = any(term.replace(" ", "").replace("　", "") in compact for term in PAYMENT_METHOD_ACTION_TERMS)
    return has_subject and has_action


def is_online_payment_account_help_query(text: str) -> bool:
    compact = (text or "").replace(" ", "").replace("　", "").lower()
    if not compact:
        return False
    if any(term in compact for term in ("查用戶編號", "查詢用戶編號", "查網路編號", "網路編號", "用戶編號在哪", "客戶編號在哪", "客編在哪")):
        return True
    has_online_payment = any(term in compact for term in ("線上繳費", "官網繳費", "app繳費", "網路繳費"))
    has_account_problem = any(term in compact for term in (
        "沒有註冊", "沒註冊", "用戶編號", "客戶編號", "客編", "帳號密碼", "忘記密碼", "密碼忘記", "收不到簡訊"
    ))
    return has_online_payment and has_account_problem


def is_speed_test_how_to_query(text: str) -> bool:
    compact = (text or "").replace(" ", "").replace("　", "")
    if not compact:
        return False
    if any(term in compact for term in ("測速結果", "Mbps", "mbps", "Mpbs", "速度只有", "只有")):
        return False
    explicit_speed_test = any(term in compact for term in ("測速", "測試網速", "網速測試", "測試寬頻", "寬頻測試"))
    how_to = any(term in compact for term in ("如何", "怎麼", "方法", "方式", "教學", "想知道", "要去哪", "哪裡"))
    return explicit_speed_test and how_to


def is_contextual_speed_test_how_to_query(text: str, history: List[Dict[str, str]]) -> bool:
    compact = (text or "").replace(" ", "").replace("　", "")
    if not compact:
        return False
    if is_speed_test_how_to_query(text):
        return True
    if compact not in {"想知道如何測試", "想知道怎麼測試", "如何測試", "怎麼測試", "要怎麼測試"}:
        return False
    recent = "".join(str(item.get("content") or "") for item in (history or [])[-6:])
    recent_compact = recent.replace(" ", "").replace("　", "")
    return any(term in recent_compact for term in ("測速", "測試網速", "網速測試", "寬頻速度", "網路速度"))


def is_basic_channel_table_query(text: str) -> bool:
    compact = (text or "").replace(" ", "").replace("　", "")
    if not compact:
        return False
    has_basic_channel = any(term in compact for term in ("基本頻道", "有線電視頻道", "第四台頻道"))
    has_list_question = any(term in compact for term in ("哪幾台", "哪些台", "頻道表", "可以看", "有哪些", "查詢"))
    return has_basic_channel and has_list_question


def is_online_payment_app_password_query(text: str) -> bool:
    compact = (text or "").replace(" ", "").replace("　", "")
    if not compact or "密碼" not in compact:
        return False
    return any(term in compact.lower() for term in ("線上繳費", "官網繳費", "網路繳費", "官方網站", "官網"))


def is_personal_monthly_fee_clarify_query(text: str) -> bool:
    compact = (text or "").replace(" ", "").replace("　", "")
    if not compact:
        return False

    monthly_terms = ("查詢月租", "查月租", "查月費", "月租多少", "月費多少")
    if not any(term in compact for term in monthly_terms):
        return False

    return not any(term in compact for term in (
        "帳單", "帳款", "合約", "方案", "優惠", "網路", "寬頻", "速率", "第四台", "有線電視", "頻道",
    ))


def is_bill_payment_deadline_query(text: str) -> bool:
    compact = (text or "").replace(" ", "").replace("　", "")
    if not compact:
        return False
    has_bill = any(term in compact for term in ("帳單", "帳款", "繳費", "繳款"))
    has_deadline = any(term in compact for term in ("截止日期", "截止日", "繳費期限", "繳款期限", "最晚幾號"))
    return has_bill and has_deadline


def is_credit_card_payment_method_query(text: str) -> bool:
    value = (text or "").strip()
    if not value:
        return False

    compact = value.replace(" ", "").replace("　", "")
    has_card = any(term in compact for term in ("信用卡", "刷卡"))
    has_payment_action = any(term in compact for term in ("怎麼繳", "如何繳", "怎麼付款", "如何付款", "繳費", "付款"))
    has_transitive_payment_request = bool(
        re.search(r"(?:信用卡|刷卡).{0,12}(?:繳|付).{0,12}(?:費用|帳單|帳款|月租)", compact)
        or re.search(r"(?:費用|帳單|帳款|月租).{0,12}(?:用|以)?(?:信用卡|刷卡).{0,12}(?:繳|付)", compact)
    )
    return has_card and (has_payment_action or has_transitive_payment_request)


def is_broadband_unlimited_query(text: str) -> bool:
    compact = (text or "").replace(" ", "").replace("　", "")
    if not compact:
        return False
    return any(term in compact for term in (
        "吃到飽",
        "不限流量",
        "流量無上限",
        "沒有流量限制",
        "有流量限制",
        "流量上限",
    ))


def is_price_complaint_query(text: str) -> bool:
    compact = (text or "").replace(" ", "").replace("　", "")
    if not compact:
        return False
    has_fee_subject = any(term in compact for term in ("收費", "費用", "價格", "月租", "費率"))
    has_complaint = any(term in compact for term in ("太貴", "那麼貴", "這麼貴", "很貴", "比較貴"))
    return has_fee_subject and has_complaint


def is_personal_contact_phone_change_query(text: str) -> bool:
    compact = (text or "").replace(" ", "").replace("　", "")
    if not compact:
        return False
    has_change = any(term in compact for term in ("更改", "變更", "修改", "更換", "改"))
    has_phone = any(term in compact for term in ("聯絡電話", "留存之聯絡電話", "留存電話", "手機門號", "門號", "電話"))
    return has_change and has_phone


def is_payment_not_posted_query(text: str) -> bool:
    compact = (text or "").replace(" ", "").replace("　", "")
    if not compact:
        return False
    has_paid = any(term in compact for term in ("已繳費", "已付款", "已刷卡", "刷卡繳費", "門市刷卡", "臨櫃繳費"))
    has_not_posted = any(term in compact for term in ("未沖帳", "沒沖帳", "尚未沖帳", "未入帳", "沒入帳", "尚未入帳"))
    return has_paid and has_not_posted


def last_bill_query_was_no_unpaid(memory: Optional[Dict[str, Any]] = None) -> bool:
    memory = memory or {}
    status = memory.get("last_bill_query_status")
    if isinstance(status, dict):
        if status.get("status") == "no_unpaid":
            return True
        message = str(status.get("message") or "")
        return "尚無須繳納" in message or "帳務狀況正常" in message

    result = memory.get("last_tool_result")
    if isinstance(result, dict) and result.get("tool_name") == "search_bill":
        data = result.get("data") or {}
        if data.get("bill_status") == "no_unpaid":
            return True
        message = str(result.get("message") or "")
        return "尚無須繳納" in message or "帳務狀況正常" in message

    return False


def is_monthly_fee_after_contract_lookup_query(
    text: str,
    memory: Optional[Dict[str, Any]] = None,
) -> bool:
    compact = (text or "").replace(" ", "").replace("　", "")
    if not compact or not any(term in compact for term in ("每月費用", "每月繳", "月費", "月繳費用")):
        return False

    memory = memory or {}
    if memory.get("last_tool") == "search_contract_info":
        return True
    result = memory.get("last_tool_result")
    return isinstance(result, dict) and result.get("tool_name") == "search_contract_info"


def is_next_bill_followup_query(text: str) -> bool:
    compact = (text or "").replace(" ", "").replace("　", "")
    if not compact:
        return False
    has_next_bill = any(term in compact for term in (
        "下期帳單",
        "下一期帳單",
        "下期帳款",
        "下一期帳款",
        "下個月帳單",
        "下月帳單",
        "下次帳單",
        "下次繳費",
        "下次繳款",
        "下次繳費時間",
        "下次繳款時間",
        "下一次繳費",
        "下一次繳款",
        "下期繳費",
        "下期繳款",
    ))
    has_question = any(term in compact for term in ("何時", "什麼時候", "甚麼時候", "多久", "幾號", "哪時", "查", "查詢", "會來", "會出", "產生"))
    return has_next_bill and (has_question or len(compact) <= 12)


def is_paid_but_bill_still_visible_query(text: str) -> bool:
    compact = (text or "").replace(" ", "").replace("　", "")
    if not compact:
        return False
    has_paid = any(term in compact for term in (
        "已繳費",
        "已繳",
        "繳了",
        "剛繳",
        "剛剛繳",
        "超商繳",
        "便利商店繳",
        "ibon繳",
        "famiport繳",
    ))
    has_bill = any(term in compact for term in ("帳單", "待繳", "未繳", "欠費", "費用"))
    has_still_visible = any(term in compact for term in (
        "還查得到",
        "還查的到",
        "還有",
        "仍有",
        "還是有",
        "還在",
        "怎麼還",
        "為什麼還",
        "為何還",
        "仍查到",
        "查到",
    ))
    return has_paid and has_bill and has_still_visible


def is_past_payment_or_posting_record_query(text: str) -> bool:
    compact = (text or "").replace(" ", "").replace("　", "")
    if not compact:
        return False
    if is_paid_but_bill_still_visible_query(text):
        return False
    if any(term in compact for term in (
        "過往繳費紀錄",
        "過去繳費紀錄",
        "歷史繳費紀錄",
        "繳費紀錄",
        "付款紀錄",
        "已繳費明細",
        "已繳明細",
        "繳費明細",
        "入帳紀錄",
        "入帳記錄",
        "入帳確認",
        "查入帳",
        "查詢入帳",
        "是否入帳",
        "有沒有入帳",
    )):
        return True

    has_paid = any(term in compact for term in ("已繳", "已付款", "已刷卡", "繳過", "付款"))
    has_record_subject = any(term in compact for term in ("資訊", "資料", "紀錄", "記錄", "明細", "帳單", "入帳"))
    return has_paid and has_record_subject


def is_tv_600_fee_clarify_query(text: str) -> bool:
    compact = (text or "").replace(" ", "").replace("　", "")
    if not compact:
        return False
    has_600 = "600" in compact
    has_month = any(term in compact for term in ("一個月", "每月", "月繳", "月費", "月租"))
    asks_briefly = len(compact) <= 14 or "??" in compact or "？" in compact or "?" in compact
    return has_600 and has_month and asks_briefly


def is_hatv_plus_youtube_query(text: str) -> bool:
    compact = (text or "").replace(" ", "").replace("　", "").lower()
    if not compact:
        return False
    has_hatv_plus = any(
        term in compact
        for term in (
            "hatv+",
            "哈tv+",
            "哈tvplus",
            "哈tvplus",
            "聯網機上盒",
            "4k雙模",
            "雙模機",
            "哈tv",
            "hatv",
        )
    )
    return has_hatv_plus and "youtube" in compact


def is_connected_stb_youtube_query(text: str) -> bool:
    compact = (text or "").replace(" ", "").replace("　", "").lower()
    if not compact:
        return False
    has_stb = any(term in compact for term in ("聯網機上盒", "雙模機", "4k雙模", "機上盒"))
    has_youtube = "youtube" in compact
    has_youtube_addon_context = has_youtube and any(term in compact for term in ("加值", "換裝", "收視", "能用", "可以用"))
    return (has_stb and has_youtube) or has_youtube_addon_context


def is_router_replacement_query(text: str) -> bool:
    compact = (text or "").replace(" ", "").replace("　", "")
    return "更換" in compact and any(term in compact for term in ("分享器", "wifi", "WiFi", "WIFI", "路由器"))


def is_new_network_equipment_registration_query(text: str) -> bool:
    compact = (text or "").replace(" ", "").replace("　", "")
    has_equipment_change = any(term in compact for term in ("更換新的設備", "更換新設備", "換新設備", "新設備", "更換設備"))
    has_network_failure = any(term in compact for term in ("無法上網", "不能上網", "連不上網", "無法連線"))
    return has_equipment_change and has_network_failure


def is_ambiguous_signal_instability_query(text: str) -> bool:
    compact = (text or "").replace(" ", "").replace("　", "")
    has_signal_issue = "訊號" in compact and any(term in compact for term in ("不穩", "不好", "異常"))
    has_service = any(term in compact for term in ("網路", "寬頻", "上網", "電視", "第四台", "機上盒"))
    return has_signal_issue and not has_service


def is_network_signal_instability_query(text: str) -> bool:
    compact = (text or "").replace(" ", "").replace("　", "")
    return (
        any(term in compact for term in ("網路", "寬頻", "上網"))
        and "訊號" in compact
        and any(term in compact for term in ("不穩", "不好", "異常"))
    )


def is_tv_signal_instability_repair_query(text: str) -> bool:
    compact = (text or "").replace(" ", "").replace("　", "")
    has_tv = any(term in compact for term in ("電視", "第四台", "機上盒"))
    has_instability = "訊號" in compact and any(term in compact for term in ("不穩", "不好", "異常"))
    has_network_available = any(term in compact for term in ("可以上網", "網路可以用", "網路正常", "網路沒問題"))
    return has_tv and has_instability and has_network_available


def is_ds_light_blinking_query(text: str) -> bool:
    compact = (text or "").replace(" ", "").replace("　", "").lower()
    return any(term in compact for term in ("ds燈", "ds灯")) and any(term in compact for term in ("閃爍", "一直閃", "閃"))


def is_general_channel_e004_query(text: str) -> bool:
    compact = (text or "").replace(" ", "").replace("　", "").lower()
    has_general_channel = any(term in compact for term in ("一般頻道", "基本頻道", "一般基本頻道"))
    has_error = any(term in compact for term in ("e004", "授權到期", "未授權", "無授權"))
    return has_general_channel and has_error


def is_online_payment_done_followup(text: str) -> bool:
    compact = (text or "").replace(" ", "").replace("　", "")
    return compact in {"是線上繳費", "線上繳費", "線上繳費的", "線上繳的", "線上付款", "APP繳費", "app繳費"}


def is_app_payment_receipt_query(text: str) -> bool:
    compact = (text or "").replace(" ", "").replace("　", "").lower()
    if not compact:
        return False
    has_app_or_online_payment = any(term in compact for term in ("app", "行動客服", "線上繳", "線上付款"))
    has_receipt_or_invoice = any(term in compact for term in ("收據", "發票", "實體收據", "紙本收據"))
    has_completion = any(term in compact for term in ("繳完", "繳費後", "繳完費", "付款後", "繳費"))
    return has_app_or_online_payment and has_receipt_or_invoice and has_completion


def is_half_year_online_payment_query(text: str) -> bool:
    compact = (text or "").replace(" ", "").replace("　", "")
    has_half_year = any(term in compact for term in ("半年繳", "繳半年", "半年"))
    has_online_payment = any(term.replace(" ", "").replace("　", "") in compact for term in ONLINE_PAYMENT_TERMS)
    return has_half_year and has_online_payment


def is_member_registration_query(text: str) -> bool:
    compact = (text or "").replace(" ", "").replace("　", "")
    return any(term in compact for term in ("註冊會員", "註冊帳號", "會員註冊", "如何註冊會員", "怎麼註冊會員"))


def is_cloud_account_app_usage_query(text: str) -> bool:
    compact = (text or "").replace(" ", "").replace("　", "").lower()
    if "雲端帳號" not in compact:
        return False
    return any(term in compact for term in ("登入", "使用", "協助", "怎麼", "如何", "不會", "無法"))


def is_tv_no_program_query(text: str) -> bool:
    compact = (text or "").replace(" ", "").replace("　", "")
    return any(term in compact for term in ("沒有節目", "沒節目", "沒有頻道", "沒頻道", "沒有台", "沒台"))


def is_set_top_box_relocation_payment_query(text: str) -> bool:
    compact = (text or "").replace(" ", "").replace("　", "")
    has_stb_move = any(term in compact for term in ("機上盒移機", "機上盒同地址移動", "機上盒同址移動", "同址移動"))
    has_pay = any(term in compact for term in ("如何付費", "怎麼付費", "付款", "收費", "費用"))
    return has_stb_move and (has_pay or compact in {"機上盒移機", "機上盒同地址移動", "機上盒同址移動", "同址移動"})


def is_wireless_network_acquisition_query(text: str) -> bool:
    compact = (text or "").replace(" ", "").replace("　", "")
    return any(term in compact for term in ("怎麼獲取無線網路", "如何獲取無線網路", "取得無線網路", "想要無線網路"))


def is_prepay_lookup_query(text: str) -> bool:
    compact = (text or "").replace(" ", "").replace("　", "")
    return compact in {"預繳", "預繳方式", "預繳費用", "預繳帳單"}


def is_network_outage_instability_query(text: str) -> bool:
    compact = (text or "").replace(" ", "").replace("　", "")
    if not compact:
        return False

    has_network_instability = any(
        term in compact
        for term in ("網路很不穩", "網路不穩", "網路不太穩", "連線不穩", "上網不穩")
    )
    asks_cause_or_outage = any(
        term in compact
        for term in ("發生什麼事", "怎麼回事", "是不是區域故障", "區域故障", "區故", "有公告", "查詢")
    )
    return has_network_instability and asks_cause_or_outage


def is_network_instability_short_query(text: str) -> bool:
    compact = (text or "").replace(" ", "").replace("　", "")
    has_network = any(term in compact for term in ("網路", "寬頻", "上網", "連線"))
    has_instability = any(term in compact for term in ("不順", "怪怪", "不太穩", "不穩", "斷斷續續"))
    return has_network and has_instability


def is_network_intermittent_fault_query(text: str) -> bool:
    compact = (text or "").replace(" ", "").replace("　", "")
    has_network = any(term in compact for term in ("網路", "寬頻", "上網", "連線", "訊號"))
    has_intermittent_symptom = any(
        term in compact for term in ("時有時無", "忽有忽無", "一下有一下沒有")
    )
    return has_network and has_intermittent_symptom


def is_wifi_router_password_query(text: str) -> bool:
    compact = (text or "").replace(" ", "").replace("　", "").lower()
    has_wifi = any(term in compact for term in ("wifi", "wi-fi", "無線網路", "分享器"))
    asks_password = "密碼" in compact and any(term in compact for term in ("忘", "怎麼", "如何", "查", "看", "改", "修改"))
    return has_wifi and asks_password


def is_tv_safe_mode_query(text: str) -> bool:
    compact = (text or "").replace(" ", "").replace("　", "").lower()
    return any(term in compact for term in ("安全模式", "safemode")) and any(
        term in compact for term in ("電視", "tv", "機上盒")
    )


def is_rebooted_all_channel_unavailable_query(text: str) -> bool:
    compact = (text or "").replace(" ", "").replace("　", "")
    has_rebooted = any(term in compact for term in ("已重開", "重開機過", "重新開機過", "已經重開", "重啟過"))
    has_all_channels = any(term in compact for term in ("全部頻道", "所有頻道", "全頻道", "每個頻道"))
    has_unavailable = any(term in compact for term in ("無法收視", "無法收看", "不能看", "不能收看", "看不到"))
    return has_rebooted and has_all_channels and has_unavailable


def is_virtual_hosting_query(text: str) -> bool:
    compact = (text or "").replace(" ", "").replace("　", "").lower()
    if not compact:
        return False

    return any(
        term in compact
        for term in (
            "虛擬主機",
            "網站主機",
            "網頁主機",
            "webhosting",
            "virtualhosting",
            "virtualhost",
        )
    )


def build_network_outage_instability_reply(memory: Optional[Dict[str, Any]] = None) -> str:
    memory = memory or {}
    profile = get_company_profile(memory.get("company_code") or memory.get("tv_cable") or DEFAULT_TV_CABLE)
    company = profile.get("company_name") or memory.get("company") or "目前系統台"
    outage = str(profile.get("area_outage") or "").strip()
    if outage:
        outage_text = f"目前{company}公告：{outage}"
    else:
        outage_text = f"目前{company}沒有區域故障公告。"
    return (
        f"{outage_text}\n"
        "若您家中網路仍持續不穩，我先帶您做簡單排除："
        "請將數據機電源拔掉約 10 秒後重新插上，等待 3 到 5 分鐘；"
        "再確認數據機燈號是否正常，並重新連線 Wi-Fi 或網路線。"
        "如果多台設備仍不穩，請回覆目前燈號狀態，我再協助您判斷是否需要報修。"
    )


def wants_promotion_gifts(text: str) -> bool:
    compact = (text or "").replace(" ", "").replace("　", "")
    return any(term in compact for term in ("贈品", "送什麼", "送甚麼", "送什麼東西", "送甚麼東西", "家電", "送電視", "送冰箱"))


def wants_promotion_full_content(text: str) -> bool:
    compact = (text or "").replace(" ", "").replace("　", "")
    return any(term in compact for term in ("是什麼方案", "是甚麼方案", "內容", "活動內容", "方案內容", "完整", "有哪些"))


def is_card_autopay_binding_status_query(text: str) -> bool:
    value = (text or "").strip()
    if not value:
        return False

    if is_card_autopay_application_query(value):
        return False

    compact = value.replace(" ", "").replace("　", "")
    has_card = any(term.replace(" ", "").replace("　", "") in compact for term in CARD_AUTOPAY_BINDING_TERMS)
    has_payment = any(term in compact for term in ("繳費", "繳款", "帳單", "帳務", "扣款"))
    has_status = any(term.replace(" ", "").replace("　", "") in compact for term in CARD_AUTOPAY_BINDING_STATUS_TERMS)
    return has_card and has_payment and has_status


def is_area_repair_status_query(text: str) -> bool:
    compact = (text or "").replace(" ", "").replace("　", "")
    if not compact:
        return False

    has_repair = any(term in compact for term in ("維修", "報修", "派工", "修復", "修好", "施工"))
    has_status_question = any(
        term in compact
        for term in ("好了嗎", "修好了嗎", "恢復了嗎", "完成了嗎", "進度", "今天會來", "會來維修", "何時會來")
    )
    has_location_or_schedule = (
        any(term in compact for term in ("路", "街", "巷", "弄", "號", "區", "地址"))
        or any(term in compact for term in ("今天", "明天", "下午", "上午", "晚上"))
    )
    return has_repair and has_status_question and has_location_or_schedule


def is_individual_repair_schedule_query(text: str) -> bool:
    compact = (text or "").replace(" ", "").replace("　", "")
    if not compact:
        return False

    has_repair = any(term in compact for term in ("維修", "報修", "派工", "工程", "師傅"))
    has_schedule = any(
        term in compact
        for term in ("今天會來", "會來維修", "何時會來", "幾點來", "什麼時候來", "派工時間", "到府")
    )
    return has_repair and has_schedule


def build_area_repair_status_reply(memory: Dict[str, Any], text: str = "") -> str:
    if is_individual_repair_schedule_query(text):
        return AREA_REPAIR_STATUS_REPLY

    profile = get_company_profile(memory.get("company_code") or memory.get("tv_cable") or DEFAULT_TV_CABLE)
    company = str(profile.get("company_name") or "").strip()
    outage = str(profile.get("area_outage") or "").strip()
    if not outage:
        return AREA_REPAIR_STATUS_REPLY

    company_prefix = f"{company}目前公告" if company else "目前公司公告"
    return (
        f"{company_prefix}：{outage}\n"
        "不過線上仍無法即時確認特定路段或個案維修是否已完成；"
        "若要確認最新進度，建議由真人客服依地址與聯絡電話協助查詢。"
    )


def is_contract_lookup_with_explicit_address(text: str) -> bool:
    compact = (text or "").replace(" ", "").replace("　", "")
    if not compact:
        return False

    has_contract = any(term in compact for term in ("合約", "服務內容", "目前服務"))
    # 「網路」也包含「路」字，不能把服務名稱誤認為地址。
    has_address = any(term in compact for term in ("地址", "住址", "街", "巷", "弄", "號", "樓"))
    return has_contract and has_address


def is_personal_billing_address_query(text: str) -> bool:
    compact = (text or "").replace(" ", "").replace("　", "")
    if not compact:
        return False
    has_bill = any(term in compact for term in ("帳單", "帳務", "收據"))
    has_delivery_address = any(term in compact for term in ("寄送地址", "寄件地址", "郵寄地址", "寄到哪", "寄去哪"))
    return has_bill and has_delivery_address


def is_contract_termination_request(text: str) -> bool:
    compact = (text or "").replace(" ", "").replace("　", "")
    if not compact:
        return False
    if any(term in compact for term in ("欠費", "未繳", "繳費")):
        return False
    has_contract = "合約" in compact or "約" in compact
    has_termination = any(term in compact for term in (
        "提前終止",
        "終止合約",
        "合約終止",
        "解約",
        "退租",
        "不續約",
        "不要續約",
        "取消服務",
        "停用服務",
    ))
    vague_stop_tv = any(term in compact for term in ("不想看了", "不看了", "不要看了"))
    return (has_contract and has_termination) or vague_stop_tv


def is_card_autopay_definition_query(text: str) -> bool:
    compact = (text or "").replace(" ", "").replace("　", "")
    if not compact:
        return False
    has_autopay = any(term in compact for term in ("循環扣款", "自動扣款", "自動扣繳", "信用卡扣款", "銀行帳戶扣款"))
    has_definition = any(term in compact for term in ("是什麼意思", "什麼意思", "是什麼", "意思", "代表什麼"))
    return has_autopay and has_definition


def is_online_payment_physical_receipt_query(text: str) -> bool:
    compact = (text or "").replace(" ", "").replace("　", "").lower()
    if not compact:
        return False
    has_online_payment = any(term.replace(" ", "").replace("　", "").lower() in compact for term in ONLINE_PAYMENT_TERMS)
    has_receipt = any(term in compact for term in ("實體收據", "紙本收據", "收據", "發票", "寄到家", "寄回家", "到家"))
    return has_online_payment and has_receipt


def is_line_tv_opening_query(text: str) -> bool:
    compact = (text or "").replace(" ", "").replace("　", "").lower()
    if not compact:
        return False
    if any(term in compact for term in ("最多", "幾台", "幾個裝置", "裝置數", "同時登入")):
        return False
    has_line_tv = any(term in compact for term in ("linetv", "line tv", "line電視"))
    has_opening = any(term in compact for term in ("開通", "啟用", "登入", "訂購", "加購", "申請", "怎麼用", "如何用"))
    return has_line_tv and has_opening


def is_mobile_casting_query(text: str) -> bool:
    compact = (text or "").replace(" ", "").replace("　", "")
    if not compact:
        return False
    return any(term in compact for term in ("手機投影電視", "手機投放電視", "手機鏡像電視", "手機投屏電視"))


def is_card_autopay_application_query(text: str) -> bool:
    value = (text or "").strip()
    if not value:
        return False

    compact = value.replace(" ", "").replace("　", "")
    status_query = any(term in compact for term in (
        "如何確認",
        "怎麼確認",
        "是否已",
        "有沒有",
        "查詢",
        "成功",
        "已經",
    ))
    if status_query:
        return False

    if "綁定信用卡" in compact:
        return True

    has_autopay = any(term in compact for term in ("自動扣款", "自動卡款", "信用卡扣繳", "信用卡自動扣款", "定期扣款"))
    has_application = any(term in compact for term in ("申請", "申請方式", "如何申請", "怎麼申請", "怎麼辦理", "辦理方式", "流程", "設定", "綁定", "辦"))
    return has_autopay and has_application


def is_identity_document_upload_query(text: str) -> bool:
    compact = (text or "").replace(" ", "").replace("　", "")
    if not compact:
        return False

    has_document = any(term in compact for term in ("身分證", "身份證", "雙證件", "證件"))
    has_upload_or_supplement = any(term in compact for term in ("上傳", "補件", "補交", "補資料", "補證件"))
    return has_document and has_upload_or_supplement


def is_convenience_store_payment_machine_query(text: str) -> bool:
    value = (text or "").strip()
    if not value:
        return False

    compact = value.replace(" ", "").replace("　", "")
    has_machine = any(
        term.replace(" ", "").replace("　", "") in compact
        for term in CONVENIENCE_STORE_PAYMENT_MACHINE_TERMS
    )
    has_payment_context = any(term in compact for term in ("繳費", "繳款", "付款", "帳單"))
    has_guide_intent = any(
        term.replace(" ", "").replace("　", "") in compact
        for term in CONVENIENCE_STORE_PAYMENT_GUIDE_TERMS
    )
    return (has_machine or ("超商" in compact and has_payment_context)) and has_guide_intent


def is_set_top_box_multi_fee_query(text: str) -> bool:
    value = (text or "").strip()
    if not value:
        return False

    compact = value.replace(" ", "").replace("　", "").lower()
    has_device = any(
        term.replace(" ", "").replace("　", "").lower() in compact
        for term in SET_TOP_BOX_MULTI_FEE_DEVICE_TERMS
    )
    has_count_context = any(
        term.replace(" ", "").replace("　", "").lower() in compact
        for term in SET_TOP_BOX_MULTI_FEE_COUNT_TERMS
    )
    has_cost_context = any(
        term.replace(" ", "").replace("　", "").lower() in compact
        for term in SET_TOP_BOX_MULTI_FEE_COST_TERMS
    )
    return has_device and has_count_context and has_cost_context


def is_three_set_top_box_half_year_query(text: str) -> bool:
    compact = (text or "").replace(" ", "").replace("　", "").lower()
    return (
        is_set_top_box_multi_fee_query(text)
        and any(term in compact for term in ("3台", "三台", "第三台"))
        and any(term in compact for term in ("半年繳", "繳半年", "半年費用", "半年多少"))
    )


def is_triple_play_bill_item_query(text: str) -> bool:
    compact = (text or "").replace(" ", "").replace("　", "")
    if not compact or "三合一" not in compact:
        return False

    bill_context_terms = (
        "帳單",
        "帳務",
        "帳款",
        "繳費項目",
        "收費項目",
        "費用項目",
        "繳費內容",
        "收費內容",
        "是哪三種",
        "哪三種",
        "三種",
    )
    return any(term in compact for term in bill_context_terms)


def is_sms_bill_registered_phone_policy_query(text: str, memory: Optional[Dict[str, Any]] = None) -> bool:
    compact = (text or "").replace(" ", "").replace("　", "")
    if not compact:
        return False

    memory = memory or {}
    in_sms_bill_flow = memory.get("pending_tool") == "send_message" or memory.get("last_tool") == "send_message"
    has_sms_bill_context = any(term in compact for term in (
        "簡訊帳單",
        "帳單簡訊",
        "帳單訊息",
        "補寄帳單",
        "補發帳單",
        "補寄繳費帳單",
        "補發繳費帳單",
        "補寄繳費單",
        "補發繳費單",
        "未收到帳單",
        "沒收到帳單",
    ))
    has_bill_resend_request = any(term in compact for term in (
        "補寄帳單",
        "補發帳單",
        "補寄繳費帳單",
        "補發繳費帳單",
        "補寄繳費單",
        "補發繳費單",
        "補發簡訊帳單",
        "補寄簡訊帳單",
    ))
    looks_like_customer_number = compact.isdigit() and len(compact) >= 5
    has_redirect_request = any(term in compact for term in (
        "改寄",
        "改傳",
        "改發",
        "改送",
        "寄到",
        "傳到",
        "發到",
        "送到",
        "指定電話",
        "指定號碼",
        "這個號碼",
        "那個號碼",
        "另一支",
        "別支",
        "換電話",
        "換號碼",
    ))
    asks_destination = any(term in compact for term in (
        "寄到哪",
        "寄去哪",
        "哪一個電話",
        "哪個電話",
        "哪支電話",
        "哪一個號碼",
        "哪個號碼",
        "哪支號碼",
    ))
    if in_sms_bill_flow and (has_sms_bill_context or looks_like_customer_number):
        return True
    if has_bill_resend_request:
        return True
    return (in_sms_bill_flow or has_sms_bill_context) and (has_redirect_request or asks_destination)


def is_online_payment_activation_query(text: str) -> bool:
    compact = (text or "").replace(" ", "").replace("　", "").lower()
    if not compact:
        return False
    has_online_payment = any(term.replace(" ", "").replace("　", "").lower() in compact for term in ONLINE_PAYMENT_TERMS)
    has_activation = any(term in compact for term in ("開通", "恢復", "馬上", "立即", "自動", "多久", "何時"))
    return has_online_payment and has_activation


def is_value_added_service_query(text: str) -> bool:
    compact = (text or "").replace(" ", "").replace("　", "")
    if any(term in compact for term in ("加值數位套餐內容", "數位套餐內容")):
        return False
    return bool(compact) and any(term.replace(" ", "").replace("　", "") in compact for term in VALUE_ADDED_SERVICE_QUERY_TERMS)


def is_value_added_catalog_overview_query(text: str) -> bool:
    compact = (text or "").replace(" ", "").replace("　", "")
    return bool(compact) and any(term in compact for term in VALUE_ADDED_CATALOG_OVERVIEW_TERMS)


def should_clarify_unspecified_value_added_service(
    text: str,
    router: Optional[Dict[str, Any]] = None,
) -> bool:
    """Clarify a semantic add-on request only when no concrete product is known."""
    value = normalize_text_width(text or "").strip()
    if not value or detect_value_added_product_keys(value):
        return False

    if is_value_added_catalog_overview_query(value):
        return False

    router = router or {}
    route = str(router.get("route") or "")
    if route not in {"knowledge_query", "clarify"}:
        return False

    semantic_context = " ".join(
        str(router.get(field) or "")
        for field in ("intent", "topic", "knowledge_query", "reason")
    ).lower()
    return any(hint.lower() in semantic_context for hint in VALUE_ADDED_ROUTER_HINTS)


def is_generic_uncertain_router_result(router: Optional[Dict[str, Any]]) -> bool:
    """Return True only when the primary router did not establish a useful intent."""
    router = router or {}
    if str(router.get("route") or "") not in {"unknown", "clarify"}:
        return False

    intent = str(router.get("intent") or "other").strip().lower()
    return intent in {
        "",
        "other",
        "unknown",
        "clarify",
        "ambiguous",
        "ambiguous_request",
        "unclear_request",
        "general_inquiry",
    }


def recheck_value_added_service_semantically(
    user_input: str,
    history_text: str,
    router: Dict[str, Any],
    llm,
) -> Optional[Dict[str, Any]]:
    """Use a focused LLM recheck when the primary router remains uncertain.

    This intentionally avoids a keyword gate: the fallback exists for natural
    requests such as "還有沒有其他可以另外付費使用的東西" where none of the
    product names appear in the message.
    """
    if not is_generic_uncertain_router_result(router):
        return None

    prompt = ChatPromptTemplate.from_template(
        "{rules}\n\n"
        "最近對話（僅供代名詞與上下文判斷）：\n{history_text}\n\n"
        "使用者最新訊息：\n{user_input}\n"
    )
    try:
        response = (prompt | llm).invoke({
            "rules": VALUE_ADDED_SEMANTIC_RECHECK_RULES,
            "history_text": history_text,
            "user_input": user_input,
        })
        data = safe_json_loads(getattr(response, "content", ""))
    except Exception:
        return None

    classification = str(data.get("classification") or "").strip().lower()
    if classification == "unspecified_value_added_service":
        return build_clarify_decision(
            intent="value_added_service_clarification",
            topic="加值服務",
            reply=VALUE_ADDED_SERVICE_CLARIFY_REPLY,
            reason="semantic_recheck_unspecified_value_added_service",
        )
    if classification == "value_added_catalog":
        return build_knowledge_query_decision(
            intent="value_added_service_query",
            topic="加值服務",
            knowledge_query=(
                f"{user_input} 加值服務 單品銷售 LINE TV WiFi 加值服務 "
                "居家智慧攝影機 熊搭心 月租 費用 申請方式"
            ),
            reason="semantic_recheck_value_added_catalog",
        )
    return None


def is_value_added_service_followup_query(text: str, memory: Optional[Dict[str, Any]] = None) -> bool:
    compact = (text or "").replace(" ", "").replace("　", "")
    if not compact:
        return False

    asks_addon_package = any(term in compact for term in ("加值數位套餐", "數位套餐", "數位電視套餐"))
    asks_detail = any(term in compact for term in ("內容", "有哪些", "項目", "清單", "費用", "價格", "月租"))
    if not (asks_addon_package and asks_detail):
        return False

    memory = memory or {}
    recent_texts: List[str] = []
    for doc in (memory.get("last_knowledge_results") or [])[:4]:
        if isinstance(doc, dict):
            recent_texts.extend(str(doc.get(field) or "") for field in ("question", "title", "answer", "category"))
            source = doc.get("source")
            if isinstance(source, dict):
                recent_texts.extend(str(source.get(field) or "") for field in ("title", "source", "content"))

    recent = "".join(recent_texts).replace(" ", "").replace("　", "")
    if not recent:
        return False

    return any(term in recent for term in ("各項單品銷售", "單品銷售", "熱門單品", "加值服務", "數位電視套餐"))


def infer_recent_campaign_topic(memory: Optional[Dict[str, Any]] = None) -> Optional[str]:
    memory = memory or {}
    known = memory.get("known_info") if isinstance(memory.get("known_info"), dict) else {}
    remembered_topic = str(
        memory.get("last_campaign_topic")
        or known.get("last_campaign_topic")
        or ""
    )
    if remembered_topic.strip():
        return remembered_topic.strip()

    for doc in (memory.get("last_knowledge_results") or [])[:5]:
        if not isinstance(doc, dict):
            continue
        source = doc.get("source")
        campaign_name = str(
            doc.get("campaign_name")
            or (source.get("campaign_name") if isinstance(source, dict) else "")
            or ""
        ).strip()
        if campaign_name:
            return campaign_name

    return None


def detect_promotion_followup_detail_query(
    text: str,
    memory: Optional[Dict[str, Any]] = None,
) -> Optional[Dict[str, Any]]:
    compact = (text or "").replace(" ", "").replace("　", "")
    if not compact:
        return None

    # A new month/holiday discovery question starts a fresh campaign search. It
    # must not inherit the previous campaign merely because it contains words
    # such as "有哪些" or "活動".
    if is_period_or_occasion_promotion_query(text):
        return None

    topic = infer_recent_campaign_topic(memory)
    if not topic:
        return None

    if not any(term.replace(" ", "").replace("　", "") in compact for term in PROMOTION_FOLLOWUP_DETAIL_TERMS):
        return None

    if any(term in compact for term in ("總共費用", "總費用", "總金額", "合計", "裝到好")):
        detail_terms = "售價 速率 月繳 季繳 半年繳 年繳 裝機費 設備押金 押金"
    elif any(term in compact.upper() for term in ("LINETV", "LITV")) or any(
        term in compact for term in ("贈幾個月", "送幾個月")
    ):
        detail_terms = "LINE TV LITV 贈送月數 到期"
    elif any(term in compact.upper() for term in ("POINT", "POINTS")) or "點數" in compact:
        detail_terms = "POINT POINTS 點數 月繳 季繳 半年繳 年繳 贈點規則"
    elif any(term in compact for term in ("抽獎", "中獎")):
        detail_terms = "抽獎資格 抽獎方式 抽獎獎項 中獎"
    elif any(term in compact for term in ("違約金", "綁約")):
        detail_terms = "綁約期間 違約金 逐月遞減"
    elif any(term in compact for term in ("活動期間", "到何時", "到什麼時候", "到哪時候", "優惠期限", "活動期限")):
        detail_terms = "活動期間 開始日期 結束日期"
    elif any(term in compact for term in ("如何申請", "怎麼申請", "怎麼辦理", "申請方式")):
        detail_terms = "申請方式 裝機申告 客服協助 辦理流程"
    elif any(term in compact for term in ("裝機費", "設備押金", "押金")):
        detail_terms = "裝機費 設備押金 押金 月繳 季繳 半年繳 年繳"
    else:
        detail_terms = "活動方案 贈品 家電 配送 保固 壁掛"

    return build_knowledge_query_decision(
        intent="promotion_followup_detail",
        topic=topic,
        knowledge_query=f"{topic} {detail_terms} {text}",
        reason="recent_campaign_followup_detail_rule",
    )


def is_invoice_carrier_query(text: str) -> bool:
    compact = (text or "").replace(" ", "").replace("　", "").replace("從新", "重新")
    if not compact:
        return False
    if any(term.replace(" ", "").replace("　", "") in compact for term in INVOICE_CARRIER_TERMS):
        return True
    return "載具" in compact and any(term in compact for term in ("換約", "綁", "歸戶", "手機條碼", "發票"))


def build_invoice_carrier_reply_for_query(text: str) -> str:
    compact = (text or "").replace(" ", "").replace("　", "").replace("從新", "重新")
    if any(term in compact for term in ("換約", "重新綁定", "載具重新綁定")):
        return (
            "若您是換約後要重新綁定發票載具，是否需要重新綁定仍需依帳戶狀態確認。\n\n"
            f"{INVOICE_CARRIER_REPLY}"
        )
    return INVOICE_CARRIER_REPLY


def is_points_usage_query(text: str) -> bool:
    compact = (text or "").replace(" ", "").replace("　", "").casefold()
    if not compact:
        return False
    has_points = any(term in compact for term in ("哈point", "紅利點數", "point點數", "紅利"))
    has_usage = any(term in compact for term in ("怎麼用", "如何使用", "能如何使用", "用途", "兌換", "抵扣", "購買", "可以用"))
    return has_points and has_usage


def is_campaign_points_query(text: str) -> bool:
    compact = (text or "").replace(" ", "").replace("　", "").casefold()
    if not compact:
        return False

    has_points = any(term in compact for term in ("哈point", "紅利點數", "point點數", "point", "points", "點數"))
    if not has_points:
        return False

    has_campaign_reference = any(
        term in compact
        for term in (
            "這個方案",
            "該方案",
            "方案",
            "優惠",
            "活動",
        )
    )
    has_gift_question = any(
        term in compact
        for term in ("贈幾點", "送幾點", "贈多少點", "送多少點", "贈點", "送點", "點數送多少")
    )
    has_payment_gift_rule = any(term in compact for term in ("月繳", "季繳", "半年繳", "年繳")) and any(
        term in compact for term in ("贈", "送")
    )
    return has_campaign_reference or has_gift_question or has_payment_gift_rule


def is_points_overview_query(text: str) -> bool:
    compact = (text or "").replace(" ", "").replace("　", "").casefold()
    if not compact or is_campaign_points_query(text):
        return False

    # Canonical service names should start a fresh general points lookup even
    # when the previous turn discussed a promotion. A vague follow-up such as
    # "點數呢" is intentionally left to the campaign follow-up resolver.
    return any(term in compact for term in ("哈point", "紅利點數", "point點數"))


def is_refund_calculation_query(text: str) -> bool:
    compact = (text or "").replace(" ", "").replace("　", "")
    if not compact or "退費" not in compact:
        return False
    return any(
        term in compact
        for term in ("解約", "退租", "終止", "取消", "合約到期", "已繳", "繳費", "機制", "計算", "怎麼退")
    )


def is_overdue_disconnection_query(text: str) -> bool:
    compact = (text or "").replace(" ", "").replace("　", "")
    if not compact:
        return False
    has_payment_problem = any(term in compact for term in ("忘了繳費", "未繳", "欠費", "逾期"))
    has_disconnection = any(term in compact for term in ("斷訊", "斷線", "被斷", "停訊", "停用", "不能看", "不能上網"))
    return has_payment_problem and has_disconnection


def is_restore_before_payment_request(text: str) -> bool:
    compact = (text or "").replace(" ", "").replace("　", "")
    has_restore = any(
        term in compact
        for term in ("恢復", "復線", "復訊", "開通", "先幫我恢復", "先恢復", "先復線", "先復訊")
    )
    has_later_payment = any(
        term in compact
        for term in ("晚點去繳", "晚點繳", "等一下繳", "還沒繳", "尚未繳", "未繳", "再繳費", "後繳費")
    )
    return has_restore and has_later_payment


def build_service_termination_query_decision(reason: str) -> Dict[str, Any]:
    return build_knowledge_query_decision(
        intent="service_termination_process",
        topic="退租流程",
        knowledge_query="退租 終止服務 取消服務 不續約 約滿 結束 合約 退租流程 設備歸還",
        reason=reason,
    )


def build_service_suspension_query_decision(reason: str) -> Dict[str, Any]:
    return build_direct_reply_decision(
        intent="service_suspension_process",
        topic="暫停機流程",
        reply=SERVICE_SUSPENSION_REPLY,
        reason=reason,
    )


def is_service_suspension_query(text: str) -> bool:
    compact = (text or "").replace(" ", "").replace("　", "")
    if not compact:
        return False
    if any(term in compact for term in ("欠費", "未繳", "忘了繳費", "繳費")):
        return False

    has_suspension = any(
        term.replace(" ", "").replace("　", "") in compact
        for term in SERVICE_SUSPENSION_TERMS
    )
    if not has_suspension:
        return False

    return any(
        term.replace(" ", "").replace("　", "") in compact
        for term in SERVICE_SUSPENSION_ACTION_TERMS
    )


def is_ambiguous_service_stop_query(text: str) -> bool:
    compact = (text or "").replace(" ", "").replace("　", "")
    if not compact or any(term in compact for term in ("欠費", "未繳", "忘了繳費", "繳費")):
        return False
    has_ambiguous_stop = any(term in compact for term in ("停用", "停止服務", "取消網路", "取消寬頻"))
    has_service = any(term in compact for term in ("網路", "寬頻", "光纖", "有線電視", "第四台"))
    has_explicit_termination = any(term in compact for term in ("退租", "終止", "解約", "不續約"))
    return has_ambiguous_stop and has_service and not has_explicit_termination


def is_service_termination_query(text: str) -> bool:
    compact = (text or "").replace(" ", "").replace("　", "")
    if not compact:
        return False
    if any(term in compact for term in ("欠費", "未繳", "忘了繳費", "繳費")):
        return False
    if any(term.replace(" ", "").replace("　", "") in compact for term in CANCEL_TV_KEEP_INTERNET_TERMS) and any(
        term.replace(" ", "").replace("　", "") in compact for term in KEEP_INTERNET_TERMS
    ):
        return False
    explicit_terms = ("退租", "退掉", "不續約", "不要續約", "不續了", "停掉", "取消服務", "終止服務", "停用服務")
    if any(term.replace(" ", "").replace("　", "") in compact for term in explicit_terms):
        return True
    service_stop_terms = ("停用", "暫停", "停止", "取消")
    service_subject_terms = ("網路", "寬頻", "光纖", "有線電視", "第四台")
    return (
        any(term in compact for term in service_stop_terms)
        and any(term in compact for term in service_subject_terms)
    )


def is_service_termination_followup(text: str, history: List[Dict[str, str]]) -> bool:
    compact = (text or "").replace(" ", "").replace("　", "")
    if not compact or not any(term.replace(" ", "").replace("　", "") == compact for term in TERMINATION_FOLLOWUP_TERMS):
        return False
    recent = "".join(str(m.get("content") or "") for m in (history or [])[-6:])
    recent_compact = recent.replace(" ", "").replace("　", "")
    return any(term.replace(" ", "").replace("　", "") in recent_compact for term in TERMINATION_CONTEXT_TERMS)


def is_bill_content_query(text: str) -> bool:
    value = (text or "").strip()
    if not value:
        return False

    compact = value.replace(" ", "").replace("　", "")

    if any(term.replace(" ", "").replace("　", "") in compact for term in APP_BILL_GUIDE_TERMS):
        return False

    if is_payment_method_query(value):
        return False

    if any(term.replace(" ", "").replace("　", "") in compact for term in BILL_LOST_OR_PAYMENT_TERMS):
        return False

    if any(term.replace(" ", "").replace("　", "") in compact for term in BILL_CONTENT_QUERY_TERMS):
        return True

    has_bill_subject = "帳單" in compact or "帳務" in compact or "帳款" in compact
    has_query_action = any(term in compact for term in ("查", "查詢", "詢問", "看", "確認"))
    has_content_target = any(term in compact for term in ("內容", "明細", "金額", "本期", "費用"))
    return has_bill_subject and has_query_action and has_content_target


def is_bill_amount_difference_query(text: str) -> bool:
    compact = (text or "").replace(" ", "").replace("　", "")
    if not compact:
        return False
    has_bill = any(term in compact for term in ("帳單", "帳務", "帳款", "金額", "費用"))
    has_previous_period = any(term in compact for term in ("上一期", "上期", "上個月", "上月", "前一期", "上次"))
    has_difference = any(term in compact for term in ("不一樣", "不同", "差異", "差很多", "變多", "變少", "比較貴", "比較便宜", "為什麼"))
    return has_bill and has_previous_period and has_difference


def is_unsupported_bill_detail_query(text: str) -> bool:
    compact = (text or "").replace(" ", "").replace("　", "")
    if not compact:
        return False
    has_bill_subject = any(term in compact for term in ("帳單", "帳務", "帳款", "繳費"))
    has_unsupported_detail = any(term in compact for term in (
        "繳費起訖",
        "繳費起迄",
        "起訖日",
        "起迄日",
        "起訖",
        "起迄",
        "帳單期間",
        "帳務期間",
        "帳款期間",
        "費用期間",
    ))
    return has_bill_subject and has_unsupported_detail


def build_bill_content_query_decision(reason: str) -> Dict[str, Any]:
    return build_tool_action_decision(
        intent="bill_query",
        tool_name="search_bill",
        topic="帳單查詢",
        reply="可以，我幫您查詢帳單。",
        reason=reason,
    )


def detect_promotion_price_difference_query(
    text: str,
    memory: Optional[Dict[str, Any]] = None,
) -> Optional[Dict[str, Any]]:
    text = (text or "").strip()
    memory = memory or {}
    known = memory.get("known_info", {})
    compact = text.replace(" ", "").replace("　", "")

    if not text:
        return None

    if memory.get("pending_tool") or known.get("troubleshooting_started") == "yes":
        return None

    has_subject = any(term in compact for term in PROMOTION_PRICE_DIFFERENCE_TERMS)
    has_comparison = any(term in compact for term in PROMOTION_PRICE_COMPARISON_TERMS)
    mentions_price = any(term in compact for term in ("便宜", "貴", "價格", "費用", "費率", "收費", "優惠"))

    if has_subject and (has_comparison or mentions_price):
        return build_direct_reply_decision(
            intent="promotion_price_difference",
            topic="優惠費率差異",
            reply=PROMOTION_PRICE_DIFFERENCE_REPLY,
            reason="direct_promotion_price_difference_rule",
        )

    return None


def detect_cancel_tv_keep_internet_query(
    text: str,
    memory: Optional[Dict[str, Any]] = None,
) -> Optional[Dict[str, Any]]:
    text = (text or "").strip()
    memory = memory or {}
    known = memory.get("known_info", {})
    compact = text.replace(" ", "").replace("　", "")

    if not text:
        return None

    if memory.get("pending_tool") or known.get("troubleshooting_started") == "yes":
        return None

    if (
        any(term in compact for term in CANCEL_TV_KEEP_INTERNET_TERMS)
        and any(term in compact for term in KEEP_INTERNET_TERMS)
    ):
        return build_direct_reply_decision(
            intent="cancel_tv_keep_internet",
            topic="停用有線電視保留網路",
            reply=CANCEL_TV_KEEP_INTERNET_REPLY,
            reason="direct_cancel_tv_keep_internet_rule",
        )

    return None


def detect_fixed_ip_knowledge_query(
    text: str,
    memory: Optional[Dict[str, Any]] = None,
) -> Optional[Dict[str, Any]]:
    value = normalize_text_width(text).strip()
    compact = value.lower().replace(" ", "").replace("　", "")
    memory = memory or {}
    known = memory.get("known_info", {})

    if not value:
        return None

    if memory.get("pending_tool") or known.get("troubleshooting_started") == "yes":
        return None

    if "固定ip" not in compact:
        return None

    if (
        any(term in compact for term in FIXED_IP_ACTION_TERMS)
        and not any(term in value for term in ("怎麼", "如何", "方式", "步驟"))
    ):
        return None

    if any(term in value.lower() for term in FIXED_IP_KNOWLEDGE_TERMS) or any(
        term in value for term in FIXED_IP_INFO_TERMS
    ):
        return build_knowledge_query_decision(
            intent="fixed_ip_knowledge",
            topic="固定 IP",
            knowledge_query=value,
            reason="fixed_ip_knowledge_rule",
        )

    return None


def detect_casting_detail_followup(
    text: str,
    history: List[Dict[str, str]],
) -> Optional[Dict[str, Any]]:
    """Keep a short device reply attached to the preceding casting question."""
    value = normalize_text_width(text).strip().lower().replace(" ", "")
    if value not in {"電視", "電視機", "智慧電視", "不知道", "不清楚"}:
        return None

    recent_assistant = " ".join(
        str(item.get("content") or "")
        for item in (history or [])[-4:]
        if item.get("role") == "assistant"
    )
    normalized_recent = recent_assistant.lower().replace(" ", "")
    has_casting_context = any(
        term in normalized_recent
        for term in ("投屏", "投放", "鏡像", "chromecast", "airplay", "miracast")
    )
    asked_for_device_detail = any(
        term in normalized_recent
        for term in ("品牌", "型號", "支援")
    )
    if not (has_casting_context and asked_for_device_detail):
        return None

    return build_direct_reply_decision(
        intent="tv_casting_device_clarification",
        topic="電視投屏功能確認",
        reply=(
            "了解，請再提供電視的品牌與型號；若不確定型號，也可以查看機身背面標籤。\n"
            "確認型號後，才能判斷是否支援 Chromecast、AirPlay、Miracast 或螢幕鏡像功能。"
        ),
        reason="casting_detail_followup_context_rule",
    )


def detect_troubleshooting_execution_followup(
    text: str,
    history: List[Dict[str, str]],
) -> Optional[Dict[str, Any]]:
    compact = (text or "").replace(" ", "").replace("　", "")
    if compact not in {"如何執行", "怎麼執行", "如何排錯", "怎麼排錯", "協助排錯"}:
        return None

    recent = "".join(str(m.get("content") or "") for m in (history or [])[-6:])
    has_troubleshooting_offer = "簡單排錯" in recent or "排錯" in recent
    has_network_instability_context = any(
        term in recent
        for term in ("網路很不穩", "網路不穩", "網路不太穩", "連線不穩", "上網不穩")
    )
    if not has_troubleshooting_offer and not has_network_instability_context:
        return None

    if any(term in recent for term in ("網路", "寬頻", "上網", "連線")):
        return build_direct_reply_decision(
            intent="network_simple_troubleshooting_steps",
            topic="網路簡易排除",
            reply=NETWORK_SIMPLE_TROUBLESHOOTING_REPLY,
            reason="history_network_troubleshooting_execution_followup",
        )

    if any(term in recent for term in ("電視", "第四台", "頻道", "機上盒")):
        return build_troubleshooting_decision("電視不能收看", "history_tv_troubleshooting_execution_followup")

    return build_troubleshooting_decision(text, "history_troubleshooting_execution_followup")


def detect_network_outage_instability_followup(
    text: str,
    history: List[Dict[str, str]],
    memory: Optional[Dict[str, Any]] = None,
) -> Optional[Dict[str, Any]]:
    compact = (text or "").replace(" ", "").replace("　", "")
    if compact not in {"查詢", "查一下", "幫我查", "幫我查詢", "查區故", "查區域故障"}:
        return None

    recent = "".join(str(m.get("content") or "") for m in (history or [])[-6:])
    recent_compact = recent.replace(" ", "").replace("　", "")
    has_network_instability = any(
        term in recent_compact
        for term in ("網路很不穩", "網路不穩", "網路不太穩", "連線不穩", "上網不穩")
    )
    has_outage_context = any(term in recent_compact for term in ("發生什麼事", "區域故障", "區故", "無公告"))
    if not (has_network_instability and has_outage_context):
        return None

    return build_direct_reply_decision(
        intent="network_outage_instability_check",
        topic="網路不穩與區域故障",
        reply=build_network_outage_instability_reply(memory),
        reason="history_network_outage_instability_followup_rule",
    )


def detect_virtual_hosting_followup(
    text: str,
    history: List[Dict[str, str]],
) -> Optional[Dict[str, Any]]:
    compact = (text or "").replace(" ", "").replace("　", "").lower()
    if not compact:
        return None

    asks_virtual_detail = compact in {
        "服務內容",
        "服務內容?",
        "服務內容？",
        "費用",
        "價格",
        "價錢",
        "月租",
        "介紹",
        "官網",
        "官方網站",
        "網站",
        "申請方式",
        "辦理方式",
        "怎麼申請",
        "如何申請",
        "怎麼辦理",
        "如何辦理",
    } or any(term in compact for term in ("服務內容", "費用", "價格", "申請", "辦理", "官網", "網站", "介紹"))
    if not asks_virtual_detail:
        return None

    recent = "".join(str(m.get("content") or "") for m in (history or [])[-6:])
    if not is_virtual_hosting_query(recent):
        return None

    return build_direct_reply_decision(
        intent="unsupported_virtual_hosting_service",
        topic="虛擬主機",
        reply=VIRTUAL_HOSTING_UNSUPPORTED_REPLY,
        reason="history_virtual_hosting_unsupported_rule",
    )


def detect_remote_repair_followup(
    text: str,
    history: List[Dict[str, str]],
) -> Optional[Dict[str, Any]]:
    compact = (text or "").replace(" ", "").replace("　", "")
    if compact not in {"回報故障", "報修", "報故障", "我要報修", "我要回報故障"}:
        return None

    recent = "".join(str(m.get("content") or "") for m in (history or [])[-6:])
    if not any(term in recent for term in ("遙控器", "遙控", "搖控器", "搖控")):
        return None

    return build_direct_reply_decision(
        intent="remote_control_issue",
        topic="遙控器故障",
        reply=(
            "了解，前面提到的是遙控器故障。請先確認按遙控器時是否有亮紅燈；"
            "若沒有亮燈，請先更換電池後再測試。若有亮燈但無法操作，請檢查機上盒 IR 接收器是否亮燈或脫落，並重啟機上盒。\n"
            "若仍無法使用，可能需要更換遙控器：一般型 300 元、語音型 400 元，可臨櫃購買；實際型號與費用仍以客服確認為準。"
        ),
        reason="history_remote_repair_followup_rule",
    )


def detect_connected_stb_youtube_followup(
    text: str,
    history: List[Dict[str, str]],
) -> Optional[Dict[str, Any]]:
    compact = (text or "").replace(" ", "").replace("　", "").lower()
    recent = "".join(str(m.get("content") or "") for m in (history or [])[-8:])
    recent_compact = recent.replace(" ", "").replace("　", "").lower()
    if "youtube" not in compact and compact not in {"聯網機上盒", "雙模機"}:
        return None
    if not any(term in recent_compact for term in ("聯網機上盒", "雙模機", "hatv可以使用youtube", "哈tv可以使用youtube")):
        return None
    return build_direct_reply_decision(
        intent="connected_stb_youtube",
        topic="聯網機上盒 YouTube",
        reply=CONNECTED_STB_YOUTUBE_REPLY,
        reason="history_connected_stb_youtube_followup_rule",
    )


def detect_value_added_option_selection_followup(
    text: str,
    history: List[Dict[str, str]],
) -> Optional[Dict[str, Any]]:
    compact = (text or "").replace(" ", "").replace("　", "")
    if compact not in {"2", "２", "第二個", "第2個", "選2"}:
        return None

    recent = "".join(str(m.get("content") or "") for m in (history or [])[-6:])
    recent_compact = recent.replace(" ", "").replace("　", "")
    has_value_added_options = (
        "1.LINETV" in recent_compact
        and "2.WiFi加值服務" in recent_compact
        and "3.居家智慧攝影機" in recent_compact
    )
    if not has_value_added_options:
        return None

    return build_direct_reply_decision(
        intent="wifi_value_added_service",
        topic="WiFi 加值服務",
        reply=WIFI_VALUE_ADDED_SERVICE_REPLY,
        reason="history_value_added_option_2_wifi_rule",
    )


def detect_general_channel_e004_followup(
    text: str,
    history: List[Dict[str, str]],
) -> Optional[Dict[str, Any]]:
    compact = (text or "").replace(" ", "").replace("　", "").lower()
    if compact not in {
        "一般頻道",
        "一般頻道的",
        "基本頻道",
        "基本頻道的",
        "一般基本頻道",
        "一般基本頻道的",
    }:
        return None

    recent = "".join(str(m.get("content") or "") for m in (history or [])[-8:])
    recent_compact = recent.replace(" ", "").replace("　", "").lower()
    if not any(term in recent_compact for term in ("e004", "授權到期", "未授權", "無授權")):
        return None

    return build_clarify_decision(
        intent="general_channel_e004_temp_restore_clarify",
        topic="一般頻道 E004",
        reply=GENERAL_CHANNEL_E004_REPLY,
        reason="history_general_channel_e004_temp_restore_clarify_rule",
    )


def detect_cnt_seasonal_authorization_followup(
    text: str,
    history: List[Dict[str, str]],
    memory: Optional[Dict[str, Any]] = None,
) -> Optional[Dict[str, Any]]:
    compact = (text or "").replace(" ", "").replace("　", "")
    if not any(term in compact for term in ("授權過期", "授權到期", "E004", "未授權", "無授權", "不能收視", "無法收視")):
        return None

    memory = memory or {}
    known = memory.get("known_info", {}) or {}
    company_code = str(memory.get("company_code") or memory.get("tv_cable") or "").lower()
    recent = "".join(str(m.get("content") or "") for m in (history or [])[-8:])
    recent_compact = recent.replace(" ", "").replace("　", "")
    has_cnt_context = company_code == "cnt" or any(term in recent for term in ("中投", "中投有線"))
    has_customer_context = (
        str(known.get("custnum") or memory.get("custnum") or "") == "609741"
        or "609741" in recent_compact
    )
    has_seasonal_context = any(term in recent_compact for term in ("季繳", "HBO", "hbo", "第四台", "有線電視"))
    if not (has_cnt_context and has_customer_context and has_seasonal_context):
        return None

    return build_direct_reply_decision(
        intent="cnt_seasonal_authorization_paid",
        topic="中投季繳授權與 HBO 優惠",
        reply=CNT_SEASONAL_AUTHORIZATION_REPLY,
        reason="history_cnt_seasonal_authorization_paid_rule",
    )


def detect_tv_only_promotion_followup(
    text: str,
    history: List[Dict[str, str]],
) -> Optional[Dict[str, Any]]:
    compact = (text or "").replace(" ", "").replace("　", "")
    has_promotion_followup = any(term in compact for term in ("優惠", "方案", "活動", "促銷", "多少錢", "費用"))
    if not has_promotion_followup:
        return None

    recent = "".join(str(m.get("content") or "") for m in (history or [])[-6:])
    recent_compact = recent.replace(" ", "").replace("　", "")
    has_tv_only_context = any(
        term in recent_compact
        for term in ("只要裝有線電視", "只裝有線電視", "只申裝有線電視", "單辦有線電視", "只要第四台")
    )
    if not has_tv_only_context:
        return None

    return build_knowledge_query_decision(
        intent="pure_tv_promotion_query",
        topic="單辦有線電視優惠",
        knowledge_query=f"{PURE_TV_INSTALL_KNOWLEDGE_QUERY} {text}",
        reason="history_pure_tv_promotion_knowledge_rule",
    )


def detect_overdue_reconnection_service_selection_followup(
    text: str,
    history: List[Dict[str, str]],
) -> Optional[Dict[str, Any]]:
    compact = (text or "").replace(" ", "").replace("　", "")
    if compact not in {"電視", "第四台", "有線電視", "網路", "寬頻"}:
        return None

    recent = "".join(str(m.get("content") or "") for m in (history or [])[-8:])
    recent_compact = recent.replace(" ", "").replace("　", "")
    has_overdue_restore_context = any(
        term in recent_compact
        for term in ("忘了繳費已被斷訊", "欠費斷訊", "逾期停訊", "先幫我恢復", "晚點去繳", "未完成繳費前")
    )
    if not has_overdue_restore_context:
        return None

    if compact in {"電視", "第四台", "有線電視"}:
        return build_tool_action_decision(
            intent="reconnection",
            tool_name="bill_return_line_tv",
            topic="電視復線",
            reply="可以，我先協助確認電視復線。若 API 已帶入登入客戶資料可直接查詢；否則請提供客戶編號、戶名、登記電話任兩項。",
            reason="history_overdue_reconnection_tv_selection_rule",
        )

    return build_tool_action_decision(
        intent="reconnection",
        tool_name="bill_return_line_internet",
        topic="網路復線",
        reply="可以，我先協助確認網路復線。若 API 已帶入登入客戶資料可直接查詢；否則請提供客戶編號、戶名、登記電話任兩項。",
        reason="history_overdue_reconnection_network_selection_rule",
    )


def detect_sms_bill_customer_number_followup(
    text: str,
    history: List[Dict[str, str]],
) -> Optional[Dict[str, Any]]:
    compact = (text or "").replace(" ", "").replace("　", "")
    if not (compact.isdigit() and len(compact) >= 5):
        return None

    recent_messages = list((history or [])[-6:])
    has_direct_sms_request = any(
        m.get("role") == "user"
        and any(
            term in str(m.get("content") or "").replace(" ", "").replace("　", "")
            for term in (
                "補發簡訊帳單",
                "補寄簡訊帳單",
                "補發繳費帳單",
                "補寄繳費帳單",
                "補發帳單",
                "補寄帳單",
            )
        )
        for m in recent_messages
    )
    has_sms_policy_reply = any(
        m.get("role") == "assistant"
        and any(
            term in str(m.get("content") or "").replace(" ", "").replace("　", "")
            for term in (
                "簡訊帳單只能寄送",
                "登記電話",
            )
        )
        for m in recent_messages
    )
    if not (has_direct_sms_request or has_sms_policy_reply):
        return None

    return build_direct_reply_decision(
        intent="sms_bill_registered_phone_policy",
        topic="簡訊帳單登記電話",
        reply=SMS_BILL_REGISTERED_PHONE_REPLY,
        reason="history_sms_bill_customer_number_followup_rule",
    )


def detect_payment_clarify_option_followup(
    text: str,
    history: List[Dict[str, str]],
) -> Optional[Dict[str, Any]]:
    compact = (text or "").replace(" ", "").replace("　", "")
    if compact not in {"1", "１", "第一個", "第1個", "繳費方式"}:
        return None

    recent = "".join(str(m.get("content") or "") for m in (history or [])[-4:])
    if "查詢繳費方式" not in recent or "確認是否繳費成功" not in recent:
        return None

    return build_direct_reply_decision(
        intent="bill_payment_methods",
        topic="繳費方式",
        reply=PAYMENT_METHOD_REPLY,
        reason="history_payment_clarify_option_1_rule",
    )


def has_sms_bill_context_from_history(history: List[Dict[str, str]]) -> bool:
    recent = "".join(str(m.get("content") or "") for m in (history or [])[-6:])
    recent_compact = recent.replace(" ", "").replace("　", "")
    return any(
        term in recent_compact
        for term in (
            "補發簡訊帳單",
            "補寄簡訊帳單",
            "補發繳費帳單",
            "補寄繳費帳單",
            "登記電話",
            "簡訊帳單只能寄送",
        )
    )


def detect_contextual_feedback_direct_reply(
    text: str,
    history: List[Dict[str, str]],
    memory: Optional[Dict[str, Any]] = None,
) -> Optional[Dict[str, Any]]:
    for detector in (
        lambda: detect_virtual_hosting_followup(text, history),
        lambda: detect_network_outage_instability_followup(text, history, memory),
        lambda: detect_value_added_option_selection_followup(text, history),
        lambda: detect_remote_repair_followup(text, history),
        lambda: detect_connected_stb_youtube_followup(text, history),
        lambda: detect_general_channel_e004_followup(text, history),
        lambda: detect_cnt_seasonal_authorization_followup(text, history, memory),
        lambda: detect_tv_only_promotion_followup(text, history),
        lambda: detect_overdue_reconnection_service_selection_followup(text, history),
        lambda: detect_sms_bill_customer_number_followup(text, history),
        lambda: detect_payment_clarify_option_followup(text, history),
    ):
        result = detector()
        if result:
            return result
    return None


def build_company_info_clarify_decision(text: str, reason: str) -> Dict[str, Any]:
    return validate_router_result({
        "route": "clarify",
        "intent": "ambiguous_short_query",
        "tool_name": None,
        "topic": "公司資訊",
        "should_cancel_current_flow": False,
        "should_call_tool": False,
        "should_retrieve_knowledge": False,
        "knowledge_query": None,
        "reply": "請問您是想知道公司地址，還是目前系統台的服務地區範圍呢？",
        "extracted_slots": {},
        "reason": reason,
    })


def build_reconnection_clarify_decision(reason: str) -> Dict[str, Any]:
    return validate_router_result({
        "route": "clarify",
        "intent": "ambiguous_short_query",
        "tool_name": None,
        "topic": "復線服務類型",
        "should_cancel_current_flow": False,
        "should_call_tool": False,
        "should_retrieve_knowledge": False,
        "knowledge_query": None,
        "reply": "請問是網路服務被斷線，還是電視訊號無法收看呢？確認服務類型後，我再協助您處理復線。",
        "extracted_slots": {},
        "reason": reason,
    })


def build_reconnection_tool_decision(tool_name: str, reason: str) -> Dict[str, Any]:
    return validate_router_result({
        "route": "tool_action",
        "intent": "reconnection",
        "tool_name": tool_name,
        "topic": "復線",
        "should_cancel_current_flow": False,
        "should_call_tool": True,
        "should_retrieve_knowledge": False,
        "knowledge_query": None,
        "reply": "可以，我幫您處理復線申請。",
        "extracted_slots": {},
        "reason": reason,
    })


def has_receipt_barcode_text(text: str) -> bool:
    value = text or ""
    barcode_count = len(re.findall(r"第\s*[一二三123]\s*段(?:\s*條碼)?", value))
    return barcode_count >= 2


def is_reference_website_request(text: str) -> bool:
    value = (text or "").strip()
    if not value:
        return False
    return "網站" in value and any(term in value for term in (
        "參考",
        "資料來源",
        "來源",
        "佐證",
        "參考連結",
    ))


def detect_company_info_interrupt_query(
    text: str,
    memory: Optional[Dict[str, Any]] = None,
) -> Optional[Dict[str, Any]]:
    text = (text or "").strip()
    if not text:
        return None

    if is_contextual_website_page_request(text):
        return None

    if any(
        term in text
        for term in ("區域故障", "區域異常", "區故", "地區故障", "地區異常", "附近故障", "大範圍故障")
    ):
        return build_company_info_decision("area_outage", "company_info_area_outage_interrupt_rule")

    if any(term in text for term in SERVICE_AREA_TERMS):
        return build_company_info_decision("service_area", "company_info_service_area_interrupt_rule")

    if any(term in text for term in BUSINESS_HOUR_TERMS):
        return build_company_info_decision("business_hours", "company_info_business_hours_interrupt_rule")

    if any(term in text for term in VALUE_ADDED_URL_TERMS):
        return build_company_info_decision("value_added_urls", "company_info_value_added_urls_interrupt_rule")

    if is_explicit_company_website_request(text) and not is_reference_website_request(text) and not any(
        term in text for term in PROMOTION_COMPANY_INFO_BLOCK_TERMS
    ):
        return build_company_info_decision("website", "company_info_website_interrupt_rule")

    if any(term in text for term in CONTACT_PHONE_TERMS):
        return build_company_info_decision("contact_phone", "company_info_contact_phone_interrupt_rule")

    explicit_company_address = any(
        term in text
        for term in ("公司地址", "櫃台地址", "門市地址", "營業處")
    )
    if explicit_company_address and not is_technical_ip_address_query(text):
        return build_company_info_decision("company_address", "company_info_address_interrupt_rule")

    return None


def build_definition_query_decision(text: str, reason: str) -> Dict[str, Any]:
    text = (text or "").strip()
    return validate_router_result({
        "route": "knowledge_query",
        "intent": "definition_query",
        "tool_name": None,
        "topic": text,
        "should_cancel_current_flow": False,
        "should_call_tool": False,
        "should_retrieve_knowledge": True,
        "knowledge_query": text,
        "reply": "",
        "extracted_slots": {},
        "reason": reason,
    })


def build_memory_summary(memory: Dict[str, Any]) -> str:
    known = memory.get("known_info", {})
    data = {
        "company_code": memory.get("company_code"),
        "company": memory.get("company"),
        "pending_tool": memory.get("pending_tool"),
        "pending_tool_args": memory.get("pending_tool_args", []),
        "clarify_context": memory.get("clarify_context"),
        "decision_type": memory.get("decision_type"),
        "service": memory.get("service"),
        "issue_type": memory.get("issue_type"),
        "last_campaign_topic": memory.get("last_campaign_topic") or known.get("last_campaign_topic"),
        "last_value_added_topic": memory.get("last_value_added_topic") or known.get("last_value_added_topic"),
        "known_info": {
            "troubleshooting_started": known.get("troubleshooting_started"),
            "troubleshooting_type": known.get("troubleshooting_type"),
            "troubleshooting_step": known.get("troubleshooting_step"),
            "repair_ready": known.get("repair_ready"),
            "issue_description": known.get("issue_description"),
            "contact_name": known.get("contact_name"),
            "contact_phone": known.get("contact_phone"),
            "service_address": known.get("service_address"),
            "preferred_date": known.get("preferred_date"),
            "preferred_time_range": known.get("preferred_time_range"),
            "name": known.get("name"),
            "phone": known.get("phone"),
            "custnum": known.get("custnum"),
            "service_area": known.get("service_area"),
            "channel_name": known.get("channel_name"),
            "addon_name": known.get("addon_name"),
            "install_service": known.get("install_service"),
            "desired_plan": known.get("desired_plan"),
            "repair_ticket_id": known.get("repair_ticket_id"),
            "first_barcode": known.get("first_barcode"),
            "second_barcode": known.get("second_barcode"),
            "third_barcode": known.get("third_barcode"),
            "internet_reactivation_status": known.get("internet_reactivation_status"),
            "internet_reactivation_message": known.get("internet_reactivation_message"),
            "tv_reactivation_status": known.get("tv_reactivation_status"),
            "tv_reactivation_message": known.get("tv_reactivation_message"),
            "termination_service_scope": known.get("termination_service_scope"),
            "last_campaign_topic": known.get("last_campaign_topic"),
            "last_value_added_topic": known.get("last_value_added_topic"),
        }
    }
    def compact(value):
        if isinstance(value, dict):
            result = {}
            for key, item in value.items():
                compacted = compact(item)
                if compacted not in (None, "", [], {}):
                    result[key] = compacted
            return result
        if isinstance(value, list):
            return [compact(item) for item in value]
        return value

    return json.dumps(
        compact(data),
        ensure_ascii=False,
        separators=(",", ":"),
    )


def build_router_history_text(
    history: List[Dict[str, str]],
    memory: Dict[str, Any],
    user_input: str,
) -> str:
    """Build routing context without treating ordinary assistant replies as facts."""
    messages = [
        message for message in (history or [])
        if str(message.get("content") or "").strip()
    ]

    # The web endpoint persists the current user turn before routing, while
    # other channels may not. Keep it only in the dedicated latest-message
    # section so both paths present the same context to the model.
    latest_input = str(user_input or "").strip()
    if (
        messages
        and str(messages[-1].get("role") or "").lower() == "user"
        and str(messages[-1].get("content") or "").strip() == latest_input
    ):
        messages = messages[:-1]

    recent_user_messages = [
        message for message in messages
        if str(message.get("role") or "").lower() == "user"
    ][-4:]
    history_lines = [
        f"user: {str(message.get('content') or '').strip()}"
        for message in recent_user_messages
    ]

    # Ordinary assistant answers remain excluded because they may be the
    # incorrect content under review. A clarification is different: a short
    # reply such as "both" has no meaning unless the model sees the options it
    # asked the customer to choose between.
    if str(memory.get("decision_type") or "") == "clarify":
        previous_clarification = next((
            str(message.get("content") or "").strip()
            for message in reversed(messages)
            if str(message.get("role") or "").lower() == "assistant"
        ), "")
        if previous_clarification:
            history_lines.append(f"assistant_clarification: {previous_clarification}")

    return "\n".join(history_lines) if history_lines else "無"


def resolve_remembered_value_added_followup(
    user_input: str,
    memory: Dict[str, Any],
    router: Dict[str, Any],
) -> Optional[Dict[str, Any]]:
    """Carry a confirmed add-on product into a short semantic follow-up.

    The remembered topic is used only when the primary router has not selected
    another concrete flow.  This resolves natural turns such as "一年多少？"
    without turning a stale topic into a global keyword shortcut.
    """
    value = normalize_text_width(user_input or "").strip()
    if not value or detect_value_added_product_keys(value):
        return None

    router = router or {}
    if str(router.get("route") or "") not in {"knowledge_query", "clarify", "unknown"}:
        return None

    memory = memory or {}
    known = memory.get("known_info") if isinstance(memory.get("known_info"), dict) else {}
    remembered_topic = str(
        memory.get("last_value_added_topic")
        or known.get("last_value_added_topic")
        or ""
    ).strip()
    if not remembered_topic:
        return None

    if memory.get("pending_tool") or known.get("troubleshooting_started") == "yes":
        return None

    compact = value.replace(" ", "").replace("　", "")
    if remembered_topic == "WiFi 加值服務" and "youtube" in compact.lower():
        return build_direct_reply_decision(
            intent="wifi_value_added_youtube_scope",
            topic=remembered_topic,
            reply=WIFI_VALUE_ADDED_YOUTUBE_REPLY,
            reason="remembered_wifi_value_added_youtube_scope",
        )

    semantic_context = " ".join(
        str(router.get(field) or "")
        for field in ("intent", "topic", "knowledge_query", "reason")
    ).lower()
    router_supports_topic = any(
        hint.lower() in semantic_context for hint in VALUE_ADDED_ROUTER_HINTS
    )
    router_is_uncertain = is_generic_uncertain_router_result(router)

    # A knowledge route about another established domain is an intentional
    # topic switch, not an add-on follow-up.  Uncertain results may safely use
    # the remembered product after the message-level checks below.
    if not router_supports_topic and not router_is_uncertain:
        return None

    followup_terms = VALUE_ADDED_PRODUCT_INFO_TERMS + (
        "多久",
        "幾個月",
        "可以打多久",
        "能打多久",
        "可以用",
        "能用",
        "youtube",
        "通話多久",
        "打電話",
        "怎麼辦",
        "怎麼用",
        "如何使用",
    )
    if len(compact) > 30 or not any(term in compact for term in followup_terms):
        return None

    # Do not let a remembered product swallow a clear switch to an account,
    # billing, contract, cancellation, installation or fault request.  These
    # are customer-facing domains with their own tools and workflows.
    explicit_switch_terms = (
        "帳單",
        "繳費",
        "付款",
        "入帳",
        "信用卡",
        "合約",
        "續約",
        "到期",
        "退租",
        "停用",
        "復線",
        "報修",
        "故障",
        "不能用",
        "無法使用",
        "沒網路",
        "不能上網",
        "不能看",
        "訊號",
        "斷線",
        "裝機",
        "新裝",
        "移機",
        "頻道",
        "第四台",
        "有線電視",
        "客編",
        "真人客服",
    )
    if any(term in compact for term in explicit_switch_terms):
        return None

    if any(term in compact for term in ("一年", "年繳", "年費")):
        detail_query = "年繳 一年 年費 費用 價格"
    elif any(term in compact for term in ("半年", "半年繳")):
        detail_query = "半年繳 半年 費用 價格"
    elif any(term in compact for term in ("月租", "月繳", "每月", "一個月")):
        detail_query = "月租 月繳 每月 費用 價格"
    elif any(term in compact for term in ("多久", "幾個月", "打電話", "通話")):
        detail_query = "通話分鐘 使用時間 贈送月數 期限"
    elif any(term in compact for term in ("怎麼辦", "怎麼用", "如何使用", "申請", "申辦")):
        detail_query = "申辦方式 使用方式"
    else:
        detail_query = value

    return build_knowledge_query_decision(
        intent="value_added_product_query",
        topic=remembered_topic,
        # The remembered topic is already canonical. Query only the requested
        # field; broad aliases and every possible field would pull unrelated
        # add-on products into a narrow follow-up.
        knowledge_query=f"{remembered_topic} {detail_query}".strip(),
        reason="remembered_value_added_product_followup",
    )


def router_guard(
    user_input: str,
    memory: Dict[str, Any],
    router: Dict[str, Any],
) -> Dict[str, Any]:
    text = (user_input or "").strip()
    known = memory.get("known_info", {})
    guarded = dict(router or {})

    # Model decisions are authoritative for semantics.  The post-model
    # guard only normalizes the typed contract and blocks unsafe or
    # duplicate tool execution; it never reclassifies customer wording.
    if guarded.get("reason") == "model_router_unavailable":
        return validate_router_result(guarded)

    model_intent = str(guarded.get("intent") or "").strip()
    if model_intent in MODEL_HUMAN_HANDOFF_INTENT_ALIASES:
        known["human_handoff_active"] = "yes"
        known["human_handoff_topic"] = str(
            guarded.get("topic") or "服務辦理"
        )
        memory["known_info"] = known
        return build_human_handoff_request_decision(
            str(guarded.get("reason") or "model_handoff_intent_alias"),
            topic=str(guarded.get("topic") or "真人客服"),
        )
    if (
        known.get("human_handoff_active") == "yes"
        and not guarded.get("should_cancel_current_flow")
        and model_intent in MODEL_HUMAN_HANDOFF_FOLLOWUP_INTENTS
    ):
        return build_human_handoff_request_decision(
            "model_handoff_followup_contract",
            topic=str(
                known.get("human_handoff_topic")
                or guarded.get("topic")
                or "真人客服"
            ),
        )
    if model_intent in MODEL_MEMBER_LOGIN_INTENTS:
        return build_direct_reply_decision(
            intent="member_login_guidance",
            topic="官網與哈TV行動客服 APP 登入",
            reply=MEMBER_LOGIN_GUIDANCE_REPLY,
            reason="model_member_login_contract",
        )
    if model_intent in MODEL_ACCOUNT_HOLDER_CHANGE_FEE_INTENTS:
        return build_direct_reply_decision(
            intent="account_holder_change_fee_query",
            topic="變更使用者費用",
            reply=ACCOUNT_HOLDER_CHANGE_FEE_REPLY,
            reason="model_account_holder_change_fee_contract",
        )
    if model_intent in MODEL_ACCOUNT_HOLDER_CHANGE_DOCUMENT_INTENTS:
        return build_direct_reply_decision(
            intent="account_holder_change_required_documents",
            topic="變更使用者應備證件",
            reply=ACCOUNT_HOLDER_CHANGE_DOCUMENTS_REPLY,
            reason="model_account_holder_change_documents_contract",
        )
    if model_intent in MODEL_SELF_OWNED_ROUTER_COMPATIBILITY_INTENTS:
        return build_direct_reply_decision(
            intent="self_owned_router_compatibility_guidance",
            topic="自備路由器相容性",
            reply=SELF_OWNED_ROUTER_COMPATIBILITY_REPLY,
            reason="model_self_owned_router_compatibility_contract",
        )
    if model_intent in MODEL_SELF_OWNED_ROUTER_SETUP_INTENTS:
        return build_direct_reply_decision(
            intent="self_owned_router_setup_guidance",
            topic="自備路由器初始設定",
            reply=SELF_OWNED_ROUTER_SETUP_REPLY,
            reason="model_self_owned_router_setup_contract",
        )
    if model_intent in MODEL_MODEM_DUAL_ROUTER_INTENTS:
        return build_direct_reply_decision(
            intent="modem_dual_router_dhcp_guidance",
            topic="數據機連接多台路由器",
            reply=MODEM_DUAL_ROUTER_DHCP_REPLY,
            reason="model_modem_dual_router_contract",
        )
    if model_intent in MODEL_DYNAMIC_IP_COUNT_INTENTS:
        return build_direct_reply_decision(
            intent="dynamic_ip_allocation_count",
            topic="浮動 IP 數量",
            reply=DYNAMIC_IP_ALLOCATION_COUNT_REPLY,
            reason="model_dynamic_ip_count_contract",
        )
    if model_intent in MODEL_ROUTER_MANUAL_REGISTRATION_INTENTS:
        return build_direct_reply_decision(
            intent="router_manual_registration_guidance",
            topic="路由器手動註冊",
            reply=ROUTER_MANUAL_REGISTRATION_REPLY,
            reason="model_router_manual_registration_contract",
        )
    if model_intent in MODEL_APPROVED_DIRECT_REPLY_CONTRACTS:
        topic, reply = MODEL_APPROVED_DIRECT_REPLY_CONTRACTS[model_intent]
        return build_direct_reply_decision(
            intent=model_intent,
            topic=topic,
            reply=reply,
            reason=f"model_{model_intent}_contract",
        )

    repair_offer_active = (
        known.get("repair_ready") == "yes"
        or known.get("troubleshooting_failed") == "yes"
        or (memory.get("clarify_context") or {}).get("type")
        == "human_handoff_offer"
    )
    if (
        repair_offer_active
        and guarded.get("route") == "company_info"
        and (
            model_intent in {"contact_phone", "company_contact_phone"}
            or str(guarded.get("topic") or "")
            in {"contact_phone", "company_contact_phone"}
        )
    ):
        return build_clarify_decision(
            intent="human_handoff_offer",
            topic="故障後續處理",
            reply=(
                "您的問題需進一步協助處理，可填寫申告維修單，"
                "或選擇轉真人服務。請問是否需要幫您轉接真人文字客服？"
            ),
            reason="repair_offer_blocks_phone_only_reply",
        )

    if (
        guarded.get("route") == "tool_action"
        and guarded.get("tool_name") == "bill_return_line_tv"
        and known.get("tv_reactivation_status") == "already_temp_restored"
    ):
        return validate_router_result(build_direct_reply_decision(
            intent="tv_reactivation_already_temp_restored_followup",
            topic="電視暫時復線",
            reply="電視服務已暫時恢復，不會重複送出復線申請。",
            reason="guard_duplicate_tv_reactivation",
        ))
    if (
        guarded.get("route") == "tool_action"
        and guarded.get("tool_name") == "create_repair_ticket"
    ):
        # Repair is never the first action. The model owns the semantic
        # classification, while this guard enforces the workflow order:
        # troubleshoot first, then offer a human handoff after failure.
        if (
            known.get("troubleshooting_failed") == "yes"
            and known.get("repair_ready") == "yes"
        ):
            return validate_router_result({
                "route": "clarify",
                "intent": "human_handoff_offer",
                "tool_name": None,
                "topic": str(guarded.get("topic") or "故障處理"),
                "should_cancel_current_flow": False,
                "should_call_tool": False,
                "should_retrieve_knowledge": False,
                "knowledge_query": None,
                "reply": "排除後仍無法恢復，請問是否需要幫您轉接真人文字客服？",
                "extracted_slots": {},
                "reason": "guard_repair_failure_requires_handoff_confirmation",
            })
        guarded.update({
            "route": (
                "continue_current_flow"
                if known.get("troubleshooting_started") == "yes"
                else "troubleshooting"
            ),
            "intent": (
                "troubleshooting"
                if known.get("troubleshooting_started") == "yes"
                else "repair_troubleshooting_intake"
            ),
            "tool_name": None,
            "should_call_tool": False,
            "should_retrieve_knowledge": False,
            "knowledge_query": None,
            "reply": "",
            "reason": "guard_repair_requires_troubleshooting_first",
        })
    if guarded.get("route") == "tool_action" and guarded.get("tool_name") not in SUPPORTED_TOOLS:
        guarded.update({
            "route": "unsupported_flow",
            "tool_name": None,
            "should_call_tool": False,
            "should_retrieve_knowledge": False,
            "reply": UNSUPPORTED_REPLY,
            "reason": "guard_unsupported_tool_action",
        })
    elif guarded.get("route") == "unsupported_flow":
        guarded["tool_name"] = None
        guarded["should_call_tool"] = False
        guarded["should_retrieve_knowledge"] = False
        if not guarded.get("reply"):
            guarded["reply"] = UNSUPPORTED_REPLY
    elif guarded.get("route") == "knowledge_query":
        guarded["tool_name"] = None
        guarded["should_call_tool"] = False
        guarded["should_retrieve_knowledge"] = True
        if not guarded.get("knowledge_query"):
            guarded["knowledge_query"] = text
    elif guarded.get("route") == "unknown":
        guarded["reply"] = DEFAULT_UNKNOWN_REPLY

    # A bare authorization message can mean that the customer landed on
    # an unsubscribed channel. It is not enough evidence to run a
    # state-changing television reconnection API. Keep the LLM-selected
    # service scope, but require the channel/authorization SOP first.
    if (
        guarded.get("route") == "tool_action"
        and guarded.get("tool_name") == "bill_return_line_tv"
        and is_tv_authorization_issue(text)
    ):
        return build_troubleshooting_decision(
            text,
            "guard_tv_authorization_requires_channel_check",
        )

    # The model has already interpreted the turn. A receipt barcode can
    # trigger an account-side action only when the values came from a
    # verified uploaded image, never from text the customer typed.
    receipt_evidence = current_verified_receipt_image_evidence(memory, text)
    if receipt_evidence and guarded.get("tool_name") == "payment_bill_batch":
        return build_tool_action_decision(
            intent="payment_receipt_reconnection",
            tool_name="payment_bill_batch",
            topic="超商收據復線",
            reply="",
            reason="guard_verified_receipt_image_reconnection",
        )
    if (
        guarded.get("tool_name") == "payment_bill_batch"
    ):
        return build_direct_reply_decision(
            intent="payment_receipt_image_required",
            topic="超商收據復線",
            reply=(
                RECEIPT_IMAGE_REUPLOAD_REPLY
                if is_receipt_image_submission(text, memory)
                else RECEIPT_IMAGE_REQUIRED_REPLY
            ),
            reason=(
                "guard_receipt_image_ocr_incomplete"
                if is_receipt_image_submission(text, memory)
                else "guard_receipt_image_evidence_required"
            ),
        )

    # A model-selected handoff is an action contract, not free-form copy.
    # Keep the model's intent but replace its wording with the canonical
    # response so Web callers receive a real, signed handoff link.
    if guarded.get("intent") in {"human_handoff_request", "human_agent"}:
        known["human_handoff_active"] = "yes"
        known["human_handoff_topic"] = str(
            guarded.get("topic") or "真人客服"
        )
        memory["known_info"] = known
        return build_human_handoff_request_decision(
            str(guarded.get("reason") or "llm_human_handoff_request"),
            topic=str(guarded.get("topic") or "真人客服"),
        )

    return validate_router_result(guarded)


def is_paper_bill_request(text: str) -> bool:
    normalized = (text or "").replace(" ", "").replace("　", "")
    if not normalized or any(term in normalized for term in PAPER_BILL_EXCLUSION_TERMS):
        return False

    has_paper_bill_topic = any(term in normalized for term in PAPER_BILL_TERMS) or (
        "紙本" in normalized and ("帳單" in normalized or "繳費單" in normalized)
    )
    return has_paper_bill_topic and any(term in normalized for term in PAPER_BILL_REQUEST_TERMS)


def is_paper_to_electronic_bill_change_query(text: str) -> bool:
    normalized = (text or "").replace(" ", "").replace("　", "").lower()
    if not normalized:
        return False

    has_paper_bill = "紙本" in normalized and "帳單" in normalized
    has_electronic_bill = any(term in normalized for term in (
        "電子帳單",
        "電子化帳單",
        "e帳單",
        "ebill",
    ))
    has_change_request = any(term in normalized for term in (
        "改",
        "變更",
        "轉",
        "換",
    ))
    return has_paper_bill and has_electronic_bill and has_change_request


def run_intent_router(
    user_input: str,
    memory: Dict[str, Any],
    history: List[Dict[str, str]],
    llm,
) -> Dict[str, Any]:
    """Route every customer turn through the model before selecting a flow."""
    history_text = build_router_history_text(history, memory, user_input)
    prompt = ChatPromptTemplate.from_template(
        "{rules}\n\n"
        "目前服務公司資訊：\n{company_context}\n\n"
        "目前 memory：\n{memory_summary}\n\n"
        "最近對話：\n{history_text}\n\n"
        "使用者最新訊息：\n{user_input}\n"
    )

    try:
        runtime_modules = select_runtime_prompt_modules(
            user_input,
            memory,
            history,
        )
        runtime_rules = build_contextual_runtime_intent_router_rules(
            user_input,
            memory,
            history,
            modules=runtime_modules,
        )
        regional_policy_rules = build_policy_prompt(
            memory,
            select_runtime_policy_keys(runtime_modules),
        )
        response = (prompt | llm).invoke({
            "rules": f"{runtime_rules}\n\n{regional_policy_rules}",
            "company_context": build_company_context(memory.get("company_code", DEFAULT_TV_CABLE)),
            "memory_summary": build_memory_summary(memory),
            "history_text": history_text,
            "user_input": user_input,
        })
        data = safe_json_loads(response.content)
        if data:
            decision = validate_router_result(data)
            guarded_decision = router_guard(
                user_input,
                memory,
                decision,
            )
            if guarded_decision.get("route") != "unknown":
                return guarded_decision
    except Exception:
        pass

    fallback_decision = validate_router_result({
        "route": "unknown",
        "intent": "other",
        "tool_name": None,
        "topic": (user_input or "").strip(),
        "should_cancel_current_flow": False,
        "should_call_tool": False,
        "should_retrieve_knowledge": False,
        "knowledge_query": None,
        "reply": MODEL_ROUTER_UNAVAILABLE_REPLY,
        "extracted_slots": {},
        "reason": "model_router_unavailable",
    })
    guarded_fallback = router_guard(
        user_input,
        memory,
        fallback_decision,
    )
    return guarded_fallback
