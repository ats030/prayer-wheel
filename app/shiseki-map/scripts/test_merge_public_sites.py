import json
import unittest
from pathlib import Path

from merge_public_sites import ROOT, SNAPSHOT, SUPPLEMENT, merge_rows


def same_name_collision(addition, rows):
    if addition.get("same_site_qid"):
        return any(row.get("qid") == addition["same_site_qid"] for row in rows)
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
                     "tokyo:130001:0000000141", "tokyo:130001:0000000142",
                     "tokyo:130001:0000000123", "tokyo:130001:0000000124",
                     "tokyo:130001:0000000128", "tokyo:130001:0000000138",
                     "tokyo:130001:0000000171", "tokyo:130001:0000000180",
                     "tokyo:130001:0000000185"}
        # 都CSV点がずれていた件は、自治体のCC BYデータの座標を使う
        municipal_points = {
            fuchu_id: (35.669874402894102, 139.47669744938199),
            "tokyo:130001:0000000128": (35.67800139, 139.531607),
            "tokyo:130001:0000000138": (35.760502, 139.50924),
            "tokyo:130001:0000000185": (35.788337, 139.295547),
        }
        self.assertEqual({row["id"] for row in additions}, set(approved) | {fuchu_id} | batch_ids)
        base_ids = {row.get("qid") for row in rows}
        kept_ids, merged_ids = set(), set()
        for item in additions:
            if same_name_collision(item, [row for row in rows if row.get("id") != item["id"]]):
                merged_ids.add(item["id"])
            else:
                kept_ids.add(item["id"])
        once_ids = {row["id"] for row in once if row.get("id", "").startswith("tokyo:")}
        self.assertEqual(once_ids, kept_ids)
        for row in once:
            source = review_by_id.get(row.get("id"))
            if source is None:
                continue
            self.assertEqual(row["label_ja"], source["name"])
            if source["source_id"] in municipal_points:
                self.assertEqual((row["latitude"], row["longitude"]),
                                 municipal_points[source["source_id"]])
            else:
                self.assertEqual((row["latitude"], row["longitude"]),
                                 (source["latitude"], source["longitude"]))
        # Wikidataに同名の行がある補足件は別マーカーにせず、その行へ出典証拠を統合する
        for item in additions:
            if item["id"] not in merged_ids:
                continue
            target = next(row for row in once
                          if (item.get("same_site_qid") and row.get("qid") == item["same_site_qid"])
                          or (not item.get("same_site_qid") and row["prefecture"] == item["prefecture"]
                              and (row.get("label_ja") or "").strip() == item["label_ja"].strip() and row.get("qid")))
            self.assertEqual(target["source_url"], item["source_url"])
            self.assertEqual(target["designation"], item["designation"])
            self.assertEqual(target["designation_label"], item["designation_label"])
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

    def test_same_site_qid_merges_into_differently_named_row(self):
        rows = json.loads(SNAPSHOT.read_text(encoding="utf-8"))
        merged = merge_rows(rows)
        self.assertNotIn("tokyo:130001:0000000123", {row["id"] for row in merged if row.get("id")})
        kasai = next(row for row in merged if row.get("qid") == "Q11620984")
        self.assertEqual(kasai["label_ja"], "葛西城")
        self.assertEqual(kasai["visit_url"], "https://katsushika-park.com/gotenyama/")

    def test_near_record_is_rejected_unless_reviewed_as_distinct(self):
        rows = json.loads(SNAPSHOT.read_text(encoding="utf-8"))
        merged = merge_rows(rows)
        ids = {row.get("id") for row in merged}
        self.assertIn("tokyo:130001:0000000180", ids)
        rows = [row for row in rows if row.get("qid") != "Q97203084"]
        rows.append({"qid": "Q999999998", "label_ja": "近接テスト", "prefecture": "東京都",
                     "latitude": 35.797744, "longitude": 139.78858})
        with self.assertRaisesRegex(ValueError, "near-coincident"):
            merge_rows(rows)


if __name__ == "__main__":
    unittest.main()
