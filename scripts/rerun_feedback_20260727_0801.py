from __future__ import annotations

import csv
import base64
import hashlib
import hmac
import html
import json
import os
import re
import sys
import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

import requests
from dotenv import dotenv_values


ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

FEEDBACK_FILES = (
    ROOT_DIR.parent / "cust_app_runtime" / "feedback" / "ai_feedback_2026-07-27.csv",
    ROOT_DIR.parent / "cust_app_runtime" / "feedback" / "ai_feedback_2026-07-29.csv",
    ROOT_DIR.parent / "cust_app_runtime" / "feedback" / "ai_feedback_2026-07-30.csv",
    ROOT_DIR.parent / "cust_app_runtime" / "feedback" / "ai_feedback_2026-07-31.csv",
    ROOT_DIR.parent / "cust_app_runtime" / "feedback" / "ai_feedback_2026-08-01.csv",
)
BACKEND_URL = "http://127.0.0.1:8123"
OUTPUT_DIR = ROOT_DIR / "reports"


def esc(value: Any) -> str:
    return html.escape(str(value or "")).replace("\n", "<br>")


def get_backend_auth_headers(base_url: str) -> dict[str, str]:
    env_file = os.getenv("CUST_APP_ENV_FILE", ".env")
    config = dotenv_values(ROOT_DIR / env_file)
    fixed_token = str(config.get("API_AUTH_TOKEN") or "").strip()
    header_name = str(config.get("API_AUTH_HEADER") or "X-API-Token").strip()
    if fixed_token:
        return {header_name: fixed_token}
    name = str(config.get("API_AUTH_NAME") or "").strip()
    password = str(config.get("API_AUTH_PASSWORD") or "").strip()
    secret = str(config.get("API_AUTH_SECRET") or "").strip()
    if name and password:
        response = requests.post(
            f"{base_url.rstrip('/')}/api/auth/token",
            json={"name": name, "password": password},
            timeout=15,
        )
        if response.status_code == 200:
            token_data = response.json()
            access_token = str(token_data.get("access_token") or "").strip()
            response_header = str(token_data.get("header_name") or header_name).strip()
            if access_token:
                return {response_header: access_token}
    if not name or not secret:
        return {}
    now = int(time.time())
    payload = {
        "sub": name,
        "iat": now,
        "exp": now + 600,
        "nonce": uuid.uuid4().hex,
    }
    payload_raw = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    payload_b64 = base64.urlsafe_b64encode(payload_raw).decode("ascii").rstrip("=")
    signature = hmac.new(secret.encode("utf-8"), payload_b64.encode("ascii"), hashlib.sha256).digest()
    signature_b64 = base64.urlsafe_b64encode(signature).decode("ascii").rstrip("=")
    token = f"aicust.{payload_b64}.{signature_b64}"
    return {header_name: token}


def run_case_backend(case: dict[str, Any], backend_url: str) -> dict[str, Any]:
    user_id = f"test_web:feedback-case-{case['case_no']:02d}-{uuid.uuid4().hex[:8]}"
    company_code = case.get("company_code") or "tdtv"
    rerun_messages: list[dict[str, Any]] = []
    turn_results: list[dict[str, Any]] = []
    started = time.perf_counter()
    base_url = backend_url.rstrip("/")
    result: dict[str, Any] = {
        **case,
        "user_id": user_id,
        "runner": "backend_api",
        "backend_url": base_url,
        "status": "PASS",
        "error": "",
        "rerun_messages": rerun_messages,
        "turn_results": turn_results,
        "final_memory": {},
        "duration_sec": 0.0,
    }
    try:
        headers = get_backend_auth_headers(base_url)
        reset_resp = requests.post(f"{base_url}/reset/{user_id}", headers=headers, timeout=15)
        if reset_resp.status_code >= 400:
            result["reset_warning"] = reset_resp.text
        for turn_index, user_text in enumerate(case.get("user_turns") or [], start=1):
            rerun_messages.append({"role": "user", "content": user_text})
            turn_started = time.perf_counter()
            resp = requests.post(
                f"{base_url}/chat",
                json={"user_id": user_id, "user_input": user_text, "tv_cable": company_code},
                headers=headers,
                timeout=120,
            )
            request_time_sec = round(time.perf_counter() - turn_started, 3)
            if resp.status_code >= 400:
                raise RuntimeError(f"HTTP {resp.status_code}: {resp.text}")
            response = resp.json()
            ai_response = str(response.get("ai_response") or "")
            rerun_messages.append({
                "role": "assistant",
                "content": ai_response,
                "response_time_sec": response.get("response_time_sec") or request_time_sec,
            })
            turn_results.append({
                "turn": turn_index,
                "http_status": resp.status_code,
                "request_time_sec": request_time_sec,
                "response_time_sec": response.get("response_time_sec"),
                "latency": response.get("latency") or {},
                "actions": response.get("actions") or [],
                "known_info": response.get("known_info"),
                "decision_type": response.get("decision_type"),
                "company_code": response.get("company_code"),
                "company": response.get("company"),
            })
        state_resp = requests.get(
            f"{base_url}/state/{user_id}",
            params={"tv_cable": company_code},
            headers=headers,
            timeout=15,
        )
        if state_resp.status_code < 400:
            result["final_memory"] = state_resp.json()
        else:
            result["state_warning"] = state_resp.text
    except Exception as exc:
        result["status"] = "ERROR"
        result["error"] = str(exc)
    finally:
        result["duration_sec"] = round(time.perf_counter() - started, 3)
    return result


def render_messages(messages: list[dict[str, Any]]) -> str:
    if not messages:
        return '<div class="muted">沒有可重跑的 user turn。</div>'
    parts: list[str] = []
    for item in messages:
        role = "user" if item.get("role") == "user" else "ai"
        label = "User" if role == "user" else "AI"
        meta = ""
        if role == "ai" and item.get("response_time_sec") is not None:
            meta = f'<div class="bubble-meta">{esc(item.get("response_time_sec"))} 秒</div>'
        parts.append(
            f'<div class="bubble-row {role}"><div class="avatar">{label}</div>'
            f'<div class="bubble {role}"><div class="bubble-head">{label}</div>'
            f'<div class="bubble-body">{esc(item.get("content"))}</div>{meta}</div></div>'
        )
    return "".join(parts)


def render_turn_debug(turn_results: list[dict[str, Any]]) -> str:
    if not turn_results:
        return '<div class="muted">沒有 turn debug。</div>'
    rows = []
    for item in turn_results:
        latency = item.get("latency") or {}
        actions = ", ".join(str((action or {}).get("type") or action) for action in (item.get("actions") or []))
        rows.append(
            "<tr>"
            f'<td>{esc(item.get("turn"))}</td><td>{esc(item.get("decision_type"))}</td>'
            f'<td>{esc(actions)}</td><td>{esc(item.get("company_code"))}</td>'
            f'<td>{esc(round(float(item.get("request_time_sec") or 0), 3))}</td>'
            f'<td>{esc(round(float(latency.get("total") or item.get("response_time_sec") or 0), 3))}</td>'
            "</tr>"
        )
    return (
        '<table class="debug-table"><thead><tr><th>Turn</th><th>Decision</th><th>Actions</th>'
        '<th>Company</th><th>Request 秒</th><th>Total 秒</th></tr></thead><tbody>'
        + "".join(rows)
        + "</tbody></table>"
    )


EXPECTATIONS: dict[int, dict[str, Any]] = {
    1: {
        "label": "寬頻斷訊直接進入網路排錯",
        "must": (("數據機", "燈號", "網路線", "重開", "電源"),),
        "must_not": ("請直接回覆「電視」", "目前遇到的是電視、網路"),
    },
    2: {
        "label": "第四台加網路優先提供好視成雙 NO8",
        "must": (("好視成雙",), ("NO8", "no8")),
    },
    3: {
        "label": "第四台月租直接回答 550 元",
        "must": (("550",),),
    },
    4: {
        "label": "500M 費用依不同方案清楚分列",
        "must": (
            ("500M", "500m"),
            ("飆網守護家",),
            ("哈NET1", "哈 NET1"),
            ("好視成雙",),
            ("2,097", "2097"),
            ("6,600", "6600"),
            ("11,988", "11988"),
        ),
    },
    5: {
        "label": "一年約詢問說明主推 24 個月並提供客服確認",
        "must": (("24", "兩年", "2年"), ("客服", "專人", "確認")),
        "must_not": ("服務地址", "裝機地址"),
    },
    6: {
        "label": "限制級頻道授權到期回答購買方式",
        "must": (
            ("成人", "限制級"),
            ("元", "$"),
            ("優惠專區",),
            ("數位電視",),
            ("客服",),
        ),
        "must_not": ("E004", "重開機"),
    },
    7: {
        "label": "有線電視裝機先提供一般有線電視報價",
        "must": (("有線電視", "第四台"), ("裝機",), ("月租", "收視費", "月繳")),
    },
    8: {
        "label": "月繳新裝兩台機上盒包含首收兩個月",
        "must": (("2個月", "兩個月", "首收"), ("機上盒",), ("合計", "共")),
    },
    9: {
        "label": "新網路優惠首答提供客服核定的核心方案資訊",
        "must": (
            ("好康三合一",),
            ("綁約", "合約"),
            ("月繳", "季繳", "半年繳", "年繳"),
            ("LINE TV",),
            ("POINT",),
        ),
        "must_not": ("清冰組或借用", "清冰組／借用"),
    },
    10: {
        "label": "一年合約延續優惠方案上下文",
        "must": (("一年", "1年"), ("方案", "合約")),
        "must_not": ("提供戶名", "聯絡電話", "目前服務與合約"),
    },
    11: {
        "label": "網路費過期視為逾期繳費並提供繳費方式",
        "must": (("繳費", "繳款"), ("官網", "APP", "超商", "臨櫃")),
        "must_not": ("合約到期", "優惠到期"),
    },
    12: {
        "label": "不存在的頻道號說明編排與頻道數",
        "must": (("4XX", "4xx", "400"), ("100", "120"), ("頻道名稱", "名稱")),
    },
    13: {
        "label": "線上繳費未註冊時說明用戶編號與忘記密碼",
        "must": (("用戶編號",), ("帳單",), ("忘記密碼",), ("APP", "app"), ("簡訊",)),
    },
    14: {
        "label": "父親節優惠命中爸氣獻禮",
        "must": (("爸氣獻禮",),),
    },
    15: {
        "label": "直接詢問爸氣獻禮可取得方案內容",
        "must": (("爸氣獻禮",), ("活動期間",), ("LINE TV", "POINT", "抽獎", "月繳", "季繳")),
    },
    16: {
        "label": "父親節方案延續上下文並回答爸氣獻禮",
        "must": (("爸氣獻禮",),),
    },
    18: {
        "label": "繳費截止日不可誤稱已繳費迄日",
        "must": (("未提供", "不提供", "無法查詢", "僅能確認"), ("已繳費迄日",), ("最新帳單", "客服")),
        "must_not": ("截止日：202",),
    },
    19: {
        "label": "電視投屏依品牌型號與智慧電視規格判斷",
        "must": (
            ("品牌",),
            ("型號",),
            ("智慧電視", "Chromecast", "AirPlay", "Miracast", "螢幕鏡像"),
        ),
    },
}


def esc(value: Any) -> str:
    return html.escape(str(value or "")).replace("\n", "<br>")


def normalize(value: str) -> str:
    return re.sub(r"\s+", "", str(value or "")).lower()


def load_cases() -> list[dict[str, Any]]:
    cases: list[dict[str, Any]] = []
    case_no = 0
    for csv_path in FEEDBACK_FILES:
        with csv_path.open("r", encoding="utf-8-sig", newline="") as file:
            for row in csv.DictReader(file):
                case_no += 1
                if "請無視" in str(row.get("suggestion") or ""):
                    continue
                try:
                    conversation = json.loads(row.get("conversation_json") or "[]")
                except json.JSONDecodeError:
                    conversation = []
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
                    item["content"] for item in original_messages if item.get("role") == "user"
                ]
                cases.append(
                    {
                        "case_no": case_no,
                        "feedback_id": row.get("feedback_id") or "",
                        "date": str(row.get("created_at") or "")[:10],
                        "feedback_type": row.get("feedback_type") or "",
                        "category": row.get("decision_type") or "",
                        "title": row.get("user_message") or (user_turns[-1] if user_turns else ""),
                        "suggestion": row.get("suggestion") or "",
                        "company_code": row.get("company_code") or row.get("tv_cable") or "tdtv",
                        "company": row.get("company") or "",
                        "source_csv": str(csv_path),
                        "original_messages": original_messages,
                        "user_turns": user_turns,
                    }
                )
    return cases


def evaluate(result: dict[str, Any]) -> dict[str, Any]:
    case_no = int(result.get("case_no") or 0)
    spec = EXPECTATIONS[case_no]
    if result.get("status") == "ERROR":
        return {
            "status": "ERROR",
            "label": spec["label"],
            "reasons": [result.get("error") or "API 執行失敗"],
        }

    replies = [
        str(item.get("content") or "")
        for item in result.get("rerun_messages") or []
        if item.get("role") == "assistant"
    ]
    final_reply = replies[-1] if replies else ""
    normalized = normalize(final_reply)
    reasons: list[str] = []
    for group in spec.get("must") or ():
        if not any(normalize(term) in normalized for term in group):
            reasons.append(f"缺少：{' / '.join(group)}")
    for term in spec.get("must_not") or ():
        if normalize(term) in normalized:
            reasons.append(f"不應出現：{term}")

    status = "FAIL" if reasons else ("REVIEW" if spec.get("manual_layout") else "PASS")
    if spec.get("manual_layout") and not reasons:
        reasons.append("必要資料已出現，仍需人工確認兩種方案的視覺分界是否清楚。")
    return {
        "status": status,
        "label": spec["label"],
        "reasons": reasons or ["符合客服建議。"],
        "final_reply": final_reply,
    }


def render_report(results: list[dict[str, Any]]) -> str:
    counts: dict[str, int] = {}
    for item in results:
        status = item["evaluation"]["status"]
        counts[status] = counts.get(status, 0) + 1

    passed = [item for item in results if item["evaluation"]["status"] == "PASS"]
    attention = [item for item in results if item["evaluation"]["status"] != "PASS"]
    pass_rows = "".join(
        f"<tr><td>#{int(item['case_no']):02d}</td><td>{esc(item['title'])}</td>"
        f"<td>{esc(item['evaluation']['label'])}</td></tr>"
        for item in passed
    ) or '<tr><td colspan="3">目前沒有自動判定通過的案例。</td></tr>'

    cards: list[str] = []
    for item in results:
        evaluation = item["evaluation"]
        reasons = "".join(f"<li>{esc(reason)}</li>" for reason in evaluation["reasons"])
        cards.append(
            f"""
            <details class="case-card" open>
              <summary><span><span class="kicker">{esc(item['date'])}｜#{int(item['case_no']):02d}｜{esc(item['company'])}</span>
                <strong class="case-title">{esc(item['title'])}</strong></span><b class="status {esc(evaluation['status'])}">{esc(evaluation['status'])}</b></summary>
              <div class="case-body">
                <section class="evaluation {esc(evaluation['status'])}"><strong>{esc(evaluation['label'])}</strong><ul>{reasons}</ul></section>
                <h3>本機 API 實際完整對話</h3>
                <div class="conversation">{render_messages(item.get('rerun_messages') or [])}</div>
                <h3>客服原始建議</h3><div class="suggestion">{esc(item.get('suggestion'))}</div>
                <details><summary>路由與後端狀態</summary>{render_turn_debug(item.get('turn_results') or [])}</details>
              </div>
            </details>
            """
        )

    stat_html = "".join(
        f'<div class="stat {esc(status)}"><strong>{count}</strong><span>{esc(status)}</span></div>'
        for status, count in sorted(counts.items())
    )
    return f"""<!doctype html>
<html lang="zh-Hant"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>7/27-8/1 客服回饋逐案 API 驗證</title><style>
:root{{--bg:#0c1118;--panel:#131b27;--panel2:#1b2635;--line:#3b4758;--text:#f7f9fc;--muted:#aab5c5;--pass:#4ade80;--fail:#fb7185;--review:#fbbf24;--accent:#f59e0b}}
*{{box-sizing:border-box}}body{{margin:0;background:var(--bg);color:var(--text);font-family:"Microsoft JhengHei",sans-serif;line-height:1.65}}
.page-head{{position:sticky;top:0;z-index:4;padding:20px max(24px,calc((100vw - 1200px)/2));background:rgba(12,17,24,.95);border-bottom:1px solid var(--line);backdrop-filter:blur(10px)}}
h1{{margin:0;font-size:28px}}.sub,.kicker{{color:var(--muted)}}.stats{{display:flex;gap:10px;margin-top:12px}}.stat{{padding:8px 14px;border:1px solid var(--line);border-radius:7px;background:var(--panel)}}
.stat strong,.stat span{{display:block}}.stat.PASS strong{{color:var(--pass)}}.stat.FAIL strong{{color:var(--fail)}}.stat.REVIEW strong{{color:var(--review)}}
main{{width:min(1200px,calc(100% - 30px));margin:22px auto}}.summary{{padding:18px;border:1px solid var(--line);border-radius:8px;background:var(--panel);margin-bottom:20px}}
table{{width:100%;border-collapse:collapse}}th,td{{padding:9px;border-bottom:1px solid var(--line);text-align:left}}th{{color:var(--muted)}}
.case-card{{margin-bottom:18px;border:1px solid var(--line);border-radius:8px;background:var(--panel);overflow:hidden}}.case-card>summary{{display:flex;justify-content:space-between;gap:16px;padding:16px 20px;cursor:pointer;list-style:none}}.case-card>summary::-webkit-details-marker{{display:none}}.case-title{{display:block;font-size:21px;color:var(--text);margin-top:2px}}.case-body{{padding:0 20px 20px}}h3{{font-size:16px;margin:18px 0 8px}}
.status{{height:max-content;padding:4px 10px;border:1px solid currentColor;border-radius:999px}}.status.PASS{{color:var(--pass)}}.status.FAIL{{color:var(--fail)}}.status.REVIEW{{color:var(--review)}}
.evaluation,.suggestion{{padding:12px 14px;border-radius:6px;background:var(--panel2)}}.evaluation{{border-left:4px solid var(--fail)}}.evaluation.PASS{{border-left-color:var(--pass)}}.evaluation.REVIEW{{border-left-color:var(--review)}}.conversation{{padding:10px;border:1px solid var(--line);border-radius:8px;background:#0e141d}}
.bubble-row{{display:grid;gap:10px;align-items:start;margin:10px 0}}.bubble-row.ai{{grid-template-columns:42px minmax(0,1fr)}}.bubble-row.user{{grid-template-columns:minmax(0,1fr) 42px}}.bubble-row.user .avatar{{grid-column:2;background:#ef174b}}.bubble-row.user .bubble{{grid-column:1;grid-row:1;justify-self:end;background:#183b63}}.bubble-row.ai .avatar{{background:#df741e}}
.avatar{{width:42px;height:42px;border-radius:7px;display:flex;align-items:center;justify-content:center;font-weight:800;font-size:12px}}.bubble{{max-width:86%;padding:10px 12px;border:1px solid var(--line);border-radius:7px;background:#1a202b}}.bubble-head,.bubble-meta{{font-size:12px;color:var(--muted)}}
.debug-table{{width:100%}}details{{margin-top:15px;color:var(--muted)}}summary{{cursor:pointer;font-weight:800}}@media(max-width:700px){{.bubble{{max-width:96%}}}}
</style></head><body><header class="page-head"><h1>7/27-8/1 客服回饋逐案 API 驗證</h1>
<div class="sub">每案獨立 User ID；保留原始多輪上下文；所有案例皆可展開檢視。產生時間：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</div><div class="stats"><div class="stat"><strong>{len(results)}</strong><span>總案例</span></div>{stat_html}</div></header>
<main><section class="summary"><h2>已符合客服建議，可跳過</h2><table><thead><tr><th>案例</th><th>問題</th><th>驗證重點</th></tr></thead><tbody>{pass_rows}</tbody></table></section>
<h2>逐案完整驗證內容</h2>{''.join(cards) or '<div class="summary">目前沒有案例。</div>'}</main></body></html>"""


def save(results: list[dict[str, Any]], json_path: Path, html_path: Path) -> None:
    json_path.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    html_path.write_text(render_report(results), encoding="utf-8")


def main() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    json_path = OUTPUT_DIR / f"feedback_api_check_20260727_0801_{stamp}.json"
    html_path = OUTPUT_DIR / f"feedback_api_check_20260727_0801_{stamp}.html"
    cases = load_cases()
    requested_case_ids = {
        int(value)
        for value in re.split(r"[\s,]+", os.getenv("FEEDBACK_CASE_IDS", "").strip())
        if value.isdigit()
    }
    if requested_case_ids:
        cases = [case for case in cases if int(case.get("case_no") or 0) in requested_case_ids]
    results: list[dict[str, Any]] = []
    started = time.perf_counter()
    for index, case in enumerate(cases, start=1):
        print(f"[{index}/{len(cases)}] #{case['case_no']:02d} {case['title']}", flush=True)
        result = run_case_backend(case, BACKEND_URL)
        result["evaluation"] = evaluate(result)
        results.append(result)
        save(results, json_path, html_path)
        print(
            f"  => {result['evaluation']['status']} | {result['duration_sec']} sec | "
            f"{'; '.join(result['evaluation']['reasons'])}",
            flush=True,
        )
    print(f"TOTAL_SEC={round(time.perf_counter() - started, 3)}", flush=True)
    print(f"JSON={json_path}", flush=True)
    print(f"HTML={html_path}", flush=True)


if __name__ == "__main__":
    main()
