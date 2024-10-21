import os
import json
import gspread
from flask import Flask, request, jsonify, render_template, redirect, url_for
from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import MessageEvent, TextMessage, TextSendMessage
import openai
import pandas as pd
import re
from datetime import datetime

app = Flask(__name__)
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

# 初始化全局購物車字典
user_carts = {}
user_tables = {}

# 將中文數字轉換為阿拉伯數字
def chinese_to_number(chinese):
    chinese_numerals = {'一': 1, '二': 2, '三': 3, '四': 4, '五': 5, 
                        '六': 6, '七': 7, '八': 8, '九': 9, '十': 10}
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
def add_item_to_cart(user_id, item_name, quantity):
    if user_id not in user_carts:
        user_carts[user_id] = []
    
    cart = user_carts[user_id]
    item = data[data['品項'] == item_name]
    if not item.empty:
        for _ in range(quantity):
            cart.append({
                "品項": item.iloc[0]['品項'],
                "價格": int(item.iloc[0]['價格'])
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
            cart_summary[item_name] = {'價格': item['價格'], '數量': 1}
    
    display_str = "以下是您的購物車內容：\n"
    for item_name, details in cart_summary.items():
        display_str += f"{item_name}: {details['數量']} 杯, 每杯 {details['價格']} 元\n"
    
    return display_str

# 虛擬付款頁面
@app.route("/payment/<user_id>", methods=['GET', 'POST'])
def payment(user_id):
    try:
        # 取得使用者購物車資料
        cart = user_carts.get(user_id, [])
        
        # 計算總金額
        total_amount = sum(item['價格'] for item in cart)
        
        # 訂單資料
        order = {
            "amount": total_amount,  # 使用總金額
            "productName": "購物車內商品",
            "productImageUrl": "https://raw.githubusercontent.com/hong91511/images/main/S__80822274.jpg",
            "confirmUrl": "http://127.0.0.1:3000/payment_success",
            "orderId": "B858CB282617FB0956D960215C8E84D1CCF909C6",
            "currency": "TWD"
        }

        if request.method == 'POST':
            # 模擬付款成功後跳轉至付款成功頁面
            return redirect(url_for('payment_success', total=total_amount, user_id=user_id))

        # 將訂單資料傳遞給模板
        return render_template('payment.html', order=order)

    except Exception as e:
        print(f"Error in payment route: {e}")
        return render_template('error.html', message="發生錯誤，請稍後再試。")

# 付款成功頁面
@app.route("/payment_success")
def payment_success():
    total = request.args.get('total', 0)
    user_id = request.args.get('user_id', None)
    if user_id and user_id in user_tables:
        table_number = user_tables.pop(user_id)
        order_confirmation = confirm_order(user_id, table_number)
        return f"<h1>付款成功！總金額為 {total} 元</h1><p>{order_confirmation['message']}</p>"
    return f"<h1>付款成功！總金額為 {total} 元</h1>"

# 確認訂單並更新到 Google Sheets
def confirm_order(user_id, table_number):
    cart = user_carts.get(user_id, [])
    if not cart:
        return {"message": "購物車是空的，無法確認訂單。"}
    
    google_credentials_json = os.getenv('GOOGLE_CREDENTIALS')
    if not google_credentials_json:
        return {"message": "無法找到 Google 憑證，請聯繫管理員。"}
    
    credentials_dict = json.loads(google_credentials_json)
    gc = gspread.service_account_from_dict(credentials_dict)
    
    sh = gc.open_by_url('https://docs.google.com/spreadsheets/d/YOUR_SPREADSHEET_ID')
    worksheet = sh.get_worksheet(1)
    
    cart_summary = {}
    for item in cart:
        if item['品項'] in cart_summary:
            cart_summary[item['品項']]['數量'] += 1
        else:
            cart_summary[item['品項']] = {'價格': item['價格'], '數量': 1}
    
    order_df = pd.DataFrame([
        {'品項': item_name, '價格': details['價格'], '數量': details['數量']}
        for item_name, details in cart_summary.items()
    ])
    
    order_df['總價'] = order_df['價格'] * order_df['數量']
    order_df['訂單時間'] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    order_df['訂單編號'] = datetime.now().strftime('%m%d%H%M')
    order_df['桌號'] = table_number  # 增加桌號欄位
    
    data = [order_df.columns.values.tolist()] + order_df.values.tolist()
    worksheet.insert_rows(data, 1)
    
    user_carts[user_id] = []
    return {"message": "訂單已確認並更新到 Google Sheets。"}

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
    # 將 DataFrame 轉換為字串
    info_str = data.to_string(index=False)
    user_id = event.source.user_id  # 獲取 LINE 用戶的唯一 ID
    
    # 使用 OpenAI 生成回應
    response = openai.ChatCompletion.create(
        model="gpt-3.5-turbo",
        messages=[
            {"role": "system", "content": "你是一個線上咖啡廳點餐助手"},
            {"role": "system", "content": "當客人點的餐包含咖啡、茶或歐蕾時，請務必回復品項和數量並詢問是要熱的還是冰的。"},
            {"role": "user", "content": user_message},
            {"role": "system", "content": info_str}
        ]
    )
    
    reply = response['choices'][0]['message']['content']
    line_bot_api.reply_message(event.reply_token, TextSendMessage(text=reply))
    
    # 增加品項到購物車
    extracted_items = extract_item_name(reply)
    if extracted_items:
        for item_name, quantity in extracted_items:
            add_item_to_cart(user_id, item_name, quantity)
    
    # 當回應包含"結帳"時，進行付款處理
    if "結帳" in user_message or "付款" in user_message:
        if user_id not in user_tables:
            reply = "請輸入您的桌號以便我們確認您的訂單。"
            line_bot_api.reply_message(event.reply_token, TextSendMessage(text=reply))
            return

        # 確認桌號後處理訂單付款
        if user_id in user_tables:
            reply = "您的訂單將進行付款處理，請稍候..."
            line_bot_api.reply_message(event.reply_token, TextSendMessage(text=reply))
            payment_url = url_for('payment', user_id=user_id, _external=True)
            line_bot_api.reply_message(event.reply_token, TextSendMessage(text=f"請前往以下連結完成付款：{payment_url}"))
    
    # 當回應包含桌號時，儲存桌號並確認訂單
    table_number_match = re.search(r'桌號\s*(\d+)', user_message)
    if table_number_match:
        table_number = table_number_match.group(1)
        user_tables[user_id] = table_number
        confirm_msg = "您的桌號已確認，請進行下一步操作。"
        line_bot_api.reply_message(event.reply_token, TextSendMessage(text=confirm_msg))
        return

    # 回應購物車內容
    if "購物車" in user_message:
        cart_content = display_cart(user_id)
        line_bot_api.reply_message(event.reply_token, TextSendMessage(text=cart_content))
    
    # 清空購物車
    if "清空購物車" in user_message:
        user_carts[user_id] = []
        line_bot_api.reply_message(event.reply_token, TextSendMessage(text="購物車已清空。"))

if __name__ == "__main__":
    app.run(debug=True)
