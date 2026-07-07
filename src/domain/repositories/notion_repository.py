from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional

from ..entities.book import Book
from ..entities.highlight import Highlight


class NotionRepository(ABC):
    """Notion 資料庫接口"""
    
    @abstractmethod
    def check_book_exists(self, title: str, is_exported: bool = True) -> Dict[str, Any]:
        """檢查書籍是否存在於Notion資料庫"""
        pass
    
    @abstractmethod
    def create_book_entry(self, title: str) -> bool:
        """創建新的書籍條目"""
        pass
    
    @abstractmethod
    def sync_book_highlights(self, page_id: str, highlights: List[Highlight]) -> None:
        """同步書籍高亮到Notion頁面"""
        pass
    
    @abstractmethod
    def update_book_metadata(self, page_id: str, book: Book) -> None:
        """更新書籍元數據"""
        pass
    
    @abstractmethod
    def add_book_cover(self, page_id: str, title: str, isbn: Optional[str] = None) -> None:
        """添加書籍封面"""
        pass