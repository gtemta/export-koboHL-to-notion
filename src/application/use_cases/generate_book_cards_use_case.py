"""產生書籍卡片並上傳到 Notion 卡片盒的用例。"""
import logging
from typing import List

from zettelkasten_generator import ZettelkastenCardGenerator

from ...domain.entities.book import Book
from ...domain.entities.highlight import Highlight
from ...infrastructure.notion.zettelkasten_card_repository import (
    ZettelkastenCardRepository,
)


class GenerateBookCardsUseCase:
    def __init__(
        self,
        generator: ZettelkastenCardGenerator,
        card_repo: ZettelkastenCardRepository,
    ):
        self._generator = generator
        self._card_repo = card_repo
        self._logger = logging.getLogger(__name__)

    def execute(self, book: Book, highlights: List[Highlight]) -> int:
        try:
            highlight_dicts = [self._to_dict(h) for h in highlights if h.is_valid()]
            cards = self._generator.generate_cards(highlight_dicts, book.title)
            if not cards:
                return 0
            return self._card_repo.upload_cards(cards, book.title)
        except Exception as e:
            self._logger.error(f"產生 / 上傳 {book.title} 的卡片時失敗: {e}", exc_info=True)
            return 0

    @staticmethod
    def _to_dict(h: Highlight) -> dict:
        return {
            "text": h.text,
            "chapter_name": h.chapter_name,
            "chapter_progress": h.chapter_progress,
            "current_chapter_progress": h.current_chapter_progress,
            "annotation": h.annotation,
            "bookmark_id": h.bookmark_id,
        }
