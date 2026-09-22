"""One disposable V2 integration flow; no network, sleeps, or real-account data."""
import sys
from pathlib import Path

if '--expect-unbuilt' in sys.argv:
    assert not Path(__file__).with_name('app.py').exists(), 'app.py still exists'
    print('PASS: baseline restored; application absent')
    raise SystemExit(0)

if __name__ == '__main__':
    import os
    import json
    import sqlite3
    import tempfile
    import time
    from datetime import datetime, timedelta, timezone
    from unittest.mock import patch
    os.environ['AI_API_KEY'] = ''
    os.environ['AI_MODEL'] = ''
    from app import create_app

    with tempfile.TemporaryDirectory() as directory:
        database = str(Path(directory) / 'check.db')
        app = create_app({'TESTING': True, 'DATABASE': database, 'SECRET_KEY': 'local-check-only'})
        client, headers = app.test_client(), {}

        def sql(statement, args=()):
            connection = sqlite3.connect(database)
            try:
                result = connection.execute(statement, args).fetchall()
                connection.commit()
                return result
            finally:
                connection.close()

        def api(path, body=None, method='POST', expected=None):
            response = client.open(path, method=method, json=body, headers=headers)
            assert response.status_code == expected if expected else response.status_code < 300, (path, response.status_code, response.get_json())
            return response.get_json()

        def state():
            return api('/api/state', method='GET')

        def csrf():
            with client.session_transaction() as saved:
                return saved['csrf_token']

        def login():
            client.get('/login')
            assert client.post('/login', data={'csrf_token': csrf(), 'email': 'check@example.test', 'password': 'temporary-check-only'}).status_code == 302
            headers['X-CSRF-Token'] = csrf()

        assert client.get('/api/session').status_code == 401
        assert client.get('/register').status_code == 200
        assert client.post('/register', data={'csrf_token': csrf(), 'name': '检查账号', 'email': 'check@example.test', 'password': 'temporary-check-only'}).status_code == 302
        headers['X-CSRF-Token'] = csrf()
        identity = api('/api/session', method='GET')
        assert identity['csrf_token'] == csrf()
        uid = identity['user_id']
        answers = ['从容地使用英语', '不透支自己', '不知道怎样开始', '十分钟的小任务', '温柔简短']
        assert api('/api/onboarding/question', {'answers': answers, 'step': 1})['question']
        api('/api/onboarding', {'answers': answers, 'complete': True, 'memory_enabled': False})
        assert state()['model_profile']['ideal'] == answers[0]
        api('/api/jobs/run', {})
        assert any(letter['source_id'] is None for letter in state()['letters'])
        assert client.post('/logout', data={'csrf_token': csrf()}).status_code == 302
        login()
        assert state()['model_profile']['ideal'] == ''
        api('/api/profile', {'profile_reuse_enabled': True})
        assert state()['model_profile']['ideal'] == answers[0]
        api('/api/profile', {'profile_reuse_enabled': False, 'tone': '清晰简短'})
        assert client.post('/logout', data={'csrf_token': csrf()}).status_code == 302
        login()
        assert state()['model_profile']['ideal'] == '' and state()['model_profile']['tone'] == '清晰简短'
        for page in ('chat', 'focus', 'echoes', 'profile'):
            assert client.get('/' + page).status_code == 200
        assert client.post('/api/tasks', json={}).status_code == 403

        class ProviderResponse:
            def __init__(self, envelope):
                self.payload = json.dumps(envelope).encode('utf-8')

            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def read(self, _limit):
                return self.payload

        broken = {'choices': [{'finish_reason': 'length', 'message': {'content': '{"reply_text":"不应显示"'}}]}
        repaired = {'choices': [{'finish_reason': 'stop', 'message': {'content': json.dumps({
            'reply_text': '这是修复后的可见回答。', 'intent': 'listen',
            'action_suggestion': None, 'evidence_ids': []}, ensure_ascii=False)}}]}
        provider_env = {'AI_BASE_URL': 'https://provider.example/v1', 'AI_MODEL': 'test-model', 'AI_API_KEY': 'test-only-key'}
        with patch.dict(os.environ, provider_env), patch('modeling.urllib.request.urlopen', side_effect=[ProviderResponse(broken), ProviderResponse(repaired)]):
            repaired_reply = api('/api/chat', {'message': '测试协议修复', 'request_id': 'protocol-repaired'})
        assert repaired_reply['reply_text'] == '这是修复后的可见回答。'
        assert state()['messages'][-1]['content'] == '这是修复后的可见回答。'

        with patch.dict(os.environ, provider_env), patch('modeling.urllib.request.urlopen', side_effect=[ProviderResponse(broken), ProviderResponse(broken)]):
            fallback_reply = api('/api/chat', {'message': '测试安全降级', 'request_id': 'protocol-fallback'})
        assert fallback_reply['model']['mode'] == 'local'
        assert not fallback_reply['reply_text'].lstrip().startswith(('{', '[', '```'))
        assert 'reply_text' not in fallback_reply['reply_text'] and '不应显示' not in fallback_reply['reply_text']
        assert state()['messages'][-1]['content'] == fallback_reply['reply_text']

        api('/api/profile', {'memory_enabled': True})
        message = {'message': '我喜欢不透支生活的进步。希望你说话简短直接。', 'request_id': 'preferences'}
        reply = api('/api/chat', message)
        assert api('/api/chat', message)['message_id'] == reply['message_id']
        api('/api/jobs/run', {})
        candidates = state()['memories']
        value = next(item for item in candidates if item['field'] == 'values')
        tone = next(item for item in candidates if item['field'] == 'tone')
        api('/api/memories/' + str(value['id']), {'action': 'confirm'}, 'PATCH')
        api('/api/memories/' + str(tone['id']), {'action': 'reject'}, 'PATCH')
        assert not sql('SELECT content FROM memories WHERE id=?', (tone['id'],))
        assert sql('SELECT signature FROM memory_tombstones WHERE user_id=? AND signature=?', (uid, tone['signature']))
        api('/api/messages/' + str(reply['message_id']) + '/feedback', {'feedback': 'direct'})
        assert 'direct' in next(item for item in state()['messages'] if item['id'] == reply['message_id'])['feedback']
        action = api('/api/chat', {'message': '我想学英语，从十分钟开始', 'request_id': 'action'})
        assert action['action_suggestion']['first_step']
        api('/api/jobs/run', {})

        goal = api('/api/goals', {'title': '持续练习英语', 'description': '从小步骤开始'})['goal']
        assert api('/api/goals/' + str(goal['id']) + '/decompose', {})['steps']
        milestone = api('/api/milestones', {'title': '第一次开口', 'date': '2026-12-01', 'goal_id': goal['id']})['milestone']
        task = api('/api/tasks', {**action['action_suggestion'], 'goal_id': goal['id'], 'milestone_id': milestone['id']})['task']
        assert task['goal_id'] == goal['id'] and task['milestone_id'] == milestone['id']
        # A supplied offline chronology: 60 running + 30 paused + 30 running = 90 seconds.
        base = time.time() - 180
        start = {'task_id': task['id'], 'request_id': 'start', 'offline': True, 'occurred_at': base}
        focus = api('/api/focus/start', start)['session']
        assert api('/api/focus/start', start)['session']['id'] == focus['id']
        endpoint = '/api/focus/' + str(focus['id'])
        def focus_action(action_name, offset, **more):
            return api(endpoint, {'action': action_name, 'request_id': action_name, 'offline': True, 'occurred_at': base + offset, **more})
        assert focus_action('pause', 60)['session']['status'] == 'paused'
        api(endpoint, {'action': 'resume', 'request_id': 'out-of-order', 'offline': True, 'occurred_at': base + 50}, expected=409)
        assert focus_action('resume', 90)['session']['status'] == 'running'
        ended = focus_action('end', 120)['session']
        assert ended['status'] == 'ending' and abs(ended['elapsed_seconds'] - 90) < .01 and ended['timing_review_required']
        focus_action('end', 120)
        reflection = '我发现安静的环境更容易帮助我开始学习'
        with patch('modeling.make_letter', side_effect=TimeoutError('simulated provider outage')):
            finished = focus_action('finish', 121, result='partial', reflection=reflection)
            assert finished['session']['status'] == 'ended'
            api('/api/jobs/run', {})
        focus_action('finish', 121, result='partial', reflection=reflection)
        event = finished['event']
        assert len(state()['events']) == 1 and state()['active_session'] is None
        api('/api/events/' + str(event['id']) + '/letter', {})
        api('/api/jobs/run', {})
        letter = next(item for item in state()['letters'] if item['source_id'] == event['id'])
        corrected = api('/api/events/' + str(event['id']), {'result': 'completed', 'elapsed_seconds': 75, 'reflection': '先写一个小结果更容易开始'}, 'PATCH')['event']
        assert corrected['revision'] == 2 and corrected['elapsed_seconds'] == 75
        assert next(item for item in state()['letters'] if item['id'] == letter['id'])['source_adjusted']
        api('/api/events/' + str(event['id']) + '/letter', {'rewrite': True})
        api('/api/jobs/run', {})
        api('/api/events/' + str(event['id']) + '/letter', {'rewrite': True})
        rewritten = [item for item in state()['letters'] if item['source_id'] == event['id']]
        assert len(rewritten) == 1 and rewritten[0]['id'] == letter['id'] and not rewritten[0]['source_adjusted']
        assert api('/api/events/' + str(event['id']), method='GET')['event']['letter_status'] == 'ready'
        assert api('/api/events?limit=1', method='GET')['events'][0]['id'] == event['id']

        private = api('/api/letters', {'title': '只留给自己', 'body': '我喜欢这份私密文字', 'allow_memory': False})['letter']
        future = (datetime.now(timezone.utc) + timedelta(days=1)).isoformat()
        sealed = api('/api/letters', {'title': '约定再见', 'body': '我喜欢每天安静读书', 'allow_memory': True, 'open_at': future})['letter']
        assert sealed['locked'] and sealed['body'] == ''
        assert not any(item['source_type'] == 'letter' and item['source_id'] in (private['id'], sealed['id']) for item in state()['memories'])
        # Move only this disposable letter across its opening boundary; no sleeping.
        sql('UPDATE letters SET open_at=? WHERE id=?', ((datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat(), sealed['id']))
        assert api('/api/notifications', method='GET')['notifications']
        api('/api/jobs/run', {})
        assert next(item for item in state()['letters'] if item['id'] == sealed['id'])['body']
        assert any(item['source_type'] == 'letter' and item['source_id'] == sealed['id'] for item in state()['memories'])

        material = api('/api/imports', {'title': '我的方法', 'content': '我发现清晨散步更容易帮助我整理思路', 'allow_memory': True})['material']
        api('/api/jobs/run', {})
        imported = next(item for item in state()['memories'] if any(ref['source_type'] == 'import' and ref['source_id'] == material['id'] for ref in item['evidence_ids']))
        api('/api/memories/' + str(imported['id']), {'action': 'confirm'}, 'PATCH')
        api('/api/imports/' + str(material['id']), {'allow_memory': False}, 'PATCH')
        assert not any(item['id'] == imported['id'] for item in state()['model']['context']['evidence'])
        assert not any(item['id'] == imported['id'] and item['status'] == 'confirmed' for item in state()['memories'])
        history = api('/api/profile/history', method='GET')['versions']
        assert history
        api('/api/profile/history/' + str(history[0]['id']), method='DELETE')
        assert not any(item['id'] == history[0]['id'] for item in api('/api/profile/history', method='GET')['versions'])
        api('/api/drafts/chat-draft', {'value': '第一份草稿', 'base_version': 0}, 'PUT')
        assert api('/api/drafts/chat-draft', {'value': '冲突草稿', 'base_version': 0}, 'PUT', 409)['conflict']['value'] == '第一份草稿'
        api('/api/drafts/letter-draft', {'value': '旧版本', 'base_version': 1}, 'PUT', 409)
        api('/api/feedback', {'event_id': event['id'], 'helpful': True, 'autonomy': 'understood'})
        assert api('/api/reviews/weekly', {})['review']['body']
        assert api('/api/analytics', method='GET')['feedback']
        assert client.get('/api/export').headers['Content-Disposition'].startswith('attachment')

        stranger = app.test_client()
        stranger.get('/login')
        with stranger.session_transaction() as saved:
            other_csrf = saved['csrf_token']
        stranger.post('/demo', data={'csrf_token': other_csrf})
        with stranger.session_transaction() as saved:
            other_csrf = saved['csrf_token']
        assert stranger.post(endpoint, json={'action': 'finish'}, headers={'X-CSRF-Token': other_csrf}).status_code == 404
        assert stranger.get('/api/events/' + str(event['id'])).status_code == 404
        assert stranger.get('/api/state').get_json()['events'] == []
        assert stranger.get('/api/state').get_json()['user']['id'] != uid
    print('PASS: V2 auth, consent, memory, durable jobs, offline focus, rewrite, goals, timed letters, import, history, drafts, weekly review, isolation; 1 flow')
    print('SMOKE OK')
