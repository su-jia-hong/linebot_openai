# app.py
from flask import Flask, request, abort
from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import MessageEvent, TextMessage, TextSendMessage
import os
from shopping_cart import (load_data, add_to_cart, remove_from_cart, display_cart, update_existing_sheet, get_openai_response)

app = Flask(__name__)

# 環境變數設定
LINE_CHANNEL_ACCESS_TOKEN = os.getenv('LINE_CHANNEL_ACCESS_TOKEN')
LINE_CHANNEL_SECRET = os.getenv('LINE_CHANNEL_SECRET')

line_bot_api = LineBotApi(LINE_CHANNEL_ACCESS_TOKEN)
handler = WebhookHandler(LINE_CHANNEL_SECRET)

# 載入資料
data = load_data()

@app.route("/callback", methods=['POST'])
def callback():
    signature = request.headers.get('X-Line-Signature')
    body = request.get_data(as_text=True)

    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        abort(400)

    return 'OK'

@handler.add(MessageEvent, message=TextMessage)
def handle_message(event):
    user_message = event.message.text
    response_message = ""

    if user_message.lower() in ['查看購物車', 'cart']:
        response_message = display_cart()
    elif user_message.lower() in ['確認訂單']:
        response_message = update_existing_sheet(data)
    else:
        item_name = user_message  # 假設使用者輸入的即為品項名稱
        add_response = add_to_cart(data, item_name, 1)  # 預設數量為 1
        response_message = add_response

    line_bot_api.reply_message(event.reply_token, TextSendMessage(text=response_message))

if __name__ == "__main__":
    app.run(host='0.0.0.0', port=5000)
