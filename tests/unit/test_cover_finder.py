"""CoverFinder — Kobo 圖床優先、Google Books／Open Library 遞補、每張圖都驗證。"""
import unittest
from unittest import mock

import requests

from src.domain.entities.book import Book
from src.infrastructure.external.cover_fetcher import (
    KOBO_CDN_URL,
    CoverFinder,
    is_legacy_openlibrary_url,
    is_real_isbn13,
)

_GOOGLE = "https://www.googleapis.com/"


class _Resp:
    def __init__(self, status=200, ctype="image/jpeg", size=5000, payload=None):
        self.status_code = status
        self.headers = {"content-type": ctype}
        self.content = b"x" * size
        self._payload = payload

    def json(self):
        if self._payload is None:
            raise ValueError("no json")
        return self._payload


class _FakeHttp:
    """依序比對路由；沒對到的一律回 404 html。"""

    def __init__(self, routes):
        self.routes = routes
        self.calls = []

    def __call__(self, url, params=None, timeout=None):
        self.calls.append((url, params or {}))
        for match, resp in self.routes:
            if match(url, params or {}):
                return resp
        return _Resp(status=404, ctype="text/html", size=10)


def _book(**overrides):
    fields = dict(id="b1", title="多巴胺國度：在縱慾年代找到身心平衡",
                  isbn="9786267195185", image_id="img-1")
    fields.update(overrides)
    return Book(**fields)


def _google_calls(http):
    return [c for c in http.calls if c[0].startswith(_GOOGLE)]


class TestCoverFinder(unittest.TestCase):
    def test_kobo_cdn_is_first_and_enough(self):
        http = _FakeHttp([(lambda u, p: u.startswith("https://cdn.kobo.com/"), _Resp())])
        self.assertEqual(
            CoverFinder(http_get=http).find(_book()),
            KOBO_CDN_URL.format(image_id="img-1"))
        self.assertEqual(len(http.calls), 1)

    def test_google_isbn_when_no_image_id(self):
        payload = {"items": [{"volumeInfo": {
            "title": "多巴胺國度",
            "imageLinks": {"thumbnail": "http://books.google.com/x?id=1&zoom=1"}}}]}
        http = _FakeHttp([
            (lambda u, p: u.startswith(_GOOGLE) and p.get("q") == "isbn:9786267195185",
             _Resp(ctype="application/json", payload=payload)),
            (lambda u, p: u == "http://books.google.com/x?id=1&zoom=3", _Resp()),
        ])
        self.assertEqual(
            CoverFinder(http_get=http).find(_book(image_id=None)),
            "http://books.google.com/x?id=1&zoom=3")

    def test_google_quota_exhausted_falls_back_and_stops_asking(self):
        http = _FakeHttp([
            (lambda u, p: u.startswith(_GOOGLE), _Resp(status=429, ctype="application/json")),
            (lambda u, p: u.startswith("https://covers.openlibrary.org/"),
             _Resp(status=404, ctype="text/html", size=10)),
        ])
        finder = CoverFinder(http_get=http)
        with self.assertLogs("src.infrastructure.external.cover_fetcher", level="WARNING"):
            self.assertIsNone(finder.find(_book(image_id=None)))
        self.assertEqual(len(_google_calls(http)), 1)  # 429 後同一本書不再查書名
        self.assertIsNone(finder.find(_book(id="b2", image_id=None)))
        self.assertEqual(len(_google_calls(http)), 1)  # 第二本書完全不問 Google

    def test_google_non_200_abandons_source_and_warns_once(self):
        http = _FakeHttp([
            (lambda u, p: u.startswith(_GOOGLE), _Resp(status=403, ctype="application/json")),
        ])
        finder = CoverFinder(http_get=http)
        with self.assertLogs("src.infrastructure.external.cover_fetcher",
                              level="WARNING") as cm:
            finder.find(_book(image_id=None))
        self.assertEqual(len(_google_calls(http)), 1)  # ISBN 查詢一次 403 後即放棄本書
        self.assertTrue(any("403" in message for message in cm.output))
        finder.find(_book(id="b2", image_id=None))
        self.assertEqual(len(_google_calls(http)), 1)  # 第二本書完全不問 Google

    def test_title_search_rejects_other_books(self):
        payload = {"items": [
            {"volumeInfo": {"title": "多巴胺的秘密",
                            "imageLinks": {"thumbnail": "http://g/wrong&zoom=1"}}},
            {"volumeInfo": {"title": "多巴胺國度",
                            "imageLinks": {"thumbnail": "http://g/right&zoom=1"}}},
        ]}
        http = _FakeHttp([
            (lambda u, p: u.startswith(_GOOGLE) and p.get("q") == "intitle:多巴胺國度",
             _Resp(ctype="application/json", payload=payload)),
            (lambda u, p: u.startswith("http://g/"), _Resp()),
        ])
        url = CoverFinder(http_get=http).find(_book(image_id=None, isbn="7363579164627"))
        self.assertEqual(url, "http://g/right&zoom=3")
        self.assertNotIn("http://g/wrong&zoom=3", [c[0] for c in http.calls])

    def test_placeholder_gif_rejected(self):
        http = _FakeHttp([(lambda u, p: u.startswith("https://cdn.kobo.com/"),
                           _Resp(ctype="image/gif", size=43))])
        self.assertIsNone(CoverFinder(http_get=http).find(_book(isbn="7363579164627")))

    def test_open_library_used_for_real_isbn(self):
        http = _FakeHttp([(lambda u, p: u.startswith("https://covers.openlibrary.org/"),
                           _Resp())])
        url = CoverFinder(http_get=http).find(_book(image_id=None))
        self.assertEqual(
            url, "https://covers.openlibrary.org/b/isbn/9786267195185-L.jpg?default=false")

    def test_result_cached_per_book(self):
        http = _FakeHttp([(lambda u, p: u.startswith("https://cdn.kobo.com/"), _Resp())])
        finder = CoverFinder(http_get=http)
        finder.find(_book())
        finder.find(_book())
        self.assertEqual(len(http.calls), 1)

    def test_api_key_sent_to_google(self):
        http = _FakeHttp([])
        CoverFinder(google_api_key="k-1", http_get=http).find(_book(image_id=None))
        google = [p for u, p in _google_calls(http)]
        self.assertTrue(google)
        self.assertTrue(all(p.get("key") == "k-1" for p in google))

    def test_network_error_is_not_fatal(self):
        def boom(url, params=None, timeout=None):
            raise requests.ConnectionError("offline")

        self.assertIsNone(CoverFinder(http_get=boom).find(_book()))

    def test_google_exception_never_logs_the_api_key(self):
        """F7：連線例外的訊息常帶著完整請求 URL（含 key=），不可整包印進 log。"""
        def boom(url, params=None, timeout=None):
            if url.startswith(_GOOGLE):
                raise requests.ConnectionError(f"connect failed: {url}?key=SECRET")
            return _Resp(status=404, ctype="text/html", size=10)

        with mock.patch(
            "src.infrastructure.external.cover_fetcher.logger"
        ) as mock_logger:
            CoverFinder(google_api_key="SECRET", http_get=boom).find(_book(image_id=None))

        for method in ("debug", "info", "warning", "error"):
            for call in getattr(mock_logger, method).call_args_list:
                for value in list(call.args) + list(call.kwargs.values()):
                    self.assertNotIn("SECRET", str(value))


class TestHelpers(unittest.TestCase):
    def test_real_isbn13(self):
        self.assertTrue(is_real_isbn13("9786267195185"))
        self.assertTrue(is_real_isbn13(" 9791234567890 "))
        self.assertFalse(is_real_isbn13("7363579164627"))  # Kobo 內部 id
        self.assertFalse(is_real_isbn13(None))

    def test_legacy_openlibrary_url(self):
        self.assertTrue(is_legacy_openlibrary_url(
            "https://covers.openlibrary.org/b/isbn/9786267195185-L.jpg"))
        self.assertFalse(is_legacy_openlibrary_url(
            "https://covers.openlibrary.org/b/isbn/9786267195185-L.jpg?default=false"))
        self.assertFalse(is_legacy_openlibrary_url(KOBO_CDN_URL.format(image_id="x")))
        self.assertFalse(is_legacy_openlibrary_url(None))


if __name__ == "__main__":
    unittest.main()
