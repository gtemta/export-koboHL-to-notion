"""Notion repository for Zettelkasten cards.

Schema expected (matches 🗃️ 卡片盒重點收集):
  - 標題 (title)
  - 來源 (relation → Books DB / Personal Reading List)
Card content / source highlight / chapter reference go into the page body
as blocks, since the target DB has no matching properties for them.
"""
import logging
from typing import List, Optional

from notion_client import Client

from .rate_limiter import NotionRateLimiter
from .retry_policy import retry_with_backoff

# zettelkasten_generator lives at project root (not yet ported into src/)
from zettelkasten_generator import ZettelkastenCard

logger = logging.getLogger(__name__)

_RICH_TEXT_LIMIT = 2000


class ZettelkastenCardRepository:
    """Uploads Zettelkasten cards to the Notion 卡片盒 database.

    The `來源` relation targets the Books DB, not the Kobo highlights DB.
    We resolve it by querying the Books DB by book title; if no match is
    found, the card is still created but without the relation (the user
    can link it manually).
    """

    def __init__(
        self,
        token: str,
        database_id: str,
        books_database_id: Optional[str] = None,
        rate_limiter: Optional[NotionRateLimiter] = None,
    ):
        self._database_id = database_id
        self._books_database_id = books_database_id
        self._client = Client(auth=token)
        self._rate_limiter = rate_limiter or NotionRateLimiter()

    def upload_cards(self, cards: List[ZettelkastenCard], book_title: str) -> int:
        if not cards:
            return 0

        books_page_id = self._find_book_page(book_title)
        if self._books_database_id and books_page_id is None:
            logger.warning(
                f"Books DB 找不到 '{book_title}'，卡片會建立但不會連結「來源」"
            )

        if books_page_id and self._has_existing_cards(books_page_id):
            logger.info(f"卡片盒已有 '{book_title}' 的卡片，略過上傳")
            return 0

        success_count = 0
        for i, card in enumerate(cards, 1):
            try:
                properties = self._build_properties(card, books_page_id)
                children = self._build_children(card)
                retry_with_backoff(
                    lambda p=properties, c=children: self._client.pages.create(
                        parent={"database_id": self._database_id},
                        properties=p,
                        children=c,
                    ),
                    self._rate_limiter,
                )
                success_count += 1
                logger.info(f"建立卡片 {i}/{len(cards)}: {card.title}")
            except Exception as e:
                logger.error(f"卡片 '{card.title}' 建立失敗: {e}")

        logger.info(f"卡片盒同步完成: {success_count}/{len(cards)}")
        return success_count

    # ----- Internals -----

    def _find_book_page(self, book_title: str) -> Optional[str]:
        if not self._books_database_id:
            return None

        clean = book_title.split(":", 1)[0].strip() if ":" in book_title else book_title.strip()
        if not clean:
            return None

        for filter_body in (
            {"property": "Name", "title": {"equals": clean}},
            {"property": "Name", "title": {"contains": clean}},
        ):
            try:
                result = retry_with_backoff(
                    lambda f=filter_body: self._client.databases.query(
                        database_id=self._books_database_id,
                        filter=f,
                        page_size=1,
                    ),
                    self._rate_limiter,
                )
                results = (result or {}).get("results") or []
                if results:
                    return results[0].get("id")
            except Exception as e:
                logger.warning(f"Books DB 查詢 '{clean}' 失敗: {e}")
                return None
        return None

    def _has_existing_cards(self, books_page_id: str) -> bool:
        try:
            result = retry_with_backoff(
                lambda: self._client.databases.query(
                    database_id=self._database_id,
                    filter={
                        "property": "來源",
                        "relation": {"contains": books_page_id},
                    },
                    page_size=1,
                ),
                self._rate_limiter,
            )
            return bool((result or {}).get("results"))
        except Exception as e:
            logger.warning(f"卡片盒去重查詢失敗 ({books_page_id}): {e}")
            return False

    def _build_properties(self, card: ZettelkastenCard,
                          books_page_id: Optional[str]) -> dict:
        props: dict = {
            "標題": {"title": [{"text": {"content": card.title[:_RICH_TEXT_LIMIT]}}]},
        }
        if books_page_id:
            props["來源"] = {"relation": [{"id": books_page_id}]}
        return props

    def _build_children(self, card: ZettelkastenCard) -> List[dict]:
        blocks: List[dict] = []

        if card.content:
            blocks.append(_paragraph(card.content[:_RICH_TEXT_LIMIT]))

        if card.source_highlight:
            blocks.append({
                "object": "block",
                "type": "quote",
                "quote": {
                    "rich_text": [{"type": "text", "text": {
                        "content": card.source_highlight[:_RICH_TEXT_LIMIT]
                    }}],
                },
            })

        if card.chapter_reference:
            progress = (
                f"（進度 {card.chapter_progress:.0%}）"
                if card.chapter_progress else ""
            )
            blocks.append({
                "object": "block",
                "type": "callout",
                "callout": {
                    "icon": {"type": "emoji", "emoji": "📖"},
                    "rich_text": [{"type": "text", "text": {
                        "content": f"{card.chapter_reference}{progress}"
                    }}],
                },
            })

        return blocks


def _paragraph(text: str) -> dict:
    return {
        "object": "block",
        "type": "paragraph",
        "paragraph": {
            "rich_text": [{"type": "text", "text": {"content": text}}],
        },
    }
