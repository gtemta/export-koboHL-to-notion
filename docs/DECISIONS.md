# Decisions（輕量 ADR）

一行式架構決策紀錄：日期／決定了什麼／為什麼。新決策往上加。

## 2026-08-05 — 卡片視覺用「分類色卡 + emoji icon」，不接外部圖庫

卡片 cover 用 Notion 內建漸層（依 Tags 分類）、icon 用固定 emoji 調色盤，不接
Unsplash 等外部圖庫。外部圖庫要新 API key、抽象概念幾乎抓不到相關圖，且圖床失效
會讓整面卡片牆破圖；Notion 內建 cover 是自家 CDN、純 URL、零依賴。代價是同分類的
卡同色——真正扛「同書可辨」的責任因此被推給 icon。

## 2026-08-05 — icon 走固定調色盤，不讓模型自由生成 emoji

`_ICON_PALETTE` 收 40 個單 codepoint emoji，prompt 只讓模型「從清單挑」，parser
也只接受清單內的值。自由生成會冒出多碼點 ZWJ 序列與 variation selector，那是
Notion icon 最常見的拒收原因——一個壞 emoji 會讓整張卡 `pages.create` 失敗。
「從清單挑」把驗證問題變成集合查表，順帶讓「調色盤 ∩ 分類 emoji = ∅」這條不變
條件撐起 parser 的容錯規則。

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
