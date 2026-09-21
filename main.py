import os
import time
import threading
import requests
import pandas as pd
import numpy as np
import MetaTrader5 as mt5
from flask import Flask
from ta.trend import EMAIndicator
from ta.momentum import RSIIndicator

# --- FLASK (Healthcheck / Port Bind) ---
app = Flask(__name__)

@app.route("/")
def health_check():
    return "ScalpBot is alive!", 200

def run_flask():
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)

# --- AYARLAR VE ENV ---
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", os.getenv("TELEGRAM_TOKEN", "YOUR_BOT_TOKEN"))
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "YOUR_CHAT_ID")

SYMBOL = "EURUSD"
TIMEFRAME = mt5.TIMEFRAME_H1
LOT_SIZE = 0.1
RISK_REWARD_RATIO = 2.0

# --- TELEGRAM BİLDİRİM ---
def send_telegram(text: str):
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": text,
        "parse_mode": "Markdown",
        "disable_web_page_preview": True
    }
    try:
        requests.post(url, json=payload, timeout=10)
    except Exception as e:
        print(f"Telegram hatası: {e}")

# --- MT5 & STRATEJİ FONKSİYONLARI ---
def init_mt5():
    if not mt5.initialize():
        print(f"MT5 başlatılamadı, hata kodu: {mt5.last_error()}")
        return False
    return True

def get_data(symbol, timeframe, bars=300):
    rates = mt5.copy_rates_from_pos(symbol, timeframe, 0, bars)
    if rates is None or len(rates) == 0:
        return None
    df = pd.DataFrame(rates)
    df['time'] = pd.to_datetime(df['time'], unit='s')
    return df

def calculate_atr(df, period=14):
    high_low = df['high'] - df['low']
    high_close = np.abs(df['high'] - df['close'].shift())
    low_close = np.abs(df['low'] - df['close'].shift())
    ranges = pd.concat([high_low, high_close, low_close], axis=1)
    true_range = np.max(ranges, axis=1)
    return true_range.rolling(period).mean()

def analyze_market():
    df = get_data(SYMBOL, TIMEFRAME, 300)
    if df is None:
        return None

    ema50 = EMAIndicator(close=df['close'], window=50).ema_indicator()
    ema200 = EMAIndicator(close=df['close'], window=200).ema_indicator()
    rsi = RSIIndicator(close=df['close'], window=14).rsi()
    atr = calculate_atr(df, 14)

    df['ema50'] = ema50
    df['ema200'] = ema200
    df['rsi'] = rsi
    df['atr'] = atr

    last = df.iloc[-1]
    prev = df.iloc[-2]

    action = None
    if prev['ema50'] <= prev['ema200'] and last['ema50'] > last['ema200'] and 40 < last['rsi'] < 65:
        action = "BUY"
    elif prev['ema50'] >= prev['ema200'] and last['ema50'] < last['ema200'] and 35 < last['rsi'] < 60:
        action = "SELL"

    if action:
        current_price = last['close']
        current_atr = last['atr'] if not pd.isna(last['atr']) else (current_price * 0.001)
        sl_dist = current_atr * 1.5
        tp_dist = sl_dist * RISK_REWARD_RATIO

        sl = round(current_price - sl_dist, 5) if action == "BUY" else round(current_price + sl_dist, 5)
        tp = round(current_price + tp_dist, 5) if action == "BUY" else round(current_price - tp_dist, 5)

        return {
            "action": action,
            "price": round(current_price, 5),
            "sl": sl,
            "tp": tp,
            "atr": round(current_atr, 5)
        }
    return None

def execute_trade(signal):
    symbol_info = mt5.symbol_info(SYMBOL)
    if not symbol_info:
        return {"status": "ERROR", "msg": f"Symbol {SYMBOL} bulunamadı"}

    if not symbol_info.visible:
        if not mt5.symbol_select(SYMBOL, True):
            return {"status": "ERROR", "msg": f"Symbol {SYMBOL} seçilemedi"}

    order_type = mt5.ORDER_BUY if signal["action"] == "BUY" else mt5.ORDER_SELL
    price = mt5.symbol_info_tick(SYMBOL).ask if signal["action"] == "BUY" else mt5.symbol_info_tick(SYMBOL).bid

    request = {
        "action": mt5.TRADE_ACTION_DEAL,
        "symbol": SYMBOL,
        "volume": LOT_SIZE,
        "type": order_type,
        "price": price,
        "sl": signal["sl"],
        "tp": signal["tp"],
        "deviation": 20,
        "magic": 123456,
        "comment": "ScalpBot_Demo",
        "type_time": mt5.ORDER_TIME_GTC,
        "type_filling": mt5.ORDER_FILLING_IOC,
    }

    result = mt5.order_send(request)
    if result.retcode != mt5.TRADE_RETCODE_DONE:
        return {"status": "ERROR", "msg": f"Retcode: {result.retcode}"}
    return {"status": "SUCCESS", "ticket": result.order, "price": result.price}

# --- BOT ARKA PLAN DÖNGÜSÜ ---
def bot_loop():
    print("ScalpBot Arka Plan Döngüsü Başlatıldı...")
    while True:
        try:
            if init_mt5():
                signal = analyze_market()
                if signal:
                    trade_res = execute_trade(signal)
                    msg = (
                        f"🧪 *ScalpBot Demo Rapor*\n"
                        f"Parite: `{SYMBOL}`\n"
                        f"Yön: `{signal['action']}`\n"
                        f"Giriş: `{signal['price']}` | SL/TP: `{signal['sl']}`/`{signal['tp']}`\n"
                        f"Durum: `{trade_res['status']}`"
                    )
                    send_telegram(msg)
                mt5.shutdown()
        except Exception as e:
            print(f"Bot döngü hatası: {e}")
        
        # 1 saatte bir kontrol (3600 sn)
        time.sleep(3600)

if __name__ == "__main__":
    # Arka plan bot thread'i başlat
    t = threading.Thread(target=bot_loop, daemon=True)
    t.start()
    
    # Ana thread Flask portunu dinlesin (Render Healthcheck için şart)
    run_flask()
