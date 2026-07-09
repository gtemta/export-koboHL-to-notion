import unittest

from src.infrastructure.persistence.toc_chapter_resolver import TocChapterResolver

_B = "book-uuid!OEBPS!"


def _make_resolver():
    """模擬一本書：Prologue、跨檔的 Ch1（含同檔多 anchor 小節）、
    小節獨立成檔的 Ch2、以及一筆檔案不在 spine 的幽靈 TOC 條目。"""
    spine = [
        (_B + "Text/cover.xhtml", 0),
        (_B + "Text/prologue.xhtml", 1),
        (_B + "Text/ch1.xhtml", 2),
        (_B + "Text/ch1-cont.xhtml", 3),   # Ch1 的接續檔，TOC 沒有條目
        (_B + "Text/ch2.xhtml", 4),
        (_B + "Text/sec2-1.xhtml", 5),
        (_B + "Text/sec2-2.xhtml", 6),
    ]
    toc = [
        (_B + "Text/prologue.xhtml-1", "Prologue", 0, 1),
        (_B + "Text/ch1.xhtml-1", "Chapter 1", 1, 1),
        (_B + "Text/ch1.xhtml#a1-2", "小節甲", 2, 2),
        (_B + "Text/ch1.xhtml#a2-2", "小節乙", 3, 2),
        (_B + "Text/ch2.xhtml-1", "Chapter 2", 4, 1),
        (_B + "Text/sec2-1.xhtml-1", "小節丙", 5, 2),
        (_B + "Text/sec2-2.xhtml-1", "小節丁", 6, 2),
        (_B + "Text/missing.xhtml-1", "幽靈章", 7, 1),  # 不在 spine
    ]
    return TocChapterResolver(spine, toc)


class TestTocChapterResolver(unittest.TestCase):
    def setUp(self):
        self.resolver = _make_resolver()

    def test_direct_file_hit(self):
        """劃線檔案直接命中 TOC 條目（63% 常態路徑）"""
        self.assertEqual(
            self.resolver.resolve(_B + "Text/prologue.xhtml"), "Prologue")

    def test_multi_file_chapter_uses_nearest_preceding_entry(self):
        """一章跨多檔：接續檔往前找最近條目（物哀 case）。
        ch1-cont 在 ch1 全部 anchor 之後，可確定屬於最後一個小節。"""
        self.assertEqual(
            self.resolver.resolve(_B + "Text/ch1-cont.xhtml"),
            "Chapter 1 › 小節乙")

    def test_same_file_multiple_anchors_falls_back_to_chapter(self):
        """同檔多 anchor 無法分辨劃線落點 → 退回章級（鬆綁你的完美主義 case）"""
        self.assertEqual(
            self.resolver.resolve(_B + "Text/ch1.xhtml"), "Chapter 1")

    def test_section_as_own_file_gets_full_path(self):
        """小節獨立成檔 → 「章 › 小節」完整路徑"""
        self.assertEqual(
            self.resolver.resolve(_B + "Text/sec2-1.xhtml"),
            "Chapter 2 › 小節丙")
        self.assertEqual(
            self.resolver.resolve(_B + "Text/sec2-2.xhtml"),
            "Chapter 2 › 小節丁")

    def test_before_first_toc_entry_returns_none(self):
        """劃線在第一個 TOC 條目之前（封面）→ None，交給 fallback"""
        self.assertIsNone(self.resolver.resolve(_B + "Text/cover.xhtml"))

    def test_toc_entry_missing_from_spine_is_skipped(self):
        """幽靈條目（檔案不在 spine）不炸、也不影響其他解析"""
        self.assertEqual(
            self.resolver.resolve(_B + "Text/sec2-2.xhtml"),
            "Chapter 2 › 小節丁")

    def test_unknown_bookmark_file_returns_none(self):
        """劃線檔案不在 spine → None"""
        self.assertIsNone(self.resolver.resolve(_B + "Text/nowhere.xhtml"))

    def test_no_toc_data_returns_none(self):
        """整本書無 TOC 資料 → 全回 None，repo 走原 pipeline"""
        empty = TocChapterResolver(
            [(_B + "Text/a.xhtml", 0)], [])
        self.assertFalse(empty.has_toc())
        self.assertIsNone(empty.resolve(_B + "Text/a.xhtml"))
        self.assertTrue(self.resolver.has_toc())

    def test_spine_position_for_sorting(self):
        """spine_position 供劃線排序使用"""
        self.assertEqual(
            self.resolver.spine_position(_B + "Text/ch1-cont.xhtml"), 3)
        self.assertIsNone(
            self.resolver.spine_position(_B + "Text/nowhere.xhtml"))

    def test_deep_anchors_fall_back_to_certain_shallower_section(self):
        """三層書（主控力 case）：同檔 depth-3 anchor 不可判定，
        但同檔檔首的 depth-2 條目（CHAPTER 01）確定包含劃線 → 仍應給出小節。"""
        spine = [
            (_B + "Text/part1.xhtml", 0),
            (_B + "Text/ch01.xhtml", 1),
        ]
        toc = [
            (_B + "Text/part1.xhtml-1", "第一篇", 0, 1),
            (_B + "Text/ch01.xhtml-2", "CHAPTER 01", 1, 2),
            (_B + "Text/ch01.xhtml#s1-3", "小節A", 2, 3),
            (_B + "Text/ch01.xhtml#s2-3", "小節B", 3, 3),
        ]
        r = TocChapterResolver(spine, toc)
        self.assertEqual(
            r.resolve(_B + "Text/ch01.xhtml"), "第一篇 › CHAPTER 01")

    def test_sole_anchor_in_file_treated_as_file_start(self):
        """主控力 pattern：每章檔案唯一的 TOC 條目帶 anchor（章標題 anchor
        在檔首）→ 視同檔首條目，小節精度不應丟失。"""
        spine = [
            (_B + "Text/part1.xhtml", 0),
            (_B + "Text/ch01.xhtml", 1),
            (_B + "Text/ch02.xhtml", 2),
        ]
        toc = [
            (_B + "Text/part1.xhtml-1", "第一篇", 0, 1),
            (_B + "Text/ch01.xhtml#a-2", "CHAPTER 01", 1, 2),
            (_B + "Text/ch02.xhtml#a-2", "CHAPTER 02", 2, 2),
        ]
        r = TocChapterResolver(spine, toc)
        self.assertEqual(
            r.resolve(_B + "Text/ch01.xhtml"), "第一篇 › CHAPTER 01")
        self.assertEqual(
            r.resolve(_B + "Text/ch02.xhtml"), "第一篇 › CHAPTER 02")

    def test_skipped_anchor_at_same_depth_blocks_earlier_candidate(self):
        """同檔多條目時 anchor 才算模糊；跳過的 anchor 與較早候選同深度時，
        劃線可能已越過該 anchor 進入下一節 → 不可安全採用較早候選。"""
        spine = [
            (_B + "Text/ch1.xhtml", 0),
            (_B + "Text/secA.xhtml", 1),
            (_B + "Text/mixed.xhtml", 2),
        ]
        toc = [
            (_B + "Text/ch1.xhtml-1", "Chapter 1", 0, 1),
            (_B + "Text/secA.xhtml-2", "小節A", 1, 2),
            (_B + "Text/mixed.xhtml#b-2", "小節B", 2, 2),
            (_B + "Text/mixed.xhtml#c-3", "細項C", 3, 3),
        ]
        r = TocChapterResolver(spine, toc)
        # mixed.xhtml 有兩個 anchor 條目：可能還在小節A、也可能已進小節B
        # → 只能退回章級
        self.assertEqual(r.resolve(_B + "Text/mixed.xhtml"), "Chapter 1")

    def test_label_truncated_at_60_chars(self):
        """超長標籤沿用現有 60 字截斷慣例"""
        spine = [(_B + "Text/a.xhtml", 0)]
        toc = [(_B + "Text/a.xhtml-1", "長" * 80, 0, 1)]
        r = TocChapterResolver(spine, toc)
        label = r.resolve(_B + "Text/a.xhtml")
        self.assertEqual(len(label), 60)
        self.assertTrue(label.endswith("..."))


if __name__ == "__main__":
    unittest.main()
