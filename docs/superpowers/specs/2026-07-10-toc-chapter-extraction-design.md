# TOC 精確章節抽取 + 既有書頁重建（設計文件）

日期：2026-07-10 ／ 狀態：已實作並驗證

## 問題

章節抽取原本靠三層猜測（劃線文字 regex 猜標題 → ContentID 路徑 → 進度分群發明「第N章」），
結果常錯。調查 `KoboReader.sqlite` 後發現資料庫內含每本書的完整真實目錄，抽取可改為確定性查表。

## 資料庫事實（實測 25 本有劃線的書、2181 筆劃線）

- `content.ContentType=899` = TOC 條目：真實章節標題（Title）、目錄順序（VolumeIndex）、
  層級（Depth 1–4）。ContentID 格式 `{file}-{depth}` 或 `{file}#{anchor}-{depth}`。
- `content.ContentType=9` = spine：epub 檔案閱讀順序（VolumeIndex）。
- Bookmark.ContentID 的檔案部分（最後一個 `!` 之後）可對應 spine。
- 63% 劃線檔案直接命中 TOC；其餘為「一章跨多 xhtml 檔」，用 spine 區間法
  （往前最近的 TOC 條目）全數解決。25 本書 TOC↔spine 對應 100% 完整。

## 設計決策

1. **`TocChapterResolver`**（`src/infrastructure/persistence/toc_chapter_resolver.py`）：
   純邏輯、per-book。章 = 最後一個 Depth=1 且 spine_pos ≤ 劃線位置的條目；
   小節 = 回溯最近的 Depth≥2 條目。標籤呈現「章 › 小節」。
2. **同檔 anchor 的模糊性**：anchor 條目只有在同檔還有其他 TOC 條目時才視為模糊
   （檔案唯一條目的 anchor 是出版社把章標題 anchor 放檔首的常見模式，視同檔首）。
   遇模糊 anchor 時記錄其深度，只接受「嚴格更淺」的較早候選（其範圍確定包含劃線），
   否則退回章級。實證：《主控力》三層結構全解析；《鬆綁你的完美主義》同檔多 anchor
   正確退回章級。
3. **排序改為 (spine_pos, ChapterProgress)**：修掉舊「全書用 ChapterProgress 排序導致
   章節交錯」的隱性 bug（ChapterProgress 是檔內進度，非全書單調）。
4. **Fallback 保留**：整本書無 TOC 資料（sideload 等）→ 原 `organize_by_progress`
   pipeline 不變；`chapter_title_heuristics` 降級為個別劃線的 fallback。
5. **Resync 機制**（`RESYNC_HIGHLIGHTS` env：空｜`all`｜書名子字串清單）：
   符合的已匯出書呼叫 `replace_book_highlights`——只刪同步產生的 block 類型
   （heading_1/bulleted_list_item/callout/divider），使用者手動內容保留，再重新上傳。
   頁面 id 不變，卡片盒 `來源` relation 與 BookmarkID dedup 不受影響。

## 驗證結果（2026-07-10）

- 134 unit/integration 測試全綠、ruff 乾淨。
- `DRY_RUN=true RESYNC_HIGHLIGHTS=物哀`：log 顯示重建計畫（53 劃線／14 章節）。
- 真實跑 `RESYNC_HIGHLIGHTS=物哀`：刪除 152 個舊 block，Notion 頁面章節 heading
  與書內目錄逐字一致（此書舊法 0/47 命中，為最強對照組）。exit code 0。
- 順手修掉 `SyncResult.failed_syncs` 在 `__post_init__` 定格導致成功執行也 exit 1 的既有 bug。

## 明確不做（登記於 CLAUDE.md Known Cleanup Debt）

- 資料純度：`Bookmark.Type` 過濾（23 筆 dogear＋107 筆 markup 混入為空白劃線）、`Hidden` 過濾。
- 劃線 DateCreated／Color 匯出；content.Series/Language、Shelf 收藏、Reviews 個人書評匯出。
- Event/Activity/AnalyticsEvents 閱讀行為挖掘。
