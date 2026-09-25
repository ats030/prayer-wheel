import json
import unittest
from pathlib import Path

from merge_public_sites import ROOT, SNAPSHOT, SUPPLEMENT, merge_rows


def same_name_collision(addition, rows):
    return any(
        row.get("prefecture") == addition["prefecture"] and (row.get("label_ja") or "").strip() == addition["label_ja"].strip()
        and row.get("qid")
        for row in rows
    )


class PublicSiteMergeTest(unittest.TestCase):
    def test_snapshot_merge_is_idempotent_and_matches_review(self):
        rows = json.loads(SNAPSHOT.read_text(encoding="utf-8"))
        once = merge_rows(rows)
        self.assertEqual(once, merge_rows(once))
        additions = json.loads(SUPPLEMENT.read_text(encoding="utf-8"))
        review = json.loads((ROOT / "docs" / "public-candidate-review.json").read_text(encoding="utf-8"))
        approved = {row["source_id"]: row for row in review["records"] if row["status"] == "publish"}
        review_by_id = {row["source_id"]: row for row in review["records"]}
        fuchu_id = "tokyo:130001:0000000186"
        batch_ids = {"tokyo:130001:0000000136", "tokyo:130001:0000000140",
                     "tokyo:130001:0000000141", "tokyo:130001:0000000142"}
        self.assertEqual({row["id"] for row in additions}, set(approved) | {fuchu_id} | batch_ids)
        base_ids = {row.get("qid") for row in rows}
        kept_ids, merged_ids = set(), set()
        for item in additions:
            if same_name_collision(item, [row for row in rows if row.get("id") != item["id"]]):
                merged_ids.add(item["id"])
            else:
                kept_ids.add(item["id"])
        once_ids = {row["id"] for row in once if row.get("id")}
        self.assertEqual(once_ids, kept_ids)
        for row in once:
            source = review_by_id.get(row.get("id"))
            if source is None:
                continue
            self.assertEqual(row["label_ja"], source["name"])
            if source["source_id"] == fuchu_id:
                self.assertEqual((row["latitude"], row["longitude"]),
                                 (35.669874402894102, 139.47669744938199))
            else:
                self.assertEqual((row["latitude"], row["longitude"]),
                                 (source["latitude"], source["longitude"]))
        # Wikidataに同名の行がある補足件は別マーカーにせず、その行へ出典証拠を統合する
        for item in additions:
            if item["id"] not in merged_ids:
                continue
            target = next(row for row in once
                          if row["prefecture"] == item["prefecture"] and (row.get("label_ja") or "").strip() == item["label_ja"].strip()
                          and row.get("qid"))
            self.assertEqual(target["source_url"], item["source_url"])
            self.assertTrue(target.get("visit_url"))
            self.assertTrue(target.get("access_note"))

    def test_same_name_supplement_is_merged_not_duplicated(self):
        rows = json.loads(SNAPSHOT.read_text(encoding="utf-8"))
        rows.append({"qid": "Q999999999", "label_ja": "子規庵", "prefecture": "東京都",
                     "latitude": 35.7, "longitude": 139.7})
        merged = merge_rows(rows)
        shigen = [row for row in merged if (row.get("label_ja") or "").strip() == "子規庵"
                  and row["prefecture"] == "東京都"]
        self.assertEqual(len(shigen), 1)
        self.assertEqual(shigen[0]["qid"], "Q999999999")
        self.assertNotIn("tokyo:130001:0000000243", {row["id"] for row in merged if row.get("id")})


if __name__ == "__main__":
    unittest.main()
