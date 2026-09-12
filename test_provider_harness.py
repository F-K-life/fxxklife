import unittest

import provider_harness
import provider_tls


class ProviderHarnessTests(unittest.TestCase):
    def test_provider_tls_context_contains_trusted_roots(self):
        context = provider_tls.secure_context()
        self.assertGreater(len(context.get_ca_certs()), 0)

    def test_provider_headers_use_an_explicit_application_user_agent(self):
        headers = provider_tls.request_headers("test-key")
        self.assertEqual(headers["Authorization"], "Bearer test-key")
        self.assertEqual(headers["Content-Type"], "application/json")
        self.assertTrue(headers["User-Agent"].startswith("Future-Self/"))
        self.assertNotIn("Python-urllib", headers["User-Agent"])

    def test_chat_completions_url_accepts_base_or_full_endpoint(self):
        self.assertEqual(
            provider_harness.chat_completions_url("https://example.com/v1"),
            "https://example.com/v1/chat/completions",
        )
        self.assertEqual(
            provider_harness.chat_completions_url("https://example.com/v1/chat/completions/"),
            "https://example.com/v1/chat/completions",
        )

    def test_parse_protocol_response_requires_json_content(self):
        content = provider_harness.parse_protocol_response(
            {
                "choices": [
                    {
                        "message": {
                            "content": '{"status":"ok","message":"connected"}'
                        }
                    }
                ]
            }
        )
        self.assertEqual(content["status"], "ok")

        with self.assertRaisesRegex(ValueError, "protocol response"):
            provider_harness.parse_protocol_response({"choices": []})

    def test_verify_application_result_requires_remote_valid_reply(self):
        result = {
            "reply_text": "先打开项目，花五分钟运行一个最小例子。",
            "intent": "action",
            "action_suggestion": {
                "title": "运行一个最小例子",
                "first_step": "打开项目。",
                "done_criteria": "看到输出或记下报错。",
                "planned_minutes": 5,
            },
            "evidence_ids": [],
            "model": {"mode": "remote", "label": "deepseek-v4-flash", "available": True},
        }
        provider_harness.verify_application_result(result)

        result["model"] = {"mode": "local", "label": "local", "available": False}
        with self.assertRaisesRegex(ValueError, "local fallback"):
            provider_harness.verify_application_result(result)

    def test_safe_summary_never_contains_api_key(self):
        api_key = "sk-secret-value"
        summary = provider_harness.safe_summary(
            base_url="https://example.com/v1",
            model="deepseek-v4-flash",
            api_key=api_key,
        )
        self.assertNotIn(api_key, summary)
        self.assertNotIn("secret-value", summary)
        self.assertIn("deepseek-v4-flash", summary)


if __name__ == "__main__":
    unittest.main()
