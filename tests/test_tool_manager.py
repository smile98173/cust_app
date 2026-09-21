import unittest
from unittest.mock import ANY, Mock, patch

from app.services.tool_manager import (
    CUST_API_META_KEY,
    call_tool,
    call_json_text,
    call_json_text2,
    call_search_bill,
    call_contract_info,
    call_channel_no,
    customer_not_found_response,
    call_return_line_endpoint,
    exec_search_contract_info,
    exec_search_bill,
    exec_send_message,
    exec_payment_bill_batch,
    exec_bill_return_line_internet,
    exec_bill_return_line_tv,
    format_speed_text,
    get_token,
    get_available_functions,
    sanitize_cust_api_payload,
    validate_customer_identity,
)


def verified_receipt_evidence(bills):
    return {"verified": True, "bills": bills}


class ToolManagerTest(unittest.TestCase):
    def test_format_speed_text_handles_fullwidth_separator_and_labels(self):
        self.assertEqual(
            format_speed_text("下載1000000K／上傳600000K"),
            "下載 1 Gbps / 上傳 600 Mbps",
        )

    def test_call_json_text_uses_custnum_payload(self):
        payload = call_json_text(True, {"custnum": "1082281"}, "token-value")

        self.assertEqual(payload["token"], "token-value")
        self.assertEqual(payload["custNo"], "1082281")
        self.assertEqual(payload["custTel"], "")
        self.assertEqual(payload["custCName"], "")

    def test_tv_reactivation_not_found_with_custnum_uses_neutral_message(self):
        result = customer_not_found_response("bill_return_line_tv", used_custnum=True)

        self.assertFalse(result["success"])
        self.assertEqual(result["data"]["missing"], [])
        self.assertIn("無法確認", result["message"])
        self.assertNotIn("客戶編號是否正確", result["message"])

    def test_tv_reactivation_preserves_customer_api_message(self):
        with patch(
            "app.services.tool_manager.call_customer_endpoint",
            return_value=(True, {"code": "0099", "msg": "經查詢，您的電視服務狀態正常，無需進行復線處理。"}),
        ):
            result = call_return_line_endpoint(
                "bill_return_line_tv",
                "https://example.test/return-line-tv",
                {"custNo": "1078971"},
        )

        self.assertTrue(result["success"])
        self.assertEqual(result["message"], "經查詢，您的電視服務狀態正常，無需進行復線處理。")
        self.assertNotIn("customer_service_status", result["data"])

    def test_call_json_text2_uses_name_phone_payload(self):
        payload = call_json_text2(
            {"name": "王大明", "phone": "09-1234-5678"},
            "token-value",
        )

        self.assertEqual(payload["custCName"], "王大明")
        self.assertEqual(payload["custTel"], "0912345678")

    @patch("app.services.tool_manager.time.sleep")
    @patch("app.services.tool_manager.log_cust_api_diagnostic")
    @patch("app.services.tool_manager.requests.get")
    def test_get_token_retries_transient_connection_error(self, requests_get, diagnostic_log, sleep):
        import requests

        response = Mock()
        response.status_code = 200
        response.json.return_value = {"token": "token-value"}
        requests_get.side_effect = [
            requests.exceptions.ConnectionError("remote closed"),
            response,
        ]

        token = get_token()

        self.assertEqual(token, "token-value")
        self.assertEqual(requests_get.call_count, 2)
        sleep.assert_called_once_with(0.5)
        self.assertEqual(diagnostic_log.call_count, 2)
        first_call = diagnostic_log.call_args_list[0].kwargs
        second_call = diagnostic_log.call_args_list[1].kwargs
        self.assertEqual(first_call["stage"], "token")
        self.assertFalse(first_call["success"])
        self.assertEqual(first_call["error_type"], "ConnectionError")
        self.assertEqual(first_call["attempt"], 1)
        self.assertEqual(first_call["max_attempts"], 3)
        self.assertTrue(second_call["success"])
        self.assertEqual(second_call["attempt"], 2)
        self.assertEqual(second_call["max_attempts"], 3)

    @patch("app.services.tool_manager.time.sleep")
    @patch("app.services.tool_manager.log_cust_api_diagnostic")
    @patch("app.services.tool_manager.requests.get")
    def test_get_token_retries_transient_http_status(self, requests_get, diagnostic_log, sleep):
        busy = Mock()
        busy.status_code = 503
        busy.text = "temporarily unavailable"
        success = Mock()
        success.status_code = 200
        success.json.return_value = {"token": "token-value"}
        requests_get.side_effect = [busy, success]

        token = get_token()

        self.assertEqual(token, "token-value")
        self.assertEqual(requests_get.call_count, 2)
        sleep.assert_called_once_with(0.5)
        first_call = diagnostic_log.call_args_list[0].kwargs
        second_call = diagnostic_log.call_args_list[1].kwargs
        self.assertEqual(first_call["http_status"], 503)
        self.assertEqual(first_call["attempt"], 1)
        self.assertTrue(second_call["success"])
        self.assertEqual(second_call["attempt"], 2)

    def test_sanitize_cust_api_payload_masks_sensitive_values(self):
        payload = sanitize_cust_api_payload({
            "token": "secret-token",
            "custNo": "A123456789",
            "custTel": "0988555333",
            "custCName": "王大明",
        })

        self.assertEqual(payload["identity_mode"], "custNo")
        self.assertTrue(payload["has_token"])
        self.assertTrue(payload["has_custNo"])
        self.assertEqual(payload["custNo_length"], 10)
        self.assertEqual(payload["custNo_last4"], "6789")
        self.assertEqual(payload["custTel_last3"], "333")
        self.assertEqual(payload["custCName_length"], 3)
        self.assertNotIn("secret-token", str(payload))
        self.assertNotIn("0988555333", str(payload))
        self.assertNotIn("王大明", str(payload))

    def test_validate_customer_identity_returns_missing_invalid_fields(self):
        missing, name, phone = validate_customer_identity("查帳單", "12345")

        self.assertEqual(missing, ["phone"])
        self.assertEqual(name, "查帳單")
        self.assertEqual(phone, "12345")

    def test_exec_search_bill_invalid_phone_does_not_fetch_token(self):
        with patch("app.services.tool_manager.get_token") as get_token:
            result = exec_search_bill(name="王大明", phone="12345")

        get_token.assert_not_called()
        self.assertFalse(result["success"])
        self.assertEqual(result["data"]["missing"], ["identity_pair"])

    def test_exec_search_bill_uses_mock_bill_data_by_default(self):
        with patch("app.services.tool_manager.get_token") as get_token:
            result = exec_search_bill(name="王大明", phone="0988555666")

        get_token.assert_not_called()
        self.assertTrue(result["success"])
        self.assertIn("寬頻月租：799元（已繳費迄日：2026-05-31）", result["message"])
        self.assertIn("有線電視：600元（已繳費迄日：2026-06-05）", result["message"])
        self.assertIn("合計：1399元", result["message"])
        self.assertIn("mock-api.local", result["message"])
        self.assertTrue(result["data"]["raw"]["mock"])
        self.assertIsInstance(result["data"]["raw"]["response"]["data"], list)

    def test_exec_search_bill_accepts_customer_number_without_name_or_phone(self):
        with (
            patch("app.services.tool_manager.CUST_API_USE_MOCK", False),
            patch(
                "app.services.tool_manager.get_token_with_timing",
                return_value=(
                    "token-value",
                    {
                        "type": "token",
                        "name": "get_token",
                        "elapsed_sec": 0.0,
                        "success": True,
                    },
                ),
            ),
            patch(
                "app.services.tool_manager.call_search_bill",
                return_value={
                    "success": True,
                    "tool_name": "search_bill",
                    "message": "ok",
                    "data": {},
                },
            ) as call_search_bill_mock,
        ):
            result = exec_search_bill(custnum=" 905397 ", authenticated_custnum=True)

        self.assertTrue(result["success"])
        payload = call_search_bill_mock.call_args.args[0]
        self.assertEqual(payload["custNo"], "905397")
        self.assertEqual(payload["custCName"], "")
        self.assertEqual(payload["custTel"], "")

    def test_exec_search_bill_rejects_customer_number_with_symbol_without_fetching_token(self):
        with patch("app.services.tool_manager.get_token_with_timing") as get_token:
            result = exec_search_bill(custnum="-046793")

        get_token.assert_not_called()
        self.assertFalse(result["success"])
        self.assertIn("客戶編號、戶名、登記電話任兩項", result["message"])
        self.assertEqual(result["data"]["missing"], ["identity_pair"])

    def test_exec_search_bill_rejects_zero_prefixed_customer_number_without_fetching_token(self):
        with patch("app.services.tool_manager.get_token_with_timing") as get_token:
            result = exec_search_bill(custnum="046793")

        get_token.assert_not_called()
        self.assertFalse(result["success"])
        self.assertIn("客戶編號、戶名、登記電話任兩項", result["message"])
        self.assertEqual(result["data"]["missing"], ["identity_pair"])

    def test_call_search_bill_parses_unpaid_bill_response(self):
        with patch(
            "app.services.tool_manager.call_customer_endpoint",
            return_value=(True, {"billType": "寬頻月租", "shoAmt": "799"}),
        ):
            result = call_search_bill({"token": "token-value"})

        self.assertTrue(result["success"])
        self.assertEqual(result["message"], "寬頻月租：799元")

    def test_call_search_bill_includes_cust_api_timing_metadata(self):
        with patch(
            "app.services.tool_manager.call_customer_endpoint",
            return_value=(
                True,
                {
                    "billType": "寬頻月租",
                    "shoAmt": "799",
                    CUST_API_META_KEY: {
                        "type": "endpoint",
                        "url": "https://example.test/bill",
                        "elapsed_sec": 0.321,
                        "success": True,
                    },
                },
            ),
        ):
            result = call_search_bill({"token": "token-value"})

        self.assertTrue(result["success"])
        self.assertEqual(result["cust_api"]["endpoint_sec"], 0.321)
        self.assertEqual(result["cust_api"]["total_sec"], 0.321)
        self.assertEqual(result["data"]["cust_api"]["total_sec"], 0.321)
        self.assertNotIn(CUST_API_META_KEY, result["data"]["raw"])

    @patch("app.services.tool_manager.log_cust_api_diagnostic")
    @patch("app.services.tool_manager.requests.get")
    def test_call_customer_endpoint_logs_raw_code_and_msg_without_identity(self, requests_get, diagnostic_log):
        response = requests_get.return_value
        response.status_code = 200
        response.json.return_value = {"code": "0000", "msg": "查無客戶未繳帳單"}

        from app.services.tool_manager import call_customer_endpoint

        ok, _ = call_customer_endpoint(
            "https://example.test/cust/getCustBill",
            {
                "token": "secret-token",
                "custNo": "905397",
                "custTel": "",
                "custCName": "",
            },
        )

        self.assertTrue(ok)
        diagnostic_log.assert_called_once_with(
            tool_name="unknown",
            url="https://example.test/cust/getCustBill",
            payload={
                "token": "secret-token",
                "custNo": "905397",
                "custTel": "",
                "custCName": "",
            },
            http_status=200,
            response_data={"code": "0000", "msg": "查無客戶未繳帳單"},
            stage="endpoint",
            elapsed_sec=ANY,
            success=True,
        )

    @patch("app.services.tool_manager.log_cust_api_diagnostic")
    @patch("app.services.tool_manager.requests.get")
    def test_call_customer_endpoint_logs_timeout_details(self, requests_get, diagnostic_log):
        import requests

        requests_get.side_effect = requests.ReadTimeout("upstream timed out")

        from app.services.tool_manager import call_customer_endpoint

        ok, data = call_customer_endpoint(
            "https://example.test/cust/getCustBill",
            {"custNo": "905397"},
        )

        self.assertFalse(ok)
        self.assertEqual(data["error"], "upstream timed out")
        diagnostic_log.assert_called_once_with(
            tool_name="unknown",
            url="https://example.test/cust/getCustBill",
            payload={"custNo": "905397"},
            http_status=None,
            error_type="ReadTimeout",
            stage="endpoint",
            elapsed_sec=ANY,
            success=False,
            error_detail="upstream timed out",
        )

    def test_call_search_bill_includes_due_date_when_api_returns_it(self):
        with patch(
            "app.services.tool_manager.call_customer_endpoint",
            return_value=(
                True,
                {
                    "billType": "寬頻月租",
                    "shoAmt": "799",
                    "payDueDate": "2026-05-31",
                },
            ),
        ):
            result = call_search_bill({"token": "token-value"})

        self.assertTrue(result["success"])
        self.assertIn("寬頻月租：799元", result["message"])
        self.assertIn("繳費到期日：2026-05-31", result["message"])

    def test_call_search_bill_parses_new_bill_list_response_with_due_dates(self):
        with patch(
            "app.services.tool_manager.call_customer_endpoint",
            return_value=(
                True,
                {
                    "data": [
                        {"billType": "寬頻月租", "shoAmt": "799", "xEdate": "2026-05-31"},
                        {"billType": "有線電視", "shoAmt": "600", "xEdate": "2026-06-05"},
                    ],
                },
            ),
        ):
            result = call_search_bill({"token": "token-value"})

        self.assertTrue(result["success"])
        self.assertIn("寬頻月租：799元（已繳費迄日：2026-05-31）", result["message"])
        self.assertIn("有線電視：600元（已繳費迄日：2026-06-05）", result["message"])
        self.assertIn("合計：1399元", result["message"])

    def test_call_search_bill_filters_zero_show_amt_from_bill_list(self):
        with patch(
            "app.services.tool_manager.call_customer_endpoint",
            return_value=(
                True,
                {
                    "data": [
                        {"billType": "寬頻月租", "showAmt": "799", "xEdate": "2026-05-31"},
                        {"billType": "0元帳單", "showAmt": "0", "xEdate": "2026-06-05"},
                        {"billType": "空白金額", "shoAmt": "", "xEdate": "2026-06-06"},
                    ],
                },
            ),
        ):
            result = call_search_bill({"token": "token-value"})

        self.assertTrue(result["success"])
        self.assertIn("寬頻月租：799元（已繳費迄日：2026-05-31）", result["message"])
        self.assertIn("合計：799元", result["message"])
        self.assertEqual(result["data"]["bill_status"], "payable")
        self.assertNotIn("0元帳單", result["message"])
        self.assertNotIn("空白金額", result["message"])

    def test_call_search_bill_zero_show_amt_single_bill_means_no_unpaid_bill(self):
        with patch(
            "app.services.tool_manager.call_customer_endpoint",
            return_value=(True, {"billType": "0元帳單", "showAmt": "0"}),
        ):
            result = call_search_bill({"token": "token-value"})

        self.assertTrue(result["success"])
        self.assertIn("目前帳務狀況正常", result["message"])
        self.assertEqual(result["data"]["bill_status"], "no_unpaid")
        self.assertNotIn("0元帳單", result["message"])

    def test_call_search_bill_new_empty_bill_list_means_no_unpaid_bill(self):
        with patch(
            "app.services.tool_manager.call_customer_endpoint",
            return_value=(True, {"data": []}),
        ):
            result = call_search_bill({"token": "token-value"})

        self.assertTrue(result["success"])
        self.assertIn("尚無須繳納的費用", result["message"])
        self.assertEqual(result["data"]["bill_status"], "no_unpaid")

    def test_call_search_bill_success_message_without_bill_data_means_normal_status(self):
        with patch(
            "app.services.tool_manager.call_customer_endpoint",
            return_value=(True, {"code": "0000", "msg": "成功"}),
        ):
            result = call_search_bill({"token": "token-value"})

        self.assertTrue(result["success"])
        self.assertEqual(
            result["message"],
            "我已幫您確認，目前帳務狀況正常，沒有需要處理或繳費的項目",
        )
        self.assertEqual(result["data"]["bill_status"], "no_unpaid")

    def test_call_search_bill_asks_for_identity_when_customer_not_found(self):
        with patch(
            "app.services.tool_manager.call_customer_endpoint",
            return_value=(True, {"msg": "查無客戶資料"}),
        ):
            result = call_search_bill({"token": "token-value"})

        self.assertFalse(result["success"])
        self.assertEqual(result["data"]["missing"], ["name", "phone"])

    def test_call_search_bill_does_not_ask_for_customer_number_when_custnum_not_found(self):
        with patch(
            "app.services.tool_manager.call_customer_endpoint",
            return_value=(True, {"msg": "查無客戶資料"}),
        ):
            result = call_search_bill(
                {
                    "token": "token-value",
                    "custNo": "1124249",
                    "custTel": "",
                    "custCName": "",
                }
            )

        self.assertFalse(result["success"])
        self.assertEqual(result["data"]["missing"], [])
        self.assertIn("登入資料", result["message"])
        self.assertNotIn("客戶編號是否正確", result["message"])
        self.assertNotIn("戶名與電話", result["message"])

    def test_call_search_bill_customer_not_found_status_ignores_stale_bill_data(self):
        with patch(
            "app.services.tool_manager.call_customer_endpoint",
            return_value=(
                True,
                {
                    "code": "0099",
                    "msg": "查無客戶資料",
                    "data": [{"billType": "不應顯示", "showAmt": "15704"}],
                },
            ),
        ):
            result = call_search_bill({"token": "token-value"})

        self.assertFalse(result["success"])
        self.assertIn("查詢不到您的資料", result["message"])
        self.assertNotIn("15704", result["message"])

    def test_mock_contract_tool_returns_preloaded_contract(self):
        result = exec_search_contract_info(custnum="1082281")

        self.assertTrue(result["success"])
        self.assertIn("已為您查詢目前服務與合約資訊", result["message"])
        self.assertNotIn("基本頻道（CATV）", result["message"])
        self.assertNotIn("數位電視頻道（DTV）", result["message"])
        self.assertIn("FTTH-EPON 流量測試方案（EPON）", result["message"])
        self.assertIn("狀態：使用中", result["message"])
        self.assertIn("速率：下載 1 Gbps / 上傳 600 Mbps", result["message"])
        self.assertIn("LineTV（OTT）", result["message"])
        self.assertIn("合約：無綁約", result["message"])
        self.assertIn("合約到期日", result["message"])
        self.assertIn("getCustProd", result["message"])
        self.assertTrue(result["data"]["raw"]["mock"])

    def test_call_contract_info_parses_product_list_response(self):
        with patch(
            "app.services.tool_manager.call_customer_endpoint",
            return_value=(
                True,
                {
                    "data": [
                        {
                            "conDate": "無合約",
                            "pkgPrdName": "基本頻道",
                            "useStatusName": "使用中",
                            "prdTypeName": "CATV",
                        },
                        {
                            "conDate": "2016-03-31",
                            "pkgPrdName": "數位電視頻道",
                            "useStatusName": "使用中",
                            "prdTypeName": "DTV",
                        },
                        {
                            "speed": "1000000K/600000K",
                            "conDate": "2026-12-31",
                            "pkgPrdName": "FTTH-EPON 流量測試方案",
                            "useStatusName": "使用中",
                            "prdTypeName": "EPON",
                        },
                        {
                            "conDate": "無合約",
                            "pkgPrdName": "LineTV",
                            "useStatusName": "使用中",
                            "prdTypeName": "OTT",
                        },
                        {
                            "conDate": "2024-01-05",
                            "pkgPrdName": "LineTV",
                            "useStatusName": "停用",
                            "prdTypeName": "LINE TV",
                        },
                        {
                            "conDate": "2023-09-06",
                            "pkgPrdName": "LiTV",
                            "useStatusName": "停用",
                            "prdTypeName": "LiTV",
                        },
                    ],
                    "code": "0000",
                    "msg": "成功",
                },
            ),
        ):
            result = call_contract_info({"token": "token-value"})

        self.assertTrue(result["success"])
        self.assertNotIn("基本頻道（CATV）", result["message"])
        self.assertNotIn("數位電視頻道（DTV）", result["message"])
        self.assertIn("FTTH-EPON 流量測試方案（EPON）", result["message"])
        self.assertIn("速率：下載 1 Gbps / 上傳 600 Mbps", result["message"])
        self.assertIn("合約到期日：2026-12-31", result["message"])
        self.assertIn("LineTV（OTT）", result["message"])
        self.assertIn("合約：無綁約", result["message"])
        self.assertNotIn("2024-01-05", result["message"])
        self.assertNotIn("LiTV（LiTV）", result["message"])
        self.assertNotIn("狀態：停用", result["message"])

    def test_mock_identity_apis_use_same_default_customer(self):
        with patch("app.services.tool_manager.get_token") as get_token:
            send_result = exec_send_message(name="王大明", phone="0988555666")
            internet_result = exec_bill_return_line_internet(name="王大明", phone="0988555666")
            tv_result = exec_bill_return_line_tv(name="王大明", phone="0988555666")

        get_token.assert_not_called()
        self.assertTrue(send_result["success"])
        self.assertTrue(internet_result["success"])
        self.assertTrue(tv_result["success"])
        self.assertIn("mock-api.local", send_result["message"])
        self.assertIn("mock-api.local", internet_result["message"])
        self.assertIn("mock-api.local", tv_result["message"])

    def test_mock_identity_apis_accept_required_customer_identity(self):
        send_result = exec_send_message(custnum="1082281", phone="0988555666")
        internet_result = exec_bill_return_line_internet(
            custnum="1082281",
            authenticated_custnum=True,
        )
        tv_result = exec_bill_return_line_tv(
            custnum="1082281",
            authenticated_custnum=True,
        )

        self.assertTrue(send_result["success"])
        self.assertTrue(internet_result["success"])
        self.assertTrue(tv_result["success"])
        self.assertEqual(send_result["data"]["raw"]["request"]["custNo"], "1082281")
        self.assertEqual(send_result["data"]["raw"]["request"]["custTel"], "0988555666")
        self.assertEqual(internet_result["data"]["raw"]["request"]["custNo"], "1082281")
        self.assertEqual(tv_result["data"]["raw"]["request"]["custNo"], "1082281")

    def test_send_message_reply_mentions_registered_phone_only(self):
        send_result = exec_send_message(custnum="1082281", phone="0988555666")

        self.assertTrue(send_result["success"])
        self.assertIn("登記電話", send_result["message"])
        self.assertIn("無法改寄或指定其他電話", send_result["message"])

    def test_send_message_requires_phone_with_customer_number(self):
        result = exec_send_message(custnum="1082281")

        self.assertFalse(result["success"])
        self.assertEqual(result["data"]["missing"], ["phone"])
        self.assertIn("登入資料", result["message"])
        self.assertNotIn("客戶編號", result["message"])
        self.assertIn("登記電話", result["message"])

    def test_mock_identity_apis_do_not_reprompt_custnum_for_unknown_customer_number(self):
        send_result = exec_send_message(custnum="1124249", phone="0988555666")
        bill_result = exec_search_bill(custnum="1124249", authenticated_custnum=True)
        contract_result = exec_search_contract_info(custnum="1124249")

        self.assertFalse(send_result["success"])
        self.assertEqual(send_result["data"]["missing"], [])
        self.assertIn("登入資料", send_result["message"])
        self.assertNotIn("客戶編號是否正確", send_result["message"])
        self.assertNotIn("戶名與電話", send_result["message"])

        for result in [bill_result, contract_result]:
            self.assertFalse(result["success"])
            self.assertEqual(result["data"]["missing"], [])
            self.assertIn("登入資料", result["message"])
            self.assertNotIn("客戶編號是否正確", result["message"])
            self.assertNotIn("戶名與電話", result["message"])

    def test_real_identity_tools_send_custnum_payload_when_available(self):
        with patch("app.services.tool_manager.CUST_API_USE_MOCK", False), patch(
            "app.services.tool_manager.get_token",
            return_value="token-value",
        ), patch(
            "app.services.tool_manager.send_message",
            return_value={"success": True, "tool_name": "send_message", "message": "ok", "data": {}},
        ) as send_api, patch(
            "app.services.tool_manager.bill_return_line_internet",
            return_value={"success": True, "tool_name": "bill_return_line_internet", "message": "ok", "data": {}},
        ) as internet_api, patch(
            "app.services.tool_manager.bill_return_line_tv",
            return_value={"success": True, "tool_name": "bill_return_line_tv", "message": "ok", "data": {}},
        ) as tv_api:
            send_result = exec_send_message(custnum="1082281", phone="0988555666")
            internet_result = exec_bill_return_line_internet(
                custnum="1082281",
                authenticated_custnum=True,
            )
            tv_result = exec_bill_return_line_tv(
                custnum="1082281",
                authenticated_custnum=True,
            )

        self.assertTrue(send_result["success"])
        self.assertTrue(internet_result["success"])
        self.assertTrue(tv_result["success"])
        expected_custnum_payload = {
            "token": "token-value",
            "custTel": "",
            "custCName": "",
            "custNo": "1082281",
        }
        send_api.assert_called_once_with({
            "token": "token-value",
            "custTel": "0988555666",
            "custCName": "",
            "custNo": "1082281",
        })
        internet_api.assert_called_once_with(expected_custnum_payload)
        tv_api.assert_called_once_with(expected_custnum_payload)

    def test_guest_identity_tool_schemas_require_any_two_identity_fields(self):
        schemas = {
            item["name"]: item
            for item in get_available_functions({
                "known_info": {
                    "custnum": "1082281",
                    "custnum_source": "user_provided",
                },
            })
        }

        for tool_name in [
            "search_bill",
            "bill_return_line_internet",
            "bill_return_line_tv",
        ]:
            parameters = schemas[tool_name]["parameters"]
            self.assertEqual(
                parameters["anyOf"],
                [
                    {"required": ["custnum", "name"]},
                    {"required": ["custnum", "phone"]},
                    {"required": ["name", "phone"]},
                ],
            )
            self.assertEqual(
                set(parameters["properties"]),
                {"custnum", "name", "phone"},
            )

        self.assertEqual(schemas["send_message"]["parameters"]["required"], ["name", "phone"])
        self.assertNotIn("custnum", schemas["send_message"]["parameters"]["properties"])

    def test_identity_tool_schemas_use_custnum_for_authenticated_web_context(self):
        memory = {
            "is_logged_in": True,
            "known_info": {
                "custnum": "1082281",
                "custnum_source": "web_authenticated",
                "is_logged_in": True,
            },
        }
        schemas = {item["name"]: item for item in get_available_functions(memory)}

        for tool_name in [
            "search_bill",
            "bill_return_line_internet",
            "bill_return_line_tv",
        ]:
            self.assertEqual(schemas[tool_name]["parameters"]["required"], ["custnum"])

    def test_guest_identity_tools_send_all_provided_identity_fields(self):
        memory = {
            "known_info": {
                "custnum": "1082281",
                "custnum_source": "user_provided",
                "name": "王大明",
                "phone": "0988555666",
            },
        }

        for tool_name in [
            "search_bill",
            "bill_return_line_internet",
            "bill_return_line_tv",
        ]:
            with self.subTest(tool_name=tool_name):
                result = call_tool(tool_name, memory)
                self.assertTrue(result["success"])
                self.assertEqual(result["data"]["raw"]["request"]["custNo"], "1082281")
                self.assertEqual(result["data"]["raw"]["request"]["custCName"], "王大明")
                self.assertEqual(result["data"]["raw"]["request"]["custTel"], "0988555666")

    def test_guest_customer_number_alone_cannot_replace_identity_pair(self):
        result = call_tool(
            "search_bill",
            {
                "known_info": {
                    "custnum": "1082281",
                    "custnum_source": "user_provided",
                },
            },
        )

        self.assertFalse(result["success"])
        self.assertEqual(result["data"]["missing"], ["identity_pair"])
        self.assertIn("客戶編號、戶名、登記電話任兩項", result["message"])

    def test_search_bill_schema_requires_any_two_identity_fields_for_guest(self):
        schemas = {
            item["name"]: item
            for item in get_available_functions({"known_info": {}})
        }

        schema = schemas["search_bill"]["parameters"]

        self.assertNotIn("required", schema)
        self.assertEqual(len(schema["anyOf"]), 3)
        self.assertNotIn("service_address", schema["properties"])

    def test_call_tool_identity_apis_use_custnum_from_memory(self):
        send_result = call_tool(
            "send_message",
            {
                "is_logged_in": True,
                "known_info": {
                    "custnum": "1082281",
                    "custnum_source": "web_authenticated",
                    "is_logged_in": True,
                    "phone": "0988555666",
                },
            },
        )
        self.assertTrue(send_result["success"])
        self.assertEqual(send_result["data"]["raw"]["request"]["custNo"], "1082281")
        self.assertEqual(send_result["data"]["raw"]["request"]["custTel"], "0988555666")

        for tool_name in ["bill_return_line_internet", "bill_return_line_tv"]:
            result = call_tool(tool_name, {
                "is_logged_in": True,
                "known_info": {
                    "custnum": "1082281",
                    "custnum_source": "web_authenticated",
                    "is_logged_in": True,
                },
            })

            self.assertTrue(result["success"], tool_name)
            self.assertEqual(result["data"]["raw"]["request"]["custNo"], "1082281")

    def test_call_tool_requires_a_second_guest_identity_field_with_customer_number(self):
        memory = {
            "known_info": {
                "custnum": "1082281",
                "custnum_source": "user_provided",
            },
        }

        for tool_name in [
            "search_bill",
            "bill_return_line_internet",
            "bill_return_line_tv",
        ]:
            with self.subTest(tool_name=tool_name):
                result = call_tool(tool_name, memory)
                self.assertFalse(result["success"])
                self.assertEqual(result["data"]["missing"], ["identity_pair"])
                self.assertIn("客戶編號、戶名、登記電話任兩項", result["message"])

    def test_call_tool_accepts_customer_number_with_name_or_phone_for_guest(self):
        identity_pairs = [
            ({"name": "王大明"}, "王大明", ""),
            ({"phone": "0988555666"}, "", "0988555666"),
        ]

        for extra_fields, expected_name, expected_phone in identity_pairs:
            memory = {
                "known_info": {
                    "custnum": "1082281",
                    "custnum_source": "user_provided",
                    **extra_fields,
                },
            }
            for tool_name in [
                "search_bill",
                "bill_return_line_internet",
                "bill_return_line_tv",
            ]:
                with self.subTest(tool_name=tool_name, extra_fields=extra_fields):
                    result = call_tool(tool_name, memory)
                    self.assertTrue(result["success"])
                    self.assertEqual(result["data"]["raw"]["request"]["custNo"], "1082281")
                    self.assertEqual(result["data"]["raw"]["request"]["custCName"], expected_name)
                    self.assertEqual(result["data"]["raw"]["request"]["custTel"], expected_phone)

    def test_contract_lookup_requires_authenticated_web_customer_number(self):
        for memory in [
            {"known_info": {}},
            {"known_info": {"name": "王大明", "phone": "0988555666"}},
            {
                "known_info": {
                    "custnum": "1082281",
                    "custnum_source": "user_provided",
                    "name": "王大明",
                    "phone": "0988555666",
                },
            },
        ]:
            with self.subTest(memory=memory):
                result = call_tool("search_contract_info", memory)
                self.assertFalse(result["success"])
                self.assertEqual(result["data"]["missing"], [])
                self.assertTrue(result["data"]["access_denied"])
                self.assertEqual(
                    result["message"],
                    "為保障您的個人資料安全，個人帳務及方案等資訊需登入會員後才能查詢，"
                    "您可以至官網或行動客服 APP 登入後查看相關資料。",
                )

    def test_call_tool_send_message_requires_name_and_phone_with_unverified_custnum_from_memory(self):
        result = call_tool("send_message", {"known_info": {"custnum": "1082281"}})

        self.assertFalse(result["success"])
        self.assertEqual(result["data"]["missing"], ["name", "phone"])

    def test_mock_identity_apis_reject_wrong_phone(self):
        result = exec_send_message(name="王大明", phone="0988666555")

        self.assertFalse(result["success"])
        self.assertEqual(result["data"]["missing"], ["name", "phone"])

    def test_payment_bill_batch_rejects_barcodes_without_image_evidence(self):
        result = exec_payment_bill_batch(
            first_barcode="1234567890",
            second_barcode="ABC1234567",
            third_barcode="9999999999",
        )

        self.assertFalse(result["success"])
        self.assertIn("重新上傳", result["message"])
        self.assertEqual(result["data"]["missing"], ["receipt_image_evidence"])

    def test_payment_bill_batch_mock_confirms_numeric_barcodes(self):
        result = exec_payment_bill_batch(
            receipt_image_evidence=verified_receipt_evidence([{
                "first_barcode": "1234567890",
                "second_barcode": "0058072222",
                "third_barcode": "9999999999",
            }]),
        )

        self.assertTrue(result["success"])
        self.assertTrue(result["message"].startswith("這筆帳單："))
        self.assertIn("模擬超商收據條碼 API", result["message"])
        self.assertEqual(result["data"]["raw"]["request"]["barCode1"], "1234567890")
        self.assertEqual(result["data"]["bill_count"], 1)

    def test_payment_bill_batch_accepts_short_company_payment_item_prefixes(self):
        result = exec_payment_bill_batch(
            receipt_image_evidence=verified_receipt_evidence([
                {
                    "first_num": "1234567890",
                    "second_num": "3564123456",
                    "third_num": "9999999999",
                },
                {
                    "first_num": "150519TGE",
                    "second_num": "810961234567",
                    "third_num": "150395000001795",
                },
            ]),
        )

        self.assertTrue(result["success"])
        self.assertIn("第1筆帳單：", result["message"])
        self.assertIn("第2筆帳單：", result["message"])
        self.assertIn("模擬超商收據條碼 API", result["message"])
        self.assertEqual(result["data"]["bill_count"], 2)
        self.assertEqual(result["data"]["raw"]["results"][0]["request"]["barCode2"], "3564123456")
        self.assertEqual(result["data"]["raw"]["results"][1]["request"]["barCode2"], "810961234567")

    def test_payment_bill_batch_accepts_beigang_payment_item_prefix(self):
        result = exec_payment_bill_batch(
            receipt_image_evidence=verified_receipt_evidence([{
                "first_barcode": "1234567890",
                "second_barcode": "0058362222",
                "third_barcode": "9999999999",
            }]),
        )

        self.assertTrue(result["success"])
        self.assertIn("模擬超商收據條碼 API", result["message"])

    def test_payment_bill_batch_rejects_non_company_numeric_payment_item(self):
        result = exec_payment_bill_batch(
            receipt_image_evidence=verified_receipt_evidence([{
                "first_barcode": "1234567890",
                "second_barcode": "2222222222",
                "third_barcode": "9999999999",
            }]),
        )

        self.assertTrue(result["success"])
        self.assertIn("目前無法確認您所反映之繳費項目為本公司收取", result["message"])
        self.assertIn("建議您可依繳費明細確認收款單位", result["message"])
        self.assertNotIn("222222", result["message"])
        self.assertNotIn("代收項目前碼", result["message"])
        self.assertEqual(result["data"]["raw"]["response"]["status"], "non_company_payment_item")

    def test_payment_bill_batch_accepts_multiple_bills(self):
        result = exec_payment_bill_batch(
            receipt_image_evidence=verified_receipt_evidence([
                {
                    "first_num": "1234567890",
                    "second_num": "0058082222",
                    "third_num": "9999999999",
                },
                {
                    "first_num": "150519TGE",
                    "second_num": "0058092603754828",
                    "third_num": "150395000001795",
                },
            ]),
        )

        self.assertTrue(result["success"])
        self.assertIn("第1筆帳單：", result["message"])
        self.assertIn("第2筆帳單：", result["message"])
        self.assertEqual(result["data"]["bill_count"], 2)
        self.assertEqual(result["data"]["raw"]["results"][0]["request"]["barCode1"], "1234567890")
        self.assertEqual(result["data"]["raw"]["results"][1]["request"]["barCode3"], "150395000001795")

    def test_real_payment_bill_batch_sends_token_and_three_barcodes(self):
        with patch("app.services.tool_manager.CUST_API_USE_MOCK", False), patch(
            "app.services.tool_manager.get_token",
            return_value="token-value",
        ), patch(
            "app.services.tool_manager.call_payment_barcode_endpoint",
            return_value={"success": True, "tool_name": "payment_bill_batch", "message": "ok", "data": {}},
        ) as barcode_api:
            result = exec_payment_bill_batch(
                receipt_image_evidence=verified_receipt_evidence([{
                    "first_barcode": "1234567890",
                    "second_barcode": "0058072222",
                    "third_barcode": "9999999999",
                }]),
            )

        self.assertTrue(result["success"])
        barcode_api.assert_called_once_with({
            "token": "token-value",
            "barCode1": "1234567890",
            "barCode2": "0058072222",
            "barCode3": "9999999999",
        })

    def test_real_payment_bill_batch_rejects_non_company_numeric_item_without_api_call(self):
        with patch("app.services.tool_manager.CUST_API_USE_MOCK", False), patch(
            "app.services.tool_manager.get_token",
            return_value="token-value",
        ) as get_token, patch(
            "app.services.tool_manager.call_payment_barcode_endpoint",
        ) as barcode_api:
            result = exec_payment_bill_batch(
                receipt_image_evidence=verified_receipt_evidence([{
                    "first_barcode": "1234567890",
                    "second_barcode": "2222222222",
                    "third_barcode": "9999999999",
                }]),
            )

        self.assertTrue(result["success"])
        self.assertIn("目前無法確認您所反映之繳費項目為本公司收取", result["message"])
        get_token.assert_not_called()
        barcode_api.assert_not_called()

    def test_real_payment_bill_batch_sends_each_numeric_bill(self):
        with patch("app.services.tool_manager.CUST_API_USE_MOCK", False), patch(
            "app.services.tool_manager.get_token",
            return_value="token-value",
        ), patch(
            "app.services.tool_manager.call_payment_barcode_endpoint",
            side_effect=[
                {"success": True, "tool_name": "payment_bill_batch", "message": "ok1", "data": {"raw": {"msg": "ok1"}}},
                {"success": True, "tool_name": "payment_bill_batch", "message": "ok2", "data": {"raw": {"msg": "ok2"}}},
            ],
        ) as barcode_api:
            result = exec_payment_bill_batch(
                receipt_image_evidence=verified_receipt_evidence([
                    {
                        "first_num": "1111111111",
                        "second_num": "0058072222",
                        "third_num": "3333333333",
                    },
                    {
                        "first_num": "4444444444",
                        "second_num": "0058105555",
                        "third_num": "6666666666",
                    },
                ]),
            )

        self.assertTrue(result["success"])
        self.assertIn("第1筆帳單：ok1", result["message"])
        self.assertIn("第2筆帳單：ok2", result["message"])
        self.assertEqual(barcode_api.call_count, 2)
        barcode_api.assert_any_call({
            "token": "token-value",
            "barCode1": "1111111111",
            "barCode2": "0058072222",
            "barCode3": "3333333333",
        })
        barcode_api.assert_any_call({
            "token": "token-value",
            "barCode1": "4444444444",
            "barCode2": "0058105555",
            "barCode3": "6666666666",
        })

    def test_payment_bill_batch_tool_can_be_called_from_memory(self):
        tool_names = {item["name"] for item in get_available_functions({})}
        self.assertIn("payment_bill_batch", tool_names)

        result = call_tool(
            "payment_bill_batch",
            {
                "known_info": {
                    "active_receipt_image_evidence": verified_receipt_evidence([{
                        "first_barcode": "1234567890",
                        "second_barcode": "0058072222",
                        "third_barcode": "9999999999",
                    }]),
                }
            },
        )

        self.assertTrue(result["success"])
        self.assertIn("復線處理", result["message"])

    def test_removed_promotion_tool_is_not_available(self):
        tool_names = {item["name"] for item in get_available_functions({})}
        self.assertNotIn("search_promotion", tool_names)

        result = call_tool(
            "search_promotion",
            {"known_info": {"service_area": "台中", "desired_plan": "測試寬頻優惠"}},
        )

        self.assertFalse(result["success"])
        self.assertIn("找不到工具", result["message"])

    def test_contract_info_tool_is_available_for_service_content_query(self):
        tool_names = {item["name"] for item in get_available_functions({})}
        self.assertIn("search_contract_info", tool_names)

        result = call_tool(
            "search_contract_info",
            {
                "is_logged_in": True,
                "known_info": {
                    "custnum": "1082281",
                    "custnum_source": "web_authenticated",
                    "is_logged_in": True,
                },
            },
        )

        self.assertTrue(result["success"])
        self.assertIn("FTTH-EPON", result["message"])
        self.assertIn("下載 1 Gbps / 上傳 600 Mbps", result["message"])

    def test_mock_channel_tool_can_be_called_from_memory(self):
        result = call_tool(
            "search_channel_no",
            {"known_info": {"service_area": "大屯", "channel_name": "愛爾達體育"}},
        )

        self.assertTrue(result["success"])
        self.assertIn("168", result["message"])

    def test_mock_channel_tool_returns_hbo_channel_list(self):
        result = call_tool(
            "search_channel_no",
            {"known_info": {"channel_name": "HBO"}},
        )

        self.assertTrue(result["success"])
        self.assertIn("HBO：第 65 台", result["message"])
        self.assertIn("HBO HD：第 220 台", result["message"])
        self.assertIn("HBO Signature：第 221 台", result["message"])
        self.assertIn("HBO Family：第 222 台", result["message"])
        self.assertIn("HBO Hits：第 223 台", result["message"])
        self.assertIn("mock-api.local", result["message"])

    def test_mock_channel_tool_returns_eastern_movie_channel(self):
        result = call_tool(
            "search_channel_no",
            {"known_info": {"channel_name": "東森電影台"}},
        )

        self.assertTrue(result["success"])
        self.assertIn("頻道名稱：東森電影台", result["message"])
        self.assertIn("頻道號：62", result["message"])
        self.assertNotIn("服務地區", result["message"])
        self.assertNotIn("地區：", result["message"])

    def test_mock_channel_tool_returns_pili_channel_alias(self):
        result = call_tool(
            "search_channel_no",
            {"known_info": {"channel_name": "霹靂台灣台"}},
        )

        self.assertTrue(result["success"])
        self.assertIn("頻道號：99", result["message"])

    def test_real_channel_api_formats_multiple_channel_results(self):
        with patch(
            "app.services.tool_manager.call_customer_endpoint",
            return_value=(
                True,
                {
                    "data": [
                        {"channelName": "HBO", "channelId": "65"},
                        {"channelName": "HBO HD", "channelId": "220"},
                        {"channelName": "HBO Signature", "channelId": "221"},
                    ],
                    "code": "0000",
                    "msg": "成功",
                },
            ),
        ) as endpoint:
            result = call_channel_no(
                {"token": "tertwsop[eirtapkrf==", "channelName": "HBO"},
                "HBO",
            )

        endpoint.assert_called_once()
        self.assertTrue(result["success"])
        self.assertIn("HBO：第 65 台", result["message"])
        self.assertIn("HBO HD：第 220 台", result["message"])
        self.assertEqual(result["data"]["raw"]["code"], "0000")

    def test_real_channel_api_handles_success_without_data_as_not_found(self):
        with patch(
            "app.services.tool_manager.call_customer_endpoint",
            return_value=(True, {"code": "0000", "msg": "成功"}),
        ):
            result = call_channel_no(
                {"token": "tertwsop[eirtapkrf==", "channelName": "NotFound"},
                "NotFound",
            )

        self.assertTrue(result["success"])
        self.assertIn("查不到", result["message"])

    def test_real_channel_tool_sends_token_and_channel_name(self):
        with patch("app.services.tool_manager.CUST_API_USE_MOCK", False), patch(
            "app.services.tool_manager.get_token",
            return_value="tertwsop[eirtapkrf==",
        ), patch(
            "app.services.tool_manager.call_channel_no",
            return_value={"success": True, "tool_name": "search_channel_no", "message": "ok", "data": {}},
        ) as channel_api:
            result = call_tool(
                "search_channel_no",
                {"known_info": {"channel_name": "HBO"}},
            )

        self.assertTrue(result["success"])
        channel_api.assert_called_once_with(
            {"token": "tertwsop[eirtapkrf==", "channelName": "HBO"},
            "HBO",
        )

    def test_disabled_service_availability_tool_returns_disabled_response(self):
        tool_names = {item["name"] for item in get_available_functions({})}
        self.assertNotIn("search_service_availability", tool_names)

        result = call_tool(
            "search_service_availability",
            {"known_info": {"service_address": "彰化縣和美鎮", "install_service": "寬頻上網"}},
        )

        self.assertFalse(result["success"])
        self.assertTrue(result["data"]["disabled"])
        self.assertIn("線上服務暫停", result["message"])

    def test_disabled_install_and_addon_tools_return_disabled_response(self):
        tool_names = {item["name"] for item in get_available_functions({})}
        self.assertNotIn("apply_new_install", tool_names)
        self.assertNotIn("search_addon_plans", tool_names)

        install_result = call_tool(
            "apply_new_install",
            {
                "known_info": {
                    "contact_name": "王大明",
                    "contact_phone": "0912345678",
                    "service_address": "台中市測試路1號",
                    "install_service": "寬頻上網",
                }
            },
        )
        addon_result = call_tool(
            "search_addon_plans",
            {"known_info": {"service_area": "台中", "addon_name": "LINE TV"}},
        )

        self.assertFalse(install_result["success"])
        self.assertTrue(install_result["data"]["disabled"])
        self.assertFalse(addon_result["success"])
        self.assertTrue(addon_result["data"]["disabled"])

    def test_mock_cancel_repair_requires_ticket_id_and_phone(self):
        missing = call_tool(
            "cancel_repair_ticket",
            {"known_info": {"repair_ticket_id": "NT20260513-ABC123"}},
        )
        self.assertFalse(missing["success"])
        self.assertEqual(missing["data"]["missing"], ["contact_phone"])

        result = call_tool(
            "cancel_repair_ticket",
            {
                "known_info": {
                    "repair_ticket_id": "NT20260513-ABC123",
                    "contact_phone": "0988555666",
                }
            },
        )

        self.assertTrue(result["success"])
        self.assertIn("模擬取消請求", result["message"])


if __name__ == "__main__":
    unittest.main()
