"""Notion repository for Zettelkasten cards.

Schema expected (matches 🗃️ 卡片盒重點收集):
  - 標題 (title)
  - 來源 (relation → Books DB / Personal Reading List)
Card content / source highlight / chapter reference go into the page body
as blocks, since the target DB has no matching properties for them.
"""
import hashlib
import logging
from typing import List, Optional, Set, Tuple

from notion_client import Client

from .rate_limiter import NotionRateLimiter
from .retry_policy import retry_with_backoff

# zettelkasten_generator lives at project root (not yet ported into src/)
from zettelkasten_generator import ZettelkastenCard

logger = logging.getLogger(__name__)

_RICH_TEXT_LIMIT = 2000
# rich_text property on the 卡片盒 DB that records which source highlight a card
# came from, so we can dedup at highlight granularity (not whole-book).
_SOURCE_ID_PROPERTY = "來源劃線ID"


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

        done_ids, existing_count = self._existing_source_ids(books_page_id)
        # 已有卡片、但沒有任何來源劃線ID → 卡片盒尚未加該屬性，退回「整本略過」
        # 以免每次重跑都重複建立卡片。
        if existing_count > 0 and not done_ids:
            logger.info(
                f"卡片盒已有 '{book_title}' 的卡片但無「{_SOURCE_ID_PROPERTY}」屬性，"
                f"沿用整本略過（在卡片盒新增此 rich_text 屬性即可支援增量補卡）"
            )
            return 0

        pending = self._filter_new_cards(cards, done_ids)
        skipped = len(cards) - len(pending)
        if skipped:
            logger.info(f"'{book_title}' 已有 {skipped} 張卡片，僅需上傳 {len(pending)} 張新卡")
        if not pending:
            logger.info(f"'{book_title}' 無新卡片需要上傳")
            return 0

        success_count = 0
        for i, card in enumerate(pending, 1):
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
                logger.info(f"建立卡片 {i}/{len(pending)}: {card.title}")
            except Exception as e:
                logger.error(f"卡片 '{card.title}' 建立失敗: {e}")

        logger.info(f"卡片盒同步完成: {success_count}/{len(pending)}")
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

    def _existing_source_ids(
        self, books_page_id: Optional[str]
    ) -> Tuple[Set[str], int]:
        """Collect the source-highlight IDs already recorded for this book.

        Returns (set_of_source_ids, total_existing_cards). Paginates through all
        cards whose 來源 relation points at this book so a partially-failed prior
        run can be resumed rather than skipped wholesale.
        """
        if not books_page_id:
            return set(), 0

        ids: Set[str] = set()
        total = 0
        cursor: Optional[str] = None
        try:
            while True:
                kwargs = {
                    "database_id": self._database_id,
                    "filter": {
                        "property": "來源",
                        "relation": {"contains": books_page_id},
                    },
                    "page_size": 100,
                }
                if cursor:
                    kwargs["start_cursor"] = cursor
                result = retry_with_backoff(
                    lambda k=kwargs: self._client.databases.query(**k),
                    self._rate_limiter,
                ) or {}
                for page in result.get("results", []):
                    total += 1
                    sid = self._read_source_id_property(page)
                    if sid:
                        ids.add(sid)
                if not result.get("has_more"):
                    break
                cursor = result.get("next_cursor")
        except Exception as e:
            logger.warning(f"卡片盒去重查詢失敗 ({books_page_id}): {e}")
            return set(), 0
        return ids, total

    @staticmethod
    def _read_source_id_property(page: dict) -> str:
        props = (page or {}).get("properties", {})
        prop = props.get(_SOURCE_ID_PROPERTY) or {}
        rich = prop.get("rich_text") or []
        if rich:
            first = rich[0] or {}
            return (first.get("plain_text")
                    or (first.get("text") or {}).get("content")
                    or "").strip()
        return ""

    @staticmethod
    def _card_source_id(card: ZettelkastenCard) -> str:
        """Stable id for the source highlight a card came from.

        Prefers the Kobo BookmarkID; falls back to a hash of the highlight text
        so cards still dedup even when no BookmarkID is available.
        """
        bookmark_id = getattr(card, "source_bookmark_id", "") or ""
        if bookmark_id.strip():
            return bookmark_id.strip()
        basis = (card.source_highlight or card.title or "").encode("utf-8")
        return "sha1:" + hashlib.sha1(basis).hexdigest()[:12]

    @classmethod
    def _filter_new_cards(
        cls, cards: List[ZettelkastenCard], done_ids: Set[str]
    ) -> List[ZettelkastenCard]:
        """Cards whose source highlight has no card yet (also dedups within batch)."""
        seen = set(done_ids)
        pending: List[ZettelkastenCard] = []
        for card in cards:
            sid = cls._card_source_id(card)
            if sid in seen:
                continue
            seen.add(sid)
            pending.append(card)
        return pending

    def _build_properties(self, card: ZettelkastenCard,
                          books_page_id: Optional[str]) -> dict:
        props: dict = {
            "標題": {"title": [{"text": {"content": card.title[:_RICH_TEXT_LIMIT]}}]},
            _SOURCE_ID_PROPERTY: {
                "rich_text": [{"text": {"content": self._card_source_id(card)}}]
            },
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
