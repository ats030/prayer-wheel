#!/usr/bin/env python3
"""Cultural Agency detail-page prefecture extraction regression tests."""

import importlib.util
from pathlib import Path
from unittest import TestCase, main
from unittest.mock import patch

SCRIPTS = Path(__file__).parent
MODULES = ("fetch_cultural_relaw.py",)
PREFECTURES = (
    "北海道", "青森県", "岩手県", "宮城県", "秋田県", "山形県", "福島県",
    "茨城県", "栃木県", "群馬県", "埼玉県", "千葉県", "東京都", "神奈川県",
    "新潟県", "富山県", "石川県", "福井県", "山梨県", "長野県", "岐阜県",
    "静岡県", "愛知県", "三重県", "滋賀県", "京都府", "大阪府", "兵庫県",
    "奈良県", "和歌山県", "鳥取県", "島根県", "岡山県", "広島県", "山口県",
    "徳島県", "香川県", "愛媛県", "高知県", "福岡県", "佐賀県", "長崎県",
    "熊本県", "大分県", "宮崎県", "鹿児島県", "沖縄県",
)


class Response:
    def __init__(self, text):
        self.text = text

    def raise_for_status(self):
        pass


def load_module(filename):
    spec = importlib.util.spec_from_file_location(filename, SCRIPTS / filename)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class TestPrefectureExtraction(TestCase):
    def test_extracts_all_prefecture_suffixes(self):
        for filename in MODULES:
            module = load_module(filename)
            for prefecture in PREFECTURES:
                html = ("<th>\u6240\u5728\u90fd\u9053\u5e9c\u770c\u3001\u5730\u57df</th>"
                        f"<td class=\"detail-td\">{prefecture}</td>")
                with self.subTest(fetcher=filename, prefecture=prefecture):
                    with patch.object(module.requests, "get", return_value=Response(html)):
                        result = module.fetch_cultural_data("https://example.invalid/detail")
                    self.assertEqual(result["prefecture"], prefecture)

    def test_rejects_a_non_prefecture_value(self):
        html = ("<th>\u6240\u5728\u90fd\u9053\u5e9c\u770c\u3001\u5730\u57df</th>"
                "<td class=\"detail-td\">\u67b6\u7a7a\u770c</td>")
        for filename in MODULES:
            module = load_module(filename)
            with self.subTest(fetcher=filename):
                with patch.object(module.requests, "get", return_value=Response(html)):
                    result = module.fetch_cultural_data("https://example.invalid/detail")
                self.assertEqual(result["prefecture"], "")


if __name__ == "__main__":
    main()
