import tempfile
import unittest
from pathlib import Path

from app.services.state_repository import MongoCustomerStateRepository, SQLiteCustomerStateRepository


class FakeMongoCollection:
    def __init__(self):
        self.documents = {}
        self.indexes = []

    def create_index(self, key, unique=False, name=None):
        self.indexes.append((key, unique, name))

    def list_indexes(self):
        output = []
        for key, unique, name in self.indexes:
            output.append({
                "name": name or f"{key}_1",
                "key": {key: 1} if isinstance(key, str) else dict(key),
                "unique": unique,
            })
        return output

    def find_one(self, query, projection=None):
        document = self.documents.get(query.get("id"))
        if document is None:
            return None

        copied = {
            key: value
            for key, value in document.items()
        }
        if projection and isinstance(projection.get("chat_logs"), dict):
            slice_value = projection["chat_logs"].get("$slice")
            if isinstance(slice_value, int):
                copied["chat_logs"] = copied.get("chat_logs", [])[slice_value:]
        return copied

    def update_one(self, query, update, upsert=False):
        doc_id = query.get("id")
        exists = doc_id in self.documents
        if not exists and not upsert:
            return

        document = self.documents.setdefault(doc_id, {})

        if not exists:
            for key, value in update.get("$setOnInsert", {}).items():
                document[key] = value

        for key, value in update.get("$set", {}).items():
            document[key] = value

        for key, value in update.get("$push", {}).items():
            document.setdefault(key, []).append(value)

    def delete_one(self, query):
        self.documents.pop(query.get("id"), None)


class FakeMongoDatabase:
    def __init__(self):
        self.collections = {}

    def __getitem__(self, name):
        return self.collections.setdefault(name, FakeMongoCollection())


class FakeMongoClient:
    def __init__(self):
        self.databases = {}

    def __getitem__(self, name):
        return self.databases.setdefault(name, FakeMongoDatabase())


class SQLiteCustomerStateRepositoryTest(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = str(Path(self.temp_dir.name) / "state.db")
        self.repository = SQLiteCustomerStateRepository(self.db_path)
        self.repository.init_schema()

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_session_is_saved_and_loaded_as_document(self):
        memory = {
            "company_code": "tdtv",
            "known_info": {
                "channel_name": "HBO",
            },
        }

        self.repository.save_session_document(
            "web:member_123456",
            memory,
            customer_key="web:member_123456",
        )

        document = self.repository.get_session_document("web:member_123456")

        self.assertEqual(document["user_id"], "web:member_123456")
        self.assertEqual(document["customer_key"], "web:member_123456")
        self.assertEqual(document["memory"]["known_info"]["channel_name"], "HBO")

    def test_chat_logs_keep_user_order_after_limit_query(self):
        self.repository.append_chat_log("line:tdtv:U123", "user", "第一句", "line:U123")
        self.repository.append_chat_log("line:tdtv:U123", "assistant", "第二句", "line:U123")
        self.repository.append_chat_log("line:tdtv:U123", "user", "第三句", "line:U123")

        history = self.repository.get_recent_chat_history("line:tdtv:U123", limit=2)

        self.assertEqual(
            history,
            [
                {"role": "assistant", "content": "第二句"},
                {"role": "user", "content": "第三句"},
            ],
        )

    def test_customer_profile_is_saved_as_shared_document(self):
        self.repository.save_customer_profile({
            "customer_key": "line:U123",
            "last_company_code": "tdtv",
            "last_company": "大屯有線",
            "last_area": "大里區",
            "last_user_id": "line:tdtv:U123",
            "last_line_bot_code": "tdtv",
            "resolution_source": "service_area",
            "updated_at": "2026-05-25T10:00:00+08:00",
        })

        profile = self.repository.get_customer_profile("line:U123")

        self.assertEqual(profile["last_company_code"], "tdtv")
        self.assertEqual(profile["last_area"], "大里區")
        self.assertEqual(profile["last_line_bot_code"], "tdtv")

    def test_list_chat_logs_since_filters_by_date(self):
        conn = self.repository.connect()
        try:
            conn.execute(
                "INSERT INTO chat_logs (user_id, customer_key, role, message, created_at) VALUES (?, ?, ?, ?, ?)",
                ("line:tdtv:old", "line:old", "user", "舊對話", "2026-08-23T23:59:59"),
            )
            conn.execute(
                "INSERT INTO chat_logs (user_id, customer_key, role, message, created_at) VALUES (?, ?, ?, ?, ?)",
                ("line:tdtv:new", "line:new", "assistant", "新對話", "2026-08-24T00:00:00"),
            )
            conn.commit()
        finally:
            conn.close()

        records = self.repository.list_chat_logs_since("2026-08-24")

        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["message"], "新對話")


class MongoCustomerStateRepositoryTest(unittest.TestCase):
    def setUp(self):
        self.client = FakeMongoClient()
        self.repository = MongoCustomerStateRepository(
            database_name="aicust_service",
            web_collection_name="web_conversations",
            test_web_collection_name="test_web_conversations",
            line_collection_name="line_conversations",
            client=self.client,
        )
        self.repository.init_schema()
        self.web_collection = self.client["aicust_service"]["web_conversations"]
        self.test_web_collection = self.client["aicust_service"]["test_web_conversations"]
        self.line_collection = self.client["aicust_service"]["line_conversations"]

    def test_init_schema_creates_id_index(self):
        self.assertIn(("id", True, "id_unique"), self.web_collection.indexes)
        self.assertIn(("id", True, "id_unique"), self.test_web_collection.indexes)
        self.assertIn(("id", True, "id_unique"), self.line_collection.indexes)

    def test_init_schema_reuses_existing_unique_id_index_with_different_name(self):
        client = FakeMongoClient()
        web_collection = client["aicust_service"]["web_conversations"]
        test_web_collection = client["aicust_service"]["test_web_conversations"]
        line_collection = client["aicust_service"]["line_conversations"]
        web_collection.indexes.append(("id", True, "id_unique"))
        test_web_collection.indexes.append(("id", True, "id_unique"))
        line_collection.indexes.append(("id", True, "id_unique"))

        repository = MongoCustomerStateRepository(
            database_name="aicust_service",
            web_collection_name="web_conversations",
            test_web_collection_name="test_web_conversations",
            line_collection_name="line_conversations",
            client=client,
        )
        repository.init_schema()

        self.assertEqual(web_collection.indexes.count(("id", True, "id_unique")), 1)
        self.assertEqual(test_web_collection.indexes.count(("id", True, "id_unique")), 1)
        self.assertEqual(line_collection.indexes.count(("id", True, "id_unique")), 1)

    def test_line_collection_stores_ai_state_and_chat_logs(self):
        memory = {
            "company_code": "tdtv",
            "known_info": {
                "channel_name": "HBO",
            },
        }

        self.repository.save_session_document(
            "line:tdtv:U123",
            memory,
            customer_key="line:U123",
        )
        self.repository.append_chat_log("line:tdtv:U123", "user", "第一句", "line:U123")
        self.repository.append_chat_log("line:tdtv:U123", "assistant", "第二句", "line:U123")

        document = self.line_collection.documents["line:tdtv:U123"]
        self.assertEqual(document["id"], "line:tdtv:U123")
        self.assertEqual(document["line_bot_code"], "tdtv")
        self.assertEqual(document["line_user_id"], "U123")
        self.assertEqual(document["ai_state"]["known_info"]["channel_name"], "HBO")
        self.assertEqual(len(document["chat_logs"]), 2)
        self.assertNotIn("line:tdtv:U123", self.web_collection.documents)

        loaded = self.repository.get_session_document("line:tdtv:U123")
        self.assertEqual(loaded["memory"]["company_code"], "tdtv")

    def test_recent_history_comes_from_embedded_chat_logs(self):
        self.repository.append_chat_log("line:tdtv:U123", "user", "第一句", "line:U123")
        self.repository.append_chat_log("line:tdtv:U123", "assistant", "第二句", "line:U123")
        self.repository.append_chat_log("line:tdtv:U123", "user", "第三句", "line:U123")

        history = self.repository.get_recent_chat_history("line:tdtv:U123", limit=2)

        self.assertEqual(
            history,
            [
                {"role": "assistant", "content": "第二句"},
                {"role": "user", "content": "第三句"},
            ],
        )

    def test_customer_profile_uses_line_collection_with_customer_key_id(self):
        self.repository.save_customer_profile({
            "customer_key": "line:U123",
            "last_company_code": "tdtv",
            "last_company": "大屯有線",
            "last_area": "大里區",
            "last_user_id": "line:tdtv:U123",
            "last_line_bot_code": "tdtv",
            "resolution_source": "service_area",
            "updated_at": "2026-05-25T10:00:00+08:00",
        })

        profile = self.repository.get_customer_profile("line:U123")
        document = self.line_collection.documents["line:U123"]

        self.assertEqual(document["id"], "line:U123")
        self.assertEqual(document["doc_type"], "line_customer_profile")
        self.assertEqual(profile["last_company_code"], "tdtv")
        self.assertEqual(profile["last_area"], "大里區")
        self.assertNotIn("line:U123", self.web_collection.documents)

    def test_web_conversation_uses_web_collection(self):
        memory = {
            "company_code": "tdtv",
            "member_id": "member_123456",
            "is_logged_in": True,
            "channel_context": {
                "channel": "web",
            },
            "known_info": {
                "custnum": "member_123456",
            },
        }

        self.repository.save_session_document(
            "web:member_123456",
            memory,
            customer_key="web:member_123456",
        )
        self.repository.append_chat_log("web:member_123456", "user", "優惠套餐有哪些?", "web:member_123456")

        document = self.web_collection.documents["web:member_123456"]
        self.assertEqual(document["id"], "web:member_123456")
        self.assertEqual(document["channel"], "web")
        self.assertEqual(document["member_id"], "member_123456")
        self.assertTrue(document["is_logged_in"])
        self.assertEqual(document["ai_state"]["company_code"], "tdtv")
        self.assertEqual(document["ai_state"]["known_info"]["custnum"], "member_123456")
        self.assertEqual(document["chat_logs"][0]["message"], "優惠套餐有哪些?")
        self.assertNotIn("web:member_123456", self.line_collection.documents)
        self.assertNotIn("web:member_123456", self.test_web_collection.documents)

    def test_test_web_conversation_uses_test_web_collection(self):
        memory = {
            "company_code": "tdtv",
            "channel_context": {
                "channel": "test_web",
            },
            "known_info": {},
        }

        self.repository.save_session_document(
            "test_web:local-user",
            memory,
            customer_key="test_web:local-user",
        )
        self.repository.append_chat_log("test_web:local-user", "user", "測試訊息", "test_web:local-user")

        document = self.test_web_collection.documents["test_web:local-user"]
        self.assertEqual(document["id"], "test_web:local-user")
        self.assertEqual(document["channel"], "test_web")
        self.assertEqual(document["chat_logs"][0]["message"], "測試訊息")
        self.assertNotIn("test_web:local-user", self.web_collection.documents)
        self.assertNotIn("test_web:local-user", self.line_collection.documents)


if __name__ == "__main__":
    unittest.main()
