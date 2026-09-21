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
            json.dump(data, f, indent+4 if False else 4)
    except Exception:
        pass

KASA = kasa_yukle()

PARITELER = {
    "EURUSD=X": {"isim": "EUR/USD", "kontrat": 100000, "pip_carpan": 0.0001},
    "GBPUSD=X": {"isim": "GBP/USD", "kontrat": 100000, "pip_carpan": 0.0001},
    "GC=F": {"isim": "XAU/USD (Altın)", "kontrat": 100, "pip_carpan": 0.1},
    "USDJPY=X": {"isim": "USD/JPY", "kontrat": 100000, "pip_carpan": 0.01}
}

TIMEFRAME = "15m"
RISK_YUZDESI = 0.02  # Kasanın %2'si risk edilir ($60 / $3,000)
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

def lot_hesapla(bakiye, giris, sl, sembol_info):
    try:
        risk_dolar = bakiye * RISK_YUZDESI
        fark = abs(giris - sl)
        if fark == 0:
            return 0.01
        
        kontrat = sembol_info["kontrat"]
        # Zarar edilen miktar = Lot * kontrat * fiyat_farkı
        lot = risk_dolar / (fark * kontrat)
        # Broker standartlarına göre yuvarla (en az 0.01 lot)
        lot = max(0.01, round(lot, 2))
        return lot
    except Exception:
        return 0.01

def piyasa_tarayici():
    global KASA, SON_SAATLIK_ZAMAN
    telegram_gonder(
        f"🟢 *Dinamik Lot & Scalp Bot Aktif!*\n"
        f"Başlangıç Kasa: `${KASA['bakiye']:,.2f}` | Risk Oranı: `%{RISK_YUZDESI*100}`"
    )
    
    while True:
        simdiki_zaman = time.time()
        
        # 1. SAAT BAŞI HATIRLATICI & DURUM RAPORU
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
                    yon, sl, tp, isim, lot = pos['yon'], pos['sl'], pos['tp'], pos['isim'], pos.get('lot', 0.1)

                    kapatildi, sonuc_msg = False, ""
                    risk_tutar = KASA["bakiye"] * RISK_YUZDESI # Yaklaşık baz
                    if yon == 'BUY':
                        if anlik >= tp:
                            kazanc = risk_tutar * 2.0
                            KASA["bakiye"] += kazanc
                            sonuc_msg = f"✅ *TP OLDU (LONG)* | {isim} ({lot} lot)\nKapatma: `{anlik}` | Kâr: `+${kazanc:,.2f}`"
                            kapatildi = True
                        elif anlik <= sl:
                            Zarar = risk_tutar
                            KASA["bakiye"] -= Zarar
                            sonuc_msg = f"❌ *SL PATLADI (LONG)* | {isim} ({lot} lot)\nKapatma: `{anlik}` | Zarar: `-${Zarar:,.2f}`"
                            kapatildi = True
                    elif yon == 'SELL':
                        if anlik <= tp:
                            kazanc = risk_tutar * 2.0
                            KASA["bakiye"] += kazanc
                            sonuc_msg = f"✅ *TP OLDU (SHORT)* | {isim} ({lot} lot)\nKapatma: `{anlik}` | Kâr: `+${kazanc:,.2f}`"
                            kapatildi = True
                        elif anlik >= sl:
                            Zarar = risk_tutar
                            KASA["bakiye"] -= Zarar
                            sonuc_msg = f"❌ *SL PATLADI (SHORT)* | {isim} ({lot} lot)\nKapatma: `{anlik}` | Zarar: `-${Zarar:,.2f}`"
                            kapatildi = True

                    if kapatildi:
                        del KASA["aktif_poz"][sembol]
                        kasa_kaydet(KASA)
                        telegram_gonder(f"{sonuc_msg}\n💰 *Güncel Kasa:* `${KASA['bakiye']:,.2f}`")
                except Exception:
                    pass

            # 3. Yeni Sinyal Taraması + Dinamik Lot Hesaplama
            for sembol, s_info in PARITELER.items():
                isim = s_info["isim"]
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
                        lot_boyutu = lot_hesapla(KASA["bakiye"], fiyat, sl, s_info)
                        KASA["aktif_poz"][sembol] = {"isim": isim, "yon": "BUY", "giris": fiyat, "sl": sl, "tp": tp, "lot": lot_boyutu}
                        kasa_kaydet(KASA)
                        telegram_gonder(
                            f"🟢 *DEMO LONG AÇILDI* | `{isim}`\n"
                            f"⚖️ Hesaplanan Lot: `{lot_boyutu}`\n"
                            f"Giriş: `{fiyat}` | SL: `{sl}` | TP: `{tp}`\n"
                            f"💰 Kasa: `${KASA['bakiye']:,.2f}`"
                        )
                    else:
                        sl = round(fiyat * 1.002, 4)
                        tp = round(fiyat * 0.996, 4)
                        lot_boyutu = lot_hesapla(KASA["bakiye"], fiyat, sl, s_info)
                        KASA["aktif_poz"][sembol] = {"isim": isim, "yon": "SELL", "giris": fiyat, "sl": sl, "tp": tp, "lot": lot_boyutu}
                        kasa_kaydet(KASA)
                        telegram_gonder(
                            f"🔴 *DEMO SHORT AÇILDI* | `{isim}`\n"
                            f"⚖️ Hesaplanan Lot: `{lot_boyutu}`\n"
                            f"Giriş: `{fiyat}` | SL: `{sl}` | TP: `{tp}`\n"
                            f"💰 Kasa: `${KASA['bakiye']:,.2f}`"
                        )
                except Exception:
                    pass
        except Exception:
            pass

        time.sleep(300)

if __name__ == '__main__':
    SON_SAATLİK_ZAMAN = time.time()
    threading.Thread(target=piyasa_tarayici, daemon=True).start()
    port = int(os.environ.get('PORT', 10000))
    app.run(host='0.0.0.0', port=port)
