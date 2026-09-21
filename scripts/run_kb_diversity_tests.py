from __future__ import annotations

import html
import json
import os
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

BACKEND_URL = os.getenv("KB_DIVERSITY_TEST_BACKEND", "http://127.0.0.1:8123")
OUTPUT_DIR = ROOT_DIR / "reports"


CASES: list[dict[str, Any]] = [
    {
        "title": "服務名稱常見錯字",
        "turns": [
            {
                "text": "熊大心是什麼？",
                "required": ["熊搭心", "電視電話"],
                "forbidden": ["一般理解", "無法確認"],
            }
        ],
    },
    {
        "title": "服務名稱距離過遠時確認",
        "turns": [
            {
                "text": "熊溫馨是什麼？",
                "required": ["熊搭心"],
                "required_any": ["指的是", "是否", "請問"],
            }
        ],
    },
    {
        "title": "WiFi 5 精準費用",
        "turns": [
            {
                "text": "WiFi 5 分享器一年多少錢？",
                "required": ["300"],
                "forbidden": ["所有設備都不能上網", "網路故障"],
            }
        ],
    },
    {
        "title": "居家智慧攝影機租用",
        "turns": [
            {
                "text": "居家智慧攝影機租一年多少錢？",
                "required": ["600"],
                "required_any": ["攝影機", "智慧鏡頭"],
            }
        ],
    },
    {
        "title": "優惠方案第一次詢問",
        "turns": [
            {
                "text": "爸氣獻禮有哪些主要優惠？",
                "required": ["爸氣獻禮"],
                "required_any": ["LINE TV", "POINT", "點數", "抽獎"],
            }
        ],
    },
    {
        "title": "優惠抽獎多輪追問",
        "turns": [
            {
                "text": "爸氣獻禮有抽獎嗎？",
                "required": ["抽獎"],
            },
            {
                "text": "第二波會抽什麼？",
                "required": ["車用無線充電器", "料理鍋", "加濕器"],
            },
        ],
    },
    {
        "title": "優惠指定速率與繳別",
        "turns": [
            {
                "text": "爸氣獻禮100M/100M年繳多少錢？",
                "required": ["100M/100M", "5,400"],
            }
        ],
    },
    {
        "title": "有線電視口語月費",
        "turns": [
            {
                "text": "大屯第四台一個月多少錢？",
                "required": ["550"],
                "forbidden": ["CATV"],
            }
        ],
    },
    {
        "title": "第三台機上盒收費",
        "turns": [
            {
                "text": "第三台機上盒要收哪些費用？",
                "required": ["1,200", "800"],
                "required_any": ["押金", "分機費"],
            }
        ],
    },
    {
        "title": "遙控器購買費用",
        "turns": [
            {
                "text": "一般遙控器壞了，買一支多少錢？",
                "required": ["300"],
                "required_any": ["遙控器", "臨櫃"],
            }
        ],
    },
    {
        "title": "低收入戶申請資料",
        "turns": [
            {
                "text": "低收入戶優惠需要準備什麼？",
                "required": ["低收入戶證明"],
                "required_any": ["門市", "臨櫃", "親自"],
            }
        ],
    },
    {
        "title": "世界盃口語頻道查詢",
        "turns": [
            {
                "text": "今年世足要轉哪幾台？",
                "required": ["CH07", "CH51", "CH66"],
            }
        ],
    },
    {
        "title": "紅利點數名稱與用途",
        "turns": [
            {
                "text": "你們的紅利點數可以做什麼？",
                "required": ["哈Point"],
                "required_any": ["購買", "抵扣", "服務費"],
            }
        ],
    },
    {
        "title": "LINE TV 裝置數量",
        "turns": [
            {
                "text": "LINE TV最多能登入幾台裝置？",
                "required": ["沒有", "上限"],
            }
        ],
    },
    {
        "title": "加值服務多輪承接",
        "turns": [
            {
                "text": "WiFi加值服務有哪些？",
                "required": ["WiFi 5", "WiFi 6"],
            },
            {
                "text": "那WiFi 5一年多少？",
                "required": ["300"],
                "forbidden": ["所有設備都不能上網", "網路故障"],
            },
        ],
    },
]


def normalized_contains(text: str, value: str) -> bool:
    compact_text = text.replace(",", "").replace("，", "").replace(" ", "")
    compact_value = value.replace(",", "").replace("，", "").replace(" ", "")
    return compact_value.lower() in compact_text.lower()


def evaluate(answer: str, turn: dict[str, Any]) -> tuple[bool, list[str]]:
    problems: list[str] = []
    for value in turn.get("required", []):
        if not normalized_contains(answer, value):
            problems.append(f"缺少：{value}")
    any_values = turn.get("required_any", [])
    if any_values and not any(normalized_contains(answer, value) for value in any_values):
        problems.append(f"至少應包含其一：{' / '.join(any_values)}")
    for value in turn.get("forbidden", []):
        if normalized_contains(answer, value):
            problems.append(f"不應出現：{value}")
    return not problems, problems


def get_backend_auth_headers(base_url: str) -> dict[str, str]:
    env_file = os.getenv("CUST_APP_ENV_FILE", ".env")
    config = dotenv_values(ROOT_DIR / env_file)
    header_name = str(config.get("API_AUTH_HEADER") or "X-API-Token").strip()
    name = str(os.getenv("KB_DIVERSITY_API_AUTH_NAME") or config.get("API_AUTH_NAME") or "").strip()
    password = str(
        os.getenv("KB_DIVERSITY_API_AUTH_PASSWORD")
        or config.get("API_AUTH_PASSWORD")
        or ""
    ).strip()
    if name and password:
        response = requests.post(
            f"{base_url.rstrip('/')}/api/auth/token",
            json={"name": name, "password": password},
            timeout=15,
        )
        if response.status_code == 200:
            payload = response.json()
            access_token = str(payload.get("access_token") or "").strip()
            response_header = str(payload.get("header_name") or header_name).strip()
            if access_token:
                return {response_header: access_token}

    fixed_token = str(config.get("API_AUTH_TOKEN") or "").strip()
    return {header_name: fixed_token} if fixed_token else {}


def run() -> tuple[list[dict[str, Any]], Path]:
    base_url = BACKEND_URL.rstrip("/")
    headers = get_backend_auth_headers(base_url)
    results: list[dict[str, Any]] = []
    for case_no, case in enumerate(CASES, start=1):
        user_id = f"test_web:kb-diversity-{case_no:02d}-{uuid.uuid4().hex[:8]}"
        requests.post(f"{base_url}/reset/{user_id}", headers=headers, timeout=20)
        case_result = {
            "case_no": case_no,
            "title": case["title"],
            "status": "PASS",
            "turns": [],
        }
        for turn_no, turn in enumerate(case["turns"], start=1):
            started = time.perf_counter()
            try:
                response = requests.post(
                    f"{base_url}/chat",
                    json={
                        "user_id": user_id,
                        "user_input": turn["text"],
                        "tv_cable": "tdtv",
                    },
                    headers=headers,
                    timeout=180,
                )
                response.raise_for_status()
                payload = response.json()
                answer = str(payload.get("ai_response") or "")
                passed, problems = evaluate(answer, turn)
                latency = payload.get("latency") or {}
            except Exception as exc:
                answer = ""
                passed = False
                problems = [f"API 錯誤：{exc}"]
                latency = {}
            if not passed:
                case_result["status"] = "FAIL"
            case_result["turns"].append(
                {
                    "turn": turn_no,
                    "question": turn["text"],
                    "answer": answer,
                    "status": "PASS" if passed else "FAIL",
                    "problems": problems,
                    "duration_sec": round(time.perf_counter() - started, 3),
                    "latency": latency,
                }
            )
        results.append(case_result)
        print(f"[{case_result['status']}] {case_no:02d} {case['title']}", flush=True)

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    json_path = OUTPUT_DIR / f"kb_diversity_api_test_{stamp}.json"
    html_path = OUTPUT_DIR / f"kb_diversity_api_test_{stamp}.html"
    json_path.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    html_path.write_text(render_html(results), encoding="utf-8")
    return results, html_path


def render_html(results: list[dict[str, Any]]) -> str:
    pass_count = sum(item["status"] == "PASS" for item in results)
    cards: list[str] = []
    for item in results:
        turns = []
        for turn in item["turns"]:
            issues = "".join(f"<li>{html.escape(problem)}</li>" for problem in turn["problems"])
            issue_block = f"<ul class='issues'>{issues}</ul>" if issues else ""
            turns.append(
                "<div class='turn'>"
                f"<div class='user'><b>使用者</b><br>{html.escape(turn['question'])}</div>"
                f"<div class='ai'><b>AI</b><br>{html.escape(turn['answer']).replace(chr(10), '<br>')}</div>"
                f"<div class='meta'>{turn['status']} · {turn['duration_sec']} 秒</div>{issue_block}"
                "</div>"
            )
        cards.append(
            f"<section class='card {item['status'].lower()}'>"
            f"<header><span>#{item['case_no']:02d}</span><h2>{html.escape(item['title'])}</h2>"
            f"<strong>{item['status']}</strong></header>{''.join(turns)}</section>"
        )
    return f"""<!doctype html>
<html lang="zh-Hant"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width">
<title>知識庫多樣化 API 測試</title><style>
:root{{--bg:#0b1119;--panel:#121c2a;--line:#334155;--text:#eef2f7;--muted:#9fb0c3;--user:#1d3f61;--ai:#1a2432;--pass:#35c982;--fail:#ff6b6b}}
*{{box-sizing:border-box}}body{{margin:0;background:var(--bg);color:var(--text);font:16px/1.65 system-ui,"Microsoft JhengHei",sans-serif}}
main{{width:min(1100px,94vw);margin:38px auto 80px}}h1{{margin:0 0 4px;font-size:32px;letter-spacing:0}}.summary{{color:var(--muted);margin-bottom:28px}}
.card{{border:1px solid var(--line);background:rgba(18,28,42,.92);margin:18px 0;border-radius:8px;overflow:hidden}}.card header{{display:flex;align-items:center;gap:12px;padding:16px 20px;border-bottom:1px solid var(--line)}}
.card header span{{color:var(--muted)}}.card h2{{font-size:19px;margin:0;flex:1;letter-spacing:0}}.pass header strong{{color:var(--pass)}}.fail header strong{{color:var(--fail)}}
.turn{{padding:20px}}.user,.ai{{max-width:86%;padding:13px 16px;border:1px solid var(--line);border-radius:8px;margin-bottom:13px}}.user{{margin-left:auto;background:var(--user)}}.ai{{background:var(--ai)}}
.meta{{font-size:13px;color:var(--muted)}}.issues{{color:var(--fail);margin:8px 0 0}}b{{color:white}}
</style></head><body><main><h1>知識庫多樣化 API 測試</h1><div class="summary">{pass_count} / {len(results)} 組通過 · 實際呼叫 {html.escape(BACKEND_URL)} 對話 API</div>{''.join(cards)}</main></body></html>"""


if __name__ == "__main__":
    test_results, report_path = run()
    passed = sum(item["status"] == "PASS" for item in test_results)
    print(f"SUMMARY {passed}/{len(test_results)}", flush=True)
    print(f"REPORT {report_path}", flush=True)
