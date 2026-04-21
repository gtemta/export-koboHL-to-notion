"""Entry point for Kobo → Notion highlight sync.

Usage:
    python main.py

Loads settings from .env, wires the clean-architecture composition root,
and runs SyncBooksUseCase.
"""
import logging
import sys

from src.config.settings import Settings
from src.infrastructure.container import build_use_case, setup_file_and_console_logging


def main() -> int:
    try:
        settings = Settings.from_env()
    except ValueError as e:
        print(f"[設定錯誤] {e}", file=sys.stderr)
        return 2

    setup_file_and_console_logging(settings.log_level)
    logger = logging.getLogger(__name__)
    logger.info("啟動 Kobo → Notion 同步流程")

    use_case = build_use_case(settings)
    result = use_case.execute()

    logger.info(
        f"同步結束: {result.successful_syncs}/{result.total_books} 成功 "
        f"({result.success_rate:.1f}%)"
    )
    if result.errors:
        logger.warning(f"錯誤總數: {len(result.errors)}")
        for err in result.errors:
            logger.warning(f"  - {err}")

    return 0 if result.failed_syncs == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
