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

    def second_demo(self):
        client = self.app.test_client()
        client.get("/login")
        with client.session_transaction() as saved:
            csrf = saved["csrf_token"]
        self.assertEqual(client.post("/demo", data={"csrf_token": csrf}).status_code, 302)
        with client.session_transaction() as saved:
            headers = {"X-CSRF-Token": saved["csrf_token"]}
        return client, headers

    def create_experiment(self, **changes):
        body = {
            "title": "成为能交付的 AI 产品经理",
            "future_identity": "能把真实问题转化为可验证产品的人",
            "desired_outcome": "完成一个可供真实用户试用的作品",
        }
        body.update(changes)
        return self.api("/api/growth-experiments", body)

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

    def test_capability_confirmation_validates_count_names_and_owner(self):
        created = self.create_experiment()
        self.assertEqual(created.status_code, 201)
        experiment = created.get_json()["experiment"]
        self.assertEqual(experiment["status"], "draft")

        too_few = self.api(
            f"/api/growth-experiments/{experiment['id']}/capabilities/confirm",
            {
                "version": experiment["version"],
                "request_id": "caps-too-few",
                "capabilities": [
                    {"name": "洞察", "description": "识别问题", "target_state": "完成访谈"},
                    {"name": "原型", "description": "快速表达", "target_state": "做出原型"},
                ],
            },
        )
        self.assertEqual(too_few.status_code, 400)

        capabilities = [
            {"name": "用户洞察", "description": "从事实识别问题", "target_state": "完成三次访谈"},
            {"name": "产品原型", "description": "把假设变成界面", "target_state": "完成可测试原型"},
            {"name": "结果复盘", "description": "依据证据调整", "target_state": "完成每周复盘"},
        ]
        body = {
            "version": experiment["version"],
            "request_id": "caps-confirm-1",
            "capabilities": capabilities,
        }
        confirmed = self.api(
            f"/api/growth-experiments/{experiment['id']}/capabilities/confirm", body
        )
        self.assertEqual(confirmed.status_code, 200)
        payload = confirmed.get_json()
        self.assertEqual(len(payload["capabilities"]), 3)
        self.assertEqual(payload["experiment"]["status"], "draft")
        self.assertEqual(
            self.api(
                f"/api/growth-experiments/{experiment['id']}/capabilities/confirm", body
            ).get_json(),
            payload,
        )

        stale = self.api(
            f"/api/growth-experiments/{experiment['id']}/capabilities/confirm",
            {**body, "request_id": "caps-stale"},
        )
        self.assertEqual(stale.status_code, 409)

        duplicate = self.create_experiment(title="另一个草稿")
        self.assertEqual(duplicate.status_code, 201)
        self.assertEqual(duplicate.get_json()["experiment"]["status"], "draft")

        stranger, stranger_headers = self.second_demo()
        foreign = stranger.patch(
            f"/api/growth-experiments/{experiment['id']}",
            json={"title": "越权修改", "version": payload["experiment"]["version"]},
            headers=stranger_headers,
        )
        self.assertEqual(foreign.status_code, 404)


if __name__ == "__main__":
    unittest.main()
