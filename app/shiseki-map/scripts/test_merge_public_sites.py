import json
import unittest
from pathlib import Path

from merge_public_sites import ROOT, SNAPSHOT, SUPPLEMENT, merge_rows


class PublicSiteMergeTest(unittest.TestCase):
    def test_snapshot_merge_is_idempotent_and_matches_review(self):
        rows = json.loads(SNAPSHOT.read_text(encoding="utf-8"))
        once = merge_rows(rows)
        self.assertEqual(once, merge_rows(once))
        self.assertEqual(len(once), 3314)
        additions = json.loads(SUPPLEMENT.read_text(encoding="utf-8"))
        review = json.loads((ROOT / "docs" / "public-candidate-review.json").read_text(encoding="utf-8"))
        approved = {row["source_id"]: row for row in review["records"] if row["status"] == "publish"}
        self.assertEqual({row["id"] for row in additions}, set(approved))
        for row in additions:
            source = approved[row["id"]]
            self.assertEqual((row["label_ja"], row["latitude"], row["longitude"]),
                             (source["name"], source["latitude"], source["longitude"]))

    def test_same_name_record_is_rejected(self):
        rows = json.loads(SNAPSHOT.read_text(encoding="utf-8"))
        rows.append({"qid": "Q999999999", "label_ja": "子規庵", "prefecture": "東京都",
                     "latitude": 35.7, "longitude": 139.7})
        with self.assertRaisesRegex(ValueError, "same-name map record"):
            merge_rows(rows)


if __name__ == "__main__":
    unittest.main()
