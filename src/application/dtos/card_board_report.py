from dataclasses import dataclass, field
from typing import List, Tuple


@dataclass
class CardBoardReport:
    """build_card_board 一次執行的結果。"""
    planned: List[str] = field(default_factory=list)                 # dry-run：每本書一行
    processed: List[Tuple[str, int]] = field(default_factory=list)   # (書名, 寫入幾張卡)
    untouched: List[str] = field(default_factory=list)               # 沒有任何卡需要更新的書
    failed: List[Tuple[str, str]] = field(default_factory=list)      # (書名或書頁 id, 原因)
    no_source_cards: int = 0                                         # 沒有「來源」的卡，不處理
    aborted: str = ""                                                # 非空 = 整次中止、什麼都沒寫
