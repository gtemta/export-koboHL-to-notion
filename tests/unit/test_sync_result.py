import unittest

from src.application.dtos.sync_result import SyncResult


class TestSyncResult(unittest.TestCase):
    def test_failed_syncs_tracks_late_increments(self):
        """execute() 先建 result 再遞增 successful_syncs；
        failed_syncs 必須反映最終值，否則成功執行也會 exit 1。"""
        result = SyncResult(total_books=3, successful_syncs=0)
        result.successful_syncs += 3
        self.assertEqual(result.failed_syncs, 0)

    def test_failed_syncs_counts_shortfall(self):
        result = SyncResult(total_books=5, successful_syncs=0)
        result.successful_syncs += 3
        self.assertEqual(result.failed_syncs, 2)

    def test_success_rate(self):
        result = SyncResult(total_books=4, successful_syncs=1)
        self.assertEqual(result.success_rate, 25.0)
        empty = SyncResult(total_books=0, successful_syncs=0)
        self.assertEqual(empty.success_rate, 0.0)


if __name__ == "__main__":
    unittest.main()
