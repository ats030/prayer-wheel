#!/usr/bin/env python3
"""maker_draft.json の抽出結果を jawiki 本文で検証する。

hallucination 防止として、maker 値が空でない全件について:
  - maker の文字列が本文に含まれるか
  - maker_evidence が本文（空白正規化後）に実在するか
を確認し、PASS / FAIL を表示する。FAIL 件がある場合は exit 1。

使い方:
  python3 scripts/validate_maker.py            # 詳細表示
  python3 scripts/validate_maker.py --quiet    # FAIL 件のみ表示
"""
import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
from fetch_tokusan import jawiki_extract  # noqa: E402

DRAFT = ROOT / "data" / "maker_draft.json"
CURATION = ROOT / "data" / "curation.json"


def normalize(s: str) -> str:
    return re.sub(r"\s+", "", s or "")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args()

    draft = json.loads(DRAFT.read_text(encoding="utf-8"))
    curation = json.loads(CURATION.read_text(encoding="utf-8"))
    include = curation["include"]

    checked = 0
    fails = []
    no_text = []
    for qid, d in draft.items():
        maker = (d.get("maker") or "").strip()
        if not maker:
            continue
        check_target = include.get(qid) or d
        wiki_title = check_target.get("wiki_title") or ""
        if not wiki_title:
            fails.append((d.get("label"), maker, d.get("maker_evidence", ""), "(wiki_title なし)"))
            continue
        text = jawiki_extract(wiki_title)
        if not text:
            no_text.append((d.get("label"), maker, d.get("maker_evidence", "")))
            continue
        checked += 1
        nt = normalize(text)
        nm = normalize(maker)
        ne = normalize(d.get("maker_evidence", ""))
        maker_ok = nm and nm in nt
        evidence_ok = bool(ne) and ne in nt
        status = "PASS" if (maker_ok or evidence_ok) else "FAIL"
        if status == "PASS" and not args.quiet:
            print(f"PASS  {d.get('label')}  maker={maker!r} maker_in_text={maker_ok} evidence_in_text={evidence_ok}")
        if status == "FAIL":
            fails.append((d.get("label"), maker, d.get("maker_evidence", ""), "(本文に不一致)"))
            if not args.quiet:
                print(f"FAIL  {d.get('label')}  maker={maker!r}  evidence={d.get('maker_evidence')!r}")

    if no_text:
        print(f"\n警告: 本文取得失敗 {len(no_text)} 件:")
        for label, maker, ev in no_text:
            print(f"  {label}  maker={maker!r}  evidence={ev!r}")

    print(f"\n検証 {checked} 件 / FAIL {len(fails)} 件 / 本文取得失敗 {len(no_text)} 件")
    if fails:
        print("FAIL 一覧 (maker を空にするべき候補):")
        for label, maker, ev, why in fails:
            print(f"  {label}  maker={maker!r}  evidence={ev!r}  {why}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
