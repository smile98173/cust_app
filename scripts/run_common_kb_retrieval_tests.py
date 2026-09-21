from __future__ import annotations

import html
import json
import os
import sys
import time
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any

import requests
from dotenv import dotenv_values


ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

BACKEND_URL = os.getenv("KB_COMMON_TEST_BACKEND", "http://127.0.0.1:8123").rstrip("/")
OUTPUT_DIR = ROOT_DIR / "reports"
REQUEST_TIMEOUT = float(os.getenv("KB_COMMON_TEST_REQUEST_TIMEOUT", "35"))
CASE_FILTER = {
    value.strip().upper()
    for value in os.getenv("KB_COMMON_TEST_CASE_IDS", "").split(",")
    if value.strip()
}

DOCS = {
    "stb": "abea9a9eee5b464fbe4fd8120b8af73f",
    "fifa": "6720a0194846431ebd7f2510b8285ca2",
    "network": "612c7c09feb64593b71d83fdfa33e9c3",
    "value_added": "7e7f5f3fe3b64f48a80e28993d261a5e",
    "single_sales": "f06c6752f0b3481bbf1389350b1846e9",
    "billing": "a8e7ccf7a95f404faa174450f0c6285c",
    "jiannan_test": "340554c26b674f50b38b6a5253290a7a",
    "jiannan_common": "1ea9af5939534184a838ff47067745dd",
}


def case(
    case_id: str,
    group: str,
    station: str,
    document: str,
    question: str,
    expected_any: list[str],
    *,
    variant: str,
    knowledge_gap: bool = False,
    expected_mode: str = "retrieval",
) -> dict[str, Any]:
    return {
        "id": case_id,
        "group": group,
        "station": station,
        "expected_document_id": DOCS[document],
        "question": question,
        "expected_any": expected_any,
        "variant": variant,
        "negative": False,
        "knowledge_gap": knowledge_gap,
        "expected_mode": expected_mode,
    }


def negative_case(
    case_id: str,
    group: str,
    station: str,
    forbidden_document: str,
    question: str,
    *,
    variant: str,
) -> dict[str, Any]:
    return {
        "id": case_id,
        "group": group,
        "station": station,
        "expected_document_id": DOCS[forbidden_document],
        "question": question,
        "expected_any": [],
        "variant": variant,
        "negative": True,
        "knowledge_gap": False,
        "expected_mode": "retrieval",
    }


CASES = [
    # 通用-中區：機上盒
    case("C01", "中區／機上盒", "大屯", "stb", "遙控器學習鍵要怎麼設定？", ["學習", "LED"], variant="口語"),
    case("C02", "中區／機上盒", "西海岸", "stb", "電視跳出 E003 是什麼意思？", ["E003", "未授權"], variant="錯誤碼"),
    case("C03", "中區／機上盒", "佳光市區", "stb", "為什麼 200 台以後都不能看？", ["付費頻道", "額外訂閱"], variant="口語"),
    case("C04", "中區／機上盒", "中投", "stb", "普通的電視遙控器一支多少錢？", ["300", "一般型"], variant="同義詞"),
    case("C05", "中區／機上盒", "佳聯", "stb", "機上盒 USB 孔可以插隨身碟看片嗎？", ["韌體", "無法使用"], variant="反向問法"),
    case("C06", "中區／機上盒", "北港", "stb", "我不想打電話，能不能直接線上叫修？", ["線上", "報修"], variant="口語"),
    case("C07", "中區／機上盒", "大屯", "stb", "電視畫面一直定格要怎麼處理？", ["定格", "電源"], variant="故障"),
    case("C08", "中區／機上盒", "中投", "stb", "機上盒的 HDMI 線多少錢？", ["HDMI", "200"], variant="配件"),

    # 通用-中區：網路寬頻
    case("C09", "中區／網路", "大屯", "network", "固定 IP 第二個開始要收多少？", ["200", "第二"], variant="追問式"),
    case("C10", "中區／網路", "西海岸", "network", "家裡可以跟你們借 WiFi 分享器嗎？", ["分享器", "租借"], variant="口語"),
    case("C11", "中區／網路", "佳光市區", "network", "Mesh WiFi 怎麼計費？", ["Mesh", "WIFI"], variant="產品名"),
    case("C12", "中區／網路", "中投", "network", "網路最近一直斷斷續續，很不穩", ["數據機", "重新啟動"], variant="症狀描述"),
    case("C13", "中區／網路", "佳聯", "network", "要限制小孩晚上上網，怎麼設定？", ["上網時間", "設定"], variant="需求描述"),
    case("C14", "中區／網路", "北港", "network", "數據機燈完全沒亮怎麼辦？", ["燈", "電源"], variant="故障"),
    case("C15", "中區／網路", "大屯", "network", "網速升級了但用起來還是沒有變快", ["測速"], variant="口語"),

    # 通用-中區：加值服務 CSV
    case("C16", "中區／加值服務", "大屯", "value_added", "熊大心是什麼服務？", ["熊搭心", "電視電話"], variant="同音錯字"),
    case("C17", "中區／加值服務", "西海岸", "value_added", "家裡長輩有適合的加值服務嗎？", ["熊搭心", "長者"], variant="需求描述"),
    case("C18", "中區／加值服務", "佳光市區", "value_added", "哈 Point 點數要怎麼拿？", ["紅利點數", "哈point"], variant="別名"),
    case("C19", "中區／加值服務", "中投", "value_added", "紅利點數放多久會過期？", ["期限", "點數"], variant="口語"),
    case("C20", "中區／加值服務", "佳聯", "value_added", "LINE TV 同一個帳號可以幾台一起看？", ["登入", "裝置"], variant="口語"),
    case("C21", "中區／加值服務", "北港", "value_added", "我不想續用 LINE TV，要怎麼取消？", ["取消", "LINE TV"], variant="需求描述"),
    case("C22", "中區／加值服務", "大屯", "value_added", "哈 NET 到底是什麼？", ["哈NET", "網路"], variant="產品名", knowledge_gap=True),
    case("C23", "中區／加值服務", "西海岸", "value_added", "你們有家用監視器或攝影機服務嗎？", ["監視器", "攝影"], variant="同義詞"),
    case("C24", "中區／加值服務", "中投", "value_added", "瑪帛要怎麼申裝？", ["瑪帛", "申"], variant="簡短問法"),
    case(
        "C25", "中區／加值服務", "大屯", "value_added", "熊溫馨是什麼？",
        ["熊搭心", "電視電話"], variant="名稱差距較大", expected_mode="clarification",
    ),

    # 通用-中區：單品銷售／加值服務 DOCX
    case("C26", "中區／單品銷售", "大屯", "single_sales", "WiFi 5 分享器年繳多少錢？", ["300", "WIFI 5"], variant="精確費用"),
    case("C27", "中區／單品銷售", "佳光市區", "single_sales", "WiFi 6 半年要付多少？", ["300", "WIFI 6"], variant="精確費用"),
    case("C28", "中區／單品銷售", "佳聯", "single_sales", "居家智慧攝影機租一年多少錢？", ["600", "攝影機"], variant="精確費用"),
    case("C29", "中區／單品銷售", "北港", "single_sales", "熊搭心有哪些收費方案？", ["瑪帛好友", "瑪帛夥伴"], variant="方案總覽"),
    case("C30", "中區／單品銷售", "中投", "single_sales", "LINE TV 買一年是多少？", ["1200", "LINE TV"], variant="精確費用"),

    # 通用-中區：帳務 Big5 CSV
    case("C31", "中區／帳務", "大屯", "billing", "ibon 要怎麼繳第四台費用？", ["7-Eleven", "ibon"], variant="操作流程"),
    case("C32", "中區／帳務", "西海岸", "billing", "全家的 FamiPort 要怎麼繳費？", ["FamiPort"], variant="操作流程"),
    case("C33", "中區／帳務", "佳光市區", "billing", "信用卡要怎麼線上繳？", ["信用卡", "線上"], variant="精確問法"),
    case("C34", "中區／帳務", "中投", "billing", "帳單沒有寄來，我還能去哪裡付款？", ["帳單", "繳費"], variant="情境問法"),
    case("C35", "中區／帳務", "佳聯", "billing", "ATM 的專屬繳款帳號在哪裡看？", ["ATM", "帳單"], variant="口語"),
    case("C36", "中區／帳務", "北港", "billing", "電子發票通常多久會拿到？", ["發票", "入帳"], variant="口語", knowledge_gap=True),
    case("C37", "中區／帳務", "大屯", "billing", "手機條碼載具要如何綁定？", ["載具", "綁定"], variant="同義詞", knowledge_gap=True),
    case("C38", "中區／帳務", "佳聯", "billing", "有線電視要退租需要帶什麼證件？", ["身分證", "退"], variant="申辦流程"),

    # 通用-中區：FIFA
    case("C39", "中區／賽事", "大屯", "fifa", "世界盃足球賽在哪幾台播？", ["台視", "東森"], variant="同義問法"),
    case("C40", "中區／賽事", "北港", "fifa", "世足轉播頻道是幾號？", ["CH07", "CH51"], variant="簡稱"),

    # 通用-中區：泛化與省略問法
    case("C41", "中區／泛化驗證", "大屯", "stb", "E003 未授權是什麼狀況？", ["E003", "未授權"], variant="錯誤碼省略主詞"),
    case("C42", "中區／泛化驗證", "佳聯", "stb", "一條 HDMI 訊號線要多少？", ["HDMI", "200"], variant="設備別名"),
    case("C43", "中區／泛化驗證", "北港", "network", "第二組固定 IP 每月會加多少錢？", ["200", "第二"], variant="同義問法"),
    case("C44", "中區／泛化驗證", "中投", "billing", "我想用信用卡繳第四台費用", ["信用卡", "線上"], variant="需求描述"),
    case("C45", "中區／泛化驗證", "西海岸", "fifa", "FIFA 世界盃在第幾台？", ["CH07", "CH51"], variant="英文別名"),
    case("C46", "中區／泛化驗證", "佳光市區", "value_added", "熊打心是照顧長輩的服務嗎？", ["熊搭心", "電視電話"], variant="同音錯字"),
    case("C47", "中區／泛化驗證", "大屯", "single_sales", "家用攝影機租半年怎麼算？", ["300", "攝影機"], variant="產品口語"),
    case("C48", "中區／泛化驗證", "佳聯", "value_added", "哈 POINT 可以拿來折抵費用嗎？", ["點數", "折抵"], variant="用途問法"),
    case("C49", "中區／泛化驗證", "北港", "stb", "一般遙控器壞了，買一支多少？", ["一般型", "300"], variant="省略設備名"),
    case("C50", "中區／泛化驗證", "中投", "stb", "畫面馬賽克又定格要先檢查什麼？", ["馬賽克", "電源"], variant="複合症狀"),

    # 通用-中區：同一份加值服務文件內的商品細項
    case("C51", "中區／加值商品細項", "大屯", "single_sales", "LINE TV 每個月多少錢？", ["LINE TV", "210"], variant="月繳費用"),
    case("C52", "中區／加值商品細項", "佳光市區", "single_sales", "LINE TV 買半年要多少？", ["LINE TV", "600"], variant="半年費用"),
    case("C53", "中區／加值商品細項", "中投", "single_sales", "WiFi 5 分享器月租多少？", ["WIFI 5", "25"], variant="月繳費用"),
    case("C54", "中區／加值商品細項", "佳聯", "single_sales", "WiFi 6 分享器年繳多少？", ["WIFI 6", "600"], variant="年繳費用"),
    case("C55", "中區／加值商品細項", "北港", "single_sales", "Mesh 一組母機加子機要怎麼算？", ["母機", "子機"], variant="組合計價"),
    case("C56", "中區／加值商品細項", "大屯", "single_sales", "居家智慧攝影機要綁約多久？", ["攝影機", "2"], variant="合約期間"),
    case("C57", "中區／加值商品細項", "佳光市區", "single_sales", "租攝影機需要自己準備記憶卡嗎？", ["記憶卡", "自備"], variant="設備需求"),
    case("C58", "中區／加值商品細項", "中投", "single_sales", "瑪帛用戶方案一個月多少？", ["瑪帛用戶", "49"], variant="子方案月費"),
    case("C59", "中區／加值商品細項", "佳聯", "single_sales", "瑪帛好友半年多少錢？", ["瑪帛好友", "414"], variant="子方案半年費"),
    case("C60", "中區／加值商品細項", "北港", "single_sales", "瑪帛夥伴的電視電話可以講多久？", ["瑪帛夥伴", "無限"], variant="功能限制"),
    case("C61", "中區／加值商品細項", "大屯", "single_sales", "熊搭心有包含哪些服務？", ["家庭相簿", "生活提醒"], variant="服務內容"),
    case("C62", "中區／加值商品細項", "佳光市區", "single_sales", "紅利點數可以拿來做什麼？", ["折抵", "服務費用"], variant="點數用途"),
    case("C63", "中區／加值商品細項", "中投", "single_sales", "哈 Point 點數是怎麼回饋的？", ["活動", "回饋"], variant="取得方式"),
    case("C64", "中區／加值商品細項", "佳聯", "single_sales", "攝影機弄壞要賠多少？", ["攝影機", "1,200"], variant="設備賠償", knowledge_gap=True),
    case("C65", "中區／加值商品細項", "北港", "single_sales", "LINE TV 到期後不想繼續可以取消嗎？", ["LINE TV", "取消"], variant="到期取消"),

    # 通用-中區：從實際 CSV 延伸的多樣口語測試
    case("C66", "中區／機上盒延伸", "大屯", "stb", "搖控器壞了，換一支要多少錢？", ["300", "400"], variant="錯字＋費用"),
    case("C67", "中區／機上盒延伸", "台灣佳光", "stb", "電視出現 E003 要切回哪一台？", ["E003", "100"], variant="錯誤碼追問"),
    case("C68", "中區／機上盒延伸", "佳光市區", "stb", "機上盒能不能錄節目？", ["無法", "錄"], variant="功能問法"),
    case("C69", "中區／機上盒延伸", "中投", "stb", "電視找不到 HDMI 輸入源怎麼辦？", ["HDMI", "輸入"], variant="操作症狀"),
    case("C70", "中區／機上盒延伸", "佳聯", "stb", "為什麼頻道超過 200 台就不能看？", ["付費頻道", "訂閱"], variant="頻道口語"),

    case("C71", "中區／網路延伸", "北港", "network", "第二組固定 IP 每個月加多少？", ["200", "固定"], variant="費用口語"),
    case("C72", "中區／網路延伸", "大屯", "network", "固定 IP 最多能申請幾組？", ["四組", "固定"], variant="數量限制"),
    case("C73", "中區／網路延伸", "台灣佳光", "network", "外面的網路線被車子勾斷了怎麼辦？", ["外線", "客服"], variant="事故描述"),
    case("C74", "中區／網路延伸", "佳光市區", "network", "我想讓小孩晚上十點後不能上網", ["上網時間", "設定"], variant="家長需求"),

    case("C75", "中區／加值服務延伸", "中投", "value_added", "LINE TV 一個帳號最多能登入幾台裝置？", ["LINE TV", "裝置"], variant="裝置數量"),
    case("C76", "中區／加值服務延伸", "佳聯", "value_added", "LINE TV 要怎麼掃 QR Code 登入電視？", ["QR", "掃描"], variant="登入操作"),
    case("C77", "中區／加值服務延伸", "北港", "value_added", "有沒有適合家中長輩使用的服務？", ["熊搭心", "長者"], variant="未說產品名"),
    case("C78", "中區／加值服務延伸", "大屯", "value_added", "家裡長輩回診可以用電視提醒嗎？", ["生活提醒"], variant="功能需求"),
    case("C79", "中區／加值服務延伸", "台灣佳光", "value_added", "哈 Point 紅利點數可以拿來做什麼？", ["點數", "折抵"], variant="別名＋用途"),

    case("C80", "中區／帳務延伸", "佳光市區", "billing", "全家的 FamiPort 要怎麼繳第四台？", ["FamiPort", "有線電視"], variant="通路操作"),
    case("C81", "中區／帳務延伸", "中投", "billing", "繳費後發票大概多久會收到？", ["發票", "天"], variant="寄送時間"),
    case("C82", "中區／帳務延伸", "佳聯", "billing", "帳單沒收到還可以怎麼繳？", ["帳單", "繳費"], variant="遺失帳單"),
    case("C83", "中區／帳務延伸", "北港", "billing", "有線電視費可以分期付款嗎？", ["分期", "沒有"], variant="付款限制"),
    case("C84", "中區／帳務延伸", "大屯", "billing", "發票要打公司統編要怎麼辦？", ["統編", "發票"], variant="公司報帳"),
    case("C85", "中區／帳務延伸", "台灣佳光", "billing", "ATM 轉帳的繳款帳號去哪裡看？", ["ATM", "帳單"], variant="轉帳資訊"),

    # 通用-嘉南區：故障／收費，同一資料分別從兩個系統台查詢
    case("J01", "嘉南／電視排錯", "新永安", "jiannan_common", "電視看到一半突然變藍畫面", ["HDMI", "輸入源"], variant="症狀描述"),
    case("J02", "嘉南／電視排錯", "大揚", "jiannan_common", "畫面正常但完全沒有聲音", ["重新插入", "有影無聲"], variant="同義問法"),
    case("J03", "嘉南／錯誤碼", "新永安", "jiannan_common", "螢幕顯示 E001 要怎麼處理？", ["晶片", "插入"], variant="錯誤碼"),
    case("J04", "嘉南／錯誤碼", "大揚", "jiannan_common", "E007 智慧卡配對過期怎麼辦？", ["1751", "客服"], variant="錯誤碼"),
    case("J05", "嘉南／配件", "新永安", "jiannan_common", "一般遙控器壞了，買新的多少錢？", ["300", "遙控器"], variant="口語"),
    case("J06", "嘉南／配件", "大揚", "jiannan_common", "機上盒 HDMI 線和電源線各多少？", ["400", "200"], variant="複合問法"),
    case("J07", "嘉南／收費", "新永安", "jiannan_common", "新永安第四台一個月多少錢？", ["540", "收視費"], variant="精確費用"),
    case("J08", "嘉南／收費", "大揚", "jiannan_common", "大揚有線電視月租多少？", ["555", "收視費"], variant="精確費用"),
    case("J09", "嘉南／頻道", "新永安", "jiannan_common", "頻道少很多台，要怎麼重新搜尋？", ["節目搜尋", "重搜"], variant="口語"),
    case("J10", "嘉南／聲音", "大揚", "jiannan_common", "電視聲音比畫面慢一秒", ["重新拔插", "電源"], variant="症狀描述"),
    case("J11", "嘉南／功能", "新永安", "jiannan_common", "機上盒要怎麼切換雙語？", ["語言", "雙語"], variant="操作流程"),
    case("J12", "嘉南／到府服務", "新永安", "jiannan_test", "遙控器可以送到家裡更換嗎？", ["真人客服", "遙控器"], variant="口語"),
    case("J13", "嘉南／到府服務", "大揚", "jiannan_test", "可以請人到府收我的繳款嗎？", ["真人客服", "到府"], variant="口語"),
    case("J14", "嘉南／泛化驗證", "新永安", "jiannan_common", "E001 卡片讀不到怎麼處理？", ["晶片", "插入"], variant="錯誤碼口語"),
    case("J15", "嘉南／泛化驗證", "大揚", "jiannan_common", "機上盒電源線買一條多少錢？", ["電源線", "200"], variant="單一配件"),
    case("J16", "嘉南／泛化驗證", "新永安", "jiannan_common", "第四台月租費是多少？", ["540", "收視費"], variant="省略公司名"),
    case("J17", "嘉南／泛化驗證", "大揚", "jiannan_test", "遙控器能請客服送來嗎？", ["真人客服", "遙控器"], variant="配送口語"),

    # 區域隔離：不得把另一區通用文件混進來
    negative_case("X01", "區域隔離", "大屯", "jiannan_common", "新永安有線電視一個月多少錢？", variant="中區不可讀嘉南通用"),
    negative_case("X02", "區域隔離", "新永安", "network", "固定 IP 第二個要收多少錢？", variant="嘉南不可讀中區通用"),
    negative_case("X03", "區域隔離", "大揚", "fifa", "世界盃足球賽在哪幾台播？", variant="嘉南不可讀中區賽事文件"),
]


def get_backend_auth_headers() -> dict[str, str]:
    default_env_file = ".env.production" if (ROOT_DIR / ".env.production").exists() else ".env"
    config = dotenv_values(ROOT_DIR / os.getenv("CUST_APP_ENV_FILE", default_env_file))
    header_name = str(config.get("API_AUTH_HEADER") or "X-API-Token").strip()
    name = str(os.getenv("KB_COMMON_API_AUTH_NAME") or config.get("API_AUTH_NAME") or "").strip()
    password = str(os.getenv("KB_COMMON_API_AUTH_PASSWORD") or config.get("API_AUTH_PASSWORD") or "").strip()
    if name and password:
        response = requests.post(
            f"{BACKEND_URL}/api/auth/token",
            json={"name": name, "password": password},
            timeout=20,
        )
        response.raise_for_status()
        payload = response.json()
        token = str(payload.get("access_token") or "").strip()
        response_header = str(payload.get("header_name") or header_name).strip()
        if token:
            return {response_header: token}
    fixed_token = str(config.get("API_AUTH_TOKEN") or "").strip()
    return {header_name: fixed_token} if fixed_token else {}


def result_document_id(result: dict[str, Any]) -> str:
    source = result.get("source") if isinstance(result.get("source"), dict) else {}
    return str(result.get("document_id") or source.get("document_id") or "")


def result_title(result: dict[str, Any]) -> str:
    source = result.get("source") if isinstance(result.get("source"), dict) else {}
    return str(result.get("title") or source.get("title") or "")


def result_content(result: dict[str, Any]) -> str:
    source = result.get("source") if isinstance(result.get("source"), dict) else {}
    return str(
        result.get("answer")
        or result.get("content")
        or result.get("text")
        or source.get("answer")
        or source.get("content")
        or source.get("text")
        or ""
    )


def merged_results(payload: dict[str, Any]) -> list[dict[str, Any]]:
    answerable = payload.get("answerable_sources") or payload.get("answerable_docs") or []
    docs = payload.get("sources") or payload.get("docs") or payload.get("results") or []
    combined: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for item in [*answerable, *docs]:
        if not isinstance(item, dict):
            continue
        key = (result_document_id(item), result_content(item))
        if key in seen:
            continue
        seen.add(key)
        combined.append(item)
    return combined


def normalize_evaluation_text(value: Any) -> str:
    """Normalize equivalent Traditional Chinese spellings for report matching."""
    return str(value or "").casefold().replace("身份證", "身分證").replace("身份證明", "身分證明")


def run_case(item: dict[str, Any], headers: dict[str, str]) -> dict[str, Any]:
    started = time.perf_counter()
    response = requests.post(
        f"{BACKEND_URL}/api/kb/chat-search",
        json={"plan_name": item["question"], "knowledge_base": item["station"], "limit": 10},
        headers=headers,
        timeout=REQUEST_TIMEOUT,
    )
    elapsed = round(time.perf_counter() - started, 3)
    response.raise_for_status()
    payload = response.json()
    combined = merged_results(payload)
    expected_id = item["expected_document_id"]
    expected_results = [result for result in combined if result_document_id(result) == expected_id]
    hit_rank = next(
        (index for index, result in enumerate(combined, 1) if result_document_id(result) == expected_id),
        None,
    )

    if item.get("expected_mode") == "clarification":
        # A distant service-name variant must not be silently rewritten into a
        # specific product. Retrieval should still surface the likely candidate
        # so the conversation layer can ask the customer to confirm the name.
        status = "PASS" if expected_results else "FAIL"
        keyword_hit = bool(expected_results)
        content_hit_rank = hit_rank
        missing_terms = [] if expected_results else ["clarification_candidate"]
    elif item["negative"]:
        status = "PASS" if not expected_results else "FAIL"
        keyword_hit = None
        content_hit_rank = None
        missing_terms: list[str] = []
    else:
        required_terms = [normalize_evaluation_text(keyword) for keyword in item["expected_any"]]
        content_hit_rank = None
        missing_terms = required_terms
        for index, result in enumerate(combined, 1):
            searchable = normalize_evaluation_text(f"{result_title(result)}\n{result_content(result)}")
            current_missing = [term for term in required_terms if term not in searchable]
            if not current_missing:
                content_hit_rank = index
                missing_terms = []
                break
            if len(current_missing) < len(missing_terms):
                missing_terms = current_missing
        keyword_hit = content_hit_rank is not None
        if keyword_hit:
            status = "PASS"
        else:
            aggregate_expected = normalize_evaluation_text("\n".join(
                f"{result_title(result)}\n{result_content(result)}" for result in expected_results
            ))
            aggregate_missing = [term for term in required_terms if term not in aggregate_expected]
            if expected_results and not aggregate_missing:
                status = "PARTIAL"
                missing_terms = []
            else:
                status = "FAIL"

        if item.get("knowledge_gap") and status == "FAIL":
            status = "GAP"

    top_results = [
        {
            "document_id": result_document_id(result),
            "title": result_title(result),
            "score": result.get("score", result.get("_score")),
            "content": result_content(result)[:700],
        }
        for result in combined[:10]
    ]
    return {
        **item,
        "status": status,
        "hit_rank": hit_rank,
        "content_hit_rank": content_hit_rank,
        "missing_terms": missing_terms,
        "keyword_hit": keyword_hit,
        "latency_sec": elapsed,
        "retrieval_pipeline_version": payload.get("retrieval_pipeline_version"),
        "returned_count": len(combined),
        "top_results": top_results,
    }


def write_report(results: list[dict[str, Any]], generated_at: str, stamp: str) -> tuple[Path, Path]:
    json_path = OUTPUT_DIR / f"common_kb_deep_test_{stamp}.json"
    html_path = OUTPUT_DIR / f"common_kb_deep_test_{stamp}.html"
    json_path.write_text(
        json.dumps(
            {"generated_at": generated_at, "backend": BACKEND_URL, "results": results},
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    html_path.write_text(render_html(results, generated_at), encoding="utf-8")
    return json_path, html_path


def render_html(results: list[dict[str, Any]], generated_at: str) -> str:
    counts = Counter(result["status"] for result in results)
    group_counts: dict[str, Counter[str]] = {}
    for result in results:
        group_counts.setdefault(result["group"], Counter())[result["status"]] += 1
    summary_rows = "".join(
        f"<tr><td>{html.escape(group)}</td><td>{counter['PASS']}</td><td>{counter['PARTIAL']}</td><td>{counter['GAP']}</td><td>{counter['FAIL']}</td><td>{counter['ERROR']}</td></tr>"
        for group, counter in group_counts.items()
    )
    cards = []
    for result in results:
        status_label = {"PASS": "完整命中", "PARTIAL": "分散命中", "GAP": "知識缺口", "FAIL": "失敗", "ERROR": "逾時／錯誤"}.get(
            result["status"], result["status"]
        )
        rows = []
        for rank, item in enumerate(result["top_results"], 1):
            matched = item["document_id"] == result["expected_document_id"]
            score = item.get("score")
            score_text = f"{score:.4f}" if isinstance(score, (int, float)) else "-"
            rows.append(
                f"<tr class={'matched' if matched else ''}><td>{rank}</td>"
                f"<td>{html.escape(item['title'] or '未標題')}</td><td>{score_text}</td>"
                f"<td><pre>{html.escape(item['content'])}</pre></td></tr>"
            )
        expectation = (
            "不得出現此區域文件"
            if result["negative"]
            else f"同一檢索片段須完整包含：{'／'.join(result['expected_any'])}"
        )
        verdict = (
            "原始文件未提供回答此問題所需的完整資訊，需補充知識庫。"
            if result["status"] == "GAP"
            else
            f"原始文件排名：{result['hit_rank'] or '未命中'}；內容命中排名："
            f"{result['content_hit_rank'] or '未命中'}；片段關鍵資訊："
            f"{'符合' if result['keyword_hit'] else ('資訊散在同文件多個片段' if result['status'] == 'PARTIAL' else '缺少 ' + '、'.join(result['missing_terms']))}"
            if not result["negative"]
            else f"隔離結果：{'未跨區，正確' if result['status'] == 'PASS' else '發生跨區誤抓'}"
        )
        cards.append(
            f"""
            <article class="case {result['status'].lower()}">
              <header><span class="case-no">{result['id']}</span><h2>{html.escape(result['group'])}</h2><span class="badge">{status_label}</span></header>
              <div class="meta"><span>系統台：{html.escape(result['station'])}</span><span>問法：{html.escape(result['variant'])}</span><span>耗時：{result['latency_sec']:.3f} 秒</span></div>
              <div class="question"><strong>使用者問題</strong>{html.escape(result['question'])}</div>
              <p><strong>驗證條件：</strong>{html.escape(expectation)}</p><p><strong>結果：</strong>{html.escape(verdict)}</p>
              <details {'open' if result['status'] in {'FAIL', 'PARTIAL', 'GAP'} else ''}><summary>實際前 10 筆檢索結果</summary><div class="table-wrap"><table><thead><tr><th>#</th><th>文件</th><th>分數</th><th>片段</th></tr></thead><tbody>{''.join(rows)}</tbody></table></div></details>
            </article>
            """
        )
    return f"""<!doctype html>
<html lang="zh-Hant"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>通用區 RAG 深度驗證</title><style>
:root{{--bg:#0d1117;--panel:#151c26;--panel2:#1b2532;--text:#edf2f7;--muted:#a9b6c7;--line:#39485a;--ok:#45c77b;--bad:#ff6b6b;--accent:#d98b2b}}
*{{box-sizing:border-box}}body{{margin:0;background:var(--bg);color:var(--text);font:16px/1.65 system-ui,"Microsoft JhengHei",sans-serif}}
main{{width:min(1440px,calc(100% - 32px));margin:28px auto 72px}}h1{{font-size:32px;margin:0 0 4px}}.sub{{color:var(--muted);margin:0 0 24px}}
.stats{{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:12px;margin-bottom:20px}}.stat{{background:var(--panel);border:1px solid var(--line);padding:18px}}.stat b{{display:block;font-size:28px}}
.summary{{width:100%;border-collapse:collapse;background:var(--panel);margin-bottom:24px}}th,td{{padding:10px 12px;border:1px solid var(--line);text-align:left;vertical-align:top}}th{{background:var(--panel2)}}
.case{{background:var(--panel);border:1px solid var(--line);border-left:5px solid var(--ok);padding:18px;margin:14px 0}}.case.partial{{border-left-color:var(--accent)}}.case.gap{{border-left-color:#5aa9e6}}.case.fail,.case.error{{border-left-color:var(--bad)}}header{{display:flex;gap:12px;align-items:center}}h2{{font-size:19px;margin:0;flex:1}}.case-no,.badge{{padding:3px 9px;border:1px solid var(--line);background:var(--panel2)}}.badge{{color:var(--ok)}}.partial .badge{{color:var(--accent)}}.gap .badge{{color:#72b9ee}}.fail .badge,.error .badge{{color:var(--bad)}}
.meta{{display:flex;flex-wrap:wrap;gap:10px 20px;color:var(--muted);margin:10px 0}}.question{{background:var(--panel2);padding:12px 14px;margin:12px 0}}.question strong{{display:block;color:var(--accent)}}details{{margin-top:12px}}summary{{cursor:pointer;color:var(--accent)}}.table-wrap{{overflow:auto;margin-top:10px}}table{{width:100%;border-collapse:collapse}}tr.matched{{background:#173528}}pre{{white-space:pre-wrap;margin:0;font:inherit;min-width:420px}}
@media(max-width:720px){{.stats{{grid-template-columns:1fr}}main{{width:min(100% - 20px,1440px)}}}}
</style></head><body><main><h1>通用區 RAG 深度驗證</h1><p class="sub">產生時間：{html.escape(generated_at)}｜API：{html.escape(BACKEND_URL)}｜驗證文件命中、答案片段與區域隔離</p>
<section class="stats"><div class="stat">測試數<b>{len(results)}</b></div><div class="stat">完整命中<b>{counts['PASS']}</b></div><div class="stat">分散命中<b>{counts['PARTIAL']}</b></div><div class="stat">知識缺口<b>{counts['GAP']}</b></div><div class="stat">失敗／錯誤<b>{counts['FAIL'] + counts['ERROR']}</b></div></section>
<table class="summary"><thead><tr><th>測試群組</th><th>完整命中</th><th>分散命中</th><th>知識缺口</th><th>失敗</th><th>逾時／錯誤</th></tr></thead><tbody>{summary_rows}</tbody></table>{''.join(cards)}</main></body></html>"""


def main() -> int:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    headers = get_backend_auth_headers()
    generated_at = datetime.now().astimezone().isoformat(timespec="seconds")
    selected_cases = [item for item in CASES if not CASE_FILTER or item["id"] in CASE_FILTER]
    if not selected_cases:
        raise SystemExit(f"No cases matched KB_COMMON_TEST_CASE_IDS={','.join(sorted(CASE_FILTER))}")
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    results: list[dict[str, Any]] = []
    for index, item in enumerate(selected_cases, 1):
        try:
            result = run_case(item, headers)
        except Exception as exc:
            result = {**item, "status": "ERROR", "hit_rank": None, "content_hit_rank": None, "missing_terms": item.get("expected_any", []), "keyword_hit": False, "latency_sec": REQUEST_TIMEOUT, "returned_count": 0, "top_results": [], "error": str(exc)}
        results.append(result)
        write_report(results, generated_at, stamp)
        print(f"[{index:02d}/{len(selected_cases)}] {result['status']} {item['id']} {item['station']} {item['question']}", flush=True)

    json_path, html_path = write_report(results, generated_at, stamp)
    counts = Counter(result["status"] for result in results)
    print(json.dumps({"total": len(results), "pass": counts["PASS"], "partial": counts["PARTIAL"], "gap": counts["GAP"], "fail": counts["FAIL"], "error": counts["ERROR"], "json": str(json_path), "html": str(html_path)}, ensure_ascii=False), flush=True)
    return 0 if counts["FAIL"] == 0 and counts["ERROR"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
