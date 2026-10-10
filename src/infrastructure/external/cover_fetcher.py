"""Book covers for Kobo highlight pages and Reading List pages.

Sources, first *validated* hit wins (spec 2026-09-28「封面」):
1. Kobo's own CDN via content.ImageId — exact edition, no quota
   (35/35 in the 2026-09-28 survey);
2. Google Books — real ISBN-13 first, then a main-title search whose result
   title must match; optional API key (keyless calls share one global daily
   quota and mostly return 429, which is how 20/26 covers went blank);
3. Open Library by real ISBN-13 with ?default=false (404 when no cover);
4. Open Library title search — the only source for books that are not on Kobo
   (hand-made Reading List pages have neither ImageId nor ISBN). A hit must
   carry the same title, so another book's cover is never borrowed.

Every candidate is downloaded and checked, so a 1x1 placeholder can never be
written as a "cover" again. The downloaded bytes are kept and handed on
(`CoverImage`): Notion's servers are refused by Kobo's CDN, so a cover that
loads fine here still shows as "Permission denied" in Notion when written as an
external URL — covers are uploaded to Notion instead (see CoverUploader).
"""
import logging
import re
import threading
import unicodedata
from dataclasses import dataclass
from typing import Callable, Dict, List, Optional

import requests

logger = logging.getLogger(__name__)

KOBO_CDN_URL = "https://cdn.kobo.com/book-images/{image_id}/353/569/90/False/image.jpg"
OPEN_LIBRARY_URL = "https://covers.openlibrary.org/b/isbn/{isbn}-L.jpg?default=false"
_OPEN_LIBRARY_SEARCH_URL = "https://openlibrary.org/search.json"
_OPEN_LIBRARY_COVER_URL = "https://covers.openlibrary.org/b/id/{cover_id}-L.jpg?default=false"
_GOOGLE_BOOKS_URL = "https://www.googleapis.com/books/v1/volumes"
_MIN_IMAGE_BYTES = 2048
_TIMEOUT = 8.0
_ISBN13 = re.compile(r"^97[89]\d{10}$")
# 搜尋結果的書名若只是「被主書名包含」，至少要這麼長才算同一本——
# 避免 "Give" 這種短詞命中 "Give and Take"，卻放行完整的英文書名嵌在中文書名裡的情況。
_MIN_CONTAINED_CORE = 10


def is_real_isbn13(isbn: Optional[str]) -> bool:
    """Kobo's ISBN column often holds internal ids (e.g. 7363579164627)."""
    return bool(_ISBN13.match((isbn or "").strip()))


def is_kobo_cdn_url(url: Optional[str]) -> bool:
    """Kobo CDN covers written earlier as external URLs: they download fine from
    our machine, but Kobo's CDN refuses Notion's servers, so Notion renders them
    as a "Permission denied" image."""
    return bool(url) and "cdn.kobo.com/book-images/" in url


def is_legacy_openlibrary_url(url: Optional[str]) -> bool:
    """Open Library URLs written before validation existed: they answer with a
    1x1 placeholder instead of 404 when the book has no cover."""
    return bool(url) and "covers.openlibrary.org" in url and "default=false" not in url


def _title_core(text: str) -> str:
    """Letters/digits only — same idea as the card classifier's text core."""
    return "".join(
        ch for ch in (text or "") if unicodedata.category(ch)[0] in ("L", "N")
    ).lower()


def _main_title(title: str) -> str:
    return re.split(r"[:：]", title or "", maxsplit=1)[0].strip()


def _same_title(doc_core: str, main_core: str) -> bool:
    if doc_core == main_core:
        return True
    return len(doc_core) >= _MIN_CONTAINED_CORE and doc_core in main_core


@dataclass(frozen=True)
class CoverImage:
    """A validated cover: where it came from and the bytes that were checked."""
    url: str
    content_type: str
    data: bytes
    source: str  # kobo | google | openlibrary | openlibrary-search


class CoverFinder:
    """Finds and validates one cover per book; cached for the whole run.

    Shared by the highlight-page cover step (runs in the sync thread pool) and
    Reading List page completion (runs afterwards), so each book is looked up
    once. `http_get` is injectable for tests (signature of requests.get).
    """

    def __init__(self, google_api_key: Optional[str] = None,
                 http_get: Optional[Callable] = None):
        self._google_api_key = google_api_key
        self._http_get = http_get or requests.get
        self._cache: Dict[str, Optional[CoverImage]] = {}
        self._lock = threading.Lock()
        self._google_exhausted = False

    def find(self, book) -> Optional[str]:
        image = self.find_image(book)
        return image.url if image else None

    def find_image(self, book) -> Optional[CoverImage]:
        key = book.id or book.title
        with self._lock:
            if key in self._cache:
                return self._cache[key]
        image = (self._from_kobo(book) or self._from_google(book)
                 or self._from_open_library(book)
                 or self._from_open_library_search(book))
        if image is None:
            logger.info(f"找不到 '{book.title}' 的封面")
        with self._lock:
            self._cache[key] = image
        return image

    def is_valid_image(self, url: Optional[str]) -> bool:
        return self._fetch_image(url, "") is not None

    def _fetch_image(self, url: Optional[str], source: str) -> Optional[CoverImage]:
        if not url:
            return None
        try:
            response = self._http_get(url, timeout=_TIMEOUT)
        except requests.RequestException as e:
            logger.debug(f"封面驗證失敗 {url}: {e}")
            return None
        content_type = (response.headers or {}).get("content-type", "")
        data = response.content or b""
        if (response.status_code == 200 and content_type.startswith("image/")
                and len(data) > _MIN_IMAGE_BYTES):
            return CoverImage(url=url, content_type=content_type.split(";")[0].strip(),
                              data=data, source=source)
        return None

    # ----- sources -----

    def _from_kobo(self, book) -> Optional[CoverImage]:
        image_id = (getattr(book, "image_id", None) or "").strip()
        if not image_id:
            return None
        return self._fetch_image(KOBO_CDN_URL.format(image_id=image_id), "kobo")

    def _from_google(self, book) -> Optional[CoverImage]:
        queries = []
        if is_real_isbn13(book.isbn):
            queries.append((f"isbn:{book.isbn.strip()}", 1, ""))
        main = _main_title(book.title)
        if main:
            queries.append((f"intitle:{main}", 5, _title_core(main)))
        for query, max_results, match_core in queries:
            if self._google_exhausted:
                return None
            for item in self._google_items(query, max_results):
                info = item.get("volumeInfo") or {}
                if match_core:
                    core = _title_core(info.get("title", ""))
                    if not core or (match_core not in core and core not in match_core):
                        continue
                thumb = (info.get("imageLinks") or {}).get("thumbnail")
                if not thumb:
                    continue
                image = self._fetch_image(thumb.replace("&zoom=1", "&zoom=3"), "google")
                if image:
                    return image
        return None

    def _google_items(self, query: str, max_results: int) -> List[dict]:
        params = {"q": query, "maxResults": max_results}
        if self._google_api_key:
            params["key"] = self._google_api_key
        try:
            response = self._http_get(_GOOGLE_BOOKS_URL, params=params, timeout=_TIMEOUT)
        except requests.RequestException as e:
            # 不可印 {e}：連線例外的訊息常帶著完整請求 URL，含 ?key=<GOOGLE_BOOKS_API_KEY>。
            logger.debug(f"Google Books 查詢失敗: {type(e).__name__}")
            return []
        if response.status_code != 200:
            if not self._google_exhausted:
                logger.warning(
                    f"Google Books 查詢失敗（HTTP {response.status_code}），"
                    "本輪不再查詢；可設定 GOOGLE_BOOKS_API_KEY 取得自己的配額")
            self._google_exhausted = True
            return []
        try:
            return response.json().get("items") or []
        except ValueError:
            return []

    def _from_open_library(self, book) -> Optional[CoverImage]:
        if not is_real_isbn13(book.isbn):
            return None
        return self._fetch_image(OPEN_LIBRARY_URL.format(isbn=book.isbn.strip()),
                                 "openlibrary")

    def _from_open_library_search(self, book) -> Optional[CoverImage]:
        main = _main_title(book.title)
        main_core = _title_core(main)
        if not main_core:
            return None
        params = {"title": main, "limit": 5, "fields": "title,cover_i"}
        try:
            response = self._http_get(_OPEN_LIBRARY_SEARCH_URL, params=params,
                                      timeout=_TIMEOUT)
            if response.status_code != 200:
                return None
            docs = response.json().get("docs") or []
        except (requests.RequestException, ValueError) as e:
            logger.debug(f"Open Library 搜尋失敗: {type(e).__name__}")
            return None
        for doc in docs:
            cover_id = doc.get("cover_i")
            doc_core = _title_core(doc.get("title", ""))
            if not cover_id or not doc_core or not _same_title(doc_core, main_core):
                continue
            image = self._fetch_image(
                _OPEN_LIBRARY_COVER_URL.format(cover_id=cover_id), "openlibrary-search")
            if image:
                logger.info(f"Open Library 搜尋命中 '{doc.get('title')}'（{book.title}）")
                return image
        return None
