"""Tests for tools/fix_card_tags.py — Phase 2 T2, re-splitting stored tags.

The tool rewrites files the user cannot regenerate cheaply, so the bar here is
"never lose anything that isn't a glued tag".
"""
import json
import os
import shutil
import tempfile
import unittest

from tools.fix_card_tags import fix_payload, process_dir, resplit_tags


def _payload(cards, rejected=None, **extra):
    data = {
        "book_title": "我的書",
        "created_at": "2026-07-04T12:00:00",
        "uploaded": True,
        "uploaded_at": "2026-07-04T12:05:00",
        "cards": cards,
        "rejected": rejected or [],
    }
    data.update(extra)
    return data


def _card(title="卡片", tags=None, **extra):
    card = {
        "id": "card_1", "title": title, "content": "內容",
        "source_highlight": "劃線", "chapter_reference": "第一章",
        "chapter_progress": 0.5, "source_bookmark_id": "BM-1",
        "tags": list(tags or []), "categories": ["💞心理學"],
    }
    card.update(extra)
    return card


class TestResplitTags(unittest.TestCase):
    """The three formats actually found in cards_output/*.json."""

    def test_fullwidth_colon(self):
        self.assertEqual(resplit_tags(["語言演化：社交結構：謊言藝術"]),
                         ["語言演化", "社交結構", "謊言藝術"])

    def test_em_dash(self):
        self.assertEqual(resplit_tags(["資本結構—負債比率—金融風險"]),
                         ["資本結構", "負債比率", "金融風險"])

    def test_leading_middle_dot(self):
        self.assertEqual(resplit_tags(["・說服論述・故事架構・聽眾心理"]),
                         ["說服論述", "故事架構", "聽眾心理"])

    def test_already_clean_tags_untouched(self):
        self.assertEqual(resplit_tags(["習慣", "複利", "系統思考"]),
                         ["習慣", "複利", "系統思考"])

    def test_partially_glued_list(self):
        self.assertEqual(resplit_tags(["習慣", "複利-一致性"]),
                         ["習慣", "複利", "一致性"])

    def test_idempotent(self):
        once = resplit_tags(["語言演化：社交結構：謊言藝術"])
        self.assertEqual(resplit_tags(once), once)

    def test_empty_and_missing(self):
        self.assertEqual(resplit_tags([]), [])
        self.assertEqual(resplit_tags(None), [])

    def test_prose_tag_is_cleared(self):
        self.assertEqual(
            resplit_tags(["這是一句完全沒有分隔符號而且長到不可能是概念標籤的句子"]), [])


class TestFixPayload(unittest.TestCase):
    def test_reports_and_applies_changes(self):
        data = _payload([_card(tags=["語言演化：社交結構"])])
        changes = fix_payload(data)
        self.assertEqual(len(changes), 1)
        title, old, new = changes[0]
        self.assertEqual(old, ["語言演化：社交結構"])
        self.assertEqual(new, ["語言演化", "社交結構"])
        self.assertEqual(data["cards"][0]["tags"], ["語言演化", "社交結構"])

    def test_clean_payload_reports_nothing(self):
        data = _payload([_card(tags=["習慣", "複利"])])
        self.assertEqual(fix_payload(data), [])

    def test_rejected_cards_also_fixed(self):
        data = _payload([], rejected=[_card(title="被退回", tags=["A：B"])])
        changes = fix_payload(data)
        self.assertEqual([c[0] for c in changes], ["被退回"])
        self.assertEqual(data["rejected"][0]["tags"], ["A", "B"])

    def test_every_other_field_survives(self):
        data = _payload(
            [_card(tags=["A：B"], review_scores={"consistency": 4},
                   review_status="passed")],
            extra_key="must survive",
        )
        fix_payload(data)
        self.assertTrue(data["uploaded"])
        self.assertEqual(data["uploaded_at"], "2026-07-04T12:05:00")
        self.assertEqual(data["extra_key"], "must survive")
        card = data["cards"][0]
        self.assertEqual(card["content"], "內容")
        self.assertEqual(card["categories"], ["💞心理學"])
        self.assertEqual(card["review_scores"], {"consistency": 4})
        self.assertEqual(card["review_status"], "passed")

    def test_missing_cards_key_is_not_an_error(self):
        self.assertEqual(fix_payload({"book_title": "x"}), [])

    def test_non_dict_entries_skipped(self):
        data = _payload(["不是卡片", _card(tags=["A：B"])])
        self.assertEqual(len(fix_payload(data)), 1)


class TestProcessDir(unittest.TestCase):
    def setUp(self):
        self._dir = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self._dir, ignore_errors=True)

    def _write(self, name, data):
        path = os.path.join(self._dir, name)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        return path

    def _read(self, path):
        with open(path, encoding="utf-8") as f:
            return json.load(f)

    def test_dry_run_leaves_files_alone(self):
        path = self._write("a.json", _payload([_card(tags=["A：B"])]))
        stats = process_dir(self._dir, dry_run=True)
        self.assertEqual(stats["cards_changed"], 1)
        self.assertEqual(self._read(path)["cards"][0]["tags"], ["A：B"])

    def test_real_run_writes_back(self):
        path = self._write("a.json", _payload([_card(tags=["A：B"])]))
        stats = process_dir(self._dir, dry_run=False)
        self.assertEqual(stats["files_changed"], 1)
        self.assertEqual(self._read(path)["cards"][0]["tags"], ["A", "B"])

    def test_rerun_is_a_no_op(self):
        self._write("a.json", _payload([_card(tags=["A：B"])]))
        process_dir(self._dir, dry_run=False)
        stats = process_dir(self._dir, dry_run=False)
        self.assertEqual(stats["cards_changed"], 0)
        self.assertEqual(stats["files_changed"], 0)

    def test_no_temp_files_left_behind(self):
        self._write("a.json", _payload([_card(tags=["A：B"])]))
        process_dir(self._dir, dry_run=False)
        self.assertEqual(sorted(os.listdir(self._dir)), ["a.json"])

    def test_emptied_tags_are_counted_separately(self):
        self._write("a.json", _payload([_card(tags=["這是一句長到不可能是概念標籤的句子"])]))
        stats = process_dir(self._dir, dry_run=True)
        self.assertEqual(stats["emptied"], 1)

    def test_unreadable_file_does_not_stop_the_run(self):
        with open(os.path.join(self._dir, "broken.json"), "w", encoding="utf-8") as f:
            f.write("{ not json")
        good = self._write("good.json", _payload([_card(tags=["A：B"])]))
        stats = process_dir(self._dir, dry_run=False)
        self.assertEqual(stats["unreadable"], 1)
        self.assertEqual(self._read(good)["cards"][0]["tags"], ["A", "B"])

    def test_non_json_files_ignored(self):
        with open(os.path.join(self._dir, "notes.txt"), "w", encoding="utf-8") as f:
            f.write("hello")
        stats = process_dir(self._dir, dry_run=True)
        self.assertEqual(stats["files"], 0)

    def test_missing_directory_is_reported_not_raised(self):
        stats = process_dir(os.path.join(self._dir, "nope"), dry_run=True)
        self.assertEqual(stats["files"], 0)


if __name__ == "__main__":
    unittest.main()
