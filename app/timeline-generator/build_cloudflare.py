"""Build only operator-approved public timelines, never the application or DB."""
from pathlib import Path
import argparse
import hashlib
import json
import shutil

from publish import ASSETS, build

ROOT = Path(__file__).resolve().parent
PUBLISHED_SNAPSHOT = Path.home() / "cache/timeline-public-build/site"


def build_public(published_snapshot=False):
    output = ROOT / "cloudflare" / "assets"
    if published_snapshot:
        # Migration of the existing publication, not a new source-mode approval.
        # Fixed archived paths were published under ats030-udy41; no user URL or DB input.
        expected = {"index.html", *ASSETS, "showa/index.html"}
        hashes = json.loads((ROOT / "cloudflare" / "published-snapshot-sha256.json").read_text())
        if set(hashes) != expected:
            raise ValueError("Published snapshot manifest changed")
        bodies = {}
        for name in sorted(expected):
            source = PUBLISHED_SNAPSHOT / name
            if source.is_symlink() or not source.is_file() or source.stat().st_size > 2_000_000:
                raise ValueError("Published snapshot asset missing or invalid")
            bodies[name] = source.read_bytes()
            if hashlib.sha256(bodies[name]).hexdigest() != hashes[name]:
                raise ValueError("Published snapshot content changed")
        if output.exists():
            shutil.rmtree(output)
        output.mkdir(parents=True)
        for name, body in bodies.items():
            path = output / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(body)
        count = 1
    else:
        records = build(output)
        expected = {"index.html", *ASSETS, *(r["slug"] + "/index.html" for r in records)}
        count = len(records)
    actual = {p.relative_to(output).as_posix() for p in output.rglob("*") if p.is_file()}
    if actual != expected:
        raise ValueError("Unexpected public build files")
    for path in output.rglob("*.html"):
        html = path.read_text()
        if "<script" in html.lower() or "ubuntu-server-app" in html or "<form" in html.lower():
            raise ValueError("Public build contains active application content")
    shutil.copyfile(ROOT / "cloudflare" / "headers.txt", output / "_headers")
    print(f"Built {count} published timelines, {len(expected)} public files")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--published-snapshot", action="store_true",
                        help="Copy the fixed archived Cloud Run publication; does not approve new records")
    build_public(parser.parse_args().published_snapshot)
