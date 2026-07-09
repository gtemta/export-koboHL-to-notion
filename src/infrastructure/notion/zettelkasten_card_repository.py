"""Notion repository for Zettelkasten cards.

Schema (卡片盒): 標題 (title) is mandatory. The repository auto-creates the
optional columns below on first upload (see _ensure_schema) and only writes a
property if the DB has it (see _wants):
  - 來源 (relation → Books DB / Personal Reading List)
  - Key Word (rich_text)   — free concept tags, joined by 、
  - Tags (multi_select)    — fixed-category classification
  - 來源劃線ID (rich_text)  — source-highlight id, enables per-highlight dedup
  - 品質分數 (number)       — reviewer quality score (1-10)
  - 狀態 (select)           — 草稿 / 已審 / 永久筆記
Card content / source highlight / chapter reference go into the page body
as blocks.
"""
import hashlib
import logging
from typing import List, Optional, Set, Tuple

from notion_client import Client

# zettelkasten_generator lives at project root (not yet ported into src/)
from zettelkasten_generator import ZettelkastenCard

from .rate_limiter import NotionRateLimiter
from .retry_policy import retry_with_backoff

logger = logging.getLogger(__name__)

_RICH_TEXT_LIMIT = 2000
# rich_text property on the 卡片盒 DB that records which source highlight a card
# came from, so we can dedup at highlight granularity (not whole-book).
_SOURCE_ID_PROPERTY = "來源劃線ID"
# rich_text holding free concept tags (、-joined); multi_select for fixed categories.
_KEYWORD_PROPERTY = "Key Word"
_TAGS_PROPERTY = "Tags"
# number property: reviewer quality score (1-10); select: card processing stage.
_QUALITY_PROPERTY = "品質分數"
_STATUS_PROPERTY = "狀態"
_STATUS_DRAFT = "草稿"
_STATUS_REVIEWED = "已審"
_STATUS_PERMANENT = "永久筆記"  # human-only decision, never set automatically
# score at/above which a card counts as reviewed rather than a rough draft.
_REVIEWED_SCORE = 7
# Books DB title property + the relation on it that points back at the Kobo DB.
_BOOKS_TITLE_PROPERTY = "Name"
_KOBO_RELATION_PROPERTY = "Kobo EReader"

# sentinel: schema not yet fetched (distinct from "fetched, empty/unreadable").
_UNSET = object()


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
        tag_categories: Optional[List[str]] = None,
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
        # E4 full Books-DB page list, fetched once for name-based matching
        self._books_pages_cache = _UNSET

    def upload_cards(
        self,
        cards: List[ZettelkastenCard],
        book_title: str,
        source_page_id: Optional[str] = None,
    ) -> int:
        if not cards:
            return 0

        self._ensure_schema()

        books_page_id = self._find_book_page(book_title, source_page_id)
        if self._books_database_id and books_page_id is None:
            logger.warning(
                f"Books DB 找不到 '{book_title}'，卡片會建立但不會連結「來源」"
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
        if _QUALITY_PROPERTY not in existing:
            to_add[_QUALITY_PROPERTY] = {"number": {}}
        if _STATUS_PROPERTY not in existing:
            to_add[_STATUS_PROPERTY] = {"select": {"options": [
                {"name": _STATUS_DRAFT},
                {"name": _STATUS_REVIEWED},
                {"name": _STATUS_PERMANENT},
            ]}}

        tags_update = self._tags_options_update(existing.get(_TAGS_PROPERTY))
        if tags_update is not None:
            to_add[_TAGS_PROPERTY] = tags_update

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

    def _find_book_page(
        self, book_title: str, source_page_id: Optional[str] = None
    ) -> Optional[str]:
        """E4: resolve the Books-DB page for a card's 來源 relation.

        1. reverse lookup: Books page whose `Kobo EReader` relation points at the
           source highlight page (exact, no title ambiguity);
        2. strengthened title match (equals → contains → normalized two-way
           containment over the whole Books DB).
        """
        if not self._books_database_id:
            return None

        if source_page_id:
            pid = self._reverse_lookup_book(source_page_id)
            if pid:
                return pid

        return self._match_book_by_name(book_title)

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

    def _match_book_by_name(self, book_title: str) -> Optional[str]:
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
                    return results[0].get("id")
            except Exception as e:
                logger.warning(f"Books DB 查詢 '{main}' 失敗: {e}")
                break

        # normalized two-way containment over all Books pages (cached per run)
        main_norm = self._normalize(main)
        for page in self._all_books_pages():
            name_norm = self._normalize(self._page_name(page))
            if name_norm and (name_norm in main_norm or main_norm in name_norm):
                return page.get("id")
        return None

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
        score = getattr(card, "quality_score", 0) or 0
        if score > 0 and self._wants(_QUALITY_PROPERTY):
            props[_QUALITY_PROPERTY] = {"number": score}
        if self._wants(_STATUS_PROPERTY):
            props[_STATUS_PROPERTY] = {"select": {"name": self._status_name(card)}}
        if books_page_id and self._wants("來源"):
            props["來源"] = {"relation": [{"id": books_page_id}]}
        return props

    @staticmethod
    def _status_name(card: ZettelkastenCard) -> str:
        """草稿 for a rough draft, 已審 once its score clears the reviewed bar.

        永久筆記 is a human decision and is never set automatically.
        """
        score = getattr(card, "quality_score", 0) or 0
        return _STATUS_REVIEWED if score >= _REVIEWED_SCORE else _STATUS_DRAFT

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

        notes = (getattr(card, "revision_notes", "") or "").strip()
        if notes:
            blocks.append(self._revision_toggle(notes))

        return blocks

    @staticmethod
    def _revision_toggle(notes: str) -> dict:
        """Collapsible block holding Gemini's revision notes, for later review."""
        return {
            "object": "block",
            "type": "toggle",
            "toggle": {
                "rich_text": [{"type": "text", "text": {"content": "🔍 AI 審稿修改說明"}}],
                "children": [_paragraph(notes[:_RICH_TEXT_LIMIT])],
            },
        }


def _paragraph(text: str) -> dict:
    return {
        "object": "block",
        "type": "paragraph",
        "paragraph": {
            "rich_text": [{"type": "text", "text": {"content": text}}],
        },
    }
