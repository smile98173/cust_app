import unittest
from datetime import datetime, timedelta, timezone

from app.services.channel_context import (
    activate_human_mode,
    apply_line_channel_context,
    apply_web_channel_context,
    build_line_customer_key,
    build_company_prompt,
    detect_company_from_text,
    get_customer_profile,
    get_line_bot_config,
    is_human_mode_active,
    normalize_channel_user_id,
    resolve_service_availability_target,
)
from app.services.memory_service import db_conn, init_db


class ChannelContextTest(unittest.TestCase):
    def setUp(self):
        init_db()
        conn = db_conn()
        cursor = conn.cursor()
        cursor.execute("DELETE FROM customer_profiles WHERE customer_key LIKE 'line:UTEST%'")
        conn.commit()
        conn.close()

    def test_web_context_confirms_company(self):
        memory = apply_web_channel_context({}, "cnt")

        self.assertEqual(memory["company_code"], "cnt")
        self.assertEqual(memory["company"], "中投有線")
        self.assertTrue(memory["channel_context"]["company_confirmed"])
        self.assertEqual(memory["channel_context"]["channel"], "web")
        self.assertNotIn("customer_key", memory["channel_context"])

    def test_web_explicit_company_overrides_sidebar_and_persists(self):
        memory = apply_web_channel_context({}, "tdtv", "北港的優惠方案")

        self.assertEqual(memory["company_code"], "pktv")
        self.assertEqual(
            memory["channel_context"]["conversation_company_override_code"],
            "pktv",
        )

        memory = apply_web_channel_context(memory, "tdtv", "一年多少錢")

        self.assertEqual(memory["company_code"], "pktv")
        self.assertEqual(
            memory["channel_context"]["resolution_source"],
            "web_conversation_override",
        )

    def test_web_sidebar_change_clears_conversation_override(self):
        memory = apply_web_channel_context({}, "tdtv", "北港的優惠方案")

        memory = apply_web_channel_context(memory, "cnt", "一年多少錢")

        self.assertEqual(memory["company_code"], "cnt")
        self.assertIsNone(
            memory["channel_context"]["conversation_company_override_code"]
        )

    def test_web_install_location_does_not_replace_selected_company(self):
        memory = apply_web_channel_context({}, "tdtv", "永康區可以裝網路嗎")

        self.assertEqual(memory["company_code"], "tdtv")
        self.assertEqual(
            memory["service_availability_context"]["target"]["company_code"],
            "hya",
        )

    def test_one_letter_company_code_does_not_match_inside_line_tv(self):
        self.assertIsNone(detect_company_from_text("LINE TV 半年多少錢"))

    def test_line_detects_company_name(self):
        memory, prompt = apply_line_channel_context({}, "我是大屯用戶，網路不能用")

        self.assertIsNone(prompt)
        self.assertEqual(memory["company_code"], "tdtv")
        self.assertTrue(memory["channel_context"]["company_confirmed"])

    def test_line_bot_config_can_fix_company(self):
        bot_config = get_line_bot_config("cltv")
        memory, prompt = apply_line_channel_context({}, "網路不能用", bot_config)

        self.assertIsNone(prompt)
        self.assertEqual(memory["company_code"], "cltv")
        self.assertEqual(memory["channel_context"]["line_bot_code"], "cltv")
        self.assertEqual(memory["channel_context"]["resolution_source"], "line_bot_config")

    def test_test_bot_uses_top_like_area_resolution(self):
        bot_config = get_line_bot_config("test_bot")

        self.assertEqual(bot_config["bot_code"], "test_bot")
        self.assertEqual(bot_config["default_tv_cable"], "")
        self.assertIn("human_group_id", bot_config)
        self.assertIn("human_access_token", bot_config)

        memory, prompt = apply_line_channel_context({}, "網路不能用", bot_config)

        self.assertIsNotNone(prompt)
        self.assertFalse(memory["channel_context"]["company_confirmed"])
        self.assertEqual(memory["channel_context"]["line_bot_code"], "test_bot")

    def test_line_detects_company_by_area(self):
        resolution = detect_company_from_text("我住大里區，家裡電視不能看")

        self.assertIsNotNone(resolution)
        self.assertEqual(resolution.company_code, "tdtv")
        self.assertEqual(resolution.area, "大里區")
        self.assertEqual(resolution.source, "service_area")

    def test_line_detects_jia_guang_city_area(self):
        resolution = detect_company_from_text("我在西屯區，網路不能用")

        self.assertIsNotNone(resolution)
        self.assertEqual(resolution.company_code, "toplight")
        self.assertEqual(resolution.area, "西屯區")

    def test_line_detects_west_coast_area(self):
        resolution = detect_company_from_text("沙鹿區電視沒有畫面")

        self.assertIsNotNone(resolution)
        self.assertEqual(resolution.company_code, "wctv")
        self.assertEqual(resolution.area, "沙鹿區")

    def test_line_detects_area_without_administrative_suffix(self):
        resolution = detect_company_from_text("大甲")

        self.assertIsNotNone(resolution)
        self.assertEqual(resolution.company_code, "wctv")
        self.assertEqual(resolution.area, "大甲區")

    def test_line_detects_area_without_suffix_in_context(self):
        resolution = detect_company_from_text("我是大里用戶")

        self.assertIsNotNone(resolution)
        self.assertEqual(resolution.company_code, "tdtv")
        self.assertEqual(resolution.area, "大里區")

    def test_line_asks_company_when_unknown(self):
        memory, prompt = apply_line_channel_context({}, "網路不能用")

        self.assertFalse(memory["channel_context"]["company_confirmed"])
        self.assertEqual(prompt, build_company_prompt())
        self.assertIn("服務地區", prompt)
        self.assertIn("行政區", prompt)
        self.assertNotIn("想詢問哪一個系統台", prompt)

    def test_normalize_channel_user_id(self):
        self.assertEqual(normalize_channel_user_id("line", "U123"), "line:U123")
        self.assertEqual(normalize_channel_user_id("line", "line:U123"), "line:U123")

    def test_build_line_customer_key(self):
        self.assertEqual(build_line_customer_key("U123"), "line:U123")
        self.assertEqual(build_line_customer_key("line:U123"), "line:U123")
        self.assertIsNone(build_line_customer_key(""))
        self.assertIsNone(build_line_customer_key("unknown"))

    def test_line_customer_profile_is_saved_from_confirmed_bot_default(self):
        customer_key = "line:UTEST_SYNC_1"
        bot_config = get_line_bot_config("tdtv")

        memory, prompt = apply_line_channel_context(
            {},
            "網路不能用",
            bot_config,
            customer_key=customer_key,
            user_id="line:tdtv:UTEST_SYNC_1",
        )

        self.assertIsNone(prompt)
        self.assertEqual(memory["company_code"], "tdtv")
        self.assertEqual(memory["customer_key"], customer_key)
        self.assertEqual(memory["channel_context"]["customer_key"], customer_key)

        profile = get_customer_profile(customer_key)
        self.assertIsNotNone(profile)
        self.assertEqual(profile["last_company_code"], "tdtv")
        self.assertEqual(profile["last_line_bot_code"], "tdtv")

    def test_top_bot_uses_existing_customer_profile_before_prompt(self):
        customer_key = "line:UTEST_SYNC_2"
        apply_line_channel_context(
            {},
            "網路不能用",
            get_line_bot_config("tdtv"),
            customer_key=customer_key,
            user_id="line:tdtv:UTEST_SYNC_2",
        )

        memory, prompt = apply_line_channel_context(
            {},
            "網路不能用",
            get_line_bot_config("top"),
            customer_key=customer_key,
            user_id="line:top:UTEST_SYNC_2",
        )

        self.assertIsNone(prompt)
        self.assertEqual(memory["company_code"], "tdtv")
        self.assertEqual(memory["channel_context"]["line_bot_code"], "top")
        self.assertEqual(memory["channel_context"]["resolution_source"], "customer_profile")

    def test_customer_profile_overrides_other_bot_default(self):
        customer_key = "line:UTEST_SYNC_3"
        apply_line_channel_context(
            {},
            "網路不能用",
            get_line_bot_config("tdtv"),
            customer_key=customer_key,
            user_id="line:tdtv:UTEST_SYNC_3",
        )

        memory, prompt = apply_line_channel_context(
            {},
            "網路不能用",
            get_line_bot_config("cltv"),
            customer_key=customer_key,
            user_id="line:cltv:UTEST_SYNC_3",
        )

        self.assertIsNone(prompt)
        self.assertEqual(memory["company_code"], "tdtv")
        self.assertEqual(memory["channel_context"]["line_bot_code"], "cltv")
        self.assertEqual(memory["channel_context"]["resolution_source"], "customer_profile")

    def test_explicit_line_company_updates_customer_profile(self):
        customer_key = "line:UTEST_SYNC_4"
        apply_line_channel_context(
            {},
            "網路不能用",
            get_line_bot_config("tdtv"),
            customer_key=customer_key,
            user_id="line:tdtv:UTEST_SYNC_4",
        )

        memory, prompt = apply_line_channel_context(
            {},
            "我是佳聯用戶",
            get_line_bot_config("top"),
            customer_key=customer_key,
            user_id="line:top:UTEST_SYNC_4",
        )

        self.assertIsNone(prompt)
        self.assertEqual(memory["company_code"], "cltv")
        self.assertEqual(memory["channel_context"]["resolution_source"], "company_name")

        profile = get_customer_profile(customer_key)
        self.assertEqual(profile["last_company_code"], "cltv")
        self.assertEqual(profile["last_line_bot_code"], "top")

    def test_install_location_does_not_overwrite_remembered_company(self):
        customer_key = "line:UTEST_INSTALL_1"
        apply_line_channel_context(
            {},
            "網路不能用",
            get_line_bot_config("tdtv"),
            customer_key=customer_key,
            user_id="line:tdtv:UTEST_INSTALL_1",
        )

        memory, prompt = apply_line_channel_context(
            {},
            "爸媽住永康，可以裝網路嗎",
            get_line_bot_config("top"),
            customer_key=customer_key,
            user_id="line:top:UTEST_INSTALL_1",
        )

        self.assertIsNone(prompt)
        self.assertEqual(memory["company_code"], "tdtv")
        self.assertEqual(memory["service_availability_context"]["target"]["company_code"], "hya")
        self.assertEqual(get_customer_profile(customer_key)["last_company_code"], "tdtv")

    def test_install_location_uses_query_area_instead_of_bot_default(self):
        memory, prompt = apply_line_channel_context(
            {},
            "大里區可以裝網路嗎",
            get_line_bot_config("cltv"),
        )

        self.assertIsNone(prompt)
        self.assertEqual(memory["company_code"], "cltv")
        self.assertEqual(memory["service_availability_context"]["target"]["company_code"], "tdtv")

    def test_top_install_query_without_saved_company_does_not_prompt_company(self):
        memory, prompt = apply_line_channel_context(
            {},
            "永康區可以裝網路嗎",
            get_line_bot_config("top"),
        )

        self.assertIsNone(prompt)
        self.assertFalse(memory["channel_context"]["company_confirmed"])
        self.assertEqual(memory["service_availability_context"]["target"]["company_code"], "hya")

    def test_assisted_install_query_uses_assisted_person_location(self):
        context = resolve_service_availability_target(
            "我住大里，想幫台南永康的爸媽問能不能裝網路"
        )

        self.assertEqual(context["status"], "resolved")
        self.assertEqual(context["target"]["company_code"], "hya")
        self.assertEqual(context["target"]["area"], "永康區")

    def test_multiple_install_locations_require_clarification(self):
        context = resolve_service_availability_target("大里和永康哪裡可以裝網路")

        self.assertEqual(context["status"], "ambiguous")
        self.assertEqual(len(context["candidates"]), 2)

    def test_company_name_and_its_area_are_one_install_target(self):
        context = resolve_service_availability_target("新永安永康區可以裝網路嗎")

        self.assertEqual(context["status"], "resolved")
        self.assertEqual(context["target"]["company_code"], "hya")
        self.assertEqual(context["target"]["area"], "永康區")

    def test_unknown_county_city_is_preserved_as_unmapped_location(self):
        context = resolve_service_availability_target("台北市可以裝你們網路嗎")

        self.assertEqual(context["status"], "unmapped")
        self.assertEqual(context["location"], "台北市")

    def test_generic_other_county_question_still_has_missing_location(self):
        context = resolve_service_availability_target("其他縣市可以裝網路嗎")

        self.assertEqual(context["status"], "missing")

    def test_human_mode_active_and_expired(self):
        now = datetime(2026, 5, 22, 10, 0, tzinfo=timezone(timedelta(hours=8)))
        memory = activate_human_mode({}, {"bot_code": "test_bot", "display_name": "測試 Bot"}, now=now)

        self.assertTrue(is_human_mode_active(memory, now + timedelta(minutes=5)))
        self.assertTrue(memory["channel_context"]["human_mode"])

        self.assertFalse(is_human_mode_active(memory, now + timedelta(minutes=26)))
        self.assertFalse(memory["channel_context"]["human_mode"])


if __name__ == "__main__":
    unittest.main()
