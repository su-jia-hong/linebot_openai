import os
import json
import gspread
from flask import Flask, request, jsonify
from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import (
    MessageEvent,
    TextMessage,
    TextSendMessage,
    FlexSendMessage,
    PostbackEvent,
    PostbackAction,
    TemplateSendMessage,
    ButtonsTemplate,
)
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

# 初始化全局購物車和用戶狀態字典
user_carts = {}
user_states = {}

# 增加購物車的品項
def add_item_to_cart(user_id, item_name, quantity, ice_hot=None, table_number=None):
    if user_id not in user_carts:
        user_carts[user_id] = {"items": [], "table_number": table_number}
    
    cart = user_carts[user_id]["items"]
    if table_number:
        user_carts[user_id]["table_number"] = table_number

    item = data[data['品項'] == item_name]
    if not item.empty:
        for _ in range(quantity):
            cart.append({
                "品項": item.iloc[0]['品項'],
                "價格": int(item.iloc[0]['價格']),
                "冰/熱": ice_hot
            })
        user_carts[user_id]["items"] = cart
        return {"message": f"已將 {quantity} 杯 {item_name} ({ice_hot}) 加入購物車。", "cart": cart}
    else:
        return {"message": f"菜單中找不到品項 {item_name}。"}

# 顯示購物車內容
def display_cart(user_id):
    cart = user_carts.get(user_id, {}).get("items", [])
    table_number = user_carts.get(user_id, {}).get("table_number", "未設定")
    if not cart:
        return "購物車是空的"
    
    cart_summary = {}
    for item in cart:
        key = (item['品項'], item['冰/熱'])
        if key in cart_summary:
            cart_summary[key]['數量'] += 1
        else:
            cart_summary[key] = {
                '價格': item['價格'],
                '數量': 1
            }
    
    display_str = f"桌號：{table_number}\n以下是您的購物車內容：\n"
    for (item_name, ice_hot), details in cart_summary.items():
        ice_hot_str = f" ({ice_hot})" if ice_hot else ""
        display_str += f"{item_name}{ice_hot_str}: {details['數量']} 杯, 每杯 {details['價格']} 元\n"
    
    return display_str

# 移除購物車中的品項
def remove_from_cart(user_id, item_name, quantity=1):
    cart = user_carts.get(user_id, {}).get("items", [])
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
    
    user_carts[user_id]["items"] = new_cart
    return {"message": f"已從購物車中移除 {removed_items} 個 {item_name}。"}

# 確認訂單並更新到 Google Sheets
def confirm_order(user_id):
    cart = user_carts.get(user_id, {}).get("items", [])
    table_number = user_carts.get(user_id, {}).get("table_number", None)
    if not cart:
        return {"message": "購物車是空的，無法確認訂單。"}
    
    if not table_number:
        return {"message": "請先設定您的桌號。"}
    
    # 從環境變數讀取 Google Service Account 的憑證
    google_credentials_json = os.getenv('GOOGLE_CREDENTIALS')
    if not google_credentials_json:
        return {"message": "無法找到 Google 憑證，請聯繫管理員。"}
    
    credentials_dict = json.loads(google_credentials_json)
    gc = gspread.service_account_from_dict(credentials_dict)
    
    sh = gc.open_by_url('https://docs.google.com/spreadsheets/d/1YPzvvQrQurqlZw2joMaDvDse-tCY9YX-7B2fzpc9qYY/edit?usp=drive_link')
    worksheet = sh.get_worksheet(1)
    
    cart_summary = {}
    for item in cart:
        key = (item['品項'], item['冰/熱'])
        if key in cart_summary:
            cart_summary[key]['數量'] += 1
        else:
            cart_summary[key] = {
                '價格': int(item['價格']),
                '數量': 1
            }
    
    order_df = pd.DataFrame([
        {'品項': item_name, '冰/熱': ice_hot, '價格': details['價格'], '數量': details['數量']}
        for (item_name, ice_hot), details in cart_summary.items()
    ])
    
    order_df['總價'] = order_df['價格'] * order_df['數量']
    order_df['訂單時間'] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    order_df['訂單編號'] = datetime.now().strftime('%m%d%H%M')
    order_df['桌號'] = table_number
    
    data_to_insert = [order_df.columns.values.tolist()] + order_df.values.tolist()
    worksheet.insert_rows(data_to_insert, 1)
    
    # 清空購物車
    user_carts[user_id] = {"items": [], "table_number": None}
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

# 處理 LINE Bot 訊息事件
@handler.add(MessageEvent, message=TextMessage)
def handle_message(event):
    user_message = event.message.text.strip()
    user_id = event.source.user_id  # 獲取 LINE 用戶的唯一 ID
    response_text = ""
    
    # 檢查用戶是否在等待選擇冰/熱或桌號
    if user_id in user_states:
        state = user_states[user_id]
        if state["awaiting"] == "ice_hot":
            ice_hot = user_message
            item_name = state["item_name"]
            # 更新購物車中的最後一項
            if user_id in user_carts:
                cart = user_carts[user_id]["items"]
                if cart:
                    cart[-1]["冰/熱"] = ice_hot
            user_states.pop(user_id)
            response_text = f"已選擇 {item_name} 為 {ice_hot}。"
        elif state["awaiting"] == "table_number":
            table_number = user_message
            if user_id in user_carts:
                user_carts[user_id]["table_number"] = table_number
            user_states.pop(user_id)
            response_text = f"已設定桌號為 {table_number}。"
        
        # 回覆用戶
        line_bot_api.reply_message(
            event.reply_token,
            TextSendMessage(text=response_text)
        )
        return
    
    # 處理特定指令
    if user_message == "菜單":
        response_text = "您好，這是我們的菜單有需要協助的請告訴我。"
    elif user_message == "使用教學":
        response_text = "好的以上是我們的使用教學。"
    elif user_message.lower() in ["查看購物車", "查看 cart"]:
        response_text = display_cart(user_id)
    elif user_message.lower() in ["確認訂單", "送出訂單"]:
        order_confirmation = confirm_order(user_id)
        response_text = order_confirmation['message']
    else:
        # 使用 OpenAI 生成回應
        response = openai.ChatCompletion.create(
            model="gpt-3.5-turbo",
            messages=[
                {"role": "system", "content": "你是一個線上咖啡廳點餐助手"},
                {"role": "system", "content": "當客人點的餐包含咖啡、茶或歐蕾時，請務必回復品項和數量並詢問是要冰的還是熱的，例如：'好的，你點的是一杯美式，價格是50元，請問您需要冰的還是熱的？' 或 '好的，您要一杯芙香蘋果茶，價格為90元。請問還有其他需要幫忙的嗎？'"},
                {"role": "system", "content": "當客人點的餐有兩個以上的品項時，請務必回復品項和數量並詢問是要冰的還是熱的，例如：'好的，你點的是一杯美式，價格是50元，請問您需要冰的還是熱的？另外再加一片巧克力厚片，價格是40元。請問還有其他需要幫忙的嗎？' "},
                {"role": "system", "content": "當客人說到刪除或移除字眼時，請務必回復刪除多少數量加品項，例如：'好的，已刪除一杯美式' "},
                {"role": "system", "content": "當客人說查看購物車時，請回復購物車內容。"},
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
                # 將品項加入購物車，並設置等待用戶選擇冰/熱
                add_item_to_cart(user_id, item_name, quantity)
                # 設置用戶狀態為等待選擇冰/熱
                user_states[user_id] = {"awaiting": "ice_hot", "item_name": item_name}
                # 發送訊息詢問冰/熱選項
                line_bot_api.reply_message(
                    event.reply_token,
                    TextSendMessage(text=f"請問 {item_name} 是要冰的還是熱的？")
                )
                return  # 結束處理，等待用戶回覆冰/熱
    
    # 回應 LINE Bot 用戶
    line_bot_api.reply_message(
        event.reply_token,
        TextSendMessage(text=response_text)
    )

# 處理 Postback 事件（可選，用於更好的用戶體驗）
@handler.add(PostbackEvent)
def handle_postback(event):
    user_id = event.source.user_id
    data = event.postback.data.split('|')
    
    if data[0] == "ice_hot":
        ice_hot = data[1]
        item_name = data[2]
        # 更新購物車中的最後一項
        if user_id in user_carts:
            cart = user_carts[user_id]["items"]
            if cart:
                cart[-1]["冰/熱"] = ice_hot
        response_text = f"已選擇 {item_name} 為 {ice_hot}。"
        # 檢查是否需要設置桌號
        if not user_carts[user_id].get("table_number"):
            user_states[user_id] = {"awaiting": "table_number"}
            response_text += "\n請問您的桌號是？"
            line_bot_api.reply_message(
                event.reply_token,
                TextSendMessage(text=response_text)
            )
            return
        else:
            response_text += "\n還有其他需要幫忙的嗎？"
    
    elif data[0] == "set_table":
        table_number = data[1]
        if user_id in user_carts:
            user_carts[user_id]["table_number"] = table_number
        response_text = f"已設定桌號為 {table_number}。還有其他需要幫忙的嗎？"
    
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
