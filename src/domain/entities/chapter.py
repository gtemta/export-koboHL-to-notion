from dataclasses import dataclass
from typing import List

from .highlight import Highlight


@dataclass
class Chapter:
    """章節實體類"""
    name: str
    progress: float
    highlights: List[Highlight]

    def get_max_progress(self) -> float:
        """獲取章節內最高進度"""
        if not self.highlights:
            return self.progress
        return max(h.chapter_progress for h in self.highlights)

    def highlight_count(self) -> int:
        """獲取高亮數量"""
        return len([h for h in self.highlights if h.is_valid()])