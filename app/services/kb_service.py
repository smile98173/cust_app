import csv
import json
import re
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

import requests

from app.config.settings import (
    NETWORK_ISSUE_TYPES,
    RAG_API_INCLUDE_EXPIRED,
    RAG_API_TIMEOUT_SECONDS,
    RAG_API_URL,
    RAG_BACKEND,
    RAG_LOCAL_COLLECTION,
    RAG_LOCAL_DOCS_DIR,
    RAG_LOCAL_EMBED_DEVICE,
    RAG_LOCAL_EMBED_MODEL,
    RAG_LOCAL_MANIFEST_PATH,
    RAG_LOCAL_MAX_DISTANCE,
    RAG_LOCAL_PERSIST_DIR,
)
from app.services.company_profile import TV_DICT
from app.services.knowledge_base_policy import (
    CENTRAL_COMMON_KNOWLEDGE_BASE,
    LEGACY_COMMON_KNOWLEDGE_BASE,
    REGIONAL_COMMON_KNOWLEDGE_BASES,
    REGIONAL_COMMON_MEMBERS,
    normalize_knowledge_base_name,
    retrieval_common_knowledge_bases,
)
from app.services.regional_policy import resolve_policy_context
from app.services.web_account_service import WebAccountService


COMMON_RAG_KNOWLEDGE_BASE = LEGACY_COMMON_KNOWLEDGE_BASE
DEFAULT_RAG_KNOWLEDGE_BASE = COMMON_RAG_KNOWLEDGE_BASE
COMMON_SCOPE_SERVICE = WebAccountService()

CAMPAIGN_OCCASION_ALIASES = {
    "春節": ("春節", "過年", "新春", "農曆年"),
    "元宵節": ("元宵節", "元宵", "燈會"),
    "清明節": ("清明節", "清明"),
    "兒童節": ("兒童節", "兒童月"),
    "勞動節": ("勞動節", "五一勞動節"),
    "母親節": ("母親節", "媽媽節", "媽咪", "母親", "媽媽"),
    "端午節": ("端午節", "端午", "粽夏", "粽情"),
    "父親節": ("父親節", "爸爸節", "爸氣", "父親", "爸爸"),
    "七夕": ("七夕", "七夕情人節"),
    "情人節": ("情人節", "西洋情人節"),
    "中秋節": ("中秋節", "中秋", "月圓"),
    "國慶日": ("國慶日", "國慶", "雙十"),
    "聖誕節": ("聖誕節", "聖誕", "耶誕節", "耶誕"),
    "跨年": ("跨年", "迎新年"),
    "開學季": ("開學季", "開學"),
    "暑期": ("暑期", "暑假", "夏日", "盛夏"),
    "週年慶": ("週年慶", "周年慶"),
    "年終": ("年終", "歲末", "尾牙"),
}

CHINESE_CALENDAR_MONTHS = {
    "一月": 1,
    "二月": 2,
    "三月": 3,
    "四月": 4,
    "五月": 5,
    "六月": 6,
    "七月": 7,
    "八月": 8,
    "九月": 9,
    "十月": 10,
    "十一月": 11,
    "十二月": 12,
}

KEYWORD_FALLBACK_TERMS = (
    "室內",
    "室外",
    "移機",
    "搬移",
    "搬家",
    "費用",
    "收費",
    "多少錢",
    "月租",
    "月費",
    "收視費",
    "半年繳",
    "年繳",
    "總價",
    "合計",
    "總金額",
    "價格",
    "價錢",
    "方案",
    "優惠",
    "促銷",
    "活動",
    "春節",
    "過年",
    "新春",
    "母親節",
    "媽媽節",
    "父親節",
    "爸爸節",
    "爸氣",
    "端午節",
    "中秋節",
    "聖誕節",
    "週年慶",
    "抽獎",
    "摸彩",
    "中獎",
    "獎項",
    "獎品",
    "送什麼",
    "好禮",
    "贈品",
    "家電",
    "壁掛",
    "壁掛架",
    "壁架",
    "保固",
    "配送",
    "品牌",
    "廠牌",
    "廠商",
    "另行報價",
    "低收入",
    "低收",
    "中低收入",
    "身心障礙",
    "身障",
    "減免",
    "免裝機費",
    "優惠後收費",
    "優惠期間",
    "申請條件",
    "限制條件",
    "好視成雙",
    "no8",
    "no.8",
    "飆網守護",
    "申裝",
    "新申裝",
    "裝機",
    "安裝",
    "分機費",
    "順裝",
    "停機",
    "暫停機",
    "暫停收視",
    "暫停收看",
    "復機",
    "復機費",
    "雙證件",
    "證件",
    "身分證",
    "身份證",
    "印章",
    "臨櫃辦理",
    "帳單",
    "繳費",
    "線上繳費",
    "線上刷卡",
    "線上刷卡繳費",
    "自動開通",
    "開通",
    "IBON",
    "FAMIPORT",
    "ibon",
    "famiport",
    "超商",
    "便利商店",
    "繳費機",
    "機台",
    "教學",
    "操作",
    "發票",
    "載具",
    "載具歸戶",
    "發票載具",
    "用戶歸戶",
    "固定ip",
    "固定IP",
    "網路",
    "寬頻",
    "電視",
    "機上盒",
    "STB",
    "報修",
    "維修",
    "line tv",
    "linetv",
    "哈tv",
    "哈TV",
    "A套餐",
    "B套餐",
    "C套餐",
    "哈TV-A套餐",
    "哈TV-B套餐",
    "哈TV-C套餐",
    "數位套餐",
    "加值套餐",
    "加值數位套餐",
    "加值服務",
    "紅利點數",
    "哈point",
    "point",
    "點數",
    "單品銷售",
    "熱門單品",
    "加購",
    "申請方式",
    "辦理方式",
    "購買",
    "收費標準",
    "頻道內容",
    "頻道",
    "vip會員",
    "VIP會員",
    "優惠專區",
    "裝置",
    "幾台",
    "同時",
    "觀看",
    "收看",
)

HIGH_SIGNAL_ANSWER_TERMS = (
    "壁掛",
    "壁掛架",
    "壁架",
    "保固",
    "配送",
    "品牌",
    "廠牌",
    "贈品",
    "家電",
    "另行報價",
    "低收入",
    "低收",
    "中低收入",
    "身心障礙",
    "身障",
    "減免",
    "免裝機費",
    "優惠後收費",
    "優惠期間",
    "申請條件",
    "限制條件",
    "收視費",
    "分機費",
    "停機",
    "暫停機",
    "暫停收視",
    "暫停收看",
    "復機費",
    "雙證件",
    "證件",
    "身分證",
    "身份證",
    "印章",
    "臨櫃辦理",
    "哈tv",
    "哈TV",
    "數位套餐",
    "加值套餐",
    "加值數位套餐",
    "加值服務",
    "紅利點數",
    "哈point",
    "point",
    "點數",
    "單品銷售",
    "熱門單品",
    "加購",
    "收費標準",
    "頻道內容",
    "世界盃",
    "世足",
    "fifa",
)

CONVENIENCE_STORE_PAYMENT_GUIDE_TERMS = (
    "ibon",
    "famiport",
    "超商繳費機",
    "便利商店機台",
    "繳費機",
    "機台操作",
    "繳費教學",
)

SOCIAL_DISCOUNT_TERMS = (
    "低收入",
    "低收",
    "中低收入",
    "身心障礙",
    "身障",
    "殘障",
    "社福",
    "減免",
)

GENERIC_PROMOTION_TERMS = (
    "推薦",
    "優惠",
    "促銷",
    "活動",
    "方案",
    "套餐",
)

PURE_NETWORK_CATALOG_QUERY_TERMS = (
    "純網",
    "純寬頻",
    "單一網路",
    "單純網路",
    "單辦網路",
    "單裝網路",
    "單辦寬頻",
    "單裝寬頻",
    "只要網路",
    "只有網路",
    "只上網",
    "只裝網路",
    "不用第四台",
    "不要第四台",
    "不含第四台",
    "不用有線電視",
    "不要有線電視",
    "不含有線電視",
)

PURE_TV_CATALOG_QUERY_TERMS = (
    "純有線電視",
    "純有線",
    "純電視",
    "純tv",
    "單辦有線電視",
    "單裝有線電視",
    "只要有線電視",
    "只看第四台",
)

BROADBAND_PLAN_PRICE_QUERY_TERMS = (
    "一般寬頻",
    "哈net1",
    "哈 net1",
    "單辦網路",
    "單裝網路",
    "只要網路",
    "寬頻費",
    "網路費",
)

RESTRICTED_CHANNEL_PURCHASE_QUERY_TERMS = (
    "成人頻道",
    "成人節目",
    "限制級",
    "鎖碼頻道",
)

RESTRICTED_CHANNEL_PURCHASE_DOC_TERMS = (
    "成人頻道",
    "成人節目",
    "限制級",
    "鎖碼頻道",
    "VIP會員",
    "優惠專區",
    "Hi Play全餐",
    "HBO全餐",
)

# A named digital-TV package can be a normal package rather than an
# authorization issue. Keep the acquisition path and the package price as
# separate evidence types so the LLM can answer "how to add it" with an actual
# customer action instead of inferring a process from the price list alone.
DIGITAL_TV_PACKAGE_PURCHASE_ACTION_TERMS = (
    "購買",
    "加購",
    "訂購",
    "訂閱",
    "申請",
    "辦理",
    "流程",
    "怎麼買",
    "如何買",
)

DIGITAL_TV_PACKAGE_PURCHASE_SUBJECT_TERMS = (
    "數位電視",
    "數位套餐",
    "電視套餐",
    "頻道套餐",
    "全餐",
)

# This is a retrieval facet, not customer-facing content. The actual purchase
# steps must still come from an active knowledge-base document.
DIGITAL_TV_PACKAGE_PURCHASE_PATH_QUERY = "數位套餐加購 機上盒"

BASIC_TV_FEE_QUERY_TERMS = (
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
    "純tv",
    "純 TV",
    "TV 基本收費",
    "大屯 TV 基本收費",
    "機上盒多台",
    "多台機上盒",
    "多台電視",
    "第3台",
    "第三台",
    "第6台",
    "第六台",
    "STB 設備押金",
    "分機施工費",
)

BASIC_TV_FEE_DOC_TERMS = (
    "TV 收視費",
    "收視費",
    "基本收費標準",
    "大屯_TV_基本收費標準",
    "TV 分機費",
    "STB 設備押金",
    "機上盒",
    "分機施工費",
)

PROMOTION_CAMPAIGN_TERMS = (
    "活動期間",
    "方案名稱",
    "飆網守護",
    "好視成雙",
    "新春",
    "母親節",
    "父親節",
    "B2606",
    "NO8",
    "NO9",
    "NO10",
    "綁約",
    "違約金",
    "贈",
    "贈品",
    "拆帳表",
    "派工方案",
    "售價",
    "月繳",
    "季繳",
    "半年繳",
    "年繳",
    "裝機費",
    "押金",
)

PROMOTION_CAMPAIGN_REQUIRED_DETAIL_TERMS = (
    "綁約",
    "違約金",
    "贈",
    "贈品",
    "月繳",
    "季繳",
    "半年繳",
    "年繳",
    "裝機費",
    "押金",
    "售價",
)

GENERIC_PROMOTION_FAQ_TERMS = (
    "通常是指",
    "泛指",
    "如果您需要更詳細",
    "真人客服",
    "可輸入關鍵字",
    "請洽客服",
)

INTERNAL_CAMPAIGN_NOTE_TERMS = (
    "客服報價",
    "派工方案注意事項",
    "派工備註",
    "派工請",
    "順簽",
    "優惠方案同意書",
    "上傳雙證件",
    "完工收",
    "退租設備",
    "自停前",
    "xx/xx",
    "09xx",
)

NON_PRIMARY_CAMPAIGN_TERMS = (
    "隱藏版",
    "非主推",
    "不主推",
    "不要主推",
    "不建議主推",
    "售戶盡量不主推",
    "下述頻寬不推",
    "特殊需求須請示主管",
    "AI 禁止報價",
    "ai禁止報價",
    "禁止報價",
)

RESTRICTED_RATE_NOTE_TERMS = (
    "下述頻寬不推",
    "特殊需求須請示主管",
    "AI 禁止報價",
    "ai禁止報價",
    "禁止報價",
)

PRIMARY_CAMPAIGN_TERMS = (
    "主推",
    "主推100M",
    "主推 100M",
    "主推 100M、300M、500M",
)

NON_PRIMARY_QUERY_TERMS = (
    "隱藏版",
    "非主推",
    "不主推",
    "不推",
    "禁止報價",
)

def normalize_retrieval_query(query: str) -> str:
    value = str(query or "").strip()
    if not value:
        return ""

    lower = value.lower()
    compact = lower.replace(" ", "").replace("　", "")
    if "linetv" in compact or "line tv" in lower:
        value = value.replace("線台裝置", "幾台裝置")
        value = value.replace("在線台", "在幾台")
        if "裝置" in value and not any(term in value for term in ("幾台", "同時", "人數")):
            value = f"{value} 幾台裝置 同時觀看"
        if "收看" in value and "觀看" not in value:
            value = f"{value} 觀看"

    # Plans are indexed with a symmetric rate such as 500M/500M, while
    # customers commonly write 500mbps. This only enriches a query already
    # selected for knowledge retrieval; it does not decide the conversation
    # intent or provide a price outside the knowledge base.
    normalized = normalize_keyword_text(value)
    has_speed = bool(re.search(r"\d+(?:\.\d+)?(?:m|mbps|g|gbps)", normalized))
    has_price = any(term in normalized for term in ("費用", "收費", "價格", "價錢", "月租", "月費", "多少錢"))
    has_tv = any(term in normalized for term in ("有線電視", "第四台", "電視"))
    if has_speed and has_price and not has_tv:
        speeds = sorted(extract_requested_broadband_speeds(value))
        speed_terms = " ".join(
            f"{speed}/{speed}" if speed.endswith(("m", "g")) else speed
            for speed in speeds
        )
        value = f"{value} 寬頻網路 單辦寬頻 {speed_terms} 速率 月繳 季繳 半年繳 年繳"

    return value


def infer_category_from_memory_and_text(
    memory: Dict[str, Any],
    user_input: str,
    controller_output: Optional[Dict[str, Any]] = None,
) -> Optional[str]:
    service = memory.get("service") or (controller_output.get("service") if controller_output else None)
    issue_type = memory.get("issue_type") or (controller_output.get("issue_type") if controller_output else None)
    text = (user_input or "").lower()

    if service == "billing":
        return "billing"
    if service == "television":
        return "set_top_box"
    if service == "network":
        return "network_support"

    if (
        any(k in text for k in ["網路", "寬頻"])
        and any(k in text for k in ["方案", "費用", "月租", "價格", "價錢", "多少錢", "優惠"])
    ):
        return "network_support"

    if any(k in text for k in ["瑪帛", "瑪柏", "熊搭心", "電視電話", "家庭相簿", "生活提醒"]):
        return "value_added_service"

    if any(k in text for k in ["帳單", "繳費", "退費", "退租", "發票", "載具", "月租", "違約金"]):
        return "billing"
    if any(k in text for k in ["第四台", "機上盒", "雙模機", "聯網機上盒", "遙控器", "頻道", "無訊號", "電視"]):
        return "set_top_box"
    if any(k in text for k in ["網路", "寬頻", "wifi", "wi-fi", "數據機", "speedtest", "固定ip", "固定 ip", "光纖"]):
        return "network_support"
    if any(k in text for k in ["line tv", "hbo", "friday", "監視器", "加值"]):
        return "value_added_service"

    if issue_type in NETWORK_ISSUE_TYPES:
        return "network_support"

    return None


def infer_company_filter(memory: Dict[str, Any]) -> Optional[str]:
    company = memory.get("company")
    return company if company and company != "共用" else None


def infer_knowledge_base(memory: Dict[str, Any]) -> str:
    explicit_knowledge_base = str((memory or {}).get("knowledge_base") or "").strip()
    if explicit_knowledge_base:
        return normalize_knowledge_base_name(explicit_knowledge_base)

    company_code = (memory or {}).get("company_code")
    if company_code in TV_DICT:
        return TV_DICT[company_code]

    profile = (memory or {}).get("company_profile") or {}
    if profile.get("class"):
        return profile["class"]

    company = (memory or {}).get("company") or ""
    for class_name in TV_DICT.values():
        if class_name and class_name in company:
            return class_name

    return DEFAULT_RAG_KNOWLEDGE_BASE


def configured_common_knowledge_base_scopes() -> dict[str, list[str]]:
    try:
        return COMMON_SCOPE_SERVICE.get_common_knowledge_base_scopes()
    except Exception:
        return {
            common_base: sorted(members)
            for common_base, members in REGIONAL_COMMON_MEMBERS.items()
        }


def infer_knowledge_bases(memory: Dict[str, Any]) -> List[str]:
    specific_base = infer_knowledge_base(memory)
    common_scopes = configured_common_knowledge_base_scopes()
    bases = retrieval_common_knowledge_bases(
        specific_base,
        common_scopes,
    )
    if specific_base and specific_base not in bases:
        bases.append(specific_base)
    memory["resolved_knowledge_bases"] = list(bases)
    memory["policy_context"] = resolve_policy_context(memory, common_scopes)
    return bases


def is_named_campaign_query(query: str) -> bool:
    normalized = normalize_keyword_text(query)
    if not normalized:
        return False
    if "飆網守護" in normalized or re.search(r"\bb\d{4}\b", normalized):
        return True
    return "好視成雙" in normalized and bool(re.search(r"no\.?\d+", normalized))


def detect_hatv_package_key(query: str) -> Optional[str]:
    normalized = normalize_keyword_text(query).replace("-", "")
    for key in ("a", "b", "c"):
        if f"{key}套餐" in normalized or f"哈tv{key}套餐" in normalized:
            return key.upper()
    return None


def build_hatv_package_table_content(chunks: List[Dict[str, Any]], package_key: str) -> str:
    target = f"哈tv{package_key.lower()}套餐"
    rows: List[str] = []
    collecting = False

    for chunk in chunks:
        content = str(chunk.get("content") or "").strip()
        if not content:
            continue

        section = str(chunk.get("section") or "")
        lines = [line.strip() for line in content.splitlines() if line.strip()] or [content]
        is_table_section = section.startswith("table")

        for line in lines:
            normalized = normalize_keyword_text(line).replace("-", "")
            is_package_header = bool(re.search(r"哈tv[abc]套餐", normalized))
            is_other_package_header = is_package_header and target not in normalized
            is_channel_row = bool(re.match(r"^\s*\d+\s*\|", line)) or "|" in line

            if target in normalized and (is_table_section or normalized.startswith(target)):
                collecting = True
                rows.append(line)
                continue

            if collecting and is_other_package_header:
                return "\n".join(rows) if len(rows) > 1 else ""

            if collecting and (is_table_section or is_channel_row):
                rows.append(line)

    if len(rows) <= 1:
        return ""

    return "\n".join(rows)


def infer_retrieval_knowledge_bases(query: str, memory: Dict[str, Any]) -> List[str]:
    bases = infer_knowledge_bases(memory)
    if not is_named_campaign_query(query):
        return bases

    for base in TV_DICT.values():
        if base not in bases:
            bases.append(base)
    return bases


def build_local_search_candidate_count(query: str, top_k: int) -> int:
    query_terms = set(build_keyword_terms(query))
    if detect_value_added_product_keys(query):
        return max(top_k * 12, 60)
    if detect_query_facets(query):
        return max(top_k * 12, 60)
    if is_named_campaign_query(query):
        return max(top_k * 16, 80)
    if is_basic_tv_fee_query(query):
        return max(top_k * 12, 60)
    if (
        is_broadband_plan_price_query(query)
        or is_pure_network_catalog_query(query)
        or is_restricted_channel_purchase_query(query)
        or is_digital_tv_package_purchase_query(query)
    ):
        return max(top_k * 12, 60)
    if is_generic_promotion_query(query):
        return max(top_k * 12, 60)
    if query_terms.intersection(HIGH_SIGNAL_ANSWER_TERMS):
        return max(top_k * 10, 50)
    return max(top_k * 3, 12)


def should_merge_keyword_fallback(query: str) -> bool:
    query_terms = set(build_keyword_terms(query))
    return (
        bool(detect_value_added_product_keys(query))
        or bool(detect_query_facets(query))
        or is_named_campaign_query(query)
        or is_basic_tv_fee_query(query)
        or is_broadband_plan_price_query(query)
        or is_pure_network_catalog_query(query)
        or is_restricted_channel_purchase_query(query)
        or is_digital_tv_package_purchase_query(query)
        or is_generic_promotion_query(query)
        or is_convenience_store_payment_guide_query(query)
        or is_hatv_addon_info_query(query)
        or bool(detect_hatv_package_key(query))
        or bool(query_terms.intersection(HIGH_SIGNAL_ANSWER_TERMS))
    )


def is_specific_interrogative_query(query: str) -> bool:
    """Return whether the customer asks for a concrete fact or operation.

    This is a retrieval-safety signal, not an intent rule.  It prevents a
    semantically nearby chunk from being treated as the answer when the source
    documents may contain a much more precise FAQ row.
    """
    normalized = normalize_keyword_text(query)
    if len(normalized) < 4:
        return False
    return any(
        marker in normalized
        for marker in (
            "怎麼",
            "如何",
            "能不能",
            "可不可以",
            "可以嗎",
            "為什麼",
            "最多",
            "多少",
            "幾號",
            "幾組",
            "幾台",
            "有沒有",
        )
    )


def should_merge_keyword_fallback_for_results(
    query: str,
    docs: List[Dict[str, Any]],
) -> bool:
    """Supplement semantic results when none has direct query evidence.

    Chroma can return semantically nearby chunks even when an exact FAQ row is
    outside its candidate window.  In that case, treating a non-empty result
    list as success prevents the local document scan from recovering the exact
    row.  Keep the established high-signal triggers, then use the scores already
    computed for Chroma results to detect this generic low-evidence case.
    """
    if should_merge_keyword_fallback(query):
        return True
    if not docs or not build_keyword_terms(query):
        return not docs

    # A customer who names both the television and broadband products is
    # asking about their combined service.  Always merge lexical candidates so
    # a standalone add-on FAQ cannot crowd the actual combo-plan document out.
    if is_tv_network_combo_query(query):
        return True

    # A rate such as 60M/6M is an explicit service anchor, not a soft
    # similarity hint. Semantic search can otherwise return a basic cable-TV
    # rate card because it shares billing language, even though it cannot
    # answer the named broadband rate. Request the lexical supplement before
    # evidence selection so the exact rate row remains a candidate.
    requested_speeds = extract_requested_broadband_speeds(query)
    if requested_speeds and not any(
        all(
            speed in normalize_keyword_text(doc_search_text(doc))
            for speed in requested_speeds
        )
        for doc in docs
    ):
        return True

    # A semantic neighbour can accumulate relevance from broad words such as
    # "機上盒" or "設定" while still missing the customer's actual subject.
    # When a stable natural-language anchor was extracted, require at least one
    # semantic result to contain that complete phrase before accepting the set.
    anchors = [
        normalize_keyword_text(anchor)
        for anchor in extract_query_anchor_terms(query)
        if normalize_keyword_text(anchor)
    ]
    best_keyword_score = max(int(doc.get("_keyword_score") or 0) for doc in docs)
    best_relevance_score = max(
        int(
            doc.get("_query_relevance_score")
            if doc.get("_query_relevance_score") is not None
            else score_query_relevance(query, doc)
        )
        for doc in docs
    )
    has_anchor_match = any(
        any(anchor in normalize_keyword_text(doc_search_text(doc)) for anchor in anchors)
        for doc in docs
    )
    strict_identifiers = extract_query_strict_identifier_terms(query)
    has_identifier_match = any(
        all(
            identifier in normalize_keyword_text(doc_search_text(doc))
            for identifier in strict_identifiers
        )
        for doc in docs
    )
    if strict_identifiers and not has_identifier_match:
        return True
    if not docs_contain_query_subject_evidence(query, docs):
        return True
    # A concrete customer question deserves a source question that contains
    # the same state/action.  Broad answer-body similarity alone is not enough;
    # otherwise "LINE TV QR Code" can be swallowed by a LINE TV promotion and
    # "分期付款" by a generic payment guide.
    if is_specific_interrogative_query(query) and not any(
        has_precise_question_side_match(query, doc)
        for doc in docs
    ):
        return True
    if (
        anchors
        and not has_anchor_match
        and (
            best_relevance_score < 40
            or has_stable_query_subject_anchor(query)
        )
    ):
        return True

    return best_keyword_score <= 0 and best_relevance_score < 8


def knowledge_base_priority(knowledge_base: str, memory: Dict[str, Any]) -> int:
    specific_base = normalize_knowledge_base_name(infer_knowledge_base(memory))
    applicable_common_bases = retrieval_common_knowledge_bases(
        specific_base,
        configured_common_knowledge_base_scopes(),
    )
    raw_value = str(knowledge_base or "").strip()
    if raw_value == LEGACY_COMMON_KNOWLEDGE_BASE:
        return 3
    value = normalize_knowledge_base_name(knowledge_base)
    if specific_base and value == specific_base:
        return 0
    if value in REGIONAL_COMMON_KNOWLEDGE_BASES and value in applicable_common_bases:
        return 1
    if value == CENTRAL_COMMON_KNOWLEDGE_BASE:
        return 2
    if value in REGIONAL_COMMON_KNOWLEDGE_BASES:
        return 4
    return 5


def doc_knowledge_base(doc: Dict[str, Any]) -> str:
    return str(
        doc.get("company")
        or doc.get("knowledge_base")
        or (doc.get("source") or {}).get("knowledge_base")
        or ""
    ).strip()


def build_relevance_terms(query: str) -> List[str]:
    terms = build_keyword_terms(query)
    normalized = normalize_keyword_text(query)

    for token in re.findall(r"[a-z0-9]+", normalized):
        if len(token) >= 2 and token not in terms:
            terms.append(token)

    return terms


def detect_query_facets(query: str) -> set[str]:
    """Return answer facets that need stronger evidence than semantic similarity."""
    normalized = normalize_keyword_text(query)
    if not normalized:
        return set()

    facets: set[str] = set()
    has_set_top_box = any(term in normalized for term in ("機上盒", "數位機上盒", "stb", "分機"))
    has_multiple_units = any(
        term in normalized
        for term in ("多台", "第2台", "第二台", "第3台", "第三台", "第4台", "第四台", "第5台", "第五台", "第6台", "第六台", "以上", "加裝", "申裝")
    )
    has_fee_intent = any(
        term in normalized
        for term in ("費用", "收費", "多少錢", "價錢", "價格", "押金", "分機費", "施工費", "裝機費", "怎麼算")
    )
    if has_set_top_box and has_multiple_units and has_fee_intent:
        facets.add("multi_set_top_box_fee")

    has_set_top_box_power_context = has_set_top_box or any(
        term in normalized for term in ("sd21", "sd22", "sd-21", "sd-22")
    )
    has_power_saving_request = any(
        term in normalized
        for term in ("節能", "待機", "休眠", "睡眠", "自動開關機", "自動關機", "關閉螢幕")
    )
    if has_set_top_box_power_context and has_power_saving_request:
        facets.add("set_top_box_power_saving")

    has_remote = any(term in normalized for term in ("遙控器", "語音遙控器"))
    has_purchase = any(term in normalized for term in ("買", "購買", "換一支", "更換", "申購", "加購"))
    if has_remote and has_purchase and has_fee_intent:
        facets.add("equipment_purchase_price")

    has_points = any(term in normalized for term in ("紅利點數", "紅利點", "哈point", "point點數", "points"))
    has_points_usage = any(
        term in normalized
        for term in ("可以做什麼", "能做什麼", "怎麼用", "如何使用", "用途", "兌換", "折抵", "可以換", "拿來做")
    )
    if has_points and has_points_usage:
        facets.add("points_usage")

    has_points_overview = has_points and any(
        term in normalized
        for term in ("紅利點數", "哈point", "point點數")
    )
    has_campaign_gift_points = any(
        term in normalized
        for term in ("贈幾點", "送幾點", "贈多少點", "送多少點", "贈點", "送點")
    ) or (
        any(term in normalized for term in ("月繳", "季繳", "半年繳", "年繳"))
        and any(term in normalized for term in ("贈", "送"))
    )
    if has_points_overview and not has_campaign_gift_points:
        facets.add("points_overview")

    has_line_tv = "linetv" in normalized
    has_device = any(term in normalized for term in ("登入", "登錄", "裝置", "設備", "手機", "電視"))
    has_limit = any(term in normalized for term in ("幾台", "多少台", "最多", "上限", "限制", "同時"))
    if has_line_tv and has_device and has_limit:
        facets.add("service_device_limit")

    has_senior = any(term in normalized for term in ("長輩", "年長者", "銀髮", "老人", "高齡"))
    has_service_intent = any(
        term in normalized
        for term in ("服務", "加值", "適合", "方案", "功能", "可以用", "有什麼", "有哪些")
    )
    if has_senior and has_service_intent:
        facets.add("senior_value_added_service")

    has_internet = any(term in normalized for term in ("上網", "網路"))
    has_time_context = any(
        term in normalized
        for term in (
            "小孩", "孩子", "兒童", "家長", "晚上", "夜間", "幾點",
            "時段", "時間", "十點", "十一點", "十二點",
        )
    )
    has_time_control = any(
        term in normalized
        for term in (
            "不能上網", "禁止上網", "限制", "管控", "管理", "設定",
            "停用", "關閉", "不准上網", "不要上網",
        )
    )
    if has_internet and has_time_context and has_time_control:
        facets.add("internet_time_control")

    has_cancellation = any(
        term in normalized
        for term in (
            "退租",
            "終止服務",
            "取消服務",
            "停用服務",
            "解約",
            "停機",
            "暫停機",
            "暫停收視",
            "暫停收看",
        )
    )
    has_required_items = any(
        term in normalized
        for term in ("證件", "要帶", "攜帶", "準備", "需要什麼", "需要哪些")
    )
    if has_cancellation and has_required_items:
        facets.add("service_cancellation_requirements")

    has_credit_card = any(term in normalized for term in ("信用卡", "刷卡"))
    has_payment_action = any(
        term in normalized
        for term in ("繳費", "繳款", "付款", "怎麼繳", "如何繳", "用信用卡繳", "線上繳")
    )
    if has_credit_card and has_payment_action:
        facets.add("credit_card_payment_method")

    has_online_payment_request = any(
        term in normalized
        for term in ("線上繳費", "線上刷卡", "線上信用卡繳費", "網路繳費")
    )
    if has_online_payment_request:
        facets.add("online_payment_guidance")

    has_payment_method_request = any(
        term in normalized
        for term in (
            "繳費方式", "繳款方式", "付款方式", "繳費管道", "繳款管道",
            "付款管道", "如何繳費", "怎麼繳費", "怎麼繳", "如何繳",
        )
    )
    if has_payment_method_request and not has_credit_card:
        facets.add("payment_method_guidance")

    return facets


def score_query_facet_evidence(query: str, doc: Dict[str, Any]) -> int:
    """Score whether a chunk contains the facts required by the user's facet."""
    facets = detect_query_facets(query)
    if not facets:
        return 0

    text = normalize_keyword_text(doc_search_text(doc))
    score = 0

    if "multi_set_top_box_fee" in facets:
        if any(term in text for term in ("機上盒", "數位機上盒", "stb", "分機")):
            score += 45
        if any(term in text for term in ("第3台", "第三台", "第3台起", "第3、4、5台", "第3台以上")):
            score += 110
        if "押金" in text:
            score += 70
        if any(term in text for term in ("分機費", "施工費", "裝機費")):
            score += 55
        if re.search(r"(?:押金|分機費|施工費|裝機費).{0,12}\d+(?:,\d{3})*元", text):
            score += 70

    if "equipment_purchase_price" in facets:
        if "遙控器" in text:
            score += 90
        if any(term in text for term in ("元/支", "元一支", "每支", "購買", "售價")):
            score += 100
        if re.search(r"遙控器.{0,18}\d+(?:,\d{3})*元", text):
            score += 110
        if any(term in text for term in ("電池", "重新配對", "無法操作")) and not re.search(r"遙控器.{0,18}\d+(?:,\d{3})*元", text):
            score -= 80

    if "set_top_box_power_saving" in facets:
        source = doc.get("source") if isinstance(doc.get("source"), dict) else {}
        question_text = normalize_keyword_text(
            doc.get("question") or source.get("title") or ""
        )
        normalized_query = normalize_keyword_text(query)
        asks_to_disable = any(
            term in normalized_query
            for term in ("不要休眠", "不要睡眠", "不要待機", "關閉節能", "關閉待機", "取消節能", "不進入待機")
        )
        if any(term in text for term in ("節能模式", "待機模式", "休眠", "睡眠", "自動開關機", "關閉螢幕")):
            score += 150
        if any(term in question_text for term in ("節能模式", "待機模式", "休眠", "睡眠", "自動開關機", "關閉螢幕")):
            score += 140
        if any(term in text for term in ("sd22", "sd-22", "雙模機")):
            score += 70
        if asks_to_disable:
            if any(term in text for term in ("關閉節能", "關閉螢幕", "設定為永不")):
                score += 220
            else:
                score -= 100
        if any(term in text for term in ("鏡頭", "視訊鏡頭")) and not any(
            term in text for term in ("節能模式", "待機模式", "休眠", "自動開關機", "關閉螢幕")
        ):
            score -= 160

    if "points_usage" in facets:
        if any(term in text for term in ("紅利點數", "哈point", "point點數")):
            score += 70
        if any(term in text for term in ("購買加值商品", "折抵", "兌換", "收視費", "連線費", "服務費")):
            score += 130
        if any(term in text for term in ("1點等於1元", "1點折抵1元", "不得兌換現金", "不可兌換現金")):
            score += 100
        if any(term in text for term in ("贈point", "贈哈point", "贈點")) and not any(
            term in text for term in ("折抵", "兌換", "購買加值商品", "不得兌換現金", "不可兌換現金")
        ):
            score -= 100

    if "points_overview" in facets:
        if any(term in text for term in ("台數科紅利點數哈point說明", "紅利點數哈point說明")):
            score += 260
        if any(term in text for term in ("優惠積點回饋機制", "紅利點數", "哈point點數")):
            score += 120
        if any(term in text for term in ("購買台數科商品", "抵扣各項服務費用", "專屬優惠福利")):
            score += 100
        if any(term in text for term in ("如何獲得", "如何使用", "有效期限", "查詢點數", "查看點數")):
            score += 60
        gift_only = any(term in text for term in ("贈point", "贈哈point", "贈點", "point贈點規則"))
        explains_points = any(
            term in text
            for term in ("回饋機制", "購買台數科商品", "抵扣各項服務費用", "如何使用", "有效期限")
        )
        if gift_only and not explains_points:
            score -= 180

    if "service_device_limit" in facets:
        if "linetv" in text:
            score += 80
        if any(term in text for term in ("登入裝置", "登錄裝置", "裝置數", "登入數")):
            score += 120
        if any(term in text for term in ("無上限", "不限裝置", "沒有上限", "最多登入", "同時觀看")):
            score += 140
        if "頻道" in text and not any(term in text for term in ("登入", "裝置", "設備")):
            score -= 100

    if "senior_value_added_service" in facets:
        source = doc.get("source") if isinstance(doc.get("source"), dict) else {}
        question_text = normalize_keyword_text(doc.get("question") or source.get("title") or "")
        if any(term in text for term in ("長輩", "年長者", "銀髮", "老人", "高齡")):
            score += 150
        if "熊搭心" in text:
            score += 110
        if any(term in question_text for term in ("長輩", "年長者", "銀髮", "老人", "高齡")):
            score += 130
        if (
            any(term in question_text for term in ("長輩", "年長者", "銀髮", "老人", "高齡"))
            and any(term in question_text for term in ("服務", "提供", "有哪些", "有那些", "適合"))
        ):
            score += 190

    if "internet_time_control" in facets:
        if any(term in text for term in ("上網時間管理", "上網時間限制")):
            score += 220
        if any(term in text for term in ("特定時段", "指定時段", "禁止上網", "限制上網")):
            score += 160
        if any(term in text for term in ("設定", "管理", "申請")):
            score += 60
        if any(term in text for term in ("小孩", "孩子", "家長", "兒童")):
            score += 40

    if "service_cancellation_requirements" in facets:
        if any(
            term in text
            for term in (
                "退租",
                "終止服務",
                "取消服務",
                "解約",
                "停機",
                "暫停機",
                "暫停收視",
                "暫停收看",
            )
        ):
            score += 100
        if any(term in text for term in ("身分證", "身份證", "護照")):
            score += 150
        if "雙證件" in text:
            score += 150
        if any(term in text for term in ("印章", "設備", "配件", "遙控器", "hdmi線", "電源線")):
            score += 80
        if any(term in text for term in ("服務櫃檯", "臨櫃辦理", "櫃台辦理")):
            score += 80
        if any(term in text for term in ("基本收費", "月租", "月繳")) and not any(
            term in text for term in ("身分證", "身份證", "護照", "印章", "設備", "配件")
        ):
            score -= 100

    if "credit_card_payment_method" in facets:
        if any(term in text for term in ("信用卡", "刷卡")):
            score += 120
        if any(term in text for term in ("線上信用卡繳費", "線上刷卡", "線上繳費專區")):
            score += 160
        if any(term in text for term in ("官方網站", "官網")):
            score += 80
        if "用戶編號" in text and "密碼" in text:
            score += 100
        if any(term in text for term in ("基本收費", "月租", "月繳")) and not any(
            term in text for term in ("信用卡", "刷卡", "線上繳費")
        ):
            score -= 120

    if "online_payment_guidance" in facets:
        if any(term in text for term in ("線上繳費", "線上刷卡", "線上信用卡繳費", "繳費專區")):
            score += 150
        if any(term in text for term in ("官方網站", "官網")):
            score += 120
        if "用戶編號" in text and "密碼" in text:
            score += 140
        if any(term in text for term in ("ibon", "famiport", "便利商店機台", "7-eleven")) and not any(
            term in text for term in ("官方網站", "官網", "繳費專區", "用戶編號")
        ):
            score -= 220

    if "payment_method_guidance" in facets:
        payment_channel_terms = (
            "線上繳費", "線上刷卡", "行動客服app", "行動客服 app", "app繳費",
            "臨櫃繳費", "櫃台辦理", "便利商店繳費", "帳單條碼", "ibon", "famiport",
        )
        channel_hits = sum(term in text for term in payment_channel_terms)
        if channel_hits:
            score += min(channel_hits, 4) * 65
        if any(term in text for term in ("繳費方式", "繳款方式", "付款方式", "如何繳費")):
            score += 100
        if any(term in text for term in ("用戶編號", "帳號")) and "密碼" in text:
            score += 60
        if any(term in text for term in ("基本收費", "裝機費", "行政規費", "月租", "月繳")) and not channel_hits:
            score -= 180

    return score


def is_basic_tv_fee_query(query: str) -> bool:
    normalized = normalize_keyword_text(query)
    if not normalized:
        return False

    has_basic_tv = has_any_normalized_term(query, BASIC_TV_FEE_QUERY_TERMS)
    has_tv = any(term in normalized for term in ("有線電視", "第四台", "tv", "基本收費"))
    has_hatv_combo_anchor = "哈tv" in normalized and (
        "哈net" in normalized
        or bool(re.search(r"\d+(?:\.\d+)?(?:mbps|gbps|m|g)", normalized))
    )
    has_fee = any(term in normalized for term in ("費用", "收費", "月租", "月費", "每月", "一個月", "收視費", "半年繳", "年繳", "裝機費", "分機費", "合計", "總金額", "裝到好", "多少錢"))
    has_multi_stb = (
        any(term in normalized for term in ("機上盒", "stb", "分機", "多台電視"))
        and any(term in normalized for term in ("多台", "第1", "第2", "第3", "第三台", "第6", "第六台", "以上", "加裝", "申裝"))
        and any(term in normalized for term in ("費用", "收費", "押金", "分機費", "施工費", "怎麼算", "多少錢"))
    )
    mentions_combo = has_hatv_combo_anchor or any(
        term in normalized
        for term in ("好視成雙", "飆網守護", "寬頻", "網路同裝", "電視加網路", "電視跟網路")
    )
    return (has_basic_tv or has_multi_stb or (has_tv and has_fee)) and not mentions_combo


def extract_requested_broadband_speeds(query: str) -> set[str]:
    normalized = normalize_keyword_text(query)
    return {
        re.sub(r"(?:mbps|gbps)$", lambda match: match.group(0)[0], match.lower())
        for match in re.findall(r"\d+(?:\.\d+)?\s*(?:mbps|gbps|m|g)", normalized, flags=re.IGNORECASE)
    }


def is_broadband_upgrade_query(query: str) -> bool:
    normalized = normalize_keyword_text(query)
    return any(term in normalized for term in ("升級", "升一階", "高一階", "再高一階", "上一階"))


def extract_broadband_download_speeds(text: str) -> list[float]:
    normalized = normalize_keyword_text(text)
    return [
        float(value)
        for value in re.findall(
            r"(\d+(?:\.\d+)?)\s*(?:mbps|gbps|m|g)(?:\s*/\s*\d+(?:\.\d+)?\s*(?:mbps|gbps|m|g))?",
            normalized,
            flags=re.IGNORECASE,
        )
    ]


def is_broadband_plan_price_query(query: str) -> bool:
    normalized = normalize_keyword_text(query)
    if not normalized:
        return False
    has_broadband = any(term in normalized for term in ("網路", "寬頻", "net"))
    has_speed = bool(extract_requested_broadband_speeds(query))
    has_price_or_application = any(
        term in normalized
        for term in (
            "費用", "收費", "價格", "價錢", "月租", "月費", "多少錢",
            "月繳", "季繳", "半年繳", "年繳", "申裝", "申請", "辦理", "我要辦",
        )
    )
    has_fault = any(term in normalized for term in ("故障", "不能上網", "斷線", "不穩", "很慢", "報修"))
    # A bare "500mbps費用" is still a broadband plan price query. The LLM
    # chooses whether to retrieve knowledge; this lets the retrieval layer
    # recognize the abbreviated query after that decision.
    return (has_broadband or (has_speed and has_price_or_application)) and has_speed and has_price_or_application and not has_fault


def is_broadband_plan_price_doc(query: str, doc: Dict[str, Any]) -> bool:
    normalized = normalize_keyword_text(doc_search_text(doc))
    requested_speeds = extract_requested_broadband_speeds(query)
    if is_broadband_upgrade_query(query):
        current_speeds = extract_broadband_download_speeds(query)
        candidate_speeds = extract_broadband_download_speeds(normalized)
        if current_speeds and not any(speed > max(current_speeds) for speed in candidate_speeds):
            return False
    elif requested_speeds and not all(speed in normalized for speed in requested_speeds):
        return False
    has_speed = bool(re.search(r"\d+(?:\.\d+)?[mg](?:/\d+(?:\.\d+)?[mg])?", normalized))
    has_price = any(
        term in normalized
        for term in ("月繳", "季繳", "半年繳", "年繳", "月租", "原價", "售價")
    )
    return has_speed and has_price


def is_restricted_channel_purchase_query(query: str) -> bool:
    normalized = normalize_keyword_text(query)
    if not normalized:
        return False
    has_restricted_channel = has_any_normalized_term(query, RESTRICTED_CHANNEL_PURCHASE_QUERY_TERMS)
    has_purchase_intent = any(
        term in normalized
        for term in ("購買", "加購", "訂閱", "申請", "辦理", "怎麼買", "如何買", "恢復授權")
    )
    return has_restricted_channel and has_purchase_intent


def is_digital_tv_package_purchase_query(query: str) -> bool:
    """Identify a digital-TV package request that needs an acquisition path."""
    normalized = normalize_keyword_text(query)
    if not normalized:
        return False
    has_subject = any(
        normalize_keyword_text(term) in normalized
        for term in DIGITAL_TV_PACKAGE_PURCHASE_SUBJECT_TERMS
    )
    has_purchase_intent = any(
        normalize_keyword_text(term) in normalized
        for term in DIGITAL_TV_PACKAGE_PURCHASE_ACTION_TERMS
    )
    return has_subject and has_purchase_intent


def is_restricted_channel_purchase_doc(doc: Dict[str, Any]) -> bool:
    text = normalize_keyword_text(doc_search_text(doc))
    return is_restricted_channel_purchase_path_doc(doc) or is_restricted_channel_price_doc(doc)


def is_digital_tv_package_purchase_doc(doc: Dict[str, Any]) -> bool:
    return (
        is_digital_tv_package_purchase_path_doc(doc)
        or is_digital_tv_package_price_doc(doc)
    )


def is_digital_tv_package_purchase_path_doc(doc: Dict[str, Any]) -> bool:
    text = normalize_keyword_text(doc_search_text(doc))
    has_navigation = any(term in text for term in ("vip會員", "優惠專區"))
    has_purchase_path = any(
        normalize_keyword_text(term) in text
        for term in DIGITAL_TV_PACKAGE_PURCHASE_ACTION_TERMS
    )
    has_set_top_box_routing = (
        "聯網機上盒" in text
        and "非聯網機上盒" in text
        and any(term in text for term in ("自行加購", "洽客服", "客服辦理"))
    )
    return (has_navigation and has_purchase_path) or has_set_top_box_routing


def is_digital_tv_package_specific_path_doc(doc: Dict[str, Any]) -> bool:
    """Exclude other add-on journeys such as LINE TV from package evidence."""
    text = normalize_keyword_text(doc_search_text(doc))
    has_digital_package_context = any(
        term in text
        for term in ("數位套餐", "數位電視加購", "頻道加購", "數位電視", "依喜愛頻道")
    )
    return has_digital_package_context and is_digital_tv_package_purchase_path_doc(doc)


def is_digital_tv_package_price_doc(doc: Dict[str, Any]) -> bool:
    text = normalize_keyword_text(doc_search_text(doc))
    has_package = any(
        normalize_keyword_text(term) in text
        for term in DIGITAL_TV_PACKAGE_PURCHASE_SUBJECT_TERMS
    )
    has_price = bool(re.search(r"(?:\$|＄)\s*\d+|\d+\s*元", text))
    return has_package and has_price


def is_restricted_channel_purchase_path_doc(doc: Dict[str, Any]) -> bool:
    text = normalize_keyword_text(doc_search_text(doc))
    has_restricted_content = has_any_normalized_term(text, RESTRICTED_CHANNEL_PURCHASE_DOC_TERMS)
    has_purchase_path = any(
        term in text
        for term in ("購買", "加購", "訂閱", "優惠專區", "vip會員", "官方網站", "遙控器")
    )
    return has_restricted_content and has_purchase_path


def is_restricted_channel_price_doc(doc: Dict[str, Any]) -> bool:
    text = normalize_keyword_text(doc_search_text(doc))
    has_package = any(
        term in text
        for term in (
            "hi play全餐", "hiplay全餐", "松視全餐", "潘朵拉套餐",
            "潘朵拉", "蜜桃套餐", "蜜桃", "hbo全餐", "成人頻道",
        )
    )
    has_price = bool(re.search(r"(?:\$|＄)\s*\d+|\d+\s*元", text))
    return has_package and has_price


def select_restricted_channel_purchase_docs(
    docs: List[Dict[str, Any]],
    top_k: int,
) -> List[Dict[str, Any]]:
    """Keep both the purchase steps and the matching package prices."""
    path_docs = [doc for doc in docs if is_restricted_channel_purchase_path_doc(doc)]
    price_docs = [doc for doc in docs if is_restricted_channel_price_doc(doc)]
    selected: List[Dict[str, Any]] = []
    seen: set[str] = set()
    # Reserve one slot for each evidence type before filling the remaining
    # capacity. Otherwise several near-identical purchase-path QA chunks can
    # consume all top-k slots and hide the separate package-price document.
    priority_groups = (
        path_docs[:1],
        price_docs[:1],
        [*path_docs[1:], *price_docs[1:]],
        docs,
    )
    for group in priority_groups:
        for doc in group:
            key = doc_dedupe_key(doc)
            if key in seen:
                continue
            seen.add(key)
            selected.append(doc)
            if len(selected) >= top_k:
                return selected
    return selected


def select_digital_tv_package_purchase_docs(
    docs: List[Dict[str, Any]],
    top_k: int,
) -> List[Dict[str, Any]]:
    """Reserve context for both a package price and its supported purchase path."""
    path_docs = [doc for doc in docs if is_digital_tv_package_specific_path_doc(doc)]
    path_docs = sorted(
        path_docs,
        key=lambda doc: (
            -int(
                any(
                    term in normalize_keyword_text(str(doc.get("question") or ""))
                    for term in ("數位套餐加購", "數位電視加購")
                )
            ),
            -int(doc.get("_query_question_evidence_score") or 0),
            -int(doc.get("_query_relevance_score") or 0),
        ),
    )
    price_docs = [doc for doc in docs if is_digital_tv_package_price_doc(doc)]
    selected: List[Dict[str, Any]] = []
    seen: set[str] = set()
    for group in (path_docs[:1], price_docs[:1], [*path_docs[1:], *price_docs[1:]], docs):
        for doc in group:
            key = doc_dedupe_key(doc)
            if key in seen:
                continue
            seen.add(key)
            selected.append(doc)
            if len(selected) >= top_k:
                return selected
    return selected


def supplement_digital_tv_package_purchase_path_docs(
    query: str,
    docs: List[Dict[str, Any]],
    memory: Dict[str, Any],
    active_filter_bases: List[str],
) -> List[Dict[str, Any]]:
    """Recover a documented purchase path when a named package only finds its price."""
    if (
        not is_digital_tv_package_purchase_query(query)
        or any(is_digital_tv_package_specific_path_doc(doc) for doc in docs)
    ):
        return docs

    path_candidates = retrieve_knowledge_from_keyword_fallback(
        DIGITAL_TV_PACKAGE_PURCHASE_PATH_QUERY,
        memory,
        top_k=24,
    )
    path_docs = [
        doc for doc in path_candidates
        if is_digital_tv_package_specific_path_doc(doc)
    ]
    if not path_docs:
        return docs

    merged_docs = dedupe_retrieved_docs([*docs, *path_docs])
    return filter_docs_to_active_manifest_sources(merged_docs, active_filter_bases)


def select_broadband_plan_price_docs(
    query: str,
    docs: List[Dict[str, Any]],
    top_k: int,
) -> List[Dict[str, Any]]:
    """Prefer one matching price chunk per source document before duplicates."""
    price_docs = [doc for doc in docs if is_broadband_plan_price_doc(query, doc)]
    candidates = price_docs or docs
    selected: List[Dict[str, Any]] = []
    deferred: List[Dict[str, Any]] = []
    seen_docs: set[str] = set()
    seen_chunks: set[str] = set()

    for doc in candidates:
        chunk_key = doc_dedupe_key(doc)
        document_key = campaign_document_id(doc) or str(
            (doc.get("source") or {}).get("source")
            if isinstance(doc.get("source"), dict)
            else doc.get("source")
            or ""
        ).strip()
        if chunk_key in seen_chunks:
            continue
        seen_chunks.add(chunk_key)
        if document_key and document_key in seen_docs:
            deferred.append(doc)
            continue
        if document_key:
            seen_docs.add(document_key)
        selected.append(doc)
        if len(selected) >= top_k:
            return selected

    for doc in deferred:
        selected.append(doc)
        if len(selected) >= top_k:
            break
    return selected


def is_hatv_addon_info_query(query: str) -> bool:
    normalized = normalize_keyword_text(query)
    if not normalized:
        return False
    has_hatv = "哈tv" in normalized or "hatv" in normalized
    has_addon = any(term in normalized for term in ("加購", "數位套餐", "加值套餐", "加值數位套餐"))
    return has_hatv and has_addon


def is_value_added_catalog_query(query: str) -> bool:
    normalized = normalize_keyword_text(query)
    if not normalized:
        return False
    has_value_added = any(
        term in normalized
        for term in (
            "加值套餐",
            "加值數位套餐",
            "數位電視套餐",
            "單品銷售",
            "熱門單品",
            "加值服務",
        )
    )
    has_catalog_intent = any(term in normalized for term in ("哪些", "有哪些", "清單", "內容", "費用", "收費", "價格", "月繳", "加購"))
    return has_value_added and has_catalog_intent


VALUE_ADDED_PRODUCT_QUERY_ALIASES = {
    "line_tv": ("LINE TV", "LINETV", "LITV", "LINE TV套餐", "影音服務"),
    "wifi_5": ("WiFi 5", "WIFI5", "WI-FI 5", "WiFi 5分享器"),
    "wifi_6": ("WiFi 6", "WIFI6", "WI-FI 6", "WiFi 6分享器"),
    "wifi_addon": ("WiFi加值", "WiFi服務", "Mesh", "分享器", "無線網路設備"),
    "home_camera": (
        "居家智慧攝影機", "智慧攝影機", "攝影機", "監視器", "智慧鏡頭",
        "居家監控", "攝影機租借", "租借攝影機",
    ),
    "bear_care": ("熊搭心", "電視電話", "家庭相簿", "生活提醒"),
    "marpa_user": ("瑪帛用戶", "瑪帛基本方案"),
    "marpa_friend": ("瑪帛好友", "瑪帛好友方案"),
    "marpa_partner": ("瑪帛夥伴", "瑪帛夥伴方案"),
    "marpa": ("瑪帛",),
}

# Retrieval-only terms connect a customer-facing parent service with the
# concrete plan names and benefits that may be stored in separate chunks.
# They are intentionally not entity aliases, so they cannot broaden intent
# detection or silently reinterpret an unrelated user message.
VALUE_ADDED_PRODUCT_RETRIEVAL_TERMS = {
    "bear_care": (
        "瑪帛用戶",
        "瑪帛好友",
        "瑪帛夥伴",
        "電視電話",
        "家庭相簿",
        "生活提醒",
        "通話120分鐘",
        "無限通話",
    ),
}

VALUE_ADDED_PRODUCT_NAMES = {
    "line_tv": "LINE TV",
    "wifi_5": "WiFi 5 系列分享器",
    "wifi_6": "WiFi 6 系列分享器",
    "wifi_addon": "WiFi 加值服務",
    "home_camera": "居家智慧攝影機",
    "bear_care": "熊搭心",
    "marpa_user": "瑪帛用戶",
    "marpa_friend": "瑪帛好友",
    "marpa_partner": "瑪帛夥伴",
    "marpa": "瑪帛",
}

_KNOWLEDGE_ENTITY_CATALOG_LOCK = threading.Lock()
_KNOWLEDGE_ENTITY_CATALOG_SIGNATURE = None
_KNOWLEDGE_ENTITY_CATALOG: List[Dict[str, Any]] = []


def normalize_entity_identity(value: Any) -> str:
    """Normalize a business entity name without inventing aliases."""
    return re.sub(r"[^0-9a-z\u4e00-\u9fff]+", "", str(value or "").lower())


def _manifest_signature(path: Path) -> tuple:
    try:
        stat = path.stat()
        return (str(path.resolve()), stat.st_mtime_ns, stat.st_size)
    except OSError:
        return (str(path), 0, 0)


def _fixed_knowledge_entities() -> List[Dict[str, Any]]:
    return [
        {
            "key": key,
            "name": VALUE_ADDED_PRODUCT_NAMES.get(key) or aliases[0],
            "aliases": list(dict.fromkeys((VALUE_ADDED_PRODUCT_NAMES.get(key), *aliases))),
            "knowledge_bases": [],
            "source": "built_in",
        }
        for key, aliases in VALUE_ADDED_PRODUCT_QUERY_ALIASES.items()
    ]


def load_knowledge_entity_catalog() -> List[Dict[str, Any]]:
    """Load indexed product/service names generated from uploaded documents."""
    global _KNOWLEDGE_ENTITY_CATALOG_SIGNATURE, _KNOWLEDGE_ENTITY_CATALOG

    path = Path(RAG_LOCAL_MANIFEST_PATH)
    signature = _manifest_signature(path)
    with _KNOWLEDGE_ENTITY_CATALOG_LOCK:
        if signature == _KNOWLEDGE_ENTITY_CATALOG_SIGNATURE:
            return [dict(item) for item in _KNOWLEDGE_ENTITY_CATALOG]

        entities: Dict[tuple, Dict[str, Any]] = {}
        for item in _fixed_knowledge_entities():
            identity = (str(item["key"]), normalize_entity_identity(item["name"]))
            entities[identity] = item

        try:
            payload = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
        except Exception:
            payload = {}

        documents = payload.get("documents") if isinstance(payload, dict) else []
        for document in documents if isinstance(documents, list) else []:
            if not isinstance(document, dict):
                continue
            if document.get("status", "active") != "active" or document.get("processing_status") == "deleted":
                continue
            profile = document.get("product_service_profile")
            if not isinstance(profile, dict):
                continue
            knowledge_base = str(document.get("knowledge_base") or "").strip()
            for product in profile.get("products") or []:
                if not isinstance(product, dict):
                    continue
                name = str(product.get("name") or "").strip()
                normalized_name = normalize_entity_identity(name)
                if len(normalized_name) < 2:
                    continue
                raw_key = str(product.get("key") or "").strip()
                key = raw_key if raw_key and not raw_key.startswith("item_") else f"entity:{normalized_name}"
                identity = (key, normalized_name)
                current = entities.setdefault(identity, {
                    "key": key,
                    "name": name,
                    "aliases": [],
                    "knowledge_bases": [],
                    "source": "manifest",
                })
                aliases = [name, *(product.get("aliases") or [])]
                current["aliases"] = list(dict.fromkeys([
                    *current.get("aliases", []),
                    *(str(alias).strip() for alias in aliases if str(alias).strip()),
                ]))
                if knowledge_base and knowledge_base not in current["knowledge_bases"]:
                    current["knowledge_bases"].append(knowledge_base)

        _KNOWLEDGE_ENTITY_CATALOG_SIGNATURE = signature
        _KNOWLEDGE_ENTITY_CATALOG = list(entities.values())
        return [dict(item) for item in _KNOWLEDGE_ENTITY_CATALOG]


def _single_substitution_window(query: str, candidate: str) -> bool:
    """Accept one conservative typo, e.g. 熊大心 -> 熊搭心."""
    if len(candidate) < 3 or len(candidate) > 16 or len(query) < len(candidate):
        return False
    for start in range(len(query) - len(candidate) + 1):
        window = query[start:start + len(candidate)]
        differences = sum(left != right for left, right in zip(window, candidate))
        if differences != 1:
            continue
        if len(candidate) == 3 and (window[0] != candidate[0] or window[-1] != candidate[-1]):
            continue
        return True
    return False


def is_high_confidence_campaign_alias_match(query: str, alias: str) -> bool:
    """Match an indexed campaign alias exactly or with one substituted glyph."""
    normalized_query = normalize_keyword_text(query)
    normalized_alias = normalize_keyword_text(alias)
    if len(normalized_alias) < 3 or not normalized_query:
        return False
    return (
        normalized_query == normalized_alias
        or normalized_alias in normalized_query
        or _single_substitution_window(normalized_query, normalized_alias)
    )


def resolve_knowledge_entities(query: str) -> List[Dict[str, Any]]:
    """Resolve exact names first, then a high-confidence one-character typo."""
    normalized_query = normalize_entity_identity(query)
    if not normalized_query:
        return []

    catalog = load_knowledge_entity_catalog()
    exact: List[Dict[str, Any]] = []
    for entity in catalog:
        aliases = [entity.get("name"), *(entity.get("aliases") or [])]
        if any(
            (normalized_alias := normalize_entity_identity(alias))
            and normalized_alias in normalized_query
            for alias in aliases
        ):
            exact.append({**entity, "match_type": "exact", "confidence": 1.0})
    if exact:
        return exact

    fuzzy: List[Dict[str, Any]] = []
    for entity in catalog:
        candidate = normalize_entity_identity(entity.get("name"))
        if _single_substitution_window(normalized_query, candidate):
            fuzzy.append({**entity, "match_type": "single_substitution", "confidence": 0.9})
    return fuzzy[:3]


def suggest_knowledge_entity(query: str) -> Optional[Dict[str, Any]]:
    """Return one low-confidence indexed entity that requires user confirmation.

    This deliberately handles a wider two-character substitution than
    ``resolve_knowledge_entities``.  It never becomes a retrieval match by
    itself; callers must ask the user to confirm the canonical name first.
    """
    normalized_query = normalize_entity_identity(query)
    if not normalized_query or resolve_knowledge_entities(query):
        return None

    candidates: Dict[str, Dict[str, Any]] = {}
    for entity in load_knowledge_entity_catalog():
        candidate = normalize_entity_identity(entity.get("name"))
        if len(candidate) < 3 or len(candidate) > 16 or len(normalized_query) < len(candidate):
            continue

        best_window = ""
        best_differences = len(candidate) + 1
        for start in range(len(normalized_query) - len(candidate) + 1):
            window = normalized_query[start:start + len(candidate)]
            if window[0] != candidate[0]:
                continue
            differences = sum(left != right for left, right in zip(window, candidate))
            if differences < best_differences:
                best_window = window
                best_differences = differences

        if best_differences != 2:
            continue

        # Three-character brand names may retain only the leading brand glyph
        # (for example 熊溫馨 -> 熊搭心). Longer names still need most of their
        # characters to agree before they are safe enough to suggest.
        if len(candidate) > 3 and (len(candidate) - best_differences) / len(candidate) < 0.6:
            continue

        current = candidates.get(candidate)
        suggestion = {
            **entity,
            "matched_text": best_window,
            "match_type": "confirmation_required",
            "confidence": round(1 - (best_differences / len(candidate)), 3),
        }
        if current is None or len(entity.get("aliases") or []) > len(current.get("aliases") or []):
            candidates[candidate] = suggestion

    if not candidates:
        return None

    ranked = sorted(
        candidates.values(),
        key=lambda item: (
            float(item.get("confidence") or 0),
            len(normalize_entity_identity(item.get("name"))),
        ),
        reverse=True,
    )
    if len(ranked) > 1 and ranked[0]["confidence"] == ranked[1]["confidence"]:
        return None
    return ranked[0]


def value_added_query_aliases(query: str) -> List[str]:
    aliases: List[str] = []
    for entity in resolve_knowledge_entities(query):
        aliases.extend([entity.get("name"), *(entity.get("aliases") or [])])
        aliases.extend(
            VALUE_ADDED_PRODUCT_RETRIEVAL_TERMS.get(
                str(entity.get("key") or ""),
                (),
            )
        )
    return list(dict.fromkeys(str(value).strip() for value in aliases if str(value).strip()))


def preferred_value_added_entities(query: str) -> List[Dict[str, Any]]:
    """Prefer a named product variant over its broad catalog parent."""
    entities = resolve_knowledge_entities(query)
    keys = {str(entity.get("key") or "") for entity in entities}

    specific_keys = keys & {"wifi_5", "wifi_6"}
    if specific_keys:
        generation_markers = {key: key.replace("_", "") for key in specific_keys}

        def matches_specific_wifi(entity: Dict[str, Any]) -> bool:
            key = str(entity.get("key") or "")
            if key in specific_keys:
                return True
            identities = {
                normalize_entity_identity(alias)
                for alias in (entity.get("name"), *(entity.get("aliases") or []))
                if normalize_entity_identity(alias)
            }
            return any(
                marker in identity
                for marker in generation_markers.values()
                for identity in identities
            )

        # Expanded queries may also contain broad words such as WiFi, Mesh or
        # 分享器.  Once a generation is explicitly named, those broad catalog
        # entities must not compete with the requested product variant.
        return [entity for entity in entities if matches_specific_wifi(entity)]

    suppressed_keys: set[str] = set()
    if keys & {"marpa_user", "marpa_friend", "marpa_partner"}:
        suppressed_keys.update({"marpa", "bear_care"})
    if not suppressed_keys:
        return entities
    return [
        entity
        for entity in entities
        if str(entity.get("key") or "") not in suppressed_keys
    ]


def detect_value_added_product_keys(query: str) -> set[str]:
    matched = {str(entity.get("key") or "") for entity in resolve_knowledge_entities(query)}
    matched.discard("")
    if matched & {"wifi_5", "wifi_6"}:
        matched.add("wifi_addon")
    if matched & {"marpa_user", "marpa_friend", "marpa_partner"}:
        matched.update({"marpa", "bear_care"})
    return matched


def is_value_added_product_fee_query(query: str) -> bool:
    """Return whether a named add-on product is being asked about price."""
    if not detect_value_added_product_keys(query):
        return False
    normalized = normalize_keyword_text(query)
    return any(
        marker in normalized
        for marker in (
            "多少",
            "費用",
            "價格",
            "價錢",
            "收費",
            "月租",
            "月費",
            "月繳",
            "半年繳",
            "年繳",
            "年費",
            "一年",
        )
    )


def score_value_added_product_fee_evidence(
    query: str,
    doc: Dict[str, Any],
) -> int:
    """Score price evidence while respecting the requested payment period."""
    query_text = normalize_keyword_text(query)
    doc_text = normalize_keyword_text(doc_search_text(doc))
    if not doc_text or not any(marker in doc_text for marker in ("元", "$", "價格", "費用")):
        return 0

    score = 40
    requested_periods = []
    if any(marker in query_text for marker in ("年繳", "年費", "一年")):
        requested_periods.append(("年繳", "每年", "/年"))
    if "半年" in query_text:
        requested_periods.append(("半年繳", "半年", "/半年"))
    if any(marker in query_text for marker in ("月繳", "月租", "月費")):
        requested_periods.append(("月繳", "月租", "月費", "/月"))

    if requested_periods:
        matched_periods = sum(
            1
            for aliases in requested_periods
            if any(alias in doc_text for alias in aliases)
        )
        if matched_periods == 0:
            return 0
        score += matched_periods * 80

    if is_product_service_doc(doc):
        score += 100
    if product_metadata_value(doc, "record_type") == "product_service":
        score += 60
    if doc.get("_structured_product_profile"):
        score += 60
    return score


def product_metadata_value(doc: Dict[str, Any], field_name: str) -> str:
    source = doc.get("source") if isinstance(doc.get("source"), dict) else {}
    return str(doc.get(field_name) or source.get(field_name) or "").strip()


def is_product_service_doc(doc: Dict[str, Any]) -> bool:
    record_type = product_metadata_value(doc, "record_type")
    document_type = product_metadata_value(doc, "document_type")
    return record_type.startswith("product_service") or document_type == "product_service_catalog"


def product_service_doc_matches_query(query: str, doc: Dict[str, Any]) -> bool:
    entities = preferred_value_added_entities(query)
    if not entities or not is_product_service_doc(doc):
        return False

    product_text = " ".join([
        product_metadata_value(doc, "product_name"),
        product_metadata_value(doc, "product_aliases"),
        product_metadata_value(doc, "product_parent"),
    ])
    if not product_text.strip():
        product_text = doc_search_text(doc)
    normalized_product_text = normalize_keyword_text(product_text)
    specific_wifi_keys = {
        str(entity.get("key") or "")
        for entity in entities
    } & {"wifi_5", "wifi_6"}
    if specific_wifi_keys:
        compact_product_text = normalize_entity_identity(product_text)
        if not any(key.replace("_", "") in compact_product_text for key in specific_wifi_keys):
            return False

    for entity in entities:
        aliases = [entity.get("name"), *(entity.get("aliases") or [])]
        if any(normalize_keyword_text(alias) in normalized_product_text for alias in aliases):
            return True
    return False


def doc_mentions_value_added_product(query: str, doc: Dict[str, Any]) -> bool:
    """Match a product in any source row, including FAQ rows without profile metadata."""
    entities = preferred_value_added_entities(query)
    if not entities:
        return False
    specific_wifi_keys = {
        str(entity.get("key") or "")
        for entity in entities
    } & {"wifi_5", "wifi_6"}
    if specific_wifi_keys:
        compact_doc = normalize_entity_identity(doc_search_text(doc))
        if not any(key.replace("_", "") in compact_doc for key in specific_wifi_keys):
            return False
    normalized_doc = normalize_keyword_text(doc_search_text(doc))
    for entity in entities:
        aliases = [entity.get("name"), *(entity.get("aliases") or [])]
        if any(
            normalized_alias and normalized_alias in normalized_doc
            for alias in aliases
            if (normalized_alias := normalize_keyword_text(alias))
        ):
            return True
    return False


def is_hatv_addon_doc(doc: Dict[str, Any]) -> bool:
    if doc.get("_hatv_package_table"):
        return True
    text = normalize_keyword_text(doc_search_text(doc))
    if not text:
        return False
    if "哈tv" in text or "hatv" in text:
        return any(term in text for term in ("加購", "數位套餐", "加值套餐", "加值數位套餐", "數位電視"))
    return "數位套餐加購" in text or "加值數位套餐加購" in text


def is_value_added_catalog_doc(doc: Dict[str, Any]) -> bool:
    text = normalize_keyword_text(doc_search_text(doc))
    if not text:
        return False
    if any(term in text for term in ("單品銷售", "各項單品銷售", "數位電視套餐", "加值服務數位電視套餐")):
        return True
    has_value_added = any(term in text for term in ("加值服務", "加值套餐", "加購", "優惠專區", "vip會員"))
    has_price_list = any(term in text for term in ("月繳價格", "博斯套餐", "hbo加價購", "冠軍套餐", "hiplay全餐", "linetv", "wifi加值服務"))
    return has_value_added and has_price_list


def is_convenience_store_payment_guide_query(query: str) -> bool:
    normalized = normalize_keyword_text(query)
    if not normalized:
        return False

    has_store_machine = any(
        normalize_keyword_text(term) in normalized
        for term in ("ibon", "famiport", "超商繳費機", "便利商店機台", "繳費機")
    )
    has_payment_context = any(term in normalized for term in ("繳費", "繳款", "付款", "帳單"))
    has_guide_intent = any(term in normalized for term in ("教學", "操作", "流程", "步驟", "怎麼", "如何", "使用"))
    return has_store_machine and (has_payment_context or has_guide_intent)


def is_convenience_store_payment_guide_doc(doc: Dict[str, Any]) -> bool:
    text = normalize_keyword_text(doc_search_text(doc))
    if not text:
        return False
    has_machine = any(
        normalize_keyword_text(term) in text
        for term in CONVENIENCE_STORE_PAYMENT_GUIDE_TERMS
    )
    has_steps = any(term in text for term in ("繳費", "繳款", "列印繳費單", "持繳費單", "輸入用戶電話"))
    return has_machine and has_steps


def is_specific_convenience_store_payment_guide_doc(doc: Dict[str, Any]) -> bool:
    source = doc.get("source") if isinstance(doc.get("source"), dict) else {}
    title_text = " ".join([
        str(doc.get("question") or ""),
        str(doc.get("title") or ""),
        str(source.get("title") or ""),
    ])
    normalized_title = normalize_keyword_text(title_text)
    if not normalized_title:
        return False
    has_specific_machine = "ibon" in normalized_title or "famiport" in normalized_title
    has_guide_label = any(term in normalized_title for term in ("繳費教學", "機台操作", "操作教學"))
    return is_convenience_store_payment_guide_doc(doc) and (has_specific_machine or has_guide_label)


def is_basic_tv_fee_doc(doc: Dict[str, Any]) -> bool:
    text = doc_search_text(doc)
    normalized = normalize_keyword_text(text)
    has_tv_service = any(
        normalize_keyword_text(term) in normalized
        for term in ("有線電視", "第四台", "TV收視費", "基本收視費")
    )
    return has_tv_service and has_any_normalized_term(text, BASIC_TV_FEE_DOC_TERMS)


def is_pure_tv_rate_card_doc(doc: Dict[str, Any]) -> bool:
    """Keep only rate-card records for an explicit standalone cable-TV lookup."""
    source = doc.get("source") if isinstance(doc.get("source"), dict) else {}
    label = " ".join(
        str(value or "")
        for value in (
            doc.get("question"),
            doc.get("title"),
            source.get("title"),
            source.get("source"),
        )
    )
    normalized_label = normalize_keyword_text(label)
    return (
        is_basic_tv_fee_doc(doc)
        and any(term in normalized_label for term in ("基本收費標準", "有線電視基本收費"))
        and not is_campaign_activity_doc(doc)
    )


def score_query_relevance(query: str, doc: Dict[str, Any]) -> int:
    normalized_query = normalize_keyword_text(query)
    question = str(doc.get("question") or "")
    answer = str(doc.get("answer") or "")
    source = doc.get("source") if isinstance(doc.get("source"), dict) else {}
    source_title = str(source.get("title") or source.get("source") or "")
    normalized_question = normalize_keyword_text(question or source_title)
    normalized_answer = normalize_keyword_text(answer)

    if not normalized_query:
        return 0

    score = score_query_facet_evidence(query, doc)
    requested_products = detect_value_added_product_keys(query)
    if requested_products:
        if product_service_doc_matches_query(query, doc):
            score += 260
            if product_metadata_value(doc, "record_type") == "product_service":
                score += 40
        elif is_campaign_activity_doc(doc):
            score -= 140
    if normalized_query and normalized_query in normalized_question:
        score += 160
    elif normalized_question and normalized_question in normalized_query:
        if len(normalized_question) >= 6:
            score += 140
        else:
            score += 60

    matched_question_terms = 0
    for term in build_relevance_terms(query):
        if not term:
            continue
        if term in normalized_question:
            score += 12
            matched_question_terms += 1
        if term in normalized_answer:
            score += 3
            if term in HIGH_SIGNAL_ANSWER_TERMS:
                score += 10

    if matched_question_terms >= 2:
        score += 12
    if matched_question_terms >= 3:
        score += 18

    if str(doc.get("document_type") or "") == "promotion_campaign":
        score += 20
        score += campaign_occasion_relevance(query, doc)
        score += campaign_period_relevance(query, doc)
        normalized_aliases = [
            normalize_keyword_text(alias)
            for alias in str(doc.get("campaign_aliases") or "").split("|")
            if normalize_keyword_text(alias)
        ]
        if any(
            len(alias) >= 3 and alias in normalized_query
            for alias in normalized_aliases
        ):
            score += 180
        query_speeds = {
            normalize_keyword_text(f"{download}/{upload}")
            for download, upload in re.findall(
                r"(\d+(?:\.\d+)?\s*[MG])\s*/\s*(\d+(?:\.\d+)?\s*[MG])",
                str(query or ""),
                flags=re.IGNORECASE,
            )
        }
        document_speeds = normalize_keyword_text(doc.get("speeds") or "")
        if query_speeds and any(speed in document_speeds for speed in query_speeds):
            score += 80
        query_months = re.findall(r"(\d{1,3})\s*個?月", str(query or ""))
        document_months = {
            value.strip()
            for value in str(doc.get("contract_months") or "").split("|")
            if value.strip()
        }
        if query_months and any(month in document_months for month in query_months):
            score += 60
        for field_name, field_boost in (
            ("occasion_terms", 100),
            ("gift_items", 70),
            ("lottery_details", 90),
        ):
            raw_field_text = str(doc.get(field_name) or "")
            field_text = normalize_keyword_text(raw_field_text)
            field_values = [
                normalize_keyword_text(value)
                for value in raw_field_text.split("|")
                if normalize_keyword_text(value)
            ]
            direct_match = any(
                len(value) >= 2 and value in normalized_query
                for value in field_values
            )
            keyword_match = field_text and any(
                len(term) >= 2 and term in field_text
                for term in build_keyword_terms(query)
            )
            intent_match = (
                field_name == "gift_items"
                and has_any_normalized_term(
                    query,
                    ("贈品", "贈送", "送什麼", "好禮", "二擇一", "家電"),
                )
            ) or (
                field_name == "lottery_details"
                and has_any_normalized_term(
                    query,
                    ("抽獎", "摸彩", "中獎", "獎項", "獎品", "怎麼參加"),
                )
            )
            if field_text and (direct_match or keyword_match or intent_match):
                score += field_boost

    if is_generic_promotion_query(query):
        if is_campaign_activity_doc(doc):
            score += 60
            if is_internal_campaign_note_doc(doc):
                score -= 80
            if is_non_primary_campaign_doc(doc) and not is_non_primary_campaign_query(query):
                score -= 120
        elif is_generic_promotion_faq_doc(doc):
            score -= 35

    if is_tv_network_combo_query(query):
        if is_tv_network_combo_doc(doc):
            score += 220
        elif is_campaign_activity_doc(doc):
            score -= 160

    if is_basic_tv_fee_query(query):
        if is_basic_tv_fee_doc(doc):
            score += 80
            if any(term in normalized_query for term in ("一個月", "每月", "月租", "月費", "多少錢")):
                if "收視費" in normalized_answer and "月繳" in normalized_answer:
                    score += 45
        if is_campaign_activity_doc(doc):
            score -= 100

    if is_broadband_plan_price_query(query):
        if is_broadband_plan_price_doc(query, doc):
            score += 180
        else:
            score -= 120
        if any(term in normalized_answer for term in ("移機", "搬移", "室內移機", "室外移機")):
            score -= 180

    if is_restricted_channel_purchase_query(query):
        if is_restricted_channel_purchase_doc(doc):
            score += 180
        else:
            score -= 100
        if is_campaign_activity_doc(doc):
            score -= 120

    if is_digital_tv_package_purchase_query(query):
        if is_digital_tv_package_purchase_doc(doc):
            score += 180
        else:
            score -= 100
        if is_campaign_activity_doc(doc):
            score -= 120

    if is_value_added_catalog_query(query):
        if is_value_added_catalog_doc(doc):
            score += 100
        if is_campaign_activity_doc(doc):
            score -= 120

    if is_convenience_store_payment_guide_query(query):
        if is_convenience_store_payment_guide_doc(doc):
            score += 140
            if is_specific_convenience_store_payment_guide_doc(doc):
                score += 80
        elif is_campaign_activity_doc(doc):
            score -= 100
        else:
            score -= 30

    return score


def doc_search_text(doc: Dict[str, Any]) -> str:
    source = doc.get("source")
    source_text = ""
    if isinstance(source, dict):
        source_text = " ".join([
            str(source.get("title") or ""),
            str(source.get("source") or ""),
            str(source.get("file_name") or ""),
            str(source.get("document_type") or ""),
            str(source.get("campaign_name") or ""),
            str(source.get("campaign_aliases") or ""),
            str(source.get("campaign_sections") or ""),
            str(source.get("service_types") or ""),
            str(source.get("speeds") or ""),
            str(source.get("contract_months") or ""),
            str(source.get("payment_terms") or ""),
            str(source.get("customer_types") or ""),
            str(source.get("valid_period") or ""),
            str(source.get("occasion_terms") or ""),
            str(source.get("gift_items") or ""),
            str(source.get("lottery_details") or ""),
            str(source.get("product_catalog") or ""),
            str(source.get("product_name") or ""),
            str(source.get("product_aliases") or ""),
            str(source.get("product_parent") or ""),
            str(source.get("content") or ""),
        ])
    elif source:
        source_text = str(source)

    return " ".join([
        str(doc.get("question") or ""),
        str(doc.get("answer") or ""),
        str(doc.get("content") or ""),
        str(doc.get("title") or ""),
        str(doc.get("document_type") or ""),
        str(doc.get("campaign_name") or ""),
        str(doc.get("campaign_aliases") or ""),
        str(doc.get("campaign_sections") or ""),
        str(doc.get("service_types") or ""),
        str(doc.get("speeds") or ""),
        str(doc.get("contract_months") or ""),
        str(doc.get("payment_terms") or ""),
        str(doc.get("customer_types") or ""),
        str(doc.get("valid_period") or ""),
        str(doc.get("occasion_terms") or ""),
        str(doc.get("gift_items") or ""),
        str(doc.get("lottery_details") or ""),
        str(doc.get("product_catalog") or ""),
        str(doc.get("product_name") or ""),
        str(doc.get("product_aliases") or ""),
        str(doc.get("product_parent") or ""),
        source_text,
    ])


def has_any_normalized_term(text: str, terms: List[str] | tuple[str, ...]) -> bool:
    normalized = normalize_keyword_text(text)
    return any(normalize_keyword_text(term) in normalized for term in terms)


def is_social_discount_query(query: str) -> bool:
    return has_any_normalized_term(query, SOCIAL_DISCOUNT_TERMS)


def is_generic_promotion_query(query: str) -> bool:
    return (
        has_any_normalized_term(query, GENERIC_PROMOTION_TERMS)
        and not is_social_discount_query(query)
        and not has_any_normalized_term(query, BROADBAND_PLAN_PRICE_QUERY_TERMS)
    )


def is_pure_network_catalog_query(query: str) -> bool:
    """Return true when the customer is choosing a standalone broadband plan."""
    return (
        has_any_normalized_term(query, PURE_NETWORK_CATALOG_QUERY_TERMS)
        and not is_tv_network_combo_query(query)
    )


def is_pure_tv_catalog_query(query: str) -> bool:
    """Identify an explicit standalone cable-TV choice from the promotion menu."""
    return (
        has_any_normalized_term(query, PURE_TV_CATALOG_QUERY_TERMS)
        and not is_tv_network_combo_query(query)
    )


def is_campaign_discovery_query(query: str) -> bool:
    """Identify month/occasion discovery before expanded product terms hijack intent."""
    return (
        has_any_normalized_term(query, GENERIC_PROMOTION_TERMS)
        and not is_social_discount_query(query)
        and bool(extract_calendar_months(query) or extract_campaign_occasions(query))
    )


def campaign_metadata_value(doc: Dict[str, Any], field_name: str) -> str:
    source = doc.get("source") if isinstance(doc.get("source"), dict) else {}
    return str(doc.get(field_name) or source.get(field_name) or "").strip()


def extract_campaign_occasions(text: str) -> set[str]:
    normalized = normalize_keyword_text(text)
    if not normalized:
        return set()
    return {
        canonical
        for canonical, aliases in CAMPAIGN_OCCASION_ALIASES.items()
        if any(normalize_keyword_text(alias) in normalized for alias in aliases)
    }


def extract_calendar_months(text: str) -> set[int]:
    value = str(text or "")
    months = {
        int(match)
        for match in re.findall(r"(?<!\d)(1[0-2]|0?[1-9])\s*月", value)
    }
    normalized = normalize_keyword_text(value)
    for label, month in sorted(CHINESE_CALENDAR_MONTHS.items(), key=lambda item: -len(item[0])):
        normalized_label = normalize_keyword_text(label)
        if normalized_label in normalized:
            months.add(month)
            normalized = normalized.replace(normalized_label, "")
    return months


def extract_valid_period_months(valid_period: str) -> tuple[set[int], int | None]:
    value = str(valid_period or "")
    date_months = [
        int(month)
        for month in re.findall(r"(?:\d{2,4}\s*[./-]\s*)?(1[0-2]|0?[1-9])\s*[./-]\s*\d{1,2}", value)
    ]
    if not date_months:
        date_months = [
            int(month)
            for month in re.findall(r"(?:\d{2,4}\s*年\s*)?(1[0-2]|0?[1-9])\s*月", value)
        ]
    if not date_months:
        return set(), None

    start_month = date_months[0]
    if len(date_months) == 1:
        return {start_month}, start_month

    end_month = date_months[-1]
    if start_month <= end_month:
        return set(range(start_month, end_month + 1)), start_month
    return set(range(start_month, 13)) | set(range(1, end_month + 1)), start_month


def campaign_period_relevance(query: str, doc: Dict[str, Any]) -> int:
    query_months = extract_calendar_months(query)
    if not query_months:
        return 0
    valid_months, start_month = extract_valid_period_months(
        campaign_metadata_value(doc, "valid_period")
    )
    if not valid_months:
        return 0
    if start_month in query_months:
        return 260
    if query_months.intersection(valid_months):
        return 180
    return -180


def campaign_occasion_relevance(query: str, doc: Dict[str, Any]) -> int:
    query_occasions = extract_campaign_occasions(query)
    if not query_occasions:
        return 0
    doc_occasions = extract_campaign_occasions(
        " ".join(
            [
                campaign_metadata_value(doc, "occasion_terms"),
                campaign_metadata_value(doc, "campaign_name"),
                campaign_metadata_value(doc, "campaign_aliases"),
                str(doc.get("question") or ""),
                str(doc.get("title") or ""),
            ]
        )
    )
    return 320 if query_occasions.intersection(doc_occasions) else -240


def filter_campaigns_by_discovery_context(
    query: str,
    docs: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    campaign_docs = [doc for doc in docs if is_campaign_activity_doc(doc)]
    if not campaign_docs:
        return []

    query_occasions = extract_campaign_occasions(query)
    if query_occasions:
        occasion_docs = [
            doc for doc in campaign_docs
            if campaign_occasion_relevance(query, doc) > 0
        ]
        if occasion_docs:
            campaign_docs = occasion_docs

    query_months = extract_calendar_months(query)
    if query_months:
        period_docs = [
            doc for doc in campaign_docs
            if campaign_period_relevance(query, doc) > 0
        ]
        if period_docs:
            campaign_docs = period_docs

    return campaign_docs


def is_tv_network_combo_query(query: str) -> bool:
    normalized = normalize_keyword_text(query)
    if not normalized:
        return False
    has_hatv_hatnet_pair = "哈tv" in normalized and "哈net" in normalized
    combo_terms = (
        "第四台加網路",
        "第四台跟網路",
        "第四台和網路",
        "第四台與網路",
        "有線電視加網路",
        "電視加網路",
        "電視跟網路",
        "電視和網路",
        "電視與網路",
        "電視網路同裝",
        "電視+網路",
        "好視成雙",
    )
    if has_hatv_hatnet_pair:
        return True

    # Retrieval queries may describe the selected scope by explicitly
    # excluding the other service (for example, "排除電視+網路同裝方案").
    # Treat only non-negated occurrences as positive combo evidence.
    negation_terms = ("排除", "不含", "不要", "不用", "不是", "非", "不包括")
    for term in combo_terms:
        offset = 0
        while True:
            index = normalized.find(term, offset)
            if index < 0:
                break
            prefix = normalized[max(0, index - 8):index]
            if not any(negation in prefix for negation in negation_terms):
                return True
            offset = index + len(term)
    return False


def is_tv_network_combo_doc(doc: Dict[str, Any]) -> bool:
    normalized = normalize_keyword_text(doc_search_text(doc))
    return (
        "好視成雙" in normalized
        or "電視網路同裝" in normalized
        or "電視+網路" in normalized
        or "有線電視加網路" in normalized
    )


def is_pure_network_plan_doc(doc: Dict[str, Any]) -> bool:
    """Keep standalone broadband campaigns while excluding TV-plus-network bundles."""
    if is_tv_network_combo_doc(doc):
        return False

    text = doc_search_text(doc)
    normalized = normalize_keyword_text(text)
    service_types = normalize_keyword_text(campaign_metadata_value(doc, "service_types"))
    explicit_pure_terms = (
        "純網",
        "純寬頻",
        "單辦網路",
        "單裝網路",
        "單辦寬頻",
        "單裝寬頻",
        "網路贈清冰組",
        "清冰組",
        "哈net1",
    )
    if any(term in normalized for term in explicit_pure_terms):
        return True

    return any(term in service_types for term in ("寬頻", "網路"))


def is_social_discount_doc(doc: Dict[str, Any]) -> bool:
    return has_any_normalized_term(doc_search_text(doc), SOCIAL_DISCOUNT_TERMS)


def is_generic_promotion_faq_doc(doc: Dict[str, Any]) -> bool:
    return has_any_normalized_term(doc_search_text(doc), GENERIC_PROMOTION_FAQ_TERMS)


def is_internal_campaign_note_doc(doc: Dict[str, Any]) -> bool:
    return has_any_normalized_term(doc_search_text(doc), INTERNAL_CAMPAIGN_NOTE_TERMS)


def is_non_primary_campaign_doc(doc: Dict[str, Any]) -> bool:
    text = doc_search_text(doc)
    if has_any_normalized_term(text, ("非主推", "不主動推薦", "不要主推", "不建議主推", "售戶盡量不主推")):
        return True
    hidden_lines = [
        line
        for line in str(text or "").splitlines()
        if "隱藏版" in line
    ]
    if hidden_lines:
        hidden_rate_lines = [
            line for line in hidden_lines
            if re.search(r"(?:^|[\s：:、])(?:60M\s*/\s*60M|1G\s*/\s*1G|60M|1G)\b", line, flags=re.IGNORECASE)
        ]
        if len(hidden_rate_lines) != len(hidden_lines):
            return True
    if has_any_normalized_term(text, RESTRICTED_RATE_NOTE_TERMS):
        return not has_any_normalized_term(text, PRIMARY_CAMPAIGN_TERMS)
    return False


def is_non_primary_campaign_query(query: str) -> bool:
    return has_any_normalized_term(query, NON_PRIMARY_QUERY_TERMS)


def is_campaign_activity_doc(doc: Dict[str, Any]) -> bool:
    source = doc.get("source") if isinstance(doc.get("source"), dict) else {}
    if (
        str(doc.get("document_type") or source.get("document_type") or "") == "promotion_campaign"
        or str(doc.get("record_type") or source.get("record_type") or "").startswith("campaign_")
    ):
        return True

    text = doc_search_text(doc)
    normalized = normalize_keyword_text(text)

    if has_any_normalized_term(text, ("活動期間", "飆網守護", "好視成雙", "拆帳表")):
        return True
    if re.search(r"\bb\d{4}\b", normalized) or re.search(r"no\.?\d+", normalized):
        return True

    if "方案名稱" not in text or "活動" not in text:
        return False

    detail_matches = sum(
        1
        for term in PROMOTION_CAMPAIGN_REQUIRED_DETAIL_TERMS
        if normalize_keyword_text(term) in normalized
    )
    return detail_matches >= 2


def is_requested_campaign_doc(query: str, doc: Dict[str, Any]) -> bool:
    normalized_query = normalize_keyword_text(query)
    normalized_doc = normalize_keyword_text(doc_search_text(doc))

    campaign_code = re.search(r"\bb\d{4}\b", normalized_query)
    if campaign_code:
        return campaign_code.group(0) in normalized_doc

    if "飆網守護" in normalized_query:
        return "飆網守護" in normalized_doc

    if "好視成雙" in normalized_query:
        no_match = re.search(r"no\.?\d+", normalized_query)
        if no_match:
            return "好視成雙" in normalized_doc and no_match.group(0).replace(".", "") in normalized_doc.replace(".", "")
        return "好視成雙" in normalized_doc

    source = doc.get("source") if isinstance(doc.get("source"), dict) else {}
    aliases = str(
        doc.get("campaign_aliases")
        or source.get("campaign_aliases")
        or ""
    ).split("|")
    for alias in aliases:
        normalized_alias = normalize_keyword_text(alias)
        if len(normalized_alias) >= 3 and normalized_alias in normalized_query:
            return normalized_alias in normalized_doc

    return False


def filter_docs_for_query_intent(query: str, docs: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    if not docs:
        return docs
    product_keys = detect_value_added_product_keys(query)
    query_facets = detect_query_facets(query)
    # A named digital-TV package add-on needs two evidence types: the named
    # package and the common set-top-box purchase flow. Handle it before
    # generic product/facet filters can discard either one.
    if is_digital_tv_package_purchase_query(query):
        purchase_docs = [
            doc for doc in docs
            if is_digital_tv_package_purchase_doc(doc)
        ]
        if purchase_docs:
            return purchase_docs

    # This must precede the single-product 哈TV branch below.  When the
    # customer explicitly names both 哈TV and 哈NET, an add-on-only document
    # is adjacent knowledge, not evidence for a combined-service answer.
    if is_tv_network_combo_query(query):
        combo_docs = [
            doc for doc in docs
            if is_tv_network_combo_doc(doc)
            and not is_internal_campaign_note_doc(doc)
            and not is_social_discount_doc(doc)
            and (is_non_primary_campaign_query(query) or not is_non_primary_campaign_doc(doc))
        ]
        if combo_docs:
            return combo_docs

    if is_pure_network_catalog_query(query):
        pure_network_docs = [
            doc for doc in docs
            if is_pure_network_plan_doc(doc)
            and not is_internal_campaign_note_doc(doc)
            and not is_social_discount_doc(doc)
            and (
                is_non_primary_campaign_query(query)
                or not is_non_primary_campaign_doc(doc)
            )
        ]
        if pure_network_docs:
            return pure_network_docs

    if is_pure_tv_catalog_query(query):
        return [
            doc for doc in docs
            if is_pure_tv_rate_card_doc(doc)
            and not is_social_discount_doc(doc)
        ]

    package_key = detect_hatv_package_key(query)
    if package_key:
        package_marker = f"哈tv{package_key.lower()}套餐"
        package_docs = [
            doc for doc in docs
            if doc.get("_hatv_package_table")
            or package_marker in normalize_keyword_text(doc_search_text(doc)).replace("-", "")
        ]
        if package_docs:
            return package_docs

    if is_convenience_store_payment_guide_query(query):
        guide_docs = [
            doc for doc in docs
            if is_convenience_store_payment_guide_doc(doc)
        ]
        specific_guide_docs = [
            doc for doc in guide_docs
            if is_specific_convenience_store_payment_guide_doc(doc)
        ]
        if specific_guide_docs:
            return specific_guide_docs
        if guide_docs:
            return guide_docs

    if is_hatv_addon_info_query(query):
        hatv_docs = [
            doc for doc in docs
            if is_hatv_addon_doc(doc)
        ]
        if hatv_docs:
            return hatv_docs
        non_campaign_docs = [
            doc for doc in docs
            if not is_campaign_activity_doc(doc)
        ]
        if non_campaign_docs:
            return non_campaign_docs

    # An explicit standalone cable-TV fee question is narrower than the broad
    # fee facets below. Resolve it first so campaign documents containing many
    # prices cannot outrank the actual basic rate card.
    if is_basic_tv_fee_query(query) and not product_keys and not query_facets:
        non_campaign_docs = [
            doc for doc in docs
            if not is_campaign_activity_doc(doc)
        ]
        basic_docs = [
            doc for doc in non_campaign_docs
            if is_basic_tv_fee_doc(doc)
        ]
        if basic_docs:
            return basic_docs
        # Returning no candidates lets the caller run the full keyword scan and
        # recover the rate-card document instead of using unrelated fee content.
        return []

    # A named value-added product is a stronger anchor than generic facets
    # such as "annual fee" or "price".  Let the product branch below narrow
    # the candidates first; otherwise an unrelated document with more fee
    # wording can win before the requested product is considered.
    if is_broadband_plan_price_query(query):
        price_docs = [doc for doc in docs if is_broadband_plan_price_doc(query, doc)]
        if price_docs:
            return price_docs

    if query_facets and not product_keys:
        scored_docs = [
            (score_query_facet_evidence(query, doc), doc)
            for doc in docs
        ]
        best_score = max((score for score, _doc in scored_docs), default=0)
        if best_score >= 120:
            evidence_docs = [
                doc
                for score, doc in scored_docs
                if score >= max(120, best_score - 80)
            ]
            if evidence_docs:
                return evidence_docs

    # Controller query expansion may append examples such as LINE TV and POINTS
    # to a broad month/holiday promotion question. Select campaign documents
    # first so those helper terms cannot turn discovery into a product query.
    if is_campaign_discovery_query(query):
        campaign_docs = [
            doc for doc in docs
            if is_campaign_activity_doc(doc)
            and not is_social_discount_doc(doc)
            and not is_internal_campaign_note_doc(doc)
        ]
        contextual_campaign_docs = filter_campaigns_by_discovery_context(
            query,
            campaign_docs,
        )
        if contextual_campaign_docs:
            campaign_docs = contextual_campaign_docs
        if campaign_docs and not is_non_primary_campaign_query(query):
            campaign_docs = [
                doc for doc in campaign_docs
                if not is_non_primary_campaign_doc(doc)
            ]
        if campaign_docs:
            return campaign_docs

    if product_keys:
        requested_campaign_docs = [
            doc for doc in docs
            if is_requested_campaign_doc(query, doc)
        ]
        if requested_campaign_docs:
            return requested_campaign_docs

        product_docs = [
            doc for doc in docs
            if product_service_doc_matches_query(query, doc)
            and not is_campaign_activity_doc(doc)
        ]
        if is_value_added_product_fee_query(query):
            scored_fee_docs = sorted(
                (
                    (score_value_added_product_fee_evidence(query, doc), doc)
                    for doc in product_docs
                ),
                key=lambda item: item[0],
                reverse=True,
            )
            fee_docs = [doc for score, doc in scored_fee_docs if score > 0]
            if fee_docs:
                return fee_docs

        # A specific FAQ row (for example cancellation or device limits) carries
        # stronger evidence than a generated product overview. Keep those rows
        # before narrowing the result to structured product profiles.
        specific_product_docs = [
            doc for doc in docs
            if doc_mentions_value_added_product(query, doc)
            and not is_campaign_activity_doc(doc)
            and (
                # One distinctive action/state bigram in an FAQ question is
                # enough to beat a generated product overview.  Product-only
                # queries such as "LINE TV 費用" do not receive this signal.
                score_query_question_text_evidence(query, doc) >= 100
                or score_query_facet_evidence(query, doc) >= 120
            )
        ]
        if specific_product_docs:
            return specific_product_docs

        derived_product_docs = [
            doc for doc in product_docs
            if product_metadata_value(doc, "record_type") == "product_service"
        ]
        if derived_product_docs:
            return derived_product_docs
        if product_docs:
            return product_docs

    if is_value_added_catalog_query(query):
        catalog_docs = [
            doc for doc in docs
            if is_value_added_catalog_doc(doc) and not is_campaign_activity_doc(doc)
        ]
        if catalog_docs:
            return catalog_docs
        non_campaign_docs = [
            doc for doc in docs
            if not is_campaign_activity_doc(doc)
        ]
        if non_campaign_docs:
            return non_campaign_docs

    if is_broadband_plan_price_query(query):
        price_docs = [
            doc for doc in docs
            if is_broadband_plan_price_doc(query, doc)
        ]
        if price_docs:
            return price_docs

    if is_restricted_channel_purchase_query(query):
        purchase_docs = [
            doc for doc in docs
            if is_restricted_channel_purchase_doc(doc)
        ]
        if purchase_docs:
            return purchase_docs

    requested_campaign_docs = [
        doc for doc in docs
        if is_requested_campaign_doc(query, doc)
    ]
    if requested_campaign_docs:
        return requested_campaign_docs

    if is_generic_promotion_query(query):
        non_social_docs = [doc for doc in docs if not is_social_discount_doc(doc)]
        campaign_docs = [doc for doc in non_social_docs if is_campaign_activity_doc(doc)]
        contextual_campaign_docs = filter_campaigns_by_discovery_context(query, campaign_docs)
        if contextual_campaign_docs:
            campaign_docs = contextual_campaign_docs
        if campaign_docs and not is_non_primary_campaign_query(query):
            campaign_docs = [
                doc for doc in campaign_docs
                if not is_non_primary_campaign_doc(doc)
            ]
        if campaign_docs:
            customer_facing_docs = [
                doc for doc in campaign_docs
                if not is_internal_campaign_note_doc(doc)
            ]
            return customer_facing_docs if customer_facing_docs else []
        # A broad promotion question must not be answered from a merely
        # promotion-adjacent document (for example a LINE TV add-on or a gift
        # fragment).  Returning no candidates lets the keyword fallback scan
        # the indexed campaign profiles instead of fabricating a campaign list.
        if is_non_primary_campaign_query(query):
            return [
                doc for doc in non_social_docs
                if not is_generic_promotion_faq_doc(doc)
                and not is_internal_campaign_note_doc(doc)
            ]
        return []
    return docs


def query_relevance_bucket(score: Any) -> int:
    try:
        value = int(score or 0)
    except (TypeError, ValueError):
        value = 0
    if value >= 20:
        return 2
    if value >= 8:
        return 1
    return 0


def score_query_anchor_evidence(query: str, doc: Dict[str, Any]) -> int:
    """Score exact subject phrases without rewarding generic action words."""
    normalized_doc = normalize_keyword_text(doc_search_text(doc))
    if not normalized_doc:
        return 0

    score = 0
    for anchor in extract_query_anchor_terms(query):
        if anchor in normalized_doc:
            score += min(len(anchor), 16)
    return score


def score_query_direct_text_evidence(query: str, doc: Dict[str, Any]) -> int:
    """Score literal query evidence before applying knowledge-base scope priority.

    Semantic similarity can return a locally scoped but unrelated document.  A
    common knowledge-base document that literally contains an error code or the
    distinctive subject of the question is stronger evidence and must survive
    the final top-k ranking.
    """
    normalized_doc = normalize_keyword_text(doc_search_text(doc))
    if not normalized_doc:
        return 0

    score = 0
    identifiers = extract_query_strict_identifier_terms(query)
    matched_identifiers = {
        identifier for identifier in identifiers if identifier in normalized_doc
    }
    if matched_identifiers:
        score += 1000 + (len(matched_identifiers) * 100)
        if matched_identifiers == identifiers:
            score += 200

    anchors = {
        normalize_keyword_text(anchor)
        for anchor in extract_query_anchor_terms(query)
        if normalize_keyword_text(anchor)
    }
    matched_anchor_lengths = [
        len(anchor) for anchor in anchors if anchor in normalized_doc
    ]
    if matched_anchor_lengths:
        score += 300 + (min(max(matched_anchor_lengths), 20) * 10)

    subject_tokens = extract_query_subject_evidence_bigrams(query)
    source = doc.get("source") if isinstance(doc.get("source"), dict) else {}
    normalized_question = normalize_keyword_text(
        doc.get("question") or source.get("title") or ""
    )
    question_overlap = len(
        subject_tokens.intersection(_cjk_bigrams(normalized_question))
    )
    subject_overlap = len(subject_tokens.intersection(_cjk_bigrams(normalized_doc)))

    # A single distinctive state/action phrase in the source question is strong
    # evidence.  This separates rows such as "LINE TV 取消" from campaign
    # documents that merely mention LINE TV in their answer.  Matches found only
    # in the full document still require two bigrams to avoid broad one-word hits.
    if question_overlap:
        score += 220 + (min(question_overlap, 10) * 40)
        if subject_tokens:
            score += int(100 * question_overlap / len(subject_tokens))
    elif subject_overlap >= 2:
        score += 200 + (min(subject_overlap, 10) * 20)

    return score


def score_query_question_text_evidence(query: str, doc: Dict[str, Any]) -> int:
    """Score distinctive query wording found in the source question/title.

    This signal is intentionally separate from full-document evidence.  It is
    allowed to outrank knowledge-base scope only when the FAQ question itself
    contains the customer's state or action, such as ``取消`` or ``沒亮``.
    Merely mentioning the same product somewhere in an answer is not enough.
    """
    subject_tokens = extract_query_subject_evidence_bigrams(query)
    if not subject_tokens:
        return 0
    source = doc.get("source") if isinstance(doc.get("source"), dict) else {}
    normalized_question = normalize_keyword_text(
        doc.get("question") or source.get("title") or ""
    )
    overlap = len(subject_tokens.intersection(_cjk_bigrams(normalized_question)))
    if not overlap:
        return 0
    return (overlap * 100) + int(100 * overlap / len(subject_tokens))


def build_question_paraphrase_terms(query: str) -> List[str]:
    """Return precise query paraphrases suitable for FAQ-question matching.

    These are deliberately narrower than ``build_keyword_terms``.  Broad
    product/facet expansions are useful when scanning documents, but allowing
    them to promote FAQ rows would make any row containing words such as
    ``機上盒`` or ``費用`` look exact.  Only wording-level paraphrases belong
    here.
    """
    normalized = normalize_keyword_text(query)
    aliases: List[str] = []
    normalized_aliases = {
        "信用卡": ("刷卡", "線上刷卡"),
        "刷卡": ("信用卡", "線上刷卡"),
        "退租": ("辦理退租", "取消服務"),
        "停機": ("暫停", "暫停機", "暫停收視", "暫停收看"),
        "暫停機": ("停機", "暫停", "暫停收視", "暫停收看"),
        "身分證": ("身份證",),
        "身份證": ("身分證",),
        "世足": ("世界盃", "足球賽", "fifa"),
        "世界盃": ("世足", "足球賽", "fifa"),
        "fifa": ("世界盃", "世足", "足球賽"),
        "錄節目": ("錄影", "錄製節目"),
        "錄影": ("錄節目", "錄製節目"),
        "分期付款": ("繳費分期",),
        "繳費分期": ("分期付款",),
    }
    for source_term, values in normalized_aliases.items():
        if normalize_keyword_text(source_term) not in normalized:
            continue
        for value in values:
            normalized_value = normalize_keyword_text(value)
            if normalized_value and normalized_value not in aliases:
                aliases.append(normalized_value)

    # Preserve the number while translating the customer's comparative phrase
    # into wording commonly used by channel-list FAQ rows.
    for channel_no in re.findall(r"超過\s*(\d+)\s*台", str(query or "")):
        for value in (f"{channel_no}台以後", f"{channel_no}台之後"):
            normalized_value = normalize_keyword_text(value)
            if normalized_value not in aliases:
                aliases.append(normalized_value)
    return aliases


def score_query_question_paraphrase_evidence(
    query: str,
    doc: Dict[str, Any],
) -> int:
    """Score generated query paraphrases found in a source FAQ question."""
    aliases = build_question_paraphrase_terms(query)
    if not aliases or not is_faq_row_candidate(doc):
        return 0
    source = doc.get("source") if isinstance(doc.get("source"), dict) else {}
    normalized_question = normalize_keyword_text(
        doc.get("question") or source.get("title") or ""
    )
    matched = [alias for alias in aliases if alias in normalized_question]
    if not matched:
        return 0
    return 300 + sum(min(len(alias), 20) * 10 for alias in matched)


def is_faq_row_candidate(doc: Dict[str, Any]) -> bool:
    """Return whether a candidate represents one source FAQ row.

    CSV FAQ rows carry a much more precise customer-facing question than a
    generic document chunk.  Keeping this distinction in the ranker prevents
    an answer that merely repeats a broad word (for example ``機上盒``) from
    hiding the row whose question actually matches the customer's intent.
    """
    source = doc.get("source") if isinstance(doc.get("source"), dict) else {}
    section = str(source.get("section") or "").strip().lower()
    question = str(doc.get("question") or source.get("title") or "").strip()
    answer = str(doc.get("answer") or source.get("content") or "").strip()
    return bool(question and answer and re.search(r"(?:^|\s)row\s+\d+", section))


def has_strong_faq_question_match(doc: Dict[str, Any]) -> bool:
    """Identify FAQ rows supported by question-side relevance evidence."""
    if not is_faq_row_candidate(doc):
        return False
    return bool(
        int(doc.get("_query_paraphrase_question_score") or 0) >= 300
        or
        int(doc.get("_query_question_evidence_score") or 0) >= 100
        or int(doc.get("_query_relevance_score") or 0) >= 24
        or int(doc.get("_keyword_score") or 0) >= 10
    )


def has_precise_question_side_match(query: str, doc: Dict[str, Any]) -> bool:
    """Return whether a result question/title covers the concrete user ask.

    Product names alone are intentionally insufficient.  A campaign title such
    as ``LINE TV 新裝優惠`` is related to LINE TV, but it does not answer how
    to scan a QR code.  Exact wording, a supported FAQ paraphrase, or substantial
    state/action overlap is required before semantic results may suppress the
    local FAQ scan.
    """
    source = doc.get("source") if isinstance(doc.get("source"), dict) else {}
    normalized_query = normalize_keyword_text(query)
    normalized_question = normalize_keyword_text(
        doc.get("question") or source.get("title") or ""
    )
    if not normalized_query or not normalized_question:
        return False
    if normalized_query == normalized_question:
        return True
    if len(normalized_query) >= 6 and normalized_query in normalized_question:
        return True
    if score_query_question_paraphrase_evidence(query, doc) >= 300:
        return True

    subject_tokens = extract_query_subject_evidence_bigrams(query)
    if not subject_tokens:
        return False
    overlap = len(subject_tokens.intersection(_cjk_bigrams(normalized_question)))
    coverage = overlap / len(subject_tokens)

    # One distinctive phrase is enough for an actual FAQ row; generated plan
    # titles need broader coverage so a shared product name cannot hide a more
    # precise row elsewhere in the source documents.
    if is_faq_row_candidate(doc):
        return overlap >= 1 and coverage >= 0.2
    return overlap >= 2 and coverage >= 0.4


def has_query_strict_identifier_match(query: str, doc: Dict[str, Any]) -> bool:
    """Keep exact codes/model identifiers above all softer FAQ signals."""
    identifiers = extract_query_strict_identifier_terms(query)
    if not identifiers:
        return False
    normalized_doc = normalize_keyword_text(doc_search_text(doc))
    return any(identifier in normalized_doc for identifier in identifiers)


def sort_docs_by_company_priority(
    docs: List[Dict[str, Any]],
    memory: Dict[str, Any],
    query: str = "",
) -> List[Dict[str, Any]]:
    prefer_exact_subject = has_stable_query_subject_anchor(query)
    for doc in docs:
        if query and doc.get("_query_relevance_score") is None:
            doc["_query_relevance_score"] = score_query_relevance(query, doc)
        if query:
            doc["_query_anchor_score"] = score_query_anchor_evidence(query, doc)
            doc["_query_question_evidence_score"] = score_query_question_text_evidence(
                query,
                doc,
            )
            doc["_query_paraphrase_question_score"] = (
                score_query_question_paraphrase_evidence(query, doc)
            )
            doc["_query_direct_evidence_score"] = score_query_direct_text_evidence(
                query,
                doc,
            )
            doc["_query_strict_identifier_match"] = has_query_strict_identifier_match(
                query,
                doc,
            )

    return sorted(
        docs,
        key=lambda doc: (
            -int(bool(doc.get("_query_strict_identifier_match"))),
            -int(bool(doc.get("_query_paraphrase_question_score"))),
            -int(prefer_exact_subject and bool(doc.get("_query_anchor_score"))),
            -int(bool(doc.get("_query_question_evidence_score"))),
            knowledge_base_priority(doc_knowledge_base(doc), memory),
            -int(doc.get("_query_paraphrase_question_score") or 0),
            -int(doc.get("_query_question_evidence_score") or 0),
            -int(has_strong_faq_question_match(doc)),
            -query_relevance_bucket(doc.get("_query_relevance_score")),
            -int(doc.get("_query_relevance_score") or 0),
            -int(doc.get("_keyword_score") or 0),
            -int(bool(doc.get("_query_direct_evidence_score"))),
            -int(doc.get("_query_direct_evidence_score") or 0),
            -int(doc.get("_query_anchor_score") or 0),
            float(doc.get("_distance", 999)) if doc.get("_distance") is not None else 999,
            -float(doc.get("_score", 0) or 0),
        ),
    )


def doc_dedupe_key(doc: Dict[str, Any]) -> str:
    source = doc.get("source") if isinstance(doc.get("source"), dict) else {}
    source_name = str(source.get("source") or doc.get("source") or "").strip()
    section = str(source.get("section") or "").strip()
    question = normalize_keyword_text(doc.get("question") or source.get("title") or "")
    answer = normalize_keyword_text(doc.get("answer") or source.get("content") or "")
    if source_name and question and answer:
        return f"source:{source_name}|q:{question}|a:{answer[:160]}"
    if source_name and section and (question or answer):
        return f"source:{source_name}|section:{section}|q:{question}|a:{answer[:120]}"
    if question and answer:
        return f"qa:{question}|a:{answer[:160]}"
    return f"id:{doc.get('id') or source.get('chunk_id') or id(doc)}"


def dedupe_retrieved_docs(docs: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    deduped: Dict[str, Dict[str, Any]] = {}
    for doc in docs:
        key = doc_dedupe_key(doc)
        current = deduped.get(key)
        if current is None:
            deduped[key] = doc
            continue

        def rank(value: Dict[str, Any]) -> tuple:
            distance = value.get("_distance")
            return (
                int(value.get("_query_relevance_score") or 0),
                int(value.get("_keyword_score") or 0),
                -float(distance) if distance is not None else -999,
                float(value.get("_score") or 0),
            )

        if rank(doc) > rank(current):
            deduped[key] = doc
    return list(deduped.values())


def build_rag_payload(
    plan_name: str,
    knowledge_base: str,
    limit: int,
) -> Dict[str, Any]:
    return {
        "plan_name": plan_name,
        "knowledge_base": knowledge_base,
        "limit": limit,
        "include_expired": RAG_API_INCLUDE_EXPIRED,
    }


def normalize_rag_source(source: Dict[str, Any], plan_name: str, knowledge_base: str) -> Dict[str, Any]:
    doc_id = source.get("chunk_id") or source.get("document_id") or source.get("id")
    question = source.get("title") or source.get("source") or plan_name
    answer = source.get("content") or source.get("answer") or ""
    return {
        "id": doc_id,
        "question": question,
        "answer": answer,
        "company": source.get("knowledge_base") or knowledge_base,
        "category": source.get("category"),
        "record_type": source.get("record_type"),
        "document_type": source.get("document_type"),
        "campaign_name": source.get("campaign_name"),
        "campaign_aliases": source.get("campaign_aliases"),
        "campaign_sections": source.get("campaign_sections"),
        "service_types": source.get("service_types"),
        "speeds": source.get("speeds"),
        "contract_months": source.get("contract_months"),
        "payment_terms": source.get("payment_terms"),
        "customer_types": source.get("customer_types"),
        "valid_period": source.get("valid_period"),
        "occasion_terms": source.get("occasion_terms"),
        "gift_items": source.get("gift_items"),
        "lottery_details": source.get("lottery_details"),
        "product_catalog": source.get("product_catalog"),
        "product_name": source.get("product_name"),
        "product_aliases": source.get("product_aliases"),
        "product_parent": source.get("product_parent"),
        "_score": source.get("score"),
        "source": source,
    }


def normalize_rag_response(data: Dict[str, Any], plan_name: str, knowledge_base: str) -> List[Dict[str, Any]]:
    sources = data.get("sources")
    if not isinstance(sources, list):
        return []

    docs = []
    for source in sources:
        if isinstance(source, dict):
            docs.append(normalize_rag_source(source, plan_name, knowledge_base))
    return docs


def _doc_source_document_id(doc: Dict[str, Any]) -> str:
    source = doc.get("source") if isinstance(doc.get("source"), dict) else {}
    return str(
        doc.get("document_id")
        or source.get("document_id")
        or ""
    ).strip()


def manifest_document_statuses() -> Optional[Dict[str, Dict[str, str]]]:
    manifest_path = Path(RAG_LOCAL_MANIFEST_PATH)
    if not manifest_path.exists():
        return None

    try:
        data = json.loads(manifest_path.read_text(encoding="utf-8-sig"))
    except Exception:
        return None

    documents = data.get("documents") if isinstance(data, dict) else None
    if not isinstance(documents, list):
        return None

    statuses: Dict[str, Dict[str, str]] = {}
    for document in documents:
        if not isinstance(document, dict):
            continue
        document_id = str(document.get("id") or "").strip()
        if document_id:
            statuses[document_id] = {
                "status": str(document.get("status", "active") or "active"),
                "processing_status": str(document.get("processing_status") or ""),
                "knowledge_base": str(document.get("knowledge_base") or DEFAULT_RAG_KNOWLEDGE_BASE),
            }

    return statuses


def filter_docs_to_active_manifest_sources(
    docs: List[Dict[str, Any]],
    knowledge_bases: Optional[List[str]] = None,
) -> List[Dict[str, Any]]:
    statuses = manifest_document_statuses()
    if statuses is None:
        return docs

    allowed_bases = set(knowledge_bases or [])
    filtered = []
    rejected_ids = []
    for doc in docs:
        document_id = _doc_source_document_id(doc)
        if not document_id:
            filtered.append(doc)
            continue

        document_status = statuses.get(document_id)
        if document_status is None:
            filtered.append(doc)
            continue

        if (
            document_status.get("status") != "active"
            or document_status.get("processing_status") == "deleted"
            or (
                allowed_bases
                and document_status.get("knowledge_base") not in allowed_bases
            )
        ):
            rejected_ids.append(document_id)
            continue
        filtered.append(doc)

    if rejected_ids:
        print(
            "[KB] filtered stale retrieved document ids: "
            + ", ".join(sorted(set(rejected_ids)))
        )
    return filtered


def call_rag_api(payload: Dict[str, Any]) -> Dict[str, Any]:
    response = requests.post(
        RAG_API_URL,
        json=payload,
        timeout=RAG_API_TIMEOUT_SECONDS,
    )
    if response.status_code != 200:
        return {}
    try:
        data = response.json()
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


_LOCAL_SEARCHER = None
_LOCAL_SEARCHER_PREWARM_THREAD = None
_LOCAL_INDEX_REPAIR_LOCK = threading.Lock()
_LOCAL_SEARCHER_DEGRADED = False
_LOCAL_SEARCHER_DEGRADED_REASON = ""


def mark_local_searcher_degraded(reason: Any) -> None:
    global _LOCAL_SEARCHER_DEGRADED, _LOCAL_SEARCHER_DEGRADED_REASON
    _LOCAL_SEARCHER_DEGRADED = True
    _LOCAL_SEARCHER_DEGRADED_REASON = str(reason or "Local Chroma index unavailable")


def clear_local_searcher_degraded() -> None:
    global _LOCAL_SEARCHER_DEGRADED, _LOCAL_SEARCHER_DEGRADED_REASON
    _LOCAL_SEARCHER_DEGRADED = False
    _LOCAL_SEARCHER_DEGRADED_REASON = ""


def reset_local_searcher_cache(*, clear_degraded: bool = True) -> None:
    global _LOCAL_SEARCHER, _KNOWLEDGE_ENTITY_CATALOG_SIGNATURE, _KNOWLEDGE_ENTITY_CATALOG
    searcher = _LOCAL_SEARCHER
    _LOCAL_SEARCHER = None
    if searcher is not None:
        close = getattr(searcher, "close", None)
        if callable(close):
            try:
                close()
            except Exception as exc:
                print(f"[KB] Failed to close cached local searcher: {exc}")
    if clear_degraded:
        clear_local_searcher_degraded()
    with _KNOWLEDGE_ENTITY_CATALOG_LOCK:
        _KNOWLEDGE_ENTITY_CATALOG_SIGNATURE = None
        _KNOWLEDGE_ENTITY_CATALOG = []


def is_local_chroma_index_error(exc: Exception) -> bool:
    message = str(exc).lower()
    return (
        "hnsw" in message
        or "error in compaction" in message
        or "error loading hnsw index" in message
        or "constructing hnsw segment reader" in message
        or "error sending backfill request to compactor" in message
    )


def is_local_chroma_transient_compaction_error(exc: Exception) -> bool:
    message = str(exc).lower()
    persistent_index_error = (
        "error loading hnsw index" in message
        or "constructing hnsw segment reader" in message
    )
    return (
        not persistent_index_error
        and (
            "error sending backfill request to compactor" in message
            or ("backfill" in message and "compactor" in message)
        )
    )


def local_kb_runtime_snapshot() -> Dict[str, Any]:
    manifest_path = Path(RAG_LOCAL_MANIFEST_PATH)
    docs_path = Path(RAG_LOCAL_DOCS_DIR)
    persist_path = Path(RAG_LOCAL_PERSIST_DIR)
    documents: List[Dict[str, Any]] = []

    if manifest_path.exists():
        try:
            data = json.loads(manifest_path.read_text(encoding="utf-8"))
            if isinstance(data, dict) and isinstance(data.get("documents"), list):
                documents = [item for item in data["documents"] if isinstance(item, dict)]
        except Exception as exc:
            return {
                "manifest_path": str(manifest_path),
                "manifest_exists": True,
                "manifest_error": str(exc),
                "docs_dir": str(docs_path),
                "docs_dir_exists": docs_path.exists(),
                "persist_dir": str(persist_path),
                "persist_dir_exists": persist_path.exists(),
            }

    active_documents = [
        item for item in documents
        if item.get("status", "active") == "active"
        and item.get("processing_status") != "deleted"
    ]
    indexed_active_documents = [
        item for item in active_documents
        if item.get("processing_status") == "indexed"
    ]
    return {
        "manifest_path": str(manifest_path),
        "manifest_exists": manifest_path.exists(),
        "docs_dir": str(docs_path),
        "docs_dir_exists": docs_path.exists(),
        "persist_dir": str(persist_path),
        "persist_dir_exists": persist_path.exists(),
        "total_documents": len(documents),
        "active_documents": len(active_documents),
        "indexed_active_documents": len(indexed_active_documents),
    }


LOCAL_CHROMA_REPAIR_STRATEGY = "archive-and-rebuild-single-session-v4"


def repair_local_chroma_index() -> bool:
    with _LOCAL_INDEX_REPAIR_LOCK:
        try:
            from app.services.kb_admin_service import (
                kb_index_write_lock,
                refresh_restored_chroma_store_from_manifest_delta,
                rebuild_active_index,
                restore_chroma_store_from_backup,
            )

            print(f"[KB] Local Chroma repair strategy: {LOCAL_CHROMA_REPAIR_STRATEGY}")

            # The lock file lives outside chroma_db, so replacing that whole
            # directory cannot remove the lock. Re-probe after acquiring it:
            # another worker may already have completed the repair.
            with kb_index_write_lock():
                reset_local_searcher_cache(clear_degraded=False)
                probe = None
                try:
                    probe = load_local_searcher()
                    probe.search("知識庫索引健康檢查", top_k=1)
                    clear_local_searcher_degraded()
                    print("[KB] Local Chroma repair skipped: index is already healthy.")
                    return True
                except Exception as probe_exc:
                    if is_local_chroma_transient_compaction_error(probe_exc):
                        print(
                            "[KB] Local Chroma repair deferred: transient "
                            f"compactor/backfill error during health check: {probe_exc}"
                        )
                        reset_local_searcher_cache(clear_degraded=False)
                        return False
                    if not is_local_chroma_index_error(probe_exc):
                        print(f"[KB] Local Chroma health check failed without HNSW error: {probe_exc}")
                        reset_local_searcher_cache()
                        return False
                    print(f"[KB] Local Chroma corruption confirmed: {probe_exc}")
                    # Keep new requests from reopening the damaged store while
                    # Windows file handles are being released and replaced.
                    mark_local_searcher_degraded("Local Chroma repair in progress")
                finally:
                    # Do not retain a KBSearcher while the physical Chroma
                    # directory is archived on Windows.
                    probe = None
                    reset_local_searcher_cache(clear_degraded=False)

                before = local_kb_runtime_snapshot()
                print(f"[KB] Local Chroma repair starting: {before}")
                active_count = int(before.get("active_documents") or 0)
                if active_count <= 0:
                    print("[KB] Local Chroma repair aborted: no active KB documents found in manifest.")
                    return False

                try:
                    restore_summary = restore_chroma_store_from_backup(_lock_held=True)
                    if restore_summary.get("restored"):
                        print(
                            "[KB] Local Chroma restored from healthy backup: "
                            f"{restore_summary}"
                        )
                        if restore_summary.get("manifest_matches") is False:
                            delta_summary = refresh_restored_chroma_store_from_manifest_delta(
                                restore_summary,
                                _lock_held=True,
                            )
                            print(
                                "[KB] Local Chroma backup restore delta refreshed: "
                                f"{delta_summary}"
                            )
                        reset_local_searcher_cache(clear_degraded=False)
                        verified = load_local_searcher()
                        verified.search("知識庫索引備份還原驗證", top_k=1)
                        clear_local_searcher_degraded()
                        print(
                            "[KB] Local Chroma backup restore verified: "
                            f"{local_kb_runtime_snapshot()}"
                        )
                        return True
                    print(
                        "[KB] Local Chroma backup restore skipped: "
                        f"{restore_summary.get('reason') or 'backup unavailable'}"
                    )
                except Exception as restore_exc:
                    print(f"[KB] Local Chroma backup restore failed: {restore_exc}")
                    reset_local_searcher_cache(clear_degraded=False)

                summary = rebuild_active_index(_lock_held=True)
                print(
                    "[KB] Local Chroma repair mode: "
                    f"{summary.get('repair_mode') or 'unknown'}"
                )
                if summary.get("corrupt_store_backup"):
                    print(
                        "[KB] Corrupted Chroma store archived at: "
                        f"{summary.get('corrupt_store_backup')}"
                    )
                failed_count = int(summary.get("failed_count") or 0)
                indexed_count = int(summary.get("indexed_count") or 0)
                if failed_count or indexed_count != active_count:
                    raise RuntimeError(
                        "索引重建未完整成功："
                        f"active={active_count}, indexed={indexed_count}, failed={failed_count}"
                    )

                reset_local_searcher_cache(clear_degraded=False)
                verified = load_local_searcher()
                verified.search("知識庫索引修復驗證", top_k=1)
                clear_local_searcher_degraded()
                print(
                    "[KB] Local Chroma repair finished and verified: "
                    f"{local_kb_runtime_snapshot()}"
                )
                return True
        except Exception as exc:
            print(f"[KB] Local Chroma index repair failed: {exc}")
            print(f"[KB] Local Chroma repair snapshot: {local_kb_runtime_snapshot()}")
            reset_local_searcher_cache(clear_degraded=False)
            mark_local_searcher_degraded(exc)
            return False


def load_local_searcher():
    global _LOCAL_SEARCHER
    if _LOCAL_SEARCHER is None:
        from app.services.kb_core import load_kb_searcher

        _LOCAL_SEARCHER = load_kb_searcher(
            persist_dir=RAG_LOCAL_PERSIST_DIR,
            collection_name=RAG_LOCAL_COLLECTION,
            model_name=RAG_LOCAL_EMBED_MODEL,
            device=RAG_LOCAL_EMBED_DEVICE,
        )
    return _LOCAL_SEARCHER


def prewarm_local_searcher() -> None:
    backend = (RAG_BACKEND or "local").lower()
    if backend not in {"local", "hybrid"}:
        return

    searcher = None
    for attempt in range(2):
        try:
            searcher = searcher or load_local_searcher()
            searcher.search("知識庫預熱", top_k=1)
            clear_local_searcher_degraded()
            print("[KB] local searcher prewarm completed")
            return
        except Exception as exc:
            if not is_local_chroma_index_error(exc):
                print(f"[KB] local searcher prewarm skipped: {exc}")
                return
            if attempt == 0:
                print(f"[KB] local searcher prewarm HNSW retry scheduled: {exc}")
                time.sleep(1.0)
                continue

            if is_local_chroma_transient_compaction_error(exc):
                print(
                    "[KB] local searcher prewarm deferred: transient "
                    f"Chroma compactor/backfill error: {exc}"
                )
                searcher = None
                reset_local_searcher_cache(clear_degraded=False)
                return

            print(f"[KB] local searcher prewarm HNSW error, starting repair: {exc}")
            # The local variable otherwise keeps the broken PersistentClient
            # alive while repair tries to replace chroma_db on Windows.
            searcher = None
            reset_local_searcher_cache(clear_degraded=False)
            if repair_local_chroma_index():
                print("[KB] local searcher prewarm repaired and verified")
            else:
                mark_local_searcher_degraded(exc)
                print("[KB] local searcher prewarm repair failed")
            return


def prewarm_local_searcher_async() -> None:
    global _LOCAL_SEARCHER_PREWARM_THREAD
    current = _LOCAL_SEARCHER_PREWARM_THREAD
    if current and current.is_alive():
        return

    thread = threading.Thread(
        target=prewarm_local_searcher,
        name="kb-local-searcher-prewarm",
        daemon=True,
    )
    _LOCAL_SEARCHER_PREWARM_THREAD = thread
    thread.start()


def normalize_keyword_text(value: Any) -> str:
    text = "" if value is None else str(value)
    text = text.lower()
    text = text.replace("好事成雙", "好視成雙")
    text = text.replace("ㄏㄚtv", "哈tv").replace("ㄏㄚnet", "哈net")
    text = re.sub(r"[\s　]+", "", text)
    text = re.sub(r"[?？!！。.,，、:：;；「」『』（）()\[\]【】]", "", text)
    return text


def extract_query_identifier_terms(query: str) -> List[str]:
    """Extract product codes and protocol names without maintaining a whitelist.

    Knowledge documents often contain identifiers such as E003, HDMI, FIFA,
    USB, ATM or IP.  They are strong retrieval evidence even when the natural
    language around them differs, so keep them as independent fallback terms.
    """
    raw_text = "" if query is None else str(query).lower()
    terms: List[str] = []
    for token in re.findall(r"[a-z]+[0-9]+|[0-9]+[a-z]+|[a-z]{2,}", raw_text):
        if len(token) < 2 or token.isdigit():
            continue
        if token not in terms:
            terms.append(token)
    return terms


def extract_query_strict_identifier_terms(query: str) -> List[str]:
    """Return identifiers whose exact spelling is essential to retrieval.

    Mixed letter/number codes (for example E003) and explicit uppercase
    abbreviations with at least three letters (HDMI, USB, ATM, FIFA) are much
    less ambiguous than ordinary words or broadband speeds.  Only these terms
    can force a lexical supplement when semantic results miss the identifier.
    """
    raw_text = "" if query is None else str(query)
    terms: List[str] = []
    # Product names such as "Hi Play" or "LINE TV" are often written with
    # spaces by customers but stored without them in source documents.  Keep
    # the normalized full phrase as one exact retrieval signal.
    for token in re.findall(r"[A-Za-z]{2,}(?:\s+[A-Za-z]{2,})+", raw_text):
        normalized = normalize_keyword_text(token)
        if normalized and normalized not in terms:
            terms.append(normalized)
    for token in re.findall(
        r"[A-Za-z]+[0-9]+|[0-9]+[A-Za-z]+|[A-Z]{3,}|[A-Z][A-Za-z]{2,}",
        raw_text,
    ):
        normalized = normalize_keyword_text(token)
        if re.fullmatch(r"\d+(?:m|g)", normalized):
            continue
        if normalized and normalized not in terms:
            terms.append(normalized)
    return terms


LEXICAL_OVERLAP_STOP_BIGRAMS = {
    "可以", "請問", "想問", "怎麼", "如何", "什麼", "多少", "問題",
    "服務", "資料", "資訊", "幫我", "一下", "有關", "目前", "公司",
}


QUERY_SUBJECT_EVIDENCE_STOP_BIGRAMS = LEXICAL_OVERLAP_STOP_BIGRAMS | {
    "申請", "辦理", "設定", "查詢", "費用", "收費", "方案", "優惠",
    "活動", "電視", "網路", "有線", "機上", "上盒", "使用", "我要",
    "這個", "那個", "一個", "一支", "一台", "哪裡", "是否", "需要",
}
QUERY_SUBJECT_EDGE_CHARS = set("的了嗎呢啊呀吧我你您想要請問")


def _cjk_bigrams(value: str) -> set[str]:
    normalized = normalize_keyword_text(value)
    output: set[str] = set()
    for segment in re.findall(r"[\u3400-\u9fff]+", normalized):
        for index in range(len(segment) - 1):
            token = segment[index:index + 2]
            if token not in LEXICAL_OVERLAP_STOP_BIGRAMS:
                output.add(token)
    return output


def extract_query_subject_evidence_bigrams(query: str) -> set[str]:
    """Return reusable lexical evidence without a business-term whitelist.

    Semantic retrieval may return a nearby service or plan even though none of
    the returned chunks contains the customer's actual subject.  Adjacent CJK
    characters provide a format-independent signal for that case.  Generic
    question wording and broad product words are removed so a shared word such
    as ``費用`` or ``網路`` cannot by itself suppress the document scan.
    """
    return {
        token
        for token in _cjk_bigrams(query)
        if token not in QUERY_SUBJECT_EVIDENCE_STOP_BIGRAMS
        and token[0] not in QUERY_SUBJECT_EDGE_CHARS
        and token[-1] not in QUERY_SUBJECT_EDGE_CHARS
    }


def docs_contain_query_subject_evidence(
    query: str,
    docs: List[Dict[str, Any]],
) -> bool:
    query_tokens = extract_query_subject_evidence_bigrams(query)
    if len(query_tokens) < 2:
        return True
    return any(
        len(query_tokens.intersection(_cjk_bigrams(doc_search_text(doc)))) >= 2
        for doc in docs
    )


def score_query_lexical_overlap(query: str, question: str, answer: str) -> int:
    """Give a small score to rows sharing multiple adjacent Chinese terms.

    This is deliberately weaker than an exact keyword match.  Requiring at
    least two shared bigrams recovers paraphrases such as "普通遙控器" versus
    "一般型遙控器", while a single broad word such as "方案" cannot pull an
    unrelated row into the candidate set.
    """
    query_tokens = _cjk_bigrams(query)
    if len(query_tokens) < 2:
        return 0

    question_overlap = query_tokens.intersection(_cjk_bigrams(question))
    answer_overlap = query_tokens.intersection(_cjk_bigrams(answer))
    best_overlap = max(len(question_overlap), len(answer_overlap))
    if best_overlap < 2:
        return 0
    return min(best_overlap, 6) * 2


QUERY_ANCHOR_SPLITTERS = (
    "要怎麼",
    "該怎麼",
    "怎麼",
    "如何",
    "是什麼",
    "有哪些",
    "有什麼",
    "可不可以",
    "能不能",
    "多少錢",
)

QUERY_ANCHOR_PREFIXES = (
    "請問",
    "想請問",
    "我想問",
    "我想知道",
    "想知道",
    "可以幫我查",
    "幫我查",
    "麻煩幫我查",
)

LOW_VALUE_QUERY_ANCHORS = {
    "申請",
    "設定",
    "辦理",
    "查詢",
    "說明",
    "介紹",
    "資訊",
    "資料",
    "服務",
    "問題",
}


def extract_query_anchor_terms(query: str) -> List[str]:
    """Extract stable subject phrases from natural customer questions."""
    normalized = normalize_keyword_text(query)
    if not normalized:
        return []

    core = normalized
    for prefix in sorted(QUERY_ANCHOR_PREFIXES, key=len, reverse=True):
        normalized_prefix = normalize_keyword_text(prefix)
        if core.startswith(normalized_prefix):
            core = core[len(normalized_prefix):]
            break

    splitter_pattern = "|".join(
        re.escape(normalize_keyword_text(value))
        for value in sorted(QUERY_ANCHOR_SPLITTERS, key=len, reverse=True)
    )
    segments = re.split(splitter_pattern, core) if splitter_pattern else [core]
    candidates = segments if len(segments) > 1 else [core]
    anchors: List[str] = []
    for candidate in candidates:
        candidate = re.sub(r"(?:可以|嗎|呢|啊|呀|吧)+$", "", candidate)
        if len(candidate) < 3 or candidate in LOW_VALUE_QUERY_ANCHORS:
            continue
        if candidate not in anchors:
            anchors.append(candidate)
    return anchors


def has_stable_query_subject_anchor(query: str) -> bool:
    """Return whether a natural question yielded a distinct exact subject.

    Broad discovery text such as ``八月優惠活動`` remains unchanged after
    anchor extraction and must keep the established semantic/company ordering.
    Questions such as ``固定 IP 要怎麼申請`` yield ``固定ip``; that distinct
    subject is safe to use for exact-row recovery and ranking.
    """
    normalized = normalize_keyword_text(query)
    if not normalized:
        return False
    return any(
        len(anchor) >= 4 and anchor != normalized
        for anchor in extract_query_anchor_terms(query)
    )


def build_keyword_terms(query: str) -> List[str]:
    normalized = normalize_keyword_text(query)
    terms = []

    for anchor in extract_query_anchor_terms(query):
        if anchor not in terms:
            terms.append(anchor)

    for identifier in extract_query_identifier_terms(query):
        if identifier not in terms:
            terms.append(identifier)

    for term in KEYWORD_FALLBACK_TERMS:
        normalized_term = normalize_keyword_text(term)
        if normalized_term and normalized_term in normalized and normalized_term not in terms:
            terms.append(normalized_term)

    if "移機" in terms and "搬移" not in terms:
        terms.append("搬移")
    if "搬移" in terms and "移機" not in terms:
        terms.append("移機")
    if "費用" in terms and "收費" not in terms:
        terms.append("收費")
    if "收費" in terms and "費用" not in terms:
        terms.append("費用")
    if "多少錢" in terms and "費用" not in terms:
        terms.append("費用")
    if any(term in terms for term in ("停機", "暫停機", "暫停收視", "暫停收看")):
        for synonym in (
            "暫停機",
            "停機",
            "暫停收視",
            "暫停收看",
            "有線電視",
            "第四台",
            "雙證件",
            "印章",
            "臨櫃辦理",
            "復機費",
        ):
            normalized_synonym = normalize_keyword_text(synonym)
            if normalized_synonym and normalized_synonym not in terms:
                terms.append(normalized_synonym)
    for alias in build_question_paraphrase_terms(query):
        if alias not in terms:
            terms.append(alias)
    if any(term in terms for term in ("加值套餐", "加值數位套餐", "數位電視套餐")):
        for synonym in ("加值服務", "單品銷售", "數位電視套餐"):
            normalized_synonym = normalize_keyword_text(synonym)
            if normalized_synonym not in terms:
                terms.append(normalized_synonym)

    for synonym in value_added_query_aliases(query):
        normalized_synonym = normalize_keyword_text(synonym)
        if normalized_synonym and normalized_synonym not in terms:
            terms.append(normalized_synonym)

    query_facets = detect_query_facets(query)
    facet_synonyms = {
        "multi_set_top_box_fee": ("機上盒", "數位機上盒", "第三台", "第3台", "押金", "分機費", "施工費"),
        "equipment_purchase_price": ("遙控器", "購買", "售價", "元/支", "費用"),
        "points_usage": ("紅利點數", "哈POINT", "使用", "用途", "兌換", "折抵", "1點", "1元"),
        "service_device_limit": ("LINE TV", "登入", "裝置", "設備", "幾台", "上限"),
        "senior_value_added_service": ("長輩", "年長者", "銀髮", "高齡", "熊搭心", "加值服務"),
        "internet_time_control": ("上網時間管理", "上網時間限制", "特定時段", "禁止上網", "設定"),
        "service_cancellation_requirements": (
            "退租", "辦理退租", "身分證", "身份證", "護照", "印章", "設備", "配件", "臨櫃辦理",
        ),
        "credit_card_payment_method": (
            "信用卡", "線上刷卡", "線上信用卡繳費", "線上繳費專區", "官網", "官方網站", "用戶編號", "密碼",
        ),
        "payment_method_guidance": (
            "繳費方式", "線上刷卡", "臨櫃繳費", "行動客服 APP", "帳單條碼", "ibon", "FamiPort",
        ),
    }
    for facet in query_facets:
        for synonym in facet_synonyms.get(facet, ()):
            normalized_synonym = normalize_keyword_text(synonym)
            if normalized_synonym and normalized_synonym not in terms:
                terms.append(normalized_synonym)

    if is_basic_tv_fee_query(query):
        for synonym in ("第四台", "有線電視", "收視費", "月繳", "基本收費標準"):
            normalized_synonym = normalize_keyword_text(synonym)
            if normalized_synonym not in terms:
                terms.append(normalized_synonym)

    if is_broadband_plan_price_query(query):
        for synonym in ("網路", "寬頻", "月繳", "季繳", "半年繳", "年繳", "費用"):
            normalized_synonym = normalize_keyword_text(synonym)
            if normalized_synonym not in terms:
                terms.append(normalized_synonym)
        for speed in extract_requested_broadband_speeds(query):
            if speed not in terms:
                terms.append(speed)

    if is_restricted_channel_purchase_query(query):
        for synonym in (
            "成人頻道", "限制級", "VIP會員", "優惠專區", "數位電視", "購買", "加購",
        ):
            normalized_synonym = normalize_keyword_text(synonym)
            if normalized_synonym not in terms:
                terms.append(normalized_synonym)

    if is_digital_tv_package_purchase_query(query):
        for synonym in ("數位電視", "數位套餐", "VIP會員", "優惠專區", "購買", "加購"):
            normalized_synonym = normalize_keyword_text(synonym)
            if normalized_synonym not in terms:
                terms.append(normalized_synonym)

    for number in re.findall(r"\d+", str(query or "")):
        if number not in terms:
            terms.append(number)

    if not terms and normalized:
        terms.append(normalized)

    return terms


def read_active_kb_document_records(knowledge_bases: List[str]) -> List[Dict[str, Any]]:
    manifest_path = Path(RAG_LOCAL_MANIFEST_PATH)
    if not manifest_path.exists():
        return []

    try:
        data = json.loads(manifest_path.read_text(encoding="utf-8-sig"))
    except Exception:
        return []

    documents = data.get("documents") if isinstance(data, dict) else None
    if not isinstance(documents, list):
        return []

    allowed_bases = set(knowledge_bases)
    records = []
    for document in documents:
        if not isinstance(document, dict):
            continue
        if document.get("status") != "active":
            continue
        if document.get("processing_status") != "indexed":
            continue

        knowledge_base = str(document.get("knowledge_base") or DEFAULT_RAG_KNOWLEDGE_BASE)
        if knowledge_base not in allowed_bases:
            continue

        file_path = Path(str(document.get("file_path") or ""))
        current_docs_candidate = Path(RAG_LOCAL_DOCS_DIR) / file_path.name
        if file_path.name and current_docs_candidate.exists():
            file_path = current_docs_candidate
        elif not file_path.is_absolute():
            file_path = Path.cwd() / file_path
        if file_path.exists():
            record = dict(document)
            record["_resolved_file_path"] = file_path
            records.append(record)

    return records


def score_keyword_match(query_terms: List[str], question: str, answer: str) -> int:
    normalized_question = normalize_keyword_text(question)
    normalized_answer = normalize_keyword_text(answer)
    score = 0

    for term in query_terms:
        if term in normalized_question:
            score += 4
        if term in normalized_answer:
            score += 2

    if "費用" in query_terms or "收費" in query_terms:
        if re.search(r"\d+\s*元", answer):
            score += 3

    return score


def campaign_profile_metadata(record: Dict[str, Any]) -> Dict[str, Any]:
    profile = record.get("campaign_profile")
    if not isinstance(profile, dict):
        return {}
    return {
        "document_type": str(profile.get("document_type") or ""),
        "campaign_name": str(profile.get("campaign_name") or ""),
        "campaign_aliases": " | ".join(profile.get("aliases") or []),
        "campaign_sections": " | ".join(profile.get("section_types") or []),
        "service_types": " | ".join(profile.get("service_types") or []),
        "speeds": " | ".join(profile.get("speeds") or []),
        "contract_months": " | ".join(
            str(value) for value in (profile.get("contract_months") or [])
        ),
        "payment_terms": " | ".join(profile.get("payment_terms") or []),
        "customer_types": " | ".join(profile.get("customer_types") or []),
        "valid_period": str(profile.get("valid_period") or ""),
        "occasion_terms": " | ".join(profile.get("occasion_terms") or []),
        "gift_items": " | ".join(profile.get("gift_items") or []),
        "lottery_details": " | ".join(profile.get("lottery_details") or []),
    }


def campaign_alias_match_score(query: str, record: Dict[str, Any]) -> int:
    profile = record.get("campaign_profile")
    if not isinstance(profile, dict):
        return 0
    normalized_query = normalize_keyword_text(query)
    for alias in profile.get("aliases") or []:
        normalized_alias = normalize_keyword_text(alias)
        if len(normalized_alias) >= 3 and normalized_alias in normalized_query:
            return 80
    return 0


def build_product_service_profile_candidates(
    query: str,
    record: Dict[str, Any],
) -> List[Dict[str, Any]]:
    """Expose structured value-added products to the keyword fallback path."""
    profile = record.get("product_service_profile")
    if not isinstance(profile, dict):
        return []

    normalized_query = normalize_keyword_text(query)
    if not normalized_query:
        return []

    catalog_name = str(profile.get("catalog_name") or record.get("title") or "").strip()
    output: List[Dict[str, Any]] = []
    for index, product in enumerate(profile.get("products") or [], start=1):
        if not isinstance(product, dict):
            continue
        name = str(product.get("name") or "").strip()
        key = str(product.get("key") or "").strip()
        parent = str(product.get("parent_name") or "").strip()
        aliases = [
            str(value).strip()
            for value in product.get("aliases") or []
            if str(value).strip()
        ]
        match_terms = [name, parent, *aliases]
        normalized_terms = [
            normalize_keyword_text(value)
            for value in match_terms
            if len(normalize_keyword_text(value)) >= 2
        ]
        matched_terms = [value for value in normalized_terms if value in normalized_query]
        if not matched_terms:
            continue

        content = str(product.get("content") or "").strip()
        if not content:
            continue
        score = 120 + max(len(value) for value in matched_terms) * 4
        source = {
            "document_id": record.get("id"),
            "chunk_id": f"{record.get('id')}:product:{index}:keyword",
            "source": record.get("file_name"),
            "title": name or catalog_name or str(record.get("title") or query),
            "section": f"product {index} {name}".strip(),
            "knowledge_base": record.get("knowledge_base") or DEFAULT_RAG_KNOWLEDGE_BASE,
            "category": "value_added_service",
            "record_type": "product_service",
            "document_type": str(profile.get("document_type") or "product_service_catalog"),
            "product_catalog": catalog_name,
            "product_name": name,
            "product_aliases": " | ".join(aliases),
            "product_parent": parent,
            "score": round(score / 20, 6),
            "distance": None,
            "content": content,
        }
        normalized = normalize_rag_source(
            source,
            query,
            record.get("knowledge_base") or DEFAULT_RAG_KNOWLEDGE_BASE,
        )
        normalized["_keyword_score"] = score
        normalized["_distance"] = None
        normalized["_query_relevance_score"] = score_query_relevance(query, normalized) + 120
        normalized["_structured_product_profile"] = True
        normalized["product_key"] = key
        output.append(normalized)

    return output


def match_active_campaign_alias(
    query: str,
    memory: Optional[Dict[str, Any]] = None,
) -> Optional[Dict[str, str]]:
    """Match a query against campaign aliases generated during indexing."""
    normalized_query = normalize_keyword_text(query)
    if len(normalized_query) < 3:
        return None

    scoped_memory = memory if isinstance(memory, dict) else {}
    knowledge_bases = infer_knowledge_bases(scoped_memory)
    best_match: Optional[Dict[str, str]] = None
    best_score = 0

    for record in read_active_kb_document_records(knowledge_bases):
        profile = record.get("campaign_profile")
        if not isinstance(profile, dict):
            continue
        if str(profile.get("document_type") or "") != "promotion_campaign":
            continue

        campaign_name = str(profile.get("campaign_name") or record.get("title") or "").strip()
        aliases = [
            campaign_name,
            *(str(value).strip() for value in (profile.get("aliases") or [])),
        ]
        for alias in aliases:
            normalized_alias = normalize_keyword_text(alias)
            if len(normalized_alias) < 3:
                continue
            if normalized_query == normalized_alias:
                score = 300 + len(normalized_alias)
            elif normalized_alias in normalized_query:
                score = 200 + len(normalized_alias)
            elif _single_substitution_window(normalized_query, normalized_alias):
                score = 150 + len(normalized_alias)
            else:
                continue

            if score <= best_score:
                continue
            best_score = score
            best_match = {
                "campaign_name": campaign_name or alias,
                "matched_alias": alias,
                "knowledge_base": str(record.get("knowledge_base") or ""),
                "document_id": str(record.get("id") or ""),
            }

    return best_match


def filter_docs_for_active_campaign_alias(
    query: str,
    memory: Optional[Dict[str, Any]],
    docs: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """Keep an explicitly named campaign on its indexed source document."""
    if not docs:
        return docs
    # A named digital-TV package needs both its own price evidence and the
    # separately maintained, common set-top-box purchase process. It is not a
    # promotion campaign comparison, so do not discard that process evidence.
    if is_digital_tv_package_purchase_query(query):
        return docs

    campaign_match = match_active_campaign_alias(query, memory)
    if not campaign_match:
        return docs

    target_document_id = str(campaign_match.get("document_id") or "").strip()
    matched_alias = normalize_keyword_text(
        campaign_match.get("matched_alias")
        or campaign_match.get("campaign_name")
        or ""
    )

    matched_docs: List[Dict[str, Any]] = []
    for doc in docs:
        source = doc.get("source") if isinstance(doc.get("source"), dict) else {}
        document_id = str(
            doc.get("document_id")
            or source.get("document_id")
            or ""
        ).strip()
        if target_document_id and document_id == target_document_id:
            matched_docs.append(doc)
            continue
        if matched_alias and matched_alias in normalize_keyword_text(doc_search_text(doc)):
            matched_docs.append(doc)

    # An explicitly named campaign must never fall through to another campaign.
    # Returning no documents lets the answer layer say that the named activity
    # was not found instead of composing a confident answer from unrelated data.
    return matched_docs


def retrieve_knowledge_from_keyword_fallback(
    plan_name: str,
    memory: Dict[str, Any],
    top_k: int,
) -> List[Dict[str, Any]]:
    query_terms = build_keyword_terms(plan_name)
    if not query_terms:
        return []

    knowledge_bases = infer_retrieval_knowledge_bases(plan_name, memory)
    candidates = []
    generic_campaign_query = is_generic_promotion_query(plan_name)

    for record in read_active_kb_document_records(knowledge_bases):
        file_path = record["_resolved_file_path"]
        suffix = file_path.suffix.lower()
        profile_metadata = campaign_profile_metadata(record)
        is_profiled_campaign = (
            str(profile_metadata.get("document_type") or "").strip().lower()
            == "promotion_campaign"
        )
        alias_score = campaign_alias_match_score(plan_name, record)

        candidates.extend(build_product_service_profile_candidates(plan_name, record))

        try:
            if suffix == ".csv":
                from app.services.kb_admin_service import read_text_with_fallback

                rows = csv.DictReader(read_text_with_fallback(file_path).splitlines())
                for row_index, row in enumerate(rows, start=1):
                    question = str(row.get("question") or row.get("問題") or "").strip()
                    answer = str(row.get("answer") or row.get("答案") or "").strip()
                    company = str(row.get("company") or row.get("公司") or record.get("knowledge_base") or "").strip()
                    if not question and not answer:
                        continue

                    source = {
                        "document_id": record.get("id"),
                        "chunk_id": f"{record.get('id')}:{row_index}:keyword",
                        "source": record.get("file_name"),
                        "title": question or record.get("title") or plan_name,
                        "section": f"row {row_index}",
                        "knowledge_base": record.get("knowledge_base") or DEFAULT_RAG_KNOWLEDGE_BASE,
                        "category": record.get("category"),
                        "score": None,
                        "distance": None,
                        "content": answer,
                        **profile_metadata,
                    }
                    score = (
                        score_keyword_match(query_terms, question, answer)
                        + score_query_lexical_overlap(plan_name, question, answer)
                        + alias_score
                    )
                    force_purchase_evidence = (
                        is_restricted_channel_purchase_query(plan_name)
                        and is_restricted_channel_price_doc(source)
                    ) or (
                        is_digital_tv_package_purchase_query(plan_name)
                        and is_digital_tv_package_purchase_doc(source)
                    )
                    include_profiled_campaign = generic_campaign_query and is_profiled_campaign
                    if score <= 0 and not force_purchase_evidence and not include_profiled_campaign:
                        continue
                    if force_purchase_evidence:
                        score = max(score, 40)
                    elif include_profiled_campaign:
                        score = max(score, 5)
                    source["score"] = round(score / 20, 6)
                    normalized = normalize_rag_source(
                        source,
                        plan_name,
                        record.get("knowledge_base") or DEFAULT_RAG_KNOWLEDGE_BASE,
                    )
                    normalized["_keyword_score"] = score
                    normalized["_distance"] = None
                    normalized["_query_relevance_score"] = score_query_relevance(plan_name, normalized)
                    candidates.append(normalized)
                continue

            if suffix not in {".txt", ".md"}:
                supported_suffixes = {".pdf", ".docx", ".html", ".htm", ".jsonl"}
                if suffix not in supported_suffixes:
                    continue

                from app.services.kb_admin_service import chunk_sections, extract_document_sections

                chunks = chunk_sections(extract_document_sections(file_path))
            else:
                from app.services.kb_admin_service import read_text_with_fallback

                chunks = [{
                    "content": read_text_with_fallback(file_path).strip(),
                    "section": "text",
                    "page_no": None,
                }]

            title = str(record.get("title") or file_path.stem or "").strip()
            package_key = detect_hatv_package_key(plan_name)
            if package_key:
                package_content = build_hatv_package_table_content(chunks, package_key)
                if package_content:
                    score = 80
                    source = {
                        "document_id": record.get("id"),
                        "chunk_id": f"{record.get('id')}:hatv-{package_key.lower()}-package:keyword",
                        "source": record.get("file_name"),
                        "title": f"哈TV-{package_key}套餐頻道內容",
                        "section": f"哈TV-{package_key}套餐 table",
                        "page_no": None,
                        "knowledge_base": record.get("knowledge_base") or DEFAULT_RAG_KNOWLEDGE_BASE,
                        "category": record.get("category"),
                        "score": round(score / 20, 6),
                        "distance": None,
                        "content": package_content,
                    }
                    normalized = normalize_rag_source(
                        source,
                        plan_name,
                        record.get("knowledge_base") or DEFAULT_RAG_KNOWLEDGE_BASE,
                    )
                    normalized["_keyword_score"] = score
                    normalized["_distance"] = None
                    normalized["_query_relevance_score"] = score_query_relevance(plan_name, normalized) + 120
                    normalized["_hatv_package_table"] = True
                    candidates.append(normalized)

            for chunk_index, chunk in enumerate(chunks, start=1):
                content = str(chunk.get("content") or "").strip()
                if not content:
                    continue

                question = str(chunk.get("question") or title or plan_name).strip()
                section = chunk.get("section") or "text"
                source = {
                    "document_id": record.get("id"),
                    "chunk_id": f"{record.get('id')}:{chunk_index}:keyword",
                    "source": record.get("file_name"),
                    "title": question or title or plan_name,
                    "section": section,
                    "page_no": chunk.get("page_no"),
                    "knowledge_base": record.get("knowledge_base") or DEFAULT_RAG_KNOWLEDGE_BASE,
                    "category": record.get("category"),
                    "score": None,
                    "distance": None,
                    "content": content,
                    **profile_metadata,
                }
                score = (
                    score_keyword_match(query_terms, question, content)
                    + score_query_lexical_overlap(plan_name, question, content)
                    + alias_score
                )
                force_purchase_evidence = (
                    is_restricted_channel_purchase_query(plan_name)
                    and is_restricted_channel_price_doc(source)
                ) or (
                    is_digital_tv_package_purchase_query(plan_name)
                    and is_digital_tv_package_purchase_doc(source)
                )
                include_profiled_campaign = generic_campaign_query and is_profiled_campaign
                if score <= 0 and not force_purchase_evidence and not include_profiled_campaign:
                    continue
                if force_purchase_evidence:
                    score = max(score, 40)
                elif include_profiled_campaign:
                    score = max(score, 5)
                source["score"] = round(score / 20, 6)
                normalized = normalize_rag_source(
                    source,
                    plan_name,
                    record.get("knowledge_base") or DEFAULT_RAG_KNOWLEDGE_BASE,
                )
                normalized["_keyword_score"] = score
                normalized["_distance"] = None
                normalized["_query_relevance_score"] = score_query_relevance(plan_name, normalized)
                candidates.append(normalized)
        except Exception as exc:
            print(f"RAG keyword fallback skipped {file_path}: {exc}")

    candidates = filter_docs_for_query_intent(plan_name, candidates)
    candidates = sort_docs_by_company_priority(candidates, memory, plan_name)
    output = (
        diversify_generic_campaign_documents(candidates, top_k)
        if generic_campaign_query
        else candidates[:top_k]
    )

    print("==== LOCAL KEYWORD RAG FALLBACK DEBUG ====")
    print("query:", plan_name)
    print("terms:", query_terms)
    print("docs:", output)
    return output


def campaign_document_id(doc: Dict[str, Any]) -> str:
    source = doc.get("source") if isinstance(doc.get("source"), dict) else {}
    return str(source.get("document_id") or doc.get("document_id") or "").strip()


def campaign_document_group_key(doc: Dict[str, Any]) -> str:
    """Return a stable campaign grouping key even for legacy chunks."""
    document_id = campaign_document_id(doc)
    if document_id:
        return f"document:{document_id}"

    campaign_name = campaign_metadata_value(doc, "campaign_name")
    if campaign_name:
        return f"campaign:{normalize_keyword_text(campaign_name)}"

    source = doc.get("source") if isinstance(doc.get("source"), dict) else {}
    source_name = str(source.get("source") or doc.get("source") or "").strip()
    if source_name:
        return f"source:{normalize_keyword_text(source_name)}"

    return f"chunk:{doc.get('id') or id(doc)}"


def generic_campaign_representative_score(doc: Dict[str, Any]) -> float:
    """Prefer a complete campaign overview over a gift/detail-only chunk."""
    answer = str(doc.get("answer") or doc.get("content") or "")
    normalized = normalize_keyword_text(answer)
    record_type = str(doc.get("record_type") or "").strip().lower()

    score = 0.0
    if record_type == "campaign_profile":
        score += 24.0
    elif record_type == "campaign_summary":
        score += 10.0
    elif record_type == "campaign_variant":
        score += 2.0

    # A useful first answer needs the campaign frame, not only one benefit.
    coverage_patterns = (
        (r"方案名稱|活動名稱", 5.0),
        (r"活動期間|有效期間|即日起|截止", 7.0),
        (r"\d+(?:\.\d+)?\s*[mg]\s*/\s*\d+(?:\.\d+)?\s*[mg]", 5.0),
        (r"月繳|季繳|半年繳|年繳|售價|月租|費用", 5.0),
        (r"綁約|合約|約期|違約金", 4.0),
        (r"裝機費|設備押金|網路設備押金", 3.0),
        (r"申請資格|適用對象|舊戶|新戶", 3.0),
        (r"line\s*tv|贈品|point|點數|抽獎|獎項", 1.0),
    )
    core_hits = 0
    for pattern, weight in coverage_patterns:
        if re.search(pattern, normalized, flags=re.IGNORECASE):
            score += weight
            if weight >= 3.0:
                core_hits += 1

    score += min(len(answer) / 320.0, 4.0)
    if core_hits <= 1 and re.search(r"line\s*tv|贈品|point|點數|抽獎|獎項", normalized, re.IGNORECASE):
        score -= 8.0
    return score


def diversify_generic_campaign_documents(
    docs: List[Dict[str, Any]],
    top_k: int,
) -> List[Dict[str, Any]]:
    """Expose multiple campaigns before adding detail chunks from one campaign."""
    if not docs or top_k <= 0:
        return []

    unique_docs: List[Dict[str, Any]] = []
    seen_answers: set[str] = set()
    for doc in docs:
        answer_key = normalize_keyword_text(doc.get("answer") or "")[:240]
        if answer_key and answer_key in seen_answers:
            continue
        if answer_key:
            seen_answers.add(answer_key)
        unique_docs.append(doc)

    group_order: List[str] = []
    grouped: Dict[str, List[tuple[int, Dict[str, Any]]]] = {}
    for index, doc in enumerate(unique_docs):
        group_key = campaign_document_group_key(doc)
        if group_key not in grouped:
            grouped[group_key] = []
            group_order.append(group_key)
        grouped[group_key].append((index, doc))

    output: List[Dict[str, Any]] = []
    deferred: List[Dict[str, Any]] = []
    for group_key in group_order:
        group_docs = grouped[group_key]
        ranked = sorted(
            group_docs,
            key=lambda item: (-generic_campaign_representative_score(item[1]), item[0]),
        )
        representative_index, representative = ranked[0]
        output.append(representative)
        # Choosing the overview must not reorder the document's remaining
        # lottery, gift, pricing, or eligibility chunks.
        deferred.extend(
            doc for index, doc in group_docs if index != representative_index
        )
        if len(output) >= top_k:
            return output

    for doc in deferred:
        output.append(doc)
        if len(output) >= top_k:
            break
    return output


def complete_campaign_document_context(
    query: str,
    docs: List[Dict[str, Any]],
    top_k: int,
) -> List[Dict[str, Any]]:
    if not docs or top_k <= 1:
        return docs[:top_k]

    anchors = [
        doc for doc in docs
        if is_campaign_activity_doc(doc) and is_requested_campaign_doc(query, doc)
    ]
    if not anchors:
        if is_pure_network_catalog_query(query):
            pure_network_docs = [
                doc for doc in docs
                if is_pure_network_plan_doc(doc)
                and not is_internal_campaign_note_doc(doc)
                and not is_social_discount_doc(doc)
            ]
            if pure_network_docs:
                return diversify_generic_campaign_documents(pure_network_docs, top_k)
        if is_campaign_discovery_query(query):
            campaign_docs = filter_campaigns_by_discovery_context(query, docs)
            if campaign_docs:
                return diversify_generic_campaign_documents(campaign_docs, top_k)
        if is_generic_promotion_query(query):
            return diversify_generic_campaign_documents(docs, top_k)
        return docs[:top_k]

    document_id = campaign_document_id(anchors[0])
    if not document_id:
        return docs[:top_k]

    same_document = [
        doc for doc in docs
        if campaign_document_id(doc) == document_id and is_campaign_activity_doc(doc)
    ]
    if len(same_document) <= 1:
        return docs[:top_k]

    output: List[Dict[str, Any]] = []
    seen_answers: set[str] = set()
    for doc in [*anchors, *same_document, *docs]:
        answer_key = normalize_keyword_text(doc.get("answer") or "")[:240]
        if answer_key and answer_key in seen_answers:
            continue
        if answer_key:
            seen_answers.add(answer_key)
        output.append(doc)
        if len(output) >= top_k:
            break
    return output


def finalize_docs_for_query(
    query: str,
    docs: List[Dict[str, Any]],
    top_k: int,
) -> List[Dict[str, Any]]:
    """Apply query-specific final selection without campaign anchoring side effects."""
    if is_digital_tv_package_purchase_query(query):
        purchase_docs = [doc for doc in docs if is_digital_tv_package_purchase_doc(doc)]
        return select_digital_tv_package_purchase_docs(purchase_docs or docs, top_k)
    if is_tv_network_combo_query(query):
        combo_docs = [
            doc for doc in docs
            if is_tv_network_combo_doc(doc) and not is_social_discount_doc(doc)
        ]
        return complete_campaign_document_context(query, combo_docs or docs, top_k)
    if is_pure_network_catalog_query(query):
        pure_network_docs = [
            doc for doc in docs
            if is_pure_network_plan_doc(doc)
            and not is_internal_campaign_note_doc(doc)
            and not is_social_discount_doc(doc)
        ]
        return diversify_generic_campaign_documents(pure_network_docs or docs, top_k)
    if is_pure_tv_catalog_query(query):
        rate_card_docs = [
            doc for doc in docs
            if is_pure_tv_rate_card_doc(doc)
            and not is_social_discount_doc(doc)
        ]
        return rate_card_docs[:top_k]
    if is_broadband_plan_price_query(query):
        return select_broadband_plan_price_docs(query, docs, top_k)
    if detect_query_facets(query):
        return sorted(
            docs,
            key=lambda doc: (
                -score_query_facet_evidence(query, doc),
                -int(doc.get("_query_relevance_score") or 0),
                -int(doc.get("_keyword_score") or 0),
                float(doc.get("_distance", 999)) if doc.get("_distance") is not None else 999,
            ),
        )[:top_k]
    if is_restricted_channel_purchase_query(query):
        purchase_docs = [doc for doc in docs if is_restricted_channel_purchase_doc(doc)]
        return select_restricted_channel_purchase_docs(purchase_docs or docs, top_k)
    return complete_campaign_document_context(query, docs, top_k)


def retrieve_knowledge_from_api(plan_name: str, memory: Dict[str, Any], top_k: int) -> List[Dict[str, Any]]:
    if not RAG_API_URL:
        return []

    knowledge_base = infer_knowledge_base(memory)
    payload = build_rag_payload(plan_name, knowledge_base, top_k)

    try:
        data = call_rag_api(payload)
    except requests.RequestException as exc:
        print(f"RAG API request failed: {exc}")
        return []
    except Exception as exc:
        print(f"RAG API unexpected error: {exc}")
        return []

    docs = normalize_rag_response(data, plan_name, knowledge_base)
    print("==== RAG API DEBUG ====")
    print("payload:", payload)
    print("docs:", docs)
    return docs


def retrieve_knowledge_from_local_chroma(
    plan_name: str,
    memory: Dict[str, Any],
    top_k: int,
    max_distance: float,
) -> List[Dict[str, Any]]:
    if _LOCAL_SEARCHER_DEGRADED:
        print(
            "Local Chroma RAG is in degraded mode; using document text fallback: "
            f"{_LOCAL_SEARCHER_DEGRADED_REASON}"
        )
        return []

    knowledge_bases = infer_retrieval_knowledge_bases(plan_name, memory)
    category = None
    search_top_k = build_local_search_candidate_count(plan_name, top_k)
    raw_docs = []

    try:
        searcher = load_local_searcher()
        for knowledge_base in knowledge_bases:
            raw_docs.extend(
                searcher.search(
                    plan_name,
                    top_k=search_top_k,
                    knowledge_base=knowledge_base,
                    category=category,
                )
            )
    except Exception as exc:
        if not is_local_chroma_index_error(exc):
            print(f"Local Chroma RAG failed: {exc}")
            return []

        if is_local_chroma_transient_compaction_error(exc):
            print(
                "Local Chroma RAG transient compactor/backfill error; "
                f"using document text fallback for this request: {exc}"
            )
            reset_local_searcher_cache(clear_degraded=False)
            return []

        prewarm_thread = _LOCAL_SEARCHER_PREWARM_THREAD
        if (
            prewarm_thread
            and prewarm_thread.is_alive()
            and prewarm_thread is not threading.current_thread()
        ):
            print(
                "Local Chroma RAG index repair is already running; "
                "using document text fallback for this request."
            )
            return []

        print(f"Local Chroma RAG index error, rebuilding active index and retrying: {exc}")
        if not repair_local_chroma_index():
            # repair_local_chroma_index normally records degraded state itself.
            # Keep the caller defensive as tests and alternate repair hooks may
            # return False without touching the shared circuit breaker.
            mark_local_searcher_degraded(exc)
            return []

        raw_docs = []
        try:
            searcher = load_local_searcher()
            for knowledge_base in knowledge_bases:
                raw_docs.extend(
                    searcher.search(
                        plan_name,
                        top_k=search_top_k,
                        knowledge_base=knowledge_base,
                        category=category,
                    )
                )
        except Exception as retry_exc:
            print(f"Local Chroma RAG failed after index repair: {retry_exc}")
            if is_local_chroma_index_error(retry_exc):
                mark_local_searcher_degraded(retry_exc)
            return []

    unique_docs = {}
    for doc in raw_docs:
        doc_id = doc.get("id")
        if doc_id not in unique_docs:
            unique_docs[doc_id] = doc

    sorted_docs = sorted(
        unique_docs.values(),
        key=lambda item: (
            float(item.get("_distance", 999)),
            -float(item.get("_score", 0)),
        ),
    )

    output = []
    for doc in sorted_docs:
        distance = doc.get("_distance")
        if distance is not None and float(distance) > max_distance:
            continue
        doc_knowledge_base = doc.get("company") or infer_knowledge_base(memory)
        source = {
            "document_id": doc.get("document_id"),
            "chunk_id": doc.get("id"),
            "source": doc.get("source"),
            "title": doc.get("question") or doc.get("title"),
            "page_no": doc.get("page_no"),
            "section": doc.get("section"),
            "knowledge_base": doc_knowledge_base,
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
            "product_catalog": doc.get("product_catalog"),
            "product_name": doc.get("product_name"),
            "product_aliases": doc.get("product_aliases"),
            "product_parent": doc.get("product_parent"),
            "score": doc.get("_score"),
            "distance": distance,
            "content": doc.get("answer"),
        }
        normalized = normalize_rag_source(source, plan_name, doc_knowledge_base)
        normalized["_distance"] = distance
        normalized["_keyword_score"] = score_keyword_match(
            build_keyword_terms(plan_name),
            str(normalized.get("question") or ""),
            str(normalized.get("answer") or ""),
        )
        normalized["_query_relevance_score"] = score_query_relevance(plan_name, normalized)
        output.append(normalized)

    output = filter_docs_to_active_manifest_sources(output, knowledge_bases)
    output = filter_docs_for_query_intent(plan_name, output)
    output = sort_docs_by_company_priority(output, memory, plan_name)
    output = finalize_docs_for_query(plan_name, output, top_k)

    print("==== LOCAL CHROMA RAG DEBUG ====")
    print("query:", plan_name)
    print("knowledge_bases:", knowledge_bases)
    print("category:", category or "不指定")
    print("docs:", output)
    return output


def retrieve_knowledge(
    user_input: str,
    memory: Dict[str, Any],
    controller_output: Optional[Dict[str, Any]] = None,
    top_k: int = 5,
    max_distance: float = 0.55,
) -> List[Dict[str, Any]]:
    target_document_id = str(
        (controller_output or {}).get("target_document_id") or ""
    ).strip()
    target_knowledge_base = str(
        (controller_output or {}).get("target_knowledge_base") or ""
    ).strip()

    def constrain_to_validated_target(docs: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        if not target_document_id:
            return docs
        matched: List[Dict[str, Any]] = []
        for doc in docs:
            source = doc.get("source") if isinstance(doc.get("source"), dict) else {}
            document_id = str(
                doc.get("document_id") or source.get("document_id") or ""
            ).strip()
            knowledge_base = str(
                doc.get("knowledge_base") or source.get("knowledge_base") or ""
            ).strip()
            if document_id != target_document_id:
                continue
            if target_knowledge_base and knowledge_base and knowledge_base != target_knowledge_base:
                continue
            matched.append(doc)
        return matched

    retrieval_query = (
        controller_output.get("knowledge_query")
        if controller_output and controller_output.get("knowledge_query")
        else user_input
    )
    raw_user_input = str(user_input or "").strip()
    raw_query = str(retrieval_query or raw_user_input).strip()
    preserve_promotion_scope_query = (
        (controller_output or {}).get("promotion_query_kind") == "catalog"
        and (controller_output or {}).get("promotion_scope")
        in {"pure_network", "tv_network", "pure_tv"}
    )
    semantic_route = str((controller_output or {}).get("reason") or "").startswith(
        "llm_failure_semantic_"
    )
    starts_new_topic = bool((controller_output or {}).get("should_cancel_current_flow"))
    if (
        starts_new_topic
        and raw_user_input
        and not semantic_route
        and not preserve_promotion_scope_query
    ):
        # Retrieval contract: when the LLM identifies a new request, the
        # customer's wording is the primary subject. Query rewrites are useful
        # for same-topic follow-ups, but must not inject a previous topic or an
        # illustrative channel/product into an unrelated new question.
        raw_query = raw_user_input
    # Month/holiday discovery must keep the user's actual wording. Controller
    # expansion includes product examples (LINE TV, POINTS, gifts), which used
    # to misroute a broad campaign request as a single-product lookup.
    if is_campaign_discovery_query(raw_user_input) and not preserve_promotion_scope_query:
        raw_query = raw_user_input
    # A new, explicit speed/price request starts fresh plan discovery.  Do not
    # let a campaign mentioned in an earlier turn constrain the new request.
    if (
        is_broadband_plan_price_query(raw_user_input)
        and not is_named_campaign_query(raw_user_input)
        and not semantic_route
        and not preserve_promotion_scope_query
    ):
        raw_query = raw_user_input
    if is_restricted_channel_purchase_query(raw_user_input) and not semantic_route:
        # The controller may expand "authorization expired" into a generic
        # set-top-box or promotion query.  Preserve the explicit purchase
        # intent so both the purchase path and package price table survive the
        # query-specific final selection.
        raw_query = raw_user_input
    if (
        "payment_method_guidance" in detect_query_facets(raw_user_input)
        and not semantic_route
    ):
        # A generic payment-method question needs the overview document.  LLM
        # examples such as "ibon" or "FamiPort" are individual channels and
        # must not become strict retrieval anchors unless the customer named one.
        raw_query = raw_user_input
    basic_tv_query = (
        raw_user_input
        if is_basic_tv_fee_query(raw_user_input) and not semantic_route
        else raw_query
    )
    if is_basic_tv_fee_query(basic_tv_query):
        # A standalone cable-TV fee question is narrower than the controller's
        # generic fee expansion.  Terms such as installation fee, set-top-box
        # deposit and promotions otherwise crowd the actual rate card out of
        # the semantic candidates.  For a short follow-up, retain the LLM's
        # contextual query rather than dropping the service scope back to the
        # customer's abbreviated wording.
        followup_detail = raw_query if semantic_route else (
            raw_user_input if raw_user_input != basic_tv_query else ""
        )
        raw_query = " ".join(
            part for part in (
                "有線電視 基本收費標準 基本收視費",
                followup_detail,
            ) if part
        )
    campaign_match = match_active_campaign_alias(raw_query, memory)
    if campaign_match:
        # Controller query expansion is useful for broad promotion questions, but
        # it can dilute a named campaign enough for a different activity to rank
        # above it. Preserve the user's own detail terms while ignoring generic
        # expansion added by the controller.
        matched_alias = str(
            campaign_match.get("matched_alias")
            or campaign_match.get("campaign_name")
            or ""
        ).strip()
        user_campaign_match = match_active_campaign_alias(raw_user_input, memory)
        raw_query = (
            raw_user_input
            if user_campaign_match and not semantic_route
            else " ".join(part for part in (matched_alias, raw_user_input) if part)
        )

    plan_name = normalize_retrieval_query(raw_query)
    if not plan_name:
        return []

    # A catalog reply is deterministic and compact, so it can safely carry one
    # representative document per eligible pure-network plan instead of the
    # normal five-document summary ceiling.
    selection_top_k = max(top_k, 12) if is_pure_network_catalog_query(plan_name) else top_k

    backend = (RAG_BACKEND or "local").lower()
    local_max_distance = max_distance if max_distance is not None else RAG_LOCAL_MAX_DISTANCE
    active_filter_bases = infer_retrieval_knowledge_bases(plan_name, memory)

    if backend == "api":
        docs = retrieve_knowledge_from_api(plan_name, memory, selection_top_k)
        docs = supplement_digital_tv_package_purchase_path_docs(
            plan_name,
            docs,
            memory,
            active_filter_bases,
        )
        if is_digital_tv_package_purchase_query(plan_name):
            docs = filter_docs_for_query_intent(plan_name, docs)
            docs = sort_docs_by_company_priority(docs, memory, plan_name)
            docs = finalize_docs_for_query(plan_name, docs, selection_top_k)
        docs = filter_docs_for_active_campaign_alias(plan_name, memory, docs)
        return constrain_to_validated_target(docs)

    docs = retrieve_knowledge_from_local_chroma(
        plan_name,
        memory,
        top_k=selection_top_k,
        max_distance=local_max_distance,
    )
    if docs and should_merge_keyword_fallback_for_results(plan_name, docs):
        keyword_top_k = (
            max(selection_top_k * 8, 40)
            if is_broadband_plan_price_query(plan_name)
            or is_pure_network_catalog_query(plan_name)
            or is_restricted_channel_purchase_query(plan_name)
            or is_digital_tv_package_purchase_query(plan_name)
            or is_generic_promotion_query(plan_name)
            or bool(detect_query_facets(plan_name))
            else max(selection_top_k * 6, 30)
        )
        keyword_docs = retrieve_knowledge_from_keyword_fallback(
            plan_name,
            memory,
            top_k=keyword_top_k,
        )
        # A CSV/DOCX document can contribute several independent QA rows that
        # intentionally share one document id.  De-duplicating by id here drops
        # the exact FAQ row whenever a broader row from the same file appears
        # first.  The content-aware key keeps distinct rows while still merging
        # duplicate Chroma and keyword hits for the same row.
        merged_list = dedupe_retrieved_docs([*docs, *keyword_docs])
        merged_list = filter_docs_to_active_manifest_sources(merged_list, active_filter_bases)
        merged_list = filter_docs_for_query_intent(plan_name, merged_list)
        merged_list = sort_docs_by_company_priority(merged_list, memory, plan_name)
        docs = finalize_docs_for_query(plan_name, merged_list, selection_top_k)
    elif not docs:
        keyword_top_k = (
            max(selection_top_k * 8, 40)
            if detect_query_facets(plan_name) or is_pure_network_catalog_query(plan_name)
            else max(selection_top_k * 4, 24)
        )
        docs = retrieve_knowledge_from_keyword_fallback(plan_name, memory, keyword_top_k)
        docs = dedupe_retrieved_docs(docs)
        docs = filter_docs_to_active_manifest_sources(docs, active_filter_bases)
        docs = filter_docs_for_query_intent(plan_name, docs)
        docs = sort_docs_by_company_priority(docs, memory, plan_name)
        docs = finalize_docs_for_query(plan_name, docs, selection_top_k)

    docs = supplement_digital_tv_package_purchase_path_docs(
        plan_name,
        docs,
        memory,
        active_filter_bases,
    )
    if is_digital_tv_package_purchase_query(plan_name):
        docs = filter_docs_for_query_intent(plan_name, docs)
        docs = sort_docs_by_company_priority(docs, memory, plan_name)
        docs = finalize_docs_for_query(plan_name, docs, top_k)

    if docs or backend != "hybrid":
        docs = filter_docs_for_active_campaign_alias(plan_name, memory, docs)
        return constrain_to_validated_target(docs)

    docs = retrieve_knowledge_from_api(plan_name, memory, top_k)
    docs = filter_docs_for_active_campaign_alias(plan_name, memory, docs)
    return constrain_to_validated_target(docs)


def render_knowledge_text(docs: List[Dict[str, Any]]) -> str:
    if not docs:
        return "無"

    blocks = []
    for index, doc in enumerate(docs, start=1):
        blocks.append(
            "\n".join([
                f"[知識 {index}]",
                f"id: {doc.get('id')}",
                f"company: {doc.get('company')}",
                f"category: {doc.get('category')}",
                f"question: {doc.get('question')}",
                f"answer: {doc.get('answer')}",
                f"score: {doc.get('_score')}",
            ])
        )
    return "\n\n".join(blocks)
