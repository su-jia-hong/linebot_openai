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
import json

app = Flask(__name__)

# 讀取環境變數
secret_key = os.getenv('SECRET_KEY')
if not secret_key:
    raise ValueError("SECRET_KEY is not set")
app.config['SECRET_KEY'] = secret_key

# 初始化 LINE Bot
line_bot_api = LineBotApi(os.getenv('CHANNEL_ACCESS_TOKEN'))
handler = WebhookHandler(os.getenv('CHANNEL_SECRET'))

# 初始化 OpenAI API Key
openai.api_key = os.getenv('OPENAI_API_KEY')

# 讀取 CSV 資料
try:
    data = pd.read_csv('coffee2.csv', encoding='big5')
    print("CSV loaded successfully.")
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

# 初始化全局購物車字典
user_carts = {}

# 增加購物車的品項
def add_item_to_cart(user_id, item_name, quantity):
    if user_id not in user_carts:
        user_carts[user_id] = []
    
    cart = user_carts[user_id]
    item = data[data['品項'] == item_name]
    if not item.empty:
        for _ in range(quantity):
            cart.append({
                "品項": item.iloc[0]['品項'],
                "價格": int(item.iloc[0]['價格'])  # 確保價格為整數
            })
        user_carts[user_id] = cart
        return {"message": f"已將 {quantity} 杯 {item_name} 加入購物車。", "cart": cart}
    else:
        return {"message": f"菜單中找不到品項 {item_name}。"}

# 顯示購物車內容
def display_cart(user_id):
    cart = user_carts.get(user_id, [])
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
    
    display_str = "以下是您的購物車內容：\n"
    for item_name, details in cart_summary.items():
        display_str += f"{item_name}: {details['數量']} 杯, 每杯 {details['價格']} 元\n"
    
    return display_str

# 移除購物車中的品項
def remove_from_cart(user_id, item_name, quantity=1):
    cart = user_carts.get(user_id, [])
    item_count = sum(1 for item in cart if item['品項'] == item_name)
    
    if item_count == 0:
        return {"message": f"購物車中沒有找到 {item_name}。"}
    
    remove_count = min(quantity, item_count)
    new_cart = []
    removed_items = 0
    
    for item in cart:
        if item['品項'] == item_name and removed_items < remove_count:
            removed_items += 1
        else:
            new_cart.append(item)
    
    user_carts[user_id] = new_cart
    return {"message": f"已從購物車中移除 {removed_items} 個 {item_name}。"}

# 定義內部函數 confirm_order
def confirm_order(user_id):
    cart = user_carts.get(user_id, [])
    if not cart:
        return {"message": "購物車是空的，無法確認訂單。"}
    
    try:
        # 從環境變數中讀取 Service Account JSON
        service_account_info = os.getenv('GOOGLE_SERVICE_ACCOUNT_JSON')
        if not service_account_info:
            return {"message": "Google Service Account 憑證未設置。"}
        
        # 將 JSON 字串轉換為字典
        service_account_dict = json.loads(service_account_info)
        
        # 使用 gspread 的 service_account_from_dict 方法
        gc = gspread.service_account_from_dict(service_account_dict)
        sh = gc.open_by_url('https://docs.google.com/spreadsheets/d/1YPzvvQrQurqlZw2joMaDvDse-tCY9YX-7B2fzpc9qYY/edit?usp=sharing')
        worksheet = sh.get_worksheet(0)
    
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
    
        order_df = pd.DataFrame([
            {'品項': item_name, '價格': details['價格'], '數量': details['數量']}
            for item_name, details in cart_summary.items()
        ])
        
        order_df['總價'] = order_df['價格'] * order_df['數量']
        order_df['訂單時間'] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        order_df['訂單編號'] = datetime.now().strftime('%m%d%H%M')
    
        data = [order_df.columns.values.tolist()] + order_df.values.tolist()
        worksheet.insert_rows(data, 1)
    
        # 清空購物車
        user_carts[user_id] = []
        return {"message": "訂單已確認並更新到 Google Sheets。"}
    except json.JSONDecodeError:
        return {"message": "Google Service Account 憑證格式錯誤。"}
    except Exception as e:
        return {"message": f"訂單確認失敗，錯誤訊息：{str(e)}"}

# 確認訂單的 API 路由
@app.route('/confirm_order', methods=['POST'])
def confirm_order_route():
    user_id = request.json.get('user_id')
    if not user_id:
        return jsonify({"message": "缺少 user_id 參數。"}), 400
    
    order_confirmation = confirm_order(user_id)
    if order_confirmation.get('message') == "訂單已確認並更新到 Google Sheets。":
        return jsonify(order_confirmation), 200
    else:
        return jsonify(order_confirmation), 500

# LINE Bot Webhook 路由
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
    user_id = event.source.user_id  # 獲取 LINE 用戶的唯一 ID
    
    if '確認訂單' in user_message:
        # 調用內部的 confirm_order 函數
        order_confirmation = confirm_order(user_id)
        response_text = order_confirmation['message']
    else:
        # 使用 OpenAI 生成回應
        response = openai.ChatCompletion.create(
            model="gpt-3.5-turbo",
            messages=[
                {"role": "system", "content": "你是一個線上咖啡廳點餐助手"},
                {"role": "system", "content": "當客人點餐時，請務必回復品項和數量，例如：'好的，你點的是一杯美式，價格是50元 請問還需要為您添加其他的餐點或飲品嗎？' 或 '好的，您要一杯榛果拿鐵，價格為80元。請問還有其他需要幫忙的嗎？'"},
                {"role": "system", "content": "當客人說查看購物車時，請回復 '好的' "},
                {"role": "user", "content": user_message}
            ]
        )
        response_text = response.choices[0].message.content
    
        # 提取並處理購物車品項
        items = extract_item_name(user_message)
        for item_name, quantity in items:
            add_to_cart_response = add_item_to_cart(user_id, item_name, quantity)
            response_text += f"\n{add_to_cart_response['message']}"
    
        # 查看購物車功能
        if '查看購物車' in user_message:
            cart_display = display_cart(user_id)
            response_text += f"\n{cart_display}"
    
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
