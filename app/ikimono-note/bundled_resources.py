"""Read application resources from disk locally or an explicit Workers bundle."""
from pathlib import Path
import hashlib
import os
import secrets

from starlette.exceptions import HTTPException
from starlette.datastructures import Headers
from starlette.responses import FileResponse, Response
from starlette.staticfiles import StaticFiles

ROOT = Path(__file__).parent
_embedded: dict[str, bytes] | None = None
_etags: dict[str, str] = {}
_TYPES = {
    ".css": "text/css", ".js": "text/javascript", ".mjs": "text/javascript",
    ".png": "image/png", ".svg": "image/svg+xml", ".txt": "text/plain",
    ".xml": "application/xml", ".apk": "application/vnd.android.package-archive",
}


def configure(resources: dict[str, bytes]) -> None:
    """Called once, before importing main, by the Workers entrypoint."""
    global _embedded
    _embedded = resources
    _etags.clear()
    _etags.update({name: '"' + hashlib.sha256(content).hexdigest() + '"'
                  for name, content in resources.items()})


def read_text(path: Path) -> str:
    if _embedded is None:
        return path.read_text(encoding="utf-8")
    return _embedded[path.relative_to(ROOT).as_posix()].decode("utf-8")


def file_response(path: Path, **kwargs) -> Response:
    if _embedded is None:
        return FileResponse(path, **kwargs)
    key = path.relative_to(ROOT).as_posix()
    if key not in _embedded:
        raise HTTPException(404)
    headers = dict(kwargs.pop("headers", None) or {})
    headers.setdefault("ETag", _etags[key])
    return EmbeddedFileResponse(path, _embedded[key], headers=headers, **kwargs)


class EmbeddedFileResponse(FileResponse):
    """Keep Starlette's Range/If-Range handling, replacing only file I/O."""

    def __init__(self, path, content: bytes, **kwargs):
        self.content = content
        headers = dict(kwargs.pop("headers", None) or {})
        # Bundled files have no filesystem mtime. Omit Last-Modified rather than
        # presenting a made-up build date; content ETag supports If-Range.
        super().__init__(path, stat_result=os.stat_result((0o100644, 0, 0, 1, 0, 0,
                                                         len(content), 0, 0, 0)),
                         headers=headers, **kwargs)
        del self.headers["last-modified"]

    def _should_use_range(self, value):
        return value == self.headers["etag"]

    async def _handle_simple(self, send, send_header_only, send_pathsend):
        await send({"type": "http.response.start", "status": self.status_code, "headers": self.raw_headers})
        await send({"type": "http.response.body", "body": b"" if send_header_only else self.content})

    async def _handle_single_range(self, send, start, end, file_size, send_header_only):
        headers = dict(self.headers)
        headers["content-range"] = f"bytes {start}-{end-1}/{file_size}"
        headers["content-length"] = str(end-start)
        response = Response(b"" if send_header_only else self.content[start:end],
                            status_code=206, headers=headers)
        await send({"type": "http.response.start", "status": 206, "headers": response.raw_headers})
        await send({"type": "http.response.body", "body": response.body})

    async def _handle_multiple_ranges(self, send, ranges, file_size, send_header_only):
        boundary = secrets.token_hex(13)
        length, part_header = self.generate_multipart(ranges, boundary, file_size, self.headers["content-type"])
        headers = dict(self.headers)
        headers["content-type"] = f"multipart/byteranges; boundary={boundary}"
        headers["content-length"] = str(length)
        body = b"" if send_header_only else (
            b"".join(part_header(start, end) + self.content[start:end] + b"\r\n" for start, end in ranges)
            + f"--{boundary}--".encode())
        response = Response(body, status_code=206, headers=headers)
        await send({"type": "http.response.start", "status": 206, "headers": response.raw_headers})
        await send({"type": "http.response.body", "body": body})


def static_files(directory: Path):
    if _embedded is None:
        return StaticFiles(directory=directory)
    prefix = directory.relative_to(ROOT).as_posix() + "/"

    async def serve(scope, receive, send):
        if scope["method"] not in {"GET", "HEAD"}:
            response = Response(status_code=405, headers={"Allow": "GET, HEAD"})
        else:
            # ASGI mount keeps the full path and sets root_path. Exact membership
            # rejects traversal and directory listings without filesystem access.
            path = scope["path"][len(scope.get("root_path", "")):].lstrip("/")
            key = prefix + path
            if key not in _embedded:
                response = Response(status_code=404)
            else:
                content = _embedded[key]
                response = Response(
                    content if scope["method"] == "GET" else b"",
                    media_type=_TYPES.get(Path(key).suffix, "application/octet-stream"),
                    headers={"Content-Length": str(len(content)), "ETag": _etags[key]},
                )
                if StaticFiles.is_not_modified(None, response.headers, Headers(scope=scope)):
                    response = Response(status_code=304, headers={"ETag": _etags[key]})
        await response(scope, receive, send)

    return serve
