import json
from copy import deepcopy
from pathlib import Path
from typing import Any, Dict, Iterable, Mapping

from app.config.settings import REGIONAL_POLICY_PATH
from app.services.company_profile import TV_DICT
from app.services.knowledge_base_policy import (
    CENTRAL_COMMON_KNOWLEDGE_BASE,
    JIANNAN_COMMON_KNOWLEDGE_BASE,
    LEGACY_COMMON_KNOWLEDGE_BASE,
    REGIONAL_COMMON_MEMBERS,
    normalize_knowledge_base_name,
    regional_common_knowledge_bases,
)


REGION_CENTRAL = "central"
REGION_JIANNAN = "jiannan"
REGION_UNRESOLVED = "unresolved"
REGION_AMBIGUOUS = "ambiguous"

REGION_BY_COMMON_KNOWLEDGE_BASE = {
    CENTRAL_COMMON_KNOWLEDGE_BASE: REGION_CENTRAL,
    JIANNAN_COMMON_KNOWLEDGE_BASE: REGION_JIANNAN,
}

DEFAULT_POLICY_RULES: Dict[str, Dict[str, Any]] = {
    "promotion.social_discount_stacking": {
        "prompt": (
            "若使用者詢問低收入戶、中低收入戶、身心障礙等社福優惠是否可與"
            "一般促銷或其他公司活動併用、合併、搭配或重複適用，請明確回答"
            "「公司活動多重優惠不可重複適用」，不可回答「資料沒有明確寫」。"
        ),
        "reply": (
            "低收入戶、中低收入戶、身心障礙等社福優惠不可與其他公司優惠活動重複適用。\n"
            "若已申請低收入戶優惠，就不能再同時申請一般促銷或其他優惠方案；"
            "反過來，若已參加公司優惠活動，也不能再疊加低收入戶優惠。\n"
            "若要申辦，仍需由客服依您的資格與目前合約狀態確認可適用哪一種優惠。"
        ),
    },
    "promotion.discount_stacking_caution": {
        "prompt": (
            "若使用者詢問其他優惠是否可併用、搭配或重複適用，而資料沒有明確寫可併用，"
            "不可承諾可同時適用；請回答需依公司公告與個案資格由客服確認。"
        ),
        "reply": (
            "優惠是否可重複適用需依公司公告與個案資格確認；"
            "若資料未明確寫可併用，請不要承諾可同時適用，建議由客服協助確認。"
        ),
    },
    "promotion.hidden_plan_visibility": {
        "prompt": (
            "若整個方案標示「隱藏版」、「非主推」、「不主推」、「AI 禁止報價」或"
            "「特殊需求須請示主管」，不可主動推薦或列入一般比較；只有使用者明確詢問該方案時，"
            "才簡短說明並引導客服確認。若只有部分速率標示隱藏版，保留主方案，"
            "但不要主動列出隱藏版速率。"
        ),
    },
    "promotion.non_promoted_1g_plan": {
        "prompt": (
            "使用者明確詢問或申請 1G 非主推方案時，只說明需確認申辦資格與服務條件，"
            "不可當成一般主推方案主動推薦。"
        ),
        "reply": (
            "您好！1G 非主推網路方案，實際申辦資格及服務條件需依安裝地點及設備條件確認。"
            "若您有申辦需求，我們將安排專人為您進一步說明與協助。"
        ),
    },
    "promotion.low_income_500m_year_fee": {
        "prompt": (
            "使用者詢問低收入戶 500M 一年費用時，請依本區政策回答費用、申請方式與限制條件，"
            "不可自行換算資料中未提供的金額。"
        ),
        "reply": (
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
        ),
    },
    "billing.next_bill_after_no_unpaid": {
        "prompt": (
            "若前一輪已查詢本期帳單且結果為無待繳，使用者接著問下期帳單或下次繳費時間，"
            "請說明目前僅能查詢本期待繳帳單，待下期帳單產生後留意通知。"
        ),
        "reply": "您好，目前系統可協助查詢本期待繳帳單。待下期帳單產生後，請留意相關通知，謝謝。",
    },
    "billing.past_payment_record": {
        "prompt": (
            "若使用者詢問過往繳費紀錄、已繳費明細、入帳紀錄或入帳確認，"
            "請引導至行動客服 APP 或官網查閱。"
        ),
        "reply": "若需查詢已繳費明細或入帳紀錄，可至行動客服 APP 或官網查閱。很高興為您服務，謝謝。",
    },
    "billing.payment_not_posted": {
        "prompt": (
            "若使用者表示已在門市或以信用卡繳費但尚未沖帳，請提醒帳務更新可能需要作業時間、"
            "保留收據或交易明細，若需確認是否入帳，由真人客服依收據資訊協助查詢。"
        ),
        "reply": (
            "您好，門市或刷卡繳費後，帳務更新可能需要作業時間，通常不一定會即時沖帳。\n\n"
            "請先保留繳費收據或交易明細，以便後續核對。\n\n"
            "若需確認是否已入帳，建議提供繳費收據資訊，由真人客服協助查詢。"
        ),
    },
    "billing.store_payment_still_billed": {
        "prompt": (
            "若使用者表示已在超商繳費但仍查到帳單，請提醒入帳可能需要作業時間、保留收據或交易明細，"
            "若需確認是否入帳，由真人客服依收據資訊協助查詢。"
        ),
        "reply": (
            "您好，超商繳費入帳可能需要作業時間，通常不一定會即時更新。\n\n"
            "請先保留繳費收據或交易明細，以便後續核對。\n\n"
            "若需確認是否已入帳，建議提供繳費收據資訊，由真人客服協助查詢。"
        ),
    },
    "support.remote_control_price": {
        "prompt": (
            "若使用者詢問遙控器價格，請依本區政策提供價格與保固資訊；"
            "實際型號及是否需更換仍由客服或工程人員確認。"
        ),
        "reply": (
            "一般型遙控器 300 元、語音遙控器 400 元，保固一年；"
            "實際型號與是否需更換仍以客服或工程人員確認為準。"
        ),
    },
}

DEFAULT_REGIONAL_OVERRIDES: Dict[str, Dict[str, Dict[str, Any]]] = {
    REGION_CENTRAL: {},
    REGION_JIANNAN: {},
}


def _configured_common_scopes() -> Mapping[str, Iterable[str]]:
    try:
        from app.services.web_account_service import WebAccountService

        return WebAccountService().get_common_knowledge_base_scopes()
    except Exception:
        return REGIONAL_COMMON_MEMBERS


def infer_station_knowledge_base(memory: Mapping[str, Any] | None) -> str:
    memory = memory or {}
    company_code = str(memory.get("company_code") or "").strip()
    if company_code in TV_DICT:
        return normalize_knowledge_base_name(TV_DICT[company_code])

    profile = memory.get("company_profile") or {}
    if isinstance(profile, Mapping) and profile.get("class"):
        return normalize_knowledge_base_name(str(profile["class"]))

    company = str(memory.get("company") or "").strip()
    for station in TV_DICT.values():
        if station and station in company:
            return normalize_knowledge_base_name(station)

    return CENTRAL_COMMON_KNOWLEDGE_BASE


def resolve_policy_context(
    memory: Mapping[str, Any] | None,
    common_scopes: Mapping[str, Iterable[str]] | None = None,
) -> Dict[str, Any]:
    station = infer_station_knowledge_base(memory)
    if station in {CENTRAL_COMMON_KNOWLEDGE_BASE, LEGACY_COMMON_KNOWLEDGE_BASE}:
        matches = [CENTRAL_COMMON_KNOWLEDGE_BASE]
    elif station == JIANNAN_COMMON_KNOWLEDGE_BASE:
        matches = [JIANNAN_COMMON_KNOWLEDGE_BASE]
    else:
        matches = regional_common_knowledge_bases(
            station,
            common_scopes or _configured_common_scopes(),
        )

    if len(matches) > 1:
        region_code = REGION_AMBIGUOUS
        regional_base = None
    elif matches:
        regional_base = matches[0]
        region_code = REGION_BY_COMMON_KNOWLEDGE_BASE[regional_base]
    else:
        region_code = REGION_UNRESOLVED
        regional_base = None

    return {
        "company_code": str((memory or {}).get("company_code") or ""),
        "station_knowledge_base": station,
        "region_code": region_code,
        "regional_knowledge_base": regional_base,
        "policy_resolution_status": (
            "conflict" if region_code == REGION_AMBIGUOUS
            else "resolved" if regional_base
            else "global_only"
        ),
    }


def _load_policy_overrides() -> Dict[str, Any]:
    path = Path(REGIONAL_POLICY_PATH)
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def _merged_policy_config() -> Dict[str, Any]:
    config = {
        "global": deepcopy(DEFAULT_POLICY_RULES),
        "regions": deepcopy(DEFAULT_REGIONAL_OVERRIDES),
        "stations": {},
    }
    overrides = _load_policy_overrides()
    for scope_name in ("global", "regions", "stations"):
        value = overrides.get(scope_name)
        if isinstance(value, dict):
            if scope_name == "global":
                for key, rule in value.items():
                    if isinstance(rule, dict):
                        config["global"].setdefault(key, {}).update(rule)
            else:
                for target, rules in value.items():
                    if not isinstance(rules, dict):
                        continue
                    target_rules = config[scope_name].setdefault(target, {})
                    for key, rule in rules.items():
                        if isinstance(rule, dict):
                            target_rules.setdefault(key, {}).update(rule)
    return config


def _remember_policy_context(memory: Dict[str, Any] | None, context: Dict[str, Any]) -> None:
    if memory is not None:
        memory["policy_context"] = dict(context)


def get_policy_rule(
    memory: Dict[str, Any] | None,
    rule_key: str,
    *,
    common_scopes: Mapping[str, Iterable[str]] | None = None,
    track: bool = True,
) -> Dict[str, Any]:
    context = resolve_policy_context(memory, common_scopes)
    config = _merged_policy_config()
    rule = deepcopy(config["global"].get(rule_key, {}))
    source = "global"

    region_code = context["region_code"]
    regional_rule = config["regions"].get(region_code, {}).get(rule_key)
    if isinstance(regional_rule, dict):
        rule.update(regional_rule)
        source = f"region:{region_code}"

    station = context["station_knowledge_base"]
    station_rule = config["stations"].get(station, {}).get(rule_key)
    if isinstance(station_rule, dict):
        rule.update(station_rule)
        source = f"station:{station}"

    rule["_policy_key"] = rule_key
    rule["_policy_source"] = source
    rule["_policy_region"] = region_code
    _remember_policy_context(memory, context)

    if track and memory is not None:
        applied = memory.setdefault("applied_policy_rules", [])
        entry = {
            "rule_key": rule_key,
            "source": source,
            "region_code": region_code,
            "station_knowledge_base": station,
        }
        if entry not in applied:
            applied.append(entry)
    return rule


def get_policy_text(
    memory: Dict[str, Any] | None,
    rule_key: str,
    field: str,
    fallback: str = "",
) -> str:
    value = get_policy_rule(memory, rule_key).get(field)
    return str(value or fallback)


def build_policy_prompt(
    memory: Dict[str, Any] | None,
    rule_keys: Iterable[str],
) -> str:
    lines = []
    for rule_key in rule_keys:
        prompt = get_policy_text(memory, rule_key, "prompt")
        if prompt:
            lines.append(f"- {prompt}")
    if not lines:
        return "- 本次僅套用全域安全規則。"
    context = (memory or {}).get("policy_context") or {}
    region = context.get("regional_knowledge_base") or "未解析區域"
    return f"【本次區域政策：{region}】\n" + "\n".join(lines)
