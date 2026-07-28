"""Retry helper for Notion API — handles 409/429 plus transient network errors."""
import logging
import time
from typing import Callable, TypeVar

import httpx
from notion_client.errors import APIResponseError, RequestTimeoutError

from .rate_limiter import NotionRateLimiter

logger = logging.getLogger(__name__)

T = TypeVar('T')

# 連不上／連到一半斷掉的暫時性錯誤。這些不是 APIResponseError（連 HTTP 回應都沒
# 拿到），2026-07-28 實跑時一段兩秒的 DNS 中斷就這樣讓 5 本書直接失敗。
# 刻意不含 LocalProtocolError / UnsupportedProtocol — 那是我們這端請求組錯，重試
# 只會用同樣的錯誤再撞三次。
_TRANSIENT_NETWORK_ERRORS = (
    httpx.NetworkError,        # ConnectError（含 DNS getaddrinfo 失敗）、ReadError…
    httpx.TimeoutException,    # ConnectTimeout / ReadTimeout / PoolTimeout
    httpx.RemoteProtocolError,  # Server disconnected without sending a response.
    httpx.ProxyError,
    RequestTimeoutError,       # notion_client 自己包的 timeout
)


def retry_with_backoff(
    fn: Callable[[], T],
    rate_limiter: NotionRateLimiter,
    max_retries: int = 3,
    base_delay: float = 1.0,
) -> T:
    """Run `fn` respecting the rate limiter, retrying 409/429/網路中斷 with backoff."""
    delay = base_delay
    for attempt in range(max_retries):
        try:
            rate_limiter.wait()
            return fn()
        except _TRANSIENT_NETWORK_ERRORS as e:
            if attempt < max_retries - 1:
                logger.warning(
                    f"網路暫時性錯誤（{type(e).__name__}: {e}），"
                    f"第 {attempt + 1} 次重試，等待 {delay}s"
                )
                time.sleep(delay)
                delay *= 2
            else:
                logger.error(f"網路錯誤，重試 {max_retries} 次仍失敗: {e}")
                raise
        except APIResponseError as e:
            err = str(e)
            if "429" in err:
                wait = delay * 2
                logger.warning(f"Rate limit (429) hit, 等待 {wait}s")
                time.sleep(wait)
                delay *= 2
            elif "409" in err and attempt < max_retries - 1:
                logger.warning(f"409 衝突，第 {attempt + 1} 次重試，等待 {delay}s")
                time.sleep(delay)
                delay *= 2
            elif "404" in err and attempt < max_retries - 1:
                logger.warning(f"Notion 404 (資料來源暫時無法解析)，第 {attempt + 1} 次重試，等待 {delay}s")
                time.sleep(delay)
                delay *= 2
            else:
                logger.error(f"Notion API 錯誤 ({attempt + 1}/{max_retries}): {err}")
                raise
    raise RuntimeError(f"重試 {max_retries} 次仍失敗")
