import openai
import pandas as pd
import re
from datetime import datetime
import gspread
import os
# 讀取CSV資料
try:
    data = pd.read_csv('coffee2.csv', encoding='big5')
    print("CSV loaded successfully.")
except Exception as e:
    print(f"Failed to load CSV: {e}")
    exit()

# 設定OpenAI API金鑰

openai.api_key =  os.getenv('OPENAI_API_KEY')

# 初始化購物車
cart = []

# 將客人點餐品項與價格加入購物車中
def add_to_cart(item_name, quantity):
    global cart
    item = data[data['品項'] == item_name]
    if not item.empty:
        for _ in range(quantity):
            cart.append({
                "品項": item.iloc[0]['品項'],
            
                "價格": item.iloc[0]['價格']
            })
        return f"已將 {quantity} 杯 {item_name} 加入購物車。"
    else:
        return f"菜單中找不到品項 {item_name}。"

# 將中文數字轉換為阿拉伯數字
def chinese_to_number(chinese):
    chinese_numerals = {'一': 1, '二': 2, '三': 3, '四': 4, '五': 5, '六': 6, '七': 7, '八': 8, '九': 9, '十': 10}
    return chinese_numerals.get(chinese, 0)

# 修改提取品項名稱和數量的函數
def extract_item_name(response):
    # 匹配中文數字的數量
    matches = re.findall(r'(\d+|[一二三四五六七八九十])\s*(杯|片|份|個)\s*([\w\s]+)', response)
    
    items = []
    for match in matches:
        # 將中文數字轉換為阿拉伯數字
        quantity = int(match[0]) if match[0].isdigit() else chinese_to_number(match[0])
        item_name = match[2].strip()
        items.append((item_name, quantity))
    
    return items

# 移除購物車中的品項
def remove_from_cart(item_name, quantity=1):
    global cart
    
    # 遍歷購物車，計算目前有多少個指定品項
    item_count = sum(1 for item in cart if item['品項'] == item_name)
    
    if item_count == 0:
        return f"購物車中沒有找到 {item_name}。"
    
    # 計算實際需要移除的數量
    remove_count = min(quantity, item_count)
    
    # 初始化新購物車和已移除的項目數量
    new_cart = []
    removed_items = 0
    
    # 從購物車中移除指定數量的品項
    for item in cart:
        if item['品項'] == item_name and removed_items < remove_count:
            removed_items += 1
        else:
            new_cart.append(item)
    
    cart = new_cart
    
    if removed_items > 0:
        return f"已從購物車中移除 {removed_items} 個 {item_name}。"
    else:
        return f"購物車中沒有找到 {item_name}。"

# 顯示目前購物車
def display_cart(cart):
    if not cart:
        print("您的購物車是空的。")
    else:
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

        print("當前購物車:")
        for item_name, details in cart_summary.items():
            print(f"品項: {item_name} 價格: {details['價格']} 數量: {details['數量']}")

# 生成訂單編號
def generate_order_id():
    return datetime.now().strftime('%m%d%H%M')

# 更新現有工作表並上傳訂單
def update_existing_sheet(cart):
    # 認證並打開 Google 試算表
    gc = gspread.service_account(filename='token.json')
    sh = gc.open_by_url('https://docs.google.com/spreadsheets/d/1YPzvvQrQurqlZw2joMaDvDse-tCY9YX-7B2fzpc9qYY/edit?usp=drive_link')
    worksheet = sh.get_worksheet(0)

    # 將購物車轉換為 DataFrame
    cart_summary = {}
    for item in cart:
        if item['品項'] in cart_summary:
            cart_summary[item['品項']]['數量'] += 1
        else:
            cart_summary[item['品項']] = {
                '價格': item['價格'],
                '數量': 1
            }

    order_df = pd.DataFrame([
        {'品項': item_name, '價格': details['價格'], '數量': details['數量']}
        for item_name, details in cart_summary.items()
    ])

    # 計算總價，添加訂單編號和時間
    order_df['總價'] = order_df['價格'] * order_df['數量']
    order_df['訂單時間'] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    order_df['訂單編號'] = generate_order_id()

    # 轉換 DataFrame 為列表，並插入到試算表
    data = [order_df.columns.values.tolist()] + order_df.values.tolist()

    # 插入多行資料
    worksheet.insert_rows(data, 1)

    print("訂單已成功寫入 Google 試算表")

# 主循環
while True:
    # 顯示菜單資料
    info_from_csv = data[['種類', '品項', '價格', '標籤']]
    info_str = f"Category: {info_from_csv['種類'].tolist()}, Item: {info_from_csv['品項'].tolist()}, Price: {info_from_csv['價格'].tolist()}, Tag: {info_from_csv['標籤'].tolist()}"
    
    msg = str(input(""))  # 接收用戶輸入

    if msg.lower() == 'exit':  # 如果用戶輸入 'exit'，結束迴圈
        break
    elif msg.lower() == '查看購物車' or msg.lower() == 'check cart':  # 查看購物車內容
        display_cart(cart)
        continue
    elif '移除' in msg or '刪除' in msg or '拿掉' in msg:  # 如果用戶要求移除品項
        items = extract_item_name(msg)  # 提取品項名稱和數量
        if items:
            for item_name, quantity in items:
                remove_response = remove_from_cart(item_name, quantity)  # 從購物車中移除指定品項
                print(remove_response)
        else:
            print("無法從指令中提取要移除的品項名稱。")
        continue
    elif msg.lower() == '確認訂單':
        update_existing_sheet(cart)  # 更新現有的 Google Sheets 工作表
        print("訂單已確認並更新到 Google Sheets。")
        cart = []  # 清空購物車以開始新的訂單
        continue

    # 使用openAI 的 chatGPT 來回應
    completion = openai.ChatCompletion.create(
        model="gpt-3.5-turbo",
        messages=[
            {"role": "system", "content": "你是一個線上咖啡廳點餐助手"},
            {"role": "system", "content": "answer the question considering the following data: " + info_str},
            {"role": "system", "content": "當客人點餐時，請務必回復品項和數量，例如：'好的，你點的是一杯美式，價格是50元 請問還需要為您添加其他的餐點或飲品嗎？' 或 '好的，您要一杯榛果拿鐵，價格為80元。請問還有其他需要幫忙的嗎？'"},
            # {"role": "system", "content": "當客人點餐時，如果他點的內容包含不同品項和數量，請幫客人統整品項和數量，例如:客人說 我要三杯拿鐵跟一杯美式 請回復好的，你點的是三杯拿鐵跟一杯美式， 請問還需要為您添加其他的餐點或飲品嗎？"},
            # {"role": "system", "content": "當使用者只有傳送菜單兩個字時，不要回覆他"},
            {"role": "user", "content": msg},
        ]
    )
    
    response = completion.choices[0].message.content
    print(response)
    
    # 從回應中提取多個品項名稱和數量並加入購物車
    items = extract_item_name(response)
    if items:
        for item_name, quantity in items:  # 遍歷每個提取的品項和數量
            add_response = add_to_cart(item_name, quantity)  # 將每個品項加入購物車
            print(add_response)
    else:
        print("無法從回應中提取品項名稱。")
