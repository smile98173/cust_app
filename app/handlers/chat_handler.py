import time
import re
import html
import json
from datetime import date, datetime
from decimal import Decimal, ROUND_HALF_UP
from typing import Dict, Any, List
from uuid import uuid4

from langchain_core.prompts import ChatPromptTemplate

from app.services.intent_router import (
    APP_PAYMENT_RECEIPT_REPLY,
    BASIC_CHANNEL_TABLE_REPLY,
    CABLE_TV_TERMINATION_CALCULATION_REPLY,
    CLOUD_ACCOUNT_APP_GUIDE_REPLY,
    CONTRACT_CHANGE_AFTER_TERMINATION_REPLY,
    HUMAN_HANDOFF_CONFIRM_REPLY,
    HUMAN_HANDOFF_TRIAGE_REPLY,
    INVOICE_CARRIER_BINDING_CONFIRMATION_REPLY,
    INVOICE_CARRIER_REPLY,
    INVOICE_ISSUE_TIMING_REPLY,
    POINTS_USAGE_FALLBACK_REPLY,
    POINTS_ACCOUNT_MERGE_REPLY,
    REPAIR_VISIT_EXPECTATION_REPLY,
    BROADBAND_TERMINATION_GUIDANCE_REPLY,
    WIFI_VALUE_ADDED_YOUTUBE_REPLY,
    WIFI_VALUE_ADDED_SERVICE_REPLY,
    WEB_HUMAN_HANDOFF_REPLY,
    TV_PASSWORD_PROMPT_REPLY,
    TV_UNAUTHORIZED_PAID_CHANNEL_REPLY,
    SERVICE_ACCOUNT_TRANSFER_REPLY,
    VIRTUAL_HOSTING_UNSUPPORTED_REPLY,
    detect_contextual_feedback_direct_reply,
    is_broadband_unlimited_query,
    is_human_handoff_confirmation_no,
    is_human_handoff_confirmation_yes,
    has_human_handoff_issue_details,
    is_human_handoff_query,
    is_contract_lookup_request,
    is_tv_network_install_option_query,
    is_virtual_hosting_query,
    run_intent_router,
)
from app.services.router_catalog import (
    ROUTE_DECISION_TYPES,
    TOPIC_WORDS,
    get_clarify_context,
    match_contextual_clarify_fallback,
    match_clarify_option,
)
from app.services.kb_answer_guard import filter_answerable_docs, is_promotion_query
from app.services.general_knowledge_fallback import build_general_knowledge_reply
from app.services.kb_service import (
    VALUE_ADDED_PRODUCT_QUERY_ALIASES,
    VALUE_ADDED_PRODUCT_NAMES,
    detect_value_added_product_keys,
    doc_search_text,
    is_broadband_plan_price_query,
    is_restricted_channel_purchase_query,
    extract_requested_broadband_speeds,
    is_pure_network_catalog_query,
    is_pure_network_plan_doc,
    is_pure_tv_rate_card_doc,
    is_social_discount_doc,
    is_tv_network_combo_doc,
    is_high_confidence_campaign_alias_match,
    normalize_keyword_text,
    dedupe_retrieved_docs,
    retrieve_knowledge,
)
from app.services.memory_service import save_session_memory, save_chat_log
from app.services.ticket_service import evaluate_dispatch_need
from app.services.tool_manager import (
    CUSTOMER_NOT_FOUND_MESSAGE,
    CUST_API_BACKED_TOOL_NAMES,
    call_tool,
)
from app.services.customer_validation import (
    CONTRACT_LOOKUP_LOGIN_REQUIRED_REPLY,
    has_authenticated_web_custnum,
)
from app.services.slot_manager import (
    extract_slots_from_text,
    has_invalid_customer_number_format,
    merge_slots_into_memory,
    get_missing_tool_args,
    build_missing_args_question,
    normalize_pending_tool_args,
)
from app.services.controller_service import merge_memory_update
from app.services.company_profile import (
    DEFAULT_TV_CABLE,
    build_company_context,
    build_company_link,
    build_company_info_reply,
    extract_company_links,
    get_all_company_profiles,
    get_company_profile,
    is_contextual_website_page_request,
)
from app.services.latency_logging import log_chat_latency
from app.services.cust_api_diagnostic_logging import (
    cust_api_diagnostic_context,
    log_cust_api_tool_result,
)
from app.config.settings import (
    CUSTOMER_TOOL_FLOW_DISABLED_MESSAGE,
    REPAIR_TICKET_FLOW_ENABLED,
    RAG_SUMMARY_MAX_CHARS_PER_DOC,
    RAG_SUMMARY_MAX_DOCS,
)
from app.services.troubleshooting_engine import (
    apply_troubleshooting_engine,
    detect_troubleshooting_type,
    is_direct_fault_report,
    is_network_slow_issue,
    is_remote_control_issue,
    start_tv_input_source_troubleshooting,
)
from app.services.model_manager import finish_llm_trace, start_llm_trace
from app.services.regional_policy import build_policy_prompt, get_policy_text
from app.services.reply_safety import sanitize_human_handoff_keyword_instruction
from app.services.receipt_image_evidence import (
    RECEIPT_IMAGE_REQUIRED_REPLY,
    RECEIPT_IMAGE_REUPLOAD_REPLY,
    clear_unverified_receipt_barcode_slots,
    current_verified_receipt_image_evidence,
    is_receipt_image_submission,
)

REPAIR_TICKET_TOOL_NAMES = {"create_repair_ticket", "cancel_repair_ticket"}
IDENTITY_LOOKUP_TOOL_NAMES = {
    "search_bill",
    "search_contract_info",
    "send_message",
    "bill_return_line_internet",
    "bill_return_line_tv",
}
REPAIR_TICKET_SLOT_NAMES = {
    "contact_name",
    "contact_phone",
    "service_address",
    "issue_description",
    "preferred_date",
    "preferred_time_range",
    "repair_ticket_id",
}
DISABLED_CUSTOMER_TOOL_NAMES = {
    "search_service_availability",
    "apply_new_install",
    "search_addon_plans",
}
DISABLED_CUSTOMER_TOOL_SLOT_NAMES = {
    "contact_name",
    "contact_phone",
    "service_address",
    "service_area",
    "install_service",
    "desired_plan",
    "addon_name",
}
IDENTITY_LOOKUP_FAILURE_COUNT_KEY = "_identity_lookup_failure_count"
IDENTITY_LOOKUP_FAILURE_TOOL_KEY = "_identity_lookup_failure_tool"
IDENTITY_LOOKUP_FAILURE_REMINDED_KEY = "_identity_lookup_failure_reminded"
IDENTITY_LOOKUP_FAILURE_REMINDER = (
    "若您已多次確認資料仍查不到，建議可洽詢真人客服協助核對資料。"
    "目前不會自動轉接，您也可以重新提供正確的客戶編號、戶名、登記電話任兩項，我再協助查詢。"
)
PROMOTION_REFERRAL_CODE = "NET06"
PROMOTION_REFERRAL_FOOTER = f"推薦人代碼：{PROMOTION_REFERRAL_CODE}"
PROMOTION_REFERRAL_REPLY_ALLOW_TERMS = (
    "方案名稱",
    "活動期間",
    "優惠內容",
    "優惠方案",
    "優惠活動",
    "活動方案",
    "促銷方案",
    "推薦方案",
    "目前推薦",
    "最新方案",
    "新申裝",
    "新裝優惠",
    "月繳",
    "季繳",
    "半年繳",
    "年繳",
    "綁約",
    "違約金",
    "贈品",
    "贈送",
    "抽獎",
    "哈 POINT",
    "哈POINT",
    "LINE TV",
)
PROMOTION_REFERRAL_REPLY_BLOCK_TERMS = (
    "目前沒有優惠活動公告",
    "目前沒有優惠方案",
    "沒有優惠活動公告",
    "沒有優惠方案",
    "查不到優惠",
    "未查到優惠",
    "暫不提供優惠",
    "目前線上客服暫不提供優惠",
)
ACTIVE_FLOW_SWITCH_TERMS = (
    "區域故障",
    "區域異常",
    "區故",
    "地區故障",
    "地區異常",
    "公告",
    "客服電話",
    "公司電話",
    "聯絡電話",
    "營業時間",
    "地址",
    "服務地區",
    "服務範圍",
    "合約",
    "我的合約",
    "合約到期",
    "目前服務",
    "服務內容",
    "官網",
    "官方網站",
    "方案",
    "優惠",
    "促銷",
    "費用",
    "價格",
    "價錢",
    "月租",
    "多少錢",
    "什麼是",
    "是什麼",
    "怎麼申請",
    "如何申請",
    "怎麼辦理",
    "如何辦理",
    "裝機申請",
    "新裝申請",
    "新申裝",
    "繳費方式",
    "繳費",
    "帳單",
    "帳務",
    "帳款",
    "已繳費",
    "繳了",
    "付款",
    "付費",
    "恢復",
    "復線",
    "開通",
    "斷訊",
    "停訊",
    "欠費",
    "載具",
    "LINE TV",
    "LINETV",
    "LineTV",
    "紅利",
    "哈POINT",
    "哈 Point",
    "POINT",
    "點數",
    "頻道",
    "瑪帛",
    "熊搭心",
    "固定ip",
    "固定IP",
    "固定 IP",
    "故障",
    "不想看了",
    "不看了",
    "不要看了",
    "維修",
    "報修",
    "派工",
    "網路排除",
    "電視排除",
    "機上盒排除",
    "今天會來",
    "會來維修",
    "維修好了",
    "不能用",
    "不能看",
    "未授權",
    "遙控器",
    "遙控",
)
ACTIVE_FLOW_QUESTION_MARKERS = ("?", "？", "嗎", "呢", "如何", "怎麼", "什麼")
STRONG_TOPIC_SWITCH_TERMS = (
    "固定ip",
    "固定IP",
    "固定 IP",
    "優惠",
    "促銷",
    "方案",
    "費用",
    "月租",
    "價格",
    "價錢",
    "合約",
    "目前服務",
    "服務內容",
    "帳單",
    "帳務",
    "帳款",
    "故障",
    "不能用",
    "不能看",
    "無訊號",
    "無信號",
    "未授權",
    "授權到期",
    "無授權",
    "沒有授權",
    "E004",
    "e004",
    "只有四台可看",
    "只能看四台",
    "遙控器",
    "遙控",
    "世足",
    "世界盃",
    "世界杯",
    "賽事",
)


def is_tv_authorization_or_limited_channel_text(text: str) -> bool:
    value = (text or "").strip()
    return any(
        term in value
        for term in (
            "E004",
            "e004",
            "授權到期",
            "未授權",
            "無授權",
            "沒有授權",
            "只有四台可看",
            "只能看四台",
            "只剩四台",
            "只剩4台",
            "只有4台可看",
            "只能看4台",
        )
    )
TROUBLESHOOTING_HISTORY_STEP_MARKERS = (
    (("機上盒電源線是否插好", "插座是否有電"), "tv", "tv_check_power_cable"),
    (("機上盒電源是否有亮燈",), "tv", "tv_check_power"),
    (("電源燈目前是有亮", "沒有亮"), "tv", "tv_check_power"),
    (("電視畫面目前是顯示",), "tv", "tv_check_screen"),
    (("目前畫面是顯示", "無訊號"), "tv", "tv_check_screen"),
    (("訊號源", "畫面是否恢復"), "tv", "tv_check_input_source"),
    (("機上盒電源拔掉約 10 秒",), "tv", "tv_reboot"),
    (("所有設備都不能上網", "單一手機或電腦"), "network", "net_check_scope"),
    (("數據機", "燈號"), "network", "net_check_modem_light"),
    (("數據機電源拔掉",), "network", "net_reboot_modem"),
    (("該設備是否已可以上網",), "network", "net_single_device"),
)
TROUBLESHOOTING_CONTEXT_FOLLOWUP_TERMS = (
    "報故障",
    "回報故障",
    "報修",
    "故障排除",
    "線上排除",
    "線上教我",
    "教我排除",
    "怎麼排除",
    "如何排除",
    "可以排除",
    "需要排除",
    "最近變慢",
    "變慢",
)
VALUE_ADDED_CONTEXT_PRIORITY = (
    "wifi_5",
    "wifi_6",
    "home_camera",
    "marpa_user",
    "marpa_friend",
    "marpa_partner",
    "line_tv",
    "bear_care",
    "marpa",
    "wifi_addon",
)
VALUE_ADDED_DETAIL_FOLLOWUP_TERMS = (
    "費用",
    "價格",
    "價錢",
    "月租",
    "多少錢",
    "一年",
    "半年",
    "怎麼收",
    "怎麼申請",
    "如何申請",
    "內容",
    "有哪些",
    "差別",
    "限制",
    "押金",
    "賠償",
    "那呢",
)

RAG_SUMMARY_PROMPT = """
你是有線電視與寬頻客服助理。請根據提供的資料，直接回答使用者問題。

目前服務公司資訊：
{company_context}

優惠服務範圍：{promotion_scope}
優惠回答模式：{promotion_query_kind}
本輪回答焦點：{response_focus}

要求：
- 這是給一般使用者看的對外回覆。不可出現 API、RAG、知識庫、檢索、模型、向量、chunk 等內部技術或資料來源用語。
- 不要以「RAG 內」、「根據知識庫」、「目前資料顯示」、「資料中查到」等來源說明開頭；直接回答結論。資訊不足時，不要說「目前查不到明確資訊」或「目前查不到明確線上申請方式」；改用客服語氣說「這部分需由客服依實際狀況確認」，並提供可行的下一步。
- 回答中的內部縮寫必須轉為一般用語：CATV 改為「有線電視」、STB 改為「數位機上盒」、BB 改為「寬頻網路」。
- 只使用資料內容，不要自行補充資料外的優惠、價格或承諾。
- 若資料已對使用者的問題提供直接結論，請先用一句話明確回答結論；不要在後面自行加入會推翻結論的「可能、未必、需再確認」說法。只有資料本身保留條件或不確定性時，才說明該條件。
- 使用者詢問費用、金額、月繳／年繳差異時，只要資料中有數字，就必須把對應繳別與金額寫出來；不可只留下「費用如下」「銷售價格如下」等標題。若問同期間差多少，須用資料中的金額列式計算差額。
- 使用者詢問申請、加購、購買、設定、排除或其他流程時，若資料有可操作步驟，必須先回答那些步驟；費用、產品介紹或一般說明不能取代處理流程。資料同時提供步驟與費用時，先列處理方式，再補充費用或條件。
- 本輪若是移機服務，只回答移機流程、移機本身的費用與必要條件；忽略候選文件中不屬於移機段落的優惠到期、恢復原價、續期或其他方案文字。除非使用者明確追問，否則不要列分機費、機上盒押金或設備租借費。
- 本輪若是移機服務，先完整說明資料提供的移機費用；只有使用者看完後明確要求專人協助，才引導轉真人文字客服。不可提供客服電話。
- 本輪若是遙控器拷貝／學習功能，回答只保留文件中的學習模式、按鍵順序、燈號與完成方式；不可改答機上盒方案、收視費或一般遙控器故障。
- 資料已提供可直接完成需求的標準答案或操作流程時，回答到該流程即可；不可主動附加「請聯繫真人客服」、「需由客服協助」、「線上 AI 無法代辦」等但書。只有資料本身明確要求人工處理，或使用者完成步驟後仍表示失敗時，才說明人工協助方式。
- 路由已判定為「數位電視頻道套餐加購」時，回答必須完整保留兩種機上盒處理方式：聯網機上盒可使用遙控器依「VIP會員 → 優惠專區 → 數位電視」自行加購；非聯網機上盒無法自行加購，須洽客服辦理。不可只保留其中一種，也不可用方案價格、LINE TV、Wi-Fi 或其他加值服務取代此流程。使用者點名特定數位套餐時，可在流程後補充資料明確提供的費用或內容，但流程仍須保留。
- 使用者只問「線上繳費／線上付款／線上刷卡」時，須先說明官方網站與行動客服 APP 的線上繳費步驟；可在最後以一段「貼心提醒」說明線上刷卡、ibon、FamiPort 繳費會自動開通，並提醒重啟設備。不可展開超商機台的操作步驟。
- 使用者詢問 APP 內的發票或舊帳單位置時，入口統一寫為「歷史帳單」；不可寫「用戶資訊」，也不可把「用戶資訊／帳單歷史」並列。客戶只問 APP 時，只回答 APP 路徑，不主動展開官網與載具歸戶。
- 使用者表示「無法在便利商店繳費／超商繳費不會操作」，且資料提供 ibon 或 FamiPort 機台流程時，應視為機台操作詢問：先明確說明可依機台操作繳費，再以「【7-Eleven ibon】」與「【全家 FamiPort】」分段列出各自的操作流程。每段只保留該機台的路徑、輸入登記電話、確認資料、列印繳費單及至櫃台繳費等文件已提供的步驟；不可把兩種機台步驟混在同一段、不可重複相同流程，也不可混入官網、APP、臨櫃或其他泛用繳費方式。未明確提及條碼失效或帳務異常時，不可自行假設帳單失效。
- 不可把不同服務混為一談。使用者或資料正在談有線電視、寬頻網路、電視加網路方案、LINE TV、Wi-Fi 加值服務、聯網型機上盒或數位電視套餐時，僅回答該服務及直接相關內容；不要為了補充而換成另一項服務或方案。
- 「目前服務產品」是公司最新提供的產品清單。若使用者明確詢問、申請、購買或設定一項未列在清單內的獨立產品或服務，且不是既有產品的功能追問，不可使用相近的 RAG 資料回答。請婉轉說明「您好，目前本公司未提供『使用者提到的服務名稱』服務，抱歉無法協助辦理。」；服務名稱或歸屬不明確時，先詢問使用者要了解的具體服務，不要直接拒絕。
- 使用者追問前文方案的繳別、綁約、付款條件、包含服務或特定功能時，必須承接同一方案；不可因資料中同時有其他活動或產品就改答另一份方案。
- 回答要比原文短很多，適合客服聊天室閱讀。
- 先辨識使用者這一輪真正要的欄位，再只保留能回答該欄位的內容。問單一速率或單一價格時，先列該速率或價格與必要條件；不要展開同一文件的拆機、設備賠償、抽獎、加購或其他無關段落。問公司電話、地址或營業時間時，也只回答所問項目。
- 同時有多份不同方案來源都直接包含使用者指定速率或產品時，逐方案簡短比較該指定項目；不可只選其中一份，也不可把每份文件的完整內容全部重述。若資料分別提供辦理流程與費用，兩項都要保留，但只保留各自與問題直接相關的資訊。
- 一般知識回答最多 5 點，每點盡量 1 句。優惠活動內容要精簡，不可貼出整份活動文件。
- 若回答包含【方案名稱】、【適用對象】、【申請方式】、【申請條件】、【優惠內容】、【限制條件】，請每個欄位分行顯示，不要擠在同一段。
- 優惠內容內的項目請分行顯示，例如「項目1」、「項目2」各自一行。
- 使用者廣泛詢問優惠方案，或詢問特定月份、節日的優惠時，先以條列列出每個檢索到的方案名稱、服務類型與活動期間；不要主動展開費率、贈品、設備、合約或抽獎細節。
- 優惠回答模式為 catalog 時，只能回答「優惠服務範圍」指定的類型。先列方案名稱，再列速率與費用、活動期間；純有線電視沒有網路速率時，改列收視費與裝機費。不要混入其他服務類型。
- 使用者只輸入或明確點名某一個方案名稱、但未指定特定欄位時，首次只整理四項：寬頻費用、贈送內容、裝機費、違約金。資料未提供的欄位不要自行補充，也不要為了湊欄位寫「未提供」。
- 使用者追問已介紹方案的特定項目時，只回答該項目與必要條件，不要再次重述方案總覽。例如詢問 LINE TV、贈品、POINT、抽獎、設備、合約或申辦資格時，只整理該項目。
- 優惠活動的費率必須以「一個速率一行」呈現，且同一速率的月繳、季繳、半年繳、年繳與金額必須留在同一行；不可在「月繳／季繳／半年繳／年繳」和其金額之間換行。例如：「100M/10M：月繳 399 元、季繳 1,197 元、半年繳 2,394 元、年繳 4,788 元」。
- 不要主動展開設備遺失賠償、舊戶換約細節、Wi-Fi/攝影機租借、施工備註等次要內容；只有使用者明確追問該項目時才回答。
- 使用者追問優惠活動的特定項目時，只回答該項目與必要條件，不要再次重述整份方案。例如詢問 LINE TV 時，直接回答贈送幾個月及必要限制；詢問 POINT 或抽獎時，只整理贈點規則或抽獎資格/獎項。
- 回答抽獎獎項時，原始資料中每個獎項必須各自獨立一行，不要用頓號合併。數量必須與獎項留在同一行，例如「LINE FRIENDS 料理鍋 ×4」，不可把「×」與數字拆開。
- 使用者詢問優惠活動的「總共費用、總費用、合計、裝到好」時，必須依同一速率與同一繳別列式計算：裝機費 + 實際應收設備押金 + 該速率/繳別金額 = 合計。若押金因繳別而免收，請明列為 0 元；若使用者尚未指定速率或繳別，先請他選擇，不可混用不同方案金額，也不可猜測合計。
- 使用者在已知有線電視年繳費用與裝機費後追問兩年費用時，必須依同一份文件列式計算「年繳收視費 × 2 + 首次裝機費」並直接給出合計；不可只重列年繳費率。
- 如果資料太長，只保留與使用者問題最相關的重點。
- 如果資料內容含有 `［名稱🔗］` 這類連結標記，請原樣保留這個標記，不要改寫成純文字。
- 如果資訊看起來是內部派工備註或不適合直接給客戶，請不要完整照抄，只簡短提醒需由客服確認。
- 不要要求使用者輸入或回覆「真人客服」、「人工客服」、「轉真人」等固定關鍵字；目前由 AI 依使用者語意自動判斷是否需要轉接。
- 使用者詢問申請、補寄或設定紙本帳單時，先婉轉詢問是否有特別需求，並建議優先使用簡訊帳單、行動客服 APP 或官網線上信用卡繳費；紙本帳單的申請與寄送設定需由真人客服協助，不能承諾已完成設定。
{regional_policy_rules}
- 若使用者詢問「合計、總共、總金額、裝到好」這類費用計算，且資料中有明確金額，請列出公式，例如：半年收視費 + 裝機費 + 分機費 = 合計；不要只列其中一項費用。
- 若資料中以「售價」列出「月繳、半年繳、年繳」或「300M/300M：月繳$899元」這類內容，月繳就是月租/月費資料；不可回答「資料未提供月租」。
- 若使用者指定寬頻速率並詢問費用或申裝方案，只要資料中有該速率，就必須列出查到的方案名稱與該速率費用；不可因另一份文件未包含該速率而回答查無資料。
- 若資料中有多份不同方案皆包含使用者指定速率，必須分方案列出每份的該速率費用與必要條件；不可只挑其中一份回答。
- 若使用者是在詢問既有服務的推薦方案、升級方案或更高一階方案，且提供資料可辨識其目前網路速率，應以目前速率為基準，優先推薦更高速率的方案；例如目前為 100M，推薦範圍為 100M 以上。不可自行猜測目前方案、服務類型、合約狀態或可申辦資格。
- 若提供資料可辨識使用者目前是「電視＋網路」服務，推薦時優先列出「電視＋網路」類型的更高速率方案；除非使用者明確詢問純網路方案，否則不要主動以純網路方案取代推薦。若資料不足以辨識目前服務類型，請明確說明需先確認目前方案，不可自行假定。
- 對既有用戶的網路升級建議，回答結尾必須補充：「原用戶如欲升級網路速率，需先確認目前的方案及合約狀態，再依欲升級的速率確認是否可申請及相關費用，實際以查詢結果為準。」
- 若使用者詢問限制級或成人頻道授權到期後如何購買，資料中的「購買路徑」與「套餐月租」可能分屬不同文件；請分成「購買方式」與「可參考套餐費用」回答，不可因此回答資料未提供，最後補充實際可購買項目與資格仍需由客服確認。
- 若使用者問「續約、重新續約、續訂、重新訂購、約滿後怎麼辦」這類辦理方式，請優先回答續約/換約需由客服依目前合約狀態與可適用方案確認；不要把整份優惠活動清單當成主要答案。只有在使用者同時問「續約有什麼優惠/方案」時，才簡短列可參考費率與重點優惠。
- 若使用者明確表示「不續繳、不再續繳、不續約、不要續約、不再續用、不要再收費、停止收視、取消」等負向續用意圖，請優先視為「取消/停用/不續用」問題，不要當成一般續約優惠或合約查詢。若使用者詢問「會不會影響其他服務/聯網服務」，回答必須包含：目前資料是否有明確說明影響、若資料未明確則說需由客服依帳務與服務綁定狀態確認、以及不續用/取消需由客服協助登記；不可只列出合約到期日或目前服務清單。
- 若使用者明確表示「只要有線電視、只看第四台、基本有線、純 TV」，請優先使用基本收費、收視費、裝機費、分機費、機上盒押金資料；不要主動混入寬頻同裝或其他 TV+網路優惠方案。
- 若使用者已明確說只要有線電視／第四台，即使同一份有線電視新裝資料附帶贈送寬頻、聯網機上盒或影音體驗，也不可把那些附帶內容當成主要優惠列出；回答只保留有線電視收視費、裝機費與直接相關的使用條件，除非客戶追問附贈服務。
- 若使用者詢問「優惠、推薦、划算、目前活動」，才可以同時整理基本收費與相關優惠活動，並分成「基本收費」與「可參考優惠方案」兩段，不要把兩者混成同一個價格。
- 若使用者詢問有線電視或第四台費用，資料同時出現「基本收視費」與「新裝機優惠／到期恢復原價」時，請分成「基本收視費」、「新裝或優惠到期說明」、「裝機/機上盒相關費用」三段；不可把基本月租與優惠到期後恢復原價混成同一個費用。
- 若使用者只問「第四台月租費多少」，請直接回答目前適用的有線電視月繳金額；不要主動加入裝機費、數位機上盒或分機費。若資料同時標示原價與新裝月繳優惠，優先回答新裝月繳優惠。
- 若同時提供兩個以上方案，請以「【方案 1】」、「【方案 2】」分段，每個方案前保留空行；不可把兩個方案接在同一段。
- 「年繳」是付款週期，不代表只綁一年；使用者詢問一年合約時，不可用年繳金額代替回答綁約期間。
- 若回答是多台電視、機上盒、分機費、押金等收費規則，請使用「項目：說明」格式，每個項目獨立一行；不要再加外層 1. 2. 3. 編號，例如「第 1、2 台機上盒：...」、「第 3 台起：...」、「分機施工費：...」。
- 若使用者詢問多台機上盒的「半年繳合計」，請將半年收視費、裝機費、每台分機施工費及第 3 台起的機上盒押金逐項列出後再加總；例如資料為 $3,240、$1,000、$500 × 2 與 $1,200 時，合計必須是 $6,440。
- 不要輸出只有「1. 第」或「2. 第」這種殘缺標題。

使用者問題：
{user_text}

RAG 資料：
{knowledge_text}
"""


COMPLETE_KNOWLEDGE_EVIDENCE_INTENTS = {
    "cable_tv_payment_cycle_comparison",
    "relocation_guidance",
    "remote_power_learning",
}


def carry_forward_same_intent_evidence(
    docs: List[Dict[str, Any]],
    memory: Dict[str, Any] | None,
    intent: str | None,
) -> List[Dict[str, Any]]:
    """Preserve grounded evidence across consecutive turns of one LLM intent."""
    if intent not in COMPLETE_KNOWLEDGE_EVIDENCE_INTENTS:
        return docs

    memory = memory or {}
    if memory.get("last_knowledge_intent") != intent:
        return docs

    previous_docs = memory.get("last_knowledge_results") or []
    if not previous_docs:
        return docs

    return dedupe_retrieved_docs([*previous_docs, *docs])


def knowledge_response_focus(intent: str | None) -> str:
    if intent == "relocation_guidance":
        return (
            "只整理移機流程、移機本身的費用與必要條件；資料有明確金額時，"
            "必須逐項列出所有室內／室外及各服務費用，不帶入優惠活動、其他方案、"
            "分機、機上盒費用、客服電話或服務地區。"
        )
    if intent == "cable_tv_payment_cycle_comparison":
        return (
            "只列有線電視各繳別金額與同期間差額；不可加入服務地區、公司介紹或其他方案。"
        )
    if intent == "remote_power_learning":
        return "只回答遙控器拷貝／學習的操作步驟、按鍵順序與燈號。"
    if intent == "fixed_ip_binding_guidance":
        return (
            "只回答固定 IP 的申請確認與綁定流程。先說明數量及當期費用須由客服依現行規則確認，"
            "不可自行補數量或價格；再依資料列出官網登入、選擇設備、設定、確認完成與重新啟動。"
        )
    if intent in {"app_payment_receipt_lookup", "invoice_storage_lookup"}:
        return (
            "只回答使用者這一輪所問的發票或帳單查詢入口；若問題只問 APP，"
            "只提供 APP 的歷史帳單路徑，不重述實體收據、官網與載具歸戶。"
            "APP 入口只能寫「歷史帳單」，不可寫「用戶資訊」或把兩者並列。"
        )
    return "只回答使用者最新問題所需的資訊。"


PAYMENT_CYCLE_LABELS = ("月繳", "季繳", "半年繳", "年繳")


def extract_payment_cycle_amounts(docs: List[Dict[str, Any]]) -> Dict[str, int]:
    """Extract current rate-card values from retrieved evidence, never prompts."""
    amounts: Dict[str, int] = {}
    pattern = re.compile(
        r"(半年繳|季繳|月繳|年繳)(?:收視費)?\s*(?:[:：]|為)?\s*[$＄]?\s*(\d[\d,]*)\s*元?"
    )
    for doc in docs:
        source = str(doc.get("answer") or "")
        for label, raw_amount in pattern.findall(source):
            try:
                value = int(raw_amount.replace(",", ""))
            except ValueError:
                continue
            if value > 0:
                amounts.setdefault(label, value)
    return amounts


def missing_knowledge_summary_requirements(
    intent: str | None,
    summary: str | None,
    docs: List[Dict[str, Any]],
) -> List[str]:
    """Validate factual fields that an intent requires against current evidence."""
    if intent != "cable_tv_payment_cycle_comparison":
        return []

    amounts = extract_payment_cycle_amounts(docs)
    if not amounts:
        return []

    normalized = compact_text(summary or "").replace(",", "")
    return [
        f"{label} {amounts[label]:,} 元"
        for label in PAYMENT_CYCLE_LABELS
        if label in amounts
        and (label not in normalized or str(amounts[label]) not in normalized)
    ]


def build_payment_cycle_evidence_fallback(docs: List[Dict[str, Any]]) -> str:
    """Render evidence only after two incomplete LLM summaries."""
    amounts = extract_payment_cycle_amounts(docs)
    if not all(label in amounts for label in PAYMENT_CYCLE_LABELS):
        return ""

    monthly = amounts["月繳"]
    periods = {"月繳": 1, "季繳": 3, "半年繳": 6, "年繳": 12}
    lines = ["有線電視收視費如下："]
    for label in PAYMENT_CYCLE_LABELS:
        amount = amounts[label]
        if label == "月繳":
            lines.append(f"{label}：{amount:,} 元")
            continue
        difference = monthly * periods[label] - amount
        if difference > 0:
            comparison = f"（比同期月繳省 {difference:,} 元）"
        elif difference < 0:
            comparison = f"（比同期月繳多 {abs(difference):,} 元）"
        else:
            comparison = "（與同期月繳相同）"
        lines.append(f"{label}：{amount:,} 元{comparison}")
    return "\n".join(lines)

KNOWLEDGE_EVIDENCE_PROMPT = """
你是客服知識文件的證據審核器，只能輸出 JSON，不要輸出其他文字。

請判斷每一份候選文件是否能直接回答使用者這一輪的問題。只保留服務主體與所問資訊都相符的文件；
「相關」、「同一產業」或只出現一個相同詞，不代表可回答。不可因前一輪提過某服務，就把它帶入一個已切換主題的新問題。

使用者最新問題：
{user_text}

路由判定的服務主體：
{service_scope}

路由判定的所問資訊：
{requested_information}

候選文件：
{documents}

輸出格式：
{{"selected_document_indexes": [1], "has_sufficient_evidence": true}}

規則：
- index 從 1 開始。
- 只有文件可直接支援回答時才列入 selected_document_indexes。
- 如果沒有任何文件能直接回答，輸出空陣列及 false。
- 不要挑選只回答另一個設備、另一種繳費通路、另一項服務或另一種處理流程的文件。
""".strip()

DISCOUNT_STACKING_QUERY_TERMS = (
    "併用",
    "並用",
    "一起用",
    "一起使用",
    "重複適用",
    "重複使用",
    "搭配",
    "合併",
    "合用",
    "疊加",
    "同時適用",
    "可以一起",
    "加在一起",
)

DISCOUNT_CONTEXT_TERMS = (
    "優惠",
    "低收入",
    "中低收入",
    "身心障礙",
    "身障",
    "減免",
    "活動方案",
    "促銷",
)

DISCOUNT_STACKING_CAUTION = (
    "優惠是否可重複適用需依公司公告與個案資格確認；"
    "若資料未明確寫可併用，請不要承諾可同時適用，建議由客服協助確認。"
)

SOCIAL_DISCOUNT_STACKING_RULE = (
    "低收入戶、中低收入戶、身心障礙等社福優惠不可與其他公司優惠活動重複適用。\n"
    "若已申請低收入戶優惠，就不能再同時申請一般促銷或其他優惠方案；"
    "反過來，若已參加公司優惠活動，也不能再疊加低收入戶優惠。\n"
    "若要申辦，仍需由客服依您的資格與目前合約狀態確認可適用哪一種優惠。"
)

HIDDEN_DETAIL_QUERY_TERMS = (
    "隱藏版",
    "非主推",
    "不主推",
    "不推",
    "60M",
    "60m",
    "1G",
    "1g",
)

HIDDEN_RATE_LINE_RE = re.compile(
    r"(?:^|[\s：:、])(?:60M\s*/\s*60M|60M\s*/\s*6M|60M|1G\s*/\s*1G|1G)\b.*隱藏版",
    flags=re.IGNORECASE,
)
PLAN_PRICE_LINE_RE = re.compile(
    r"(?P<speed>\d+\s*[MG]\s*/\s*\d+\s*[MG])\s*[：:]\s*(?P<price>[^。\n；;]*月繳[^。\n；;]*)",
    flags=re.IGNORECASE,
)


def should_add_discount_stacking_caution(user_text: str, docs: List[Dict[str, Any]]) -> bool:
    compact_query = compact_text(user_text)
    asks_stacking = any(term in compact_query for term in DISCOUNT_STACKING_QUERY_TERMS)
    if not asks_stacking:
        return False

    combined = compact_text(" ".join([
        str(user_text or ""),
        " ".join(str(doc.get("question") or "") for doc in docs),
        " ".join(str(doc.get("answer") or "") for doc in docs),
    ]))
    return any(term in combined for term in DISCOUNT_CONTEXT_TERMS)


def is_social_discount_stacking_query(user_text: str, docs: List[Dict[str, Any]]) -> bool:
    compact_query = compact_text(user_text)
    asks_stacking = any(term in compact_query for term in DISCOUNT_STACKING_QUERY_TERMS)
    if not asks_stacking:
        return False

    combined = compact_text(" ".join([
        str(user_text or ""),
        " ".join(str(doc.get("question") or "") for doc in docs),
        " ".join(str(doc.get("answer") or "") for doc in docs),
    ]))
    social_terms = ("低收入", "中低收入", "身心障礙", "身障", "社福", "優惠戶")
    promotion_terms = ("促銷", "活動", "一般優惠", "優惠方案", "其他優惠", "公司優惠")
    return any(term in combined for term in social_terms) and any(term in combined for term in promotion_terms)


def is_hidden_detail_query(user_text: str) -> bool:
    compact_query = compact_text(user_text)
    return any(compact_text(term) in compact_query for term in HIDDEN_DETAIL_QUERY_TERMS)


def remove_hidden_rate_lines(text: str) -> str:
    value = str(text or "")
    if not value:
        return ""

    lines = value.splitlines()
    if len(lines) > 1:
        kept_lines = [
            line
            for line in lines
            if not ("隱藏版" in line and HIDDEN_RATE_LINE_RE.search(line))
        ]
        return "\n".join(kept_lines).strip()

    value = re.sub(
        r"(?:^|[。；;\n])\s*(?:60M\s*/\s*60M|60M\s*/\s*6M|60M|1G\s*/\s*1G|1G)[^。；;\n]*隱藏版[^。；;\n]*",
        "",
        value,
        flags=re.IGNORECASE,
    )
    return value.strip()


def extract_monthly_price_lines(docs: List[Dict[str, Any]]) -> List[str]:
    lines: List[str] = []
    seen = set()
    for doc in docs:
        parts = [
            str(doc.get("answer") or ""),
            str(doc.get("question") or ""),
        ]
        source = doc.get("source")
        if isinstance(source, dict):
            parts.append(str(source.get("content") or ""))

        for part in parts:
            for match in PLAN_PRICE_LINE_RE.finditer(part):
                speed = re.sub(r"\s+", "", match.group("speed").upper())
                price = match.group("price").strip(" ：:")
                line = f"{speed}：{price}"
                if line not in seen:
                    lines.append(line)
                    seen.add(line)
    return lines


def apply_monthly_price_correction(reply: str, docs: List[Dict[str, Any]]) -> str:
    value = str(reply or "").strip()
    compact_reply = compact_text(value)
    if not any(term in compact_reply for term in ("未提供月租", "沒有提供月租", "無月租資料")):
        return value

    price_lines = extract_monthly_price_lines(docs)
    if not price_lines:
        return value

    kept_lines = [
        line
        for line in value.splitlines()
        if not any(term in compact_text(line) for term in ("未提供月租", "沒有提供月租", "無月租資料"))
    ]
    corrected = "\n".join(line for line in kept_lines if line.strip()).strip()
    monthly_block = "【月租/速率】\n" + "\n".join(price_lines)
    return f"{corrected}\n{monthly_block}".strip()


def apply_knowledge_doc_visibility_policies(
    user_text: str,
    docs: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    if is_hidden_detail_query(user_text):
        return docs

    cleaned_docs: List[Dict[str, Any]] = []
    for doc in docs:
        cleaned = dict(doc)
        cleaned["answer"] = remove_hidden_rate_lines(str(cleaned.get("answer") or ""))
        source = cleaned.get("source")
        if isinstance(source, dict):
            cleaned_source = dict(source)
            cleaned_source["content"] = remove_hidden_rate_lines(str(cleaned_source.get("content") or ""))
            cleaned["source"] = cleaned_source
        cleaned_docs.append(cleaned)
    return cleaned_docs


def is_basic_tv_monthly_fee_only_query(user_text: str) -> bool:
    compact = compact_text(user_text)
    has_tv = any(term in compact for term in ("第四台", "有線電視", "基本收視", "catv"))
    has_monthly_fee = any(term in compact for term in ("月租", "月費", "一個月", "每月"))
    asks_other_fee = any(
        term in compact
        for term in ("裝機", "機上盒", "分機", "押金", "總共", "合計", "裝到好")
    )
    return has_tv and has_monthly_fee and not asks_other_fee


def knowledge_docs_text(docs: List[Dict[str, Any]]) -> str:
    parts: List[str] = []
    for doc in docs:
        parts.extend([
            str(doc.get("question") or ""),
            str(doc.get("answer") or ""),
        ])
        source = doc.get("source")
        if isinstance(source, dict):
            parts.append(str(source.get("content") or ""))
    return "\n".join(parts)


def knowledge_doc_text(doc: Dict[str, Any]) -> str:
    parts: List[str] = []
    for field in ("question", "title", "answer", "content", "file_name", "source_file"):
        value = str(doc.get(field) or "").strip()
        if value:
            parts.append(value)
    source = doc.get("source")
    if isinstance(source, dict):
        for field in ("title", "source", "file_name", "content"):
            value = str(source.get(field) or "").strip()
            if value:
                parts.append(value)
    return "\n".join(parts)


def build_clear_channel_group_reply(
    user_text: str,
    docs: List[Dict[str, Any]],
    intent: str | None = None,
) -> str:
    """Return only the requested facts from the maintained 清冰組 document."""
    if intent != "clear_channel_group_query" and "清冰組" not in str(user_text or ""):
        return ""

    source_lines: List[str] = []
    seen: set[str] = set()
    for doc in docs:
        text = knowledge_doc_text(doc)
        if "清冰組" not in text:
            continue
        for raw_line in text.splitlines():
            line = re.sub(r"^[#*\-\s]+", "", raw_line).strip()
            if not line or line in seen:
                continue
            if any(marker in line for marker in (
                "清冰組為申裝純網方案",
                "免費借用 1 台聯網機上盒",
                "最多只能借用 1 台聯網機上盒",
                "約 20～24 個頻道",
                "實際頻道依公司安排",
            )):
                source_lines.append(line)
                seen.add(line)

    if not source_lines:
        return ""

    compact_query = compact_text(user_text)
    asks_box = any(term in compact_query for term in (
        "機上盒", "幾台", "借用", "加裝", "額外付費",
    ))
    asks_channel_count = any(term in compact_query for term in (
        "幾個頻道", "多少頻道", "頻道數", "幾個台",
    ))

    if asks_box and not asks_channel_count:
        selected = [line for line in source_lines if "機上盒" in line or "加裝" in line]
    elif asks_channel_count and not asks_box:
        selected = [
            line for line in source_lines
            if "20～24" in line or "實際頻道依公司安排" in line
        ]
    else:
        selected = source_lines

    return "\n".join(f"- {line}" for line in selected)


def extract_basic_tv_monthly_fee(docs: List[Dict[str, Any]]) -> str | None:
    basic_markers = (
        "基本收費標準",
        "基本收視費",
        "有線電視基本收費",
        "tv_基本收費",
    )
    explicit_patterns = (
        r"(?:有線電視基本收視費|基本收視費|CATV)[\s\S]{0,100}?月繳[^$\d\n]{0,12}[$＄]?\s*([1-9]\d{2,4})",
        r"(?:有線電視基本收視費|基本收視費|CATV)[^。\n]{0,50}?[$＄]?\s*([1-9]\d{2,4})\s*元?\s*/?\s*月",
    )
    generic_basic_patterns = (
        r"月繳[^$\d\n]{0,12}[$＄]?\s*([1-9]\d{2,4})",
        r"[$＄]?\s*([1-9]\d{2,4})\s*元?\s*/\s*月",
    )
    new_install_patterns = (
        r"(?:新裝(?:機)?(?:優惠)?|新申裝)[^。\n]{0,60}?月繳[^$\d\n]{0,12}[$＄]?\s*([1-9]\d{2,4})",
        r"(?:新裝(?:機)?(?:優惠)?|新申裝)[^。\n]{0,60}?[$＄]?\s*([1-9]\d{2,4})\s*元?\s*/?\s*月",
    )

    preferred_docs: List[str] = []
    other_docs: List[str] = []
    for doc in docs:
        text = knowledge_doc_text(doc)
        compact = compact_text(text).lower()
        if any(marker in compact for marker in basic_markers):
            preferred_docs.append(text)
        else:
            other_docs.append(text)

    def collect_candidates(text: str, *, preferred: bool) -> List[tuple[int, int]]:
        candidates: List[tuple[int, int]] = []
        segments = [
            segment.strip()
            for segment in re.split(r"[\r\n]+|(?<=[。；;])\s*", text)
            if segment.strip()
        ]
        pattern_groups = (
            # A basic-fee document may list both the renewal/original price and
            # the currently offered new-install monthly price.  For a plain
            # "how much per month" question, prefer that explicit current
            # offer while still ignoring promotion-only documents below.
            (new_install_patterns, 155),
            (explicit_patterns, 90),
            (generic_basic_patterns, 25),
        )
        for segment in segments:
            compact_segment = compact_text(segment).lower()
            # These amounts describe an extra set-top box/package, not the
            # household's base cable-TV monthly fee.
            if any(
                marker in compact_segment
                for marker in ("第6台", "第六台", "加購", "分機費", "以上套餐")
            ):
                continue

            for patterns, base_score in pattern_groups:
                if not preferred and patterns is not explicit_patterns:
                    continue
                for pattern in patterns:
                    for match in re.finditer(pattern, segment, flags=re.IGNORECASE):
                        amount = int(match.group(1))
                        score = base_score + (15 if preferred else 0)
                        if any(marker in compact_segment for marker in ("基本收視費", "基本收費")):
                            score += 45
                        if sum(
                            marker in compact_segment
                            for marker in ("月繳", "季繳", "半年繳", "年繳")
                        ) >= 3:
                            score += 35
                        if "裝機費" in compact_segment:
                            score += 12
                        if any(marker in compact_segment for marker in ("新裝", "新申裝")):
                            score -= 8
                        candidates.append((score, amount))
        return candidates

    preferred_candidates: List[tuple[int, int]] = []
    for text in preferred_docs:
        preferred_candidates.extend(collect_candidates(text, preferred=True))
    if preferred_candidates:
        _, amount = max(preferred_candidates, key=lambda item: item[0])
        return f"{amount:,}"

    # Files about promotions often contain several monthly prices. Outside a
    # basic-fee document, only accept a value explicitly labelled as basic TV fee.
    other_candidates: List[tuple[int, int]] = []
    for text in other_docs:
        other_candidates.extend(collect_candidates(text, preferred=False))
    if other_candidates:
        _, amount = max(other_candidates, key=lambda item: item[0])
        return f"{amount:,}"
    return None


def explicit_company_label(user_text: str) -> str:
    compact_user_text = compact_text(user_text).lower()
    if not compact_user_text:
        return ""

    matches: List[tuple[int, str]] = []
    for profile in get_all_company_profiles():
        label = str(profile.get("class") or profile.get("company_name") or "").strip()
        names = {
            label,
            str(profile.get("company_name") or "").strip(),
        }
        for name in names:
            aliases = {
                name,
                re.sub(r"(?:有線|電訊|股份有限公司|有限公司)$", "", name).strip(),
            }
            for alias in aliases:
                compact_alias = compact_text(alias).lower()
                if len(compact_alias) >= 2 and compact_alias in compact_user_text:
                    matches.append((len(compact_alias), label))
    return max(matches)[1] if matches else ""


def apply_basic_tv_monthly_fee_concision(
    user_text: str,
    reply: str,
    docs: List[Dict[str, Any]],
) -> str:
    if not is_basic_tv_monthly_fee_only_query(user_text):
        return reply
    monthly_fee = extract_basic_tv_monthly_fee(docs)
    if not monthly_fee:
        return reply
    company_label = explicit_company_label(user_text)
    prefix = f"{company_label}有線電視" if company_label else "有線電視"
    return f"{prefix}基本收視費：月繳 ${monthly_fee} 元。"


def apply_basic_tv_two_year_fee_calculation(
    user_text: str,
    reply: str,
    docs: List[Dict[str, Any]],
) -> str:
    compact_user_text = compact_text(user_text)
    if not any(term in compact_user_text for term in ("兩年", "2年")):
        return reply

    for doc in docs:
        text = str(doc.get("answer") or "")
        annual_matches = re.findall(
            r"(?<!半)年繳(?:收視費)?\s*[:：]?\s*\$?\s*([\d,]+)",
            text,
        )
        install_match = re.search(
            r"年繳者[^\n]{0,40}?裝機費?優惠(?:價|為)?\s*[:：]?\s*\$?\s*([\d,]+)",
            text,
        ) or re.search(
            r"裝機(?:費)?優惠(?:價|為)?\s*[:：]?\s*\$?\s*([\d,]+)",
            text,
        )
        if not annual_matches or not install_match:
            continue
        annual_fee = int(annual_matches[-1].replace(",", ""))
        install_fee = int(install_match.group(1).replace(",", ""))
        total = annual_fee * 2 + install_fee
        return (
            f"有線電視新裝兩年費用：年繳收視費 {annual_fee:,} 元 × 2 "
            f"+ 首次裝機費 {install_fee:,} 元 = {total:,} 元。"
        )

    return reply


PROMOTION_FOCUSED_DETAIL_TERMS = (
    "除了", "其他", "贈品", "有送", "送什麼", "包含", "是否包含",
    "wifi", "wi-fi", "設備", "押金", "申請", "資格", "條件", "舊戶",
    "合約", "綁約", "違約", "活動期間", "line tv", "linetv", "litv",
    "point", "抽獎", "家電", "裝機", "費用", "價格", "價錢", "月繳",
    "半年繳", "年繳", "總共", "合計", "全部費用",
)


def campaign_source_lines(docs: List[Dict[str, Any]]) -> List[str]:
    lines: List[str] = []
    seen: set[str] = set()
    for doc in docs:
        for raw_line in str(doc.get("answer") or "").splitlines():
            line = raw_line.strip(" -")
            if not line:
                continue
            normalized = compact_text(line).casefold()
            if normalized in seen:
                continue
            seen.add(normalized)
            lines.append(line)
    return lines


def campaign_doc_field(doc: Dict[str, Any], field: str) -> str:
    source = doc.get("source") if isinstance(doc.get("source"), dict) else {}
    return str(doc.get(field) or source.get(field) or "").strip()


def is_structured_campaign_doc(doc: Dict[str, Any]) -> bool:
    """Keep catalog entries limited to records explicitly maintained as campaigns."""
    if not campaign_doc_field(doc, "campaign_name"):
        return False
    document_type = campaign_doc_field(doc, "document_type").casefold()
    record_type = campaign_doc_field(doc, "record_type").casefold()
    return document_type == "promotion_campaign" or record_type.startswith("campaign_")


PROMOTION_SCOPE_QUERY_HINTS = {
    "pure_network": (
        "目前有效 純網路 單辦寬頻 優惠方案 方案名稱 "
        "速率 月繳 季繳 半年繳 年繳 活動期間"
    ),
    "tv_network": (
        "目前有效 有線電視加網路 電視網路同裝 優惠方案 方案名稱 "
        "速率 月繳 季繳 半年繳 年繳 活動期間"
    ),
    "pure_tv": (
        "目前有效 純有線電視 第四台 單辦優惠 基本收視費 "
        "月繳 季繳 半年繳 年繳 裝機費 活動期間"
    ),
}


def build_promotion_scope_query(
    current_query: str,
    promotion_scope: str | None,
    promotion_query_kind: str | None,
) -> str:
    """Apply the model-selected promotion scope to retrieval, not routing."""
    if promotion_query_kind != "catalog":
        return str(current_query or "").strip()
    hint = PROMOTION_SCOPE_QUERY_HINTS.get(str(promotion_scope or ""))
    if not hint:
        return str(current_query or "").strip()
    return f"{hint} {current_query or ''}".strip()


def build_campaign_detail_context_query(
    current_query: str,
    memory: Dict[str, Any] | None,
    promotion_query_kind: str | None,
    *,
    allow_context: bool = True,
) -> str:
    """Keep the model-selected campaign attached to a semantic follow-up."""
    query = str(current_query or "").strip()
    if promotion_query_kind != "campaign_detail" or not allow_context:
        return query

    campaign_topic = str((memory or {}).get("last_campaign_topic") or "").strip()
    if not campaign_topic:
        return query
    if compact_text(campaign_topic).casefold() in compact_text(query).casefold():
        return query
    return f"{campaign_topic} {query}".strip()


def is_pure_tv_plan_doc(doc: Dict[str, Any]) -> bool:
    if is_tv_network_combo_doc(doc) or is_pure_network_plan_doc(doc):
        return False
    if is_pure_tv_rate_card_doc(doc):
        return True
    text = normalize_keyword_text(doc_search_text(doc))
    service_types = normalize_keyword_text(campaign_doc_field(doc, "service_types"))
    has_tv = any(term in f"{service_types} {text}" for term in ("純有線電視", "單辦有線電視", "第四台"))
    has_network = any(term in service_types for term in ("網路", "寬頻"))
    return has_tv and not has_network


def constrain_promotion_documents(
    docs: List[Dict[str, Any]],
    promotion_scope: str | None,
    promotion_query_kind: str | None,
    social_discount_requested: bool = False,
) -> List[Dict[str, Any]]:
    """Enforce the LLM contract against retrieved document metadata."""
    if promotion_query_kind not in {"catalog", "campaign_detail"}:
        return docs

    scoped_docs = [
        doc for doc in docs
        if social_discount_requested or not is_social_discount_doc(doc)
    ]
    if promotion_query_kind != "catalog":
        return scoped_docs
    if promotion_scope == "pure_network":
        return [doc for doc in scoped_docs if is_pure_network_plan_doc(doc)]
    if promotion_scope == "tv_network":
        return [doc for doc in scoped_docs if is_tv_network_combo_doc(doc)]
    if promotion_scope == "pure_tv":
        return [doc for doc in scoped_docs if is_pure_tv_plan_doc(doc)]
    return scoped_docs


def campaign_aliases(doc: Dict[str, Any]) -> List[str]:
    values = [
        campaign_doc_field(doc, "campaign_name"),
        *str(campaign_doc_field(doc, "campaign_aliases") or "").split("|"),
    ]
    aliases: List[str] = []
    seen: set[str] = set()
    for value in values:
        normalized = compact_text(value).casefold()
        if len(normalized) < 4 or normalized in seen:
            continue
        seen.add(normalized)
        aliases.append(value.strip())
    return aliases


def campaign_family_aliases(doc: Dict[str, Any]) -> List[str]:
    """Return an unnumbered family name only for disambiguated campaign lookup."""
    aliases: List[str] = []
    seen: set[str] = set()
    for alias in campaign_aliases(doc):
        value = re.sub(r"\s*(?:no|n[o0])\s*\d+.*$", "", alias, flags=re.IGNORECASE).strip()
        normalized = compact_text(value).casefold()
        if len(normalized) < 4 or normalized in seen:
            continue
        seen.add(normalized)
        aliases.append(value)
    return aliases


def find_named_campaign_docs(
    user_text: str,
    docs: List[Dict[str, Any]],
) -> tuple[str, List[Dict[str, Any]]]:
    query = compact_text(user_text).casefold()
    matches: List[tuple[int, int, str, Dict[str, Any]]] = []
    for doc in docs:
        campaign_name = campaign_doc_field(doc, "campaign_name")
        if not campaign_name:
            continue
        for alias in campaign_aliases(doc):
            normalized_alias = compact_text(alias).casefold()
            if query == normalized_alias:
                match_quality = 3
            elif normalized_alias in query:
                match_quality = 2
            elif is_high_confidence_campaign_alias_match(query, alias):
                match_quality = 1
            else:
                continue
            if match_quality:
                matches.append((match_quality, len(normalized_alias), campaign_name, doc))
                break

    if not matches:
        family_matches: List[tuple[str, Dict[str, Any]]] = []
        for doc in docs:
            campaign_name = campaign_doc_field(doc, "campaign_name")
            if not campaign_name:
                continue
            if any(
                compact_text(alias).casefold() in query
                for alias in campaign_family_aliases(doc)
            ):
                family_matches.append((campaign_name, doc))

        campaign_names = {
            compact_text(campaign_name).casefold()
            for campaign_name, _ in family_matches
        }
        # A shortened family name is safe only when retrieval has already
        # narrowed it to one concrete campaign.
        if len(campaign_names) != 1:
            return "", []

        campaign_name = family_matches[0][0]
        campaign_key = compact_text(campaign_name).casefold()
        return campaign_name, [
            doc for _, doc in family_matches
            if compact_text(campaign_doc_field(doc, "campaign_name")).casefold() == campaign_key
        ]

    _, _, campaign_name, _ = max(matches, key=lambda item: (item[0], item[1]))
    campaign_key = compact_text(campaign_name).casefold()
    selected = [
        doc for doc in docs
        if compact_text(campaign_doc_field(doc, "campaign_name")).casefold() == campaign_key
    ]
    return campaign_name, selected


CAMPAIGN_PERIOD_QUERY_TERMS = (
    "活動期間",
    "期間",
    "何時",
    "什麼時候",
    "到何時",
    "何時截止",
    "何時結束",
    "截止",
)


def build_campaign_valid_period_reply(
    user_text: str,
    docs: List[Dict[str, Any]],
) -> str:
    """Answer a named campaign's timing with its source-backed period only."""
    query = compact_text(user_text).casefold()
    if not any(term in query for term in CAMPAIGN_PERIOD_QUERY_TERMS):
        return ""

    campaign_name, campaign_docs = find_named_campaign_docs(user_text, docs)
    if not campaign_name:
        return ""

    periods: List[str] = []
    for doc in campaign_docs:
        period = campaign_doc_field(doc, "valid_period")
        if not period:
            period_lines = select_campaign_lines(campaign_source_lines([doc]), ("活動期間",), limit=1)
            period = period_lines[0] if period_lines else ""
        normalized = compact_text(period)
        if period and normalized and normalized not in {compact_text(value) for value in periods}:
            periods.append(period)

    if len(periods) == 1:
        return f"{campaign_name}活動期間：{periods[0]}。"
    if len(periods) > 1:
        return f"{campaign_name}各地區活動期間如下：\n" + "\n".join(
            f"- {period}" for period in periods
        )
    return ""


def is_broad_promotion_discovery_query(
    user_text: str,
    docs: List[Dict[str, Any]],
) -> bool:
    campaign_name, _ = find_named_campaign_docs(user_text, docs)
    if campaign_name:
        return False
    return (
        is_pure_network_catalog_query(user_text)
        or is_tv_network_install_option_query(user_text)
        or is_promotion_recommendation_query(user_text)
        or is_fresh_campaign_discovery_query(user_text)
    )


def compact_campaign_speeds(doc: Dict[str, Any], max_items: int = 3) -> str:
    """Return a short, readable speed preview from campaign metadata or content."""
    value = campaign_doc_field(doc, "speeds") or str(doc.get("answer") or "")
    matches = re.findall(
        r"\d+(?:\.\d+)?\s*(?:gbps|g|mbps|m)\s*/\s*\d+(?:\.\d+)?\s*(?:gbps|g|mbps|m)",
        value,
        flags=re.IGNORECASE,
    )
    speeds: List[str] = []
    seen: set[str] = set()
    for match in matches:
        normalized = re.sub(r"\s+", "", match).upper()
        if normalized in seen:
            continue
        seen.add(normalized)
        speeds.append(normalized)

    if not speeds:
        return ""
    preview = "、".join(speeds[:max_items])
    return f"{preview} 等" if len(speeds) > max_items else preview


def compact_campaign_rate_lines(
    doc: Dict[str, Any],
    max_items: int = 3,
) -> List[str]:
    """Extract comparable speed-and-price rows without unrelated campaign terms."""
    answer = str(doc.get("answer") or "")
    if not answer:
        source = doc.get("source") if isinstance(doc.get("source"), dict) else {}
        answer = str(source.get("content") or "")
    if not answer:
        return []

    speed_pattern = (
        r"\d+(?:\.\d+)?\s*(?:gbps|g|mbps|m)\s*/\s*"
        r"\d+(?:\.\d+)?\s*(?:gbps|g|mbps|m)"
    )
    rate_speed_pattern = (
        rf"(?<![\d.])(?:--?[A-Z][.、]\s*|[A-Z][.、]\s*)?"
        rf"(?P<speed>{speed_pattern})"
    )
    speed_matches = list(re.finditer(
        rate_speed_pattern,
        answer,
        flags=re.IGNORECASE,
    ))

    rows: List[str] = []
    seen_speeds: set[str] = set()
    for index, speed_match in enumerate(speed_matches):
        segment_end = (
            speed_matches[index + 1].start()
            if index + 1 < len(speed_matches)
            else len(answer)
        )
        raw_line = answer[speed_match.start():segment_end].splitlines()[0]
        speed = re.sub(r"\s+", "", speed_match.group("speed")).upper()
        if speed in seen_speeds:
            continue

        price_matches = re.findall(
            r"(原價|月繳|季繳|半年繳|年繳)\s*[:：]?\s*[$＄]?\s*([\d,]+)\s*元?",
            raw_line,
            flags=re.IGNORECASE,
        )
        actual_prices = [item for item in price_matches if item[0] != "原價"]
        selected_prices = actual_prices or price_matches
        if not selected_prices:
            continue

        seen_labels: set[str] = set()
        formatted_prices: List[str] = []
        for label, amount in selected_prices:
            if label in seen_labels:
                continue
            seen_labels.add(label)
            numeric_amount = int(amount.replace(",", ""))
            formatted_prices.append(f"{label} {numeric_amount:,} 元")

        if formatted_prices:
            rows.append(f"{speed}：" + "、".join(formatted_prices))
            seen_speeds.add(speed)
        if len(rows) >= max_items:
            break

    return rows


def select_promotion_catalog_documents(
    user_text: str,
    docs: List[Dict[str, Any]],
    intent: str | None = None,
    promotion_scope: str | None = None,
) -> tuple[bool, bool, List[Dict[str, Any]]]:
    """Select the source documents that will appear in a promotion catalog."""
    if intent == "promotion_named_campaign_selection":
        return False, False, []

    if promotion_scope == "pure_tv":
        return False, False, []

    pure_network_catalog = (
        promotion_scope == "pure_network"
        or intent == "pure_network_install_plan_query"
        or is_pure_network_catalog_query(user_text)
    )
    combo_catalog = (
        promotion_scope == "tv_network"
        or intent == "tv_network_install_plan_query"
        or is_tv_network_install_option_query(user_text)
    )
    if not (
        pure_network_catalog
        or combo_catalog
        or is_broad_promotion_discovery_query(user_text, docs)
    ):
        return pure_network_catalog, combo_catalog, []

    selected_docs: List[Dict[str, Any]] = []
    seen: set[str] = set()
    for doc in docs:
        if not is_structured_campaign_doc(doc):
            continue
        if is_social_discount_doc(doc):
            continue
        if pure_network_catalog and not is_pure_network_plan_doc(doc):
            continue
        if combo_catalog and not is_tv_network_combo_doc(doc):
            continue
        campaign_name = campaign_doc_field(doc, "campaign_name")
        if not campaign_name:
            continue
        key = compact_text(campaign_name).casefold()
        if key in seen:
            continue
        seen.add(key)
        selected_docs.append(doc)
        if len(selected_docs) >= 4:
            break

    return pure_network_catalog, combo_catalog, selected_docs


def build_promotion_catalog_clarify_context(
    user_text: str,
    docs: List[Dict[str, Any]],
    intent: str | None = None,
    promotion_scope: str | None = None,
) -> Dict[str, Any] | None:
    """Remember the exact dynamic campaign order shown to the customer."""
    pure_network_catalog, combo_catalog, selected_docs = select_promotion_catalog_documents(
        user_text,
        docs,
        intent=intent,
        promotion_scope=promotion_scope,
    )
    if not selected_docs:
        return None

    options: Dict[str, Dict[str, Any]] = {}
    selected_scope = (
        promotion_scope
        or ("pure_network" if pure_network_catalog else None)
        or ("tv_network" if combo_catalog else None)
    )
    for index, doc in enumerate(selected_docs, start=1):
        campaign_name = campaign_doc_field(doc, "campaign_name")
        if not campaign_name:
            continue
        options[campaign_name] = {
            "option_id": f"option_{index}",
            "entity_type": "knowledge_document",
            "route": "knowledge_query",
            "intent": "promotion_named_campaign_selection",
            "topic": campaign_name,
            "knowledge_query": (
                f"{campaign_name} 優惠方案 寬頻費用 贈送內容 裝機費 違約金"
            ),
            "requested_information": "寬頻費用、贈送內容、裝機費與違約金",
            "promotion_scope": selected_scope,
            "promotion_query_kind": "campaign_detail",
            "social_discount_requested": False,
            "document_id": campaign_doc_field(doc, "document_id"),
            "knowledge_base": campaign_doc_field(doc, "knowledge_base"),
            "reply": "",
        }

    if not options:
        return None
    return {
        "type": "campaign_catalog_selection",
        "topic": "優惠方案清單",
        "options": options,
    }


def build_promotion_catalog_reply(
    user_text: str,
    docs: List[Dict[str, Any]],
    intent: str | None = None,
    promotion_scope: str | None = None,
    promotion_query_kind: str | None = None,
) -> str:
    """Present broad promotion discovery as a compact, source-backed list."""
    if promotion_query_kind is not None and promotion_query_kind != "catalog":
        return ""
    pure_network_catalog, combo_catalog, selected_docs = (
        select_promotion_catalog_documents(
            user_text,
            docs,
            intent=intent,
            promotion_scope=promotion_scope,
        )
    )
    if not selected_docs:
        return ""

    requested_speeds = extract_requested_broadband_speeds(user_text)
    requested_text = str(user_text or "")
    requested_cycles = [
        label for label in PAYMENT_CYCLE_LABELS if label in requested_text
    ]
    if any(term in requested_text for term in ("一個月", "每月", "月租", "月費")):
        requested_cycles.append("月繳")
    if any(term in requested_text for term in ("一年", "每年")):
        requested_cycles.append("年繳")
    requested_cycles = list(dict.fromkeys(requested_cycles))

    def keep_requested_rates(rate_lines: List[str]) -> List[str]:
        if not requested_speeds:
            return rate_lines

        selected: List[str] = []
        for line in rate_lines:
            normalized = normalize_keyword_text(line)
            speed_part = re.split(r"[：:]", normalized, maxsplit=1)[0]
            if not any(
                speed_part == speed or speed_part.startswith(f"{speed}/")
                for speed in requested_speeds
            ):
                continue

            if requested_cycles:
                prefix = re.split(r"[：:]", line, maxsplit=1)[0].strip()
                prices = re.findall(
                    r"(月繳|季繳|半年繳|年繳)\s*([\d,]+)\s*元",
                    line,
                )
                matching_prices = [
                    f"{label} {amount} 元"
                    for label, amount in prices
                    if label in requested_cycles
                ]
                if matching_prices:
                    line = f"{prefix}：" + "、".join(matching_prices)
            selected.append(line)
        return selected

    rows: List[str] = []
    for doc in selected_docs:
        campaign_name = campaign_doc_field(doc, "campaign_name")
        service_types = re.sub(
            r"\s*\|\s*",
            "、",
            re.sub(r"\s+", " ", campaign_doc_field(doc, "service_types")),
        ).strip("、")
        valid_period = re.sub(
            r"\s+",
            " ",
            campaign_doc_field(doc, "valid_period"),
        ).strip()
        rate_lines = (
            compact_campaign_rate_lines(doc)
            if pure_network_catalog or combo_catalog
            else []
        )
        rate_lines = keep_requested_rates(rate_lines)
        if requested_speeds and not rate_lines:
            continue
        speeds = compact_campaign_speeds(doc) if not rate_lines else ""
        details: List[str] = []
        if service_types and not pure_network_catalog:
            details.append(f"類型：{service_types}")
        if rate_lines:
            details.append("速率與費用：\n" + "\n".join(
                f"      {line}" for line in rate_lines
            ))
        elif speeds:
            details.append(f"速率：{speeds}")
        if valid_period:
            details.append(f"活動期間：{valid_period}")

        row_number = len(rows) + 1
        row = f"{row_number}. {campaign_name}"
        if details:
            row += "\n" + "\n".join(f"   {detail}" for detail in details)
        rows.append(row)

    if not rows:
        return ""
    if pure_network_catalog:
        heading = "目前可參考的純網方案："
    elif combo_catalog:
        heading = "目前可參考的電視＋網路同裝方案："
    else:
        heading = "目前可參考的優惠方案："
    reply = heading + "\n\n" + "\n\n".join(rows)
    if requested_speeds:
        if combo_catalog:
            reply += "\n\n以上為電視＋網路同裝方案，所列費用包含有線電視與寬頻網路服務。"
        return reply
    return reply + "\n\n請輸入想了解的方案名稱或編號，我會先整理方案重點。"


def clean_campaign_line(line: str) -> str:
    value = str(line or "").strip(" -")
    value = re.sub(r"^[一二三四五六七八九十]+[、．.]\s*", "", value)
    value = re.sub(r"^\d+[、．]\s*", "", value)
    return re.sub(
        r"^\d+\.(?=\d+\s*(?:mbps|m)\s*/)",
        "",
        value,
        flags=re.IGNORECASE,
    )


def select_campaign_lines(lines: List[str], terms: tuple[str, ...], limit: int = 4) -> List[str]:
    selected: List[str] = []
    for line in lines:
        normalized = compact_text(line).casefold()
        if not any(compact_text(term).casefold() in normalized for term in terms):
            continue
        selected.append(clean_campaign_line(line))
        if len(selected) >= limit:
            break
    return selected


def campaign_field_value(line: str, labels: tuple[str, ...]) -> str:
    """Remove a repeated source label while preserving its factual value."""
    value = clean_campaign_line(line)
    label_pattern = "|".join(re.escape(label) for label in labels)
    value = re.sub(
        rf"^(?:{label_pattern})\s*[：:]\s*",
        "",
        value,
        flags=re.IGNORECASE,
    )
    value = value.replace(";", "，").replace("；", "，")
    return value.strip(" ，")


def campaign_context_docs(
    docs: List[Dict[str, Any]],
    memory: Dict[str, Any] | None = None,
) -> tuple[str, List[Dict[str, Any]]]:
    """Return documents belonging to the dynamically remembered campaign."""
    memory = memory or {}
    active_campaign = normalize_campaign_topic(str(memory.get("last_campaign_topic") or ""))
    candidates = [*docs, *(memory.get("last_knowledge_results") or [])]
    if active_campaign:
        active_key = compact_text(active_campaign).casefold()
        matched = [
            doc for doc in candidates
            if compact_text(campaign_doc_field(doc, "campaign_name")).casefold() == active_key
        ]
        if matched:
            return active_campaign, matched

    names = {
        campaign_doc_field(doc, "campaign_name")
        for doc in docs
        if campaign_doc_field(doc, "campaign_name")
    }
    if len(names) == 1:
        return next(iter(names)), docs
    return "", docs


def build_campaign_contract_followup_reply(
    user_text: str,
    docs: List[Dict[str, Any]],
    memory: Dict[str, Any] | None = None,
) -> str:
    """Render one requested contract fact after the LLM selects campaign detail."""
    query = compact_text(user_text).casefold()
    asks_penalty = any(term in query for term in ("違約金", "違約", "提前解約", "解約費"))
    asks_term = any(term in query for term in ("綁約多久", "綁多久", "合約多久", "綁約期間", "合約期間"))
    if not (asks_penalty or asks_term):
        return ""

    campaign_name, campaign_docs = campaign_context_docs(docs, memory)
    if not campaign_name:
        return ""
    lines = campaign_source_lines(campaign_docs)

    if asks_penalty:
        penalty_lines = select_campaign_lines(lines, ("提前解約", "違約金", "違約"), limit=1)
        if not penalty_lines:
            return ""
        date_range = parse_contract_date_range(user_text)
        base_penalty = extract_campaign_base_penalty(penalty_lines[0])
        if date_range and base_penalty is not None:
            install_date, termination_date = date_range
            fulfilled_days = (termination_date - install_date).days + 1
            if fulfilled_days <= 0:
                return ""
            total_days = 730
            unfulfilled_days = max(0, total_days - fulfilled_days)
            calculated = (
                Decimal(base_penalty) * Decimal(unfulfilled_days) / Decimal(total_days)
            )
            final_fee = int(calculated.quantize(Decimal("1"), rounding=ROUND_HALF_UP))
            return (
                f"{campaign_name}\n"
                f"裝機日：{install_date:%Y/%m/%d}\n"
                f"退租日：{termination_date:%Y/%m/%d}\n"
                f"已履約天數：{fulfilled_days} 天\n"
                f"未履約天數：730 - {fulfilled_days} = {unfulfilled_days} 天\n"
                f"違約金：{base_penalty:,} × ({unfulfilled_days} / 730) "
                f"≈ {final_fee:,} 元\n"
                f"最終應繳違約金：{final_fee:,} 元\n"
                "溫馨提醒：實際退租金額仍以退租當日系統結算與設備回收狀態為準。"
            )
        value = campaign_field_value(penalty_lines[0], ("違約金", "違約"))
        return f"{campaign_name}：{value}"

    term_lines = select_campaign_lines(lines, ("綁約條件", "綁約期間", "合約期間", "綁約"), limit=1)
    if not term_lines:
        return ""
    value = campaign_field_value(term_lines[0], ("綁約條件", "綁約期間", "合約期間", "綁約"))
    return f"{campaign_name}：{value}"


def parse_contract_date_range(text: str) -> tuple[date, date] | None:
    """Extract the first two Gregorian dates from a contract calculation turn."""
    matches = re.findall(r"(?<!\d)(20\d{2})[./-](\d{1,2})[./-](\d{1,2})(?!\d)", str(text or ""))
    if len(matches) < 2:
        return None
    try:
        parsed = [
            datetime.strptime(f"{year}-{month}-{day}", "%Y-%m-%d").date()
            for year, month, day in matches[:2]
        ]
    except ValueError:
        return None
    return parsed[0], parsed[1]


def extract_campaign_base_penalty(line: str) -> int | None:
    """Read the maintained base penalty from the selected campaign evidence."""
    value = clean_campaign_line(line)
    match = re.search(
        r"(?:提前解約|違約金|違約)[^\d]{0,24}\$?\s*([\d,]+)\s*元",
        value,
        flags=re.IGNORECASE,
    )
    if not match:
        return None
    try:
        return int(match.group(1).replace(",", ""))
    except ValueError:
        return None


def build_named_campaign_overview_reply(
    user_text: str,
    docs: List[Dict[str, Any]],
) -> str:
    """Keep a named campaign's first answer to the four customer-facing facts."""
    campaign_name, campaign_docs = find_named_campaign_docs(user_text, docs)
    if not campaign_name:
        return ""

    query = compact_text(user_text).casefold()
    if any(compact_text(term).casefold() in query for term in PROMOTION_FOCUSED_DETAIL_TERMS):
        return ""

    lines = campaign_source_lines(campaign_docs)
    rate_lines: List[str] = []
    for doc in campaign_docs:
        rate_lines.extend(compact_campaign_rate_lines(doc, max_items=3))
    rate_lines = list(dict.fromkeys(rate_lines))[:3]
    gift_lines = select_campaign_lines(
        lines,
        ("贈送", "line tv", "litv", "贈哈point", "贈point"),
        limit=2,
    )
    install_lines = select_campaign_lines(lines, ("裝機費",), limit=1)
    penalty_lines = select_campaign_lines(lines, ("提前解約", "違約金", "違約"), limit=1)

    sections = [f"方案名稱：{campaign_name}"]
    if rate_lines:
        sections.append("寬頻費用：\n" + "\n".join(f"- {line}" for line in rate_lines))
    if gift_lines:
        sections.append("贈送內容：\n" + "\n".join(f"- {line}" for line in gift_lines))
    if install_lines:
        install_value = campaign_field_value(install_lines[0], ("裝機費",))
        sections.append(f"裝機費：{install_value}")
    if penalty_lines:
        penalty_value = campaign_field_value(penalty_lines[0], ("違約金", "違約"))
        sections.append(f"違約金：{penalty_value}")
    return "\n".join(sections) if len(sections) > 1 else ""


def has_compact_promotion_reply(
    user_text: str,
    docs: List[Dict[str, Any]],
    memory: Dict[str, Any] | None = None,
    intent: str | None = None,
    promotion_scope: str | None = None,
    promotion_query_kind: str | None = None,
) -> bool:
    """Identify promotion turns that have a complete source-backed short format."""
    return bool(
        build_campaign_total_fee_reply(user_text, docs, memory=memory)
        or build_campaign_valid_period_reply(user_text, docs)
        or build_promotion_catalog_reply(
            user_text,
            docs,
            intent=intent,
            promotion_scope=promotion_scope,
            promotion_query_kind=promotion_query_kind,
        )
        or build_campaign_gift_followup_reply(user_text, docs)
        or build_campaign_contract_followup_reply(user_text, docs, memory=memory)
        or build_named_campaign_overview_reply(user_text, docs)
    )


def build_campaign_gift_followup_reply(
    user_text: str,
    docs: List[Dict[str, Any]],
) -> str:
    campaign_name, campaign_docs = find_named_campaign_docs(user_text, docs)
    query = compact_text(user_text).casefold()
    asks_gift = any(term in query for term in ("贈品", "有送", "送什麼", "line tv", "linetv", "litv"))
    if not campaign_name or not asks_gift:
        return ""

    gift_lines = select_campaign_lines(
        campaign_source_lines(campaign_docs),
        ("贈", "送", "line tv", "litv", "point", "抽獎", "家電"),
        limit=4,
    )
    if not gift_lines:
        return ""

    other_gift_lines = [
        line for line in gift_lines
        if not any(term in compact_text(line).casefold() for term in ("line tv", "linetv", "litv"))
    ]
    if any(term in query for term in ("除了", "其他")) and not other_gift_lines:
        return f"{campaign_name}目前資料列出的贈送內容為 LINE TV，未列其他贈品。"

    return f"{campaign_name}的贈送內容：\n" + "\n".join(f"- {line}" for line in gift_lines)


def build_campaign_total_fee_reply(
    user_text: str,
    docs: List[Dict[str, Any]],
    memory: Dict[str, Any] | None = None,
) -> str:
    """Calculate a requested annual campaign total from one matching document."""
    query = compact_text(user_text).casefold()
    if not any(term in query for term in ("總共", "總費用", "總金額", "合計", "裝到好", "全部費用")):
        return ""
    if "年繳" not in query:
        return ""
    speed_match = re.search(r"(\d+)\s*(?:mbps|m)", query, re.IGNORECASE)
    if not speed_match:
        return ""

    speed = speed_match.group(1)
    active_campaign = normalize_campaign_topic(
        str((memory or {}).get("last_campaign_topic") or "")
    )
    candidate_docs = list(docs)
    if active_campaign:
        active_key = compact_text(active_campaign).casefold()
        context_docs = [
            *docs,
            *((memory or {}).get("last_knowledge_results") or []),
        ]
        candidate_docs = [
            doc
            for doc in context_docs
            if compact_text(campaign_doc_field(doc, "campaign_name")).casefold() == active_key
        ]
        if not candidate_docs:
            return ""

    for doc in candidate_docs:
        lines = campaign_source_lines([doc])
        rate_line = next(
            (
                clean_campaign_line(line)
                for line in lines
                if re.search(rf"{re.escape(speed)}\s*(?:mbps|m)\s*/", line, re.IGNORECASE)
                and "年繳" in line
            ),
            "",
        )
        annual_match = re.search(r"(?<!半)年繳\s*\$?\s*([\d,]+)", rate_line)
        if not annual_match:
            continue

        text = "\n".join(lines)
        install_match = None
        for line in lines:
            if "裝機費" not in line:
                continue
            install_match = re.search(
                r"(?<!半)年繳(?:用戶)?[^；;。\n]*?"
                r"(?:優待為|裝機費(?:用戶)?(?:優待)?(?:為|:|：)?|費用(?:為|:|：)?)"
                r"\s*\$?\s*([\d,]+)",
                line,
            )
            if not install_match:
                install_match = re.search(
                    r"(?<!半)年繳(?:用戶)?\s*\$?\s*([\d,]+)",
                    line,
                )
            if install_match:
                break
        if not install_match:
            continue

        annual_fee = int(annual_match.group(1).replace(",", ""))
        install_fee = int(install_match.group(1).replace(",", ""))
        deposit_fee = 0 if re.search(r"半年繳[^\n]{0,30}以上免押|年繳[^\n]{0,30}免押", text) else None
        if deposit_fee is None:
            continue

        campaign_name = campaign_doc_field(doc, "campaign_name") or "此方案"
        total = annual_fee + install_fee + deposit_fee
        return (
            f"{campaign_name} {speed}M 年繳總費用：\n"
            f"年繳費用 {annual_fee:,} 元 + 裝機費 {install_fee:,} 元 + "
            f"設備押金 {deposit_fee:,} 元 = {total:,} 元。"
        )

    return ""


def build_multi_plan_broadband_price_reply(
    user_text: str,
    docs: List[Dict[str, Any]],
) -> str:
    """Render each knowledge-backed plan when a speed has multiple sources."""
    compact_user_text = compact_text(user_text).lower()
    speed_match = re.search(r"(\d+)\s*(?:mbps|m)", compact_user_text, flags=re.IGNORECASE)
    if not speed_match or not any(term in compact_user_text for term in ("費用", "多少錢", "價格", "價錢", "月租")):
        return ""

    speed = speed_match.group(1)
    rows: List[tuple[str, str]] = []
    seen_plans: set[str] = set()
    for doc in docs:
        plan_name = str(doc.get("campaign_name") or doc.get("question") or "").strip()
        answer = str(doc.get("answer") or "")
        rate_match = re.search(
            rf"(?im)^.*?{re.escape(speed)}\s*m\s*/\s*{re.escape(speed)}\s*m.*$",
            answer,
        )
        plan_key = compact_text(plan_name).lower()
        if not plan_key or not rate_match or plan_key in seen_plans:
            continue
        seen_plans.add(plan_key)
        rows.append((plan_name, rate_match.group(0).strip(" -")))

    if len(rows) < 2:
        return ""

    sections = [f"【方案 {index}】\n方案名稱：{name}\n{rate}" for index, (name, rate) in enumerate(rows, start=1)]
    return "目前可參考的方案如下：\n\n" + "\n\n".join(sections)


def build_next_tier_plan_fallback(
    docs: List[Dict[str, Any]],
    user_text: str = "",
) -> str:
    """Keep an upgrade recommendation usable when the summary model times out."""
    requested_speeds = [
        float(value)
        for value in re.findall(
            r"(\d+(?:\.\d+)?)\s*(?:mbps|gbps|m|g)",
            compact_text(user_text),
            flags=re.IGNORECASE,
        )
    ]
    current_speed = requested_speeds[0] if requested_speeds else None
    candidates: List[tuple[float, str, str, str]] = []

    for doc in docs:
        answer = str(doc.get("answer") or "")
        plan_name = str(
            doc.get("campaign_name")
            or doc.get("question")
            or doc.get("title")
            or ""
        ).strip()
        if not answer or not plan_name:
            continue

        lines = [line.strip(" -") for line in answer.splitlines() if line.strip()]
        rate_lines: List[tuple[float, str]] = []
        for line in lines:
            normalized_line = re.sub(r"^\d+[.、]\s*", "", line)
            speed_match = re.search(
                r"(\d+(?:\.\d+)?)\s*(?:mbps|m)\s*/\s*\d+(?:\.\d+)?\s*(?:mbps|m)",
                normalized_line,
                re.IGNORECASE,
            )
            if not speed_match or not any(
                term in normalized_line
                for term in ("月繳", "季繳", "半年繳", "年繳", "原價")
            ):
                continue
            rate_lines.append((float(speed_match.group(1)), normalized_line))
        if not rate_lines:
            continue

        explicit_upgrade_conditions = [
            line
            for line in lines
            if any(term in line for term in ("中途換約", "中途升級"))
        ]
        general_contract_conditions = [
            line
            for line in lines
            if any(term in line for term in ("綁約", "合約"))
        ]
        condition = next(
            iter(explicit_upgrade_conditions or general_contract_conditions),
            "",
        )
        condition = re.sub(
            r"^[一二三四五六七八九十]+[、.]\s*",
            "",
            condition,
        )
        condition = re.sub(
            r"^是否可(?=中途(?:換約|升級))",
            "",
            condition,
        )
        for speed, rate_line in rate_lines:
            if current_speed is None or speed > current_speed:
                candidates.append((speed, plan_name, rate_line, condition))

    if not candidates:
        return ""

    target_speed = min(item[0] for item in candidates)
    selected = [item for item in candidates if item[0] == target_speed]
    sections = []
    for _, plan_name, rate_line, condition in selected:
        parts = [f"方案名稱：{plan_name}", rate_line]
        if condition:
            parts.append(condition)
        sections.append("\n".join(parts))
    return "目前可參考的下一階方案如下：\n\n" + "\n\n".join(sections)


def build_combo_rate_inclusion_reply(
    user_text: str,
    docs: List[Dict[str, Any]],
) -> str:
    """Answer whether a quoted rate belongs to a TV-and-broadband package."""
    query = compact_text(user_text).casefold()
    requested_speeds = extract_requested_broadband_speeds(user_text)
    asks_inclusion = any(term in query for term in ("包含", "含哈tv", "含hatv", "含電視"))
    if not asks_inclusion or not requested_speeds:
        return ""

    for doc in docs:
        source = doc.get("source") if isinstance(doc.get("source"), dict) else {}
        service_type = " ".join([
            str(doc.get("service_types") or ""),
            str(source.get("service_types") or ""),
            str(doc.get("campaign_name") or ""),
            str(doc.get("question") or ""),
        ])
        if not any(term in service_type for term in ("電視網路同裝", "電視+網路", "電視＋網路")):
            continue

        answer = str(doc.get("answer") or "")
        rate_line = next(
            (
                line.strip(" -")
                for line in answer.splitlines()
                if all(
                    speed in normalize_keyword_text(line)
                    for speed in requested_speeds
                )
            ),
            "",
        )
        if not rate_line:
            continue

        rate_line = re.sub(
            r"^\d+[.、](?=\d+(?:\.\d+)?\s*(?:mbps|m)\s*/)",
            "",
            rate_line,
            flags=re.IGNORECASE,
        )

        plan_name = str(
            doc.get("campaign_name") or doc.get("question") or "此方案"
        ).strip()
        return (
            f"是的，{rate_line} 為「{plan_name}」的電視＋網路同裝方案，"
            "費用包含有線電視與寬頻網路服務。"
        )

    return ""


def build_combo_service_inclusion_reply(
    user_text: str,
    docs: List[Dict[str, Any]],
) -> str:
    """Confirm the service scope for an abbreviated combo-plan follow-up."""
    query = compact_text(user_text).casefold()
    if not any(term in query for term in ("兩個加起來", "兩個一起", "都有包含", "都包含")):
        return ""

    for doc in docs:
        source = doc.get("source") if isinstance(doc.get("source"), dict) else {}
        service_type = " ".join([
            str(doc.get("service_types") or ""),
            str(source.get("service_types") or ""),
            str(doc.get("campaign_name") or ""),
            str(doc.get("question") or ""),
        ])
        if not any(term in service_type for term in ("電視網路同裝", "電視+網路", "電視＋網路")):
            continue
        plan_name = str(doc.get("campaign_name") or doc.get("question") or "此方案").strip()
        return (
            f"是的，「{plan_name}」是電視＋網路同裝方案，"
            "方案費用包含有線電視與寬頻網路服務；實際金額會依選擇的速率與繳別不同。"
        )

    return ""


def build_hatv_hatnet_combo_overview_reply(
    user_text: str,
    docs: List[Dict[str, Any]],
) -> str:
    """Render a compact, source-backed overview for the paired services."""
    if not is_hatv_hatnet_combo_request(user_text):
        return ""

    for doc in docs:
        source = doc.get("source") if isinstance(doc.get("source"), dict) else {}
        service_type = " ".join([
            str(doc.get("service_types") or ""),
            str(source.get("service_types") or ""),
            str(doc.get("campaign_name") or ""),
            str(doc.get("question") or ""),
        ])
        if not any(term in service_type for term in ("電視網路同裝", "電視+網路", "電視＋網路")):
            continue

        lines = [
            line.strip(" -")
            for line in str(doc.get("answer") or "").splitlines()
            if line.strip(" -")
        ]
        rate_lines = [
            re.sub(
                r"^\d+[.、](?=\d+(?:\.\d+)?\s*(?:mbps|m)\s*/)",
                "",
                line,
                flags=re.IGNORECASE,
            )
            for line in lines
            if re.search(r"\d+(?:\.\d+)?\s*(?:mbps|m)\s*/\s*\d+(?:\.\d+)?\s*(?:mbps|m)", line, re.IGNORECASE)
            and any(term in line for term in ("月繳", "季繳", "半年繳", "年繳"))
        ]
        if not rate_lines:
            continue

        plan_name = str(
            doc.get("campaign_name") or doc.get("question") or "此電視＋網路同裝方案"
        ).strip()
        conditions = [
            line for line in lines
            if any(term in line for term in ("舊戶", "無合約", "中途換約", "中途升級"))
        ]
        parts = [
            "目前可參考的電視＋網路同裝方案如下：",
            f"方案名稱：{plan_name}",
            *rate_lines,
        ]
        if conditions:
            parts.append(conditions[0])
        return "\n".join(parts)

    return ""


def extract_knowledge_evidence_terms(user_text: str) -> set[str]:
    """Create query anchors that work for Chinese text without word spacing."""
    query = compact_text(user_text).casefold()
    terms: set[str] = set()
    for token in re.findall(r"[\u4e00-\u9fff]{2,}|[a-z0-9]{2,}", query):
        if token in {"請問", "您好", "可以", "怎麼", "如何", "幫我", "一下"}:
            continue
        terms.add(token)
        if re.fullmatch(r"[\u4e00-\u9fff]+", token):
            terms.update(token[index:index + 2] for index in range(len(token) - 1))
    return {term for term in terms if len(term) >= 2}


def extract_knowledge_primary_terms(user_text: str) -> set[str]:
    """Prefer the action at the end of a Chinese request over the service name."""
    query = compact_text(user_text).casefold()
    terms: set[str] = set()
    for token in re.findall(r"[\u4e00-\u9fff]{2,}|[a-z0-9]{2,}", query):
        if re.fullmatch(r"[\u4e00-\u9fff]+", token):
            terms.update(
                token[index:index + 2]
                for index in range(max(0, len(token) - 4), len(token) - 1)
            )
        else:
            terms.add(token)
    return {term for term in terms if len(term) >= 2}


def has_knowledge_reply_evidence(user_text: str, reply: str) -> bool:
    normalized_reply = compact_text(reply).casefold()
    evidence_terms = extract_knowledge_evidence_terms(user_text)
    return bool(normalized_reply and evidence_terms and any(
        term in normalized_reply for term in evidence_terms
    ))


def build_evidence_compact_fallback(
    user_text: str,
    docs: List[Dict[str, Any]],
    *,
    max_lines: int = 6,
    max_chars: int = 900,
) -> str:
    """Select source-backed lines when the knowledge summarizer is unavailable.

    This is deliberately a presentation fallback, not an intent decision: the
    LLM has already selected the knowledge route and the evidence filter has
    already retained the documents.  It prevents a transient summary failure
    from exposing a whole campaign or rate-card document to a customer.
    """
    query = compact_text(user_text).casefold()
    meaningful_terms = extract_knowledge_evidence_terms(user_text)
    primary_terms = extract_knowledge_primary_terms(user_text)
    if not query or not meaningful_terms:
        return ""

    candidates: List[tuple[int, int, str]] = []
    for doc_index, doc in enumerate(docs):
        answer = sanitize_knowledge_answer(doc.get("answer", ""))
        if not answer:
            continue
        source_lines = [
            line.strip(" -")
            for line in re.split(r"[\r\n]+|(?<=。)", answer)
            if line.strip(" -")
        ]
        for line_index, line in enumerate(source_lines):
            normalized_line = compact_text(line).casefold()
            if not normalized_line:
                continue
            score = sum(
                (len(term) * 4 if len(term) > 2 else 3)
                for term in meaningful_terms
                if term in normalized_line
            )
            score += sum(
                10 for term in primary_terms if term in normalized_line
            )
            if any(term in query for term in ("費用", "月費", "月租", "價格", "多少", "年繳", "半年繳")):
                score += sum(
                    3 for term in ("月繳", "季繳", "半年繳", "年繳", "費用", "售價")
                    if term in normalized_line
                )
            if any(term in query for term in ("如何", "怎麼", "申請", "辦理", "流程", "開通")):
                score += sum(
                    3 for term in ("步驟", "申請", "辦理", "登入", "點選", "前往")
                    if term in normalized_line
                )
            if score:
                candidates.append((score, -(doc_index * 1000 + line_index), line))

    if not candidates:
        return ""

    selected: List[str] = []
    seen = set()
    for _, _, line in sorted(candidates, reverse=True):
        normalized_line = compact_text(line).casefold()
        if normalized_line in seen:
            continue
        if sum(len(item) for item in selected) + len(line) > max_chars:
            continue
        selected.append(line)
        seen.add(normalized_line)
        if len(selected) >= max_lines:
            break

    return "\n".join(selected)


def format_multiple_plan_sections(text: str) -> str:
    value = str(text or "").strip()
    if value.count("【方案名稱】") < 2:
        return value

    numbered_headings = re.findall(r"【方案\s*\d+】", value)
    if len(numbered_headings) >= 2:
        return re.sub(
            r"(【方案\s*\d+】)[ \t]*\n+[ \t]*【方案名稱】",
            r"\1",
            value,
        ).strip()

    index = 0

    def replace_marker(_match) -> str:
        nonlocal index
        index += 1
        prefix = "" if index == 1 else "\n\n"
        return f"{prefix}【方案 {index}】"

    return re.sub(r"【方案名稱】", replace_marker, value).strip()


def apply_restricted_channel_reply_label(user_text: str, reply: str) -> str:
    """Keep restricted-channel answers explicit without changing unrelated replies."""
    value = str(reply or "").strip()
    if not value or not is_restricted_channel_purchase_query(user_text):
        return value
    if any(term in value for term in ("成人頻道", "限制級頻道", "成人／限制級")):
        return value
    if value.startswith("購買方式："):
        return value.replace("購買方式：", "成人／限制級頻道購買方式：", 1)
    return f"成人／限制級頻道購買方式：\n{value}"


def apply_customer_reply_policies(
    user_text: str,
    reply: str,
    docs: List[Dict[str, Any]],
    memory: Dict[str, Any] | None = None,
) -> str:
    value = format_customer_reply_text(reply)
    compact_user_text = compact_text(user_text)
    if (
        any(term in compact_user_text for term in ("費用", "價格", "價錢", "月租", "多少錢", "優惠", "方案", "裝機"))
        and "移機" not in compact_user_text
    ):
        value = re.sub(r"依地址與(?:狀態|方案|可申辦內容|施工狀況)確認", "由客服確認申辦條件", value)
        value = re.sub(r"依地址/方案確認", "由客服確認方案", value)
        value = re.sub(r"依地址與活動資格確認", "依合約狀態與活動資格確認", value)
        value = re.sub(r"客服依地址確認", "客服依合約狀態確認", value)
    if is_social_discount_stacking_query(user_text, docs):
        return get_policy_text(
            memory,
            "promotion.social_discount_stacking",
            "reply",
            SOCIAL_DISCOUNT_STACKING_RULE,
        )

    if should_add_discount_stacking_caution(user_text, docs):
        compact_reply = compact_text(value)
        if not any(term in compact_reply for term in ("不可承諾", "不得承諾", "不可併用", "需確認", "由客服確認", "重複適用需依")):
            caution = get_policy_text(
                memory,
                "promotion.discount_stacking_caution",
                "reply",
                DISCOUNT_STACKING_CAUTION,
            )
            value = f"{value}\n{caution}".strip()
    value = apply_monthly_price_correction(value, docs)
    value = apply_basic_tv_two_year_fee_calculation(user_text, value, docs)
    value = apply_basic_tv_monthly_fee_concision(user_text, value, docs)
    value = format_multiple_plan_sections(value)
    value = apply_restricted_channel_reply_label(user_text, value)
    return value


def format_tool_result(tool_name: str, tool_result: Dict[str, Any]) -> str:
    if not tool_result.get("success"):
        return tool_result.get("message", "資料不足，請再補充必要資訊。")

    if tool_name == "search_bill":
        bills = tool_result.get("data", {}).get("bills", [])
        if bills:
            lines = ["已為您查詢帳單："]
            for b in bills:
                lines.append(f"{b['month']}：{b['amount']}元（{b['status']}）")
            return "\n".join(lines)
        return tool_result.get("message", "目前查無帳單資料")

    return tool_result.get("message", "已處理完成")


def remember_bill_query_status(memory: Dict[str, Any], tool_result: Dict[str, Any]) -> Dict[str, Any]:
    data = tool_result.get("data") or {}
    status = str(data.get("bill_status") or "").strip()
    if not status:
        message = str(tool_result.get("message") or "")
        if "尚無須繳納" in message or "帳務狀況正常" in message:
            status = "no_unpaid"
        elif "合計" in message or "繳費到期日" in message:
            status = "payable"
        else:
            status = "unknown"

    memory["last_bill_query_status"] = {
        "status": status,
        "message": str(tool_result.get("message") or ""),
    }
    return memory


def remember_tv_reactivation_status(memory: Dict[str, Any], tool_result: Dict[str, Any]) -> Dict[str, Any]:
    known = memory.setdefault("known_info", {})
    data = tool_result.get("data") or {}
    raw = data.get("raw") if isinstance(data, dict) else {}
    raw = raw if isinstance(raw, dict) else {}
    message = str(tool_result.get("message") or "")
    raw_message = str(raw.get("msg") or raw.get("api_msg") or "")
    combined = f"{message} {raw_message}"

    if "已暫復" in combined and ("無法重復" in combined or "無法重複" in combined):
        known["tv_reactivation_status"] = "already_temp_restored"
        known["tv_reactivation_message"] = message.strip()
    elif tool_result.get("success") and ("復線成功" in combined or "申請復線成功" in combined):
        known["tv_reactivation_status"] = "requested"
        known["tv_reactivation_message"] = message.strip()

    memory["known_info"] = known
    return memory


def build_repair_ticket_flow_disabled_reply(memory: Dict[str, Any]) -> str:
    profile = get_company_profile((memory or {}).get("company_code", DEFAULT_TV_CABLE))
    repair_link = build_company_link(profile, "維修申告")
    known = (memory or {}).get("known_info") or {}
    download_speed = known.get("download_speed")
    low_speed_context = ""
    if isinstance(download_speed, (int, float)) and download_speed < 10:
        low_speed_context = f"目前測得下載速度僅 {download_speed:g} Mbps，尚未恢復正常。\n"
    if repair_link:
        return (
            f"{low_speed_context}您好，為更完整了解您的需求，建議轉由真人客服協助確認及安排。\n"
            f"若要報修，您也可填寫 {repair_link}\n"
            "送出需求，我們將安排專人與您聯繫協助處理，謝謝。"
        )
    return f"{low_speed_context}您好，為更完整了解您的需求，建議轉由真人客服協助確認及安排，謝謝。"


def build_install_application_reply(memory: Dict[str, Any]) -> str:
    """Provide the configured installation path after the LLM selects it."""
    profile = get_company_profile((memory or {}).get("company_code", DEFAULT_TV_CABLE))
    install_link = build_company_link(profile, "裝機申告")
    install_channel = (
        f"您可透過{install_link}填寫需求，由專人與您聯繫；"
        "也可轉由真人客服協助辦理。"
        if install_link
        else "目前公司資訊未設定裝機申告連結，建議轉由真人客服協助辦理。"
    )
    return (
        "您好，歡迎申請網路裝機！可先參考目前可申辦的寬頻速率與優惠方案，"
        "實際費用與裝機條件仍須依服務地區及活動資格確認。\n"
        f"{install_channel}"
    )


INSTALL_APPLICATION_ROUTER_INTENTS = frozenset({
    "internet_install_application_guidance",
    "internet_install_application_info",
    "internet_installation_application_info",
    "new_internet_install_inquiry",
})


def is_install_application_router_intent(router: Dict[str, Any]) -> bool:
    """Map model-selected new-installation intent variants to one SOP."""
    return str((router or {}).get("intent") or "").strip().lower() in (
        INSTALL_APPLICATION_ROUTER_INTENTS
    )


def disable_repair_ticket_flow(memory: Dict[str, Any], tool_name: str) -> Dict[str, Any]:
    known = memory.setdefault("known_info", {})
    for slot in REPAIR_TICKET_SLOT_NAMES:
        if slot == "issue_description":
            continue
        known.pop(slot, None)

    known["repair_ready"] = "no"
    known["repair_flow_status"] = "disabled"
    # The online repair tool is currently disabled, but the conversation is
    # still in a repair hand-off context. Keep a lightweight marker so a short
    # follow-up such as "還是沒恢復" does not restart intent clarification.
    known["repair_followup_active"] = "yes"
    memory["known_info"] = known
    memory["pending_tool"] = None
    memory["pending_tool_args"] = []
    memory["last_tool"] = None
    memory["last_tool_result"] = {
        "success": False,
        "tool_name": tool_name,
        "message": build_repair_ticket_flow_disabled_reply(memory),
        "data": {
            "missing": [],
            "disabled": True,
        },
    }
    return memory


def disable_customer_tool_flow(memory: Dict[str, Any], tool_name: str) -> Dict[str, Any]:
    known = memory.setdefault("known_info", {})
    for slot in DISABLED_CUSTOMER_TOOL_SLOT_NAMES:
        known.pop(slot, None)

    known["disabled_tool"] = tool_name
    memory["known_info"] = known
    memory["pending_tool"] = None
    memory["pending_tool_args"] = []
    memory["last_tool"] = None
    memory["last_tool_result"] = {
        "success": False,
        "tool_name": tool_name,
        "message": CUSTOMER_TOOL_FLOW_DISABLED_MESSAGE,
        "data": {
            "missing": [],
            "disabled": True,
        },
    }
    return memory


def attach_llm_latency(latency: Dict[str, Any], trace_token) -> Dict[str, Any]:
    events = finish_llm_trace(trace_token)
    latency["llm_calls"] = len(events)
    latency["llm_total"] = round(
        sum(float(event.get("duration_sec", 0.0)) for event in events),
        3,
    )
    latency["llm_events"] = events
    return latency


def sanitize_knowledge_answer(answer: str) -> str:
    value = str(answer or "").strip()
    if not value:
        return ""

    compact = value.replace("\n", " ")
    match = re.search(
        r"answer\s*[:：]\s*(.*?)(?:\s*[;；]\s*company\s*[:：]|$)",
        compact,
        flags=re.IGNORECASE | re.DOTALL,
    )
    if match:
        return match.group(1).strip(" ;；")

    return value


CUSTOMER_REPLY_URL_RE = re.compile(
    r"(?:[a-z][a-z0-9+.-]*://|www\.)[^\s<>\"']+",
    flags=re.IGNORECASE,
)


def _replace_customer_text_outside_urls(
    value: str,
    pattern: str,
    replacement: str,
) -> str:
    """Apply customer-facing wording replacements without altering URLs."""
    parts = []
    cursor = 0
    for url_match in CUSTOMER_REPLY_URL_RE.finditer(value):
        parts.append(
            re.sub(
                pattern,
                replacement,
                value[cursor : url_match.start()],
                flags=re.IGNORECASE,
            )
        )
        parts.append(url_match.group(0))
        cursor = url_match.end()
    parts.append(re.sub(pattern, replacement, value[cursor:], flags=re.IGNORECASE))
    return "".join(parts)


def sanitize_customer_facing_jargon(text: str) -> str:
    """Remove internal implementation and industry shorthand from customer replies."""
    value = str(text or "").strip()
    if not value:
        return ""

    replacements = (
        (r"(?:根據|依據)\s*(?:公司)?知識庫(?:內|中|的)?(?:查到|檢索到)?的?資料", "根據目前查到的資料"),
        (r"(?:公司)?知識庫(?:內|中)", "目前查到的資料中"),
        (r"(?:根據|依據)\s*RAG\s*(?:查到|檢索到)?的?資料", "根據目前查到的資料"),
        (r"RAG\s*(?:內|中|資料中)", "目前查到的資料中"),
        (r"帳務\s*API", "查詢結果"),
        (r"正式\s*API", "正式服務"),
        (r"(?<![A-Za-z0-9_])(?:CUST\s*)?API(?![A-Za-z0-9_])", "系統"),
        (r"(?<![A-Za-z0-9_])RAG(?![A-Za-z0-9_])", "目前查到的資料"),
        (r"(?<![A-Za-z0-9_])CATV(?![A-Za-z0-9_])", "有線電視"),
        (r"(?<![A-Za-z0-9_])STB(?![A-Za-z0-9_])", "數位機上盒"),
        (r"(?<![A-Za-z0-9_])BB(?![A-Za-z0-9_])", "寬頻網路"),
    )
    for pattern, replacement in replacements:
        value = _replace_customer_text_outside_urls(value, pattern, replacement)

    value = re.sub(
        r"目前查不到明確(?:的)?(?:線上)?申請方式[，,]\s*建議由客服協助確認地址是否可安裝並安排申辦[。.]?",
        "實際可安裝區域、施工條件與可約時間，需由客服依地址確認。",
        value,
    )
    value = re.sub(
        r"目前查不到明確(?:的)?(?:線上)?申請方式[。.]?",
        "申辦細節需由客服依地址與方案確認。",
        value,
    )
    value = re.sub(
        r"目前查不到明確資訊[，,]?",
        "這部分需由客服依實際狀況確認，",
        value,
    )

    for customer_term in (
        "正式服務",
        "有線電視",
        "數位機上盒",
        "寬頻網路",
    ):
        value = re.sub(rf"[ \t　]*{customer_term}[ \t　]*", customer_term, value)

    value = re.sub(r"^不是[，,]\s*目前資料顯示", "目前", value, flags=re.MULTILINE)
    value = value.replace("目前資料顯示", "目前")
    value = re.sub(r"目前查到的資料\s*目前查到的資料", "目前查到的資料", value)
    return value.strip()


CUSTOMER_REPLY_FIELD_LABEL_RE = re.compile(
    r"【(?:方案名稱|適用對象|申請方式|申請條件|優惠內容|限制條件|備註|注意事項)】"
)
CUSTOMER_REPLY_PLAIN_FIELD_LABEL_RE = re.compile(
    r"(?<!\n)(方案名稱|活動期間|裝機費|網路設備押金|繳別|舊戶是否可參加|中途換約或升級|贈加值服務|"
    r"借用加值設備二擇一|借用一台聯網機上盒|WIFI設備|居家智慧攝影機|售價|綁約期間|限制條件|注意事項)\s*[：:]"
)
CUSTOMER_REPLY_CHINESE_ITEM_RE = re.compile(r"(?<!\n)([一二三四五六七八九十]+[、])")
CUSTOMER_REPLY_NUMBERED_ITEM_RE = re.compile(r"(?<![\n$＄,\d])(\d+[、])")
CUSTOMER_REPLY_DOTTED_ITEM_RE = re.compile(r"(?<![\n$＄,\d])(\d+\.)[ \t　]+(?=\S)")
CUSTOMER_REPLY_ORPHAN_FEE_HEADER_RE = re.compile(
    r"^\s*(?:(?:\d+[.)]\s*)?第|第\s*\d+[.)]\s*第)\s*[：:]?\s*$"
)
CUSTOMER_REPLY_ORPHAN_NUMBER_RE = re.compile(r"^\s*\d+[.)]\s*$")
CUSTOMER_REPLY_FEE_RULE_NUMBER_RE = re.compile(
    r"^(\d+[.)]\s+)(?=(?:第\s*)?\d|第\s*[一二三四五六七八九十]|分機|若|如|已|第\s*6)"
)


def format_customer_reply_text(text: str) -> str:
    value = sanitize_customer_facing_jargon(sanitize_knowledge_answer(text))
    if not value:
        return ""

    value = re.sub(r"([$＄])\s*\n\s*(?=\d)", r"\1", value)
    value = re.sub(r"(?<=\d),\s*\n\s*(?=\d{3}(?:\D|$))", ",", value)
    value = re.sub(r"([$＄]?\s*)(\d{1,2}),(\d)(\d{3})(?=\D|$)", r"\1\2\3,\4", value)
    # LLM summaries occasionally wrap a payment label away from its amount.
    # Keep each rate/payment row intact without flattening intentional sections.
    value = re.sub(
        r"((?:月繳|季繳|半年繳|年繳|月租)(?:費)?[ \t　]*[:：]?[ \t　]*(?:[$＄][ \t　]*)?)"
        r"[ \t　]*[\r\n]+[ \t　]*(?=\d)",
        r"\1 ",
        value,
    )
    value = re.sub(r"(二擇)\s*\n\s*(一)", r"\1\2", value)
    value = re.sub(r"(第)\s*\n\s*(?=\d|[一二三四五六七八九十])", r"\1", value)
    value = re.sub(r"\s*(" + CUSTOMER_REPLY_FIELD_LABEL_RE.pattern + r")\s*", r"\n\1\n", value)
    value = CUSTOMER_REPLY_PLAIN_FIELD_LABEL_RE.sub(r"\n\1：", value)
    value = re.sub(r"新[ \t　]*[\r\n]+[ \t　]*(裝機費\s*[：:])", r"新\1", value)
    value = re.sub(r"其他[ \t　]*[\r\n]+[ \t　]*(繳別\s*[：:])", r"其他\1", value)
    value = CUSTOMER_REPLY_CHINESE_ITEM_RE.sub(r"\n\1", value)
    value = re.sub(r"\s*貼心提醒[：:，,]?\s*", "\n貼心提醒：\n", value)

    def split_numbered_item(match: re.Match) -> str:
        number_text = match.group(1)[:-1]
        prefix = value[max(0, match.start() - 4):match.start()].rstrip()
        # Quantities such as "充電器 ×2、料理鍋 ×4" are not numbered-list
        # markers. Keep the multiplier and its number together.
        if prefix.endswith(("×", "x", "X", "*")):
            return match.group(1)
        # Large values followed by "、" are usually prices such as
        # "月繳 399、季繳 1,197", not numbered list markers.
        if int(number_text) > 20:
            return match.group(1)
        return f"\n{match.group(1)}"

    value = CUSTOMER_REPLY_NUMBERED_ITEM_RE.sub(split_numbered_item, value)
    # The summary model sometimes changes source-list markers from "1、" to
    # "1.". Treat both forms as lists so a long customer-facing response does
    # not collapse into one unreadable paragraph.
    value = CUSTOMER_REPLY_DOTTED_ITEM_RE.sub(
        lambda match: f"{split_numbered_item(match)} ",
        value,
    )
    value = re.sub(r"二擇\s*\n\s*一[、,，]", "二擇一，", value)
    value = re.sub(r"\n([一二三四五六七八九十]+、)\n", r"\n\1", value)
    value = re.sub(r"\n(\d+、)\n", r"\n\1", value)
    value = re.sub(r"\s*(項目\s*\d+\s*[：:])\s*", r"\n\1", value)
    value = re.sub(r"\s*(-\s*優惠(?:期間|後收費金額)[：:])\s*", r"\n\1", value)
    value = re.sub(r"\n{3,}", "\n\n", value)
    lines = []
    for raw_line in value.splitlines():
        line = raw_line.strip()
        if (
            not line
            or CUSTOMER_REPLY_ORPHAN_FEE_HEADER_RE.match(line)
            or CUSTOMER_REPLY_ORPHAN_NUMBER_RE.match(line)
        ):
            continue
        # A summary may flatten several prize rows into one line. When a line
        # contains multiple explicit quantities, restore one prize per line.
        if len(re.findall(r"[×xX*]\s*\d+", line)) > 1:
            line = re.sub(r"([×xX*]\s*\d+)[、，]\s*(?=\S)", r"\1\n", line)
        line = re.sub(r"^\d+[.)]\s*(?=【)", "", line)
        line = CUSTOMER_REPLY_FEE_RULE_NUMBER_RE.sub("", line)
        lines.append(line)
    formatted = "\n".join(line for line in lines if line).strip()
    return format_multiple_plan_sections(formatted)


def is_fee_reply_formatting_context(user_text: str, reply: str) -> bool:
    combined = compact_text(f"{user_text}\n{reply}")
    if not combined:
        return False
    return any(
        term in combined
        for term in (
            "費用",
            "收費",
            "月租",
            "月繳",
            "半年繳",
            "年繳",
            "季繳",
            "多少錢",
            "價格",
            "價錢",
            "裝機費",
            "押金",
            "分機費",
            "機上盒",
            "繳費",
            "方案",
            "優惠",
            "贈品",
        )
    )


def finalize_customer_reply(user_text: str, reply: str) -> str:
    value = sanitize_customer_facing_jargon(reply)
    value = sanitize_human_handoff_keyword_instruction(value)
    if is_fee_reply_formatting_context(user_text, value):
        value = format_customer_reply_text(value)
    return sanitize_customer_facing_jargon(value)


def _has_link_for_label(text: str, label: str, url: str) -> bool:
    link_icon = "\U0001f517"
    normalized_text = html.unescape(text)
    if url and html.unescape(url) in normalized_text:
        return True
    if label == "官網" and re.search(
        r"官網\s*[：:]?\s*(?:https?://|<a\b[^>]*\bhref=[\"']https?://)",
        normalized_text,
        flags=re.IGNORECASE,
    ):
        # A named third-party website, such as the TINP speed-test site, has
        # already satisfied the nearby website mention. Do not append the
        # cable company's home page as an unrelated second "official site".
        return True
    if label == "官網" and re.search(
        r"台基科官網[^\n]*https?://(?:www\.)?tinp\.net\.tw/",
        normalized_text,
        flags=re.IGNORECASE,
    ):
        return True
    return bool(re.search(
        rf"[［【\[]\s*{re.escape(label)}\s*{link_icon}?\s*[］】\]]\s*https?://",
        normalized_text,
    ))


def _known_reply_links(memory: Dict[str, Any]) -> list[tuple[str, tuple[str, ...], str]]:
    profile = get_company_profile((memory or {}).get("company_code", DEFAULT_TV_CABLE))
    links = []
    for label, url in extract_company_links(profile):
        mentions = [label]
        if label == "官網":
            mentions.extend(["公司官網", "官方網站"])
        if label == "LINE TV客服中心":
            mentions.append("LINE TV官方客服中心")
        if label.endswith("申告"):
            mentions.append(f"{label}表單")
        links.append((label, tuple(mentions), f"［{label}🔗］{url}"))
    return links


def ensure_known_link_mentions(reply: str, memory: Dict[str, Any]) -> str:
    value = str(reply or "")
    appended = []
    for label, mentions, link in _known_reply_links(memory):
        if not link:
            continue
        if not any(mention in value for mention in mentions):
            continue
        url_match = re.search(r"https?://[^\s]+", link)
        url = url_match.group(0) if url_match else ""
        if _has_link_for_label(value, label, url):
            continue
        appended.append(f"{label}：{link}")

    if not appended:
        return value
    return f"{value.rstrip()}\n" + "\n".join(appended)


def ensure_repair_report_link(reply: str, memory: Dict[str, Any]) -> str:
    return ensure_known_link_mentions(reply, memory)


def append_promotion_referral_code(
    reply: str,
    router: Dict[str, Any],
    memory: Dict[str, Any],
    user_text: str = "",
) -> str:
    """Append the referral code only to actual promotion recommendations."""
    value = str(reply or "").rstrip()
    if not value or router.get("topic") != "promotion_activity":
        return strip_promotion_referral_code(value)

    # Once a customer has named a campaign, the reply is a factual campaign
    # detail rather than a recommendation. Do not append unrelated promotion
    # metadata to that focused answer.
    named_campaign, _ = find_named_campaign_docs(
        user_text,
        memory.get("last_knowledge_results") or [],
    )
    if named_campaign:
        return strip_promotion_referral_code(value)

    if not should_append_promotion_referral_code(value, user_text):
        return strip_promotion_referral_code(value)

    has_knowledge_result = bool(memory.get("last_knowledge_results"))
    company_code = memory.get("company_code", DEFAULT_TV_CABLE)
    profile = get_company_profile(company_code)
    has_company_promotion = bool(str(profile.get("promotion_activity") or "").strip())
    if not has_knowledge_result and not has_company_promotion:
        return strip_promotion_referral_code(value)

    if PROMOTION_REFERRAL_CODE in value:
        return value

    return f"{value}\n\n{PROMOTION_REFERRAL_FOOTER}"


def strip_promotion_referral_code(reply: str) -> str:
    value = str(reply or "")
    code_pattern = re.escape(PROMOTION_REFERRAL_CODE)
    value = re.sub(rf"\n{{0,2}}\s*推薦人代碼\s*[：:]\s*{code_pattern}\s*", "\n", value)
    value = re.sub(rf"(?<![A-Za-z0-9]){code_pattern}(?![A-Za-z0-9])", "", value)
    return value.rstrip()


def should_append_promotion_referral_code(reply: str, user_text: str = "") -> bool:
    reply_value = str(reply or "").strip()
    if not reply_value:
        return False

    # A broad campaign catalogue is an index for the customer to choose from,
    # not a recommendation. Keep it limited to the campaign facts requested.
    if reply_value.startswith("目前可參考的優惠方案："):
        return False

    compact_reply = compact_text(reply_value)
    if any(compact_text(term) in compact_reply for term in PROMOTION_REFERRAL_REPLY_BLOCK_TERMS):
        return False

    if any(compact_text(term) in compact_reply for term in PROMOTION_REFERRAL_REPLY_ALLOW_TERMS):
        return True

    compact_user = compact_text(user_text)
    if compact_user and is_promotion_recommendation_query(user_text):
        return any(term in compact_reply for term in ("方案", "活動", "優惠", "費率", "月繳", "年繳", "贈", "抽獎"))

    return False


def trim_summary_answer(answer: str) -> str:
    value = format_customer_reply_text(answer)
    if len(value) <= RAG_SUMMARY_MAX_CHARS_PER_DOC:
        return value
    return value[:RAG_SUMMARY_MAX_CHARS_PER_DOC].rstrip() + "..."


def is_empty_knowledge_summary(summary: str) -> bool:
    value = format_customer_reply_text(str(summary or "").strip())
    compact = value.replace(" ", "").replace("　", "").replace("\n", "").replace("\t", "")
    return compact.lower() in {"", "{}", "{。}", "[]", "null", "none"}


def build_online_payment_portal_reply(
    user_text: str,
    docs: List[Dict[str, Any]],
) -> str | None:
    """Return the focused portal steps when the retrieved evidence supports them."""
    normalized_query = compact_text(user_text).lower()
    asks_online_payment = any(
        term in normalized_query
        for term in ("線上繳費", "線上付款", "線上刷卡", "網路繳費")
    )
    asks_other_channel = any(
        term in normalized_query
        for term in ("ibon", "famiport", "超商", "便利商店", "app繳費", "行動客服")
    )
    if not asks_online_payment or asks_other_channel:
        return None

    evidence = compact_text("\n".join(str(doc.get("answer") or "") for doc in docs)).lower()
    required_terms = ("官方網站", "繳費專區", "用戶編號", "密碼")
    if not all(compact_text(term).lower() in evidence for term in required_terms):
        return None

    return (
        "您好，您可以透過官網或行動客服 APP 進行線上繳費：\n"
        "A、官方網站\n"
        "1. 開啟瀏覽器，進入本公司官方網站。\n"
        "2. 進入「線上繳費」專區。\n"
        "3. 輸入用戶編號及密碼：用戶編號通常可於帳單上查詢。\n"
        "4. 選擇繳費方式，例如信用卡、ATM 轉帳等。\n"
        "5. 依照系統提示完成繳費，繳費成功後會顯示相關訊息及繳費憑證。\n\n"
        "B、行動客服 APP\n"
        "1. 下載並開啟行動客服 APP，完成登入。\n"
        "2. 在首頁勾選要繳納的待繳帳單，點選「立即繳費」。\n"
        "3. 選擇繳費方式，例如線上刷卡、LINE Pay 等。\n"
        "4. 依照系統提示完成繳費，繳費成功後會顯示相關訊息。\n\n"
        "貼心提醒\n"
        "透過線上刷卡繳費，以及使用 ibon、FamiPort 繳費，系統會自動開通服務。"
        "繳費完成後，請將設備電源關閉再重新開機。"
    )


def build_payment_method_overview_reply(
    intent: str | None,
    docs: List[Dict[str, Any]],
) -> str:
    """Render the complete payment-channel SOP after model routing and retrieval."""
    if intent != "bill_payment_methods" or not docs:
        return ""
    return (
        "若尚未繳費，可以透過以下方式進行繳費：\n"
        "1. 線上刷卡繳費：前往官方網站，在線上繳費專區輸入用戶編號和密碼，再依畫面指示完成繳費。\n"
        "2. 臨櫃繳費：至公司櫃台辦理。\n"
        "3. APP 繳費：下載行動客服 APP，註冊或登入後依畫面指示完成繳費。\n"
        "4. 便利商店繳費：持帳單至便利商店櫃台，刷帳單條碼繳費。\n"
        "5. ibon／FamiPort 繳費：至 7-Eleven 或全家便利商店的機台，依畫面指示完成繳費。\n"
        "貼心提醒：透過線上刷卡、ibon 或 FamiPort 繳費後，系統會自動開通；"
        "請將設備電源關閉後重新開機。"
    )


def build_digital_tv_package_addon_process_reply(intent: str | None) -> str:
    """Render the shared digital-channel purchase SOP after LLM intent selection."""
    if intent != "digital_tv_package_addon":
        return ""

    return (
        "數位電視頻道套餐的加購方式依機上盒類型而定：\n"
        "1. 聯網機上盒：可使用遙控器依「VIP會員 → 優惠專區 → 數位電視」自行加購。\n"
        "2. 非聯網機上盒：無法透過機上盒自行加購，欲申請數位頻道請洽客服辦理。\n"
        "套餐內容與收費可再至官方網站查詢。"
    )


def build_app_payment_receipt_lookup_reply(
    intent: str | None,
    user_text: str = "",
) -> str:
    """Render the approved invoice lookup SOP after LLM intent selection."""
    if intent != "app_payment_receipt_lookup":
        return ""

    compact = compact_text(user_text).lower()
    asks_receipt_delivery = any(
        term in compact
        for term in ("實體收據", "寄到家", "寄到府", "寄送收據", "收到收據")
    )
    if asks_receipt_delivery:
        return APP_PAYMENT_RECEIPT_REPLY

    return "可以。請登入哈TV行動客服 APP，點選「歷史帳單」即可查詢發票及帳單資訊。"


def build_fixed_ip_binding_knowledge_fallback(
    user_text: str,
    intent: str | None,
    docs: List[Dict[str, Any]] | None = None,
    llm=None,
    memory: Dict[str, Any] | None = None,
) -> str:
    """Combine current fee evidence with the approved fixed-IP process."""
    if intent != "fixed_ip_binding_guidance":
        return ""

    process_docs = [{
        "question": "固定 IP 申請與綁定流程",
        "answer": (
            "先由真人客服依目前寬頻帳戶確認可申請的固定 IP 數量與當期費用；"
            "未取得當期正式資料時，不提供固定數量或價格。申請確認後，使用要綁定的設備前往"
            "［台基科官網🔗］https://www.tinp.net.tw/ 依序進入會員登入、綁定固定 IP，"
            "輸入客戶編號與密碼後，在用戶服務資訊選擇要綁定的設備並執行設定。"
            "看到綁定完成訊息後，重新啟動該設備。"
        ),
    }]
    summary = build_knowledge_summary(
        user_text,
        [*(docs or []), *process_docs],
        llm=llm,
        memory=memory,
        intent=intent,
    )
    required_fragments = (
        "［台基科官網🔗］https://www.tinp.net.tw/",
        "會員登入",
        "綁定固定 IP",
        "重新啟動",
    )
    if summary and all(fragment in summary for fragment in required_fragments):
        return summary
    return (
        "固定 IP 綁定前，需先由真人客服依目前寬頻帳戶確認可申請數量與當期費用。"
        "申請確認後，請使用要綁定的設備前往［台基科官網🔗］https://www.tinp.net.tw/ "
        "依序進入「會員登入」→「綁定固定 IP」，輸入客戶編號與密碼，"
        "選擇設備並完成設定；看到完成訊息後重新啟動該設備。"
    )


def build_invoice_issue_timing_reply(intent: str | None) -> str:
    """Render the approved invoice timing and carrier-binding SOP after LLM intent selection."""
    return INVOICE_ISSUE_TIMING_REPLY if intent == "invoice_issue_timing" else ""


def build_invoice_carrier_binding_reply(intent: str | None) -> str:
    """Render the approved carrier-binding SOP after LLM intent selection."""
    return INVOICE_CARRIER_REPLY if intent == "invoice_carrier_binding" else ""


def build_cable_tv_termination_calculation_reply(intent: str | None) -> str:
    """Render the approved cable-TV termination calculation SOP after LLM selection."""
    return CABLE_TV_TERMINATION_CALCULATION_REPLY if intent == "cable_tv_termination_calculation" else ""


def build_contract_change_after_termination_reply(intent: str | None) -> str:
    """Render the approved contract-change follow-up after LLM selection."""
    return CONTRACT_CHANGE_AFTER_TERMINATION_REPLY if intent == "contract_change_after_termination" else ""


def build_cloud_account_app_usage_reply(intent: str | None) -> str:
    """Render the cloud-account app guide after LLM intent selection."""
    return CLOUD_ACCOUNT_APP_GUIDE_REPLY if intent == "cloud_account_app_usage" else ""


def build_basic_channel_table_reply(intent: str | None) -> str:
    """Render the official channel-table referral after LLM intent selection."""
    return BASIC_CHANNEL_TABLE_REPLY if intent == "basic_channel_table_query" else ""


def _format_convenience_store_machine_steps(answer: str) -> str:
    """Turn a source-provided kiosk path into readable customer steps."""
    value = str(answer or "").replace("\r", "").strip()
    if not value or "→" not in value:
        return ""

    value = re.split(r"貼心提醒[：:]?", value, maxsplit=1)[0].strip()
    value = re.sub(
        r"^(?:ibon|famiport)\s*機台操作\s*[：:]?\s*",
        "",
        value,
        flags=re.IGNORECASE,
    )
    steps = []
    for item in value.split("→"):
        step = re.sub(r"^[0-9]+[\.、]\s*", "", item)
        step = re.sub(r"輸入用戶電話", "輸入用戶登記電話", step).strip(" 。")
        if step:
            steps.append(step)
    if len(steps) < 2:
        return ""

    return "\n".join(f"{index}、{item}" for index, item in enumerate(steps, start=1))


def build_convenience_store_payment_machine_reply(
    intent: str | None,
    docs: List[Dict[str, Any]],
) -> str:
    """Present retrieved ibon/FamiPort SOPs without blending their paths."""
    if intent != "convenience_store_payment_machine_guide":
        return ""

    machine_docs: Dict[str, tuple[str, str]] = {}
    for doc in docs:
        title = str(doc.get("question") or "").strip()
        answer = str(doc.get("answer") or "").strip()
        title_text = title.casefold()
        source_text = f"{title}\n{answer}".casefold()
        machine = (
            "ibon" if "ibon" in title_text
            else "famiport" if "famiport" in title_text
            else "ibon" if "ibon" in source_text and "famiport" not in source_text
            else "famiport" if "famiport" in source_text and "ibon" not in source_text
            else ""
        )
        steps = _format_convenience_store_machine_steps(answer)
        if not machine or not steps:
            continue
        existing = machine_docs.get(machine)
        if not existing or len(steps) > len(existing[1]):
            machine_docs[machine] = (answer, steps)

    if not {"ibon", "famiport"}.issubset(machine_docs):
        return ""

    reminder_source = "\n".join(answer for answer, _ in machine_docs.values())
    reply = (
        "您可依便利商店內的機台操作繳費：\n\n"
        "【7-Eleven ibon】\n"
        f"{machine_docs['ibon'][1]}\n\n"
        "【全家 FamiPort】\n"
        f"{machine_docs['famiport'][1]}"
    )
    if "自動開通" in reminder_source:
        reply += "\n\n貼心提醒：透過 ibon 或 FamiPort 繳費後，系統會自動開通服務。"
        if any(term in reminder_source for term in ("關機重開", "關閉再重新開機", "關機後重新開機")):
            reply += "繳費完成後，請將設備電源關閉再重新開機。"
    return reply


def build_knowledge_summary(
    user_text: str,
    docs: List[Dict[str, Any]],
    llm=None,
    memory: Dict[str, Any] | None = None,
    intent: str | None = None,
    promotion_scope: str | None = None,
    promotion_query_kind: str | None = None,
    required_evidence: List[str] | None = None,
) -> str | None:
    if llm is None:
        return None

    blocks = []
    for index, doc in enumerate(docs[:RAG_SUMMARY_MAX_DOCS], start=1):
        answer = trim_summary_answer(doc.get("answer") or "")
        if not answer:
            continue
        blocks.append(
            "\n".join([
                f"[資料 {index}]",
                f"標題：{doc.get('question') or ''}",
                f"內容：{answer}",
            ])
        )

    if not blocks:
        return None

    try:
        prompt = ChatPromptTemplate.from_template(RAG_SUMMARY_PROMPT)
        response_focus = knowledge_response_focus(intent)
        if required_evidence:
            response_focus = (
                f"{response_focus} \n上一版回答缺少必要資料："
                f"{'、'.join(required_evidence)}。"
                "請重新根據候選資料回答，並逐項保留上述標籤與金額。"
            )
        response = (prompt | llm).invoke({
            "user_text": user_text,
            "knowledge_text": "\n\n".join(blocks),
            "company_context": build_company_context(
                (memory or {}).get("company_code", DEFAULT_TV_CABLE)
            ),
            "promotion_scope": promotion_scope or "不適用",
            "promotion_query_kind": promotion_query_kind or "不適用",
            "response_focus": response_focus,
            "regional_policy_rules": build_policy_prompt(
                memory,
                (
                    "promotion.social_discount_stacking",
                    "promotion.discount_stacking_caution",
                    "promotion.hidden_plan_visibility",
                ),
            ),
        })
        content = getattr(response, "content", response)
        summary = format_customer_reply_text(str(content or "").strip())
        if is_empty_knowledge_summary(summary):
            return None
        return summary or None
    except Exception:
        return None


def add_summary_failure_context(user_text: str, answer: str) -> str:
    """Keep a raw promotion fallback understandable when summarization fails."""
    value = str(answer or "").strip()
    if not value or not is_promotion_query(user_text):
        return value
    if "優惠方案如下" in value or "優惠活動如下" in value:
        return value

    company_label = explicit_company_label(user_text)
    prefix = (
        f"{company_label}目前查到的優惠方案如下："
        if company_label
        else "目前查到的優惠方案如下："
    )
    return f"{prefix}\n\n{value}"


def keep_explicit_rate_evidence(
    user_text: str,
    docs: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """Keep documents that contain every broadband rate named by the customer."""
    requested_speeds = extract_requested_broadband_speeds(user_text)
    if not requested_speeds:
        return []

    return [
        doc for doc in docs
        if all(
            speed in normalize_keyword_text(doc_search_text(doc))
            for speed in requested_speeds
        )
    ]


def filter_docs_with_llm_evidence(
    user_text: str,
    docs: List[Dict[str, Any]],
    router: Dict[str, Any],
    llm=None,
) -> tuple[List[Dict[str, Any]], bool]:
    """Use the model as a positive reranker for this turn's semantic contract.

    The existing retrieval guards remain authoritative when the model cannot
    select evidence.  A conservative or malformed model verdict must not turn
    otherwise usable knowledge into a generic "not found" response.
    """
    if llm is None or not docs:
        return docs, False

    explicit_rate_docs = keep_explicit_rate_evidence(user_text, docs)
    if explicit_rate_docs:
        return explicit_rate_docs, True

    # The router has already resolved a short follow-up such as "兩年呢" to
    # the cable-TV two-year total.  The annual rate card plus installation fee
    # is sufficient evidence for that calculation even though no source says
    # the literal phrase "兩年".  This is evidence selection after the LLM
    # intent decision, not a keyword route or a synthetic answer.
    if router.get("intent") in {
        "basic_tv_two_year_fee_query",
        "cable_tv_two_year_fee_inquiry",
    }:
        evidence_query = str(router.get("knowledge_query") or user_text)
        verified_docs = filter_answerable_docs(evidence_query, docs)
        if verified_docs:
            return verified_docs, True

    # An existing customer asking for the next tier needs the currently
    # promotable plans as comparison evidence. The retrieval query already
    # carries the LLM-resolved service type and current speed when available;
    # do not let a second generic evidence verdict discard every eligible
    # source and turn a useful recommendation into a data-not-found reply.
    if router.get("intent") == "next_tier_plan_fee_guidance":
        evidence_query = str(router.get("knowledge_query") or user_text)
        verified_docs = filter_answerable_docs(evidence_query, docs)
        if verified_docs:
            return verified_docs, True

    blocks = []
    for index, doc in enumerate(docs, start=1):
        answer = trim_summary_answer(doc.get("answer") or "")
        blocks.append(
            "\n".join((
                f"[文件 {index}]",
                f"標題：{doc.get('question') or doc.get('title') or ''}",
                f"內容：{answer}",
            ))
        )

    try:
        prompt = ChatPromptTemplate.from_template(KNOWLEDGE_EVIDENCE_PROMPT)
        response = (prompt | llm).invoke({
            "user_text": user_text,
            "service_scope": router.get("service_scope") or router.get("topic") or "未提供",
            "requested_information": (
                router.get("requested_information")
                or router.get("knowledge_query")
                or user_text
            ),
            "documents": "\n\n".join(blocks),
        })
        content = getattr(response, "content", response)
        text = str(content or "").strip()
        start, end = text.find("{"), text.rfind("}")
        if start < 0 or end <= start:
            return docs, False
        result = json.loads(text[start:end + 1])
        selected = result.get("selected_document_indexes")
        has_sufficient_evidence = result.get("has_sufficient_evidence")
        if not isinstance(selected, list) or not isinstance(has_sufficient_evidence, bool):
            return docs, False
        if not has_sufficient_evidence:
            # A negative reranker verdict is not enough to discard documents
            # that pass the existing query/document evidence contract.  The
            # reranker occasionally answers conservatively even when retrieval
            # found the exact FAQ; clearing the list then turns a valid answer
            # into a random "not found" response.
            verified_docs = filter_answerable_docs(user_text, docs)
            if verified_docs and has_knowledge_reply_evidence(
                user_text,
                knowledge_docs_text(verified_docs),
            ):
                return verified_docs, True
            return docs, False
        indexes = {
            item for item in selected
            if isinstance(item, int) and 1 <= item <= len(docs)
        }
        if len(indexes) != len(selected) or not indexes:
            return docs, False
        return [doc for index, doc in enumerate(docs, start=1) if index in indexes], True
    except (TypeError, ValueError, json.JSONDecodeError):
        return docs, False
    except Exception:
        return docs, False


def compose_knowledge_reply(
    user_text: str,
    base_reply: str,
    docs: List[Dict[str, Any]],
    llm=None,
    summary_llm=None,
    answer_guard_query: str | None = None,
    memory: Dict[str, Any] | None = None,
    fallback_reply: str | None = None,
    prefer_compact_upgrade: bool = False,
    intent: str | None = None,
    promotion_scope: str | None = None,
    promotion_query_kind: str | None = None,
) -> str:
    digital_tv_package_reply = build_digital_tv_package_addon_process_reply(intent)
    if digital_tv_package_reply:
        return digital_tv_package_reply

    app_payment_receipt_reply = build_app_payment_receipt_lookup_reply(
        intent,
        user_text,
    )
    if app_payment_receipt_reply:
        return app_payment_receipt_reply

    invoice_issue_timing_reply = build_invoice_issue_timing_reply(intent)
    if invoice_issue_timing_reply:
        return invoice_issue_timing_reply

    invoice_carrier_binding_reply = build_invoice_carrier_binding_reply(intent)
    if invoice_carrier_binding_reply:
        return invoice_carrier_binding_reply

    cable_tv_termination_reply = build_cable_tv_termination_calculation_reply(intent)
    if cable_tv_termination_reply:
        return cable_tv_termination_reply

    contract_change_reply = build_contract_change_after_termination_reply(intent)
    if contract_change_reply:
        return contract_change_reply

    cloud_account_reply = build_cloud_account_app_usage_reply(intent)
    if cloud_account_reply:
        return cloud_account_reply

    basic_channel_reply = build_basic_channel_table_reply(intent)
    if basic_channel_reply:
        return basic_channel_reply

    guard_query = answer_guard_query or user_text
    docs = apply_knowledge_doc_visibility_policies(user_text, docs)
    answerable_docs = filter_answerable_docs(guard_query, docs)

    fixed_ip_reply = build_fixed_ip_binding_knowledge_fallback(
        user_text,
        intent,
        docs=answerable_docs,
        llm=summary_llm or llm,
        memory=memory,
    )
    if fixed_ip_reply:
        return fixed_ip_reply

    if not answerable_docs:
        general_reply = build_general_knowledge_reply(user_text, llm, memory=memory)
        if general_reply:
            return general_reply

        if fallback_reply:
            return fallback_reply

        return (
            "目前我這邊沒有查到足夠明確的資料，"
            "請您換個方式描述想了解的問題。"
        )

    payment_method_reply = build_payment_method_overview_reply(intent, answerable_docs)
    if payment_method_reply:
        return payment_method_reply

    clear_channel_group_reply = build_clear_channel_group_reply(
        user_text,
        answerable_docs,
        intent=intent,
    )
    if clear_channel_group_reply:
        return clear_channel_group_reply

    convenience_store_machine_reply = build_convenience_store_payment_machine_reply(
        intent,
        answerable_docs,
    )
    if convenience_store_machine_reply:
        return convenience_store_machine_reply

    online_payment_reply = build_online_payment_portal_reply(
        user_text,
        answerable_docs,
    )
    if online_payment_reply:
        return online_payment_reply

    combo_rate_inclusion_reply = build_combo_rate_inclusion_reply(
        user_text,
        answerable_docs,
    )
    if combo_rate_inclusion_reply:
        return combo_rate_inclusion_reply

    combo_service_inclusion_reply = build_combo_service_inclusion_reply(
        user_text,
        answerable_docs,
    )
    if combo_service_inclusion_reply:
        return combo_service_inclusion_reply

    combo_overview_reply = build_hatv_hatnet_combo_overview_reply(
        user_text,
        answerable_docs,
    )
    if combo_overview_reply:
        return combo_overview_reply

    # A basic cable-TV monthly-fee question has one factual value in the
    # source document.  Return that value directly once it is found instead
    # of asking the summarizer to reinterpret it as a promotion price.
    basic_tv_fee_reply = apply_basic_tv_monthly_fee_concision(
        user_text,
        "",
        answerable_docs,
    )
    if basic_tv_fee_reply:
        return basic_tv_fee_reply

    # This follow-up is a deterministic calculation once both source values
    # are present.  Keep it grounded in those documents instead of allowing
    # the summary model to replace it with a generic rate-card answer.
    basic_tv_two_year_reply = apply_basic_tv_two_year_fee_calculation(
        user_text,
        "",
        answerable_docs,
    )
    if basic_tv_two_year_reply:
        return basic_tv_two_year_reply

    campaign_total_reply = build_campaign_total_fee_reply(
        user_text,
        answerable_docs,
        memory=memory,
    )
    if campaign_total_reply:
        return campaign_total_reply

    campaign_period_reply = build_campaign_valid_period_reply(
        user_text,
        answerable_docs,
    )
    if campaign_period_reply:
        return campaign_period_reply

    if prefer_compact_upgrade:
        compact_upgrade_reply = build_next_tier_plan_fallback(
            answerable_docs,
            user_text=user_text,
        )
        if compact_upgrade_reply:
            return compact_upgrade_reply

    campaign_contract_reply = build_campaign_contract_followup_reply(
        user_text,
        answerable_docs,
        memory=memory,
    )
    if campaign_contract_reply:
        return campaign_contract_reply

    promotion_catalog_reply = build_promotion_catalog_reply(
        user_text,
        answerable_docs,
        intent=intent,
        promotion_scope=promotion_scope,
        promotion_query_kind=promotion_query_kind,
    )
    if promotion_catalog_reply:
        return promotion_catalog_reply

    campaign_gift_followup_reply = build_campaign_gift_followup_reply(
        user_text,
        answerable_docs,
    )
    if campaign_gift_followup_reply:
        return campaign_gift_followup_reply

    named_campaign_overview_reply = build_named_campaign_overview_reply(
        user_text,
        answerable_docs,
    )
    if named_campaign_overview_reply:
        return named_campaign_overview_reply

    multi_plan_broadband_reply = build_multi_plan_broadband_price_reply(
        user_text,
        answerable_docs,
    )
    if multi_plan_broadband_reply:
        return multi_plan_broadband_reply

    top = answerable_docs[0]
    answer = sanitize_knowledge_answer(top.get("answer", ""))
    if answer and is_promotion_query(user_text):
        campaign_title = str(
            top.get("campaign_name")
            or top.get("question")
            or top.get("title")
            or ""
        ).strip()
        if campaign_title and campaign_title not in answer:
            answer = f"方案名稱：{campaign_title}\n{answer}"

    if answer:
        summary = build_knowledge_summary(
            user_text,
            answerable_docs,
            llm=summary_llm or llm,
            memory=memory,
            intent=intent,
            promotion_scope=promotion_scope,
            promotion_query_kind=promotion_query_kind,
        )
        missing_requirements = missing_knowledge_summary_requirements(
            intent,
            summary,
            answerable_docs,
        )
        if missing_requirements:
            summary = build_knowledge_summary(
                user_text,
                answerable_docs,
                llm=summary_llm or llm,
                memory=memory,
                intent=intent,
                promotion_scope=promotion_scope,
                promotion_query_kind=promotion_query_kind,
                required_evidence=missing_requirements,
            )
            missing_requirements = missing_knowledge_summary_requirements(
                intent,
                summary,
                answerable_docs,
            )
        if summary and not missing_requirements and has_knowledge_reply_evidence(user_text, summary):
            return apply_customer_reply_policies(
                user_text,
                summary,
                answerable_docs,
                memory=memory,
            )
        payment_cycle_fallback = build_payment_cycle_evidence_fallback(answerable_docs)
        if payment_cycle_fallback:
            return apply_customer_reply_policies(
                user_text,
                payment_cycle_fallback,
                answerable_docs,
                memory=memory,
            )
        compact_fallback = build_evidence_compact_fallback(
            user_text,
            answerable_docs,
        )
        if compact_fallback:
            return apply_customer_reply_policies(
                user_text,
                compact_fallback,
                answerable_docs,
                memory=memory,
            )
        answer = add_summary_failure_context(user_text, answer)
        return apply_customer_reply_policies(
            user_text,
            answer,
            answerable_docs,
            memory=memory,
        )

    return (
        fallback_reply
        or "目前我這邊沒有查到足夠明確的資料，請您換個方式描述想了解的問題。"
    )


def compact_text(text: str) -> str:
    return (text or "").replace(" ", "").replace("　", "")


def history_texts(history: List[Dict[str, str]]) -> List[str]:
    values: List[str] = []
    for item in history or []:
        content = str(item.get("content") or "").strip()
        if content:
            values.append(content)
    return values


# These are intent families, not reply routes. They are used only to decide
# whether an earlier conversation may be used as context for the latest turn.
# The model still chooses the actual intent, response, knowledge query, or tool.
EXPLICIT_INTENT_DOMAIN_TERMS = (
    (
        "termination",
        (
            "退租",
            "退掉",
            "解約",
            "提前終止",
            "終止合約",
            "合約終止",
            "終止服務",
            "取消服務",
            "不續約",
            "停用服務",
        ),
    ),
    ("reconnection", ("復線", "恢復服務", "恢復收視", "恢復網路", "繳費後開通")),
    ("billing", ("帳單", "帳務", "繳費", "付款", "發票", "收據", "載具", "扣款")),
    ("network_fault", ("不能上網", "無法上網", "網路不能用", "網路斷線", "網路很慢", "網路不穩", "網路故障")),
    ("tv_fault", ("電視不能看", "第四台不能看", "無訊號", "未授權", "授權到期", "機上盒故障", "遙控器故障")),
    ("relocation", ("移機", "搬家", "搬遷", "換地址", "新地址")),
    ("installation", ("新申裝", "新裝", "申裝", "裝機", "安裝服務")),
    ("account", ("我的網路", "我家網路", "我的合約", "目前服務", "服務內容", "目前方案", "我的方案", "合約到期", "客戶編號", "客編")),
    ("promotion", ("優惠方案", "優惠活動", "促銷方案", "推薦方案", "最新優惠")),
    ("value_added", ("LINE TV", "哈TV", "WiFi加值", "Wi-Fi加值", "數位套餐", "加值服務", "聯網機上盒")),
)


def infer_explicit_intent_domain(text: str) -> str | None:
    """Return a concrete customer intent family when the wording names one."""
    value = compact_text(text).lower()
    if not value:
        return None

    for domain, terms in EXPLICIT_INTENT_DOMAIN_TERMS:
        if any(compact_text(term).lower() in value for term in terms):
            return domain
    return None


def select_contextual_history(
    user_text: str,
    history: List[Dict[str, str]] | None,
) -> tuple[List[Dict[str, str]], bool]:
    """Keep history only when the latest turn has not named another domain.

    Customer messages such as "兩年呢" or "可以嗎" require the preceding
    context. A complete request such as "我的網路" after "退租" does not.
    Looking only at earlier *user* messages prevents a verbose assistant reply
    from becoming the topic source for an unrelated later request.
    """
    current_domain = infer_explicit_intent_domain(user_text)
    if not current_domain:
        return list(history or []), False

    previous_domain = None
    for item in reversed(history or []):
        if str(item.get("role") or "").lower() != "user":
            continue
        previous_domain = infer_explicit_intent_domain(str(item.get("content") or ""))
        if previous_domain:
            break

    if previous_domain and previous_domain != current_domain:
        return [], True

    return list(history or []), False


PROMOTION_GIFT_FOLLOWUP_TERMS = (
    "贈品",
    "電視機",
    "電視",
    "壁掛",
    "壁掛架",
    "壁架",
    "保固",
    "配送",
    "品牌",
    "廠牌",
    "另行報價",
)

PROMOTION_GIFT_DISCOVERY_TERMS = (
    "送家電",
    "送電視",
    "有送",
    "贈品",
    "家電",
    "65吋",
    "電視機",
    "冰箱",
    "大冰箱",
    "小冰箱",
    "投影機",
)

STRONG_PROMOTION_GIFT_DISCOVERY_TERMS = (
    "送家電",
    "送電視",
    "65吋",
    "冰箱",
    "大冰箱",
    "小冰箱",
    "投影機",
)

THIS_CAMPAIGN_REFERENCE_TERMS = (
    "這個方案",
    "此方案",
    "剛剛那個",
    "剛才那個",
    "上面那個",
    "前面那個",
)

TV_NET_COMBO_PROMOTION_TERMS = (
    "電視+網路",
    "電視＋網路",
    "電視加網路",
    "電視與網路",
    "電視和網路",
    "電視網路同裝",
    "網路同裝",
    "同裝優惠",
)


def is_hatv_hatnet_combo_request(text: str) -> bool:
    """Recognize a customer asking about the TV-plus-broadband service pair."""
    normalized = compact_text(text).casefold()
    has_hatv = any(alias in normalized for alias in ("哈tv", "ㄏㄚtv"))
    has_hatnet = any(alias in normalized for alias in ("哈net", "ㄏㄚnet"))
    return has_hatv and has_hatnet

CAMPAIGN_DISCOVERY_OCCASION_TERMS = (
    "春節", "過年", "新春", "元宵", "清明", "兒童節", "勞動節",
    "母親節", "媽媽節", "媽咪", "端午", "父親節", "爸爸節", "爸氣",
    "七夕", "情人節", "中秋", "國慶", "雙十", "聖誕", "耶誕", "跨年",
    "開學", "暑期", "暑假", "週年慶", "周年慶", "年終", "歲末", "尾牙",
)

PROMOTION_DETAIL_CONTEXT_TERMS = (
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
    "贈品",
)

BASIC_TV_QUERY_TERMS = (
    "只要裝有線電視",
    "只要看有線電視",
    "只看有線電視",
    "只裝有線電視",
    "只申裝有線電視",
    "只要第四台",
    "只看第四台",
    "只裝第四台",
    "基本有線",
    "基本收費",
    "純 TV",
    "純TV",
)

TV_FEE_QUERY_TERMS = (
    "合計",
    "總共",
    "總金額",
    "裝到好",
    "一個月",
    "每月",
    "多少錢",
    "費用",
    "月租",
    "月費",
    "收視費",
    "半年繳",
    "年繳",
    "裝機",
    "機上盒",
)

PROMOTION_RECOMMENDATION_TERMS = (
    "優惠",
    "優惠方案",
    "優惠活動",
    "推薦",
    "推薦方案",
    "划算",
    "比較便宜",
    "目前活動",
    "最新方案",
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


def is_basic_tv_fee_query(text: str) -> bool:
    value = compact_text(text)
    if not value:
        return False

    has_basic_tv = any(compact_text(term) in value for term in BASIC_TV_QUERY_TERMS)
    # Do not treat an add-on name such as "LINE TV" as a request for the
    # basic cable-TV rate card.  The explicit Chinese service terms below
    # still cover actual fourth-channel/basic-service fee questions.
    has_tv = any(term in value for term in ("有線電視", "第四台", "基本收費"))
    has_fee = any(compact_text(term) in value for term in TV_FEE_QUERY_TERMS)
    has_combo = any(term in value for term in ("網路", "寬頻", "同裝"))
    return (has_basic_tv or (has_tv and has_fee)) and not has_combo


def is_promotion_recommendation_query(text: str) -> bool:
    value = compact_text(text)
    if not value:
        return False
    if any(term in value for term in ("低收入", "低收", "中低收入", "身障", "身心障礙")):
        return False
    return any(compact_text(term) in value for term in PROMOTION_RECOMMENDATION_TERMS)


def is_fresh_campaign_discovery_query(text: str) -> bool:
    value = compact_text(text)
    if not value:
        return False
    has_promotion = any(compact_text(term) in value for term in PROMOTION_RECOMMENDATION_TERMS) or any(
        term in value for term in ("活動", "方案")
    )
    has_occasion = any(compact_text(term) in value for term in CAMPAIGN_DISCOVERY_OCCASION_TERMS)
    has_month = bool(re.search(r"(?<!\d)(?:1[0-2]|0?[1-9])月", value)) or any(
        month in value
        for month in ("一月", "二月", "三月", "四月", "五月", "六月", "七月", "八月", "九月", "十月", "十一月", "十二月")
    )
    return has_promotion and (has_occasion or has_month)


def is_renewal_process_query(text: str) -> bool:
    value = compact_text(text)
    if not value:
        return False
    has_renewal = any(compact_text(term) in value for term in RENEWAL_PROCESS_TERMS)
    has_action = any(compact_text(term) in value for term in RENEWAL_PROCESS_ACTION_TERMS)
    return has_renewal and has_action


def expand_targeted_knowledge_query(user_text: str, query: str) -> str:
    combined = " ".join(part for part in [query, user_text] if part).strip()
    user_compact = compact_text(user_text).casefold()
    has_explicit_points_name = any(
        term in user_compact
        for term in ("紅利點數", "哈point", "point點數")
    )
    asks_campaign_gift_points = any(
        term in user_compact
        for term in ("贈幾點", "送幾點", "贈多少點", "送多少點", "贈點", "送點")
    ) or (
        any(term in user_compact for term in ("月繳", "季繳", "半年繳", "年繳"))
        and any(term in user_compact for term in ("贈", "送"))
    )
    # An explicit service name starts a fresh points overview lookup. Without
    # this guard, the previous campaign name appended by conversation context
    # can turn a general points question into an unrelated promotion lookup.
    if has_explicit_points_name and not asks_campaign_gift_points:
        return (
            "台數科紅利點數哈Point說明 "
            "紅利點數哈Point優惠積點回饋機制 如何獲得 有效期限 "
            f"{user_text}"
        ).strip()
    if is_restricted_channel_purchase_query(user_text):
        return (
            "成人頻道 限制級頻道 數位電視套餐 月租 收費價格 "
            "購買方式 聯網機上盒 VIP會員 優惠專區 數位電視 "
            f"{user_text}"
        ).strip()
    combined_compact = compact_text(combined)
    if is_fresh_campaign_discovery_query(combined):
        return (
            "優惠活動 節慶 節日 活動期間 方案名稱 售價 速率 繳別 "
            "贈品 LINE TV POINTS 抽獎資格 抽獎獎項 "
            f"{user_text}"
        ).strip()

    if is_renewal_process_query(combined):
        return (
            "續約 重新續約 續訂 重新訂購 約滿 合約到期後 "
            "合約狀態 換約 升級 原合約 新合約 辦理方式 流程 "
            "可適用方案 月繳 半年繳 年繳 客服確認 "
            f"{user_text}"
        ).strip()

    if (
        any(compact_text(term) in combined_compact for term in TV_NET_COMBO_PROMOTION_TERMS)
        or is_hatv_hatnet_combo_request(combined)
    ):
        return (
            "電視網路同裝 電視+網路 有線電視加網路 優惠活動 活動方案 完整內容 "
            "售價 月繳 半年繳 年繳 贈品 家電 加值服務 裝機費 押金 綁約 違約金 "
            "請回答電視+網路同裝方案內容，不要回答純網方案。 "
            f"{user_text}"
        ).strip()

    user_compact = compact_text(user_text)
    if any(compact_text(term) in user_compact for term in PROMOTION_GIFT_DISCOVERY_TERMS):
        return (
            "優惠活動 活動方案 完整內容 售價 月繳 半年繳 年繳 "
            "贈品 家電 送電視 65吋電視 大冰箱 小冰箱 投影機 "
            "LINE TV LITV 哈POINTS 裝機費 押金 綁約 違約金 "
            f"{user_text}"
        ).strip()

    if is_basic_tv_fee_query(combined):
        return (
            "TV 基本收費標準 純 TV 有線電視 第四台 "
            "TV 收視費 月費 半年繳 年繳 裝機費 TV 分機費 順裝 "
            "STB 機上盒 押金 第1台 第2台 免押金 合計 裝到好 "
            f"{user_text}"
        ).strip()

    if is_promotion_recommendation_query(combined):
        return (
            "優惠方案 推薦方案 目前活動 完整方案 活動期間 方案名稱 適用對象 "
            "新裝 同裝 售價 速率 月繳 季繳 半年繳 年繳 綁約 裝機費 設備押金 "
            f"{user_text}"
        ).strip()

    return query


def normalize_campaign_topic(value: str) -> str:
    topic = re.sub(r"\s+", " ", str(value or "")).strip(" -_，,。:：")
    return topic


def campaign_name_from_doc(doc: Dict[str, Any]) -> str | None:
    if not isinstance(doc, dict):
        return None
    source = doc.get("source") if isinstance(doc.get("source"), dict) else {}
    name = normalize_campaign_topic(
        str(doc.get("campaign_name") or source.get("campaign_name") or "")
    )
    return name or None


def infer_recent_campaign_topic(memory: Dict[str, Any], history: List[Dict[str, str]]) -> str | None:
    remembered_topic = normalize_campaign_topic(str(memory.get("last_campaign_topic") or ""))
    if remembered_topic:
        return remembered_topic

    last_docs = memory.get("last_knowledge_results") or []
    for doc in last_docs[:4]:
        campaign_name = campaign_name_from_doc(doc)
        if campaign_name:
            return campaign_name

    return None


def remember_campaign_topic(
    memory: Dict[str, Any],
    reply: str = "",
    docs: List[Dict[str, Any]] | None = None,
    query: str = "",
) -> Dict[str, Any]:
    explicit_campaign, _ = find_named_campaign_docs(query, docs or [])
    if explicit_campaign:
        memory["last_campaign_topic"] = explicit_campaign
        return memory

    doc_campaigns = {
        campaign_name
        for doc in docs or []
        if (campaign_name := campaign_name_from_doc(doc))
    }
    if len(doc_campaigns) == 1:
        memory["last_campaign_topic"] = next(iter(doc_campaigns))
        return memory
    if len(doc_campaigns) > 1:
        memory.pop("last_campaign_topic", None)
        return memory

    return memory


def exact_value_added_topic(text: str) -> str | None:
    normalized_text = compact_text(text).lower()
    if not normalized_text:
        return None

    # Session topic memory must only be changed by a product name or alias that
    # the user actually typed. Fuzzy retrieval matching remains available in the
    # KB layer, but must not turn a generic follow-up such as "一年多少" into a
    # different product and overwrite the active conversation topic.
    direct_matches: List[tuple[int, int, str]] = []
    for priority, product_key in enumerate(VALUE_ADDED_CONTEXT_PRIORITY):
        product_name = VALUE_ADDED_PRODUCT_NAMES.get(product_key)
        if not product_name:
            continue
        aliases = (product_name, *VALUE_ADDED_PRODUCT_QUERY_ALIASES.get(product_key, ()))
        for alias in aliases:
            normalized_alias = compact_text(alias).lower()
            if normalized_alias and normalized_alias in normalized_text:
                direct_matches.append((len(normalized_alias), -priority, product_name))

    if direct_matches:
        return max(direct_matches)[2]
    return None


def infer_recent_topic(user_text: str, memory: Dict[str, Any], history: List[Dict[str, str]]) -> str | None:
    value = compact_text(user_text)
    if not value:
        return None

    # A short promotion follow-up must retain an explicit service-only choice
    # from the customer. The preference belongs to the conversation, not to a
    # particular promotion document, so carry it into retrieval as context.
    if (
        is_promotion_recommendation_query(user_text)
        and not any(term in value for term in ("網路", "寬頻", "同裝"))
    ):
        recent_user_values = [
            compact_text(str(item.get("content") or ""))
            for item in history or []
            if str(item.get("role") or "").lower() == "user"
        ]
        if any(
            any(compact_text(term) in recent_value for term in BASIC_TV_QUERY_TERMS)
            for recent_value in recent_user_values
        ):
            return "純有線電視 第四台 基本收費 收視費 單辦優惠"

    if is_fresh_campaign_discovery_query(user_text):
        return None

    explicit_value_added_topic = exact_value_added_topic(user_text)
    if explicit_value_added_topic:
        memory["last_value_added_topic"] = explicit_value_added_topic
        memory.setdefault("known_info", {})["last_value_added_topic"] = explicit_value_added_topic
        return explicit_value_added_topic

    recent_values = history_texts(history)[-6:]
    last_docs = memory.get("last_knowledge_results") or []
    for doc in last_docs[:2]:
        question = str(doc.get("question") or "").strip()
        if question:
            recent_values.append(question)

    recent = compact_text(" ".join(recent_values))

    is_value_added_followup = len(value) <= 12 or any(
        term in value for term in VALUE_ADDED_DETAIL_FOLLOWUP_TERMS
    )
    if is_value_added_followup:
        remembered_topic = str(
            memory.get("last_value_added_topic")
            or (memory.get("known_info", {}) or {}).get("last_value_added_topic")
            or ""
        ).strip()
        if remembered_topic:
            return remembered_topic

        # Prefer the product the user explicitly named. Assistant replies may
        # mention related sub-plans (for example 熊搭心 and 瑪帛用戶 together),
        # which must not replace the user's active product context.
        recent_user_values = [
            str(item.get("content") or "").strip()
            for item in history or []
            if str(item.get("role") or "").lower() == "user"
            and str(item.get("content") or "").strip()
        ][-6:]
        topic_candidates = list(reversed(recent_user_values))
        topic_candidates.extend(
            recent_value
            for recent_value in reversed(recent_values)
            if recent_value not in recent_user_values
        )
        for recent_value in topic_candidates:
            recent_value_added_topic = exact_value_added_topic(recent_value)
            if recent_value_added_topic:
                return recent_value_added_topic

    campaign_topic = infer_recent_campaign_topic(memory, history)
    if campaign_topic and any(
        compact_text(term).lower() in value.lower()
        for term in PROMOTION_DETAIL_CONTEXT_TERMS
    ):
        return (
            f"{campaign_topic} 活動方案 活動期間 綁約 違約金 售價 速率 "
            "月繳 季繳 半年繳 年繳 裝機費 設備押金 LINE TV LITV "
            "POINT POINTS 抽獎資格 抽獎獎項 贈品"
        )

    if any(term in value for term in ("賽事時間", "賽程", "網站參考", "參考網站", "有網站")):
        if any(term in recent for term in ("世足", "世界盃", "世界杯", "FIFA", "足球賽")):
            return "世足賽"

    if "押金" in value:
        if any(term in recent for term in ("第四台", "有線電視", "電視", "機上盒")):
            return "第四台 機上盒"
        if any(term in recent for term in ("網路", "寬頻", "數據機", "分享器")):
            return "寬頻網路設備"

    if any(term in value for term in ("費用", "價格", "價錢", "月租", "多少錢", "怎麼收")):
        if any(term in recent for term in ("第四台", "有線電視", "電視")):
            return "有線電視 第四台"
        if any(term in recent for term in ("移機", "搬家", "搬遷")):
            return "移機"
        if any(term in recent for term in ("網路", "寬頻")):
            return "寬頻網路"

    if any(term in value for term in PROMOTION_GIFT_FOLLOWUP_TERMS):
        has_this_campaign_reference = any(
            compact_text(term) in value for term in THIS_CAMPAIGN_REFERENCE_TERMS
        )
        has_strong_gift_discovery = any(
            compact_text(term) in value for term in STRONG_PROMOTION_GIFT_DISCOVERY_TERMS
        )
        if has_strong_gift_discovery and not has_this_campaign_reference:
            return (
                "優惠活動 活動方案 完整內容 贈品 家電 送電視 65吋電視 "
                "大冰箱 小冰箱 投影機 LINE TV LITV 哈POINTS 售價 月繳 半年繳 年繳"
            )
        campaign_topic = infer_recent_campaign_topic(memory, history)
        if campaign_topic:
            return f"{campaign_topic} 家電配送 保固 壁掛 贈品 品牌"
        if any(compact_text(term) in value for term in PROMOTION_GIFT_DISCOVERY_TERMS):
            return (
                "優惠活動 活動方案 完整內容 贈品 家電 送電視 65吋電視 "
                "大冰箱 小冰箱 投影機 LINE TV LITV 哈POINTS 售價 月繳 半年繳 年繳"
            )

    if any(term in value for term in ("怎麼辦理", "如何辦理", "怎麼申請", "如何申請")):
        if any(term in recent for term in ("固定IP", "固定ip", "固定ip地址")):
            return "固定 IP"
        if any(term in recent for term in ("移機", "搬家", "搬遷")):
            return "移機"

    return None


def build_contextual_knowledge_query(
    user_text: str,
    current_query: str | None,
    memory: Dict[str, Any],
    history: List[Dict[str, str]] | None,
    *,
    allow_context: bool = True,
) -> str:
    query = str(current_query or user_text or "").strip()
    if not allow_context:
        return query

    explicit_domain = infer_explicit_intent_domain(user_text)
    if explicit_domain and explicit_domain != "promotion":
        return query

    campaign_topic = infer_recent_campaign_topic(memory, history or [])
    compact_user_text = compact_text(user_text).lower()
    if campaign_topic and infer_explicit_intent_domain(user_text) in {None, "promotion"} and any(
        term in compact_user_text
        for term in ("費用", "價格", "價錢", "多少", "年繳", "半年", "月繳", "贈品", "申請", "辦理")
    ) and compact_text(campaign_topic).lower() not in compact_text(query).lower():
        query = f"{campaign_topic} {query}".strip()

    # For price and payment follow-ups, the preceding customer message is a
    # stronger product anchor than an assistant reply that may mention gifts
    # or adjacent services.  Keep the wording dynamic so new campaigns need
    # no prompt or code update.
    recent_user_topics = [
        str(item.get("content") or "").strip()
        for item in history or []
        if str(item.get("role") or "").lower() == "user"
        and str(item.get("content") or "").strip()
    ]
    if any(term in compact_user_text for term in ("費用", "價格", "價錢", "多少", "年繳", "半年", "月繳")) and recent_user_topics:
        previous_customer_topic = recent_user_topics[-1]
        if compact_text(previous_customer_topic).lower() not in compact_text(query).lower():
            query = f"{previous_customer_topic} {query}".strip()

    # The router model, rather than a message-length or keyword heuristic,
    # decides whether this turn is continuing the previous subject.  The
    # caller passes allow_context=False whenever it selected a new intent.

    # Campaign names are the strongest retrieval anchor for short price and
    # payment follow-ups.  Preserve the named plan before generic fee words
    # can broaden the search to unrelated offers.
    if campaign_topic and any(
        term in compact_user_text
        for term in ("費用", "價格", "價錢", "多少", "年繳", "半年", "月繳", "贈品", "申請", "辦理")
    ):
        if compact_text(campaign_topic).lower() not in compact_text(query).lower():
            return f"{campaign_topic} {query}".strip()

    # The controller may expand a short follow-up with terms found in retrieved
    # child plans. Topic memory must follow what the user actually typed, or a
    # query such as "一年多少" can incorrectly switch 熊搭心 to 瑪帛用戶.
    topic = infer_recent_topic(user_text, memory, history or [])
    if not topic:
        # Do not let a generic menu response erase a concrete product or
        # device the customer just named.  Passing recent user wording to
        # retrieval gives the LLM the actual conversation subject without
        # manufacturing a reply in code.
        recent_user_topics = [
            str(item.get("content") or "").strip()
            for item in history or []
            if str(item.get("role") or "").lower() == "user"
            and str(item.get("content") or "").strip()
        ][-2:]
        if recent_user_topics:
            return f"{' '.join(recent_user_topics)} {query}".strip()
        return query

    compact_query = compact_text(query).lower()
    if campaign_topic and compact_text(campaign_topic).lower() in compact_query:
        return query
    if compact_text(topic).lower() in compact_query:
        return query

    return f"{topic} {query}".strip()


def clear_current_flow(memory: Dict[str, Any]) -> Dict[str, Any]:
    known = memory.setdefault("known_info", {})

    known["troubleshooting_started"] = "no"
    known["troubleshooting_step"] = None
    known["troubleshooting_type"] = None
    known["troubleshooting_failed"] = "no"
    known["repair_ready"] = "no"
    for key in [
        "issue_description",
        "affected_scope",
        "modem_light_status",
        "repair_flow_status",
        "repair_followup_active",
    ]:
        known.pop(key, None)

    memory["pending_tool"] = None
    memory["pending_tool_args"] = []
    memory["clarify_context"] = None

    return memory


def clear_intent_context(memory: Dict[str, Any]) -> Dict[str, Any]:
    """Clear transient flow and retrieval anchors before a separate request."""
    memory = clear_current_flow(memory)
    memory["last_tool"] = None
    memory["last_tool_result"] = None
    memory["last_knowledge_results"] = []
    memory.pop("last_campaign_topic", None)
    memory.pop("last_value_added_topic", None)
    memory.pop("service", None)
    memory.pop("issue_type", None)
    memory.pop("next_goal", None)

    known = memory.setdefault("known_info", {})
    known.pop("last_value_added_topic", None)
    known.pop("disabled_tool", None)
    known.pop(IDENTITY_LOOKUP_FAILURE_COUNT_KEY, None)
    known.pop(IDENTITY_LOOKUP_FAILURE_TOOL_KEY, None)
    known.pop(IDENTITY_LOOKUP_FAILURE_REMINDED_KEY, None)
    memory["known_info"] = known
    return memory


def build_plan_from_router(router: Dict[str, Any]) -> Dict[str, Any]:
    route = router.get("route")
    intent = router.get("intent", "other")
    reply = router.get("reply") or "請問您想查詢資料、辦理服務，還是回報故障呢？"
    if intent == "invoice_carrier_binding_confirmation":
        reply = INVOICE_CARRIER_BINDING_CONFIRMATION_REPLY
    elif intent == "tv_password_prompt":
        reply = TV_PASSWORD_PROMPT_REPLY
    elif intent == "tv_unauthorized_paid_channel_guidance":
        reply = TV_UNAUTHORIZED_PAID_CHANNEL_REPLY
    elif intent == "service_account_transfer":
        reply = SERVICE_ACCOUNT_TRANSFER_REPLY
    elif intent == "repair_visit_expectation":
        reply = REPAIR_VISIT_EXPECTATION_REPLY
    elif intent == "installation_visit_expectation":
        reply = REPAIR_VISIT_EXPECTATION_REPLY
    elif intent == "broadband_termination_guidance":
        reply = BROADBAND_TERMINATION_GUIDANCE_REPLY
    elif intent == "points_account_merge_policy":
        reply = POINTS_ACCOUNT_MERGE_REPLY

    return {
        "intent": intent,
        "decision_type": ROUTE_DECISION_TYPES.get(route, "clarify"),
        "service": None,
        "issue_type": None,
        "should_call_tool": bool(router.get("should_call_tool")),
        "tool_name": router.get("tool_name"),
        "should_retrieve_knowledge": bool(router.get("should_retrieve_knowledge")),
        "knowledge_query": router.get("knowledge_query") or router.get("topic"),
        "service_scope": router.get("service_scope"),
        "requested_information": router.get("requested_information"),
        "promotion_scope": router.get("promotion_scope"),
        "promotion_query_kind": router.get("promotion_query_kind"),
        "social_discount_requested": bool(router.get("social_discount_requested")),
        "selected_option_id": router.get("selected_option_id"),
        "target_document_id": router.get("target_document_id"),
        "target_knowledge_base": router.get("target_knowledge_base"),
        "extracted_slots": router.get("extracted_slots", {}),
        "reply": reply,
        "next_goal": route or "none",
        "need_dispatch": None,
    }


def build_troubleshooting_plan(memory: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "intent": "troubleshooting",
        "decision_type": "direct_reply",
        "service": memory.get("service"),
        "issue_type": memory.get("issue_type"),
        "should_call_tool": False,
        "tool_name": None,
        "should_retrieve_knowledge": False,
        "knowledge_query": None,
        "extracted_slots": {},
        "reply": "",
        "next_goal": "continue_current_flow",
        "need_dispatch": None,
    }


def build_clarify_context(router: Dict[str, Any], original_query: str = "") -> Dict[str, Any] | None:
    topic = router.get("topic")
    intent = router.get("intent")

    if intent in {"human_handoff_confirmation", "human_handoff_triage"}:
        return {
            "type": "human_handoff_triage",
            "topic": "真人客服問題",
        }

    if intent == "overdue_reconnection_service_clarify":
        context = get_clarify_context("復線服務類型")
        if context is not None and original_query:
            context["original_query"] = original_query
        return context

    if intent == "service_termination_service_clarify":
        # The first turn was classified by the LLM.  Keep only that scoped
        # selection state so the following answer cannot be polluted by a
        # generic, mismatched equipment article.
        return {
            "type": "llm_termination_service_selection",
            "topic": "退租服務類型",
            "original_query": original_query,
        }

    if intent == "service_account_transfer_service_clarify":
        return {
            "type": "service_account_transfer_service_selection",
            "topic": "更名服務類型",
            "original_query": original_query,
        }

    if intent in {"general_channel_e004_temp_restore_clarify", "personal_monthly_fee_clarify"}:
        topic = "一般頻道 E004 暫復確認" if intent == "general_channel_e004_temp_restore_clarify" else "月租查詢類型"
        context = get_clarify_context(topic)
        if context is not None and original_query:
            context["original_query"] = original_query
        return context

    if intent == "knowledge_entity_confirmation":
        entity = router.get("entity_confirmation")
        if not isinstance(entity, dict) or not entity.get("name") or not entity.get("knowledge_query"):
            return None
        return {
            "type": "knowledge_entity_confirmation",
            "topic": "加值產品與服務",
            "name": entity["name"],
            "original_query": entity.get("original_query"),
            "knowledge_query": entity["knowledge_query"],
            "prompt": router.get("reply") or f"請問您指的是「{entity['name']}」服務嗎？",
        }

    if intent == "value_added_service_clarification":
        # The LLM may use a descriptive topic such as "加值產品與服務".  The
        # conversation state must still retain the concrete choices it just
        # asked the customer to select from.
        context = get_clarify_context("加值服務")
        if context is not None and original_query:
            context["original_query"] = original_query
        return context

    if intent == "promotion_service_scope_clarification":
        context = get_clarify_context("優惠方案服務類型")
        if context is not None and original_query:
            context["original_query"] = original_query
        return context

    if intent != "ambiguous_short_query":
        return None

    context = get_clarify_context(topic)
    if context is not None and original_query:
        context["original_query"] = original_query
    return context


def resolve_clarify_context(user_text: str, memory: Dict[str, Any]) -> Dict[str, Any] | None:
    context = memory.get("clarify_context")
    if not context:
        return None

    if context.get("type") == "llm_termination_service_selection":
        # Let the user's service choice be classified by the LLM.  The router
        # consumes this limited context after that classification.
        return None

    if context.get("type") == "service_account_transfer_service_selection":
        compact = compact_text(user_text)
        if any(term in compact for term in ("有線電視", "第四台", "電視")):
            memory["clarify_context"] = None
            return {
                "route": "direct_reply",
                "intent": "tv_account_transfer_document_guidance",
                "topic": "有線電視更名應備文件",
                "reply": (
                    "了解，您是要辦理有線電視更名。"
                    "目前線上資料未列出有線電視更名的正式證件清單；"
                    "為避免遺漏，請由櫃台或客服依原用戶與新用戶身分確認需攜帶的證件與文件。"
                ),
            }
        if any(term in compact for term in ("寬頻", "網路", "光纖")):
            memory["clarify_context"] = None
            return {
                "route": "direct_reply",
                "intent": "broadband_account_transfer_document_guidance",
                "topic": "寬頻網路更名應備文件",
                "reply": (
                    "了解，您是要辦理寬頻網路更名。"
                    "目前線上資料未列出寬頻網路更名的正式證件清單；"
                    "為避免遺漏，請由櫃台或客服依原用戶與新用戶身分確認需攜帶的證件與文件。"
                ),
            }
        return {
            "route": "clarify",
            "intent": "service_account_transfer_service_clarify",
            "topic": "更名服務類型",
            "next_clarify_context": dict(context),
            "reply": (
                "為確認變更戶名時需要攜帶的證件與文件，"
                "請問您要辦理有線電視更名還是寬頻網路更名？"
            ),
        }

    if context.get("type") in {"human_handoff_confirmation", "human_handoff_triage"}:
        if is_human_handoff_confirmation_no(user_text):
            return {
                "route": "direct_reply",
                "intent": "human_handoff_declined",
                "topic": "真人客服",
                "reply": "好的，我先不轉真人客服。請直接告訴我想查詢的內容，我會先協助您整理。",
            }
        if has_human_handoff_issue_details(user_text):
            memory.setdefault("known_info", {})["human_handoff_issue_described"] = "yes"
            memory["clarify_context"] = None
            return {
                "route": "direct_reply",
                "intent": "human_handoff_request",
                "topic": "真人客服",
                "reply": WEB_HUMAN_HANDOFF_REPLY,
            }

        return {
            "route": "clarify",
            "intent": "human_handoff_triage",
            "topic": "真人客服問題",
            "next_clarify_context": {
                "type": "human_handoff_triage",
                "topic": "真人客服問題",
            },
            "reply": HUMAN_HANDOFF_TRIAGE_REPLY,
        }

    if context.get("type") == "knowledge_entity_confirmation":
        if is_human_handoff_confirmation_yes(user_text):
            return {
                "route": "knowledge_query",
                "intent": "value_added_product_query",
                "topic": context.get("topic") or "加值產品與服務",
                "knowledge_query": context.get("knowledge_query"),
                "reply": "",
            }
        if is_human_handoff_confirmation_no(user_text):
            return {
                "route": "direct_reply",
                "intent": "knowledge_entity_confirmation_declined",
                "topic": context.get("topic") or "加值產品與服務",
                "reply": "了解，請告訴我正確的服務名稱，或直接描述您想了解的內容。",
            }

        # A substantive new message is a topic change, not another attempt to
        # force the suggested name onto the user.
        memory["clarify_context"] = None
        return None

    compact_selection_text = compact_text(user_text)
    # A named full-package product (for example, a product name containing
    # ASCII words plus "全餐") is not one of the generic add-on menu choices.
    # Let the LLM classify it and retrieve the package's own procedure.
    if (
        context.get("topic") == "加值服務"
        and any(term in compact_selection_text for term in ("套餐", "全餐"))
        and bool(re.search(r"[a-z]", compact_selection_text, flags=re.IGNORECASE))
    ):
        memory["clarify_context"] = None
        return None

    selection = match_clarify_option(user_text, context)
    if selection:
        original_query = str(context.get("original_query") or "")
        matched_option = str(selection.get("matched_option") or "")
        if context.get("topic") == "優惠方案服務類型" and original_query:
            knowledge_query = str(selection.get("knowledge_query") or "").strip()
            if knowledge_query:
                selection["knowledge_query"] = f"{knowledge_query} {original_query}".strip()
        if (
            context.get("topic") == "加值服務"
            and matched_option == "WiFi 加值服務"
            and "youtube" in original_query.lower()
        ):
            return {
                "route": "direct_reply",
                "intent": "wifi_value_added_youtube_scope",
                "topic": "WiFi 加值服務",
                "reply": WIFI_VALUE_ADDED_YOUTUBE_REPLY,
                "matched_option": matched_option,
            }
        compact_selection_text = (user_text or "").replace(" ", "").replace("　", "")
        if (
            context.get("topic") == "加值服務"
            and matched_option == "WiFi 加值服務"
            and compact_selection_text in {"2", "２", "第二個", "第2個", "選2"}
        ):
            return {
                "route": "direct_reply",
                "intent": "wifi_value_added_service",
                "topic": "WiFi 加值服務",
                "reply": WIFI_VALUE_ADDED_SERVICE_REPLY,
                "matched_option": matched_option,
            }
        return selection

    # A customer may replace a broad add-on choice with a specific product or
    # package name. Clear the generic menu so the LLM can interpret that new
    # subject instead of repeatedly presenting the old options.
    compact_user_text = compact_text(user_text)
    if (
        context.get("topic") == "加值服務"
        and len(compact_user_text) >= 3
        and compact_user_text not in {"不知道", "不確定", "不清楚"}
    ):
        memory["clarify_context"] = None
        return None

    return match_contextual_clarify_fallback(user_text, context)


def resolve_model_selected_context(
    memory: Dict[str, Any],
    router: Dict[str, Any],
) -> tuple[Dict[str, Any], bool]:
    """Validate an LLM-selected clarify option against conversation state.

    The model interprets the customer's wording and returns only an option ID.
    This function never guesses from the message text; it accepts an ID only
    when it exists in the exact option set previously shown to the customer.
    Route, tool, reply and source-document fields come from the validated
    option rather than from model-supplied identifiers.
    """
    context = memory.get("clarify_context")
    if not isinstance(context, dict):
        return router, False

    selected_option_id = str(router.get("selected_option_id") or "").strip()
    if not selected_option_id:
        return router, False

    options = context.get("options")
    if not isinstance(options, dict):
        return router, False

    selected_name = ""
    selected: Dict[str, Any] | None = None
    for name, raw_option in options.items():
        if not isinstance(raw_option, dict):
            continue
        if str(raw_option.get("option_id") or "").strip() == selected_option_id:
            selected_name = str(name or raw_option.get("topic") or "").strip()
            selected = raw_option
            break

    if selected is None:
        invalid = dict(router)
        invalid.update({
            "route": "clarify",
            "intent": "dynamic_option_selection_invalid",
            "tool_name": None,
            "topic": context.get("topic"),
            "should_cancel_current_flow": False,
            "should_call_tool": False,
            "should_retrieve_knowledge": False,
            "knowledge_query": None,
            "selected_option_id": None,
            "target_document_id": None,
            "target_knowledge_base": None,
            "reply": "請從上一則清單選擇方案名稱或編號。",
            "reason": "model_selected_option_not_in_context",
        })
        return invalid, False

    selected_route = str(selected.get("route") or "clarify")
    is_knowledge = selected_route == "knowledge_query"
    is_tool = selected_route == "tool_action"
    validated = dict(router)
    validated.update({
        "route": selected_route,
        "intent": selected.get("intent") or "knowledge_option_selection",
        "tool_name": selected.get("tool_name") if is_tool else None,
        "topic": selected.get("topic") or selected_name,
        "should_cancel_current_flow": False,
        "should_call_tool": is_tool,
        "should_retrieve_knowledge": is_knowledge,
        "knowledge_query": (
            selected.get("knowledge_query") or selected_name
            if is_knowledge
            else None
        ),
        "requested_information": selected.get("requested_information"),
        "promotion_scope": selected.get("promotion_scope"),
        "promotion_query_kind": selected.get("promotion_query_kind"),
        "social_discount_requested": bool(selected.get("social_discount_requested")),
        "selected_option_id": selected_option_id,
        "target_document_id": selected.get("document_id") if is_knowledge else None,
        "target_knowledge_base": selected.get("knowledge_base") if is_knowledge else None,
        "reply": selected.get("reply") or "",
        "reason": "model_selected_context_validated",
    })
    return validated, True


# Backward-compatible import name. Production selection validation is generic;
# it is not limited to campaign catalogs.
resolve_model_selected_knowledge_context = resolve_model_selected_context


def build_plan_from_clarify_selection(selection: Dict[str, Any]) -> Dict[str, Any]:
    route = selection.get("route")

    return {
        "intent": selection.get("intent") or "clarify_resolved",
        "decision_type": ROUTE_DECISION_TYPES.get(route, "clarify"),
        "service": None,
        "issue_type": None,
        "should_call_tool": route == "tool_action",
        "tool_name": selection.get("tool_name"),
        "should_retrieve_knowledge": route == "knowledge_query",
        "knowledge_query": selection.get("knowledge_query"),
        "promotion_scope": selection.get("promotion_scope"),
        "promotion_query_kind": selection.get("promotion_query_kind"),
        "social_discount_requested": bool(selection.get("social_discount_requested")),
        "selected_option_id": selection.get("option_id"),
        "target_document_id": selection.get("document_id"),
        "target_knowledge_base": selection.get("knowledge_base"),
        "extracted_slots": {},
        "reply": selection.get("reply") or (
            "請問您想選擇哪一項服務呢？" if route == "clarify" else ""
        ),
        "next_goal": route or "none",
        "need_dispatch": None,
    }


def is_likely_slot_answer(text: str) -> bool:
    text = (text or "").strip()

    if not text:
        return False

    if is_human_handoff_query(text):
        return False

    # 電話、姓名、地址、日期、時段，通常是補資料
    if any(ch.isdigit() for ch in text):
        return True

    address_candidate = text.replace("網路", "").replace("線路", "")
    if any(k in address_candidate for k in ["路", "街", "巷", "號", "區", "市", "縣"]):
        return True

    if any(k in text for k in ["今天", "明天", "後天", "上午", "下午", "晚上"]):
        return True

    # 短中文姓名，例如王大明
    if 2 <= len(text) <= 4 and all("\u4e00" <= ch <= "\u9fff" for ch in text):
        # 但排除常見意圖詞
        if text not in ["網路", "電視", "帳單", "繳費", "優惠", "報修", "合約", "我的合約", "服務內容"]:
            return True

    return False


def is_likely_active_flow_switch(text: str) -> bool:
    value = (text or "").strip()
    if not value:
        return False

    normalized = value.replace(" ", "").replace("　", "")
    if any(term in normalized for term in ACTIVE_FLOW_SWITCH_TERMS):
        return True

    if any(marker in normalized for marker in ACTIVE_FLOW_QUESTION_MARKERS):
        return len(normalized) >= 5 and not is_likely_slot_answer(normalized)

    return False


CONTEXTUAL_WEBSITE_GENERIC_TERMS = {
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
}


CONTEXTUAL_WEBSITE_TOPIC_HINTS = (
    "主機",
    "方案",
    "服務",
    "網路",
    "電視",
    "機上盒",
    "頻道",
    "加值",
    "套餐",
    "IP",
    "ip",
    "LINE",
    "TV",
    "WiFi",
    "wifi",
)


def is_likely_identity_slot_when_finding_topic(text: str) -> bool:
    compact = compact_text(text)
    if any(ch.isdigit() for ch in compact):
        return True
    if any(k in compact for k in ["路", "街", "巷", "號", "區", "市", "縣"]):
        return True
    if any(k in compact for k in ["今天", "明天", "後天", "上午", "下午", "晚上"]):
        return True
    if (
        2 <= len(compact) <= 4
        and all("\u4e00" <= ch <= "\u9fff" for ch in compact)
        and not any(term in text for term in CONTEXTUAL_WEBSITE_TOPIC_HINTS)
    ):
        return True
    return False


def infer_contextual_website_page_topic(history: List[Dict[str, str]]) -> str | None:
    for item in reversed(history or []):
        if str(item.get("role") or "").lower() != "user":
            continue
        content = str(item.get("content") or "").strip()
        if not content:
            continue
        compact = compact_text(content)
        if compact in CONTEXTUAL_WEBSITE_GENERIC_TERMS:
            continue
        if is_contextual_website_page_request(content):
            continue
        if is_likely_identity_slot_when_finding_topic(content):
            continue
        if len(compact) <= 30:
            return content
    return None


def build_contextual_website_page_switch_router(
    user_text: str,
    history: List[Dict[str, str]],
) -> Dict[str, Any] | None:
    if not is_contextual_website_page_request(user_text):
        return None

    topic = infer_contextual_website_page_topic(history)
    if not topic:
        return None

    if is_virtual_hosting_query(topic):
        return {
            "route": "direct_reply",
            "intent": "unsupported_virtual_hosting_service",
            "tool_name": None,
            "topic": "虛擬主機",
            "should_cancel_current_flow": True,
            "should_call_tool": False,
            "should_retrieve_knowledge": False,
            "knowledge_query": None,
            "reply": VIRTUAL_HOSTING_UNSUPPORTED_REPLY,
            "extracted_slots": {},
            "reason": "active_flow_switch_virtual_hosting_unsupported",
        }

    knowledge_query = (
        f"{topic} 官網 頁面 介紹 服務內容 申辦方式 "
        f"{user_text}"
    ).strip()
    return {
        "route": "knowledge_query",
        "intent": "contextual_website_page_lookup",
        "tool_name": None,
        "topic": topic,
        "should_cancel_current_flow": True,
        "should_call_tool": False,
        "should_retrieve_knowledge": True,
        "knowledge_query": knowledge_query,
        "reply": "",
        "extracted_slots": {},
        "reason": "active_flow_switch_contextual_website_page_lookup",
    }


def is_troubleshooting_context_followup(user_text: str) -> bool:
    compact = (user_text or "").replace(" ", "").replace("　", "")
    if not compact:
        return False
    return is_direct_fault_report(compact) or any(
        term.replace(" ", "").replace("　", "") in compact
        for term in TROUBLESHOOTING_CONTEXT_FOLLOWUP_TERMS
    )


def infer_troubleshooting_type_from_user_history(
    user_text: str,
    history: List[Dict[str, str]],
) -> str | None:
    if not is_troubleshooting_context_followup(user_text):
        return None

    recent_user_texts = [
        str(item.get("content") or "")
        for item in (history or [])[-8:]
        if item.get("role") == "user"
    ]
    for previous_text in reversed(recent_user_texts):
        troubleshooting_type = detect_troubleshooting_type(previous_text)
        if troubleshooting_type:
            return troubleshooting_type

    recent = "".join(recent_user_texts)
    if any(term in recent for term in ("網路", "寬頻", "光纖", "上網", "網速")):
        return "network"
    if any(term in recent for term in ("有線電視", "第四台", "電視", "機上盒", "頻道")):
        return "tv"
    if any(term in recent for term in ("遙控器", "遙控")):
        return "remote"
    return None


def default_troubleshooting_step_for_context(
    troubleshooting_type: str,
    user_text: str,
    history: List[Dict[str, str]],
) -> str:
    recent = "".join(str(item.get("content") or "") for item in (history or [])[-8:])
    combined = f"{recent}\n{user_text or ''}"
    if troubleshooting_type == "network":
        if is_network_slow_issue(combined):
            return "net_slow_scope"
        return "net_check_scope"
    if troubleshooting_type == "remote":
        return "remote_check_light"
    if any(term in combined for term in ("無反應", "沒反應", "沒亮", "不亮")):
        return "tv_check_power"
    return "tv_reboot"


def retain_reported_equipment_power_context(
    user_text: str,
    memory: Dict[str, Any],
    history: List[Dict[str, str]],
) -> None:
    """Carry a customer's prior no-light report into a named-device reply."""
    current = (user_text or "").replace(" ", "").replace("　", "")
    if not any(term in current for term in ("機上盒", "數據機", "分享器")):
        return

    prior_user_text = "".join(
        str(message.get("content") or "")
        for message in history or []
        if str(message.get("role") or "").lower() == "user"
    )
    has_no_light = any(term in prior_user_text for term in ("無亮燈", "沒亮燈", "沒有亮燈", "燈不亮"))
    has_power_context = any(term in prior_user_text for term in ("插電", "電源", "插頭"))
    if not (has_no_light and has_power_context):
        return

    known = memory.setdefault("known_info", {})
    known["power_status"] = "off"
    known.setdefault("issue_description", "設備已插電但沒有亮燈")


def recover_troubleshooting_state_from_history(
    user_text: str,
    memory: Dict[str, Any],
    history: List[Dict[str, str]],
) -> bool:
    known = memory.setdefault("known_info", {})
    if known.get("troubleshooting_started") == "yes" or memory.get("pending_tool"):
        return False

    text = (user_text or "").strip()
    if not text:
        return False

    normalized = text.replace(" ", "").replace("　", "")
    strong_switch = any(
        term.replace(" ", "").replace("　", "") in normalized
        for term in STRONG_TOPIC_SWITCH_TERMS
    )
    if normalized in {"查詢", "查一下", "幫我查", "幫我查詢", "查區故", "查區域故障"}:
        recent = "".join(str(item.get("content") or "") for item in (history or [])[-6:])
        recent_compact = recent.replace(" ", "").replace("　", "")
        has_network_instability = any(
            term in recent_compact
            for term in ("網路很不穩", "網路不穩", "網路不太穩", "連線不穩", "上網不穩")
        )
        has_outage_context = any(term in recent_compact for term in ("發生什麼事", "區域故障", "區故", "無公告"))
        if has_network_instability and has_outage_context:
            return False

    contextual_type = infer_troubleshooting_type_from_user_history(text, history)
    if contextual_type in {"network", "tv", "remote"}:
        known["troubleshooting_started"] = "yes"
        known["troubleshooting_type"] = contextual_type
        known["troubleshooting_step"] = default_troubleshooting_step_for_context(
            contextual_type,
            text,
            history,
        )
        known["troubleshooting_failed"] = "no"
        known["repair_ready"] = "no"
        known["retry"] = 0
        known.setdefault("issue_description", "使用者前文已描述故障，最新訊息要求排除或報修")
        known["_troubleshooting_restored_from_history"] = "yes"
        known["_troubleshooting_restored_source"] = "user_history"
        return True

    if text in TOPIC_WORDS or is_likely_active_flow_switch(text) or strong_switch:
        return False

    for message in reversed(history or []):
        if message.get("role") != "assistant":
            continue

        content = str(message.get("content") or "")
        for markers, troubleshooting_type, step in TROUBLESHOOTING_HISTORY_STEP_MARKERS:
            if all(marker in content for marker in markers):
                known["troubleshooting_started"] = "yes"
                known["troubleshooting_type"] = troubleshooting_type
                known["troubleshooting_step"] = step
                known["troubleshooting_failed"] = "no"
                known["repair_ready"] = "no"
                known["retry"] = 0
                known.setdefault("issue_description", "使用者正在進行故障排錯")
                known["_troubleshooting_restored_from_history"] = "yes"
                return True

        break

    return False


def build_memory_without_active_flow(memory: Dict[str, Any]) -> Dict[str, Any]:
    candidate = {
        key: value
        for key, value in (memory or {}).items()
        if key not in {"pending_tool", "pending_tool_args", "clarify_context"}
    }
    candidate["pending_tool"] = None
    candidate["pending_tool_args"] = []
    candidate["clarify_context"] = None
    candidate["_active_flow_switch_check"] = True

    known = dict(candidate.get("known_info", {}) or {})
    if known.get("troubleshooting_started") == "yes":
        known["_previous_troubleshooting_started"] = "yes"
    known["troubleshooting_started"] = "no"
    known["troubleshooting_step"] = None
    known["troubleshooting_type"] = None
    known["troubleshooting_failed"] = "no"
    known["repair_ready"] = "no"
    candidate["known_info"] = known
    return candidate


def build_reconnection_switch_router(
    user_text: str,
    memory: Dict[str, Any],
) -> Dict[str, Any] | None:
    value = (user_text or "").strip()
    known = memory.get("known_info", {}) or {}
    troubleshooting_type = known.get("troubleshooting_type")

    has_completed_payment_signal = any(term in value for term in ["已繳費", "已經繳費", "繳費了", "繳了", "已付款", "付款成功", "付費了"])
    has_payment_signal = has_completed_payment_signal or any(term in value for term in ["繳費", "付款", "付費", "欠費"])
    has_restore_signal = any(term in value for term in ["恢復", "復線", "開通", "斷訊", "停訊", "斷線"])
    if not (has_payment_signal and has_restore_signal):
        return None

    if has_completed_payment_signal:
        return {
            "route": "tool_action",
            "intent": "payment_receipt_reconnection",
            "tool_name": "payment_bill_batch",
            "topic": "超商收據復線",
            "should_cancel_current_flow": True,
            "should_call_tool": True,
            "should_retrieve_knowledge": False,
            "knowledge_query": None,
            "reply": "可以，我幫您確認超商繳費收據並處理復線。請上傳超商繳費收據圖片，我會辨識收據上的三段條碼。",
            "extracted_slots": {},
            "reason": "active_flow_switch_payment_receipt_reconnection",
        }

    if troubleshooting_type == "network":
        return {
            "route": "tool_action",
            "intent": "reconnection",
            "tool_name": "bill_return_line_internet",
            "topic": "網路復線",
            "should_cancel_current_flow": True,
            "should_call_tool": True,
            "should_retrieve_knowledge": False,
            "knowledge_query": None,
            "reply": "可以，我幫您處理網路復線申請。",
            "extracted_slots": {},
            "reason": "active_flow_switch_network_reconnection",
        }

    if troubleshooting_type == "tv":
        return {
            "route": "tool_action",
            "intent": "reconnection",
            "tool_name": "bill_return_line_tv",
            "topic": "電視復線",
            "should_cancel_current_flow": True,
            "should_call_tool": True,
            "should_retrieve_knowledge": False,
            "knowledge_query": None,
            "reply": "可以，我幫您處理電視復線申請。",
            "extracted_slots": {},
            "reason": "active_flow_switch_tv_reconnection",
        }

    return None


def requires_receipt_image_evidence(
    user_text: str,
    router: Dict[str, Any],
    memory: Dict[str, Any],
) -> bool:
    value = (user_text or "").replace(" ", "").replace("　", "")
    if (router or {}).get("tool_name") == "payment_bill_batch":
        return True

    if is_receipt_image_submission(user_text, memory):
        return True

    barcode_labels = len(re.findall(r"第\s*[一二三123]\s*段(?:\s*條碼)?", value))
    if barcode_labels >= 2:
        return True

    paid = any(term in value for term in ("已繳費", "已經繳費", "繳費完成", "繳費成功", "已付款"))
    restore = any(term in value for term in ("恢復", "復線", "開通", "不能看", "不能上網"))
    return paid and restore


def is_unpaid_partial_payment_question(user_text: str) -> bool:
    value = compact_text(user_text)
    explicitly_unpaid = any(
        term in value
        for term in ("未繳", "沒繳", "尚未繳", "忘了繳", "還沒繳", "費用沒付")
    )
    asks_partial_payment = (
        any(term in value for term in ("先繳", "只繳", "單繳", "分開繳", "拆開繳"))
        and any(term in value for term in ("電視", "網路", "其中一項", "一項"))
    )
    return explicitly_unpaid and asks_partial_payment


def is_unpaid_reactivation_request(user_text: str) -> bool:
    value = compact_text(user_text)
    future_or_missing_payment = any(
        term in value
        for term in (
            "未繳",
            "沒繳",
            "尚未繳",
            "還沒繳",
            "晚點去繳",
            "晚點再繳",
            "之後去繳",
            "之後再繳",
            "等等去繳",
            "稍後去繳",
        )
    )
    asks_reactivation = any(
        term in value
        for term in ("幫我恢復", "先恢復", "先復線", "恢復服務", "恢復使用", "先開通")
    )
    return future_or_missing_payment and asks_reactivation


def build_unpaid_reactivation_router() -> Dict[str, Any]:
    return {
        "route": "direct_reply",
        "intent": "unpaid_reactivation_guidance",
        "tool_name": None,
        "topic": "未繳費復線限制",
        "should_cancel_current_flow": True,
        "should_call_tool": False,
        "should_retrieve_knowledge": False,
        "knowledge_query": None,
        "reply": (
            "目前尚未完成繳費，無法先執行復線。請先透過官網或哈TV行動客服 APP 完成繳費，"
            "待入帳後重新啟動數據機、分享器或機上盒；若已入帳仍未恢復，再由真人客服協助核對。"
        ),
        "extracted_slots": {},
        "reason": "guard_unpaid_reactivation_no_tool_call",
    }


def build_unpaid_partial_payment_router() -> Dict[str, Any]:
    return {
        "route": "direct_reply",
        "intent": "partial_payment_tv_only_guidance",
        "tool_name": None,
        "topic": "多服務部分繳費",
        "should_cancel_current_flow": True,
        "should_call_tool": False,
        "should_retrieve_knowledge": False,
        "knowledge_query": None,
        "reply": (
            "您目前尚未繳費，因此這一輪不會直接執行復線。"
            "是否可只繳有線電視，以及各服務可拆分的待繳金額，需以帳單資料為準。"
            "請先至官網或哈TV行動客服 APP 查看待繳項目；若畫面無法分開繳納，"
            "再由真人客服協助核對。完成繳費並入帳後，再重新啟動機上盒確認收視。"
        ),
        "extracted_slots": {},
        "reason": "guard_unpaid_partial_payment_no_reactivation",
    }


def detect_active_flow_switch(
    user_text: str,
    memory: Dict[str, Any],
    history: List[Dict[str, str]],
    llm,
    latency: Dict[str, Any],
) -> Dict[str, Any] | None:
    candidate_memory = build_memory_without_active_flow(memory)
    t0 = time.perf_counter()
    router = run_intent_router(
        user_input=user_text,
        memory=candidate_memory,
        history=history,
        llm=llm,
    )
    latency["intent_router_interrupt"] = time.perf_counter() - t0

    active_type = str((memory.get("known_info") or {}).get("troubleshooting_type") or "")
    model_context = " ".join(
        str(router.get(key) or "")
        for key in ("intent", "service_scope", "topic", "requested_information")
    ).lower()
    incoming_type = (
        "network"
        if any(term in model_context for term in ("internet", "network", "網路", "寬頻"))
        else "remote"
        if any(term in model_context for term in ("remote", "遙控"))
        else "tv"
        if any(term in model_context for term in ("tv_", "電視", "機上盒", "頻道"))
        else ""
    )
    # A troubleshooting result means "continue" only when the LLM kept the
    # same service. A model-selected TV-to-network (or reverse) change is a
    # new issue and must replace the active SOP instead of consuming its next
    # question as an unrelated answer.
    if (
        router.get("route") == "troubleshooting"
        and active_type in {"tv", "network", "remote"}
        and incoming_type
        and incoming_type != active_type
    ):
        router["should_cancel_current_flow"] = True
        router["reason"] = f"active_flow_switch_troubleshooting_{incoming_type}"
        return router

    # A fresh LLM decision of ``troubleshooting`` while the same SOP is active
    # confirms the current flow. Return that decision so the troubleshooting
    # engine can use the model's latest semantic intent instead of collapsing
    # every active turn to the generic ``troubleshooting`` intent.
    if router.get("route") not in {"unknown", "continue_current_flow", "troubleshooting"}:
        router["should_cancel_current_flow"] = True
        router["reason"] = f"active_flow_switch_{router.get('reason') or router.get('route')}"
        return router

    if (
        active_type in {"tv", "network", "remote"}
        and router.get("route") in {"continue_current_flow", "troubleshooting"}
    ):
        router["should_cancel_current_flow"] = False
        return router

    return None


def should_cancel_pending_tool(user_text: str, router: Dict[str, Any], memory: Dict[str, Any]) -> bool:
    pending_tool = memory.get("pending_tool")

    if not pending_tool:
        return False

    text = (user_text or "").strip()
    route = router.get("route")
    new_tool = router.get("tool_name")

    # 如果看起來是補資料，不取消
    if is_likely_slot_answer(text):
        return False

    return route not in {"unknown", "continue_current_flow"} and (
        route != "tool_action" or new_tool != pending_tool
    )


def clear_pending_tool(memory: Dict[str, Any]) -> Dict[str, Any]:
    memory["pending_tool"] = None
    memory["pending_tool_args"] = []
    memory["last_tool"] = None
    reset_identity_lookup_failure(memory)
    return memory


def clear_missing_tool_fields(memory: Dict[str, Any], missing: List[str]) -> Dict[str, Any]:
    known = memory.setdefault("known_info", {})
    for slot in missing:
        known.pop(slot, None)
    memory["known_info"] = known
    return memory


def reset_identity_lookup_failure(memory: Dict[str, Any]) -> Dict[str, Any]:
    known = memory.setdefault("known_info", {})
    known.pop(IDENTITY_LOOKUP_FAILURE_COUNT_KEY, None)
    known.pop(IDENTITY_LOOKUP_FAILURE_TOOL_KEY, None)
    known.pop(IDENTITY_LOOKUP_FAILURE_REMINDED_KEY, None)
    memory["known_info"] = known
    return memory


def is_customer_identity_not_found(tool_result: Dict[str, Any]) -> bool:
    if tool_result.get("success"):
        return False

    message = str(tool_result.get("message") or "")
    return (
        CUSTOMER_NOT_FOUND_MESSAGE in message
        or "查無客戶" in message
        or "查詢不到您的資料" in message
        or "資料目前已停用" in message
    )


def update_identity_lookup_failure_state(
    memory: Dict[str, Any],
    tool_name: str,
    tool_result: Dict[str, Any],
) -> tuple[Dict[str, Any], bool]:
    if tool_name not in IDENTITY_LOOKUP_TOOL_NAMES:
        return memory, False

    if tool_result.get("success"):
        return reset_identity_lookup_failure(memory), False

    if not is_customer_identity_not_found(tool_result):
        return memory, False

    known = memory.setdefault("known_info", {})
    previous_tool = known.get(IDENTITY_LOOKUP_FAILURE_TOOL_KEY)
    count = int(known.get(IDENTITY_LOOKUP_FAILURE_COUNT_KEY) or 0)
    if previous_tool and previous_tool != tool_name:
        count = 0
        known[IDENTITY_LOOKUP_FAILURE_REMINDED_KEY] = "no"

    count += 1
    known[IDENTITY_LOOKUP_FAILURE_COUNT_KEY] = count
    known[IDENTITY_LOOKUP_FAILURE_TOOL_KEY] = tool_name

    should_remind = count >= 3 and known.get(IDENTITY_LOOKUP_FAILURE_REMINDED_KEY) != "yes"
    if should_remind:
        known[IDENTITY_LOOKUP_FAILURE_REMINDED_KEY] = "yes"

    memory["known_info"] = known
    return memory, should_remind


def run_tool_or_rag_flow(
    user_text: str,
    memory: Dict[str, Any],
    plan: Dict[str, Any],
    router: Dict[str, Any],
    latency: Dict[str, float],
    history: List[Dict[str, str]] | None = None,
    llm=None,
    rag_summary_llm=None,
) -> tuple[str, Dict[str, Any]]:
    reply = plan.get("reply", "請問您想查詢資料、辦理服務，還是回報故障呢？")

    pending_tool = memory.get("pending_tool")
    in_pending_mode = bool(pending_tool)

    should_call_tool = plan.get("should_call_tool", False)
    tool_name = plan.get("tool_name")

    if in_pending_mode and plan.get("skip_pending_tool_call") is True:
        should_call_tool = False
        tool_name = None

    elif in_pending_mode:
        should_call_tool = True
        tool_name = pending_tool

    elif router.get("route") == "tool_action":
        should_call_tool = True
        tool_name = router.get("tool_name") or plan.get("tool_name")

    elif plan.get("tool_name") == "create_repair_ticket" and plan.get("should_call_tool") is True:
        should_call_tool = True
        tool_name = "create_repair_ticket"

    else:
        should_call_tool = False
        tool_name = None

    if router.get("route") == "company_info":
        info_topic = router.get("topic") or plan.get("knowledge_query") or "company_overview"
        reply = build_company_info_reply(
            info_topic,
            memory.get("company_code", DEFAULT_TV_CABLE),
        )
        memory["last_knowledge_results"] = []
        if info_topic == "promotion_activity":
            t0 = time.perf_counter()
            rag_plan = dict(plan)
            explicit_knowledge_query = router.get("knowledge_query") or plan.get("knowledge_query")
            if explicit_knowledge_query and explicit_knowledge_query != "優惠方案":
                rag_plan["knowledge_query"] = explicit_knowledge_query
            else:
                rag_plan["knowledge_query"] = (
                    f"優惠方案 {user_text}".strip()
                    if user_text
                    else explicit_knowledge_query
                    or "優惠方案"
                )
            rag_plan["knowledge_query"] = build_promotion_scope_query(
                rag_plan["knowledge_query"],
                router.get("promotion_scope"),
                router.get("promotion_query_kind"),
            )
            rag_plan["knowledge_query"] = build_campaign_detail_context_query(
                rag_plan["knowledge_query"],
                memory,
                router.get("promotion_query_kind"),
                allow_context=not bool(router.get("should_cancel_current_flow")),
            )
            rag_plan["knowledge_query"] = build_contextual_knowledge_query(
                user_text=user_text,
                current_query=rag_plan["knowledge_query"],
                memory=memory,
                history=history or [],
                allow_context=not bool(router.get("should_cancel_current_flow")),
            )
            if router.get("promotion_query_kind") != "catalog":
                rag_plan["knowledge_query"] = expand_targeted_knowledge_query(
                    user_text,
                    rag_plan["knowledge_query"],
                )
            docs = retrieve_knowledge(user_text, memory, rag_plan)
            latency["rag_retrieved_docs"] = len(docs)
            docs = constrain_promotion_documents(
                docs,
                router.get("promotion_scope"),
                router.get("promotion_query_kind"),
                bool(router.get("social_discount_requested")),
            )
            latency["rag_scoped_docs"] = len(docs)
            latency["rag"] = time.perf_counter() - t0
            # A new request is grounded against the customer's actual wording,
            # not a retrieval rewrite that may contain contextual helper terms.
            answer_guard_query = (
                user_text
                if router.get("should_cancel_current_flow")
                else rag_plan["knowledge_query"]
            )
            if rag_plan.get("intent") in COMPLETE_KNOWLEDGE_EVIDENCE_INTENTS:
                evidence_docs = docs
            elif has_compact_promotion_reply(
                user_text,
                docs,
                memory=memory,
                intent=rag_plan.get("intent"),
                promotion_scope=router.get("promotion_scope"),
                promotion_query_kind=router.get("promotion_query_kind"),
            ):
                evidence_docs = docs
            else:
                evidence_docs, _ = filter_docs_with_llm_evidence(
                    user_text,
                    docs,
                    router,
                    llm=rag_summary_llm or llm,
                )
            answerable_docs = filter_answerable_docs(answer_guard_query, evidence_docs)
            latency["rag_answerable_docs"] = len(answerable_docs)
            memory["last_knowledge_results"] = answerable_docs

            if answerable_docs:
                rag_reply = compose_knowledge_reply(
                    user_text,
                    "",
                    answerable_docs,
                    llm=llm,
                    summary_llm=rag_summary_llm,
                    answer_guard_query=answer_guard_query,
                    memory=memory,
                    intent=rag_plan.get("intent"),
                    promotion_scope=router.get("promotion_scope"),
                    promotion_query_kind=router.get("promotion_query_kind"),
                )
                if rag_reply:
                    profile = get_company_profile(memory.get("company_code", DEFAULT_TV_CABLE))
                    company_promotion = (profile.get("promotion_activity") or "").strip()
                    if company_promotion:
                        reply = f"{reply}\n\n{rag_reply}"
                    else:
                        reply = rag_reply
                memory = remember_campaign_topic(
                    memory,
                    reply=reply,
                    docs=answerable_docs,
                    query=answer_guard_query,
                )
                catalog_context = build_promotion_catalog_clarify_context(
                    user_text,
                    answerable_docs,
                    intent=rag_plan.get("intent"),
                    promotion_scope=router.get("promotion_scope"),
                )
                if catalog_context:
                    memory["clarify_context"] = catalog_context

    elif (
        should_call_tool
        and tool_name in REPAIR_TICKET_TOOL_NAMES
        and not REPAIR_TICKET_FLOW_ENABLED
    ):
        disabled_reply = build_repair_ticket_flow_disabled_reply(memory)
        plan_reply = str(plan.get("reply") or "").strip()
        if plan.get("preserve_reply_when_tool_disabled") and plan_reply:
            profile = get_company_profile(memory.get("company_code", DEFAULT_TV_CABLE))
            repair_link = build_company_link(profile, "維修申告")
            reply = f"{plan_reply}\n維修申告：{repair_link}" if repair_link else plan_reply
        else:
            reply = disabled_reply
        memory = disable_repair_ticket_flow(memory, tool_name)

    elif should_call_tool and tool_name in DISABLED_CUSTOMER_TOOL_NAMES:
        reply = CUSTOMER_TOOL_FLOW_DISABLED_MESSAGE
        memory = disable_customer_tool_flow(memory, tool_name)

    elif should_call_tool and tool_name:
        if tool_name == "search_contract_info" and not has_authenticated_web_custnum(memory):
            # Do not collect name/phone for contracts from guest WEB or LINE.
            # The tool layer repeats this guard in case another caller bypasses
            # the chat flow.
            reply = CONTRACT_LOOKUP_LOGIN_REQUIRED_REPLY
            memory = clear_pending_tool(memory)
            memory["pending_tool_missing_repeat_count"] = 0
            memory["last_tool"] = None
            memory["last_tool_result"] = None
            router.update({
                "route": "direct_reply",
                "intent": "contract_lookup_login_required",
                "tool_name": None,
                "should_call_tool": False,
                "should_retrieve_knowledge": False,
                "reply": reply,
                "reason": "guard_contract_lookup_requires_authenticated_web_custnum",
            })
            plan.update({"reply": reply, "should_call_tool": False, "tool_name": None})
        else:
            missing = get_missing_tool_args(tool_name, memory)
            receipt_evidence = (
                current_verified_receipt_image_evidence(memory, user_text)
                if tool_name == "payment_bill_batch"
                else None
            )
            receipt_image_required = tool_name == "payment_bill_batch" and not receipt_evidence
            if receipt_evidence:
                memory.setdefault("known_info", {})["active_receipt_image_evidence"] = receipt_evidence

            if receipt_image_required:
                reply = RECEIPT_IMAGE_REQUIRED_REPLY
                memory = clear_pending_tool(memory)
                memory = clear_unverified_receipt_barcode_slots(memory)
                memory["pending_tool_missing_repeat_count"] = 0
            elif missing:
                previous_pending_tool = memory.get("pending_tool")
                previous_pending_args = list(memory.get("pending_tool_args") or [])
                repeated_missing = (
                    previous_pending_tool == tool_name
                    and previous_pending_args == missing
                )
                repeat_count = int(memory.get("pending_tool_missing_repeat_count") or 0)
                repeat_count = repeat_count + 1 if repeated_missing else 1
                memory["pending_tool_missing_repeat_count"] = repeat_count
                if (
                    tool_name == "search_contract_info"
                    and router.get("intent") == "existing_speed_upgrade_eligibility"
                    and "name" in missing
                    and "phone" in missing
                ):
                    reply = (
                        "可以，我先確認您目前使用的方案及合約狀態，再依您想升級的速率確認"
                        "是否可申請及相關費用，實際以查詢結果為準。"
                        "請同時提供戶名與登記電話。"
                    )
                else:
                    reply = build_missing_args_question(tool_name, missing, memory)
                memory["pending_tool"] = tool_name
                memory["pending_tool_args"] = missing
                memory["last_tool"] = tool_name
            else:
                t0 = time.perf_counter()
                if tool_name in CUST_API_BACKED_TOOL_NAMES:
                    with cust_api_diagnostic_context(tool_name=tool_name):
                        tool_result = call_tool(tool_name, memory)
                        log_cust_api_tool_result(tool_result)
                else:
                    tool_result = call_tool(tool_name, memory)
                if tool_name == "payment_bill_batch":
                    memory.setdefault("known_info", {}).pop("active_receipt_image_evidence", None)
                latency["tool_call"] = time.perf_counter() - t0
                cust_api = tool_result.get("cust_api") or (tool_result.get("data") or {}).get("cust_api") or {}
                if isinstance(cust_api, dict) and cust_api.get("total_sec") is not None:
                    latency["cust_api"] = cust_api.get("total_sec")
                    latency["cust_api_token"] = cust_api.get("token_sec", 0)
                    latency["cust_api_endpoint"] = cust_api.get("endpoint_sec", 0)

                memory["last_tool"] = tool_name
                memory["last_tool_result"] = tool_result
                memory["pending_tool_missing_repeat_count"] = 0
                if tool_name == "search_bill":
                    memory = remember_bill_query_status(memory, tool_result)
                if tool_name == "bill_return_line_tv":
                    memory = remember_tv_reactivation_status(memory, tool_result)

                if not tool_result.get("success"):
                    reply = tool_result.get("message", "資料不足，請再補充必要資訊。")
                    if tool_name in IDENTITY_LOOKUP_TOOL_NAMES:
                        reply = f"本次操作未完成。{reply}"
                        if "真人客服" not in reply:
                            reply += " 若重新確認資料後仍無法完成，請由真人客服協助核對。"
                    memory, should_remind_human_service = update_identity_lookup_failure_state(
                        memory,
                        tool_name,
                        tool_result,
                    )
                    if should_remind_human_service:
                        reply = f"{reply}\n{IDENTITY_LOOKUP_FAILURE_REMINDER}".strip()
                    missing = tool_result.get("data", {}).get("missing", [])
                    if missing:
                        memory = clear_missing_tool_fields(memory, missing)
                        memory["pending_tool"] = tool_name
                        memory["pending_tool_args"] = missing
                    else:
                        memory["pending_tool"] = None
                        memory["pending_tool_args"] = []
                else:
                    memory, _ = update_identity_lookup_failure_state(
                        memory,
                        tool_name,
                        tool_result,
                    )
                    memory["pending_tool"] = None
                    memory["pending_tool_args"] = []
                    reply = format_tool_result(tool_name, tool_result)

    elif plan.get("should_retrieve_knowledge") or router.get("route") in ["knowledge_query", "switch_topic"]:
        t0 = time.perf_counter()
        original_query = (
            plan.get("knowledge_query")
            or router.get("knowledge_query")
            or user_text
        )
        original_query = build_promotion_scope_query(
            original_query,
            plan.get("promotion_scope"),
            plan.get("promotion_query_kind"),
        )
        original_query = build_campaign_detail_context_query(
            original_query,
            memory,
            plan.get("promotion_query_kind"),
            allow_context=not bool(router.get("should_cancel_current_flow")),
        )
        has_validated_knowledge_target = bool(plan.get("target_document_id"))
        has_active_campaign_detail = bool(
            plan.get("promotion_query_kind") == "campaign_detail"
            and not router.get("should_cancel_current_flow")
            and memory.get("last_campaign_topic")
        )
        preserve_exact_knowledge_query = (
            has_validated_knowledge_target
            or has_active_campaign_detail
            or plan.get("intent") == "promotion_named_campaign_selection"
            or plan.get("intent") == "digital_tv_package_addon"
            or plan.get("promotion_query_kind") == "catalog"
        )
        # A named digital-TV package has already been identified by the LLM.
        # Do not let a prior generic add-on menu inject an unrelated product
        # (such as WiFi) into its knowledge query.
        if preserve_exact_knowledge_query:
            enhanced_query = original_query
        else:
            enhanced_query = build_contextual_knowledge_query(
                user_text=user_text,
                current_query=original_query,
                memory=memory,
                history=history or [],
                allow_context=not bool(router.get("should_cancel_current_flow")),
            )
        if not preserve_exact_knowledge_query:
            enhanced_query = expand_targeted_knowledge_query(user_text, enhanced_query)
        plan["knowledge_query"] = enhanced_query
        retrieval_top_k = (
            12
            if plan.get("promotion_query_kind") == "catalog"
            else 8
            if is_basic_tv_monthly_fee_only_query(user_text)
            or is_broadband_plan_price_query(enhanced_query)
            else 5
        )
        docs = retrieve_knowledge(
            user_text,
            memory,
            plan,
            top_k=retrieval_top_k,
        )
        latency["rag_retrieved_docs"] = len(docs)
        docs = constrain_promotion_documents(
            docs,
            plan.get("promotion_scope"),
            plan.get("promotion_query_kind"),
            bool(plan.get("social_discount_requested")),
        )
        docs = carry_forward_same_intent_evidence(
            docs,
            memory,
            plan.get("intent"),
        )
        latency["rag_scoped_docs"] = len(docs)
        latency["rag"] = time.perf_counter() - t0
        # Keep the answerability check anchored to a fresh customer request.
        # The expanded query remains available for genuine follow-ups only.
        answer_guard_query = (
            user_text
            if router.get("should_cancel_current_flow")
            else enhanced_query
        )
        if plan.get("promotion_query_kind") == "catalog":
            answer_guard_query = enhanced_query
        if plan.get("intent") == "next_tier_plan_fee_guidance":
            answer_guard_query = "目前可推廣寬頻方案 升級方案內容 費用 合約資格"

        compact_reply_input = (
            str(router.get("topic") or user_text)
            if plan.get("intent") == "promotion_named_campaign_selection"
            else user_text
        )
        if plan.get("intent") in COMPLETE_KNOWLEDGE_EVIDENCE_INTENTS:
            evidence_docs = docs
        elif has_compact_promotion_reply(
            compact_reply_input,
            docs,
            memory=memory,
            intent=plan.get("intent"),
            promotion_scope=plan.get("promotion_scope"),
            promotion_query_kind=plan.get("promotion_query_kind"),
        ):
            evidence_docs = docs
        else:
            evidence_docs, _ = filter_docs_with_llm_evidence(
                compact_reply_input,
                docs,
                router,
                llm=rag_summary_llm or llm,
            )
        answerable_docs = filter_answerable_docs(answer_guard_query, evidence_docs)
        latency["rag_answerable_docs"] = len(answerable_docs)
        if is_install_application_router_intent(router) and not answerable_docs:
            reply = build_install_application_reply(memory)
        else:
            if plan.get("intent") == "next_tier_plan_fee_guidance":
                summary_input = enhanced_query
            elif plan.get("intent") == "promotion_named_campaign_selection":
                summary_input = str(router.get("topic") or user_text)
            else:
                summary_input = user_text
            reply = compose_knowledge_reply(
                summary_input,
                reply,
                evidence_docs,
                llm=llm,
                summary_llm=rag_summary_llm,
                answer_guard_query=answer_guard_query,
                memory=memory,
                fallback_reply=(
                    POINTS_USAGE_FALLBACK_REPLY
                    if plan.get("intent") == "points_usage_query"
                    else None
                ),
                prefer_compact_upgrade=(
                    plan.get("intent") == "next_tier_plan_fee_guidance"
                ),
                intent=plan.get("intent"),
                promotion_scope=plan.get("promotion_scope"),
                promotion_query_kind=plan.get("promotion_query_kind"),
            )
            if (
                is_install_application_router_intent(router)
                and reply
                and plan.get("promotion_query_kind") != "catalog"
            ):
                reply = (
                    f"{build_install_application_reply(memory)}\n\n"
                    f"目前查到的方案資訊：\n{reply}"
                )
        if plan.get("intent") == "next_tier_plan_fee_guidance" and reply:
            reply = (
                f"{reply}\n\n"
                "原用戶如欲升級網路速率，需先確認目前的方案及合約狀態，再依欲升級的速率確認是否可申請及相關費用，實際以查詢結果為準。"
            )
        memory["last_knowledge_results"] = answerable_docs
        memory["last_knowledge_intent"] = plan.get("intent")
        memory = remember_campaign_topic(
            memory,
            reply=reply,
            docs=memory["last_knowledge_results"],
            query=answer_guard_query,
        )
        catalog_context = build_promotion_catalog_clarify_context(
            user_text,
            memory["last_knowledge_results"],
            intent=plan.get("intent"),
            promotion_scope=plan.get("promotion_scope"),
        )
        if catalog_context:
            memory["clarify_context"] = catalog_context

    else:
        memory["last_knowledge_results"] = []
        memory["last_knowledge_intent"] = None

    memory.pop("_recent_slot_status", None)
    return reply, memory


def handle_chat_message(
    user_id: str,
    user_text: str,
    memory: Dict[str, Any],
    history: List[Dict[str, str]],
    llm,
    rag_summary_llm=None,
    persist: bool = True,
) -> Dict[str, Any]:
    latency = {}
    request_id = uuid4().hex
    t_total = time.perf_counter()
    llm_trace_token = start_llm_trace()

    # The model receives the complete customer history and decides whether the
    # latest turn continues or changes the subject. Keyword domain inference
    # must not prune context or reset state before that decision.
    contextual_history = list(history or [])
    retain_reported_equipment_power_context(
        user_text,
        memory,
        contextual_history,
    )

    known = memory.setdefault("known_info", {})
    memory["last_tool_result"] = None
    pending_tool = memory.get("pending_tool")
    in_pending_mode = bool(pending_tool)
    if pending_tool == "payment_bill_batch":
        # Legacy sessions may still contain a barcode-collection pending flow.
        # It must not survive into the image-evidence-only contract.
        memory = clear_pending_tool(memory)
        memory = clear_unverified_receipt_barcode_slots(memory)
        memory["pending_tool_missing_repeat_count"] = 0
        pending_tool = None
        in_pending_mode = False
    is_troubleshooting = (
        known.get("troubleshooting_started") == "yes"
        or known.get("repair_followup_active") == "yes"
    )
    active_flow_router = None
    if is_troubleshooting or (
        in_pending_mode and not is_likely_slot_answer(user_text)
    ):
        active_flow_router = detect_active_flow_switch(
            user_text=user_text,
            memory=memory,
            history=contextual_history,
            llm=llm,
            latency=latency,
        )

    active_switch_router = (
        active_flow_router
        if active_flow_router and active_flow_router.get("should_cancel_current_flow")
        else None
    )

    if active_switch_router:
        memory = clear_current_flow(memory)
        known = memory.setdefault("known_info", {})
        pending_tool = memory.get("pending_tool")
        in_pending_mode = False
        is_troubleshooting = False

    clarify_context = memory.get("clarify_context")

    invalid_customer_number_router = None
    invalid_customer_number_plan = None
    if (
        in_pending_mode
        and pending_tool in IDENTITY_LOOKUP_TOOL_NAMES
        and has_invalid_customer_number_format(user_text)
    ):
        invalid_reply = "請提供有效的客戶編號、戶名、登記電話任兩項。"
        invalid_customer_number_router = {
            "route": "direct_reply",
            "intent": "invalid_customer_number_format",
            "tool_name": None,
            "topic": pending_tool,
            "should_cancel_current_flow": False,
            "should_call_tool": False,
            "should_retrieve_knowledge": False,
            "knowledge_query": None,
            "reply": invalid_reply,
            "extracted_slots": {},
            "reason": "invalid_pending_customer_number_format",
        }
        invalid_customer_number_plan = build_plan_from_router(invalid_customer_number_router)
        invalid_customer_number_plan["skip_pending_tool_call"] = True

    router = {
        "route": "continue_current_flow" if is_troubleshooting else "unknown",
        "intent": "troubleshooting" if is_troubleshooting else "other",
        "tool_name": None,
        "topic": None,
        "should_cancel_current_flow": False,
        "should_call_tool": False,
        "should_retrieve_knowledge": False,
        "knowledge_query": None,
        "reply": "",
        "extracted_slots": {},
        "reason": "state_machine_first" if is_troubleshooting else "",
    }

    # 1. 如果使用者正在回答上一輪 clarify，先解析 clarify_context
    if invalid_customer_number_plan:
        router = invalid_customer_number_router or router
        plan = invalid_customer_number_plan

    elif active_switch_router:
        router = active_switch_router
        plan = build_plan_from_router(router)
        if router.get("route") == "clarify":
            memory["clarify_context"] = build_clarify_context(
                router,
                original_query=user_text,
            )
        if router.get("route") == "troubleshooting":
            plan = apply_troubleshooting_engine(user_text, memory, plan, llm=llm)

    # 2. 如果正在排錯，且不是 pending tool 收資料，直接進 SOP，不先跑 Router
    elif is_troubleshooting and not in_pending_mode:
        if active_flow_router:
            router = active_flow_router
            plan = build_plan_from_router(router)
        else:
            plan = build_troubleshooting_plan(memory)
        plan = apply_troubleshooting_engine(user_text, memory, plan, llm=llm)

    else:
        # A non-slot message while a tool is waiting for identity data is a
        # fresh customer turn. Clear only the pending collection state before
        # asking the LLM to classify it, so an unfinished account query cannot
        # force a later plan, fault, or knowledge question back into the same
        # tool flow.
        if in_pending_mode and not is_likely_slot_answer(user_text):
            memory = clear_pending_tool(memory)
            pending_tool = None
            in_pending_mode = False

        # 3. 非排錯狀態才跑 Router
        t0 = time.perf_counter()
        router = run_intent_router(
            user_input=user_text,
            memory=memory,
            history=contextual_history,
            llm=llm,
        )
        latency["intent_router"] = time.perf_counter() - t0

        router, validated_context_selection = resolve_model_selected_context(
            memory,
            router,
        )
        if validated_context_selection:
            memory["clarify_context"] = None

        # 如果正在 pending tool，但使用者明顯換話題，取消原本 pending tool
        if should_cancel_pending_tool(user_text, router, memory):
            memory = clear_pending_tool(memory)
            pending_tool = None
            in_pending_mode = False

            t1 = time.perf_counter()
            router = run_intent_router(
                user_input=user_text,
                memory=memory,
                history=contextual_history,
                llm=llm,
            )
            latency["intent_router_reroute"] = time.perf_counter() - t1

        elif in_pending_mode and pending_tool:
            router = {
                "route": "tool_action",
                "intent": "pending_tool_args",
                "tool_name": pending_tool,
                "topic": pending_tool,
                "should_cancel_current_flow": False,
                "should_call_tool": True,
                "should_retrieve_knowledge": False,
                "knowledge_query": None,
                "reply": "",
                "extracted_slots": {},
                "reason": "pending_tool_continue",
            }

        if router.get("should_cancel_current_flow") or router.get("route") == "switch_topic":
            memory = clear_current_flow(memory)

        plan = build_plan_from_router(router)

        if router.get("route") == "clarify":
            memory["clarify_context"] = build_clarify_context(router, original_query=user_text)

        if router.get("route") in ["troubleshooting", "continue_current_flow"]:
            plan = apply_troubleshooting_engine(user_text, memory, plan, llm=llm)

        elif router.get("intent") == "remote_input_source_help":
            plan = start_tv_input_source_troubleshooting(
                user_text,
                memory,
                plan,
            )

    # An explicit unpaid statement can never authorize a reactivation API.
    # Keep this as an action-safety invariant after the LLM has interpreted
    # the customer's billing question.
    if is_unpaid_reactivation_request(user_text):
        memory = clear_current_flow(memory)
        in_pending_mode = False
        pending_tool = None
        router = build_unpaid_reactivation_router()
        plan = build_plan_from_router(router)
    elif is_unpaid_partial_payment_question(user_text):
        memory = clear_current_flow(memory)
        in_pending_mode = False
        router = build_unpaid_partial_payment_router()
        plan = build_plan_from_router(router)

    # This post-routing safety gate also covers an old pending flow or an
    # in-progress troubleshooting state. It can only prevent an account-side
    # action; a verified image is still required before the payment API runs.
    if requires_receipt_image_evidence(user_text, router, memory):
        receipt_evidence = current_verified_receipt_image_evidence(memory, user_text)
        memory = clear_current_flow(memory)
        in_pending_mode = False
        if receipt_evidence:
            router = {
                "route": "tool_action",
                "intent": "payment_receipt_reconnection",
                "tool_name": "payment_bill_batch",
                "topic": "超商收據復線",
                "should_cancel_current_flow": False,
                "should_call_tool": True,
                "should_retrieve_knowledge": False,
                "knowledge_query": None,
                "reply": "",
                "extracted_slots": {},
                "reason": "guard_verified_receipt_image_reconnection",
            }
        else:
            router = {
                "route": "direct_reply",
                "intent": "payment_receipt_image_required",
                "tool_name": None,
                "topic": "超商收據復線",
                "should_cancel_current_flow": False,
                "should_call_tool": False,
                "should_retrieve_knowledge": False,
                "knowledge_query": None,
                "reply": (
                    RECEIPT_IMAGE_REUPLOAD_REPLY
                    if is_receipt_image_submission(user_text, memory)
                    else RECEIPT_IMAGE_REQUIRED_REPLY
                ),
                "extracted_slots": {},
                "reason": (
                    "guard_receipt_image_ocr_incomplete"
                    if is_receipt_image_submission(user_text, memory)
                    else "guard_receipt_image_evidence_required"
                ),
            }
        plan = build_plan_from_router(router)

    # 3. smalltalk 快速回覆
    if router.get("route") == "smalltalk" and not in_pending_mode:
        reply = plan.get("reply") or "您好，請問今天需要我協助什麼呢？"
        memory["decision_type"] = "smalltalk"

        latency["total"] = time.perf_counter() - t_total
        attach_llm_latency(latency, llm_trace_token)
        log_chat_latency(
            user_id=user_id,
            user_text=user_text,
            memory=memory,
            router=router,
            plan=plan,
            latency=latency,
            request_id=request_id,
        )

        if persist:
            save_session_memory(user_id, memory)
            save_chat_log(user_id, "assistant", reply)

        return {
            "status": "success",
            "ai_response": reply,
            "memory": memory,
            "router": router,
            "plan": plan,
            "latency": latency,
        }

    # unsupported_flow：不能代辦、不能收資料、不能 RAG
    if router.get("route") == "unsupported_flow" and not in_pending_mode:
        reply = plan.get("reply") or (
            "這項服務目前我無法直接代為辦理。"
            "為避免提供錯誤流程，建議您聯繫客服人員確認。"
        )

        memory["decision_type"] = "direct_reply"
        memory["last_knowledge_results"] = []

        latency["total"] = time.perf_counter() - t_total
        attach_llm_latency(latency, llm_trace_token)
        log_chat_latency(
            user_id=user_id,
            user_text=user_text,
            memory=memory,
            router=router,
            plan=plan,
            latency=latency,
            request_id=request_id,
        )

        if persist:
            save_session_memory(user_id, memory)
            save_chat_log(user_id, "assistant", reply)

        return {
            "status": "success",
            "ai_response": reply,
            "memory": memory,
            "router": router,
            "plan": plan,
            "latency": latency,
        }

    # 4. merge memory-level fields
    memory_update = {}
    if plan.get("service") is not None:
        memory_update["service"] = plan.get("service")
    if plan.get("issue_type") is not None:
        memory_update["issue_type"] = plan.get("issue_type")
    if plan.get("need_dispatch") is not None:
        memory_update["need_dispatch"] = plan.get("need_dispatch")

    if memory_update:
        memory = merge_memory_update(memory, memory_update)

    memory["decision_type"] = plan.get("decision_type")
    if plan.get("next_goal"):
        memory["next_goal"] = plan.get("next_goal")

    # 5. slot merge：只在工具流程 / pending / 報修 ready 才抽 slot
    is_clarify_resolved = router.get("reason") == "clarify_context_resolved"

    should_extract_slots = (
            not is_clarify_resolved
            and (
                    in_pending_mode
                    or plan.get("should_call_tool") is True
                    or router.get("route") == "tool_action"
                    or memory.get("known_info", {}).get("repair_ready") == "yes"
            )
    )

    if should_extract_slots:
        router_slots = plan.get("extracted_slots", {}) or {}

        fallback_tool_name = pending_tool or plan.get("tool_name")
        if fallback_tool_name == "payment_bill_batch":
            fallback_slots = {}
            router_slots = {
                key: value for key, value in router_slots.items()
                if key not in {
                    "bills",
                    "first_barcode",
                    "second_barcode",
                    "third_barcode",
                }
            }
        else:
            fallback_slots = extract_slots_from_text(
                user_text,
                memory,
                fallback_tool_name,
                llm=None,
            )

        merged_slots = dict(fallback_slots)
        for k, v in router_slots.items():
            if v not in [None, ""] and k not in merged_slots:
                merged_slots[k] = v

        memory = merge_slots_into_memory(memory, merged_slots)
        memory = normalize_pending_tool_args(memory)

    # 6. need_dispatch fallback
    if memory.get("need_dispatch") is None:
        dispatch_eval = evaluate_dispatch_need(memory)
        if dispatch_eval is not None:
            memory["need_dispatch"] = dispatch_eval

    # 7. Tool / RAG / normal reply
    channel_context = memory.get("channel_context") or {}
    with cust_api_diagnostic_context(
        request_id=request_id,
        user_id=user_id,
        channel=channel_context.get("channel") or (
            "line" if str(user_id).startswith("line:") else "web"
        ),
        company_code=memory.get("company_code"),
    ):
        reply, memory = run_tool_or_rag_flow(
            user_text=user_text,
            memory=memory,
            plan=plan,
            router=router,
            latency=latency,
            history=contextual_history,
            llm=llm,
            rag_summary_llm=rag_summary_llm,
        )
    if not (reply or "").strip():
        known = memory.get("known_info", {})
        if known.get("repair_flow_status") == "disabled" or known.get("repair_followup_active") == "yes":
            reply = build_repair_ticket_flow_disabled_reply(memory)
        else:
            reply = (
                plan.get("reply")
                or router.get("reply")
                or "系統暫時無法判讀您的需求，請稍後再試。"
            )
    reply = finalize_customer_reply(user_text, reply)
    if router.get("intent") == "contract_lookup_login_required":
        # This controlled privacy response intentionally stays verbatim. The
        # generic link appender would otherwise change the approved wording.
        reply = CONTRACT_LOOKUP_LOGIN_REQUIRED_REPLY
    else:
        reply = ensure_known_link_mentions(reply, memory)
    reply = append_promotion_referral_code(reply, router, memory, user_text=user_text)

    # 8. save
    latency["total"] = time.perf_counter() - t_total
    attach_llm_latency(latency, llm_trace_token)
    log_chat_latency(
        user_id=user_id,
        user_text=user_text,
        memory=memory,
        router=router,
        plan=plan,
        latency=latency,
        request_id=request_id,
    )

    if persist:
        save_session_memory(user_id, memory)
        save_chat_log(user_id, "assistant", reply)

    return {
        "status": "success",
        "ai_response": reply,
        "memory": memory,
        "router": router,
        "plan": plan,
        "latency": latency,
        "request_id": request_id,
    }
