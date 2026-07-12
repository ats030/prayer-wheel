from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Iterable

from app_hub import config
from app_hub.backfill import (
    IMAGE_GALLERY,
    WRITING_DIR,
    ZENN_ARTICLES_DIR,
    backfill_all,
)
from app_hub.db import (
    connect,
    failure_rows,
    find_artifacts,
    init_db,
    recent_artifacts,
)


def rows_to_dicts(rows: Iterable) -> list[dict]:
    return [dict(row) for row in rows]


def print_json(value: object) -> None:
    print(json.dumps(value, ensure_ascii=False, indent=2, default=str))


def _short(value: object, width: int) -> str:
    text = "" if value is None else str(value)
    text = " ".join(text.split())
    if len(text) > width:
        return text[: max(width - 1, 1)] + "…"
    return text


def print_table(rows: list[dict], columns: list[tuple[str, str, int]]) -> None:
    if not rows:
        print("(no rows)")
        return
    headers = [label for _, label, _ in columns]
    widths = []
    for key, label, max_width in columns:
        width = max(len(label), *(len(_short(row.get(key), max_width)) for row in rows))
        widths.append(min(width, max_width))
    print("  ".join(label.ljust(widths[i]) for i, label in enumerate(headers)))
    print("  ".join("-" * width for width in widths))
    for row in rows:
        print(
            "  ".join(
                _short(row.get(key), widths[i]).ljust(widths[i])
                for i, (key, _, _) in enumerate(columns)
            )
        )


def _check(name: str, level: str, detail: object = "") -> dict:
    return {
        "name": name,
        "level": level,
        "ok": level == "ok",
        "detail": "" if detail is None else str(detail),
    }


def _writable_dir_check(name: str, path: Path) -> dict:
    try:
        path.mkdir(parents=True, exist_ok=True)
        probe = path / ".app-hub-doctor.tmp"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink(missing_ok=True)
    except Exception as exc:
        return _check(name, "error", f"{path}: not writable ({exc})")
    return _check(name, "ok", str(path))


def _target_dir_check(name: str, path: Path) -> dict:
    if path.exists() and path.is_dir():
        return _check(name, "ok", str(path))
    return _check(name, "warning", f"{path}: missing")


def _db_counts(con) -> dict[str, int]:
    return {
        table: int(con.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])
        for table in ("runs", "artifacts", "sources", "events")
    }


def doctor_report(
    *,
    db_path: Path | str | None = None,
    image_gallery: Path = IMAGE_GALLERY,
    writing_dir: Path = WRITING_DIR,
    zenn_articles_dir: Path = ZENN_ARTICLES_DIR,
) -> dict:
    checks: list[dict] = []
    checks.append(_writable_dir_check("data_dir", config.data_dir()))
    checks.append(_writable_dir_check("cache_dir", config.cache_dir()))

    db_target = Path(db_path).expanduser() if db_path else config.db_path()
    try:
        with connect(db_target) as con:
            init_db(con)
            quick_check = con.execute("PRAGMA quick_check").fetchone()[0]
            con.execute("CREATE TEMP TABLE app_hub_doctor_probe(x TEXT)")
            con.execute("INSERT INTO app_hub_doctor_probe(x) VALUES('ok')")
            fts = con.execute("SELECT value FROM meta WHERE key='fts5'").fetchone()
            counts = _db_counts(con)
        if quick_check == "ok":
            fts_value = fts["value"] if fts else "unknown"
            detail = f"{db_target}; fts5={fts_value}; counts={counts}"
            checks.append(_check("database", "ok", detail))
        else:
            checks.append(_check("database", "error", f"quick_check={quick_check}"))
    except Exception as exc:
        checks.append(_check("database", "error", f"{db_target}: {exc}"))

    try:
        from app_hub import hooks  # noqa: F401
    except Exception as exc:
        checks.append(_check("hooks_import", "error", str(exc)))
    else:
        checks.append(_check("hooks_import", "ok", "app_hub.hooks"))

    checks.extend(
        [
            _target_dir_check("image_gallery", Path(image_gallery).expanduser()),
            _target_dir_check("writing_dir", Path(writing_dir).expanduser()),
            _target_dir_check(
                "zenn_articles_dir", Path(zenn_articles_dir).expanduser()
            ),
        ]
    )

    error_log = config.error_log_path()
    log_rows = _hub_error_log_rows(5)
    if log_rows:
        checks.append(
            _check("error_log", "warning", f"{error_log}: {len(log_rows)} recent lines")
        )
    else:
        checks.append(_check("error_log", "ok", str(error_log)))

    levels = [check["level"] for check in checks]
    if "error" in levels:
        status = "error"
    elif "warning" in levels:
        status = "warning"
    else:
        status = "ok"
    return {
        "status": status,
        "checks": checks,
        "summary": {
            "errors": levels.count("error"),
            "warnings": levels.count("warning"),
            "ok": levels.count("ok"),
        },
    }


def cmd_init(args: argparse.Namespace) -> int:
    with connect(args.db) as con:
        init_db(con)
    print(f"initialized: {Path(args.db or config.db_path()).expanduser()}")
    return 0


def cmd_backfill(args: argparse.Namespace) -> int:
    result = backfill_all(
        image_gallery=Path(args.image_gallery).expanduser(),
        writing_dir=Path(args.writing_dir).expanduser(),
        zenn_articles_dir=Path(args.zenn_articles_dir).expanduser(),
        limit=args.limit,
        max_text_bytes=args.max_text_bytes,
        db_path=Path(args.db).expanduser() if args.db else None,
    )
    if args.json:
        print_json(result)
    else:
        for name, stats in result.items():
            if name == "finished_at":
                continue
            print(
                f"{name}: scanned={stats['scanned']} "
                f"new={stats['artifacts_created']} "
                f"seen={stats['artifacts_seen']} "
                f"sources_new={stats['sources_created']} "
                f"errors={len(stats['errors'])}"
            )
            for error in stats["errors"][:5]:
                print(f"  error: {error}")
    return 0


def cmd_recent(args: argparse.Namespace) -> int:
    with connect(args.db) as con:
        init_db(con)
        rows = rows_to_dicts(recent_artifacts(limit=args.limit, app=args.app, con=con))
    if args.json:
        print_json(rows)
    else:
        print_table(
            rows,
            [
                ("app", "APP", 16),
                ("kind", "KIND", 14),
                ("created_at", "CREATED", 20),
                ("title", "TITLE", 46),
                ("uri", "URI", 72),
            ],
        )
    return 0


def cmd_find(args: argparse.Namespace) -> int:
    with connect(args.db) as con:
        init_db(con)
        rows = rows_to_dicts(
            find_artifacts(args.query, limit=args.limit, app=args.app, con=con)
        )
    if args.json:
        print_json(rows)
    else:
        print_table(
            rows,
            [
                ("app", "APP", 16),
                ("kind", "KIND", 14),
                ("created_at", "CREATED", 20),
                ("title", "TITLE", 42),
                ("excerpt", "EXCERPT", 64),
                ("uri", "URI", 56),
            ],
        )
    return 0


def _hub_error_log_rows(limit: int) -> list[dict]:
    path = config.error_log_path()
    if not path.exists():
        return []
    lines = path.read_text(encoding="utf-8", errors="ignore").splitlines()
    return [
        {
            "type": "hub-log",
            "app": "app-hub",
            "ts": "",
            "level": "error",
            "message": line,
            "detail": str(path),
        }
        for line in lines[-limit:]
    ]


def cmd_failures(args: argparse.Namespace) -> int:
    with connect(args.db) as con:
        init_db(con)
        rows = rows_to_dicts(failure_rows(limit=args.limit, con=con))
    rows.extend(_hub_error_log_rows(args.limit))
    rows = rows[-args.limit :]
    if args.json:
        print_json(rows)
    else:
        print_table(
            rows,
            [
                ("type", "TYPE", 10),
                ("app", "APP", 16),
                ("ts", "TS", 20),
                ("level", "LEVEL", 10),
                ("message", "MESSAGE", 64),
                ("detail", "DETAIL", 56),
            ],
        )
    return 0


def cmd_doctor(args: argparse.Namespace) -> int:
    report = doctor_report(db_path=Path(args.db).expanduser() if args.db else None)
    if args.json:
        print_json(report)
    else:
        print(f"status: {report['status']}")
        print_table(
            report["checks"],
            [
                ("level", "LEVEL", 8),
                ("name", "CHECK", 24),
                ("detail", "DETAIL", 88),
            ],
        )
    return 1 if report["status"] == "error" else 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="app-hub")
    parser.add_argument("--db", default=None, help="SQLite DB path")
    sub = parser.add_subparsers(dest="command", required=True)

    p_init = sub.add_parser("init", help="initialize the SQLite schema")
    p_init.set_defaults(func=cmd_init)

    p_backfill = sub.add_parser("backfill", help="scan existing app artifacts")
    p_backfill.add_argument("--json", action="store_true", help="print JSON")
    p_backfill.add_argument("--limit", type=int, default=None, help="limit per source")
    p_backfill.add_argument(
        "--max-text-bytes",
        type=int,
        default=2_000_000,
        help="skip Markdown files larger than this many bytes",
    )
    p_backfill.add_argument("--image-gallery", default=str(IMAGE_GALLERY))
    p_backfill.add_argument("--writing-dir", default=str(WRITING_DIR))
    p_backfill.add_argument("--zenn-articles-dir", default=str(ZENN_ARTICLES_DIR))
    p_backfill.set_defaults(func=cmd_backfill)

    p_recent = sub.add_parser("recent", help="show recently recorded artifacts")
    p_recent.add_argument("--json", action="store_true", help="print JSON")
    p_recent.add_argument("-n", "--limit", type=int, default=20)
    p_recent.add_argument("--app", default=None)
    p_recent.set_defaults(func=cmd_recent)

    p_find = sub.add_parser("find", help="search artifact metadata")
    p_find.add_argument("query")
    p_find.add_argument("--json", action="store_true", help="print JSON")
    p_find.add_argument("-n", "--limit", type=int, default=20)
    p_find.add_argument("--app", default=None)
    p_find.set_defaults(func=cmd_find)

    p_failures = sub.add_parser("failures", help="show structured failures")
    p_failures.add_argument("--json", action="store_true", help="print JSON")
    p_failures.add_argument("-n", "--limit", type=int, default=20)
    p_failures.set_defaults(func=cmd_failures)

    p_doctor = sub.add_parser("doctor", help="run local app-hub diagnostics")
    p_doctor.add_argument("--json", action="store_true", help="print JSON")
    p_doctor.set_defaults(func=cmd_doctor)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
