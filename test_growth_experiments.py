import sqlite3
import tempfile
import unittest
from pathlib import Path

from app import create_app


class GrowthExperimentTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.database = str(Path(self.directory.name) / "growth.db")
        self.app = create_app(
            {
                "TESTING": True,
                "DATABASE": self.database,
                "SECRET_KEY": "growth-test-only",
            }
        )
        self.client = self.app.test_client()
        self.client.get("/login")
        with self.client.session_transaction() as saved:
            csrf = saved["csrf_token"]
        self.assertEqual(
            self.client.post("/demo", data={"csrf_token": csrf}).status_code,
            302,
        )
        with self.client.session_transaction() as saved:
            self.headers = {"X-CSRF-Token": saved["csrf_token"]}
        self.user_id = self.client.get("/api/session").get_json()["user_id"]

    def tearDown(self):
        self.directory.cleanup()

    def api(self, path, body=None, method="POST"):
        return self.client.open(path, method=method, json=body, headers=self.headers)

    def sql(self, statement, args=()):
        connection = sqlite3.connect(self.database)
        connection.row_factory = sqlite3.Row
        try:
            return connection.execute(statement, args).fetchall()
        finally:
            connection.close()

    def test_empty_growth_state_is_backward_compatible(self):
        state = self.client.get("/api/state").get_json()
        self.assertEqual(
            state["growth"],
            {
                "active_experiment": None,
                "capabilities": [],
                "active_week": None,
                "recent_evidence": [],
            },
        )

    def test_additive_migration_preserves_legacy_rows(self):
        connection = sqlite3.connect(self.database)
        try:
            connection.execute(
                """INSERT INTO tasks(user_id,title,first_step,done_criteria,planned_minutes,status,created_at)
                   VALUES(?,?,?,?,?,'ready',?)""",
                (self.user_id, "legacy task", "start", "done", 10, "2026-09-22T00:00:00Z"),
            )
            connection.commit()
        finally:
            connection.close()

        self.assertEqual(
            self.sql("SELECT COUNT(*) AS n FROM tasks WHERE title=?", ("legacy task",))[0]["n"],
            1,
        )
        columns = {row[1] for row in self.sql("PRAGMA table_info(tasks)")}
        self.assertTrue(
            {"experiment_id", "weekly_experiment_id", "capability_id"} <= columns
        )


if __name__ == "__main__":
    unittest.main()
