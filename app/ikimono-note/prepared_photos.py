"""Bound client-prepared JPEGs and measurements without decoding pixels.

Measurements are supplied by the caller, not an attestation of image quality.
The original server path keeps measuring its own pixels. The Workers profile
uses browser measurements for the same user-facing quality guidance.
"""
import json
import math
import re

import image_quality
import vision

MAX_PREPARED_BYTES = 2 * 1024 * 1024


def jpeg_dimensions(raw: bytes) -> tuple[int, int]:
    """Validate a bounded JPEG header; this does not fully decode entropy data."""
    if (not raw or len(raw) > MAX_PREPARED_BYTES or not raw.startswith(b"\xff\xd8")
            or not raw.endswith(b"\xff\xd9")):
        raise vision.VisionError("写真の送信形式を確認してください。写真を選び直してください。")
    cursor, dimensions = 2, None
    for _ in range(128):
        if cursor + 4 > min(len(raw), 65536) or raw[cursor] != 255:
            break
        while cursor < len(raw) and raw[cursor] == 255:
            cursor += 1
        if cursor + 3 > len(raw):
            break
        marker = raw[cursor]
        cursor += 1
        length = int.from_bytes(raw[cursor:cursor+2], "big")
        if length < 2 or cursor + length > min(len(raw), 65536):
            break
        # JPEG encoders may write JFIF or ICC. Never forward EXIF/IPTC/comments.
        if marker == 0xfe or (0xe0 <= marker <= 0xef and marker not in {0xe0, 0xe2}):
            break
        if marker in {0xc0, 0xc2}:
            if dimensions is not None or length != 17 or raw[cursor+2] != 8 or raw[cursor+7] != 3:
                break
            height = int.from_bytes(raw[cursor+3:cursor+5], "big")
            width = int.from_bytes(raw[cursor+5:cursor+7], "big")
            if not (1 <= width <= 1600 and 1 <= height <= 1600):
                break
            dimensions = (width, height)
        if marker == 0xda:
            if dimensions and length >= 6:
                return dimensions
            break
        cursor += length
    raise vision.VisionError("写真の送信形式を確認してください。写真を選び直してください。")


def read_reports(serialized: str, count: int) -> tuple[dict, list[dict]]:
    """Accept only finite, bounded source measurements and capture fields."""
    try:
        if len(serialized) > 8192:
            raise ValueError()
        reports = json.loads(serialized)
        if not isinstance(reports, list) or len(reports) != count or not 1 <= count <= 3:
            raise ValueError()
        combined, qualities = {}, []
        for report in reports:
            if not isinstance(report, dict) or set(report) != {"metadata", "measured"}:
                raise ValueError()
            measured, metadata = report["measured"], report["metadata"]
            if not isinstance(measured, dict) or set(measured) != {
                "width", "height", "pixels", "brightness", "sharpness", "contrast"
            }:
                raise ValueError()
            if any(type(measured[key]) is not int or not 1 <= measured[key] <= 16384 for key in ("width", "height")):
                raise ValueError()
            if type(measured["pixels"]) is not int or measured["pixels"] != measured["width"] * measured["height"] or measured["pixels"] > 50_000_000:
                raise ValueError()
            for key, maximum in (("brightness", 255), ("sharpness", 1_040_400), ("contrast", 128)):
                if type(measured[key]) not in {int, float} or not math.isfinite(measured[key]) or not 0 <= measured[key] <= maximum:
                    raise ValueError()
            if not isinstance(metadata, dict) or set(metadata) - {"observed_date", "latitude", "longitude", "location", "gps_status"}:
                raise ValueError()
            clean = {}
            if "observed_date" in metadata:
                value = metadata["observed_date"]
                if not isinstance(value, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
                    raise ValueError()
                clean["observed_date"] = value
            if "latitude" in metadata or "longitude" in metadata:
                for key, bound in (("latitude", 90), ("longitude", 180)):
                    value = metadata.get(key)
                    if type(value) not in {int, float} or not math.isfinite(value) or abs(value) > bound:
                        raise ValueError()
                    clean[key] = round(value, 4)
                clean["location"] = f"緯度 {clean['latitude']:.4f}, 経度 {clean['longitude']:.4f}"
            if "gps_status" in metadata:
                if metadata["gps_status"] not in {"unreadable", "exif_unreadable"}:
                    raise ValueError()
                clean["gps_status"] = metadata["gps_status"]
            for key, value in clean.items():
                combined.setdefault(key, value)
            qualities.append(image_quality.judge_measured(measured))
        return combined, qualities
    except (ValueError, TypeError, KeyError, OverflowError) as error:
        raise vision.VisionError("写真の情報を読み取れませんでした。写真を選び直してください。") from error
