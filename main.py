import time
import requests
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
import yfinance as yf
import pandas as pd
import ta

# --- RENDER WEB SUNUCUSU DİNLEYİCİSİ (PORT HATASINI ÇÖZER) ---
class SimpleHTTPRequestHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header('Content-type', 'text/html')
        self.end_headers()
        self.wfile.write(b"Bot Aktif ve Calisiyor!")

def run_web_server():
    server_address = ('', 10000)
    httpd = HTTPServer(server_address, SimpleHTTPRequestHandler)
    print("Web sunucusu başlatıldı...")
    httpd.serve_forever()

# --- BİLDİRİM VE PARİTE AYARLARI ---
TELEGRAM_TOKEN = "8814586618:AAFrQ2kCbjXf8XuWaJ2NK-gCXkL2_8ik81c"
CHAT_ID = "8982017587"

FOREX_PARITELERI = {
    "EURUSD=X": "EUR/USD",
    "GBPUSD=X": "GBP/USD",
    "GC=F": "XAU/USD (Altın)",
    "JPY=X": "USD/JPY",
    "AUDUSD=X": "AUD/USD"
}

TIMEFRAME = "5m"

def telegram_mesaj_gonder(mesaj):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {"chat_id": CHAT_ID, "text": mesaj, "parse_mode": "Markdown"}
    try:
        requests.post(url, json=payload)
    except Exception as e:
        print(f"Telegram Hatasi: {e}")

def forex_parite_tara(ticker_symbol, isim):
    try:
        ticker = yf.Ticker(ticker_symbol)
        df = ticker.history(period="1d", interval=TIMEFRAME)

        if df.empty or len(df) < 30:
            return

        df['EMA_Fast'] = ta.trend.ema_indicator(df['Close'], window=9)
        df['EMA_Slow'] = ta.trend.ema_indicator(df['Close'], window=21)
        df['RSI'] = ta.momentum.rsi(df['Close'], window=14)

        son = df.iloc[-1]
        onceki = df.iloc[-2]

        fiyat = round(son['Close'], 4)
        rsi = round(son['RSI'], 2)

        al_kosulu = (onceki['EMA_Fast'] <= onceki['EMA_Slow']) and (son['EMA_Fast'] > son['EMA_Slow']) and (rsi > 50)
        sat_kosulu = (onceki['EMA_Fast'] >= onceki['EMA_Slow']) and (son['EMA_Fast'] < son['EMA_Slow']) and (rsi < 50)

        is_gold = "GC=F" in ticker_symbol
        sl_rate = 0.0030 if is_gold else 0.0015
        tp_rate = 0.0060 if is_gold else 0.0030

        if al_kosulu:
            stop_loss = round(fiyat * (1 - sl_rate), 4)
            take_profit = round(fiyat * (1 + tp_rate), 4)

            mesaj = (
                f"💱 *FOREX SCALP SİNYALİ (AL)* 💱\n\n"
                f"📌 *Parite:* {isim}\n"
                f"🟢 *Alış Fiyatı:* {fiyat}\n"
                f"📈 *Target TP:* {take_profit}\n"
                f"🔴 *Stop Loss:* {stop_loss}\n"
                f"🔍 *RSI:* {rsi}"
            )
            telegram_mesaj_gonder(mesaj)

        elif sat_kosulu:
            stop_loss = round(fiyat * (1 + sl_rate), 4)
            take_profit = round(fiyat * (1 - tp_rate), 4)

            mesaj = (
                f"💱 *FOREX SCALP SİNYALİ (SAT / SHORT)* 💱\n\n"
                f"📌 *Parite:* {isim}\n"
                f"🔴 *Satış Fiyatı:* {fiyat}\n"
                f"📉 *Target TP:* {take_profit}\n"
                f"🛡️ *Stop Loss:* {stop_loss}\n"
                f"🔍 *RSI:* {rsi}"
            )
            telegram_mesaj_gonder(mesaj)

    except Exception as e:
        print(f"{isim} taranırken hata: {e}")

# Web sunucusunu arka planda çalıştır
threading.Thread(target=run_web_server, daemon=True).start()

# Başlangıç bildirimi
telegram_mesaj_gonder("🚀 *Forex Scalp Botu Başarıyla Çalıştırıldı!* Pariteler taranıyor...")

# Ana Döngü
while True:
    print("Forex piyasası taranıyor...")
    for ticker, isim in FOREX_PARITELERI.items():
        forex_parite_tara(ticker, isim)
        time.sleep(2)
    time.sleep(120)
