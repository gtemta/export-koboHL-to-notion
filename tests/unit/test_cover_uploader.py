"""CoverUploader — 把驗證過的書封上傳給 Notion（File Upload API），回傳 file_upload id。

用真的 notion_client.Client 搭 httpx.MockTransport：驗的是實際送出的請求
（JSON 建立、multipart 傳檔、預設 API 版本），不是 mock 掉的呼叫。
"""
import json
import unittest

import httpx
from notion_client import Client

from src.domain.entities.book import Book
from src.infrastructure.external.cover_fetcher import CoverImage
from src.infrastructure.notion.cover_uploader import CoverUploader


class _NoWait:
    def wait(self):
        pass


class _Finder:
    def __init__(self, image):
        self.image = image
        self.calls = 0

    def find_image(self, book):
        self.calls += 1
        return self.image


class _Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


def _image(content_type="image/jpeg", data=b"JPEGDATA" * 400):
    return CoverImage(url="https://cdn.kobo.com/x.jpg", content_type=content_type,
                      data=data, source="kobo")


BOOK = Book(id="b1", title="多巴胺國度")


class _Notion:
    """Records every request; answers the two File Upload endpoints."""

    def __init__(self, send_status=200, send_body=None, create_status=200):
        self.requests = []
        self.send_status = send_status
        self.send_body = send_body or {"status": "uploaded"}
        self.create_status = create_status
        self.created = 0

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if request.url.path.endswith("/file_uploads"):
            if self.create_status != 200:
                return httpx.Response(self.create_status, json={
                    "object": "error", "code": "validation_error", "message": "bad"})
            self.created += 1
            return httpx.Response(200, json={"id": f"upload-{self.created}",
                                             "status": "pending"})
        return httpx.Response(self.send_status, json=self.send_body)

    def client(self):
        return Client(auth="secret", client=httpx.Client(
            transport=httpx.MockTransport(self.handler)))


def _uploader(notion, finder, clock=None):
    return CoverUploader(token="secret", cover_finder=finder, rate_limiter=_NoWait(),
                         client=notion.client(), clock=clock or _Clock())


class TestUpload(unittest.TestCase):
    def test_creates_then_sends_the_bytes_and_returns_the_id(self):
        notion = _Notion()
        file_id = _uploader(notion, _Finder(_image())).upload(BOOK)

        self.assertEqual(file_id, "upload-1")
        create, send = notion.requests
        self.assertEqual(create.method, "POST")
        self.assertEqual(create.url.path, "/v1/file_uploads")
        self.assertEqual(json.loads(create.content),
                         {"filename": "cover.jpg", "content_type": "image/jpeg"})
        self.assertEqual(send.url.path, "/v1/file_uploads/upload-1/send")
        self.assertTrue(send.headers["content-type"].startswith("multipart/form-data"))
        self.assertIn(b"JPEGDATA" * 400, send.content)

    def test_uses_the_default_notion_version(self):
        notion = _Notion()
        _uploader(notion, _Finder(_image())).upload(BOOK)
        for request in notion.requests:
            self.assertEqual(request.headers["notion-version"], "2022-06-28")

    def test_filename_follows_the_content_type(self):
        notion = _Notion()
        _uploader(notion, _Finder(_image("image/png"))).upload(BOOK)
        self.assertEqual(json.loads(notion.requests[0].content)["filename"], "cover.png")

    def test_same_book_is_uploaded_once(self):
        notion = _Notion()
        uploader = _uploader(notion, _Finder(_image()))
        self.assertEqual(uploader.upload(BOOK), uploader.upload(BOOK))
        self.assertEqual(len(notion.requests), 2)

    def test_upload_is_repeated_after_it_may_have_expired(self):
        notion = _Notion()
        clock = _Clock()
        uploader = _uploader(notion, _Finder(_image()), clock)
        first = uploader.upload(BOOK)
        clock.now += 51 * 60  # Notion 的 file_upload 建立後一小時內要掛上去
        self.assertNotEqual(uploader.upload(BOOK), first)
        self.assertEqual(notion.created, 2)

    def test_no_cover_found_means_none_and_no_request(self):
        notion = _Notion()
        self.assertIsNone(_uploader(notion, _Finder(None)).upload(BOOK))
        self.assertEqual(notion.requests, [])

    def test_failed_send_raises_and_is_not_cached(self):
        notion = _Notion(send_status=400, send_body={"object": "error", "message": "nope"})
        uploader = _uploader(notion, _Finder(_image()))
        with self.assertRaises(RuntimeError) as ctx:
            uploader.upload(BOOK)
        self.assertIn("400", str(ctx.exception))
        notion.send_status, notion.send_body = 200, {"status": "uploaded"}
        self.assertEqual(uploader.upload(BOOK), "upload-2")

    def test_send_that_does_not_end_uploaded_raises(self):
        notion = _Notion(send_body={"status": "failed"})
        with self.assertRaises(RuntimeError):
            _uploader(notion, _Finder(_image())).upload(BOOK)

    def test_failed_create_raises(self):
        notion = _Notion(create_status=400)
        with self.assertRaises(Exception):
            _uploader(notion, _Finder(_image())).upload(BOOK)


if __name__ == "__main__":
    unittest.main()
