"""Scheduling policy for conversation-triggered future-self letters.

The policy is deliberately pure: callers decide how to persist a scheduled
letter, while this module only evaluates whether a message is eligible.
"""

from hashlib import sha256


def _stable_unit(*parts):
    payload = "|".join(str(part) for part in parts).encode("utf-8")
    return int.from_bytes(sha256(payload).digest()[:8], "big") / 2**64


def _recent(times, now, days):
    from datetime import timedelta

    return [value for value in (times or []) if now - value <= timedelta(days=days)]


def decide_chat_letter(*, user_id, message_id, message="", intent="", has_action=False,
                       recent_user_messages=None, prior_send_times=None, now,
                       roll=None, enabled=True, **_context):
    """Return a deterministic, explainable decision for one chat message."""
    recent_user_messages = recent_user_messages or []
    prior_send_times = prior_send_times or []
    reasons = []

    if not enabled:
        return {"scheduled": False, "probability": 0.0, "roll": 1.0,
                "delay_seconds": 0, "reasons": reasons, "blocked_by": "disabled"}
    if intent == "crisis" or any(token in message for token in ("不想活", "自杀", "伤害自己", "想死")):
        return {"scheduled": False, "probability": 0.0, "roll": 1.0,
                "delay_seconds": 0, "reasons": reasons, "blocked_by": "safety"}
    if len(_recent(prior_send_times, now, 7)) >= 2:
        return {"scheduled": False, "probability": 0.0, "roll": 1.0,
                "delay_seconds": 0, "reasons": reasons, "blocked_by": "weekly_limit"}
    if _recent(prior_send_times, now, 1):
        return {"scheduled": False, "probability": 0.0, "roll": 1.0,
                "delay_seconds": 0, "reasons": reasons, "blocked_by": "cooldown"}

    emotional = any(token in message for token in ("焦虑", "担心", "害怕", "难", "压力", "累", "迷茫", "沮丧"))
    if emotional:
        reasons.append("emotional_state")
    if intent in {"action", "goal", "planning"} or has_action:
        reasons.append("action_intent")
    probability = 0.08
    if emotional:
        probability += 0.16
    if intent in {"action", "goal", "planning"} or has_action:
        probability += 0.16
    probability = min(probability, 0.8)
    actual_roll = _stable_unit(user_id, message_id, message) if roll is None else float(roll)
    delay = 600 + int(_stable_unit("delay", user_id, message_id, message) * 4801)
    scheduled = actual_roll < probability
    return {"scheduled": scheduled, "probability": round(probability, 2), "roll": actual_roll,
            "delay_seconds": delay if scheduled else 0, "reasons": reasons,
            "blocked_by": None if scheduled else "random_roll"}
