import json
import tempfile
import unittest
from contextlib import nullcontext
from pathlib import Path
from unittest.mock import Mock, patch

import requests
from langchain_core.messages import AIMessage
from langchain_core.runnables import RunnableLambda

from app.handlers.chat_handler import (
    build_campaign_contract_followup_reply,
    build_campaign_detail_context_query,
    build_contextual_knowledge_query,
    build_named_campaign_overview_reply,
    build_promotion_catalog_reply,
    compose_knowledge_reply,
    filter_docs_with_llm_evidence,
    format_customer_reply_text,
    remember_campaign_topic,
)
from app.services import kb_service


class KBServiceTest(unittest.TestCase):
    def setUp(self):
        self.common_scope_patch = patch.object(
            kb_service.COMMON_SCOPE_SERVICE,
            "get_common_knowledge_base_scopes",
            return_value={
                "通用-中區": ["大屯", "西海岸", "佳光市區", "中投", "佳聯", "北港"],
                "通用-嘉南區": ["大揚", "新永安"],
            },
        )
        self.common_scope_patch.start()

    def tearDown(self):
        kb_service.reset_local_searcher_cache()
        self.common_scope_patch.stop()

    def test_named_campaign_overview_formats_install_and_penalty_fields_once(self):
        docs = [{
            "campaign_name": "哈 NET1",
            "campaign_aliases": "哈 NET1",
            "answer": (
                "方案名稱：哈 NET1\n"
                "1、寬頻費用：60M/6M：月繳 500 元、半年繳 3,000 元、年繳 6,000 元。\n"
                "2、裝機費：500 元。\n"
                "3、綁約條件：月繳、年繳用戶綁約一年，半年繳用戶綁約半年。\n"
                "4、違約：提前解約需支付違約金 1,500 元，可逐月遞減。"
            ),
        }]

        reply = build_named_campaign_overview_reply("哈 NET1", docs)

        self.assertIn("裝機費：500 元。", reply)
        self.assertIn("違約金：提前解約需支付違約金 1,500 元，可逐月遞減。", reply)
        self.assertNotIn("違約金：綁約條件", reply)
        self.assertNotIn("\n-\n", format_customer_reply_text(reply))

    def test_campaign_penalty_followup_uses_remembered_campaign_only(self):
        selected = {
            "campaign_name": "哈 NET1",
            "answer": (
                "綁約條件：月繳、年繳用戶綁約一年，半年繳用戶綁約半年。\n"
                "違約：提前解約需支付違約金 1,500 元，可逐月遞減。"
            ),
        }
        unrelated = {
            "campaign_name": "其他方案",
            "answer": "違約：提前解約需支付違約金 9,999 元。",
        }
        memory = {
            "last_campaign_topic": "哈 NET1",
            "last_knowledge_results": [selected],
        }

        reply = build_campaign_contract_followup_reply(
            "違約金多少？",
            [unrelated, selected],
            memory=memory,
        )

        self.assertEqual(reply, "哈 NET1：提前解約需支付違約金 1,500 元，可逐月遞減。")
        self.assertNotIn("9,999", reply)

    def test_campaign_penalty_followup_calculates_from_dates_and_dynamic_campaign(self):
        selected = {
            "campaign_name": "動態方案 X9",
            "answer": "綁約期間：24 個月，提前解約需收違約金 $2,400 元，可逐月遞減。",
        }
        memory = {
            "last_campaign_topic": "動態方案 X9",
            "last_knowledge_results": [selected],
        }

        reply = build_campaign_contract_followup_reply(
            "2026/08/01 裝機，2026/12/31 退租，要繳多少違約金？",
            [selected],
            memory=memory,
        )

        self.assertIn("動態方案 X9", reply)
        self.assertIn("裝機日：2026/08/01", reply)
        self.assertIn("退租日：2026/12/31", reply)
        self.assertIn("已履約天數：153 天", reply)
        self.assertIn("未履約天數：730 - 153 = 577 天", reply)
        self.assertIn("最終應繳違約金：1,897 元", reply)
        self.assertIn("設備回收狀態", reply)

    def test_campaign_detail_query_keeps_dynamic_selected_campaign(self):
        query = build_campaign_detail_context_query(
            "優惠方案 詳細介紹",
            {"last_campaign_topic": "動態方案 X9"},
            "campaign_detail",
        )

        self.assertEqual(query, "動態方案 X9 優惠方案 詳細介紹")
        self.assertEqual(
            build_campaign_detail_context_query(
                "新方案 Y8 詳細介紹",
                {"last_campaign_topic": "動態方案 X9"},
                "campaign_detail",
                allow_context=False,
            ),
            "新方案 Y8 詳細介紹",
        )

    def test_campaign_detail_mode_does_not_render_a_catalog(self):
        reply = build_promotion_catalog_reply(
            "有詳細介紹？",
            [{
                "campaign_name": "動態方案 X9",
                "document_type": "promotion_campaign",
                "record_type": "campaign_summary",
                "service_types": "純網寬頻",
                "speeds": "300M/300M",
            }],
            intent="promotion_campaign_detail_query",
            promotion_scope="pure_network",
            promotion_query_kind="campaign_detail",
        )

        self.assertEqual(reply, "")

    def test_validated_document_target_excludes_other_retrieval_hits(self):
        docs = [
            {
                "document_id": "dynamic-plan-a",
                "knowledge_base": "大屯",
                "question": "動態方案 A",
                "answer": "方案 A 內容",
            },
            {
                "document_id": "dynamic-plan-b",
                "knowledge_base": "大屯",
                "question": "動態方案 B",
                "answer": "方案 B 內容",
            },
        ]

        with (
            patch.object(kb_service, "RAG_BACKEND", "local"),
            patch.object(kb_service, "retrieve_knowledge_from_local_chroma", return_value=docs),
            patch.object(kb_service, "should_merge_keyword_fallback_for_results", return_value=False),
            patch.object(kb_service, "supplement_digital_tv_package_purchase_path_docs", return_value=docs),
            patch.object(kb_service, "filter_docs_for_active_campaign_alias", side_effect=lambda _q, _m, values: values),
        ):
            result = kb_service.retrieve_knowledge(
                "2",
                {"company_code": "tdtv"},
                {
                    "knowledge_query": "動態方案 B 費用",
                    "target_document_id": "dynamic-plan-b",
                    "target_knowledge_base": "大屯",
                },
            )

        self.assertEqual([doc["document_id"] for doc in result], ["dynamic-plan-b"])

    def test_promotion_catalog_scope_survives_legacy_query_rewrites(self):
        captured_queries = []
        docs = [{
            "document_id": "dynamic-pure-network",
            "knowledge_base": "大屯",
            "question": "動態純網方案",
            "answer": "300M/300M 月繳 799 元。",
        }]

        def retrieve_local(query, _memory, top_k=5, max_distance=0.55):
            captured_queries.append(query)
            return docs

        with (
            patch.object(kb_service, "RAG_BACKEND", "local"),
            patch.object(kb_service, "match_active_campaign_alias", return_value=None),
            patch.object(kb_service, "retrieve_knowledge_from_local_chroma", side_effect=retrieve_local),
            patch.object(kb_service, "should_merge_keyword_fallback_for_results", return_value=False),
            patch.object(kb_service, "supplement_digital_tv_package_purchase_path_docs", return_value=docs),
            patch.object(kb_service, "filter_docs_for_active_campaign_alias", side_effect=lambda _q, _m, values: values),
        ):
            result = kb_service.retrieve_knowledge(
                "網路裝機申請",
                {"company_code": "tdtv"},
                {
                    "knowledge_query": "目前有效 純網路 單辦寬頻 優惠方案 網路裝機申請",
                    "promotion_scope": "pure_network",
                    "promotion_query_kind": "catalog",
                    "should_cancel_current_flow": True,
                },
                top_k=12,
            )

        self.assertEqual(result, docs)
        self.assertEqual(len(captured_queries), 1)
        self.assertIn("純網路", captured_queries[0])
        self.assertNotEqual(captured_queries[0], "網路裝機申請")

    def test_llm_evidence_filter_drops_adjacent_service_document(self):
        docs = [
            {"question": "SD22 節能模式", "answer": "可到設定關閉節能模式。"},
            {"question": "線上繳費", "answer": "可使用官網或行動客服 APP。"},
        ]
        llm = RunnableLambda(
            lambda _payload: AIMessage(
                content='{"selected_document_indexes": [2], "has_sufficient_evidence": true}'
            )
        )

        filtered, decided = filter_docs_with_llm_evidence(
            "線上繳費",
            docs,
            {"service_scope": "線上繳費", "requested_information": "繳費流程"},
            llm=llm,
        )

        self.assertTrue(decided)
        self.assertEqual(filtered, [docs[1]])

    def test_llm_evidence_filter_keeps_existing_docs_when_model_output_is_invalid(self):
        docs = [{"question": "線上繳費", "answer": "可使用官網。"}]
        llm = RunnableLambda(lambda _payload: AIMessage(content="不是 JSON"))

        filtered, decided = filter_docs_with_llm_evidence(
            "線上繳費",
            docs,
            {"service_scope": "線上繳費", "requested_information": "繳費流程"},
            llm=llm,
        )

        self.assertFalse(decided)
        self.assertEqual(filtered, docs)

    def test_llm_evidence_filter_keeps_docs_when_model_finds_no_direct_evidence(self):
        docs = [{"question": "SD22 節能模式", "answer": "可到設定關閉節能模式。"}]
        llm = RunnableLambda(
            lambda _payload: AIMessage(
                content='{"selected_document_indexes": [1], "has_sufficient_evidence": false}'
            )
        )

        filtered, decided = filter_docs_with_llm_evidence(
            "線上繳費",
            docs,
            {"service_scope": "線上繳費", "requested_information": "繳費流程"},
            llm=llm,
        )

        self.assertFalse(decided)
        self.assertEqual(filtered, docs)

    def test_explicit_rate_requires_a_matching_retrieval_candidate(self):
        docs = [{
            "question": "有線電視基本收費標準",
            "answer": "月繳 565 元。",
        }]

        self.assertTrue(
            kb_service.should_merge_keyword_fallback_for_results(
                "60M/6M 是否包含電視費用",
                docs,
            )
        )

    def test_hatv_with_broadband_rate_is_not_a_basic_tv_fee_query(self):
        self.assertFalse(
            kb_service.is_basic_tv_fee_query(
                "60M/6M 月繳 790 元，是否包含哈TV費用"
            )
        )
        self.assertTrue(kb_service.is_basic_tv_fee_query("第四台月費多少錢"))

    def test_hatv_and_hatnet_are_a_combined_service_query(self):
        query = "本身有哈TV想申請哈NET有什麼優惠"
        standalone_hatv_doc = {
            "question": "哈TV 加值服務",
            "answer": "可加購哈TV 數位套餐。",
        }
        combo_doc = {
            "question": "電視網路同裝優惠",
            "answer": "好視成雙為電視網路同裝方案。",
        }

        self.assertTrue(kb_service.is_tv_network_combo_query(query))
        self.assertTrue(
            kb_service.should_merge_keyword_fallback_for_results(query, [standalone_hatv_doc])
        )
        self.assertEqual(
            kb_service.filter_docs_for_query_intent(query, [standalone_hatv_doc, combo_doc]),
            [combo_doc],
        )

    def test_excluded_combo_wording_remains_a_pure_network_catalog_query(self):
        query = (
            "目前有效 純網路 單辦寬頻 優惠方案 "
            "排除有線電視加網路方案 排除電視+網路同裝方案"
        )

        self.assertFalse(kb_service.is_tv_network_combo_query(query))
        self.assertTrue(kb_service.is_pure_network_catalog_query(query))

    def test_positive_combo_wording_is_still_a_combo_query(self):
        self.assertTrue(
            kb_service.is_tv_network_combo_query("我要申請有線電視加網路方案")
        )

    def test_broadband_upgrade_keeps_higher_speed_price_evidence(self):
        query = "目前速率 60M/6M 再高一階多少錢 寬頻升級費用"
        docs = [
            {"question": "60M/6M", "answer": "60M/6M 月繳 790 元"},
            {"question": "100M/10M", "answer": "100M/10M 月繳 990 元"},
            {"question": "200M/200M", "answer": "200M/200M 月繳 1190 元"},
        ]

        selected = kb_service.finalize_docs_for_query(query, docs, top_k=5)

        self.assertEqual(
            [item["question"] for item in selected],
            ["100M/10M", "200M/200M"],
        )

    def test_filter_docs_to_active_manifest_sources_rejects_deleted_document_ids(self):
        with tempfile.TemporaryDirectory() as tmp:
            manifest_path = Path(tmp) / "documents.json"
            manifest_path.write_text(json.dumps({
                "documents": [
                    {
                        "id": "active-doc",
                        "status": "active",
                        "processing_status": "indexed",
                        "knowledge_base": "通用",
                    },
                    {
                        "id": "deleted-doc",
                        "status": "deleted",
                        "processing_status": "deleted",
                        "knowledge_base": "通用",
                    },
                ],
            }, ensure_ascii=False), encoding="utf-8")

            docs = [
                {"source": {"document_id": "active-doc"}, "answer": "保留"},
                {"source": {"document_id": "deleted-doc"}, "answer": "刪除"},
                {"source": {"document_id": "missing-doc"}, "answer": "不存在"},
                {"source": {}, "answer": "無來源舊格式"},
            ]

            with patch.object(kb_service, "RAG_LOCAL_MANIFEST_PATH", str(manifest_path)):
                filtered = kb_service.filter_docs_to_active_manifest_sources(docs, ["通用"])

        self.assertEqual(
            [item["answer"] for item in filtered],
            ["保留", "不存在", "無來源舊格式"],
        )

    def test_dynamic_entity_catalog_resolves_one_character_typo_from_manifest(self):
        with tempfile.TemporaryDirectory() as tmp:
            manifest_path = Path(tmp) / "documents.json"
            manifest_path.write_text(json.dumps({
                "documents": [{
                    "id": "dynamic-service",
                    "status": "active",
                    "processing_status": "indexed",
                    "knowledge_base": "通用-中區",
                    "product_service_profile": {
                        "document_type": "product_service_catalog",
                        "products": [{
                            "key": "item_2",
                            "name": "安心雲管家",
                            "aliases": ["安心雲管家"],
                        }],
                    },
                }],
            }, ensure_ascii=False), encoding="utf-8")

            with patch.object(kb_service, "RAG_LOCAL_MANIFEST_PATH", str(manifest_path)):
                kb_service.reset_local_searcher_cache()
                matches = kb_service.resolve_knowledge_entities("安心雲管嘉一年多少錢？")

        self.assertEqual(len(matches), 1)
        self.assertEqual(matches[0]["name"], "安心雲管家")
        self.assertEqual(matches[0]["match_type"], "single_substitution")

    def test_bear_care_typo_expands_to_indexed_canonical_name(self):
        matches = kb_service.resolve_knowledge_entities("熊大心是什麼？")

        self.assertTrue(matches)
        self.assertEqual(matches[0]["key"], "bear_care")
        self.assertIn("熊搭心", kb_service.value_added_query_aliases("熊大心是什麼？"))

    def test_bear_care_query_expands_to_plan_and_call_terms(self):
        aliases = kb_service.value_added_query_aliases("熊搭心一年多少？")

        self.assertIn("瑪帛好友", aliases)
        self.assertIn("瑪帛夥伴", aliases)
        self.assertIn("通話120分鐘", aliases)
        self.assertIn("無限通話", aliases)

    def test_unrelated_text_does_not_force_entity_match(self):
        self.assertEqual(kb_service.resolve_knowledge_entities("今天心情不太好"), [])

    def test_two_character_entity_difference_requires_confirmation(self):
        suggestion = kb_service.suggest_knowledge_entity("熊溫馨")

        self.assertIsNotNone(suggestion)
        self.assertEqual(suggestion["name"], "熊搭心")
        self.assertEqual(suggestion["match_type"], "confirmation_required")
        self.assertEqual(kb_service.resolve_knowledge_entities("熊溫馨"), [])

    def test_unrelated_entity_does_not_create_confirmation_candidate(self):
        self.assertIsNone(kb_service.suggest_knowledge_entity("今天心情不太好"))

    def test_structured_product_profile_adds_line_tv_keyword_candidate(self):
        record = {
            "id": "catalog-1",
            "title": "各項單品銷售",
            "file_name": "catalog.docx",
            "knowledge_base": "通用-中區",
            "product_service_profile": {
                "document_type": "product_service_catalog",
                "catalog_name": "各項單品銷售",
                "products": [{
                    "key": "line_tv",
                    "name": "LINE TV",
                    "aliases": ["LINE TV", "LINE TV 加購"],
                    "content": "LINE TV：原價 210 元/月，特價 600 元/半年、1,200 元/年。",
                }],
            },
        }

        docs = kb_service.build_product_service_profile_candidates("LINE TV 一年多少錢？", record)

        self.assertEqual(len(docs), 1)
        self.assertEqual(docs[0]["record_type"], "product_service")
        self.assertIn("1,200 元/年", docs[0]["answer"])

    def test_structured_product_profile_does_not_add_unrelated_product(self):
        record = {
            "id": "catalog-1",
            "title": "各項單品銷售",
            "file_name": "catalog.docx",
            "knowledge_base": "通用-中區",
            "product_service_profile": {
                "document_type": "product_service_catalog",
                "products": [{
                    "key": "home_camera",
                    "name": "居家智慧攝影機",
                    "aliases": ["攝影機"],
                    "content": "特價 300 元/半年。",
                }],
            },
        }

        docs = kb_service.build_product_service_profile_candidates("LINE TV 一年多少錢？", record)

        self.assertEqual(docs, [])

    def test_reward_points_query_enables_keyword_fallback(self):
        terms = kb_service.build_keyword_terms("紅利點數是什麼？")

        self.assertIn("紅利點數", terms)
        self.assertIn("點數", terms)
        self.assertTrue(kb_service.should_merge_keyword_fallback("紅利點數是什麼？"))

    def test_identifier_query_supplements_only_when_semantic_results_miss_code(self):
        unrelated_docs = [
            {
                "question": "機上盒未授權",
                "answer": "請重新啟動設備。",
                "_keyword_score": 10,
                "_query_relevance_score": 30,
            }
        ]
        matching_docs = [
            {
                "question": "E003 未授權",
                "answer": "請重新啟動設備。",
                "_keyword_score": 10,
                "_query_relevance_score": 30,
            }
        ]

        self.assertTrue(
            kb_service.should_merge_keyword_fallback_for_results(
                "E003 未授權是什麼狀況？", unrelated_docs
            )
        )
        self.assertFalse(
            kb_service.should_merge_keyword_fallback_for_results(
                "E003 未授權是什麼狀況？", matching_docs
            )
        )
        self.assertEqual(
            kb_service.extract_query_strict_identifier_terms("300M 固定 IP"), []
        )

    def test_campaign_metadata_is_remembered_for_followup_questions(self):
        memory = {"last_knowledge_results": []}

        remember_campaign_topic(
            memory,
            docs=[{"campaign_name": "爸氣獻禮", "answer": "LINE TV 贈送 6 個月。"}],
        )

        self.assertEqual(memory["last_campaign_topic"], "爸氣獻禮")

    def test_campaign_cost_followup_keeps_dynamic_campaign_context(self):
        query = build_contextual_knowledge_query(
            "總共費用多少？",
            "總共費用多少？",
            {"last_campaign_topic": "動態方案 X9", "last_knowledge_results": []},
            [],
        )

        self.assertEqual(query, "動態方案 X9 總共費用多少？")
        self.assertNotIn("裝機費", query)
        self.assertNotIn("設備押金", query)

    def test_explicit_relocation_does_not_inherit_remembered_campaign(self):
        query = build_contextual_knowledge_query(
            "移機流程和費用",
            "移機 搬家 換地址 流程 費用 條件",
            {"last_campaign_topic": "動態方案 X9", "last_knowledge_results": []},
            [{"role": "user", "content": "動態方案 X9"}],
        )

        self.assertIn("移機", query)
        self.assertNotIn("動態方案 X9", query)

    def test_wifi_5_price_followup_keeps_exact_product_context(self):
        query = build_contextual_knowledge_query(
            "一年多少錢？",
            "一年多少錢？",
            {},
            [
                {"role": "user", "content": "WiFi 5 加值服務有哪些？"},
                {
                    "role": "assistant",
                    "content": "WiFi 5 系列分享器可選半年繳或年繳。",
                },
            ],
        )

        self.assertIn("WiFi 5 系列分享器", query)
        self.assertNotIn("WiFi 6", query)

    def test_bear_care_price_followup_keeps_product_context(self):
        query = build_contextual_knowledge_query(
            "費用呢？",
            "費用呢？",
            {},
            [
                {"role": "user", "content": "熊搭心是什麼？"},
                {
                    "role": "assistant",
                    "content": "熊搭心包含電視電話、家庭相簿與生活提醒。",
                },
            ],
        )

        self.assertIn("熊搭心", query)

    def test_online_payment_does_not_inherit_previous_set_top_box_topic(self):
        query = build_contextual_knowledge_query(
            "線上繳費",
            "線上繳費",
            {},
            [
                {"role": "user", "content": "SD22可以不要睡眠嗎"},
                {"role": "assistant", "content": "可到設定關閉節能模式。"},
            ],
            allow_context=False,
        )

        self.assertEqual(query, "線上繳費")

    def test_named_campaign_first_reply_uses_compact_source_fields(self):
        captured = []
        llm = RunnableLambda(
            lambda payload: captured.append(payload) or AIMessage(content="不應呼叫摘要模型")
        )

        reply = compose_knowledge_reply(
            "動態方案 X9",
            "",
            [
                {
                    "id": "campaign-1",
                    "campaign_name": "動態方案 X9",
                    "document_type": "promotion_campaign",
                    "answer": (
                        "方案名稱：動態方案 X9\n"
                        "300M/300M：月繳 799 元\n"
                        "LINE TV 贈送 6 個月\n"
                        "裝機費免收\n"
                        "綁約 24 個月"
                    ),
                }
            ],
            llm=llm,
            answer_guard_query="動態方案 X9",
            memory={"company_code": "tdtv"},
            promotion_query_kind="campaign_detail",
        )

        self.assertEqual(captured, [])
        self.assertIn("方案名稱：動態方案 X9", reply)
        self.assertIn("300M/300M：月繳 799 元", reply)
        self.assertIn("LINE TV 贈送 6 個月", reply)
        self.assertIn("裝機費免收", reply)
        self.assertNotIn(";", reply)

    def test_hatpoint_query_enables_keyword_fallback(self):
        terms = kb_service.build_keyword_terms("哈Point要怎麼使用？")

        self.assertIn("哈point", terms)
        self.assertIn("point", terms)
        self.assertTrue(kb_service.should_merge_keyword_fallback("哈Point要怎麼使用？"))

    def test_natural_question_extracts_stable_subject_anchor(self):
        self.assertIn(
            "複製遙控器",
            kb_service.build_keyword_terms("複製遙控器要怎麼設定？"),
        )
        self.assertIn(
            "固定ip",
            kb_service.build_keyword_terms("固定 IP 要怎麼申請？"),
        )
        self.assertIn(
            "台數科紅利點數哈point",
            kb_service.build_keyword_terms("台數科紅利點數哈 Point 是什麼？"),
        )

    def test_product_codes_and_protocol_names_are_independent_fallback_terms(self):
        terms = kb_service.build_keyword_terms("電視顯示 E003，HDMI 要怎麼切換？")

        self.assertIn("e003", terms)
        self.assertIn("hdmi", terms)

    def test_payment_and_world_cup_aliases_enable_fallback(self):
        payment_terms = kb_service.build_keyword_terms("信用卡要怎麼繳？")
        sports_terms = kb_service.build_keyword_terms("世足轉播頻道是幾號？")

        self.assertIn("線上刷卡", payment_terms)
        self.assertIn("世界盃", sports_terms)
        self.assertIn("fifa", sports_terms)
        self.assertTrue(kb_service.should_merge_keyword_fallback("世足轉播頻道是幾號？"))

    def test_lexical_overlap_requires_multiple_shared_chinese_bigrams(self):
        relevant = kb_service.score_query_lexical_overlap(
            "普通的電視遙控器一支多少錢？",
            "請問數位機上盒配件價格？",
            "一般型遙控器每支 300 元。",
        )
        unrelated = kb_service.score_query_lexical_overlap(
            "普通的電視遙控器一支多少錢？",
            "有線電視優惠方案",
            "申辦網路可贈送點數。",
        )

        self.assertGreater(relevant, 0)
        self.assertEqual(unrelated, 0)

    def test_stronger_content_evidence_precedes_local_scope_priority(self):
        docs = [
            {
                "question": "當地優惠活動",
                "answer": "申辦方案可贈哈 POINT 點數。",
                "company": "大屯",
                "_query_relevance_score": 129,
                "_keyword_score": 6,
            },
            {
                "question": "台數科紅利點數哈 Point 說明",
                "answer": "紅利點數可用於兌換商品或折抵服務費用。",
                "company": "通用-中區",
                "_query_relevance_score": 130,
                "_keyword_score": 24,
            },
        ]

        ranked = kb_service.sort_docs_by_company_priority(
            docs,
            {"knowledge_base": "大屯"},
            "台數科紅利點數哈 Point 是什麼？",
        )

        self.assertEqual(ranked[0]["company"], "通用-中區")

    def test_low_evidence_semantic_results_enable_generic_keyword_fallback(self):
        docs = [
            {
                "question": "好視成雙優惠方案",
                "answer": "申辦網路與有線電視可享優惠。",
                "_keyword_score": 0,
                "_query_relevance_score": 0,
            }
        ]

        self.assertTrue(
            kb_service.should_merge_keyword_fallback_for_results(
                "固定 IP 要怎麼申請？",
                docs,
            )
        )

    def test_relevant_semantic_results_do_not_force_generic_keyword_fallback(self):
        docs = [
            {
                "question": "遙控器可以送到府嗎",
                "answer": "遙控器更換或寄送方式請由客服確認。",
                "_keyword_score": 20,
                "_query_relevance_score": 40,
            }
        ]

        self.assertFalse(
            kb_service.should_merge_keyword_fallback_for_results(
                "遙控器可以送到府嗎？",
                docs,
            )
        )

    def test_specific_question_without_matching_faq_wording_enables_fallback(self):
        docs = [
            {
                "question": "LINE TV 新裝優惠",
                "answer": "新裝用戶可享 LINE TV 優惠。",
                "_keyword_score": 12,
                "_query_relevance_score": 48,
            }
        ]

        self.assertTrue(
            kb_service.should_merge_keyword_fallback_for_results(
                "LINE TV 要怎麼掃 QR Code 登入電視？",
                docs,
            )
        )

    def test_broad_product_title_cannot_suppress_precise_faq_fallback(self):
        docs = [
            {
                "question": "機上盒與寬頻方案優惠",
                "answer": "方案可借用數位機上盒，並提供相關設備服務。",
                "_keyword_score": 18,
                "_query_relevance_score": 93,
                "_query_direct_evidence_score": 330,
            }
        ]

        self.assertTrue(
            kb_service.should_merge_keyword_fallback_for_results(
                "機上盒能不能錄節目？",
                docs,
            )
        )

    def test_precise_question_side_match_keeps_semantic_result(self):
        docs = [
            {
                "question": "複製遙控器設定方式",
                "answer": "依照說明完成配對設定。",
                "_keyword_score": 8,
                "_query_relevance_score": 30,
            }
        ]

        self.assertTrue(
            kb_service.has_precise_question_side_match(
                "複製遙控器要怎麼設定？",
                docs[0],
            )
        )

    def test_functional_question_paraphrases_are_added_for_keyword_scan(self):
        recording_terms = kb_service.build_keyword_terms("機上盒能不能錄節目？")
        channel_terms = kb_service.build_keyword_terms("為什麼頻道超過 200 台就不能看？")
        installment_terms = kb_service.build_keyword_terms("有線電視費可以分期付款嗎？")

        self.assertIn("錄影", recording_terms)
        self.assertIn("200台以後", channel_terms)
        self.assertIn("繳費分期", installment_terms)

    def test_senior_service_overview_scores_above_specific_subfeature(self):
        query = "有沒有適合家中長輩使用的服務？"
        overview = {
            "question": "台數科能提供給年長者的服務有哪些",
            "answer": "熊搭心包含電視電話、家庭相簿與生活提醒。",
        }
        subfeature = {
            "question": "什麼是生活提醒",
            "answer": "生活提醒可協助長輩安排回診通知。",
        }

        self.assertGreater(
            kb_service.score_query_facet_evidence(query, overview),
            kb_service.score_query_facet_evidence(query, subfeature),
        )

    def test_semantic_results_missing_distinctive_subject_enable_document_scan(self):
        docs = [
            {
                "question": "機上盒與電視設備說明",
                "answer": "設備異常可重新啟動後確認。",
                "_keyword_score": 10,
                "_query_relevance_score": 48,
            }
        ]

        self.assertTrue(
            kb_service.should_merge_keyword_fallback_for_results(
                "一般遙控器壞了，買一支多少？",
                docs,
            )
        )

    def test_semantic_results_with_distinctive_subject_do_not_force_document_scan(self):
        docs = [
            {
                "question": "一般型遙控器購買價格",
                "answer": "一般型遙控器每支 300 元。",
                "_keyword_score": 10,
                "_query_relevance_score": 48,
            }
        ]

        self.assertFalse(
            kb_service.should_merge_keyword_fallback_for_results(
                "一般遙控器壞了，買一支多少？",
                docs,
            )
        )

    def test_subject_evidence_ignores_generic_question_words(self):
        evidence = kb_service.extract_query_subject_evidence_bigrams(
            "請問網路費用要怎麼查詢？"
        )

        self.assertNotIn("網路", evidence)
        self.assertNotIn("費用", evidence)
        self.assertNotIn("查詢", evidence)

    def test_missing_natural_subject_anchor_forces_keyword_fallback(self):
        docs = [
            {
                "question": "優惠方案機上盒設定",
                "answer": "申辦網路與有線電視可借用機上盒。",
                "_keyword_score": 8,
                "_query_relevance_score": 30,
            }
        ]

        self.assertTrue(
            kb_service.should_merge_keyword_fallback_for_results(
                "複製遙控器要怎麼設定？",
                docs,
            )
        )

    def test_high_scoring_broad_results_still_enable_exact_subject_fallback(self):
        docs = [
            {
                "question": "寬頻與機上盒優惠活動",
                "answer": "申辦方案可享設備與點數優惠。",
                "_keyword_score": 12,
                "_query_relevance_score": 129,
            }
        ]

        self.assertTrue(
            kb_service.should_merge_keyword_fallback_for_results(
                "固定 IP 要怎麼申請？",
                docs,
            )
        )

    def test_present_natural_subject_anchor_keeps_semantic_results(self):
        docs = [
            {
                "question": "複製遙控器設定方式",
                "answer": "依照說明完成配對設定。",
                "_keyword_score": 8,
                "_query_relevance_score": 30,
            }
        ]

        self.assertFalse(
            kb_service.should_merge_keyword_fallback_for_results(
                "複製遙控器要怎麼設定？",
                docs,
            )
        )

    def test_keyword_normalization_removes_fullwidth_question_mark(self):
        self.assertEqual(
            kb_service.normalize_keyword_text("複製遙控器要怎麼設定？"),
            "複製遙控器要怎麼設定",
        )
        self.assertEqual(
            kb_service.extract_query_anchor_terms("複製遙控器要怎麼設定？"),
            ["複製遙控器"],
        )

    def test_exact_subject_anchor_precedes_broad_semantic_results(self):
        docs = [
            {
                "question": "寬頻優惠活動",
                "answer": "申辦方案可借用機上盒與相關設備。",
                "company": "大屯",
                "_query_relevance_score": 40,
                "_keyword_score": 0,
            },
            {
                "question": "複製遙控器設定",
                "answer": "依說明按鍵完成複製遙控器配對。",
                "company": "通用-中區",
                "_query_relevance_score": 12,
                "_keyword_score": 4,
            },
        ]

        ranked = kb_service.sort_docs_by_company_priority(
            docs,
            {"knowledge_base": "大屯"},
            "複製遙控器要怎麼設定？",
        )

        self.assertEqual(ranked[0]["company"], "通用-中區")

    def test_direct_error_code_evidence_precedes_local_scope_similarity(self):
        docs = [
            {
                "question": "機上盒常見問題",
                "answer": "設備異常時請重新啟動。",
                "company": "大屯",
                "_query_relevance_score": 80,
                "_keyword_score": 12,
            },
            {
                "question": "錯誤代碼 E003",
                "answer": "E003 表示數位機上盒授權或訊號異常。",
                "company": "通用-中區",
                "_query_relevance_score": 12,
                "_keyword_score": 4,
            },
        ]

        ranked = kb_service.sort_docs_by_company_priority(
            docs,
            {"knowledge_base": "大屯"},
            "電視跳出 E003 是什麼意思？",
        )

        self.assertEqual(ranked[0]["company"], "通用-中區")

    def test_direct_subject_evidence_precedes_unrelated_local_result(self):
        docs = [
            {
                "question": "網路與電視設備說明",
                "answer": "申辦方案可借用相關設備。",
                "company": "大屯",
                "_query_relevance_score": 80,
                "_keyword_score": 12,
            },
            {
                "question": "一般型遙控器購買價格",
                "answer": "一般型遙控器每支 300 元。",
                "company": "通用-中區",
                "_query_relevance_score": 12,
                "_keyword_score": 4,
            },
        ]

        ranked = kb_service.sort_docs_by_company_priority(
            docs,
            {"knowledge_base": "大屯"},
            "一般遙控器壞了，買一支多少？",
        )

        self.assertEqual(ranked[0]["company"], "通用-中區")

    def test_scope_priority_remains_when_neither_doc_has_direct_evidence(self):
        docs = [
            {
                "question": "當地設備說明",
                "answer": "請依現場狀況確認。",
                "company": "大屯",
                "_query_relevance_score": 12,
            },
            {
                "question": "通用設備說明",
                "answer": "請依設備狀況確認。",
                "company": "通用-中區",
                "_query_relevance_score": 80,
            },
        ]

        ranked = kb_service.sort_docs_by_company_priority(
            docs,
            {"knowledge_base": "大屯"},
            "我要詢問服務內容",
        )

        self.assertEqual(ranked[0]["company"], "大屯")

    def test_distinctive_state_in_question_precedes_broad_local_mention(self):
        docs = [
            {
                "question": "寬頻新裝優惠方案",
                "answer": "方案包含網路服務與數據機設備。",
                "company": "大屯",
                "_query_relevance_score": 90,
            },
            {
                "question": "網路不穩或很慢或斷線時不好使用",
                "answer": "請先檢查數據機與分享器。",
                "company": "通用-中區",
                "_query_relevance_score": 12,
            },
        ]

        ranked = kb_service.sort_docs_by_company_priority(
            docs,
            {"knowledge_base": "大屯"},
            "網路最近一直斷斷續續，很不穩",
        )

        self.assertEqual(ranked[0]["company"], "通用-中區")

    def test_action_in_question_differentiates_same_named_product(self):
        docs = [
            {
                "question": "好視成雙優惠",
                "answer": "方案贈送 LINE TV 半年。",
                "company": "大屯",
                "_query_relevance_score": 90,
            },
            {
                "question": "如何取消 LINE TV",
                "answer": "若不續用可依說明取消服務。",
                "company": "通用-中區",
                "_query_relevance_score": 12,
            },
        ]

        ranked = kb_service.sort_docs_by_company_priority(
            docs,
            {"knowledge_base": "大屯"},
            "我不想續用 LINE TV，要怎麼取消？",
        )

        self.assertEqual(ranked[0]["company"], "通用-中區")

    def test_local_scope_wins_when_both_results_have_exact_subject_anchor(self):
        docs = [
            {
                "question": "固定 IP 申請方式",
                "answer": "大屯適用的申請說明。",
                "company": "大屯",
                "_query_relevance_score": 12,
                "_keyword_score": 4,
            },
            {
                "question": "如何申請固定 IP",
                "answer": "通用申請說明。",
                "company": "通用-中區",
                "_query_relevance_score": 40,
                "_keyword_score": 12,
            },
        ]

        ranked = kb_service.sort_docs_by_company_priority(
            docs,
            {"knowledge_base": "大屯"},
            "固定 IP 要怎麼申請？",
        )

        self.assertEqual(ranked[0]["company"], "大屯")

    def test_matching_faq_question_precedes_generic_answer_repetition(self):
        docs = [
            {
                "question": "機上盒相關說明",
                "answer": "申辦服務會提供機上盒，設備請妥善保管。",
                "company": "通用-中區",
                "source": {"section": "row 1", "title": "機上盒相關說明"},
                "_query_relevance_score": 3,
                "_keyword_score": 6,
            },
            {
                "question": "機上盒可以錄影嗎?",
                "answer": "因智慧財產權因素，機上盒無法提供錄影功能。",
                "company": "通用-中區",
                "source": {"section": "row 30", "title": "機上盒可以錄影嗎?"},
                "_query_relevance_score": 42,
                "_keyword_score": 16,
            },
        ]

        ranked = kb_service.sort_docs_by_company_priority(
            docs,
            {"knowledge_base": "大屯"},
            "機上盒能不能錄節目？",
        )

        self.assertEqual(ranked[0]["question"], "機上盒可以錄影嗎?")

    def test_generated_question_paraphrase_beats_generic_local_result(self):
        scenarios = [
            (
                "機上盒能不能錄節目？",
                "機上盒可以錄影嗎?",
                "因智慧財產權因素，機上盒無法提供錄影功能。",
            ),
            (
                "為什麼頻道超過 200 台就不能看？",
                "第四台無法觀看200台之後",
                "200 台以後屬於付費頻道，需要額外訂閱。",
            ),
            (
                "有線電視費可以分期付款嗎？",
                "可繳費分期嗎",
                "目前帳單無法辦理分期付款。",
            ),
        ]
        for query, faq_question, faq_answer in scenarios:
            with self.subTest(query=query):
                docs = [
                    {
                        "question": "一般服務與費用說明",
                        "answer": "可洽詢有線電視、機上盒與各項繳費服務。",
                        "company": "大屯",
                        "source": {"section": "document", "title": "一般服務與費用說明"},
                        "_query_relevance_score": 80,
                        "_keyword_score": 18,
                    },
                    {
                        "question": faq_question,
                        "answer": faq_answer,
                        "company": "通用-中區",
                        "source": {"section": "row 30", "title": faq_question},
                        "_query_relevance_score": 4,
                        "_keyword_score": 2,
                    },
                ]

                ranked = kb_service.sort_docs_by_company_priority(
                    docs,
                    {"knowledge_base": "大屯"},
                    query,
                )

                self.assertEqual(ranked[0]["question"], faq_question)

    def test_strict_identifier_still_precedes_soft_faq_match(self):
        docs = [
            {
                "question": "設備錯誤說明",
                "answer": "一般設備異常時請重新啟動。",
                "company": "大屯",
                "source": {"section": "row 2", "title": "設備錯誤說明"},
                "_query_relevance_score": 80,
                "_keyword_score": 18,
            },
            {
                "question": "錯誤代碼 E003",
                "answer": "E003 表示數位機上盒授權或訊號異常。",
                "company": "通用-中區",
                "source": {"section": "row 9", "title": "錯誤代碼 E003"},
                "_query_relevance_score": 12,
                "_keyword_score": 4,
            },
        ]

        ranked = kb_service.sort_docs_by_company_priority(
            docs,
            {"knowledge_base": "大屯"},
            "電視跳出 E003 是什麼意思？",
        )

        self.assertEqual(ranked[0]["question"], "錯誤代碼 E003")

    def test_specific_campaign_query_prefers_matching_campaign_docs(self):
        docs = [
            {
                "question": "一般寬頻方案",
                "answer": "方案名稱：一般寬頻方案\n300M/300M：月繳$900元。",
                "company": "北港",
                "document_type": "promotion_campaign",
                "campaign_name": "一般寬頻方案",
                "campaign_aliases": "一般寬頻方案",
            },
            {
                "question": "星耀暢網 X7",
                "answer": "方案名稱：星耀暢網 X7\n300M/300M：月繳$799元。",
                "company": "北港",
                "document_type": "promotion_campaign",
                "campaign_name": "星耀暢網 X7",
                "campaign_aliases": "星耀暢網 X7 | 星耀暢網X7",
            },
        ]

        filtered = kb_service.filter_docs_for_query_intent("星耀暢網 X7 300M多少錢?", docs)

        self.assertEqual(len(filtered), 1)
        self.assertEqual(filtered[0]["question"], "星耀暢網 X7")

    def test_new_campaign_alias_is_not_limited_to_hardcoded_campaign_names(self):
        docs = [
            {
                "question": "一般寬頻方案",
                "answer": "300M/300M 月繳900元。",
                "company": "大屯",
                "document_type": "promotion_campaign",
                "campaign_name": "一般寬頻方案",
                "campaign_aliases": "一般寬頻方案",
            },
            {
                "question": "星耀暢網 X7 300M/300M 24個月",
                "answer": "月繳899元，贈LINE TV半年。",
                "company": "大屯",
                "document_type": "promotion_campaign",
                "campaign_name": "星耀暢網 X7",
                "campaign_aliases": "星耀暢網 X7 | 星耀暢網X7",
                "speeds": "300M/300M",
                "contract_months": "24",
            },
        ]

        filtered = kb_service.filter_docs_for_query_intent(
            "星耀暢網X7的300M方案綁多久？",
            docs,
        )

        self.assertEqual(len(filtered), 1)
        self.assertEqual(filtered[0]["campaign_name"], "星耀暢網 X7")

    def test_campaign_holiday_gift_and_lottery_metadata_improves_relevance(self):
        campaign_doc = {
            "question": "爸氣獻禮好康活動",
            "answer": "申裝即贈智慧音箱或氣炸鍋二擇一，另可參加抽獎。",
            "document_type": "promotion_campaign",
            "campaign_name": "爸氣獻禮好康活動",
            "campaign_aliases": "爸氣獻禮好康活動",
            "occasion_terms": "父親節 | 爸爸節 | 爸氣",
            "gift_items": "申裝即贈智慧音箱或氣炸鍋二擇一",
            "lottery_details": "抽獎獎項為65吋電視",
        }
        unrelated_doc = {
            "question": "一般寬頻優惠方案",
            "answer": "300M/300M 月繳899元。",
            "document_type": "promotion_campaign",
            "campaign_name": "一般寬頻優惠方案",
            "campaign_aliases": "一般寬頻優惠方案",
        }

        for query in (
            "父親節有什麼優惠活動？",
            "爸氣獻禮會送什麼贈品？",
            "爸氣獻禮抽獎的獎品是什麼？",
        ):
            self.assertGreater(
                kb_service.score_query_relevance(query, campaign_doc),
                kb_service.score_query_relevance(query, unrelated_doc),
            )

    def test_parent_day_discovery_filters_unrelated_campaigns(self):
        dad_campaign = {
            "question": "爸氣獻禮",
            "answer": "父親節申裝優惠，LINE TV 贈送 6 個月。",
            "document_type": "promotion_campaign",
            "campaign_name": "爸氣獻禮",
            "occasion_terms": "父親節 | 爸爸節 | 爸氣",
            "valid_period": "115.08.01~115.09.30",
        }
        generic_campaign = {
            "question": "飆網守護家 B2606",
            "answer": "一般網路贈清冰組方案。",
            "document_type": "promotion_campaign",
            "campaign_name": "飆網守護家 B2606",
            "valid_period": "2026/06/05~2026/09/30",
        }

        filtered = kb_service.filter_campaigns_by_discovery_context(
            "父親節有優惠方案嗎？",
            [generic_campaign, dad_campaign],
        )

        self.assertEqual([doc["campaign_name"] for doc in filtered], ["爸氣獻禮"])

    def test_august_discovery_prefers_campaign_starting_in_august(self):
        dad_campaign = {
            "question": "爸氣獻禮",
            "answer": "8 月父親節優惠。",
            "document_type": "promotion_campaign",
            "campaign_name": "爸氣獻禮",
            "valid_period": "115.08.01~115.09.30",
        }
        older_campaign = {
            "question": "飆網守護家 B2606",
            "answer": "6 月開始的一般活動。",
            "document_type": "promotion_campaign",
            "campaign_name": "飆網守護家 B2606",
            "valid_period": "2026/06/05~2026/09/30",
        }

        self.assertGreater(
            kb_service.score_query_relevance("八月優惠活動", dad_campaign),
            kb_service.score_query_relevance("八月優惠活動", older_campaign),
        )
        self.assertEqual(kb_service.extract_calendar_months("十一月優惠"), {11})

    def test_august_promotion_final_selection_keeps_multiple_campaign_documents(self):
        docs = [
            {
                "id": "dad-profile",
                "document_id": "dad-doc",
                "question": "大屯爸氣獻禮11508",
                "answer": "方案名稱：爸氣獻禮，活動期間115.08.01~115.09.30。",
                "document_type": "promotion_campaign",
                "campaign_name": "爸氣獻禮",
                "valid_period": "115.08.01~115.09.30",
            },
            {
                "id": "dad-lottery",
                "document_id": "dad-doc",
                "question": "爸氣獻禮抽獎",
                "answer": "每月抽獎兩次。",
                "document_type": "promotion_campaign",
                "campaign_name": "爸氣獻禮",
                "valid_period": "115.08.01~115.09.30",
            },
            {
                "id": "dad-gifts",
                "document_id": "dad-doc",
                "question": "爸氣獻禮贈點",
                "answer": "季繳588點。",
                "document_type": "promotion_campaign",
                "campaign_name": "爸氣獻禮",
                "valid_period": "115.08.01~115.09.30",
            },
            {
                "id": "no8-profile",
                "document_id": "no8-doc",
                "question": "好視成雙NO8",
                "answer": "方案名稱：好視成雙NO8，活動至115.08.31。",
                "document_type": "promotion_campaign",
                "campaign_name": "好視成雙NO8",
                "valid_period": "115.06.10~115.08.31",
            },
            {
                "id": "b2606-profile",
                "document_id": "b2606-doc",
                "question": "飆網守護家B2606",
                "answer": "活動至2026/09/30。",
                "document_type": "promotion_campaign",
                "campaign_name": "飆網守護家B2606",
                "valid_period": "2026/06/05~2026/09/30",
            },
        ]

        selected = kb_service.finalize_docs_for_query("八月的優惠活動", docs, top_k=4)

        self.assertEqual(
            [doc["id"] for doc in selected],
            ["dad-profile", "no8-profile", "b2606-profile", "dad-lottery"],
        )
        self.assertEqual(
            len({kb_service.campaign_document_group_key(doc) for doc in selected[:3]}),
            3,
        )

    def test_generic_promotion_prefers_complete_overview_to_gift_only_chunk(self):
        docs = [
            {
                "id": "dad-line-tv",
                "document_id": "dad-doc",
                "question": "寬頻新裝機首期贈送 LINE TV 半年 POINT 贈點規則",
                "answer": (
                    "【方案名稱】寬頻新裝機首期贈送 LINE TV 半年\n"
                    "【LINE TV 贈送月數】贈 6 個月\n"
                    "【POINT 贈點規則】季繳 588 點"
                ),
                "document_type": "promotion_campaign",
                "record_type": "campaign_variant",
                "campaign_name": "爸氣獻禮",
                "valid_period": "115.08.01~115.09.30",
            },
            {
                "id": "dad-profile",
                "document_id": "dad-doc",
                "question": "爸氣獻禮 八月優惠活動 完整方案",
                "answer": (
                    "方案名稱：爸氣獻禮\n"
                    "活動期間：115.08.01~115.09.30\n"
                    "100M/10M：月繳399元、季繳1197元\n"
                    "綁約24個月，違約金2400元逐月遞減\n"
                    "LINE TV 贈送6個月，另有POINT贈點及抽獎資格。"
                ),
                "document_type": "promotion_campaign",
                "record_type": "campaign_summary",
                "campaign_name": "爸氣獻禮",
                "valid_period": "115.08.01~115.09.30",
            },
            {
                "id": "no8-profile",
                "document_id": "no8-doc",
                "question": "好視成雙NO8",
                "answer": "方案名稱：好視成雙NO8\n活動期間：115.06.10~115.08.31\n300M/300M月繳899元。",
                "document_type": "promotion_campaign",
                "record_type": "campaign_summary",
                "campaign_name": "好視成雙NO8",
            },
        ]

        selected = kb_service.finalize_docs_for_query("優惠活動", docs, top_k=3)

        self.assertEqual(selected[0]["id"], "dad-profile")
        self.assertEqual(selected[1]["id"], "no8-profile")
        self.assertEqual(selected[2]["id"], "dad-line-tv")

    def test_generic_promotion_does_not_fall_back_to_unrelated_addon_docs(self):
        docs = [
            {
                "id": "line-tv-addon",
                "question": "LINE TV 新裝機首期優惠",
                "answer": "新裝機首期贈送 LINE TV 半年。",
                "document_type": "product_service_catalog",
                "record_type": "product_service",
            },
            {
                "id": "paid-channel",
                "question": "數位電視頻道加購",
                "answer": "HBO 加價購每月 39 元。",
            },
        ]

        filtered = kb_service.filter_docs_for_query_intent("優惠活動", docs)

        self.assertEqual(filtered, [])

    def test_generic_keyword_fallback_scans_profiled_campaign_without_literal_term(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            docs_dir = tmp_path / "kb_documents"
            docs_dir.mkdir()
            campaign_path = docs_dir / "dad_campaign.txt"
            campaign_path.write_text(
                "方案名稱：爸氣獻禮\n"
                "活動期間：115.08.01~115.09.30\n"
                "100M/10M：月繳399元、季繳1197元\n"
                "綁約24個月，違約金2400元逐月遞減\n"
                "LINE TV贈送6個月，另有POINT贈點及抽獎資格。\n",
                encoding="utf-8",
            )
            addon_path = docs_dir / "line_tv.txt"
            addon_path.write_text(
                "LINE TV新裝機首期贈送半年，到期恢復原價。\n",
                encoding="utf-8",
            )
            manifest_path = docs_dir / "documents.json"
            manifest_path.write_text(
                """{
  "documents": [
    {
      "id": "dad-doc",
      "title": "爸氣獻禮11508",
      "file_name": "dad_campaign.txt",
      "file_path": "%s",
      "knowledge_base": "大屯",
      "category": "billing",
      "status": "active",
      "processing_status": "indexed",
      "campaign_profile": {
        "document_type": "promotion_campaign",
        "campaign_name": "爸氣獻禮",
        "aliases": ["爸氣獻禮"],
        "valid_period": "115.08.01~115.09.30"
      }
    },
    {
      "id": "line-tv-doc",
      "title": "LINE TV首期贈送",
      "file_name": "line_tv.txt",
      "file_path": "%s",
      "knowledge_base": "大屯",
      "category": "value_added_service",
      "status": "active",
      "processing_status": "indexed"
    }
  ]
}""" % (
                    str(campaign_path).replace("\\", "\\\\"),
                    str(addon_path).replace("\\", "\\\\"),
                ),
                encoding="utf-8",
            )

            with patch.object(kb_service, "RAG_LOCAL_MANIFEST_PATH", str(manifest_path)), \
                    patch.object(kb_service, "RAG_LOCAL_DOCS_DIR", str(docs_dir)):
                docs = kb_service.retrieve_knowledge_from_keyword_fallback(
                    "優惠活動",
                    {"company_code": "tdtv"},
                    top_k=5,
                )

        self.assertEqual(len(docs), 1)
        self.assertEqual(docs[0]["campaign_name"], "爸氣獻禮")
        self.assertIn("月繳399元", docs[0]["answer"])
        self.assertNotIn("LINE TV首期贈送", docs[0]["question"])

    def test_expanded_august_query_cannot_be_hijacked_by_line_tv_product_terms(self):
        expanded_query = (
            "優惠活動 節慶 節日 活動期間 方案名稱 售價 速率 繳別 贈品 "
            "LINE TV POINTS 抽獎資格 抽獎獎項 八月的優惠活動"
        )
        docs = [
            {
                "id": "line-tv",
                "question": "LINE TV 新裝機首期優惠",
                "answer": "新裝機首期贈送 LINE TV 半年。",
                "document_type": "product_service_catalog",
                "record_type": "product_service",
                "product_name": "LINE TV",
            },
            {
                "id": "dad",
                "question": "大屯爸氣獻禮11508",
                "answer": "方案名稱：爸氣獻禮。",
                "document_type": "promotion_campaign",
                "campaign_name": "爸氣獻禮",
                "valid_period": "115.08.01~115.09.30",
            },
            {
                "id": "no8",
                "question": "好視成雙NO8",
                "answer": "方案名稱：好視成雙NO8。",
                "document_type": "promotion_campaign",
                "campaign_name": "好視成雙NO8",
                "valid_period": "115.06.10~115.08.31",
            },
        ]

        filtered = kb_service.filter_docs_for_query_intent(expanded_query, docs)

        self.assertEqual([doc["id"] for doc in filtered], ["dad", "no8"])

    def test_retrieve_august_discovery_uses_raw_user_query_not_expansion(self):
        dad_doc = {
            "id": "dad",
            "question": "大屯爸氣獻禮11508",
            "answer": "方案名稱：爸氣獻禮。",
            "document_type": "promotion_campaign",
            "campaign_name": "爸氣獻禮",
            "valid_period": "115.08.01~115.09.30",
        }
        expanded_query = (
            "優惠活動 節慶 節日 活動期間 方案名稱 售價 速率 繳別 贈品 "
            "LINE TV POINTS 抽獎資格 抽獎獎項 八月的優惠活動"
        )

        with (
            patch.object(
                kb_service,
                "retrieve_knowledge_from_local_chroma",
                return_value=[dad_doc],
            ) as local_retrieve,
            patch.object(
                kb_service,
                "should_merge_keyword_fallback_for_results",
                return_value=False,
            ),
            patch.object(kb_service, "filter_docs_for_active_campaign_alias", side_effect=lambda query, memory, docs: docs),
        ):
            docs = kb_service.retrieve_knowledge(
                "八月的優惠活動",
                {"company": "大屯有線"},
                controller_output={"knowledge_query": expanded_query},
            )

        self.assertEqual(local_retrieve.call_args.args[0], "八月的優惠活動")
        self.assertEqual(docs, [dad_doc])

    def test_new_topic_uses_customer_wording_over_controller_query_rewrite(self):
        payment_doc = {
            "id": "payment-overview",
            "question": "查詢繳費方式",
            "answer": "可透過官網、APP、臨櫃、超商、ibon 或 FamiPort 繳費。",
        }

        with (
            patch.object(
                kb_service,
                "retrieve_knowledge_from_local_chroma",
                return_value=[payment_doc],
            ) as local_retrieve,
            patch.object(
                kb_service,
                "should_merge_keyword_fallback_for_results",
                return_value=False,
            ),
            patch.object(
                kb_service,
                "filter_docs_for_active_campaign_alias",
                side_effect=lambda query, memory, docs: docs,
            ),
        ):
            docs = kb_service.retrieve_knowledge(
                "繳費方式",
                {"company_code": "tdtv"},
                controller_output={
                    "knowledge_query": "繳費方式 ibon FamiPort 超商繳費機操作流程",
                    "should_cancel_current_flow": True,
                },
            )

        self.assertEqual(local_retrieve.call_args.args[0], "繳費方式")
        self.assertEqual(docs, [payment_doc])

    def test_bare_500mbps_fee_query_uses_canonical_broadband_retrieval_terms(self):
        price_doc = {
            "id": "500m-price",
            "question": "哈NET1 寬頻方案",
            "answer": "500M/500M 月繳 1,100 元，半年繳 6,600 元，年繳 13,200 元。",
        }

        with (
            patch.object(
                kb_service,
                "retrieve_knowledge_from_local_chroma",
                return_value=[price_doc],
            ) as local_retrieve,
            patch.object(
                kb_service,
                "should_merge_keyword_fallback_for_results",
                return_value=False,
            ),
            patch.object(
                kb_service,
                "filter_docs_for_active_campaign_alias",
                side_effect=lambda query, memory, docs: docs,
            ),
        ):
            docs = kb_service.retrieve_knowledge(
                "500mbps費用",
                {"company_code": "toplight"},
                controller_output={"knowledge_query": "500mbps費用"},
            )

        retrieval_query = local_retrieve.call_args.args[0]
        self.assertIn("500m/500m", retrieval_query.lower())
        self.assertIn("寬頻網路", retrieval_query)
        self.assertEqual(docs, [price_doc])

    def test_august_discovery_merges_campaigns_when_vector_results_are_hijacked(self):
        unrelated_line_tv_doc = {
            "id": "line-tv",
            "question": "LINE TV 新裝機首期優惠",
            "answer": "新裝機首期贈送 LINE TV 半年。",
            "document_type": "product_service_catalog",
            "record_type": "product_service",
            "product_name": "LINE TV",
        }
        dad_doc = {
            "id": "dad",
            "document_id": "dad-doc",
            "question": "大屯爸氣獻禮11508",
            "answer": "方案名稱：爸氣獻禮。",
            "document_type": "promotion_campaign",
            "campaign_name": "爸氣獻禮",
            "valid_period": "115.08.01~115.09.30",
        }
        no8_doc = {
            "id": "no8",
            "document_id": "no8-doc",
            "question": "好視成雙NO8",
            "answer": "方案名稱：好視成雙NO8。",
            "document_type": "promotion_campaign",
            "campaign_name": "好視成雙NO8",
            "valid_period": "115.06.10~115.08.31",
        }
        expanded_query = (
            "優惠活動 節慶 節日 活動期間 方案名稱 售價 速率 繳別 贈品 "
            "LINE TV POINTS 抽獎資格 抽獎獎項 八月的優惠活動"
        )

        with (
            patch.object(
                kb_service,
                "retrieve_knowledge_from_local_chroma",
                return_value=[unrelated_line_tv_doc],
            ) as local_retrieve,
            patch.object(
                kb_service,
                "retrieve_knowledge_from_keyword_fallback",
                return_value=[dad_doc, no8_doc],
            ) as keyword_retrieve,
            patch.object(
                kb_service,
                "filter_docs_for_active_campaign_alias",
                side_effect=lambda query, memory, docs: docs,
            ),
        ):
            docs = kb_service.retrieve_knowledge(
                "八月的優惠活動",
                {"company": "大屯有線"},
                controller_output={"knowledge_query": expanded_query},
                top_k=5,
            )

        self.assertEqual(local_retrieve.call_args.args[0], "八月的優惠活動")
        self.assertEqual(keyword_retrieve.call_args.args[0], "八月的優惠活動")
        self.assertEqual([doc["id"] for doc in docs], ["dad", "no8"])

    def test_fresh_campaign_discovery_ignores_remembered_campaign(self):
        query = build_contextual_knowledge_query(
            "父親節有哪些優惠？",
            "父親節有哪些優惠？",
            {
                "last_campaign_topic": "飆網守護家 B2606",
                "last_knowledge_results": [],
            },
            [],
        )

        self.assertEqual(query, "父親節有哪些優惠？")
        self.assertNotIn("B2606", query)

    def test_multiple_campaign_results_do_not_remember_arbitrary_campaign(self):
        memory = {"last_campaign_topic": "飆網守護家 B2606"}

        remember_campaign_topic(
            memory,
            docs=[
                {"campaign_name": "爸氣獻禮"},
                {"campaign_name": "八月暢網活動"},
            ],
        )

        self.assertNotIn("last_campaign_topic", memory)

    def test_active_campaign_alias_matches_index_metadata_in_current_scope(self):
        records = [
            {
                "id": "campaign-dad-gift",
                "title": "大屯爸氣獻禮11508",
                "knowledge_base": "大屯",
                "campaign_profile": {
                    "document_type": "promotion_campaign",
                    "campaign_name": "爸氣獻禮",
                    "aliases": ["爸氣獻禮", "大屯爸氣獻禮11508"],
                },
            }
        ]

        with patch.object(kb_service, "read_active_kb_document_records", return_value=records):
            matched = kb_service.match_active_campaign_alias(
                "爸氣獻禮有哪些優惠？",
                {"company": "大屯"},
            )

        self.assertIsNotNone(matched)
        self.assertEqual(matched["campaign_name"], "爸氣獻禮")
        self.assertEqual(matched["matched_alias"], "爸氣獻禮")
        self.assertEqual(matched["knowledge_base"], "大屯")

    def test_active_campaign_alias_locks_results_to_matching_document(self):
        records = [
            {
                "id": "campaign-dad-gift",
                "title": "大屯爸氣獻禮11508",
                "knowledge_base": "大屯",
                "campaign_profile": {
                    "document_type": "promotion_campaign",
                    "campaign_name": "爸氣獻禮",
                    "aliases": ["爸氣獻禮", "大屯爸氣獻禮11508"],
                },
            }
        ]
        docs = [
            {
                "id": "campaign-no8:1",
                "question": "好視成雙NO8",
                "answer": "500M 月繳999元。",
                "source": {"document_id": "campaign-no8"},
            },
            {
                "id": "campaign-dad-gift:1",
                "question": "爸氣獻禮",
                "answer": "100M/10M 月繳399元。",
                "source": {"document_id": "campaign-dad-gift"},
            },
        ]

        with patch.object(kb_service, "read_active_kb_document_records", return_value=records):
            filtered = kb_service.filter_docs_for_active_campaign_alias(
                "優惠方案 爸氣獻禮",
                {"company": "大屯"},
                docs,
            )

        self.assertEqual([doc["id"] for doc in filtered], ["campaign-dad-gift:1"])

    def test_active_campaign_alias_does_not_fall_through_to_other_campaign(self):
        records = [
            {
                "id": "campaign-dad-gift",
                "title": "大屯爸氣獻禮11508",
                "knowledge_base": "大屯",
                "campaign_profile": {
                    "document_type": "promotion_campaign",
                    "campaign_name": "爸氣獻禮",
                    "aliases": ["爸氣獻禮"],
                },
            }
        ]
        docs = [
            {
                "id": "campaign-no8:1",
                "question": "好視成雙NO8",
                "answer": "500M 月繳999元。",
                "source": {"document_id": "campaign-no8"},
            }
        ]

        with patch.object(kb_service, "read_active_kb_document_records", return_value=records):
            filtered = kb_service.filter_docs_for_active_campaign_alias(
                "爸氣獻禮",
                {"company": "大屯"},
                docs,
            )

        self.assertEqual(filtered, [])

    def test_retrieve_knowledge_uses_indexed_alias_instead_of_expanded_campaign_query(self):
        records = [
            {
                "id": "campaign-dad-gift",
                "title": "大屯爸氣獻禮11508",
                "knowledge_base": "大屯",
                "campaign_profile": {
                    "document_type": "promotion_campaign",
                    "campaign_name": "爸氣獻禮",
                    "aliases": ["爸氣獻禮"],
                },
            }
        ]
        expected_doc = {
            "id": "campaign-dad-gift:1",
            "document_id": "campaign-dad-gift",
            "question": "爸氣獻禮",
            "answer": "100M/10M 月繳399元。",
        }

        with (
            patch.object(
                kb_service,
                "read_active_kb_document_records",
                return_value=records,
            ),
            patch.object(
                kb_service,
                "retrieve_knowledge_from_local_chroma",
                return_value=[expected_doc],
            ) as local_retrieve,
            patch.object(
                kb_service,
                "should_merge_keyword_fallback",
                return_value=False,
            ),
        ):
            docs = kb_service.retrieve_knowledge(
                "爸氣獻禮",
                {"company": "大屯"},
                controller_output={
                    "knowledge_query": "爸氣獻禮 優惠方案 月租 贈品 申請資格"
                },
            )

        self.assertEqual(local_retrieve.call_args.args[0], "爸氣獻禮")
        self.assertEqual(docs, [expected_doc])

    def test_campaign_metadata_boosts_matching_speed_and_contract(self):
        query = "星耀暢網X7 300M/300M 綁約24個月多少錢"
        matching = {
            "question": "星耀暢網 X7",
            "answer": "300M/300M 月繳899元。",
            "document_type": "promotion_campaign",
            "campaign_aliases": "星耀暢網 X7 | 星耀暢網X7",
            "speeds": "300M/300M",
            "contract_months": "24",
        }
        other = {
            "question": "其他優惠方案",
            "answer": "500M/500M 月繳999元。",
            "document_type": "promotion_campaign",
            "campaign_aliases": "其他優惠方案",
            "speeds": "500M/500M",
            "contract_months": "36",
        }

        self.assertGreater(
            kb_service.score_query_relevance(query, matching),
            kb_service.score_query_relevance(query, other),
        )

    def test_campaign_context_keeps_distinct_sections_from_the_same_document_together(self):
        docs = [
            {
                "id": "campaign-x7:campaign:2",
                "document_id": "campaign-x7",
                "question": "星耀暢網 X7 300M/300M 費用",
                "answer": "300M/300M 月繳899元。",
                "document_type": "promotion_campaign",
                "campaign_aliases": "星耀暢網 X7 | 星耀暢網X7",
            },
            {
                "id": "campaign-other:campaign:1",
                "document_id": "campaign-other",
                "question": "其他優惠方案",
                "answer": "500M/500M 月繳999元。",
                "document_type": "promotion_campaign",
                "campaign_aliases": "其他優惠",
            },
            {
                "id": "campaign-x7:campaign:3",
                "document_id": "campaign-x7",
                "question": "星耀暢網 X7 贈品",
                "answer": "贈LINE TV半年。",
                "document_type": "promotion_campaign",
                "campaign_aliases": "星耀暢網 X7 | 星耀暢網X7",
            },
        ]

        completed = kb_service.complete_campaign_document_context(
            "星耀暢網X7有哪些優惠？",
            docs,
            top_k=3,
        )

        self.assertEqual(
            [doc["document_id"] for doc in completed[:2]],
            ["campaign-x7", "campaign-x7"],
        )
        self.assertIn("月繳899元", completed[0]["answer"])
        self.assertIn("LINE TV半年", completed[1]["answer"])

    def test_basic_tv_monthly_fee_scores_monthly_block_above_install_fee(self):
        query = "只看第四台 純 TV 有線電視 基本收費 收視費 月租 月費 裝機費 第四台一個月多少錢"
        install_doc = {
            "question": "北港_TV_基本收費標準11507",
            "answer": "一、TV裝機費與行政規費\n裝機費用$1,500元。月費保留復機$200。",
            "company": "北港",
        }
        monthly_doc = {
            "question": "北港_TV_基本收費標準11507",
            "answer": "二、TV 收視費(月費)標準\n年繳$6,480、半年繳$3,240、季繳$1,620、月繳$540。",
            "company": "北港",
        }

        install_score = kb_service.score_query_relevance(query, install_doc)
        monthly_score = kb_service.score_query_relevance(query, monthly_doc)

        self.assertGreater(monthly_score, install_score)

    def test_hatv_package_table_content_merges_rows_until_next_package(self):
        chunks = [
            {"section": "table 1 row 1", "content": "哈TV-A套餐 (原價1250元/月)"},
            {"section": "table 1 row 2", "content": "CH | 頻道名稱 | 原價格"},
            {"section": "table 1 row 3", "content": "1 | 200 | Discovery Asia | 100元/月"},
            {"section": "table 1 row 4", "content": "2 | 201 | Discovery科學頻道 | 100元/月"},
            {"section": "table 1 row 5", "content": "哈TV-B套餐 (原價700元/月)"},
            {"section": "table 1 row 6", "content": "1 | 202 | DMAX | 100元/月"},
        ]

        content = kb_service.build_hatv_package_table_content(chunks, "A")

        self.assertIn("哈TV-A套餐", content)
        self.assertIn("Discovery Asia", content)
        self.assertIn("Discovery科學頻道", content)
        self.assertNotIn("哈TV-B套餐", content)
        self.assertNotIn("DMAX", content)

    def test_hatv_package_query_filters_unrelated_addon_docs(self):
        docs = [
            {
                "question": "哈TV-A套餐頻道內容",
                "answer": "哈TV-A套餐 (原價1250元/月)\n1 | 200 | Discovery Asia | 100元/月",
                "company": "北港",
                "_hatv_package_table": True,
            },
            {
                "question": "我想訂閱成人頻道",
                "answer": "可透過機上盒購買，使用遙控器進入 VIP會員 → 優惠專區 → 數位電視。",
                "company": "通用",
            },
        ]

        filtered = kb_service.filter_docs_for_query_intent("雲林 哈TV A套餐 頻道內容", docs)

        self.assertEqual(len(filtered), 1)
        self.assertEqual(filtered[0]["question"], "哈TV-A套餐頻道內容")

    def test_authorization_expired_is_not_restricted_channel_purchase(self):
        self.assertFalse(
            kb_service.is_restricted_channel_purchase_query(
                "機上盒出現 E004 授權到期，該怎麼處理？"
            )
        )
        self.assertTrue(
            kb_service.is_restricted_channel_purchase_query("我要訂閱成人頻道")
        )

    def test_named_campaign_query_can_retrieve_campaign_from_other_company_base(self):
        seen_bases = []

        class FakeSearcher:
            def search(self, query, top_k, knowledge_base=None, category=None):
                seen_bases.append(knowledge_base)
                if knowledge_base != "大屯":
                    return []
                return [
                    {
                        "id": "b2606-campaign",
                        "document_id": "campaign-doc",
                        "question": "飆網守護家B2606",
                        "answer": "方案名稱：飆網守護家 B2606。300M/300M：季繳$1797、半年繳$3594、年繳$7188。",
                        "company": "大屯",
                        "category": "billing",
                        "source": "飆網守護家_B2606_AI版.docx",
                        "title": "飆網守護家B2606",
                        "_score": 0.93,
                        "_distance": 0.08,
                    }
                ]

        with patch.object(kb_service, "RAG_BACKEND", "local"), \
                patch.object(kb_service, "load_local_searcher", return_value=FakeSearcher()), \
                patch.object(kb_service, "read_active_kb_document_records", return_value=[]):
            docs = kb_service.retrieve_knowledge(
                "飆網守護家 300M多少錢?",
                {"company_code": "pktv"},
                {"knowledge_query": "飆網守護家 B2606 300M多少錢?"},
                top_k=3,
            )

        self.assertIn("北港", seen_bases)
        self.assertIn("大屯", seen_bases)
        self.assertEqual(docs[0]["id"], "b2606-campaign")

    def test_retrieve_knowledge_calls_rag_api_and_normalizes_sources(self):
        response = Mock()
        response.status_code = 200
        response.json.return_value = {
            "plan_name": "好康三合一",
            "knowledge_base": "大屯",
            "limit": 5,
            "include_expired": False,
            "count": 1,
            "sources": [
                {
                    "document_id": "doc-1",
                    "chunk_id": "chunk-1",
                    "source": "好康三合一(台中區)1150107",
                    "title": "好康三合一(台中區)1150107",
                    "knowledge_base": "大屯",
                    "category": None,
                    "score": 3,
                    "content": "申裝寬頻網路即可免費享有 LINE TV，並免費借用 OTT 盒子。",
                }
            ],
        }

        with patch.object(kb_service, "RAG_BACKEND", "api"), \
                patch.object(kb_service, "RAG_API_URL", "http://rag.internal/search"), \
                patch.object(kb_service, "RAG_API_TIMEOUT_SECONDS", 7), \
                patch.object(kb_service.requests, "post", return_value=response) as post:
            docs = kb_service.retrieve_knowledge(
                "請問好康三合一",
                {"company_code": "tdtv"},
                {"knowledge_query": "好康三合一"},
                top_k=5,
            )

        post.assert_called_once_with(
            "http://rag.internal/search",
            json={
                "plan_name": "好康三合一",
                "knowledge_base": "大屯",
                "limit": 5,
                "include_expired": False,
            },
            timeout=7,
        )
        self.assertEqual(docs[0]["id"], "chunk-1")
        self.assertEqual(docs[0]["question"], "好康三合一(台中區)1150107")
        self.assertEqual(docs[0]["answer"], "申裝寬頻網路即可免費享有 LINE TV，並免費借用 OTT 盒子。")
        self.assertEqual(docs[0]["company"], "大屯")
        self.assertEqual(docs[0]["_score"], 3)
        self.assertEqual(docs[0]["source"]["document_id"], "doc-1")

        reply = compose_knowledge_reply(
            "請問好康三合一",
            "",
            docs,
            answer_guard_query="好康三合一",
            memory={"company_code": "tdtv"},
        )
        self.assertEqual(reply, "申裝寬頻網路即可免費享有 LINE TV，並免費借用 OTT 盒子。")

    def test_retrieve_knowledge_uses_user_text_when_knowledge_query_missing(self):
        response = Mock()
        response.status_code = 200
        response.json.return_value = {"sources": []}

        with patch.object(kb_service, "RAG_BACKEND", "api"), \
                patch.object(kb_service, "RAG_API_URL", "http://rag.internal/search"), \
                patch.object(kb_service.requests, "post", return_value=response) as post:
            docs = kb_service.retrieve_knowledge("好康三合一", {"company_code": "tdtv"}, {}, top_k=3)

        self.assertEqual(docs, [])
        self.assertEqual(post.call_args.kwargs["json"]["plan_name"], "好康三合一")
        self.assertEqual(post.call_args.kwargs["json"]["limit"], 3)

    def test_retrieve_knowledge_returns_empty_when_api_has_no_sources(self):
        response = Mock()
        response.status_code = 200
        response.json.return_value = {
            "plan_name": "不存在的方案",
            "knowledge_base": "大屯",
            "sources": [],
        }

        with patch.object(kb_service, "RAG_BACKEND", "api"), \
                patch.object(kb_service, "RAG_API_URL", "http://rag.internal/search"), \
                patch.object(kb_service.requests, "post", return_value=response):
            docs = kb_service.retrieve_knowledge("不存在的方案", {"company_code": "tdtv"}, {}, top_k=5)

        self.assertEqual(docs, [])

    def test_retrieve_knowledge_returns_empty_on_api_failures(self):
        cases = [
            requests.Timeout("timeout"),
            Mock(status_code=500, json=Mock(return_value={})),
            Mock(status_code=200, json=Mock(side_effect=ValueError("bad json"))),
        ]

        for result in cases:
            with self.subTest(result=result), \
                    patch.object(kb_service, "RAG_BACKEND", "api"), \
                    patch.object(kb_service, "RAG_API_URL", "http://rag.internal/search"), \
                    patch.object(kb_service.requests, "post", side_effect=result if isinstance(result, Exception) else None, return_value=None if isinstance(result, Exception) else result):
                docs = kb_service.retrieve_knowledge("好康三合一", {"company_code": "tdtv"}, {}, top_k=5)

            self.assertEqual(docs, [])

    def test_retrieve_knowledge_uses_local_chroma_backend(self):
        class FakeSearcher:
            def __init__(self):
                self.calls = []

            def search(self, query, top_k, knowledge_base=None, category=None):
                self.calls.append({
                    "query": query,
                    "top_k": top_k,
                    "knowledge_base": knowledge_base,
                    "category": category,
                })
                return [
                    {
                        "id": f"{knowledge_base}:doc-1:1",
                        "document_id": f"{knowledge_base}:doc-1",
                        "question": f"{knowledge_base}退租流程",
                        "answer": f"{knowledge_base}請攜帶證件與設備至門市辦理退租。",
                        "company": knowledge_base,
                        "category": "billing",
                        "source": "內部流程.txt",
                        "title": "退租流程",
                        "_score": 0.91,
                        "_distance": 0.09,
                    }
                ]

        fake = FakeSearcher()
        with patch.object(kb_service, "RAG_BACKEND", "local"), \
                patch.object(kb_service, "load_local_searcher", return_value=fake):
            docs = kb_service.retrieve_knowledge(
                "退租要帶什麼",
                {"company_code": "tdtv"},
                {"knowledge_query": "退租流程"},
                top_k=3,
            )

        self.assertEqual(
            [call["knowledge_base"] for call in fake.calls],
            ["通用-中區", "通用", "大屯"],
        )
        self.assertEqual(fake.calls[0]["query"], "退租流程")
        self.assertIsNone(fake.calls[0]["category"])
        self.assertIsNone(fake.calls[1]["category"])
        self.assertEqual(docs[0]["id"], "大屯:doc-1:1")
        self.assertEqual(docs[0]["answer"], "大屯請攜帶證件與設備至門市辦理退租。")
        self.assertEqual(docs[0]["source"]["document_id"], "大屯:doc-1")

    def test_line_tv_query_reranks_by_question_relevance_without_category_lock(self):
        class FakeSearcher:
            def __init__(self):
                self.calls = []

            def search(self, query, top_k, knowledge_base=None, category=None):
                self.calls.append({
                    "query": query,
                    "top_k": top_k,
                    "knowledge_base": knowledge_base,
                    "category": category,
                })
                if knowledge_base == "通用":
                    return [
                        {
                            "id": "common:line-tv-device",
                            "document_id": "common:line-tv",
                            "question": "LINE TV可以在幾台裝置收看？",
                            "answer": "一個帳號可同時登入多台裝置，但同時觀看限制請依 LINE TV 規則。",
                            "company": "通用",
                            "category": "network_support",
                            "source": "加值服務.csv",
                            "title": "加值服務",
                            "_score": 0.83,
                            "_distance": 0.21,
                        }
                    ]
                return [
                    {
                        "id": "datun-promo",
                        "document_id": "datun-promo-doc",
                        "question": "好視成雙NO8-1150610-1150831",
                        "answer": "方案贈 LINE TV 會員半年，另有贈品與月租優惠。",
                        "company": "大屯",
                        "category": "billing",
                        "source": "優惠活動.pdf",
                        "title": "好視成雙NO8-1150610-1150831",
                        "_score": 0.97,
                        "_distance": 0.03,
                    }
                ]

        fake = FakeSearcher()
        with patch.object(kb_service, "RAG_BACKEND", "local"), \
                patch.object(kb_service, "load_local_searcher", return_value=fake):
            docs = kb_service.retrieve_knowledge(
                "LINE TV可以在線台裝置收看？",
                {"company_code": "tdtv"},
                {"knowledge_query": "LINE TV可以在線台裝置收看？"},
                top_k=3,
            )

        self.assertEqual(
            [call["knowledge_base"] for call in fake.calls],
            ["通用-中區", "通用", "大屯"],
        )
        self.assertTrue(all(call["category"] is None for call in fake.calls))
        self.assertIn("幾台裝置", fake.calls[0]["query"])
        self.assertEqual(docs[0]["question"], "LINE TV可以在幾台裝置收看？")
        self.assertGreater(docs[0]["_query_relevance_score"], docs[1]["_query_relevance_score"])

    def test_local_chroma_prioritizes_specific_company_over_common_when_both_match(self):
        class FakeSearcher:
            def search(self, query, top_k, knowledge_base=None, category=None):
                distance = 0.05 if knowledge_base == "通用" else 0.12
                answer = "室內移機 500 元。" if knowledge_base == "通用" else "室內移機 800 元。"
                return [
                    {
                        "id": f"{knowledge_base}:move-fee",
                        "document_id": f"{knowledge_base}:doc",
                        "question": "移機費用",
                        "answer": answer,
                        "company": knowledge_base,
                        "category": "billing",
                        "source": "移機費用.csv",
                        "title": "移機費用",
                        "_score": round(1 - distance, 6),
                        "_distance": distance,
                    }
                ]

        with patch.object(kb_service, "RAG_BACKEND", "local"), \
                patch.object(kb_service, "load_local_searcher", return_value=FakeSearcher()):
            docs = kb_service.retrieve_knowledge(
                "室內移機費用",
                {"company_code": "tdtv"},
                {"knowledge_query": "室內移機費用"},
                top_k=2,
            )

        self.assertEqual([doc["company"] for doc in docs], ["大屯", "通用-中區"])
        self.assertIn("800", docs[0]["answer"])

    def test_local_chroma_prefers_specific_company_when_both_are_relevant_enough(self):
        class FakeSearcher:
            def search(self, query, top_k, knowledge_base=None, category=None):
                if knowledge_base == "通用":
                    return [
                        {
                            "id": "common-move-fee",
                            "document_id": "common-doc",
                            "question": "室內移機費用",
                            "answer": "有線電視 TV 室內移機費：500 元。",
                            "company": "通用",
                            "category": "billing",
                            "source": "通用移機費.csv",
                            "title": "室內移機費用",
                            "_score": 0.96,
                            "_distance": 0.04,
                        }
                    ]
                return [
                    {
                        "id": "datun-network-move-fee",
                        "document_id": "datun-doc",
                        "question": "大屯網路移機費",
                        "answer": "移機分室內或室外移機，移機需收費室內 800 元 室外 800 元。",
                        "company": "大屯",
                        "category": "billing",
                        "source": "大屯網路移機費.txt",
                        "title": "大屯網路移機費",
                        "_score": 0.79,
                        "_distance": 0.21,
                    }
                ]

        with patch.object(kb_service, "RAG_BACKEND", "local"), \
                patch.object(kb_service, "load_local_searcher", return_value=FakeSearcher()):
            docs = kb_service.retrieve_knowledge(
                "室內移機費用",
                {"company_code": "tdtv"},
                {"knowledge_query": "室內移機費用"},
                top_k=2,
            )

        self.assertEqual(docs[0]["company"], "大屯")
        self.assertIn("800", docs[0]["answer"])
        self.assertEqual(kb_service.query_relevance_bucket(docs[0]["_query_relevance_score"]), 2)

    def test_local_chroma_expands_and_reranks_promotion_gift_detail_queries(self):
        class FakeSearcher:
            def __init__(self):
                self.calls = []

            def search(self, query, top_k, knowledge_base=None, category=None):
                self.calls.append({
                    "query": query,
                    "top_k": top_k,
                    "knowledge_base": knowledge_base,
                    "category": category,
                })
                if knowledge_base != "大屯":
                    return []
                return [
                    {
                        "id": "promo:title",
                        "document_id": "promo-doc",
                        "question": "星耀暢網 X7",
                        "answer": "方案名稱：星耀暢網 X7 活動期間：2026/09/01~2026/12/31",
                        "company": "大屯",
                        "category": "billing",
                        "source": "dynamic-campaign.pdf",
                        "title": "星耀暢網 X7",
                        "document_type": "promotion_campaign",
                        "campaign_name": "星耀暢網 X7",
                        "campaign_aliases": "星耀暢網 X7 | 星耀暢網X7",
                        "service_types": "電視網路同裝",
                        "valid_period": "2026/09/01~2026/12/31",
                        "_score": 0.92,
                        "_distance": 0.08,
                    },
                    {
                        "id": "promo:wall-mount",
                        "document_id": "promo-doc",
                        "question": "星耀暢網 X7",
                        "answer": "家電配送及保固說明。電視無壁掛架及安裝壁架服務，若客戶有需求，由廠商另行報價。",
                        "company": "大屯",
                        "category": "billing",
                        "source": "dynamic-campaign.pdf",
                        "title": "星耀暢網 X7",
                        "document_type": "promotion_campaign",
                        "campaign_name": "星耀暢網 X7",
                        "campaign_aliases": "星耀暢網 X7 | 星耀暢網X7",
                        "service_types": "電視網路同裝",
                        "valid_period": "2026/09/01~2026/12/31",
                        "_score": 0.61,
                        "_distance": 0.39,
                    },
                ]

        fake = FakeSearcher()
        with patch.object(kb_service, "RAG_BACKEND", "local"), \
                patch.object(kb_service, "load_local_searcher", return_value=fake), \
                patch.object(kb_service, "retrieve_knowledge_from_keyword_fallback", return_value=[]):
            docs = kb_service.retrieve_knowledge(
                "星耀暢網 X7 贈品 電視機 壁掛 服務",
                {"company_code": "tdtv"},
                {"knowledge_query": "星耀暢網 X7 贈品 電視機 壁掛 服務"},
                top_k=3,
            )

        self.assertGreaterEqual(fake.calls[0]["top_k"], 50)
        self.assertEqual(docs[0]["id"], "promo:wall-mount")
        self.assertIn("壁掛架", docs[0]["answer"])

    def test_local_chroma_expands_and_reranks_discount_eligibility_queries(self):
        class FakeSearcher:
            def __init__(self):
                self.calls = []

            def search(self, query, top_k, knowledge_base=None, category=None):
                self.calls.append({
                    "query": query,
                    "top_k": top_k,
                    "knowledge_base": knowledge_base,
                    "category": category,
                })
                if knowledge_base != "大屯":
                    return []
                return [
                    {
                        "id": "generic-discount",
                        "document_id": "discount-doc",
                        "question": "一般優惠",
                        "answer": "優惠方案需由客服確認。",
                        "company": "大屯",
                        "category": "billing",
                        "source": "優惠.docx",
                        "title": "一般優惠",
                        "_score": 0.9,
                        "_distance": 0.1,
                    },
                    {
                        "id": "low-income-discount",
                        "document_id": "discount-doc",
                        "question": "低收入、身心障礙優惠報價AI版",
                        "answer": "【方案名稱】 低收入戶優惠方案\n【優惠內容】 裝機費優惠後收費金額：0元。電視收視服務費優惠期間：12個月，優惠後收費金額：0元／年。\n【申請條件】 須提供有效期限內之低收入戶證明文件。",
                        "company": "大屯",
                        "category": "billing",
                        "source": "低收入.docx",
                        "title": "低收入、身心障礙優惠報價AI版",
                        "_score": 0.63,
                        "_distance": 0.37,
                    },
                ]

        fake = FakeSearcher()
        with patch.object(kb_service, "RAG_BACKEND", "local"), \
                patch.object(kb_service, "load_local_searcher", return_value=fake), \
                patch.object(kb_service, "retrieve_knowledge_from_keyword_fallback", return_value=[]):
            docs = kb_service.retrieve_knowledge(
                "低收入優惠方案",
                {"company_code": "tdtv"},
                {"knowledge_query": "低收入優惠方案"},
                top_k=3,
            )

        self.assertGreaterEqual(fake.calls[0]["top_k"], 50)
        self.assertEqual(docs[0]["id"], "low-income-discount")
        self.assertIn("0元／年", docs[0]["answer"])

    def test_generic_promotion_query_suppresses_social_discount_docs(self):
        class FakeSearcher:
            def search(self, query, top_k, knowledge_base=None, category=None):
                if knowledge_base != "大屯":
                    return []
                return [
                    {
                        "id": "low-income-discount",
                        "document_id": "social-doc",
                        "question": "低收入、身心障礙優惠報價AI版",
                        "answer": "【方案名稱】 低收入戶優惠方案\n【優惠內容】 收視服務費 0 元。",
                        "company": "大屯",
                        "category": "billing",
                        "source": "低收入.docx",
                        "title": "低收入、身心障礙優惠報價AI版",
                        "_score": 0.99,
                        "_distance": 0.01,
                    },
                    {
                        "id": "campaign-discount",
                        "document_id": "campaign-doc",
                        "question": "好視成雙 NO8",
                        "answer": "方案一、500M/500M 綁約36個月，贈 LINE TV 會員半年與家電二擇一。",
                        "company": "大屯",
                        "category": "billing",
                        "source": "好視成雙NO8.pdf",
                        "title": "好視成雙 NO8",
                        "_score": 0.72,
                        "_distance": 0.28,
                    },
                ]

        with patch.object(kb_service, "RAG_BACKEND", "local"), \
                patch.object(kb_service, "load_local_searcher", return_value=FakeSearcher()), \
                patch.object(kb_service, "retrieve_knowledge_from_keyword_fallback", return_value=[]):
            docs = kb_service.retrieve_knowledge(
                "有推薦的優惠方案嗎?",
                {"company_code": "tdtv"},
                {"knowledge_query": "優惠方案 有推薦的優惠方案嗎?"},
                top_k=3,
            )

        self.assertEqual([doc["id"] for doc in docs], ["campaign-discount"])

    def test_explicit_pure_tv_scope_keeps_only_basic_rate_cards(self):
        basic_rate_card = {
            "id": "basic-tv",
            "question": "大屯_有線電視_基本收費標準11507",
            "answer": "有線電視基本收視費：月繳550元；裝機費1,500元。",
        }
        combo_campaign = {
            "id": "combo",
            "question": "好視成雙NO7",
            "answer": "有線電視加網路同裝優惠，月繳990元。",
            "document_type": "promotion_campaign",
        }
        adjacent_faq = {
            "id": "faq",
            "question": "要如何暫停第四台或有線電視呢？",
            "answer": "暫停收視未逾三個月可申請復機。",
        }

        docs = kb_service.filter_docs_for_query_intent(
            "純有線電視 單辦有線電視 基本收費標準 月繳 裝機費",
            [combo_campaign, adjacent_faq, basic_rate_card],
        )

        self.assertEqual([doc["id"] for doc in docs], ["basic-tv"])

    def test_combo_scope_suppresses_social_discount_campaign(self):
        social_combo = {
            "id": "social-combo",
            "question": "低收入戶好視成雙優惠",
            "answer": "低收入戶有線電視加網路優惠。",
            "document_type": "promotion_campaign",
        }
        general_combo = {
            "id": "general-combo",
            "question": "好視成雙NO7",
            "answer": "有線電視加網路同裝優惠。",
            "document_type": "promotion_campaign",
        }

        docs = kb_service.filter_docs_for_query_intent(
            "有線電視加網路優惠",
            [social_combo, general_combo],
        )

        self.assertEqual([doc["id"] for doc in docs], ["general-combo"])

    def test_generic_promotion_query_prefers_campaign_activity_over_generic_faq(self):
        class FakeSearcher:
            def __init__(self):
                self.calls = []

            def search(self, query, top_k, knowledge_base=None, category=None):
                self.calls.append({
                    "query": query,
                    "top_k": top_k,
                    "knowledge_base": knowledge_base,
                    "category": category,
                })
                if knowledge_base != "大屯":
                    return []
                return [
                    {
                        "id": "generic-triple-play",
                        "document_id": "generic-doc",
                        "question": "三合一方案",
                        "answer": "三合一方案通常是指數位電視、寬頻上網以及加值頻道套餐。如果您需要更詳細的資訊請洽客服。",
                        "company": "大屯",
                        "category": "billing",
                        "source": "常見問題.csv",
                        "title": "三合一方案",
                        "_score": 0.97,
                        "_distance": 0.03,
                    },
                    {
                        "id": "b2606-campaign",
                        "document_id": "campaign-doc",
                        "question": "飆網守護家_B2606",
                        "answer": "方案名稱：飆網守護家_(B2606) 網路贈清冰組方案\n活動期間：2026/06/05~2026/9/30\n裝機費：免裝機費。綁約期間 24 個月。售價：100M/10M 季繳 1197 元、半年繳 2394 元、年繳 4788 元。",
                        "company": "大屯",
                        "category": "network_support",
                        "source": "飆網守護家_B2606.pdf",
                        "title": "飆網守護家_B2606",
                        "_score": 0.62,
                        "_distance": 0.38,
                    },
                    {
                        "id": "low-income-discount",
                        "document_id": "social-doc",
                        "question": "低收入戶優惠方案",
                        "answer": "【方案名稱】 低收入戶優惠方案\n【優惠內容】 收視服務費 0 元。",
                        "company": "大屯",
                        "category": "billing",
                        "source": "低收入.docx",
                        "title": "低收入、身心障礙優惠報價AI版",
                        "_score": 0.99,
                        "_distance": 0.01,
                    },
                ]

        fake = FakeSearcher()
        with patch.object(kb_service, "RAG_BACKEND", "local"), \
                patch.object(kb_service, "load_local_searcher", return_value=fake), \
                patch.object(kb_service, "retrieve_knowledge_from_keyword_fallback", return_value=[]):
            docs = kb_service.retrieve_knowledge(
                "有推薦的優惠方案嗎?",
                {"company_code": "tdtv"},
                {"knowledge_query": "有推薦的優惠方案嗎?"},
                top_k=3,
            )

        self.assertGreaterEqual(fake.calls[0]["top_k"], 60)
        self.assertEqual([doc["id"] for doc in docs], ["b2606-campaign"])
        self.assertIn("2026/06/05", docs[0]["answer"])

    def test_basic_tv_fee_query_filters_out_combo_campaign_docs(self):
        docs = [
            {
                "id": "basic-fee",
                "question": "大屯_TV_基本收費標準11506",
                "answer": "TV 收視費：半年繳 $3,280。TV 分機費 (裝機時順裝) $500。STB 設備押金第 1、2 台免押金。",
                "source": {"title": "大屯_TV_基本收費標準11506"},
            },
            {
                "id": "combo-campaign",
                "question": "好視成雙 NO8",
                "answer": "方案名稱：好視成雙 NO8。電視+網路同裝方案，500M/500M 半年繳 $5,994。",
                "source": {"title": "好視成雙 NO8"},
            },
        ]

        filtered = kb_service.filter_docs_for_query_intent(
            "大屯 TV 基本收費標準 純 TV 有線電視 半年繳 裝機費 TV 分機費 STB 合計",
            docs,
        )

        self.assertEqual([doc["id"] for doc in filtered], ["basic-fee"])

    def test_short_basic_tv_monthly_fee_query_prefers_rate_card_over_campaign(self):
        docs = [
            {
                "id": "basic-fee",
                "question": "大屯有線電視基本收費標準",
                "answer": "有線電視收視費（月費）：月繳 $550。",
                "source": {"title": "大屯_有線電視_基本收費標準11507"},
            },
            {
                "id": "combo-campaign",
                "question": "好視成雙 NO8",
                "answer": "電視與網路同裝優惠，月繳 899 元，另有贈品。",
                "source": {"title": "好視成雙 NO8"},
            },
        ]

        filtered = kb_service.filter_docs_for_query_intent(
            "大屯第四台一個月多少？",
            docs,
        )

        self.assertEqual([doc["id"] for doc in filtered], ["basic-fee"])

    def test_basic_tv_fee_query_does_not_accept_unrelated_non_campaign_docs(self):
        docs = [
            {
                "id": "unrelated",
                "question": "遙控器操作說明",
                "answer": "請先確認遙控器電池是否有電。",
                "source": {"title": "電視操作說明"},
            },
            {
                "id": "campaign",
                "question": "好視成雙 NO8",
                "answer": "電視與網路同裝優惠，500M/500M 月繳 999 元。",
                "source": {"title": "好視成雙 NO8"},
            },
        ]

        filtered = kb_service.filter_docs_for_query_intent(
            "大屯第四台一個月多少？",
            docs,
        )

        self.assertEqual(filtered, [])

    def test_tv_network_combo_query_filters_out_standalone_broadband_campaign(self):
        docs = [
            {
                "id": "b2606",
                "question": "飆網守護家 B2606",
                "answer": "單辦網路方案，500M/500M 年繳 $8,388。",
                "source": {"title": "飆網守護家 B2606"},
            },
            {
                "id": "no8",
                "question": "好視成雙 NO8",
                "answer": "電視+網路同裝方案，500M/500M 月繳 $999。",
                "source": {"title": "好視成雙 NO8 電視+網路同裝方案"},
            },
        ]

        filtered = kb_service.filter_docs_for_query_intent(
            "有第四台加網路的優惠方案嗎？ 好視成雙 電視網路同裝",
            docs,
        )

        self.assertEqual([doc["id"] for doc in filtered], ["no8"])
        self.assertGreater(
            kb_service.score_query_relevance("第四台加網路優惠", docs[1]),
            kb_service.score_query_relevance("第四台加網路優惠", docs[0]),
        )

    def test_single_network_query_filters_out_tv_network_campaign(self):
        docs = [
            {
                "id": "pure-a",
                "campaign_name": "測試純網方案 A",
                "service_types": "寬頻",
                "answer": "純網方案，500M/500M 年繳 $8,388。",
            },
            {
                "id": "pure-b",
                "campaign_name": "測試純網方案 B",
                "service_types": "寬頻 | 加值服務",
                "answer": "單辦網路方案，300M/300M 年繳 $7,188。",
            },
            {
                "id": "combo",
                "campaign_name": "測試電視網路方案",
                "service_types": "電視網路同裝",
                "answer": "好視成雙，電視+網路同裝方案。",
            },
            {
                "id": "social",
                "campaign_name": "低收入戶方案",
                "service_types": "寬頻 | 有線電視",
                "answer": "限持有效低收入戶證明的客戶申請。",
            },
        ]

        filtered = kb_service.filter_docs_for_query_intent(
            "請問有單一網路的嗎？",
            docs,
        )
        finalized = kb_service.finalize_docs_for_query(
            "請問有單一網路的嗎？",
            docs,
            top_k=5,
        )

        self.assertEqual([doc["id"] for doc in filtered], ["pure-a", "pure-b"])
        self.assertEqual([doc["id"] for doc in finalized], ["pure-a", "pure-b"])

    def test_multi_set_top_box_fee_query_filters_out_combo_campaign_docs(self):
        docs = [
            {
                "id": "basic-fee",
                "question": "大屯_TV_基本收費標準11506",
                "answer": (
                    "1、2 台機上盒：一般戶免費借用，免押金。"
                    "第 3 台起：每台需收 STB 設備押金 $1,200。"
                    "分機施工費：裝機時順裝 $500；後續加裝 $800。"
                    "第 6 台含以上：需加購 $100 元以上套餐。"
                ),
                "source": {"title": "大屯_TV_基本收費標準11506"},
            },
            {
                "id": "combo-campaign",
                "question": "好視成雙 NO8",
                "answer": "方案名稱：好視成雙 NO8。電視+網路同裝方案，500M/500M 半年繳 $5,994。",
                "source": {"title": "好視成雙 NO8"},
            },
        ]

        filtered = kb_service.filter_docs_for_query_intent(
            "機上盒有多台要申裝 費用怎麼算?",
            docs,
        )

        self.assertEqual([doc["id"] for doc in filtered], ["basic-fee"])

    def test_third_set_top_box_fee_prefers_exact_source_evidence(self):
        docs = [
            {
                "id": "combo-campaign",
                "question": "好視成雙 NO8",
                "answer": "電視與網路同裝優惠，設備押金依方案規定。",
            },
            {
                "id": "third-box-fee",
                "question": "大屯有線電視基本收費標準",
                "answer": "多台機上盒依基本收費標準辦理。",
                "source": {
                    "content": "第3、4、5台一律收押金$1,200元/台、收分機費$800元/台，客戶若已有線路可免收分機費。"
                },
            },
        ]

        filtered = kb_service.filter_docs_for_query_intent(
            "第三台機上盒要收哪些費用？",
            docs,
        )

        self.assertEqual([doc["id"] for doc in filtered], ["third-box-fee"])
        self.assertGreater(
            kb_service.score_query_facet_evidence("第三台機上盒要收哪些費用？", docs[1]),
            kb_service.score_query_facet_evidence("第三台機上盒要收哪些費用？", docs[0]),
        )

    def test_remote_control_purchase_price_prefers_price_over_troubleshooting(self):
        docs = [
            {
                "id": "remote-troubleshooting",
                "question": "遙控器沒有反應",
                "answer": "請先更換電池並確認紅外線是否正常。",
            },
            {
                "id": "remote-price",
                "question": "遙控器購買價格",
                "answer": "一般遙控器售價300元/支，語音遙控器售價400元/支。",
            },
        ]

        filtered = kb_service.filter_docs_for_query_intent(
            "一般遙控器壞了，買一支多少錢？",
            docs,
        )

        self.assertEqual([doc["id"] for doc in filtered], ["remote-price"])

    def test_reward_points_usage_prefers_redemption_rules_over_gift_campaign(self):
        docs = [
            {
                "id": "gift-points",
                "question": "POINT贈點活動",
                "answer": "半年繳贈888點，年繳贈1288點。",
            },
            {
                "id": "points-usage",
                "question": "台數科紅利點數哈Point說明",
                "answer": "哈Point可購買加值商品或折抵連線、收視服務費用；1點等於1元，不可兌換現金。",
            },
        ]

        filtered = kb_service.filter_docs_for_query_intent(
            "你們的紅利點數可以做什麼？",
            docs,
        )

        self.assertEqual([doc["id"] for doc in filtered], ["points-usage"])

    def test_reward_points_overview_ranks_general_explanation_above_campaign_gifts(self):
        docs = [
            {
                "id": "campaign-gift-points",
                "question": "爸氣獻禮 POINT 贈點規則",
                "answer": "季繳贈588點、半年繳贈888點、年繳贈1288點。",
                "document_type": "promotion_campaign",
                "record_type": "campaign_variant",
            },
            {
                "id": "points-overview",
                "question": "台數科紅利點數哈Point說明",
                "answer": (
                    "台數科設有紅利點數哈Point優惠積點回饋機制，"
                    "點數可用於購買台數科商品或抵扣各項服務費用。"
                ),
                "document_type": "product_service_catalog",
                "record_type": "product_service",
            },
        ]

        selected = kb_service.finalize_docs_for_query(
            "紅利點數 台數科紅利點數哈Point說明 優惠積點回饋機制 如何獲得 有效期限",
            docs,
            top_k=2,
        )

        self.assertEqual(selected[0]["id"], "points-overview")
        self.assertGreater(
            kb_service.score_query_facet_evidence("紅利點數", docs[1]),
            kb_service.score_query_facet_evidence("紅利點數", docs[0]),
        )

    def test_line_tv_device_limit_prefers_login_rule_over_channel_content(self):
        docs = [
            {
                "id": "line-tv-channel",
                "question": "LINE TV頻道內容",
                "answer": "提供戲劇與綜藝等影音內容。",
            },
            {
                "id": "line-tv-device-limit",
                "question": "LINE TV登入裝置限制",
                "answer": "LINE TV登入裝置數量無上限，實際同時觀看限制依服務公告為準。",
            },
        ]

        filtered = kb_service.filter_docs_for_query_intent(
            "LINE TV最多能登入幾台裝置？",
            docs,
        )

        self.assertEqual([doc["id"] for doc in filtered], ["line-tv-device-limit"])

    def test_line_tv_device_limit_faq_outranks_generated_product_profile(self):
        docs = [
            {
                "id": "line-tv-profile",
                "question": "LINE TV",
                "answer": "LINE TV 原價210元/月，特價600元/半年。",
                "record_type": "product_service",
                "document_type": "product_service_catalog",
                "product_name": "LINE TV",
                "product_aliases": "LINE TV | LINETV | LITV",
            },
            {
                "id": "line-tv-device-faq",
                "question": "LINE TV可以在幾台裝置收看？",
                "answer": "同一帳號可登入多台裝置，同時觀看限制依服務公告為準。",
            },
        ]

        filtered = kb_service.filter_docs_for_query_intent(
            "LINE TV同一個帳號可以幾台一起看？",
            docs,
        )

        self.assertEqual([doc["id"] for doc in filtered], ["line-tv-device-faq"])

    def test_line_tv_cancellation_faq_outranks_generated_product_profile(self):
        docs = [
            {
                "id": "line-tv-profile",
                "question": "LINE TV",
                "answer": "LINE TV 原價210元/月，特價600元/半年。",
                "record_type": "product_service",
                "document_type": "product_service_catalog",
                "product_name": "LINE TV",
                "product_aliases": "LINE TV | LINETV | LITV",
            },
            {
                "id": "line-tv-cancel-faq",
                "question": "如何取消LINE TV",
                "answer": "LINE TV到期後如不續用，可依公告方式取消。",
            },
        ]

        filtered = kb_service.filter_docs_for_query_intent(
            "我不想續用 LINE TV，要怎麼取消？",
            docs,
        )

        self.assertEqual([doc["id"] for doc in filtered], ["line-tv-cancel-faq"])

    def test_senior_service_query_prefers_bear_care_faq_over_catalog(self):
        docs = [
            {
                "id": "value-added-catalog",
                "question": "各項單品銷售／加值服務",
                "answer": "LINE TV、WiFi、居家智慧攝影機與熊搭心等加值服務。",
            },
            {
                "id": "bear-care-faq",
                "question": "台數科能提供給年長者的服務有哪些",
                "answer": "熊搭心包含電視電話、家庭相簿與生活提醒。",
            },
        ]

        filtered = kb_service.filter_docs_for_query_intent(
            "家裡長輩有適合的加值服務嗎？",
            docs,
        )

        self.assertEqual([doc["id"] for doc in filtered], ["bear-care-faq"])

    def test_channel_number_question_is_specific_interrogative(self):
        self.assertTrue(
            kb_service.is_specific_interrogative_query("世足轉播頻道是幾號？")
        )

    def test_internet_time_control_facet_detects_parental_schedule_request(self):
        query = "我想讓小孩晚上十點後不能上網"

        self.assertIn("internet_time_control", kb_service.detect_query_facets(query))
        self.assertIn("上網時間管理", kb_service.build_keyword_terms(query))

    def test_internet_time_control_prefers_schedule_management_doc(self):
        query = "我想讓小孩晚上十點後不能上網"
        generic = {
            "id": "generic-network",
            "question": "網路不能上網",
            "answer": "請重新啟動數據機。",
        }
        schedule = {
            "id": "schedule-control",
            "question": "上網時間管理如何設定",
            "answer": "可設定特定時段禁止上網。",
        }

        self.assertGreater(
            kb_service.score_query_facet_evidence(query, schedule),
            kb_service.score_query_facet_evidence(query, generic),
        )

    def test_set_top_box_power_saving_prefers_setting_faq_over_sd22_camera_doc(self):
        query = "SD22可以不要睡眠嗎"
        camera = {
            "id": "sd22-camera",
            "question": "哈TV 使用視訊鏡頭型號有什麼建議",
            "answer": "哈TV+ SD22 機上盒可使用台數科 M1 鏡頭、羅技 C310。",
        }
        power_saving = {
            "id": "sd22-power-saving",
            "question": "如何關閉 SD-22 節能模式",
            "answer": "右上角齒輪 → 高級設定 → 裝置偏好設定 → 節約耗電量 → 關閉螢幕功能，設定為永不。",
        }

        self.assertIn("set_top_box_power_saving", kb_service.detect_query_facets(query))
        filtered = kb_service.filter_docs_for_query_intent(query, [camera, power_saving])

        self.assertEqual([doc["id"] for doc in filtered], ["sd22-power-saving"])

    def test_cancellation_requirements_prefer_documents_and_equipment_row(self):
        query = "有線電視要退租需要帶什麼證件？"
        docs = [
            {
                "id": "basic-fee",
                "question": "有線電視基本收費",
                "answer": "有線電視月租依基本收費標準辦理。",
            },
            {
                "id": "cancellation-requirements",
                "question": "有線電視如何辦理退租？",
                "answer": "請攜帶身分證明、印章、設備及所有配件至服務櫃檯辦理。",
            },
        ]

        self.assertIn(
            "service_cancellation_requirements",
            kb_service.detect_query_facets(query),
        )
        filtered = kb_service.filter_docs_for_query_intent(query, docs)
        self.assertEqual([doc["id"] for doc in filtered], ["cancellation-requirements"])

    def test_service_suspension_query_expands_to_pause_document_terms(self):
        terms = kb_service.build_keyword_terms("如何申請停機")

        self.assertIn("停機", terms)
        self.assertIn("暫停機", terms)
        self.assertIn("雙證件", terms)
        self.assertTrue(kb_service.should_merge_keyword_fallback("如何申請停機"))

    def test_service_suspension_query_prefers_pause_document_over_generic_apply_rows(self):
        with tempfile.TemporaryDirectory() as tmp:
            csv_path = Path(tmp) / "機上盒.csv"
            csv_path.write_text(
                "question,answer,company\n"
                "如何申請固定IP,需跟真人客服聯繫並核對基本個資。\n"
                "要如何暫停第四台或有線電視呢?,申請暫停機需保留1個月以上月租，"
                "如需辦理需持登記者雙證件印章臨櫃辦理，"
                "代辦人請攜帶登記者及代辦者雙證件印章。\n",
                encoding="utf-8",
            )
            records = [{
                "id": "set-top-box-doc",
                "title": "機上盒",
                "file_name": "機上盒.csv",
                "knowledge_base": "通用-中區",
                "category": "billing",
                "_resolved_file_path": csv_path,
            }]

            with patch.object(kb_service, "read_active_kb_document_records", return_value=records):
                docs = kb_service.retrieve_knowledge_from_keyword_fallback(
                    "如何申請停機",
                    {"company_code": "tdtv", "knowledge_base": "大屯", "company": "大屯"},
                    top_k=3,
                )

        self.assertTrue(docs)
        self.assertEqual(docs[0]["question"], "要如何暫停第四台或有線電視呢?")
        self.assertIn("雙證件", docs[0]["answer"])

    def test_credit_card_payment_prefers_online_payment_steps_over_fee_table(self):
        query = "我想用信用卡繳第四台費用"
        docs = [
            {
                "id": "basic-fee",
                "question": "第四台費用",
                "answer": "有線電視月繳550元。",
            },
            {
                "id": "credit-card-payment",
                "question": "信用卡要怎麼線上繳？",
                "answer": "至官方網站線上繳費專區，輸入用戶編號與密碼後依指示刷卡繳費。",
            },
        ]

        self.assertIn(
            "credit_card_payment_method",
            kb_service.detect_query_facets(query),
        )
        filtered = kb_service.filter_docs_for_query_intent(query, docs)
        self.assertEqual([doc["id"] for doc in filtered], ["credit-card-payment"])

    def test_payment_method_guidance_filters_out_installation_fee_table(self):
        query = "繳款方式查詢"
        docs = [
            {
                "id": "fee-table",
                "question": "有線電視基本收費標準",
                "answer": "裝機費 1,500 元，月繳收視費 550 元。",
            },
            {
                "id": "payment-methods",
                "question": "帳單未收到如何繳費",
                "answer": "可使用官網線上繳費、行動客服 APP、臨櫃、超商帳單條碼、ibon 或 FamiPort。",
            },
        ]

        self.assertIn("payment_method_guidance", kb_service.detect_query_facets(query))
        filtered = kb_service.filter_docs_for_query_intent(query, docs)
        self.assertEqual([doc["id"] for doc in filtered], ["payment-methods"])

    def test_payment_method_guidance_keeps_payment_overview_ahead_of_ibon_tutorial(self):
        query = "繳費方式"
        docs = [
            {
                "id": "ibon-tutorial",
                "question": "IBON",
                "answer": "前往 7-Eleven 的 ibon 機台，依畫面操作繳費。",
            },
            {
                "id": "payment-overview",
                "question": "查詢繳費方式",
                "answer": "可透過官網、行動客服 APP、臨櫃、超商帳單條碼、ibon 或 FamiPort 繳費。",
            },
        ]

        filtered = kb_service.filter_docs_for_query_intent(query, docs)
        self.assertEqual([doc["id"] for doc in filtered], ["payment-overview"])

    def test_online_payment_prefers_official_payment_portal_over_ibon_steps(self):
        query = "線上繳費"
        docs = [
            {
                "id": "ibon-steps",
                "question": "IBON",
                "answer": "前往 7-Eleven 的 ibon 機台，選擇繳費、輸入電話、列印繳費單後至櫃台繳費。",
            },
            {
                "id": "online-payment",
                "question": "線上繳費",
                "answer": "前往官方網站的線上繳費專區，輸入您的用戶編號和密碼，依指示完成繳費。",
            },
        ]

        self.assertIn("online_payment_guidance", kb_service.detect_query_facets(query))
        filtered = kb_service.filter_docs_for_query_intent(query, docs)
        self.assertEqual([doc["id"] for doc in filtered], ["online-payment"])

    def test_hatv_addon_query_filters_out_basic_tv_fee_docs(self):
        docs = [
            {
                "id": "basic-fee",
                "question": "大屯_TV_基本收費標準11506",
                "answer": "一般戶第 1、2 台機上盒免費借用。第 6 台含以上機上盒需加購冠軍套餐或其他 $100 元以上套餐。",
                "source": {"title": "大屯_TV_基本收費標準11506"},
            },
            {
                "id": "hatv-addon",
                "question": "哈tv數位套餐加購",
                "answer": "您可以透過官方網站了解詳細頻道內容和收費標準。如府上已有台數科聯網機上盒，可透過機上盒 VIP會員→優惠專區→數位電視購買。",
                "source": {"title": "哈tv數位套餐加購", "source": "加值服務.csv"},
            },
        ]

        filtered = kb_service.filter_docs_for_query_intent(
            "哈TV 數位套餐 加購 費用 內容 申請方式 哈tv數位套餐加購",
            docs,
        )

        self.assertEqual([doc["id"] for doc in filtered], ["hatv-addon"])

    def test_value_added_package_query_prefers_single_item_catalog_over_campaigns(self):
        docs = [
            {
                "id": "campaign-no8",
                "question": "好視成雙NO8",
                "answer": "方案名稱：好視成雙NO8。【優惠內容】LITV 首期贈送半年，WIFI 或居家智慧攝影機二擇一借用。",
                "source": {"title": "好視成雙NO8", "source": "好視成雙NO8.docx"},
            },
            {
                "id": "single-item-tv",
                "question": "各項單品銷售(數位電視)",
                "answer": "各項單品銷售/加值服務-數位電視套餐。博斯套餐：$0。HBO加價購：$39。冠軍套餐：$100。Hi Play全餐：$120。",
                "source": {"title": "各項單品銷售(數位電視)", "source": "各項單品銷售_數位電視_.docx"},
            },
        ]

        filtered = kb_service.filter_docs_for_query_intent("加值套餐有哪些呢?", docs)

        self.assertEqual([doc["id"] for doc in filtered], ["single-item-tv"])

    def test_digital_tv_package_purchase_keeps_path_and_price_evidence(self):
        query = "Hi Play全餐 數位電視套餐 加購流程 申請方式"
        docs = [
            {
                "id": "price",
                "answer": "數位電視套餐月繳：Hi Play全餐 $120。",
            },
            {
                "id": "path",
                "answer": "已有聯網機上盒時，使用遙控器進入VIP會員→優惠專區→數位電視，再選擇套餐購買。",
            },
            {
                "id": "set-top-box-path",
                "answer": "聯網機上盒可自行加購；非聯網機上盒無法自行加購，請洽客服辦理。",
            },
            {
                "id": "unrelated",
                "answer": "LINE TV 可在手機上觀看。",
            },
        ]

        selected = kb_service.finalize_docs_for_query(query, docs, top_k=2)

        self.assertTrue(kb_service.is_digital_tv_package_purchase_query(query))
        self.assertEqual([doc["id"] for doc in selected], ["path", "price"])
        self.assertTrue(kb_service.is_digital_tv_package_purchase_path_doc(docs[2]))

    def test_digital_tv_package_path_excludes_other_add_on_navigation(self):
        line_tv_path = {
            "question": "購買LINE TV",
            "answer": "透過聯網機上盒進入VIP會員→優惠專區→加值服務→LINE TV。",
        }

        self.assertTrue(kb_service.is_digital_tv_package_purchase_path_doc(line_tv_path))
        self.assertFalse(kb_service.is_digital_tv_package_specific_path_doc(line_tv_path))

    def test_digital_tv_package_price_is_not_treated_as_purchase_path(self):
        price = {
            "question": "各項單品銷售(數位電視)",
            "answer": "數位電視套餐費用說明，Hi Play全餐 $120，客戶如加購次期和電視一起寄送帳單。",
        }

        self.assertFalse(kb_service.is_digital_tv_package_purchase_path_doc(price))
        self.assertTrue(kb_service.is_digital_tv_package_price_doc(price))

    def test_digital_tv_package_purchase_keeps_common_process_outside_campaign_alias(self):
        query = "Hi Play全餐 數位電視套餐 加購流程"
        docs = [
            {"id": "price", "answer": "Hi Play全餐 $120。"},
            {"id": "path", "answer": "聯網機上盒可自行加購；非聯網機上盒請洽客服辦理。"},
        ]

        with patch.object(kb_service, "match_active_campaign_alias") as match_alias:
            selected = kb_service.filter_docs_for_active_campaign_alias(
                query,
                {"company_code": "tdtv"},
                docs,
            )

        self.assertEqual(selected, docs)
        match_alias.assert_not_called()

    def test_digital_tv_package_purchase_keeps_common_path_before_restricted_filter(self):
        query = "Hi Play全餐 數位電視套餐 加購流程"
        price = {"id": "price", "answer": "Hi Play全餐 $120。"}
        path = {
            "id": "path",
            "question": "數位套餐加購/數位電視加購",
            "answer": "聯網機上盒可自行加購；非聯網機上盒請洽客服辦理。",
        }

        filtered = kb_service.filter_docs_for_query_intent(query, [price, path])

        self.assertEqual([doc["id"] for doc in filtered], ["price", "path"])

    def test_digital_tv_package_purchase_prefers_generic_addon_path_over_other_packages(self):
        query = "Hi Play全餐 數位電視套餐 加購流程"
        generic_path = {
            "id": "generic-path",
            "question": "數位套餐加購/數位電視加購",
            "answer": "聯網機上盒可自行加購；非聯網機上盒請洽客服辦理。",
        }
        other_package_path = {
            "id": "other-path",
            "question": "什麼是松視套餐",
            "answer": "透過聯網機上盒進入VIP會員→優惠專區→數位電視購買。",
        }
        price = {"id": "price", "answer": "Hi Play全餐 $120。"}

        selected = kb_service.select_digital_tv_package_purchase_docs(
            [other_package_path, price, generic_path],
            top_k=2,
        )

        self.assertEqual([doc["id"] for doc in selected], ["generic-path", "price"])

    def test_digital_tv_package_purchase_supplements_missing_path_evidence(self):
        query = "Hi Play全餐 數位電視套餐 加購流程"
        price = {
            "id": "price",
            "answer": "數位電視套餐月繳：Hi Play全餐 $120。",
        }
        path = {
            "id": "path",
            "question": "數位套餐加購/數位電視加購",
            "answer": "聯網機上盒可自行加購；非聯網機上盒無法自行加購，請洽客服辦理。",
        }

        with patch.object(
            kb_service,
            "retrieve_knowledge_from_keyword_fallback",
            return_value=[path],
        ) as retrieve_path:
            supplemented = kb_service.supplement_digital_tv_package_purchase_path_docs(
                query,
                [price],
                {"company_code": "tdtv"},
                ["大屯", "通用-中區"],
            )

        self.assertEqual(retrieve_path.call_args.args[0], "數位套餐加購 機上盒")
        selected = kb_service.finalize_docs_for_query(query, supplemented, top_k=2)
        self.assertEqual([doc["id"] for doc in selected], ["path", "price"])

    def test_camera_rental_query_prefers_standalone_product_over_campaign_benefit(self):
        docs = [
            {
                "id": "campaign-no8",
                "question": "好視成雙NO8",
                "answer": "WIFI 或居家智慧攝影機二擇一借用。",
                "document_type": "promotion_campaign",
                "campaign_name": "好視成雙NO8",
            },
            {
                "id": "camera-product",
                "question": "居家智慧攝影機 攝影機租借",
                "answer": "借用智慧鏡頭一顆，需綁約2年。特價$300元/半年、$600元/1年。",
                "record_type": "product_service",
                "document_type": "product_service_catalog",
                "product_name": "居家智慧攝影機",
                "product_aliases": "居家智慧攝影機 | 攝影機 | 租借攝影機",
            },
        ]

        filtered = kb_service.filter_docs_for_query_intent(
            "我貴公司有租借攝影機服務嗎？",
            docs,
        )

        self.assertEqual([doc["id"] for doc in filtered], ["camera-product"])

    def test_each_value_added_product_query_selects_its_derived_record(self):
        docs = [
            {
                "id": "line-tv",
                "answer": "LINE TV 特價$600元/半年。",
                "record_type": "product_service",
                "document_type": "product_service_catalog",
                "product_name": "LINE TV",
                "product_aliases": "LINE TV | LINETV | LITV",
            },
            {
                "id": "wifi-6",
                "answer": "WiFi 6 系列分享器年繳$600元。",
                "record_type": "product_service",
                "document_type": "product_service_catalog",
                "product_name": "WiFi 6 系列分享器",
                "product_aliases": "WiFi 6 | WIFI6 | 分享器",
                "product_parent": "WiFi 加值服務",
            },
            {
                "id": "marpa-friend",
                "answer": "瑪帛好友年繳$828元。",
                "record_type": "product_service",
                "document_type": "product_service_catalog",
                "product_name": "瑪帛好友",
                "product_aliases": "瑪帛好友 | 瑪帛",
                "product_parent": "熊搭心",
            },
        ]

        cases = {
            "LINE TV半年多少錢？": "line-tv",
            "WiFi 6分享器怎麼收費？": "wifi-6",
            "瑪帛好友一年多少錢？": "marpa-friend",
        }
        for query, expected_id in cases.items():
            with self.subTest(query=query):
                filtered = kb_service.filter_docs_for_query_intent(query, docs)
                self.assertEqual([doc["id"] for doc in filtered], [expected_id])

    def test_named_value_added_product_wins_before_generic_fee_facets(self):
        docs = [
            {
                "id": "generic-bear-care-faq",
                "question": "什麼是熊搭心",
                "answer": "熊搭心包含電視電話、家庭相簿與生活提醒服務。",
            },
            {
                "id": "unrelated-annual-plan",
                "question": "一般寬頻年繳費用",
                "answer": "月繳、半年繳及年繳方案，年繳費用 12,000 元。",
                "record_type": "plan",
            },
            {
                "id": "bear-care",
                "question": "熊搭心費用方案",
                "answer": "瑪帛好友年繳 828 元；瑪帛夥伴年繳 1,188 元。",
                "record_type": "product_service",
                "document_type": "product_service_catalog",
                "product_name": "熊搭心",
                "product_aliases": "熊搭心 | 熊大心 | 熊溫馨",
            },
        ]

        filtered = kb_service.filter_docs_for_query_intent(
            "熊搭心 年繳 一年 年費 費用 價格",
            docs,
        )

        self.assertEqual([doc["id"] for doc in filtered], ["bear-care"])

    def test_named_value_added_product_always_merges_keyword_fallback(self):
        self.assertTrue(
            kb_service.should_merge_keyword_fallback("熊搭心 年繳 一年多少錢")
        )

    def test_wifi_5_expanded_query_excludes_generic_wifi_parent_record(self):
        docs = [
            {
                "id": "wifi-generic",
                "answer": "WiFi 加值服務月租 50 元，年繳 600 元。",
                "record_type": "product_service",
                "document_type": "product_service_catalog",
                "product_name": "WiFi 加值服務",
                "product_aliases": "WiFi 加值 | WiFi 服務 | Mesh 分享器",
            },
            {
                "id": "wifi-5",
                "answer": "WiFi 5 系列分享器半年繳 150 元，年繳 300 元。",
                "record_type": "product_service",
                "document_type": "product_service_catalog",
                "product_name": "WiFi 5 系列分享器",
                "product_aliases": "WiFi 5 | WIFI5 | WI-FI 5 | WiFi 5分享器",
                "product_parent": "WiFi 加值服務",
            },
        ]

        filtered = kb_service.filter_docs_for_query_intent(
            "WiFi 5 一年多少？ WiFi 5 WIFI5 WI-FI 5 WiFi 5分享器 "
            "WiFi加值 WiFi服務 Mesh 分享器 無線網路設備 加值服務",
            docs,
        )

        self.assertEqual([doc["id"] for doc in filtered], ["wifi-5"])

    def test_named_campaign_product_query_keeps_requested_campaign(self):
        docs = [
            {
                "id": "campaign-no8",
                "answer": "好視成雙NO8 LINE TV首期贈送半年。",
                "document_type": "promotion_campaign",
                "campaign_name": "好視成雙NO8",
                "campaign_aliases": "好視成雙NO8 | 好視成雙 NO8",
            },
            {
                "id": "line-tv",
                "answer": "LINE TV 特價$600元/半年。",
                "record_type": "product_service",
                "document_type": "product_service_catalog",
                "product_name": "LINE TV",
                "product_aliases": "LINE TV | LINETV",
            },
        ]

        filtered = kb_service.filter_docs_for_query_intent(
            "好視成雙NO8的LINE TV送多久？",
            docs,
        )

        self.assertEqual([doc["id"] for doc in filtered], ["campaign-no8"])

    def test_generic_promotion_query_excludes_internal_dispatch_note_and_scans_campaign(self):
        class DispatchOnlySearcher:
            def search(self, query, top_k, knowledge_base=None, category=None):
                if knowledge_base != "大屯":
                    return []
                return [
                    {
                        "id": "b2606-dispatch-note",
                        "document_id": "campaign-doc",
                        "question": "飆網守護家_B2606",
                        "answer": "客服報價／派工方案注意事項 客新裝【飆網守護家(B2606)：綁約24個月；300M/300M；半年繳】請上傳雙證件，完工收$3594元。",
                        "company": "大屯",
                        "category": "network_support",
                        "source": "飆網守護家_B2606.pdf",
                        "title": "飆網守護家_B2606",
                        "_score": 0.96,
                        "_distance": 0.04,
                    }
                ]

        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            campaign_file = tmp_path / "b2606.txt"
            campaign_file.write_text(
                "方案名稱：飆網守護家_(B2606) (網路贈清冰組方案)\n"
                "活動期間：2026/06/05~2026/9/30\n"
                "裝機費：免裝機費。\n"
                "綁約期間：此方案須綁約24個月。\n"
                "售價：100M/10M 原價600元、季繳1197元、半年繳2394元、年繳4788元。\n"
                "300M/300M 原價1000元、季繳1797元、半年繳3594元、年繳7188元。\n",
                encoding="utf-8",
            )
            manifest_path = tmp_path / "documents.json"
            manifest_path.write_text(
                """{
  "documents": [
    {
      "id": "doc-b2606",
      "title": "飆網守護家_B2606",
      "file_name": "b2606.txt",
      "file_path": "%s",
      "knowledge_base": "大屯",
      "category": "network_support",
      "status": "active",
      "processing_status": "indexed"
    }
  ]
}""" % str(campaign_file).replace("\\", "\\\\"),
                encoding="utf-8",
            )

            with patch.object(kb_service, "RAG_BACKEND", "local"), \
                    patch.object(kb_service, "RAG_LOCAL_MANIFEST_PATH", str(manifest_path)), \
                    patch.object(kb_service, "load_local_searcher", return_value=DispatchOnlySearcher()):
                docs = kb_service.retrieve_knowledge(
                    "有推薦的優惠方案嗎?",
                    {"company_code": "tdtv"},
                    {"knowledge_query": "有推薦的優惠方案嗎?"},
                    top_k=3,
                )

        self.assertEqual(len(docs), 1)
        self.assertNotEqual(docs[0]["id"], "b2606-dispatch-note")
        self.assertIn("活動期間：2026/06/05", docs[0]["answer"])
        self.assertIn("300M/300M", docs[0]["answer"])
        self.assertNotIn("客服報價", docs[0]["answer"])

    def test_social_discount_query_keeps_social_discount_docs(self):
        docs = [
            {
                "id": "low-income-discount",
                "question": "低收入、身心障礙優惠報價AI版",
                "answer": "【方案名稱】 低收入戶優惠方案",
                "source": {"title": "低收入、身心障礙優惠報價AI版"},
            }
        ]

        filtered = kb_service.filter_docs_for_query_intent("有低收入優惠方案嗎?", docs)

        self.assertEqual(filtered, docs)

    def test_low_income_abbreviation_query_keeps_social_discount_docs(self):
        docs = [
            {
                "id": "low-income-discount",
                "question": "低收入、身心障礙優惠報價AI版",
                "answer": "【方案名稱】 低收入戶優惠方案",
                "source": {"title": "低收入、身心障礙優惠報價AI版"},
            },
            {
                "id": "campaign-discount",
                "question": "好視成雙 NO8",
                "answer": "方案名稱：好視成雙 NO8 活動期間：115.06.10~115.08.31",
                "source": {"title": "好視成雙 NO8"},
            },
        ]

        filtered = kb_service.filter_docs_for_query_intent("低收優惠方案", docs)

        self.assertEqual(filtered, docs)

    def test_generic_promotion_query_filters_non_primary_campaign_docs(self):
        docs = [
            {
                "id": "primary-campaign",
                "question": "飆網守護家 B2606",
                "answer": "方案名稱：飆網守護家 B2606 活動期間：2026/06/05~2026/9/30 主推 300M/300M。",
            },
            {
                "id": "hidden-campaign",
                "question": "隱藏版優惠方案",
                "answer": "方案名稱：隱藏版方案。下述頻寬不推，特殊需求須請示主管同意後方可派工裝機，AI 禁止報價。",
            },
        ]

        filtered = kb_service.filter_docs_for_query_intent("有推薦的優惠方案嗎?", docs)

        self.assertEqual([doc["id"] for doc in filtered], ["primary-campaign"])

    def test_non_primary_query_keeps_non_primary_campaign_docs(self):
        docs = [
            {
                "id": "hidden-campaign",
                "question": "隱藏版優惠方案",
                "answer": "方案名稱：隱藏版方案。下述頻寬不推，特殊需求須請示主管同意後方可派工裝機，AI 禁止報價。",
            },
        ]

        filtered = kb_service.filter_docs_for_query_intent("隱藏版方案有哪些?", docs)

        self.assertEqual(filtered, docs)

    def test_generic_promotion_query_keeps_primary_campaign_with_restricted_rate_notes(self):
        docs = [
            {
                "id": "b2606",
                "question": "飆網守護家 B2606",
                "answer": (
                    "方案名稱：飆網守護家_(B2606) 活動期間：2026/06/05~2026/9/30 "
                    "本方案:1.主推 100M、300M、500M；"
                    "2.如特殊需求 60M 與 1G 須請示主管同意後方可派工裝機。"
                    "下述頻寬不推，特殊需求須請示主管同意後方可派工裝機 (AI 禁止報價)"
                ),
            },
        ]

        filtered = kb_service.filter_docs_for_query_intent("有推薦的優惠方案嗎?", docs)

        self.assertEqual(filtered, docs)

    def test_generic_promotion_query_keeps_campaign_when_only_rates_are_hidden(self):
        docs = [
            {
                "id": "b2606",
                "question": "飆網守護家 B2606",
                "answer": (
                    "方案名稱：飆網守護家_(B2606) 活動期間：2026/06/05~2026/9/30\n"
                    "100M/10M：季繳$1197元、半年繳$2394元、年繳$4788元\n"
                    "300M/300M：季繳$1797元、半年繳$3594元、年繳$7188元\n"
                    "500M/500M：季繳$2097元、半年繳$4194元、年繳$8388元\n"
                    "60M/60M：原價$500元、季繳$897元、半年繳$1794元、年繳$8388元(隱藏版)\n"
                    "1G/1G：原價$1700元、季繳$3597元、半年繳$7194元、年繳$14388元(隱藏版)"
                ),
            },
        ]

        filtered = kb_service.filter_docs_for_query_intent("有推薦的優惠方案嗎?", docs)

        self.assertEqual(filtered, docs)

    def test_broadband_plan_price_query_does_not_promote_campaign_docs(self):
        class FakeSearcher:
            def search(self, query, top_k, knowledge_base=None, category=None):
                if knowledge_base != "大屯":
                    return []
                return [
                    {
                        "id": "b2606-campaign",
                        "document_id": "campaign-doc",
                        "question": "飆網守護家B2606",
                        "answer": "方案名稱：飆網守護家 B2606。裝機費 0 元，寬頻設備押金 0 元，月繳、半年繳、年繳。",
                        "company": "大屯",
                        "category": "billing",
                        "source": "飆網守護家B2606.pdf",
                        "title": "飆網守護家B2606",
                        "_score": 0.95,
                        "_distance": 0.05,
                    },
                    {
                        "id": "net1-plan",
                        "document_id": "net1-doc",
                        "question": "一般寬頻方案哈NET1-AI版",
                        "answer": "一般寬頻方案 方案名稱：哈 NET1。60M/6M 月繳 500 元，100M/10M 月繳 600 元。",
                        "company": "大屯",
                        "category": "network_support",
                        "source": "一般寬頻方案哈NET1-AI版.pdf",
                        "title": "一般寬頻方案哈NET1-AI版",
                        "_score": 0.75,
                        "_distance": 0.25,
                    },
                ]

        with patch.object(kb_service, "RAG_BACKEND", "local"), \
                patch.object(kb_service, "load_local_searcher", return_value=FakeSearcher()):
            docs = kb_service.retrieve_knowledge(
                "寬頻費$",
                {"company_code": "tdtv"},
                {"knowledge_query": "一般寬頻方案 哈 NET1 速率 月繳 半年繳 年繳 裝機費 押金"},
                top_k=2,
            )

        self.assertEqual(docs[0]["id"], "net1-plan")

    def test_high_signal_query_merges_keyword_fallback_when_chroma_returns_irrelevant_docs(self):
        class FakeSearcher:
            def search(self, query, top_k, knowledge_base=None, category=None):
                return [
                    {
                        "id": "generic-plan",
                        "document_id": "generic-plan-doc",
                        "question": "三合一方案",
                        "answer": "三合一方案可享有高速網路與電視服務，如需優惠方案請洽客服。",
                        "company": knowledge_base or "通用",
                        "category": "billing",
                        "source": "網路寬頻.csv",
                        "title": "三合一方案",
                        "_score": 0.9,
                        "_distance": 0.1,
                    }
                ]

        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            docs_dir = tmp_path / "docs"
            docs_dir.mkdir()
            discount_file = docs_dir / "低收入優惠.txt"
            discount_file.write_text(
                "【方案名稱】 低收入戶優惠方案\n"
                "【申請方式】 客戶需親自至門市臨櫃辦理申請。\n"
                "【優惠內容】 裝機費優惠後收費金額：0元。電視收視服務費優惠期間：12個月，優惠後收費金額：0元／年。\n",
                encoding="utf-8",
            )
            manifest_path = docs_dir / "documents.json"
            manifest_path.write_text(
                """{
  "documents": [
    {
      "id": "discount-doc",
      "title": "低收入、身心障礙優惠報價AI版",
      "file_name": "低收入優惠.txt",
      "file_path": "%s",
      "knowledge_base": "大屯",
      "category": "billing",
      "status": "active",
      "processing_status": "indexed"
    }
  ]
}""" % str(discount_file).replace("\\", "\\\\"),
                encoding="utf-8",
            )

            with patch.object(kb_service, "RAG_BACKEND", "local"), \
                    patch.object(kb_service, "RAG_LOCAL_MANIFEST_PATH", str(manifest_path)), \
                    patch.object(kb_service, "RAG_LOCAL_DOCS_DIR", str(docs_dir)), \
                    patch.object(kb_service, "load_local_searcher", return_value=FakeSearcher()):
                docs = kb_service.retrieve_knowledge(
                    "有低收入優惠方案嗎?",
                    {"company_code": "tdtv"},
                    {"knowledge_query": "有低收入優惠方案嗎?"},
                    top_k=3,
                )

        self.assertEqual(docs[0]["question"], "低收入、身心障礙優惠報價AI版")
        self.assertIn("0元／年", docs[0]["answer"])
        self.assertTrue(any(doc["id"] == "generic-plan" for doc in docs))

    def test_merge_keeps_distinct_faq_rows_that_share_one_document_id(self):
        broad_row = {
            "id": "shared-faq-document",
            "document_id": "shared-faq-document",
            "question": "機上盒無法使用",
            "answer": "請先確認電源與畫面狀態。",
            "company": "佳光市區",
            "category": "set_top_box",
            "source": "機上盒.csv",
            "title": "機上盒無法使用",
            "section": "row 1",
            "_score": 0.8,
            "_distance": 0.2,
        }
        exact_row = {
            "id": "shared-faq-document",
            "document_id": "shared-faq-document",
            "question": "機上盒可以錄影嗎?",
            "answer": "目前機上盒不提供錄影功能。",
            "company": "佳光市區",
            "category": "set_top_box",
            "source": "機上盒.csv",
            "title": "機上盒可以錄影嗎?",
            "section": "row 2",
            "_keyword_score": 900,
        }

        with (
            patch.object(kb_service, "RAG_BACKEND", "local"),
            patch.object(
                kb_service,
                "retrieve_knowledge_from_local_chroma",
                return_value=[broad_row],
            ),
            patch.object(
                kb_service,
                "retrieve_knowledge_from_keyword_fallback",
                return_value=[exact_row],
            ),
            patch.object(
                kb_service,
                "should_merge_keyword_fallback_for_results",
                return_value=True,
            ),
            patch.object(
                kb_service,
                "filter_docs_for_active_campaign_alias",
                side_effect=lambda query, memory, docs: docs,
            ),
        ):
            docs = kb_service.retrieve_knowledge(
                "機上盒能不能錄節目？",
                {"knowledge_base": "佳光市區", "company": "佳光市區"},
                top_k=8,
            )

        self.assertEqual(len(docs), 2)
        self.assertTrue(any(doc["question"] == "機上盒可以錄影嗎?" for doc in docs))

    def test_local_chroma_backend_uses_common_only_without_company_context(self):
        class FakeSearcher:
            def __init__(self):
                self.calls = []

            def search(self, query, top_k, knowledge_base=None, category=None):
                self.calls.append(knowledge_base)
                return []

        fake = FakeSearcher()
        with patch.object(kb_service, "RAG_BACKEND", "local"), \
                patch.object(kb_service, "load_local_searcher", return_value=fake), \
                patch.object(kb_service, "read_active_kb_document_records", return_value=[]):
            docs = kb_service.retrieve_knowledge("退租流程", {}, {}, top_k=3)

        self.assertEqual(docs, [])
        self.assertEqual(fake.calls, ["通用-中區", "通用"])

    def test_local_chroma_hnsw_error_repairs_index_and_retries(self):
        class BrokenSearcher:
            def search(self, query, top_k, knowledge_base=None, category=None):
                raise RuntimeError("Error constructing hnsw segment reader: Error loading hnsw index")

        class RepairedSearcher:
            def __init__(self):
                self.calls = []

            def search(self, query, top_k, knowledge_base=None, category=None):
                self.calls.append(knowledge_base)
                return [
                    {
                        "id": f"{knowledge_base}:move-fee",
                        "document_id": f"{knowledge_base}:doc",
                        "question": "移機費用",
                        "answer": f"{knowledge_base}移機費用資料",
                        "company": knowledge_base,
                        "category": "billing",
                        "source": "移機費用.csv",
                        "title": "移機費用",
                        "_score": 0.9,
                        "_distance": 0.1,
                    }
                ]

        repaired = RepairedSearcher()
        with patch.object(kb_service, "RAG_BACKEND", "local"), \
                patch.object(kb_service, "load_local_searcher", side_effect=[BrokenSearcher(), repaired]), \
                patch.object(kb_service, "repair_local_chroma_index", return_value=True) as repair:
            docs = kb_service.retrieve_knowledge(
                "移機費用",
                {"company_code": "tdtv"},
                {"knowledge_query": "移機費用"},
                top_k=2,
            )

        repair.assert_called_once()
        self.assertEqual(repaired.calls, ["通用-中區", "通用", "大屯"])
        self.assertEqual(len(docs), 2)
        self.assertIn("移機費用資料", docs[0]["answer"])

    def test_local_chroma_failed_repair_uses_circuit_breaker(self):
        class BrokenSearcher:
            def __init__(self):
                self.calls = 0

            def search(self, query, top_k, knowledge_base=None, category=None):
                self.calls += 1
                raise RuntimeError(
                    "Error constructing hnsw segment reader: Error loading hnsw index"
                )

        broken = BrokenSearcher()
        kb_service.clear_local_searcher_degraded()
        try:
            with patch.object(kb_service, "load_local_searcher", return_value=broken), \
                    patch.object(kb_service, "repair_local_chroma_index", return_value=False) as repair:
                first = kb_service.retrieve_knowledge_from_local_chroma(
                    "移機費用", {"company_code": "tdtv"}, 3, 1.0
                )
                second = kb_service.retrieve_knowledge_from_local_chroma(
                    "移機費用", {"company_code": "tdtv"}, 3, 1.0
                )

            self.assertEqual(first, [])
            self.assertEqual(second, [])
            self.assertEqual(broken.calls, 1)
            repair.assert_called_once_with()
            self.assertTrue(kb_service._LOCAL_SEARCHER_DEGRADED)
        finally:
            kb_service.clear_local_searcher_degraded()

    def test_local_chroma_repair_restores_backup_before_full_rebuild(self):
        class BrokenSearcher:
            def search(self, query, top_k):
                raise RuntimeError(
                    "Error constructing hnsw segment reader: Error loading hnsw index"
                )

        class RestoredSearcher:
            def __init__(self):
                self.calls = 0

            def search(self, query, top_k):
                self.calls += 1
                return []

        restored = RestoredSearcher()
        kb_service.clear_local_searcher_degraded()
        try:
            with patch(
                "app.services.kb_admin_service.kb_index_write_lock",
                return_value=nullcontext(),
            ), patch(
                "app.services.kb_admin_service.restore_chroma_store_from_backup",
                return_value={"restored": True, "backup_dir": "backup"},
            ) as restore, patch(
                "app.services.kb_admin_service.rebuild_active_index"
            ) as rebuild, patch.object(
                kb_service,
                "local_kb_runtime_snapshot",
                return_value={"active_documents": 1},
            ), patch.object(
                kb_service,
                "load_local_searcher",
                side_effect=[BrokenSearcher(), restored],
            ):
                repaired = kb_service.repair_local_chroma_index()

            self.assertTrue(repaired)
            restore.assert_called_once_with(_lock_held=True)
            rebuild.assert_not_called()
            self.assertEqual(restored.calls, 1)
            self.assertFalse(kb_service._LOCAL_SEARCHER_DEGRADED)
        finally:
            kb_service.clear_local_searcher_degraded()

    def test_reset_local_searcher_cache_clears_degraded_mode(self):
        kb_service.mark_local_searcher_degraded("broken index")
        kb_service.reset_local_searcher_cache()

        self.assertFalse(kb_service._LOCAL_SEARCHER_DEGRADED)
        self.assertEqual(kb_service._LOCAL_SEARCHER_DEGRADED_REASON, "")

    def test_local_searcher_prewarm_retries_transient_hnsw_error_without_rebuild(self):
        class TransientSearcher:
            def __init__(self):
                self.calls = 0

            def search(self, query, top_k):
                self.calls += 1
                if self.calls == 1:
                    raise RuntimeError("Error sending backfill request to compactor")
                return []

        searcher = TransientSearcher()
        with patch.object(kb_service, "RAG_BACKEND", "local"), \
                patch.object(kb_service, "load_local_searcher", return_value=searcher), \
                patch.object(kb_service.time, "sleep"), \
                patch.object(kb_service, "repair_local_chroma_index") as repair:
            kb_service.prewarm_local_searcher()

        self.assertEqual(searcher.calls, 2)
        repair.assert_not_called()

    def test_local_searcher_prewarm_repairs_persistent_hnsw_error_once(self):
        class BrokenSearcher:
            def __init__(self):
                self.calls = 0

            def search(self, query, top_k):
                self.calls += 1
                raise RuntimeError("Error constructing hnsw segment reader: Error loading hnsw index")

        searcher = BrokenSearcher()
        with patch.object(kb_service, "RAG_BACKEND", "local"), \
                patch.object(kb_service, "load_local_searcher", return_value=searcher), \
                patch.object(kb_service.time, "sleep"), \
                patch.object(kb_service, "repair_local_chroma_index", return_value=True) as repair:
            kb_service.prewarm_local_searcher()

        self.assertEqual(searcher.calls, 2)
        repair.assert_called_once_with()

    def test_local_searcher_prewarm_repairs_compactor_hnsw_error_once(self):
        class CompactorHnswBrokenSearcher:
            def __init__(self):
                self.calls = 0

            def search(self, query, top_k):
                self.calls += 1
                raise RuntimeError(
                    "Error sending backfill request to compactor: "
                    "Error constructing hnsw segment reader: Error loading hnsw index"
                )

        searcher = CompactorHnswBrokenSearcher()
        kb_service.clear_local_searcher_degraded()
        with patch.object(kb_service, "RAG_BACKEND", "local"), \
                patch.object(kb_service, "load_local_searcher", return_value=searcher), \
                patch.object(kb_service.time, "sleep"), \
                patch.object(kb_service, "repair_local_chroma_index", return_value=True) as repair:
            kb_service.prewarm_local_searcher()

        self.assertEqual(searcher.calls, 2)
        repair.assert_called_once_with()
        self.assertFalse(kb_service._LOCAL_SEARCHER_DEGRADED)

    def test_local_chroma_compactor_error_uses_fallback_without_rebuild(self):
        class CompactorBusySearcher:
            def search(self, query, top_k, knowledge_base=None, category=None):
                raise RuntimeError("Error sending backfill request to compactor")

        kb_service.clear_local_searcher_degraded()
        try:
            with patch.object(kb_service, "load_local_searcher", return_value=CompactorBusySearcher()), \
                    patch.object(kb_service, "repair_local_chroma_index") as repair:
                docs = kb_service.retrieve_knowledge_from_local_chroma(
                    "移機費用", {"company_code": "tdtv"}, 3, 1.0
                )

            self.assertEqual(docs, [])
            repair.assert_not_called()
            self.assertFalse(kb_service._LOCAL_SEARCHER_DEGRADED)
        finally:
            kb_service.clear_local_searcher_degraded()

    def test_local_chroma_compactor_hnsw_error_repairs_index_and_retries(self):
        class BrokenSearcher:
            def search(self, query, top_k, knowledge_base=None, category=None):
                raise RuntimeError(
                    "Error sending backfill request to compactor: "
                    "Error constructing hnsw segment reader: Error loading hnsw index"
                )

        class RepairedSearcher:
            def __init__(self):
                self.calls = []

            def search(self, query, top_k, knowledge_base=None, category=None):
                self.calls.append(knowledge_base)
                return [
                    {
                        "id": f"{knowledge_base}:install",
                        "document_id": f"{knowledge_base}:doc",
                        "question": "裝機說明",
                        "answer": f"{knowledge_base}裝機說明資料",
                        "company": knowledge_base,
                        "category": "service",
                        "source": "裝機說明.csv",
                        "title": "裝機說明",
                        "_score": 0.9,
                        "_distance": 0.1,
                    }
                ]

        repaired = RepairedSearcher()
        kb_service.clear_local_searcher_degraded()
        try:
            with patch.object(kb_service, "load_local_searcher", side_effect=[BrokenSearcher(), repaired]), \
                    patch.object(kb_service, "repair_local_chroma_index", return_value=True) as repair:
                docs = kb_service.retrieve_knowledge_from_local_chroma(
                    "裝機說明", {"company_code": "tdtv"}, 3, 1.0
                )

            repair.assert_called_once_with()
            self.assertEqual(repaired.calls, ["通用-中區", "通用", "大屯"])
            self.assertEqual(len(docs), 3)
            self.assertIn("裝機說明資料", docs[0]["answer"])
            self.assertFalse(kb_service._LOCAL_SEARCHER_DEGRADED)
        finally:
            kb_service.clear_local_searcher_degraded()

    def test_local_keyword_fallback_finds_move_fee_when_chroma_returns_empty(self):
        class EmptySearcher:
            def search(self, query, top_k, knowledge_base=None, category=None):
                return []

        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            csv_path = tmp_path / "faq.csv"
            csv_path.write_text(
                "question,answer,company\n"
                "申請電視搬移服務？,移機分室內或室外移機，移機需收費室內 500元 室外800元。,共用\n",
                encoding="utf-8",
            )
            manifest_path = tmp_path / "documents.json"
            manifest_path.write_text(
                """{
  "documents": [
    {
      "id": "doc-move",
      "title": "加值服務",
      "file_name": "faq.csv",
      "file_path": "%s",
      "knowledge_base": "通用",
      "category": "value_added_service",
      "status": "active",
      "processing_status": "indexed"
    }
  ]
}""" % str(csv_path).replace("\\", "\\\\"),
                encoding="utf-8",
            )

            with patch.object(kb_service, "RAG_BACKEND", "local"), \
                    patch.object(kb_service, "RAG_LOCAL_MANIFEST_PATH", str(manifest_path)), \
                    patch.object(kb_service, "load_local_searcher", return_value=EmptySearcher()):
                docs = kb_service.retrieve_knowledge(
                    "室內移機費用",
                    {"company_code": "tdtv"},
                    {"knowledge_query": "室內移機費用"},
                    top_k=3,
                )

        self.assertEqual(len(docs), 1)
        self.assertEqual(docs[0]["question"], "申請電視搬移服務？")
        self.assertIn("室內 500元", docs[0]["answer"])
        self.assertIn("室外800元", docs[0]["answer"])
        self.assertEqual(docs[0]["company"], "通用")

    def test_local_keyword_fallback_can_scan_indexed_pdf_documents(self):
        class EmptySearcher:
            def search(self, query, top_k, knowledge_base=None, category=None):
                return []

        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            pdf_path = tmp_path / "promo.pdf"
            pdf_path.write_bytes(b"%PDF-1.4\n")
            manifest_path = tmp_path / "documents.json"
            manifest_path.write_text(
                """{
  "documents": [
    {
      "id": "doc-promo",
      "title": "好視成雙NO8-1150610-1150831",
      "file_name": "好視成雙NO8.pdf",
      "file_path": "%s",
      "knowledge_base": "大屯",
      "category": "billing",
      "status": "active",
      "processing_status": "indexed"
    }
  ]
}""" % str(pdf_path).replace("\\", "\\\\"),
                encoding="utf-8",
            )

            chunks = [{
                "content": "方案名稱：好視成雙 NO8。300M/300M 月繳 $899，500M/500M 月繳 $999。",
                "section": "page 2",
                "page_no": 2,
            }]
            with patch.object(kb_service, "RAG_BACKEND", "local"), \
                    patch.object(kb_service, "RAG_LOCAL_MANIFEST_PATH", str(manifest_path)), \
                    patch.object(kb_service, "load_local_searcher", return_value=EmptySearcher()), \
                    patch("app.services.kb_admin_service.extract_document_sections", return_value=[]), \
                    patch("app.services.kb_admin_service.chunk_sections", return_value=chunks):
                docs = kb_service.retrieve_knowledge(
                    "好視成雙 NO8 300M多少錢",
                    {"company_code": "tdtv"},
                    {"knowledge_query": "好視成雙 NO8 300M多少錢"},
                    top_k=3,
                )

        self.assertEqual(len(docs), 1)
        self.assertEqual(docs[0]["source"]["source"], "好視成雙NO8.pdf")
        self.assertEqual(docs[0]["source"]["section"], "page 2")
        self.assertIn("300M/300M", docs[0]["answer"])

    def test_hatv_addon_exact_csv_question_beats_related_campaign_limit(self):
        class RelatedOnlySearcher:
            def search(self, query, top_k, knowledge_base=None, category=None):
                if knowledge_base != "大屯":
                    return []
                return [
                    {
                        "id": "datun-promo-limit",
                        "document_id": "datun-promo",
                        "question": "好視成雙NO8",
                        "answer": "第6台（含）以上機上盒須持續加購100元（含）以上套餐。",
                        "company": "大屯",
                        "category": "billing",
                        "source": "好視成雙NO8.docx",
                        "title": "好視成雙NO8",
                        "_score": 0.89,
                        "_distance": 0.18,
                    }
                ]

        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            csv_path = tmp_path / "hatv.csv"
            csv_path.write_text(
                "question,answer,company\n"
                "哈tv數位套餐加購,"
                "您可以透過官方網站了解詳細頻道內容和收費標準。"
                "如您府上已有安裝台數科聯網機上盒，可透過機上盒購買，"
                "使用遙控器進入VIP會員→優惠專區→數位電視→依喜愛頻道進行購買。,共用\n",
                encoding="utf-8",
            )
            manifest_path = tmp_path / "documents.json"
            manifest_path.write_text(
                """{
  "documents": [
    {
      "id": "doc-hatv",
      "title": "哈TV數位套餐加購",
      "file_name": "hatv.csv",
      "file_path": "%s",
      "knowledge_base": "通用",
      "category": "value_added_service",
      "status": "active",
      "processing_status": "indexed"
    }
  ]
}""" % str(csv_path).replace("\\", "\\\\"),
                encoding="utf-8",
            )

            with patch.object(kb_service, "RAG_BACKEND", "local"), \
                    patch.object(kb_service, "RAG_LOCAL_MANIFEST_PATH", str(manifest_path)), \
                    patch.object(kb_service, "load_local_searcher", return_value=RelatedOnlySearcher()):
                docs = kb_service.retrieve_knowledge(
                    "哈tv數位套餐加購",
                    {"company_code": "tdtv"},
                    {"knowledge_query": "哈TV 數位套餐 加購 費用 內容 申請方式 哈tv數位套餐加購"},
                    top_k=3,
                )

        self.assertEqual(len(docs), 1)
        self.assertEqual(docs[0]["question"], "哈tv數位套餐加購")
        self.assertIn("VIP會員", docs[0]["answer"])

    def test_hatv_addon_chroma_and_keyword_duplicate_same_csv_row_are_deduped(self):
        answer = (
            "您可以透過官方網站了解詳細頻道內容和收費標準。"
            "如您府上已有安裝台數科聯網機上盒，可透過機上盒購買，"
            "使用遙控器進入VIP會員→優惠專區→數位電視→依喜愛頻道進行購買。"
        )

        class ExactRowSearcher:
            def search(self, query, top_k, knowledge_base=None, category=None):
                if knowledge_base != "通用":
                    return []
                return [
                    {
                        "id": "chroma-row-87",
                        "document_id": "doc-hatv",
                        "question": "哈tv數位套餐加購",
                        "answer": answer,
                        "company": "通用",
                        "category": "value_added_service",
                        "source": "加值服務.csv",
                        "title": "哈tv數位套餐加購",
                        "section": "row 87",
                        "_score": 0.746204,
                        "_distance": 0.253796,
                    }
                ]

        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            csv_path = tmp_path / "value_added.csv"
            csv_path.write_text(
                "question,answer,company\n"
                f"哈tv數位套餐加購,{answer},共用\n",
                encoding="utf-8",
            )
            manifest_path = tmp_path / "documents.json"
            manifest_path.write_text(
                """{
  "documents": [
    {
      "id": "doc-hatv",
      "title": "加值服務",
      "file_name": "加值服務.csv",
      "file_path": "%s",
      "knowledge_base": "通用",
      "category": "value_added_service",
      "status": "active",
      "processing_status": "indexed"
    }
  ]
}""" % str(csv_path).replace("\\", "\\\\"),
                encoding="utf-8",
            )

            with patch.object(kb_service, "RAG_BACKEND", "local"), \
                    patch.object(kb_service, "RAG_LOCAL_MANIFEST_PATH", str(manifest_path)), \
                    patch.object(kb_service, "load_local_searcher", return_value=ExactRowSearcher()):
                docs = kb_service.retrieve_knowledge(
                    "哈tv數位套餐加購",
                    {"company_code": "tdtv"},
                    {"knowledge_query": "哈tv數位套餐加購"},
                    top_k=8,
                )

        matching_docs = [doc for doc in docs if doc["question"] == "哈tv數位套餐加購"]
        self.assertEqual(len(matching_docs), 1)
        self.assertIn("VIP會員", matching_docs[0]["answer"])

    def test_keyword_fallback_prioritizes_specific_company_over_common(self):
        class EmptySearcher:
            def search(self, query, top_k, knowledge_base=None, category=None):
                return []

        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            common_csv = tmp_path / "common.csv"
            datun_txt = tmp_path / "datun.txt"
            common_csv.write_text(
                "question,answer,company\n"
                "室內移機費用,室內移機 500 元。,共用\n",
                encoding="utf-8",
            )
            datun_txt.write_text(
                "大屯網路移機費\n"
                "移機分室內或室外移機，移機需收費室內 800 元 室外 800 元。\n",
                encoding="utf-8",
            )
            manifest_path = tmp_path / "documents.json"
            manifest_path.write_text(
                """{
  "documents": [
    {
      "id": "doc-common",
      "title": "通用移機費用",
      "file_name": "common.csv",
      "file_path": "%s",
      "knowledge_base": "通用",
      "category": "billing",
      "status": "active",
      "processing_status": "indexed"
    },
    {
      "id": "doc-datun",
      "title": "大屯網路移機費",
      "file_name": "datun.txt",
      "file_path": "%s",
      "knowledge_base": "大屯",
      "category": "billing",
      "status": "active",
      "processing_status": "indexed"
    }
  ]
}""" % (
                    str(common_csv).replace("\\", "\\\\"),
                    str(datun_txt).replace("\\", "\\\\"),
                ),
                encoding="utf-8",
            )

            with patch.object(kb_service, "RAG_BACKEND", "local"), \
                    patch.object(kb_service, "RAG_LOCAL_MANIFEST_PATH", str(manifest_path)), \
                    patch.object(kb_service, "load_local_searcher", return_value=EmptySearcher()):
                docs = kb_service.retrieve_knowledge(
                    "室內移機費用",
                    {"company_code": "tdtv"},
                    {"knowledge_query": "室內移機費用"},
                    top_k=2,
                )

        self.assertEqual([doc["company"] for doc in docs], ["大屯", "通用"])
        self.assertIn("800", docs[0]["answer"])

    def test_keyword_fallback_resolves_stale_absolute_manifest_path_from_docs_dir(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            old_path = tmp_path / "old_app" / "data" / "kb_documents" / "doc_faq.csv"
            runtime_docs_dir = tmp_path / "runtime" / "kb_documents"
            runtime_file = runtime_docs_dir / old_path.name
            runtime_file.parent.mkdir(parents=True)
            runtime_file.write_text(
                "question,answer,company\n"
                "固定IP費用,固定 IP 月租費用請由客服確認。,共用\n",
                encoding="utf-8",
            )
            manifest_path = runtime_docs_dir / "documents.json"
            manifest_path.write_text(
                """{
  "documents": [
    {
      "id": "doc-ip",
      "title": "固定IP",
      "file_name": "doc_faq.csv",
      "file_path": "%s",
      "knowledge_base": "通用",
      "category": "network_support",
      "status": "active",
      "processing_status": "indexed"
    }
  ]
}""" % str(old_path).replace("\\", "\\\\"),
                encoding="utf-8",
            )

            with patch.object(kb_service, "RAG_LOCAL_MANIFEST_PATH", str(manifest_path)), \
                    patch.object(kb_service, "RAG_LOCAL_DOCS_DIR", str(runtime_docs_dir)):
                records = kb_service.read_active_kb_document_records(["通用"])

        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["_resolved_file_path"], runtime_file)

    def test_keyword_fallback_reads_cp950_csv_documents(self):
        class EmptySearcher:
            def search(self, *_args, **_kwargs):
                return []

        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            docs_dir = tmp_path / "kb_documents"
            docs_dir.mkdir()
            csv_path = docs_dir / "billing_cp950.csv"
            csv_path.write_text(
                "question,answer,company,category\n"
                "查詢繳費方式,"
                "貼心提醒，透過線上刷卡繳費、IBON及FAMIPORT繳費方式系統會自動開通喔,"
                "共用,billing\n",
                encoding="cp950",
            )
            manifest_path = docs_dir / "documents.json"
            manifest_path.write_text(
                """{
  "documents": [
    {
      "id": "billing-cp950",
      "title": "帳務",
      "file_name": "billing_cp950.csv",
      "file_path": "%s",
      "knowledge_base": "通用",
      "category": "billing",
      "status": "active",
      "processing_status": "indexed"
    }
  ]
}""" % str(csv_path).replace("\\", "\\\\"),
                encoding="utf-8",
            )

            with patch.object(kb_service, "RAG_BACKEND", "local"), \
                    patch.object(kb_service, "RAG_LOCAL_MANIFEST_PATH", str(manifest_path)), \
                    patch.object(kb_service, "RAG_LOCAL_DOCS_DIR", str(docs_dir)), \
                    patch.object(kb_service, "load_local_searcher", return_value=EmptySearcher()):
                docs = kb_service.retrieve_knowledge(
                    "線上刷卡會自動開通嗎",
                    {"company_code": "tdtv"},
                    {"knowledge_query": "線上刷卡會自動開通嗎"},
                    top_k=3,
                )

        self.assertEqual(len(docs), 1)
        self.assertIn("線上刷卡繳費", docs[0]["answer"])
        self.assertIn("自動開通", docs[0]["answer"])

    def test_convenience_store_payment_machine_query_prefers_machine_guides(self):
        class EmptySearcher:
            def search(self, *_args, **_kwargs):
                return []

        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            docs_dir = tmp_path / "kb_documents"
            docs_dir.mkdir()
            csv_path = docs_dir / "billing.csv"
            csv_path.write_text(
                "question,answer,company,category\n"
                "查詢繳費方式,目前可用繳費方式包含線上繳費、臨櫃繳費、APP繳費、超商繳費。,共用,billing\n"
                "IBON,前往7-Eleven便利商店找到ibon機台，選擇繳費，輸入用戶電話，列印繳費單後至櫃台繳費。,共用,billing\n"
                "famiport繳費教學,famiport機台操作：繳費→有線電視→輸入用戶電話→列印繳費單→持繳費單至櫃台繳費。,共用,billing\n"
                "好視成雙NO8,方案名稱：好視成雙NO8。活動期間、月繳、半年繳與優惠內容。,大屯,billing\n",
                encoding="utf-8",
            )
            manifest_path = docs_dir / "documents.json"
            manifest_path.write_text(
                """{
  "documents": [
    {
      "id": "billing",
      "title": "帳務",
      "file_name": "billing.csv",
      "file_path": "%s",
      "knowledge_base": "通用",
      "category": "billing",
      "status": "active",
      "processing_status": "indexed"
    }
  ]
}""" % str(csv_path).replace("\\", "\\\\"),
                encoding="utf-8",
            )

            with patch.object(kb_service, "RAG_BACKEND", "local"), \
                    patch.object(kb_service, "RAG_LOCAL_MANIFEST_PATH", str(manifest_path)), \
                    patch.object(kb_service, "RAG_LOCAL_DOCS_DIR", str(docs_dir)), \
                    patch.object(kb_service, "load_local_searcher", return_value=EmptySearcher()):
                docs = kb_service.retrieve_knowledge(
                    "超商繳費機怎麼操作呢?",
                    {"company_code": "tdtv"},
                    {
                        "knowledge_query": (
                            "IBON FAMIPORT ibon famiport 超商繳費機 便利商店機台 "
                            "繳費教學 操作流程 7-Eleven 全家"
                        )
                    },
                    top_k=5,
                )

        questions = [doc["question"] for doc in docs]
        self.assertCountEqual(questions, ["IBON", "famiport繳費教學"])
        self.assertTrue(all("好視成雙" not in doc["answer"] for doc in docs))

    def test_keyword_fallback_expands_value_added_package_synonyms(self):
        class EmptySearcher:
            def search(self, *_args, **_kwargs):
                return []

        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            docs_dir = tmp_path / "kb_documents"
            docs_dir.mkdir()
            doc_path = docs_dir / "value_added.csv"
            doc_path.write_text(
                "question,answer,company,category\n"
                "各項單品銷售(數位電視),各項單品銷售/加值服務-數位電視套餐。HBO加價購：$39。冠軍套餐：$100。,大屯,billing\n",
                encoding="utf-8",
            )
            manifest_path = docs_dir / "documents.json"
            manifest_path.write_text(
                """{
  "documents": [
    {
      "id": "value-added",
      "title": "各項單品銷售(數位電視)",
      "file_name": "value_added.csv",
      "file_path": "%s",
      "knowledge_base": "大屯",
      "category": "billing",
      "status": "active",
      "processing_status": "indexed"
    }
  ]
}""" % str(doc_path).replace("\\", "\\\\"),
                encoding="utf-8",
            )

            with patch.object(kb_service, "RAG_BACKEND", "local"), \
                    patch.object(kb_service, "RAG_LOCAL_MANIFEST_PATH", str(manifest_path)), \
                    patch.object(kb_service, "RAG_LOCAL_DOCS_DIR", str(docs_dir)), \
                    patch.object(kb_service, "load_local_searcher", return_value=EmptySearcher()):
                docs = kb_service.retrieve_knowledge(
                    "加值套餐有哪些呢?",
                    {"company_code": "tdtv"},
                    {"knowledge_query": "加值套餐有哪些呢?"},
                    top_k=3,
                )

        self.assertEqual(len(docs), 1)
        self.assertIn("HBO加價購", docs[0]["answer"])

    def test_infer_knowledge_base_maps_tdtv_to_datun(self):
        self.assertEqual(kb_service.infer_knowledge_base({"company_code": "tdtv"}), "大屯")

    def test_infer_knowledge_base_maps_company_codes_and_defaults_to_common(self):
        self.assertEqual(kb_service.infer_knowledge_base({"company_code": "cltv"}), "佳聯")
        self.assertEqual(kb_service.infer_knowledge_base({"company_code": "pktv"}), "北港")
        self.assertEqual(kb_service.infer_knowledge_base({"company": "佳聯有線"}), "佳聯")
        self.assertEqual(kb_service.infer_knowledge_base({}), "通用")

    def test_infer_knowledge_bases_includes_central_common_for_central_systems(self):
        self.assertEqual(
            kb_service.infer_knowledge_bases({"company_code": "tdtv"}),
            ["通用-中區", "通用", "大屯"],
        )
        self.assertEqual(
            kb_service.infer_knowledge_bases({"company_code": "cltv"}),
            ["通用-中區", "通用", "佳聯"],
        )
        self.assertEqual(
            kb_service.infer_knowledge_bases({"company_code": "pktv"}),
            ["通用-中區", "通用", "北港"],
        )

    def test_infer_knowledge_bases_includes_common_scope_for_explicit_station(self):
        self.assertEqual(
            kb_service.infer_knowledge_bases({"knowledge_base": "西海岸"}),
            ["通用-中區", "通用", "西海岸"],
        )

    def test_infer_knowledge_bases_includes_jiannan_common_for_jiannan_systems(self):
        self.assertEqual(
            kb_service.infer_knowledge_bases({"company_code": "hya"}),
            ["通用-嘉南區", "新永安"],
        )
        self.assertEqual(
            kb_service.infer_knowledge_bases({"company_code": "tycable"}),
            ["通用-嘉南區", "大揚"],
        )

    def test_infer_knowledge_bases_uses_configured_common_scope_members(self):
        with patch.object(
            kb_service.COMMON_SCOPE_SERVICE,
            "get_common_knowledge_base_scopes",
            return_value={
                "通用-中區": ["新永安"],
                "通用-嘉南區": ["大屯"],
            },
        ):
            self.assertEqual(
                kb_service.infer_knowledge_bases({"company_code": "tdtv"}),
                ["通用-嘉南區", "大屯"],
            )
            self.assertEqual(
                kb_service.infer_knowledge_bases({"company_code": "hya"}),
                ["通用-中區", "通用", "新永安"],
            )

        with patch.object(
            kb_service.COMMON_SCOPE_SERVICE,
            "get_common_knowledge_base_scopes",
            return_value={
                "通用-中區": ["大屯"],
                "通用-嘉南區": ["大屯"],
            },
        ):
            self.assertEqual(
                kb_service.infer_knowledge_bases({"company_code": "tdtv"}),
                ["大屯"],
            )

    @unittest.skip(
        "Archived legacy path: broad promotion questions are clarified by the model router before retrieval."
    )
    def test_compose_knowledge_reply_summarizes_long_rag_answer(self):
        calls = []
        llm = RunnableLambda(
            lambda payload: calls.append(payload)
            or AIMessage(content="目前查到的優惠重點：\n1. 寬頻搭 LINE TV 半年。\n2. 可借用 OTT 盒子。\n3. 詳細月租與限制需由客服確認。")
        )
        long_answer = (
            "贈品(包含加值服務)：143 清冰組+LINE TV半年 售戶是否可參加：可參加 "
            "條件：本身需無合約 租借：租借WiFi一台+居家安全攝影機一台 注意事項："
            "1、售戶盡量不主推，價格問題可推 2、派工請派..."
        ) * 3

        reply = compose_knowledge_reply(
            "優惠套餐有哪些?",
            "",
            [{"id": "chunk-1", "question": "優惠套餐", "answer": long_answer}],
            llm=llm,
            answer_guard_query="優惠套餐有哪些?",
            memory={"company_code": "tdtv"},
        )

        self.assertIn("目前查到的優惠重點", reply)
        self.assertIn("LINE TV", reply)
        self.assertEqual(len(calls), 1)

    def test_compose_knowledge_reply_summarizes_short_rag_answer_too(self):
        calls = []
        llm = RunnableLambda(
            lambda payload: calls.append(payload) or AIMessage(content="不應呼叫摘要模型")
        )

        reply = compose_knowledge_reply(
            "請問動態方案 X9",
            "",
            [{
                "id": "chunk-1",
                "question": "動態方案 X9",
                "campaign_name": "動態方案 X9",
                "document_type": "promotion_campaign",
                "answer": "申裝寬頻網路即可免費享有 LINE TV。",
            }],
            llm=llm,
            answer_guard_query="動態方案 X9",
            memory={"company_code": "tdtv"},
            promotion_query_kind="campaign_detail",
        )

        self.assertEqual(calls, [])
        self.assertIn("方案名稱：動態方案 X9", reply)
        self.assertIn("LINE TV", reply)

    def test_compose_knowledge_reply_adds_discount_stacking_caution(self):
        llm = RunnableLambda(lambda _payload: AIMessage(content="低收入優惠可以搭配活動方案。"))

        reply = compose_knowledge_reply(
            "低收入優惠可以跟好視成雙一起用嗎?",
            "",
            [{
                "id": "discount",
                "question": "低收入戶優惠方案",
                "answer": "【方案名稱】 低收入戶優惠方案\n【優惠內容】 裝機費 0 元。",
            }],
            llm=llm,
            answer_guard_query="低收入優惠可以跟好視成雙一起用嗎?",
            memory={"company_code": "tdtv"},
        )

        self.assertNotIn("低收入優惠可以搭配活動方案", reply)
        self.assertIn("社福優惠不可與其他公司優惠活動重複適用", reply)
        self.assertIn("不能再同時申請一般促銷或其他優惠方案", reply)

    def test_compose_knowledge_reply_social_discount_merge_query_uses_hard_rule(self):
        llm = RunnableLambda(lambda _payload: AIMessage(content="目前資料沒有明確寫是否可合併，需由客服確認。"))

        reply = compose_knowledge_reply(
            "可以跟低收入合併優惠嗎?",
            "",
            [{
                "id": "discount",
                "question": "低收入戶優惠方案",
                "answer": "【方案名稱】 低收入戶優惠方案\n【優惠內容】 裝機費 0 元。",
            }],
            llm=llm,
            answer_guard_query="可以跟低收入合併優惠嗎?",
            memory={"company_code": "tdtv"},
        )

        self.assertNotIn("目前資料沒有明確寫", reply)
        self.assertIn("不可與其他公司優惠活動重複適用", reply)
        self.assertIn("若要申辦，仍需由客服依您的資格與目前合約狀態確認", reply)

    def test_compose_knowledge_reply_hides_hidden_rate_lines_from_general_campaign_answer(self):
        calls = []
        llm = RunnableLambda(
            lambda payload: calls.append(payload)
            or AIMessage(content="不應呼叫摘要模型")
        )
        answer = (
            "方案名稱：動態方案 X9\n"
            "100M/10M：季繳$1197元、半年繳$2394元、年繳$4788元\n"
            "300M/300M：季繳$1797元、半年繳$3594元、年繳$7188元\n"
            "500M/500M：季繳$2097元、半年繳$4194元、年繳$8388元\n"
            "60M/60M：原價$500元、季繳$897元、半年繳$1794元、年繳$8388元(隱藏版)\n"
            "1G/1G：原價$1700元、季繳$3597元、半年繳$7194元、年繳$14388元(隱藏版)"
        )

        reply = compose_knowledge_reply(
            "動態方案 X9",
            "",
            [{
                "id": "dynamic-x9",
                "question": "動態方案 X9",
                "campaign_name": "動態方案 X9",
                "document_type": "promotion_campaign",
                "answer": answer,
            }],
            llm=llm,
            answer_guard_query="動態方案 X9",
            memory={"company_code": "tdtv"},
            promotion_query_kind="campaign_detail",
        )

        self.assertEqual(calls, [])
        self.assertIn("方案名稱：動態方案 X9", reply)
        self.assertNotIn("60M/60M", reply)
        self.assertNotIn("1G/1G", reply)
        self.assertNotIn("隱藏版", reply)

    def test_format_customer_reply_text_splits_kb_field_labels(self):
        raw = (
            "【方案名稱】 低收入戶優惠方案 【適用對象】 持有有效低收入戶第一、二、三款證明之客戶。"
            "【申請方式】 客戶需親自至門市臨櫃辦理申請。"
            "【優惠內容】 項目1：裝機費 - 優惠後收費金額：0元 項目2：電視收視服務費 - 優惠期間：12個月"
            "【限制條件】 僅適用符合資格之客戶。"
        )

        reply = format_customer_reply_text(raw)

        self.assertIn("【方案名稱】\n低收入戶優惠方案", reply)
        self.assertIn("\n【適用對象】\n持有有效低收入戶", reply)
        self.assertIn("\n【申請方式】\n客戶需親自", reply)
        self.assertIn("\n【優惠內容】\n項目1：裝機費", reply)
        self.assertIn("\n項目2：電視收視服務費", reply)
        self.assertIn("\n【限制條件】\n僅適用符合資格之客戶。", reply)

    def test_format_customer_reply_text_splits_dotted_numbered_list(self):
        raw = (
            "若尚未繳費可以透過以下幾種繳費方式進行繳費：1. 線上刷卡繳費：前往官方網站。"
            "2. 臨櫃繳費：至公司櫃台辦理。"
            "3. APP繳費：下載行動客服 APP。"
            "4. 便利商店繳費：持帳單刷條碼。"
            "5. IBON 及 FamiPort 繳費：依機台指示完成。貼心提醒，繳費後請重新開機。"
        )

        reply = format_customer_reply_text(raw)

        self.assertIn("若尚未繳費可以透過以下幾種繳費方式進行繳費：\n1. 線上刷卡繳費", reply)
        self.assertIn("\n2. 臨櫃繳費", reply)
        self.assertIn("\n5. IBON 及 FamiPort 繳費", reply)
        self.assertIn("\n貼心提醒：\n繳費後請重新開機。", reply)

    def test_format_customer_reply_text_splits_plain_campaign_sections(self):
        raw = (
            "方案名稱：好視成雙 NO8 活動期間：115.06.10~115.08.31 "
            "一、裝機費：免裝機費。 二、網路設備押金：1000元；半年繳(含)以上免押。 "
            "三、繳別：月繳、半年繳、年繳。 四、舊戶是否可參加：無合約均可。"
        )

        reply = format_customer_reply_text(raw)

        self.assertIn("方案名稱：好視成雙 NO8", reply)
        self.assertIn("\n活動期間：115.06.10~115.08.31", reply)
        self.assertIn("\n一、裝機費：免裝機費。", reply)
        self.assertIn("\n二、網路設備押金：1000元", reply)
        self.assertIn("\n三、繳別：月繳、半年繳、年繳。", reply)
        self.assertIn("\n四、舊戶是否可參加：無合約均可。", reply)
        self.assertNotIn("115.\n06", reply)

    def test_format_customer_reply_text_joins_broken_currency_amounts(self):
        raw = (
            "【月租/速率】\n"
            "60M/6M：月繳 $\n"
            "500、半年繳 $3,\n"
            "000、年繳 $6,000\n"
            "300M/300M：月繳 $900、半年繳 $5,\n"
            "400、年繳 $1,0800"
        )

        reply = format_customer_reply_text(raw)

        self.assertIn("60M/6M：月繳 $500、半年繳 $3,000、年繳 $6,000", reply)
        self.assertIn("300M/300M：月繳 $900、半年繳 $5,400、年繳 $10,800", reply)
        self.assertNotIn("$\n500", reply)
        self.assertNotIn("$3,\n000", reply)
        self.assertNotIn("$1,0800", reply)

    def test_format_customer_reply_text_keeps_campaign_payment_rows_together(self):
        raw = (
            "【各速率/繳別金額】\n"
            "100M/10M：月繳\n"
            "399、季繳 1,197、半年繳 2,394、年繳 4,788 元\n"
            "100M/100M：月繳\r\n"
            "450、季繳 1,350、半年繳 2,700、年繳 5,400 元"
        )

        reply = format_customer_reply_text(raw)

        self.assertIn(
            "100M/10M：月繳 399、季繳 1,197、半年繳 2,394、年繳 4,788 元",
            reply,
        )
        self.assertIn(
            "100M/100M：月繳 450、季繳 1,350、半年繳 2,700、年繳 5,400 元",
            reply,
        )
        self.assertNotIn("月繳\n399", reply)
        self.assertNotIn("月繳\n450", reply)

    def test_format_customer_reply_text_keeps_prize_quantities_together(self):
        raw = (
            "獎項內容：\n"
            "第一波（115年8月中）：LINE FRIENDS 車用無線充電器 ×10\n"
            "第二波（115年8月底）：LINE FRIENDS 車用無線充電器 ×2、"
            "料理鍋 ×4、加濕器 ×4"
        )

        reply = format_customer_reply_text(raw)

        self.assertIn("車用無線充電器 ×2\n料理鍋 ×4\n加濕器 ×4", reply)
        self.assertNotIn("×\n2、", reply)
        self.assertNotIn("×\n4、", reply)

    def test_format_customer_reply_text_removes_orphan_fee_numbering(self):
        raw = (
            "第\n\n"
            "1. 第\n\n"
            "1、2 台機上盒：一般戶免費借用，免押金。\n"
            "2. 第 3 台起：每台需收 STB 設備押金 $1,200。\n"
            "3. 分機施工費：裝機時順裝 $500；後續加裝 $800。\n"
            "4. 若已有線路，後續加裝的補線費可免收，實際仍依現場施工判斷。\n"
            "5. 第 6 台含以上：需加購 $100 元以上套餐，且需每年續繳。"
        )

        reply = format_customer_reply_text(raw)

        self.assertNotIn("\n第\n", f"\n{reply}\n")
        self.assertNotIn("1. 第", reply)
        self.assertIn("1、2 台機上盒：一般戶免費借用，免押金。", reply)
        self.assertIn("\n第 3 台起：每台需收數位機上盒設備押金 $1,200。", reply)
        self.assertIn("\n分機施工費：裝機時順裝 $500；後續加裝 $800。", reply)
        self.assertIn("\n若已有線路，後續加裝的補線費可免收，實際仍依現場施工判斷。", reply)
        self.assertIn("\n第 6 台含以上：需加購 $100 元以上套餐，且需每年續繳。", reply)
        self.assertNotIn("\n2. 第 3 台起", reply)
        self.assertNotIn("\n3. 分機施工費", reply)

    def test_compose_knowledge_reply_falls_back_to_raw_answer_when_summary_fails(self):
        class FailingLLM:
            def invoke(self, *_args, **_kwargs):
                raise RuntimeError("llm failed")

        raw_answer = "申裝寬頻網路即可免費享有 LINE TV。"
        reply = compose_knowledge_reply(
            "請問好康三合一",
            "",
            [{"id": "chunk-1", "question": "好康三合一", "answer": raw_answer}],
            llm=FailingLLM(),
            answer_guard_query="好康三合一",
            memory={"company_code": "tdtv"},
        )

        self.assertEqual(reply, raw_answer)

    def test_compose_online_payment_reply_keeps_all_customer_payment_channels(self):
        class FailingLLM:
            def invoke(self, *_args, **_kwargs):
                raise RuntimeError("summary timeout")

        raw_answer = (
            "線上繳費：前往官方網站，在線上繳費專區輸入您的用戶編號和密碼，"
            "然後按照指示完成繳費。\n"
            "貼心提醒，透過 IBON 及 FAMIPORT 繳費方式系統會自動開通。"
        )
        reply = compose_knowledge_reply(
            "線上繳費",
            "",
            [{"id": "online-payment", "question": "線上繳費", "answer": raw_answer}],
            llm=FailingLLM(),
            answer_guard_query="線上繳費 官方網站 繳費專區 用戶編號 密碼",
            memory={"company_code": "tdtv"},
        )

        self.assertIn("官方網站", reply)
        self.assertIn("線上繳費」專區", reply)
        self.assertIn("用戶編號", reply)
        self.assertIn("行動客服 APP", reply)
        self.assertIn("立即繳費", reply)
        self.assertIn("LINE Pay", reply)
        self.assertIn("ibon", reply)
        self.assertIn("FamiPort", reply)

    def test_compose_generic_payment_methods_returns_all_five_channels(self):
        docs = [{
            "id": "payment-overview",
            "question": "查詢繳費方式",
            "answer": "可使用線上刷卡、臨櫃、APP、帳單條碼、ibon 或 FamiPort 繳費。",
        }]

        reply = compose_knowledge_reply(
            "繳款方式查詢",
            "",
            docs,
            llm=RunnableLambda(lambda _prompt: AIMessage(content="不應使用摘要")),
            answer_guard_query="繳費方式 線上刷卡 臨櫃 行動客服 APP 帳單條碼 ibon FamiPort",
            memory={"company_code": "tdtv"},
            intent="bill_payment_methods",
        )

        self.assertIn("1. 線上刷卡繳費", reply)
        self.assertIn("2. 臨櫃繳費", reply)
        self.assertIn("3. APP 繳費", reply)
        self.assertIn("4. 便利商店繳費", reply)
        self.assertIn("5. ibon／FamiPort 繳費", reply)
        self.assertIn("設備電源關閉後重新開機", reply)

    def test_compose_knowledge_reply_labels_promotion_when_summary_fails(self):
        class FailingLLM:
            def invoke(self, *_args, **_kwargs):
                raise RuntimeError("summary timeout")

        raw_answer = "方案名稱：好視成雙NO7。\n500M/500M：月繳999元。"
        reply = compose_knowledge_reply(
            "大屯有哪些優惠？",
            "",
            [{"id": "chunk-1", "question": "大屯優惠方案", "answer": raw_answer}],
            llm=FailingLLM(),
            answer_guard_query="大屯 優惠方案",
            memory={"company_code": "tdtv"},
        )

        self.assertTrue(reply.startswith("大屯目前查到的優惠方案如下："))
        self.assertIn(raw_answer, reply)

    def test_compose_knowledge_reply_does_not_expose_raw_rag_row_when_summary_fails(self):
        class FailingLLM:
            def invoke(self, *_args, **_kwargs):
                raise RuntimeError("llm failed")

        raw_answer = "question: 機上盒可以錄影嗎? ; answer: 因智慧財產權因素，機上盒無法提供錄影功能。 ; company: 共用"
        reply = compose_knowledge_reply(
            "機上盒可以錄影嗎?",
            "",
            [{"id": "chunk-1", "question": "機上盒可以錄影嗎?", "answer": raw_answer}],
            llm=FailingLLM(),
            answer_guard_query="機上盒可以錄影嗎?",
            memory={"company_code": "tdtv"},
        )

        self.assertEqual(reply, "因智慧財產權因素，機上盒無法提供錄影功能。")
        self.assertNotIn("question:", reply)
        self.assertNotIn("company:", reply)

    def test_compose_knowledge_reply_uses_points_fallback_when_retrieval_is_empty(self):
        fallback = "哈POINT 1 點可折抵 1 元，可用於折抵連線費與收視費。"

        with patch(
            "app.handlers.chat_handler.build_general_knowledge_reply",
            return_value=None,
        ):
            reply = compose_knowledge_reply(
                "哈POINT能如何使用",
                "",
                [],
                answer_guard_query="哈POINT 紅利點數 使用方式",
                memory={"company_code": "tdtv"},
                fallback_reply=fallback,
            )

        self.assertEqual(reply, fallback)

    def test_compose_knowledge_reply_uses_later_matching_fee_doc(self):
        class FailingLLM:
            def invoke(self, *_args, **_kwargs):
                raise RuntimeError("llm failed")

        docs = [
            {"id": "1", "question": "優惠", "answer": "裝機費免費。"},
            {"id": "2", "question": "加值服務", "answer": "方案需由客服確認。"},
            {"id": "3", "question": "帳務", "answer": "帳單金額可由客服查詢。"},
            {
                "id": "4",
                "question": "加值服務",
                "answer": "移機分室內或室外移機，移機需收費室內 500元 室外800元。",
            },
        ]

        reply = compose_knowledge_reply(
            "移機費用",
            "",
            docs,
            llm=FailingLLM(),
            answer_guard_query="移機費用",
            memory={"company_code": "tdtv"},
        )

        self.assertIn("室內 500元", reply)
        self.assertIn("室外800元", reply)
        self.assertNotIn("裝機費免費", reply)

    def test_compose_knowledge_reply_returns_explicit_basic_tv_monthly_fee(self):
        class UnexpectedLLM:
            def invoke(self, *_args, **_kwargs):
                raise AssertionError("基本收視費已有明確金額，不應再交給 LLM 重新解讀")

        docs = [
            {
                "id": "promotion",
                "question": "優惠方案",
                "answer": "好視成雙 300M 月繳 899 元。",
            },
            {
                "id": "basic-tv",
                "question": "大屯有線電視基本收費標準",
                "answer": (
                    "TV 收視費：年繳 6,550 元、半年繳 3,280 元、"
                    "季繳 1,650 元、月繳 550 元。"
                ),
            },
        ]

        reply = compose_knowledge_reply(
            "大屯第四台一個月多少？",
            "",
            docs,
            llm=UnexpectedLLM(),
            answer_guard_query="大屯 有線電視 基本收視費 月繳",
            memory={"company_code": "tdtv"},
        )

        self.assertEqual(reply, "大屯有線電視基本收視費：月繳 $550 元。")
        self.assertNotIn("899", reply)


if __name__ == "__main__":
    unittest.main()
