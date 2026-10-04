"""Verify original ZIP selection through real HTTP, IndexedDB and the map; no AI calls."""
import argparse
import hashlib
import io
from pathlib import Path
import zipfile

from playwright.sync_api import sync_playwright
from smoke_browser import app_for_checking
from smoke_photo_location import fixture, records


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--photo", type=Path)
    parser.add_argument("--zip", type=Path, help="Use an archive produced by the Android Java implementation")
    args = parser.parse_args()
    photo = args.photo.read_bytes() if args.photo else fixture()["buffer"]
    name = args.photo.name if args.photo else "photo.jpg"
    archive = io.BytesIO()
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as zipped:
        zipped.writestr(name, photo)
    upload = {"name": "original.zip", "mimeType": "application/zip", "buffer": args.zip.read_bytes() if args.zip else archive.getvalue()}
    with app_for_checking() as (base, _), sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        context = browser.new_context(viewport={"width": 360, "height": 900})
        context.route("**/*", lambda route: route.continue_() if route.request.url.startswith(base) else route.abort())
        page = context.new_page()
        errors = []
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.add_init_script("navigator.geolocation.getCurrentPosition=()=>{throw new Error('unexpected current location')}")
        def wait(expression):
            for _ in range(150):
                if page.evaluate(expression):
                    return
                page.wait_for_timeout(100)
            raise AssertionError(expression)
        page.goto(base)
        wait("typeof selectOriginalZip==='function'")
        assert page.evaluate("async()=>{const {photoFingerprint}=await import('/assets/photo-location.mjs');return photoFingerprint({size:16*1024*1024,arrayBuffer(){throw Error('must not read oversized file')}})}") == "写真が15MBを超えています"
        metadata_requests = []
        def block_metadata(route):
            metadata_requests.append(route.request.url)
            route.abort()
        page.route("**/api/photo-metadata", block_metadata)
        with page.expect_file_chooser() as chooser:
            page.locator("#originalZipBtn").click()
        chooser.value.set_files(upload)
        wait("gps?.source==='exif' && !document.getElementById('originalZipBtn').disabled")
        assert page.locator("#gpsStatus").is_visible()
        assert page.locator("#photoDiagnostic").get_attribute("data-gps-state") == "present"
        assert hashlib.sha256(photo).hexdigest()[:16] in page.locator("#photoDiagnostic").inner_text()
        assert page.evaluate("selected.length") == 1
        assert page.evaluate("selected[0].name") == name
        digest = page.evaluate("async()=>Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256',await selected[0].arrayBuffer()))).map(x=>x.toString(16).padStart(2,'0')).join('')")
        assert digest == hashlib.sha256(photo).hexdigest()
        expected = page.evaluate("({latitude:gps.latitude,longitude:gps.longitude})")
        # Saving uses the existing identification flow, but the AI response is mocked.
        page.route("**/identify", lambda route: route.fulfill(json={"category": "植物", "summary": "zip test", "candidates": []}))
        page.locator("#identify").click()
        wait("lastSavedRecordId!=null && !document.getElementById('identify').disabled")
        saved = records(page)
        assert len(saved) == 1 and saved[0]["coordinates"] == expected
        record_id = saved[0]["id"]
        page.goto(base + "/dashboard")
        wait("document.getElementById('locatedCount').textContent==='1'")
        page.locator("#showMap").click()
        wait("mapInstance!==null")
        points = page.evaluate("Object.values(mapInstance._layers).filter(layer=>layer instanceof L.Marker).map(layer=>layer.getLatLng())")
        assert points == [{"lat": expected["latitude"], "lng": expected["longitude"]}]

        # Repair only the location of an existing record using the same original ZIP.
        page.goto(base + "/history")
        page.evaluate("""async id=>{const db=await openDb(),tx=db.transaction('entries','readwrite'),store=tx.objectStore('entries');
          const record=await request(store.get(id));record.coordinates=null;record.context.location='';
          store.put(record);await finished(tx);db.close()}""", record_id)
        page.reload()
        page.locator(".detail summary").click()
        with page.expect_file_chooser() as chooser:
            page.locator(".location-zip-select").click()
        chooser.value.set_files(upload)
        wait("document.querySelector('.location-message').textContent.includes('保存しました')")
        repaired = page.evaluate("async()=> (await all())[0]")
        assert repaired["coordinates"] == expected
        assert not metadata_requests, metadata_requests
        page.unroute("**/api/photo-metadata", block_metadata)
        assert repaired["summary"] == "zip test" and repaired["id"] == record_id

        page.goto(base)
        page.locator("#originalZip").set_input_files(upload)
        wait("gps?.source==='exif' && !document.getElementById('originalZipBtn').disabled")
        # A distinct File with the same name must not inherit the selected original's GPS.
        result = page.evaluate("""async bytes=>{
          const {readPhotoLocation}=await import('/assets/photo-location.mjs');
          return readPhotoLocation([new File([new Uint8Array(bytes)],selected[0].name,{type:'image/jpeg'})]);
        }""", list(fixture(False)["buffer"]))
        assert "latitude" not in result and "longitude" not in result

        # Old responses without the header retain the existing metadata request.
        legacy_requests = []
        def watch_metadata(route):
            legacy_requests.append(route.request.url)
            route.continue_()
        def legacy_original(route):
            route.fulfill(body=photo, content_type="image/jpeg", headers={"X-Photo-Name": "photo.jpg"})
        page.route("**/api/photo-metadata", watch_metadata)
        page.route("**/api/photo-original", legacy_original)
        page.locator("#originalZip").set_input_files(upload)
        wait("gps?.source==='exif' && !document.getElementById('originalZipBtn').disabled")
        assert len(legacy_requests) == 1
        page.unroute("**/api/photo-metadata", watch_metadata)
        page.unroute("**/api/photo-original", legacy_original)
        page.locator("#originalZip").set_input_files({"name": "bad.zip", "mimeType": "application/zip", "buffer": b"not zip"})
        wait("document.getElementById('status').classList.contains('error')")
        assert page.evaluate("({latitude:gps.latitude,longitude:gps.longitude})") == expected
        assert not page.locator("#identify").is_disabled()

        # A slow ZIP response must not replace a photograph selected in the meantime.
        pending = []
        page.route("**/api/photo-original", lambda route: pending.append(route))
        page.locator("#originalZip").set_input_files(upload)
        for _ in range(100):
            if pending:
                break
            page.wait_for_timeout(100)
        assert pending
        assert page.locator("#identify").is_disabled()
        page.locator("#library").set_input_files(fixture(False))
        wait("gps===null && document.getElementById('gpsStatus').textContent.includes('位置情報を読み取れませんでした')")
        pending.pop().fulfill(body=photo, content_type="image/jpeg", headers={"X-Photo-Name": "late.jpg"})
        wait("!document.getElementById('originalZipBtn').disabled")
        assert page.evaluate("selected[0].name") == "photo.jpg"
        assert page.evaluate("gps") is None
        assert page.locator("#photoDiagnostic").get_attribute("data-gps-state") == "missing"
        assert "GPSタグがありません" in page.locator("#photoDiagnostic").inner_text()
        # Failed metadata requests must not be diagnosed as absent GPS.
        page.route("**/api/photo-metadata", lambda route: route.fulfill(status=401, json={"detail": "ログインしてください"}))
        page.locator("#library").set_input_files(fixture())
        wait("document.getElementById('photoDiagnostic').dataset.gpsState==='request_failed'")
        assert "HTTP 401" in page.locator("#photoDiagnostic").inner_text()
        assert "写真に位置情報がないとは限りません" in page.locator("#gpsStatus").inner_text()
        page.unroute("**/api/photo-metadata")
        # A malformed EXIF response has its own state, without coordinates.
        page.route("**/api/photo-metadata", lambda route: route.fulfill(json={"gps_status": "unreadable"}))
        page.locator("#library").set_input_files(fixture())
        wait("document.getElementById('photoDiagnostic').dataset.gpsState==='unreadable'")
        assert page.evaluate("gps") is None
        assert "GPSタグはありますが" in page.locator("#photoDiagnostic").inner_text()
        page.unroute("**/api/photo-metadata")
        page.locator("#library").set_input_files([fixture(False), fixture()])
        wait("document.getElementById('photoDiagnostic').dataset.gpsState==='present'")
        assert "2枚全体" in page.locator("#photoDiagnostic").inner_text()
        assert "確認コード" not in page.locator("#photoDiagnostic").inner_text()
        for width in (360, 1280):
            page.set_viewport_size({"width": width, "height": 900})
            assert page.locator("#originalZipBtn").is_visible()
            assert page.evaluate("document.documentElement.scrollWidth<=innerWidth")
            page.screenshot(path=f"/tmp/ikimono-zip-{width}.png", full_page=True)
        page.goto(base + "/android-original")
        for width in (360, 1280):
            page.set_viewport_size({"width": width, "height": 900})
            link = page.get_by_role("link", name="補助アプリをダウンロード（0.1.1）")
            assert link.is_visible()
            link.focus()
            assert page.evaluate("document.documentElement.scrollWidth<=innerWidth")
            page.screenshot(path=f"/tmp/ikimono-android-download-{width}.png", full_page=True)
        with page.expect_download() as download:
            link.click()
        assert download.value.suggested_filename == "ikimono-original-0.1.1.apk"
        assert download.value.failure() is None
        assert not errors, errors
        browser.close()
    print("OK: ZIP byte preservation, EXIF, record and map, ZIP location repair, invalid archive, selection race, viewports, APK download")


if __name__ == "__main__":
    main()
