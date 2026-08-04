# app-hub

Local metadata index for this PC's app artifacts.

Phase 1 is intentionally small:

- SQLite DB: `~/.local/share/app-hub/hub.sqlite`
- cache/error log: `~/.cache/app-hub/`
- source of truth remains each app's existing files/DBs
- backfill only covers `image-generator` and `writing`
- writing の取材メモは `kind=interview` の artifact として記録される
  (著者にしか答えられない質問への回答。本文にまだ入っていない一次情報を探す口)

Run:

```bash
~/app/app-hub/app-hub init
~/app/app-hub/app-hub backfill
~/app/app-hub/app-hub recent
~/app/app-hub/app-hub find DuckDB
~/app/app-hub/app-hub failures
~/app/app-hub/app-hub doctor
```

Use `--json` on list commands for machine-readable output.
