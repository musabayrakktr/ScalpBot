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

# --- FLASK WEB SUNUCUSU (TEMİZ RENDER & CRON MİMARİSİ) ---
app = Flask(__name__)

@app.route('/')
def home():
    return jsonify({"status": "active", "service": "ScalpBot Pro"}), 200

# Cron Job'un uyanık tutması için hafif endpoint (Spam bildirim kaldırıldı)
@app.route('/health', methods=['GET'])
def health():
    return "OK"

# --- ENVIRONMENT VARIABLES (GÜVENLİK) ---
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN", "")
CHAT_ID = os.environ.get("CHAT_ID", "")

# --- BAKIYE VE RISK AYARLARI ---
HESAP_BAKIYESI = 3000.0   # $3000 Demo
RISK_YUZDESI = 0.01      # %1 Risk

# --- KALICI TP/SL TAKİP SİSTEMİ (JSON VERİTABANI) ---
JSON_FILE = "aktif_islemler.json"

def aktif_islemleri_yukle():
    if os.path.exists(JSON_FILE):
        try:
            with open(JSON_FILE, "r") as f:
                return json.load(f)
        except:
            return {}
    return {}

def aktif_islemleri_kaydet(data):
    try:
        with open(JSON_FILE, "w") as f:
            json.dump(data, f, indent=4)
    except Exception as e:
        print(f"JSON Kayıt Hatası: {e}")

AKTIF_ISLEMLER = aktif_islemleri_yukle()

# --- PARİTELER VE AYARLAR ---
FOREX_PARITELERI = {
    "EURUSD=X": ("EUR/USD", "FX:EURUSD"),
    "GBPUSD=X": ("GBP/USD", "FX:GBPUSD"),
    "GC=F": ("XAU/USD (Altın)", "OANDA:XAUUSD"),
    "JPY=X": ("USD/JPY", "FX:USDJPY"),
    "AUDUSD=X": ("AUD/USD", "FX:AUDUSD")
}

TIMEFRAME = "5m"
SON_SINYALLER = {}
COOLDOWN_SURESI = 900  # 15 Dakika
LAST_UPDATE_ID = 0
GUNLUK_SINYAL_SAYISI = 0
RAPOR_GONDERILDI = False
ACILIS_UYARI_LONDRA = False
ACILIS_UYARI_NY = False
SON_SAATLIK_BILDIRIM = 0  # 1 Saatlik rapor takip zamanı

def telegram_komutlari_ayarla():
    if not TELEGRAM_TOKEN:
        return
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/setMyCommands"
        commands = [
            {"command": "start", "description": "🚀 Kontrol Paneli & Bilgi"},
            {"command": "fiyat", "description": "📊 Canlı Fiyatlar & RSI"},
            {"command": "durum", "description": "⚡ Bot Çalışma Durumu"},
            {"command": "test", "description": "🧪 Bağlantı Testi"},
            {"command": "tv", "description": "🌐 TradingView Grafikleri"},
            {"command": "bakiye", "description": "💰 Bakiye Güncelle (Örn: /bakiye 3000)"}
        ]
        requests.post(url, json={"commands": commands}, timeout=5)
    except Exception as e:
        print(f"Komut Set Hatası: {e}")

def telegram_mesaj_gonder(mesaj, target_chat=None):
    if not TELEGRAM_TOKEN:
        return
    cid = target_chat if target_chat else CHAT_ID
    if not cid:
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {
        "chat_id": cid,
        "text": mesaj,
        "parse_mode": "Markdown",
        "disable_web_page_preview": True
    }
    try:
        requests.post(url, json=payload, timeout=5)
    except Exception as e:
        print(f"Telegram Mesaj Hatası: {e}")

def lot_hesapla(fiyat, sl, ticker_symbol):
    global HESAP_BAKIYESI, RISK_YUZDESI
    fark = abs(fiyat - sl)
    if fark == 0:
        return 0.01

    risked_amount = HESAP_BAKIYESI * RISK_YUZDESI
    
    if "GC=F" in ticker_symbol:
        lot = risked_amount / (fark * 100)
    elif "JPY=X" in ticker_symbol:
        lot = risked_amount / ((fark / fiyat) * 100000)
    else:
        lot = risked_amount / (fark * 100000)

    lot = round(lot, 2)
    return max(lot, 0.01)

def hafta_sonu_mu():
    simdi = datetime.now(timezone.utc)
    weekday = simdi.weekday()
    if weekday == 5 or (weekday == 4 and simdi.hour >= 22) or (weekday == 6 and simdi.hour < 22):
        return True
    return False

def borsa_acilis_kontrol():
    global ACILIS_UYARI_LONDRA, ACILIS_UYARI_NY
    simdi_utc = datetime.now(timezone.utc)
    saat, dakika = simdi_utc.hour, simdi_utc.minute

    # Londra Açılış (07:00 UTC)
    if saat == 6 and 45 <= dakika <= 59:
        if not ACILIS_UYARI_LONDRA:
            telegram_mesaj_gonder("🚨 *BORSA AÇILIŞ UYARISI (LONDRA)* 🏛️\n\n15 Dakika sonra Avrupa/Londra borsası açılıyor!")
            ACILIS_UYARI_LONDRA = True
    else:
        if saat != 6:
            ACILIS_UYARI_LONDRA = False

    # New York Açılış (12:30 UTC)
    if saat == 12 and 15 <= dakika <= 29:
        if not ACILIS_UYARI_NY:
            telegram_mesaj_gonder("🚨 *BORSA AÇILIŞ UYARISI (NEW YORK)* 🗽\n\n15 Dakika sonra ABD/New York borsası açılıyor!")
            ACILIS_UYARI_NY = True
    else:
        if saat != 12:
            ACILIS_UYARI_NY = False

def tp_sl_kontrol_et(ticker_symbol, anlik_fiyat, isim):
    if ticker_symbol not in AKTIF_ISLEMLER:
        return

    islem = AKTIF_ISLEMLER[ticker_symbol]
    yon = islem['yon']
    entry = islem['entry']
    degisiklik = False

    if yon == 'BUY':
        if anlik_fiyat >= islem['tp1'] and not islem.get('tp1_hit'):
            islem['tp1_hit'] = True
            degisiklik = True
            telegram_mesaj_gonder(f"🎯 *TP1 HEDEFİ GELDİ!* 🎉\n📌 *Parite:* {isim}\n💰 *Anlık Fiyat:* `{anlik_fiyat}`\n💡 *Öneri:* Stop Loss seviyesini giriş fiyatına (`{entry}`) çekin!")
        elif anlik_fiyat >= islem['tp2'] and not islem.get('tp2_hit'):
            islem['tp2_hit'] = True
            degisiklik = True
            telegram_mesaj_gonder(f"🚀 *TP2 HEDEFİ GELDİ!* 🔥\n📌 *Parite:* {isim}\n💰 *Anlık Fiyat:* `{anlik_fiyat}`")
        elif anlik_fiyat >= islem['tp3'] and not islem.get('tp3_hit'):
            telegram_mesaj_gonder(f"🔥 *TP3 MAKSİMUM HEDEF GELDİ!* 🏆\n📌 *Parite:* {isim}\n💰 *Anlık Fiyat:* `{anlik_fiyat}`")
            del AKTIF_ISLEMLER[ticker_symbol]
            degisiklik = True
        elif anlik_fiyat <= islem['sl']:
            telegram_mesaj_gonder(f"🔴 *STOP LOSS TETİKLENDİ!* 🛑\n📌 *Parite:* {isim}\n📉 *Fiyat:* `{anlik_fiyat}`")
            del AKTIF_ISLEMLER[ticker_symbol]
            degisiklik = True

    elif yon == 'SELL':
        if anlik_fiyat <= islem['tp1'] and not islem.get('tp1_hit'):
            islem['tp1_hit'] = True
            degisiklik = True
            telegram_mesaj_gonder(f"🎯 *TP1 HEDEFİ GELDİ!* 🎉\n📌 *Parite:* {isim}\n💰 *Anlık Fiyat:* `{anlik_fiyat}`\n💡 *Öneri:* Stop Loss seviyesini giriş fiyatına (`{entry}`) çekin!")
        elif anlik_fiyat <= islem['tp2'] and not islem.get('tp2_hit'):
            islem['tp2_hit'] = True
            degisiklik = True
            telegram_mesaj_gonder(f"🚀 *TP2 HEDEFİ GELDİ!* 🔥\n📌 *Parite:* {isim}\n💰 *Anlık Fiyat:* `{anlik_fiyat}`")
        elif anlik_fiyat <= islem['tp3'] and not islem.get('tp3_hit'):
            telegram_mesaj_gonder(f"🔥 *TP3 MAKSİMUM HEDEF GELDİ!* 🏆\n📌 *Parite:* {isim}\n💰 *Anlık Fiyat:* `{anlik_fiyat}`")
            del AKTIF_ISLEMLER[ticker_symbol]
            degisiklik = True
        elif anlik_fiyat >= islem['sl']:
            telegram_mesaj_gonder(f"🔴 *STOP LOSS TETİKLENDİ!* 🛑\n📌 *Parite:* {isim}\n📈 *Fiyat:* `{anlik_fiyat}`")
            del AKTIF_ISLEMLER[ticker_symbol]
            degisiklik = True

    if degisiklik:
        aktif_islemleri_kaydet(AKTIF_ISLEMLER)

def anlik_durum_raporu():
    rapor = f"📊 *CANLI PARİTE VE RSI DURUMU*\n💰 *Kasa:* `${HESAP_BAKIYESI}`\n\n"
    for ticker, isim_tuple in FOREX_PARITELERI.items():
        isim, _ = isim_tuple
        try:
            df = yf.Ticker(ticker).history(period="1d", interval=TIMEFRAME)
            if not df.empty and len(df) >= 20:
                fiyat = round(df['Close'].iloc[-1], 4)
                rsi = round(ta.momentum.rsi(df['Close'], window=14).iloc[-1], 2)
                durum_emoji = "🟢" if rsi > 55 else ("🔴" if rsi < 45 else "🟡")
                rapor += f"{durum_emoji} *{isim}:* `{fiyat}` | 📈 RSI: `{rsi}`\n"
        except:
            rapor += f"⚠️ *{isim}:* Veri alınamadı\n"
    return rapor

def telegram_komut_dinleyici():
    """ Sadece Yetkili CHAT_ID İçin Polling Dinleyici """
    global LAST_UPDATE_ID, HESAP_BAKIYESI
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
                        incoming_chat_id = str(msg["chat"]["id"])
                        
                        if CHAT_ID and incoming_chat_id != str(CHAT_ID):
                            continue

                        text = msg["text"].strip()
                        if text in ["/start", "/menu", "menu"]:
                            telegram_mesaj_gonder(
                                f"🤖 *ScalpBot ULTIMATE Kontrol Paneli*\n\n💰 *Aktif Kasa:* `${HESAP_BAKIYESI}`\n\nKomutları alt menüden seçebilirsiniz.",
                                target_chat=incoming_chat_id
                            )
                        elif text in ["/fiyat", "/analiz"]:
                            telegram_mesaj_gonder(anlik_durum_raporu(), target_chat=incoming_chat_id)
                        elif text == "/durum":
                            telegram_mesaj_gonder(f"⚡ *Bot Durumu:* Aktif 🟢\n💰 Kasa Bakiyesi: `${HESAP_BAKIYESI}`", target_chat=incoming_chat_id)
                        elif text == "/test":
                            telegram_mesaj_gonder("✅ *Sistem Testi Başarılı!* Telegram polling ve sunucu bağlantısı sorunsuz çalışıyor 🚀", target_chat=incoming_chat_id)
                        elif text == "/tv":
                            links = "🌐 *TRADINGVIEW CANLI GRAFİK LİNKLERİ*\n\n"
                            for _, (isim, tv_sym) in FOREX_PARITELERI.items():
                                links += f"📌 [{isim} Grafiğini Aç](https://www.tradingview.com/chart/?symbol={tv_sym})\n"
                            telegram_mesaj_gonder(links, target_chat=incoming_chat_id)
                        elif text.startswith("/bakiye"):
                            try:
                                yeni_bakiye = float(text.split())
                                HESAP_BAKIYESI = yeni_bakiye
                                telegram_mesaj_gonder(f"✅ *Hesap Bakiyesi Güncellendi!*\nYeni Kasa: `${HESAP_BAKIYESI}`", target_chat=incoming_chat_id)
                            except:
                                telegram_mesaj_gonder("⚠️ Örnek kullanım: `/bakiye 3000`", target_chat=incoming_chat_id)
        except Exception as e:
            time.sleep(2)
        time.sleep(1)

def forex_parite_tara(ticker_symbol, isim_tuple):
    global GUNLUK_SINYAL_SAYISI
    isim, tv_symbol = isim_tuple
    suan = time.time()

    if ticker_symbol in AKTIF_ISLEMLER:
        try:
            ticker = yf.Ticker(ticker_symbol)
            df = ticker.history(period="1d", interval=TIMEFRAME)
            if not df.empty:
                fiyat = round(df['Close'].iloc[-1], 4)
                tp_sl_kontrol_et(ticker_symbol, fiyat, isim)
        except:
            pass
        return

    try:
        ticker = yf.Ticker(ticker_symbol)
        df = ticker.history(period="1d", interval=TIMEFRAME)

        if df.empty or len(df) < 35:
            return

        fiyat = round(df['Close'].iloc[-1], 4)

        if ticker_symbol in SON_SINYALLER and (suan - SON_SINYALLER[ticker_symbol]) < COOLDOWN_SURESI:
            return

        df['EMA_Fast'] = ta.trend.ema_indicator(df['Close'], window=9)
        df['EMA_Slow'] = ta.trend.ema_indicator(df['Close'], window=21)
        df['RSI'] = ta.momentum.rsi(df['Close'], window=14)
        macd_ind = ta.trend.MACD(df['Close'])
        df['MACD_Diff'] = macd_ind.macd_diff()

        son = df.iloc[-1]
        onceki = df.iloc[-2]
        rsi = round(son['RSI'], 2)

        al_kosulu = (
            (onceki['EMA_Fast'] <= onceki['EMA_Slow']) and 
            (son['EMA_Fast'] > son['EMA_Slow']) and 
            (rsi > 50) and 
            (son['MACD_Diff'] > 0)
        )

        sat_kosulu = (
            (onceki['EMA_Fast'] >= onceki['EMA_Slow']) and 
            (son['EMA_Fast'] < son['EMA_Slow']) and 
            (rsi < 50) and 
            (son['MACD_Diff'] < 0)
        )

        is_gold = "GC=F" in ticker_symbol
        sl_rate = 0.0030 if is_gold else 0.0015
        tv_link = f"https://www.tradingview.com/chart/?symbol={tv_symbol}"

        simdi_utc = datetime.now(timezone.utc)
        yuksek_hacim_saatleri =
        hacim_etiketi = " 🔥 *[YÜKSEK HACİM]*" if simdi_utc.hour in yuksek_hacim_saatleri else ""

        if al_kosulu:
            sl = round(fiyat * (1 - sl_rate), 4)
            fark = fiyat - sl
            tp1, tp2, tp3 = round(fiyat + fark, 4), round(fiyat + (fark * 2), 4), round(fiyat + (fark * 3), 4)
            önerilen_lot = lot_hesapla(fiyat, sl, ticker_symbol)

            mesaj = (
                f"🚨 *PRO SCALP SİNYALİ (LONG / AL)*{hacim_etiketi} 🚨\n\n"
                f"📌 *Parite:* {isim}\n"
                f"🟢 *Giriş Fiyatı:* `{fiyat}`\n"
                f"💵 *Önerilen Lot (%1 Risk):* `{önerilen_lot} Lot`\n\n"
                f"🎯 *TP1:* `{tp1}` | 🎯 *TP2:* `{tp2}` | 🎯 *TP3:* `{tp3}`\n"
                f"🛑 *Stop Loss:* `{sl}`\n\n"
                f"💡 *Öneri:* TP1'e ulaştığında Stop Loss'u giriş seviyesine (`{fiyat}`) çekin.\n"
                f"📊 *RSI:* `{rsi}` | 🔗 [TradingView Grafiği]({tv_link})"
            )
            telegram_mesaj_gonder(mesaj)

            AKTIF_ISLEMLER[ticker_symbol] = {
                'yon': 'BUY',
                'entry': fiyat,
                'tp1': tp1, 'tp2': tp2, 'tp3': tp3,
                'sl': sl,
                'tp1_hit': False, 'tp2_hit': False, 'tp3_hit': False
            }
            aktif_islemleri_kaydet(AKTIF_ISLEMLER)
            SON_SINYALLER[ticker_symbol] = suan
            GUNLUK_SINYAL_SAYISI += 1

        elif sat_kosulu:
            sl = round(fiyat * (1 + sl_rate), 4)
            fark = sl - fiyat
            tp1, tp2, tp3 = round(fiyat - fark, 4), round(fiyat - (fark * 2), 4), round(fiyat - (fark * 3), 4)
            önerilen_lot = lot_hesapla(fiyat, sl, ticker_symbol)

            mesaj = (
                f"🚨 *PRO SCALP SİNYALİ (SHORT / SAT)*{hacim_etiketi} 🚨\n\n"
                f"📌 *Parite:* {isim}\n"
                f"🔴 *Satış Fiyatı:* `{fiyat}`\n"
                f"💵 *Önerilen Lot (%1 Risk):* `{önerilen_lot} Lot`\n\n"
                f"🎯 *TP1:* `{tp1}` | 🎯 *TP2:* `{tp2}` | 🎯 *TP3:* `{tp3}`\n"
                f"🛡️ *Stop Loss:* `{sl}`\n\n"
                f"💡 *Öneri:* TP1'e ulaştığında Stop Loss'u giriş seviyesine (`{fiyat}`) çekin.\n"
                f"📊 *RSI:* `{rsi}` | 🔗 [TradingView Grafiği]({tv_link})"
            )
            telegram_mesaj_gonder(mesaj)

            AKTIF_ISLEMLER[ticker_symbol] = {
                'yon': 'SELL',
                'entry': fiyat,
                'tp1': tp1, 'tp2': tp2, 'tp3': tp3,
                'sl': sl,
                'tp1_hit': False, 'tp2_hit': False, 'tp3_hit': False
            }
            aktif_islemleri_kaydet(AKTIF_ISLEMLER)
            SON_SINYALLER[ticker_symbol] = suan
            GUNLUK_SINYAL_SAYISI += 1

    except Exception as e:
        print(f"{isim} hatası: {e}")

def background_worker():
    global GUNLUK_SINYAL_SAYISI, RAPOR_GONDERILDI, SON_SAATLIK_BILDIRIM
    telegram_komutlari_ayarla()
    telegram_mesaj_gonder("🚀 *ScalpBot Tam Güvenlikli Sürümle Başlatıldı!*\n`/test` komutunu yazarak bağlantıyı deneyebilirsiniz.")

    while True:
        try:
            simdi = datetime.now()
            suan_epoch = time.time()
            borsa_acilis_kontrol()

            # --- 1 SAATTE BİR OTOMATİK DURUM RAPORU ---
            if suan_epoch - SON_SAATLIK_BILDIRIM > 3600:
                aktif_sayi = len(AKTIF_ISLEMLER)
                saatlik_ozet = (
                    f"🌟 *SCALPBOT SAATLİK DURUM RAPORU* ⏰\n"
                    f"━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                    f"🟢 *Sistem:* Aktif ve tarama yapıyor\n"
                    f"📊 *Günlük Üretilen Sinyal:* `{GUNLUK_SINYAL_SAYISI}`\n"
                    f"📌 *Aktif Pozisyon / Takip:* `{aktif_sayi} adet`\n"
                    f"💰 *Demo Kasa:* `${HESAP_BAKIYESI}`"
                )
                telegram_mesaj_gonder(saatlik_ozet)
                SON_SAATLIK_BILDIRIM = suan_epoch

            if simdi.hour == 22 and not RAPOR_GONDERILDI:
                telegram_mesaj_gonder(f"📈 *GÜNLÜK BÖLÜM RAPORU*\n\nBugün toplam `{GUNLUK_SINYAL_SAYISI}` adet kaliteli scalp sinyali üretildi.")
                RAPOR_GONDERILDI = True
            elif simdi.hour != 22:
                RAPOR_GONDERILDI = False

            if not hafta_sonu_mu():
                for ticker, isim_tuple in FOREX_PARITELERI.items():
                    forex_parite_tara(ticker, isim_tuple)
                    time.sleep(1)
        except Exception as e:
            print(f"Tarama Hatası: {e}")

        time.sleep(30)

if __name__ == "__main__":
    threading.Thread(target=telegram_komut_dinleyici, daemon=True).start()
    threading.Thread(target=background_worker, daemon=True).start()
    port = int(os.environ.get("PORT", 10000))
    app.run(host='0.0.0.0', port=port, debug=False)
