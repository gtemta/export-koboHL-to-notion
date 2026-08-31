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
    icons_for,
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


class TestBuildUpdateWriteStage(unittest.TestCase):
    """write_stage threads through whether the 卡片盒 DB actually has the
    加工狀態 column yet (see needs_work/build_update's write_stage param).
    Writing it when the column doesn't exist 400s the whole pages.update —
    cover and icon included, since they share one call (Finding 1)."""

    def test_write_stage_false_omits_properties_key_entirely(self):
        upd = build_update(_page(), icon="🧭", write_stage=False)
        self.assertNotIn("properties", upd)
        # cover/icon must still be written — only the stage write is skipped
        self.assertIn("cover", upd)
        self.assertEqual(upd["icon"], {"type": "emoji", "emoji": "🧭"})

    def test_write_stage_false_still_omits_when_stage_already_missing(self):
        # a page with cover+icon already set and no 加工狀態 value: with
        # write_stage=False there is nothing left to write at all.
        page = _page(cover={"external": {"url": "x"}}, icon={"emoji": "🧭"})
        upd = build_update(page, icon="🧭", write_stage=False)
        self.assertEqual(upd, {})

    def test_write_stage_true_unchanged_behaviour(self):
        # explicit write_stage=True must match the pre-existing default
        # behaviour exercised by TestBuildUpdate.test_fills_all_three.
        upd = build_update(_page(), icon="🧭", write_stage=True)
        self.assertEqual(
            upd["properties"][_STAGE_PROPERTY],
            {"select": {"name": _STAGE_UNPROCESSED}},
        )

    def test_write_stage_defaults_to_true(self):
        # existing call sites (and existing tests) call build_update without
        # the new kwarg at all — behaviour must be unchanged for them.
        upd = build_update(_page(), icon="🧭")
        self.assertIn("properties", upd)


class TestNeedsWorkWriteStage(unittest.TestCase):
    def test_stage_only_missing_not_pending_when_write_stage_false(self):
        page = _page(cover={"external": {"url": "x"}}, icon={"emoji": "🧭"})
        self.assertTrue(needs_work(page))  # default: stage counts
        self.assertFalse(needs_work(page, write_stage=False))

    def test_still_pending_when_cover_missing_even_if_write_stage_false(self):
        page = _page(icon={"emoji": "🧭"}, stage=_STAGE_UNPROCESSED)
        self.assertTrue(needs_work(page, write_stage=False))


class _HallucinatingEnhancer:
    """Fake `classify_cards`：把 card.categories 換成跟真實 Notion Tags不同的
    假分類（模擬模型幻覺），並且**確實遵守** `apply_icon_fallback` —— 跟真正
    的 `ZettelkastenLLMEnhancer.classify_cards` 行為一致。這一點是測試有效的
    關鍵：如果 fake 忽略這個旗標，就沒辦法區分「修好的呼叫方式」跟「有 bug
    的呼叫方式」，測試永遠綠燈。
    """

    def __init__(self, bogus_categories=("💼商務",)):
        self.bogus_categories = list(bogus_categories)
        self.calls = []  # 記錄每次呼叫收到的 apply_icon_fallback

    def classify_cards(self, cards, categories, book_title="",
                        *, apply_icon_fallback=True):
        self.calls.append(apply_icon_fallback)
        for card in cards:
            card.categories = list(self.bogus_categories)
            if apply_icon_fallback:
                # 對應正式版行為：在這裡就用剛寫入的假分類把 fallback icon 定案
                # —— 這正是本測試要抓的 bug 來源。
                from zettelkasten_generator import ZettelkastenLLMEnhancer
                card.icon = ZettelkastenLLMEnhancer._fallback_icon(card)
            else:
                card.icon = ""  # 模型（假裝）沒挑到可用的 icon
        return True


class _UnparseableEnhancer:
    """模擬 Ollama 回應解析不出任何 CARD_i 行：分類失敗。"""

    def classify_cards(self, cards, categories, book_title="",
                        *, apply_icon_fallback=True):
        return False


class _RaisingEnhancer:
    """模擬 Ollama 呼叫本身掛掉（連線失敗、timeout 等）。"""

    def classify_cards(self, cards, categories, book_title="",
                        *, apply_icon_fallback=True):
        raise RuntimeError("ollama unreachable")


class TestIconsFor(unittest.TestCase):
    def test_uses_real_categories_not_the_models_hallucinated_ones(self):
        # 真實 Notion Tags 是「心理學」（fallback 預設 🪺）；fake enhancer 幻覺出
        # 「商務」（fallback 預設 🪐）。icons_for 必須在算 fallback 之前把
        # categories 換回真實值，所以結果必須是 🪺，絕不能是 🪐。
        page = _page(tags=("💞心理學",), title="卡片標題", keywords="專注、心流")
        enhancer = _HallucinatingEnhancer(bogus_categories=("💼商務",))

        icons = icons_for(enhancer, [page], ["💞心理學", "💼商務"])

        # 必須關掉 classify_cards 內建的 fallback，才有機會用回真實分類重算
        self.assertEqual(enhancer.calls, [False])
        self.assertEqual(icons, ["🪺"])

    def test_unparseable_response_yields_all_empty_icons(self):
        page = _page()
        icons = icons_for(_UnparseableEnhancer(), [page], ["💞心理學"])
        self.assertEqual(icons, [""])

    def test_enhancer_exception_yields_all_empty_icons_without_propagating(self):
        page = _page()
        icons = icons_for(_RaisingEnhancer(), [page], ["💞心理學"])
        self.assertEqual(icons, [""])


if __name__ == "__main__":
    unittest.main()
