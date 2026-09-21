import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from app.services import company_profile
from app.services.channel_context import detect_company_from_text
from app.services.company_profile import (
    DEFAULT_TV_CABLE,
    apply_company_to_memory,
    build_company_context,
    build_company_info_reply,
    extract_company_links,
    extract_company_link_url,
    get_company_options,
    get_company_profile,
    is_contextual_website_page_request,
    is_explicit_company_website_request,
    save_company_profile,
)


class CompanyProfileTest(unittest.TestCase):
    def test_default_company_is_tdtv(self):
        profile = get_company_profile()

        self.assertEqual(DEFAULT_TV_CABLE, "tdtv")
        self.assertEqual(profile["tv_cable"], "tdtv")
        self.assertEqual(profile["company_name"], "大屯有線")

    def test_unknown_company_falls_back_to_default(self):
        profile = get_company_profile("unknown")

        self.assertEqual(profile["tv_cable"], "tdtv")
        self.assertEqual(profile["company_name"], "大屯有線")

    def test_natural_contact_wording_returns_phone_only(self):
        reply = build_company_info_reply("要怎麼聯絡", "tdtv")

        self.assertIn("客服電話", reply)
        self.assertNotIn("公司網址", reply)
        self.assertNotIn("營業時間", reply)

    def test_company_options_include_tdtv(self):
        codes = {item["code"] for item in get_company_options()}

        self.assertIn("tdtv", codes)
        self.assertIn("tinp", codes)

    def test_apply_company_to_memory(self):
        memory = apply_company_to_memory({}, "cnt")

        self.assertEqual(memory["company_code"], "cnt")
        self.assertEqual(memory["company"], "中投有線")
        self.assertEqual(memory["company_profile"]["class"], "中投")

    def test_build_company_context_contains_service_info(self):
        context = build_company_context("tdtv")

        self.assertIn("服務公司：大屯有線", context)
        self.assertIn("系統台代碼：tdtv", context)
        self.assertIn("服務地區：烏日區、霧峰區、太平區、大里區", context)

    def test_build_company_address_reply(self):
        reply = build_company_info_reply("company_address", "tdtv")

        self.assertIn("大屯有線地址：台中市大里區國光路一段68號", reply)
        self.assertIn("(04)449-5678", reply)

    def test_build_service_area_reply(self):
        reply = build_company_info_reply("service_area", "tdtv")

        self.assertIn("大屯有線服務地區", reply)
        self.assertIn("烏日區、霧峰區、太平區、大里區", reply)

    def test_natural_phone_topic_returns_only_customer_service_phone(self):
        for topic in ("服務電話", "客服電話", "company_phone_inquiry"):
            with self.subTest(topic=topic):
                reply = build_company_info_reply(topic, "tdtv")

                self.assertEqual(reply, "大屯有線客服電話：(04)449-5678。")
                self.assertNotIn("地址", reply)
                self.assertNotIn("官網", reply)
                self.assertNotIn("營業時間", reply)

    def test_website_reply_only_returns_official_site(self):
        reply = build_company_info_reply("website", "tdtv")

        self.assertIn("［官網🔗］https://www.tdtv.com.tw/", reply)
        self.assertNotIn("維修申告", reply)
        self.assertNotIn("裝機申告", reply)

    def test_extract_company_links_includes_custom_value_added_links(self):
        profile = {
            "urls": "［官網］https://example.com/\n［維修申告🔗］https://example.com/repair",
            "value_added_urls": "［熊大心🔗］https://test.com.tw",
        }

        links = dict(extract_company_links(profile))

        self.assertEqual(links["官網"], "https://example.com/")
        self.assertEqual(links["維修申告"], "https://example.com/repair")
        self.assertEqual(links["熊大心"], "https://test.com.tw")
        self.assertEqual(extract_company_link_url(profile, "熊大心"), "https://test.com.tw")

    def test_contextual_website_page_request_is_not_company_website_request(self):
        text = "官網哪裡可以看到介紹?"

        self.assertTrue(is_contextual_website_page_request(text))
        self.assertFalse(is_explicit_company_website_request(text))
        self.assertTrue(is_explicit_company_website_request("大屯官網網址"))

    def test_missing_json_file_uses_builtin_default(self):
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "missing_company_profiles.json"
            with patch.object(company_profile, "COMPANY_PROFILE_PATH", str(path)):
                profile = get_company_profile("tdtv")

        self.assertEqual(profile["company_name"], "大屯有線")
        self.assertIn("大里區", profile["service_area"])

    def test_saved_profile_updates_business_hours_reply(self):
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "company_profiles.json"
            with patch.object(company_profile, "COMPANY_PROFILE_PATH", str(path)):
                save_company_profile("tdtv", {"business_hours": "每日 09:00-18:00"})
                reply = build_company_info_reply("business_hours", "tdtv")

        self.assertIn("每日 09:00-18:00", reply)

    def test_saved_service_area_updates_company_detection(self):
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "company_profiles.json"
            with patch.object(company_profile, "COMPANY_PROFILE_PATH", str(path)):
                save_company_profile("tdtv", {"service_area": "測試區、霧峰區"})
                resolution = detect_company_from_text("我是測試區用戶")

        self.assertIsNotNone(resolution)
        self.assertEqual(resolution.company_code, "tdtv")
        self.assertEqual(resolution.area, "測試區")

    def test_saved_area_outage_is_in_company_context(self):
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "company_profiles.json"
            with patch.object(company_profile, "COMPANY_PROFILE_PATH", str(path)):
                save_company_profile("tdtv", {"area_outage": "大里區寬頻異常，工程搶修中。"})
                context = build_company_context("tdtv")
                reply = build_company_info_reply("company_overview", "tdtv")

        self.assertIn("區域故障：大里區寬頻異常，工程搶修中。", context)
        self.assertIn("區域故障：大里區寬頻異常，工程搶修中。", reply)

    def test_saved_promotion_activity_updates_company_reply(self):
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "company_profiles.json"
            with patch.object(company_profile, "COMPANY_PROFILE_PATH", str(path)):
                save_company_profile("tdtv", {"promotion_activity": "新申裝寬頻請洽真人客服確認優惠。"})
                context = build_company_context("tdtv")
                reply = build_company_info_reply("promotion_activity", "tdtv")

        self.assertIn("優惠活動：新申裝寬頻請洽真人客服確認優惠。", context)
        self.assertIn("新申裝寬頻請洽真人客服確認優惠。", reply)

    def test_saved_service_products_update_context_and_company_reply(self):
        products = "有線電視\n寬頻網路\nLINE TV"
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "company_profiles.json"
            with patch.object(company_profile, "COMPANY_PROFILE_PATH", str(path)):
                save_company_profile("tdtv", {"service_products": products})
                context = build_company_context("tdtv")
                reply = build_company_info_reply("service_products", "tdtv")

        self.assertIn("目前服務產品：有線電視", context)
        self.assertIn("LINE TV", context)
        self.assertIn("目前服務的產品內容：有線電視", reply)
        self.assertIn("LINE TV", reply)

    def test_save_unknown_company_is_rejected(self):
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "company_profiles.json"
            with patch.object(company_profile, "COMPANY_PROFILE_PATH", str(path)):
                with self.assertRaises(KeyError):
                    save_company_profile("unknown", {"business_hours": "每日 09:00-18:00"})

    def test_blank_required_field_is_rejected(self):
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "company_profiles.json"
            with patch.object(company_profile, "COMPANY_PROFILE_PATH", str(path)):
                with self.assertRaises(ValueError):
                    save_company_profile("tdtv", {"service_area": ""})

    def test_non_editable_fields_are_ignored(self):
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "company_profiles.json"
            with patch.object(company_profile, "COMPANY_PROFILE_PATH", str(path)):
                profile = save_company_profile("tdtv", {"company_name": "不應被修改"})

        self.assertEqual(profile["company_name"], "大屯有線")

    def test_invalid_json_falls_back_to_builtin_default_and_logs(self):
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "company_profiles.json"
            path.write_text("{bad json", encoding="utf-8")
            with patch.object(company_profile, "COMPANY_PROFILE_PATH", str(path)), \
                    patch.object(company_profile, "log_exception") as log_exception:
                profile = get_company_profile("tdtv")

        self.assertEqual(profile["company_name"], "大屯有線")
        log_exception.assert_called_once()


if __name__ == "__main__":
    unittest.main()
