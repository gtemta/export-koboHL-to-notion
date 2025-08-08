from abc import ABC, abstractmethod
from typing import List
from ..entities.book import Book
from ..entities.highlight import Highlight


class BookRepository(ABC):
    """書籍資料庫接口"""
    
    @abstractmethod
    def get_all_books(self) -> List[Book]:
        """獲取所有書籍"""
        pass
    
    @abstractmethod  
    def get_highlights_with_chapters(self, book_id: str) -> List[Highlight]:
        """獲取書籍的高亮內容（含章節信息）"""
        pass