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
import base64
import glob
import os
from pathlib import Path
import httpx
import time
import subprocess
import contextlib
import json
import re
import sys
import tempfile
from urllib.parse import unquote_plus

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
    # 共有ページの置き場は検査ごとに捨てる。手元の本物 (~/data) を検査で汚さない
    share_db = Path(tempfile.mkdtemp(prefix="ikimono-smoke-")) / "shares.db"
    environment = {**os.environ, "IKIMONO_PUBLIC_MODE": "0",
                   "IKIMONO_ALLOWED_HOSTS": "127.0.0.1,localhost",
                   "IKIMONO_SHARE_DB": str(share_db)}
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


@contextlib.contextmanager
def public_app_for_checking():
    """公開版 (BYOK) を1つ起こす。APIキーはサーバーに置かず、この端末にだけ残る。

    運営者用とは画面の出し分けも設定の保存先も違う。本番 (Cloud Run) は
    こちらなので、公開版でしか起きない壊れ方はここでしか捕まえられない。
    """
    port = LOCAL_PORT + 1
    base = f"http://127.0.0.1:{port}"
    share_db = Path(tempfile.mkdtemp(prefix="ikimono-smoke-public-")) / "shares.db"
    environment = {**os.environ, "IKIMONO_PUBLIC_MODE": "1", "IKIMONO_PUBLIC_LOCAL": "0",
                   "IKIMONO_BACKGROUND_JOBS": "0",
                   "IKIMONO_ALLOWED_HOSTS": "127.0.0.1,localhost",
                   "IKIMONO_SHARE_DB": str(share_db)}
    process = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "main:app", "--host", "127.0.0.1",
         "--port", str(port), "--log-level", "warning"],
        cwd=str(Path(__file__).resolve().parent.parent), env=environment,
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        for _ in range(60):
            try:
                if httpx.get(base + "/health", timeout=2).status_code == 200:
                    break
            except httpx.HTTPError:
                time.sleep(0.5)
        else:
            raise SystemExit("検査用の公開版が起動しませんでした")
        yield base
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
        context.set_geolocation({"latitude": 35.681236, "longitude": 139.767125, "accuracy": 12})
        context.grant_permissions(["geolocation"], origin=base)
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
        for name in ["readApiKey", "keepingKeys", "buildBackup", "displayName", "providerLabel", "normalizeOllamaUrl"]:
            check(f"設定画面で {name} が使える", page.evaluate(f"() => typeof {name}") == "function")

        check("Ollama URLへhttpを補える", page.evaluate("() => normalizeOllamaUrl('localhost:11434')") == "http://localhost:11434")
        check("空のOllama URLを日本語で案内する", page.evaluate("() => { try { normalizeOllamaUrl(''); return false } catch (error) { return error.message === 'Ollama URLを入力してください' } }") is True)
        page.fill("#model-local", "gemma4:12b")
        page.locator("[name=provider][value=local]").check()
        check("Ollama選択が現在のAIへ即時反映される", page.locator("#active-provider").inner_text() == "Ollama · gemma4:12b")
        page.locator("[name=provider][value=gemini]").check()
        check("Geminiへ戻しても現在のAIと一致する", page.locator("#active-provider").inner_text().startswith("Google Gemini API · "))
        # 記録の保存 (ドライブ) の導線が出ているか
        page.wait_for_timeout(800)
        check("設定画面がエラーを出していない",
              not page.locator("#message").inner_text().strip() if page.locator("#message").count() else True,
              page.locator("#message").inner_text()[:60] if page.locator("#message").count() else "")
        check("モデルの選択肢が描けている", page.locator("select[id^=model-]").count() >= 3)

        # 運営者用では解析スクリプトを読まない。押しても動かないボタンを見せない
        page.goto(base + "/privacy"); page.wait_for_load_state("networkidle")
        check("運営者用でアクセス解析の設定ボタンを出さない",
              page.locator("#analytics-reset").count() == 0)
        page.goto(base + "/settings"); page.wait_for_load_state("networkidle")
        check("ドライブの導線が出る", page.locator("#drive-connect").count() == 1)

        # 利用者自身の観察メモ。AIの候補とは別に保存され、再読込でも残る
        page.goto(base + "/history"); page.wait_for_load_state("networkidle")
        note_record = {**json.loads(json.dumps(SAMPLE)), "id": "note-smoke",
                       "createdAt": "2026-08-14T12:00:00Z",
                       "context": {"location": "緯度 35.6812, 経度 139.7671"},
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
        page.locator("#historyMap .leaflet-marker-icon").click()
        page.wait_for_selector(".leaflet-popup .map-popup-record")
        check("地図ピンに代表写真を表示する", page.locator(".leaflet-popup .map-popup-photo").count() == 1)
        check("地図ピンに候補名と写真枚数を表示する", "セイヨウタンポポ" in page.locator(".leaflet-popup").inner_text() and "写真 2枚" in page.locator(".leaflet-popup").inner_text())
        check("現在地へ移動ボタンが表示される", page.locator("#locateMe").is_visible())
        page.click("#locateMe")
        page.wait_for_function("() => document.getElementById('mapLocationState').textContent.includes('移動しました')")
        current_center = page.evaluate("() => { const c=mapInstance.getCenter(); return {lat:c.lat,lng:c.lng} }")
        check("現在地へカーソルを合わせる", abs(current_center["lat"]-35.681236)<0.0001 and abs(current_center["lng"]-139.767125)<0.0001, str(current_center))
        page.wait_for_function("() => [\'mapLandform\',\'mapElevation\',\'mapMicroterrain\',\'mapLandUse\'].every(id => ![\'\',\'調べています…\'].includes(document.getElementById(id).textContent))")
        check("中央地点の5種の土地情報を同時表示する", all(page.locator("#"+value_id).inner_text() not in ["", "調べています…"] for value_id in ["mapLandform", "mapElevation", "mapMicroterrain", "mapLandUse", "mapVegetation"]))
        layer_labels = page.locator(".leaflet-control-layers label")
        labels = layer_labels.all_inner_texts()
        check("観察環境向けの7レイヤを表示する", layer_labels.count() == 7 and all(any(name in label for label in labels) for name in ["地図", "写真", "土地条件", "標高・起伏", "全国微地形", "土地利用", "植生"]), str(labels))
        for layer_name, credit in [("土地条件", "数値地図25000・土地条件"), ("標高・起伏", "陰影起伏図"), ("全国微地形", "J-SHIS"), ("土地利用", "国土数値情報"), ("植生", "現存植生図2024")]:
            layer = page.locator(".leaflet-control-layers label", has_text=layer_name)
            layer.click(); page.wait_for_timeout(500)
            check(layer_name+"レイヤへ切り替えられる", layer.locator('input[type="radio"]').is_checked() and credit in page.locator(".leaflet-control-attribution").inner_text())
            if layer_name == "土地条件":
                land_tiles = page.locator('#historyMap img[src*="/lcm25k_2012/"]').evaluate_all("nodes => nodes.map(node => node.src)")
                check("土地条件の未整備地点を淡色地図で補う", page.locator('#historyMap img[src*="/pale/"]').count() > 0)
                page.wait_for_function("() => performance.getEntriesByType(\'resource\').some(entry => entry.name.includes(\'/experimental_landformclassification1/14/\'))")
                check("土地条件の広域版を補完層として取得する", page.locator("#historyMap .leaflet-landform-pane path").count() > 0)
                page.wait_for_function("() => document.getElementById(\'mapLandform\').textContent !== \'調べています…\'")
                check("中央カーソルを表示する", page.locator(".map-cursor").is_visible())
                cursor_center = page.evaluate("() => { const map = document.getElementById(\'historyMap\').getBoundingClientRect(), cursor = document.querySelector(\'.map-cursor\').getBoundingClientRect(); return {dx: cursor.x + cursor.width / 2 - (map.x + map.width / 2), dy: cursor.y + cursor.height / 2 - (map.y + map.height / 2)} }")
                check("カーソルの中心が地図中央と一致する", abs(cursor_center["dx"]) < 0.01 and abs(cursor_center["dy"]) < 0.01, str(cursor_center))
                check("中央地点の土地条件を表示する", page.locator("#mapLandform").inner_text() not in ["", "調べています…", "この地点のデータはありません"])
                check("土地条件の詳細タイルを上層に表示する", any("/lcm25k_2012/15/" in src for src in land_tiles), str(land_tiles[:3]))
                detail_z = page.locator("#historyMap .leaflet-landDetail-pane").evaluate("node => getComputedStyle(node).zIndex")
                broad_z = page.locator("#historyMap .leaflet-landform-pane").evaluate("node => getComputedStyle(node).zIndex")
                check("詳細土地条件を広域版より上に表示する", int(detail_z) > int(broad_z), str((broad_z, detail_z)))
            if layer_name == "全国微地形":
                page.wait_for_function("() => performance.getEntriesByType('resource').some(entry => entry.name.includes('/map/wms/sstrct/V4'))")
                check("全国微地形レイヤがJ-SHIS WMSを読み込む", page.locator('#historyMap img[src*="/map/wms/sstrct/V4"]').count() > 0)
            if layer_name == "植生":
                check("植生レイヤが環境省の現存植生図2024を読み込む", page.locator('#historyMap img[src*="/webgis/vg2024/MapServer/tile/"]').count() > 0)
            if layer_name == "土地利用":
                check("土地利用レイヤが国土数値情報タイルを読み込む", page.locator('#historyMap img[src*="/ksj/tile/L03-b/L03-b-2016/"]').count() > 0)
            if layer_name == "標高・起伏":
                page.wait_for_function("() => document.getElementById(\'mapElevation\').textContent.endsWith(\' m\')")
                elevation_text = page.locator("#mapElevation").inner_text()
                check("中央地点の標高を0.1m単位で表示する", re.fullmatch(r"-?\d+\.\d m", elevation_text) is not None, elevation_text)
                check("標高・起伏でも背景地図が表示される", page.locator('#historyMap img[src*="tile.openstreetmap.org"]').count() > 0)
        check("標高・起伏レイヤが陰影タイルを読み込む", page.evaluate("() => performance.getEntriesByType('resource').some(entry => entry.name.includes('/hillshademap/'))"))
        page.set_viewport_size({"width": 390, "height": 844})
        summary = page.locator(".summary-grid").bounding_box()
        breakdown_box = page.locator(".breakdown-summary").bounding_box()
        check("ダッシュボードがスマホ幅に収まる", bool(summary) and summary["x"] >= 0 and summary["x"] + summary["width"] <= 390 and bool(breakdown_box) and breakdown_box["x"] + breakdown_box["width"] <= 390, str((summary, breakdown_box)))
        mobile_cursor_center = page.evaluate("() => { const map = document.getElementById(\'historyMap\').getBoundingClientRect(), cursor = document.querySelector(\'.map-cursor\').getBoundingClientRect(); return {dx: cursor.x + cursor.width / 2 - (map.x + map.width / 2), dy: cursor.y + cursor.height / 2 - (map.y + map.height / 2)} }")
        check("スマホでもカーソルの中心が地図中央と一致する", abs(mobile_cursor_center["dx"]) < 0.01 and abs(mobile_cursor_center["dy"]) < 0.01, str(mobile_cursor_center))
        page.set_viewport_size({"width": 1100, "height": 900})
        page.goto(base + "/history"); page.wait_for_load_state("networkidle")
        check("地図を記録ページから移動した", page.locator("#historyMap").count() == 0)
        page.reload(); page.wait_for_load_state("networkidle"); page.wait_for_timeout(500)
        check("手入力した地名は一覧表示に残す", page.evaluate("() => rowLocation({context: {location: \"東京都 高尾山\"}})") == "東京都 高尾山")
        record = page.locator('.entry[data-id="note-smoke"]')
        outside_detail = record.evaluate("node => { const copy = node.cloneNode(true); copy.querySelector('.detail').remove(); return copy.textContent }")
        check("緯度経度を閉じた記録の外側に表示しない", all(value not in outside_detail for value in ["緯度", "経度", "35.6812", "139.7671"]) and "位置の記録あり" not in outside_detail, outside_detail)
        detail = record.locator(".detail")
        check("緯度経度は開くまで見えない", not detail.evaluate("node => node.open") and "35.6812" not in detail.inner_text() and "139.7671" not in detail.inner_text())
        detail.locator("summary").click(); page.wait_for_timeout(300)
        check("記録の内容を開くと緯度経度を表示する", detail.evaluate("node => node.open") and "35.6812" in detail.inner_text() and "139.7671" in detail.inner_text())
        check("記録の候補に写真付きX共有ボタンが1つ出る", detail.locator(".x-share").count() == 1 and detail.locator(".share-record").count() == 0)
        check("押す前はXへ通信しない", not page.evaluate("() => performance.getEntriesByType('resource').some(entry => entry.name.includes('x.com/'))"))
        check("公開前は取り消しボタンを出さない", detail.locator(".share-revoke").count() == 0)
        # 開くタブは掴んでおく。about:blank のまま置き去りにすると、以後の検査が別タブを見る
        page.evaluate("""() => {
            window.openedTargets = [];
            window.open = url => { window.openedTargets.push(url);
                return {location: {replace: target => window.openedTargets.push(target)}, close(){}, opener: null}; };
        }""")
        detail.locator(".x-share").click()
        page.wait_for_function("() => document.querySelector('.share-revoke') !== null", timeout=15000)
        opened = page.evaluate("() => window.openedTargets || []")
        intent = next((url for url in opened if "x.com/intent/tweet" in url), "")
        check("記録の共有がXの投稿画面を開く", bool(intent), str(opened))
        check("投稿画面に共有ページのURLを載せる", "%2Fs%2F" in intent, intent[:160])
        # エンコードされたまま見ると、何を検査しているのか読めない
        posted = unquote_plus(re.search(r"text=([^&]+)", intent).group(1))
        check("投稿本文に候補と特徴が入る",
              "写真から調べた候補" in posted and "ぎざぎざした根生葉" in posted, posted[:120])
        check("投稿本文がアプリ名を名乗る", "「生きものノート」で調べました。" in posted, posted[:120])
        check("投稿本文が候補を断定しない", "結果は候補です。" in posted, posted[:120])
        check("投稿本文に観察メモや緯度経度を入れない",
              "夕方には花が閉じていた" not in posted and "35.6812" not in posted, posted[:160])
        share_url = re.search(r"url=([^&]+)", intent)
        share_page = page.request.get(re.sub(r"%3A", ":", re.sub(r"%2F", "/", share_url.group(1))))
        check("共有ページが開ける", share_page.status == 200, str(share_page.status))
        body = share_page.text()
        check("共有ページにカード用のタグが入る", 'property="og:image"' in body and 'name="twitter:card"' in body)
        check("共有ページに robots の指示を置かない", 'name="robots"' not in body)
        check("共有ページに観察メモと緯度経度を出さない",
              "夕方には花が閉じていた" not in body and "35.6812" not in body)
        check("公開したら取り消しボタンが出る", detail.locator(".share-revoke").count() == 1)
        detail.locator(".share-revoke").click()
        page.wait_for_function("() => document.querySelector('.share-revoke') === null", timeout=15000)
        check("取り消すと公開ページが消える",
              page.request.get(re.sub(r"%3A", ":", re.sub(r"%2F", "/", share_url.group(1)))).status == 404)
        check("取り消しを画面で知らせる", "取り消しました" in detail.locator(".share-message").inner_text(),
              detail.locator(".share-message").inner_text())
        page.set_viewport_size({"width": 390, "height": 844})
        history_share_box = detail.locator(".record-share").bounding_box()
        history_share_button = detail.locator(".x-share").bounding_box()
        check("記録の共有導線がスマホ幅に収まる", bool(history_share_box) and history_share_box["x"] >= 0 and history_share_box["x"] + history_share_box["width"] <= 390, str(history_share_box))
        check("記録の共有ボタンの高さが44px以上", bool(history_share_button) and history_share_button["height"] >= 44, str(history_share_button))
        history_x_button = detail.locator(".x-share").bounding_box()
        check("記録のX共有ボタンの高さが44px以上", bool(history_x_button) and history_x_button["height"] >= 44, str(history_x_button))
        page.set_viewport_size({"width": 1100, "height": 900})
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
        # 中身は本物の JPEG にする。テキストの Blob だと createImageBitmap が通らず、
        # カード用の作り直しが黙って素通しになって、検査が実物と違うものを見る
        page.evaluate("""([sample, encoded]) => {
            const bytes = Uint8Array.from(atob(encoded), c => c.charCodeAt(0));
            const blob = new Blob([bytes], {type: "image/jpeg"});
            render(sample, [blob, blob]);
        }""", [SAMPLE, base64.b64encode(photo("a.jpg")["buffer"]).decode()])
        check("結果が描ける", page.locator(".candidate .name").count() == 1)
        check("参照リンクが並ぶ", page.locator(".sources a").count() >= 2)
        check("安全カードが出る", page.locator("#safetyCard").count() == 1)
        widths = page.eval_on_selector_all(".meter span", "els => els.map(e => e.style.width)")
        check("確信度のメーターに幅が入る", widths == ["60%"], str(widths))


        # X向けは判別写真をOSの共有画面へ渡す。一般共有は従来どおり本文だけ
        check("結果のX共有も押す前は通信しない", not page.evaluate("() => performance.getEntriesByType('resource').some(entry => entry.name.includes('x.com/'))"))
        check("結果の共有ボタンが共有ページを作ると名乗る",
              "共有ページを作り" in page.locator(".share-result").inner_text(),
              page.locator(".share-result").inner_text())
        page.evaluate("""() => {
            window.openedTargets = [];
            window.open = url => { window.openedTargets.push(url);
                return {location: {replace: target => window.openedTargets.push(target)}, close(){}, opener: null}; };
        }""")
        page.locator(".share-result .x-share").click()
        page.wait_for_function("() => (window.openedTargets || []).some(u => u.includes('x.com/intent/tweet'))",
                               timeout=15000)
        intent = next(u for u in page.evaluate("() => window.openedTargets") if "x.com/intent/tweet" in u)
        check("結果の共有がXの投稿画面を開く", bool(intent))
        check("結果の投稿画面に共有ページのURLを載せる", "%2Fs%2F" in intent, intent[:160])
        result_url = re.search(r"url=([^&]+)", intent).group(1).replace("%3A", ":").replace("%2F", "/")
        result_page = page.request.get(result_url)
        check("結果から作った共有ページが開ける", result_page.status == 200, str(result_page.status))
        result_body = result_page.text()
        check("共有ページに候補と特徴が出る",
              "セイヨウタンポポ" in result_body and "ぎざぎざした根生葉" in result_body)
        check("共有ページに観察の要約を出さない", "キク科の草本と考えられます" not in result_body)
        check("共有ページに但し書きを出す", "AI抽出・未確認" in result_body and "結果は候補です" in result_body)
        card_response = page.request.get(result_url + "/photo")
        check("共有ページの写真が配信される", card_response.status == 200)
        # 記録の写真をそのまま渡していた頃、原寸を持たない記録は一覧用の320pxが回り、
        # 幅240でXの最小要件(300)を割ってカードに画像が出なかった
        from io import BytesIO as _BytesIO

        from PIL import Image as _Image

        card_image = _Image.open(_BytesIO(card_response.body()))
        check("共有ページの写真がXのカード寸法", card_image.size == (1200, 630), str(card_image.size))
        check("共有ページの写真がJPEG", card_image.format == "JPEG", str(card_image.format))
        made = page.evaluate("""async () => {
            const canvas = document.createElement("canvas");
            canvas.width = 240; canvas.height = 320;
            const context = canvas.getContext("2d");
            context.fillStyle = "#3a7"; context.fillRect(0, 0, 240, 320);
            const small = await new Promise(resolve => canvas.toBlob(resolve, "image/jpeg", .8));
            const card = await shareCardImage(small);
            const bitmap = await createImageBitmap(card);
            return {width: bitmap.width, height: bitmap.height, type: card.type, bytes: card.size};
        }""")
        check("小さい縦長の写真でもカード寸法に作り直す",
              made["width"] == 1200 and made["height"] == 630, str(made))
        check("カード画像がFirestoreの上限に収まる", made["bytes"] < 700 * 1024, str(made["bytes"]))
        # 日本語は1文字が2文字ぶん。text.length で数えると上限を超えたことに気づけない
        limit_case = page.evaluate("""() => {
            const candidates = [{common_name_ja: "ながいなまえのいきもの", confidence: 60,
                traits: ["とてもながいとくちょうのせつめい".repeat(6), "ふたつめのとくちょう".repeat(6)]}];
            const text = shareBody(candidates);
            return {weight: xWeight(text) + 1 + 23, text,
                    ends: text.endsWith("確かめてください。")};
        }""")
        check("長い特徴でもXの上限に収まる", limit_case["weight"] <= 280, str(limit_case["weight"]))
        check("上限に収めるときも文を途中で切らない", limit_case["ends"], limit_case["text"][-40:])
        page.set_viewport_size({"width": 390, "height": 844})
        share_box = page.locator(".share-result").bounding_box()
        check("共有ボタンがスマホ幅に収まる", bool(share_box) and share_box["x"] >= 0 and share_box["x"] + share_box["width"] <= 390, str(share_box))
        check("結果の共有ボタンが1つだけ", page.locator(".share-result button").count() == 1)
        check("結果のX共有ボタンの高さが44px以上", page.locator(".share-result .x-share").bounding_box()["height"] >= 44)
        page.set_viewport_size({"width": 1100, "height": 900})
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
            # ここまで render() を直接呼ぶ検査しかなく、撮影から識別を通したときに
            # 共有ボタンへ写真が渡るかは誰も見ていなかった。渡っていなければボタンは
            # 「Xで共有」と名乗り、写真なしで X の投稿画面へ落ちる
            share_label = page.locator(".share-result .x-share").inner_text()
            check("識別を通した結果の共有ボタンに写真が渡る", "写真" in share_label, share_label)
            shared = page.evaluate("""() => {
                Object.defineProperty(navigator, "canShare", {configurable: true, value: payload => Boolean(payload.files?.length)});
                Object.defineProperty(navigator, "share", {configurable: true, value: async payload => { window.flowShared = payload; }});
                return true;
            }""")
            page.locator(".share-result .x-share").click()
            page.wait_for_timeout(300)
            flow_share = page.evaluate("() => ({files: window.flowShared?.files?.length || 0, type: window.flowShared?.files?.[0]?.type || ''})")
            check("識別を通した写真がX向け共有画面へ渡る", flow_share["files"] >= 1, str(flow_share))
            page.wait_for_timeout(2500)
            page.goto(base + "/history"); page.wait_for_load_state("networkidle"); page.wait_for_timeout(1500)
            check("記録に残る", page.locator(".entry").count() >= 1)
            check("記録から調べ直せる", page.locator(".again").count() >= 1)

        check("JSエラーが出ない", not errors, "; ".join(errors[:2]))
        context.close(); browser.close()


def run_key_saving(base: str) -> None:
    """公開版で、APIキーを入れて保存を押すと本当に保存されるか。

    公開版のサーバーは Ollama URL を空で返す。既定の Gemini を選んでいる間、
    その入力欄は display:none で隠れるが、隠れても required は効いたままで、
    ブラウザが submit を黙って止めていた。画面には成功も失敗も出ず、押しても
    何も起きないように見える。押して localStorage を覗くまで分からない。
    """
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        context = browser.new_context(viewport={"width": 1100, "height": 900})
        page = context.new_page()
        errors = page_errors(page)

        page.goto(base + "/settings")
        page.wait_for_load_state("networkidle")
        page.locator("[name=provider][value=gemini]").check()
        page.fill("#key-gemini", "smoke-key-abcdef")
        check("隠れた必須欄が保存を止めない",
              page.evaluate("() => document.getElementById('settingsForm').checkValidity()") is True,
              page.evaluate("""() => [...document.querySelectorAll('#settingsForm :invalid')]
                                       .map(el => el.id).join(',')"""))
        page.click("#save-button")
        page.wait_for_timeout(800)
        check("APIキーがこの端末に保存される",
              bool(page.evaluate("""() => sessionStorage.getItem('species-key-gemini')
                                       || localStorage.getItem('species-key-gemini')""")))
        check("保存したことが画面に出る", "保存" in page.locator("#message").inner_text(),
              page.locator("#message").inner_text()[:60])
        check("保存後にキー欄を残さない", page.input_value("#key-gemini") == "")

        # 検証を外すのは選んでいない provider だけ。Ollama を選べば URL は必須に戻る
        page.locator("[name=provider][value=local]").check()
        page.fill("#local-llm-url", "")
        check("Ollamaを選べばURLは必須に戻る",
              page.evaluate("() => document.getElementById('settingsForm').checkValidity()") is False)

        check("公開版の設定画面がJSエラーを出さない", not errors, "; ".join(errors[:2]))
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
    if not args.base and not ADMIN:
        # 公開版でしか起きない壊れ方 (APIキーが黙って保存されない) を見る
        with public_app_for_checking() as public_base:
            print(f"■ {public_base} (公開版)")
            run_key_saving(public_base)
    if failures:
        print(f"\n{len(failures)}件だめでした: {', '.join(failures)}")
        return 1
    print("\nすべて通りました")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
