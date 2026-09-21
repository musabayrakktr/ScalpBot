from datetime import datetime, timezone, timedelta
import os
import threading
import time
from flask import Flask, request
import numpy as np
import pandas as pd
import requests
import yfinance as yf

app = Flask(__name__)


# --- HEALTHCHECK & KEEP-ALIVE (Render 404 / Spin-Down Çözümü) ---
@app.route("/", methods=["GET"])
@app.route("/health", methods=["GET"])
@app.route("/ping", methods=["GET"])
def health_check():
  status_str, _ = get_market_status()
  return (
      {
          "status": "alive",
          "market": status_str,
          "balance": virtual_balance,
          "open_positions": len(open_positions),
          "timestamp": time.time(),
      },
      200,
  )


@app.route("/webhook", methods=["POST"])
def tradingview_webhook():
  global virtual_balance, open_positions
  data = request.get_json(silent=True)
  if not data:
    return {"status": "error", "message": "JSON yok"}, 400

  action_raw = str(data.get("action", "")).upper()
  symbol = str(data.get("symbol", "GBPUSD")).upper()
  lot = float(data.get("lot", 1.0))
  price = float(data.get("price", 1.33700))
  sl = float(data.get("sl", price - 0.001))
  tp = float(data.get("tp", price + 0.003))

  action_str = (
      "LONG (BUY)"
      if ("BUY" in action_raw or "LONG" in action_raw)
      else "SHORT (SELL)"
  )

  open_positions.append({
      "symbol": symbol,
      "action": action_str,
      "price": price,
      "sl": sl,
      "tp": tp,
      "lot": lot,
      "time": datetime.now().strftime("%H:%M"),
  })

  emoji_map = {"EURUSD": "💶", "XAUUSD": "🥇", "USDJPY": "💱", "GBPUSD": "💷"}
  em = emoji_map.get(symbol, "⚡")
  reply = (
      f"🚨 *WEBHOOK DEMO İŞLEM* {em}\n"
      f"──────────────────────────\n"
      f"🎯 *Parite:* `{symbol}`\n"
      f"⚡ *Yön:* *{action_str}*\n"
      f"📦 *Lot:* `{lot} Lot`\n"
      f"🏷️ *Giriş:* `{price}` | 🛑 *SL:* `{sl}` | 🎯 *TP:* `{tp}`\n"
      f"──────────────────────────\n"
      f"💡 *Sanal kasaya webhook ile eklendi.*"
  )
  broadcast_telegram(reply)
  return {"status": "success", "added": symbol}, 200


TELEGRAM_TOKEN = os.getenv(
    "TELEGRAM_TOKEN", os.getenv("TELEGRAM_BOT_TOKEN", "")
)
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")

SYMBOLS = {
    "EURUSD": ("EURUSD=X", "💶"),
    "XAUUSD": ("GC=F", "🥇"),
    "USDJPY": ("USDJPY=X", "💱"),
    "GBPUSD": ("GBPUSD=X", "💷"),
}

virtual_balance = 3000.0
INITIAL_BALANCE = 3000.0
open_positions = []
last_signal_time = {}


def send_telegram(chat_id, text):
  if not TELEGRAM_TOKEN or not chat_id:
    return
  url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
  payload = {
      "chat_id": chat_id,
      "text": text,
      "parse_mode": "Markdown",
      "disable_web_page_preview": True,
  }
  try:
    requests.post(url, json=payload, timeout=10)
  except Exception as e:
    print(f"Telegram send err: {e}")


def broadcast_telegram(text):
  if TELEGRAM_CHAT_ID:
    send_telegram(TELEGRAM_CHAT_ID, text)


def fetch_live_price(symbol_key):
  ticker_info = SYMBOLS.get(symbol_key)
  if not ticker_info:
    return None
  ticker = ticker_info[0]
  try:
    data = yf.Ticker(ticker).history(period="1d", interval="1h")
    if data is not None and not data.empty:
      return round(float(data["Close"].iloc[-1]), 5)
  except Exception as e:
    print(f"yfinance err for {symbol_key}: {e}")
  return None


def fetch_15m_df(symbol_key):
  ticker_info = SYMBOLS.get(symbol_key)
  if not ticker_info:
    return None
  ticker = ticker_info[0]
  try:
    data = yf.Ticker(ticker).history(period="5d", interval="15m")
    if data is not None and len(data) > 30:
      return data
  except Exception as e:
    print(f"yfinance 15m err for {symbol_key}: {e}")
  return None


def calculate_atr(df, period=14):
  high_low = df["High"] - df["Low"]
  high_close = np.abs(df["High"] - df["Close"].shift())
  low_close = np.abs(df["Low"] - df["Close"].shift())
  ranges = pd.concat([high_low, high_close, low_close], axis=1)
  true_range = np.max(ranges, axis=1)
  return true_range.rolling(period).mean()


def get_market_status():
  tr_tz = timezone(timedelta(hours=3))
  now = datetime.now(tr_tz)
  weekday = now.weekday()
  hour = now.hour

  if weekday == 5 or weekday == 6 or (weekday == 4 and hour >= 23):
    return "🔴 KAPALI", "Pazartesi 00:00 (TR)"
  else:
    return "🟢 AKTİF", "Cuma 23:00 (TR)"


def telegram_poller():
  global virtual_balance, open_positions, TELEGRAM_CHAT_ID
  if not TELEGRAM_TOKEN:
    print("TELEGRAM_TOKEN bulunamadı, poller başlatılmıyor.")
    return

  print("Telegram polling başlatıldı...")
  offset = 0
  url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/getUpdates"

  while True:
    try:
      resp = requests.get(
          url, params={"offset": offset, "timeout": 20}, timeout=25
      )
      if resp.status_code == 200:
        data = resp.json()
        for update in data.get("result", []):
          offset = update["update_id"] + 1
          msg = update.get("message")
          if not msg:
            continue
          chat_id = msg.get("chat", {}).get("id")
          if not TELEGRAM_CHAT_ID:
            TELEGRAM_CHAT_ID = str(chat_id)

          text = msg.get("text", "").strip()

          if text == "/start":
            reply = (
                "⚡ *SCALPRADAR TERMINAL v2.1*\n"
                "──────────────────────────\n"
                "🎯 *Komuta Merkezi Aktif!*\n\n"
                "📋 *Mevcut Komutlar:*\n"
                "• /durum — _Sanal kasa & piyasa nabzı_\n"
                "• /fiyat — _Canlı parite akışı (EURUSD, XAUUSD, USDJPY,"
                " GBPUSD)_\n"
                "• /reset — _Kasayı $3,000'a sıfırla_\n"
                "──────────────────────────"
            )
            send_telegram(chat_id, reply)

          elif text == "/durum":
            status_str, time_str = get_market_status()
            status_line = (
                f"{status_str} *(Kapanış: {time_str}*)"
                if status_str == "🟢 AKTİF"
                else f"{status_str} *(Açılış: {time_str}*)"
            )

            pnl_diff = virtual_balance - INITIAL_BALANCE
            pnl_emoji = "🟢" if pnl_diff >= 0 else "🔴"
            pnl_str = (
                f"+${pnl_diff:,.2f}"
                if pnl_diff >= 0
                else f"-${abs(pnl_diff):,.2f}"
            )

            if open_positions:
              pos_lines = []
              for p in open_positions:
                pos_lines.append(
                    f"▪️ `{p['symbol']}` | *{p['action']}* | {p.get('lot', 1.0)}"
                    f" Lot | G: `{p['price']}`"
                )
              pos_str = "\n".join(pos_lines)
            else:
              pos_str = "💤 _Aktif pozisyon bulunmuyor._"

            reply = (
                f"🛡️ *SANAL KASA & RİSK RAPORU*\n"
                f"──────────────────────────\n"
                f"💵 *Bakiye:* `${virtual_balance:,.2f}`  {pnl_emoji}"
                f" `({pnl_str})`\n"
                f"📡 *Piyasa:* {status_line}\n\n"
                f"📂 *Açık Pozisyonlar:*\n{pos_str}\n"
                f"──────────────────────────"
            )
            send_telegram(chat_id, reply)

          elif text == "/fiyat":
            status_str, _ = get_market_status()
            lines = []
            for s, (ticker_code, emoji) in SYMBOLS.items():
              val = fetch_live_price(s)
              val_str = f"`{val}`" if val is not None else "`Veri Yok`"
              lines.append(f"{emoji} *{s}*: {val_str}")

            prices_block = "\n".join(lines)
            reply = (
                f"📈 *CANLI PİYASA AKIŞI*\n"
                f"──────────────────────────\n"
                f"{status_str} — Anlık Fiyatlar:\n\n"
                f"{prices_block}\n"
                f"──────────────────────────"
            )
            send_telegram(chat_id, reply)

          elif text == "/reset":
            virtual_balance = INITIAL_BALANCE
            open_positions.clear()
            reply = (
                f"🔄 *KASA SIFIRLANDI*\n"
                f"──────────────────────────\n"
                f"⚠️ Sanal bakiye **$3,000.00** seviyesine resetlendi.\n"
                f"🗑️ Tüm açık pozisyonlar temizlendi.\n"
                f"──────────────────────────"
            )
            send_telegram(chat_id, reply)

    except Exception as e:
      print(f"Telegram polling err: {e}")
    time.sleep(2)


def evaluate_scalp_strategy(symbol):
  df = fetch_15m_df(symbol)
  if df is None or len(df) < 30:
    return None

  close = df["Close"]
  ema9 = close.ewm(span=9).mean()
  ema21 = close.ewm(span=21).mean()
  atr = calculate_atr(df, 14)

  delta = close.diff()
  gain = (delta.where(delta > 0, 0)).rolling(14).mean()
  loss = (-delta.where(delta < 0, 0)).rolling(14).mean()
  rs = gain / loss
  rsi = 100 - (100 / (1 + rs))

  last_close = float(close.iloc[-1])
  last_ema9 = float(ema9.iloc[-1])
  prev_ema9 = float(ema9.iloc[-2])
  last_ema21 = float(ema21.iloc[-1])
  prev_ema21 = float(ema21.iloc[-2])
  last_rsi = float(rsi.iloc[-1]) if not pd.isna(rsi.iloc[-1]) else 50.0
  last_atr = (
      float(atr.iloc[-1]) if not pd.isna(atr.iloc[-1]) else (last_close * 0.001)
  )

  action = None
  if prev_ema9 <= prev_ema21 and last_ema9 > last_ema21 and 45 < last_rsi < 70:
    action = "LONG (BUY)"
  elif prev_ema9 >= prev_ema21 and last_ema9 < last_ema21 and 30 < last_rsi < 55:
    action = "SHORT (SELL)"

  if action:
    sl_dist = last_atr * 1.5
    tp_dist = last_atr * 3.0
    if "LONG" in action:
      sl = round(last_close - sl_dist, 5)
      tp = round(last_close + tp_dist, 5)
    else:
      sl = round(last_close + sl_dist, 5)
      tp = round(last_close - tp_dist, 5)

    sl_diff = abs(last_close - sl)
    pip_mult = (
        100.0 if "JPY" in symbol else (10.0 if symbol == "XAUUSD" else 10000.0)
    )
    pip_val = sl_diff * pip_mult
    risk_target = virtual_balance * 0.05
    raw_lot = (risk_target / pip_val) * 2.5 if pip_val > 0 else 1.0
    lot_size = round(max(0.5, min(raw_lot, 5.0)), 2)

    return {
        "symbol": symbol,
        "action": action,
        "price": round(last_close, 5),
        "sl": sl,
        "tp": tp,
        "rsi": round(last_rsi, 1),
        "atr": round(last_atr, 5),
        "lot": lot_size,
    }
  return None


def bot_loop():
  global virtual_balance, open_positions
  print("ScalpBot 15m strateji döngüsü devrede...")
  while True:
    try:
      status_str, _ = get_market_status()
      if status_str == "🟢 AKTİF":
        for symbol in SYMBOLS.keys():
          now_ts = time.time()
          if now_ts - last_signal_time.get(symbol, 0) < 900:
            continue

          sig = evaluate_scalp_strategy(symbol)
          if sig:
            last_signal_time[symbol] = now_ts
            risk_amount = virtual_balance * 0.05
            open_positions.append({
                "symbol": symbol,
                "action": sig["action"],
                "price": sig["price"],
                "sl": sig["sl"],
                "tp": sig["tp"],
                "lot": sig["lot"],
                "risk_usd": round(risk_amount, 2),
                "time": datetime.now().strftime("%H:%M"),
            })

            emoji_map = {
                "EURUSD": "💶",
                "XAUUSD": "🥇",
                "USDJPY": "💱",
                "GBPUSD": "💷",
            }
            em = emoji_map.get(symbol, "⚡")
            reply = (
                f"🚨 *15M VIP SCALP SİNYALİ* {em}\n"
                f"──────────────────────────\n"
                f"🎯 *Parite:* `{sig['symbol']}`\n"
                f"⚡ *Yön:* *{sig['action']}*\n"
                f"📦 *Lot Boyutu:* `{sig['lot']} Lot`\n"
                f"🏷️ *Giriş Fiyatı:* `{sig['price']}`\n"
                f"🛑 *Stop-Loss (1.5xATR):* `{sig['sl']}`\n"
                f"🎯 *Take-Profit (3.0xATR):* `{sig['tp']}`\n"
                f"📊 *RSI(14):* `{sig['rsi']}` | *ATR:* `{sig['atr']}`\n"
                f"💰 *Simüle Risk:* `${risk_amount:,.2f}` (Agresif Demo)\n"
                f"──────────────────────────\n"
                f"💡 *Sanal kasaya işlendi.*"
            )
            broadcast_telegram(reply)
            print(f"VIP Sinyal üretildi ve işlendi: {sig}")
      else:
        print("Piyasa kapalı, tarama es geçiliyor...")
    except Exception as e:
      print(f"Loop err: {e}")
    time.sleep(60)


if __name__ == "__main__":
  t_loop = threading.Thread(target=bot_loop, daemon=True)
  t_loop.start()

  t_telegram = threading.Thread(target=telegram_poller, daemon=True)
  t_telegram.start()

  port = int(os.environ.get("PORT", 10000))
  app.run(host="0.0.0.0", port=port)
