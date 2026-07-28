"""Notion write-back stays free of review data.

The review gate decides whether a card reaches Notion at all, so nothing in the
card box should expose scores, a review status or the reviewer's notes.
"""
import unittest

from src.infrastructure.notion.zettelkasten_card_repository import (
    _KEYWORD_PROPERTY,
    _SOURCE_ID_PROPERTY,
    ZettelkastenCardRepository,
)
from zettelkasten_generator import ZettelkastenCard


def _card(title="t", **overrides):
    kwargs = dict(
        id="id", title=title, content="c", source_highlight="h",
        chapter_reference="ch", chapter_progress=0.5,
        review_status="passed",
        review_scores={"consistency": 4, "correctness": 5,
                       "shareability": 4, "atomicity": 4},
        review_notes="把標題改得更精準",
        review_model="qwen3:8b",
        tags=["習慣", "複利"],
    )
    kwargs.update(overrides)
    return ZettelkastenCard(**kwargs)


def _repo(schema=None):
    repo = ZettelkastenCardRepository(token="dummy", database_id="db")
    # Pre-seed the schema cache so no network call happens.
    #   schema=None  -> "schema unreadable": write everything (legacy behaviour)
    #   schema=set() -> known, so optional props are gated
    repo._schema_props = schema
    return repo


class TestNoReviewDataInNotion(unittest.TestCase):
    def test_no_score_or_status_properties(self):
        # schema=None is the write-everything fallback — even then, nothing
        # review-related may leak into the page properties.
        props = _repo(None)._build_properties(_card(), books_page_id=None)
        for leaked in ("品質分數", "狀態"):
            self.assertNotIn(leaked, props)

    def test_no_review_toggle_in_page_body(self):
        blocks = _repo(None)._build_children(_card())
        self.assertEqual([b for b in blocks if b["type"] == "toggle"], [])

    def test_page_body_keeps_content_quote_and_chapter(self):
        types = [b["type"] for b in _repo(None)._build_children(_card())]
        self.assertEqual(types, ["paragraph", "quote", "callout"])


class TestSchemaGating(unittest.TestCase):
    def test_absent_optional_props_dropped(self):
        # DB only has the title property -> optional props must not be written.
        props = _repo({"標題"})._build_properties(_card(), books_page_id=None)
        self.assertEqual(list(props.keys()), ["標題"])

    def test_present_props_written(self):
        schema = {"標題", _SOURCE_ID_PROPERTY}
        props = _repo(schema)._build_properties(_card(), books_page_id=None)
        self.assertIn(_SOURCE_ID_PROPERTY, props)
        self.assertNotIn(_KEYWORD_PROPERTY, props)  # not in schema

    def test_unreadable_schema_writes_all(self):
        props = _repo(None)._build_properties(_card(), books_page_id=None)
        self.assertIn(_SOURCE_ID_PROPERTY, props)
        self.assertIn(_KEYWORD_PROPERTY, props)


if __name__ == "__main__":
    unittest.main()
