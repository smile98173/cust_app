import re
from typing import Any, Dict, List, Optional


DEFINITION_MARKERS = (
    "是什麼",
    "什麼是",
    "代表什麼",
    "意思是",
    "的意思",
    "定義",
)

DEFINITION_DOC_MARKERS = (
    *DEFINITION_MARKERS,
    "說明",
    "介紹",
)

FEE_MARKERS = (
    "費用",
    "月租",
    "價格",
    "價錢",
    "多少錢",
    "收費",
    "押金",
)

GENERIC_FEE_TERMS = {
    "費用",
    "月租",
    "價格",
    "價錢",
    "多少錢",
    "收費",
    "請問",
    "查詢",
    "想問",
    "想知道",
    "押金",
}

FEE_QUERY_FILLER_TERMS = {
    "介紹",
    "說明",
    "請介紹",
    "請說明",
    "幫我介紹",
    "幫我說明",
    "我想了解",
    "想了解",
    "了解",
    "如何",
    "怎麼",
    "怎麼收",
    "怎麼算",
    "收",
    "算",
    "方案",
    "方案價格",
    "方案費用",
    "內容",
    "申請方式",
    "辦理方式",
    "月繳",
    "月費",
    "半年繳",
    "半年費用",
    "年繳",
    "年費",
    "一年",
    "要",
    "嗎",
}

SERVICE_FEE_TERMS = (
    "移機",
    "搬移",
    "搬家",
    "室內",
    "室外",
    "固定ip",
    "固定IP",
    "mesh",
    "wifi",
    "wi-fi",
    "機上盒",
    "遙控器",
    "裝機",
    "安裝",
    "退租",
    "違約金",
    "發票",
    "紙本",
    "帳單",
    "繳費",
    "復線",
    "恢復",
    "哈tv",
    "哈TV",
    "line tv",
    "LINE TV",
    "數位套餐",
    "加值套餐",
    "加值數位套餐",
    "加購",
    "有線電視",
    "第四台",
    "電視",
)

FEE_SUBJECT_ALIASES = {
    "第四台": ("有線電視", "電視"),
    "有線電視": ("第四台", "電視"),
    "電視": ("第四台", "有線電視"),
}

PROMOTION_QUERY_TERMS = (
    "優惠",
    "優惠方案",
    "優惠活動",
    "促銷",
    "活動方案",
    "推薦方案",
    "最新方案",
)

# These are evidence constraints, not reply routes.  A clear service request
# must never be answered by a semantically unrelated document merely because
# vector search found a loosely similar company record.
SERVICE_EVIDENCE_TOPICS = (
    (("移機", "搬家", "搬遷", "搬移"), ("移機", "搬家", "搬遷", "搬移")),
    (("退租", "解約", "終止合約", "終止服務"), ("退租", "解約", "終止", "拆機")),
    (("固定ip", "固定ip"), ("固定ip", "固定 ip", "靜態ip", "靜態 ip")),
    (("線上繳費", "線上付款", "線上刷卡", "網路繳費"), ("線上繳費", "線上付款", "線上刷卡", "網路繳費")),
    (("youtube", "youtube"), ("youtube", "聯網機上盒", "雙模機")),
)

TERMINATION_NETWORK_TERMS = ("網路", "寬頻", "光纖", "數據機", "modem")
TERMINATION_TV_TERMS = ("有線電視", "第四台", "電視", "機上盒")
TV_ONLY_EQUIPMENT_TERMS = ("機上盒", "遙控器", "hdmi", "av傳輸線")


def normalize_text(text: Any) -> str:
    value = "" if text is None else str(text)
    value = value.strip().lower()
    value = re.sub(r"[\s　]+", "", value)
    value = re.sub(r"[?？!！。.,，、:：;；「」『』（）()]", "", value)
    value = value.replace("瑪柏", "瑪帛")
    value = value.replace("瑪帛電話", "瑪帛電視電話")
    return value


def is_service_evidence_match(query: str, doc: Dict[str, Any]) -> bool:
    """Reject retrieved documents that cannot answer the explicit service."""
    normalized_query = normalize_text(query)
    source = doc.get("source") if isinstance(doc.get("source"), dict) else {}
    normalized_doc = normalize_text(" ".join([
        str(doc.get("question") or ""),
        str(doc.get("title") or ""),
        str(doc.get("answer") or ""),
        str(doc.get("content") or ""),
        str(source.get("title") or ""),
        str(source.get("content") or ""),
    ]))
    is_termination = any(
        normalize_text(term) in normalized_query
        for term in ("退租", "解約", "終止合約", "終止服務", "退網", "退寬頻")
    )
    if is_termination:
        requests_network = any(
            normalize_text(term) in normalized_query
            for term in TERMINATION_NETWORK_TERMS
        )
        requests_tv = any(
            normalize_text(term) in normalized_query
            for term in TERMINATION_TV_TERMS
        )
        if requests_network and not any(
            normalize_text(term) in normalized_doc
            for term in TERMINATION_NETWORK_TERMS
        ):
            return False
        if requests_network:
            has_network_equipment = any(
                normalize_text(term) in normalized_doc
                for term in ("數據機", "modem")
            )
            has_tv_only_equipment = any(
                normalize_text(term) in normalized_doc
                for term in TV_ONLY_EQUIPMENT_TERMS
            )
            if has_tv_only_equipment and not has_network_equipment:
                return False
        if requests_tv and not any(
            normalize_text(term) in normalized_doc
            for term in TERMINATION_TV_TERMS
        ):
            return False
    for query_terms, evidence_terms in SERVICE_EVIDENCE_TOPICS:
        if any(normalize_text(term) in normalized_query for term in query_terms):
            return any(normalize_text(term) in normalized_doc for term in evidence_terms)
    return True


def is_definition_query(query: str) -> bool:
    normalized = normalize_text(query)
    return any(marker in normalized for marker in DEFINITION_MARKERS)


def is_network_plan_fee_query(query: str) -> bool:
    normalized = normalize_text(query)
    has_network = any(term in normalized for term in ["網路", "寬頻"])
    has_plan = "方案" in normalized
    has_fee = any(marker in normalized for marker in FEE_MARKERS)
    return has_network and has_plan and has_fee


def is_basic_tv_two_year_fee_query(query: str) -> bool:
    normalized = normalize_text(query)
    has_tv = any(term in normalized for term in ("有線電視", "第四台"))
    has_two_year_period = any(term in normalized for term in ("兩年", "二年", "2年", "24個月"))
    has_fee = any(marker in normalized for marker in ("費用", "收費", "收視費", "裝機費"))
    return has_tv and has_two_year_period and has_fee


def is_basic_tv_annual_rate_card(doc: Dict[str, Any]) -> bool:
    source = doc.get("source") if isinstance(doc.get("source"), dict) else {}
    combined = normalize_text(" ".join([
        str(doc.get("question") or ""),
        str(doc.get("answer") or ""),
        str(doc.get("content") or ""),
        str(source.get("title") or ""),
        str(source.get("content") or ""),
    ]))
    has_tv = any(term in combined for term in ("有線電視", "第四台"))
    has_annual_fee = "年繳" in combined and any(
        marker in combined for marker in ("收視費", "基本收費", "基本收視")
    )
    return has_tv and has_annual_fee and "裝機" in combined and has_fee_information(combined)


def is_specific_fee_query(query: str) -> bool:
    normalized = normalize_text(query)
    has_fee = any(marker in normalized for marker in FEE_MARKERS)
    has_subject = bool(extract_fee_subject_terms(query))
    return has_fee and has_subject


def is_promotion_query(query: str) -> bool:
    normalized = normalize_text(query)
    return any(normalize_text(term) in normalized for term in PROMOTION_QUERY_TERMS)


def extract_fee_subject_terms(query: str) -> List[str]:
    normalized = normalize_text(query)
    terms = []
    for term in SERVICE_FEE_TERMS:
        normalized_term = normalize_text(term)
        if normalized_term and normalized_term in normalized and normalized_term not in terms:
            terms.append(normalized_term)

    for generic in list(GENERIC_FEE_TERMS) + list(FEE_QUERY_FILLER_TERMS) + list(SERVICE_FEE_TERMS):
        normalized = normalized.replace(normalize_text(generic), "")
    if normalized and len(normalized) >= 2 and normalized not in terms:
        terms.append(normalized)

    return terms


def expand_fee_subject_terms(terms: List[str]) -> List[str]:
    expanded = list(terms)
    for term in terms:
        for alias in FEE_SUBJECT_ALIASES.get(term, ()):
            normalized_alias = normalize_text(alias)
            if normalized_alias and normalized_alias not in expanded:
                expanded.append(normalized_alias)
    return expanded


def has_fee_information(text: str) -> bool:
    normalized = normalize_text(text)
    if any(marker in normalized for marker in FEE_MARKERS):
        return True
    value = str(text or "")
    return bool(
        re.search(r"\d+\s*(元|塊|/月|月)", value)
        or re.search(r"[$＄]\s*\d+", value)
        or re.search(r"月\s*(繳|付|租)", value)
        or re.search(r"(半年|年繳)\s*[$＄]?\s*\d+", value)
    )


def extract_fee_rate_subjects(query: str) -> List[str]:
    """Extract explicitly requested network speeds from a fee question."""
    normalized = normalize_text(query)
    tokens = re.findall(
        r"\d+(?:\.\d+)?(?:m|g)(?:/\d+(?:\.\d+)?(?:m|g))?",
        normalized,
        flags=re.IGNORECASE,
    )
    return list(dict.fromkeys(token.lower() for token in tokens))


def extract_named_fee_subject(query: str, rate_subjects: List[str]) -> Optional[str]:
    normalized = normalize_text(query)
    removable_terms = (
        list(GENERIC_FEE_TERMS)
        + list(FEE_QUERY_FILLER_TERMS)
        + list(SERVICE_FEE_TERMS)
        + ["多少", "幾元", "的", "呢", "啊"]
    )
    for term in removable_terms:
        normalized = normalized.replace(normalize_text(term), "")
    for rate in rate_subjects:
        normalized = normalized.replace(rate, "")
    normalized = normalized.strip()
    return normalized if len(normalized) >= 2 else None


def extract_doc_product_name(doc: Dict[str, Any]) -> str:
    source = doc.get("source") if isinstance(doc.get("source"), dict) else {}
    product_name = str(doc.get("product_name") or source.get("product_name") or "").strip()
    if product_name:
        return product_name

    section = str(doc.get("section") or source.get("section") or "").strip()
    legacy_section = re.match(r"^product\s+\d+\s+(.+?)\s*$", section, re.IGNORECASE)
    return legacy_section.group(1).strip() if legacy_section else ""


def requested_fee_period_matches(query: str, text: str) -> bool:
    """Require the requested billing period to be present in the evidence."""
    normalized_query = normalize_text(query)
    normalized_text = normalize_text(text)

    if any(term in normalized_query for term in ("年繳", "年費", "一年")):
        return bool(
            any(term in normalized_text for term in ("年繳", "年費", "一年", "/年"))
            and has_fee_information(text)
        )
    if "半年" in normalized_query:
        return "半年" in normalized_text and has_fee_information(text)
    if any(term in normalized_query for term in ("月繳", "月費", "月租")):
        return bool(
            any(term in normalized_text for term in ("月繳", "月費", "月租", "元/月", "/月"))
            and has_fee_information(text)
        )
    return has_fee_information(text)


def named_product_fee_doc_match(query: str, doc: Dict[str, Any], combined: str) -> Optional[bool]:
    """Match a fee question to one canonical indexed product, when present.

    ``None`` means the query does not name a known product and the ordinary
    subject matcher should continue. A boolean result is authoritative and
    prevents related sibling plans from leaking into the answer context.
    """
    try:
        from app.services.kb_service import resolve_knowledge_entities

        entities = resolve_knowledge_entities(query)
        canonical_names = {
            normalize_text(entity.get("name") or "")
            for entity in entities
            if entity.get("name")
        }
        # Generated aliases may connect a parent service with every child
        # plan (for example, 熊搭心 with three 瑪帛 variants). When the
        # customer directly names one canonical product, that explicit name
        # must outrank sibling entities reached only through aliases.
        normalized_query = normalize_text(query)
        directly_named = {
            name for name in canonical_names if name and name in normalized_query
        }
        if directly_named:
            canonical_names = directly_named
    except (ImportError, RuntimeError):
        return None

    canonical_names.discard("")
    if not canonical_names:
        return None

    product_name = normalize_text(extract_doc_product_name(doc))
    if product_name:
        if product_name not in canonical_names:
            return False
    elif not any(name in combined for name in canonical_names):
        return False

    return requested_fee_period_matches(query, combined)


def is_specific_fee_doc_match(query: str, doc: Dict[str, Any]) -> bool:
    terms = expand_fee_subject_terms(extract_fee_subject_terms(query))
    if not terms:
        return True

    source = doc.get("source") if isinstance(doc.get("source"), dict) else {}
    combined = normalize_text(" ".join([
        str(doc.get("question") or ""),
        str(doc.get("answer") or ""),
        str(doc.get("content") or ""),
        str(doc.get("title") or ""),
        str(source.get("title") or ""),
        str(source.get("content") or ""),
        str(source.get("section") or ""),
    ]))
    product_match = named_product_fee_doc_match(query, doc, combined)
    if product_match is not None:
        return product_match

    rate_subjects = extract_fee_rate_subjects(query)
    named_subject = extract_named_fee_subject(query, rate_subjects)
    if (
        rate_subjects
        and all(rate in combined for rate in rate_subjects)
        and (not named_subject or named_subject in combined)
    ):
        return has_fee_information(combined)

    has_subject = any(term in combined for term in terms)
    return has_subject and has_fee_information(combined)


def extract_definition_subject(query: str) -> Optional[str]:
    normalized = normalize_text(query)

    prefixes = (
        "請問",
        "我想知道",
        "想知道",
        "我想了解",
        "想了解",
        "可以說明",
        "幫我說明",
    )
    for prefix in prefixes:
        if normalized.startswith(prefix):
            normalized = normalized[len(prefix):]
            break

    patterns = (
        r"^什麼是(?P<subject>.+)$",
        r"^(?P<subject>.+?)是什麼$",
        r"^(?P<subject>.+?)代表什麼$",
        r"^(?P<subject>.+?)意思是什麼$",
        r"^(?P<subject>.+?)的意思$",
        r"^(?P<subject>.+?)定義$",
    )

    for pattern in patterns:
        match = re.match(pattern, normalized)
        if match:
            subject = match.group("subject").strip()
            return subject or None

    return None


def is_definition_doc_match(query: str, doc: Dict[str, Any]) -> bool:
    # Product-service records carry a canonical product name generated during
    # indexing. Use it before parsing the expanded retrieval query: contextual
    # terms appended after "is what" make the ordinary subject parser too
    # broad, even when entity normalization already resolved the user's typo.
    source = doc.get("source") if isinstance(doc.get("source"), dict) else {}
    product_name = str(doc.get("product_name") or source.get("product_name") or "").strip()
    if not product_name:
        # Product-service chunks created before product metadata was returned
        # by the local searcher still retain a stable section label such as
        # "product 6 熊搭心". Recover the canonical name so old indexes remain
        # answerable without forcing an immediate rebuild.
        section = str(doc.get("section") or source.get("section") or "").strip()
        legacy_section = re.match(r"^product\s+\d+\s+(.+?)\s*$", section, re.IGNORECASE)
        if legacy_section:
            product_name = legacy_section.group(1).strip()
    if product_name:
        try:
            from app.services.kb_service import resolve_knowledge_entities

            entity_query = str(query or "")
            for segment in re.split(r"[?？!！。\n]", entity_query):
                if extract_definition_subject(segment):
                    entity_query = segment
                    break
            else:
                marker_match = re.match(
                    r"^(.+?(?:是什麼|代表什麼|意思是什麼|的意思|定義))",
                    entity_query,
                )
                if marker_match:
                    entity_query = marker_match.group(1)

            canonical_names = {
                normalize_text(entity.get("name") or "")
                for entity in resolve_knowledge_entities(entity_query)
                if entity.get("name")
            }
            if normalize_text(product_name) in canonical_names:
                return True
        except (ImportError, RuntimeError):
            # Keep the guard usable during isolated startup/tests where the
            # knowledge service may not be initialized yet.
            pass

    subject = extract_definition_subject(query)
    question = normalize_text(doc.get("question", ""))

    if not subject or not question:
        return False

    if question == subject:
        return True

    if subject not in question:
        return False

    return any(marker in question for marker in DEFINITION_DOC_MARKERS)


def is_doc_answerable_for_query(query: str, doc: Dict[str, Any]) -> bool:
    if not is_service_evidence_match(query, doc):
        return False

    # A two-year cable-TV total is calculated from the source's annual rate
    # plus its first-installation fee.  The source need not literally contain
    # the phrase "兩年" to be valid evidence for that calculation.
    if is_basic_tv_two_year_fee_query(query):
        return is_basic_tv_annual_rate_card(doc)

    if is_promotion_query(query):
        return True

    if is_definition_query(query):
        return is_definition_doc_match(query, doc)

    if is_network_plan_fee_query(query):
        question = normalize_text(doc.get("question", ""))
        answer = normalize_text(doc.get("answer", ""))
        combined = f"{question}{answer}"

        has_plan_subject = any(
            term in combined
            for term in [
                "網路方案",
                "寬頻方案",
                "優惠方案",
                "活動方案",
                "方案名稱",
            ]
        )
        has_fee = has_fee_information(combined)
        return has_plan_subject and has_fee

    if is_specific_fee_query(query):
        return is_specific_fee_doc_match(query, doc)

    return True


def filter_answerable_docs(
    query: str,
    docs: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    if not docs:
        return []

    return [
        doc
        for doc in docs
        if is_doc_answerable_for_query(query, doc)
    ]
