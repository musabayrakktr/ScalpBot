# ============================================================
# SCALPBOT PRO — TELEGRAM SIGNAL BOT
# PART 1 / 2
# ============================================================

import os
import time
import html
import sqlite3
import logging
import threading
import datetime as dt

from logging.handlers import RotatingFileHandler
from zoneinfo import ZoneInfo
from datetime import datetime, timezone, time

import numpy as np
import pandas as pd
import requests
import yfinance as yf

from flask import Flask, jsonify


# ============================================================
# CONFIG
# ============================================================

APP_NAME = "ScalpBot Pro"
VERSION = "4.0-SIGNAL"

SIMULATION_MODE = True

TIMEZONE = "Europe/Istanbul"
TZ = ZoneInfo(TIMEZONE)

DB_FILE = "scalpbot.db"

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN", "").strip()
ALLOWED_TELEGRAM_IDS = os.getenv("ALLOWED_TELEGRAM_IDS", "").strip()
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "").strip()

WEB_HOST = "0.0.0.0"
WEB_PORT = int(os.getenv("PORT", "10000"))


# ============================================================
# RISK SETTINGS
# ============================================================

INITIAL_BALANCE = 3000.0

MAX_DAILY_LOSS = 150.0
MAX_OPEN_POSITIONS = 3
MAX_TOTAL_OPEN_RISK = 300.0

COMMISSION_PER_SIDE = 3.50

SIGNAL_COOLDOWN_SECONDS = 900

LOOP_SECONDS = 30


# ============================================================
# MARKET SETTINGS
# ============================================================

SYMBOL_CONFIG = {
    # =========================
    # FOREX MAJORS
    # =========================

    "EURUSD": {
        "yf": "EURUSD=X",
        "sl_atr": 1.5,
        "tp_atr": 3.0,
        "digits": 5
    },

    "GBPUSD": {
        "yf": "GBPUSD=X",
        "sl_atr": 1.5,
        "tp_atr": 3.0,
        "digits": 5
    },

    "USDJPY": {
        "yf": "USDJPY=X",
        "sl_atr": 1.5,
        "tp_atr": 3.0,
        "digits": 3
    },

    "AUDUSD": {
        "yf": "AUDUSD=X",
        "sl_atr": 1.5,
        "tp_atr": 3.0,
        "digits": 5
    },

    "USDCAD": {
        "yf": "USDCAD=X",
        "sl_atr": 1.5,
        "tp_atr": 3.0,
        "digits": 5
    },

    "USDCHF": {
        "yf": "USDCHF=X",
        "sl_atr": 1.5,
        "tp_atr": 3.0,
        "digits": 5
    },

    "NZDUSD": {
        "yf": "NZDUSD=X",
        "sl_atr": 1.5,
        "tp_atr": 3.0,
        "digits": 5
    },

    # =========================
    # GOLD
    # =========================

    "XAUUSD": {
        "yf": "XAU=X",
        "sl_atr": 1.2,
        "tp_atr": 2.5,
        "digits": 2
    },
}

# ============================================================
# LOGGING
# ============================================================

logger = logging.getLogger("scalpbot")
logger_strategy = logging.getLogger("strategy")

logger.setLevel(logging.INFO)
logger_strategy.setLevel(logging.INFO)

_formatter = logging.Formatter(
    "%(asctime)s | %(levelname)s | %(name)s | %(message)s"
)

_console = logging.StreamHandler()
_console.setFormatter(_formatter)

_file = RotatingFileHandler(
    "scalpbot.log",
    maxBytes=2_000_000,
    backupCount=3,
    encoding="utf-8",
)

_file.setFormatter(_formatter)

if not logger.handlers:
    logger.addHandler(_console)
    logger.addHandler(_file)

if not logger_strategy.handlers:
    logger_strategy.addHandler(_console)
    logger_strategy.addHandler(_file)


# ============================================================
# FLASK
# ============================================================

app = Flask(__name__)


# ============================================================
# DATABASE
# ============================================================

DB_LOCK = threading.Lock()


def db_connect():
    conn = sqlite3.connect(
        DB_FILE,
        timeout=30,
        check_same_thread=False
    )
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def init_db():

    with DB_LOCK:

        conn = db_connect()

        cur = conn.cursor()

        cur.execute("""
            CREATE TABLE IF NOT EXISTS state (
                key TEXT PRIMARY KEY,
                value REAL
            )
        """)

        cur.execute("""
            CREATE TABLE IF NOT EXISTS state_str (
                key TEXT PRIMARY KEY,
                value TEXT
            )
        """)

        cur.execute("""
            CREATE TABLE IF NOT EXISTS positions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                symbol TEXT,
                side TEXT,
                entry REAL,
                sl REAL,
                tp REAL,
                risk REAL,
                opened_at TEXT,
                status TEXT DEFAULT 'OPEN'
            )
        """)

        cur.execute("""
            CREATE TABLE IF NOT EXISTS closed_trades (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                symbol TEXT,
                side TEXT,
                entry REAL,
                exit REAL,
                pnl REAL,
                opened_at TEXT,
                closed_at TEXT
            )
        """)

        cur.execute("""
            CREATE TABLE IF NOT EXISTS signal_cooldown (
                symbol TEXT PRIMARY KEY,
                last_signal INTEGER
            )
        """)

        cur.execute("""
            CREATE TABLE IF NOT EXISTS processed_bars (
                symbol TEXT PRIMARY KEY,
                bar_time TEXT
            )
        """)

        cur.execute("""
            CREATE TABLE IF NOT EXISTS market_health (
                symbol TEXT PRIMARY KEY,
                status TEXT,
                message TEXT,
                updated_at TEXT
            )
        """)

        conn.commit()
        conn.close()


# ============================================================
# STATE HELPERS
# ============================================================

def get_state(key, default=0.0):

    with DB_LOCK:

        conn = db_connect()

        cur = conn.cursor()

        cur.execute(
            "SELECT value FROM state WHERE key = ?",
            (key,)
        )

        row = cur.fetchone()

        conn.close()

    if row is None:
        return default

    try:
        return float(row[0])
    except Exception:
        return default


def set_state(key, value):

    with DB_LOCK:

        conn = db_connect()

        conn.execute("""
            INSERT INTO state(key, value)
            VALUES(?, ?)
            ON CONFLICT(key)
            DO UPDATE SET value = excluded.value
        """, (key, float(value)))

        conn.commit()
        conn.close()


def get_state_str(key, default=""):

    with DB_LOCK:

        conn = db_connect()

        cur = conn.cursor()

        cur.execute(
            "SELECT value FROM state_str WHERE key = ?",
            (key,)
        )

        row = cur.fetchone()

        conn.close()

    if row is None:
        return default

    return str(row[0])


def set_state_str(key, value):

    with DB_LOCK:

        conn = db_connect()

        conn.execute("""
            INSERT INTO state_str(key, value)
            VALUES(?, ?)
            ON CONFLICT(key)
            DO UPDATE SET value = excluded.value
        """, (key, str(value)))

        conn.commit()
        conn.close()


# ============================================================
# TELEGRAM
# ============================================================

def parse_allowed_ids():

    if not ALLOWED_TELEGRAM_IDS:
        return set()

    result = set()

    for item in ALLOWED_TELEGRAM_IDS.split(","):

        item = item.strip()

        if not item:
            continue

        try:
            result.add(int(item))
        except ValueError:
            pass

    return result


ALLOWED_IDS = parse_allowed_ids()


def telegram_send(message, chat_id=None):

    if not TELEGRAM_TOKEN:
        logger.warning("TELEGRAM_TOKEN bulunamadı.")
        return False

    target_chat = chat_id or TELEGRAM_CHAT_ID

    if not target_chat:
        logger.warning("TELEGRAM_CHAT_ID bulunamadı.")
        return False

    url = (
        f"https://api.telegram.org/bot"
        f"{TELEGRAM_TOKEN}/sendMessage"
    )

    payload = {
        "chat_id": target_chat,
        "text": message,
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
    }

    try:

        response = requests.post(
            url,
            json=payload,
            timeout=15
        )

        if response.ok:
            return True

        logger.error(
            f"Telegram gönderim hatası: "
            f"{response.status_code} {response.text}"
        )

    except Exception as e:

        logger.error(
            f"Telegram bağlantı hatası: {e}"
        )

    return False


# ============================================================
# FORMAT HELPERS
# ============================================================

def format_price(value, digits=5):

    try:
        return f"{float(value):.{digits}f}"
    except Exception:
        return "-"


def format_signed_pnl(value):

    try:

        value = float(value)

        if value > 0:
            return f"+${value:.2f}"

        return f"${value:.2f}"

    except Exception:

        return "$0.00"


def now_istanbul():

    return dt.datetime.now(TZ)


# ============================================================
# POSITION / RISK HELPERS
# ============================================================

def get_open_position_stats():

    with DB_LOCK:

        conn = db_connect()

        cur = conn.cursor()

        cur.execute("""
            SELECT
                COUNT(*),
                COALESCE(SUM(risk), 0)
            FROM positions
            WHERE status = 'OPEN'
        """)

        row = cur.fetchone()

        conn.close()

    cnt = int(row[0]) if row and row[0] is not None else 0

    total_open_risk = (
        float(row[1])
        if row and len(row) > 1 and row[1] is not None
        else 0.0
    )

    return cnt, total_open_risk


def atomic_add_position_safely(
    symbol,
    side,
    entry,
    sl,
    tp,
    risk
):

    with DB_LOCK:

        conn = db_connect()

        cur = conn.cursor()

        cur.execute("""
            SELECT
                COUNT(*),
                COALESCE(SUM(risk), 0)
            FROM positions
            WHERE status = 'OPEN'
        """)

        row = cur.fetchone()

        cnt = int(row[0]) if row and row[0] is not None else 0

        total_open_risk = (
            float(row[1])
            if row and len(row) > 1 and row[1] is not None
            else 0.0
        )

        if cnt >= MAX_OPEN_POSITIONS:

            conn.close()

            return False, "MAX_OPEN_POSITIONS"

        if total_open_risk + float(risk) > MAX_TOTAL_OPEN_RISK:

            conn.close()

            return False, "MAX_TOTAL_OPEN_RISK"

        cur.execute("""
            INSERT INTO positions(
                symbol,
                side,
                entry,
                sl,
                tp,
                risk,
                opened_at,
                status
            )
            VALUES(?, ?, ?, ?, ?, ?, ?, 'OPEN')
        """, (
            symbol,
            side,
            float(entry),
            float(sl),
            float(tp),
            float(risk),
            now_istanbul().isoformat()
        ))

        conn.commit()

        position_id = cur.lastrowid

        conn.close()

    return True, position_id


# ============================================================
# MARKET DATA
# ============================================================

def fetch_market_data(
    symbol,
    interval="5m",
    period="5d"
):

    if symbol not in SYMBOL_CONFIG:
        raise ValueError(
            f"Bilinmeyen sembol: {symbol}"
        )

    ticker = SYMBOL_CONFIG[symbol]["yf"]

    try:

        df = yf.download(
            ticker,
            interval=interval,
            period=period,
            progress=False,
            auto_adjust=False,
            threads=False
        )

    except Exception as e:

        logger_strategy.error(
            f"{symbol} veri çekme hatası: {e}"
        )

        return None

    if df is None or df.empty:
        return None

    # Yahoo bazen MultiIndex döndürüyor.
    if isinstance(df.columns, pd.MultiIndex):

        try:
            df.columns = df.columns.get_level_values(0)
        except Exception:
            pass

    required = [
        "Open",
        "High",
        "Low",
        "Close",
        "Volume"
    ]

    for col in required:

        if col not in df.columns:

            if col == "Volume":

                df[col] = 0

            else:

                return None

    df = df[required].copy()

    for col in required:

        df[col] = pd.to_numeric(
            df[col],
            errors="coerce"
        )

    df.dropna(
        subset=[
            "Open",
            "High",
            "Low",
            "Close"
        ],
        inplace=True
    )

    if len(df) < 100:
        return None

    return df


# ============================================================
# INDICATORS
# ============================================================

def ema(series, period):

    return series.ewm(
        span=period,
        adjust=False
    ).mean()


def calculate_rsi(series, period=14):

    delta = series.diff()

    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)

    avg_gain = gain.ewm(
        alpha=1 / period,
        adjust=False
    ).mean()

    avg_loss = loss.ewm(
        alpha=1 / period,
        adjust=False
    ).mean()

    rs = avg_gain / avg_loss.replace(
        0,
        np.nan
    )

    rsi = 100 - (
        100 / (1 + rs)
    )

    return rsi.fillna(50)


def calculate_macd(
    series,
    fast=12,
    slow=26,
    signal=9
):

    fast_ema = ema(
        series,
        fast
    )

    slow_ema = ema(
        series,
        slow
    )

    macd_line = (
        fast_ema - slow_ema
    )

    signal_line = ema(
        macd_line,
        signal
    )

    histogram = (
        macd_line - signal_line
    )

    return (
        macd_line,
        signal_line,
        histogram
    )


def calculate_atr(
    df,
    period=14
):

    high = df["High"]
    low = df["Low"]
    close = df["Close"]

    previous_close = close.shift(1)

    tr1 = high - low

    tr2 = (
        high - previous_close
    ).abs()

    tr3 = (
        low - previous_close
    ).abs()

    true_range = pd.concat(
        [tr1, tr2, tr3],
        axis=1
    ).max(axis=1)

    atr = true_range.ewm(
        alpha=1 / period,
        adjust=False
    ).mean()

    return atr


def add_indicators(df):

    df = df.copy()

    df["EMA9"] = ema(
        df["Close"],
        9
    )

    df["EMA21"] = ema(
        df["Close"],
        21
    )

    df["RSI14"] = calculate_rsi(
        df["Close"],
        14
    )

    (
        df["MACD"],
        df["MACD_SIGNAL"],
        df["MACD_HIST"]
    ) = calculate_macd(
        df["Close"]
    )

    df["ATR14"] = calculate_atr(
        df,
        14
    )

    return df


# ============================================================
# 1H TREND
# ============================================================

def get_higher_timeframe_trend(symbol):

    df_1h = fetch_market_data(
        symbol,
        interval="1h",
        period="30d"
    )

    if df_1h is None or len(df_1h) < 50:

        return "UNKNOWN"

    df_1h = add_indicators(
        df_1h
    )

    last = df_1h.iloc[-1]

    ema9 = float(last["EMA9"])
    ema21 = float(last["EMA21"])

    if ema9 > ema21:
        return "BULLISH"

    if ema9 < ema21:
        return "BEARISH"

    return "NEUTRAL"


# ============================================================
# COOLDOWN
# ============================================================

def can_send_signal(symbol):

    with DB_LOCK:

        conn = db_connect()

        cur = conn.cursor()

        cur.execute("""
            SELECT last_signal
            FROM signal_cooldown
            WHERE symbol = ?
        """, (symbol,))

        row = cur.fetchone()

        conn.close()

    if not row:
        return True

    try:
        last_signal = int(row[0])
    except Exception:
        return True

    elapsed = int(time.time()) - last_signal

    return elapsed >= SIGNAL_COOLDOWN_SECONDS


def mark_signal_sent(symbol):

    with DB_LOCK:

        conn = db_connect()

        conn.execute("""
            INSERT INTO signal_cooldown(
                symbol,
                last_signal
            )
            VALUES(?, ?)
            ON CONFLICT(symbol)
            DO UPDATE SET
                last_signal = excluded.last_signal
        """, (
            symbol,
            int(time.time())
        ))

        conn.commit()
        conn.close()
# ============================================================
# SCALPBOT PRO — PART 2 / 2
# SIGNAL ENGINE + TELEGRAM + COMMAND MENU + FLASK
# ============================================================


# ============================================================
# SIGNAL ENGINE
# ============================================================

def generate_signal(symbol):

    try:
        df = fetch_market_data(
            symbol,
            interval="5m",
            period="5d"
        )

        if df is None or len(df) < 100:
            return None

        df = add_indicators(df)

        last = df.iloc[-1]

        price = float(last["Close"])
        ema9 = float(last["EMA9"])
        ema21 = float(last["EMA21"])
        rsi = float(last["RSI14"])
        macd_hist = float(last["MACD_HIST"])
        atr = float(last["ATR14"])

        if not all(
            np.isfinite(x)
            for x in [
                price,
                ema9,
                ema21,
                rsi,
                macd_hist,
                atr
            ]
        ):
            return None

        if atr <= 0 or price <= 0:
            return None

        trend = get_higher_timeframe_trend(symbol)

        buy_score = 0
        sell_score = 0

        # 1 — EMA 9 / 21
        if ema9 > ema21:
            buy_score += 1
        elif ema9 < ema21:
            sell_score += 1

        # 2 — RSI
        if 50 <= rsi <= 70:
            buy_score += 1
        elif 30 <= rsi < 50:
            sell_score += 1

        # 3 — MACD
        if macd_hist > 0:
            buy_score += 1
        elif macd_hist < 0:
            sell_score += 1

        # 4 — 1H Trend
        if trend == "BULLISH":
            buy_score += 1
        elif trend == "BEARISH":
            sell_score += 1

        # En az 3/4 şart aynı yönde
        if buy_score >= 3 and buy_score > sell_score:
            action = "BUY"

        elif sell_score >= 3 and sell_score > buy_score:
            action = "SELL"

        else:
            return None

        config = SYMBOL_CONFIG[symbol]

        sl_distance = atr * config["sl_atr"]
        tp_distance = atr * config["tp_atr"]

        if action == "BUY":
            sl = price - sl_distance
            tp = price + tp_distance
        else:
            sl = price + sl_distance
            tp = price - tp_distance

        digits = config["digits"]

        return {
            "symbol": symbol,
            "action": action,
            "price": round(price, digits),
            "sl": round(sl, digits),
            "tp": round(tp, digits),
            "rsi": round(rsi, 2),
            "ema9": round(ema9, digits),
            "ema21": round(ema21, digits),
            "macd_hist": macd_hist,
            "atr": atr,
            "trend": trend,
            "buy_score": buy_score,
            "sell_score": sell_score,
            "time": now_istanbul().strftime(
                "%d.%m.%Y %H:%M:%S"
            )
        }

    except Exception as e:

        logger_strategy.error(
            f"{symbol} generate_signal hatası: {e}",
            exc_info=True
        )

        return None


# ============================================================
# SIGNAL MESSAGE
# ============================================================

def format_signal_message(signal):

    symbol = signal["symbol"]

    digits = SYMBOL_CONFIG[symbol]["digits"]

    if signal["action"] == "BUY":
        direction = "🟢 BUY"
    else:
        direction = "🔴 SELL"

    score = max(
        signal["buy_score"],
        signal["sell_score"]
    )

    return f"""
🚨 <b>SCALPRADAR SİNYAL</b>

{direction}

💱 <b>Sembol:</b> {html.escape(symbol)}
⏱ <b>Timeframe:</b> M5
🕐 <b>Zaman:</b> {signal["time"]}

💰 <b>Entry:</b> {format_price(signal["price"], digits)}
🛑 <b>SL:</b> {format_price(signal["sl"], digits)}
🎯 <b>TP:</b> {format_price(signal["tp"], digits)}

📊 <b>Skor:</b> {score}/4

EMA9:
{format_price(signal["ema9"], digits)}

EMA21:
{format_price(signal["ema21"], digits)}

RSI14:
{signal["rsi"]:.2f}

MACD Histogram:
{signal["macd_hist"]:.6f}

ATR14:
{signal["atr"]:.6f}

🕐 <b>1H Trend:</b>
{signal["trend"]}

━━━━━━━━━━━━━━━━━━

⚠️ <b>MANUEL İŞLEM</b>

MT5 otomatik emir:
🔴 KAPALI

Bu yalnızca teknik analiz
sinyalidir. İşlemi kendin
değerlendirip manuel açarsın.
""".strip()


# ============================================================
# SIGNAL PREVIEW
# ============================================================

def get_signal_preview():

    signals = []

    for symbol in SYMBOL_CONFIG:

        try:

            signal = generate_signal(symbol)

            if signal is not None:
                signals.append(signal)

        except Exception as e:

            logger_strategy.error(
                f"{symbol} preview hatası: {e}"
            )

    return signals


# ============================================================
# MARKET STATUS
# ============================================================

def get_market_status(symbol):
    try:
        now = datetime.now(TZ)
        weekday = now.weekday()  # Pazartesi=0, Pazar=6
        current_time = now.time()

        # Hafta sonu
        if weekday >= 5:
            return "KAPALI", "Hafta sonu"

        # EURUSD / GBPUSD / USDJPY
        # Forex piyasası hafta içi 24 saate yakın çalışır.
        if symbol in ["EURUSD", "GBPUSD", "USDJPY"]:
            return "AÇIK", "Forex piyasası aktif"

        # XAUUSD (Altın)
        # Hafta içi aktif, günlük kısa rollover arası bulunabilir.
        if symbol == "XAUUSD":

            # Türkiye saatiyle yaklaşık günlük bakım/rollover aralığı
            rollover_start = time(00, 0)
            rollover_end = time(1, 5)

            if rollover_start <= current_time < rollover_end:
                return "KAPALI", "Günlük rollover/bakım aralığı"

            return "AÇIK", "Altın piyasası aktif"

        return "BİLİNMİYOR", "Tanımsız sembol"

    except Exception as e:
        return "KAPALI", f"Durum kontrol hatası: {e}"

# ============================================================
# TELEGRAM AUTH
# ============================================================

def is_authorized(chat_id):

    if not ALLOWED_IDS:
        return False

    try:
        return int(chat_id) in ALLOWED_IDS

    except Exception:
        return False


# ============================================================
# TELEGRAM COMMAND MENU
# ============================================================

def set_telegram_commands():

    if not TELEGRAM_TOKEN:

        logger.warning(
            "TELEGRAM_TOKEN yok, komut menüsü kurulamadı."
        )

        return False

    url = (
        f"https://api.telegram.org/bot"
        f"{TELEGRAM_TOKEN}/setMyCommands"
    )

    commands = {
        "commands": [
            {
                "command": "start",
                "description": "🤖 SCALPRADAR'ı başlat"
            },
            {
                "command": "durum",
                "description": "📡 Bot ve sistem durumu"
            },
            {
                "command": "bakiye",
                "description": "💰 Demo bakiye"
            },
            {
                "command": "istatistik",
                "description": "📊 İşlem istatistikleri"
            },
            {
                "command": "risk",
                "description": "🛡️ Risk durumunu göster"
            },
            {
                "command": "pozisyonlar",
                "description": "📂 Açık pozisyonlar"
            },
            {
                "command": "fiyat",
                "description": "💹 Güncel piyasa fiyatları"
            },
            {
                "command": "sinyaller",
                "description": "📡 Sinyal motoru durumu"
            },
            {
                "command": "test",
                "description": "🔎 Anlık sinyal taraması"
            },
            {
                "command": "reset",
                "description": "♻️ Bot durumunu sıfırla"
            }
        ]
    }

    try:

        response = requests.post(
            url,
            json=commands,
            timeout=15
        )

        if response.ok:

            logger.info(
                "Telegram komut menüsü başarıyla kuruldu."
            )

            return True

        logger.error(
            "Telegram komut menüsü hatası: "
            f"{response.status_code} "
            f"{response.text}"
        )

    except Exception as e:

        logger.error(
            f"Telegram komut menüsü bağlantı hatası: {e}"
        )

    return False


# ============================================================
# TELEGRAM COMMAND HANDLER
# ============================================================

def handle_telegram_command(
    chat_id,
    command,
    args=""
):

    if not is_authorized(chat_id):

        telegram_send(
            "⛔ <b>Yetkiniz bulunmuyor.</b>",
            chat_id
        )

        return

    command = command.lower().strip()

    # --------------------------------------------------------
    # START
    # --------------------------------------------------------

    if command == "/start":

        telegram_send(
            """
🤖 <b>SCALPRADAR</b>

━━━━━━━━━━━━━━━━━━

🟢 Sinyal Motoru: AKTİF
🧪 Mod: SIMULATION
📊 Analiz: M5
🕐 Trend: 1H

━━━━━━━━━━━━━━━━━━

📈 EMA 9/21
📊 RSI 14
📉 MACD
〽️ ATR
🕐 1H Trend

━━━━━━━━━━━━━━━━━━

💻 MT5 Otomatik Emir:
🔴 KAPALI

Sinyaller Telegram üzerinden
gönderilir.

⚠️ İşlemler MANUEL değerlendirilir.
""",
            chat_id
        )

        return

    # --------------------------------------------------------
    # DURUM
    # --------------------------------------------------------

    if command == "/durum":

        paused = (
            get_state("paused", 0.0) == 1.0
        )

        open_count, open_risk = (
            get_open_position_stats()
        )

        status = (
            "🔴 DURAKLATILDI"
            if paused
            else "🟢 AKTİF"
        )

        telegram_send(
            f"""
📡 <b>SCALPRADAR DURUM</b>

━━━━━━━━━━━━━━━━━━

Bot:
{status}

Sinyal Motoru:
🟢 AKTİF

5M Analiz:
🟢 AKTİF

1H Trend:
🟢 AKTİF

MT5 Otomatik Emir:
🔴 KAPALI

━━━━━━━━━━━━━━━━━━

📂 Açık Pozisyon:
{open_count}

🛡️ Açık Risk:
${open_risk:.2f}

🧪 Mode:
SIMULATION
""",
            chat_id
        )

        return

    # --------------------------------------------------------
    # BAKİYE
    # --------------------------------------------------------

    if command == "/bakiye":

        balance = get_state(
            "balance",
            INITIAL_BALANCE
        )

        telegram_send(
            f"""
💰 <b>DEMO BAKİYE</b>

━━━━━━━━━━━━━━━━━━

💵 Bakiye:
<b>${balance:.2f}</b>

🧪 Mode:
SIMULATION

🔴 Gerçek para kullanılmıyor.
""",
            chat_id
        )

        return

    # --------------------------------------------------------
    # RİSK
    # --------------------------------------------------------

    if command == "/risk":

        open_count, open_risk = (
            get_open_position_stats()
        )

        telegram_send(
            f"""
🛡️ <b>RİSK MERKEZİ</b>

━━━━━━━━━━━━━━━━━━

📉 Günlük Max Zarar:
${MAX_DAILY_LOSS:.2f}

📂 Max Açık Pozisyon:
{MAX_OPEN_POSITIONS}

📂 Mevcut Pozisyon:
{open_count}

💰 Max Toplam Risk:
${MAX_TOTAL_OPEN_RISK:.2f}

⚠️ Mevcut Risk:
${open_risk:.2f}
""",
            chat_id
        )

        return

    # --------------------------------------------------------
    # POZİSYONLAR
    # --------------------------------------------------------

    if command == "/pozisyonlar":

        with DB_LOCK:

            conn = db_connect()
            cur = conn.cursor()

            cur.execute("""
                SELECT
                    symbol,
                    side,
                    entry,
                    sl,
                    tp,
                    risk,
                    opened_at
                FROM positions
                WHERE status = 'OPEN'
                ORDER BY id DESC
            """)

            rows = cur.fetchall()

            conn.close()

        if not rows:

            telegram_send(
                """
📂 <b>AÇIK POZİSYONLAR</b>

Şu anda açık pozisyon yok. 📭
""",
                chat_id
            )

            return

        text = (
            "📂 <b>AÇIK POZİSYONLAR</b>\n\n"
        )

        for row in rows:

            symbol = row[0]
            side = row[1]
            entry = row[2]
            sl = row[3]
            tp = row[4]
            risk = row[5]

            digits = SYMBOL_CONFIG.get(
                symbol,
                {}
            ).get(
                "digits",
                5
            )

            icon = (
                "🟢"
                if side == "BUY"
                else "🔴"
            )

            text += (
                f"{icon} <b>{symbol}</b>\n"
                f"Yön: {side}\n"
                f"Entry: {format_price(entry, digits)}\n"
                f"SL: {format_price(sl, digits)}\n"
                f"TP: {format_price(tp, digits)}\n"
                f"Risk: ${risk:.2f}\n"
                f"━━━━━━━━━━━━\n"
            )

        telegram_send(
            text,
            chat_id
        )

        return

    # --------------------------------------------------------
    # FİYAT
    # --------------------------------------------------------

    if command == "/fiyat":

        text = (
            "💹 <b>GÜNCEL FİYATLAR</b>\n\n"
        )

        for symbol in SYMBOL_CONFIG:

            try:

                ticker = (
                    SYMBOL_CONFIG[symbol]["yf"]
                )

                data = yf.download(
                    ticker,
                    period="1d",
                    interval="1m",
                    progress=False,
                    auto_adjust=False,
                    threads=False
                )

                if data is None or data.empty:
                    continue

                if isinstance(
                    data.columns,
                    pd.MultiIndex
                ):

                    data.columns = (
                        data.columns
                        .get_level_values(0)
                    )

                price = float(
                    data["Close"]
                    .dropna()
                    .iloc[-1]
                )

                digits = (
                    SYMBOL_CONFIG[symbol]["digits"]
                )

                text += (
                    f"💱 <b>{symbol}</b>: "
                    f"{format_price(price, digits)}\n"
                )

            except Exception as e:

                logger.warning(
                    f"/fiyat {symbol}: {e}"
                )

        telegram_send(
            text,
            chat_id
        )

        return

    # --------------------------------------------------------
    # SİNYALLER
    # --------------------------------------------------------

    if command == "/sinyaller":

        telegram_send(
            """
📡 <b>SİNYAL MOTORU</b>

━━━━━━━━━━━━━━━━━━

🟢 Strategy Loop
🟢 5M Analiz
🟢 EMA 9/21
🟢 RSI 14
🟢 MACD
🟢 ATR
🟢 1H Trend

━━━━━━━━━━━━━━━━━━

🎯 Sinyal Kuralı:

4 teknik kontrolden
en az 3 tanesi aynı yönde
olursa sinyal oluşturulur.

━━━━━━━━━━━━━━━━━━

⏱️ Cooldown:
15 dakika

💻 MT5 Auto Trade:
🔴 KAPALI
""",
            chat_id
        )

        return

    # --------------------------------------------------------
    # TEST
    # --------------------------------------------------------

if command == "/test":

        telegram_send(
            """
🔎 <b>SİNYAL TARAMASI</b>

━━━━━━━━━━━━━━━━━━

⏳ EURUSD
⏳ GBPUSD
⏳ USDJPY
⏳ AUDUSD
⏳ USDCAD
⏳ USDCHF
⏳ NZDUSD
⏳ XAUUSD

Piyasa verileri kontrol ediliyor...
""",
            chat_id
        )

        signals = get_signal_preview()

        if not signals:

            telegram_send(
                """
ℹ️ <b>SONUÇ</b>

Şu anda 3/4 şartı sağlayan
bir sinyal bulunamadı.

🟢 Motor çalışıyor.
🔴 Ancak işlem şartları oluşmadı.
""",
                chat_id
            )

            return

        for signal in signals:

            telegram_send(
                format_signal_message(signal),
                chat_id
            )

        return

    # --------------------------------------------------------
    # İSTATİSTİK
    # --------------------------------------------------------

    if command == "/istatistik":

        with DB_LOCK:

            conn = db_connect()
            cur = conn.cursor()

            cur.execute("""
                SELECT
                    COUNT(*),
                    COALESCE(SUM(pnl), 0)
                FROM closed_trades
            """)

            row = cur.fetchone()

            conn.close()

        total_trades = (
            int(row[0])
            if row
            else 0
        )

        total_pnl = (
            float(row[1])
            if row
            else 0.0
        )

        telegram_send(
            f"""
📊 <b>İSTATİSTİK MERKEZİ</b>

━━━━━━━━━━━━━━━━━━

🔢 Toplam İşlem:
{total_trades}

💵 Toplam PnL:
{format_signed_pnl(total_pnl)}

🧪 Mode:
SIMULATION

⚠️ Bu sistem geçmiş performansı
garanti etmez.
""",
            chat_id
        )

        return

    # --------------------------------------------------------
    # RESET
    # --------------------------------------------------------

    if command == "/reset":

        set_state(
            "paused",
            0
        )

        telegram_send(
            """
♻️ <b>SİSTEM RESET</b>

━━━━━━━━━━━━━━━━━━

🟢 Bot aktif edildi.
🟢 Sinyal motoru aktif.
🟢 Telegram aktif.

💻 MT5 Auto Trade:
🔴 KAPALI
""",
            chat_id
        )

        return

    # --------------------------------------------------------
    # UNKNOWN
    # --------------------------------------------------------

    telegram_send(
        """
❓ <b>Bilinmeyen komut.</b>

📋 Menüden bir komut seçebilirsin.

Örnek:
/durum
/test
/sinyaller
/fiyat
""",
        chat_id
    )


# ============================================================
# TELEGRAM POLLER
# ============================================================

def telegram_poller():

    logger.info(
        "Telegram poller başlatıldı."
    )

    offset = None

    while True:

        try:

            if not TELEGRAM_TOKEN:

                logger.warning(
                    "TELEGRAM_TOKEN bulunamadı."
                )

                time.sleep(30)
                continue

            url = (
                f"https://api.telegram.org/bot"
                f"{TELEGRAM_TOKEN}/getUpdates"
            )

            params = {
                "timeout": 25
            }

            if offset is not None:
                params["offset"] = offset

            response = requests.get(
                url,
                params=params,
                timeout=35
            )

            if not response.ok:

                time.sleep(5)
                continue

            data = response.json()

            if not data.get("ok"):

                time.sleep(5)
                continue

            updates = data.get(
                "result",
                []
            )

            for update in updates:

                offset = (
                    update["update_id"] + 1
                )

                message = update.get(
                    "message"
                )

                if not message:
                    continue

                chat = message.get(
                    "chat",
                    {}
                )

                chat_id = chat.get(
                    "id"
                )

                text = message.get(
                    "text",
                    ""
                ).strip()

                if not text.startswith("/"):
                    continue

                parts = text.split(
                    maxsplit=1
                )

                command = parts[0]

                args = (
                    parts[1]
                    if len(parts) > 1
                    else ""
                )

                handle_telegram_command(
                    chat_id,
                    command,
                    args
                )

        except Exception as e:

            logger.error(
                f"Telegram poller hatası: {e}",
                exc_info=True
            )

            time.sleep(5)


# ============================================================
# STRATEGY LOOP
# ============================================================

def bot_loop():

    logger_strategy.info(
        "ScalpBot signal engine devrede."
    )

    while True:

        try:

            if get_state(
                "paused",
                0.0
            ) == 1.0:

                time.sleep(
                    LOOP_SECONDS
                )

                continue

            for symbol in SYMBOL_CONFIG:

                try:

                    market_status, _ = (
                        get_market_status(symbol)
                    )

                    if "KAPALI" in market_status:
                        continue

                    signal = generate_signal(
                        symbol
                    )

                    if signal is None:
                        continue

                    if not can_send_signal(
                        symbol
                    ):
                        continue

                    message = (
                        format_signal_message(
                            signal
                        )
                    )

                    sent = telegram_send(
                        message
                    )

                    if sent:

                        mark_signal_sent(
                            symbol
                        )

                        logger_strategy.info(
                            "SİNYAL GÖNDERİLDİ | "
                            f"{symbol} | "
                            f"{signal['action']} | "
                            f"price={signal['price']}"
                        )

                except Exception as symbol_error:

                    logger_strategy.error(
                        f"{symbol} sinyal hatası: "
                        f"{symbol_error}",
                        exc_info=True
                    )

        except Exception as e:

            logger_strategy.error(
                f"Strategy loop hatası: {e}",
                exc_info=True
            )

        time.sleep(
            LOOP_SECONDS
        )


# ============================================================
# BACKGROUND SERVICES
# ============================================================

_bg_started = False


def start_background_services():

    global _bg_started

    if _bg_started:
        return

    threading.Thread(
        target=bot_loop,
        daemon=True,
        name="strategy-loop"
    ).start()

    threading.Thread(
        target=telegram_poller,
        daemon=True,
        name="telegram-poller"
    ).start()

    _bg_started = True

    logger.info(
        "Background services başlatıldı."
    )


# ============================================================
# FLASK ROUTES
# ============================================================

@app.route("/")
def home():

    return jsonify({
        "bot": APP_NAME,
        "version": VERSION,
        "status": "online",
        "simulation_mode": SIMULATION_MODE,
        "signal_engine": True,
        "mt5_auto_trade": False
    })


@app.route("/ping")
def ping():

    return jsonify({
        "status": "ok",
        "bot": APP_NAME,
        "time": now_istanbul().isoformat()
    })


@app.route("/health")
def health():

    return jsonify({
        "status": "healthy",
        "simulation": SIMULATION_MODE,
        "signal_engine": True,
        "mt5_auto_trade": False
    })


# ============================================================
# STARTUP
# ============================================================

def startup():

    logger.info(
        f"{APP_NAME} {VERSION} başlatılıyor..."
    )

    # Database
    init_db()

    # İlk demo bakiye
    if get_state(
        "balance",
        None
    ) is None:

        set_state(
            "balance",
            INITIAL_BALANCE
        )

    # Telegram komut menüsünü kur
    set_telegram_commands()

    # Arka plan servislerini başlat
    start_background_services()

    logger.info(
        "Startup tamamlandı."
    )


# ============================================================
# MAIN
# ============================================================

if __name__ == "__main__":

    startup()

    app.run(
        host=WEB_HOST,
        port=WEB_PORT,
        debug=False,
        use_reloader=False
    )
