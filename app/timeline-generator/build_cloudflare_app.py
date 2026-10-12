"""Build the shared UI and only the hash-verified existing public publication."""
import hashlib
from html.parser import HTMLParser
import json
from pathlib import Path
import re
import shutil
import tempfile
from urllib.parse import urlsplit

from build_cloudflare import PUBLISHED_SNAPSHOT, ROOT

FILES = ("index.html", "detail.html", "library.html", "quality.html", "changelog.html",
         "app.js", "local-library.js", "styles.css", "tokens.css", "favicon.svg")
LOCAL_LOG = '<script src="http://ubuntu-server-app:8526/v.js" data-site="timeline-generator" defer></script>'
NOTICE = "既存の公開年表を移行したものです。現在の出典方式の検証を新たに通過した結果ではありません。各出来事の題名と説明は、生成AIがWikipedia（日本語版・英語版）の記事をもとに要約・改変したものです。CC BY-SA 4.0（https://creativecommons.org/licenses/by-sa/4.0/deed.ja）で提供します。原文の著者は各出典記事の履歴を参照してください。気になる出来事は出典も確認してください。"


class PublishedEvents(HTMLParser):
    """Extract displayed fields only; never read unpublished source JSON or databases."""
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.events = []
        self.event = None
        self.field = None
        self.text = []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        class_name = attrs.get("class")
        if tag == "li" and class_name == "event":
            self.event = {}
        if self.event is None:
            return
        if class_name in ("event-date", "event-title", "event-description"):
            self.field = {"event-date": "date", "event-title": "title", "event-description": "description"}[class_name]
            self.text = []
        if tag == "a" and class_name == "source-link":
            url = attrs["href"]
            parts = urlsplit(url)
            if parts.scheme != "https" or parts.hostname != "ja.wikipedia.org" or parts.username or parts.password:
                raise ValueError("Unexpected published source")
            self.event["source"] = {"url": url, "title": attrs["title"]}

    def handle_data(self, data):
        if self.field:
            self.text.append(data)

    def handle_endtag(self, tag):
        if self.field and tag in ("div", "h3", "p"):
            self.event[self.field] = "".join(self.text)
            self.field = None
        if tag == "li" and self.event is not None:
            if set(self.event) != {"date", "title", "description", "source"}:
                raise ValueError("Published event fields changed")
            match = re.fullmatch(r"([0-9]{4})年.*", self.event["date"])
            if not match:
                raise ValueError("Published date cannot be represented")
            self.event["year"] = int(match[1])
            self.events.append(self.event)
            self.event = None


def published_job():
    hashes = json.loads((ROOT / "cloudflare/published-snapshot-sha256.json").read_text())
    if set(hashes) != {"index.html", "showa/index.html", "tokens.css", "styles.css", "favicon.svg"}:
        raise ValueError("Published snapshot manifest changed")
    # Verify the entire previous publication before deriving a portable view.
    for name, expected in hashes.items():
        source = PUBLISHED_SNAPSHOT / name
        if source.is_symlink() or not source.is_file() or source.stat().st_size > 2_000_000:
            raise ValueError("Published snapshot asset missing or invalid")
        if hashlib.sha256(source.read_bytes()).hexdigest() != expected:
            raise ValueError("Published snapshot content changed")
    parser = PublishedEvents()
    parser.feed((PUBLISHED_SNAPSHOT / "showa/index.html").read_text())
    if len(parser.events) != 50:
        raise ValueError("Published event count changed")
    return {"id": "pub-showa", "query": "昭和", "topic": "昭和", "period": "全期間",
            "state": "complete", "read_only": True, "legacy_period": False,
            "can_delete": False, "has_result": True, "event_count": len(parser.events),
            "generated_at": None, "updated_at": None, "quality": None,
            "requested_milestones": [], "result": {"theme": "昭和", "source_mode": "unknown",
                "notice": NOTICE, "elapsed_seconds": "記録なし", "events": parser.events}}


def build_app():
    job = published_job()
    cloudflare = ROOT / "cloudflare"
    with tempfile.TemporaryDirectory(dir=cloudflare) as directory:
        stage = Path(directory)
        for name in FILES:
            source = ROOT / name
            if source.is_symlink() or not source.is_file() or source.stat().st_size > 2_000_000:
                raise ValueError("Invalid shared application file")
            body = source.read_text()
            if name.endswith(".html"):
                if body.count(LOCAL_LOG) != 1:
                    raise ValueError("Local visitor log template changed")
                # Public-network exception: LAN visitor logger is unreachable over HTTPS.
                # This omission is explicit and recorded in ats030-pc85t; local HTML retains it.
                body = body.replace(LOCAL_LOG, "")
            (stage / name).write_text(body)
        (stage / "published").mkdir()
        (stage / "published/showa.json").write_text(json.dumps(job, ensure_ascii=False))
        shutil.copyfile(cloudflare / "app-headers.txt", stage / "_headers")
        output = cloudflare / "app-assets"
        if output.exists():
            shutil.rmtree(output)
        shutil.copytree(stage, output)
    print(f"Built shared application ({len(FILES)} source files), {job['event_count']} previously published events")


if __name__ == "__main__":
    build_app()
