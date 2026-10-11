"""Shared writer for geo.db: each builder replaces only the tables it owns."""
import shutil
import sqlite3
from pathlib import Path


def replace_tables(path: Path, schema: str, tables: dict[str, list[tuple]], meta: dict[str, str]) -> None:
    """Drop and recreate `tables` from `schema`, upsert `meta`, and swap the file in atomically."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.unlink(missing_ok=True)
    if path.exists():
        shutil.copyfile(path, temporary)
    con = sqlite3.connect(temporary)
    for name in tables:
        con.execute(f"drop table if exists {name}")
    con.executescript("create table if not exists meta(key text primary key, value text not null);" + schema)
    for name, rows in tables.items():
        if rows:
            con.executemany(f"insert into {name} values ({','.join('?' * len(rows[0]))})", rows)
    con.executemany("insert or replace into meta values (?,?)", meta.items())
    con.commit()
    con.execute("vacuum")
    con.close()
    temporary.replace(path)
