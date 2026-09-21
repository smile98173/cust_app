from __future__ import annotations

import argparse
import csv
import html
import json
import os
import re
import time
import uuid
from datetime import datetime
from pathlib import Path
import sys
from typing import Any

import requests
from bs4 import BeautifulSoup

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from app.handlers import chat_handler
from app.handlers.chat_handler import handle_chat_message
from app.services.company_profile import apply_company_to_memory
from app.services.memory_service import default_memory
from app.services.model_manager import ModelManager


DEFAULT_SOURCE = Path(
    r"C:\Users\user\.codex\visualizations\2026\06\22"
    r"\019eecc9-bf14-73a2-8cf4-6cb9e5326a71\feedback-dialog-cases-full-standalone.html"
)
DEFAULT_OUTPUT_DIR = Path(
    r"C:\Users\user\.codex\visualizations\2026\06\22"
    r"\019eecc9-bf14-73a2-8cf4-6cb9e5326a71"
)


def text_of(node) -> str:
    if not node:
        return ""
    return node.get_text("\n", strip=True)


def esc(value: Any) -> str:
    return html.escape(str(value or "")).replace("\n", "<br>")


def load_inner_html(path: Path) -> BeautifulSoup:
    outer = BeautifulSoup(path.read_text(encoding="utf-8"), "html.parser")
    iframe = outer.find("iframe")
    if iframe and iframe.get("srcdoc"):
        return BeautifulSoup(iframe["srcdoc"], "html.parser")
    return outer


def extract_company_code(article) -> str:
    clue = text_of(article.select_one(".review-panel:nth-of-type(2)"))
    match = re.search(r"公司\s*[:：]\s*([A-Za-z0-9_]+)", clue)
    if match:
        return match.group(1).strip()
    return "tdtv"


def extract_cases(source: Path) -> list[dict[str, Any]]:
    soup = load_inner_html(source)
    cases: list[dict[str, Any]] = []
    for index, article in enumerate(soup.select("article.case-card"), start=1):
        messages = []
        for row in article.select(".bubble-row"):
            classes = row.get("class") or []
            role = "user" if "user" in classes else "assistant"
            body = text_of(row.select_one(".bubble-body"))
            if body:
                messages.append({"role": role, "content": body})

        user_turns = [item["content"] for item in messages if item.get("role") == "user"]
        suggestion_panel = article.select_one(".review-panel")
        suggestion = text_of(suggestion_panel.select_one("p") if suggestion_panel else None)

        cases.append({
            "case_no": index,
            "date": article.get("data-date") or "",
            "feedback_type": article.get("data-type") or "",
            "category": article.get("data-cat") or "",
            "title": text_of(article.select_one("h2")),
            "suggestion": suggestion,
            "company_code": extract_company_code(article),
            "original_messages": messages,
            "user_turns": user_turns,
        })
    return cases


def load_json_messages(value: str) -> list[dict[str, Any]]:
    try:
        parsed = json.loads(value or "[]")
    except Exception:
        return []
    if not isinstance(parsed, list):
        return []
    messages: list[dict[str, Any]] = []
    for item in parsed:
        if not isinstance(item, dict):
            continue
        role = str(item.get("role") or "").strip().lower()
        content = str(item.get("content") or "").strip()
        if role in {"user", "assistant"} and content:
            message = {"role": role, "content": content}
            if item.get("response_time_sec") is not None:
                message["response_time_sec"] = item.get("response_time_sec")
            messages.append(message)
    return messages


def extract_cases_from_feedback_csv(paths: list[Path]) -> list[dict[str, Any]]:
    cases: list[dict[str, Any]] = []
    for path in paths:
        with path.open("r", newline="", encoding="utf-8-sig") as handle:
            reader = csv.DictReader(handle)
            for row in reader:
                messages = load_json_messages(row.get("conversation_json") or "")
                if not messages:
                    if row.get("user_message"):
                        messages.append({"role": "user", "content": row.get("user_message")})
                    if row.get("ai_response"):
                        messages.append({"role": "assistant", "content": row.get("ai_response")})

                user_turns = [item["content"] for item in messages if item.get("role") == "user"]
                if not user_turns and row.get("user_message"):
                    user_turns = [str(row.get("user_message") or "")]

                feedback_id = row.get("feedback_id") or f"CSV-{len(cases) + 1:03d}"
                created_at = row.get("created_at") or ""
                user_message = row.get("user_message") or (user_turns[-1] if user_turns else "")
                cases.append({
                    "case_no": len(cases) + 1,
                    "feedback_id": feedback_id,
                    "date": created_at,
                    "feedback_type": row.get("feedback_type") or "",
                    "category": row.get("feedback_type") or "",
                    "title": f"{feedback_id}｜{user_message}",
                    "suggestion": row.get("suggestion") or "",
                    "company_code": row.get("company_code") or row.get("tv_cable") or "tdtv",
                    "company": row.get("company") or "",
                    "source_file": str(path),
                    "original_messages": messages,
                    "user_turns": user_turns,
                })
    return cases


def run_case(case: dict[str, Any], model_manager: ModelManager) -> dict[str, Any]:
    user_id = f"feedback-case-{case['case_no']:02d}-{uuid.uuid4().hex[:8]}"
    company_code = case.get("company_code") or "tdtv"
    memory = apply_company_to_memory(default_memory(), company_code)
    history: list[dict[str, str]] = []
    rerun_messages: list[dict[str, Any]] = []
    turn_results: list[dict[str, Any]] = []
    started = time.perf_counter()

    result: dict[str, Any] = {
        **case,
        "user_id": user_id,
        "status": "RAN",
        "error": "",
        "rerun_messages": rerun_messages,
        "turn_results": turn_results,
        "final_memory": {},
        "duration_sec": 0.0,
    }

    try:
        for turn_index, user_text in enumerate(case.get("user_turns") or [], start=1):
            rerun_messages.append({"role": "user", "content": user_text})
            response = handle_chat_message(
                user_id=user_id,
                user_text=user_text,
                memory=memory,
                history=history,
                llm=model_manager.get_llm(),
                rag_summary_llm=model_manager.get_llm(task="rag_summary"),
                persist=False,
            )
            ai_response = str(response.get("ai_response") or "")
            memory = response.get("memory") or memory
            history.append({"role": "user", "content": user_text})
            history.append({"role": "assistant", "content": ai_response})
            rerun_messages.append({
                "role": "assistant",
                "content": ai_response,
                "response_time_sec": round(float((response.get("latency") or {}).get("total") or 0), 3),
            })
            turn_results.append({
                "turn": turn_index,
                "router": response.get("router") or {},
                "plan": response.get("plan") or {},
                "latency": response.get("latency") or {},
            })
        result["final_memory"] = memory
    except Exception as exc:
        result["status"] = "ERROR"
        result["error"] = str(exc)
    finally:
        result["duration_sec"] = round(time.perf_counter() - started, 3)
    return result


def load_env_values(path: str) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path:
        return values
    env_path = Path(path)
    if not env_path.exists():
        return values
    for raw_line in env_path.read_text(encoding="utf-8-sig").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def build_backend_headers(backend_url: str, auth_env_file: str = "") -> dict[str, str]:
    env_values = load_env_values(auth_env_file)
    auth_name = os.getenv("API_AUTH_NAME") or env_values.get("API_AUTH_NAME") or ""
    auth_password = os.getenv("API_AUTH_PASSWORD") or env_values.get("API_AUTH_PASSWORD") or ""
    auth_header = os.getenv("API_AUTH_HEADER") or env_values.get("API_AUTH_HEADER") or "X-API-Token"
    fixed_token = os.getenv("API_AUTH_TOKEN") or env_values.get("API_AUTH_TOKEN") or ""

    if fixed_token:
        return {auth_header: fixed_token}
    if not auth_name or not auth_password:
        return {}

    token_resp = requests.post(
        f"{backend_url.rstrip('/')}/api/auth/token",
        json={"name": auth_name, "password": auth_password},
        timeout=30,
    )
    if token_resp.status_code >= 400:
        raise RuntimeError(f"API token request failed: HTTP {token_resp.status_code}: {token_resp.text}")
    token_data = token_resp.json()
    token = str(token_data.get("access_token") or "").strip()
    header_name = str(token_data.get("header_name") or auth_header or "X-API-Token").strip()
    return {header_name: token} if token else {}


def run_case_backend(
    case: dict[str, Any],
    backend_url: str,
    chat_timeout: int = 120,
    headers: dict[str, str] | None = None,
    api_mode: str = "internal",
) -> dict[str, Any]:
    if api_mode == "external":
        user_id = f"feedback-case-{case['case_no']:02d}-{uuid.uuid4().hex[:8]}"
        reset_user_id = f"web:{user_id}"
    else:
        user_id = f"test_web:feedback-case-{case['case_no']:02d}-{uuid.uuid4().hex[:8]}"
        reset_user_id = user_id
    company_code = case.get("company_code") or "tdtv"
    history: list[dict[str, str]] = []
    rerun_messages: list[dict[str, Any]] = []
    turn_results: list[dict[str, Any]] = []
    started = time.perf_counter()
    base_url = backend_url.rstrip("/")
    request_headers = dict(headers or {})

    result: dict[str, Any] = {
        **case,
        "user_id": user_id,
        "runner": f"backend_api:{api_mode}",
        "backend_url": base_url,
        "status": "RAN",
        "error": "",
        "rerun_messages": rerun_messages,
        "turn_results": turn_results,
        "final_memory": {},
        "duration_sec": 0.0,
    }

    try:
        reset_resp = requests.post(f"{base_url}/reset/{reset_user_id}", headers=request_headers, timeout=30)
        if reset_resp.status_code >= 400:
            result["reset_warning"] = reset_resp.text

        for turn_index, user_text in enumerate(case.get("user_turns") or [], start=1):
            rerun_messages.append({"role": "user", "content": user_text})
            turn_started = time.perf_counter()
            if api_mode == "external":
                endpoint = f"{base_url}/api/v1/chat"
                payload = {
                    "request_id": f"feedback-rerun-{case['case_no']:02d}-{turn_index}",
                    "user_id": user_id,
                    "is_logged_in": False,
                    "company_code": company_code,
                    "msg": user_text,
                }
            else:
                endpoint = f"{base_url}/chat"
                payload = {
                    "user_id": user_id,
                    "user_input": user_text,
                    "tv_cable": company_code,
                }
            resp = requests.post(
                endpoint,
                headers=request_headers,
                json=payload,
                timeout=chat_timeout,
            )
            request_time_sec = round(time.perf_counter() - turn_started, 3)
            if resp.status_code >= 400:
                raise RuntimeError(f"HTTP {resp.status_code}: {resp.text}")
            response = resp.json()
            ai_response = str(response.get("msg") if api_mode == "external" else response.get("ai_response") or "")
            history.append({"role": "user", "content": user_text})
            history.append({"role": "assistant", "content": ai_response})
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
            f"{base_url}/state/{reset_user_id}",
            headers=request_headers,
            params={"tv_cable": company_code},
            timeout=30,
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
            f"""
            <div class="bubble-row {role}">
              <div class="avatar">{label}</div>
              <div class="bubble {role}">
                <div class="bubble-head">{label}</div>
                <div class="bubble-body">{esc(item.get("content"))}</div>
                {meta}
              </div>
            </div>
            """
        )
    return "".join(parts)


def render_turn_debug(turn_results: list[dict[str, Any]]) -> str:
    rows = []
    for item in turn_results:
        router = item.get("router") or {}
        plan = item.get("plan") or {}
        latency = item.get("latency") or {}
        if not router and not plan:
            rows.append(
                "<tr>"
                f"<td>{esc(item.get('turn'))}</td>"
                f"<td>{esc(item.get('decision_type'))}</td>"
                f"<td>{esc(', '.join(str((action or {}).get('type') or action) for action in (item.get('actions') or [])))}</td>"
                f"<td>{esc(item.get('company_code'))}</td>"
                f"<td>{esc(round(float(item.get('request_time_sec') or 0), 3))}</td>"
                f"<td>{esc(round(float((latency or {}).get('total') or item.get('response_time_sec') or 0), 3))}</td>"
                "</tr>"
            )
            continue
        rows.append(
            "<tr>"
            f"<td>{esc(item.get('turn'))}</td>"
            f"<td>{esc(router.get('route'))}</td>"
            f"<td>{esc(router.get('intent'))}</td>"
            f"<td>{esc(plan.get('decision_type'))}</td>"
            f"<td>{esc(plan.get('tool_name'))}</td>"
            f"<td>{esc(round(float(latency.get('total') or 0), 3))}</td>"
            "</tr>"
        )
    if not rows:
        return '<div class="muted">沒有 turn debug。</div>'
    if turn_results and not (turn_results[0].get("router") or turn_results[0].get("plan")):
        return (
            '<table class="debug-table"><thead><tr>'
            '<th>Turn</th><th>Decision</th><th>Actions</th><th>Company</th><th>Request 秒</th><th>Total 秒</th>'
            '</tr></thead><tbody>'
            + "".join(rows)
            + '</tbody></table>'
        )
    return (
        '<table class="debug-table"><thead><tr>'
        '<th>Turn</th><th>Route</th><th>Intent</th><th>Decision</th><th>Tool</th><th>Total 秒</th>'
        '</tr></thead><tbody>'
        + "".join(rows)
        + '</tbody></table>'
    )


def render_report(results: list[dict[str, Any]], source: Path) -> str:
    total = len(results)
    errors = sum(1 for item in results if item.get("status") == "ERROR")
    upstream = sum(1 for item in results if item.get("status") == "UPSTREAM")
    multi_turn = sum(1 for item in results if len(item.get("user_turns") or []) >= 2)
    generated_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    runner = results[0].get("runner") if results else "direct_core"
    backend_url = results[0].get("backend_url") if results else ""
    cards = []
    for item in results:
        original_user_turns = len(item.get("user_turns") or [])
        source_hint = item.get("source_file") or str(source)
        cards.append(
            f"""
            <article class="case-card" data-status="{esc(item.get('status'))}">
              <header class="case-head">
                <div>
                  <div class="case-kicker">{esc(item.get('date'))}｜#{int(item.get('case_no')):02d}｜{esc(item.get('feedback_type'))}</div>
                  <h2>{esc(item.get('title'))}</h2>
                </div>
                <div class="status {esc(item.get('status'))}">{esc(item.get('status'))}</div>
              </header>
              <div class="meta-grid">
                <div><span>分類</span><strong>{esc(item.get('category'))}</strong></div>
                <div><span>公司</span><strong>{esc(item.get('company_code'))}</strong></div>
                <div><span>User turns</span><strong>{original_user_turns}</strong></div>
                <div><span>重跑耗時</span><strong>{esc(item.get('duration_sec'))} 秒</strong></div>
              </div>
              <div class="sub">來源檔：{esc(source_hint)}</div>
              <section class="conversation">
                <div class="section-title">重跑後完整多輪對話</div>
                {render_messages(item.get('rerun_messages') or [])}
              </section>
              <section class="review-panel">
                <div class="section-title">客服原始回饋建議</div>
                <p>{esc(item.get('suggestion'))}</p>
              </section>
              <details>
                <summary>原始對話與每輪路由資訊</summary>
                <div class="section-title">原始對話</div>
                {render_messages(item.get('original_messages') or [])}
                <div class="section-title">重跑路由</div>
                {render_turn_debug(item.get('turn_results') or [])}
                <pre>{esc(json.dumps(item.get('final_memory') or {}, ensure_ascii=False, indent=2))}</pre>
              </details>
              {f'<div class="upstream-box">{esc(item.get("review_note"))}</div>' if item.get("review_note") else ''}
              {f'<div class="error-box">{esc(item.get("error"))}</div>' if item.get("error") else ''}
            </article>
            """
        )

    return f"""<!doctype html>
<html lang="zh-Hant">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>客服回饋案例重跑結果</title>
<style>
:root {{
  color-scheme: dark;
  --bg: #0b0f16;
  --panel: #151a23;
  --panel-2: #1b2230;
  --text: #f8fafc;
  --muted: #a8b3c7;
  --line: #303849;
  --user: #12345a;
  --ai: #1b202a;
  --accent: #38bdf8;
  --ok: #22c55e;
  --bad: #fb7185;
}}
* {{ box-sizing: border-box; }}
body {{
  margin: 0;
  background: var(--bg);
  color: var(--text);
  font-family: "Microsoft JhengHei", "Noto Sans TC", Arial, sans-serif;
  line-height: 1.65;
}}
header.page-head {{
  position: sticky;
  top: 0;
  z-index: 2;
  padding: 22px 28px;
  background: rgba(11, 15, 22, 0.94);
  border-bottom: 1px solid var(--line);
  backdrop-filter: blur(10px);
}}
h1 {{ margin: 0 0 6px; font-size: 28px; }}
.sub {{ color: var(--muted); }}
main {{ width: min(1180px, calc(100% - 32px)); margin: 24px auto; }}
.stats {{ display: flex; gap: 12px; flex-wrap: wrap; margin-top: 14px; }}
.stat {{ border: 1px solid var(--line); background: var(--panel); border-radius: 8px; padding: 9px 12px; }}
.stat strong {{ display: block; font-size: 20px; }}
.stat span {{ color: var(--muted); font-size: 13px; }}
.case-card {{
  border: 1px solid var(--line);
  background: var(--panel);
  border-radius: 10px;
  margin-bottom: 18px;
  padding: 18px;
}}
.case-head {{ display: flex; justify-content: space-between; gap: 16px; align-items: flex-start; }}
.case-kicker {{ color: var(--accent); font-size: 13px; font-weight: 800; }}
h2 {{ margin: 4px 0 0; font-size: 22px; }}
.status {{ border-radius: 999px; padding: 4px 10px; font-weight: 800; }}
.status.PASS {{ background: rgba(34,197,94,.15); color: var(--ok); }}
.status.RAN {{ background: rgba(59,130,246,.15); color: #60a5fa; }}
.status.UPSTREAM {{ background: rgba(245,158,11,.18); color: #fbbf24; }}
.status.ERROR {{ background: rgba(251,113,133,.15); color: var(--bad); }}
.meta-grid {{ display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 10px; margin: 14px 0; }}
.meta-grid div {{ background: var(--panel-2); border: 1px solid var(--line); border-radius: 8px; padding: 8px 10px; }}
.meta-grid span {{ display:block; color: var(--muted); font-size: 12px; }}
.section-title {{ margin: 16px 0 8px; font-weight: 900; }}
.conversation {{ border: 1px solid var(--line); border-radius: 10px; padding: 12px; background: #0f141d; }}
.bubble-row {{ display: grid; gap: 10px; align-items: start; margin: 10px 0; }}
.bubble-row.ai {{ grid-template-columns: 42px minmax(0, 1fr); }}
.bubble-row.user {{ grid-template-columns: minmax(0, 1fr) 42px; }}
.bubble-row.user .avatar {{ grid-column: 2; background: #ff0040; }}
.bubble-row.user .bubble {{ grid-column: 1; grid-row: 1; justify-self: end; background: var(--user); }}
.bubble-row.ai .avatar {{ background: #ff7a21; }}
.avatar {{ width: 42px; height: 42px; border-radius: 8px; display:flex; align-items:center; justify-content:center; font-weight:900; font-size: 12px; }}
.bubble {{ max-width: 82%; border-radius: 8px; padding: 10px 12px; background: var(--ai); border: 1px solid var(--line); }}
.bubble-head {{ color: var(--muted); font-size: 12px; font-weight: 900; margin-bottom: 3px; }}
.bubble-body {{ white-space: normal; }}
.bubble-meta {{ color: var(--muted); font-size: 12px; margin-top: 5px; }}
.review-panel {{ margin-top: 12px; border-left: 4px solid var(--accent); background: #101927; border-radius: 8px; padding: 2px 14px 12px; }}
details {{ margin-top: 12px; color: var(--muted); }}
summary {{ cursor: pointer; font-weight: 800; }}
.debug-table {{ width: 100%; border-collapse: collapse; margin: 8px 0; }}
.debug-table th, .debug-table td {{ border-bottom: 1px solid var(--line); padding: 7px; text-align: left; vertical-align: top; }}
pre {{ white-space: pre-wrap; background: #05070b; color: #d8e1f3; padding: 12px; border-radius: 8px; overflow-x: auto; }}
.error-box {{ margin-top: 12px; background: rgba(251,113,133,.12); color: var(--bad); border: 1px solid rgba(251,113,133,.35); padding: 10px; border-radius: 8px; }}
.upstream-box {{ margin-top: 12px; background: rgba(245,158,11,.10); color: #fde68a; border: 1px solid rgba(245,158,11,.35); padding: 10px; border-radius: 8px; }}
.muted {{ color: var(--muted); }}
@media (max-width: 820px) {{
  .meta-grid {{ grid-template-columns: 1fr 1fr; }}
  .bubble {{ max-width: 92%; }}
}}
</style>
</head>
<body>
<header class="page-head">
  <h1>客服回饋案例重跑結果</h1>
  <div class="sub">來源：{esc(source)}｜產生時間：{esc(generated_at)}</div>
  <div class="sub">測試模式：{esc(runner or "direct_core")}{f"｜後端：{esc(backend_url)}" if backend_url else ""}</div>
  <div class="stats">
    <div class="stat"><strong>{total}</strong><span>總案例</span></div>
    <div class="stat"><strong>{multi_turn}</strong><span>來源含 2+ 輪 User</span></div>
    <div class="stat"><strong>{upstream}</strong><span>上游 API 待修</span></div>
    <div class="stat"><strong>{errors}</strong><span>執行錯誤</span></div>
  </div>
</header>
<main>
  {''.join(cards)}
</main>
</body>
</html>"""


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", default=str(DEFAULT_SOURCE))
    parser.add_argument("--csv-files", default="", help="Comma-separated feedback CSV paths")
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--case", default="", help="Comma-separated case numbers, e.g. 1,2,7")
    parser.add_argument("--upstream-case", default="", help="Cases blocked by an upstream dependency, e.g. 11")
    parser.add_argument("--backend-url", default="", help="Use a running backend API, e.g. http://127.0.0.1:8123")
    parser.add_argument("--api-mode", choices=["internal", "external"], default="internal")
    parser.add_argument("--auth-env-file", default="", help="Env file for API_AUTH_NAME/API_AUTH_PASSWORD/API_AUTH_HEADER")
    parser.add_argument("--chat-timeout", type=int, default=120, help="Seconds to wait for each backend /chat turn")
    args = parser.parse_args()

    source = Path(args.source)
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    if args.csv_files:
        csv_paths = [Path(value.strip()) for value in args.csv_files.split(",") if value.strip()]
        cases = extract_cases_from_feedback_csv(csv_paths)
        source = Path(";".join(str(path) for path in csv_paths))
    else:
        cases = extract_cases(source)
    if args.case:
        allowed = {int(value.strip()) for value in args.case.split(",") if value.strip()}
        cases = [item for item in cases if int(item["case_no"]) in allowed]
    if args.limit > 0:
        cases = cases[:args.limit]

    model_manager = None
    backend_headers: dict[str, str] = {}
    if not args.backend_url:
        # Keep the direct-core runner from writing latency rows while still using the same core flow.
        chat_handler.log_chat_latency = lambda **_kwargs: None
        model_manager = ModelManager()
    elif args.api_mode == "external":
        backend_headers = build_backend_headers(args.backend_url, args.auth_env_file)
    results = []
    for index, case in enumerate(cases, start=1):
        print(
            f"[{index}/{len(cases)}] #{case['case_no']:02d} "
            f"{case.get('title')} ({len(case.get('user_turns') or [])} user turns)",
            flush=True,
        )
        if args.backend_url:
            results.append(
                run_case_backend(
                    case,
                    args.backend_url,
                    chat_timeout=args.chat_timeout,
                    headers=backend_headers,
                    api_mode=args.api_mode,
                )
            )
        else:
            results.append(run_case(case, model_manager))

    upstream_cases = {int(value.strip()) for value in args.upstream_case.split(",") if value.strip()}
    for result in results:
        if int(result["case_no"]) in upstream_cases and result.get("status") != "ERROR":
            result["status"] = "UPSTREAM"
            result["review_note"] = (
                "此案需由上游 CUST API 修正客戶編號停用狀態的判斷；"
                "本專案僅呈現 API 原始回覆，不在回覆層覆寫或猜測帳戶狀態。"
            )

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    json_path = output_dir / f"feedback_dialog_rerun_{stamp}.json"
    html_path = output_dir / f"feedback_dialog_rerun_{stamp}.html"
    json_path.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    html_path.write_text(render_report(results, source), encoding="utf-8")

    print(f"JSON={json_path}", flush=True)
    print(f"HTML={html_path}", flush=True)


if __name__ == "__main__":
    main()
