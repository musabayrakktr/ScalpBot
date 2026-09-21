import os, time, requests, json, threading
from datetime import datetime, timezone
from flask import Flask, jsonify
import yfinance as yf
import pandas as pd

app = Flask(__name__)

@app.route('/')
def home():
    return jsonify({"status": "live", "bakiye": KASA.get("bakiye")}), 200

@app.route('/health', methods=['GET'])
def health():
    return "OK", 200

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN", "")
CHAT_ID = os.environ.get("CHAT_ID", "")
SANAL_KASA_FILE = "sanal_kasa.json"

def kasa_yukle():
    if os.path.exists(SANAL_KASA_FILE):
        try:
            with open(SANAL_KASA_FILE, "r") as f:
                return json.load(f)
        except Exception:
            pass
    return {"bakiye": 3000.0, "aktif_poz": {}}

def kasa_kaydet(data):
    try:
        with open(SANAL_KASA_FILE, "w") as f:
            json.dump(data, f, indent=4)
    except Exception:
        pass

KASA = kasa_yukle()

PARITELER = {
    "EURUSD=X": "EUR/USD",
    "GBPUSD=X": "GBP/USD",
    "GC=F": "XAU/USD (Altın)",
    "USDJPY=X": "USD/JPY"
}

TIMEFRAME = "15m"
RISK_MIKTARI = 150.0
SON_SAATLIK_ZAMAN = 0

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

def piyasa_tarayici():
    global KASA, SON_SAATLIK_ZAMAN
    telegram_gonder(
        f"🟢 *Scalp Bot & Saatlik Rapor Sistemi Aktif!*\n"
        f"Başlangıç Kasa: `${KASA['bakiye']:,.2f}` | Risk/Poz: `${RISK_MIKTARI}`"
    )
    
    while True:
        simdiki_zaman = time.time()
        
        # 1. SAAT BAŞI HATIRLATICI & DURUM RAPORu (Her 3600 sn / 1 saat)
        if simdiki_zaman - SON_SAATLIK_ZAMAN >= 3600:
            aktif_sayi = len(KASA["aktif_poz"])
            telegram_gonder(
                f"⏰ *SAATLİK BOT DURUM RAPORU*\n"
                f"━━━━━━━━━━━━━━━━━━━━━━\n"
                f"🟢 Bot Durumu: *AKTİF / LIVE*\n"
                f"💰 Güncel Kasa: `${KASA['bakiye']:,.2f}`\n"
                f"📌 Açık Pozisyon: `{aktif_sayi} adet`"
            )
            SON_SAATLIK_ZAMAN = simdiki_zaman

        try:
            # 2. Açık pozisyonları kontrol et (TP / SL vuruldu mu?)
            aktifler = list(KASA["aktif_poz"].items())
            for sembol, pos in aktifler:
                try:
                    df = yf.Ticker(sembol).history(period="1d", interval=TIMEFRAME)
                    if df.empty: continue
                    anlik = round(float(df['Close'].iloc[-1]), 4)
                    yon, sl, tp, isim = pos['yon'], pos['sl'], pos['tp'], pos['isim']

                    kapatildi, sonuc_msg = False, ""
                    if yon == 'BUY':
                        if anlik >= tp:
                            kazanc = RISK_MIKTARI * 2.0
                            KASA["bakiye"] += kazanc
                            sonuc_msg = f"✅ *TP OLDU (LONG)* | {isim}\nKapatma: `{anlik}` | Kâr: `+${kazanc:,.2f}`"
                            kapatildi = True
                        elif anlik <= sl:
                            KASA["bakiye"] -= RISK_MIKTARI
                            sonuc_msg = f"❌ *SL PATLADI (LONG)* | {isim}\nKapatma: `{anlik}` | Zarar: `-${RISK_MIKTARI}`"
                            kapatildi = True
                    elif yon == 'SELL':
                        if anlik <= tp:
                            kazanc = RISK_MIKTARI * 2.0
                            KASA["bakiye"] += kazanc
                            sonuc_msg = f"✅ *TP OLDU (SHORT)* | {isim}\nKapatma: `{anlik}` | Kâr: `+${kazanc:,.2f}`"
                            kapatildi = True
                        elif anlik >= sl:
                            KASA["bakiye"] -= RISK_MIKTARI
                            sonuc_msg = f"❌ *SL PATLADI (SHORT)* | {isim}\nKapatma: `[anlik]` | Zarar: `-${RISK_MIKTARI}`".replace('[anlik]', str(anlik))
                            kapatildi = True

                    if kapatildi:
                        del KASA["aktif_poz"][sembol]
                        kasa_kaydet(KASA)
                        telegram_gonder(f"{sonuc_msg}\n💰 *Güncel Kasa:* `${KASA['bakiye']:,.2f}`")
                except Exception:
                    pass

            # 3. Yeni Sinyal Taraması (Mum yönü değişimi)
            for sembol, isim in PARITELER.items():
                if sembol in KASA["aktif_poz"]:
                    continue
                try:
                    df = yf.Ticker(sembol).history(period="2d", interval=TIMEFRAME)
                    if len(df) < 2: continue
                    son = df.iloc[-1]
                    fiyat = round(float(son['Close']), 4)
                    acilis = float(son['Open'])
                    current_dir = "BUY" if fiyat > acilis else "SELL"
                    
                    if current_dir == "BUY":
                        sl = round(fiyat * 0.998, 4)
                        tp = round(fiyat * 1.004, 4)
                        KASA["aktif_poz"][sembol] = {"isim": isim, "yon": "BUY", "giris": fiyat, "sl": sl, "tp": tp}
                        kasa_kaydet(KASA)
                        telegram_gonder(
                            f"🟢 *DEMO LONG AÇILDI* | `{isim}`\n"
                            f"Giriş: `{fiyat}` | SL: `{sl}` | TP: `{tp}`\n"
                            f"💰 Kasa: `${KASA['bakiye']:,.2f}`"
                        )
                    else:
                        sl = round(fiyat * 1.002, 4)
                        tp = round(fiyat * 0.996, 4)
                        KASA["aktif_poz"][sembol] = {"isim": isim, "yon": "SELL", "giris": fiyat, "sl": sl, "tp": tp}
                        kasa_kaydet(KASA)
                        telegram_gonder(
                            f"🔴 *DEMO SHORT AÇILDI* | `{isim}`\n"
                            f"Giriş: `{fiyat}` | SL: `{sl}` | TP: `{tp}`\n"
                            f"💰 Kasa: `${KASA['bakiye']:,.2f}`"
                        )
                except Exception:
                    pass
        except Exception:
            pass

        time.sleep(300) # 5 dk döngü

if __name__ == '__main__':
    SON_SAATLIK_ZAMAN = time.time() # Bot ilk açıldığı an sayacı başlat
    threading.Thread(target=piyasa_tarayici, daemon=True).start()
    port = int(os.environ.get('PORT', 10000))
    app.run(host='0.0.0.0', port=port)
