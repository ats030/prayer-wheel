"""画面の見た目を数値で写し取り、変更の前後で突き合わせる。

smoke_browser.py は「動くか」を見るが「色や枠が付いているか」は見ない。実際に
index.css が login/settings 側の名前 (--color-*) を未定義のまま参照して、枠も背景も
消えたことがあり、全テストが緑のまま配ってしまった。CSS を触るときは、押して
確かめるだけでは足りず、算出値を突き合わせる必要がある。

  uv run --with playwright python tests/style_snapshot.py before.json
  uv run --with playwright python tests/style_snapshot.py after.json
  uv run --with playwright python tests/style_snapshot.py --diff before.json after.json

見た目を変えない整理なら差分は0になる。1件でも出たら、その整理は見た目を変えている。

検査用のアプリは smoke_browser.py と同じやり方でこの場に1つ起こす。手元の記録や
共有の置き場を汚さず、画面の中身も毎回同じところから始まる。
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import httpx
from playwright.sync_api import sync_playwright

sys.path.insert(0, str(Path(__file__).resolve().parent))
from smoke_browser import app_for_checking, photo  # noqa: E402

PAGES = ["/", "/history", "/dashboard", "/settings", "/login",
         "/changelog", "/terms", "/privacy"]
# (名前, localStorage に置く値, OS 側の明るさ)。テーマの宣言は各 CSS に4組あり、
# 素の :root / [data-theme="dark"] / [data-theme="light"] / prefers-color-scheme。
# localStorage を置くと theme.js が必ず data-theme を立てるので、置かない場合を
# 用意しないと prefers-color-scheme の組だけ一度も評価されない。そこを書き換えて
# 壊しても差分0と出てしまうため、「自動 + OS ダーク」を必ず通す。
THEMES = [
    ("light", "light", "light"),
    ("dark", "dark", "light"),
    ("system-dark", None, "dark"),
]
# index.css の折り返し点は 360 / 390 / 520 / 760。その境目の内側と、
# どの折り返しにも入らない広い幅を見る。1つの幅だけでは、@media を
# まとめ直したときの崩れが素通りしてしまう。
WIDTHS = [360, 390, 520, 760, 1024]

# 色と枠は「消えた」を捕まえるため。寸法は @media の重複をまとめたり、上書きされる
# 規則を消したりしたときに、効き目まで変わっていないかを見るため。
PROPS = [
    "background-color", "color", "border-top-color", "border-right-color",
    "border-bottom-color", "border-left-color", "border-top-width",
    "border-right-width", "border-bottom-width", "border-left-width",
    "border-top-left-radius", "border-bottom-right-radius", "outline-color",
    "box-shadow", "fill", "stroke", "font-family", "font-size", "font-weight",
    "display", "flex-direction", "flex-wrap", "grid-template-columns",
    "justify-content", "align-items", "gap", "padding-top", "padding-left",
    "margin-top", "margin-left", "min-height", "min-width", "width", "height",
    "text-decoration-line", "opacity", "visibility",
]

COLLECT = """(props) => {
  const out = [];
  const nodes = document.querySelectorAll("*");
  /* 採番は「見る要素」だけで進める。head に link を1本足しただけで
     以降の全要素の鍵がずれ、比較が成立しなくなるのを避けるため。 */
  let n = 0;
  for (let i = 0; i < nodes.length; i++) {
    const el = nodes[i];
    const tag = el.tagName.toLowerCase();
    if (tag === "script" || tag === "style" || tag === "link" || tag === "meta") continue;
    const cs = getComputedStyle(el);
    const row = {};
    for (const p of props) row[p] = cs.getPropertyValue(p);
    out.push({ k: n + ":" + tag, v: row });
    n++;
  }
  return out;
}"""

# 共有ページは /s/<合言葉> でしか開けない。share.css の当たる要素 (写真・候補・
# 特徴・但し書き) を全部出すため、特徴付きの候補を2件入れて1つ作る。
SHARE_CANDIDATES = [
    {"common_name_ja": "セイヨウタンポポ", "scientific_name": "Taraxacum officinale",
     "confidence": 62, "traits": ["黄色い舌状花", "根生葉がロゼット", "総苞外片が反り返る"]},
    {"common_name_ja": "カンサイタンポポ", "scientific_name": "Taraxacum japonicum",
     "confidence": 24, "traits": ["総苞外片が反り返らない"]},
]


def make_share(base: str) -> str:
    """検査用アプリに共有ページを1つ作り、その合言葉を返す。置き場は使い捨て。"""
    response = httpx.post(
        base + "/api/share",
        files={"photo": ("share.jpg", photo("share.jpg")["buffer"], "image/jpeg")},
        data={"candidates": json.dumps(SHARE_CANDIDATES, ensure_ascii=False)},
        timeout=30)
    response.raise_for_status()
    return response.json()["token"]


def capture(out_path: str) -> None:
    """全ページ・全テーマ・全幅で算出値を集める。テーマは theme.js と同じ入口で決める。"""
    snapshot: dict[str, list] = {}
    with app_for_checking() as (base, _public):
        paths = PAGES + [f"/s/{make_share(base)}"]
        with sync_playwright() as engine:
            browser = engine.chromium.launch()
            for theme, stored, scheme in THEMES:
              for width in WIDTHS:
                for path in paths:
                    page = browser.new_page(
                        viewport={"width": width, "height": 844},
                        color_scheme=scheme)
                    # 「自動」は取り置きを消してから開く。残っていると data-theme が
                    # 立ち、OS 側の指定が効かなくなる。
                    page.add_init_script(
                        f"try{{localStorage.setItem('species-theme','{stored}')}}"
                        f"catch(error){{}}" if stored else
                        "try{localStorage.removeItem('species-theme')}catch(error){}")
                    page.goto(base + path, wait_until="load")
                    # 設定の取り寄せが済むまで待つ。ここを待たないと
                    # PlantNet の選択肢の出し入れが実行ごとに変わり、
                    # 整理による差分と見分けられなくなる。
                    page.wait_for_load_state("networkidle")
                    # networkidle だけでは Web フォントの適用完了を保証しない。ここを
                    # 待たないとフォールバック書体での折り返しが高さや幅の差分として
                    # 混ざり、CSS の変更と区別できなくなる。
                    page.evaluate("document.fonts.ready")
                    page.wait_for_timeout(600)
                    # 合言葉は毎回変わる。画面の名前には残さない
                    name = "/s/*" if path.startswith("/s/") else path
                    snapshot[f"{theme} {width}px {name}"] = page.evaluate(COLLECT, PROPS)
                    page.close()
            browser.close()
    Path(out_path).write_text(
        json.dumps(snapshot, ensure_ascii=False, indent=1, sort_keys=True),
        encoding="utf-8")
    print(f"{out_path}: {len(snapshot)} 画面 / {sum(len(v) for v in snapshot.values())} 要素")


def diff(before_path: str, after_path: str) -> int:
    """差分を人が読める形で出す。0でなければ、その整理は見た目を変えている。"""
    before = json.loads(Path(before_path).read_text(encoding="utf-8"))
    after = json.loads(Path(after_path).read_text(encoding="utf-8"))
    changes = 0
    for screen in sorted(set(before) | set(after)):
        old, new = before.get(screen), after.get(screen)
        if old is None or new is None:
            print(f"[片方にしかない画面] {screen}")
            changes += 1
            continue
        if len(old) != len(new):
            print(f"[要素の数が違う] {screen}: {len(old)} → {len(new)}")
            changes += 1
        moved = False
        for row_old, row_new in zip(old, new):
            if row_old["k"] != row_new["k"]:
                print(f"[要素がずれた] {screen}: {row_old['k']} → {row_new['k']}")
                changes += 1
                moved = True
                break
            for prop, was in row_old["v"].items():
                now = row_new["v"].get(prop)
                if was != now:
                    print(f"{screen} {row_old['k']} {prop}: {was!r} → {now!r}")
                    changes += 1
        if moved:
            continue
    print(f"差分 {changes} 件")
    return changes


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("out", nargs="?", help="算出値を書き出す先")
    parser.add_argument("--diff", nargs=2, metavar=("BEFORE", "AFTER"))
    args = parser.parse_args()
    if args.diff:
        return 1 if diff(*args.diff) else 0
    if not args.out:
        parser.error("書き出し先か --diff のどちらかが要ります")
    capture(args.out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
