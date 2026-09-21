import re


_HUMAN_KEYWORD_PATTERN = re.compile(
    r"(?:請(?:您)?|可(?:以)?|您可以|你可以)?"
    r"(?:直接)?"
    r"(?:輸入|回覆|打)"
    r"[「『\"]?(?:真人客服|人工客服|轉真人|轉人工|找真人|找人工)[」』\"]?"
    r"(?:，|,)?"
    r"(?:我們的)?"
    r"(?:客服專員|客服人員|真人客服|人工客服)?"
    r"(?:將會|會)?"
    r"(?:協助您|協助你|為您服務|接手處理)?",
)


def sanitize_human_handoff_keyword_instruction(text: str) -> str:
    if not text:
        return text

    replacement = "我會依您的需求判斷是否需要轉真人客服，由客服專員接手處理"
    sanitized = _HUMAN_KEYWORD_PATTERN.sub(replacement, str(text))
    return re.sub(r"\s+([。！？])", r"\1", sanitized).strip()
