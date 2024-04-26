from flask import Flask, request, abort

from linebot import (
    LineBotApi, WebhookHandler
)
from linebot.exceptions import (
    InvalidSignatureError
)
from linebot.models import *
from openai import OpenAI
#======python的函數庫==========
import tempfile, os
import datetime
#import openai
import json
import time
import traceback
import pandas as pd
#======python的函數庫==========

app = Flask(__name__)
static_tmp_path = os.path.join(os.path.dirname(__file__), 'static', 'tmp')
# Channel Access Token
line_bot_api = LineBotApi(os.getenv('CHANNEL_ACCESS_TOKEN'))
# Channel Secret
handler = WebhookHandler(os.getenv('CHANNEL_SECRET'))
# OPENAI API Key初始化設定
OpenAI.api_key = os.getenv('OPENAI_API_KEY')


try:
    data = pd.read_csv('coffee2.csv',encoding='big5')
    print("CSV loaded successfully.")
except Exception as e:
    print(f"Failed to load CSV: {e}")
    exit()


def GPT_response(text):
    # 接收回應
    # response = openai.Completion.create(model="gpt-3.5-turbo-instruct", prompt=text, temperature=0.5, max_tokens=50)
    # print(response)
    # # 重組回應
    # answer = response['choices'][0]['text'].replace('。','')
    # print(answer+"answer//////////////////////////")
    # return answer
    client = OpenAI()
    info_from_csv = data[['種類','品項','價格','標籤']]
    info_str = f"Category: {info_from_csv['種類']}, Item: {info_from_csv['品項']}, Price: {info_from_csv['價格']}, Tag: {info_from_csv['標籤']}"
    completion = client.chat.completions.create(
      model="ft:gpt-3.5-turbo",
        
      messages=[
        {"role": "system", "content": "你是一個線上咖啡廳點餐助手 "},
        {"role": "system", "content": "answer the question considering the following data: " + info_str},
        {"role": "user", "content": msg},
      ]
    )
    #   messages = [
    #     {
    #       "role": "system",
    #       "content": "你現在學校內部咖啡廳的店員"
    #     },
    #     {
    #       "role": "user",
    #       "content": text
    #     },
    #     {
    #       "role": "assistant",
    #       "content": "我們咖啡廳提供以下飲品和甜點：\n咖啡類：\n- 濃縮咖啡/美式咖啡 Espresso/Americano: $70\n- 卡布奇諾 Cappuccino: $80\n- 拿鐵 Latte: $90\n- 白咖啡 Flat white: $90\n- 1+1 美式咖啡+拿鐵 Americano & Latte: $100\n- 風味拿鐵（榛果/焦糖/香草/黑糖/蜂蜜/抹茶/摩卡）Flavored Latte: $100\n奶蓋茶類：\n- 奶蓋（榛果/焦糖/香草/黑糖/蜂蜜/抹茶/可可）Au Lait: $90\n可可類：\n- 可可（榛果/焦糖/香草/黑糖/蜂蜜）Cocoa: $100\n氣泡飲料類：\n- 氣泡飲料（玫瑰蜂蜜/蘋果/柚子）Sparkling Drink: $90\n茶類：\n- 茶（紅茶/綠茶/伯爵/玫瑰/蘋果/柚子）Tea: $90\n鮮奶茶類：\n- 鮮奶茶（紅茶/綠茶/伯爵）Milk Tea: $90\n厚片類：\n- 厚片（巧克力/花生/奶油/綠茶/披薩+25）Thick Toast: $40\n帕尼尼三明治類：\n- 帕尼尼三明治（蘑菇青醬/義大利火腿/泰式辣豬肉/巧克力棉花糖）Panini Sandwich: $80\n甜點類：\n- 布朗尼 Brownie: $60\n- 磅蛋糕 Pound cake: $60\n- 瑪德蓮 Madeleine: $60\n- 巴斯克起司蛋糕 Basque cheesecake: $70\n歡迎選購！"
    #     }
    #   ]
    # )
    print(completion.choices[0].message)
    print(completion.choices[0].message.content)
    answer = completion.choices[0].message.content
    return answer

# 監聽所有來自 /callback 的 Post Request
@app.route("/callback", methods=['POST'])
def callback():
    # get X-Line-Signature header value
    signature = request.headers['X-Line-Signature']
    # get request body as text
    body = request.get_data(as_text=True)
    app.logger.info("Request body: " + body)
    # handle webhook body
    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        abort(400)
    return 'OK'


# 處理訊息
@handler.add(MessageEvent, message=TextMessage)
def handle_message(event):
    msg = event.message.text
    try:
        GPT_answer = GPT_response(msg)
        print(GPT_answer)
        line_bot_api.reply_message(event.reply_token, TextSendMessage(GPT_answer))
    except:
        print(traceback.format_exc())
        line_bot_api.reply_message(event.reply_token, TextSendMessage('你所使用的OPENAI API key額度可能已經超過，請於後台Log內確認錯誤訊息'))
    # if(message == '店家資訊'):
    #     FlexMessage = json.load(open('card.json','r',encoding='utf-8'))
    #     line_bot_api.reply_message(reply_token, FlexSendMessage('店家資訊',FlexMessage))
    # else:
    #     line_bot_api.reply_message(reply_token, TextSendMessage(text=message))

@handler.add(PostbackEvent)
def handle_message(event):
    print(event.postback.data)


@handler.add(MemberJoinedEvent)
def welcome(event):
    uid = event.joined.members[0].user_id
    gid = event.source.group_id
    profile = line_bot_api.get_group_member_profile(gid, uid)
    name = profile.display_name
    message = TextSendMessage(text=f'{name}歡迎加入')
    line_bot_api.reply_message(event.reply_token, message)
    
        
import os
if __name__ == "__main__":
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
