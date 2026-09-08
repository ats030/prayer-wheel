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
        response = requests.get(WIKIDATA_API, params=params, timeout=10)
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
        response = requests.get(WIKIDATA_API, params=params, timeout=10)
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
            response = requests.get(WIKIDATA_API, params=params, timeout=10)
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

def generate_description_with_ai(festival_name: str, location: str, wikidata_desc: str) -> str:
    """Generate description using Ollama AI"""
    if not wikidata_desc:
        prompt = f"{festival_name}は{location}で開催される祭りです。概要を3行で教えてください。"
    else:
        prompt = f"{festival_name}は{location}で開催される祭りです。WikiDataの情報によると、{wikidata_desc}です。概要を3行で教えてください。"

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
    data_dir = script_dir.parent / "data"
    input_file = data_dir / "festivals-with-date.json"
    output_file = data_dir / "festivals-with-descriptions.json"

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

        # Generate AI description
        description = generate_description_with_ai(label_ja, location, wikidata_desc)

        if description:
            festival["description"] = description
            print(f"  ✓ Generated: {description[:50]}...")
        else:
            festival["description"] = ""
            print(f"  ✗ Failed to generate description")

        # Save periodically
        if (idx + 1) % 10 == 0:
            print("Saving progress...")
            with open(output_file, "w", encoding="utf-8") as f:
                json.dump(festivals, f, ensure_ascii=False, indent=2)

    # Final save
    print("\nSaving final result...")
    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(festivals, f, ensure_ascii=False, indent=2)

    print(f"Done! Output saved to {output_file}")

if __name__ == "__main__":
    main()
