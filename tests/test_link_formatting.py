import pytest

from app.services.channel_context import format_reply_for_line
from app.services.company_profile import INSTALL_REPORT_URL, REPAIR_REPORT_URL


def test_external_web_formats_corner_bracket_known_repair_link():
    pytest.importorskip("fastapi")
    from app import app_backend

    html = app_backend.format_reply_for_external_web("也可以開啟【維修申告🔗】申請報修。")

    assert '<a href="http://stb.topmso.com.tw:8080/' in html
    assert "維修申告" in html
    assert "target=\"_blank\"" in html


def test_external_web_extracts_corner_bracket_known_repair_link():
    pytest.importorskip("fastapi")
    from app import app_backend

    links = app_backend.extract_reply_links_for_external_web("也可以開啟【維修申告🔗】申請報修。")

    assert links == [
        {
            "label": "維修申告",
            "url": REPAIR_REPORT_URL.replace("&amp;", "&"),
        }
    ]


def test_external_web_known_repair_link_uses_company_profile(monkeypatch):
    pytest.importorskip("fastapi")
    from app import app_backend

    def fake_profile(_company_code):
        return {
            "urls": (
                "［官網🔗］https://example.test/\n"
                "［維修申告🔗］https://example.test/repair\n"
                "［裝機申告🔗］https://example.test/install"
            )
        }

    monkeypatch.setattr(app_backend, "get_company_profile", fake_profile)

    html = app_backend.format_reply_for_external_web(
        "也可以開啟【維修申告🔗】申請報修。",
        {"company_code": "wctv"},
    )
    links = app_backend.extract_reply_links_for_external_web(
        "也可以開啟【維修申告🔗】申請報修。",
        {"company_code": "wctv"},
    )

    assert '<a href="https://example.test/repair"' in html
    assert links == [{"label": "維修申告", "url": "https://example.test/repair"}]


def test_external_web_linkifies_plain_urls():
    pytest.importorskip("fastapi")
    from app import app_backend

    html = app_backend.format_reply_for_external_web(
        "相關網站：\n1. 東森電視官網：https://share.google/ajoE0ongUyZMxSlUv\n"
        "2. 台視官網：https://share.google/2wACEm4p3vbegThaU\n"
        "賽事時間及轉播場次請依各電視台公告為準。"
    )

    assert '<a href="https://share.google/ajoE0ongUyZMxSlUv"' in html
    assert '>https://share.google/ajoE0ongUyZMxSlUv</a>' in html
    assert '<a href="https://share.google/2wACEm4p3vbegThaU"' in html
    assert "賽事時間及轉播場次" in html


def test_external_web_stops_known_install_link_before_following_prose():
    pytest.importorskip("fastapi")
    from app import app_backend

    html = app_backend.format_reply_for_external_web(
        f"請透過［裝機申告🔗］{INSTALL_REPORT_URL}填寫需求。",
        {"company_code": "tdtv"},
    )

    expected_url = INSTALL_REPORT_URL.replace("&amp;", "&amp;")
    assert f'<a href="{expected_url}"' in html
    assert "</a> 填寫需求。" in html


def test_external_web_extracts_plain_url_links():
    pytest.importorskip("fastapi")
    from app import app_backend

    links = app_backend.extract_reply_links_for_external_web(
        "東森電視官網：https://share.google/ajoE0ongUyZMxSlUv\n"
        "台視官網：https://share.google/2wACEm4p3vbegThaU。"
    )

    assert links == [
        {
            "label": "https://share.google/ajoE0ongUyZMxSlUv",
            "url": "https://share.google/ajoE0ongUyZMxSlUv",
        },
        {
            "label": "https://share.google/2wACEm4p3vbegThaU",
            "url": "https://share.google/2wACEm4p3vbegThaU",
        },
    ]


def test_line_formats_corner_bracket_known_repair_link():
    text = format_reply_for_line("也可以開啟【維修申告🔗】申請報修。")

    assert "[維修申告]" in text
    assert REPAIR_REPORT_URL.replace("&amp;", "&") in text


def test_line_formats_known_links_without_icon():
    text = format_reply_for_line("可至［官網］或［裝機申告］填寫資料。", "tdtv")

    assert "[官網]" in text
    assert "https://www.tdtv.com.tw/" in text
    assert "[裝機申告]" in text
    assert "go_cust_con_install_main" in text


def test_line_formats_custom_profile_links_without_icon(monkeypatch):
    from app.services import channel_context

    def fake_profile(_company_code):
        return {
            "urls": "［官網🔗］https://example.com/",
            "value_added_urls": "［熊大心🔗］https://test.com.tw",
        }

    monkeypatch.setattr(channel_context, "get_company_profile", fake_profile)

    text = format_reply_for_line("可至［熊大心］查看服務說明。", "tdtv")

    assert "[熊大心]" in text
    assert "https://test.com.tw" in text


def test_line_formats_links_on_standalone_lines():
    text = format_reply_for_line("公司網址：［官網🔗］https://www.tdtv.com.tw/")

    assert text == "公司網址：\n[官網]\nhttps://www.tdtv.com.tw/"


def test_line_converts_html_anchor_to_plain_link_lines():
    text = format_reply_for_line(
        '公司網址：<a href="https://www.tdtv.com.tw/" target="_blank">官網</a>'
    )

    assert text == "公司網址：\n[官網]\nhttps://www.tdtv.com.tw/"
