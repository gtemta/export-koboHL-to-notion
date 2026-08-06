#!/usr/bin/env python
"""為卡片盒既有卡片補上 cover / icon / 加工狀態。

新卡在建立時就帶這三樣（見 ZettelkastenCardRepository），但既有卡片不會自動有。
本工具掃過整個卡片盒，只補「缺的那一項」：

  - cover：純規則，由卡片的 Tags 分類決定，不花任何 LLM 呼叫；
  - icon ：以「標題 + Key Word」批次送 Ollama 挑 emoji（兩個欄位在 query 回應裡
           就有，不必為了讀內文再打一次 API）。Ollama 不可用時只補 cover，
           icon 留給下次重跑；
  - 加工狀態：一律補「🌱未加工」。

已有值的一律不覆蓋 —— 重跑冪等，也不會蓋掉你在 Notion 上手動換過的圖。

    python tools/backfill_card_visuals.py --dry-run
    python tools/backfill_card_visuals.py
"""
import argparse
import logging
import os
import sys
from typing import Dict, List, Optional

# allow `python tools/backfill_card_visuals.py` from anywhere
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from notion_client import Client  # noqa: E402

from src.config.settings import Settings  # noqa: E402
from src.infrastructure.container import (  # noqa: E402
    setup_file_and_console_logging,
)
from src.infrastructure.notion.card_visuals import cover_url_for  # noqa: E402
from src.infrastructure.notion.rate_limiter import NotionRateLimiter  # noqa: E402
from src.infrastructure.notion.retry_policy import retry_with_backoff  # noqa: E402
from src.infrastructure.notion.zettelkasten_card_repository import (  # noqa: E402
    _STAGE_PROPERTY,
    _STAGE_UNPROCESSED,
)
from zettelkasten_generator import (  # noqa: E402
    ZettelkastenCard,
    ZettelkastenLLMEnhancer,
)

logger = logging.getLogger("backfill_card_visuals")

_TITLE_PROP = "標題"
_TAGS_PROP = "Tags"
_KEYWORD_PROP = "Key Word"
# 一次送給 Ollama 的卡片數。跟產卡時的單書張數同量級，prompt 不會爆 num_ctx。
_ICON_BATCH_SIZE = 20


# ----- 純函式：讀頁面欄位 -----

def card_title(page: dict) -> str:
    prop = (page.get("properties") or {}).get(_TITLE_PROP) or {}
    return "".join(
        p.get("plain_text", "") for p in (prop.get("title") or [])
    ).strip()


def card_keywords(page: dict) -> str:
    prop = (page.get("properties") or {}).get(_KEYWORD_PROP) or {}
    return "".join(
        p.get("plain_text", "") for p in (prop.get("rich_text") or [])
    ).strip()


def card_categories(page: dict) -> List[str]:
    prop = (page.get("properties") or {}).get(_TAGS_PROP) or {}
    return [o.get("name", "") for o in (prop.get("multi_select") or []) if o.get("name")]


def missing_cover(page: dict) -> bool:
    return not page.get("cover")


def missing_icon(page: dict) -> bool:
    return not page.get("icon")


def missing_stage(page: dict) -> bool:
    prop = (page.get("properties") or {}).get(_STAGE_PROPERTY) or {}
    return not (prop.get("select") or {}).get("name")


def needs_work(page: dict) -> bool:
    return missing_cover(page) or missing_icon(page) or missing_stage(page)


def build_update(page: dict, icon: str) -> dict:
    """pages.update 的 kwargs —— 只包含這張卡真正缺的東西。

    空 icon 代表這批 Ollama 呼叫失敗；此時不寫 icon，讓下次重跑補上，
    而不是用規則值把它凍住。
    """
    update: Dict = {}
    if missing_cover(page):
        update["cover"] = {
            "type": "external",
            "external": {"url": cover_url_for(card_categories(page))},
        }
    if icon and missing_icon(page):
        update["icon"] = {"type": "emoji", "emoji": icon}
    if missing_stage(page):
        update["properties"] = {
            _STAGE_PROPERTY: {"select": {"name": _STAGE_UNPROCESSED}}
        }
    return update


# ----- IO -----

def fetch_all_cards(client, database_id: str, limiter) -> List[dict]:
    pages: List[dict] = []
    cursor: Optional[str] = None
    while True:
        kwargs = {"database_id": database_id, "page_size": 100}
        if cursor:
            kwargs["start_cursor"] = cursor
        result = retry_with_backoff(
            lambda k=kwargs: client.databases.query(**k), limiter
        ) or {}
        pages.extend(result.get("results", []))
        if not result.get("has_more"):
            break
        cursor = result.get("next_cursor")
    return pages


def icons_for(enhancer, pages: List[dict], categories: List[str]) -> List[str]:
    """為一批頁面挑 icon；整批 Ollama 失敗時回傳全空字串。

    只用「標題 + Key Word」組出臨時卡片 —— 兩者都在 query 回應裡，不必為了讀
    內文再打一次 API。classify_cards 會覆寫 card.categories，所以事後還原成
    Notion 上的真實分類，_fallback_icon 才會依真實分類遞補。
    """
    cards = [
        ZettelkastenCard(
            id=page.get("id", ""),
            title=card_title(page),
            content=card_keywords(page),
            source_highlight="",
            chapter_reference="",
            chapter_progress=0.0,
            tags=[t for t in card_keywords(page).split("、") if t],
            categories=card_categories(page),
        )
        for page in pages
    ]
    original = [list(c.categories) for c in cards]
    try:
        ok = enhancer.classify_cards(cards, categories)
    except Exception as e:  # noqa: BLE001 — Ollama 掛掉不該中止整個回填
        logger.warning(f"Ollama 分類呼叫失敗，本批只補 cover: {e}")
        return ["" for _ in cards]
    if not ok:
        logger.warning("Ollama 回應無法解析，本批只補 cover（下次重跑會再試）")
        return ["" for _ in cards]
    for card, cats in zip(cards, original):
        card.categories = cats  # 本工具不改 Tags，還原以免 fallback 用到亂猜的分類
    return [c.icon or ZettelkastenLLMEnhancer._fallback_icon(c) for c in cards]


def run(dry_run: bool = False) -> Dict[str, int]:
    settings = Settings.from_env()
    if not settings.notion_zettelkasten_database_id:
        print("未設定 NOTION_ZETTELKASTEN_DATABASE_ID，無事可做")
        return {"scanned": 0, "pending": 0, "updated": 0, "failed": 0}

    limiter = NotionRateLimiter()
    client = Client(auth=settings.notion_token)
    enhancer = ZettelkastenLLMEnhancer()

    pages = fetch_all_cards(client, settings.notion_zettelkasten_database_id, limiter)
    pending = [p for p in pages if needs_work(p)]
    stats = {"scanned": len(pages), "pending": len(pending), "updated": 0, "failed": 0}
    print(f"掃描 {len(pages)} 張卡片，其中 {len(pending)} 張需要補齊")
    if not pending:
        return stats

    for start in range(0, len(pending), _ICON_BATCH_SIZE):
        batch = pending[start:start + _ICON_BATCH_SIZE]
        need_icon = any(missing_icon(p) for p in batch)
        icons = (
            icons_for(enhancer, batch, settings.zettelkasten_tag_categories)
            if need_icon else ["" for _ in batch]
        )
        for page, icon in zip(batch, icons):
            update = build_update(page, icon)
            if not update:
                continue
            title = card_title(page) or "?"
            cover_name = (
                update.get("cover", {}).get("external", {}).get("url", "")
                .rsplit("/", 1)[-1]
            )
            print(f"   {title}\n      cover={cover_name or '（保留）'} "
                  f"icon={update.get('icon', {}).get('emoji', '（保留）')}")
            if dry_run:
                continue
            try:
                retry_with_backoff(
                    lambda pid=page["id"], u=update: client.pages.update(
                        page_id=pid, **u
                    ),
                    limiter,
                )
                stats["updated"] += 1
            except Exception as e:  # noqa: BLE001 — 單張失敗不該中止整批
                logger.error(f"卡片 '{title}' 更新失敗: {e}")
                stats["failed"] += 1
    return stats


def main() -> int:
    parser = argparse.ArgumentParser(
        description="為卡片盒既有卡片補上 cover / icon / 加工狀態"
    )
    parser.add_argument("--dry-run", action="store_true",
                        help="只印出將要寫入的 cover / icon，不實際寫回")
    args = parser.parse_args()

    setup_file_and_console_logging()
    mode = "DRY RUN（不寫入）" if args.dry_run else "正式執行"
    print(f"=== 卡片視覺回填 — {mode} ===")

    stats = run(dry_run=args.dry_run)

    print(
        f"\n=== 總結 ===\n"
        f"掃描 {stats['scanned']} 張，需補齊 {stats['pending']} 張，"
        f"已更新 {stats['updated']} 張，失敗 {stats['failed']} 張"
    )
    if args.dry_run and stats["pending"]:
        print("\n確認無誤後拿掉 --dry-run 正式執行。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
