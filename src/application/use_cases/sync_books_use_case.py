import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import List

from ...domain.repositories.book_repository import BookRepository  
from ...domain.repositories.notion_repository import NotionRepository
from ...domain.services.chapter_extractor import ChapterExtractor
from ..dtos.sync_result import SyncResult


class SyncBooksUseCase:
    """同步書籍用例"""
    
    def __init__(self, 
                 book_repo: BookRepository,
                 notion_repo: NotionRepository,
                 chapter_extractor: ChapterExtractor,
                 max_workers: int = 5):
        self.book_repo = book_repo
        self.notion_repo = notion_repo
        self.chapter_extractor = chapter_extractor
        self.max_workers = max_workers
        self.logger = logging.getLogger(__name__)
    
    def execute(self) -> SyncResult:
        """執行同步流程"""
        self.logger.info("開始同步書籍到Notion")
        
        books = self.book_repo.get_all_books()
        self.logger.info(f"找到 {len(books)} 本書籍待處理")
        
        if not books:
            return SyncResult(total_books=0, successful_syncs=0)
        
        result = SyncResult(total_books=len(books), successful_syncs=0)
        
        # 使用線程池並行處理
        with ThreadPoolExecutor(max_workers=min(self.max_workers, len(books))) as executor:
            # 提交所有任務
            future_to_book = {
                executor.submit(self._process_single_book, book): book 
                for book in books
            }
            
            # 處理完成的任務
            for future in as_completed(future_to_book):
                book = future_to_book[future]
                try:
                    if future.result():
                        result.successful_syncs += 1
                        self.logger.info(f"成功處理書籍: {book.title}")
                    else:
                        result.add_error(f"處理失敗: {book.title}")
                except Exception as e:
                    error_msg = f"處理書籍 {book.title} 時發生錯誤: {str(e)}"
                    result.add_error(error_msg)
                    self.logger.error(error_msg, exc_info=True)
        
        self.logger.info(f"同步完成。成功: {result.successful_syncs}/{result.total_books} ({result.success_rate:.1f}%)")
        return result
    
    def _process_single_book(self, book) -> bool:
        """處理單本書籍"""
        try:
            clean_title = book.get_clean_title()
            
            # 檢查書籍是否已存在且已導出
            book_status = self.notion_repo.check_book_exists(clean_title, is_exported=True)
            
            if book_status["is_target_valid"]:
                # 書籍已存在且已導出，更新元數據
                self.logger.info(f"書籍 {clean_title} 已導出，更新元數據")
                page_id = book_status["pageId"]
                self.notion_repo.update_book_metadata(page_id, book)
                self.notion_repo.add_book_cover(page_id, book.title, book.isbn)
                return True
            
            # 檢查書籍是否存在但未導出
            book_status = self.notion_repo.check_book_exists(clean_title, is_exported=False)
            page_id = book_status.get("pageId")
            
            if not book_status["is_target_valid"]:
                # 書籍不存在，創建新條目
                self.logger.info(f"創建新書籍條目: {clean_title}")
                if not self.notion_repo.create_book_entry(clean_title):
                    return False
                
                # 重新獲取頁面ID
                new_book_status = self.notion_repo.check_book_exists(clean_title, is_exported=False)
                page_id = new_book_status.get("pageId")
            
            if not page_id:
                self.logger.error(f"無法獲取書籍 {clean_title} 的頁面ID")
                return False
            
            # 獲取並處理高亮內容
            highlights = self.book_repo.get_highlights_with_chapters(book.id)
            
            # 使用章節提取器處理高亮內容
            for highlight in highlights:
                highlight_data = {
                    'text': highlight.text,
                    'content_id': highlight.content_id,
                    'start_container_path': highlight.start_container_path
                }
                highlight.chapter_name = self.chapter_extractor.extract_chapter_name(highlight_data)
            
            self.logger.info(f"找到 {len(highlights)} 個高亮內容，開始同步")
            
            # 同步高亮內容到Notion
            self.notion_repo.sync_book_highlights(page_id, highlights)
            
            # 更新書籍元數據
            self.notion_repo.update_book_metadata(page_id, book)
            
            # 添加書籍封面
            self.notion_repo.add_book_cover(page_id, book.title, book.isbn)
            
            return True
            
        except Exception as e:
            self.logger.error(f"處理書籍 {book.title} 時發生錯誤: {str(e)}", exc_info=True)
            return False