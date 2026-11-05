"""使用者標記 🔧待修正 的卡 → 審核目前版本（有「待修正的點」就再重產候選版本）→ 結果寫到頁尾。

內容一律從 Notion 讀：使用者會手動改卡，本地 JSON 是舊版，而且不一定在這台機器上。

審核在這裡只是參考，不是閘門。`correctness` 面向會扣「原文沒寫」的內容，而使用者自己
加的想法正是永久筆記該有的，所以分數低也不會刪卡或擋下結果，卡片本文永遠不動。

任何一步失敗就什麼都不寫：頁尾沒有這個版本的結果，下次重跑自然會再試。
"""
import logging
from dataclasses import dataclass
from datetime import date
from typing import Callable, Dict, List, Optional

from zettelkasten_generator import CardReview, ZettelkastenCard

from ...domain.entities.board_card import BoardCard
from ...domain.entities.card_revision import Candidate, CardBody, Verdict
from ...domain.services.card_revision_rules import (
    fingerprint,
    format_result,
    has_result_for,
    parse_card_body,
    revision_hint,
)
from ..dtos.card_revision_report import CardRevisionReport

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class _Prepared:
    card: BoardCard
    body: CardBody
    mark: str


@dataclass(frozen=True)
class _BookContext:
    title: str = ""
    theme: str = ""
    cards: tuple = ()   # 同書的 BookCard


class ReviseCardsUseCase:
    def __init__(self, cards, reviewer, enhancer, today: Optional[Callable[[], str]] = None):
        self._cards = cards
        self._reviewer = reviewer
        self._enhancer = enhancer
        self._today = today or (lambda: date.today().isoformat())

    def execute(self, dry_run: bool = False) -> CardRevisionReport:
        report = CardRevisionReport()
        prepared = self._prepare(report)
        if dry_run:
            report.planned = [
                (p.card.title, "依「待修正的點」重產候選版本" if p.body.revision_note else "只審目前版本")
                for p in prepared
            ]
            return report
        if not prepared:
            return report
        if not self._reviewer.is_available():
            report.aborted = "審核模型不可用（原因見上方 log），沒有寫入任何東西。"
            return report

        contexts: Dict[str, _BookContext] = {}
        for item in prepared:
            try:
                self._revise(item, contexts, report)
            except Exception as e:  # noqa: BLE001 — 單張失敗不該中止整批
                logger.error(f"卡片 '{item.card.title}' 重審失敗: {e}", exc_info=True)
                report.failed.append((item.card.title, str(e)))
        return report

    def _prepare(self, report: CardRevisionReport) -> List[_Prepared]:
        """只讀：找出這次真的要跑模型的卡。"""
        prepared: List[_Prepared] = []
        for card in self._cards.list_cards_marked_for_revision():
            try:
                blocks = self._cards.read_card_blocks(card.page_id)
            except Exception as e:  # noqa: BLE001 — 單張讀不到不該中止整批
                logger.error(f"讀取卡片 '{card.title}' 失敗: {e}", exc_info=True)
                report.failed.append((card.title, str(e)))
                continue
            body = parse_card_body(blocks)
            mark = fingerprint(card.title, body)
            if not body.highlight:
                report.skipped.append((card.title, "頁面上沒有原文劃線（quote 區塊），無從對照"))
            elif not body.content:
                report.skipped.append((card.title, "頁面上沒有內文"))
            elif has_result_for(blocks, mark):
                report.skipped.append((card.title, "這個版本審過了，結果在頁尾（刪掉結果區塊或改內容就會再審）"))
            else:
                prepared.append(_Prepared(card, body, mark))
        return prepared

    def _revise(
        self,
        item: _Prepared,
        contexts: Dict[str, _BookContext],
        report: CardRevisionReport,
    ) -> None:
        card, body = item.card, item.body
        context = self._book_context(card.book_page_id, contexts)
        siblings = [c.title for c in context.cards if c.page_id != card.page_id]

        def judge(version: ZettelkastenCard) -> Optional[CardReview]:
            return self._reviewer.review(
                version,
                book_title=context.title,
                book_theme=context.theme,
                sibling_titles=siblings,
            )

        current = judge(ZettelkastenCard(
            id=card.page_id,
            title=card.title,
            content=body.content,
            source_highlight=body.highlight,
            chapter_reference="",
            chapter_progress=0.0,
            source_bookmark_id=card.source_id,
        ))
        if current is None:
            report.failed.append((card.title, "審核模型沒有回傳可用的結果（原因見上方 log）"))
            return

        candidate: Optional[Candidate] = None
        if body.revision_note:
            remade = self._enhancer.generate_card(
                {"text": body.highlight, "bookmark_id": card.source_id},
                context.title,
                book_theme=context.theme,
                revision_hint=revision_hint(body),
            )
            if remade is None:
                report.failed.append((card.title, "產卡模型沒有產出候選版本（原因見上方 log）"))
                return
            remade_review = judge(remade)
            if remade_review is None:
                report.failed.append((card.title, "審核模型沒有回傳候選版本的可用結果（原因見上方 log）"))
                return
            candidate = Candidate(remade.title, remade.content, self._verdict(remade_review))

        heading, lines = format_result(
            self._verdict(current),
            threshold=self._reviewer.threshold,
            mark=item.mark,
            day=self._today(),
            candidate=candidate,
        )
        self._cards.append_revision_result(card.page_id, heading, lines)
        (report.regenerated if candidate else report.reviewed).append(card.title)

    def _verdict(self, review: CardReview) -> Verdict:
        return Verdict(review.scores(), review.notes, review.passed(self._reviewer.threshold))

    def _book_context(
        self, book_page_id: str, contexts: Dict[str, _BookContext]
    ) -> _BookContext:
        if not book_page_id:
            return _BookContext()
        if book_page_id not in contexts:
            title = self._cards.book_title(book_page_id)
            cards = tuple(self._cards.list_book_cards(book_page_id))
            drafts = [
                ZettelkastenCard(
                    id=c.page_id,
                    title=c.title,
                    content=self._cards.card_text(c.page_id),
                    source_highlight="",
                    chapter_reference="",
                    chapter_progress=0.0,
                )
                for c in cards
            ]
            contexts[book_page_id] = _BookContext(
                title, self._reviewer.summarize_book(drafts, title), cards
            )
        return contexts[book_page_id]
