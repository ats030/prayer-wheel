import json
import os

from ..config import DATA_FILE


class FeedStore:
    def load(self) -> list[str]:
        if not DATA_FILE.exists():
            return []
        try:
            return json.loads(DATA_FILE.read_text())["feeds"]
        except Exception:
            return []

    def save(self, urls: list[str]) -> None:
        DATA_FILE.parent.mkdir(parents=True, exist_ok=True)
        tmp = DATA_FILE.with_suffix(".tmp")
        tmp.write_text(json.dumps({"feeds": urls}, ensure_ascii=False, indent=2))
        os.replace(tmp, DATA_FILE)

    def add(self, url: str) -> None:
        urls = self.load()
        if url not in urls:
            urls.append(url)
            self.save(urls)

    def remove(self, url: str) -> None:
        urls = self.load()
        if url in urls:
            urls.remove(url)
            self.save(urls)
