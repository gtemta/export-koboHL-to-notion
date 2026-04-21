"""Book cover lookup — tries Google Books first, falls back to Open Library by ISBN."""
import logging
from typing import Optional

import requests

logger = logging.getLogger(__name__)

_GOOGLE_BOOKS_URL = "https://www.googleapis.com/books/v1/volumes"
_OPEN_LIBRARY_URL = "https://covers.openlibrary.org/b/isbn/{isbn}-L.jpg"
_REQUEST_TIMEOUT = 8.0


def get_google_books_cover(title: str) -> Optional[str]:
    """Query Google Books for a high-resolution cover URL."""
    try:
        response = requests.get(
            _GOOGLE_BOOKS_URL,
            params={"q": f"intitle:{title}", "maxResults": 1},
            timeout=_REQUEST_TIMEOUT,
        )
        if response.status_code != 200:
            logger.debug(f"Google Books non-200: {response.status_code}")
            return None
        items = response.json().get("items") or []
        if not items:
            return None
        links = items[0].get("volumeInfo", {}).get("imageLinks", {})
        thumb = links.get("thumbnail")
        if not thumb:
            return None
        return thumb.replace("&zoom=1", "&zoom=3")
    except (requests.RequestException, ValueError) as e:
        logger.debug(f"Google Books 查詢失敗: {e}")
        return None


def get_openlibrary_cover(isbn: str) -> str:
    return _OPEN_LIBRARY_URL.format(isbn=isbn)


def get_best_book_cover(title: str, isbn: Optional[str]) -> Optional[str]:
    """Google Books preferred; Open Library fallback if ISBN is present."""
    cover = get_google_books_cover(title)
    if cover:
        return cover
    if isbn:
        return get_openlibrary_cover(isbn)
    return None
