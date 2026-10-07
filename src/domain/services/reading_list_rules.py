"""Pure rules for Reading List page completion (no IO)."""
import unicodedata
from typing import Dict, List, Sequence

from ..entities.book_card import BookCard


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
