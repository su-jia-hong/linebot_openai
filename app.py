import os
import json
import gspread
from flask import Flask, request, jsonify
from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import MessageEvent, TextMessage, TextSendMessage
import openai
import pandas as pd
import re
from datetime import datetime
from shopping_cart import extract_item_name
from shopping_cart import (
    load_data,
    add_item_to_cart,
    remove_from_cart,
    display_cart,
    confirm_order,
    get_openai_response
)

app = Flask(__name__)

# 初始化 LINE Bot
line_bot_api = LineBotApi(os.getenv('CHANNEL_ACCESS_TOKEN'))
handler = WebhookHandler(os.getenv('CHANNEL_SECRET'))

# 初始化 OpenAI API Key
openai.api_key = os.getenv('OPENAI_API_KEY')

# 讀取 CSV 資料
data = load_data('coffee2.csv')
if data is None:
    print("Failed to load CSV data.")
    exit()

# 確認 Google Sheets 的 URL 和憑證
GOOGLE_SHEET_URL = 'https://docs.google.com/spreadsheets/d/1YPzvvQrQurqlZw2joMaDvDse-tCY9YX-7B2fzpc9qYY/edit?usp=drive_link'
GOOGLE_CREDENTIALS_JSON = os.getenv('GOOGLE_CREDENTIALS')

# LINE Bot Webhook 路由
@app.route("/callback", methods=['POST'])
def callback():
    signature = request.headers.get('X-Line-Signature', '')
    body = request.get_data(as_text=True)
    
    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        return 'Invalid signature', 400
    
    return 'OK'

# LINE Bot 處理訊息事件
# 用於存儲每個用戶的狀態
user_states = {}

@handler.add(MessageEvent, message=TextMessage)
def handle_message(event):
    user_message = event.message.text.strip()
    user_id = event.source.user_id  # 獲取 LINE 用戶的唯一 ID
    
    # 初始化用戶狀態
    if user_id not in user_states:
        user_states[user_id] = {'cart': [], 'step': 'start'}

    # 根據用戶當前的狀態處理消息
    current_state = user_states[user_id]['step']
    response_text = ""

    # 處理不同狀態下的用戶消息
    if current_state == 'start':
        if '查看購物車' in user_message:
            cart_display = display_cart(user_id)
            response_text += f"\n{cart_display}"
        elif '確認訂單' in user_message or '送出訂單' in user_message:
            order_confirmation = confirm_order(user_id, data, GOOGLE_CREDENTIALS_JSON, GOOGLE_SHEET_URL)
            response_text += f"\n{order_confirmation['message']}"
        else:
            items = extract_item_name(user_message)
            if items:
                for item_name, quantity in items:
                    add_to_cart_response = add_item_to_cart(user_id, item_name, quantity, data)
                    response_text += f"\n{add_to_cart_response['message']}"
                # 更新狀態為 "等待確認"
                user_states[user_id]['step'] = 'waiting_for_confirmation'
            else:
                response_text = get_openai_response(user_message, data.to_string(index=False))

    elif current_state == 'waiting_for_confirmation':
        if '確認' in user_message:
            order_confirmation = confirm_order(user_id, data, GOOGLE_CREDENTIALS_JSON, GOOGLE_SHEET_URL)
            response_text += f"\n{order_confirmation['message']}"
            user_states[user_id]['step'] = 'start'  # 重置狀態
        elif '取消' in user_message:
            response_text += "\n您的訂單已取消。"
            user_states[user_id]['step'] = 'start'  # 重置狀態
        else:
            response_text = "請問您要確認訂單嗎？還是取消訂單？"

    # 回應 LINE Bot 用戶
    line_bot_api.reply_message(
        event.reply_token,
        TextSendMessage(text=response_text)
    )




# 測試購物車內容的路由
@app.route("/test_display_cart", methods=['GET'])
def test_display_cart():
    # 為了測試，這裡假設使用特定的 user_id
    test_user_id = 'test_user'
    return display_cart(test_user_id)

# 啟動應用
if __name__ == '__main__':
    app.run(debug=True)
