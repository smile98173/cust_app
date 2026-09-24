import json
import re
from typing import Dict, Any
from langchain_core.prompts import ChatPromptTemplate


def safe_json_loads(text: str) -> Dict[str, Any]:
    if not text:
        return {}

    cleaned = text.strip().replace("```json", "").replace("```", "").strip()
    start = cleaned.find("{")
    end = cleaned.rfind("}")

    if start != -1 and end != -1 and end > start:
        cleaned = cleaned[start:end + 1]

    try:
        data = json.loads(cleaned)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


STEP_RULES = """
你是客服排錯流程判斷器。

請根據「目前步驟正在確認的問題」與使用者最新回覆，判斷使用者意思。
重點是判斷語意，不要只看字面關鍵字。

label 可為：
- affirmative：表示有、是、已確認、有亮、有做
- negative：表示沒有、不是、沒亮、沒做
- recovered：表示好了、恢復了、可以了
- failed：表示還是不行、沒有恢復、沒用
- refuse：表示不會弄、不想排錯、太麻煩、直接派人、我要報修
- fault_report：在已開始排錯時，只是再次說「回報故障」或有錯字的「回報故髒」，未明確要求派人或立刻報修
- device_replacement：表示更換了新的 Wi-Fi／網路設備後不能上網，但原本或舊設備可以正常使用
- app_connectivity_detail：在機上盒聯網排錯中，使用者補充 Wi-Fi／網路訊號正常，但機上盒內的應用程式顯示無法連網；這是新的故障範圍資訊，不代表已執行目前步驟後仍失敗
- unknown：無法判斷

判斷原則：
- 使用者提供下載／上傳測速數值時，不能只因為說了「重開完成」就判斷為 recovered。若下載速度明顯偏低或較前次測速大幅下降，應判斷為 failed 或 unknown，交由排錯流程接續處理。
- 若目前步驟是在請使用者確認或操作某件事，使用者回答「狀況沒有改善、結果跟前面一樣、仍然不能用、仍然沒有亮」時，應判斷為 failed 或 negative。
- 若使用者表示已經做過重插電、重開、切換、檢查等操作，但狀況仍一樣或燈號/畫面仍異常，應判斷為 failed。
- 若使用者明確說已恢復、可以了，判斷為 recovered。
- 若使用者要停止排錯、要報修、要派人，判斷為 refuse。
- 若已在排錯中，使用者只說「回報故障」或「回報故髒」，而沒有說要派人、立即報修或不想排錯，判斷為 fault_report；這是在重申問題，應繼續診斷，不是直接轉真人。
- 若正在處理網路問題，且使用者說新設備不能用、換回舊設備就正常，判斷為 device_replacement。
  這代表原本網路服務可用，優先引導新設備的註冊方式，不要重複詢問所有設備或單一設備。
- 若正在處理機上盒網路問題，使用者只是補充 Wi-Fi／網路訊號正常，但進入應用程式時顯示無法連網，判斷為 app_connectivity_detail。除非使用者同時明確說已完成重新連線、重開與其他應用程式測試仍失敗，否則不可判斷為 failed。
- 若使用者只是說不知道、不會看、不確定，判斷為 unknown；不要硬猜。

只能輸出 JSON：
{"label": "unknown"}
"""


FAULT_CATEGORY_RULES = """
你是客服故障類型語意分類器。

請根據「先前故障描述」與「使用者最新回覆」，判斷使用者要回報的故障類型。
你只負責選排錯流程，不要決定是否派修、查帳務或建立工單。

type 可為：
- tv：有線電視、第四台、頻道、電視畫面、機上盒收視或訊號問題
- network：寬頻網路、Wi-Fi、上網、數據機、分享器、網速或連線問題
- remote：遙控器按鍵、轉台、配對、控制機上盒的問題
- unknown：無法判斷，或看起來不是故障排錯

判斷原則：
- 使用者可能有錯字、口語或自創詞，例如「不好看的」「怪怪的」「卡卡」「霧霧」「爛掉」。
- 若使用者已明確回答「電視」「網路」「遙控器」「機上盒」，請依該類別判斷。
- 若沒有服務類別，也沒有足夠故障語意，請回 unknown。

只能輸出 JSON：
{"type": "unknown", "confidence": 0.0}
"""


STEP_CONTEXTS = {
    "ask_fault_category": "正在確認使用者遇到的是電視、網路，還是其他設備問題。",
    "tv_check_power": "正在確認機上盒電源燈是否有亮。",
    "tv_check_power_cable": "已請使用者確認機上盒電源線是否插好、插座是否有電，現在要判斷確認後機上盒電源燈是否有亮或仍未恢復。",
    "tv_check_screen": "正在確認電視畫面狀況；例如無訊號、黑畫面、錯誤代碼、開機循環或其他異常畫面。",
    "tv_check_input_source": "已請使用者切換電視訊號源到 HDMI 或 AV，正在確認畫面是否恢復。",
    "tv_reboot": "已請使用者重開機上盒，正在確認畫面或服務是否恢復。",
    "tv_rescan_channels": "已請使用者重搜或恢復預設，正在確認頻道是否恢復。",
    "remote_check_light": "正在確認遙控器按鍵時是否有亮紅燈。",
    "remote_check_receiver": "已確認遙控器按鍵有亮紅燈，正在確認是否對準機上盒、IR 接收器是否遮住或脫落。",
    "net_check_scope": "正在確認是所有設備都不能上網，還是只有單一手機或電腦不能上網。",
    "net_check_modem_light": "正在確認數據機燈號是否正常、紅燈、異常閃爍或完全沒亮。",
    "net_reboot_modem": "已請使用者重開數據機，正在確認網路是否恢復。",
    "net_single_device": "已請使用者重新連線單一設備的 Wi-Fi 或網路線，正在確認該設備是否恢復。",
    "net_phone_connection_type": "正在確認手機使用的是家中 Wi-Fi 還是 4G/5G 行動網路。",
    "net_computer_connection_type": "正在確認電腦使用的是 Wi-Fi 還是實體網路線。",
    "net_unstable_scope": "正在確認網路不穩、遊戲或 APP 斷線，是所有服務/設備都會發生，還是只在特定遊戲、影片或 APP 發生；使用者不一定是完全不能上網。",
    "net_slow_scope": "正在確認是所有網站/APP 都很慢，還是只有特定遊戲、影片或 APP 很慢。",
    "net_slow_specific": "正在確認特定遊戲、影片或 APP 的問題是否也影響其他服務或測速結果。",
    "net_router_path_check": "已確認速度問題集中在路由器路徑，正在比較電腦直連數據機與經路由器連線的測速結果。",
    "net_device_registration": "已請使用者確認新路由器的 WAN／Internet 接線及 DHCP／自動取得 IP，正在確認設定後能否上網。",
    "net_manual_device_registration": "已引導使用者至官網手動完成設備註冊，正在確認註冊後能否上網。",
    "net_wired_connection_check": "使用者補充目前直接接網路孔或網路線，正在確認有線連接、孔位與影響範圍。",
    "stb_network_check": "正在排除哈TV機上盒本身的網路連線，需確認其他裝置是否正常、機上盒網路設定與重新連線結果。",
    "stb_app_connectivity_check": "已確認機上盒 Wi-Fi 訊號正常但應用程式無法連線，正在確認重新連線、重開機上盒及其他應用程式測試結果。",
}


SET_TOP_BOX_NETWORK_INTENTS = {
    "tv_set_top_box_network_connection_issue",
    "hatv_set_top_box_network_connection_issue",
    "tv_set_top_box_app_network_issue",
}

ROUTER_PATH_SLOW_INTENTS = {
    "router_path_slow_issue",
    "router_bottleneck_issue",
}

ROUTER_REGISTRATION_INTENTS = {
    "new_device_registration_issue",
    "router_replacement_registration_issue",
}

TV_PICTURE_QUALITY_INTENTS = {
    "tv_picture_quality_issue",
    "tv_channel_jitter_issue",
    "tv_channel_picture_jitter_issue",
    "tv_channel_picture_audio_issue",
    "tv_picture_audio_issue",
}

REMOTE_CONTROL_TROUBLESHOOTING_INTENTS = {
    "remote_control_issue",
    "tv_remote_control_issue",
    "tv_remote_control_channel_issue",
    "remote_control_channel_selection_issue",
    "remote_control_button_issue",
}


def classify_reply_by_keywords(text: str) -> str:
    if is_recovered_reply(text):
        return "recovered"
    if is_refuse_reply(text):
        return "refuse"
    if is_unknown_reply(text):
        return "unknown"
    if is_failed_reply(text):
        return "failed"
    return "unknown"


def classify_reply(text: str, step: str, issue_description: str = "", llm=None) -> str:
    if llm is None:
        return classify_reply_by_keywords(text)

    prompt = ChatPromptTemplate.from_template(
        "{rules}\n\n目前步驟代碼：{step}\n目前步驟語境：{step_context}\n"
        "先前問題描述：{issue_description}\n使用者回覆：{text}"
    )

    try:
        chain = prompt | llm
        resp = chain.invoke({
            "rules": STEP_RULES,
            "step": step,
            "step_context": STEP_CONTEXTS.get(step, "請依目前步驟與使用者回覆判斷。"),
            "issue_description": issue_description,
            "text": text,
        })
        data = safe_json_loads(resp.content)
        label = data.get("label", "unknown")
        if label not in [
            "affirmative", "negative", "recovered", "failed", "refuse", "fault_report",
            "device_replacement", "app_connectivity_detail", "unknown",
        ]:
            return "unknown"
        return label
    except Exception:
        return "unknown"


def classify_fault_category_by_llm(text: str, memory: Dict[str, Any], llm=None) -> str | None:
    if llm is None:
        return None

    known = memory.setdefault("known_info", {})
    prompt = ChatPromptTemplate.from_template(
        "{rules}\n\n先前故障描述：{issue_description}\n使用者最新回覆：{text}"
    )

    try:
        chain = prompt | llm
        resp = chain.invoke({
            "rules": FAULT_CATEGORY_RULES,
            "issue_description": known.get("issue_description") or "",
            "text": text,
        })
        data = safe_json_loads(resp.content)
        category = data.get("type") or data.get("category")
        confidence = float(data.get("confidence", 0) or 0)
        if category in ["tv", "network", "remote"] and confidence >= 0.65:
            return category
        return None
    except Exception:
        return None


def contains_any(text: str, keywords: list[str]) -> bool:
    text = text or ""
    return any(k in text for k in keywords)


WIRED_CONNECTION_DETAIL_TERMS = [
    "直接插網路孔",
    "插網路孔",
    "接網路孔",
    "網路孔",
    "牆上孔",
    "牆壁孔",
    "資訊插座",
    "網路線",
    "實體網路線",
    "有線",
    "lan",
    "LAN",
    "直接插",
]


def is_wired_connection_detail(text: str) -> bool:
    value = text or ""
    compact = value.replace(" ", "").replace("　", "")
    if not compact:
        return False
    if is_failed_reply(value) or is_recovered_reply(value) or is_explicit_repair_request(value):
        return False
    return contains_any(compact, WIRED_CONNECTION_DETAIL_TERMS)


NO_SIGNAL_TERMS = [
    "無訊號",
    "沒訊號",
    "沒有訊號",
    "無信號",
    "沒信號",
    "沒有信號",
    "搜不到訊號",
    "搜尋不到訊號",
    "類比訊號",
    "類比信號",
]


def is_no_signal_issue(text: str) -> bool:
    return contains_any(text, NO_SIGNAL_TERMS)


FAILED_REPLY_KEYWORDS = [
    "還是不行",
    "還是不能",
    "還是無法",
    "還是沒辦法",
    "沒有恢復",
    "沒恢復",
    "一樣不行",
    "一樣不能",
    "一樣無法",
    "仍然不行",
    "仍然不能",
    "還沒好",
    "沒用",
    "不能上網",
    "無法上網",
    "連不上網",
    "上不了網",
    "沒網路",
    "就是不能用",
    "還是不能用",
    "一樣不能用",
    "重開也一樣",
    "重開一樣",
    "重開過了",
    "剛剛重開過",
    "都試過了",
    "都試過",
]


RECOVERED_REPLY_KEYWORDS = [
    "好了",
    "可以了",
    "沒事了",
    "沒問題了",
    "問題解決了",
    "恢復了",
    "已恢復",
    "正常了",
    "能上網了",
    "可以上網了",
    "已經可以上網",
    "現在可以上網",
]

STOP_TROUBLESHOOTING_KEYWORDS = [
    "先不用了",
    "不用排查了",
    "不用再查了",
    "不用處理了",
    "暫時不用",
    "先這樣",
    "算了",
]

REFUSE_REPLY_KEYWORDS = [
    "回報故障",
    "報修",
    "我要報修",
    "直接報修",
    "建立工單",
    "派人",
    "派工",
    "請人來修",
    "不行",
    "不用了",
    "不要",
    "不要吵",
    "不想排錯",
    "不會弄",
    "太麻煩",
    "懶得用",
    "懶得弄",
    "算了",
    "我不會調",
    "我不會切",
]

UNKNOWN_REPLY_KEYWORDS = [
    "不知道",
    "我不知道",
    "我就不知道",
    "不確定",
    "不清楚",
    "看不懂",
    "不會看",
    "不會確認",
    "無法確認",
    "沒辦法確認",
    "應該吧",
    "你幫我看",
    "幫我看",
]

CORRECTION_REPLY_KEYWORDS = [
    "我說錯",
    "我講錯",
    "剛剛說錯",
    "剛剛講錯",
    "打錯",
    "弄錯",
    "搞錯",
    "不是這個",
    "不是這樣",
    "不是剛剛那個",
    "不對",
    "重來",
    "重新來",
    "重新確認",
]

CONFUSION_REPLY_KEYWORDS = [
    "蛤",
    "蛤?",
    "蛤？",
    "啥",
    "聽不懂",
    "看不懂",
    "不懂你在問什麼",
    "不知道你在問什麼",
    "你在問什麼",
    "你問什麼",
    "問什麼",
]

FLOW_REJECTION_REPLIES = {
    "不是",
    "不是啦",
    "不是拉",
    "不是啊",
    "不是阿",
}


def is_failed_reply(text: str) -> bool:
    return contains_any(text, FAILED_REPLY_KEYWORDS)


def is_recovered_reply(text: str) -> bool:
    if is_failed_reply(text):
        return False
    return contains_any(text, RECOVERED_REPLY_KEYWORDS)


def extract_network_speed_result(text: str) -> tuple[float | None, float | None]:
    """Extract labelled download/upload values from a customer speed-test reply."""
    value = text or ""

    def extract(labels: str) -> float | None:
        match = re.search(
            rf"(?:{labels})\s*[:：]?\s*(\d+(?:\.\d+)?)\s*(?:mbps|m)\b",
            value,
            flags=re.IGNORECASE,
        )
        return float(match.group(1)) if match else None

    return (
        extract(r"下載|download|down"),
        extract(r"上傳|upload|up"),
    )


def normalize_speed_to_mbps(value: float, unit: str) -> float:
    return value * 1000 if unit.lower() in {"g", "gbps"} else value


def extract_declared_plan_speed_mbps(text: str) -> float | None:
    """Extract a plan speed the customer explicitly says they subscribed to."""
    match = re.search(
        r"(?:申辦|申請|方案|合約|速率|頻寬)\s*(?:為|是)?\s*"
        r"(\d+(?:\.\d+)?)\s*(gbps|g|mbps|m)(?![a-z])",
        text or "",
        flags=re.IGNORECASE,
    )
    if not match:
        return None
    return normalize_speed_to_mbps(float(match.group(1)), match.group(2))


def extract_unlabelled_measured_speed_mbps(text: str) -> float | None:
    """Extract a measured result stated as 'only N Mbps' without a download label."""
    match = re.search(
        r"(?:只有|僅|測得|實測|測試(?:結果|之後|後)?)\D{0,16}?"
        r"(\d+(?:\.\d+)?)\s*(mbps|m)(?![a-z])",
        text or "",
        flags=re.IGNORECASE,
    )
    if not match:
        return None
    return normalize_speed_to_mbps(float(match.group(1)), match.group(2))


def record_declared_speed_gap(known: Dict[str, Any], text: str) -> tuple[float | None, float | None]:
    declared = extract_declared_plan_speed_mbps(text)
    measured = extract_unlabelled_measured_speed_mbps(text)
    if declared is not None:
        known["declared_plan_speed_mbps"] = declared
    if measured is not None:
        known["download_speed"] = measured
    remembered_declared = known.get("declared_plan_speed_mbps")
    remembered_measured = known.get("download_speed")
    return (
        declared if declared is not None else remembered_declared,
        measured if measured is not None else remembered_measured,
    )


def is_substantially_below_declared_speed(
    declared: float | None,
    measured: float | None,
) -> bool:
    return (
        declared is not None
        and measured is not None
        and measured < declared * 0.5
    )


def has_declared_speed_gap(text: str) -> bool:
    return is_substantially_below_declared_speed(
        extract_declared_plan_speed_mbps(text),
        extract_unlabelled_measured_speed_mbps(text),
    )


def build_declared_speed_retest_reply(declared: float, measured: float) -> str:
    return (
        f"了解，您表示申辦速率為 {declared:g} Mbps，但目前實測約 {measured:g} Mbps，"
        "差距明顯，先確認測速條件。\n\n"
        "1. 請將電腦以網路線直接連接數據機或分享器，暫時不要使用 Wi-Fi。\n"
        "2. 關閉下載、雲端同步、影音串流及其他大量用網設備。\n"
        "3. 將數據機及分享器電源拔掉約 10 秒後重新插上，等待 3 到 5 分鐘，再到 www.speedtest.net 重測下載與上傳速度。\n\n"
        "若重測後仍明顯低於申辦速率，或您想直接報修，請告訴我，我會接續安排線路與設備檢查。"
    )


def record_network_speed_result(known: Dict[str, Any], text: str) -> tuple[float | None, float | None]:
    download, upload = extract_network_speed_result(text)
    if download is not None:
        previous = known.get("download_speed")
        if isinstance(previous, (int, float)) and previous != download:
            known["previous_download_speed"] = previous
        known["download_speed"] = download
    if upload is not None:
        known["upload_speed"] = upload
    return download, upload


def is_clearly_abnormal_download_speed(known: Dict[str, Any], download: float | None) -> bool:
    if download is None:
        return False
    if download < 10:
        return True

    previous = known.get("previous_download_speed")
    return isinstance(previous, (int, float)) and previous >= 100 and download <= previous * 0.25


def is_stop_troubleshooting_reply(text: str) -> bool:
    if is_failed_reply(text) or is_explicit_repair_request(text):
        return False
    return contains_any(text, STOP_TROUBLESHOOTING_KEYWORDS)


def is_refuse_reply(text: str) -> bool:
    return contains_any(text, REFUSE_REPLY_KEYWORDS)


def is_unknown_reply(text: str) -> bool:
    return contains_any(text, UNKNOWN_REPLY_KEYWORDS)


def is_repair_context_continuation(text: str) -> bool:
    value = text or ""
    compact = value.replace(" ", "").replace("　", "").lower()
    if not compact:
        return False

    symptom_terms = [
        "不穩",
        "不穩定",
        "訊號不穩",
        "訊號不好",
        "沒有連線",
        "沒連線",
        "未連線",
        "卡住",
        "繞圈圈",
        "轉圈圈",
        "一直閃",
        "閃紅",
        "紅燈",
        "亮紅",
        "異常",
        "發熱",
        "很熱",
        "會熱",
    ]
    device_terms = [
        "數據機",
        "機器",
        "燈",
        "燈號",
        "電視",
        "機上盒",
        "網路",
        "上網",
        "wifi",
        "wi-fi",
        "一樓",
        "二樓",
        "樓",
    ]

    if contains_any(compact, symptom_terms):
        return True

    return contains_any(compact, device_terms) and contains_any(
        compact,
        ["可以上網", "能上網", "但是", "只是", "還是", "一樣", "常"],
    )


def has_persistent_modem_instability_context(memory: Dict[str, Any]) -> bool:
    known = (memory or {}).get("known_info", {}) or {}
    description = str(known.get("issue_description") or "")
    compact = description.replace(" ", "").replace("　", "").lower()
    return contains_any(
        compact,
        [
            "超過半年",
            "半年",
            "舊款",
            "sb6141",
            "發熱",
            "很熱",
            "容易發熱",
            "免費更",
            "更換",
            "換數據機",
        ],
    )


def has_high_risk_modem_instability_context(memory: Dict[str, Any]) -> bool:
    description = str(((memory or {}).get("known_info", {}) or {}).get("issue_description") or "")
    compact = description.replace(" ", "").replace("　", "").lower()
    has_aging_or_heat_signal = contains_any(
        compact,
        ["sb6141", "舊款", "發熱", "很熱", "容易發熱", "過熱"],
    )
    has_persistent_connection_signal = contains_any(
        compact,
        ["不穩", "不穩定", "常斷", "斷線", "訊號差", "訊號不好", "超過半年", "半年"],
    )
    return has_aging_or_heat_signal and has_persistent_connection_signal


def is_correction_reply(text: str) -> bool:
    return contains_any(text, CORRECTION_REPLY_KEYWORDS)


def is_confusion_reply(text: str) -> bool:
    return contains_any(text, CONFUSION_REPLY_KEYWORDS)


def is_flow_rejection_reply(text: str) -> bool:
    return (text or "").strip() in FLOW_REJECTION_REPLIES


def is_already_rebooted_reply(text: str) -> bool:
    return contains_any(text or "", [
        "重開過",
        "重開了",
        "重開後",
        "剛剛重開",
        "已經重開",
        "都重開",
        "重啟後",
        "重新啟動後",
        "拔插後",
        "重拔插頭",
        "都試過",
    ])


def allow_keyword_step_fallback(memory: Dict[str, Any]) -> bool:
    known = memory.setdefault("known_info", {})
    return known.get("_llm_step_classifier_used") != "yes"


def fallback_failed(memory: Dict[str, Any], text: str) -> bool:
    return allow_keyword_step_fallback(memory) and is_failed_reply(text)


def fallback_recovered(memory: Dict[str, Any], text: str) -> bool:
    return allow_keyword_step_fallback(memory) and is_recovered_reply(text)


def fallback_refuse(memory: Dict[str, Any], text: str) -> bool:
    return allow_keyword_step_fallback(memory) and is_refuse_reply(text)


def fallback_unknown(memory: Dict[str, Any], text: str) -> bool:
    return allow_keyword_step_fallback(memory) and is_unknown_reply(text)


def is_input_source_not_recovered_reply(text: str) -> bool:
    value = (text or "").strip()
    return (
        value in ["沒有", "沒", "無", "沒有恢復", "沒恢復"]
        or contains_any(value, [
            "沒有恢復",
            "沒恢復",
            "還是不行",
            "還是不能",
            "一樣不行",
            "沒用",
        ])
    )


def is_partial_channel_issue(text: str) -> bool:
    value = text or ""
    has_partial = contains_any(value, ["部分", "部份", "有些", "某些", "特定", "幾台", "幾個"])
    has_channel = contains_any(value, ["頻道", "台", "第四台"])
    has_problem = contains_any(value, [
        "看不到",
        "不能看",
        "黑畫面",
        "收不到",
        "不見",
        "消失",
        "訊號不好",
        "訊號不佳",
        "訊號不良",
        "收訊不好",
        "收訊不佳",
        "收訊不良",
    ]) or is_no_signal_issue(value)
    return has_partial and has_channel and has_problem


def build_channel_rescan_reply() -> str:
    return (
        "頻道收視異常時，請先嘗試恢復原廠預設或重新搜頻：\n\n"
        "1. 如果您使用的是東方紅色機上盒，請按遙控器上的「目錄鍵」加「數字 1」執行恢復預設，"
        "等待搜頻結束後，機上盒會跳到 01 頻道，再確認是否可以選台觀看。\n"
        "2. 如果您使用的是雙模機且遙控器型號為 TOP-006，請按遙控器下方九個功能鍵中的「重搜」。\n"
        "3. 如果您使用的是雙模機且遙控器型號為 TOP-007，請按遙控器上方八個功能鍵中的「重搜」。\n\n"
        "重搜完成後，請再確認原本看不到的頻道是否恢復。"
    )


def is_input_source_how_to_query(text: str) -> bool:
    value = (text or "").strip()
    if not value:
        return False
    has_switch_action = contains_any(value, ["怎麼切", "怎麼調", "如何切", "如何調", "不會切", "不會調", "不會操作", "不會用"])
    has_source_context = contains_any(value, ["訊號源", "輸入源", "input", "Input", "INPUT", "source", "Source", "SOURCE", "hdmi", "HDMI", "av", "AV"])
    return has_switch_action and (has_source_context or len(value) <= 8)


def is_network_troubleshooting_how_to_query(text: str) -> bool:
    value = (text or "").strip()
    if not value:
        return False
    asks_how = contains_any(value, ["如何", "怎麼", "怎樣", "不會"])
    has_action = contains_any(value, ["執行", "操作", "做", "排除", "測試", "測速", "重開"])
    return asks_how and has_action


def is_network_cause_source_question(text: str) -> bool:
    value = compact_text(text)
    return "基地台" in value or (
        "線路" in value
        and contains_any(value, ["關係", "原因", "哪裡", "問題", "造成"])
    )


def is_fault(text: str) -> bool:
    return detect_troubleshooting_type(text) is not None


def is_outdoor_service_line_issue(text: str) -> bool:
    value = compact_text(text)
    return (
        "室外" in value
        and contains_any(value, ["電源線", "纜線", "線路", "電纜", "訊號線"])
        and contains_any(value, ["鬆脫", "鬆掉", "脫落", "掉下", "掉了", "斷掉"])
    )


def is_general_signal_fault_report(text: str) -> bool:
    value = (text or "").strip()
    if not value:
        return False
    generic_signal = contains_any(value, [
        "訊號不佳",
        "訊號不良",
        "訊號不好",
        "收訊不佳",
        "收訊不良",
        "收訊不好",
    ])
    has_explicit_service = contains_any(value, [
        "電視",
        "第四台",
        "機上盒",
        "畫面",
        "頻道",
        "網路",
        "寬頻",
        "wifi",
        "Wi-Fi",
        "WIFI",
        "連線",
    ])
    if generic_signal and not has_explicit_service:
        return True
    return contains_any(value, ["斷訊", "查訊號", "訊號異常", "訊號問題"]) and not (
        is_network_fault(value) or is_tv_fault(value)
    )


def is_remote_control_issue(text: str) -> bool:
    value = text or ""
    has_remote = contains_any(value, ["遙控器", "遙控", "搖控器", "搖控"])
    has_problem = contains_any(value, [
        "異常",
        "控制異常",
        "接觸不良",
        "不能控制",
        "無法控制",
        "不能使用",
        "無法使用",
        "不能用",
        "無法開關機",
        "不能開關機",
        "無法開機",
        "無法關機",
        "不能轉台",
        "無法轉台",
        "沒反應",
        "沒有反應",
        "無反應",
        "按了沒反應",
        "按鍵沒反應",
        "按鈕壞",
        "按鍵壞",
        "數字按鈕壞",
        "數字鍵壞",
        "壞了",
        "故障",
    ])
    return has_remote and has_problem


def is_restricted_channel_purchase_request(text: str) -> bool:
    value = text or ""
    return contains_any(value, ["成人", "限制級"]) and contains_any(
        value,
        ["購買", "加購", "訂購", "怎麼買", "如何買", "如何購買"],
    )


def compact_text(text: str) -> str:
    return (text or "").replace(" ", "").replace("　", "")


def is_tv_no_channel_issue(text: str) -> bool:
    value = compact_text(text)
    return contains_any(value, [
        "沒頻道",
        "沒有頻道",
        "沒節目",
        "沒有節目",
        "沒台",
        "沒有台",
        "搜尋不到頻道",
        "搜不到頻道",
        "頻道看不到",
        "頻道不能看",
        "頻道沒訊號",
        "頻道沒有訊號",
        "收不到頻道",
        "頻道都不見",
        "頻道消失",
        "有開但沒頻道",
        "有開但是沒頻道",
    ])


def is_tv_screen_freeze_issue(text: str) -> bool:
    value = compact_text(text)
    return contains_any(value, [
        "電視一直卡",
        "卡在機上盒教學",
        "畫面一直卡",
        "畫面卡卡",
        "畫面卡住",
        "畫面定格",
        "畫面lag",
        "畫面會lag",
        "中途會轉圈",
        "中途轉圈",
        "會轉圈lag",
        "轉圈lag",
        "轉圈",
        "畫面一直停住",
        "畫面停住",
        "畫面一直跳",
        "畫面閃爍",
        "畫面一直斷",
        "電視一直黑掉",
        "一直轉圈圈",
        "電視一直轉圈圈",
        "一直出現異常訊息",
    ])


def is_tv_black_screen_issue(text: str) -> bool:
    value = text or ""
    return contains_any(value, [
        "有聲音沒畫面",
        "有聲音沒有畫面",
        "只有黑畫面",
        "無畫面",
        "沒有畫面",
        "沒畫面",
        "沒看到畫面",
        "看不到畫面",
        "畫面黑",
        "黑畫面",
        "黑色畫面",
        "黑屏",
        "螢幕沒有畫面",
        "畫面全黑",
        "畫面不見",
    ])


def is_tv_color_abnormal_issue(text: str) -> bool:
    value = compact_text(text)
    has_screen = contains_any(value, ["畫面", "影像", "顏色", "色彩"])
    has_color_problem = contains_any(value, [
        "顏色錯誤",
        "顏色不對",
        "顏色異常",
        "色彩錯誤",
        "色彩不對",
        "色彩異常",
        "偏色",
    ])
    return has_screen and has_color_problem


def is_tv_equipment_boot_issue(text: str) -> bool:
    value = compact_text(text)
    has_box = contains_any(value, ["機上盒", "電視盒", "數位機上盒"])
    has_problem = contains_any(value, [
        "卡在",
        "停在",
        "打不開",
        "沒反應",
        "沒有反應",
        "死機",
        "當掉",
        "卡住",
        "跑不進去",
        "一直跑不進去",
        "不能進去",
        "進不去",
    ])
    return has_box and has_problem


def is_tv_boot_loop_reply(text: str) -> bool:
    """Recognize a boot-loop update while an active TV troubleshooting flow owns context."""
    value = compact_text(text)
    return contains_any(value, [
        "重複開機",
        "一直開機",
        "不停開機",
        "反覆開機",
        "開機中請稍後",
        "卡在開機",
        "停在開機",
    ])


def is_tv_no_program_display_issue(text: str) -> bool:
    value = compact_text(text)
    return is_tv_no_channel_issue(value) and contains_any(
        value,
        ["顯示", "畫面", "卡住", "停在"],
    )


def has_completed_channel_rescan(text: str) -> bool:
    return contains_any(
        compact_text(text),
        ["重搜後", "重搜完", "重搜完成", "已重搜", "恢復預設後", "恢復原廠後", "重設後"],
    )


def is_channel_viewing_abnormal_issue(text: str) -> bool:
    value = compact_text(text)
    return contains_any(value, [
        "頻道收視異常",
        "收視異常",
        "頻道異常",
        "頻道有問題",
        "頻道不能收視",
        "頻道無法收視",
        "頻道無法觀看",
        "頻道不能觀看",
    ])


def has_tv_power_known_on(text: str) -> bool:
    value = compact_text(text)
    return contains_any(value, [
        "有開",
        "有開機",
        "有電",
        "有亮",
        "有聲音",
        "電源有亮",
        "電源燈有亮",
        "機上盒有開",
        "電視有開",
    ])


def is_modem_light_abnormal_issue(text: str) -> bool:
    value = text or ""
    return contains_any(value, ["數據機", "modem", "Modem", "MODEM", "DS燈", "DS 燈", "ds燈", "ds 燈"]) and contains_any(
        value,
        ["紅燈", "亮紅", "閃紅", "沒亮", "不亮", "閃爍", "一直閃", "燈號異常", "異常閃爍"],
    )


def is_ds_light_status_question(text: str) -> bool:
    value = compact_text(text).lower()
    return contains_any(value, ["ds燈", "ds灯"]) and contains_any(value, ["閃", "正常", "怎麼", "什麼"])


def is_wifi_only_network_issue(text: str) -> bool:
    value = compact_text(text).lower()
    has_wifi_problem = contains_any(value, [
        "wifi不能用",
        "wi-fi不能用",
        "wifi連不上",
        "wi-fi連不上",
        "wifi沒網路",
        "wi-fi沒網路",
        "無線不能用",
        "無線網路不能用",
    ])
    wired_ok = contains_any(value, [
        "有線可以用",
        "網路線可以用",
        "插線可以用",
        "接線可以用",
        "電腦有線正常",
        "有線正常",
    ])
    return has_wifi_problem and wired_ok


def is_computer_only_network_issue(text: str) -> bool:
    value = compact_text(text)
    computer_problem = contains_any(value, ["電腦不能", "電腦無法", "電腦連不上", "電腦沒網路", "筆電不能", "筆電無法"])
    other_ok = contains_any(value, ["手機能上網", "手機可以上網", "手機正常", "其他正常", "其他可以"])
    return computer_problem and other_ok


def is_phone_only_network_issue(text: str) -> bool:
    value = compact_text(text)
    phone_problem = contains_any(value, ["手機不能", "手機無法", "手機連不上", "手機沒網路", "平板不能", "平板無法"])
    other_ok = contains_any(value, ["電腦能上網", "電腦可以上網", "電腦正常", "其他正常", "其他可以"])
    return phone_problem and other_ok


def is_tv_authorization_expired_issue(text: str) -> bool:
    return contains_any(text or "", ["授權到期", "收視授權到期", "授權逾期"])


def is_tv_unauthorized_channel_issue(text: str) -> bool:
    if is_tv_authorization_expired_issue(text):
        return False
    return contains_any(text or "", [
        "E004",
        "e004",
        "未授權",
        "無授權",
        "沒有授權",
        "未收權",
        "未受權",
    ])


def parse_troubleshooting_context(text: str) -> Dict[str, Any]:
    value = text or ""
    compact = compact_text(value)
    context: Dict[str, Any] = {}
    has_network_context = contains_any(value, [
        "網路",
        "寬頻",
        "光纖",
        "上網",
        "連線",
        "線路",
        "wifi",
        "Wi-Fi",
        "WIFI",
        "wi-fi",
        "數據機",
        "分享器",
    ])
    has_tv_context = contains_any(value, ["有線電視", "第四台", "電視", "機上盒", "頻道", "哈TV", "哈tv", "HATV", "hatv"])
    prefer_network_context = has_network_context and not has_tv_context

    if is_restricted_channel_purchase_request(value):
        return context

    if is_tv_authorization_expired_issue(value) and not prefer_network_context:
        context.update({"service_type": "tv", "symptom_type": "authorization_expired"})
    elif is_tv_unauthorized_channel_issue(value) and not prefer_network_context:
        context.update({"service_type": "tv", "symptom_type": "unauthorized_channel"})
    elif is_no_signal_issue(value) and not prefer_network_context:
        context.update({"service_type": "tv", "symptom_type": "no_signal"})
    elif is_partial_channel_issue(value) and not prefer_network_context:
        context.update({"service_type": "tv", "symptom_type": "partial_channels", "affected_scope": "partial_channels"})
    elif (is_tv_no_channel_issue(value) or is_channel_viewing_abnormal_issue(value)) and not prefer_network_context:
        context.update({"service_type": "tv", "symptom_type": "no_channels"})
    elif is_tv_black_screen_issue(value) and not prefer_network_context:
        context.update({"service_type": "tv", "symptom_type": "black_screen"})
    elif is_tv_equipment_boot_issue(value) and not prefer_network_context:
        context.update({"service_type": "tv", "symptom_type": "set_top_box_boot"})
    elif is_tv_screen_freeze_issue(value) and not prefer_network_context:
        context.update({"service_type": "tv", "symptom_type": "screen_freeze"})
    elif is_tv_color_abnormal_issue(value) and not prefer_network_context:
        context.update({"service_type": "tv", "symptom_type": "picture_quality"})
    elif has_tv_context and contains_any(value, ["沒聲音", "沒有聲音", "無聲音", "没聲音", "没有聲音", "聲音出不來"]) and not prefer_network_context:
        context.update({"service_type": "tv", "symptom_type": "sound_issue"})
    elif contains_any(value, ["畫面出現雪花", "畫面雪花", "畫面馬賽克", "馬賽克", "畫面很模糊"]) and not prefer_network_context:
        context.update({"service_type": "tv", "symptom_type": "picture_quality"})

    if context.get("service_type") == "tv" and has_tv_power_known_on(value):
        context["power_status"] = "on"

    if is_modem_light_abnormal_issue(value):
        context.update({
            "service_type": "network",
            "symptom_type": "modem_light_abnormal",
            "modem_light_status": "abnormal",
        })
    elif is_wifi_only_network_issue(value):
        context.update({"service_type": "network", "symptom_type": "wifi_only", "affected_scope": "wifi_only"})
    elif is_computer_only_network_issue(value):
        context.update({"service_type": "network", "symptom_type": "computer_only", "affected_scope": "single_device"})
    elif is_phone_only_network_issue(value):
        context.update({"service_type": "network", "symptom_type": "phone_only", "affected_scope": "single_device"})
    elif contains_any(compact, ["手機能上網電腦不能", "手機可以上網電腦不能"]):
        context.update({"service_type": "network", "symptom_type": "computer_only", "affected_scope": "single_device"})

    return context


def is_tv_fault(text: str) -> bool:
    value = text or ""
    if is_restricted_channel_purchase_request(value):
        return False
    has_network_context = contains_any(value, ["網路", "寬頻", "光纖", "上網", "wifi", "Wi-Fi", "WIFI", "wi-fi", "數據機", "分享器", "線路"])
    if parse_troubleshooting_context(value).get("service_type") == "tv":
        return True

    has_tv_context = contains_any(value, ["有線電視", "第四台", "電視", "機上盒", "頻道", "哈TV", "哈tv", "HATV", "hatv"])
    has_tv_outage_or_instability = contains_any(value, [
        "斷訊",
        "斷線",
        "中斷",
        "一直斷",
        "訊號不好",
        "訊號不佳",
        "訊號不良",
        "收訊不好",
        "收訊不佳",
        "收訊不良",
        "lag",
        "LAG",
        "卡卡",
        "不穩",
        "不能看",
        "沒聲音",
        "沒有聲音",
        "無聲音",
        "没聲音",
        "没有聲音",
        "無法看",
        "沒辦法看",
        "無法收看",
        "不能收看",
        "沒有第四台",
        "沒第四台",
        "無反應",
        "沒反應",
        "故障排除",
        "需要排除",
    ])
    if has_tv_context and has_tv_outage_or_instability:
        return True

    has_set_top_box_problem = contains_any(value, ["機上盒", "電視盒"]) and contains_any(value, [
        "故障",
        "壞",
        "不能用",
        "不能看",
        "無法",
        "沒反應",
        "沒亮",
        "不亮",
        "紅燈",
        "異常",
        "授權到期",
        "未授權",
        "錯誤代碼",
        "重開機",
        "死機",
        "當掉",
        "卡住",
        "跑不進去",
        "自己關機",
        "自已關機",
        "自己重開",
        "再開機",
        "自動關機",
        "排除",
    ])
    return (is_no_signal_issue(value) and not has_network_context) or has_set_top_box_problem or contains_any(value, [
        "電視不能看", "電視壞了", "第四台不能看",
        "電視沒辦法看", "電視無法看", "電視看不了",
        "無法收看", "不能收看", "沒辦法收看", "無法觀看", "不能觀看",
        "電視故障", "第四台故障", "電視不能用", "第四台不能用",
        "電視沒聲音", "電視沒有聲音", "哈tv沒有聲音", "哈tv没聲音",
        "電視完全斷訊", "第四台完全斷訊", "有線電視完全斷訊",
        "不能看",
        "無畫面", "沒有畫面", "沒畫面", "黑畫面",
        "沒看到畫面", "看不到畫面", "畫面黑", "黑屏",
        "沒頻道", "沒有頻道", "頻道看不到", "頻道不能看", "收不到頻道", "頻道都不見了",
        "訊號源",
        "訊號不佳", "訊號不良", "訊號不好", "收訊不佳", "收訊不良", "收訊不好",
        "機上盒排除",
        "授權到期", "未授權", "不能轉台",
        "錯誤代碼", "畫面停住", "畫面停頓", "播放停頓", "播出停頓",
        "播一播停", "播一播會停", "突然停頓", "突然停住", "累格", "類格",
        "畫面卡住", "畫面卡卡", "畫面定格", "畫面閃爍", "畫面出現雪花",
        "馬賽克",
        "電視很不清", "電視不清", "畫面不清", "畫面模糊",
        "有畫面但是會lag", "有畫面會lag", "畫面會lag", "電視會lag",
    ])


def is_combined_tv_network_fault(text: str) -> bool:
    return contains_any(text, [
        "電視跟網路都不能用",
        "電視和網路都不能用",
        "第四台跟網路都不能用",
        "電視跟網路都沒有訊號",
        "電視和網路都沒有訊號",
        "電視跟網路都沒訊號",
        "電視和網路都沒訊號",
        "電視跟網路都沒有網路",
    ])


def is_network_fault(text: str) -> bool:
    if is_combined_tv_network_fault(text):
        return True
    if parse_troubleshooting_context(text).get("service_type") == "network":
        return True

    if is_tv_fault(text) and not contains_any(text or "", ["網路", "寬頻", "光纖", "上網", "wifi", "Wi-Fi", "WIFI", "wi-fi", "數據機", "分享器"]):
        return False

    compact = (text or "").replace(" ", "").replace("　", "")
    has_speed_test_result = any(term in compact for term in ("測速", "測試")) and bool(
        re.search(r"\d+\s*(?:k|K|kbps|Kbps|KBPS|m|M|mbps|Mbps|MBPS)", text or "")
    )
    has_applied_speed = any(term in compact for term in ("申辦", "申請", "光纖", "寬頻", "網路", "1G", "1g", "100M", "300M", "500M"))
    if has_speed_test_result and has_applied_speed:
        return True

    if contains_any(text, ["網路", "連線", "網速"]) and contains_any(
        text,
        ["很慢", "慢", "lag", "LAG", "不順", "很爛", "爛", "很卡", "卡卡", "卡頓", "時有時無", "忽有忽無", "訊號不好", "訊號不穩", "訊號異常"],
    ):
        return True

    has_network_context = contains_any(text, [
        "網路", "寬頻", "光纖", "上網", "連線", "wifi", "wi-fi",
        "數據機", "分享器", "線路",
    ])
    has_network_outage = contains_any(text, [
        "斷訊", "斷線", "斷網", "中斷", "不通", "不能用", "無法使用",
        "不能上", "無法上", "連不上", "不能連線", "無連線", "未連線", "無訊號", "沒訊號", "沒有訊號",
    ])
    if has_network_context and has_network_outage:
        return True

    return contains_any(text, [
        "網路不能用", "不能上網", "網路壞了", "網路掛了", "斷線",
        "網路無訊號", "線路不通",
        "斷網", "網路斷網", "網路斷訊", "寬頻網路斷訊",
        "網路中斷", "光纖網路中斷",
        "無法連線", "無法連網", "不能連線", "無連線", "網路無連線", "網路不能連線", "未連線", "網路未連線",
        "網路有問題", "寬頻有問題", "網路故障", "寬頻故障",
        "wifi不能用", "wi-fi不能用", "wifi 不能用",
        "wifi壞了", "wifi斷線", "wi-fi斷線",
        "網路斷掉", "網路不通", "上不了網",
        "無法上網", "網路異常",
        "網路不穩", "網路不穩定", "網路連線不穩", "網路連線不穩定",
        "網路不太穩", "網路為什麼不太穩",
        "網路不順", "網路很爛", "網路爛", "網路很卡", "網路卡卡", "網路卡頓", "連線卡頓", "上網卡頓",
        "網路訊號不好", "網路訊號不穩", "網路訊號異常",
        "連線不穩", "連線不穩定", "斷斷續續", "一直斷",
        "網路很慢", "網速很慢", "連線很慢", "速度很慢", "網路慢", "網速慢", "連度很慢",
        "連不上網", "沒網路", "沒有網路", "完全沒網路", "完全沒有網路",
        "沒有連線", "沒連線", "網路沒有連線", "網路沒連線",
        "無網路進來", "沒有網路進來", "網路沒進來", "網路進不來",
        "網路斷了", "網路怪怪的",
        "數據機", "分享器"
    ])


def detect_troubleshooting_type(text: str) -> str | None:
    if is_remote_control_issue(text):
        return "remote"

    if is_network_slow_issue(text) and contains_any(text or "", ["網路", "網速", "速度", "連線"]):
        return "network"

    if (
        contains_any(text or "", ["網路", "寬頻", "光纖", "上網", "wifi", "wi-fi", "數據機", "分享器"])
        and is_network_fault(text)
    ):
        return "network"

    if is_tv_fault(text) and not is_combined_tv_network_fault(text):
        return "tv"

    if is_network_fault(text):
        return "network"

    if is_tv_fault(text):
        return "tv"

    return None


def detect_fault_category_selection(text: str) -> str | None:
    value = (text or "").strip()
    if not value:
        return None

    compact = value.replace(" ", "").replace("　", "").lower()
    remote_terms = ["遙控器", "遙控", "搖控器", "搖控"]
    network_terms = ["網路", "寬頻", "wifi", "wi-fi", "上網", "數據機", "分享器"]
    tv_terms = ["電視", "第四台", "有線電視", "頻道", "機上盒", "數位機上盒"]
    if compact.startswith(("不是", "非")) and not contains_any(compact, [
        "是電視",
        "是第四台",
        "是有線電視",
        "是網路",
        "是寬頻",
        "是wifi",
        "是wi-fi",
        "是遙控",
        "是搖控",
        "是機上盒",
    ]):
        return None

    if contains_any(compact, remote_terms):
        return "remote"

    has_network = contains_any(compact, network_terms)
    has_tv = contains_any(compact, tv_terms)

    if has_network and has_tv:
        return "network"
    if has_network:
        return "network"
    if has_tv:
        return "tv"

    return None


def build_fault_category_context_text(text: str, memory: Dict[str, Any]) -> str:
    known = memory.setdefault("known_info", {})
    issue_description = (known.get("issue_description") or "").strip()
    if issue_description and issue_description != text:
        return f"{issue_description} {text}".strip()
    return text


def start_troubleshooting_by_type(
    troubleshooting_type: str,
    user_text: str,
    memory: Dict[str, Any],
    plan: Dict[str, Any],
) -> Dict[str, Any]:
    if troubleshooting_type == "network":
        return start_network_troubleshooting(user_text, memory, plan)
    if troubleshooting_type == "remote":
        return start_remote_control_troubleshooting(user_text, memory, plan)
    return start_tv_troubleshooting(user_text, memory, plan)


def switch_to_repair(
    memory: Dict[str, Any],
    plan: Dict[str, Any],
    reply: str = "",
) -> Dict[str, Any]:
    known = memory.setdefault("known_info", {})

    known["troubleshooting_started"] = "no"
    known["troubleshooting_failed"] = "yes"
    known["repair_ready"] = "yes"

    plan["intent"] = "human_handoff_offer"
    plan["decision_type"] = "clarify"
    plan["reply"] = reply or (
        "了解，前面的排除步驟完成後仍無法恢復。"
        "請問是否需要幫您轉接真人文字客服協助後續處理？"
    )
    plan["should_call_tool"] = False
    plan["tool_name"] = None

    return plan


def start_set_top_box_network_troubleshooting(
    user_text: str,
    memory: Dict[str, Any],
    plan: Dict[str, Any],
) -> Dict[str, Any]:
    """Start a device-scoped flow without treating home broadband as down."""
    known = memory.setdefault("known_info", {})
    known["troubleshooting_started"] = "yes"
    known["troubleshooting_type"] = "set_top_box_network"
    known["troubleshooting_step"] = (
        "stb_app_connectivity_check"
        if plan.get("intent") == "tv_set_top_box_app_network_issue"
        else "stb_network_check"
    )
    known["troubleshooting_failed"] = "no"
    known["repair_ready"] = "no"
    known["issue_description"] = user_text
    known["retry"] = 0

    if known["troubleshooting_step"] == "stb_app_connectivity_check":
        plan["reply"] = (
            "Wi-Fi 顯示訊號正常但應用程式無法連線時，請先在機上盒的網路設定中"
            "將目前 Wi-Fi 中斷後重新連線，再將機上盒電源拔除約 10 秒後重新啟動。"
            "完成後請測試另一個需要網路的應用程式，確認是單一應用程式還是所有聯網功能都無法使用。"
        )
    else:
        plan["reply"] = (
            "請先確認家中手機或電腦是否可以正常上網。若其他裝置正常，問題較可能集中在機上盒：\n"
            "1. 到機上盒的網路設定確認已連上正確的 Wi-Fi，使用網路線時則確認兩端插緊。\n"
            "2. 將機上盒電源拔除約 10 秒後重新啟動。\n"
            "3. 重新連線後測試另一個需要網路的應用程式。\n"
            "完成後請告訴我是單一應用程式，還是機上盒所有聯網功能都無法使用。"
        )
    plan["should_call_tool"] = False
    plan["tool_name"] = None
    return plan


def continue_set_top_box_network_troubleshooting(
    user_text: str,
    memory: Dict[str, Any],
    plan: Dict[str, Any],
    llm=None,
) -> Dict[str, Any]:
    known = memory.setdefault("known_info", {})

    if known.get("repair_ready") == "yes" or known.get("repair_followup_active") == "yes":
        return switch_to_repair(
            memory,
            plan,
            reply=(
                "已確認家中網路正常，問題仍集中在哈TV機上盒的聯網功能，"
                "不會再要求您重做一般數據機排錯。"
                "請問是否需要幫您轉接真人文字客服處理？"
            ),
        )

    step = str(known.get("troubleshooting_step") or "stb_network_check")
    label = classify_reply(
        user_text,
        step,
        issue_description=str(known.get("issue_description") or ""),
        llm=llm,
    )
    known["_llm_step_classifier_used"] = "yes" if llm is not None else "no"

    if label == "recovered":
        return finish_troubleshooting(memory, plan)
    if label == "refuse":
        known["issue_description"] = user_text
        return switch_to_repair(memory, plan)

    if (
        (
            plan.get("intent") == "tv_set_top_box_app_network_issue"
            or label == "app_connectivity_detail"
        )
        and step != "stb_app_connectivity_check"
    ):
        known["troubleshooting_step"] = "stb_app_connectivity_check"
        known["issue_description"] = user_text
        plan["reply"] = (
            "了解，訊號強度正常不代表機上盒的應用程式已成功連上網路。"
            "請先在機上盒網路設定中將 Wi-Fi 中斷後重新連線，再重開機上盒，"
            "並測試另一個需要網路的應用程式。若所有聯網功能仍無法使用，我會接續協助報修。"
        )
        plan["should_call_tool"] = False
        plan["tool_name"] = None
        return plan

    if label == "failed":
        known["issue_description"] = user_text
        return switch_to_repair(memory, plan)

    if plan.get("intent") == "tv_set_top_box_app_network_issue":
        plan["reply"] = (
            "請先將機上盒目前的 Wi-Fi 中斷後重新連線，再重開機上盒，"
            "並測試另一個需要網路的應用程式。若所有聯網功能仍無法使用，"
            "我會接續協助報修。"
        )
        plan["should_call_tool"] = False
        plan["tool_name"] = None
        return plan

    plan["reply"] = (
        "目前會繼續針對哈TV機上盒本身排除，不會改成一般寬頻斷線流程。"
        "請確認機上盒已重新連接 Wi-Fi 或網路線並重開機，接著測試另一個聯網應用程式；"
        "再告訴我是單一應用程式，還是所有聯網功能都無法使用。"
    )
    plan["should_call_tool"] = False
    plan["tool_name"] = None
    return plan


def start_router_path_troubleshooting(
    user_text: str,
    memory: Dict[str, Any],
    plan: Dict[str, Any],
) -> Dict[str, Any]:
    known = memory.setdefault("known_info", {})
    known["troubleshooting_started"] = "yes"
    known["troubleshooting_type"] = "network"
    known["troubleshooting_step"] = "net_router_path_check"
    known["troubleshooting_failed"] = "no"
    known["repair_ready"] = "no"
    known["issue_description"] = user_text
    known["retry"] = 0
    plan["reply"] = (
        "若只有經過路由器時速度變慢，請先比較電腦直接用網路線連接數據機，"
        "以及經路由器連線時的測速結果。也請確認：\n"
        "1. 路由器未啟用 QoS、流量控制或家長監護限速。\n"
        "2. 無線裝置改連 5 GHz 頻段測試。\n"
        "3. 路由器 WAN／LAN 埠與網路線支援 Gigabit（1000 Mbps）。\n"
        "可使用 https://www.tinp.net.tw/ 的「網速推薦工具」進行測速。"
        "若直連數據機正常、經路由器才慢，通常需調整路由器設定或由設備原廠協助。"
    )
    plan["should_call_tool"] = False
    plan["tool_name"] = None
    return plan


def continue_router_path_troubleshooting(
    user_text: str,
    memory: Dict[str, Any],
    plan: Dict[str, Any],
    llm=None,
) -> Dict[str, Any]:
    known = memory.setdefault("known_info", {})
    label = classify_reply(
        user_text,
        "net_router_path_check",
        issue_description=str(known.get("issue_description") or ""),
        llm=llm,
    )
    known["_llm_step_classifier_used"] = "yes" if llm is not None else "no"
    if label == "recovered":
        return finish_troubleshooting(memory, plan)
    if label == "refuse":
        return switch_to_repair(memory, plan)
    if label == "failed":
        failed_count = int(known.get("router_path_failed_count") or 0) + 1
        known["router_path_failed_count"] = failed_count
        if failed_count >= 2:
            return switch_to_repair(memory, plan)

    known["retry"] = int(known.get("retry") or 0) + 1
    plan["reply"] = (
        "請回覆兩個測速結果：電腦直連數據機的速度，以及經路由器連線的速度。"
        "若直連正常、經路由器才慢，可優先關閉 QoS／家長監護限速、改用 5 GHz，"
        "並確認埠口與網路線支援 Gigabit；仍未改善時再由路由器原廠協助檢查設定。"
    )
    plan["should_call_tool"] = False
    plan["tool_name"] = None
    return plan


def is_direct_fault_report(text: str) -> bool:
    value = (text or "").strip()
    return value in {
        "故障",
        "報故障",
        "報修",
        "維修",
        "線上報修",
        "我要報修",
        "我要維修",
        "回報故障",
        "回傳故障",
        "我要回報故障",
        "故障報修",
    }


def is_explicit_repair_request(text: str) -> bool:
    return contains_any(text or "", [
        "報故障",
        "報修",
        "回報故障",
        "建立工單",
        "派人",
        "派工",
        "請人來修",
    ])


def is_explicit_repair_handoff_request(text: str) -> bool:
    """Return true only for a clear request to start repair after diagnosis."""
    value = (text or "").strip().replace(" ", "").replace("　", "")
    return value in {
        "報修",
        "維修",
        "線上報修",
        "我要報修",
        "我要維修",
        "我要線上報修",
        "建立工單",
        "請人來修",
        "請派人",
        "派工",
    }


def ask_fault_category(memory: Dict[str, Any], plan: Dict[str, Any]) -> Dict[str, Any]:
    known = memory.setdefault("known_info", {})
    known["troubleshooting_started"] = "yes"
    known["troubleshooting_type"] = "unknown"
    known["troubleshooting_step"] = "ask_fault_category"
    known["troubleshooting_failed"] = "no"
    known["repair_ready"] = "no"
    known["retry"] = 0

    plan["reply"] = (
        "請問目前遇到的是電視、網路，還是其他設備問題？"
        "也可以直接描述狀況，例如：訊號不良、完全斷線、網速變慢、遊戲爆 ping、畫面 lag。"
    )
    plan["should_call_tool"] = False
    plan["tool_name"] = None
    return plan


def reset_to_fault_category(memory: Dict[str, Any], plan: Dict[str, Any], prefix: str = "沒問題，我們重新確認一次。") -> Dict[str, Any]:
    known = memory.setdefault("known_info", {})
    known["troubleshooting_started"] = "yes"
    known["troubleshooting_type"] = "unknown"
    known["troubleshooting_step"] = "ask_fault_category"
    known["troubleshooting_failed"] = "no"
    known["repair_ready"] = "no"
    known["retry"] = 0
    known["category_retry"] = 0
    known["unexpected_reply_count"] = 0

    plan["reply"] = (
        f"{prefix}\n"
        "請問目前主要是電視、網路，還是遙控器/機上盒等設備問題？"
        "您也可以直接描述現在看到的畫面或網路狀況。"
    )
    plan["should_call_tool"] = False
    plan["tool_name"] = None
    return plan


def is_network_slow_issue(text: str) -> bool:
    value = text or ""
    compact = value.replace(" ", "").replace("　", "")
    if any(term in compact for term in ("測速", "測試")) and re.search(r"\d+\s*(?:k|K|kbps|Kbps|KBPS|m|M|mbps|Mbps|MBPS)", value):
        return True
    if re.search(r"\d+\s*(?:k|K|kbps|Kbps|KBPS)", value) and contains_any(value, ["網路", "網速", "速度", "連線"]):
        return True
    return contains_any(value, [
        "網路很慢", "網速很慢", "連線很慢", "速度很慢",
        "網路慢", "網速慢", "很慢", "lag", "LAG",
        "網路卡頓", "連線卡頓", "上網卡頓",
        "變慢", "轉圈圈", "一直轉圈", "影片轉圈", "影片一直轉",
        "影片一直轉圈圈",
    ])


def is_network_unstable_issue(text: str) -> bool:
    return contains_any(text or "", [
        "不穩",
        "訊號不好",
        "不太穩",
        "不穩定",
        "斷線",
        "斷掉",
        "斷斷續續",
        "時有時無",
        "忽有忽無",
        "一下有一下沒有",
        "一直斷",
        "會斷",
        "網路飄",
        "連線中斷",
        "沒恢復",
        "沒有恢復",
        "一樣",
    ])


def is_internet_available_but_unstable_issue(text: str) -> bool:
    value = text or ""
    return (
        is_network_unstable_issue(value)
        and contains_any(value, ["能上網", "可以上網", "能連", "可以連", "不是不能上網"])
    )


def is_game_or_app_network_issue(text: str) -> bool:
    return contains_any(text or "", [
        "遊戲",
        "手遊",
        "線上遊戲",
        "爆ping",
        "爆 ping",
        "ping",
        "影片",
        "app",
        "APP",
    ])


def is_specific_service_unstable_issue(text: str) -> bool:
    value = text or ""
    return is_game_or_app_network_issue(value) and (
        is_network_unstable_issue(value)
        or contains_any(value, ["爆ping", "爆 ping", "lag", "LAG", "延遲"])
    )


def is_multi_device_network_issue(text: str) -> bool:
    value = text or ""
    has_phone = contains_any(value, ["手機", "手遊", "平板"])
    has_computer = contains_any(value, ["電腦", "筆電", "桌機", "網路線", "插線", "有線"])
    has_multi_marker = contains_any(value, ["全部", "所有", "都", "也", "一樣", "同時", "多台", "每台"])
    has_problem = (
        is_network_unstable_issue(value)
        or is_failed_reply(value)
        or contains_any(value, ["不能上網", "無法上網", "沒網路", "沒有網路", "連不上"])
    )
    return has_problem and ((has_phone and has_computer) or has_multi_marker)


def is_line_level_network_outage(text: str) -> bool:
    value = (text or "").replace(" ", "").replace("　", "")
    if not value:
        return False

    has_line_signal = contains_any(value, [
        "光纖網路中斷",
        "光纖中斷",
        "線路中斷",
        "網路中斷",
        "斷線",
        "無網路進來",
        "沒網路進來",
        "網路進不來",
    ])
    has_wired_test = contains_any(value, [
        "插網路線到電腦",
        "接網路線到電腦",
        "網路線到電腦",
        "電腦接網路線",
        "有線測試",
        "網路線測試",
    ])
    has_no_network = contains_any(value, [
        "無網路",
        "沒網路",
        "不能上網",
        "無法上網",
        "連不上網",
    ])
    return has_line_signal or (has_wired_test and has_no_network)


def is_floor_after_install_network_issue(text: str) -> bool:
    value = (text or "").replace(" ", "").replace("　", "")
    if not value:
        return False
    has_floor = bool(re.search(r"\d+樓", value)) or contains_any(
        value,
        [
            "一樓", "二樓", "三樓", "四樓", "五樓", "六樓",
            "七樓", "八樓", "九樓", "十樓", "樓上", "樓下", "地下室",
        ],
    )
    has_install_context = contains_any(
        value,
        ["今天安裝", "剛安裝", "新安裝", "剛申辦", "新申辦", "裝好", "安裝後"],
    )
    has_network_problem = contains_any(
        value,
        [
            "沒網路",
            "無網路",
            "不能上網",
            "無法上網",
            "網路不通",
            "無法使用手機視訊",
            "不能使用手機視訊",
            "手機視訊不能用",
            "視訊不能用",
        ],
    )
    return has_floor and has_install_context and has_network_problem


def move_to_modem_light_check(memory: Dict[str, Any], plan: Dict[str, Any], issue_description: str) -> Dict[str, Any]:
    known = memory.setdefault("known_info", {})
    known["affected_scope"] = "multiple_devices"
    known["issue_description"] = issue_description
    known["troubleshooting_step"] = "net_check_modem_light"
    known["retry"] = 0
    plan["reply"] = (
        "了解，手機與電腦都出現網路不穩時，先以數據機或線路狀況確認。"
        "請幫我看一下數據機目前燈號是否有亮紅燈、閃爍異常，或完全沒亮燈？"
    )
    plan["should_call_tool"] = False
    plan["tool_name"] = None
    return plan


def start_wifi_only_troubleshooting(user_text: str, memory: Dict[str, Any], plan: Dict[str, Any]) -> Dict[str, Any]:
    known = memory.setdefault("known_info", {})
    known["affected_scope"] = "wifi_only"
    known["issue_description"] = user_text or "有線網路可用但 Wi-Fi 無法使用"
    known["troubleshooting_step"] = "net_single_device"
    known["retry"] = 0
    plan["reply"] = (
        "了解，有線網路可以用但 Wi-Fi 不能用時，先以 Wi-Fi 或分享器方向確認。"
        "請先確認手機/電腦是否連到正確 Wi-Fi，並將分享器電源拔掉約 10 秒後重新插上，"
        "等待 2 到 3 分鐘後再試一次。完成後請告訴我 Wi-Fi 是否恢復。"
    )
    plan["should_call_tool"] = False
    plan["tool_name"] = None
    return plan


def start_computer_only_troubleshooting(user_text: str, memory: Dict[str, Any], plan: Dict[str, Any]) -> Dict[str, Any]:
    known = memory.setdefault("known_info", {})
    known["affected_scope"] = "single_device"
    known["issue_description"] = user_text or "單一電腦無法上網"
    known["troubleshooting_step"] = "net_computer_connection_type"
    known["retry"] = 0
    plan["reply"] = "了解，手機可以上網但電腦不能上網，先以單一電腦連線確認。請問電腦是透過 Wi-Fi 連線，還是接實體網路線？"
    plan["should_call_tool"] = False
    plan["tool_name"] = None
    return plan


def start_phone_only_troubleshooting(user_text: str, memory: Dict[str, Any], plan: Dict[str, Any]) -> Dict[str, Any]:
    known = memory.setdefault("known_info", {})
    known["affected_scope"] = "single_device"
    known["issue_description"] = user_text or "單一手機無法上網"
    known["troubleshooting_step"] = "net_phone_connection_type"
    known["retry"] = 0
    plan["reply"] = "了解，只有手機不能上網時，先確認手機目前是連家中 Wi-Fi，還是使用門號的 4G/5G 行動網路？"
    plan["should_call_tool"] = False
    plan["tool_name"] = None
    return plan


def build_network_unstable_reply(memory: Dict[str, Any], plan: Dict[str, Any]) -> Dict[str, Any]:
    known = memory.setdefault("known_info", {})
    known["troubleshooting_started"] = "yes"
    known["troubleshooting_type"] = "network"
    known["troubleshooting_step"] = "net_unstable_scope"
    known["troubleshooting_failed"] = "no"
    known["repair_ready"] = "no"
    known["retry"] = 0
    known["issue_description"] = known.get("issue_description") or "網路連線不穩"

    plan["reply"] = (
        "網路連線不穩時，我們先確認影響範圍。\n"
        "請問是所有網站、APP 都會不穩或斷線，還是只有玩遊戲、看影片或特定 APP 時才會發生？"
        "如果手機 Wi-Fi 和電腦接網路線都會不穩，也可以直接告訴我。"
    )
    plan["should_call_tool"] = False
    plan["tool_name"] = None
    return plan


def build_network_slow_reply(memory: Dict[str, Any], plan: Dict[str, Any]) -> Dict[str, Any]:
    known = memory.setdefault("known_info", {})
    known["troubleshooting_started"] = "yes"
    known["troubleshooting_type"] = "network"
    known["troubleshooting_step"] = "net_slow_scope"
    known["troubleshooting_failed"] = "no"
    known["repair_ready"] = "no"
    known["retry"] = 0
    known["issue_description"] = known.get("issue_description") or "網路速度慢"

    if has_high_risk_modem_instability_context(memory):
        known["issue_description"] = (
            "舊款或發熱數據機長期網路不穩，需由客服確認設備與線路狀態"
        )
        return switch_to_repair(memory, plan)

    declared, measured = record_declared_speed_gap(
        known,
        known.get("issue_description", ""),
    )
    if is_substantially_below_declared_speed(declared, measured):
        known["troubleshooting_step"] = "net_speed_retest"
        known["speed_retest_requested"] = "yes"
        return_reply = build_declared_speed_retest_reply(declared, measured)
        plan["reply"] = return_reply
        plan["should_call_tool"] = False
        plan["tool_name"] = None
        return plan

    plan["reply"] = (
        "了解，這是網速變慢，不是完全無法上網，我們先用測速確認。\n\n"
        "1. 請先重新啟動數據機及分享器，等待約 2 分鐘後再測試。\n"
        "2. 若方便，請讓電腦直接以網路線連接數據機或分享器，不透過 Wi-Fi，再到 www.speedtest.net 測速。\n"
        "3. 請回覆申辦速率，以及測得的下載與上傳速度；若有線單機測速仍明顯低於申辦速率，"
        "我會接續安排後續檢查。"
    )
    plan["should_call_tool"] = False
    plan["tool_name"] = None
    return plan


def is_set_top_box_power_cycle_issue(text: str) -> bool:
    value = text or ""
    return contains_any(value, ["機上盒"]) and contains_any(
        value,
        ["自己關機", "自已關機", "自動關機", "一直重開", "自己重開"],
    )


def is_tv_authorization_issue(text: str) -> bool:
    if is_restricted_channel_purchase_request(text):
        return False
    return is_tv_authorization_expired_issue(text) or is_tv_unauthorized_channel_issue(text)


def reply_tv_unauthorized_channel_check(memory: Dict[str, Any], plan: Dict[str, Any]) -> Dict[str, Any]:
    known = memory.setdefault("known_info", {})
    known["troubleshooting_started"] = "no"
    known["troubleshooting_failed"] = "no"
    known["repair_ready"] = "no"
    known["symptom_type"] = "unauthorized_channel"
    known["troubleshooting_step"] = "unauthorized_channel_check"
    plan["reply"] = (
        "畫面顯示未授權時，請先確認是否誤切到加購或付費頻道，也可能是 200 頻道以上的頻道。"
        "請先切到 200 頻道以下的一般基本頻道確認是否可以收看。"
        "如果一般基本頻道也顯示未授權，再請客服協助確認授權狀態。"
    )
    plan["should_call_tool"] = False
    plan["tool_name"] = None
    return plan


def reply_tv_authorization_payment(memory: Dict[str, Any], plan: Dict[str, Any]) -> Dict[str, Any]:
    known = memory.setdefault("known_info", {})
    known["troubleshooting_started"] = "no"
    known["troubleshooting_failed"] = "no"
    known["repair_ready"] = "no"
    known["symptom_type"] = "authorization_expired"
    known["troubleshooting_step"] = "authorization_payment"
    plan["reply"] = (
        "畫面顯示授權到期時，請先確認收視費或相關帳單是否已完成繳費。"
        "若已繳費但仍顯示授權到期，可能需要確認入帳與收視授權狀態，建議由真人客服協助核對。"
    )
    plan["should_call_tool"] = False
    plan["tool_name"] = None
    return plan


def is_tv_signal_or_playback_issue(text: str) -> bool:
    return contains_any(text or "", [
        "斷訊",
        "一直斷",
        "中斷",
        "看到一半會中斷",
        "播到一半中斷",
        "訊號不良",
        "訊號不好",
        "收訊不良",
        "收訊不好",
        "畫面停頓",
        "播放停頓",
        "播出停頓",
        "播一播停",
        "播一播會停",
        "突然停頓",
        "突然停住",
        "累格",
        "類格",
    ])


def is_all_channel_unavailable_issue(text: str) -> bool:
    value = text or ""
    has_all_channels = contains_any(value, ["全部頻道", "所有頻道", "全頻道", "每一台", "每個頻道"])
    has_unavailable = contains_any(value, ["無法收視", "無法收看", "不能看", "不能收看", "看不到", "沒有畫面", "黑畫面"])
    return has_all_channels and has_unavailable


def has_described_tv_screen_issue(text: str) -> bool:
    value = text or ""
    if not value:
        return False

    if is_no_signal_issue(value) or is_tv_authorization_issue(value):
        return True

    screen_context = contains_any(value, [
        "畫面",
        "螢幕",
        "屏幕",
        "電視上",
        "出現",
        "顯示",
        "跳出",
        "跳掉",
        "停在",
        "卡在",
        "黑屏",
        "藍屏",
        "花屏",
        "雪花",
        "馬賽克",
        "模糊",
    ])
    problem_context = contains_any(value, [
        "不能看",
        "無法看",
        "沒辦法看",
        "無法收看",
        "不能收看",
        "看不到",
        "故障",
        "異常",
        "錯誤",
        "代碼",
        "停住",
        "停頓",
        "lag",
        "LAG",
        "轉圈",
        "顏色",
        "色彩",
        "不清",
        "不清楚",
        "不正常",
        "跑不出來",
    ])
    return screen_context and problem_context


def continue_tv_after_power_confirmed_from_description(
    memory: Dict[str, Any],
    plan: Dict[str, Any],
    prefix: str = "了解，機上盒電源有亮。",
) -> Dict[str, Any] | None:
    known = memory.setdefault("known_info", {})
    issue_description = (known.get("issue_description") or "").strip()
    if not has_described_tv_screen_issue(issue_description):
        return None

    if is_no_signal_issue(issue_description):
        known["issue_description"] = "電視畫面顯示無訊號"
        known["troubleshooting_step"] = "tv_check_input_source"
        known["retry"] = 0
        plan["reply"] = (
            f"{prefix}畫面顯示無訊號時，請先確認電視訊號源是否切到正確的 HDMI 或 AV。"
            "您可以用電視遙控器按「訊號源 / Input / Source」切換看看。"
            "切換後請回覆我畫面是否恢復。"
        )
        plan["should_call_tool"] = False
        plan["tool_name"] = None
        return plan

    if is_tv_authorization_issue(issue_description):
        if is_tv_authorization_expired_issue(issue_description):
            return reply_tv_authorization_payment(memory, plan)
        return reply_tv_unauthorized_channel_check(memory, plan)

    if is_partial_channel_issue(issue_description):
        known["troubleshooting_step"] = "tv_rescan_channels"
        known["retry"] = 0
        plan["reply"] = build_channel_rescan_reply()
        plan["should_call_tool"] = False
        plan["tool_name"] = None
        return plan

    known["troubleshooting_step"] = "tv_reboot"
    known["retry"] = 0
    plan["reply"] = (
        f"{prefix}我先依您前面描述的畫面狀況做下一步排除："
        "請將機上盒電源拔掉約 10 秒後重新插上，等待 2 到 3 分鐘後，再確認畫面是否恢復。"
    )
    plan["should_call_tool"] = False
    plan["tool_name"] = None
    return plan


def finish_troubleshooting(memory: Dict[str, Any], plan: Dict[str, Any]) -> Dict[str, Any]:
    known = memory.setdefault("known_info", {})

    known["troubleshooting_started"] = "no"
    known["troubleshooting_failed"] = "no"
    known["repair_ready"] = "no"
    known["troubleshooting_step"] = "resolved"

    plan["reply"] = "太好了，已恢復正常。若後續還有狀況，隨時再告訴我。"
    plan["should_call_tool"] = False
    plan["tool_name"] = None

    return plan


def stop_troubleshooting(memory: Dict[str, Any], plan: Dict[str, Any]) -> Dict[str, Any]:
    known = memory.setdefault("known_info", {})

    known["troubleshooting_started"] = "no"
    known["troubleshooting_failed"] = "no"
    known["repair_ready"] = "no"
    known["troubleshooting_step"] = "cancelled"

    plan["reply"] = "好的，已停止這次排錯，也不會建立報修。之後若仍需要協助，再告訴我即可。"
    plan["should_call_tool"] = False
    plan["tool_name"] = None

    return plan


def start_tv_troubleshooting(user_text: str, memory: Dict[str, Any], plan: Dict[str, Any]) -> Dict[str, Any]:
    known = memory.setdefault("known_info", {})
    context = parse_troubleshooting_context(user_text)

    known["troubleshooting_started"] = "yes"
    known["troubleshooting_type"] = "tv"
    known["troubleshooting_failed"] = "no"
    known["repair_ready"] = "no"
    known["retry"] = 0

    if not known.get("issue_description"):
        known["issue_description"] = user_text

    if context.get("symptom_type"):
        known["symptom_type"] = context["symptom_type"]
    if context.get("affected_scope"):
        known["affected_scope"] = context["affected_scope"]
    if context.get("power_status"):
        known["power_status"] = context["power_status"]

    if (
        known.get("power_status") == "off"
        and contains_any(user_text, ["機上盒", "電視", "第四台"])
    ):
        known["troubleshooting_step"] = "tv_check_power_cable"
        known["retry"] = 0
        plan["reply"] = (
            "了解，機上盒已插電但沒有亮燈。"
            "請先確認機上盒電源線與插座是否插緊，也可換另一個確認有電的插座測試。"
            "確認後再看看機上盒電源燈是否恢復亮起。"
        )
        plan["should_call_tool"] = False
        plan["tool_name"] = None
        return plan

    if context.get("symptom_type") == "authorization_expired":
        return reply_tv_authorization_payment(memory, plan)

    if context.get("symptom_type") == "unauthorized_channel":
        return reply_tv_unauthorized_channel_check(memory, plan)

    if context.get("symptom_type") == "partial_channels":
        known["troubleshooting_step"] = "tv_rescan_channels"
        plan["reply"] = build_channel_rescan_reply()
        plan["should_call_tool"] = False
        plan["tool_name"] = None
        return plan

    if context.get("symptom_type") == "no_channels":
        known["troubleshooting_step"] = "tv_rescan_channels"
        known["affected_scope"] = known.get("affected_scope") or "all_or_unknown_channels"
        plan["reply"] = (
            "了解，頻道收視異常時，先嘗試恢復原廠預設或重新搜頻。\n\n"
            f"{build_channel_rescan_reply()}"
        )
        plan["should_call_tool"] = False
        plan["tool_name"] = None
        return plan

    if context.get("symptom_type") == "picture_quality":
        known["troubleshooting_step"] = "tv_rescan_channels"
        plan["reply"] = (
            "了解，畫面顏色或影像異常時，先嘗試恢復原廠預設或重新搜頻。\n\n"
            f"{build_channel_rescan_reply()}"
        )
        plan["should_call_tool"] = False
        plan["tool_name"] = None
        return plan

    if context.get("symptom_type") == "sound_issue":
        known["troubleshooting_step"] = "tv_check_sound"
        plan["reply"] = (
            "了解，電視或數位機上盒沒有聲音時，請先確認兩邊都沒有開啟靜音，並將音量調高。"
            "接著確認 HDMI 或 AV 的音訊線路是否插緊；若仍沒有聲音，請將機上盒電源拔掉約 10 秒後重新插上，"
            "等待 2 到 3 分鐘後再確認。"
        )
        plan["should_call_tool"] = False
        plan["tool_name"] = None
        return plan

    if context.get("symptom_type") == "black_screen":
        known["troubleshooting_step"] = "tv_check_input_source"
        plan["reply"] = (
            "無畫面時，請先確認電視訊號源是否切到機上盒連接的 HDMI 或 AV。"
            "如果訊號源正確但仍無畫面，請將機上盒電源拔掉約 10 秒後重新插上，"
            "等待 2 到 3 分鐘後再確認畫面是否恢復。"
        )
        plan["should_call_tool"] = False
        plan["tool_name"] = None
        return plan

    if context.get("symptom_type") in {"screen_freeze", "set_top_box_boot"}:
        known["troubleshooting_step"] = "tv_reboot"
        plan["reply"] = (
            "了解，依您描述的畫面或機上盒狀況，先做下一步排除："
            "請將機上盒電源拔掉約 10 秒後重新插上，等待 2 到 3 分鐘後，再確認畫面是否恢復。"
        )
        plan["should_call_tool"] = False
        plan["tool_name"] = None
        return plan

    if is_tv_signal_or_playback_issue(user_text):
        known["troubleshooting_step"] = "tv_reboot"
        known["awaiting_channel_scope_after_reboot"] = "yes"
        known["issue_description"] = user_text or "電視收訊或播放不穩"
        plan["reply"] = (
            "了解，目前比較像是有線電視收訊或播放不穩。"
            "請先將機上盒電源拔掉約 10 秒後重新插上，等待 2 到 3 分鐘後再觀察。"
            "若仍會訊號不良或播放停頓，請再告訴我是單一頻道還是全部頻道都會發生，我再協助轉報修。"
        )
        plan["should_call_tool"] = False
        plan["tool_name"] = None
        return plan

    if contains_any(user_text, ["電視很不清", "電視不清", "畫面不清", "畫質不清", "畫面模糊", "馬賽克"]) or is_tv_color_abnormal_issue(user_text):
        known["troubleshooting_step"] = "tv_blurry_check_channel"
        plan["reply"] = (
            "電視畫面不清時，請先確認是第幾台，以及是單一頻道不清還是全部頻道都不清。"
            "您也可以先將機上盒電源拔掉約 10 秒後重新插上，等待 2 到 3 分鐘再確認；"
            "若仍不清楚，請提供頻道號碼與是否所有頻道皆異常。"
        )
        plan["should_call_tool"] = False
        plan["tool_name"] = None
        return plan

    if contains_any(user_text, ["有畫面但是會lag", "有畫面會lag", "畫面會lag", "電視會lag", "有畫面但是會LAG"]):
        known["troubleshooting_step"] = "tv_lag_reboot"
        plan["reply"] = (
            "有畫面但會 lag 時，請先將機上盒電源拔掉約 10 秒後重新插上，等待 2 到 3 分鐘再確認。"
            "若仍會 lag，請再確認是單一頻道還是全部頻道、是否固定時段發生。"
        )
        plan["should_call_tool"] = False
        plan["tool_name"] = None
        return plan

    if is_all_channel_unavailable_issue(user_text):
        known["troubleshooting_step"] = "tv_reboot"
        known["issue_description"] = user_text or "全部頻道無法收視"
        plan["reply"] = (
            "了解，目前是全部頻道無法收視。"
            "請先將機上盒電源拔掉約 10 秒後重新插上，等待 2 到 3 分鐘後再確認是否恢復。"
            "若已重開仍無法收看，建議由真人客服協助確認訊號、帳務授權或安排維修。"
        )
        plan["should_call_tool"] = False
        plan["tool_name"] = None
        return plan

    if is_set_top_box_power_cycle_issue(user_text):
        known["troubleshooting_step"] = "tv_power_cycle_reboot"
        plan["reply"] = (
            "機上盒看到一半會自己關機再開機時，請先將機上盒電源拔掉約 10 秒後重新插上，"
            "等待 2 到 3 分鐘後再觀察是否還會反覆重開。若仍持續發生，建議轉真人客服協助預約維修。"
        )
        plan["should_call_tool"] = False
        plan["tool_name"] = None
        return plan

    if is_partial_channel_issue(user_text):
        known["troubleshooting_step"] = "tv_rescan_channels"
        plan["reply"] = build_channel_rescan_reply()
        plan["should_call_tool"] = False
        plan["tool_name"] = None
        return plan

    if is_no_signal_issue(user_text):
        known["troubleshooting_step"] = "tv_check_input_source"
        known["issue_description"] = "電視畫面顯示無訊號"
        plan["reply"] = (
            "畫面顯示無訊號時，請先確認電視訊號源是否切到正確的 HDMI 或 AV。"
            "您可以用電視遙控器按「訊號源 / Input / Source」切換看看。"
            "切換後請回覆我畫面是否恢復。"
        )
        plan["should_call_tool"] = False
        plan["tool_name"] = None
        return plan

    known["troubleshooting_step"] = "tv_check_power"

    plan["reply"] = (
        "我先帶您做幾個簡單檢查，若還是無法恢復，我再協助您建立報修工單。\n\n"
        "請先確認機上盒電源是否有亮燈？"
    )
    plan["should_call_tool"] = False
    plan["tool_name"] = None
    return plan


def start_remote_control_troubleshooting(user_text: str, memory: Dict[str, Any], plan: Dict[str, Any]) -> Dict[str, Any]:
    known = memory.setdefault("known_info", {})

    known["troubleshooting_started"] = "yes"
    known["troubleshooting_type"] = "remote"
    known["troubleshooting_step"] = "remote_check_light"
    known["troubleshooting_failed"] = "no"
    known["repair_ready"] = "no"
    known["retry"] = 0
    known["issue_description"] = user_text or "遙控器控制異常"

    plan["reply"] = (
        "了解，目前比較像是遙控器控制異常。"
        "請先確認遙控器電池是否有電、正負極是否裝反，並更換新電池再試一次。\n"
        "若仍無法操作，請對準機上盒或電視感應位置，確認中間沒有遮蔽物，"
        "並確認機上盒前方 IR 接收器沒有脫落。\n"
        "更換電池後仍無法使用時，可能需要更換遙控器；一般型 300 元、語音型 400 元，"
        "可臨櫃購買，實際型號與費用仍以客服確認為準。若不便自行更換，也可接續協助登記維修。"
    )
    plan["should_call_tool"] = False
    plan["tool_name"] = None
    return plan


def start_tv_tutorial_screen_troubleshooting(
    user_text: str,
    memory: Dict[str, Any],
    plan: Dict[str, Any],
) -> Dict[str, Any]:
    """Start with the remote when the set-top box is stuck on its tutorial screen."""
    known = memory.setdefault("known_info", {})
    known["troubleshooting_started"] = "yes"
    known["troubleshooting_type"] = "remote"
    known["troubleshooting_step"] = "remote_check_light"
    known["troubleshooting_failed"] = "no"
    known["repair_ready"] = "no"
    known["retry"] = 0
    known["tutorial_screen_flow"] = "yes"
    known["issue_description"] = user_text or "機上盒停留在教學畫面"

    plan["reply"] = (
        "了解，機上盒停留在教學畫面時，請先確認遙控器電池是否有電，"
        "再試按上下選台鍵，看看是否有反應。\n"
        "請回覆我遙控器按鍵是否能正常操作，我再帶您做下一步。"
    )
    plan["should_call_tool"] = False
    plan["tool_name"] = None
    return plan


def start_tv_input_source_troubleshooting(
    user_text: str,
    memory: Dict[str, Any],
    plan: Dict[str, Any],
) -> Dict[str, Any]:
    known = memory.setdefault("known_info", {})

    known["troubleshooting_started"] = "yes"
    known["troubleshooting_type"] = "tv"
    known["troubleshooting_step"] = "tv_check_input_source"
    known["troubleshooting_failed"] = "no"
    known["repair_ready"] = "no"
    known["retry"] = 0

    if not known.get("issue_description"):
        known["issue_description"] = user_text or "電視訊號源設定後仍無畫面"

    plan["next_goal"] = "continue_current_flow"
    plan["reply"] = (
        "請您拿電視遙控器，按「訊號源／INPUT／SOURCE」鍵，切換到機上盒連接的來源，"
        "常見為 HDMI1、HDMI2 或 AV。若不確定是哪一個，可以逐一切換，每切一次等 3 到 5 秒確認畫面是否恢復。"
    )
    plan["should_call_tool"] = False
    plan["tool_name"] = None
    return plan


def start_network_troubleshooting(user_text: str, memory: Dict[str, Any], plan: Dict[str, Any]) -> Dict[str, Any]:
    known = memory.setdefault("known_info", {})
    context = parse_troubleshooting_context(user_text)

    known["troubleshooting_started"] = "yes"
    known["troubleshooting_type"] = "network"
    known["troubleshooting_step"] = "net_check_scope"
    known["troubleshooting_failed"] = "no"
    known["repair_ready"] = "no"
    known["retry"] = 0

    if not known.get("issue_description"):
        known["issue_description"] = user_text

    if context.get("symptom_type"):
        known["symptom_type"] = context["symptom_type"]
    if context.get("affected_scope"):
        known["affected_scope"] = context["affected_scope"]
    if context.get("modem_light_status"):
        known["modem_light_status"] = context["modem_light_status"]

    if is_combined_tv_network_fault(user_text):
        known["affected_scope"] = "tv_and_network"
        known["troubleshooting_step"] = "net_check_modem_light"
        plan["reply"] = (
            "了解，電視與網路同時沒有訊號，先以共用線路或設備供電方向確認。\n\n"
            "請先確認機上盒與數據機都有亮電源燈，並查看數據機是否有紅燈、異常閃爍或完全沒亮；"
            "請把目前看到的燈號狀況告訴我。"
        )
        plan["should_call_tool"] = False
        plan["tool_name"] = None
        return plan

    if context.get("symptom_type") == "modem_light_abnormal":
        known["troubleshooting_step"] = "net_reboot_modem"
        plan["reply"] = (
            "了解，您已經有看到數據機燈號異常。"
            "請先將數據機電源拔掉約 10 秒後重新插上，等待 3 到 5 分鐘後，再確認是否可以上網。"
        )
        plan["should_call_tool"] = False
        plan["tool_name"] = None
        return plan

    if context.get("symptom_type") == "wifi_only":
        return start_wifi_only_troubleshooting(user_text, memory, plan)

    if context.get("symptom_type") == "computer_only":
        return start_computer_only_troubleshooting(user_text, memory, plan)

    if context.get("symptom_type") == "phone_only":
        return start_phone_only_troubleshooting(user_text, memory, plan)

    if is_internet_available_but_unstable_issue(user_text) or is_specific_service_unstable_issue(user_text) or is_network_unstable_issue(user_text):
        return build_network_unstable_reply(memory, plan)

    if is_network_slow_issue(user_text):
        return build_network_slow_reply(memory, plan)

    if is_floor_after_install_network_issue(user_text):
        known["affected_scope"] = "floor_or_indoor_wiring"
        known["troubleshooting_step"] = "net_check_scope"
        plan["reply"] = (
            "了解，您是剛安裝後特定樓層沒有網路，先以該樓層室內線路方向確認。\n\n"
            "請先確認該樓層的網路孔、網路線與分享器/電腦連接是否插緊；"
            "也請確認其他樓層是否可以正常上網？"
        )
        plan["should_call_tool"] = False
        plan["tool_name"] = None
        return plan

    if is_line_level_network_outage(user_text):
        known["affected_scope"] = "line_or_modem"
        known["troubleshooting_step"] = "net_check_modem_light"
        plan["reply"] = (
            "了解，您已用網路線接電腦測試仍無網路，先以數據機或線路方向確認。\n\n"
            "請問數據機目前燈號是否有亮紅燈、閃爍異常，或完全沒亮燈？"
        )
        plan["should_call_tool"] = False
        plan["tool_name"] = None
        return plan

    if contains_any(user_text, ["手機不能上網", "手機無法上網", "手機連不上網"]):
        known["affected_scope"] = "single_device"
        known["troubleshooting_step"] = "net_phone_connection_type"
        plan["reply"] = "請先確認手機目前是連家中 Wi-Fi，還是使用門號的 4G/5G 行動網路？"
        plan["should_call_tool"] = False
        plan["tool_name"] = None
        return plan

    if contains_any(user_text, ["電腦不能上網", "電腦無法上網", "電腦連不上網"]):
        known["affected_scope"] = "single_device"
        known["troubleshooting_step"] = "net_computer_connection_type"
        plan["reply"] = "請問您的電腦是透過 Wi-Fi 連線，還是接實體網路線？"
        plan["should_call_tool"] = False
        plan["tool_name"] = None
        return plan

    # The LLM has already identified a complete network-disconnection
    # report. Start with recovery rather than asking the customer to repeat
    # whether the problem affects one or all devices.
    if contains_any(user_text, [
        "網路無連線",
        "網路無法連線",
        "網路連不上",
        "網路完全不能用",
        "沒有網路",
        "沒網路",
        "無法上網",
        "不能上網",
    ]):
        known["affected_scope"] = "unknown"
        known["troubleshooting_step"] = "net_reboot_modem"
        plan["reply"] = (
            "了解，網路目前無法連線，我們先做最簡單的重開步驟："
            "請將數據機電源拔掉約 10 秒後重新插上，等待 3 到 5 分鐘後，"
            "再確認網路是否恢復。"
        )
        plan["should_call_tool"] = False
        plan["tool_name"] = None
        return plan

    plan["reply"] = (
        "我先帶您做幾個簡單檢查，若還是無法恢復，我再協助您建立報修工單。\n\n"
        "1. 請確認數據機與分享器都有亮電源燈。\n"
        "2. 將數據機與分享器的電源拔除 10 秒後再插回，等待約 3 至 5 分鐘。\n"
        "3. 確認數據機、分享器與電腦之間的網路線兩端都有插緊。\n\n"
        "完成後，請告訴我目前是所有設備都不能上網，還是只有單一手機或電腦不能上網，以及網路是否已恢復。"
    )
    plan["should_call_tool"] = False
    plan["tool_name"] = None
    return plan


def start_troubleshooting(user_text: str, memory: Dict[str, Any], plan: Dict[str, Any]) -> Dict[str, Any]:
    troubleshooting_type = detect_troubleshooting_type(user_text)

    if troubleshooting_type == "network":
        return start_network_troubleshooting(user_text, memory, plan)

    if troubleshooting_type == "remote":
        return start_remote_control_troubleshooting(user_text, memory, plan)

    return start_tv_troubleshooting(user_text, memory, plan)


def apply_tv_troubleshooting_step(
    text: str,
    memory: Dict[str, Any],
    plan: Dict[str, Any],
    label: str,
) -> Dict[str, Any]:
    known = memory.setdefault("known_info", {})
    step = known.get("troubleshooting_step")

    if is_tv_equipment_boot_issue(text) or is_tv_boot_loop_reply(text):
        known["issue_description"] = "機上盒持續重複開機或停在開機畫面"
        known["troubleshooting_step"] = "tv_reboot"
        known["retry"] = 0
        plan["reply"] = (
            "了解，機上盒持續重複開機或停在開機畫面時，請先將機上盒電源拔掉約 10 秒後重新插上，"
            "等待 2 到 3 分鐘確認是否能正常完成開機。若仍持續重複開機，再協助安排維修。"
        )
        plan["should_call_tool"] = False
        plan["tool_name"] = None
        return plan

    if is_no_signal_issue(text) and step not in {"tv_check_input_source", "tv_reboot"}:
        known["issue_description"] = "電視畫面顯示無訊號"
        known["troubleshooting_step"] = "tv_check_input_source"
        known["retry"] = 0
        plan["reply"] = (
            "畫面顯示無訊號時，請先確認電視訊號源是否切到正確的 HDMI 或 AV。"
            "您可以用電視遙控器按「訊號源 / Input / Source」切換看看。"
            "若不會操作，我可以改用更簡單的方式一步一步帶您確認。"
        )
        plan["should_call_tool"] = False
        plan["tool_name"] = None
        return plan

    if contains_any(text, ["有聲音沒畫面", "有聲音沒有畫面", "只有黑畫面", "黑畫面", "黑色畫面", "沒畫面", "沒有畫面"]) and step not in {"tv_reboot"}:
        known["issue_description"] = "電視黑畫面或沒有畫面"
        known["troubleshooting_step"] = "tv_reboot"
        known["retry"] = 0
        plan["reply"] = "請您先將機上盒電源拔掉約 10 秒後重新插上，等待 2 到 3 分鐘後，再確認畫面是否恢復。"
        plan["should_call_tool"] = False
        plan["tool_name"] = None
        return plan

    if step == "tv_check_sound":
        if label == "recovered":
            return finish_troubleshooting(memory, plan)

        if label in {"failed", "negative"} or contains_any(
            text,
            ["還是沒聲音", "仍然沒聲音", "沒有恢復", "沒恢復", "不行"],
        ):
            known["troubleshooting_step"] = "tv_reboot"
            known["retry"] = 0
            plan["reply"] = (
                "請將機上盒電源拔掉約 10 秒後重新插上，等待 2 到 3 分鐘後，"
                "再確認聲音是否恢復。"
            )
            plan["should_call_tool"] = False
            plan["tool_name"] = None
            return plan

        plan["reply"] = (
            "請先確認電視與數位機上盒都沒有開啟靜音並將音量調高，"
            "再確認 HDMI 或 AV 的音訊線路是否插緊；完成後請告訴我是否恢復聲音。"
        )
        plan["should_call_tool"] = False
        plan["tool_name"] = None
        return plan

    described_context = parse_troubleshooting_context(text)
    if step in {"tv_check_power", "tv_check_screen"} and described_context.get("service_type") == "tv":
        symptom = described_context.get("symptom_type")
        if symptom == "picture_quality":
            known["issue_description"] = text
            known["troubleshooting_step"] = "tv_rescan_channels"
            known["retry"] = 0
            plan["reply"] = (
                "了解，畫面顏色或影像異常時，先嘗試恢復原廠預設或重新搜頻。\n\n"
                f"{build_channel_rescan_reply()}"
            )
            plan["should_call_tool"] = False
            plan["tool_name"] = None
            return plan
        if symptom == "black_screen":
            known["issue_description"] = "電視黑畫面或沒有畫面"
            known["troubleshooting_step"] = "tv_reboot"
            known["retry"] = 0
            plan["reply"] = "請您先將機上盒電源拔掉約 10 秒後重新插上，等待 2 到 3 分鐘後，再確認畫面是否恢復。"
            plan["should_call_tool"] = False
            plan["tool_name"] = None
            return plan

    if step == "tv_check_power":
        if label == "affirmative" or text in ["有", "有啦", "有亮", "有亮燈"]:
            described_screen_plan = continue_tv_after_power_confirmed_from_description(memory, plan)
            if described_screen_plan:
                return described_screen_plan
            known["troubleshooting_step"] = "tv_check_screen"
            known["retry"] = 0
            plan["reply"] = (
                "了解。請問電視畫面目前是什麼狀況？"
                "例如無訊號、黑畫面、錯誤代碼或機上盒反覆開機；若是其他畫面，也請直接描述。"
            )
            plan["should_call_tool"] = False
            plan["tool_name"] = None
            return plan

        if label == "negative" or text in ["沒有", "沒亮", "沒有亮", "不亮"]:
            known["troubleshooting_step"] = "tv_check_power_cable"
            known["issue_description"] = "機上盒電源燈不亮"
            known["retry"] = 0
            plan["reply"] = "請先確認機上盒電源線是否插好，插座是否有電。確認後請告訴我電源燈是否有亮。"
            plan["should_call_tool"] = False
            plan["tool_name"] = None
            return plan

        if label in ["failed", "refuse"] or fallback_unknown(memory, text):
            known["troubleshooting_step"] = "tv_reboot"
            known["retry"] = 0
            plan["reply"] = (
                "了解，若目前無法確認電源燈或畫面細節，先做最簡單的重開："
                "請將機上盒電源拔掉約 10 秒後重新插上，等待 2 到 3 分鐘後，再確認是否恢復。"
            )
            plan["should_call_tool"] = False
            plan["tool_name"] = None
            return plan

        plan["reply"] = "我再確認一下，機上盒電源燈目前是有亮，還是沒有亮呢？"
        return plan

    if step == "tv_check_power_cable":
        if label == "affirmative" or contains_any(text, ["有亮", "亮了"]):
            described_screen_plan = continue_tv_after_power_confirmed_from_description(
                memory,
                plan,
                "確認電源線與插座後，機上盒電源有亮。",
            )
            if described_screen_plan:
                return described_screen_plan
            known["troubleshooting_step"] = "tv_check_screen"
            known["retry"] = 0
            plan["reply"] = "目前畫面是什麼狀況？例如無訊號、黑畫面、錯誤代碼或機上盒反覆開機；其他畫面也可以直接描述。"
            return plan

        if label in ["negative", "failed", "refuse"] or text in ["沒有", "沒", "不亮"] or contains_any(text, [
            "還是沒亮",
            "還是不亮",
            "還是沒有亮",
            "還是沒有",
            "還是沒",
            "就沒有",
            "就是沒有",
            "沒有亮",
            "沒亮",
        ]):
            return switch_to_repair(memory, plan)

        plan["reply"] = "確認電源線與插座後，機上盒電源燈是否有亮？"
        return plan

    if step == "tv_check_screen":
        context = parse_troubleshooting_context(text)
        if context.get("symptom_type") == "no_channels":
            known["issue_description"] = text
            known["troubleshooting_step"] = "tv_rescan_channels"
            known["retry"] = 0
            plan["reply"] = (
                "了解，頻道或節目清單異常時，先嘗試恢復原廠預設或重新搜頻。\n\n"
                f"{build_channel_rescan_reply()}"
            )
            return plan

        if context.get("symptom_type") == "screen_freeze" or is_tv_signal_or_playback_issue(text):
            known["issue_description"] = text
            known["troubleshooting_step"] = "tv_reboot"
            known["retry"] = 0
            plan["reply"] = (
                "了解，有畫面但會卡頓、轉圈或 lag 時，請先將機上盒電源拔掉約 10 秒後重新插上，"
                "等待 2 到 3 分鐘後再確認。若仍會發生，請再告訴我是單一頻道還是全部頻道。"
            )
            return plan

        if context.get("symptom_type") == "picture_quality":
            known["issue_description"] = text
            known["troubleshooting_step"] = "tv_rescan_channels"
            known["retry"] = 0
            plan["reply"] = (
                "了解，畫面顏色或影像異常時，先嘗試恢復原廠預設或重新搜頻。\n\n"
                f"{build_channel_rescan_reply()}"
            )
            return plan

        if is_no_signal_issue(text):
            known["issue_description"] = "電視畫面顯示無訊號"
            known["troubleshooting_step"] = "tv_check_input_source"
            known["retry"] = 0
            plan["reply"] = (
                "畫面顯示無訊號時，請先確認電視訊號源是否切到正確的 HDMI 或 AV。"
                "您可以用電視遙控器按「訊號源 / Input / Source」切換看看。"
            )
            return plan

        if contains_any(text, ["黑畫面", "沒有畫面", "沒看到畫面", "看不到畫面", "畫面黑", "黑的", "黑屏"]):
            known["issue_description"] = "電視黑畫面或沒有畫面"
            known["troubleshooting_step"] = "tv_reboot"
            known["retry"] = 0
            plan["reply"] = "請您先將機上盒電源拔掉約 10 秒後重新插上，等待 2 到 3 分鐘後，再確認畫面是否恢復。"
            return plan

        if contains_any(text, ["錯誤代碼", "代碼"]):
            known["issue_description"] = f"電視出現錯誤代碼：{text}"
            known["troubleshooting_step"] = "tv_reboot"
            known["retry"] = 0
            plan["reply"] = "請您先將機上盒電源拔掉約 10 秒後重新插上，等待 2 到 3 分鐘後，再確認錯誤代碼是否消失。"
            return plan

        plan["reply"] = "請問畫面是什麼狀況？例如無訊號、黑畫面、錯誤代碼或機上盒反覆開機；其他畫面也可以直接描述。"
        return plan

    if step in {"tv_authorization_check_channel", "unauthorized_channel_check"}:
        if contains_any(text, ["一般頻道", "基本頻道", "一般基本頻道"]):
            known["troubleshooting_step"] = "authorization_payment"
            plan["reply"] = (
                "若一般基本頻道也顯示 E004、授權到期或未授權，需協助確認收視費與授權狀態。"
                "如您已繳費，請提供繳費收據或交易明細；若是線上繳費，請先將機上盒電源關機約 10 秒後重新開機再確認。"
            )
            plan["should_call_tool"] = False
            plan["tool_name"] = None
            return plan

        if contains_any(text, ["成人", "加值"]):
            plan["reply"] = (
                "如果目前停在成人頻道或加值頻道，可能需要另外訂購才會授權。"
                "請先切到一般基本頻道確認是否能看；若基本頻道也顯示授權到期，"
                "再請提供戶名與聯絡電話，由客服協助確認繳費或授權狀態。"
            )
            plan["should_call_tool"] = False
            plan["tool_name"] = None
            return plan

        if label == "recovered" or fallback_recovered(memory, text):
            return finish_troubleshooting(memory, plan)

        if label in ["failed", "refuse"] or fallback_failed(memory, text):
            known["troubleshooting_step"] = "tv_reboot"
            known["retry"] = 0
            plan["reply"] = "若一般基本頻道也無法收看，請先將機上盒電源拔掉約 10 秒後重新插上，等待 2 到 3 分鐘後再確認。"
            return plan

        plan["reply"] = "請先切到一般基本頻道確認是否能看，例如台視/中視/民視；切換後是否還是顯示授權到期？"
        return plan

    if step == "tv_power_cycle_reboot":
        if is_all_channel_unavailable_issue(text):
            known["troubleshooting_failed"] = "yes"
            known["repair_ready"] = "no"
            known["issue_description"] = "機上盒已重開機，全部頻道仍無法收視"
            plan["reply"] = (
                "了解，目前是全部頻道無法收視，不是機上盒自動關機再開機。"
                "既然已重開機仍無法收看，建議由真人客服協助確認訊號、帳務授權或安排維修。"
            )
            plan["should_call_tool"] = False
            plan["tool_name"] = None
            return plan

        if label == "recovered" or fallback_recovered(memory, text):
            return finish_troubleshooting(memory, plan)

        if label in ["failed", "refuse"] or fallback_failed(memory, text):
            known["troubleshooting_failed"] = "yes"
            known["repair_ready"] = "no"
            plan["reply"] = "了解，機上盒重開後仍反覆自動關機，建議轉真人客服協助預約維修。"
            plan["should_call_tool"] = False
            plan["tool_name"] = None
            return plan

        plan["reply"] = "重新插電後，機上盒是否還會自己關機再開機？"
        return plan

    if step == "tv_check_input_source":
        if is_direct_fault_report(text):
            known["troubleshooting_step"] = "tv_check_power"
            known["retry"] = 0
            plan["reply"] = "了解，我們再做一個簡單確認：請看一下機上盒電源燈目前是有亮，還是沒有亮？"
            plan["should_call_tool"] = False
            plan["tool_name"] = None
            return plan

        if is_input_source_how_to_query(text):
            known["retry"] = 0
            plan["reply"] = (
                "沒關係，我一步一步帶您確認：請拿電視遙控器，找「訊號源 / INPUT / SOURCE」鍵，"
                "按下後依序切換 HDMI1、HDMI2 或 AV，每切一次等 3 到 5 秒看畫面是否恢復。"
                "如果找不到這個按鍵，請先將機上盒電源拔掉 10 秒後再插回。"
            )
            plan["should_call_tool"] = False
            plan["tool_name"] = None
            return plan

        if label == "recovered" or fallback_recovered(memory, text):
            return finish_troubleshooting(memory, plan)

        if label in ["failed", "refuse"] or fallback_failed(memory, text):
            known["troubleshooting_step"] = "tv_reboot"
            known["retry"] = 0
            plan["reply"] = "了解。請您再將機上盒電源拔掉約 10 秒後重新插上，等待 2 到 3 分鐘後，再確認畫面是否恢復。"
            return plan

        plan["reply"] = "切換訊號源後，畫面是否已恢復？"
        return plan

    if step == "tv_reboot":
        if (
            known.get("awaiting_channel_scope_after_reboot") == "yes"
            and (text or "").strip() in {"單一", "全部", "單一頻道", "全部頻道"}
        ):
            known.pop("awaiting_channel_scope_after_reboot", None)
            if "單一" in text:
                known["troubleshooting_step"] = "tv_single_channel_detail"
                known["retry"] = 0
                known["issue_description"] = "機上盒重開後仍有單一頻道收訊異常"
                plan["reply"] = (
                    "了解，若只有單一頻道異常，請告訴我頻道號碼，"
                    "並確認該頻道目前是無訊號、馬賽克，還是畫面會卡頓；"
                    "我再協助您做下一步確認。"
                )
                plan["should_call_tool"] = False
                plan["tool_name"] = None
                return plan

            known["issue_description"] = "機上盒重開後仍有全部頻道收訊異常"
            return switch_to_repair(memory, plan)

        if label == "recovered" or fallback_recovered(memory, text):
            return finish_troubleshooting(memory, plan)

        if label == "unknown" or fallback_unknown(memory, text):
            known["troubleshooting_step"] = "tv_reboot"
            known["retry"] = 0
            plan["reply"] = (
                "沒關係，先不用判斷細節。請直接將機上盒電源拔掉約 10 秒後重新插上，"
                "等待 2 到 3 分鐘後，再看畫面是否恢復。"
            )
            plan["should_call_tool"] = False
            plan["tool_name"] = None
            return plan

        if is_partial_channel_issue(text):
            known["troubleshooting_step"] = "tv_rescan_channels"
            known["retry"] = 0
            plan["reply"] = build_channel_rescan_reply()
            plan["should_call_tool"] = False
            plan["tool_name"] = None
            return plan

        if label in ["failed", "refuse"] or fallback_failed(memory, text):
            return switch_to_repair(memory, plan)

        plan["reply"] = "重新插電後，畫面是否已恢復？如果還是不行，我可以協助您建立報修工單。"
        return plan

    if step == "tv_rescan_channels":
        # The model has identified that the same picture-quality symptom is
        # still present after this flow already supplied the rescan step.
        # Advance instead of emitting the identical instructions again.
        if plan.get("intent") in TV_PICTURE_QUALITY_INTENTS:
            known["issue_description"] = text
            return switch_to_repair(memory, plan)

        context = parse_troubleshooting_context(text)
        if (
            context.get("symptom_type") == "picture_quality"
            and not has_completed_channel_rescan(text)
        ):
            known["issue_description"] = text
            known["retry"] = 0
            plan["reply"] = build_channel_rescan_reply()
            plan["should_call_tool"] = False
            plan["tool_name"] = None
            return plan

        if is_tv_no_program_display_issue(text) and not has_completed_channel_rescan(text):
            known["retry"] = 0
            plan["reply"] = build_channel_rescan_reply()
            plan["should_call_tool"] = False
            plan["tool_name"] = None
            return plan

        if label == "recovered" or fallback_recovered(memory, text):
            return finish_troubleshooting(memory, plan)

        if label in ["failed", "refuse"] or fallback_failed(memory, text):
            return switch_to_repair(memory, plan)

        plan["reply"] = "重搜或恢復預設完成後，原本看不到的頻道是否已恢復？如果仍無法觀看，我可以協助您轉真人客服或安排後續處理。"
        plan["should_call_tool"] = False
        plan["tool_name"] = None
        return plan

    plan["reply"] = "我再確認一下，目前電視畫面是什麼狀況？例如無訊號、黑畫面、錯誤代碼或機上盒反覆開機；其他畫面也可以直接描述。"
    return plan


def apply_remote_control_troubleshooting_step(
    text: str,
    memory: Dict[str, Any],
    plan: Dict[str, Any],
    label: str,
) -> Dict[str, Any]:
    known = memory.setdefault("known_info", {})
    step = known.get("troubleshooting_step")

    if step == "remote_check_light":
        if label == "affirmative" or contains_any(text, ["有亮", "亮紅燈", "有紅燈", "會亮"]):
            if known.pop("tutorial_screen_flow", None) == "yes":
                known["troubleshooting_type"] = "tv"
                known["troubleshooting_step"] = "tv_rescan_channels"
                known["retry"] = 0
                plan["reply"] = (
                    "遙控器有反應的話，請先依機上盒型號執行恢復預設或重新搜頻，"
                    "完成後再用上下選台鍵確認是否可以切換頻道。\n\n"
                    f"{build_channel_rescan_reply()}"
                )
                plan["should_call_tool"] = False
                plan["tool_name"] = None
                return plan

            known["troubleshooting_step"] = "remote_check_receiver"
            known["retry"] = 0
            plan["reply"] = (
                "有亮紅燈代表遙控器本身有送出訊號。"
                "請再確認是否對準機上盒感應位置，機上盒前方 IR 接收器是否遮住、脫落或沒有亮燈。"
                "也可以先將機上盒電源拔掉約 10 秒後重新插上再測試。"
            )
            plan["should_call_tool"] = False
            plan["tool_name"] = None
            return plan

        if label == "negative" or contains_any(text, ["沒亮", "沒有亮", "不亮", "沒紅燈"]):
            known["troubleshooting_failed"] = "yes"
            known["repair_ready"] = "no"
            plan["reply"] = (
                "遙控器按鍵時沒有紅燈，請先更換電池後再測試。"
                "若更換電池後仍沒有紅燈，可能是遙控器故障，需由客服協助確認更換方式與型號。"
            )
            plan["should_call_tool"] = False
            plan["tool_name"] = None
            return plan

        plan["reply"] = "請先確認遙控器按鍵時是否有亮紅燈？"
        plan["should_call_tool"] = False
        plan["tool_name"] = None
        return plan

    if step == "remote_check_receiver":
        if label == "recovered" or fallback_recovered(memory, text):
            return finish_troubleshooting(memory, plan)

        if label in ["failed", "negative", "refuse"] or fallback_failed(memory, text):
            known["troubleshooting_failed"] = "yes"
            known["repair_ready"] = "no"
            plan["reply"] = (
                "了解，若遙控器有亮紅燈但仍無法控制，請由真人客服協助確認機上盒 IR 接收器、"
                "遙控器型號或是否需要更換。"
            )
            plan["should_call_tool"] = False
            plan["tool_name"] = None
            return plan

        plan["reply"] = "確認對準機上盒感應位置並重開機上盒後，遙控器是否可以正常控制了？"
        plan["should_call_tool"] = False
        plan["tool_name"] = None
        return plan

    return start_remote_control_troubleshooting(text, memory, plan)


def apply_network_troubleshooting_step(
    text: str,
    memory: Dict[str, Any],
    plan: Dict[str, Any],
    label: str,
) -> Dict[str, Any]:
    known = memory.setdefault("known_info", {})
    step = known.get("troubleshooting_step")

    if label == "device_replacement":
        known["affected_scope"] = "replacement_device"
        known["issue_description"] = (
            "更換新的網路設備後無法上網，但原本設備可以正常使用"
        )
        known["troubleshooting_step"] = "net_device_registration"
        known["retry"] = 0
        plan["reply"] = (
            "了解，原本設備可以正常上網，表示線路服務大致正常。"
            "請先確認新路由器的 WAN／Internet 埠已接到數據機 LAN 埠，"
            "並將上網方式設為「DHCP／自動取得 IP」，再測試是否可以上網。"
        )
        plan["should_call_tool"] = False
        plan["tool_name"] = None
        return plan

    if step == "net_device_registration":
        if label == "recovered":
            return finish_troubleshooting(memory, plan)

        if label in {"failed", "affirmative"}:
            known["troubleshooting_step"] = "net_manual_device_registration"
            known["retry"] = 0
            plan["reply"] = (
                "若已確認使用 DHCP／自動取得 IP 仍無法上網，請至台基科官網 "
                "https://www.tinp.net.tw/ → 會員專區 →「電腦網卡更換註冊」，"
                "依畫面完成手動註冊後，再重新啟動路由器測試。"
            )
        elif label == "refuse":
            known["troubleshooting_failed"] = "yes"
            known["repair_ready"] = "yes"
            known["retry"] = 0
            plan["intent"] = "human_handoff_offer"
            plan["reply"] = "若不方便自行確認設定，請問是否需要幫您轉接真人文字客服？"
        else:
            plan["reply"] = (
                "請先確認新路由器的 WAN／Internet 埠已接到數據機 LAN 埠，"
                "並將上網方式設為「DHCP／自動取得 IP」，再告訴我是否可以上網。"
            )
        plan["should_call_tool"] = False
        plan["tool_name"] = None
        return plan

    if step == "net_manual_device_registration":
        if label == "recovered":
            return finish_troubleshooting(memory, plan)

        if label in {"failed", "refuse"}:
            known["troubleshooting_failed"] = "yes"
            known["repair_ready"] = "yes"
            known["retry"] = 0
            plan["intent"] = "human_handoff_offer"
            plan["reply"] = (
                "手動註冊後仍無法上網，需要由客服進一步確認。"
                "請問是否需要幫您轉接真人文字客服？"
            )
            plan["should_call_tool"] = False
            plan["tool_name"] = None
            return plan

        plan["reply"] = "請問完成官網手動註冊並重新啟動路由器後，是否已可以上網？"
        plan["should_call_tool"] = False
        plan["tool_name"] = None
        return plan

    if step in {
        "net_check_scope",
        "net_check_modem_light",
        "net_reboot_modem",
        "net_single_device",
    } and contains_any(text, ["電腦不能上網", "電腦無法上網", "電腦連不上網"]):
        known["affected_scope"] = "single_device"
        known["issue_description"] = text
        known["troubleshooting_step"] = "net_computer_connection_type"
        known["retry"] = 0
        plan["reply"] = "了解，目前是電腦無法上網。請問這台電腦是透過 Wi-Fi 連線，還是接實體網路線？"
        plan["should_call_tool"] = False
        plan["tool_name"] = None
        return plan

    if step in {
        "net_unstable_scope",
        "net_slow_scope",
        "net_slow_specific",
        "net_check_scope",
        "net_check_modem_light",
        "net_reboot_modem",
        "net_single_device",
        "net_computer_connection_type",
    } and is_wired_connection_detail(text) and not is_multi_device_network_issue(text):
        known["connection_type"] = "wired"
        known["affected_scope"] = known.get("affected_scope") or "wired_or_wall_port"
        known["issue_description"] = text
        known["troubleshooting_step"] = "net_wired_connection_check"
        known["retry"] = 0
        plan["reply"] = (
            "了解，您目前是直接接網路孔或網路線。我們先往有線連接方向確認："
            "請確認網路線兩端都有插緊，若方便也請換一條網路線，或改接數據機/分享器其他 LAN 孔測試。"
            "確認後是恢復、仍然速度慢，還是完全不能上網？"
        )
        plan["should_call_tool"] = False
        plan["tool_name"] = None
        return plan

    if step in {"net_unstable_scope", "net_slow_scope", "net_slow_specific"} and is_network_troubleshooting_how_to_query(text):
        known["retry"] = 0
        plan["reply"] = (
            "可以，請依序這樣做：\n"
            "1. 將數據機及分享器電源拔掉約 10 秒後重新插上，等待 3 到 5 分鐘。\n"
            "2. 若方便，讓電腦直接用網路線連接數據機或分享器，暫時不要使用 Wi-Fi。\n"
            "3. 暫停下載、雲端同步、影音串流等大量用網，再到 www.speedtest.net 測試。\n"
            "4. 請回覆下載與上傳速度；若重測後仍不穩或明顯偏慢，我再協助您安排後續檢查。"
        )
        plan["should_call_tool"] = False
        plan["tool_name"] = None
        return plan

    if is_network_cause_source_question(text):
        known["retry"] = 0
        plan["reply"] = (
            "家用寬頻不是透過行動基地台連線，因此目前較可能要從 Wi-Fi 環境、分享器／數據機，"
            "或室內外線路來確認。\n\n"
            "請先讓電腦直接以網路線連接數據機或分享器，暫停其他大量用網後測速："
            "若有線也持續不穩或明顯偏慢，較需要由客服確認數據機與線路；"
            "若只有 Wi-Fi 不穩，則較偏向分享器或室內無線環境。"
        )
        plan["should_call_tool"] = False
        plan["tool_name"] = None
        return plan

    if step == "net_unstable_scope":
        if is_multi_device_network_issue(text):
            return move_to_modem_light_check(memory, plan, text)

        if is_specific_service_unstable_issue(text) or contains_any(text, ["特定", "只有", "遊戲", "影片", "APP", "app"]):
            known["troubleshooting_step"] = "net_slow_specific"
            known["retry"] = 0
            known["issue_description"] = text
            plan["reply"] = (
                "了解，這是特定遊戲、影片或 APP 連線不穩的情境。"
                "請再確認其他網站或 APP 是否也會不穩；如果手機 Wi-Fi 和電腦有線都一樣不穩，我們就直接往數據機與線路方向確認。"
            )
            plan["should_call_tool"] = False
            plan["tool_name"] = None
            return plan

        if contains_any(text, ["全部", "所有", "都會", "都一樣", "每個", "很多"]):
            return move_to_modem_light_check(memory, plan, text)

        if label == "unknown" or fallback_unknown(memory, text):
            known["troubleshooting_step"] = "net_reboot_modem"
            known["retry"] = 0
            plan["reply"] = (
                "沒關係，我們先做最基本的線路設備排除。"
                "請將數據機電源拔掉約 10 秒後重新插上，等待 3 到 5 分鐘後，再確認網路是否還會不穩。"
            )
            plan["should_call_tool"] = False
            plan["tool_name"] = None
            return plan

        if label in ["failed", "refuse"] or fallback_failed(memory, text):
            known["issue_description"] = known.get("issue_description") or "網路連線不穩，使用者不便繼續排查"
            return switch_to_repair(memory, plan)

        plan["reply"] = (
            "我再確認一下：是所有網站、APP 都會不穩，還是只有玩遊戲、看影片或特定 APP 時才會發生？"
            "如果手機 Wi-Fi 和電腦有線都會不穩，請直接回覆「兩邊都不穩」。"
        )
        plan["should_call_tool"] = False
        plan["tool_name"] = None
        return plan

    if step == "net_slow_scope":
        if contains_any(text, ["實際速率與合約速率不符", "測速不達", "速率不符", "頻寬不符"]):
            known["retry"] = 0
            plan["reply"] = (
                "了解，請直接告訴我申辦速率與目前測得的下載速度，例如「申辦 300M、實測 30M」；"
                "我會依這兩個數值接續有線單機測速或維修流程，不會再重問影響範圍。"
            )
            plan["should_call_tool"] = False
            plan["tool_name"] = None
            return plan

        if is_multi_device_network_issue(text):
            return move_to_modem_light_check(memory, plan, text)

        if contains_any(text, ["遊戲", "爆ping", "爆 ping", "ping", "影片", "特定", "只有"]):
            known["troubleshooting_step"] = "net_slow_specific"
            known["retry"] = 0
            plan["reply"] = (
                "了解，若是特定遊戲、影片或 APP 很慢，請先測試其他網站是否正常，"
                "並到 www.speedtest.net 測速。若測速正常，可能與特定服務路由或尖峰時段有關。"
            )
            return plan

        if contains_any(text, ["都很慢", "全部", "所有", "都慢", "都一樣慢"]):
            known["troubleshooting_step"] = "net_reboot_modem"
            known["retry"] = 0
            plan["reply"] = "若所有網站/APP 都很慢，請先將數據機電源拔掉約 10 秒後重新插上，等待 3 到 5 分鐘後再測速確認。"
            return plan

        plan["reply"] = "請問是所有網站/APP 都很慢，還是只有玩線上遊戲、看影片或特定 APP 時很慢？"
        return plan

    if step == "net_slow_specific":
        if is_multi_device_network_issue(text):
            return move_to_modem_light_check(memory, plan, text)

        if label == "recovered" or fallback_recovered(memory, text):
            return finish_troubleshooting(memory, plan)

        if label in ["failed", "refuse"] or fallback_failed(memory, text):
            known["troubleshooting_step"] = "net_reboot_modem"
            known["retry"] = 0
            plan["reply"] = "請再將數據機電源拔掉約 10 秒後重新插上，等待 3 到 5 分鐘後重新測速；若仍明顯異常，再轉真人客服協助確認線路。"
            return plan

        plan["reply"] = "測速後下載/上傳速度是否明顯低於申辦速率？"
        return plan

    if step == "net_phone_connection_type":
        if contains_any(text, ["4g", "4G", "5g", "5G", "行動", "門號"]):
            plan["reply"] = "如果手機使用 4G/5G 門號不能上網，這通常不是有線寬頻線路問題，建議先確認電信門號訊號與行動數據設定。"
            return plan

        if contains_any(text, ["wifi", "Wi-Fi", "WIFI", "wi-fi", "家中"]):
            known["troubleshooting_step"] = "net_single_device"
            known["retry"] = 0
            plan["reply"] = "請先確認手機是否連到正確 Wi-Fi，並關閉 Wi-Fi 後重新連線。重新連線後是否恢復？"
            return plan

        plan["reply"] = "請先確認手機目前是連家中 Wi-Fi，還是使用門號的 4G/5G 行動網路？"
        return plan

    if step == "net_computer_connection_type":
        if contains_any(text, ["wifi", "Wi-Fi", "WIFI", "wi-fi", "無線"]):
            known["troubleshooting_step"] = "net_single_device"
            known["retry"] = 0
            plan["reply"] = "請先確認電腦是否連到正確 Wi-Fi，並中斷後重新連線。重新連線後是否恢復？"
            return plan

        if label == "negative" or (text or "").strip() in {"否", "沒有", "沒", "不是"}:
            known["connection_type"] = "wired"
            known["troubleshooting_step"] = "net_wired_connection_check"
            known["retry"] = 0
            plan["reply"] = (
                "了解，若不是使用 Wi-Fi，我們先以有線連接確認。"
                "請檢查電腦與數據機／分享器兩端的網路線是否插緊；若方便，請換一條網路線或改接其他 LAN 孔，再確認是否恢復。"
            )
            plan["should_call_tool"] = False
            plan["tool_name"] = None
            return plan

        if contains_any(text, ["網路線", "實體", "有線", "lan", "LAN"]):
            known["troubleshooting_step"] = "net_single_device"
            known["retry"] = 0
            plan["reply"] = "請先確認網路線兩端是否插緊，也可以換一個數據機或分享器 LAN 孔測試。確認後是否恢復？"
            return plan

        plan["reply"] = "請問您的電腦是透過 Wi-Fi 連線，還是接實體網路線？"
        return plan

    if step == "net_wired_connection_check":
        if label == "recovered" or fallback_recovered(memory, text):
            return finish_troubleshooting(memory, plan)

        if is_multi_device_network_issue(text):
            return move_to_modem_light_check(memory, plan, text)

        if contains_any(text, ["只有這個孔", "這個孔", "房間", "客廳孔", "牆上孔", "牆壁孔", "網路孔"]):
            known["affected_scope"] = "wall_port_or_indoor_wiring"
            known["issue_description"] = known.get("issue_description") or "有線網路孔或室內線路異常"
            plan["reply"] = (
                "了解，若像是特定網路孔或室內線路異常，通常需要進一步確認孔位與線路。"
                "請問同一台設備改接其他網路孔，或直接接數據機/分享器 LAN 孔時是否正常？"
            )
            plan["should_call_tool"] = False
            plan["tool_name"] = None
            return plan

        if label in ["failed", "refuse"] or fallback_failed(memory, text):
            known["issue_description"] = known.get("issue_description") or "有線網路測試後仍無法恢復"
            return switch_to_repair(memory, plan)

        if label == "unknown" or fallback_unknown(memory, text):
            known["retry"] = known.get("retry", 0) + 1
            if known["retry"] >= 2:
                known["issue_description"] = known.get("issue_description") or "有線網路連接狀況無法線上確認"
                return switch_to_repair(memory, plan)
            plan["reply"] = (
                "我再確認一下：目前是只有這個網路孔或這台電腦異常，"
                "還是手機 Wi-Fi、其他電腦也都會慢或不能上網？"
            )
            plan["should_call_tool"] = False
            plan["tool_name"] = None
            return plan

        plan["reply"] = "請問換線或換 LAN 孔後，這台電腦是否已恢復上網？"
        plan["should_call_tool"] = False
        plan["tool_name"] = None
        return plan

    if step == "net_check_scope":
        if known.get("awaiting_other_devices_after_single_failure") == "yes":
            if label == "negative" or (text or "").strip() in {"否", "沒有", "沒", "不是"}:
                known.pop("awaiting_other_devices_after_single_failure", None)
                return move_to_modem_light_check(
                    memory,
                    plan,
                    "原本電腦無法上網，其他設備也無法正常連線",
                )

            if label == "affirmative" or contains_any(text, ["正常", "可以", "能上網"]):
                known.pop("awaiting_other_devices_after_single_failure", None)
                known["affected_scope"] = "single_device"
                known["troubleshooting_step"] = "net_computer_connection_type"
                known["retry"] = 0
                plan["reply"] = "了解，其他設備可以上網的話，先以這台電腦的連接方式確認。請問電腦目前是透過 Wi-Fi，還是接實體網路線？"
                plan["should_call_tool"] = False
                plan["tool_name"] = None
                return plan

        if is_already_rebooted_reply(text) and (
            label in ["failed", "refuse"]
            or (allow_keyword_step_fallback(memory) and (is_failed_reply(text) or contains_any(text, ["不行", "不能", "無法", "沒用", "一樣"])))
        ):
            known["issue_description"] = known.get("issue_description") or "網路無法連線，使用者已重開設備但仍無法恢復"
            return switch_to_repair(memory, plan)

        if contains_any(text, ["紅燈", "亮紅", "閃紅", "沒亮", "不亮", "異常"]):
            known["affected_scope"] = "unknown"
            known["modem_light_status"] = "abnormal"
            known["issue_description"] = "網路異常，數據機燈號異常"
            known["troubleshooting_step"] = "net_reboot_modem"
            known["retry"] = 0
            plan["reply"] = "了解，數據機燈號看起來異常。請您先將數據機電源拔掉約 10 秒後重新插上，等待 3 到 5 分鐘後，再確認是否可以上網。"
            return plan

        if contains_any(text, ["有亮燈", "有亮", "正常亮", "綠燈", "白燈", "藍燈"]):
            known["affected_scope"] = "unknown"
            known["modem_light_status"] = "normal"
            known["troubleshooting_step"] = "net_reboot_modem"
            known["retry"] = 0
            plan["reply"] = "了解，數據機有亮燈的話，我們先重開數據機。請將電源拔掉約 10 秒後重新插上，等待 3 到 5 分鐘後，再確認網路是否恢復。"
            return plan

        if is_multi_device_network_issue(text):
            return move_to_modem_light_check(memory, plan, text)

        if is_game_or_app_network_issue(text) and is_network_unstable_issue(text):
            known["troubleshooting_step"] = "net_slow_specific"
            known["retry"] = 0
            known["issue_description"] = text
            plan["reply"] = (
                "了解，遊戲或特定 APP 玩到一半斷線，可能與 Wi-Fi、設備或特定服務連線有關。"
                "請先確認其他網站或 APP 是否也會不穩；如果其他設備也會斷線，我們就往數據機與線路方向確認。"
            )
            plan["should_call_tool"] = False
            plan["tool_name"] = None
            return plan

        if is_line_level_network_outage(text):
            return move_to_modem_light_check(memory, plan, text)

        if contains_any(text, ["全部", "所有", "都不能", "都不行", "手機電腦都不行"]):
            known["affected_scope"] = "all_devices"
            known["troubleshooting_step"] = "net_check_modem_light"
            known["retry"] = 0
            plan["reply"] = "了解。請幫我確認數據機目前燈號是否有亮紅燈、閃爍異常，或完全沒亮燈？"
            return plan

        if contains_any(text, ["只有", "單一", "一台", "手機", "電腦"]):
            known["affected_scope"] = "single_device"
            known["troubleshooting_step"] = "net_single_device"
            known["retry"] = 0
            plan["reply"] = (
                "如果只有單一設備不能上網，請先確認該設備是否連到正確 Wi-Fi，"
                "也可以先關閉 Wi-Fi 後重新連線。請問重新連線後是否恢復？"
            )
            return plan

        if label == "unknown" or fallback_unknown(memory, text):
            known["affected_scope"] = "unknown"
            known["troubleshooting_step"] = "net_check_modem_light"
            known["retry"] = 0
            plan["reply"] = "沒關係，我們先從數據機確認。請問數據機目前燈號是否有亮紅燈、閃爍異常，或完全沒亮燈？"
            return plan

        if label in ["failed", "refuse"]:
            known["affected_scope"] = "unknown"
            known["troubleshooting_step"] = "net_check_modem_light"
            known["retry"] = 0
            plan["reply"] = "了解，我先不重複問設備範圍。我們改從數據機確認，請問數據機目前燈號是否有亮紅燈、閃爍異常，或完全沒亮燈？"
            return plan

        plan["reply"] = "請問是所有設備都不能上網，還是只有單一手機或電腦不能上網？"
        return plan

    if step == "net_check_modem_light":
        if is_already_rebooted_reply(text) and (
            label in ["failed", "refuse"]
            or (allow_keyword_step_fallback(memory) and (is_failed_reply(text) or contains_any(text, ["不行", "不能", "無法", "沒用", "一樣"])))
        ):
            known["issue_description"] = known.get("issue_description") or "網路異常，使用者已重開數據機但仍無法恢復"
            return switch_to_repair(memory, plan)

        if is_multi_device_network_issue(text):
            known["issue_description"] = text
            known["troubleshooting_step"] = "net_reboot_modem"
            known["retry"] = 0
            plan["reply"] = "了解，既然手機與電腦都不穩，我們先重開數據機。請將數據機電源拔掉約 10 秒後重新插上，等待 3 到 5 分鐘後，再確認網路是否恢復。"
            return plan

        if contains_any(text, ["紅燈", "亮紅", "閃紅", "沒亮", "不亮", "異常"]):
            known["modem_light_status"] = "abnormal"
            known["issue_description"] = "網路異常，數據機燈號異常"
            known["troubleshooting_step"] = "net_reboot_modem"
            known["retry"] = 0
            plan["reply"] = "請您先將數據機電源拔掉約 10 秒後重新插上，等待 3 到 5 分鐘後，再確認是否可以上網。"
            return plan

        if contains_any(text, ["正常", "都有亮", "綠燈", "白燈", "藍燈"]):
            known["modem_light_status"] = "normal"
            known["troubleshooting_step"] = "net_reboot_modem"
            known["retry"] = 0
            plan["reply"] = "燈號正常的話，請您先將數據機電源拔掉約 10 秒後重新插上，等待 3 到 5 分鐘後，再確認是否可以上網。"
            return plan

        if label == "unknown" or fallback_unknown(memory, text):
            known["modem_light_status"] = "unknown"
            known["troubleshooting_step"] = "net_reboot_modem"
            known["retry"] = 0
            plan["reply"] = (
                "沒關係，不用判斷燈號。我們先做最簡單的重開步驟："
                "請您將數據機電源拔掉約 10 秒後重新插上，等待 3 到 5 分鐘後，再確認網路是否恢復。"
            )
            return plan

        if label in ["failed", "refuse"]:
            known["modem_light_status"] = "unknown"
            known["troubleshooting_step"] = "net_reboot_modem"
            known["retry"] = 0
            plan["reply"] = (
                "了解，先不用看太細的燈號。我們先做最簡單的重開步驟："
                "請您將數據機電源拔掉約 10 秒後重新插上，等待 3 到 5 分鐘後，再確認網路是否恢復。"
            )
            return plan

        plan["reply"] = "請問數據機燈號目前是正常亮燈、亮紅燈、閃爍異常，還是完全沒亮燈？"
        return plan

    if step == "net_reboot_modem":
        if contains_any(text, ["紅燈", "亮紅", "閃紅", "一直閃", "燈號異常", "異常"]):
            known["modem_light_status"] = "abnormal"
            known["issue_description"] = "網路不穩，數據機燈號異常"
            return switch_to_repair(memory, plan)

        if (label == "unknown" or fallback_unknown(memory, text)) and contains_any(text, ["燈", "燈號", "哪個燈"]):
            known["troubleshooting_step"] = "net_reboot_modem"
            known["retry"] = 0
            plan["reply"] = (
                "沒關係，不用判斷是哪個燈。請先將數據機電源拔掉約 10 秒後重新插上，"
                "等待 3 到 5 分鐘後，再確認網路是否恢復。"
            )
            plan["should_call_tool"] = False
            plan["tool_name"] = None
            return plan

        if is_already_rebooted_reply(text):
            if label == "recovered" or fallback_recovered(memory, text):
                return finish_troubleshooting(memory, plan)
            known["issue_description"] = known.get("issue_description") or "網路無法連線，重開數據機後仍無法恢復"
            return switch_to_repair(memory, plan)

        if is_multi_device_network_issue(text):
            persistent_context = has_persistent_modem_instability_context(memory)
            known["issue_description"] = text
            compact = text.replace(" ", "").replace("　", "")
            if persistent_context or contains_any(compact, ["兩邊都不穩", "都不穩", "都一樣不穩"]):
                return switch_to_repair(memory, plan)
            plan["reply"] = (
                "了解，手機 Wi-Fi 和電腦有線都會不穩，先以數據機或線路方向處理。"
                "請先將數據機電源拔掉約 10 秒後重新插上，等待 3 到 5 分鐘後，再確認網路是否恢復穩定。"
            )
            plan["should_call_tool"] = False
            plan["tool_name"] = None
            return plan

        if label == "refuse":
            known["issue_description"] = known.get("issue_description") or "網路無法連線，重開數據機後仍無法恢復"
            return switch_to_repair(memory, plan)

        if label == "failed" or fallback_failed(memory, text):
            if is_already_rebooted_reply(text):
                known["issue_description"] = known.get("issue_description") or "網路無法連線，重開數據機後仍無法恢復"
                return switch_to_repair(memory, plan)
            known["troubleshooting_step"] = "net_reboot_modem"
            known["retry"] = 0
            plan["reply"] = (
                "目前還無法確認是否已完成數據機重開。請先將數據機電源拔掉約 10 秒後重新插上，"
                "等待 3 到 5 分鐘，再告訴我網路是否恢復；若您已經重開過，也請直接告訴我結果。"
            )
            plan["should_call_tool"] = False
            plan["tool_name"] = None
            return plan

        if label == "recovered" or fallback_recovered(memory, text):
            return finish_troubleshooting(memory, plan)

        if label == "unknown" or fallback_unknown(memory, text):
            known["retry"] = known.get("retry", 0) + 1
            if known["retry"] >= 2:
                known["issue_description"] = known.get("issue_description") or "網路連線不穩，使用者無法確認數據機燈號或重開後狀態"
                return switch_to_repair(memory, plan)
            plan["reply"] = (
                "我再確認一下：您重開數據機後，網路是恢復了、仍然速度慢，"
                "還是完全不能上網？若您是用網路線或網路孔測試，也可以直接說明目前接法。"
            )
            plan["should_call_tool"] = False
            plan["tool_name"] = None
            return plan

        plan["reply"] = "重開數據機後，網路是否已恢復？如果還是不行，我可以協助您建立報修工單。"
        return plan

    if step == "net_single_device":
        if is_multi_device_network_issue(text):
            return move_to_modem_light_check(memory, plan, text)

        if label in ["failed", "refuse"] or fallback_failed(memory, text):
            known["issue_description"] = "單一設備無法連線，重新連線後仍無法恢復"
            known["troubleshooting_step"] = "net_check_scope"
            known["awaiting_other_devices_after_single_failure"] = "yes"
            known["retry"] = 0
            plan["reply"] = "了解。那請問其他手機或電腦是否可以正常上網？"
            return plan

        if label == "recovered" or fallback_recovered(memory, text):
            return finish_troubleshooting(memory, plan)

        plan["reply"] = "重新連線 Wi-Fi 後，該設備是否已可以上網？"
        return plan

    plan["reply"] = "我再確認一下，目前是所有設備都不能上網，還是只有單一設備不能上網？"
    return plan


def apply_troubleshooting_engine(
    user_text: str,
    memory: Dict[str, Any],
    plan: Dict[str, Any],
    llm=None,
) -> Dict[str, Any]:
    known = memory.setdefault("known_info", {})
    text = (user_text or "").strip()

    # These flows are entered from the LLM's semantic intent, then continued
    # from trusted state. They do not infer a route from customer keywords.
    if known.get("troubleshooting_type") == "set_top_box_network":
        return continue_set_top_box_network_troubleshooting(
            text,
            memory,
            plan,
            llm=llm,
        )
    if plan.get("intent") in SET_TOP_BOX_NETWORK_INTENTS:
        return start_set_top_box_network_troubleshooting(text, memory, plan)

    if known.get("troubleshooting_step") == "net_router_path_check":
        return continue_router_path_troubleshooting(
            text,
            memory,
            plan,
            llm=llm,
        )
    if plan.get("intent") in ROUTER_PATH_SLOW_INTENTS:
        return start_router_path_troubleshooting(text, memory, plan)

    if (
        known.get("troubleshooting_started") != "yes"
        and plan.get("intent") == "repair_troubleshooting_intake"
    ):
        troubleshooting_type = detect_troubleshooting_type(text)
        if troubleshooting_type:
            return start_troubleshooting_by_type(
                troubleshooting_type,
                text,
                memory,
                plan,
            )
        return ask_fault_category(memory, plan)

    if is_tv_authorization_expired_issue(text):
        return reply_tv_authorization_payment(memory, plan)
    if is_tv_unauthorized_channel_issue(text):
        return reply_tv_unauthorized_channel_check(memory, plan)

    if is_outdoor_service_line_issue(text):
        known["issue_description"] = text
        return switch_to_repair(
            memory,
            plan,
            reply=(
                "室外線路鬆脫可能有安全風險，請勿自行碰觸或嘗試接回。"
                "此狀況不適合自行排除，請問是否需要幫您轉接真人文字客服安排檢查？"
            ),
        )

    if (
        known.get("repair_followup_active") == "yes"
        and plan.get("intent") == "repair_ticket_request"
    ):
        prior_issue = str(known.get("issue_description") or "")
        if is_outdoor_service_line_issue(prior_issue):
            reply = (
                "若您確認室外線路確實有鬆脫，請勿自行碰觸或嘗試接回；"
                "請問是否需要幫您轉接真人文字客服安排工程人員檢查？"
            )
        else:
            reply = (
                "已收到您的故障回報。"
                "請問是否需要幫您轉接真人文字客服安排後續檢查？"
            )
        return switch_to_repair(memory, plan, reply=reply)

    # Once the same picture-quality issue has reached repair, continuing
    # symptoms should stay in that flow instead of restarting channel rescan.
    repair_picture_context = parse_troubleshooting_context(text)
    if (
        known.get("repair_followup_active") == "yes"
        and known.get("repair_flow_status") == "disabled"
        and known.get("troubleshooting_type") == "tv"
        and known.get("troubleshooting_failed") == "yes"
        and (
            plan.get("intent") in TV_PICTURE_QUALITY_INTENTS
            or repair_picture_context.get("symptom_type") == "picture_quality"
        )
    ):
        return switch_to_repair(
            memory,
            plan,
            reply=(
                "已記錄畫面仍有抖動或異音，不需要再重複恢復預設或重新搜頻。"
                "請問是否需要幫您轉接真人文字客服處理？"
            ),
        )

    # Keep the model's current-turn semantic decision authoritative. A prior
    # repair hand-off must not turn a newly described picture-quality symptom
    # into a generic hand-off or consume it as an answer to an old SOP step.
    if (
        plan.get("intent") in TV_PICTURE_QUALITY_INTENTS
        and known.get("troubleshooting_started") != "yes"
    ):
        if is_tv_signal_or_playback_issue(text):
            known.pop("repair_followup_active", None)
            known.pop("repair_flow_status", None)
            return start_tv_troubleshooting(text, memory, plan)
        known.pop("repair_followup_active", None)
        known.pop("repair_flow_status", None)
        known["troubleshooting_started"] = "yes"
        known["troubleshooting_type"] = "tv"
        known["troubleshooting_step"] = "tv_rescan_channels"
        known["troubleshooting_failed"] = "no"
        known["repair_ready"] = "no"
        known["issue_description"] = text
        known["retry"] = 0
        plan["reply"] = build_channel_rescan_reply()
        plan["should_call_tool"] = False
        plan["tool_name"] = None
        return plan

    # A DS-light question provides actionable network status, even after a
    # repair hand-off was suggested. Answer it before retaining the hand-off.
    if (
        known.get("troubleshooting_type") == "network"
        and is_ds_light_status_question(text)
    ):
        known.pop("repair_followup_active", None)
        known.pop("repair_flow_status", None)
        known["troubleshooting_started"] = "yes"
        known["troubleshooting_failed"] = "no"
        known["repair_ready"] = "no"
        known["troubleshooting_step"] = "net_reboot_modem"
        known["issue_description"] = "數據機 DS 燈持續閃爍，網路尚未恢復"
        known["retry"] = 0
        plan["reply"] = (
            "DS 燈閃爍通常表示數據機正在同步下行訊號；剛重新啟動時短暫閃爍是正常的。"
            "但若等待 3 到 5 分鐘後仍持續閃爍且無法上網，表示尚未完成同步，"
            "建議由客服協助確認線路或安排檢修。"
        )
        plan["should_call_tool"] = False
        plan["tool_name"] = None
        return plan

    # A disabled repair hand-off should retain terse continuations such as
    # "還是沒好", but a concrete new TV symptom must re-enter the relevant SOP.
    if (
        known.get("repair_followup_active") == "yes"
        and known.get("troubleshooting_type") == "tv"
        and (is_tv_equipment_boot_issue(text) or is_tv_boot_loop_reply(text))
    ):
        if is_tv_boot_loop_reply(str(known.get("issue_description") or "")):
            return switch_to_repair(
                memory,
                plan,
                reply=(
                    "已記錄機上盒重開後仍停在開機畫面，不需要再重複重新插電。"
                    "請問是否需要幫您轉接真人文字客服處理？"
                ),
            )
        known.pop("repair_followup_active", None)
        known.pop("repair_flow_status", None)
        known["troubleshooting_started"] = "yes"
        known["troubleshooting_failed"] = "no"
        known["repair_ready"] = "no"
        known["troubleshooting_step"] = "tv_reboot"
        known["issue_description"] = "機上盒持續重複開機或停在開機畫面"
        known["retry"] = 0
        plan["reply"] = (
            "了解，機上盒持續重複開機或停在開機畫面時，請先將機上盒電源拔掉約 10 秒後重新插上，"
            "等待 2 到 3 分鐘確認是否能正常完成開機。若仍持續重複開機，再協助安排維修。"
        )
        plan["should_call_tool"] = False
        plan["tool_name"] = None
        return plan

    # A concrete "no program" screen is actionable TV evidence. It must not
    # remain trapped in a prior repair follow-up created from an earlier vague
    # reply.
    if known.get("repair_followup_active") == "yes" and is_tv_no_program_display_issue(text):
        known.pop("repair_followup_active", None)
        known.pop("repair_flow_status", None)
        known["troubleshooting_started"] = "yes"
        known["troubleshooting_type"] = "tv"
        known["troubleshooting_step"] = "tv_rescan_channels"
        known["troubleshooting_failed"] = "no"
        known["repair_ready"] = "no"
        known["issue_description"] = "機上盒顯示沒有節目並卡住"
        known["retry"] = 0
        plan["reply"] = build_channel_rescan_reply()
        plan["should_call_tool"] = False
        plan["tool_name"] = None
        return plan

    if (
        known.get("repair_followup_active") == "yes"
        and repair_picture_context.get("symptom_type") == "picture_quality"
    ):
        known.pop("repair_followup_active", None)
        known.pop("repair_flow_status", None)
        known["troubleshooting_started"] = "yes"
        known["troubleshooting_type"] = "tv"
        known["troubleshooting_step"] = "tv_rescan_channels"
        known["troubleshooting_failed"] = "no"
        known["repair_ready"] = "no"
        known["issue_description"] = text
        known["retry"] = 0
        plan["reply"] = build_channel_rescan_reply()
        plan["should_call_tool"] = False
        plan["tool_name"] = None
        return plan

    repair_context_active = (
        known.get("repair_ready") == "yes"
        or known.get("repair_followup_active") == "yes"
    )
    has_known_speed_gap = (
        known.get("troubleshooting_type") == "network"
        and isinstance(known.get("declared_plan_speed_mbps"), (int, float))
        and isinstance(known.get("download_speed"), (int, float))
        and plan.get("intent") == "internet_slow_buffering"
    )
    has_known_tv_no_power = (
        known.get("troubleshooting_type") == "tv"
        and contains_any(
            str(known.get("issue_description") or ""),
            ("電源燈不亮", "沒有亮燈", "無亮燈", "沒亮燈"),
        )
        and plan.get("intent") in {
            "tv_set_top_box_unresponsive_issue",
            "tv_set_top_box_power_no_light_issue",
        }
    )
    if repair_context_active and (
        is_explicit_repair_request(text)
        or is_failed_reply(text)
        or is_refuse_reply(text)
        or is_unknown_reply(text)
        or is_repair_context_continuation(text)
        or has_declared_speed_gap(text)
        or has_known_speed_gap
        or has_known_tv_no_power
    ):
        known["troubleshooting_started"] = "no"
        known["troubleshooting_failed"] = "yes"
        known["repair_followup_count"] = known.get("repair_followup_count", 0) + 1
        if known.get("repair_followup_active") == "yes":
            if has_known_speed_gap:
                declared = float(known["declared_plan_speed_mbps"])
                measured = float(known["download_speed"])
                reply = (
                    f"已保留您申辦 {declared:g} Mbps、實測約 {measured:g} Mbps 的結果，"
                    "不需要再重複測速。請問是否需要幫您轉接真人文字客服處理？"
                )
            elif has_known_tv_no_power:
                reply = (
                    "已記錄機上盒有插電但電源燈仍未亮，不需要再重複確認燈號。"
                    "請問是否需要幫您轉接真人文字客服處理？"
                )
            else:
                reply = (
                    "已收到您補充的狀況。"
                    "請問是否需要幫您轉接真人文字客服協助後續處理？"
                )
            return switch_to_repair(memory, plan, reply=reply)
        return switch_to_repair(memory, plan)

    # The marker only carries a related short continuation. A clear new topic
    # must be allowed to route normally instead of being held in repair mode.
    if known.get("repair_followup_active") == "yes":
        known.pop("repair_followup_active", None)

    # Preserve LLM-derived fault types before generic phrases such as "故障"
    # fall back to an undifferentiated category question.
    if (
        known.get("troubleshooting_started") != "yes"
        and plan.get("intent") in REMOTE_CONTROL_TROUBLESHOOTING_INTENTS
    ):
        return start_remote_control_troubleshooting(text, memory, plan)

    if (
        known.get("troubleshooting_started") != "yes"
        and plan.get("intent") == "internet_slow_buffering"
    ):
        known["issue_description"] = text
        return build_network_slow_reply(memory, plan)

    if (
        known.get("troubleshooting_started") != "yes"
        and plan.get("intent") == "internet_connection_issue"
    ):
        return start_network_troubleshooting(text, memory, plan)

    if (
        known.get("troubleshooting_started") != "yes"
        and plan.get("intent") in {
            "tv_viewing_interruption_issue",
            "tv_signal_or_playback_issue",
        }
    ):
        return start_tv_troubleshooting(text, memory, plan)

    if (
        known.get("troubleshooting_started") != "yes"
        and plan.get("intent") == "tv_no_program_display_issue"
    ):
        known["troubleshooting_started"] = "yes"
        known["troubleshooting_type"] = "tv"
        known["troubleshooting_step"] = "tv_rescan_channels"
        known["troubleshooting_failed"] = "no"
        known["repair_ready"] = "no"
        known["retry"] = 0
        known["issue_description"] = "機上盒顯示沒有節目或停在沒有節目畫面"
        plan["reply"] = build_channel_rescan_reply()
        plan["should_call_tool"] = False
        plan["tool_name"] = None
        return plan

    if (
        known.get("troubleshooting_started") != "yes"
        and plan.get("intent") in ROUTER_REGISTRATION_INTENTS
    ):
        known["troubleshooting_started"] = "yes"
        known["troubleshooting_type"] = "network"
        known["troubleshooting_failed"] = "no"
        known["repair_ready"] = "no"
        return apply_network_troubleshooting_step(
            text,
            memory,
            plan,
            "device_replacement",
        )

    # 第一次進入排錯
    if (
        known.get("troubleshooting_started") != "yes"
        and is_explicit_repair_request(text)
        and bool(known.get("issue_description"))
        and not is_fault(text)
        and not is_network_slow_issue(text)
    ):
        known["issue_description"] = text
        return switch_to_repair(memory, plan)

    if known.get("troubleshooting_started") != "yes" and is_direct_fault_report(text):
        return ask_fault_category(memory, plan)

    if known.get("troubleshooting_started") != "yes" and is_general_signal_fault_report(text):
        known["issue_description"] = text
        return ask_fault_category(memory, plan)

    # The router has already made a semantic decision for terse reports such as
    # "哈TV 頻道不見". Preserve that decision instead of requiring the same
    # meaning to match a second keyword-only detector.
    if (
        known.get("troubleshooting_started") != "yes"
        and plan.get("intent") == "tv_partial_channel_issue"
    ):
        known["troubleshooting_started"] = "yes"
        known["troubleshooting_type"] = "tv"
        known["troubleshooting_step"] = "tv_rescan_channels"
        known["troubleshooting_failed"] = "no"
        known["repair_ready"] = "no"
        known["retry"] = 0
        known["issue_description"] = text
        plan["reply"] = build_channel_rescan_reply()
        plan["should_call_tool"] = False
        plan["tool_name"] = None
        return plan

    if (
        known.get("troubleshooting_started") != "yes"
        and plan.get("intent") == "tv_set_top_box_unresponsive_issue"
    ):
        return start_tv_troubleshooting(text, memory, plan)

    if (
        known.get("troubleshooting_started") != "yes"
        and plan.get("intent") == "tv_tutorial_screen_stuck_issue"
    ):
        return start_tv_tutorial_screen_troubleshooting(text, memory, plan)

    if (
        known.get("troubleshooting_started") != "yes"
        and plan.get("intent") == "tv_set_top_box_boot_issue"
    ):
        known["troubleshooting_started"] = "yes"
        known["troubleshooting_type"] = "tv"
        known["troubleshooting_step"] = "tv_reboot"
        known["troubleshooting_failed"] = "no"
        known["repair_ready"] = "no"
        known["retry"] = 0
        known["issue_description"] = text
        plan["reply"] = (
            "了解，機上盒持續重複開機或停在開機畫面時，請先將機上盒電源拔掉約 10 秒後重新插上，"
            "等待 2 到 3 分鐘確認是否能正常完成開機。若仍持續重複開機，再協助安排維修。"
        )
        plan["should_call_tool"] = False
        plan["tool_name"] = None
        return plan

    if known.get("troubleshooting_started") != "yes" and (
        is_fault(text)
        or (is_network_slow_issue(text) and contains_any(text, ["網路", "網速", "速度", "連線"]))
    ):
        return start_troubleshooting(text, memory, plan)

    # 不在排錯中，直接返回
    if known.get("troubleshooting_started") != "yes":
        return plan

    step = known.get("troubleshooting_step")
    if known.get("troubleshooting_type") == "network":
        declared, measured = record_declared_speed_gap(known, text)
        if is_substantially_below_declared_speed(declared, measured):
            known["issue_description"] = (
                f"申辦速率 {declared:g} Mbps，實測約 {measured:g} Mbps"
            )
            if known.get("speed_retest_requested") == "yes":
                return switch_to_repair(memory, plan)
            known["troubleshooting_step"] = "net_speed_retest"
            known["speed_retest_requested"] = "yes"
            plan["reply"] = build_declared_speed_retest_reply(declared, measured)
            plan["should_call_tool"] = False
            plan["tool_name"] = None
            return plan

        download, upload = record_network_speed_result(known, text)
        if is_clearly_abnormal_download_speed(known, download):
            known["issue_description"] = (
                f"網路測速下載僅 {download:g} Mbps"
                + (f"、上傳 {upload:g} Mbps" if upload is not None else "")
                + "，重開數據機後仍明顯異常"
            )
            return switch_to_repair(memory, plan)

    explicit_type = detect_troubleshooting_type(text)
    # 使用者可在任何排錯步驟表示已恢復或停止，不應被當成答非所問而重複提問。
    if is_recovered_reply(text):
        return finish_troubleshooting(memory, plan)

    if is_stop_troubleshooting_reply(text):
        return stop_troubleshooting(memory, plan)

    if explicit_type == "remote" and known.get("troubleshooting_type") != "remote":
        return start_remote_control_troubleshooting(text, memory, plan)

    if (
        known.get("troubleshooting_type") == "network"
        and isinstance(known.get("declared_plan_speed_mbps"), (int, float))
        and isinstance(known.get("download_speed"), (int, float))
        and (is_flow_rejection_reply(text) or is_correction_reply(text) or is_confusion_reply(text))
    ):
        declared = float(known["declared_plan_speed_mbps"])
        measured = float(known["download_speed"])
        known["retry"] = 0
        if known.get("speed_retest_requested") == "yes":
            return switch_to_repair(memory, plan)
        known["troubleshooting_step"] = "net_speed_retest"
        known["speed_retest_requested"] = "yes"
        plan["reply"] = build_declared_speed_retest_reply(declared, measured)
        plan["should_call_tool"] = False
        plan["tool_name"] = None
        return plan

    if is_flow_rejection_reply(text):
        known["flow_rejection_count"] = known.get("flow_rejection_count", 0) + 1
        if known["flow_rejection_count"] >= 2:
            return reset_to_fault_category(
                memory,
                plan,
                "了解，目前方向可能不對，我們重新確認一次。",
            )
        plan["reply"] = (
            "了解，那我先不沿用剛剛的判斷。"
            "請問您現在主要是電視、網路、遙控器/機上盒，還是想直接報修？"
        )
        plan["should_call_tool"] = False
        plan["tool_name"] = None
        return plan

    if is_correction_reply(text) or is_confusion_reply(text):
        if explicit_type:
            return start_troubleshooting(text, memory, plan)
        return reset_to_fault_category(
            memory,
            plan,
            "沒問題，我們先停一下，重新確認方向。",
        )

    if step == "ask_fault_category":
        if explicit_type:
            return start_troubleshooting(text, memory, plan)
        category = detect_fault_category_selection(text)
        if category:
            category_text = build_fault_category_context_text(text, memory)
            return start_troubleshooting_by_type(category, category_text, memory, plan)
        semantic_category = classify_fault_category_by_llm(text, memory, llm=llm)
        if semantic_category:
            category_text = build_fault_category_context_text(text, memory)
            return start_troubleshooting_by_type(semantic_category, category_text, memory, plan)
        known["category_retry"] = known.get("category_retry", 0) + 1
        if known["category_retry"] >= 3:
            known["issue_description"] = known.get("issue_description") or "使用者無法明確描述故障類型"
            return switch_to_repair(memory, plan)
        if known["category_retry"] >= 2:
            plan["reply"] = (
                "我換個方式問，請直接回覆「電視」、「網路」或「遙控器/機上盒」。"
                "如果不確定，也可以描述目前看到的畫面、燈號或網路狀況。"
            )
            plan["should_call_tool"] = False
            plan["tool_name"] = None
            return plan
        plan["reply"] = (
            "請問目前遇到的是電視、網路，還是其他設備問題？"
            "也可以直接描述狀況，例如：訊號不良、完全斷線、網速變慢、畫面 lag。"
        )
        plan["should_call_tool"] = False
        plan["tool_name"] = None
        return plan

    compact_text = text.replace(" ", "").replace("　", "")
    if (
        known.get("troubleshooting_type") == "network"
        and compact_text in {"網路排除", "網路故障排除", "寬頻排除", "寬頻故障排除"}
    ):
        known["affected_scope"] = known.get("affected_scope") or "unknown"
        known["troubleshooting_step"] = "net_reboot_modem"
        known["retry"] = 0
        plan["reply"] = (
            "已在處理網路無法連線，我們先做最簡單的重開步驟："
            "請將數據機與分享器電源拔掉約 10 秒後重新插上，等待 3 到 5 分鐘後，"
            "再確認網路是否恢復。"
        )
        plan["should_call_tool"] = False
        plan["tool_name"] = None
        return plan

    known["_llm_step_classifier_used"] = "yes" if llm is not None else "no"
    label = classify_reply(
        text,
        step,
        issue_description=known.get("issue_description") or "",
        llm=llm,
    )

    # Short terms such as "故障" and "回報故障" often mean that the customer
    # wants help with the current symptom. They must continue the SOP even if
    # the step classifier marks them as refusal. A repair hand-off is reserved
    # for a clear request to create a repair action after diagnosis has begun.
    if is_explicit_repair_handoff_request(text):
        known["issue_description"] = known.get("issue_description") or text
        return switch_to_repair(memory, plan)

    print("==== TROUBLESHOOTING ====")
    print({
        "type": known.get("troubleshooting_type"),
        "step": step,
        "label": label,
    })

    known["retry"] = known.get("retry", 0) + 1

    if known["retry"] > 2:
        return switch_to_repair(memory, plan)

    if label == "recovered":
        return finish_troubleshooting(memory, plan)

    if label == "refuse" and is_explicit_repair_request(text):
        known["issue_description"] = known.get("issue_description") or text
        return switch_to_repair(memory, plan)

    if label == "fault_report" and known.get("troubleshooting_type") == "network":
        return move_to_modem_light_check(
            memory,
            plan,
            known.get("issue_description") or "網路故障",
        )

    if is_partial_channel_issue(text):
        known["troubleshooting_type"] = "tv"
        known["troubleshooting_step"] = "tv_rescan_channels"
        known["issue_description"] = text
        known["retry"] = 0
        plan["reply"] = build_channel_rescan_reply()
        plan["should_call_tool"] = False
        plan["tool_name"] = None
        return plan

    if step == "tv_check_input_source" and (
        label in ["negative", "failed"]
        or (allow_keyword_step_fallback(memory) and is_input_source_not_recovered_reply(text))
    ):
        return apply_tv_troubleshooting_step(text, memory, plan, "failed")

    is_reboot_light_clarification = (
        step == "net_reboot_modem"
        and label == "unknown"
        and contains_any(text, ["燈", "燈號", "哪個燈"])
    )
    is_tv_reboot_unknown = step == "tv_reboot" and label == "unknown"
    is_unconfirmed_network_reboot_failure = (
        step == "net_reboot_modem"
        and label == "failed"
        and not is_already_rebooted_reply(text)
    )
    if (
        label in ["failed", "refuse"]
        and step in {"net_reboot_modem", "tv_reboot"}
        and not is_reboot_light_clarification
        and not is_tv_reboot_unknown
        and not is_unconfirmed_network_reboot_failure
        and not (
            step == "net_reboot_modem"
            and contains_any(text, ["電腦不能上網", "電腦無法上網", "電腦連不上網"])
        )
    ):
        return switch_to_repair(memory, plan)

    troubleshooting_type = known.get("troubleshooting_type")

    if troubleshooting_type == "network":
        return apply_network_troubleshooting_step(text, memory, plan, label)

    if troubleshooting_type == "remote":
        return apply_remote_control_troubleshooting_step(text, memory, plan, label)

    return apply_tv_troubleshooting_step(text, memory, plan, label)
