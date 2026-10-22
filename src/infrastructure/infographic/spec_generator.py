"""概念圖卡規格的地端 LLM 呼叫（Ollama）。

兩種呼叫，都只回「還沒整理過」的資料，整理與驗證交給 domain 的
`normalize_spec`／`normalize_book_map`：
  - `build_book_map`：每本書一次，判斷每張卡在全書的角色與卡片間關係；
  - `generate_card_spec`：每張要做圖的卡一次，濃縮成 ≤3 行文字＋圖示節點＋版面。

不碰產卡與審核的提示詞。模型出錯、逾時或回非 JSON 一律回 None，由呼叫端決定怎麼降級。
"""
import logging
import os
from typing import Dict, Optional, Sequence, Tuple

from zettelkasten_generator import ZettelkastenCard, _ollama_generate

from ...domain.entities.infographic_spec import MapEntry
from ...domain.services.infographic_rules import (
    ICON_NAMES,
    LAYOUTS,
    MAX_LABEL_CHARS,
    MAX_LINE_CHARS,
    normalize_book_map,
)
from .llm_json import parse_json_object

logger = logging.getLogger(__name__)

# 小模型的 context 有限：每張卡只帶內容前段進全書提示詞，16 張卡也塞得進去。
_CONTENT_PREVIEW_CHARS = 90

_LAYOUT_HINTS = {
    "flow": "依序發生的步驟或流程",
    "contrast": "兩種做法或觀點的對比（前半節點是 A、後半節點是 B）",
    "cause": "由原因一路推導出結果",
    "hierarchy": "由基礎到進階、或由大到小的層級",
    "cycle": "會自我強化、反覆循環的迴圈",
}


def build_card_prompt(card: ZettelkastenCard, book_title: str, theme: str) -> str:
    theme_line = f"全書主軸：{theme}\n" if theme else ""
    layouts = "\n".join(f"- {name}：{_LAYOUT_HINTS[name]}" for name in LAYOUTS)
    return f"""你是一位資訊圖表設計師，要把一張知識卡片濃縮成一張社群貼文用的概念圖。

書名：{book_title}
{theme_line}
卡片標題：{card.title}
卡片內容：{card.content}
原文劃線：{card.source_highlight}

只輸出一個 JSON 物件，不要任何說明：
{{"lines": ["第一行", "第二行"], "nodes": [{{"icon": "圖示名", "label": "短標籤"}}], "layout": "版面名"}}

規則：
- lines：最多 3 行，每行不超過 {MAX_LINE_CHARS} 字的完整短句。只能濃縮這張卡片已經說的內容，不得加入卡片沒說的結論或舉例。標題已經會顯示在圖上，lines 不要重複卡片標題。
- nodes：3 到 4 個，依序是這個概念的關鍵環節。icon 只能從下方圖示清單挑；label 是不超過 {MAX_LABEL_CHARS} 字的名詞片語，不要整句話。
- layout：只能從下列挑一個，選最貼近這張卡內容結構的：
{layouts}

可用圖示：{"、".join(ICON_NAMES)}
"""


def build_book_map_prompt(book_title: str, cards: Sequence[ZettelkastenCard]) -> str:
    listing = "\n".join(
        f"{i}. {c.title}｜{(c.content or '')[:_CONTENT_PREVIEW_CHARS]}"
        for i, c in enumerate(cards, start=1)
    )
    return f"""你是一位知識編輯。以下是同一本書的 {len(cards)} 張卡片筆記，前面的數字是編號。

書名：{book_title}

{listing}

請判斷每張卡片在全書的角色，以及卡片之間的關係。只輸出一個 JSON 物件，不要任何說明：
{{"theme": "全書主軸一句話", "cards": [{{"n": 1, "role": "主軸", "neighbors": [{{"relation": "導向", "n": 2}}]}}]}}

規則：
- 每張卡片都要有一筆，n 是上面的編號。
- role 只能是：主軸（貫穿全書的核心觀點，全書最多 3 張）、支柱（支撐主軸的關鍵概念）、案例（舉例、補充或細節）。
- neighbors 最多 3 個，沒有就給空陣列。relation 只能是：前提（本卡要成立，必須先理解的卡）、導向（讀完本卡自然接著讀的卡）、對照（觀點相反或互補的卡）。
- neighbors 裡的 n 必須是上面列出的編號，不可以是本卡自己。
"""


class InfographicSpecGenerator:
    def __init__(self, api_url: str, model: str, timeout_s: int = 300):
        self._api_url = api_url
        self._model = model
        self._timeout_s = timeout_s

    def _ask(self, prompt: str, *, label: str, num_predict: int) -> Optional[dict]:
        try:
            raw = _ollama_generate(
                prompt,
                api_url=self._api_url,
                model=self._model,
                timeout_s=self._timeout_s,
                temperature=0.2,
                num_predict=num_predict,
                num_ctx=int(os.getenv("OLLAMA_BATCH_NUM_CTX", "16384")),
                keep_alive=os.getenv("OLLAMA_KEEP_ALIVE", "30m"),
                think=False,
                json_mode=True,
                label=label,
            )
        except Exception as e:  # noqa: BLE001 — 單次 LLM 失敗由呼叫端降級，不中止整批
            logger.warning(f"Ollama {label} 呼叫失敗: {e}")
            return None
        parsed = parse_json_object(raw)
        if parsed is None:
            logger.warning(f"Ollama {label} 回應不是可解析的 JSON：{(raw or '')[:200]!r}")
        return parsed

    def build_book_map(
        self, book_title: str, cards: Sequence[ZettelkastenCard]
    ) -> Optional[Tuple[str, Dict[str, MapEntry]]]:
        """(全書主軸, {卡片標題: MapEntry})；模型沒給出可用回應回傳 None。"""
        if not cards:
            return None
        parsed = self._ask(
            build_book_map_prompt(book_title, cards), label="book-map", num_predict=2000
        )
        if parsed is None:
            return None
        return normalize_book_map(parsed, [c.title for c in cards])

    def generate_card_spec(
        self, card: ZettelkastenCard, book_title: str, theme: str
    ) -> Optional[dict]:
        """尚未整理的 {lines, nodes, layout}；交給 normalize_spec 收斂。"""
        return self._ask(
            build_card_prompt(card, book_title, theme), label="infographic", num_predict=700
        )
