#!/usr/bin/env python3
import json
import time
import urllib.request
import urllib.parse

def fetch_dates(qid):
    url = f"https://www.wikidata.org/w/api.php?action=wbgetentities&ids={qid}&format=json&props=claims"
    
    try:
        with urllib.request.urlopen(url, timeout=10) as response:
            data = json.loads(response.read().decode())
        
        claims = data.get("entities", {}).get(qid, {}).get("claims", {})
        
        if "P585" in claims:
            stmt = claims["P585"][0]
            date_value = stmt.get("mainsnak", {}).get("datavalue", {}).get("value", {})
            date_str = date_value.get("time", "")
            if date_str:
                return date_str.split("T")[0]
        
        if "P571" in claims:
            stmt = claims["P571"][0]
            date_value = stmt.get("mainsnak", {}).get("datavalue", {}).get("value", {})
            date_str = date_value.get("time", "")
            if date_str:
                return date_str.split("T")[0]
        
        return "日付未定"
        
    except Exception as e:
        print(f"エラー (QID: {qid}): {e}")
        return "日付未定"

def main():
    with open("/home/ats030/app/omatsuri-map/data/festivals.json", "r", encoding="utf-8") as f:
        festivals = json.load(f)
    
    total = len(festivals)
    print(f"合計 {total} 件を処理します")
    
    for i, festival in enumerate(festivals, 1):
        qid = festival["qid"]
        print(f"[{i}/{total}] {qid} を処理中...")
        
        date_info = fetch_dates(qid)
        festival["date"] = date_info
        print(f"  -> {date_info}")
        
        if i < total:
            time.sleep(5)
    
    with open("/home/ats030/app/omatsuri-map/data/festivals-with-date.json", "w", encoding="utf-8") as f:
        json.dump(festivals, f, ensure_ascii=False, indent=2)
    
    print(f"\n完了! 結果を data/festivals-with-date.json に保存しました")

if __name__ == "__main__":
    main()
