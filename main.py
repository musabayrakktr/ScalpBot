import os, time, requests, threading
from flask import Flask, jsonify
import yfinance as yf

app = Flask(__name__)

@app.route('/')
def home():
    return jsonify({"status": "live", "mode": "safe_signal_only"}), 200

@app.route('/health', methods=['GET'])
def health():
    return "OK", 200

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN", "")
CHAT_ID = os.environ.get("CHAT_ID", "")

# Sabit mini lot / MT5 pratik için güvenli SL-TP mesafesi (yüzde bazlı net marj)
PARITELER = {
    "EURUSD=X": {"isim": "EUR/USD", "sl_yuzde": 0.0015, "tp_yuzde": 0.0030},
    "GBPUSD=X": {"isim": "GBP/USD", "sl_yuzde": 0.0015, "tp_yuzde": 0.0030},
    "GC=F": {"isim": "XAU/USD (Altın)", "sl_yuzde": 0.0020, "tp_yuzde": 0.0040},
    "USDJPY=X": {"isim": "USD/JPY", "sl_yuzde": 0.0015, "tp_yuzde": 0.0030}
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

def sinyal_tarayici():
    telegram_gonder("🎯 *Safe MT5 Sinyal Botu Aktif!* (Lot patlatmayan net seviyeler)")
    while True:
        try:
            for sembol, info in PARITELER.items():
                isim = info["isim"]
                df = yf.Ticker(sembol).history(period="2d", interval=TIMEFRAME)
                if len(df) < 2: continue
                
                son = df.iloc[-1]
                fiyat = round(float(son['Close']), 4)
                acilis = float(son['Open'])
                current_dir = "BUY" if fiyat > acilis else "SELL"
                
                if son_yon.get(sembol) != current_dir:
                    son_yon[sembol] = current_dir
                    sl_p = info["sl_yuzde"]
                    tp_p = info["tp_yuzde"]
                    
                    if current_dir == "BUY":
                        sl = round(fiyat * (1 - sl_p), 4)
                        tp = round(fiyat * (1 + tp_p), 4)
                        telegram_gonder(
                            f"🟢 *MT5 LONG* | `{isim}`\n"
                            f"⚖️ Önerilen Lot: `0.01 - 0.05`\n"
                            f"🟢 Giriş: `{fiyat}` | SL: `{sl}` | TP: `{tp}`"
                        )
                    else:
                        sl = round(fiyat * (1 + sl_p), 4)
                        tp = round(fiyat * (1 - tp_p), 4)
                        telegram_gonder(
                            f"🔴 *MT5 SHORT* | `{isim}`\n"
                            f"⚖️ Önerilen Lot: `0.01 - 0.05`\n"
                            f"🔴 Giriş: `{fiyat}` | SL: `{sl}` | TP: `{tp}`"
                        )
        except Exception:
            pass
        time.sleep(300)

if __name__ == '__main__':
    threading.Thread(target=sinyal_tarayici, daemon=True).start()
    port = int(os.environ.get('PORT', 10000))
    app.run(host='0.0.0.0', port=port)
