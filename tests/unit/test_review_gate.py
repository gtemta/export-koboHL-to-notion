"""The review gate decides what may reach Notion.

Both LLM collaborators are faked, so these tests pin the orchestration —
who gets called, what gets regenerated, what is thrown away — without Ollama.
"""
import unittest

from zettelkasten_generator import (
    CardReview,
    ZettelkastenCard,
    ZettelkastenCardGenerator,
)

_PASS = dict(consistency=4, correctness=4, shareability=4, atomicity=4)
_FAIL = dict(consistency=4, correctness=4, shareability=4, atomicity=2)


def _highlight(i):
    return {
        "text": f"第 {i} 條劃線，內容夠長才不會被 CardSelectionAlgorithm 的長度過濾器擋掉，"
                f"所以這裡刻意寫得囉唆一點。",
        "chapter_name": f"第 {i} 章",
        "chapter_progress": 0.1 * i,
        "current_chapter_progress": 0.5,
        "annotation": "",
        "bookmark_id": f"BM-{i}",
    }


def _card_for(highlight, suffix=""):
    return ZettelkastenCard(
        id=f"id-{highlight['bookmark_id']}{suffix}",
        title=f"卡片-{highlight['bookmark_id']}{suffix}",
        content="內容",
        source_highlight=highlight["text"],
        chapter_reference=highlight["chapter_name"],
        chapter_progress=highlight["chapter_progress"],
        source_bookmark_id=highlight["bookmark_id"],
    )


class _FakeEnhancer:
    model = "gemma4:e2b"

    def __init__(self, regenerate=True):
        self._regenerate = regenerate
        self.batch_calls = 0
        self.regen_calls = []
        self.classified = None

    def batch_generate(self, highlights, book_title=""):
        self.batch_calls += 1
        return [_card_for(h) for h in highlights]

    def generate_card(self, highlight, book_title="", *, book_theme="", revision_hint=""):
        self.regen_calls.append((highlight["bookmark_id"], book_theme, revision_hint))
        if not self._regenerate:
            return None
        return _card_for(highlight, suffix="-v2")

    def classify_cards(self, cards, categories, book_title=""):
        self.classified = [c.title for c in cards]


class _FakeReviewer:
    """Returns a scripted verdict per card title, consuming one per review."""

    threshold = 3

    def __init__(self, verdicts, available=True, theme="本書主軸是複利"):
        self._verdicts = {title: list(seq) for title, seq in verdicts.items()}
        self._available = available
        self._theme = theme
        self.reviewed = []
        self.summarize_calls = 0

    def is_available(self):
        return self._available

    def summarize_book(self, cards, book_title=""):
        self.summarize_calls += 1
        return self._theme

    def review(self, card, *, book_title="", book_theme="", sibling_titles=None):
        self.reviewed.append((card.title, book_theme, list(sibling_titles or [])))
        queue = self._verdicts.get(card.title)
        if not queue:
            return CardReview(**_PASS)
        outcome = queue.pop(0)
        return None if outcome is None else CardReview(**outcome)


def _generator(enhancer, reviewer, tag_categories=None):
    return ZettelkastenCardGenerator(
        max_cards=5, min_highlights=1,
        tag_categories=tag_categories,
        enhancer=enhancer, reviewer=reviewer,
    )


class TestGateOutcomes(unittest.TestCase):
    def test_all_pass_uploads_everything_and_never_regenerates(self):
        enhancer = _FakeEnhancer()
        reviewer = _FakeReviewer({})
        result = _generator(enhancer, reviewer).generate_cards_with_review(
            [_highlight(1), _highlight(2)], "測試書"
        )
        self.assertEqual(len(result.passed), 2)
        self.assertEqual(result.rejected, [])
        self.assertEqual(enhancer.regen_calls, [])
        self.assertTrue(all(c.review_status == "passed" for c in result.passed))

    def test_failed_card_is_regenerated_once_and_can_pass(self):
        enhancer = _FakeEnhancer()
        reviewer = _FakeReviewer({"卡片-BM-1": [_FAIL]})  # v2 falls through to pass
        result = _generator(enhancer, reviewer).generate_cards_with_review(
            [_highlight(1), _highlight(2)], "測試書"
        )
        self.assertEqual(len(result.passed), 2)
        self.assertEqual(result.rejected, [])
        self.assertEqual([c[0] for c in enhancer.regen_calls], ["BM-1"])
        remade = next(c for c in result.passed if c.source_bookmark_id == "BM-1")
        self.assertTrue(remade.regenerated)
        self.assertEqual(remade.title, "卡片-BM-1-v2")

    def test_failing_twice_is_dropped(self):
        enhancer = _FakeEnhancer()
        reviewer = _FakeReviewer({
            "卡片-BM-1": [_FAIL],
            "卡片-BM-1-v2": [_FAIL],
        })
        result = _generator(enhancer, reviewer).generate_cards_with_review(
            [_highlight(1), _highlight(2)], "測試書"
        )
        self.assertEqual([c.source_bookmark_id for c in result.passed], ["BM-2"])
        self.assertEqual([c.source_bookmark_id for c in result.rejected], ["BM-1"])
        self.assertEqual(result.rejected[0].review_status, "rejected")

    def test_unparseable_review_counts_as_not_approved(self):
        enhancer = _FakeEnhancer()
        reviewer = _FakeReviewer({"卡片-BM-1": [None], "卡片-BM-1-v2": [None]})
        result = _generator(enhancer, reviewer).generate_cards_with_review(
            [_highlight(1)], "測試書"
        )
        self.assertEqual(result.passed, [])
        self.assertEqual(len(result.rejected), 1)

    def test_failed_regeneration_drops_the_card(self):
        enhancer = _FakeEnhancer(regenerate=False)
        reviewer = _FakeReviewer({"卡片-BM-1": [_FAIL]})
        result = _generator(enhancer, reviewer).generate_cards_with_review(
            [_highlight(1)], "測試書"
        )
        self.assertEqual(result.passed, [])
        self.assertEqual(len(result.rejected), 1)


class TestGateIsHard(unittest.TestCase):
    def test_unavailable_reviewer_produces_nothing_and_skips_drafting(self):
        enhancer = _FakeEnhancer()
        reviewer = _FakeReviewer({}, available=False)
        result = _generator(enhancer, reviewer).generate_cards_with_review(
            [_highlight(1)], "測試書"
        )
        self.assertEqual(result.passed, [])
        self.assertEqual(result.rejected, [])
        # drafting is minutes of local inference — don't spend it just to bin it
        self.assertEqual(enhancer.batch_calls, 0)

    def test_below_min_highlights_never_touches_the_models(self):
        enhancer = _FakeEnhancer()
        reviewer = _FakeReviewer({})
        generator = ZettelkastenCardGenerator(
            max_cards=5, min_highlights=10, enhancer=enhancer, reviewer=reviewer
        )
        result = generator.generate_cards_with_review([_highlight(1)], "測試書")
        self.assertEqual(result.passed, [])
        self.assertEqual(enhancer.batch_calls, 0)
        self.assertEqual(reviewer.reviewed, [])


class TestReviewContext(unittest.TestCase):
    def test_book_theme_and_siblings_reach_the_reviewer(self):
        enhancer = _FakeEnhancer()
        reviewer = _FakeReviewer({})
        _generator(enhancer, reviewer).generate_cards_with_review(
            [_highlight(1), _highlight(2)], "測試書"
        )
        self.assertEqual(reviewer.summarize_calls, 1)
        title, theme, siblings = reviewer.reviewed[0]
        self.assertEqual(theme, "本書主軸是複利")
        # a card is never offered its own title as a duplicate candidate
        self.assertEqual(siblings, ["卡片-BM-2"])
        self.assertNotIn(title, siblings)

    def test_regeneration_carries_theme_and_reviewer_notes(self):
        enhancer = _FakeEnhancer()
        reviewer = _FakeReviewer({
            "卡片-BM-1": [dict(_FAIL, notes="一張卡塞了兩個概念")],
        })
        _generator(enhancer, reviewer).generate_cards_with_review(
            [_highlight(1)], "測試書"
        )
        _, theme, hint = enhancer.regen_calls[0]
        self.assertEqual(theme, "本書主軸是複利")
        self.assertEqual(hint, "一張卡塞了兩個概念")


class TestClassification(unittest.TestCase):
    def test_only_survivors_get_classified(self):
        enhancer = _FakeEnhancer()
        reviewer = _FakeReviewer({
            "卡片-BM-1": [_FAIL],
            "卡片-BM-1-v2": [_FAIL],
        })
        _generator(enhancer, reviewer, tag_categories=["💞心理學"]) \
            .generate_cards_with_review([_highlight(1), _highlight(2)], "測試書")
        self.assertEqual(enhancer.classified, ["卡片-BM-2"])

    def test_no_classification_call_when_nothing_passes(self):
        enhancer = _FakeEnhancer(regenerate=False)
        reviewer = _FakeReviewer({"卡片-BM-1": [_FAIL]})
        _generator(enhancer, reviewer, tag_categories=["💞心理學"]) \
            .generate_cards_with_review([_highlight(1)], "測試書")
        self.assertIsNone(enhancer.classified)


if __name__ == "__main__":
    unittest.main()
