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
MARKDOWN_HTTP_LINK_RE = re.compile(r"\[[^\]\n]+\]\(https?://[^\s)]+\)")
PLAIN_HTTP_URL_RE = re.compile(r"https?://[A-Za-z0-9\-._~:/?#@!$&'*+=%;]+")


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


def linkify_plain_http_urls(text: str, label: str = "開啟連結") -> str:
    """Linkify bare URLs without nesting links already written as Markdown."""

    raw = str(text or "")

    def linkify_segment(segment: str) -> str:
        def replace(match: re.Match) -> str:
            url = match.group(0)
            next_character = segment[match.end():match.end() + 1]
            separator = (
                " "
                if next_character
                and not next_character.isspace()
                and next_character not in "，。；、,.;:：)]】"
                else ""
            )
            return f"[{label}]({url}){separator}"

        return PLAIN_HTTP_URL_RE.sub(replace, segment)

    parts: list[str] = []
    cursor = 0
    for match in MARKDOWN_HTTP_LINK_RE.finditer(raw):
        parts.append(linkify_segment(raw[cursor:match.start()]))
        parts.append(match.group(0))
        cursor = match.end()
    parts.append(linkify_segment(raw[cursor:]))
    return "".join(parts)


def text_linebreaks_to_html(text: str) -> str:
    """Render plain-text line breaks without exposing the text to Markdown lists."""
    normalized = str(text or "").replace("\r\n", "\n").replace("\r", "\n")
    return normalized.replace("\n", "<br>")
