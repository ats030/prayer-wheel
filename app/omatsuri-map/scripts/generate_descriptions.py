#!/usr/bin/env python3
"""
Generate descriptions for festivals using Wikidata API + Ollama AI
"""

import json
import os
import requests
import time
from pathlib import Path

# API endpoints
WIKIDATA_API = "https://www.wikidata.org/w/api.php"
WIKIPEDIA_API = "https://ja.wikipedia.org/w/api.php"
OLLAMA_API = "http://localhost:11434/api/generate"

def get_wikipedia_title(qid: str, cache: dict = None) -> str:
    """Get Japanese Wikipedia title from Wikidata QID"""
    if cache is None:
        cache = {}

    # Check cache first
    if qid in cache:
        return cache[qid]

    params = {
        "action": "wbgetentities",
        "ids": qid,
        "props": "sitelinks",
        "sitefilter": "jawiki",
        "format": "json"
    }

    try:
        response = requests.get(
            WIKIDATA_API,
            params=params,
            headers={"User-Agent": "omatsuri-map/1.0"},
            timeout=10,
        )
        response.raise_for_status()
        data = response.json()

        entities = data.get("entities", {})
        if qid not in entities:
            cache[qid] = None
            return None

        sitelinks = entities[qid].get("sitelinks", {})
        title = sitelinks["jawiki"].get("title") if "jawiki" in sitelinks else None
        cache[qid] = title
        return title

    except Exception as e:
        print(f"Error getting Wikipedia title for {qid}: {e}")
        cache[qid] = None
        return None

def get_wikidata_description(qid: str, cache: dict = None) -> str:
    """Get description from Wikidata"""
    if cache is None:
        cache = {}
    cache_key = qid + "_desc"

    # Check cache first
    if cache_key in cache:
        return cache[cache_key]

    params = {
        "action": "wbgetentities",
        "ids": qid,
        "props": "descriptions",
        "format": "json"
    }

    try:
        response = requests.get(
            WIKIDATA_API,
            params=params,
            headers={"User-Agent": "omatsuri-map/1.0"},
            timeout=10,
        )
        response.raise_for_status()
        data = response.json()

        entities = data.get("entities", {})
        if qid not in entities:
            cache[cache_key] = None
            return None

        descriptions = entities[qid].get("descriptions", {})
        desc = descriptions["ja"].get("value") if "ja" in descriptions else None
        cache[cache_key] = desc
        return desc

    except Exception as e:
        print(f"Error getting Wikidata description for {qid}: {e}")
        cache[cache_key] = None
        return None

def get_wikipedia_extract(title: str) -> str:
    """Fetch a longer plain-text extract from Japanese Wikipedia for grounding.

    Unlike the live site's 700-char intro-only extract, this pulls up to ~2000
    chars from the full article (not just the intro) so the AI prompt has more
    factual material to draw on.
    """
    if not title:
        return None

    params = {
        "action": "query",
        "format": "json",
        "formatversion": "2",
        "redirects": "1",
        "prop": "extracts",
        "explaintext": "1",
        "exchars": "2000",
        "titles": title,
    }

    try:
        response = requests.get(
            WIKIPEDIA_API,
            params=params,
            headers={"User-Agent": "omatsuri-map/1.0"},
            timeout=10,
        )
        response.raise_for_status()
        data = response.json()

        pages = data.get("query", {}).get("pages", [])
        if not pages or pages[0].get("missing"):
            return None
        extract = pages[0].get("extract", "").strip()
        return extract or None

    except Exception as e:
        print(f"Error getting Wikipedia extract for {title}: {e}")
        return None

def save_festivals(festivals: list, output_file: Path) -> None:
    """Write festivals to output_file atomically.

    Writes to a temp file in the same directory first, then os.replace()s it
    into place, so a crash mid-write never leaves output_file truncated or
    partially written (important since output_file may be a live data file
    the running server reads).
    """
    tmp_file = output_file.with_suffix(output_file.suffix + ".tmp")
    with open(tmp_file, "w", encoding="utf-8") as f:
        json.dump(festivals, f, ensure_ascii=False, indent=2)
    os.replace(tmp_file, output_file)

def fetch_all_wikidata_data(qids: list) -> dict:
    """Fetch all Wikipedia titles and Wikidata descriptions in batches"""
    cache = {}

    # Wikidata API allows up to 50 IDs per request
    batch_size = 50
    total = len(qids)

    for i in range(0, total, batch_size):
        batch = qids[i:i+batch_size]
        batch_str = "|".join([q for q in batch if q])

        params = {
            "action": "wbgetentities",
            "ids": batch_str,
            "props": "sitelinks|descriptions",
            "sitefilter": "jawiki",
            "format": "json"
        }

        try:
            response = requests.get(
                WIKIDATA_API,
                params=params,
                headers={"User-Agent": "omatsuri-map/1.0"},
                timeout=10,
            )
            response.raise_for_status()
            data = response.json()

            entities = data.get("entities", {})
            for qid in batch:
                if qid in entities:
                    # Get Wikipedia title
                    sitelinks = entities[qid].get("sitelinks", {})
                    if "jawiki" in sitelinks:
                        cache[qid] = sitelinks["jawiki"].get("title")
                    else:
                        cache[qid] = None

                    # Get Wikidata description
                    descriptions = entities[qid].get("descriptions", {})
                    if "ja" in descriptions:
                        cache[qid + "_desc"] = descriptions["ja"].get("value")
                    else:
                        cache[qid + "_desc"] = None
                else:
                    cache[qid] = None
                    cache[qid + "_desc"] = None

            print(f"  Processed {min(i+batch_size, total)}/{total} items")
            time.sleep(1)  # Rate limiting
        except Exception as e:
            print(f"Error fetching batch: {e}")

    return cache

def generate_description_with_ai(festival_name: str, location: str, wikidata_desc: str, wikipedia_extract: str) -> str:
    """Generate a richer description using Ollama AI, grounded in Wikidata/Wikipedia facts."""
    reference_lines = []
    if wikidata_desc:
        reference_lines.append(f"Wikidataの説明: {wikidata_desc}")
    if wikipedia_extract:
        reference_lines.append(f"Wikipediaの解説文:\n{wikipedia_extract}")
    has_reference = bool(reference_lines)
    reference_text = "\n\n".join(reference_lines) if reference_lines else "(参考情報なし)"

    if has_reference:
        prompt = (
            f"あなたは日本の祭りを紹介するライターです。「{festival_name}」({location})について、"
            "日本語で400〜600字程度の紹介文を書いてください。\n"
            "含めてほしい観点: 由来・歴史、行事の内容や見どころ、開催時期・規模などの特徴。\n"
            "書き方: 見出しや箇条書き、前置きの挨拶は使わず、自然な文章の段落として書いてください。\n"
            "重要な制約: 以下の参考情報に書かれていない具体的な事実(年号、人数、記録、規模の数値、具体的な行事名や開催時期など)を推測や創作で書き加えないでください。"
            "参考情報が乏しい場合は、無理に詳細を作らず、一般的な説明に留めてください。\n\n"
            f"【参考情報】\n{reference_text}"
        )
    else:
        # 参考情報が皆無の場合は、固有の事実を一切創作させず、
        # 名称・所在地から読み取れる一般的な性格づけのみで短く説明させる。
        prompt = (
            f"あなたは日本の神社・祭りを紹介するライターです。「{festival_name}」({location})について、"
            "日本語で150〜250字程度の短い紹介文を書いてください。\n"
            "この対象については具体的な由来・年号・開催時期・規模・行事名などの参考情報が一切ありません。"
            "そうした具体的な事実は絶対に創作しないでください。\n"
            "書いてよい内容: 名称・所在地から読み取れる一般的な性格(神社名や地名の由来となる神格・地域の特徴など、"
            "名称自体から明らかな範囲)や、日本の神社の祭礼・地域の祭りに一般的に見られる特徴についての、"
            "断定を避けた一般論のみ。\n"
            "書き方: 見出しや箇条書き、前置きの挨拶は使わず、自然な文章の段落として書いてください。\n"
            "「詳細は不明」「記録が限られている」といった断り書きを不自然に繰り返す必要はありませんが、"
            "存在しない具体的な事実(固有の年号、人数、行事名、伝承の内容など)を断定的に書かないでください。"
        )

    payload = {
        "model": "qwen3-coder-next:q4_K_M",
        "prompt": prompt,
        "stream": False
    }

    try:
        response = requests.post(
            OLLAMA_API,
            headers={"Content-Type": "application/json"},
            json=payload,
            timeout=60
        )
        response.raise_for_status()
        data = response.json()
        return data.get("response", "")

    except Exception as e:
        print(f"Error generating description for {festival_name}: {e}")
        return None

def main():
    # Paths
    script_dir = Path(__file__).parent
    input_file = script_dir.parent / "frontend/festivals.json"
    output_file = input_file

    # Load data
    print(f"Loading {input_file}...")
    with open(input_file, "r", encoding="utf-8") as f:
        festivals = json.load(f)

    print(f"Found {len(festivals)} festivals")

    # Pre-fetch all Wikipedia titles and Wikidata descriptions using batch API
    print("Pre-fetching Wikipedia titles and Wikidata descriptions...")
    all_qids = [f.get("qid") for f in festivals]
    cache = fetch_all_wikidata_data(all_qids)

    # Process each festival
    for idx, festival in enumerate(festivals):
        qid = festival.get("qid")
        label_ja = festival.get("label_ja", "Unknown")
        prefecture = festival.get("prefecture", "Unknown")

        # Skip if description already exists
        if festival.get("description"):
            print(f"[{idx+1}/{len(festivals)}] {label_ja}: Already has description")
            continue

        print(f"[{idx+1}/{len(festivals)}] Processing {label_ja} ({qid})...")

        # Get location
        location = prefecture

        # Get Wikipedia title from cache
        wikipedia_title = get_wikipedia_title(qid, cache)
        if wikipedia_title:
            location = f"{ prefecture }の「{ wikipedia_title }」"

        # Store wikipedia_title in festival object
        festival["wikipedia_title"] = wikipedia_title

        # Get Wikidata description from cache
        wikidata_desc = get_wikidata_description(qid, cache)

        # Fetch a longer Wikipedia extract for grounding (if an article exists)
        wikipedia_extract = get_wikipedia_extract(wikipedia_title)
        time.sleep(0.2)  # Be polite to the Wikipedia API

        # Generate AI description
        description = generate_description_with_ai(label_ja, location, wikidata_desc, wikipedia_extract)

        if description:
            festival["description"] = description
            print(f"  ✓ Generated ({len(description)} chars): {description[:50]}...")
        else:
            festival["description"] = ""
            print(f"  ✗ Failed to generate description")

        # Save periodically
        if (idx + 1) % 5 == 0:
            print("Saving progress...")
            save_festivals(festivals, output_file)

    # Final save
    print("\nSaving final result...")
    save_festivals(festivals, output_file)

    print(f"Done! Output saved to {output_file}")

if __name__ == "__main__":
    main()
