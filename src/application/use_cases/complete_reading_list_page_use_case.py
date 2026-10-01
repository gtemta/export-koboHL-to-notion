"""Complete a sync-created 📚 Personal Reading List page (M1: no LLM).

Spec: docs/superpowers/specs/2026-09-28-reading-list-book-pages-design.md
Only pages created by this integration are touched, and only what is still
empty is written — so re-running is a no-op and nothing a person typed is ever
overwritten.
"""
import logging
from typing import Dict, Optional

from ...domain.entities.book import Book
from ...domain.services.reading_list_rules import derive_book_types
from ...infrastructure.external.cover_fetcher import CoverFinder
from ...infrastructure.notion.notion_views_client import NotionViewsClient
from ...infrastructure.notion.reading_list_page_blocks import (
    SECTION_NOTES,
    find_section,
    is_blank_page,
    section_is_empty,
    skeleton_blocks,
)
from ...infrastructure.notion.reading_list_repository import (
    BOOK_TYPE_PROPERTY,
    ReadingListRepository,
)
from ...infrastructure.notion.zettelkasten_card_repository import (
    ZettelkastenCardRepository,
)

logger = logging.getLogger(__name__)


class CompleteReadingListPageUseCase:
    def __init__(
        self,
        reading_list: ReadingListRepository,
        card_repo: Optional[ZettelkastenCardRepository],
        views: Optional[NotionViewsClient],
        cover_finder: CoverFinder,
        cards_database_id: Optional[str],
        type_mapping: Dict[str, str],
    ):
        self._reading_list = reading_list
        self._card_repo = card_repo
        self._views = views
        self._cover_finder = cover_finder
        self._cards_database_id = cards_database_id
        self._type_mapping = type_mapping

    def execute(self, book: Book, kobo_page_id: str) -> None:
        page = self._reading_list.find_page(book.title, kobo_page_id)
        if page is None:
            logger.debug(f"'{book.title}' 沒有 Reading List 頁，跳過補頁")
            return
        if not self._reading_list.is_created_by_integration(page):
            logger.debug(f"'{book.title}' 的 Reading List 頁是手動建立的，不補")
            return

        page_id = page["id"]
        blocks = self._reading_list.list_blocks(page_id)
        blank = is_blank_page(blocks)
        # 骨架只有空白頁才需要封面；非空白頁只在 cover／icon 缺一時才需要——
        # 兩者皆無就不查，省掉每次同步對已完整頁面的下載。
        needs_visual = not page.get("cover") or not page.get("icon")
        cover_url = self._cover_finder.find(book) if (blank or needs_visual) else None
        if blank:
            logger.info(f"'{book.title}' 書頁為空白，將寫入版面（{page_id}）")
            self._reading_list.append_blocks(
                page_id, skeleton_blocks(book, cover_url, kobo_page_id))
            blocks = self._reading_list.list_blocks(page_id)

        self._ensure_card_gallery(book, page_id, blocks)
        self._ensure_cover(page, cover_url)
        self._ensure_book_types(book, page)

    def _ensure_card_gallery(self, book: Book, page_id: str, blocks) -> None:
        if self._views is None or not self._cards_database_id:
            return
        section = find_section(blocks, SECTION_NOTES)
        if section is None:
            logger.warning(f"'{book.title}' 書頁找不到「{SECTION_NOTES}」段，跳過卡片 gallery")
            return
        heading, body = section
        if not section_is_empty(body):
            return
        try:
            self._views.create_card_gallery(
                page_id, self._cards_database_id, page_id, heading["id"])
        except Exception as e:  # noqa: BLE001 — 下次同步段落仍空白，會自動重試
            logger.warning(f"'{book.title}' 卡片 gallery 建立失敗（下次同步重試）: {e}")

    def _ensure_cover(self, page: dict, cover_url: Optional[str]) -> None:
        if not cover_url:
            return
        need_cover = not page.get("cover")
        need_icon = not page.get("icon")
        if not (need_cover or need_icon):
            return
        self._reading_list.update_page(
            page["id"],
            cover_url=cover_url if need_cover else None,
            icon_url=cover_url if need_icon else None,
        )

    def _ensure_book_types(self, book: Book, page: dict) -> None:
        if self._card_repo is None:
            return
        prop = (page.get("properties") or {}).get(BOOK_TYPE_PROPERTY)
        if prop is None or prop.get("relation"):
            return
        if not self._reading_list.book_types_available():
            return
        cards = self._card_repo.list_book_cards(page["id"])
        names = derive_book_types(cards, self._type_mapping)
        if not names:
            if cards:
                logger.warning(
                    f"'{book.title}' 的 {len(cards)} 張卡片 Tags 都對不到書籍種類，"
                    f"不填 {BOOK_TYPE_PROPERTY}")
            return
        ids = self._reading_list.type_page_ids(names)
        missing = [name for name in names if name not in ids]
        if missing:
            logger.warning(f"書籍種類庫找不到：{'、'.join(missing)}（'{book.title}'）")
        found = [ids[name] for name in names if name in ids]
        if found:
            self._reading_list.update_page(
                page["id"],
                properties={BOOK_TYPE_PROPERTY: {"relation": [{"id": i} for i in found]}},
            )
