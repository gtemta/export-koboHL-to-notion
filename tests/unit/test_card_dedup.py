"""Tests for highlight-granularity card dedup — improvement #2."""
import unittest

from zettelkasten_generator import ZettelkastenCard
from src.infrastructure.notion.zettelkasten_card_repository import (
    ZettelkastenCardRepository,
    _SOURCE_ID_PROPERTY,
)


def _card(title="卡片", highlight="來源劃線文字", bookmark_id=""):
    return ZettelkastenCard(
        id="id",
        title=title,
        content="內容",
        source_highlight=highlight,
        chapter_reference="第一章",
        chapter_progress=0.5,
        source_bookmark_id=bookmark_id,
    )


def _repo():
    # Client(auth=...) does no network at construction.
    repo = ZettelkastenCardRepository(token="dummy", database_id="db")
    repo._schema_props = None  # skip schema fetch; write all props (legacy path)
    return repo


class TestCardSourceId(unittest.TestCase):
    def test_prefers_bookmark_id(self):
        self.assertEqual(
            ZettelkastenCardRepository._card_source_id(_card(bookmark_id="BM-123")),
            "BM-123",
        )

    def test_hash_fallback_when_no_bookmark_id(self):
        sid = ZettelkastenCardRepository._card_source_id(_card(highlight="同一段文字"))
        self.assertTrue(sid.startswith("sha1:"))

    def test_hash_is_stable_for_same_text(self):
        a = ZettelkastenCardRepository._card_source_id(_card(highlight="重複文字"))
        b = ZettelkastenCardRepository._card_source_id(_card(highlight="重複文字"))
        self.assertEqual(a, b)

    def test_hash_differs_for_different_text(self):
        a = ZettelkastenCardRepository._card_source_id(_card(highlight="文字A"))
        b = ZettelkastenCardRepository._card_source_id(_card(highlight="文字B"))
        self.assertNotEqual(a, b)


class TestFilterNewCards(unittest.TestCase):
    def test_skips_already_uploaded(self):
        cards = [_card(bookmark_id="A"), _card(bookmark_id="B")]
        pending = ZettelkastenCardRepository._filter_new_cards(cards, {"A"})
        self.assertEqual([c.source_bookmark_id for c in pending], ["B"])

    def test_dedups_within_batch(self):
        cards = [_card(bookmark_id="A"), _card(bookmark_id="A")]
        pending = ZettelkastenCardRepository._filter_new_cards(cards, set())
        self.assertEqual(len(pending), 1)

    def test_all_new_when_no_done_ids(self):
        cards = [_card(bookmark_id="A"), _card(bookmark_id="B")]
        pending = ZettelkastenCardRepository._filter_new_cards(cards, set())
        self.assertEqual(len(pending), 2)


class TestReadSourceIdProperty(unittest.TestCase):
    def test_reads_plain_text(self):
        page = {"properties": {_SOURCE_ID_PROPERTY: {
            "rich_text": [{"plain_text": "BM-9"}]}}}
        self.assertEqual(
            ZettelkastenCardRepository._read_source_id_property(page), "BM-9")

    def test_missing_property_returns_empty(self):
        self.assertEqual(
            ZettelkastenCardRepository._read_source_id_property({"properties": {}}), "")


class TestBuildProperties(unittest.TestCase):
    def test_includes_source_id_property(self):
        repo = _repo()
        props = repo._build_properties(_card(bookmark_id="BM-7"), books_page_id=None)
        self.assertIn(_SOURCE_ID_PROPERTY, props)
        self.assertEqual(
            props[_SOURCE_ID_PROPERTY]["rich_text"][0]["text"]["content"], "BM-7")


if __name__ == "__main__":
    unittest.main()
