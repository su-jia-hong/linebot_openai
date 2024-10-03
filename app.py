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
@handler.add(MessageEvent, message=TextMessage)
def handle_message(event):
    user_message = event.message.text.strip()
    user_id = event.source.user_id  # 獲取 LINE 用戶的唯一 ID
    
    # 將 DataFrame 轉換為字串
    info_str = data.to_string(index=False)
    
    # 使用 OpenAI 生成回應
    response_text = get_openai_response(user_message, info_str)
    
    # 提取並處理購物車品項
    items = extract_item_name(user_message)
    for item_name, quantity in items:
        add_to_cart_response = add_item_to_cart(user_id, item_name, quantity, data)
        response_text += f"\n{add_to_cart_response['message']}"
    
    # 查看購物車功能
    if '查看購物車' in user_message:
        cart_display = display_cart(user_id)
        response_text += f"\n{cart_display}"
    
    # 確認訂單功能
    if '確認訂單' in user_message or '送出訂單' in user_message:
        order_confirmation = confirm_order(user_id, data, GOOGLE_CREDENTIALS_JSON, GOOGLE_SHEET_URL)
        response_text += f"\n{order_confirmation['message']}"
    
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
