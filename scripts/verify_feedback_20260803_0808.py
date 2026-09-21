from __future__ import annotations

import html
import json
import os
import re
import time
import uuid
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any

import requests

from rerun_feedback_csv_cases import extract_cases
from run_feedback_html_dialog_tests import esc, render_messages, render_turn_debug


ROOT_DIR = Path(__file__).resolve().parent.parent
FEEDBACK_DIR = ROOT_DIR.parent / "cust_app_runtime" / "feedback"
CSV_PATHS = [
    FEEDBACK_DIR / f"ai_feedback_2026-08-{day}.csv"
    for day in ("03", "04", "06", "08")
]
OUTPUT_DIR = ROOT_DIR / "reports"


EXPECTATIONS: dict[int, dict[str, Any]] = {
    1: {
        "label": "退費問題只說明需依合約狀態確認，不混入其他促銷方案",
        "must": (("退費",), ("合約", "繳別", "已使用期間"), ("客服", "確認")),
        "must_not": ("爸氣獻禮", "違約金 2,400", "違約金2400"),
    },
    2: {
        "label": "重複反映網路不能連線後應進入網路排錯",
        "must": (("數據機", "網路線", "電源", "燈號", "重開"),),
        "must_not": ("請問目前遇到的是電視、網路", "查詢資料、辦理服務，還是回報故障"),
    },
    3: {
        "label": "多次確認網路不能連線後仍應延續排錯，不可重置流程",
        "must": (("數據機", "網路線", "電源", "燈號", "重開", "報修"),),
        "must_not": ("請問目前遇到的是電視、網路", "查詢資料、辦理服務，還是回報故障"),
    },
    4: {
        "label": "有線電視裝機申請應回答裝機費與收視費",
        "must": (("裝機費",), ("1,500", "1500"), ("550", "6,550", "6550")),
        "must_not": ("本期帳單",),
    },
    5: {
        "label": "正常使用戶無待繳費用時應回覆目前無須繳納",
        "must": (("無費用", "無待繳", "無須繳", "沒有需要繳"),),
        "note": "此案原始情境含登入客戶身分；若重播環境未帶入該身分，需人工判讀。",
    },
    6: {
        "label": "姓名與電話完整時應能完成帳單查詢",
        "must_not": ("查詢不到您的資料", "姓名與電話資訊不一致"),
        "note": "此案結果同時受測試帳務 API 資料影響。",
    },
    7: {
        "label": "第四台與光纖更換用戶應回答過戶／更名流程",
        "must": (("更換用戶", "過戶", "更名", "戶名"), ("客服", "文件", "帳戶", "合約")),
        "must_not": ("優惠方案", "爸氣獻禮", "好視成雙"),
    },
    8: {
        "label": "有線網路未連線應直接提供基本網路排錯",
        "must": (("數據機",), ("電源", "重開"), ("線路", "網路線")),
        "must_not": ("請問目前遇到的是電視、網路",),
    },
    9: {
        "label": "換約後載具問題應回答發票載具，不可誤走合約方案",
        "must": (("載具",), ("歸戶", "重新綁定", "帳戶狀態", "客服")),
        "must_not": ("優惠方案", "目前服務內容與合約資訊"),
    },
    10: {
        "label": "機上盒要求密碼時先引導輸入 0000",
        "must": (("0000",),),
    },
    11: {
        "label": "輸入 0000 後顯示未授權應說明可能誤入付費頻道",
        "must": (("付費頻道", "需加購", "另行訂閱"), ("200", "頻道向下", "切換")),
        "must_not": ("繳費方式",),
    },
    12: {
        "label": "發票加入手機條碼應先確認是否要辦理載具歸戶",
        "must": (("手機條碼", "載具"), ("歸戶", "綁定")),
        "must_not": ("直接轉真人",),
    },
    13: {
        "label": "含符號的無效客編不可模糊比對到其他客戶",
        "must": (("格式", "數字", "無效", "查無", "重新輸入"),),
        "must_not": ("合計：", "寬頻月租：", "有線電視："),
    },
    14: {
        "label": "機上盒搜不到訊號且已說故障時應延續電視排錯",
        "must": (("機上盒", "電視"), ("電源", "線路", "訊號", "重開", "報修")),
        "must_not": ("請問目前遇到的是電視、網路", "查詢資料、辦理服務，還是回報故障"),
    },
    15: {
        "label": "已說電視完全斷訊後應直接排錯，不重問問題類別",
        "must": (("機上盒", "電視"), ("電源", "訊號", "線路", "重開", "報修")),
        "must_not": ("請問目前遇到的是電視、網路", "請問您想查詢資料、辦理服務，還是回報故障"),
    },
    16: {
        "label": "欠費斷訊應回答繳費復線流程",
        "must": (("繳費",), ("復線", "開通", "重開", "入帳")),
        "must_not": ("請問目前遇到的是電視、網路",),
    },
    17: {
        "label": "哈 POINT 應回答點數用途",
        "must": (("哈point", "哈 point", "紅利點數"), ("購買", "抵扣", "服務費用", "商品")),
        "must_not": ("好視成雙", "退租"),
    },
}


CASE_DIAGNOSTICS: dict[int, dict[str, Any]] = {
    13: {
        "title": "第 13 案完整判讀",
        "summary": (
            "這一案不是單純的 CUST API 查不到資料。舊流程把含符號的客編 -046793 原樣送出；"
            "外部 API 回傳 HTTP 200、code=0099、msg=查無客戶資料，但回應中同時夾帶 data。"
            "舊程式先看到 data 就當成帳單成功，因而顯示到不屬於該客編的帳單。"
        ),
        "evidence": [
            "舊送出條件：custNo=-046793（包含非數字字元）",
            "CUST API 狀態：HTTP 200 / code=0099 / msg=查無客戶資料",
            "異常點：失敗狀態中仍含 data，舊程式錯把 data 視為成功帳單",
            "修正後：客編只接受純數字；先判斷 code/msg，再決定是否讀取 data",
            "預期結果：直接提示客編格式錯誤，且不呼叫 CUST API",
        ],
    }
}


def normalize(value: str) -> str:
    return re.sub(r"\s+", "", value or "").casefold()


def get_api_token(base_url: str) -> str:
    name = os.environ.get("TEST_API_AUTH_NAME", "").strip()
    password = os.environ.get("TEST_API_AUTH_PASSWORD", "")
    if not name or not password:
        raise RuntimeError("TEST_API_AUTH_NAME / TEST_API_AUTH_PASSWORD is not configured")
    response = requests.post(
        f"{base_url}/api/auth/token",
        json={"name": name, "password": password},
        timeout=30,
    )
    response.raise_for_status()
    return str(response.json().get("access_token") or "")


def evaluate(result: dict[str, Any]) -> dict[str, Any]:
    if result.get("status") == "ERROR":
        return {"status": "ERROR", "label": "API 執行失敗", "reasons": [result.get("error") or "未知錯誤"]}

    spec = EXPECTATIONS[int(result["case_no"])]
    assistant_messages = [
        str(message.get("content") or "")
        for message in result.get("rerun_messages") or []
        if message.get("role") == "assistant"
    ]
    final_reply = assistant_messages[-1] if assistant_messages else ""
    text = normalize(final_reply)
    reasons: list[str] = []
    for group in spec.get("must") or ():
        if not any(normalize(term) in text for term in group):
            reasons.append(f"缺少必要資訊：{' / '.join(group)}")
    for term in spec.get("must_not") or ():
        if normalize(term) in text:
            reasons.append(f"仍出現不應有內容：{term}")

    status = "FAIL" if reasons else "PASS"
    if int(result["case_no"]) in {5, 6} and status == "FAIL":
        status = "DEPENDENCY"
        reasons.append("此案例依賴原登入客戶身分或測試帳務 API 資料，需搭配每輪狀態人工判讀。")
    if spec.get("note"):
        reasons.append(str(spec["note"]))
    return {
        "status": status,
        "label": spec["label"],
        "reasons": reasons or ["API 最終回答符合本案例必要資訊與排除條件。"],
        "final_reply": final_reply,
    }


def run_case(case: dict[str, Any], base_url: str, headers: dict[str, str]) -> dict[str, Any]:
    user_id = f"test_web:feedback-verify-{case['case_no']:02d}-{uuid.uuid4().hex[:8]}"
    company_code = str(case.get("company_code") or "tdtv")
    rerun_messages: list[dict[str, Any]] = []
    turn_results: list[dict[str, Any]] = []
    started = time.perf_counter()
    result = {
        **case,
        "user_id": user_id,
        "runner": "authenticated_backend_api",
        "backend_url": base_url,
        "status": "PASS",
        "error": "",
        "rerun_messages": rerun_messages,
        "turn_results": turn_results,
        "final_memory": {},
        "duration_sec": 0.0,
    }
    try:
        reset = requests.post(f"{base_url}/reset/{user_id}", headers=headers, timeout=30)
        reset.raise_for_status()
        for turn_index, user_text in enumerate(case.get("user_turns") or [], start=1):
            rerun_messages.append({"role": "user", "content": user_text})
            turn_started = time.perf_counter()
            response = requests.post(
                f"{base_url}/chat",
                headers=headers,
                json={"user_id": user_id, "user_input": user_text, "tv_cable": company_code},
                timeout=300,
            )
            request_time = round(time.perf_counter() - turn_started, 3)
            response.raise_for_status()
            payload = response.json()
            ai_response = str(payload.get("ai_response") or "")
            rerun_messages.append(
                {
                    "role": "assistant",
                    "content": ai_response,
                    "response_time_sec": payload.get("response_time_sec") or request_time,
                }
            )
            turn_results.append(
                {
                    "turn": turn_index,
                    "http_status": response.status_code,
                    "request_time_sec": request_time,
                    "response_time_sec": payload.get("response_time_sec"),
                    "latency": payload.get("latency") or {},
                    "actions": payload.get("actions") or [],
                    "known_info": payload.get("known_info"),
                    "decision_type": payload.get("decision_type"),
                    "company_code": payload.get("company_code"),
                    "company": payload.get("company"),
                }
            )
        state = requests.get(
            f"{base_url}/state/{user_id}",
            headers=headers,
            params={"tv_cable": company_code},
            timeout=30,
        )
        if state.ok:
            result["final_memory"] = state.json()
    except Exception as exc:
        result["status"] = "ERROR"
        result["error"] = str(exc)
    finally:
        result["duration_sec"] = round(time.perf_counter() - started, 3)
    result["evaluation"] = evaluate(result)
    return result


def render_report(results: list[dict[str, Any]]) -> str:
    counts = Counter((item.get("evaluation") or {}).get("status") or "UNKNOWN" for item in results)
    stats = "".join(
        f'<div class="stat {esc(status)}"><strong>{count}</strong><span>{esc(status)}</span></div>'
        for status, count in sorted(counts.items())
    )
    cards: list[str] = []
    for item in results:
        evaluation = item.get("evaluation") or {}
        status = str(evaluation.get("status") or "UNKNOWN")
        reasons = "".join(f"<li>{esc(reason)}</li>" for reason in evaluation.get("reasons") or [])
        diagnostic = CASE_DIAGNOSTICS.get(int(item["case_no"]))
        diagnostic_html = ""
        if diagnostic:
            evidence = "".join(f"<li>{esc(line)}</li>" for line in diagnostic["evidence"])
            diagnostic_html = f"""
              <section class="diagnosis">
                <h3>{esc(diagnostic['title'])}</h3>
                <p>{esc(diagnostic['summary'])}</p>
                <ul>{evidence}</ul>
                <h3>客服回饋中的完整原始對話</h3>
                <div class="conversation">{render_messages(item.get('original_messages') or [])}</div>
              </section>
            """
        cards.append(
            f"""
            <article class="case-card" id="case-{int(item['case_no']):02d}">
              <header><div><div class="kicker">{esc(item.get('date'))}｜#{int(item['case_no']):02d}｜{esc(item.get('feedback_type'))}</div><h2>{esc(item.get('title'))}</h2><div class="muted">{esc(item.get('company'))}（{esc(item.get('company_code'))}）</div></div><span class="status {esc(status)}">{esc(status)}</span></header>
              <section class="evaluation {esc(status)}"><strong>{esc(evaluation.get('label'))}</strong><ul>{reasons}</ul></section>
              {diagnostic_html}
              <h3>8123 API 實際重播</h3><div class="conversation">{render_messages(item.get('rerun_messages') or [])}</div>
              <section class="feedback"><h3>客服原始建議</h3><p>{esc(item.get('suggestion'))}</p></section>
              <details><summary>查看原始對話、每輪路由與後端狀態</summary><h3>原始對話</h3><div class="conversation">{render_messages(item.get('original_messages') or [])}</div><h3>每輪資訊</h3>{render_turn_debug(item.get('turn_results') or [])}<pre>{esc(json.dumps(item.get('final_memory') or {}, ensure_ascii=False, indent=2))}</pre></details>
            </article>
            """
        )
    return f"""<!doctype html><html lang="zh-Hant"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>8/3–8/8 客服回饋實測</title><style>
:root{{color-scheme:dark;--bg:#0a0e15;--panel:#121925;--panel2:#182231;--line:#334155;--text:#f8fafc;--muted:#aab6c8;--accent:#f59e0b;--pass:#4ade80;--fail:#fb7185;--dep:#60a5fa}}*{{box-sizing:border-box}}body{{margin:0;background:var(--bg);color:var(--text);font-family:"Microsoft JhengHei",sans-serif;line-height:1.65}}.page-head{{position:sticky;top:0;z-index:5;padding:20px max(24px,calc((100vw - 1240px)/2));background:rgba(10,14,21,.94);border-bottom:1px solid var(--line);backdrop-filter:blur(12px)}}h1{{margin:0;font-size:28px}}.muted{{color:var(--muted)}}.stats{{display:flex;gap:10px;margin-top:12px;flex-wrap:wrap}}.stat{{min-width:92px;padding:8px 12px;border:1px solid var(--line);border-radius:7px;background:var(--panel)}}.stat strong,.stat span{{display:block}}.stat.PASS strong{{color:var(--pass)}}.stat.FAIL strong,.stat.ERROR strong{{color:var(--fail)}}.stat.DEPENDENCY strong{{color:var(--dep)}}main{{width:min(1240px,calc(100% - 30px));margin:22px auto}}.case-card{{margin-bottom:20px;padding:20px;border:1px solid var(--line);border-radius:7px;background:var(--panel)}}header{{display:flex;align-items:flex-start;justify-content:space-between;gap:16px}}.kicker{{color:var(--accent);font-size:13px;font-weight:800}}h2{{margin:4px 0;font-size:22px}}h3{{margin:18px 0 8px;font-size:16px}}.status{{padding:4px 10px;border:1px solid currentColor;border-radius:999px;font-weight:900}}.status.PASS{{color:var(--pass)}}.status.FAIL,.status.ERROR{{color:var(--fail)}}.status.DEPENDENCY{{color:var(--dep)}}.evaluation{{margin-top:14px;padding:12px 14px;border-left:4px solid var(--accent);background:var(--panel2);border-radius:6px}}.evaluation.PASS{{border-color:var(--pass)}}.evaluation.FAIL,.evaluation.ERROR{{border-color:var(--fail)}}.evaluation.DEPENDENCY{{border-color:var(--dep)}}.evaluation ul{{margin:6px 0 0;padding-left:22px}}.diagnosis{{margin-top:14px;padding:14px;border:1px solid #765722;border-radius:7px;background:#211b12}}.diagnosis h3:first-child{{margin-top:0}}.diagnosis ul{{margin:6px 0 14px;padding-left:22px}}.conversation{{padding:10px 12px;border:1px solid var(--line);border-radius:7px;background:#0d131d}}.bubble-row{{display:grid;gap:10px;align-items:start;margin:10px 0}}.bubble-row.ai{{grid-template-columns:42px minmax(0,1fr)}}.bubble-row.user{{grid-template-columns:minmax(0,1fr) 42px}}.bubble-row.user .avatar{{grid-column:2;background:#ef174b}}.bubble-row.user .bubble{{grid-column:1;grid-row:1;justify-self:end;background:#183b63}}.bubble-row.ai .avatar{{background:#df741e}}.avatar{{width:42px;height:42px;border-radius:7px;display:flex;align-items:center;justify-content:center;font-weight:900;font-size:12px}}.bubble{{max-width:84%;padding:10px 12px;border:1px solid var(--line);border-radius:7px;background:#1a202b}}.bubble-head,.bubble-meta{{color:var(--muted);font-size:12px}}.feedback{{margin-top:12px;padding:2px 14px 10px;border-left:4px solid var(--accent);background:#171e29;border-radius:6px}}details{{margin-top:14px;color:var(--muted)}}summary{{cursor:pointer;font-weight:800}}.debug-table{{width:100%;border-collapse:collapse}}.debug-table th,.debug-table td{{padding:7px;border-bottom:1px solid var(--line);text-align:left}}pre{{padding:12px;border-radius:7px;background:#05070b;white-space:pre-wrap;overflow-wrap:anywhere}}@media(max-width:760px){{.bubble{{max-width:94%}}}}
</style></head><body><div class="page-head"><h1>8/3–8/8 客服回饋逐案 API 實測</h1><div class="muted">後端：127.0.0.1:8123｜產生時間：{esc(datetime.now().strftime('%Y-%m-%d %H:%M:%S'))}</div><div class="stats"><div class="stat"><strong>{len(results)}</strong><span>已執行</span></div>{stats}</div></div><main>{''.join(cards)}</main></body></html>"""


def main() -> None:
    for path in CSV_PATHS:
        if not path.exists():
            raise FileNotFoundError(path)
    base_url = os.environ.get("TEST_BACKEND_URL", "http://127.0.0.1:8123").rstrip("/")
    token = get_api_token(base_url)
    headers = {"Authorization": f"Bearer {token}"}
    health = requests.get(f"{base_url}/health", headers=headers, timeout=30)
    health.raise_for_status()

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    json_path = OUTPUT_DIR / f"feedback_verify_20260803_0808_{stamp}.json"
    html_path = OUTPUT_DIR / f"feedback_verify_20260803_0808_{stamp}.html"
    results: list[dict[str, Any]] = []
    cases = extract_cases(CSV_PATHS)
    requested_cases = {
        int(value)
        for value in re.split(r"[,\s]+", os.environ.get("TEST_CASE_NUMBERS", "").strip())
        if value
    }
    if requested_cases:
        cases = [case for case in cases if int(case["case_no"]) in requested_cases]
        missing_cases = requested_cases - {int(case["case_no"]) for case in cases}
        if missing_cases:
            raise RuntimeError(f"Unknown case numbers: {sorted(missing_cases)}")
    started = time.perf_counter()
    for index, case in enumerate(cases, start=1):
        print(f"[{index}/{len(cases)}] #{case['case_no']:02d} turns={len(case['user_turns'])} {case['title']}", flush=True)
        result = run_case(case, base_url, headers)
        results.append(result)
        json_path.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
        html_path.write_text(render_report(results), encoding="utf-8")
        evaluation = result["evaluation"]
        print(f"  => {evaluation['status']} | {result['duration_sec']} sec | {evaluation['label']}", flush=True)
    print(f"TOTAL_SEC={round(time.perf_counter() - started, 3)}", flush=True)
    print(f"JSON={json_path}", flush=True)
    print(f"HTML={html_path}", flush=True)


if __name__ == "__main__":
    main()
