"""
Zettelkasten Card Generator

This module generates Zettelkasten (slip-box) style note cards from book highlights.
It uses two *different* local models so that review is genuinely independent of
generation (cross-model review, not self-grading):

- `OLLAMA_MODEL` drafts the cards.
- `OLLAMA_REVIEW_MODEL` reviews them on four axes (一致性 / 正確性 / 分享性 /
  知識最小片段性). Only cards that pass are handed back for upload.
"""

import json
import logging
import os
import re
import time
import unicodedata
from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Optional, Tuple

import requests

# Setup logger
logger = logging.getLogger('kobo_notion_sync')


def _ollama_generate(
    prompt: str,
    *,
    api_url: str,
    model: str,
    timeout_s: int,
    temperature: float,
    num_predict: int,
    num_ctx: Optional[int] = None,
    keep_alive: Optional[str] = None,
    think: Optional[bool] = None,
    salvage_partial: bool = False,
    label: str = "ollama",
) -> Optional[str]:
    """One streaming POST to Ollama `/api/generate`, returning the accumulated text.

    Shared by card generation, classification and review so the hard-won details
    live in exactly one place:

    - `think=False` disables hidden reasoning on thinking models (gemma4:e4b
      otherwise burns the whole `num_predict` budget before emitting anything);
      a 400 response means the server rejects the parameter, so we retry without it.
    - in-stream `{"error": ...}` chunks are surfaced instead of silently truncating.
    - `done_reason == "length"` with empty output is called out explicitly.

    Returns None when nothing usable came back. `salvage_partial=True` returns
    whatever streamed in before a timeout/error — only for callers whose parser
    can safely handle a truncated response.
    """
    options: Dict[str, object] = {"temperature": temperature, "num_predict": num_predict}
    if num_ctx is not None:
        options["num_ctx"] = num_ctx

    payload: Dict[str, object] = {
        "model": model,
        "prompt": prompt,
        "stream": True,
        "options": options,
    }
    if keep_alive is not None:
        payload["keep_alive"] = keep_alive
    if think is not None:
        payload["think"] = think

    accumulated: List[str] = []
    start_time = time.monotonic()
    logger.debug(
        f"Ollama {label} request → url={api_url} model={model} "
        f"prompt_chars={len(prompt)} timeout={timeout_s}s num_predict={num_predict}"
    )

    def _partial() -> Optional[str]:
        text = "".join(accumulated)
        return text if (salvage_partial and text) else None

    try:
        response = requests.post(api_url, json=payload, timeout=timeout_s, stream=True)
        if response.status_code == 400 and "think" in payload:
            # older Ollama / non-thinking model may reject the parameter
            logger.info(f"Ollama {label}: 不接受 think 參數，改以預設模式重試")
            payload.pop("think")
            response = requests.post(api_url, json=payload, timeout=timeout_s, stream=True)

        if response.status_code != 200:
            elapsed = time.monotonic() - start_time
            logger.error(
                f"Ollama {label} error: status={response.status_code} "
                f"elapsed={elapsed:.1f}s body={response.text[:500]}"
            )
            return None

        for line in response.iter_lines(decode_unicode=True):
            if not line:
                continue
            chunk = json.loads(line)
            if chunk.get("error"):
                logger.error(f"Ollama {label} in-stream error: {chunk['error']}")
                break
            accumulated.append(chunk.get("response", ""))
            if chunk.get("done"):
                if chunk.get("done_reason") == "length" and not "".join(accumulated).strip():
                    logger.warning(
                        f"Ollama {label} hit num_predict with empty output "
                        "(thinking-model budget exhausted?)"
                    )
                break

        generated_text = "".join(accumulated)
        elapsed = time.monotonic() - start_time
        logger.debug(
            f"Ollama {label} response ← elapsed={elapsed:.1f}s chars={len(generated_text)}"
        )
        return generated_text

    except requests.exceptions.Timeout:
        elapsed = time.monotonic() - start_time
        partial = "".join(accumulated) if accumulated else "<no bytes received>"
        logger.error(
            f"Ollama {label} timeout after {elapsed:.1f}s "
            f"(url={api_url} model={model} prompt_chars={len(prompt)})"
        )
        logger.error(f"Partial response before timeout ({len(partial)} chars): {partial[:500]!r}")
        return _partial()
    except requests.exceptions.ConnectionError as e:
        elapsed = time.monotonic() - start_time
        logger.error(f"Cannot connect to Ollama for {label} after {elapsed:.1f}s (url={api_url}): {e}")
        return None
    except Exception as e:  # noqa: BLE001 — one bad response must not kill the run
        elapsed = time.monotonic() - start_time
        logger.exception(f"Error in Ollama {label} after {elapsed:.1f}s: {e}")
        return _partial()


# 章節參照消毒（K4）。污染唯一來源是 chapter_title_heuristics.extract_real_chapter_title()
# ——它拿劃線正文去猜章名、容忍到 150 字，只要含「：」就給 3 分信心，於是整段內文會被
# 當成章名印在卡片的 📖 callout 上。TOC 來源的章名是 Kobo 目錄的真實標題，不做任何判斷。
_CHAPTER_JUNK_CHARS = ('」', '「', '⋯', '。')
_CHAPTER_MAX_LEN = 25
_CHAPTER_UNKNOWN = 'Unknown'


def _clean_chapter_reference(raw: Optional[str], *, from_toc: bool) -> str:
    """回傳可信的章節標籤；判定為劃線內文時回空字串。

    `from_toc=True` 代表章名來自 Kobo 目錄（`Highlight.toc_chapter` 非 None），
    一律照留。其餘都是猜的，才套長度與標點的審查規則。
    """
    text = (raw or '').strip()
    if not text or text == _CHAPTER_UNKNOWN:
        return ''
    if from_toc:
        return text
    if len(text) > _CHAPTER_MAX_LEN or any(c in text for c in _CHAPTER_JUNK_CHARS):
        logger.debug(f"章節參照疑似劃線內文，已捨棄：{text[:30]}")
        return ''
    return text


@dataclass
class ZettelkastenCard:
    """Represents a single Zettelkasten note card"""
    id: str                           # Unique identifier
    title: str                        # Card title (5-20 characters)
    content: str                      # Card content (100-150 characters)
    source_highlight: str             # Original highlight text
    chapter_reference: str            # Source chapter name
    chapter_progress: float           # Reading progress (0.0 - 1.0)
    source_bookmark_id: str = ""      # Kobo BookmarkID of the source highlight
    tags: List[str] = field(default_factory=list)  # Free concept tags (2-3) → Key Word
    categories: List[str] = field(default_factory=list)  # Fixed Tags classification (1-2)
    icon: str = ""                    # Notion page icon emoji (from _ICON_PALETTE)
    # --- review gate (local only; never written to Notion) ---
    review_status: str = "pending"    # pending / passed / rejected
    review_scores: Dict[str, int] = field(default_factory=dict)  # 四維 1-5
    review_notes: str = ""            # reviewer's reason / revision direction
    review_model: str = ""            # which local model judged this card
    regenerated: bool = False         # was this the post-rejection second attempt
    created_at: datetime = field(default_factory=datetime.now)

    def to_dict(self) -> Dict:
        """Convert card to dictionary for serialization"""
        return {
            'id': self.id,
            'title': self.title,
            'content': self.content,
            'source_highlight': self.source_highlight,
            'chapter_reference': self.chapter_reference,
            'chapter_progress': self.chapter_progress,
            'source_bookmark_id': self.source_bookmark_id,
            'tags': self.tags,
            'categories': self.categories,
            'icon': self.icon,
            'review_status': self.review_status,
            'review_scores': self.review_scores,
            'review_notes': self.review_notes,
            'review_model': self.review_model,
            'regenerated': self.regenerated,
            'created_at': self.created_at.isoformat()
        }

    @classmethod
    def from_dict(cls, d: Dict) -> 'ZettelkastenCard':
        """Rebuild a card from a to_dict() payload (for local persistence/resume)."""
        raw_created = d.get('created_at')
        try:
            created_at = datetime.fromisoformat(raw_created) if raw_created else datetime.now()
        except (TypeError, ValueError):
            created_at = datetime.now()
        return cls(
            id=d.get('id', ''),
            title=d.get('title', ''),
            content=d.get('content', ''),
            source_highlight=d.get('source_highlight', ''),
            chapter_reference=d.get('chapter_reference', ''),
            chapter_progress=d.get('chapter_progress', 0.0) or 0.0,
            source_bookmark_id=d.get('source_bookmark_id', '') or '',
            tags=list(d.get('tags') or []),
            categories=list(d.get('categories') or []),
            icon=d.get('icon', '') or '',
            review_status=d.get('review_status', 'pending') or 'pending',
            review_scores=dict(d.get('review_scores') or {}),
            review_notes=d.get('review_notes', '') or '',
            review_model=d.get('review_model', '') or '',
            regenerated=bool(d.get('regenerated', False)),
            created_at=created_at,
        )


# ----- page icon 調色盤 -----
# 兩條不變條件（有測試把關，見 tests/unit/test_card_icons.py）：
#   1. 每個元素恰為 1 個 codepoint，不含 ZWJ / variation selector / 膚色修飾符
#      —— 多碼點序列是 Notion icon 最常見的拒收原因，會讓整張卡建立失敗。
#   2. 與分類自帶的 emoji 零交集 —— parser 靠「行內出現的調色盤 emoji 必為
#      模型挑的 icon」判讀，兩者相交這條規則就只是機率上成立。
# 讓模型「從清單裡挑」而非自由生成，因此不需要任何 codepoint 驗證邏輯。
_ICON_PALETTE = (
    "🧭", "🪞", "🎯", "🔑", "🧪", "🌱", "🔁", "🪜", "🧱", "🔍",
    "💡", "🧨", "🚧", "🪤", "🎭", "🧊", "🔥", "🌊", "🌉", "🚀",
    "🧬", "🦴", "🩺", "🪐", "📉", "🧯", "🪺", "🫧", "🪃", "🧲",
    "🪢", "🌀", "🍀", "🐘", "🦉", "🐜", "🌗", "🧵", "🪟", "🚪",
)
_ICON_PALETTE_SET = frozenset(_ICON_PALETTE)

# 只在 process 內對同一組分類警告一次，避免每本書都重複洗版 log。
_palette_overlap_warned: set = set()

# 關鍵字 → icon。模型沒挑或挑了清單外的值時接手；值必須取自 _ICON_PALETTE。
_ICON_KEYWORD_HINTS = (
    (("習慣", "循環", "重複", "迴圈"), "🔁"),
    (("風險", "陷阱", "偏誤", "謬誤"), "🪤"),
    (("方向", "選擇", "決策", "策略"), "🧭"),
    (("時間", "階段", "週期"), "🌗"),
    (("學習", "練習", "記憶"), "🧪"),
    (("關係", "連結", "網絡"), "🪢"),
    (("成長", "起點", "萌芽"), "🌱"),
    (("情緒", "動機", "慾望"), "🔥"),
    (("溝通", "表達", "敘事"), "🎭"),
    (("金錢", "投資", "資產", "成本"), "🧯"),
    (("結構", "系統", "框架"), "🧱"),
    (("觀察", "洞察", "發現"), "🔍"),
)

# 分類 text core → 預設 icon（同樣取自 _ICON_PALETTE，且刻意不用分類自帶的 emoji）。
_CATEGORY_ICON_DEFAULTS = {
    "心理學": "🪺",
    "學習技巧": "🧪",
    "商務": "🪐",
    "人生觀點": "🧭",
    "邏輯思考": "🪢",
    "哲學科學": "🧬",
    "軟體工程": "🧱",
    "行銷": "🎯",
    "專案管理": "🪜",
    "理財投資": "🧯",
}


class CardSelectionAlgorithm:
    """Algorithm for selecting the most valuable highlights for card generation"""

    # Keywords that indicate important content
    IMPORTANCE_KEYWORDS = [
        '重要', '核心', '原則', '關鍵', '本質', '根本', '基礎', '基本',
        '必須', '一定', '務必', '首先', '最重要', '記住', '注意',
        '總之', '因此', '所以', '結論', '總結', '關鍵點', '要點',
        'important', 'key', 'essential', 'fundamental', 'core', 'principle'
    ]

    def __init__(self, max_cards: int = 16, min_highlights: int = 10):
        self.max_cards = max_cards
        self.min_highlights = min_highlights

    def should_generate_cards(self, highlights: List[Dict]) -> bool:
        """Check if the number of highlights meets the minimum threshold"""
        return len(highlights) >= self.min_highlights

    def select_highlights(self, highlights: List[Dict]) -> List[Dict]:
        """
        Select the most valuable highlights for card generation.

        Selection process:
        1. Pre-filter: Remove too short (<30 chars) or too long (>500 chars) highlights
        2. Score each highlight based on multiple factors
        3. Distribute cards across chapters (max 3 per chapter)
        4. Select top-scoring highlights up to max_cards
        """
        if not self.should_generate_cards(highlights):
            logger.info(f"Highlight count ({len(highlights)}) below minimum threshold ({self.min_highlights}), skipping card generation")
            return []

        # Pre-filter highlights
        filtered_highlights = self._pre_filter(highlights)
        logger.info(f"After pre-filtering: {len(filtered_highlights)} highlights (from {len(highlights)})")

        if len(filtered_highlights) < self.min_highlights:
            logger.info(f"Filtered highlight count ({len(filtered_highlights)}) below minimum threshold")
            return []

        # Score all highlights
        scored_highlights = [(h, self._calculate_score(h)) for h in filtered_highlights]
        scored_highlights.sort(key=lambda x: x[1], reverse=True)

        # Select with chapter distribution constraint
        selected = self._select_with_chapter_distribution(scored_highlights)

        logger.info(f"Selected {len(selected)} highlights for card generation")
        return selected

    def _pre_filter(self, highlights: List[Dict]) -> List[Dict]:
        """Remove highlights that are too short or too long"""
        filtered = []
        for h in highlights:
            text = h.get('text', '')
            if text:
                text_len = len(text.strip())
                # Filter: 30-500 characters
                if 30 <= text_len <= 500:
                    filtered.append(h)
        return filtered

    def _calculate_score(self, highlight: Dict) -> float:
        """
        Calculate importance score for a highlight.

        Scoring weights:
        - Reader wrote an annotation: +5 points (strongest importance signal)
        - Ideal length (80-200 chars): +3 points
        - Chapter start/end position: +1.5 points
        - Contains importance keywords: +0.5 points per keyword (max 2)
        - Complete sentence: +1 point
        """
        score = 0.0
        text = highlight.get('text', '').strip()
        text_len = len(text)

        # A reader-written annotation is the strongest signal that this
        # highlight mattered to them — weight it heavily so it (almost) always
        # makes the cut.
        annotation = highlight.get('annotation')
        if annotation and annotation.strip():
            score += 5.0

        # Length scoring
        if 80 <= text_len <= 200:
            score += 3.0
        elif 60 <= text_len <= 250:
            score += 2.0
        elif 40 <= text_len <= 300:
            score += 1.0

        # Position scoring (beginning or end of chapter)
        chapter_progress = highlight.get('current_chapter_progress', 0.5)
        if chapter_progress is not None:
            if chapter_progress < 0.15 or chapter_progress > 0.85:
                score += 1.5

        # Keyword scoring
        keyword_count = 0
        text_lower = text.lower()
        for keyword in self.IMPORTANCE_KEYWORDS:
            if keyword.lower() in text_lower:
                keyword_count += 1
                if keyword_count >= 2:
                    break
        score += keyword_count * 0.5

        # Complete sentence bonus
        if text.endswith(('。', '！', '？', '.', '!', '?')):
            score += 1.0

        return score

    def _select_with_chapter_distribution(self, scored_highlights: List[Tuple[Dict, float]]) -> List[Dict]:
        """
        Select highlights ensuring even distribution across chapters.
        Each chapter can have at most 3 cards.
        """
        chapter_counts = {}
        selected = []
        max_per_chapter = 3

        for highlight, score in scored_highlights:
            if len(selected) >= self.max_cards:
                break

            chapter = highlight.get('chapter_name', 'Unknown')
            current_count = chapter_counts.get(chapter, 0)

            # Penalty for chapters that already have many cards
            if current_count >= max_per_chapter:
                continue

            selected.append(highlight)
            chapter_counts[chapter] = current_count + 1

        return selected


class ZettelkastenLLMEnhancer:
    """Uses Ollama (Gemma) to generate card titles and content"""

    def __init__(self, api_url: str = None, model: str = None):
        self.api_url = api_url or os.getenv('OLLAMA_API_URL', 'http://localhost:11434/api/generate')
        self.model = model or os.getenv('OLLAMA_MODEL', 'gemma4:31b')

    def generate_card(
        self,
        highlight: Dict,
        book_title: str = "",
        *,
        book_theme: str = "",
        revision_hint: str = "",
    ) -> Optional[ZettelkastenCard]:
        """
        Generate a Zettelkasten card from a highlight using Ollama.

        Returns a ZettelkastenCard with:
        - Title: 5-15 characters summarizing the core concept
        - Content: 100-150 characters atomic note in own words

        `book_theme` and `revision_hint` are optional context used when the
        review gate sends a rejected card back for a second attempt.
        """
        text = highlight.get('text', '').strip()
        chapter = highlight.get('chapter_name', 'Unknown')
        progress = highlight.get('chapter_progress', 0.0)
        annotation = (highlight.get('annotation') or '').strip()

        if not text:
            return None

        prompt = self._build_prompt(
            text, book_title, annotation,
            book_theme=book_theme, revision_hint=revision_hint,
        )

        generated_text = _ollama_generate(
            prompt,
            api_url=self.api_url,
            model=self.model,
            timeout_s=int(os.getenv('OLLAMA_TIMEOUT_SECONDS', '300')),
            temperature=0.7,
            num_predict=int(os.getenv('OLLAMA_NUM_PREDICT', '2000')),
            keep_alive=os.getenv('OLLAMA_KEEP_ALIVE', '30m'),
            label="card",
        )
        if not generated_text:
            return None

        title, content = self._parse_response(generated_text, text)
        if not (title and content):
            return None

        card_id = f"card_{datetime.now().strftime('%Y%m%d%H%M%S')}_{hash(text) % 10000:04d}"
        return ZettelkastenCard(
            id=card_id,
            title=title,
            content=content,
            source_highlight=text,
            chapter_reference=chapter,
            chapter_progress=progress or 0.0,
            source_bookmark_id=str(highlight.get('bookmark_id') or ''),
            tags=self._extract_tags(generated_text),
        )

    def _build_prompt(self, highlight_text: str, book_title: str = "",
                      annotation: str = "", *, book_theme: str = "",
                      revision_hint: str = "") -> str:
        """Build the prompt for card generation"""
        book_context = f"書名：{book_title}\n" if book_title else ""
        annotation_context = (
            f"\n讀者的個人註記（請務必納入這個觀點）：\n{annotation}\n"
            if annotation and annotation.strip() else ""
        )
        theme_context = (
            f"\n本書整體主軸（請讓這張卡與整本書的方向一致）：\n{book_theme.strip()}\n"
            if book_theme and book_theme.strip() else ""
        )
        revision_context = (
            f"\n⚠️ 上一版卡片已被審核退回，退回理由如下，請針對這些問題重寫：\n"
            f"{revision_hint.strip()}\n"
            if revision_hint and revision_hint.strip() else ""
        )

        return f"""你是一位卡片盒筆記專家。請為以下書籍劃線生成一張卡片筆記。

{book_context}劃線內容：
{highlight_text}
{annotation_context}{theme_context}{revision_context}
請生成卡片筆記，格式如下：
【標題】5-15個字，概括這段話的核心概念
【內容】100-150個字，用你自己的話重新闡述這個觀點的關鍵洞見，要確保這是一個完整、獨立的原子筆記
【標籤】2-3個概念標籤，用頓號分隔（例如：習慣、複利、系統思考），方便日後跨書用概念瀏覽

注意事項：
1. 標題要精準、簡潔，能讓人一眼看出核心概念
2. 內容要用自己的話重述，不要直接複製原文
3. 內容要包含原文的關鍵洞見，但要更精煉
4. 使用繁體中文，符合台灣用語習慣
5. 確保內容是獨立完整的，不需要回頭看原文也能理解
6. 標籤要用抽象的概念詞，不要用書名或章節名
7. 標籤之間只能用頓號（、）分隔，每個標籤 2-6 個字。絕對不要用冒號、破折號、
   中點或句號把標籤串在一起（❌「語言演化：社交結構」❌「習慣-複利」✅「習慣、複利」）

請直接輸出，不要加任何解釋："""

    _THINKING_PATTERNS = [
        re.compile(r'(?is)^\s*Thinking\.\.\..*?\.\.\.\s*done thinking\.\s*'),
        re.compile(r'(?is)<think>.*?</think>\s*'),
        re.compile(r'(?is)^\s*Thinking Process\s*:.*?(?=【|標題|###|$)'),
    ]

    @classmethod
    def _strip_thinking(cls, text: str) -> str:
        for pat in cls._THINKING_PATTERNS:
            text = pat.sub('', text)
        return text

    def _parse_response(
        self,
        response_text: str,
        original_text: str,
        allow_fallback: bool = True,
    ) -> Tuple[Optional[str], Optional[str]]:
        """Parse the LLM response to extract title and content.

        When `allow_fallback` is False, return (None, None) if the structured
        【標題】/【內容】 markers are missing — used by batch parsing so we can
        retry that specific card per-highlight instead of silently fabricating
        a title from the original text.
        """
        response_text = self._strip_thinking(response_text)
        title = None
        content = None

        # Try to extract title
        title_patterns = [
            r'【標題】\s*(.+?)(?=【|$)',
            r'標題[：:]\s*(.+?)(?=內容|$)',
            r'\*\*標題\*\*[：:]\s*(.+?)(?=\*\*|$)',
        ]

        for pattern in title_patterns:
            match = re.search(pattern, response_text, re.DOTALL)
            if match:
                title = match.group(1).strip()
                # Clean up the title
                title = re.sub(r'[\n\r]', '', title)
                title = title[:50] if len(title) > 50 else title  # Max 50 chars
                break

        # Try to extract content
        content_patterns = [
            r'【內容】\s*(.+?)(?=【|$)',
            r'內容[：:]\s*(.+?)(?=$)',
            r'\*\*內容\*\*[：:]\s*(.+?)(?=\*\*|$)',
        ]

        for pattern in content_patterns:
            match = re.search(pattern, response_text, re.DOTALL)
            if match:
                content = match.group(1).strip()
                # Clean up multiple newlines
                content = re.sub(r'\n{2,}', '\n', content)
                break

        if not allow_fallback:
            return title, content

        # Fallback: if no structured format, try to split by newline
        if not title or not content:
            lines = [ln.strip() for ln in response_text.strip().split('\n') if ln.strip()]
            if len(lines) >= 2:
                if not title:
                    title = lines[0][:50]
                if not content:
                    content = ' '.join(lines[1:])

        # Final fallback: generate simple title from original text
        if not title and original_text:
            title = original_text[:20] + "..." if len(original_text) > 20 else original_text

        if not content and original_text:
            content = original_text[:150] if len(original_text) > 150 else original_text

        return title, content

    _TAG_LINE = re.compile(r'【標籤】\s*(.+?)(?=【|###|\n\n|$)', re.DOTALL)
    # Separators the model actually uses instead of the 頓號 we ask for. Observed
    # in real output: "語言演化：社交結構：謊言藝術"（全形冒號）、
    # "資本結構—負債比率—金融風險"（破折號）、"・說服論述・故事架構"（中點）、
    # "環境心理學。習慣建立。行動科學"（句號）、"習慣-複利-一致性"（連字號）。
    _TAG_SPLIT = re.compile(r'[、,，/|｜:：;；。．.・·\-‑–—―−~～\s]+')
    # Punctuation to shave off a tag's edges once it has been split out.
    _TAG_TRIM = '#*「」『』〈〉()（）[]【】"\'`'
    # A "tag" longer than this is a sentence the model failed to split, not a concept.
    _TAG_MAX_LEN = 15

    @classmethod
    def _extract_tags(cls, text: str, limit: int = 3) -> List[str]:
        """Pull 2-3 concept tags from a 【標籤】 line; [] if absent.

        Models routinely ignore "separate with 、" and glue the tags together
        with colons, dashes, middle dots or full stops. Splitting on all of them
        is the difference between three browsable concepts and one unusable
        mega-tag in the Key Word column.
        """
        if not text:
            return []
        match = cls._TAG_LINE.search(text)
        if not match:
            return []
        return cls._split_tags(match.group(1), limit)

    @classmethod
    def _split_tags(cls, raw: str, limit: int = 3) -> List[str]:
        """Split one 標籤 string into clean, de-duplicated concept tags.

        Kept separate from `_extract_tags` so `tools/fix_card_tags.py` can
        re-split already-stored tags through exactly these rules — two copies
        of the separator list would drift apart on the first fix.
        """
        tags: List[str] = []
        for part in cls._TAG_SPLIT.split((raw or "").strip()):
            tag = part.strip().strip(cls._TAG_TRIM).strip()
            if not tag or len(tag) > cls._TAG_MAX_LEN or tag in tags:
                continue
            tags.append(tag)
            if len(tags) >= limit:
                break
        return tags

    # ----- E3: fixed-category classification (Tags multi_select) -----

    _CLASSIFY_SPLIT = re.compile(r'[、,，/|｜\s]+')
    _CLASSIFY_LINE = re.compile(r'CARD[_\- ]?(\d+)\s*[:：]\s*(.*)', re.IGNORECASE)

    @staticmethod
    def _category_core(name: str) -> str:
        """Text core of a category name: letters/digits only.

        Drops emoji, ZWJ, variation selectors and whitespace so that
        "💞心理學", "心理學" and a mangled "🧘人生觀點" all map to the same key —
        small local models rarely reproduce multi-codepoint emoji exactly.
        """
        return "".join(
            ch for ch in (name or "")
            if unicodedata.category(ch)[0] in ("L", "N")
        )

    @classmethod
    def _fallback_icon(cls, card: 'ZettelkastenCard') -> str:
        """模型沒給 icon（或給了清單外的值）時的決定性遞補。

        扛「同一本書的卡彼此可辨」的是 icon，而 icon 來自本地小模型，
        所以這不是裝飾而是保底 —— 保證 icon 永不空白。
        """
        haystack = "".join(card.tags or []) + (card.title or "")
        for keywords, emoji in _ICON_KEYWORD_HINTS:
            if any(k in haystack for k in keywords):
                return emoji
        for category in card.categories or []:
            emoji = _CATEGORY_ICON_DEFAULTS.get(cls._category_core(category))
            if emoji:
                return emoji
        return _ICON_PALETTE[0]

    @classmethod
    def _pick_palette_emoji(cls, text: str) -> str:
        """文字中第一個落在 _ICON_PALETTE 的 emoji，沒有則回空字串。

        因為調色盤與分類自帶的 emoji 零交集，且 prompt 給模型的分類名已去 emoji，
        所以行內出現的調色盤 emoji 必為模型挑的 icon —— 可以放心掃整行，
        不必依賴模型有沒有照 `｜` 格式輸出。
        """
        for ch in text or "":
            if ch in _ICON_PALETTE_SET:
                return ch
        return ""

    @staticmethod
    def _warn_if_categories_overlap_palette(categories: List[str]) -> None:
        """The palette-disjointness invariant (see _ICON_PALETTE) is only
        test-enforced for DEFAULT_TAG_CATEGORIES; a runtime override via
        ZETTELKASTEN_TAG_CATEGORIES can violate it (e.g. "🚀成長駭客" puts a
        palette emoji into the category text). When that happens,
        _pick_palette_emoji's whole-remainder scan can misread the category
        prefix as the model's icon pick, giving every card in that category
        the same icon. Cheap fix: warn once per process instead of
        restricting the scan (which would change already-well-tested parser
        behaviour) — see Finding 3 in the card-visual-richness final review.
        """
        overlapping = [
            c for c in categories if any(ch in _ICON_PALETTE_SET for ch in c)
        ]
        if not overlapping:
            return
        key = tuple(sorted(overlapping))
        if key in _palette_overlap_warned:
            return
        _palette_overlap_warned.add(key)
        logger.warning(
            "分類清單包含調色盤 emoji，可能讓 icon 解析誤判整個分類前綴為模型的"
            f"挑選結果（見 _ICON_PALETTE 不變條件）：{overlapping}"
        )

    _ICON_SEPARATOR = re.compile(r'[｜|]')

    @classmethod
    def _iter_matched_card_lines(cls, text: str, n: int):
        """Yield `(idx, remainder)` for each `CARD_i:` line whose index is in
        `1..n`, regardless of what (if anything) it goes on to contain.

        Shared by `_parse_classification` (which extracts categories/icon from
        `remainder`) and `classify_cards` (which only needs to know whether the
        raw response matched the expected format at all — see
        `_response_has_card_lines`). Keeping the line-matching logic in one
        place means the two can't drift apart on what counts as "matched".
        """
        if not text:
            return
        cleaned = cls._strip_thinking(text)
        for line in cleaned.splitlines():
            m = cls._CLASSIFY_LINE.search(line)
            if not m:
                continue
            try:
                idx = int(m.group(1))
            except ValueError:
                continue
            if 1 <= idx <= n:
                yield idx, m.group(2).strip()

    @classmethod
    def _response_has_card_lines(cls, text: str, n: int) -> bool:
        """Whether the raw response contains at least one recognizable
        `CARD_i:` line — i.e. whether it was parseable at all, independent of
        whether any card actually got a usable category or icon out of it.

        `classify_cards` returns this (not "did anything get extracted") so
        callers can tell a well-formed response where the model legitimately
        picked nothing usable apart from a genuinely unparseable/empty one.
        """
        return any(True for _ in cls._iter_matched_card_lines(text, n))

    @classmethod
    def _parse_classification(
        cls, text: str, n: int, allowed: List[str]
    ) -> List[Tuple[List[str], str]]:
        """Parse `CARD_i: 分類A、分類B｜emoji` lines into per-card (categories, icon).

        Category names are matched on their text core (emoji-insensitive) and
        written back as the canonical `allowed` value, so Notion multi_select
        options keep their emoji prefix. At most 2 categories per card; the icon
        is `""` when the model gave none or gave one outside the palette.
        Pure — no Ollama, unit-testable.
        """
        result: List[Tuple[List[str], str]] = [([], "") for _ in range(n)]
        if not text or not allowed:
            return result
        canonical = {cls._category_core(a): a for a in allowed if cls._category_core(a)}
        for idx, remainder in cls._iter_matched_card_lines(text, n):
            # 分類只看 ｜ 之前，icon 掃整行（模型常常不照格式）
            category_part = cls._ICON_SEPARATOR.split(remainder, maxsplit=1)[0]
            picked: List[str] = []
            for part in cls._CLASSIFY_SPLIT.split(category_part.strip()):
                name = canonical.get(cls._category_core(part))
                if name and name not in picked:
                    picked.append(name)
                if len(picked) >= 2:
                    break
            result[idx - 1] = (picked, cls._pick_palette_emoji(remainder))
        return result

    def _build_classification_prompt(
        self, cards: List[ZettelkastenCard], categories: List[str]
    ) -> str:
        # 給模型看純文字分類名（去 emoji），小模型較能一字不差照抄；
        # parse 時再以 text core 對回 canonical 名稱。
        allowed = "、".join(self._category_core(c) or c for c in categories)
        card_blocks = []
        for i, c in enumerate(cards, start=1):
            card_blocks.append(f"CARD_{i}：{c.title}｜{c.content}")
        cards_section = "\n".join(card_blocks)
        icons = " ".join(_ICON_PALETTE)
        return f"""你是一位知識分類助理。以下是 {len(cards)} 張卡片筆記，請為每張卡片挑選最貼切的分類與一個代表 emoji。

可用分類（只能從這裡挑，不可自創）：
{allowed}

可用 emoji（只能從這裡挑，不可自創）：
{icons}

卡片：
{cards_section}

規則：
1. 每張卡片挑 1-2 個最貼切的分類，只能從上面清單挑，用頓號（、）分隔
2. 如果沒有任何分類貼切，該卡片分類留空（不要硬塞、不要發明新分類）
3. 每張卡片再挑「一個」最能代表它的 emoji，只能從上面的 emoji 清單挑
4. 嚴格依照格式逐行輸出，每張卡片一行：CARD_編號：分類｜emoji
5. 不要加任何解釋或結語

請直接輸出："""

    def classify_cards(
        self, cards: List[ZettelkastenCard], categories: List[str],
        book_title: str = "", *, apply_icon_fallback: bool = True,
    ) -> bool:
        """Assign fixed-category Tags + a page icon to each card in place.

        One Ollama call per book. Returns whether the raw response contained at
        least one recognizable `CARD_i:` line (see `_response_has_card_lines`) —
        callers (the visual backfill tool) use it to tell "the model responded
        but legitimately picked nothing usable for any card" apart from "the
        whole call failed / came back empty / unparseable", so only the latter
        gets retried later instead of being frozen with rule-based icons. A
        well-formed response where every card's categories/icon end up empty
        still returns True.

        No-op returning False if there are no cards or no category list. On any
        Ollama failure the cards keep empty `categories`; `icon` still gets a
        deterministic fallback so it is never blank — unless the caller opts
        out (see `apply_icon_fallback` below).

        `apply_icon_fallback` (default True, matching every production caller):
        when False, `card.icon` is left as the model's raw pick — empty string
        if it didn't choose one — instead of being backfilled with
        `_fallback_icon` here. This call also overwrites `card.categories`
        with the model's own parse, which `_fallback_icon` reads from; a
        caller that needs the fallback to reason about the card's *real*
        categories (e.g. the visual backfill tool restoring the actual Notion
        Tags right after this returns) must pass False and compute the
        fallback itself afterward — otherwise the fallback baked in here
        would already reflect the model's (possibly hallucinated) categories.
        """
        if not cards or not categories:
            return False

        self._warn_if_categories_overlap_palette(categories)

        prompt = self._build_classification_prompt(cards, categories)
        logger.info(
            f"Ollama classify request → model={self.model} cards={len(cards)} "
            f"prompt_chars={len(prompt)}"
        )
        raw = _ollama_generate(
            prompt,
            api_url=self.api_url,
            model=self.model,
            timeout_s=int(os.getenv('OLLAMA_BATCH_TIMEOUT_SECONDS', '600')),
            temperature=0.3,
            num_predict=1000,
            num_ctx=int(os.getenv('OLLAMA_BATCH_NUM_CTX', '16384')),
            keep_alive=os.getenv('OLLAMA_KEEP_ALIVE', '30m'),
            think=False,
            salvage_partial=True,
            label="classify",
        ) or ""
        logger.debug(f"Ollama classify raw response ({len(raw)} chars): {raw[:500]}")
        parsed = self._parse_classification(raw, len(cards), categories)
        assigned = 0
        model_icons = 0
        for card, (cats, icon) in zip(cards, parsed):
            card.categories = cats
            # 先寫 categories，_fallback_icon 才吃得到分類預設
            card.icon = (icon or self._fallback_icon(card)) if apply_icon_fallback else icon
            if cats:
                assigned += 1
            if icon:
                model_icons += 1
        parsed_ok = self._response_has_card_lines(raw, len(cards))
        logger.info(
            f"Ollama classify done: {assigned}/{len(cards)} cards tagged, "
            f"{model_icons}/{len(cards)} icons from model "
            f"({len(cards) - model_icons} via fallback)"
        )
        return parsed_ok

    def _build_batch_prompt(self, highlights: List[Dict], book_title: str = "") -> str:
        n = len(highlights)
        book_context = f"書名：{book_title}\n\n" if book_title else ""

        highlight_blocks = []
        for i, h in enumerate(highlights, start=1):
            text = (h.get('text') or '').strip()
            annotation = (h.get('annotation') or '').strip()
            block = f"---\n劃線 {i}：\n{text}"
            if annotation:
                block += f"\n（讀者註記，請納入觀點）：{annotation}"
            highlight_blocks.append(block)
        highlights_section = "\n".join(highlight_blocks) + "\n---"

        format_lines = []
        for i in range(1, n + 1):
            format_lines.append(
                f"### CARD_{i}\n【標題】5-15個字...\n【內容】100-150個字...\n"
                f"【標籤】2-3個概念標籤，用頓號分隔"
            )
        format_example = "\n".join(format_lines)

        return f"""你是一位卡片盒筆記專家。請為以下書籍的 {n} 條劃線，各生成一張卡片筆記。

{book_context}{highlights_section}

請依序為每一條劃線輸出一張卡片，嚴格依照以下格式（千萬不要省略分隔符）：

{format_example}

規則：
1. 每張卡的【標題】【內容】都要用繁體中文、台灣用語
2. 內容要用自己的話重述，不要照抄原文
3. {n} 張卡都要給，不可省略、不可合併
4. 分隔符只用 ### CARD_編號，不要加其他註解、結語或總結
5. 標題 5-15 個字，內容 100-150 個字
6. 【標籤】之間只能用頓號（、）分隔，每個標籤 2-6 個字。絕對不要用冒號、破折號、
   中點或句號把標籤串在一起（❌「語言演化：社交結構」❌「習慣-複利」✅「習慣、複利」）

請直接輸出，不要在格式外加任何解釋："""

    def _parse_batch_response(
        self,
        response_text: str,
        highlights: List[Dict],
    ) -> List[Optional[ZettelkastenCard]]:
        """Parse a batch response into N cards aligned to the input highlights.

        Missing / malformed cards are returned as None at their index so the
        caller can fall back per-highlight.
        """
        cleaned = self._strip_thinking(response_text)

        # Split on "### CARD_<n>" and capture the index so we can align.
        splitter = re.compile(r'###\s*CARD[_\- ]?(\d+)\s*', re.IGNORECASE)
        parts = splitter.split(cleaned)
        # parts = [preamble, idx1, body1, idx2, body2, ...]
        segments: Dict[int, str] = {}
        for i in range(1, len(parts) - 1, 2):
            try:
                idx = int(parts[i])
            except ValueError:
                continue
            segments[idx] = parts[i + 1].strip()

        results: List[Optional[ZettelkastenCard]] = [None] * len(highlights)
        for i, highlight in enumerate(highlights, start=1):
            segment = segments.get(i)
            if not segment:
                logger.warning(f"Batch parse: missing CARD_{i} in response")
                continue
            original = (highlight.get('text') or '').strip()
            title, content = self._parse_response(segment, original, allow_fallback=False)
            if not title or not content:
                logger.warning(f"Batch parse: CARD_{i} missing title or content")
                continue
            chapter = highlight.get('chapter_name', 'Unknown')
            progress = highlight.get('chapter_progress', 0.0) or 0.0
            card_id = f"card_{datetime.now().strftime('%Y%m%d%H%M%S')}_{i:02d}_{hash(original) % 10000:04d}"
            results[i - 1] = ZettelkastenCard(
                id=card_id,
                title=title,
                content=content,
                source_highlight=original,
                chapter_reference=chapter,
                chapter_progress=progress,
                source_bookmark_id=str(highlight.get('bookmark_id') or ''),
                tags=self._extract_tags(segment),
            )
        return results

    def _batch_generate_single_call(
        self,
        highlights: List[Dict],
        book_title: str = "",
    ) -> List[Optional[ZettelkastenCard]]:
        """One POST to Ollama that asks for all N cards at once."""
        if not highlights:
            return []

        prompt = self._build_batch_prompt(highlights, book_title)
        num_ctx = int(os.getenv('OLLAMA_BATCH_NUM_CTX', '16384'))

        logger.info(
            f"Ollama batch request → model={self.model} highlights={len(highlights)} "
            f"prompt_chars={len(prompt)} num_ctx={num_ctx}"
        )

        # salvage_partial: a truncated batch response still yields the cards that
        # made it through; _parse_batch_response returns None for the rest.
        generated_text = _ollama_generate(
            prompt,
            api_url=self.api_url,
            model=self.model,
            timeout_s=int(os.getenv('OLLAMA_BATCH_TIMEOUT_SECONDS', '600')),
            temperature=0.7,
            num_predict=int(os.getenv('OLLAMA_BATCH_NUM_PREDICT', '-1')),
            num_ctx=num_ctx,
            keep_alive=os.getenv('OLLAMA_KEEP_ALIVE', '30m'),
            salvage_partial=True,
            label="batch",
        )
        if not generated_text:
            return [None] * len(highlights)

        logger.info(f"Ollama batch response ← chars={len(generated_text)}")
        return self._parse_batch_response(generated_text, highlights)

    def batch_generate(self, highlights: List[Dict], book_title: str = "") -> List[ZettelkastenCard]:
        """Generate cards for multiple highlights via a single batched Ollama call.

        Strategy:
        1. If estimated tokens exceed context, split the batch in half and recurse.
        2. Issue one POST that asks the model for all N cards.
        3. Any card that came back missing or malformed is retried per-highlight.
        """
        if not highlights:
            return []

        num_ctx = int(os.getenv('OLLAMA_BATCH_NUM_CTX', '16384'))
        # Rough estimate: Chinese ~1.5 tokens/char, plus per-card thinking + output budget.
        input_chars = sum(len((h.get('text') or '')) for h in highlights) + len(book_title)
        est_input_tokens = int(input_chars * 1.5) + 600  # prompt overhead
        est_output_tokens = len(highlights) * 600 + 1500  # cards + thinking buffer
        est_total = est_input_tokens + est_output_tokens

        if est_total > num_ctx and len(highlights) > 1:
            mid = len(highlights) // 2
            logger.warning(
                f"batch_generate: estimated {est_total} tokens exceeds num_ctx={num_ctx}, "
                f"splitting {len(highlights)} → {mid} + {len(highlights) - mid}"
            )
            left = self.batch_generate(highlights[:mid], book_title)
            right = self.batch_generate(highlights[mid:], book_title)
            return left + right

        logger.info(
            f"batch_generate: {len(highlights)} highlights, "
            f"est_tokens~{est_total} / num_ctx={num_ctx}"
        )

        cards = self._batch_generate_single_call(highlights, book_title)

        missing_indices = [i for i, c in enumerate(cards) if c is None]
        if missing_indices:
            logger.warning(
                f"Batch produced {len(cards) - len(missing_indices)}/{len(cards)} cards; "
                f"retrying {len(missing_indices)} per-highlight"
            )
            for i in missing_indices:
                logger.info(f"Per-highlight fallback for card {i + 1}/{len(highlights)}...")
                card = self.generate_card(highlights[i], book_title)
                if card:
                    cards[i] = card

        produced = [c for c in cards if c is not None]
        logger.info(f"batch_generate done: {len(produced)}/{len(highlights)} cards produced")
        return produced


@dataclass
class CardReview:
    """Verdict from the local review model for one card.

    Four axes, each 1-5. A card passes only when *every* axis clears the
    threshold: a card that is factually impeccable but crams three ideas into
    one note is still not a Zettelkasten card, so an average would hide it.
    """
    consistency: int    # 標題↔內容↔原文不矛盾，且與全書主軸同向、不與其他卡重複
    correctness: int    # 忠於原文，沒有推論出原文沒說的事
    shareability: int   # 離開原書脈絡也讀得懂、值得單獨分享
    atomicity: int      # 只講一個概念，是最小知識片段
    notes: str = ""
    model: str = ""

    AXES = ('consistency', 'correctness', 'shareability', 'atomicity')

    def scores(self) -> Dict[str, int]:
        return {axis: getattr(self, axis) for axis in self.AXES}

    def passed(self, threshold: int) -> bool:
        return all(getattr(self, axis) >= threshold for axis in self.AXES)

    def summary(self) -> str:
        return (
            f"一致性 {self.consistency} / 正確性 {self.correctness} / "
            f"分享性 {self.shareability} / 最小片段性 {self.atomicity}"
        )


class CardReviewer:
    """Reviews draft cards with a *different* local model than the one that wrote them.

    Cross-model on purpose: a model grading its own output mostly rediscovers
    its own blind spots. Two stages per book:

    1. `summarize_book` — one call distilling the book's overall direction, so
       that single-card review can tell "off-topic for this book" from "fine".
    2. `review` — one call per card, judging four axes against the source
       highlight, the book theme and the sibling card titles.
    """

    _DEFAULT_REVIEW_MODEL = 'qwen3:8b'

    def __init__(self, api_url: str = None, model: str = None,
                 threshold: int = None, generator_model: str = None):
        self.api_url = api_url or os.getenv('OLLAMA_API_URL', 'http://localhost:11434/api/generate')
        self.model = model or os.getenv('OLLAMA_REVIEW_MODEL', self._DEFAULT_REVIEW_MODEL)
        self.threshold = (
            threshold if threshold is not None
            else int(os.getenv('ZETTELKASTEN_REVIEW_MIN_SCORE', '4'))
        )
        self.timeout_s = int(os.getenv('OLLAMA_REVIEW_TIMEOUT_SECONDS', '300'))
        logger.info(
            f"卡片審核閘門：產卡模型={generator_model or '?'} 審核模型={self.model} "
            f"每項門檻={self.threshold}/5"
        )
        if generator_model and generator_model == self.model:
            logger.warning(
                f"審核模型與產卡模型相同（{self.model}）— 等於讓模型改自己的考卷。"
                "建議把 OLLAMA_REVIEW_MODEL 設成另一個地端模型。"
            )

    # ----- availability -----

    def _tags_url(self) -> str:
        return self.api_url.replace('/api/generate', '/api/tags')

    def is_available(self) -> bool:
        """True only if Ollama answers *and* the review model is actually pulled.

        Distinguishing "service down" from "model not pulled" matters: both are
        hard failures for the gate, but only one is fixed by `ollama pull`.
        """
        url = self._tags_url()
        try:
            response = requests.get(url, timeout=5)
        except requests.RequestException as e:
            logger.error(f"審核模型不可用：連不上 Ollama（{url}）：{e}")
            return False
        if response.status_code != 200:
            logger.error(f"審核模型不可用：Ollama {url} 回 {response.status_code}")
            return False
        try:
            installed = [m.get('name', '') for m in (response.json().get('models') or [])]
        except ValueError:
            logger.error(f"審核模型不可用：{url} 回傳非 JSON")
            return False
        if not self._model_installed(self.model, installed):
            logger.error(
                f"審核模型不可用：{self.model} 尚未安裝"
                f"（已安裝：{'、'.join(installed) or '無'}）。"
                f"請先執行 `ollama pull {self.model}`。"
            )
            return False
        return True

    @staticmethod
    def _model_installed(model: str, installed: List[str]) -> bool:
        """`qwen3:8b` must match exactly; a bare `qwen3` also matches `qwen3:latest`."""
        if not model:
            return False
        if model in installed:
            return True
        if ':' not in model:
            return any(name.split(':')[0] == model for name in installed)
        return False

    # ----- stage 1: book theme -----

    def summarize_book(self, cards: List[ZettelkastenCard], book_title: str = "") -> str:
        """Distil the book's overall direction from its draft cards.

        Returns "" when the model gives nothing back — the caller degrades to
        using only the sibling titles as context. The service being reachable
        means this is not a gate failure, just thinner context.
        """
        if not cards:
            return ""
        raw = _ollama_generate(
            self._build_theme_prompt(cards, book_title),
            api_url=self.api_url,
            model=self.model,
            timeout_s=self.timeout_s,
            temperature=0.2,
            num_predict=800,
            num_ctx=int(os.getenv('OLLAMA_BATCH_NUM_CTX', '16384')),
            keep_alive=os.getenv('OLLAMA_KEEP_ALIVE', '30m'),
            think=False,
            salvage_partial=True,
            label="theme",
        )
        theme = ZettelkastenLLMEnhancer._strip_thinking(raw or "").strip()
        if not theme:
            logger.warning(f"'{book_title}' 全書主軸抽取失敗，審核改以卡片標題清單為脈絡")
        else:
            logger.info(f"'{book_title}' 全書主軸：{theme[:120]}")
        return theme

    @staticmethod
    def _build_theme_prompt(cards: List[ZettelkastenCard], book_title: str = "") -> str:
        book_context = f"書名：{book_title}\n\n" if book_title else ""
        blocks = "\n".join(
            f"{i}. {c.title}｜{c.content}" for i, c in enumerate(cards, start=1)
        )
        return f"""你是一位知識編輯。以下是從同一本書擷取出來的 {len(cards)} 張卡片筆記草稿。

{book_context}{blocks}

請用 150 字以內歸納：
1. 這本書的核心主軸是什麼（一到兩句話）
2. 反覆出現的核心概念有哪些（條列 3-5 個關鍵詞）

只輸出歸納結果，不要評論個別卡片，不要加開場白："""

    # ----- stage 2: per-card review -----

    def review(
        self,
        card: ZettelkastenCard,
        *,
        book_title: str = "",
        book_theme: str = "",
        sibling_titles: Optional[List[str]] = None,
    ) -> Optional[CardReview]:
        """Judge one card. None means the review itself failed (≠ a low score)."""
        raw = _ollama_generate(
            self._build_review_prompt(card, book_title, book_theme, sibling_titles or []),
            api_url=self.api_url,
            model=self.model,
            timeout_s=self.timeout_s,
            temperature=0.2,
            num_predict=1000,
            num_ctx=int(os.getenv('OLLAMA_BATCH_NUM_CTX', '16384')),
            keep_alive=os.getenv('OLLAMA_KEEP_ALIVE', '30m'),
            think=False,
            salvage_partial=True,
            label="review",
        )
        if not raw:
            return None
        review = self._parse_review(raw)
        if review is None:
            logger.warning(f"審核回應無法解析（卡片：{card.title}）：{raw[:200]!r}")
            return None
        review.model = self.model
        return review

    def _build_review_prompt(
        self,
        card: ZettelkastenCard,
        book_title: str,
        book_theme: str,
        sibling_titles: List[str],
    ) -> str:
        book_context = f"書名：{book_title}\n" if book_title else ""
        theme_section = (
            f"\n本書整體主軸：\n{book_theme.strip()}\n"
            if book_theme and book_theme.strip() else ""
        )
        siblings = [t for t in sibling_titles if t]
        sibling_section = (
            "\n同一本書其他卡片的標題（用來判斷這張卡是否離題或與別張重複）：\n"
            + "\n".join(f"- {t}" for t in siblings) + "\n"
            if siblings else ""
        )
        return f"""你是嚴格的卡片盒筆記審核員。請審核以下這張卡片，決定它是否夠格成為一則獨立的知識卡片。

{book_context}{theme_section}{sibling_section}
原始劃線（唯一的事實依據）：
{card.source_highlight}

卡片標題：{card.title}

卡片內容：
{card.content}

請針對四個面向各給 1 到 5 分（1=嚴重不合格，3=剛好可接受，5=優秀）：

1. consistency（一致性）：標題、內容、原始劃線三者不互相矛盾；且這張卡與「本書整體主軸」方向一致，沒有離題，也沒有和其他卡片重複同一個論點。
2. correctness（正確性）：內容忠於原始劃線的意涵，沒有加入原文沒說的因果、數據或結論，沒有誤讀，沒有混入無關語言或雜訊字元。
3. shareability（分享性）：不看原書脈絡也讀得懂，是一段可以單獨拿出來分享的完整想法，不是需要補充才成立的殘句。
4. atomicity（知識最小片段性）：這張卡只講一個概念。若同時塞了兩個以上可以各自獨立成卡的概念，這項最多給 2 分。

評分要嚴格，不要因為文句通順就給高分。

只輸出以下 JSON，不要加任何說明文字，不要加 markdown 標記：
{{"consistency": 分數, "correctness": 分數, "shareability": 分數, "atomicity": 分數, "notes": "若有任一項低於 3 分，具體說明問題出在哪裡、應該怎麼改寫；否則留空字串"}}"""

    # ----- parsing (pure, unit-tested) -----

    _AXIS_KEYS = ('consistency', 'correctness', 'shareability', 'atomicity')
    _CODE_FENCE = re.compile(r'```(?:json)?\s*(.*?)```', re.DOTALL)

    @classmethod
    def _parse_review(cls, text: str) -> Optional[CardReview]:
        """Parse the reviewer's JSON verdict; None if it cannot be trusted.

        Tolerates thinking prefixes and ```json fences, but *not* missing or
        out-of-range scores — a half-parsed verdict must not be mistaken for a
        real judgement, because the gate treats "unparseable" as "not approved".
        """
        if not text:
            return None
        cleaned = ZettelkastenLLMEnhancer._strip_thinking(text)
        fence = cls._CODE_FENCE.search(cleaned)
        if fence:
            cleaned = fence.group(1)

        data = cls._loads_json(cleaned)
        if not isinstance(data, dict):
            return None

        scores: Dict[str, int] = {}
        for key in cls._AXIS_KEYS:
            value = data.get(key)
            if isinstance(value, bool):
                return None
            if isinstance(value, str) and value.strip().isdigit():
                value = int(value.strip())
            if not isinstance(value, (int, float)):
                return None
            value = int(value)
            if not 1 <= value <= 5:
                return None
            scores[key] = value

        notes = data.get('notes') or ''
        return CardReview(notes=str(notes).strip(), **scores)

    @staticmethod
    def _loads_json(text: str) -> Optional[Dict]:
        """Innermost brace pair first, then outermost — small models like to
        wrap the verdict in prose or nest an example object."""
        candidates: List[str] = []
        match = re.search(r'\{[^{}]*\}', text, re.DOTALL)
        if match:
            candidates.append(match.group())
        start, end = text.find('{'), text.rfind('}')
        if start != -1 and end > start:
            candidates.append(text[start:end + 1])
        for candidate in candidates:
            try:
                parsed = json.loads(candidate)
            except (ValueError, TypeError):
                continue
            if isinstance(parsed, dict):
                return parsed
        return None


@dataclass
class GenerationResult:
    """Cards that cleared the review gate, and the ones that did not.

    Only `passed` is ever uploaded; `rejected` is kept so the local JSON records
    what was thrown away and why.
    """
    passed: List[ZettelkastenCard] = field(default_factory=list)
    rejected: List[ZettelkastenCard] = field(default_factory=list)


class ZettelkastenCardGenerator:
    """
    Main class that orchestrates the entire card generation process.

    Flow:
    1. Check if highlights meet minimum threshold
    2. Select best highlights using CardSelectionAlgorithm
    3. Generate draft cards using ZettelkastenLLMEnhancer (OLLAMA_MODEL)
    4. Review gate using CardReviewer (OLLAMA_REVIEW_MODEL) — a rejected card
       gets one regeneration attempt carrying the reviewer's notes, then it is
       dropped. Only survivors are returned for upload.
    5. Classify the survivors into the fixed Tags categories
    """

    def __init__(self,
                 max_cards: int = None,
                 min_highlights: int = None,
                 tag_categories: Optional[List[str]] = None,
                 enhancer: Optional[ZettelkastenLLMEnhancer] = None,
                 reviewer: Optional[CardReviewer] = None):

        self.max_cards = max_cards or int(os.getenv('ZETTELKASTEN_MAX_CARDS', '16'))
        self.min_highlights = min_highlights or int(os.getenv('ZETTELKASTEN_MIN_HIGHLIGHTS', '10'))
        # Fixed Tags classification list (DI from settings); empty → classification off.
        self.tag_categories = list(tag_categories or [])
        self.max_regen = int(os.getenv('ZETTELKASTEN_REVIEW_MAX_REGEN', '1'))

        self.selector = CardSelectionAlgorithm(
            max_cards=self.max_cards,
            min_highlights=self.min_highlights
        )
        # Injectable so the gate can be exercised without a live Ollama.
        self.enhancer = enhancer or ZettelkastenLLMEnhancer()
        self.reviewer = reviewer or CardReviewer(generator_model=self.enhancer.model)

    def generate_cards(self, highlights: List[Dict], book_title: str = "") -> List[ZettelkastenCard]:
        """Cards that passed review. Thin wrapper kept for the legacy entry point."""
        return self.generate_cards_with_review(highlights, book_title).passed

    def generate_cards_with_review(
        self, highlights: List[Dict], book_title: str = "",
    ) -> GenerationResult:
        """
        Generate Zettelkasten cards from book highlights, gated on review.

        Returns a GenerationResult; `passed` is what may go to Notion. All state
        travels through arguments and return values because books are synced
        concurrently through a shared generator instance.
        """
        logger.info(f"Starting Zettelkasten card generation for '{book_title}'")
        logger.info(
            f"Total highlights: {len(highlights)}, Max cards: {self.max_cards}, "
            f"Min threshold: {self.min_highlights}"
        )

        # Step 1: Check threshold
        if not self.selector.should_generate_cards(highlights):
            logger.info(
                f"Skipping card generation: only {len(highlights)} highlights "
                f"(minimum: {self.min_highlights})"
            )
            return GenerationResult()

        # Step 2: Select best highlights
        selected_highlights = self.selector.select_highlights(highlights)
        if not selected_highlights:
            logger.info("No highlights selected after filtering")
            return GenerationResult()

        logger.info(f"Selected {len(selected_highlights)} highlights for card generation")

        # Step 3: the gate must be usable before we spend minutes drafting.
        if not self.reviewer.is_available():
            logger.error(
                f"審核模型不可用 → '{book_title}' 不產卡也不上傳"
                "（卡片必須通過審核才能進 Notion）"
            )
            return GenerationResult()

        # Step 4: Generate draft cards with the drafting model
        logger.info("Generating draft cards with Ollama...")
        draft_cards = self.enhancer.batch_generate(selected_highlights, book_title)

        if not draft_cards:
            logger.warning("No cards generated from Ollama")
            return GenerationResult()

        logger.info(f"Generated {len(draft_cards)} draft cards")

        # Step 5: Review gate (book theme first, then card by card)
        book_theme = self.reviewer.summarize_book(draft_cards, book_title)
        result = self._run_review_gate(
            draft_cards, selected_highlights, book_title, book_theme
        )

        # Step 6: Classify survivors into fixed Tags categories (one call per book)
        if result.passed and self.tag_categories:
            logger.info("Classifying cards into fixed Tags categories...")
            self.enhancer.classify_cards(result.passed, self.tag_categories, book_title)

        logger.info(
            f"'{book_title}' 審核結果：通過 {len(result.passed)} 張／"
            f"退回 {len(result.rejected)} 張（草稿共 {len(draft_cards)} 張）"
        )
        return result

    # ----- review gate internals -----

    def _run_review_gate(
        self,
        draft_cards: List[ZettelkastenCard],
        selected_highlights: List[Dict],
        book_title: str,
        book_theme: str,
    ) -> GenerationResult:
        by_id, by_text = self._index_highlights(selected_highlights)
        draft_titles = [c.title for c in draft_cards]
        result = GenerationResult()

        for i, card in enumerate(draft_cards):
            logger.info(f"審核卡片 {i + 1}/{len(draft_cards)}：{card.title}")
            siblings = [t for j, t in enumerate(draft_titles) if j != i]
            current = card

            for attempt in range(self.max_regen + 1):
                review = self.reviewer.review(
                    current,
                    book_title=book_title,
                    book_theme=book_theme,
                    sibling_titles=siblings,
                )
                if review is not None:
                    self._apply_review(current, review)
                    if review.passed(self.reviewer.threshold):
                        current.review_status = 'passed'
                        result.passed.append(current)
                        logger.info(f"  ✅ 通過（{review.summary()}）")
                        break
                    logger.info(
                        f"  ⚠️ 未通過（{review.summary()}）：{review.notes[:120]}"
                    )
                else:
                    current.review_notes = current.review_notes or "審核回應無法解析"
                    logger.warning("  ⚠️ 審核回應無法解析，視同未通過")

                if attempt >= self.max_regen:
                    self._reject(result, current, "重產後仍未通過")
                    break

                highlight = self._find_highlight(current, by_id, by_text)
                if highlight is None:
                    self._reject(result, current, "找不到對應的原始劃線，無法重產")
                    break

                logger.info("  🔄 帶審核意見重產一次")
                remade = self.enhancer.generate_card(
                    highlight,
                    book_title,
                    book_theme=book_theme,
                    revision_hint=current.review_notes,
                )
                if remade is None:
                    self._reject(result, current, "重產失敗")
                    break
                remade.regenerated = True
                current = remade

        return result

    @staticmethod
    def _reject(result: GenerationResult, card: ZettelkastenCard, reason: str) -> None:
        card.review_status = 'rejected'
        result.rejected.append(card)
        logger.info(f"  ❌ 丟棄（{reason}）：{card.title}")

    @staticmethod
    def _apply_review(card: ZettelkastenCard, review: CardReview) -> None:
        card.review_scores = review.scores()
        card.review_notes = review.notes
        card.review_model = review.model

    @staticmethod
    def _index_highlights(highlights: List[Dict]) -> Tuple[Dict[str, Dict], Dict[str, Dict]]:
        by_id: Dict[str, Dict] = {}
        by_text: Dict[str, Dict] = {}
        for h in highlights:
            bookmark_id = str(h.get('bookmark_id') or '')
            if bookmark_id:
                by_id[bookmark_id] = h
            text = (h.get('text') or '').strip()
            if text:
                by_text[text] = h
        return by_id, by_text

    @staticmethod
    def _find_highlight(
        card: ZettelkastenCard,
        by_id: Dict[str, Dict],
        by_text: Dict[str, Dict],
    ) -> Optional[Dict]:
        """Map a card back to the highlight it came from.

        `batch_generate` drops cards it failed to parse, so positional alignment
        with the selected highlights is unreliable — go through the bookmark id,
        falling back to the highlight text.
        """
        if card.source_bookmark_id and card.source_bookmark_id in by_id:
            return by_id[card.source_bookmark_id]
        return by_text.get((card.source_highlight or '').strip())



def check_ollama_availability() -> bool:
    """Check if Ollama service is running and accessible"""
    api_url = os.getenv('OLLAMA_API_URL', 'http://localhost:11434/api/tags')
    try:
        response = requests.get(api_url.replace('/api/generate', '/api/tags'), timeout=5)
        return response.status_code == 200
    except requests.RequestException:
        return False


# For testing
if __name__ == "__main__":
    # Setup basic logging for testing
    logging.basicConfig(level=logging.INFO)

    print("Checking service availability...")
    print(f"Ollama available: {check_ollama_availability()}")
    print(f"Review model ready: {CardReviewer().is_available()}")

    # Test with sample data
    sample_highlights = [
        {
            'text': '成功的關鍵不在於你做了什麼，而在於你持續做了什麼。一致性比強度更重要，因為只有持續的行動才能帶來複利效應。',
            'chapter_name': '第一章：開始',
            'chapter_progress': 0.1,
            'current_chapter_progress': 0.5
        },
        {
            'text': '學習最有效的方式是教導他人。當你必須解釋一個概念時，你會發現自己對它的理解還不夠深入，這促使你更深入地學習。',
            'chapter_name': '第二章：學習',
            'chapter_progress': 0.3,
            'current_chapter_progress': 0.2
        }
    ] * 6  # Duplicate to meet minimum threshold

    generator = ZettelkastenCardGenerator(max_cards=3, min_highlights=5)
    result = generator.generate_cards_with_review(sample_highlights, "測試書籍")

    print(f"\nPassed {len(result.passed)} / rejected {len(result.rejected)}:")
    for card in result.passed:
        print(f"\n--- {card.title} ---")
        print(f"Content: {card.content}")
        print(f"Review ({card.review_model}): {card.review_scores}")
    for card in result.rejected:
        print(f"\n[REJECTED] {card.title} — {card.review_notes[:100]}")
