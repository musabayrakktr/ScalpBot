from datetime import datetime, timezone, timedelta
import os
import threading
import time
from flask import Flask
import numpy as np
import pandas as pd
import requests
import yfinance as yf

app = Flask(__name__)


@app.route("/")
def health_check():
  return "ScalpBot is alive!", 200


# Env okuma (Render env'deki key adlarıyla uyumlu)
TELEGRAM_TOKEN = os.getenv(
    "TELEGRAM_TOKEN", os.getenv("TELEGRAM_BOT_TOKEN", "")
)
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")

SYMBOLS = {
    "EURUSD": "EURUSD=X",
    "XAUUSD": "GC=F",
    "USDJPY": "USDJPY=X",
    "GBPUSD": "GBPUSD=X",
}

# Sanal kasa durumu hafızası
virtual_balance = 3000.0
open_positions = []


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


def fetch_live_price(symbol_key):
  ticker = SYMBOLS.get(symbol_key, "EURUSD=X")
  try:
    data = yf.Ticker(ticker).history(period="1d", interval="1h")
    if data is not None and not data.empty:
      return round(float(data["Close"].iloc[-1]), 5)
  except Exception as e:
    print(f"yfinance err for {symbol_key}: {e}")
  return None


def get_market_status():
  tr_tz = timezone(timedelta(hours=3))
  now = datetime.now(tr_tz)
  weekday = now.weekday()  # 0=Pazartesi, ..., 5=Cumartesi, 6=Pazar
  hour = now.hour

  if weekday == 5:
    return "🔴 KAPALI", "Pazartesi 00:00 (TR)"
  elif weekday == 6:
    return "🔴 KAPALI", "Pazartesi 00:00 (TR)"
  elif weekday == 4 and hour >= 23:
    return "🔴 KAPALI", "Pazartesi 00:00 (TR)"
  else:
    return "🟢 AKTİF", "Cuma 23:00 (TR)"


def telegram_poller():
  if not TELEGRAM_TOKEN:
    print("TELEGRAM_TOKEN bulunamadı, poller başlatılmıyor.")
    return

  print("Telegram polling başlatıldı...")
  offset = 0
  url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/getUpdates"

  while True:
    try:
      resp = requests.get(
          url, params={"offset": offset, "timeout": 30}, timeout=35
      )
      if resp.status_code == 200:
        data = resp.json()
        for update in data.get("result", []):
          offset = update["update_id"] + 1
          msg = update.get("message")
          if not msg:
            continue
          chat_id = msg.get("chat", {}).get("id")
          text = msg.get("text", "").strip()

          if text == "/durum":
            status_str, time_str = get_market_status()
            status_line = (
                f"{status_str} (Kapanış/Açılış: {time_str})"
                if status_str == "🟢 AKTİF"
                else f"{status_str} (Açılış: {time_str})"
            )
            pos_str = (
                "\n".join([
                    f"- {p['symbol']} {p['action']} @ {p['price']}"
                    for p in open_positions
                ])
                if open_positions
                else "Açık pozisyon yok."
            )
            reply = (
                f"💰 *Sanal Kasa & Pozisyonlar*\n"
                f"Kasa: `${virtual_balance:,.2f}`\n"
                f"Piyasa: {status_line}\n\n"
                f"*Pozisyonlar:*\n{pos_str}"
            )
            send_telegram(chat_id, reply)
          elif text == "/fiyat":
            prices_str = "\n".join([
                f"{s}: `{fetch_live_price(s)}`" for s in SYMBOLS.keys()
            ])
            reply = f"📊 *Anlık Fiyatlar*\n{prices_str}"
            send_telegram(chat_id, reply)
    except Exception as e:
        print(f"Telegram polling err: {e}")
    time.sleep(3)


def bot_loop():
  print("ScalpBot veri döngüsü devrede...")
  while True:
    try:
      p_str = " | ".join(
          [f"{s}: {fetch_live_price(s)}" for s in SYMBOLS.keys()]
      )
      print(f"Canlı Fiyatlar -> {p_str}")
    except Exception as e:
      print(f"Loop err: {e}")
    time.sleep(300)


if __name__ == "__main__":
  t_loop = threading.Thread(target=bot_loop, daemon=True)
  t_loop.start()

  t_telegram = threading.Thread(target=telegram_poller, daemon=True)
  t_telegram.start()

  port = int(os.environ.get("PORT", 10000))
  app.run(host="0.0.0.0", port=port)
