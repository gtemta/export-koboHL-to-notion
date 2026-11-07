from dataclasses import dataclass
from typing import Mapping


@dataclass(frozen=True)
class CardBlock:
    """卡片頁上的一個 block，只留判讀需要的部分。"""
    kind: str    # Notion block type
    text: str


@dataclass(frozen=True)
class CardBody:
    """從卡片頁讀出來的目前內容（使用者可能手動改過）。"""
    content: str              # 卡片本文
    highlight: str = ""       # 原文劃線：第一個 quote
    revision_note: str = ""   # 使用者寫的「待修正的點」


@dataclass(frozen=True)
class Verdict:
    """審核模型對一個版本的判定。"""
    scores: Mapping[str, int]   # consistency / correctness / shareability / atomicity
    notes: str = ""
    passed: bool = False


@dataclass(frozen=True)
class Candidate:
    """模型依「待修正的點」重產的版本。只給使用者看，不會寫進卡片本文。"""
    title: str
    content: str
    verdict: Verdict
