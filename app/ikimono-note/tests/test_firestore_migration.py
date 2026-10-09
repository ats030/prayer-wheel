import base64
import importlib.util
import json
from pathlib import Path
import sqlite3

import httpx
import pytest

APP=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('migration',APP/'cloudflare/migrate_firestore.py')
migration=importlib.util.module_from_spec(spec);spec.loader.exec_module(migration)
PROJECT='synthetic-project'


def doc(collection,identity,fields):
    return {'name':f'projects/{PROJECT}/databases/(default)/documents/{collection}/{identity}',
            'fields':{k:{'bytesValue' if k=='photo' else 'stringValue':v} for k,v in fields.items()}}


def fixtures():
    user=doc('users','owner',{'subject':'owner','email':'private@example.invalid',
        'created_at':'2025-01-01','last_seen_at':'2026-10-09','plan':'existing-plan'})
    share=doc('shares','synthetic_token_012345',{'owner':'owner','created_at':'2026-10-09',
        'payload':json.dumps({'candidates':[{'name':"quoted ' name"}]},ensure_ascii=False),
        'photo':base64.b64encode(b'private synthetic photo').decode(),'photo_type':'image/jpeg'})
    return {'users':[user],'shares':[share]}


def test_snapshot_preserves_identity_plan_token_payload_and_photo(tmp_path):
    source=fixtures();output=tmp_path/'private.db'
    summary=migration.snapshot(PROJECT,output,lambda collection:source[collection])
    assert summary['counts']=={'users':1,'shares':1} and summary['remote_writes']==0
    assert output.stat().st_mode&0o777==0o600
    with sqlite3.connect(output) as db:
        assert db.execute('SELECT subject,email,created_at,last_seen_at,plan FROM users').fetchone()==(
            'owner','private@example.invalid','2025-01-01','2026-10-09','existing-plan')
        assert db.execute('SELECT token,owner,payload,photo FROM shares').fetchone()==(
            'synthetic_token_012345','owner',source['shares'][0]['fields']['payload']['stringValue'],b'private synthetic photo')
    assert 'private@example.invalid' not in json.dumps(summary)
    with pytest.raises(FileExistsError):migration.snapshot(PROJECT,output,lambda _:[])


@pytest.mark.parametrize('bad',['duplicate','unknown','type','identity','photo','payload','origin'])
def test_invalid_sources_remove_partial_artifact(tmp_path,bad):
    source=fixtures()
    if bad=='duplicate':source['users']*=2
    if bad=='unknown':source['users'][0]['fields']['unknown']={'stringValue':'private'}
    if bad=='type':source['users'][0]['fields']['plan']={'integerValue':'1'}
    if bad=='identity':source['users'][0]['fields']['subject']={'stringValue':'other'}
    if bad=='photo':source['shares'][0]['fields']['photo']={'bytesValue':'not base64'}
    if bad=='payload':source['shares'][0]['fields']['payload']={'stringValue':'[]'}
    if bad=='origin':source['users'][0]['name']='projects/other/databases/(default)/documents/users/owner'
    output=tmp_path/'partial.db'
    with pytest.raises((ValueError,sqlite3.IntegrityError)):migration.snapshot(PROJECT,output,lambda c:source[c])
    assert not output.exists()


def test_paginated_read_is_get_only_and_repeated_token_stops():
    requests=[]
    def respond(request):
        requests.append(request)
        return httpx.Response(200,json={'documents':[],'nextPageToken':'same'})
    with httpx.Client(transport=httpx.MockTransport(respond)) as client:
        with pytest.raises(ValueError,match='pagination'):list(migration.documents(client,PROJECT,'users','2026-10-09T23:00:00Z'))
    assert len(requests)==2 and all(r.method=='GET' and r.url.host=='firestore.googleapis.com' for r in requests)
    assert all(r.url.params['readTime']=='2026-10-09T23:00:00Z' for r in requests)


@pytest.mark.parametrize('git_kind',['directory','file'])
def test_snapshot_rejects_git_worktree(tmp_path,git_kind):
    repo=tmp_path/'repo';repo.mkdir()
    if git_kind=='directory':(repo/'.git').mkdir()
    else:(repo/'.git').write_text('gitdir: /synthetic/worktree')
    output=repo/'nested/private.db'
    with pytest.raises(ValueError,match='Git worktrees'):
        migration.snapshot(PROJECT,output,lambda _:[])
    assert not output.parent.exists()


def test_empty_pages_have_independent_request_bound():
    requests=[]
    def respond(request):
        requests.append(request)
        return httpx.Response(200,json={'documents':[],'nextPageToken':str(len(requests))})
    with httpx.Client(transport=httpx.MockTransport(respond)) as client:
        with pytest.raises(ValueError,match='Page bound'):
            list(migration.documents(client,PROJECT,'users','2026-10-09T23:00:00Z'))
    assert len(requests)==500
