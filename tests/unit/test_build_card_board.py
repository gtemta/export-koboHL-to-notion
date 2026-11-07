"""BuildCardBoardUseCase 與 tools/build_card_board.py：Notion、Kobo、模型全以假物件取代。"""
import os
import unittest
from dataclasses import replace
from unittest import mock

from src.application.dtos.card_board_report import CardBoardReport
from src.application.use_cases import build_card_board_use_case as uc_module
from src.application.use_cases.build_card_board_use_case import BuildCardBoardUseCase
from src.domain.entities.board_card import BoardCard
from tools.build_card_board import card_map_model, format_report, run

CARDS_DB = "cards-db"
UC_LOGGER = "src.application.use_cases.build_card_board_use_case"
NOTES_HEADING = {"id": "h-notes", "type": "heading_2",
                 "heading_2": {"rich_text": [{"plain_text": "筆記圖"}]}}
NEXT_HEADING = {"id": "h-next", "type": "heading_2",
                "heading_2": {"rich_text": [{"plain_text": "概要"}]}}


def card(page_id, book="bk1", role="", order=None, related=(), complete=True, created="2026-01-01"):
    return BoardCard(
        page_id=page_id, book_page_id=book, title=f"卡{page_id}", source_id=f"s-{page_id}",
        created_time=created + f"-{page_id}", role=role, reading_order=order,
        related_ids=tuple(related), related_complete=complete)


def filled(page_id, book="bk1", order=10):
    return card(page_id, book, role="案例", order=order)


class _FakeCards:
    def __init__(self, cards, read_only=False):
        self.cards = list(cards)
        self.read_only = read_only
        self.written = {}
        self.ensure_calls = 0
        self.text_calls = 0

    def ensure_card_board_columns(self):
        if self.read_only:
            raise AssertionError("dry run must not create columns")
        self.ensure_calls += 1
        return []

    def list_board_cards(self):
        return list(self.cards)

    def card_text(self, page_id):
        self.text_calls += 1
        return f"內文{page_id}"

    def update_board_fields(self, update):
        if self.read_only:
            raise AssertionError("dry run must not write")
        self.written[update.page_id] = update


class _FakeReadingList:
    def __init__(self, pages, section_body=None, no_section=False):
        self.pages = pages
        self.section_body = [] if section_body is None else section_body
        self.no_section = no_section

    def list_pages(self):
        return list(self.pages)

    @staticmethod
    def page_title(page):
        return page["title"]

    def is_created_by_integration(self, page):
        return page.get("bot", True)

    def list_blocks(self, page_id):
        if self.no_section:
            return [NEXT_HEADING]
        return [NOTES_HEADING, *self.section_body, NEXT_HEADING]


class _FakeViews:
    def __init__(self, read_only=False, swap=None):
        self.read_only = read_only
        self.calls = []
        self.swap = swap

    def create_card_board(self, page_id, cards_database_id, book_page_id, after_block_id):
        if self.read_only:
            raise AssertionError("dry run must not create a board")
        self.calls.append(("create_card_board", page_id, cards_database_id, book_page_id,
                           after_block_id))
        return "view-1"

    def swap_gallery_for_board(self, linked_database_id, cards_database_id, book_page_id):
        if self.read_only:
            raise AssertionError("dry run must not swap")
        self.calls.append(("swap_gallery_for_board", linked_database_id, cards_database_id,
                           book_page_id))
        return True

    def describe_swap(self, linked_database_id):
        from src.infrastructure.notion.notion_views_client import ViewSwap
        return self.swap or ViewSwap(add_board=True, delete_gallery_id="g1")

    def calls_for(self, page_id):
        return [c for c in self.calls if page_id in c[1:]]


class _FakePositions:
    def __init__(self, order):
        self.order = list(order)   # page ids in book order
        self.calls = []

    def positions_for(self, source_ids):
        self.calls.append(list(source_ids))
        return {f"s-{pid}": (0, float(i)) for i, pid in enumerate(self.order)
                if f"s-{pid}" in source_ids}


def good(links=()):
    """依該次收到的清單順序把 page id 轉成編號，產生涵蓋全部卡的 JSON。"""
    def build(listing_ids):
        number = {pid: i + 1 for i, pid in enumerate(listing_ids)}
        cards = [{"n": number[pid], "role": "支柱",
                  "neighbors": [{"n": number[o]} for a, o in links if a == pid]}
                 for pid in listing_ids]
        return {"cards": cards}
    return build


class _FakeGenerator:
    model = "gemma4:12b"

    def __init__(self, replies=None, available=True):
        self.replies = list(replies) if replies is not None else None
        self.available = available
        self.calls = 0
        self.listings = []

    def is_available(self):
        return self.available

    def ask_book_map(self, book_title, cards):
        self.calls += 1
        ids = [c.page_id for c in cards]
        self.listings.append(ids)
        for c in cards:
            assert c.content, "card text must be filled before asking the model"
        reply = good([("a", "b")]) if self.replies is None else (
            self.replies.pop(0) if self.replies else None)
        return reply(ids) if reply else None


BOOK_ORDER_IDS = ["c", "e", "a", "d", "b"]


def build(cards=None, replies=None, available=True, pages=None, section_body=None,
          no_section=False, read_only=False, swap=None):
    cards = cards if cards is not None else [card(x) for x in "abcde"]
    pages = pages if pages is not None else [{"id": "bk1", "title": "書一"}]
    fakes = {
        "cards": _FakeCards(cards, read_only=read_only),
        "reading_list": _FakeReadingList(pages, section_body, no_section),
        "views": _FakeViews(read_only=read_only, swap=swap),
        "positions": _FakePositions(BOOK_ORDER_IDS),
        "generator": _FakeGenerator(replies, available),
    }
    use_case = BuildCardBoardUseCase(cards_database_id=CARDS_DB, **fakes)
    return use_case, fakes


def two_book_world(first_book_replies):
    first = [card(x, "bk1") for x in "abc"]
    second = [card(x, "bk2") for x in "def"]
    replies = list(first_book_replies) + [good(), good()]
    pages = [{"id": "bk1", "title": "書一"}, {"id": "bk2", "title": "書二"}]
    return build(cards=first + second, replies=replies, pages=pages)


class TestModelRuns(unittest.TestCase):
    def test_two_runs_write_only_links_seen_twice(self):
        cards = [card(x) for x in "abc"]
        use_case, fakes = build(cards=cards, replies=[
            good([("a", "b"), ("b", "c")]), good([("a", "b")])])
        report = use_case.execute()
        written = fakes["cards"].written
        self.assertEqual(written["a"].related_ids, ("b",))
        self.assertEqual(written["b"].related_ids, ("a",))
        self.assertIsNone(written["c"].related_ids)
        self.assertEqual(report.failed, [])

    def test_second_listing_is_shuffled_and_first_is_book_order(self):
        use_case, fakes = build()
        use_case.execute()
        first, second = fakes["generator"].listings
        self.assertEqual(first, BOOK_ORDER_IDS)
        self.assertNotEqual(second, BOOK_ORDER_IDS)
        self.assertEqual(set(second), set(BOOK_ORDER_IDS))

    def test_each_model_call_gets_a_second_attempt(self):
        use_case, fakes = build(replies=[None, good(), good()])
        report = use_case.execute()
        self.assertEqual(fakes["generator"].calls, 3)
        self.assertEqual(report.failed, [])

    def test_second_run_failing_twice_fails_the_book_without_writes(self):
        use_case, fakes = build(replies=[good(), None, None])
        report = use_case.execute()
        self.assertEqual(fakes["generator"].calls, 3)
        self.assertEqual([t for t, _ in report.failed], ["書一"])
        self.assertEqual(fakes["cards"].written, {})
        self.assertEqual(fakes["views"].calls, [])
        self.assertEqual(report.processed, [])

    def test_failed_map_writes_nothing_and_other_books_continue(self):
        use_case, fakes = two_book_world([None, None])
        report = use_case.execute()
        self.assertEqual([t for t, _ in report.failed], ["書一"])
        self.assertEqual(set(fakes["cards"].written), {"d", "e", "f"})
        self.assertEqual(fakes["views"].calls_for("bk1"), [])
        self.assertEqual([t for t, _ in report.processed], ["書二"])

    def test_text_is_read_for_every_card_of_a_book_that_needs_the_model(self):
        cards = [filled("a"), filled("b"), card("c"), card("d")]
        use_case, fakes = build(cards=cards)
        use_case.execute()
        self.assertEqual(fakes["cards"].text_calls, 4)
        self.assertEqual(len(fakes["generator"].listings[0]), 4)

    def test_small_book_skips_the_model_but_still_orders_by_book(self):
        cards = [card("d"), card("e")]
        use_case, fakes = build(cards=cards)
        use_case.execute()
        self.assertEqual(fakes["generator"].calls, 0)
        written = fakes["cards"].written
        self.assertEqual({u.role for u in written.values()}, {"案例"})
        # 書中順序 e 在 d 之前，與建立時間（d 先）相反
        self.assertLess(written["e"].reading_order, written["d"].reading_order)
        self.assertEqual(len(fakes["positions"].calls), 1)


class TestFilledBooks(unittest.TestCase):
    def test_rerun_on_a_filled_book_never_touches_the_model(self):
        cards = [filled(x, order=10 * (i + 1)) for i, x in enumerate("abc")]
        use_case, fakes = build(cards=cards, section_body=[{"type": "child_database", "id": "x"}],
                                swap=None)
        with self.assertLogs(UC_LOGGER, level="INFO") as logs:
            report = use_case.execute()
        self.assertEqual(fakes["generator"].calls, 0)
        self.assertEqual(fakes["cards"].text_calls, 0)
        self.assertEqual(fakes["positions"].calls, [])
        self.assertEqual(fakes["cards"].written, {})
        self.assertEqual(report.untouched, ["書一"])
        self.assertTrue(any("不需跑模型" in line for line in logs.output))

    def test_filled_books_do_not_need_ollama_running(self):
        cards = [filled(x, order=10 * (i + 1)) for i, x in enumerate("abc")]
        use_case, _ = build(cards=cards, available=False, section_body=[{"type": "paragraph"}])
        report = use_case.execute()
        self.assertEqual(report.aborted, "")

    def test_model_unavailable_aborts_before_any_write(self):
        use_case, fakes = build(available=False)
        report = use_case.execute()
        self.assertIn("gemma4", report.aborted)
        self.assertEqual(fakes["cards"].ensure_calls, 0)
        self.assertEqual(fakes["cards"].written, {})
        self.assertEqual(fakes["views"].calls, [])


class TestFixRound1(unittest.TestCase):
    def test_filled_book_with_a_blank_order_gets_no_card_writes(self):
        cards = [filled("a", order=10), filled("b", order=None), filled("c", order=30)]
        use_case, fakes = build(cards=cards, section_body=[{"type": "paragraph"}])
        report = use_case.execute()
        self.assertEqual(fakes["cards"].written, {})
        self.assertEqual(fakes["positions"].calls, [])
        self.assertEqual(report.untouched, ["書一"])
        self.assertEqual(report.processed, [])

    def test_filled_book_still_gets_its_board(self):
        cards = [filled("a"), filled("b", order=None), filled("c")]
        use_case, fakes = build(cards=cards, section_body=[])
        use_case.execute()
        self.assertEqual(fakes["views"].calls[-1][0], "create_card_board")
        self.assertEqual(fakes["cards"].written, {})

    def _stateful(self, fail_on=None):
        """寫入會回存到假的卡片盒，讓重跑看得到上一輪寫了什麼。"""
        use_case, fakes = build()
        cards = fakes["cards"]
        pending = {"fail_on": fail_on}

        def update(upd):
            if upd.page_id == pending["fail_on"]:
                pending["fail_on"] = None
                raise RuntimeError("notion hiccup")
            cards.written[upd.page_id] = upd
            cards.cards = [
                replace(c, role=upd.role or c.role,
                        reading_order=upd.reading_order
                        if upd.reading_order is not None else c.reading_order)
                if c.page_id == upd.page_id else c
                for c in cards.cards]
        cards.update_board_fields = update
        return use_case, cards

    def test_mid_book_failure_then_rerun_gives_the_uninterrupted_orders(self):
        clean_use_case, clean_cards = self._stateful()
        clean_use_case.execute()
        expected = {c.page_id: c.reading_order for c in clean_cards.cards}
        self.assertEqual(expected, {"c": 10, "e": 20, "a": 30, "d": 40, "b": 50})

        use_case, cards = self._stateful(fail_on="a")
        first = use_case.execute()
        self.assertEqual([t for t, _ in first.failed], ["書一"])
        # 失敗前寫下的是書中順序的前綴
        self.assertEqual(set(cards.written), {"c", "e"})
        use_case.execute()
        self.assertEqual({c.page_id: c.reading_order for c in cards.cards}, expected)

    def test_small_book_writes_in_book_order_too(self):
        use_case, fakes = build(cards=[card("d"), card("e")])
        use_case.execute()
        self.assertEqual(list(fakes["cards"].written), ["e", "d"])

    def test_board_creation_returning_none_fails_the_book(self):
        use_case, fakes = build(section_body=[])
        fakes["views"].create_card_board = mock.Mock(return_value=None)
        report = use_case.execute()
        self.assertEqual([t for t, _ in report.failed], ["書一"])
        self.assertEqual(report.processed, [])
        code = run(False, None, use_case=_Stub(report))[1]
        self.assertEqual(code, 1)

    def test_cards_without_a_position_are_warned_about_once_per_book(self):
        cards = [card("a"), card("b"), card("c"), card("x"),
                 replace(card("y"), source_id="")]
        use_case, _ = build(cards=cards)
        with self.assertLogs(UC_LOGGER, level="WARNING") as logs:
            use_case.execute()
        warnings = [line for line in logs.output if "查不到書中位置" in line]
        self.assertEqual(len(warnings), 1)
        self.assertIn("2 張卡", warnings[0])

    def test_no_warning_when_every_card_has_a_position(self):
        use_case, _ = build()
        # assertNoLogs 要 Python 3.10，CI 跑 3.8
        with mock.patch.object(uc_module.logger, "warning") as warn, \
                mock.patch.object(uc_module.logger, "error") as error:
            use_case.execute()
        warn.assert_not_called()
        error.assert_not_called()


class TestBookPage(unittest.TestCase):
    def test_manual_book_page_gets_fields_but_no_board(self):
        use_case, fakes = build(pages=[{"id": "bk1", "title": "書一", "bot": False}])
        use_case.execute()
        self.assertTrue(fakes["cards"].written)
        self.assertEqual(fakes["views"].calls, [])

    def test_blank_section_creates_board(self):
        use_case, fakes = build(section_body=[])
        use_case.execute()
        self.assertEqual(
            fakes["views"].calls[-1],
            ("create_card_board", "bk1", CARDS_DB, "bk1", "h-notes"))

    def test_gallery_in_section_is_swapped(self):
        use_case, fakes = build(section_body=[{"type": "child_database", "id": "linked"}])
        use_case.execute()
        self.assertEqual(fakes["views"].calls[-1],
                         ("swap_gallery_for_board", "linked", CARDS_DB, "bk1"))

    def test_missing_section_warns_and_still_counts_the_fields(self):
        use_case, fakes = build(no_section=True)
        with self.assertLogs(UC_LOGGER, level="WARNING"):
            report = use_case.execute()
        self.assertEqual(fakes["views"].calls, [])
        self.assertEqual([t for t, _ in report.processed], ["書一"])

    def test_board_failure_is_reported_for_that_book_only(self):
        use_case, fakes = two_book_world([good(), good()])
        fakes["views"].create_card_board = mock.Mock(side_effect=RuntimeError("boom"))
        report = use_case.execute()
        self.assertEqual({t for t, _ in report.failed}, {"書一", "書二"})
        self.assertIn("boom", report.failed[0][1])

    def test_board_creation_does_not_make_a_filled_book_processed(self):
        cards = [filled(x, order=10 * (i + 1)) for i, x in enumerate("abc")]
        use_case, fakes = build(cards=cards, section_body=[])
        report = use_case.execute()
        self.assertEqual(report.untouched, ["書一"])
        self.assertEqual(fakes["views"].calls[-1][0], "create_card_board")


class TestGrouping(unittest.TestCase):
    def test_book_filter_limits_processing(self):
        use_case, fakes = two_book_world([good(), good()])
        report = use_case.execute(book_filter="書二")
        self.assertEqual([t for t, _ in report.processed], ["書二"])
        self.assertEqual(set(fakes["cards"].written), {"d", "e", "f"})

    def test_cards_without_source_are_counted_and_skipped(self):
        extra = [card("x", book=""), card("y", book="")]
        use_case, fakes = build(cards=[card(c) for c in "abcde"] + extra)
        report = use_case.execute()
        self.assertEqual(report.no_source_cards, 2)
        self.assertNotIn("x", fakes["cards"].written)

    def test_source_page_missing_from_reading_list_is_failed_without_writes(self):
        use_case, fakes = build(cards=[card("a", "gone"), card("b", "gone"), card("c", "gone")])
        report = use_case.execute()
        self.assertEqual(report.failed, [("gone", "Reading List 找不到這一頁")])
        self.assertEqual(fakes["cards"].written, {})
        self.assertEqual(fakes["generator"].calls, 0)

    def test_unexpected_error_in_one_book_does_not_stop_the_rest(self):
        use_case, fakes = two_book_world([good(), good()])
        original = fakes["cards"].card_text

        def flaky(page_id):
            if page_id == "a":
                raise RuntimeError("notion down")
            return original(page_id)
        fakes["cards"].card_text = flaky
        report = use_case.execute()
        self.assertEqual(report.failed, [("書一", "notion down")])
        self.assertEqual([t for t, _ in report.processed], ["書二"])

    def test_read_failure_propagates(self):
        use_case, fakes = build()
        fakes["cards"].list_board_cards = mock.Mock(side_effect=RuntimeError("401"))
        with self.assertRaises(RuntimeError):
            use_case.execute()


class TestDryRun(unittest.TestCase):
    def test_dry_run_is_read_only(self):
        use_case, fakes = build(read_only=True, section_body=[])
        report = use_case.execute(dry_run=True)
        self.assertEqual(len(report.planned), 1)
        line = report.planned[0]
        self.assertIn("書一", line)
        self.assertIn("5 張", line)
        self.assertIn("新卡 5", line)
        self.assertIn("會跑模型", line)
        self.assertIn("建看板", line)
        self.assertEqual(fakes["generator"].calls, 0)
        self.assertEqual(fakes["cards"].text_calls, 0)
        self.assertEqual(fakes["positions"].calls, [])

    def test_dry_run_describes_a_gallery_swap(self):
        use_case, _ = build(read_only=True,
                            section_body=[{"type": "child_database", "id": "linked"}])
        report = use_case.execute(dry_run=True)
        self.assertIn("取代 gallery", report.planned[0])

    def test_dry_run_reports_an_existing_board(self):
        from src.infrastructure.notion.notion_views_client import ViewSwap
        use_case, _ = build(read_only=True,
                            section_body=[{"type": "child_database", "id": "linked"}],
                            swap=ViewSwap(add_board=False, delete_gallery_id=None))
        report = use_case.execute(dry_run=True)
        self.assertIn("已有看板", report.planned[0])

    def test_dry_run_leaves_a_manual_page_alone(self):
        use_case, _ = build(read_only=True, pages=[{"id": "bk1", "title": "書一", "bot": False}])
        report = use_case.execute(dry_run=True)
        self.assertIn("不動", report.planned[0])

    def test_dry_run_does_not_need_the_model(self):
        use_case, _ = build(read_only=True, available=False)
        report = use_case.execute(dry_run=True)
        self.assertEqual(report.aborted, "")
        self.assertEqual(len(report.planned), 1)


class _Stub:
    def __init__(self, report):
        self.report = report

    def execute(self, book_filter=None, dry_run=False):
        self.args = (book_filter, dry_run)
        return self.report


class TestTool(unittest.TestCase):
    def test_card_map_model_ignores_ollama_model(self):
        with mock.patch.dict(os.environ, {"OLLAMA_MODEL": "qwen3:4b"}, clear=False):
            os.environ.pop("OLLAMA_CARD_MAP_MODEL", None)
            self.assertEqual(card_map_model(), "gemma4:12b")

    def test_card_map_model_can_be_overridden(self):
        with mock.patch.dict(os.environ, {"OLLAMA_CARD_MAP_MODEL": " foo:1b "}, clear=False):
            self.assertEqual(card_map_model(), "foo:1b")

    def test_tool_exit_code_reflects_failures(self):
        self.assertEqual(run(False, None, use_case=_Stub(CardBoardReport()))[1], 0)
        self.assertEqual(
            run(False, None, use_case=_Stub(CardBoardReport(failed=[("書", "x")])))[1], 1)
        self.assertEqual(
            run(False, None, use_case=_Stub(CardBoardReport(aborted="模型沒開")))[1], 1)

    def test_tool_passes_flags_to_the_use_case(self):
        stub = _Stub(CardBoardReport())
        run(True, "主控力", use_case=stub)
        self.assertEqual(stub.args, ("主控力", True))

    def test_tool_turns_a_read_failure_into_exit_1(self):
        class Boom:
            def execute(self, book_filter=None, dry_run=False):
                raise RuntimeError("401 unauthorized")
        text, code = run(False, None, use_case=Boom())
        self.assertEqual(code, 1)
        self.assertIn("401 unauthorized", text)

    def test_missing_database_ids_explain_and_exit_1(self):
        from src.config.settings import Settings
        with mock.patch("tools.build_card_board.Settings.from_env",
                        return_value=Settings(notion_token="t", notion_database_id="d")):
            text, code = run(False, None)
        self.assertEqual(code, 1)
        self.assertIn("NOTION_ZETTELKASTEN_DATABASE_ID", text)

    def test_report_lists_each_section(self):
        report = CardBoardReport(
            planned=["書一：5 張"], processed=[("書二", 3)], untouched=["書三"],
            failed=[("書四", "boom")], no_source_cards=2, aborted="")
        text = format_report(report, dry_run=True)
        for needle in ("書一：5 張", "書二", "書三", "書四", "boom", "2"):
            self.assertIn(needle, text)

    def test_report_shows_abort_message(self):
        text = format_report(CardBoardReport(aborted="模型沒開"), dry_run=False)
        self.assertIn("模型沒開", text)


if __name__ == "__main__":
    unittest.main()
