# app-hub

Local metadata index for this PC's app artifacts.

Phase 1 is intentionally small:

- SQLite DB: `~/.local/share/app-hub/hub.sqlite`
- cache/error log: `~/.cache/app-hub/`
- source of truth remains each app's existing files/DBs
- backfill only covers `image-generator` and `writing`

Run:

```bash
~/app/app-hub/app-hub init
~/app/app-hub/app-hub backfill
~/app/app-hub/app-hub recent
~/app/app-hub/app-hub find DuckDB
~/app/app-hub/app-hub failures
```

Use `--json` on list commands for machine-readable output.
