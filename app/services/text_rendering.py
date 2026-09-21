"""Small, side-effect-free text conversions shared by display surfaces."""

from __future__ import annotations

import html
import re


HTML_ANCHOR_RE = re.compile(
    r'<a\b[^>]*\bhref\s*=\s*["\'](?P<url>https?://[^"\'\s<>]+)["\'][^>]*>'
    r'(?P<label>.*?)</a>',
    flags=re.IGNORECASE | re.DOTALL,
)
HTML_TAG_RE = re.compile(r"<[^>]+>")


def escape_streamlit_markdown_literals(text: str) -> str:
    """Keep customer-entered tildes and currency markers as literal text."""
    return str(text or "").replace("$", r"\$").replace("~", r"\~")


def html_anchors_to_markdown(text: str) -> str:
    """Convert trusted response anchors before a Markdown-only view renders them."""

    raw = str(text or "")

    def replace(match: re.Match) -> str:
        url = html.unescape(match.group("url")).strip()
        label = html.unescape(HTML_TAG_RE.sub("", match.group("label"))).strip()
        label = label or "開啟連結"
        return f"[{label}]({url})"

    return HTML_ANCHOR_RE.sub(replace, raw)


def text_linebreaks_to_html(text: str) -> str:
    """Render plain-text line breaks without exposing the text to Markdown lists."""
    normalized = str(text or "").replace("\r\n", "\n").replace("\r", "\n")
    return normalized.replace("\n", "<br>")
