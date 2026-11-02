"""卡片盒的卡 → 角色／閱讀順序／相關卡片 → 同步建立的書頁換上依角色分欄的看板。

安全順序（任何一步失敗，都不能讓使用者改過的東西被動到）：
  1. 唯讀：讀所有卡與書頁（讀取失敗直接拋出，絕不當成「沒有卡」）；
  2. 有書需要模型但模型不可用 → 整次中止，連欄位都不建；
  3. 逐本、依序處理（只有一個模型、8GB VRAM，不開執行緒池）；單本例外只影響那一本；
  4. 要跑模型的書：兩次詢問（書中順序、洗牌順序）各最多試 2 次，只留兩次都出現的連結；
     任一次最終失敗 → 這本書什麼都不寫、也不動書頁；
  5. 只填空白欄位（見 card_board_rules.plan_book_updates），再處理書頁的看板。

只有「同步自動建立」的書頁才會動看板；使用者手動建的書頁只補卡片欄位。
"""
import logging
from dataclasses import replace
from typing import Dict, List, Optional, Sequence, Tuple

from ...domain.entities.board_card import BoardCard, CardUpdate, MapRun
from ...domain.services.card_board_rules import (
    MIN_CARDS_FOR_MAP,
    merge_map_runs,
    needs_map,
    parse_map_run,
    plan_book_updates,
    shuffled_listing,
    sort_by_book_order,
)
from ...infrastructure.notion.reading_list_page_blocks import (
    SECTION_NOTES,
    find_section,
    section_is_empty,
)
from ..dtos.card_board_report import CardBoardReport

logger = logging.getLogger(__name__)

_ATTEMPTS_PER_RUN = 2
_MISSING_PAGE = "Reading List 找不到這一頁"

Positions = Dict[str, Tuple[int, float]]


class BuildCardBoardUseCase:
    def __init__(self, cards, reading_list, views, positions, generator,
                 cards_database_id: str):
        self._cards = cards
        self._reading_list = reading_list
        self._views = views
        self._positions = positions
        self._generator = generator
        self._cards_database_id = cards_database_id

    def execute(self, book_filter: Optional[str] = None, dry_run: bool = False
                ) -> CardBoardReport:
        report = CardBoardReport()
        # 讀取失敗要拋出（呼叫端據此中止），不能吞掉當成「沒有卡」
        cards = self._cards.list_board_cards()
        pages = {p["id"]: p for p in self._reading_list.list_pages()}
        books = self._group_books(cards, pages, book_filter, report)

        if dry_run:
            for title, page, book_cards in books:
                try:
                    report.planned.append(self._plan_line(title, page, book_cards))
                except Exception as e:  # noqa: BLE001 — 預覽也是單本隔離
                    logger.error(f"《{title}》預覽失敗: {e}")
                    report.failed.append((title, str(e)))
            return report

        if (any(self._wants_model(book_cards) for _, _, book_cards in books)
                and not self._generator.is_available()):
            model = self._generator.model
            report.aborted = (
                f"本地模型 {model} 不可用（Ollama 沒開，或沒有 pull 這個模型）。"
                f"請先啟動 Ollama 並執行 `ollama pull {model}`，"
                "或用 OLLAMA_CARD_MAP_MODEL 指定已安裝的模型後重跑；這次什麼都沒有寫入。")
            return report

        created = self._cards.ensure_card_board_columns()
        if created:
            logger.info(f"已在卡片盒建立欄位：{'、'.join(created)}")

        for title, page, book_cards in books:
            try:
                self._process_book(title, page, book_cards, report)
            except Exception as e:  # noqa: BLE001 — 單本失敗不影響其他書
                logger.error(f"《{title}》處理失敗: {e}", exc_info=True)
                report.failed.append((title, str(e)))
        return report

    # -- 分組 ---------------------------------------------------------------

    def _group_books(self, cards: Sequence[BoardCard], pages: Dict[str, dict],
                     book_filter: Optional[str], report: CardBoardReport
                     ) -> List[Tuple[str, dict, List[BoardCard]]]:
        by_book: Dict[str, List[BoardCard]] = {}
        for card in cards:
            if not card.book_page_id:
                report.no_source_cards += 1
                continue
            by_book.setdefault(card.book_page_id, []).append(card)

        books = []
        for page_id, book_cards in by_book.items():
            page = pages.get(page_id)
            if page is None:
                # 找不到頁就拿不到書名，沒辦法套用書名篩選；只在不篩選時回報
                if not book_filter:
                    report.failed.append((page_id, _MISSING_PAGE))
                continue
            title = self._reading_list.page_title(page)
            if book_filter and book_filter not in title:
                continue
            books.append((title, page, book_cards))
        books.sort(key=lambda b: b[0])
        return books

    @staticmethod
    def _wants_model(cards: Sequence[BoardCard]) -> bool:
        return needs_map(cards) and len(cards) >= MIN_CARDS_FOR_MAP

    # -- 預覽 ---------------------------------------------------------------

    def _plan_line(self, title: str, page: dict, cards: Sequence[BoardCard]) -> str:
        new_count = sum(1 for c in cards if not c.role)
        model = "會跑模型" if self._wants_model(cards) else "不跑模型"
        return (f"{title}：{len(cards)} 張卡（新卡 {new_count}），{model}，"
                f"書頁：{self._page_plan(page)}")

    def _page_plan(self, page: dict) -> str:
        if not self._reading_list.is_created_by_integration(page):
            return "不動（手動建立的書頁，只補卡片欄位）"
        section = find_section(self._reading_list.list_blocks(page["id"]), SECTION_NOTES)
        if section is None:
            return f"不動（找不到「{SECTION_NOTES}」段）"
        _, body = section
        linked = _linked_databases(body)
        if linked:
            swaps = [self._views.describe_swap(block_id) for block_id in linked]
            if any(s.add_board or s.delete_gallery_id for s in swaps):
                return "取代 gallery"
            return "已有看板"
        if section_is_empty(body):
            return "建看板"
        return f"不動（「{SECTION_NOTES}」段已有內容）"

    # -- 正式處理 -----------------------------------------------------------

    def _process_book(self, title: str, page: dict, cards: List[BoardCard],
                      report: CardBoardReport) -> None:
        if self._wants_model(cards):
            updates = self._plan_with_model(title, cards)
            if updates is None:
                report.failed.append((
                    title, "模型沒有給出可用的全書地圖（兩次詢問各試 2 次）；"
                           "這本書的卡與書頁都沒有動"))
                return
        elif needs_map(cards):
            logger.info(f"《{title}》{len(cards)} 張卡不足 {MIN_CARDS_FOR_MAP} 張，"
                        "不需跑模型：角色填預設、只排閱讀順序")
            updates = plan_book_updates(cards, None, self._positions_of(cards))
        else:
            logger.info(f"《{title}》不需跑模型：每張卡都已有角色")
            updates = plan_book_updates(cards, None, {})

        for update in updates:
            self._cards.update_board_fields(update)

        self._ensure_board(title, page)

        if updates:
            report.processed.append((title, len(updates)))
        else:
            report.untouched.append(title)

    def _plan_with_model(self, title: str, cards: List[BoardCard]
                         ) -> Optional[List[CardUpdate]]:
        # 模型要看整本書，所以舊卡新卡的內文都要讀
        with_text = [replace(c, content=self._cards.card_text(c.page_id)) for c in cards]
        positions = self._positions_of(cards)
        by_book_order = sort_by_book_order(with_text, positions)
        listings = (by_book_order, shuffled_listing(by_book_order, title))

        runs: List[MapRun] = []
        for index, listing in enumerate(listings, start=1):
            run = self._ask_run(title, listing)
            if run is None:
                logger.error(f"《{title}》第 {index} 次詢問模型失敗（含重試），這本書不寫入")
                return None
            runs.append(run)
        logger.info(f"《{title}》已跑模型（{len(with_text)} 張卡，兩次詢問）")
        return plan_book_updates(with_text, merge_map_runs(runs[0], runs[1]), positions)

    def _ask_run(self, title: str, listing: Sequence[BoardCard]) -> Optional[MapRun]:
        page_ids = [c.page_id for c in listing]
        for attempt in range(1, _ATTEMPTS_PER_RUN + 1):
            raw = self._generator.ask_book_map(title, listing)
            run = parse_map_run(raw, page_ids)
            if run is not None:
                return run
            logger.warning(f"《{title}》模型回應不可用（第 {attempt}/{_ATTEMPTS_PER_RUN} 次）")
        return None

    def _positions_of(self, cards: Sequence[BoardCard]) -> Positions:
        ids = [c.source_id for c in cards if c.source_id]
        return self._positions.positions_for(ids) if ids else {}

    def _ensure_board(self, title: str, page: dict) -> None:
        if not self._reading_list.is_created_by_integration(page):
            logger.info(f"《{title}》書頁不是同步建立的，只補卡片欄位、不動看板")
            return
        page_id = page["id"]
        section = find_section(self._reading_list.list_blocks(page_id), SECTION_NOTES)
        if section is None:
            logger.warning(f"《{title}》書頁找不到「{SECTION_NOTES}」段，跳過看板")
            return
        heading, body = section
        linked = _linked_databases(body)
        if linked:
            for linked_id in linked:
                self._views.swap_gallery_for_board(linked_id, self._cards_database_id, page_id)
        elif section_is_empty(body):
            self._views.create_card_board(
                page_id, self._cards_database_id, page_id, heading["id"])
        else:
            logger.info(f"《{title}》「{SECTION_NOTES}」段已有使用者內容，不動看板")


def _linked_databases(body: Sequence[dict]) -> List[str]:
    return [b["id"] for b in body if b.get("type") == "child_database"]
