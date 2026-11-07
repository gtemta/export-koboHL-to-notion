from dataclasses import dataclass, field
from typing import List


@dataclass(frozen=True)
class Neighbor:
    """同一本書裡與本卡相關的另一張卡。relation: 前提／導向／對照。"""
    relation: str
    title: str


@dataclass(frozen=True)
class Node:
    """圖上的一個圖示＋圖示下方的短標籤（標籤可為空，只剩圖示）。"""
    icon: str
    label: str = ""


@dataclass(frozen=True)
class MapEntry:
    """全書概念地圖裡，一張卡的定位：它在全書的角色與它和其他卡的關係。"""
    role: str
    neighbors: List[Neighbor] = field(default_factory=list)


@dataclass(frozen=True)
class MarkedCard:
    """卡片盒裡被使用者勾選「做圖」的一張卡。source_id 是 `來源劃線ID`，
    用來回本地 cards_output 找完整卡片；手動建立的卡沒有，會是空字串。"""
    page_id: str
    title: str
    source_id: str


@dataclass
class InfographicSpec:
    """一張概念圖卡要畫什麼（尚未決定怎麼畫）。

    由 infographic_rules.normalize_spec 從模型的原始輸出整理而來，
    所以欄位值已經是可信的：行數／字數受限、圖示在白名單內、鄰居卡真的在同一本書。
    """
    card_title: str
    lines: List[str]                                  # ≤3 行
    nodes: List[Node]                                 # 3–4 個「圖示＋短標籤」
    layout: str                                       # flow/contrast/cause/hierarchy/cycle
    role: str                                         # 主軸／支柱／案例
    neighbors: List[Neighbor] = field(default_factory=list)
