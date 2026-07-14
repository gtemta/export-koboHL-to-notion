"""Tests for Kobo Annotation (personal note) export — improvement #1."""
import unittest

from src.domain.entities.highlight import Highlight
from src.infrastructure.notion.highlight_page_blocks import quote_block
from zettelkasten_generator import CardSelectionAlgorithm, ZettelkastenLLMEnhancer


def _highlight(text="劃線內容", annotation=None):
    return Highlight(
        text=text,
        chapter_name="第一章",
        chapter_progress=0.5,
        content_id="cid",
        annotation=annotation,
    )


class TestHighlightAnnotation(unittest.TestCase):
    def test_has_annotation_true(self):
        self.assertTrue(_highlight(annotation="我的想法").has_annotation())

    def test_has_annotation_false_for_none(self):
        self.assertFalse(_highlight(annotation=None).has_annotation())

    def test_has_annotation_false_for_whitespace(self):
        self.assertFalse(_highlight(annotation="   ").has_annotation())


class TestNotionAnnotationBlocks(unittest.TestCase):
    """v2 版面：註記 callout 巢狀在 quote 之下。"""

    def test_quote_only_without_annotation(self):
        block = quote_block(_highlight())
        self.assertEqual(block["type"], "quote")
        self.assertNotIn("children", block["quote"])

    def test_callout_nested_with_annotation(self):
        block = quote_block(_highlight(annotation="這段讓我想到複利效應"))
        children = block["quote"]["children"]
        self.assertEqual(children[0]["type"], "callout")
        self.assertEqual(children[0]["callout"]["icon"]["emoji"], "💭")
        self.assertEqual(
            children[0]["callout"]["rich_text"][0]["text"]["content"],
            "這段讓我想到複利效應")

    def test_annotation_over_2000_lossless(self):
        block = quote_block(_highlight(annotation="字" * 3000))
        segs = block["quote"]["children"][0]["callout"]["rich_text"]
        self.assertEqual(sum(len(s["text"]["content"]) for s in segs), 3000)


class TestAnnotationScoring(unittest.TestCase):
    def setUp(self):
        self.algo = CardSelectionAlgorithm()

    def test_annotation_adds_bonus(self):
        base = {"text": "一段普通的劃線內容而已", "current_chapter_progress": 0.5}
        annotated = dict(base, annotation="我覺得這很關鍵")
        self.assertAlmostEqual(
            self.algo._calculate_score(annotated) - self.algo._calculate_score(base),
            5.0,
        )

    def test_blank_annotation_no_bonus(self):
        base = {"text": "一段普通的劃線內容而已", "current_chapter_progress": 0.5}
        blank = dict(base, annotation="   ")
        self.assertEqual(
            self.algo._calculate_score(blank),
            self.algo._calculate_score(base),
        )


class TestAnnotationPrompt(unittest.TestCase):
    def test_single_prompt_includes_annotation(self):
        enhancer = ZettelkastenLLMEnhancer()
        prompt = enhancer._build_prompt("劃線文字", "書名", annotation="我的註記內容")
        self.assertIn("我的註記內容", prompt)
        self.assertIn("讀者的個人註記", prompt)

    def test_single_prompt_omits_empty_annotation(self):
        enhancer = ZettelkastenLLMEnhancer()
        prompt = enhancer._build_prompt("劃線文字", "書名", annotation="")
        self.assertNotIn("讀者的個人註記", prompt)

    def test_batch_prompt_includes_annotation(self):
        enhancer = ZettelkastenLLMEnhancer()
        highlights = [
            {"text": "第一條劃線", "annotation": "註記一"},
            {"text": "第二條劃線", "annotation": ""},
        ]
        prompt = enhancer._build_batch_prompt(highlights, "書名")
        self.assertIn("註記一", prompt)


if __name__ == "__main__":
    unittest.main()
