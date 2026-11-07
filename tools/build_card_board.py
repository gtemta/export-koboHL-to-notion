#!/usr/bin/env python
"""為卡片盒的卡補上「角色／閱讀順序／相關卡片」，並讓同步建立的書頁換上依角色分欄的看板。

手動執行的工具（不接進 main.py）：
  1. 讀卡片盒所有卡與 Reading List 書頁（唯讀）；
  2. 角色空白的卡 = 新卡。新卡太少的書不跑模型，其餘的書請地端模型看整本書判斷
     每張卡的角色（主軸／支柱／案例）與相關卡片，問兩次（書中順序、洗牌順序），
     只留兩次都出現的連結；任一次失敗，這本書什麼都不寫；
  3. 只填空白欄位，絕不覆寫你改過的值，也不移除你刪掉的連結；
  4. 只有「同步自動建立」的書頁才會把「筆記圖」段換成看板；手動建立的書頁只補卡片欄位。

所有書都已填過時不需要模型（Ollama 不必開），重跑是 no-op。需要較大的地端模型：
OLLAMA_CARD_MAP_MODEL（預設 gemma4:12b，刻意不沿用 OLLAMA_MODEL）。

    python tools/build_card_board.py --dry-run              # 只列出每本書會怎樣，不呼叫模型、不寫入
    python tools/build_card_board.py --dry-run --book 主控力
    python tools/build_card_board.py --book 主控力
    python tools/build_card_board.py
"""
import argparse
import logging
import os
import sys
from typing import Optional, Tuple

# allow `python tools/build_card_board.py` from anywhere
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.application.dtos.card_board_report import CardBoardReport  # noqa: E402
from src.application.use_cases.build_card_board_use_case import (  # noqa: E402
    BuildCardBoardUseCase,
)
from src.config.settings import Settings  # noqa: E402
from src.infrastructure.container import (  # noqa: E402
    setup_file_and_console_logging,
)
from src.infrastructure.infographic.spec_generator import (  # noqa: E402
    InfographicSpecGenerator,
)
from src.infrastructure.notion.notion_views_client import NotionViewsClient  # noqa: E402
from src.infrastructure.notion.rate_limiter import NotionRateLimiter  # noqa: E402
from src.infrastructure.notion.reading_list_repository import (  # noqa: E402
    ReadingListRepository,
)
from src.infrastructure.notion.zettelkasten_card_repository import (  # noqa: E402
    ZettelkastenCardRepository,
)
from src.infrastructure.persistence.kobo_book_positions import (  # noqa: E402
    KoboBookPositions,
)
from zettelkasten_generator import ZettelkastenLLMEnhancer  # noqa: E402

logger = logging.getLogger(__name__)

_DEFAULT_MODEL = "gemma4:12b"


def card_map_model() -> str:
    """全書判斷用的模型：OLLAMA_CARD_MAP_MODEL，沒設就是 gemma4:12b。

    刻意不退回 OLLAMA_MODEL：角色與相關卡片是整本書的語意判斷，產卡用的小模型
    （實測 qwen3:4b）會把每張卡標成同一個角色、連結亂串。"""
    return (os.getenv("OLLAMA_CARD_MAP_MODEL") or "").strip() or _DEFAULT_MODEL


def format_report(report: CardBoardReport, dry_run: bool) -> str:
    lines = []
    if report.aborted:
        lines.append(f"中止：{report.aborted}")
    if dry_run and report.planned:
        lines.append(f"預覽：{len(report.planned)} 本書（沒有呼叫模型，也沒有寫入任何東西）")
        lines += [f"   {line}" for line in report.planned]
    if report.processed:
        lines.append(f"已處理 {len(report.processed)} 本：")
        lines += [f"   {title}：更新 {count} 張卡" for title, count in report.processed]
    if report.untouched:
        lines.append(f"沒有卡需要更新 {len(report.untouched)} 本：")
        lines += [f"   {title}" for title in report.untouched]
    if report.failed:
        lines.append(f"失敗 {len(report.failed)} 本：")
        lines += [f"   {title}：{reason}" for title, reason in report.failed]
    if report.no_source_cards:
        lines.append(f"另有 {report.no_source_cards} 張卡沒有「來源」，已略過。")
    return "\n".join(lines) or "沒有需要處理的卡。"


def _build(settings: Settings) -> BuildCardBoardUseCase:
    limiter = NotionRateLimiter()
    reading_list = ReadingListRepository(
        token=settings.notion_token,
        database_id=settings.notion_books_database_id,
        rate_limiter=limiter,
    )
    cards = ZettelkastenCardRepository(
        token=settings.notion_token,
        database_id=settings.notion_zettelkasten_database_id,
        books_database_id=settings.notion_books_database_id,
        rate_limiter=limiter,
        tag_categories=settings.zettelkasten_tag_categories,
        reading_list=reading_list,
    )
    views = NotionViewsClient(token=settings.notion_token, rate_limiter=limiter)
    generator = InfographicSpecGenerator(
        api_url=ZettelkastenLLMEnhancer().api_url,
        model=card_map_model(),
        timeout_s=int(os.getenv("OLLAMA_CARD_MAP_TIMEOUT_SECONDS", "600")),
    )
    return BuildCardBoardUseCase(
        cards=cards,
        reading_list=reading_list,
        views=views,
        positions=KoboBookPositions(settings.kobo_db_path),
        generator=generator,
        cards_database_id=settings.notion_zettelkasten_database_id,
    )


def run(
    dry_run: bool = False,
    book: Optional[str] = None,
    *,
    use_case: Optional[BuildCardBoardUseCase] = None,
) -> Tuple[str, int]:
    """(給人看的報告, exit code)。use_case 可注入以便測試。"""
    if use_case is None:
        settings = Settings.from_env()
        missing = [name for name, value in (
            ("NOTION_ZETTELKASTEN_DATABASE_ID", settings.notion_zettelkasten_database_id),
            ("NOTION_BOOKS_DATABASE_ID", settings.notion_books_database_id),
        ) if not value]
        if missing:
            return f"未設定 {'、'.join(missing)}，無法建立卡片看板（沒有做任何事）。", 1
        use_case = _build(settings)

    try:
        report = use_case.execute(book_filter=book, dry_run=dry_run)
    except Exception as e:  # noqa: BLE001 — 讀取失敗：不能當成「沒有卡」，明確失敗收場
        logger.error(f"讀取 Notion 失敗，沒有做任何事: {e}", exc_info=True)
        return f"讀取 Notion 失敗，沒有做任何事：{e}", 1
    code = 1 if (report.failed or report.aborted) else 0
    return format_report(report, dry_run), code


def main() -> int:
    parser = argparse.ArgumentParser(description="為卡片補角色／閱讀順序／相關卡片，並建立書頁看板")
    parser.add_argument("--dry-run", action="store_true",
                        help="只列出每本書會怎樣；不呼叫模型、不建欄位、不寫入 Notion")
    parser.add_argument("--book", help="只處理書名包含這段文字的書")
    args = parser.parse_args()

    setup_file_and_console_logging()
    mode = "DRY RUN（不寫入）" if args.dry_run else "正式執行"
    print(f"=== 卡片角色看板 — {mode} ===")
    report, code = run(dry_run=args.dry_run, book=args.book)
    print(report)
    return code


if __name__ == "__main__":
    raise SystemExit(main())
