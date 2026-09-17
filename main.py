import time
import requests
import yfinance as yf
import pandas as pd
import pandas_ta as ta

# --- BİLDİRİM VE PARİTE AYARLARI ---
TELEGRAM_TOKEN = "8814586618:AAFrQ2kCbjXf8XuWaJ2NK-gCXkL2_8ik81c"
CHAT_ID = "8982017587"

# Hacmi ve kazanç potansiyeli en yüksek Forex Listesi
FOREX_PARITELERI = {
    "EURUSD=X": "EUR/USD",
    "GBPUSD=X": "GBP/USD",
    "GC=F": "XAU/USD (Altın)",
    "JPY=X": "USD/JPY",
    "AUDUSD=X": "AUD/USD"
}

TIMEFRAME = "5m"  # 5 Dakikalık Mumlar (Scalp)

def telegram_mesaj_gonder(mesaj):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {"chat_id": CHAT_ID, "text": mesaj, "parse_mode": "Markdown"}
    try:
        requests.post(url, json=payload)
    except Exception as e:
        print(f"Telegram Hatasi: {e}")

def forex_parite_tara(ticker_symbol, isim):
    try:
        # Canlı veriyi çek (Son 1 günün 5 dakikalık mumları)
        ticker = yf.Ticker(ticker_symbol)
        df = ticker.history(period="1d", interval=TIMEFRAME)

        if df.empty or len(df) < 30:
            return

        # İndikatör Hesaplamaları
        df['EMA_Fast'] = ta.ema(df['Close'], length=9)
        df['EMA_Slow'] = ta.ema(df['Close'], length=21)
        df['RSI'] = ta.rsi(df['Close'], length=14)

        son = df.iloc[-1]
        onceki = df.iloc[-2]

        fiyat = round(son['Close'], 4)
        rsi = round(son['RSI'], 2)

        # Hacim Filtresi
        hacim_ort = df['Volume'].rolling(20).mean().iloc[-1]
        hacim_onayi = True if hacim_ort == 0 else (son['Volume'] >= hacim_ort)

        # AL / SAT KOSULLARI
        al_kosulu = (onceki['EMA_Fast'] <= onceki['EMA_Slow']) and (son['EMA_Fast'] > son['EMA_Slow']) and (rsi > 50) and hacim_onayi
        sat_kosulu = (onceki['EMA_Fast'] >= onceki['EMA_Slow']) and (son['EMA_Fast'] < son['EMA_Slow']) and (rsi < 50) and hacim_onayi

        # Altın (XAU/USD) için esnek risk marjı, dövizler için standart marj
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
            print(f"{isim} için AL sinyali gönderildi.")

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
            print(f"{isim} için SAT sinyali gönderildi.")

    except Exception as e:
        print(f"{isim} taranırken hata: {e}")

# İlk açılışta bota bağlandığını doğrulamak için mesaj gönderir
telegram_mesaj_gonder("🚀 *Forex Scalp Botu Başarıyla Çalıştırıldı!* Pariteler taranıyor...")

# 2 dakikada bir tarama döngüsü
while True:
    print("Forex piyasası taranıyor...")
    for ticker, isim in FOREX_PARITELERI.items():
        forex_parite_tara(ticker, isim)
        time.sleep(2)
    time.sleep(120)
