"""產生書籍卡片並上傳到 Notion 卡片盒的用例。"""
import logging
from typing import List, Optional

from zettelkasten_generator import ZettelkastenCardGenerator

from ...domain.entities.book import Book
from ...domain.entities.highlight import Highlight
from ...infrastructure.notion.zettelkasten_card_repository import (
    ZettelkastenCardRepository,
)
from ...infrastructure.persistence.card_store import CardStore


class GenerateBookCardsUseCase:
    def __init__(
        self,
        generator: ZettelkastenCardGenerator,
        card_repo: ZettelkastenCardRepository,
        card_store: Optional[CardStore] = None,
    ):
        self._generator = generator
        self._card_repo = card_repo
        self._store = card_store
        self._logger = logging.getLogger(__name__)

    def execute(
        self,
        book: Book,
        highlights: List[Highlight],
        source_page_id: Optional[str] = None,
    ) -> int:
        try:
            # 續傳：若上次已產生但尚未（完整）上傳，先送出留存的卡片，不重跑 LLM。
            if self._store is not None:
                pending = self._store.load_pending(book.title)
                if pending:
                    path, cards = pending
                    uploaded = self._card_repo.upload_cards(
                        cards, book.title, source_page_id, book.percent_read
                    )
                    self._store.mark_uploaded(path)
                    return uploaded

            highlight_dicts = [self._to_dict(h) for h in highlights if h.is_valid()]
            cards = self._generator.generate_cards(highlight_dicts, book.title)
            if not cards:
                return 0

            # 先落地再上傳，上傳失敗時下次可續傳。
            path = self._store.save(book.title, cards) if self._store else None
            uploaded = self._card_repo.upload_cards(
                cards, book.title, source_page_id, book.percent_read
            )
            if self._store is not None:
                self._store.mark_uploaded(path)
            return uploaded
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
