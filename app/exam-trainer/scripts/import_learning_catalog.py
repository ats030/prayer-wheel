#!/usr/bin/env python3
"""Preview missing courses; --apply backs up the bank and imports additively."""

from contextlib import closing
import argparse
import datetime as dt
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from exam_trainer import db, learning_catalog
from exam_trainer.config import settings


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args()
    # No default request or startup hook writes learner data. Preview is read-only.
    with closing(sqlite3.connect(settings.db_path.resolve().as_uri() + '?mode=ro', uri=True)) as source:
        source.row_factory = sqlite3.Row
        courses = learning_catalog.prepare_missing([dict(r) for r in source.execute('SELECT name,slug FROM exam')])
        for course in courses:
            print(f"追加予定: {course['name']} / {len(course['questions'])}問")
        if not courses:
            print('すべての教材が登録済みです。変更はありません。')
            return
        if not args.apply:
            print('確認のみ。反映には --apply を指定してください。')
            return
        stamp = dt.datetime.now(dt.UTC).strftime('%Y%m%dT%H%M%S%fZ')
        backup = settings.data_dir / f'bank-before-catalog-{stamp}.sqlite'
        backup.touch(mode=0o600, exist_ok=False)
        with closing(sqlite3.connect(backup)) as target:
            source.backup(target)
        print(f'バックアップ: {backup}')
    try:
        for item in learning_catalog.import_missing():
            print(f"追加完了: {item['name']} / exam_id={item['exam_id']} / {item['questions']}問")
    finally:
        db.close()


if __name__ == '__main__':
    main()
