import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Callable, List, Optional, Tuple

from ...domain.entities.book import Book
from ...domain.repositories.book_repository import BookRepository
from ...domain.repositories.notion_repository import NotionRepository
from ...domain.services.chapter_extractor import ChapterExtractor
from ..dtos.sync_result import SyncResult
from .complete_reading_list_page_use_case import CompleteReadingListPageUseCase
from .generate_book_cards_use_case import GenerateBookCardsUseCase


class SyncBooksUseCase:
    """同步書籍用例"""

    def __init__(self,
                 book_repo: BookRepository,
                 notion_repo: NotionRepository,
                 chapter_extractor: ChapterExtractor,
                 max_workers: int = 5,
                 card_use_case: Optional[GenerateBookCardsUseCase] = None,
                 should_resync: Optional[Callable[[str], bool]] = None,
                 page_use_case: Optional[CompleteReadingListPageUseCase] = None,
                 should_complete_page: Optional[Callable[[str], bool]] = None):
        self.book_repo = book_repo
        self.notion_repo = notion_repo
        self.chapter_extractor = chapter_extractor
        self.max_workers = max_workers
        self.card_use_case = card_use_case
        # 書名 → 是否重建已匯出頁面的劃線內容（RESYNC_HIGHLIGHTS）
        self.should_resync = should_resync or (lambda _title: False)
        # 同步後補完 Reading List 書頁（READING_LIST_PAGES）；None = 功能關閉
        self.page_use_case = page_use_case
        self.should_complete_page = should_complete_page or (lambda _title: False)
        self.logger = logging.getLogger(__name__)

    def execute(self) -> SyncResult:
        """執行同步流程"""
        self.logger.info("開始同步書籍到Notion")

        books = self.book_repo.get_all_books()
        self.logger.info(f"找到 {len(books)} 本書籍待處理")

        if not books:
            return SyncResult(total_books=0, successful_syncs=0)

        result = SyncResult(total_books=len(books), successful_syncs=0)
        # (書, 劃線頁 id)：as_completed 迴圈跑在主執行緒，append 不需要鎖
        synced: List[Tuple[Book, str]] = []

        # 使用線程池並行處理
        with ThreadPoolExecutor(max_workers=min(self.max_workers, len(books))) as executor:
            future_to_book = {
                executor.submit(self._process_single_book, book): book
                for book in books
            }

            for future in as_completed(future_to_book):
                book = future_to_book[future]
                try:
                    page_id = future.result()
                    if page_id:
                        result.successful_syncs += 1
                        synced.append((book, page_id))
                        self.logger.info(f"成功處理書籍: {book.title}")
                    else:
                        result.add_error(f"處理失敗: {book.title}")
                except Exception as e:
                    error_msg = f"處理書籍 {book.title} 時發生錯誤: {str(e)}"
                    result.add_error(error_msg)
                    self.logger.error(error_msg, exc_info=True)

        self._complete_reading_list_pages(synced, result)

        self.logger.info(
            f"同步完成。成功: {result.successful_syncs}/{result.total_books} "
            f"({result.success_rate:.1f}%)")
        return result

    def _complete_reading_list_pages(self, synced: List[Tuple[Book, str]],
                                     result: SyncResult) -> None:
        """執行緒池結束後，依書名順序逐本補 Reading List 書頁。

        刻意不並行：M2 會用地端 LLM，VRAM 一次只放得下一個模型；依序也讓 log 可讀。
        單本失敗只記進錯誤清單，不算劃線同步失敗、不影響 exit code。
        """
        if self.page_use_case is None:
            return
        for book, page_id in sorted(synced, key=lambda pair: pair[0].title):
            if not self.should_complete_page(book.title):
                continue
            try:
                self.page_use_case.execute(book, page_id)
            except Exception as e:
                error_msg = f"補頁失敗: {book.title}: {e}"
                result.add_error(error_msg)
                self.logger.error(error_msg, exc_info=True)

    def _process_single_book(self, book) -> Optional[str]:
        """處理單本書籍；成功回傳劃線頁 id，失敗回傳 None"""
        try:
            clean_title = book.get_clean_title()

            # 檢查書籍是否已存在且已導出
            book_status = self.notion_repo.check_book_exists(clean_title, is_exported=True)

            if book_status["is_target_valid"]:
                # 書籍已存在且已導出，更新元數據
                self.logger.info(f"書籍 {clean_title} 已導出，更新元數據")
                page_id = book_status["pageId"]
                highlights = None
                if self.should_resync(clean_title):
                    # RESYNC_HIGHLIGHTS 命中：刪除同步產生的 block 後重建劃線
                    self.logger.info(f"重建 {clean_title} 的劃線內容 (resync)")
                    highlights = self.book_repo.get_highlights_with_chapters(book.id)
                    self.notion_repo.replace_book_highlights(page_id, highlights)
                self.notion_repo.update_book_metadata(page_id, book)
                self.notion_repo.add_book_cover(page_id, book)
                # 補齊卡片：若卡片盒尚無此書關聯卡片，repo 內 dedup 會控制是否實際新增
                if self.card_use_case is not None:
                    if highlights is None:
                        highlights = self.book_repo.get_highlights_with_chapters(book.id)
                    self.card_use_case.execute(book, highlights, source_page_id=page_id)
                return page_id

            # 檢查書籍是否存在但未導出
            book_status = self.notion_repo.check_book_exists(clean_title, is_exported=False)
            page_id = book_status.get("pageId")

            if not book_status["is_target_valid"]:
                # 書籍不存在，創建新條目
                self.logger.info(f"創建新書籍條目: {clean_title}")
                if not self.notion_repo.create_book_entry(clean_title):
                    return None

                # 重新獲取頁面ID
                new_book_status = self.notion_repo.check_book_exists(clean_title, is_exported=False)
                page_id = new_book_status.get("pageId")

            if not page_id:
                self.logger.error(f"無法獲取書籍 {clean_title} 的頁面ID")
                return None

            # 獲取並處理高亮內容
            highlights = self.book_repo.get_highlights_with_chapters(book.id)

            # Repo 已做完整章節提取;extractor 僅在章節名稱仍為預設值時作 fallback
            for highlight in highlights:
                if highlight.chapter_name in (None, '', '未知章節', '未知章节'):
                    highlight_data = {
                        'text': highlight.text,
                        'content_id': highlight.content_id,
                        'start_container_path': highlight.start_container_path
                    }
                    highlight.chapter_name = self.chapter_extractor.extract_chapter_name(highlight_data)

            self.logger.info(f"找到 {len(highlights)} 個高亮內容，開始同步")

            # 同步高亮內容到Notion
            self.notion_repo.sync_book_highlights(page_id, highlights)

            # 產生 Zettelkasten 卡片並上傳卡片盒（若已啟用）
            if self.card_use_case is not None:
                self.card_use_case.execute(book, highlights, source_page_id=page_id)

            # 更新書籍元數據
            self.notion_repo.update_book_metadata(page_id, book)

            # 添加書籍封面
            self.notion_repo.add_book_cover(page_id, book)

            return page_id

        except Exception as e:
            self.logger.error(f"處理書籍 {book.title} 時發生錯誤: {str(e)}", exc_info=True)
            return None
