"""Fill full adjusted conversations for feedback items waiting for acceptance."""

import argparse
import json
import os
import re
import sys
from datetime import date
from pathlib import Path

import requests
from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

if "--env-file" in sys.argv:
    try:
        _env_file = sys.argv[sys.argv.index("--env-file") + 1]
    except IndexError:
        _env_file = ".env.ai-test"
else:
    _env_file = ".env.ai-test"
if _env_file:
    os.environ.setdefault("CUST_APP_ENV_FILE", _env_file)
    load_dotenv(_env_file, override=True)

from app.services.feedback_tracker_service import list_feedback_items, update_feedback_item


def has_adjusted_reply(review_note: str) -> bool:
    return bool(re.search(r"(?:最後回答|調整後回答)[:：]\s*\S", str(review_note or ""), re.S))


def get_token(base_url: str) -> dict:
    response = requests.post(
        f"{base_url}/api/auth/token",
        json={"name": os.environ["API_AUTH_NAME"], "password": os.environ["API_AUTH_PASSWORD"]},
        timeout=15,
    )
    response.raise_for_status()
    return response.json()


def direct_chat(payload: dict, *, reset: bool = False) -> str:
    from app.app_backend import (
        build_web_human_handoff_reply,
        external_chat,
        format_reply_for_external_web,
        is_human_handoff_result,
        memory_from_external_state,
        normalize_channel_user_id,
        normalize_external_history,
        run_core_chat,
    )
    from app.schemas.chat import ExternalChatRequest
    from app.services.memory_service import reset_user_session

    request = ExternalChatRequest(**payload)
    raw_user_id = payload["user_id"]
    user_id = normalize_channel_user_id(request.channel or "web", raw_user_id)
    if reset:
        reset_user_session(user_id)
    memory = memory_from_external_state(request, user_id)
    result = run_core_chat(
        user_id,
        payload["msg"],
        memory,
        persist=True,
        history=normalize_external_history(request) or None,
    )
    if is_human_handoff_result(result):
        return build_web_human_handoff_reply(result["memory"])
    return format_reply_for_external_web(result["ai_response"], result["memory"])


def feedback_user_turns(item: dict) -> list[str]:
    conversation = item.get("conversation") or []
    turns = [
        str(message.get("content") or message.get("message") or "").strip()
        for message in conversation
        if str(message.get("role") or "").lower() == "user"
        and str(message.get("content") or message.get("message") or "").strip()
    ]
    if turns:
        return turns
    fallback = str(item.get("user_message") or "").strip()
    return [fallback] if fallback else []


def replay_payload(item: dict, user_text: str, history: list[dict]) -> dict:
    return {
        "user_id": f"pending-acceptance-{item['feedback_id']}",
        "msg": user_text,
        "tv_cable": item.get("company_code") or "tdtv",
        "channel": "test_web",
        "history": history,
    }


def replay_full_conversation_http(item: dict, authenticated_post, chat_timeout: int) -> list[dict]:
    user_id = f"pending-acceptance-{item['feedback_id']}"
    session_user_id = f"test_web:{user_id}"
    authenticated_post(f"/reset/{session_user_id}", timeout=15).raise_for_status()

    adjusted_conversation: list[dict] = []
    for user_text in feedback_user_turns(item):
        payload = replay_payload(item, user_text, adjusted_conversation)
        response = authenticated_post(
            "/api/v1/chat",
            json=payload,
            timeout=chat_timeout,
        )
        response.raise_for_status()
        adjusted_reply = str(response.json().get("msg") or "").strip()
        if not adjusted_reply:
            raise RuntimeError("重新測試沒有取得 AI 回答")
        adjusted_conversation.extend([
            {"role": "user", "content": user_text},
            {"role": "assistant", "content": adjusted_reply},
        ])
    if not adjusted_conversation:
        raise RuntimeError("原始回饋沒有可重跑的使用者問題")
    return adjusted_conversation


def replay_full_conversation_direct(item: dict) -> list[dict]:
    adjusted_conversation: list[dict] = []
    for index, user_text in enumerate(feedback_user_turns(item)):
        payload = replay_payload(item, user_text, adjusted_conversation)
        adjusted_reply = direct_chat(payload, reset=index == 0).strip()
        if not adjusted_reply:
            raise RuntimeError("重新測試沒有取得 AI 回答")
        adjusted_conversation.extend([
            {"role": "user", "content": user_text},
            {"role": "assistant", "content": adjusted_reply},
        ])
    if not adjusted_conversation:
        raise RuntimeError("原始回饋沒有可重跑的使用者問題")
    return adjusted_conversation


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://127.0.0.1:8123")
    parser.add_argument("--env-file", default=".env.ai-test")
    parser.add_argument("--limit", type=int)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--force", action="store_true", help="Refresh items that already have an adjusted reply.")
    parser.add_argument("--direct", action="store_true", help="Call the local backend logic directly instead of HTTP.")
    parser.add_argument("--chat-timeout", type=int, default=90)
    parser.add_argument("--feedback-id", action="append", default=[])
    args = parser.parse_args()

    if args.env_file:
        os.environ.setdefault("CUST_APP_ENV_FILE", args.env_file)
        load_dotenv(args.env_file, override=True)

    requested_feedback_ids = {
        feedback_id.strip()
        for value in args.feedback_id
        for feedback_id in value.split(",")
        if feedback_id.strip()
    }

    items = list_feedback_items(start_date="2026-08-24", status="processed", review_status="pending")
    if requested_feedback_ids:
        items = [item for item in items if item["feedback_id"] in requested_feedback_ids]
    if not args.force:
        items = [
            item for item in items
            if not item.get("adjusted_conversation")
            and not has_adjusted_reply(str(item.get("review_note") or ""))
        ]
    if args.limit:
        items = items[: args.limit]

    if args.dry_run:
        print(json.dumps({
            "dry_run": True,
            "total": len(items),
            "feedback_ids": [item["feedback_id"] for item in items],
        }, ensure_ascii=False, indent=2))
        return

    headers = {}
    if not args.direct:
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

    summary = {"updated": 0, "error": 0}
    for index, item in enumerate(items, start=1):
        feedback_id = item["feedback_id"]
        try:
            if args.direct:
                adjusted_conversation = replay_full_conversation_direct(item)
            else:
                adjusted_conversation = replay_full_conversation_http(item, authenticated_post, args.chat_timeout)
            update_feedback_item(
                feedback_id,
                {
                    "status": "processed",
                    "priority": item.get("priority") or "",
                    "owner": item.get("owner") or "tinp",
                    "review_status": "pending",
                    "review_note": (
                        f"{date.today().isoformat()} 重新測試："
                        f"已重跑完整對話，共 {len(adjusted_conversation) // 2} 輪，等待驗收。"
                    ),
                    "adjusted_conversation": adjusted_conversation,
                },
                "codex",
            )
            summary["updated"] += 1
        except Exception as error:
            summary["error"] += 1
            update_feedback_item(
                feedback_id,
                {
                    "status": "processed",
                    "priority": item.get("priority") or "",
                    "owner": item.get("owner") or "tinp",
                    "review_status": "pending",
                    "review_note": f"{date.today().isoformat()} 重新測試失敗：{error}",
                },
                "codex",
            )
        print(json.dumps({
            "index": index,
            "total": len(items),
            "feedback_id": feedback_id,
            "summary": summary,
        }, ensure_ascii=False), flush=True)

    print(json.dumps({"complete": True, "summary": summary}, ensure_ascii=False))


if __name__ == "__main__":
    main()
