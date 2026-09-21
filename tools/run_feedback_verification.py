"""Replay pending feedback conversations against the local AI-test backend."""

import argparse
import json
import os
import sys
import time
from datetime import date
from pathlib import Path
from queue import Empty, Queue
from threading import Thread

import requests
from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.feedback_tracker_service import list_feedback_items, update_feedback_item
from app.services.model_manager import ModelManager


def json_object(text: str) -> dict:
    cleaned = (text or "").replace("```json", "").replace("```", "").strip()
    start, end = cleaned.find("{"), cleaned.rfind("}")
    if start < 0 or end <= start:
        return {}
    try:
        value = json.loads(cleaned[start : end + 1])
        return value if isinstance(value, dict) else {}
    except json.JSONDecodeError:
        return {}


def invoke_with_timeout(llm, prompt: str, timeout: int) -> str:
    """Keep one stalled quality-evaluation request from blocking the whole batch."""
    result_queue: Queue[object] = Queue(maxsize=1)

    def invoke() -> None:
        try:
            result_queue.put(getattr(llm.invoke(prompt), "content", ""))
        except Exception as error:  # Returned to the batch's normal error handling below.
            result_queue.put(error)

    Thread(target=invoke, daemon=True).start()
    try:
        result = result_queue.get(timeout=timeout)
    except Empty as error:
        raise TimeoutError(f"模型品質判讀逾時（{timeout} 秒）") from error
    if isinstance(result, Exception):
        raise result
    return str(result or "")


def evaluate(llm, suggestion: str, conversation: list[dict], final_reply: str, timeout: int) -> dict:
    prompt = f"""你是客服品質驗證員。依客服建議判斷 AI 最後回答是否符合期待。
只能輸出 JSON：{{\"verdict\": \"pass|fail|manual\", \"reason\": \"不超過60字\"}}。

客服建議：{suggestion}
原始對話：{json.dumps(conversation, ensure_ascii=False)}
本次 AI 最後回答：{final_reply}
"""
    result = json_object(invoke_with_timeout(llm, prompt, timeout))
    if result.get("verdict") not in {"pass", "fail", "manual"}:
        return {"verdict": "manual", "reason": "判讀格式無效"}
    return result


def get_token(base_url: str) -> dict:
    response = requests.post(
        f"{base_url}/api/auth/token",
        json={"name": os.environ["API_AUTH_NAME"], "password": os.environ["API_AUTH_PASSWORD"]},
        timeout=15,
    )
    response.raise_for_status()
    return response.json()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://127.0.0.1:8124")
    parser.add_argument("--limit", type=int)
    parser.add_argument(
        "--status",
        default="pending",
        choices=("pending", "processed"),
        help="Feedback processing status to replay. Use processed for pending acceptance items.",
    )
    parser.add_argument(
        "--chat-timeout",
        type=int,
        default=90,
        help="Seconds to wait for one replayed chat turn before recording an error and continuing.",
    )
    parser.add_argument(
        "--evaluation-timeout",
        type=int,
        default=90,
        help="Seconds to wait for one model quality evaluation before recording an error and continuing.",
    )
    parser.add_argument(
        "--feedback-id",
        action="append",
        default=[],
        help="Only verify these feedback IDs. May be supplied more than once or comma-separated.",
    )
    parser.add_argument(
        "--exclude-feedback-id",
        action="append",
        default=[],
        help="Skip these feedback IDs. May be supplied more than once or comma-separated.",
    )
    parser.add_argument(
        "--skip-retested-today",
        action="store_true",
        help="Skip items whose review note was written by this verifier today.",
    )
    args = parser.parse_args()

    env_file = os.environ.get("CUST_APP_ENV_FILE")
    if env_file:
        load_dotenv(env_file, override=False)

    items = list_feedback_items(start_date="2026-08-24", status=args.status, review_status="pending")
    requested_feedback_ids = {
        feedback_id.strip()
        for value in args.feedback_id
        for feedback_id in value.split(",")
        if feedback_id.strip()
    }
    if requested_feedback_ids:
        items = [item for item in items if item["feedback_id"] in requested_feedback_ids]
    excluded_feedback_ids = {
        feedback_id.strip()
        for value in args.exclude_feedback_id
        for feedback_id in value.split(",")
        if feedback_id.strip()
    }
    if excluded_feedback_ids:
        items = [item for item in items if item["feedback_id"] not in excluded_feedback_ids]
    if args.skip_retested_today:
        today_prefix = f"{date.today().isoformat()} 重新測試："
        items = [
            item
            for item in items
            if not str(item.get("review_note") or "").startswith(today_prefix)
        ]
    if args.limit:
        items = items[: args.limit]

    token = get_token(args.base_url)
    headers = {token.get("header_name", "X-API-Token"): token["access_token"]}

    def authenticated_post(path: str, **kwargs):
        nonlocal headers
        response = requests.post(f"{args.base_url}{path}", headers=headers, **kwargs)
        if response.status_code == 401:
            token = get_token(args.base_url)
            headers = {token.get("header_name", "X-API-Token"): token["access_token"]}
            response = requests.post(f"{args.base_url}{path}", headers=headers, **kwargs)
        return response
    llm = ModelManager().get_llm()
    summary = {"pass": 0, "fail": 0, "manual": 0, "error": 0}

    for index, item in enumerate(items, start=1):
        feedback_id = item["feedback_id"]
        conversation = item.get("conversation") or []
        replay_messages = [
            str(message.get("content") or message.get("message") or "").strip()
            for message in conversation
            if str(message.get("role") or "").lower() == "user"
            and str(message.get("content") or message.get("message") or "").strip()
        ]
        if not replay_messages:
            replay_messages = [str(item.get("user_message") or "").strip()]
        replay_messages = [message for message in replay_messages if message]
        if not replay_messages:
            raise ValueError("案例沒有可回放的使用者訊息")
        user_id = f"batch-verify-{feedback_id}"
        # /chat namespaces this internal endpoint as test_web:<user_id>.
        # Reset the same key before a recheck so a prior run cannot leak its
        # conversation context into the current feedback case.
        session_user_id = f"test_web:{user_id}"
        try:
            authenticated_post(f"/reset/{session_user_id}", timeout=15).raise_for_status()
            final_reply = ""
            for message in replay_messages:
                response = authenticated_post(
                    "/api/v1/chat",
                    json={
                        "user_id": user_id,
                        "msg": message,
                        "tv_cable": item.get("company_code") or "tdtv",
                        "channel": "test_web",
                    },
                    timeout=args.chat_timeout,
                )
                response.raise_for_status()
                final_reply = str(response.json().get("msg") or "")
            verdict = evaluate(
                llm,
                str(item.get("suggestion") or ""),
                item.get("conversation") or [],
                final_reply,
                args.evaluation_timeout,
            )
            matches_feedback = verdict["verdict"] == "pass"
            update_feedback_item(
                feedback_id,
                {
                    "status": "processed" if matches_feedback else "pending",
                    "owner": "tinp",
                    "review_status": "pending",
                    "review_note": (
                        f"{date.today().isoformat()} 重新測試："
                        f"{'調整後回答已符合客服回饋，等待驗收' if matches_feedback else '調整後回答仍需調整'}；"
                        f"原因：{verdict.get('reason', '')}；"
                        f"調整後回答：{final_reply[:300]}"
                    ),
                },
                "codex",
            )
            summary[verdict["verdict"]] += 1
        except Exception as error:
            summary["error"] += 1
            update_feedback_item(
                feedback_id,
                {
                    "status": "pending",
                    "owner": "tinp",
                    "review_status": "pending",
                    "review_note": f"{date.today().isoformat()} 重新測試失敗：{error}",
                },
                "codex",
            )
        print(json.dumps({"index": index, "total": len(items), "feedback_id": feedback_id, "summary": summary}, ensure_ascii=False), flush=True)

    print(json.dumps({"complete": True, "summary": summary}, ensure_ascii=False))


if __name__ == "__main__":
    main()
