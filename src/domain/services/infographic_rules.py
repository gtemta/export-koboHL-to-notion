"""Pure rules for card infographic specs (no IO).

模型的原始 JSON 不可信：行數會超、字會爆、圖示名會編造、鄰居卡可能根本不在這本書裡。
`normalize_spec`／`normalize_book_map` 把這些全部收斂成可信的實體，之後的渲染不必再防禦。
"""
from typing import Any, Dict, List, Optional, Sequence, Tuple

from ..entities.infographic_spec import InfographicSpec, MapEntry, Neighbor, Node

MAX_LINES = 3
# 1080px 畫布、38px 字、左右留白後一行約 24 字，留 2 字餘裕。
MAX_LINE_CHARS = 22
# 圖示下方的標籤放在 270px 寬的格子裡，34px 字，換兩行也只容得下這麼多。
MAX_LABEL_CHARS = 8
MIN_NODES = 3
MAX_NODES = 4
MAX_NEIGHBORS = 3

LAYOUTS = ("flow", "contrast", "cause", "hierarchy", "cycle")
DEFAULT_LAYOUT = "flow"
ROLES = ("主軸", "支柱", "案例")
DEFAULT_ROLE = "案例"          # 最保守：不替沒把握的卡宣稱它是全書主軸
RELATIONS = ("前提", "導向", "對照")

# 圖示白名單（Lucide 圖示名）。模型只能從這裡挑，不能自由生成——
# 與 zettelkasten_generator._ICON_PALETTE 同一個作法。每個名字都要有對應的 SVG
# （src/infrastructure/infographic/icons/，有測試把關）。
ICON_NAMES = (
    "target", "lightbulb", "repeat", "compass", "key", "puzzle",
    "layers", "link", "scale", "shield", "heart", "brain",
    "users", "clock", "flame", "sprout", "search", "flag",
    "mountain", "map", "lock", "rocket", "trending-up", "eye",
    "hourglass", "route", "anchor", "arrow-right",
)
# 模型給的節點不足 MIN_NODES 時依序用這些（無標籤）遞補。
DEFAULT_ICONS = ("target", "lightbulb", "repeat", "compass")

_CUT_MARKS = "，。；、！？：,.;:!?"


def _clean_lines(value: Any) -> List[str]:
    if isinstance(value, str):
        value = value.splitlines()
    if not isinstance(value, list):
        return []
    lines = [item.strip() for item in value if isinstance(item, str) and item.strip()]
    return [_fit_line(line) for line in lines[:MAX_LINES]]


def _fit_line(line: str) -> str:
    """過長的行優先斷在字數內的最後一個標點，沒有標點才硬切並補「…」。"""
    if len(line) <= MAX_LINE_CHARS:
        return line
    window = line[:MAX_LINE_CHARS]
    cut = max(window.rfind(mark) for mark in _CUT_MARKS)
    if cut >= 0:
        return window[: cut + 1]
    return line[: MAX_LINE_CHARS - 1] + "…"


def _clean_label(value: Any) -> str:
    if not isinstance(value, str):
        return ""
    label = value.strip()
    if len(label) > MAX_LABEL_CHARS:
        label = label[: MAX_LABEL_CHARS - 1] + "…"
    return label


def _clean_nodes(value: Any) -> List[Node]:
    nodes: List[Node] = []
    seen = set()
    for item in value if isinstance(value, list) else []:
        if isinstance(item, str):
            icon, label = item, ""
        elif isinstance(item, dict):
            icon, label = item.get("icon"), _clean_label(item.get("label"))
        else:
            continue
        if not isinstance(icon, str) or icon not in ICON_NAMES or icon in seen:
            continue
        seen.add(icon)
        nodes.append(Node(icon=icon, label=label))
    nodes = nodes[:MAX_NODES]
    for icon in DEFAULT_ICONS:
        if len(nodes) >= MIN_NODES:
            break
        if icon not in {n.icon for n in nodes}:
            nodes.append(Node(icon=icon))
    return nodes


def _clean_neighbors(value: Any, card_title: str, sibling_titles: Sequence[str]) -> List[Neighbor]:
    allowed = set(sibling_titles) - {card_title}
    neighbors: List[Neighbor] = []
    seen = set()
    for item in value if isinstance(value, list) else []:
        if not isinstance(item, dict):
            continue
        relation, title = item.get("relation"), item.get("title")
        if not isinstance(title, str) or relation not in RELATIONS:
            continue
        if title not in allowed or title in seen:
            continue
        seen.add(title)
        neighbors.append(Neighbor(relation=relation, title=title))
    return neighbors[:MAX_NEIGHBORS]


def normalize_spec(
    raw: Any, card_title: str, sibling_titles: Sequence[str]
) -> Optional[InfographicSpec]:
    """模型原始輸出 → 可信的 InfographicSpec；連一行可用文字都沒有就回傳 None。

    sibling_titles 是同一本書所有卡的標題，鄰居卡必須出自其中（防模型編造）。"""
    if not isinstance(raw, dict):
        return None
    lines = _clean_lines(raw.get("lines"))
    if not lines:
        return None
    layout = raw.get("layout")
    role = raw.get("role")
    return InfographicSpec(
        card_title=card_title,
        lines=lines,
        nodes=_clean_nodes(raw.get("nodes")),
        layout=layout if layout in LAYOUTS else DEFAULT_LAYOUT,
        role=role if role in ROLES else DEFAULT_ROLE,
        neighbors=_clean_neighbors(raw.get("neighbors"), card_title, sibling_titles),
    )


def _is_card_number(value: Any, count: int) -> bool:
    # bool 是 int 的子類別；True 不能當成第 1 張卡。字串數字也不收——寧缺勿猜。
    return isinstance(value, int) and not isinstance(value, bool) and 1 <= value <= count


def normalize_book_map(
    raw: Any, titles: Sequence[str]
) -> Tuple[str, Dict[str, MapEntry]]:
    """全書概念地圖的原始輸出 → (全書主軸, {卡片標題: MapEntry})。

    模型用「編號」指卡（1 起算、對應 titles 順序）而不是複誦標題——小模型會改寫標題，
    編號則可以由程式精確對回。每張卡都保證有 entry：模型漏掉的卡退回預設角色、無鄰居，
    所以呼叫端不需要再判斷「這張卡有沒有被分析到」。"""
    data = raw if isinstance(raw, dict) else {}
    theme = data.get("theme")
    theme = theme.strip() if isinstance(theme, str) else ""

    count = len(titles)
    entries: Dict[str, MapEntry] = {title: MapEntry(role=DEFAULT_ROLE) for title in titles}
    seen_cards = set()
    cards = data.get("cards")
    for item in cards if isinstance(cards, list) else []:
        if not isinstance(item, dict) or not _is_card_number(item.get("n"), count):
            continue
        number = item["n"]
        if number in seen_cards:
            continue
        seen_cards.add(number)
        role = item.get("role")
        entries[titles[number - 1]] = MapEntry(
            role=role if role in ROLES else DEFAULT_ROLE,
            neighbors=_map_neighbors(item.get("neighbors"), number, titles),
        )
    return theme, entries


def _map_neighbors(value: Any, own_number: int, titles: Sequence[str]) -> List[Neighbor]:
    neighbors: List[Neighbor] = []
    seen = set()
    for item in value if isinstance(value, list) else []:
        if not isinstance(item, dict):
            continue
        relation, number = item.get("relation"), item.get("n")
        if relation not in RELATIONS or not _is_card_number(number, len(titles)):
            continue
        if number == own_number or number in seen:
            continue
        seen.add(number)
        neighbors.append(Neighbor(relation=relation, title=titles[number - 1]))
    return neighbors[:MAX_NEIGHBORS]
