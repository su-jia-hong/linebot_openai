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

# 初始化全局購物車字典和桌號字典
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
        total_amount = sum(item['價格'] for item in cart)

        # 模擬付款頁面資料
        order = {
            "amount": total_amount,
            "productName": "購物車內商品",
            "productImageUrl": "https://raw.githubusercontent.com/hong91511/images/main/S__80822274.jpg",
            "confirmUrl": f"{request.url_root}payment_success/{user_id}?total={total_amount}",
            "orderId": datetime.now().strftime('%m%d%H%M%S'),  # 動態訂單編號
            "currency": "TWD"
        }

        if request.method == 'POST':
            # 模擬付款成功後跳轉到 payment_success 頁面
            return redirect(order["confirmUrl"])

        # 將訂單資料傳遞給模板
        return render_template('payment.html', order=order)

    except Exception as e:
        print(f"Error in payment route: {e}")
        return render_template('error.html', message="發生錯誤，請稍後再試。")

# 付款成功頁面並上傳訂單至 Google Sheets
@app.route("/payment_success/<user_id>", methods=['GET', 'POST'])
def payment_success(user_id):
    try:
        if request.method == 'POST':
            table_number = request.form.get('table_number')
            user_tables[user_id] = table_number  # 儲存桌號
            
            # 上傳訂單資料至 Google Sheets
            order_confirmation = confirm_order(user_id, table_number)

            # 確認上傳是否成功
            if order_confirmation["message"].startswith("訂單已確認"):
                total_amount = request.args.get('total', 0)
                return f"<h1>付款成功！總金額為 {total_amount} 元</h1><p>{order_confirmation['message']}</p>"
            else:
                return f"<h1>付款失敗</h1><p>{order_confirmation['message']}</p>"
        else:
            return render_template('ask_table.html', user_id=user_id)

    except Exception as e:
        print(f"Error in payment_success route: {e}")
        return render_template('error.html', message="付款完成，但訂單上傳失敗。請聯繫客服。")

# 確認訂單並更新到 Google Sheets
def confirm_order(user_id, table_number):
    cart = user_carts.get(user_id, [])
    if not cart:
        return {"message": "購物車是空的，無法確認訂單。"}
    
    try:
        # 驗證 Google 憑證
        google_credentials_json = os.getenv('GOOGLE_CREDENTIALS')
        if not google_credentials_json:
            return {"message": "無法找到 Google 憑證，請聯繫管理員。"}
        
        credentials_dict = json.loads(google_credentials_json)
        gc = gspread.service_account_from_dict(credentials_dict)

        # 開啟 Google Sheets 並選擇工作表
        sh = gc.open_by_url('https://docs.google.com/spreadsheets/d/1YPzvvQrQurqlZw2joMaDvDse-tCY9YX-7B2fzpc9qYY/edit?usp=sharing')
        worksheet = sh.get_worksheet(1)

        # 整理訂單資料
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
        order_df['桌號'] = table_number  # 新增桌號欄位

        # 將資料寫入工作表
        data = [order_df.columns.values.tolist()] + order_df.values.tolist()
        worksheet.insert_rows(data, 1)

        # 清空購物車
        user_carts[user_id] = []
        return {"message": "訂單已確認並更新到 Google Sheets。"}

    except Exception as e:
        print(f"Error in confirm_order: {e}")
        return {"message": "上傳訂單失敗，請稍後再試。"}


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
    user_id = event.source.user_id

    if "查看菜單" in user_message:
        line_bot_api.reply_message(
            event.reply_token,
            TextSendMessage(text=info_str)
        )
    
    elif "加入" in user_message:
        items = extract_item_name(user_message)
        response_messages = []
        for item_name, quantity in items:
            response = add_item_to_cart(user_id, item_name, quantity)
            response_messages.append(response['message'])
        
        line_bot_api.reply_message(
            event.reply_token,
            TextSendMessage(text="\n".join(response_messages))
        )
    
    elif "查看購物車" in user_message:
        cart_contents = display_cart(user_id)
        line_bot_api.reply_message(
            event.reply_token,
            TextSendMessage(text=cart_contents)
        )
    
    elif "確認訂單" in user_message:
        # 轉至付款頁面
        line_bot_api.reply_message(
            event.reply_token,
            TextSendMessage(text="即將轉至付款頁面，請稍候...")
        )
        return redirect(url_for('payment', user_id=user_id))

# 啟動 Flask 應用程式
if __name__ == "__main__":
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 5000)))
