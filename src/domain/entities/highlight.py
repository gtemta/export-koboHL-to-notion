from dataclasses import dataclass
from typing import Optional


@dataclass
class Highlight:
    """高亮實體類"""
    text: str
    chapter_name: str
    chapter_progress: float
    content_id: str
    start_container_path: Optional[str] = None
    end_container_path: Optional[str] = None
    chapter_id_bookmarked: Optional[str] = None
    current_chapter_estimate: Optional[float] = None
    current_chapter_progress: Optional[float] = None

    def is_valid(self) -> bool:
        """檢查高亮是否有效"""
        return bool(self.text and self.text.strip())