"""Owner-scoped 12-week growth experiment domain and APIs."""

import json
from datetime import date, timedelta

from flask import abort, g, jsonify, request

import modeling


SCHEMA = """
CREATE TABLE IF NOT EXISTS growth_experiments (
 id INTEGER PRIMARY KEY,
 user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
 title TEXT NOT NULL,
 future_identity TEXT NOT NULL,
 desired_outcome TEXT NOT NULL,
 start_date TEXT NOT NULL,
 end_date TEXT NOT NULL,
 status TEXT NOT NULL DEFAULT 'draft' CHECK(status IN ('draft','active','paused','completed')),
 current_week INTEGER NOT NULL DEFAULT 1 CHECK(current_week BETWEEN 1 AND 12),
 version INTEGER NOT NULL DEFAULT 1,
 created_at TEXT NOT NULL,
 updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS capabilities (
 id INTEGER PRIMARY KEY,
 user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
 experiment_id INTEGER NOT NULL REFERENCES growth_experiments(id) ON DELETE CASCADE,
 name TEXT NOT NULL,
 description TEXT NOT NULL DEFAULT '',
 target_state TEXT NOT NULL DEFAULT '',
 status TEXT NOT NULL DEFAULT 'unverified' CHECK(status IN ('unverified','practicing','evidenced')),
 position INTEGER NOT NULL,
 version INTEGER NOT NULL DEFAULT 1,
 created_at TEXT NOT NULL,
 updated_at TEXT NOT NULL,
 UNIQUE(experiment_id, name),
 UNIQUE(experiment_id, position)
);
CREATE TABLE IF NOT EXISTS weekly_experiments (
 id INTEGER PRIMARY KEY,
 user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
 experiment_id INTEGER NOT NULL REFERENCES growth_experiments(id) ON DELETE CASCADE,
 week_number INTEGER NOT NULL CHECK(week_number BETWEEN 1 AND 12),
 hypothesis TEXT NOT NULL,
 success_signal TEXT NOT NULL,
 status TEXT NOT NULL DEFAULT 'draft' CHECK(status IN ('draft','active','ready_for_review','reviewed')),
 version INTEGER NOT NULL DEFAULT 1,
 created_at TEXT NOT NULL,
 updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS growth_evidence (
 id INTEGER PRIMARY KEY,
 user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
 experiment_id INTEGER NOT NULL REFERENCES growth_experiments(id) ON DELETE CASCADE,
 capability_id INTEGER NOT NULL REFERENCES capabilities(id) ON DELETE CASCADE,
 weekly_experiment_id INTEGER NOT NULL REFERENCES weekly_experiments(id) ON DELETE CASCADE,
 task_id INTEGER REFERENCES tasks(id) ON DELETE SET NULL,
 session_id INTEGER REFERENCES focus_sessions(id) ON DELETE SET NULL,
 event_id INTEGER REFERENCES events(id) ON DELETE SET NULL,
 kind TEXT NOT NULL CHECK(kind IN ('artifact','answer','link','reflection')),
 content TEXT NOT NULL,
 source_label TEXT NOT NULL,
 status TEXT NOT NULL DEFAULT 'active' CHECK(status IN ('active','revoked','source_missing')),
 confirmed_by_user INTEGER NOT NULL DEFAULT 0,
 created_at TEXT NOT NULL,
 updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS growth_actions (
 user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
 request_id TEXT NOT NULL,
 action TEXT NOT NULL,
 entity_id INTEGER NOT NULL,
 result TEXT NOT NULL,
 PRIMARY KEY(user_id, request_id)
);
CREATE UNIQUE INDEX IF NOT EXISTS one_active_growth_experiment
 ON growth_experiments(user_id) WHERE status='active';
CREATE UNIQUE INDEX IF NOT EXISTS one_week_per_experiment
 ON weekly_experiments(experiment_id, week_number);
CREATE UNIQUE INDEX IF NOT EXISTS one_active_week_per_experiment
 ON weekly_experiments(experiment_id) WHERE status='active';
CREATE INDEX IF NOT EXISTS capabilities_owner ON capabilities(user_id, experiment_id, position);
CREATE INDEX IF NOT EXISTS weekly_experiments_owner ON weekly_experiments(user_id, experiment_id, week_number);
CREATE INDEX IF NOT EXISTS growth_evidence_owner ON growth_evidence(user_id, experiment_id, id);
"""


def register_growth(app, services):
    db, row, rows = (services[key] for key in ("db", "row", "rows"))
    owned, auth, data = (services[key] for key in ("owned", "require_auth", "data"))
    text, number, now = (services[key] for key in ("text", "number", "now"))
    get_profile, model_profile = (services[key] for key in ("get_profile", "model_profile"))

    with app.app_context():
        db().executescript(SCHEMA)
        additions = {
            "tasks": ("experiment_id", "weekly_experiment_id", "capability_id"),
            "reviews": ("experiment_id", "week_number"),
        }
        for table, names in additions.items():
            existing = {item["name"] for item in db().execute(f"PRAGMA table_info({table})")}
            for name in names:
                if name not in existing:
                    db().execute(f"ALTER TABLE {table} ADD COLUMN {name} INTEGER")
        db().commit()

    def growth_snapshot(uid):
        experiment = row(
            """SELECT * FROM growth_experiments WHERE user_id=?
               ORDER BY CASE status WHEN 'active' THEN 0 WHEN 'draft' THEN 1 ELSE 2 END, id DESC LIMIT 1""",
            (uid,),
        )
        if not experiment:
            return {
                "active_experiment": None,
                "capabilities": [],
                "active_week": None,
                "recent_evidence": [],
            }
        experiment_id = experiment["id"]
        return {
            "active_experiment": experiment,
            "capabilities": rows(
                "SELECT * FROM capabilities WHERE user_id=? AND experiment_id=? ORDER BY position,id",
                (uid, experiment_id),
            ),
            "active_week": row(
                """SELECT * FROM weekly_experiments
                   WHERE user_id=? AND experiment_id=? AND status='active' ORDER BY week_number DESC LIMIT 1""",
                (uid, experiment_id),
            ),
            "recent_evidence": rows(
                """SELECT * FROM growth_evidence
                   WHERE user_id=? AND experiment_id=? AND status='active' AND confirmed_by_user=1
                   ORDER BY id DESC LIMIT 10""",
                (uid, experiment_id),
            ),
        }

    app.extensions["future_self_growth_snapshot"] = growth_snapshot

    def bounded(value, label, limit, required=True):
        if not isinstance(value, str) or len(value) > limit:
            abort(400, description=f"{label} 需要不超过 {limit} 字的文本。")
        value = value.strip()
        if required and not value:
            abort(400, description=f"请填写{label}。")
        return value

    @app.route("/api/growth-experiments", methods=["GET", "POST"])
    @auth
    def growth_experiments():
        if request.method == "GET":
            return jsonify(
                experiments=rows(
                    "SELECT * FROM growth_experiments WHERE user_id=? ORDER BY id DESC",
                    (g.user["id"],),
                )
            )
        body = data()
        start = date.today()
        stamp = now()
        experiment_id = db().execute(
            """INSERT INTO growth_experiments(
                 user_id,title,future_identity,desired_outcome,start_date,end_date,created_at,updated_at)
               VALUES(?,?,?,?,?,?,?,?)""",
            (
                g.user["id"],
                text(body, "title", 160, True),
                text(body, "future_identity", 1000, True),
                text(body, "desired_outcome", 1000, True),
                start.isoformat(),
                (start + timedelta(weeks=12)).isoformat(),
                stamp,
                stamp,
            ),
        ).lastrowid
        db().commit()
        return jsonify(experiment=owned("growth_experiments", experiment_id)), 201

    @app.patch("/api/growth-experiments/<int:experiment_id>")
    @auth
    def update_growth_experiment(experiment_id):
        experiment = owned("growth_experiments", experiment_id)
        body = data()
        if number(body, "version") != experiment["version"]:
            abort(409, description="成长主题刚有更新，请刷新后重试。")
        status = body.get("status", experiment["status"])
        if status not in ("draft", "paused", "completed") and status != experiment["status"]:
            abort(400, description="请通过确认周实验来激活成长主题。")
        db().execute(
            """UPDATE growth_experiments SET title=?,future_identity=?,desired_outcome=?,
               status=?,version=version+1,updated_at=? WHERE id=? AND user_id=?""",
            (
                text(body, "title", 160, True, experiment["title"]),
                text(body, "future_identity", 1000, True, experiment["future_identity"]),
                text(body, "desired_outcome", 1000, True, experiment["desired_outcome"]),
                status,
                now(),
                experiment_id,
                g.user["id"],
            ),
        )
        db().commit()
        return jsonify(experiment=owned("growth_experiments", experiment_id))

    @app.post("/api/growth-experiments/<int:experiment_id>/capabilities/confirm")
    @auth
    def confirm_capabilities(experiment_id):
        body = data()
        request_id = text(body, "request_id", 100, True)
        connection = db()
        connection.execute("BEGIN IMMEDIATE")
        repeated = row(
            "SELECT result FROM growth_actions WHERE user_id=? AND request_id=?",
            (g.user["id"], request_id),
        )
        if repeated:
            connection.commit()
            return jsonify(json.loads(repeated["result"]))
        experiment = owned("growth_experiments", experiment_id)
        if experiment["status"] != "draft":
            connection.rollback()
            abort(409, description="只能调整尚未激活的能力草案。")
        if number(body, "version") != experiment["version"]:
            connection.rollback()
            abort(409, description="成长主题刚有更新，请刷新后重试。")
        submitted = body.get("capabilities")
        if not isinstance(submitted, list) or not 3 <= len(submitted) <= 7:
            connection.rollback()
            abort(400, description="请确认 3 至 7 项能力。")
        normalized = []
        names = set()
        for position, item in enumerate(submitted, 1):
            if not isinstance(item, dict):
                connection.rollback()
                abort(400, description="能力格式未识别。")
            name = bounded(item.get("name"), "能力名称", 80)
            key = name.casefold()
            if key in names:
                connection.rollback()
                abort(400, description="能力名称不能重复。")
            names.add(key)
            normalized.append(
                (
                    name,
                    bounded(item.get("description", ""), "能力说明", 500, False),
                    bounded(item.get("target_state", ""), "目标状态", 500, False),
                    position,
                )
            )
        stamp = now()
        connection.execute(
            "DELETE FROM capabilities WHERE user_id=? AND experiment_id=?",
            (g.user["id"], experiment_id),
        )
        connection.executemany(
            """INSERT INTO capabilities(
                 user_id,experiment_id,name,description,target_state,position,created_at,updated_at)
               VALUES(?,?,?,?,?,?,?,?)""",
            [
                (g.user["id"], experiment_id, name, description, target, position, stamp, stamp)
                for name, description, target, position in normalized
            ],
        )
        connection.execute(
            "UPDATE growth_experiments SET version=version+1,updated_at=? WHERE id=?",
            (stamp, experiment_id),
        )
        result = {
            "experiment": row("SELECT * FROM growth_experiments WHERE id=?", (experiment_id,)),
            "capabilities": rows(
                "SELECT * FROM capabilities WHERE user_id=? AND experiment_id=? ORDER BY position",
                (g.user["id"], experiment_id),
            ),
        }
        connection.execute(
            "INSERT INTO growth_actions VALUES(?,?,?,?,?)",
            (g.user["id"], request_id, "confirm_capabilities", experiment_id, json.dumps(result, ensure_ascii=False)),
        )
        connection.commit()
        return jsonify(result)

    def generation_context(experiment_id):
        experiment = owned("growth_experiments", experiment_id)
        return experiment, get_profile()["version"], g.user["consent_version"]

    def verify_context(experiment, profile_version, consent_version):
        current = owned("growth_experiments", experiment["id"])
        if (current["version"] != experiment["version"] or get_profile()["version"] != profile_version
                or g.user["consent_version"] != consent_version):
            abort(409, description="成长主题或授权刚有更新，请重新生成草案。")

    @app.post("/api/growth-experiments/<int:experiment_id>/capability-draft")
    @auth
    def capability_draft(experiment_id):
        experiment, profile_version, consent_version = generation_context(experiment_id)
        result = modeling.growth_capability_draft(model_profile(), experiment)
        verify_context(experiment, profile_version, consent_version)
        return jsonify(result)

    @app.post("/api/growth-experiments/<int:experiment_id>/weekly-draft")
    @auth
    def weekly_draft(experiment_id):
        experiment, profile_version, consent_version = generation_context(experiment_id)
        capabilities = rows(
            "SELECT * FROM capabilities WHERE user_id=? AND experiment_id=? ORDER BY position",
            (g.user["id"], experiment_id),
        )
        if not 3 <= len(capabilities) <= 7:
            abort(409, description="请先确认 3 至 7 项能力。")
        evidence = rows(
            """SELECT * FROM growth_evidence WHERE user_id=? AND experiment_id=?
               AND status='active' AND confirmed_by_user=1 ORDER BY id DESC LIMIT 10""",
            (g.user["id"], experiment_id),
        )
        result = modeling.growth_weekly_draft(model_profile(), experiment, capabilities, evidence)
        verify_context(experiment, profile_version, consent_version)
        return jsonify(result)
