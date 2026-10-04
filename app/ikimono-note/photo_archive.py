"""Read one original photograph from a ZIP without writing to disk."""

import io
from pathlib import PurePosixPath
import stat
import zipfile
import zlib

from PIL import Image

import vision


def read_original(raw: bytes) -> tuple[bytes, str, str]:
    limit = vision.MAX_UPLOAD_BYTES
    if len(raw) > limit:
        raise vision.VisionError("ZIPは15MB以下にしてください")
    try:
        with zipfile.ZipFile(io.BytesIO(raw)) as archive:
            entries = archive.infolist()
            if len(entries) > 64:
                raise vision.VisionError("元写真1枚だけをZIPに入れてください")
            if any(not entry.filename for entry in entries):
                raise vision.VisionError("元写真1枚を新しいZIPに入れて選び直してください")
            files = [entry for entry in entries if not entry.is_dir()
                     and not entry.filename.startswith("__MACOSX/")
                     and PurePosixPath(entry.filename).name != ".DS_Store"]
            if len(files) != 1:
                raise vision.VisionError("元写真1枚だけをZIPに入れてください")
            entry = files[0]
            path = PurePosixPath(entry.filename)
            if (not path.name or len(path.name) > 200 or path.is_absolute()
                    or ".." in path.parts or "\\" in entry.filename
                    or stat.S_ISLNK(entry.external_attr >> 16)):
                raise vision.VisionError("元写真1枚を新しいZIPに入れて選び直してください")
            if entry.flag_bits & 1:
                raise vision.VisionError("パスワードのないZIPを選んでください")
            if entry.compress_type not in {zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED}:
                raise vision.VisionError("通常のZIP形式で元写真を圧縮してください")
            if entry.file_size > limit:
                raise vision.VisionError("ZIPの中の写真は15MB以下にしてください")
            # Check both the declared size and the actual bytes read. Never extract paths.
            with archive.open(entry) as source:
                photo = source.read(limit + 1)
            if len(photo) > limit:
                raise vision.VisionError("ZIPの中の写真は15MB以下にしてください")
    except vision.VisionError:
        raise
    except (zipfile.BadZipFile, EOFError, RuntimeError, OSError, ValueError, zlib.error) as exc:
        raise vision.VisionError("ZIPを読み取れませんでした。元写真1枚をZIPに入れて選び直してください") from exc

    # Validation may re-encode a separate copy, but the returned bytes retain original EXIF.
    vision.prepare_image(photo)
    with Image.open(io.BytesIO(photo)) as image:
        mime = Image.MIME.get(image.format, "")
    if not mime.startswith("image/"):
        raise vision.VisionError("対応している形式の写真をZIPに入れてください")
    return photo, path.name, mime
