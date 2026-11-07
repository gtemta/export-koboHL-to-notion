from dataclasses import dataclass, field
from typing import List


@dataclass
class BookCard:
    """A 卡片盒 card as read back from Notion (Reading List page completion)."""
    page_id: str
    title: str
    tags: List[str] = field(default_factory=list)      # Tags multi_select（固定分類）
    keywords: List[str] = field(default_factory=list)  # Key Word（自由概念）
    content: str = ""                                   # 卡片內文；M2 才讀
