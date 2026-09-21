import os
import time
import threading
import requests
import numpy as np
import pandas as pd
import yfinance as yf
from flask import Flask

app = Flask(__name__)

@app.route("/")
def health_check():
    return "ScalpBot is alive!", 200

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", os.getenv("TELEGRAM_TOKEN", ""))
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")

SYMBOLS = {
    "EURUSD": "EURUSD=X",
    "XAUUSD": "GC=F"
}

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

def fetch_live_price(symbol_key):
    ticker = SYMBOLS.get(symbol_key, "EURUSD=X")
    data = yf.Ticker(ticker).history(period="1d", interval="1h")
    if data is not None and not data.empty:
        return round(float(data['Close'].iloc[-1]), 5)
    return None

def bot_loop():
    print("ScalpBot canli veri döngüsü devrede...")
    while True:
        try:
            eur_price = fetch_live_price("EURUSD")
            gold_price = fetch_live_price("XAUUSD")
            print(f"Canlı Fiyatlar -> EURUSD: {eur_price} | XAUUSD: {gold_price}")
            
            # Örnek sinyal/kontrol mantığı buraya bağlanır
            # if condition: send_telegram(...)
            
        except Exception as e:
            print(f"Loop err: {e}")
        time.sleep(300)

if __name__ == "__main__":
    t = threading.Thread(target=bot_loop, daemon=True)
    t.start()
    
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
