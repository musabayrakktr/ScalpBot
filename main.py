import time
import requests
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
import yfinance as yf
import pandas as pd
import ta

# --- RENDER WEB SUNUCUSU (PORT HEALTH CHECK) ---
class SimpleHTTPRequestHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header('Content-type', 'text/html')
        self.end_headers()
        self.wfile.write(b"ScalpBot Pro Aktif!")

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
SON_SINYALLER = {}  # Cooldown takibi
COOLDOWN_SURESI = 900  # Aynı parite için 15 dakika bekleme (saniye)

def telegram_mesaj_gonder(mesaj):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {"chat_id": CHAT_ID, "text": mesaj, "parse_mode": "Markdown", "disable_web_page_preview": True}
    try:
        requests.post(url, json=payload)
    except Exception as e:
        print(f"Telegram Hatası: {e}")

def forex_parite_tara(ticker_symbol, isim_tuple):
    isim, tv_symbol = isim_tuple
    suan = time.time()

    # Cooldown Kontrolü
    if ticker_symbol in SON_SINYALLER and (suan - SON_SINYALLER[ticker_symbol]) < COOLDOWN_SURESI:
        return

    try:
        ticker = yf.Ticker(ticker_symbol)
        df = ticker.history(period="1d", interval=TIMEFRAME)

        if df.empty or len(df) < 35:
            return

        # 1. İndikatörler: EMA & RSI
        df['EMA_Fast'] = ta.trend.ema_indicator(df['Close'], window=9)
        df['EMA_Slow'] = ta.trend.ema_indicator(df['Close'], window=21)
        df['RSI'] = ta.momentum.rsi(df['Close'], window=14)

        # 2. İndikatör: MACD
        macd_ind = ta.trend.MACD(df['Close'])
        df['MACD_Diff'] = macd_ind.macd_diff()

        # 3. İndikatör: Hacim
        df['Vol_SMA'] = df['Volume'].rolling(window=20).mean()

        son = df.iloc[-1]
        onceki = df.iloc[-2]

        fiyat = round(son['Close'], 4)
        rsi = round(son['RSI'], 2)

        # Hacim Onayı (Altın hariç Forex'te hacim sıfır gelirse es geçilir)
        hacim_ok = True
        if son['Vol_SMA'] > 0:
            hacim_ok = son['Volume'] >= (son['Vol_SMA'] * 0.8)

        # Kesişim & MACD Şartları
        al_kosulu = (
            (onceki['EMA_Fast'] <= onceki['EMA_Slow']) and 
            (son['EMA_Fast'] > son['EMA_Slow']) and 
            (rsi > 50) and 
            (son['MACD_Diff'] > 0) and 
            hacim_ok
        )

        sat_kosulu = (
            (onceki['EMA_Fast'] >= onceki['EMA_Slow']) and 
            (son['EMA_Fast'] < son['EMA_Slow']) and 
            (rsi < 50) and 
            (son['MACD_Diff'] < 0) and 
            hacim_ok
        )

        is_gold = "GC=F" in ticker_symbol
        sl_rate = 0.0030 if is_gold else 0.0015
        tv_link = f"https://www.tradingview.com/chart/?symbol={tv_symbol}"

        if al_kosulu:
            sl = round(fiyat * (1 - sl_rate), 4)
            fark = fiyat - sl
            tp1 = round(fiyat + fark, 4)
            tp2 = round(fiyat + (fark * 2), 4)
            tp3 = round(fiyat + (fark * 3), 4)

            mesaj = (
                f"🚨 *PRO SCALP SİNYALİ (LONG / AL)* 🚨\n\n"
                f"📌 *Parite:* {isim}\n"
                f"🟢 *Giriş Fiyatı:* `{fiyat}`\n\n"
                f"🎯 *TP1 (1:1):* `{tp1}`\n"
                f"🎯 *TP2 (1:2):* `{tp2}`\n"
                f"🎯 *TP3 (1:3):* `{tp3}`\n"
                f"🛑 *Stop Loss:* `{sl}`\n\n"
                f"📊 *RSI:* `{rsi}` | *MACD:* `Pozitif`\n"
                f"🔗 [TradingView'de Aç]({tv_link})"
            )
            telegram_mesaj_gonder(mesaj)
            SON_SINYALLER[ticker_symbol] = suan

        elif sat_kosulu:
            sl = round(fiyat * (1 + sl_rate), 4)
            fark = sl - fiyat
            tp1 = round(fiyat - fark, 4)
            tp2 = round(fiyat - (fark * 2), 4)
            tp3 = round(fiyat - (fark * 3), 4)

            mesaj = (
                f"🚨 *PRO SCALP SİNYALİ (SHORT / SAT)* 🚨\n\n"
                f"📌 *Parite:* {isim}\n"
                f"🔴 *Giriş Fiyatı:* `{fiyat}`\n\n"
                f"🎯 *TP1 (1:1):* `{tp1}`\n"
                f"🎯 *TP2 (1:2):* `{tp2}`\n"
                f"🎯 *TP3 (1:3):* `{tp3}`\n"
                f"🛡️ *Stop Loss:* `{sl}`\n\n"
                f"📊 *RSI:* `{rsi}` | *MACD:* `Negatif`\n"
                f"🔗 [TradingView'de Aç]({tv_link})"
            )
            telegram_mesaj_gonder(mesaj)
            SON_SINYALLER[ticker_symbol] = suan

    except Exception as e:
        print(f"{isim} taranırken hata: {e}")

# Web sunucusunu başlat
threading.Thread(target=run_web_server, daemon=True).start()

# Başlangıç Bildirimi
telegram_mesaj_gonder("🔥 *ScalpBot PRO Aktif!* MACD + Hacim Filtreli & Kademeli TP Modu Başlatıldı.")

# Ana Döngü
while True:
    for ticker, isim_tuple in FOREX_PARITELERI.items():
        forex_parite_tara(ticker, isim_tuple)
        time.sleep(1)
    time.sleep(60)
