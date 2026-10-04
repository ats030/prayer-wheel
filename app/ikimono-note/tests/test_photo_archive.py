import io
from pathlib import Path
import struct
import sys
import zipfile

from fastapi.testclient import TestClient
from PIL import Image
import pytest

sys.path.insert(0, str(Path(__file__).parents[1]))
import main
import photo_archive
import vision

client = TestClient(main.app, base_url="http://localhost")


@pytest.mark.parametrize("version", ["0.1.0", "0.1.1"])
def test_android_companion_download_is_available_before_login(monkeypatch, version):
    monkeypatch.setattr(main, "PUBLIC_MODE", True)
    monkeypatch.setattr(main.auth, "configured", lambda: True)
    monkeypatch.setattr(main.auth, "read_session", lambda _: None)
    page = client.get("/android-original")
    assert page.status_code == 200
    assert "実機での確認が必要" in page.text
    assert "手動でZIPを作る必要はありません" in page.text
    response = client.get(f"/downloads/ikimono-original-{version}.apk")
    assert response.status_code == 200
    assert response.headers["content-type"] == "application/vnd.android.package-archive"
    assert response.headers["content-disposition"].startswith("attachment;")
    assert response.content == (main.STATIC_DIR / "downloads" / f"ikimono-original-{version}.apk").read_bytes()
    assert client.get("/api/settings").status_code == 401  # No new API access.


def original():
    exif = Image.Exif()
    exif[306] = "2026:10:03 02:54:15"
    exif[34853] = {1: "N", 2: (35., 30., 0.), 3: "E", 4: (139., 30., 0.)}
    out = io.BytesIO()
    Image.new("RGB", (64, 64), "green").save(out, "JPEG", exif=exif)
    return out.getvalue()


def zipped(*files):
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, photo in files:
            archive.writestr(name, photo)
    return out.getvalue()


def post(raw):
    return client.post("/api/photo-original", content=raw, headers={"Content-Type": "application/zip"})


def test_original_zip_keeps_photo_bytes_and_gps():
    photo = original()
    response = post(zipped(("Camera/元写真.jpg", photo), ("__MACOSX/._photo.jpg", b"ignored")))
    assert response.status_code == 200
    assert response.content == photo
    assert response.headers["content-type"] == "image/jpeg"
    assert response.headers["x-photo-name"] == "%E5%85%83%E5%86%99%E7%9C%9F.jpg"
    assert response.headers["cache-control"] == "no-store"
    assert vision.extract_exif_context(response.content) == {
        "observed_date": "2026-10-03", "latitude": 35.5, "longitude": 139.5,
        "location": "緯度 35.5000, 経度 139.5000",
    }


@pytest.mark.parametrize("raw", [
    b"not a zip", zipped(), zipped(("photo.jpg", b"not a photograph")),
    zipped(("a.jpg", original()), ("b.jpg", original())),
    zipped(("../photo.jpg", original())), zipped(("/photo.jpg", original())),
    zipped(("..\\photo.jpg", original())),
    zipped((".", original())), zipped(("x" * 201, original())),
])
def test_invalid_zip_is_rejected(raw):
    assert post(raw).status_code == 415


def test_zip_and_expanded_photo_have_separate_size_limits(monkeypatch):
    monkeypatch.setattr(vision, "MAX_UPLOAD_BYTES", 1024)
    assert post(b"x" * 1025).status_code == 413
    response = post(zipped(("large.jpg", b"x" * 4096)))
    assert response.status_code == 415
    assert "ZIPの中の写真は15MB以下" in response.json()["detail"]


def test_encrypted_and_symlink_entries_are_rejected():
    raw = bytearray(zipped(("photo.jpg", original())))
    # zipfile cannot create encrypted archives; set encryption flags in both headers.
    for signature, offset in ((b"PK\x03\x04", 6), (b"PK\x01\x02", 8)):
        pos = raw.index(signature) + offset
        flags = struct.unpack_from("<H", raw, pos)[0]
        struct.pack_into("<H", raw, pos, flags | 1)
    assert "パスワード" in post(bytes(raw)).json()["detail"]
    info = zipfile.ZipInfo("photo.jpg")
    info.external_attr = 0o120777 << 16
    assert post(zipped((info, original()))).status_code == 415


def test_corrupt_zip_crc_is_rejected():
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_STORED) as archive:
        archive.writestr("photo.jpg", original())
    raw = bytearray(out.getvalue())
    start = 30 + len("photo.jpg")
    raw[start + 100] ^= 1
    assert post(bytes(raw)).status_code == 415


def test_empty_zip_member_name_is_rejected_without_server_error():
    raw = bytearray(zipped(("a", original())))
    raw[30] = 0
    raw[raw.index(b"PK\x01\x02") + 46] = 0
    assert post(bytes(raw)).status_code == 415


def test_zip_requires_login_in_public_mode(monkeypatch):
    monkeypatch.setattr(main, "PUBLIC_MODE", True)
    monkeypatch.setattr(main.auth, "configured", lambda: True)
    monkeypatch.setattr(main.auth, "read_session", lambda cookie: None)
    monkeypatch.setattr(main, "trial_enabled", lambda: False)
    assert post(zipped(("photo.jpg", original()))).status_code == 401


def test_zip_is_rate_limited_in_public_mode(monkeypatch):
    monkeypatch.setattr(main, "PUBLIC_MODE", True)
    monkeypatch.setattr(main.auth, "configured", lambda: False)
    def limited(request, action, maximum):
        assert (action, maximum) == ("original-photo", 10)
        raise main.HTTPException(status_code=429, detail="少し待ってください")
    monkeypatch.setattr(main, "_rate_limit", limited)
    assert post(zipped(("photo.jpg", original()))).status_code == 429


def test_archive_entry_count_and_compression_are_bounded():
    assert post(zipped(*[(f"{index}/", b"") for index in range(65)])).status_code == 415
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_BZIP2) as archive:
        archive.writestr("photo.jpg", original())
    assert post(out.getvalue()).status_code == 415
