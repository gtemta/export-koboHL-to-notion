"""Tests for card tagging: free concept tags → Key Word, fixed categories → Tags.

Covers Phase 1 E2/E3 of the knowledge-refinement plan. The 【標籤】 extraction
tests still guard the generator's concept-tag parsing (Phase 2 revisits _TAG_SPLIT).
"""
import unittest

from src.infrastructure.notion.zettelkasten_card_repository import (
    _KEYWORD_PROPERTY,
    _TAGS_PROPERTY,
    ZettelkastenCardRepository,
)
from zettelkasten_generator import ZettelkastenCard, ZettelkastenLLMEnhancer


class TestExtractTags(unittest.TestCase):
    def test_ideographic_comma(self):
        text = "【標題】複利\n【內容】內容\n【標籤】習慣、複利、系統思考"
        self.assertEqual(
            ZettelkastenLLMEnhancer._extract_tags(text),
            ["習慣", "複利", "系統思考"],
        )

    def test_missing_tag_line(self):
        self.assertEqual(
            ZettelkastenLLMEnhancer._extract_tags("【標題】x\n【內容】y"), [])

    def test_limit_three(self):
        text = "【標籤】一、二、三、四、五"
        self.assertEqual(ZettelkastenLLMEnhancer._extract_tags(text), ["一", "二", "三"])

    def test_prompt_asks_for_tags(self):
        enhancer = ZettelkastenLLMEnhancer()
        self.assertIn("【標籤】", enhancer._build_prompt("文字", "書名"))
        self.assertIn("【標籤】", enhancer._build_batch_prompt([{"text": "a"}], "書名"))


def _card(tags=None, categories=None):
    return ZettelkastenCard(
        id="id", title="t", content="c", source_highlight="h",
        chapter_reference="ch", chapter_progress=0.5,
        tags=list(tags or []), categories=list(categories or []),
    )


def _repo(schema=None, tag_categories=None):
    repo = ZettelkastenCardRepository(
        token="dummy", database_id="db", tag_categories=tag_categories,
    )
    repo._schema_props = schema  # None → write-all; set() → gated
    return repo


class TestKeyWordProperty(unittest.TestCase):
    """E2: free concept tags are joined by 、 into the Key Word rich_text."""

    def test_tags_joined_into_key_word(self):
        props = _repo()._build_properties(_card(tags=["習慣", "複利"]), books_page_id=None)
        content = props[_KEYWORD_PROPERTY]["rich_text"][0]["text"]["content"]
        self.assertEqual(content, "習慣、複利")

    def test_no_key_word_when_no_tags(self):
        props = _repo()._build_properties(_card(tags=[]), books_page_id=None)
        self.assertNotIn(_KEYWORD_PROPERTY, props)

    def test_key_word_gated_by_schema(self):
        props = _repo(schema={"標題"})._build_properties(
            _card(tags=["習慣"]), books_page_id=None)
        self.assertNotIn(_KEYWORD_PROPERTY, props)


class TestTagsProperty(unittest.TestCase):
    """E3: fixed-category classification goes to the Tags multi_select."""

    def test_categories_written_as_multi_select(self):
        repo = _repo(tag_categories=["💞心理學", "🧠學習技巧"])
        props = repo._build_properties(
            _card(categories=["💞心理學", "🧠學習技巧"]), books_page_id=None)
        names = [o["name"] for o in props[_TAGS_PROPERTY]["multi_select"]]
        self.assertEqual(names, ["💞心理學", "🧠學習技巧"])

    def test_categories_outside_allowed_list_dropped(self):
        repo = _repo(tag_categories=["💞心理學"])
        props = repo._build_properties(
            _card(categories=["💞心理學", "亂造分類"]), books_page_id=None)
        names = [o["name"] for o in props[_TAGS_PROPERTY]["multi_select"]]
        self.assertEqual(names, ["💞心理學"])

    def test_no_tags_property_when_all_dropped(self):
        repo = _repo(tag_categories=["💞心理學"])
        props = repo._build_properties(_card(categories=["不在清單"]), books_page_id=None)
        self.assertNotIn(_TAGS_PROPERTY, props)

    def test_categories_passthrough_when_no_allowed_list(self):
        # repo has no configured list → categories pass through de-duped
        repo = _repo(tag_categories=None)
        props = repo._build_properties(
            _card(categories=["任意", "任意", "另一"]), books_page_id=None)
        names = [o["name"] for o in props[_TAGS_PROPERTY]["multi_select"]]
        self.assertEqual(names, ["任意", "另一"])


if __name__ == "__main__":
    unittest.main()
