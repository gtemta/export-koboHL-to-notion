"""
Zettelkasten Card Generator

This module generates Zettelkasten (slip-box) style note cards from book highlights.
It uses a dual-layer LLM architecture:
- Ollama (Gemma) for fast local generation of card drafts
- Gemini API for quality review and refinement
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


@dataclass
class ZettelkastenCard:
    """Represents a single Zettelkasten note card"""
    id: str                           # Unique identifier
    title: str                        # Card title (5-20 characters)
    content: str                      # Card content (100-150 characters)
    source_highlight: str             # Original highlight text
    chapter_reference: str            # Source chapter name
    chapter_progress: float           # Reading progress (0.0 - 1.0)
    quality_score: int = 0            # Quality score from Gemini review (1-10)
    revision_notes: str = ""          # Notes from Gemini review
    source_bookmark_id: str = ""      # Kobo BookmarkID of the source highlight
    tags: List[str] = field(default_factory=list)  # Free concept tags (2-3) → Key Word
    categories: List[str] = field(default_factory=list)  # Fixed Tags classification (1-2)
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
            'quality_score': self.quality_score,
            'revision_notes': self.revision_notes,
            'source_bookmark_id': self.source_bookmark_id,
            'tags': self.tags,
            'categories': self.categories,
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
            quality_score=d.get('quality_score', 0) or 0,
            revision_notes=d.get('revision_notes', '') or '',
            source_bookmark_id=d.get('source_bookmark_id', '') or '',
            tags=list(d.get('tags') or []),
            categories=list(d.get('categories') or []),
            created_at=created_at,
        )


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

    def generate_card(self, highlight: Dict, book_title: str = "") -> Optional[ZettelkastenCard]:
        """
        Generate a Zettelkasten card from a highlight using Ollama.

        Returns a ZettelkastenCard with:
        - Title: 5-15 characters summarizing the core concept
        - Content: 100-150 characters atomic note in own words
        """
        text = highlight.get('text', '').strip()
        chapter = highlight.get('chapter_name', 'Unknown')
        progress = highlight.get('chapter_progress', 0.0)
        annotation = (highlight.get('annotation') or '').strip()

        if not text:
            return None

        prompt = self._build_prompt(text, book_title, annotation)

        accumulated: List[str] = []
        start_time = time.monotonic()
        timeout_s = int(os.getenv('OLLAMA_TIMEOUT_SECONDS', '300'))
        keep_alive = os.getenv('OLLAMA_KEEP_ALIVE', '30m')
        num_predict = int(os.getenv('OLLAMA_NUM_PREDICT', '2000'))

        logger.debug(
            f"Ollama request → url={self.api_url} model={self.model} "
            f"prompt_chars={len(prompt)} timeout={timeout_s}s num_predict={num_predict}"
        )

        try:
            response = requests.post(
                self.api_url,
                json={
                    "model": self.model,
                    "prompt": prompt,
                    "stream": True,
                    "keep_alive": keep_alive,
                    "options": {
                        "temperature": 0.7,
                        "num_predict": num_predict,
                    },
                },
                timeout=timeout_s,
                stream=True,
            )

            if response.status_code == 200:
                for line in response.iter_lines(decode_unicode=True):
                    if not line:
                        continue
                    chunk = json.loads(line)
                    accumulated.append(chunk.get("response", ""))
                    if chunk.get("done"):
                        break

                generated_text = "".join(accumulated)
                elapsed = time.monotonic() - start_time
                logger.debug(
                    f"Ollama response ← status=200 elapsed={elapsed:.1f}s "
                    f"chars={len(generated_text)}"
                )

                title, content = self._parse_response(generated_text, text)

                if title and content:
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
            else:
                elapsed = time.monotonic() - start_time
                logger.error(
                    f"Ollama API error: status={response.status_code} "
                    f"elapsed={elapsed:.1f}s body={response.text[:500]}"
                )

        except requests.exceptions.Timeout:
            elapsed = time.monotonic() - start_time
            partial = "".join(accumulated) if accumulated else "<no bytes received>"
            logger.error(
                f"Ollama API timeout after {elapsed:.1f}s "
                f"(url={self.api_url} model={self.model} prompt_chars={len(prompt)})"
            )
            logger.error(
                f"Partial response before timeout ({len(partial)} chars): {partial!r}"
            )
        except requests.exceptions.ConnectionError as e:
            elapsed = time.monotonic() - start_time
            logger.error(
                f"Cannot connect to Ollama after {elapsed:.1f}s "
                f"(url={self.api_url}): {e}"
            )
        except Exception as e:
            elapsed = time.monotonic() - start_time
            logger.exception(
                f"Error generating card with Ollama after {elapsed:.1f}s: {e}"
            )

        return None

    def _build_prompt(self, highlight_text: str, book_title: str = "",
                      annotation: str = "") -> str:
        """Build the prompt for card generation"""
        book_context = f"書名：{book_title}\n" if book_title else ""
        annotation_context = (
            f"\n讀者的個人註記（請務必納入這個觀點）：\n{annotation}\n"
            if annotation and annotation.strip() else ""
        )

        return f"""你是一位卡片盒筆記專家。請為以下書籍劃線生成一張卡片筆記。

{book_context}劃線內容：
{highlight_text}
{annotation_context}
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
    _TAG_SPLIT = re.compile(r'[、,，/|｜\s]+')

    @classmethod
    def _extract_tags(cls, text: str, limit: int = 3) -> List[str]:
        """Pull 2-3 concept tags from a 【標籤】 line; [] if absent."""
        if not text:
            return []
        match = cls._TAG_LINE.search(text)
        if not match:
            return []
        raw = match.group(1).strip()
        tags: List[str] = []
        for part in cls._TAG_SPLIT.split(raw):
            tag = part.strip().lstrip('#').replace('，', '').replace(',', '')
            if tag and tag not in tags:
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
    def _parse_classification(
        cls, text: str, n: int, allowed: List[str]
    ) -> List[List[str]]:
        """Parse `CARD_i: 分類A、分類B` lines into per-card category lists.

        Category names are matched on their text core (emoji-insensitive) and
        written back as the canonical `allowed` value, so Notion multi_select
        options keep their emoji prefix. At most 2 per card; cards with no
        valid category get []. Pure — no Ollama, unit-testable.
        """
        result: List[List[str]] = [[] for _ in range(n)]
        if not text or not allowed:
            return result
        canonical = {cls._category_core(a): a for a in allowed if cls._category_core(a)}
        cleaned = cls._strip_thinking(text)
        for line in cleaned.splitlines():
            m = cls._CLASSIFY_LINE.search(line)
            if not m:
                continue
            try:
                idx = int(m.group(1))
            except ValueError:
                continue
            if not (1 <= idx <= n):
                continue
            picked: List[str] = []
            for part in cls._CLASSIFY_SPLIT.split(m.group(2).strip()):
                name = canonical.get(cls._category_core(part))
                if name and name not in picked:
                    picked.append(name)
                if len(picked) >= 2:
                    break
            result[idx - 1] = picked
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
        return f"""你是一位知識分類助理。以下是 {len(cards)} 張卡片筆記，請為每張卡片挑選最貼切的分類。

可用分類（只能從這裡挑，不可自創）：
{allowed}

卡片：
{cards_section}

規則：
1. 每張卡片挑 1-2 個最貼切的分類，只能從上面清單挑，用頓號（、）分隔
2. 如果沒有任何分類貼切，該卡片留空（不要硬塞、不要發明新分類）
3. 嚴格依照格式逐行輸出，每張卡片一行：CARD_編號：分類
4. 不要加任何解釋或結語

請直接輸出："""

    def classify_cards(
        self, cards: List[ZettelkastenCard], categories: List[str],
        book_title: str = "",
    ) -> None:
        """Assign fixed-category Tags to each card in place via one Ollama call.

        No-op if there are no cards or no category list. On any Ollama failure
        the cards simply keep empty `categories` (left for manual tagging).
        """
        if not cards or not categories:
            return

        prompt = self._build_classification_prompt(cards, categories)
        timeout_s = int(os.getenv('OLLAMA_BATCH_TIMEOUT_SECONDS', '600'))
        keep_alive = os.getenv('OLLAMA_KEEP_ALIVE', '30m')
        num_ctx = int(os.getenv('OLLAMA_BATCH_NUM_CTX', '16384'))

        accumulated: List[str] = []
        start_time = time.monotonic()
        logger.info(
            f"Ollama classify request → model={self.model} cards={len(cards)} "
            f"prompt_chars={len(prompt)}"
        )
        payload = {
            "model": self.model,
            "prompt": prompt,
            "stream": True,
            "keep_alive": keep_alive,
            # thinking models (e.g. gemma4:e4b) silently burn the whole
            # num_predict budget on hidden reasoning before any visible output
            # (done_reason=length, response "") — disable it for this short
            # structured task.
            "think": False,
            "options": {"temperature": 0.3, "num_predict": 1000, "num_ctx": num_ctx},
        }
        try:
            response = requests.post(
                self.api_url, json=payload, timeout=timeout_s, stream=True,
            )
            if response.status_code == 400 and "think" in payload:
                # older Ollama / non-thinking model may reject the parameter
                logger.info("Ollama 不接受 think 參數，改以預設模式重試")
                payload.pop("think")
                response = requests.post(
                    self.api_url, json=payload, timeout=timeout_s, stream=True,
                )
            if response.status_code != 200:
                logger.error(
                    f"Ollama classify error: status={response.status_code} "
                    f"body={response.text[:300]}"
                )
                return
            for line in response.iter_lines(decode_unicode=True):
                if not line:
                    continue
                chunk = json.loads(line)
                if chunk.get("error"):
                    logger.error(f"Ollama classify in-stream error: {chunk['error']}")
                    break
                accumulated.append(chunk.get("response", ""))
                if chunk.get("done"):
                    if chunk.get("done_reason") == "length" and not "".join(accumulated).strip():
                        logger.warning(
                            "Ollama classify hit num_predict with empty output "
                            "(thinking-model budget exhausted?)"
                        )
                    break
        except Exception as e:  # noqa: BLE001 — classification is best-effort
            elapsed = time.monotonic() - start_time
            logger.error(f"Ollama classify failed after {elapsed:.1f}s: {e}")
            # fall through: parse whatever streamed in before the error, if any

        raw = "".join(accumulated)
        logger.debug(f"Ollama classify raw response ({len(raw)} chars): {raw[:500]}")
        parsed = self._parse_classification(raw, len(cards), categories)
        assigned = 0
        for card, cats in zip(cards, parsed):
            card.categories = cats
            if cats:
                assigned += 1
        logger.info(f"Ollama classify done: {assigned}/{len(cards)} cards tagged")

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
        timeout_s = int(os.getenv('OLLAMA_BATCH_TIMEOUT_SECONDS', '600'))
        keep_alive = os.getenv('OLLAMA_KEEP_ALIVE', '30m')
        num_predict = int(os.getenv('OLLAMA_BATCH_NUM_PREDICT', '-1'))
        num_ctx = int(os.getenv('OLLAMA_BATCH_NUM_CTX', '16384'))

        accumulated: List[str] = []
        start_time = time.monotonic()

        logger.info(
            f"Ollama batch request → model={self.model} highlights={len(highlights)} "
            f"prompt_chars={len(prompt)} num_ctx={num_ctx} timeout={timeout_s}s"
        )

        try:
            response = requests.post(
                self.api_url,
                json={
                    "model": self.model,
                    "prompt": prompt,
                    "stream": True,
                    "keep_alive": keep_alive,
                    "options": {
                        "temperature": 0.7,
                        "num_predict": num_predict,
                        "num_ctx": num_ctx,
                    },
                },
                timeout=timeout_s,
                stream=True,
            )

            if response.status_code != 200:
                elapsed = time.monotonic() - start_time
                logger.error(
                    f"Ollama batch error: status={response.status_code} "
                    f"elapsed={elapsed:.1f}s body={response.text[:500]}"
                )
                return [None] * len(highlights)

            for line in response.iter_lines(decode_unicode=True):
                if not line:
                    continue
                chunk = json.loads(line)
                accumulated.append(chunk.get("response", ""))
                if chunk.get("done"):
                    break

            generated_text = "".join(accumulated)
            elapsed = time.monotonic() - start_time
            logger.info(
                f"Ollama batch response ← elapsed={elapsed:.1f}s "
                f"chars={len(generated_text)}"
            )
            return self._parse_batch_response(generated_text, highlights)

        except requests.exceptions.Timeout:
            elapsed = time.monotonic() - start_time
            partial = "".join(accumulated) if accumulated else "<no bytes received>"
            logger.error(
                f"Ollama batch timeout after {elapsed:.1f}s "
                f"(highlights={len(highlights)} prompt_chars={len(prompt)})"
            )
            logger.error(f"Partial response before timeout ({len(partial)} chars): {partial[:500]!r}")
            # Try to salvage whatever cards made it through before timeout.
            if accumulated:
                return self._parse_batch_response("".join(accumulated), highlights)
            return [None] * len(highlights)
        except requests.exceptions.ConnectionError as e:
            logger.error(f"Cannot connect to Ollama for batch: {e}")
            return [None] * len(highlights)
        except Exception as e:
            logger.exception(f"Error in batch generation: {e}")
            return [None] * len(highlights)

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


class GeminiReviewer:
    """Uses Gemini API to review and refine card quality"""

    def __init__(self, api_key: str = None, model: str = None, review_threshold: int = None):
        self.api_key = api_key or os.getenv('GEMINI_API_KEY')
        self.model = model or os.getenv('GEMINI_MODEL', 'gemini-2.0-flash')
        self.review_threshold = review_threshold or int(os.getenv('GEMINI_REVIEW_THRESHOLD', '6'))
        self.api_url = f"https://generativelanguage.googleapis.com/v1beta/models/{self.model}:generateContent"

    def is_available(self) -> bool:
        """Check if Gemini API is configured"""
        return bool(self.api_key)

    def review_and_refine(self, card: ZettelkastenCard) -> ZettelkastenCard:
        """
        Review a single card and refine if quality is below threshold.

        Returns the card with updated quality_score and potentially refined content.
        """
        if not self.is_available():
            logger.warning("Gemini API not configured, skipping review")
            card.quality_score = 7  # Default score when review is skipped
            return card

        prompt = self._build_review_prompt(card)

        try:
            response = requests.post(
                f"{self.api_url}?key={self.api_key}",
                headers={"Content-Type": "application/json"},
                json={
                    "contents": [{
                        "parts": [{"text": prompt}]
                    }],
                    "generationConfig": {
                        "temperature": 0.3,
                        "maxOutputTokens": 1000
                    }
                },
                timeout=30
            )

            if response.status_code == 200:
                result = response.json()
                generated_text = result.get("candidates", [{}])[0].get("content", {}).get("parts", [{}])[0].get("text", "")

                reviewed_card = self._parse_review_response(generated_text, card)
                return reviewed_card
            else:
                logger.error(f"Gemini API error: {response.status_code} - {response.text}")
                card.quality_score = 7
                return card

        except Exception as e:
            logger.error(f"Error reviewing card with Gemini: {str(e)}")
            card.quality_score = 7
            return card

    def _build_review_prompt(self, card: ZettelkastenCard) -> str:
        """Build the review prompt for Gemini"""
        return f"""你是卡片筆記品質審核員。請審核以下卡片筆記，確保：
1. 標題精準概括核心概念（5-20字）
2. 內容是獨立完整的原子筆記（100-150字）
3. 用語清晰、邏輯通順
4. 忠實於原文意涵

原始劃線：
{card.source_highlight}

初稿標題：{card.title}

初稿內容：
{card.content}

請以 JSON 格式輸出審核結果（只輸出 JSON，不要加其他文字）：
{{
  "title": "優化後的標題（如無需修改則保持原樣）",
  "content": "優化後的內容（如無需修改則保持原樣）",
  "quality_score": 1到10的評分,
  "revision_notes": "修改說明（如無修改則為空字串）"
}}"""

    def _parse_review_response(self, response_text: str, original_card: ZettelkastenCard) -> ZettelkastenCard:
        """Parse the Gemini review response"""
        try:
            # Try to extract JSON from the response
            json_match = re.search(r'\{[^{}]*\}', response_text, re.DOTALL)
            if json_match:
                review_data = json.loads(json_match.group())

                quality_score = review_data.get('quality_score', 7)
                revision_notes = review_data.get('revision_notes', '')

                # Only apply refinements if quality is below threshold
                if quality_score < self.review_threshold:
                    original_card.title = review_data.get('title', original_card.title)
                    original_card.content = review_data.get('content', original_card.content)
                    logger.info(f"Card refined by Gemini (score: {quality_score})")
                else:
                    logger.info(f"Card quality acceptable (score: {quality_score}), keeping original")

                original_card.quality_score = quality_score
                original_card.revision_notes = revision_notes

        except json.JSONDecodeError as e:
            logger.warning(f"Failed to parse Gemini response as JSON: {e}")
            original_card.quality_score = 7
        except Exception as e:
            logger.error(f"Error parsing Gemini review: {e}")
            original_card.quality_score = 7

        return original_card

    def batch_review(self, cards: List[ZettelkastenCard]) -> List[ZettelkastenCard]:
        """
        Review multiple cards.

        For efficiency, this processes cards one at a time but could be
        optimized for batch API calls if needed.
        """
        if not self.is_available():
            logger.warning("Gemini API not configured, skipping batch review")
            for card in cards:
                card.quality_score = 7
            return cards

        reviewed_cards = []
        for i, card in enumerate(cards):
            logger.info(f"Reviewing card {i+1}/{len(cards)}...")
            reviewed_card = self.review_and_refine(card)
            reviewed_cards.append(reviewed_card)

        return reviewed_cards


class ZettelkastenCardGenerator:
    """
    Main class that orchestrates the entire card generation process.

    Flow:
    1. Check if highlights meet minimum threshold
    2. Select best highlights using CardSelectionAlgorithm
    3. Generate draft cards using ZettelkastenLLMEnhancer (Ollama)
    4. Review and refine cards using GeminiReviewer
    """

    def __init__(self,
                 max_cards: int = None,
                 min_highlights: int = None,
                 enable_gemini_review: bool = True,
                 tag_categories: Optional[List[str]] = None):

        self.max_cards = max_cards or int(os.getenv('ZETTELKASTEN_MAX_CARDS', '16'))
        self.min_highlights = min_highlights or int(os.getenv('ZETTELKASTEN_MIN_HIGHLIGHTS', '10'))
        self.enable_gemini_review = enable_gemini_review
        # Fixed Tags classification list (DI from settings); empty → classification off.
        self.tag_categories = list(tag_categories or [])

        self.selector = CardSelectionAlgorithm(
            max_cards=self.max_cards,
            min_highlights=self.min_highlights
        )
        self.enhancer = ZettelkastenLLMEnhancer()
        self.reviewer = GeminiReviewer()

    def generate_cards(self, highlights: List[Dict], book_title: str = "") -> List[ZettelkastenCard]:
        """
        Generate Zettelkasten cards from book highlights.

        Args:
            highlights: List of highlight dictionaries from DBReader
            book_title: Title of the book (for context)

        Returns:
            List of ZettelkastenCard objects
        """
        logger.info(f"Starting Zettelkasten card generation for '{book_title}'")
        logger.info(f"Total highlights: {len(highlights)}, Max cards: {self.max_cards}, Min threshold: {self.min_highlights}")

        # Step 1: Check threshold
        if not self.selector.should_generate_cards(highlights):
            logger.info(f"Skipping card generation: only {len(highlights)} highlights (minimum: {self.min_highlights})")
            return []

        # Step 2: Select best highlights
        selected_highlights = self.selector.select_highlights(highlights)
        if not selected_highlights:
            logger.info("No highlights selected after filtering")
            return []

        logger.info(f"Selected {len(selected_highlights)} highlights for card generation")

        # Step 3: Generate draft cards with Ollama
        logger.info("Generating draft cards with Ollama (Gemma)...")
        draft_cards = self.enhancer.batch_generate(selected_highlights, book_title)

        if not draft_cards:
            logger.warning("No cards generated from Ollama")
            return []

        logger.info(f"Generated {len(draft_cards)} draft cards")

        # Step 4: Review and refine with Gemini (optional)
        if self.enable_gemini_review and self.reviewer.is_available():
            logger.info("Reviewing cards with Gemini API...")
            final_cards = self.reviewer.batch_review(draft_cards)
        else:
            logger.info("Skipping Gemini review (disabled or not configured)")
            final_cards = draft_cards
            for card in final_cards:
                card.quality_score = 7  # Default score

        logger.info(f"Card generation complete: {len(final_cards)} cards")

        # Step 5: Classify into fixed Tags categories (one Ollama call per book)
        if final_cards and self.tag_categories:
            logger.info("Classifying cards into fixed Tags categories...")
            self.enhancer.classify_cards(final_cards, self.tag_categories, book_title)

        # Log quality statistics
        if final_cards:
            avg_score = sum(c.quality_score for c in final_cards) / len(final_cards)
            logger.info(f"Average quality score: {avg_score:.1f}/10")

        return final_cards


def check_ollama_availability() -> bool:
    """Check if Ollama service is running and accessible"""
    api_url = os.getenv('OLLAMA_API_URL', 'http://localhost:11434/api/tags')
    try:
        response = requests.get(api_url.replace('/api/generate', '/api/tags'), timeout=5)
        return response.status_code == 200
    except requests.RequestException:
        return False


def check_gemini_availability() -> bool:
    """Check if Gemini API key is configured"""
    return bool(os.getenv('GEMINI_API_KEY'))


# For testing
if __name__ == "__main__":
    # Setup basic logging for testing
    logging.basicConfig(level=logging.INFO)

    print("Checking service availability...")
    print(f"Ollama available: {check_ollama_availability()}")
    print(f"Gemini configured: {check_gemini_availability()}")

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
    cards = generator.generate_cards(sample_highlights, "測試書籍")

    print(f"\nGenerated {len(cards)} cards:")
    for card in cards:
        print(f"\n--- {card.title} ---")
        print(f"Content: {card.content}")
        print(f"Quality: {card.quality_score}/10")
