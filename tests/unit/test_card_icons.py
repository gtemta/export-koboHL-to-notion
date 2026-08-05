"""卡片 page icon：固定 emoji 調色盤的不變條件，與規則式 fallback。"""
import unicodedata
import unittest

from src.config.settings import DEFAULT_TAG_CATEGORIES
from zettelkasten_generator import (
    _ICON_PALETTE,
    _ICON_PALETTE_SET,
    ZettelkastenCard,
    ZettelkastenLLMEnhancer,
)


def _card(title="卡片標題", tags=None, categories=None):
    return ZettelkastenCard(
        id="id", title=title, content="內容", source_highlight="劃線",
        chapter_reference="第一章", chapter_progress=0.5,
        tags=list(tags or []), categories=list(categories or []),
    )


class TestPaletteInvariants(unittest.TestCase):
    """兩條不變條件壞掉會直接讓 Notion 建卡失敗或讓 parser 誤判，必須有測試把關。"""

    def test_no_duplicates(self):
        self.assertEqual(len(set(_ICON_PALETTE)), len(_ICON_PALETTE))

    def test_every_entry_is_a_single_codepoint(self):
        # 多碼點序列（ZWJ / variation selector）是 Notion icon 最常見的拒收原因
        for emoji in _ICON_PALETTE:
            self.assertEqual(len(emoji), 1, f"{emoji!r} 不是單一 codepoint")

    def test_no_zwj_or_variation_selector(self):
        for emoji in _ICON_PALETTE:
            self.assertNotIn("‍", emoji)
            self.assertNotIn("️", emoji)

    def test_disjoint_from_category_emoji(self):
        # parser 靠「行內出現的調色盤 emoji 必為 icon」判讀，兩者相交規則就不成立
        category_symbols = {
            ch for cat in DEFAULT_TAG_CATEGORIES for ch in cat
            if unicodedata.category(ch)[0] not in ("L", "N")
        }
        self.assertEqual(set(_ICON_PALETTE) & category_symbols, set())

    def test_set_matches_tuple(self):
        self.assertEqual(_ICON_PALETTE_SET, frozenset(_ICON_PALETTE))

    def test_palette_is_non_trivial(self):
        # 太小的調色盤會讓同一本書的卡片撞 icon，痛點就沒解掉
        self.assertGreaterEqual(len(_ICON_PALETTE), 30)


class TestFallbackIcon(unittest.TestCase):
    def test_keyword_hit_from_tags(self):
        icon = ZettelkastenLLMEnhancer._fallback_icon(_card(tags=["習慣迴圈"]))
        self.assertEqual(icon, "🔁")

    def test_keyword_hit_from_title(self):
        icon = ZettelkastenLLMEnhancer._fallback_icon(_card(title="認知偏誤的陷阱"))
        self.assertEqual(icon, "🪤")

    def test_falls_back_to_category_default(self):
        icon = ZettelkastenLLMEnhancer._fallback_icon(
            _card(title="無關詞", tags=["無關詞"], categories=["💼商務"]))
        self.assertEqual(icon, "🪐")

    def test_category_default_is_emoji_insensitive(self):
        icon = ZettelkastenLLMEnhancer._fallback_icon(
            _card(title="無關詞", tags=[], categories=["商務"]))
        self.assertEqual(icon, "🪐")

    def test_last_resort_never_empty(self):
        icon = ZettelkastenLLMEnhancer._fallback_icon(_card(title="無關詞", tags=[]))
        self.assertIn(icon, _ICON_PALETTE_SET)

    def test_keyword_beats_category(self):
        icon = ZettelkastenLLMEnhancer._fallback_icon(
            _card(title="習慣的力量", categories=["💼商務"]))
        self.assertEqual(icon, "🔁")

    def test_all_results_are_in_palette(self):
        for cat in DEFAULT_TAG_CATEGORIES:
            icon = ZettelkastenLLMEnhancer._fallback_icon(
                _card(title="無關詞", tags=[], categories=[cat]))
            self.assertIn(icon, _ICON_PALETTE_SET, cat)


if __name__ == "__main__":
    unittest.main()
