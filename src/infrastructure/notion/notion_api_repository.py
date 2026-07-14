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
from .highlight_page_blocks import (
    PAGE_TITLE,
    chapter_children,
    chapter_tree,
    heading_block,
    total_block_count,
)
from .rate_limiter import NotionRateLimiter
from .retry_policy import retry_with_backoff

logger = logging.getLogger(__name__)

# Notion block API: max 100 children per append. We use 80 to stay safely below
# and allow for occasional oversize fallback.
_BATCH_SIZE = 80
_MAX_BLOCKS_PER_REQUEST = 100

# sync_book_highlights 產生的「頂層」block 類型；resync 重建時只刪這些
# （v2 版面的 quote/小節 heading_2 巢狀在章 toggle=heading_1 內，隨父塊遞迴刪除；
# bulleted_list_item/divider 保留是為了清掉 v1 舊版頁面）。
# 頂層的 paragraph、toggle、quote、heading_2… 視為使用者手動內容，一律保留。
_SYNC_GENERATED_BLOCK_TYPES = frozenset(
    {"heading_1", "bulleted_list_item", "callout", "divider"}
)


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
        """Upload highlights as 章 toggle → 小節 toggle → quote（💭 註記為
        quote 的 child），then mark book as exported."""
        tree = chapter_tree(highlights)
        logger.info(
            f"開始同步 {len(highlights)} 個劃線（{len(tree)} 章）到 page {page_id}")

        top_blocks = [heading_block(PAGE_TITLE, level=1)]
        top_blocks += [heading_block(g.title, level=1, toggleable=True)
                       for g in tree]
        created = self._append_blocks_returning_ids(page_id, top_blocks)
        if len(created) != len(top_blocks):
            raise RuntimeError(
                f"頂層 block 建立數量不符: 預期 {len(top_blocks)} 實得 {len(created)}")

        for group, block in zip(tree, created[1:]):  # created[0] 是頁首標題
            n_sections = len(group.sections)
            logger.info(
                f"章節: {group.title}（直下 {len(group.direct)} 條、"
                f"{n_sections} 小節）")
            self._append_chapter_children(block["id"], chapter_children(group))

        retry_with_backoff(
            lambda: self._client.pages.update(
                page_id=page_id,
                properties={"Exported": {"checkbox": True}},
            ),
            self._rate_limiter,
        )

    def replace_book_highlights(self, page_id: str, highlights: List[Highlight]) -> None:
        """Rebuild the page's highlight blocks: delete sync-generated blocks,
        keep user-added content, then re-upload."""
        deleted = self._delete_sync_generated_blocks(page_id)
        logger.info(f"重建 page {page_id}: 已刪除 {deleted} 個同步產生的 block")
        self.sync_book_highlights(page_id, highlights)

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

    def _append_blocks_returning_ids(
            self, parent_id: str,
            blocks: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Append top-level blocks and return the created block objects
        (in order) — 章 toggle 需要 id 才能掛 children."""
        created: List[Dict[str, Any]] = []
        for i in range(0, len(blocks), _MAX_BLOCKS_PER_REQUEST):
            batch = blocks[i:i + _MAX_BLOCKS_PER_REQUEST]
            response = retry_with_backoff(
                lambda b=batch: self._client.blocks.children.append(
                    block_id=parent_id, children=b,
                ),
                self._rate_limiter,
            )
            created.extend(response.get("results", []))
        return created

    def _append_chapter_children(self, chapter_block_id: str,
                                 blocks: List[Dict[str, Any]]) -> None:
        """以 toggle 為單位切批（不得把一個 toggle 的 children 拆到兩個
        request），批次預算按含巢狀的總 block 數計。"""
        batch: List[Dict[str, Any]] = []
        budget = 0
        for block in blocks:
            size = total_block_count(block)
            if batch and budget + size > _BATCH_SIZE:
                self._append_blocks(chapter_block_id, batch)
                batch, budget = [], 0
            batch.append(block)
            budget += size
        if batch:
            self._append_blocks(chapter_block_id, batch)

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
    def _is_sync_generated(block: Dict[str, Any]) -> bool:
        return block.get("type") in _SYNC_GENERATED_BLOCK_TYPES

    def _list_page_blocks(self, page_id: str) -> List[Dict[str, Any]]:
        blocks: List[Dict[str, Any]] = []
        cursor: Optional[str] = None
        while True:
            kwargs: Dict[str, Any] = {"block_id": page_id, "page_size": 100}
            if cursor:
                kwargs["start_cursor"] = cursor
            response = retry_with_backoff(
                lambda k=kwargs: self._client.blocks.children.list(**k),
                self._rate_limiter,
            )
            blocks.extend(response.get("results", []))
            if not response.get("has_more"):
                return blocks
            cursor = response.get("next_cursor")

    def _delete_sync_generated_blocks(self, page_id: str) -> int:
        deleted = 0
        for block in self._list_page_blocks(page_id):
            if not self._is_sync_generated(block):
                continue
            retry_with_backoff(
                lambda b=block: self._client.blocks.delete(block_id=b["id"]),
                self._rate_limiter,
            )
            deleted += 1
        return deleted


def _clean_html(text: str) -> str:
    clean = re.sub(r'<[^>]+>', '', text)
    clean = re.sub(r'\s+', ' ', clean).strip()
    return (clean
            .replace('&amp;', '&')
            .replace('&lt;', '<')
            .replace('&gt;', '>')
            .replace('&quot;', '"')
            .replace('&#39;', "'"))
