"""Verify the retained ZIP compatibility API/module, without the removed ZIP UI."""
import argparse
import base64
import hashlib
import io
from pathlib import Path
import zipfile
from playwright.sync_api import sync_playwright
from smoke_browser import app_for_checking
from smoke_photo_location import fixture


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--photo',type=Path)
    parser.add_argument('--zip',type=Path)
    args=parser.parse_args()
    photo=args.photo.read_bytes() if args.photo else fixture()['buffer']
    name=args.photo.name if args.photo else 'photo.jpg'
    archive=io.BytesIO()
    with zipfile.ZipFile(archive,'w',zipfile.ZIP_STORED) as zipped:
        zipped.writestr(name,photo)
    upload={'name':'original.zip','mimeType':'application/zip','buffer':args.zip.read_bytes() if args.zip else archive.getvalue()}
    with app_for_checking() as (base,_),sync_playwright() as playwright:
        browser=playwright.chromium.launch(headless=True)
        page=browser.new_page()
        page.route('**/*',lambda route: route.continue_() if route.request.url.startswith(base) else route.abort())
        page.goto(base)
        # A compatibility caller may still use the module, but the normal UI has no ZIP entry.
        assert page.locator('#originalZipBtn').count()==0
        page.evaluate("data=>{window.zipInput=new File([Uint8Array.from(atob(data),c=>c.charCodeAt(0))],'original.zip',{type:'application/zip'})}",base64.b64encode(upload['buffer']).decode())
        calls=[]
        page.route('**/api/photo-metadata',lambda route:(calls.append(route.request.url),route.abort()))
        result=page.evaluate("""async()=>{
          const m=await import('/assets/photo-location.mjs');
          const photo=await m.readOriginalZip(zipInput);
          window.compatPhoto=photo;
          return {name:photo.name,code:await m.photoFingerprint(photo),data:await m.readPhotoLocation([photo])};
        }""")
        assert result['name']==name
        assert result['code']==hashlib.sha256(photo).hexdigest()[:16]
        assert 'latitude' in result['data']
        assert not calls
        # Same name is not enough to reuse cached metadata.
        try:
            page.evaluate("async()=>{const m=await import('/assets/photo-location.mjs');return m.readPhotoLocation([new File([new Uint8Array([1])],compatPhoto.name,{type:'image/jpeg'})])}")
        except Exception:
            pass
        assert len(calls)==1
        page.unroute('**/api/photo-metadata')
        # Older ZIP responses (no header) retain the metadata-request fallback.
        page.route('**/api/photo-original',lambda route:route.fulfill(body=photo,content_type='image/jpeg',headers={'X-Photo-Name':name}))
        result=page.evaluate("async()=>{const m=await import('/assets/photo-location.mjs');return m.readPhotoLocation([await m.readOriginalZip(zipInput)])}")
        assert 'latitude' in result
        page.unroute('**/api/photo-original')
        error=page.evaluate("async()=>{try{const m=await import('/assets/photo-location.mjs');await m.readOriginalZip(new File(['not zip'],'bad.zip',{type:'application/zip'}));return ''}catch(e){return e.message}}")
        assert error
        browser.close()
    print('OK: retained ZIP API/module byte preservation, EXIF header reuse, File identity, old-response fallback, invalid archive')


if __name__=='__main__':
    main()
