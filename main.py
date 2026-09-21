import os, time, requests, threading
from datetime import datetime, timezone
from flask import Flask, jsonify
import yfinance as yf

app = Flask(__name__)

@app.route('/')
def home():
    return jsonify({"status": "active", "bot": "RawActionBot"}), 200

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

TIMEFRAME = "15m"
son_yon = {}

def telegram_gonder(mesaj):
    if not TELEGRAM_TOKEN or not CHAT_ID:
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {
        "chat_id": CHAT_ID,
        "text": mesaj,
        "parse_mode": "Markdown",
        "disable_web_page_preview": True
    }
    try:
        requests.post(url, json=payload, timeout=5)
    except Exception:
        pass

def tarayici_worker():
    telegram_gonder("🔥 *Agresif Mum Yön Botu Devrede!* Renk değiştiği an yapıştırır.")
    while True:
        for sembol, isim in PARITELER.items():
            try:
                df = yf.Ticker(sembol).history(period="2d", interval=TIMEFRAME)
                if len(df) < 2: continue
                
                son = df.iloc[-1]
                fiyat = round(float(son['Close']), 4)
                acilis = float(son['Open'])
                
                # Yeşil mum = BUY, Kırmızı mum = SELL
                current_dir = "BUY" if fiyat > acilis else "SELL"
                
                # Yön önceki duruma göre değiştiyse patlat
                if son_yon.get(sembol) != current_dir:
                    son_yon[sembol] = current_dir
                    if current_dir == "BUY":
                        sl = round(fiyat * 0.998, 4)
                        tp = round(fiyat * 1.004, 4)
                        telegram_gonder(
                            f"🟢 *MUM DÖNDÜ (BUY)* | `{isim}` (15M)\n"
                            f"Giriş: `{fiyat}` | SL: `{sl}` | TP: `{tp}`"
                        )
                    else:
                        sl = round(fiyat * 1.002, 4)
                        tp = round(fiyat * 0.996, 4)
                        telegram_gonder(
                            f"🔴 *MUM DÖNDÜ (SELL)* | `{isim}` (15M)\n"
                            f"Giriş: `{fiyat}` | SL: `{sl}` | TP: `{tp}`"
                        )
            except Exception:
                pass
        time.sleep(300) # 5 dk tarama

if __name__ == "__main__":
    threading.Thread(target=tarayici_worker, daemon=True).start()
    port = int(os.environ.get("PORT", 10000))
    app.run(host='0.0.0.0', port=port, debug=False)
