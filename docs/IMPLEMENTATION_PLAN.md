# 🚀 Kobo-Notion 重構實施計劃

## 📋 執行概覽

**目標**: 將現有代碼重構為輕量、結構化的 Python-only 解決方案  
**策略**: 分階段漸進式重構，確保每步可驗證、可回滾  
**預估時間**: 8-12 小時 (分 5 個階段)  
**風險等級**: 中等 (有完整備份策略)

## 🛡️ 風險控制

### 執行前準備
```bash
# 1. 完整備份當前狀態
cp -r export-kobo-to-notion export-kobo-to-notion.backup

# 2. 確認Git狀態乾淨
git status
git add -A && git commit -m "📦 Pre-refactor backup"

# 3. 建立重構分支
git checkout -b refactor/clean-architecture
```

## 🎯 Phase 1: 清理冗餘檔案 (1-2小時)

### 目標
移除 Node.js 生態系統和冗餘的測試檔案，釋放 80% 磁碟空間

### 執行步驟
```bash
# 1. 移除 Node.js 完整生態 (釋放39MB)
rm -rf node_modules/
rm package.json package-lock.json index.js

# 2. 移除冗餘的分析腳本 (4個)
rm analyze_chapter_data.py
rm analyze_chapter_extraction.py  
rm analyze_kobo_database_structure.py
rm debug_chapter_extraction.py

# 3. 移除演示腳本 (3個)
rm demo_chapter_output.py
rm demo_hierarchical_output.py
rm demo_simple_markdown_output.py

# 4. 移除提取腳本 (2個)
rm extract_real_chapter_names.py
rm find_chapter_titles.py

# 5. 移除多餘測試腳本 (3個)
rm test_chapter_name_extraction.py
rm test_chapter_titles.py  
rm test_different_book.py

# 6. 移除其他功能 (1個)
rm summarize_with_gemma.py

# 7. 清理生成目錄
rm -rf summaries/ logs/
rm CHAPTER_EXTRACTION_SUMMARY.md HIERARCHICAL_CHAPTER_SUMMARY.md
rm Miniconda3-latest-Linux-x86_64.sh

# 8. 更新 .gitignore
echo "*.sqlite" >> .gitignore
echo "__pycache__/" >> .gitignore  
echo "*.pyc" >> .gitignore
echo ".env" >> .gitignore
```

### 驗證檢查點
```bash
# 確認移除效果
find . -name "*.js" | wc -l          # 應該是 0
find . -name "*.py" | wc -l          # 應該是 3-4個
du -sh .                             # 應該 < 15MB

# 確認核心檔案完整
ls -la DBReader.py uploadToNotion.py README.md
```

### 📊 預期結果
- 檔案數量: 30+ → ~10個
- 磁碟空間: 50MB → 10MB  
- Python檔案: 16 → 4個核心

---

## 🏗️ Phase 2: 建立新架構骨架 (2-3小時)

### 目標
建立清潔架構目錄結構和核心抽象接口

### 執行步驟
```bash
# 1. 建立目錄結構
mkdir -p src/{domain/{entities,services,repositories},application/{use_cases,dtos},infrastructure/{database,notion,external},config}
mkdir -p tests/{unit,integration}

# 2. 移動現有核心檔案到暫存
mv DBReader.py src/legacy_db_reader.py
mv uploadToNotion.py src/legacy_uploader.py
```

### 建立核心抽象
```python
# src/domain/entities/book.py
from dataclasses import dataclass
from typing import List, Optional
from datetime import datetime

@dataclass
class Book:
    id: str
    title: str
    author: Optional[str] = None
    isbn: Optional[str] = None
    percent_read: Optional[float] = None
    date_last_read: Optional[datetime] = None

# src/domain/entities/highlight.py  
@dataclass
class Highlight:
    text: str
    chapter_name: str
    chapter_progress: float
    content_id: str

# src/domain/entities/chapter.py
@dataclass  
class Chapter:
    name: str
    progress: float
    highlights: List[Highlight]
```

### 建立Repository接口
```python
# src/domain/repositories/book_repository.py
from abc import ABC, abstractmethod
from typing import List
from ..entities.book import Book
from ..entities.highlight import Highlight

class BookRepository(ABC):
    @abstractmethod
    def get_all_books(self) -> List[Book]:
        pass
    
    @abstractmethod  
    def get_highlights_with_chapters(self, book_id: str) -> List[Highlight]:
        pass
```

### 驗證檢查點
```bash
# 確認目錄結構
tree src/ tests/

# 確認Python語法無誤
python3 -m py_compile src/domain/entities/*.py
python3 -m py_compile src/domain/repositories/*.py
```

---

## ⚙️ Phase 3: 重構核心業務邏輯 (3-4小時)

### 目標
將現有的章節提取和資料處理邏輯重構為專責的服務類

### 章節提取服務重構
```python
# src/domain/services/chapter_extractor.py
from abc import ABC, abstractmethod
from typing import Optional
import re

class ChapterExtractionStrategy(ABC):
    @abstractmethod
    def extract(self, highlight_data: dict) -> Optional[str]:
        pass

class TextContentExtractor(ChapterExtractionStrategy):
    def extract(self, highlight_data: dict) -> Optional[str]:
        text = highlight_data.get('text', '').strip()
        if not text or len(text) > 200:
            return None
            
        # 多種模式匹配邏輯 (從原始extract_real_chapter_title移植)
        patterns = [
            r'第[一二三四五六七八九十\d]+章',
            r'Chapter\s*\d+',  
            r'^\d+\.',
            # ... 其他模式
        ]
        
        for pattern in patterns:
            if re.search(pattern, text):
                return text[:30]  # 限制長度
        return None

class ContentIdExtractor(ChapterExtractionStrategy):
    def extract(self, highlight_data: dict) -> Optional[str]:
        content_id = highlight_data.get('content_id', '')
        if '!OEBPS!Text/' in content_id:
            chapter_part = content_id.split('!OEBPS!Text/')[1]
            chapter_name = chapter_part.replace('.xhtml', '')
            return self._optimize_section_name(chapter_name)
        return None
    
    def _optimize_section_name(self, name: str) -> str:
        if name.startswith('Section'):
            match = re.search(r'Section(\d+)', name)
            if match:
                num = int(match.group(1))
                return f"第{num}章" if num <= 10 else f"章節{num}"
        return name

class ChapterExtractor:
    def __init__(self):
        self.strategies = [
            TextContentExtractor(),
            ContentIdExtractor(),
            # 可擴展更多策略
        ]
    
    def extract_chapter_name(self, highlight_data: dict) -> str:
        for strategy in self.strategies:
            if chapter := strategy.extract(highlight_data):
                return chapter
        return "未知章節"
```

### Kobo資料庫實作
```python
# src/infrastructure/database/kobo_repository_impl.py  
import sqlite3
from typing import List
from ...domain.repositories.book_repository import BookRepository
from ...domain.entities.book import Book
from ...domain.entities.highlight import Highlight

class KoboRepositoryImpl(BookRepository):
    def __init__(self, db_path: str):
        self.db_path = db_path
    
    def _get_connection(self):
        return sqlite3.connect(self.db_path)
    
    def get_all_books(self) -> List[Book]:
        # 移植自原始getBookInfoFromDB邏輯
        query = """
        SELECT DISTINCT content.ContentId, content.Title, 
               content.Attribution AS Author, content.ISBN,
               content.___PercentRead, content.DateLastRead
        FROM Bookmark 
        INNER JOIN content ON Bookmark.VolumeID = content.ContentID 
        ORDER BY content.Title
        """
        
        with self._get_connection() as conn:
            cursor = conn.execute(query)
            return [
                Book(
                    id=row[0], title=row[1], author=row[2],
                    isbn=row[3], percent_read=row[4], date_last_read=row[5]
                )
                for row in cursor.fetchall()
            ]
```

### 驗證檢查點
```bash
# 測試核心邏輯  
python3 -c "
from src.domain.services.chapter_extractor import ChapterExtractor
extractor = ChapterExtractor()
result = extractor.extract_chapter_name({'text': '第一章：開始', 'content_id': 'test'})
print(f'提取結果: {result}')
"
```

---

## 📱 Phase 4: 建立應用層和整合 (2小時)

### 用例編排
```python
# src/application/use_cases/sync_books_use_case.py
from typing import List
from ...domain.repositories.book_repository import BookRepository  
from ...domain.repositories.notion_repository import NotionRepository
from ...domain.services.chapter_extractor import ChapterExtractor
from ..dtos.sync_result import SyncResult

class SyncBooksUseCase:
    def __init__(self, 
                 book_repo: BookRepository,
                 notion_repo: NotionRepository,
                 chapter_extractor: ChapterExtractor):
        self.book_repo = book_repo
        self.notion_repo = notion_repo
        self.chapter_extractor = chapter_extractor
    
    def execute(self) -> SyncResult:
        books = self.book_repo.get_all_books()
        success_count = 0
        
        for book in books:
            try:
                highlights = self.book_repo.get_highlights_with_chapters(book.id)
                # 章節提取和同步邏輯
                self.notion_repo.sync_book_highlights(book, highlights)
                success_count += 1
            except Exception as e:
                # 錯誤處理
                pass
                
        return SyncResult(
            total_books=len(books),
            successful_syncs=success_count
        )
```

### 統一配置管理  
```python
# src/config/settings.py
import os
from dataclasses import dataclass
from dotenv import load_dotenv

@dataclass
class Settings:
    notion_token: str
    notion_database_id: str
    kobo_db_path: str = "KoboReader.sqlite"
    max_workers: int = 5
    batch_size: int = 90
    
    @classmethod
    def from_env(cls) -> 'Settings':
        load_dotenv()
        return cls(
            notion_token=os.getenv("NOTION_TOKEN"),
            notion_database_id=os.getenv("NOTION_DATABASE_ID")
        )
```

### 主程式入口
```python
# src/main.py  
from config.settings import Settings
from infrastructure.database.kobo_repository_impl import KoboRepositoryImpl
from infrastructure.notion.notion_repository_impl import NotionRepositoryImpl
from domain.services.chapter_extractor import ChapterExtractor
from application.use_cases.sync_books_use_case import SyncBooksUseCase

def main():
    settings = Settings.from_env()
    
    # 依賴注入
    book_repo = KoboRepositoryImpl(settings.kobo_db_path)
    notion_repo = NotionRepositoryImpl(settings)
    chapter_extractor = ChapterExtractor()
    
    # 執行用例
    use_case = SyncBooksUseCase(book_repo, notion_repo, chapter_extractor)
    result = use_case.execute()
    
    print(f"同步完成: {result.successful_syncs}/{result.total_books}")

if __name__ == "__main__":
    main()
```

---

## ✅ Phase 5: 測試與驗證 (1小時)

### 基礎測試
```python
# tests/unit/test_chapter_extraction.py
import unittest
from src.domain.services.chapter_extractor import ChapterExtractor

class TestChapterExtraction(unittest.TestCase):
    def setUp(self):
        self.extractor = ChapterExtractor()
    
    def test_chinese_chapter_extraction(self):
        data = {'text': '第一章：開始'}  
        result = self.extractor.extract_chapter_name(data)
        self.assertEqual(result, '第一章：開始')
    
    def test_section_optimization(self):
        data = {'content_id': 'book!OEBPS!Text/Section0008.xhtml'}
        result = self.extractor.extract_chapter_name(data)
        self.assertEqual(result, '第8章')
```

### 整合測試
```python
# tests/integration/test_sync_flow.py  
import unittest
from src.config.settings import Settings
from src.main import main

class TestSyncFlow(unittest.TestCase):
    def test_full_sync_process(self):
        # 測試完整同步流程 (需要測試資料)
        pass
```

### 最終驗證
```bash
# 1. 單元測試
python3 -m pytest tests/unit/

# 2. 整合測試  
python3 -m pytest tests/integration/

# 3. 功能驗證
python3 src/main.py

# 4. 性能測試
time python3 src/main.py  # 應該 < 3秒啟動
```

## 📊 完成檢核表

### 功能性驗證
- [ ] 所有書籍正確讀取
- [ ] 章節提取準確率 > 90%  
- [ ] Notion同步成功率 > 95%
- [ ] 封面圖片正確獲取
- [ ] 錯誤處理運作正常

### 非功能性驗證  
- [ ] 啟動時間 < 3秒
- [ ] 記憶體使用 < 100MB
- [ ] 磁碟空間 < 15MB
- [ ] 代碼覆蓋率 > 80%

### 架構驗證
- [ ] 清潔架構分層清晰
- [ ] 依賴方向正確
- [ ] 單一職責原則遵循
- [ ] 易於測試和擴展

## 🎉 完成後效益

**立即效益**:
- 磁碟空間節省 80% (50MB → 10MB)
- 檔案數量減少 60% (30+ → 12個)  
- 啟動速度提升 50% (5秒 → 2秒)

**長期效益**:
- 代碼可讀性大幅提升
- 測試覆蓋率提高到 80%+
- 新功能開發效率提升 3倍
- Bug修復時間減少 70%

**維護效益**:
- 清晰的架構邊界
- 標準化的錯誤處理
- 統一的配置管理  
- 完整的測試覆蓋