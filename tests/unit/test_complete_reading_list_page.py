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

FILE_ID = "file-1"  # 上傳到 Notion 的書封（file_upload id）
KOBO_URL = "https://cdn.kobo.com/book-images/img-1/353/569/90/False/image.jpg"
UC_LOGGER = "src.application.use_cases.complete_reading_list_page_use_case"
BOOK = Book(id="b1", title="多巴胺國度", author="安娜．蘭布克", image_id="img-1")


def _ext(url):
    return {"type": "external", "external": {"url": url}}


def _uploaded():
    return {"type": "file", "file": {"url": "https://prod-files.example/x"}}


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
        self.replaced = []

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

    def replace_image(self, block_id, file_id):
        self.replaced.append((block_id, file_id))
        for block in self.blocks:
            if block.get("id") == block_id:
                block["image"] = _uploaded()

    def update_page(self, page_id, properties=None, cover_file_id=None, icon_file_id=None):
        self.updates.append({"properties": properties, "cover_file_id": cover_file_id,
                             "icon_file_id": icon_file_id})
        if cover_file_id:
            self.page["cover"] = _uploaded()
        if icon_file_id:
            self.page["icon"] = _uploaded()
        if properties:
            self.page["properties"].update(
                {k: {"type": "relation", "relation": v["relation"]}
                 for k, v in properties.items()})

    def type_page_ids(self, names):
        return {n: self.type_ids[n] for n in names if n in self.type_ids}


class _FakeViews:
    """建立成功時在「筆記圖」標題後插入一個 child_database block，模擬真實頁面。"""

    def __init__(self, reading_list, fail=False, events=None):
        self.rl = reading_list
        self.fail = fail
        self.calls = []
        self.events = events if events is not None else []

    def create_card_board(self, page_id, cards_database_id, book_page_id, after_block_id):
        self.events.append("create_card_board")
        self.calls.append((page_id, cards_database_id, book_page_id, after_block_id))
        if self.fail:
            raise RuntimeError("views api down")
        index = next(i for i, b in enumerate(self.rl.blocks) if b.get("id") == after_block_id)
        self.rl.blocks.insert(index + 1, {"type": "child_database", "id": "db-1"})
        return "view-1"


class _FakeCards:
    def __init__(self, cards, events=None, ensure_fails=False):
        self.cards = cards
        self.calls = 0
        self.ensure_calls = 0
        self.ensure_fails = ensure_fails
        self.events = events if events is not None else []

    def ensure_card_board_columns(self):
        self.events.append("ensure_card_board_columns")
        self.ensure_calls += 1
        if self.ensure_fails:
            raise RuntimeError("notion down")
        return []

    def list_book_cards(self, books_page_id):
        self.calls += 1
        return list(self.cards)


class _FakeUploader:
    """None＝哪裡都找不到封面；fail＝找到了但上傳失敗。"""

    def __init__(self, file_id=FILE_ID, fail=False):
        self.file_id = file_id
        self.fail = fail
        self.calls = 0

    def upload(self, book):
        self.calls += 1
        if self.fail:
            raise RuntimeError("upload down")
        return self.file_id


def _psych_cards():
    return [BookCard(page_id=f"c{i}", title="卡", tags=["💞心理學"]) for i in range(3)]


def _use_case(rl, views=None, cards=None, cover=FILE_ID, cards_db="cards-db", uploader=None,
              dry_run=False):
    return CompleteReadingListPageUseCase(
        reading_list=rl,
        card_repo=cards if cards is not None else _FakeCards(_psych_cards()),
        views=views,
        cover_uploader=uploader or _FakeUploader(cover),
        cards_database_id=cards_db,
        type_mapping=dict(DEFAULT_BOOK_TYPE_MAPPING),
        dry_run=dry_run,
    )


def _heading(text):
    return {"type": "heading_2", "id": f"h-{text}", "heading_2": {"rich_text": [{"plain_text": text}]}}


def _user_line():
    return {"type": "paragraph", "id": "u1",
            "paragraph": {"rich_text": [{"plain_text": "我先寫的一行"}]}}


def _image(image, block_id="img-1"):
    return {"type": "image", "id": block_id, "image": image}


class TestCompleteReadingListPage(unittest.TestCase):
    def test_blank_page_gets_skeleton_board_cover_and_type(self):
        rl = _FakeReadingList(_page())
        events = []
        views = _FakeViews(rl, events=events)
        cards = _FakeCards(_psych_cards(), events=events)
        _use_case(rl, views, cards).execute(BOOK, "kobo-1")
        self.assertEqual(events, ["ensure_card_board_columns", "create_card_board"])

        self.assertEqual(len(rl.appended), 1)
        headings = [block_text(b) for b in rl.appended[0] if b["type"] == "heading_2"]
        self.assertEqual(headings, list(SECTIONS))
        image = next(b for b in rl.appended[0] if b["type"] == "image")
        self.assertEqual(image["image"],
                         {"type": "file_upload", "file_upload": {"id": FILE_ID}})
        notes_id = next(b["id"] for b in rl.blocks if block_text(b) == SECTION_NOTES)
        self.assertEqual(views.calls, [("rl-1", "cards-db", "rl-1", notes_id)])
        self.assertIn({"properties": None, "cover_file_id": FILE_ID, "icon_file_id": FILE_ID},
                      rl.updates)
        self.assertIn(
            {"properties": {BOOK_TYPE_PROPERTY: {"relation": [{"id": "t-psy"}]}},
             "cover_file_id": None, "icon_file_id": None},
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
        uploader = _FakeUploader()
        _use_case(rl, views, cards, uploader=uploader).execute(BOOK, "kobo-1")
        self.assertEqual((rl.appended, views.calls, rl.updates, cards.calls), ([], [], [], 0))
        self.assertEqual(uploader.calls, 0)

    def test_page_not_found(self):
        rl = _FakeReadingList(None)
        _use_case(rl, _FakeViews(rl)).execute(BOOK, "kobo-1")
        self.assertEqual((rl.appended, rl.updates), ([], []))

    def test_page_with_user_text_gets_no_skeleton(self):
        rl = _FakeReadingList(_page(), blocks=[_user_line()])
        views = _FakeViews(rl)
        with self.assertLogs(UC_LOGGER, level="WARNING"):
            _use_case(rl, views).execute(BOOK, "kobo-1")
        self.assertEqual(rl.appended, [])
        self.assertEqual(views.calls, [])
        self.assertIn({"properties": None, "cover_file_id": FILE_ID, "icon_file_id": FILE_ID},
                      rl.updates)

    def test_dry_run_never_creates_columns(self):
        rl = _FakeReadingList(_page())
        views = _FakeViews(rl)
        cards = _FakeCards(_psych_cards())
        _use_case(rl, views, cards, dry_run=True).execute(BOOK, "kobo-1")
        self.assertEqual(cards.ensure_calls, 0)
        self.assertEqual(len(views.calls), 1)

    def test_column_failure_skips_board_but_not_other_steps_and_is_retried(self):
        rl = _FakeReadingList(_page())
        views = _FakeViews(rl)
        cards = _FakeCards(_psych_cards(), ensure_fails=True)
        use_case = _use_case(rl, views, cards)
        with self.assertLogs(UC_LOGGER, level="WARNING"):
            use_case.execute(BOOK, "kobo-1")
        self.assertEqual(views.calls, [])
        self.assertTrue([u for u in rl.updates if u["properties"]])
        cards.ensure_fails = False
        use_case.execute(BOOK, "kobo-1")
        self.assertEqual(len(views.calls), 1)

    def test_non_blank_notes_section_is_left_alone(self):
        """既有 gallery 的取代是 Task 7 工具的事；段落有內容就不動。"""
        rl = _FakeReadingList(
            _page(), blocks=[_heading("書籍資料"), _heading("筆記圖"),
                             {"type": "child_database", "id": "db-1"}])
        views = _FakeViews(rl)
        cards = _FakeCards(_psych_cards())
        _use_case(rl, views, cards).execute(BOOK, "kobo-1")
        self.assertEqual((views.calls, cards.ensure_calls), ([], 0))

    def test_renamed_notes_heading_skips_board(self):
        rl = _FakeReadingList(_page(), blocks=[_heading("書籍資料"), _heading("卡片")])
        views = _FakeViews(rl)
        with self.assertLogs(UC_LOGGER, level="WARNING") as logs:
            _use_case(rl, views).execute(BOOK, "kobo-1")
        self.assertEqual(views.calls, [])
        self.assertEqual(rl.appended, [])
        self.assertTrue(any(SECTION_NOTES in line for line in logs.output))

    def test_board_failure_does_not_raise_and_is_retried(self):
        rl = _FakeReadingList(_page())
        views = _FakeViews(rl, fail=True)
        use_case = _use_case(rl, views)
        with self.assertLogs(UC_LOGGER, level="WARNING"):
            use_case.execute(BOOK, "kobo-1")
        views.fail = False
        use_case.execute(BOOK, "kobo-1")
        self.assertEqual(len(views.calls), 2)
        self.assertEqual(len(rl.appended), 1)

    def test_existing_cover_only_icon_added(self):
        rl = _FakeReadingList(_page(cover=_uploaded()))
        _use_case(rl, _FakeViews(rl)).execute(BOOK, "kobo-1")
        self.assertIn({"properties": None, "cover_file_id": None, "icon_file_id": FILE_ID},
                      rl.updates)

    def test_no_cover_means_no_image_and_no_cover_update(self):
        rl = _FakeReadingList(_page())
        _use_case(rl, _FakeViews(rl), cover=None).execute(BOOK, "kobo-1")
        self.assertNotIn("image", [b["type"] for b in rl.appended[0]])
        self.assertFalse([u for u in rl.updates if u["cover_file_id"] or u["icon_file_id"]])

    def test_existing_type_untouched(self):
        rl = _FakeReadingList(_page(types=[{"id": "t-mkt"}]))
        cards = _FakeCards(_psych_cards())
        _use_case(rl, _FakeViews(rl), cards).execute(BOOK, "kobo-1")
        self.assertEqual(cards.calls, 0)
        self.assertFalse([u for u in rl.updates if u["properties"]])

    def test_type_name_missing_from_type_db_warns(self):
        rl = _FakeReadingList(_page(), type_ids={})
        with self.assertLogs(UC_LOGGER, level="WARNING"):
            _use_case(rl, _FakeViews(rl)).execute(BOOK, "kobo-1")
        self.assertFalse([u for u in rl.updates if u["properties"]])

    def test_without_cards_db_no_board_and_no_type(self):
        rl = _FakeReadingList(_page())
        views = _FakeViews(rl)
        use_case = CompleteReadingListPageUseCase(
            reading_list=rl, card_repo=None, views=None, cover_uploader=_FakeUploader(),
            cards_database_id=None, type_mapping=dict(DEFAULT_BOOK_TYPE_MAPPING))
        use_case.execute(BOOK, "kobo-1")
        self.assertEqual(len(rl.appended), 1)
        self.assertEqual(views.calls, [])
        self.assertFalse([u for u in rl.updates if u["properties"]])

    def test_cards_tags_dont_map_to_any_type_warns(self):
        rl = _FakeReadingList(_page())
        views = _FakeViews(rl)
        cards = _FakeCards([BookCard(page_id="c0", title="卡", tags=["🍳料理"])])
        with self.assertLogs(UC_LOGGER, level="WARNING") as logs:
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
    """F5：封面只在「空白頁」或「cover／icon 缺一」時才查（現在還要上傳），
    省掉查了也用不到的呼叫。"""

    @staticmethod
    def _use_case(rl, uploader):
        return CompleteReadingListPageUseCase(
            reading_list=rl, card_repo=_FakeCards(_psych_cards()), views=_FakeViews(rl),
            cover_uploader=uploader, cards_database_id="cards-db",
            type_mapping=dict(DEFAULT_BOOK_TYPE_MAPPING))

    def test_complete_page_skips_cover_lookup(self):
        rl = _FakeReadingList(
            _page(cover=_uploaded(), icon={"type": "emoji", "emoji": "📚"}),
            blocks=[_user_line()])
        uploader = _FakeUploader()
        self._use_case(rl, uploader).execute(BOOK, "kobo-1")
        self.assertEqual(uploader.calls, 0)

    def test_blank_page_looks_up_cover(self):
        rl = _FakeReadingList(_page())
        uploader = _FakeUploader()
        self._use_case(rl, uploader).execute(BOOK, "kobo-1")
        self.assertEqual(uploader.calls, 1)

    def test_non_blank_page_missing_icon_looks_up_and_writes_icon(self):
        rl = _FakeReadingList(_page(cover=_uploaded(), icon=None), blocks=[_user_line()])
        uploader = _FakeUploader()
        self._use_case(rl, uploader).execute(BOOK, "kobo-1")
        self.assertEqual(uploader.calls, 1)
        self.assertIn(
            {"properties": None, "cover_file_id": None, "icon_file_id": FILE_ID}, rl.updates)


class TestUnusableKoboCdnVisuals(unittest.TestCase):
    """Kobo 圖床會擋 Notion 的伺服器：舊版寫成外部網址的封面／icon／圖片 block 在
    Notion 裡都是「Permission denied」，要換成上傳的書封。使用者自己換的不碰。"""

    def test_kobo_cdn_cover_and_icon_are_replaced(self):
        rl = _FakeReadingList(
            _page(cover=_ext(KOBO_URL), icon=_ext(KOBO_URL)), blocks=[_user_line()])
        _use_case(rl).execute(BOOK, "kobo-1")
        self.assertIn({"properties": None, "cover_file_id": FILE_ID, "icon_file_id": FILE_ID},
                      rl.updates)

    def test_only_the_broken_slot_is_replaced(self):
        rl = _FakeReadingList(
            _page(cover=_ext(KOBO_URL), icon={"type": "emoji", "emoji": "📚"}),
            blocks=[_user_line()])
        _use_case(rl).execute(BOOK, "kobo-1")
        self.assertIn({"properties": None, "cover_file_id": FILE_ID, "icon_file_id": None},
                      rl.updates)

    def test_user_set_cover_and_icon_are_left_alone(self):
        rl = _FakeReadingList(
            _page(cover=_ext("https://example.com/mine.jpg"),
                  icon={"type": "emoji", "emoji": "📚"}),
            blocks=[_user_line()])
        uploader = _FakeUploader()
        _use_case(rl, uploader=uploader).execute(BOOK, "kobo-1")
        self.assertEqual(uploader.calls, 0)
        self.assertFalse([u for u in rl.updates if u["cover_file_id"] or u["icon_file_id"]])

    def test_broken_image_block_is_replaced_in_place(self):
        rl = _FakeReadingList(
            _page(cover=_uploaded(), icon=_uploaded()),
            blocks=[_heading("書籍資料"), _image(_ext(KOBO_URL)), _heading("筆記圖")])
        _use_case(rl).execute(BOOK, "kobo-1")
        self.assertEqual(rl.replaced, [("img-1", FILE_ID)])
        self.assertEqual(rl.appended, [])
        self.assertFalse([u for u in rl.updates if u["cover_file_id"] or u["icon_file_id"]])

    def test_repaired_image_block_is_not_touched_again(self):
        rl = _FakeReadingList(
            _page(cover=_uploaded(), icon=_uploaded()),
            blocks=[_heading("書籍資料"), _image(_ext(KOBO_URL)), _heading("筆記圖")])
        use_case = _use_case(rl)
        use_case.execute(BOOK, "kobo-1")
        use_case.execute(BOOK, "kobo-1")
        self.assertEqual(len(rl.replaced), 1)

    def test_uploaded_or_user_pasted_image_is_left_alone(self):
        for image in (_uploaded(), _ext("https://example.com/mine.jpg")):
            rl = _FakeReadingList(
                _page(cover=_uploaded(), icon=_uploaded()),
                blocks=[_heading("書籍資料"), _image(image), _heading("筆記圖")])
            uploader = _FakeUploader()
            _use_case(rl, uploader=uploader).execute(BOOK, "kobo-1")
            self.assertEqual((rl.replaced, uploader.calls), ([], 0))


class TestUploadFailure(unittest.TestCase):
    """上傳失敗（網路、Notion 暫時拒絕）不可留下半成品，也不可拖垮整輪同步。"""

    def test_blank_page_writes_nothing_so_the_cover_image_is_not_lost_for_good(self):
        """骨架只寫在空白頁；若上傳失敗還是寫了沒有圖的骨架，頁面就不再空白，
        書封圖永遠補不回來。所以整本書這輪跳過，下次同步重試。"""
        rl = _FakeReadingList(_page())
        uploader = _FakeUploader(fail=True)
        with self.assertLogs(UC_LOGGER, level="WARNING") as logs:
            _use_case(rl, uploader=uploader).execute(BOOK, "kobo-1")
        self.assertTrue(any("封面上傳失敗" in line for line in logs.output))
        self.assertEqual((rl.appended, rl.updates), ([], []))

        uploader.fail = False
        _use_case(rl, uploader=uploader).execute(BOOK, "kobo-1")
        image = next(b for b in rl.appended[0] if b["type"] == "image")
        self.assertEqual(image["image"]["file_upload"]["id"], FILE_ID)

    def test_existing_page_still_gets_its_other_steps(self):
        rl = _FakeReadingList(
            _page(cover=_ext(KOBO_URL)),
            blocks=[_heading("書籍資料"), _heading("筆記圖")])
        views = _FakeViews(rl)
        with self.assertLogs(UC_LOGGER, level="WARNING"):
            _use_case(rl, views, uploader=_FakeUploader(fail=True)).execute(BOOK, "kobo-1")
        self.assertEqual(len(views.calls), 1)
        self.assertTrue([u for u in rl.updates if u["properties"]])
        self.assertFalse([u for u in rl.updates if u["cover_file_id"] or u["icon_file_id"]])
        self.assertEqual(rl.replaced, [])


if __name__ == "__main__":
    unittest.main()
