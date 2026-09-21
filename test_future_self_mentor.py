import os
import unittest
from unittest.mock import patch

import modeling


class FutureSelfMentorTests(unittest.TestCase):
    def _without_remote_model(self):
        return patch.dict(
            os.environ,
            {"AI_API_KEY": "", "AI_MODEL": "", "AI_BASE_URL": ""},
            clear=False,
        )

    def test_first_question_helps_user_describe_who_they_want_to_be(self):
        with self._without_remote_model():
            result = modeling.onboarding_question(["", "", "", "", ""], 0)

        self.assertEqual(result["question"], "你希望未来的自己，成为一个怎样的人？")
        for dimension in ("性格", "生活状态", "能力", "关系"):
            self.assertIn(dimension, result["hint"])
        self.assertTrue(result["examples"])

    def test_second_question_carries_the_future_self_portrait_forward(self):
        answer = "从容坚定，也懂得照顾重要的人"
        with self._without_remote_model():
            result = modeling.onboarding_question([answer, "", "", "", ""], 1)

        self.assertIn("希望未来的自己", result["question"])
        self.assertIn(answer, result["question"])
        self.assertIn("为什么对你重要", result["question"])

    def test_offline_identity_is_future_self_mentor_and_partner_with_boundaries(self):
        with self._without_remote_model():
            result = modeling.chat_reply(
                "你是谁？你会预言我的未来吗？",
                {},
                [],
                [],
                {"feedback": []},
            )

        self.assertIn("未来的自己", result["reply_text"])
        self.assertIn("导师", result["reply_text"])
        self.assertIn("伙伴", result["reply_text"])
        self.assertIn("不会预知未来", result["reply_text"])
        self.assertIsNone(result["action_suggestion"])

    def test_system_role_listens_before_guiding_or_suggesting_action(self):
        prompt = modeling.SYSTEM_PROMPT

        for role in ("未来的自己", "导师", "伙伴"):
            self.assertIn(role, prompt)
        self.assertLess(prompt.index("倾听"), prompt.index("澄清方向"))
        self.assertLess(prompt.index("澄清方向"), prompt.index("鼓励"))
        self.assertIn("只有用户愿意时", prompt)
        self.assertIn("不得声称已经真实经历未来", prompt)


if __name__ == "__main__":
    unittest.main()
