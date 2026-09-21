import os
import re
import time
from typing import Any, Dict, List, Optional, Tuple

import requests

from app.services.customer_validation import (
    CONTRACT_LOOKUP_LOGIN_REQUIRED_REPLY,
    has_authenticated_web_custnum,
    normalize_customer_number,
    normalize_tel,
    validate_name,
    validate_tel,
)
from app.services.cust_api_diagnostic_logging import log_cust_api_diagnostic
from app.services.mock_api_data import (
    find_mock_bill,
    is_mock_customer_identity,
    MOCK_CUSTOMER,
    MOCK_ADDON_PLANS,
    MOCK_CONTRACT_PRODUCTS,
    check_mock_service_availability,
    find_mock_channel,
    mock_api_response,
)
from app.config.settings import CUSTOMER_TOOL_FLOW_DISABLED_MESSAGE
from app.services.receipt_image_evidence import RECEIPT_IMAGE_REUPLOAD_REPLY


try:
    import urllib3

    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
except Exception:
    pass


TOKEN_URL = os.getenv("CUST_API_TOKEN_URL", "https://mock-api.local/cust/getToken")
SEARCH_BILL_URL = os.getenv("CUST_API_SEARCH_BILL_URL", "https://mock-api.local/cust/getCustBill")
INTERNET_RETURN_URL = os.getenv("CUST_API_INTERNET_RETURN_URL", "https://mock-api.local/cust/changeReceive")
TV_RETURN_URL = os.getenv("CUST_API_TV_RETURN_URL", "https://mock-api.local/cust/dtvChangeReceive")
SEND_MESSAGE_URL = os.getenv("CUST_API_SEND_MESSAGE_URL", "https://mock-api.local/cust/reBillE")
CONTRACT_INFO_URL = os.getenv("CUST_API_CONTRACT_INFO_URL", "https://mock-api.local/cust/getCustProd")
PAYMENT_BARCODE_URL = os.getenv(
    "CUST_API_PAYMENT_BARCODE_URL",
    "https://custservice.topmso.com.tw:8085/csr_sms_mobile_client_web-war/eBillAction.do?method=receiveByBarCode",
)
CHANNEL_QUERY_URL = os.getenv("CUST_API_CHANNEL_QUERY_URL", "https://mock-api.local/cust/channelNo")
SERVICE_AVAILABILITY_URL = os.getenv("CUST_API_SERVICE_AVAILABILITY_URL", "https://mock-api.local/cust/serviceAvailability")
NEW_INSTALL_URL = os.getenv("CUST_API_NEW_INSTALL_URL", "https://mock-api.local/cust/newInstall")
ADDON_PLAN_URL = os.getenv("CUST_API_ADDON_PLAN_URL", "https://mock-api.local/cust/addonPlans")
CANCEL_REPAIR_URL = os.getenv("CUST_API_CANCEL_REPAIR_URL", "https://mock-api.local/cust/cancelRepair")
REQUEST_TIMEOUT = int(os.getenv("CUST_API_TIMEOUT", "30"))
TOKEN_RETRY_DELAYS = (0.5, 1.0)
TOKEN_RETRY_HTTP_STATUSES = {502, 503, 504}
CUST_API_USE_MOCK = os.getenv("CUST_API_USE_MOCK", "true").lower() in ["1", "true", "yes", "on"]
CUST_API_META_KEY = "_cust_api_meta"
DISABLED_TOOL_NAMES = {
    "search_service_availability",
    "apply_new_install",
    "search_addon_plans",
}

CUST_API_TOOL_NAMES = {
    SEARCH_BILL_URL: "search_bill",
    INTERNET_RETURN_URL: "bill_return_line_internet",
    TV_RETURN_URL: "bill_return_line_tv",
    SEND_MESSAGE_URL: "send_message",
    CONTRACT_INFO_URL: "search_contract_info",
    PAYMENT_BARCODE_URL: "payment_bill_batch",
    CHANNEL_QUERY_URL: "search_channel_no",
    SERVICE_AVAILABILITY_URL: "search_service_availability",
    NEW_INSTALL_URL: "apply_new_install",
    ADDON_PLAN_URL: "search_addon_plans",
    CANCEL_REPAIR_URL: "cancel_repair_ticket",
}
CUST_API_BACKED_TOOL_NAMES = frozenset(CUST_API_TOOL_NAMES.values())
CUSTNUM_GUARDED_TOOL_NAMES = frozenset({
    "search_contract_info",
    "send_message",
})
GUEST_IDENTITY_PAIR_MESSAGE = "請提供有效的客戶編號、戶名、登記電話任兩項。"
API_BUSY_MESSAGE = "目前暫時無法完成查詢或送出申請，請稍後再試；若情況較急，請由真人客服協助核對。"
TOKEN_BUSY_MESSAGE = "目前暫時無法完成查詢，請稍後再試；若情況較急，請由真人客服協助核對。"
CUSTOMER_NOT_FOUND_MESSAGE = (
    "查詢不到您的資料。若是登入會員查詢，請重新登入後再試；"
    "若是人工核對，請確認戶名與電話是否與帳務資料一致。"
)
CUSTOMER_NOT_FOUND_BY_CUSTNUM_MESSAGE = (
    "目前依登入資料查詢不到您的資料，請重新登入後再試；若仍無法查詢，請由真人客服協助核對。"
)
CUSTOMER_NOT_FOUND_BY_CUSTNUM_PHONE_MESSAGE = (
    "目前依登入資料與登記電話查詢不到您的資料，請重新登入後再試；若仍無法查詢，請由真人客服協助核對。"
)
SEND_MESSAGE_CUSTNUM_PHONE_REQUIRED_MESSAGE = (
    "補發簡訊帳單需搭配登入資料與登記電話；"
    "請提供登記電話。\n"
    "簡訊帳單無法改寄或指定其他電話。"
)
TV_REACTIVATION_UNCONFIRMED_MESSAGE = (
    "目前無法確認您的電視授權或復線狀態。"
    "如您已繳費，請先將機上盒電源關機重開後再確認；"
    "若仍無法收視，請由真人客服協助核對帳務入帳與授權狀態。"
)
CUSTOMER_NOT_FOUND_BY_NAME_PHONE_MESSAGE = (
    "查詢不到您的資料，請確認戶名與電話是否與帳務資料一致。"
)
NO_UNPAID_BILL_MESSAGE = "尚無須繳納的費用，如您已繳費，請記得將設備電源關機重開。"
NORMAL_BILL_STATUS_MESSAGE = "我已幫您確認，目前帳務狀況正常，沒有需要處理或繳費的項目"
COMPANY_PAYMENT_ITEM_CODES = {
    "005807": "大屯",
    "005808": "中投",
    "005809": "佳光",
    "005810": "佳聯",
    "005836": "北港",
    "3564": "大揚",
    "81096": "新永安",
}
NON_COMPANY_PAYMENT_ITEM_MESSAGE = (
    "您好，經查詢，目前無法確認您所反映之繳費項目為本公司收取，"
    "建議您可依繳費明細確認收款單位，若仍有疑問，歡迎提供相關繳費資訊，"
    "我們再協助您確認，謝謝。"
)

BILL_DUE_DATE_KEYS = (
    "xEdate",
    "payDueDate",
    "paymentDueDate",
    "dueDate",
    "deadline",
    "繳費到期日",
    "繳費截止日",
)


def should_retry_token_exception(exc: Exception) -> bool:
    return isinstance(exc, (requests.exceptions.ConnectionError, requests.exceptions.Timeout))


def get_token() -> str:
    max_attempts = len(TOKEN_RETRY_DELAYS) + 1
    for attempt in range(1, max_attempts + 1):
        started = time.perf_counter()
        try:
            response = requests.get(TOKEN_URL, verify=False, timeout=REQUEST_TIMEOUT)
            elapsed = round(time.perf_counter() - started, 3)
            if response.status_code != 200:
                should_retry = (
                    response.status_code in TOKEN_RETRY_HTTP_STATUSES
                    and attempt < max_attempts
                )
                log_cust_api_diagnostic(
                    url=TOKEN_URL,
                    stage="token",
                    http_status=response.status_code,
                    elapsed_sec=elapsed,
                    success=False,
                    error_detail=getattr(response, "text", ""),
                    attempt=attempt,
                    max_attempts=max_attempts,
                )
                if should_retry:
                    time.sleep(TOKEN_RETRY_DELAYS[attempt - 1])
                    continue
                return ""

            data = response.json()
            token = str(data.get("token") or "")
            log_cust_api_diagnostic(
                url=TOKEN_URL,
                stage="token",
                http_status=response.status_code,
                elapsed_sec=elapsed,
                success=bool(token),
                error_type=None if token else "MissingToken",
                attempt=attempt,
                max_attempts=max_attempts,
            )
            return token
        except Exception as exc:
            elapsed = round(time.perf_counter() - started, 3)
            should_retry = should_retry_token_exception(exc) and attempt < max_attempts
            log_cust_api_diagnostic(
                url=TOKEN_URL,
                stage="token",
                elapsed_sec=elapsed,
                success=False,
                error_type=type(exc).__name__,
                error_detail=str(exc),
                attempt=attempt,
                max_attempts=max_attempts,
            )
            if should_retry:
                time.sleep(TOKEN_RETRY_DELAYS[attempt - 1])
                continue
            return ""

    return ""


def get_token_with_timing() -> Tuple[str, Dict[str, Any]]:
    started = time.perf_counter()
    token = get_token()
    return token, {
        "type": "token",
        "name": "get_token",
        "url": TOKEN_URL,
        "elapsed_sec": round(time.perf_counter() - started, 3),
        "success": bool(token),
    }


def extract_cust_api_meta(data: Dict[str, Any]) -> Tuple[Dict[str, Any], List[Dict[str, Any]]]:
    if not isinstance(data, dict):
        return {}, []

    clean_data = dict(data)
    meta = clean_data.pop(CUST_API_META_KEY, None)
    if not meta:
        return clean_data, []
    if isinstance(meta, list):
        return clean_data, [item for item in meta if isinstance(item, dict)]
    if isinstance(meta, dict):
        return clean_data, [meta]
    return clean_data, []


def attach_cust_api_timing(response: Dict[str, Any], *metas: Dict[str, Any]) -> Dict[str, Any]:
    valid_metas = [meta for meta in metas if isinstance(meta, dict)]
    existing = response.get("cust_api") if isinstance(response, dict) else None
    if isinstance(existing, dict):
        valid_metas = list(existing.get("calls") or []) + valid_metas

    if not valid_metas:
        return response

    response = dict(response)
    calls = []
    for meta in valid_metas:
        elapsed = meta.get("elapsed_sec")
        try:
            elapsed = round(float(elapsed), 3)
        except (TypeError, ValueError):
            elapsed = 0.0
        item = dict(meta)
        item["elapsed_sec"] = elapsed
        calls.append(item)

    token_sec = round(sum(item["elapsed_sec"] for item in calls if item.get("type") == "token"), 3)
    endpoint_sec = round(sum(item["elapsed_sec"] for item in calls if item.get("type") != "token"), 3)
    cust_api = {
        "total_sec": round(token_sec + endpoint_sec, 3),
        "token_sec": token_sec,
        "endpoint_sec": endpoint_sec,
        "calls": calls,
    }

    data = dict(response.get("data") or {})
    data["cust_api"] = cust_api
    response["data"] = data
    response["cust_api"] = cust_api
    return response


def sanitize_cust_api_payload(payload: Dict[str, Any]) -> Dict[str, Any]:
    payload = payload or {}
    cust_no = str(payload.get("custNo") or "").strip()
    cust_tel = normalize_tel(payload.get("custTel"))
    cust_name = str(payload.get("custCName") or "").strip()

    return {
        "keys": sorted(payload.keys()),
        "identity_mode": "custNo" if cust_no else "name_phone",
        "has_token": bool(payload.get("token")),
        "has_custNo": bool(cust_no),
        "custNo_length": len(cust_no),
        "custNo_last4": cust_no[-4:] if cust_no else "",
        "has_custTel": bool(cust_tel),
        "custTel_last3": cust_tel[-3:] if cust_tel else "",
        "has_custCName": bool(cust_name),
        "custCName_length": len(cust_name),
    }


def response_text_preview(response) -> str:
    text = getattr(response, "text", "") or ""
    text = str(text).replace("\r", " ").replace("\n", " ").strip()
    return text[:300]


def call_json_text(custNo: bool, json_data: Dict[str, Any], token: str) -> Dict[str, Any]:
    if custNo:
        return {
            "token": token,
            "custTel": normalize_tel(json_data.get("phone")) or "",
            "custCName": str(json_data.get("name") or "").strip(),
            "custNo": str(json_data.get("custnum") or "").strip(),
        }

    return call_json_text2(json_data, token)


def call_json_text2(json_data: Dict[str, Any], token: str) -> Dict[str, Any]:
    return {
        "token": token,
        "custTel": normalize_tel(json_data.get("phone")) or "",
        "custCName": str(json_data.get("name") or "").strip(),
    }


def validate_customer_identity(name: Any, phone: Any) -> Tuple[List[str], Optional[str], Optional[str]]:
    missing = []
    normalized_name = str(name or "").strip()
    normalized_phone = normalize_tel(phone)

    if not validate_name(normalized_name):
        missing.append("name")

    if not validate_tel(normalized_phone):
        missing.append("phone")

    return missing, normalized_name or None, normalized_phone


def validate_guest_identity_pair(
    name: Any,
    phone: Any,
    custnum: Any,
    authenticated_custnum: bool = False,
) -> Tuple[List[str], Optional[str], Optional[str], Optional[str]]:
    """Validate the two-of-three identity rule for guest account actions."""
    normalized_name = str(name or "").strip()
    normalized_phone = normalize_tel(phone)
    normalized_custnum = normalize_customer_number(custnum)

    if not validate_name(normalized_name):
        normalized_name = None
    if not validate_tel(normalized_phone):
        normalized_phone = None

    if authenticated_custnum and normalized_custnum:
        return [], normalized_name, normalized_phone, normalized_custnum

    provided_count = sum(
        value is not None
        for value in (normalized_custnum, normalized_name, normalized_phone)
    )
    if provided_count < 2:
        return ["identity_pair"], normalized_name, normalized_phone, normalized_custnum

    return [], normalized_name, normalized_phone, normalized_custnum


def missing_response(tool_name: str, message: str, missing: List[str]) -> Dict[str, Any]:
    return {
        "success": False,
        "tool_name": tool_name,
        "message": message,
        "data": {"missing": missing},
    }


def payload_uses_custnum(payload: Optional[Dict[str, Any]]) -> bool:
    if not isinstance(payload, dict):
        return False
    return bool(str(payload.get("custNo") or "").strip())


def customer_not_found_response(tool_name: str, used_custnum: bool) -> Dict[str, Any]:
    if tool_name == "bill_return_line_tv" and used_custnum:
        return missing_response(
            tool_name,
            TV_REACTIVATION_UNCONFIRMED_MESSAGE,
            [],
        )

    if used_custnum:
        return missing_response(
            tool_name,
            CUSTOMER_NOT_FOUND_BY_CUSTNUM_MESSAGE,
            [],
        )

    return missing_response(
        tool_name,
        CUSTOMER_NOT_FOUND_BY_NAME_PHONE_MESSAGE,
        ["name", "phone"],
    )


def send_message_customer_not_found_response(used_custnum: bool) -> Dict[str, Any]:
    if used_custnum:
        return missing_response(
            "send_message",
            CUSTOMER_NOT_FOUND_BY_CUSTNUM_PHONE_MESSAGE,
            [],
        )

    return customer_not_found_response("send_message", False)


def api_error_response(tool_name: str, message: str = API_BUSY_MESSAGE) -> Dict[str, Any]:
    return {
        "success": False,
        "tool_name": tool_name,
        "message": message,
        "data": {"missing": []},
    }


def api_success_response(
    tool_name: str,
    message: str,
    raw_data: Optional[Dict[str, Any]] = None,
    extra_data: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    data = {"raw": raw_data or {}}
    if extra_data:
        data.update(extra_data)
    return {
        "success": True,
        "tool_name": tool_name,
        "message": message,
        "data": data,
    }


def extract_bill_due_date(data: Dict[str, Any]) -> str:
    for key in BILL_DUE_DATE_KEYS:
        value = str(data.get(key) or "").strip()
        if value:
            return value
    return ""


def parse_bill_amount(value: Any) -> int:
    try:
        return int(float(str(value or "0").strip()))
    except Exception:
        return 0


def get_bill_amount_value(bill: Dict[str, Any]) -> Any:
    if "showAmt" in bill:
        return bill.get("showAmt")
    return bill.get("shoAmt")


def is_zero_amount_bill(bill: Dict[str, Any]) -> bool:
    return parse_bill_amount(get_bill_amount_value(bill)) == 0


def format_bill_list_response(bill_list: List[Dict[str, Any]]) -> Tuple[str, str]:
    payable_bills = [bill for bill in bill_list if not is_zero_amount_bill(bill)]
    if not payable_bills:
        return NO_UNPAID_BILL_MESSAGE, "no_unpaid"

    result_list = []
    total_amount = 0

    for bill in payable_bills:
        bill_type = str(bill.get("billType") or "未知帳單").strip()
        amount = parse_bill_amount(get_bill_amount_value(bill))
        due_date = extract_bill_due_date(bill)

        total_amount += amount

        if due_date:
            result_list.append(f"{bill_type}：{amount}元（已繳費迄日：{due_date}）")
        else:
            result_list.append(f"{bill_type}：{amount}元")

    return "\n".join(result_list) + f"\n合計：{total_amount}元", "payable"


def build_search_bill_response(
    data: Dict[str, Any],
    raw_data: Optional[Dict[str, Any]] = None,
    used_custnum: bool = False,
) -> Dict[str, Any]:
    raw = raw_data if raw_data is not None else data

    code = str(data.get("code") or "").strip()
    msg = str(data.get("msg") or "").strip()

    # CUST API 偶爾會在失敗狀態夾帶非本次查詢的 data；狀態碼與訊息必須優先。
    if msg == "查無客戶資料":
        return customer_not_found_response("search_bill", used_custnum)

    if msg == "查無客戶未繳帳單":
        return api_success_response(
            "search_bill",
            NO_UNPAID_BILL_MESSAGE,
            raw,
            {"bill_status": "no_unpaid"},
        )

    if code and code != "0000":
        return api_error_response("search_bill", msg or "帳單查詢失敗，請稍後再試。")

    if isinstance(data.get("data"), list):
        message, bill_status = format_bill_list_response(data.get("data", []))
        return api_success_response(
            "search_bill",
            message,
            raw,
            {"bill_status": bill_status},
        )

    if "billType" in data:
        amount_value = get_bill_amount_value(data)
        amount = str(amount_value or "").strip()
        due_date = extract_bill_due_date(data)
        if parse_bill_amount(amount_value) == 0:
            return api_success_response(
                "search_bill",
                NORMAL_BILL_STATUS_MESSAGE,
                raw,
                {"bill_status": "no_unpaid"},
            )
        return api_success_response(
            "search_bill",
            (
                f"{data.get('billType')}：{amount}元"
                + (f"\n繳費到期日：{due_date}" if due_date else "")
            ),
            raw,
            {"bill_status": "payable"},
        )

    if msg == "成功":
        return api_success_response(
            "search_bill",
            NORMAL_BILL_STATUS_MESSAGE,
            raw,
            {"bill_status": "no_unpaid"},
        )

    if msg:
        return api_success_response("search_bill", msg, raw, {"bill_status": "unknown"})

    return api_success_response("search_bill", "目前查無帳單資料", raw, {"bill_status": "unknown"})


def append_mock_endpoint(
    response: Dict[str, Any],
    endpoint_url: str = SEARCH_BILL_URL,
) -> Dict[str, Any]:
    if response.get("success"):
        response = dict(response)
        response["message"] = f"{response.get('message', '')}\n模擬 endpoint：{endpoint_url}"
    return response


IGNORED_CONTRACT_PRODUCT_TYPES = {"CATV", "DTV"}
IGNORED_CONTRACT_PRODUCT_NAMES = {"基本頻道", "數位電視頻道"}
IGNORED_CONTRACT_PRODUCT_STATUSES = {
    "停用",
    "已停用",
    "終止",
    "已終止",
    "退租",
    "已退租",
    "取消",
    "已取消",
}


def should_ignore_contract_product(product: Dict[str, Any]) -> bool:
    product_type = str(product.get("prdTypeName") or "").strip().upper()
    product_name = str(product.get("pkgPrdName") or "").strip()
    status = str(product.get("useStatusName") or "").strip()

    return (
        product_type in IGNORED_CONTRACT_PRODUCT_TYPES
        or product_name in IGNORED_CONTRACT_PRODUCT_NAMES
        or status in IGNORED_CONTRACT_PRODUCT_STATUSES
    )


def format_mbps_value(value: float) -> str:
    if value.is_integer():
        return str(int(value))
    return f"{value:.1f}".rstrip("0").rstrip(".")


def format_bandwidth_value(mbps: float) -> str:
    if mbps >= 1000:
        gbps = mbps / 1000
        return f"{format_mbps_value(gbps)} Gbps"
    return f"{format_mbps_value(mbps)} Mbps"


def parse_speed_token_to_mbps(token: str) -> Optional[float]:
    value = str(token or "").strip()
    if not value:
        return None

    upper = value.upper().replace("MBPS", "M")
    upper = re.sub(r"[^\d.KM]+", "", upper)
    if not upper:
        return None

    multiplier = 1.0
    if upper.endswith("K"):
        upper = upper[:-1]
        multiplier = 0.001
    elif upper.endswith("M"):
        upper = upper[:-1]

    try:
        return float(upper) * multiplier
    except Exception:
        return None


def format_speed_text(speed: Any) -> str:
    text = str(speed or "").strip()
    if not text:
        return ""

    normalized_text = (
        text
        .replace("／", "/")
        .replace("∕", "/")
        .replace("\\", "/")
    )
    parts = [part.strip() for part in normalized_text.split("/") if part.strip()]
    if not parts:
        return ""

    download = parse_speed_token_to_mbps(parts[0])
    upload = parse_speed_token_to_mbps(parts[1]) if len(parts) > 1 else None

    if download is None and upload is None:
        return text

    if download is not None and upload is not None:
        return f"下載 {format_bandwidth_value(download)} / 上傳 {format_bandwidth_value(upload)}"

    if download is not None:
        return format_bandwidth_value(download)

    return f"上傳 {format_bandwidth_value(upload)}"


def format_contract_products_response(data: Dict[str, Any]) -> str:
    msg = str(data.get("msg") or "").strip()
    product_list = data.get("data")

    if msg == "查無客戶資料":
        return CUSTOMER_NOT_FOUND_MESSAGE

    if not isinstance(product_list, list):
        return msg or "目前查無合約或服務產品資料。"

    if not product_list:
        return "目前查無合約或服務產品資料。"

    visible_products = [
        product for product in product_list
        if isinstance(product, dict) and not should_ignore_contract_product(product)
    ]

    if not visible_products:
        return (
            "已查詢到資料；基本頻道與數位電視頻道通常無綁約，"
            "因此不列入合約到期日查詢。目前沒有其他需要顯示的服務內容。"
        )

    lines = ["已為您查詢目前服務與合約資訊："]
    for index, product in enumerate(visible_products, start=1):
        product_name = str(product.get("pkgPrdName") or "未命名服務").strip()
        product_type = str(product.get("prdTypeName") or "").strip()
        status = str(product.get("useStatusName") or "未提供").strip()
        contract_date = str(product.get("conDate") or "").strip()
        speed_text = format_speed_text(product.get("speed"))

        title = f"{index}. {product_name}"
        if product_type:
            title += f"（{product_type}）"

        lines.append(title)
        lines.append(f"   狀態：{status}")
        if speed_text:
            lines.append(f"   速率：{speed_text}")
        if contract_date and contract_date != "無合約":
            lines.append(f"   合約到期日：{contract_date}")
        elif contract_date == "無合約":
            lines.append("   合約：無綁約")
        else:
            lines.append("   合約：無綁約或未提供到期日")

    return "\n".join(lines)


def build_contract_info_response(
    data: Dict[str, Any],
    raw_data: Optional[Dict[str, Any]] = None,
    used_custnum: bool = False,
) -> Dict[str, Any]:
    raw = raw_data if raw_data is not None else data

    if str(data.get("msg") or "").strip() == "查無客戶資料":
        return customer_not_found_response("search_contract_info", used_custnum)

    return api_success_response(
        "search_contract_info",
        format_contract_products_response(data),
        raw,
    )


def call_contract_info(json_text: Dict[str, Any]) -> Dict[str, Any]:
    ok, data = call_customer_endpoint(CONTRACT_INFO_URL, json_text)
    data, metas = extract_cust_api_meta(data)
    if not ok:
        return attach_cust_api_timing(api_error_response("search_contract_info"), *metas)

    return attach_cust_api_timing(
        build_contract_info_response(data, used_custnum=payload_uses_custnum(json_text)),
        *metas,
    )


def format_channel_query_response(
    data: Dict[str, Any],
    channel_name: str,
    raw_data: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    raw = raw_data if raw_data is not None else data
    rows = data.get("data")

    if isinstance(rows, list) and rows:
        lines = [f"已查詢到「{channel_name}」相關頻道："]
        for item in rows:
            if not isinstance(item, dict):
                continue
            name = str(item.get("channelName") or "").strip()
            channel_id = str(item.get("channelId") or "").strip()
            if name and channel_id:
                lines.append(f"{name}：第 {channel_id} 台")
            elif name:
                lines.append(name)

        if len(lines) > 1:
            return api_success_response(
                "search_channel_no",
                "\n".join(lines),
                raw,
            )

    if str(data.get("code") or "").strip() == "0000":
        return api_success_response(
            "search_channel_no",
            f"目前查不到「{channel_name}」的頻道資料。",
            raw,
        )

    return api_error_response(
        "search_channel_no",
        str(data.get("msg") or "").strip() or API_BUSY_MESSAGE,
    )


def call_channel_no(json_text: Dict[str, Any], channel_name: str) -> Dict[str, Any]:
    ok, data = call_customer_endpoint(CHANNEL_QUERY_URL, json_text)
    data, metas = extract_cust_api_meta(data)
    if not ok:
        return attach_cust_api_timing(api_error_response("search_channel_no"), *metas)

    return attach_cust_api_timing(format_channel_query_response(data, channel_name), *metas)


def call_customer_endpoint(url: str, payload: Dict[str, Any]) -> Tuple[bool, Dict[str, Any]]:
    started = time.perf_counter()
    tool_name = CUST_API_TOOL_NAMES.get(url, "unknown")
    try:
        response = requests.get(
            url,
            verify=False,
            json=payload,
            timeout=REQUEST_TIMEOUT,
        )
        elapsed = round(time.perf_counter() - started, 3)
        meta = {
            "type": "endpoint",
            "method": "GET",
            "url": url,
            "elapsed_sec": elapsed,
            "status_code": response.status_code,
            "success": response.status_code == 200,
            "payload": sanitize_cust_api_payload(payload),
        }
        if response.status_code != 200:
            log_cust_api_diagnostic(
                tool_name=tool_name,
                url=url,
                payload=payload,
                http_status=response.status_code,
                stage="endpoint",
                elapsed_sec=elapsed,
                success=False,
                error_detail=getattr(response, "text", ""),
            )
            meta["response_preview"] = response_text_preview(response)
            return False, {"status_code": response.status_code, CUST_API_META_KEY: meta}

        data = response.json()
        clean_data = data if isinstance(data, dict) else {}
        log_cust_api_diagnostic(
            tool_name=tool_name,
            url=url,
            payload=payload,
            http_status=response.status_code,
            response_data=clean_data,
            stage="endpoint",
            elapsed_sec=elapsed,
            success=True,
        )
        clean_data = dict(clean_data)
        clean_data[CUST_API_META_KEY] = meta
        return True, clean_data
    except Exception as exc:
        elapsed = round(time.perf_counter() - started, 3)
        log_cust_api_diagnostic(
            tool_name=tool_name,
            url=url,
            payload=payload,
            http_status=None,
            error_type=type(exc).__name__,
            stage="endpoint",
            elapsed_sec=elapsed,
            success=False,
            error_detail=str(exc),
        )
        return False, {
            "error": str(exc),
            CUST_API_META_KEY: {
                "type": "endpoint",
                "method": "GET",
                "url": url,
                "elapsed_sec": round(time.perf_counter() - started, 3),
                "success": False,
                "error": str(exc),
                "payload": sanitize_cust_api_payload(payload),
            },
        }


def call_search_bill(json_text: Dict[str, Any]) -> Dict[str, Any]:
    ok, data = call_customer_endpoint(SEARCH_BILL_URL, json_text)
    data, metas = extract_cust_api_meta(data)
    if not ok:
        return attach_cust_api_timing(api_error_response("search_bill"), *metas)

    return attach_cust_api_timing(
        build_search_bill_response(data, used_custnum=payload_uses_custnum(json_text)),
        *metas,
    )


def bill_return_line_internet(json_text: Dict[str, Any]) -> Dict[str, Any]:
    return call_return_line_endpoint(
        tool_name="bill_return_line_internet",
        url=INTERNET_RETURN_URL,
        payload=json_text,
    )


def bill_return_line_tv(json_text: Dict[str, Any]) -> Dict[str, Any]:
    return call_return_line_endpoint(
        tool_name="bill_return_line_tv",
        url=TV_RETURN_URL,
        payload=json_text,
    )


def call_return_line_endpoint(
    tool_name: str,
    url: str,
    payload: Dict[str, Any],
) -> Dict[str, Any]:
    ok, data = call_customer_endpoint(url, payload)
    data, metas = extract_cust_api_meta(data)
    if not ok:
        return attach_cust_api_timing(api_error_response(tool_name), *metas)

    msg = str(data.get("msg") or "").strip()
    if "查無客戶" in msg:
        response = customer_not_found_response(tool_name, payload_uses_custnum(payload))
        response["message"] += "\n如您已繳費，請記得將設備電源關機重開。\n貼心提醒，透過 IBON及FAMIPORT繳費方式系統會自動開通喔"
        return attach_cust_api_timing(
            response,
            *metas,
        )

    return attach_cust_api_timing(api_success_response(tool_name, msg or "已送出復機申請", data), *metas)


def send_message(json_text: Dict[str, Any]) -> Dict[str, Any]:
    ok, data = call_customer_endpoint(SEND_MESSAGE_URL, json_text)
    data, metas = extract_cust_api_meta(data)
    if not ok:
        return attach_cust_api_timing(api_error_response("send_message"), *metas)

    msg = str(data.get("msg") or "").strip()
    if "查無客戶" in msg:
        return attach_cust_api_timing(
            send_message_customer_not_found_response(payload_uses_custnum(json_text)),
            *metas,
        )

    success_msg = msg or "已送出簡訊帳單補發申請"
    if "登記電話" not in success_msg:
        success_msg = f"{success_msg}\n簡訊帳單會寄送至登記電話，無法改寄或指定其他電話。"
    return attach_cust_api_timing(api_success_response("send_message", success_msg, data), *metas)


def call_payment_barcode_endpoint(payload: Dict[str, Any]) -> Dict[str, Any]:
    ok, data = call_customer_endpoint(PAYMENT_BARCODE_URL, payload)
    data, metas = extract_cust_api_meta(data)
    if not ok:
        return attach_cust_api_timing(api_error_response("payment_bill_batch"), *metas)

    msg = str(data.get("msg") or "").strip()
    return attach_cust_api_timing(
        api_success_response(
            "payment_bill_batch",
            msg or "已確認超商收據繳費資料；若先前因欠費停用，系統將進行復線處理。請將數據機或機上盒重新開機後再確認服務是否正常。",
            data,
        ),
        *metas,
    )


def is_store_kiosk_barcode(second_barcode: Any) -> bool:
    return any(char.isalpha() for char in str(second_barcode or ""))


def payment_item_code(second_barcode: Any) -> str:
    value = str(second_barcode or "").strip()
    if not value.isdigit():
        return ""
    for code in sorted(COMPANY_PAYMENT_ITEM_CODES, key=len, reverse=True):
        if value.startswith(code):
            return code
    return value[:6] if len(value) >= 6 else value


def is_company_payment_item(second_barcode: Any) -> bool:
    code = payment_item_code(second_barcode)
    return bool(code and code in COMPANY_PAYMENT_ITEM_CODES)


def is_non_company_numeric_payment_item(second_barcode: Any) -> bool:
    value = str(second_barcode or "").strip()
    return bool(value.isdigit() and not is_company_payment_item(value))


def non_company_payment_item_message(code: str = "") -> str:
    return NON_COMPANY_PAYMENT_ITEM_MESSAGE


def build_payment_barcode_payload(token: str, first_barcode: Any, second_barcode: Any, third_barcode: Any) -> Dict[str, Any]:
    return {
        "token": token,
        "barCode1": str(first_barcode or "").strip(),
        "barCode2": str(second_barcode or "").strip(),
        "barCode3": str(third_barcode or "").strip(),
    }


def normalize_payment_bill_item(bill: Dict[str, Any]) -> Dict[str, str]:
    bill = bill or {}
    return {
        "first_barcode": str(bill.get("first_barcode") or bill.get("first_num") or "").strip(),
        "second_barcode": str(bill.get("second_barcode") or bill.get("second_num") or "").strip(),
        "third_barcode": str(bill.get("third_barcode") or bill.get("third_num") or "").strip(),
    }


def normalize_payment_bills(
    bills: Any = None,
    first_barcode: Any = None,
    second_barcode: Any = None,
    third_barcode: Any = None,
) -> List[Dict[str, str]]:
    if isinstance(bills, list):
        return [
            normalize_payment_bill_item(item)
            for item in bills
            if isinstance(item, dict)
        ]

    return [
        {
            "first_barcode": str(first_barcode or "").strip(),
            "second_barcode": str(second_barcode or "").strip(),
            "third_barcode": str(third_barcode or "").strip(),
        }
    ]


def missing_payment_bill_slots(bills: List[Dict[str, str]]) -> List[str]:
    if not bills:
        return ["first_barcode", "second_barcode", "third_barcode"]

    missing = []
    for index, bill in enumerate(bills):
        for key in ["first_barcode", "second_barcode", "third_barcode"]:
            if not str(bill.get(key) or "").strip():
                missing.append(f"bills[{index}].{key}" if len(bills) > 1 else key)
    return missing


def payment_bill_prefix(index: int, total_count: int) -> str:
    return "這筆帳單" if total_count == 1 else f"第{index}筆帳單"


def store_kiosk_payment_message() -> str:
    return (
        "系統判讀為便利商店事務機繳費。"
        "若先前因欠費停用，系統將自動恢復訊號。"
        "請將數據機或機上盒重新開機，再確認網路或電視是否正常。"
    )


def build_payload_from_identity(
    token: str,
    name: Any = None,
    phone: Any = None,
    custnum: Any = None,
    allow_custnum: bool = False,
) -> Tuple[Optional[Dict[str, Any]], Optional[Dict[str, Any]]]:
    if allow_custnum and custnum:
        payload = call_json_text(
            True,
            {"custnum": str(custnum).strip()},
            token,
        )
        return payload, None

    missing, normalized_name, normalized_phone = validate_customer_identity(name, phone)
    if missing:
        return None, {
            "missing": missing,
            "name": normalized_name,
            "phone": normalized_phone,
        }

    payload = call_json_text2(
        {"name": normalized_name, "phone": normalized_phone},
        token,
    )
    return payload, None


def build_mock_identity_payload(
    name: Any = None,
    phone: Any = None,
    custnum: Any = None,
    **extra: Any,
) -> Dict[str, Any]:
    payload = {
        "custNo": str(custnum or "").strip(),
        "custTel": normalize_tel(phone) or "",
        "custCName": str(name or "").strip(),
    }
    payload.update(extra)
    return payload


def exec_payment_bill_batch(
    first_barcode=None,
    second_barcode=None,
    third_barcode=None,
    bills=None,
    receipt_image_evidence=None,
):
    evidence = receipt_image_evidence if isinstance(receipt_image_evidence, dict) else {}
    evidence_bills = evidence.get("bills") if evidence.get("verified") else None
    if not isinstance(evidence_bills, list) or not evidence_bills:
        return missing_response(
            "payment_bill_batch",
            RECEIPT_IMAGE_REUPLOAD_REPLY,
            ["receipt_image_evidence"],
        )

    payment_bills = normalize_payment_bills(bills=evidence_bills)
    missing = missing_payment_bill_slots(payment_bills)
    if missing:
        return missing_response(
            "payment_bill_batch",
            RECEIPT_IMAGE_REUPLOAD_REPLY,
            missing,
        )

    if CUST_API_USE_MOCK:
        results = []
        raw_results = []
        total_count = len(payment_bills)
        for index, bill in enumerate(payment_bills, start=1):
            payload_without_token = {
                "barCode1": bill["first_barcode"],
                "barCode2": bill["second_barcode"],
                "barCode3": bill["third_barcode"],
            }
            if is_store_kiosk_barcode(bill["second_barcode"]):
                msg = store_kiosk_payment_message()
                raw = mock_api_response(
                    "receiveByBarCode",
                    payload_without_token,
                    {
                        "status": "store_kiosk_payment",
                        "msg": "系統判讀為便利商店事務機繳費，若先前因欠費停用，系統將自動恢復訊號。",
                    },
                )
            elif is_non_company_numeric_payment_item(bill["second_barcode"]):
                msg = non_company_payment_item_message(payment_item_code(bill["second_barcode"]))
                raw = mock_api_response(
                    "receiveByBarCode",
                    payload_without_token,
                    {
                        "status": "non_company_payment_item",
                        "msg": msg,
                    },
                )
            else:
                msg = (
                    "已用模擬超商收據條碼 API 確認繳費資料。"
                    "若先前因欠費停用，系統將進行復線處理。"
                    "請將數據機或機上盒重新開機，再確認網路或電視是否正常。"
                )
                raw = mock_api_response(
                    "receiveByBarCode",
                    payload_without_token,
                    {
                        "status": "mock_received",
                        "msg": "模擬超商收據條碼確認成功，若先前因欠費停用，系統將進行復線處理。",
                    },
                )
            results.append(f"{payment_bill_prefix(index, total_count)}：{msg}")
            raw_results.append(raw)

        return api_success_response(
            "payment_bill_batch",
            "\n".join(results),
            raw_results[0] if len(raw_results) == 1 else {"results": raw_results},
            {"bill_count": total_count},
        )

    if all(
        is_store_kiosk_barcode(bill["second_barcode"])
        or is_non_company_numeric_payment_item(bill["second_barcode"])
        for bill in payment_bills
    ):
        total_count = len(payment_bills)
        raw_results = []
        results = []
        for index, bill in enumerate(payment_bills, start=1):
            payload_without_token = {
                "barCode1": bill["first_barcode"],
                "barCode2": bill["second_barcode"],
                "barCode3": bill["third_barcode"],
            }
            if is_store_kiosk_barcode(bill["second_barcode"]):
                msg = store_kiosk_payment_message()
                raw = mock_api_response(
                    "receiveByBarCode",
                    payload_without_token,
                    {
                        "status": "store_kiosk_payment",
                        "msg": "系統判讀為便利商店事務機繳費，若先前因欠費停用，系統將自動恢復訊號。",
                    },
                )
            else:
                msg = non_company_payment_item_message(payment_item_code(bill["second_barcode"]))
                raw = mock_api_response(
                    "receiveByBarCode",
                    payload_without_token,
                    {
                        "status": "non_company_payment_item",
                        "msg": msg,
                    },
                )
            results.append(f"{payment_bill_prefix(index, total_count)}：{msg}")
            raw_results.append(raw)
        return api_success_response(
            "payment_bill_batch",
            "\n".join(results),
            raw_results[0] if len(raw_results) == 1 else {"results": raw_results},
            {"bill_count": total_count},
        )

    requires_payment_api = any(
        not is_store_kiosk_barcode(bill["second_barcode"])
        and not is_non_company_numeric_payment_item(bill["second_barcode"])
        for bill in payment_bills
    )
    token_meta = None
    token = ""
    if requires_payment_api:
        token, token_meta = get_token_with_timing()
        if not token:
            return attach_cust_api_timing(api_error_response("payment_bill_batch", TOKEN_BUSY_MESSAGE), token_meta)

    results = []
    raw_results = []
    endpoint_metas = []
    total_count = len(payment_bills)
    for index, bill in enumerate(payment_bills, start=1):
        if is_store_kiosk_barcode(bill["second_barcode"]):
            msg = store_kiosk_payment_message()
            raw = mock_api_response(
                "receiveByBarCode",
                {
                    "barCode1": bill["first_barcode"],
                    "barCode2": bill["second_barcode"],
                    "barCode3": bill["third_barcode"],
                },
                {
                    "status": "store_kiosk_payment",
                    "msg": "系統判讀為便利商店事務機繳費，若先前因欠費停用，系統將自動恢復訊號。",
                },
            )
        elif is_non_company_numeric_payment_item(bill["second_barcode"]):
            msg = non_company_payment_item_message(payment_item_code(bill["second_barcode"]))
            raw = mock_api_response(
                "receiveByBarCode",
                {
                    "barCode1": bill["first_barcode"],
                    "barCode2": bill["second_barcode"],
                    "barCode3": bill["third_barcode"],
                },
                {
                    "status": "non_company_payment_item",
                    "msg": msg,
                },
            )
        else:
            payload = build_payment_barcode_payload(
                token,
                bill["first_barcode"],
                bill["second_barcode"],
                bill["third_barcode"],
            )
            api_result = call_payment_barcode_endpoint(payload)
            raw, metas = extract_cust_api_meta(api_result.get("data", {}).get("raw", {}))
            if api_result.get("cust_api"):
                endpoint_metas.extend(api_result.get("cust_api", {}).get("calls") or [])
            msg = str(api_result.get("message") or "資料有誤，請重新查詢，謝謝").strip()
            if not api_result.get("success"):
                msg = str(api_result.get("message") or "連線失敗，請重新查詢，謝謝").strip()
            raw = raw or api_result.get("data", {}).get("raw", {})
            endpoint_metas.extend(metas)

        results.append(f"{payment_bill_prefix(index, total_count)}：{msg}")
        raw_results.append(raw)

    response = api_success_response(
        "payment_bill_batch",
        "\n".join(results),
        raw_results[0] if len(raw_results) == 1 else {"results": raw_results},
        {"bill_count": total_count},
    )
    return attach_cust_api_timing(response, token_meta, *endpoint_metas)


def exec_search_bill(name=None, phone=None, custnum=None, authenticated_custnum=False):
    missing, normalized_name, normalized_phone, normalized_custnum = validate_guest_identity_pair(
        name,
        phone,
        custnum,
        authenticated_custnum=authenticated_custnum,
    )
    if missing:
        return missing_response("search_bill", GUEST_IDENTITY_PAIR_MESSAGE, missing)

    if CUST_API_USE_MOCK:
        data = find_mock_bill(normalized_name, normalized_phone, normalized_custnum)
        raw = mock_api_response(
            "getCustBill",
            {
                "custNo": normalized_custnum or "",
                "custTel": normalized_phone or "",
                "custCName": normalized_name or "",
            },
            data,
        )

        return append_mock_endpoint(
            build_search_bill_response(data, raw, used_custnum=bool(normalized_custnum))
        )

    token, token_meta = get_token_with_timing()
    if not token:
        return attach_cust_api_timing(api_error_response("search_bill", TOKEN_BUSY_MESSAGE), token_meta)

    if normalized_custnum:
        payload = call_json_text(
            True,
            {
                "custnum": normalized_custnum,
                "name": normalized_name,
                "phone": normalized_phone,
            },
            token,
        )
    else:
        payload = call_json_text2(
            {"name": normalized_name, "phone": normalized_phone},
            token,
        )

    return attach_cust_api_timing(call_search_bill(payload), token_meta)


def exec_send_message(name=None, phone=None, custnum=None):
    normalized_custnum = normalize_customer_number(custnum)
    normalized_phone = normalize_tel(phone)
    if custnum and not normalized_custnum:
        return missing_response(
            "send_message",
            "目前只能使用 API 登入資料補發簡訊帳單；請同時提供戶名與登記電話。",
            ["name", "phone"],
        )

    if normalized_custnum:
        if not validate_tel(normalized_phone):
            return missing_response(
                "send_message",
                SEND_MESSAGE_CUSTNUM_PHONE_REQUIRED_MESSAGE,
                ["phone"],
            )
        normalized_name = None
    else:
        missing, normalized_name, normalized_phone = validate_customer_identity(name, normalized_phone)
        if missing:
            return missing_response(
                "send_message",
                "補發簡訊帳單需要有效的戶名與登記電話；簡訊帳單無法改寄或指定其他電話。",
                missing,
            )

    if CUST_API_USE_MOCK:
        payload = build_mock_identity_payload(
            normalized_name,
            normalized_phone,
            normalized_custnum,
        )
        if normalized_custnum:
            is_valid_identity = (
                normalized_custnum == MOCK_CUSTOMER["custNo"]
                and normalized_phone == MOCK_CUSTOMER["custTel"]
            )
        else:
            is_valid_identity = is_mock_customer_identity(
                normalized_name,
                normalized_phone,
                normalized_custnum,
            )
        if not is_valid_identity:
            return send_message_customer_not_found_response(bool(normalized_custnum))

        raw = mock_api_response(
            "reBillE",
            payload,
            {
                "status": "mock_sent",
                "msg": "模擬簡訊帳單補發請求已送出，正式 API 接上後才會發送真實簡訊。",
            },
        )
        return api_success_response(
            "send_message",
            (
                "已用模擬簡訊帳單 API 送出測試請求。\n"
                "提醒：目前只是 mock 情境，尚未發送真實簡訊。\n"
                "正式流程會寄送至登記電話，無法改寄或指定其他電話。\n"
                f"模擬 endpoint：{SEND_MESSAGE_URL}"
            ),
            raw,
        )

    token, token_meta = get_token_with_timing()
    if not token:
        return attach_cust_api_timing(api_error_response("send_message", TOKEN_BUSY_MESSAGE), token_meta)

    if normalized_custnum:
        payload = call_json_text(
            True,
            {"custnum": normalized_custnum, "phone": normalized_phone},
            token,
        )
    else:
        payload = call_json_text2(
            {"name": normalized_name, "phone": normalized_phone},
            token,
        )

    return attach_cust_api_timing(send_message(payload), token_meta)


def exec_bill_return_line_internet(name=None, phone=None, custnum=None, authenticated_custnum=False):
    missing, normalized_name, normalized_phone, normalized_custnum = validate_guest_identity_pair(
        name,
        phone,
        custnum,
        authenticated_custnum=authenticated_custnum,
    )
    if missing:
        return missing_response(
            "bill_return_line_internet",
            GUEST_IDENTITY_PAIR_MESSAGE,
            missing,
        )

    if CUST_API_USE_MOCK:
        payload = build_mock_identity_payload(
            normalized_name,
            normalized_phone,
            normalized_custnum,
            service="internet",
        )
        if not is_mock_customer_identity(normalized_name, normalized_phone, normalized_custnum):
            return customer_not_found_response(
                "bill_return_line_internet",
                bool(normalized_custnum),
            )

        raw = mock_api_response(
            "changeReceive",
            payload,
            {
                "status": "mock_received",
                "msg": "模擬網路復線申請已受理，正式 API 接上後才會送出真實復線。",
            },
        )
        return api_success_response(
            "bill_return_line_internet",
            (
                "已用模擬網路復線 API 送出測試申請。\n"
                "如您已繳費，請記得將設備電源關機重開。\n"
                f"模擬 endpoint：{INTERNET_RETURN_URL}"
            ),
            raw,
        )

    token, token_meta = get_token_with_timing()
    if not token:
        return attach_cust_api_timing(api_error_response("bill_return_line_internet", TOKEN_BUSY_MESSAGE), token_meta)

    if normalized_custnum:
        payload = call_json_text(
            True,
            {
                "custnum": normalized_custnum,
                "name": normalized_name,
                "phone": normalized_phone,
            },
            token,
        )
    else:
        payload = call_json_text2(
            {"name": normalized_name, "phone": normalized_phone},
            token,
        )

    return attach_cust_api_timing(bill_return_line_internet(payload), token_meta)


def exec_bill_return_line_tv(name=None, phone=None, custnum=None, authenticated_custnum=False):
    missing, normalized_name, normalized_phone, normalized_custnum = validate_guest_identity_pair(
        name,
        phone,
        custnum,
        authenticated_custnum=authenticated_custnum,
    )
    if missing:
        return missing_response(
            "bill_return_line_tv",
            GUEST_IDENTITY_PAIR_MESSAGE,
            missing,
        )

    if CUST_API_USE_MOCK:
        payload = build_mock_identity_payload(
            normalized_name,
            normalized_phone,
            normalized_custnum,
            service="tv",
        )
        if not is_mock_customer_identity(normalized_name, normalized_phone, normalized_custnum):
            return customer_not_found_response(
                "bill_return_line_tv",
                bool(normalized_custnum),
            )

        raw = mock_api_response(
            "dtvChangeReceive",
            payload,
            {
                "status": "mock_received",
                "msg": "模擬電視復線申請已受理，正式 API 接上後才會送出真實復線。",
            },
        )
        return api_success_response(
            "bill_return_line_tv",
            (
                "已用模擬電視復線 API 送出測試申請。\n"
                "如您已繳費，請記得將設備電源關機重開。\n"
                f"模擬 endpoint：{TV_RETURN_URL}"
            ),
            raw,
        )

    token, token_meta = get_token_with_timing()
    if not token:
        return attach_cust_api_timing(api_error_response("bill_return_line_tv", TOKEN_BUSY_MESSAGE), token_meta)

    if normalized_custnum:
        payload = call_json_text(
            True,
            {
                "custnum": normalized_custnum,
                "name": normalized_name,
                "phone": normalized_phone,
            },
            token,
        )
    else:
        payload = call_json_text2(
            {"name": normalized_name, "phone": normalized_phone},
            token,
        )

    return attach_cust_api_timing(bill_return_line_tv(payload), token_meta)


def exec_create_repair_ticket(
    contact_name=None,
    contact_phone=None,
    service_address=None,
    issue_description=None,
    preferred_date=None,
    preferred_time_range=None,
):
    return {
        "success": True,
        "tool_name": "create_repair_ticket",
        "message": "已建立報修工單",
        "data": {
            "contact_name": contact_name,
            "contact_phone": contact_phone,
            "service_address": service_address,
            "issue_description": issue_description,
            "preferred_date": preferred_date,
            "preferred_time_range": preferred_time_range,
        },
    }


def exec_search_contract_info(name=None, phone=None, custnum=None):
    normalized_custnum = normalize_customer_number(custnum)
    if not normalized_custnum:
        return {
            "success": False,
            "tool_name": "search_contract_info",
            "message": CONTRACT_LOOKUP_LOGIN_REQUIRED_REPLY,
            "data": {"missing": [], "access_denied": True},
        }

    if CUST_API_USE_MOCK:
        payload = {
            "custNo": normalized_custnum or "",
            "custCName": "",
            "custTel": "",
        }
        if not is_mock_customer_identity(
            None,
            None,
            normalized_custnum,
        ):
            return customer_not_found_response(
                "search_contract_info",
                bool(normalized_custnum),
            )

        raw = mock_api_response("getCustProd", payload, MOCK_CONTRACT_PRODUCTS)
        response = build_contract_info_response(
            MOCK_CONTRACT_PRODUCTS,
            raw,
            used_custnum=bool(normalized_custnum),
        )
        return append_mock_endpoint(response, CONTRACT_INFO_URL)

    token, token_meta = get_token_with_timing()
    if not token:
        return attach_cust_api_timing(api_error_response("search_contract_info", TOKEN_BUSY_MESSAGE), token_meta)

    if normalized_custnum:
        payload = call_json_text(
            True,
            {"custnum": normalized_custnum},
            token,
        )

    return attach_cust_api_timing(call_contract_info(payload), token_meta)


def exec_search_channel_no(service_area=None, channel_name=None):
    channel = str(channel_name or "").strip()
    if not channel:
        return missing_response(
            "search_channel_no",
            "查詢頻道號需要頻道名稱。",
            ["channel_name"],
        )

    if not CUST_API_USE_MOCK:
        token, token_meta = get_token_with_timing()
        if not token:
            return attach_cust_api_timing(api_error_response("search_channel_no", TOKEN_BUSY_MESSAGE), token_meta)

        return attach_cust_api_timing(
            call_channel_no(
                {
                    "token": token,
                    "channelName": channel,
                },
                channel,
            ),
            token_meta,
        )

    payload = {"channelName": channel}
    data = find_mock_channel(channel)
    raw = mock_api_response("channelNo", payload, data)

    if isinstance(data.get("data"), list):
        response = format_channel_query_response(data, channel, raw)
        return append_mock_endpoint(response, CHANNEL_QUERY_URL)

    if data.get("channelNo"):
        message = (
            "已用模擬頻道 API 查詢頻道位置：\n"
            f"頻道名稱：{data['name']}\n"
            f"頻道號：{data['channelNo']}\n"
            f"備註：{data['note']}\n"
            f"模擬 endpoint：{CHANNEL_QUERY_URL}"
        )
    else:
        message = (
            f"模擬頻道 API 目前查不到「{channel}」的頻道號。"
            "正式 API 接上後可依頻道名稱查詢。"
        )

    return api_success_response("search_channel_no", message, raw)


def exec_search_service_availability(service_address=None, install_service=None):
    address = str(service_address or "").strip()
    service = str(install_service or "寬頻上網").strip()
    if not address:
        return missing_response(
            "search_service_availability",
            "查詢地址是否可申辦需要提供服務地址或鄉鎮市區。",
            ["service_address"],
        )

    payload = {"serviceAddress": address, "service": service}
    data = check_mock_service_availability(address)
    raw = mock_api_response("serviceAvailability", payload, data)

    if data["available"] is True:
        status = "可進一步申辦"
    elif data["available"] is False:
        status = "目前模擬資料顯示不可申辦"
    else:
        status = "需正式 API 進一步確認"

    return api_success_response(
        "search_service_availability",
        (
            "已用模擬服務範圍 API 查詢：\n"
            f"查詢地址/區域：{address}\n"
            f"服務項目：{service}\n"
            f"查詢結果：{status}\n"
            f"說明：{data['message']}\n"
            f"模擬 endpoint：{SERVICE_AVAILABILITY_URL}"
        ),
        raw,
    )


def exec_apply_new_install(
    contact_name=None,
    contact_phone=None,
    service_address=None,
    install_service=None,
    desired_plan=None,
):
    missing = []
    if not validate_name(str(contact_name or "").strip()):
        missing.append("contact_name")
    phone = normalize_tel(contact_phone)
    if not validate_tel(phone):
        missing.append("contact_phone")
    if not service_address:
        missing.append("service_address")
    if not install_service:
        missing.append("install_service")
    if missing:
        return missing_response(
            "apply_new_install",
            "申請裝機需要聯絡人、聯絡電話、服務地址與申辦服務。",
            missing,
        )

    payload = {
        "contactName": str(contact_name).strip(),
        "contactPhone": phone,
        "serviceAddress": str(service_address).strip(),
        "installService": str(install_service).strip(),
        "desiredPlan": str(desired_plan or "").strip(),
    }
    data = {
        "requestId": "MOCK-INSTALL-20260513-001",
        "status": "mock_received",
        "message": "模擬資料已收件，正式 API 接上後才會建立真實申裝案件。",
    }
    raw = mock_api_response("newInstall", payload, data)

    return api_success_response(
        "apply_new_install",
        (
            "已用模擬裝機申請 API 建立測試申請：\n"
            f"申請編號：{data['requestId']}\n"
            f"申辦服務：{payload['installService']}\n"
            f"服務地址：{payload['serviceAddress']}\n"
            "提醒：目前只是 mock 情境，尚未送出正式申裝。\n"
            f"模擬 endpoint：{NEW_INSTALL_URL}"
        ),
        raw,
    )


def exec_search_addon_plans(service_area=None, addon_name=None):
    area = str(service_area or "").strip()
    addon = str(addon_name or "").strip()
    missing = []
    if not area:
        missing.append("service_area")
    if not addon:
        missing.append("addon_name")
    if missing:
        return missing_response(
            "search_addon_plans",
            "查詢加值方案需要服務地區與加值服務名稱。",
            missing,
        )

    data = None
    for key, item in MOCK_ADDON_PLANS.items():
        if key.lower() in addon.lower() or addon.lower() in key.lower():
            data = dict(item)
            break
    if data is None:
        data = {
            "name": addon,
            "available": None,
            "purchaseUrl": "https://mock-api.local/official/addons",
            "note": "模擬資料沒有此加值服務，正式 API 可查實際方案。",
        }

    payload = {"serviceArea": area, "addonName": addon}
    raw = mock_api_response("addonPlans", payload, data)

    return api_success_response(
        "search_addon_plans",
        (
            "已用模擬加值方案 API 查詢：\n"
            f"加值服務：{data['name']}\n"
            f"服務地區：{area}\n"
            f"購買/說明連結：{data['purchaseUrl']}\n"
            f"備註：{data['note']}\n"
            f"模擬 endpoint：{ADDON_PLAN_URL}"
        ),
        raw,
    )


def exec_cancel_repair_ticket(repair_ticket_id=None, contact_phone=None):
    ticket_id = str(repair_ticket_id or "").strip()
    phone = normalize_tel(contact_phone)
    missing = []
    if not ticket_id:
        missing.append("repair_ticket_id")
    if not validate_tel(phone):
        missing.append("contact_phone")
    if missing:
        return missing_response(
            "cancel_repair_ticket",
            "取消報修需要報修單號與聯絡電話，以便核對工單。",
            missing,
        )

    if CUST_API_USE_MOCK and not is_mock_customer_identity(
        name="王大明",
        phone=phone,
    ):
        return missing_response(
            "cancel_repair_ticket",
            CUSTOMER_NOT_FOUND_MESSAGE,
            ["contact_phone"],
        )

    payload = {"repairTicketId": ticket_id, "contactPhone": phone}
    data = {
        "ticketId": ticket_id,
        "status": "mock_cancel_requested",
        "message": "模擬取消請求已送出，正式 API 接上後才會異動真實工單。",
    }
    raw = mock_api_response("cancelRepair", payload, data)

    return api_success_response(
        "cancel_repair_ticket",
        (
            "已用模擬取消報修 API 送出測試請求：\n"
            f"報修單號：{ticket_id}\n"
            "狀態：模擬取消請求已建立，尚未異動真實工單。\n"
            f"模擬 endpoint：{CANCEL_REPAIR_URL}"
        ),
        raw,
    )


FUNCTION_REGISTRY = {
    "search_bill": exec_search_bill,
    "send_message": exec_send_message,
    "payment_bill_batch": exec_payment_bill_batch,
    "bill_return_line_internet": exec_bill_return_line_internet,
    "bill_return_line_tv": exec_bill_return_line_tv,
    "create_repair_ticket": exec_create_repair_ticket,
    "search_contract_info": exec_search_contract_info,
    "search_channel_no": exec_search_channel_no,
    "search_service_availability": exec_search_service_availability,
    "apply_new_install": exec_apply_new_install,
    "search_addon_plans": exec_search_addon_plans,
    "cancel_repair_ticket": exec_cancel_repair_ticket,
}


def build_search_bill_schema(memory: Dict[str, Any]) -> Dict[str, Any]:
    known = memory.get("known_info", {})

    if has_authenticated_web_custnum(memory):
        return {
            "name": "search_bill",
            "description": "查詢未繳或需繳費的帳單",
            "parameters": {
                "type": "object",
                "properties": {
                    "custnum": {
                        "type": "string",
                        "description": "客戶編號",
                    },
                },
                "required": ["custnum"],
            },
        }

    return {
        "name": "search_bill",
        "description": "查詢未繳或需繳費的帳單；訪客須提供客戶編號、戶名、登記電話任兩項",
        "parameters": build_guest_identity_pair_parameters(),
    }


def build_guest_identity_pair_parameters() -> Dict[str, Any]:
    return {
        "type": "object",
        "properties": {
            "custnum": {"type": "string", "description": "客戶編號"},
            "name": {"type": "string", "description": "戶名"},
            "phone": {"type": "string", "description": "登記電話"},
        },
        "anyOf": [
            {"required": ["custnum", "name"]},
            {"required": ["custnum", "phone"]},
            {"required": ["name", "phone"]},
        ],
    }


def build_contract_info_schema(memory: Dict[str, Any]) -> Dict[str, Any]:
    known = memory.get("known_info", {})

    if has_authenticated_web_custnum(memory):
        return {
            "name": "search_contract_info",
            "description": "查詢目前服務內容、合約到期日、加值服務到期日與申辦網速",
            "parameters": {
                "type": "object",
                "properties": {
                    "custnum": {
                        "type": "string",
                        "description": "客戶編號",
                    },
                },
                "required": ["custnum"],
            },
        }

    return {
        "name": "search_contract_info",
        "description": "查詢目前服務內容、合約到期日、加值服務到期日與申辦網速",
        "parameters": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "戶名"},
                "phone": {"type": "string", "description": "電話"},
            },
            "required": ["name", "phone"],
        },
    }


def build_identity_tool_schema(
    memory: Dict[str, Any],
    name: str,
    description: str,
) -> Dict[str, Any]:
    known = memory.get("known_info", {})

    if has_authenticated_web_custnum(memory):
        return {
            "name": name,
            "description": description,
            "parameters": {
                "type": "object",
                "properties": {
                    "custnum": {
                        "type": "string",
                        "description": "客戶編號",
                    },
                },
                "required": ["custnum"],
            },
        }

    return {
        "name": name,
        "description": f"{description}；訪客須提供客戶編號、戶名、登記電話任兩項",
        "parameters": build_guest_identity_pair_parameters(),
    }


def build_send_message_schema(memory: Dict[str, Any]) -> Dict[str, Any]:
    if has_authenticated_web_custnum(memory):
        return {
            "name": "send_message",
            "description": "發送新的簡訊帳單、補寄繳費帳單或補發繳費單",
            "parameters": {
                "type": "object",
                "properties": {
                    "custnum": {"type": "string", "description": "客戶編號"},
                    "phone": {
                        "type": "string",
                        "description": "登記電話",
                    },
                },
                "required": ["custnum", "phone"],
            },
        }

    return {
        "name": "send_message",
        "description": "發送新的簡訊帳單、補寄繳費帳單或補發繳費單",
        "parameters": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "戶名"},
                "phone": {"type": "string", "description": "登記電話"},
            },
            "required": ["name", "phone"],
        },
    }


def get_available_functions(memory: Dict[str, Any]) -> List[Dict[str, Any]]:
    return [
        build_search_bill_schema(memory),
        build_contract_info_schema(memory),
        build_send_message_schema(memory),
        {
            "name": "payment_bill_batch",
            "description": "僅使用後端已驗證的超商繳費收據圖片 OCR 證據確認繳費並進行復線；不可向使用者收集或接受手動輸入條碼",
            "parameters": {
                "type": "object",
                "properties": {},
                "additionalProperties": False,
            },
        },
        build_identity_tool_schema(
            memory,
            "bill_return_line_internet",
            "超商已繳費、網路開通、欠斷補繳後需要恢復網路",
        ),
        build_identity_tool_schema(
            memory,
            "bill_return_line_tv",
            "超商已繳費、電視開通、欠斷補繳後恢復電視，或電視授權到期",
        ),
        {
            "name": "create_repair_ticket",
            "description": "建立報修工單，適用於排錯失敗、用戶不會排錯、用戶要求派人、電視不能看、網路不能用、設備故障等技術報修情境",
            "parameters": {
                "type": "object",
                "properties": {
                    "contact_name": {"type": "string"},
                    "contact_phone": {"type": "string"},
                    "service_address": {"type": "string"},
                    "issue_description": {"type": "string"},
                    "preferred_date": {"type": "string"},
                    "preferred_time_range": {"type": "string"},
                },
                "required": [
                    "contact_name",
                    "contact_phone",
                    "service_address",
                    "issue_description",
                    "preferred_date",
                    "preferred_time_range",
                ],
            },
        },
        {
            "name": "search_channel_no",
            "description": "模擬依頻道名稱查詢頻道號",
            "parameters": {
                "type": "object",
                "properties": {
                    "channel_name": {"type": "string", "description": "頻道名稱"},
                },
                "required": ["channel_name"],
            },
        },
        {
            "name": "cancel_repair_ticket",
            "description": "模擬取消報修或取消派工，需要報修單號與聯絡電話",
            "parameters": {
                "type": "object",
                "properties": {
                    "repair_ticket_id": {"type": "string"},
                    "contact_phone": {"type": "string"},
                },
                "required": ["repair_ticket_id", "contact_phone"],
            },
        },
    ]


def map_memory_to_tool_args(memory: Dict[str, Any]) -> Dict[str, Any]:
    known = memory.get("known_info", {})

    return {
        "name": known.get("name"),
        "phone": known.get("phone"),
        "custnum": known.get("custnum"),
        "contact_name": known.get("contact_name"),
        "contact_phone": known.get("contact_phone"),
        "service_address": known.get("service_address"),
        "issue_description": known.get("issue_description"),
        "preferred_date": known.get("preferred_date"),
        "preferred_time_range": known.get("preferred_time_range"),
        "service_area": known.get("service_area"),
        "channel_name": known.get("channel_name"),
        "addon_name": known.get("addon_name"),
        "install_service": known.get("install_service"),
        "desired_plan": known.get("desired_plan"),
        "repair_ticket_id": known.get("repair_ticket_id"),
        "bills": known.get("bills"),
        "first_barcode": known.get("first_barcode"),
        "second_barcode": known.get("second_barcode"),
        "third_barcode": known.get("third_barcode"),
    }


def call_tool(tool_name: str, memory: Dict[str, Any]) -> Dict[str, Any]:
    if tool_name in DISABLED_TOOL_NAMES:
        return {
            "success": False,
            "tool_name": tool_name,
            "message": CUSTOMER_TOOL_FLOW_DISABLED_MESSAGE,
            "data": {
                "missing": [],
                "disabled": True,
            },
        }

    fn = FUNCTION_REGISTRY.get(tool_name)

    if not fn:
        return {
            "success": False,
            "tool_name": tool_name,
            "message": f"找不到工具 {tool_name}",
            "data": {"missing": []},
        }

    args = map_memory_to_tool_args(memory)

    # Contract and current-plan data is available only when the external WEB
    # request supplied a customer number from an authenticated member session.
    # LINE and guest WEB sessions must never fall back to name/phone lookup.
    if tool_name == "search_contract_info" and not has_authenticated_web_custnum(memory):
        return {
            "success": False,
            "tool_name": tool_name,
            "message": CONTRACT_LOOKUP_LOGIN_REQUIRED_REPLY,
            "data": {"missing": [], "access_denied": True},
        }

    # Contract queries and SMS-bill delivery still require an authenticated Web
    # customer number. The three guest two-of-three tools are handled below.
    if tool_name in CUSTNUM_GUARDED_TOOL_NAMES and not has_authenticated_web_custnum(memory):
        args["custnum"] = None

    if tool_name == "search_bill":
        return fn(
            name=args.get("name"),
            phone=args.get("phone"),
            custnum=args.get("custnum"),
            authenticated_custnum=has_authenticated_web_custnum(memory),
        )

    if tool_name == "send_message":
        if args.get("custnum"):
            missing = [k for k in ["phone"] if not args.get(k)]
            if missing:
                return missing_response(
                    tool_name,
                    SEND_MESSAGE_CUSTNUM_PHONE_REQUIRED_MESSAGE,
                    missing,
                )
            return fn(custnum=args.get("custnum"), phone=args.get("phone"))

        missing = [k for k in ["name", "phone"] if not args.get(k)]
        if missing:
            return missing_response(
                tool_name,
                "補發簡訊帳單需要戶名與登記電話；簡訊帳單無法改寄或指定其他電話。",
                missing,
            )

        return fn(
            name=args.get("name"),
            phone=args.get("phone"),
            custnum=args.get("custnum"),
        )

    if tool_name in [
        "bill_return_line_internet",
        "bill_return_line_tv",
    ]:
        return fn(
            name=args.get("name"),
            phone=args.get("phone"),
            custnum=args.get("custnum"),
            authenticated_custnum=has_authenticated_web_custnum(memory),
        )

    if tool_name == "payment_bill_batch":
        evidence = (memory.get("known_info") or {}).get("active_receipt_image_evidence")
        if not isinstance(evidence, dict) or not evidence.get("verified"):
            return missing_response(
                tool_name,
                RECEIPT_IMAGE_REUPLOAD_REPLY,
                ["receipt_image_evidence"],
            )
        return fn(receipt_image_evidence=evidence)

    if tool_name == "search_contract_info":
        return fn(custnum=args.get("custnum"))

    if tool_name == "search_channel_no":
        missing = [k for k in ["channel_name"] if not args.get(k)]
        if missing:
            return missing_response(
                tool_name,
                "查詢頻道號需要頻道名稱。",
                missing,
            )
        return fn(
            service_area=args.get("service_area"),
            channel_name=args.get("channel_name"),
        )

    if tool_name == "search_service_availability":
        missing = [k for k in ["service_address"] if not args.get(k)]
        if missing:
            return missing_response(
                tool_name,
                "查詢地址是否可申辦需要服務地址或鄉鎮市區。",
                missing,
            )
        return fn(
            service_address=args.get("service_address"),
            install_service=args.get("install_service"),
        )

    if tool_name == "apply_new_install":
        required = [
            "contact_name",
            "contact_phone",
            "service_address",
            "install_service",
        ]
        missing = [k for k in required if not args.get(k)]
        if missing:
            return missing_response(
                tool_name,
                "申請裝機需要補齊資料。",
                missing,
            )
        return fn(
            contact_name=args.get("contact_name"),
            contact_phone=args.get("contact_phone"),
            service_address=args.get("service_address"),
            install_service=args.get("install_service"),
            desired_plan=args.get("desired_plan"),
        )

    if tool_name == "search_addon_plans":
        missing = [k for k in ["service_area", "addon_name"] if not args.get(k)]
        if missing:
            return missing_response(
                tool_name,
                "查詢加值方案需要服務地區與加值服務名稱。",
                missing,
            )
        return fn(
            service_area=args.get("service_area"),
            addon_name=args.get("addon_name"),
        )

    if tool_name == "cancel_repair_ticket":
        missing = [k for k in ["repair_ticket_id", "contact_phone"] if not args.get(k)]
        if missing:
            return missing_response(
                tool_name,
                "取消報修需要報修單號與聯絡電話。",
                missing,
            )
        return fn(
            repair_ticket_id=args.get("repair_ticket_id"),
            contact_phone=args.get("contact_phone"),
        )

    if tool_name == "create_repair_ticket":
        required = [
            "contact_name",
            "contact_phone",
            "service_address",
            "issue_description",
            "preferred_date",
            "preferred_time_range",
        ]

        missing = [k for k in required if not args.get(k)]
        if missing:
            return missing_response(
                tool_name,
                "建立報修工單需要補齊資料。",
                missing,
            )

        return fn(
            contact_name=args.get("contact_name"),
            contact_phone=args.get("contact_phone"),
            service_address=args.get("service_address"),
            issue_description=args.get("issue_description"),
            preferred_date=args.get("preferred_date"),
            preferred_time_range=args.get("preferred_time_range"),
        )

    return {
        "success": False,
        "tool_name": tool_name,
        "message": "工具未正確配置",
        "data": {"missing": []},
    }
