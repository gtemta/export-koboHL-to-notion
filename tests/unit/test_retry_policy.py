"""retry_with_backoff 的暫時性網路錯誤重試。

2026-07-28 實跑事故：api.notion.com 的 DNS 解析失敗約兩秒（getaddrinfo failed），
期間還夾雜 `Server disconnected without sending a response.`。這兩種都不是
`APIResponseError`，直接穿過原本只認 409/429/404 的 except，5 本書當場判死、
不重試。本檔鎖住「暫時性傳輸錯誤要退避重試」這個行為。
"""
import unittest
from unittest.mock import patch

import httpx
from notion_client.errors import APIResponseError

from src.infrastructure.notion.retry_policy import retry_with_backoff


class _NoWaitLimiter:
    """retry_with_backoff 只需要 .wait()；這裡不真的睡。"""

    def __init__(self):
        self.waits = 0

    def wait(self):
        self.waits += 1


def _api_error(status: int) -> APIResponseError:
    """造一個帶 status code 的 APIResponseError（訊息含代碼，policy 以字串比對）。"""
    response = httpx.Response(
        status, request=httpx.Request("POST", "https://api.notion.com/v1/pages")
    )
    return APIResponseError(response, f"{status} something went wrong", "bad_request")


class RetryTransientNetworkErrorTest(unittest.TestCase):
    """事故重現：連線類錯誤必須重試，而不是第一次就放棄。"""

    def setUp(self):
        # 這些測試只驗證重試次數與最終結果，不需要真的等退避時間。
        patcher = patch("src.infrastructure.notion.retry_policy.time.sleep")
        self.sleep = patcher.start()
        self.addCleanup(patcher.stop)
        self.limiter = _NoWaitLimiter()

    def test_connect_error_then_success(self):
        """DNS 掛掉兩次後恢復 → 應該拿到結果，而不是拋錯。"""
        calls = []

        def fn():
            calls.append(1)
            if len(calls) < 3:
                raise httpx.ConnectError("[Errno 11001] getaddrinfo failed")
            return "ok"

        self.assertEqual(retry_with_backoff(fn, self.limiter), "ok")
        self.assertEqual(len(calls), 3)

    def test_remote_protocol_error_then_success(self):
        """`Server disconnected without sending a response.` 同樣要重試。"""
        calls = []

        def fn():
            calls.append(1)
            if len(calls) < 2:
                raise httpx.RemoteProtocolError(
                    "Server disconnected without sending a response."
                )
            return "ok"

        self.assertEqual(retry_with_backoff(fn, self.limiter), "ok")
        self.assertEqual(len(calls), 2)

    def test_persistent_connect_error_eventually_raises(self):
        """網路真的斷了就該在耗盡重試後拋出，不能無限重試或吞掉錯誤。"""

        def fn():
            raise httpx.ConnectError("[Errno 11001] getaddrinfo failed")

        with self.assertRaises(httpx.ConnectError):
            retry_with_backoff(fn, self.limiter, max_retries=3)

    def test_backoff_is_exponential(self):
        """退避要拉開，避免 DNS 還沒恢復就把重試打光。"""

        def fn():
            raise httpx.ConnectError("boom")

        with self.assertRaises(httpx.ConnectError):
            retry_with_backoff(fn, self.limiter, max_retries=3, base_delay=1.0)
        self.assertEqual([c.args[0] for c in self.sleep.call_args_list], [1.0, 2.0])


class NonTransientErrorTest(unittest.TestCase):
    """回歸防線：既有的不可重試路徑不能因為新增 except 而被改寫。"""

    def setUp(self):
        patcher = patch("src.infrastructure.notion.retry_policy.time.sleep")
        patcher.start()
        self.addCleanup(patcher.stop)
        self.limiter = _NoWaitLimiter()

    def test_400_raises_immediately(self):
        """400 是我們自己送錯資料，重試沒有意義。"""
        calls = []

        def fn():
            calls.append(1)
            raise _api_error(400)

        with self.assertRaises(APIResponseError):
            retry_with_backoff(fn, self.limiter)
        self.assertEqual(len(calls), 1)

    def test_local_protocol_error_is_not_retried(self):
        """LocalProtocolError 是我們這端組錯請求，重試也不會變好。"""
        calls = []

        def fn():
            calls.append(1)
            raise httpx.LocalProtocolError("bad request built locally")

        with self.assertRaises(httpx.LocalProtocolError):
            retry_with_backoff(fn, self.limiter)
        self.assertEqual(len(calls), 1)


if __name__ == "__main__":
    unittest.main()
