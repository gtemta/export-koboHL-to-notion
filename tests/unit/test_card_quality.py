"""Tests for quality score / status / revision-note write-back — improvement #4."""
import unittest

from zettelkasten_generator import ZettelkastenCard
from src.infrastructure.notion.zettelkasten_card_repository import (
    ZettelkastenCardRepository,
    _QUALITY_PROPERTY,
    _STATUS_PROPERTY,
    _STATUS_DRAFT,
    _STATUS_REVIEWED,
    _SOURCE_ID_PROPERTY,
)


def _card(quality_score=0, revision_notes="", title="t"):
    return ZettelkastenCard(
        id="id", title=title, content="c", source_highlight="h",
        chapter_reference="ch", chapter_progress=0.5,
        quality_score=quality_score, revision_notes=revision_notes,
    )


def _repo(schema=None):
    repo = ZettelkastenCardRepository(token="dummy", database_id="db")
    # Pre-seed the schema cache so no network call happens.
    #   schema=None  -> "schema unreadable": write everything (legacy behaviour)
    #   schema=set() -> known, so optional props are gated
    repo._schema_props = schema
    return repo


class TestStatusName(unittest.TestCase):
    def test_reviewed_when_score_high(self):
        self.assertEqual(ZettelkastenCardRepository._status_name(_card(8)), _STATUS_REVIEWED)

    def test_draft_when_score_low(self):
        self.assertEqual(ZettelkastenCardRepository._status_name(_card(5)), _STATUS_DRAFT)

    def test_draft_when_no_score(self):
        self.assertEqual(ZettelkastenCardRepository._status_name(_card(0)), _STATUS_DRAFT)


class TestQualityProperties(unittest.TestCase):
    def test_score_and_status_written(self):
        props = _repo(None)._build_properties(_card(quality_score=9), books_page_id=None)
        self.assertEqual(props[_QUALITY_PROPERTY]["number"], 9)
        self.assertEqual(props[_STATUS_PROPERTY]["select"]["name"], _STATUS_REVIEWED)

    def test_no_score_omits_quality_but_keeps_status(self):
        props = _repo(None)._build_properties(_card(quality_score=0), books_page_id=None)
        self.assertNotIn(_QUALITY_PROPERTY, props)
        self.assertEqual(props[_STATUS_PROPERTY]["select"]["name"], _STATUS_DRAFT)


class TestSchemaGating(unittest.TestCase):
    def test_absent_optional_props_dropped(self):
        # DB only has the title property -> optional props must not be written.
        props = _repo({"標題"})._build_properties(_card(quality_score=9), books_page_id=None)
        self.assertEqual(list(props.keys()), ["標題"])

    def test_present_props_written(self):
        schema = {"標題", _QUALITY_PROPERTY, _SOURCE_ID_PROPERTY}
        props = _repo(schema)._build_properties(_card(quality_score=9), books_page_id=None)
        self.assertIn(_QUALITY_PROPERTY, props)
        self.assertIn(_SOURCE_ID_PROPERTY, props)
        self.assertNotIn(_STATUS_PROPERTY, props)  # not in schema

    def test_unreadable_schema_writes_all(self):
        props = _repo(None)._build_properties(_card(quality_score=9), books_page_id=None)
        self.assertIn(_STATUS_PROPERTY, props)
        self.assertIn(_SOURCE_ID_PROPERTY, props)


class TestRevisionToggle(unittest.TestCase):
    def test_toggle_added_when_notes_present(self):
        blocks = _repo(None)._build_children(_card(revision_notes="把標題改得更精準"))
        toggles = [b for b in blocks if b["type"] == "toggle"]
        self.assertEqual(len(toggles), 1)
        child_text = toggles[0]["toggle"]["children"][0]["paragraph"]["rich_text"][0]["text"]["content"]
        self.assertEqual(child_text, "把標題改得更精準")

    def test_no_toggle_without_notes(self):
        blocks = _repo(None)._build_children(_card(revision_notes=""))
        self.assertEqual([b for b in blocks if b["type"] == "toggle"], [])


if __name__ == "__main__":
    unittest.main()
