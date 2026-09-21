from app.services.reply_safety import sanitize_human_handoff_keyword_instruction


def test_sanitize_human_handoff_keyword_instruction_rewrites_legacy_prompt():
    reply = (
        "如果您有需要涉及個人資料查詢或修改、帳號密碼設定或重設需求等問題，"
        "可以輸入「真人客服」，我們的客服專員將會協助您。"
    )

    sanitized = sanitize_human_handoff_keyword_instruction(reply)

    assert "輸入「真人客服」" not in sanitized
    assert "我會依您的需求判斷是否需要轉真人客服" in sanitized


def test_sanitize_human_handoff_keyword_instruction_keeps_normal_mentions():
    reply = "這項優惠需由真人客服依公司公告與個案資格確認。"

    assert sanitize_human_handoff_keyword_instruction(reply) == reply
