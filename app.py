"""明日见 Self Echo: a small Flask/Jinja application with owner-scoped SQLite records."""
import hashlib
import json
import math
import os
import re
import secrets
import sqlite3
import time
import threading
from datetime import date, datetime, timezone
from functools import wraps
from pathlib import Path

from flask import Flask, abort, g, has_request_context, jsonify, redirect, render_template, request, session, url_for
from werkzeug.security import check_password_hash, generate_password_hash

import modeling


SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
 id INTEGER PRIMARY KEY, name TEXT NOT NULL, email TEXT NOT NULL UNIQUE,
 password_hash TEXT, is_demo INTEGER NOT NULL DEFAULT 0,
 memory_enabled INTEGER NOT NULL DEFAULT 0, onboarded INTEGER NOT NULL DEFAULT 0,
 auto_letters INTEGER NOT NULL DEFAULT 1, auth_version INTEGER NOT NULL DEFAULT 1,
 created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS profiles (
 user_id INTEGER PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
 ideal TEXT NOT NULL DEFAULT '', "values" TEXT NOT NULL DEFAULT '',
 current TEXT NOT NULL DEFAULT '', conditions TEXT NOT NULL DEFAULT '',
 tone TEXT NOT NULL DEFAULT '', version INTEGER NOT NULL DEFAULT 1,
 answers TEXT NOT NULL DEFAULT '["","","","",""]', updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS messages (
 id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
 role TEXT NOT NULL, content TEXT NOT NULL, metadata TEXT NOT NULL DEFAULT '{}', created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS chat_requests (
 user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
 request_id TEXT NOT NULL, status TEXT NOT NULL, result TEXT, message_id INTEGER, started_at REAL NOT NULL,
 PRIMARY KEY(user_id, request_id)
);
CREATE TABLE IF NOT EXISTS tasks (
 id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
 title TEXT NOT NULL, first_step TEXT NOT NULL, done_criteria TEXT NOT NULL,
 planned_minutes INTEGER NOT NULL CHECK(planned_minutes BETWEEN 1 AND 180),
 source_message_id INTEGER REFERENCES messages(id) ON DELETE SET NULL,
 status TEXT NOT NULL DEFAULT 'ready', created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS focus_sessions (
 id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
 task_id INTEGER NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
 title TEXT NOT NULL, planned_minutes INTEGER NOT NULL, status TEXT NOT NULL,
 elapsed_seconds REAL NOT NULL DEFAULT 0, running_since REAL,
 started_at TEXT NOT NULL, ended_at TEXT, result TEXT, reflection TEXT NOT NULL DEFAULT ''
);
CREATE UNIQUE INDEX IF NOT EXISTS one_active_focus ON focus_sessions(user_id) WHERE status != 'ended';
CREATE TABLE IF NOT EXISTS focus_intervals (
 id INTEGER PRIMARY KEY, session_id INTEGER NOT NULL REFERENCES focus_sessions(id) ON DELETE CASCADE,
 started_at REAL NOT NULL, ended_at REAL
);
CREATE TABLE IF NOT EXISTS focus_actions (
 user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
 request_id TEXT NOT NULL, session_id INTEGER NOT NULL REFERENCES focus_sessions(id) ON DELETE CASCADE,
 action TEXT NOT NULL, PRIMARY KEY(user_id, request_id)
);
CREATE TABLE IF NOT EXISTS events (
 id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
 session_id INTEGER NOT NULL UNIQUE REFERENCES focus_sessions(id) ON DELETE CASCADE,
 title TEXT NOT NULL, result TEXT NOT NULL, elapsed_seconds REAL NOT NULL,
 reflection TEXT NOT NULL, created_at TEXT NOT NULL, letter_status TEXT NOT NULL DEFAULT 'pending'
);
CREATE TABLE IF NOT EXISTS letters (
 id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
 title TEXT NOT NULL, body TEXT NOT NULL, direction TEXT NOT NULL,
 created_at TEXT NOT NULL, is_read INTEGER NOT NULL DEFAULT 0,
 source_id INTEGER UNIQUE REFERENCES events(id) ON DELETE CASCADE,
 allow_memory INTEGER NOT NULL DEFAULT 0, persona_version INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS memories (
 id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
 content TEXT NOT NULL, kind TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'candidate',
 source_type TEXT NOT NULL, source_id INTEGER NOT NULL, created_at TEXT NOT NULL,
 UNIQUE(user_id,source_type,source_id)
);
CREATE TABLE IF NOT EXISTS milestones (
 id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
 title TEXT NOT NULL, date TEXT NOT NULL, completed INTEGER NOT NULL DEFAULT 0, created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS login_attempts (key TEXT PRIMARY KEY, count INTEGER NOT NULL, started_at REAL NOT NULL);
CREATE INDEX IF NOT EXISTS messages_owner ON messages(user_id,id);
CREATE INDEX IF NOT EXISTS sessions_owner ON focus_sessions(user_id,id);
"""


def now():
    return datetime.now(timezone.utc).isoformat(timespec='milliseconds')


def create_app(test_config=None):
    app = Flask(__name__, instance_relative_config=True)
    Path(app.instance_path).mkdir(parents=True, exist_ok=True)
    secret_path = Path(app.instance_path) / '.session-secret'
    secret = os.environ.get('SECRET_KEY')
    if not secret:
        try:
            with secret_path.open('x', encoding='utf-8') as file:
                file.write(secrets.token_hex(32))
            try:
                secret_path.chmod(0o600)
            except OSError:
                pass
        except FileExistsError:
            pass
        secret = secret_path.read_text(encoding='utf-8').strip()
    app.config.update(
        SECRET_KEY=secret, DATABASE=str(Path(app.instance_path) / 'future_self.db'),
        MAX_CONTENT_LENGTH=65536, SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE='Lax', SESSION_COOKIE_SECURE=os.environ.get('COOKIE_SECURE') == '1',
        MODELSCOPE_STUDIO=os.environ.get('MODELSCOPE_STUDIO') == '1',
        STARTUP_NONCE=secrets.token_urlsafe(24),
    )
    if test_config:
        app.config.update(test_config)

    def db():
        if 'db' not in g:
            g.db = sqlite3.connect(app.config['DATABASE'], timeout=15)
            g.db.row_factory = sqlite3.Row
            g.db.execute('PRAGMA foreign_keys=ON')
            g.db.execute('PRAGMA busy_timeout=15000')
        return g.db

    @app.teardown_appcontext
    def close_db(error=None):
        connection = g.pop('db', None)
        if connection:
            connection.close()

    with app.app_context():
        db().executescript(SCHEMA)
        # Additive migration keeps every existing account and recorded action.
        additions = {
            'users': {'profile_reuse_enabled': 'INTEGER NOT NULL DEFAULT 0', 'consent_version': 'INTEGER NOT NULL DEFAULT 1'},
            'profiles': {'manual_confirmed': 'INTEGER NOT NULL DEFAULT 0', 'manual_fields': "TEXT NOT NULL DEFAULT '[]'"},
            'tasks': {'goal_id': 'INTEGER', 'milestone_id': 'INTEGER'},
            'milestones': {'goal_id': 'INTEGER'},
            'focus_sessions': {'timing_review_required': 'INTEGER NOT NULL DEFAULT 0', 'last_action_at': 'REAL'},
            'events': {'revision': 'INTEGER NOT NULL DEFAULT 1'},
            'letters': {'source_adjusted': 'INTEGER NOT NULL DEFAULT 0', 'revision': 'INTEGER NOT NULL DEFAULT 1', 'job_id': 'INTEGER', 'open_at': 'TEXT'},
        }
        for table, columns in additions.items():
            existing = {record[1] for record in db().execute(f'PRAGMA table_info({table})')}
            for column, definition in columns.items():
                if column not in existing:
                    db().execute(f'ALTER TABLE {table} ADD COLUMN {column} {definition}')
                    if table == 'profiles' and column == 'manual_fields':
                        db().execute('UPDATE profiles SET manual_fields=? WHERE manual_confirmed=1', (json.dumps(['ideal', 'values', 'current', 'conditions', 'tone']),))
        if 'field' not in {record[1] for record in db().execute('PRAGMA table_info(memories)')}:
            db().execute('ALTER TABLE memories RENAME TO memories_v1')
            db().execute("""CREATE TABLE memories (
                id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                content TEXT NOT NULL,kind TEXT NOT NULL,status TEXT NOT NULL DEFAULT 'candidate',
                source_type TEXT NOT NULL,source_id INTEGER NOT NULL,created_at TEXT NOT NULL,
                field TEXT NOT NULL DEFAULT 'conditions',proposed_value TEXT NOT NULL DEFAULT '',
                reason TEXT NOT NULL DEFAULT '',evidence_ids TEXT NOT NULL DEFAULT '[]',
                confidence TEXT NOT NULL DEFAULT '待用户确认',signature TEXT NOT NULL DEFAULT '',
                locked INTEGER NOT NULL DEFAULT 0,conflicts_with TEXT NOT NULL DEFAULT '[]')""")
            db().execute("""INSERT INTO memories(id,user_id,content,kind,status,source_type,source_id,created_at,proposed_value,locked)
                SELECT id,user_id,content,kind,status,source_type,source_id,created_at,content,CASE WHEN kind='correction' THEN 1 ELSE 0 END FROM memories_v1""")
            db().execute('DROP TABLE memories_v1')
        db().executescript("""
            CREATE TABLE IF NOT EXISTS memory_tombstones(user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
              signature TEXT NOT NULL,created_at TEXT NOT NULL,PRIMARY KEY(user_id,signature));
            CREATE TABLE IF NOT EXISTS session_profiles(token TEXT PRIMARY KEY,user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
              profile_json TEXT NOT NULL,created_at TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS message_feedback(user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
              message_id INTEGER NOT NULL REFERENCES messages(id) ON DELETE CASCADE,feedback TEXT NOT NULL,created_at TEXT NOT NULL,
              PRIMARY KEY(user_id,message_id,feedback));
            CREATE TABLE IF NOT EXISTS jobs(id INTEGER PRIMARY KEY,user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
              kind TEXT NOT NULL,source_type TEXT NOT NULL,source_id INTEGER NOT NULL,payload TEXT NOT NULL DEFAULT '{}',
              status TEXT NOT NULL DEFAULT 'pending',attempts INTEGER NOT NULL DEFAULT 0,available_at REAL NOT NULL,
              locked_at REAL,created_at TEXT NOT NULL,updated_at TEXT NOT NULL,last_error TEXT NOT NULL DEFAULT '',
              profile_version INTEGER NOT NULL,consent_version INTEGER NOT NULL,source_revision INTEGER NOT NULL,
              dedup_key TEXT NOT NULL UNIQUE);
            CREATE UNIQUE INDEX IF NOT EXISTS letter_job ON letters(job_id) WHERE job_id IS NOT NULL;
            CREATE INDEX IF NOT EXISTS jobs_due ON jobs(status,available_at);
        """)
        for item in db().execute("SELECT id,user_id,content,source_type,source_id,status FROM memories WHERE signature='' ").fetchall():
            signature = hashlib.sha256(re.sub(r'[\W_]+', '', item['content'].lower()).encode()).hexdigest()
            evidence = json.dumps([{'source_type': item['source_type'], 'source_id': item['source_id'], 'revision': 1}])
            db().execute('UPDATE memories SET signature=?,evidence_ids=? WHERE id=?', (signature, evidence, item['id']))
            if item['status'] == 'rejected':
                db().execute('INSERT OR IGNORE INTO memory_tombstones VALUES(?,?,?)', (item['user_id'], signature, now()))
                db().execute('DELETE FROM memories WHERE id=?', (item['id'],))
        db().commit()

    def row(sql, parameters=()):
        found = db().execute(sql, parameters).fetchone()
        return dict(found) if found else None

    def rows(sql, parameters=()):
        return [dict(item) for item in db().execute(sql, parameters).fetchall()]

    def user_public(user):
        if not user:
            return None
        return {key: bool(user[key]) if key in ('is_demo', 'memory_enabled', 'onboarded', 'auto_letters', 'profile_reuse_enabled') else user[key]
                for key in ('id', 'name', 'email', 'is_demo', 'memory_enabled', 'onboarded', 'auto_letters', 'profile_reuse_enabled', 'created_at')}

    def data():
        body = request.get_json(silent=True)
        if not isinstance(body, dict):
            abort(400, description='请求需要 JSON 对象。')
        return body

    def text(body, key, limit=2000, required=False, default=''):
        value = body.get(key, default)
        if not isinstance(value, str) or len(value) > limit:
            abort(400, description=f'{key} 需要不超过 {limit} 字的文本。')
        value = value.strip()
        if required and not value:
            abort(400, description=f'请填写 {key}。')
        return value

    def boolean(body, key, default=False):
        value = body.get(key, default)
        if not isinstance(value, bool):
            abort(400, description=f'{key} 需要布尔值。')
        return value

    def number(body, key, minimum=1, maximum=2147483647):
        value = body.get(key)
        if isinstance(value, bool) or not isinstance(value, int) or not minimum <= value <= maximum:
            abort(400, description=f'{key} 需要 {minimum} 至 {maximum} 之间的整数。')
        return value

    def nullable_owner(body, key, table):
        if body.get(key) is None:
            return None
        value = number(body, key)
        owned(table, value)
        return value

    def action_time(body, item=None):
        timestamp = time.time()
        offline = boolean(body, 'offline')
        supplied = body.get('occurred_at', timestamp)
        if isinstance(supplied, bool) or not isinstance(supplied, (int, float)) or not math.isfinite(supplied):
            abort(400, description='操作时间需要有效的 Unix 秒数。')
        if supplied > timestamp + 5 or supplied < timestamp - 604800:
            abort(400, description='操作时间超出可同步的 7 天范围，请修正记录。')
        supplied = min(timestamp, supplied)
        previous = item.get('last_action_at') if item else None
        if item and not previous:
            previous = item.get('running_since') or datetime.fromisoformat(item['started_at']).timestamp()
        if previous and supplied < previous:
            abort(409, description='请按发生顺序同步沉浸操作。')
        if offline and not body.get('request_id'):
            abort(400, description='离线同步需要操作唯一标识。')
        return supplied, offline

    def owned(table, item_id):
        # Table names only come from route code, never from submitted data.
        item = row(f'SELECT * FROM {table} WHERE id=? AND user_id=?', (item_id, g.user['id']))
        if not item:
            abort(404, description='记录不存在。')
        return item

    def require_auth(function):
        @wraps(function)
        def wrapped(*args, **kwargs):
            if not g.user:
                if request.path.startswith('/api/'):
                    abort(401, description='请先登录。')
                return redirect(url_for('login'))
            return function(*args, **kwargs)
        return wrapped

    @app.before_request
    def load_identity():
        user_id = session.get('user_id')
        startup_nonce = str(session.get('startup_nonce', ''))
        if user_id and not secrets.compare_digest(startup_nonce, str(app.config['STARTUP_NONCE'])):
            session.clear()
            user_id = None
        g.user = row('SELECT * FROM users WHERE id=?', (user_id,)) if user_id else None
        if g.user and session.get('auth_version') != g.user['auth_version']:
            session.clear()
            g.user = None
        if 'csrf_token' not in session:
            session['csrf_token'] = secrets.token_urlsafe(32)
        if request.path.startswith('/api/') and not g.user:
            abort(401, description='请先登录。')
        if request.method in ('POST', 'PATCH', 'PUT', 'DELETE'):
            token = request.headers.get('X-CSRF-Token') or request.form.get('csrf_token') or ''
            if not secrets.compare_digest(token.encode('utf-8'), session['csrf_token'].encode('utf-8')):
                abort(403, description='页面已过期，请刷新后再试。')

    @app.after_request
    def response_headers(response):
        response.headers['X-Content-Type-Options'] = 'nosniff'
        if app.config['MODELSCOPE_STUDIO']:
            response.headers['Content-Security-Policy'] = "frame-ancestors 'self' https://www.modelscope.cn"
        else:
            response.headers['X-Frame-Options'] = 'DENY'
        response.headers['Referrer-Policy'] = 'same-origin'
        if not request.path.startswith('/static/'):
            response.headers['Cache-Control'] = 'no-store'
        return response

    @app.context_processor
    def template_context():
        return {'current_user': user_public(g.user), 'csrf_token': session.get('csrf_token', ''),
                'page': request.endpoint or ''}

    for code in (400, 401, 403, 404, 409, 413, 429, 500, 503):
        def error_handler(error):
            message = error.description if error.code != 500 else '操作暂时未完成，请重试。'
            if request.path.startswith('/api/') or request.is_json:
                return jsonify(error=message), error.code
            return message, error.code
        app.register_error_handler(code, error_handler)

    def sign_in(user):
        db().execute('DELETE FROM session_profiles WHERE user_id=?', (user['id'],))
        db().commit()
        session.clear()
        session.update(user_id=user['id'], auth_version=user['auth_version'],
                       csrf_token=secrets.token_urlsafe(32), chat_since=now(), profile_token=secrets.token_urlsafe(24),
                       startup_nonce=app.config['STARTUP_NONCE'])

    def create_user(name, email, password=None, demo=False):
        connection = db()
        uid = connection.execute(
            'INSERT INTO users(name,email,password_hash,is_demo,onboarded,created_at) VALUES(?,?,?,?,?,?)',
            (name, email, generate_password_hash(password) if password else None, int(demo), int(demo), now())
        ).lastrowid
        connection.execute('INSERT INTO profiles(user_id,updated_at) VALUES(?,?)', (uid, now()))
        if demo:
            connection.execute('UPDATE profiles SET ideal=?, "values"=?, current=?, conditions=?, tone=? WHERE user_id=?',
                ('DEMO · 成为从容、持续创造的自己', 'DEMO · 好奇心、独立思考与生活的平衡',
                 'DEMO · 想把一个小创意变成现实', 'DEMO · 从一个 10 分钟的小步骤开始', '温柔、具体、简短', uid))
            connection.execute('UPDATE profiles SET manual_confirmed=1,manual_fields=? WHERE user_id=?', (json.dumps(['ideal', 'values', 'current', 'conditions', 'tone']), uid))
        connection.commit()
        return row('SELECT * FROM users WHERE id=?', (uid,))

    @app.route('/login', methods=['GET', 'POST'])
    def login():
        if g.user:
            return redirect(url_for('index'))
        error = None
        if request.method == 'POST':
            email = request.form.get('email', '').strip().lower()[:254]
            password = request.form.get('password', '')
            key = hashlib.sha256(f'{request.remote_addr}|{email}'.encode()).hexdigest()
            attempt = row('SELECT * FROM login_attempts WHERE key=?', (key,))
            if attempt and time.time() - attempt['started_at'] < 900 and attempt['count'] >= 8:
                return render_template('login.html', error='尝试次数较多，请 15 分钟后再试。'), 429
            user = row('SELECT * FROM users WHERE email=? AND is_demo=0', (email,))
            if user and len(password) <= 128 and check_password_hash(user['password_hash'], password):
                db().execute('DELETE FROM login_attempts WHERE key=?', (key,))
                db().commit()
                sign_in(user)
                return redirect(url_for('index'))
            start = attempt['started_at'] if attempt and time.time() - attempt['started_at'] < 900 else time.time()
            count = attempt['count'] + 1 if attempt and start == attempt['started_at'] else 1
            db().execute('INSERT OR REPLACE INTO login_attempts VALUES(?,?,?)', (key, count, start))
            db().execute('DELETE FROM login_attempts WHERE started_at < ?', (time.time() - 86400,))
            db().commit()
            error = '邮箱或密码不正确。'
        return render_template('login.html', error=error), 400 if error else 200

    @app.route('/register', methods=['GET', 'POST'])
    def register():
        if g.user:
            return redirect(url_for('index'))
        error = None
        if request.method == 'POST':
            name = request.form.get('name', '').strip()
            email = request.form.get('email', '').strip().lower()
            password = request.form.get('password', '')
            if not 1 <= len(name) <= 40:
                error = '请填写 1–40 字的称呼。'
            elif len(email) > 254 or not re.fullmatch(r'[^\s@]+@[^\s@]+\.[^\s@]+', email):
                error = '请填写有效的邮箱。'
            elif not 8 <= len(password) <= 128:
                error = '密码请使用 8–128 个字符。'
            else:
                try:
                    sign_in(create_user(name, email, password))
                    return redirect(url_for('onboarding'))
                except sqlite3.IntegrityError:
                    db().rollback()
                    error = '这个邮箱已注册，请直接登录。'
        return render_template('register.html', error=error), 400 if error else 200

    @app.post('/demo')
    def demo():
        sign_in(create_user('体验者', f'demo-{secrets.token_hex(12)}@demo.local', demo=True))
        return redirect(url_for('chat'))

    @app.post('/logout')
    def logout():
        if session.get('profile_token'):
            db().execute('DELETE FROM session_profiles WHERE token=?', (session['profile_token'],))
            db().commit()
        session.clear()
        return redirect(url_for('login'))

    @app.get('/')
    def index():
        if not g.user:
            return redirect(url_for('login'))
        if not g.user['onboarded']:
            return redirect(url_for('onboarding'))
        active = row("SELECT id FROM focus_sessions WHERE user_id=? AND status!='ended'", (g.user['id'],))
        return redirect(url_for('focus' if active else 'chat'))

    def page_view(name):
        @require_auth
        def view():
            if name != 'onboarding' and not g.user['onboarded']:
                return redirect(url_for('onboarding'))
            return render_template(name + '.html')
        return view

    for name in ('onboarding', 'chat', 'focus', 'echoes', 'profile'):
        app.add_url_rule('/' + name, endpoint=name, view_func=page_view(name))

    def get_profile():
        item = row('SELECT * FROM profiles WHERE user_id=?', (g.user['id'],))
        item.pop('user_id', None)
        return item

    def profile_for_model():
        profile = get_profile()
        fields = ('ideal', 'values', 'current', 'conditions', 'tone')
        if g.user['profile_reuse_enabled']:
            return {key: profile[key] for key in (*fields, 'version')}
        temporary = row('SELECT profile_json FROM session_profiles WHERE token=? AND user_id=?',
                        (session.get('profile_token'), g.user['id'])) if has_request_context() else None
        values = json.loads(temporary['profile_json']) if temporary else dict.fromkeys(fields, '')
        for field in json.loads(profile['manual_fields']):
            if field in fields:
                values[field] = profile[field]
        return values | {'version': profile['version']}

    def source_record(source_type, source_id):
        tables = {'reflection': 'events', 'chat': 'messages', 'letter': 'letters', 'import': 'imports'}
        if source_type not in tables:
            loader = app.extensions.get('future_self_source_loaders', {}).get(source_type)
            return loader(source_id) if loader else None
        source = row(f'SELECT * FROM {tables[source_type]} WHERE id=? AND user_id=?', (source_id, g.user['id']))
        if not source:
            return None
        if source_type == 'chat' and source['role'] != 'user':
            return None
        if source_type in ('letter', 'import') and not source['allow_memory']:
            return None
        if source_type == 'letter' and (source['direction'] != 'sent' or (source.get('open_at') and source['open_at'] > now())):
            return None
        content = source.get('reflection') if source_type == 'reflection' else source.get('body') if source_type == 'letter' else source.get('content')
        return {'source_type': source_type, 'source_id': source['id'], 'content': content or '',
                'revision': source.get('revision', 1), 'created_at': source['created_at'],
                'source_authorized': True, 'source_exists': True, 'direction': source.get('direction')}

    def memory_data(item):
        item = dict(item)
        for key in ('evidence_ids', 'conflicts_with'):
            item[key] = json.loads(item[key]) if isinstance(item.get(key), str) else item.get(key, [])
        item['user_locked'] = bool(item.get('locked'))
        return item

    def message_data(item, feedback_rows=None):
        item = dict(item)
        item.update(json.loads(item.pop('metadata')))
        if feedback_rows is None:
            feedback_rows = rows('SELECT message_id,feedback FROM message_feedback WHERE user_id=? AND message_id=?', (g.user['id'], item['id']))
        item['feedback'] = [feedback['feedback'] for feedback in feedback_rows if feedback['message_id'] == item['id']]
        return item

    def valid_evidence(item):
        evidence = memory_data(item)['evidence_ids']
        if not evidence:
            return False
        for reference in evidence:
            if not isinstance(reference, dict):
                return False
            source = source_record(reference.get('source_type'), reference.get('source_id'))
            if not source or source['revision'] != reference.get('revision', 1):
                return False
        return True

    def session_data(item):
        if not item:
            return None
        item = dict(item)
        timestamp = time.time()
        item['elapsed_seconds'] = max(0, item['elapsed_seconds']) + (
            max(0, timestamp - item['running_since']) if item['status'] == 'running' and item['running_since'] else 0)
        item['server_time'] = timestamp
        return item

    def confirmed_memories():
        if not g.user['memory_enabled']:
            return []
        found = rows("SELECT * FROM memories WHERE user_id=? AND status='confirmed' ORDER BY id DESC LIMIT 200", (g.user['id'],))
        return [dict(memory_data(item), source_authorized=True, source_exists=True) for item in found if valid_evidence(item)]

    def queue_job(kind, source_type, source_id, payload=None):
        payload = dict(payload or {})
        profile = get_profile()
        source = source_record(source_type, source_id) if kind == 'memory' else row('SELECT revision FROM events WHERE id=? AND user_id=?', (source_id, g.user['id'])) if source_type == 'reflection' else None
        revision = source['revision'] if source else 1
        if has_request_context():
            payload['_profile'] = profile_for_model()
            payload['_profile_token'] = session.get('profile_token')
        dedup = f"{g.user['id']}:{kind}:{source_type}:{source_id}:{revision}:{profile['version']}:{g.user['consent_version']}:{bool(payload.get('rewrite'))}"
        db().execute('''INSERT OR IGNORE INTO jobs(user_id,kind,source_type,source_id,payload,available_at,created_at,updated_at,
                       profile_version,consent_version,source_revision,dedup_key) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)''',
            (g.user['id'], kind, source_type, source_id, json.dumps(payload, ensure_ascii=False), time.time(), now(), now(),
             profile['version'], g.user['consent_version'], revision, dedup))
        db().commit()
        return row('SELECT * FROM jobs WHERE dedup_key=?', (dedup,))

    def invalidate_source(source_type, source_id):
        for item in rows("SELECT * FROM memories WHERE user_id=? AND status!='rejected'", (g.user['id'],)):
            if any(ref.get('source_type') == source_type and ref.get('source_id') == source_id for ref in memory_data(item)['evidence_ids']):
                db().execute("UPDATE memories SET status='revoked' WHERE id=?", (item['id'],))
        db().execute("UPDATE jobs SET status='cancelled',payload='{}',updated_at=? WHERE user_id=? AND source_type=? AND source_id=? AND status IN ('pending','running')",
                     (now(), g.user['id'], source_type, source_id))

    def run_jobs(limit=20, user_id=None):
        processed = 0
        previous_user = getattr(g, 'user', None)
        for _ in range(max(1, min(int(limit), 50))):
            db().execute('BEGIN IMMEDIATE')
            db().execute("UPDATE jobs SET status=CASE WHEN attempts>=3 THEN 'failed' ELSE 'pending' END,locked_at=NULL WHERE status='running' AND locked_at<?", (time.time() - 90,))
            job = row("SELECT * FROM jobs WHERE status='pending' AND available_at<=? AND attempts<3" + (' AND user_id=?' if user_id else '') + ' ORDER BY id LIMIT 1',
                      (time.time(), user_id) if user_id else (time.time(),))
            if not job:
                db().commit()
                break
            db().execute("UPDATE jobs SET status='running',attempts=attempts+1,locked_at=?,updated_at=? WHERE id=?", (time.time(), now(), job['id']))
            db().commit()
            processed += 1
            try:
                g.user = row('SELECT * FROM users WHERE id=?', (job['user_id'],))
                if not g.user:
                    continue
                profile = profile_for_model()
                payload = json.loads(job['payload'])
                if payload.get('_profile_token') and row('SELECT token FROM session_profiles WHERE token=? AND user_id=?', (payload['_profile_token'], g.user['id'])):
                    profile = dict(payload.get('_profile') or profile, version=profile['version'])
                permitted = bool(g.user['memory_enabled']) if job['kind'] == 'memory' else bool(g.user['auto_letters'])
                if not permitted or g.user['consent_version'] != job['consent_version'] or profile['version'] != job['profile_version']:
                    db().execute("UPDATE jobs SET status='cancelled',payload='{}',updated_at=? WHERE id=?", (now(), job['id']))
                    if job['source_type'] == 'reflection' and job['kind'] != 'memory':
                        db().execute('UPDATE events SET letter_status=? WHERE id=? AND user_id=?', ('failed' if g.user['auto_letters'] else 'disabled', job['source_id'], job['user_id']))
                    db().commit()
                    continue
                if job['kind'] == 'memory':
                    source = source_record(job['source_type'], job['source_id'])
                    if not source or source['revision'] != job['source_revision']:
                        raise LookupError('source unavailable')
                    sources = [source]
                    for old in rows("SELECT source_type,source_id FROM memories WHERE user_id=? AND status IN ('candidate','confirmed') ORDER BY id DESC LIMIT 20", (g.user['id'],)):
                        extra = source_record(old['source_type'], old['source_id'])
                        if extra and (extra['source_type'], extra['source_id']) not in {(s['source_type'], s['source_id']) for s in sources}:
                            sources.append(extra)
                    existing = [memory_data(item) for item in rows("SELECT * FROM memories WHERE user_id=? AND status IN ('candidate','confirmed')", (g.user['id'],))]
                    output = modeling.extract_candidates(profile, sources, existing)
                else:
                    event = owned('events', job['source_id']) if job['source_type'] == 'reflection' else {'kind': job['kind'], 'id': job['source_id']}
                    if job['source_type'] == 'reflection' and event['revision'] != job['source_revision']:
                        raise LookupError('source changed')
                    output = modeling.make_letter(profile, event)
                db().execute('BEGIN IMMEDIATE')
                g.user = row('SELECT * FROM users WHERE id=?', (job['user_id'],))
                current_job = row('SELECT status FROM jobs WHERE id=?', (job['id'],))
                if not g.user or not current_job or current_job['status'] != 'running' or g.user['consent_version'] != job['consent_version'] or get_profile()['version'] != job['profile_version']:
                    raise LookupError('context changed')
                if job['kind'] == 'memory':
                    for candidate in output[:12]:
                        content = str(candidate.get('proposed_value') or candidate.get('content') or '').strip()[:2000]
                        signature = hashlib.sha256(re.sub(r'[\W_]+', '', content.lower()).encode()).hexdigest()
                        field = candidate.get('field', 'conditions')
                        if not content or field not in ('ideal', 'values', 'current', 'conditions', 'tone'):
                            continue
                        if row('SELECT signature FROM memory_tombstones WHERE user_id=? AND signature=?', (g.user['id'], signature)):
                            continue
                        evidence = candidate.get('evidence_ids') or []
                        verified = []
                        for ref in evidence:
                            src = source_record(ref.get('source_type'), ref.get('source_id')) if isinstance(ref, dict) else None
                            if not src or src['revision'] != ref.get('revision', src['revision']):
                                verified = []
                                break
                            verified.append({'source_type': src['source_type'], 'source_id': src['source_id'], 'revision': src['revision']})
                        if not verified:
                            continue
                        duplicate = row("SELECT * FROM memories WHERE user_id=? AND signature=? AND status IN ('candidate','confirmed')", (g.user['id'], signature))
                        if duplicate:
                            merged = memory_data(duplicate)['evidence_ids']
                            merged += [ref for ref in verified if ref not in merged]
                            db().execute('UPDATE memories SET evidence_ids=? WHERE id=?', (json.dumps(merged), duplicate['id']))
                            continue
                        conflicts = [item['id'] for item in existing if item['field'] == field and item['user_locked'] and item['signature'] != signature]
                        confidence = str(candidate.get('confidence') or ('多条来源待确认' if len(verified) > 1 else '单次自述待确认'))[:80]
                        if re.search(r'\d.*[%％]', confidence):
                            confidence = '待用户确认'
                        db().execute('''INSERT INTO memories(user_id,content,kind,status,source_type,source_id,created_at,field,proposed_value,reason,
                                      evidence_ids,confidence,signature,conflicts_with) VALUES(?,?,?,'candidate',?,?,?,?,?,?,?,?,?,?)''',
                            (g.user['id'], content, 'observation', verified[0]['source_type'], verified[0]['source_id'], now(), field, content,
                             str(candidate.get('reason') or '')[:1000], json.dumps(verified), confidence, signature, json.dumps(conflicts)))
                else:
                    if job['source_type'] == 'reflection':
                        fresh = owned('events', job['source_id'])
                        if fresh['revision'] != job['source_revision']:
                            raise LookupError('source changed')
                    title, body = str(output['title'])[:200], str(output['body'])[:12000]
                    source_id = job['source_id'] if job['source_type'] == 'reflection' else None
                    old = row('SELECT id FROM letters WHERE source_id=? AND user_id=?', (source_id, g.user['id'])) if source_id else None
                    if old and payload.get('rewrite'):
                        db().execute('UPDATE letters SET title=?,body=?,persona_version=?,source_adjusted=0,revision=revision+1,is_read=0,job_id=? WHERE id=?',
                                     (title, body, profile['version'], job['id'], old['id']))
                    elif not old:
                        db().execute("INSERT OR IGNORE INTO letters(user_id,title,body,direction,created_at,source_id,persona_version,job_id) VALUES(?,?,?,'received',?,?,?,?)",
                            (g.user['id'], title, body, now(), source_id, profile['version'], job['id']))
                    if source_id:
                        db().execute("UPDATE events SET letter_status='ready' WHERE id=?", (source_id,))
                db().execute("UPDATE jobs SET status='complete',updated_at=?,locked_at=NULL,payload='{}' WHERE id=?", (now(), job['id']))
                db().commit()
            except LookupError:
                db().rollback()
                db().execute("UPDATE jobs SET status='cancelled',updated_at=?,payload='{}' WHERE id=?", (now(), job['id']))
                if job['source_type'] == 'reflection' and job['kind'] != 'memory':
                    db().execute("UPDATE events SET letter_status='failed' WHERE id=? AND user_id=?", (job['source_id'], job['user_id']))
                db().commit()
            except Exception:
                db().rollback()
                failed = job['attempts'] + 1 >= 3
                db().execute("UPDATE jobs SET status=?,available_at=?,locked_at=NULL,updated_at=?,last_error=? WHERE id=?",
                    ('failed' if failed else 'pending', time.time() + 5 * (2 ** job['attempts']), now(), '生成暂未完成，可重试；事实记录已保留。', job['id']))
                if job['source_type'] == 'reflection' and job['kind'] != 'memory':
                    db().execute("UPDATE events SET letter_status='failed' WHERE id=? AND user_id=?", (job['source_id'], job['user_id']))
                db().commit()
        g.user = previous_user
        return processed

    @app.post('/api/jobs/run')
    @require_auth
    def drain_jobs():
        return jsonify(processed=run_jobs(user_id=g.user['id']))

    @app.post('/api/jobs/<int:jid>/retry')
    @require_auth
    def retry_job(jid):
        job = owned('jobs', jid)
        if job['status'] in ('failed', 'pending'):
            db().execute("UPDATE jobs SET status='pending',attempts=0,available_at=?,last_error='' WHERE id=?", (time.time(), jid))
            db().commit()
        return jsonify(job=owned('jobs', jid))

    def get_state():
        uid = g.user['id']
        profile = get_profile()
        answers = json.loads(profile.pop('answers'))
        sessions = [session_data(item) for item in rows('SELECT * FROM focus_sessions WHERE user_id=? ORDER BY id DESC LIMIT 500', (uid,))]
        messages = rows('SELECT * FROM messages WHERE user_id=? ORDER BY id DESC LIMIT 300', (uid,))[::-1]
        feedback_rows = rows('SELECT message_id,feedback FROM message_feedback WHERE user_id=?', (uid,))
        messages = [message_data(message, feedback_rows) for message in messages]
        model = modeling.build_model(profile_for_model(), confirmed_memories(), sessions, bool(g.user['memory_enabled']))
        model['pending_count'] = row("SELECT COUNT(*) AS n FROM memories WHERE user_id=? AND status='candidate'", (uid,))['n']
        growth_snapshot = app.extensions.get('future_self_growth_snapshot')
        return dict(user=user_public(g.user), profile=profile, model_profile=profile_for_model(), answers=answers,
            tasks=rows('SELECT * FROM tasks WHERE user_id=? ORDER BY id DESC LIMIT 500', (uid,)), sessions=sessions,
            active_session=next((item for item in sessions if item['status'] != 'ended'), None),
            messages=messages, events=rows('SELECT * FROM events WHERE user_id=? ORDER BY id DESC LIMIT 500', (uid,)),
            letters=rows('SELECT * FROM letters WHERE user_id=? ORDER BY id DESC LIMIT 500', (uid,)),
            memories=[memory_data(item) for item in rows('SELECT * FROM memories WHERE user_id=? ORDER BY id DESC LIMIT 500', (uid,))],
            milestones=rows('SELECT * FROM milestones WHERE user_id=? ORDER BY date,id', (uid,)),
            jobs=rows('SELECT id,kind,source_type,source_id,status,attempts,last_error,created_at,updated_at FROM jobs WHERE user_id=? ORDER BY id DESC LIMIT 40', (uid,)),
            model=model,
            growth=growth_snapshot(uid) if growth_snapshot else {'active_experiment': None, 'capabilities': [], 'active_week': None, 'recent_evidence': []},
            server_time=time.time())

    @app.get('/api/state')
    @require_auth
    def state():
        return jsonify(get_state())

    @app.get('/api/session')
    @require_auth
    def session_identity():
        return jsonify(user_id=g.user['id'], csrf_token=session['csrf_token'])

    @app.post('/api/onboarding')
    @require_auth
    def save_onboarding():
        body = data()
        answers = body.get('answers')
        if not isinstance(answers, list) or len(answers) != 5 or any(not isinstance(v, str) or len(v) > 2000 for v in answers):
            abort(400, description='请提交五个回答，每项不超过 2000 字；可以留空。')
        answers = [value.strip() for value in answers]
        complete = boolean(body, 'complete')
        memory = boolean(body, 'memory_enabled', bool(g.user['memory_enabled']))
        uid = g.user['id']
        db().execute('UPDATE profiles SET answers=?,updated_at=? WHERE user_id=?', (json.dumps(answers, ensure_ascii=False), now(), uid))
        if complete:
            old = get_profile()
            changed = any(old[key] != value for key, value in zip(('ideal', 'values', 'current', 'conditions', 'tone'), answers))
            db().execute("UPDATE profiles SET ideal=?, \"values\"=?,current=?,conditions=?,tone=?,manual_confirmed=0,manual_fields='[]',version=version+? WHERE user_id=?",
                         (*answers, int(changed and bool(g.user['onboarded'])), uid))
            db().execute('UPDATE users SET onboarded=1,memory_enabled=? WHERE id=?', (int(memory), uid))
            token = session.setdefault('profile_token', secrets.token_urlsafe(24))
            temporary = dict(zip(('ideal', 'values', 'current', 'conditions', 'tone'), answers))
            db().execute('INSERT OR REPLACE INTO session_profiles VALUES(?,?,?,?)', (token, uid, json.dumps(temporary, ensure_ascii=False), now()))
            reuse = boolean(body, 'profile_reuse_enabled', bool(g.user['profile_reuse_enabled']))
            consent_changed = memory != bool(g.user['memory_enabled']) or reuse != bool(g.user['profile_reuse_enabled'])
            db().execute('UPDATE users SET profile_reuse_enabled=?,consent_version=consent_version+? WHERE id=?', (int(reuse), int(consent_changed), uid))
        db().commit()
        g.user = row('SELECT * FROM users WHERE id=?', (uid,))
        if complete and not row("SELECT id FROM jobs WHERE user_id=? AND kind='welcome' AND status IN ('pending','running','complete')", (uid,)):
            queue_job('welcome', 'onboarding', uid)
        return jsonify(saved=True, complete=bool(g.user['onboarded']), profile=get_profile())

    @app.post('/api/onboarding/question')
    @require_auth
    def next_question():
        body = data()
        answers = body.get('answers', ['', '', '', '', ''])
        if not isinstance(answers, list) or len(answers) != 5 or any(not isinstance(value, str) or len(value) > 2000 for value in answers):
            abort(400, description='请提交五项回答，可以留空。')
        step = number(body, 'step', 0, 4)
        return jsonify(modeling.onboarding_question(answers, step))

    @app.route('/api/profile', methods=['GET', 'POST'])
    @require_auth
    def edit_profile():
        if request.method == 'POST':
            body = data()
            profile = get_profile()
            fields = ('ideal', 'values', 'current', 'conditions', 'tone')
            values = [text(body, key, default=profile[key]) for key in fields]
            name = text(body, 'name', 40, True, g.user['name'])
            memory = boolean(body, 'memory_enabled', bool(g.user['memory_enabled']))
            letters = boolean(body, 'auto_letters', bool(g.user['auto_letters']))
            reuse = boolean(body, 'profile_reuse_enabled', bool(g.user['profile_reuse_enabled']))
            changed = any(profile[key] != value for key, value in zip(fields, values)) or bool({key for key in fields if key in body} - set(json.loads(profile['manual_fields'])))
            db().execute('UPDATE profiles SET ideal=?, "values"=?,current=?,conditions=?,tone=?,version=version+?,updated_at=? WHERE user_id=?',
                         (*values, int(changed), now(), g.user['id']))
            if any(key in body for key in fields):
                manual = sorted(set(json.loads(profile['manual_fields'])) | {key for key in fields if key in body})
                db().execute('UPDATE profiles SET manual_confirmed=1,manual_fields=? WHERE user_id=?', (json.dumps(manual), g.user['id']))
            consent_changed = memory != bool(g.user['memory_enabled']) or letters != bool(g.user['auto_letters']) or reuse != bool(g.user['profile_reuse_enabled'])
            db().execute('UPDATE users SET name=?,memory_enabled=?,auto_letters=?,profile_reuse_enabled=?,consent_version=consent_version+? WHERE id=?',
                         (name, int(memory), int(letters), int(reuse), int(consent_changed), g.user['id']))
            if consent_changed:
                db().execute("UPDATE jobs SET status='cancelled',payload='{}' WHERE user_id=? AND status IN ('pending','running')", (g.user['id'],))
                db().execute("""UPDATE events SET letter_status=? WHERE user_id=? AND letter_status='pending' AND
                              EXISTS(SELECT 1 FROM jobs j WHERE j.user_id=events.user_id AND j.source_id=events.id
                              AND j.source_type='reflection' AND j.kind='letter' AND j.status='cancelled')""",
                             ('failed' if letters else 'disabled', g.user['id']))
            db().commit()
            g.user = row('SELECT * FROM users WHERE id=?', (g.user['id'],))
        return jsonify(profile=get_profile(), user=user_public(g.user))

    @app.post('/api/chat')
    @require_auth
    def send_chat():
        body = data()
        message = text(body, 'message', 4000, True)
        key = text(body, 'request_id', 100, True, secrets.token_hex(16))
        uid = g.user['id']
        connection = db()
        connection.execute('BEGIN IMMEDIATE')
        existing = row('SELECT * FROM chat_requests WHERE user_id=? AND request_id=?', (uid, key))
        if existing and existing['status'] == 'complete':
            connection.commit()
            return jsonify(json.loads(existing['result']))
        if existing and existing['status'] == 'pending':
            age = time.time() - existing['started_at']
            if age < 90:
                connection.commit()
                abort(409, description='这条消息正在生成，请稍候。')
        if existing:
            saved = row('SELECT content FROM messages WHERE id=? AND user_id=?', (existing['message_id'], uid))
            if not saved or saved['content'] != message:
                connection.rollback()
                abort(409, description='请求标识已用于另一条消息。')
            connection.execute("UPDATE chat_requests SET status='pending',started_at=? WHERE user_id=? AND request_id=?", (time.time(), uid, key))
            user_message_id = existing['message_id']
        else:
            mid = connection.execute("INSERT INTO messages(user_id,role,content,created_at) VALUES(?,'user',?,?)", (uid, message, now())).lastrowid
            connection.execute("INSERT INTO chat_requests(user_id,request_id,status,message_id,started_at) VALUES(?,?,'pending',?,?)", (uid, key, mid, time.time()))
            user_message_id = mid
        connection.commit()
        try:
            profile = profile_for_model()
            stats = get_state()['model'] if g.user['memory_enabled'] else {}
            active = row("SELECT * FROM focus_sessions WHERE user_id=? AND status!='ended'", (uid,))
            task_id = body.get('task_id') or (active['task_id'] if active else None)
            current_task = owned('tasks', task_id) if task_id else row("SELECT * FROM tasks WHERE user_id=? AND status='ready' ORDER BY id DESC LIMIT 1", (uid,))
            stats.update(current_task=current_task, active_session=session_data(active),
                         feedback=rows('SELECT message_id,feedback,created_at FROM message_feedback WHERE user_id=? ORDER BY created_at DESC LIMIT 5', (uid,))[::-1])
            memories = confirmed_memories()
            memory_enabled = g.user['memory_enabled']
            consent_version = g.user['consent_version']
            valid_ids = {str(item['id']) for item in memories}
            recent = []
            for item in rows('SELECT id,role,content,metadata FROM messages WHERE user_id=? AND created_at>=? ORDER BY id DESC LIMIT 20', (uid, session.get('chat_since', now())))[::-1]:
                metadata = json.loads(item['metadata'])
                evidence = {str(value) for value in metadata.get('evidence_ids') or []}
                if item['id'] == user_message_id or (item['role'] == 'assistant' and
                    (not evidence.issubset(valid_ids) or metadata.get('persona_version', profile['version']) != profile['version'])):
                    continue
                recent.append({'role': item['role'], 'content': item['content']})
            result = modeling.chat_reply(message, profile, memories, recent, stats)
            if not isinstance(result, dict) or not isinstance(result.get('reply_text'), str) or not result['reply_text'].strip():
                raise ValueError('invalid model reply')
            connection.execute('BEGIN IMMEDIATE')
            current = row('SELECT * FROM users WHERE id=?', (uid,))
            if not current or current['auth_version'] != session.get('auth_version') or not row("SELECT user_id FROM chat_requests WHERE user_id=? AND request_id=? AND status='pending'", (uid, key)):
                raise ValueError('source deleted')
            g.user = current
            if current['memory_enabled'] != memory_enabled or current['consent_version'] != consent_version or profile_for_model() != profile or confirmed_memories() != memories:
                raise ValueError('context changed during generation')
            metadata = {key: result.get(key) for key in ('intent', 'action_suggestion', 'evidence_ids', 'model')}
            metadata['persona_version'] = profile['version']
            mid = connection.execute("INSERT INTO messages(user_id,role,content,metadata,created_at) VALUES(?,'assistant',?,?,?)",
                (uid, result['reply_text'], json.dumps(metadata, ensure_ascii=False), now())).lastrowid
            result.update(request_id=key, message_id=mid)
            connection.execute("UPDATE chat_requests SET status='complete',result=? WHERE user_id=? AND request_id=?",
                               (json.dumps(result, ensure_ascii=False), uid, key))
            connection.commit()
            if g.user['memory_enabled']:
                queue_job('memory', 'chat', user_message_id)
            return jsonify(result)
        except Exception:
            connection.rollback()
            connection.execute("UPDATE chat_requests SET status='failed' WHERE user_id=? AND request_id=?", (uid, key))
            connection.commit()
            return jsonify(error='消息已保存，回应暂未生成。请重试。', request_id=key, retryable=True), 503

    @app.get('/api/messages/<int:mid>')
    @require_auth
    def get_message(mid):
        return jsonify(message=message_data(owned('messages', mid)))

    @app.post('/api/messages/<int:mid>/feedback')
    @require_auth
    def message_feedback(mid):
        message = owned('messages', mid)
        if message['role'] != 'assistant':
            abort(400, description='请选择一条 AI 回复。')
        feedback = text(data(), 'feedback', 30, True)
        if feedback not in ('direct', 'listen', 'correction', 'dismiss_action'):
            abort(400, description='无效的反馈。')
        db().execute('INSERT OR IGNORE INTO message_feedback VALUES(?,?,?,?)', (g.user['id'], mid, feedback, now()))
        db().commit()
        return jsonify(saved=True, feedback=feedback, message_id=mid)

    @app.post('/api/tasks')
    @require_auth
    def create_task():
        body = data()
        values = [text(body, key, 300, True) for key in ('title', 'first_step', 'done_criteria')]
        minutes = number(body, 'planned_minutes', 1, 180)
        source_id = body.get('source_message_id')
        if source_id is not None:
            owned('messages', number(body, 'source_message_id'))
        goal_id = nullable_owner(body, 'goal_id', 'goals')
        milestone_id = nullable_owner(body, 'milestone_id', 'milestones')
        if milestone_id and goal_id and owned('milestones', milestone_id).get('goal_id') not in (None, goal_id):
            abort(400, description='里程碑与目标不匹配。')
        tid = db().execute('INSERT INTO tasks(user_id,title,first_step,done_criteria,planned_minutes,source_message_id,created_at,goal_id,milestone_id) VALUES(?,?,?,?,?,?,?,?,?)',
                           (g.user['id'], *values, minutes, source_id, now(), goal_id, milestone_id)).lastrowid
        db().commit()
        return jsonify(task=owned('tasks', tid)), 201

    @app.post('/api/focus/start')
    @require_auth
    def start_focus():
        body = data()
        task_id = number(body, 'task_id')
        key = text(body, 'request_id', 100)
        connection = db()
        connection.execute('BEGIN IMMEDIATE')
        task = owned('tasks', task_id)
        repeated = row('SELECT * FROM focus_actions WHERE user_id=? AND request_id=?', (g.user['id'], key)) if key else None
        if repeated:
            if repeated['action'] != 'start':
                connection.rollback()
                abort(409, description='请求标识已用于另一项操作。')
            previous = owned('focus_sessions', repeated['session_id'])
            connection.commit()
            return jsonify(session=session_data(previous), resumed=True)
        active = row("SELECT * FROM focus_sessions WHERE user_id=? AND status!='ended'", (g.user['id'],))
        if active:
            if key:
                connection.execute('INSERT INTO focus_actions VALUES(?,?,?,?)', (g.user['id'], key, active['id'], 'start'))
            connection.commit()
            return jsonify(session=session_data(active), resumed=True)
        timestamp, offline = action_time(body)
        sid = connection.execute("INSERT INTO focus_sessions(user_id,task_id,title,planned_minutes,status,running_since,started_at) VALUES(?,?,?,?,'running',?,?)",
            (g.user['id'], task_id, task['title'], task['planned_minutes'], timestamp, datetime.fromtimestamp(timestamp, timezone.utc).isoformat())).lastrowid
        connection.execute('UPDATE focus_sessions SET last_action_at=?,timing_review_required=? WHERE id=?', (timestamp, int(offline), sid))
        connection.execute('INSERT INTO focus_intervals(session_id,started_at) VALUES(?,?)', (sid, timestamp))
        connection.execute("UPDATE tasks SET status='active' WHERE id=?", (task_id,))
        if key:
            connection.execute('INSERT INTO focus_actions VALUES(?,?,?,?)', (g.user['id'], key, sid, 'start'))
        connection.commit()
        return jsonify(session=session_data(owned('focus_sessions', sid))), 201

    def generate_letter(event_id, rewrite=False, retry=False):
        event = owned('events', event_id)
        if not g.user['auto_letters']:
            db().execute("UPDATE events SET letter_status='disabled' WHERE id=?", (event_id,))
            db().commit()
            return None
        existing = row('SELECT * FROM letters WHERE source_id=? AND user_id=?', (event_id, g.user['id']))
        if existing and not rewrite:
            return existing
        job = queue_job('letter', 'reflection', event_id, {'rewrite': rewrite})
        if retry and job['status'] in ('failed', 'pending'):
            db().execute("UPDATE jobs SET status='pending',attempts=0,available_at=?,last_error='' WHERE id=?", (time.time(), job['id']))
            job['status'] = 'pending'
        db().execute("""UPDATE events SET letter_status=CASE (SELECT status FROM jobs WHERE id=?)
                      WHEN 'complete' THEN 'ready' WHEN 'failed' THEN 'failed' WHEN 'cancelled' THEN 'failed' ELSE 'pending' END WHERE id=?""", (job['id'], event_id))
        db().commit()
        return existing

    @app.post('/api/focus/<int:sid>')
    @require_auth
    def update_focus(sid):
        owned('focus_sessions', sid)
        body = data()
        action = text(body, 'action', 20, True)
        if action not in ('pause', 'resume', 'end', 'finish'):
            abort(400, description='无效的沉浸操作。')
        result = text(body, 'result', 20)
        reflection = text(body, 'reflection', 2000)
        if action == 'finish' and result not in ('completed', 'partial', 'stopped'):
            abort(400, description='请选择这次沉浸的结果。')
        key = text(body, 'request_id', 100)
        connection = db()
        connection.execute('BEGIN IMMEDIATE')
        item = owned('focus_sessions', sid)
        repeated = row('SELECT * FROM focus_actions WHERE user_id=? AND request_id=?', (g.user['id'], key)) if key else None
        if repeated and (repeated['session_id'] != sid or repeated['action'] != action):
            connection.rollback()
            abort(409, description='请求标识已用于另一项操作。')
        if repeated or item['status'] == 'ended':
            connection.commit()
            event = row('SELECT * FROM events WHERE session_id=? AND user_id=?', (sid, g.user['id']))
            return jsonify(session=session_data(item), event=event)
        timestamp, offline = action_time(body, item)
        if action in ('pause', 'end') and item['status'] == 'running':
            elapsed = max(0, timestamp - item['running_since'])
            connection.execute('UPDATE focus_sessions SET elapsed_seconds=elapsed_seconds+?,running_since=NULL WHERE id=?', (elapsed, sid))
            connection.execute('UPDATE focus_intervals SET ended_at=? WHERE session_id=? AND ended_at IS NULL', (timestamp, sid))
        if action == 'pause' and item['status'] == 'running':
            connection.execute("UPDATE focus_sessions SET status='paused' WHERE id=?", (sid,))
        elif action == 'resume' and item['status'] == 'paused':
            connection.execute("UPDATE focus_sessions SET status='running',running_since=? WHERE id=?", (timestamp, sid))
            connection.execute('INSERT INTO focus_intervals(session_id,started_at) VALUES(?,?)', (sid, timestamp))
        elif action == 'end' and item['status'] in ('running', 'paused'):
            connection.execute("UPDATE focus_sessions SET status='ending',ended_at=? WHERE id=?", (datetime.fromtimestamp(timestamp, timezone.utc).isoformat(), sid))
        elif action == 'finish':
            if item['status'] != 'ending':
                connection.rollback()
                abort(409, description='请先结束计时，再记录结果。')
            connection.execute("UPDATE focus_sessions SET status='ended',result=?,reflection=? WHERE id=?", (result, reflection, sid))
            connection.execute('UPDATE tasks SET status=? WHERE id=?', (result, item['task_id']))
            eid = connection.execute('INSERT INTO events(user_id,session_id,title,result,elapsed_seconds,reflection,created_at) VALUES(?,?,?,?,?,?,?)',
                (g.user['id'], sid, item['title'], result, item['elapsed_seconds'], reflection, item['ended_at'])).lastrowid
        elif action in ('pause', 'resume') and item['status'] == 'ending':
            connection.rollback()
            abort(409, description='计时已经结束，请完成结果记录。')
        if key:
            connection.execute('INSERT INTO focus_actions VALUES(?,?,?,?)', (g.user['id'], key, sid, action))
        transitioned = ((action in ('pause', 'end') and item['status'] == 'running') or
                        (action in ('resume', 'end') and item['status'] == 'paused') or
                        (action == 'finish' and item['status'] == 'ending'))
        if transitioned:
            connection.execute('UPDATE focus_sessions SET last_action_at=?,timing_review_required=MAX(timing_review_required,?) WHERE id=?', (timestamp, int(offline), sid))
        connection.commit()
        event = row('SELECT * FROM events WHERE session_id=? AND user_id=?', (sid, g.user['id']))
        if action == 'finish' and event and reflection and g.user['memory_enabled']:
            queue_job('memory', 'reflection', event['id'])
        letter = generate_letter(event['id']) if action == 'finish' and event else None
        if event:
            event = owned('events', event['id'])
        return jsonify(session=session_data(owned('focus_sessions', sid)), event=event, letter=letter)

    @app.post('/api/events/<int:eid>/letter')
    @require_auth
    def retry_letter(eid):
        owned('events', eid)
        body = request.get_json(silent=True) or {}
        letter = generate_letter(eid, boolean(body, 'rewrite'), retry=True)
        return jsonify(letter=letter, event=owned('events', eid))

    @app.post('/api/letters')
    @require_auth
    def write_letter():
        body = data()
        title = text(body, 'title', 200, True)
        content = text(body, 'body', 12000, True)
        allow = boolean(body, 'allow_memory')
        open_at = body.get('open_at') or None
        if open_at:
            try:
                parsed = datetime.fromisoformat(open_at.replace('Z', '+00:00'))
                if not parsed.tzinfo:
                    raise ValueError()
                open_at = parsed.astimezone(timezone.utc).isoformat(timespec='milliseconds')
            except (ValueError, TypeError, AttributeError):
                abort(400, description='开信时间需要包含时区的 ISO 日期。')
        lid = db().execute("INSERT INTO letters(user_id,title,body,direction,created_at,is_read,allow_memory,persona_version,open_at) VALUES(?,?,?,'sent',?,1,?,?,?)",
             (g.user['id'], title, content, now(), int(allow), get_profile()['version'], open_at)).lastrowid
        db().commit()
        if allow and g.user['memory_enabled'] and (not open_at or open_at <= now()):
            queue_job('memory', 'letter', lid)
        return jsonify(letter=owned('letters', lid)), 201

    @app.route('/api/letters/<int:lid>', methods=['GET', 'PATCH', 'DELETE'])
    @require_auth
    def edit_letter(lid):
        item = owned('letters', lid)
        if request.method == 'GET':
            return jsonify(letter=item)
        if request.method == 'DELETE':
            invalidate_source('letter', lid)
            db().execute('DELETE FROM letters WHERE id=? AND user_id=?', (lid, g.user['id']))
            if item['source_id']:
                db().execute("UPDATE events SET letter_status='deleted' WHERE id=? AND user_id=?", (item['source_id'], g.user['id']))
            db().execute('UPDATE profiles SET version=version+1,updated_at=? WHERE user_id=?', (now(), g.user['id']))
            db().commit()
            return jsonify(deleted=True)
        body = data()
        read = boolean(body, 'is_read', True)
        allow = boolean(body, 'allow_memory', bool(item['allow_memory']))
        if item['direction'] != 'sent':
            allow = False
        db().execute('UPDATE letters SET is_read=?,allow_memory=? WHERE id=?', (int(read), int(allow), lid))
        if not allow:
            invalidate_source('letter', lid)
        if bool(item['allow_memory']) != allow:
            db().execute('UPDATE profiles SET version=version+1,updated_at=? WHERE user_id=?', (now(), g.user['id']))
        db().commit()
        if allow and g.user['memory_enabled'] and source_record('letter', lid):
            queue_job('memory', 'letter', lid)
        return jsonify(letter=owned('letters', lid))

    @app.post('/api/milestones')
    @require_auth
    def create_milestone():
        body = data()
        title = text(body, 'title', 200, True)
        planned = text(body, 'date', 10, True)
        try:
            if date.fromisoformat(planned).isoformat() != planned:
                raise ValueError()
        except ValueError:
            abort(400, description='日期请使用 YYYY-MM-DD 格式。')
        goal_id = nullable_owner(body, 'goal_id', 'goals')
        mid = db().execute('INSERT INTO milestones(user_id,title,date,created_at,goal_id) VALUES(?,?,?,?,?)', (g.user['id'], title, planned, now(), goal_id)).lastrowid
        db().commit()
        return jsonify(milestone=owned('milestones', mid)), 201

    @app.route('/api/milestones/<int:mid>', methods=['PATCH', 'DELETE'])
    @require_auth
    def update_milestone(mid):
        item = owned('milestones', mid)
        if request.method == 'DELETE':
            db().execute('UPDATE tasks SET milestone_id=NULL WHERE milestone_id=? AND user_id=?', (mid, g.user['id']))
            db().execute('DELETE FROM milestones WHERE id=?', (mid,))
            db().commit()
            return jsonify(deleted=True)
        body = data()
        completed = boolean(body, 'completed', bool(item['completed']))
        title = text(body, 'title', 200, True, item['title'])
        planned = text(body, 'date', 10, True, item['date'])
        try:
            if date.fromisoformat(planned).isoformat() != planned:
                raise ValueError()
        except ValueError:
            abort(400, description='日期请使用 YYYY-MM-DD 格式。')
        goal_id = nullable_owner(body, 'goal_id', 'goals') if 'goal_id' in body else item['goal_id']
        db().execute('UPDATE milestones SET completed=?,title=?,date=?,goal_id=? WHERE id=?', (int(completed), title, planned, goal_id, mid))
        if goal_id != item['goal_id']:
            db().execute('UPDATE tasks SET goal_id=? WHERE milestone_id=? AND user_id=?', (goal_id, mid, g.user['id']))
        db().commit()
        return jsonify(milestone=owned('milestones', mid))

    @app.route('/api/memories/<int:mid>', methods=['PATCH', 'DELETE'])
    @require_auth
    def update_memory(mid):
        item = owned('memories', mid)
        if request.method == 'DELETE':
            db().execute('INSERT OR IGNORE INTO memory_tombstones VALUES(?,?,?)', (g.user['id'], item['signature'], now()))
            db().execute('DELETE FROM memories WHERE id=?', (mid,))
        else:
            body = data()
            action = text(body, 'action', 20, True)
            if action not in ('confirm', 'reject', 'edit'):
                abort(400, description='请选择确认、拒绝或修改。')
            content = text(body, 'content', 2000, True) if action == 'edit' else item['content']
            status = 'rejected' if action == 'reject' else 'confirmed'
            kind = 'correction' if action == 'edit' else item['kind']
            if action != 'reject' and (not content or not valid_evidence(item)):
                abort(409, description='来源已变化，请查看新的待确认观察。')
            conflicts = memory_data(item)['conflicts_with']
            if action == 'confirm' and any(row("SELECT id FROM memories WHERE id=? AND user_id=? AND status='confirmed' AND locked=1", (cid, g.user['id'])) for cid in conflicts):
                abort(409, description='这条观察与已锁定修正冲突，请先修改原条目。')
            if action == 'reject':
                db().execute('INSERT OR IGNORE INTO memory_tombstones VALUES(?,?,?)', (g.user['id'], item['signature'], now()))
                db().execute('DELETE FROM memories WHERE id=?', (mid,))
            else:
                signature = hashlib.sha256(re.sub(r'[\W_]+', '', content.lower()).encode()).hexdigest()
                db().execute('UPDATE memories SET content=?,proposed_value=?,status=?,kind=?,locked=?,signature=? WHERE id=?',
                             (content, content, status, kind, int(action == 'edit' or item['locked']), signature, mid))
        db().execute('UPDATE profiles SET version=version+1,updated_at=? WHERE user_id=?', (now(), g.user['id']))
        db().commit()
        if request.method == 'DELETE':
            return jsonify(deleted=True)
        if action == 'reject':
            return jsonify(memory={'id': mid, 'status': 'rejected', 'content': ''})
        return jsonify(memory=memory_data(owned('memories', mid)))

    @app.delete('/api/events/<int:eid>')
    @require_auth
    def delete_event(eid):
        event = owned('events', eid)
        invalidate_source('reflection', eid)
        db().execute('DELETE FROM focus_sessions WHERE id=? AND user_id=?', (event['session_id'], g.user['id']))
        db().execute('UPDATE profiles SET version=version+1,updated_at=? WHERE user_id=?', (now(), g.user['id']))
        db().commit()
        return jsonify(deleted=True, linked_letters_deleted=True, linked_memories_deleted=True)

    @app.patch('/api/events/<int:eid>')
    @require_auth
    def correct_event(eid):
        event = owned('events', eid)
        body = data()
        result = text(body, 'result', 20, True, event['result'])
        reflection = text(body, 'reflection', 2000, default=event['reflection'])
        elapsed = body.get('elapsed_seconds', event['elapsed_seconds'])
        if result not in ('completed', 'partial', 'stopped') or isinstance(elapsed, bool) or not isinstance(elapsed, (int, float)) or not math.isfinite(elapsed) or not 0 <= elapsed <= 604800:
            abort(400, description='请填写有效结果与 0–604800 秒的计时时长。')
        invalidate_source('reflection', eid)
        db().execute("UPDATE events SET result=?,reflection=?,elapsed_seconds=?,revision=revision+1,letter_status=CASE WHEN letter_status='pending' THEN 'failed' ELSE letter_status END WHERE id=?", (result, reflection, elapsed, eid))
        db().execute('UPDATE focus_sessions SET result=?,reflection=?,elapsed_seconds=?,timing_review_required=0 WHERE id=?', (result, reflection, elapsed, event['session_id']))
        focus = owned('focus_sessions', event['session_id'])
        db().execute('UPDATE tasks SET status=? WHERE id=?', (result, focus['task_id']))
        db().execute('UPDATE letters SET source_adjusted=1 WHERE source_id=? AND user_id=?', (eid, g.user['id']))
        db().execute('UPDATE profiles SET version=version+1,updated_at=? WHERE user_id=?', (now(), g.user['id']))
        db().commit()
        if reflection and g.user['memory_enabled']:
            queue_job('memory', 'reflection', eid)
        return jsonify(event=owned('events', eid), session=session_data(owned('focus_sessions', event['session_id'])))

    @app.get('/api/events/<int:eid>')
    @require_auth
    def get_event(eid):
        return jsonify(event=owned('events', eid))

    @app.get('/api/events')
    @require_auth
    def paginated_events():
        try:
            limit = min(100, max(1, int(request.args.get('limit', '30'))))
            before = int(request.args.get('before', '9223372036854775807'))
        except ValueError:
            abort(400, description='分页参数需要整数。')
        records = rows('SELECT * FROM events WHERE user_id=? AND id<? ORDER BY id DESC LIMIT ?', (g.user['id'], before, limit + 1))
        more = len(records) > limit
        records = records[:limit]
        return jsonify(events=records, has_more=more, next_cursor=records[-1]['id'] if more else None)

    @app.delete('/api/messages')
    @require_auth
    def delete_messages():
        for item in rows("SELECT id FROM messages WHERE user_id=? AND role='user'", (g.user['id'],)):
            invalidate_source('chat', item['id'])
        db().execute('DELETE FROM chat_requests WHERE user_id=?', (g.user['id'],))
        db().execute('DELETE FROM messages WHERE user_id=?', (g.user['id'],))
        db().commit()
        session['chat_since'] = now()
        return jsonify(deleted=True)

    @app.post('/api/account/password')
    @require_auth
    def change_password():
        body = data()
        current = body.get('current_password', '')
        if not isinstance(current, str) or len(current) > 128:
            abort(400, description='请输入当前密码。')
        password = body.get('new_password', '')
        if g.user['is_demo']:
            abort(400, description='临时档案无需密码；退出后可注册正式账号。')
        if not check_password_hash(g.user['password_hash'], current):
            abort(403, description='当前密码不正确。')
        if not isinstance(password, str) or not 8 <= len(password) <= 128:
            abort(400, description='新密码请使用 8–128 个字符。')
        db().execute('UPDATE users SET password_hash=?,auth_version=auth_version+1 WHERE id=?', (generate_password_hash(password), g.user['id']))
        db().commit()
        session['auth_version'] = g.user['auth_version'] + 1
        return jsonify(saved=True)

    @app.delete('/api/account')
    @require_auth
    def delete_account():
        body = data()
        password = body.get('password', '')
        if not g.user['is_demo'] and (not isinstance(password, str) or len(password) > 128 or not check_password_hash(g.user['password_hash'], password)):
            abort(403, description='请输入正确密码确认删除。')
        db().execute('DELETE FROM users WHERE id=?', (g.user['id'],))
        db().commit()
        session.clear()
        return jsonify(deleted=True, redirect='/login')

    @app.get('/api/export')
    @require_auth
    def export_account():
        uid = g.user['id']
        exported = {'exported_at': now(), 'user': user_public(g.user), 'profile': get_profile()}
        for table in ('messages', 'tasks', 'focus_sessions', 'events', 'letters', 'memories', 'milestones',
                      'growth_experiments', 'capabilities', 'weekly_experiments', 'growth_evidence'):
            exported[table] = rows(f'SELECT * FROM {table} WHERE user_id=? ORDER BY id', (uid,))
        exported['focus_intervals'] = rows('SELECT i.* FROM focus_intervals i JOIN focus_sessions s ON s.id=i.session_id WHERE s.user_id=? ORDER BY i.id', (uid,))
        response = jsonify(exported)
        response.headers['Content-Disposition'] = 'attachment; filename="future-self-export.json"'
        return response

    @app.get('/health')
    def health():
        return jsonify(status='ok', service='future-self')

    app.extensions['future_self_tick_callbacks'] = []
    app.extensions['future_self_source_loaders'] = {}
    app.extensions['future_self_run_jobs'] = run_jobs
    from extras import register_extras
    register_extras(app, {'db': db, 'row': row, 'rows': rows, 'owned': owned, 'require_auth': require_auth,
                         'data': data, 'text': text, 'number': number, 'boolean': boolean,
                         'get_profile': get_profile, 'model_profile': profile_for_model,
                         'invalidate_source': invalidate_source, 'now': now, 'queue_job': queue_job,
                         'confirmed_memories': confirmed_memories})
    from growth import register_growth
    register_growth(app, {'db': db, 'row': row, 'rows': rows, 'owned': owned, 'require_auth': require_auth,
                          'data': data, 'text': text, 'number': number, 'boolean': boolean,
                          'nullable_owner': nullable_owner, 'get_profile': get_profile,
                          'model_profile': profile_for_model, 'now': now})
    if not app.config.get('TESTING'):
        def worker():
            while True:
                try:
                    with app.app_context():
                        run_jobs(limit=10)
                        for callback in app.extensions['future_self_tick_callbacks']:
                            callback()
                except Exception:
                    app.logger.error('Background tick deferred; durable jobs remain queued.')
                time.sleep(2)
        threading.Thread(target=worker, daemon=True, name='future-self-jobs').start()
    return app


if __name__ == '__main__':
    create_app().run(host=os.environ.get('HOST', '0.0.0.0'), port=int(os.environ.get('PORT', '5001')), debug=False)
