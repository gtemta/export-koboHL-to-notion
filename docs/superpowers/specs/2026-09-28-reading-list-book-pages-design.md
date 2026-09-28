# Reading List 書頁補完（書籍介紹＋AI 剖析）設計

> 記錄日期：2026-09-28
> 對應：與 `docs/KNOWLEDGE_REFINEMENT_PLAN.md` Phase 6 P2（讀畢書摘，同樣寫進 Reading List 書頁）相鄰但不同——
> 本案只做**書籍介紹頁**，社群貼文不在範圍
> 分支：`feat/reading-list-pages`（從 `feat/card-claim-titles` 開出；該分支尚有 9 個 commit 未合進 main）
> 狀態：設計已與使用者逐段確認，待寫實作計畫——**一份 spec、兩份計畫**：先寫並完成 M1，
> M1 在 Notion 真跑驗收後才寫 M2 計畫（M2 會用到 M1 的實測結果）

## 背景

同步流程會在 📚 Personal Reading List 自動建書頁（`ZettelkastenCardRepository._create_book_page`），
但只寫 `Name`／`Kobo EReader`／`Status` 三個屬性，內文全空、沒有封面。Reading List 的 gallery view
用「頁面第一張圖」當卡片預覽，所以這些書在 gallery 裡是一格格空白。

使用者手動建的書頁都套資料庫預設模板「心得摘錄」：書籍資料 → 筆記圖 → 概要 → 實際執行 → 心得 →
金句摘錄。卡片盒裡每本書已有 7–21 張卡，但從書頁上看不到它們。

另外，劃線頁（Kobo DB）的封面大多是**看不見的透明圖**——見「關鍵事實」，同一個 fetcher 也是書頁封面的來源，
所以一併修。

## 目標與成功標準

- 打開任一頁「同步建的書頁」，外觀與使用者手動頁一致：封面、書籍資料、本書卡片 gallery、連回劃線頁；
  Reading List 的 gallery view 看得到書封。
- 已讀完的書另有 🤖 標示的 AI 剖析（概要）、`Summary 一言以蔽之`、心得段的 Kobo 註記原文。
- 使用者**不需要找圖貼圖**；使用者寫過的任何內容**永遠不被覆寫**。

## 關鍵事實（2026-09-28 實地查證，實作時不需重查）

### Notion 端

| 事實 | 備註 |
|------|------|
| Reading List 共 163 頁，其中 **26 頁 `created_by` = 本 integration** | 以 `users.me()` 的 bot id 比對，已用唯讀腳本驗證；這 26 頁 17 本 🔖閱讀完畢、9 本 📖 閱讀中 |
| 這 26 頁由 `_create_book_page` 建立、不帶 children | 抽查確認內文空白、無 cover／icon |
| Reading List 屬性：`Name`(title)、`Status`(select：Ready to Start／📖 閱讀中／🔖閱讀完畢／✍️轉換完畢／Blog Published)、`Summary 一言以蔽之`(text)、`Type 書籍種類`(relation)、`推薦分數/5`(relation, limit 1)、`Done Date`(date)、`Blog Link`(url)、`slug`(text)、`Kobo EReader`(relation)、`完成閱讀 `(formula) | `📖 閱讀中` 的 📖 後有空格 |
| `Type 書籍種類` 指向「Dante 閱讀標籤分類庫」，title 欄叫 `領域（標籤名）`，共 10 頁：Psychology、Project Management、Business & Finance、Spiritual Inspiration、Philosophy & Science、Learning Skills、Software Engineering、Others、Logical Thinking、Marketing | 實作時由 Books DB schema 的 relation 取得目標 DB，**不寫死 id** |
| `推薦分數/5` 指向「Dante 閱讀推薦等級庫」（💜 ～ 💜💙💚🧡♥️） | 使用者個人評價，本案永不寫入 |
| gallery view「五星評價」「閱讀完成」設定 `cover: page_content` | 預覽圖 = 頁面內文第一張圖 → 書籍資料段必須放書封圖片 |
| 模板「心得摘錄」段落（`##`）：書籍資料／筆記圖／概要／實際執行／心得／金句摘錄；筆記圖內有一顆按鈕與一個卡片盒 linked view | 該 view 是**依來源分組、沒有篩選**的 table，會列出整個卡片盒；手動頁（如《高產出的本事》）的「來源＝本頁」篩選是使用者事後手動加的 |
| 卡片盒約 497 張卡，全部有 `來源`；26 本書各有 7–21 張 | 卡片內文結構：paragraph（內容）＋ quote（原文）＋ 📖 callout |
| 劃線頁封面實測：**6/26** 是 Google Books 真圖；**20/26** 是 Open Library 回傳的 **43 bytes 1×1 透明 GIF** | 對應書頁同樣會「有封面但看不見」 |

### 程式碼端

| 事實 | 位置 |
|------|------|
| Books DB 邏輯（反查、書名比對、補 relation、自動建頁、Status 推導）全在卡片 repo | `src/infrastructure/notion/zettelkasten_card_repository.py:310-527` |
| `resolve_book_page` 是外部唯一的公開入口，`backfill_zettelkasten.py:235` 在用 | `zettelkasten_card_repository.py:170` |
| `test_book_page_autocreate.py` 直接呼叫 `_book_status_name`／`_create_book_page`／`_find_book_page` | 抽出後改測新類別 |
| 依 `來源` relation 分頁查卡片的寫法 | `zettelkasten_card_repository.py:529`（`_existing_source_ids`） |
| 同步用 ThreadPoolExecutor 並行處理書；卡片 use case 呼叫點兩處 | `src/application/use_cases/sync_books_use_case.py:44`、`:92`（已匯出分支）、`:133`（新書分支） |
| `_process_single_book` 只回傳 bool；測試只經由 `execute()` 呼叫 | `sync_books_use_case.py:68`、`tests/unit/test_resync.py` |
| `add_book_cover` 把同一個 URL 同時設成 icon 與 cover；`_has_existing_cover` 只要 icon 是 external 就當作已有 → 透明圖**永遠不會重試** | `src/infrastructure/notion/notion_api_repository.py:126`、`:196` |
| `_clean_html`（去 HTML／實體字元） | `notion_api_repository.py:309` |
| Google Books 不帶 API key、`intitle:<完整書名>`、`maxResults=1`，只取第一筆 | `src/infrastructure/external/cover_fetcher.py:14-35` |
| Open Library 只是組 URL，不檢查圖片存在 | `cover_fetcher.py:38` |
| 書籍查詢沒有選 `content.ImageId`；TOC 查詢有 `Depth` | `src/infrastructure/persistence/kobo_sqlite_repository.py:26`、`:43` |
| `split_rich_text`（2000 字切段）、`heading_block`、`quote_block`（quote＋💭 child）可直接重用 | `src/infrastructure/notion/highlight_page_blocks.py` |
| `_ollama_generate`（產卡／分類／審核共用的串流 helper）、`_strip_thinking`、`CardReviewer._loads_json`、`CardReviewer.is_available`（檢查模型是否 pull 過） | `zettelkasten_generator.py:29`、`:550`、`:1372`、`:1169` |
| `RESYNC_HIGHLIGHTS` 的解析與比對（空=停用、`all`、書名子字串清單） | `src/config/settings.py:73`、`:79` |

### 外部服務與套件

| 事實 | 備註 |
|------|------|
| notion-client 2.2.1：預設 Notion-Version `2022-06-28`；`pages.create`／`pages.update` 以 `pick()` 白名單過濾參數（`template` 等新參數會被**靜默丟掉**）；`blocks.children.append` 有傳 `after`；`Client.request(path, method, body)` 可原樣送出任何 body | 已讀原始碼確認 |
| Views API 需 Notion-Version ≥ `2025-09-03`：`POST /v1/views`，必填 `data_source_id`、`name`、`type`，並擇一 `database_id`／`view_id`／`create_database`；`create_database: {parent: {type: "page_id", page_id}}` 會在頁面上建一個 linked view；`filter` 格式同 data source query | 容器在頁面中的**落點**文件沒寫 → M1 第一個任務驗證 |
| Google Books 不帶 key 時與全球共用每日配額：2026-09-28 實測 3/3 回 **429 "Quota exceeded … Queries per day"** | 這就是 20 本落到 Open Library 的根因 |
| 26 本中有 **10 本**的 Kobo「ISBN」不是 ISBN-13（非 978／979 開頭，例 `7363579164627`） | 拿它查 ISBN 一定查不到 |
| `checkUSBandUpload.py` 會先把裝置 `.kobo/KoboReader.sqlite` 複製到工作目錄再跑 `main.main()` | 使用者於 2026-09-28 放入資料庫後完成下列驗證 |
| **Kobo 圖床已驗證**：`content.ImageId`（有劃線的 35 本書 35/35 有值，是獨立於 `ContentID` 的 UUID）組成 `https://cdn.kobo.com/book-images/{ImageId}/353/569/90/False/image.jpg` → **35/35** 回傳有效 JPEG（78–104 KB、約 0.2 秒）；目視確認《多巴胺國度》為正確的繁中版封面 | 舊圖床 `kbimages1-a.akamaihd.net` 同路徑回 400，不用 |

## 使用者已定案的決策（不要再問）

1. **AI 剖析與心得分開**：AI 寫客觀剖析放「概要」並以 🤖 標註；「心得」只放使用者在 Kobo 寫的 💭 註記原文，
   其餘留白。理由：手動頁的心得都是個人經驗，模型寫不出來。
2. **讀完才寫 AI 剖析**：建頁時只放不需要 LLM 的部分；概要／一言以蔽之／心得註記等「讀完」那次同步才寫。
   理由：閱讀中卡片不齊，剖析寫了又不覆蓋，會永遠停在半本的理解。
3. **做法 A：程式自建版面＋Views API 放卡片 gallery**，不套用 Notion 模板。放棄模板裡那顆按鈕，
   以及「改模板、新頁跟著變」的能力（理由見 ADR）。
4. **封面全自動**，使用者不找圖；**順便修好劃線頁那 20 張透明封面**（同一個 fetcher）。
5. **只處理同步建的頁**（`created_by` = integration）；使用者手動建的頁完全不碰，包括它們的空白段。
6. 開關語法與 `RESYNC_HIGHLIGHTS` 相同，可先對單本書試跑。
7. 第一次開啟時不設「每次同步最多寫 N 本」的上限（使用者未要求）。
8. 一份 spec、兩份實作計畫（M1 → 真跑驗收 → M2）。

## 成品長相

### 版面與歸屬

段落標題一律 `heading_2`，文字與模板一致。

| 位置 | 內容 | 誰寫 | 何時 |
|---|---|---|---|
| 頁面 cover／icon | 書封（與劃線頁同一張） | 程式 | M1 |
| `## 書籍資料` | 書封圖片（gallery 預覽靠它）＋作者／出版社／ISBN（僅真 ISBN-13）＋「出版社簡介」toggle（Kobo `Description`）。閱讀進度等會變動的數字不放（劃線頁已有） | 程式 | M1 |
| `## 筆記圖` | 卡片盒 gallery view，篩選 `來源` 包含本頁，即時更新 | 程式 | M1 |
| `## 概要` | 🤖 callout「AI 整理」：全書主軸＋ 3–5 條核心論點，每條 @ 連到支撐它的卡片 | AI（過審核） | M2 |
| `## 實際執行` | 留白 | 使用者 | — |
| `## 心得` | 有 💭 註記的劃線原文（quote＋💭，與劃線頁同格式）；沒有註記就留白 | 使用者的原文 | M2 |
| `## 金句摘錄` | 「畫線重點 → @劃線頁」mention（與使用者手動頁寫法一致） | 程式 | M1 |

### 屬性

| 屬性 | 規則 | 何時 |
|---|---|---|
| `Type 書籍種類` | 卡片 Tags 多數決推出 1–2 個（見「書籍種類推算」）；欄位空白才寫 | M1（有卡片就寫） |
| `Summary 一言以蔽之` | `"🤖 " + 一句話`；欄位空白才寫。使用者改寫時拿掉 🤖，即成為使用者的內容 | M2 |
| `推薦分數/5`、`Status`、`Done Date`、`Blog Link`、`slug` | **永不寫入** | — |

### 「讀完」判定

`percent_read >= 99`（Kobo，與既有 `_BOOK_DONE_PERCENT` 一致），**或** Reading List `Status` ∈
{🔖閱讀完畢, ✍️轉換完畢, Blog Published}。後者讓使用者能手動觸發 Kobo 永遠到不了 99% 的書。

### 歸屬與冪等規則

- 只處理 `page.created_by.id == users.me().id` 的頁。
- 版面只寫在「空白頁」：沒有任何 block，或所有頂層 block 都是沒有文字的 paragraph。
- 每一段、每個屬性都**只在空白時寫**；重跑是 no-op → **不另寫回填工具**，開啟功能後跑一次同步，26 頁全部補上。
- 🤖 剖析每本書最多寫一次；使用者刪掉 🤖 區塊，程式不會補回來（依本地紀錄判斷，見 M2）。

## 封面

### 來源串接（`CoverFinder.find(book) -> Optional[str]`）

依序嘗試，第一個**通過驗證**的就用：

1. **Kobo 官方書封**：`book.image_id`（新增，取自 `content.ImageId`）→
   `https://cdn.kobo.com/book-images/{image_id}/353/569/90/False/image.jpg`。
   **已驗證**（見「關鍵事實」：35/35 命中、版本正確），是主力來源；後兩個來源只給沒有 `ImageId` 的書（例如側載）用。
2. **Google Books**：
   - `isbn` 是真 ISBN-13（`^97[89]\d{10}$`）→ `q=isbn:{isbn}`；
   - 再以主書名（`：`／`:` 之前）`q=intitle:{主書名}`、`maxResults=5`，取第一筆「書名 text core 互相包含」的結果；
   - 選填 `GOOGLE_BOOKS_API_KEY` 帶 `key=`；回 429／非 200 → 此來源放棄，每輪只 WARNING 一次並提示可設 key。
   - 縮圖 URL 沿用 `&zoom=1 → &zoom=3`。
3. **Open Library**：僅真 ISBN-13 →
   `https://covers.openlibrary.org/b/isbn/{isbn}-L.jpg?default=false`（沒有封面時回 404）。

### 驗證（`is_valid_image(url)`）

`GET`（timeout 8 秒）→ HTTP 200、`content-type` 以 `image/` 開頭、內容 > 2048 bytes。
拒收 1×1 透明圖與錯誤頁。

### 劃線頁舊封面修復

`NotionApiRepository.add_book_cover(page_id, book)`（改收 `Book`，ABC 與 dry-run decorator 同步改）：

- 既有 icon／cover 是 `covers.openlibrary.org` 的 URL → 用 `is_valid_image` 重驗；不合格視為「沒有封面」。
- 其他既有封面一律信任（不每輪重驗，避免每次同步多打幾十個 GET）。
- 沒有封面 → `CoverFinder.find`；找到就設 icon＋cover；**找不到且原本是無效封面 → 清掉**（`cover=None`、`icon=None`），
  讓狀態誠實。
- 這段屬於既有同步流程，**不受 `READING_LIST_PAGES` 開關影響**（它是 bug 修正）。

### 本輪快取

`CoverFinder` 以 `book.id` 做執行緒安全的 dict 快取：劃線頁（執行緒池內）與書頁（事後依序）共用結果，同一本書只查一次。

## 架構

### 元件（✚ 新增／✎ 修改）

| 層 | 檔案 | 職責 |
|---|---|---|
| domain | ✎ `entities/book.py` | 新增 `image_id: Optional[str] = None` |
| domain | ✚ `entities/book_card.py` | `BookCard`（page_id、title、tags、keywords、content）——從卡片盒讀回的卡片 |
| domain | ✚ `services/reading_list_rules.py` | 純規則：`derive_book_types(cards, mapping)`、`is_finished(percent_read, status)` |
| domain | ✎ `repositories/book_repository.py` | 新增 `get_toc_titles(book_id) -> List[str]`（M2） |
| domain | ✎ `repositories/notion_repository.py` | `add_book_cover(page_id, book)` 改收 `Book` |
| infra | ✎ `external/cover_fetcher.py` | `CoverFinder`（來源串接、驗證、快取）、`is_valid_image`、`is_legacy_openlibrary_url` |
| infra | ✎ `persistence/kobo_sqlite_repository.py` | `_BOOK_QUERY` 加選 `content.ImageId`；實作 `get_toc_titles`（`ContentType=899 AND Depth=1`，依 `VolumeIndex`，去空白／去重，最多 40 條） |
| infra | ✚ `notion/reading_list_repository.py` | 從卡片 repo **原樣搬出**的 Books DB 邏輯＋書頁讀寫（介面見下） |
| infra | ✎ `notion/zettelkasten_card_repository.py` | 改用 `ReadingListRepository`（約少 200 行，行為不變）；新增 `list_book_cards(books_page_id, with_content=False) -> List[BookCard]` |
| infra | ✚ `notion/reading_list_page_blocks.py` | 純函式：段落常數、版面三段、書籍資料、mention、`find_section`、`section_is_empty`、（M2）剖析與註記 blocks |
| infra | ✚ `notion/notion_views_client.py` | **全專案唯一**使用新版 API（`2025-09-03`）的地方 |
| infra | ✎ `notion/notion_api_repository.py` | `add_book_cover` 改用 `CoverFinder`＋舊封面修復；`_clean_html` 搬到 `text_utils.py` 後改為 import |
| infra | ✚ `notion/text_utils.py` | `clean_html`（自 `notion_api_repository._clean_html` 原樣搬出）：`Description` 屬性與書籍資料的出版社簡介共用 |
| infra | ✚ `notion/dry_run_reading_list_repository.py` | DRY_RUN decorator：讀取委派、寫入只記 log（同 `DryRunNotionRepository` 模式）；views client 同樣包一層 |
| infra | ✚ `llm/book_analysis.py` | （M2）`BookAnalyzer`、`AnalysisReviewer`、輸出與審核的純函式解析 |
| infra | ✚ `persistence/analysis_store.py` | （M2）`reading_list_output/<slug>.json` 本地留存 |
| app | ✚ `use_cases/complete_reading_list_page_use_case.py` | 單本書的補頁流程 |
| app | ✎ `use_cases/sync_books_use_case.py` | 記下處理成功的書與劃線頁 id；執行緒池結束後依序補頁 |
| config | ✎ `settings.py`、`container.py`、`.env.example`、`.gitignore` | `READING_LIST_PAGES`、`GOOGLE_BOOKS_API_KEY`、`DEFAULT_BOOK_TYPE_MAPPING`；`.gitignore` 加 `reading_list_output/` |

### 主要介面

```python
class ReadingListRepository:
    # --- 自 ZettelkastenCardRepository 搬移，行為不變 ---
    def resolve_or_create(self, title, source_page_id=None, percent_read=None) -> Optional[str]
    # --- 新增 ---
    def find_page(self, title, source_page_id=None) -> Optional[dict]  # 反查 → 書名比對；絕不建頁；回完整 page 物件
    def is_created_by_integration(self, page: dict) -> bool           # users.me() 每輪快取一次
    def list_blocks(self, page_id) -> List[dict]                      # 頂層 block，分頁讀完
    def append_blocks(self, page_id, blocks, after=None) -> List[dict]  # 回傳建立的 block（取 id 用）
    def update_page(self, page_id, properties=None, cover_url=None, icon_url=None) -> None
    def type_page_ids(self, names: List[str]) -> Dict[str, str]       # 書籍種類名稱 → 種類庫頁 id，每輪快取

class NotionViewsClient:  # Client(auth=token, notion_version="2025-09-03") + client.request(...)
    def data_source_id(self, database_id) -> str                      # GET databases/{id} → data_sources[0].id，快取
    def create_card_gallery(self, page_id, cards_database_id, book_page_id) -> Optional[str]

class CompleteReadingListPageUseCase:
    def __init__(self, reading_list, card_repo, views, cover_finder, cards_database_id,
                 book_repo=None, analyzer=None, analysis_store=None)  # 後三者 M2 才注入
    def execute(self, book: Book, kobo_page_id: str) -> None
```

`ZettelkastenCardRepository` 建構子新增可選參數 `reading_list: Optional[ReadingListRepository]`；
未傳入且有 `books_database_id` 時自行建立一個——`backfill_zettelkasten.py` 與既有測試的建構方式不用改。
`resolve_book_page` 委派給 `reading_list.resolve_or_create`。

### 流程（每次 `python main.py`）

```
SyncBooksUseCase.execute()
├─ 執行緒池（不變）：劃線頁 → 卡片（卡片流程仍負責自動建 Reading List 頁）
│    └─ _process_single_book 改回傳 Optional[str]（劃線頁 id；None = 失敗），成功者記入清單
└─ 新增：池結束後，依書名排序、依序執行（只對 should_complete_page(title) 為真的書）
     CompleteReadingListPageUseCase.execute(book, kobo_page_id)
       1. page = find_page(...)；找不到 → return（DEBUG）
       2. 不是 integration 建的 → return
       3. blocks = list_blocks(page_id)；cover = cover_finder.find(book)
       4. 空白頁 → 寫版面（三段，見 M1），寫完**重讀一次 blocks**，供後續步驟定位段落
       5. cover 有值時：頁面缺 cover 就補 cover、缺 icon 就補 icon（各自判斷，都用同一張書封）
       6. `Type 書籍種類` 空白 → list_book_cards → derive_book_types → type_page_ids → update_page
       7. （M2）見「M2：AI 剖析」
```

依序執行的理由：M2 使用地端 LLM，VRAM 一次只放得下一個模型，與執行緒池內的產卡並行會互搶；依序也讓 log 可讀。

### 設定

| env | 說明 |
|---|---|
| `READING_LIST_PAGES` | 空＝關閉；`all`＝全部；否則為逗號分隔的書名子字串。解析沿用 `_parse_resync`，比對規則同 `resync_matches` |
| `GOOGLE_BOOKS_API_KEY` | 選填；有值才帶 `key=` |
| 依賴 | 需要 `NOTION_BOOKS_DATABASE_ID`（缺 → WARNING 並停用本功能）；卡片 gallery 與書籍種類需要 `NOTION_ZETTELKASTEN_DATABASE_ID`（缺 → 這兩項跳過、版面照寫） |
| 組裝 | `container.py` 在本功能開啟且 `NOTION_ZETTELKASTEN_DATABASE_ID` 有值時，**一律建立** `ZettelkastenCardRepository` 供讀卡片——與 `ENABLE_ZETTELKASTEN_CARDS`（是否產卡）無關；同一個 `ReadingListRepository` 實例注入卡片 repo 與補頁 use case |

`DEFAULT_BOOK_TYPE_MAPPING`（`settings.py` 常數，不開 env）：

| 卡片 Tags | 書籍種類 |
|---|---|
| 💞心理學 | Psychology |
| 🧠學習技巧 | Learning Skills |
| 💼商務、💰理財投資 | Business & Finance |
| 🧘‍♂️人生觀點 | Spiritual Inspiration |
| 🧩邏輯思考 | Logical Thinking |
| 🔬哲學科學 | Philosophy & Science |
| 💻軟體工程 | Software Engineering |
| 📈行銷 | Marketing |
| 📋專案管理 | Project Management |

Tags 比對沿用 emoji-insensitive 的 text core 慣例（同卡片分類）。

### DRY_RUN

- `ReadingListRepository` 與 `NotionViewsClient` 各包一層 dry-run decorator：讀取照常、寫入只記 `[DRY RUN]` log。
- `CoverFinder` 的外部 GET 是讀取，照常執行。
- M2 在 dry-run 下**不呼叫 LLM**，只記「將為 N 本已讀完的書產生剖析」。
- 因此 M1 可用 `DRY_RUN=true python main.py` 預覽（符合 DoD 第 2 條）。

## M1 細節

### 版面寫入順序

linked view 容器預期只能加在頁尾，所以分三次寫，讓 gallery 落在「筆記圖」底下：

1. `append_blocks`：`## 書籍資料`、書封 image（有才放）、書籍資訊、「出版社簡介」toggle（有才放）、`## 筆記圖`
2. `views.create_card_gallery(page_id, cards_database_id, book_page_id=page_id)`
3. `append_blocks`：`## 概要`、`## 實際執行`、`## 心得`、`## 金句摘錄`、「畫線重點 → 」＋ mention（劃線頁）

第 2 步的實際落點由第一個任務驗證；若 API 支援指定位置則改用之、順序可簡化。

### 書籍資料

- image block：`{"type": "external", "external": {"url": cover}}`。
- 書籍資訊：bulleted list，`作者：…`、`出版社：…`、`ISBN：…`；欄位缺值就不列；ISBN 只列真 ISBN-13。
- 「出版社簡介」：可收合的 `toggle` block，children 為 `_clean_html(book.description)` 以 `split_rich_text` 切段的 paragraph。

### 卡片 gallery

`POST /v1/views` body（欄位名以第一個任務驗證為準）：

```json
{
  "data_source_id": "<卡片盒 data source id>",
  "name": "本書卡片",
  "type": "gallery",
  "create_database": {"parent": {"type": "page_id", "page_id": "<書頁 id>"}},
  "filter": {"property": "來源", "relation": {"contains": "<書頁 id>"}},
  "sorts": [{"property": "標題", "direction": "ascending"}]
}
```

### 書籍種類推算（`derive_book_types`，純函式）

1. 每張卡的每個 Tag 經 mapping 轉成種類；**同一張卡對同一種類只算 1 票**（💼商務＋💰理財投資 → Business & Finance 1 票）。
2. 票數由高到低排序，同票依 mapping 表順序。
3. 取第 1 名；第 2 名票數 ≥ 第 1 名的一半時一併取，最多 2 個。
4. 沒有卡片或沒有任何可對應的 Tag → 回空（不寫）。

例：《多巴胺國度》17 張卡，心理學 15 票、其餘各 1–2 票 → 只有 Psychology。

名稱 → 種類庫頁 id（`type_page_ids`）：由 Books DB schema 中 `Type 書籍種類` relation 的目標 DB 取得種類庫，
以該 DB schema 裡 `type == "title"` 的屬性（目前叫 `領域（標籤名）`）比對名稱；兩者都不寫死。

### 段落定位（`find_section`、`section_is_empty`）

- 段落 = 文字（strip 後）完全等於段落名的 `heading_1`／`heading_2`／`heading_3`（層級記為 L），
  到下一個**層級 ≤ L** 的標題之前的所有頂層 block。段內較低層級的標題（例如 `##` 概要底下的 `###` 小標）
  屬於段落內容——使用者手動頁的概要就有這種寫法，若把 `###` 當成段落結尾，會把有內容的概要誤判為空白。
- 空白 = 段落內沒有 block，或全部是沒有文字的 paragraph（有文字的小標題算有內容）。
- 找不到段落 → 回 None，呼叫端跳過該段並記 WARNING，**絕不寫到別處**。

## M2：AI 剖析

### 觸發條件（全部成立才做）

1. 已讀完（見「讀完判定」）
2. `## 概要` 存在且空白
3. 本地沒有這本書的紀錄，或紀錄是 `passed`（已審核通過、尚未寫入 → 直接續傳，不重跑 LLM）
4. 卡片盒裡這本書的卡片 ≥ 5 張
5. 不是 dry-run
6. `analyzer.is_available()`：Ollama 連得上，且 `OLLAMA_MODEL`、`OLLAMA_REVIEW_MODEL` 都已 pull；否則 WARNING、這次跳過、**不留紀錄**

### 輸入（只用使用者的資料）

- 書名、作者、`_clean_html(book.description)`
- `book_repo.get_toc_titles(book.id)`
- `list_book_cards(page_id, with_content=True)`：標題、內文（第一個 paragraph）、Key Word，編號 1..N
- **刻意不放**：💭 註記（使用者的心得素材，不該被改寫成「客觀剖析」）、原始劃線（卡片已是審核過的精華）
- prompt 明文禁止：作者生平、書評、銷量、其他書、任何輸入沒有的事實／數字／評價；每條論點至少引用一張卡片；
  繁體中文、台灣用語；論點標題為 5–20 字的主張句（與卡片 K1 規則一致）

### 輸出格式與解析

```
【主軸】這本書在回答什麼問題、核心主張是什麼（1–2 句）
【論點】主張句標題｜1–2 句說明｜卡片 3,7
（3 到 5 條【論點】）
【一言以蔽之】≤25 字
```

- 解析前先 `_strip_thinking`；容忍全形／半形 `|`、`｜` 與前後空白。
- 卡片編號超出 1..N 的丟掉；丟完仍無引用的論點整條丟掉。
- 缺【主軸】、有效論點 < 3、或缺【一言以蔽之】→ 解析失敗。
- 論點 > 5 取前 5；一言以蔽之 > 25 字截斷。

### 審核閘門（交叉審核，沿用卡片的原則）

產生：`OLLAMA_MODEL`；審核：`OLLAMA_REVIEW_MODEL`。審核 prompt 附上完整輸入（編號卡片、簡介、目錄）與剖析，
只輸出 JSON：`{"grounding": n, "coverage": n, "clarity": n, "notes": "..."}`，三項 1–5 分，
**全部 ≥ `ZETTELKASTEN_REVIEW_MIN_SCORE`（預設 4）才通過**，不用平均。

- **grounding（忠實）**：每條論點都被它引用的卡片支撐；沒有輸入以外的事實、數字、評價。
- **coverage（涵蓋）**：主軸與論點抓的是全書主線（對照簡介與目錄），不是枝節。
- **clarity（清晰）**：論點彼此不重複、各自是完整主張句；一言以蔽之對得上主軸。

JSON 抽取沿用 `_loads_json` 的容錯方式；分數缺漏、非整數、超出 1–5、或為 bool → 解析失敗。

### 單輪嘗試流程（每輪同步、每本書最多產生 2 次）

```
attempt 1..2:
  產生 → 解析失敗 → 還有次數就重產（不帶意見）；否則「暫時失敗」
  審核 → 回應解析失敗 → 「暫時失敗」
  審核 → 有任一項 < 門檻 → 還有次數就帶 notes 重產；否則記 rejected
  審核 → 通過 → 記 passed → 寫入 Notion → 記 uploaded
暫時失敗：不留紀錄，下次同步自動再試
```

### 寫入頁面

寫入順序：**心得 → 一言以蔽之 → 概要**。概要最後寫，兼作「完成標記」：中途任何一步失敗，紀錄停在 `passed`、
概要仍空白，下次同步以 `passed` 續傳；已寫好的心得／一言以蔽之因為不再空白而自動跳過，不會重複。

- **概要**：`append_blocks(page_id, [callout], after=概要標題 id)`，callout icon 🤖、`gray_background`，文字
  「AI 整理｜依 {N} 張卡片{、出版社簡介}{、目錄}｜{YYYY-MM-DD}」（沒有簡介／目錄就不列）。children：
  主軸 paragraph；每條論點一個 bulleted item：粗體標題 ＋「 — 」＋ 說明 ＋ 各引用卡片的 page mention。
- **一言以蔽之**：欄位空白才寫 `"🤖 " + 一句話`。
- **心得**：`## 心得` 存在且空白、且有帶註記的劃線 → 在標題後插入「📝 Kobo 註記原文（{m} 則）」paragraph，
  以及每條註記劃線的 `quote_block(h)`（與劃線頁同格式）。切批沿用劃線頁的方式：每批含巢狀 block 不超過 80
  （`total_block_count` 計算）；後一批的 `after` 取前一批最後建立的頂層 block id，維持原順序。

> ⚠️ **M2 計畫前必須重新討論心得段的來源**（2026-09-28 資料盤點發現，見附錄）：使用者的 3,080 筆劃線
> **打字註記為 0**，照上面的規則心得段對所有書都會留白。使用者實際的筆記是 **121 筆手寫 markup**（分布 26 本書），
> SQLite 只存位置與時間、圖檔在裝置上，目前被 `_BOOKMARK_FILTER` 當成空白雜訊排除。M1 不受影響。

### 本地留存（`reading_list_output/<slug>.json`，gitignore）

每本書一個檔（檔名規則同 `CardStore._slug`），欄位：`book_title`、`status`（`passed`／`rejected`／`uploaded`）、
`created_at`、`uploaded_at`、`generator_model`、`review_model`、`card_count`、
`analysis`（`theme`、`points[{title, explanation, card_page_ids}]`、`one_liner`）、
`review`（三項分數＋`notes`）、`attempts`。

| 狀態 | 下次同步的行為 |
|---|---|
| 無紀錄 | 符合觸發條件就產生 |
| `passed` | 不重跑 LLM，直接寫入 Notion（上次寫入失敗的續傳） |
| `uploaded` | 不再處理，即使「概要」後來變空白（使用者刪掉即為使用者的選擇） |
| `rejected` | 不自動重試；INFO log 提示「刪除該檔即可重試」 |

審核分數只留在本地與 log；Notion 上只有 🤖 標示。

### 時間成本（粗估）

一本約 1–4 分鐘（讀卡片內文約 16 次 API 呼叫、產生、審核）。第一次開啟時 17 本已讀完的書一次跑完，約 20–70 分鐘；
之後每次同步只處理新讀完的書。

## 錯誤處理

| 狀況 | 行為 |
|---|---|
| 單本書補頁拋例外 | 該本 try/except；`result.add_error("補頁失敗: …")`，出現在結尾摘要；**不算劃線同步失敗、不影響 exit code** |
| Views API 失敗 | 「筆記圖」改放本書卡片的 mention 清單（靜態），WARNING |
| 找不到封面 | 不放 image block，其餘照寫，INFO |
| 找不到某段標題 | 該段跳過，WARNING，絕不寫到別處 |
| Tags 對不到種類，或種類庫找不到該名稱 | 不填，WARNING（附缺少的名稱） |
| Notion 409／429 | 沿用 `retry_with_backoff`＋`NotionRateLimiter` |
| Google Books 429 | 此來源本輪放棄，WARNING 一次（提示 `GOOGLE_BOOKS_API_KEY`） |
| M2 各種失敗 | 見「單輪嘗試流程」與「本地留存」 |

## 測試

- **純函式單元測試（不連網）**
  - `derive_book_types`：單一多數、兩類、同票、同卡雙 Tag 同種類只算一票、對不到、沒有卡片
  - `is_finished`：99／98.9／None，各 Status
  - `reading_list_page_blocks`：三段版面順序、缺作者／出版社／簡介／封面時的省略、非 ISBN-13 不列、mention 結構、
    `find_section`／`section_is_empty`（`#`／`##`／`###` 各層級、**`##` 概要底下只有 `###` 小標＋內容時判定為非空白**、
    空 paragraph、找不到段落）
  - `CoverFinder`（mock HTTP）：來源順序、429 跳下一個、43 bytes GIF 被拒、真 ISBN 判斷、書名比對、快取只查一次、
    舊 Open Library URL 判斷
  - （M2）輸出解析（正常、缺段、編號越界、thinking 前綴、全形／半形分隔）、審核解析、剖析與註記 blocks、
    `analysis_store` 各狀態轉移
- **fake-client 編排測試**（同 `tests/unit/test_notion_upload_batching.py` 模式）
  - 空白頁：寫入順序為前段 → view → 後段
  - 第二次執行零寫入
  - `created_by` 非 integration 的頁零寫入；`## 概要` 有內容時不寫剖析
  - dry-run decorator 零寫入
  - 頁面已有 cover 但沒有 icon → 只補 icon
  - `add_book_cover`：無效舊封面被替換；找不到替代時被清掉；有效封面不重驗
  - （M2）寫入順序為心得 → 一言以蔽之 → 概要；概要寫入失敗後再跑一次，只補概要、不重複寫心得與一言以蔽之、不重跑 LLM
- **既有測試**：`test_book_page_autocreate.py` 改測 `ReadingListRepository`；全部綠燈；`python -m ruff check .` 乾淨。

## 真跑驗收（DoD 第 3 條，以觀察收尾）

1. **第一個任務：驗證 Views API**（不成立 → 停下與使用者討論，不硬做；Kobo 圖床已在設計階段驗證過）
   - 在 Reading List 建一頁暫時測試頁（`_spike_讀書頁`），依「版面寫入順序」寫前段 → 建 gallery（篩選指向
     《多巴胺國度》書頁，應顯示 17 張卡）→ 寫後段；確認 view 落在「筆記圖」底下、篩選正確；驗證後封存（archive）測試頁。
2. **M1**：`DRY_RUN=true` 預覽 → `READING_LIST_PAGES=<一本閱讀中>,<一本已讀完>` 真跑 → Notion 上看到版面、封面、
   gallery、書籍種類，Reading List gallery 出現書封，劃線頁的透明封面被換掉 → 改 `all` 真跑 26 頁。
3. **M2**（M2 計畫寫完後）：挑一本已讀完的書真跑 → 看到 🤖 概要、一言以蔽之、心得註記，本地 JSON 狀態為
   `uploaded` → 改 `all`。

每一步保留 log 片段作為證據再宣告完成。

## 已知風險

- **Views API 容器落點與 body 欄位**未驗證 → 第一個任務；失敗時退回靜態卡片清單。
- Kobo 圖床是非公開 API 的網址慣例，Kobo 日後可能更改；驗證失敗時自動落到 Google Books／Open Library，不會壞掉，只會少封面。
- 地端小模型的剖析品質：以「只用卡片與簡介」＋交叉審核壓制；持續解析失敗的書會每次同步重試（成本：每本每次數分鐘）。
- 第一次開 M2 需 20–70 分鐘，若經由插 USB 自動同步觸發會拖長該次同步。
- 使用者改段落標題或種類庫名稱 → 該項跳過並 WARNING。
- **Reading List 頁仍只由卡片流程建立**：目前 `.env` 的 `ENABLE_ZETTELKASTEN_CARDS=false`，新書不會自動有書頁，
  直到卡片流程開啟。
- 本地紀錄是單機的：換一台電腦同步時沒有 `uploaded` 紀錄，若使用者刪過 🤖 區塊（概要又變空白），會再寫一次。

## 不做

- 社群貼文（Phase 6 P1–P3）
- 重產／更新已寫入的剖析
- 使用者手動建的頁，以及它們的空白段
- 讀完後自動把 `Status` 從 📖 改成 🔖（已知缺口，可另開一圈）
- `推薦分數/5`、`實際執行`、`Done Date`、`Blog Link`、`slug`
- 套用 Notion 模板、模板裡的按鈕
- 為沒有卡片的書建 Reading List 頁
- 每次同步的剖析數量上限

## 文件更新（同圈完成，不留到之後）

- `CLAUDE.md`：新增「Reading List 書頁補完」一節（流程、歸屬規則、讀完判定、封面來源、Views API 的新版 API 例外、
  env）；Development Commands 補 `READING_LIST_PAGES` 用法；Configuration 補新 env。
- `docs/DECISIONS.md` 三條 ADR：
  1. 書頁版面由程式自建＋Views API，不套模板（模板的 view 沒有篩選、套用是非同步且需兩個新 API；代價是沒有按鈕、
     改模板不會連動）
  2. AI 剖析讀完才寫、與心得分開、每本最多寫一次
  3. 封面改 Kobo 圖床優先、每張圖先驗證（20/26 透明圖的根因：不帶 key 的 Google Books 配額＋未驗證的 Open Library）
- `.env.example`：`READING_LIST_PAGES`、`GOOGLE_BOOKS_API_KEY`
- `.gitignore`：`reading_list_output/`

## 附錄：KoboReader.sqlite 資料盤點（2026-09-28）

使用者要求「若發現可以取出更多資訊，也記錄下來」。以下以唯讀方式（`mode=ro`）盤點使用者的資料庫；
「有值」以有劃線的 35 本書（或 3,080 筆劃線）為分母。**本案只用到第一列**，其餘皆為候選，未納入任何範圍。

### 書籍（`content`，`ContentType = 6`）

| 欄位 | 有值 | 內容 | 用途／候選 |
|---|---|---|---|
| `ImageId` | 35/35 | 書封圖片 UUID | **本案 M1 使用**：Kobo 圖床封面 |
| `Subtitle` | 26/35 | 多為原文書名（例：`DOPAMINE NATION: Finding Balance…`） | 候選：書籍資料加「原文書名」（既有同步已寫到劃線頁的 `Subtitle` 屬性） |
| `Series`／`SeriesNumber`／`SeriesID` | 26／10／26 | 出版社書系（例：`自由學習`；部分前綴全形空白） | 候選：書籍資料加「書系」 |
| `DateCreated` | 35/35 | 例：《多巴胺國度》`2023-03-02` | 推測為 Kobo 電子書上架日（非紙本出版日，未證實） |
| `Language` | 35/35 | 全部 `zh` | 低價值 |
| `AverageRating`／`RatingCount` | 6/35 | Kobo 商店評分（例：4.66／135 則） | 候選：書籍資料加「Kobo 評分」 |
| `TimesStartedReading`／`LastTimeStartedReading` | 32/35 | 開始閱讀次數與時間 | 候選：閱讀歷程 |
| `LastTimeFinishedReading` | 26/35 | Kobo 記錄的讀完時間 | 候選：比 Notion 自動化填的 `Done Date`（= 同步當天）更準；本案不碰 `Done Date` |
| `TimeSpentReading`／`___PercentRead` | 34／28 | 閱讀秒數、進度 | 既有同步已寫到劃線頁 |
| `PageProgressDirection` | 14/35 | `rtl` = 直排書 | 低價值 |
| `WishlistedDate` | 4/35 | 曾加入願望清單的時間 | 低價值 |

### 劃線（`Bookmark`）

| 發現 | 數據 | 意義 |
|---|---|---|
| `Type` 分布 | highlight 3,080／markup 121／dogear 25；**沒有 `note`** | 同步的 `Type='highlight'` 過濾沒有漏掉任何打字註記 |
| `Annotation`（打字註記） | **0/3,080** | 使用者不在 Kobo 打字註記 → 影響 M2 心得段（見 M2 的 ⚠️） |
| **`markup`（手寫筆記）** | **121 筆，26 本書**（例：《從Q到Q+》18、《最有生產力的一年》18、《麥肯錫寫作技術與邏輯思考》14）；全部有位置（`StartContainerPath`）與時間 | 使用者真正的筆記。SQLite 只有位置，**圖檔在裝置上**（Kobo 慣例為 `.kobo/markups/`，未驗證——需接上 Kobo）；`checkUSBandUpload.py` 目前只複製 SQLite。候選：M2 心得段、劃線頁 |
| `DateCreated`／`DateModified` | 3,080/3,080 | 每筆劃線的時間戳 → 可做閱讀時間軸（`docs/KNOWLEDGE_SYSTEM_GAPS.md` B4） |
| `Color` | 18/3,080 非預設（17 筆 `2`、1 筆 `1`） | 幾乎沒用，低價值 |

### 其他資料表

| 資料表 | 列數 | 內容 | 評估 |
|---|---|---|---|
| `Shelf`／`ShelfContent` | 4／3 | 使用者書架：Creativity、Psychology、Software Engineer、主人的小說 | 幾乎沒在用 |
| `Wishlist` | 9 | 只有 `CrossRevisionId`＋時間，書名需另外對照 | 候選：自動在 Reading List 建「Ready to Start」頁 |
| `Reviews` | 2 | **其他讀者**的商店書評（署名非使用者） | 更正 CLAUDE.md「Reviews 個人書評」的描述 |
| `Event` | 336 | 每本書的閱讀事件計數（`EventType` 為未文件化的數字代碼，例：46 累計 13,224 次）；`ExtraData` 含非 UTF-8 位元組，讀取需 `text_factory = bytes` | 候選：閱讀行為分析，需先研究代碼意義 |
| `Activity` | 277 | 首頁動態（RecentBook 252 等） | 低價值 |
| `Achievement` | 27 | 2011 年的 Kobo 徽章 | 雜訊 |
| `KoboPlusAssets`、`volume_shortcovers`、`content_settings` | 294／3,264／10 | 訂閱資產、章節檔對照、閱讀設定 | 內部資料，低價值 |
