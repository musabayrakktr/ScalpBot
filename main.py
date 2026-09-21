import os
import time
import requests
import json
import threading
from datetime import datetime, timezone, timedelta
from flask import Flask, jsonify
import yfinance as yf
import pandas as pd
import ta

app = Flask(__name__)

@app.route('/')
def home():
    return jsonify({"status": "active", "bot": "ForexScalpBot-Debug"}), 200

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
        except Exception as e:
            print(f"Kasa yükleme hatası: {e}")
    return {"bakiye": 3000.0, "aktif_poz": {}}

def kasa_kaydet(data):
    try:
        with open(SANAL_KASA_FILE, "w") as f:
            json.dump(data, f, indent=4)
    except Exception as e:
        print(f"Kasa kayıt hatası: {e}")

KASA = kasa_yukle()

PARITELER = {
    "EURUSD=X": "EUR/USD",
    "GBPUSD=X": "GBP/USD",
    "GC=F": "XAU/USD (Altın)",
    "USDJPY=X": "USD/JPY"
}

TIMEFRAME = "15m"  
RISK_MIKTARI = 150.0  
LAST_UPDATE_ID = 0
SON_SAATLIK_BILDIRIM = 0

def telegram_gonder(mesaj):
    if not TELEGRAM_TOKEN or not CHAT_ID:
        print("Telegram token veya chat id eksik!")
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {
        "chat_id": CHAT_ID,
        "text": mesaj,
        "parse_mode": "Markdown",
        "disable_web_page_preview": True
    }
    try:
        res = requests.post(url, json=payload, timeout=5)
        print(f"Telegram yanıt code: {res.status_code}")
    except Exception as e:
        print(f"Telegram mesaj hatası: {e}")

def komutlari_ayarla():
    if not TELEGRAM_TOKEN:
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/setMyCommands"
    commands = [
        {"command": "durum", "description": "💰 Sanal Kasa & Pozisyonlar"},
        {"command": "fiyat", "description": "📊 Anlık Forex/Altın Fiyat & RSI (15M)"},
        {"command": "piyasa", "description": "⏰ Piyasa Açık/Kapalı Durumu"},
        {"command": "reset", "description": "🔄 Sanal Kasayı Sıfırla ($3000)"},
        {"command": "yardim", "description": "ℹ️ Komut Listesi"}
    ]
    try:
        requests.post(url, json={"commands": commands}, timeout=5)
    except Exception as e:
        print(f"Komut ayar hatası: {e}")

def piyasa_durumu_bilgisi():
    now_utc = datetime.now(timezone.utc)
    wd = now_utc.weekday()
    hour = now_utc.hour

    kapali = False
    durum_str = "🟢 **AÇIK (İşlem Yapılabilir)**"
    detay = "Piyasalar aktif, 15M scalping taraması çalışıyor."

    if wd == 5 or (wd == 4 and hour >= 21) or (wd == 6 and hour < 21):
        kapali = True
        durum_str = "🔴 **KAPALI (Hafta Sonu Tatili)**"
        detay = "Forex/Altın piyasaları hafta sonu kapalıdır. Pazar 21:00 UTC'de açılır."

    return durum_str, detay, kapali

def haffacilik_kapali_mi():
    _, _, kapali = piyasa_durumu_bilgisi()
    return kapali

def telegram_dinleyici():
    global LAST_UPDATE_ID, KASA
    if not TELEGRAM_TOKEN:
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/getUpdates"

    while True:
        try:
            res = requests.get(url, params={"offset": LAST_UPDATE_ID + 1, "timeout": 5}, timeout=10).json()
            if "result" in res:
                for update in res["result"]:
                    LAST_UPDATE_ID = update["update_id"]
                    if "message" in update and "text" in update["message"]:
                        msg = update["message"]
                        cid = str(msg["chat"]["id"])
                        if CHAT_ID and cid != str(CHAT_ID):
                            continue
                        txt = msg["text"].strip().lower()
                        if txt in ["/start", "/yardim", "yardım"]:
                            telegram_gonder("🤖 *Bot Aktif*")
                        elif txt == "/durum":
                            telegram_gonder(f"Bakiye: ${KASA['bakiye']:,.2f}")
        except Exception as e:
            print(f"Listener hata: {e}")
            time.sleep(2)
        time.sleep(1)

def piyasa_tarayici_worker():
    global KASA, SON_SAATLIK_BILDIRIM
    telegram_gonder("🚀 *Debug Mod Başlatıldı!* Loglar devrede.")
    print("Worker başladı...")

    while True:
        try:
            suan_epoch = time.time()
            if suan_epoch - SON_SAATLIK_BILDIRIM > 3600:
                aktif_sayi = len(KASA["aktif_poz"])
                durum, _, _ = piyasa_durumu_bilgisi()
                telegram_gonder(
                    f"🟢 *SCALPBOT 15M SAATLİK RAPOR* ⏰\n"
                    f"⚡ *Piyasa:* {durum}\n"
                    f"📌 *Aktif Poz:* `{aktif_sayi} adet`\n"
                    f"💰 *Kasa:* `${KASA['bakiye']:,.2f}`"
                )
                SON_SAATLIK_BILDIRIM = suan_epoch

            is_closed = haffacilik_kapali_mi()
            print(f"Piyasa kapalı mı?: {is_closed}")

            if not is_closed:
                for sembol, isim in PARITELER.items():
                    print(f"Taranıyor: {isim} ({sembol})...")
                    try:
                        df = yf.Ticker(sembol).history(period="2d", interval=TIMEFRAME)
                        print(f"DF uzunluk ({sembol}): {len(df)}")
                        if len(df) < 25: 
                            print(f"Yetersiz veri: {len(df)}")
                            continue
                        
                        df['EMA9'] = ta.trend.ema_indicator(df['Close'], window=9)
                        df['EMA21'] = ta.trend.ema_indicator(df['Close'], window=21)
                        df['RSI'] = ta.momentum.rsi(df['Close'], window=14)

                        son = df.iloc[-1]
                        onceki = df.iloc[-2]
                        fiyat = round(float(son['Close']), 4)
                        rsi = round(float(son['RSI']), 2)

                        long_kosul = onceki['EMA9'] <= onceki['EMA21'] and son['EMA9'] > son['EMA21'] and rsi > 46
                        short_kosul = onceki['EMA9'] >= onceki['EMA21'] and son['EMA9'] < son['EMA21'] and rsi < 54

                        print(f"{isim} Fiyat: {fiyat}, RSI: {rsi}, LongK: {long_kosul}, ShortK: {short_kosul}")

                        if sembol not in KASA["aktif_poz"]:
                            if long_kosul:
                                sl = round(fiyat * 0.998, 4)
                                tp = round(fiyat * 1.004, 4)
                                KASA["aktif_poz"][sembol] = {"isim": isim, "yon": "BUY", "giris": fiyat, "sl": sl, "tp": tp}
                                kasa_kaydet(KASA)
                                telegram_gonder(f"⚡ *SCALP SİNYALİ (LONG)* | {isim} | Giriş: {fiyat}")
                            elif short_kosul:
                                sl = round(fiyat * 1.002, 4)
                                tp = round(fiyat * 0.996, 4)
                                KASA["aktif_poz"][sembol] = {"isim": isim, "yon": "SELL", "giris": fiyat, "sl": sl, "tp": tp}
                                kasa_kaydet(KASA)
                                telegram_gonder(f"⚡ *SCALP SİNYALİ (SHORT)* | {isim} | Giriş: {fiyat}")
                    except Exception as e:
                        print(f"Parite iç hata ({sembol}): {e}")
        except Exception as e:
            print(f"Tarayıcı genel hata: {e}")

        time.sleep(60) # Debug için 60 saniyede bir dene hızlıca görelim

if __name__ == "__main__":
    komutlari_ayarla()
    threading.Thread(target=telegram_dinleyici, daemon=True).start()
    threading.Thread(target=piyasa_tarayici_worker, daemon=True).start()
    port = int(os.environ.get("PORT", 10000))
    app.run(host='0.0.0.0', port=port, debug=False)
