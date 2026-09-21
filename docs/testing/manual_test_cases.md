# Manual Test Cases

## Clarify Flow

### Case 1
User: 帳單
Expected: 反問查詢帳單金額、補寄帳單、繳費方式

User: 金額
Expected: 進 search_bill，詢問戶名與電話

User: 網路
Expected: 中斷 search_bill pending，改問網路方案、網路故障、網速問題、網路復線

## RAG

User: 固定IP怎麼申請
Expected: 回固定 IP 知識庫答案

User: line_tv無法綁定電話
Expected: 回覆新用戶僅提供 LINE 帳號註冊，並在聊天回覆中顯示可點的 LINE TV 客服中心連結；側欄知識庫命中結果仍保留 `［LINE TV客服中心🔗］` 純文字標記

User: 公司網站
Expected: 只回公司網址、維修申告、裝機申告，不顯示 LINE TV 客服中心

User: 加值服務網址
Expected: 回 LINE TV 客服中心連結

## Unsupported Flow

User: 幫我申請固定IP
Expected: 不代辦、不收姓名電話地址

## TV Troubleshooting

User: 電視不能看
Expected: 問機上盒電源燈

User: 不知道
Expected: 不再繼續追問排錯步驟，直接回報修暫停訊息並附維修申告連結

## Network Troubleshooting

User: 網路不能用
Expected: 問所有設備或單一設備

## Repair Flow Disabled

User: 我要報修
Expected: 告知線上報修暫停，請改由真人客服協助，並附維修申告連結

## Human Handoff

Web User: 我不想跟 AI 講了，幫我轉真人客服
Expected: 回覆含 `此項需由真人文字客服協助處理` 與 `轉真人文字客服` 連結，response `actions` 包含 `{"type":"human_handoff","reason":"user_requested"}`

Web User: 有沒有真人 我想要隱藏優惠
Expected: 回覆 `請問您目前遇到什麼問題？我會先協助您處理；若確認無法在線上協助，再幫您轉接真人客服。`，response `actions` 為空

Web User: 好
Expected: 回覆含 `此項需由真人文字客服協助處理` 與 `轉真人文字客服` 連結，response `actions` 包含 `{"type":"human_handoff","reason":"user_requested"}`

LINE User: 我想請真人客服處理
Expected: 啟動 LINE 真人客服模式，回覆 `已轉換為真人客服模式。`，並推送最近對話到真人客服群組；不得說「請稍後」或承諾等待時間

User: 客服電話是多少
Expected: 回覆公司客服電話，不應觸發 `human_handoff`

## Company Profile Admin

Action: 在 Web UI「公司資訊維護」編輯公司網址與加值服務網址後儲存
Expected: 儲存成功，後續公司網址查詢使用新公司網址，加值服務網址查詢使用新加值服務網址
