import os
import time
import requests
import json
import threading
from datetime import datetime, timezone
from flask import Flask, jsonify
import yfinance as yf
import pandas as pd
import ta

# --- FLASK (Render Health-Check) ---
app = Flask(__name__)

@app.route('/')
def home():
    return jsonify({"status": "active", "bot": "MT5PracticeScalpBot"}), 200

@app.route('/health', methods=['GET'])
def health():
    return "OK", 200

# --- AYARLAR & SANAL KASA ---
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN", "")
CHAT_ID = os.environ.get("CHAT_ID", "")
SANAL_KASA_FILE = "sanal_kasa.json"

def kasa_yukle():
    if os.path.exists(SANAL_KASA_FILE):
        try:
            with open(SANAL_KASA_FILE, "r") as f:
                return json.load(f)
        except Exception as e:
            print(f"Kasa yükleme hatası: {e}", flush=True)
    return {"bakiye": 3000.0, "aktif_poz": {}}

def kasa_kaydet(data):
    try:
        with open(SANAL_KASA_FILE, "w") as f:
            json.dump(data, f, indent=4)
    except Exception as e:
        print(f"Kasa kayıt hatası: {e}", flush=True)

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

def telegram_gonder(mesaj):
    if not TELEGRAM_TOKEN or not CHAT_ID:
        print("⚠️ Telegram Token veya Chat ID eksik!", flush=True)
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
    except Exception as e:
        print(f"Telegram mesaj hatası: {e}", flush=True)

def komutlari_ayarla():
    if not TELEGRAM_TOKEN:
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/setMyCommands"
    commands = [
        {"command": "durum", "description": "💰 Sanal Kasa & Pozisyonlar"},
        {"command": "fiyat", "description": "📊 Anlık Fiyatlar & RSI"},
        {"command": "reset", "description": "🔄 Kasayı $3000'a Sıfırla"}
    ]
    try:
        requests.post(url, json={"commands": commands}, timeout=5)
    except Exception:
        pass

def piyasa_kapali_mi():
    now_utc = datetime.now(timezone.utc)
    wd = now_utc.weekday()
    hour = now_utc.hour
    # Cuma 21:00 UTC - Pazar 21:00 UTC arası kapalı
    if wd == 5 or (wd == 4 and hour >= 21) or (wd == 6 and hour < 21):
        return True
    return False

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
                        if txt == "/durum":
                            bakiye = KASA["bakiye"]
                            pozs = KASA["aktif_poz"]
                            ozet = f"💰 *Demo Kasa:* `${bakiye:,.2f}`\n\n"
                            if not pozs:
                                ozet += "📌 *Aktif poz yok.*"
                            else:
                                for sym, p in pozs.items():
                                    ozet += f"• *{p['isim']}* ({p['yon']}) | Giriş: `{p['giris']}` | SL: `{p['sl']}` | TP: `{p['tp']}`\n"
                            telegram_gonder(ozet)
                        elif txt == "/reset":
                            KASA = {"bakiye": 3000.0, "aktif_poz": {}}
                            kasa_kaydet(KASA)
                            telegram_gonder("🔄 Kasa *$3,000.00* olarak sıfırlandı!")
        except Exception:
            time.sleep(2)
        time.sleep(1)

def piyasa_tarayici_worker():
    global KASA
    print("🚀 Piyasa tarayıcı worker aktifleşti...", flush=True)
    telegram_gonder("🎯 *MT5 Pratik Botu Başlatıldı!* Her 5 dakikada bir tarama devrede.")

    while True:
        try:
            print(f"[{datetime.now().strftime('%H:%M:%S')}] Piyasalar taranıyor...", flush=True)
            
            # 1. Açık pozisyonları TP/SL tetik kontrolü yap
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
                            kazanc = RISK_MIKTARI * 2
                            KASA["bakiye"] += kazanc
                            sonuc_msg = f"✅ *TP OLDU (LONG)* | {isim}\nKapatma: `{anlik}` | Kâr: `+${kazanc}`"
                            kapatildi = True
                        elif anlik <= sl:
                            KASA["bakiye"] -= RISK_MIKTARI
                            sonuc_msg = f"❌ *SL PATLADI (LONG)* | {isim}\nKapatma: `{anlik}` | Zarar: `-${RISK_MIKTARI}`"
                            kapatildi = True
                    elif yon == 'SELL':
                        if anlik <= tp:
                            kazanc = RISK_MIKTARI * 2
                            KASA["bakiye"] += kazanc
                            sonuc_msg = f"✅ *TP OLDU (SHORT)* | {isim}\nKapatma: `{anlik}` | Kâr: `+${kazanc}`"
                            kapatildi = True
                        elif anlik >= sl:
                            KASA["bakiye"] -= RISK_MIKTARI
                            sonuc_msg = f"❌ *SL PATLADI (SHORT)* | {isim}\nKapatma: `{anlik}` | Zarar: `-${RISK_MIKTARI}`"
                            kapatildi = True

                    if kapatildi:
                        del KASA["aktif_poz"][sembol]
                        kasa_kaydet(KASA)
                        telegram_gonder(f"{sonuc_msg}\n💰 Yeni Bakiye: `${KASA['bakiye']:,.2f}`")
                except Exception as e:
                    print(f"Poz kontrol hatası {sembol}: {e}", flush=True)

            # 2. Yeni Sinyal Taraması (Piyasa açıkken)
            if not piyasa_kapali_mi():
                for sembol, isim in PARITELER.items():
                    if sembol in KASA["aktif_poz"]:
                        continue
                    try:
                        df = yf.Ticker(sembol).history(period="3d", interval=TIMEFRAME)
                        if len(df) < 25: continue

                        df['EMA9'] = ta.trend.ema_indicator(df['Close'], window=9)
                        df['EMA21'] = ta.trend.ema_indicator(df['Close'], window=21)
                        df['RSI'] = ta.momentum.rsi(df['Close'], window=14)

                        son, onceki = df.iloc[-1], df.iloc[-2]
                        fiyat = round(float(son['Close']), 4)
                        rsi = round(float(son['RSI']), 2)

                        long_kosul = onceki['EMA9'] <= onceki['EMA21'] and son['EMA9'] > son['EMA21'] and rsi > 46
                        short_kosul = onceki['EMA9'] >= onceki['EMA21'] and son['EMA9'] < son['EMA21'] and rsi < 54

                        if long_kosul:
                            sl = round(fiyat * 0.998, 4)
                            tp = round(fiyat * 1.004, 4)
                            KASA["aktif_poz"][sembol] = {"isim": isim, "yon": "BUY", "giris": fiyat, "sl": sl, "tp": tp}
                            kasa_kaydet(KASA)
                            msg = (
                                f"⚡ *MT5 PRATİK SİNYALİ - LONG (BUY)*\n"
                                f"━━━━━━━━━━━━━━━━━━━━━━\n"
                                f"📊 Parite: `{isim}`\n"
                                f"🟢 MT5 Giriş: `{fiyat}`\n"
                                f"🛑 MT5 Stop-Loss: `{sl}`\n"
                                f"🎯 MT5 Take-Profit: `{tp}`\n"
                                f"📈 RSI: `{rsi}`"
                            )
                            telegram_gonder(msg)
                            print(f"Sinyal atıldı (LONG): {isim} @ {fiyat}", flush=True)

                        elif short_kosul:
                            sl = round(fiyat * 1.002, 4)
                            tp = round(fiyat * 0.996, 4)
                            KASA["aktif_poz"][sembol] = {"isim": isim, "yon": "SELL", "giris": fiyat, "sl": sl, "tp": tp}
                            kasa_kaydet(KASA)
                            msg = (
                                f"⚡ *MT5 PRATİK SİNYALİ - SHORT (SELL)*\n"
                                f"━━━━━━━━━━━━━━━━━━━━━━\n"
                                f"📊 Parite: `{isim}`\n"
                                f"🔴 MT5 Giriş: `{fiyat}`\n"
                                f"🛑 MT5 Stop-Loss: `{sl}`\n"
                                f"🎯 MT5 Take-Profit: `{tp}`\n"
                                f"📉 RSI: `{rsi}`"
                            )
                            telegram_gonder(msg)
                            print(f"Sinyal atıldı (SHORT): {isim} @ {fiyat}", flush=True)

                    except Exception as e:
                        print(f"Parite analiz hatası {sembol}: {e}", flush=True)
            else:
                print("Piyasa şu an kapalı (hafta sonu tatili UTC).", flush=True)

        except Exception as e:
            print(f"Genel tarayıcı hatası: {e}", flush=True)

        # 5 dakikada bir (300 saniye) tarama
        time.sleep(300)

if __name__ == "__main__":
    komutlari_ayarla()
    threading.Thread(target=telegram_dinleyici, daemon=True).start()
    threading.Thread(target=piyasa_tarayici_worker, daemon=True).start()
    port = int(os.environ.get("PORT", 10000))
    app.run(host='0.0.0.0', port=port, debug=False)
