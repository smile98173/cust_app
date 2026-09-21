from __future__ import annotations

import html
import json
import os
import sys
import time
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any

import requests
from dotenv import dotenv_values


ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

RUNTIME_DIR = ROOT_DIR.parent / "cust_app_runtime"
MANIFEST_PATH = RUNTIME_DIR / "kb_documents" / "documents.json"
BACKEND_URL = os.getenv("KB_ALL_TEST_BACKEND", "http://127.0.0.1:8123").rstrip("/")
OUTPUT_DIR = ROOT_DIR / "reports"

COMMON_TEST_STATIONS = {
    "通用-中區": "大屯",
    "通用-嘉南區": "新永安",
}


def load_active_documents() -> list[dict[str, Any]]:
    payload = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    documents = payload.get("documents", payload) if isinstance(payload, dict) else payload
    return [document for document in documents if document.get("status") == "active"]


def get_backend_auth_headers() -> dict[str, str]:
    default_env_file = ".env.production" if (ROOT_DIR / ".env.production").exists() else ".env"
    env_file = os.getenv("CUST_APP_ENV_FILE", default_env_file)
    config = dotenv_values(ROOT_DIR / env_file)
    header_name = str(config.get("API_AUTH_HEADER") or "X-API-Token").strip()
    name = str(
        os.getenv("KB_ALL_API_AUTH_NAME")
        or os.getenv("API_AUTH_NAME")
        or config.get("API_AUTH_NAME")
        or ""
    ).strip()
    password = str(
        os.getenv("KB_ALL_API_AUTH_PASSWORD")
        or os.getenv("API_AUTH_PASSWORD")
        or config.get("API_AUTH_PASSWORD")
        or ""
    ).strip()
    if name and password:
        response = requests.post(
            f"{BACKEND_URL}/api/auth/token",
            json={"name": name, "password": password},
            timeout=20,
        )
        response.raise_for_status()
        payload = response.json()
        token = str(payload.get("access_token") or "").strip()
        response_header = str(payload.get("header_name") or header_name).strip()
        if token:
            return {response_header: token}
    fixed_token = str(config.get("API_AUTH_TOKEN") or "").strip()
    return {header_name: fixed_token} if fixed_token else {}


def station_label(knowledge_base: str) -> str:
    return {
        "西海岸": "台灣佳光",
        "佳光市區": "佳光市區",
        "大屯": "大屯",
        "中投": "中投",
        "佳聯": "佳聯",
        "北港": "北港",
        "新永安": "新永安",
        "大揚": "大揚",
    }.get(knowledge_base, knowledge_base)


def build_probe(document: dict[str, Any]) -> str:
    title = str(document.get("title") or "").strip()
    knowledge_base = str(document.get("knowledge_base") or "").strip()
    station = station_label(COMMON_TEST_STATIONS.get(knowledge_base, knowledge_base))

    if title == "機上盒":
        return "複製遙控器要怎麼設定？"
    if "移機費" in title:
        return f"{station}網路移機要收多少錢？"
    if "低收入" in title:
        return f"{station}低收入戶優惠要準備哪些資料？"
    if "FIFA" in title or "世界盃" in title:
        return "世足比賽會在哪幾台播？"
    if title == "網路寬頻":
        return "固定 IP 要怎麼申請？"
    if title == "加值服務":
        return "台數科紅利點數哈 Point 是什麼？"
    if "單品銷售(加值服務)" in title:
        return "WiFi 5 分享器一年多少錢？"
    if "單品銷售(數位電視)" in title:
        return f"{station}數位電視有哪些加值套餐？"
    if title == "帳務":
        return "ibon 要怎麼繳有線電視費？"
    if title == "嘉南區測試用":
        return "遙控器壞掉可以送到府更換嗎？"
    if title == "通用-嘉南區資料庫":
        return "電視看到一半變成藍畫面怎麼辦？"
    if "基本收費標準" in title:
        return f"{station}有線電視一個月多少錢？"
    if "爸氣獻禮" in title:
        return f"{station}八月父親節優惠有哪些？"
    if "飆網守護家" in title:
        return f"{station}飆網守護家有哪些優惠？"
    if "好視成雙NO8" in title:
        return f"{station}好視成雙 NO8 有哪些方案？"
    if "好視成雙NO7" in title:
        return f"{station}好視成雙 NO7 有哪些方案？"
    if "好康三合一" in title:
        return f"{station}好康三合一的月租和優惠有哪些？"
    if "哈NET2" in title:
        return f"{station}單辦網路哈 NET2 有哪些月租方案？"
    if "哈NET1" in title:
        return f"{station}單辦網路哈 NET1 有哪些月租方案？"
    return f"請問{station}{title}的內容是什麼？"


def result_document_id(result: dict[str, Any]) -> str:
    source = result.get("source") if isinstance(result.get("source"), dict) else {}
    return str(result.get("document_id") or source.get("document_id") or "")


def result_title(result: dict[str, Any]) -> str:
    source = result.get("source") if isinstance(result.get("source"), dict) else {}
    return str(result.get("title") or source.get("title") or "")


def result_content(result: dict[str, Any]) -> str:
    source = result.get("source") if isinstance(result.get("source"), dict) else {}
    return str(
        result.get("answer")
        or result.get("content")
        or result.get("text")
        or source.get("answer")
        or source.get("content")
        or source.get("text")
        or ""
    )


def run_probe(document: dict[str, Any], headers: dict[str, str]) -> dict[str, Any]:
    source_knowledge_base = str(document.get("knowledge_base") or "通用")
    test_knowledge_base = COMMON_TEST_STATIONS.get(source_knowledge_base, source_knowledge_base)
    question = build_probe(document)
    started = time.perf_counter()
    response = requests.post(
        f"{BACKEND_URL}/api/kb/chat-search",
        json={
            "plan_name": question,
            "knowledge_base": test_knowledge_base,
            "limit": 10,
        },
        headers=headers,
        timeout=120,
    )
    elapsed = round(time.perf_counter() - started, 3)
    response.raise_for_status()
    payload = response.json()
    docs = (
        payload.get("sources")
        or payload.get("docs")
        or payload.get("results")
        or []
    )
    answerable_docs = (
        payload.get("answerable_sources")
        or payload.get("answerable_docs")
        or []
    )
    combined: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for item in [*answerable_docs, *docs]:
        if not isinstance(item, dict):
            continue
        key = (result_document_id(item), result_content(item))
        if key in seen:
            continue
        seen.add(key)
        combined.append(item)

    expected_id = str(document.get("id") or "")
    hit_rank = next(
        (index for index, item in enumerate(combined, start=1) if result_document_id(item) == expected_id),
        None,
    )
    top_results = []
    for item in combined[:10]:
        top_results.append(
            {
                "document_id": result_document_id(item),
                "title": result_title(item),
                "score": item.get("score", item.get("_score")),
                "distance": item.get("distance", item.get("_distance")),
                "content": result_content(item)[:500],
            }
        )
    return {
        "document_id": expected_id,
        "title": document.get("title"),
        "source_knowledge_base": source_knowledge_base,
        "test_knowledge_base": test_knowledge_base,
        "category": document.get("category"),
        "question": question,
        "status": "PASS" if hit_rank is not None else "FAIL",
        "hit_rank": hit_rank,
        "latency_sec": elapsed,
        "returned_count": len(combined),
        "top_results": top_results,
    }


def render_html(results: list[dict[str, Any]], generated_at: str) -> str:
    counts = Counter(result["status"] for result in results)
    pass_rate = (counts["PASS"] / len(results) * 100) if results else 0
    cards = []
    for index, result in enumerate(results, start=1):
        result_rows = []
        for rank, item in enumerate(result["top_results"], start=1):
            matched = item["document_id"] == result["document_id"]
            score = item.get("score")
            score_text = f"{score:.4f}" if isinstance(score, (int, float)) else "-"
            result_rows.append(
                "<tr class='matched'>" if matched else "<tr>"
            )
            result_rows.append(
                f"<td>{rank}</td><td>{html.escape(item['title'] or '未標題')}</td>"
                f"<td>{score_text}</td><td>{html.escape(item['content'])}</td></tr>"
            )
        status_label = "命中" if result["status"] == "PASS" else "未命中"
        cards.append(
            f"""
            <article class="case {result['status'].lower()}">
              <header><span class="case-no">#{index:02d}</span><h2>{html.escape(str(result['title']))}</h2><span class="badge">{status_label}</span></header>
              <div class="meta"><span>來源：{html.escape(result['source_knowledge_base'])}</span><span>測試範圍：{html.escape(result['test_knowledge_base'])}</span><span>分類：{html.escape(str(result['category']))}</span><span>耗時：{result['latency_sec']:.3f} 秒</span></div>
              <p class="question"><strong>使用者問法</strong>{html.escape(result['question'])}</p>
              <p class="verdict">預期文件排名：{result['hit_rank'] if result['hit_rank'] is not None else '前 10 筆未出現'}</p>
              <details {'open' if result['status'] == 'FAIL' else ''}><summary>查看實際檢索結果</summary>
                <div class="table-wrap"><table><thead><tr><th>#</th><th>文件</th><th>分數</th><th>片段</th></tr></thead><tbody>{''.join(result_rows)}</tbody></table></div>
              </details>
            </article>
            """
        )
    return f"""<!doctype html>
<html lang="zh-Hant"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>RAG 全文件檢索驗證</title>
<style>
:root{{--bg:#0b1017;--panel:#121a26;--panel2:#182333;--text:#edf2f7;--muted:#9fb0c3;--line:#334155;--ok:#43c77b;--bad:#ff6b6b;--accent:#d97706}}
*{{box-sizing:border-box}} body{{margin:0;background:var(--bg);color:var(--text);font:16px/1.65 system-ui,"Microsoft JhengHei",sans-serif}}
main{{width:min(1500px,calc(100% - 32px));margin:32px auto 80px}} h1{{font-size:30px;margin:0}} .sub{{color:var(--muted);margin:4px 0 20px}}
.summary{{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:12px;margin:20px 0 28px}} .metric{{background:var(--panel);border:1px solid var(--line);padding:16px;border-radius:8px}} .metric b{{display:block;font-size:25px}}
.filters{{display:flex;gap:8px;margin-bottom:14px}} button{{background:var(--panel2);color:var(--text);border:1px solid var(--line);padding:8px 14px;border-radius:6px;cursor:pointer}}
.case{{background:var(--panel);border:1px solid var(--line);border-left:5px solid var(--ok);border-radius:8px;margin:14px 0;padding:18px}} .case.fail{{border-left-color:var(--bad)}}
.case header{{display:flex;align-items:center;gap:12px}} .case h2{{font-size:19px;margin:0;flex:1}} .case-no{{color:var(--muted)}} .badge{{font-weight:700;color:var(--ok)}} .fail .badge{{color:var(--bad)}}
.meta{{display:flex;flex-wrap:wrap;gap:8px 18px;color:var(--muted);font-size:14px;margin:8px 0 12px}} .question{{background:var(--panel2);padding:12px;border-radius:6px;margin:0}} .question strong{{display:block;color:#f2b35e;font-size:13px}}
.verdict{{margin:10px 0;color:var(--muted)}} details{{border-top:1px solid var(--line);padding-top:10px}} summary{{cursor:pointer}} .table-wrap{{overflow:auto;margin-top:10px}}
table{{width:100%;border-collapse:collapse;min-width:900px}} th,td{{padding:9px;border-bottom:1px solid var(--line);text-align:left;vertical-align:top}} th{{color:var(--muted)}} tr.matched{{background:rgba(67,199,123,.12)}} td:nth-child(4){{white-space:pre-wrap}}
@media(max-width:800px){{.summary{{grid-template-columns:1fr 1fr}} main{{width:min(100% - 20px,1500px)}}}}
</style></head><body><main>
<h1>RAG 全文件檢索驗證</h1><p class="sub">每一份啟用文件皆使用一個真實問法呼叫聊天同款檢索流程。產生時間：{html.escape(generated_at)}</p>
<section class="summary"><div class="metric"><span>啟用文件</span><b>{len(results)}</b></div><div class="metric"><span>命中</span><b>{counts['PASS']}</b></div><div class="metric"><span>未命中</span><b>{counts['FAIL']}</b></div><div class="metric"><span>命中率</span><b>{pass_rate:.1f}%</b></div></section>
<div class="filters"><button onclick="filterCases('all')">全部</button><button onclick="filterCases('pass')">只看命中</button><button onclick="filterCases('fail')">只看未命中</button></div>
{''.join(cards)}
</main><script>function filterCases(status){{document.querySelectorAll('.case').forEach(el=>el.hidden=status!=='all'&&!el.classList.contains(status))}}</script></body></html>"""


def main() -> None:
    documents = load_active_documents()
    headers = get_backend_auth_headers()
    results: list[dict[str, Any]] = []
    for index, document in enumerate(documents, start=1):
        try:
            result = run_probe(document, headers)
        except requests.HTTPError as exc:
            status_code = exc.response.status_code if exc.response is not None else None
            if status_code in {401, 403}:
                raise RuntimeError(
                    f"Backend authorization failed with HTTP {status_code}; test aborted."
                ) from exc
            result = {
                "document_id": document.get("id"),
                "title": document.get("title"),
                "source_knowledge_base": document.get("knowledge_base"),
                "test_knowledge_base": COMMON_TEST_STATIONS.get(
                    str(document.get("knowledge_base")), str(document.get("knowledge_base"))
                ),
                "category": document.get("category"),
                "question": build_probe(document),
                "status": "FAIL",
                "hit_rank": None,
                "latency_sec": 0.0,
                "returned_count": 0,
                "top_results": [],
                "error": f"{type(exc).__name__}: {exc}",
            }
        except Exception as exc:
            result = {
                "document_id": document.get("id"),
                "title": document.get("title"),
                "source_knowledge_base": document.get("knowledge_base"),
                "test_knowledge_base": COMMON_TEST_STATIONS.get(
                    str(document.get("knowledge_base")), str(document.get("knowledge_base"))
                ),
                "category": document.get("category"),
                "question": build_probe(document),
                "status": "FAIL",
                "hit_rank": None,
                "latency_sec": 0.0,
                "returned_count": 0,
                "top_results": [],
                "error": f"{type(exc).__name__}: {exc}",
            }
        results.append(result)
        print(
            f"[{index:02d}/{len(documents):02d}] {result['status']} "
            f"{result['source_knowledge_base']} / {result['title']} "
            f"rank={result['hit_rank']}"
        )

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    generated_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    json_path = OUTPUT_DIR / f"kb_all_document_retrieval_{stamp}.json"
    html_path = OUTPUT_DIR / f"kb_all_document_retrieval_{stamp}.html"
    json_path.write_text(
        json.dumps(
            {"generated_at": generated_at, "backend": BACKEND_URL, "results": results},
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    html_path.write_text(render_html(results, generated_at), encoding="utf-8")
    failures = sum(result["status"] == "FAIL" for result in results)
    print(f"JSON: {json_path}")
    print(f"HTML: {html_path}")
    print(f"SUMMARY: total={len(results)} pass={len(results) - failures} fail={failures}")


if __name__ == "__main__":
    main()
