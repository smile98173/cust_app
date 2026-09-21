import csv
import html
import json
from datetime import datetime
from pathlib import Path


SRC = Path(r"C:\Users\user\Desktop\ai_feedback.csv")
BASE_DIR = Path(__file__).resolve().parent.parent
OUT = BASE_DIR / "outputs" / "ai_feedback_bubbles.html"


FEEDBACK_LABELS = {
    "bad_answer": "回答不正確",
    "loop": "多輪卡住/重複回覆",
    "wrong_route": "意圖判斷錯誤",
    "tool_flow": "工具或報修流程錯誤",
    "knowledge": "知識庫答案不佳",
    "tone": "語氣或文字需調整",
    "other": "其他",
}


def esc(value):
    return html.escape(str(value or "")).replace("\n", "<br>")


def parse_json(value, fallback):
    try:
        return json.loads(value) if value else fallback
    except Exception:
        return fallback


def bubble(role, content):
    label = "使用者" if role == "user" else "AI" if role == "assistant" else role or "未知"
    klass = "user" if role == "user" else "assistant"
    return f"""
    <div class="bubble-row {klass}">
      <div class="bubble">
        <div class="bubble-label">{esc(label)}</div>
        <div class="bubble-text">{esc(content)}</div>
      </div>
    </div>
    """


def build_card(index, row):
    conversation = parse_json(row.get("conversation_json"), [])
    if not isinstance(conversation, list) or not conversation:
        conversation = [
            {"role": "user", "content": row.get("user_message", "")},
            {"role": "assistant", "content": row.get("ai_response", "")},
        ]

    bubbles = "".join(
        bubble(item.get("role"), item.get("content"))
        for item in conversation
        if isinstance(item, dict)
    )
    known_info = parse_json(row.get("known_info_json"), {})
    tool_result = parse_json(row.get("last_tool_result_json"), {})
    tool_name = tool_result.get("tool_name") if isinstance(tool_result, dict) else ""
    suggestion = row.get("suggestion") or "未填寫"
    feedback_type = FEEDBACK_LABELS.get(row.get("feedback_type"), row.get("feedback_type") or "未分類")

    return f"""
    <section class="card" id="fb-{index}">
      <div class="card-head">
        <div>
          <div class="eyebrow">第 {index} 筆</div>
          <h2>{esc(feedback_type)}</h2>
        </div>
        <div class="meta-block">
          <span>{esc(row.get("created_at"))}</span>
          <span>{esc(row.get("feedback_id"))}</span>
        </div>
      </div>

      <div class="summary-grid">
        <div class="summary-item"><span>系統台</span><strong>{esc(row.get("company") or row.get("company_code"))}</strong></div>
        <div class="summary-item"><span>Decision</span><strong>{esc(row.get("decision_type") or "-")}</strong></div>
        <div class="summary-item"><span>Tool</span><strong>{esc(tool_name or row.get("pending_tool") or "-")}</strong></div>
      </div>

      <div class="suggestion">
        <div class="section-title">客服建議</div>
        <div class="suggestion-text">{esc(suggestion)}</div>
      </div>

      <div class="last-turn">
        <div>
          <div class="section-title">最後一輪使用者</div>
          <div class="small-panel">{esc(row.get("user_message"))}</div>
        </div>
        <div>
          <div class="section-title">最後一輪 AI 回覆</div>
          <div class="small-panel">{esc(row.get("ai_response"))}</div>
        </div>
      </div>

      <div class="section-title">完整對話</div>
      <div class="chat-frame">{bubbles}</div>

      <details>
        <summary>已收集資訊 / Debug</summary>
        <pre>{esc(json.dumps(known_info, ensure_ascii=False, indent=2))}</pre>
      </details>
    </section>
    """


def main():
    OUT.parent.mkdir(parents=True, exist_ok=True)
    with SRC.open("r", encoding="utf-8-sig", newline="") as file:
        rows = list(csv.DictReader(file))

    cards = [build_card(index, row) for index, row in enumerate(rows, start=1)]
    nav = "".join(f'<a href="#fb-{index}">第 {index} 筆</a>' for index in range(1, len(rows) + 1))

    html_doc = f"""<!doctype html>
<html lang="zh-Hant">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>AI Feedback 泡泡對話視覺化</title>
<style>
:root {{
  --bg: #f4f6f8;
  --card: #ffffff;
  --ink: #1f2937;
  --muted: #667085;
  --line: #d8dee6;
  --user: #ffe8d6;
  --user-border: #ff9f43;
  --ai: #e9f2ff;
  --ai-border: #4d96ff;
  --accent: #0f766e;
  --danger-soft: #fff1f2;
}}
* {{ box-sizing: border-box; }}
body {{
  margin: 0;
  font-family: "Microsoft JhengHei", "Noto Sans TC", Arial, sans-serif;
  background: var(--bg);
  color: var(--ink);
}}
header {{
  position: sticky;
  top: 0;
  z-index: 3;
  background: rgba(244, 246, 248, 0.94);
  backdrop-filter: blur(10px);
  border-bottom: 1px solid var(--line);
  padding: 18px 28px;
}}
h1 {{ margin: 0 0 6px; font-size: 24px; }}
.header-meta {{ color: var(--muted); font-size: 14px; }}
main {{ max-width: 1120px; margin: 0 auto; padding: 24px; }}
.nav {{ display: flex; gap: 8px; flex-wrap: wrap; margin-top: 12px; }}
.nav a {{
  text-decoration: none;
  color: var(--accent);
  border: 1px solid #99d6cf;
  border-radius: 999px;
  padding: 5px 11px;
  background: #eefaf8;
  font-size: 13px;
}}
.card {{
  background: var(--card);
  border: 1px solid var(--line);
  border-radius: 12px;
  padding: 22px;
  margin-bottom: 22px;
  box-shadow: 0 10px 24px rgba(15, 23, 42, 0.06);
}}
.card-head {{ display: flex; justify-content: space-between; gap: 16px; align-items: flex-start; }}
.eyebrow {{ color: var(--accent); font-weight: 700; font-size: 13px; }}
h2 {{ margin: 4px 0 0; font-size: 22px; }}
.meta-block {{ display: flex; flex-direction: column; gap: 4px; color: var(--muted); font-size: 13px; text-align: right; }}
.summary-grid {{ display: grid; grid-template-columns: repeat(3, 1fr); gap: 10px; margin: 18px 0; }}
.summary-item {{ border: 1px solid var(--line); border-radius: 10px; padding: 10px 12px; background: #fafbfc; }}
.summary-item span {{ display:block; color: var(--muted); font-size: 12px; margin-bottom: 3px; }}
.summary-item strong {{ font-size: 14px; }}
.section-title {{ font-weight: 800; margin: 18px 0 8px; color: #344054; }}
.suggestion {{ background: var(--danger-soft); border-left: 4px solid #e11d48; border-radius: 10px; padding: 1px 14px 14px; }}
.suggestion-text {{ white-space: normal; line-height: 1.65; }}
.last-turn {{ display: grid; grid-template-columns: 1fr 1fr; gap: 14px; }}
.small-panel {{ border: 1px solid var(--line); border-radius: 10px; padding: 12px; background: #fbfdff; line-height: 1.6; min-height: 72px; }}
.chat-frame {{ border: 1px solid var(--line); background: #f8fafc; border-radius: 12px; padding: 16px; }}
.bubble-row {{ display: flex; margin: 10px 0; }}
.bubble-row.user {{ justify-content: flex-start; }}
.bubble-row.assistant {{ justify-content: flex-end; }}
.bubble {{ max-width: 76%; border-radius: 14px; padding: 10px 12px; line-height: 1.6; border: 1px solid; }}
.bubble-row.user .bubble {{ background: var(--user); border-color: var(--user-border); }}
.bubble-row.assistant .bubble {{ background: var(--ai); border-color: var(--ai-border); }}
.bubble-label {{ font-size: 12px; font-weight: 800; color: var(--muted); margin-bottom: 4px; }}
.bubble-text {{ font-size: 15px; }}
details {{ margin-top: 14px; color: var(--muted); }}
summary {{ cursor: pointer; }}
pre {{ white-space: pre-wrap; background: #111827; color: #e5e7eb; border-radius: 10px; padding: 12px; overflow-x: auto; }}
@media (max-width: 760px) {{
  main {{ padding: 14px; }}
  .card-head, .last-turn {{ display: block; }}
  .summary-grid {{ grid-template-columns: 1fr; }}
  .bubble {{ max-width: 94%; }}
  .meta-block {{ text-align: left; margin-top: 10px; }}
}}
</style>
</head>
<body>
<header>
  <h1>AI Feedback 泡泡對話視覺化</h1>
  <div class="header-meta">來源：{esc(str(SRC))} ｜ 筆數：{len(rows)} ｜ 產生時間：{esc(datetime.now().strftime("%Y-%m-%d %H:%M:%S"))}</div>
  <nav class="nav">{nav}</nav>
</header>
<main>
{"".join(cards)}
</main>
</body>
</html>
"""
    OUT.write_text(html_doc, encoding="utf-8")
    print(OUT)


if __name__ == "__main__":
    main()
