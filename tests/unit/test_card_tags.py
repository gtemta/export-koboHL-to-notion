"""Tests for card tagging: free concept tags → Key Word, fixed categories → Tags.

Covers Phase 1 E2/E3 plus Phase 2 T1 (the 【標籤】 separators the model actually
uses instead of the 頓號 the prompt asks for).
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

    def test_prompt_forbids_gluing_separators(self):
        enhancer = ZettelkastenLLMEnhancer()
        for prompt in (enhancer._build_prompt("文字", "書名"),
                       enhancer._build_batch_prompt([{"text": "a"}], "書名")):
            self.assertIn("只能用頓號", prompt)


class TestGluedTagSeparators(unittest.TestCase):
    """T1: real failures observed in cards_output/*.json and live runs.

    Each of these used to survive _TAG_SPLIT intact and land in Notion's
    Key Word column as one unusable mega-tag.
    """

    def _tags(self, tag_line):
        return ZettelkastenLLMEnhancer._extract_tags(f"【標籤】{tag_line}")

    def test_fullwidth_colon(self):
        # 《多巴胺國度》全書 16 張都長這樣
        self.assertEqual(self._tags("語言演化：社交結構：謊言藝術"),
                         ["語言演化", "社交結構", "謊言藝術"])

    def test_em_dash(self):
        # 《大威脅》
        self.assertEqual(self._tags("資本結構—負債比率—金融風險"),
                         ["資本結構", "負債比率", "金融風險"])

    def test_leading_middle_dot(self):
        # 《說理Ⅱ》— note the leading ・
        self.assertEqual(self._tags("・說服論述・故事架構・聽眾心理"),
                         ["說服論述", "故事架構", "聽眾心理"])

    def test_full_stop(self):
        self.assertEqual(self._tags("環境心理學。習慣建立。行動科學"),
                         ["環境心理學", "習慣建立", "行動科學"])

    def test_ascii_hyphen(self):
        self.assertEqual(self._tags("習慣-複利-一致性"), ["習慣", "複利", "一致性"])

    def test_mixed_separators(self):
        self.assertEqual(self._tags("學習方法, 內在動力・知識轉化"),
                         ["學習方法", "內在動力", "知識轉化"])

    def test_hash_and_brackets_stripped(self):
        self.assertEqual(self._tags("#習慣、「複利」、（系統）"),
                         ["習慣", "複利", "系統"])

    def test_sentence_length_tag_dropped(self):
        # not a concept — the model wrote prose on the 標籤 line
        self.assertEqual(
            self._tags("這是一句完全沒有分隔符號而且長到不可能是概念標籤的句子"), [])

    def test_duplicates_deduped(self):
        self.assertEqual(self._tags("習慣、習慣、複利"), ["習慣", "複利"])

    def test_punctuation_only_yields_nothing(self):
        self.assertEqual(self._tags("、、—・"), [])


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
