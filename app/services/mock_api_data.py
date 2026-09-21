from typing import Any, Dict, Optional


MOCK_API_BASE_URL = "https://mock-api.local/cust"

MOCK_CUSTOMER = {
    "custCName": "王大明",
    "custTel": "0988555666",
    "custNo": "1082281",
}

MOCK_CONTRACT_PRODUCTS = {
    "code": "0000",
    "msg": "成功",
    "data": [
        {
            "conDate": "無合約",
            "pkgPrdName": "基本頻道",
            "useStatusName": "使用中",
            "prdTypeName": "CATV",
        },
        {
            "conDate": "無合約",
            "pkgPrdName": "寬頻服務",
            "useStatusName": "停用",
            "prdTypeName": "CM",
        },
        {
            "conDate": "2016-03-31",
            "pkgPrdName": "數位電視頻道",
            "useStatusName": "使用中",
            "prdTypeName": "DTV",
        },
        {
            "speed": "1000000K/600000K",
            "conDate": "2026-12-31",
            "pkgPrdName": "FTTH-EPON 流量測試方案",
            "useStatusName": "使用中",
            "prdTypeName": "EPON",
        },
        {
            "speed": "",
            "conDate": "無合約",
            "pkgPrdName": "LineTV",
            "useStatusName": "使用中",
            "prdTypeName": "OTT",
        },
    ],
}

MOCK_BILLS = [
    {
        "custCName": MOCK_CUSTOMER["custCName"],
        "custTel": MOCK_CUSTOMER["custTel"],
        "custNo": MOCK_CUSTOMER["custNo"],
        "data": [
            {
                "billType": "寬頻月租",
                "shoAmt": "799",
                "xEdate": "2026-05-31",
            },
            {
                "billType": "有線電視",
                "shoAmt": "600",
                "xEdate": "2026-06-05",
            },
        ],
    },
]

MOCK_PROMOTIONS = [
    {
        "name": "測試寬頻優惠",
        "area": "台中",
        "service": "寬頻上網",
        "monthlyAverage": "699",
        "contractMonths": "24",
        "gift": "指定期間加贈 Wi-Fi 分享器租用優惠",
        "officialUrl": "https://mock-api.local/official/promotions/new-year-net",
    },
    {
        "name": "有線電視加網路組合",
        "area": "台中",
        "service": "有線電視 + 寬頻",
        "monthlyAverage": "999",
        "contractMonths": "24",
        "gift": "依系統台公告為準",
        "officialUrl": "https://mock-api.local/official/promotions/tv-net-bundle",
    },
]

MOCK_CHANNELS = {
    "HBO": {
        "code": "0000",
        "msg": "成功",
        "data": [
            {
                "channelName": "HBO",
                "channelId": "65",
            },
            {
                "channelName": "HBO HD",
                "channelId": "220",
            },
            {
                "channelName": "HBO Signature",
                "channelId": "221",
            },
            {
                "channelName": "HBO Family",
                "channelId": "222",
            },
            {
                "channelName": "HBO Hits",
                "channelId": "223",
            },
        ],
    },
    "愛爾達體育": {
        "channelNo": "168",
        "area": "大屯",
        "note": "頻道位置為模擬資料，正式結果需依系統台頻道表為準。",
    },
    "東森電影台": {
        "channelNo": "62",
        "area": "大屯",
        "note": "頻道位置為模擬資料。",
    },
    "霹靂": {
        "channelNo": "99",
        "area": "共用",
        "note": "頻道位置為模擬資料。",
    },
}

MOCK_ADDON_PLANS = {
    "LINE TV": {
        "name": "LINE TV 加值服務",
        "available": True,
        "purchaseUrl": "https://mock-api.local/official/addons/line-tv",
        "note": "需確認系統台、機上盒型號與現有方案。",
    },
    "哈TV": {
        "name": "哈TV 數位套餐",
        "available": True,
        "purchaseUrl": "https://mock-api.local/official/addons/hatv",
        "note": "方案內容依系統台與當期公告為準。",
    },
}

MOCK_SERVICE_AREAS = {
    "大屯": ["烏日", "霧峰", "太平", "大里"],
    "台中": ["烏日", "霧峰", "太平", "大里"],
}


def mock_api_response(endpoint: str, payload: Dict[str, Any], data: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "mock": True,
        "endpoint": f"{MOCK_API_BASE_URL}/{endpoint}",
        "request": payload,
        "response": data,
    }


def is_mock_customer_identity(
    name: Optional[str] = None,
    phone: Optional[str] = None,
    custnum: Optional[str] = None,
) -> bool:
    name_text = str(name or "").strip()
    phone_text = str(phone or "").strip()
    custnum_text = str(custnum or "").strip()

    provided_values = {
        "custCName": name_text,
        "custTel": phone_text,
        "custNo": custnum_text,
    }
    return bool(any(provided_values.values())) and all(
        not value or value == MOCK_CUSTOMER[field]
        for field, value in provided_values.items()
    )


def find_mock_promotion(query: Optional[str], area: Optional[str]) -> Dict[str, Any]:
    query_text = query or ""
    area_text = area or ""

    for item in MOCK_PROMOTIONS:
        if item["name"] in query_text:
            return item

    for item in MOCK_PROMOTIONS:
        if area_text and area_text in item["area"]:
            return item

    return MOCK_PROMOTIONS[0]


def find_mock_bill(name: Optional[str], phone: Optional[str], custnum: Optional[str] = None) -> Dict[str, Any]:
    name_text = str(name or "").strip()
    phone_text = str(phone or "").strip()
    custnum_text = str(custnum or "").strip()

    for item in MOCK_BILLS:
        provided_values = {
            "custCName": name_text,
            "custTel": phone_text,
            "custNo": custnum_text,
        }
        if any(provided_values.values()) and all(
            not value or item.get(field) == value
            for field, value in provided_values.items()
        ):
            return dict(item)

    return {
        "msg": "查無客戶資料",
        "custCName": name_text,
        "custTel": phone_text,
        "custNo": custnum_text,
    }


def find_mock_channel(channel_name: str) -> Dict[str, Any]:
    for key, item in MOCK_CHANNELS.items():
        if key in channel_name or channel_name in key:
            if "data" in item:
                return dict(item)
            return dict(item, name=key)

    return {
        "name": channel_name,
        "channelNo": "",
        "area": "",
        "note": "模擬資料查無此頻道，正式 API 可改由頻道名稱查詢。",
    }


def check_mock_service_availability(service_address: str) -> Dict[str, Any]:
    address = service_address or ""
    if any(term in address for term in ["彰化", "和美"]):
        return {
            "available": False,
            "matchedArea": "彰化縣和美鎮",
            "message": "模擬資料顯示目前選擇系統台未服務此區。",
        }

    if any(term in address for terms in MOCK_SERVICE_AREAS.values() for term in terms):
        return {
            "available": True,
            "matchedArea": address,
            "message": "模擬資料顯示此地址所在區域可進一步申辦。",
        }

    return {
        "available": None,
        "matchedArea": address,
        "message": "模擬資料無法判斷，正式 API 需用完整地址查詢。",
    }
