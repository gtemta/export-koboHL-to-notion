# Decisions（輕量 ADR）

一行式架構決策紀錄：日期／決定了什麼／為什麼。新決策往上加。

## 2026-07-10 — 書不在 Reading List 時自動建頁

卡片盒 `來源` relation 指向 📚 Personal Reading List，但 Kobo 同步的書大多不在
書單裡（實查 60 頁只涵蓋手動加入的書），導致 137 張卡無來源。決定：同步／回填
時自動在 Reading List 建頁（Name=完整書名、`Kobo EReader` relation 指回劃線頁、
Status 依 Kobo 進度 ≥99% → 🔖閱讀完畢，否則 📖 閱讀中）。替代方案「改指向 Kobo
DB」被否決——會失去 Reading List（Blog/Status/推薦分數）這個 canonical hub。

## 2026-07-10 — 分類呼叫 Ollama 帶 `think: false`

gemma4:e4b 是 thinking model：大 prompt 時隱藏推理吃光 `num_predict`（
done_reason=length、response 空字串、log 顯示 0/16）。分類是短結構化任務，
不需要推理——`classify_cards` 帶 `think: false`（16 卡 14 秒完成），遇 400
（舊版 Ollama／不支援的模型）自動去掉參數重試。in-stream error 與空輸出
now 都有 log。

## 2026-07-10 — Tags 分類比對 emoji-insensitive

分類選項帶 emoji 前綴（💞心理學），本地 LLM 實測輸出純文字名（`心理學、人生觀點`），
舊的完全比對造成全部 0/16 落空。決定：prompt 給純文字分類名、parser 以 text core
（只留字母/數字）比回 canonical 名稱寫入 Notion。改分類清單時 text core 不可重複。
