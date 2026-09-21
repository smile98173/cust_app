from __future__ import annotations

import argparse
import csv
import html
import json
import re
import time
from datetime import datetime
from pathlib import Path
from typing import Any

from run_feedback_html_dialog_tests import (
    esc,
    render_messages,
    render_turn_debug,
    run_case_backend,
)


ROOT_DIR = Path(__file__).resolve().parent.parent
DEFAULT_FEEDBACK_DIR = ROOT_DIR.parent / "cust_app_runtime" / "feedback"
DEFAULT_DATES = ("20", "21", "22", "23", "24", "27")
DEFAULT_OUTPUT_DIR = ROOT_DIR / "reports"


# Each inner tuple is an OR group; every group must be represented in the final reply.
EXPECTATIONS: dict[int, dict[str, Any]] = {
    1: {
        "label": "下期帳單需使用核准後的固定說法",
        "must": (("本期待繳帳單",), ("下期帳單產生後",)),
        "must_not": ("設備電源",),
    },
    2: {
        "label": "延續網路排錯並進入報修／真人協助，不重問服務類別",
        "must": (("網路", "數據機", "連線", "報修", "維修", "真人客服"),),
        "must_not": ("查詢資料、辦理服務，還是回報故障",),
    },
    3: {
        "label": "停用／查無帳戶由帳務 API 狀態決定",
        "review_only": True,
        "note": "此案依賴帳務 API 的帳戶狀態過濾；仍重播對話，但不以文字規則宣告通過。",
    },
    4: {
        "label": "訊號不佳先釐清電視或網路",
        "must": (("電視",), ("網路",)),
    },
    5: {
        "label": "信用卡繳費只回答信用卡管道",
        "must": (("信用卡",), ("官網", "官方網站", "線上繳費"), ("app", "APP")),
        "must_not": ("超商繳費", "臨櫃繳費"),
    },
    6: {
        "label": "新裝後樓層無網路應進入網路排錯",
        "must": (("3樓", "三樓", "樓層"), ("網路", "wi-fi", "Wi-Fi", "網路線")),
        "must_not": ("優惠方案",),
    },
    7: {
        "label": "寬頻是否吃到飽要明確回答",
        "must": (("吃到飽", "不限流量", "不計量"),),
    },
    8: {
        "label": "電視與網路同時無訊號應排錯",
        "must": (("電視",), ("網路",), ("電源", "數據機", "燈號", "報修")),
        "must_not": ("方案名稱",),
    },
    9: {
        "label": "低收入戶 500M 一年費用",
        "must": (("低收入",), ("500m", "500M"), ("6,000", "6000")),
    },
    10: {
        "label": "送家電活動應命中好視成雙 NO8",
        "must": (("好視成雙",), ("no8", "NO8"), ("家電", "電視", "冰箱", "投影機")),
    },
    11: {
        "label": "官網家電活動應命中好視成雙 NO8",
        "must": (("好視成雙",), ("no8", "NO8"), ("家電", "電視", "冰箱", "投影機")),
    },
    12: {
        "label": "三台機上盒半年繳總額與明細",
        "must": (("6,440", "6440"), ("3,240", "3240"), ("1,200", "1200")),
    },
    13: {"label": "佳聯第四台月租", "must": (("540",),)},
    14: {"label": "佳聯有線電視月租", "must": (("540",),)},
    15: {"label": "佳聯有線電視月租", "must": (("540",),)},
    16: {"label": "佳聯有線電視月租", "must": (("540",),)},
    17: {"label": "佳聯有線電視月租", "must": (("540",),)},
    18: {
        "label": "A 套餐頻道清單",
        "must": (("a套餐", "A套餐"), ("頻道",)),
        "must_not": ("資料未提供", "無法查到", "待客服確認"),
    },
    19: {
        "label": "價格抱怨需先同理再協助",
        "must": (("理解", "了解", "抱歉", "確實"), ("協助", "客服")),
    },
    20: {
        "label": "北港電視月費需直接回答價格",
        "must": (("月", "月租"), ("元", "$")),
    },
    21: {
        "label": "更改聯絡電話應引導真人管道",
        "must": (("真人", "客服"),),
    },
    22: {
        "label": "刷卡後尚未入帳",
        "must": (("入帳", "沖帳"), ("作業時間", "不一定會即時", "尚未更新"), ("收據", "交易明細", "客服")),
    },
    23: {
        "label": "延續前文解釋每月 600 元",
        "must": (("600",),),
    },
    24: {
        "label": "依前文方案回答贈品",
        "must": (("贈", "家電", "電視", "冰箱", "投影機", "point"),),
    },
    25: {
        "label": "來源對話未包含「不綁約」，依實際提問驗證贈品內容",
        "must": (("贈", "家電", "電視", "冰箱", "投影機", "point"),),
    },
    26: {
        "label": "同一方案贈品不可混入其他方案",
        "must": (("贈", "家電", "電視", "冰箱", "投影機", "point"),),
        "must_not": ("好視成雙NO7", "好視成雙 NO7"),
    },
    27: {
        "label": "延續方案上下文回答完整活動內容",
        "must": (("方案",), ("月租", "費用", "速率"), ("優惠", "贈品")),
    },
    28: {
        "label": "E004 授權到期排錯",
        "must": (("e004", "E004", "授權到期"), ("繳費", "帳單", "重開機", "電源")),
    },
    29: {
        "label": "哈TV+ 可使用 YouTube",
        "must": (("youtube", "YouTube"), ("可以", "可使用")),
    },
    30: {
        "label": "錯誤身份資料不可誤查帳務",
        "must": (("查無", "不一致", "無效", "停用", "重新確認", "真人客服"),),
    },
    31: {
        "label": "新裝後二樓視訊不穩應排錯",
        "must": (("二樓", "2樓", "樓層"), ("wi-fi", "Wi-Fi", "網路", "訊號")),
        "must_not": ("優惠方案",),
    },
    32: {
        "label": "查詢自家網路費用應走目前服務／合約",
        "must": (("目前", "現有"), ("服務", "合約", "網路費用"),),
        "must_not": ("新裝優惠",),
    },
    33: {
        "label": "本期帳單繳費起訖日屬目前未提供項目",
        "must": (("本期待繳帳單", "目前系統"), ("app", "APP", "官網", "真人客服", "無法查詢")),
    },
    34: {
        "label": "已繳明細／入帳紀錄應導向 APP 或官網",
        "must": (("已繳", "入帳"), ("app", "APP", "官網")),
    },
    35: {
        "label": "西海岸電視費用需直接區分價格",
        "must": (("電視", "第四台", "tv", "TV"), ("月", "月租"), ("元", "$")),
    },
    36: {
        "label": "寬頻斷訊應進入網路排錯",
        "must": (("數據機", "燈號", "網路線", "重開", "報修"),),
        "must_not": ("優惠方案",),
    },
    37: {
        "label": "第四台加網路優惠應優先提供 NO8",
        "must": (("好視成雙",), ("no8", "NO8")),
    },
    38: {
        "label": "西海岸第四台月租",
        "must": (("550",),),
    },
    39: {
        "label": "500M 申辦費用需清楚列出",
        "must": (("500m", "500M"), ("月", "半年", "年"), ("元", "$")),
    },
    40: {
        "label": "一年約詢問需說明主方案綁約期",
        "must": (("一年", "1年"), ("24", "兩年", "2年"), ("客服", "確認", "協助")),
    },
}


def _load_conversation(raw: str) -> list[dict[str, Any]]:
    try:
        value = json.loads(raw or "[]")
    except json.JSONDecodeError:
        return []
    return value if isinstance(value, list) else []


def extract_cases(csv_paths: list[Path]) -> list[dict[str, Any]]:
    cases: list[dict[str, Any]] = []
    case_no = 0
    for csv_path in csv_paths:
        with csv_path.open("r", encoding="utf-8-sig", newline="") as file:
            for row in csv.DictReader(file):
                case_no += 1
                conversation = _load_conversation(row.get("conversation_json") or "")
                original_messages = [
                    {
                        "role": item.get("role"),
                        "content": str(item.get("content") or ""),
                        "response_time_sec": item.get("response_time_sec"),
                    }
                    for item in conversation
                    if item.get("role") in {"user", "assistant"} and item.get("content")
                ]
                user_turns = [
                    item["content"]
                    for item in original_messages
                    if item.get("role") == "user"
                ]
                cases.append(
                    {
                        "case_no": case_no,
                        "feedback_id": row.get("feedback_id") or "",
                        "date": (row.get("created_at") or "")[:10],
                        "feedback_type": row.get("feedback_type") or "",
                        "category": row.get("decision_type") or "",
                        "title": row.get("user_message") or (user_turns[-1] if user_turns else ""),
                        "suggestion": row.get("suggestion") or "",
                        "company_code": row.get("company_code") or row.get("tv_cable") or "tdtv",
                        "company": row.get("company") or "",
                        "original_messages": original_messages,
                        "user_turns": user_turns,
                        "source_csv": str(csv_path),
                    }
                )
    return cases


def _normalize(value: str) -> str:
    return re.sub(r"\s+", "", value or "").lower()


def evaluate(result: dict[str, Any]) -> dict[str, Any]:
    if result.get("status") == "ERROR":
        return {
            "status": "ERROR",
            "label": "API 執行失敗",
            "reasons": [result.get("error") or "未知錯誤"],
        }

    case_no = int(result.get("case_no") or 0)
    spec = EXPECTATIONS.get(case_no)
    if not spec:
        return {
            "status": "REVIEW",
            "label": "尚未建立自動驗證規則",
            "reasons": ["請人工檢視完整多輪回答。"],
        }
    if spec.get("review_only"):
        return {
            "status": "DEPENDENCY",
            "label": spec.get("label") or "外部依賴",
            "reasons": [spec.get("note") or "需人工確認外部系統狀態。"],
        }

    assistant_messages = [
        str(item.get("content") or "")
        for item in (result.get("rerun_messages") or [])
        if item.get("role") == "assistant"
    ]
    final_reply = assistant_messages[-1] if assistant_messages else ""
    normalized = _normalize(final_reply)
    reasons: list[str] = []

    for group in spec.get("must") or ():
        if not any(_normalize(term) in normalized for term in group):
            reasons.append(f"缺少必要資訊：{' / '.join(group)}")

    for term in spec.get("must_not") or ():
        if _normalize(term) in normalized:
            reasons.append(f"仍出現不應有內容：{term}")

    return {
        "status": "FAIL" if reasons else "PASS",
        "label": spec.get("label") or "",
        "reasons": reasons or ["最終回答符合本案例的必要資訊與排除條件。"],
        "final_reply": final_reply,
    }


def render_report(results: list[dict[str, Any]], csv_paths: list[Path]) -> str:
    status_counts: dict[str, int] = {}
    for item in results:
        status = (item.get("evaluation") or {}).get("status") or "PENDING"
        status_counts[status] = status_counts.get(status, 0) + 1

    cards: list[str] = []
    for item in results:
        evaluation = item.get("evaluation") or {}
        eval_status = evaluation.get("status") or "PENDING"
        reasons = "".join(f"<li>{esc(reason)}</li>" for reason in evaluation.get("reasons") or [])
        cards.append(
            f"""
            <article class="case-card" id="case-{int(item.get('case_no') or 0):02d}">
              <header class="case-head">
                <div>
                  <div class="case-kicker">{esc(item.get('date'))}｜#{int(item.get('case_no') or 0):02d}｜{esc(item.get('feedback_type'))}</div>
                  <h2>{esc(item.get('title'))}</h2>
                  <div class="company">{esc(item.get('company'))}（{esc(item.get('company_code'))}）</div>
                </div>
                <span class="status {esc(eval_status)}">{esc(eval_status)}</span>
              </header>
              <section class="evaluation {esc(eval_status)}">
                <strong>{esc(evaluation.get('label'))}</strong>
                <ul>{reasons}</ul>
              </section>
              <section>
                <h3>API 重跑後完整多輪對話</h3>
                <div class="conversation">{render_messages(item.get('rerun_messages') or [])}</div>
              </section>
              <section class="feedback">
                <h3>客服原始回饋</h3>
                <p>{esc(item.get('suggestion'))}</p>
              </section>
              <details>
                <summary>查看原始對話、路由與後端狀態</summary>
                <h3>原始對話</h3>
                <div class="conversation">{render_messages(item.get('original_messages') or [])}</div>
                <h3>API 每輪資訊</h3>
                {render_turn_debug(item.get('turn_results') or [])}
                <pre>{esc(json.dumps(item.get('final_memory') or {{}}, ensure_ascii=False, indent=2))}</pre>
              </details>
            </article>
            """
        )

    source_list = "、".join(path.name for path in csv_paths)
    stats = "".join(
        f'<div class="stat {esc(status)}"><strong>{count}</strong><span>{esc(status)}</span></div>'
        for status, count in sorted(status_counts.items())
    )
    return f"""<!doctype html>
<html lang="zh-Hant">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>7/20–7/27 客服回饋逐案重跑</title>
<style>
:root {{
  color-scheme: dark;
  --bg: #0a0e15; --panel: #121925; --panel2: #182231; --line: #334155;
  --text: #f8fafc; --muted: #aab6c8; --accent: #f59e0b;
  --pass: #4ade80; --fail: #fb7185; --review: #fbbf24; --dependency: #60a5fa;
}}
* {{ box-sizing: border-box; }}
body {{ margin: 0; background: var(--bg); color: var(--text); font-family: "Microsoft JhengHei", sans-serif; line-height: 1.65; }}
.page-head {{ position: sticky; top: 0; z-index: 5; padding: 20px max(24px, calc((100vw - 1240px)/2)); background: rgba(10,14,21,.94); border-bottom: 1px solid var(--line); backdrop-filter: blur(12px); }}
h1 {{ margin: 0; font-size: 28px; }} .sub,.company {{ color: var(--muted); }}
.stats {{ display: flex; gap: 10px; margin-top: 12px; flex-wrap: wrap; }}
.stat {{ min-width: 92px; padding: 8px 12px; border: 1px solid var(--line); border-radius: 8px; background: var(--panel); }}
.stat strong,.stat span {{ display: block; }} .stat strong {{ font-size: 20px; }}
.stat.PASS strong {{ color: var(--pass); }} .stat.FAIL strong {{ color: var(--fail); }}
.stat.DEPENDENCY strong {{ color: var(--dependency); }} .stat.ERROR strong {{ color: var(--fail); }}
main {{ width: min(1240px, calc(100% - 30px)); margin: 22px auto; }}
.case-card {{ margin: 0 0 20px; padding: 20px; border: 1px solid var(--line); border-radius: 8px; background: var(--panel); }}
.case-head {{ display: flex; align-items: flex-start; justify-content: space-between; gap: 16px; }}
.case-kicker {{ color: var(--accent); font-size: 13px; font-weight: 800; }}
h2 {{ margin: 4px 0; font-size: 22px; }} h3 {{ margin: 18px 0 8px; font-size: 16px; }}
.status {{ flex: none; padding: 4px 10px; border-radius: 999px; border: 1px solid currentColor; font-weight: 900; }}
.status.PASS {{ color: var(--pass); }} .status.FAIL,.status.ERROR {{ color: var(--fail); }}
.status.REVIEW {{ color: var(--review); }} .status.DEPENDENCY {{ color: var(--dependency); }}
.evaluation {{ margin-top: 14px; padding: 12px 14px; border-left: 4px solid var(--review); background: var(--panel2); border-radius: 6px; }}
.evaluation.PASS {{ border-color: var(--pass); }} .evaluation.FAIL,.evaluation.ERROR {{ border-color: var(--fail); }}
.evaluation.DEPENDENCY {{ border-color: var(--dependency); }} .evaluation ul {{ margin: 6px 0 0; padding-left: 22px; }}
.conversation {{ padding: 10px 12px; border: 1px solid var(--line); border-radius: 8px; background: #0d131d; }}
.bubble-row {{ display: grid; gap: 10px; align-items: start; margin: 10px 0; }}
.bubble-row.ai {{ grid-template-columns: 42px minmax(0, 1fr); }}
.bubble-row.user {{ grid-template-columns: minmax(0, 1fr) 42px; }}
.bubble-row.user .avatar {{ grid-column: 2; background: #ef174b; }}
.bubble-row.user .bubble {{ grid-column: 1; grid-row: 1; justify-self: end; background: #183b63; }}
.bubble-row.ai .avatar {{ background: #df741e; }}
.avatar {{ width: 42px; height: 42px; border-radius: 7px; display:flex; align-items:center; justify-content:center; font-weight:900; font-size:12px; }}
.bubble {{ max-width: 84%; padding: 10px 12px; border: 1px solid var(--line); border-radius: 7px; background: #1a202b; }}
.bubble-head,.bubble-meta {{ color: var(--muted); font-size: 12px; }} .bubble-body {{ white-space: normal; }}
.feedback {{ margin-top: 12px; padding: 2px 14px 10px; border-left: 4px solid var(--accent); background: #171e29; border-radius: 6px; }}
details {{ margin-top: 14px; color: var(--muted); }} summary {{ cursor: pointer; font-weight: 800; }}
.debug-table {{ width: 100%; border-collapse: collapse; }} .debug-table th,.debug-table td {{ padding: 7px; border-bottom: 1px solid var(--line); text-align: left; }}
pre {{ padding: 12px; border-radius: 7px; background: #05070b; white-space: pre-wrap; overflow-wrap: anywhere; }}
@media (max-width: 760px) {{ .bubble {{ max-width: 94%; }} .case-head {{ align-items: center; }} }}
</style>
</head>
<body>
<header class="page-head">
  <h1>7/20–7/27 客服回饋逐案 API 重跑</h1>
  <div class="sub">來源：{esc(source_list)}｜產生時間：{esc(datetime.now().strftime("%Y-%m-%d %H:%M:%S"))}</div>
  <div class="stats"><div class="stat"><strong>{len(results)}</strong><span>已執行案例</span></div>{stats}</div>
</header>
<main>{''.join(cards)}</main>
</body>
</html>"""


def save_checkpoint(
    results: list[dict[str, Any]],
    csv_paths: list[Path],
    json_path: Path,
    html_path: Path,
) -> None:
    json_path.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    html_path.write_text(render_report(results, csv_paths), encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--feedback-dir", default=str(DEFAULT_FEEDBACK_DIR))
    parser.add_argument("--dates", default=",".join(DEFAULT_DATES))
    parser.add_argument("--backend-url", default="http://127.0.0.1:8123")
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    parser.add_argument("--case", default="", help="Comma-separated global case numbers")
    parser.add_argument("--resume-json", default="")
    args = parser.parse_args()

    feedback_dir = Path(args.feedback_dir)
    csv_paths = [
        feedback_dir / f"ai_feedback_2026-07-{date.strip()}.csv"
        for date in args.dates.split(",")
        if date.strip()
    ]
    missing = [str(path) for path in csv_paths if not path.exists()]
    if missing:
        raise FileNotFoundError(f"Missing feedback CSV: {missing}")

    all_cases = extract_cases(csv_paths)
    allowed = {
        int(value.strip())
        for value in args.case.split(",")
        if value.strip()
    }
    cases = [
        item
        for item in all_cases
        if not allowed or int(item["case_no"]) in allowed
    ]

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    json_path = output_dir / f"feedback_api_rerun_{stamp}.json"
    html_path = output_dir / f"feedback_api_rerun_{stamp}.html"

    results: list[dict[str, Any]] = []
    completed: set[int] = set()
    if args.resume_json:
        resume_path = Path(args.resume_json)
        results = json.loads(resume_path.read_text(encoding="utf-8"))
        completed = {int(item.get("case_no") or 0) for item in results}

    started = time.perf_counter()
    for index, case in enumerate(cases, start=1):
        case_no = int(case["case_no"])
        if case_no in completed:
            continue
        print(
            f"[{index}/{len(cases)}] #{case_no:02d} "
            f"{case.get('company_code')} | {len(case.get('user_turns') or [])} turns | "
            f"{case.get('title')}",
            flush=True,
        )
        result = run_case_backend(case, args.backend_url)
        result["evaluation"] = evaluate(result)
        results.append(result)
        results.sort(key=lambda item: int(item.get("case_no") or 0))
        save_checkpoint(results, csv_paths, json_path, html_path)
        print(
            f"  => {result['evaluation']['status']} | "
            f"{result['evaluation'].get('label')} | {result.get('duration_sec')} sec",
            flush=True,
        )

    print(f"TOTAL_SEC={round(time.perf_counter() - started, 3)}", flush=True)
    print(f"JSON={json_path}", flush=True)
    print(f"HTML={html_path}", flush=True)


if __name__ == "__main__":
    main()
