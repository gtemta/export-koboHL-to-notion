from dataclasses import dataclass, field
from typing import List, Tuple


@dataclass
class CardRevisionReport:
    """revise_cards 一次執行的結果。"""
    planned: List[Tuple[str, str]] = field(default_factory=list)   # dry-run：(卡片標題, 會做什麼)
    reviewed: List[str] = field(default_factory=list)              # 只審目前版本的卡
    regenerated: List[str] = field(default_factory=list)           # 審核並附上候選版本的卡
    skipped: List[Tuple[str, str]] = field(default_factory=list)   # (卡片標題, 原因)
    failed: List[Tuple[str, str]] = field(default_factory=list)    # (卡片標題, 原因)；什麼都沒寫
    aborted: str = ""                                              # 非空 = 整次中止、什麼都沒寫
