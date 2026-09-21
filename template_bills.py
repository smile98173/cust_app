def send_bills_and_format_msg(json_data, token):
    results = []
    bills = json_data.get("bills", [])
    total_count = len(bills)

    for idx, bill in enumerate(bills, start=1):
        jsons = {
            "token": token,
            "barCode1": bill.get("first_num", ""),
            "barCode2": bill.get("second_num", ""),
            "barCode3": bill.get("third_num", "")
        }

        try:
            # 這裡維持你的請求邏輯
            response = requests.get(
                "https://custservice.topmso.com.tw:8085/csr_sms_mobile_client_web-war/eBillAction.do?method=receiveByBarCode",
                verify=False, json=jsons, timeout=30)

            if response.status_code == 200:
                msg = response.json().get("msg", "資料有誤，請重新查詢，謝謝")
            else:
                msg = "連線失敗，請重新查詢，謝謝"
                print(f"HTTP 錯誤 {response.status_code}")
        except Exception as e:
            msg = "連線失敗，請重新查詢，謝謝"
            print(f"請求失敗：{e}")
        # ⭐ 關鍵邏輯：判斷總數來決定顯示方式
        if total_count == 1:
            prefix = "這筆帳單"
        else:
            prefix = f"第{idx}筆帳單"

        results.append(f"{prefix}：{msg}")

    return "\n".join(results)

if func_name == "payment_bill_batch":
    print("call payment_bill_batch")
    print(json_data)

    for bill in json_data["bills"]:
        if re.search(r"[A-Za-z]", bill["second_num"]):
            return "您好，系統判讀為便利商店事務機繳費。\n若先前因欠費停用，系統將自動恢復訊號。\n請將數據機或機上盒重新開機，再確認網路或電視是否正常。"

    token = get_token()
    if token:
        respText = send_bills_and_format_msg(json_data, token)

    return respText