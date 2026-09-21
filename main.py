import os
import time
import requests
import pandas as pd
import yfinance as yf
from datetime import datetime

# --- AYARLAR ---
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "SENIN_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "SENIN_CHAT_ID")

# 4 Parite (Scalp İçin 15M Dönüyoruz)
SYMBOLS = ["EURUSD=X", "GBPUSD=X", "USDJPY=X", "GC=F"]  # XAUUSD için GC=F veya broker kodun
INTERVAL = "15m"  # 1H yerine 15M scalping hızı
CHECK_INTERVAL_SECONDS = 900  # Her 15 dakikada bir kontrol (900 saniye)

# Demo Bakiye Takip
demo_balance = 3000.0
active_positions = 0

def send_telegram_message(text):
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {"chat_id": TELEGRAM_CHAT_ID, "text": text, "parse_mode": "Markdown"}
    try:
        response = requests.post(url, json=payload, timeout=10)
        return response.json().get("ok", False)
    except Exception as e:
        print(f"Telegram hata: {e}")
        return False

def calculate_rsi(series, period=14):
    delta = series.diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=period).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
    rs = gain / loss
    return 100 - (100 / (1 + rs))

def check_market():
    global active_positions
    msg_list = []
    
    for symbol in SYMBOLS:
        try:
            # 15m veri çek
            df = yf.download(symbol, period="2d", interval=INTERVAL, progress=False)
            if df.empty or len(df.Close) < 25:
                continue
                
            close_prices = df['Close'].squeeze()
            
            # EMA 9 ve EMA 21
            ema9 = close_prices.ewm(span=9, adjust=False).mean()
            ema21 = close_prices.ewm(span=21, adjust=False).mean()
            rsi14 = calculate_rsi(close_prices, period=14)
            
            curr_close = float(close_prices.iloc[-1])
            prev_close = float(close_prices.iloc[-2])
            curr_ema9 = float(ema9.iloc[-1])
            prev_ema9 = float(ema9.iloc[-2])
            curr_ema21 = float(ema21.iloc[-1])
            prev_ema21 = float(ema21.iloc[-1]) # ya da önceki
            curr_rsi = float(rsi14.iloc[-1])
            
            clean_name = symbol.replace("=X", "").replace("GC=F", "XAUUSD")
            
            # Scalp Kesişim Şartı: EMA9 yukarı kesiyor EMA21 + RSI momentum (> 48)
            buy_condition = (prev_ema9 <= prev_ema21) and (curr_ema9 > curr_ema21) and (curr_rsi > 48)
            # Scalp Satış Şartı: EMA9 aşağı kesiyor EMA21 + RSI momentum (< 52)
            sell_condition = (prev_ema9 >= prev_ema21) and (curr_ema9 < curr_ema21) and (curr_rsi < 52)
            
            # Pip / Nokta bazlı basit SL/TP hesapla
            if buy_condition:
                sl = round(curr_close * 0.998, 4)
                tp = round(curr_close * 1.004, 4)
                signal_text = f"⚡ *SCALP SİNYALİ - BUY*\n" \
                              f"📊 Parite: `{clean_name}` (15M)\n" \
                              f"🟢 Giriş: `{curr_close}`\n" \
                              f"🛑 Stop-Loss: `{sl}`\n" \
                              f"🎯 Take-Profit: `{tp}`\n" \
                              f"📈 RSI: `{curr_rsi:.1f}`"
                send_telegram_message(signal_text)
                
            elif sell_condition:
                sl = round(curr_close * 1.002, 4)
                tp = round(curr_close * 0.996, 4)
                signal_text = f"⚡ *SCALP SİNYALİ - SELL*\n" \
                              f"📊 Parite: `{clean_name}` (15M)\n" \
                              f"🔴 Giriş: `{curr_close}`\n" \
                              f"🛑 Stop-Loss: `{sl}`\n" \
                              f"🎯 Take-Profit: `{tp}`\n" \
                              f"📉 RSI: `{curr_rsi:.1f}`"
                send_telegram_message(signal_text)
                
        except Exception as e:
            print(f"Hata ({symbol}): {e}")

# Döngü
if __name__ == "__main__":
    send_telegram_message("🚀 *SCALPBOT 15M MODU AKTİF*\n⚡ Hızlı tarama devrede.")
    while True:
        check_market()
        time.sleep(CHECK_INTERVAL_SECONDS)
