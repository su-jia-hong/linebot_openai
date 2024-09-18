import openai
import pandas as pd
import re
from datetime import datetime
import gspread
from flask import Flask, request, abort

from linebot import (
    LineBotApi, WebhookHandler
)
from linebot.exceptions import (
    InvalidSignatureError
)
from linebot.models import *
from openai import OpenAI
import os
import traceback

# ======設定相關變數======
app = Flask(__name__)
static_tmp_path = os.path.join(os.path.dirname(__file__), 'static', 'tmp')
# Channel Access Token
line_bot_api = LineBotApi(os.getenv('CHANNEL_ACCESS_TOKEN'))
# Channel Secret
handler = WebhookHandler(os.getenv('CHANNEL_SECRET'))
# OPENAI API Key初始化設定
OpenAI.api_key = os.getenv('OPENAI_API_KEY')

# 讀取CSV資料
try:
    data = pd.read_csv('coffee2.csv', encoding='big5')
    print("CSV成功載入。")
except Exception as e:
    print(f"CSV載入失敗: {e}")
    exit()

# 初始化購物車
cart = []

# 將客人點餐品項與價格加入購物車中
def add_to_cart(item_name, quantity):
    global cart
    item = data[data['品項'] == item_name]
    if not item.empty:
        for _ in range(quantity):
            cart.append({
                "品項": item.iloc[0]['品項'],
                "價格": item.iloc[0]['價格']
            })
        return f"已將 {quantity} 杯 {item_name} 加入購物車。"
    else:
        return f"菜單中找不到品項 {item_name}。"

# 將中文數字轉換為阿拉伯數字
def chinese_to_number(chinese):
    chinese_numerals = {'一': 1, '二': 2, '三': 3, '四': 4, '五': 5, '六': 6, '七': 7, '八': 8, '九': 9, '十': 10}
    return chinese_numerals.get(chinese, 0)

# 提取品項名稱和數量
def extract_item_name(response):
    matches = re.findall(r'(\d+|[一二三四五六七八九十])\s*(杯|片|份|個)\s*([\w\s]+)', response)
    
    items = []
    for match in matches:
        quantity = int(match[0]) if match[0].isdigit() else chinese_to_number(match[0])
        item_name = match[2].strip()
        items.append((item_name, quantity))
    
    return items

# 移除購物車中的品項
def remove_from_cart(item_name, quantity=1):
    global cart
    item_count = sum(1 for item in cart if item['品項'] == item_name)
    
    if item_count == 0:
        return f"購物車中沒有找到 {item_name}。"
    
    remove_count = min(quantity, item_count)
    new_cart = []
    removed_items = 0
    
    for item in cart:
        if item['品項'] == item_name and removed_items < remove_count:
            removed_items += 1
        else:
            new_cart.append(item)
    
    cart = new_cart
    
    if removed_items > 0:
        return f"已從購物車中移除 {removed_items} 個 {item_name}。"
    else:
        return f"購物車中沒有找到 {item_name}。"

# 顯示購物車內容
def display_cart(cart):
    if not cart:
        print("您的購物車是空的。")
    else:
        cart_summary = {}
        for item in cart:
            item_name = item['品項']
            if item_name in cart_summary:
                cart_summary[item_name]['數量'] += 1
            else:
                cart_summary[item_name] = {
                    '價格': item['價格'],
                    '數量': 1
                }

        print("當前購物車:")
        for item_name, details in cart_summary.items():
            print(f"品項: {item_name} 價格: {details['價格']} 數量: {details['數量']}")

# 生成訂單編號
def generate_order_id():
    return datetime.now().strftime('%m%d%H%M')

# 更新現有工作表並上傳訂單
def update_existing_sheet(cart):
    gc = gspread.service_account(filename='token.json')
    sh = gc.open_by_url('https://docs.google.com/spreadsheets/d/1YPzvvQrQurqlZw2joMaDvDse-tCY9YX-7B2fzpc9qYY/edit?usp=sharing')
    worksheet = sh.get_worksheet(0)

    cart_summary = {}
    for item in cart:
        if item['品項'] in cart_summary:
            cart_summary[item['品項']]['數量'] += 1
        else:
            cart_summary[item['品項']] = {
                '價格': item['價格'],
                '數量': 1
            }

    order_df = pd.DataFrame([
        {'品項': item_name, '價格': details['價格'], '數量': details['數量']}
        for item_name, details in cart_summary.items()
    ])

    order_df['總價'] = order_df['價格'] * order_df['數量']
    order_df['訂單時間'] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    order_df['訂單編號'] = generate_order_id()

    data = [order_df.columns.values.tolist()] + order_df.values.tolist()
    worksheet.insert_rows(data, 1)

    print("訂單已成功寫入 Google 試算表")

# GPT 回應
def GPT_response(text):
    client = OpenAI()
    info_from_csv = data[['種類', '品項', '價格', '標籤']]
    info_str = f"Category: {info_from_csv['種類']}, Item: {info_from_csv['品項']}, Price: {info_from_csv['價格']}, Tag: {info_from_csv['標籤']}"
    completion = client.chat.completions.create(
        model="gpt-3.5-turbo",
        messages=[
            {"role": "system", "content": "你是一個線上咖啡廳點餐助手"},
            {"role": "system", "content": "根據以下數據回答問題: " + info_str},
            {"role": "user", "content": text},
        ]
    )
    answer = completion.choices[0].message.content
    return answer

# 監聽所有來自 /callback 的 Post Request
@app.route("/callback", methods=['POST'])
def callback():
    signature = request.headers['X-Line-Signature']
    body = request.get_data(as_text=True)
    app.logger.info("Request body: " + body)

    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        abort(400)
    return 'OK'

# 處理訊息
@handler.add(MessageEvent, message=TextMessage)
def handle_message(event):
    msg = event.message.text
    try:
        GPT_answer = GPT_response(msg)
        line_bot_api.reply_message(event.reply_token, TextSendMessage(GPT_answer))
    except:
        print(traceback.format_exc())
        line_bot_api.reply_message(event.reply_token, TextSendMessage('你所使用的OPENAI API key額度可能已經超過，請於後台Log內確認錯誤訊息'))

@handler.add(PostbackEvent)
def handle_message(event):
    print(event.postback.data)

@handler.add(MemberJoinedEvent)
def welcome(event):
    uid = event.joined.members[0].user_id
    gid = event.source.group_id
    profile = line_bot_api.get_group_member_profile(gid, uid)
    name = profile.display_name
    message = TextSendMessage(text=f'{name}歡迎加入')
    line_bot_api.reply_message(event.reply_token, message)

# 啟動Flask伺服器
if __name__ == "__main__":
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
