"""卡片角色看板的決策邏輯（純函式）：排順序、合併兩次模型回應、算出「只填空白」的寫入計畫。

產品規則：程式只補空白，不覆寫、不移除使用者改過的任何值。"""
import hashlib
import math
import random
from typing import Any, Dict, FrozenSet, List, Mapping, Optional, Sequence, Set, Tuple

from src.domain.entities.board_card import BoardCard, CardUpdate, MapRun
from src.domain.services.infographic_rules import (
    DEFAULT_ROLE,
    MIN_MAP_COVERAGE,
    ROLES,
    clean_role,
    is_card_number,
)

READING_ORDER_STEP = 10
# 少於這個張數的書不值得跑模型（角色填預設、只排順序）。
MIN_CARDS_FOR_MAP = 3


def needs_map(cards: Sequence[BoardCard]) -> bool:
    return any(not card.role for card in cards)


def sort_by_book_order(
    cards: Sequence[BoardCard], positions: Mapping[str, Tuple[int, float]]
) -> List[BoardCard]:
    """依劃線在書中的位置排序；查不到位置的（手動卡、別台機器的卡）排最後，彼此依建立時間。"""
    known = [c for c in cards if c.source_id and c.source_id in positions]
    unknown = [c for c in cards if not (c.source_id and c.source_id in positions)]
    known.sort(key=lambda c: positions[c.source_id])
    unknown.sort(key=lambda c: c.created_time)
    return known + unknown


def shuffled_listing(cards: Sequence[BoardCard], book_title: str) -> List[BoardCard]:
    """給模型看的卡片清單：以書名為種子洗牌，避免模型把「清單順序」當成閱讀順序。

    種子用 sha1——內建 hash() 每個 process 有隨機 salt，同一本書每次跑會得到不同順序。"""
    seed = int(hashlib.sha1(book_title.encode("utf-8")).hexdigest(), 16)
    listing = list(cards)
    random.Random(seed).shuffle(listing)
    return listing


def parse_map_run(raw: Any, page_ids: Sequence[str]) -> Optional[MapRun]:
    """模型一次回應 → MapRun；`n` 依 page_ids 順序從 1 起算。

    與 normalize_book_map 同一套覆蓋率規則：定位到的卡不足 MIN_MAP_COVERAGE 視為失敗。
    鄰居只看 `n`（不看 relation），自己與超出範圍的丟棄；模型輸出不可信，形狀不對就當沒有。"""
    count = len(page_ids)
    data = raw if isinstance(raw, dict) else {}
    cards = data.get("cards")
    roles: Dict[str, str] = {}
    links: Set[FrozenSet[str]] = set()
    seen: Set[int] = set()
    for item in cards if isinstance(cards, list) else []:
        if not isinstance(item, dict) or not is_card_number(item.get("n"), count):
            continue
        number = item["n"]
        if number in seen:
            continue
        seen.add(number)
        roles[page_ids[number - 1]] = clean_role(item.get("role"))
        neighbors = item.get("neighbors")
        for neighbor in neighbors if isinstance(neighbors, list) else []:
            if not isinstance(neighbor, dict):
                continue
            other = neighbor.get("n")
            if is_card_number(other, count) and other != number:
                links.add(frozenset({page_ids[number - 1], page_ids[other - 1]}))
    if not seen or len(seen) < count * MIN_MAP_COVERAGE:
        return None
    return MapRun(roles=roles, links=frozenset(links))


def merge_map_runs(first: MapRun, second: MapRun) -> MapRun:
    """兩次回應只留下都出現的連結；角色不同取較低階（主軸 > 支柱 > 案例），只出現一次的用那次的。"""
    roles = dict(first.roles)
    for page_id, role in second.roles.items():
        if page_id in roles:
            roles[page_id] = max(roles[page_id], role, key=ROLES.index)
        else:
            roles[page_id] = role
    return MapRun(roles=roles, links=first.links & second.links)


def plan_book_updates(
    cards: Sequence[BoardCard],
    merged: Optional[MapRun],
    positions: Mapping[str, Tuple[int, float]],
) -> List[CardUpdate]:
    """一本書的寫入計畫：只填空白欄位，沒有要改的卡不產生 CardUpdate。

    merged 為 None 代表沒跑模型：角色填 DEFAULT_ROLE、不建連結。
    連結只在「至少一端是新卡（角色空白）」時才加——兩張都已建立過的卡之間若沒有連結，
    可能是使用者刪的，不能加回去。"""
    roles = merged.roles if merged else {}
    new_ids = {c.page_id for c in cards if not c.role}
    orders = _assign_orders(cards, positions)
    additions = _link_additions(cards, merged, new_ids)

    updates: List[CardUpdate] = []
    for card in cards:
        role = roles.get(card.page_id, DEFAULT_ROLE) if card.page_id in new_ids else None
        order = orders.get(card.page_id)
        added = additions.get(card.page_id)
        related = card.related_ids + tuple(sorted(added)) if added else None
        if role is None and order is None and related is None:
            continue
        updates.append(
            CardUpdate(page_id=card.page_id, role=role, reading_order=order, related_ids=related)
        )
    return updates


def _assign_orders(
    cards: Sequence[BoardCard], positions: Mapping[str, Tuple[int, float]]
) -> Dict[str, int]:
    """閱讀順序空白的卡依書中順序編號：接在同書既有最大值（取整）之後，沒有既有值從 10 起。"""
    existing = [c.reading_order for c in cards if c.reading_order is not None]
    number = (math.floor(max(existing)) if existing else 0) + READING_ORDER_STEP
    blanks = sort_by_book_order([c for c in cards if c.reading_order is None], positions)
    orders: Dict[str, int] = {}
    for card in blanks:
        orders[card.page_id] = number
        number += READING_ORDER_STEP
    return orders


def _link_additions(
    cards: Sequence[BoardCard], merged: Optional[MapRun], new_ids: Set[str]
) -> Dict[str, Set[str]]:
    """每張卡要新增的連結對象（兩端都寫：單一欄位的自我關聯 API 只寫一邊，另一邊讀不到）。"""
    if not merged:
        return {}
    by_id = {c.page_id: c for c in cards}
    additions: Dict[str, Set[str]] = {}
    for pair in merged.links:
        if len(pair) != 2 or not all(p in by_id for p in pair) or not pair & new_ids:
            continue
        for page_id in pair:
            (other,) = pair - {page_id}
            card = by_id[page_id]
            if card.related_complete and other not in card.related_ids:
                additions.setdefault(page_id, set()).add(other)
    return additions
