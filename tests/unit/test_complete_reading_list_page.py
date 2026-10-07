"""CompleteReadingListPageUseCase — 只補 integration 建的頁、只補空白處、重跑冪等。"""
import unittest
from unittest import mock

from src.application.use_cases import complete_reading_list_page_use_case as uc_module
from src.application.use_cases.complete_reading_list_page_use_case import (
    CompleteReadingListPageUseCase,
)
from src.config.settings import DEFAULT_BOOK_TYPE_MAPPING
from src.domain.entities.book import Book
from src.domain.entities.book_card import BookCard
from src.infrastructure.notion.reading_list_page_blocks import (
    SECTION_NOTES,
    SECTIONS,
    block_text,
)
from src.infrastructure.notion.reading_list_repository import BOOK_TYPE_PROPERTY

COVER = "https://cdn.kobo.com/book-images/img-1/353/569/90/False/image.jpg"
BOOK = Book(id="b1", title="多巴胺國度", author="安娜．蘭布克", image_id="img-1")


def _page(cover=None, icon=None, types=None, with_type_prop=True):
    props = {}
    if with_type_prop:
        props[BOOK_TYPE_PROPERTY] = {"type": "relation", "relation": list(types or [])}
    return {"id": "rl-1", "cover": cover, "icon": icon,
            "created_by": {"id": "bot"}, "properties": props}


class _FakeReadingList:
    def __init__(self, page, blocks=None, bot=True, type_ids=None, types_available=True):
        self.page = page
        self.blocks = list(blocks or [])
        self.bot = bot
        self.type_ids = type_ids if type_ids is not None else {"Psychology": "t-psy"}
        self.types_available = types_available
        self.appended = []
        self.updates = []

    def find_page(self, title, source_page_id=None):
        return self.page

    def is_created_by_integration(self, page):
        return self.bot

    def book_types_available(self):
        return self.types_available

    def list_blocks(self, page_id):
        return list(self.blocks)

    def append_blocks(self, page_id, blocks, after=None):
        self.appended.append(blocks)
        created = []
        for block in blocks:
            new = dict(block)
            new["id"] = f"blk-{len(self.blocks)}"
            self.blocks.append(new)
            created.append(new)
        return created

    def update_page(self, page_id, properties=None, cover_url=None, icon_url=None):
        self.updates.append({"properties": properties, "cover_url": cover_url,
                             "icon_url": icon_url})
        if cover_url:
            self.page["cover"] = {"type": "external"}
        if icon_url:
            self.page["icon"] = {"type": "external"}
        if properties:
            self.page["properties"].update(
                {k: {"type": "relation", "relation": v["relation"]}
                 for k, v in properties.items()})

    def type_page_ids(self, names):
        return {n: self.type_ids[n] for n in names if n in self.type_ids}


class _FakeViews:
    """建立成功時在「筆記圖」標題後插入一個 child_database block，模擬真實頁面。"""

    def __init__(self, reading_list, fail=False):
        self.rl = reading_list
        self.fail = fail
        self.calls = []

    def create_card_gallery(self, page_id, cards_database_id, book_page_id, after_block_id):
        self.calls.append((page_id, cards_database_id, book_page_id, after_block_id))
        if self.fail:
            raise RuntimeError("views api down")
        index = next(i for i, b in enumerate(self.rl.blocks) if b.get("id") == after_block_id)
        self.rl.blocks.insert(index + 1, {"type": "child_database", "id": "db-1"})
        return "view-1"


class _FakeCards:
    def __init__(self, cards):
        self.cards = cards
        self.calls = 0

    def list_book_cards(self, books_page_id):
        self.calls += 1
        return list(self.cards)


class _FakeCover:
    def __init__(self, url=COVER):
        self.url = url
        self.calls = 0

    def find(self, book):
        self.calls += 1
        return self.url


def _psych_cards():
    return [BookCard(page_id=f"c{i}", title="卡", tags=["💞心理學"]) for i in range(3)]


def _use_case(rl, views=None, cards=None, cover=COVER, cards_db="cards-db"):
    return CompleteReadingListPageUseCase(
        reading_list=rl,
        card_repo=cards if cards is not None else _FakeCards(_psych_cards()),
        views=views,
        cover_finder=_FakeCover(cover),
        cards_database_id=cards_db,
        type_mapping=dict(DEFAULT_BOOK_TYPE_MAPPING),
    )


def _heading(text):
    return {"type": "heading_2", "id": f"h-{text}", "heading_2": {"rich_text": [{"plain_text": text}]}}


class TestCompleteReadingListPage(unittest.TestCase):
    def test_blank_page_gets_skeleton_gallery_cover_and_type(self):
        rl = _FakeReadingList(_page())
        views = _FakeViews(rl)
        _use_case(rl, views).execute(BOOK, "kobo-1")

        self.assertEqual(len(rl.appended), 1)
        headings = [block_text(b) for b in rl.appended[0] if b["type"] == "heading_2"]
        self.assertEqual(headings, list(SECTIONS))
        notes_id = next(b["id"] for b in rl.blocks if block_text(b) == SECTION_NOTES)
        self.assertEqual(views.calls, [("rl-1", "cards-db", "rl-1", notes_id)])
        self.assertIn({"properties": None, "cover_url": COVER, "icon_url": COVER}, rl.updates)
        self.assertIn(
            {"properties": {BOOK_TYPE_PROPERTY: {"relation": [{"id": "t-psy"}]}},
             "cover_url": None, "icon_url": None},
            rl.updates)

    def test_blank_page_logs_decision_before_writing(self):
        """F4：空白頁的決定要在 append_blocks 之前記 log，不是寫完才回報。"""
        rl = _FakeReadingList(_page())
        views = _FakeViews(rl)
        order = []
        original_append = rl.append_blocks

        def tracking_append(page_id, blocks, after=None):
            order.append("append")
            return original_append(page_id, blocks, after=after)

        rl.append_blocks = tracking_append
        with mock.patch.object(
            uc_module.logger, "info",
            side_effect=lambda msg: order.append(("log", msg)),
        ):
            _use_case(rl, views).execute(BOOK, "kobo-1")

        self.assertEqual(len(order), 2)
        self.assertEqual(order[1], "append")
        self.assertIn("書頁為空白，將寫入版面", order[0][1])

    def test_second_run_is_a_no_op(self):
        rl = _FakeReadingList(_page())
        views = _FakeViews(rl)
        use_case = _use_case(rl, views)
        use_case.execute(BOOK, "kobo-1")
        appended, calls, updates = len(rl.appended), len(views.calls), len(rl.updates)
        use_case.execute(BOOK, "kobo-1")
        self.assertEqual(
            (len(rl.appended), len(views.calls), len(rl.updates)), (appended, calls, updates))

    def test_manual_page_is_never_touched(self):
        rl = _FakeReadingList(_page(), bot=False)
        views = _FakeViews(rl)
        cards = _FakeCards(_psych_cards())
        _use_case(rl, views, cards).execute(BOOK, "kobo-1")
        self.assertEqual((rl.appended, views.calls, rl.updates, cards.calls), ([], [], [], 0))

    def test_page_not_found(self):
        rl = _FakeReadingList(None)
        _use_case(rl, _FakeViews(rl)).execute(BOOK, "kobo-1")
        self.assertEqual((rl.appended, rl.updates), ([], []))

    def test_page_with_user_text_gets_no_skeleton(self):
        user_line = {"type": "paragraph", "id": "u1",
                     "paragraph": {"rich_text": [{"plain_text": "我先寫的一行"}]}}
        rl = _FakeReadingList(_page(), blocks=[user_line])
        views = _FakeViews(rl)
        with self.assertLogs(
            "src.application.use_cases.complete_reading_list_page_use_case", level="WARNING"
        ):
            _use_case(rl, views).execute(BOOK, "kobo-1")
        self.assertEqual(rl.appended, [])
        self.assertEqual(views.calls, [])
        self.assertIn({"properties": None, "cover_url": COVER, "icon_url": COVER}, rl.updates)

    def test_renamed_notes_heading_skips_gallery(self):
        rl = _FakeReadingList(_page(), blocks=[_heading("書籍資料"), _heading("卡片")])
        views = _FakeViews(rl)
        with self.assertLogs(
            "src.application.use_cases.complete_reading_list_page_use_case", level="WARNING"
        ) as logs:
            _use_case(rl, views).execute(BOOK, "kobo-1")
        self.assertEqual(views.calls, [])
        self.assertEqual(rl.appended, [])
        self.assertTrue(any(SECTION_NOTES in line for line in logs.output))

    def test_gallery_failure_does_not_raise_and_is_retried(self):
        rl = _FakeReadingList(_page())
        views = _FakeViews(rl, fail=True)
        use_case = _use_case(rl, views)
        with self.assertLogs(
            "src.application.use_cases.complete_reading_list_page_use_case", level="WARNING"
        ):
            use_case.execute(BOOK, "kobo-1")
        views.fail = False
        use_case.execute(BOOK, "kobo-1")
        self.assertEqual(len(views.calls), 2)
        self.assertEqual(len(rl.appended), 1)

    def test_existing_cover_only_icon_added(self):
        rl = _FakeReadingList(_page(cover={"type": "external"}))
        _use_case(rl, _FakeViews(rl)).execute(BOOK, "kobo-1")
        self.assertIn({"properties": None, "cover_url": None, "icon_url": COVER}, rl.updates)

    def test_no_cover_means_no_image_and_no_cover_update(self):
        rl = _FakeReadingList(_page())
        _use_case(rl, _FakeViews(rl), cover=None).execute(BOOK, "kobo-1")
        self.assertNotIn("image", [b["type"] for b in rl.appended[0]])
        self.assertFalse([u for u in rl.updates if u["cover_url"] or u["icon_url"]])

    def test_existing_type_untouched(self):
        rl = _FakeReadingList(_page(types=[{"id": "t-mkt"}]))
        cards = _FakeCards(_psych_cards())
        _use_case(rl, _FakeViews(rl), cards).execute(BOOK, "kobo-1")
        self.assertEqual(cards.calls, 0)
        self.assertFalse([u for u in rl.updates if u["properties"]])

    def test_type_name_missing_from_type_db_warns(self):
        rl = _FakeReadingList(_page(), type_ids={})
        with self.assertLogs(
            "src.application.use_cases.complete_reading_list_page_use_case", level="WARNING"
        ):
            _use_case(rl, _FakeViews(rl)).execute(BOOK, "kobo-1")
        self.assertFalse([u for u in rl.updates if u["properties"]])

    def test_without_cards_db_no_gallery_and_no_type(self):
        rl = _FakeReadingList(_page())
        views = _FakeViews(rl)
        use_case = CompleteReadingListPageUseCase(
            reading_list=rl, card_repo=None, views=None, cover_finder=_FakeCover(),
            cards_database_id=None, type_mapping=dict(DEFAULT_BOOK_TYPE_MAPPING))
        use_case.execute(BOOK, "kobo-1")
        self.assertEqual(len(rl.appended), 1)
        self.assertEqual(views.calls, [])
        self.assertFalse([u for u in rl.updates if u["properties"]])

    def test_cards_tags_dont_map_to_any_type_warns(self):
        rl = _FakeReadingList(_page())
        views = _FakeViews(rl)
        cards = _FakeCards([BookCard(page_id="c0", title="卡", tags=["🍳料理"])])
        with self.assertLogs(
            "src.application.use_cases.complete_reading_list_page_use_case", level="WARNING"
        ) as logs:
            _use_case(rl, views, cards).execute(BOOK, "kobo-1")
        self.assertTrue(any("都對不到書籍種類" in line for line in logs.output))
        self.assertFalse([u for u in rl.updates if u["properties"]])

    def test_no_cards_no_type_warning(self):
        rl = _FakeReadingList(_page())
        views = _FakeViews(rl)
        cards = _FakeCards([])
        with mock.patch.object(uc_module.logger, "warning") as warn:
            _use_case(rl, views, cards).execute(BOOK, "kobo-1")
        warn.assert_not_called()
        self.assertFalse([u for u in rl.updates if u["properties"]])

    def test_book_types_unavailable_skips_without_reading_cards(self):
        """F2：relation 不可見時直接跳過，不查卡片、不多一條 WARNING。"""
        rl = _FakeReadingList(_page(), types_available=False)
        views = _FakeViews(rl)
        cards = _FakeCards(_psych_cards())
        with mock.patch.object(uc_module.logger, "warning") as warn:
            _use_case(rl, views, cards).execute(BOOK, "kobo-1")
        self.assertEqual(cards.calls, 0)
        warn.assert_not_called()
        self.assertFalse([u for u in rl.updates if u["properties"]])

    def test_page_without_type_property_skips_without_reading_cards(self):
        """F2（Task 9 補測）：頁面屬性完全沒有 Type 書籍種類 欄位時不查卡片。"""
        rl = _FakeReadingList(_page(with_type_prop=False))
        views = _FakeViews(rl)
        cards = _FakeCards(_psych_cards())
        _use_case(rl, views, cards).execute(BOOK, "kobo-1")
        self.assertEqual(cards.calls, 0)
        self.assertFalse([u for u in rl.updates if u["properties"]])


class TestCoverLookupOnlyWhenUsable(unittest.TestCase):
    """F5：封面只在「空白頁」或「cover／icon 缺一」時才查，省掉查了也用不到的呼叫。"""

    @staticmethod
    def _non_blank_blocks():
        return [{"type": "paragraph", "id": "u1",
                "paragraph": {"rich_text": [{"plain_text": "我先寫的一行"}]}}]

    @staticmethod
    def _use_case(rl, cover):
        return CompleteReadingListPageUseCase(
            reading_list=rl, card_repo=_FakeCards(_psych_cards()), views=_FakeViews(rl),
            cover_finder=cover, cards_database_id="cards-db",
            type_mapping=dict(DEFAULT_BOOK_TYPE_MAPPING))

    def test_complete_page_skips_cover_lookup(self):
        rl = _FakeReadingList(
            _page(cover={"type": "external"}, icon={"type": "emoji"}),
            blocks=self._non_blank_blocks())
        cover = _FakeCover()
        self._use_case(rl, cover).execute(BOOK, "kobo-1")
        self.assertEqual(cover.calls, 0)

    def test_blank_page_looks_up_cover(self):
        rl = _FakeReadingList(_page())
        cover = _FakeCover()
        self._use_case(rl, cover).execute(BOOK, "kobo-1")
        self.assertEqual(cover.calls, 1)

    def test_non_blank_page_missing_icon_looks_up_and_writes_icon(self):
        rl = _FakeReadingList(
            _page(cover={"type": "external"}, icon=None),
            blocks=self._non_blank_blocks())
        cover = _FakeCover()
        self._use_case(rl, cover).execute(BOOK, "kobo-1")
        self.assertEqual(cover.calls, 1)
        self.assertIn(
            {"properties": None, "cover_url": None, "icon_url": COVER}, rl.updates)


if __name__ == "__main__":
    unittest.main()
