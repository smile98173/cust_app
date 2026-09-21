from typing import Any, Optional

from langchain_core.prompts import ChatPromptTemplate

from app.services.company_profile import DEFAULT_TV_CABLE, build_company_context
from app.services.kb_answer_guard import (
    extract_definition_subject,
    is_definition_query,
    normalize_text,
)


BLOCKED_GENERAL_FALLBACK_TERMS = (
    "如何",
    "怎麼",
    "怎樣",
    "申請",
    "辦理",
    "設定",
    "操作",
    "步驟",
    "流程",
    "費用",
    "多少錢",
    "價格",
    "月租",
    "優惠",
    "方案",
    "訂購",
    "加購",
    "退租",
    "移機",
    "復線",
    "報修",
    "故障",
    "不能",
    "無法",
    "可不可以",
    "可以嗎",
    "能不能",
    "有沒有",
    "網路分享",
    "分享網路",
    "帳單",
    "繳費",
)

GENERAL_KNOWLEDGE_PROMPT = """
你是台灣有線電視與寬頻客服中心的輔助說明助手。

目前公司知識庫沒有足夠明確的資料可以回答使用者問題。
你可以只用一般常識回答低風險的概念或定義題。

目前服務公司資訊：
{company_context}

回答規則：
- 只能使用繁體中文。
- 回答要簡短，2 到 4 句即可。
- 回覆一般使用者時，不可出現 API、RAG、知識庫、檢索、模型、向量、chunk 等內部技術或資料來源用語。
- 不可使用 CATV、STB、BB 等業內縮寫，請分別改寫為有線電視、數位機上盒、寬頻網路。
- 只有可確認為通用技術或生活概念的名詞，第一段才以「依一般理解，」開頭。
- 若名詞可能是品牌、活動、方案或公司服務的專有名稱，但目前資料不足以確認，不可依字面、諧音或自行聯想解釋；請只回覆「GENERAL_FALLBACK_NOT_ALLOWED」。
- 必須明確說明這不是公司官方服務承諾。
- 不可以提供申請、設定、報修、費用、優惠、方案、公司規定或保證性說法。
- 如果是設備或服務名詞，只能說明一般概念，不要臆測具體支援功能。
- 不要要求使用者輸入或回覆「真人客服」、「人工客服」、「轉真人」等固定關鍵字；目前由 AI 依使用者語意自動判斷是否需要轉接。
- 如果題目不是一般概念題，請只回覆「GENERAL_FALLBACK_NOT_ALLOWED」。

使用者問題：
{user_input}
"""


UNSUPPORTED_NAME_GUESS_MARKERS = (
    "可能是以",
    "可能是品牌",
    "可能是活動",
    "可能是方案",
    "可能是服務",
    "像是品牌",
    "像是活動",
    "像是方案",
    "像是服務",
    "諧音",
)


def is_general_knowledge_fallback_allowed(user_input: str) -> bool:
    text = normalize_text(user_input)

    if not text:
        return False

    if not is_definition_query(user_input):
        return False

    if not extract_definition_subject(user_input):
        return False

    return not any(term in text for term in BLOCKED_GENERAL_FALLBACK_TERMS)


def build_general_knowledge_reply(
    user_input: str,
    llm: Any,
    memory: Optional[dict] = None,
) -> Optional[str]:
    if not is_general_knowledge_fallback_allowed(user_input):
        return None

    try:
        company_code = (memory or {}).get("company_code", DEFAULT_TV_CABLE)
        prompt = ChatPromptTemplate.from_template(GENERAL_KNOWLEDGE_PROMPT)
        chain = prompt | llm
        resp = chain.invoke({
            "company_context": build_company_context(company_code),
            "user_input": user_input,
        })
        text = (getattr(resp, "content", "") or "").strip()
    except Exception:
        return None

    if not text or "GENERAL_FALLBACK_NOT_ALLOWED" in text:
        return None

    # A no-hit fallback must not invent a definition for a possible company
    # product, campaign or service name.  If the model still guesses from the
    # wording, reject it and let the caller return the explicit no-data reply.
    if any(marker in text for marker in UNSUPPORTED_NAME_GUESS_MARKERS):
        return None

    if not text.startswith("依一般理解，"):
        text = f"依一般理解，{text}"

    disclaimer = "實際功能與可用服務仍以您家中設備型號及公司提供資訊為準。"
    if disclaimer not in text:
        text = f"{text}\n\n{disclaimer}"

    return text
