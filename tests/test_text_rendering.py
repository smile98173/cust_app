import unittest

from app.services.text_rendering import (
    escape_streamlit_markdown_literals,
    html_anchors_to_markdown,
    text_linebreaks_to_html,
)


class TextRenderingTest(unittest.TestCase):
    def test_html_anchor_is_converted_to_single_markdown_link(self):
        value = (
            '請前往台基科官網 <a href="https://www.tinp.net.tw/" '
            'target="_blank" rel="noopener noreferrer">開啟連結</a>，再登入會員。'
        )

        rendered = html_anchors_to_markdown(value)

        self.assertEqual(
            rendered,
            "請前往台基科官網 [開啟連結](https://www.tinp.net.tw/)，再登入會員。",
        )
        self.assertNotIn("<a href=", rendered)

    def test_plain_numbered_lines_do_not_remain_markdown_source(self):
        source = "一起說明：\n\n1. 確認真偽：請洽官方。\n\n2. 領獎方式：攜帶證件。"

        rendered = text_linebreaks_to_html(source)

        self.assertEqual(
            rendered,
            "一起說明：<br><br>1. 確認真偽：請洽官方。"
            "<br><br>2. 領獎方式：攜帶證件。",
        )
        self.assertNotIn("\n", rendered)

    def test_customer_date_ranges_do_not_become_markdown_strikethrough(self):
        source = "2026/08/01裝機~2026/12/31 退租~要角多少違約金？"

        rendered = escape_streamlit_markdown_literals(source)

        self.assertEqual(
            rendered,
            r"2026/08/01裝機\~2026/12/31 退租\~要角多少違約金？",
        )
