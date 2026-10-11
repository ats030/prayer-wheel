#!/usr/bin/env python3
"""Import curated sibling snapshots while the unified server is stopped."""
import argparse, hashlib, json
from pathlib import Path
KINDS={"omatsuri":"festivals.db","onsen":"onsen.db","shiseki":"shiseki.db","tokusan":"tokusan.db"}
parser=argparse.ArgumentParser();parser.add_argument("--replace",action="store_true")
parser.add_argument("--kind",choices=KINDS,action="append",help="import only these kinds (repeatable)")
parser.add_argument("--database-only",action="store_true",help="replace only the database and keep the unified summaries")
args=parser.parse_args()
root=Path(__file__).resolve().parents[1]; plan=[]
manifest_path=root/"migration-manifest.json"
manifest=json.loads(manifest_path.read_text()) if manifest_path.exists() else {}
for kind,db in KINDS.items():
    if args.kind and kind not in args.kind: continue
    source=root.parent/(kind+"-map")
    files=manifest.get(kind,{}).get("files",{}) if args.database_only else {}
    manifest[kind]={"source":source.name,"database":db,"files":files}
    paths=[source/"frontend"/db]+([] if args.database_only else [source/"data/summaries.json", source/"data/official_summaries.json"])
    for path in paths:
        if not path.exists():
            if path.name==db: parser.error(str(path)+" is missing")
            continue
        target=root/"data"/kind/path.name
        # The database is regenerated from the sibling source; only summaries can hold unified-only work.
        if target.exists() and not args.replace and not args.database_only: parser.error(str(target)+" exists; back up unified summaries before --replace")
        data=path.read_bytes();plan.append((target,data))
        manifest[kind]["files"][path.name]=hashlib.sha256(data).hexdigest()
# Validate every input and destination before writing any file.
for target,data in plan:
    target.parent.mkdir(parents=True,exist_ok=True); temporary=target.with_suffix(target.suffix+".tmp"); temporary.write_bytes(data); temporary.replace(target)
manifest_path.write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+"\n")
print("Imported",len(plan),"snapshots")
