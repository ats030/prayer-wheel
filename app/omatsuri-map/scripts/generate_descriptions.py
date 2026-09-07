#!/usr/bin/env python3
"""
Generate descriptions for festivals using Wikidata API + Ollama AI
"""

import json
import os
import requests
from pathlib import Path

# API endpoints
WIKIDATA_API = "https://www.wikidata.org/w/api.php"
OLLAMA_API = "http://localhost:11434/api/generate"

def get_wikipedia_title(qid: str) -> str:
    """Get Japanese Wikipedia title from Wikidata QID"""
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
            return None
            
        sitelinks = entities[qid].get("sitelinks", {})
        if "jawiki" in sitelinks:
            return sitelinks["jawiki"].get("title")
        return None
        
    except Exception as e:
        print(f"Error getting Wikipedia title for {qid}: {e}")
        return None

def get_wikidata_description(qid: str) -> str:
    """Get description from Wikidata"""
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
            return None
            
        descriptions = entities[qid].get("descriptions", {})
        if "ja" in descriptions:
            return descriptions["ja"].get("value")
        return None
        
    except Exception as e:
        print(f"Error getting Wikidata description for {qid}: {e}")
        return None

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
        
        # Get Wikipedia title
        wikipedia_title = get_wikipedia_title(qid)
        if wikipedia_title:
            location = f"{ prefecture }の「{ wikipedia_title }」"
        
        # Get Wikidata description
        wikidata_desc = get_wikidata_description(qid)
        
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
