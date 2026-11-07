#!/usr/bin/env python
"""重審你標記的卡：審核目前版本，需要時再由模型重產一版給你比較。內文絕不會被更動。

  1. 在 Notion 把卡片的「加工狀態」改成 🔧待修正；
     - 內文有一段以「待修正的點」開頭：模型依這段重產候選版本，兩版都審；
     - 沒有：只審目前的版本（例如你剛改完，想請模型複查）；
  2. 執行這支工具；
  3. 到卡片頁尾看「🤖 重審結果」區塊，要用候選版本就自己複製，再把狀態改成 🌿已重寫。

重跑時，內容沒變且結果區塊還在的卡會略過，不花模型時間。刪掉結果區塊或改過內容就會再審。
需要地端 Ollama：OLLAMA_REVIEW_MODEL 審核、OLLAMA_MODEL 重產。

    python tools/revise_cards.py --dry-run    # 只列出每張卡會怎樣，不呼叫模型、不寫入
    python tools/revise_cards.py
"""
import argparse
import logging
import os
import sys
from typing import Optional, Tuple

# allow `python tools/revise_cards.py` from anywhere
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.application.dtos.card_revision_report import CardRevisionReport  # noqa: E402
from src.application.use_cases.revise_cards_use_case import ReviseCardsUseCase  # noqa: E402
from src.config.settings import Settings  # noqa: E402
from src.domain.services.card_revision_rules import RESULT_MARKER  # noqa: E402
from src.infrastructure.container import setup_file_and_console_logging  # noqa: E402
from src.infrastructure.notion.zettelkasten_card_repository import (  # noqa: E402
    _STAGE_NEEDS_FIX,
    ZettelkastenCardRepository,
)
from zettelkasten_generator import CardReviewer, ZettelkastenLLMEnhancer  # noqa: E402

logger = logging.getLogger(__name__)


def format_report(report: CardRevisionReport, dry_run: bool) -> str:
    lines = []
    if report.aborted:
        lines.append(f"中止：{report.aborted}")
    if dry_run and report.planned:
        lines.append(f"預覽：{len(report.planned)} 張卡（沒有呼叫模型，也沒有寫入任何東西）")
        lines += [f"   {title}：{action}" for title, action in report.planned]
    if report.regenerated or report.reviewed:
        lines.append(f"結果已寫到各卡頁尾的「{RESULT_MARKER}」區塊，內文沒有更動：")
        lines += [f"   {title}：已審核，附候選版本" for title in report.regenerated]
        lines += [f"   {title}：已審核" for title in report.reviewed]
    if report.skipped:
        lines.append(f"略過 {len(report.skipped)} 張：")
        lines += [f"   {title}：{reason}" for title, reason in report.skipped]
    if report.failed:
        lines.append(f"失敗 {len(report.failed)} 張（沒有寫入，重跑會再試）：")
        lines += [f"   {title}：{reason}" for title, reason in report.failed]
    return "\n".join(lines) or f"卡片盒裡沒有標「{_STAGE_NEEDS_FIX}」的卡。"


def _build(settings: Settings) -> ReviseCardsUseCase:
    cards = ZettelkastenCardRepository(
        token=settings.notion_token,
        database_id=settings.notion_zettelkasten_database_id,
    )
    enhancer = ZettelkastenLLMEnhancer()
    return ReviseCardsUseCase(
        cards=cards,
        reviewer=CardReviewer(generator_model=enhancer.model),
        enhancer=enhancer,
    )


def run(
    dry_run: bool = False,
    *,
    use_case: Optional[ReviseCardsUseCase] = None,
) -> Tuple[str, int]:
    """(給人看的報告, exit code)。use_case 可注入以便測試。"""
    if use_case is None:
        settings = Settings.from_env()
        if not settings.notion_zettelkasten_database_id:
            return "未設定 NOTION_ZETTELKASTEN_DATABASE_ID，無法重審卡片（沒有做任何事）。", 1
        use_case = _build(settings)

    try:
        report = use_case.execute(dry_run=dry_run)
    except Exception as e:  # noqa: BLE001 — 讀取失敗：不能當成「沒有標記的卡」，明確失敗收場
        logger.error(f"讀取 Notion 失敗，沒有做任何事: {e}", exc_info=True)
        return f"讀取 Notion 失敗，沒有做任何事：{e}", 1
    code = 1 if (report.failed or report.aborted) else 0
    return format_report(report, dry_run), code


def main() -> int:
    parser = argparse.ArgumentParser(description="重審標記 🔧待修正 的卡片，結果寫到頁尾")
    parser.add_argument("--dry-run", action="store_true",
                        help="只列出每張卡會怎樣；不呼叫模型、不寫入 Notion")
    args = parser.parse_args()

    setup_file_and_console_logging()
    mode = "DRY RUN（不寫入）" if args.dry_run else "正式執行"
    print(f"=== 卡片重審 — {mode} ===")
    report, code = run(dry_run=args.dry_run)
    print(report)
    return code


if __name__ == "__main__":
    raise SystemExit(main())
