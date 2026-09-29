"""Pure block builders for Reading List book pages (M1 layout).

Mirrors the user's「心得摘錄」template: six heading_2 sections. No Notion client
here — CompleteReadingListPageUseCase orchestrates the writes, this module owns
block construction and section lookup so both stay unit-testable.
"""
from typing import Any, Dict, List, Optional, Tuple

from ...domain.entities.book import Book
from ..external.cover_fetcher import is_real_isbn13
from .highlight_page_blocks import heading_block, split_rich_text
from .text_utils import clean_html

SECTION_BOOK_INFO = "書籍資料"
SECTION_NOTES = "筆記圖"
SECTION_OVERVIEW = "概要"
SECTION_ACTIONS = "實際執行"
SECTION_REFLECTION = "心得"
SECTION_QUOTES = "金句摘錄"
SECTIONS = (SECTION_BOOK_INFO, SECTION_NOTES, SECTION_OVERVIEW,
            SECTION_ACTIONS, SECTION_REFLECTION, SECTION_QUOTES)

DESCRIPTION_TOGGLE = "出版社簡介"
HIGHLIGHTS_LINK_TEXT = "畫線重點 → "

_HEADING_LEVELS = {"heading_1": 1, "heading_2": 2, "heading_3": 3}


def skeleton_blocks(book: Book, cover_url: Optional[str],
                    kobo_page_id: Optional[str]) -> List[Dict[str, Any]]:
    """The whole six-section layout, written once onto a blank page."""
    blocks: List[Dict[str, Any]] = [heading_block(SECTION_BOOK_INFO, level=2)]
    blocks += book_info_blocks(book, cover_url)
    blocks += [heading_block(name, level=2) for name in SECTIONS[1:]]
    if kobo_page_id:
        blocks.append(highlights_link_block(kobo_page_id))
    return blocks


def book_info_blocks(book: Book, cover_url: Optional[str]) -> List[Dict[str, Any]]:
    """書籍資料段：書封圖（gallery 預覽靠它）、作者／出版社／ISBN、出版社簡介。"""
    blocks: List[Dict[str, Any]] = []
    if cover_url:
        blocks.append({"object": "block", "type": "image",
                       "image": {"type": "external", "external": {"url": cover_url}}})
    facts = [("作者", book.author), ("出版社", book.publisher)]
    if is_real_isbn13(book.isbn):
        facts.append(("ISBN", book.isbn.strip()))
    for label, value in facts:
        if value and value.strip():
            blocks.append(_bullet(f"{label}：{value.strip()}"))
    description = clean_html(book.description or "")
    if description:
        blocks.append({"object": "block", "type": "toggle", "toggle": {
            "rich_text": split_rich_text(DESCRIPTION_TOGGLE),
            "children": [_paragraph(description)],
        }})
    return blocks


def highlights_link_block(kobo_page_id: str) -> Dict[str, Any]:
    """「畫線重點 → @劃線頁」——與使用者手動頁的金句摘錄寫法一致。"""
    return {"object": "block", "type": "paragraph", "paragraph": {"rich_text": [
        {"type": "text", "text": {"content": HIGHLIGHTS_LINK_TEXT}},
        {"type": "mention", "mention": {"type": "page", "page": {"id": kobo_page_id}}},
    ]}}


def block_text(block: Dict[str, Any]) -> str:
    """Plain text of a block — works for API responses (plain_text) and for
    blocks built here (text.content)."""
    payload = block.get(block.get("type", ""), {}) or {}
    return "".join(
        rt.get("plain_text") or (rt.get("text") or {}).get("content") or ""
        for rt in payload.get("rich_text") or []
    )


def is_blank_page(blocks: List[Dict[str, Any]]) -> bool:
    """No blocks, or only paragraphs without text."""
    return all(b.get("type") == "paragraph" and not block_text(b).strip() for b in blocks)


def find_section(blocks: List[Dict[str, Any]], name: str
                 ) -> Optional[Tuple[Dict[str, Any], List[Dict[str, Any]]]]:
    """(heading, body) of the section whose heading text equals `name`.

    The body runs until the next heading of the same or a higher level, so a
    `###` inside a `##` section is content — the user's own 概要 uses that.
    """
    for i, block in enumerate(blocks):
        level = _HEADING_LEVELS.get(block.get("type"))
        if level is None or block_text(block).strip() != name:
            continue
        body: List[Dict[str, Any]] = []
        for following in blocks[i + 1:]:
            other = _HEADING_LEVELS.get(following.get("type"))
            if other is not None and other <= level:
                break
            body.append(following)
        return block, body
    return None


def section_is_empty(body: List[Dict[str, Any]]) -> bool:
    return is_blank_page(body)


def _bullet(text: str) -> Dict[str, Any]:
    return {"object": "block", "type": "bulleted_list_item",
            "bulleted_list_item": {"rich_text": split_rich_text(text)}}


def _paragraph(text: str) -> Dict[str, Any]:
    return {"object": "block", "type": "paragraph",
            "paragraph": {"rich_text": split_rich_text(text)}}
