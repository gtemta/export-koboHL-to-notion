"""Host a book's cover inside Notion via the File Upload API.

Why not just write the cover's URL: Notion's servers fetch external images
themselves, and Kobo's CDN (behind Cloudflare) refuses them — the image
downloads fine from our machine but renders as "Permission denied" in Notion
(2026-10-09). An uploaded file lives in Notion, so it shows no matter which
site the cover came from.

File Upload works with the notion-client default API version (2022-06-28), so
this module needs no version override. One upload can be attached to any number
of places (page cover, page icon, image block), so each book is uploaded once
per run.
"""
import logging
import threading
import time
from typing import Any, Callable, Dict, Optional, Tuple

from notion_client import Client

from ..external.cover_fetcher import CoverFinder, CoverImage
from .rate_limiter import NotionRateLimiter
from .retry_policy import retry_with_backoff

logger = logging.getLogger(__name__)

# 建立後一小時內必須掛到某個頁面／block 上，否則失效；留 10 分鐘餘裕後就重傳。
_UPLOAD_TTL_SECONDS = 50 * 60
_EXTENSIONS = {
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/gif": ".gif",
    "image/webp": ".webp",
}


def file_upload_ref(file_id: str) -> Dict[str, Any]:
    """Page cover/icon pointing at a file uploaded to Notion."""
    return {"type": "file_upload", "file_upload": {"id": file_id}}


class CoverUploader:
    """`upload(book)` → file_upload id of the book's cover, cached per run."""

    def __init__(
        self,
        token: str,
        cover_finder: CoverFinder,
        rate_limiter: Optional[NotionRateLimiter] = None,
        client: Optional[Client] = None,
        clock: Callable[[], float] = time.monotonic,
    ):
        self._finder = cover_finder
        self._client = client or Client(auth=token)
        self._rate_limiter = rate_limiter or NotionRateLimiter()
        self._clock = clock
        self._uploads: Dict[str, Tuple[str, float]] = {}
        self._lock = threading.Lock()

    @property
    def finder(self) -> CoverFinder:
        return self._finder

    def upload(self, book) -> Optional[str]:
        """None when no cover exists anywhere; raises when the upload itself fails
        (callers log it and retry on the next sync — nothing was written)."""
        image = self._finder.find_image(book)
        if image is None:
            return None
        key = book.id or book.title
        with self._lock:
            cached = self._uploads.get(key)
            if cached and self._clock() - cached[1] < _UPLOAD_TTL_SECONDS:
                return cached[0]
        file_id = self._upload(image)
        with self._lock:
            self._uploads[key] = (file_id, self._clock())
        logger.info(f"已上傳 '{book.title}' 的封面到 Notion（來源 {image.source}）")
        return file_id

    def _upload(self, image: CoverImage) -> str:
        filename = f"cover{_EXTENSIONS.get(image.content_type, '')}"
        created = retry_with_backoff(
            lambda: self._client.request(
                path="file_uploads", method="POST",
                body={"filename": filename, "content_type": image.content_type}),
            self._rate_limiter,
        )
        file_id = created["id"]

        def send() -> dict:
            # multipart 不能走 Client.request（只送 JSON），直接用它底下的 httpx client，
            # 授權與 API 版本都是這個 client 的預設值。
            http = self._client.client
            response = http.send(http.build_request(
                "POST", f"file_uploads/{file_id}/send",
                files={"file": (filename, image.data, image.content_type)}))
            if response.status_code != 200:
                raise RuntimeError(
                    f"上傳封面失敗（HTTP {response.status_code}）: {response.text[:200]}")
            return response.json()

        sent = retry_with_backoff(send, self._rate_limiter)
        if sent.get("status") != "uploaded":
            raise RuntimeError(f"上傳封面後狀態不是 uploaded: {sent.get('status')}")
        return file_id
