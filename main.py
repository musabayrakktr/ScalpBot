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
  global virtual_balance, open_positions
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
          text = msg.get("text", "").strip()

          if text == "/start":
            reply = (
                "⚡ *SCALPRADAR TERMINAL v2.1*\n"
                "──────────────────────────\n"
                "🎯 *Komuta Merkezi Aktif!*\n\n"
                "📋 *Mevcut Komutlar:*\n"
                "• /durum — _Sanal kasa & piyasa nabzı_\n"
                "• /fiyat — _Canlı parite akışı (EURUSD, XAUUSD, USDJPY, GBPUSD)_\n"
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
                f"+${pnl_diff:,.2f}" if pnl_diff >= 0 else f"-${abs(pnl_diff):,.2f}"
            )

            if open_positions:
              pos_lines = []
              for p in open_positions:
                pos_lines.append(
                    f"▪️ `{p['symbol']}` | *{p['action']}* | G: `{p['price']}`"
                )
              pos_str = "\n".join(pos_lines)
            else:
              pos_str = "💤 _Aktif pozisyon bulunmuyor._"

            reply = (
                f"🛡️ *SANAL KASA & RİSK RAPORU*\n"
                f"──────────────────────────\n"
                f"💵 *Bakiye:* `${virtual_balance:,.2f}`  {pnl_emoji} `({pnl_str})`\n"
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
