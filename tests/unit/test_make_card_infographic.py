"""MakeCardInfographicUseCase：被勾選的卡 → 本地 HTML 概念圖卡。"""
import json
import os
import shutil
import tempfile
import unittest

from src.application.use_cases.make_card_infographic_use_case import (
    MakeCardInfographicUseCase,
)
from src.domain.entities.infographic_spec import MapEntry, MarkedCard, Neighbor
from src.infrastructure.persistence.book_map_store import BookMapStore
from src.infrastructure.persistence.card_store import CardStore

BOOK = "原子習慣"
CARDS = [("習慣是複利", "BM-1"), ("改變身分", "BM-2"), ("環境設計", "BM-3")]


class FakeGenerator:
    def __init__(self, map_result="default", spec=None):
        self.map_calls = []
        self.spec_calls = []
        self._map = (
            ("習慣靠系統", {
                "習慣是複利": MapEntry("主軸", [Neighbor("導向", "改變身分")]),
                "改變身分": MapEntry("支柱", [Neighbor("前提", "習慣是複利"),
                                              Neighbor("導向", "環境設計")]),
                "環境設計": MapEntry("案例"),
            }) if map_result == "default" else map_result
        )
        self._spec = spec if spec is not None else {
            "lines": ["目標決定方向。", "身分決定行動。"],
            "nodes": [{"icon": "target", "label": "目標"}, {"icon": "lightbulb", "label": "身分"},
                      {"icon": "repeat", "label": "重複"}],
            "layout": "flow",
        }

    def build_book_map(self, book_title, cards):
        self.map_calls.append((book_title, [c.title for c in cards]))
        return self._map

    def generate_card_spec(self, card, book_title, theme):
        self.spec_calls.append((card.title, book_title, theme))
        return None if self._spec is False else dict(self._spec)


class _Case(unittest.TestCase):
    def setUp(self):
        self.cards_dir = tempfile.mkdtemp()
        self.out_dir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.cards_dir, ignore_errors=True)
        self.addCleanup(shutil.rmtree, self.out_dir, ignore_errors=True)
        self.write_batch("原子習慣_20260101_000000.json", BOOK, CARDS)

    def write_batch(self, filename, book, cards):
        payload = {"book_title": book, "uploaded": True, "cards": [
            {"id": f"id-{t}", "title": t, "content": f"{t}的內容", "source_highlight": "劃線",
             "chapter_reference": "", "chapter_progress": 0.0, "source_bookmark_id": sid}
            for t, sid in cards]}
        with open(os.path.join(self.cards_dir, filename), "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False)

    def use_case(self, generator=None, render=None):
        self.generator = generator or FakeGenerator()
        kwargs = {"render": render} if render else {}
        return MakeCardInfographicUseCase(
            card_store=CardStore(self.cards_dir),
            map_store=BookMapStore(self.cards_dir),
            generator=self.generator,
            output_dir=self.out_dir,
            **kwargs,
        )

    @staticmethod
    def marked(title="改變身分", sid="BM-2"):
        return MarkedCard(page_id=f"p-{sid}", title=title, source_id=sid)

    def read(self, path):
        with open(path, encoding="utf-8") as f:
            return f.read()


class TestGenerate(_Case):
    def test_writes_one_html_per_marked_card_under_a_book_folder(self):
        result = self.use_case().execute([self.marked()])
        self.assertEqual(len(result.generated), 1)
        title, path = result.generated[0]
        self.assertEqual(title, "改變身分")
        self.assertEqual(path, os.path.join(self.out_dir, BOOK, "改變身分.html"))
        html = self.read(path)
        self.assertIn("目標決定方向。", html)
        self.assertIn("《原子習慣》", html)

    def test_role_and_neighbors_come_from_the_book_map_and_show_up_in_the_html(self):
        result = self.use_case().execute([self.marked()])
        html = self.read(result.generated[0][1])
        self.assertIn("支柱觀念", html)
        self.assertIn("習慣是複利", html)
        self.assertIn("環境設計", html)
        self.assertIn("第 2 / 3 張", html)

    def test_role_and_neighbors_claimed_by_the_card_level_model_are_ignored(self):
        spec = {"lines": ["甲"], "nodes": [], "layout": "flow", "role": "主軸",
                "neighbors": [{"relation": "對照", "title": "習慣是複利"}]}
        uc = self.use_case(FakeGenerator(spec=spec))
        html = self.read(uc.execute([self.marked()]).generated[0][1])
        self.assertIn("支柱觀念", html)          # 來自全書地圖，不是模型自報的「主軸」
        self.assertNotIn("對照", html)

    def test_theme_from_the_map_is_passed_to_the_card_prompt(self):
        uc = self.use_case()
        uc.execute([self.marked()])
        self.assertEqual(self.generator.spec_calls, [("改變身分", BOOK, "習慣靠系統")])

    def test_two_marked_cards_of_one_book_share_one_map_call(self):
        uc = self.use_case()
        result = uc.execute([self.marked(), self.marked("環境設計", "BM-3")])
        self.assertEqual(len(result.generated), 2)
        self.assertEqual(len(self.generator.map_calls), 1)

    def test_map_is_cached_across_runs_until_the_card_set_changes(self):
        self.use_case().execute([self.marked()])
        uc = self.use_case()
        uc.execute([self.marked("環境設計", "BM-3")])
        self.assertEqual(self.generator.map_calls, [])
        self.write_batch("原子習慣_20260202_000000.json", BOOK, [("兩分鐘法則", "BM-4")])
        uc = self.use_case(FakeGenerator(map_result=None))
        uc.execute([self.marked()], force=True)
        self.assertEqual(len(self.generator.map_calls), 1)       # 多了一張卡 → 地圖重做

    def test_cards_from_every_batch_of_the_book_form_the_map(self):
        self.write_batch("原子習慣_20260202_000000.json", BOOK, [("兩分鐘法則", "BM-4")])
        uc = self.use_case(FakeGenerator(map_result=None))
        uc.execute([self.marked()])
        self.assertEqual(self.generator.map_calls[0][1],
                         ["習慣是複利", "改變身分", "環境設計", "兩分鐘法則"])


class TestDegradeAndSkip(_Case):
    def test_failed_book_map_still_produces_a_card_with_default_role_and_no_neighbors(self):
        uc = self.use_case(FakeGenerator(map_result=None))
        result = uc.execute([self.marked()])
        html = self.read(result.generated[0][1])
        self.assertNotIn("支柱觀念", html)
        self.assertNotIn('class="map-note"', html)
        self.assertEqual(os.path.exists(os.path.join(self.cards_dir, "maps")), False)  # 失敗的地圖不留存

    def test_card_spec_failure_is_reported_and_writes_nothing(self):
        result = self.use_case(FakeGenerator(spec=False)).execute([self.marked()])
        self.assertEqual(result.generated, [])
        self.assertEqual([t for t, _ in result.failed], ["改變身分"])
        self.assertFalse(os.path.exists(os.path.join(self.out_dir, BOOK)))

    def test_spec_without_any_usable_line_is_a_failure(self):
        uc = self.use_case(FakeGenerator(spec={"lines": [], "nodes": [], "layout": "flow"}))
        result = uc.execute([self.marked()])
        self.assertEqual(len(result.failed), 1)

    def test_marked_card_without_source_id_is_skipped(self):
        result = self.use_case().execute([self.marked("手動卡", "")])
        self.assertEqual(result.generated, [])
        self.assertIn("來源劃線ID", result.skipped[0][1])

    def test_marked_card_missing_from_local_json_is_skipped(self):
        result = self.use_case().execute([self.marked("別的卡", "BM-404")])
        self.assertIn("cards_output", result.skipped[0][1])
        self.assertEqual(self.generator.spec_calls, [])

    def test_existing_file_is_kept_unless_forced(self):
        self.use_case().execute([self.marked()])
        result = self.use_case().execute([self.marked()])
        self.assertEqual(result.generated, [])
        self.assertIn("--force", result.skipped[0][1])
        self.assertEqual(self.generator.spec_calls, [])
        forced = self.use_case().execute([self.marked()], force=True)
        self.assertEqual(len(forced.generated), 1)

    def test_one_cards_unexpected_error_does_not_stop_the_others(self):
        def render(spec, book_title, titles):
            if spec.card_title == "改變身分":
                raise RuntimeError("boom")
            return "<html>ok</html>"

        uc = self.use_case(render=render)
        result = uc.execute([self.marked(), self.marked("環境設計", "BM-3")])
        self.assertEqual([t for t, _ in result.generated], ["環境設計"])
        self.assertEqual([t for t, _ in result.failed], ["改變身分"])
        self.assertIn("boom", result.failed[0][1])

    def test_cards_sharing_a_title_get_distinct_files(self):
        self.write_batch("原子習慣_20260202_000000.json", BOOK, [("改變身分", "BM-9")])
        result = self.use_case().execute([self.marked(), self.marked("改變身分", "BM-9")])
        paths = [p for _, p in result.generated]
        self.assertEqual(len(set(paths)), len(paths))

    def test_titles_whose_file_names_collide_get_distinct_files(self):
        # `a/b` 與 `a:b` 都會變成 a_b；`Abc`／`abc` 在 Windows 是同一個檔
        for first, second in (("a/b", "a:b"), ("Abc", "abc")):
            with self.subTest(first=first):
                self.write_batch("原子習慣_20260202_000000.json", BOOK,
                                 [(first, "BM-7"), (second, "BM-8")])
                result = self.use_case().execute(
                    [self.marked(first, "BM-7"), self.marked(second, "BM-8")])
                paths = [p for _, p in result.generated]
                self.assertEqual(len(paths), 2, result.skipped)
                self.assertEqual(len({p.lower() for p in paths}), 2)

    def test_a_colliding_title_keeps_the_same_file_name_whichever_cards_are_marked(self):
        self.write_batch("原子習慣_20260202_000000.json", BOOK, [("a/b", "BM-7"), ("a:b", "BM-8")])
        alone = self.use_case().execute([self.marked("a:b", "BM-8")])
        both = self.use_case().execute([self.marked("a/b", "BM-7"), self.marked("a:b", "BM-8")])
        self.assertEqual([t for t, _ in both.generated], ["a/b"])       # a:b 已存在 → 略過
        self.assertEqual([t for t, _ in both.skipped], ["a:b"])
        self.assertEqual(len(alone.generated), 1)

    def test_a_dot_only_book_title_cannot_write_outside_the_output_folder(self):
        self.write_batch("點點_20260101_000000.json", "..", [("卡", "BM-5")])
        result = self.use_case().execute([self.marked("卡", "BM-5")])
        self.assertEqual(len(result.generated), 1)
        path = os.path.realpath(result.generated[0][1])
        self.assertTrue(path.startswith(os.path.realpath(self.out_dir) + os.sep), path)

    def test_a_failed_replace_cleans_up_its_temp_file(self):
        from unittest import mock
        with mock.patch("src.application.use_cases.make_card_infographic_use_case.os.replace",
                        side_effect=OSError("disk full")):
            result = self.use_case().execute([self.marked()])
        self.assertEqual(len(result.failed), 1)
        folder = os.path.join(self.out_dir, BOOK)
        self.assertEqual(os.listdir(folder) if os.path.isdir(folder) else [], [])

    def test_no_temp_files_are_left_behind(self):
        self.use_case().execute([self.marked()])
        leftovers = [f for f in os.listdir(os.path.join(self.out_dir, BOOK)) if not f.endswith(".html")]
        self.assertEqual(leftovers, [])


class TestDryRun(_Case):
    def test_dry_run_plans_without_calling_the_model_or_writing(self):
        uc = self.use_case()
        result = uc.execute([self.marked(), self.marked("手動卡", "")], dry_run=True)
        self.assertEqual([t for t, _ in result.planned], ["改變身分"])
        self.assertEqual(len(result.skipped), 1)
        self.assertEqual(result.generated, [])
        self.assertEqual(self.generator.map_calls, [])
        self.assertEqual(self.generator.spec_calls, [])
        self.assertFalse(os.path.exists(os.path.join(self.out_dir, BOOK)))

    def test_dry_run_reports_existing_files_as_skipped(self):
        self.use_case().execute([self.marked()])
        result = self.use_case().execute([self.marked()], dry_run=True)
        self.assertEqual(result.planned, [])
        self.assertIn("--force", result.skipped[0][1])


if __name__ == "__main__":
    unittest.main()
