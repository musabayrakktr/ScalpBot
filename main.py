import time
import requests
import threading
from datetime import datetime, timezone
from http.server import HTTPServer, BaseHTTPRequestHandler
import yfinance as yf
import pandas as pd
import ta

# --- RENDER WEB SUNUCUSU ---
class SimpleHTTPRequestHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header('Content-type', 'text/html')
        self.end_headers()
        self.wfile.write(b"ScalpBot Pro Ultimate Aktif!")

def run_web_server():
    server_address = ('', 10000)
    httpd = HTTPServer(server_address, SimpleHTTPRequestHandler)
    httpd.serve_forever()

# --- AYARLAR VE PARİTELER ---
TELEGRAM_TOKEN = "8814586618:AAFrQ2kCbjXf8XuWaJ2NK-gCXkL2_8ik81c"
CHAT_ID = "8982017587"

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

def telegram_komutlari_ayarla():
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/setMyCommands"
        commands = [
            {"command": "start", "description": "🚀 Kontrol Paneli & Menü"},
            {"command": "fiyat", "description": "📊 Canlı Fiyatlar & RSI"},
            {"command": "durum", "description": "⚡ Bot Çalışma Durumu"},
            {"command": "tv", "description": "🌐 TradingView Grafikleri"}
        ]
        requests.post(url, json={"commands": commands})
    except Exception as e:
        print(f"Komut Set Hatası: {e}")

def telegram_mesaj_gonder(mesaj, keyboard=None):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {
        "chat_id": CHAT_ID,
        "text": mesaj,
        "parse_mode": "Markdown",
        "disable_web_page_preview": True
    }
    if keyboard:
        payload["reply_markup"] = keyboard
    try:
        requests.post(url, json=payload)
    except Exception as e:
        print(f"Telegram Mesaj Hatası: {e}")

def ana_menu_keyboard():
    return {
        "inline_keyboard": [
            [
                {"text": "📊 Canlı Fiyatlar", "callback_data": "fiyatlar"},
                {"text": "🔍 Trend Analizi", "callback_data": "analiz"}
            ],
            [
                {"text": "⚡ Bot Durumu", "callback_data": "durum"},
                {"text": "🌐 TradingView Linkleri", "callback_data": "tv_links"}
            ]
        ]
    }

def haber_filtresi_aktif_mi():
    simdi = datetime.now(timezone.utc)
    dakika = simdi.minute
    if (50 <= dakika <= 59) or (0 <= dakika <= 10) or (20 <= dakika <= 40):
        return False
    return True

def hafta_sonu_mu():
    simdi = datetime.now(timezone.utc)
    weekday = simdi.weekday()
    if weekday == 5 or (weekday == 4 and simdi.hour >= 22) or (weekday == 6 and simdi.hour < 22):
        return True
    return False

def anlik_durum_raporu():
    rapor = "📊 *CANLI PARİTE VE RSI DURUMU*\n\n"
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
    global LAST_UPDATE_ID
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/getUpdates"
    
    while True:
        try:
            res = requests.get(url, params={"offset": LAST_UPDATE_ID + 1, "timeout": 10}).json()
            if "result" in res:
                for update in res["result"]:
                    LAST_UPDATE_ID = update["update_id"]
                    
                    if "message" in update and "text" in update["message"]:
                        text = update["message"]["text"]
                        if text in ["/start", "/menu", "menu"]:
                            telegram_mesaj_gonder(
                                "🤖 *ScalpBot ULTIMATE Kontrol Paneli*\n\nİstediğiniz işlemi aşağıdaki emojili menüden seçebilirsiniz:",
                                ana_menu_keyboard()
                            )
                        elif text in ["/fiyat", "/analiz"]:
                            telegram_mesaj_gonder(anlik_durum_raporu(), ana_menu_keyboard())
                        elif text == "/durum":
                            telegram_mesaj_gonder("⚡ *Bot Durumu:* Aktif 🟢\n⏱️ Tarama: 60sn\n🛡️ Haber & Hafta Sonu Filtreleri: Açık", ana_menu_keyboard())
                        elif text == "/tv":
                            links = "🌐 *TRADINGVIEW CANLI GRAFİK LİNKLERİ*\n\n"
                            for _, (isim, tv_sym) in FOREX_PARITELERI.items():
                                links += f"📌 [{isim} Grafiğini Aç](https://www.tradingview.com/chart/?symbol={tv_sym})\n"
                            telegram_mesaj_gonder(links, ana_menu_keyboard())

                    elif "callback_query" in update:
                        data = update["callback_query"]["data"]
                        if data in ["fiyatlar", "analiz"]:
                            telegram_mesaj_gonder(anlik_durum_raporu(), ana_menu_keyboard())
                        elif data == "durum":
                            telegram_mesaj_gonder("⚡ *Bot Durumu:* Aktif 🟢\n⏱️ 60 saniyelik periyotlarla taranıyor.", ana_menu_keyboard())
                        elif data == "tv_links":
                            links = "🌐 *TRADINGVIEW CANLI GRAFİK LİNKLERİ*\n\n"
                            for _, (isim, tv_sym) in FOREX_PARITELERI.items():
                                links += f"📌 [{isim} Grafiğini Aç](https://www.tradingview.com/chart/?symbol={tv_sym})\n"
                            telegram_mesaj_gonder(links, ana_menu_keyboard())
        except Exception as e:
            print(f"Komut Dinleme Hatası: {e}")
        time.sleep(2)

def forex_parite_tara(ticker_symbol, isim_tuple):
    global GUNLUK_SINYAL_SAYISI
    isim, tv_symbol = isim_tuple
    suan = time.time()

    if ticker_symbol in SON_SINYALLER and (suan - SON_SINYALLER[ticker_symbol]) < COOLDOWN_SURESI:
        return

    try:
        ticker = yf.Ticker(ticker_symbol)
        df = ticker.history(period="1d", interval=TIMEFRAME)

        if df.empty or len(df) < 35:
            return

        df['EMA_Fast'] = ta.trend.ema_indicator(df['Close'], window=9)
        df['EMA_Slow'] = ta.trend.ema_indicator(df['Close'], window=21)
        df['RSI'] = ta.momentum.rsi(df['Close'], window=14)
        macd_ind = ta.trend.MACD(df['Close'])
        df['MACD_Diff'] = macd_ind.macd_diff()

        son = df.iloc[-1]
        onceki = df.iloc[-2]

        fiyat = round(son['Close'], 4)
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

        if al_kosulu:
            sl = round(fiyat * (1 - sl_rate), 4)
            fark = fiyat - sl
            tp1, tp2, tp3 = round(fiyat + fark, 4), round(fiyat + (fark * 2), 4), round(fiyat + (fark * 3), 4)

            mesaj = (
                f"🚨 *PRO SCALP SİNYALİ (LONG / AL)* 🚨\n\n"
                f"📌 *Parite:* {isim}\n"
                f"🟢 *Giriş Fiyatı:* `{fiyat}`\n\n"
                f"🎯 *TP1:* `{tp1}` | 🎯 *TP2:* `{tp2}` | 🎯 *TP3:* `{tp3}`\n"
                f"🛑 *Stop Loss:* `{sl}`\n\n"
                f"💡 *Öneri:* TP1'e ulaştığında Stop Loss'u giriş seviyesine (`{fiyat}`) çekin.\n"
                f"📊 *RSI:* `{rsi}` | 🔗 [TradingView Grafiği]({tv_link})"
            )
            telegram_mesaj_gonder(mesaj, ana_menu_keyboard())
            SON_SINYALLER[ticker_symbol] = suan
            GUNLUK_SINYAL_SAYISI += 1

        elif sat_kosulu:
            sl = round(fiyat * (1 + sl_rate), 4)
            fark = sl - fiyat
            tp1, tp2, tp3 = round(fiyat - fark, 4), round(fiyat - (fark * 2), 4), round(fiyat - (fark * 3), 4)

            mesaj = (
                f"🚨 *PRO SCALP SİNYALİ (SHORT / SAT)* 🚨\n\n"
                f"📌 *Parite:* {isim}\n"
                f"🔴 *Satış Fiyatı:* `{fiyat}`\n\n"
                f"🎯 *TP1:* `{tp1}` | 🎯 *TP2:* `{tp2}` | 🎯 *TP3:* `{tp3}`\n"
                f"🛡️ *Stop Loss:* `{sl}`\n\n"
                f"💡 *Öneri:* TP1'e ulaştığında Stop Loss'u giriş seviyesine (`{fiyat}`) çekin.\n"
                f"📊 *RSI:* `{rsi}` | 🔗 [TradingView Grafiği]({tv_link})"
            )
            telegram_mesaj_gonder(mesaj, ana_menu_keyboard())
            SON_SINYALLER[ticker_symbol] = suan
            GUNLUK_SINYAL_SAYISI += 1

    except Exception as e:
        print(f"{isim} hatası: {e}")

# Servisleri Başlat
threading.Thread(target=run_web_server, daemon=True).start()
threading.Thread(target=telegram_komut_dinleyici, daemon=True).start()

# Menü Komutlarını Otomatik Kaydet
telegram_komutlari_ayarla()

# Başlangıç Bildirimi
telegram_mesaj_gonder("🚀 *ScalpBot PRO Ultimate Aktif!*\nSol alt köşedeki emojili menüden komutları kullanabilirsiniz.", ana_menu_keyboard())

# Ana Döngü
while True:
    simdi = datetime.now()
    
    if simdi.hour == 22 and not RAPOR_GONDERILDI:
        telegram_mesaj_gonder(f"📈 *GÜNLÜK BÖLÜM RAPORU*\n\nBugün toplam `{GUNLUK_SINYAL_SAYISI}` adet kaliteli scalp sinyali üretildi.", ana_menu_keyboard())
        RAPOR_GONDERILDI = True
    elif simdi.hour != 22:
        RAPOR_GONDERILDI = False

    if hafta_sonu_mu():
        time.sleep(300)
        continue

    if not haber_filtresi_aktif_mi():
        time.sleep(60)
        continue

    for ticker, isim_tuple in FOREX_PARITELERI.items():
        forex_parite_tara(ticker, isim_tuple)
        time.sleep(1)
    time.sleep(60)
