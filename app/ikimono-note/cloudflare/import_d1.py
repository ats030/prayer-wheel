"""Import a bounded snapshot into a new, unbound D1 candidate; never overwrite."""
import argparse
from contextlib import closing
import hashlib
import json
from pathlib import Path
import sqlite3
import tomllib
import uuid

import httpx

from migrate_firestore import HERE

ACCOUNT='559cfb7fb4d4ff05a7bbcfc75ec739a4'
NAMES={'ikimono-note-production-candidate','ikimono-note-migration-probe'}
COLUMNS={'users':('subject','email','created_at','last_seen_at','plan'),
         'shares':('token','owner','created_at','payload','photo','photo_type')}


def load_snapshot(path,expected_sha256):
    path=path.resolve(strict=True)
    if any((p/'.git').exists() for p in path.parents):raise ValueError('Private snapshot inside Git')
    if path.stat().st_mode&0o077:raise ValueError('Snapshot is not private')
    if path.stat().st_size>20*1024*1024:raise ValueError('Snapshot experiment too large')
    if any(Path(str(path)+suffix).exists() for suffix in ('-wal','-shm','-journal')):
        raise ValueError('Snapshot has SQLite sidecars; checkpoint first')
    content=path.read_bytes()
    if len(content)>20*1024*1024:raise ValueError('Snapshot experiment too large')
    digest=hashlib.sha256(content).hexdigest()
    if digest!=expected_sha256:raise ValueError('Snapshot hash mismatch')
    rows={}
    # Parse exactly the hashed bytes, not a second filesystem read or a WAL.
    with closing(sqlite3.connect(':memory:')) as db:
        db.deserialize(content)
        if db.execute('PRAGMA integrity_check').fetchone()!=('ok',):raise ValueError('Snapshot corrupt')
        for table,columns in COLUMNS.items():
            if tuple(r[1] for r in db.execute(f'PRAGMA table_info({table})'))!=columns:
                raise ValueError('Unexpected snapshot schema')
            rows[table]=db.execute(f"SELECT {','.join(columns)} FROM {table} ORDER BY {columns[0]} LIMIT 101").fetchall()
            if len(rows[table])>100:raise ValueError('Snapshot experiment row bound exceeded')
            for row in rows[table]:
                for column,value in zip(columns,row):
                    if column=='photo':
                        if not isinstance(value,bytes) or not 0<len(value)<=700*1024:raise ValueError('Photo bound exceeded')
                    elif not isinstance(value,str):raise ValueError('Unexpected value type')
                if sum(len(v) if isinstance(v,bytes) else len(v.encode()) for v in row)>1900000:
                    raise ValueError('D1 row bound exceeded')
    return rows


def statements(rows):
    schema=(HERE/'migrations/0001.sql').read_text()
    batch=[{'sql':s.strip()+';','params':[]} for s in schema.split(';') if s.strip()]
    for table,columns in COLUMNS.items():
        for row in rows[table]:
            params=list(row)
            placeholders=['?']*len(columns)
            if table=='shares':
                photo=params[4];params.pop(4);placeholders[4]="x''"
            batch.append({'sql':f"INSERT INTO {table} ({','.join(columns)}) VALUES ({','.join(placeholders)})",'params':params})
            if table=='shares':
                for offset in range(0,len(photo),40000):
                    batch.append({'sql':"UPDATE shares SET photo=CAST(photo||x'"+photo[offset:offset+40000].hex()+"' AS BLOB) WHERE token=?",'params':[row[0]]})
    if len(batch)>500 or len(json.dumps({'batch':batch}).encode())>20*1024*1024:
        raise ValueError('Import experiment request bound exceeded')
    return batch


class Remote:
    def __init__(self,client):
        self.client=client
        self.root=f'https://api.cloudflare.com/client/v4/accounts/{ACCOUNT}/d1/database'

    def call(self,method,suffix='',body=None):
        response=self.client.request(method,self.root+suffix,json=body)
        response.raise_for_status()
        data=response.json()
        if data.get('success') is not True:raise ValueError('D1 operation failed')
        return data['result']

    def query(self,database,batch):
        result=self.call('POST',f'/{database}/query',{'batch':batch})
        if len(result)!=len(batch) or any(r.get('success') is not True for r in result):
            raise ValueError('D1 query failed')
        return result


def verify(remote,database,rows):
    counts={};photo_bytes=0
    for table,columns in COLUMNS.items():
        count=remote.query(database,[{'sql':f'SELECT count(*) AS n FROM {table}','params':[]}])[0]['results'][0]['n']
        if count!=len(rows[table]):raise ValueError('D1 count mismatch')
        counts[table]=count
        for expected in rows[table]:
            select=','.join('hex(photo) AS photo' if c=='photo' else c for c in columns)
            result=remote.query(database,[{'sql':f'SELECT {select} FROM {table} WHERE {columns[0]}=?','params':[expected[0]]}])[0]['results']
            if len(result)!=1:raise ValueError('D1 missing identity')
            actual=tuple(bytes.fromhex(result[0][c]) if c=='photo' else result[0][c] for c in columns)
            if actual!=expected:raise ValueError('D1 value mismatch')
            if table=='shares':photo_bytes+=len(actual[4])
    return {'counts':counts,'shared_photo_bytes':photo_bytes,'row_values_verified':True}


def import_new(remote,name,rows,created):
    if name not in NAMES:raise ValueError('Unexpected destination name')
    batch=statements(rows)  # Validate before creating any resource.
    existing=remote.call('GET','?per_page=100')
    if len(existing)>=10:raise ValueError('Free database count bound exceeded')
    if any(d['name']==name for d in existing):raise ValueError('Destination already exists; refusing overwrite')
    result=remote.call('POST',body={'name':name,'primary_location_hint':'apac'})
    database=str(uuid.UUID(result['uuid']))
    created(database)  # Report only the resource ID, even if import/readback later fails.
    tables=remote.query(database,[{'sql':"SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' AND name NOT LIKE '_cf_%'",'params':[]}])[0]['results']
    if tables:raise ValueError('New destination is not empty')
    remote.query(database,batch)
    return {'database_name':name,'database_id':database,**verify(remote,database,rows),
            'public_worker_binding':False,'source_writes':0,'ready_for_public_cutover':False}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--snapshot',type=Path,required=True)
    parser.add_argument('--sha256',required=True)
    parser.add_argument('--name',choices=sorted(NAMES),required=True)
    args=parser.parse_args()
    try:
        rows=load_snapshot(args.snapshot,args.sha256)
        config=tomllib.loads((Path.home()/'.config/.wrangler/config/default.toml').read_text())
        with httpx.Client(headers={'Authorization':'Bearer '+config['oauth_token']},timeout=60,follow_redirects=False) as client:
            result=import_new(Remote(client),args.name,rows,lambda identifier:print(json.dumps({'created_database_id':identifier,'verified':False}),flush=True))
        print(json.dumps(result))
    except (ValueError,TypeError,KeyError,OSError,sqlite3.Error,httpx.HTTPError):
        print('FAIL: destination is not verified; no automatic retry/delete; private details withheld')
        return 2
    return 0


if __name__=='__main__':raise SystemExit(main())
