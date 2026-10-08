"""Verify actual Workers responses, including expected native-thread failure."""
import json
from urllib.request import urlopen


def read(path):
    with urlopen(f"http://127.0.0.1:8788/{path}", timeout=20) as response:
        assert response.status == 200
        return json.load(response)


for path in ("health", "sync-health", "threadpool"):
    assert read(path) == {"ok": True}, path
for mode in ("sync", "async"):
    assert read(f"probe/{mode}") == {"ok": True, "status": 200,
                                     "example_domain": True}, mode
for kind, content_type in (("json", "application/json"),
                           ("form", "application/x-www-form-urlencoded"),
                           ("multipart", "multipart/form-data; boundary=")):
    result = read(f"post/{kind}")
    assert result["ok"] and result["content_type"].startswith(content_type), result
    if kind == "json":
        assert json.loads(result["body"]) == {"probe": "synthetic"}
    elif kind == "form":
        assert result["body"] == "probe=synthetic"
    else:
        for expected in ('name="images"; filename="probe.jpg"',
                         "Content-Type: image/jpeg", "synthetic-photo"):
            assert expected in result["body"], result
result = read("native-thread")
assert result == {"ok": False, "error_type": "RuntimeError",
                  "error": "can't start new thread"}, result
assert read("probe/invalid") == {"ok": False, "error": "unknown mode"}
assert read("post/invalid") == {"ok": False, "error": "unknown kind"}
print("PASS: HTTP GET/POST, multipart, sync routes, inline threadpool, native-thread boundary")
