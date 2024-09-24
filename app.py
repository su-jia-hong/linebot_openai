from flask import Flask, request, session, jsonify
from flask_session import Session
from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import MessageEvent, TextMessage, TextSendMessage
import os
import openai
import pandas as pd
import re
import gspread
from datetime import datetime
import redis


# 初始化 Flask 應用
app = Flask(__name__)

secret_key = os.getenv('SECRET_KEY')
if not secret_key:
    raise ValueError("SECRET_KEY is not set")
app.config['SECRET_KEY'] = secret_key

# 從環境變數中讀取 Redis URL
redis_url = os.getenv('REDIS_URL')

# 配置 Flask Session 使用 Redis
app.config['SESSION_TYPE'] = 'redis'
app.config['SESSION_PERMANENT'] = False
app.config['SESSION_USE_SIGNER'] = True
app.config['SESSION_KEY_PREFIX'] = 'session:'

# 使用 Redis URL 進行連接
app.config['SESSION_REDIS'] = redis.StrictRedis.from_url(redis_url)
# 啟用 Session
Session(app)

# Channel Access Token
line_bot_api = LineBotApi(os.getenv('CHANNEL_ACCESS_TOKEN'))

# Channel Secret
handler = WebhookHandler(os.getenv('CHANNEL_SECRET'))

# OPENAI API Key初始化設定
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

# 轉換價格為整數
def convert_price(price):
    return int(price) if isinstance(price, (int, float)) else price

# 增加購物車的品項
def add_item_to_cart(item_name, quantity):
    if 'cart' not in session:
        session['cart'] = []
    
    cart = session['cart']
    item = data[data['品項'] == item_name]
    if not item.empty:
        for _ in range(quantity):
            cart.append({
                "品項": item.iloc[0]['品項'],
                "價格": int(item.iloc[0]['價格'])  # 確保價格為整數
            })
        session['cart'] = cart
        return {"message": f"已將 {quantity} 杯 {item_name} 加入購物車。", "cart": cart}
    else:
        return {"message": f"菜單中找不到品項 {item_name}。"}

# 顯示購物車內容的函數
def display_cart():
    cart = session.get('cart', [])
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
        display_str += f"{item_name}: {details['數量']} 個, 每個 {details['價格']} 元\n"
    
    return display_str

# 增加購物車的品項
@app.route('/add_to_cart', methods=['POST'])
def add_to_cart():
    item_name = request.json.get('item')
    quantity = request.json.get('quantity', 1)
    return add_item_to_cart(item_name, quantity)

# 顯示購物車內容
@app.route('/view_cart')
def view_cart():
    return display_cart()

# 從購物車移除品項
@app.route('/remove_from_cart', methods=['POST'])
def remove_from_cart():
    item_name = request.json.get('item')
    quantity = request.json.get('quantity', 1)
    
    cart = session.get('cart', [])
    item_count = sum(1 for item in cart if item['品項'] == item_name)
    
    if item_count == 0:
        return {"message": f"購物車中沒有找到 {item_name}。"}
    
    remove_count = min(quantity, item_count)
    new_cart = [item for item in cart if not (item['品項'] == item_name and remove_count > 0)]
    
    session['cart'] = new_cart
    return {"message": f"已從購物車中移除 {remove_count} 個 {item_name}。"}

# 確認訂單並更新到 Google Sheets
@app.route('/confirm_order', methods=['POST'])
def confirm_order():
    cart = session.get('cart', [])
    
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

    order_df = pd.DataFrame([
        {'品項': item_name, '價格': details['價格'], '數量': details['數量']}
        for item_name, details in cart_summary.items()
    ])
    
    order_df['總價'] = order_df['價格'] * order_df['數量']
    order_df['訂單時間'] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    order_df['訂單編號'] = datetime.now().strftime('%m%d%H%M')

    data = [order_df.columns.values.tolist()] + order_df.values.tolist()
    worksheet.insert_rows(data, 1)

    session['cart'] = []  # 清空購物車
    return {"message": "訂單已確認並更新到 Google Sheets。"}

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

# 測試購物車內容的路由
@app.route("/test_display_cart", methods=['GET'])
def test_display_cart():
    return display_cart()

# LINE Bot 處理訊息事件
@handler.add(MessageEvent, message=TextMessage)
def handle_message(event):
    user_message = event.message.text.strip()
    
    # 使用 OpenAI 生成回應
    info_from_csv = data[['種類', '品項', '價格', '標籤']]
    info_str = f"Category: {info_from_csv['種類']}, Item: {info_from_csv['品項']}, Price: {info_from_csv['價格']}, Tag: {info_from_csv['標籤']}"
    response = openai.ChatCompletion.create(
        model="gpt-3.5-turbo",
        messages=[
            {"role": "system", "content": "你是一個線上咖啡廳點餐助手"},
            {"role": "system", "content": "answer the question considering the following data: " + info_str},
            {"role": "system", "content": "當客人點餐時，請務必回復品項和數量，例如：'好的，你點的是一杯美式，價格是50元 請問還需要為您添加其他的餐點或飲品嗎？' 或 '好的，您要一杯榛果拿鐵，價格為80元。請問還有其他需要幫忙的嗎？'"},
            {"role": "user", "content": user_message},
        ]
    )
     
    items = extract_item_name(response)
    
    for item_name, quantity in items:
        add_to_cart_response = add_item_to_cart(item_name, quantity)
        print(add_to_cart_response)

    line_bot_api.reply_message(
        event.reply_token,
        TextSendMessage(text=response)
    )

        # 查看購物車功能
    if '查看購物車' in user_message:
        cart_display = display_cart()
        line_bot_api.reply_message(event.reply_token, TextSendMessage(text=cart_display))


    response = response.choices[0].message.content
   

if __name__ == '__main__':
    app.run(debug=True)
