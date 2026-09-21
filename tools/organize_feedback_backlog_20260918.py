"""Consolidate the 2026-09-18 organizing backlog into professional cases.

This tool never changes a feedback item's review stage. It creates one
traceable regression definition per necessary intent and links each source
feedback item to exactly one definition. Use --apply only after --check.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from typing import Any

from app.services.feedback_tracker_service import (
    init_tracker_schema,
    list_feedback_items,
    now_iso,
    tracker_db_conn,
)


SNAPSHOT_COUNT = 164
SNAPSHOT_SHA256 = "725dedbe1932efaa2718a2388568a74efaf533a41ac1aac01445277b96a863d5"
EXPECTED_CASE_COUNT = 55
CASE_PREFIX = "ORG-202609-"
ACTOR = "codex:organize-feedback-20260918"
EXCLUDED = {
    81: "原回饋明確標示為測試內容並要求忽略，不納入回歸案例。",
}


def case(
    number: int,
    source_numbers: list[int],
    suite: str,
    group_name: str,
    case_kind: str,
    script: str,
    expected_behavior: str,
    must_include: str,
    must_not_include: str,
    dependency: str,
    focus: str,
    priority: str = "P1",
) -> dict[str, Any]:
    return {
        "case_id": f"{CASE_PREFIX}{number:03d}",
        "source_numbers": source_numbers,
        "suite": suite,
        "priority": priority,
        "group_name": group_name,
        "case_kind": case_kind,
        "script": script,
        "expected_behavior": expected_behavior,
        "must_include": must_include,
        "must_not_include": must_not_include,
        "dependency": dependency,
        "focus": focus,
    }


GROUPS = [
    case(1, [1, 62], "合約與服務異動", "換約或轉換方案", "多輪意圖釐清",
         "U1：原合約已到期，想換方案怎麼辦？\nU2：我想改成純網路。",
         "先確認客戶想變更的服務類型與目標；未明確前不推定特定方案。已在合約期內者，說明轉換資格、合約與費用需依現有合約及目標方案確認。",
         "服務類型或目標方案；現有合約影響", "未確認需求就列特定方案；承諾可直接轉換", "8123 + OpenAI；個人合約查詢需受信任登入資料", "把「想換方案」先收斂成可回答的服務範圍。"),
    case(2, [2, 101, 103], "繳費與帳務", "自動扣款定義與申請", "單輪知識問答",
         "U：綁定循環扣款是什麼意思？",
         "先說明自動扣款是帳單產生後，從指定信用卡或銀行帳戶自動繳費；再依現行官方流程說明設定方式。",
         "自動繳費定義；信用卡或銀行帳戶；官方設定流程", "誤當成查詢是否已綁定；自行虛構優惠", "8123 + OpenAI + 現行繳費知識", "區分「這是什麼」與「我有沒有設定」。"),
    case(3, [3, 8, 17], "合約與服務異動", "寬頻網路退租", "多輪服務主體保留",
         "U1：我要退網路。\nU2：要帶哪些設備或文件？",
         "全程保留寬頻退租主體，說明合約狀態、可能費用與數據機及實際租借配件歸還；不主動導向電話或混入有線電視設備。",
         "寬頻合約；數據機；實際租借配件", "機上盒、遙控器、HDMI 線；主動提供客服電話", "8123 + OpenAI", "後續短問句不得遺失「只退網路」。"),
    case(4, [4], "故障排除", "機上盒無電源燈", "多輪已知條件承接",
         "U1：都有插電，但沒有亮燈。\nA：哪一台設備？\nU2：機上盒。",
         "記住已確認「有插電且無亮燈」，補充設備類型後直接進入下一個安全排除步驟，不重複問燈號。",
         "電源線與插座檢查；下一步排除", "再問是否有亮燈；忽略首輪資訊", "8123 + OpenAI", "對話槽位一旦已知即不重複提問。"),
    case(5, [5, 72, 143], "人工協助與安全", "需查個人紀錄的聯繫追蹤", "單輪導向人工",
         "U：專案點數沒入帳／剛剛有人打給我／裝機報價還沒聯繫。",
         "先說明可確認的一般原則，再指出該需求必須查閱個人專案、外撥或受理紀錄，並提供站內真人文字客服轉接；不公開收集個資或只給電話。",
         "需查閱個人紀錄；轉真人文字客服", "猜測聯繫原因；客服電話；要求客戶在對話輸入敏感資料", "8123 + OpenAI + 站內轉接", "同類「只能查個案記錄」需求統一使用安全轉接。", "P0"),
    case(6, [6, 106, 140], "繳費與帳務", "繳費方式與線上繳費", "單輪範圍判斷",
         "U1：有哪些繳費方式？\n變體：我想用 APP 線上繳費／改成半年繳。",
         "廣泛詢問列完整現行繳費管道；指定線上或 APP 時只回對應流程。同時要求變更繳別時，分開說明線上繳費與繳別變更的處理邊界。",
         "官網與 APP 流程；廣泛問題的完整管道", "廣泛問題只給 ibon；APP 問題改答點數或優惠", "8123 + OpenAI + 繳費知識", "回答範圍必須與客戶指定的繳費管道一致。"),
    case(7, [7, 44, 59, 89, 91, 137, 138], "機上盒與加值服務", "聯網機上盒、YouTube 與 LINE TV", "意圖矩陣",
         "U：機上盒可以看 YouTube 嗎？\n變體：如何訂購／開通／取消 LINE TV？如何加購數位電視套餐？",
         "先辨識客戶問的產品與動作。YouTube 說明聯網型機上盒條件；LINE TV 區分訂購、電視登入與取消；數位套餐依聯網型與非聯網型機上盒提供對應流程。費用依現行知識。",
         "產品名稱；使用條件；對應操作流程", "把 YouTube 當成不存在的加值服務；用費率取代操作步驟；混入無關方案", "8123 + OpenAI + 現行加值服務知識", "同屬機上盒加值服務，但必須依產品與動作分流。"),
    case(8, [9, 10], "發票與載具", "發票中獎通知與領取", "單輪異義消除",
         "U：發票中獎會主動通知嗎？",
         "把「發票中獎」與「優惠活動抽獎」完全分開；依正式知識說明簡訊通知、領取期限、應備資料與逾期寄送處理。",
         "發票中獎；簡訊通知；領取期限", "優惠方案名稱；抽獎獎項；活動資格", "8123 + OpenAI + 發票知識", "防止「中獎」共現詞導致誤檢促銷文件。"),
    case(9, [11, 23], "帳戶資料與安全", "基本資料異動與更名", "多輪資料類型釐清",
         "U1：我要修改基本資料。\nU2：要變更戶名，週末可以辦嗎？\nU3：電視的，要帶哪些證件？",
         "第一輪先確認要修改的資料類型。電話等個資異動使用安全轉接；更名則保留服務主體，回答營業時間後接續確認實際應備文件，不回到泛用選單。",
         "資料類型；服務主體；更名應備文件或查核邊界", "未釐清就直接轉電話；重新詢問有線電視要查什麼", "8123 + OpenAI + 營業資訊；個資異動需安全轉接", "資料修改必須先分類，並在多輪對話保留更名主題。", "P0"),
    case(10, [12, 94], "合約與服務異動", "移機流程、費用與收費", "多輪知識問答",
         "U1：我要移機。\nU2：請說明流程、可能費用與如何付費。",
         "先回答移機本身的申請流程、新址線路確認、室內／室外與各服務費用，再依正式資料說明收費時點與方式。不提供客服電話或無關優惠。",
         "移機流程；新址線路；室內／室外費用；收費時點", "公司地址；其他方案；客服電話；僅說無法代辦", "8123 + OpenAI + 現行移機知識", "每一輪移機追問都保留完整金額與服務主體。"),
    case(11, [13, 14, 15, 43, 76, 112, 147], "繳費與帳務", "已繳費但服務未恢復", "多輪入帳與復線",
         "U1：忘記繳費被斷訊。\nU2：我已用官網／信用卡繳完，什麼時候恢復？",
         "承接已繳費與繳費管道，說明入帳可能需作業時間，先引導設備關機重開並等待重新授權；需確認入帳時優先引導官網或 APP，不重新進入一般故障排除或繳費方式。",
         "已繳費；入帳作業時間；設備重啟；官網或 APP 查詢", "要求線上繳費客戶上傳超商收據；網速測試；主動提供電話", "8123 + OpenAI；個人入帳狀態需正式查詢", "繳費復線是帳務授權主題，不可被「斷訊」誤導為線路故障。"),
    case(12, [16], "繳費與帳務", "信用卡繳費無法送出", "單輪操作排除",
         "U：線上刷卡繳費無法送出。",
         "提供卡號、有效期限、安全碼、3D 驗證、重新整理與更換瀏覽器等安全排除；仍失敗時提供其他繳費管道與官網／APP 交易查詢。",
         "刷卡欄位檢查；3D 驗證；替代繳費管道；交易查詢", "收集完整卡號或驗證碼；只給客服電話", "8123 + OpenAI", "線上交易失敗先提供可執行排除與替代途徑。", "P0"),
    case(13, [18, 40, 47, 53, 64, 67, 85, 145, 146], "故障排除", "網路完全無法連線", "多輪排除",
         "U1：家裡沒網路／無法連網。\nU2：可以線上教我排除嗎？",
         "LLM 直接判斷為網路故障並進入簡短排除；保留已說明的「無法上網」與設備範圍，不重複問是否要回報故障或問題類型。",
         "數據機／分享器重啟；影響範圍；必要時維修", "泛用三選一；電視故障流程；未排除就轉真人", "8123 + OpenAI", "口語的「網路掛了」、「無訊號」均要正確進入網路排除。"),
    case(14, [19, 29, 33, 39, 111, 124, 125], "故障排除", "遙控器故障", "單輪／多輪症狀分流",
         "U：遙控器壞掉／數字鍵壞掉／無法開關機。",
         "未提供症狀時只詢問整支無反應或特定按鍵失效；已有症狀就直接檢查電池、正負極、遮擋與對準位置。確認無法排除後再說明維修／更換與現行費用。",
         "症狀分流；電池檢查；必要時更換", "資料／辦理／故障三選一；忽略已說明的按鍵症狀", "8123 + OpenAI + 現行設備費用知識", "將「壞掉」視為完整故障意圖，再依症狀深化。"),
    case(15, [20, 35, 49, 149], "繳費與帳務", "帳單金額、差異與部分繳費", "多輪帳務意圖",
         "U：我本期要繳多少／為什麼跟上期不同／可以只繳電視嗎？",
         "分辨本期待繳金額、已繳明細、跨期差異與多服務部分繳費。只在授權的帳務查詢中使用 API；無法查上期或拆分繳費時，明確說明限制並引導官網／APP 或安全轉接。",
         "帳務問題類型；可查範圍；官網或 APP", "把金額差異當成方案介紹；只重複當期金額；虛構可拆繳", "8123 + OpenAI + 帳務 API／登入權限", "同為金額問題，但要依客戶要查的期間與動作分流。", "P0"),
    case(16, [21, 71], "優惠方案與申裝", "原用戶升級下一階速率", "知識回答後合約提醒",
         "U：我是原用戶，想升級下一階速率，有哪些方案？",
         "先依目前可推廣知識列出相符的下一階方案與費用，再說明實際升級資格、合約與費用需依現有服務確認。",
         "目前可推廣方案；速率與費用；現有合約確認", "直接回答查無資料；不查合約就承諾可升級", "8123 + OpenAI + 當期方案索引", "先提供可參考方案，再交代個人合約邊界。"),
    case(17, [22, 26, 121, 122], "發票與載具", "電子帳單、發票與 APP 查詢", "意圖矩陣",
         "U：APP 繳費後會寄實體收據嗎？\n變體：舊發票在 APP 哪裡？如何把紙本帳單改電子？",
         "依客戶所問的單一目標回答。繳費後先說明是否寄實體收據，再給官網與 APP 發票查詢路徑；歷史資料引導歷史帳單；改電子帳單只提供正式可用管道。",
         "實體收據結論；發票查詢路徑；歷史帳單入口", "未回主問題就展開載具；要求客戶提供個資；回答無資料", "8123 + OpenAI + 發票／APP 知識", "收據、發票、帳單與載具必須區分。"),
    case(18, [24, 25, 46, 105, 148], "帳戶資料與安全", "官網與行動客服帳號密碼", "多輪系統範圍釐清",
         "U：我想線上繳費，但忘記帳號密碼。",
         "先釐清是官網或行動客服 APP，明確說明兩者登入資料不共用。官網用戶編號可從帳單查看；APP 使用雲帳號；密碼依對應忘記密碼流程重設。",
         "官網／APP 釐清；帳號來源；忘記密碼流程", "說兩者帳密共用；只提供電話；把密碼問題改答繳費方式", "8123 + OpenAI + 登入知識", "同一「忘記帳密」需先定位所屬系統。", "P0"),
    case(19, [27], "工程與預約", "已預約維修的到府時間", "單輪期待說明",
         "U：我已申報維修，工程人員什麼時候會來？",
         "說明完成預約後，工程人員通常依排程或預約時段聯繫；尚未超過時段先請客戶等候，逾時才轉人工確認。",
         "排程或預約時段；工程人員聯繫；逾時處理", "第一輪就轉真人；客服電話；承諾精確到府時間", "8123 + OpenAI", "對已完成預約的期待提供一致說明。"),
    case(20, [28, 34, 51, 54, 74, 120, 123, 133, 159, 160, 162, 163], "故障排除", "網速過慢、不穩或測速不達", "多輪數值與狀態承接",
         "U1：申請 300M，測速只有 30M。\nU2：已重啟且測試，還是 30M。\nU3：請安排維修。",
         "判斷為速度異常而非完全無法上網。保留申辦速率、實測值與已完成步驟，依序引導重啟、有線單機測速與線路確認；合理排除後仍不達再提供維修。",
         "申辦速率；實測值；有線單機測速；已完成步驟", "重複詢問已提供的數值；改問是否完全不能上網；在排除前轉人工", "8123 + OpenAI", "多輪排除必須將數值與已完成動作寫入狀態。"),
    case(21, [30], "網路設定", "固定 IP 申請與綁定", "單輪流程說明",
         "U：我要申請並綁定固定 IP。",
         "先說明固定 IP 數量需申請確認，再依官網現行介面說明登入、選擇設備、設定與重啟流程；數量與費用依當期正式資料。",
         "申請數量；官網綁定流程；設備重啟", "未申請就稱已綁定；寫死過期費率", "8123 + OpenAI + 現行固定 IP 知識", "申請資格與實際綁定是兩個階段。"),
    case(22, [31, 126, 127], "合約與服務異動", "提前終止與違約金", "單輪帳戶邊界",
         "U：我想提前終止合約，違約金多少？",
         "說明提前終止可能產生違約金，金額必須依客戶目前方案、合約與剩餘期間確認；不從任意優惠文件推定個人金額。",
         "合約狀態；剩餘期間；實際金額需查詢", "猜測固定違約金；改答合約到期日；誤用其他方案", "8123 + OpenAI + 受信任登入合約查詢", "合約事實不可由通用知識代入。", "P0"),
    case(23, [32, 45, 134], "網路設定", "更換分享器後無法上網", "多輪因果判斷",
         "U1：我換了新分享器就不能上網。\nU2：換回舊的就正常。",
         "優先判斷為新設備註冊或設定問題，而非通用線路故障。先說明自動註冊與重啟，未自動註冊時提供官網的電腦網卡更換註冊流程。",
         "新舊設備對照；自動註冊；官網更換註冊；重啟", "通用數據機排除取代註冊流程；直接判定線路故障", "8123 + OpenAI + 網卡更換註冊知識", "設備更換是重要因果資訊，不可忽略。"),
    case(24, [58, 80, 104], "優惠方案與申裝", "電視與網路同裝需求", "釐清／方案清單／欄位追問",
         "U：家裡要裝 100M／500M 網路加電視，月費多少？\n變體：這個價格有包含電視嗎？",
         "若「查目前帳戶」與「問新申裝」都有可能，先問一次釐清。確認為新申裝後，只用當期同裝活動列出目標速率與對應費用，平鋪回答費用是否包含電視與網路。",
         "查合約／新申裝釐清；目標速率；當期同裝方案；費用所含服務", "純網方案；只列單一非目標速率；未確認就查個人合約", "8123 + OpenAI + 當期同裝活動索引", "用服務類型與速率範圍驅動動態方案檢索。"),
    case(25, [36], "故障排除", "未指定電視或網路的訊號不穩", "單輪服務主體釐清",
         "U：訊號不穩。",
         "只釐清是電視畫面或寬頻網路不穩，取得答案後直接進入對應排除。",
         "電視或網路二選一", "資料／辦理／故障三選一；在未確認主體前猜測排除", "8123 + OpenAI", "只對真正欠缺的服務主體提問。"),
    case(26, [37, 38, 42, 158], "網路設定", "分享器連線類型、Wi-Fi 名稱與密碼", "知識問答矩陣",
         "U：ISP 連線類型是什麼？\n變體：如何改 Wi-Fi 名稱或密碼？",
         "連線類型問題回答 DHCP 自動取得 IP，不需 PPPoE 帳密。Wi-Fi 名稱或密碼則說明依分享器型號進入管理介面的一般流程，不虛構特定品牌介面。",
         "DHCP 自動取得 IP；分享器型號；管理介面；儲存後重新連線", "PPPoE 帳密；未知型號卻指定固定網址；要求客戶公開密碼", "8123 + OpenAI + 網路設定知識", "依客戶實際設定目標選擇最小必要步驟。", "P0"),
    case(27, [41, 78, 151], "帳戶資料與安全", "客戶編號與身分資料解析", "多輪查詢資格",
         "U：不知道客戶編號／這組客編不是這個地址／可以用地址查目前方案嗎？",
         "說明客戶編號可從帳單或登入帳戶取得；系統不以聊天中的地址查個人方案。帳單與復線工具只接受客編、戶名、登記電話任兩項；提供新有效值後必須更新狀態，不重複索取舊值。",
         "帳單查找客編；地址不可查個人方案；任兩項規則", "用地址返回個人方案；重複要求已更新的客編；公開顯示敏感資料", "8123 + OpenAI + 帳務工具權限", "解決「我是誰」與「可用哪些欄位查什麼」的邊界。", "P0"),
    case(28, [48, 79, 116, 119], "故障排除", "部分頻道消失或搜尋不到", "多輪畫面症狀承接",
         "U1：特定幾台不見了。\nU2：不是無訊號、黑畫面或錯誤碼。",
         "識別為部分頻道編排或搜頻問題，直接引導恢復預設或重新搜尋頻道；不重複詢問已被排除的畫面類型。",
         "恢復預設或重新搜頻；部分頻道上下文", "再問無訊號／黑畫面／錯誤碼；改答方案或頻道套餐", "8123 + OpenAI", "將「少幾台」與「全部無法收看」分流。"),
    case(29, [50, 63], "帳戶資料與安全", "個人合約到期與內容查詢", "權限驗證",
         "U：我的網路合約到什麼時候？",
         "僅在已登入 WEB 且後端帶入受信任客編時查詢個人合約。其他通道引導至官網或行動客服 APP 登入，不收集戶名、電話或聊天輸入的客編。",
         "個人資料安全；登入後查詢；官網或 APP", "要求聊天提供戶名、電話或客編；未授權查詢；問 A 答 B", "8123 + OpenAI + 受信任 WEB 登入情境", "合約查詢必須在路由、欄位與工具層同時守住權限。", "P0"),
    case(30, [52, 95, 96, 98, 99, 100, 102], "優惠方案與申裝", "具名方案的多輪追問", "多輪動態文件追蹤",
         "U1：請介紹目前方案。\nU2：選擇某方案後追問價格、贈品、循環扣款、活動期間或申請方式。",
         "系統必須記住本輪實際顯示與客戶選定的動態方案，每一輪只回答追問欄位，並依同一份現行文件保留金額、條件與期間。切換到另一方案時更新主題，不被前案污染。",
         "選定方案名稱；本輪追問欄位；同文件證據", "跳到其他方案；回答查無資料；重送整份方案；在提示詞寫死活動名稱", "8123 + OpenAI + 當期活動索引", "方案是動態實體，多輪記憶必須來自實際檢索結果。"),
    case(31, [55, 75, 107, 108, 113, 114], "故障排除", "機上盒異常畫面與卡住", "多輪畫面分流",
         "U：畫面卡在教學／開機中／沒有節目／顏色異常。",
         "承認客戶已描述的畫面，不把所有電視異常限制為無訊號、黑畫面或錯誤碼。依已知症狀引導遙控器確認、恢復預設、重新搜頻或機上盒重啟，無效再報修。",
         "已知畫面症狀；對應排除；無效後報修", "重複問三種畫面；虛構自動重開機症狀；畫面異常改查費用", "8123 + OpenAI", "排除引擎需容納開放式畫面描述。"),
    case(32, [57, 60, 83, 117], "優惠方案與申裝", "純有線電視費用與裝機", "單輪／多輪費率回答",
         "U1：只裝有線電視要多少錢？\nU2：一年與兩年總共多少？",
         "純有線電視只使用所屬系統台現行基本收視費與裝機費資料。首答不可只列裝機費；兩年追問依同一份資料使用「年繳收視費×2＋首次裝機費」列式。",
         "收視費；裝機費；繳別；多年費用列式", "網路方案；僅列裝機費；跨公司費率；未列式猜測", "8123 + OpenAI + 所屬系統台費率知識", "動態費率不寫死，但計算關係必須可驗證。"),
    case(33, [66, 69, 90, 139, 141], "對話狀態與語意", "主題切換、選項與上下文", "多輪中斷與選擇",
         "U1：進行機上盒排除。\nU2：改問 LINE TV／費用／客服電話，或回覆上輪選單編號。",
         "LLM 判斷最新訊息是舊流程補充、選單選擇或明確新主題。選單編號對回當輪實際顯示選項；新主題中斷舊流程並直接回答，不被早先故障狀態綁住。",
         "最新訊息意圖；當輪選單對應；必要時清除舊流程", "堅持重複舊排除問題；將編號一字誤當其他意圖；忽略明確新問題", "8123 + OpenAI", "對話記憶用來理解短回覆，不是強迫客戶留在舊流程。"),
    case(34, [61], "發票與載具", "發票歸戶到手機條碼", "釐清後操作流程",
         "U1：發票加入手機條碼。\nA：請問是想將發票歸戶到手機條碼載具嗎？\nU2：是。",
         "尚未明確操作意圖時只問一次確認；客戶確認後，依官網線上繳費、用戶歸戶、用戶歸戶2到財政部網站的順序引導。",
         "用戶歸戶；用戶歸戶2；財政部網站", "在聊天中索取手機條碼、手機號、驗證碼或證件；改答發票時程", "8123 + OpenAI + 發票歸戶知識", "設定流程要完整，且個資只在官方頁面輸入。", "P0"),
    case(35, [65], "故障排除", "電視或機上盒無聲音", "單輪故障分流",
         "U：哈 TV 沒有聲音。",
         "直接視為聲音故障，檢查電視與機上盒靜音、音量、音訊線路與重啟；必要時再報修。",
         "靜音；音量；線路；重啟", "泛用三選一；網路故障；未排除就轉人工", "8123 + OpenAI", "口語的「沒聲音」已是完整故障意圖。"),
    case(36, [68], "頻道與套餐", "基本頻道與數位套餐差異", "單輪比較",
         "U：基本頻道和數位頻道有什麼不同？",
         "說明基本頻道是申裝有線電視即可收看的基本服務；數位套餐是依需求另行付費加購的內容，詳細套餐與當期費用引導官網。",
         "基本服務；付費加購；官網詳情", "把數位頻道說成全部免費；貼出無關方案", "8123 + OpenAI + 頻道知識", "簡短解釋概念差異，不展開整份套餐文件。"),
    case(37, [70, 82, 84], "繳費與帳務", "簡訊帳單補發與 APP 超商條碼", "多輪帳單管道",
         "U：APP 沒有超商繳費條碼／我要補發簡訊帳單。",
         "先依目前繳費方式分流：可產生條碼的帳單從 APP 待繳帳單取得；簡訊帳單從手機簡訊開啟。補發只寄至帳務登記電話，不允許指定他號碼。",
         "繳費方式分流；APP 待繳帳單；登記電話", "承諾改寄其他電話；把簡訊帳單當紙本條碼；在公開對話揭露完整電話", "8123 + OpenAI + 帳單知識／身分核對", "條碼顯示方式取決於帳單類型。", "P0"),
    case(38, [73, 135, 156, 157], "合約與服務異動", "暫停服務或永久退租", "多輪語意釐清",
         "U：我要停機／不想看了／暫時中斷網路。",
         "只在「暫停」與「永久退租」之間釐清，然後依選擇先說明可辦期間、合約、費用與設備影響的處理原則。客戶確定要辦理後再安全轉接。",
         "暫停或退租釐清；合約與費用影響；辦理邊界", "當成網路故障；第一輪就給電話；未釐清就假定退租", "8123 + OpenAI", "口語「停機」的關鍵是服務持續性，不是設備狀態。"),
    case(39, [77], "繳費與帳務", "已退租帳號無法復線", "工具狀態判斷",
         "U：忘了繳費被斷訊，可以先恢復嗎？（查詢結果為已退租）",
         "工具回傳已退租／停用帳號時，不可回答服務正常或執行復線。明確說明無法直接恢復，需重新申請並確認實際資格。",
         "已退租狀態；不可復線；重新申請", "稱服務正常；呼叫復線工具；猜測已入帳", "8123 + OpenAI + 客資 API 狀態", "工具狀態優先於使用者對原因的推測。", "P0"),
    case(40, [86, 93], "優惠方案與申裝", "純網方案與指定速率", "動態方案清單",
         "U：可以只申請網路嗎？500M 或最低費用有哪些方案？",
         "只檢索當期可推廣的純網方案，依指定速率或最低費用範圍列出相符方案；不寫死活動名稱，不混入電視同裝與社福方案。",
         "純網服務；指定速率或最低費用；當期方案", "電視同裝；社福方案；提示詞寫死活動名；已下架方案", "8123 + OpenAI + 當期純網活動索引", "用動態知識回答現行方案，程式只保留服務範圍。"),
    case(41, [87], "網路知識", "寬頻是單戶獨立或區域共用", "單輪條件說明",
         "U：你們的網路是每戶獨立，還是整個區域共用？",
         "說明一般寬頻為每戶獨立申裝；學舍或房東統一申請等特定方案可能是共用配置，實際依申辦方案與現場架構確認。",
         "一般單戶獨立；特定共用方案；實際配置確認", "絕對保證不共用；把問題當成個人合約查詢", "8123 + OpenAI + 寬頻產品知識", "給明確預設結論，同時保留特定架構例外。"),
    case(42, [88], "繳費與帳務", "預繳費用", "帳務狀態分流",
         "U：我想預繳，怎麼辦？",
         "先確認是否已有待繳帳單。有待繳時回答當期金額與可用繳費方式；無待繳時明確回答目前無費用需繳，不虛構預存入帳。",
         "待繳帳單狀態；有帳單金額或無費用需繳", "未查詢就承諾預繳成功；虛構預存金額", "8123 + OpenAI + 帳務 API／授權欄位", "「預繳」必須依現有帳單狀態回答。"),
    case(43, [92], "優惠方案與申裝", "新申請寬頻或既有寬頻加裝 Wi-Fi", "單輪意圖釐清",
         "U：請問怎麼取得無線網路？",
         "只詢客戶是要新申請寬頻網路，還是已有寬頻要加裝 Wi-Fi 分享器；依回答進入對應方案或設備服務。",
         "新申請寬頻／已有寬頻加裝 Wi-Fi 二選一", "直接把無線網路當成 LINE TV、YouTube 或機上盒；未釐清就列方案", "8123 + OpenAI", "日常語言的「無線網路」可能是新申裝或屋內 Wi-Fi。"),
    case(44, [109, 128, 129], "故障排除", "基本頻道 E004／未授權／授權過期", "多輪授權與帳務分流",
         "U1：基本頻道顯示 E004 或授權過期。\nU2：我已繳費。",
         "先確認是一般基本頻道而非需加購的付費頻道。基本頻道顯示 E004／未授權時，依帳務與授權流程確認收視費；已繳費則引導重啟，未恢復再確認入帳與授權。",
         "基本頻道；E004／未授權；收視費；重啟", "反覆詢問是否一般頻道；把基本頻道誤當付費頻道；改答優惠方案", "8123 + OpenAI + 收視授權／帳務狀態", "錯誤碼排除需保留頻道類型與繳費狀態。"),
    case(45, [110], "帳戶資料與安全", "個人帳單寄送地址", "單輪個資邊界",
         "U：我現在帳單寄到哪個地址？",
         "明確說明線上 AI 不直接顯示個人帳單寄送地址，並使用安全的真人文字客服轉接確認。",
         "個人資料限制；轉真人文字客服", "回答公司地址；在對話內顯示個人寄送地址；只給電話", "8123 + OpenAI + 站內轉接", "「帳單地址」是個人資料，不是公司據點地址。", "P0"),
    case(46, [115], "設備操作", "手機投影到電視", "單輪一般性說明",
         "U：手機畫面要怎麼投影到電視？",
         "說明投影能力取決於手機、電視與中間設備是否支援，提供螢幕鏡像、投放或 AirPlay 等一般路徑，並請客戶依設備規格與說明書確認。",
         "設備相容性；螢幕鏡像／投放／AirPlay；原廠說明", "保證任何設備都可投影；改答有線電視套餐", "8123 + OpenAI", "一般設備知識不虛構特定型號步驟。"),
    case(47, [118], "服務邊界", "未提供虛擬主機服務", "單輪不支援回答",
         "U：請介紹虛擬主機服務。",
         "明確說明目前未提供虛擬主機服務，不進行 RAG 廣泛聯想、不推薦不相關產品，也不要求客戶重新描述。",
         "目前未提供此服務", "虛構產品內容；推薦無關方案；資料不足請重述", "8123 + OpenAI", "不支援服務要簡短、明確、不幻覺。"),
    case(48, [130], "故障排除", "數據機 DS 燈閃爍", "單輪燈號說明",
         "U：數據機 DS 燈一直閃是正常的嗎？",
         "先說明重啟後短暫閃爍通常代表正在同步下行訊號；若等待 3 至 5 分鐘後仍持續閃爍且無法上網，才視為未完成同步並需進一步確認。",
         "正在同步；3 至 5 分鐘；持續閃爍且無法上網", "直接判定正常；不說明燈號意義；直接報修", "8123 + OpenAI", "客戶問的是燈號意義，回答必須包含時間與連線條件。"),
    case(49, [136], "帳戶資料與安全", "雲端帳號登入行動客服 APP", "單輪操作說明",
         "U：系統已開通雲端帳號，要怎麼登入使用？",
         "引導下載行動客服 APP，使用雲端帳號與密碼登入，並簡短說明可使用線上報修、帳單、點數與繳費等功能。",
         "行動客服 APP；雲端帳號與密碼；可用功能", "LINE TV 登入或綁定；回答查無資料；轉人工", "8123 + OpenAI + APP 帳號知識", "「雲端帳號」是行動客服 APP 帳號，不是 LINE TV。"),
    case(50, [144], "工具與系統穩定性", "帳務工具傳送失敗", "錯誤處理",
         "U：未收到帳單，提供核對資料後系統回覆傳送失敗。",
         "保留工具錯誤原因與追蹤資訊，回覆應說明本次操作未完成，不得假裝成功或陷入無限重試；提供安全重試或人工協助路徑。",
         "本次操作未完成；可追蹤錯誤；重試或人工協助", "稱已補發成功；只回覆系統繁忙而無下一步；回顯敏感資料", "8123 + 帳務工具及錯誤日誌", "系統錯誤必須可觀測、不假成功、不重複扣款或送出。", "P0"),
    case(51, [152], "頻道與套餐", "基本頻道表", "單輪導航",
         "U：基本頻道可以看哪幾台？",
         "簡短說明基本頻道就是有線電視頻道，並依所屬系統台引導至官網最新頻道表；不貼出方案內容或過時頻道清單。",
         "有線電視頻道；所屬系統台官網頻道表", "優惠方案；回答查無資料；過時靜態頻道清單", "8123 + OpenAI + 公司官網連結", "頻道會變動，以所屬系統台官網為準。"),
    case(52, [155], "故障排除", "電視安全模式", "單輪設備邊界",
         "U：電視畫面出現安全模式。",
         "說明安全模式通常屬電視機本身系統功能，不是機上盒功能。先引導電視斷電約 1 分鐘再開機；仍出現時查閱電視原廠說明或原廠客服。",
         "電視機本身；斷電 1 分鐘；原廠說明", "機上盒燈號檢查；有線電視報修；泛用三選一", "8123 + OpenAI", "正確區分電視原廠功能與有線電視設備。"),
    case(53, [161], "優惠方案與申裝", "申裝地址範例與服務區", "公司資訊應用",
         "U：我想同時申裝電視和網路，地址要怎麼提供？",
         "依當前系統台的實際服務區提供縣市與行政區範例，並說明實際能否裝機仍需完整地址與線路查詢。",
         "當前系統台；其服務區範例；完整地址查線路", "使用其他系統台或服務區外的範例；只靠行政區保證可安裝", "8123 + OpenAI + 公司服務區資訊", "舉例也必須符合當前公司的地理範圍。"),
    case(54, [164], "故障排除", "如何測試寬頻速度", "單輪操作說明",
         "U：我想知道如何測試網速。",
         "提供數據機／分享器重啟、優先用網路線直接連線、關閉其他大流量使用、開啟測速網站與記錄上下載數值的步驟。若明顯未達申辦速率，再進入速度異常排除。",
         "重啟；有線直連；測速網站；上下載數值", "回答資料不足；只提供客服電話；未測試就報修", "8123 + OpenAI", "將「如何測速」與「測速已不達」分流。"),
    case(55, [56, 97, 131, 132, 142, 150, 153, 154], "故障排除", "有線電視無法正常收看", "單輪／多輪電視故障",
         "U：第四台卡頓／黑畫面／沒有節目／雜訊無法收視。",
         "將「第四台」、「有線電視」與電視收視異常視為同一服務主體。根據已提供的畫面或收視症狀進入對應排除，不誤切到網路故障、不虛構客戶沒說過的症狀，排除後仍異常再報修。",
         "有線電視主體；已知畫面症狀；對應排除；必要時報修", "網路故障流程；泛用三選一；虛構反覆重開機；重複詢問已描述畫面", "8123 + OpenAI", "客戶不需使用專業術語，系統要從日常描述判斷電視故障。"),
]


AUDIT_FINDINGS: dict[str, tuple[str, str]] = {
    "ORG-202609-006": (
        "needs_split",
        "同時包含廣泛繳費管道、APP 線上繳費與變更繳別；回答契約不同，建議至少拆成「繳費管道」與「繳別變更」。",
    ),
    "ORG-202609-007": (
        "needs_split",
        "YouTube、LINE TV 與數位套餐屬不同產品及操作流程，應分開由客服確認，不宜共用一份回答契約。",
    ),
    "ORG-202609-009": (
        "needs_split",
        "一般基本資料異動與有線電視更名的資格、證件及流程不同，應拆成兩筆案例。",
    ),
    "ORG-202609-015": (
        "needs_split",
        "來源同時包含本期帳務、跨期差異、部分繳費與新方案月費；其中方案詢問應移至申裝方案案例。",
    ),
    "ORG-202609-017": (
        "needs_split",
        "實體收據寄送、歷史發票查詢與紙本改電子帳單是三個不同目標，應分開驗收。",
    ),
    "ORG-202609-018": (
        "needs_split",
        "忘記帳號密碼與會員／用戶編號產生方式不同，建議拆成登入重設與帳號取得兩類。",
    ),
    "ORG-202609-026": (
        "needs_split",
        "DHCP／PPPoE 連線類型與 Wi-Fi 名稱密碼設定是不同技術問題，應分開驗收。",
    ),
    "ORG-202609-027": (
        "needs_split",
        "客編更新失敗、地址不可查個人方案及客編取得方式涉及不同狀態與權限，需拆分。",
    ),
    "ORG-202609-028": (
        "needs_split",
        "部分頻道消失／搜尋不到與特定頻道訊號不良的排除步驟不同，需拆分或移至收視品質案例。",
    ),
    "ORG-202609-044": (
        "needs_split",
        "HBO 贈送資格與一般基本頻道 E004 授權異常不是同一問題，必須拆開。",
    ),
    "ORG-202609-055": (
        "needs_split",
        "黑畫面、間歇卡頓、全部無法收視與機上盒無反應需要不同排除路徑，建議依症狀拆分。",
    ),
    "ORG-202609-029": (
        "needs_evidence",
        "原客服建議要求在聊天中索取個資，與現行受信任登入政策衝突；須由客服主管確認現行個資邊界。",
    ),
    "ORG-202609-047": (
        "needs_evidence",
        "知識庫沒有資料不能單獨證明公司未提供服務，須由產品或服務目錄確認。",
    ),
    "ORG-202609-048": (
        "needs_evidence",
        "來源只要求說明 DS 閃爍意義，草稿中的等待時間需由設備知識或 SOP 證實。",
    ),
    "ORG-202609-050": (
        "needs_evidence",
        "原回饋只有「確認無法傳送原因」，缺少工具錯誤、預期動作與可接受回覆，需先查日誌並由客服補充。",
    ),
    "ORG-202609-053": (
        "needs_evidence",
        "原始對話主題與客服提出的地址範例不一致，無法確認代表情境是否正確，需客服重新定義。",
    ),
}

AUDIT_DEFAULT = (
    "ready_for_csr_review",
    "初步檢視未發現明顯過度合併或來源衝突；仍須由客服確認業務事實與回答邊界。",
)


def snapshot_rows() -> list[dict[str, Any]]:
    rows = list_feedback_items(
        start_date="2026-08-24",
        status="processed",
    )
    return [
        row for row in rows
        if str(row.get("review_status") or "") in {"organizing", "merged"}
    ]


def snapshot_digest(rows: list[dict[str, Any]]) -> str:
    value = "\n".join(str(row.get("feedback_id") or "") for row in rows)
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def validate_definitions(rows: list[dict[str, Any]]) -> dict[str, Any]:
    errors: list[str] = []
    if len(rows) != SNAPSHOT_COUNT:
        errors.append(f"快照筆數應為 {SNAPSHOT_COUNT}，實際為 {len(rows)}")
    digest = snapshot_digest(rows)
    if digest != SNAPSHOT_SHA256:
        errors.append(f"快照雜湊不符：{digest}")
    if len(GROUPS) != EXPECTED_CASE_COUNT:
        errors.append(f"案例數應為 {EXPECTED_CASE_COUNT}，實際為 {len(GROUPS)}")
    unknown_audit_cases = sorted(set(AUDIT_FINDINGS) - {item["case_id"] for item in GROUPS})
    if unknown_audit_cases:
        errors.append(f"檢視結果包含不存在的案例：{unknown_audit_cases}")

    assigned: dict[int, str] = {}
    case_ids: set[str] = set()
    for definition in GROUPS:
        case_id = str(definition.get("case_id") or "")
        if case_id in case_ids:
            errors.append(f"案例編號重複：{case_id}")
        case_ids.add(case_id)
        for field in (
            "suite", "group_name", "case_kind", "script", "expected_behavior",
            "must_include", "must_not_include", "dependency", "focus",
        ):
            if not str(definition.get(field) or "").strip():
                errors.append(f"{case_id} 缺少 {field}")
        for source_number in definition["source_numbers"]:
            if source_number in assigned:
                errors.append(
                    f"第 {source_number} 筆同時分到 {assigned[source_number]} "
                    f"與 {definition['case_id']}"
                )
            assigned[source_number] = definition["case_id"]

    for source_number in EXCLUDED:
        if source_number in assigned:
            errors.append(f"第 {source_number} 筆既分組又排除")
        assigned[source_number] = "excluded"

    expected_numbers = set(range(1, SNAPSHOT_COUNT + 1))
    missing = sorted(expected_numbers - set(assigned))
    extra = sorted(set(assigned) - expected_numbers)
    if missing:
        errors.append(f"未分組：{missing}")
    if extra:
        errors.append(f"超出快照：{extra}")

    return {
        "valid": not errors,
        "errors": errors,
        "feedback_count": len(rows),
        "case_count": len(GROUPS),
        "grouped_feedback_count": sum(len(item["source_numbers"]) for item in GROUPS),
        "excluded_feedback_count": len(EXCLUDED),
        "snapshot_sha256": digest,
    }


def materialize_definitions(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    materialized = []
    for definition in GROUPS:
        source_rows = [rows[number - 1] for number in definition["source_numbers"]]
        company_codes = sorted({str(row.get("company_code") or "") for row in source_rows if row.get("company_code")})
        audit_status, audit_note = AUDIT_FINDINGS.get(definition["case_id"], AUDIT_DEFAULT)
        materialized.append({
            **{key: value for key, value in definition.items() if key != "source_numbers"},
            "company_codes": "全部系統台" if len(company_codes) > 1 else (company_codes[0] if company_codes else "全部系統台"),
            "source_feedback_ids": [row["feedback_id"] for row in source_rows],
            "audit_status": audit_status,
            "audit_note": audit_note,
        })
    return materialized


def apply_definitions(rows: list[dict[str, Any]], definitions: list[dict[str, Any]]) -> dict[str, int]:
    init_tracker_schema()
    source_feedback_ids = {str(row["feedback_id"]) for row in rows}
    now = now_iso()
    conn = tracker_db_conn()
    unlinked = 0
    stale_cases_removed = 0
    feedback_updated = 0
    try:
        existing_cases = conn.execute(
            "SELECT case_id, source_feedback_ids_json FROM regression_cases"
        ).fetchall()
        generated_ids = {definition["case_id"] for definition in definitions}
        for existing in existing_cases:
            if existing["case_id"] in generated_ids:
                continue
            try:
                source_ids = json.loads(existing["source_feedback_ids_json"] or "[]")
            except json.JSONDecodeError:
                source_ids = []
            kept_ids = [source_id for source_id in source_ids if source_id not in source_feedback_ids]
            if kept_ids == source_ids:
                continue
            conn.execute(
                "UPDATE regression_cases SET source_feedback_ids_json=?, updated_at=?, updated_by=? WHERE case_id=?",
                (json.dumps(kept_ids, ensure_ascii=False), now, ACTOR, existing["case_id"]),
            )
            unlinked += len(source_ids) - len(kept_ids)

        stale_rows = conn.execute(
            "SELECT case_id FROM regression_cases WHERE case_id LIKE ?",
            (f"{CASE_PREFIX}%",),
        ).fetchall()
        for stale_row in stale_rows:
            stale_case_id = str(stale_row["case_id"])
            if stale_case_id in generated_ids:
                continue
            conn.execute("DELETE FROM regression_cases WHERE case_id=?", (stale_case_id,))
            stale_cases_removed += 1

        for definition in definitions:
            case_review_note = (
                f"初步檢視：{definition['audit_note']}\n"
                "尚未由客服確認，亦未以 8123 重播。"
            )
            conn.execute(
                """
                INSERT INTO regression_cases (
                    case_id, suite, priority, group_name, company_codes, case_kind,
                    script, expected_behavior, must_include, must_not_include,
                    dependency, focus, source_feedback_ids_json, test_results_json,
                    status, owner, review_status, review_note, updated_at, updated_by
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, '[]',
                          'ready_for_review', NULL, 'organizing', ?, ?, ?)
                ON CONFLICT(case_id) DO UPDATE SET
                    suite=excluded.suite,
                    priority=excluded.priority,
                    group_name=excluded.group_name,
                    company_codes=excluded.company_codes,
                    case_kind=excluded.case_kind,
                    script=excluded.script,
                    expected_behavior=excluded.expected_behavior,
                    must_include=excluded.must_include,
                    must_not_include=excluded.must_not_include,
                    dependency=excluded.dependency,
                    focus=excluded.focus,
                    source_feedback_ids_json=excluded.source_feedback_ids_json,
                    status='ready_for_review',
                    review_status='organizing',
                    review_note=excluded.review_note,
                    updated_at=excluded.updated_at,
                    updated_by=excluded.updated_by
                """,
                (
                    definition["case_id"], definition["suite"], definition["priority"],
                    definition["group_name"], definition["company_codes"], definition["case_kind"],
                    definition["script"], definition["expected_behavior"], definition["must_include"],
                    definition["must_not_include"], definition["dependency"], definition["focus"],
                    json.dumps(definition["source_feedback_ids"], ensure_ascii=False),
                    case_review_note,
                    now,
                    ACTOR,
                ),
            )
            representative_id = str(definition["source_feedback_ids"][0])
            representative_note = (
                f"已整理至 {definition['case_id']}｜{definition['group_name']}\n"
                f"專業建議：{definition['expected_behavior']}\n"
                f"初步檢視：{definition['audit_note']}\n"
                "尚未由客服確認，亦未以 8123 重播，狀態維持待整理。"
            )
            conn.execute(
                """
                UPDATE feedback_tracker_state
                SET status='processed', review_status='organizing', review_note=?,
                    updated_at=?, updated_by=?
                WHERE feedback_id=?
                """,
                (representative_note, now, ACTOR, representative_id),
            )
            feedback_updated += 1
            for feedback_id in definition["source_feedback_ids"][1:]:
                merged_note = (
                    f"已合併至代表案例 {representative_id}｜{definition['case_id']}｜"
                    f"{definition['group_name']}。原始回饋保留供追溯，不再列入待整理計數。"
                )
                conn.execute(
                    """
                    UPDATE feedback_tracker_state
                    SET status='processed', review_status='merged', review_note=?,
                        updated_at=?, updated_by=?
                    WHERE feedback_id=?
                    """,
                    (merged_note, now, ACTOR, feedback_id),
                )
                feedback_updated += 1

        for source_number, reason in EXCLUDED.items():
            feedback_id = str(rows[source_number - 1]["feedback_id"])
            conn.execute(
                """
                UPDATE feedback_tracker_state
                SET status='processed', review_status='merged', review_note=?,
                    updated_at=?, updated_by=?
                WHERE feedback_id=?
                """,
                (
                    f"排除說明：{reason}\n原始回饋保留供追溯，不列入待整理計數。",
                    now,
                    ACTOR,
                    feedback_id,
                ),
            )
            feedback_updated += 1

        conn.commit()
    finally:
        conn.close()
    return {
        "cases_upserted": len(definitions),
        "feedback_updated": feedback_updated,
        "representatives_kept_organizing": len(definitions),
        "sources_marked_merged": feedback_updated - len(definitions),
        "legacy_links_removed": unlinked,
        "stale_cases_removed": stale_cases_removed,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()

    rows = snapshot_rows()
    validation = validate_definitions(rows)
    print(json.dumps({"validation": validation}, ensure_ascii=False, indent=2))
    if not validation["valid"]:
        raise SystemExit(1)

    definitions = materialize_definitions(rows)
    summary = {
        "cases": len(definitions),
        "source_feedback": sum(len(item["source_feedback_ids"]) for item in definitions),
        "excluded_feedback": len(EXCLUDED),
        "suites": sorted({item["suite"] for item in definitions}),
        "audit": {
            status: sum(item["audit_status"] == status for item in definitions)
            for status in {item["audit_status"] for item in definitions}
        },
    }
    print(json.dumps({"organization": summary}, ensure_ascii=False, indent=2))
    if args.apply:
        print(json.dumps({"applied": apply_definitions(rows, definitions)}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
