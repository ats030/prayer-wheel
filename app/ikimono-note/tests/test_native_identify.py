import json
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import main


@pytest.fixture
def native(monkeypatch):
    for name in ('PUBLIC_MODE', 'BROWSER_PHOTOS', 'NATIVE_TRANSPORT'):
        monkeypatch.setattr(main, name, True)
    monkeypatch.setattr(main, 'TRIAL_PER_DAY', 0)
    monkeypatch.setattr(main, '_rate_limit', lambda *args: None)
    monkeypatch.setattr(main.auth, 'configured', lambda: True)
    monkeypatch.setattr(main.auth, 'read_session', lambda cookie: {'sub': 'synthetic'} if cookie == 'signed' else None)
    monkeypatch.setattr(main.config_store, 'load', lambda: {'api_keys': {}, 'models': {'local': ''}, 'local_llm': {}})
    calls = []
    async def callback(template, count, model, key):
        calls.append((template, count, model, key))
        return {'status': 200, 'data': {'candidates': [{'content': {'parts': [{'text': '{"category":"不明","summary":"観察","candidates":[]}'}]}}]}}
    async def scoped_app(scope, receive, send):
        if scope.get('path') == '/identify':
            scope['native_identify'] = callback
        await main.app(scope, receive, send)
    client = TestClient(scoped_app, base_url='http://localhost', cookies={'ikimono_session': 'signed'})
    fields = {'request_provider': 'gemini', 'request_model': main.config_store.MODELS['gemini'][0]['id'],
              'request_api_key': ' own-key ', 'client_photos': json.dumps([{'metadata': {'observed_date': '2026-10-09'},
                  'measured': {'width': 600, 'height': 450, 'pixels': 270000, 'brightness': 120, 'sharpness': 200, 'contrast': 30}}])}
    return client, fields, calls


def test_native_runs_existing_normalization_and_finish(native, monkeypatch):
    client, fields, calls = native
    finished = []
    def finish(result):
        finished.append(result.copy())
        return {**result, 'protected_species_checked': True}
    monkeypatch.setattr(main.pipeline, 'finish', finish)
    response = client.post('/identify', data=fields)
    assert response.status_code == 200
    assert response.json()['protected_species_checked']
    assert response.json()['photo_metadata']['observed_date'] == '2026-10-09'
    assert 'photo_notes' in response.json()
    assert finished[0]['provider'] == 'gemini'
    template, count, model, key = calls[0]
    assert count == 1 and model == fields['request_model'] and key == 'own-key'
    assert template == main.vision.provider_payload('gemini', model, [], observed_date='2026-10-09')


@pytest.mark.parametrize('status', [429, 503])
def test_taxonomy_failure_propagates_through_both_gemini_paths(native, monkeypatch, status):
    client, fields, calls = native
    monkeypatch.setattr(main, 'BROWSER_GEMINI', True)
    def unavailable(result):
        raise main.vision.TaxonomyUnavailable(status, 120)
    monkeypatch.setattr(main.pipeline, 'finish', unavailable)
    body = {'model': fields['request_model'], 'count': 1, 'client_photos': fields['client_photos'],
            'reply': '{"candidates":[{"content":{"parts":[{"text":"{\\"candidates\\":[]}"}]}}]}'}
    for response in [client.post('/identify', data=fields), client.post('/api/gemini/result', json=body),
                     client.post('/api/local/result', json={'text': '{"candidates":[]}'})]:
        assert response.status_code == status
        assert response.headers['Retry-After'] == '120'
        assert '分類サービス' in response.json()['detail']
        assert 'candidates' not in response.json()


@pytest.mark.parametrize('change,status', [
    ({'request_model': 'unlisted'}, 400), ({'request_api_key': ''}, 400),
    ({'request_provider': 'openai'}, 400), ({'use_plantnet': 'true'}, 400),
    ({'client_photos': '[]'}, 422), ({'client_photos': 'broken'}, 422),
])
def test_native_rejects_before_transferring(native, change, status):
    client, fields, calls = native
    response = client.post('/identify', data={**fields, **change})
    assert response.status_code == status
    assert not calls


def test_native_quality_gate_precedes_transfer(native):
    client, fields, calls = native
    reports = json.loads(fields['client_photos'])
    reports[0]['measured']['brightness'] = 0
    response = client.post('/identify', data={**fields, 'client_photos': json.dumps(reports)})
    assert response.status_code == 422 and not calls


def test_native_auth_and_disabled_gate(native, monkeypatch):
    client, fields, calls = native
    client.cookies.clear()
    assert client.post('/identify', data=fields, follow_redirects=False).status_code == 303
    assert not calls
    client.cookies.set('ikimono_session', 'signed')
    monkeypatch.setattr(main, 'NATIVE_TRANSPORT', False)
    assert client.post('/identify', data=fields).status_code == 400
    assert client.post('/api/provider/template', json={'model': fields['request_model'], 'count': 1,
        'client_photos': fields['client_photos']}).status_code == 404
    assert not calls


def test_template_preserves_context_and_checks_model_and_reports(native):
    client, fields, calls = native
    body = {'model': fields['request_model'], 'count': 1, 'client_photos': fields['client_photos']}
    response = client.post('/api/provider/template', json=body)
    assert response.status_code == 200
    assert response.json() == main.vision.provider_payload('gemini', fields['request_model'], [], observed_date='2026-10-09')
    assert client.post('/api/provider/template', json={**body, 'model': 'unlisted'}).status_code == 400
    assert client.post('/api/provider/template', json={**body, 'client_photos': 'broken'}).status_code == 422
    assert not calls


def test_malformed_provider_structure_returns_user_error(native, monkeypatch):
    client, fields, calls = native
    original = main.vision._gemini_output_text
    monkeypatch.setattr(main.vision, '_gemini_output_text', lambda data: original({'candidates': [{'content': 'invalid'}]}))
    response = client.post('/identify', data=fields)
    assert response.status_code == 422
    assert 'Gemini' in response.json()['detail']
    assert len(calls) == 1


def test_browser_gemini_preserves_authoritative_template_result_and_metadata(native, monkeypatch):
    client, fields, calls = native
    monkeypatch.setattr(main, 'BROWSER_GEMINI', True)
    body = {'model': fields['request_model'], 'count': 1, 'client_photos': fields['client_photos']}
    template = client.post('/api/gemini/prepare', json=body)
    assert template.status_code == 200
    assert template.json() == main.vision.provider_payload('gemini', body['model'], [], observed_date='2026-10-09')
    assert not calls
    reply = {'candidates': [{'content': {'parts': [{'text': '{"category":"不明","summary":"観察","candidates":[]}'}]}}]}
    response = client.post('/api/gemini/result', json={**body, 'reply': json.dumps(reply)})
    reference = client.post('/identify', data=fields)
    assert response.status_code == reference.status_code == 200
    assert response.json() == reference.json()
    assert response.json()['provider'] == 'gemini'
    assert response.json()['strict_mode']
    assert response.json()['photo_metadata']['observed_date'] == '2026-10-09'
    assert response.json()['image_saved'] is False


def test_browser_gemini_auth_flag_quality_model_and_result_bounds(native, monkeypatch):
    client, fields, calls = native
    body = {'model': fields['request_model'], 'count': 1, 'client_photos': fields['client_photos']}
    result_body = {**body, 'reply': '{}'}
    for path, payload in [('/api/gemini/prepare', body), ('/api/gemini/result', result_body)]:
        assert client.post(path, json=payload).status_code == 404
    monkeypatch.setattr(main, 'BROWSER_GEMINI', True)
    client.cookies.clear()
    for path, payload in [('/api/gemini/prepare', body), ('/api/gemini/result', result_body)]:
        assert client.post(path, json=payload, follow_redirects=False).status_code == 401
    client.cookies.set('ikimono_session', 'signed')
    reports = json.loads(fields['client_photos']); reports[0]['measured']['brightness'] = 0
    for path, payload in [('/api/gemini/prepare', body), ('/api/gemini/result', result_body)]:
        assert client.post(path, json={**payload, 'model': 'unlisted'}).status_code == 400
        assert client.post(path, json={**payload, 'count': 3}).status_code == 422
        assert client.post(path, json={**payload, 'client_photos': json.dumps(reports)}).status_code == 422
    for reply in ['broken', '[]', json.dumps({'candidates': [{'finishReason': 'MAX_TOKENS'}]}),
                  json.dumps({'candidates': [{'content': 'bad'}]})]:
        assert client.post('/api/gemini/result', json={**body, 'reply': reply}).status_code == 422
    assert client.post('/api/gemini/result', json={**body, 'reply': 'x' * (2 * 1024 * 1024 + 1)}).status_code == 422
    assert not calls


def test_browser_gemini_enforces_identify_rate_before_provider_work(native, monkeypatch):
    client, fields, calls = native
    monkeypatch.setattr(main, 'BROWSER_GEMINI', True)
    def limit(request, scope, count):
        assert scope == 'identify' and count == 6
        raise main.HTTPException(429, '上限')
    monkeypatch.setattr(main, '_rate_limit', limit)
    assert client.post('/api/gemini/prepare', json={'model': fields['request_model'], 'count': 1,
        'client_photos': fields['client_photos']}).status_code == 429
    assert not calls
