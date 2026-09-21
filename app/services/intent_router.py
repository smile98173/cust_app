import json
import re
from typing import Any, Dict, List, Optional

from langchain_core.prompts import ChatPromptTemplate

from app.schemas.router import RouterDecision
from app.services.kb_answer_guard import is_definition_query
from app.services.kb_service import (
    detect_query_facets,
    detect_value_added_product_keys,
    suggest_knowledge_entity,
    value_added_query_aliases,
)
from app.services.company_profile import (
    DEFAULT_TV_CABLE,
    build_company_link,
    build_company_context,
    build_company_info_reply,
    get_company_profile,
    is_contextual_website_page_request,
    is_explicit_company_website_request,
    split_address_phone,
)
from app.services.router_catalog import (
    AMBIGUOUS_TOPIC_REPLIES,
    DEFAULT_UNKNOWN_REPLY,
    MODEL_ROUTER_UNAVAILABLE_REPLY,
    SMALLTALK_REPLIES,
    SUPPORTED_TOOLS,
    UNSUPPORTED_REPLY,
)
from app.config.settings import (
    CUSTOMER_TOOL_FLOW_DISABLED_MESSAGE,
    PROMOTION_QUERY_UNAVAILABLE_MESSAGE,
)
from app.services.router_prompt import build_intent_router_rules
from app.services.troubleshooting_engine import (
    detect_troubleshooting_type,
    is_general_signal_fault_report,
    is_direct_fault_report,
    is_fault,
    is_remote_control_issue,
    is_tv_authorization_issue,
)
from app.services.query_normalization import (
    is_technical_ip_address_query,
    normalize_text_width,
    normalize_channel_name_from_query,
)
from app.services.regional_policy import build_policy_prompt, get_policy_text
from app.services.channel_context import (
    is_service_availability_query,
    resolve_service_availability_target,
)
from app.services.receipt_image_evidence import (
    RECEIPT_IMAGE_REQUIRED_REPLY,
    RECEIPT_IMAGE_REUPLOAD_REPLY,
    current_verified_receipt_image_evidence,
    is_receipt_image_submission,
)


INTENT_ROUTER_RULES = build_intent_router_rules()


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

REPAIR_SERVICE_HOUR_TERMS = (
    "電話報修客服時間",
    "報修客服時間",
    "報修時間",
    "維修客服時間",
    "維修報修時間",
)

WEBSITE_TERMS = (
    "官網",
    "官方網站",
    "網站",
    "網址",
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
PAPER_BILL_REQUEST_REPLY = (
    "您好，請問您需要紙本帳單是有特別需求嗎？若方便，建議先使用簡訊帳單或線上信用卡繳費，快速又便利，謝謝。"
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
REPAIR_VISIT_EXPECTATION_REPLY = (
    "若您已完成預約，工程人員通常會依排程或預約時段與您聯繫。"
    "請您耐心等候；如已超過約定時段，歡迎再與我們聯繫，謝謝。"
)
BROADBAND_TERMINATION_GUIDANCE_REPLY = (
    "您好，寬頻網路退租須由客服依您的合約狀態、設備歸還及可能費用確認。\n"
    "若仍在綁約期間，提前退租可能會有違約金。\n"
    "設備部分通常需歸還數據機及實際租借的相關配件，實際項目仍以客服查詢與現場設備為準。"
)
POINTS_ACCOUNT_MERGE_REPLY = (
    "您好，不同用戶編號的哈 Point 點數是分開累積的，目前無法合併或轉移，敬請見諒，謝謝。"
)
HUMAN_HANDOFF_TRIAGE_REPLY = (
    "可以，請先告訴我遇到什麼問題，我會先協助確認；"
    "若仍需要真人客服，我會提供轉接方式。"
)
HUMAN_HANDOFF_CONFIRM_REPLY = HUMAN_HANDOFF_TRIAGE_REPLY
CARD_AUTOPAY_BINDING_STATUS_REPLY = (
    "目前我無法直接查詢您的信用卡扣繳是否已綁定成功，"
    "這需要由真人客服協助確認。\n"
    "若您是想詢問「線上刷卡繳費後是否會自動開通」，"
    "透過線上刷卡繳費、IBON及FAMIPORT繳費方式，系統會自動開通。"
)
CARD_AUTOPAY_APPLICATION_REPLY = (
    "您可以到有線電視或網路官方網站登入會員專區後，"
    "填寫您續期要扣款的信用卡資訊。"
)
CARD_AUTOPAY_DEFINITION_REPLY = (
    "綁定循環扣款是指申請信用卡或銀行帳戶自動扣款。"
    "申請完成後，後續帳款會依約定方式定期扣款；"
    "實際可綁定方式與生效時間仍以客服確認為準。"
)
WIFI_VALUE_ADDED_YOUTUBE_REPLY = (
    "WiFi 加值服務主要是提供無線網路設備與 WiFi 訊號延伸，本身不是 YouTube 或影音 App 功能。\n"
    "加值 WiFi 後，手機、平板、智慧電視或支援 YouTube 的設備可透過網路使用 YouTube；"
    "若是數位機上盒能否直接開 YouTube，仍需依機型與系統支援確認。"
)
TATUNG_TV_INSTALL_REPLY = (
    "大屯有線電視裝機可先參考基本頻道報價：\n"
    "基本收視費：月繳 550 元、季繳 1,650 元、半年繳 3,280 元、年繳 6,550 元。\n"
    "裝機費：\n"
    "月繳／季繳：裝機費 1,500 元。\n"
    "半年繳：裝機優惠價 1,000 元；若未滿半年退租，需補收優惠差額 500 元。\n"
    "年繳：裝機優惠價 600 元；若未滿 1 年退租，需補收優惠差額 900 元。\n"
    "第 1、2 台機上盒免費借用、免押金；實際仍需由客服確認服務地址、裝設條件與可約時間。"
)
PURE_NETWORK_INSTALL_KNOWLEDGE_QUERY = (
    "目前有效的純網方案總覽 請列出所有符合方案的方案名稱 服務類型 活動期間 "
    "純網方案 一般寬頻方案 網路裝機申請 單辦寬頻 單辦網路 單一網路 單純網路 "
    "速率 月繳 季繳 半年繳 年繳 裝機費 寬頻設備押金 綁約 違約金 "
    "只找純網方案，排除電視同裝。"
)
PURE_TV_INSTALL_KNOWLEDGE_QUERY = (
    "純有線電視 單辦有線電視 第四台 基本收費標準 基本收視費 "
    "月繳 季繳 半年繳 年繳 裝機費 機上盒押金 分機費"
)
TV_NETWORK_INSTALL_KNOWLEDGE_QUERY = (
    "同時申裝有線電視與寬頻網路 電視+網路方案 電視網路同裝方案 "
    "有線電視加網路 "
    "方案名稱 活動期間 速率 月繳 季繳 半年繳 年繳 裝機費 設備押金 "
    "贈品 加值服務 綁約 違約金 "
    "請回答電視+網路同裝方案內容，不要回答純網方案。"
)
PROMOTION_SERVICE_SCOPE_CLARIFY_REPLY = (
    "請問您想了解哪一類優惠方案？\n"
    "1. 有線電視＋網路\n"
    "2. 純網路\n"
    "3. 純有線電視"
)
SPEED_TEST_GUIDE_REPLY = (
    "可以這樣測試寬頻網路速度：\n"
    "1. 先將網路數據機電源關閉後重新啟動。\n"
    "2. 連上測速網站（例如 www.speedtest.net）進行測速。\n"
    "3. 測速時建議確認裝置已正常連線，並暫停其他下載或串流。\n"
    "若測速結果明顯低於您申請的頻寬，請聯繫客服協助確認。"
)
NETWORK_SCOPE_CLARIFY_REPLY = (
    "了解，您說的是網路連線不順。請問是家中所有手機、電腦都不順，還是只有單一設備？\n"
    "也請確認數據機燈號是否有紅燈或異常閃爍；確認後我再依狀況帶您排除或協助安排報修。"
)
WIFI_ROUTER_PASSWORD_REPLY = (
    "修改家中 Wi-Fi 密碼時，請先用手機或電腦連上目前的 Wi-Fi，再開啟瀏覽器輸入分享器說明書上的管理網址並登入。\n"
    "進入「Wi-Fi／無線網路／Wireless／WLAN」後，找到「安全性／Security」或 Wi-Fi 密碼欄位，"
    "輸入新密碼並按儲存／套用；修改後原本連線的裝置會斷線，請用新密碼重新連線。\n"
    "若不清楚管理網址、登入帳密或型號，請查看分享器機身貼紙或原廠使用說明書。"
)
TV_SAFE_MODE_REPLY = (
    "機上盒本身沒有「安全模式」功能；若電視畫面顯示「安全模式」，通常是電視本體的系統功能所致。\n"
    "建議先將電視電源拔除，等待約 1 分鐘後再重新插上並開機。\n"
    "若重新啟動後仍顯示「安全模式」，建議參考電視品牌提供的使用說明書，或洽詢電視原廠客服進一步確認。"
)
ALL_CHANNELS_REBOOTED_REPLY = (
    "了解，機上盒已重開機但全部頻道仍無法收視。\n"
    "這種情況需要由真人客服協助確認訊號、帳務授權或安排維修，請不要重複重開機。"
)
BILL_AMOUNT_DIFFERENCE_REPLY = (
    "您好，目前線上 AI 無法直接查詢上期繳費金額或逐項比對帳單差異。"
    "建議您登入哈TV行動客服 APP 或官網查詢帳單歷史；"
    "若仍需確認本期與上期金額不同的原因，請由真人客服協助核對您的帳務資訊。"
)
BASIC_CHANNEL_TABLE_REPLY = (
    "基本頻道就是有線電視頻道。您可以到系統台官網的頻道查詢頁面查看最新頻道表；"
    "實際可收視頻道仍以您所在地區與系統台公告為準。"
)
BASIC_VS_DIGITAL_CHANNEL_REPLY = (
    "基本頻道是申裝有線電視後可收看的主要頻道，頻道內容與號碼依所在地區及系統台公告為準。\n"
    "數位頻道通常是額外的數位付費套餐或加值頻道，需要另外訂購或符合方案內容才會授權收看。\n"
    "數位套餐的詳細內容及費用，歡迎至官網查詢參考。"
)
NETWORK_LINE_OWNERSHIP_REPLY = (
    "一般家用寬頻會以每戶獨立申裝、獨立管理為主，不會把多戶帳務合併成同一個一般用戶方案。\n"
    "但若是房東或學舍統一申請的學舍／套房方案，可能會由房東統一管理後提供住戶使用；"
    "實際是獨立線路或區域共用，仍要以您申裝的方案與現場設備配置為準。"
)
APP_CONVENIENCE_BARCODE_REPLY = (
    "哈TV行動客服 APP 可依帳單與繳費方式提供繳費資訊。若您的帳單支援超商條碼，"
    "登入 APP 後可到「待繳帳單」查看或產生可繳費的條碼。\n"
    "若您目前使用的是簡訊帳單，請直接開啟收到的簡訊帳單連結，依頁面指示繳費即可，"
    "不一定需要另外在 APP 產生超商條碼。"
)
CONVENIENCE_STORE_PAYMENT_FAILED_REPLY = (
    "若目前無法在便利商店繳費，可能是帳單條碼過期、金額或帳務狀態需重新確認。\n"
    "您可以改用官網線上繳費、哈TV行動客服 APP、臨櫃繳費，或請真人客服協助補發簡訊帳單。"
    "若要補發簡訊帳單，仍需提供戶名與登記電話供核對。"
)
OUTBOUND_CALL_LOOKUP_REPLY = (
    "目前線上 AI 無法查詢是否有客服人員外撥給您，也無法確認來電原因。\n"
    "若您想確認剛剛的來電是否為本公司客服，建議由真人客服協助核對通話紀錄與通知事項。"
)
ONLINE_PAYMENT_APP_PASSWORD_REPLY = (
    "線上繳費登入時，請先依登入頁面確認帳號資訊。"
    "若忘記密碼，請使用登入頁的「忘記密碼」依畫面指示重設；若要修改密碼，請登入後依帳戶設定指示變更。"
    "若頁面無法完成操作，請由客服核對帳號資料後協助處理。"
)
VIRTUAL_HOSTING_UNSUPPORTED_REPLY = (
    "您好，目前本公司未提供「虛擬主機」服務，抱歉無法協助辦理。"
)
IDENTITY_DOCUMENT_UPLOAD_REPLY = (
    "您好，目前此線上服務無法代收或上傳身分證件。\n"
    "若您需要補件或辦理相關申請，為保障個資安全，請下載哈TV行動客服 APP，"
    "並透過 APP 進行雙證件上傳。"
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

VAGUE_NETWORK_TROUBLESHOOTING_TERMS = (
    "網路排除",
    "網路故障排除",
    "寬頻排除",
    "寬頻故障排除",
)

NEW_INSTALL_TERMS = (
    "裝機申請",
    "網路裝機",
    "裝網路",
    "安裝網路",
    "申裝網路",
    "想裝網路",
    "我要裝網路",
    "想安裝網路",
    "我要安裝網路",
    "新申辦",
    "申裝",
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

ONE_YEAR_NETWORK_CONTRACT_TERMS = (
    "只綁一年",
    "綁一年",
    "一年約",
    "一年合約",
    "合約一年",
    "12個月",
    "十二個月",
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

UPGRADE_LINE_TERMS = (
    "升級",
    "升速",
)

LINE_CHANGE_TERMS = (
    "改線",
    "更改線路",
    "換線",
    "線路",
)

RELOCATION_TERMS = (
    "搬家",
    "移機",
    "搬遷",
    "搬過去",
    "搬到",
)

RELOCATION_FEE_TERMS = (
    "費用",
    "多少錢",
    "多少",
    "收費",
    "價格",
    "價錢",
)

RELOCATION_NETWORK_ONLY_TERMS = (
    "只移網路",
    "只辦理網路",
    "只移寬頻",
    "只搬網路",
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

BROADBAND_PRICE_TERMS = (
    "寬頻費",
    "網路費",
    "上網費",
    "寬頻費用",
    "網路費用",
    "上網費用",
    "寬頻多少錢",
    "網路多少錢",
    "上網多少錢",
    "最便宜的上網",
    "最便宜上網",
    "最便宜網路",
    "網路最便宜",
    "寬頻最便宜",
    "只要網路",
    "單辦網路",
    "單裝網路",
)

BROADBAND_PRICE_EXCLUDE_TERMS = (
    "移機",
    "搬家",
    "退租",
    "拆機",
    "停用",
    "欠費",
    "欠繳",
    "帳單",
    "發票",
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

PRICE_COMPLAINT_REPLY = (
    "您好，了解您對費用的疑問。若您願意，我們可協助轉由文字客服專人為您確認目前方案及適用優惠，謝謝。"
)

PERSONAL_CONTACT_PHONE_CHANGE_REPLY = (
    "您好，聯絡電話變更涉及個人資料，線上 AI 無法直接修改。"
    "請由真人客服協助確認身分資料後辦理變更，謝謝您。"
)

PAYMENT_NOT_POSTED_REPLY = (
    "您好，門市或刷卡繳費後，帳務更新可能需要作業時間，通常不一定會即時沖帳。\n\n"
    "請先保留繳費收據或交易明細，以便後續核對。\n\n"
    "若需確認是否已入帳，建議提供繳費收據資訊，由真人客服協助查詢。"
)

PAST_PAYMENT_RECORD_REPLY = "若需查詢已繳費明細或入帳紀錄，可至行動客服 APP 或官網查閱。很高興為您服務，謝謝。"

NEXT_BILL_AFTER_NO_UNPAID_REPLY = "您好，目前系統可協助查詢本期待繳帳單。待下期帳單產生後，請留意相關通知，謝謝。"

UNSUPPORTED_BILL_DETAIL_REPLY = (
    "您好，目前系統可協助查詢本期待繳帳單。"
    "若需查看帳單期間、繳費起訖日、已繳費明細或入帳紀錄，"
    "可至行動客服 APP 或官網查閱，謝謝。"
)

STORE_PAYMENT_STILL_BILLED_REPLY = (
    "您好，超商繳費入帳可能需要作業時間，通常不一定會即時更新。\n\n"
    "請先保留繳費收據或交易明細，以便後續核對。\n\n"
    "若需確認是否已入帳，建議提供繳費收據資訊，由真人客服協助查詢。"
)

TV_600_FEE_CLARIFY_REPLY = (
    "一般有線電視基本收視費目前是月繳 $540。"
    "若您看到或聽到「一個月 $600」，通常可能是新裝機贈送的聯網機上盒體驗或 LINE TV 體驗到期後恢復原價收費。"
    "若續期後不使用相關體驗或加值服務，可由客服協助確認是否可取消，並恢復一般有線電視收費。"
)

HATV_PLUS_YOUTUBE_REPLY = (
    "您好，目前公司提供的機上盒分為聯網型及非聯網型。"
    "如有聯網需求，可加購每月 60 元換裝聯網型機上盒，聯網型機上盒可使用 YouTube、LINE TV 等數位串流功能。\n"
    "實際是否符合申辦及換裝條件，需由客服依您的地址、合約狀態及適用方案進行確認，謝謝您。"
)

LINE_TV_OPENING_REPLY = (
    "要訂購或開通 LINE TV，可先確認家中是否已安裝雙模機／聯網機上盒。\n"
    "已安裝者：可用遙控器進入 VIP會員 → 優惠專區 → 加值服務 → LINE TV 進行加購。\n"
    "尚未安裝聯網機上盒者：請透過 LINE 搜尋並加入「台數科」官方帳號，發送訊息請客服協助報價安裝。\n"
    "若已購買 LINE TV：請先在電視或雙模機下載並開啟 LINE TV 電視版 App，"
    "再用手機或平板的 LINE TV App 進入「個人」頁，點選右上角掃描圖示，"
    "掃描電視上的 QR code，或手動輸入電視顯示的 6 位代碼後登入觀看。"
)

STOP_WATCHING_CLARIFY_REPLY = (
    "了解，請問您是想辦理退租／終止服務，還是想暫停收看一段時間？\n"
    "若是退租或提前終止合約，可能會有違約金或設備歸還等事項，需由客服依您的合約資料確認。"
)

ROUTER_REPLACEMENT_CLARIFY_REPLY = (
    "請問您是更換分享器後無法上網，還是分享器故障想更換設備？\n"
    "若是更換分享器後無法上網，一般將設備接上網路數據機後，系統會自動註冊，重啟電腦即可連線。"
    "若未自動註冊，可至台基科官網 https://www.tinp.net.tw/ → 會員專區 → 電腦網卡更換註冊，"
    "依頁面提示完成登入或驗證後再重啟電腦。\n"
    "若是分享器故障要更換，通常分享器為客戶自備；如有租用公司 WiFi 服務，需由客服確認申裝方案。"
)

WCTV_NEW_NETWORK_EQUIPMENT_REPLY = (
    "一般來說，將新設備接上網路數據機後，系統會自動把設備註冊到客戶端資料庫；"
    "請先重新啟動電腦後再確認是否可連線。\n\n"
    "若仍未自動註冊，可至台基科官網 https://www.tinp.net.tw/ → 會員專區 →「電腦網卡更換註冊」，"
    "依頁面提示完成登入或驗證後，再重新啟動電腦即可。"
)

DS_LIGHT_BLINKING_REPLY = (
    "DS 燈閃爍通常代表數據機正在同步下行訊號，不一定是正常完成連線狀態。"
    "請先將數據機電源拔掉約 10 秒後重新插上，等待 3 到 5 分鐘。"
    "若 DS 燈仍持續閃爍或無法上網，請由客服協助確認線路或安排檢修。"
)

GENERAL_CHANNEL_E004_REPLY = (
    "若一般基本頻道也顯示 E004、授權到期或未授權，請先確認收視費是否已繳清。\n"
    "若尚未繳費，我可以先協助您進行電視暫時復線；請問需要我現在協助嗎？"
)

ONLINE_PAYMENT_DONE_REPLY = (
    "如您已透過官網或哈TV行動客服 APP 完成線上繳費，系統會自動開通。"
    "若仍無法使用，請先重啟數據機或機上盒後再確認；如仍未恢復，請由客服協助確認入帳與授權狀態。"
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

TV_NO_PROGRAM_CLARIFY_REPLY = (
    "了解，想先確認目前電視的狀況：是完全沒有畫面、只有部分頻道無法收視，"
    "還是畫面有顯示錯誤代碼？請告訴我畫面情況或錯誤代碼，我再帶您處理。"
)

HALF_YEAR_ONLINE_PAYMENT_REPLY = (
    "半年繳可先透過以下方式繳費：\n"
    "1. 官網線上繳費／信用卡刷卡：至官方網站「線上繳費專區」，輸入用戶編號與密碼後依指示繳費。\n"
    "2. APP 繳費：下載哈TV行動客服 APP，註冊或登入後依指示繳費。\n"
    "但線上客服無法直接協助更改繳別；若您要改成半年繳，需由客服確認帳務與可變更狀態。"
)

MEMBER_REGISTRATION_REPLY = (
    "申請本公司電視或網路服務後，系統即會產生一組用戶編號，無須另外註冊會員。"
    "如需查詢用戶編號，可查看每月帳單，通常會列於帳單上；若仍查不到，請由客服協助核對。"
)

SET_TOP_BOX_RELOCATION_PAYMENT_REPLY = (
    "機上盒移機流程如下：\n"
    "申請方式：請聯繫客服協助登記移機。\n"
    "確認事項：客服會先確認新地址或移機位置是否有線路可安裝。\n"
    "費用：室內移機 500 元；室外移機 800 元。工程施工完畢後現場收取現金。\n"
    "後續安排：確認可移機後，客服會協助處理移機手續與安排作業。"
)

WIRELESS_NETWORK_CLARIFY_REPLY = (
    "請問您是要新申請寬頻網路，還是已經有寬頻網路、想加裝 WiFi 分享器來使用無線功能？"
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

WCTV_FIXED_IP_BINDING_REPLY = (
    "您可以使用要綁定固定 IP 的設備前往台基科官網 https://www.tinp.net.tw/，"
    "依序選擇「會員登入」→「綁定固定 IP」，輸入帳號與密碼後，依畫面指示完成綁定。"
)

DHCP_NOT_PPPOE_REPLY = (
    "您好，本公司網路連線採用 DHCP 自動取得 IP，不使用 PPPoE 撥號方式，"
    "因此不需要輸入 PPPoE 帳號及密碼。請將網路連線設定為「自動取得 IP」即可。"
)

WIFI_ROUTER_SETUP_REPLY = (
    "您好，Wi-Fi 機器的設定方式會依分享器型號而有所不同，"
    "建議依您使用的分享器型號參考設定流程或使用說明書操作。"
)

PREPAY_LOOKUP_REPLY = (
    "預繳前建議先確認目前是否有待繳帳單；登入會員會依 API 帶入的客戶資料查詢，"
    "若仍需人工核對，請提供戶名與聯絡電話。\n"
    "如有待繳帳單，會回覆目前帳單金額；如無待繳帳單，則會回覆目前無費用需繳納。"
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

CHANNEL_QUERY_TERMS = (
    "第幾台",
    "哪個頻道",
    "頻道位置",
    "在哪一台",
    "在幾台",
    "哪一台",
    "哪台",
    "幾台",
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

ADVANCED_NETWORK_SETTING_TERMS = (
    "橋接",
    "橋接器",
    "路由器",
    "zyxel",
    "Zyxel",
)

PASSWORD_TERMS = (
    "忘記密碼",
    "密碼忘記",
)

REMOTE_CONTROL_TERMS = (
    "遙控器",
    "遙控",
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

CARD_PAYMENT_METHOD_REPLY = (
    "線上刷卡／信用卡繳費可用以下方式：\n"
    "1. 線上繳費：至官方網站「線上繳費專區」，輸入用戶編號與密碼後依指示進行信用卡繳費。\n"
    "2. APP 繳費：下載哈TV行動客服 APP，註冊或登入後依指示進行信用卡繳費。"
)

TRIPLE_PLAY_BILL_ITEM_REPLY = (
    "三合一方案通常是指寬頻網路及電視服務，並提供數位電視盒供收視使用。\n"
    "若是帳單上的「三合一方案」項目，實際內容仍需依您的帳務資料由客服確認。"
)

SMS_BILL_REGISTERED_PHONE_REPLY = (
    "簡訊帳單只能寄送到登記電話，無法改寄或指定寄送到其他電話。\n"
    "若要補發簡訊帳單，請提供戶名與登記電話供核對；"
    "若需變更登記電話，需由真人客服協助確認。"
)

ONLINE_PAYMENT_ACTIVATION_REPLY = (
    "線上繳費方式：\n"
    "1. 官方網站：至「線上繳費專區」，輸入用戶編號與密碼後依指示完成繳費。\n"
    "2. 哈TV行動客服 APP：下載 APP 並註冊或登入後，依指示完成線上刷卡繳費。\n"
    "貼心提醒，透過線上刷卡繳費、IBON及FAMIPORT繳費方式，系統會自動開通喔；"
    "若仍無法使用，請重啟數據機或機上盒後再確認。"
)

TV_AUTHORIZATION_PAYMENT_REPLY = (
    "畫面顯示「未授權」時，請先確認目前停在哪一個頻道。\n"
    "若為 200 頻道以上，可能是付費頻道、需另行訂閱或尚未加購；"
    "請先按頻道向下鍵，切換至 200 頻道以下的一般基本頻道確認。\n"
    "若一般基本頻道也顯示 E004、授權到期或未授權，再協助確認收視費與授權狀態。"
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

ADDRESS_CONTRACT_LOOKUP_REPLY = (
    "若您詢問的地址與目前登入帳號不一定相同，不能直接用登入客編回覆合約內容。\n"
    "請由真人客服依姓名、聯絡電話與服務地址逐筆核對後，再確認該地址的合約資訊。"
)

PERSONAL_BILLING_ADDRESS_REPLY = (
    "線上客服無法直接提供您的個人帳單寄送地址。"
    "如需查詢或變更帳單寄送地址，請由真人客服協助核對身分後確認。"
)
SERVICE_TERMINATION_WITH_CONTRACT_REPLY = (
    "若您要提前終止合約或辦理退租，辦理流程如下：\n"
    "1. 向客服提出退租申請。\n"
    "2. 客服核對目前的服務項目、合約狀態與退租資格。\n"
    "3. 依核對結果告知可辦理時間及後續安排。\n"
    "仍在綁約期間提前終止，可能產生違約金；實際是否可辦理、合約剩餘期間與相關費用，"
    "須以客服查詢的合約資料為準。"
)
ONLINE_PAYMENT_RECEIPT_REPLY = (
    "使用 APP 或官網線上繳費後，通常不會另外寄送實體收據到府。"
    "費用入帳後，發票號碼會於營業日以簡訊通知用戶。\n"
    "您也可自行查詢：\n"
    "1. 官網：客戶服務 → 發票查詢，依頁面提示登入或驗證後即可查詢。\n"
    "2. 哈TV行動客服 APP：註冊後登入帳密 → 歷史帳單即可查詢。\n"
    "若需要申請發票號碼載具歸戶，可到公司官網的客戶服務 → 發票查詢，"
    "輸入用戶帳號密碼後點選「用戶歸戶」，並連結財政部網站進行歸戶。"
)
MOBILE_CASTING_REPLY = (
    "手機投影到電視需視手機、電視型號及使用設備是否支援投影功能而定。"
    "一般可透過手機內建的螢幕鏡像、投放或 AirPlay 等功能，"
    "將畫面投影至支援的電視或相關設備；實際操作方式請依手機與電視設備說明為準。"
)
LINE_TV_OPENING_QUERY = (
    "LINE TV 開通 訂購 雙模機 聯網機上盒 VIP會員 優惠專區 加值服務 "
    "LINE TV 電視版 App QR code 掃描 6位代碼 登入"
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
LINE_TV_TOPIC_CLARIFY_REPLY = (
    "請問您想詢問 LINE TV 的哪一種問題？例如：如何在機上盒開通／登入、無法收看、費用，"
    "或是 LINE TV 能不能在電視上看。"
)
STB_TUTORIAL_STUCK_REPLY = (
    "畫面一直卡在機上盒教學時，請先確認遙控器是否可正常操作：按鍵時遙控器燈號是否會亮，"
    "也可先更換電池再試。\n"
    "若遙控器正常，請嘗試將機上盒恢復原廠預設，完成後按頻道上／下鍵確認是否可進入一般收視畫面。"
    "若仍卡住，再將機上盒電源拔掉約 10 秒後重新插上，等待 2 到 3 分鐘後確認。"
)
ADDRESS_SERVICE_PLAN_LOOKUP_REPLY = (
    "無法依地址查詢您目前申請的網路速率或方案。\n"
    "若您是登入會員，系統會依 API 帶入的客戶資料協助查詢；若仍需人工核對，請提供戶名與聯絡電話。"
)
CONTRACT_CHANGE_REPLY = (
    "可以詢問換約或轉換方案，但能不能轉、是否需要補差額或是否會有違約金，"
    "都要依您目前合約狀態、剩餘期間與想改的方案確認。\n"
    "若您確定想換方案，請告訴我想改成哪一個方案，後續需由真人客服協助查詢並確認可辦理條件。"
)
GENERIC_FEE_LOOKUP_CLARIFY_REPLY = (
    "請問您想查的是哪一類費用：有線電視月費、寬頻網路方案費用、加值服務費用，"
    "還是目前帳單／合約上的費用？\n"
    "若是查您自己的帳單或目前方案，登入會員會依 API 帶入的客戶資料查詢；若仍需人工核對，請提供戶名與聯絡電話。"
)
SERVICE_SUSPENSION_REPLY = (
    "若您說的「停機」是暫停服務／暫停收看，通常需由登記人辦理，並由客服確認目前合約、設備與費用狀態。\n"
    "暫停收視通常需保留至少 1 個月以上月租；3 個月內復機一般免收復機費，超過 3 個月復機費為 200 元。"
    "辦理方式以臨櫃為主，登記人需帶雙證件與印章；代辦則需雙方雙證件與印章。\n"
    "若您其實是要退租／終止服務，流程與費用會不同，需要另外由客服確認。"
)
TV_ONLY_PROMOTION_REPLY = (
    "若只申裝有線電視，會以有線電視基本收視費、裝機費與所在地區公告方案為主，"
    "不會套用寬頻同裝優惠。\n"
    "若您想確認目前單辦有線電視的費用或優惠，請提供服務地區，我再協助查詢對應系統台資訊。"
)
PURE_TV_INSTALL_REPLY = (
    "可以，若只申裝有線電視，客服需依實際裝機地址確認可安裝狀況、基本收視費、裝機費與機上盒相關費用。\n"
    "請提供服務地址、是否新裝，以及需要幾台電視收看，後續可由真人客服協助確認可辦內容與費用。"
)
NEXT_TIER_PLAN_FEE_REPLY = (
    "若是想升級到再高一階的方案，可以先參考目前主推寬頻或電視加網路方案；"
    "但實際月費差額、是否能直接轉換、合約是否需要累加或重簽，都要依您目前合約與想升級的方案確認。\n"
    "若您告訴我想升級到的速率或方案名稱，後續需由真人客服查詢後確認可辦理條件與實際費用。"
)

OVERDUE_DISCONNECTION_REPLY = (
    "若因忘記繳費而被斷訊，請先完成繳費；可透過官方網站線上繳費專區、"
    "哈TV行動客服 APP、超商條碼或臨櫃繳款。\n"
    "若沒有帳單或條碼，可請真人客服協助補發簡訊帳單或核對應繳金額。\n"
    "入帳後服務恢復可能需要一段作業時間；請將數據機或機上盒關機約 10 秒再重新開機確認是否已復線。\n"
    "若已繳費仍未開通，請保留繳費收據或交易明細，由真人客服協助確認入帳與復線狀態。"
)
REFUND_CALCULATION_REPLY = (
    "目前系統無法直接查詢或計算解約退費金額。\n"
    "是否可退費及實際金額，需依您的服務項目、合約狀態、繳別、已使用期間與帳務狀態，"
    "由真人客服協助確認。\n"
    "請先保留繳費收據或交易明細，以便後續核對。"
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

BROADBAND_UNLIMITED_REPLY = (
    "您好，您目前申辦的是非流量制寬頻方案，沒有流量使用上限，"
    "可不限流量正常使用，請您放心。"
)

LOW_INCOME_500M_YEAR_REPLY = (
    "【方案名稱】\n"
    "低收入戶優惠方案\n"
    "【優惠內容】\n"
    "500M 寬頻：一般寬頻 500M/500M 年繳 $12,000，低收入戶寬頻連線費一律半價，"
    "收半年繳可使用一年，因此一年寬頻費用為 $6,000。\n"
    "裝機費：0 元。\n"
    "【申請方式】\n"
    "需本人至門市臨櫃辦理，並提供有效低收入戶證明。\n"
    "【限制條件】\n"
    "每年須重新申請；次年若未取得低收入戶證明，會恢復原價。"
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

REMOTE_PRICE_TERMS = (
    "遙控器多少錢",
    "遙控器價格",
    "遙控器費用",
)

APPLE_PAY_TERMS = (
    "apple pay",
    "APPLE PAY",
    "Apple Pay",
)

WIFI_AP_SETTING_TERMS = (
    "無線ap",
    "無線AP",
    "wifi ap",
    "WIFI AP",
    "分享器設定",
    "wifi分享器設定",
    "WIFI分享器設定",
)

WIFI_ROUTER_SALE_TERMS = (
    "賣wifi分享器",
    "賣WIFI分享器",
    "賣 WiFi 分享器",
    "賣 WIFI 分享器",
    "賣分享器",
    "買wifi分享器",
    "買WIFI分享器",
    "買分享器",
    "公司有在賣",
)

ENGINEER_WEEKEND_TERMS = (
    "工程師假日",
    "工程假日",
    "假日有上班",
    "假日可以維修",
    "假日可以裝機",
    "假日有空可以約裝機",
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

TV_PAID_CANNOT_WATCH_TERMS = (
    "已經繳費了",
    "已經繳費完成",
    "已繳費",
    "已繳費完成",
    "繳費完成",
    "繳費了",
    "繳費成功",
    "付款成功",
    "繳了",
    "付費了",
)

TV_CANNOT_WATCH_TERMS = (
    "不能看電視",
    "電視還不能看",
    "電視不能看",
    "還是不能看",
    "無法收看",
    "不能收看",
    "無法看電視",
    "看不了電視",
)

NON_PROMOTED_1G_TERMS = (
    "1G",
    "1g",
    "1 G",
    "1 g",
    "1G/1G",
    "1g/1g",
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

TV_BLURRY_TERMS = (
    "電視很不清",
    "電視不清",
    "畫面不清",
    "畫質不清",
    "畫面模糊",
    "馬賽克",
)

TV_LAG_TERMS = (
    "有畫面但是會lag",
    "有畫面但是會LAG",
    "有畫面會lag",
    "有畫面會LAG",
    "畫面會lag",
    "畫面會LAG",
    "電視會lag",
    "電視會LAG",
)

REMOTE_POWER_LEARN_TERMS = (
    "拷貝電源",
    "學習電源",
    "複製電源",
    "遙控器拷貝",
    "遙控器學習",
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

TV_TROUBLESHOOTING_NOT_RECONNECTION_TERMS = (
    "電視故障",
    "第四台故障",
    "電視不能用",
    "第四台不能用",
    "電視跟網路都不能用",
    "電視顯示未授權",
    "授權到期",
    "未授權",
    "沒有授權",
    "無授權",
    "遙控器",
    "遙控",
    "不能轉台",
)

RECONNECTION_INTENT_TERMS = (
    "復線",
    "恢復",
    "開通",
    "已繳",
    "繳費",
    "欠費",
    "斷訊",
    "停訊",
)

SIGNAL_SOURCE_TERMS = (
    "訊號源",
    "輸入源",
    "input",
    "Input",
    "INPUT",
    "source",
    "Source",
    "SOURCE",
    "hdmi",
    "HDMI",
)

CANCEL_REPAIR_TERMS = (
    "取消報修",
    "取消派工",
    "取消工單",
    "取消維修",
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


def detect_value_added_product_knowledge_query(text: str) -> Optional[Dict[str, Any]]:
    """Route add-on product catalog questions to RAG before fault detection."""
    value = normalize_text_width(text or "").strip()
    compact = value.replace(" ", "").replace("　", "")
    product_keys = detect_value_added_product_keys(value)
    if not compact or not product_keys:
        return None

    has_info_intent = any(term in compact for term in VALUE_ADDED_PRODUCT_INFO_TERMS)
    if not has_info_intent:
        return None

    has_fault = any(term.lower() in compact.lower() for term in VALUE_ADDED_PRODUCT_FAULT_TERMS)
    has_price_intent = any(term in compact for term in VALUE_ADDED_PRODUCT_PRICE_TERMS)
    if has_fault and not has_price_intent:
        return None

    aliases = value_added_query_aliases(value)
    alias_query = " ".join(dict.fromkeys(aliases))
    knowledge_query = (
        f"{value} {alias_query} 加值服務 單品銷售 月租 半年繳 年繳 "
        "費用 申辦方式 限制條件"
    ).strip()
    return build_knowledge_query_decision(
        intent="value_added_product_query",
        topic="加值產品與服務",
        knowledge_query=knowledge_query,
        reason="value_added_product_knowledge_rule",
    )


def detect_equipment_purchase_knowledge_query(text: str) -> Optional[Dict[str, Any]]:
    """Keep an equipment purchase/price question out of the fault flow."""
    value = normalize_text_width(text or "").strip()
    compact = value.replace(" ", "").replace("　", "")
    if not compact:
        return None

    has_subject = any(term in compact for term in ("遙控器", "語音遙控器", "機上盒", "數位機上盒"))
    has_purchase = any(term in compact for term in ("買", "購買", "換一支", "更換", "申購", "加購"))
    has_price = any(term in compact for term in ("多少錢", "多少", "價格", "價錢", "費用", "收費"))
    if not (has_subject and has_purchase and has_price):
        return None

    return build_knowledge_query_decision(
        intent="equipment_purchase_price_query",
        topic="設備購買與費用",
        knowledge_query=f"{value} 設備購買 售價 每支費用 申購方式",
        reason="equipment_purchase_knowledge_rule",
    )


def detect_service_device_limit_knowledge_query(text: str) -> Optional[Dict[str, Any]]:
    """Distinguish service device limits from television channel-number queries."""
    value = normalize_text_width(text or "").strip()
    if "service_device_limit" not in detect_query_facets(value):
        return None

    return build_knowledge_query_decision(
        intent="service_device_limit_query",
        topic="加值服務登入裝置限制",
        knowledge_query=(
            f"{value} LINE TV 登入裝置數量 裝置上限 同時觀看限制 使用規則"
        ),
        reason="service_device_limit_knowledge_rule",
    )


def detect_knowledge_entity_confirmation(text: str) -> Optional[Dict[str, Any]]:
    """Ask before using a plausible but low-confidence indexed service name."""
    value = normalize_text_width(text or "").strip()
    compact = value.replace(" ", "").replace("　", "")
    if not compact:
        return None
    if is_payment_method_query(value):
        return None

    suggestion = suggest_knowledge_entity(value)
    if not suggestion:
        return None

    canonical_name = str(suggestion.get("name") or "").strip()
    if not canonical_name:
        return None

    has_info_intent = any(term in compact for term in VALUE_ADDED_PRODUCT_INFO_TERMS)
    is_short_entity_query = len(compact) <= len(canonical_name) + 4
    if not has_info_intent and not is_short_entity_query:
        return None

    aliases = [canonical_name, *(suggestion.get("aliases") or [])]
    alias_query = " ".join(dict.fromkeys(str(alias).strip() for alias in aliases if str(alias).strip()))
    decision = build_clarify_decision(
        intent="knowledge_entity_confirmation",
        topic="加值產品與服務",
        reply=f"請問您指的是「{canonical_name}」服務嗎？",
        reason="knowledge_entity_confirmation_required",
    )
    decision["entity_confirmation"] = {
        "name": canonical_name,
        "original_query": value,
        "knowledge_query": (
            f"{canonical_name} {alias_query} 加值服務 單品銷售 月租 半年繳 年繳 "
            "費用 申辦方式 限制條件"
        ).strip(),
    }
    return decision


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


def detect_service_availability_query(
    text: str,
    memory: Optional[Dict[str, Any]] = None,
) -> Optional[Dict[str, Any]]:
    text = (text or "").strip()
    memory = memory or {}
    known = memory.get("known_info", {})

    if not text:
        return None

    if is_service_availability_query(text):
        return build_direct_reply_decision(
            intent="service_availability",
            topic="服務範圍申辦查詢",
            reply=build_service_availability_reply(text, memory),
            reason="direct_service_availability_rule",
        )

    return None


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


def detect_mabow_query(
    text: str,
    memory: Optional[Dict[str, Any]] = None,
) -> Optional[Dict[str, Any]]:
    text = (text or "").strip()
    memory = memory or {}
    known = memory.get("known_info", {})

    if not text:
        return None

    if memory.get("pending_tool") or known.get("troubleshooting_started") == "yes":
        return None

    if any(term in text for term in MABOW_TERMS):
        return build_mabow_knowledge_decision(text, "mabow_knowledge_rule")

    return None


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
    remembered_topic = str(memory.get("last_campaign_topic") or "")
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


def detect_safe_direct_reply(
    text: str,
    memory: Optional[Dict[str, Any]] = None,
) -> Optional[Dict[str, Any]]:
    text = (text or "").strip()
    memory = memory or {}
    known = memory.get("known_info", {})

    if not text:
        return None

    compact = text.replace(" ", "").replace("　", "")
    if compact in {"2", "２", "第二個", "第2個", "選2"} and (
        known.get("last_value_added_topic") == "WiFi 加值服務"
        or memory.get("last_value_added_topic") == "WiFi 加值服務"
    ):
        return build_direct_reply_decision(
            intent="wifi_value_added_service",
            topic="WiFi 加值服務",
            reply=WIFI_VALUE_ADDED_SERVICE_REPLY,
            reason="direct_remembered_value_added_option_2_wifi_rule",
        )

    if is_virtual_hosting_query(text):
        return build_direct_reply_decision(
            intent="unsupported_virtual_hosting_service",
            topic="虛擬主機",
            reply=VIRTUAL_HOSTING_UNSUPPORTED_REPLY,
            reason="direct_virtual_hosting_unsupported_rule",
        )

    if "pppoe" in compact.lower():
        return build_direct_reply_decision(
            intent="dhcp_not_pppoe",
            topic="PPPoE 網路設定",
            reply=DHCP_NOT_PPPOE_REPLY,
            reason="direct_dhcp_not_pppoe_rule",
        )

    if (
        any(term in compact.lower() for term in ("網際網路連線類型", "網際網路連線方式", "網路連線類型", "網路連線方式", "isp連線"))
    ):
        return build_direct_reply_decision(
            intent="dhcp_connection_type",
            topic="網際網路連線類型",
            reply="本公司網際網路連線採用 DHCP 自動取得 IP，由系統自動動態發放 IP 位址，客戶端無需手動設定固定 IP。",
            reason="direct_dhcp_connection_type_rule",
        )

    if (
        any(term in compact.lower() for term in ("wifi", "wi-fi", "分享器", "路由器"))
        and any(term in compact for term in ("重新設定", "重設", "設定"))
    ):
        return build_direct_reply_decision(
            intent="wifi_router_setup_guidance",
            topic="Wi-Fi 分享器設定",
            reply=WIFI_ROUTER_SETUP_REPLY,
            reason="direct_wifi_router_setup_guidance_rule",
        )

    if (
        memory.get("company_code") == "wctv"
        and "固定ip" in compact.lower()
        and any(term in compact for term in ("綁定", "設定", "怎麼", "如何", "步驟", "方式"))
    ):
        return build_direct_reply_decision(
            intent="wctv_fixed_ip_binding",
            topic="固定 IP 綁定",
            reply=WCTV_FIXED_IP_BINDING_REPLY,
            reason="direct_wctv_fixed_ip_binding_rule",
        )

    if is_network_line_ownership_query(text):
        return build_direct_reply_decision(
            intent="network_line_ownership",
            topic="網路獨立或共用",
            reply=NETWORK_LINE_OWNERSHIP_REPLY,
            reason="direct_network_line_ownership_rule",
        )

    if is_app_convenience_store_barcode_query(text):
        return build_direct_reply_decision(
            intent="app_convenience_store_barcode",
            topic="APP 超商繳費條碼",
            reply=APP_CONVENIENCE_BARCODE_REPLY,
            reason="direct_app_convenience_store_barcode_rule",
        )

    if is_convenience_store_payment_failed_query(text):
        return build_direct_reply_decision(
            intent="convenience_store_payment_failed",
            topic="便利商店繳費失敗",
            reply=CONVENIENCE_STORE_PAYMENT_FAILED_REPLY,
            reason="direct_convenience_store_payment_failed_rule",
        )

    if is_basic_vs_digital_channel_query(text):
        return build_direct_reply_decision(
            intent="basic_vs_digital_channel",
            topic="基本頻道與數位頻道",
            reply=BASIC_VS_DIGITAL_CHANNEL_REPLY,
            reason="direct_basic_vs_digital_channel_rule",
        )

    if is_outbound_call_lookup_query(text):
        return build_direct_reply_decision(
            intent="outbound_call_lookup_handoff",
            topic="客服來電確認",
            reply=OUTBOUND_CALL_LOOKUP_REPLY,
            reason="direct_outbound_call_lookup_rule",
        )

    if is_bare_line_tv_topic_query(text):
        return build_clarify_decision(
            intent="line_tv_topic_clarification",
            topic="LINE TV",
            reply=LINE_TV_TOPIC_CLARIFY_REPLY,
            reason="direct_line_tv_topic_clarification_rule",
        )

    if is_stb_tutorial_stuck_query(text):
        return build_direct_reply_decision(
            intent="stb_tutorial_stuck",
            topic="機上盒教學畫面卡住",
            reply=STB_TUTORIAL_STUCK_REPLY,
            reason="direct_stb_tutorial_stuck_rule",
        )

    if is_address_service_plan_lookup_query(text):
        return build_direct_reply_decision(
            intent="address_service_plan_lookup_handoff",
            topic="依地址查詢網路速率",
            reply=ADDRESS_SERVICE_PLAN_LOOKUP_REPLY,
            reason="direct_address_service_plan_lookup_rule",
        )

    if is_contract_change_or_plan_switch_query(text):
        return build_direct_reply_decision(
            intent="contract_change_guidance",
            topic="換約或轉換方案",
            reply=CONTRACT_CHANGE_REPLY,
            reason="direct_contract_change_guidance_rule",
        )

    if is_generic_fee_lookup_query(text):
        return build_clarify_decision(
            intent="generic_fee_lookup_clarification",
            topic="費用查詢",
            reply=GENERIC_FEE_LOOKUP_CLARIFY_REPLY,
            reason="direct_generic_fee_lookup_clarification_rule",
        )

    if is_personal_monthly_fee_clarify_query(text):
        return build_clarify_decision(
            intent="personal_monthly_fee_clarify",
            topic="月租查詢類型",
            reply="請問您是想查詢目前待繳帳單金額，還是查詢目前合約／服務內容？",
            reason="direct_personal_monthly_fee_clarify_rule",
        )

    if is_next_tier_plan_fee_query(text):
        return build_knowledge_query_decision(
            intent="next_tier_plan_fee_guidance",
            topic="升級高一階費用",
            knowledge_query=(
                f"{text} 目前可推廣寬頻方案 電視加網路方案 升級費用 合約期間"
            ),
            reason="next_tier_plan_fee_knowledge_rule",
        )

    if is_tv_only_promotion_query(text):
        return build_knowledge_query_decision(
            intent="pure_tv_promotion_query",
            topic="單辦有線電視優惠",
            knowledge_query=f"{PURE_TV_INSTALL_KNOWLEDGE_QUERY} {text}",
            reason="direct_tv_only_promotion_knowledge_rule",
        )

    if is_ambiguous_signal_instability_query(text):
        return build_clarify_decision(
            intent="signal_instability_service_clarification",
            topic="訊號不穩",
            reply="請問您反映的是電視訊號不穩，還是網路訊號不好？我會依您使用的服務帶您進行對應的故障排除。",
            reason="clarify_ambiguous_signal_instability_rule",
        )

    if is_tv_signal_instability_repair_query(text):
        return build_tool_action_decision(
            intent="tv_signal_instability_repair",
            tool_name="create_repair_ticket",
            topic="電視訊號不穩維修申告",
            reply="了解，網路可正常使用但電視訊號持續不穩，將協助您進入維修申告流程安排檢查。",
            reason="direct_tv_signal_instability_repair_rule",
        )

    if is_network_signal_instability_query(text):
        return build_troubleshooting_decision(
            text,
            "direct_network_signal_instability_rule",
        )

    if is_network_outage_instability_query(text):
        return build_direct_reply_decision(
            intent="network_outage_instability_check",
            topic="網路不穩與區域故障",
            reply=build_network_outage_instability_reply(memory),
            reason="direct_network_outage_instability_rule",
        )

    if is_network_intermittent_fault_query(text):
        return build_troubleshooting_decision(
            text,
            "direct_network_intermittent_fault_rule",
        )

    if is_network_instability_short_query(text):
        return build_direct_reply_decision(
            intent="network_instability_scope_clarification",
            topic="網路連線不順",
            reply=NETWORK_SCOPE_CLARIFY_REPLY,
            reason="direct_network_instability_short_rule",
        )

    if is_line_tv_opening_query(text):
        return build_direct_reply_decision(
            intent="line_tv_opening_query",
            topic="LINE TV 開通與登入",
            reply=LINE_TV_OPENING_REPLY,
            reason="direct_line_tv_opening_reply_rule",
        )

    if text.replace(" ", "").replace("　", "") in {"不想看了", "不看了", "不要看了"}:
        return build_clarify_decision(
            intent="stop_watching_clarify",
            topic="退租或暫停收看",
            reply=STOP_WATCHING_CLARIFY_REPLY,
            reason="direct_stop_watching_clarify_rule",
        )

    if (
        memory.get("company_code") == "wctv"
        and is_new_network_equipment_registration_query(text)
    ):
        return build_direct_reply_decision(
            intent="wctv_new_network_equipment_registration",
            topic="更換設備後網路註冊",
            reply=WCTV_NEW_NETWORK_EQUIPMENT_REPLY,
            reason="direct_wctv_new_network_equipment_registration_rule",
        )

    if is_router_replacement_query(text):
        return build_direct_reply_decision(
            intent="router_replacement_clarify",
            topic="更換分享器",
            reply=ROUTER_REPLACEMENT_CLARIFY_REPLY,
            reason="direct_router_replacement_clarify_rule",
        )

    if is_ds_light_blinking_query(text):
        return build_direct_reply_decision(
            intent="ds_light_blinking",
            topic="數據機 DS 燈閃爍",
            reply=DS_LIGHT_BLINKING_REPLY,
            reason="direct_ds_light_blinking_rule",
        )

    if is_general_channel_e004_query(text):
        return build_clarify_decision(
            intent="general_channel_e004_temp_restore_clarify",
            topic="一般頻道 E004",
            reply=GENERAL_CHANNEL_E004_REPLY,
            reason="direct_general_channel_e004_temp_restore_clarify_rule",
        )

    if (
        any(term in text for term in ("授權過期", "E004", "未授權", "無授權"))
        and str(memory.get("company_code") or memory.get("tv_cable") or "").lower() == "cnt"
        and str(known.get("custnum") or memory.get("custnum") or "") == "609741"
    ):
        return build_direct_reply_decision(
            intent="cnt_seasonal_authorization_paid",
            topic="中投季繳授權與 HBO 優惠",
            reply=CNT_SEASONAL_AUTHORIZATION_REPLY,
            reason="direct_cnt_seasonal_authorization_paid_rule",
        )

    if is_online_payment_done_followup(text):
        return build_direct_reply_decision(
            intent="online_payment_done_activation",
            topic="線上繳費後開通",
            reply=ONLINE_PAYMENT_DONE_REPLY,
            reason="direct_online_payment_done_rule",
        )

    if is_app_payment_receipt_query(text):
        return build_direct_reply_decision(
            intent="app_payment_receipt_lookup",
            topic="APP 線上繳費收據與發票查詢",
            reply=APP_PAYMENT_RECEIPT_REPLY,
            reason="direct_app_payment_receipt_rule",
        )

    if is_cloud_account_app_usage_query(text):
        return build_direct_reply_decision(
            intent="cloud_account_app_usage",
            topic="雲端帳號與行動客服 APP",
            reply=CLOUD_ACCOUNT_APP_GUIDE_REPLY,
            reason="direct_cloud_account_app_usage_rule",
        )

    if is_tv_no_program_query(text):
        return build_direct_reply_decision(
            intent="tv_no_program_clarify",
            topic="電視沒有節目",
            reply=TV_NO_PROGRAM_CLARIFY_REPLY,
            reason="direct_tv_no_program_clarify_rule",
        )

    if is_half_year_online_payment_query(text):
        return build_direct_reply_decision(
            intent="half_year_online_payment",
            topic="半年繳與線上繳費",
            reply=HALF_YEAR_ONLINE_PAYMENT_REPLY,
            reason="direct_half_year_online_payment_rule",
        )

    if is_member_registration_query(text):
        return build_direct_reply_decision(
            intent="member_registration_policy",
            topic="會員與用戶編號",
            reply=MEMBER_REGISTRATION_REPLY,
            reason="direct_member_registration_rule",
        )

    if is_set_top_box_relocation_payment_query(text):
        return build_direct_reply_decision(
            intent="set_top_box_relocation_payment",
            topic="機上盒移機付款方式",
            reply=SET_TOP_BOX_RELOCATION_PAYMENT_REPLY,
            reason="direct_set_top_box_relocation_payment_rule",
        )

    if (
        is_rebooted_all_channel_unavailable_query(text)
        and known.get("troubleshooting_started") != "yes"
        and known.get("_previous_troubleshooting_started") != "yes"
    ):
        return build_direct_reply_decision(
            intent="tv_all_channels_unavailable_after_reboot",
            topic="全部頻道無法收視",
            reply=ALL_CHANNELS_REBOOTED_REPLY,
            reason="direct_tv_all_channels_unavailable_after_reboot_rule",
        )

    if is_tv_safe_mode_query(text):
        return build_direct_reply_decision(
            intent="tv_safe_mode_recovery",
            topic="電視安全模式",
            reply=TV_SAFE_MODE_REPLY,
            reason="direct_tv_safe_mode_recovery_rule",
        )

    if is_wifi_router_password_query(text):
        return build_direct_reply_decision(
            intent="wifi_router_password_help",
            topic="WiFi 分享器密碼",
            reply=WIFI_ROUTER_PASSWORD_REPLY,
            reason="direct_wifi_router_password_rule",
        )

    if is_wireless_network_acquisition_query(text):
        return build_clarify_decision(
            intent="wireless_network_acquisition_clarify",
            topic="無線網路申請",
            reply=WIRELESS_NETWORK_CLARIFY_REPLY,
            reason="direct_wireless_network_acquisition_clarify_rule",
        )

    if is_prepay_lookup_query(text):
        return build_direct_reply_decision(
            intent="prepay_bill_lookup",
            topic="預繳與待繳帳單",
            reply=PREPAY_LOOKUP_REPLY,
            reason="direct_prepay_lookup_rule",
        )

    if is_connected_stb_youtube_query(text):
        return build_direct_reply_decision(
            intent="connected_stb_youtube",
            topic="聯網機上盒 YouTube",
            reply=CONNECTED_STB_YOUTUBE_REPLY,
            reason="direct_connected_stb_youtube_rule",
        )

    normalized_text = re.sub(r"\s+", "", text)
    if (
        any(term in normalized_text for term in ("機上盒", "電視畫面", "頻道畫面"))
        and "密碼" in normalized_text
        and any(term in normalized_text for term in ("輸入", "要求", "出現", "跳出", "顯示", "要我"))
    ):
        return build_direct_reply_decision(
            intent="tv_password_prompt",
            topic="機上盒畫面要求輸入密碼",
            reply=TV_PASSWORD_PROMPT_REPLY,
            reason="direct_tv_password_prompt_rule",
        )

    if (
        any(term in normalized_text for term in ("更換用戶", "變更用戶", "換用戶", "過戶", "更名"))
        and any(term in normalized_text for term in ("第四台", "有線電視", "光纖", "網路", "寬頻"))
    ):
        return build_direct_reply_decision(
            intent="service_account_transfer",
            topic="第四台與光纖服務過戶／更名",
            reply=SERVICE_ACCOUNT_TRANSFER_REPLY,
            reason="direct_service_account_transfer_rule",
        )

    if is_broadband_unlimited_query(text):
        return build_direct_reply_decision(
            intent="broadband_unlimited_usage",
            topic="寬頻流量限制",
            reply=BROADBAND_UNLIMITED_REPLY,
            reason="direct_broadband_unlimited_rule",
        )

    if is_identity_document_upload_query(text):
        return build_direct_reply_decision(
            intent="identity_document_upload",
            topic="身分證件補件與上傳",
            reply=IDENTITY_DOCUMENT_UPLOAD_REPLY,
            reason="direct_identity_document_upload_rule",
        )

    if is_area_repair_status_query(text):
        return build_direct_reply_decision(
            intent="area_repair_status_lookup",
            topic="維修進度確認",
            reply=build_area_repair_status_reply(memory, text),
            reason="direct_area_repair_status_rule",
        )

    if is_contract_lookup_with_explicit_address(text):
        return build_direct_reply_decision(
            intent="address_contract_lookup_handoff",
            topic="指定地址合約查詢",
            reply=ADDRESS_CONTRACT_LOOKUP_REPLY,
            reason="direct_address_contract_lookup_rule",
        )

    if is_personal_billing_address_query(text):
        return build_direct_reply_decision(
            intent="personal_billing_address_handoff",
            topic="帳單寄送地址查詢",
            reply=PERSONAL_BILLING_ADDRESS_REPLY,
            reason="direct_personal_billing_address_rule",
        )

    if is_contract_termination_request(text):
        return build_direct_reply_decision(
            intent="contract_termination_guidance",
            topic="合約終止與退租",
            reply=SERVICE_TERMINATION_WITH_CONTRACT_REPLY,
            reason="direct_contract_termination_rule",
        )

    if is_price_complaint_query(text):
        return build_direct_reply_decision(
            intent="price_complaint",
            topic="費用疑問",
            reply=PRICE_COMPLAINT_REPLY,
            reason="direct_price_complaint_rule",
        )

    if is_sms_bill_registered_phone_policy_query(text, memory):
        return build_direct_reply_decision(
            intent="sms_bill_registered_phone_policy",
            topic="簡訊帳單登記電話",
            reply=SMS_BILL_REGISTERED_PHONE_REPLY,
            reason="direct_sms_bill_registered_phone_policy_rule",
        )

    if is_personal_contact_phone_change_query(text):
        return build_direct_reply_decision(
            intent="human_handoff_request",
            topic="變更聯絡電話",
            reply=WEB_HUMAN_HANDOFF_REPLY,
            reason="direct_personal_contact_phone_change_rule",
        )

    if is_speed_test_how_to_query(text):
        return build_direct_reply_decision(
            intent="speed_test_guide",
            topic="網路測速方式",
            reply=SPEED_TEST_GUIDE_REPLY,
            reason="direct_speed_test_guide_rule",
        )

    if is_triple_play_bill_item_query(text):
        return build_direct_reply_decision(
            intent="triple_play_bill_item_explanation",
            topic="三合一帳單項目",
            reply=TRIPLE_PLAY_BILL_ITEM_REPLY,
            reason="direct_triple_play_bill_item_rule",
        )

    if is_online_payment_activation_query(text):
        return build_direct_reply_decision(
            intent="online_payment_activation",
            topic="線上繳費與自動開通",
            reply=ONLINE_PAYMENT_ACTIVATION_REPLY,
            reason="direct_online_payment_activation_rule",
        )

    if is_online_payment_physical_receipt_query(text):
        return build_direct_reply_decision(
            intent="online_payment_receipt_query",
            topic="線上繳費收據與發票",
            reply=ONLINE_PAYMENT_RECEIPT_REPLY,
            reason="direct_online_payment_receipt_rule",
        )

    if is_paid_but_bill_still_visible_query(text):
        return build_direct_reply_decision(
            intent="store_payment_still_billed",
            topic="超商繳費入帳確認",
            reply=get_policy_text(
                memory,
                "billing.store_payment_still_billed",
                "reply",
                STORE_PAYMENT_STILL_BILLED_REPLY,
            ),
            reason="direct_store_payment_still_billed_rule",
        )

    if is_payment_not_posted_query(text):
        return build_direct_reply_decision(
            intent="payment_not_posted",
            topic="繳費未沖帳",
            reply=get_policy_text(
                memory,
                "billing.payment_not_posted",
                "reply",
                PAYMENT_NOT_POSTED_REPLY,
            ),
            reason="direct_payment_not_posted_rule",
        )

    if is_past_payment_or_posting_record_query(text):
        return build_direct_reply_decision(
            intent="past_payment_record_lookup",
            topic="已繳費明細與入帳紀錄",
            reply=get_policy_text(
                memory,
                "billing.past_payment_record",
                "reply",
                PAST_PAYMENT_RECORD_REPLY,
            ),
            reason="direct_past_payment_record_rule",
        )

    if is_next_bill_followup_query(text):
        return build_direct_reply_decision(
            intent="next_bill_after_no_unpaid",
            topic="下期帳單",
            reply=get_policy_text(
                memory,
                "billing.next_bill_after_no_unpaid",
                "reply",
                NEXT_BILL_AFTER_NO_UNPAID_REPLY,
            ),
            reason="direct_next_bill_after_no_unpaid_rule",
        )

    if is_bill_amount_difference_query(text):
        return build_direct_reply_decision(
            intent="bill_amount_difference_lookup",
            topic="本期與上期帳單差異",
            reply=BILL_AMOUNT_DIFFERENCE_REPLY,
            reason="direct_bill_amount_difference_rule",
        )

    if is_unsupported_bill_detail_query(text):
        return build_direct_reply_decision(
            intent="unsupported_bill_detail_lookup",
            topic="帳單期間與起訖日",
            reply=UNSUPPORTED_BILL_DETAIL_REPLY,
            reason="direct_unsupported_bill_detail_rule",
        )

    if is_bill_payment_deadline_query(text):
        return build_direct_reply_decision(
            intent="bill_payment_deadline_lookup",
            topic="帳單繳費期限",
            reply=(
                "目前可協助查詢本期待繳金額與已繳費迄日，但無法查詢帳單繳費截止日期。\n"
                "請以最新一期帳單標示的繳費期限為準；若帳單遺失或仍需確認期限，請由真人客服協助查詢。"
            ),
            reason="direct_bill_payment_deadline_rule",
        )

    if is_bill_content_query(text):
        return build_bill_content_query_decision("direct_bill_content_query_rule")

    if is_tv_600_fee_clarify_query(text):
        return build_direct_reply_decision(
            intent="tv_600_fee_clarify",
            topic="有線電視 $600 月費釐清",
            reply=TV_600_FEE_CLARIFY_REPLY,
            reason="direct_tv_600_fee_clarify_rule",
        )

    if is_monthly_fee_after_contract_lookup_query(text, memory):
        return build_direct_reply_decision(
            intent="monthly_fee_after_contract_lookup",
            topic="已繳費明細與入帳紀錄",
            reply=PAST_PAYMENT_RECORD_REPLY,
            reason="direct_monthly_fee_after_contract_lookup_rule",
        )

    if is_personal_service_fee_lookup_query(text):
        return build_tool_action_decision(
            intent="service_content_query",
            tool_name="search_contract_info",
            topic="目前服務費用查詢",
            reply="可以，我幫您查詢目前服務內容與合約資訊。",
            reason="direct_personal_service_fee_lookup_rule",
        )

    if is_restricted_channel_purchase_query(text):
        return build_knowledge_query_decision(
            intent="restricted_channel_purchase",
            topic="限制級頻道購買",
            knowledge_query=(
                "限制級 成人頻道 成人節目 授權到期 購買 加購 訂購 價格 元 "
                "聯網機上盒 VIP會員 優惠專區 數位電視 客服"
            ),
            reason="direct_restricted_channel_purchase_knowledge_rule",
        )

    if is_invoice_carrier_query(text):
        return build_direct_reply_decision(
            intent="invoice_carrier_binding",
            topic="發票載具歸戶",
            reply=build_invoice_carrier_reply_for_query(text),
            reason="direct_invoice_carrier_knowledge_rule",
        )

    if is_refund_calculation_query(text):
        return build_direct_reply_decision(
            intent="service_refund_calculation",
            topic="解約退費確認",
            reply=REFUND_CALCULATION_REPLY,
            reason="direct_service_refund_calculation_rule",
        )

    if is_points_usage_query(text):
        return build_knowledge_query_decision(
            intent="points_usage_query",
            topic="哈POINT 紅利點數使用方式",
            knowledge_query=(
                f"{text} 哈POINT 哈 Point 紅利點數 使用方式 用途 "
                "購買台數科商品 抵扣各項服務費用 兌換商品"
            ),
            reason="direct_points_usage_knowledge_rule",
        )

    if is_points_overview_query(text):
        return build_knowledge_query_decision(
            intent="points_overview_query",
            topic="哈POINT 紅利點數說明",
            knowledge_query=(
                f"{text} 台數科紅利點數哈Point說明 "
                "紅利點數哈Point優惠積點回饋機制 如何獲得 有效期限"
            ),
            reason="direct_points_overview_knowledge_rule",
        )

    if is_overdue_disconnection_query(text):
        return build_direct_reply_decision(
            intent="overdue_disconnection_guidance",
            topic="欠費斷訊與復線",
            reply=OVERDUE_DISCONNECTION_REPLY,
            reason="direct_overdue_disconnection_guidance_rule",
        )

    if is_restore_before_payment_request(text):
        return build_clarify_decision(
            intent="overdue_reconnection_service_clarify",
            topic="復線服務類型",
            reply="請問您要恢復的是「網路」還是「電視」服務？",
            reason="restore_before_payment_service_type_clarify_rule",
        )

    if is_card_autopay_definition_query(text):
        return build_direct_reply_decision(
            intent="card_autopay_definition",
            topic="循環扣款說明",
            reply=CARD_AUTOPAY_DEFINITION_REPLY,
            reason="direct_card_autopay_definition_rule",
        )

    if is_card_autopay_binding_status_query(text):
        return build_direct_reply_decision(
            intent="card_autopay_binding_status_handoff",
            topic="信用卡扣繳綁定確認",
            reply=CARD_AUTOPAY_BINDING_STATUS_REPLY,
            reason="direct_card_autopay_binding_status_handoff_rule",
        )

    if is_card_autopay_application_query(text):
        return build_direct_reply_decision(
            intent="card_autopay_application",
            topic="信用卡自動扣款申請方式",
            reply=CARD_AUTOPAY_APPLICATION_REPLY,
            reason="direct_card_autopay_application_rule",
        )

    if is_online_payment_account_help_query(text):
        return build_direct_reply_decision(
            intent="online_payment_account_help",
            topic="線上繳費帳號協助",
            reply=(
                "用戶編號可在紙本帳單、簡訊帳單，或哈TV行動客服 APP 的帳務資料中找到。\n"
                "若已註冊但忘記密碼，請在 APP 或官網登入頁選擇「忘記密碼」，"
                "依登記手機號碼接收簡訊驗證碼後重設。\n"
                "若尚未註冊、收不到驗證簡訊或無法確認用戶編號，請由真人客服協助核對。"
            ),
            reason="direct_online_payment_account_help_rule",
        )

    if is_basic_channel_table_query(text):
        return build_direct_reply_decision(
            intent="basic_channel_table_query",
            topic="基本頻道表",
            reply=BASIC_CHANNEL_TABLE_REPLY,
            reason="direct_basic_channel_table_rule",
        )

    if is_line_tv_opening_query(text):
        return build_knowledge_query_decision(
            intent="line_tv_opening_query",
            topic="LINE TV 開通與登入",
            knowledge_query=f"{LINE_TV_OPENING_QUERY} {text}",
            reason="direct_line_tv_opening_knowledge_rule",
        )

    if is_mobile_casting_query(text):
        return build_direct_reply_decision(
            intent="mobile_casting_tv",
            topic="手機投影電視",
            reply=MOBILE_CASTING_REPLY,
            reason="direct_mobile_casting_rule",
        )

    if is_online_payment_app_password_query(text):
        return build_direct_reply_decision(
            intent="online_payment_app_password_policy",
            topic="線上繳費與 APP 帳密",
            reply=ONLINE_PAYMENT_APP_PASSWORD_REPLY,
            reason="direct_online_payment_app_password_rule",
        )

    if (
        any(term in text for term in TV_PAID_CANNOT_WATCH_TERMS)
        and any(term in text for term in TV_CANNOT_WATCH_TERMS + ("開通", "恢復", "復線"))
    ):
        return build_tool_action_decision(
            intent="payment_receipt_reconnection",
            tool_name="payment_bill_batch",
            topic="超商收據復線",
            reply="可以，我幫您確認超商繳費收據並處理復線。請上傳超商繳費收據圖片，我會辨識收據上的三段條碼。",
            reason="direct_paid_tv_payment_receipt_reconnection_rule",
        )

    # A precise payment-method question is a new request and must not be
    # swallowed by stale account-query or troubleshooting state.
    if is_credit_card_payment_method_query(text):
        return build_direct_reply_decision(
            intent="credit_card_payment_methods",
            topic="信用卡繳費",
            reply=CARD_PAYMENT_METHOD_REPLY,
            reason="direct_credit_card_payment_method_rule",
        )

    if is_convenience_store_payment_machine_query(text):
        return build_knowledge_query_decision(
            intent="convenience_store_payment_machine_guide",
            topic="超商繳費機操作",
            knowledge_query="IBON FAMIPORT ibon famiport 超商繳費機 便利商店機台 繳費教學 操作流程 7-Eleven 全家",
            reason="direct_convenience_store_payment_machine_guide_rule",
        )

    if is_payment_method_query(text):
        return build_direct_reply_decision(
            intent="bill_payment_methods",
            topic="繳費方式",
            reply=PAYMENT_METHOD_REPLY,
            reason="direct_payment_method_query_rule",
        )

    if any(term in text for term in BILL_LOST_OR_PAYMENT_TERMS):
        return build_direct_reply_decision(
            intent="bill_payment_methods",
            topic="帳單遺失與繳費方式",
            reply=(
                "帳單不見或沒收到時，仍可用多種方式繳費：可至 7-11 ibon 或全家 FamiPort 依指示繳費，"
                "也可用官網線上繳費、哈TV行動客服 APP，或到公司櫃台繳費。"
                "若需要補發簡訊帳單，再提供戶名與聯絡電話由客服協助。"
            ),
            reason="direct_bill_lost_payment_methods_rule",
        )

    if any(term in text for term in APP_BILL_GUIDE_TERMS):
        return build_direct_reply_decision(
            intent="app_bill_guide",
            topic="哈TV行動客服 APP 查帳單",
            reply=(
                "您可以用哈TV行動客服 APP 查詢帳單：先下載並登入 APP，"
                "進入帳務或我的資訊相關選單，再點選帳單查詢或帳單歷史。"
                "若登入後查不到資料，請確認帳號是否已綁定正確用戶資料，或由客服協助身分核對。"
            ),
            reason="direct_app_bill_guide_rule",
        )

    if any(term in text for term in PASSWORD_TERMS):
        return build_direct_reply_decision(
            intent="password_help",
            topic="忘記密碼",
            reply=(
                "如果是哈TV行動客服或會員帳號忘記密碼，請先使用登入頁面的「忘記密碼」流程重設。"
                "若無法完成重設，建議由客服協助身分核對後處理；請不要在公開對話中提供完整密碼或敏感資料。"
            ),
            reason="direct_password_rule",
        )

    company_info_interrupt = detect_company_info_interrupt_query(text, memory)
    if company_info_interrupt:
        return company_info_interrupt

    service_availability = detect_service_availability_query(text, memory)
    if service_availability:
        return service_availability

    if memory.get("pending_tool") or known.get("troubleshooting_started") == "yes":
        return None

    if (
        known.get("tv_reactivation_status") == "already_temp_restored"
        and any(
            term in text
            for term in TV_CANNOT_WATCH_TERMS + (
                "不可以看電視",
                "電視還是不可以看",
                "還是不可以看",
            )
        )
    ):
        return build_direct_reply_decision(
            intent="tv_reactivation_already_temp_restored_followup",
            topic="已暫復後仍無法收看",
            reply=(
                "系統顯示已做過暫時復線，無法重複暫復。\n"
                "請先將機上盒電源關閉約 10 秒後重新開機，等待 2 到 3 分鐘再切換頻道測試。\n"
                "若仍無法收看，請由真人客服協助核對帳務入帳與收視授權狀態。"
            ),
            reason="direct_tv_reactivation_already_temp_restored_followup_rule",
        )

    if any(term in text for term in TV_AUTHORIZATION_TERMS):
        return build_direct_reply_decision(
            intent="tv_authorization_payment_check",
            topic="電視授權到期與繳費確認",
            reply=TV_AUTHORIZATION_PAYMENT_REPLY,
            reason="direct_tv_authorization_payment_rule",
        )

    if any(term in text for term in REPAIR_SERVICE_HOUR_TERMS):
        return build_direct_reply_decision(
            intent="company_repair_service_hours",
            topic="電話報修客服時間",
            reply=(
                "電話報修客服與智能 AI 服務為 24 小時服務。\n"
                "若需要報修，您可以直接描述故障狀況，或使用維修申告管道；"
                "公司櫃台營業時間僅適用於臨櫃辦理。"
            ),
            reason="direct_repair_service_24h_rule",
        )

    if (
        any(term in text for term in TV_PAID_CANNOT_WATCH_TERMS)
        and any(term in text for term in TV_CANNOT_WATCH_TERMS)
    ):
        return build_tool_action_decision(
            intent="payment_receipt_reconnection",
            tool_name="payment_bill_batch",
            topic="超商收據復線",
            reply="可以，我幫您確認超商繳費收據並處理復線。請上傳超商繳費收據圖片，我會辨識收據上的三段條碼。",
            reason="direct_paid_tv_payment_receipt_reconnection_rule",
        )

    if (
        any(term in text for term in NON_PROMOTED_1G_TERMS)
        and any(term in text for term in APPLY_PLAN_TERMS)
        and any(term in text for term in ["網路", "寬頻", "方案"])
    ):
        return build_direct_reply_decision(
            intent="non_promoted_1g_plan",
            topic="1G 非主推網路方案",
            reply=get_policy_text(
                memory,
                "promotion.non_promoted_1g_plan",
                "reply",
                (
                    "您好！1G 非主推網路方案，實際申辦資格及服務條件需依安裝地點及設備條件確認。"
                    "若您有申辦需求，我們將安排專人為您進一步說明與協助。"
                ),
            ),
            reason="direct_non_promoted_1g_plan_rule",
        )

    if is_promotion_application_request(text):
        return build_direct_reply_decision(
            intent="human_handoff_request",
            topic="優惠方案申辦",
            reply=WEB_HUMAN_HANDOFF_REPLY,
            reason="direct_promotion_application_handoff_rule",
        )

    if (
        any(term in text for term in RELOCATION_TERMS)
        and any(term in text for term in ["網路", "寬頻"])
        and not any(term in text for term in RELOCATION_FEE_TERMS)
    ):
        if any(term in text for term in RELOCATION_NETWORK_ONLY_TERMS):
            return build_direct_reply_decision(
                intent="network_only_relocation",
                topic="網路移機",
                reply=(
                    "可以的，您可先辦理寬頻網路移機，第四台服務可暫不辦理移機。"
                    "為確認新址是否位於本公司服務範圍內，請提供搬遷後的完整地址，"
                    "我們將先為您查詢並協助安排網路移機。"
                ),
                reason="direct_network_only_relocation_rule",
            )

        if any(term in text for term in ["第四台", "電視", "有線電視"]):
            return build_direct_reply_decision(
                intent="tv_network_relocation",
                topic="有線電視與網路移機",
                reply=(
                    "您好，我們可受理有線電視與寬頻網路同時辦理移機。"
                    "為確認新址是否位於本公司服務範圍內，請您提供搬遷後的完整地址，"
                    "我們將先為您查詢並協助後續移機申請。"
                ),
                reason="direct_tv_network_relocation_rule",
            )

    if any(term in text for term in VAGUE_NETWORK_TROUBLESHOOTING_TERMS):
        return build_clarify_decision(
            intent="network_troubleshooting_clarify",
            topic="網路排除",
            reply=(
                "請問您想排除的是哪一種網路狀況：無法連線、速度慢、Wi-Fi 連不上、"
                "數據機燈號異常，還是只有特定手機或電腦不能上網？"
            ),
            reason="clarify_vague_network_troubleshooting_rule",
        )

    if "哪個住址" in text or "哪個地址" in text:
        return build_direct_reply_decision(
            intent="address_disambiguation",
            topic="地址核對",
        reply="查詢帳單請提供客戶編號、戶名、登記電話任兩項；合約資訊則需先登入會員查詢。",
            reason="direct_address_disambiguation_rule",
        )

    compact_text = text.replace(" ", "").replace("　", "")
    if (
        any(term.replace(" ", "").replace("　", "") in compact_text for term in RENEWAL_PROCESS_TERMS)
        and any(term.replace(" ", "").replace("　", "") in compact_text for term in RENEWAL_PROCESS_ACTION_TERMS)
    ):
        return build_knowledge_query_decision(
            intent="renewal_process_query",
            topic="續約辦理方式",
            knowledge_query=(
                "續約 重新續約 續訂 重新訂購 約滿 合約到期後 "
                "合約狀態 換約 升級 辦理方式 流程 客服確認"
            ),
            reason="direct_renewal_process_knowledge_rule",
        )

    recent_campaign = infer_recent_campaign_topic(memory)
    if recent_campaign and any(
        term.replace(" ", "").replace("　", "") in compact_text
        for term in ONE_YEAR_NETWORK_CONTRACT_TERMS
    ):
        return build_direct_reply_decision(
            intent="promotion_one_year_contract_followup",
            topic=f"{recent_campaign} 一年合約",
            reply=(
                f"前面提到的「{recent_campaign}」資料沒有列出只綁一年的優惠選項。\n"
                "請注意，「年繳」是繳費週期，不代表合約只綁一年；目前資料所列主推優惠多為 24 個月。\n"
                "若要確認是否另有一年合約或其他非主推選擇，需由客服依當期方案確認。"
            ),
            reason="direct_promotion_one_year_contract_followup_rule",
        )

    # A customer can mention an expiring contract only as context for choosing
    # a new standalone network plan.  Preserve that explicit purchase intent
    # instead of hijacking the turn as a personal contract lookup.
    if is_pure_network_plan_query(text):
        return build_knowledge_query_decision(
            intent="pure_network_install_plan_query",
            topic="純網方案",
            reason="direct_pure_network_plan_before_contract_lookup_rule",
            knowledge_query=f"{PURE_NETWORK_INSTALL_KNOWLEDGE_QUERY} {text}",
        )

    if any(term in text for term in CONTRACT_LOOKUP_TERMS):
        return build_tool_action_decision(
            intent="service_content_query",
            tool_name="search_contract_info",
            topic="合約查詢",
            reply="可以，我幫您查詢目前服務內容與合約資訊。",
            reason="direct_contract_lookup_rule",
        )

    if is_hatv_plus_youtube_query(text):
        return build_direct_reply_decision(
            intent="hatv_plus_youtube",
            topic="哈TV+ YouTube",
            reply=HATV_PLUS_YOUTUBE_REPLY,
            reason="direct_hatv_plus_youtube_rule",
        )

    if any(term in text for term in APPLE_PAY_TERMS):
        return build_direct_reply_decision(
            intent="apple_pay_payment",
            topic="Apple Pay",
            reply=(
                "目前不支援 Apple Pay。您可改用帳單條碼至超商繳費、官網線上繳費、"
                "哈TV行動客服 APP、金融機構代收，或至公司櫃台繳費；實際可用方式仍以帳單與客服確認為準。"
            ),
            reason="direct_apple_pay_rule",
        )

    if is_social_discount_alternative_promotion_query(text):
        return build_clarify_decision(
            intent="promotion_service_scope_clarification",
            topic="優惠方案服務類型",
            reply=PROMOTION_SERVICE_SCOPE_CLARIFY_REPLY,
            reason="social_discount_ineligible_promotion_scope_clarification_rule",
        )

    if is_low_income_500m_year_fee_query(text):
        return build_direct_reply_decision(
            intent="low_income_500m_year_fee",
            topic="低收入戶 500M 年費",
            reply=get_policy_text(
                memory,
                "promotion.low_income_500m_year_fee",
                "reply",
                LOW_INCOME_500M_YEAR_REPLY,
            ),
            reason="direct_low_income_500m_year_fee_rule",
        )

    if any(term in text for term in LOW_INCOME_DISABILITY_TERMS):
        return build_knowledge_query_decision(
            intent="social_discount_query",
            topic="社福優惠",
            knowledge_query=text,
            reason="social_discount_knowledge_rule",
        )

    if any(term in text for term in ENGINEER_WEEKEND_TERMS):
        return build_direct_reply_decision(
            intent="engineer_weekend_service",
            topic="工程假日服務",
            reply=(
                "假日可受理裝機或維修預約，但仍需依當日工程量控與排程確認。"
                "裝機工程會依可預約時段安排；維修工程通常由輪值人員處理，實際到府時間需由客服確認。"
            ),
            reason="direct_engineer_weekend_rule",
        )

    if any(term in text for term in REMOTE_PRICE_TERMS):
        return build_direct_reply_decision(
            intent="remote_control_price",
            topic="遙控器價格",
            reply=get_policy_text(
                memory,
                "support.remote_control_price",
                "reply",
                (
                    "一般型遙控器 300 元、語音遙控器 400 元，保固一年；"
                    "實際型號與是否需更換仍以客服或工程人員確認為準。"
                ),
            ),
            reason="direct_remote_control_price_rule",
        )

    if any(term in text for term in REMOTE_POWER_LEARN_TERMS):
        return build_direct_reply_decision(
            intent="remote_power_learning",
            topic="雙模機遙控器電源鍵學習",
            reply=(
                "雙模機遙控器若要拷貝或學習電視電源鍵，可先將電視原廠遙控器與雙模機遙控器的紅外線發射端相對，"
                "距離約 3 到 5 公分；接著長按雙模機遙控器的「學習／設定」鍵約 3 秒進入學習模式，"
                "再按雙模機遙控器要設定的「電源鍵」，最後按電視原廠遙控器的「電源鍵」。"
                "若指示燈閃爍後保持常亮，通常代表學習成功；完成後按 OK 或設定鍵保存。"
                "不同型號按鍵名稱與燈號可能不同，若無法完成請洽真人客服確認型號。"
            ),
            reason="direct_remote_power_learning_rule",
        )

    if any(term in text for term in WIFI_AP_SETTING_TERMS):
        return build_direct_reply_decision(
            intent="wifi_ap_setting",
            topic="Wi-Fi AP 設定",
            reply=(
                "新增 Wi-Fi 無線 AP 或分享器時，請依該品牌說明書進入設定頁；"
                "網路連線類型通常選「動態 DHCP／浮動 IP」，再設定 Wi-Fi 名稱與密碼即可。"
                "若需橋接、固定 IP 或特殊內網設定，建議由工程或客服協助確認。"
            ),
            reason="direct_wifi_ap_setting_rule",
        )

    normalized_width_text = normalize_text_width(text)
    if (
        any(term in text for term in WIFI_ROUTER_SALE_TERMS)
        and any(term in normalized_width_text.lower() for term in ("wifi", "wi-fi", "分享器", "mesh"))
    ):
        return build_direct_reply_decision(
            intent="wifi_router_sale",
            topic="Wi-Fi 分享器租借/加購",
            reply=(
                "目前提供的是「租借／加購」Wi-Fi 分享器服務，暫無單機販售資訊。"
                "申裝寬頻網路可搭配 Mesh WiFi 租借方案：Mesh WiFi-5 半年繳 150 元／顆、年繳 300 元／顆；"
                "Mesh WiFi-6 半年繳 300 元／顆、年繳 600 元／顆。"
                "也可透過聯網機上盒 VIP會員 → 優惠專區 → 加值服務 → MESH WIFI 加值服務申辦；"
                "實際是否可辦理仍需由客服確認。"
            ),
            reason="direct_wifi_router_sale_rule",
        )

    if is_convenience_store_payment_machine_query(text):
        return build_knowledge_query_decision(
            intent="convenience_store_payment_machine_guide",
            topic="超商繳費機操作",
            knowledge_query="IBON FAMIPORT ibon famiport 超商繳費機 便利商店機台 繳費教學 操作流程 7-Eleven 全家",
            reason="direct_convenience_store_payment_machine_guide_rule",
        )

    if is_online_payment_account_help_query(text):
        return build_direct_reply_decision(
            intent="online_payment_account_help",
            topic="線上繳費帳號協助",
            reply=(
                "用戶編號可在紙本帳單、簡訊帳單，或哈TV行動客服 APP 的帳務資料中找到。\n"
                "若已註冊但忘記密碼，請在 APP 或官網登入頁選擇「忘記密碼」，"
                "依登記手機號碼接收簡訊驗證碼後重設。\n"
                "若尚未註冊、收不到驗證簡訊或無法確認用戶編號，請由真人客服協助核對。"
            ),
            reason="direct_online_payment_account_help_rule",
        )

    if is_network_fee_overdue_query(text):
        return build_direct_reply_decision(
            intent="overdue_network_bill_payment",
            topic="網路費逾期繳費",
            reply=(
                "網路費已逾期仍可先嘗試繳費：\n"
                "1. 至官網「線上繳費專區」繳費。\n"
                "2. 使用哈TV行動客服 APP 繳費。\n"
                "3. 持帳單條碼至 7-11 ibon 或全家 FamiPort 等超商通路繳費。\n"
                "4. 至公司櫃台臨櫃繳費。\n"
                "若帳單條碼已失效或無法繳費，請由真人客服協助確認帳務狀況。"
            ),
            reason="direct_overdue_network_bill_payment_rule",
        )

    if is_payment_method_query(text):
        return build_direct_reply_decision(
            intent="bill_payment_methods",
            topic="繳費方式",
            reply=PAYMENT_METHOD_REPLY,
            reason="direct_payment_method_query_rule",
        )

    if is_install_contact_or_quote_followup(text):
        profile = get_company_profile(memory.get("company_code") or memory.get("tv_cable") or DEFAULT_TV_CABLE)
        install_link = build_company_link(profile, "裝機申告")
        install_channel = (
            f"也可透過{install_link}補充需求，讓專人協助追蹤。"
            if install_link
            else "若需查詢已現勘或報價進度，建議轉由真人客服協助追蹤。"
        )
        return build_direct_reply_decision(
            intent="install_contact_or_quote_followup",
            topic="裝機報價與聯繫追蹤",
            reply=(
                "您好，您這個狀況需要由真人客服協助確認現勘、報價或牽線進度。\n"
                f"{install_channel}"
            ),
            reason="direct_install_contact_or_quote_followup_rule",
        )

    if is_basic_tv_fee_query(text):
        return build_knowledge_query_decision(
            intent="basic_tv_fee_query",
            topic="有線電視基本收費",
            knowledge_query=(
                f"{text} CATV TV 基本收費標準 只看第四台 純 TV 有線電視 "
                "基本收視費 月繳 月租 月費 裝機費 機上盒押金 分機費"
            ),
            reason="direct_basic_tv_fee_knowledge_rule",
        )

    if is_value_added_service_followup_query(text, memory):
        return build_knowledge_query_decision(
            intent="value_added_service_query",
            topic="加值服務",
            knowledge_query="各項單品銷售 加值服務 數位電視套餐 加值數位套餐 月繳 價格",
            reason="direct_value_added_service_followup_knowledge_rule",
        )

    hatv_package_key = detect_hatv_package_key(text)
    if hatv_package_key:
        return build_knowledge_query_decision(
            intent="hatv_package_channel_query",
            topic=f"哈TV {hatv_package_key}套餐",
            knowledge_query=f"雲林 哈TV {hatv_package_key}套餐 頻道內容 原價 有哪些頻道 {text}",
            reason="direct_hatv_package_channel_knowledge_rule",
        )

    if is_value_added_service_query(text):
        if not is_value_added_catalog_overview_query(text):
            return build_clarify_decision(
                intent="value_added_service_clarification",
                topic="加值服務",
                reply=VALUE_ADDED_SERVICE_CLARIFY_REPLY,
                reason="direct_unspecified_value_added_service_clarification",
            )
        return build_knowledge_query_decision(
            intent="value_added_service_query",
            topic="加值服務",
            knowledge_query="加值服務 單品銷售 熱門單品 加購服務 優惠專區 VIP會員",
            reason="direct_value_added_service_knowledge_rule",
        )

    promotion_followup = detect_promotion_followup_detail_query(text, memory)
    if promotion_followup:
        return promotion_followup

    if is_service_suspension_query(text):
        return build_service_suspension_query_decision("direct_service_suspension_query_rule")

    if is_ambiguous_service_stop_query(text):
        return build_clarify_decision(
            intent="stop_watching_clarify",
            topic="退租或暫停服務",
            reply=STOP_WATCHING_CLARIFY_REPLY,
            reason="direct_ambiguous_service_stop_rule",
        )

    if is_service_termination_query(text):
        return build_service_termination_query_decision("direct_service_termination_query_rule")

    if any(term in text for term in BILL_LOST_OR_PAYMENT_TERMS):
        return build_direct_reply_decision(
            intent="bill_payment_methods",
            topic="帳單遺失與繳費方式",
            reply=(
                "帳單不見或沒收到時，仍可用多種方式繳費：可至 7-11 ibon 或全家 FamiPort 依指示繳費，"
                "也可用官網線上繳費、哈TV行動客服 APP，或到公司櫃台繳費。"
                "若需要補發簡訊帳單，再提供戶名與聯絡電話由客服協助。"
            ),
            reason="direct_bill_lost_payment_methods_rule",
        )

    if is_service_content_query(text):
        return build_tool_action_decision(
            intent="service_content_query",
            tool_name="search_contract_info",
            topic="服務內容查詢",
            reply="可以，我幫您查詢目前服務內容與合約資訊。",
            reason="direct_service_content_query_rule",
        )

    if any(term in text for term in PERSONAL_ACCOUNT_QUERY_TERMS):
        return build_tool_action_decision(
            intent="service_content_query",
            tool_name="search_contract_info",
            topic="合約到期日",
            reply="可以，我幫您查詢目前服務內容與合約資訊。",
            reason="direct_contract_date_rule",
        )

    if any(term in text for term in CURRENT_PLAN_QUERY_TERMS):
        return build_tool_action_decision(
            intent="service_content_query",
            tool_name="search_contract_info",
            topic="目前合約方案",
            reply="可以，我幫您查詢目前服務內容與合約資訊。",
            reason="direct_current_plan_rule",
        )

    if any(term in text for term in APP_BILL_GUIDE_TERMS):
        return build_direct_reply_decision(
            intent="app_bill_guide",
            topic="哈TV行動客服 APP 查帳單",
            reply=(
                "您可以用哈TV行動客服 APP 查詢帳單：先下載並登入 APP，"
                "進入帳務或我的資訊相關選單，再點選帳單查詢或帳單歷史。"
                "若登入後查不到資料，請確認帳號是否已綁定正確用戶資料，或由客服協助身分核對。"
            ),
            reason="direct_app_bill_guide_rule",
        )

    if any(term in text for term in PASSWORD_TERMS):
        return build_direct_reply_decision(
            intent="password_help",
            topic="忘記密碼",
            reply=(
                "如果是哈TV行動客服或會員帳號忘記密碼，請先使用登入頁面的「忘記密碼」流程重設。"
                "若無法完成重設，建議由客服協助身分核對後處理；請不要在公開對話中提供完整密碼或敏感資料。"
            ),
            reason="direct_password_rule",
        )

    if any(term in text for term in SIGNAL_SOURCE_TERMS):
        return build_direct_reply_decision(
            intent="remote_input_source_help",
            topic="訊號源設定",
            reply=(
                "請您拿電視遙控器，按「訊號源／INPUT／SOURCE」鍵，切換到機上盒連接的來源，"
                "常見為 HDMI1、HDMI2 或 AV。若不確定是哪一個，可以逐一切換，"
                "每切一次等 3 到 5 秒確認畫面是否恢復。"
            ),
            reason="direct_signal_source_rule",
        )

    if any(term in text for term in TV_BLURRY_TERMS):
        return build_direct_reply_decision(
            intent="tv_blurry_picture",
            topic="電視畫面不清",
            reply=(
                "電視畫面不清時，請先確認是第幾台，以及是單一頻道不清還是全部頻道都不清。"
                "您也可以先將機上盒電源拔掉約 10 秒後重新插上，等待 2 到 3 分鐘再確認；"
                "若仍不清楚，請提供頻道號碼與是否所有頻道皆異常，方便客服或工程協助判斷。"
            ),
            reason="direct_tv_blurry_picture_rule",
        )

    if any(term in text for term in TV_LAG_TERMS):
        return build_direct_reply_decision(
            intent="tv_picture_lag",
            topic="電視畫面 lag",
            reply=(
                "有畫面但會 lag 時，請先將機上盒電源拔掉約 10 秒後重新插上，等待 2 到 3 分鐘再確認。"
                "若仍會 lag，請再確認是單一頻道還是全部頻道、是否固定時段發生，後續可由真人客服協助安排檢查。"
            ),
            reason="direct_tv_picture_lag_rule",
        )

    if is_remote_control_issue(text):
        return build_direct_reply_decision(
            intent="remote_control_issue",
            topic="遙控器故障",
            reply=(
                "遙控器沒有反應時，請先確認按鍵時是否亮紅燈、電池是否有電、正負極是否裝反，並更換新電池再試一次。"
                "若仍無法操作，請對準機上盒或電視感應位置，確認中間沒有遮蔽物，"
                "並確認機上盒前方 IR 接收器沒有脫落。"
                "更換電池後仍無法使用時，可能需要更換遙控器。"
                "一般型遙控器 300 元、語音型遙控器 400 元，可臨櫃購買；實際型號與費用仍以客服確認為準。"
                "若上述排除後仍無法使用，可接續協助登記維修。"
            ),
            reason="direct_remote_control_rule",
        )

    if any(term in text for term in CANCEL_REPAIR_TERMS):
        return build_tool_action_decision(
            intent="cancel_repair",
            tool_name="cancel_repair_ticket",
            topic="取消報修",
            reply="可以，我先用模擬取消報修 API 測試流程。",
            reason="direct_cancel_repair_rule",
        )

    promotion_price_difference = detect_promotion_price_difference_query(text, memory)
    if promotion_price_difference:
        return promotion_price_difference

    cancel_tv_keep_internet = detect_cancel_tv_keep_internet_query(text, memory)
    if cancel_tv_keep_internet:
        return cancel_tv_keep_internet

    if is_clear_channel_group_query(text):
        return build_clear_channel_group_knowledge_decision(text)

    if is_tv_network_install_option_query(text) or any(term in text for term in COMBO_PLAN_TERMS):
        return build_knowledge_query_decision(
            intent="tv_network_install_plan_query",
            topic="電視+網路方案",
            reason="direct_tv_network_install_option_knowledge_rule",
            knowledge_query=f"{TV_NETWORK_INSTALL_KNOWLEDGE_QUERY} {text}",
        )

    if is_pure_network_plan_query(text):
        return build_knowledge_query_decision(
            intent="pure_network_install_plan_query",
            topic="純網方案",
            reason="direct_pure_network_plan_knowledge_rule",
            knowledge_query=f"{PURE_NETWORK_INSTALL_KNOWLEDGE_QUERY} {text}",
        )

    promotion_activity = detect_promotion_activity_query(text, memory)
    if promotion_activity:
        return promotion_activity

    if (
        any(term in compact_text for term in BROADBAND_PRICE_TERMS)
        or (
            any(term in compact_text for term in ("網路", "寬頻"))
            and any(term in compact_text for term in ("多少錢", "費用", "費率", "收費", "月租", "價格", "$"))
        )
    ) and not any(term in compact_text for term in BROADBAND_PRICE_EXCLUDE_TERMS):
        return build_knowledge_query_decision(
            intent="broadband_plan_price_query",
            topic="單辦寬頻費用",
            knowledge_query=(
                f"{text} 500M 網路 優惠方案 一般寬頻方案 單辦寬頻 "
                "單辦 同裝 月繳 季繳 半年繳 年繳 方案名稱 裝機費 押金"
            ),
            reason="direct_broadband_plan_price_knowledge_rule",
        )

    sports_broadcast = detect_sports_broadcast_query(text)
    if sports_broadcast:
        return sports_broadcast

    if is_channel_number_gap_query(text):
        return build_direct_reply_decision(
            intent="channel_number_gap_explanation",
            topic="頻道號碼缺口",
            reply=(
                "頻道號碼不一定會連續排列，部分號碼可能沒有配置頻道；"
                "數位頻道也可能使用 4XX 等號碼區段。\n"
                "基本收視頻道通常約有 100～120 個，但實際頻道與號碼仍依系統台公告為準。\n"
                "若要確認特定節目在哪一台，請提供頻道名稱，我可以再幫您查詢。"
            ),
            reason="direct_channel_number_gap_rule",
        )

    if (
        any(term in text for term in ("電視", "第四台", "頻道", "機上盒"))
        and any(term in text for term in ("訊號不好", "訊號不佳", "訊號不良", "無法正常看", "不能正常看", "卡卡", "不穩"))
    ):
        return build_troubleshooting_decision(text, "direct_tv_signal_fault_before_channel_query_rule")

    channel_name = extract_channel_name_from_query(text)
    if any(term in text for term in CHANNEL_QUERY_TERMS) or channel_name == "霹靂台灣台":
        return build_tool_action_decision(
            intent="channel_query",
            tool_name="search_channel_no",
            topic="頻道位置查詢",
            reply="可以，我先用模擬頻道 API 查詢頻道位置。",
            reason="direct_channel_query_rule",
            extracted_slots={"channel_name": channel_name or None},
        )

    if is_hatv_addon_query(text):
        if is_addon_knowledge_query(text):
            return build_knowledge_query_decision(
                intent="hatv_addon_knowledge",
                topic="哈TV 數位套餐加購",
                knowledge_query=f"哈TV 數位套餐 加購 費用 內容 申請方式 {text}",
                reason="direct_hatv_addon_knowledge_rule",
            )
        return build_direct_reply_decision(
            intent="hatv_addon",
            topic="哈TV 加購",
            reply=CUSTOMER_TOOL_FLOW_DISABLED_MESSAGE,
            reason="direct_hatv_addon_rule",
        )

    if any(term in text for term in ADVANCED_NETWORK_SETTING_TERMS):
        return build_direct_reply_decision(
            intent="advanced_network_setting",
            topic="路由器與橋接模式",
            reply=(
                "路由器模式通常由設備負責撥號、NAT 與分配內網 IP；橋接模式則較像把連線交給後端路由器處理。"
                "實際 Zyxel 設備要設定為路由器或橋接器，需依您的申裝方式、固定 IP、內網需求與公司端設定確認；"
                "若涉及後台參數，建議由客服或工程人員協助。"
            ),
            reason="direct_advanced_network_setting_rule",
        )

    if "違約金" in text:
        return build_tool_action_decision(
            intent="contract_penalty_lookup",
            tool_name="search_contract_info",
            topic="合約違約金",
            reply="違約金會依您的申辦方案、合約期間與目前狀態而不同，先為您查詢合約資料。",
            reason="direct_contract_penalty_lookup_rule",
        )

    if is_set_top_box_multi_fee_query(text):
        if is_two_set_top_box_monthly_total_query(text):
            return build_direct_reply_decision(
                intent="two_set_top_box_monthly_total",
                topic="兩台機上盒月繳首期費用",
                reply=(
                    "月繳申裝 2 台機上盒的首期費用如下：\n"
                    "收視費：$550 × 2 個月＝$1,100\n"
                    "裝機費：$1,500\n"
                    "第 1、2 台機上盒：免費借用、免押金\n"
                    "合計：$1,100 + $1,500＝$2,600"
                ),
                reason="direct_two_set_top_box_monthly_total_rule",
            )
        if is_three_set_top_box_half_year_query(text):
            return build_direct_reply_decision(
                intent="three_set_top_box_half_year_fee",
                topic="三台機上盒半年繳費用",
                reply=(
                    "3 台機上盒半年繳費用如下：\n"
                    "半年收視費：$3,240\n"
                    "裝機費：$1,000（半年繳優惠價）\n"
                    "第 2、3 台分機施工費：$500 × 2 台＝$1,000\n"
                    "第 3 台機上盒押金：$1,200\n"
                    "合計：$3,240 + $1,000 + $1,000 + $1,200＝$6,440"
                ),
                reason="direct_three_set_top_box_half_year_fee_rule",
            )
        return build_knowledge_query_decision(
            intent="set_top_box_multi_fee_query",
            topic="多台機上盒收費",
            knowledge_query=(
                "有線電視基本收費 機上盒多台 第1台 第2台 第3台 第6台 "
                "半年繳 收視費 裝機費 TV 分機費 STB 設備押金 分機施工費 合計 "
                f"{text}"
            ),
            reason="direct_set_top_box_multi_fee_knowledge_rule",
        )

    if (
        any(term in compact_text for term in ("網路", "寬頻"))
        and any(term in compact_text for term in ("新裝", "新申裝", "申裝", "裝機", "申辦"))
        and any(term in compact_text for term in ONE_YEAR_NETWORK_CONTRACT_TERMS)
    ):
        return build_direct_reply_decision(
            intent="new_network_one_year_contract",
            topic="新申裝寬頻綁約期間",
            reply=(
                "您好，目前資料未列出只綁一年的新申裝網路方案；目前主推 24 個月優惠方案，"
                "可享較優惠的月租費及方案內容。\n"
                "若您想了解詳細方案或確認是否有其他適合您的選擇，可由文字客服專人為您進一步說明，謝謝。"
            ),
            reason="direct_new_network_one_year_contract_rule",
        )

    # A question that names an installation location is about service coverage,
    # even though it also contains generic installation words such as "裝" or
    # "申請". Resolve that explicit target before the generic new-install plan
    # rules below can consume the question.
    if is_service_availability_query(text):
        current_service_target = resolve_service_availability_target(text)
        current_target_memory = dict(memory)
        current_target_memory["service_availability_context"] = current_service_target
        service_availability = detect_service_availability_query(text, current_target_memory)
        if service_availability:
            return service_availability

    if is_tv_network_install_option_query(text):
        return build_knowledge_query_decision(
            intent="tv_network_install_plan_query",
            topic="電視+網路方案",
            reason="direct_tv_network_install_option_knowledge_rule",
            knowledge_query=f"{TV_NETWORK_INSTALL_KNOWLEDGE_QUERY} {text}",
        )

    if is_pure_tv_install_query(text):
        profile = get_company_profile(memory.get("company_code") or memory.get("tv_cable") or DEFAULT_TV_CABLE)
        company_code = str(memory.get("company_code") or memory.get("tv_cable") or DEFAULT_TV_CABLE).lower()
        company_name = str(profile.get("name") or "")
        if company_code == "tdtv" or "大屯" in company_name:
            return build_direct_reply_decision(
                intent="pure_tv_install_query",
                topic="有線電視裝機申請",
                reply=TATUNG_TV_INSTALL_REPLY,
                reason="direct_tatung_pure_tv_install_fee_rule",
            )

        return build_direct_reply_decision(
            intent="pure_tv_install_query",
            topic="有線電視裝機申請",
            reply=PURE_TV_INSTALL_REPLY,
            reason="direct_pure_tv_install_handoff_rule",
        )

    if is_network_install_option_query(text) or is_pure_network_plan_query(text):
        return build_knowledge_query_decision(
            intent="pure_network_install_plan_query",
            topic="純網方案",
            reason="direct_pure_network_install_option_knowledge_rule",
            knowledge_query=f"{PURE_NETWORK_INSTALL_KNOWLEDGE_QUERY} {text}",
        )

    if any(term in text for term in ("我想安裝網路", "想安裝網路", "我要安裝網路", "我想裝網路", "想裝網路", "我要裝網路")):
        return build_knowledge_query_decision(
            intent="pure_network_install_plan_query",
            topic="純網方案",
            reason="direct_new_network_install_plan_knowledge_rule",
            knowledge_query=(
                f"{PURE_NETWORK_INSTALL_KNOWLEDGE_QUERY} {text}"
            ),
        )

    if any(term in text for term in NEW_INSTALL_TERMS):
        compact = (text or "").replace(" ", "").replace("　", "")
        if any(term in compact for term in NEW_INSTALL_FAULT_CONTEXT_TERMS):
            return build_troubleshooting_decision(text, "direct_new_install_fault_context_rule")

        profile = get_company_profile(memory.get("company_code") or memory.get("tv_cable") or DEFAULT_TV_CABLE)
        service_items = str(profile.get("service_items") or "")
        supports_tv = "有線電視" in service_items
        install_link = build_company_link(profile, "裝機申告")
        install_channel = (
            f"您可透過{install_link}填寫需求，由專人與您聯繫；也可轉由真人客服協助辦理。"
            if install_link
            else "目前公司資訊未設定裝機申告連結，建議轉由真人客服協助辦理。"
        )
        install_reply = (
            "您好，歡迎申請網路裝機！可先參考目前可申辦的寬頻速率與優惠方案，"
            "實際月繳/半年繳/年繳、裝機費、押金與綁約條件需依服務地區、合約狀態與活動資格確認。\n"
            f"{install_channel}"
        )
        if supports_tv:
            install_reply += "\n若您同時需要有線電視與網路，客服也可協助確認是否有適用的電視加網路同裝方案。"
        return build_direct_reply_decision(
            intent="new_network_install_plan",
            topic="新申裝寬頻方案",
            reply=install_reply,
            reason="direct_new_install_plan_query_rule",
        )

    if (
        any(term in text for term in UPGRADE_LINE_TERMS)
        and any(term in text for term in LINE_CHANGE_TERMS)
    ):
        return build_direct_reply_decision(
            intent="speed_upgrade",
            topic="升級網速是否需改線",
            reply=(
                "升級網速是否需要更改線路，要依現場線路、數據機與申辦方案確認。"
                "通常不一定需要更改屋內線路，但可能需要更換數據機或分享器；"
                "建議提供目前方案，由客服確認是否需要施工或更換設備。"
            ),
            reason="direct_speed_upgrade_line_rule",
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


def detect_troubleshooting_query(
    text: str,
    memory: Optional[Dict[str, Any]] = None,
) -> Optional[Dict[str, Any]]:
    text = (text or "").strip()
    memory = memory or {}
    known = memory.get("known_info", {})

    if not text:
        return None

    if detect_value_added_product_knowledge_query(text) or detect_equipment_purchase_knowledge_query(text):
        return None

    if memory.get("pending_tool") or known.get("troubleshooting_started") == "yes":
        return None

    if text in DIRECT_FAULT_REPORT_TERMS:
        return build_troubleshooting_decision(text, "direct_fault_report_rule")

    compact = text.replace(" ", "").replace("　", "")
    has_installed_context = any(term.replace(" ", "").replace("　", "") in compact for term in INSTALLED_SERVICE_CONTEXT_TERMS)
    has_trouble = any(term.replace(" ", "").replace("　", "") in compact for term in INSTALLED_SERVICE_TROUBLE_TERMS)
    if has_installed_context and has_trouble:
        return build_troubleshooting_decision(text, "installed_service_trouble_rule")

    if is_general_signal_fault_report(text):
        return build_troubleshooting_decision(text, "general_signal_fault_rule")

    if detect_troubleshooting_type(text):
        return build_troubleshooting_decision(text, "troubleshooting_keyword_rule")

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


def detect_payment_receipt_query(
    text: str,
    memory: Optional[Dict[str, Any]] = None,
) -> Optional[Dict[str, Any]]:
    text = (text or "").strip()
    memory = memory or {}
    known = memory.get("known_info", {})

    if not text:
        return None

    has_strong_barcode_signal = has_receipt_barcode_text(text)
    receipt_image_submission = is_receipt_image_submission(text, memory)
    has_paid_reconnection_signal = (
        any(term in text for term in PAID_RECONNECTION_TERMS)
        and any(term in text for term in ["恢復", "復線", "開通", "收看", "不能看", "不能上網"])
        and not any(term in text for term in ONLINE_PAYMENT_TERMS)
    )

    if (
        (memory.get("pending_tool") or known.get("troubleshooting_started") == "yes")
        and not has_strong_barcode_signal
        and not receipt_image_submission
    ):
        return None

    receipt_evidence = current_verified_receipt_image_evidence(memory, text)
    if receipt_evidence:
        return build_tool_action_decision(
            intent="payment_receipt_reconnection",
            tool_name="payment_bill_batch",
            topic="超商收據復線",
            reply="",
            reason="verified_receipt_image_reconnection",
        )

    if receipt_image_submission:
        return build_direct_reply_decision(
            intent="payment_receipt_image_required",
            topic="超商收據復線",
            reply=RECEIPT_IMAGE_REUPLOAD_REPLY,
            reason="payment_receipt_image_ocr_incomplete",
        )

    if has_strong_barcode_signal or (
        any(term in text for term in PAYMENT_RECEIPT_TERMS)
        and any(term in text for term in ["復線", "恢復", "開通", "繳費", "條碼"])
    ) or has_paid_reconnection_signal:
        return build_direct_reply_decision(
            intent="payment_receipt_image_required",
            topic="超商收據復線",
            reply=RECEIPT_IMAGE_REQUIRED_REPLY,
            reason="payment_receipt_image_evidence_required",
        )

    return None


def detect_reconnection_query(
    text: str,
    memory: Optional[Dict[str, Any]] = None,
) -> Optional[Dict[str, Any]]:
    text = (text or "").strip()
    memory = memory or {}
    known = memory.get("known_info", {})

    if not text:
        return None

    if memory.get("pending_tool") or known.get("troubleshooting_started") == "yes":
        return None

    if any(term in text for term in TV_AUTHORIZATION_TERMS):
        return None

    has_reconnection_signal = (
        any(term in text for term in RECONNECTION_PROBLEM_TERMS)
        or (
            any(term in text for term in RECONNECTION_PAYMENT_TERMS)
            and any(term in text for term in ["恢復", "復線", "開通", "收看", "不能看", "不能上網"])
        )
    )

    if not has_reconnection_signal:
        return None

    if any(term in text for term in NETWORK_RECONNECTION_TERMS):
        return build_reconnection_tool_decision(
            "bill_return_line_internet",
            "reconnection_network_rule",
        )

    if any(term in text for term in TV_RECONNECTION_TERMS):
        return build_reconnection_tool_decision(
            "bill_return_line_tv",
            "reconnection_tv_rule",
        )

    return build_reconnection_clarify_decision("reconnection_service_type_clarify_rule")


def detect_company_info_query(
    text: str,
    memory: Optional[Dict[str, Any]] = None,
) -> Optional[Dict[str, Any]]:
    text = (text or "").strip()
    memory = memory or {}
    known = memory.get("known_info", {})

    if not text:
        return None

    if is_contextual_website_page_request(text):
        return None

    if memory.get("pending_tool") or known.get("troubleshooting_started") == "yes":
        return None

    if any(term in text for term in SERVICE_AREA_TERMS):
        return build_company_info_decision("service_area", "company_info_service_area_rule")

    if any(term in text for term in BUSINESS_HOUR_TERMS):
        return build_company_info_decision("business_hours", "company_info_business_hours_rule")

    if any(term in text for term in VALUE_ADDED_URL_TERMS):
        return build_company_info_decision("value_added_urls", "company_info_value_added_urls_rule")

    if is_explicit_company_website_request(text) and not is_reference_website_request(text) and not any(
        term in text for term in PROMOTION_COMPANY_INFO_BLOCK_TERMS
    ):
        return build_company_info_decision("website", "company_info_website_rule")

    if any(term in text for term in CONTACT_PHONE_TERMS):
        return build_company_info_decision("contact_phone", "company_info_contact_phone_rule")

    if (
        any(term in text for term in COMPANY_ADDRESS_TERMS)
        and not is_technical_ip_address_query(text)
        and not is_address_service_plan_lookup_query(text)
    ):
        return build_company_info_decision("company_address", "company_info_address_rule")

    if any(term in text for term in COMPANY_INFO_CLARIFY_TERMS):
        return build_company_info_clarify_decision(text, "company_info_location_clarify_rule")

    return None


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


def detect_ambiguous_short_query(text: str) -> Optional[Dict[str, Any]]:
    text = (text or "").strip()
    reply = AMBIGUOUS_TOPIC_REPLIES.get(text)

    if not reply:
        return None

    return validate_router_result({
        "route": "clarify",
        "intent": "ambiguous_short_query",
        "tool_name": None,
        "topic": text,
        "should_cancel_current_flow": False,
        "should_call_tool": False,
        "should_retrieve_knowledge": False,
        "knowledge_query": None,
        "reply": reply,
        "extracted_slots": {},
        "reason": "ambiguous_short_query",
    })


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
        "last_campaign_topic": memory.get("last_campaign_topic"),
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
            "tv_reactivation_status": known.get("tv_reactivation_status"),
            "tv_reactivation_message": known.get("tv_reactivation_message"),
            "last_value_added_topic": known.get("last_value_added_topic"),
        }
    }
    return json.dumps(data, ensure_ascii=False, indent=2)


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
    *,
    llm_first: bool = True,
) -> Dict[str, Any]:
    text = (user_input or "").strip()
    known = memory.get("known_info", {})
    is_active_flow_switch_check = bool(memory.get("_active_flow_switch_check"))
    guarded = dict(router or {})

    if llm_first:
        # Model decisions are authoritative for semantics.  The post-model
        # guard only normalizes the typed contract and blocks unsafe or
        # duplicate tool execution; it never reclassifies customer wording.
        if guarded.get("reason") == "model_router_unavailable":
            return validate_router_result(guarded)

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

        # A repair ticket changes the customer's service state. When a new
        # turn already describes a concrete device, TV, or network symptom,
        # complete the model-selected intent through the relevant diagnostic
        # SOP first. This is a tool-safety gate, not a keyword reply: the
        # customer still receives the LLM-routed troubleshooting flow and can
        # request repair after the initial checks fail.
        if (
            guarded.get("route") == "tool_action"
            and guarded.get("tool_name") == "create_repair_ticket"
            and known.get("troubleshooting_started") != "yes"
            and known.get("repair_ready") != "yes"
        ):
            guarded.update({
                "route": "troubleshooting",
                "tool_name": None,
                "should_call_tool": False,
                "should_retrieve_knowledge": False,
                "reply": "",
                "reason": "guard_initial_fault_requires_troubleshooting",
            })

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
            return build_human_handoff_request_decision(
                str(guarded.get("reason") or "llm_human_handoff_request"),
                topic=str(guarded.get("topic") or "真人客服"),
            )

        return validate_router_result(guarded)

    # The keyword-based compatibility guard is retired.  Callers that omit
    # model ownership receive schema normalization only; they cannot obtain a
    # semantic route or a customer-facing answer from this function.
    return validate_router_result(guarded)

    entity_confirmation = detect_knowledge_entity_confirmation(text)
    if entity_confirmation:
        return entity_confirmation

    if is_human_handoff_query(text):
        if has_human_handoff_issue_context(memory) or has_human_handoff_issue_details(text):
            return build_human_handoff_request_decision("guard_human_handoff_request")
        return build_human_handoff_triage_decision("guard_human_handoff_requires_issue")

    if is_human_handoff_confirmation_query(text):
        return build_human_handoff_triage_decision("guard_human_handoff_requires_issue")

    if is_contextual_website_page_request(text) and guarded.get("route") in {
        "company_info",
        "direct_reply",
        "unknown",
        "clarify",
        None,
        "",
    }:
        return build_contextual_website_page_decision(
            text,
            "guard_contextual_website_page_lookup",
        )

    service_device_limit = detect_service_device_limit_knowledge_query(text)
    if service_device_limit and guarded.get("route") in {
        "tool_action",
        "troubleshooting",
        "continue_current_flow",
    }:
        service_device_limit["reason"] = "guard_service_device_limit_over_channel_tool"
        return validate_router_result(service_device_limit)

    equipment_purchase_candidate = detect_equipment_purchase_knowledge_query(text)
    if equipment_purchase_candidate and guarded.get("route") in {"troubleshooting", "continue_current_flow"}:
        equipment_purchase_candidate["reason"] = "guard_equipment_purchase_over_fault"
        return validate_router_result(equipment_purchase_candidate)

    value_added_candidate = detect_value_added_product_knowledge_query(text)
    if value_added_candidate and guarded.get("route") in {"troubleshooting", "continue_current_flow"}:
        return build_clarify_decision(
            intent="value_added_product_or_fault_clarification",
            topic="加值產品或設備故障",
            reply="請問您是要查詢這項 WiFi 加值服務的內容或費用，還是 WiFi 設備目前無法使用？",
            reason="guard_product_fault_intent_conflict",
        )

    # A complete customer request must not be recast as an unspecified
    # add-on question merely because the preceding turn mentioned an add-on.
    direct_reply = detect_safe_direct_reply(text, memory)
    if direct_reply:
        return direct_reply

    if should_clarify_unspecified_value_added_service(text, guarded):
        return build_clarify_decision(
            intent="value_added_service_clarification",
            topic="加值服務",
            reply=VALUE_ADDED_SERVICE_CLARIFY_REPLY,
            reason="guard_unspecified_value_added_service_clarification",
        )

    if is_unsupported_bill_detail_query(text):
        return build_direct_reply_decision(
            intent="unsupported_bill_detail_lookup",
            topic="帳單期間與起訖日",
            reply=UNSUPPORTED_BILL_DETAIL_REPLY,
            reason="guard_unsupported_bill_detail_rule",
        )

    if is_human_handoff_query(text):
        if has_human_handoff_issue_context(memory) or has_human_handoff_issue_details(text):
            return build_human_handoff_request_decision("guard_human_handoff_request")
        return build_human_handoff_triage_decision("guard_human_handoff_requires_issue")

    # A tentative human-handoff phrase must be confirmed before promotion or
    # other deterministic rules inspect the same sentence.
    if is_human_handoff_confirmation_query(text):
        return build_human_handoff_triage_decision("guard_human_handoff_requires_issue")

    if is_bill_content_query(text):
        return build_bill_content_query_decision("guard_bill_content_query_rule")

    if (
        guarded.get("route") == "tool_action"
        and guarded.get("tool_name") == "bill_return_line_tv"
        and any(term in text for term in TV_AUTHORIZATION_TERMS)
    ):
        troubleshooting = detect_troubleshooting_query(text, memory)
        if troubleshooting:
            troubleshooting["reason"] = "guard_tv_authorization_not_reconnection"
            return validate_router_result(troubleshooting)

    if is_personal_service_fee_lookup_query(text):
        return build_tool_action_decision(
            intent="service_content_query",
            tool_name="search_contract_info",
            topic="目前服務費用查詢",
            reply="可以，我幫您查詢目前服務內容與合約資訊。",
            reason="guard_personal_service_fee_lookup_rule",
        )

    indexed_campaign = detect_indexed_campaign_activity_query(text, memory)
    if indexed_campaign:
        return indexed_campaign

    # 排錯中短句，一律交回 state machine；明確的人工作業或活動名稱
    # 已在上方先行處理，避免把使用者切換主題誤當成排錯回答。
    if known.get("troubleshooting_started") == "yes" and len(text) <= 6:
        guarded.update({
            "route": "continue_current_flow",
            "intent": "troubleshooting",
            "tool_name": None,
            "should_call_tool": False,
            "should_retrieve_knowledge": False,
            "knowledge_query": None,
            "reply": "",
            "reason": "guard_troubleshooting_short_reply",
        })
        return validate_router_result(guarded)

    troubleshooting = detect_troubleshooting_query(text, memory)
    if (
        troubleshooting
        and not is_active_flow_switch_check
        and guarded.get("route") in [None, "", "unknown", "clarify", "company_info", "direct_reply", "knowledge_query"]
    ):
        return troubleshooting

    direct_reply = detect_safe_direct_reply(text, memory)
    if direct_reply:
        return direct_reply

    if guarded.get("intent") == "human_handoff_triage":
        return build_human_handoff_triage_decision(
            guarded.get("reason") or "llm_human_handoff_triage",
        )

    if guarded.get("intent") in {"human_handoff_request", "human_agent"}:
        guarded.update({
            "route": "direct_reply",
            "intent": "human_handoff_request",
            "tool_name": None,
            "should_call_tool": False,
            "should_retrieve_knowledge": False,
            "knowledge_query": None,
            "reply": WEB_HUMAN_HANDOFF_REPLY,
            "reason": guarded.get("reason") or "llm_human_handoff_request",
        })
        return validate_router_result(guarded)

    if any(term in text for term in TV_AUTHORIZATION_TERMS):
        troubleshooting = detect_troubleshooting_query(text, memory)
        if troubleshooting:
            troubleshooting["reason"] = "guard_tv_authorization_not_reconnection"
            return troubleshooting

    if (
        guarded.get("route") == "tool_action"
        and guarded.get("tool_name") == "bill_return_line_tv"
        and any(term in text for term in TV_TROUBLESHOOTING_NOT_RECONNECTION_TERMS)
        and not any(term in text for term in RECONNECTION_INTENT_TERMS)
    ):
        direct_reply = detect_safe_direct_reply(text, memory)
        if direct_reply:
            return direct_reply

        troubleshooting = detect_troubleshooting_query(text, memory)
        if troubleshooting:
            troubleshooting["reason"] = "guard_tv_troubleshooting_not_reconnection"
            return troubleshooting

    payment_receipt = detect_payment_receipt_query(text, memory)
    if payment_receipt:
        return payment_receipt

    promotion_price_difference = detect_promotion_price_difference_query(text, memory)
    if promotion_price_difference:
        return promotion_price_difference

    cancel_tv_keep_internet = detect_cancel_tv_keep_internet_query(text, memory)
    if cancel_tv_keep_internet:
        return cancel_tv_keep_internet

    fixed_ip = detect_fixed_ip_knowledge_query(text, memory)
    if fixed_ip and guarded.get("route") in [None, "", "unknown", "company_info", "clarify"]:
        return fixed_ip

    promotion_activity = detect_promotion_activity_query(text, memory)
    if promotion_activity:
        return promotion_activity

    needs_rule_fallback = (
        guarded.get("route") in [None, "", "unknown"]
        and not is_active_flow_switch_check
    )

    if needs_rule_fallback:
        reconnection = detect_reconnection_query(text, memory)
        if reconnection:
            return reconnection

        mabow = detect_mabow_query(text, memory)
        if mabow:
            return mabow

        service_availability = detect_service_availability_query(text, memory)
        if service_availability:
            return service_availability

        troubleshooting = detect_troubleshooting_query(text, memory)
        if troubleshooting:
            return troubleshooting

        company_info = detect_company_info_query(text, memory)
        if company_info:
            return company_info

        ambiguous = detect_ambiguous_short_query(text)
        if ambiguous:
            return ambiguous

    if is_definition_query(text) and guarded.get("route") in [None, "", "unknown", "clarify"]:
        return build_definition_query_decision(
            text=text,
            reason="guard_definition_query",
        )

    if guarded.get("route") == "tool_action":
        if guarded.get("tool_name") not in SUPPORTED_TOOLS:
            guarded.update({
                "route": "unsupported_flow",
                "tool_name": None,
                "should_call_tool": False,
                "should_retrieve_knowledge": False,
                "reply": UNSUPPORTED_REPLY,
                "reason": "guard_unsupported_tool_action",
            })
            return validate_router_result(guarded)

    if guarded.get("route") == "unsupported_flow":
        guarded["tool_name"] = None
        guarded["should_call_tool"] = False
        guarded["should_retrieve_knowledge"] = False
        if not guarded.get("reply"):
            guarded["reply"] = UNSUPPORTED_REPLY
        return validate_router_result(guarded)

    if guarded.get("route") == "knowledge_query":
        guarded["tool_name"] = None
        guarded["should_call_tool"] = False
        guarded["should_retrieve_knowledge"] = True
        if not guarded.get("knowledge_query"):
            guarded["knowledge_query"] = text
        return validate_router_result(guarded)

    if guarded.get("route") == "unknown":
        guarded["reply"] = DEFAULT_UNKNOWN_REPLY
        return validate_router_result(guarded)

    return validate_router_result(guarded)


def fallback_router(user_input: str, memory: Dict[str, Any]) -> Dict[str, Any]:
    """Return a closed routing failure; semantic rule fallback is disabled."""
    return validate_router_result({
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

    # Historical implementation intentionally remains unreachable until its
    # old test fixtures are removed from the repository.
    text = (user_input or "").strip()

    entity_confirmation = detect_knowledge_entity_confirmation(text)
    if entity_confirmation:
        return entity_confirmation

    if is_human_handoff_query(text):
        if has_human_handoff_issue_context(memory) or has_human_handoff_issue_details(text):
            return build_human_handoff_request_decision("fallback_human_handoff_request")
        return build_human_handoff_triage_decision("fallback_human_handoff_requires_issue")

    if is_human_handoff_confirmation_query(text):
        return build_human_handoff_triage_decision("fallback_human_handoff_requires_issue")

    payment_receipt = detect_payment_receipt_query(text, memory)
    if payment_receipt:
        return payment_receipt

    direct_reply = detect_safe_direct_reply(text, memory)
    if direct_reply:
        return direct_reply

    equipment_purchase = detect_equipment_purchase_knowledge_query(text)
    if equipment_purchase:
        equipment_purchase["reason"] = "fallback_equipment_purchase_knowledge_rule"
        return validate_router_result(equipment_purchase)

    service_device_limit = detect_service_device_limit_knowledge_query(text)
    if service_device_limit:
        service_device_limit["reason"] = "fallback_service_device_limit_knowledge_rule"
        return validate_router_result(service_device_limit)

    troubleshooting = detect_troubleshooting_query(text, memory)
    if troubleshooting:
        return troubleshooting

    value_added_product = detect_value_added_product_knowledge_query(text)
    if value_added_product:
        value_added_product["reason"] = "fallback_value_added_product_knowledge_rule"
        return validate_router_result(value_added_product)

    promotion_price_difference = detect_promotion_price_difference_query(text, memory)
    if promotion_price_difference:
        return promotion_price_difference

    cancel_tv_keep_internet = detect_cancel_tv_keep_internet_query(text, memory)
    if cancel_tv_keep_internet:
        return cancel_tv_keep_internet

    fixed_ip = detect_fixed_ip_knowledge_query(text, memory)
    if fixed_ip:
        return fixed_ip

    promotion_activity = detect_promotion_activity_query(text, memory)
    if promotion_activity:
        return promotion_activity

    reconnection = detect_reconnection_query(text, memory)
    if reconnection:
        return reconnection

    mabow = detect_mabow_query(text, memory)
    if mabow:
        return mabow

    service_availability = detect_service_availability_query(text, memory)
    if service_availability:
        return service_availability

    if is_contextual_website_page_request(text):
        return build_contextual_website_page_decision(
            text,
            "fallback_contextual_website_page_lookup",
        )

    company_info = detect_company_info_query(text, memory)
    if company_info:
        return company_info

    ambiguous = detect_ambiguous_short_query(text)
    if ambiguous:
        return ambiguous

    if is_definition_query(text):
        return build_definition_query_decision(
            text=text,
            reason="fallback_definition_query",
        )

    smalltalk_reply = SMALLTALK_REPLIES.get(text.lower())
    if smalltalk_reply:
        return validate_router_result({
            "route": "smalltalk",
            "intent": "smalltalk",
            "tool_name": None,
            "topic": text,
            "should_cancel_current_flow": False,
            "should_call_tool": False,
            "should_retrieve_knowledge": False,
            "knowledge_query": None,
            "reply": smalltalk_reply,
            "extracted_slots": {},
            "reason": "fallback_smalltalk",
        })

    return validate_router_result({
        "route": "unknown",
        "intent": "other",
        "tool_name": None,
        "topic": text,
        "should_cancel_current_flow": False,
        "should_call_tool": False,
        "should_retrieve_knowledge": False,
        "knowledge_query": None,
        "reply": MODEL_ROUTER_UNAVAILABLE_REPLY,
        "extracted_slots": {},
        "reason": "fallback_safe_unknown",
    })


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


def detect_paper_bill_request_rule(
    text: str,
    memory: Optional[Dict[str, Any]] = None,
) -> Optional[Dict[str, Any]]:
    if not is_paper_bill_request(text):
        return None

    return build_direct_reply_decision(
        intent="paper_bill_request",
        topic="paper_bill",
        reply=PAPER_BILL_REQUEST_REPLY,
        reason="paper_bill_request_rule",
    )


def detect_active_flow_rule_interrupt(
    text: str,
    memory: Optional[Dict[str, Any]] = None,
    history: Optional[List[Dict[str, str]]] = None,
) -> Optional[Dict[str, Any]]:
    """Match only router rules that may replace an active customer flow."""
    memory = memory or {}
    history = history or []

    for detector in (
        lambda: detect_paper_bill_request_rule(text, memory),
        lambda: detect_company_info_interrupt_query(text, memory),
        lambda: detect_contextual_feedback_direct_reply(text, history, memory),
        lambda: detect_safe_direct_reply(text, memory),
    ):
        decision = detector()
        if decision:
            return decision

    return None


def detect_fault_rule(text: str, memory: Optional[Dict[str, Any]] = None) -> Optional[Dict[str, Any]]:
    memory = memory or {}
    known = memory.get("known_info", {})
    if (
        memory.get("pending_tool")
        or memory.get("_active_flow_switch_check")
        or known.get("troubleshooting_started") == "yes"
        or known.get("repair_followup_active") == "yes"
        or detect_equipment_purchase_knowledge_query(text)
        or detect_value_added_product_knowledge_query(text)
    ):
        return None

    direct_reply = detect_safe_direct_reply(text, memory)
    if direct_reply and direct_reply.get("intent") not in {"network_instability_scope_clarification"} and not (
        is_tv_authorization_issue(text)
        and direct_reply.get("intent")
        not in {"cnt_seasonal_authorization_paid", "general_channel_e004_authorization"}
    ):
        return None

    if is_fault(text) or is_direct_fault_report(text):
        return detect_troubleshooting_query(text, memory)

    return None


def detect_llm_failure_semantic_route(
    text: str,
    memory: Dict[str, Any],
    history: List[Dict[str, str]],
) -> Optional[Dict[str, Any]]:
    """Ground malformed model output in a flow, never in a canned answer."""
    compact = (text or "").replace(" ", "").replace("　", "").lower()
    recent = "".join(str(item.get("content") or "") for item in (history or [])[-8:])
    recent_compact = recent.replace(" ", "").replace("　", "").lower()

    if (
        "100m" in compact
        and any(term in compact for term in ("電視", "頻道"))
        and any(term in compact for term in ("多少錢", "費用", "月租", "一個月"))
    ):
        return build_clarify_decision(
            intent="existing_service_or_combo_plan_clarification",
            topic="100M 電視加網路費用",
            reply="請問您是想查詢目前合約的月費，還是想了解 100M 電視加網路的優惠方案？",
            reason="llm_failure_semantic_existing_service_or_combo_plan_clarification",
        )

    if any(term in compact for term in ("套餐", "全餐")) and re.search(r"[a-z]", text or "", flags=re.IGNORECASE):
        return build_knowledge_query_decision(
            intent="digital_tv_package_addon",
            topic="數位電視套餐",
            knowledge_query=f"{text} 數位電視套餐 加購流程 申請方式",
            reason="llm_failure_semantic_digital_package_retrieval",
        )

    if any(term in compact for term in ("500m", "500mbps")) and any(
        term in compact for term in ("費用", "多少錢", "價格", "價錢", "月租")
    ):
        return build_knowledge_query_decision(
            intent="broadband_500m_plan_price_query",
            topic="500M 寬頻方案費用",
            knowledge_query=f"{text} 一般寬頻 目前促銷方案 費用 月繳 季繳 半年繳 年繳",
            reason="llm_failure_semantic_500m_retrieval",
        )

    if any(term in compact for term in ("再高一階", "高一階", "升一階", "升級一階")):
        speed_matches = re.findall(
            r"(?:下載\s*)?(\d+)\s*(?:mbps|m)\s*/\s*(?:上傳\s*)?(\d+)\s*(?:mbps|m)",
            recent,
            flags=re.IGNORECASE,
        )
        current_speed = (
            f"目前速率 {speed_matches[-1][0]}M/{speed_matches[-1][1]}M"
            if speed_matches
            else ""
        )
        return build_knowledge_query_decision(
            intent="next_tier_plan_fee_guidance",
            topic="寬頻升級方案費用",
            knowledge_query=(
                f"{current_speed} {text} 目前可推廣寬頻方案 "
                "升級下一階速率 費用 方案內容 合約資格"
            ).strip(),
            reason="llm_failure_semantic_upgrade_retrieval",
        )

    if compact in {"2年的呢", "兩年的呢", "2年呢", "兩年呢"} and any(
        term in recent_compact for term in ("第四台", "有線電視", "收視費")
    ):
        return build_knowledge_query_decision(
            intent="basic_tv_two_year_fee_query",
            topic="第四台兩年繳費用",
            knowledge_query="第四台 有線電視 兩年繳 收視費 裝機費",
            reason="llm_failure_semantic_tv_two_year_retrieval",
        )

    if any(term in compact for term in ("300kbps", "網速", "網路速度")) and any(
        term in compact for term in ("維修", "報修", "人員", "慢")
    ):
        return build_troubleshooting_decision(text, "llm_failure_semantic_network_repair")

    if compact in {"如何申請", "怎麼申請", "申請方式", "如何辦理", "怎麼辦理"} and any(
        term in recent_compact for term in ("優惠", "方案", "促銷")
    ):
        return build_human_handoff_request_decision(
            "llm_failure_semantic_promotion_application_handoff",
            topic="優惠方案申請",
        )

    if any(term in compact for term in ("年繳", "全部費用", "總費用")) and any(
        term in recent_compact for term in ("優惠", "方案", "促銷")
    ):
        recent_customer_topics = [
            str(item.get("content") or "").strip()
            for item in history or []
            if str(item.get("role") or "").lower() == "user"
            and str(item.get("content") or "").strip()
        ]
        topic_anchor = recent_customer_topics[-1] if recent_customer_topics else ""
        return build_knowledge_query_decision(
            intent="campaign_payment_detail",
            topic="目前方案費用",
            knowledge_query=f"{topic_anchor} {text} 年繳 全部費用 裝機費",
            reason="llm_failure_semantic_campaign_fee_retrieval",
        )

    return None


def detect_digital_tv_package_knowledge_guard(
    text: str,
    router: Dict[str, Any],
) -> Optional[Dict[str, Any]]:
    """Keep an unresolved package-purchase intent in the digital-TV KB flow.

    This runs only after the LLM has evaluated the message and only repairs an
    unresolved clarification/unknown result. It deliberately returns a
    knowledge-query contract, never a customer-facing canned answer.
    """
    if str(router.get("route") or "") not in {"unknown", "clarify"}:
        return None

    compact = (text or "").replace(" ", "").replace("　", "").casefold()
    generic_package_purchase = compact in {
        "套餐如何加購",
        "套餐怎麼加購",
        "套餐怎麼購買",
        "如何加購套餐",
        "套餐購買流程",
    }
    named_full_package = (
        "全餐" in compact
        and bool(re.search(r"[a-z]", text or "", flags=re.IGNORECASE))
    )
    if not (generic_package_purchase or named_full_package):
        return None

    subject = str(text or "").strip() if named_full_package else "數位電視頻道套餐"
    return build_knowledge_query_decision(
        intent="digital_tv_package_addon",
        topic="數位電視套餐",
        knowledge_query=(
            f"{subject} 數位電視套餐 數位電視頻道套餐 加購流程 聯網機上盒 非聯網機上盒"
        ),
        reason="llm_guard_digital_tv_package_addon_retrieval",
    )


def detect_convenience_store_payment_machine_guard(
    text: str,
    router: Dict[str, Any],
) -> Optional[Dict[str, Any]]:
    """Send an unresolved convenience-store payment request to the machine SOP."""
    if str(router.get("route") or "") not in {"unknown", "clarify"}:
        return None

    compact = (text or "").replace(" ", "").replace("　", "")
    if compact not in {
        "無法在便利商店繳費",
        "無法在超商繳費",
        "超商繳費不會操作",
        "便利商店繳費不會操作",
    }:
        return None

    return build_knowledge_query_decision(
        intent="convenience_store_payment_machine_guide",
        topic="超商繳費機操作",
        knowledge_query=(
            "IBON FamiPort ibon famiport 超商繳費機 便利商店機台 "
            "繳費教學 操作流程 7-Eleven 全家"
        ),
        reason="llm_guard_convenience_store_payment_machine_retrieval",
    )


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
        regional_policy_rules = build_policy_prompt(
            memory,
            (
                "promotion.social_discount_stacking",
                "promotion.discount_stacking_caution",
                "promotion.hidden_plan_visibility",
                "promotion.non_promoted_1g_plan",
                "promotion.low_income_500m_year_fee",
                "billing.next_bill_after_no_unpaid",
                "billing.past_payment_record",
                "billing.payment_not_posted",
                "billing.store_payment_still_billed",
                "support.remote_control_price",
            ),
        )
        response = (prompt | llm).invoke({
            "rules": f"{INTENT_ROUTER_RULES}\n\n{regional_policy_rules}",
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
                llm_first=True,
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
    return router_guard(
        user_input,
        memory,
        fallback_decision,
        llm_first=True,
    )
