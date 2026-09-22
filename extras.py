"""Small persisted P1 features; the existing Flask app remains the authority."""
import csv
import hashlib
import io
import json
import secrets
import sqlite3
import time
import zipfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from xml.etree import ElementTree

from flask import abort, g, jsonify, request, send_from_directory

import modeling


SCHEMA = '''
CREATE TABLE IF NOT EXISTS goals (
 id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
 title TEXT NOT NULL, description TEXT NOT NULL DEFAULT '', target_date TEXT,
 status TEXT NOT NULL DEFAULT 'active', created_at TEXT NOT NULL, updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS imports (
 id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
 title TEXT NOT NULL, content TEXT NOT NULL, allow_memory INTEGER NOT NULL DEFAULT 0,
 created_at TEXT NOT NULL, revision INTEGER NOT NULL DEFAULT 1
);
CREATE TABLE IF NOT EXISTS profile_versions (
 id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
 version INTEGER NOT NULL, snapshot TEXT NOT NULL, created_at TEXT NOT NULL,
 UNIQUE(user_id,version)
);
CREATE TABLE IF NOT EXISTS preferences (
 user_id INTEGER PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
 weekly_enabled INTEGER NOT NULL DEFAULT 0, weekly_day INTEGER NOT NULL DEFAULT 6,
 weekly_hour INTEGER NOT NULL DEFAULT 20, timezone_offset INTEGER NOT NULL DEFAULT 480,
 notifications_enabled INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS notifications (
 id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
 event_key TEXT NOT NULL, title TEXT NOT NULL, body TEXT NOT NULL, href TEXT NOT NULL,
 is_read INTEGER NOT NULL DEFAULT 0, created_at TEXT NOT NULL, UNIQUE(user_id,event_key)
);
CREATE TABLE IF NOT EXISTS reviews (
 id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
 period_start TEXT NOT NULL, period_end TEXT NOT NULL, title TEXT NOT NULL, body TEXT NOT NULL,
 model TEXT NOT NULL, source_ids TEXT NOT NULL, profile_version INTEGER NOT NULL,
 created_at TEXT NOT NULL, source_adjusted INTEGER NOT NULL DEFAULT 0,
 UNIQUE(user_id,period_start,period_end)
);
CREATE TABLE IF NOT EXISTS feedback (
 user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
 event_id INTEGER NOT NULL REFERENCES events(id) ON DELETE CASCADE,
 helpful INTEGER, autonomy TEXT NOT NULL, created_at TEXT NOT NULL, PRIMARY KEY(user_id,event_id)
);
CREATE TABLE IF NOT EXISTS analytics_events (
 id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
 name TEXT NOT NULL, event_key TEXT NOT NULL, entity_id INTEGER, created_at TEXT NOT NULL,
 UNIQUE(user_id,event_key)
);
CREATE TABLE IF NOT EXISTS drafts (
 user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
 key TEXT NOT NULL, value TEXT NOT NULL, version INTEGER NOT NULL DEFAULT 1,
 updated_at TEXT NOT NULL, PRIMARY KEY(user_id,key)
);
CREATE TABLE IF NOT EXISTS sync_versions (
 user_id INTEGER PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
 revision INTEGER NOT NULL DEFAULT 1, updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS profile_history_deleted (
 user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
 version INTEGER NOT NULL, PRIMARY KEY(user_id,version)
);
'''


def register_extras(app, services):
    db, row, rows = (services[k] for k in ('db', 'row', 'rows'))
    owned, auth, data = (services[k] for k in ('owned', 'require_auth', 'data'))
    text, number, boolean = (services[k] for k in ('text', 'number', 'boolean'))
    get_profile, now, queue_job = (services[k] for k in ('get_profile', 'now', 'queue_job'))
    model_profile, invalidate_source = (services[k] for k in ('model_profile', 'invalidate_source'))
    app.config['MAX_CONTENT_LENGTH'] = 2 * 1024 * 1024
    app.config['TEMPLATES_AUTO_RELOAD'] = True
    with app.app_context():
        db().executescript(SCHEMA)
        for name, definition in [('open_at', 'TEXT'), ('open_notified', 'INTEGER NOT NULL DEFAULT 0')]:
            if name not in {item['name'] for item in db().execute('PRAGMA table_info(letters)')}:
                db().execute(f'ALTER TABLE letters ADD COLUMN {name} {definition}')
        if 'stats' not in {item['name'] for item in db().execute('PRAGMA table_info(reviews)')}:
            db().execute("ALTER TABLE reviews ADD COLUMN stats TEXT NOT NULL DEFAULT '{}'")
        db().commit()

    def prefs(uid=None):
        uid = uid or g.user['id']
        return row('SELECT * FROM preferences WHERE user_id=?', (uid,)) or {
            'user_id': uid, 'weekly_enabled': False, 'weekly_day': 6,
            'weekly_hour': 20, 'timezone_offset': 480, 'notifications_enabled': False}

    def snapshot():
        profile = get_profile()
        if row('SELECT version FROM profile_history_deleted WHERE user_id=? AND version=?', (g.user['id'], profile['version'])):
            return
        values = {key: profile.get(key, '') for key in ('ideal', 'values', 'current', 'conditions', 'tone')}
        db().execute('INSERT OR IGNORE INTO profile_versions(user_id,version,snapshot,created_at) VALUES(?,?,?,?)',
                     (g.user['id'], profile['version'], json.dumps(values, ensure_ascii=False), now()))

    def notify(uid, key, title, body, href):
        db().execute('INSERT OR IGNORE INTO notifications(user_id,event_key,title,body,href,created_at) VALUES(?,?,?,?,?,?)',
                     (uid, key, title, body, href, now()))

    def locked_letter(letter):
        if not isinstance(letter, dict):
            return letter
        result = dict(letter)
        opening = result.get('open_at')
        try:
            locked = bool(opening and datetime.fromisoformat(opening.replace('Z', '+00:00')) > datetime.now(timezone.utc))
        except (ValueError, TypeError):
            locked = bool(opening)
        result['locked'] = locked
        if locked:
            result['body'] = ''
        return result

    def sync_state():
        uid = g.user['id']
        revision = row('SELECT revision,updated_at FROM sync_versions WHERE user_id=?', (uid,)) or {'revision': 0, 'updated_at': now()}
        # ponytail: a handful of indexed aggregate queries; use a shared event cursor at larger scale.
        counts = [row(f'SELECT COUNT(*) AS n,MAX(id) AS last FROM {table} WHERE user_id=?', (uid,))
                  for table in ('messages', 'letters', 'memories', 'notifications')]
        jobs = rows('SELECT status,COUNT(*) AS n FROM jobs WHERE user_id=? GROUP BY status', (uid,)) if row("SELECT name FROM sqlite_master WHERE name='jobs'") else []
        digest = hashlib.sha256(json.dumps([revision, counts, jobs], sort_keys=True).encode()).hexdigest()[:20]
        return {'revision': digest, 'server_time': time.time(), 'updated_at': revision['updated_at'],
                'unread_notifications': row('SELECT COUNT(*) AS n FROM notifications WHERE user_id=? AND is_read=0', (uid,))['n']}

    @app.before_request
    def extras_before():
        if getattr(g, 'user', None) and request.method in ('POST', 'PATCH', 'PUT', 'DELETE'):
            snapshot()
            db().commit()

    @app.after_request
    def extras_after(response):
        if not getattr(g, 'user', None) or not row('SELECT id FROM users WHERE id=?', (g.user['id'],)):
            return response
        uid = g.user['id']
        response.headers['X-Future-Self-User'] = str(uid)
        if request.method in ('POST', 'PATCH', 'PUT', 'DELETE') and response.status_code < 300:
            snapshot()
            db().execute('INSERT INTO sync_versions(user_id,revision,updated_at) VALUES(?,1,?) ON CONFLICT(user_id) DO UPDATE SET revision=revision+1,updated_at=excluded.updated_at', (uid, now()))
            if request.path.startswith('/api/events/') and request.method in ('PATCH', 'DELETE'):
                db().execute('UPDATE reviews SET source_adjusted=1 WHERE user_id=?', (uid,))
            names = {'/api/onboarding': 'onboarding_confirmed', '/api/tasks': 'task_confirmed', '/api/chat': 'chat_reply',
                     '/api/profile': 'profile_corrected', '/api/focus/start': 'focus_started'}
            event_name = names.get(request.path)
            if request.path.startswith('/api/focus/') and request.path != '/api/focus/start':
                event_name = {'pause':'focus_paused','resume':'focus_resumed','end':'focus_ended','finish':'focus_settled'}.get((request.get_json(silent=True) or {}).get('action'))
            if event_name:
                payload = request.get_json(silent=True) or {}
                if event_name != 'onboarding_confirmed' or payload.get('complete'):
                    db().execute('INSERT OR IGNORE INTO analytics_events(user_id,name,event_key,created_at) VALUES(?,?,?,?)',
                                 (uid, event_name, event_name + ':' + str(payload.get('request_id') or secrets.token_hex(10)), now()))
            if request.path == '/api/profile' and (request.get_json(silent=True) or {}).get('memory_enabled') is False:
                db().execute('INSERT OR IGNORE INTO analytics_events(user_id,name,event_key,created_at) VALUES(?,?,?,?)',
                             (uid, 'memory_opt_out', 'memory_opt_out:'+secrets.token_hex(10), now()))
            db().commit()
        if response.is_json and response.status_code < 300:
            body = response.get_json()
            if isinstance(body, dict):
                if isinstance(body.get('letters'), list):
                    body['letters'] = [locked_letter(item) for item in body['letters']]
                if isinstance(body.get('letter'), dict):
                    body['letter'] = locked_letter(body['letter'])
                if request.path == '/api/state':
                    body['preferences'] = prefs()
                    body['goals'] = goal_list()
                    body['sync'] = sync_state()
                if request.path == '/api/export':
                    for table in ('goals', 'imports', 'profile_versions', 'reviews', 'preferences', 'notifications', 'feedback', 'drafts'):
                        body[table] = rows(f'SELECT * FROM {table} WHERE user_id=?', (uid,))
                response.set_data(app.json.dumps(body))
        return response

    @app.get('/sw.js')
    def service_worker():
        response = send_from_directory(app.static_folder, 'sw.js', mimetype='application/javascript')
        response.headers['Service-Worker-Allowed'] = '/'
        response.headers['Cache-Control'] = 'no-cache'
        return response

    @app.get('/api/sync')
    @auth
    def get_sync():
        return jsonify(sync_state())

    @app.get('/api/drafts')
    @auth
    def get_drafts():
        return jsonify(drafts=[dict(item, value=json.loads(item['value'])) for item in rows('SELECT * FROM drafts WHERE user_id=?', (g.user['id'],))])

    @app.put('/api/drafts/<key>')
    @auth
    def save_draft(key):
        if key not in {'chat-draft', 'letter-draft', 'focus-task-draft', 'action-draft', 'onboarding-answers'}:
            abort(400, description='草稿类型未识别。')
        body = data()
        value = json.dumps(body.get('value'), ensure_ascii=False)
        if len(value) > 32000:
            abort(400, description='草稿请控制在 32000 字以内。')
        base = number(body, 'base_version', 0)
        connection = db()
        connection.execute('BEGIN IMMEDIATE')
        current = row('SELECT * FROM drafts WHERE user_id=? AND key=?', (g.user['id'], key))
        if (current['version'] if current else 0) != base:
            connection.rollback()
            return jsonify(error='另一台设备更新了这份草稿，两份内容均已保留。', conflict=dict(current, value=json.loads(current['value'])) if current else None), 409
        version = base + 1
        connection.execute('INSERT INTO drafts(user_id,key,value,version,updated_at) VALUES(?,?,?,?,?) ON CONFLICT(user_id,key) DO UPDATE SET value=excluded.value,version=excluded.version,updated_at=excluded.updated_at',
                           (g.user['id'], key, value, version, now()))
        connection.commit()
        return jsonify(key=key, version=version, saved=True)

    @app.get('/api/profile/history')
    @auth
    def history():
        snapshot()
        db().commit()
        return jsonify(versions=[dict(item, snapshot=json.loads(item['snapshot'])) for item in rows('SELECT * FROM profile_versions WHERE user_id=? ORDER BY id DESC LIMIT 100', (g.user['id'],))])

    @app.delete('/api/profile/history/<int:version_id>')
    @auth
    def delete_history(version_id):
        item = owned('profile_versions', version_id)
        db().execute('INSERT OR IGNORE INTO profile_history_deleted(user_id,version) VALUES(?,?)', (g.user['id'], item['version']))
        db().execute('DELETE FROM profile_versions WHERE id=? AND user_id=?', (version_id, g.user['id']))
        db().commit()
        return jsonify(deleted=True)

    @app.route('/api/preferences', methods=['GET', 'POST'])
    @auth
    def preferences():
        if request.method == 'POST':
            body, old = data(), prefs()
            values = {key: boolean(body, key, bool(old[key])) for key in ('weekly_enabled', 'notifications_enabled')}
            for key, low, high in [('weekly_day',0,6), ('weekly_hour',0,23), ('timezone_offset',-720,840)]:
                values[key] = number(body, key, low, high) if key in body else old[key]
            db().execute('INSERT INTO preferences(user_id,weekly_enabled,weekly_day,weekly_hour,timezone_offset,notifications_enabled) VALUES(?,?,?,?,?,?) ON CONFLICT(user_id) DO UPDATE SET weekly_enabled=excluded.weekly_enabled,weekly_day=excluded.weekly_day,weekly_hour=excluded.weekly_hour,timezone_offset=excluded.timezone_offset,notifications_enabled=excluded.notifications_enabled',
                         (g.user['id'], int(values['weekly_enabled']), values['weekly_day'], values['weekly_hour'], values['timezone_offset'], int(values['notifications_enabled'])))
            db().commit()
        return jsonify(preferences=prefs())

    @app.get('/api/notifications')
    @auth
    def notification_list():
        tick(only_user=g.user['id'], include_weekly=False)
        return jsonify(notifications=rows('SELECT * FROM notifications WHERE user_id=? ORDER BY id DESC LIMIT 50', (g.user['id'],)), preferences=prefs())

    @app.patch('/api/notifications/<int:nid>')
    @auth
    def notification_read(nid):
        owned('notifications', nid)
        db().execute('UPDATE notifications SET is_read=1 WHERE id=?', (nid,))
        db().commit()
        return jsonify(read=True)

    @app.get('/api/goals')
    @auth
    def goals():
        return jsonify(goals=goal_list())

    def goal_list():
        return rows('''SELECT g.*,
          (SELECT COUNT(*) FROM milestones m WHERE m.goal_id=g.id AND m.user_id=g.user_id) AS milestone_count,
          (SELECT COUNT(*) FROM milestones m WHERE m.goal_id=g.id AND m.user_id=g.user_id AND m.completed=1) AS completed_count
          FROM goals g WHERE g.user_id=? ORDER BY g.id DESC''', (g.user['id'],))

    @app.post('/api/goals')
    @auth
    def new_goal():
        body = data()
        title, description = text(body, 'title', 200, True), text(body, 'description', 2000)
        target = validate_date(body.get('target_date'))
        stamp = now()
        gid = db().execute('INSERT INTO goals(user_id,title,description,target_date,created_at,updated_at) VALUES(?,?,?,?,?,?)',
                           (g.user['id'], title, description, target, stamp, stamp)).lastrowid
        db().commit()
        return jsonify(goal=owned('goals', gid)), 201

    @app.route('/api/goals/<int:gid>', methods=['PATCH', 'DELETE'])
    @auth
    def update_goal(gid):
        goal = owned('goals', gid)
        if request.method == 'DELETE':
            db().execute('UPDATE tasks SET goal_id=NULL WHERE user_id=? AND goal_id=?', (g.user['id'], gid))
            db().execute('UPDATE milestones SET goal_id=NULL WHERE user_id=? AND goal_id=?', (g.user['id'], gid))
            db().execute('DELETE FROM goals WHERE id=?', (gid,))
            db().commit()
            return jsonify(deleted=True)
        body = data()
        status = text(body, 'status', 20, default=goal['status'])
        if status not in ('active', 'completed', 'paused'):
            abort(400, description='目标状态未识别。')
        db().execute('UPDATE goals SET title=?,description=?,target_date=?,status=?,updated_at=? WHERE id=?',
                     (text(body, 'title', 200, True, goal['title']), text(body, 'description', 2000, default=goal['description']),
                      validate_date(body.get('target_date', goal['target_date'])), status, now(), gid))
        db().commit()
        return jsonify(goal=owned('goals', gid))

    def validate_date(value):
        if not value:
            return None
        if not isinstance(value, str) or len(value) != 10:
            abort(400, description='日期请使用 YYYY-MM-DD。')
        try:
            return datetime.strptime(value, '%Y-%m-%d').date().isoformat()
        except ValueError:
            abort(400, description='日期未识别。')

    @app.post('/api/goals/<int:gid>/decompose')
    @auth
    def goal_steps(gid):
        goal = owned('goals', gid)
        version, consent = get_profile()['version'], g.user['consent_version']
        result = modeling.decompose_goal(model_profile(), goal)
        if owned('goals', gid) != goal or get_profile()['version'] != version or row('SELECT consent_version FROM users WHERE id=?', (g.user['id'],))['consent_version'] != consent:
            abort(409, description='目标或授权刚有调整，请按新版本重新拆分。')
        return jsonify(result)

    @app.patch('/api/tasks/<int:tid>')
    @auth
    def edit_task(tid):
        task, body = owned('tasks', tid), data()
        if row("SELECT id FROM focus_sessions WHERE task_id=? AND user_id=? AND status!='ended'", (tid, g.user['id'])):
            abort(409, description='正在沉浸的任务先保持不变，结束后可调整下一步。')
        fields = [text(body, key, 300, True, task[key]) for key in ('title','first_step','done_criteria')]
        minutes = number(body, 'planned_minutes', 1, 180) if 'planned_minutes' in body else task['planned_minutes']
        db().execute('UPDATE tasks SET title=?,first_step=?,done_criteria=?,planned_minutes=? WHERE id=?', (*fields, minutes, tid))
        db().commit()
        return jsonify(task=owned('tasks', tid))

    @app.get('/api/imports')
    @auth
    def import_list():
        return jsonify(imports=rows('SELECT * FROM imports WHERE user_id=? ORDER BY id DESC', (g.user['id'],)))

    @app.post('/api/imports')
    @auth
    def import_material():
        if request.files:
            uploaded = request.files.get('file')
            if not uploaded:
                abort(400, description='请选择资料文件。')
            filename = Path(uploaded.filename or '资料.txt').name
            raw = uploaded.read(512001)
            if len(raw) > 512000:
                abort(400, description='单份资料请控制在 500 KB 内。')
            extension = Path(filename).suffix.lower()
            if extension not in {'.txt','.md','.csv','.json','.docx'}:
                abort(400, description='支持 TXT、Markdown、CSV、JSON 与 DOCX。')
            try:
                if extension == '.docx':
                    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
                        info = archive.getinfo('word/document.xml')
                        if info.file_size > 2_000_000:
                            raise ValueError('expanded document too large')
                        document = ElementTree.fromstring(archive.read(info))
                        content = '\n'.join(''.join(part.itertext()) for part in document.iter('{http://schemas.openxmlformats.org/wordprocessingml/2006/main}p'))
                else:
                    try:
                        content = raw.decode('utf-8-sig')
                    except UnicodeDecodeError:
                        content = raw.decode('gb18030')
                    if extension == '.json':
                        content = json.dumps(json.loads(content), ensure_ascii=False, indent=2)
                if '\x00' in content:
                    raise ValueError('binary input')
            except (ValueError, UnicodeError, zipfile.BadZipFile, KeyError, ElementTree.ParseError):
                abort(400, description='资料格式未识别，请检查文件或直接粘贴文本。')
            title = request.form.get('title', filename).strip()[:200]
            allow = request.form.get('allow_memory') == 'true'
        else:
            body = data()
            title, content, allow = text(body, 'title', 200, True), text(body, 'content', 30000, True), boolean(body, 'allow_memory')
        if not content.strip() or len(content) > 30000:
            abort(400, description='资料需包含正文，最多 30000 字。')
        iid = db().execute('INSERT INTO imports(user_id,title,content,allow_memory,created_at) VALUES(?,?,?,?,?)',
                           (g.user['id'], title or '导入资料', content.strip(), int(allow), now())).lastrowid
        db().commit()
        if allow and g.user['memory_enabled']:
            queue_job('memory', 'import', iid)
        return jsonify(material=owned('imports', iid)), 201

    @app.route('/api/imports/<int:iid>', methods=['PATCH', 'DELETE'])
    @auth
    def change_import(iid):
        item = owned('imports', iid)
        if request.method == 'DELETE':
            db().execute('DELETE FROM imports WHERE id=?', (iid,))
        else:
            body = data()
            allow = boolean(body, 'allow_memory', bool(item['allow_memory']))
            db().execute('UPDATE imports SET allow_memory=?,revision=revision+1 WHERE id=?', (int(allow), iid))
        invalidate_source('import', iid)
        db().execute('UPDATE profiles SET version=version+1,updated_at=? WHERE user_id=?', (now(), g.user['id']))
        db().commit()
        if request.method != 'DELETE' and allow and g.user['memory_enabled']:
            queue_job('memory', 'import', iid)
        return jsonify(deleted=True) if request.method == 'DELETE' else jsonify(material=owned('imports', iid))

    @app.post('/api/feedback')
    @auth
    def event_feedback():
        body = data()
        eid = number(body, 'event_id')
        owned('events', eid)
        helpful = body.get('helpful')
        if helpful is not None and not isinstance(helpful, bool):
            abort(400, description='帮助度请选择是、否或跳过。')
        autonomy = text(body, 'autonomy', 20, default='neutral')
        if autonomy not in ('understood', 'pressured', 'neutral'):
            abort(400, description='请选择真实的感受。')
        db().execute('INSERT INTO feedback(user_id,event_id,helpful,autonomy,created_at) VALUES(?,?,?,?,?) ON CONFLICT(user_id,event_id) DO UPDATE SET helpful=excluded.helpful,autonomy=excluded.autonomy',
                     (g.user['id'], eid, helpful, autonomy, now()))
        db().commit()
        return jsonify(saved=True)

    @app.route('/api/analytics', methods=['GET', 'POST'])
    @auth
    def analytics():
        if request.method == 'POST':
            body = data()
            name = text(body, 'name', 40, True)
            if name not in {'onboarding_started','action_card_viewed','echo_viewed','letter_opened','memory_opt_out','page_viewed'}:
                abort(400, description='事件类型未识别。')
            key = text(body, 'request_id', 100, default=secrets.token_hex(12))
            entity_id = text(body, 'entity_id', 40)
            db().execute('INSERT OR IGNORE INTO analytics_events(user_id,name,event_key,entity_id,created_at) VALUES(?,?,?,?,?)', (g.user['id'], name, name+':'+key, entity_id, now()))
            db().commit()
        return jsonify(events=rows('SELECT name,COUNT(*) AS count FROM analytics_events WHERE user_id=? GROUP BY name', (g.user['id'],)),
                       feedback=rows('SELECT helpful,autonomy,COUNT(*) AS count FROM feedback WHERE user_id=? GROUP BY helpful,autonomy', (g.user['id'],)))

    def make_review(uid, automatic=False):
        preference = prefs(uid)
        if automatic and not preference['weekly_enabled']:
            return None
        local_today = (datetime.now(timezone.utc) + timedelta(minutes=preference['timezone_offset'])).date()
        start_date, end_date = local_today - timedelta(days=6), local_today + timedelta(days=1)
        start = datetime.combine(start_date, datetime.min.time(), tzinfo=timezone(timedelta(minutes=preference['timezone_offset']))).astimezone(timezone.utc).isoformat()
        end = datetime.combine(end_date, datetime.min.time(), tzinfo=timezone(timedelta(minutes=preference['timezone_offset']))).astimezone(timezone.utc).isoformat()
        existing = row('SELECT * FROM reviews WHERE user_id=? AND period_start=? AND period_end=?', (uid, start_date.isoformat(), local_today.isoformat()))
        if existing and not existing['source_adjusted']:
            return review_data(existing)
        events = rows('SELECT * FROM events WHERE user_id=? AND created_at>=? AND created_at<? ORDER BY created_at', (uid, start, end))
        profile = model_profile()
        consent_version = g.user['consent_version']
        growth_context = app.extensions.get('future_self_growth_context')
        growth = growth_context(uid) if growth_context else {
            'experiment': None, 'active_week': None, 'capabilities': [], 'evidence': []}
        result = modeling.weekly_review(profile, events, growth)
        db().execute('BEGIN IMMEDIATE')
        fresh_user = row('SELECT * FROM users WHERE id=?', (uid,))
        if not fresh_user or fresh_user['consent_version'] != consent_version or (automatic and prefs(uid) != preference):
            db().rollback()
            return None
        current_events = rows('SELECT * FROM events WHERE user_id=? AND created_at>=? AND created_at<? ORDER BY created_at', (uid, start, end))
        current_growth = growth_context(uid) if growth_context else growth
        if events != current_events or current_growth != growth or get_profile()['version'] != profile['version']:
            db().rollback()
            return None
        experiment = growth.get('experiment') or {}
        active_week = growth.get('active_week') or {}
        db().execute('INSERT INTO reviews(user_id,period_start,period_end,title,body,model,source_ids,profile_version,created_at,experiment_id,week_number) VALUES(?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(user_id,period_start,period_end) DO UPDATE SET title=excluded.title,body=excluded.body,model=excluded.model,source_ids=excluded.source_ids,profile_version=excluded.profile_version,source_adjusted=0,experiment_id=excluded.experiment_id,week_number=excluded.week_number',
                     (uid, start_date.isoformat(), local_today.isoformat(), result['title'], result['body'], json.dumps(result.get('model', {}), ensure_ascii=False), json.dumps([e['id'] for e in events]), profile['version'], now(), experiment.get('id'), active_week.get('week_number')))
        stats = {'session_count':len(events), 'recorded_minutes':round(sum(e['elapsed_seconds'] for e in events)/60, 1),
                 **{key+'_count':sum(e['result']==key for e in events) for key in ('completed','partial','stopped')},
                 'growth_evidence_ids': result.get('growth_evidence_ids', []),
                 'next_week_proposal': result.get('next_week_proposal')}
        db().execute('UPDATE reviews SET stats=? WHERE user_id=? AND period_start=? AND period_end=?',
                     (json.dumps(stats), uid, start_date.isoformat(), local_today.isoformat()))
        db().commit()
        review = row('SELECT * FROM reviews WHERE user_id=? AND period_start=? AND period_end=?', (uid, start_date.isoformat(), local_today.isoformat()))
        return review_data(review)

    def review_data(review):
        return dict(review, model=json.loads(review['model']), stats=json.loads(review['stats']))

    @app.route('/api/reviews/weekly', methods=['GET', 'POST'])
    @auth
    def weekly():
        if request.method == 'POST':
            review = make_review(g.user['id'])
            if not review:
                return jsonify(error='资料刚有变化，请重新生成本周回顾。'), 409
            return jsonify(review=review)
        return jsonify(reviews=[review_data(item) for item in rows('SELECT * FROM reviews WHERE user_id=? ORDER BY id DESC LIMIT 52', (g.user['id'],))])

    @app.get('/api/reviews/<int:rid>')
    @auth
    def get_review(rid):
        result = owned('reviews', rid)
        return jsonify(review=review_data(result))

    def tick(only_user=None, include_weekly=True):
        original = getattr(g, 'user', None)
        moment = datetime.now(timezone.utc)
        user_clause, parameters = (' AND l.user_id=?', (only_user,)) if only_user else ('', ())
        due = rows("SELECT l.* FROM letters l JOIN users u ON u.id=l.user_id WHERE l.open_at IS NOT NULL AND l.open_at<=? AND l.open_notified=0" + user_clause, (moment.isoformat(), *parameters))
        try:
            for letter in due:
                g.user = row('SELECT * FROM users WHERE id=?', (letter['user_id'],))
                notify(letter['user_id'], f"letter:{letter['id']}", '一封信，到了约定的时间', '你留给未来的文字，现在可以打开了。', f"/echoes?letter={letter['id']}")
                db().execute('UPDATE letters SET open_notified=1 WHERE id=?', (letter['id'],))
                db().commit()
                if letter['allow_memory'] and g.user['memory_enabled']:
                    queue_job('memory', 'letter', letter['id'])
            if include_weekly:
                for preference in rows('SELECT * FROM preferences WHERE weekly_enabled=1' + (' AND user_id=?' if only_user else ''), (only_user,) if only_user else ()):
                    local = moment + timedelta(minutes=preference['timezone_offset'])
                    if local.weekday() < preference['weekly_day'] or (local.weekday() == preference['weekly_day'] and local.hour < preference['weekly_hour']):
                        continue
                    key = 'weekly:' + local.strftime('%G-%V')
                    if row('SELECT id FROM notifications WHERE user_id=? AND event_key=?', (preference['user_id'], key)):
                        continue
                    g.user = row('SELECT * FROM users WHERE id=?', (preference['user_id'],))
                    if not g.user:
                        continue
                    review = make_review(g.user['id'], automatic=True)
                    db().execute('BEGIN IMMEDIATE')
                    if review and prefs(g.user['id']) == preference:
                        notify(g.user['id'], key, '这一周，值得轻轻回看', '你的周回顾已准备好，基于真实行动而不是人生评分。', '/echoes?review=' + str(review['id']))
                    db().commit()
        finally:
            g.user = original

    app.extensions.setdefault('future_self_tick_callbacks', []).append(tick)
    app.extensions['future_self_extras_tick'] = tick
