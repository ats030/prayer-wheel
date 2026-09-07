"""写真の位置を実ブラウザとIndexedDBで検証。外部AIは呼ばない。

  python tests/smoke_photo_location.py [--photo 元写真.jpg]
"""
import argparse
import io
from pathlib import Path

from PIL import Image
from playwright.sync_api import sync_playwright
from smoke_browser import app_for_checking


def fixture(gps=True):
    image = Image.new("RGB", (64, 64), "green")
    exif = Image.Exif()
    exif[36867] = "2026:09:05 07:48:31"
    if gps:
        exif[34853] = {1: "N", 2: (35., 30., 0.), 3: "E", 4: (139., 30., 0.)}
    out = io.BytesIO()
    image.save(out, "JPEG", exif=exif)
    return {"name": "photo.jpg", "mimeType": "image/jpeg", "buffer": out.getvalue()}


def records(page):
    return page.evaluate("async()=>{const db=await historyDb();return await requestValue(db.transaction('entries').objectStore('entries').getAll())}")


def main():
    args = argparse.ArgumentParser()
    args.add_argument("--photo", type=Path)
    options = args.parse_args()
    with app_for_checking() as (base, _), sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        context = browser.new_context()
        # 地図タイル、広告、AIなどの外部通信は行わない。
        context.route("**/*", lambda route: route.continue_() if route.request.url.startswith(base) else route.abort())
        page = context.new_page()
        # wait_for_function内のevalはアプリのCSPに遮断されるため、CDPでポーリングする。
        def wait(expression):
            for _ in range(150):
                if page.evaluate(expression):
                    return
                page.wait_for_timeout(100)
            raise AssertionError(expression + '\n' + page.locator('body').inner_text()[:1200])
        page.wait_for_function = wait
        errors = []
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.add_init_script("navigator.geolocation.getCurrentPosition=()=>{throw new Error('unexpected current location')}")
        page.goto(base)
        page.wait_for_function("typeof setFiles==='function'")
        photo = str(options.photo) if options.photo else fixture()
        page.locator("#library").set_input_files(photo)
        page.wait_for_function("gps?.source==='exif'")
        expected = page.evaluate("({latitude:gps.latitude,longitude:gps.longitude})")

        # 識別を待機させ、写真を選び直しても保存対象が混ざらないことを確認する。
        pending = []
        page.route("**/identify", lambda route: pending.append(route))
        metadata_pending = []
        page.route("**/api/photo-metadata", lambda route: metadata_pending.append(route))
        page.locator("#library").set_input_files(photo)
        page.locator("#identify").click()
        page.wait_for_timeout(300)
        assert not pending, "写真の位置情報の読取前に識別を始めている"
        assert metadata_pending
        metadata_pending.pop().fulfill(json={**expected, "observed_date": "2026-09-05"})
        page.unroute("**/api/photo-metadata")
        page.wait_for_function("document.getElementById('identify').disabled")
        for _ in range(100):
            if pending:
                break
            page.wait_for_timeout(100)
        assert pending, "識別のリクエストが来ない"
        page.locator("#library").set_input_files(fixture(False))
        page.wait_for_function("gps===null && document.getElementById('gpsStatus').textContent.includes('残っていません')")
        pending.pop().fulfill(json={"category": "植物", "summary": "test", "candidates": []})
        page.wait_for_function("lastSavedRecordId!==null && lastSavedRecordId!==undefined")
        saved = records(page)
        assert len(saved) == 1 and saved[0]["coordinates"] == expected
        assert saved[0]["context"]["location"].startswith("緯度 ")

        # 位置がない写真で、前の座標・自動入力を残さない。
        assert page.locator("#location").input_value() == ""
        page.locator("#library").set_input_files(photo)
        page.wait_for_function("gps?.source==='exif'")
        page.route("**/api/photo-metadata", lambda route: route.fulfill(status=503, json={}))
        page.locator("#library").set_input_files(fixture(False))
        page.wait_for_function("document.getElementById('gpsStatus').textContent.includes('読み取れません')")
        assert page.evaluate("gps") is None and page.locator("#location").input_value() == ""
        page.unroute("**/api/photo-metadata")

        # 空の既存記録に位置だけを補う。写真・識別結果・観察メモは保持する。
        page.evaluate("""async()=>{
          const db=await historyDb(),tx=db.transaction('entries','readwrite');
          tx.objectStore('entries').clear();
          tx.objectStore('entries').put({id:'repair',createdAt:'2026-09-05T00:00:00Z',
            context:{size:'5cm',observedDate:'2026-09-05'},coordinates:null,
            summary:'keep summary',userNote:'keep note',candidates:[]});
          await transactionDone(tx);
        }""")
        page.goto(base + "/history")
        page.locator(".detail summary").click()
        field = page.locator(".location-photo")
        field.set_input_files(photo)
        page.wait_for_function("document.querySelector('.location-message').textContent.includes('保存しました')")
        record = page.evaluate("async()=> (await all())[0]")
        assert record["coordinates"] == expected
        assert record["userNote"] == "keep note" and record["summary"] == "keep summary"
        assert record["context"]["size"] == "5cm" and record["createdAt"] == "2026-09-05T00:00:00Z"

        # 既存場所の置換は拒否・承認の両方を検証する。
        page.evaluate("""async()=>{const db=await openDb(),tx=db.transaction('entries','readwrite'),s=tx.objectStore('entries');
          const r=await request(s.get('repair'));r.context.location='手入力の場所';s.put(r);await finished(tx)}""")
        page.once("dialog", lambda dialog: dialog.dismiss())
        field.set_input_files(photo)
        page.wait_for_function("document.querySelector('.location-message').textContent==='場所は変更していません。'")
        assert page.evaluate("async()=> (await all())[0].context.location") == "手入力の場所"
        page.once("dialog", lambda dialog: dialog.accept())
        field.set_input_files(photo)
        page.wait_for_function("document.querySelector('.location-message').textContent.includes('保存しました')")
        field.set_input_files(fixture(False))
        page.wait_for_function("document.querySelector('.location-message').textContent.includes('位置情報がありません')")
        assert page.evaluate("async()=> (await all())[0].coordinates") == expected

        page.goto(base + "/dashboard")
        page.wait_for_function("document.getElementById('locatedCount').textContent==='1'")
        page.locator("#showMap").click()
        page.wait_for_function("mapInstance!==null")
        points = page.evaluate("Object.values(mapInstance._layers).filter(layer=>layer instanceof L.Marker).map(layer=>layer.getLatLng())")
        assert points == [{"lat": expected["latitude"], "lng": expected["longitude"]}]
        page.goto(base + "/history")
        page.locator(".detail summary").click()
        field = page.locator(".location-photo")

        # 読取中に削除されても記録を復活させない。
        page.evaluate("async()=>{const db=await openDb(),tx=db.transaction('entries','readwrite');tx.objectStore('entries').delete('repair');await finished(tx)}")
        field.set_input_files(photo)
        page.wait_for_function("document.querySelector('.location-message').textContent.includes('見つかりません')")
        assert page.evaluate("async()=> (await all()).length") == 0
        assert not errors, errors
        browser.close()
    print("OK: EXIF read, selection isolation, missing/failed GPS, history repair, overwrite confirmation, deleted record")


if __name__ == "__main__":
    main()
