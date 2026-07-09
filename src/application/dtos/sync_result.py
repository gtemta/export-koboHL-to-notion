from dataclasses import dataclass
from typing import List


@dataclass
class SyncResult:
    """同步結果數據傳輸對象"""
    total_books: int
    successful_syncs: int
    errors: List[str] = None

    def __post_init__(self):
        if self.errors is None:
            self.errors = []

    @property
    def failed_syncs(self) -> int:
        """動態計算：successful_syncs 由 execute() 事後遞增，不能在建構時定格"""
        return self.total_books - self.successful_syncs


    @property
    def success_rate(self) -> float:
        """成功率百分比"""
        if self.total_books == 0:
            return 0.0
        return (self.successful_syncs / self.total_books) * 100
    
    def add_error(self, error: str) -> None:
        """添加錯誤信息"""
        self.errors.append(error)