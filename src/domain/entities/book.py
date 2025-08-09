from dataclasses import dataclass
from typing import Optional
from datetime import datetime


@dataclass
class Book:
    """書籍實體類"""
    id: str
    title: str
    author: Optional[str] = None
    subtitle: Optional[str] = None
    publisher: Optional[str] = None
    isbn: Optional[str] = None
    description: Optional[str] = None
    percent_read: Optional[float] = None
    date_last_read: Optional[datetime] = None
    time_spent_reading: Optional[int] = None
    last_time_finished_reading: Optional[datetime] = None

    def get_clean_title(self) -> str:
        """獲取不含副標題的清潔標題"""
        if ":" in self.title:
            return self.title.split(":")[0].strip()
        return self.title.strip()