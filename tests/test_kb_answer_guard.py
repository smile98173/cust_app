import unittest

from app.services.kb_answer_guard import (
    extract_definition_subject,
    filter_answerable_docs,
    is_basic_tv_two_year_fee_query,
    is_network_plan_fee_query,
    is_definition_query,
    is_promotion_query,
    is_specific_fee_query,
)


class KBAnswerGuardTest(unittest.TestCase):
    def test_two_year_cable_tv_query_accepts_annual_rate_card(self):
        docs = [{
            "id": "tv-rate-card",
            "question": "大屯_有線電視_基本收費標準",
            "answer": (
                "收視費採年繳者，裝機費優惠為 600 元。\n"
                "年繳 $6,550、半年繳 $3,280、月繳 $550。"
            ),
        }]

        query = "第四台 有線電視 兩年繳 收視費 裝機費"

        self.assertTrue(is_basic_tv_two_year_fee_query(query))
        self.assertEqual(filter_answerable_docs(query, docs), docs)

    def test_definition_query_detected(self):
        self.assertTrue(is_definition_query("我想知道雙模機是什麼?"))
        self.assertEqual(extract_definition_subject("我想知道雙模機是什麼?"), "雙模機")

    def test_definition_query_rejects_related_but_wrong_question(self):
        docs = [
            {
                "id": "network_support_0042",
                "question": "雙模機網路分享",
                "answer": "雙模機本身並無網路分享功能。",
            }
        ]

        self.assertEqual(filter_answerable_docs("雙模機是什麼", docs), [])

    def test_definition_query_rejects_operation_question(self):
        docs = [
            {
                "id": "set_top_box_0026",
                "question": "雙模機設定選項",
                "answer": "要進入雙模機的設定選項，請進入設定。",
            }
        ]

        self.assertEqual(filter_answerable_docs("雙模機是什麼", docs), [])

    def test_definition_query_accepts_definition_question(self):
        docs = [
            {
                "id": "set_top_box_9999",
                "question": "雙模機是什麼",
                "answer": "雙模機是具備聯網功能的機上盒。",
            }
        ]

        self.assertEqual(filter_answerable_docs("雙模機是什麼", docs), docs)

    def test_definition_query_accepts_same_subject_explanation_question(self):
        docs = [
            {
                "id": "value_added_service_points",
                "question": "台數科紅利點數哈Point說明",
                "answer": "台數科透過哈Point點數回饋顧客，可用於兌換商品或折抵服務費用。",
            }
        ]

        self.assertEqual(filter_answerable_docs("紅利點數是什麼？", docs), docs)
        self.assertEqual(filter_answerable_docs("哈Point是什麼？", docs), docs)

    def test_definition_query_still_rejects_unrelated_explanation_question(self):
        docs = [
            {
                "id": "network_fixed_ip",
                "question": "固定IP服務說明",
                "answer": "固定IP依網路方案提供。",
            }
        ]

        self.assertEqual(filter_answerable_docs("紅利點數是什麼？", docs), [])

    def test_mabow_phone_alias_accepts_tv_phone_definition(self):
        docs = [
            {
                "id": "value_added_service_0083",
                "question": "什麼是瑪帛電視電話",
                "answer": "瑪帛電視電話是一款銀髮軟體服務。",
            }
        ]

        self.assertEqual(filter_answerable_docs("什麼是瑪柏電話", docs), docs)

    def test_canonical_product_name_accepts_typo_definition_with_expanded_query(self):
        docs = [
            {
                "id": "bear-care",
                "question": "熊搭心 熊搭心服務 電視電話 家庭相簿 生活提醒 是什麼 服務內容",
                "answer": "熊搭心含電視電話、家庭相簿、生活提醒三項服務。",
                "record_type": "product_service",
                "document_type": "product_service_catalog",
                "product_name": "熊搭心",
            },
            {
                "id": "marpa-friend",
                "question": "瑪帛好友 熊搭心 瑪帛 是什麼 服務內容",
                "answer": "瑪帛好友提供電視電話通話服務。",
                "record_type": "product_service",
                "document_type": "product_service_catalog",
                "product_name": "瑪帛好友",
            },
        ]
        expanded_query = "熊大心是什麼？ 熊搭心 電視電話 家庭相簿 生活提醒 加值服務"

        self.assertEqual(filter_answerable_docs(expanded_query, docs), [docs[0]])

    def test_legacy_product_section_accepts_typo_without_product_metadata(self):
        docs = [
            {
                "id": "bear-care",
                "question": "熊搭心 熊搭心服務 電視電話 家庭相簿 生活提醒 是什麼 服務內容",
                "answer": "熊搭心含電視電話、家庭相簿、生活提醒三項服務。",
                "record_type": "product_service",
                "source": {"section": "product 6 熊搭心"},
            },
            {
                "id": "marpa-friend",
                "question": "瑪帛好友 熊搭心 瑪帛 是什麼 服務內容",
                "answer": "瑪帛好友提供電視電話通話服務。",
                "record_type": "product_service",
                "source": {"section": "product 8 瑪帛好友"},
            },
        ]
        expanded_query = "熊大心是什麼？ 熊搭心 電視電話 家庭相簿 生活提醒 加值服務"

        self.assertEqual(filter_answerable_docs(expanded_query, docs), [docs[0]])

    def test_named_product_annual_fee_keeps_only_matching_product(self):
        docs = [
            {
                "id": "bear-care",
                "question": "熊搭心服務內容與費用",
                "answer": "熊搭心包含瑪帛好友年繳 828 元、瑪帛夥伴年繳 1,188 元。",
                "record_type": "product_service",
                "product_name": "熊搭心",
            },
            {
                "id": "marpa-friend",
                "question": "瑪帛好友費用",
                "answer": "瑪帛好友月費 69 元、年繳 828 元，屬於熊搭心服務。",
                "record_type": "product_service",
                "product_name": "瑪帛好友",
            },
            {
                "id": "line-tv",
                "question": "LINE TV 費用",
                "answer": "LINE TV 年繳 1,200 元。",
                "record_type": "product_service",
                "product_name": "LINE TV",
            },
        ]
        expanded_query = "熊搭心 年繳 一年 年費 費用 價格"

        self.assertTrue(is_specific_fee_query(expanded_query))
        self.assertEqual(filter_answerable_docs(expanded_query, docs), [docs[0]])

    def test_non_definition_query_keeps_rag_results(self):
        docs = [
            {
                "id": "network_support_0042",
                "question": "雙模機網路分享",
                "answer": "雙模機本身並無網路分享功能。",
            }
        ]

        self.assertEqual(filter_answerable_docs("雙模機可以網路分享嗎", docs), docs)

    def test_network_termination_rejects_tv_only_equipment_document(self):
        docs = [
            {
                "id": "tv-termination",
                "question": "有線電視退租應備文件",
                "answer": "請攜帶機上盒、遙控器、HDMI 線與 AV 傳輸線。",
            }
        ]

        self.assertEqual(filter_answerable_docs("我要退網路", docs), [])

    def test_network_termination_keeps_network_evidence_document(self):
        docs = [
            {
                "id": "network-termination",
                "question": "寬頻網路退租注意事項",
                "answer": "請由客服確認數據機歸還、合約與可能費用。",
            }
        ]

        self.assertEqual(filter_answerable_docs("我要退網路", docs), docs)

    def test_network_termination_rejects_mislabelled_tv_equipment_answer(self):
        docs = [
            {
                "id": "mislabelled-network-termination",
                "question": "網路如何辦理退租",
                "answer": "請攜帶機上盒、遙控器、HDMI 線與 AV 傳輸線。",
            }
        ]

        self.assertEqual(filter_answerable_docs("網路退租要帶哪些文件", docs), [])

    def test_network_plan_fee_query_rejects_addon_fee_docs(self):
        docs = [
            {
                "id": "network_support_0039",
                "question": "我需要設定IP",
                "answer": "針對網路用戶我們有免費提供一組固定IP，第二組以上加收200元/月。",
            },
            {
                "id": "network_support_0022",
                "question": "Mesh WIFI怎麼收費?",
                "answer": "申裝網路可綁約租借Mesh WIFI。",
            },
        ]

        self.assertTrue(is_network_plan_fee_query("網路方案 費用 月租"))
        self.assertEqual(filter_answerable_docs("網路方案 費用 月租", docs), [])

    def test_network_plan_fee_query_accepts_plan_fee_doc(self):
        docs = [
            {
                "id": "network_support_9999",
                "question": "網路方案月租費用",
                "answer": "網路方案月租依速率不同而有不同費用。",
            },
        ]

        self.assertEqual(filter_answerable_docs("網路方案 費用 月租", docs), docs)

    def test_specific_fee_query_prefers_matching_subject_fee_doc(self):
        docs = [
            {
                "id": "promo",
                "question": "加值服務",
                "answer": "裝機費免費，是否適用方案需由客服確認。",
            },
            {
                "id": "move",
                "question": "加值服務",
                "answer": "移機分室內或室外移機，移機需收費室內 500元 室外800元。",
            },
        ]

        self.assertTrue(is_specific_fee_query("移機費用"))
        self.assertEqual(filter_answerable_docs("移機費用", docs), [docs[1]])

    def test_tv_fee_query_accepts_cable_tv_fee_doc(self):
        docs = [
            {
                "id": "tv-fee",
                "question": "有線電視費用",
                "answer": "有線電視基本頻道月租費用依各區方案公告為準。",
            }
        ]

        self.assertTrue(is_specific_fee_query("第四台費用怎麼收?"))
        self.assertEqual(filter_answerable_docs("第四台費用怎麼收?", docs), docs)

    def test_cable_tv_fee_intro_query_ignores_intro_words(self):
        docs = [
            {
                "id": "tv-fee",
                "question": "第四台收費方式",
                "answer": "第四台月租依收視方案與地區公告為準。",
            }
        ]

        self.assertTrue(is_specific_fee_query("請介紹有線電視費用"))
        self.assertEqual(filter_answerable_docs("請介紹有線電視費用", docs), docs)

    def test_cable_tv_plan_price_query_does_not_require_plan_word_in_doc(self):
        docs = [
            {
                "id": "tv-fee",
                "question": "大屯 TV 基本收費標準",
                "answer": "有線電視基本頻道收視費每月依公告收取。",
            }
        ]

        self.assertTrue(is_specific_fee_query("有線電視方案價格"))
        self.assertEqual(filter_answerable_docs("有線電視方案價格", docs), docs)

    def test_set_top_box_deposit_query_accepts_deposit_doc(self):
        docs = [
            {
                "id": "stb-deposit",
                "question": "機上盒押金",
                "answer": "機上盒押金依設備與方案由客服確認。",
            }
        ]

        self.assertTrue(is_specific_fee_query("第四台 機上盒 要押金嗎"))
        self.assertEqual(filter_answerable_docs("第四台 機上盒 要押金嗎", docs), docs)

    def test_third_set_top_box_fee_accepts_exact_fact_from_source_content(self):
        docs = [
            {
                "id": "third-box-fee",
                "question": "大屯有線電視基本收費標準",
                "answer": "多台機上盒依基本收費標準辦理。",
                "source": {
                    "content": "第3、4、5台一律收押金$1,200元/台、收分機費$800元/台。"
                },
            }
        ]

        self.assertEqual(
            filter_answerable_docs("第三台機上盒要收哪些費用？", docs),
            docs,
        )

    def test_generic_fee_query_keeps_results_when_subject_is_unknown(self):
        docs = [
            {
                "id": "fee",
                "question": "費用說明",
                "answer": "各項費用需依服務項目確認。",
            },
        ]

        self.assertFalse(is_specific_fee_query("費用"))
        self.assertEqual(filter_answerable_docs("費用", docs), docs)

    def test_promotion_price_query_does_not_filter_promotion_docs(self):
        docs = [
            {
                "id": "promo",
                "question": "最新優惠",
                "answer": "飆網守護家 B2606 主推 100M、300M、500M，免裝機費。",
            }
        ]

        query = "優惠方案 飆網守護家 和好視成雙 300M多少錢?"
        self.assertTrue(is_promotion_query(query))
        self.assertEqual(filter_answerable_docs(query, docs), docs)

    def test_generic_promotion_query_keeps_campaign_doc_from_evidence(self):
        docs = [
            {
                "id": "promo",
                "question": "最新優惠",
                "answer": "飆網守護家 B2606 可申辦 300M。",
            }
        ]

        query = "優惠方案 300M多少錢?"
        self.assertTrue(is_promotion_query(query))
        self.assertEqual(filter_answerable_docs(query, docs), docs)

    def test_network_plan_fee_query_keeps_named_promotion_price_doc(self):
        docs = [
            {
                "id": "promo",
                "question": "好視成雙NO8-1150610-1150831",
                "answer": "方案名稱：好視成雙 NO8。300M/300M 月繳 $899，500M/500M 月繳 $999。",
            }
        ]

        query = "網路方案多少錢?"
        self.assertTrue(is_network_plan_fee_query(query))
        self.assertEqual(filter_answerable_docs(query, docs), docs)

    def test_named_campaign_download_speed_fee_matches_full_rate(self):
        docs = [
            {
                "id": "promo-summer-fiber",
                "question": "夏日光纖禮遇月租速率",
                "answer": "方案名稱：夏日光纖禮遇。777M/77M 月租 777 元。",
            }
        ]

        query = "夏日光纖禮遇的 777M 月租多少？"
        self.assertTrue(is_specific_fee_query(query))
        self.assertEqual(filter_answerable_docs(query, docs), docs)

    def test_named_campaign_download_speed_fee_rejects_wrong_rate(self):
        docs = [
            {
                "id": "promo-summer-fiber",
                "question": "夏日光纖禮遇月租速率",
                "answer": "方案名稱：夏日光纖禮遇。777M/77M 月租 777 元。",
            }
        ]

        query = "夏日光纖禮遇的 500M 月租多少？"
        self.assertTrue(is_specific_fee_query(query))
        self.assertEqual(filter_answerable_docs(query, docs), [])


if __name__ == "__main__":
    unittest.main()
