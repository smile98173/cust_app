from copy import deepcopy
from typing import Any, Dict, Optional

from app.services.tool_manager import get_available_functions


TOOL_CATALOG = {
    item["name"]: item
    for item in get_available_functions({})
}

SUPPORTED_TOOLS = frozenset(TOOL_CATALOG.keys())

ROUTE_DESCRIPTIONS = {
    "continue_current_flow": "延續目前流程，例如排錯、補資料、等待用戶回覆",
    "switch_topic": "使用者明顯切換話題",
    "troubleshooting": "使用者回報故障，需要進入排錯",
    "tool_action": "使用者要執行已支援工具",
    "knowledge_query": "使用者問知識、優惠、規定、流程、產品介紹",
    "company_info": "使用者詢問目前系統台的公司地址、服務地區、營業時間、電話、官網或網址",
    "direct_reply": "模型判斷可直接回覆，不需 RAG 或工具",
    "clarify": "使用者意圖模糊，需要反問",
    "unsupported_flow": "使用者要求代辦未支援流程，不能自行辦理",
    "smalltalk": "問候、感謝、結束對話",
    "unknown": "無法判斷",
}

ROUTE_DECISION_TYPES = {
    "smalltalk": "smalltalk",
    "knowledge_query": "faq_answer",
    "company_info": "direct_reply",
    "direct_reply": "direct_reply",
    "tool_action": "tool_call",
    "troubleshooting": "direct_reply",
    "continue_current_flow": "direct_reply",
    "switch_topic": "faq_answer",
    "clarify": "clarify",
    "unsupported_flow": "direct_reply",
}

UNSUPPORTED_REPLY = (
    "這項服務目前我無法直接代為辦理。"
    "我可以先幫您查詢相關說明，或建議您聯繫客服人員確認。"
)

DEFAULT_UNKNOWN_REPLY = (
    "不好意思，我無法理解您的問題，請重新提問。"
)

# This is deliberately distinct from an ordinary unclear question. It is only
# used when the LLM router itself cannot be reached or cannot return a valid
# decision, so legacy keyword rules never answer in its place.
MODEL_ROUTER_UNAVAILABLE_REPLY = (
    "系統暫時無法判讀您的需求，請稍後再試。"
)

SMALLTALK_REPLIES = {
    "你好": "您好，請問今天需要我協助帳單、網路，還是電視相關問題呢？",
    "您好": "您好，請問今天需要我協助帳單、網路，還是電視相關問題呢？",
    "hi": "您好，請問今天需要我協助帳單、網路，還是電視相關問題呢？",
    "hello": "您好，請問今天需要我協助帳單、網路，還是電視相關問題呢？",
    "謝謝": "不客氣，若還有其他問題，也可以再告訴我。",
    "感謝": "不客氣，若還有其他問題，也可以再告訴我。",
}

AMBIGUOUS_TOPIC_REPLIES = {
    "帳單": "請問您是想查詢帳單金額、補寄帳單，還是詢問繳費方式呢？",
    "帳務": "請問您是想查詢帳單、繳費、補寄帳單，還是其他帳務問題呢？",
    "繳費": "請問您是想查詢繳費方式、確認是否繳費成功，還是申請繳費後復線呢？",
    "紅利": "請問您是想了解紅利點數規則、查詢點數，還是兌換方式呢？",
    "紅利點數": "請問您是想了解紅利點數規則、查詢點數，還是兌換方式呢？",
    "網路": "請問您是想詢問網路方案、網路故障、網速問題，還是繳費後恢復網路呢？",
    "寬頻": "請問您是想了解寬頻方案、網路故障，還是網速相關問題呢？",
    "電視": "請問您是想詢問電視方案、機上盒問題、電視不能看，還是繳費後恢復電視呢？",
    "第四台": "請問您是想詢問電視方案、機上盒問題、頻道問題，還是電視不能看呢？",
    "報修": "請問您是要報修電視、網路，還是其他設備問題呢？",
    "優惠": "請問您是想了解網路優惠、電視優惠，還是目前促銷方案呢？",
    "方案": "請問您是想了解網路方案、電視方案，還是加值服務方案呢？",
    "公司資訊": "請問您是想知道公司地址、服務地區範圍、營業時間，還是客服電話呢？",
}

TOPIC_WORDS = frozenset(AMBIGUOUS_TOPIC_REPLIES.keys())

BILLING_OPTIONS = {
    "查詢帳單金額": {
        "route": "tool_action",
        "tool_name": "search_bill",
        "reply": "可以，我幫您查詢帳單。",
    },
    "補寄帳單": {
        "route": "tool_action",
        "tool_name": "send_message",
        "reply": "可以，我幫您補發簡訊帳單。",
    },
    "繳費方式": {
        "route": "knowledge_query",
        "knowledge_query": "繳費方式",
        "reply": "我幫您查詢繳費方式。",
    },
}

CLARIFY_CONTEXTS = {
    "帳單": {"options": BILLING_OPTIONS},
    "帳務": {"options": BILLING_OPTIONS},
    "繳費": {
        "options": {
            "繳費方式": {
                "route": "knowledge_query",
                "knowledge_query": "繳費方式",
                "reply": "我幫您查詢繳費方式。",
            },
            "確認是否繳費成功": {
                "route": "tool_action",
                "tool_name": "search_bill",
                "reply": "可以，我幫您查詢帳單狀態。",
            },
            "繳費後復線": {
                "route": "clarify",
                "reply": "請問您是要恢復網路服務，還是恢復電視服務呢？",
            },
        }
    },
    "復線服務類型": {
        "options": {
            "網路復線": {
                "route": "tool_action",
                "tool_name": "bill_return_line_internet",
                "reply": "可以，我幫您送出網路復機申請。",
            },
            "電視復線": {
                "route": "tool_action",
                "tool_name": "bill_return_line_tv",
                "reply": "可以，我幫您送出電視復機申請。",
            },
        }
    },
    "一般頻道 E004 暫復確認": {
        "options": {
            "要暫復": {
                "route": "tool_action",
                "tool_name": "bill_return_line_tv",
                "reply": "可以，我幫您處理電視暫時復線。",
            },
            "暫時不要": {
                "route": "direct_reply",
                "reply": "好的。完成繳費後若仍無法收看，請再告訴我，我會協助您確認後續處理方式。",
            },
        }
    },
    "月租查詢類型": {
        "options": {
            "查詢帳單": {
                "route": "tool_action",
                "tool_name": "search_bill",
                "reply": "可以，我幫您查詢目前待繳帳單金額。",
            },
            "查詢合約內容": {
                "route": "tool_action",
                "tool_name": "search_contract_info",
                "reply": "可以，我幫您查詢目前服務內容與合約資訊。",
            },
        }
    },
    "加值服務": {
        "options": {
            "LINE TV": {
                "route": "knowledge_query",
                "intent": "value_added_product_query",
                "knowledge_query": "LINE TV 加值服務 原價 月租 半年繳 年繳 費用 申辦方式 限制條件",
                "reply": "",
            },
            "WiFi 加值服務": {
                "route": "knowledge_query",
                "intent": "value_added_product_query",
                "knowledge_query": (
                    "WiFi 加值服務 WiFi 5 WiFi 6 Mesh 分享器 "
                    "月租 半年繳 年繳 費用 申辦方式 設備賠償"
                ),
                "reply": "",
            },
            "居家智慧攝影機": {
                "route": "knowledge_query",
                "intent": "value_added_product_query",
                "knowledge_query": (
                    "居家智慧攝影機 智慧鏡頭 攝影機租借 "
                    "半年繳 年繳 費用 申辦方式 限制條件"
                ),
                "reply": "",
            },
            "熊搭心": {
                "route": "knowledge_query",
                "intent": "value_added_product_query",
                "knowledge_query": (
                    "熊搭心 瑪帛用戶 瑪帛好友 瑪帛夥伴 "
                    "電視電話 家庭相簿 生活提醒 月租 半年繳 年繳"
                ),
                "reply": "",
            },
            "全部加值服務": {
                "route": "knowledge_query",
                "intent": "value_added_service_query",
                "knowledge_query": (
                    "各項單品銷售 加值服務 LINE TV WiFi 5 WiFi 6 Mesh "
                    "居家智慧攝影機 熊搭心 月租 半年繳 年繳 費用"
                ),
                "reply": "",
            },
        }
    },
    "網路": {
        "options": {
            "網路方案": {
                "route": "knowledge_query",
                "knowledge_query": "網路方案",
                "reply": "我幫您查詢網路方案。",
            },
            "網路故障": {
                "route": "troubleshooting",
                "reply": "",
            },
            "網速問題": {
                "route": "knowledge_query",
                "knowledge_query": "網速問題處理方式",
                "reply": "我幫您查詢網速問題的處理方式。",
            },
            "網路復線": {
                "route": "tool_action",
                "tool_name": "bill_return_line_internet",
                "reply": "可以，我幫您送出網路復機申請。",
            },
        }
    },
    "寬頻": {
        "options": {
            "網路方案": {
                "route": "knowledge_query",
                "knowledge_query": "網路方案",
                "reply": "我幫您查詢網路方案。",
            },
            "網路故障": {
                "route": "troubleshooting",
                "reply": "",
            },
            "網速問題": {
                "route": "knowledge_query",
                "knowledge_query": "網速問題處理方式",
                "reply": "我幫您查詢網速問題的處理方式。",
            },
            "網路復線": {
                "route": "tool_action",
                "tool_name": "bill_return_line_internet",
                "reply": "可以，我幫您送出網路復機申請。",
            },
        }
    },
    "電視": {
        "options": {
            "電視方案": {
                "route": "knowledge_query",
                "knowledge_query": "電視方案",
                "reply": "我幫您查詢電視方案。",
            },
            "機上盒問題": {
                "route": "troubleshooting",
                "reply": "",
            },
            "電視不能看": {
                "route": "troubleshooting",
                "reply": "",
            },
            "電視復線": {
                "route": "tool_action",
                "tool_name": "bill_return_line_tv",
                "reply": "可以，我幫您送出電視復機申請。",
            },
        }
    },
    "第四台": {
        "options": {
            "電視方案": {
                "route": "knowledge_query",
                "knowledge_query": "電視方案",
                "reply": "我幫您查詢電視方案。",
            },
            "機上盒問題": {
                "route": "troubleshooting",
                "reply": "",
            },
            "電視不能看": {
                "route": "troubleshooting",
                "reply": "",
            },
            "電視復線": {
                "route": "tool_action",
                "tool_name": "bill_return_line_tv",
                "reply": "可以，我幫您送出電視復機申請。",
            },
        }
    },
    "紅利": {
        "options": {
            "紅利點數規則": {
                "route": "knowledge_query",
                "knowledge_query": "紅利點數規則",
                "reply": "我幫您查詢紅利點數規則。",
            },
            "查詢點數": {
                "route": "unsupported_flow",
                "reply": "目前我無法直接查詢紅利點數。您可以透過官方客服或會員專區確認點數資訊。",
            },
            "兌換方式": {
                "route": "knowledge_query",
                "knowledge_query": "紅利點數兌換方式",
                "reply": "我幫您查詢紅利點數兌換方式。",
            },
        }
    },
    "紅利點數": {
        "options": {
            "紅利點數規則": {
                "route": "knowledge_query",
                "knowledge_query": "紅利點數規則",
                "reply": "我幫您查詢紅利點數規則。",
            },
            "查詢點數": {
                "route": "unsupported_flow",
                "reply": "目前我無法直接查詢紅利點數。您可以透過官方客服或會員專區確認點數資訊。",
            },
            "兌換方式": {
                "route": "knowledge_query",
                "knowledge_query": "紅利點數兌換方式",
                "reply": "我幫您查詢紅利點數兌換方式。",
            },
        }
    },
    "優惠": {
        "options": {
            "網路優惠": {
                "route": "company_info",
                "topic": "promotion_activity",
                "reply": "我幫您查詢目前優惠活動。",
            },
            "電視優惠": {
                "route": "company_info",
                "topic": "promotion_activity",
                "reply": "我幫您查詢目前優惠活動。",
            },
            "促銷方案": {
                "route": "company_info",
                "topic": "promotion_activity",
                "reply": "我幫您查詢目前優惠活動。",
            },
        }
    },
    "方案": {
        "options": {
            "網路優惠": {
                "route": "company_info",
                "topic": "promotion_activity",
                "reply": "我幫您查詢目前優惠活動。",
            },
            "電視優惠": {
                "route": "company_info",
                "topic": "promotion_activity",
                "reply": "我幫您查詢目前優惠活動。",
            },
            "促銷方案": {
                "route": "company_info",
                "topic": "promotion_activity",
                "reply": "我幫您查詢目前優惠活動。",
            },
        }
    },
    "優惠方案服務類型": {
        "options": {
            "有線電視＋網路": {
                "route": "knowledge_query",
                "intent": "tv_network_install_plan_query",
                "topic": "電視+網路方案",
                "promotion_scope": "tv_network",
                "promotion_query_kind": "catalog",
                "social_discount_requested": False,
                "knowledge_query": (
                    "同時申裝有線電視與寬頻網路 電視+網路方案 電視網路同裝方案 "
                    "方案名稱 活動期間 速率 月租 贈品 裝機費 違約金"
                ),
                "reply": "",
            },
            "純網路": {
                "route": "knowledge_query",
                "intent": "pure_network_install_plan_query",
                "topic": "純網方案",
                "promotion_scope": "pure_network",
                "promotion_query_kind": "catalog",
                "social_discount_requested": False,
                "knowledge_query": (
                    "目前有效的純網方案總覽 純網方案 一般寬頻方案 單辦寬頻 單辦網路 "
                    "方案名稱 服務類型 活動期間 排除電視同裝與社福優惠"
                ),
                "reply": "",
            },
            "純有線電視": {
                "route": "knowledge_query",
                "intent": "pure_tv_promotion_query",
                "topic": "單辦有線電視優惠",
                "promotion_scope": "pure_tv",
                "promotion_query_kind": "catalog",
                "social_discount_requested": False,
                "knowledge_query": (
                    "純有線電視 單辦有線電視 第四台 基本收費標準 基本收視費 "
                    "月繳 季繳 半年繳 年繳 裝機費"
                ),
                "reply": "",
            },
        }
    },
    "方案轉換目標": {
        "prompt": "請問您想轉換成哪一類新方案？",
        "options": {
            "純網路": {
                "route": "knowledge_query",
                "intent": "pure_network_install_plan_query",
                "topic": "純網方案",
                "promotion_scope": "pure_network",
                "promotion_query_kind": "catalog",
                "social_discount_requested": False,
                "knowledge_query": (
                    "目前有效的純網方案總覽 純網方案 一般寬頻方案 單辦寬頻 單辦網路 "
                    "方案名稱 服務類型 活動期間 排除電視同裝與社福優惠"
                ),
                "reply": "",
            },
            "純有線電視": {
                "route": "knowledge_query",
                "intent": "pure_tv_promotion_query",
                "topic": "單辦有線電視優惠",
                "promotion_scope": "pure_tv",
                "promotion_query_kind": "catalog",
                "social_discount_requested": False,
                "knowledge_query": (
                    "純有線電視 單辦有線電視 第四台 基本收費標準 基本收視費 "
                    "月繳 季繳 半年繳 年繳 裝機費"
                ),
                "reply": "",
            },
            "有線電視＋網路": {
                "route": "knowledge_query",
                "intent": "tv_network_install_plan_query",
                "topic": "電視+網路方案",
                "promotion_scope": "tv_network",
                "promotion_query_kind": "catalog",
                "social_discount_requested": False,
                "knowledge_query": (
                    "同時申裝有線電視與寬頻網路 電視+網路方案 電視網路同裝方案 "
                    "方案名稱 活動期間 速率 月租 贈品 裝機費 違約金"
                ),
                "reply": "",
            },
            "已有指定方案": {
                "route": "clarify",
                "intent": "named_plan_clarification",
                "topic": "指定方案名稱",
                "reply": "請輸入想更換的方案名稱。",
            },
        },
    },
    "公司資訊": {
        "options": {
            "公司地址": {
                "route": "company_info",
                "reply": "",
                "topic": "company_address",
            },
            "服務地區範圍": {
                "route": "company_info",
                "reply": "",
                "topic": "service_area",
            },
            "營業時間": {
                "route": "company_info",
                "reply": "",
                "topic": "business_hours",
            },
            "客服電話": {
                "route": "company_info",
                "reply": "",
                "topic": "contact_phone",
            },
        }
    },
}

CLARIFY_ALIASES = {
    "金額": "查詢帳單金額",
    "查金額": "查詢帳單金額",
    "查帳單": "查詢帳單金額",
    "查詢帳單": "查詢帳單金額",
    "帳單金額": "查詢帳單金額",
    "補寄": "補寄帳單",
    "補發": "補寄帳單",
    "補寄帳單": "補寄帳單",
    "補發帳單": "補寄帳單",
    "繳費方式": "繳費方式",
    "怎麼繳費": "繳費方式",
    "如何繳費": "繳費方式",
    "繳款方式": "繳費方式",
    "繳款方式查詢": "繳費方式",
    "付款方式": "繳費方式",
    "付款方式查詢": "繳費方式",
    "怎麼付款": "繳費方式",
    "如何付款": "繳費方式",
    "要怎麼付款": "繳費方式",
    "復線": "繳費後復線",
    "恢復服務": "繳費後復線",
    "網路故障": "網路故障",
    "網路不能用": "網路故障",
    "網路壞了": "網路故障",
    "網路方案": "網路方案",
    "網速": "網速問題",
    "網速問題": "網速問題",
    "電視不能看": "電視不能看",
    "電視壞了": "電視不能看",
    "機上盒": "機上盒問題",
    "機上盒問題": "機上盒問題",
    "電視方案": "電視方案",
    "電視復線": "電視復線",
    "恢復電視": "電視復線",
    "網路復線": "網路復線",
    "恢復網路": "網路復線",
    "帳單": "查詢帳單",
    "查帳單": "查詢帳單",
    "查詢帳單": "查詢帳單",
    "合約": "查詢合約內容",
    "合約內容": "查詢合約內容",
    "查合約": "查詢合約內容",
    "紅利規則": "紅利點數規則",
    "點數規則": "紅利點數規則",
    "查點數": "查詢點數",
    "查詢點數": "查詢點數",
    "兌換": "兌換方式",
    "兌換方式": "兌換方式",
    "網路優惠": "網路優惠",
    "電視優惠": "電視優惠",
    "促銷": "促銷方案",
    "促銷方案": "促銷方案",
    "有線電視+網路": "有線電視＋網路",
    "有線電視＋網路": "有線電視＋網路",
    "電視加網路": "有線電視＋網路",
    "電視+網路": "有線電視＋網路",
    "電視＋網路": "有線電視＋網路",
    "第四台加網路": "有線電視＋網路",
    "純網": "純網路",
    "純網路": "純網路",
    "純寬頻": "純網路",
    "單一網路": "純網路",
    "單純網路": "純網路",
    "純有線": "純有線電視",
    "純有線電視": "純有線電視",
    "純電視": "純有線電視",
    "純TV": "純有線電視",
    "只要有線電視": "純有線電視",
    "只看第四台": "純有線電視",
    "地址": "公司地址",
    "公司地址": "公司地址",
    "在哪": "公司地址",
    "在哪裡": "公司地址",
    "在哪邊": "公司地址",
    "位置": "公司地址",
    "服務範圍": "服務地區範圍",
    "服務區域": "服務地區範圍",
    "服務地區": "服務地區範圍",
    "經營區": "服務地區範圍",
    "營業時間": "營業時間",
    "客服電話": "客服電話",
    "電話": "客服電話",
    "linetv": "LINE TV",
    "LINE TV": "LINE TV",
    "line tv": "LINE TV",
    "wifi": "WiFi 加值服務",
    "WiFi": "WiFi 加值服務",
    "wi-fi": "WiFi 加值服務",
    "分享器": "WiFi 加值服務",
    "mesh": "WiFi 加值服務",
    "攝影機": "居家智慧攝影機",
    "居家攝影機": "居家智慧攝影機",
    "智慧攝影機": "居家智慧攝影機",
    "熊搭心": "熊搭心",
    "熊大心": "熊搭心",
    "全部": "全部加值服務",
    "全部加值服務": "全部加值服務",
    "所有加值服務": "全部加值服務",
    "都想看": "全部加值服務",
}


CONTEXTUAL_CLARIFY_FALLBACKS = {
    "網路": [
        {
            "keywords": ("金額", "費用", "價格", "價錢", "月租", "多少錢"),
            "reply": "請問您是想了解網路方案的月租費用，還是要查詢目前帳單金額呢？",
            "next_context": {
                "topic": "網路金額",
                "options": {
                    "網路方案月租": {
                        "route": "knowledge_query",
                        "knowledge_query": "網路方案 費用 月租",
                        "reply": "我幫您查詢網路方案月租費用。",
                    },
                    "查詢帳單金額": {
                        "route": "tool_action",
                        "tool_name": "search_bill",
                        "reply": "可以，我幫您查詢帳單。",
                    },
                },
            },
        },
    ],
    "寬頻": [
        {
            "keywords": ("金額", "費用", "價格", "價錢", "月租", "多少錢"),
            "reply": "請問您是想了解寬頻方案的月租費用，還是要查詢目前帳單金額呢？",
            "next_context": {
                "topic": "網路金額",
                "options": {
                    "網路方案月租": {
                        "route": "knowledge_query",
                        "knowledge_query": "網路方案 費用 月租",
                        "reply": "我幫您查詢網路方案月租費用。",
                    },
                    "查詢帳單金額": {
                        "route": "tool_action",
                        "tool_name": "search_bill",
                        "reply": "可以，我幫您查詢帳單。",
                    },
                },
            },
        },
    ],
}

CONTEXTUAL_CLARIFY_ALIASES = {
    "月租": "網路方案月租",
    "費用": "網路方案月租",
    "價格": "網路方案月租",
    "價錢": "網路方案月租",
    "多少錢": "網路方案月租",
    "方案費用": "網路方案月租",
    "網路月租": "網路方案月租",
    "寬頻月租": "網路方案月租",
    "網路方案費用": "網路方案月租",
    "查帳單金額": "查詢帳單金額",
    "查詢帳單金額": "查詢帳單金額",
    "帳單金額": "查詢帳單金額",
    "帳單": "查詢帳單金額",
}


def get_clarify_context(topic: Optional[str]) -> Optional[Dict[str, Any]]:
    if not topic or topic not in CLARIFY_CONTEXTS:
        return None

    context = deepcopy(CLARIFY_CONTEXTS[topic])
    context["topic"] = topic
    options = context.get("options")
    if isinstance(options, dict):
        for index, option in enumerate(options.values(), start=1):
            if isinstance(option, dict):
                option["option_id"] = f"option_{index}"
    return context


def match_contextual_clarify_fallback(
    user_text: str,
    context: Dict[str, Any],
) -> Optional[Dict[str, Any]]:
    text = (user_text or "").strip()
    topic = context.get("topic")

    if not text or not topic:
        return None

    for rule in CONTEXTUAL_CLARIFY_FALLBACKS.get(topic, []):
        if not any(keyword in text for keyword in rule.get("keywords", ())):
            continue

        return {
            "route": "clarify",
            "topic": topic,
            "reply": rule.get("reply", "請問您想選擇哪一項服務呢？"),
            "next_clarify_context": deepcopy(rule.get("next_context")),
            "matched_option": "__contextual_fallback__",
        }

    return None


def match_clarify_option(
    user_text: str,
    context: Dict[str, Any],
) -> Optional[Dict[str, Any]]:
    text = (user_text or "").strip()
    options = context.get("options", {})

    option_key = CONTEXTUAL_CLARIFY_ALIASES.get(text) or CLARIFY_ALIASES.get(text)

    if not option_key and text.isdigit():
        index = int(text) - 1
        option_keys = list(options.keys())
        if 0 <= index < len(option_keys):
            option_key = option_keys[index]

    if not option_key:
        for key in options.keys():
            if key in text or text in key:
                option_key = key
                break

    if not option_key or option_key not in options:
        return None

    selected = dict(options[option_key])
    selected["matched_option"] = option_key
    selected["topic"] = selected.get("topic") or context.get("topic")
    return selected
