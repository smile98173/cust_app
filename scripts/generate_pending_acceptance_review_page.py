"""Generate an offline, card-based page for manually reviewing API reruns."""

from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
REPORT_DIR = ROOT / "reports"
OUTPUT = ROOT / "outputs" / "pending_acceptance_manual_review.html"

# Only outcomes actually read and decided by a person belong here.  The page
# stores any additional reviewer choices in browser local storage.
MANUAL_SEED = {
    "FB-20260831131051-A8E1A5": {
        "verdict": "passed",
        "note": "人工比對客服建議後通過：同裝方案、費用是否合併與 60M/6M 包含範圍皆已正確回答。",
    },
    "FB-20260911132133-DD27E5": {
        "verdict": "passed",
        "note": "人工確認：個人專案點數須由客服核對時，/api/v1/chat 已回傳可點擊的真人文字客服連結，未再假稱已直接轉接。",
    },
}


def load_json(path: Path) -> list[dict[str, Any]]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    return payload if isinstance(payload, list) else []


def messages(value: Any) -> list[dict[str, str]]:
    if not isinstance(value, list):
        return []
    return [
        {
            "role": str(item.get("role") or "assistant"),
            "content": str(item.get("content") or "").strip(),
        }
        for item in value
        if isinstance(item, dict) and str(item.get("content") or "").strip()
    ]


def latest_cases() -> list[dict[str, Any]]:
    latest: dict[str, dict[str, Any]] = {}
    for report_path in sorted(REPORT_DIR.glob("pending_acceptance_api_rerun_*.json")):
        for item in load_json(report_path):
            feedback_id = str(item.get("feedback_id") or "").strip()
            rerun = messages(item.get("rerun_messages"))
            if feedback_id and item.get("status") == "RAN" and rerun:
                latest[feedback_id] = {
                    "id": feedback_id,
                    "company": str(item.get("company_code") or "-").upper(),
                    "feedbackType": str(item.get("feedback_type") or "未分類"),
                    "createdAt": str(item.get("created_at") or ""),
                    "suggestion": str(item.get("suggestion") or "未填寫客服建議。"),
                    "original": messages(item.get("original_messages")),
                    "rerun": rerun,
                    "report": report_path.name,
                    "manual": MANUAL_SEED.get(feedback_id, {"verdict": "unreviewed", "note": ""}),
                }
    return sorted(latest.values(), key=lambda item: (item["createdAt"], item["id"]), reverse=True)


PAGE = r"""<!doctype html>
<html lang="zh-Hant">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>待驗收案例人工審閱</title>
<style>
:root { --bg:#0b0f16; --panel:#121924; --panel-2:#182131; --line:#2d3a4d; --ink:#edf3fa; --muted:#9aa9bc; --blue:#4ca8ff; --blue-soft:#142c47; --coral:#ff9a55; --coral-soft:#3a261a; --teal:#42c7ae; --teal-soft:#13352f; --red:#ff6576; --red-soft:#421f2a; --yellow:#f0bf62; --yellow-soft:#382f1c; }
* { box-sizing:border-box; } body { margin:0; background:var(--bg); color:var(--ink); font-family:"Microsoft JhengHei","Noto Sans TC",Arial,sans-serif; line-height:1.55; }
header { height:74px; display:flex; align-items:center; justify-content:space-between; gap:20px; padding:0 28px; border-bottom:1px solid var(--line); background:#0e141e; }
h1 { margin:0; font-size:21px; } .sub { margin-top:3px; color:var(--muted); font-size:13px; } .progress { color:var(--muted); font-size:13px; white-space:nowrap; }
.app { display:grid; grid-template-columns:320px minmax(0,1fr); min-height:calc(100vh - 74px); } aside { padding:18px; border-right:1px solid var(--line); background:#0e141e; }
.filters { display:grid; gap:10px; } input,select,textarea { width:100%; color:var(--ink); background:var(--panel); border:1px solid var(--line); border-radius:6px; font:inherit; padding:9px 10px; } textarea { min-height:92px; resize:vertical; }
.case-list { display:grid; gap:7px; margin-top:16px; max-height:calc(100vh - 210px); overflow:auto; padding-right:3px; }.case-item { width:100%; text-align:left; cursor:pointer; color:var(--ink); border:1px solid transparent; border-radius:6px; background:transparent; padding:10px; }.case-item:hover { background:var(--panel); }.case-item.active { background:var(--blue-soft); border-color:#386793; }.case-id { font-size:12px; font-weight:800; color:var(--blue); }.case-title { margin-top:2px; font-size:14px; font-weight:700; }.case-meta { margin-top:3px; color:var(--muted); font-size:12px; }
main { width:100%; max-width:1500px; margin:0 auto; padding:26px 30px 48px; }.card { border:1px solid var(--line); border-radius:8px; background:var(--panel); padding:20px; }.card-head { display:flex; justify-content:space-between; align-items:start; gap:14px; }.eyebrow { color:var(--blue); font-size:13px; font-weight:800; } h2 { margin:3px 0 0; font-size:24px; }.tags { display:flex; flex-wrap:wrap; gap:6px; justify-content:flex-end; }.tag { border:1px solid var(--line); border-radius:999px; color:var(--muted); background:var(--panel-2); padding:4px 9px; font-size:12px; }.tag.pass { color:var(--teal); border-color:#2d7a6c; background:var(--teal-soft); }.tag.fix { color:var(--coral); border-color:#8c5633; background:var(--coral-soft); }.tag.kb { color:var(--yellow); border-color:#806a39; background:var(--yellow-soft); }
.suggestion { margin:18px 0; padding:12px 14px; border-left:4px solid var(--yellow); background:var(--yellow-soft); }.label { color:var(--muted); font-size:12px; font-weight:800; margin-bottom:5px; }.suggestion-text,.note-text { white-space:pre-wrap; }.review { display:grid; grid-template-columns:1fr 1fr; gap:18px; }.column-head { display:flex; justify-content:space-between; align-items:center; gap:10px; margin-bottom:8px; } h3 { margin:0; font-size:16px; }.chat { min-height:330px; padding:14px; background:#0d131d; border:1px solid var(--line); border-radius:8px; }.bubble-row { display:flex; margin:10px 0; }.bubble-row.user { justify-content:flex-end; }.bubble { max-width:84%; padding:9px 11px; border:1px solid; border-radius:8px; white-space:pre-wrap; }.bubble-row.user .bubble { background:var(--blue-soft); border-color:#35658e; }.bubble-row.assistant .bubble { background:var(--coral-soft); border-color:#845333; }.role { display:block; margin-bottom:3px; color:var(--muted); font-size:11px; font-weight:800; }.handoff-link { display:inline-block; margin-top:8px; color:var(--ink); background:#174b72; border:1px solid #4ca8ff; border-radius:5px; padding:5px 8px; font-weight:800; text-decoration:none; }.handoff-link:hover { background:#1e5d8c; }.empty { color:var(--muted); padding:24px; text-align:center; }
.manual { display:grid; grid-template-columns:185px minmax(0,1fr); gap:12px; margin-top:20px; padding-top:18px; border-top:1px solid var(--line); }.manual label { font-size:13px; font-weight:800; }.manual .help { grid-column:2; margin:0; color:var(--muted); font-size:12px; }.report { margin-top:14px; color:var(--muted); font-size:12px; }.notice { padding:18px; border:1px solid var(--line); border-radius:8px; color:var(--muted); }
@media (max-width:980px) { header { height:auto; padding:16px; align-items:start; } .app { grid-template-columns:1fr; } aside { border-right:0; border-bottom:1px solid var(--line); } .case-list { max-height:220px; } main { padding:18px 14px; } .review,.manual { grid-template-columns:1fr; } .manual .help { grid-column:auto; } .card-head { display:block; }.tags { justify-content:flex-start; margin-top:12px; } }
</style>
</head>
<body>
<header><div><h1>待驗收案例人工審閱</h1><div class="sub">原始對話、客服建議與最新 8123 真實 API 回覆並列。</div></div><div class="progress" id="progress"></div></header>
<div class="app"><aside><div class="filters"><input id="search" placeholder="搜尋案例 ID、系統台或內容"><select id="status"><option value="">全部人工狀態</option><option value="unreviewed">尚未判讀</option><option value="passed">符合客服建議</option><option value="needs_fix">待修正</option><option value="needs_kb">需客服補知識</option><option value="billing_approval">待確認帳務規則</option></select></div><div class="case-list" id="caseList"></div></aside><main id="detail"></main></div>
<script>
const cases = __PAYLOAD__;
const esc = value => String(value || '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const labels = {unreviewed:'尚未判讀',passed:'符合客服建議',needs_fix:'待修正',needs_kb:'需客服補知識',billing_approval:'待確認帳務規則'};
const key = id => `pending-acceptance-manual-review-${id}`;
const saved = item => { try { return {...item.manual, ...JSON.parse(localStorage.getItem(key(item.id)) || '{}')}; } catch { return item.manual || {}; } };
const formatBubbleText = value => {
  const raw = String(value || '').replace(/<br\s*\/?\s*>/gi, '\n');
  const pattern = /<a\s+href=["'](https?:\/\/[^"']+)["'][^>]*>([^<]*)<\/a>/gi;
  let output = '', cursor = 0, match;
  while ((match = pattern.exec(raw))) {
    output += esc(raw.slice(cursor, match.index)).replace(/\n/g, '<br>');
    let trusted = false;
    try { trusted = new URL(match[1]).hostname === 'pweb.topmso.com.tw'; } catch (_) {}
    output += trusted
      ? `<a class="handoff-link" href="${esc(match[1])}" target="_blank" rel="noopener noreferrer">${esc(match[2] || '轉真人文字客服')}</a>`
      : esc(match[0]);
    cursor = pattern.lastIndex;
  }
  return output + esc(raw.slice(cursor)).replace(/\n/g, '<br>');
};
const bubbles = (items, userLabel, aiLabel) => items?.length ? items.map(item => `<div class="bubble-row ${item.role === 'user' ? 'user' : 'assistant'}"><div class="bubble"><span class="role">${item.role === 'user' ? userLabel : aiLabel}</span>${formatBubbleText(item.content)}</div></div>`).join('') : '<div class="empty">沒有可顯示的對話。</div>';
let visible = cases, selected = cases[0]?.id || '';
function statusClass(value) { return value === 'passed' ? 'pass' : value === 'needs_fix' ? 'fix' : value === 'needs_kb' || value === 'billing_approval' ? 'kb' : ''; }
function renderList() { const search = document.querySelector('#search').value.trim().toLowerCase(); const filter = document.querySelector('#status').value; visible = cases.filter(item => { const review = saved(item); return (!filter || review.verdict === filter) && (!search || JSON.stringify(item).toLowerCase().includes(search)); }); if (!visible.some(item => item.id === selected)) selected = visible[0]?.id || ''; document.querySelector('#caseList').innerHTML = visible.map(item => { const review = saved(item); return `<button class="case-item ${item.id === selected ? 'active' : ''}" data-id="${esc(item.id)}"><div class="case-id">${esc(item.id)}</div><div class="case-title">${esc(labels[review.verdict] || labels.unreviewed)}</div><div class="case-meta">${esc(item.company)} · ${esc(item.feedbackType)}</div></button>`; }).join('') || '<div class="empty">沒有符合的案例。</div>'; document.querySelectorAll('.case-item').forEach(button => button.onclick = () => { selected = button.dataset.id; render(); }); }
function renderDetail() { const item = cases.find(value => value.id === selected); const detail = document.querySelector('#detail'); if (!item) { detail.innerHTML = '<div class="notice">請從左側選擇案例。</div>'; return; } const review = saved(item); detail.innerHTML = `<article class="card"><div class="card-head"><div><div class="eyebrow">${esc(item.id)}</div><h2>最新真實 API 對話</h2></div><div class="tags"><span class="tag ${statusClass(review.verdict)}">${esc(labels[review.verdict] || labels.unreviewed)}</span><span class="tag">${esc(item.company)}</span><span class="tag">${esc(item.feedbackType)}</span></div></div><section class="suggestion"><div class="label">客服建議</div><div class="suggestion-text">${esc(item.suggestion)}</div></section><section class="review"><div><div class="column-head"><h3>原始案例</h3><span class="tag">${esc(item.createdAt)}</span></div><div class="chat">${bubbles(item.original, '使用者', '原始 AI')}</div></div><div><div class="column-head"><h3>修正後案例</h3><span class="tag">8123 API</span></div><div class="chat">${bubbles(item.rerun, '使用者', '最新 AI')}</div></div></section><section class="manual"><label for="verdict">人工判讀</label><select id="verdict">${Object.entries(labels).map(([value,label]) => `<option value="${value}" ${review.verdict === value ? 'selected' : ''}>${label}</option>`).join('')}</select><label for="note">判讀理由</label><textarea id="note" placeholder="說明回覆是否符合客服建議，或要補什麼規則。">${esc(review.note || '')}</textarea><div></div><p class="help" id="saved">判讀只儲存在此瀏覽器；不會自動寫回回饋系統。</p></section><div class="report">最新來源報告：${esc(item.report)}</div></article>`; const persist = () => { localStorage.setItem(key(item.id), JSON.stringify({verdict:document.querySelector('#verdict').value,note:document.querySelector('#note').value})); document.querySelector('#saved').textContent = '已儲存在此瀏覽器。'; renderList(); renderProgress(); }; document.querySelector('#verdict').onchange = persist; document.querySelector('#note').onchange = persist; }
function renderProgress() { const reviewed = cases.filter(item => saved(item).verdict && saved(item).verdict !== 'unreviewed').length; document.querySelector('#progress').textContent = `已人工判讀 ${reviewed} / ${cases.length} 筆`; }
function render() { renderList(); renderDetail(); renderProgress(); }
document.querySelector('#search').oninput = render; document.querySelector('#status').onchange = render; render();
</script></body></html>"""


def write_page(content: str, output: Path) -> Path:
    try:
        output.write_text(content, encoding="utf-8")
        return output
    except PermissionError:
        alternate = output.with_name(
            f"{output.stem}_{datetime.now().strftime('%Y%m%d_%H%M%S')}{output.suffix}"
        )
        alternate.write_text(content, encoding="utf-8")
        return alternate


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", default=str(OUTPUT))
    args = parser.parse_args()
    output = Path(args.output).resolve()
    cases = latest_cases()
    payload = json.dumps(cases, ensure_ascii=False).replace("</", "<\\/")
    output.parent.mkdir(parents=True, exist_ok=True)
    generated = write_page(PAGE.replace("__PAYLOAD__", payload), output)
    print(f"generated={generated}")
    print(f"cases={len(cases)}")
    print(f"generated_at={datetime.now().isoformat(timespec='seconds')}")


if __name__ == "__main__":
    main()
