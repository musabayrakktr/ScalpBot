import os
import time
import threading
import requests
import numpy as np
from flask import Flask

app = Flask(__name__)

@app.route("/")
def health_check():
    return "ScalpBot is alive!", 200

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", os.getenv("TELEGRAM_TOKEN", ""))
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")

def send_telegram(text: str):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print(f"Telegram env eksik, mesaj: {text}")
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": text,
        "parse_mode": "Markdown",
        "disable_web_page_preview": True
    }
    try:
        requests.post(url, json=payload, timeout=10)
    except Exception as e:
        print(f"Telegram hatası: {e}")

def bot_loop():
    print("ScalpBot arka plan döngüsü devrede...")
    while True:
        try:
            price = round(1.0850 + np.random.uniform(-0.0020, 0.0020), 5)
            print(f"Piyasa yoklama geçildi, anlık ref fiyat: {price}")
        except Exception as e:
            print(f"Loop err: {e}")
        time.sleep(300)

if __name__ == "__main__":
    t = threading.Thread(target=bot_loop, daemon=True)
    t.start()
    
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
