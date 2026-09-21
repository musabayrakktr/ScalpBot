import os
import time
import requests
import threading
import yfinance as yf
from flask import Flask, jsonify

app = Flask(__name__)

@app.route('/')
def home():
    return jsonify({"status": "live", "mode": "clean_skeleton"}), 200

@app.route('/health', methods=['GET'])
def health():
    return "OK", 200

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN", "")
CHAT_ID = os.environ.get("CHAT_ID", "")

PARITELER = {
    "EURUSD=X": "EUR/USD",
    "GBPUSD=X": "GBP/USD",
    "GC=F": "XAU/USD (Altın)",
    "USDJPY=X": "USD/JPY"
}

def telegram_gonder(mesaj):
    if not TELEGRAM_TOKEN or not CHAT_ID:
        return
    url = f'https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage'
    payload = {'chat_id': CHAT_ID, 'text': mesaj, 'parse_mode': 'Markdown', 'disable_web_page_preview': True}
    try:
        requests.post(url, json=payload, timeout=5)
    except Exception:
        pass

def calisma_dongusu():
    telegram_gonder("☕ *Sakin Kafa İskelet Hazır!* Buradan yürüyoruz.")
    while True:
        try:
            for sembol, isim in PARITELER.items():
                df = yf.Ticker(sembol).history(period="1d", interval="15m")
                if not df.empty:
                    fiyat = round(float(df['Close'].iloc[-1]), 4)
                    print(f"[{isim}] Fiyat: {fiyat}", flush=True)
                    # İstediğin koşulu (örn: mum yönü/RSI) sakin kafayla buraya ekleyeceksin knk
        except Exception as e:
            print(f"Hata: {e}", flush=True)
        time.sleep(300)

if __name__ == '__main__':
    threading.Thread(target=calisma_dongusu, daemon=True).start()
    port = int(os.environ.get('PORT', 10000))
    app.run(host='0.0.0.0', port=port)
