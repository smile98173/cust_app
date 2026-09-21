import json
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

import pytest

from app.services import kb_admin_service
from app.services.kb_core import KBSearcher


class FakeSearcher:
    def __init__(self):
        self.records = []
        self.deleted = []
        self.delete_collection_calls = 0
        self.collection = "loaded"

    def upsert_records(self, records, delete_document_id=None):
        self.records = records
        self.deleted.append(delete_document_id)
        return len(records)

    def delete_by_document_id(self, document_id):
        self.deleted.append(document_id)

    def delete_collection(self):
        self.delete_collection_calls += 1
        self.records = []
        self.collection = None


class ResidualVectorCollection:
    def __init__(self):
        self.get_calls = []

    def get(self, where, limit=None):
        self.get_calls.append({"where": where, "limit": limit})
        return {"ids": ["stale-vector"]}


class ResidualVectorSearcher(FakeSearcher):
    def __init__(self):
        super().__init__()
        self.residual_collection = ResidualVectorCollection()
        self.collection = self.residual_collection


class RepairableSearcher:
    def __init__(self):
        self.calls = []
        self.delete_collection_calls = 0
        self.collection = "old"

    def upsert_records(self, records, delete_document_id=None):
        self.calls.append(delete_document_id)
        if len(self.calls) == 1:
            raise RuntimeError("Error in compaction: Error loading hnsw index")
        return len(records)

    def delete_collection(self):
        self.delete_collection_calls += 1


class FakeCollection:
    def __init__(self):
        self.upserts = []

    def upsert(self, ids, documents, metadatas):
        self.upserts.append({
            "ids": ids,
            "documents": documents,
            "metadatas": metadatas,
        })


class NotFoundError(Exception):
    pass


class CollectionDeletionClient:
    def __init__(self, delete_error=None, collection_still_exists=False):
        self.delete_error = delete_error
        self.collection_still_exists = collection_still_exists

    def delete_collection(self, name):
        if self.delete_error:
            raise self.delete_error

    def get_collection(self, name):
        if self.collection_still_exists:
            return object()
        raise NotFoundError(f"Collection [{name}] does not exist")


class ClosableClient:
    def __init__(self):
        self.closed = False

    def close(self):
        self.closed = True


def test_kb_searcher_preserves_line_breaks_in_metadata_for_display():
    searcher = KBSearcher.__new__(KBSearcher)
    searcher.collection = FakeCollection()
    searcher.create_or_load_collection = lambda: searcher.collection

    count = searcher.upsert_records([{
        "id": "doc-1-1",
        "document_id": "doc-1",
        "answer": "問題：\n世界盃足球賽哪一台可以看？\n回答：\n台視（CH07）",
    }])

    upsert = searcher.collection.upserts[0]
    assert count == 1
    assert "問題：\n世界盃足球賽哪一台可以看？" in upsert["metadatas"][0]["answer"]
    assert "問題： 世界盃足球賽哪一台可以看？" in upsert["documents"][0]


def test_kb_searcher_delete_collection_verifies_removal():
    searcher = KBSearcher.__new__(KBSearcher)
    searcher.client = CollectionDeletionClient()
    searcher.collection_name = "company_kb"
    searcher.collection = object()

    assert searcher.delete_collection() is True
    assert searcher.collection is None


def test_kb_searcher_delete_collection_raises_unexpected_storage_error():
    searcher = KBSearcher.__new__(KBSearcher)
    searcher.client = CollectionDeletionClient(delete_error=RuntimeError("disk failure"))
    searcher.collection_name = "company_kb"
    searcher.collection = object()

    with pytest.raises(RuntimeError, match="無法刪除 Chroma collection"):
        searcher.delete_collection()


def test_kb_searcher_delete_collection_rejects_false_success():
    searcher = KBSearcher.__new__(KBSearcher)
    searcher.client = CollectionDeletionClient(collection_still_exists=True)
    searcher.collection_name = "company_kb"
    searcher.collection = object()

    with pytest.raises(RuntimeError, match="仍可被讀取"):
        searcher.delete_collection()


def test_kb_searcher_close_releases_client_and_collection_handles():
    searcher = KBSearcher.__new__(KBSearcher)
    client = ClosableClient()
    searcher.client = client
    searcher.collection = object()

    searcher.close()

    assert client.closed is True
    assert searcher.client is None
    assert searcher.collection is None


def test_create_document_extracts_chunks_and_writes_manifest():
    with TemporaryDirectory() as tmp:
        docs_dir = Path(tmp) / "docs"
        manifest = docs_dir / "documents.json"
        fake = FakeSearcher()

        with patch.object(kb_admin_service, "RAG_LOCAL_DOCS_DIR", str(docs_dir)), \
                patch.object(kb_admin_service, "RAG_LOCAL_MANIFEST_PATH", str(manifest)), \
                patch.object(kb_admin_service, "load_searcher", return_value=fake) as load_searcher:
            doc = kb_admin_service.create_document(
                file_name="退租流程.txt",
                content="退租時請攜帶證件與設備到門市。".encode("utf-8"),
                title="退租流程",
                knowledge_base="大屯",
                category="billing",
                uploaded_by="Alice",
            )

        assert doc["processing_status"] == "indexed"
        assert doc["indexed_chunk_count"] == 1
        assert doc["uploaded_by"] == "Alice"
        assert doc["last_indexed_by"] == "Alice"
        assert doc["uploaded_at"]
        assert doc["last_indexed_at"]
        assert fake.records[0]["knowledge_base"] == "大屯"
        assert fake.records[0]["category"] == "billing"
        assert manifest.exists()


def test_reindex_document_updates_index_actor_without_changing_uploader():
    with TemporaryDirectory() as tmp:
        docs_dir = Path(tmp) / "docs"
        manifest = docs_dir / "documents.json"
        fake = FakeSearcher()

        with patch.object(kb_admin_service, "RAG_LOCAL_DOCS_DIR", str(docs_dir)), \
                patch.object(kb_admin_service, "RAG_LOCAL_MANIFEST_PATH", str(manifest)), \
                patch.object(kb_admin_service, "load_searcher", return_value=fake) as load_searcher:
            doc = kb_admin_service.create_document(
                file_name="退租流程.txt",
                content="退租時請攜帶證件與設備到門市。".encode("utf-8"),
                title="退租流程",
                knowledge_base="大屯",
                category="billing",
                uploaded_by="Alice",
            )
            reindexed = kb_admin_service.reindex_document(doc["id"], indexed_by="Bob")

        assert reindexed["uploaded_by"] == "Alice"
        assert reindexed["last_indexed_by"] == "Bob"
        assert reindexed["last_indexed_at"]


def test_delete_document_records_actor_and_time():
    with TemporaryDirectory() as tmp:
        docs_dir = Path(tmp) / "docs"
        manifest = docs_dir / "documents.json"
        fake = FakeSearcher()

        with patch.object(kb_admin_service, "RAG_LOCAL_DOCS_DIR", str(docs_dir)), \
                patch.object(kb_admin_service, "RAG_LOCAL_MANIFEST_PATH", str(manifest)), \
                patch.object(kb_admin_service, "load_searcher", return_value=fake), \
                patch.object(kb_admin_service, "delete_document_vectors_from_index"):
            doc = kb_admin_service.create_document(
                file_name="優惠方案.txt",
                content="優惠方案內容".encode("utf-8"),
                knowledge_base="大屯",
                uploaded_by="uploader",
            )
            deleted = kb_admin_service.delete_document(
                doc["id"],
                deleted_by="north-lead",
            )

        assert deleted["status"] == "deleted"
        assert deleted["deleted_by"] == "north-lead"
        assert deleted["deleted_at"]


def test_jsonl_import_uses_question_and_answer_text():
    with TemporaryDirectory() as tmp:
        path = Path(tmp) / "kb.jsonl"
        path.write_text(
            '{"question":"固定 IP 怎麼申請","answer":"請由客服協助申請固定 IP。"}\n',
            encoding="utf-8",
        )

        sections = kb_admin_service.extract_document_sections(path)

    assert sections[0]["content"] == "固定 IP 怎麼申請 請由客服協助申請固定 IP。"


def test_value_added_catalog_builds_independent_product_records():
    content = """各項單品銷售/加值服務
一、LINE TV：原價$210元/月。特價$600元/半年、$1200元/1年。
二、WIFI加值服務：皆為單顆之價格。
1、WIFI 5系列分享器：半年繳$150元或年繳$300元。
2、WIFI 6系列分享器：半年繳$300元或年繳$600元。
三、居家智慧攝影機：借用智慧鏡頭一顆，需綁約2年。特價$300元/半年、$600元/1年。
四、熊搭心：含電視電話、家庭相簿、生活提醒，3項服務。
1、瑪帛用戶：原價$49元/月，可免費使用電視電話功能。
2、瑪帛好友：原價$69元/月，半年繳$414元、年繳$828元。
3、瑪帛夥伴：原價$99元/月，半年繳$594元、年繳$1188元。
"""
    record = {
        "id": "value-added-catalog",
        "title": "各項單品銷售(加值服務)",
        "file_name": "各項單品銷售_加值服務_.docx",
        "knowledge_base": "通用-中區",
    }
    chunks = [{"content": content}]

    profile = kb_admin_service.build_value_added_product_profile(record, chunks)
    records = kb_admin_service.build_value_added_product_index_records(record, profile)

    assert profile["document_type"] == "product_service_catalog"
    product_records = [item for item in records if item["record_type"] == "product_service"]
    names = {item["product_name"] for item in product_records}
    assert {
        "LINE TV", "WiFi 加值服務", "WiFi 5 系列分享器",
        "WiFi 6 系列分享器", "居家智慧攝影機", "熊搭心",
        "瑪帛用戶", "瑪帛好友", "瑪帛夥伴",
    }.issubset(names)

    camera = next(item for item in product_records if item["product_name"] == "居家智慧攝影機")
    assert "特價$300元/半年" in camera["answer"]
    assert "LINE TV" not in camera["answer"]

    marpa_friend = next(item for item in product_records if item["product_name"] == "瑪帛好友")
    assert marpa_friend["product_parent"] == "熊搭心"
    assert "半年繳$414元" in marpa_friend["answer"]


def test_index_document_adds_value_added_product_metadata():
    with TemporaryDirectory() as tmp:
        path = Path(tmp) / "各項單品銷售_加值服務_.txt"
        path.write_text(
            "各項單品銷售/加值服務\n"
            "一、LINE TV：特價$600元/半年。\n"
            "二、居家智慧攝影機：特價$300元/半年。\n"
            "三、熊搭心：含電視電話、家庭相簿、生活提醒。\n",
            encoding="utf-8",
        )
        record = {
            "id": "value-added-index",
            "title": "各項單品銷售(加值服務)",
            "file_name": path.name,
            "file_path": str(path),
            "knowledge_base": "通用-中區",
            "category": "network_support",
        }
        fake = FakeSearcher()
        with patch.object(kb_admin_service, "load_searcher", return_value=fake), \
                patch.object(kb_admin_service, "reset_runtime_search_cache"), \
                patch.object(kb_admin_service, "backup_active_chroma_store_best_effort"), \
                patch.object(
                    kb_admin_service,
                    "upsert_document_record",
                    side_effect=lambda value: value,
                ):
            indexed = kb_admin_service.index_document(record, _lock_held=True)

    product_records = [item for item in fake.records if item.get("record_type") == "product_service"]
    assert indexed["product_service_index_count"] == len(product_records) + 1
    assert indexed["product_service_index_count"] == 4
    assert all(item["document_type"] == "product_service_catalog" for item in product_records)
    assert {item["product_name"] for item in product_records} == {
        "LINE TV", "居家智慧攝影機", "熊搭心",
    }


def test_value_added_profile_discovers_unconfigured_product_names_from_document_structure():
    record = {
        "id": "dynamic-product-catalog",
        "title": "各項單品銷售(加值服務)",
        "file_name": "新加值服務.docx",
        "knowledge_base": "通用-中區",
    }
    chunks = [{
        "content": (
            "各項單品銷售/加值服務\n"
            "一、安心雲管家：提供設備狀態提醒服務，月租 79 元。\n"
            "二、樂活守護包：提供生活提醒功能，半年繳 300 元。\n"
        ),
    }]

    profile = kb_admin_service.build_value_added_product_profile(record, chunks)

    assert profile["schema_version"] == "1.1"
    assert {product["name"] for product in profile["products"]} == {
        "安心雲管家", "樂活守護包",
    }


def test_txt_import_preserves_original_line_layout():
    with TemporaryDirectory() as tmp:
        path = Path(tmp) / "world_cup.txt"
        path.write_text(
            "問題：\n"
            "世界盃足球賽哪一台可以看？\n"
            "世足賽在哪個頻道播出？\n\n"
            "回答：\n"
            "2026 FIFA 世界盃足球賽轉播頻道如下：\n"
            "．台視（CH07）\n"
            "．東森新聞台（CH51）\n",
            encoding="utf-8",
        )

        sections = kb_admin_service.extract_document_sections(path)
        chunks = kb_admin_service.chunk_sections(sections)

    assert sections[0]["section_type"] == "text"
    assert "問題：\n世界盃足球賽哪一台可以看？" in chunks[0]["content"]
    assert "回答：\n2026 FIFA 世界盃足球賽轉播頻道如下：" in chunks[0]["content"]
    assert "．台視（CH07）\n．東森新聞台（CH51）" in chunks[0]["content"]


def test_txt_campaign_chunking_splits_summary_and_each_plan():
    sections = [{
        "content": (
            "方案名稱：好視成雙NO8 (電視+網路同裝方案)\n"
            "活動期間：115.06.10~115.08.31\n"
            "一、裝機費：免裝機費。\n"
            "二、網路設備押金：1000元，半年繳(含)以上免押，遺失/損壞賠償：數據機3,000元/台。\n"
            "三、繳別：月繳(需綁定循環扣款，首期需繳2個月)、半年繳、年繳。\n"
            "七、借用加值設備二擇一：WIFI或居家智慧攝影機，合約到期不收回。\n"
            "售價：\n"
            "500M/500M：月繳$999元、半年繳$5994元、年繳$11988元\n"
            "300M/300M：月繳$899元、半年繳$5394元、年繳$10788元\n"
            "方案一、500M/500M綁約36個月(3年)\n"
            "綁約36個月，違約金$10,000可逐月遞減。\n"
            "贈哈POINTS點數1,000點\n"
            "贈LINE TV會員半年\n"
            "贈家電二擇一：小冰箱或投影機\n"
            "方案二、500M/500M綁約48個月(4年)\n"
            "綁約48個月，違約金$18,000可逐月遞減。\n"
            "贈哈POINTS點數1,500點\n"
            "贈LINE TV會員半年\n"
            "贈家電二擇一：贈65吋電視或大冰箱\n"
        ),
        "page_no": None,
        "section": "document",
        "section_type": "text",
    }]

    chunks = kb_admin_service.chunk_sections(sections)

    assert len(chunks) == 3
    assert chunks[0]["content"].startswith("方案名稱：好視成雙NO8")
    assert "售價：" in chunks[0]["content"]
    assert "500M/500M：月繳$999元" in chunks[0]["content"]
    assert "方案一、500M/500M綁約36個月" not in chunks[0]["content"]
    assert chunks[1]["content"].startswith("方案一、500M/500M綁約36個月")
    assert "贈家電二擇一：小冰箱或投影機" in chunks[1]["content"]
    assert "方案二、500M/500M綁約48個月" not in chunks[1]["content"]
    assert chunks[2]["content"].startswith("方案二、500M/500M綁約48個月")
    assert "贈65吋電視或大冰箱" in chunks[2]["content"]


def test_campaign_index_adds_hidden_qa_records_for_short_queries():
    sections = [{
        "content": (
            "方案名稱：好視成雙NO8 (電視+網路同裝方案)\n"
            "活動期間：115.06.10~115.08.31\n"
            "一、裝機費：免裝機費。\n"
            "七、借用加值設備二擇一：WIFI或居家智慧攝影機，合約到期不收回。\n"
            "售價：\n"
            "500M/500M：月繳$999元、半年繳$5994元、年繳$11988元\n"
            "方案一、500M/500M綁約36個月(3年)\n"
            "綁約36個月，違約金$10,000可逐月遞減。\n"
            "贈哈POINTS點數1,000點\n"
            "贈LINE TV會員半年\n"
            "贈家電二擇一：小冰箱或投影機\n"
        ),
        "page_no": None,
        "section": "document",
        "section_type": "text",
    }]
    chunks = kb_admin_service.chunk_sections(sections)
    record = {
        "id": "doc-1",
        "title": "好視成雙",
        "file_name": "好視成雙NO8.docx",
        "knowledge_base": "大屯",
    }

    qa_records = kb_admin_service.build_qa_index_records(record, chunks, "billing")
    questions = [record["question"] for record in qa_records]

    assert qa_records
    assert all(record["record_type"] == "qa" for record in qa_records)
    assert any("推薦優惠方案" in question for question in questions)
    assert any("贈品" in question and "POINTS" in question and "LINE TV" in question for question in questions)
    assert any("WiFi" in question and "月租50元" in question and "只付一個月" in question for question in questions)
    assert any("小冰箱或投影機" in record["answer"] for record in qa_records)


def test_qa_index_does_not_add_generic_questions_to_csv_faq_rows():
    record = {
        "id": "settop-faq",
        "title": "機上盒",
        "file_name": "機上盒.csv",
        "knowledge_base": "通用-中區",
    }
    chunks = [{
        "question": "機上盒出現E004授權到期",
        "content": "請先確認收視繳費是否尚未繳納。",
        "section": "row 31",
        "page_no": None,
    }]

    qa_records = kb_admin_service.build_qa_index_records(record, chunks, "billing")

    assert qa_records == []


def test_campaign_profile_normalizes_mixed_field_order_without_fixed_template():
    chunks = [
        {
            "content": (
                "星耀暢網年度回饋專案\n"
                "500M/500M：月繳 999 元，半年繳 5,994 元。\n"
                "舊戶合約到期可申請，須重新綁約 36 個月。\n"
                "活動期間：2026/08/01 至 2026/10/31\n"
                "贈品為 POINTS 1,000 點，可借用 WiFi 設備。"
            ),
            "section": "document",
            "page_no": None,
        }
    ]
    record = {
        "id": "campaign-new",
        "title": "星耀暢網年度回饋專案",
        "file_name": "星耀暢網_客服版.docx",
        "knowledge_base": "大屯",
    }

    profile = kb_admin_service.build_campaign_profile(record, chunks)

    assert profile["document_type"] == "promotion_campaign"
    assert profile["campaign_name"] == "星耀暢網年度回饋專案"
    assert "星耀暢網年度回饋專案" in profile["aliases"]
    assert profile["speeds"] == ["500M/500M"]
    assert profile["contract_months"] == [36]
    assert "月繳" in profile["payment_terms"]
    assert "半年繳" in profile["payment_terms"]
    assert "舊戶" in profile["customer_types"]
    assert profile["valid_period"] == "2026/08/01 至 2026/10/31"
    assert profile["validation"]["status"] == "complete"


def test_campaign_profile_indexes_holiday_gifts_and_lottery_without_activity_code():
    content = (
        "方案名稱：爸氣獻禮好康活動\n"
        "活動期間：2026/08/01 至 2026/08/31\n"
        "300M/300M 月繳899元，綁約24個月。\n"
        "申裝即贈智慧音箱或氣炸鍋二擇一。\n"
        "活動期間完成申裝可參加抽獎，獎項為65吋電視；抽獎日期為2026/09/10。\n"
        "新戶與合約到期舊戶皆可申請。"
    )
    chunks = [{"content": content, "section": "document", "page_no": None}]
    record = {
        "id": "father-day-campaign",
        "title": "爸氣獻禮好康活動",
        "file_name": "爸氣獻禮好康活動.docx",
        "knowledge_base": "大屯",
    }

    profile = kb_admin_service.build_campaign_profile(record, chunks)
    semantic_records = kb_admin_service.build_campaign_index_records(
        record, chunks, "billing", profile
    )
    qa_questions = [
        item["question"]
        for item in kb_admin_service.build_qa_index_records(record, chunks, "billing")
    ]

    assert profile["document_type"] == "promotion_campaign"
    assert "父親節" in profile["occasion_terms"]
    assert "爸氣" in profile["occasion_terms"]
    assert any("智慧音箱" in item and "氣炸鍋" in item for item in profile["gift_items"])
    assert any("抽獎" in item and "65吋電視" in item for item in profile["lottery_details"])
    assert "gift" in profile["section_types"]
    assert "lottery" in profile["section_types"]
    assert "父親節" in semantic_records[0]["occasion_terms"]
    assert "智慧音箱" in semantic_records[0]["gift_items"]
    assert "65吋電視" in semantic_records[0]["lottery_details"]
    assert "活動代碼" not in semantic_records[0]["question"]
    assert any("父親節" in question and "節慶" in question for question in qa_questions)
    assert any("送什麼" in question and "智慧音箱" in question for question in qa_questions)
    assert any("抽獎資格" in question and "65吋電視" in question for question in qa_questions)


def test_campaign_profile_removes_numbered_prefixes_from_speeds_and_ignores_deposit_months():
    chunks = [{
        "content": (
            "方案名稱：哈NET1一般寬頻方案\n"
            "1. 60M/6M：月繳500元\n"
            "2、100M/10M：月繳600元\n"
            "--3.300M/300M：月繳900元\n"
            "首期需繳2個月費用。\n"
            "月繳用戶綁約一年；半年繳用戶綁約半年。"
        ),
        "section": "document",
    }]
    record = {
        "title": "一般寬頻方案哈NET1",
        "file_name": "一般寬頻方案哈NET1.docx",
        "knowledge_base": "大屯",
    }

    profile = kb_admin_service.build_campaign_profile(record, chunks)

    assert profile["speeds"] == ["60M/6M", "100M/10M", "300M/300M"]
    assert profile["contract_months"] == [12, 6]
    assert 2 not in profile["contract_months"]


def test_campaign_profile_does_not_classify_broad_reference_documents_from_incidental_plan_text():
    cases = [
        {
            "title": "機上盒",
            "file_name": "機上盒.csv",
            "content": "機上盒押金與分機費說明。\n其他問題：好視成雙NO8方案可借用機上盒。",
        },
        {
            "title": "台灣佳光_TV_基本收費標準11507",
            "file_name": "台灣佳光_TV_基本收費標準11507.docx",
            "content": "有線電視基本收費標準。\n附註：部分優惠方案依活動期間另行公告。",
        },
        {
            "title": "加值服務",
            "file_name": "加值服務.csv",
            "content": "問題：LINE TV 如何加購？\n答案：依目前活動方案與帳戶資格確認。",
        },
    ]

    for case in cases:
        profile = kb_admin_service.build_campaign_profile(
            {
                "title": case["title"],
                "file_name": case["file_name"],
                "knowledge_base": "通用-中區",
            },
            [{"content": case["content"], "section": "document"}],
        )
        assert profile == {}, case["title"]


def test_campaign_semantic_records_keep_original_answer_and_structured_metadata():
    chunks = [
        {
            "content": (
                "方案名稱：星耀暢網 X7\n"
                "方案A、300M/300M 綁約24個月\n"
                "月繳899元，贈LINE TV半年。"
            ),
            "section": "paragraph 1",
            "page_no": None,
        }
    ]
    record = {
        "id": "campaign-x7",
        "title": "星耀暢網",
        "file_name": "星耀暢網X7.docx",
        "knowledge_base": "大屯",
    }
    profile = kb_admin_service.build_campaign_profile(record, chunks)

    records = kb_admin_service.build_campaign_index_records(
        record,
        chunks,
        "billing",
        profile,
    )

    assert len(records) == 1
    assert records[0]["record_type"] == "campaign_variant"
    assert records[0]["document_type"] == "promotion_campaign"
    assert records[0]["campaign_name"] == "星耀暢網 X7"
    assert records[0]["speeds"] == "300M/300M"
    assert records[0]["contract_months"] == "24"
    assert "月繳899元，贈LINE TV半年。" in records[0]["answer"]
    assert "優惠內容" in records[0]["question"]


def test_social_discount_qa_does_not_create_generic_promotion_question():
    content = (
        "【方案名稱】 低收入戶優惠方案\n"
        "【適用對象】 持有有效低收入戶證明之客戶。\n"
        "【申請方式】 客戶需親自至門市臨櫃辦理申請。\n"
        "【優惠內容】 裝機費優惠後收費金額：0元，電視收視服務費優惠期間：12個月。"
    )

    questions = kb_admin_service.build_qa_questions_for_chunk(content, "低收入_身心障礙優惠報價AI版")

    assert any("低收入" in question and "申請方式" in question for question in questions)
    assert all("推薦優惠方案" not in question for question in questions)


def test_pdf_chunking_splits_page_into_smaller_semantic_blocks():
    sections = [{
        "content": (
            "300M/300M 拆帳表\n"
            "月繳 $540 $359 $899\n"
            "半年繳 $3,240 $2,154 $5,394\n"
            "家電配送及保固說明\n"
            "1.電視、冰箱\n"
            "o 提供 3 年保固。\n"
            "o 申請後 5 個工作天內，將由專人主動聯繫，並依約定時間安排配送。\n"
            "o 電視無壁掛架及安裝壁架服務，若客戶有需求，請專人電聯時主動告知廠商，由廠商另行報價。\n"
            "2.投影機\n"
            "o 提供 1 年保固。\n"
        ),
        "page_no": 3,
        "section": "page 3",
    }]

    chunks = kb_admin_service.chunk_sections(sections)

    assert len(chunks) >= 3
    wall_mount_chunks = [
        chunk for chunk in chunks
        if "壁掛架" in chunk["content"] or "安裝壁架" in chunk["content"]
    ]
    assert wall_mount_chunks
    assert "家電配送及保固說明" in wall_mount_chunks[0]["content"]
    assert "月繳 $540" not in wall_mount_chunks[0]["content"]
    assert wall_mount_chunks[0]["section"].startswith("page 3 block")


def test_pdf_page_text_prefers_layout_extraction_and_preserves_lines():
    class FakePage:
        def __init__(self):
            self.calls = []

        def extract_text(self, **kwargs):
            self.calls.append(kwargs)
            return "第一段\n第二段\n"

    page = FakePage()

    text = kb_admin_service.extract_pdf_page_text(page)

    assert page.calls[0]["extraction_mode"] == "layout"
    assert text == "第一段\n第二段"


def test_pdf_chunks_preserve_line_breaks_in_content():
    sections = [{
        "content": (
            "家電配送及保固說明\n"
            "1.電視、冰箱\n"
            "o 提供 3 年保固。\n"
            "o 電視無壁掛架及安裝壁架服務。\n"
        ),
        "page_no": 3,
        "section": "page 3",
    }]

    chunks = kb_admin_service.chunk_sections(sections)
    wall_mount_chunk = next(chunk for chunk in chunks if "壁掛架" in chunk["content"])

    assert "\n" in wall_mount_chunk["content"]
    assert wall_mount_chunk["content"].splitlines()[0] == "家電配送及保固說明"


def test_pdf_chunking_splits_form_style_campaign_fields():
    sections = [
        {
            "content": (
                "方案名稱：飆網守護家_(B2606)\n"
                "說明\n"
                "活動期間：2026/06/05~2026/9/30\n"
                "裝機費： ■ 無 □ 有 金額：0\n"
                "寬頻設備押金： ■ 無 □ 有 金額：0 遺失/損壞賠償：CM、EP：賠償 2,000。ONU：賠償$3,000 元\n"
                "機上盒借用： □無 ■ 有 4K 雙模機 用戶預設類別： 類有線。賠償$3,000 元\n"
                "繳別： □ 月繳(需收 2 個月) ■ 季繳 ■ 半年繳 ■年繳 最低季繳\n"
                "綁約： ■ 是 □ 否 綁約期限：24 個月\n"
                "違約金： 補收新台幣 2,400 元為基準計算剩月份按比例扣減之方式返還專案贈與金\n"
                "舊戶是否可參加： ■ 是 □ 否\n"
                "申裝條件：1.合約已到期\n"
                "2.結清違約金+前帳\n"
                "中途換約或升級： ■ 可 □ 否 需重新綁約，同方案升速補齊價差\n"
                "----------------------------------------------------------------\n"
                "客服報價/派工方案注意事項\n"
                "客新裝【飆網守護家(B2606)；綁約 24 個月；300M/300M；半年繳】\n"
                "用戶若需停用服務需自行提前進電告知不續用，退租設備均需歸還公司。\n"
            ),
            "page_no": 1,
            "section": "page 1",
        },
        {
            "content": (
                "飆網守護家三合一_(B2606)：\n"
                "配合速率\n"
                "牌價\n"
                "拆帳表\n"
                "100M 100M 或 10M 600 399 0 2,394 0 2,394\n"
                "300M 300M 1,000 599 0 3,594 0 3,594\n"
                "500M 500M 1,100 699 0 4,194 0 4,194\n"
                "下述頻寬不推，特殊需求須請示主管同意後方可派工裝機 (AI 禁止報價)\n"
                "60M 6M 500 299 0 1,794 0 1,794\n"
                "1G 1G 1,700 1,199 0 7,194 0 7,194\n"
            ),
            "page_no": 2,
            "section": "page 2",
        },
    ]

    chunks = kb_admin_service.chunk_sections(sections)

    assert len(chunks) == 3
    assert "方案名稱：飆網守護家_(B2606)" in chunks[0]["content"]
    assert "活動期間：2026/06/05~2026/9/30" in chunks[0]["content"]
    assert "裝機費" in chunks[0]["content"]
    assert "違約金" in chunks[0]["content"]
    assert "客服報價/派工方案注意事項" in chunks[1]["content"]
    forbidden_quote_chunks = [chunk for chunk in chunks if "AI 禁止報價" in chunk["content"]]
    assert forbidden_quote_chunks
    assert "100M" in forbidden_quote_chunks[0]["content"]
    assert "300M" in forbidden_quote_chunks[0]["content"]
    assert "500M" in forbidden_quote_chunks[0]["content"]
    assert "60M" in forbidden_quote_chunks[0]["content"]
    assert "1G" in forbidden_quote_chunks[0]["content"]
    assert all(chunk["section"].startswith("page ") for chunk in chunks)


def test_pdf_chunking_keeps_campaign_plan_items_together():
    sections = [{
        "content": (
            "方案一、500M/500M綁約36個月(3 年)\n"
            "1、 綁約36個月，違約金$10,000可逐月遞減。\n"
            "2、 贈哈POINTS點數1,000 點\n"
            "3、 贈LINE TV會員半年\n"
            "4、 贈家電二擇一：小冰箱或投影機\n"
            "方案二、500M/500M綁約48個月(4 年)\n"
            "1、 綁約48個月，違約金$18,000可逐月遞減。\n"
            "2、 贈哈POINTS點數1,500 點\n"
            "3、 贈LINE TV會員半年\n"
            "4、 贈家電二擇一：贈65 吋電視或大冰箱\n"
        ),
        "page_no": 2,
        "section": "page 2",
    }]

    chunks = kb_admin_service.chunk_sections(sections)

    assert len(chunks) == 2
    assert "方案一、500M/500M綁約36個月" in chunks[0]["content"]
    assert "1、 綁約36個月" in chunks[0]["content"]
    assert "4、 贈家電二擇一：小冰箱或投影機" in chunks[0]["content"]
    assert "方案二、500M/500M綁約48個月" not in chunks[0]["content"]
    assert "方案二、500M/500M綁約48個月" in chunks[1]["content"]
    assert "4、 贈家電二擇一：贈65 吋電視或大冰箱" in chunks[1]["content"]


def test_pdf_chunking_keeps_campaign_rate_table_separate_from_plans():
    sections = [{
        "content": (
            "方案一、500M/500M綁約36個月(3 年)\n"
            "1、 綁約36個月，違約金$10,000可逐月遞減。\n"
            "2、 贈哈POINTS點數1,000 點\n"
            "500M500M拆帳表\n"
            "頻寬 繳別 CATV BB 合計\n"
            "月繳 $540 $459 $999\n"
            "500M/500M 半年繳 $3,240 $2,754 $5,994\n"
            "方案二、300M/300M綁約36個月(3 年)\n"
            "1、 綁約36個月，違約金$10,000可逐月遞減。\n"
            "2、 贈哈POINTS點數500點\n"
        ),
        "page_no": 2,
        "section": "page 2",
    }]

    chunks = kb_admin_service.chunk_sections(sections)

    assert len(chunks) == 3
    assert chunks[0]["content"].startswith("方案一、500M/500M")
    assert chunks[1]["content"].startswith("500M500M拆帳表")
    assert "月繳 $540 $459 $999" in chunks[1]["content"]
    assert chunks[2]["content"].startswith("方案二、300M/300M")


def test_pdf_chunking_merges_campaign_plan_items_across_pages():
    sections = [
        {
            "content": (
                "方案四、300M/300M 綁約48個月(4 年)\n"
                "1、 綁約48個月，違約金$10,000可逐月遞減。\n"
            ),
            "page_no": 2,
            "section": "page 2",
        },
        {
            "content": (
                "2、 贈哈POINTS點數1,000 點\n"
                "3、 贈LINE TV會員半年\n"
                "4、 贈家電二擇一：小冰箱或投影機\n"
                "300M/300M拆帳表\n"
                "月繳 $540 $359 $899\n"
            ),
            "page_no": 3,
            "section": "page 3",
        },
    ]

    chunks = kb_admin_service.chunk_sections(sections)

    assert "方案四、300M/300M 綁約48個月" in chunks[0]["content"]
    assert "2、 贈哈POINTS點數1,000 點" in chunks[0]["content"]
    assert "4、 贈家電二擇一：小冰箱或投影機" in chunks[0]["content"]
    assert chunks[1]["content"].startswith("300M/300M拆帳表")


def test_pdf_chunking_merges_dispatch_note_continuation_across_pages():
    sections = [
        {
            "content": (
                "月繳 派工備註範例：\n"
                "約X/X上午，去電09XX-XXXXXX，新裝-好視成雙 NO8-500M/500M月繳，"
                "方案包含 TV+BB+LINETV半年+LITV半年，LINETV到期恢復原\n"
            ),
            "page_no": 3,
            "section": "page 3",
        },
        {
            "content": (
                "價、LITV到期停止授權，收費完工收$1988+押金1000 共收2988 元，簽合約並上傳雙證件至 APP\n"
                "年繳 派工備註範例：\n"
                "約X/X上午，去電09XX-XXXXXX，新裝-好視成雙 NO8-500M/500M年繳。\n"
            ),
            "page_no": 4,
            "section": "page 4",
        },
    ]

    chunks = kb_admin_service.chunk_sections(sections)

    assert "LINETV到期恢復原\n價、LITV到期停止授權" in chunks[0]["content"]
    assert chunks[1]["content"].startswith("年繳 派工備註範例")


def test_pdf_chunking_keeps_colon_plan_name_numbered_lines_together():
    sections = [{
        "content": (
            "一般寬頻方案\n"
            "方案名稱：哈 NET1\n"
            "1、裝機費： 500 元\n"
            "2、數據機設備押金： 1000 元，如客戶採用半年繳 (含)以上免押金。\n"
            "3、綁約條件：月繳、年繳用戶綁約一年；半年繳用戶綁約半年\n"
            "4、違約：提前解約需支付違約金 1,500 元，可逐月遞減。\n"
            "5、採用月繳用戶，首次付款需支付 2 個月費用。\n"
            "6、頻寬繳別售價如下：\n"
            "A.60M/6M：月繳 $500 元、半年繳 $3,000、年繳 $6,000。\n"
            "B.100M/10M：月繳 $600 元、半年繳 $3,600、年繳 $7,200。\n"
            "C.200M/200M：月繳 $800 元、半年繳 $4,800、年繳 $9,600。\n"
            "D.300M/300M：月繳 $900 元、半年繳 $5,400、年繳 $10,800。\n"
            "7、客如有租借 WIFI 需求，可加價租借，每月月租 50 元。\n"
        ),
        "page_no": 1,
        "section": "page 1",
    }]

    chunks = kb_admin_service.chunk_sections(sections)

    assert len(chunks) == 1
    assert "一般寬頻方案" in chunks[0]["content"]
    assert "方案名稱：哈 NET1" in chunks[0]["content"]
    assert "1、裝機費： 500 元" in chunks[0]["content"]
    assert "6、頻寬繳別售價如下：" in chunks[0]["content"]
    assert "A.60M/6M：月繳 $500 元" in chunks[0]["content"]
    assert "D.300M/300M：月繳 $900 元" in chunks[0]["content"]
    assert "7、客如有租借 WIFI 需求" in chunks[0]["content"]


def test_docx_chunking_splits_numbered_policy_sections():
    sections = [{
        "content": (
            "「大屯有線電視基本收費標準」 一、TV 裝機費與行政規費 大屯有線電視之裝機費用依客戶選擇的繳別而有不同優惠標準。"
            " 二、TV 收視費（月費）標準 以下為大屯有線電視各繳別之銷售終端價格。"
            " 三、移機費與分機費 移機與分機費用依施工性質及是否與主機同裝而異。"
            " 四、加值服務與設備賠償 平台費與設備遺失損壞賠償標準。"
            " 五、其他重要規範 分機施工原則與設備借用上限。"
        ),
        "page_no": None,
        "section": "paragraph 1",
        "section_type": "docx",
    }]

    chunks = kb_admin_service.chunk_sections(sections)

    assert len(chunks) >= 5
    assert any(chunk["content"].startswith("一、TV 裝機費") for chunk in chunks)
    assert any(chunk["content"].startswith("二、TV 收視費") for chunk in chunks)
    assert any(chunk["content"].startswith("三、移機費") for chunk in chunks)
    assert not any("一、TV 裝機費" in chunk["content"] and "五、其他重要規範" in chunk["content"] for chunk in chunks)


def test_docx_chunking_splits_discount_plan_labels_and_keeps_plan_context():
    sections = [{
        "content": (
            "【方案名稱】 低收入戶優惠方案 【適用對象】 持有有效低收入戶證明之客戶。"
            "【申請方式】 客戶需親自至門市臨櫃辦理申請。"
            "【優惠內容】 項目1：裝機費優惠後收費金額：0元。項目2：電視收視服務費優惠期間：12個月。"
            "【限制條件】 僅適用符合資格之客戶，每年須重新申請。"
            "------------------------------------------------"
            "【方案名稱】 中低收入戶優惠方案 【適用對象】 持有有效中低收入戶證明之客戶。"
            "【優惠內容】 項目1：裝機費優惠後收費金額：600元。項目2：收視服務費優惠後收費金額：3280元／年。"
        ),
        "page_no": None,
        "section": "paragraph 1",
        "section_type": "docx",
    }]

    chunks = kb_admin_service.chunk_sections(sections)

    assert len(chunks) == 2
    low_income_discount = [
        chunk for chunk in chunks
        if "電視收視服務費優惠期間" in chunk["content"]
    ]
    assert low_income_discount
    assert "【方案名稱】 低收入戶優惠方案" in low_income_discount[0]["content"]
    assert "【適用對象】 持有有效低收入戶證明之客戶。" in low_income_discount[0]["content"]
    assert "【申請方式】 客戶需親自至門市臨櫃辦理申請。" in low_income_discount[0]["content"]
    assert "【限制條件】 僅適用符合資格之客戶，每年須重新申請。" in low_income_discount[0]["content"]
    mid_income_discount = [
        chunk for chunk in chunks
        if "3280元／年" in chunk["content"]
    ]
    assert mid_income_discount
    assert "【方案名稱】 中低收入戶優惠方案" in mid_income_discount[0]["content"]


def test_docx_chunking_keeps_colon_plan_name_numbered_lines_together():
    sections = [{
        "content": (
            "一般寬頻方案\n"
            "方案名稱：哈 NET1\n"
            "1、裝機費：500 元\n"
            "2、數據機設備押金：1000 元，如客戶採用半年繳(含)以上免押金。\n"
            "3、綁約條件：月繳、年繳用戶綁約一年；半年繳用戶綁約半年\n"
            "4、違約：提前解約需支付違約金 1,500 元，可逐月遞減。\n"
            "5、採用月繳用戶，首次付款需支付 2 個月費用。\n"
            "6、頻寬繳別售價如下：\n"
            "A.60M/6M：月繳$500 元、半年繳$3,000、年繳$6,000。\n"
            "B.100M/10M：月繳$600 元、半年繳$3,600、年繳$7,200。\n"
            "C.200M/200M：月繳$800 元、半年繳$4,800、年繳$9,600。\n"
            "D.300M/300M：月繳$900 元、半年繳$5,400、年繳$10,800。\n"
        ),
        "page_no": None,
        "section": "paragraph 1",
        "section_type": "docx",
    }]

    chunks = kb_admin_service.chunk_sections(sections)

    assert len(chunks) == 1
    assert "方案名稱：哈 NET1" in chunks[0]["content"]
    assert "1、裝機費：500 元" in chunks[0]["content"]
    assert "6、頻寬繳別售價如下：" in chunks[0]["content"]
    assert "A.60M/6M：月繳$500 元" in chunks[0]["content"]
    assert "D.300M/300M：月繳$900 元" in chunks[0]["content"]


def test_docx_campaign_chunking_splits_summary_and_each_plan():
    sections = [{
        "content": (
            "方案名稱：好視成雙NO8 (電視+網路同裝方案)\n"
            "活動期間：115.06.10~115.08.31\n"
            "一、裝機費：免裝機費。\n"
            "二、網路設備押金：1000元，半年繳(含)以上免押，遺失/損壞賠償：數據機3,000元/台。\n"
            "三、繳別：月繳(需綁定循環扣款，首期需繳2個月)、半年繳、年繳。\n"
            "售價：\n"
            "500M/500M：月繳$999元、半年繳$5994元、年繳$11988元\n"
            "300M/300M：月繳$899元、半年繳$5394元、年繳$10788元\n"
            "方案一、500M/500M綁約36個月(3年)\n"
            "綁約36個月，違約金$10,000可逐月遞減。\n"
            "贈哈POINTS點數1,000點\n"
            "贈LINE TV會員半年\n"
            "贈家電二擇一：小冰箱或投影機\n"
            "方案二、500M/500M綁約48個月(4年)\n"
            "綁約48個月，違約金$18,000可逐月遞減。\n"
            "贈哈POINTS點數1,500點\n"
            "贈LINE TV會員半年\n"
            "贈家電二擇一：贈65吋電視或大冰箱\n"
        ),
        "page_no": None,
        "section": "paragraphs 1-54",
        "section_type": "docx",
    }]

    chunks = kb_admin_service.chunk_sections(sections)

    assert len(chunks) == 3
    assert chunks[0]["content"].startswith("方案名稱：好視成雙NO8")
    assert "售價：" in chunks[0]["content"]
    assert "方案一、500M/500M綁約36個月" not in chunks[0]["content"]
    assert chunks[1]["content"].startswith("方案一、500M/500M綁約36個月")
    assert "贈家電二擇一：小冰箱或投影機" in chunks[1]["content"]
    assert chunks[2]["content"].startswith("方案二、500M/500M綁約48個月")
    assert "贈65吋電視或大冰箱" in chunks[2]["content"]


def test_docx_chunking_merges_paragraph_sections_before_splitting_plans():
    sections = [
        {
            "content": "【方案名稱】\n低收入戶優惠方案",
            "page_no": None,
            "section": "paragraph 1",
            "section_type": "docx",
        },
        {
            "content": "【適用對象】\n持有有效低收入戶證明之客戶。",
            "page_no": None,
            "section": "paragraph 2",
            "section_type": "docx",
        },
        {
            "content": "【申請方式】\n客戶需親自至門市臨櫃辦理申請。",
            "page_no": None,
            "section": "paragraph 3",
            "section_type": "docx",
        },
        {
            "content": "【優惠內容】\n電視收視服務費優惠後收費金額：0元／年。",
            "page_no": None,
            "section": "paragraph 4",
            "section_type": "docx",
        },
        {
            "content": "【方案名稱】\n中低收入戶優惠方案",
            "page_no": None,
            "section": "paragraph 5",
            "section_type": "docx",
        },
        {
            "content": "【優惠內容】\n收視服務費優惠後收費金額：3280元／年。",
            "page_no": None,
            "section": "paragraph 6",
            "section_type": "docx",
        },
    ]

    chunks = kb_admin_service.chunk_sections(sections)

    assert len(chunks) == 2
    assert "【方案名稱】\n低收入戶優惠方案" in chunks[0]["content"]
    assert "【適用對象】\n持有有效低收入戶證明之客戶。" in chunks[0]["content"]
    assert "【申請方式】\n客戶需親自至門市臨櫃辦理申請。" in chunks[0]["content"]
    assert "【優惠內容】\n電視收視服務費優惠後收費金額：0元／年。" in chunks[0]["content"]
    assert "【方案名稱】\n中低收入戶優惠方案" in chunks[1]["content"]
    assert "3280元／年" in chunks[1]["content"]


def test_docx_table_sections_group_hatv_package_rows():
    table_rows = [
        (1, ["哈TV-A套餐 (原價1250元/月)", "哈TV-A套餐 (原價1250元/月)"]),
        (2, ["CH", "頻道名稱", "原價格"]),
        (3, ["1", "200", "Discovery Asia", "100元/月"]),
        (4, ["2", "201", "Discovery科學頻道", "100元/月"]),
        (5, ["哈TV-B套餐 (原價700元/月)"]),
        (6, ["1", "202", "DMAX", "100元/月"]),
    ]

    sections = kb_admin_service.build_docx_table_sections(table_rows, table_index=1)
    chunks = kb_admin_service.chunk_sections(sections)

    assert len(chunks) == 2
    assert chunks[0]["section"] == "table 1 哈TV-A套餐 rows 1-4"
    assert chunks[0]["content"].startswith("哈TV-A套餐 (原價1250元/月)\nCH | 頻道名稱 | 原價格")
    assert "Discovery Asia" in chunks[0]["content"]
    assert "Discovery科學頻道" in chunks[0]["content"]
    assert "哈TV-B套餐" not in chunks[0]["content"]
    assert chunks[1]["section"] == "table 1 哈TV-B套餐 rows 5-6"
    assert "DMAX" in chunks[1]["content"]


def test_docx_table_sections_keep_plain_table_as_single_block():
    table_rows = [
        (2, ["CH", "頻道名稱", "原價格"]),
        (3, ["1", "200", "Discovery Asia", "100元/月"]),
        (4, ["2", "201", "Discovery科學頻道", "100元/月"]),
    ]

    sections = kb_admin_service.build_docx_table_sections(table_rows, table_index=1)
    chunks = kb_admin_service.chunk_sections(sections)

    assert len(chunks) == 1
    assert chunks[0]["section"] == "table 1 rows 2-4"
    assert "CH | 頻道名稱 | 原價格" in chunks[0]["content"]
    assert "1 | 200 | Discovery Asia | 100元/月" in chunks[0]["content"]
    assert "2 | 201 | Discovery科學頻道 | 100元/月" in chunks[0]["content"]


def test_create_document_auto_infers_category_when_not_provided():
    with TemporaryDirectory() as tmp:
        docs_dir = Path(tmp) / "docs"
        manifest = docs_dir / "documents.json"
        fake = FakeSearcher()

        with patch.object(kb_admin_service, "RAG_LOCAL_DOCS_DIR", str(docs_dir)), \
                patch.object(kb_admin_service, "RAG_LOCAL_MANIFEST_PATH", str(manifest)), \
                patch.object(kb_admin_service, "load_searcher", return_value=fake):
            doc = kb_admin_service.create_document(
                file_name="固定IP申請流程.txt",
                content="固定 IP 申請需要由客服協助確認客戶寬頻狀態。".encode("utf-8"),
                title="固定 IP 申請流程",
                knowledge_base="通用",
                category=None,
            )

        assert doc["processing_status"] == "indexed"
        assert doc["category"] == "network_support"
        assert fake.records[0]["category"] == "network_support"


def test_csv_import_preserves_question_answer_company_fields():
    with TemporaryDirectory() as tmp:
        docs_dir = Path(tmp) / "docs"
        manifest = docs_dir / "documents.json"
        fake = FakeSearcher()

        with patch.object(kb_admin_service, "RAG_LOCAL_DOCS_DIR", str(docs_dir)), \
                patch.object(kb_admin_service, "RAG_LOCAL_MANIFEST_PATH", str(manifest)), \
                patch.object(kb_admin_service, "load_searcher", return_value=fake):
            doc = kb_admin_service.create_document(
                file_name="移機費用.csv",
                content=(
                    "question,answer,company\n"
                    "電視移機,移機分室內或室外移機，室內 500 元、室外 800 元。,共用\n"
                ).encode("utf-8"),
                title="機上盒",
                knowledge_base="通用",
                category=None,
            )

    assert doc["processing_status"] == "indexed"
    assert fake.records[0]["question"] == "電視移機"
    assert fake.records[0]["answer"] == "移機分室內或室外移機，室內 500 元、室外 800 元。"
    assert fake.records[0]["company"] == "共用"
    assert "question:" not in fake.records[0]["answer"]
    assert "answer:" not in fake.records[0]["answer"]


def test_create_document_stops_single_write_when_hnsw_index_is_corrupted():
    with TemporaryDirectory() as tmp:
        docs_dir = Path(tmp) / "docs"
        manifest = docs_dir / "documents.json"
        fake = RepairableSearcher()

        with patch.object(kb_admin_service, "RAG_LOCAL_DOCS_DIR", str(docs_dir)), \
                patch.object(kb_admin_service, "RAG_LOCAL_MANIFEST_PATH", str(manifest)), \
                patch.object(kb_admin_service, "load_searcher", return_value=fake):
            doc = kb_admin_service.create_document(
                file_name="移機費用.csv",
                content="question,answer,company\n室內移機費用,室內 500元 室外800元,共用\n".encode("utf-8"),
                title="移機費用",
                knowledge_base="通用",
                category=None,
            )

        assert doc["processing_status"] == "failed"
        assert "必須完整重建索引" in doc["processing_error"]
        assert doc["processing_error_stage"] == "write_vectors"
        assert doc["processing_error_type"] == "RuntimeError"
        assert fake.delete_collection_calls == 0
        assert fake.calls == [doc["id"]]
        assert fake.collection == "old"


def test_archive_corrupted_chroma_store_replaces_physical_directory():
    with TemporaryDirectory() as tmp:
        persist_dir = Path(tmp) / "chroma_db"
        persist_dir.mkdir()
        broken_segment = persist_dir / "broken-hnsw.bin"
        broken_segment.write_bytes(b"broken")

        with patch.object(kb_admin_service, "RAG_LOCAL_PERSIST_DIR", str(persist_dir)), \
                patch.object(kb_admin_service, "release_chroma_runtime_handles"):
            backup_dir = kb_admin_service.archive_corrupted_chroma_store()

        assert backup_dir is not None
        assert backup_dir.exists()
        assert (backup_dir / "broken-hnsw.bin").read_bytes() == b"broken"
        assert persist_dir.exists()
        assert list(persist_dir.iterdir()) == []


def test_backup_active_chroma_store_creates_sibling_backup():
    with TemporaryDirectory() as tmp:
        runtime_dir = Path(tmp)
        persist_dir = runtime_dir / "chroma_db"
        docs_dir = runtime_dir / "kb_documents"
        segment_dir = persist_dir / "segment-1"
        segment_dir.mkdir(parents=True)
        docs_dir.mkdir()
        (persist_dir / "chroma.sqlite3").write_bytes(b"sqlite")
        (segment_dir / "header.bin").write_bytes(b"header")

        with patch.object(kb_admin_service, "RAG_LOCAL_PERSIST_DIR", str(persist_dir)), \
                patch.object(kb_admin_service, "RAG_LOCAL_DOCS_DIR", str(docs_dir)), \
                patch.object(kb_admin_service, "release_chroma_runtime_handles"):
            summary = kb_admin_service.backup_active_chroma_store(_lock_held=True)

        backup_dir = runtime_dir / "chroma_db.backup"
        assert summary["backup_created"] is True
        assert summary["backup_dir"] == str(backup_dir)
        assert (backup_dir / "chroma.sqlite3").read_bytes() == b"sqlite"
        assert (backup_dir / "segment-1" / "header.bin").read_bytes() == b"header"
        assert (backup_dir / "_backup_metadata.json").exists()
        metadata = json.loads((backup_dir / "_backup_metadata.json").read_text(encoding="utf-8"))
        assert metadata["manifest_signature"] == summary["manifest_signature"]
        assert metadata["manifest_snapshot"]["schema_version"] == 1


def test_restore_chroma_store_from_backup_replaces_bad_store():
    with TemporaryDirectory() as tmp:
        runtime_dir = Path(tmp)
        persist_dir = runtime_dir / "chroma_db"
        backup_dir = runtime_dir / "chroma_db.backup"
        persist_dir.mkdir()
        backup_dir.mkdir()
        (persist_dir / "chroma.sqlite3").write_bytes(b"bad")
        (backup_dir / "chroma.sqlite3").write_bytes(b"good")
        (backup_dir / "_backup_metadata.json").write_text("{}", encoding="utf-8")

        with patch.object(kb_admin_service, "RAG_LOCAL_PERSIST_DIR", str(persist_dir)), \
                patch.object(kb_admin_service, "release_chroma_runtime_handles"):
            summary = kb_admin_service.restore_chroma_store_from_backup(_lock_held=True)

        assert summary["restored"] is True
        assert (persist_dir / "chroma.sqlite3").read_bytes() == b"good"
        assert not (persist_dir / "_backup_metadata.json").exists()
        replaced_dir = Path(summary["replaced_persist_store"])
        assert replaced_dir.exists()
        assert (replaced_dir / "chroma.sqlite3").read_bytes() == b"bad"


def test_restore_chroma_store_from_backup_reports_manifest_delta():
    with TemporaryDirectory() as tmp:
        runtime_dir = Path(tmp)
        persist_dir = runtime_dir / "chroma_db"
        backup_dir = runtime_dir / "chroma_db.backup"
        docs_dir = runtime_dir / "kb_documents"
        persist_dir.mkdir()
        backup_dir.mkdir()
        docs_dir.mkdir()
        (persist_dir / "chroma.sqlite3").write_bytes(b"bad")
        (backup_dir / "chroma.sqlite3").write_bytes(b"good")
        old_file = docs_dir / "old.txt"
        changed_file = docs_dir / "changed.txt"
        new_file = docs_dir / "new.txt"
        old_file.write_text("old", encoding="utf-8")
        changed_file.write_text("changed", encoding="utf-8")
        new_file.write_text("new", encoding="utf-8")
        backup_snapshot = {
            "schema_version": 1,
            "documents": [
                {
                    "id": "changed",
                    "file_name": "changed.txt",
                    "file_path": str(changed_file),
                    "file_size": 7,
                    "knowledge_base": "通用",
                    "category": "",
                    "updated_at": "old-time",
                    "processed_at": "old-time",
                    "indexed_vector_count": 1,
                },
                {
                    "id": "deleted",
                    "file_name": "old.txt",
                    "file_path": str(old_file),
                    "file_size": 3,
                    "knowledge_base": "通用",
                    "category": "",
                    "updated_at": "old-time",
                    "processed_at": "old-time",
                    "indexed_vector_count": 1,
                },
            ],
        }
        (backup_dir / "_backup_metadata.json").write_text(
            json.dumps({
                "manifest_signature": kb_admin_service.chroma_manifest_signature(backup_snapshot),
                "manifest_snapshot": backup_snapshot,
            }, ensure_ascii=False),
            encoding="utf-8",
        )
        manifest = docs_dir / "documents.json"
        manifest.write_text(json.dumps({
            "documents": [
                {
                    "id": "changed",
                    "file_name": "changed.txt",
                    "file_path": str(changed_file),
                    "file_type": "txt",
                    "file_size": 7,
                    "knowledge_base": "通用",
                    "category": "",
                    "status": "active",
                    "processing_status": "indexed",
                    "updated_at": "new-time",
                    "processed_at": "new-time",
                    "indexed_vector_count": 1,
                },
                {
                    "id": "new",
                    "file_name": "new.txt",
                    "file_path": str(new_file),
                    "file_type": "txt",
                    "file_size": 3,
                    "knowledge_base": "通用",
                    "category": "",
                    "status": "active",
                    "processing_status": "indexed",
                    "updated_at": "new-time",
                    "processed_at": "new-time",
                    "indexed_vector_count": 1,
                },
            ],
        }, ensure_ascii=False), encoding="utf-8")

        with patch.object(kb_admin_service, "RAG_LOCAL_PERSIST_DIR", str(persist_dir)), \
                patch.object(kb_admin_service, "RAG_LOCAL_DOCS_DIR", str(docs_dir)), \
                patch.object(kb_admin_service, "RAG_LOCAL_MANIFEST_PATH", str(manifest)), \
                patch.object(kb_admin_service, "release_chroma_runtime_handles"):
            summary = kb_admin_service.restore_chroma_store_from_backup(_lock_held=True)

        assert summary["restored"] is True
        assert summary["manifest_matches"] is False
        assert summary["changed_document_ids"] == ["changed", "new"]
        assert summary["deleted_document_ids"] == ["deleted"]


def test_refresh_restored_chroma_store_from_manifest_delta_reindexes_changed_only():
    class DeltaCollection:
        def __init__(self):
            self.deletes = []

        def delete(self, where):
            self.deletes.append(where)

    class DeltaSearcher(FakeSearcher):
        def __init__(self):
            super().__init__()
            self.collection = DeltaCollection()

        def create_or_load_collection(self):
            return self.collection

    with TemporaryDirectory() as tmp:
        runtime_dir = Path(tmp)
        persist_dir = runtime_dir / "chroma_db"
        docs_dir = runtime_dir / "kb_documents"
        manifest = docs_dir / "documents.json"
        persist_dir.mkdir()
        docs_dir.mkdir()
        (persist_dir / "chroma.sqlite3").write_bytes(b"sqlite")
        changed_file = docs_dir / "changed.csv"
        unchanged_file = docs_dir / "unchanged.csv"
        changed_file.write_text("question,answer,company\n新題,新答,共用\n", encoding="utf-8")
        unchanged_file.write_text("question,answer,company\n舊題,舊答,共用\n", encoding="utf-8")
        manifest.write_text(json.dumps({
            "documents": [
                {
                    "id": "changed",
                    "title": "changed",
                    "file_name": "changed.csv",
                    "file_path": str(changed_file),
                    "file_type": "csv",
                    "file_size": changed_file.stat().st_size,
                    "knowledge_base": "通用",
                    "category": "",
                    "status": "active",
                    "processing_status": "indexed",
                    "updated_at": "new-time",
                    "processed_at": "new-time",
                    "indexed_vector_count": 1,
                },
                {
                    "id": "unchanged",
                    "title": "unchanged",
                    "file_name": "unchanged.csv",
                    "file_path": str(unchanged_file),
                    "file_type": "csv",
                    "file_size": unchanged_file.stat().st_size,
                    "knowledge_base": "通用",
                    "category": "",
                    "status": "active",
                    "processing_status": "indexed",
                    "updated_at": "same-time",
                    "processed_at": "same-time",
                    "indexed_vector_count": 1,
                },
            ],
        }, ensure_ascii=False), encoding="utf-8")
        searcher = DeltaSearcher()

        with patch.object(kb_admin_service, "RAG_LOCAL_PERSIST_DIR", str(persist_dir)), \
                patch.object(kb_admin_service, "RAG_LOCAL_DOCS_DIR", str(docs_dir)), \
                patch.object(kb_admin_service, "RAG_LOCAL_MANIFEST_PATH", str(manifest)), \
                patch.object(kb_admin_service, "load_searcher", return_value=searcher), \
                patch.object(kb_admin_service, "release_chroma_runtime_handles"), \
                patch.object(kb_admin_service, "backup_active_chroma_store_best_effort", return_value={"backup_created": True}):
            summary = kb_admin_service.refresh_restored_chroma_store_from_manifest_delta(
                {
                    "changed_document_ids": ["changed"],
                    "deleted_document_ids": ["deleted"],
                },
                _lock_held=True,
            )

        assert summary["indexed_count"] == 1
        assert summary["deleted_count"] == 1
        assert searcher.collection.deletes == [{"document_id": "deleted"}]
        assert searcher.deleted == ["changed"]
        assert {record["document_id"] for record in searcher.records} == {"changed"}


def test_rebuild_active_index_stops_when_windows_blocks_store_archive():
    with TemporaryDirectory() as tmp:
        docs_dir = Path(tmp) / "docs"
        docs_dir.mkdir()
        manifest = docs_dir / "documents.json"
        manifest.write_text('{"documents": []}', encoding="utf-8")
        with patch.object(kb_admin_service, "RAG_LOCAL_MANIFEST_PATH", str(manifest)), \
                patch.object(
                    kb_admin_service,
                    "archive_corrupted_chroma_store",
                    side_effect=PermissionError("[WinError 5] 存取被拒"),
                ), \
                patch.object(kb_admin_service, "release_chroma_runtime_handles"), \
                patch.object(kb_admin_service, "reindex_all_documents") as reindex, \
                patch.object(kb_admin_service, "reset_runtime_search_cache") as reset_cache:
            with pytest.raises(RuntimeError, match="只有一個 API 程序"):
                kb_admin_service.rebuild_active_index(_lock_held=True)

    reindex.assert_not_called()
    reset_cache.assert_called_with(clear_degraded=False)


def test_get_document_file_path_returns_saved_original_file():
    with TemporaryDirectory() as tmp:
        docs_dir = Path(tmp) / "docs"
        manifest = docs_dir / "documents.json"
        fake = FakeSearcher()

        with patch.object(kb_admin_service, "RAG_LOCAL_DOCS_DIR", str(docs_dir)), \
                patch.object(kb_admin_service, "RAG_LOCAL_MANIFEST_PATH", str(manifest)), \
                patch.object(kb_admin_service, "load_searcher", return_value=fake):
            doc = kb_admin_service.create_document(
                file_name="原始流程.txt",
                content="這是原始檔案內容。".encode("utf-8"),
                title="原始流程",
                knowledge_base="通用",
                category=None,
            )
            file_path = kb_admin_service.get_document_file_path(doc["id"])

        assert file_path.exists()
        assert file_path.read_text(encoding="utf-8") == "這是原始檔案內容。"


def test_csv_preview_preserves_cell_line_breaks():
    pytest.importorskip("fastapi")
    import app.app_backend as app_backend

    with TemporaryDirectory() as tmp:
        docs_dir = Path(tmp) / "docs"
        manifest = docs_dir / "documents.json"
        fake = FakeSearcher()

        with patch.object(kb_admin_service, "RAG_LOCAL_DOCS_DIR", str(docs_dir)), \
                patch.object(kb_admin_service, "RAG_LOCAL_MANIFEST_PATH", str(manifest)), \
                patch.object(kb_admin_service, "load_searcher", return_value=fake):
            doc = kb_admin_service.create_document(
                file_name="機上盒.csv",
                content='question,answer,company\n遙控器怎麼設定,"步驟一\n步驟二",共用\n'.encode("utf-8"),
                title="機上盒",
                knowledge_base="通用",
                category=None,
            )
            html = app_backend.render_csv_preview_content(doc["id"])

    assert "問題：" in html
    assert "答案：" in html
    assert "步驟一<br>步驟二" in html


def test_pdf_preview_uses_absolute_original_file_url():
    pytest.importorskip("fastapi")
    import app.app_backend as app_backend

    assert app_backend.kb_document_file_url("doc 1") == "/api/kb/documents/doc%201/file"
    assert (
        app_backend.kb_document_file_url("doc 1", "aicust.token/value")
        == "/api/kb/documents/doc%201/file?api_token=aicust.token%2Fvalue"
    )


def test_kb_document_direct_link_invalid_api_token_shows_refresh_hint():
    pytest.importorskip("fastapi")
    pytest.importorskip("fastapi.testclient")
    from fastapi.testclient import TestClient
    import app.app_backend as app_backend

    with patch.object(app_backend, "API_AUTH_TOKEN", ""), \
            patch.object(app_backend, "API_AUTH_SECRET", "test-secret"), \
            patch.object(app_backend, "API_AUTH_NAME", "web"), \
            patch.object(app_backend, "API_AUTH_PASSWORD", "password"):
        response = TestClient(app_backend.app).get(
            "/api/kb/documents/doc-1/preview?api_token=expired-token"
        )

    assert response.status_code == 401
    assert "text/html" in response.headers["content-type"]
    assert "文件連結已失效" in response.text
    assert "請回到知識庫維護頁重新整理後" in response.text


def test_kb_document_auth_error_page_uses_refresh_hint_for_downloads():
    pytest.importorskip("fastapi")
    import app.app_backend as app_backend

    response = app_backend.render_kb_document_auth_error_page("登入狀態已失效，請重新登入。")

    assert response.status_code == 401
    assert "登入狀態已失效，請重新登入。" in response.body.decode("utf-8")
    assert "查看」或「下載" in response.body.decode("utf-8")


def test_kb_document_actor_names_use_account_display_names():
    pytest.importorskip("fastapi")
    import app.app_backend as app_backend

    document = {
        "uploaded_by": "bluebells",
        "last_indexed_by": "tinp",
    }

    result = app_backend.with_kb_actor_display_names(
        document,
        {
            "bluebells": "陳蜜鈴",
            "tinp": "陳聲鈴",
        },
    )

    assert result["uploaded_by"] == "bluebells"
    assert result["uploaded_by_display_name"] == "陳蜜鈴"
    assert result["last_indexed_by"] == "tinp"
    assert result["last_indexed_by_display_name"] == "陳聲鈴"


def test_kb_document_actor_names_keep_unknown_actor_as_fallback():
    pytest.importorskip("fastapi")
    import app.app_backend as app_backend

    result = app_backend.with_kb_actor_display_names(
        {"uploaded_by": "legacy-user", "last_indexed_by": "system"},
        {},
    )

    assert result["uploaded_by_display_name"] == "legacy-user"
    assert result["last_indexed_by_display_name"] == "system"


def test_relative_manifest_file_path_resolves_from_project_root():
    with TemporaryDirectory() as tmp:
        root = Path(tmp)
        file_path = root / "data" / "kb_documents" / "abc_test.pdf"
        file_path.parent.mkdir(parents=True)
        file_path.write_bytes(b"%PDF-1.4\n")

        with patch.object(kb_admin_service, "BASE_DIR", root), \
                patch.object(kb_admin_service, "RAG_LOCAL_DOCS_DIR", str(file_path.parent)):
            resolved = kb_admin_service.resolve_document_file_path("data/kb_documents/abc_test.pdf")

        assert resolved == file_path


def test_manifest_old_absolute_file_path_resolves_to_current_docs_dir_copy():
    with TemporaryDirectory() as tmp:
        root = Path(tmp)
        old_docs_dir = root / "old_app" / "data" / "kb_documents"
        runtime_docs_dir = root / "runtime" / "kb_documents"
        manifest = runtime_docs_dir / "documents.json"
        old_file = old_docs_dir / "abc_same.csv"
        runtime_file = runtime_docs_dir / "abc_same.csv"
        old_file.parent.mkdir(parents=True)
        runtime_file.parent.mkdir(parents=True)
        old_file.write_text("old", encoding="utf-8")
        runtime_file.write_text("new", encoding="utf-8")
        manifest.write_text(
            """
{
  "documents": [
    {
      "id": "doc1",
      "status": "active",
      "file_path": "%s"
    }
  ]
}
""".strip() % str(old_file).replace("\\", "\\\\"),
            encoding="utf-8",
        )

        with patch.object(kb_admin_service, "RAG_LOCAL_DOCS_DIR", str(runtime_docs_dir)), \
                patch.object(kb_admin_service, "RAG_LOCAL_MANIFEST_PATH", str(manifest)):
            resolved = kb_admin_service.get_document_file_path("doc1")

        assert resolved == runtime_file.resolve()
        assert resolved.read_text(encoding="utf-8") == "new"


def test_delete_document_removes_vectors_without_full_rebuild_when_verified_clean():
    with TemporaryDirectory() as tmp:
        docs_dir = Path(tmp) / "docs"
        manifest = docs_dir / "documents.json"
        fake = FakeSearcher()

        with patch.object(kb_admin_service, "RAG_LOCAL_DOCS_DIR", str(docs_dir)), \
                patch.object(kb_admin_service, "RAG_LOCAL_MANIFEST_PATH", str(manifest)), \
                patch.object(kb_admin_service, "load_searcher", return_value=fake):
            old_doc = kb_admin_service.create_document(
                file_name="舊FAQ.csv",
                content="question,answer,company\n舊問題,舊答案,共用\n".encode("utf-8"),
                title="舊FAQ",
                knowledge_base="通用",
                category=None,
            )
            active_doc = kb_admin_service.create_document(
                file_name="新FAQ.csv",
                content="question,answer,company\n新問題,新答案,共用\n".encode("utf-8"),
                title="新FAQ",
                knowledge_base="通用",
                category=None,
            )

            deleted = kb_admin_service.delete_document(old_doc["id"])

        assert deleted["status"] == "deleted"
        assert fake.delete_collection_calls == 0
        assert fake.deleted[-1] == old_doc["id"]
        assert fake.records
        assert {record["document_id"] for record in fake.records} == {active_doc["id"]}


def test_delete_document_rebuilds_active_index_when_vector_delete_leaves_residue():
    with TemporaryDirectory() as tmp:
        docs_dir = Path(tmp) / "docs"
        manifest = docs_dir / "documents.json"
        fake = ResidualVectorSearcher()

        with patch.object(kb_admin_service, "RAG_LOCAL_DOCS_DIR", str(docs_dir)), \
                patch.object(kb_admin_service, "RAG_LOCAL_MANIFEST_PATH", str(manifest)), \
                patch.object(kb_admin_service, "load_searcher", return_value=fake):
            old_doc = kb_admin_service.create_document(
                file_name="舊FAQ.csv",
                content="question,answer,company\n舊問題,舊答案,共用\n".encode("utf-8"),
                title="舊FAQ",
                knowledge_base="通用",
                category=None,
            )
            active_doc = kb_admin_service.create_document(
                file_name="新FAQ.csv",
                content="question,answer,company\n新問題,新答案,共用\n".encode("utf-8"),
                title="新FAQ",
                knowledge_base="通用",
                category=None,
            )

            deleted = kb_admin_service.delete_document(old_doc["id"])

        assert deleted["status"] == "deleted"
        assert fake.delete_collection_calls == 1
        assert fake.residual_collection.get_calls[-1] == {
            "where": {"document_id": old_doc["id"]},
            "limit": 1,
        }
        assert fake.records
        assert {record["document_id"] for record in fake.records} == {active_doc["id"]}


def test_reindex_all_documents_rebuilds_active_documents_once_and_returns_summary():
    with TemporaryDirectory() as tmp:
        docs_dir = Path(tmp) / "docs"
        manifest = docs_dir / "documents.json"
        fake = FakeSearcher()

        with patch.object(kb_admin_service, "RAG_LOCAL_DOCS_DIR", str(docs_dir)), \
                patch.object(kb_admin_service, "RAG_LOCAL_MANIFEST_PATH", str(manifest)), \
                patch.object(kb_admin_service, "load_searcher", return_value=fake) as load_searcher:
            first_doc = kb_admin_service.create_document(
                file_name="第一份.csv",
                content="question,answer,company\n第一題,第一答,共用\n".encode("utf-8"),
                title="第一份",
                knowledge_base="通用",
                category=None,
            )
            second_doc = kb_admin_service.create_document(
                file_name="第二份.csv",
                content="question,answer,company\n第二題,第二答,共用\n".encode("utf-8"),
                title="第二份",
                knowledge_base="通用",
                category=None,
            )
            deleted_doc = kb_admin_service.create_document(
                file_name="刪除份.csv",
                content="question,answer,company\n刪除題,刪除答,共用\n".encode("utf-8"),
                title="刪除份",
                knowledge_base="通用",
                category=None,
            )
            deleted_doc["status"] = "deleted"
            deleted_doc["processing_status"] = "deleted"
            kb_admin_service.upsert_document_record(deleted_doc)

            fake.delete_collection_calls = 0
            fake.deleted = []
            load_searcher.reset_mock()

            result = kb_admin_service.reindex_all_documents(indexed_by="Carol")

    assert result["total_count"] == 2
    assert result["indexed_count"] == 2
    assert result["failed_count"] == 0
    assert result["chunk_count"] == 2
    assert fake.delete_collection_calls == 1
    load_searcher.assert_called_once_with()
    assert set(fake.deleted) == {first_doc["id"], second_doc["id"]}
    assert {doc["id"] for doc in result["documents"]} == {first_doc["id"], second_doc["id"]}
    assert {doc["last_indexed_by"] for doc in result["documents"]} == {"Carol"}


def test_reindex_all_documents_returns_per_document_failure_details():
    failed_document = {
        "id": "doc-failed",
        "title": "壞掉的文件",
        "file_name": "broken.docx",
        "knowledge_base": "大屯",
        "processing_status": "failed",
        "processing_error_stage": "extract_document",
        "processing_error_type": "ValueError",
        "processing_error": "DOCX 結構不完整",
    }

    fake = FakeSearcher()
    with patch.object(kb_admin_service, "reset_runtime_search_cache"), \
            patch.object(kb_admin_service, "list_documents", return_value=[failed_document]), \
            patch.object(kb_admin_service, "load_searcher", return_value=fake), \
            patch.object(kb_admin_service, "index_document", return_value=failed_document):
        result = kb_admin_service.reindex_all_documents(
            indexed_by="system",
            reset_collection=False,
            _lock_held=True,
        )

    assert result["failed_count"] == 1
    assert result["failures"] == [{
        "document_id": "doc-failed",
        "title": "壞掉的文件",
        "file_name": "broken.docx",
        "knowledge_base": "大屯",
        "stage": "extract_document",
        "exception_type": "ValueError",
        "error": "DOCX 結構不完整",
    }]


def test_migrate_legacy_common_documents_moves_manifest_and_reindexes_active_docs():
    with TemporaryDirectory() as tmp:
        docs_dir = Path(tmp) / "docs"
        manifest = docs_dir / "documents.json"
        fake = FakeSearcher()

        with patch.object(kb_admin_service, "RAG_LOCAL_DOCS_DIR", str(docs_dir)), \
                patch.object(kb_admin_service, "RAG_LOCAL_MANIFEST_PATH", str(manifest)), \
                patch.object(kb_admin_service, "load_searcher", return_value=fake):
            legacy_file = docs_dir / "legacy.txt"
            docs_dir.mkdir(parents=True, exist_ok=True)
            legacy_file.write_text("退租請攜帶證件。", encoding="utf-8")
            kb_admin_service.save_manifest({
                "documents": [{
                    "id": "legacy-doc",
                    "title": "舊通用文件",
                    "file_name": "legacy.txt",
                    "file_path": str(legacy_file),
                    "file_type": "txt",
                    "file_size": legacy_file.stat().st_size,
                    "knowledge_base": "通用",
                    "category": "billing",
                    "status": "active",
                    "processing_status": "indexed",
                    "created_at": kb_admin_service.now_iso(),
                    "updated_at": kb_admin_service.now_iso(),
                }],
            })

            result = kb_admin_service.migrate_legacy_common_documents(
                indexed_by="system",
            )
            migrated = kb_admin_service.get_document("legacy-doc")

    assert result["migrated_count"] == 1
    assert result["indexed_count"] == 1
    assert result["failed_count"] == 0
    assert migrated["knowledge_base"] == "通用-中區"
    assert migrated["knowledge_base_migrated_from"] == "通用"
    assert migrated["last_indexed_by"] == "system"
    assert {record["knowledge_base"] for record in fake.records} == {"通用-中區"}
