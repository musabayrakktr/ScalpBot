import os
import time
import requests
import pandas as pd
import numpy as np
import MetaTrader5 as mt5
from ta.trend import EMAIndicator
from ta.momentum import RSIIndicator

# --- AYARLAR VE ENV ---
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "YOUR_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "YOUR_CHAT_ID")

SYMBOL = "EURUSD"
TIMEFRAME = mt5.TIMEFRAME_H1  # 1 Saatlik
LOT_SIZE = 0.1
RISK_REWARD_RATIO = 2.0  # TP = 2 * SL (ATR bazlı)

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

# --- MT5 BAĞLANTI & VERİ ÇEKME ---
def init_mt5():
    if not mt5.initialize():
        print(f"MT5 başlatılamadı, hata kodu: {mt5.last_error()}")
        return False
    # Demo hesapta olduğundan emin olmak için hesap bilgisi basabilirsin
    account_info = mt5.account_info()
    if account_info:
        print(f"Bağlandı! Hesap: {account_info.login} | Sunucu: {account_info.server} | Demo/Live: {not account_info.trade_allowed}")
    return True

def get_data(symbol, timeframe, bars=300):
    rates = mt5.copy_rates_from_pos(symbol, timeframe, 0, bars)
    if rates is None or len(rates) == 0:
        return None
    df = pd.DataFrame(rates)
    df['time'] = pd.to_datetime(df['time'], unit='s')
    return df

# --- ATR HESABI ---
def calculate_atr(df, period=14):
    high_low = df['high'] - df['low']
    high_close = np.abs(df['high'] - df['close'].shift())
    low_close = np.abs(df['low'] - df['close'].shift())
    ranges = pd.concat([high_low, high_close, low_close], axis=1)
    true_range = np.max(ranges, axis=1)
    return true_range.rolling(period).mean()

# --- STRATEJİ & ANALİZ ---
def analyze_market():
    df = get_data(SYMBOL, TIMEFRAME, 300)
    if df is None:
        return None

    # İndikatörler
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

    # Koşul: EMA50 yukarı yönlü EMA200'ü kesiyor + RSI aşırı alım/satım bölgesinde değil
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

        if action == "BUY":
            sl = round(current_price - sl_dist, 5)
            tp = round(current_price + tp_dist, 5)
        else:
            sl = round(current_price + sl_dist, 5)
            tp = round(current_price - tp_dist, 5)

        return {
            "action": action,
            "price": round(current_price, 5),
            "sl": sl,
            "tp": tp,
            "atr": round(current_atr, 5)
        }
    return None

# --- MT5 İŞLEM İCRASI (DEMO) ---
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
        return {"status": "ERROR", "msg": f"Retcode: {result.retcode}, desc: {result.comment}"}
    
    return {"status": "SUCCESS", "ticket": result.order, "price": result.price}

# --- ANA DÖNGÜ / ÇALIŞMA ---
def main():
    print("ScalpBot Demo Başlatılıyor...")
    if not init_mt5():
        return

    # Sinyal kontrol
    signal = analyze_market()
    if signal:
        print(f"Sinyal Yakalandı: {signal}")
        trade_res = execute_trade(signal)
        print(f"İşlem Sonucu: {trade_res}")

        # Telegram Rapor
        msg = (
            f"🧪 *ScalpBot Demo Rapor*\n"
            f"Parite: `{SYMBOL}`\n"
            f"Yön: `{signal['action']}`\n"
            f"Giriş Fiyatı: `{signal['price']}`\n"
            f"SL: `{signal['sl']}` | TP: `{signal['tp']}`\n"
            f"İşlem Durumu: `{trade_res['status']}`\n"
            f"Detay/Ticket: `{trade_res.get('ticket', trade_res.get('msg'))}`"
        )
        send_telegram(msg)
    else:
        print("Şu an strateji koşuluna uyan yeni sinyal yok, takipteyiz.")

    mt5.shutdown()

if __name__ == "__main__":
    main()
