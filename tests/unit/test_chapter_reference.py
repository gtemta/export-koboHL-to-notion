"""章節參照消毒（K4）：TOC 來源照留，heuristic 猜的才審查。

污染樣本取自 docs/KNOWLEDGE_REFINEMENT_PLAN.md「關鍵事實」#4 的真實輸出。
"""
import unittest
from unittest.mock import patch

from src.application.use_cases.generate_book_cards_use_case import GenerateBookCardsUseCase
from src.domain.entities.highlight import Highlight
from src.infrastructure.notion.zettelkasten_card_repository import ZettelkastenCardRepository
from zettelkasten_generator import (
    ZettelkastenCard,
    ZettelkastenLLMEnhancer,
    _clean_chapter_reference,
)

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


_BATCH_RESPONSE = (
    "### CARD_1\n"
    "【標題】延遲滿足會反過來擴大痛苦\n"
    "【內容】" + "內" * 100 + "\n"
    "【標籤】習慣、複利\n"
)


class TestCardConstructionSanitisesChapter(unittest.TestCase):
    """建卡當下就清乾淨，讓 cards_output/*.json 落地的就是可信值。"""

    def test_batch_parse_drops_polluted_chapter(self):
        highlights = [{
            "text": "原始劃線",
            "chapter_name": _POLLUTED,
            "chapter_progress": 0.42,
        }]
        cards = ZettelkastenLLMEnhancer()._parse_batch_response(
            _BATCH_RESPONSE, highlights
        )
        self.assertEqual(cards[0].chapter_reference, "")
        # 進度是 Kobo 硬數據，不受章名判定影響
        self.assertEqual(cards[0].chapter_progress, 0.42)

    def test_batch_parse_keeps_toc_chapter(self):
        label = "第三章 建立讓好習慣自動發生的系統 › 讓提示顯而易見的環境設計"
        highlights = [{
            "text": "原始劃線",
            "chapter_name": label,
            "chapter_progress": 0.42,
            "chapter_from_toc": True,
        }]
        cards = ZettelkastenLLMEnhancer()._parse_batch_response(
            _BATCH_RESPONSE, highlights
        )
        self.assertEqual(cards[0].chapter_reference, label)

    def test_generate_card_drops_polluted_chapter(self):
        highlight = {
            "text": "原始劃線",
            "chapter_name": _POLLUTED,
            "chapter_progress": 0.42,
        }
        single_response = (
            "【標題】延遲滿足會反過來擴大痛苦\n"
            "【內容】" + "內" * 100 + "\n"
            "【標籤】習慣、複利\n"
        )
        with patch(
            "zettelkasten_generator._ollama_generate",
            return_value=single_response,
        ):
            card = ZettelkastenLLMEnhancer().generate_card(highlight, "書名")
        self.assertEqual(card.chapter_reference, "")

    def test_unknown_default_never_reaches_the_card(self):
        # highlight dict 沒有 chapter_name → 兩處建卡點的 .get 預設值 'Unknown'
        highlights = [{"text": "原始劃線", "chapter_progress": 0.0}]
        cards = ZettelkastenLLMEnhancer()._parse_batch_response(
            _BATCH_RESPONSE, highlights
        )
        self.assertEqual(cards[0].chapter_reference, "")


class TestHighlightDictCarriesTocFlag(unittest.TestCase):
    """可信度訊號的唯一來源：Highlight.toc_chapter 非 None ⟺ 章名來自 Kobo 目錄。"""

    @staticmethod
    def _highlight(**overrides):
        kwargs = dict(
            text="劃線內容",
            chapter_name="第一章",
            chapter_progress=0.5,
            content_id="cid",
        )
        kwargs.update(overrides)
        return Highlight(**kwargs)

    def test_toc_backed_highlight_is_marked_trusted(self):
        h = self._highlight(toc_chapter="第一章", toc_section="小節")
        self.assertTrue(GenerateBookCardsUseCase._to_dict(h)["chapter_from_toc"])

    def test_guessed_highlight_is_marked_untrusted(self):
        h = self._highlight(toc_chapter=None)
        self.assertFalse(GenerateBookCardsUseCase._to_dict(h)["chapter_from_toc"])


def _repo():
    repo = ZettelkastenCardRepository(token="dummy", database_id="db")
    repo._schema_props = None  # 預先塞快取，避免任何網路呼叫
    return repo


def _card(**overrides):
    kwargs = dict(
        id="id", title="標題", content="內容", source_highlight="劃線",
        chapter_reference="", chapter_progress=0.0,
    )
    kwargs.update(overrides)
    return ZettelkastenCard(**kwargs)


class TestChapterCalloutFallsBackToProgress(unittest.TestCase):
    """進度是 Kobo 硬數據，不該被章名的問題連坐。"""

    @staticmethod
    def _callouts(blocks):
        return [b for b in blocks if b["type"] == "callout"
                and b["callout"]["icon"]["emoji"] == "📖"]

    def test_progress_only_callout_when_chapter_was_dropped(self):
        blocks = _repo()._build_children(_card(chapter_reference="", chapter_progress=0.42))
        callouts = self._callouts(blocks)
        self.assertEqual(len(callouts), 1)
        self.assertEqual(
            callouts[0]["callout"]["rich_text"][0]["text"]["content"],
            "（進度 42%）",
        )

    def test_no_callout_when_both_chapter_and_progress_are_empty(self):
        blocks = _repo()._build_children(_card(chapter_reference="", chapter_progress=0.0))
        self.assertEqual(self._callouts(blocks), [])

    def test_chapter_and_progress_together_unchanged(self):
        blocks = _repo()._build_children(
            _card(chapter_reference="第一章", chapter_progress=0.42)
        )
        self.assertEqual(
            self._callouts(blocks)[0]["callout"]["rich_text"][0]["text"]["content"],
            "第一章（進度 42%）",
        )


if __name__ == "__main__":
    unittest.main()
