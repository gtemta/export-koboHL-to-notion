"""Tests for local JSON persistence + resume — improvement #5."""
import json
import os
import shutil
import tempfile
import unittest

from src.application.use_cases.generate_book_cards_use_case import (
    GenerateBookCardsUseCase,
)
from src.infrastructure.persistence.card_store import CardStore
from zettelkasten_generator import GenerationResult, ZettelkastenCard


def _card(title="卡片", bookmark_id="BM-1"):
    return ZettelkastenCard(
        id="id-1", title=title, content="內容", source_highlight="劃線",
        chapter_reference="第一章", chapter_progress=0.5,
        source_bookmark_id=bookmark_id, tags=["習慣", "複利"],
        review_status="passed",
        review_scores={"consistency": 4, "correctness": 5,
                       "shareability": 4, "atomicity": 4},
        review_notes="說明", review_model="qwen3:8b", regenerated=True,
    )


class TestCardRoundTrip(unittest.TestCase):
    def test_to_from_dict_preserves_fields(self):
        card = _card()
        rebuilt = ZettelkastenCard.from_dict(card.to_dict())
        for attr in ("title", "content", "source_highlight", "chapter_reference",
                     "chapter_progress", "source_bookmark_id", "tags",
                     "review_status", "review_scores", "review_notes",
                     "review_model", "regenerated"):
            self.assertEqual(getattr(rebuilt, attr), getattr(card, attr), attr)

    def test_from_dict_tolerates_json_without_review_fields(self):
        # cards_output/*.json written before the review gate existed
        legacy = {
            "id": "old", "title": "舊卡", "content": "內容",
            "source_highlight": "劃線", "chapter_reference": "第一章",
            "chapter_progress": 0.3, "source_bookmark_id": "BM-9",
            "tags": ["習慣"], "quality_score": 7, "revision_notes": "",
        }
        rebuilt = ZettelkastenCard.from_dict(legacy)
        self.assertEqual(rebuilt.title, "舊卡")
        self.assertEqual(rebuilt.review_status, "pending")
        self.assertEqual(rebuilt.review_scores, {})
        self.assertFalse(rebuilt.regenerated)


class TestCardStore(unittest.TestCase):
    def setUp(self):
        self._dir = tempfile.mkdtemp()
        self.store = CardStore(output_dir=self._dir)

    def tearDown(self):
        shutil.rmtree(self._dir, ignore_errors=True)

    def test_save_then_load_pending(self):
        path = self.store.save("我的書", [_card()])
        self.assertIsNotNone(path)
        pending = self.store.load_pending("我的書")
        self.assertIsNotNone(pending)
        loaded_path, cards = pending
        self.assertEqual(loaded_path, path)
        self.assertEqual(len(cards), 1)
        self.assertEqual(cards[0].source_bookmark_id, "BM-1")

    def test_mark_uploaded_hides_from_pending(self):
        path = self.store.save("我的書", [_card()])
        self.store.mark_uploaded(path)
        self.assertIsNone(self.store.load_pending("我的書"))

    def test_load_pending_none_when_empty(self):
        self.assertIsNone(self.store.load_pending("不存在的書"))

    def test_save_empty_returns_none(self):
        self.assertIsNone(self.store.save("我的書", []))

    def test_rejected_recorded_but_never_resumed(self):
        rejected = _card(title="被退回的卡", bookmark_id="BM-2")
        path = self.store.save("我的書", [_card()], [rejected])
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        self.assertEqual([c["title"] for c in data["rejected"]], ["被退回的卡"])
        # load_pending only ever hands back `cards`
        _, cards = self.store.load_pending("我的書")
        self.assertEqual([c.title for c in cards], ["卡片"])

    def test_all_rejected_saves_record_but_stays_out_of_pending(self):
        path = self.store.save("我的書", [], [_card(title="被退回的卡")])
        self.assertTrue(os.path.exists(path))
        # nothing passed → nothing to upload → nothing to resume
        self.assertIsNone(self.store.load_pending("我的書"))

    def test_slug_sanitizes_illegal_chars(self):
        path = self.store.save('書:名/含*非法?字元', [_card()])
        self.assertIsNotNone(path)
        # round-trips through the same slug logic
        self.assertIsNotNone(self.store.load_pending('書:名/含*非法?字元'))


class _FakeGenerator:
    def __init__(self, cards):
        self.cards = cards
        self.calls = 0

    def generate_cards_with_review(self, highlight_dicts, book_title):
        self.calls += 1
        return GenerationResult(passed=list(self.cards), rejected=[])


class _FakeRepo:
    def __init__(self, fail_first=False):
        self.uploaded = []
        self.fail_first = fail_first
        self.calls = 0

    def upload_cards(self, cards, book_title, source_page_id=None, percent_read=None):
        self.calls += 1
        if self.fail_first and self.calls == 1:
            raise RuntimeError("simulated upload failure")
        self.uploaded.append((book_title, list(cards)))
        return len(cards)


class _Book:
    def __init__(self, title):
        self.title = title
        self.percent_read = None


class TestUseCaseResume(unittest.TestCase):
    def setUp(self):
        self._dir = tempfile.mkdtemp()
        self.store = CardStore(output_dir=self._dir)

    def tearDown(self):
        shutil.rmtree(self._dir, ignore_errors=True)

    def test_failed_upload_resumes_without_regenerating(self):
        cards = [_card()]
        gen = _FakeGenerator(cards)
        repo = _FakeRepo(fail_first=True)
        uc = GenerateBookCardsUseCase(gen, repo, card_store=self.store)
        book = _Book("我的書")

        # First run: generation succeeds, save happens, upload FAILS.
        result1 = uc.execute(book, highlights=[])
        self.assertEqual(result1, 0)
        self.assertEqual(gen.calls, 1)
        self.assertIsNotNone(self.store.load_pending("我的書"))  # still pending

        # Second run: resume the saved cards, do NOT call the generator again.
        result2 = uc.execute(book, highlights=[])
        self.assertEqual(result2, 1)
        self.assertEqual(gen.calls, 1)  # generator not re-invoked
        self.assertEqual(len(repo.uploaded), 1)
        self.assertIsNone(self.store.load_pending("我的書"))  # marked uploaded


if __name__ == "__main__":
    unittest.main()
