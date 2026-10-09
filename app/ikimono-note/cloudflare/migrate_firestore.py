"""Read-only Firestore snapshot in the existing D1 schema; no remote writes."""
import argparse
import base64
from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
import subprocess

import httpx

HERE=Path(__file__).resolve().parent
APP=HERE.parent
COLLECTIONS={'users':('subject','email','created_at','last_seen_at','plan'),
             'shares':('owner','created_at','payload','photo','photo_type')}


def convert(project,collection,document):
    prefix=f'projects/{project}/databases/(default)/documents/{collection}/'
    name=document.get('name','')
    if not isinstance(name,str) or not name.startswith(prefix):raise ValueError('Unexpected document origin')
    identity=name[len(prefix):]
    if not identity or '/' in identity:raise ValueError('Invalid document identifier')
    fields=document.get('fields')
    if not isinstance(fields,dict) or set(fields)!=set(COLLECTIONS[collection]):
        raise ValueError('Unexpected source fields; manual mapping required')
    row={}
    for key in COLLECTIONS[collection]:
        kind='bytesValue' if key=='photo' else 'stringValue'
        value=fields[key]
        if not isinstance(value,dict) or set(value)!={kind} or not isinstance(value[kind],str):
            raise ValueError('Unexpected source field type')
        row[key]=value[kind]
    if collection=='users':
        if row['subject']!=identity:raise ValueError('User identity mismatch')
    else:
        if not re.fullmatch(r'[A-Za-z0-9_-]{16,128}',identity):raise ValueError('Invalid shared token')
        if not row['owner'] or not isinstance(json.loads(row['payload']),dict):raise ValueError('Invalid share payload')
        row['photo']=base64.b64decode(row['photo'],validate=True)
        if not 0<len(row['photo'])<=700*1024 or row['photo_type'] not in {'image/jpeg','image/png','image/gif'}:
            raise ValueError('Invalid share photo')
        row={'token':identity,**row}
    return row


def documents(client,project,collection,read_time):
    url=f'https://firestore.googleapis.com/v1/projects/{project}/databases/(default)/documents/{collection}'
    token=None;seen=set();count=0;pages=0
    while True:
        pages+=1
        if pages>500:raise ValueError('Page bound exceeded')
        params={'pageSize':25,'readTime':read_time}
        if token:params['pageToken']=token
        response=client.get(url,params=params)
        response.raise_for_status()
        page=response.json()
        if not isinstance(page,dict) or not isinstance(page.get('documents',[]),list):raise ValueError('Invalid source page')
        for document in page.get('documents',[]):
            count+=1
            if count>10000:raise ValueError('Snapshot bound exceeded')
            yield document
        token=page.get('nextPageToken')
        if not token:break
        if not isinstance(token,str) or token in seen:raise ValueError('Invalid pagination')
        seen.add(token)


def snapshot(project,output,source,read_time=None):
    """Create a new private local artifact; preserve values and verify each row."""
    if not re.fullmatch(r'[a-z][a-z0-9-]{4,62}',project):raise ValueError('Invalid project')
    output=output.resolve()
    if any((parent/'.git').exists() for parent in output.parents):
        raise ValueError('Snapshot must stay outside Git worktrees')
    output.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
    fd=os.open(output,os.O_WRONLY|os.O_CREAT|os.O_EXCL|getattr(os,'O_NOFOLLOW',0),0o600)
    os.close(fd)
    db=None;completed=False
    try:
        db=sqlite3.connect(output)
        db.executescript((HERE/'migrations/0001.sql').read_text())
        counts={};photo_bytes=0
        for collection in COLLECTIONS:
            count=0
            for document in source(collection):
                row=convert(project,collection,document)
                keys=list(row)
                db.execute(f"INSERT INTO {collection} ({','.join(keys)}) VALUES ({','.join('?' for _ in keys)})",list(row.values()))
                primary='subject' if collection=='users' else 'token'
                actual=db.execute(f"SELECT {','.join(keys)} FROM {collection} WHERE {primary}=?",(row[primary],)).fetchone()
                if tuple(row.values())!=actual:raise ValueError('Snapshot verification failed')
                count+=1
                if collection=='shares':photo_bytes+=len(row['photo'])
            counts[collection]=count
        db.commit();db.close();db=None
        digest=hashlib.sha256()
        with output.open('rb') as stored:
            for chunk in iter(lambda:stored.read(65536),b''):digest.update(chunk)
        completed=True
        return {'source_project':project,'captured_at_utc':datetime.now(timezone.utc).isoformat(),
                'source_read_time':read_time,'consistent_read_requested':read_time is not None,
                'counts':counts,'shared_photo_bytes':photo_bytes,'snapshot_sha256':digest.hexdigest(),
                'row_values_verified':True,'remote_writes':0,
                'scope':'Private local snapshot only; no D1 import, Drive data or shared URL migration'}
    finally:
        if db is not None:db.close()
        if not completed:output.unlink(missing_ok=True)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--project',default='ikimono-note-12205')
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    try:
        # Keep access token and source documents out of stdout, logs and Git.
        token=subprocess.run([str(Path.home()/'google-cloud-sdk/bin/gcloud'),'auth','print-access-token'],
            capture_output=True,text=True,check=True,timeout=60).stdout.strip()
        if not token:raise ValueError('Credentials unavailable')
        read_time=(datetime.now(timezone.utc)-timedelta(seconds=5)).isoformat(timespec='microseconds').replace('+00:00','Z')
        with httpx.Client(headers={'Authorization':'Bearer '+token},timeout=30,follow_redirects=False) as client:
            summary=snapshot(args.project,args.output,lambda collection:documents(client,args.project,collection,read_time),read_time)
        print(json.dumps(summary,ensure_ascii=False))
    except (ValueError,TypeError,KeyError,AttributeError,OSError,sqlite3.Error,httpx.HTTPError,subprocess.SubprocessError):
        print('FAIL: read-only snapshot unavailable or source validation failed; private source details withheld')
        return 2
    return 0


if __name__=='__main__':raise SystemExit(main())
