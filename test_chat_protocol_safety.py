import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app import create_app


class ChatProtocolSafetyTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.app = create_app(
            {
                "TESTING": True,
                "DATABASE": str(Path(self.directory.name) / "chat-safety.db"),
                "SECRET_KEY": "chat-safety-test-only",
            }
        )
        self.client = self.app.test_client()
        self.client.get("/register")
        with self.client.session_transaction() as saved:
            csrf = saved["csrf_token"]
        response = self.client.post(
            "/register",
            data={
                "csrf_token": csrf,
                "name": "协议测试",
                "email": "protocol@example.test",
                "password": "temporary-test-password",
            },
        )
        self.assertEqual(response.status_code, 302)
        with self.client.session_transaction() as saved:
            self.csrf = {"X-CSRF-Token": saved["csrf_token"]}

    def tearDown(self):
        self.directory.cleanup()

    def test_chat_persists_only_visible_valid_reply(self):
        safe = {
            "reply_text": "先做一个五分钟的小实验。",
            "intent": "listen",
            "action_suggestion": None,
            "evidence_ids": [],
            "model": {"mode": "local", "label": "本地规则", "available": False},
        }
        with patch("app.modeling.chat_reply", return_value=safe):
            response = self.client.post(
                "/api/chat",
                json={"message": "我卡住了", "request_id": "safe-1"},
                headers=self.csrf,
            )

        self.assertEqual(response.status_code, 200)
        state = self.client.get("/api/state").get_json()
        self.assertEqual(state["messages"][-1]["content"], safe["reply_text"])
        self.assertFalse(state["messages"][-1]["content"].lstrip().startswith("{"))

    def test_chat_failure_does_not_persist_an_assistant_message(self):
        with patch("app.modeling.chat_reply", side_effect=ValueError("invalid protocol")):
            response = self.client.post(
                "/api/chat",
                json={"message": "这条用户消息要保留", "request_id": "failed-1"},
                headers=self.csrf,
            )

        self.assertEqual(response.status_code, 503)
        state = self.client.get("/api/state").get_json()
        self.assertEqual([message["role"] for message in state["messages"]], ["user"])
        self.assertEqual(state["messages"][0]["content"], "这条用户消息要保留")


if __name__ == "__main__":
    unittest.main()
