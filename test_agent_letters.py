import unittest
from datetime import datetime, timedelta, timezone

from agent_letters import decide_chat_letter


class AgentLetterDecisionTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2026, 9, 12, 12, 0, tzinfo=timezone.utc)

    def decide(self, **overrides):
        values = {
            "user_id": 7,
            "message_id": 11,
            "message": "最近我很焦虑，也很难开始，但我想继续学习英语。",
            "intent": "action",
            "has_action": True,
            "recent_user_messages": ["我总担心英语学不好。"],
            "prior_send_times": [],
            "now": self.now,
            "roll": 0.0,
            "enabled": True,
        }
        values.update(overrides)
        return decide_chat_letter(**values)

    def test_high_signal_chat_can_schedule_a_delayed_letter(self):
        decision = self.decide()

        self.assertTrue(decision["scheduled"])
        self.assertGreaterEqual(decision["probability"], 0.3)
        self.assertIn("emotional_state", decision["reasons"])
        self.assertIn("action_intent", decision["reasons"])
        self.assertGreaterEqual(decision["delay_seconds"], 600)
        self.assertLessEqual(decision["delay_seconds"], 5400)

    def test_low_signal_chat_does_not_schedule_when_roll_is_above_probability(self):
        decision = self.decide(
            message="你好。",
            intent="listen",
            has_action=False,
            recent_user_messages=[],
            roll=0.9,
        )

        self.assertFalse(decision["scheduled"])
        self.assertEqual(decision["probability"], 0.08)
        self.assertEqual(decision["blocked_by"], "random_roll")

    def test_recent_agent_letter_enforces_a_24_hour_cooldown(self):
        decision = self.decide(prior_send_times=[self.now - timedelta(hours=23)])

        self.assertFalse(decision["scheduled"])
        self.assertEqual(decision["blocked_by"], "cooldown")

    def test_two_agent_letters_in_seven_days_enforce_the_weekly_cap(self):
        decision = self.decide(
            prior_send_times=[self.now - timedelta(days=2), self.now - timedelta(days=5)]
        )

        self.assertFalse(decision["scheduled"])
        self.assertEqual(decision["blocked_by"], "weekly_limit")

    def test_crisis_language_never_schedules_an_automatic_letter(self):
        decision = self.decide(message="我不想活了。", intent="crisis")

        self.assertFalse(decision["scheduled"])
        self.assertEqual(decision["blocked_by"], "safety")
        self.assertEqual(decision["probability"], 0.0)

    def test_same_chat_has_a_stable_roll_and_delay(self):
        first = self.decide(roll=None)
        second = self.decide(roll=None)

        self.assertEqual(first["roll"], second["roll"])
        self.assertEqual(first["delay_seconds"], second["delay_seconds"])
        self.assertGreaterEqual(first["roll"], 0.0)
        self.assertLess(first["roll"], 1.0)
        self.assertGreaterEqual(first["delay_seconds"], 600)
        self.assertLessEqual(first["delay_seconds"], 5400)


if __name__ == "__main__":
    unittest.main()
