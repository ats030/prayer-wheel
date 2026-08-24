from pathlib import Path
from xml.etree import ElementTree


PROJECT_ROOT = Path(__file__).resolve().parents[1]
FAVICON = PROJECT_ROOT / "src" / "rss_reader" / "static" / "favicon.svg"
BASE_TEMPLATE = PROJECT_ROOT / "src" / "rss_reader" / "templates" / "base.html"


def test_favicon_is_dedicated_rss_svg():
    svg = FAVICON.read_text(encoding="utf-8")
    root = ElementTree.fromstring(svg)

    assert root.tag.endswith("svg")
    assert root.attrib["viewBox"] == "0 0 100 100"
    assert "<text" not in svg
    assert "📡" not in svg
    assert 'stroke="#464a52"' in svg
    assert 'stroke="#f97316"' in svg
    assert 'fill="#f97316"' in svg
    assert svg.count("A") == 2


def test_base_template_uses_static_favicon():
    template = BASE_TEMPLATE.read_text(encoding="utf-8")

    assert "path='favicon.svg'" in template
    assert "data:image/svg+xml" not in template
