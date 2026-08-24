from pathlib import Path
from xml.etree import ElementTree


PROJECT_ROOT = Path(__file__).resolve().parents[1]
FAVICON = PROJECT_ROOT / "src" / "exam_trainer" / "static" / "favicon.svg"
WRITING_FAVICON = PROJECT_ROOT.parent / "writing" / "src" / "writing" / "static" / "favicon.svg"
BASE_TEMPLATE = PROJECT_ROOT / "src" / "exam_trainer" / "templates" / "base.html"


def test_favicon_is_dedicated_exam_svg_with_writing_background():
    svg = FAVICON.read_text(encoding="utf-8")
    writing = WRITING_FAVICON.read_text(encoding="utf-8")
    root = ElementTree.fromstring(svg)

    assert root.tag.endswith("svg")
    assert root.attrib["viewBox"] == "0 0 100 100"
    assert "<text" not in svg
    assert "🎓" not in svg
    assert 'd="M24 16H61L77 32V82H24Z" fill="#ffffff"' in svg
    assert 'd="M24 16H61L77 32V82H24Z" fill="#ffffff"' in writing
    assert '<rect width="100"' not in svg
    assert 'stroke="#5e6ad2"' in svg


def test_base_template_uses_static_favicon():
    template = BASE_TEMPLATE.read_text(encoding="utf-8")

    assert "path='favicon.svg'" in template
    assert "data:image/svg+xml" not in template
