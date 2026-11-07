"""Complete a sync-created 📚 Personal Reading List page (M1: no LLM).

Spec: docs/superpowers/specs/2026-09-28-reading-list-book-pages-design.md
Only pages created by this integration are touched, and only what is still
empty is written — so re-running is a no-op and nothing a person typed is ever
overwritten. The one thing rewritten is what an earlier version wrote itself and
Notion cannot show: Kobo-CDN covers/icons/images (Kobo's CDN refuses Notion's
servers → "Permission denied"), replaced by an uploaded copy of the cover.
"""
import logging
from typing import Dict, Optional

from ...domain.entities.book import Book
from ...domain.services.reading_list_rules import derive_book_types
from ...infrastructure.external.cover_fetcher import is_kobo_cdn_visual
from ...infrastructure.notion.cover_uploader import CoverUploader
from ...infrastructure.notion.notion_views_client import NotionViewsClient
from ...infrastructure.notion.reading_list_page_blocks import (
    SECTION_NOTES,
    find_section,
    find_unusable_cover_image,
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
        cover_uploader: CoverUploader,
        cards_database_id: Optional[str],
        type_mapping: Dict[str, str],
        dry_run: bool = False,
    ):
        self._reading_list = reading_list
        self._card_repo = card_repo
        self._views = views
        self._cover_uploader = cover_uploader
        self._cards_database_id = cards_database_id
        self._type_mapping = type_mapping
        self._dry_run = dry_run

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
        broken_image = None if blank else find_unusable_cover_image(blocks)
        # 只有空白頁（寫骨架）、cover／icon 缺或壞、或圖片 block 壞了才需要書封——
        # 都不是就不查也不上傳，省掉每次同步對已完整頁面的下載與上傳。
        needs_visual = _visual_unusable(page.get("cover")) or _visual_unusable(page.get("icon"))
        file_id: Optional[str] = None
        if blank or needs_visual or broken_image is not None:
            file_id, failed = self._upload_cover(book)
            if failed and blank:
                # 骨架只寫在空白頁：沒有圖就寫，頁面不再空白，書封圖永遠補不回來。
                # 整本書這輪跳過，下次同步重試。
                return
        if blank:
            logger.info(f"'{book.title}' 書頁為空白，將寫入版面（{page_id}）")
            self._reading_list.append_blocks(
                page_id, skeleton_blocks(book, file_id, kobo_page_id))
            blocks = self._reading_list.list_blocks(page_id)
        elif broken_image is not None and file_id:
            self._reading_list.replace_image(broken_image["id"], file_id)

        self._ensure_card_board(book, page_id, blocks)
        self._ensure_cover(page, file_id)
        self._ensure_book_types(book, page)

    def _upload_cover(self, book: Book):
        """(file_upload id 或 None, 上傳是否失敗)。None 且未失敗＝哪裡都找不到封面。"""
        try:
            return self._cover_uploader.upload(book), False
        except Exception as e:  # noqa: BLE001 — 下次同步會重試，這輪不可拖垮其他步驟
            logger.warning(f"'{book.title}' 封面上傳失敗（下次同步重試）: {e}")
            return None, True

    def _ensure_card_board(self, book: Book, page_id: str, blocks) -> None:
        if self._views is None or not self._cards_database_id:
            return
        section = find_section(blocks, SECTION_NOTES)
        if section is None:
            logger.warning(f"'{book.title}' 書頁找不到「{SECTION_NOTES}」段，跳過卡片看板")
            return
        heading, body = section
        if not section_is_empty(body):
            return
        try:
            # 看板要用到的欄位（角色、閱讀順序等）先備齊；預覽時只讀不建。
            if self._card_repo is not None and not self._dry_run:
                self._card_repo.ensure_card_board_columns()
            self._views.create_card_board(
                page_id, self._cards_database_id, page_id, heading["id"])
        except Exception as e:  # noqa: BLE001 — 下次同步段落仍空白，會自動重試
            logger.warning(f"'{book.title}' 卡片看板建立失敗（下次同步重試）: {e}")

    def _ensure_cover(self, page: dict, file_id: Optional[str]) -> None:
        if not file_id:
            return
        need_cover = _visual_unusable(page.get("cover"))
        need_icon = _visual_unusable(page.get("icon"))
        if not (need_cover or need_icon):
            return
        self._reading_list.update_page(
            page["id"],
            cover_file_id=file_id if need_cover else None,
            icon_file_id=file_id if need_icon else None,
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


def _visual_unusable(visual: Optional[dict]) -> bool:
    """頁面 cover／icon 是空的，或是舊版寫下、Notion 讀不到的 Kobo 圖床網址。
    使用者自己設的（emoji、上傳的檔案、其他外部網址）一律視為可用，不覆蓋。"""
    return not visual or is_kobo_cdn_visual(visual)
