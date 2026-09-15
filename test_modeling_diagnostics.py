import os
import unittest
import urllib.error
import json
from unittest.mock import patch

import modeling


class ProviderDiagnosticsTests(unittest.TestCase):
    class _Response:
        def __init__(self, payload):
            self.payload = json.dumps(payload).encode("utf-8")

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self, _limit):
            return self.payload

    def test_chat_reply_keeps_plain_text_from_compatible_provider(self):
        envelope = {
            "choices": [{"message": {"content": "这是模型生成的一句话。"}}]
        }
        with patch.dict(
            os.environ,
            {
                "AI_BASE_URL": "https://provider.example/v1",
                "AI_MODEL": "test-model",
                "AI_API_KEY": "configured-test-key",
            },
        ), patch(
            "modeling.urllib.request.urlopen",
            return_value=self._Response(envelope),
        ):
            result = modeling.chat_reply(
                "给我一句简短回应。",
                {"tone": "简短、清晰"},
                [],
                [],
                {"feedback": []},
            )

        self.assertEqual(result["reply_text"], "这是模型生成的一句话。")
        self.assertEqual(result["model"]["mode"], "remote")
        self.assertTrue(result["model"]["available"])

    def test_generate_logs_http_status_without_sensitive_details(self):
        api_key = "sk-sensitive-test-value"
        error = urllib.error.HTTPError(
            "https://provider.example/v1/chat/completions",
            403,
            "response contained sensitive upstream details",
            {},
            None,
        )

        with patch.dict(
            os.environ,
            {
                "AI_BASE_URL": "https://provider.example/v1",
                "AI_MODEL": "test-model",
                "AI_API_KEY": api_key,
            },
        ), patch("modeling.urllib.request.urlopen", side_effect=error):
            with self.assertLogs("self_echo.modeling", level="WARNING") as captured:
                result = modeling._generate(
                    "system prompt",
                    {"private": "user content"},
                    {"reply_text": "fallback"},
                    lambda value: value,
                )

        output = "\n".join(captured.output)
        self.assertEqual(result["model"]["mode"], "local")
        self.assertIn("category=http_403", output)
        self.assertNotIn(api_key, output)
        self.assertNotIn("sensitive upstream details", output)
        self.assertNotIn("user content", output)


if __name__ == "__main__":
    unittest.main()
