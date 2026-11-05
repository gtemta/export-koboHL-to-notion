"""重審流程：標記 → 讀 Notion 目前內容 → 審核／重產 → 結果寫到頁尾，內文不動。"""
import unittest

from src.application.use_cases.revise_cards_use_case import ReviseCardsUseCase
from src.domain.entities.board_card import BoardCard
from src.domain.entities.book_card import BookCard
from src.domain.entities.card_revision import CardBlock
from src.domain.services.card_revision_rules import (
    RESULT_MARKER,
    fingerprint,
    parse_card_body,
)
from zettelkasten_generator import CardReview, ZettelkastenCard


def _card(page_id="p1", title="原標題", book="book-1"):
    return BoardCard(page_id=page_id, book_page_id=book, title=title,
                     source_id="BM-1", created_time="")


REVIEW_ONLY = [CardBlock("paragraph", "目前內文"), CardBlock("quote", "原文劃線")]
WITH_NOTE = REVIEW_ONLY + [CardBlock("paragraph", "待修正的點：寫三維卻有四個層面")]


class FakeCards:
    def __init__(self, marked=(), blocks=None, siblings=()):
        self.marked = list(marked)
        self.blocks = blocks or {}
        self.siblings = list(siblings)
        self.written = []
        self.titles_read = []
        self.fail_reading = set()

    def list_cards_marked_for_revision(self):
        return self.marked

    def read_card_blocks(self, page_id):
        if page_id in self.fail_reading:
            raise RuntimeError("讀取失敗")
        return self.blocks.get(page_id, REVIEW_ONLY)

    def append_revision_result(self, page_id, heading, lines):
        self.written.append((page_id, heading, lines))

    def book_title(self, book_page_id):
        self.titles_read.append(book_page_id)
        return "主控力"

    def list_book_cards(self, book_page_id):
        return self.siblings

    def card_text(self, page_id):
        return f"{page_id} 的內文"


class FakeReviewer:
    threshold = 4
    model = "審核模型"

    def __init__(self, available=True, reviews=None):
        self.available = available
        self.reviews = list(reviews) if reviews is not None else None
        self.reviewed = []
        self.summaries = []

    def is_available(self):
        return self.available

    def summarize_book(self, cards, book_title=""):
        self.summaries.append((book_title, [c.title for c in cards]))
        return "全書主軸"

    def review(self, card, *, book_title="", book_theme="", sibling_titles=None):
        self.reviewed.append((card, book_title, book_theme, sibling_titles))
        if self.reviews is not None:
            return self.reviews.pop(0)
        return CardReview(4, 4, 4, 4, notes="", model=self.model)


class FakeEnhancer:
    def __init__(self, result="default"):
        self.calls = []
        self.result = result

    def generate_card(self, highlight, book_title="", *, book_theme="", revision_hint=""):
        self.calls.append((highlight, book_title, book_theme, revision_hint))
        if self.result is None:
            return None
        return ZettelkastenCard(id="c", title="新標題", content="新內容",
                                source_highlight=highlight["text"],
                                chapter_reference="", chapter_progress=0.0)


def _use_case(cards, reviewer=None, enhancer=None):
    return ReviseCardsUseCase(
        cards=cards,
        reviewer=reviewer or FakeReviewer(),
        enhancer=enhancer or FakeEnhancer(),
        today=lambda: "2026-11-06",
    )


class TestNothingToDo(unittest.TestCase):
    def test_no_marked_cards_never_touches_the_model(self):
        reviewer = FakeReviewer(available=False)
        report = _use_case(FakeCards(), reviewer).execute()
        self.assertEqual(reviewer.reviewed, [])
        self.assertEqual(report.aborted, "")


class TestReviewOnly(unittest.TestCase):
    def test_reviews_the_text_currently_on_the_page(self):
        reviewer = FakeReviewer()
        _use_case(FakeCards([_card()]), reviewer).execute()
        reviewed = reviewer.reviewed[0][0]
        self.assertEqual(reviewed.title, "原標題")
        self.assertEqual(reviewed.content, "目前內文")
        self.assertEqual(reviewed.source_highlight, "原文劃線")

    def test_does_not_regenerate(self):
        enhancer = FakeEnhancer()
        report = _use_case(FakeCards([_card()]), enhancer=enhancer).execute()
        self.assertEqual(enhancer.calls, [])
        self.assertEqual(report.reviewed, ["原標題"])
        self.assertEqual(report.regenerated, [])

    def test_writes_one_result_carrying_this_version_fingerprint(self):
        cards = FakeCards([_card()])
        _use_case(cards).execute()
        [(page_id, heading, lines)] = cards.written
        mark = fingerprint("原標題", parse_card_body(REVIEW_ONLY))
        self.assertEqual(page_id, "p1")
        self.assertTrue(heading.startswith(RESULT_MARKER))
        self.assertIn(mark, heading)
        self.assertIn("2026-11-06", heading)
        self.assertNotIn("候選", heading + "".join(lines))


class TestRegenerate(unittest.TestCase):
    def _cards(self):
        return FakeCards([_card()], {"p1": WITH_NOTE})

    def test_regenerates_from_the_highlight_with_the_users_request(self):
        enhancer = FakeEnhancer()
        _use_case(self._cards(), enhancer=enhancer).execute()
        [(highlight, book_title, theme, hint)] = enhancer.calls
        self.assertEqual(highlight["text"], "原文劃線")
        self.assertEqual(book_title, "主控力")
        self.assertEqual(theme, "全書主軸")
        self.assertIn("寫三維卻有四個層面", hint)
        self.assertIn("目前內文", hint)

    def test_reviews_both_the_current_version_and_the_candidate(self):
        reviewer = FakeReviewer()
        _use_case(self._cards(), reviewer).execute()
        self.assertEqual([r[0].title for r in reviewer.reviewed], ["原標題", "新標題"])

    def test_candidate_goes_into_the_result_block(self):
        cards = self._cards()
        report = _use_case(cards).execute()
        [(_, heading, lines)] = cards.written
        text = "\n".join(lines)
        self.assertIn("候選", heading)
        self.assertIn("新標題", text)
        self.assertIn("新內容", text)
        self.assertEqual(report.regenerated, ["原標題"])
        self.assertEqual(report.reviewed, [])

    def test_a_failing_candidate_is_still_shown_with_its_verdict(self):
        # 審核只是參考：使用者要的是候選版本，分數低也讓使用者自己判斷
        reviews = [CardReview(4, 4, 4, 4), CardReview(4, 2, 4, 4, notes="加了原文沒有的結論")]
        cards = self._cards()
        _use_case(cards, FakeReviewer(reviews=reviews)).execute()
        [(_, _, lines)] = cards.written
        self.assertIn("加了原文沒有的結論", "\n".join(lines))


class TestBookContext(unittest.TestCase):
    def test_book_theme_is_computed_once_per_book(self):
        reviewer = FakeReviewer()
        cards = FakeCards([_card("p1"), _card("p2", "另一張")])
        _use_case(cards, reviewer).execute()
        self.assertEqual(len(reviewer.summaries), 1)
        self.assertEqual(cards.titles_read, ["book-1"])

    def test_each_card_is_reviewed_against_its_siblings_not_itself(self):
        reviewer = FakeReviewer()
        siblings = [BookCard("p1", "原標題", [], []), BookCard("p2", "別張", [], [])]
        _use_case(FakeCards([_card("p1")], siblings=siblings), reviewer).execute()
        _, book_title, theme, sibling_titles = reviewer.reviewed[0]
        self.assertEqual(book_title, "主控力")
        self.assertEqual(theme, "全書主軸")
        self.assertEqual(sibling_titles, ["別張"])

    def test_book_theme_comes_from_what_the_sibling_pages_say_now(self):
        reviewer = FakeReviewer()
        siblings = [BookCard("p2", "別張", [], [])]
        _use_case(FakeCards([_card("p1")], siblings=siblings), reviewer).execute()
        self.assertEqual(reviewer.summaries, [("主控力", ["別張"])])

    def test_card_without_a_book_is_reviewed_without_book_context(self):
        reviewer = FakeReviewer()
        cards = FakeCards([_card(book="")])
        _use_case(cards, reviewer).execute()
        self.assertEqual(cards.titles_read, [])
        self.assertEqual(reviewer.summaries, [])
        self.assertEqual(reviewer.reviewed[0][1:], ("", "", []))
        self.assertEqual(len(cards.written), 1)


class TestSkips(unittest.TestCase):
    def _skip_reason(self, blocks):
        reviewer = FakeReviewer()
        cards = FakeCards([_card()], {"p1": blocks})
        report = _use_case(cards, reviewer).execute()
        self.assertEqual(reviewer.reviewed, [])
        self.assertEqual(cards.written, [])
        [(title, reason)] = report.skipped
        self.assertEqual(title, "原標題")
        return reason

    def test_card_without_a_highlight_cannot_be_checked_against_the_source(self):
        self.assertIn("原文", self._skip_reason([CardBlock("paragraph", "內文")]))

    def test_card_without_content(self):
        self.assertIn("內文", self._skip_reason([CardBlock("quote", "原文劃線")]))

    def test_version_already_reviewed_spends_no_model_time(self):
        mark = fingerprint("原標題", parse_card_body(REVIEW_ONLY))
        blocks = REVIEW_ONLY + [CardBlock("toggle", f"{RESULT_MARKER} 2026-11-01｜通過〔{mark}〕")]
        self.assertIn("審過", self._skip_reason(blocks))

    def test_editing_the_card_after_a_result_triggers_another_review(self):
        mark = fingerprint("原標題", parse_card_body(REVIEW_ONLY))
        blocks = [
            CardBlock("paragraph", "改過的內文"),
            CardBlock("quote", "原文劃線"),
            CardBlock("toggle", f"{RESULT_MARKER} 2026-11-01｜通過〔{mark}〕"),
        ]
        cards = FakeCards([_card()], {"p1": blocks})
        report = _use_case(cards).execute()
        self.assertEqual(report.reviewed, ["原標題"])
        self.assertEqual(len(cards.written), 1)


class TestFailures(unittest.TestCase):
    def test_unavailable_reviewer_aborts_before_writing_anything(self):
        cards = FakeCards([_card()])
        report = _use_case(cards, FakeReviewer(available=False)).execute()
        self.assertTrue(report.aborted)
        self.assertEqual(cards.written, [])

    def test_unavailable_reviewer_does_not_matter_when_nothing_needs_a_review(self):
        mark = fingerprint("原標題", parse_card_body(REVIEW_ONLY))
        blocks = REVIEW_ONLY + [CardBlock("toggle", f"{RESULT_MARKER} 2026-11-01｜通過〔{mark}〕")]
        report = _use_case(FakeCards([_card()], {"p1": blocks}),
                           FakeReviewer(available=False)).execute()
        self.assertEqual(report.aborted, "")

    def _assert_failed_and_retried_next_run(self, cards, reviewer, enhancer=None):
        report = _use_case(cards, reviewer, enhancer).execute()
        self.assertEqual([t for t, _ in report.failed], ["原標題"])
        # 什麼都沒寫 = 沒有指紋 = 下次重跑會再試
        self.assertEqual(cards.written, [])

    def test_unparseable_review_writes_nothing(self):
        self._assert_failed_and_retried_next_run(
            FakeCards([_card()]), FakeReviewer(reviews=[None]))

    def test_failed_regeneration_writes_nothing(self):
        self._assert_failed_and_retried_next_run(
            FakeCards([_card()], {"p1": WITH_NOTE}), FakeReviewer(), FakeEnhancer(result=None))

    def test_unparseable_candidate_review_writes_nothing(self):
        self._assert_failed_and_retried_next_run(
            FakeCards([_card()], {"p1": WITH_NOTE}),
            FakeReviewer(reviews=[CardReview(4, 4, 4, 4), None]))

    def test_one_failure_does_not_stop_the_other_cards(self):
        cards = FakeCards([_card("p1", "壞掉的"), _card("p2", "好的")])
        cards.fail_reading.add("p1")
        report = _use_case(cards).execute()
        self.assertEqual([t for t, _ in report.failed], ["壞掉的"])
        self.assertEqual(report.reviewed, ["好的"])


class TestDryRun(unittest.TestCase):
    def test_lists_what_each_card_would_get_without_model_or_writes(self):
        reviewer = FakeReviewer(available=False)
        enhancer = FakeEnhancer()
        cards = FakeCards([_card("p1", "只審的"), _card("p2", "重產的")], {"p2": WITH_NOTE})
        report = _use_case(cards, reviewer, enhancer).execute(dry_run=True)
        self.assertEqual(reviewer.reviewed, [])
        self.assertEqual(reviewer.summaries, [])
        self.assertEqual(enhancer.calls, [])
        self.assertEqual(cards.written, [])
        self.assertEqual(report.aborted, "")
        plan = dict(report.planned)
        self.assertIn("只審", plan["只審的"])
        self.assertIn("重產", plan["重產的"])

    def test_still_reports_cards_it_would_skip(self):
        report = _use_case(FakeCards([_card()], {"p1": [CardBlock("paragraph", "內文")]})
                           ).execute(dry_run=True)
        self.assertEqual(report.planned, [])
        self.assertEqual(len(report.skipped), 1)


if __name__ == "__main__":
    unittest.main()
