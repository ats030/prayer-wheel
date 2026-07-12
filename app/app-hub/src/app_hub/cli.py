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
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
