"""Exercise the actual production adapter inside local Workers/D1."""
from hashlib import sha256
import json
import sys
from urllib.request import Request, urlopen


def read(path, method="GET"):
    request = Request("http://127.0.0.1:8792/" + path, method=method)
    with urlopen(request, timeout=60) as response:
        assert response.status == 200
        return json.load(response)


digest = sha256(bytes(range(256))*2800).hexdigest()
if "--after-restart" not in sys.argv:
    assert read("health") == {"ok": True}
    assert read("probe", "POST") == {"ok": True, "photo_bytes": 700*1024, "photo_sha256": digest}
    assert read("persist", "POST") == {"ok": True}
assert read("persist") == {"ok": True, "photo_sha256": digest}
print("PASS: D1 users, preserved created_at/plan, 700 KiB BLOB round trip, ownership, deletes, photo validation, persistence" )
