"""Notion API implementation of NotionRepository."""
import logging
import math
import re
from typing import Any, Dict, List, Optional

from notion_client import Client
from notion_client.errors import APIResponseError

from ...domain.entities.book import Book
from ...domain.entities.highlight import Highlight
from ...domain.repositories.notion_repository import NotionRepository
from ..external.cover_fetcher import get_best_book_cover
from .rate_limiter import NotionRateLimiter
from .retry_policy import retry_with_backoff

logger = logging.getLogger(__name__)

# Notion block API: max 100 children per append. We use 80 to stay safely below
# and allow for occasional oversize fallback.
_BATCH_SIZE = 80
_MAX_BLOCKS_PER_REQUEST = 100


class NotionApiRepository(NotionRepository):
    """Thin wrapper around notion_client with retry + rate-limit handling."""

    def __init__(self, token: str, database_id: str,
                 rate_limiter: Optional[NotionRateLimiter] = None):
        self._database_id = database_id
        self._client = Client(auth=token)
        self._rate_limiter = rate_limiter or NotionRateLimiter()

    # ----- NotionRepository interface -----

    def check_book_exists(self, title: str, is_exported: bool = True) -> Dict[str, Any]:
        try:
            target = retry_with_backoff(
                lambda: self._client.databases.query(
                    database_id=self._database_id,
                    filter={
                        "and": [
                            {"property": "Title", "rich_text": {"contains": title}},
                            {"property": "Exported", "checkbox": {"equals": is_exported}},
                        ],
                    },
                ),
                self._rate_limiter,
            )
            results = (target or {}).get("results", [])
            if not results:
                return {"is_target_valid": False, "pageId": None}
            if len(results) > 1:
                logger.warning(f"標題 '{title}' 有多筆結果,採用第一筆")
            return {"is_target_valid": True, "pageId": results[0].get("id")}
        except Exception as e:
            logger.error(f"check_book_exists('{title}') 失敗: {e}", exc_info=True)
            return {"is_target_valid": False, "pageId": None}

    def create_book_entry(self, title: str) -> bool:
        page_id = self._create_and_return_page_id(title)
        return page_id is not None

    def sync_book_highlights(self, page_id: str, highlights: List[Highlight]) -> None:
        """Upload highlights grouped by chapter, then mark book as exported."""
        blocks = [self._heading_block("Highlights", level=1)]

        logger.info(f"開始同步 {len(highlights)} 個高亮到 page {page_id}")

        grouped = self._group_by_chapter(highlights)
        for chapter_name, group in grouped:
            display_name = self._sanitize_chapter_name(chapter_name, group)
            logger.info(f"章節: {display_name} ({len(group)} 個高亮)")

            blocks.append(self._heading_block(f"📖 {display_name}", level=1))
            for h in group:
                if h.text:
                    blocks.append(self._bulleted_block(h.text))
            blocks.append({"object": "block", "type": "divider", "divider": {}})

            if len(blocks) > _BATCH_SIZE:
                logger.info(f"達批次上限 {len(blocks)},先送出")
                self._append_blocks(page_id, blocks)
                blocks = []

        if blocks:
            self._append_blocks(page_id, blocks)

        retry_with_backoff(
            lambda: self._client.pages.update(
                page_id=page_id,
                properties={"Exported": {"checkbox": True}},
            ),
            self._rate_limiter,
        )

    def update_book_metadata(self, page_id: str, book: Book) -> None:
        properties = self._build_properties(book)
        if not properties:
            return
        retry_with_backoff(
            lambda: self._client.pages.update(page_id=page_id, properties=properties),
            self._rate_limiter,
        )
        logger.info(f"批次更新 {len(properties)} 個屬性 for page {page_id}")

    def add_book_cover(self, page_id: str, title: str, isbn: Optional[str] = None) -> None:
        if self._has_existing_cover(page_id):
            logger.debug(f"page {page_id} 已有封面,跳過")
            return
        cover_url = get_best_book_cover(title, isbn)
        if not cover_url:
            logger.debug(f"找不到 '{title}' 的封面")
            return
        retry_with_backoff(
            lambda: self._client.pages.update(
                page_id=page_id,
                icon={"type": "external", "external": {"url": cover_url}},
                cover={"type": "external", "external": {"url": cover_url}},
            ),
            self._rate_limiter,
        )
        logger.info(f"已為 '{title}' 設定封面")

    # ----- Internal helpers -----

    def _create_and_return_page_id(self, title: str) -> Optional[str]:
        try:
            response = retry_with_backoff(
                lambda: self._client.pages.create(
                    parent={"database_id": self._database_id},
                    properties={
                        "title": {"title": [{"text": {"content": title}}]},
                    },
                ),
                self._rate_limiter,
            )
            page_id = response.get("id")
            logger.info(f"新增書籍 '{title}' (page_id={page_id})")
            return page_id
        except Exception as e:
            logger.error(f"建立書籍頁失敗: {e}", exc_info=True)
            return None

    def _build_properties(self, book: Book) -> Dict[str, Any]:
        props: Dict[str, Any] = {}

        if book.time_spent_reading is not None:
            hours = math.floor(book.time_spent_reading / 3600)
            minutes = math.floor((book.time_spent_reading % 3600) / 60)
            seconds = book.time_spent_reading % 60
            props["SpendReadingTime"] = {
                "rich_text": [{"type": "text", "text": {
                    "content": f"{hours:02}:{minutes:02}:{seconds:02}"
                }}]
            }
        if book.date_last_read:
            props["LastReadDate"] = {"date": {"start": str(book.date_last_read)}}
        if book.last_time_finished_reading:
            props["LastFinishedReadTime"] = {"date": {"start": str(book.last_time_finished_reading)}}
        if book.percent_read is not None:
            props["PercentageRead"] = {"number": book.percent_read}
        if book.subtitle:
            props["Subtitle"] = {"rich_text": [{"text": {"content": book.subtitle}}]}
        if book.publisher:
            props["Publisher"] = {"rich_text": [{"text": {"content": book.publisher}}]}
        if book.author:
            props["Author"] = {"rich_text": [{"text": {"content": book.author}}]}
        if book.description:
            props["Description"] = {
                "rich_text": [{"text": {"content": _clean_html(book.description)}}]
            }
        if book.isbn:
            props["ISBN"] = {"rich_text": [{"text": {"content": book.isbn}}]}
        return props

    def _has_existing_cover(self, page_id: str) -> bool:
        try:
            page = retry_with_backoff(
                lambda: self._client.pages.retrieve(page_id),
                self._rate_limiter,
            )
            icon = page.get("icon") or {}
            return (isinstance(icon, dict)
                    and icon.get("type") == "external"
                    and "url" in icon.get("external", {}))
        except Exception as e:
            logger.warning(f"查詢封面狀態失敗: {e}")
            return False

    def _append_blocks(self, page_id: str, blocks: List[Dict[str, Any]]) -> None:
        if not blocks:
            return
        for i in range(0, len(blocks), _MAX_BLOCKS_PER_REQUEST):
            batch = blocks[i:i + _MAX_BLOCKS_PER_REQUEST]
            batch_num = i // _MAX_BLOCKS_PER_REQUEST + 1
            try:
                retry_with_backoff(
                    lambda b=batch: self._client.blocks.children.append(
                        block_id=page_id, children=b,
                    ),
                    self._rate_limiter,
                )
                logger.info(f"成功上傳第 {batch_num} 批 ({len(batch)} blocks)")
            except APIResponseError as e:
                if "should be ≤" in str(e) and "instead was" in str(e):
                    self._append_in_smaller_chunks(page_id, batch)
                else:
                    raise

    def _append_in_smaller_chunks(self, page_id: str,
                                  oversized_batch: List[Dict[str, Any]]) -> None:
        size = min(50, len(oversized_batch) // 2) or 1
        logger.warning(f"批次 {len(oversized_batch)} 太大,拆成 {size}")
        for j in range(0, len(oversized_batch), size):
            chunk = oversized_batch[j:j + size]
            retry_with_backoff(
                lambda c=chunk: self._client.blocks.children.append(
                    block_id=page_id, children=c,
                ),
                self._rate_limiter,
            )

    @staticmethod
    def _group_by_chapter(highlights: List[Highlight]):
        """Return list of (chapter_name, [highlights]) in first-seen order."""
        order: Dict[str, int] = {}
        groups: Dict[str, List[Highlight]] = {}
        for h in highlights:
            name = h.chapter_name or "未知章節"
            if name not in groups:
                groups[name] = []
                order[name] = len(order)
            groups[name].append(h)
        return sorted(groups.items(), key=lambda kv: order[kv[0]])

    @staticmethod
    def _sanitize_chapter_name(name: str, group: List[Highlight]) -> str:
        if name in ("未知章節", "未知章节") and group:
            return "其他內容"
        return name[:47] + "..." if len(name) > 50 else name

    @staticmethod
    def _heading_block(text: str, level: int = 1) -> Dict[str, Any]:
        key = f"heading_{level}"
        return {
            "object": "block",
            "type": key,
            key: {"rich_text": [{"type": "text", "text": {"content": text}}]},
        }

    @staticmethod
    def _bulleted_block(text: str) -> Dict[str, Any]:
        return {
            "object": "block",
            "type": "bulleted_list_item",
            "bulleted_list_item": {
                "rich_text": [{"type": "text", "text": {"content": text}}],
            },
        }


def _clean_html(text: str) -> str:
    clean = re.sub(r'<[^>]+>', '', text)
    clean = re.sub(r'\s+', ' ', clean).strip()
    return (clean
            .replace('&amp;', '&')
            .replace('&lt;', '<')
            .replace('&gt;', '>')
            .replace('&quot;', '"')
            .replace('&#39;', "'"))
