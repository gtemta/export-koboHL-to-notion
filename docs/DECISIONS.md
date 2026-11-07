# Decisions（輕量 ADR）

一行式架構決策紀錄：日期／決定了什麼／為什麼。新決策往上加。

## 2026-09-29 — Reading List 書頁版面由程式自建＋Views API，不套 Notion 模板

使用者的「心得摘錄」模板裡，卡片盒 view 是**沒有篩選**的 table（手動頁的「來源＝本頁」篩選是
事後手加的），直接套模板每頁都會看到整個卡片盒；以 API 套模板又是非同步、需要兩個新 API。
改由程式一次寫六段版面，再用 Views API（`create_database` + `after_block`）在「筆記圖」後建本書
卡片 gallery。代價：沒有模板裡的按鈕，改模板不會連動到自動頁。新版 API（`2026-03-11`）只用在
`notion_views_client.py`，因為 notion-client 2.2.1 會靜默丟掉不認得的參數。

## 2026-09-29 — 書封改 Kobo 圖床優先，每張圖先下載驗證

劃線頁 20/26 的封面是 Open Library 回的 1×1 透明圖：不帶 key 的 Google Books 與全球共用每日配額
（實測 429），失敗後退回的 Open Library 網址又沒驗證。`content.ImageId` 組成的 Kobo 圖床網址在
35/35 本書命中且版本正確，改為首選；Google Books 與 Open Library 只給沒有 ImageId 的書。所有候選
都下載驗證；舊 Open Library 封面重驗不過就替換，找不到替代就清除。

## 2026-09-28 — Reading List AI 剖析：讀完才寫、與心得分開、每本最多一次（M2）

AI 剖析寫在「概要」並以 🤖 標註，「心得」只放使用者自己的文字——手動頁的心得是個人經驗，模型寫
不出來。閱讀中不寫：卡片不齊、剖析又不覆蓋，會永遠停在半本的理解。已寫入的剖析不自動重寫。
心得段的來源（打字註記 0 筆、手寫 markup 121 筆）待 M2 計畫前重議。

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
