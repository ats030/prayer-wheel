"""祭り名・説明を種別カテゴリに割り当て、frontend/festivals.json に
categories 配列(先頭=代表カテゴリ)を書き込む。

判定は DESIGN.md のカテゴリ色トークンと対応する制御語彙による部分文字列マッチ。
一つの祭りが複数の種別を持つことがあるため、マッチした種別をすべて残す
(例: ねぶた祭は「山車・屋台」+「行事」)。

カテゴリ(8 特定 + その他)
  山車・屋台  山車・屋台・ねぶた・ねぷた・山笠
  花火        花火大会・打ち上げ花火
  演舞・盆踊り 盆踊り・阿波おどり・よさこい・神楽・獅子舞 等の演舞系
  行列・渡御  渡御・行列・渡会
  神事・祭礼  祭礼・神事・奉納 等の宗教的側面
  灯籠・火祭り 灯籠・提灯・たいまつ・松明・篝火 等の灯火系
  博覧会・市   博覧会・バザール・マルシェ 等の展示・商業イベント
  行事        「まつり」「祭」「フェスティバル」等の汎用行事

いずれの特定カテゴリにも当てはまらなければ categories は空配列。
フロント側は空配列を「その他 / 未分類」(#68737d)としてマーカー・凡例に表示し、
「その他」フィルタも空配列を指す。この空配列フォールバックを、onsen-map の
spring_type 未分類(空)の表現と同形に保つ。
"""

import json
import re
from collections import Counter
from pathlib import Path

# 制御語彙。id は CSS トークン名(DESIGN.md --cat-*)に連動させる。
# order は categories 配列入れの順(先頭が代表カテゴリ)。
CATS = [
    {"id": "mt", "name": "山車・屋台",
     # 説明文の「屋台」は出店の意味が多いため、単独では祭り名だけに当て、
     # 説明文には山車の意味が明確な複合語で当てる。
     "keys": ["山車", "ねぶた", "ねぷた", "山笠", "だんじり", "曳山", "台輪",
              "屋台行事", "屋台行列", "太鼓屋台", "はやし屋台", "芸屋台", "大屋台"],
     "label_keys": ["屋台", "ふとん太鼓", "太鼓台"]},
    {"id": "hb", "name": "花火",
     "keys": ["花火", "打ち上げ花火"],
     "label_keys": ["龍勢"]},
    {"id": "ma", "name": "演舞・盆踊り",
     "keys": ["盆踊り", "阿波おどり", "あわ踊り", "よさこい", "笠踊り",
              "神楽", "獅子舞", "えんぶり", "エイヤ", "流鏑", "鉾",
              "舞楽", "稚児舞", "田遊び"],
     # 説明文に広く現れる語(一般語の「太鼓」「踊」など)は祭り名(label_ja)に
     # だけ当てる。「舞」単独は舞鶴などの地名に当たるため複合語で持つ。
     "label_keys": ["の舞", "神舞", "田舞", "撞舞", "翁舞", "つく舞",
                    "権現舞", "会舞", "神事舞", "踊", "おどり", "田楽", "田植", "囃子", "ばやし",
                    "太鼓", "念仏", "剣舞", "獅子", "YOSAKOI", "萬歳", "万歳", "歌舞伎", "神能", "奏"]},
    {"id": "kw", "name": "行列・渡御",
     "keys": ["渡御", "行列", "渡会"],
     "label_keys": ["練供養", "巡行"]},
    {"id": "jr", "name": "神事・祭礼",
     "keys": ["祭礼", "神事", "奉納", "来訪神"],
     "label_keys": ["綱引", "大綱", "会式", "護摩", "遷宮", "祇園", "くんち",
                    "えびす", "お田", "御田", "御神田", "行事"]},
    {"id": "hn", "name": "灯籠・火祭り",
     "keys": ["灯籠", "燈籠", "提灯", "たいまつ", "松明", "篝火",
              "火祭り", "送り火"],
     "label_keys": ["灯", "燈呂", "燈会", "燈花", "あかり", "の火祭", "火振",
                    "火勢", "竹宵", "百八燈"]},
    {"id": "si", "name": "博覧会・市",
     "keys": ["博覧会", "バザール", "マルシェ", "フリーマーケット",
              "マーケット", "初売り", "陶器市", "夜市", "ボロ市"],
     "label_only": True},
    {"id": "js", "name": "行事",
     "keys": ["まつり", "祭", "祭典", "フェスティバル", "フェス",
              "開園", "開花", "展"],
     "label_keys": ["カーニバル", "ミュージック", "音楽", "FES", "FESTIVAL", "ROCK",
                    "Rock", "ジャム", "マダン", "ハーリー", "ペーロン", "凧",
                    "かまくら", "グランプリ", "コンテスト", "コンクール",
                    "合戦", "競漕", "競馬", "ハロウィン", "サミット", "さみっと",
                    "まんが博", "ウチナーンチュ大会", "カヌー大会"]},
]


def _match_keys(s, keys):
    return any(k in s for k in keys)


def classify(entry):
    """entry からマッチしたカテゴリ name の list を返す。空なら []。"""
    label = (entry.get("label_ja") or "").strip()
    desc = (entry.get("description") or "").strip()
    full = f"{label} {desc}".strip()
    out = []
    for cat in CATS:
        # 「博覧会・市」以外は label+description に検出する。
        # 市名(長崎市・弘前市…)は説明文に混入するため、「市」系は
        # 祭り名(label_ja)に絞る(市名はほぼ説明文中にしか現れない)。
        src = label if cat.get("label_only") else full
        if (src and _match_keys(src, cat["keys"])) or \
                _match_keys(label, cat.get("label_keys", [])):
            out.append(cat["name"])
    return out


def main():
    path = Path("frontend/festivals.json")
    data = json.loads(path.read_text(encoding="utf-8"))
    for entry in data:
        entry["categories"] = classify(entry)

    path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )

    total = len(data)
    tagged = sum(1 for e in data if e["categories"])
    none = total - tagged
    per = Counter()
    for e in data:
        per.update(e["categories"])

    print(f"総計 {total} / 分類済み {tagged} ({tagged/total:.1%}) / その他 {none}")
    print("--- カテゴリ頻出 (multi-tag) ---")
    for cat in CATS:
        print(f"  {per[cat['name']]:5d}  {cat['name']}")
    print(f"      {none:5d}  その他(未分類)")


if __name__ == "__main__":
    main()
