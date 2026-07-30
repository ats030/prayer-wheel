import requests
from ..config import HTTP_TIMEOUT, USER_AGENT

_session = requests.Session()
_session.headers.update({"User-Agent": USER_AGENT})


def fetch_bytes(url: str) -> tuple[bytes, str]:
    resp = _session.get(url, timeout=HTTP_TIMEOUT, allow_redirects=True)
    resp.raise_for_status()
    return resp.content, resp.headers.get("Content-Type", "")


def fetch_og_image(url: str) -> str:
    if not url:
        return ""
    try:
        from bs4 import BeautifulSoup

        resp = _session.get(url, timeout=HTTP_TIMEOUT, allow_redirects=True)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.content, "lxml")
        for prop in ("og:image", "twitter:image"):
            tag = soup.find("meta", property=prop) or soup.find("meta", attrs={"name": prop})
            if tag and tag.get("content"):
                return tag["content"]
    except Exception:
        pass
    return ""


def fetch_favicon(site_url: str) -> str:
    """Google favicon service でサイトのアイコンを取得する。"""
    if not site_url:
        return ""
    import re
    m = re.search(r'https?://([^/]+)', site_url)
    if not m:
        return ""
    domain = m.group(1)
    return f"https://www.google.com/s2/favicons?domain={domain}&sz=128"
