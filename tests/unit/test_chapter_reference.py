"""章節參照消毒（K4）：TOC 來源照留，heuristic 猜的才審查。

污染樣本取自 docs/KNOWLEDGE_REFINEMENT_PLAN.md「關鍵事實」#4 的真實輸出。
"""
import unittest

from zettelkasten_generator import _clean_chapter_reference

_POLLUTED = (
    "拮抗理論」：「任何長時間或反覆從享樂或情感中性狀態脫離的情況⋯⋯"
    "都是有其代價的。」50這種代價就是一種..."
)


class TestCleanChapterReference(unittest.TestCase):
    def test_polluted_highlight_text_is_dropped(self):
        self.assertEqual(_clean_chapter_reference(_POLLUTED, from_toc=False), "")

    def test_toc_label_is_kept_even_when_long(self):
        label = "第三章 建立讓好習慣自動發生的系統 › 讓提示顯而易見的環境設計"
        self.assertGreater(len(label), 25)
        self.assertEqual(_clean_chapter_reference(label, from_toc=True), label)

    def test_toc_label_with_quotes_is_kept(self):
        label = "第三章「習慣的力量」"
        self.assertEqual(_clean_chapter_reference(label, from_toc=True), label)

    def test_guessed_label_with_quotes_is_dropped(self):
        # 已知取捨：真實章名若含「」但來自 heuristic 猜測，會被一併清掉。
        # 寧可漏掉一個章名，也不要讓劃線內文印在卡片上。
        self.assertEqual(
            _clean_chapter_reference("第三章「習慣的力量」", from_toc=False), ""
        )

    def test_guessed_label_over_25_chars_is_dropped(self):
        self.assertEqual(_clean_chapter_reference("一" * 26, from_toc=False), "")

    def test_short_guessed_label_is_kept(self):
        self.assertEqual(
            _clean_chapter_reference("第三章 習慣的力量", from_toc=False),
            "第三章 習慣的力量",
        )

    def test_unknown_sentinel_is_dropped_regardless_of_source(self):
        # 'Unknown' 是兩處 highlight.get('chapter_name', 'Unknown') 的哨兵預設值，
        # 不是任何真實章名，來自哪條路徑都該清掉。
        self.assertEqual(_clean_chapter_reference("Unknown", from_toc=True), "")
        self.assertEqual(_clean_chapter_reference("Unknown", from_toc=False), "")

    def test_empty_and_none_are_dropped(self):
        self.assertEqual(_clean_chapter_reference("", from_toc=True), "")
        self.assertEqual(_clean_chapter_reference(None, from_toc=False), "")

    def test_surrounding_whitespace_is_stripped(self):
        self.assertEqual(_clean_chapter_reference("  第一章  ", from_toc=False), "第一章")


if __name__ == "__main__":
    unittest.main()
