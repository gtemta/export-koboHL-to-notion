"""回填工具的純邏輯：頁面欄位讀取與 pages.update payload 組裝。"""
import unittest

from src.infrastructure.notion.card_visuals import _COVER_BASE
from src.infrastructure.notion.zettelkasten_card_repository import (
    _STAGE_PROPERTY,
    _STAGE_UNPROCESSED,
)
from tools.backfill_card_visuals import (
    build_update,
    card_categories,
    card_keywords,
    card_title,
    missing_cover,
    missing_icon,
    missing_stage,
    needs_work,
)


def _page(cover=None, icon=None, tags=("💞心理學",), title="卡片標題",
          keywords="專注、心流", stage=None):
    props = {
        "標題": {"type": "title",
                 "title": [{"plain_text": title}]},
        "Tags": {"type": "multi_select",
                 "multi_select": [{"name": t} for t in tags]},
        "Key Word": {"type": "rich_text",
                     "rich_text": [{"plain_text": keywords}]},
    }
    if stage is not None:
        props[_STAGE_PROPERTY] = {"type": "select", "select": {"name": stage}}
    return {"id": "page-1", "cover": cover, "icon": icon, "properties": props}


class TestPageReaders(unittest.TestCase):
    def test_title(self):
        self.assertEqual(card_title(_page(title="專注的代價")), "專注的代價")

    def test_title_missing(self):
        self.assertEqual(card_title({"properties": {}}), "")

    def test_keywords(self):
        self.assertEqual(card_keywords(_page()), "專注、心流")

    def test_keywords_missing(self):
        self.assertEqual(card_keywords({"properties": {}}), "")

    def test_categories(self):
        self.assertEqual(card_categories(_page(tags=("💼商務",))), ["💼商務"])

    def test_categories_empty(self):
        self.assertEqual(card_categories(_page(tags=())), [])


class TestMissingChecks(unittest.TestCase):
    def test_missing_cover_true_when_none(self):
        self.assertTrue(missing_cover(_page(cover=None)))

    def test_missing_cover_false_when_present(self):
        page = _page(cover={"type": "external", "external": {"url": "x"}})
        self.assertFalse(missing_cover(page))

    def test_missing_icon_true_when_none(self):
        self.assertTrue(missing_icon(_page(icon=None)))

    def test_missing_icon_false_when_present(self):
        self.assertFalse(missing_icon(_page(icon={"type": "emoji", "emoji": "🧭"})))

    def test_missing_stage_true_when_absent(self):
        self.assertTrue(missing_stage(_page()))

    def test_missing_stage_false_when_set(self):
        self.assertFalse(missing_stage(_page(stage=_STAGE_UNPROCESSED)))

    def test_needs_work_false_when_complete(self):
        page = _page(cover={"external": {"url": "x"}},
                     icon={"emoji": "🧭"}, stage=_STAGE_UNPROCESSED)
        self.assertFalse(needs_work(page))

    def test_needs_work_true_when_any_missing(self):
        self.assertTrue(needs_work(_page(icon={"emoji": "🧭"},
                                         stage=_STAGE_UNPROCESSED)))


class TestBuildUpdate(unittest.TestCase):
    def test_fills_all_three(self):
        upd = build_update(_page(), icon="🧭")
        self.assertEqual(
            upd["cover"]["external"]["url"], _COVER_BASE + "gradients_1.png")
        self.assertEqual(upd["icon"], {"type": "emoji", "emoji": "🧭"})
        self.assertEqual(
            upd["properties"][_STAGE_PROPERTY],
            {"select": {"name": _STAGE_UNPROCESSED}},
        )

    def test_does_not_overwrite_existing_cover(self):
        page = _page(cover={"type": "external", "external": {"url": "keep-me"}})
        self.assertNotIn("cover", build_update(page, icon="🧭"))

    def test_does_not_overwrite_existing_icon(self):
        page = _page(icon={"type": "emoji", "emoji": "🎯"})
        self.assertNotIn("icon", build_update(page, icon="🧭"))

    def test_does_not_overwrite_existing_stage(self):
        page = _page(stage="🌳永久筆記")
        self.assertNotIn("properties", build_update(page, icon="🧭"))

    def test_blank_icon_omitted(self):
        # Ollama 整批失敗時只補 cover，icon 留給下次重跑
        upd = build_update(_page(), icon="")
        self.assertNotIn("icon", upd)
        self.assertIn("cover", upd)

    def test_complete_page_yields_empty_update(self):
        page = _page(cover={"external": {"url": "x"}},
                     icon={"emoji": "🧭"}, stage=_STAGE_UNPROCESSED)
        self.assertEqual(build_update(page, icon="🎯"), {})

    def test_no_category_still_gets_cover(self):
        upd = build_update(_page(tags=()), icon="🧭")
        self.assertTrue(upd["cover"]["external"]["url"].startswith(_COVER_BASE))


if __name__ == "__main__":
    unittest.main()
