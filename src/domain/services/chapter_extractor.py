import re
from abc import ABC, abstractmethod
from typing import Any, Dict, Optional


class ChapterExtractionStrategy(ABC):
    """章節提取策略抽象類"""
    
    @abstractmethod
    def extract(self, highlight_data: Dict[str, Any]) -> Optional[str]:
        pass


class TextContentExtractor(ChapterExtractionStrategy):
    """從文本內容提取章節標題"""
    
    def extract(self, highlight_data: Dict[str, Any]) -> Optional[str]:
        text = highlight_data.get('text', '').strip()
        if not text or len(text) > 200:
            return None
        
        # 檢查是否像章節標題
        patterns = [
            (r'：', lambda t: '：' in t and len(t) < 50),  # 包含冒號的短文本
            (r'^\d+\.', lambda t: re.match(r'^\d+\.', t)),  # 數字開頭
            (r'^[一二三四五六七八九十]+\.', lambda t: re.match(r'^[一二三四五六七八九十]+\.', t)),  # 中文數字開頭
            (r'第[一二三四五六七八九十\d]+章', lambda t: re.search(r'第[一二三四五六七八九十\d]+章', t)),  # 第X章
            (r'Chapter\s*\d+', lambda t: re.search(r'Chapter\s*\d+', t, re.IGNORECASE)),  # Chapter X
            (r'特定關鍵詞', lambda t: any(keyword in t for keyword in ['序', '前言', '導讀', '引言', '結語', '後記'])),
            (r'短文本冒號', lambda t: len(t) < 30 and ('：' in t or ':' in t))
        ]
        
        for pattern_name, checker in patterns:
            if checker(text):
                return text[:30]  # 限制長度
        
        return None


class ContentIdExtractor(ChapterExtractionStrategy):
    """從ContentID提取章節名稱"""
    
    def extract(self, highlight_data: Dict[str, Any]) -> Optional[str]:
        content_id = highlight_data.get('content_id', '')
        
        # 從ContentID中提取
        if '!OEBPS!Text/' in content_id:
            chapter_part = content_id.split('!OEBPS!Text/')[1]
            chapter_name = chapter_part.replace('.xhtml', '')
            return self._optimize_section_name(chapter_name)
        
        # 從item!xhtml格式提取
        elif '!item!xhtml/' in content_id:
            chapter_part = content_id.split('!item!xhtml/')[1]
            return chapter_part.replace('.xhtml', '')
        
        # 直接處理文件名格式
        elif '.xhtml' in content_id:
            parts = content_id.split('/')
            if len(parts) > 1:
                filename = parts[-1]
                return filename.replace('.xhtml', '')
        
        return None
    
    def _optimize_section_name(self, name: str) -> str:
        """優化Section格式名稱"""
        if name.startswith('Section'):
            match = re.search(r'Section(\d+)', name)
            if match:
                section_num = int(match.group(1))
                if section_num <= 10:
                    return f"第{section_num}章"
                else:
                    return f"章節{section_num}"
        return name


class ContainerPathExtractor(ChapterExtractionStrategy):
    """從StartContainerPath提取章節名稱"""
    
    def extract(self, highlight_data: Dict[str, Any]) -> Optional[str]:
        container_path = highlight_data.get('start_container_path', '')
        if 'OEBPS/Text/' in container_path:
            text_part = container_path.split('OEBPS/Text/')[1]
            if '.xhtml' in text_part:
                return text_part.split('.xhtml')[0]
        return None


class ChapterExtractor:
    """智能章節提取器"""
    
    def __init__(self):
        self.strategies = [
            TextContentExtractor(),
            ContentIdExtractor(),
            ContainerPathExtractor(),
        ]
    
    def extract_chapter_name(self, highlight_data: Dict[str, Any]) -> str:
        """提取章節名稱，按策略優先級嘗試"""
        for strategy in self.strategies:
            if chapter := strategy.extract(highlight_data):
                return chapter
        return "未知章節"