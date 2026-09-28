#!/usr/bin/env python3
"""curation の include 対象について、jawiki + LLM で「生産者・ブランド・製造元」を抽出し、
人手キュレーション用の draft を data/maker_draft.json に記録する。

抽出結果は data/maker_cache.json にキャッシュし、既存の品目は再抽出しない。

使い方:
  python3 scripts/fetch_maker.py            # maker 未抽出分のみ
  python3 scripts/fetch_maker.py --force    # 全件再抽出
"""
import argparse
import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
from fetch_tokusan import (  # noqa: E402
    HEADERS,
    OLLAMA,
    jawiki_extract,
    make_key,
)

# 抽出には軽量モデルを使う（12b と併用だと RAM 不足で 503 になるため）。
# トークン削減のため e4b、必要なら env で e2b / 12b に切替可能。
MODEL = os.environ.get("MAKER_MODEL", "gemma4:e4b")
import requests  # noqa: E402

CURATION = ROOT / "data" / "curation.json"
DRAFT = ROOT / "data" / "maker_draft.json"
CACHE = ROOT / "data" / "maker_cache.json"

PROMPT = """あなたは日本の食文化・工芸の編集者です。
下の「{label}」の記事本文を読んで、この品物を製造・生産・販売している代表的な生産者・ブランド・店名を1つだけ判断してください。

判定基準:
- 記事文中に具体的に名前が記載されているもののみ採用する
- 一般的な品名・業界団体・自治体・産地のみでは「無し」とする（例: 「高知県」「宮崎県農協」など組織名が品目の製造元として具体的に明記されていない場合）
- 企業名・工芸品の場合は窯元・工房名・ブランド名が代表的なものを優先
- 根拠となる名前が1つも明確に見つからない場合は空文字 "" とする
- 日本語の回答で、JSONのみを出力すること (説明や改行は不要)

{{"maker": "代表的生产者・ブランド・店名、または空文字", "maker_evidence": "記事文中の根拠となった30文字以内の引用"}}

品目名: {label}
記事本文:
{text}
"""


def load_maker_cache():
    if CACHE.exists():
        try:
            return json.loads(CACHE.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return {}
    return {}


def save_maker_cache(cache):
    CACHE.parent.mkdir(parents=True, exist_ok=True)
    CACHE.write_text(json.dumps(cache, ensure_ascii=False, indent=1), encoding="utf-8")


def ask_maker(label, text):
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
    for attempt in range(8):
        try:
            resp = requests.post(OLLAMA, json=payload, timeout=120, headers=HEADERS)
            resp.raise_for_status()
            content = resp.json()["message"]["content"].strip()
            start = content.find("{")
            end = content.rfind("}")
            if start == -1 or end == -1:
                raise ValueError(f"no JSON in LLM reply: {content[:200]}")
            obj = json.loads(content[start:end + 1])
            maker = " ".join(str(obj.get("maker") or "").split())
            evidence = " ".join(str(obj.get("maker_evidence") or "").split())[:160]
            return {"maker": maker, "maker_evidence": evidence}
        except (requests.RequestException, ValueError, json.JSONDecodeError) as exc:
            last_err = exc
            status = getattr(getattr(exc, "response", None), "status_code", None)
            wait = (8 * (attempt + 1)) if status == 503 else (1 + attempt * 2)
            time.sleep(wait)
    raise RuntimeError(f"LLM failed after retries: {last_err}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()

    curation = json.loads(CURATION.read_text(encoding="utf-8"))
    include = curation["include"]
    cache = load_maker_cache()
    draft = {}

    processed = 0
    for qid, entry in include.items():
        label = entry.get("label") or entry.get("label_ja") or ""
        wiki_title = entry.get("wiki_title") or ""

        text = ""
        if wiki_title:
            text = jawiki_extract(wiki_title)
        key = make_key(qid, label, text)

        if key in cache and not args.force:
            result = cache[key]
            source = "cache"
        elif not text:
            result = {"maker": "", "maker_evidence": ""}
            source = "no_text"
        else:
            result = ask_maker(label, text)
            cache[key] = result
            save_maker_cache(cache)
            source = "llm"

        draft[qid] = {
            "label": label,
            "category": entry.get("category", ""),
            "maker": result["maker"],
            "maker_evidence": result.get("maker_evidence", ""),
            "source": source,
        }
        if source == "llm":
            processed += 1
        print(f"[{qid}] {label!r} -> {result['maker']!r}  [{source}]")

    DRAFT.write_text(json.dumps(draft, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\n完了: LLM抽出 {processed} 件 / draft 合計 {len(draft)} 件")
    print(f"draft: {DRAFT}")


if __name__ == "__main__":
    main()
