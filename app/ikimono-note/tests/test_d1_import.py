import hashlib
import importlib.util
from pathlib import Path
import sqlite3
import sys

import pytest

HERE=Path(__file__).resolve().parents[1]/'cloudflare'
sys.path.insert(0,str(HERE))
spec=importlib.util.spec_from_file_location('d1_import',HERE/'import_d1.py')
module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)


def rows():
    return {'users':[('owner',"quote'@example.invalid",'old','recent','existing-plan')],
            'shares':[('synthetic_token_012345','owner','old','{"note":"引用と日本語"}',bytes(range(256))*2800,'image/jpeg')]}


class Fake:
    def __init__(self,existing=False):
        self.db=sqlite3.connect(':memory:');self.existing=existing;self.created=False

    def call(self,method,suffix='',body=None):
        if method=='GET':return [{'name':'ikimono-note-production-candidate'}] if self.existing else []
        assert method=='POST';self.created=True
        return {'uuid':'11111111-1111-4111-8111-111111111111'}

    def query(self,database,batch):
        result=[]
        with self.db:
            for statement in batch:
                assert len(statement['sql'].encode())<100000
                cursor=self.db.execute(statement['sql'],statement['params'])
                data=[dict(zip([c[0] for c in cursor.description],r)) for r in cursor] if cursor.description else []
                result.append({'success':True,'results':data})
        return result


def test_new_import_preserves_every_column_and_700k_binary():
    remote=Fake();created=[]
    result=module.import_new(remote,'ikimono-note-production-candidate',rows(),created.append)
    assert created==[result['database_id']]
    assert result['counts']=={'users':1,'shares':1}
    assert result['shared_photo_bytes']==700*1024 and result['row_values_verified']
    assert not result['ready_for_public_cutover'] and not result['public_worker_binding']


def test_existing_destination_refuses_any_write():
    remote=Fake(existing=True)
    with pytest.raises(ValueError,match='already exists'):
        module.import_new(remote,'ikimono-note-production-candidate',rows(),lambda _:None)
    assert not remote.created


def test_readback_detects_modified_owner_and_extra_row():
    remote=Fake();source=rows()
    module.import_new(remote,'ikimono-note-production-candidate',source,lambda _:None)
    remote.db.execute("UPDATE shares SET owner='other'")
    with pytest.raises(ValueError,match='value mismatch'):module.verify(remote,'unused',source)
    remote.db.execute("INSERT INTO users VALUES ('extra','e','c','l','free')")
    with pytest.raises(ValueError,match='count mismatch'):module.verify(remote,'unused',source)


def test_snapshot_hash_privacy_and_row_bound(tmp_path):
    path=tmp_path/'snapshot.db'
    with sqlite3.connect(path) as db:
        db.executescript((HERE/'migrations/0001.sql').read_text())
    path.chmod(0o600)
    digest=hashlib.sha256(path.read_bytes()).hexdigest()
    assert module.load_snapshot(path,digest)=={'users':[],'shares':[]}
    with pytest.raises(ValueError,match='hash'):module.load_snapshot(path,'0'*64)
    path.chmod(0o644)
    with pytest.raises(ValueError,match='private'):module.load_snapshot(path,digest)
    path.chmod(0o600)
    with sqlite3.connect(path) as db:
        db.executemany('INSERT INTO users VALUES (?,?,?,?,?)',[(str(i),'e','c','l','free') for i in range(101)])
    with pytest.raises(ValueError,match='row bound'):
        module.load_snapshot(path,hashlib.sha256(path.read_bytes()).hexdigest())


def test_wal_rows_are_not_covered_by_main_file_hash(tmp_path):
    path=tmp_path/'snapshot.db'
    with sqlite3.connect(path) as db:
        db.executescript((HERE/'migrations/0001.sql').read_text())
    path.chmod(0o600)
    db=sqlite3.connect(path)
    try:
        db.execute('PRAGMA journal_mode=WAL')
        db.execute('PRAGMA wal_checkpoint(TRUNCATE)')
        digest=hashlib.sha256(path.read_bytes()).hexdigest()
        db.execute("INSERT INTO users VALUES ('wal-only','e','c','l','free')")
        db.commit()
        assert hashlib.sha256(path.read_bytes()).hexdigest()==digest
        with pytest.raises(ValueError,match='sidecars'):module.load_snapshot(path,digest)
    finally:db.close()
