#!/usr/bin/env python3
"""WikidataのP3259を使って文化庁文化財データを取得し、既存祭りデータと統合"""

import requests
import json
import time
import re
from pathlib import Path

OUTPUT_DIR = Path("/home/ats030/app/omatsuri-map/data")

def fetch_wikidata_p3259_url(qid: str) -> str | None:
    """WikidataからP3259の証拠URLを取得"""
    url = "https://www.wikidata.org/w/api.php"
    headers = {"User-Agent": "OmatsuriMap/1.0", "Accept": "application/json"}
    params = {"action": "wbgetclaims", "entity": qid, "property": "P3259", "format": "json"}
    
    try:
        response = requests.get(url, params=params, headers=headers, timeout=10)
        response.raise_for_status()
        data = response.json()
        
        if "claims" in data and "P3259" in data["claims"]:
            for claim in data["claims"]["P3259"]:
                if "references" in claim and claim["references"]:
                    for ref in claim["references"]:
                        if "P854" in ref["snaks"]:
                            ref_url = ref["snaks"]["P854"][0]["datavalue"]["value"]
                            if "kunishitei.bunka.go.jp" in ref_url:
                                return ref_url
    except Exception as e:
        print(f"Wikidata P3259 Error ({qid}): {e}")
    
    return None

def fetch_cultural_data(wikidata_ref_url: str) -> dict:
    """Wikidataの証拠URLから文化庁データを抽出"""
    headers = {"User-Agent": "OmatsuriMap/1.0"}
    
    response = requests.get(wikidata_ref_url, headers=headers, timeout=10)
    response.raise_for_status()
    html = response.text
    
    cultural_data = {"name": "", "prefecture": "", "date": "", "url": wikidata_ref_url}
    
    match = re.search(r'<span id="title1"[^>]*>([^<]+)</span>', html)
    if match:
        cultural_data["name"] = match.group(1).strip()
    
    match = re.search(r'[^>]*県\s*</td>', html)
    if match:
        cultural_data["prefecture"] = match.group(0).replace('</td>', '').strip()
    
    cultural_data["date"] = ""
    
    return cultural_data

def main():
    """メイン処理"""
    print("文化庁文化財データ取得と既存祭りデータ統合")
    print("=" * 60)
    
    with open(OUTPUT_DIR / "festivals.json", "r", encoding="utf-8") as f:
        festivals = json.load(f)
    
    print(f"既存祭りデータ: {len(festivals)} 件")
    
    cultural_relaw_results = []
    
    for festival in festivals[:20]:
        qid = festival.get("qid")
        label_ja = festival.get("label_ja", "")
        
        if not qid:
            continue
        
        print(f"\n処理中: {label_ja} ({qid})")
        
        ref_url = fetch_wikidata_p3259_url(qid)
        
        if ref_url:
            print(f"  証拠URL: {ref_url}")
            
            cultural_data = fetch_cultural_data(ref_url)
            
            if cultural_data and cultural_data["name"]:
                result = {
                    "qid": qid,
                    "label_ja": label_ja,
                    "label_en": festival.get("label_en", ""),
                    "latitude": festival.get("latitude", 0),
                    "longitude": festival.get("longitude", 0),
                    "prefecture": cultural_data["prefecture"] or festival.get("prefecture", ""),
                    "description": festival.get("description", ""),
                    "date": festival.get("date", ""),
                    "cultural_relaw": {
                        "id": "",
                        "name": cultural_data["name"],
                        "prefecture": cultural_data["prefecture"],
                        "date": cultural_data["date"],
                        "cultural_type": "重要無形民俗文化財",
                        "url": ref_url
                    }
                }
                cultural_relaw_results.append(result)
                
                print(f"  取得成功:")
                print(f"    文化財名称: {cultural_data['name']}")
                print(f"    都道府県: {cultural_data['prefecture']}")
            else:
                result = {
                    "qid": qid,
                    "label_ja": label_ja,
                    "label_en": festival.get("label_en", ""),
                    "latitude": festival.get("latitude", 0),
                    "longitude": festival.get("longitude", 0),
                    "prefecture": festival.get("prefecture", ""),
                    "description": festival.get("description", ""),
                    "date": festival.get("date", ""),
                    "cultural_relaw": {
                        "id": "",
                        "name": label_ja,
                        "prefecture": festival.get("prefecture", ""),
                        "date": "",
                        "cultural_type": "重要無形民俗文化財",
                        "url": ref_url
                    }
                }
                cultural_relaw_results.append(result)
                print(f"  部分データのみ")
        else:
            print(f"  文化庁 ID なし")
        
        time.sleep(10)
    
    cultural_output_path = OUTPUT_DIR / "cultural_relaw_data.json"
    with open(cultural_output_path, "w", encoding="utf-8") as f:
        json.dump(cultural_relaw_results, f, ensure_ascii=False, indent=2)
    
    festivals_output_path = OUTPUT_DIR / "festivals_with_cultural_relaw.json"
    with open(festivals_output_path, "w", encoding="utf-8") as f:
        json.dump(cultural_relaw_results, f, ensure_ascii=False, indent=2)
    
    print(f"\n{'=' * 60}")
    print(f"文化財データ取得完了: {len(cultural_relaw_results)} 件")
    print(f"文化財データ保存先: {cultural_output_path}")
    print(f"統合データ保存先: {festivals_output_path}")

if __name__ == "__main__":
    main()
