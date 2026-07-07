"""Dry-run decorator for NotionRepository.

DRY_RUN=true 時包住真正的 NotionApiRepository：讀取操作照常委派（查詢書籍
是否存在），寫入操作只記 log 不打 API。本輪「建立」的書籍會拿到假的
page_id，讓 use case 的「建立 → 重查 → 上傳」流程走得下去。
"""
import logging
import threading
from typing import Any, Dict, List, Optional

from ...domain.entities.book import Book
from ...domain.entities.highlight import Highlight
from ...domain.repositories.notion_repository import NotionRepository

logger = logging.getLogger(__name__)

_PREFIX = "[DRY RUN]"


class DryRunNotionRepository(NotionRepository):
    """Reads delegate to the wrapped repository; writes are logged only."""

    def __init__(self, inner: NotionRepository):
        self._inner = inner
        self._created: Dict[str, str] = {}
        self._lock = threading.Lock()

    def check_book_exists(self, title: str, is_exported: bool = True) -> Dict[str, Any]:
        result = self._inner.check_book_exists(title, is_exported)
        if result.get("is_target_valid"):
            return result
        # 本輪 dry-run「建立」過的書，回傳假 page_id 讓流程繼續
        with self._lock:
            fake_id = self._created.get(title)
        if fake_id and not is_exported:
            return {"is_target_valid": True, "pageId": fake_id}
        return result

    def create_book_entry(self, title: str) -> bool:
        with self._lock:
            fake_id = f"dry-run-page-{len(self._created) + 1}"
            self._created[title] = fake_id
        logger.info(f"{_PREFIX} 將建立書籍 '{title}' (模擬 page_id={fake_id})")
        return True

    def sync_book_highlights(self, page_id: str, highlights: List[Highlight]) -> None:
        chapters = {h.chapter_name or "未知章節" for h in highlights}
        logger.info(
            f"{_PREFIX} 將上傳 {len(highlights)} 個劃線（{len(chapters)} 個章節）"
            f"到 page {page_id}，並勾選 Exported"
        )

    def update_book_metadata(self, page_id: str, book: Book) -> None:
        logger.info(f"{_PREFIX} 將更新 '{book.title}' 的元數據 (page {page_id})")

    def add_book_cover(self, page_id: str, title: str, isbn: Optional[str] = None) -> None:
        logger.info(f"{_PREFIX} 將檢查並補上 '{title}' 的封面 (page {page_id})")
