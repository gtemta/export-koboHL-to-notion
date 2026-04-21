"""Retry helper for Notion API — handles 409 conflicts and 429 rate limits."""
import logging
import time
from typing import Callable, TypeVar

from notion_client.errors import APIResponseError

from .rate_limiter import NotionRateLimiter

logger = logging.getLogger(__name__)

T = TypeVar('T')


def retry_with_backoff(
    fn: Callable[[], T],
    rate_limiter: NotionRateLimiter,
    max_retries: int = 3,
    base_delay: float = 1.0,
) -> T:
    """Run `fn` respecting the rate limiter, retrying 409/429 with exponential backoff."""
    delay = base_delay
    for attempt in range(max_retries):
        try:
            rate_limiter.wait()
            return fn()
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
            else:
                logger.error(f"Notion API 錯誤 ({attempt + 1}/{max_retries}): {err}")
                raise
    raise RuntimeError(f"重試 {max_retries} 次仍失敗")
