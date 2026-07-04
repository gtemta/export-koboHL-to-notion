"""Tests for concept tags on cards — improvement #3-1."""
import unittest

from zettelkasten_generator import ZettelkastenLLMEnhancer, ZettelkastenCard
from src.infrastructure.notion.zettelkasten_card_repository import (
    ZettelkastenCardRepository,
    _TOPIC_PROPERTY,
)


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

    def test_hash_and_spaces(self):
        text = "【標籤】#習慣 #複利"
        self.assertEqual(ZettelkastenLLMEnhancer._extract_tags(text), ["習慣", "複利"])

    def test_dedups(self):
        text = "【標籤】習慣、習慣、複利"
        self.assertEqual(ZettelkastenLLMEnhancer._extract_tags(text), ["習慣", "複利"])

    def test_stops_before_next_card(self):
        text = "【標籤】習慣、複利\n### CARD_2\n【標題】其他"
        self.assertEqual(ZettelkastenLLMEnhancer._extract_tags(text), ["習慣", "複利"])

    def test_prompt_asks_for_tags(self):
        enhancer = ZettelkastenLLMEnhancer()
        self.assertIn("【標籤】", enhancer._build_prompt("文字", "書名"))
        self.assertIn("【標籤】", enhancer._build_batch_prompt([{"text": "a"}], "書名"))


def _card(tags):
    return ZettelkastenCard(
        id="id", title="t", content="c", source_highlight="h",
        chapter_reference="ch", chapter_progress=0.5, tags=tags,
    )


class TestTagProperties(unittest.TestCase):
    def setUp(self):
        self.repo = ZettelkastenCardRepository(token="dummy", database_id="db")
        self.repo._schema_props = None  # skip schema fetch; write all props

    def test_multi_select_written(self):
        props = self.repo._build_properties(_card(["習慣", "複利"]), books_page_id=None)
        names = [o["name"] for o in props[_TOPIC_PROPERTY]["multi_select"]]
        self.assertEqual(names, ["習慣", "複利"])

    def test_no_property_when_no_tags(self):
        props = self.repo._build_properties(_card([]), books_page_id=None)
        self.assertNotIn(_TOPIC_PROPERTY, props)

    def test_commas_stripped_from_option_names(self):
        opts = ZettelkastenCardRepository._tag_options(_card(["習慣,複利"]))
        self.assertEqual(opts[0]["name"], "習慣複利")


if __name__ == "__main__":
    unittest.main()
