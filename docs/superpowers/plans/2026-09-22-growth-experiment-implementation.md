# Growth Experiment Closed Loop Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn the existing chat, focus, echoes, and profile modules into one evidence-based 12-week growth experiment loop with a single active theme.

**Architecture:** Add a focused `growth.py` Flask subsystem for schema, ownership-scoped domain operations, state serialization, and growth APIs. Register it from `app.py`, extend existing task/focus/event records additively, and expose a compact growth snapshot through `/api/state`. Reuse `modeling._generate` for AI drafts, but require explicit user confirmation before capabilities, weekly experiments, tasks, or evidence become authoritative. Existing pages gain small panels rather than a fifth navigation destination.

**Tech Stack:** Python 3, Flask, SQLite, Jinja, vanilla JavaScript/CSS, `unittest`, application smoke tests.

**Spec:** `docs/superpowers/specs/2026-09-22-growth-experiment-design.md`.

## Global Constraints

- Implement `2026-09-22-model-reply-reliability.md` first so draft endpoints cannot leak malformed model protocol.
- Allow at most one active growth experiment per user; creation starts as `draft` until capabilities and week one are confirmed.
- Keep all migrations additive and preserve existing accounts, tasks, sessions, events, reviews, and exports.
- Treat AI output as a proposal. Only user-confirmed capabilities, weekly experiments, tasks, and evidence are persisted as authoritative state.
- Scope every read and mutation by `g.user['id']`; foreign IDs return the existing ownership error behavior.
- Use `BEGIN IMMEDIATE`, request IDs, and `version` checks for multi-record transitions.
- Never infer `evidenced` from elapsed time alone. Only active, user-confirmed evidence can set that state.
- A deleted or adjusted source becomes `source_missing` and must disappear from later model context.
- Do not add scores, streaks, leaderboards, social features, multi-active experiments, external storage, or a fifth navigation tab.

## Review Focus

The implementation review must explicitly verify these likely uncovered input/failure classes and their owning tests:

1. A second active experiment and simultaneous activation → `test_only_one_active_experiment_per_user`.
2. Capability lists with 2 or 8 items, duplicates, or cross-user IDs → `test_capability_confirmation_validates_count_names_and_owner`.
3. Replayed confirmation/start/finish requests → `test_confirm_and_evidence_requests_are_idempotent`.
4. Evidence referencing a task/session/event outside the experiment or another user → `test_evidence_requires_consistent_owned_sources`.
5. Source deletion/correction after evidence creation → `test_source_change_marks_evidence_missing_and_excludes_context`.
6. Stale experiment or weekly `version` → `test_stale_version_returns_409_without_partial_writes`.
7. Focus finish succeeds while evidence save fails → `test_focus_fact_survives_evidence_failure`.
8. Legacy database without growth tables/columns → `test_additive_migration_preserves_legacy_rows`.
9. Empty/unsafe AI draft and malformed protocol → modeling reliability tests plus `test_growth_draft_falls_back_without_persisting`.

---

## Task 1: Add the Growth Schema and Read Model

**Files:**

- Create: `growth.py`
- Modify: `app.py`
- Create: `test_growth_experiments.py`

- [ ] **Step 1: Add a failing additive-migration and empty-state test**

```python
def test_empty_growth_state_is_backward_compatible(self):
    state = self.client.get('/api/state').get_json()
    self.assertEqual(state['growth'], {
        'active_experiment': None, 'capabilities': [],
        'active_week': None, 'recent_evidence': []
    })

def test_additive_migration_preserves_legacy_rows(self):
    self.assertEqual(self.scalar('SELECT COUNT(*) FROM tasks WHERE title=?', ('legacy task',)), 1)
    columns = {row[1] for row in self.db.execute('PRAGMA table_info(tasks)')}
    self.assertTrue({'experiment_id', 'weekly_experiment_id', 'capability_id'} <= columns)
```

- [ ] **Step 2: Run the test and confirm the missing subsystem**

Run: `python3 -m unittest test_growth_experiments.GrowthExperimentTests.test_empty_growth_state_is_backward_compatible -v`

Expected: `/api/state` has no `growth` key.

- [ ] **Step 3: Implement `growth.py` schema and snapshot**

Define `SCHEMA` for `growth_experiments`, `capabilities`, `weekly_experiments`, `growth_evidence`, and `growth_actions`. Use the exact domain fields from the approved spec:

- `growth_experiments`: owner, title, future identity, desired outcome, start/end dates, draft/active/paused/completed status, current week, version, timestamps.
- `capabilities`: owner and experiment, name, description, target state, unverified/practicing/evidenced status, position, version, timestamps.
- `weekly_experiments`: owner and experiment, week number, hypothesis, success signal, draft/active/ready_for_review/reviewed status, version, timestamps.
- `growth_evidence`: owner, experiment, capability, weekly experiment, nullable task/session/event sources, artifact/answer/link/reflection kind, content, source label, active/revoked/source_missing status, user-confirmation flag, timestamps.
- `growth_actions`: owner/request ID idempotency key, action, entity ID, and serialized result.

Add nullable `experiment_id`, `weekly_experiment_id`, and `capability_id` columns to `tasks`; nullable `experiment_id` and `week_number` columns to `reviews`. Add indexes for every owner/parent lookup and these invariants:

```sql
CREATE UNIQUE INDEX IF NOT EXISTS one_active_growth_experiment
ON growth_experiments(user_id) WHERE status='active';
CREATE UNIQUE INDEX IF NOT EXISTS one_week_per_experiment
ON weekly_experiments(experiment_id, week_number);
CREATE UNIQUE INDEX IF NOT EXISTS one_active_week_per_experiment
ON weekly_experiments(experiment_id) WHERE status='active';
```

Implement `register_growth(app, services)` and `growth_snapshot(uid)` returning the exact empty shape above or owned active/draft experiment data. Add task columns via guarded `PRAGMA table_info` migrations. Store the snapshot callable at `app.extensions['future_self_growth_snapshot']`.

- [ ] **Step 4: Register the subsystem and include it in state/export**

In `create_app`, register growth after extras using the same service dictionary plus `nullable_owner`. In `get_state`, call the extension snapshot. In `/api/export`, include all four growth tables and the new task link columns.

- [ ] **Step 5: Run tests**

Run: `python3 -m unittest test_growth_experiments -v`

Expected: schema, legacy preservation, and empty-state tests pass.

- [ ] **Step 6: Commit**

```bash
git add growth.py app.py test_growth_experiments.py
git commit -m "feat: add growth experiment read model"
```

## Task 2: Create an Experiment and Confirm Its Capabilities

**Files:**

- Modify: `growth.py`
- Modify: `test_growth_experiments.py`

- [ ] **Step 1: Add failing ownership, count, version, and uniqueness tests**

Exercise:

- `POST /api/growth-experiments` with `title`, `future_identity`, `desired_outcome`.
- `PATCH /api/growth-experiments/<id>` with `version`.
- `POST /api/growth-experiments/<id>/capabilities/confirm` with 3–7 unique capability objects, `version`, and `request_id`.
- A second user attempting to access the first user's experiment.
- A user with an existing active experiment creating a new draft without disturbing the active one.

Name the central validation test `test_capability_confirmation_validates_count_names_and_owner`. Assert invalid counts/duplicates return 400, foreign IDs return 404, stale versions return 409, request replay returns the original result, and capability confirmation alone leaves the experiment in `draft`.

- [ ] **Step 2: Run and confirm 404s for missing routes**

Run: `python3 -m unittest test_growth_experiments -v`

Expected: new route tests fail with 404.

- [ ] **Step 3: Implement create/edit/confirm routes**

Use strict length validators, ISO dates derived from start date plus twelve weeks, and the idempotency table created in Task 1:

```sql
CREATE TABLE IF NOT EXISTS growth_actions (
 user_id INTEGER NOT NULL, request_id TEXT NOT NULL,
 action TEXT NOT NULL, entity_id INTEGER NOT NULL, result TEXT NOT NULL,
 PRIMARY KEY(user_id, request_id)
);
```

Capability confirmation runs in one `BEGIN IMMEDIATE` transaction, checks the submitted experiment `version`, replaces only draft capabilities, increments the experiment version, and returns the same serialized result on replay.

- [ ] **Step 4: Pass focused API tests**

Run: `python3 -m unittest test_growth_experiments -v`

Expected: all creation, ownership, count, idempotency, and stale-write tests pass; no confirmed draft is active yet.

- [ ] **Step 5: Commit**

```bash
git add growth.py test_growth_experiments.py
git commit -m "feat: confirm growth theme capabilities"
```

## Task 3: Generate Capability and Weekly Drafts Without Auto-Persisting

**Files:**

- Modify: `modeling.py`
- Modify: `growth.py`
- Modify: `test_growth_experiments.py`
- Modify: `test_modeling_diagnostics.py`

- [ ] **Step 1: Add failing validator tests**

Add tests for `modeling.growth_capability_draft(profile, experiment)` and `modeling.growth_weekly_draft(profile, experiment, capabilities, evidence)` asserting:

- 3–7 capability proposals with unique names and bounded descriptions.
- A weekly proposal with `hypothesis`, `success_signal`, and exactly one proposed action containing `title`, `first_step`, `done_criteria`, `planned_minutes`, `capability_name`, and `expected_evidence_kind`.
- Invalid remote output returns a local proposal and is not inserted into any table.

Name the persistence regression `test_growth_draft_falls_back_without_persisting`.

- [ ] **Step 2: Confirm missing functions/routes**

Run: `python3 -m unittest test_modeling_diagnostics test_growth_experiments -v`

Expected: missing functions and `/capability-draft`, `/weekly-draft` routes fail.

- [ ] **Step 3: Implement validated model functions**

Build prompts that distinguish aspiration from fact and forbid claims unsupported by the supplied profile/evidence. Validate bounded text, capability count, evidence kind, and 1–180 planned minutes. Use local deterministic proposals as fallback.

- [ ] **Step 4: Add non-persisting draft endpoints**

Implement:

- `POST /api/growth-experiments/<id>/capability-draft`
- `POST /api/growth-experiments/<id>/weekly-draft`

Capture experiment/profile/consent versions before generation and recheck them afterward. Return 409 when context changed. Do not persist the proposals.

- [ ] **Step 5: Pass draft tests**

Run: `python3 -m unittest test_modeling_diagnostics test_growth_experiments -v`

Expected: all tests pass and table row counts remain unchanged after draft-only calls.

- [ ] **Step 6: Commit**

```bash
git add modeling.py growth.py test_modeling_diagnostics.py test_growth_experiments.py
git commit -m "feat: draft evidence-bound growth experiments"
```

## Task 4: Confirm the Weekly Experiment and Link an Action

**Files:**

- Modify: `growth.py`
- Modify: `app.py`
- Modify: `extras.py`
- Modify: `test_growth_experiments.py`

- [ ] **Step 1: Add failing weekly confirmation tests**

Post to `PATCH /api/weekly-experiments/<id>` and assert the operation:

- validates experiment/capability ownership;
- creates or updates one weekly experiment;
- creates a linked task only when `confirm_action=true`;
- records `experiment_id`, `weekly_experiment_id`, `capability_id` on the task;
- rejects stale version without creating a task;
- returns the original task on request replay.

Add `test_only_one_active_experiment_per_user`: create two confirmed drafts, activate the first, then attempt to activate the second from another client connection. Assert one request succeeds, one returns 409, and the database contains exactly one active experiment for the user.

Add `test_stale_version_returns_409_without_partial_writes`: submit an outdated experiment or weekly version and assert neither a weekly row nor a linked task was added.

- [ ] **Step 2: Run and confirm missing route/columns behavior**

Run: `python3 -m unittest test_growth_experiments -v`

Expected: route tests fail.

- [ ] **Step 3: Implement atomic weekly confirmation**

Within `BEGIN IMMEDIATE`, verify the active experiment, valid capability, version, and request ID; mark any former active week `ready_for_review`; insert/update the target week; optionally insert the task; activate the experiment if it was draft; record the serialized response in `growth_actions`; commit once.

- [ ] **Step 4: Extend existing task create/edit APIs**

Accept optional owned growth IDs on `/api/tasks` and `/api/tasks/<id>`. Require all supplied IDs to belong to the same experiment and active user. Keep legacy task requests unchanged.

- [ ] **Step 5: Run tests and commit**

Run: `python3 -m unittest test_growth_experiments -v`

Expected: all weekly/task consistency tests pass.

```bash
git add growth.py app.py extras.py test_growth_experiments.py
git commit -m "feat: link weekly experiments to actions"
```

## Task 5: Capture Evidence After Focus Without Losing Action Facts

**Files:**

- Modify: `growth.py`
- Modify: `app.py`
- Modify: `extras.py`
- Modify: `test_growth_experiments.py`

- [ ] **Step 1: Add failing evidence consistency and failure-isolation tests**

Cover `POST /api/growth-evidence` and `PATCH /api/growth-evidence/<id>` for artifact, answer, link, and reflection. Assert source IDs are owned and linked to the same experiment. In `test_focus_fact_survives_evidence_failure`, simulate evidence insertion failure after `/api/focus/<sid>` finishes and assert the session/event/task result remains committed.

- [ ] **Step 2: Run and confirm missing evidence route**

Run: `python3 -m unittest test_growth_experiments -v`

Expected: evidence calls fail with 404.

- [ ] **Step 3: Implement explicit evidence mutation**

Evidence creation occurs only through its own request after focus completion. Require `confirmed_by_user=true`, validate `kind`, bounded `content`, `source_label`, owned source links, and request ID. Name the consistency test `test_evidence_requires_consistent_owned_sources` and the replay test `test_confirm_and_evidence_requests_are_idempotent`. Set capability to `evidenced` only when at least one active confirmed evidence row exists; otherwise leave it `practicing`.

- [ ] **Step 4: Invalidate evidence when sources change**

Expose `invalidate_growth_source(source_type, source_id)` from `growth.py`. Call it after event correction/deletion and relevant task relinking. It sets `status='source_missing'`, recomputes capability status, and increments affected versions. Name the regression `test_source_change_marks_evidence_missing_and_excludes_context`. Future snapshots and model context filter to `status='active'`.

- [ ] **Step 5: Pass tests and commit**

Run: `python3 -m unittest test_growth_experiments -v`

Expected: ownership, idempotency, source invalidation, and failure-isolation tests pass.

```bash
git add growth.py app.py extras.py test_growth_experiments.py
git commit -m "feat: record confirmed growth evidence"
```

## Task 6: Feed Confirmed Growth Facts Into Chat and Weekly Review

**Files:**

- Modify: `growth.py`
- Modify: `app.py`
- Modify: `modeling.py`
- Modify: `extras.py`
- Modify: `test_growth_experiments.py`

- [ ] **Step 1: Add failing context and review tests**

Assert chat context contains the active experiment, active week, capability names/statuses, and recent active confirmed evidence only. Assert revoked/source-missing/unconfirmed evidence is absent. Assert weekly review facts cite event/evidence IDs and next week remains a proposal until confirmed.

- [ ] **Step 2: Run and confirm missing context**

Run: `python3 -m unittest test_growth_experiments -v`

Expected: model call context lacks growth data and review linkage.

- [ ] **Step 3: Add compact `model_context(uid)`**

Return bounded data: one experiment, one active week, up to seven capabilities, and the ten newest active confirmed evidence rows with source labels/IDs. Never pass full artifacts or inactive rows.

- [ ] **Step 4: Extend chat and review orchestration**

Pass `growth_context` into `modeling.chat_reply`. Update its system prompt so future-self replies reference real recent progress only when IDs are present. Extend review generation to save `experiment_id` and `week_number`, summarize factual sessions/evidence first, and return a draft next-week proposal without auto-creating records.

- [ ] **Step 5: Pass tests and commit**

Run: `python3 -m unittest test_growth_experiments test_modeling_diagnostics -v`

Expected: only confirmed active evidence enters model calls; existing chat/review tests still pass.

```bash
git add growth.py app.py modeling.py extras.py test_growth_experiments.py
git commit -m "feat: ground future-self guidance in evidence"
```

## Task 7: Add the Creation Wizard and Growth Summary to Chat

**Files:**

- Modify: `templates/chat.html`
- Modify: `static/js/chat.js`
- Modify: `static/css/chat.css`
- Create: `test_growth_frontend.py`

- [ ] **Step 1: Add failing template contract tests**

Assert `/chat` contains `growth-summary`, `growth-create-dialog`, four labeled wizard steps, `growth-capabilities`, `growth-week`, and accessible close/submit controls. Assert script source contains calls to the four growth create/draft/confirm endpoints and renders text through `textContent` or `FS.escape`.

- [ ] **Step 2: Run and confirm missing DOM contracts**

Run: `python3 -m unittest test_growth_frontend -v`

Expected: required IDs/endpoints are absent.

- [ ] **Step 3: Implement the four-step confirmed wizard**

Steps: future identity → 12-week outcome → editable 3–7 capability proposal → editable first-week hypothesis/action. Persist only after the user confirms each relevant stage. Handle 400/409 errors inline and retain draft fields locally.

- [ ] **Step 4: Render the compact chat summary**

Show title, current week, active hypothesis, linked next action, and latest evidence source. When absent, show one “建立 12 周成长主题” entry point. Do not create a new nav item.

- [ ] **Step 5: Run tests and syntax check**

Run: `python3 -m unittest test_growth_frontend -v`

Run: `node --check static/js/chat.js`

Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add templates/chat.html static/js/chat.js static/css/chat.css test_growth_frontend.py
git commit -m "feat: create growth themes from chat"
```

## Task 8: Integrate Focus, Reflection, and the Profile Growth Map

**Files:**

- Modify: `templates/focus.html`
- Modify: `static/js/focus.js`
- Modify: `static/css/focus.css`
- Modify: `templates/echoes.html`
- Modify: `static/js/echoes.js`
- Modify: `static/css/echoes.css`
- Modify: `templates/profile.html`
- Modify: `static/js/profile.js`
- Modify: `static/css/profile.css`
- Modify: `test_growth_frontend.py`

- [ ] **Step 1: Add failing DOM and script contract tests**

Require:

- Focus: capability, hypothesis, expected evidence, and a “我卡住了” progressive-help control.
- Reflection: content/artifact-link, difficulty, effective method, capability, and next adjustment fields; evidence is submitted after the focus result call succeeds.
- Profile: a growth map with capability status labels `待验证`, `练习中`, `已有证据` and evidence source links.

- [ ] **Step 2: Run and confirm missing contracts**

Run: `python3 -m unittest test_growth_frontend -v`

Expected: new contracts fail.

- [ ] **Step 3: Implement progressive focus help**

Keep the main focus view quiet. Each click reveals the next level: guiding question → smaller first step → concrete example. Do not call the model or mutate task state automatically.

- [ ] **Step 4: Submit reflection facts before optional evidence**

Keep the existing offline focus queue for time/result/reflection. After the finish response is confirmed, post evidence separately. If it fails, retain an evidence draft locally and show a retry action; never roll back the focus event.

- [ ] **Step 5: Render the profile growth map**

Group capabilities under the active experiment, show status/basis and recent active evidence, and link source labels to `/echoes?event=...` or `/focus?task=...`. Avoid percentages and scores.

- [ ] **Step 6: Run frontend checks**

Run: `python3 -m unittest test_growth_frontend -v`

Run: `node --check static/js/focus.js && node --check static/js/echoes.js && node --check static/js/profile.js`

Expected: all pass.

- [ ] **Step 7: Commit**

```bash
git add templates/focus.html static/js/focus.js static/css/focus.css templates/echoes.html static/js/echoes.js static/css/echoes.css templates/profile.html static/js/profile.js static/css/profile.css test_growth_frontend.py
git commit -m "feat: close the focus evidence growth loop"
```

## Task 9: Complete the End-to-End Loop and Documentation

**Files:**

- Modify: `smoke.py`
- Modify: `README.md`
- Modify: `PRODUCT_HANDOFF.md`
- Modify if cache list is explicit: `static/sw.js`

- [ ] **Step 1: Add a complete smoke journey**

In one authenticated user flow:

1. Create a draft experiment.
2. Request and confirm 3 capabilities.
3. Request and confirm week one plus its linked task.
4. Start, end, and finish focus.
5. Submit confirmed reflection evidence.
6. Fetch `/api/state` and assert capability becomes `evidenced` with a source.
7. Generate weekly review and confirm the next week proposal remains unpersisted.
8. Attempt cross-user access and assert denial.
9. Replay request IDs and assert no duplicate tasks/evidence.

- [ ] **Step 2: Run all automated verification**

Run: `python3 -m unittest discover -p 'test_*.py' -v`

Run: `python3 smoke.py`

Run: `node --check static/js/chat.js && node --check static/js/focus.js && node --check static/js/echoes.js && node --check static/js/profile.js`

Run: `node test_service_worker.js`

Expected: every command passes; smoke prints `SMOKE OK`.

- [ ] **Step 3: Document the data and user contract**

Update `README.md` and `PRODUCT_HANDOFF.md` with the one-active-theme rule, four-step creation flow, evidence status semantics, failure recovery, API list, and migration/back-up notes. State explicitly that AI suggestions do not become tasks or evidence without confirmation.

- [ ] **Step 4: Verify legacy and responsive behavior manually**

- Existing users with no experiment can still chat, focus, review, and edit profile.
- Desktop and 390px mobile widths keep primary controls visible.
- Keyboard-only navigation reaches wizard, progressive help, evidence fields, and profile sources.
- Failed evidence save retains draft and never erases the completed focus record.
- Raw structured model output never appears in any draft panel.

- [ ] **Step 5: Commit**

```bash
git add smoke.py README.md PRODUCT_HANDOFF.md static/sw.js
git commit -m "test: verify the growth experiment closed loop"
```

## Final Verification

- [ ] Run `python3 -m unittest discover -p 'test_*.py' -v`.
- [ ] Run `python3 smoke.py`.
- [ ] Run all four `node --check` commands and `node test_service_worker.js`.
- [ ] Run `git diff --check`.
- [ ] Inspect `git status --short` and confirm only intentional files are present.
- [ ] In the local app, complete the full create → focus → evidence → map → weekly review loop once as the same user and attempt one cross-user URL manually.
- [ ] Confirm the login-first behavior remains unchanged for a fresh browser session.
