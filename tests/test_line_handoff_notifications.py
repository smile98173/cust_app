import pytest


def test_human_alert_text_only_includes_latest_conversation_pair():
    pytest.importorskip("fastapi")
    from app.app_backend import build_human_alert_text

    text = build_human_alert_text(
        {"display_name": "測試 Bot", "bot_code": "test_bot"},
        "U697bbc6598d09218a466236ff9db1acb",
        "我要找真人~",
        [
            {"role": "user", "content": "前面很久的問題"},
            {"role": "assistant", "content": "前面很久的回答"},
            {"role": "user", "content": "有沒有真人 我想要隱藏優惠"},
            {"role": "assistant", "content": "可以，若您要問隱藏優惠，需由真人客服確認。"},
        ],
    )

    assert text == (
        "測試 Bot 用戶要求真人客服\n"
        "LINE User ID: U697bbc6598d09218a466236ff9db1acb\n"
        "最新訊息: 我要找真人~\n\n"
        "最近對話:\n"
        "User: 有沒有真人 我想要隱藏優惠\n"
        "AI: 可以，若您要問隱藏優惠，需由真人客服確認。"
    )
    assert "前面很久的問題" not in text
