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
from pathlib import Path
import httpx
import time
import subprocess
import contextlib
import json
import sys

from playwright.sync_api import sync_playwright

# 公開の経路は変わりうる (Tailscale Funnel は .ts.net しか使えず、独自ドメインへ
# 移るときに丸ごと差し替わる)。環境変数で上書きできるようにしておく。
# 手元の2つ (運営者用 :8443 と Funnel 公開版) は 2026-08-14 に止めた。本番は
# ログインの内側なので、この検査は通せない (画面の中身を見るため)。
# 既定では、この場でアプリを1つ起こして当てる。外の相手を見たいときは環境変数で。
LOCAL_PORT = int(os.getenv("IKIMONO_SMOKE_PORT", "8531"))
LOCAL = f"http://127.0.0.1:{LOCAL_PORT}"
ADMIN = os.getenv("IKIMONO_ADMIN_ORIGIN", "")
PUBLIC = os.getenv("IKIMONO_PUBLIC_ORIGIN", "")


@contextlib.contextmanager
def app_for_checking():
    """検査用に1つ起こす。運営者モード (ログイン無し) で、手元の設定を読む。"""
    if ADMIN:
        yield ADMIN, PUBLIC or ADMIN
        return
    environment = {**os.environ, "IKIMONO_PUBLIC_MODE": "0",
                   "IKIMONO_ALLOWED_HOSTS": "127.0.0.1,localhost"}
    process = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "main:app", "--host", "127.0.0.1",
         "--port", str(LOCAL_PORT), "--log-level", "warning"],
        cwd=str(Path(__file__).resolve().parent.parent), env=environment,
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        for _ in range(60):
            try:
                if httpx.get(LOCAL + "/health", timeout=2).status_code == 200:
                    break
            except httpx.HTTPError:
                time.sleep(0.5)
        else:
            raise SystemExit("検査用のアプリが起動しませんでした")
        yield LOCAL, LOCAL
    finally:
        process.terminate()
        process.wait(timeout=15)
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

# 種の保存法の指定がある候補。SAMPLE のほうは指定なしで、無印のままであることも見る
PROTECTED_SAMPLE = json.loads(json.dumps(SAMPLE))
PROTECTED_SAMPLE["candidates"][0].update({
    "common_name_ja": "イタセンパラ", "scientific_name": "Acheilognathus longipinnis",
    "protected_species": {"category": "国内希少野生動植物種", "subtype": "",
                          "common_name_ja": "イタセンパラ", "as_of": "令和7年2月"},
})

# 候補3件。広告が候補ごとに付き、確からしさの低い候補にも付くことを目で見る
THREE_CANDIDATE_SAMPLE = json.loads(json.dumps(SAMPLE))
THREE_CANDIDATE_SAMPLE["candidates"] = [
    {**json.loads(json.dumps(SAMPLE["candidates"][0])), "common_name_ja": name,
     "scientific_name": latin, "evidence_status": status, "confidence": score}
    for name, latin, status, score in [
        ("セイヨウタンポポ", "Taraxacum officinale", "corroborated", 60),
        ("カンサイタンポポ", "Taraxacum japonicum", "taxonomy_only", 40),
        ("ノゲシ", "Sonchus oleraceus", "uncertain", 30),
    ]
]

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

        for path, marker in [("/", "#identify"), ("/dashboard", "#showMap"),
                             ("/history", "#historyList"), ("/settings", "#settingsForm"),
                             ("/privacy", ".panel"), ("/terms", ".panel")]:
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

        # 利用者自身の観察メモ。AIの候補とは別に保存され、再読込でも残る
        page.goto(base + "/history"); page.wait_for_load_state("networkidle")
        note_record = {**json.loads(json.dumps(SAMPLE)), "id": "note-smoke",
                       "createdAt": "2026-08-14T12:00:00Z", "context": {},
                       "coordinates": {"latitude": 35.6812, "longitude": 139.7671},
                       "provider": "ollama", "model": "smoke"}
        page.evaluate("""record => new Promise((resolve, reject) => {
          const open = indexedDB.open("species-history", 1);
          open.onupgradeneeded = () => open.result.createObjectStore("entries", {keyPath: "id"});
          open.onerror = () => reject(open.error);
          open.onsuccess = () => {
            const tx = open.result.transaction("entries", "readwrite");
            const bytes = Uint8Array.from(atob("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII="), c => c.charCodeAt(0));
            const blob = new Blob([bytes], {type: "image/png"});
            record.thumbnail = blob; record.thumbnails = [blob, blob];
            tx.objectStore("entries").put(record);
            tx.oncomplete = resolve; tx.onerror = () => reject(tx.error);
          };
        })""", note_record)
        page.goto(base + "/dashboard"); page.wait_for_load_state("networkidle"); page.wait_for_timeout(300)
        check("ダッシュボードが記録件数を数える", page.locator("#totalCount").inner_text() == "1")
        check("場所のある記録を数える", page.locator("#locatedCount").inner_text() == "1")
        check("最近の観察を表示する", "セイヨウタンポポ" in page.locator("#recentList").inner_text())
        check("観察した大分類を表示する", "植物" in page.locator("#categoryList").inner_text() and "1件" in page.locator("#categoryList").inner_text())
        check("名前を絞れた段階を表示する", "種まで" in page.locator("#rankList").inner_text() and "1件" in page.locator("#rankList").inner_text())
        check("2つの内訳を円グラフで表示する", page.locator(".pie-chart").count() == 2 and page.locator(".pie-chart circle").count() == 2)
        check("円グラフに文字の凡例がある", page.locator(".pie-legend-row").count() == 2 and page.locator('.pie-chart[role="img"]').count() == 2)
        multi_pie = page.evaluate("() => pieChart([{key: '植物', count: 3}, {key: '動物', count: 1}], 4, '試験')")
        check("複数区分の円グラフに扇形を描く", multi_pie.count("<path") == 2 and "75%" in multi_pie and "25%" in multi_pie, multi_pie)
        empty_pie = page.evaluate("() => pieChart([], 0, '試験')")
        check("記録がない場合は空状態を表示する", "記録が増えると" in empty_pie and "<svg" not in empty_pie, empty_pie)
        breakdowns = page.evaluate("sample => { const old = structuredClone(sample); delete old.candidates[0].taxon_rank; const records = [sample, sample, old, {candidates: []}]; return {categories: categoryCounts(records), ranks: rankCounts(records)} }", SAMPLE)
        check("大分類の合計が全記録数と一致する", sum(item["count"] for item in breakdowns["categories"]) == 4 and breakdowns["categories"][0] == {"key": "植物", "count": 3}, str(breakdowns))
        check("絞り込み段階の合計が全記録数と一致する", sum(item["count"] for item in breakdowns["ranks"]) == 4 and breakdowns["ranks"][0] == {"key": "種まで", "count": 2} and {"key": "階級の記録なし", "count": 1} in breakdowns["ranks"] and breakdowns["ranks"][-1] == {"key": "候補なし", "count": 1}, str(breakdowns))
        check("押す前は地図ライブラリを読まない", page.evaluate("() => typeof window.L") == "undefined")
        page.click("#showMap"); page.wait_for_selector("#historyMap.leaflet-container")
        check("ダッシュボードで地図を表示できる", page.locator("#historyMap .leaflet-marker-icon").count() == 1)
        layer_labels = page.locator(".leaflet-control-layers label")
        labels = layer_labels.all_inner_texts()
        check("観察環境向けの4レイヤだけを表示する", layer_labels.count() == 4 and all(any(name in label for label in labels) for name in ["地図", "写真", "土地条件", "湖沼（水深）"]), str(labels))
        for layer_name, credit in [("土地条件", "数値地図25000・土地条件"), ("湖沼（水深）", "湖沼データ・湖沼図／調査済み80湖沼")]:
            layer = page.locator(".leaflet-control-layers label", has_text=layer_name)
            layer.click(); page.wait_for_timeout(500)
            check(layer_name+"レイヤへ切り替えられる", layer.locator('input[type="radio"]').is_checked() and credit in page.locator(".leaflet-control-attribution").inner_text())
        page.set_viewport_size({"width": 390, "height": 844})
        summary = page.locator(".summary-grid").bounding_box()
        breakdown_box = page.locator(".breakdown-summary").bounding_box()
        check("ダッシュボードがスマホ幅に収まる", bool(summary) and summary["x"] >= 0 and summary["x"] + summary["width"] <= 390 and bool(breakdown_box) and breakdown_box["x"] + breakdown_box["width"] <= 390, str((summary, breakdown_box)))
        page.set_viewport_size({"width": 1100, "height": 900})
        page.goto(base + "/history"); page.wait_for_load_state("networkidle")
        check("地図を記録ページから移動した", page.locator("#historyMap").count() == 0)
        page.reload(); page.wait_for_load_state("networkidle"); page.wait_for_timeout(500)
        page.locator('.entry[data-id="note-smoke"] summary').click()
        page.wait_for_timeout(300)
        rerun = page.locator('.entry[data-id="note-smoke"] .rerun-remove')
        check("調べ直す写真ごとに外すボタンが出る", rerun.count() == 2)
        check("元の記録には2枚の写真が残る", page.locator('.entry[data-id="note-smoke"] .detail-photo').count() == 2)
        rerun.first.click(); page.wait_for_timeout(150)
        check("調べ直す写真を1枚ずつ外せる", rerun.count() == 1)
        check("外しても元の記録の写真は消えない", page.locator('.entry[data-id="note-smoke"] .detail-photo').count() == 2)
        rerun.first.click(); page.wait_for_timeout(150)
        check("調べ直す最後の1枚は残す", rerun.count() == 1 and "1枚以上必要" in page.locator('.entry[data-id="note-smoke"] .rerun-message').inner_text())
        page.set_viewport_size({"width": 390, "height": 844})
        remove_box = rerun.first.bounding_box()
        check("写真を外す操作がスマホ幅に収まる", bool(remove_box) and remove_box["x"] >= 0 and remove_box["x"] + remove_box["width"] <= 390 and remove_box["height"] >= 44, str(remove_box))
        page.set_viewport_size({"width": 1100, "height": 900})
        note = page.locator('.entry[data-id="note-smoke"] .note-input')
        check("記録に自分の観察欄が出る", note.count() == 1)
        note.fill("<b>夕方には花が閉じていた</b>")
        page.wait_for_timeout(1000)
        check("観察メモが自動保存される", "保存済み" in page.locator(
              '.entry[data-id="note-smoke"] .note-status').inner_text())
        page.reload(); page.wait_for_load_state("networkidle"); page.wait_for_timeout(500)
        page.locator('.entry[data-id="note-smoke"] summary').click()
        check("観察メモが再読込後も残る", page.locator(
              '.entry[data-id="note-smoke"] .note-input').input_value() == "<b>夕方には花が閉じていた</b>")
        check("メモのある記録に印が付く", page.locator(
              '.entry[data-id="note-smoke"] .note-mark').count() == 1)
        older = {**note_record, "userNote": "古い端末のメモ",
                 "noteUpdatedAt": "2020-01-01T00:00:00Z"}
        page.evaluate("record => restoreBackup({format: BACKUP_FORMAT, records: [record]})", older)
        page.reload(); page.wait_for_load_state("networkidle"); page.wait_for_timeout(500)
        page.locator('.entry[data-id="note-smoke"] summary').click()
        check("古いDriveメモで新しい端末メモを上書きしない", page.locator(
              '.entry[data-id="note-smoke"] .note-input').input_value() == "<b>夕方には花が閉じていた</b>")
        page.set_viewport_size({"width": 390, "height": 844})
        box = page.locator('.entry[data-id="note-smoke"] .note-input').bounding_box()
        check("観察メモ欄がスマホ幅に収まる", bool(box) and box["x"] >= 0 and box["x"] + box["width"] <= 390,
              str(box))
        page.set_viewport_size({"width": 1100, "height": 900})

        # テーマの切り替え
        page.goto(base + "/"); page.wait_for_load_state("networkidle")
        page.set_viewport_size({"width": 390, "height": 844})
        header_actions = page.locator(".top-actions").bounding_box()
        check("撮影画面の追加ナビがスマホ幅に収まる", bool(header_actions) and header_actions["x"] >= 0 and header_actions["x"] + header_actions["width"] <= 390, str(header_actions))
        page.set_viewport_size({"width": 1100, "height": 900})
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

        # 広告は候補ごと。商品APIが断られていても、候補ごとの検索リンクは残る
        page.evaluate("data => render(data)", THREE_CANDIDATE_SAMPLE)
        page.wait_for_timeout(2500)
        shelves = page.locator("article.candidate .product-shell")
        check("棚は候補の中に1つずつ置かれる", shelves.count() == 3, str(shelves.count()))
        check("棚が候補の外に残っていない",
              page.locator(".product-shell").count() == shelves.count())
        labels = page.eval_on_selector_all(".product-shell", "els => els.map(e => e.innerText)")
        check("どの候補の広告かを名前で言う",
              all(name in text for name, text in zip(["セイヨウタンポポ", "カンサイタンポポ", "ノゲシ"], labels)),
              " / ".join(t[:30] for t in labels))
        page.evaluate("data => render(data)", SAMPLE)

        # 種の保存法の指定。指定のない候補には何も出さない (無印は「指定なし」ではない)
        check("指定のない候補には注意書きを出さない", page.locator(".protected").count() == 0)
        page.evaluate("data => render(data)", PROTECTED_SAMPLE)
        check("指定のある候補に注意書きが出る", page.locator(".protected").count() == 1,
              page.locator("#results").inner_text()[:80])
        check("注意書きから環境省の一覧へ行ける",
              page.locator('.protected a[href*="env.go.jp/nature/kisho"]').count() == 1)
        check("同梱したリストの版を出す", "令和7年2月" in (
            page.locator(".protected").inner_text() if page.locator(".protected").count() else ""))
        page.evaluate("data => render(data)", SAMPLE)

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
        remove = page.locator("#previews .preview-remove")
        remove.first.click(); page.wait_for_timeout(150)
        check("選択中の写真を1枚ずつ外せる", page.locator("#previews img").count() == 2)
        remove.first.click(); page.wait_for_timeout(150)
        check("写真を1枚まで減らせる", page.locator("#previews img").count() == 1)
        remove.first.click(); page.wait_for_timeout(150)
        check("最後の1枚は残す", page.locator("#previews img").count() == 1 and "1枚以上必要" in page.locator("#status").inner_text())

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
    parser.add_argument("--base", default="", help="確かめる入口 (既定: この場で1つ起こす)")
    parser.add_argument("--public", action="store_true", help="公開版として見る")
    parser.add_argument("--identify", action="store_true", help="実際に識別まで通す (1分ほどかかる)")
    args = parser.parse_args()
    with app_for_checking() as (admin, public):
        base = args.base or (public if args.public else admin)
        print(f"■ {base}")
        run(base, args.identify)
    if failures:
        print(f"\n{len(failures)}件だめでした: {', '.join(failures)}")
        return 1
    print("\nすべて通りました")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
