"""tools/make_card_infographic.py：流程編排與報告（Notion 與 LLM 以假物件取代）。"""
import os
import unittest
from unittest import mock

from src.application.use_cases.make_card_infographic_use_case import InfographicResult
from src.config.settings import Settings
from src.domain.entities.infographic_spec import MarkedCard
from tools.make_card_infographic import format_report, pick_model, run


class FakeRepo:
    def __init__(self, marked=(), created=False):
        self.marked = list(marked)
        self.created = created
        self.ensure_calls = 0

    def ensure_infographic_column(self):
        self.ensure_calls += 1
        return self.created

    def list_cards_marked_for_infographic(self):
        return self.marked


class FakeUseCase:
    def __init__(self, result=None):
        self.result = result or InfographicResult()
        self.calls = []

    def execute(self, marked, force=False, dry_run=False):
        self.calls.append((list(marked), force, dry_run))
        return self.result


MARKED = [MarkedCard("p1", "改變身分", "BM-2")]


class TestRun(unittest.TestCase):
    def test_passes_marked_cards_and_flags_to_the_use_case(self):
        repo, uc = FakeRepo(MARKED), FakeUseCase()
        run(dry_run=False, force=True, repo=repo, use_case=uc)
        self.assertEqual(uc.calls, [(MARKED, True, False)])

    def test_real_run_makes_sure_the_checkbox_column_exists(self):
        repo = FakeRepo(MARKED)
        run(dry_run=False, force=False, repo=repo, use_case=FakeUseCase())
        self.assertEqual(repo.ensure_calls, 1)

    def test_dry_run_never_touches_the_notion_schema(self):
        repo = FakeRepo(MARKED)
        run(dry_run=True, force=False, repo=repo, use_case=FakeUseCase())
        self.assertEqual(repo.ensure_calls, 0)

    def test_nothing_marked_does_not_call_the_use_case(self):
        uc = FakeUseCase()
        report, code = run(dry_run=False, force=False, repo=FakeRepo([]), use_case=uc)
        self.assertEqual(uc.calls, [])
        self.assertEqual(code, 0)
        self.assertIn("做圖", report)

    def test_dry_run_with_nothing_marked_explains_that_the_column_may_not_exist_yet(self):
        report, code = run(dry_run=True, force=False, repo=FakeRepo([]), use_case=FakeUseCase())
        self.assertEqual(code, 0)
        self.assertIn("正式執行", report)
        self.assertNotIn("勾選要做圖的卡後，再執行一次", report)

    def test_newly_created_column_is_announced(self):
        report, _ = run(dry_run=False, force=False, repo=FakeRepo([], created=True),
                        use_case=FakeUseCase())
        self.assertIn("已在卡片盒建立", report)

    def test_exit_code_is_nonzero_only_when_something_failed(self):
        ok = InfographicResult(generated=[("甲", "a.html")])
        bad = InfographicResult(failed=[("乙", "boom")])
        _, ok_code = run(dry_run=False, force=False, repo=FakeRepo(MARKED), use_case=FakeUseCase(ok))
        _, bad_code = run(dry_run=False, force=False, repo=FakeRepo(MARKED), use_case=FakeUseCase(bad))
        self.assertEqual((ok_code, bad_code), (0, 1))


class TestFormatReport(unittest.TestCase):
    def test_lists_each_outcome_with_its_path_or_reason(self):
        result = InfographicResult(
            generated=[("甲", "out/甲.html")], skipped=[("乙", "已產生過")], failed=[("丙", "boom")],
        )
        text = format_report(result, dry_run=False)
        for needle in ("out/甲.html", "已產生過", "boom", "html.to.design"):
            self.assertIn(needle, text)

    def test_dry_run_report_says_nothing_was_written(self):
        result = InfographicResult(planned=[("甲", "out/甲.html")])
        text = format_report(result, dry_run=True)
        self.assertIn("out/甲.html", text)
        self.assertIn("沒有寫入", text)

    def test_figma_hint_only_when_something_was_generated(self):
        self.assertNotIn("html.to.design", format_report(InfographicResult(), dry_run=False))


class TestPickModel(unittest.TestCase):
    def test_dedicated_model_wins_over_the_card_model(self):
        with mock.patch.dict(os.environ, {"OLLAMA_INFOGRAPHIC_MODEL": "gemma4:12b"}):
            self.assertEqual(pick_model("qwen3:4b"), "gemma4:12b")

    def test_falls_back_to_the_card_model_when_unset_or_blank(self):
        with mock.patch.dict(os.environ, {"OLLAMA_INFOGRAPHIC_MODEL": "  "}):
            self.assertEqual(pick_model("qwen3:4b"), "qwen3:4b")
        with mock.patch.dict(os.environ):
            os.environ.pop("OLLAMA_INFOGRAPHIC_MODEL", None)
            self.assertEqual(pick_model("qwen3:4b"), "qwen3:4b")


class TestSettings(unittest.TestCase):
    def _env(self, **extra):
        env = {"NOTION_TOKEN": "t", "NOTION_DATABASE_ID": "d", **extra}
        return mock.patch.dict(os.environ, env), mock.patch("src.config.settings.load_dotenv")

    def test_output_dir_defaults_and_can_be_overridden(self):
        env, dotenv = self._env()
        with env, dotenv:
            os.environ.pop("INFOGRAPHICS_OUTPUT_DIR", None)
            self.assertEqual(Settings.from_env().infographics_output_dir, "infographics_out")
        env, dotenv = self._env(INFOGRAPHICS_OUTPUT_DIR="my_out")
        with env, dotenv:
            self.assertEqual(Settings.from_env().infographics_output_dir, "my_out")


if __name__ == "__main__":
    unittest.main()
