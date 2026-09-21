import functions_framework
from openai import OpenAI

from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import MessageEvent, TextMessage, TextSendMessage

import requests
import json

# access CSV file
import pandas as pd

# access google storage
import fsspec
import gcsfs

# best match required
import difflib
import os
import re

# 在雲端函數中處理多個用戶的對話歷史
import firebase_admin
from firebase_admin import credentials, db
import datetime
import pytz

import io
from PIL import Image
from google import genai

# Set the OpenAI API key
client = OpenAI(api_key=os.getenv('OPENAI_API_KEY'))
# 初始化 Gemini Client
gemini_client = genai.Client(api_key=os.getenv('GEMINI_API_KEY'))
# Line Messaging API 令牌
LINE_CHANNEL_ACCESS_TOKEN = os.getenv('LINE_CHANNEL_ACCESS_TOKEN')
LINE_CHANNEL_SECRET = os.getenv('LINE_CHANNEL_SECRET')

#  真人客服 Line Bot
group_id = os.getenv('GROUP_ID')
NeedHumanAlert_user_ID = os.getenv('HUMAN_ID')
NeedHumanAlert_channel_access_token = os.getenv('HUMAN_ACCESS_TOKEN')

tv_num = 0
tv_dict = [['台數科', ""], ['大屯', '大屯'], ['佳聯', '佳聯'], ['北港', '北港']]
df_name, df_area = tv_dict[tv_num]
# 線上LINE資料庫(firebase)
cred = credentials.Certificate('line-cust-chat-firebase-adminsdk.json')
firebase_admin.initialize_app(cred, {
    'databaseURL': 'https://line-only-chat-default-rtdb.firebaseio.com/'
})


def load_faq_data(csv_file, encode):
    """使用 pandas 從使用Big-5編碼的CSV文件中載入QA資料集"""
    # 讀取 CSV 文件，指定 Big-5 編碼，假設第一列是問題，第二列是答案
    df = pd.read_csv(csv_file, header=None, encoding=encode)
    # 轉換DataFrame為字點，第0列作為鍵（問題），第1列作為值（答案）
    faq_dict = pd.Series(df[1].values, index=df[0]).to_dict()
    return faq_dict


# 載入問答數據
faq_data = load_faq_data('gs://top_qa_csv/中區(不含台基科)QA-all_new-20240604 v1.csv', 'utf-8')

'''
def get_service_account_info():
    credentials, project_id = google.auth.default()

    # 檢查憑證是否需要重新整理
    if not credentials.valid:
        auth_req = google.auth.transport.requests.Request()
        credentials.refresh(auth_req)

    # 取得服務帳戶的 email 地址
    service_account_email = credentials.service_account_email

    return f"目前使用中的服務帳戶是： {service_account_email}"
'''

human_keyword_groups = [
    ["專人", "專員"],
    ["真人", "眞人"]
]
keep_dialog_keyword_groups = [
    ["為了能", "為了更"],
    ["請提供", "請您提供"],
    ["?"]
]
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
        "識別": ["中投", "南投市", "鹿谷鄉", "竹山鎮", "集集鎮", "名間鄉", "水里鄉", "仁愛鄉", "信義鄉", "埔里鎮",
                 "魚池鄉", "國姓鄉", "草屯鎮", "中寮鄉"],
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
        "識別": ["佳聯", "斗六市", "古坑鄉", "林內鄉", "土庫鎮", "大埤鄉", "虎尾鎮", "莿桐鄉", "西螺鎮", "二崙鄉",
                 "斗南鎮"],
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
        "識別": ["北港", "麥寮鄉", "台西鄉", "東勢鄉", "崙背鄉", "褒忠鄉", "四湖鄉", "北港鎮", "水林鄉", "口湖鄉",
                 "元長鄉"],
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
        "識別": ["新永安", "永康區", "新化區", "新市區", "安定區", "善化區", "山上區", "玉井區", "左鎮區", "楠西區",
                 "南化區", "歸仁區", "仁德區", "關廟區", "龍崎區",
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
    # {
    #     "class": "台基科",
    #     "識別": ["台基科", "彰化市", "鹿港鎮", "和美鎮", "線西鄉", "申港鄉", "福興鄉", "秀水鄉", "花壇鄉", "芬園鄉",
    #              "溪湖鎮", "大村鄉", "埔鹽鄉"],
    #     "公司別": "台基科",
    #     "地址電話": "無，市內電話：(04)449-5678",
    #     "官網": "無",
    #     "時間": "無",
    #     "服務項目": "寬頻網路服務",
    #     "服務地區": "彰化市、鹿港鎮、和美鎮、線西鄉、申港鄉、福興鄉、秀水鄉、花壇鄉、芬園鄉、溪湖鎮、大村鄉、埔鹽鄉",
    #     "app名稱": "無",
    #     "統一編號": "12726274"
    # }

]

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
    },
    {
        "name": "payment_bill_batch",
        "description": "超商已經繳費需要恢復訊號",
        "parameters": {
            "type": "object",
            "properties": {
                "bills": {
                    "type": "array",
                    "description": "包含一組或多組條碼的列表",
                    "items": {
                        "type": "object",
                        "properties": {
                            "first_num": {
                                "type": "string",
                                "description": "第一段條碼 (通常為公司代碼)"
                            },
                            "second_num": {
                                "type": "string",
                                "description": "第二段條碼 (通常為代收項目或用戶編號)"
                            },
                            "third_num": {
                                "type": "string",
                                "description": "第三段條碼 (通常為應繳金額與校驗碼)"
                            }
                        },
                        "required": ["first_num", "second_num", "third_num"]
                    }
                }
            },
            "required": ["bills"]
        }
    }
]


def clear_ai_text(text):
    clear_text = re.sub(r"[*#]", "", text)
    return clear_text


def remove_symbols(text):
    # 建立一個翻譯表來移除user暱稱標點符號
    symbols = str.maketrans('', '', '!@#$%^&*()[]{};:,./<>?\|`~-=_+')
    return text.translate(symbols)


def search_company(keyword):  # add
    results = []
    for company in company_profiles:
        if any(town in keyword for town in company["識別"]):
            results = company
            break
    return results


def check_keywords(text, keyword_groups):
    """
    檢查文字內容是否包含任何關鍵字組中的關鍵字。

    :param text: 要檢查的文字內容
    :param keyword_groups: 關鍵字組列表，每組關鍵字以列表表示
    :return: 如果找到任何關鍵字組中的關鍵字，返回True，否則返回False
    """
    for keywords in keyword_groups:
        for keyword in keywords:
            if keyword in text:
                return True
    return False


# 獲取用戶對話歷史
def get_chat_history(user_id, user_name):
    try:
        ref = db.reference(f'ChatHistory/{user_id}')
        entity = ref.get()
        cust_status = entity.get('cust_status') if entity else None
        end_time = entity.get('end_time') if entity else None  # add
        area = entity.get('area') if entity else None  # add
        name = entity.get('name') if entity else None  # add
        if cust_status:
            print("用戶狀態：" + str(cust_status))
        else:
            cust_status = 0
            ref.update({'cust_status': 0})
            print("用戶狀態：" + str(cust_status))
        # 建立 UTC+8 的時區物件
        tz_utc8 = datetime.timezone(datetime.timedelta(hours=8))
        if end_time:  # add
            temp_end_time = datetime.datetime.fromisoformat(end_time)
            if temp_end_time.tzinfo is not None and temp_end_time.tzinfo.utcoffset(temp_end_time) is not None:
                print(f"用戶最後時間：{end_time}")
            else:
                print("添加無時區")
                end_time = temp_end_time.replace(tzinfo=tz_utc8).isoformat()
                print(f"用戶最後時間：{end_time}")
        else:  # add
            # 取得當前時間並加上 UTC+8 時區
            end_time = datetime.datetime.now(tz_utc8).isoformat()
            print(f"用戶最後時間：{end_time}")
        if area:  # add
            print("用戶地區：" + area)
        else:  # add
            area = df_area
            ref.update({'area': area})
            print("用戶地區：" + str(area))
        if name == user_name:  # add
            print("用戶暱稱：" + name)
        else:  # add
            ref.update({'name': user_name})
            print("用戶暱稱：" + user_name)
        if entity:
            history = entity.get('history', [])
            filtered_history = [
                {'end_dialog': entry['end_dialog'], 'company': entry['company'], 'question': entry['question'],
                 'role': entry['role'], 'content': entry['content'], 'timestamp': entry['timestamp']} for entry in
                history]
            return filtered_history, cust_status, end_time, area  # add
        return [], cust_status, end_time, area  # add
    except Exception as e:
        # 處理異常情況，例如記錄異常信息
        print(f"Error fetching chat history for user {user_id}: {str(e)}")
        # 返回空列表或其他適當的值來表示失敗
        return []


# 保存用戶對話歷史
def save_chat_history(user_id, question, role, message):
    try:
        ref = db.reference(f'ChatHistory/{user_id}')
        entity = ref.get()
        history = entity.get('history')
        # 獲取當前歷史
        current_history = {'history': history} if history else {'history': []}
        service_company = search_company(question)
        if service_company:
            company = service_company['公司別']
        else:
            company = 'NONE'

        end_dialog = '0' if check_keywords(message, keep_dialog_keyword_groups) else '1'
        # 建立 UTC+8 的時區物件
        tz_utc8 = datetime.timezone(datetime.timedelta(hours=8))
        # 更新歷史
        current_history['history'].append({
            'end_dialog': end_dialog,
            'question': question,
            'company': company,
            'role': role,
            'content': message,
            'timestamp': datetime.datetime.now(tz_utc8).isoformat()
        })
        # print(current_history)
        # 保存更新後的歷史
        ref.update(current_history)
    except Exception as e:
        # 處理異常情況，例如記錄異常信息
        print(f"Error saving chat history for user {user_id}: {str(e)}")


def save_cust_status(cust_status, user_id):
    ref = db.reference(f'ChatHistory/{user_id}')
    ref.update({'cust_status': cust_status})


def save_end_time(now_time, user_id):  # add
    ref = db.reference(f'ChatHistory/{user_id}')
    ref.update({'end_time': now_time})


def save_area(area, user_id):  # add
    ref = db.reference(f'ChatHistory/{user_id}')
    ref.update({'area': area})


# 清理指定用戶的舊的對話歷史
def clean_old_histories(user_id):
    try:
        ref = db.reference(f'ChatHistory/{user_id}')
        user_history = ref.get()
        if user_history and 'history' in user_history:
            sorted_histories = sorted(user_history['history'], key=lambda x: x['timestamp'])
            if len(sorted_histories) >= 50:  # 50筆將會進行清除
                # 保留最新的20筆記錄
                new_history = sorted_histories[-19:]
                ref.child('history').set(new_history)
    except Exception as e:
        # 處理異常情況，例如記錄異常信息
        print(f"Error cleaning old chat histories for user {user_id}: {str(e)}")


'''
def find_best_match(question, faq_dict):
    """找出最匹配的问题及其答案"""
    questions = list(faq_dict.keys())
    # 使用 difflib 找到最接近的问题
    best_matches = difflib.get_close_matches(question, questions, n=1, cutoff=0.3)
    if best_matches:
        best_question = best_matches[0]
        return best_question, faq_dict[best_question]
    else:
        return "No match found", "No answer available"
'''


def find_best_matches(question, faq_dict, max_matches=6):
    """找出最匹配的問題及其答案"""
    questions = list(faq_dict.keys())
    # 使用 difflib 找到最接近的問題
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


def replace_markdown_links_with_html(text):
    # 轉換 Markdown 樣式的連結為 HTML 連結
    # pattern = re.compile(r'\[([^\]]+)\]\((https?://[^\s)]+)\)')
    # return pattern.sub(r"<a href='\2' target='_blank'>\1</a>", text)
    # 支援全形或半形中括號
    pattern = re.compile(r'[［\[]([^\]］]+)[\]］]\((https?://[^\s)]+)\)')
    return pattern.sub(r"\n[\1]\n\2\n", text)


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

    json_text = call_json_text2(json_data, token)

    print(json_text)
    return json_text


def get_completion(user_name, prompt, documents, line_bot_api, tk, user_id, msg_type, model_used="gpt-4o"):
    clean_old_histories(user_id)

    # 獲取用戶的對話歷史, Error fetchin師, waiting for debug
    chat_history, cust_status, end_time, area = get_chat_history(user_id, user_name)  # add
    # 預設公司
    service_company = """你是「哈寶寶」，一個親切、活潑、樂於幫助用戶的客服助手。
                你的任務是協助用戶查詢台數科集團旗下各系統台的服務（有線電視與寬頻）。

                當用戶沒有明確說出系統台時，你需要引導用戶選擇或說出系統台名稱。

                台數科集團系統台包含：

                大屯（有線電視、寬頻）
                中投（有線電視、寬頻）
                佳光（有線電視、寬頻）
                北港（有線電視、寬頻）
                佳聯（有線電視、寬頻）
                新永安（有線電視、寬頻）
                大揚（有線電視、寬頻）
                台基科（寬頻）
                佳光市區（寬頻）

                請用親切、簡單的方式詢問，例如：
                👉「請問您想了解哪一個系統台的服務呢？像是大屯、中投、佳光…都可以跟我說喔！」

                必要時可以舉例，但避免一次列出過多資訊造成負擔。"""
    # service_company = "\n".join([
    #     f"服務於{company['公司別']}, 公司地址: {company['地址電話']},\n"
    #     f"公司網址: {company['網址']}\n"
    #     f"加值服務網址: {company['加值服務網址']}\n"
    #     f"營業時間: {company['時間']}\n"
    #     f"服務項目: {company['服務項目']}, 服務地區: {company['服務地區']}\n"
    #     f"app: {company['app名稱']}, 統一編號: {company['統一編號']}"
    #     for company in company_profiles
    # ])
    # deafult status , set end_dialog = true/1
    end_dialog = '1'
    strQuestion_history = ''

    # 檢查是否有歷史對話紀錄
    if not chat_history:
        print("這是用戶的第一次對話")
    else:
        print("用戶有歷史對話紀錄")
        # 在這裡加入針對有歷史對話的處理邏輯
        try:
            summary = "\n".join([f"question:{item['question']}\nanswer:{item['content']}" for item in chat_history])
            print(f'用戶的歷史對話紀錄:\n{summary}')
        except Exception as e:
            print(e)
        # question_history = [f"{entry['question']}\n" for entry in chat_history]
        index = 0
        for company_entry in chat_history:
            end_dialog = company_entry['end_dialog']
            if end_dialog == '1':
                strQuestion_history = ''  # reset it
            else:
                strQuestion_history = (f"{strQuestion_history}\n{company_entry['question']}\n")

    # add
    if area:
        company = search_company(area)
        if company:
            service_company = f"服務於{company['公司別']}, 公司地址: {company['地址電話']},\n公司網址: {company['網址']},\n加值服務網址: {company['加值服務網址']},\n營業時間: {company['時間']}\n服務項目: {company['服務項目']}, 服務地區: {company['服務地區']}\napp: {company['app名稱']}, 統一編號: {company['統一編號']}"
    else:
        company = search_company(prompt)
        if company:
            service_company = f"服務於{company['公司別']}, 公司地址: {company['地址電話']},\n公司網址: {company['網址']},\n加值服務網址: {company['加值服務網址']},\n營業時間: {company['時間']}\n服務項目: {company['服務項目']}, 服務地區: {company['服務地區']}\napp: {company['app名稱']}, 統一編號: {company['統一編號']}"
            area = company['識別'][0]
            save_area(area, user_id)  # add

    print(f'service company: {service_company}\n')
    system_prompt = (
        "你是專業的有線電視與寬頻客服助理，名為哈寶寶。\n"
        f"你所屬公司為：{service_company}\n"
        "服務產品包含數位電視、寬頻上網、LINE TV（合作加值服務）、哈TV，以及無線分享器(Mesh WiFi)、監視器(IP Camera)等加值服務。\n\n"

        "你的任務是：根據【檢索問答集資料】、【最新資訊】、【回答優先順序】、【回答原則】、【真人客服規則】、"
        "【網址規則】、【電話規則】、【禁止事項】、【工具觸發規則】、【回答風格】，提供正確、保守且一致的客服回覆。\n\n"

        "[檢索問答集資料]\n"
        f"{documents}\n\n"

        # "[最新資訊]\n"
        # f"{the_news}\n\n"

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
    # 發現要求真人對談關鍵字時，送訊息到 line chat room
    # 建立 UTC+8 的時區物件
    tz_utc8 = datetime.timezone(datetime.timedelta(hours=8))
    # 取得當前時間並加上 UTC+8 時區
    now_time = datetime.datetime.now(tz_utc8).isoformat()
    # now_time = datetime.datetime.now()
    print('A')
    print((datetime.datetime.fromisoformat(now_time) - datetime.datetime.fromisoformat(end_time)).total_seconds())
    if cust_status == 1 and (datetime.datetime.fromisoformat(now_time) - datetime.datetime.fromisoformat(
            end_time)).total_seconds() >= 1200:  # add
        answer = '✨⭐💛已轉換為AI智能模式，請稍後...💛⭐✨'
        cust_status = 0
        save_cust_status(cust_status, user_id)  # add 2025-11-03
    if cust_status == 0:
        if check_keywords(prompt, human_keyword_groups):
            cust_status = 1
            save_cust_status(cust_status, user_id)  # add 2025-11-03
            answer = '✨⭐💛已轉換為真人客服模式，請稍候...💛⭐✨'
            # 以下為轉發群組通知功能
            formatted_entries = [
                f"-->{entry['question']}\n\n{entry['content']}\n" for entry in chat_history
            ]
            filtered_history = "\n".join(formatted_entries)
            print(f'filtered_history: {filtered_history}')
            try:
                send_line_message(group_id, NeedHumanAlert_channel_access_token,
                                  f'{df_name}用戶\nUser: {user_name}\nQ: {prompt}\n歷史對話:\n\n{filtered_history}')
            except Exception as e:
                print("Error_line_push" + e)
    print('B')
    if cust_status > 0:
        pass
    else:
        if msg_type != 'text' and msg_type != 'image':
            answer = "抱歉，無法辨識此類訊息，請輸入文字問題繼續與AI客服互動，或輸入「真人客服」等待專人為您服務。"
        else:
            msg = [{'role': entry['role'], 'content': entry['content']} for entry in chat_history[-5:]]
            msg.append({"role": "system", "content": "".join(system_prompt)})
            msg.append({"role": "user", "content": strQuestion_history + prompt})
            '''
            msg = [
                {"role": "system", "content": documents},
                {"role": "user", "content": prompt}]
            '''

            response = client.chat.completions.create(
                model=model_used,
                messages=msg,
                temperature=0.5,
                functions=normal_functions,
                function_call="auto"
            )
            # 獲取回答
            answer = response.choices[0].message.content
            dict_data = []
            if answer:
                pass
            else:
                dict_data = json.loads(response.choices[0].message.function_call.arguments)
                answer = response.choices[0].message.function_call.name
                answer = get_functions(answer, dict_data)
            answer = clear_ai_text(answer)
            answer = replace_markdown_links_with_html(answer)
        print(f'AI answer: {answer}')
    print('C')
    save_end_time(now_time, user_id)  # add
    print('D')
    # 保存更新後的對話歷史
    if answer and prompt:
        save_chat_history(user_id, prompt, 'assistant', answer)
    return answer


def get_functions(func_name, json_data):
    respText = "發送失敗，請重新詢問"

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

    actions = {
        "search_bill": {
            "print": "call search_bill",
            "api": call_search_bill,
            "missing_msg": "姓名或電話格式有誤!\n請再提供姓名或電話以便為您查詢帳單"
        },
        "bill_return_line_internet": {
            "print": "call bill_return_line_internet",
            "api": bill_return_line_internet,
            "missing_msg": "姓名或電話格式有誤!\n請再提供姓名或電話以便為您網路復線"
        },
        "bill_return_line_tv": {
            "print": "call bill_return_line_tv",
            "api": bill_return_line_tv,
            "missing_msg": "姓名或電話格式有誤!\n請再提供姓名或電話以便為您電視復線"
        },
        "send_message": {
            "print": "call send_message",
            "api": send_message,
            "missing_msg": "姓名或電話格式有誤!\n請再提供姓名或電話以便為您發送簡訊帳單"
        }
    }

    action = actions.get(func_name)
    if not action:
        return respText

    print(action["print"])

    # 先驗證姓名電話，不通過就不要 get_token()
    if not valid_name_tel(json_data):
        return action["missing_msg"]

    token = get_token()
    if token:
        json_text = call_json_text2(json_data, token)
        respText = action["api"](json_text)

    return respText


def get_token():
    print("呼叫token網址")
    response = requests.get(
        'https://test/eBillAction.do?method=getToken',
        verify=False, timeout=30)
    # 檢查回應狀態碼
    if response.status_code == 200:
        print("請求成功token！")
        print(response.json())  # 如果回應為 JSON 格式，可以直接解析
        data = response.json()
        return data["token"]
    else:
        print(f"發生錯誤，狀態碼：{response.status_code}")
        return ""


def call_json_text2(json_data, token):
    json_text = {
        "token": token,
        "custTel": json_data["phone"],
        "custCName": json_data["name"]
    }
    return json_text


def call_search_bill(json_text):
    response = requests.get(
        'https://test/eBillAction.do?method=getCustBill',
        verify=False, json=json_text, timeout=30)
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
    response = requests.get(
        'https://test/eBillAction.do?method=changeReceive',
        verify=False, json=json_text, timeout=30)
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
    response = requests.get(
        'https://test/eBillAction.do?method=dtvChangeReceive',
        verify=False, json=json_text, timeout=30)
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
    response = requests.get(
        'https://test/eBillAction.do?method=reBillE',
        verify=False, json=json_text, timeout=30)
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
                "https://test/eBillAction.do?method=receiveByBarCode",
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


def check_and_update_limit(user_id):
    # 1. 取得台灣時間日期
    tz = pytz.timezone('Asia/Taipei')
    today = datetime.datetime.now(tz).strftime('%Y-%m-%d')

    # 2. 定位到該用戶的 usage_limit 路徑
    limit_ref = db.reference(f'ChatHistory/{user_id}/usage_limit')
    data = limit_ref.get()

    limit_max = 5  # 每日上限
    print("check start")
    # 3. 判斷邏輯
    if data is None or data.get('last_date') != today:
        # 如果沒有紀錄，或是日期不是今天 -> 重置為 1
        print("check first")
        limit_ref.set({
            'count': 1,
            'last_date': today
        })
        return True, "1/5"

    else:
        current_count = data.get('count', 0)
        if current_count < limit_max:
            # 沒超過 5 張 -> 次數 +1
            print("check sec")
            new_count = current_count + 1
            limit_ref.update({
                'count': new_count
            })
            return True, f"{new_count}/{limit_max}"
        else:
            # 超過 5 張 -> 拒絕
            print("check third")
            return False, "今日額度已用完"


def handle_image_message(message_content):
    # 1. 將 Binary 轉為 BytesIO 流，再轉成 PIL Image 物件
    # 使用 io.BytesIO 是因為 PIL.Image.open 需要一個「檔案形式」的輸入
    img_bin = io.BytesIO(message_content.content)
    img = Image.open(img_bin)

    # (可選) 縮小圖片以節省配額與加速反應
    img.thumbnail((1024, 1024))
    image_prompt = ("請簡單描述這張圖片的內容、場景和任何可識別的物件。\n"
                    "如果是收據請條列出每一筆的第一、二、三條碼後面的編號列出來\n"
                    "格式如下:\n"
                    "代收項目: 代號 繳費名稱\n"
                    "第一段條碼 一串數字英文\n"
                    "第二段條碼 一串數字英文\n"
                    "第三段條碼 一串數字英文\n")
    try:
        # 2. 呼叫 Gemini API
        response = gemini_client.models.generate_content(
            model="gemini-2.5-pro",  # 建議先用穩定版，避免 banana 版配額問題
            contents=[
                "".join(image_prompt),
                img
            ]
        )

        # 4. 將結果回傳給 LINE 使用者
        print(response.text)
        msg = response.text

    except Exception as e:
        print(f"發生錯誤: {e}")
        msg = "圖片分析失敗"
    finally:
        return msg


def webhook(request):
    try:
        # print(get_service_account_info())
        access_token = LINE_CHANNEL_ACCESS_TOKEN
        secret = LINE_CHANNEL_SECRET
        body = request.get_data(as_text=True)
        json_data = json.loads(body)
        # print(f'json data: {json_data}')

        line_bot_api = LineBotApi(access_token)
        handler = WebhookHandler(secret)
        signature = request.headers['X-Line-Signature']
        handler.handle(body, signature)
        msg = json_data['events'][0]['message'].get('text')
        if not msg:
            msg = "此訊息無法讀取"
        tk = json_data['events'][0]['replyToken']
        msg_type = json_data['events'][0]['message']['type']

        # get username from line
        user_name = 'unKnow'
        user_id = json_data['events'][0]['source']['userId']
        print(f'user Id: {user_id}')
        user_profile = get_line_user_profile(user_id)
        user_name = user_profile.get('displayName')
        user_name = remove_symbols(user_name)
        # print(user_name)
        ref = db.reference(f'ChatHistory/{user_id}')
        entity = ref.get()
        cust_status = entity.get('cust_status') if entity else 0  # sp特殊
        if "image" == msg_type and cust_status == 0:
            print("開始計算")
            success, msg = check_and_update_limit(user_id)
            if success:
                print(f"允許辨識，目前進度: {msg}")
            else:
                print(f"攔截請求: {msg}")
                respText = "今日圖片辨識次數已達到上限，造成您的困擾非常抱歉~"
                line_bot_api.reply_message(tk, TextSendMessage(respText))
                return 'OK'
            # --- 步驟 1: 從 LINE 取得圖片內容 ---
            msgID = json_data['events'][0]['message']['id']  # 取得訊息 id
            message_content = line_bot_api.get_message_content(msgID)  # 根據訊息 ID 取得訊息內容
            msg = handle_image_message(message_content)
        matches = find_best_matches(msg, faq_data)
        formatted_qa = format_matches_for_rag(matches)
        print(f'Msg: {msg}\n')
        print(f"QA查詢\n{formatted_qa}")

        respText = get_completion(user_name, msg, formatted_qa, line_bot_api, tk, user_id, msg_type)
        if respText:
            line_bot_api.reply_message(tk, TextSendMessage(respText))
        return 'OK'
    except Exception as e:
        return f"Error: {str(e)}"


# 取得LINE用戶帳號名稱
def get_line_user_profile(user_id):
    line_profile_url = f'https://api.line.me/v2/bot/profile/{user_id}'
    headers = {
        'Authorization': f'Bearer {LINE_CHANNEL_ACCESS_TOKEN}',
    }
    response = requests.get(line_profile_url, headers=headers, timeout=30)
    if response.status_code == 200:
        return response.json()
    else:
        print(f'取得用戶資料失敗: {response.status_code}, {response.text}')
        return {}


# 主動push訊息給LINE用戶
def send_line_message(user_id, channel_token, message_text):
    line_messaging_api_url = 'https://api.line.me/v2/bot/message/push'
    headers = {
        'Authorization': f'Bearer {channel_token}',
        'Content-Type': 'application/json'
    }
    payload = {
        'to': user_id,
        'messages': [
            {
                'type': 'text',
                'text': message_text
            }
        ]
    }
    response = requests.post(line_messaging_api_url, headers=headers, json=payload, timeout=30)
    if response.status_code == 200:
        print('訊息發送成功')
    else:
        print(f'訊息發送失敗: {response.status_code}, {response.text}')


@functions_framework.http
def hello_http(request):
    """HTTP Cloud Function.
    Args:
        request (flask.Request): The request object.
        <https://flask.palletsprojects.com/en/1.1.x/api/#incoming-request-data>
    Returns:
        The response text, or any set of values that can be turned into a
        Response object using `make_response`
        <https://flask.palletsprojects.com/en/1.1.x/api/#flask.make_response>.
    """
    request_json = request.get_json(silent=True)
    request_args = request.args

    if request_json and 'name' in request_json:
        name = request_json['name']
    elif request_args and 'name' in request_args:
        name = request_args['name']
    else:
        name = 'World'
    return 'Hello {}!'.format(name)
