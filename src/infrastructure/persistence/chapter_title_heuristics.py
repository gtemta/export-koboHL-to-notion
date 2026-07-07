"""Chapter-title heuristics: identify real chapter titles embedded in highlight text.

Ported from the legacy DBReader.extract_real_chapter_title. The patterns and
confidence-score thresholds come from empirical tuning against the user's library.
"""
import re
from typing import Optional

_CHAPTER_KEYWORDS = ('序', '前言', '導讀', '引言', '結語', '後記', '附錄', '目錄')
_COUNTRY_KEYWORDS = ('美國', '中國', '日本', '台灣', '韓國', '強項', '優勢', '特色')
_ACTION_KEYWORDS_RE = re.compile(r'^[對抗|防護|掌握|學會|了解|認識|建立].+[：:]')


def extract_real_chapter_title(text: str) -> Optional[str]:
    """Return a chapter title if `text` looks like one, else None."""
    if not text:
        return None
    cleaned = text.strip()
    if not cleaned or len(cleaned) > 150:
        return None

    punct_ratio = sum(1 for c in cleaned if c in '。！？；，、') / len(cleaned)
    if punct_ratio > 0.4:
        return None

    confidence = 0
    is_title = False

    # Pattern 1: colon-containing
    if '：' in cleaned or ':' in cleaned:
        is_title = True
        confidence += 3
        if any(kw in cleaned for kw in _COUNTRY_KEYWORDS):
            confidence += 2
    elif re.match(r'^\d+\.', cleaned):
        is_title = True
        confidence += 2
    elif re.match(r'^[一二三四五六七八九十]+\.', cleaned):
        is_title = True
        confidence += 2
    elif re.search(r'第[一二三四五六七八九十\d]+章', cleaned):
        is_title = True
        confidence += 4
    elif re.search(r'Chapter\s*\d+', cleaned, re.IGNORECASE):
        is_title = True
        confidence += 4
    elif any(kw in cleaned for kw in _CHAPTER_KEYWORDS):
        is_title = True
        confidence += 3
    elif re.search(r'入口\s*[０-９\d]+\s*[：:]', cleaned):
        is_title = True
        confidence += 4
    elif _ACTION_KEYWORDS_RE.search(cleaned):
        is_title = True
        confidence += 2
    elif len(cleaned) < 40 and ('：' in cleaned or ':' in cleaned):
        is_title = True
        confidence += 1
    elif (len(cleaned) < 30
          and not cleaned.endswith(('。', '！', '？', '.', '，', '；'))
          and sum(1 for c in cleaned if c.isalnum()) / len(cleaned) > 0.7):
        is_title = True
        confidence += 1

    # Concept-in-quotes patterns
    quoted_with_paren = re.match(r'^(「.+?」\s*[（(].+?[）)])', cleaned)
    if quoted_with_paren and len(quoted_with_paren.group(1)) < 80:
        return quoted_with_paren.group(1)
    if re.match(r'^「.+」', cleaned) and len(cleaned) < 60:
        return cleaned
    if re.match(r'^[「"].{2,20}[」"]', cleaned) and len(cleaned) < 50:
        is_title = True
        confidence += 2

    if is_title and len(cleaned) > 80 and confidence < 3:
        return None
    if (is_title and cleaned.endswith(('。', '！', '？'))
            and len(cleaned) > 50 and confidence < 3):
        return None
    if is_title and confidence >= 2:
        return cleaned
    return None


def title_confidence(title: str) -> int:
    """Score how likely `title` is to be a real chapter title."""
    if not title:
        return 0
    score = 0
    if 5 <= len(title) <= 50:
        score += 2
    elif 3 <= len(title) <= 80:
        score += 1
    if '：' in title or ':' in title:
        score += 3
    if any(kw in title for kw in ('第', '章', 'Chapter', '序', '前言', '引言', '結語', '入口', '步驟')):
        score += 2
    if any(kw in title for kw in ('對抗', '掌握', '學會', '了解', '認識', '建立', '防護')):
        score += 1
    if not title.endswith(('。', '！', '？')):
        score += 1
    return score


def chapter_name_from_content_id(content_id: str) -> Optional[str]:
    """Derive chapter name from ContentID file path."""
    if not content_id:
        return None
    if '!OEBPS!Text/' in content_id:
        name = content_id.split('!OEBPS!Text/')[1].replace('.xhtml', '')
        return _optimize_section_name(name)
    if '!item!xhtml/' in content_id:
        return content_id.split('!item!xhtml/')[1].replace('.xhtml', '')
    if '.xhtml' in content_id:
        parts = content_id.split('/')
        if len(parts) > 1:
            return parts[-1].replace('.xhtml', '')
    return None


def chapter_name_from_container_path(container_path: str) -> Optional[str]:
    if not container_path or 'OEBPS/Text/' not in container_path:
        return None
    tail = container_path.split('OEBPS/Text/')[1]
    if '.xhtml' in tail:
        return tail.split('.xhtml')[0]
    return None


def _optimize_section_name(name: str) -> str:
    if not name.startswith('Section'):
        return name
    match = re.search(r'Section(\d+)', name)
    if not match:
        return name
    num = int(match.group(1))
    return f"第{num}章" if num <= 10 else f"章節{num}"
