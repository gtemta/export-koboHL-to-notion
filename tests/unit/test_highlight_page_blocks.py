"""劃線頁 v2 純函式：拆段、quote/toggle 建構、章節樹分組。"""
import unittest

from src.domain.entities.highlight import Highlight
from src.infrastructure.notion.highlight_page_blocks import (
    chapter_children,
    chapter_tree,
    heading_block,
    quote_block,
    split_rich_text,
    total_block_count,
)


def _h(text="劃線", chapter=None, section=None, annotation=None,
       chapter_name="未知章節"):
    return Highlight(
        text=text, chapter_name=chapter_name, chapter_progress=0.5,
        content_id="cid", annotation=annotation,
        toc_chapter=chapter, toc_section=section)


class TestSplitRichText(unittest.TestCase):
    def test_short_text_single_segment(self):
        segs = split_rich_text("hello")
        self.assertEqual(len(segs), 1)
        self.assertEqual(segs[0]["text"]["content"], "hello")

    def test_long_text_split_lossless(self):
        """超過 2000 字切多段，內容零遺失（取代舊的截斷）"""
        text = "字" * 4500
        segs = split_rich_text(text)
        self.assertEqual([len(s["text"]["content"]) for s in segs],
                         [2000, 2000, 500])
        self.assertEqual("".join(s["text"]["content"] for s in segs), text)


class TestQuoteBlock(unittest.TestCase):
    def test_plain_quote(self):
        block = quote_block(_h())
        self.assertEqual(block["type"], "quote")
        self.assertNotIn("children", block["quote"])

    def test_annotation_nested_as_child(self):
        """💭 callout 是 quote 的 child（縮排從屬），不再是同層 sibling"""
        block = quote_block(_h(annotation="我的想法"))
        children = block["quote"]["children"]
        self.assertEqual(len(children), 1)
        self.assertEqual(children[0]["type"], "callout")
        self.assertEqual(children[0]["callout"]["icon"]["emoji"], "💭")

    def test_long_annotation_lossless(self):
        block = quote_block(_h(annotation="註" * 3000))
        segs = block["quote"]["children"][0]["callout"]["rich_text"]
        self.assertEqual(sum(len(s["text"]["content"]) for s in segs), 3000)


class TestHeadingBlock(unittest.TestCase):
    def test_toggleable_flag(self):
        block = heading_block("第一章", level=1, toggleable=True)
        self.assertEqual(block["type"], "heading_1")
        self.assertTrue(block["heading_1"]["is_toggleable"])

    def test_plain_heading_has_no_flag(self):
        block = heading_block("📌 劃線筆記", level=1)
        self.assertNotIn("is_toggleable", block["heading_1"])


class TestChapterTree(unittest.TestCase):
    def test_groups_by_chapter_then_section_in_order(self):
        tree = chapter_tree([
            _h("a", chapter="第一章", section="開場"),
            _h("b", chapter="第一章", section="開場"),
            _h("c", chapter="第一章", section="轉折"),
            _h("d", chapter="第二章"),
        ])
        self.assertEqual([g.title for g in tree], ["第一章", "第二章"])
        self.assertEqual([(t, [h.text for h in items])
                          for t, items in tree[0].sections],
                         [("開場", ["a", "b"]), ("轉折", ["c"])])
        self.assertEqual([h.text for h in tree[1].direct], ["d"])

    def test_fallback_book_uses_chapter_name(self):
        """無 TOC 的書：chapter_name 當章、無小節；未知章節改「其他內容」"""
        tree = chapter_tree([_h("x", chapter_name="未知章節")])
        self.assertEqual(tree[0].title, "其他內容")
        self.assertEqual([h.text for h in tree[0].direct], ["x"])
        self.assertEqual(tree[0].sections, [])

    def test_same_section_nonadjacent_merges(self):
        """同名小節非連續出現仍併同一 toggle（每小節恰一個 toggle）"""
        tree = chapter_tree([
            _h("a", chapter="第一章", section="開場"),
            _h("b", chapter="第一章", section="轉折"),
            _h("c", chapter="第一章", section="開場"),
        ])
        self.assertEqual([(t, [h.text for h in items])
                          for t, items in tree[0].sections],
                         [("開場", ["a", "c"]), ("轉折", ["b"])])


class TestChapterChildren(unittest.TestCase):
    def test_direct_quotes_then_section_toggles(self):
        tree = chapter_tree([
            _h("直下劃線", chapter="第一章"),
            _h("小節劃線", chapter="第一章", section="開場"),
        ])
        blocks = chapter_children(tree[0])
        self.assertEqual([b["type"] for b in blocks], ["quote", "heading_2"])
        toggle = blocks[1]
        self.assertTrue(toggle["heading_2"]["is_toggleable"])
        self.assertEqual(
            [b["type"] for b in toggle["heading_2"]["children"]], ["quote"])

    def test_oversized_section_split_into_continuation(self):
        """小節超過 90 條 → 拆「(續)」toggle，children 皆 ≤ 90"""
        items = [_h(f"劃線{i}", chapter="第一章", section="長節")
                 for i in range(95)]
        blocks = chapter_children(chapter_tree(items)[0])
        self.assertEqual(len(blocks), 2)
        titles = [b["heading_2"]["rich_text"][0]["text"]["content"]
                  for b in blocks]
        self.assertEqual(titles, ["長節", "長節 (續)"])
        self.assertEqual(len(blocks[0]["heading_2"]["children"]), 90)
        self.assertEqual(len(blocks[1]["heading_2"]["children"]), 5)

    def test_empty_text_highlight_skipped(self):
        tree = chapter_tree([_h("", chapter="第一章")])
        self.assertEqual(chapter_children(tree[0]), [])


class TestTotalBlockCount(unittest.TestCase):
    def test_counts_nested(self):
        quote = quote_block(_h(annotation="想法"))     # quote + callout = 2
        self.assertEqual(total_block_count(quote), 2)
        tree = chapter_tree([_h("a", chapter="章", section="節",
                                annotation="想法")])
        toggle = chapter_children(tree[0])[0]          # toggle + quote + callout
        self.assertEqual(total_block_count(toggle), 3)


if __name__ == "__main__":
    unittest.main()
