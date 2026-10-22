#!/usr/bin/env python
"""為卡片盒裡勾選「做圖」的卡片產生概念圖卡 HTML（供 Figma 匯入成可編輯圖層）。

流程：
  1. 在 Notion 卡片盒勾選要做圖的卡（第一次執行會自動建立「做圖」勾選欄）；
  2. 執行本工具 → 每張卡一個 HTML，放在 infographics_out/<書名>/<卡片標題>.html；
  3. Figma → html.to.design 外掛 → Code 分頁 → 貼上或上傳 HTML → 匯入；
  4. 在 Notion 卡片頁用 /embed 貼上 Figma 連結，之後在 Figma 改字，Notion 會跟著更新。

每張卡的內容取自本地 cards_output/*.json（含已上傳的批次），所以只能處理這台機器
產過的卡。全書概念地圖（每張卡的角色與前後關係）每本書產一次並快取在
cards_output/maps/；書裡的卡片數變了才會重做。需要地端 Ollama，建議用較大的模型
（OLLAMA_INFOGRAPHIC_MODEL=gemma4:12b；不設就沿用 OLLAMA_MODEL，小模型的角色與關係會失準）。

已產生過的卡預設略過（你可能已在 Figma 改過）；要重做加 --force。

    python tools/make_card_infographic.py --dry-run   # 只列出會處理哪些卡
    python tools/make_card_infographic.py
    python tools/make_card_infographic.py --force
"""
import argparse
import os
import sys
from typing import Optional, Tuple

# allow `python tools/make_card_infographic.py` from anywhere
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.application.use_cases.make_card_infographic_use_case import (  # noqa: E402
    InfographicResult,
    MakeCardInfographicUseCase,
)
from src.config.settings import Settings  # noqa: E402
from src.infrastructure.container import (  # noqa: E402
    setup_file_and_console_logging,
)
from src.infrastructure.infographic.spec_generator import (  # noqa: E402
    InfographicSpecGenerator,
)
from src.infrastructure.notion.rate_limiter import NotionRateLimiter  # noqa: E402
from src.infrastructure.notion.zettelkasten_card_repository import (  # noqa: E402
    ZettelkastenCardRepository,
)
from src.infrastructure.persistence.book_map_store import BookMapStore  # noqa: E402
from src.infrastructure.persistence.card_store import CardStore  # noqa: E402
from zettelkasten_generator import ZettelkastenLLMEnhancer  # noqa: E402

_FIGMA_HINT = (
    "下一步：Figma → html.to.design 外掛 → Code 分頁 → 貼上或上傳 HTML → 匯入；"
    "再到 Notion 卡片頁用 /embed 貼上該 frame 的 Figma 連結。"
)


def format_report(result: InfographicResult, dry_run: bool) -> str:
    lines = []
    if dry_run and result.planned:
        lines.append(f"預覽：會產生 {len(result.planned)} 張（沒有寫入任何檔案，也沒有呼叫模型）")
        lines += [f"   {title} → {path}" for title, path in result.planned]
    if result.generated:
        lines.append(f"已產生 {len(result.generated)} 張：")
        for title, path in result.generated:
            lines += [f"   {title}", f"      {path}"]
    if result.skipped:
        lines.append(f"略過 {len(result.skipped)} 張：")
        lines += [f"   {title}：{reason}" for title, reason in result.skipped]
    if result.failed:
        lines.append(f"失敗 {len(result.failed)} 張：")
        lines += [f"   {title}：{reason}" for title, reason in result.failed]
    if result.generated:
        lines += ["", _FIGMA_HINT]
    return "\n".join(lines)


def pick_model(card_model: str) -> str:
    """做圖用的模型：OLLAMA_INFOGRAPHIC_MODEL，沒設就沿用產卡的 OLLAMA_MODEL。

    全書角色／前後關係／版面選擇都是語意判斷，小模型（實測 qwen3:4b）會把每張卡都
    標成同一個角色、前後關係亂串、還會編造卡片沒說的句子；gemma4:12b 則明顯可用。
    這個工具只處理你勾選的少數卡片，慢一點可以接受，所以允許獨立指定較大的模型。"""
    return (os.getenv("OLLAMA_INFOGRAPHIC_MODEL") or "").strip() or card_model


def _build(settings: Settings) -> Tuple[ZettelkastenCardRepository, MakeCardInfographicUseCase]:
    repo = ZettelkastenCardRepository(
        token=settings.notion_token,
        database_id=settings.notion_zettelkasten_database_id,
        rate_limiter=NotionRateLimiter(),
        tag_categories=settings.zettelkasten_tag_categories,
    )
    enhancer = ZettelkastenLLMEnhancer()
    generator = InfographicSpecGenerator(
        api_url=enhancer.api_url,
        model=pick_model(enhancer.model),
        timeout_s=int(os.getenv("OLLAMA_TIMEOUT_SECONDS", "300")),
    )
    use_case = MakeCardInfographicUseCase(
        card_store=CardStore(settings.zettelkasten_cards_output_dir),
        map_store=BookMapStore(settings.zettelkasten_cards_output_dir),
        generator=generator,
        output_dir=settings.infographics_output_dir,
    )
    return repo, use_case


def run(
    dry_run: bool = False,
    force: bool = False,
    *,
    repo: Optional[ZettelkastenCardRepository] = None,
    use_case: Optional[MakeCardInfographicUseCase] = None,
) -> Tuple[str, int]:
    """(給人看的報告, exit code)。repo／use_case 可注入以便測試。"""
    if repo is None or use_case is None:
        settings = Settings.from_env()
        if not settings.notion_zettelkasten_database_id:
            return "未設定 NOTION_ZETTELKASTEN_DATABASE_ID，無事可做", 0
        repo, use_case = _build(settings)

    notes = []
    # 預覽必須唯讀：只有正式執行才會替卡片盒補欄位
    if not dry_run and repo.ensure_infographic_column():
        notes.append("已在卡片盒建立「做圖」勾選欄。")

    marked = repo.list_cards_marked_for_infographic()
    if not marked:
        notes.append("卡片盒裡沒有勾選「做圖」的卡。到 Notion 勾選要做圖的卡後，再執行一次。")
        return "\n".join(notes), 0

    result = use_case.execute(marked, force=force, dry_run=dry_run)
    return "\n".join(notes + [format_report(result, dry_run)]), (1 if result.failed else 0)


def main() -> int:
    parser = argparse.ArgumentParser(description="為勾選「做圖」的卡片產生概念圖卡 HTML")
    parser.add_argument("--dry-run", action="store_true",
                        help="只列出會處理哪些卡；不呼叫模型、不寫檔、不改 Notion 欄位")
    parser.add_argument("--force", action="store_true",
                        help="已產生過的卡也重做（會覆蓋同名 HTML）")
    args = parser.parse_args()

    setup_file_and_console_logging()
    mode = "DRY RUN（不寫入）" if args.dry_run else "正式執行"
    print(f"=== 概念圖卡 — {mode} ===")
    report, code = run(dry_run=args.dry_run, force=args.force)
    print(report)
    return code


if __name__ == "__main__":
    raise SystemExit(main())
