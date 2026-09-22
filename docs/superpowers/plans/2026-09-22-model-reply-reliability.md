# Model Reply Reliability Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Never render or persist malformed model protocol JSON, while preserving valid natural-language replies from compatible providers and recording safe failure categories.

**Architecture:** Keep provider-envelope inspection in `provider_response.py` and orchestration in `modeling._generate`. A provider response is classified before any plain-text fallback: valid protocol JSON is validated, invalid structured-looking output receives one repair attempt, and only clearly natural prose may use the plain-text adapter. All other failures return the existing local fallback with a non-sensitive category.

**Tech Stack:** Python 3, Flask, OpenAI-compatible chat-completions envelopes, `urllib`, `unittest`.

**Spec:** `docs/superpowers/specs/2026-09-22-growth-experiment-design.md` — “模型回复可靠性” and “监控与错误恢复”.

## Global Constraints

- Preserve support for string, content-part list, and `reasoning_content` provider shapes.
- Never log API keys, prompt content, user text, raw provider bodies, or model output.
- Keep the fifteen-second total deadline and the maximum of one schema-repair request.
- A reply beginning with `{`, `[`, a JSON code fence, or known protocol field names is structured-looking and must never enter `plain_text`.
- Only validated replies may reach `/api/chat` persistence.
- Do not change prompt tone, action suggestion semantics, or valid provider behavior.

## Review Focus

The implementation review must explicitly verify these failure/input classes and their owning tests:

1. Truncated JSON (`{"reply_text": ...`) → `test_truncated_protocol_never_becomes_plain_text`.
2. JSON fenced or array-prefixed malformed output → `test_structured_markers_are_detected`.
3. Provider `finish_reason="length"` despite parseable content → `test_length_finish_reason_requires_repair`.
4. Valid natural Chinese prose → `test_chat_reply_keeps_plain_text_from_compatible_provider`.
5. Second invalid response after repair → `test_second_invalid_protocol_uses_safe_local_fallback`.
6. Missing choices/message/content → existing and extended parser validation tests.
7. Sensitive upstream error details → existing `test_generate_logs_http_status_without_sensitive_details`.

---

## Task 1: Classify Provider Completion and Content Shape

**Files:**

- Modify: `provider_response.py`
- Modify: `test_provider_harness.py`

- [ ] **Step 1: Add failing classification tests**

```python
from provider_response import assistant_finish_reason, looks_structured

def test_structured_markers_are_detected(self):
    for value in ('{"reply_text":', '[{"reply_text":', '```json\n{"reply_text":', 'reply_text: 你好'):
        with self.subTest(value=value):
            self.assertTrue(looks_structured(value))
    self.assertFalse(looks_structured('先停一下，我们把第一步缩小。'))

def test_finish_reason_is_normalized(self):
    self.assertEqual(assistant_finish_reason({"choices": [{"finish_reason": "length", "message": {"content": "x"}}]}), "length")
    self.assertEqual(assistant_finish_reason({"choices": [{"message": {"content": "x"}}]}), "unknown")
```

- [ ] **Step 2: Run the tests and confirm the expected failure**

Run: `python3 -m unittest test_provider_harness.ProviderHarnessTests.test_structured_markers_are_detected test_provider_harness.ProviderHarnessTests.test_finish_reason_is_normalized -v`

Expected: import errors because `looks_structured` and `assistant_finish_reason` do not exist.

- [ ] **Step 3: Implement pure classification helpers**

```python
_PROTOCOL_FIELD = re.compile(r'(?i)(?:^|[,{\s"])(reply_text|intent|action_suggestion|evidence_ids)\s*[":]')

def looks_structured(text):
    value = text.lstrip()
    return value.startswith(('{', '[', '```')) or bool(_PROTOCOL_FIELD.search(value[:400]))

def assistant_finish_reason(envelope):
    try:
        value = envelope['choices'][0].get('finish_reason')
        return value if isinstance(value, str) and value else 'unknown'
    except (KeyError, IndexError, TypeError):
        return 'unknown'
```

- [ ] **Step 4: Run parser tests**

Run: `python3 -m unittest test_provider_harness -v`

Expected: all provider harness tests pass.

- [ ] **Step 5: Commit**

```bash
git add provider_response.py test_provider_harness.py
git commit -m "test: classify structured provider replies"
```

## Task 2: Reject Truncation and Structured-Looking Plain Fallbacks

**Files:**

- Modify: `modeling.py`
- Modify: `test_modeling_diagnostics.py`

- [ ] **Step 1: Add a response sequence helper and failing regression tests**

```python
def test_truncated_protocol_never_becomes_plain_text(self):
    broken = {"choices": [{"finish_reason": "length", "message": {"content": '{"reply_text":"不要显示我"'}}]}
    with self._configured_provider(), patch("modeling.urllib.request.urlopen", side_effect=[self._Response(broken), self._Response(broken)]):
        result = modeling.chat_reply("你好", {"tone": "清晰"}, [], [], {"feedback": []})
    self.assertEqual(result["model"]["mode"], "local")
    self.assertNotIn("reply_text", result["reply_text"])
    self.assertNotIn("不要显示我", result["reply_text"])

def test_length_finish_reason_requires_repair(self):
    first = {"choices": [{"finish_reason": "length", "message": {"content": '{"reply_text":"看似完整","intent":"listen","action_suggestion":null,"evidence_ids":[]}'}}]}
    second = {"choices": [{"finish_reason": "stop", "message": {"content": '{"reply_text":"修复后的回答","intent":"listen","action_suggestion":null,"evidence_ids":[]}'}}]}
    with self._configured_provider(), patch("modeling.urllib.request.urlopen", side_effect=[self._Response(first), self._Response(second)]) as mocked:
        result = modeling.chat_reply("你好", {"tone": "清晰"}, [], [], {"feedback": []})
    self.assertEqual(mocked.call_count, 2)
    self.assertEqual(result["reply_text"], "修复后的回答")
```

- [ ] **Step 2: Run the new tests and confirm the bug**

Run: `python3 -m unittest test_modeling_diagnostics.ProviderDiagnosticsTests.test_truncated_protocol_never_becomes_plain_text test_modeling_diagnostics.ProviderDiagnosticsTests.test_length_finish_reason_requires_repair -v`

Expected: the first test exposes raw JSON or the second accepts the first response without repair.

- [ ] **Step 3: Gate parsing and plain-text adaptation in `_generate`**

Import the helpers and classify the envelope before validation:

```python
finish_reason = assistant_finish_reason(envelope)
visible = assistant_text(envelope)
if finish_reason == "length":
    raise ValueError("truncated_response")
try:
    result = validate(assistant_json(envelope))
    return {**result, "model": _model_meta()}
except (ValueError, TypeError, KeyError, IndexError):
    if plain_text is not None and not looks_structured(visible):
        result = plain_text(visible)
        return {**result, "model": _model_meta()}
    raise ValueError("invalid_schema")
```

Keep the classification inside the existing two-attempt loop so the first invalid response triggers exactly one repair prompt and the second reaches the local fallback.

- [ ] **Step 4: Add and pass the exhausted-repair test**

```python
def test_second_invalid_protocol_uses_safe_local_fallback(self):
    bad = {"choices": [{"finish_reason": "stop", "message": {"content": '```json\n{"reply_text":'}}]}
    with self._configured_provider(), patch("modeling.urllib.request.urlopen", side_effect=[self._Response(bad), self._Response(bad)]):
        with self.assertLogs("self_echo.modeling", level="WARNING") as logs:
            result = modeling.chat_reply("你好", {"tone": "清晰"}, [], [], {"feedback": []})
    self.assertEqual(result["model"]["mode"], "local")
    self.assertIn("category=response_validation", "\n".join(logs.output))
    self.assertNotIn("reply_text", result["reply_text"])
```

Run: `python3 -m unittest test_modeling_diagnostics -v`

Expected: all diagnostics pass, including the existing natural-language compatibility test.

- [ ] **Step 5: Commit**

```bash
git add modeling.py test_modeling_diagnostics.py
git commit -m "fix: contain malformed model protocol replies"
```

## Task 3: Prove Persistence Safety at the Flask Boundary

**Files:**

- Create: `test_chat_protocol_safety.py`
- Modify only if the test exposes a gap: `app.py`

- [ ] **Step 1: Add an authenticated API regression test**

Create a temporary database app, register a user through the existing auth endpoint, patch `modeling.chat_reply`, and assert:

```python
def test_chat_persists_only_visible_valid_reply(self):
    safe = {"reply_text": "先做一个五分钟的小实验。", "intent": "listen",
            "action_suggestion": None, "evidence_ids": [],
            "model": {"mode": "local", "label": "本地规则", "available": False}}
    with patch("app.modeling.chat_reply", return_value=safe):
        response = self.client.post("/api/chat", json={"message": "我卡住了", "request_id": "safe-1"}, headers=self.csrf)
    self.assertEqual(response.status_code, 200)
    state = self.client.get("/api/state").get_json()
    self.assertEqual(state["messages"][-1]["content"], safe["reply_text"])
    self.assertFalse(state["messages"][-1]["content"].lstrip().startswith("{"))
```

Add a second test where `chat_reply` raises `ValueError`; assert HTTP 503 and no assistant row is inserted.

- [ ] **Step 2: Run the test and confirm current boundary behavior**

Run: `python3 -m unittest test_chat_protocol_safety -v`

Expected: pass. If it fails, make the smallest change in `app.py` so assistant persistence happens only after a non-empty validated `reply_text`; do not duplicate provider-shape logic in Flask.

- [ ] **Step 3: Run the focused reliability suite**

Run: `python3 -m unittest test_provider_harness test_modeling_diagnostics test_chat_protocol_safety -v`

Expected: all tests pass.

- [ ] **Step 4: Run the full regression suite**

Run: `python3 -m unittest discover -p 'test_*.py' -v`

Expected: all Python tests pass with no secrets or raw provider content in logs.

- [ ] **Step 5: Commit**

```bash
git add test_chat_protocol_safety.py app.py
git commit -m "test: guard chat persistence from protocol failures"
```

## Task 4: Verify the User-Visible Failure Path

**Files:**

- Modify: `smoke.py`
- Modify: `README.md`

- [ ] **Step 1: Extend smoke coverage**

Patch the model response in the smoke fixture to return one malformed protocol attempt followed by a valid repair; verify `/api/chat` contains only the repaired natural-language text. Then force two invalid responses and verify a readable local fallback appears without braces or protocol field names.

- [ ] **Step 2: Run smoke and browser-independent JavaScript checks**

Run: `python3 smoke.py`

Expected: `SMOKE OK`.

Run: `node --check static/js/chat.js`

Expected: exit code 0.

- [ ] **Step 3: Document behavior**

In `README.md`, state that compatible providers may return protocol JSON or natural prose, malformed structured output is repaired once, and exhausted failures degrade to a safe local reply without storing the raw provider response.

- [ ] **Step 4: Commit**

```bash
git add smoke.py README.md
git commit -m "docs: describe safe model reply fallback"
```

## Final Verification

- [ ] Run `python3 -m unittest discover -p 'test_*.py' -v`.
- [ ] Run `python3 smoke.py`.
- [ ] Run `node --check static/js/chat.js`.
- [ ] Search for accidental secret or body logging: `rg -n "AI_API_KEY|logger\..*(raw|content|prompt|message)" modeling.py provider_response.py` and inspect every match.
- [ ] Manually send one valid prose reply, one valid JSON reply, and one truncated JSON reply against a stub provider; confirm only human-readable text appears in chat history.

