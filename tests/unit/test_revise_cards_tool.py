"""tools/revise_cards.py：報告與 exit code（Notion 與 LLM 以假物件取代）。"""
import unittest

from src.application.dtos.card_revision_report import CardRevisionReport
from tools.revise_cards import format_report, run


class FakeUseCase:
    def __init__(self, report=None, error=None):
        self.report = report or CardRevisionReport()
        self.error = error
        self.calls = []

    def execute(self, dry_run=False):
        self.calls.append(dry_run)
        if self.error:
            raise self.error
        return self.report


class TestRun(unittest.TestCase):
    def test_passes_the_dry_run_flag(self):
        use_case = FakeUseCase()
        run(dry_run=True, use_case=use_case)
        self.assertEqual(use_case.calls, [True])

    def test_exit_code_is_nonzero_when_a_card_failed(self):
        report = CardRevisionReport(failed=[("甲", "boom")])
        self.assertEqual(run(use_case=FakeUseCase(report))[1], 1)

    def test_exit_code_is_nonzero_when_the_run_was_aborted(self):
        report = CardRevisionReport(aborted="審核模型不可用")
        self.assertEqual(run(use_case=FakeUseCase(report))[1], 1)

    def test_exit_code_is_zero_when_everything_went_through(self):
        report = CardRevisionReport(reviewed=["甲"], skipped=[("乙", "審過了")])
        self.assertEqual(run(use_case=FakeUseCase(report))[1], 0)

    def test_a_failed_notion_read_is_not_mistaken_for_no_cards(self):
        text, code = run(use_case=FakeUseCase(error=RuntimeError("503")))
        self.assertEqual(code, 1)
        self.assertIn("503", text)


class TestFormatReport(unittest.TestCase):
    def test_nothing_marked_says_how_to_mark_a_card(self):
        self.assertIn("🔧待修正", format_report(CardRevisionReport(), dry_run=False))

    def test_dry_run_says_nothing_was_written(self):
        text = format_report(CardRevisionReport(planned=[("甲", "只審目前版本")]), dry_run=True)
        self.assertIn("甲", text)
        self.assertIn("只審目前版本", text)
        self.assertIn("沒有寫入", text)

    def test_real_run_lists_every_outcome_and_where_results_went(self):
        report = CardRevisionReport(
            reviewed=["甲"], regenerated=["乙"], skipped=[("丙", "審過了")], failed=[("丁", "boom")],
        )
        text = format_report(report, dry_run=False)
        for needle in ("甲", "乙", "丙", "審過了", "丁", "boom", "🤖 重審結果"):
            self.assertIn(needle, text)

    def test_aborted_run_says_why(self):
        text = format_report(CardRevisionReport(aborted="審核模型不可用"), dry_run=False)
        self.assertIn("審核模型不可用", text)


if __name__ == "__main__":
    unittest.main()
