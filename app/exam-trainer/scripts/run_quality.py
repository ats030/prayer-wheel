"""Foreground initial diagnosis with a private backup and review artifacts."""
import argparse
import hashlib
import json
import os
import sqlite3
import sys
from datetime import datetime, UTC
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from exam_trainer import db, quality
from exam_trainer.config import settings


def fingerprint(conn):
    result = {}
    for table in ('exam','question','syllabus_node','material','review','card'):
        sha = hashlib.sha256()
        count = 0
        for row in conn.execute(f'SELECT * FROM {table} ORDER BY 1'):
            sha.update(json.dumps(tuple(row), ensure_ascii=False).encode())
            count += 1
        result[table] = {'rows':count,'sha256':sha.hexdigest()}
    return result


def private_write(path, value):
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    os.fchmod(fd, 0o600)
    with os.fdopen(fd, 'w', encoding='utf-8') as file:
        file.write(value)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--rules-only', action='store_true')
    parser.add_argument('--report', type=int, help='Export a completed run without rerunning')
    args = parser.parse_args()
    if args.report is None:
        quality.init()
        if db.connection().execute("SELECT 1 FROM quality_run WHERE status IN ('queued','running')").fetchone():
            parser.error('Another diagnosis is active; check the admin page')
        before = fingerprint(db.connection())
        backup = settings.data_dir / ('bank-before-quality-' + datetime.now(UTC).strftime('%Y%m%dT%H%M%S%f') + '.sqlite')
        fd = os.open(backup, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        os.close(fd)
        with sqlite3.connect(backup) as dest:
            db.connection().backup(dest)
        run = quality.enqueue(use_llm=not args.rules_only, start=False)
        with db.transaction() as conn:
            conn.execute('BEGIN IMMEDIATE')
            claimed = conn.execute("UPDATE quality_run SET status='running' WHERE id=? AND status='queued'",(run['id'],))
            if claimed.rowcount!=1:
                parser.error('Another worker already claimed this diagnosis')
        print(json.dumps({'id':run['id'],'total':run['total'],'backup':str(backup)}, ensure_ascii=False), flush=True)
        try:
            quality.execute(run['id'])
        except Exception:
            with db.transaction() as conn:
                conn.execute("UPDATE quality_run SET status='error',finished_at=?,error=? WHERE id=?",
                             (quality.now(),'CLI診断が失敗しました',run['id']))
            raise
        after = fingerprint(db.connection())
        print(json.dumps({'learning_tables_unchanged':before==after}, ensure_ascii=False), flush=True)
        if before!=after:
            raise RuntimeError('Learning tables changed during diagnosis; investigate concurrent writes')
    else:
        run = quality.get_run(args.report)
        if not run or run['status']!='done':
            parser.error('Run does not exist or is unfinished')
    run = quality.get_run(run['id'])
    prefix = settings.data_dir / f'quality-{run["id"]}'
    private_write(prefix.with_name(prefix.name+'-review.csv'), quality.export_csv(run['id']))
    private_write(prefix.with_name(prefix.name+'-report.json'), quality.dumps({
        'run':run,'human_metrics':quality.human_metrics(quality.decorated_items(run['id'])),
        'limitations':'人の確認なしでは精度未測定。本文不足・モデル失敗は判断不能。'}))
    print(json.dumps({'id':run['id'],'status':run['status'],'summary':run['summary'],
                      'csv':str(prefix)+'-review.csv'}, ensure_ascii=False), flush=True)
    db.close()


if __name__ == '__main__':
    main()
