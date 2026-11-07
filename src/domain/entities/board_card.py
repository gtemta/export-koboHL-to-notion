from dataclasses import dataclass
from typing import Dict, FrozenSet, Optional, Tuple


@dataclass(frozen=True)
class BoardCard:
    """卡片盒裡的一張卡，在「看板」流程眼中的樣子。"""
    page_id: str
    book_page_id: str                  # 來源 relation 第一筆；"" = 沒有來源
    title: str
    source_id: str                     # 來源劃線ID，可能為空
    created_time: str
    role: str = ""                     # "" = 新卡
    reading_order: Optional[float] = None   # 使用者可能手填 25.5，所以是 float
    related_ids: Tuple[str, ...] = ()
    related_complete: bool = True      # False = API 截斷（has_more），不可重寫
    content: str = ""                  # 要跑模型時才填


@dataclass(frozen=True)
class CardUpdate:
    """對一張卡要寫回 Notion 的欄位；None = 這個欄位不動。"""
    page_id: str
    role: Optional[str] = None
    reading_order: Optional[int] = None
    related_ids: Optional[Tuple[str, ...]] = None   # 寫入後的完整清單


@dataclass(frozen=True)
class MapRun:
    """一次模型回應整理後的結果（以 page id 為鍵，不靠標題）。"""
    roles: Dict[str, str]              # page_id -> 角色
    links: FrozenSet[FrozenSet[str]]   # 不分方向的一對 page_id
