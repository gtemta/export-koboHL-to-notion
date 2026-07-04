"""Tests for local JSON persistence + resume — improvement #5."""
import shutil
import tempfile
import unittest

from zettelkasten_generator import ZettelkastenCard
from src.infrastructure.persistence.card_store import CardStore
from src.application.use_cases.generate_book_cards_use_case import (
    GenerateBookCardsUseCase,
)


def _card(title="卡片", bookmark_id="BM-1"):
    return ZettelkastenCard(
        id="id-1", title=title, content="內容", source_highlight="劃線",
        chapter_reference="第一章", chapter_progress=0.5,
        quality_score=8, revision_notes="說明", source_bookmark_id=bookmark_id,
        tags=["習慣", "複利"],
    )


class TestCardRoundTrip(unittest.TestCase):
    def test_to_from_dict_preserves_fields(self):
        card = _card()
        rebuilt = ZettelkastenCard.from_dict(card.to_dict())
        for attr in ("title", "content", "source_highlight", "chapter_reference",
                     "chapter_progress", "quality_score", "revision_notes",
                     "source_bookmark_id", "tags"):
            self.assertEqual(getattr(rebuilt, attr), getattr(card, attr), attr)


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

    def test_slug_sanitizes_illegal_chars(self):
        path = self.store.save('書:名/含*非法?字元', [_card()])
        self.assertIsNotNone(path)
        # round-trips through the same slug logic
        self.assertIsNotNone(self.store.load_pending('書:名/含*非法?字元'))


class _FakeGenerator:
    def __init__(self, cards):
        self.cards = cards
        self.calls = 0

    def generate_cards(self, highlight_dicts, book_title):
        self.calls += 1
        return self.cards


class _FakeRepo:
    def __init__(self, fail_first=False):
        self.uploaded = []
        self.fail_first = fail_first
        self.calls = 0

    def upload_cards(self, cards, book_title):
        self.calls += 1
        if self.fail_first and self.calls == 1:
            raise RuntimeError("simulated upload failure")
        self.uploaded.append((book_title, list(cards)))
        return len(cards)


class _Book:
    def __init__(self, title):
        self.title = title


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
