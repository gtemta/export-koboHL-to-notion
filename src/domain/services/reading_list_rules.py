"""Pure rules for Reading List page completion (no IO)."""
import re
import unicodedata
from typing import Dict, List, Optional, Sequence

from ..entities.book import Book
from ..entities.book_card import BookCard

# 主書名（第一個冒號前）至少要這麼長才可信——一個字的書名會配到一堆不相干的書。
_MIN_MAIN_TITLE_LEN = 2


def _core(name: str) -> str:
    """Letters/digits only — same convention as the card classifier's
    `_category_core`, so "💞心理學" and "心理學" are the same tag."""
    return "".join(
        ch for ch in (name or "") if unicodedata.category(ch)[0] in ("L", "N")
    )


def derive_book_types(
    cards: Sequence[BookCard], mapping: Dict[str, str], max_types: int = 2
) -> List[str]:
    """Majority vote of card Tags → 書籍種類 names (spec「書籍種類推算」).

    - each card votes at most once per type (💼商務 + 💰理財投資 → one vote);
    - ties keep the mapping's order;
    - the runner-up is kept only with at least half the winner's votes.
    """
    tag_to_type = {_core(tag): book_type for tag, book_type in mapping.items() if _core(tag)}
    type_order: List[str] = []
    for book_type in mapping.values():
        if book_type not in type_order:
            type_order.append(book_type)

    votes: Dict[str, int] = {}
    for card in cards:
        card_types = {tag_to_type[_core(t)] for t in card.tags if _core(t) in tag_to_type}
        for book_type in card_types:
            votes[book_type] = votes.get(book_type, 0) + 1
    if not votes:
        return []

    ranked = sorted(votes, key=lambda t: (-votes[t], type_order.index(t)))
    winner = ranked[0]
    picked = [winner]
    for runner_up in ranked[1:max_types]:
        if votes[runner_up] * 2 >= votes[winner]:
            picked.append(runner_up)
    return picked


def _title_key(text: str) -> str:
    return _core(text).lower()


def _main_key(title: str) -> str:
    return _title_key(re.split(r"[:：]", title or "", maxsplit=1)[0])


def match_library_book(page_title: str, books: Sequence[Book]) -> Optional[Book]:
    """Reading List 頁名 → Kobo 書庫裡的同一本書（補封面用）。寧可不配也不配錯。

    1. 全名一致（忽略標點、全半形、大小寫、空白）；
    2. 否則主書名（第一個冒號前，至少 2 字）一致——頁名只寫短書名、或書庫只有短書名的情況。
    同一步命中多本不同的書（封面不同）就視為不確定，回傳 None，不去猜。
    書庫裡同一本書可能有多筆（封面相同），不算不確定。"""
    full = _title_key(page_title)
    if not full:
        return None
    candidates = [b for b in books if _title_key(b.title) == full]
    if not candidates:
        main = _main_key(page_title)
        if len(main) < _MIN_MAIN_TITLE_LEN:
            return None
        candidates = [b for b in books if _main_key(b.title) == main]
    if not candidates:
        return None
    covers = {b.image_id or b.id for b in candidates}
    return candidates[0] if len(covers) == 1 else None
