"""被勾選「做圖」的卡片 → 本地 HTML 概念圖卡（供 Figma html.to.design 匯入）。

流程（每張卡）：回 cards_output 找完整卡片 → 取（或生成並快取）這本書的全書概念地圖 →
請地端模型為這張卡產規格 → 規格整理驗證 → 渲染成 HTML → 原子寫檔。

角色（主軸／支柱／案例）與鄰居卡一律取自全書地圖，不採信單卡呼叫自己報的——
單卡呼叫看不到整本書，說出來的全書定位沒有依據。

全書地圖生成失敗時降級（預設角色、沒有鄰居）仍照常出圖，且不把失敗的結果存成快取。
"""
import logging
import os
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Sequence, Tuple

from zettelkasten_generator import ZettelkastenCard

from ...domain.entities.infographic_spec import InfographicSpec, MapEntry, MarkedCard
from ...domain.services.infographic_rules import DEFAULT_ROLE, normalize_spec
from ...infrastructure.infographic.html_renderer import render_infographic_html
from ...infrastructure.infographic.spec_generator import InfographicSpecGenerator
from ...infrastructure.persistence.book_map_store import BookMapStore
from ...infrastructure.persistence.card_store import (
    CardStore,
    SavedCard,
    book_slug,
    card_source_id,
)

logger = logging.getLogger(__name__)

Renderer = Callable[[InfographicSpec, str, Sequence[str]], str]


@dataclass
class InfographicResult:
    generated: List[Tuple[str, str]] = field(default_factory=list)   # (卡片標題, HTML 路徑)
    planned: List[Tuple[str, str]] = field(default_factory=list)     # dry-run：會產生的 (標題, 路徑)
    skipped: List[Tuple[str, str]] = field(default_factory=list)     # (卡片標題, 原因)
    failed: List[Tuple[str, str]] = field(default_factory=list)      # (卡片標題, 原因)


@dataclass
class _BookContext:
    titles: List[str]
    theme: str
    entries: Dict[str, MapEntry]


class MakeCardInfographicUseCase:
    def __init__(
        self,
        card_store: CardStore,
        map_store: BookMapStore,
        generator: InfographicSpecGenerator,
        output_dir: str,
        render: Renderer = render_infographic_html,
    ):
        self._cards = card_store
        self._maps = map_store
        self._generator = generator
        self._output_dir = output_dir
        self._render = render

    def execute(
        self, marked: Sequence[MarkedCard], force: bool = False, dry_run: bool = False
    ) -> InfographicResult:
        result = InfographicResult()
        contexts: Dict[str, _BookContext] = {}
        for item in marked:
            try:
                self._process(item, force, dry_run, contexts, result)
            except Exception as e:  # noqa: BLE001 — 單張失敗不該中止整批
                logger.error(f"卡片 '{item.title}' 產圖失敗: {e}")
                result.failed.append((item.title, str(e)))
        return result

    def _process(
        self,
        item: MarkedCard,
        force: bool,
        dry_run: bool,
        contexts: Dict[str, _BookContext],
        result: InfographicResult,
    ) -> None:
        if not item.source_id:
            result.skipped.append((item.title, "沒有「來源劃線ID」（手動建立的卡？），找不到對應的本地卡片"))
            return
        saved = self._cards.find_by_source_id(item.source_id)
        if saved is None:
            result.skipped.append((item.title, "cards_output 找不到這張卡（這台機器沒有它的本地 JSON）"))
            return

        if dry_run:
            # 預覽只讀：連全書地圖都不建（那是一次 LLM 呼叫加一次存檔）
            titles = [c.title for c in self._cards.book_cards(saved.book_title)]
            path = self._output_path(saved, titles)
            if os.path.exists(path) and not force:
                result.skipped.append((item.title, f"已產生過（要重做請加 --force）：{path}"))
            else:
                result.planned.append((item.title, path))
            return

        context = contexts.get(saved.book_title) or self._book_context(saved, contexts)
        path = self._output_path(saved, context.titles)
        if os.path.exists(path) and not force:
            result.skipped.append((item.title, f"已產生過（要重做請加 --force）：{path}"))
            return

        card = saved.card
        raw = self._generator.generate_card_spec(card, saved.book_title, context.theme)
        if raw is None:
            result.failed.append((item.title, "模型沒有給出可用的規格"))
            return
        entry = context.entries.get(card.title)
        raw = dict(raw)
        raw["role"] = entry.role if entry else DEFAULT_ROLE
        raw["neighbors"] = (
            [{"relation": n.relation, "title": n.title} for n in entry.neighbors] if entry else []
        )
        spec = normalize_spec(raw, card.title, context.titles)
        if spec is None:
            result.failed.append((item.title, "規格裡沒有可用的文字行"))
            return

        self._write(path, self._render(spec, saved.book_title, context.titles))
        logger.info(f"概念圖卡已產生: {path}")
        result.generated.append((item.title, path))

    def _book_context(
        self, saved: SavedCard, contexts: Dict[str, _BookContext]
    ) -> _BookContext:
        cards: List[ZettelkastenCard] = self._cards.book_cards(saved.book_title)
        titles = [c.title for c in cards]
        cached = self._maps.load(saved.book_title, titles)
        if cached is None:
            built = self._generator.build_book_map(saved.book_title, cards)
            if built is not None:
                self._maps.save(saved.book_title, titles, *built)
            else:
                logger.warning(
                    f"'{saved.book_title}' 全書概念地圖產生失敗，圖卡改用預設角色且不標前後關係"
                )
            cached = built
        theme, entries = cached if cached is not None else ("", {})
        contexts[saved.book_title] = _BookContext(titles, theme, entries)
        return contexts[saved.book_title]

    def _output_path(self, saved: SavedCard, book_titles: Sequence[str]) -> str:
        name = book_slug(saved.card.title)
        # 同書「檔名會撞」的卡（標題相同、`a/b` 與 `a:b`、只差大小寫——Windows 不分大小寫）
        # 一律加上來源劃線ID。判斷依據是整本書的卡而非這次勾選的卡，所以不論勾了幾張，
        # 同一張卡跨次執行的檔名都一樣。
        clashes = sum(1 for t in book_titles if book_slug(t).casefold() == name.casefold())
        if clashes > 1:
            name += "_" + book_slug(card_source_id(saved.card))
        return os.path.join(self._output_dir, book_slug(saved.book_title), f"{name}.html")

    @staticmethod
    def _write(path: str, html: str) -> None:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        tmp = path + ".tmp"
        try:
            with open(tmp, "w", encoding="utf-8", newline="") as f:
                f.write(html)
            os.replace(tmp, path)
        except BaseException:
            # 寫到一半失敗不留殘檔（重跑時殘檔會被當成「已產生過」之外的垃圾）
            try:
                os.remove(tmp)
            except OSError:
                pass
            raise
