import unittest

from classify_festivals import classify

JR = "神事・祭礼"


def cats(label, description=""):
    return classify({"label_ja": label, "description": description})


class ShintoRitualCategoryTest(unittest.TestCase):
    def test_hedged_or_negated_sentences_do_not_assign(self):
        for label, desc in [
            ("Yokohama Jazz Festival", "イベントは神社の祭礼とは異なり、地域の文化振興を目的とする。"),
            ("ぴあフィルムフェスティバル", "日本の神社祭礼では、地域の信仰や豊作祈願が重んじられる。"),
            ("つきがた夏まつり", "神社の祭礼と直接結びついているとは限りません。"),
            ("染織祭", "祭名から、織機の奉納が行われた可能性があります。"),
            ("手杵祭", "地名や神社名に由来する伝統的な祭礼の一つとされています。"),
        ]:
            with self.subTest(label=label):
                self.assertNotIn(JR, cats(label, desc))

    def test_assertive_sentence_assigns(self):
        for label, desc in [
            ("日野祭", "日本の滋賀県蒲生郡日野町で開催される祭礼"),
            ("能登キリコ祭り", "日本の能登半島で開催される祭礼の総称"),
            ("なまはげ", "日本の秋田県男鹿半島周辺で行われる年中行事、そこに登場する来訪神。"),
            ("新野の雪まつり", "この祭りは、古くは「正月神事」と呼ばれた。"),
        ]:
            with self.subTest(label=label):
                self.assertIn(JR, cats(label, desc))

    def test_only_one_assertive_sentence_is_needed(self):
        desc = "神社の祭礼とは異なる趣もある。毎年8月に諏訪神社へ大わらじを奉納する。"
        self.assertIn(JR, cats("わらじまつり", desc))

    def test_shrine_and_kagura_labels_assign_without_description(self):
        for label in ["熊野本宮大社例大祭", "高千穂の夜神楽", "那智の田楽", "青梅大祭"]:
            with self.subTest(label=label):
                self.assertIn(JR, cats(label))

    def test_grouped_festival_names_do_not_assign(self):
        for label in ["東北三大祭り", "福岡五大祭"]:
            with self.subTest(label=label):
                self.assertNotIn(JR, cats(label))

    def test_hedge_filter_does_not_apply_to_fireworks(self):
        self.assertIn("花火", cats("例のまつり", "花火が上がる可能性があります。"))


class HedgedDescriptionOtherCategoriesTest(unittest.TestCase):
    def test_hedged_sentences_do_not_assign(self):
        for label, desc, cat in [
            ("例のまつり", "山車が出る可能性があります。", "山車・屋台"),
            ("つきがた夏まつり", "盆踊りが行われることが多いとされています。", "演舞・盆踊り"),
            ("村上大祭", "神輿の渡御が行われると考えられます。", "行列・渡御"),
            ("わっしょい百万夏祭り", "提灯が飾られる様子がうかがえます。", "灯籠・火祭り"),
        ]:
            with self.subTest(label=label):
                self.assertNotIn(cat, cats(label, desc))

    def test_assertive_sentences_still_assign(self):
        self.assertIn("行列・渡御", cats("例のまつり", "毎年5月に神輿の渡御がある。"))
        # 「各地区」は一般論の「各地」ではない。
        self.assertIn("山車・屋台", cats("加悦谷祭", "各地区から山車が出る。"))

    def test_label_keeps_assignment_without_description(self):
        for label, cat in [
            ("弘前ねぷた", "灯籠・火祭り"),
            ("仙台クラシックフェスティバル", "音楽・映画・芸術"),
            ("ぴあフィルムフェスティバル", "音楽・映画・芸術"),
        ]:
            with self.subTest(label=label):
                self.assertIn(cat, cats(label))


if __name__ == "__main__":
    unittest.main()
