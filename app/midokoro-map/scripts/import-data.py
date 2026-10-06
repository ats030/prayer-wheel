#!/usr/bin/env python3
"""Import curated sibling snapshots while the unified server is stopped."""
import argparse, hashlib, json
from pathlib import Path
parser=argparse.ArgumentParser();parser.add_argument("--replace",action="store_true");args=parser.parse_args()
root=Path(__file__).resolve().parents[1]; plan=[]; manifest={}
for kind,db in {"omatsuri":"festivals.db","onsen":"onsen.db","shiseki":"shiseki.db","tokusan":"tokusan.db"}.items():
    source=root.parent/(kind+"-map")
    manifest[kind]={"source":source.name,"database":db,"files":{}}
    for path in [source/"frontend"/db, source/"data/summaries.json", source/"data/official_summaries.json"]:
        if not path.exists():
            if path.name==db: parser.error(str(path)+" is missing")
            continue
        target=root/"data"/kind/path.name
        if target.exists() and not args.replace: parser.error(str(target)+" exists; back up unified summaries before --replace")
        data=path.read_bytes();plan.append((target,data))
        manifest[kind]["files"][path.name]=hashlib.sha256(data).hexdigest()
# Validate every input and destination before writing any file.
for target,data in plan:
    target.parent.mkdir(parents=True,exist_ok=True); temporary=target.with_suffix(target.suffix+".tmp"); temporary.write_bytes(data); temporary.replace(target)
(root/"migration-manifest.json").write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+"\n")
print("Imported",len(plan),"snapshots")
