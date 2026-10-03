"""祭りではない神社・合祀項目を frontend/festivals.json から除外する。

Wikidata の神社項目(P31=Q845945)が祭りとして混入したもの。いずれも日付未定で、
説明文は名称からの推測だった(ats030-vigwd)。祭事そのものである神宮式年遷宮は残す。
"""

import json
import re
from pathlib import Path

PATH = Path(__file__).resolve().parent.parent / "frontend" / "festivals.json"
SHRINE_LABEL = re.compile(r"(神社|大社|神宮|八幡宮|天満宮|宮|寺|院|稲荷|権現|明神|社)$|合祀")
KEEP = {"Q3959472"}  # 神宮式年遷宮


def is_shrine_item(item):
    return item["qid"] not in KEEP and bool(SHRINE_LABEL.search(item["label_ja"]))


def main():
    items = json.loads(PATH.read_text(encoding="utf-8"))
    kept = [x for x in items if not is_shrine_item(x)]
    PATH.write_text(json.dumps(kept, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"removed {len(items) - len(kept)}, remaining {len(kept)}")


if __name__ == "__main__":
    main()
