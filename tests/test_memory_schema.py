import unittest

from app.services.memory_service import db_conn, init_db


class MemorySchemaTest(unittest.TestCase):
    def test_init_db_removes_legacy_tickets_table(self):
        init_db()

        conn = db_conn()
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT name
            FROM sqlite_master
            WHERE type = 'table' AND name = 'tickets'
            """
        )
        row = cursor.fetchone()
        conn.close()

        self.assertIsNone(row)


if __name__ == "__main__":
    unittest.main()
