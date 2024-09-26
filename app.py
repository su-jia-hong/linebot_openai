from flask import Flask, request, jsonify
from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import MessageEvent, TextMessage, TextSendMessage
import os
import openai
import pandas as pd
import re
import gspread
from datetime import datetime

app = Flask(__name__)

# Channel Access Token & Secret
line_bot_api = LineBotApi(os.getenv('CHANNEL_ACCESS_TOKEN'))
handler = WebhookHandler(os.getenv('CHANNEL_SECRET'))

# OPENAI API Key
openai.api_key = os.getenv('OPENAI_API_KEY')

# 讀取 CSV 資料
try:
    data = pd.read_csv('coffee2.csv', encoding='big5')
except Exception as e:
    print(f"Failed to load CSV: {e}")
    exit()

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

# 增加購物車的品項
def add_item_to_cart(cart, item_name, quantity):
    item = data[data['品項'] == item_name]
    if not item.empty:
        for _ in range(quantity):
            cart.append({
                "品項": item.iloc[0]['品項'],
                "價格": int(item.iloc[0]['價格'])  # 確保價格為整數
            })
        return {"message": f"已將 {quantity} 杯 {item_name} 加入購物車。", "cart": cart}
    else:
        return {"message": f"菜單中找不到品項 {item_name}。"}

# 顯示購物車內容
def display_cart(cart):
    if not cart:
        return "購物車是空的"
    
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
    
    display_str = "購物車內容：\n"
    for item_name, details in cart_summary.items():
        display_str += f"{item_name}: {details['數量']} 杯, 每杯 {details['價格']} 元\n"
    
    return display_str

# 確認訂單並更新到 Google Sheets
def confirm_order(cart):
    gc = gspread.service_account(filename='token.json')
    sh = gc.open_by_url('https://docs.google.com/spreadsheets/d/1YPzvvQrQurqlZw2joMaDvDse-tCY9YX-7B2fzpc9qYY/edit?usp=sharing')
    worksheet = sh.get_worksheet(0)

    cart_summary = {}
    for item in cart:
        if item['品項'] in cart_summary:
            cart_summary[item['品項']]['數量'] += 1
        else:
            cart_summary[item['品項']] = {
                '價格': int(item['價格']),  # 確保價格為整數
                '數量': 1
            }

    order_df = pd.DataFrame([{'品項': item_name, '價格': details['價格'], '數量': details['數量']} for item_name, details in cart_summary.items()])
    order_df['總價'] = order_df['價格'] * order_df['數量']
    order_df['訂單時間'] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    order_df['訂單編號'] = datetime.now().strftime('%m%d%H%M')

    data = [order_df.columns.values.tolist()] + order_df.values.tolist()
    worksheet.insert_rows(data, 1)

    return {"message": "訂單已確認並更新到 Google Sheets。"}

# LINE Bot 處理訊息事件
@handler.add(MessageEvent, message=TextMessage)
def handle_message(event):
    user_message = event.message.text.strip()

    # 模擬用戶的購物車資料（這部分來自用戶，假設他在訊息中包含了購物車內容）
    cart = []

    # 使用 OpenAI 生成回應
    response = openai.ChatCompletion.create(
        model="gpt-3.5-turbo",
        messages=[
            {"role": "system", "content": "你是一個線上咖啡廳點餐助手"},
            {"role": "system", "content": "answer the question considering the following data: " + info_str},
            {"role": "system", "content": "當客人點餐時，請務必回復品項和數量，例如：'好的，你點的是一杯美式，價格是50元 請問還需要為您添加其他的餐點或飲品嗎？' 或 '好的，您要一杯榛果拿鐵，價格為80元。請問還有其他需要幫忙的嗎？'"},
            {"role": "user", "content": user_message}
        ]
    )
    response_text = response.choices[0].message.content

    # 提取並處理購物車品項
    items = extract_item_name(user_message)
    for item_name, quantity in items:
        add_to_cart_response = add_item_to_cart(cart, item_name, quantity)
        response_text += f"\n{add_to_cart_response['message']}"

    # 查看購物車功能
    if '查看購物車' in user_message:
        cart_display = display_cart(cart)
        response_text += f"\n{cart_display}"

    # 確認訂單
    if '確認訂單' in user_message:
        order_confirmation = confirm_order(cart)
        response_text += f"\n{order_confirmation['message']}"

    # 回應 LINE Bot 用戶
    line_bot_api.reply_message(
        event.reply_token,
        TextSendMessage(text=response_text)
    )

if __name__ == '__main__':
    app.run(debug=True)
