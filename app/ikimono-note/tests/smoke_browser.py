"""実ブラウザで主要導線が動くかを確かめる。

文字列を検査するテストは、画面が動くかを教えてくれない。実際にこの会話の中で、
撮影画面が丸ごと動かない状態や、APIキーが保存できない状態を、全テストが緑のまま
配ってしまった。壊れ方が静かなので、押して確かめるしかない。

  uv run --with playwright python tests/smoke_browser.py            # 運営者用(8443)
  uv run --with playwright python tests/smoke_browser.py --identify # 実際に識別まで通す

識別は Ollama で1分ほどかかるので、既定では省いて描画だけ確かめる。
"""

from __future__ import annotations

import argparse
import glob
import os
import json
import sys

from playwright.sync_api import sync_playwright

# 公開の経路は変わりうる (Tailscale Funnel は .ts.net しか使えず、独自ドメインへ
# 移るときに丸ごと差し替わる)。環境変数で上書きできるようにしておく。
ADMIN = os.getenv("IKIMONO_ADMIN_ORIGIN", "https://ubuntu-server-app.tailf74832.ts.net:8443")
PUBLIC = os.getenv("IKIMONO_PUBLIC_ORIGIN", "https://ubuntu-server-app.tailf74832.ts.net")
SAMPLE = {
    "category": "植物", "summary": "キク科の草本と考えられます。", "plantnet_used": False,
    "candidates": [{
        "common_name_ja": "セイヨウタンポポ", "scientific_name": "Taraxacum officinale",
        "confidence": 60, "evidence_status": "corroborated", "taxonomy_status": "verified",
        "taxon_rank": "species", "traits": ["ぎざぎざした根生葉"], "distinguishing_features": [],
        "contradictions": [], "evidence_gaps": [], "uncertainty": "", "sex": "対象外",
        "taxonomy_url": "https://www.inaturalist.org/taxa/47602",
    }],
}

# 決め手はあるが確かめたいことが残っている結果。撮り足しの案内はここでも出す
UNCERTAIN_SAMPLE = json.loads(json.dumps(SAMPLE))
UNCERTAIN_SAMPLE["candidates"][0]["uncertainty"] = "総苞外片が反り返っているかどうか"

failures: list[str] = []


def photo(name: str) -> dict:
    """input へ渡す小さな JPEG。撮り足しの検査に本物の写真は要らない。"""
    from io import BytesIO

    from PIL import Image

    buffer = BytesIO()
    Image.new("RGB", (64, 64), (120, 160, 120)).save(buffer, "JPEG")
    return {"name": name, "mimeType": "image/jpeg", "buffer": buffer.getvalue()}


def check(label: str, ok: bool, detail: str = "") -> None:
    print(f"  {'OK  ' if ok else 'NG  '}{label}" + (f"  ({detail})" if detail and not ok else ""))
    if not ok:
        failures.append(label)


def page_errors(page) -> list[str]:
    found: list[str] = []
    page.on("pageerror", lambda e: found.append(str(e)))
    # COOP の警告は http で開いたときに必ず出るので、動作とは無関係
    # 広告の商品APIが落ちていても、識別と記録は動く。見分けたいのは画面が壊れる類のエラー
    ignorable = ("Cross-Origin-Opener-Policy", "/api/amazon/products", "status of 503",
                 "status of 404")

    def note(message: str) -> None:
        if not any(word in message for word in ignorable):
            found.append(message)

    page.on("console", lambda m: note(m.text) if m.type == "error" else None)
    return found


def run(base: str, do_identify: bool) -> None:
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        context = browser.new_context(ignore_https_errors=True, viewport={"width": 1100, "height": 900})
        page = context.new_page()
        errors = page_errors(page)

        for path, marker in [("/", "#identify"), ("/history", "#showMap"),
                             ("/settings", "#settingsForm"), ("/privacy", ".panel"), ("/terms", ".panel")]:
            page.goto(base + path)
            page.wait_for_load_state("networkidle")
            check(f"{path} が開く", page.locator(marker).count() > 0)

        # 共通スクリプトが読まれ、関数が生きているか（読み込み忘れで静かに壊れた箇所）
        page.goto(base + "/settings"); page.wait_for_load_state("networkidle")
        for name in ["readApiKey", "keepingKeys", "buildBackup", "displayName", "providerLabel"]:
            check(f"設定画面で {name} が使える", page.evaluate(f"() => typeof {name}") == "function")

        # 記録の保存 (ドライブ) の導線が出ているか
        page.wait_for_timeout(800)
        check("設定画面がエラーを出していない",
              not page.locator("#message").inner_text().strip() if page.locator("#message").count() else True,
              page.locator("#message").inner_text()[:60] if page.locator("#message").count() else "")
        check("モデルの選択肢が描けている", page.locator("select[id^=model-]").count() >= 3)
        check("ドライブの導線が出る", page.locator("#drive-connect").count() == 1)

        # テーマの切り替え
        page.goto(base + "/"); page.wait_for_load_state("networkidle")
        before = page.evaluate("() => getComputedStyle(document.body).backgroundColor")
        page.click("#themeToggle"); page.wait_for_timeout(300)
        page.click("#themeToggle"); page.wait_for_timeout(300)
        check("テーマを切り替えられる",
              page.evaluate("() => getComputedStyle(document.body).backgroundColor") != before)

        # 結果の描画（識別を通さずに確かめる）
        page.evaluate("data => render(data)", SAMPLE)
        check("結果が描ける", page.locator(".candidate .name").count() == 1)
        check("参照リンクが並ぶ", page.locator(".sources a").count() >= 2)
        check("安全カードが出る", page.locator("#safetyCard").count() == 1)
        widths = page.eval_on_selector_all(".meter span", "els => els.map(e => e.style.width)")
        check("確信度のメーターに幅が入る", widths == ["60%"], str(widths))

        # 「もっと確かめたいこと」から撮り足せるか
        check("確かめたいことがなければ撮り足しの案内は出ない", page.locator("#shootingGuide").count() == 0)
        page.evaluate("data => render(data)", UNCERTAIN_SAMPLE)
        check("確かめたいことが残っていれば撮り足しの案内が出る", page.locator("#shootingGuide").count() == 1)
        check("案内からカメラも写真選択も押せる",
              page.locator("#addPhotoCamera").count() == 1 and page.locator("#addPhotoLibrary").count() == 1)
        page.set_input_files("#library", [photo("a.jpg")]); page.wait_for_timeout(1500)
        page.set_input_files("#libraryAdd", [photo("b.jpg")]); page.wait_for_timeout(600)
        check("撮り足すと写真は置き換わらずに増える", page.locator("#previews img").count() == 2,
              page.locator("#captureTitle").inner_text())
        page.set_input_files("#libraryAdd", [photo("c.jpg"), photo("d.jpg")]); page.wait_for_timeout(600)
        check("撮り足しても3枚を超えない", page.locator("#previews img").count() == 3,
              page.locator("#captureTitle").inner_text())

        if do_identify:
            image = sorted(glob.glob("/home/ats030/cache/species-eval/images/*.jpg"))[0]
            page.goto(base + "/"); page.wait_for_load_state("networkidle")
            page.set_input_files("#library", image); page.wait_for_timeout(2000)
            check("写真を選ぶと調べるボタンが出る", page.locator("#identify").is_visible())
            page.click("#identify")
            page.wait_for_selector(".candidate .sources", timeout=300000)
            check("実際に識別できる", page.locator(".candidate").count() >= 1)
            page.wait_for_timeout(2500)
            page.goto(base + "/history"); page.wait_for_load_state("networkidle"); page.wait_for_timeout(1500)
            check("記録に残る", page.locator(".entry").count() >= 1)
            check("記録から調べ直せる", page.locator(".again").count() >= 1)

        check("JSエラーが出ない", not errors, "; ".join(errors[:2]))
        context.close(); browser.close()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", default=ADMIN, help=f"確かめる入口 (既定: {ADMIN})")
    parser.add_argument("--public", action="store_true", help=f"公開版 ({PUBLIC}) を見る")
    parser.add_argument("--identify", action="store_true", help="実際に識別まで通す (1分ほどかかる)")
    args = parser.parse_args()
    base = PUBLIC if args.public else args.base
    print(f"■ {base}")
    run(base, args.identify)
    if failures:
        print(f"\n{len(failures)}件だめでした: {', '.join(failures)}")
        return 1
    print("\nすべて通りました")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
