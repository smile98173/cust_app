import json
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from app.config.settings import COMPANY_PROFILE_PATH
from app.services.error_logging import log_exception


TV_DICT = {
    "toplight": "佳光市區",
    "cltv": "佳聯",
    "cnt": "中投",
    "pktv": "北港",
    "tdtv": "大屯",
    "wctv": "西海岸",
    "hya": "新永安",
    "tycable": "大揚",
    "tinp": "台基科",
}

DEFAULT_TV_CABLE = "tdtv"

EDITABLE_COMPANY_PROFILE_FIELDS = [
    "address_phone",
    "business_hours",
    "service_area",
    "service_products",
    "area_outage",
    "promotion_activity",
    "urls",
    "value_added_urls",
]
REQUIRED_COMPANY_PROFILE_FIELDS = ["address_phone", "business_hours", "service_area"]

LINE_TV_HELP_URL = "https://help.linetv.tw/hc/zh-tw"
REPAIR_REPORT_URL = (
    "http://stb.topmso.com.tw:8080/csr_mobile_client_web/Move_serviceAction.do"
    "?method=go_cust_con_fix_main&amp;cust_no_con=0&amp;accountNo=&amp;password="
)
INSTALL_REPORT_URL = (
    "http://stb.topmso.com.tw:8080/csr_mobile_client_web/Move_serviceAction.do"
    "?method=go_cust_con_install_main&amp;cust_no_con=0&amp;accountNo=&amp;password="
)


def build_company_links(official_url: str) -> str:
    return (
        f"［官網🔗］{official_url}\n"
        f"［維修申告🔗］{REPAIR_REPORT_URL}\n"
        f"［裝機申告🔗］{INSTALL_REPORT_URL}"
    )


def build_value_added_links() -> str:
    return f"［LINE TV客服中心🔗］{LINE_TV_HELP_URL}"


def extract_company_links(profile: Dict[str, str]) -> List[Tuple[str, str]]:
    links: List[Tuple[str, str]] = []
    seen = set()
    link_icon = "\U0001f517"
    pattern = (
        rf"[［【\[]\s*(?P<label>[^］】\]\n]+?)\s*{link_icon}?\s*[］】\]]"
        rf"\s*(?P<url>https?://[^\s，。；、]+)"
    )
    for field in ("urls", "value_added_urls"):
        text = str((profile or {}).get(field) or "")
        for match in re.finditer(pattern, text):
            label = re.sub(r"\s+", " ", match.group("label").replace(link_icon, "")).strip()
            url = match.group("url").strip().rstrip("。．,，；;")
            if not label or not url:
                continue
            key = (label, url)
            if key in seen:
                continue
            seen.add(key)
            links.append((label, url))
    return links


def extract_company_link_url(profile: Dict[str, str], label: str) -> str:
    target = str(label or "").strip()
    if not target:
        return ""
    for link_label, url in extract_company_links(profile):
        if link_label == target:
            return url
    return ""


def build_company_link(profile: Dict[str, str], label: str) -> str:
    url = extract_company_link_url(profile, label)
    if not url:
        return ""
    return f"［{label}🔗］{url}"


def is_contextual_website_page_request(text: str) -> bool:
    value = (text or "").strip()
    if not value:
        return False

    compact = re.sub(r"\s+", "", value).lower()
    has_website = any(term in compact for term in ("官網", "官方網站", "網站"))
    if not has_website:
        return False

    if any(term in compact for term in ("網址", "連結", "url")):
        return False

    return any(term in compact for term in (
        "哪裡",
        "哪邊",
        "哪裏",
        "在哪",
        "哪個頁面",
        "哪一頁",
        "頁面",
        "選單",
        "路徑",
        "看介紹",
        "看到介紹",
        "可以看到",
        "找得到",
        "查得到",
        "介紹",
    ))


def is_explicit_company_website_request(text: str) -> bool:
    value = (text or "").strip()
    if not value or is_contextual_website_page_request(value):
        return False

    compact = re.sub(r"\s+", "", value).lower()
    if compact in {"官網", "官方網站", "公司網站", "公司網址", "官方網址", "網站", "網址"}:
        return True
    if len(compact) <= 12 and compact.endswith((
        "官網",
        "官方網站",
        "公司網站",
        "公司網址",
        "官方網址",
        "網站",
        "網址",
    )):
        return True

    return any(term in compact for term in (
        "官網網址",
        "官方網址",
        "公司網址",
        "網站網址",
        "官網連結",
        "官方網站連結",
        "公司網站連結",
        "給我官網",
        "提供官網",
    ))


COMPANY_PROFILES: List[Dict[str, str]] = [
    {
        "class": "西海岸",
        "company_name": "佳光電訊-西海岸區",
        "address_phone": "台中市梧棲區中華路一段1080號，市內電話：(04)449-5678",
        "website": "https://wctv.com.tw/",
        "urls": build_company_links("https://wctv.com.tw/"),
        "business_hours": "星期一～星期六 08:30-18:00，假日及國定假日中午12:00-13:30休息",
        "service_items": "有線電視及寬頻網路服務",
        "service_area": "大肚區、龍井區、梧棲區、清水區、大安區、大甲區、沙鹿區",
        "app_name": "哈TV行動客服",
        "tax_id": "97173528",
    },
    {
        "class": "佳光市區",
        "company_name": "佳光電訊-台中市區",
        "address_phone": "台中市西屯區台灣大道四段297號，市內電話：(04)405-56688",
        "website": "https://www.toplight.tw/",
        "urls": build_company_links("https://www.toplight.tw/"),
        "business_hours": "星期一～星期五 08:30-12:00、13:30-18:00",
        "service_items": "寬頻網路服務",
        "service_area": "東區、西區、南區、北區、中區、北屯區、南屯區、西屯區",
        "app_name": "哈TV行動客服",
        "tax_id": "97173528",
    },
    {
        "class": "大屯",
        "company_name": "大屯有線",
        "address_phone": "台中市大里區國光路一段68號，市內電話：(04)449-5678",
        "website": "https://www.tdtv.com.tw/",
        "urls": build_company_links("https://www.tdtv.com.tw/"),
        "business_hours": "星期一～星期五 08:00-19:00，假日 08:30-17:00，假日及國定假日中午12:00-13:00休息",
        "service_items": "有線電視及寬頻網路服務",
        "service_area": "烏日區、霧峰區、太平區、大里區",
        "app_name": "哈TV行動客服",
        "tax_id": "97174358",
    },
    {
        "class": "中投",
        "company_name": "中投有線",
        "address_phone": "南投縣南投市仁和路7-1號，市內電話：(04)449-8809",
        "website": "https://www.cnt.com.tw/",
        "urls": build_company_links("https://www.cnt.com.tw/"),
        "business_hours": "南投區 星期一～星期五 08:30-18:00、星期六 08:30-17:00；水里、埔里區 星期一～星期五 08:30-17:30",
        "service_items": "有線電視及寬頻網路服務",
        "service_area": "南投市、鹿谷鄉、竹山鎮、集集鎮、名間鄉、水里鄉、仁愛鄉、信義鄉、埔里鎮、魚池鄉、國姓鄉、草屯鎮、中寮鄉",
        "app_name": "哈TV行動客服",
        "tax_id": "16085715",
    },
    {
        "class": "佳聯",
        "company_name": "佳聯有線",
        "address_phone": "雲林縣虎尾鎮光復路66號，市內電話：(04)449-8808",
        "website": "https://www.cltv.com.tw/",
        "urls": build_company_links("https://www.cltv.com.tw/"),
        "business_hours": "虎尾櫃台 星期一～星期六 08:30-18:00；斗六櫃台 星期一～星期五 08:30-12:00、13:30-18:00",
        "service_items": "有線電視及寬頻網路服務",
        "service_area": "斗六市、古坑鄉、林內鄉、土庫鎮、大埤鄉、虎尾鎮、莿桐鄉、西螺鎮、二崙鄉、斗南鎮",
        "app_name": "哈TV行動客服",
        "tax_id": "97176779",
    },
    {
        "class": "北港",
        "company_name": "北港有線",
        "address_phone": "雲林縣元長鄉元南路80號，市內電話：(04)449-8808",
        "website": "https://www.pkcatv.com.tw/",
        "urls": build_company_links("https://www.pkcatv.com.tw/"),
        "business_hours": "星期一～星期六 08:30-18:00，星期日休息",
        "service_items": "有線電視及寬頻網路服務",
        "service_area": "麥寮鄉、台西鄉、東勢鄉、崙背鄉、褒忠鄉、四湖鄉、北港鎮、水林鄉、口湖鄉、元長鄉",
        "app_name": "哈TV行動客服",
        "tax_id": "97176757",
    },
    {
        "class": "新永安",
        "company_name": "新永安有線",
        "address_phone": "台南市永康區廣興街95巷3號，市內電話：(06)700-3120、(06)271-8958",
        "website": "https://www.hya.com.tw/",
        "urls": build_company_links("https://www.hya.com.tw/"),
        "business_hours": "星期一～星期五 08:30-18:20，受理退租至17:00止，星期六、日及國定假日休",
        "service_items": "有線電視及寬頻網路服務",
        "service_area": "永康區、新化區、新市區、安定區、善化區、山上區、玉井區、左鎮區、楠西區、南化區、歸仁區、仁德區、關廟區、龍崎區、大內區",
        "app_name": "哈TV行動客服",
        "tax_id": "84999365",
    },
    {
        "class": "大揚",
        "company_name": "大揚有線",
        "address_phone": "嘉義縣朴子市德興里新吉庄536號，市內電話：(05)320-3020、(05)379-6699",
        "website": "https://www.tycable.com.tw/",
        "urls": build_company_links("https://www.tycable.com.tw/"),
        "business_hours": "星期一～星期五 08:30-17:00，星期六日及國定假日休息",
        "service_items": "有線電視及寬頻網路服務",
        "service_area": "水上鄉、太保市、朴子市、新港鄉、六腳鄉、鹿草鄉、布袋鎮、東石鄉、義竹鄉",
        "app_name": "哈TV行動客服",
        "tax_id": "97165169",
    },
    {
        "class": "台基科",
        "company_name": "台灣基礎開發",
        "address_phone": "台中市大里區國光路一段68號，市內電話：(04)449-5678",
        "website": "https://www.tinp.net.tw/index.php/tw",
        "urls": build_company_links("https://www.tinp.net.tw/index.php/tw"),
        "business_hours": "週一至週五 08:00-19:00，假日 08:30-12:00、13:00-17:00",
        "service_items": "有線電視及寬頻網路服務",
        "service_area": "台中市、南投縣、雲林縣",
        "app_name": "哈TV行動客服",
        "tax_id": "12726274",
    },
]


def get_company_profile_path() -> Path:
    return Path(COMPANY_PROFILE_PATH)


def _seed_profile_for_code(tv_cable: str) -> Dict[str, str]:
    target_class = TV_DICT.get(tv_cable) or TV_DICT[DEFAULT_TV_CABLE]
    for profile in COMPANY_PROFILES:
        if profile["class"] == target_class:
            result = dict(profile)
            result["tv_cable"] = tv_cable if tv_cable in TV_DICT else DEFAULT_TV_CABLE
            result.setdefault("area_outage", "")
            result.setdefault("promotion_activity", "")
            result.setdefault("urls", build_company_links(result.get("website", "")))
            result.setdefault("value_added_urls", build_value_added_links())
            return result

    profile = dict(COMPANY_PROFILES[2])
    profile["tv_cable"] = DEFAULT_TV_CABLE
    profile.setdefault("area_outage", "")
    profile.setdefault("promotion_activity", "")
    profile.setdefault("urls", build_company_links(profile.get("website", "")))
    profile.setdefault("value_added_urls", build_value_added_links())
    return profile


def _seed_profiles_by_code() -> Dict[str, Dict[str, str]]:
    return {code: _seed_profile_for_code(code) for code in TV_DICT}


def _load_profile_file() -> Optional[Dict[str, Any]]:
    path = get_company_profile_path()
    if not path.exists():
        return None

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        log_exception(
            "company_profile.load_json",
            exc,
            extra={"path": str(path)},
        )
        return None

    if not isinstance(data, dict) or not isinstance(data.get("profiles"), list):
        log_exception(
            "company_profile.invalid_json",
            ValueError("company_profiles.json format is invalid"),
            extra={"path": str(path)},
        )
        return None

    return data


def get_all_company_profiles() -> List[Dict[str, str]]:
    profiles_by_code = _seed_profiles_by_code()
    data = _load_profile_file()

    if data:
        for item in data.get("profiles", []):
            if not isinstance(item, dict):
                continue
            code = str(item.get("tv_cable") or item.get("code") or "").strip()
            if code not in profiles_by_code:
                continue

            merged = dict(profiles_by_code[code])
            for field in EDITABLE_COMPANY_PROFILE_FIELDS:
                if field in item and item.get(field) is not None:
                    merged[field] = str(item.get(field)).strip()
            merged["class"] = TV_DICT[code]
            merged["tv_cable"] = code
            merged.setdefault("urls", build_company_links(merged.get("website", "")))
            merged.setdefault("value_added_urls", build_value_added_links())
            profiles_by_code[code] = merged

    return [profiles_by_code[code] for code in TV_DICT]


def get_company_profile_payload() -> Dict[str, Any]:
    return {
        "path": str(get_company_profile_path()),
        "profiles": get_all_company_profiles(),
    }


def validate_company_profile_updates(updates: Dict[str, Any]) -> Dict[str, str]:
    cleaned: Dict[str, str] = {}
    for field in EDITABLE_COMPANY_PROFILE_FIELDS:
        if field in updates:
            cleaned[field] = str(updates.get(field) or "").strip()

    for field in REQUIRED_COMPANY_PROFILE_FIELDS:
        if field in cleaned and not cleaned[field]:
            raise ValueError(f"{field} 不可空白。")

    return cleaned


def save_company_profile(tv_cable: str, updates: Dict[str, Any]) -> Dict[str, str]:
    code = str(tv_cable or "").strip()
    if code not in TV_DICT:
        raise KeyError("找不到指定系統台。")

    cleaned = validate_company_profile_updates(updates)
    current_profiles = {profile["tv_cable"]: profile for profile in get_all_company_profiles()}
    profile = dict(current_profiles[code])
    profile.update(cleaned)

    for field in REQUIRED_COMPANY_PROFILE_FIELDS:
        if not str(profile.get(field) or "").strip():
            raise ValueError(f"{field} 不可空白。")

    current_profiles[code] = profile
    payload = {
        "profiles": [current_profiles[item_code] for item_code in TV_DICT],
    }

    path = get_company_profile_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return dict(current_profiles[code])


def get_company_profile(tv_cable: str = DEFAULT_TV_CABLE) -> Dict[str, str]:
    code = tv_cable if tv_cable in TV_DICT else DEFAULT_TV_CABLE
    for profile in get_all_company_profiles():
        if profile.get("tv_cable") == code:
            return dict(profile)
    return _seed_profile_for_code(DEFAULT_TV_CABLE)


def get_company_options() -> List[Dict[str, str]]:
    options = []
    for code, class_name in TV_DICT.items():
        profile = get_company_profile(code)
        options.append({
            "code": code,
            "label": f"{code} - {profile['company_name']}",
            "company_name": profile["company_name"],
            "class": class_name,
        })
    return options


def build_company_context(tv_cable: str = DEFAULT_TV_CABLE) -> str:
    profile = get_company_profile(tv_cable)
    return (
        f"服務公司：{profile['company_name']}\n"
        f"系統台代碼：{profile['tv_cable']}\n"
        f"地址電話：{profile['address_phone']}\n"
        f"公司網址：{profile['urls']}\n"
        f"加值服務網址：{profile['value_added_urls']}\n"
        f"營業時間：{profile['business_hours']}\n"
        f"服務範圍：{profile['service_items']}\n"
        f"目前服務產品：{profile.get('service_products') or profile['service_items']}\n"
        f"服務地區：{profile['service_area']}\n"
        f"區域故障：{profile.get('area_outage') or '目前無公告'}\n"
        f"優惠活動：{profile.get('promotion_activity') or '目前無公告'}\n"
        f"App：{profile['app_name']}\n"
        f"統一編號：{profile['tax_id']}"
    )


def split_address_phone(address_phone: str) -> Tuple[str, str]:
    text = address_phone or ""
    for separator in ["，市內電話：", "，市內電話:", "，電話：", "，"]:
        if separator in text:
            address, phone = text.split(separator, 1)
            return address.strip(), phone.strip()

    return text.strip(), ""


def normalize_company_info_type(info_type: str) -> str:
    """Normalize the model's natural topic label to one company-info field."""
    value = re.sub(r"\s+", "", str(info_type or "")).casefold()
    exact_aliases = {
        "company_address": "company_address",
        "service_area": "service_area",
        "service_products": "service_products",
        "business_hours": "business_hours",
        "contact_phone": "contact_phone",
        "company_phone_inquiry": "contact_phone",
        "website": "website",
        "value_added_urls": "value_added_urls",
        "area_outage": "area_outage",
        "promotion_activity": "promotion_activity",
        "company_overview": "company_overview",
    }
    if value in exact_aliases:
        return exact_aliases[value]
    if any(term in value for term in (
        "客服電話", "服務電話", "聯絡電話", "公司電話", "聯絡方式", "怎麼聯絡", "如何聯絡", "電話",
    )):
        return "contact_phone"
    if any(term in value for term in ("營業時間", "服務時間")):
        return "business_hours"
    if any(term in value for term in ("服務地區", "服務範圍")):
        return "service_area"
    if any(term in value for term in ("服務產品", "產品內容")):
        return "service_products"
    if any(term in value for term in ("公司地址", "營業處地址", "地址")):
        return "company_address"
    if any(term in value for term in ("官網", "公司網址", "網站")):
        return "website"
    if "區域故障" in value:
        return "area_outage"
    if any(term in value for term in ("優惠活動", "活動公告")):
        return "promotion_activity"
    return str(info_type or "").strip()


def build_company_info_reply(info_type: str, tv_cable: str = DEFAULT_TV_CABLE) -> str:
    info_type = normalize_company_info_type(info_type)
    profile = get_company_profile(tv_cable)
    company = profile["company_name"]
    address, phone = split_address_phone(profile.get("address_phone", ""))

    if info_type == "company_address":
        lines = [f"{company}地址：{address}。"]
        if phone:
            lines.append(f"客服電話：{phone}。")
        return "\n".join(lines)

    if info_type == "service_area":
        return f"{company}服務地區：{profile['service_area']}。"

    if info_type == "installation_address_guidance":
        return (
            f"{company}目前列示的服務地區：{profile['service_area']}。\n"
            "申裝時請提供完整裝機地址，包含縣市、行政區、路街、巷弄、號及樓層；"
            "實際能否安裝仍需依完整地址查詢線路與施工條件，不能只以行政區判定。"
        )

    if info_type == "service_products":
        products = str(profile.get("service_products") or profile["service_items"]).strip()
        return f"{company}目前服務的產品內容：{products}。"

    if info_type == "business_hours":
        return f"{company}營業時間：{profile['business_hours']}。"

    if info_type == "contact_phone":
        if phone:
            return f"{company}客服電話：{phone}。"
        return f"{company}聯絡資訊：{profile['address_phone']}。"

    if info_type == "website":
        official_link = build_company_link(profile, "官網")
        return f"{company}公司網址：\n{official_link or profile['website']}"

    if info_type == "value_added_urls":
        return f"{company}加值服務網址：\n{profile['value_added_urls']}"

    if info_type == "area_outage":
        outage = (profile.get("area_outage") or "").strip()
        if outage:
            return f"目前{company}公告：{outage}"
        return f"目前{company}沒有區域故障公告。若您的服務仍異常，我可以先協助您做簡單檢查。"

    if info_type == "promotion_activity":
        promotion = (profile.get("promotion_activity") or "").strip()
        if promotion:
            return f"{company}目前優惠活動：\n{promotion}"
        return f"目前{company}沒有優惠活動公告。若您想確認最新方案，建議改由真人客服協助查詢。"

    return (
        f"{company}資訊：\n"
        f"地址：{address}\n"
        f"客服電話：{phone or profile['address_phone']}\n"
        f"公司網址：{profile['urls']}\n"
        f"加值服務網址：{profile['value_added_urls']}\n"
        f"營業時間：{profile['business_hours']}\n"
        f"目前服務產品：{profile.get('service_products') or profile['service_items']}\n"
        f"服務地區：{profile['service_area']}\n"
        f"區域故障：{profile.get('area_outage') or '目前無公告'}\n"
        f"優惠活動：{profile.get('promotion_activity') or '目前無公告'}"
    )


def apply_company_to_memory(memory: dict, tv_cable: str = DEFAULT_TV_CABLE) -> dict:
    profile = get_company_profile(tv_cable)
    memory["company_code"] = profile["tv_cable"]
    memory["company"] = profile["company_name"]
    memory["company_profile"] = profile
    return memory
