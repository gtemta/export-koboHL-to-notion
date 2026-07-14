"""Pure block builders for the highlight page (v2 兩層巢狀 toggle 版面).

No Notion client here — NotionApiRepository owns API orchestration; this
module owns grouping and block construction so layout stays unit-testable.

Notion API 限制（本模組據此設計）：
- rich_text 單段 ≤ 2000 字 → split_rich_text 切多段（零遺失）
- 單一 block 的 children ≤ 100 → 小節 toggle 超過 90 條拆「(續)」
"""
from dataclasses import dataclass, field
from typing import Any, Dict, List, Tuple

from ...domain.entities.highlight import Highlight

PAGE_TITLE = "📌 劃線筆記"
RICH_TEXT_LIMIT = 2000
MAX_TOGGLE_CHILDREN = 90


def split_rich_text(text: str, limit: int = RICH_TEXT_LIMIT) -> List[Dict[str, Any]]:
    text = text or ""
    if not text:
        return [{"type": "text", "text": {"content": ""}}]
    return [
        {"type": "text", "text": {"content": text[i:i + limit]}}
        for i in range(0, len(text), limit)
    ]


def heading_block(text: str, level: int = 1,
                  toggleable: bool = False) -> Dict[str, Any]:
    key = f"heading_{level}"
    payload: Dict[str, Any] = {"rich_text": split_rich_text(text)}
    if toggleable:
        payload["is_toggleable"] = True
    return {"object": "block", "type": key, key: payload}


def _annotation_callout(text: str) -> Dict[str, Any]:
    return {
        "object": "block",
        "type": "callout",
        "callout": {
            "icon": {"type": "emoji", "emoji": "💭"},
            "rich_text": split_rich_text(text),
        },
    }


def quote_block(h: Highlight) -> Dict[str, Any]:
    block: Dict[str, Any] = {
        "object": "block",
        "type": "quote",
        "quote": {"rich_text": split_rich_text(h.text)},
    }
    if h.has_annotation():
        block["quote"]["children"] = [_annotation_callout(h.annotation.strip())]
    return block


@dataclass
class ChapterGroup:
    title: str
    direct: List[Highlight] = field(default_factory=list)  # 章直下（無小節）
    sections: List[Tuple[str, List[Highlight]]] = field(default_factory=list)


def _sanitize_chapter_name(name: str) -> str:
    if name in ("未知章節", "未知章节"):
        return "其他內容"
    return name[:47] + "..." if len(name) > 50 else name


def chapter_tree(highlights: List[Highlight]) -> List[ChapterGroup]:
    """依（章, 小節）分組，維持輸入順序（上游已按 spine+progress 排序）。"""
    groups: List[ChapterGroup] = []
    index: Dict[str, ChapterGroup] = {}
    for h in highlights:
        chapter = h.toc_chapter or _sanitize_chapter_name(
            h.chapter_name or "未知章節")
        group = index.get(chapter)
        if group is None:
            group = ChapterGroup(title=chapter)
            index[chapter] = group
            groups.append(group)
        if h.toc_section:
            for title, items in group.sections:
                if title == h.toc_section:
                    items.append(h)
                    break
            else:
                group.sections.append((h.toc_section, [h]))
        else:
            group.direct.append(h)
    return groups


def _section_toggles(title: str, items: List[Highlight]) -> List[Dict[str, Any]]:
    quotes = [quote_block(h) for h in items if h.text]
    toggles: List[Dict[str, Any]] = []
    for i in range(0, len(quotes), MAX_TOGGLE_CHILDREN):
        label = title if i == 0 else f"{title} (續)"
        toggle = heading_block(label, level=2, toggleable=True)
        toggle["heading_2"]["children"] = quotes[i:i + MAX_TOGGLE_CHILDREN]
        toggles.append(toggle)
    return toggles


def chapter_children(group: ChapterGroup) -> List[Dict[str, Any]]:
    """一個章 toggle 內的全部 blocks：直下 quotes 先、小節 toggles 後。"""
    blocks = [quote_block(h) for h in group.direct if h.text]
    for title, items in group.sections:
        blocks.extend(_section_toggles(title, items))
    return blocks


def total_block_count(block: Dict[str, Any]) -> int:
    """含巢狀 children 的總 block 數（append 批次預算用）。"""
    payload = block.get(block.get("type", ""), {})
    children = payload.get("children", [])
    return 1 + sum(total_block_count(c) for c in children)
