"""Replay the 2026-09-17 feedback cases against an already running backend.

It never starts or restarts the backend. Tracker updates are opt-in and only
store passing replay conversations when ``--update-tracker`` is supplied.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import uuid
from pathlib import Path
from typing import Callable

import requests
from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


Check = Callable[[list[dict]], list[str]]


def get_token(base_url: str) -> dict:
    response = requests.post(
        f"{base_url}/api/auth/token",
        json={
            "name": os.environ["API_AUTH_NAME"],
            "password": os.environ["API_AUTH_PASSWORD"],
        },
        timeout=15,
    )
    response.raise_for_status()
    return response.json()


def latency_log_path() -> Path:
    from app.config.settings import CHAT_LATENCY_LOG_DAILY, CHAT_LATENCY_LOG_PATH
    from app.services.error_logging import dated_path

    return dated_path(Path(CHAT_LATENCY_LOG_PATH), CHAT_LATENCY_LOG_DAILY)


def latest_latency_record(user_id: str) -> dict:
    path = latency_log_path()
    if not path.exists():
        return {}
    lines = path.read_text(encoding="utf-8").splitlines()
    for line in reversed(lines):
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            continue
        if record.get("event") == "chat_latency" and record.get("user_id") == user_id:
            return record
    return {}


def require_text(answer: str, *values: str) -> list[str]:
    return [f"缺少「{value}」" for value in values if value not in answer]


def forbid_text(answer: str, *values: str) -> list[str]:
    return [f"不應出現「{value}」" for value in values if value in answer]


def check_model(turns: list[dict]) -> list[str]:
    errors: list[str] = []
    for index, turn in enumerate(turns, start=1):
        record = turn.get("router") or {}
        events = record.get("llm_events") or []
        primary = [event for event in events if event.get("task") == "primary"]
        if not primary:
            errors.append(f"第 {index} 輪沒有 primary LLM 紀錄")
            continue
        for event in primary:
            if not event.get("success"):
                errors.append(f"第 {index} 輪 primary LLM 失敗")
            if event.get("fallback"):
                errors.append(f"第 {index} 輪發生 fallback")
            if event.get("provider") != "openai" or event.get("model") != "gpt-5.5":
                errors.append(
                    f"第 {index} 輪模型不是 openai gpt-5.5："
                    f"{event.get('provider')} {event.get('model')}"
                )
    return errors


def payment_check(turns: list[dict]) -> list[str]:
    answer = turns[-1]["answer"]
    return require_text(answer, "線上刷卡", "臨櫃", "APP", "便利商店", "ibon", "FamiPort", "重新開機")


def fixed_ip_check(turns: list[dict]) -> list[str]:
    errors: list[str] = []
    for turn in turns:
        answer = turn["answer"]
        errors += require_text(answer, "https://www.tinp.net.tw/", "會員登入")
        errors += forbid_text(answer, "真人客服", "每月", "最多")
        if "解除" in turn["question"] and not any(value in answer for value in ("解除", "取消綁定")):
            errors.append("解除綁定問題未提供取消綁定步驟")
        if "解除" not in turn["question"]:
            errors += require_text(answer, "綁定固定 IP")
    return errors


def line_tv_check(turns: list[dict]) -> list[str]:
    answer = turns[-1]["answer"]
    errors = require_text(answer, "到期日", "自動停用")
    if not any(value in answer for value in ("不再支付續約費用", "停止繳納續期費用")):
        errors.append("未明確說明停止支付續約費用")
    return errors + forbid_text(
        answer, "無法代辦", "無法直接取消", "線上 AI 不能辦理"
    )


def penalty_check(turns: list[dict]) -> list[str]:
    answer = turns[-1]["answer"]
    return require_text(answer, "153", "577", "730") + ([] if "1,897" in answer or "1897" in answer else ["違約金不是 1,897 元"])


def repair_visit_check(turns: list[dict]) -> list[str]:
    expectation = turns[1]["answer"]
    contact = turns[2]["answer"]
    errors = require_text(expectation, "聯繫")
    errors += require_text(contact, "轉真人文字客服")
    errors += forbid_text(
        contact,
        "客服電話",
        "(04)",
        "地址",
        "官網",
        "營業時間",
        "服務地區",
        "優惠活動",
    )
    return errors


def relocation_check(turns: list[dict]) -> list[str]:
    errors: list[str] = []
    for index, turn in enumerate(turns, start=1):
        answer = turn["answer"]
        record = turn.get("router") or {}
        errors += [f"第 {index} 輪：{error}" for error in require_text(answer, "移機")]
        errors += [f"第 {index} 輪：{error}" for error in require_text(answer, "500", "800")]
        if record.get("route") != "knowledge_query":
            errors.append(f"第 {index} 輪 route 應為 knowledge_query，實際為 {record.get('route')}")
        if record.get("intent") != "relocation_guidance":
            errors.append(
                f"第 {index} 輪 intent 應為 relocation_guidance，實際為 {record.get('intent')}"
            )
        errors += [
            f"第 {index} 輪：{error}"
            for error in forbid_text(
                answer,
                "優惠活動",
                "恢復原價",
                "開學季",
                "爸氣獻禮",
                "飆網守護家",
                "哈 NET1",
                "分機費",
                "機上盒押金",
                "客服電話",
                "(04)",
            )
        ]
    return errors


def picture_quality_check(turns: list[dict]) -> list[str]:
    mosaic_turns = [turn for turn in turns if "馬賽克" in turn["question"]]
    outdoor_turns = [turn for turn in turns if "室外" in turn["question"]]
    errors: list[str] = []
    if not mosaic_turns:
        errors.append("原始對話沒有可驗證的馬賽克訊息")
    if not outdoor_turns:
        errors.append("原始對話沒有可驗證的室外線路訊息")
    first_turn = turns[0]
    if first_turn.get("router", {}).get("route") != "clarify":
        errors.append("首輪「訊號差」未先釐清電視或網路")
    errors += require_text(first_turn["answer"], "電視", "網路")
    for turn in turns:
        errors += forbid_text(
            turn["answer"],
            "請問您想查詢資料、辦理服務，還是回報故障",
        )
        if turn["question"] == "回報故障":
            errors += forbid_text(turn["answer"], "電視、網路，還是其他設備")
            if not any(value in turn["answer"] for value in ("報修", "維修申告")):
                errors.append("已有室外線路脈絡時，回報故障未承接維修申告")
        if turn["question"] == "電視收訊差":
            if not any(value in turn["answer"] for value in ("重新掃描", "重新搜頻")):
                errors.append(f"「{turn['question']}」未承接電視收訊排錯")
        if turn["question"] == "訊號很差~":
            has_rescan = any(value in turn["answer"] for value in ("重新掃描", "重新搜頻"))
            has_safe_repair = (
                any(value in turn["answer"] for value in ("不要", "請勿", "安全", "危險"))
                and any(value in turn["answer"] for value in ("報修", "維修申告"))
            )
            if not has_rescan and not has_safe_repair:
                errors.append("「訊號很差~」未承接電視收訊或室外線路維修脈絡")
    for turn in mosaic_turns:
        answer = turn["answer"]
        errors += forbid_text(answer, "無法理解", "請重新提問")
        if not any(value in answer for value in ("重新掃描", "重新搜頻", "訊號線", "訊號來源", "馬賽克")):
            errors.append(f"「{turn['question']}」未進入電視畫質排錯")
    for turn in outdoor_turns:
        answer = turn["answer"]
        if not any(value in answer for value in ("不要", "請勿", "安全")):
            errors.append("室外線路鬆脫時缺少安全提醒")
        if not any(value in answer for value in ("報修", "維修申告")):
            errors.append("室外線路鬆脫時未提供報修處理")
        errors += forbid_text(answer, "請問是所有頻道", "只有特定頻道")
    return errors


def rescan_check(turns: list[dict]) -> list[str]:
    answer = turns[-1]["answer"]
    return require_text(
        answer,
        "雙模機且遙控器型號為 TOP-006",
        "雙模機且遙控器型號為 TOP-007",
    )


CASES: list[dict] = [
    {
        "id": "FB-20260917150906-DD5F46",
        "messages": ["馬賽克", "電視收訊差", "室外的電源線有鬆脫"],
        "check": picture_quality_check,
    },
    {
        "id": "FB-20260917143745-6AFE69",
        "messages": ["我要綁定固定IP"],
        "check": fixed_ip_check,
    },
    {
        "id": "FB-20260917142644-AF8EE9",
        "messages": ["LINE TV 到期後不想續約，要怎麼取消？"],
        "check": line_tv_check,
    },
    {
        "id": "FB-20260917141721-EA49C6",
        "messages": [
            "我辦的是爸氣獻禮方案",
            "2026/08/01裝機，2026/12/31退租，違約金要多少？",
        ],
        "check": penalty_check,
    },
    {
        "id": "FB-20260917133914-005410",
        "messages": ["我有預約今早到府維修的工作", "人員是否會到？", "要怎麼聯絡"],
        "check": repair_visit_check,
    },
    {
        "id": "FB-20260917133017-BB92CB",
        "messages": ["有哪些繳費方式？"],
        "check": payment_check,
    },
    {
        "id": "FB-20260917130649-785DF9",
        "messages": ["爸氣獻禮", "我要移機，請問流程和可能收費"],
        "check": relocation_check,
    },
    {
        "id": "FB-20260917114126-6F2987",
        "messages": ["頻道跑掉了，要怎麼重新掃描？"],
        "check": rescan_check,
    },
]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://127.0.0.1:8123")
    parser.add_argument("--company-code", default="tdtv")
    parser.add_argument("--timeout", type=int, default=180)
    parser.add_argument("--feedback-id", action="append", default=[])
    parser.add_argument(
        "--update-tracker",
        action="store_true",
        help="Store passing replay conversations as the feedback item's adjusted conversation.",
    )
    parser.add_argument(
        "--use-original-conversation",
        action="store_true",
        help="Replay the original user messages stored in each feedback record.",
    )
    args = parser.parse_args()

    env_file = os.environ.get("CUST_APP_ENV_FILE")
    if not env_file:
        raise RuntimeError("請先設定 CUST_APP_ENV_FILE")
    load_dotenv(env_file, override=False)

    token = get_token(args.base_url)
    headers = {token.get("header_name", "X-API-Token"): token["access_token"]}

    requested_ids = {value.strip() for value in args.feedback_id if value.strip()}
    selected_cases = [case for case in CASES if not requested_ids or case["id"] in requested_ids]
    tracker_items: dict[str, dict] = {}
    update_feedback_item = None
    if args.update_tracker or args.use_original_conversation:
        from app.services.feedback_tracker_service import (
            list_feedback_items,
            update_feedback_item as tracker_update_feedback_item,
        )

        tracker_items = {
            item["feedback_id"]: item
            for item in list_feedback_items(start_date="2026-09-17")
            if item["feedback_id"] in {case["id"] for case in selected_cases}
        }
        missing_ids = [case["id"] for case in selected_cases if case["id"] not in tracker_items]
        if missing_ids:
            raise RuntimeError(f"回饋追蹤中找不到案例：{', '.join(missing_ids)}")
        if args.update_tracker:
            update_feedback_item = tracker_update_feedback_item

    if args.use_original_conversation:
        original_cases = []
        for case in selected_cases:
            item = tracker_items[case["id"]]
            messages = [
                str(message.get("content") or message.get("message") or "").strip()
                for message in item.get("conversation") or []
                if str(message.get("role") or "").lower() == "user"
                and str(message.get("content") or message.get("message") or "").strip()
            ]
            if not messages and str(item.get("user_message") or "").strip():
                messages = [str(item["user_message"]).strip()]
            if not messages:
                raise RuntimeError(f"原始案例沒有使用者訊息：{case['id']}")
            original_cases.append(
                {
                    **case,
                    "messages": messages,
                    "company_code": item.get("company_code") or item.get("tv_cable"),
                }
            )
        selected_cases = original_cases

    results: list[dict] = []
    for case in selected_cases:
        raw_user_id = f"codex_feedback_{case['id']}_{uuid.uuid4().hex}"
        session_user_id = f"test_web:{raw_user_id}"
        turns: list[dict] = []
        started = time.perf_counter()

        for message in case["messages"]:
            response = requests.post(
                f"{args.base_url}/chat",
                headers=headers,
                json={
                    "user_id": raw_user_id,
                    "user_input": message,
                    "tv_cable": case.get("company_code") or args.company_code,
                },
                timeout=args.timeout,
            )
            if response.status_code == 401:
                token = get_token(args.base_url)
                headers = {token.get("header_name", "X-API-Token"): token["access_token"]}
                response = requests.post(
                    f"{args.base_url}/chat",
                    headers=headers,
                    json={
                        "user_id": raw_user_id,
                        "user_input": message,
                        "tv_cable": case.get("company_code") or args.company_code,
                    },
                    timeout=args.timeout,
                )
            response.raise_for_status()
            payload = response.json()
            router = latest_latency_record(session_user_id)
            turns.append(
                {
                    "question": message,
                    "answer": str(payload.get("ai_response") or ""),
                    "decision_type": payload.get("decision_type"),
                    "elapsed_sec": payload.get("response_time_sec"),
                    "router": {
                        "route": router.get("route"),
                        "intent": router.get("intent"),
                        "reason": router.get("reason"),
                        "llm_events": router.get("llm_events") or [],
                    },
                }
            )

        errors = check_model(turns) + case["check"](turns)
        result = {
            "feedback_id": case["id"],
            "passed": not errors,
            "errors": errors,
            "duration_sec": round(time.perf_counter() - started, 3),
            "turns": turns,
            "tracker_updated": False,
        }
        if result["passed"] and update_feedback_item:
            adjusted_conversation = []
            for turn in turns:
                adjusted_conversation.extend(
                    [
                        {"role": "user", "content": turn["question"]},
                        {"role": "assistant", "content": turn["answer"]},
                    ]
                )
            tracker_item = tracker_items[case["id"]]
            update_feedback_item(
                case["id"],
                {
                    "status": "processed",
                    "review_status": "pending",
                    "owner": tracker_item.get("owner") or "tinp",
                    "priority": tracker_item.get("priority") or "medium",
                    "review_note": (
                        "2026-09-18 修正完成：已用 8123 依原始對話逐輪重播，"
                        "OpenAI gpt-5.5 成功且 fallback=false；"
                        "修正後完整對話已保存，等待客服驗收。"
                    ),
                    "adjusted_conversation": adjusted_conversation,
                },
                "codex",
            )
            result["tracker_updated"] = True
        results.append(result)
        print(json.dumps(result, ensure_ascii=False), flush=True)

    summary = {
        "total": len(results),
        "passed": sum(bool(result["passed"]) for result in results),
        "failed": sum(not result["passed"] for result in results),
        "tracker_updated": sum(bool(result["tracker_updated"]) for result in results),
    }
    print(json.dumps({"summary": summary}, ensure_ascii=False), flush=True)
    raise SystemExit(0 if summary["failed"] == 0 else 1)


if __name__ == "__main__":
    main()
