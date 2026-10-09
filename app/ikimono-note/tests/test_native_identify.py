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
