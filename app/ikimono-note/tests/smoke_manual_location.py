"""Browser verification of normal photos, manual locations and persisted map markers; no AI calls."""
from playwright.sync_api import sync_playwright
from smoke_browser import app_for_checking
from smoke_photo_location import fixture, records


def main():
    with app_for_checking() as (base, _), sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        context = browser.new_context(viewport={'width': 360, 'height': 900})
        context.route('**/*', lambda route: route.continue_() if route.request.url.startswith(base) else route.abort())
        page = context.new_page()
        errors = []
        page.on('pageerror', lambda error: errors.append(str(error)))
        page.add_init_script("""window.locationCalls=0;window.locationCallbacks=[];
          navigator.geolocation.getCurrentPosition=(success,error)=>{locationCalls++;locationCallbacks.push({success,error})};""")
        def wait(expression):
            for _ in range(150):
                if page.evaluate(expression):
                    return
                page.wait_for_timeout(100)
            raise AssertionError(expression)
        page.goto(base)
        wait('captureLocationPicker!==null')
        assert page.locator('#originalZipBtn,#originalFileBtn').count() == 0
        page.locator('#library').set_input_files(fixture(False))
        wait("document.querySelector('#photoDiagnostic').dataset.gpsState==='missing'")
        assert page.evaluate('locationCalls') == 0
        assert page.evaluate("!window.L")
        root = page.locator('#captureLocation')
        root.locator('[data-map-open]').click()
        wait('captureLocationPicker.map!==null')
        assert root.locator('[data-map-use]').is_disabled(), 'Japan default center is not a chosen shooting location'
        # Simulates a map tap and validates the actual Leaflet event path.
        page.evaluate("captureLocationPicker.map.fire('click',{latlng:L.latLng(35.123456,137.654321)})")
        root.locator('[data-map-use]').click()
        wait("gps?.source==='map'")
        expected = {'latitude': 35.1235, 'longitude': 137.6543}
        assert page.evaluate('({latitude:gps.latitude,longitude:gps.longitude})') == expected
        assert page.locator('#location').input_value().startswith('地図で指定：')
        for width in (360,1280):
            page.set_viewport_size({'width':width,'height':900})
            root.locator('[data-map-open]').click()
            root.locator('[data-map-use]').wait_for(state='visible')
            assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
            page.screenshot(path=f'/tmp/ikimono-capture-location-{width}.png',full_page=True)
            root.locator('[data-map-close]').click()
        page.route('**/identify', lambda route: route.fulfill(json={'category': '植物', 'summary': 'manual place', 'candidates': []}))
        page.locator('#identify').click()
        wait("lastSavedRecordId!=null&&!document.getElementById('identify').disabled")
        assert records(page)[0]['coordinates'] == expected
        page.goto(base+'/dashboard')
        wait("document.getElementById('locatedCount').textContent==='1'")
        page.locator('#showMap').click()
        wait('mapInstance!==null')
        points = page.evaluate('Object.values(mapInstance._layers).filter(layer=>layer instanceof L.Marker).map(layer=>layer.getLatLng())')
        assert points == [{'lat': expected['latitude'], 'lng': expected['longitude']}]
        page.goto(base)
        wait('captureLocationPicker!==null')
        # Explicit current location is rounded, and a new selection invalidates delayed callbacks.
        page.locator('#library').set_input_files(fixture(False))
        wait("document.querySelector('#photoDiagnostic').dataset.gpsState==='missing'")
        root.locator('[data-current]').click()
        page.evaluate("locationCallbacks.pop().success({coords:{latitude:34.123456,longitude:135.123456,accuracy:7}})")
        wait("gps?.source==='current'")
        assert page.evaluate('gps.latitude') == 34.1235
        assert page.locator('#location').input_value().startswith('現在地を使用：')
        page.locator('#library').set_input_files(fixture(False))
        wait("gps===null&&document.querySelector('#photoDiagnostic').dataset.gpsState==='missing'")
        assert page.locator('#location').input_value() == ''
        root.locator('[data-current]').click()
        page.locator('#library').set_input_files(fixture(False))
        page.evaluate("locationCallbacks.pop().success({coords:{latitude:1,longitude:2,accuracy:5}})")
        wait("document.querySelector('#photoDiagnostic').dataset.gpsState==='missing'")
        assert page.evaluate('gps') is None
        root.locator('[data-current]').click()
        page.evaluate('locationCallbacks.pop().error({code:1})')
        assert '許可されていません' in root.locator('[role=status]').inner_text()
        assert not root.locator('[data-current]').is_disabled()
        # Slow EXIF must not overwrite explicit location, including request failures.
        held = []
        page.route('**/api/photo-metadata', lambda route: held.append(route))
        page.locator('#library').set_input_files(fixture())
        wait("document.querySelector('#photoDiagnostic').dataset.gpsState==='reading'")
        root.locator('[data-current]').click()
        page.evaluate("locationCallbacks.pop().success({coords:{latitude:33.555555,longitude:133.555555,accuracy:5}})")
        wait("gps?.source==='current'")
        for _ in range(100):
            if held: break
            page.wait_for_timeout(100)
        assert held
        held.pop().fulfill(json={'latitude':35.5,'longitude':139.5,'observed_date':'2026-09-05'})
        wait("document.querySelector('#photoDiagnostic').dataset.gpsState==='present'")
        assert page.evaluate('gps.latitude') == 33.5556
        page.locator('#identify').click()
        wait("!document.getElementById('identify').disabled")
        assert any(record['coordinates']['latitude']==33.5556 for record in records(page))
        page.locator('#library').set_input_files(fixture(False))
        root.locator('[data-current]').click()
        page.evaluate("locationCallbacks.pop().success({coords:{latitude:32.123456,longitude:132.123456,accuracy:5}})")
        for _ in range(100):
            if held: break
            page.wait_for_timeout(100)
        assert held
        held.pop().abort()
        wait("document.querySelector('#photoDiagnostic').dataset.gpsState==='request_failed'")
        assert page.evaluate('gps.latitude') == 32.1235
        page.unroute('**/api/photo-metadata')
        # Existing record: replacement cancelled then accepted, with other fields preserved.
        page.goto(base+'/history')
        page.locator('.detail summary').first.click()
        box=page.locator('.photo-location').first
        box.locator('.location-manual').click()
        wait("document.querySelector('.history-location-picker [data-current]')!==null")
        before=page.evaluate('async()=> (await all())[0]')
        page.once('dialog', lambda dialog: dialog.dismiss())
        box.locator('[data-current]').click()
        page.evaluate("locationCallbacks.pop().success({coords:{latitude:30,longitude:130,accuracy:10}})")
        wait("document.querySelector('.history-location-picker [role=status]').textContent==='場所は変更していません。'")
        assert page.evaluate('async()=> (await all())[0]') == before
        page.once('dialog', lambda dialog: dialog.accept())
        box.locator('[data-current]').click()
        page.evaluate("locationCallbacks.pop().success({coords:{latitude:30.123456,longitude:130.123456,accuracy:10}})")
        wait("document.querySelector('.location-message').textContent.includes('保存しました')")
        after=page.evaluate('async()=> (await all())[0]')
        assert after['coordinates']=={'latitude':30.1235,'longitude':130.1235}
        for key in ('id','createdAt','summary','candidates','thumbnail','resultMeta'):
            assert after.get(key)==before.get(key)
        assert after['context']['location'].startswith('現在地を使用：')
        for width in (360,1280):
            page.set_viewport_size({'width':width,'height':900})
            box.locator('[data-map-open]').click()
            assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
            box.locator('[data-map-use]').wait_for(state='visible')
            page.screenshot(path=f'/tmp/ikimono-manual-location-{width}.png',full_page=True)
            box.locator('[data-map-close]').click()
        assert not errors, errors
        browser.close()
    print('OK: no helper/ZIP, explicit map/current location, round/save/map, selection and EXIF races, permission denied, history replacement, 360/1280')


if __name__=='__main__':
    main()
