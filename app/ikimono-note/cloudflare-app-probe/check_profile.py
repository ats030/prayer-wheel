"""Verify local-only I/O comparisons and reuse of the existing API validation."""
import hashlib
import json
from pathlib import Path

from check import fetch as original_fetch

HERE = Path(__file__).resolve().parent
client = 100


def fetch(path, method="GET", data=None, headers=None):
    global client
    client += 1
    return original_fetch(path, method, data, {"X-Forwarded-For": f"192.0.2.{client}", **(headers or {})})


def multipart(files, report):
    boundary = b"synthetic-profile-validation"
    body = bytearray()
    fields = {"request_provider": "gemini", "request_model": "gemini-3.5-flash-lite",
              "request_api_key": "synthetic-key", "client_photos": report}
    for name, value in fields.items():
        body.extend(b"--" + boundary + f'\r\nContent-Disposition: form-data; name="{name}"\r\n\r\n'.encode()
                    + value.encode() + b"\r\n")
    for raw, mime in files:
        body.extend(b"--" + boundary + b'\r\nContent-Disposition: form-data; name="files"; filename="synthetic.jpg"\r\n'
                    + f"Content-Type: {mime}\r\n\r\n".encode() + raw + b"\r\n")
    body.extend(b"--" + boundary + b"--\r\n")
    return bytes(body), {"Content-Type": "multipart/form-data; boundary=" + boundary.decode()}


def check():
    assert fetch("/health")[2]["X-Probe-Profile-IO"] == "1"
    assert fetch("/probe/profile/native-health", headers={"Host": "attacker.invalid"})[0] == 403
    assert fetch("/probe/profile/unknown")[0] == 404
    photo = (HERE / "profile-fixtures/noise.jpg").read_bytes()
    metadata = {"observed_date": "2026-10-07", "latitude": 35.5, "longitude": 139.75}
    measured = {"width": 1600, "height": 1600, "pixels": 2560000,
                "brightness": 128, "sharpness": 200, "contrast": 60}
    report = json.dumps([{"metadata": metadata, "measured": measured}])
    for count in (1, 3):
        body, headers = multipart([(photo, "image/jpeg")] * count, report)
        status, raw, _ = fetch("/probe/profile/native-gemini-payload", "POST", body, headers)
        assert status == 200, raw
        result = json.loads(raw)
        assert result["network_calls"] == 0
        assert result["wire_bytes"] >= count * 4 * ((len(photo) + 2) // 3)
        assert result["probe"]["sha256"] == [hashlib.sha256(photo).hexdigest()] * count
        status, raw, _ = fetch("/probe/profile/native-gemini-payload-checked", "POST", body, headers)
        assert status == 200, raw
        assert json.loads(raw) == result, "Measured payload differs from byte-verified payload"
    for path in ("/identify", "/probe/profile/native-identify"):
        body, headers = multipart([(photo, "image/jpeg")], report)
        status, raw, _ = fetch(path, "POST", body, headers)
        assert status == 200, (path, raw)
        result = json.loads(raw)
        assert result["probe"]["sha256"] == [hashlib.sha256(photo).hexdigest()]
        assert result["photo_metadata"]["observed_date"] == "2026-10-07"
        assert result["photo_metadata"]["latitude"] == 35.5
        body, headers = multipart([(photo, "image/jpeg")] * 3,
                                  json.dumps([{"metadata": metadata, "measured": measured}] * 3))
        status, raw, _ = fetch(path, "POST", body, headers)
        assert status == 200, (path, raw)
        assert json.loads(raw)["probe"]["sha256"] == [hashlib.sha256(photo).hexdigest()] * 3
        for files, reports, expected in (([(photo, "image/jpeg")], "", 400),
                                         ([(photo, "image/jpeg")], "{}", 422),
                                         ([(photo, "text/plain")], report, 415)):
            body, headers = multipart(files, reports)
            assert fetch(path, "POST", body, headers)[0] == expected, (path, reports, expected)
    body, headers = multipart([(photo[:1024], "image/jpeg")] * 4, report)
    assert fetch("/probe/profile/native-identify", "POST", body, headers)[0] == 400
    dark = json.dumps([{"metadata": {}, "measured": {**measured, "brightness": 0}}])
    body, headers = multipart([(photo, "image/jpeg")], dark)
    assert fetch("/probe/profile/native-identify", "POST", body, headers)[0] == 422
    print("PASS: original and native-parsed API hashes/metadata, malformed reports, MIME, count, quality blocks, local-only Host guard")


if __name__ == "__main__":
    check()
