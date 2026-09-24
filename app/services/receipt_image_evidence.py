import base64
import hashlib
import hmac
import json
import secrets
import time
from typing import Any, Dict, Optional

from app.config.settings import API_AUTH_SECRET, WEB_AUTH_SECRET
from app.services.slot_manager import extract_receipt_barcodes


RECEIPT_EVIDENCE_TTL_SECONDS = 10 * 60
RECEIPT_EVIDENCE_TOKEN_PREFIX = "receiptimg"
RECEIPT_IMAGE_REQUIRED_REPLY = (
    "為保障繳費資料安全，請上傳清楚、完整的超商繳費收據圖片。"
    "圖片需包含超商名稱、繳費完成資訊、代收項目及三段條碼；"
    "我會依圖片辨識結果確認後再處理復線，無法接受手動輸入三段條碼。"
)
RECEIPT_IMAGE_REUPLOAD_REPLY = (
    "目前無法從圖片確認為完整的超商繳費收據。"
    "請重新上傳清楚、完整的收據圖片，需包含超商名稱、繳費完成資訊、"
    "代收項目及三段條碼；無法接受手動輸入三段條碼。"
)
RECEIPT_IMAGE_MESSAGE_PREFIX = "我上傳了一張圖片，辨識內容如下："


def _compact(value: str) -> str:
    return (value or "").replace(" ", "").replace("　", "").lower()


def _base64url_encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")


def _base64url_decode(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + ("=" * (-len(value) % 4)))


def _sign(payload_b64: str) -> str:
    secret = (API_AUTH_SECRET or WEB_AUTH_SECRET).encode("utf-8")
    return _base64url_encode(
        hmac.new(secret, payload_b64.encode("ascii"), hashlib.sha256).digest()
    )


def _ocr_text_from_chat_message(user_text: str) -> Optional[str]:
    text = str(user_text or "").strip()
    if not text.startswith(RECEIPT_IMAGE_MESSAGE_PREFIX):
        return None
    value = text[len(RECEIPT_IMAGE_MESSAGE_PREFIX):].strip()
    return value or None


def _is_receipt_like_ocr_text(ocr_text: str) -> bool:
    value = _compact(ocr_text)
    markers = (
        "收據", "繳費", "代收", "條碼", "7-11", "7eleven", "seveneleven",
        "全家", "familymart", "萊爾富", "hilife", "ok超商", "okmart",
    )
    return any(marker in value for marker in markers)


def is_receipt_image_submission(
    user_text: str,
    memory: Optional[Dict[str, Any]] = None,
) -> bool:
    """Recognize a receipt-like OCR turn even when it is incomplete."""
    ocr_text = _ocr_text_from_chat_message(user_text)
    if ocr_text:
        return _is_receipt_like_ocr_text(ocr_text)

    attempt = ((memory or {}).get("known_info") or {}).get("receipt_image_ocr_attempt") or {}
    return bool(
        isinstance(attempt, dict)
        and attempt.get("source") == "line_image_ocr"
        and attempt.get("receipt_like") is True
        and hmac.compare_digest(
            str(attempt.get("message_hash") or ""),
            hashlib.sha256(str(user_text or "").encode("utf-8")).hexdigest(),
        )
    )


def evaluate_store_receipt_ocr(ocr_text: str) -> Dict[str, Any]:
    """Accept only complete, paid convenience-store receipt OCR evidence."""
    value = str(ocr_text or "").strip()
    compact = _compact(value)
    store_markers = (
        "7-11",
        "7-eleven",
        "7eleven",
        "seveneleven",
        "全家",
        "familymart",
        "萊爾富",
        "hilife",
        "ok超商",
        "okmart",
    )
    receipt_markers = ("繳費收據", "代收收據", "代收項目", "代收服務", "交易明細")
    paid_markers = ("繳費完成", "交易成功", "繳費成功", "已繳", "收款完成", "繳納成功")
    bills = extract_receipt_barcodes(value).get("bills")
    if not isinstance(bills, list) or not bills:
        single = extract_receipt_barcodes(value)
        if all(single.get(key) for key in ("first_barcode", "second_barcode", "third_barcode")):
            bills = [{
                "first_barcode": single["first_barcode"],
                "second_barcode": single["second_barcode"],
                "third_barcode": single["third_barcode"],
            }]
        else:
            bills = []

    has_store = any(marker in compact for marker in store_markers)
    has_receipt_format = any(marker in compact for marker in receipt_markers)
    has_paid_status = any(marker in compact for marker in paid_markers)
    complete_bills = [
        bill for bill in bills
        if isinstance(bill, dict)
        and all(str(bill.get(key) or "").strip() for key in (
            "first_barcode", "second_barcode", "third_barcode"
        ))
    ]
    verified = bool(
        has_store
        and has_receipt_format
        and has_paid_status
        and complete_bills
        and len(complete_bills) == len(bills)
    )
    return {
        "verified": verified,
        "store_receipt": has_store and has_receipt_format,
        "paid": has_paid_status,
        "complete": bool(complete_bills) and len(complete_bills) == len(bills),
        "bills": complete_bills,
        "ocr_text_hash": hashlib.sha256(value.encode("utf-8")).hexdigest(),
    }


def issue_receipt_image_evidence_token(ocr_text: str, user_id: str) -> Optional[str]:
    evidence = evaluate_store_receipt_ocr(ocr_text)
    if not evidence["verified"] or not str(user_id or "").strip():
        return None

    now = int(time.time())
    payload = {
        "sub": str(user_id).strip(),
        "iat": now,
        "exp": now + RECEIPT_EVIDENCE_TTL_SECONDS,
        "nonce": secrets.token_urlsafe(12),
        "receipt": evidence,
    }
    payload_b64 = _base64url_encode(
        json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    )
    return f"{RECEIPT_EVIDENCE_TOKEN_PREFIX}.{payload_b64}.{_sign(payload_b64)}"


def verify_receipt_image_evidence_token(
    token: str,
    user_id: str,
    user_text: str,
) -> Optional[Dict[str, Any]]:
    try:
        prefix, payload_b64, signature = str(token or "").split(".", 2)
        if prefix != RECEIPT_EVIDENCE_TOKEN_PREFIX:
            return None
        if not hmac.compare_digest(signature, _sign(payload_b64)):
            return None
        payload = json.loads(_base64url_decode(payload_b64).decode("utf-8"))
        if payload.get("sub") != str(user_id or "").strip():
            return None
        if int(payload.get("exp") or 0) < int(time.time()):
            return None
        ocr_text = _ocr_text_from_chat_message(user_text)
        evidence = payload.get("receipt") or {}
        if not ocr_text or not evidence.get("verified"):
            return None
        if not hmac.compare_digest(
            str(evidence.get("ocr_text_hash") or ""),
            hashlib.sha256(ocr_text.encode("utf-8")).hexdigest(),
        ):
            return None
    except Exception:
        return None

    verified = dict(evidence)
    verified["message_hash"] = hashlib.sha256(str(user_text).encode("utf-8")).hexdigest()
    verified["source"] = "verified_image_ocr"
    return verified


def build_line_receipt_image_evidence(ocr_text: str) -> Optional[Dict[str, Any]]:
    evidence = evaluate_store_receipt_ocr(ocr_text)
    if not evidence.get("verified"):
        return None
    verified = dict(evidence)
    verified["message_hash"] = hashlib.sha256(str(ocr_text).encode("utf-8")).hexdigest()
    verified["source"] = "line_image_ocr"
    return verified


def build_line_receipt_image_attempt(ocr_text: str) -> Dict[str, Any]:
    return {
        "source": "line_image_ocr",
        "receipt_like": _is_receipt_like_ocr_text(ocr_text),
        "message_hash": hashlib.sha256(str(ocr_text).encode("utf-8")).hexdigest(),
    }


def current_verified_receipt_image_evidence(
    memory: Dict[str, Any],
    user_text: str,
) -> Optional[Dict[str, Any]]:
    known = (memory or {}).get("known_info") or {}
    evidence = known.get("receipt_image_evidence") or {}
    if not isinstance(evidence, dict) or not evidence.get("verified"):
        return None
    message_hash = hashlib.sha256(str(user_text or "").encode("utf-8")).hexdigest()
    if not hmac.compare_digest(str(evidence.get("message_hash") or ""), message_hash):
        return None
    bills = evidence.get("bills")
    if not isinstance(bills, list) or not bills:
        return None
    if not all(
        isinstance(bill, dict)
        and all(str(bill.get(key) or "").strip() for key in (
            "first_barcode", "second_barcode", "third_barcode"
        ))
        for bill in bills
    ):
        return None
    return evidence


def clear_unverified_receipt_barcode_slots(memory: Dict[str, Any]) -> Dict[str, Any]:
    known = memory.setdefault("known_info", {})
    for key in ("bills", "first_barcode", "second_barcode", "third_barcode"):
        known.pop(key, None)
    return memory
