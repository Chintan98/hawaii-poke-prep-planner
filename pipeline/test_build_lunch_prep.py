import unittest

from pipeline.build_lunch_prep import (
    PairState,
    classify_article,
    parse_amount,
    protein_portion,
    resolve_pair,
)


RECIPE_DATA = {
    "protein_alternatives": {
        "standard": {
            "chicken_tofu": "100gr",
            "fresh_shrimp": "70gr",
            "salmon_tuna": "80gr",
            "falafel": "6 pcs",
            "airfried_shrimp": "3 pcs",
        }
    }
}


class ClassificationTests(unittest.TestCase):
    def test_warm_bowl_uses_article_id(self):
        actual = classify_article("304", "Yakiniku Beef", "Mat")
        self.assertEqual((actual.kind, actual.bowl, actual.protein), (
            "component",
            "Yakiniku",
            "Yakiniku Beef",
        ))

    def test_custom_warm_protein_does_not_create_bowl(self):
        actual = classify_article("197", "Yakiniku beef", "Mat")
        self.assertEqual(actual.kind, "ignored")

    def test_custom_katsu_does_not_create_bowl(self):
        actual = classify_article("1290", "Chicken Katsu", "Mat")
        self.assertEqual(actual.kind, "ignored")

    def test_lunch_deal_is_pricing_wrapper(self):
        actual = classify_article("1284", "Salmon Lunch deal", "Mat")
        self.assertEqual(actual.kind, "wrapper")

    def test_roll_is_unsupported(self):
        actual = classify_article("1134", "Yakiniku roll", "Mat")
        self.assertEqual(actual.kind, "unsupported")


class PairingTests(unittest.TestCase):
    def test_header_and_component_count_once(self):
        state = PairState(
            header_positive=1,
            protein_positive={"Salmon": 1},
        )
        resolved, unknown = resolve_pair(state, "Avoloha Standard")
        self.assertEqual(resolved, [("Salmon", 1.0)])
        self.assertEqual(unknown, 0)

    def test_header_remainder_is_retained(self):
        state = PairState(
            header_positive=2,
            protein_positive={"Salmon": 1},
        )
        resolved, unknown = resolve_pair(state, "Avoloha Standard")
        self.assertEqual(resolved, [("Salmon", 1.0), (None, 1.0)])
        self.assertEqual(unknown, 1.0)

    def test_negative_return_is_not_lost(self):
        state = PairState(
            header_negative=1,
            protein_negative={"Tofu": 1},
        )
        resolved, unknown = resolve_pair(state, "Original")
        self.assertEqual(resolved, [("Tofu", -1.0)])
        self.assertEqual(unknown, 0)


class RecipeTests(unittest.TestCase):
    def test_parse_recipe_amount(self):
        self.assertEqual(parse_amount("0.5st"), (0.5, "st"))

    def test_teriyaki_falafel_uses_piece_portion(self):
        self.assertEqual(
            protein_portion(
                RECIPE_DATA, "standard", "Teriyaki Falafel"
            ),
            [("Teriyaki Falafel", 6.0, "pcs")],
        )


if __name__ == "__main__":
    unittest.main()
