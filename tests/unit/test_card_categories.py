"""Phase 1 unit tests: classification parsing (E3), book-title matching (E4),
tag-category settings, and ZettelkastenCard.categories back-compat."""
import unittest

from src.config.settings import DEFAULT_TAG_CATEGORIES, Settings
from src.infrastructure.notion.zettelkasten_card_repository import (
    ZettelkastenCardRepository,
)
from zettelkasten_generator import ZettelkastenCard, ZettelkastenLLMEnhancer

ALLOWED = ["💞心理學", "🧠學習技巧", "💼商務", "🧘‍♂️人生觀點"]


class TestParseClassification(unittest.TestCase):
    """E3: per-card `CARD_i: 分類` lines → filtered category lists."""

    def test_basic_lines(self):
        text = "CARD_1：💞心理學、🧠學習技巧\nCARD_2：💼商務"
        parsed = ZettelkastenLLMEnhancer._parse_classification(text, 2, ALLOWED)
        self.assertEqual(parsed, [["💞心理學", "🧠學習技巧"], ["💼商務"]])

    def test_drops_values_outside_allowed(self):
        text = "CARD_1：💞心理學、亂造的分類"
        parsed = ZettelkastenLLMEnhancer._parse_classification(text, 1, ALLOWED)
        self.assertEqual(parsed, [["💞心理學"]])

    def test_empty_when_nothing_matches(self):
        text = "CARD_1：完全不相關"
        parsed = ZettelkastenLLMEnhancer._parse_classification(text, 1, ALLOWED)
        self.assertEqual(parsed, [[]])

    def test_caps_at_two(self):
        text = "CARD_1：💞心理學、🧠學習技巧、💼商務、🧘‍♂️人生觀點"
        parsed = ZettelkastenLLMEnhancer._parse_classification(text, 1, ALLOWED)
        self.assertEqual(len(parsed[0]), 2)

    def test_missing_card_stays_empty(self):
        text = "CARD_1：💞心理學"
        parsed = ZettelkastenLLMEnhancer._parse_classification(text, 3, ALLOWED)
        self.assertEqual(parsed, [["💞心理學"], [], []])

    def test_out_of_range_index_ignored(self):
        text = "CARD_9：💞心理學"
        parsed = ZettelkastenLLMEnhancer._parse_classification(text, 2, ALLOWED)
        self.assertEqual(parsed, [[], []])

    def test_strips_thinking_prefix(self):
        text = "Thinking...\nreasoning\n...done thinking.\nCARD_1：💼商務"
        parsed = ZettelkastenLLMEnhancer._parse_classification(text, 1, ALLOWED)
        self.assertEqual(parsed, [["💼商務"]])

    def test_no_allowed_list_returns_empty(self):
        parsed = ZettelkastenLLMEnhancer._parse_classification("CARD_1：x", 1, [])
        self.assertEqual(parsed, [[]])


class TestBookTitleMatching(unittest.TestCase):
    """E4: main-title extraction + normalization used for fuzzy Books-DB match."""

    def test_splits_on_halfwidth_colon(self):
        self.assertEqual(ZettelkastenCardRepository._main_title("原子習慣: 副標"), "原子習慣")

    def test_splits_on_fullwidth_colon(self):
        self.assertEqual(ZettelkastenCardRepository._main_title("原子習慣：副標題"), "原子習慣")

    def test_normalize_fullwidth_space(self):
        self.assertEqual(ZettelkastenCardRepository._normalize("原子　習慣  "), "原子 習慣")

    def test_no_colon_returns_whole_title(self):
        self.assertEqual(ZettelkastenCardRepository._main_title("多巴胺國度"), "多巴胺國度")


class TestTagCategorySettings(unittest.TestCase):
    def test_default_when_unset(self):
        self.assertEqual(Settings._parse_tag_categories(None), DEFAULT_TAG_CATEGORIES)

    def test_default_when_blank(self):
        self.assertEqual(Settings._parse_tag_categories("   "), DEFAULT_TAG_CATEGORIES)

    def test_parses_comma_separated(self):
        self.assertEqual(
            Settings._parse_tag_categories("A, B ,C"), ["A", "B", "C"])


class TestCategoriesBackCompat(unittest.TestCase):
    def test_from_dict_without_categories(self):
        # JSON produced before the categories field existed must still load.
        card = ZettelkastenCard.from_dict({"id": "x", "title": "t", "content": "c"})
        self.assertEqual(card.categories, [])

    def test_roundtrip_preserves_categories(self):
        card = ZettelkastenCard(
            id="x", title="t", content="c", source_highlight="h",
            chapter_reference="ch", chapter_progress=0.0,
            categories=["💞心理學"],
        )
        self.assertEqual(ZettelkastenCard.from_dict(card.to_dict()).categories, ["💞心理學"])


if __name__ == "__main__":
    unittest.main()
