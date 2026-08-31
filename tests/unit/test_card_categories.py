"""Phase 1 unit tests: classification parsing (E3), book-title matching (E4),
tag-category settings, and ZettelkastenCard.categories back-compat."""
import unittest
from unittest.mock import patch

from src.config.settings import DEFAULT_TAG_CATEGORIES, Settings
from src.infrastructure.notion.zettelkasten_card_repository import (
    ZettelkastenCardRepository,
)
from zettelkasten_generator import ZettelkastenCard, ZettelkastenLLMEnhancer

ALLOWED = ["💞心理學", "🧠學習技巧", "💼商務", "🧘‍♂️人生觀點"]


def _make_card(card_id: str, title: str = "t") -> ZettelkastenCard:
    return ZettelkastenCard(
        id=card_id, title=title, content="c", source_highlight="h",
        chapter_reference="ch", chapter_progress=0.0,
    )


class TestParseClassification(unittest.TestCase):
    """E3: 每行 `CARD_i：分類｜emoji` → (categories, icon)。"""

    def test_basic_lines(self):
        text = "CARD_1：💞心理學、🧠學習技巧｜🧭\nCARD_2：💼商務｜🎯"
        parsed = ZettelkastenLLMEnhancer._parse_classification(text, 2, ALLOWED)
        self.assertEqual(
            parsed, [(["💞心理學", "🧠學習技巧"], "🧭"), (["💼商務"], "🎯")])

    def test_drops_values_outside_allowed(self):
        text = "CARD_1：💞心理學、亂造的分類｜🧭"
        parsed = ZettelkastenLLMEnhancer._parse_classification(text, 1, ALLOWED)
        self.assertEqual(parsed, [(["💞心理學"], "🧭")])

    def test_empty_when_nothing_matches(self):
        text = "CARD_1：完全不相關"
        parsed = ZettelkastenLLMEnhancer._parse_classification(text, 1, ALLOWED)
        self.assertEqual(parsed, [([], "")])

    def test_caps_at_two(self):
        text = "CARD_1：💞心理學、🧠學習技巧、💼商務、🧘‍♂️人生觀點｜🧭"
        parsed = ZettelkastenLLMEnhancer._parse_classification(text, 1, ALLOWED)
        self.assertEqual(len(parsed[0][0]), 2)

    def test_missing_card_stays_empty(self):
        text = "CARD_1：💞心理學｜🧭"
        parsed = ZettelkastenLLMEnhancer._parse_classification(text, 3, ALLOWED)
        self.assertEqual(parsed, [(["💞心理學"], "🧭"), ([], ""), ([], "")])

    def test_out_of_range_index_ignored(self):
        text = "CARD_9：💞心理學｜🧭"
        parsed = ZettelkastenLLMEnhancer._parse_classification(text, 2, ALLOWED)
        self.assertEqual(parsed, [([], ""), ([], "")])

    def test_strips_thinking_prefix(self):
        text = "Thinking...\nreasoning\n...done thinking.\nCARD_1：💼商務｜🎯"
        parsed = ZettelkastenLLMEnhancer._parse_classification(text, 1, ALLOWED)
        self.assertEqual(parsed, [(["💼商務"], "🎯")])

    def test_no_allowed_list_returns_empty(self):
        parsed = ZettelkastenLLMEnhancer._parse_classification("CARD_1：x｜🧭", 1, [])
        self.assertEqual(parsed, [([], "")])


class TestParseIcon(unittest.TestCase):
    """icon 解析的容錯 —— 本地小模型幾乎不會完全照格式。"""

    def test_halfwidth_pipe(self):
        parsed = ZettelkastenLLMEnhancer._parse_classification(
            "CARD_1：💼商務|🎯", 1, ALLOWED)
        self.assertEqual(parsed, [(["💼商務"], "🎯")])

    def test_missing_icon_leaves_empty(self):
        parsed = ZettelkastenLLMEnhancer._parse_classification(
            "CARD_1：💼商務", 1, ALLOWED)
        self.assertEqual(parsed, [(["💼商務"], "")])

    def test_off_palette_icon_rejected(self):
        # 🍕 不在調色盤裡 → 視同沒挑，交給 fallback
        parsed = ZettelkastenLLMEnhancer._parse_classification(
            "CARD_1：💼商務｜🍕", 1, ALLOWED)
        self.assertEqual(parsed, [(["💼商務"], "")])

    def test_icon_found_without_separator(self):
        # 格式跑掉但行內有調色盤 emoji → 仍然抓得到
        parsed = ZettelkastenLLMEnhancer._parse_classification(
            "CARD_1：💼商務 🎯", 1, ALLOWED)
        self.assertEqual(parsed, [(["💼商務"], "🎯")])

    def test_first_palette_emoji_wins(self):
        parsed = ZettelkastenLLMEnhancer._parse_classification(
            "CARD_1：💼商務｜🎯 🧭", 1, ALLOWED)
        self.assertEqual(parsed[0][1], "🎯")

    def test_category_emoji_never_mistaken_for_icon(self):
        # 分類自帶的 emoji 與調色盤零交集，所以不會被誤判成 icon
        parsed = ZettelkastenLLMEnhancer._parse_classification(
            "CARD_1：💞心理學", 1, ALLOWED)
        self.assertEqual(parsed, [(["💞心理學"], "")])

    def test_icon_only_line_still_parses(self):
        parsed = ZettelkastenLLMEnhancer._parse_classification(
            "CARD_1：｜🧭", 1, ALLOWED)
        self.assertEqual(parsed, [([], "🧭")])

    def test_pick_palette_emoji_direct(self):
        pick = ZettelkastenLLMEnhancer._pick_palette_emoji
        self.assertEqual(pick("前面 🧭 後面"), "🧭")
        self.assertEqual(pick("沒有 emoji"), "")
        self.assertEqual(pick(""), "")


class TestEmojiInsensitiveMatching(unittest.TestCase):
    """Local models rarely reproduce emoji prefixes — the parser must map the
    plain-text name back to the canonical (emoji-prefixed) category."""

    def test_plain_text_maps_to_canonical(self):
        text = "CARD_1：心理學、學習技巧｜🧭"
        parsed = ZettelkastenLLMEnhancer._parse_classification(text, 1, ALLOWED)
        self.assertEqual(parsed, [(["💞心理學", "🧠學習技巧"], "🧭")])

    def test_zwj_emoji_category_plain_output(self):
        # 🧘‍♂️ is a multi-codepoint ZWJ sequence; plain output must still match.
        text = "CARD_1：人生觀點｜🧭"
        parsed = ZettelkastenLLMEnhancer._parse_classification(text, 1, ALLOWED)
        self.assertEqual(parsed, [(["🧘‍♂️人生觀點"], "🧭")])

    def test_mangled_emoji_still_matches(self):
        # model echoes a partial emoji (🧘 without ZWJ+♂️+VS16)
        text = "CARD_1：🧘人生觀點｜🧭"
        parsed = ZettelkastenLLMEnhancer._parse_classification(text, 1, ALLOWED)
        self.assertEqual(parsed, [(["🧘‍♂️人生觀點"], "🧭")])

    def test_exact_emoji_output_still_matches(self):
        text = "CARD_1：💞心理學｜🧭"
        parsed = ZettelkastenLLMEnhancer._parse_classification(text, 1, ALLOWED)
        self.assertEqual(parsed, [(["💞心理學"], "🧭")])

    def test_invented_category_still_dropped(self):
        text = "CARD_1：心理學、量子力學｜🧭"
        parsed = ZettelkastenLLMEnhancer._parse_classification(text, 1, ALLOWED)
        self.assertEqual(parsed, [(["💞心理學"], "🧭")])

    def test_category_core(self):
        core = ZettelkastenLLMEnhancer._category_core
        self.assertEqual(core("💞心理學"), "心理學")
        self.assertEqual(core("🧘‍♂️人生觀點"), "人生觀點")
        self.assertEqual(core("  學習 技巧  "), "學習技巧")
        self.assertEqual(core(""), "")

    def test_prompt_lists_plain_names(self):
        enhancer = ZettelkastenLLMEnhancer()
        card = ZettelkastenCard(
            id="x", title="t", content="c", source_highlight="h",
            chapter_reference="ch", chapter_progress=0.0,
        )
        prompt = enhancer._build_classification_prompt([card], ALLOWED)
        self.assertIn("心理學", prompt)
        self.assertNotIn("💞心理學", prompt)

    def test_prompt_lists_icon_palette(self):
        enhancer = ZettelkastenLLMEnhancer()
        card = ZettelkastenCard(
            id="x", title="t", content="c", source_highlight="h",
            chapter_reference="ch", chapter_progress=0.0,
        )
        prompt = enhancer._build_classification_prompt([card], ALLOWED)
        self.assertIn("🧭", prompt)
        self.assertIn("｜", prompt)


class TestResponseHasCardLines(unittest.TestCase):
    """`_response_has_card_lines` answers "was the response parseable at
    all" — independent of whether anything usable was actually extracted."""

    def test_true_when_line_matches_even_with_nothing_usable(self):
        # Well-formed CARD_1 line, but hallucinated category + no palette icon.
        text = "CARD_1：完全亂造的分類｜🍕"
        self.assertTrue(ZettelkastenLLMEnhancer._response_has_card_lines(text, 1))

    def test_false_for_empty_text(self):
        self.assertFalse(ZettelkastenLLMEnhancer._response_has_card_lines("", 1))

    def test_false_when_no_card_line_matches(self):
        text = "抱歉，我無法完成這個任務。"
        self.assertFalse(ZettelkastenLLMEnhancer._response_has_card_lines(text, 3))

    def test_false_when_index_out_of_range(self):
        text = "CARD_9：💞心理學｜🧭"
        self.assertFalse(ZettelkastenLLMEnhancer._response_has_card_lines(text, 2))

    def test_true_when_at_least_one_of_several_matches(self):
        text = "CARD_9：out of range\nCARD_1：💼商務｜🎯"
        self.assertTrue(ZettelkastenLLMEnhancer._response_has_card_lines(text, 2))


class TestClassifyCards(unittest.TestCase):
    """classify_cards itself — stubbing the Ollama call closes two gaps the
    sub-piece tests (TestParseClassification etc.) can't: the categories-
    before-icon ordering, and what the method actually returns."""

    def test_parseable_response_with_nothing_usable_returns_true(self):
        # Model responded in the right shape but picked nothing valid for any
        # card (hallucinated category, off-palette icon) — still parseable.
        card = _make_card("1")
        with patch(
            "zettelkasten_generator._ollama_generate",
            return_value="CARD_1：完全亂造的分類｜🍕",
        ):
            enhancer = ZettelkastenLLMEnhancer()
            result = enhancer.classify_cards([card], ALLOWED, "book")
        self.assertTrue(result)
        self.assertEqual(card.categories, [])
        # icon must still be non-empty via fallback even though the model
        # gave nothing usable.
        self.assertNotEqual(card.icon, "")

    def test_empty_response_returns_false(self):
        card = _make_card("1")
        with patch("zettelkasten_generator._ollama_generate", return_value=""):
            enhancer = ZettelkastenLLMEnhancer()
            result = enhancer.classify_cards([card], ALLOWED, "book")
        self.assertFalse(result)
        self.assertEqual(card.categories, [])
        self.assertNotEqual(card.icon, "")  # fallback still fires

    def test_categories_written_before_icon_fallback_reads_them(self):
        # No model icon (off-palette), but a matched category whose text core
        # has a _CATEGORY_ICON_DEFAULTS entry ("商務" -> "🪐"). If classify_cards
        # assigned icon before categories, _fallback_icon would see an empty
        # categories list and never reach the category-default tier.
        card = _make_card("1")
        with patch(
            "zettelkasten_generator._ollama_generate",
            return_value="CARD_1：💼商務｜🍕",
        ):
            enhancer = ZettelkastenLLMEnhancer()
            enhancer.classify_cards([card], ALLOWED, "book")
        self.assertEqual(card.categories, ["💼商務"])
        self.assertEqual(card.icon, "🪐")

    def test_valid_category_and_icon_returns_true(self):
        card = _make_card("1")
        with patch(
            "zettelkasten_generator._ollama_generate",
            return_value="CARD_1：💼商務｜🎯",
        ):
            enhancer = ZettelkastenLLMEnhancer()
            result = enhancer.classify_cards([card], ALLOWED, "book")
        self.assertTrue(result)
        self.assertEqual(card.categories, ["💼商務"])
        self.assertEqual(card.icon, "🎯")

    def test_no_cards_returns_false(self):
        enhancer = ZettelkastenLLMEnhancer()
        self.assertFalse(enhancer.classify_cards([], ALLOWED, "book"))

    def test_no_categories_returns_false(self):
        card = _make_card("1")
        enhancer = ZettelkastenLLMEnhancer()
        self.assertFalse(enhancer.classify_cards([card], [], "book"))


class TestPaletteOverlapWarning(unittest.TestCase):
    """Finding 3: the palette-disjointness invariant (_ICON_PALETTE vs
    category emoji) is only test-enforced for DEFAULT_TAG_CATEGORIES. A
    custom ZETTELKASTEN_TAG_CATEGORIES can violate it at runtime — e.g.
    "🚀成長駭客" (🚀 is in _ICON_PALETTE) would make _pick_palette_emoji's
    whole-remainder scan misread the category prefix as the model's icon
    pick. classify_cards should at least warn once when that happens."""

    def test_warns_when_configured_category_contains_a_palette_emoji(self):
        card = _make_card("1")
        overlapping = ["🚀成長駭客"]  # 🚀 is in _ICON_PALETTE
        with patch(
            "zettelkasten_generator._ollama_generate",
            return_value="CARD_1：成長駭客｜🎯",
        ), self.assertLogs("kobo_notion_sync", level="WARNING") as logs:
            enhancer = ZettelkastenLLMEnhancer()
            enhancer.classify_cards([card], overlapping, "book")
        self.assertTrue(
            any("🚀成長駭客" in msg for msg in logs.output),
            logs.output,
        )

    def test_no_warning_for_default_categories(self):
        card = _make_card("1")
        with patch(
            "zettelkasten_generator._ollama_generate",
            return_value="CARD_1：心理學｜🎯",
        ):
            enhancer = ZettelkastenLLMEnhancer()
            with self.assertRaises(AssertionError):
                # DEFAULT_TAG_CATEGORIES is disjoint from the palette, so no
                # warning should fire — assertLogs itself raises when the
                # logger emits nothing at all, which is the expected outcome.
                with self.assertLogs("kobo_notion_sync", level="WARNING"):
                    enhancer.classify_cards([card], DEFAULT_TAG_CATEGORIES, "book")

    def test_only_warns_once_per_category_set(self):
        # distinct category text so this test doesn't depend on / interfere
        # with the module-level "already warned" set used by other tests.
        overlapping = ["🪐一次性測試分類"]
        with self.assertLogs("kobo_notion_sync", level="WARNING"):
            ZettelkastenLLMEnhancer._warn_if_categories_overlap_palette(overlapping)
        with self.assertRaises(AssertionError):
            with self.assertLogs("kobo_notion_sync", level="WARNING"):
                ZettelkastenLLMEnhancer._warn_if_categories_overlap_palette(overlapping)


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
