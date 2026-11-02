#!/usr/bin/env python
"""移除卡片盒既有卡片上的「📖 章名／進度」callout（新卡已不再寫這一行）。

只看每張卡的頂層 block，且只刪 icon 為 📖 的 callout；其他內容一律不動。
刪除不可復原，所以請先預覽、確認清單沒問題再正式執行：

    python tools/remove_card_chapter_callouts.py --dry-run   # 列出卡片與 callout 文字，不刪
    python tools/remove_card_chapter_callouts.py             # 正式刪除

單筆刪除失敗會記下並繼續，有失敗時 exit code 為 1；重跑只會找到剩下的。
"""
import argparse
import os
import sys
from typing import List, Optional, Tuple

# allow `python tools/remove_card_chapter_callouts.py` from anywhere
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.config.settings import Settings  # noqa: E402
from src.infrastructure.container import (  # noqa: E402
    setup_file_and_console_logging,
)
from src.infrastructure.notion.rate_limiter import NotionRateLimiter  # noqa: E402
from src.infrastructure.notion.zettelkasten_card_repository import (  # noqa: E402
    ZettelkastenCardRepository,
)


def _build(settings: Settings) -> ZettelkastenCardRepository:
    return ZettelkastenCardRepository(
        token=settings.notion_token,
        database_id=settings.notion_zettelkasten_database_id,
        rate_limiter=NotionRateLimiter(),
    )


def run(
    dry_run: bool = False,
    *,
    repo: Optional[ZettelkastenCardRepository] = None,
) -> Tuple[str, int]:
    """(給人看的報告, exit code)。repo 可注入以便測試。"""
    if repo is None:
        settings = Settings.from_env()
        if not settings.notion_zettelkasten_database_id:
            return "未設定 NOTION_ZETTELKASTEN_DATABASE_ID，無法清除", 1
        repo = _build(settings)

    try:
        callouts = repo.list_chapter_callouts()
    except Exception as e:
        return f"讀取卡片失敗，沒有刪除任何東西：{e}", 1

    if not callouts:
        return "卡片盒裡沒有 📖 章名／進度 callout，無事可做", 0

    listing = [f"   {title}：{text}" for title, _block_id, text in callouts]
    if dry_run:
        header = f"預覽：會刪除 {len(callouts)} 個 📖 callout（沒有刪除任何東西）"
        return "\n".join([header] + listing), 0

    failed: List[Tuple[str, str, str]] = []
    deleted = 0
    for title, block_id, text in callouts:
        try:
            repo.delete_block(block_id)
            deleted += 1
        except Exception as e:
            failed.append((title, block_id, str(e)))

    lines = [f"已刪除 {deleted} 個 📖 callout："] + listing
    if failed:
        lines.append(f"失敗 {len(failed)} 個（重跑會再試）：")
        lines += [f"   {title}（{block_id}）：{reason}" for title, block_id, reason in failed]
    return "\n".join(lines), (1 if failed else 0)


def main() -> int:
    parser = argparse.ArgumentParser(description="移除卡片盒既有卡片上的 📖 章名／進度 callout")
    parser.add_argument("--dry-run", action="store_true",
                        help="只列出會刪除哪些卡片的 callout 與文字；不刪除")
    args = parser.parse_args()

    setup_file_and_console_logging()
    mode = "DRY RUN（不刪除）" if args.dry_run else "正式執行（刪除不可復原）"
    print(f"=== 移除卡片 📖 callout — {mode} ===")
    report, code = run(dry_run=args.dry_run)
    print(report)
    return code


if __name__ == "__main__":
    raise SystemExit(main())
