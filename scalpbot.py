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

    "EURUSD": {
        "yf": "EURUSD=X",
        "sl_atr": 1.5,
        "tp_atr": 3.0,
        "digits": 5,
    },

    "XAUUSD": {
        "yf": "XAU=X",
        "sl_atr": 1.2,
        "tp_atr": 2.5,
        "digits": 2,
    },

    "USDJPY": {
        "yf": "USDJPY=X",
        "sl_atr": 1.5,
        "tp_atr": 3.0,
        "digits": 3,
    },

    "GBPUSD": {
        "yf": "GBPUSD=X",
        "sl_atr": 1.5,
        "tp_atr": 3.0,
        "digits": 5,
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

        trend = get_higher_timeframe_trend(
            symbol
        )

        buy_score = 0
        sell_score = 0

        # ----------------------------------------------------
        # 1 — EMA 9 / 21
        # ----------------------------------------------------

        if ema9 > ema21:
            buy_score += 1

        elif ema9 < ema21:
            sell_score += 1

        # ----------------------------------------------------
        # 2 — RSI
        # ----------------------------------------------------

        if 50 <= rsi <= 70:
            buy_score += 1

        elif 30 <= rsi < 50:
            sell_score += 1

        # ----------------------------------------------------
        # 3 — MACD HISTOGRAM
        # ----------------------------------------------------

        if macd_hist > 0:
            buy_score += 1

        elif macd_hist < 0:
            sell_score += 1

        # ----------------------------------------------------
        # 4 — 1H TREND
        # ----------------------------------------------------

        if trend == "BULLISH":
            buy_score += 1

        elif trend == "BEARISH":
            sell_score += 1

        # ----------------------------------------------------
        # SIGNAL FILTER
        # Minimum 3 / 4
        # ----------------------------------------------------

        if buy_score >= 3 and buy_score > sell_score:

            action = "BUY"

        elif sell_score >= 3 and sell_score > buy_score:

            action = "SELL"

        else:

            return None

        config = SYMBOL_CONFIG[symbol]

        sl_distance = (
            atr * config["sl_atr"]
        )

        tp_distance = (
            atr * config["tp_atr"]
        )

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

    action = signal["action"]

    if action == "BUY":
        direction = "🟢 BUY"
    else:
        direction = "🔴 SELL"

    score = max(
        signal["buy_score"],
        signal["sell_score"]
    )

    message = f"""
🚨 <b>SCALPRADAR SİNYAL</b>

{direction}

💱 <b>Sembol:</b> {html.escape(symbol)}
⏱ <b>Zaman:</b> M5
🕐 <b>Oluşturulma:</b> {signal["time"]}

💰 <b>Entry:</b> {format_price(signal["price"], digits)}
🛑 <b>SL:</b> {format_price(signal["sl"], digits)}
🎯 <b>TP:</b> {format_price(signal["tp"], digits)}

📊 <b>Skor:</b> {score}/4

EMA9: {format_price(signal["ema9"], digits)}
EMA21: {format_price(signal["ema21"], digits)}

RSI14: {signal["rsi"]:.2f}

MACD Hist:
{signal["macd_hist"]:.6f}

ATR14:
{signal["atr"]:.6f}

1H Trend:
{signal["trend"]}

━━━━━━━━━━━━━━

⚠️ <b>MANUEL İŞLEM</b>

MT5 otomatik emir:
🔴 KAPALI

Bu yalnızca teknik analiz
sinyalidir. İşlemi kendin
değerlendirip manuel açarsın.
"""

    return message.strip()


# ============================================================
# SIGNAL PREVIEW
# ============================================================

def get_signal_preview():

    signals = []

    for symbol in SYMBOL_CONFIG:

        try:

            signal = generate_signal(
                symbol
            )

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

        df = fetch_market_data(
            symbol,
            interval="5m",
            period="1d"
        )

        if df is None or df.empty:

            return "KAPALI", "Veri alınamadı"

        return "AÇIK", "Veri aktif"

    except Exception as e:

        return "KAPALI", str(e)


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
# TELEGRAM COMMAND HANDLER
# ============================================================

def handle_telegram_command(
    chat_id,
    command,
    args=""
):

    if not is_authorized(chat_id):

        telegram_send(
            "⛔ Yetkiniz bulunmuyor.",
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
🤖 <b>SCALPBOT PRO</b>

Bot aktif.

📡 Sinyal motoru:
🟢 AKTİF

⏱ Timeframe:
M5

📊 EMA 9/21
📈 RSI 14
📉 MACD
〽️ ATR
🕐 1H Trend

💻 MT5 otomatik emir:
🔴 KAPALI

Komutlar:

/durum
/bakiye
/istatistik
/risk
/pozisyonlar
/fiyat
/sinyaller
/test
/reset
""",
            chat_id
        )

        return

    # --------------------------------------------------------
    # DURUM
    # --------------------------------------------------------

    if command == "/durum":

        paused = (
            get_state(
                "paused",
                0.0
            ) == 1.0
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
🤖 <b>SCALPBOT DURUM</b>

Durum:
{status}

Mode:
🧪 SIMULATION

Sinyal Motoru:
🟢 AKTİF

MT5 Otomatik Emir:
🔴 KAPALI

Açık Pozisyon:
{open_count}

Toplam Açık Risk:
${open_risk:.2f}
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
💰 <b>BALANCE</b>

Bakiye:
${balance:.2f}

Mode:
🧪 SIMULATION
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
🛡 <b>RİSK DURUMU</b>

Günlük maksimum zarar:
${MAX_DAILY_LOSS:.2f}

Maksimum açık pozisyon:
{MAX_OPEN_POSITIONS}

Mevcut açık pozisyon:
{open_count}

Maksimum toplam açık risk:
${MAX_TOTAL_OPEN_RISK:.2f}

Mevcut açık risk:
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
                "📭 Açık pozisyon bulunmuyor.",
                chat_id
            )

            return

        text = (
            "📊 <b>AÇIK POZİSYONLAR</b>\n\n"
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

            text += (
                f"💱 <b>{symbol}</b>\n"
                f"Yön: {side}\n"
                f"Entry: {format_price(entry, digits)}\n"
                f"SL: {format_price(sl, digits)}\n"
                f"TP: {format_price(tp, digits)}\n"
                f"Risk: ${risk:.2f}\n\n"
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

        symbols = list(
            SYMBOL_CONFIG.keys()
        )

        text = (
            "💹 <b>GÜNCEL FİYATLAR</b>\n\n"
        )

        for symbol in symbols:

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
                    data["Close"].dropna().iloc[-1]
                )

                digits = (
                    SYMBOL_CONFIG[symbol]["digits"]
                )

                text += (
                    f"{symbol}: "
                    f"<b>{format_price(price, digits)}</b>\n"
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

🟢 Strategy Loop: AKTİF
🟢 5M Analiz: AKTİF
🟢 EMA 9/21: AKTİF
🟢 RSI 14: AKTİF
🟢 MACD: AKTİF
🟢 ATR: AKTİF
🟢 1H Trend Filtresi: AKTİF

🔴 MT5 Otomatik Emir: KAPALI

Sinyal şartları:

• EMA
• RSI
• MACD
• 1H Trend

En az 3/4 şart aynı yönde
olduğunda sinyal üretilir.

Cooldown:
15 dakika
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
🔎 <b>SİNYAL MOTORU TESTİ</b>

Semboller taranıyor...
⏳ Birkaç saniye sürebilir.
""",
            chat_id
        )

        signals = get_signal_preview()

        if not signals:

            telegram_send(
                """
ℹ️ Şu anda şartları karşılayan
yeni bir sinyal bulunamadı.

Motor çalışıyor ancak
4 şarttan en az 3'ü aynı yönde
değil.
""",
                chat_id
            )

            return

        for signal in signals:

            telegram_send(
                format_signal_message(
                    signal
                ),
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
📊 <b>İSTATİSTİK</b>

Toplam işlem:
{total_trades}

Toplam PnL:
{format_signed_pnl(total_pnl)}

Mode:
🧪 SIMULATION
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
♻
