# 🚀 Kobo-Notion 重構計劃

## 📋 重構目標

1. **結構化**：採用清潔架構（Clean Architecture）分層設計
2. **輕量化**：移除冗餘依賴，保持最小化依賴集
3. **Python Only**：完全移除 Node.js 實現
4. **可測試性**：清晰的抽象層，便於單元測試
5. **可擴展性**：支援未來功能擴展

## 🏛️ 新架構設計

### 分層架構
```
┌─────────────────────┐
│   Presentation      │  CLI / Main Entry
├─────────────────────┤
│   Application       │  Use Cases / Orchestration  
├─────────────────────┤
│   Domain            │  Business Logic / Entities
├─────────────────────┤
│   Infrastructure    │  External Services / DB
└─────────────────────┘
```

### 目錄結構
```
kobo-notion-sync/
├── src/
│   ├── domain/
│   │   ├── entities/
│   │   │   ├── book.py          # 書籍實體
│   │   │   ├── highlight.py     # 高亮實體  
│   │   │   └── chapter.py       # 章節實體
│   │   ├── services/
│   │   │   ├── chapter_extractor.py     # 智能章節提取
│   │   │   └── highlight_formatter.py   # 高亮格式化
│   │   └── repositories/
│   │       ├── book_repository.py       # 書籍資料庫接口
│   │       └── notion_repository.py     # Notion 接口
│   ├── application/
│   │   ├── use_cases/
│   │   │   └── sync_books_use_case.py   # 同步用例
│   │   └── dtos/
│   │       └── sync_result.py           # 資料傳輸物件
│   ├── infrastructure/
│   │   ├── database/
│   │   │   └── kobo_repository_impl.py  # Kobo DB 實現
│   │   ├── notion/
│   │   │   ├── notion_client.py         # Notion 客戶端
│   │   │   └── notion_repository_impl.py # Notion 實現
│   │   └── external/
│   │       └── cover_service.py         # 封面服務
│   ├── config/
│   │   └── settings.py                  # 統一配置
│   └── main.py                          # 應用入口
├── tests/
│   ├── unit/
│   │   ├── test_chapter_extraction.py   # 單元測試
│   │   └── test_highlight_formatting.py
│   └── integration/
│       └── test_sync_flow.py            # 整合測試
├── requirements.txt                     # 最小化依賴
├── .env.example                         # 環境變數範例
└── README.md
```

## 🧹 清理計劃

### 移除檔案
```bash
# Node.js 相關
- index.js
- package.json  
- package-lock.json
- node_modules/

# 冗餘的測試/演示腳本（15個 → 3個）
- analyze_*.py
- debug_*.py  
- demo_*.py
- extract_*.py
- find_*.py
- summarize_*.py
- test_*.py (除核心測試外)

# 臨時檔案
- summaries/
- logs/ (簡化日志)
- *.sqlite (開發時產生)
```

### 精簡依賴
```python
# 當前：多個複雜依賴
# 重構後：最小化集合
notion-client==2.0.0      # Notion API
requests==2.31.0          # HTTP 請求 (封面)
python-dotenv==1.0.0      # 環境變數
```

## 🔧 核心改進

### 1. 智能章節提取器 (Strategy Pattern)
```python
class ChapterExtractor:
    def __init__(self):
        self.strategies = [
            TextContentExtractor(),    # 從文本內容提取
            ContentIdExtractor(),      # 從路徑提取  
            ContainerPathExtractor(),  # 從容器路徑提取
        ]
    
    def extract(self, highlight_data) -> str:
        for strategy in self.strategies:
            if chapter := strategy.extract(highlight_data):
                return chapter
        return "未知章節"
```

### 2. 統一配置管理
```python
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

### 3. Repository Pattern 
```python
class BookRepository(ABC):
    @abstractmethod  
    def get_all_books(self) -> List[Book]:
        pass
    
    @abstractmethod
    def get_highlights_with_chapters(self, book_id: str) -> List[Highlight]:
        pass

class KoboRepositoryImpl(BookRepository):
    def __init__(self, db_path: str):
        self.db_path = db_path
    # 具體實現...
```

### 4. 用例驅動設計
```python
class SyncBooksUseCase:
    def __init__(self, 
                 book_repo: BookRepository,
                 notion_repo: NotionRepository,
                 chapter_extractor: ChapterExtractor):
        self.book_repo = book_repo
        self.notion_repo = notion_repo  
        self.chapter_extractor = chapter_extractor
    
    def execute(self) -> SyncResult:
        # 核心同步邏輯
        pass
```

## 📊 重構效益

| 指標 | 重構前 | 重構後 | 改善 |
|------|--------|--------|------|
| 檔案數量 | ~30個 | ~15個 | -50% |
| 代碼行數 | ~2000行 | ~1000行 | -50% |
| 依賴數量 | 多個複雜依賴 | 3個核心依賴 | -70% |
| 測試覆蓋 | 難以測試 | 高可測試性 | +200% |
| 可讀性 | 職責混亂 | 清晰分層 | +100% |

## 🚀 實施步驟

1. **Phase 1**: 建立新目錄結構和核心抽象
2. **Phase 2**: 重構章節提取邏輯和實體類
3. **Phase 3**: 實現 Repository 和 Infrastructure 層
4. **Phase 4**: 建立 Use Case 和應用層
5. **Phase 5**: 整合測試和清理舊代碼

## ✅ 驗收標準

- [ ] 所有功能正常運作
- [ ] 代碼覆蓋率 > 80%
- [ ] 啟動時間 < 3秒
- [ ] 記憶體使用 < 100MB  
- [ ] 依賴數量 ≤ 3個
- [ ] 檔案數量 ≤ 15個