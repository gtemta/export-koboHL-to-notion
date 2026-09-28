"""Notion repository for 📚 Personal Reading List (the Books DB).

Everything that touches the Books DB lives here: resolving a book's page for
the card「來源」relation — reverse lookup via the `Kobo EReader` relation →
title match → auto-create — moved unchanged from ZettelkastenCardRepository,
which now delegates to this class.
"""
import logging
from typing import List, Optional

from notion_client import Client

from .rate_limiter import NotionRateLimiter
from .retry_policy import retry_with_backoff

logger = logging.getLogger(__name__)

_RICH_TEXT_LIMIT = 2000
# Books DB title property + the relation on it that points back at the Kobo DB.
_BOOKS_TITLE_PROPERTY = "Name"
_KOBO_RELATION_PROPERTY = "Kobo EReader"
# Books DB reading status (select). Option names must match the DB exactly —
# note the space in "📖 閱讀中".
_BOOKS_STATUS_PROPERTY = "Status"
_BOOK_STATUS_DONE = "🔖閱讀完畢"
_BOOK_STATUS_READING = "📖 閱讀中"
# Kobo ___PercentRead is 0-100; at/above this the book counts as finished.
_BOOK_DONE_PERCENT = 99

# sentinel: not yet fetched (distinct from "fetched, empty/unreadable").
_UNSET = object()


class ReadingListRepository:
    """Books-DB (Personal Reading List) access.

    `client` is injectable so ZettelkastenCardRepository can share its client
    and rate limiter, and so tests can pass a fake.
    """

    def __init__(
        self,
        token: str,
        database_id: Optional[str],
        rate_limiter: Optional[NotionRateLimiter] = None,
        client: Optional[Client] = None,
    ):
        self._books_database_id = database_id
        self._client = client or Client(auth=token)
        self._rate_limiter = rate_limiter or NotionRateLimiter()
        # full Books-DB page list, fetched once for name-based matching
        self._books_pages_cache = _UNSET
        # Books-DB property names; _UNSET until fetched, None if unreadable
        self._books_schema_props = _UNSET

    def resolve_or_create(
        self,
        book_title: str,
        source_page_id: Optional[str] = None,
        percent_read: Optional[float] = None,
    ) -> Optional[str]:
        """Books-DB page id for a book, auto-creating the page when unlisted."""
        return self._find_book_page(book_title, source_page_id, percent_read)

    # ----- Internals (moved unchanged from ZettelkastenCardRepository) -----

    def _find_book_page(
        self,
        book_title: str,
        source_page_id: Optional[str] = None,
        percent_read: Optional[float] = None,
    ) -> Optional[str]:
        """E4: resolve the Books-DB page for a card's 來源 relation.

        1. reverse lookup: Books page whose `Kobo EReader` relation points at the
           source highlight page (exact, no title ambiguity);
        2. strengthened title match (equals → contains → normalized two-way
           containment over the whole Books DB) — a match with an empty
           `Kobo EReader` relation gets it backfilled so次回反查直接命中;
        3. auto-create the Books-DB page when nothing matches.
        """
        if not self._books_database_id:
            return None

        if source_page_id:
            pid = self._reverse_lookup_book(source_page_id)
            if pid:
                return pid

        page = self._match_book_by_name(book_title)
        if page is not None:
            if source_page_id:
                self._backfill_kobo_relation(page, source_page_id)
            return page.get("id")

        return self._create_book_page(book_title, source_page_id, percent_read)

    def _reverse_lookup_book(self, source_page_id: str) -> Optional[str]:
        try:
            result = retry_with_backoff(
                lambda: self._client.databases.query(
                    database_id=self._books_database_id,
                    filter={
                        "property": _KOBO_RELATION_PROPERTY,
                        "relation": {"contains": source_page_id},
                    },
                    page_size=1,
                ),
                self._rate_limiter,
            ) or {}
            results = result.get("results") or []
            if results:
                return results[0].get("id")
        except Exception as e:
            logger.warning(f"Books DB 反查（{_KOBO_RELATION_PROPERTY}）失敗: {e}")
        return None

    def _match_book_by_name(self, book_title: str) -> Optional[dict]:
        """Books-DB page (full dict) whose Name matches the book title."""
        main = self._main_title(book_title)
        if not main:
            return None

        for filter_body in (
            {"property": _BOOKS_TITLE_PROPERTY, "title": {"equals": main}},
            {"property": _BOOKS_TITLE_PROPERTY, "title": {"contains": main}},
        ):
            try:
                result = retry_with_backoff(
                    lambda f=filter_body: self._client.databases.query(
                        database_id=self._books_database_id,
                        filter=f,
                        page_size=1,
                    ),
                    self._rate_limiter,
                ) or {}
                results = result.get("results") or []
                if results:
                    return results[0]
            except Exception as e:
                logger.warning(f"Books DB 查詢 '{main}' 失敗: {e}")
                break

        # normalized two-way containment over all Books pages (cached per run)
        main_norm = self._normalize(main)
        for page in self._all_books_pages():
            name_norm = self._normalize(self._page_name(page))
            if name_norm and (name_norm in main_norm or main_norm in name_norm):
                return page
        return None

    def _backfill_kobo_relation(self, page: dict, source_page_id: str) -> None:
        """Fill an empty `Kobo EReader` relation on a name-matched Books page.

        Makes the next run's reverse lookup hit exactly. No-op when the page
        lacks the property or already has a relation.
        """
        prop = (page.get("properties") or {}).get(_KOBO_RELATION_PROPERTY) or {}
        if prop.get("type") != "relation" or prop.get("relation"):
            return
        try:
            retry_with_backoff(
                lambda: self._client.pages.update(
                    page_id=page["id"],
                    properties={
                        _KOBO_RELATION_PROPERTY: {
                            "relation": [{"id": source_page_id}]
                        }
                    },
                ),
                self._rate_limiter,
            )
            logger.info(
                f"Books DB '{self._page_name(page)}' 補上 {_KOBO_RELATION_PROPERTY} relation"
            )
        except Exception as e:
            logger.warning(f"Books DB 補 {_KOBO_RELATION_PROPERTY} relation 失敗: {e}")

    def _create_book_page(
        self,
        book_title: str,
        source_page_id: Optional[str],
        percent_read: Optional[float],
    ) -> Optional[str]:
        """Auto-create the Personal Reading List page for an unlisted book.

        Name = full book title (list entries keep their subtitles), Kobo
        EReader relation → the highlights page, Status derived from reading
        progress. Properties missing from the Books DB schema are skipped.
        """
        if not self._books_database_id:
            return None

        props: dict = {
            _BOOKS_TITLE_PROPERTY: {
                "title": [{"text": {"content": book_title[:_RICH_TEXT_LIMIT]}}]
            },
        }
        if source_page_id and self._books_wants(_KOBO_RELATION_PROPERTY):
            props[_KOBO_RELATION_PROPERTY] = {"relation": [{"id": source_page_id}]}
        if self._books_wants(_BOOKS_STATUS_PROPERTY):
            props[_BOOKS_STATUS_PROPERTY] = {
                "select": {"name": self._book_status_name(percent_read)}
            }

        try:
            page = retry_with_backoff(
                lambda: self._client.pages.create(
                    parent={"database_id": self._books_database_id},
                    properties=props,
                ),
                self._rate_limiter,
            ) or {}
            logger.info(f"Reading List 自動建頁: '{book_title}'")
            return page.get("id")
        except Exception as e:
            logger.warning(f"Reading List 自動建頁失敗 '{book_title}': {e}")
            return None

    @staticmethod
    def _book_status_name(percent_read: Optional[float]) -> str:
        """Reading-status option from Kobo progress (0-100 scale)."""
        return (
            _BOOK_STATUS_DONE
            if (percent_read or 0) >= _BOOK_DONE_PERCENT
            else _BOOK_STATUS_READING
        )

    def _books_wants(self, prop_name: str) -> bool:
        """Whether the Books DB has a property; True too when its schema
        couldn't be read (then we write as-is and let Notion validate)."""
        if self._books_schema_props is _UNSET:
            try:
                db = retry_with_backoff(
                    lambda: self._client.databases.retrieve(self._books_database_id),
                    self._rate_limiter,
                ) or {}
                self._books_schema_props = set((db.get("properties") or {}).keys())
            except Exception as e:
                logger.warning(f"讀取 Books DB schema 失敗: {e}")
                self._books_schema_props = None
        return self._books_schema_props is None or prop_name in self._books_schema_props

    def _all_books_pages(self) -> List[dict]:
        if self._books_pages_cache is not _UNSET:
            return self._books_pages_cache

        pages: List[dict] = []
        cursor: Optional[str] = None
        try:
            while True:
                kwargs = {"database_id": self._books_database_id, "page_size": 100}
                if cursor:
                    kwargs["start_cursor"] = cursor
                result = retry_with_backoff(
                    lambda k=kwargs: self._client.databases.query(**k),
                    self._rate_limiter,
                ) or {}
                pages.extend(result.get("results", []))
                if not result.get("has_more"):
                    break
                cursor = result.get("next_cursor")
        except Exception as e:
            logger.warning(f"Books DB 全頁抓取失敗: {e}")
        self._books_pages_cache = pages
        return pages

    @staticmethod
    def _page_name(page: dict) -> str:
        prop = (page.get("properties") or {}).get(_BOOKS_TITLE_PROPERTY) or {}
        parts = prop.get("title") or []
        return "".join(p.get("plain_text", "") for p in parts).strip()

    @classmethod
    def _main_title(cls, title: str) -> str:
        """Main title only: split on 半形 ':' or 全形 '：', then normalize."""
        t = (title or "").replace("：", ":")
        t = t.split(":", 1)[0]
        return cls._normalize(t)

    @staticmethod
    def _normalize(s: str) -> str:
        """全形空白→半形、收斂空白、去頭尾。"""
        return " ".join((s or "").replace("　", " ").split()).strip()
