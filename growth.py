"""Owner-scoped 12-week growth experiment domain and APIs."""


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

