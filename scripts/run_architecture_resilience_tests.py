from __future__ import annotations

import argparse
import html
import json
import os
import re
import time
import uuid
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any

import requests


ROOT_DIR = Path(__file__).resolve().parent.parent
OUTPUT_DIR = ROOT_DIR / "reports"


def group(*terms: str) -> tuple[str, ...]:
    return tuple(terms)


def check(
    *must: tuple[str, ...],
    must_not: tuple[str, ...] = (),
    review: bool = False,
    note: str = "",
) -> dict[str, Any]:
    return {"must": must, "must_not": must_not, "review": review, "note": note}


def build_cases() -> list[dict[str, Any]]:
    cases: list[dict[str, Any]] = []

    def add(
        case_id: str,
        category: str,
        title: str,
        company_code: str,
        turns: list[str],
        checks: list[dict[str, Any]],
        risk: str,
    ) -> None:
        cases.append(
            {
                "case_id": case_id,
                "category": category,
                "title": title,
                "company_code": company_code,
                "turns": turns,
                "checks": checks,
                "risk": risk,
            }
        )

    # A. The location named in the question must override the remembered/default company.
    region_cases = [
        ("G01", "tdtv", "永康區可以裝網路嗎？", ("永康", "新永安"), ("大屯",)),
        ("G02", "hya", "大里區可以裝有線電視嗎？", ("大里", "大屯"), ("新永安",)),
        ("G03", "tdtv", "朋友住水上，想裝第四台。", ("水上", "大揚"), ("大屯",)),
        ("G04", "hya", "爸媽在斗六，可以裝網路嗎？", ("斗六", "佳聯"), ("新永安",)),
        ("G05", "cltv", "北港區想申請有線電視。", ("北港",), ("佳聯",)),
        ("G06", "pktv", "太平區能裝寬頻嗎？", ("太平", "大屯"), ("北港",)),
        ("G07", "tdtv", "沙鹿可以申請第四台嗎？", ("沙鹿", "台灣佳光"), ("大屯",)),
        ("G08", "wctv", "西屯區可以裝網路嗎？", ("西屯", "佳光市區"), ("台灣佳光",)),
        ("G09", "toplight", "草屯能申請寬頻嗎？", ("草屯", "中投"), ("佳光市區",)),
        ("G10", "cnt", "新化可以裝有線電視嗎？", ("新化", "新永安"), ("中投",)),
        ("G11", "hya", "朴子可以裝網路嗎？", ("朴子", "大揚"), ("新永安",)),
        ("G12", "tdtv", "我住大里，想幫台南永康的爸媽問能不能裝網路。", ("永康", "新永安"), ()),
        ("G14", "tdtv", "新永安永康區可以裝網路嗎？", ("永康", "新永安"), ("大屯",)),
        ("G15", "hya", "那北港能不能裝第四台？", ("北港",), ("新永安",)),
    ]
    for case_id, company, question, expected, forbidden in region_cases:
        add(
            case_id,
            "跨區裝機判斷",
            f"問題中的地區優先：{question}",
            company,
            [question],
            [check(group(*expected), must_not=tuple(forbidden))],
            "若仍綁定預設系統台，會錯誤判斷可裝區域。",
        )
    add(
        "G13",
        "跨區裝機判斷",
        "同時出現兩個服務地區時不可擅自選一個",
        "tdtv",
        ["大里和永康哪裡可以裝網路？"],
        [check(group("大里"), group("永康"), group("哪一個", "兩個", "都", "分別"), review=True)],
        "多地區問題應比較或澄清，不可沿用記憶中的系統台。",
    )
    add(
        "G16",
        "跨區裝機判斷",
        "未知服務區不可捏造可裝資訊",
        "tdtv",
        ["台北市可以裝你們網路嗎？"],
        [check(group("台北", "服務範圍", "無法確認", "客服"), must_not=("可以安裝",))],
        "目前資料沒有台北系統台，不應直接承諾可安裝。",
    )

    # B. Explicitly named companies must override the channel default for knowledge retrieval.
    company_cases = [
        ("C01", "tdtv", "新永安第四台月租多少？", ("新永安", "540")),
        ("C02", "hya", "大揚有線電視月租多少？", ("大揚", "555")),
        ("C03", "tdtv", "大屯第四台一個月多少？", ("大屯", "550")),
        ("C04", "tdtv", "北港 B 套餐有哪些頻道？", ("北港", "Discovery")),
        ("C05", "tdtv", "佳聯的低收入戶優惠有哪些？", ("低收入", "裝機費")),
        ("C06", "tdtv", "台灣佳光有哪些 300M 優惠？", ("300M", "台灣佳光")),
        ("C07", "hya", "大屯爸氣獻禮活動內容？", ("爸氣獻禮", "LINE FRIENDS")),
        ("C08", "tdtv", "大揚遙控器多少錢？", ("遙控器", "300")),
    ]
    for case_id, company, question, expected in company_cases:
        add(
            case_id,
            "明確系統台覆寫",
            question,
            company,
            [question],
            [check(*(group(term) for term in expected), review=case_id in {"C05", "C06"})],
            "明確指定其他公司時，不可只查目前 LINE／測試系統台。",
        )

    # C. Common knowledge bases are separated into central and Chiayi/Tainan scopes.
    common_cases = [
        (
            "K01",
            "tdtv",
            "IBON 要怎麼繳第四台費用？",
            (group("ibon"), group("7-11", "7-Eleven")),
            (),
            False,
        ),
        (
            "K02",
            "hya",
            "我想用信用卡繳第四台費用。",
            (group("信用卡"), group("線上繳費")),
            (),
            False,
        ),
        (
            "K03",
            "tdtv",
            "熊大心是什麼？",
            (group("熊搭心"), group("電視電話")),
            (),
            False,
        ),
        (
            "K04",
            "hya",
            "熊搭心是什麼？",
            (group("查不到", "未提供", "無法確認", "資料"),),
            ("瑪帛用戶", "瑪帛好友", "瑪帛夥伴", "電視電話"),
            False,
        ),
        (
            "K05",
            "tdtv",
            "WiFi 5 分享器一年多少錢？",
            (group("WiFi 5"), group("300")),
            (),
            False,
        ),
        (
            "K06",
            "hya",
            "WiFi 5 分享器一年多少錢？",
            (group("查不到", "未提供", "無法確認", "資料"),),
            ("WiFi 5 系列分享器：月均優惠", "年繳 300", "年繳300"),
            False,
        ),
        (
            "K07",
            "tdtv",
            "有線電視要退租需要帶什麼證件？",
            (group("退租"), group("身分證", "身份證")),
            (),
            False,
        ),
        (
            "K08",
            "hya",
            "遙控器可以送到府嗎？",
            (group("遙控器"), group("到府")),
            (),
            True,
        ),
    ]
    for case_id, company, question, expected_groups, forbidden, manual in common_cases:
        add(
            case_id,
            "通用知識庫區隔",
            question,
            company,
            [question],
            [check(*expected_groups, must_not=forbidden, review=manual)],
            "需確認通用-中區與通用-嘉南區是否正確套用，且不跨區洩漏規則。",
        )

    # D. Promotions and promotion detail follow-ups.
    promotion_cases = [
        ("P01", "八月有什麼優惠活動？", ("爸氣獻禮",)),
        ("P02", "爸氣獻禮的抽獎內容是什麼？", ("爸氣獻禮", "LINE FRIENDS")),
        ("P03", "爸氣獻禮的裝機費和設備押金？", ("裝機費", "押金")),
        ("P04", "好視成雙 NO8 有什麼贈品？", ("好視成雙", "贈")),
        ("P05", "飆網守護家 B2606 的 300M 費用？", ("B2606", "300M", "1,797")),
        ("P06", "低收入戶 500M 用一年多少錢？", ("低收入", "500M", "6,000")),
        ("P07", "台灣佳光八月優惠活動？", ("台灣佳光", "活動")),
        ("P08", "佳聯八月優惠活動？", ("佳聯", "優惠")),
    ]
    for case_id, question, expected in promotion_cases:
        company = "wctv" if case_id == "P07" else "cltv" if case_id == "P08" else "tdtv"
        add(
            case_id,
            "優惠活動檢索",
            question,
            company,
            [question],
            [check(*(group(term) for term in expected), review=case_id in {"P03", "P07", "P08"})],
            "泛稱優惠時應命中完整方案，不可只抓贈品或 LINE TV 零碎片段。",
        )

    # E. Multi-turn context must persist the intended object and allow explicit switches.
    flows = [
        (
            "F01",
            "好視成雙 NO8 多輪追問",
            "tdtv",
            ["好視成雙 NO8 有哪些方案？", "贈品呢？", "違約金多少？"],
            [
                check(group("好視成雙", "NO8")),
                check(group("贈", "家電", "POINT", "LINE TV")),
                check(group("違約金")),
            ],
        ),
        (
            "F02",
            "爸氣獻禮多輪追問",
            "tdtv",
            ["爸氣獻禮內容？", "抽獎資格呢？", "設備押金多少？"],
            [check(group("爸氣獻禮")), check(group("抽獎", "資格")), check(group("押金"))],
        ),
        (
            "F03",
            "WiFi 加值費用連續追問不得誤入故障排錯",
            "tdtv",
            ["WiFi 加值服務有哪些？", "WiFi 5 一年多少？", "那 WiFi 6 呢？"],
            [
                check(
                    group("WiFi 5", "Wi-Fi 5", "Wi‑Fi 5"),
                    group("WiFi 6", "Wi-Fi 6", "Wi‑Fi 6"),
                ),
                check(group("300"), must_not=("所有設備都不能上網", "數據機燈號")),
                check(group("600"), must_not=("所有設備都不能上網", "數據機燈號")),
            ],
        ),
        (
            "F04",
            "熊搭心服務多輪追問",
            "tdtv",
            ["熊搭心是什麼？", "一年多少？", "可以打多久電話？"],
            [check(group("熊搭心")), check(group("年繳", "一年")), check(group("120", "無限"), review=True)],
        ),
        (
            "F05",
            "同一對話切換指定系統台",
            "tdtv",
            ["新永安第四台月租多少？", "那大揚呢？"],
            [check(group("新永安"), group("540")), check(group("大揚"), group("555"))],
        ),
        (
            "F06",
            "同一對話切換裝機地區",
            "tdtv",
            ["永康能裝網路嗎？", "那大里呢？"],
            [check(group("永康", "新永安")), check(group("大里", "大屯"))],
        ),
        (
            "F07",
            "指定其他系統台後追問方案速率",
            "hya",
            ["大屯有哪些優惠？", "500M 呢？"],
            [check(group("大屯", "優惠")), check(group("500M"), must_not=("新永安",))],
        ),
        (
            "F08",
            "網路排錯需前進且不可死迴圈",
            "tdtv",
            ["網路不穩。", "手機和電腦都不穩。", "重開後還是一樣。", "還是沒恢復。"],
            [
                check(group("網路", "數據機", "設備")),
                check(group("數據機", "線路", "燈號"), must_not=("目前遇到的是電視、網路",)),
                check(group("燈號", "線路", "報修", "客服"), must_not=("手機和電腦都",)),
                check(group("報修", "客服", "維修"), must_not=("請重新開機",)),
            ],
        ),
    ]
    for case_id, title, company, turns, checks in flows:
        add(case_id, "多輪上下文", title, company, turns, checks, "需維持主題、接受明確切換，並避免重複同一步驟。")

    # F. Misspellings, ambiguity and internal terminology.
    ambiguous_cases = [
        ("A01", "熊打心是什麼？", check(group("熊搭心"))),
        ("A02", "熊溫馨是什麼？", check(group("熊搭心"), group("是否", "指的是", "您說的"))),
        ("A03", "加值服務有哪些？", check(group("LINE TV", "WiFi", "攝影機", "熊搭心"))),
        ("A04", "STB 第三台多少錢？", check(group("數位機上盒", "機上盒"), must_not=(" STB ", "STB："))),
        ("A05", "BB 方案有哪些？", check(group("寬頻", "網路", "確認"), must_not=("【BB】",))),
        ("A06", "不存在的彩虹 999 方案內容？", check(group("查不到", "沒有", "未找到", "無法確認"), must_not=("月租 999", "月租999"))),
    ]
    for case_id, question, spec in ambiguous_cases:
        add(
            case_id,
            "錯字與歧義",
            question,
            "tdtv",
            [question],
            [spec],
            "應容忍近音錯字；不確定時要反問；對外回答不可直接使用內部縮寫。",
        )

    # G. Tool routing and precision of narrow questions.
    tool_cases = [
        ("T01", "查詢帳單，客編 905397。", check(group("帳單", "查無", "待繳", "費用", "系統繁忙"), must_not=("姓名", "電話", "地址")), True),
        ("T02", "查詢合約，客編 905397。", check(group("合約", "查無", "系統繁忙", "服務"), must_not=("姓名", "電話", "地址")), True),
        ("T03", "WiFi 5 分享器一年多少錢？", check(group("WiFi 5"), group("300"), must_not=("所有設備都不能上網", "數據機")), False),
        ("T04", "遙控器多少錢？", check(group("遙控器"), group("元", "客服", "公司"), must_not=("機上盒電源", "錯誤代碼")), True),
        ("T05", "信用卡怎麼繳？", check(group("信用卡"), group("線上繳費", "APP"), must_not=("目前可用繳費方式：",)), False),
        ("T06", "加值數位套餐有哪些？", check(group("套餐", "HBO", "運動", "Hi Play", "頻道"), must_not=("姓名", "聯絡電話")), False),
    ]
    for case_id, question, spec, manual in tool_cases:
        spec["review"] = manual
        add(
            case_id,
            "工具與意圖路由",
            question,
            "tdtv",
            [question],
            [spec],
            "窄問題要走正確工具或資料來源，不可回覆另一個服務流程。",
        )

    assert len(cases) == 60, f"Expected 60 cases, got {len(cases)}"
    return cases


def norm(value: str) -> str:
    return re.sub(r"\s+", "", value or "").casefold()


def without_urls(value: str) -> str:
    return re.sub(r"https?://\S+", "", value or "", flags=re.IGNORECASE)


def evaluate_turn(answer: str, spec: dict[str, Any]) -> dict[str, Any]:
    normalized = norm(without_urls(answer))
    reasons: list[str] = []
    for alternatives in spec.get("must") or ():
        if not any(norm(term) in normalized for term in alternatives):
            reasons.append(f"缺少：{' / '.join(alternatives)}")
    for term in spec.get("must_not") or ():
        if norm(term) in normalized:
            reasons.append(f"不應出現：{term}")
    for jargon in ("RAG", "API"):
        if re.search(rf"(?<![A-Za-z]){jargon}(?![A-Za-z])", without_urls(answer), re.IGNORECASE):
            reasons.append(f"對外回答出現技術術語：{jargon}")
    status = "FAIL" if reasons else "REVIEW" if spec.get("review") else "PASS"
    return {"status": status, "reasons": reasons or ([spec.get("note")] if spec.get("note") else [])}


def get_auth_headers(base_url: str) -> dict[str, str]:
    name = os.getenv("RESILIENCE_API_AUTH_NAME") or os.getenv("TEST_API_AUTH_NAME") or os.getenv("API_AUTH_NAME")
    password = (
        os.getenv("RESILIENCE_API_AUTH_PASSWORD")
        or os.getenv("TEST_API_AUTH_PASSWORD")
        or os.getenv("API_AUTH_PASSWORD")
    )
    if not name or not password:
        raise RuntimeError(
            "Set RESILIENCE_API_AUTH_NAME and RESILIENCE_API_AUTH_PASSWORD before running this script."
        )
    response = requests.post(
        f"{base_url}/api/auth/token",
        json={"name": name, "password": password},
        timeout=30,
    )
    response.raise_for_status()
    payload = response.json()
    token = str(payload.get("access_token") or "")
    header_name = str(payload.get("header_name") or "Authorization")
    if not token:
        raise RuntimeError("Authentication succeeded but no access_token was returned.")
    if header_name.casefold() == "authorization" and not token.casefold().startswith("bearer "):
        token = f"Bearer {token}"
    return {header_name: token}


def run_case(case: dict[str, Any], base_url: str, headers: dict[str, str], index: int, total: int) -> dict[str, Any]:
    user_id = f"test_web:resilience-{case['case_id'].lower()}-{uuid.uuid4().hex[:8]}"
    result: dict[str, Any] = {**case, "user_id": user_id, "turn_results": [], "status": "PASS", "duration_sec": 0.0}
    started = time.perf_counter()
    print(f"[{index:02d}/{total}] {case['case_id']} {case['title']}", flush=True)
    try:
        reset = requests.post(f"{base_url}/reset/{user_id}", headers=headers, timeout=30)
        reset.raise_for_status()
        for turn_index, user_text in enumerate(case["turns"], start=1):
            turn_started = time.perf_counter()
            response = requests.post(
                f"{base_url}/chat",
                headers=headers,
                json={"user_id": user_id, "user_input": user_text, "tv_cable": case["company_code"]},
                timeout=300,
            )
            elapsed = round(time.perf_counter() - turn_started, 3)
            response.raise_for_status()
            payload = response.json()
            answer = str(payload.get("ai_response") or "")
            evaluation = evaluate_turn(answer, case["checks"][turn_index - 1])
            result["turn_results"].append(
                {
                    "turn": turn_index,
                    "user": user_text,
                    "assistant": answer,
                    "evaluation": evaluation,
                    "request_time_sec": elapsed,
                    "response_time_sec": payload.get("response_time_sec"),
                    "latency": payload.get("latency") or {},
                    "actions": payload.get("actions") or [],
                    "decision_type": payload.get("decision_type"),
                    "route": payload.get("route"),
                    "company_code": payload.get("company_code"),
                    "company": payload.get("company"),
                }
            )
        state = requests.get(
            f"{base_url}/state/{user_id}",
            params={"tv_cable": case["company_code"]},
            headers=headers,
            timeout=30,
        )
        if state.ok:
            result["final_state"] = state.json()
        statuses = [turn["evaluation"]["status"] for turn in result["turn_results"]]
        result["status"] = "FAIL" if "FAIL" in statuses else "REVIEW" if "REVIEW" in statuses else "PASS"
    except Exception as exc:
        result["status"] = "ERROR"
        result["error"] = f"{type(exc).__name__}: {exc}"
    result["duration_sec"] = round(time.perf_counter() - started, 3)
    print(f"         => {result['status']} ({result['duration_sec']}s)", flush=True)
    return result


def esc(value: Any) -> str:
    return html.escape(str(value or ""))


def nl(value: Any) -> str:
    return esc(value).replace("\n", "<br>")


def render_report(results: list[dict[str, Any]], generated_at: str, base_url: str) -> str:
    counts = Counter(item["status"] for item in results)
    category_counts: dict[str, Counter[str]] = defaultdict(Counter)
    for item in results:
        category_counts[item["category"]][item["status"]] += 1
    failures = [item for item in results if item["status"] in {"FAIL", "ERROR"}]

    category_rows = "".join(
        f"<tr><td>{esc(category)}</td><td>{sum(counts_.values())}</td>"
        f"<td>{counts_['PASS']}</td><td>{counts_['REVIEW']}</td><td>{counts_['FAIL']}</td><td>{counts_['ERROR']}</td></tr>"
        for category, counts_ in category_counts.items()
    )
    failure_items = "".join(
        f'<li><a href="#{esc(item["case_id"])}">{esc(item["case_id"])} {esc(item["title"])}</a>：{esc(item.get("error") or "回答未通過必要條件")}</li>'
        for item in failures
    ) or "<li>沒有自動判定失敗案例。</li>"

    cards: list[str] = []
    for item in results:
        conversations: list[str] = []
        for turn in item.get("turn_results") or []:
            evaluation = turn["evaluation"]
            reasons = "；".join(evaluation.get("reasons") or []) or "符合自動檢查條件"
            conversations.append(
                '<div class="turn">'
                '<div class="bubble-row user"><div class="avatar user">User</div>'
                f'<div class="bubble user"><div class="speaker">使用者</div>{nl(turn["user"])}</div></div>'
                '<div class="bubble-row ai"><div class="avatar ai">AI</div>'
                f'<div class="bubble ai"><div class="speaker">AI</div>{nl(turn["assistant"])}</div></div>'
                f'<div class="turn-check {evaluation["status"].lower()}"><strong>{evaluation["status"]}</strong> {esc(reasons)}</div>'
                '<div class="debug">'
                f'耗時 {esc(turn.get("request_time_sec"))} 秒 · decision={esc(turn.get("decision_type"))} · '
                f'route={esc(turn.get("route"))} · 回傳公司={esc(turn.get("company") or turn.get("company_code"))}'
                '</div></div>'
            )
        error = f'<div class="error-box">{esc(item.get("error"))}</div>' if item.get("error") else ""
        cards.append(
            f'<article class="case-card" id="{esc(item["case_id"])}">'
            '<div class="case-head">'
            f'<div><span class="case-id">{esc(item["case_id"])}</span><span class="category">{esc(item["category"])}</span>'
            f'<h3>{esc(item["title"])}</h3></div><span class="status {item["status"].lower()}">{item["status"]}</span></div>'
            f'<div class="risk"><strong>驗證重點：</strong>{esc(item["risk"])}</div>'
            f'<div class="meta">預設系統台代碼：{esc(item["company_code"])} · 案例耗時：{esc(item["duration_sec"])} 秒</div>'
            f'{error}{"".join(conversations)}</article>'
        )

    pass_rate = (counts["PASS"] / len(results) * 100) if results else 0
    return f"""<!doctype html>
<html lang="zh-Hant"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>客服架構韌性測試報告</title><style>
:root{{--bg:#0b1017;--panel:#121a26;--panel2:#182231;--line:#314155;--text:#edf3fa;--muted:#9eb0c3;--user:#183d61;--ai:#202a36;--accent:#f59e0b;--pass:#22c55e;--fail:#ef4444;--review:#f59e0b;--error:#f97316}}
*{{box-sizing:border-box}}body{{margin:0;background:var(--bg);color:var(--text);font-family:"Segoe UI","Microsoft JhengHei",sans-serif;line-height:1.65}}
main{{max-width:1280px;margin:auto;padding:36px 24px 80px}}h1{{font-size:36px;margin:0 0 4px}}h2{{margin-top:34px}}.sub,.meta,.debug{{color:var(--muted)}}
.summary{{display:grid;grid-template-columns:repeat(5,minmax(120px,1fr));gap:12px;margin:26px 0}}.stat{{background:var(--panel);border:1px solid var(--line);padding:16px;border-radius:7px}}.stat strong{{display:block;font-size:28px}}
table{{width:100%;border-collapse:collapse;background:var(--panel);border:1px solid var(--line)}}th,td{{padding:10px 12px;border-bottom:1px solid var(--line);text-align:left}}
.failure-list{{background:#24171b;border:1px solid #71323b;border-radius:7px;padding:14px 34px}}a{{color:#7dd3fc}}
.case-card{{background:var(--panel);border:1px solid var(--line);border-radius:7px;margin:20px 0;padding:20px}}.case-head{{display:flex;justify-content:space-between;gap:20px;align-items:flex-start}}h3{{margin:6px 0 0;font-size:22px}}
.case-id,.category,.status{{display:inline-block;padding:3px 9px;border-radius:999px;border:1px solid var(--line);margin-right:8px;font-size:13px}}.status{{font-weight:700}}.status.pass{{color:#86efac;border-color:#197544}}.status.fail{{color:#fca5a5;border-color:#8f3030}}.status.review{{color:#fcd34d;border-color:#8a651c}}.status.error{{color:#fdba74;border-color:#91491f}}
.risk{{margin:14px 0;padding:10px 12px;background:var(--panel2);border-left:3px solid var(--accent)}}.turn{{margin-top:20px;padding-top:18px;border-top:1px solid var(--line)}}
.bubble-row{{display:flex;gap:10px;margin:12px 0;align-items:flex-start}}.bubble-row.user{{justify-content:flex-end}}.bubble-row.user .avatar{{order:2}}.avatar{{width:42px;height:42px;display:grid;place-items:center;border-radius:6px;font-weight:700;background:#334155;flex:0 0 auto}}.avatar.user{{background:#e11d48}}.avatar.ai{{background:#d97706}}
.bubble{{max-width:82%;padding:14px 16px;border:1px solid var(--line);border-radius:7px;white-space:normal}}.bubble.user{{background:var(--user)}}.bubble.ai{{background:var(--ai)}}.speaker{{font-size:13px;color:#b9c9d8;font-weight:700;margin-bottom:5px}}
.turn-check{{margin:8px 52px;padding:8px 10px;border-radius:5px;background:#17202c}}.turn-check.pass{{border-left:3px solid var(--pass)}}.turn-check.fail{{border-left:3px solid var(--fail)}}.turn-check.review{{border-left:3px solid var(--review)}}.debug{{margin:5px 52px;font-size:13px}}.error-box{{background:#3b1717;color:#fecaca;padding:12px;margin:14px 0;border-radius:5px}}
@media(max-width:760px){{main{{padding:22px 12px}}.summary{{grid-template-columns:repeat(2,1fr)}}.bubble{{max-width:92%}}.case-head{{display:block}}}}
</style></head><body><main>
<h1>客服架構韌性測試報告</h1><div class="sub">產生時間：{esc(generated_at)} · 測試端點：{esc(base_url)} · 共 {len(results)} 組案例。REVIEW 表示回答具方向但仍需客服確認資料或區域政策。</div>
<section class="summary"><div class="stat"><span>案例</span><strong>{len(results)}</strong></div><div class="stat"><span>通過</span><strong>{counts['PASS']}</strong></div><div class="stat"><span>人工確認</span><strong>{counts['REVIEW']}</strong></div><div class="stat"><span>失敗</span><strong>{counts['FAIL']}</strong></div><div class="stat"><span>通過率</span><strong>{pass_rate:.1f}%</strong></div></section>
<h2>分類結果</h2><table><thead><tr><th>分類</th><th>總數</th><th>PASS</th><th>REVIEW</th><th>FAIL</th><th>ERROR</th></tr></thead><tbody>{category_rows}</tbody></table>
<h2>優先檢查</h2><ul class="failure-list">{failure_items}</ul>
<h2>完整對話與判讀</h2>{''.join(cards)}
</main></body></html>"""


def main() -> int:
    parser = argparse.ArgumentParser(description="Run 60 architecture resilience cases through the local chat API.")
    parser.add_argument("--base-url", default=os.getenv("RESILIENCE_BASE_URL", "http://127.0.0.1:8123"))
    parser.add_argument("--only", default="", help="Comma-separated case IDs to run, e.g. G01,F08")
    args = parser.parse_args()
    base_url = args.base_url.rstrip("/")
    cases = build_cases()
    selected = {item.strip().upper() for item in args.only.split(",") if item.strip()}
    if selected:
        cases = [case for case in cases if case["case_id"] in selected]
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    headers = get_auth_headers(base_url)
    health = requests.get(f"{base_url}/health", headers=headers, timeout=30)
    health.raise_for_status()
    print(f"Authenticated. Running {len(cases)} cases against {base_url}", flush=True)
    results = [run_case(case, base_url, headers, index, len(cases)) for index, case in enumerate(cases, start=1)]
    generated_at = datetime.now().astimezone().isoformat(timespec="seconds")
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    json_path = OUTPUT_DIR / f"architecture_resilience_{stamp}.json"
    html_path = OUTPUT_DIR / f"architecture_resilience_{stamp}.html"
    json_path.write_text(json.dumps({"generated_at": generated_at, "results": results}, ensure_ascii=False, indent=2), encoding="utf-8")
    html_path.write_text(render_report(results, generated_at, base_url), encoding="utf-8")
    counts = Counter(item["status"] for item in results)
    print(f"SUMMARY {dict(counts)}", flush=True)
    print(f"JSON {json_path}", flush=True)
    print(f"HTML {html_path}", flush=True)
    return 1 if counts["ERROR"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
