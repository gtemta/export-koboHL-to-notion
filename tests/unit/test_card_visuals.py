"""卡片 cover 選色：分類 → Notion 內建 cover URL（純邏輯）。"""
import unittest

from src.config.settings import DEFAULT_TAG_CATEGORIES
from src.infrastructure.notion.card_visuals import (
    _COVER_BASE,
    _DEFAULT_COVER,
    _FALLBACK_COVERS,
    cover_url_for,
)


class TestCoverUrlFor(unittest.TestCase):
    def test_known_category(self):
        self.assertEqual(
            cover_url_for(["💞心理學"]), _COVER_BASE + "gradients_1.png")

    def test_plain_text_category_matches_emoji_version(self):
        # 本地小模型常常不照抄 emoji；比對走 text core
        self.assertEqual(cover_url_for(["心理學"]), cover_url_for(["💞心理學"]))

    def test_zwj_category(self):
        self.assertEqual(
            cover_url_for(["🧘‍♂️人生觀點"]), _COVER_BASE + "gradients_4.png")

    def test_multi_category_takes_first(self):
        self.assertEqual(
            cover_url_for(["💼商務", "💞心理學"]), _COVER_BASE + "gradients_3.png")

    def test_empty_falls_back_to_default(self):
        self.assertEqual(cover_url_for([]), _COVER_BASE + _DEFAULT_COVER)

    def test_none_falls_back_to_default(self):
        self.assertEqual(cover_url_for(None), _COVER_BASE + _DEFAULT_COVER)

    def test_blank_category_skipped(self):
        # 只有 emoji、沒有文字核心的分類視為無效，往下一個找
        self.assertEqual(
            cover_url_for(["🔥", "💼商務"]), _COVER_BASE + "gradients_3.png")

    def test_every_default_category_has_a_cover(self):
        for cat in DEFAULT_TAG_CATEGORIES:
            url = cover_url_for([cat])
            self.assertTrue(url.startswith(_COVER_BASE), cat)
            self.assertNotEqual(url, _COVER_BASE + _DEFAULT_COVER, cat)

    def test_default_categories_map_to_distinct_covers(self):
        urls = {cover_url_for([c]) for c in DEFAULT_TAG_CATEGORIES}
        self.assertEqual(len(urls), len(DEFAULT_TAG_CATEGORIES))


class TestUnknownCategoryFallback(unittest.TestCase):
    """自訂分類（ZETTELKASTEN_TAG_CATEGORIES 覆寫）也要拿得到 cover。"""

    def test_unknown_category_gets_a_real_cover(self):
        url = cover_url_for(["量子力學"])
        self.assertIn(url.replace(_COVER_BASE, ""), _FALLBACK_COVERS)

    def test_unknown_category_is_stable_within_process(self):
        self.assertEqual(cover_url_for(["量子力學"]), cover_url_for(["量子力學"]))

    def test_unknown_category_is_stable_across_processes(self):
        # sha1 的硬編期望值：用內建 hash() 會因 PYTHONHASHSEED 隨機化而失敗
        self.assertEqual(
            cover_url_for(["量子力學"]), _COVER_BASE + "solid_yellow.png")
        self.assertEqual(
            cover_url_for(["建築學"]), _COVER_BASE + "gradients_4.png")


if __name__ == "__main__":
    unittest.main()
