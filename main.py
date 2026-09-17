import time
import requests
import threading
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
        self.wfile.write(b"ScalpBot Pro & Telegram Menu Aktif!")

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
                rapor += f"{durum_emoji} *{isim}:* `{fiyat}` | RSI: `{rsi}`\n"
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
                    
                    # Normal Mesaj/Komut
                    if "message" in update and "text" in update["message"]:
                        text = update["message"]["text"]
                        if text in ["/start", "/menu", "menu"]:
                            telegram_mesaj_gonder(
                                "🤖 *ScalpBot PRO Kontrol Paneli*\nLütfen yapmak istediğiniz işlemi seçin:",
                                ana_menu_keyboard()
                            )
                        elif text == "/fiyat":
                            telegram_mesaj_gonder(anlik_durum_raporu(), ana_menu_keyboard())

                    # Buton Tıklaması
                    elif "callback_query" in update:
                        cb = update["callback_query"]
                        data = cb["data"]
                        
                        if data == "fiyatlar" or data == "analiz":
                            telegram_mesaj_gonder(anlik_durum_raporu(), ana_menu_keyboard())
                        elif data == "durum":
                            telegram_mesaj_gonder("🟢 *Bot Aktif:* 60sn periyotlarla tarama yapıyor.", ana_menu_keyboard())
                        elif data == "tv_links":
                            links = "🌐 *TRADINGVIEW HIZLI GRAFİK LİNKLERİ*\n\n"
                            for _, (isim, tv_sym) in FOREX_PARITELERI.items():
                                links += f"• [{isim} Grafiği](https://www.tradingview.com/chart/?symbol={tv_sym})\n"
                            telegram_mesaj_gonder(links, ana_menu_keyboard())
        except Exception as e:
            print(f"Komut Dinleme Hatası: {e}")
        time.sleep(2)

def forex_parite_tara(ticker_symbol, isim_tuple):
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
                f"🎯 *TP1:* `{tp1}` | *TP2:* `{tp2}` | *TP3:* `{tp3}`\n"
                f"🛑 *Stop Loss:* `{sl}`\n\n"
                f"📊 *RSI:* `{rsi}` | 🔗 [TradingView]({tv_link})"
            )
            telegram_mesaj_gonder(mesaj, ana_menu_keyboard())
            SON_SINYALLER[ticker_symbol] = suan

        elif sat_kosulu:
            sl = round(fiyat * (1 + sl_rate), 4)
            fark = sl - fiyat
            tp1, tp2, tp3 = round(fiyat - fark, 4), round(fiyat - (fark * 2), 4), round(fiyat - (fark * 3), 4)

            mesaj = (
                f"🚨 *PRO SCALP SİNYALİ (SHORT / SAT)* 🚨\n\n"
                f"📌 *Parite:* {isim}\n"
                f"🔴 *Satış Fiyatı:* `{fiyat}`\n\n"
                f"🎯 *TP1:* `{tp1}` | *TP2:* `{tp2}` | *TP3:* `{tp3}`\n"
                f"🛡️ *Stop Loss:* `{sl}`\n\n"
                f"📊 *RSI:* `{rsi}` | 🔗 [TradingView]({tv_link})"
            )
            telegram_mesaj_gonder(mesaj, ana_menu_keyboard())
            SON_SINYALLER[ticker_symbol] = suan

    except Exception as e:
        print(f"{isim} hatası: {e}")

# Web Sunucusu Ve Telegram Dinleyici Başlat
threading.Thread(target=run_web_server, daemon=True).start()
threading.Thread(target=telegram_komut_dinleyici, daemon=True).start()

# Başlangıç Bildirimi Ve Menü
telegram_mesaj_gonder("🔥 *ScalpBot PRO & Telegram Menüsü Aktif!*\nAşağıdaki butonları kullanarak bota komut verebilirsiniz.", ana_menu_keyboard())

# Ana Döngü
while True:
    for ticker, isim_tuple in FOREX_PARITELERI.items():
        forex_parite_tara(ticker, isim_tuple)
        time.sleep(1)
    time.sleep(60)
