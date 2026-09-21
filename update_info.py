import functions_framework
from flask import jsonify
from openai import OpenAI
import json
import requests
import pandas as pd # access CSV file
# access google storage
import fsspec
import gcsfs
# best match required
from bs4 import BeautifulSoup
import difflib
import os
import re
import firebase_admin
from firebase_admin import credentials, db


# token = os.getenv('LINE_BOT_TOKEN')
# secret = os.getenv('LINE_BOT_SECRET')
firebase_url = os.getenv('FIREBASE_URL')
client = OpenAI(api_key=os.getenv('OPENAI_API_KEY'))
cred = credentials.Certificate('test_firebase.json')

firebase_admin.initialize_app(cred, {
    'databaseURL': firebase_url
})


def get_token():
    print("呼叫token網址")
    response = requests.get('https://test.tw/getToken', verify=False, timeout=30)
    # 檢查回應狀態碼
    if response.status_code == 200:
        print("請求成功token！")
        print(response.json())  # 如果回應為 JSON 格式，可以直接解析
        data = response.json()
        return data["token"]
    else:
        print(f"發生錯誤，狀態碼：{response.status_code}")
        return ""


def call_json_text(custNo, json_data, token):
    if custNo:
        json_text = {
                    "token": token,
                    "custTel": "",
                    "custCName": "",
                    "custNo": json_data["custnum"]
                }
    else:
        json_text = {
                    "token": token,
                    "custTel": json_data["phone"],
                    "custCName": json_data["name"]
                }
    return json_text


def call_json_text2(json_data, token):
    json_text = {
                    "token": token,
                    "custTel": json_data["phone"],
                    "custCName": json_data["name"]
                }
    return json_text


def call_search_bill(json_text):
    response = requests.get('https://test.tw/getCustBill', verify=False, json=json_text, timeout=30)
    # 檢查回應狀態碼
    if response.status_code == 200:
        print("請求成功未繳帳單！")
        print(response.json())  # 如果回應為 JSON 格式，可以直接解析
        data = response.json()
        if 'billType' in data:
            if str(data['shoAmt']) == "0":
                return "我已幫您確認，目前帳務狀況正常，沒有需要處理或繳費的項目"
            return f"{data['billType']}：{str(data['shoAmt'])}元"
        elif 'msg' in data:
            if str(data['msg']) == "查無客戶未繳帳單":
                return f"尚無須繳納的費用，如您已繳費，請記得將設備電源關機重開。"
            elif str(data['msg']) == "查無客戶資料":
                return "查詢不到您的資料，可能因您提供的姓名與電話資訊不一致，請確認後重新輸入，我再為您查詢。"
    else:
        print(f"發生查詢帳單錯誤，狀態碼：{response.status_code}")
        return "傳送失敗，系統繁忙中!~\n請稍後再試，謝謝"


def bill_return_line_internet(json_text):
    response = requests.get('https://test.tw/changeReceive', verify=False, json=json_text, timeout=30)
    # 檢查回應狀態碼
    if response.status_code == 200:
        print("請求網路欠斷復線成功！")
        print(response.json())  # 如果回應為 JSON 格式，可以直接解析
        data = response.json()
        if 'msg' in data:
            if '查無客戶' in data['msg']:
                return data['msg'] + "\n如您已繳費，請記得將設備電源關機重開。\n貼心提醒，透過 IBON及FAMIPORT繳費方式系統會自動開通喔"
            else:
                return data['msg']
    else:
        print(f"發生網路復線錯誤，狀態碼：{response.status_code}")
        return "傳送失敗，系統繁忙中!~\n請稍後再試，謝謝"


def bill_return_line_tv(json_text):
    response = requests.get('https://test.tw/dtvChangeReceive', verify=False, json=json_text, timeout=30)
    # 檢查回應狀態碼
    if response.status_code == 200:
        print("請求電視欠斷復線成功！")
        print(response.json())  # 如果回應為 JSON 格式，可以直接解析
        data = response.json()
        if 'msg' in data:
            if '查無客戶' in data['msg']:
                return data['msg'] + "\n如您已繳費，請記得將設備電源關機重開。\n貼心提醒，透過 IBON及FAMIPORT繳費方式系統會自動開通喔"
            else:
                return data['msg']
    else:
        print(f"發生電視復線錯誤，狀態碼：{response.status_code}")
        return "傳送失敗，系統繁忙中!~\n請稍後再試，謝謝"


def send_message(json_text):
    response = requests.get('https://test.tw/reBillE', verify=False, json=json_text, timeout=30)
    # 檢查回應狀態碼
    if response.status_code == 200:
        print("請求成功發送簡訊帳單！")
        print(response.json())  # 如果回應為 JSON 格式，可以直接解析
        data = response.json()
        if 'msg' in data:
            if '查無客戶' in data['msg']:
                return "查詢不到您的資料，可能因您提供的姓名與電話資訊不一致，請確認後重新輸入，我再為您查詢。"
            else:
                return data['msg']
    else:
        print(f"發生簡訊帳單錯誤，狀態碼：{response.status_code}")
        return "傳送失敗，系統繁忙中!~\n請稍後再試，謝謝"
    # return "申請簡訊帳單：\n親愛的用戶您好，目前暫時無法補發簡訊帳單。\n如您有帳單需要繳納，請利用其他管道繳費，造成您的不便敬請見諒。\n您可以透過以下方式進行繳費：\n\n1.APP繳費：\n- 下載行動客服APP，註冊後，按照指示完成繳費。\n\n2. IBON及FAMIPORT繳費：\n- 至7-11或全家便利生活機台，按照指示完成繳費。\n"


def load_faq_data(csv_file,encode):
    """使用pandas從使用Big-5編碼的CSV文件中加載問答對應並返回一個字典"""
    # 讀取CSV文件，指定Big-5編碼，假設第一列是問題，第二列是答案
    df = pd.read_csv(csv_file, header=None, encoding=encode)
    # 轉換 DataFrame 為字典，第零列作為鍵（問題），第一列作為值(答案)
    faq_dict = pd.Series(df[1].values, index=df[0]).to_dict()
    return faq_dict


def find_best_matches(question, faq_dict, max_matches=20):
    """找出最匹配的問題及其答案"""
    questions = list(faq_dict.keys())
    # 使用 difflib 找到最接近的问题
    best_matches = difflib.get_close_matches(question, questions, n=max_matches, cutoff=0.3)
    if best_matches:
        matches_with_answers = [(match, faq_dict[match]) for match in best_matches]
        return matches_with_answers
    else:
        return [("No match found", "No answer available")]


def format_matches_for_rag(matches):
    """將匹配的答案串成文字問答集的形式"""
    qa_pairs = []
    for match in matches:
        qa_pairs.append(f"Q: {match[0]}\nA: {match[1]}")
    return "\n\n".join(qa_pairs)


def search_news(company_name):
    ref = db.reference(f'Company/{company_name}')
    entity = ref.get()['content']
    print(entity)
    return entity if entity else "查無最新資訊"


# ========= 驗證 =========
def validate_name(name):
    if not name:
        return False

    name = name.strip()

    if len(name) < 2 or len(name) > 50:
        return False

    if not re.match(r'^[\u4e00-\u9fffA-Za-z .·]+$', name):
        return False

    return True


def validate_tel(tel):
    if not tel:
        return False

    return bool(re.match(r"^09\d{8}$|^0[2-8]\d{7,8}$|^[2-9]\d{6,7}$", tel))


def valid_name_tel(json_text):
    name = json_text.get('name')
    tel = json_text.get('phone')

    return validate_name(name) and validate_tel(tel)


# ========= 共用處理 =========
def handle_with_token(action_name, json_data, custNo=None):
    print(f"call {action_name}")

    token = get_token()
    if not token:
        return "系統忙碌中，請稍後再試"

    if action_name == "search_bill" and custNo is not None:
        json_text = call_json_text(custNo, json_data, token)
    else:
        json_text = call_json_text2(json_data, token)

    print(json_text)
    return json_text


def get_completion(query, prompt_template, chat_history, custNo, model_used="gpt-4o"):
    msg = []
    for row in chat_history:
        msg.append({'role': "user", 'content': row[0]})
        msg.append({'role': "assistant", 'content': row[1]})
    msg.append({"role": "system", "content": prompt_template})
    msg.append({"role": "user", "content": query})
    # print(f'GPT msg: {msg}')
    # msg = chat_history
    '''
    msg = [
        {"role": "system", "content": prompt_template},
        {"role": "user", "content": query}]
    '''
    functions = cust_functions if custNo else normal_functions
    response = client.chat.completions.create(
        model=model_used,
        messages=msg,
        temperature=0.5,
        functions=functions,
        function_call="auto"
    )
    # 獲取回答
    answer = response.choices[0].message.content
    dict_data = []
    if answer:
        if custNo and "提供" in answer and "客戶編號" in answer:
            response = client.chat.completions.create(
                model=model_used,
                messages=[{"role": "system", "content": prompt_template}, {"role": "user", "content": query + "\n客戶編號：" + custNo}],
                temperature=0.5,
                functions=functions,
                function_call="auto"
            )
            vf = response.choices[0].message.content
            if not vf:
                dict_data = json.loads(response.choices[0].message.function_call.arguments)
                answer = response.choices[0].message.function_call.name
    else:
        # print(response.choices[0].message.function_call.arguments)
        dict_data = json.loads(response.choices[0].message.function_call.arguments)
        answer = response.choices[0].message.function_call.name
    # print(response.choices[0].message)
    print(answer)
    print(dict_data)
    # 清理舊的對話歷史
    # clean_old_histories()
    return answer, dict_data


def CF_api(request):
    """Responds to any HTTP request.
    Args:
        request (flask.Request): HTTP request object.
    Returns:
        The response text or any set of values that can be turned into a
        Response object using
        `make_response <http://flask.pocoo.org/docs/1.0/api/#flask.Flask.make_response>`.
    """
    data = request.get_json()
    # print(data)
    chat_history = data.get('history')
    query = data.get('question')
    tv_cable = data.get('tv_cable')
    custNo = data.get('custNo')
    print(f"客戶編號:{custNo}")
    if tv_cable:
        for company in company_profiles:
            if company["class"] == tv_dict[tv_cable]:
                break
        service_company = f"服務於{company['公司別']}, 公司地址: {company['地址電話']},\n公司網址: {company['網址']},\n加值服務網址: {company['加值服務網址']},\n營業時間: {company['時間']}\n服務項目: {company['服務項目']}, 服務地區: {company['服務地區']}\napp: {company['app名稱']}, 統一編號: {company['統一編號']}"
    else:
        service_company = "服務公司別涵蓋佳光電訊(原西海岸有線)、大屯有線、中投有線、佳聯有線、北港有線、新永安有線、大揚有線等經營區.客服中心電話(04)4495678"
    if query:
        matches = find_best_matches(query, faq_data)
        documents = format_matches_for_rag(matches)
        the_news = search_news(tv_cable)
        prompt_template = (
            "你是專業的有線電視與寬頻客服助理，名為哈寶寶。\n"
            f"你所屬公司為：{service_company}\n"
            "服務產品包含數位電視、寬頻上網、LINE TV（合作加值服務）、哈TV，以及無線分享器(Mesh WiFi)、監視器(IP Camera)等加值服務。\n\n"

            "你的任務是：根據【檢索問答集資料】、【最新資訊】、【回答優先順序】、【回答原則】、【真人客服規則】、"
            "【網址規則】、【電話規則】、【禁止事項】、【工具觸發規則】、【回答風格】，提供正確、保守且一致的客服回覆。\n\n"

            "[檢索問答集資料]\n"
            f"{documents}\n\n"

            "[最新資訊]\n"
            f"{the_news}\n\n"

            "[回答優先順序]\n"
            "1. 優先理解使用者最新訊息的需求，並參考前文已提供的必要資訊。\n"
            "2. 若使用者需求符合工具可處理的情境，且已提供足夠必要資料，優先使用對應工具查詢或處理。\n"
            "3. 若工具已回傳結果，回答應以工具結果為準，不自行改寫成不同結論。\n"
            "4. 前文中的測試案例、示例內容或舊回覆，不可當成本次查詢結果。\n"
            "5. 若缺少工具必要資料，只詢問缺少的欄位；若資料已足夠，不要重複追問。\n\n"

            "[回答原則]\n"
            "1. 僅能提供本公司服務範圍內的說明、基本排查步驟、既有問答集內容與工具查詢結果。\n"
            "2. 僅能根據下列來源生成結論：\n"
            "   (a) 使用者提供的資訊\n"
            "   (b) 檢索問答集資料\n"
            "   (c) 最新資訊\n"
            "   (d) 工具回傳結果\n"
            "3. 若缺乏足夠依據，不可使用下列類型的句子：\n"
            "   - 查無此用戶\n"
            "   - 查詢成功\n"
            "   - 已申辦\n"
            "   - 可安裝\n"
            "   - 無法申請\n"
            "   - 有欠費\n"
            "   - 已繳費\n"
            "   - 已建立案件\n"
            "   - 已協助處理\n"
            "4. 不得承諾結果、不得保證修復、不得答應客戶任何需求、不得虛構後續處理進度。\n"
            "5. 若問題符合工具觸發情境，且使用者已提供可用資料，優先使用工具；只有明確缺少必要欄位時，才請使用者補充該欄位。\n"
            "6. 回答一律使用繁體中文。\n"
            "7. 將 modem 一律稱為「數據機」。\n"
            "8. 不得推薦或提及本公司以外的有線電視、網路供應商、品牌、銀行、電信或超商名稱。\n\n"

            "[真人客服規則]\n"
            "1. 預設情況下，不得主動提及真人客服、轉接真人客服、或引導使用者輸入「真人客服」。\n"
            "2. 僅當問題屬於下列限制情境時，才可引導使用者輸入關鍵字「真人客服」：\n"
            "   (a) 電視或網路方案費用與報價\n"
            "   (b) 派工維修、安排時間、約定施工時段\n"
            "   (c) 涉及個人資料查詢或修改\n"
            "   (d) 程式語言或系統開發問題\n"
            "   (e) 帳號密碼設定或重設需求\n"
            "   (f) 紙本帳單補發或帳單資料修改\n"
            "   (g) 取消服務\n"
            "3. 除上述限制情境外，不得提及真人客服。\n\n"

            "[網址規則]\n"
            "1. 預設情況下，不得主動提供網站、網址、聯絡資訊或外部連結。\n"
            "2. 僅當問題明確屬於『方案費用查詢』且公司政策允許時，才可提供官方網站。\n"
            "3. 除官方網站外，不得提供其他網址或表單連結。\n"
            "4. 若需提供網址，請獨立一行，並使用格式：[網站名稱](網址)\n\n"

            "[電話規則]\n"
            "1. 電話號碼包含手機、有區碼市話、無區碼市話。\n"
            "2. 台灣無區碼市話可能是 7 碼或 8 碼，例如 1234567、22702769；不可因缺少區碼就要求使用者提供完整電話。\n"
            "3. 若使用者訊息中出現姓名加 7 或 8 碼數字，例如『王小明 1234567』或『王小明 22702769』，應視為已提供姓名與電話。\n"
            "4. 若使用者只輸入連續 7 或 8 碼數字，且前文正在要求電話，也應視為已提供電話。\n"
            "5. 只有在電話少於 7 碼、超過合理長度、或明顯不是電話時，才可要求重新提供。\n"
            "6. 不要把帳單編號、條碼、客戶編號誤判為電話；但若使用者是在回覆電話要求，7 或 8 碼數字優先視為電話。\n\n"

            "[禁止事項]\n"
            "1. 不得回答公司地址以外的其他地址。\n"
            "2. 不得提供帳號密碼設定教學，只能依規則引導真人客服。\n"
            "3. 不得提供本公司服務範圍外的資訊。\n"
            "4. 不得使用簡體中文。\n"
            "5. 不得將前文測試答案、示範內容或歷史對話，當成目前真實查詢結果。\n\n"

            "[工具觸發規則]\n"
            "1. 使用者詢問帳單金額、欠費金額、帳單查詢、是否有未繳款，且已提供工具所需資料時，優先觸發 search_bill。\n"
            "2. 使用者只詢問『有沒有斷訊』、『是否停訊』、『網路是否被停用』、『電視是否被停用』，不得觸發 search_bill，除非使用者同時明確詢問欠費或帳單金額。\n"
            "3. 使用者提供姓名、電話，並詢問是否斷訊或服務狀態時，不得觸發 search_bill，也不得自行回答是否斷訊；應回覆目前無法直接確認服務狀態，請使用者提供更明確問題或改走服務狀態查詢流程。\n"
            "4. 使用者表示因未繳費導致電視訊號被切斷，且已完成繳費、希望盡快恢復，才觸發 bill_return_line_tv。\n"
            "5. 使用者表示因未繳費導致網路訊號被切斷，且已完成繳費、希望盡快恢復，才觸發 bill_return_line_internet。\n"
            "6. 使用者表示未收到帳單、帳單遺失、需要補發帳單，才觸發 send_message。\n\n"

            "[回答風格]\n"
            "1. 回答精簡、自然、清楚。\n"
            "2. 優先回答目前能確定的內容。\n"
            "3. 若需使用者補資料，明確指出要補什麼，不要模糊回答。\n"
        )
        print(f"Msg: {query}")
        print(f"RAG: {prompt_template.split('[回答優先順序]')[0]}")
        for chat in chat_history:
            print(chat)
        respText, json_data = get_completion(query, prompt_template, chat_history, custNo)
        # print("原始文字：", respText)
        if respText == "search_bill":
            if json_data.get("custNo") or valid_name_tel(json_data):
                json_text = handle_with_token("search_bill", json_data, custNo)

                if isinstance(json_text, str):  # token錯誤直接回傳
                    respText = json_text
                else:
                    respText = call_search_bill(json_text)
            else:
                respText = "姓名或電話格式有誤!\n請再提供姓名或電話以便為您查詢帳單"


        elif respText == "bill_return_line_internet":
            if valid_name_tel(json_data):
                json_text = handle_with_token("bill_return_line_internet", json_data)

                if isinstance(json_text, str):
                    respText = json_text
                else:
                    respText = bill_return_line_internet(json_text)
            else:
                respText = "姓名或電話格式有誤!\n請再提供姓名或電話以便為您網路復線"


        elif respText == "bill_return_line_tv":
            if valid_name_tel(json_data):
                json_text = handle_with_token("bill_return_line_tv", json_data)

                if isinstance(json_text, str):
                    respText = json_text
                else:
                    respText = bill_return_line_tv(json_text)
            else:
                respText = "姓名或電話格式有誤!\n請再提供姓名或電話以便為您電視復線"


        elif respText == "send_message":
            if valid_name_tel(json_data):
                json_text = handle_with_token("send_message", json_data)

                if isinstance(json_text, str):
                    respText = json_text
                else:
                    respText = send_message(json_text)
            else:
                respText = "姓名或電話格式有誤!\n請再提供姓名或電話以便為您發送簡訊帳單"
    else:
        respText = "Error"
        json_data = ""
    respText = clear_ai_text(respText)
    respText = replace_markdown_links_with_html(respText)
    print('AI Answer：', respText)
    response = {
        "message": f"{respText}"
    }
    # if json_data:
        # response.update(json_data)
    return jsonify(response)

def replace_markdown_links_with_html(text):
    # 轉換 Markdown 樣式的連結為 HTML 連結
    # pattern = re.compile(r'\[([^\]]+)\]\((https?://[^\s)]+)\)')
    # return pattern.sub(r"<a href='\2' target='_blank'>\1</a>", text)
    # 支援全形或半形中括號
    pattern = re.compile(r'[［\[]([^\]］]+)[\]］]\((https?://[^\s)]+)\)')
    return pattern.sub(r"<a href='\2' target='_blank'>\1</a>", text)


def clear_ai_text(text):
    clear_text = re.sub(r"[*#]", "", text)
    return clear_text


tv_dict = {"toplight": "佳光市區", "cltv": "佳聯", "cnt": "中投", "pktv": "北港", "tdtv": "大屯", "wctv": "西海岸", "hya": "新永安", "tycable": "大揚", "tinp": "台基科"}
company_profiles = [
    {
        "class": "西海岸",
        "識別": ["西海岸", "大肚區", "龍井區", "梧棲區", "清水區", "大安區", "大甲區", "沙鹿區"],
        "公司別": "佳光電訊-西海岸區",
        "地址電話": "台中市梧棲區中華路一段1080號，市內電話：(04)449-5678",
        "官網": "https://wctv.com.tw/",
        "網址": "［官網🔗］https://wctv.com.tw/\n［維修申告🔗］http://stb.topmso.com.tw:8080/csr_mobile_client_web/Move_serviceAction.do?method=go_cust_con_fix_main&amp;cust_no_con=0&amp;accountNo=&amp;password=\n［裝機申告🔗］http://stb.topmso.com.tw:8080/csr_mobile_client_web/Move_serviceAction.do?method=go_cust_con_install_main&amp;cust_no_con=0&amp;accountNo=&amp;password=",
        "加值服務網址": "［LINE TV客服中心🔗］https://help.linetv.tw/hc/zh-tw",
        "時間": "星期一～星期六　早上08：30－下午6：00 (假日及國定假日中午12:00~13:30休息)",
        "服務項目": "有線電視及寬頻網路服務",
        "服務地區": "大肚區、龍井區、梧棲區、清水區、大安區、大甲區、沙鹿區",
        "app名稱": "哈TV行動客服(Google Play Store或Apple App Store)",
        "統一編號": "97173528"
    },
    {
        "class": "佳光市區",
        "識別": ["市區", "東區", "西區", "南區", "北區", "中區", "北屯區", "南屯區", "西屯區"],
        "公司別": "佳光電訊-台中市區",
        "地址電話": "台中市西屯區台灣大道四段297號，市內電話：(04)405-56688",
        "官網": "https://www.toplight.tw/",
        "網址": "［官網🔗］https://www.toplight.tw/\n［維修申告🔗］http://stb.topmso.com.tw:8080/csr_mobile_client_web/Move_serviceAction.do?method=go_cust_con_fix_main&amp;cust_no_con=0&amp;accountNo=&amp;password=\n［裝機申告🔗］http://stb.topmso.com.tw:8080/csr_mobile_client_web/Move_serviceAction.do?method=go_cust_con_install_main&amp;cust_no_con=0&amp;accountNo=&amp;password=",
        "加值服務網址": "［LINE TV客服中心🔗］https://help.linetv.tw/hc/zh-tw",
        "時間": "星期一~星期五　早上8:30-12:00、下午1:30-6:00 (中午休息)",
        "服務項目": "寬頻網路服務",
        "服務地區": "東區、西區、南區、北區、中區、北屯區、南屯區、西屯區",
        "app名稱": "哈TV行動客服(Google Play Store或Apple App Store)",
        "統一編號": "97173528"
    },
    {
        "class": "大屯",
        "識別": ["大屯", "烏日區", "霧峰區", "太平區", "大里區"],
        "公司別": "大屯有線",
        "地址電話": "台中市大里區國光路一段68號，市內電話：(04)449-5678",
        "官網": "https://www.tdtv.com.tw/",
        "網址": "［官網🔗］https://www.tdtv.com.tw/\n［維修申告🔗］http://stb.topmso.com.tw:8080/csr_mobile_client_web/Move_serviceAction.do?method=go_cust_con_fix_main&amp;cust_no_con=0&amp;accountNo=&amp;password=\n［裝機申告🔗］http://stb.topmso.com.tw:8080/csr_mobile_client_web/Move_serviceAction.do?method=go_cust_con_install_main&amp;cust_no_con=0&amp;accountNo=&amp;password=",
        "加值服務網址": "［LINE TV客服中心🔗］https://help.linetv.tw/hc/zh-tw",
        "時間": "星期一～星期五　早上8:00~下午7:00 假日: 早上8:30~下午5:00，平日無休．假日及國定假日中午12:00~13:00 休息。",
        "服務項目": "有線電視及寬頻網路服務",
        "服務地區": "烏日區、霧峰區、太平區、大里區",
        "app名稱": "哈TV行動客服(Google Play Store或Apple App Store)",
        "統一編號": "97174358"
    },
    {
        "class": "中投",
        "識別": ["中投", "南投市", "鹿谷鄉", "竹山鎮", "集集鎮", "名間鄉", "水里鄉", "仁愛鄉", "信義鄉", "埔里鎮", "魚池鄉", "國姓鄉", "草屯鎮", "中寮鄉"],
        "公司別": "中投有線",
        "地址電話": "南投縣南投市仁和路7-1號，市內電話：(04)4498809",
        "官網": "https://www.cnt.com.tw/",
        "網址": "［官網🔗］https://www.cnt.com.tw/\n［維修申告🔗］http://stb.topmso.com.tw:8080/csr_mobile_client_web/Move_serviceAction.do?method=go_cust_con_fix_main&amp;cust_no_con=0&amp;accountNo=&amp;password=\n［裝機申告🔗］http://stb.topmso.com.tw:8080/csr_mobile_client_web/Move_serviceAction.do?method=go_cust_con_install_main&amp;cust_no_con=0&amp;accountNo=&amp;password=",
        "加值服務網址": "［LINE TV客服中心🔗］https://help.linetv.tw/hc/zh-tw",
        "時間": "南投區 星期一～星期五 08:30~18:00 星期六 08:30~17:00、水里區 星期一～星期五 08:30~17:30、埔里區 星期一～星期五 08:30~17:30、竹山區 星期一～星期五 08:30~18:00 中午無休息",
        "服務項目": "有線電視及寬頻網路服務",
        "服務地區": "南投市、鹿谷鄉、竹山鎮、集集鎮、名間鄉、水里鄉、仁愛鄉、信義鄉、埔里鎮、魚池鄉、國姓鄉、草屯鎮、中寮鄉",
        "app名稱": "哈TV行動客服(Google Play Store或Apple App Store)",
        "統一編號": "16085715"
    },
    {
        "class": "佳聯",
        "識別": ["佳聯", "斗六市", "古坑鄉", "林內鄉", "土庫鎮", "大埤鄉", "虎尾鎮", "莿桐鄉", "西螺鎮", "二崙鄉", "斗南鎮"],
        "公司別": "佳聯有線",
        "地址電話": "雲林縣虎尾鎮光復路66號，市內電話：(04)449-8808",
        "官網": "https://www.cltv.com.tw/",
        "網址": "［官網🔗］https://www.cltv.com.tw/\n［維修申告🔗］http://stb.topmso.com.tw:8080/csr_mobile_client_web/Move_serviceAction.do?method=go_cust_con_fix_main&amp;cust_no_con=0&amp;accountNo=&amp;password=\n［裝機申告🔗］http://stb.topmso.com.tw:8080/csr_mobile_client_web/Move_serviceAction.do?method=go_cust_con_install_main&amp;cust_no_con=0&amp;accountNo=&amp;password=",
        "加值服務網址": "［LINE TV客服中心🔗］https://help.linetv.tw/hc/zh-tw",
        "時間": "虎尾櫃台-星期一～星期六　早上8：30~下午 6：00 星期日：休息，斗六櫃台-星期一～星期五　早上8：30~中午12：00；下午1：30~下午6：00 星期六、日：休息",
        "服務項目": "有線電視及寬頻網路服務",
        "服務地區": "斗六市、古坑鄉、林內鄉、土庫鎮、大埤鄉、虎尾鎮、莿桐鄉、西螺鎮、二崙鄉、斗南鎮",
        "app名稱": "哈TV行動客服(Google Play Store或Apple App Store)",
        "統一編號": "97176779"
    },
    {
        "class": "虎尾",
        "識別": ["虎尾"],
        "公司別": "佳聯有線-虎尾區",
        "地址電話": "雲林縣虎尾鎮光復路66號，市內電話：(04)449-8808",
        "官網": "https://www.cltv.com.tw/",
        "網址": "［官網🔗］https://www.cltv.com.tw/\n［維修申告🔗］http://stb.topmso.com.tw:8080/csr_mobile_client_web/Move_serviceAction.do?method=go_cust_con_fix_main&amp;cust_no_con=0&amp;accountNo=&amp;password=\n［裝機申告🔗］http://stb.topmso.com.tw:8080/csr_mobile_client_web/Move_serviceAction.do?method=go_cust_con_install_main&amp;cust_no_con=0&amp;accountNo=&amp;password=",
        "加值服務網址": "［LINE TV客服中心🔗］https://help.linetv.tw/hc/zh-tw",
        "時間": "虎尾櫃台-星期一～星期六　早上8：30~下午 6：00 星期日：休息",
        "服務項目": "有線電視及寬頻網路服務",
        "服務地區": "斗六市、古坑鄉、林內鄉、土庫鎮、大埤鄉、虎尾鎮、莿桐鄉、西螺鎮、二崙鄉、斗南鎮",
        "app名稱": "哈TV行動客服(Google Play Store或Apple App Store)",
        "統一編號": "97176779"
    },
    {
        "class": "斗六",
        "識別": ["斗六"],
        "公司別": "佳聯有線-斗六區",
        "地址電話": "雲林縣斗六市明德北路2段419號，市內電話：(04)449-8808",
        "官網": "https://www.cltv.com.tw/",
        "網址": "［官網🔗］https://www.cltv.com.tw/\n［維修申告🔗］http://stb.topmso.com.tw:8080/csr_mobile_client_web/Move_serviceAction.do?method=go_cust_con_fix_main&amp;cust_no_con=0&amp;accountNo=&amp;password=\n［裝機申告🔗］http://stb.topmso.com.tw:8080/csr_mobile_client_web/Move_serviceAction.do?method=go_cust_con_install_main&amp;cust_no_con=0&amp;accountNo=&amp;password=",
        "加值服務網址": "［LINE TV客服中心🔗］https://help.linetv.tw/hc/zh-tw",
        "時間": "斗六櫃台-星期一～星期五　早上8：30~中午12：00；下午1：30~下午6：00 星期六、日：休息",
        "服務項目": "有線電視及寬頻網路服務",
        "服務地區": "斗六市、古坑鄉、林內鄉、土庫鎮、大埤鄉、虎尾鎮、莿桐鄉、西螺鎮、二崙鄉、斗南鎮",
        "app名稱": "哈TV行動客服(Google Play Store或Apple App Store)",
        "統一編號": "97176779"
    },
    {
        "class": "北港",
        "識別": ["北港", "麥寮鄉", "台西鄉", "東勢鄉", "崙背鄉", "褒忠鄉", "四湖鄉", "北港鎮", "水林鄉", "口湖鄉", "元長鄉"],
        "公司別": "北港有線",
        "地址電話": "雲林縣元長鄉元南路80號，市內電話：(04)449-8808",
        "官網": "https://www.pkcatv.com.tw/",
        "網址": "［官網🔗］https://www.pkcatv.com.tw/\n［維修申告🔗］http://stb.topmso.com.tw:8080/csr_mobile_client_web/Move_serviceAction.do?method=go_cust_con_fix_main&amp;cust_no_con=0&amp;accountNo=&amp;password=\n［裝機申告🔗］http://stb.topmso.com.tw:8080/csr_mobile_client_web/Move_serviceAction.do?method=go_cust_con_install_main&amp;cust_no_con=0&amp;accountNo=&amp;password=",
        "加值服務網址": "［LINE TV客服中心🔗］https://help.linetv.tw/hc/zh-tw",
        "時間": "週一至週六：08：30 ~ 18：00，週日: 休息",
        "服務項目": "有線電視及寬頻網路服務",
        "服務地區": "麥寮鄉、台西鄉、東勢鄉、崙背鄉、褒忠鄉、四湖鄉、北港鎮、水林鄉、口湖鄉、元長鄉",
        "app名稱": "哈TV行動客服(Google Play Store或Apple App Store)",
        "統一編號": "97176757"
    },
    {
        "class": "新永安",
        "識別": ["新永安", "永康區", "新化區", "新市區", "安定區", "善化區", "山上區", "玉井區", "左鎮區", "楠西區", "南化區", "歸仁區", "仁德區", "關廟區", "龍崎區",
"大內區"],
        "公司別": "新永安有線",
        "地址電話": "台南市永康區廣興街95巷3號，市內電話：(06)7003120、(06)2718958",
        "官網": "https://www.hya.com.tw/",
        "網址": "［官網🔗］https://www.hya.com.tw/\n［維修申告🔗］http://stb.topmso.com.tw:8080/csr_mobile_client_web/Move_serviceAction.do?method=go_cust_con_fix_main&amp;cust_no_con=0&amp;accountNo=&amp;password=\n［裝機申告🔗］http://stb.topmso.com.tw:8080/csr_mobile_client_web/Move_serviceAction.do?method=go_cust_con_install_main&amp;cust_no_con=0&amp;accountNo=&amp;password=",
        "加值服務網址": "［LINE TV客服中心🔗］https://help.linetv.tw/hc/zh-tw",
        "時間": "星期一~星期五 08:30-18:20 受理退租僅受理至17:00止，星期六、日以及國定假日休",
        "服務項目": "有線電視及寬頻網路服務",
        "服務地區": "永康區、新化區、新市區、安定區、善化區、山上區、玉井區、左鎮區、楠西區、南化區、歸仁區、仁德區、關廟區、龍崎區、大內區",
        "app名稱": "哈TV行動客服(Google Play Store或Apple App Store)",
        "統一編號": "84999365"
    },
    {
        "class": "大揚",
        "識別": ["大揚", "水上鄉", "太保市", "朴子市", "新港鄉", "六腳鄉", "鹿草鄉", "布袋鎮", "東石鄉", "義竹鄉"],
        "公司別": "大揚有線",
        "地址電話": "嘉義縣朴子市德興里新吉庄536號，市內電話：(05)3203020、(05)3796699",
        "官網": "https://www.tycable.com.tw/",
        "網址": "［官網🔗］https://www.tycable.com.tw/\n［維修申告🔗］http://stb.topmso.com.tw:8080/csr_mobile_client_web/Move_serviceAction.do?method=go_cust_con_fix_main&amp;cust_no_con=0&amp;accountNo=&amp;password=\n［裝機申告🔗］http://stb.topmso.com.tw:8080/csr_mobile_client_web/Move_serviceAction.do?method=go_cust_con_install_main&amp;cust_no_con=0&amp;accountNo=&amp;password=",
        "加值服務網址": "［LINE TV客服中心🔗］https://help.linetv.tw/hc/zh-tw",
        "時間": "星期一至星期五，08:30至17:00，星期六日及國定假日休息",
        "服務項目": "有線電視及寬頻網路服務",
        "服務地區": "水上鄉、太保市、朴子市、新港鄉、六腳鄉、鹿草鄉、布袋鎮、東石鄉、義竹鄉",
        "app名稱": "哈TV行動客服(Google Play Store或Apple App Store)",
        "統一編號": "97165169"
    },
    {
        "class": "台基科",
        "識別": ["台灣基礎開發", "台基科"],
        "公司別": "台灣基礎開發",
        "地址電話": "台中市大里區國光路一段68號，市內電話：(04)449-5678",
        "官網": "https://www.tinp.net.tw/index.php/tw",
        "網址": "［官網🔗］https://www.tinp.net.tw/index.php/tw\n［維修申告🔗］http://stb.topmso.com.tw:8080/csr_mobile_client_web/Move_serviceAction.do?method=go_cust_con_fix_main&amp;cust_no_con=0&amp;accountNo=&amp;password=\n［裝機申告🔗］http://stb.topmso.com.tw:8080/csr_mobile_client_web/Move_serviceAction.do?method=go_cust_con_install_main&amp;cust_no_con=0&amp;accountNo=&amp;password=",
        "加值服務網址": "［LINE TV客服中心🔗］https://help.linetv.tw/hc/zh-tw",
        "時間": "週一至週五臨櫃服務：08:00-19:00，假日臨櫃服務：08:30-12:00 | 13:00-17:00",
        "服務項目": "有線電視及寬頻網路服務",
        "服務地區": "台中市、南投縣、雲林縣",
        "app名稱": "哈TV行動客服(Google Play Store或Apple App Store)",
        "統一編號": "12726274"
    }
                        ]
faq_data = load_faq_data('gs://top_qa_csv/中區(不含台基科)QA-all_new-20240604 v1.csv', 'utf-8')

normal_functions = [
    {
        "name": "search_bill",
        "description": "查詢未繳或需繳費的帳單",
        "parameters": {
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "description": "姓名"
                },
                "phone": {
                    "type": "string",
                    "description": "電話"
                }
            },
            "required": ["name", "phone"]
        }
    },
    {
        "name": "bill_return_line_internet",
        "description": "超商已繳費或網路開通或欠斷補繳需要恢復網路",
        "parameters": {
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "description": "姓名"
                },
                "phone": {
                    "type": "string",
                    "description": "電話"
                }
            },
            "required": ["name", "phone"]
        }
    },
    {
        "name": "bill_return_line_tv",
        "description": "超商已繳費或電視開通或欠斷補繳需要恢復電視或電視授權到期或繳完費多久恢復電視或電視畫面上顯示權限到期",
        "parameters": {
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "description": "姓名"
                },
                "phone": {
                    "type": "string",
                    "description": "電話"
                }
            },
            "required": ["name", "phone"]
        }
    },
    {
        "name": "send_message",
        "description": "發送新的簡訊帳單或補寄繳費帳單或補發繳費單",
        "parameters": {
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "description": "姓名"
                },
                "phone": {
                    "type": "string",
                    "description": "電話"
                }
            },
            "required": ["name", "phone"]
        }
    }
]


cust_functions = [
    {
        "name": "search_bill",
        "description": "查詢未繳或需繳費的帳單",
        "parameters": {
            "type": "object",
            "properties": {
                "custnum": {
                    "type": "string",
                    "description": "客戶編號"
                }
            },
            "required": ["custnum"]
        }
    },
    {
        "name": "bill_return_line_internet",
        "description": "超商已繳費或網路開通或欠斷補繳需要恢復網路",
        "parameters": {
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "description": "姓名"
                },
                "phone": {
                    "type": "string",
                    "description": "電話"
                }
            },
            "required": ["name", "phone"]
        }
    },
    {
        "name": "bill_return_line_tv",
        "description": "超商已繳費或電視開通或欠斷補繳需要恢復電視或電視授權到期或繳完費多久恢復電視或電視畫面上顯示權限到期",
        "parameters": {
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "description": "姓名"
                },
                "phone": {
                    "type": "string",
                    "description": "電話"
                }
            },
            "required": ["name", "phone"]
        }
    },
    {
        "name": "send_message",
        "description": "發送新的簡訊帳單或補寄繳費帳單或補發繳費單",
        "parameters": {
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "description": "姓名"
                },
                "phone": {
                    "type": "string",
                    "description": "電話"
                }
            },
            "required": ["name", "phone"]
        }
    }
]
