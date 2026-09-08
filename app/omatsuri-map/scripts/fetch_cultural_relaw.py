#!/usr/bin/env python3
"""WikidataのP3259を使って文化庁文化財データを取得し、既存祭りデータと統合"""

import requests
import json
import time
import re
from pathlib import Path
from geopy.geocoders import Nominatim
from geopy.exc import GeocoderTimedOut, GeocoderServiceError

OUTPUT_DIR = Path("/home/ats030/app/omatsuri-map/data")

PREFECTURE_PATTERN = (
    r"(?:北海道|東京都|京都府|大阪府|"
    r"(?:青森|岩手|宮城|秋田|山形|福島|茨城|栃木|群馬|埼玉|千葉|神奈川|新潟|富山|石川|福井|山梨|長野|岐阜|静岡|愛知|三重|滋賀|兵庫|奈良|和歌山|鳥取|島根|岡山|広島|山口|徳島|香川|愛媛|高知|福岡|佐賀|長崎|熊本|大分|宮崎|鹿児島|沖縄)県)"
)

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

def geocode_address(address: str) -> tuple[float, float] | None:
    """住所から緯度経度を取得（OpenStreetMap Nominatim API）"""
    try:
        geolocator = Nominatim(user_agent="OmatsuriMap/1.0", timeout=5)
        location = geolocator.geocode(address)
        if location:
            return (location.latitude, location.longitude)
    except (GeocoderTimedOut, GeocoderServiceError):
        pass
    return None

def fetch_cultural_data(wikidata_ref_url: str) -> dict:
    """Wikidataの証拠URLから文化庁データを抽出"""
    headers = {"User-Agent": "OmatsuriMap/1.0"}
    
    response = requests.get(wikidata_ref_url, headers=headers, timeout=10)
    response.raise_for_status()
    html = response.text
    
    cultural_data = {"name": "", "prefecture": "", "date": "", "url": wikidata_ref_url, "address": ""}
    
    match = re.search(r'<span id="title1"[^>]*>([^<]+)</span>', html)
    if match:
        cultural_data["name"] = match.group(1).strip()
    
    match = re.search(rf'所在都道府県、地域[\s\S]*?>({PREFECTURE_PATTERN})', html)
    if match:
        cultural_data["prefecture"] = match.group(1).strip()
    
    match = re.search(r'公開日：([^<]+)', html)
    if match:
        cultural_data["date"] = match.group(1).strip()
    
    match = re.search(r'所在地[\s\S]*?<td[^>]*class="detail-td">[\s\S]*?([^<]+)</td>', html)
    if match:
        cultural_data["address"] = match.group(1).strip()
    
    return cultural_data

def main():
    """メイン処理"""
    print("文化庁文化財データ取得と既存祭りデータ統合")
    print("=" * 60)
    
    with open(OUTPUT_DIR / "festivals.json", "r", encoding="utf-8") as f:
        festivals = json.load(f)
    
    print(f"既存祭りデータ: {len(festivals)} 件")
    
    cultural_relaw_results = []
    
    for festival in festivals:
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
                        "url": ref_url,
                        "address": cultural_data.get("address", "")
                    }
                }
                if not festival.get("latitude") or not festival.get("longitude"):
                    address = f"{cultural_data['prefecture']}{cultural_data.get('address', '')}"
                    if address:
                        coords = geocode_address(address)
                        if coords:
                            result["latitude"] = coords[0]
                            result["longitude"] = coords[1]
                            print(f"    GeoCoding 成功: {coords[0]:.6f}, {coords[1]:.6f}")
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
