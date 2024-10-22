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

# 初始化全局購物車字典、桌號
user_carts = {}
user_states = {}

# 將中文數字轉換為阿拉伯數字
def chinese_to_number(chinese):
    chinese_numerals = {'一': 1, '二': 2, '兩': 2, '三': 3, '四': 4, '五': 5, 
                        '六': 6, '七': 7, '八': 8, '九': 9, '十': 10}
    return chinese_numerals.get(chinese, 0)


# 提取品項名稱和數量
def extract_item_name(response):
    matches = re.findall(r'(\d+|[一二兩三四五六七八九十])\s*(杯|片|份|個)\s*([\w\s]+)', response)
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
@app.route("/payment_success/<user_id>")
def payment_success(user_id):
    try:
        # 上傳訂單資料至 Google Sheets
        order_confirmation = confirm_order(user_id)

        # 確認上傳是否成功
        if order_confirmation["message"].startswith("訂單已確認"):
            total_amount = request.args.get('total', 0)
            return f"<h1>付款成功！總金額為 {total_amount} 元</h1><p>{order_confirmation['message']}</p>"
        else:
            return f"<h1>付款失敗</h1><p>{order_confirmation['message']}</p>"

    except Exception as e:
        print(f"Error in payment_success route: {e}")
        return render_template('error.html', message="付款完成，但訂單上傳失敗。請聯繫客服。")



# 確認訂單並更新到 Google Sheets
def confirm_order(user_id):
    cart = user_carts.get(user_id, [])
    if not cart:
        return {"message": "購物車是空的，無法確認訂單。"}

    try:
        # Google 憑證驗證
        google_credentials_json = os.getenv('GOOGLE_CREDENTIALS')
        credentials_dict = json.loads(google_credentials_json)
        gc = gspread.service_account_from_dict(credentials_dict)

        # 打開 Google Sheets 並選擇工作表
        sh = gc.open_by_url('https://docs.google.com/spreadsheets/d/...')
        worksheet = sh.get_worksheet(0)

        # 整理訂單內容
        cart_summary = {}
        for item in cart:
            if item['品項'] in cart_summary:
                cart_summary[item['品項']]['數量'] += 1
            else:
                cart_summary[item['品項']] = {'價格': item['價格'], '數量': 1}

        cart_items_str = ', '.join([f"{item_name} x{details['數量']}" for item_name, details in cart_summary.items()])
        timestamp = datetime.now().strftime('%Y/%m/%d %H:%M:%S')
        table_number = user_carts[user_id].get('table_number', '未提供')  # 取得桌號

        # 準備訂單資料
        order_data = [
            [timestamp, table_number, "", "", "Line Pay", cart_items_str, sum(item['價格'] for item in cart), ""]
        ]

        # 將訂單資料寫入 Google Sheets
        worksheet.append_rows(order_data)

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

#  LINE Bot 處理訊息事件
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
            {"role": "system", "content": "當客人點的餐包含咖啡、茶或歐蕾時，請務必回復品項和數量並詢問是要冰的還是熱的，例如：'好的，你點的是一杯美式，價格是50元，請問您需要冰的還是熱的？' 或 '好的，您要一杯芙香蘋果茶，價格為90元。請問還有其他需要幫忙的嗎？'"},
            {"role": "system", "content": "當客人點的餐有兩個以上的品項時，請務必回復品項和數量並詢問是要冰的還是熱的，例如：'好的，你點的是一杯美式，價格是50元，請問您需要冰的還是熱的？另外再加一片巧克力厚片，價格是40元。請問還有其他需要幫忙的嗎？' "},
            {"role": "system", "content": "當客人說到刪除或移除字眼時，請務必回復刪除多少數量加品項，例如：'好的，已刪除一杯美式' "},
            # {"role": "system", "content": "請依據提供的檔案進行回答，若無法回答直接回覆'抱歉 ! 我無法回復這個問題，請按選單右下角聯絡客服'"}
            {"role": "system", "content": "當客人說查看購物車時，請回復 '好的' "},
            {"role": "system", "content": "answer the question considering the following data: " + info_str},
            {"role": "system", "content": "當使用者傳送'菜單'這兩個字時，請回復'您好，這是我們菜單有需要協助的請告訴我'"},
            {"role": "system", "content": "當使用者傳送'使用教學'這兩個字時，請回復'好的以上是我們的使用教學'"},
            {"role": "user", "content": user_message}
        ]
    )
    
    response_text = response.choices[0].message.content
    
    # 提取並處理購物車品項
    items = extract_item_name(response_text)
    for item_name, quantity in items:
        if '刪除' in user_message or '移除' in user_message:
            remove_from_cart_response = remove_from_cart(user_id, item_name, quantity)
            response_text += f"\n{remove_from_cart_response['message']}"
        else:
            add_to_cart_response = add_item_to_cart(user_id, item_name, quantity)
            response_text += f"\n{add_to_cart_response['message']}"

    # 如果用戶正在輸入桌號
    if user_states.get(user_id) == "entering_table_number":
        user_carts[user_id]['table_number'] = user_message  # 存入桌號
        user_states[user_id] = None  # 清除狀態
        reply_text = f"已設定桌號為：{user_message}。請再次確認訂單或繼續購物。"
        line_bot_api.reply_message(event.reply_token, TextSendMessage(text=reply_text))
        return

    # 正常對話流程
    if '確認訂單' in user_message:
        user_states[user_id] = "entering_table_number"  # 更新狀態
        line_bot_api.reply_message(
            event.reply_token,
            TextSendMessage(text="請輸入您的桌號：")
        )
        return
        
        
    # 查看購物車功能
    if '查看購物車' in user_message:
        cart_display = display_cart(user_id)
        response_text += f"\n{cart_display}"

    if '付款'  in user_message or '確認訂單' in user_message:
        # 引導至付款頁面，附帶 user_id
        payment_url = f"{request.url_root}payment/{user_id}"
        response_text = f"請點擊以下連結進行付款：\n{payment_url}"




    # 回應 LINE Bot 用戶
    line_bot_api.reply_message(
        event.reply_token,
        TextSendMessage(text=response_text)
    )


    except Exception as e:
        # 若發生錯誤，回應使用者並記錄錯誤
        print(f"Error: {e}")
        line_bot_api.reply_message(
            event.reply_token,
            TextSendMessage(text="發生錯誤，請再試一次。")
        )

if __name__ == '__main__':
    app.run(debug=True)
