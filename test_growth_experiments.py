import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

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

    def confirmed_experiment(self, title="成长主题"):
        experiment = self.create_experiment(title=title).get_json()["experiment"]
        capabilities = [
            {"name": f"能力{i}", "description": f"说明{i}", "target_state": f"目标{i}"}
            for i in range(1, 4)
        ]
        result = self.api(
            f"/api/growth-experiments/{experiment['id']}/capabilities/confirm",
            {"version": experiment["version"], "request_id": f"caps-{experiment['id']}", "capabilities": capabilities},
        ).get_json()
        return result["experiment"], result["capabilities"]

    def activate_week(self, experiment, capability, request_id="week-1"):
        return self.api("/api/weekly-experiments/0", {
            "experiment_id": experiment["id"], "experiment_version": experiment["version"],
            "week_number": 1, "capability_id": capability["id"], "hypothesis": "一次真实练习能暴露关键差距",
            "success_signal": "留下结果并写出下一次调整", "confirm_action": True, "request_id": request_id,
            "action": {"title": "完成一次真实练习", "first_step": "写下要验证的问题", "done_criteria": "留下结果和调整",
                       "planned_minutes": 20, "expected_evidence_kind": "reflection"}
        }, method="PATCH")

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

    def test_growth_draft_falls_back_without_persisting(self):
        experiment = self.create_experiment().get_json()["experiment"]
        before = {
            "capabilities": self.sql("SELECT COUNT(*) AS n FROM capabilities")[0]["n"],
            "weeks": self.sql("SELECT COUNT(*) AS n FROM weekly_experiments")[0]["n"],
            "tasks": self.sql("SELECT COUNT(*) AS n FROM tasks")[0]["n"],
        }
        capability_draft = self.api(
            f"/api/growth-experiments/{experiment['id']}/capability-draft", {}
        )
        self.assertEqual(capability_draft.status_code, 200)
        proposed = capability_draft.get_json()["capabilities"]
        self.assertGreaterEqual(len(proposed), 3)
        self.assertEqual(
            self.sql("SELECT COUNT(*) AS n FROM capabilities")[0]["n"],
            before["capabilities"],
        )

        confirmed = self.api(
            f"/api/growth-experiments/{experiment['id']}/capabilities/confirm",
            {
                "version": experiment["version"],
                "request_id": "draft-test-confirm",
                "capabilities": proposed[:3],
            },
        ).get_json()
        counts_after_confirm = {
            "weeks": self.sql("SELECT COUNT(*) AS n FROM weekly_experiments")[0]["n"],
            "tasks": self.sql("SELECT COUNT(*) AS n FROM tasks")[0]["n"],
        }
        weekly_draft = self.api(
            f"/api/growth-experiments/{experiment['id']}/weekly-draft", {}
        )
        self.assertEqual(weekly_draft.status_code, 200)
        self.assertTrue(weekly_draft.get_json()["action"]["first_step"])
        self.assertEqual(
            self.sql("SELECT COUNT(*) AS n FROM weekly_experiments")[0]["n"],
            counts_after_confirm["weeks"],
        )
        self.assertEqual(
            self.sql("SELECT COUNT(*) AS n FROM tasks")[0]["n"],
            counts_after_confirm["tasks"],
        )
        self.assertEqual(confirmed["experiment"]["status"], "draft")

    def test_only_one_active_experiment_per_user(self):
        first, first_caps = self.confirmed_experiment("主题一")
        second, second_caps = self.confirmed_experiment("主题二")
        activated = self.activate_week(first, first_caps[0], "activate-first")
        self.assertEqual(activated.status_code, 200)
        blocked = self.activate_week(second, second_caps[0], "activate-second")
        self.assertEqual(blocked.status_code, 409)
        self.assertEqual(self.sql("SELECT COUNT(*) AS n FROM growth_experiments WHERE status='active'")[0]["n"], 1)

    def test_stale_version_returns_409_without_partial_writes(self):
        experiment, capabilities = self.confirmed_experiment()
        before = self.sql("SELECT COUNT(*) AS n FROM tasks")[0]["n"]
        stale = dict(experiment, version=experiment["version"] - 1)
        response = self.activate_week(stale, capabilities[0], "stale-week")
        self.assertEqual(response.status_code, 409)
        self.assertEqual(self.sql("SELECT COUNT(*) AS n FROM weekly_experiments")[0]["n"], 0)
        self.assertEqual(self.sql("SELECT COUNT(*) AS n FROM tasks")[0]["n"], before)

    def test_week_confirmation_is_idempotent_and_links_task(self):
        experiment, capabilities = self.confirmed_experiment()
        first = self.activate_week(experiment, capabilities[0], "linked-week")
        self.assertEqual(first.status_code, 200)
        payload = first.get_json()
        replay = self.activate_week(experiment, capabilities[0], "linked-week")
        self.assertEqual(replay.get_json(), payload)
        task = payload["task"]
        self.assertEqual(task["experiment_id"], experiment["id"])
        self.assertEqual(task["weekly_experiment_id"], payload["weekly_experiment"]["id"])
        self.assertEqual(task["capability_id"], capabilities[0]["id"])
        manual = self.api("/api/tasks", {
            "title": "手动关联行动", "first_step": "开始", "done_criteria": "留下结果", "planned_minutes": 10,
            "experiment_id": experiment["id"], "weekly_experiment_id": payload["weekly_experiment"]["id"],
            "capability_id": capabilities[0]["id"]
        })
        self.assertEqual(manual.status_code, 201)
        self.assertEqual(manual.get_json()["task"]["experiment_id"], experiment["id"])

    def test_confirm_and_evidence_requests_are_idempotent(self):
        experiment, capabilities = self.confirmed_experiment()
        active = self.activate_week(experiment, capabilities[0], "evidence-week").get_json()
        body = {"experiment_id": experiment["id"], "capability_id": capabilities[0]["id"],
                "weekly_experiment_id": active["weekly_experiment"]["id"], "task_id": active["task"]["id"],
                "kind": "reflection", "content": "我完成了练习并发现问题定义需要更具体。",
                "source_label": "第一次真实练习", "confirmed_by_user": True, "request_id": "evidence-1"}
        first = self.api("/api/growth-evidence", body)
        self.assertEqual(first.status_code, 201)
        replay = self.api("/api/growth-evidence", body)
        self.assertEqual(replay.get_json(), first.get_json())
        self.assertEqual(self.sql("SELECT COUNT(*) AS n FROM growth_evidence")[0]["n"], 1)
        state = self.client.get("/api/state").get_json()
        self.assertEqual(state["growth"]["capabilities"][0]["status"], "evidenced")

    def test_evidence_requires_consistent_owned_sources(self):
        experiment, capabilities = self.confirmed_experiment()
        active = self.activate_week(experiment, capabilities[0], "invalid-source-week").get_json()
        unrelated = self.api("/api/tasks", {"title": "无关任务", "first_step": "开始", "done_criteria": "结束", "planned_minutes": 5}).get_json()["task"]
        response = self.api("/api/growth-evidence", {
            "experiment_id": experiment["id"], "capability_id": capabilities[0]["id"],
            "weekly_experiment_id": active["weekly_experiment"]["id"], "task_id": unrelated["id"],
            "kind": "reflection", "content": "不应关联", "source_label": "错误来源",
            "confirmed_by_user": True, "request_id": "bad-source"})
        self.assertEqual(response.status_code, 400)
        self.assertEqual(self.sql("SELECT COUNT(*) AS n FROM growth_evidence")[0]["n"], 0)

    def test_chat_context_contains_only_active_confirmed_growth_evidence(self):
        experiment, capabilities = self.confirmed_experiment()
        active = self.activate_week(experiment, capabilities[0], "context-week").get_json()
        evidence = self.api("/api/growth-evidence", {"experiment_id": experiment["id"], "capability_id": capabilities[0]["id"],
            "weekly_experiment_id": active["weekly_experiment"]["id"], "task_id": active["task"]["id"], "kind": "reflection",
            "content": "有效证据正文不应完整进入上下文", "source_label": "练习一", "confirmed_by_user": True, "request_id": "context-evidence"}).get_json()["evidence"]
        safe = {"reply_text": "继续按证据前进。", "intent": "listen", "action_suggestion": None, "evidence_ids": [],
                "model": {"mode": "local", "label": "test", "available": False}}
        with patch("app.modeling.chat_reply", return_value=safe) as mocked:
            response = self.api("/api/chat", {"message": "我进展怎样", "request_id": "growth-context-chat"})
        self.assertEqual(response.status_code, 200)
        growth = mocked.call_args.args[4]["growth"]
        self.assertEqual(growth["experiment"]["id"], experiment["id"])
        self.assertEqual(growth["evidence"][0]["id"], evidence["id"])
        self.assertNotIn("content", growth["evidence"][0])


if __name__ == "__main__":
    unittest.main()
