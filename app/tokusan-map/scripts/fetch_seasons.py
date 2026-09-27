#!/usr/bin/env python3
"""curation の include 対象について、jawiki + LLM で「旬の季節」を抽出し、
人手キュレーション用のだraftを data/seasons_draft.json に記録する。

抽出結果は data/seasons_cache.json にキャッシュし、既存の品目は再抽出しない。

使い方:
  python3 scripts/fetch_seasons.py            # seasons 未抽出分のみ
  python3 scripts/fetch_seasons.py --force    # 全件再抽出
"""
import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
from fetch_tokusan import (  # noqa: E402
    HEADERS,
    MODEL,
    OLLAMA,
    jawiki_extract,
    make_key,
)
import requests  # noqa: E402

CURATION = ROOT / "data" / "curation.json"
DRAFT = ROOT / "data" / "seasons_draft.json"
CACHE = ROOT / "data" / "seasons_cache.json"
ALLOWED = ["春", "夏", "秋", "冬"]

PROMPT = """あなたは日本の食文化の編集者です。
下の「{label}」の記事本文を読んで、この品物を味わう旬の季節を判断してください。

判定基準:
- 「旬」「出回る時期」「食べ頃」「産出時期」「採期」「旬の食材」などの記述を優先する
- 選択できる季節は「春」「夏」「秋」「冬」のみ。複数選択可
- 時期の根拠となる具体的な記述が見つからない場合は空配列 [] とする
- 「通年」「年中」のみで特定の季節の記述がない場合は空配列 [] とする
- 日本語の回答で、JSONのみを出力すること (説明や改行は不要)

{{"seasons": ["秋"], "seasons_evidence": "記事文中の根拠となった30文字以内の引用"}}

品目名: {label}
記事本文:
{text}
"""


def load_seasons_cache():
    if CACHE.exists():
        try:
            return json.loads(CACHE.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return {}
    return {}


def save_seasons_cache(cache):
    CACHE.parent.mkdir(parents=True, exist_ok=True)
    CACHE.write_text(json.dumps(cache, ensure_ascii=False, indent=1), encoding="utf-8")


def ask_seasons(label, text):
    text = text.strip()
    if len(text) > 4000:
        text = "".join(list(text)[:4000])
    payload = {
        "model": MODEL,
        "stream": False,
        "think": False,
        "temperature": 0,
        "messages": [{"role": "user", "content": PROMPT.replace("{label}", label).replace("{text}", text)}],
    }
    last_err = None
    for attempt in range(5):
        try:
            resp = requests.post(OLLAMA, json=payload, timeout=120, headers=HEADERS)
            resp.raise_for_status()
            content = resp.json()["message"]["content"].strip()
            start = content.find("{")
            end = content.rfind("}")
            if start == -1 or end == -1:
                raise ValueError(f"no JSON in LLM reply: {content[:200]}")
            obj = json.loads(content[start:end + 1])
            raw = obj.get("seasons", []) or []
            if isinstance(raw, str):
                raw = [raw]
            seasons = [s for s in ALLOWED if s in raw]
            evidence = " ".join(str(obj.get("seasons_evidence") or "").split())[:160]
            return {"seasons": seasons, "seasons_evidence": evidence}
        except (requests.RequestException, ValueError, json.JSONDecodeError) as exc:
            last_err = exc
            time.sleep(1 + attempt)
    raise RuntimeError(f"LLM failed after retries: {last_err}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()

    curation = json.loads(CURATION.read_text(encoding="utf-8"))
    include = curation["include"]
    cache = load_seasons_cache()
    draft = {}

    processed = 0
    for qid, entry in include.items():
        label = entry.get("label") or entry.get("label_ja") or ""
        wiki_title = entry.get("wiki_title") or ""
        category = entry.get("category", "")
        craft = category in {"ta", "or", "ri"}

        text = ""
        if not craft:
            text = jawiki_extract(wiki_title) if wiki_title else ""
        key = make_key(qid, label, text)

        if key in cache and not args.force:
            result = cache[key]
            source = "cache"
        elif craft:
            result = {"seasons": [], "seasons_evidence": ""}
            source = "craft"
        elif not text:
            result = {"seasons": [], "seasons_evidence": ""}
            source = "no_text"
        else:
            result = ask_seasons(label, text)
            cache[key] = result
            save_seasons_cache(cache)
            source = "llm"

        draft[qid] = {
            "label": label,
            "category": category,
            "seasons": result["seasons"],
            "seasons_evidence": result.get("seasons_evidence", ""),
            "source": source,
        }
        if source == "llm":
            processed += 1
        print(f"[{qid}] {label!r} ({category}) -> {result['seasons']}  [{source}]")

    DRAFT.write_text(json.dumps(draft, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\n完了: LLM抽出 {processed} 件 / draft 合計 {len(draft)} 件")
    print(f"draft: {DRAFT}")


if __name__ == "__main__":
    main()
