import os
import pandas as pd
import re
import gspread
import openai
import logging
from datetime import datetime
from flask import Flask, request, jsonify, session
from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import MessageEvent, TextMessage, TextSendMessage

logging.basicConfig(level=logging.INFO)
app = Flask(__name__)
app.config['SESSION_TYPE'] = 'filesystem'  # 或者 'redis' 等
app.config['SECRET_KEY'] = os.getenv('SECRET_KEY')  # 確保設置了 SECRET_KEY
static_tmp_path = os.path.join(os.path.dirname(__file__), 'static', 'tmp')

# Channel Access Token
line_bot_api = LineBotApi(os.getenv('CHANNEL_ACCESS_TOKEN'))

# Channel Secret
handler = WebhookHandler(os.getenv('CHANNEL_SECRET'))

# OPENAI API Key初始化設定
openai.api_key = os.getenv('OPENAI_API_KEY')

# 讀取 CSV 資料
data = pd.read_csv('coffee2.csv', encoding='big5')

# 提取品項名稱和數量
def extract_item_name(response):
    matches = re.findall(r'(\d+|[一二三四五六七八九十])\s*(杯|片|份|個)\s*([\w\s]+)', response)
    return [(match[2].strip(), int(match[0]) if match[0].isdigit() else chinese_to_number(match[0])) for match in matches]

# 中文數字轉換
def chinese_to_number(chinese):
    return {'一': 1, '二': 2, '三': 3, '四': 4, '五': 5, '六': 6, '七': 7, '八': 8, '九': 9, '十': 10}.get(chinese, 0)

# 加入購物車
def add_to_cart(item_name, quantity):
    cart = session.get('cart', {})  # 使用字典來存儲購物車
    item = data[data['品項'] == item_name]
    
    if not item.empty:
        quantity = int(quantity)  # 確保數量是 int 類型
        price = float(item.iloc[0]['價格'])  # 確保價格是 float 類型
        
        # 如果品項已經在購物車中，增加數量，否則添加新項目
        if item_name in cart:
            cart[item_name]['數量'] += quantity
        else:
            cart[item_name] = {
                "品項": item_name,
                "價格": price,
                "數量": quantity
            }
        
        session['cart'] = cart  # 更新 session 中的購物車
        logging.info(f'Updated cart: {session["cart"]}')
        return f"已將 {quantity} 杯 {item_name} 加入購物車。"
    
    return f"菜單中找不到品項 {item_name}。"


# 查看購物車
def display_cart():
    cart = session.get('cart', {})
    logging.info(f'Current session cart: {cart}')
    if not cart:
        return "您的購物車是空的。"
    result = "當前購物車:\n"
    for item_name, details in cart.items():
        result += f"品項: {item_name}, 價格: {details['價格']}, 數量: {details['數量']}\n"
    return result

# 移除購物車中的品項
def remove_from_cart(item_name, quantity=1):
    cart = session.get('cart', [])
    
    # 計算購物車中某品項的數量
    item_count = sum(1 for item in cart if item['品項'] == item_name)

    if item_count == 0:
        return f"購物車中沒有找到 {item_name}。"

    # 需要移除的數量不能超過購物車中該品項的數量
    remove_count = min(quantity, item_count)

    # 移除指定數量的品項
    updated_cart = [item for item in cart if item['品項'] != item_name]  # 先排除所有該品項
    remaining_items = [item for item in cart if item['品項'] == item_name]  # 再找到該品項

    # 加回需要保留的部分
    updated_cart.extend(remaining_items[remove_count:])

    session['cart'] = updated_cart  # 更新 session 購物車

    return f"{remove_count} 個 {item_name} 已從購物車中移除。"

# 更新 Google Sheets 訂單
def update_existing_sheet():
    cart = session.get('cart', [])
    gc = gspread.service_account(filename='token.json')
    sh = gc.open_by_url('https://docs.google.com/spreadsheets/d/1YPzvvQrQurqlZw2joMaDvDse-tCY9YX-7B2fzpc9qYY/edit?usp=sharing')
    worksheet = sh.get_worksheet(0)

    cart_summary = {item['品項']: {'價格': item['價格'], '數量': cart.count(item)} for item in cart}
    order_df = pd.DataFrame([{'品項': name, '價格': details['價格'], '數量': details['數量']} for name, details in cart_summary.items()])
    order_df['總價'] = order_df['價格'] * order_df['數量']
    order_df['訂單時間'] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    order_df['訂單編號'] = datetime.now().strftime('%m%d%H%M')

    data = [order_df.columns.values.tolist()] + order_df.values.tolist()
    worksheet.insert_rows(data, 1)

    session.pop('cart', None)  # 清空購物車
    return "訂單已成功更新至 Google Sheets。"


@app.route("/", methods=['GET'])
def home():
    return "服務正常運行", 200

# Flask 路由處理 LINE Bot Webhook
@app.route("/callback", methods=['POST'])
def callback():
    signature = request.headers['X-Line-Signature']
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
    
    # 使用 OpenAI 生成回應
    response = openai.ChatCompletion.create(
        model="gpt-3.5-turbo",
        messages=[
            {"role": "system", "content": "你是一個線上咖啡廳點餐助手"},
            {"role": "system", "content": "answer the question considering the following data: "},
            {"role": "system", "content": "當客人點餐時，請務必回復品項和數量，例如：'好的，你點的是一杯美式，價格是50元 請問還需要為您添加其他的餐點或飲品嗎？' 或 '好的，您要一杯榛果拿鐵，價格為80元。請問還有其他需要幫忙的嗎？'"},
            {"role": "user", "content": user_message},
        ]
    )
    response = response.choices[0].message.content

    # 根據 GPT 的回應進行操作
    if '查看購物車' in user_message:
        line_bot_api.reply_message(event.reply_token, TextSendMessage(text=display_cart()))
    elif '確認訂單' in user_message:
        line_bot_api.reply_message(event.reply_token, TextSendMessage(text=update_existing_sheet()))
    else:
        # 自動加入購物車
        items = extract_item_name(response)
        if items:
            for item_name, quantity in items:
                add_response = add_to_cart(item_name, quantity)
                line_bot_api.reply_message(event.reply_token, TextSendMessage(text=add_response))
        else:
            line_bot_api.reply_message(event.reply_token, TextSendMessage(text="無法從回應中提取品項名稱。"))

# 啟動 Flask 伺服器
if __name__ == "__main__":
    app.run(port=5000)
