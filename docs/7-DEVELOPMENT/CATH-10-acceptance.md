# CATH-10 工程驗證報告

規格：v1.4。實作分支：`feat/repo-kb-native`，基底 `a2f3c58`。
本報告記錄工程驗證，不代替使用者的流程判讀與正式驗收。
截圖與完整 JSON 輸出另放在 issue 附件的證據包；未將公司來源內容加入程式庫。

2026-11-27 使用者已確認 D1 採方案 (b)：以「資料庫零筆存取紀錄＋保護排除規則測試」
作為通過依據，不要求 sudo 追蹤。未提供作業系統層的檔案存取追蹤仍列為已知限制，
此決定不表示已取得 OS 層證據。

## 可試用的環境

- 網址：`http://localhost:41000/repo-kb`。
- 啟動：Multica 環境側欄的 `repo-kb`，或 `"$MULTICA_CLI_PATH" env start repo-kb`。
- 停止：`"$MULTICA_CLI_PATH" env stop repo-kb`。環境由 daemon 監督，24 小時後自動停止，可重新啟動。
- 此預覽有獨立資料庫與聊天檢查點；既有 CaBook 環境沒有搬資料。
- 真實 `av_src` 首次同步前已手動加入 `usr`，全程保持啟用。

## 逐項結果

| 項目 | 已驗證結果 | 證據與仍待確認事項 |
| --- | --- | --- |
| A1 | 由 UI 建立 AV 知識庫與兩個資料源，預設保護清單為空；`av_src` 首次同步確認框列出手動新增的 `usr` | `av-doc-preview.png`、`av-src-usr-before-import.png`、`av-src-first-sync-usr-confirmed.png` |
| A2 | 由 UI 完成兩個真實資料源完整重新匯入與自動建置；987 + 3,761 = 4,748 檔，809 個確定性頁面 | `a2-clean-full-confirmation.png`、`clean-full-import.json`；含轉檔、建頁與索引共 624.98 秒。尚無同機同條件的 PoC 匯入時間，不能判定 ≤1.5 倍目標 |
| A3 | 合成副本新增 commit 後，UI 同步顯示 +1／~1／−1、重用 1；引用跟隨檔案修改 commit | `a3-incremental-result.png`；模組規則過期與舊版還原仍標過期，另有 Git + 真實 DB schema 整合測試 |
| A4 | A1、A2 重跑與 A3 的操作皆經網頁；建立及修改合成副本屬準備步驟 | 逐步截圖。早期轉檔 NUL 錯誤曾在開發資料庫修復；修正後已另從 UI 完整重匯，不把手動修復算成 UI 匯入通過 |
| A5 | 合成 repo 測過 glob、字面 `usr` 的停用／啟用、二次確認、稽核與指定資料源套用預設 | `a5-literal-usr.json`、`a5-glob-verification.json`、`a5-defaults-scoping.json`；缺確認回 409，重新啟用立即刪除 1 檔及衍生版本。合成 repo 的歷史存取數保留 1，驗證報告正確顯示需檢查；真實 `usr` 從未停用 |
| A6 | 專屬 KB 對另一筆記本不可見、掛載回 404；改全域後可掛載。真實兩來源多選同步完成；批次成功 1、取消尚未開始 2 | `acceptance-probes.json`、`flow-batch.json`。全域互斥、單項失敗不阻擋後項與取消另有整合測試。未把 API 範圍測試宣稱為 GUI 全流程測試 |
| B1 | 系統、模組、表、規則、SOP 可瀏覽；內部連結留在 SPA，頁首呈現建置 commit | `b1-layered-navigation.png` |
| B2 | 引文對到遮蔽原文、行號、commit，命中行高亮 | `b2-table-citation.png`；過期依原始 blob 判斷，重匯相同內容不會誤判過期 |
| B3 | 中文片語、表名、實際錯誤碼皆命中 | `b3-chinese-keyword-search.png`；「執行紀錄位置」0.630 秒、`DTAV0011_AA` 0.710 秒、`SQLCODE=-803` 0.578 秒，為單次量測，非延遲保證 |
| B4 | 不一致項目標記「已確認」及備註後，完整重匯／重建仍保留 | `b4-confirmed-after-rebuild.png`、`acceptance-probes.json` |
| C1 | Codex 透過正常對話 API 回答十題，每題皆有 ≥1 引文，49／49 有效 | 十張 `c1-qNN.png`、`chat-benchmark.json`；Q10 修正檔案歷史後重測 2／2 有效，另附 `chat-q10-metadata.json`。答案業務完整性仍需人工判讀 |
| C2 流程 | 編譯三個新契約相關流程，232／232 引文可回查，均有未知／待確認說明 | `flow-review.md`、`acceptance-probes.json`。步驟、方向與分支**待使用者對照圖檔確認**；不能以引文有效率取代語意正確性 |
| C2 選頁 | 十題 × 兩輪 × 兩種 CLI，工程標註的必要頁總召回 100%，純 BM25 為 63.64% | `retrieval-benchmark.json`；標註尚未由使用者確認，且首次量測時流程頁尚未建成，因此這是工程基準，**不是正式 C2 過關聲明** |
| C2 問答回寫 | 從網頁把 Q10 回答存成 QA，改問「移往冷儲存日期的畫面調整」，模型選到該 QA 頁 | `c2-save-qa-confirmation.png`、`c2-qa-paraphrase.json`；選中 `qa/9a8267c92b3eaaa04098`，過程經正常對話 API |
| C3 | A0 規則兩次真實編譯後，從 UI 比較並回復 v1，產生 v3；本文、來源 commit 與模型資訊均與 v1 相符。人工補充重建保留、ZIP、Git commit、來源路徑匯出 422 也已驗證 | `c3-rule-version-comparison.png`、`c3-final.json`、`c3-manual-note.png`、`c3-git-export.png`、`trial-wiki.zip`；合成 `usr` 清除會連同依賴該來源的人工補充清除，這是保護清除，不是重建覆寫，之後重新加的補充經重建仍保留 |
| D1 | **依使用者確認的方案 (b) 通過**：真實 `usr` 的 file、chunk、歷史存取、wiki 引用、AI 引用均 0，保護排除規則自測通過 | `d1-protection-report.png`、`acceptance-probes.json`；未提供作業系統層的檔案存取追蹤，列為已知限制，不再作為本次驗收阻礙 |
| D2 | 後端 1,329 tests；前端 45 files／511 tests 通過；Ruff、mypy（258 files）、TypeScript、ESLint 檢查結果附包 | 前端測試用 `--maxWorkers=2`；ESLint 0 errors／51 既有 warnings。新增回歸包含 fencing、中斷恢復、保護清除、scope、mask、增量 commit、嚴格引用、搜尋、422 匯出與 409 併發；載入歷史對話也重新檢查目前引用權限 |
| D3 | 本報告、截圖、完整逐題資料與 PR 草稿以繁體中文交付 | 來源內容只在經授權的資料庫與 issue 證據附件，未提交到程式庫 |

## 搜尋備案與量測

SurrealDB 原生全文索引沒有通過 Day 1 測試，因此採規格預留備案：
`repo_search_generation` 管原子發佈，`repo_search_document` 對照區塊，
`repo_search_posting` 存壓縮的 CJK bigram 倒排資料。搜尋先找候選、驗證目前保護規則，再讀遮蔽內容，以 BM25 排序；沒有向量或嵌入模型。

原始 31,583 區塊基準：載入 9.27 秒、索引 58.84 秒、資料庫峰值 507.5 MiB，
方法與取樣限制見 `decisions/ADR-016-repo-kb-native-search.md`。
完整預覽建置另外包含 wiki 段落，所以索引文件數約 33.9k，不能與純原文索引時間直接相比。
重匯後的歷史快照會增加儲存量；目前不自動刪除歷史快照。
多次真實匯入、編譯與重建後另取一次資料庫 RSS 為 1,255,680 KiB（約 1.20 GiB），
見 `db-memory-sample.json`；這是當下值而非峰值，不能以初次索引的約 0.5 GB 代表長時間使用量。

已用 `EXPLAIN` 確認大量授權檔案讀取改走 `repo_chunk_file` 索引；
原本 `$files CONTAINS file` 會掃過歷史區塊。這項改善是在上述 624.98 秒的完整重匯量測後加入，未冒用舊數字宣稱改善幅度。

| 選頁模型 | 選頁 p50／p95 | 整段檢索 p50／p95 | 備援 |
| --- | --- | --- | --- |
| Claude Code default | 5.189／7.611 秒 | 7.092／10.874 秒 | 11／20（55%），多為 JSON 格式錯誤 |
| Codex CLI default | 8.035／11.887 秒 | 10.362／14.973 秒 | 0／20 |

每次呼叫均記錄首 token、完成時間、實際／估算 token（供應者未回傳的值保留空值），
明細見 JSON。不能把 CLI 選頁 5–12 秒當成整題回答時間。
另用 Claude Code sonnet 做正常回答測試：40.998 秒，9／10 引文有效（90%）；
無效引文不允許存成 QA，畫面顯示無法回查。

## 十題逐題結果

本表是同一輪 Codex 正常對話。完整 token 分段與首 token 時間另見
`chat-timing-tokens.json`。舊檢索稽核尚未帶 session ID，因此以每題依序執行的時間區間，
配對唯一一筆檢索及回答稽核；已檢查每個區間只有一筆，這是時間關聯，非原生 run ID 關聯。
新稽核已補上 session ID 與模型 ID。

| 題號 | 整題秒數 | 檢索秒數 | 回答秒數 | 回答實際輸入／輸出 token | 引文有效率 |
| --- | --- | --- | --- | --- | --- |
| Q1 | 49.120 | 17.274 | 30.779 | 43119 / 1261 | 6/6（100%） |
| Q2 | 45.338 | 9.205 | 35.733 | 28058 / 1973 | 3/3（100%） |
| Q3 | 54.585 | 13.979 | 39.954 | 43135 / 2088 | 10/10（100%） |
| Q4 | 37.926 | 9.533 | 27.993 | 43114 / 1204 | 2/2（100%） |
| Q5 | 28.930 | 10.744 | 17.869 | 35567 / 737 | 1/1（100%） |
| Q6 | 35.839 | 11.701 | 23.462 | 43101 / 1021 | 5/5（100%） |
| Q7 | 35.813 | 8.980 | 26.332 | 43196 / 1307 | 5/5（100%） |
| Q8 | 43.068 | 8.478 | 33.452 | 43164 / 1808 | 11/11（100%） |
| Q9 | 38.942 | 15.036 | 22.488 | 43128 / 753 | 4/4（100%） |
| Q10 | 35.353 | 14.089 | 20.649 | 43108 / 657 | 2/2（100%） |

24k 是估算的檢索上下文預算，並非供應者的輸入硬上限；實際 token 與模型、完整 prompt 有關。
本輪首次作答在新增三個流程頁之前，後續另驗證流程頁與 QA 回寫。Q10 檔案日期修正後重問，
為 29.459 秒、2／2 引文有效，結果不混入原始十題分母。

## 與 CATH-9 數字差異

- 目前檔案數 4,748；已比對 PoC SQLite 的檔名清單，同為 4,748，沒有新增／漏掉的路徑。規格中的約 4,749 是概數。
- 實體資料表頁 771；連同 `tables/index` 共 772 個 Markdown 頁。不能把索引頁再算成一張表。
- 確定性 wiki 809 頁；手動編譯的 rule／flow 與 QA 另計。
- 轉檔原文中的 NUL 字元改為 replacement character，行數不變，避免 SurrealDB CBOR 拒絕資料；沒有搬入舊 mirror 或 SQLite 內容。

## 已知限制與交付缺口

1. `.vsd` 無內容轉換；`.vsdx` 只有形狀文字，無連線方向。三個流程的業務審核及必要頁標註仍需人完成。
2. 目前只有本機 macOS 真實資料驗證；Linux／Docker 的 Word 轉換需額外 converter。
3. Claude CLI 的嚴格選頁輸出不穩定，會走備援；未改用自由文字猜頁，也未因出現表名就跳過選頁。
4. 未被 wiki 涵蓋且缺少關鍵字的長尾問題仍可能找不到。引文可回查不保證回答解讀正確。
5. Git 匯出只新增指定分支 commit、不 push、不修改工作目錄。保護清除不會重寫既有 Git 匯出歷史。
6. 未提供作業系統層的檔案存取追蹤。使用者已明確接受方案 (b)，D1 依資料庫零筆紀錄與保護排除規則測試通過；不能將此結果解讀為 OS 層存取證明。
7. 使用者已提供 fork `waitingwu/open-notebook`，交付分支為 `feat/repo-kb-native`，PR 以 fork 的 `main` 為目標。`origin` 保留為原作者 repo；推送僅使用新增的 `fork` remote。原始驗證版本為 `ae7d563`，本次只追加驗收決策文件更新；PR 連結回填於 issue。
