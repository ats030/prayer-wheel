"""候補の学名が、種の保存法の規制対象かどうかを引く。

安全カードは採取について4点 (土地の持ち主の許可・保護区域・自治体のきまり・保護されて
いる種) を未確認だと述べている。座標から判定できるのは1点もなかった (docs/
tool-license-collection-regulation-data.yaml)。種だけは座標を要らず、アプリが図鑑データで
実在確認まで済ませた学名で引ける。

引き当てられなかったことは「規制対象ではない」を意味しない。都道府県の条例が独自に
指定している種があり、亜種で指定されているものは種名では当たらない。呼び出し側は
一致したときだけ表示すること。
"""

from __future__ import annotations

import json
import bundled_resources
from functools import lru_cache
from pathlib import Path
from typing import Any

DATA_PATH = Path(__file__).parent / "data" / "protected_species.json"


@lru_cache(maxsize=1)
def _table() -> tuple[dict[str, dict[str, str]], str]:
    """学名 (小文字化) から指定内容への表と、同梱した版の基準を返す。"""
    try:
        data = json.loads(bundled_resources.read_text(DATA_PATH))
    except (OSError, ValueError) as error:
        # リストを読めなくても識別は続ける。出せないのは注意書き1つで、
        # 「持ち帰ってよいか：確認が必要」は元から出ている。ただし黙って消えると
        # 「指定なし」と同じ見た目になるので、運営者には journal で知らせる。
        print(f"[ikimono-note] {DATA_PATH} を読めません ({error})。"
              " 種の保存法の照合を行いません。data/build_protected_species.py で作り直してください。",
              flush=True)
        return {}, ""
    index = {
        str(item.get("scientific_name") or "").strip().casefold(): {
            "category": str(item.get("category") or ""),
            "subtype": str(item.get("subtype") or ""),
            "common_name_ja": str(item.get("common_name_ja") or ""),
        }
        for item in data.get("species") or []
        if str(item.get("scientific_name") or "").strip()
    }
    return index, str(data.get("as_of") or "")


def as_of() -> str:
    """同梱したリストの基準 (例: 令和7年2月)。画面に出して版を明かすために使う。"""
    return _table()[1]


def count() -> int:
    return len(_table()[0])


def lookup(scientific_name: str) -> dict[str, str] | None:
    """学名の完全一致で引く。部分一致も属での推測もしない。

    前方一致を許すと、亜種が指定されているだけの種を「指定されています」と出してしまう。
    法律の話で外すほうを選ぶ。
    """
    key = str(scientific_name or "").strip().casefold()
    if not key:
        return None
    return _table()[0].get(key)


def annotate(result: dict[str, Any]) -> dict[str, Any]:
    """識別結果の各候補に protected_species を付ける。一致した候補にだけ付く。"""
    for candidate in result.get("candidates") or []:
        found = lookup(candidate.get("scientific_name", ""))
        if found:
            candidate["protected_species"] = {**found, "as_of": as_of()}
    return result
