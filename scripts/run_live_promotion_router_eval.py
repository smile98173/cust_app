from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any


ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run a small live OpenAI evaluation for promotion routing."
    )
    parser.add_argument(
        "--env-file",
        required=True,
        help="External environment file used by the application.",
    )
    return parser.parse_args()


def matches_expected(result: dict[str, Any], expected: dict[str, Any]) -> bool:
    return all(result.get(key) == value for key, value in expected.items())


def main() -> int:
    args = parse_args()
    env_path = Path(args.env_file).expanduser().resolve()
    if not env_path.is_file():
        print(f"Environment file does not exist: {env_path}", file=sys.stderr)
        return 2

    # settings.py reads this value during import, so select the environment first.
    os.environ["CUST_APP_ENV_FILE"] = str(env_path)

    from app.config.settings import OPENAI_API_KEY, OPENAI_MODEL
    from app.services.intent_router import run_intent_router
    from app.services.model_manager import (
        ModelManager,
        finish_llm_trace,
        start_llm_trace,
    )

    if not OPENAI_API_KEY:
        print("OPENAI_API_KEY is not configured in the selected environment.", file=sys.stderr)
        return 2

    cases = [
        {
            "name": "broad promotion clarification",
            "message": "現在有什麼優惠方案嗎？",
            "expected": {
                "route": "clarify",
                "promotion_scope": "unspecified",
                "promotion_query_kind": "scope_clarification",
                "social_discount_requested": False,
            },
        },
        {
            "name": "pure network installation",
            "message": "網路裝機申請",
            "expected": {
                "route": "knowledge_query",
                "promotion_scope": "pure_network",
                "promotion_query_kind": "catalog",
                "social_discount_requested": False,
            },
        },
        {
            "name": "TV and network installation",
            "message": "有線電視加網路裝機申請",
            "expected": {
                "route": "knowledge_query",
                "promotion_scope": "tv_network",
                "promotion_query_kind": "catalog",
                "social_discount_requested": False,
            },
        },
        {
            "name": "cable TV installation",
            "message": "我只想申請有線電視裝機，有哪些方案？",
            "expected": {
                "route": "knowledge_query",
                "promotion_scope": "pure_tv",
                "promotion_query_kind": "catalog",
                "social_discount_requested": False,
            },
        },
        {
            "name": "explicit social discount",
            "message": "我是中低收入戶，想了解純網路優惠方案",
            "expected": {
                "route": "knowledge_query",
                "promotion_scope": "pure_network",
                "promotion_query_kind": "catalog",
                "social_discount_requested": True,
            },
        },
    ]

    manager = ModelManager(
        provider="openai",
        fallback_provider="openai",
        enable_fallback=False,
    )
    llm = manager.get_llm()
    failures = 0
    rows: list[dict[str, Any]] = []

    for case in cases:
        trace_token = start_llm_trace()
        try:
            result = run_intent_router(
                user_input=case["message"],
                memory={"company_code": "tdtv", "known_info": {}},
                history=[],
                llm=llm,
            )
        finally:
            events = finish_llm_trace(trace_token)

        passed = matches_expected(result, case["expected"])
        openai_only = bool(events) and all(
            event.get("provider") == "openai"
            and event.get("success") is True
            and event.get("fallback") is False
            for event in events
        )
        passed = passed and openai_only
        failures += int(not passed)
        rows.append({
            "name": case["name"],
            "message": case["message"],
            "passed": passed,
            "actual": {
                key: result.get(key)
                for key in case["expected"]
            },
            "expected": case["expected"],
            "llm": [
                {
                    "provider": event.get("provider"),
                    "model": event.get("model"),
                    "success": event.get("success"),
                    "fallback": event.get("fallback"),
                    "duration_sec": event.get("duration_sec"),
                }
                for event in events
            ],
        })

    print(json.dumps({
        "model": OPENAI_MODEL,
        "passed": len(cases) - failures,
        "failed": failures,
        "cases": rows,
    }, ensure_ascii=False, indent=2))
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
