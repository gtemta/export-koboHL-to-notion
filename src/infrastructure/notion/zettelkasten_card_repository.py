"""Notion repository for Zettelkasten cards.

Schema (卡片盒): 標題 (title) is mandatory. The repository auto-creates the
optional columns below on first upload (see _ensure_schema) and only writes a
property if the DB has it (see _wants):
  - 來源 (relation → Books DB / Personal Reading List)
  - Key Word (rich_text)   — free concept tags, joined by 、
  - Tags (multi_select)    — fixed-category classification
  - 來源劃線ID (rich_text)  — source-highlight id, enables per-highlight dedup
  - 加工狀態 (select)      — revisit stage, seeded 🌱未加工 on every new card
  - 建立日期 (created_time) — set by Notion itself, so existing cards get a
                             value with no backfill needed
  - 上次回顧 (date)         — manual, not written on create; user fills it in
Every card also gets a page `cover` (Notion built-in gradient, keyed off the
card's first category — see card_visuals.cover_url_for) and, when the card has
one, an `icon` (single emoji from zettelkasten_generator's palette).
Card content / source highlight / chapter reference go into the page body
as blocks.

Review scores are deliberately NOT written to Notion. The review gate
(`CardReviewer`) decides whether a card gets here at all; every card in the DB
has already passed, so a score column would be noise. The scores live in
`cards_output/*.json` and the run log.
"""
import hashlib
import logging
import re
from typing import List, Optional, Set, Tuple

from notion_client import Client

# zettelkasten_generator lives at project root (not yet ported into src/)
from zettelkasten_generator import ZettelkastenCard

from ...domain.entities.book_card import BookCard
from .card_visuals import cover_url_for
from .rate_limiter import NotionRateLimiter
from .reading_list_repository import ReadingListRepository
from .retry_policy import retry_with_backoff

logger = logging.getLogger(__name__)

_RICH_TEXT_LIMIT = 2000
# rich_text property on the 卡片盒 DB that records which source highlight a card
# came from, so we can dedup at highlight granularity (not whole-book).
_SOURCE_ID_PROPERTY = "來源劃線ID"
# rich_text holding free concept tags (、-joined); multi_select for fixed categories.
_KEYWORD_PROPERTY = "Key Word"
_TAGS_PROPERTY = "Tags"

# 回訪機制用的欄位。加工狀態刻意不叫「狀態」——審核年代那個已退役的 `狀態` 欄
# 語意完全不同（見 docs/NOTION_OUTPUT_IMPROVEMENTS.md），同名會混淆。
_STAGE_PROPERTY = "加工狀態"
_STAGE_UNPROCESSED = "🌱未加工"
_STAGE_REWRITTEN = "🌿已重寫"
_STAGE_PERMANENT = "🌳永久筆記"
# 建立日期用 Notion 的 created_time 型別：值由 Notion 自己算，舊卡也立即有值。
_CREATED_PROPERTY = "建立日期"
_REVIEWED_PROPERTY = "上次回顧"

# sentinel: schema not yet fetched (distinct from "fetched, empty/unreadable").
_UNSET = object()


class ZettelkastenCardRepository:
    """Uploads Zettelkasten cards to the Notion 卡片盒 database.

    The `來源` relation targets the Books DB (Personal Reading List), not the
    Kobo highlights DB. Resolving it (reverse lookup → title match →
    auto-create) is delegated to ReadingListRepository; only if that fails too
    is the card left unlinked.
    """

    def __init__(
        self,
        token: str,
        database_id: str,
        books_database_id: Optional[str] = None,
        rate_limiter: Optional[NotionRateLimiter] = None,
        tag_categories: Optional[List[str]] = None,
        reading_list: Optional[ReadingListRepository] = None,
    ):
        self._database_id = database_id
        self._books_database_id = books_database_id
        self._client = Client(auth=token)
        self._rate_limiter = rate_limiter or NotionRateLimiter()
        # fixed Tags classification list (DI from settings); [] → don't seed/filter
        self._tag_categories = list(tag_categories or [])
        # cached card-DB property names; _UNSET until first fetched, None if unreadable
        self._schema_props = _UNSET
        # E1 auto-create-columns runs once per process
        self._schema_ensured = False
        # Books DB（Personal Reading List）的查找／自動建頁交給 ReadingListRepository；
        # 沒注入時自建一個，共用本 repo 的 client 與限速器。
        if reading_list is None and books_database_id:
            reading_list = ReadingListRepository(
                token=token,
                database_id=books_database_id,
                rate_limiter=self._rate_limiter,
                client=self._client,
            )
        self._reading_list = reading_list

    def upload_cards(
        self,
        cards: List[ZettelkastenCard],
        book_title: str,
        source_page_id: Optional[str] = None,
        percent_read: Optional[float] = None,
    ) -> int:
        if not cards:
            return 0

        self._ensure_schema()

        books_page_id = self._find_book_page(book_title, source_page_id, percent_read)
        if self._books_database_id and books_page_id is None:
            logger.warning(
                f"Books DB 找不到也建不了 '{book_title}'，卡片會建立但不會連結「來源」"
            )

        if books_page_id:
            done_ids, existing_count = self._existing_source_ids(books_page_id)
            # 已有卡片、但沒有任何來源劃線ID → 卡片盒尚未加該屬性，退回「整本略過」
            # 以免每次重跑都重複建立卡片。（E1 自動建欄後，此路徑僅在 schema 讀取失敗時觸發。）
            if existing_count > 0 and not done_ids:
                logger.info(
                    f"卡片盒已有 '{book_title}' 的卡片但無「{_SOURCE_ID_PROPERTY}」屬性，"
                    f"沿用整本略過（在卡片盒新增此 rich_text 屬性即可支援增量補卡）"
                )
                return 0
            pending = self._filter_new_cards(cards, done_ids)
        else:
            # E5: 無「來源」relation 可用 → 逐卡以「來源劃線ID」查重（單書 ≤ 16 張，成本可接受）
            pending = self._filter_new_cards_by_query(cards)

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
                visuals = self._build_visuals(card)
                retry_with_backoff(
                    lambda p=properties, c=children, v=visuals: (
                        self._client.pages.create(
                            parent={"database_id": self._database_id},
                            properties=p,
                            children=c,
                            **v,
                        )
                    ),
                    self._rate_limiter,
                )
                success_count += 1
                logger.info(f"建立卡片 {i}/{len(pending)}: {card.title}")
            except Exception as e:
                logger.error(f"卡片 '{card.title}' 建立失敗: {e}")

        logger.info(f"卡片盒同步完成: {success_count}/{len(pending)}")
        return success_count

    def resolve_book_page(
        self,
        book_title: str,
        source_page_id: Optional[str] = None,
        percent_read: Optional[float] = None,
    ) -> Optional[str]:
        """Public entry for backfill tooling: Books-DB page id for a title,
        auto-creating the page when the book isn't listed yet."""
        return self._find_book_page(book_title, source_page_id, percent_read)

    def ensure_schema(self) -> None:
        """Public entry for backfill tooling: create the optional 卡片盒
        columns (加工狀態/建立日期/上次回顧/來源劃線ID) and seed Tags options
        if missing. Idempotent — safe to call even if a sync already has.

        Writes to the database schema, so callers must not invoke this from a
        read-only / dry-run path (see has_property for the read-only check).
        """
        self._ensure_schema()

    def has_property(self, prop_name: str) -> bool:
        """Public entry for backfill tooling: whether the 卡片盒 DB currently
        has a given property. Read-only (only triggers a schema fetch, never
        a write) — safe to call from a dry-run path.

        Mirrors _wants's fallback: True also when the schema couldn't be
        read, so callers don't second-guess a property that might exist.
        """
        return self._wants(prop_name)

    def list_book_cards(self, books_page_id: str) -> List[BookCard]:
        """Cards whose 來源 relation points at a Books-DB page (properties only).

        Read-only; used by Reading List page completion to derive 書籍種類.
        """
        cards: List[BookCard] = []
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
                cards.extend(self._to_book_card(p) for p in result.get("results", []))
                if not result.get("has_more"):
                    break
                cursor = result.get("next_cursor")
        except Exception as e:
            logger.warning(f"讀取書頁 {books_page_id} 的卡片失敗: {e}")
            return []
        return cards

    @staticmethod
    def _to_book_card(page: dict) -> BookCard:
        props = (page or {}).get("properties") or {}

        def _plain(prop_name: str, kind: str) -> str:
            parts = (props.get(prop_name) or {}).get(kind) or []
            return "".join(p.get("plain_text", "") for p in parts).strip()

        tags = [
            o.get("name", "")
            for o in (props.get(_TAGS_PROPERTY) or {}).get("multi_select") or []
            if o.get("name")
        ]
        keywords = [
            k.strip() for k in re.split(r"[、・]", _plain(_KEYWORD_PROPERTY, "rich_text"))
            if k.strip()
        ]
        return BookCard(
            page_id=page.get("id", ""),
            title=_plain("標題", "title"),
            tags=tags,
            keywords=keywords,
        )

    # ----- Internals -----

    def _ensure_schema(self) -> None:
        """E1: create the optional 卡片盒 columns / seed Tags options if missing.

        Runs once per process. If the schema can't be read we leave the DB as-is
        (write-all fallback in _wants stays in effect).
        """
        if self._schema_ensured:
            return
        self._schema_ensured = True

        try:
            db = retry_with_backoff(
                lambda: self._client.databases.retrieve(self._database_id),
                self._rate_limiter,
            ) or {}
        except Exception as e:
            logger.warning(f"讀取卡片盒 schema 失敗，跳過自動建欄: {e}")
            return

        existing = db.get("properties") or {}
        # prime the _wants() cache with the freshly-read names
        self._schema_props = set(existing.keys())

        to_add: dict = {}
        if _SOURCE_ID_PROPERTY not in existing:
            to_add[_SOURCE_ID_PROPERTY] = {"rich_text": {}}

        tags_update = self._tags_options_update(existing.get(_TAGS_PROPERTY))
        if tags_update is not None:
            to_add[_TAGS_PROPERTY] = tags_update

        to_add.update(self._schema_additions(existing))

        if not to_add:
            return
        try:
            retry_with_backoff(
                lambda: self._client.databases.update(
                    database_id=self._database_id, properties=to_add
                ),
                self._rate_limiter,
            )
            logger.info(f"卡片盒補上缺失欄位/選項: {list(to_add.keys())}")
            # refresh cache so _wants() sees the new columns within this run
            self._schema_props = self._fetch_property_names()
        except Exception as e:
            logger.warning(f"卡片盒 schema 自動建欄失敗: {e}")

    def _tags_options_update(self, tags_prop: Optional[dict]) -> Optional[dict]:
        """E3: multi_select update body that adds missing category options to Tags.

        Returns None when nothing needs adding (or Tags is absent / not a
        multi_select). Existing options are preserved (Notion merges by name).
        """
        if not self._tag_categories:
            return None
        if not tags_prop or tags_prop.get("type") != "multi_select":
            return None
        current = {
            o.get("name")
            for o in (tags_prop.get("multi_select") or {}).get("options", [])
        }
        missing = [c for c in self._tag_categories if c not in current]
        if not missing:
            return None
        merged = [{"name": n} for n in current if n] + [{"name": c} for c in missing]
        return {"multi_select": {"options": merged}}

    @staticmethod
    def _schema_additions(existing: dict) -> dict:
        """回訪欄位中，卡片盒還缺的那些的 databases.update body（純函式）。"""
        to_add: dict = {}
        if _STAGE_PROPERTY not in (existing or {}):
            to_add[_STAGE_PROPERTY] = {
                "select": {
                    "options": [
                        {"name": _STAGE_UNPROCESSED},
                        {"name": _STAGE_REWRITTEN},
                        {"name": _STAGE_PERMANENT},
                    ]
                }
            }
        if _CREATED_PROPERTY not in (existing or {}):
            to_add[_CREATED_PROPERTY] = {"created_time": {}}
        if _REVIEWED_PROPERTY not in (existing or {}):
            to_add[_REVIEWED_PROPERTY] = {"date": {}}
        return to_add

    @staticmethod
    def _build_visuals(card: ZettelkastenCard) -> dict:
        """pages.create 的 icon / cover kwargs。

        cover 永遠有值（無分類也有預設色）；icon 為空時整個 key 不送 ——
        Notion 收到 icon=None 會拒收整張卡。
        """
        visuals: dict = {
            "cover": {
                "type": "external",
                "external": {
                    "url": cover_url_for(getattr(card, "categories", None))
                },
            }
        }
        icon = (getattr(card, "icon", "") or "").strip()
        if icon:
            visuals["icon"] = {"type": "emoji", "emoji": icon}
        return visuals

    def _find_book_page(
        self,
        book_title: str,
        source_page_id: Optional[str] = None,
        percent_read: Optional[float] = None,
    ) -> Optional[str]:
        """E4: Books-DB page for a card's 來源 relation — reverse lookup → title
        match → auto-create, implemented in ReadingListRepository."""
        if self._reading_list is None:
            return None
        return self._reading_list.resolve_or_create(
            book_title, source_page_id, percent_read
        )

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

    def _filter_new_cards_by_query(
        self, cards: List[ZettelkastenCard]
    ) -> List[ZettelkastenCard]:
        """E5: dedup when no 來源 relation — query each source id against the DB.

        Falls back to within-batch dedup only if the DB has no 來源劃線ID column
        (then we can't check prior runs and just avoid re-creating within a batch).
        """
        if not self._wants(_SOURCE_ID_PROPERTY):
            return self._filter_new_cards(cards, set())

        seen: Set[str] = set()
        pending: List[ZettelkastenCard] = []
        for card in cards:
            sid = self._card_source_id(card)
            if sid in seen:
                continue
            seen.add(sid)
            if self._source_id_exists(sid):
                continue
            pending.append(card)
        return pending

    def _source_id_exists(self, sid: str) -> bool:
        try:
            result = retry_with_backoff(
                lambda: self._client.databases.query(
                    database_id=self._database_id,
                    filter={
                        "property": _SOURCE_ID_PROPERTY,
                        "rich_text": {"equals": sid},
                    },
                    page_size=1,
                ),
                self._rate_limiter,
            ) or {}
            return bool(result.get("results"))
        except Exception as e:
            # on error, don't block the upload (better a possible dup than a miss)
            logger.warning(f"來源劃線ID 去重查詢失敗 ({sid}): {e}")
            return False

    def _build_properties(self, card: ZettelkastenCard,
                          books_page_id: Optional[str]) -> dict:
        # 標題 (title) is mandatory; everything else is optional and only written
        # if the DB actually has that property (see _wants), so a card box that
        # hasn't added the new columns yet still uploads instead of erroring.
        props: dict = {
            "標題": {"title": [{"text": {"content": card.title[:_RICH_TEXT_LIMIT]}}]},
        }
        if self._wants(_SOURCE_ID_PROPERTY):
            props[_SOURCE_ID_PROPERTY] = {
                "rich_text": [{"text": {"content": self._card_source_id(card)}}]
            }
        # E2: free concept tags → Key Word rich_text, joined by 、
        keyword = "、".join(t for t in (getattr(card, "tags", None) or []) if t)
        if keyword and self._wants(_KEYWORD_PROPERTY):
            props[_KEYWORD_PROPERTY] = {
                "rich_text": [{"text": {"content": keyword[:_RICH_TEXT_LIMIT]}}]
            }
        # E3: fixed-category classification → Tags multi_select
        categories = self._allowed_categories(card)
        if categories and self._wants(_TAGS_PROPERTY):
            props[_TAGS_PROPERTY] = {
                "multi_select": [{"name": c} for c in categories]
            }
        if self._wants(_STAGE_PROPERTY):
            props[_STAGE_PROPERTY] = {"select": {"name": _STAGE_UNPROCESSED}}
        if books_page_id and self._wants("來源"):
            props["來源"] = {"relation": [{"id": books_page_id}]}
        return props

    def _wants(self, prop_name: str) -> bool:
        """Whether to write a property: yes if the DB has it, or if the schema
        couldn't be read (then we don't second-guess and write as before)."""
        known = self._known_properties()
        return known is None or prop_name in known

    def _known_properties(self) -> Optional[Set[str]]:
        if self._schema_props is _UNSET:
            self._schema_props = self._fetch_property_names()
        return self._schema_props

    def _fetch_property_names(self) -> Optional[Set[str]]:
        try:
            db = retry_with_backoff(
                lambda: self._client.databases.retrieve(self._database_id),
                self._rate_limiter,
            ) or {}
            return set((db.get("properties") or {}).keys())
        except Exception as e:
            logger.warning(f"讀取卡片盒 schema 失敗，將照舊寫入全部屬性: {e}")
            return None

    def _allowed_categories(self, card: ZettelkastenCard) -> List[str]:
        """Card categories to write to Tags, filtered to the allowed list.

        When the repo has a configured category list, values outside it are
        dropped (Notion multi_select stays clean); when it has none, categories
        pass through de-duped. Commas are stripped (forbidden in option names).
        """
        allowed = set(self._tag_categories) if self._tag_categories else None
        out: List[str] = []
        seen: Set[str] = set()
        for cat in getattr(card, "categories", None) or []:
            name = (cat or "").replace(",", "").replace("，", "").strip()[:100]
            if not name or name in seen:
                continue
            if allowed is not None and name not in allowed:
                continue
            seen.add(name)
            out.append(name)
        return out

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

        # 章名可能被 _clean_chapter_reference 清成空字串（誤判成章名的劃線內文），
        # 但進度是 Kobo 硬數據、永遠可信，不該一起消失。
        if card.chapter_reference or card.chapter_progress:
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
