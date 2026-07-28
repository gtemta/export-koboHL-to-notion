"""Pure-function tests for the card review verdict: parsing and the pass rule.

No network: everything here is a classmethod/staticmethod on CardReviewer or
plain CardReview arithmetic.
"""
import unittest

from zettelkasten_generator import CardReview, CardReviewer


def _verdict(**overrides):
    scores = dict(consistency=4, correctness=4, shareability=4, atomicity=4)
    scores.update(overrides)
    return CardReview(**scores)


class TestPassRule(unittest.TestCase):
    def test_all_axes_at_threshold_passes(self):
        self.assertTrue(_verdict(consistency=3, correctness=3,
                                 shareability=3, atomicity=3).passed(3))

    def test_single_axis_below_threshold_fails(self):
        # The whole point of per-axis scoring: a card can be accurate, readable
        # and on-theme yet still be two ideas glued together.
        self.assertFalse(_verdict(atomicity=2).passed(3))

    def test_high_average_does_not_rescue_a_failing_axis(self):
        self.assertFalse(_verdict(consistency=5, correctness=5,
                                  shareability=5, atomicity=1).passed(3))

    def test_scores_dict_covers_all_axes(self):
        self.assertEqual(
            set(_verdict().scores()),
            {"consistency", "correctness", "shareability", "atomicity"},
        )


class TestParseReview(unittest.TestCase):
    def test_plain_json(self):
        review = CardReviewer._parse_review(
            '{"consistency": 4, "correctness": 3, "shareability": 5, '
            '"atomicity": 2, "notes": "塞了兩個概念"}'
        )
        self.assertEqual(review.scores(),
                         {"consistency": 4, "correctness": 3,
                          "shareability": 5, "atomicity": 2})
        self.assertEqual(review.notes, "塞了兩個概念")

    def test_thinking_prefix_stripped(self):
        raw = (
            "Thinking...\nlet me weigh the axes\n...done thinking.\n"
            '{"consistency": 5, "correctness": 5, "shareability": 4, '
            '"atomicity": 4, "notes": ""}'
        )
        self.assertEqual(CardReviewer._parse_review(raw).consistency, 5)

    def test_code_fence_stripped(self):
        raw = (
            "以下是我的審核結果：\n```json\n"
            '{"consistency": 3, "correctness": 4, "shareability": 3, '
            '"atomicity": 3, "notes": ""}\n```\n希望有幫助'
        )
        self.assertEqual(CardReviewer._parse_review(raw).correctness, 4)

    def test_digit_strings_accepted(self):
        # small local models often quote their numbers
        raw = ('{"consistency": "4", "correctness": "4", '
               '"shareability": "4", "atomicity": "4", "notes": ""}')
        self.assertEqual(CardReviewer._parse_review(raw).atomicity, 4)

    def test_missing_axis_is_a_failed_review(self):
        raw = '{"consistency": 4, "correctness": 4, "shareability": 4}'
        self.assertIsNone(CardReviewer._parse_review(raw))

    def test_out_of_range_score_is_a_failed_review(self):
        raw = ('{"consistency": 9, "correctness": 4, '
               '"shareability": 4, "atomicity": 4}')
        self.assertIsNone(CardReviewer._parse_review(raw))

    def test_booleans_are_not_scores(self):
        raw = ('{"consistency": true, "correctness": 4, '
               '"shareability": 4, "atomicity": 4}')
        self.assertIsNone(CardReviewer._parse_review(raw))

    def test_prose_without_json(self):
        self.assertIsNone(CardReviewer._parse_review("這張卡看起來還不錯。"))

    def test_empty_response(self):
        self.assertIsNone(CardReviewer._parse_review(""))


class TestModelInstalled(unittest.TestCase):
    def test_exact_tag_match(self):
        self.assertTrue(
            CardReviewer._model_installed("qwen3:8b", ["qwen3:8b", "gemma4:e2b"])
        )

    def test_missing_model(self):
        self.assertFalse(CardReviewer._model_installed("qwen3:8b", ["gemma4:e2b"]))

    def test_bare_name_matches_any_tag(self):
        self.assertTrue(CardReviewer._model_installed("qwen3", ["qwen3:latest"]))

    def test_tagged_name_does_not_match_other_tag(self):
        self.assertFalse(CardReviewer._model_installed("qwen3:8b", ["qwen3:4b"]))


if __name__ == "__main__":
    unittest.main()
