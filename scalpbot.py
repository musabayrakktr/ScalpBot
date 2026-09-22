from datetime import datetime, timezone, timedelta
import html
import logging
from logging.handlers import RotatingFileHandler
import os
import sqlite3
import threading
import time
from zoneinfo import ZoneInfo
from flask import Flask
import numpy as np
import pandas as pd
import requests
import yfinance as yf
# ==========================================
# 0. SİMÜLASYON / MİMARİ NOTU (v3.75)
# ==========================================
SIMULATION_MODE = True
try:
  import fcntl
except ImportError:
  fcntl = None
try:
  import msvcrt
except ImportError:
  msvcrt = None
# ==========================================
# 1. LOGGING MİMARİSİ
# ==========================================
LOG_DIR = os.getenv(
    "LOG_DIR",
    (
        "/tmp/scalpbot_logs"
        if os.getenv("RENDER") or os.getenv("PORT")
        else "./logs"
    ),
)
os.makedirs(LOG_DIR, mode=0o755, exist_ok=True)
def setup_logger(name, filename):
  logger = logging.getLogger(name)
  logger.setLevel(logging.INFO)
  if not logger.handlers:
    formatter = logging.Formatter(
        "%(asctime)s | %(levelname)-7s | [%(name)s] | %(message)s"
    )
    filepath = os.path.join(LOG_DIR, filename)
    fh = RotatingFileHandler(
        filepath, maxBytes=5 * 1024 * 1024, backupCount=3
    )
    fh.setFormatter(formatter)
    logger.addHandler(fh)
    ch = logging.StreamHandler()
    ch.setFormatter(formatter)
    logger.addHandler(ch)
  return logger
logger_data = setup_logger("DATA", "data_fetch.log")
logger_telegram = setup_logger("TELEGRAM", "telegram.log")
logger_strategy = setup_logger("STRATEGY", "strategy.log")
logger_exec = setup_logger("EXECUTION", "execution.log")
app = Flask(__name__)
# ==========================================
# 2. VERİTABANI & PERSISTENT DISK
# ==========================================
db_lock = threading.Lock()
def get_persistent_db_path():
  custom_db = os.getenv("DB_PATH", "").strip()
  if custom_db:
    parent_dir = os.path.dirname(custom_db)
    if parent_dir:
      os.makedirs(parent_dir, mode=0o755, exist_ok=True)
    return custom_db
  render_disk = "/var/data"
  if os.path.exists(render_disk) and os.access(render_disk, os.W_OK):
    os.makedirs(
        os.path.join(render_disk, "scalpbot_db"), mode=0o755, exist_ok=True
    )
    return os.path.join(render_disk, "scalpbot_db", "scalpbot.db")
  elif os.path.exists("/data") and os.access("/data", os.W_OK):
    return os.path.join("/data", "scalpbot.db")
  return "scalpbot.db"
DB_NAME = get_persistent_db_path()
logger_exec.info(
    f"Aktif SQLite DB Yolu (v3.75 | SIMULATION_MODE={SIMULATION_MODE}):"
    f" {DB_NAME}"
)
def get_istanbul_today():
  return datetime.now(ZoneInfo("Europe/Istanbul")).strftime("%Y-%m-%d")
def init_db():
  with db_lock, sqlite3.connect(DB_NAME) as conn:
    c = conn.cursor()
    c.execute("""
            CREATE TABLE IF NOT EXISTS state (
                key TEXT PRIMARY KEY,
                value REAL
            )
        """)
    c.execute("""
            CREATE TABLE IF NOT EXISTS state_str (
                key TEXT PRIMARY KEY,
                value TEXT
            )
        """)
    c.execute("""
            CREATE TABLE IF NOT EXISTS positions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                symbol TEXT,
                action TEXT,
                price REAL,
                sl REAL,
                tp REAL,
                lot REAL,
                risk_usd REAL,
                entry_commission REAL DEFAULT 0.0,
                open_time TEXT
            )
        """)
    try:
      c.execute(
          "ALTER TABLE positions ADD COLUMN entry_commission REAL DEFAULT 0.0"
      )
    except sqlite3.OperationalError:
      pass
    c.execute("""
            CREATE TABLE IF NOT EXISTS closed_trades (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                symbol TEXT,
                action TEXT,
                price REAL,
                exit_price REAL,
                lot REAL,
                pnl REAL,
                reason TEXT,
                close_time TEXT
            )
        """)
    c.execute("""
            CREATE TABLE IF NOT EXISTS signal_cooldown (
                symbol TEXT PRIMARY KEY,
                last_time REAL
            )
        """)
    c.execute("""
            CREATE TABLE IF NOT EXISTS processed_bars (
                symbol TEXT PRIMARY KEY,
                bar_time TEXT
            )
        """)
    c.execute("""
            CREATE TABLE IF NOT EXISTS market_health (
                symbol TEXT,
                timeframe TEXT,
                last_valid_time REAL,
                PRIMARY KEY (symbol, timeframe)
            )
        """)
    c.execute(
        "INSERT OR IGNORE INTO state (key, value) VALUES ('balance', 3000.0)"
    )
    c.execute(
        "INSERT OR IGNORE INTO state (key, value) VALUES ('realized_pnl', 0.0)"
    )
    c.execute("INSERT OR IGNORE INTO state (key, value) VALUES ('paused', 0.0)")
    c.execute(
        "INSERT OR IGNORE INTO state (key, value) VALUES ('daily_loss', 0.0)"
    )
    today_str = get_istanbul_today()
    c.execute(
        "INSERT OR IGNORE INTO state_str (key, value) VALUES"
        " ('daily_loss_date', ?)",
        (today_str,),
    )
    conn.commit()
  logger_exec.info("SQLite veritabanı (v3.75) hazır.")
init_db()
def get_state(key, default=0.0):
  with db_lock, sqlite3.connect(DB_NAME) as conn:
    c = conn.cursor()
    c.execute("SELECT value FROM state WHERE key = ?", (key,))
    row = c.fetchone()
    return float(row[0]) if row and row[0] is not None else default
def set_state(key, value):
  with db_lock, sqlite3.connect(DB_NAME) as conn:
    c = conn.cursor()
    c.execute(
        "INSERT OR REPLACE INTO state (key, value) VALUES (?, ?)", (key, value)
    )
    conn.commit()
def check_and_reset_daily_loss():
  today_str = get_istanbul_today()
  with db_lock, sqlite3.connect(DB_NAME) as conn:
    con = conn
    r_date = con.execute(
        "SELECT value FROM state_str WHERE key = 'daily_loss_date'"
    ).fetchone()
    stored_date = str(r_date[0]) if r_date and r_date[0] is not None else ""
    if stored_date != today_str:
      con.execute(
          "INSERT OR REPLACE INTO state (key, value) VALUES ('daily_loss',"
          " 0.0)"
      )
      con.execute(
          "INSERT OR REPLACE INTO state_str (key, value) VALUES"
          " ('daily_loss_date', ?)",
          (today_str,),
      )
      conn.commit()
      return 0.0
    r_dl = con.execute(
        "SELECT value FROM state WHERE key = 'daily_loss'"
    ).fetchone()
    return float(r_dl[0]) if r_dl and r_dl[0] is not None else 0.0
def set_db_last_fetch(symbol, timeframe, ts):
  with db_lock, sqlite3.connect(DB_NAME) as conn:
    conn.execute(
        "INSERT OR REPLACE INTO market_health (symbol, timeframe,"
        " last_valid_time) VALUES (?, ?, ?)",
        (symbol, timeframe, ts),
    )
    conn.commit()
def update_balance_db_conn(con, delta, is_loss_item=False):
  today_str = get_istanbul_today()
  r = con.execute("SELECT value FROM state WHERE key = 'balance'").fetchone()
  curr = float(r[0]) if r and r[0] is not None else 3000.0
  new_val = curr + delta
  con.execute(
      "INSERT OR REPLACE INTO state (key, value) VALUES ('balance', ?)",
      (new_val,),
  )
  if delta < 0 and is_loss_item:
    r_date = con.execute(
        "SELECT value FROM state_str WHERE key = 'daily_loss_date'"
    ).fetchone()
    stored_date = str(r_date[0]) if r_date and r_date[0] is not None else ""
    if stored_date != today_str:
      con.execute(
          "INSERT OR REPLACE INTO state_str (key, value) VALUES"
          " ('daily_loss_date', ?)",
          (today_str,),
      )
      con.execute(
          "INSERT OR REPLACE INTO state (key, value) VALUES ('daily_loss',"
          " 0.0)"
      )
      curr_dl = 0.0
    else:
      r_dl = con.execute(
          "SELECT value FROM state WHERE key = 'daily_loss'"
      ).fetchone()
      curr_dl = float(r_dl[0]) if r_dl and r_dl[0] is not None else 0.0
    con.execute(
        "INSERT OR REPLACE INTO state (key, value) VALUES ('daily_loss', ?)",
        (curr_dl + abs(delta),),
    )
  return new_val
def update_balance_db(delta, is_loss_item=False):
  with db_lock, sqlite3.connect(DB_NAME) as conn:
    with conn:
      return update_balance_db_conn(conn, delta, is_loss_item=is_loss_item)
def reset_db_state():
  today_str = get_istanbul_today()
  with db_lock, sqlite3.connect(DB_NAME) as conn:
    c = conn.cursor()
    c.execute(
        "INSERT OR REPLACE INTO state (key, value) VALUES ('balance', 3000.0)"
    )
    c.execute(
        "INSERT OR REPLACE INTO state (key, value) VALUES ('realized_pnl',"
        " 0.0)"
    )
    c.execute("INSERT OR REPLACE INTO state (key, value) VALUES ('paused', 0.0)")
    c.execute(
        "INSERT OR REPLACE INTO state (key, value) VALUES ('daily_loss', 0.0)"
    )
    c.execute(
        "INSERT OR REPLACE INTO state_str (key, value) VALUES"
        " ('daily_loss_date', ?)",
        (today_str,),
    )
    c.execute("DELETE FROM positions")
    c.execute("DELETE FROM closed_trades")
    c.execute("DELETE FROM signal_cooldown")
    c.execute("DELETE FROM processed_bars")
    c.execute("DELETE FROM market_health")
    conn.commit()
  logger_exec.warning(
      "Kasa, pozisyonlar, geçmiş, günlük limit, cooldown, processed bar ve"
      f" market health ({today_str}) sıfırlandı."
  )
def get_db_positions():
  with db_lock, sqlite3.connect(DB_NAME) as conn:
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    c.execute("SELECT * FROM positions")
    rows = c.fetchall()
    return [dict(row) for row in rows]
COMMISSION_PER_SIDE = 3.50
def atomic_add_position_safely(pos_dict, max_pos=3, max_risk_limit=300.0):
  with db_lock, sqlite3.connect(DB_NAME) as conn:
    with conn:
      c = conn.cursor()
      c.execute(
          "SELECT count(*) FROM positions WHERE symbol = ?",
          (pos_dict["symbol"],),
      )
      row_sym = c.fetchone()
      if row_sym and row_sym[0] > 0:
        return (
            False,
            f"Sembolde [{pos_dict['symbol']}] açık pozisyon zaten var.",
        )
      c.execute("SELECT count(*), sum(risk_usd) FROM positions")
      row = c.fetchone()
      cnt = int(row[0]) if row and row[0] is not None else 0
      total_open_risk = (
          float(row[1])
          if row and len(row) > 1 and row[1] is not None
          else 0.0
      )
      if cnt >= max_pos:
        return False, f"Max pozisyon sınırına ulaşıldı ({cnt}/{max_pos})."
      if (total_open_risk + pos_dict["risk_usd"]) > max_risk_limit:
        return (
            False,
            f"Toplam risk limiti aşılır"
            f" (${total_open_risk + pos_dict['risk_usd']:.2f} >"
            f" ${max_risk_limit}).",
        )
      entry_comm = pos_dict["lot"] * COMMISSION_PER_SIDE
      c.execute(
          """
                INSERT INTO positions (symbol, action, price, sl, tp, lot, risk_usd, entry_commission, open_time)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
          (
              pos_dict["symbol"],
              pos_dict["action"],
              pos_dict["price"],
              pos_dict["sl"],
              pos_dict["tp"],
              pos_dict["lot"],
              pos_dict["risk_usd"],
              entry_comm,
              pos_dict["time"],
          ),
      )
      update_balance_db_conn(conn, -entry_comm, is_loss_item=True)
  return True, "ATOMİK EKLEME & GİRİŞ KOMİSYONU BAŞARILI"
def get_closed_trades(limit=10):
  with db_lock, sqlite3.connect(DB_NAME) as conn:
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    c.execute(
        "SELECT * FROM closed_trades ORDER BY id DESC LIMIT ?", (limit,)
    )
    rows = c.fetchall()
    return [dict(row) for row in rows]
def get_trade_statistics():
  with db_lock, sqlite3.connect(DB_NAME) as conn:
    c = conn.cursor()
    row = c.execute(
        "SELECT count(*), sum(pnl), avg(pnl) FROM closed_trades"
    ).fetchone()
    total_trades = int(row[0]) if row and row[0] is not None else 0
    net_pnl = (
    float(row[1])
    if row and len(row) > 1 and row[1] is not None
    else 0.0
)
avg_pnl = (
    float(row[2])
    if row and len(row) > 2 and row[2] is not None
    else 0.0
)
    win_row = c.execute(
        "SELECT count(*) FROM closed_trades WHERE pnl > 0"
    ).fetchone()
    wins = int(win_row[0]) if win_row and win_row[0] is not None else 0
  win_rate = (wins / total_trades * 100.0) if total_trades > 0 else 0.0
  bal = get_state("balance", 3000.0)
  return {
      "total_trades": total_trades,
      "wins": wins,
      "win_rate": win_rate,
      "net_pnl": net_pnl,
      "avg_pnl": avg_pnl,
      "current_balance": bal,
  }
@app.route("/")
@app.route("/ping")
def health_check():
  return "ScalpBot Pro WSGI + Ext v3.75 is alive!", 200
TELEGRAM_TOKEN = os.getenv(
    "TELEGRAM_TOKEN", os.getenv("TELEGRAM_BOT_TOKEN", "")
)
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")
ALLOWED_USERS_ENV = os.getenv("ALLOWED_TELEGRAM_IDS", "").strip()
ALLOWED_USER_IDS = (
    [x.strip() for x in ALLOWED_USERS_ENV.split(",") if x.strip()]
    if ALLOWED_USERS_ENV
    else []
)
SYMBOLS = {
    "EURUSD": ("EURUSD=X", "💶", 100000.0, True, 1.5, 3.0),
    "XAUUSD": ("XAU=X", "🥇", 100.0, True, 1.2, 2.5),
    "USDJPY": ("USDJPY=X", "💱", 100000.0, False, 1.5, 3.0),
    "GBPUSD": ("GBPUSD=X", "💷", 100000.0, True, 1.5, 3.0),
}
def get_symbol_info(symbol_key):
  if symbol_key not in SYMBOLS:
    raise ValueError(f"Desteklenmeyen sembol: {symbol_key}")
  return SYMBOLS[symbol_key]
INITIAL_BALANCE = 3000.0
MAX_DAILY_LOSS = 150.0
MAX_OPEN_POSITIONS = 3
MAX_TOTAL_OPEN_RISK = 300.0
SLIPPAGE_PRICE = {
    "EURUSD": 0.0001,
    "XAUUSD": 0.15,
    "USDJPY": 0.015,
    "GBPUSD": 0.0001,
}
def send_telegram(chat_id, text):
  if not TELEGRAM_TOKEN or not chat_id:
    return False
  url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
  payload = {
      "chat_id": chat_id,
      "text": text,
      "parse_mode": "HTML",
      "disable_web_page_preview": True,
  }
  try:
    resp = requests.post(url, json=payload, timeout=10)
    if resp.status_code != 200:
      err_info = (
          resp.json()
          if resp.headers.get("content-type", "").startswith(
              "application/json"
          )
          else resp.text
      )
      logger_telegram.error(
          f"HTTP {resp.status_code} err for {chat_id}: {err_info}"
      )
      return False
    data = resp.json()
    if not data.get("ok", False):
      logger_telegram.error(f"API fail response: {data}")
      return False
    return True
  except Exception as e:
    logger_telegram.error(f"Genel request hatası: {e}")
    return False
def broadcast_telegram(text):
  if TELEGRAM_CHAT_ID:
    send_telegram(TELEGRAM_CHAT_ID, text)
def is_authorized_user(chat_id):
  str_id = str(chat_id)
  if not ALLOWED_USER_IDS:
    logger_security = logging.getLogger("SECURITY")
    logger_security.warning(
        "ALLOWED_USER_IDS boş! Komut erişimi güvenlik nedeniyle kapatıldı."
    )
    return False
  return str_id in ALLOWED_USER_IDS
def verify_price_sanity(symbol_key, live_p):
  if live_p <= 0:
    return False
  return True
def fetch_live_price(symbol_key):
  ticker, _, _, _, _, _ = get_symbol_info(symbol_key)
  try:
    data = yf.Ticker(ticker).history(period="1d", interval="1m")
    if data is not None and not data.empty:
      set_db_last_fetch(symbol_key, "1m", time.time())
      dig = 2 if symbol_key == "XAUUSD" else (3 if "JPY" in symbol_key else 5)
      val = round(float(data["Close"].iloc[-1]), dig)
      if verify_price_sanity(symbol_key, val):
        return val
  except Exception as e:
    logger_data.error(f"yfinance live err for {symbol_key}: {e}")
  return None
def fetch_tf_df(symbol_key, interval="15m", period="5d"):
  ticker, _, _, _, _, _ = get_symbol_info(symbol_key)
  try:
    data = yf.Ticker(ticker).history(period=period, interval=interval)
    if data is not None and len(data) > 30:
      set_db_last_fetch(symbol_key, interval, time.time())
      last_bar_time = data.index[-1]
      if hasattr(last_bar_time, "timestamp"):
        bar_sec = last_bar_time.timestamp()
        interval_map = {
            "1m": 60,
            "5m": 300,
            "15m": 900,
            "30m": 1800,
            "1h": 3600,
            "4h": 14400,
            "1d": 86400,
        }
        iv_sec = interval_map.get(interval, 900)
        if time.time() < (bar_sec + iv_sec):
          return data.iloc[:-1]
      return data
  except Exception as e:
    logger_data.error(f"yfinance {interval} err for {symbol_key}: {e}")
  return None
def calculate_rsi(series, period=14):
  delta = series.diff()
  gain = (delta.where(delta > 0, 0)).rolling(period).mean()
  loss = (-delta.where(delta < 0, 0)).rolling(period).mean()
  rs = gain / loss
  return 100 - (100 / (1 + rs))
def calculate_atr(df, period=14):
  high_low = df["High"] - df["Low"]
  high_close = np.abs(df["High"] - df["Close"].shift())
  low_close = np.abs(df["Low"] - df["Close"].shift())
  ranges = pd.concat([high_low, high_close, low_close], axis=1)
  true_range = np.max(ranges, axis=1)
  return true_range.rolling(period).mean()
def get_market_status(symbol="EURUSD"):
  tr_tz = ZoneInfo("Europe/Istanbul")
  now = datetime.now(tr_tz)
  weekday = now.weekday()
  hour = now.hour
  if weekday == 5 or weekday == 6:
    return "🔴 KAPALI", "Pazartesi 00:00 (TR)"
  if weekday == 4 and hour >= 23:
    return "🔴 KAPALI", "Pazartesi 00:00 (TR)"
  if symbol == "XAUUSD" and hour == 23:
    return "🟡 LİKİDİTE MOLASI", "Gece 01:00 (TR)"
  return "🟢 AKTİF", "Cuma 23:00 (TR)"
def check_higher_tf_trend(symbol_key):
  df_1h = fetch_tf_df(symbol_key, interval="1h", period="10d")
  if df_1h is None or len(df_1h) < 20:
    return "NEUTRAL"
  close = df_1h["Close"]
  ema_f = close.ewm(span=9).mean().iloc[-1]
  ema_s = close.ewm(span=21).mean().iloc[-1]
  if ema_f > ema_s:
    return "BULLISH"
  elif ema_f < ema_s:
    return "BEARISH"
  return "NEUTRAL"
def compute_gross_usd_pnl(symbol, action, entry_price, current_or_exit_price, lot):
  _, _, contract_size, is_direct_usd, _, _ = get_symbol_info(symbol)
  is_long = "LONG" in action
  diff = (
      (current_or_exit_price - entry_price)
      if is_long
      else (entry_price - current_or_exit_price)
  )
  if is_direct_usd:
    return diff * contract_size * lot
  else:
    jpy_profit = diff * contract_size * lot
    conv_rate = (
        current_or_exit_price if current_or_exit_price > 0 else 150.0
    )
    return jpy_profit / conv_rate
def calculate_exact_exit_pnl(symbol, action, entry_price, exit_target_price, lot, entry_comm=0.0):
  gross_pnl = compute_gross_usd_pnl(
      symbol, action, entry_price, exit_target_price, lot
  )
  exit_comm = lot * COMMISSION_PER_SIDE
  return gross_pnl - exit_comm - entry_comm
def calculate_open_positions_pnl():
  total_open_pnl = 0.0
  total_open_risk = 0.0
  parsed_positions = []
  open_positions = get_db_positions()
  for p in open_positions:
    sym = p["symbol"]
    _, _, contract_size, is_direct_usd, _, _ = get_symbol_info(sym)
    curr_p = fetch_live_price(sym) or p["price"]
    gross_pnl = compute_gross_usd_pnl(
        sym, p["action"], p["price"], curr_p, p["lot"]
    )
    total_open_pnl += gross_pnl
    sl_dist = abs(p["price"] - p["sl"])
    if is_direct_usd:
      risk_item = sl_dist * contract_size * p["lot"]
    else:
      risk_item = (sl_dist * contract_size * p["lot"]) / (
          curr_p if curr_p > 0 else 150.0
      )
    total_open_risk += risk_item
    parsed_positions.append({**p, "curr_price": curr_p, "pnl": gross_pnl})
  return total_open_pnl, total_open_risk, parsed_positions
def format_signed_pnl(val):
  prefix = "🟢+" if val >= 0 else "🔴-"
  return f"{prefix} ${html.escape(f'{abs(val):,.2f}')}"
def telegram_poller():
  global TELEGRAM_CHAT_ID
  if not TELEGRAM_TOKEN:
  
