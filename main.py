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

# --- FLASK (Render Health-Check İçin) ---
app = Flask(__name__)

@app.route('/')
def home():
    return jsonify({"status": "active", "bot": "ForexDemoBot"}), 200

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
        except:
            pass
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

TIMEFRAME = "1h"
RISK_MIKTARI = 150.0  
LAST_UPDATE_ID = 0
SON_SAATLIK_BILDIRIM = 0

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
    except Exception as e:
        print(f"Telegram mesaj hatası: {e}")

def komutlari_ayarla():
    if not TELEGRAM_TOKEN:
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/setMyCommands"
    commands = [
        {"command": "durum", "description": "💰 Sanal Kasa & Pozisyonlar"},
        {"command": "fiyat", "description": "📊 Anlık Forex/Altın Fiyat & RSI"},
        {"command": "piyasa", "description": "⏰ Piyasa Açık/Kapalı Durumu"},
        {"command": "reset", "description": "🔄 Sanal Kasayı Sıfırla ($3000)"},
        {"command": "yardim", "description": "ℹ️ Komut Listesi"}
    ]
    try:
        requests.post(url, json={"commands": commands}, timeout=5)
    except:
        pass

# Forex hafta sonu kontrolü (UTC: Cuma 21:00 - Pazar 21:00 arası kapalı)
def piyasa_durumu_bilgisi():
    now_utc = datetime.now(timezone.utc)
    wd = now_utc.weekday() # 0: Pzt, 4: Cum, 5: Cmt, 6: Paz
    hour = now_utc.hour

    # Cuma 21:00 UTC sonrası veya Cumartesi tüm gün veya Pazar 21:00 UTC öncesi kapalı
    kapali = False
    durum_str = "🟢 **AÇIK (İşlem Yapılabilir)**"
    detay = "Piyasalar aktif, sinyal taraması çalışıyor."

    if wd == 5 or (wd == 4 and hour >= 21) or (wd == 6 and hour < 21):
        kapali = True
        durum_str = "🔴 **KAPALI (Hafta Sonu Tatili)**"
        detay = "Forex/Altın piyasaları hafta sonu kapalıdır. Pazar 21:00 UTC'de açılır."

    return durum_str, detay, kapali

haffacilik_kapali_mi = lambda: piyasa_durumu_bilgisi()

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
                            telegram_gonder(
                                "🤖 *Forex/Altın Simülasyon Botu*\n\n"
                                "• `/durum` - Sanal kasa ve pozisyonlar\n"
                                "• `/fiyat` - Canlı fiyatlar ve 1h RSI\n"
                                "• `/piyasa` - Piyasa açık/kapalı durumu\n"
                                "• `/reset` - Kasayı $3000'a sıfırla"
                            )
                        elif txt == "/durum":
                            bakiye = KASA["bakiye"]
                            pozs = KASA["aktif_poz"]
                            ozet = f"💰 *Sanal Kasa Bakiyesi:* `${bakiye:,.2f}`\n\n"
                            if not pozs:
                                ozet += "📌 *Aktif pozisyon yok.*"
                            else:
                                for sym, p in pozs.items():
                                    ozet += f"• *{p['isim']}* ({p['yon']}) | Giriş: `{p['giris']}` | SL: `{p['sl']}` | TP: `{p['tp']}`\n"
                            telegram_gonder(ozet)
                        elif txt == "/fiyat":
                            rapor = "📊 *Canlı 1 Saatlik Piyasalar*\n\n"
                            for sembol, isim in PARITELER.items():
                                try:
                                    df = yf.Ticker(sembol).history(period="2d", interval=TIMEFRAME)
                                    if not df.empty:
                                        fiyat = round(df['Close'].iloc[-1], 4)
                                        rsi = round(ta.momentum.rsi(df['Close'], window=14).iloc[-1], 2)
                                        rapor += f"• *{isim}*: `{fiyat}` (RSI: `{rsi}`)\n"
                                except:
                                    rapor += f"• *{isim}*: Veri alınamadı\n"
                            telegram_gonder(rapor)
                        elif txt == "/piyasa":
                            durum, detay, _ = piyasa_durumu_bilgisi()
                            utc_zamani = datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')
                            telegram_gorn = (
                                f"⏰ *Global Piyasa Takvimi*\n"
                                f"━━━━━━━━━━━━━━━━━━━━━━\n"
                                f"Durum: {durum}\n"
                                f"ℹ️ *Bilgi:* {detay}\n"
                                f"🌐 *Sunucu Saati:* `{utc_zamani}`"
                            )
                            telegram_gonder(telegram_gorn)
                        elif txt == "/reset":
                            KASA = {"bakiye": 3000.0, "aktif_poz": {}}
                            kasa_kaydet(KASA)
                            telegram_gonder("🔄 Sanal kasa başarıyla *$3,000.00* olarak sıfırlandı!")
        except Exception as e:
            time.sleep(2)
        time.sleep(1)

def piyasa_tarayici_worker():
    global KASA, SON_SAATLIK_BILDIRIM
    telegram_gonder("🚀 *Forex/Altın 1h Simülasyon Botu Başlatıldı!* ($3000 Sanal Kasa)")

    while True:
        try:
            suan_epoch = time.time()
            if suan_epoch - SON_SAATLIK_BILDIRIM > 3600:
                aktif_sayi = len(KASA["aktif_poz"])
                durum, _, _ = piyasa_durumu_bilgisi()
                telegram_gonder(
                    f"🟢 *SCALPBOT SAATLİK DURUM RAPORU* ⏰\n"
                    f"━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                    f"⚡ *Piyasa:* {durum}\n"
                    f"📌 *Aktif Pozisyon Sayısı:* `{aktif_sayi} adet`\n"
                    f"💰 *Demo Kasa:* `${KASA['bakiye']:,.2f}`"
                )
                SON_SAATLIK_BILDIRIM = suan_epoch

            if not haffacilik_kapali_mi():
                aktifler = list(KASA["aktif_poz"].items())
                for sembol, pos in aktifler:
                    try:
                        df = yf.Ticker(sembol).history(period="1d", interval=TIMEFRAME)
                        if df.empty: continue
                        anlik = round(df['Close'].iloc[-1], 4)
                        yon = pos['yon']
                        giris = pos['giris']
                        sl = pos['sl']
                        tp = pos['tp']
                        isim = pos['isim']

                        kapatildi = False
                        sonuc_msg = ""
                        if yon == 'BUY':
                            if anlik >= tp:
                                kazanc = RISK_MIKTARI * 2  
                                KASA["bakiye"] += kazanc
                                sonuc_msg = f"✅ *TP HEDEFİ GELDİ (LONG)* | {isim}\nKapatma Fiyatı: `{anlik}` | Kâr: `+${kazanc}`"
                                kapatildi = True
                            elif anlik <= sl:
                                KASA["bakiye"] -= RISK_MIKTARI
                                sonuc_msg = f"❌ *STOP-LOSS PATLADI (LONG)* | {isim}\nKapatma Fiyatı: `{anlik}` | Zarar: `-${RISK_MIKTARI}`"
                                kapatildi = True
                        elif yon == 'SELL':
                            if anlik <= tp:
                                kazanc = RISK_MIKTARI * 2
                                KASA["bakiye"] += kazanc
                                sonuc_msg = f"✅ *TP HEDEFİ GELDİ (SHORT)* | {isim}\nKapatma Fiyatı: `{anlik}` | Kâr: `+${kazanc}`"
                                kapatildi = True
                            elif anlik >= sl:
                                KASA["bakiye"] -= RISK_MIKTARI
                                sonuc__msg = f"❌ *STOP-LOSS PATLADI (SHORT)* | {isim}\nKapatma Fiyatı: `{anlik}` | Zarar: `-${RISK_MIKTARI}`"
                                kapatildi = True

                        if kapatildi:
                            del KASA["aktif_poz"][sembol]
                            kasa_kaydet(KASA)
                            telegram_gonder(f"{sonuc_msg}\n💰 Yeni Bakiye: `${KASA['bakiye']:,.2f}`")
                    except Exception as e:
                        print(f"Pozisyon kontrol hatası ({sembol}): {e}")

                for sembol, isim in PARITELER.items():
                    if sembol in KASA["aktif_poz"]:
                        continue
                    try:
                        df = yf.Ticker(sembol).history(period="5d", interval=TIMEFRAME)
                        if len(df) < 30: continue
                        
                        df['EMA9'] = ta.trend.ema_indicator(df['Close'], window=9)
                        df['EMA21'] = ta.trend.ema_indicator(df['Close'], window=21)
                        df['RSI'] = ta.momentum.rsi(df['Close'], window=14)

                        son = df.iloc[-1]
                        onceki = df.iloc[-2]
                        fiyat = round(son['Close'], 4)
                        rsi = round(son['RSI'], 2)

                        long_kosul = onceki['EMA9'] <= onceki['EMA21'] and son['EMA9'] > son['EMA21'] and rsi > 50
                        short_kosul = onceki['EMA9'] >= onceki['EMA21'] and son['EMA9'] < son['EMA21'] and rsi < 50

                        if long_kosul:
                            sl = round(fiyat * 0.998, 4)
                            tp = round(fiyat * 1.004, 4)
                            KASA["aktif_poz"][sembol] = {"isim": isim, "yon": "BUY", "giris": fiyat, "sl": sl, "tp": tp}
                            kasa_kaydet(KASA)
                            telegram_gonder(
                                f"🧪 *SİNYAL SİMÜLASYONU (LONG)* | {isim}\n"
                                f"🟢 Giriş: `{fiyat}` | 🛑 SL: `{sl}` | 🎯 TP: `{tp}`\n"
                                f"📊 RSI: `{rsi}`"
                            )
                        elif short_kosul:
                            sl = round(fiyat * 1.002, 4)
                            tp = round(fiyat * 0.996, 4)
                            KASA["aktif_poz"][sembol] = {"isim": isim, "yon": "SELL", "giris": fiyat, "sl": sl, "tp": tp}
                            kasa_kaydet(KASA)
                            telegram_gonder(
                                f"🧪 *SİNYAL SİMÜLASYONU (SHORT)* | {isim}\n"
                                f"🔴 Giriş: `{fiyat}` | 🛑 SL: `{sl}` | 🎯 TP: `{tp}`\n"
                                f"📊 RSI: `{rsi}`"
                            )
                    except Exception as e:
                        pass
        except Exception as e:
            print(f"Tarayıcı döngü hatası: {e}")

        time.sleep(300)

if __name__ == "__main__":
    komutlari_ayarla()
    threading.Thread(target=telegram_dinleyici, daemon=True).start()
    threading.Thread(target=piyasa_tarayici_worker, daemon=True).start()
    port = int(os.environ.get("PORT", 10000))
    app.run(host='0.0.0.0', port=port, debug=False)
