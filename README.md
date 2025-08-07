# Kobo to Notion Export Tool

A Python-based tool that exports Kobo e-reader highlights and notes to a Notion database, with intelligent chapter extraction and organization features.

## 功能特點
- ✅ **智能章節標題提取**：從文本內容中自動提取真正的章節標題，而不只是文件名
- ✅ **多種章節標題模式**：支持冒號模式、數字模式、第X章模式、Chapter模式等
- ✅ **章節名稱優化**：自動將Section格式轉換為友好的章節名稱（如：第8章、章節13）
- ✅ **簡潔的markdown語法**：使用單層級標題和列表格式
- ✅ **美觀排版**：使用章節標題和分隔符美化顯示效果

## 使用方法

### 環境要求

- Python 3.7+
- Node.js（用於原始功能）
- Git（用於版本控制）

您需要配置一個可以訪問您要使用的資料庫（您的「圖書館」資料庫）的 Notion「整合」。Notion 提供了如何設置整合的說明[在此](https://developers.notion.com/docs#step-1-create-an-integration)，您可以透過與整合共享資料庫來讓它訪問您的圖書館資料庫。

### 安裝步驟

1. 在您的終端機中，執行以下指令複製此儲存庫：

   ```bash
   git clone https://github.com/juliariec/export-kobo-to-notion.git
   ```

2. 進入資料夾並執行 `pip install -r requirements.txt` 安裝必要的 Python 套件。

3. 建立一個名為 `.env` 的檔案。在檔案中，您需要設定兩個變數：

   - `NOTION_TOKEN`：與您的 Notion 整合相關聯的內部整合令牌。您可以在[這裡](https://www.notion.so/my-integrations)找到它，它看起來像 `secret_TY78iopwv`（但更長）。
   - `NOTION_DATABASE_ID`：圖書館資料庫的 ID。您可以在資料庫頁面的 URL 中找到它：URL 將在您的工作區名稱和 ? 符號之間有一個 32 位數的 ID，它看起來像 `https://www.notion.so/username/776yv4nanf6qx0bdttznd9upfljupb11?v=s9...`，其中 ID 是 `776yv4nanf6qx0bdttznd9upfljupb11`

   所以您的 `.env` 檔案將如下所示：

   ```
   NOTION_TOKEN=secret_TY78iopwv
   NOTION_DATABASE_ID=776yv4nanf6qx0bdttznd9upfljupb11
   ```

4. 將您的 Kobo 連接到電腦並在檔案總管中開啟它。導航到 `.kobo` 目錄並複製名為 `KoboReader.sqlite` 的檔案，然後將其貼到 `export-kobo-to-notion` 資料夾中。

5. 前往您的 Notion 圖書館資料庫，確保資料庫包含一個帶有書名的「Title」屬性，以及一個預設為未勾選的「Highlights」核取方塊屬性。（腳本將根據標題匹配書籍，然後查看是否已經上傳了摘錄：如果沒有，它將上傳它們，然後將「Highlights」方塊設為已勾選）。

6. 執行腳本：
   - 使用 Python 版本（推薦）：`python uploadToNotion.py`
   - 使用 Node.js 版本：`npm start`
   
   然後檢查您的 Notion 資料庫以確認它是否有效。

### 章節信息說明

從Kobo數據庫中提取的章節信息包括：

1. **智能章節標題提取**：
   - 優先從文本內容中提取真正的章節標題
   - 支持多種章節標題模式（冒號、數字、第X章等）
   - 自動識別章節標題的結構特徵

2. **章節名稱優化**：
   - Section格式：`Section0008` → `第8章`（數字≤10）
   - Section格式：`Section0013` → `章節13`（數字>10）
   - 其他格式：`Prologue`、`01`、`02` 等保持原樣

3. **階層排序**：按章節最高進度進行階層式排列

### 輸出格式

在Notion中，畫線內容將按以下格式顯示：

```
# Highlights

# 📖 中國的強項：企圖心強，整合動作快
* 中國的強項：企圖心強，整合動作快

---

# 📖 企業都應該擬定一套「數據策略」，而且必須分成幾大層次來檢視：第一，務必確保數據的完整性。
* 企業都應該擬定一套「數據策略」，而且必須分成幾大層次來檢視：第一，務必確保數據的完整性。

---

# 📖 第8章
* 是確認那些不需要改變、有價值的核心事物，並且將自己的焦點放在它們上面。

---
```

### 智能章節標題提取特點

- **真正的章節標題**：從文本內容中提取真正的章節標題，而不是文件名
- **多種識別模式**：支持冒號、數字、第X章、Chapter等多種章節標題格式
- **智能優化**：自動優化章節名稱顯示
- **單層級標題**：章節標題使用單一 # 標記
- **列表格式**：畫線內容使用 * 表示列表項目
- **按進度排序**：章節按照最高進度從低到高排列
- **視覺層次**：使用分隔符區分不同章節

## 安裝和使用

### 環境要求

- Python 3.7+
- 需要安裝的Python包（見requirements.txt）

### 安裝步驟

1. 克隆或下載項目文件
2. 安裝依賴：
   ```bash
   pip install -r requirements.txt
   ```

3. 配置環境變量：
   - 創建`.env`文件
   - 添加Notion API配置：
     ```
     NOTION_TOKEN=your_notion_token
     NOTION_DATABASE_ID=your_database_id
     ```

### 使用方法

1. **準備Kobo數據庫文件**：
   - 將Kobo設備的`KoboReader.sqlite`文件複製到項目目錄

2. **運行同步**：
   ```bash
   python uploadToNotion.py
   ```

3. **測試章節提取功能**：
   ```bash
   python test_chapter_extraction.py
   ```

4. **查看階層式排列演示**：
   ```bash
   python demo_hierarchical_output.py
   ```

5. **查看簡潔markdown語法演示**：
   ```bash
   python demo_simple_markdown_output.py
   ```

6. **測試不同書籍的章節提取**：
   ```bash
   python test_different_book.py
   ```

## 數據庫結構

### 主要表結構

- **content表**：存儲書籍基本信息
- **Bookmark表**：存儲高亮和筆記信息
  - `Text`：高亮內容
  - `ContentID`：章節文件路徑
  - `ChapterProgress`：章節進度
  - `StartContainerPath`：開始位置
  - `EndContainerPath`：結束位置

### 章節信息提取

章節信息從`ContentID`字段中提取，格式為：
```
book_id!OEBPS!Text/chapter_name.xhtml
```

例如：`012e1669-089b-40e6-854a-0b59dd194f66!OEBPS!Text/01.xhtml`

## 代碼結構

### 主要文件

- `DBReader.py`：數據庫讀取和章節信息提取
- `uploadToNotion.py`：Notion同步和格式化
- `test_chapter_extraction.py`：功能測試腳本
- `demo_hierarchical_output.py`：階層式排列演示腳本
- `demo_simple_markdown_output.py`：簡潔markdown語法演示腳本
- `test_different_book.py`：不同書籍章節提取測試腳本

### 核心函數

- `getHLWithChapterFromDB()`：獲取帶章節信息的高亮內容
- `extract_chapter_name()`：從ContentID提取章節名稱（支持多種格式）
- `sync_book_highlights_with_chapter()`：同步帶章節信息的高亮到Notion（簡潔markdown格式）

## 注意事項

1. **數據庫文件**：確保`KoboReader.sqlite`文件存在且可訪問
2. **Notion權限**：確保Notion API Token有足夠的權限
3. **網絡連接**：需要穩定的網絡連接來訪問Notion API
4. **數據備份**：建議在同步前備份重要數據

## 故障排除

### 常見問題

1. **章節名稱顯示為"未知章節"**
   - 檢查ContentID格式是否正確
   - 確認數據庫文件完整性

2. **章節名稱格式異常**
   - 檢查章節提取邏輯是否支持該格式
   - 確認數據庫文件完整性

3. **Notion同步失敗**
   - 檢查API Token和Database ID
   - 確認網絡連接正常

## 更新日誌

### v2.3 (最新)
- ✅ 新增智能章節提取功能
- ✅ 自動優化章節名稱顯示（Section格式轉換）
- ✅ 移除進度百分比顯示
- ✅ 使用簡潔的markdown語法格式
- ✅ 支持多種章節命名格式

### v2.2
- ✅ 新增簡潔的markdown語法格式
- ✅ 使用單層級標題 (#) 表示章節
- ✅ 使用列表格式 (*) 表示畫線內容
- ✅ 按閱讀進度排序章節
- ✅ 優化視覺層次和排版

### v2.1
- ✅ 新增階層式章節排列功能
- ✅ 按閱讀進度排序章節
- ✅ 章節標題顯示平均進度
- ✅ 劃線內容作為單純文本區塊
- ✅ 優化視覺層次和排版

### v2.0
- ✅ 新增章節信息提取功能
- ✅ 按章節分組顯示高亮內容
- ✅ 顯示章節進度百分比
- ✅ 優化Notion頁面排版

### v1.0
- ✅ 基礎高亮內容同步功能
- ✅ 書籍信息同步
- ✅ 封面圖片獲取

## 參考項目

本項目參考了 [mollykannn/kobo2notion](https://github.com/mollykannn/kobo2notion) 的設計理念，並在其基礎上增加了智能章節提取功能，參考了 [export-kobo](https://github.com/eliascotto/export-kobo/blob/main/export-kobo.py) 的章節提取邏輯。

## 貢獻

歡迎提交Issue和Pull Request來改進這個工具！

## 許可證

MIT License
