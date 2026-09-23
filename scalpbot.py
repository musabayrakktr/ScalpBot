# ============================================================
# SCALPBOT PRO — TELEGRAM SIGNAL BOT v4.4
# AUTO SCANNER + EMOJI MENU + CLOSED BAR PATCH
# ============================================================
#
# Sinyal botudur.
# GERÇEK EMİR GÖNDERMEZ.
#
# v4.4 değişiklikleri:
# - 6 parite otomatik tarama
# - Kapanmış M5 mumunu kullanma
# - Aynı M5 mumunda tekrar sinyal engeli
# - /oto otomatik tarama aç/kapat
# - /reset otomatik taramayı yeniden açar
# - Emojili Telegram command menu
# - Geliştirilmiş durum ekranı
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
VERSION = "4.4-AUTO-SCANNER"

SIMULATION_MODE = True

TIMEZONE = "Europe/Istanbul"
TZ = ZoneInfo(TIMEZONE)

DB_FILE = os.getenv("DB_FILE", "scalpbot.db")

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN", "").strip()
ALLOWED_TELEGRAM_IDS = os.getenv("ALLOWED_TELEGRAM_IDS", "").strip()
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "").strip()

WEB_HOST = "0.0.0.0"
WEB_PORT = int(os.getenv("PORT", "10000"))

# ============================================================
# RISK
# ============================================================

INITIAL_BALANCE = 3000.0

ACCOUNT_RISK_PERCENT = 0.01

MAX_DAILY_LOSS = 150.0
MAX_OPEN_POSITIONS = 3
MAX_TOTAL_OPEN_RISK = 300.0

COMMISSION_PER_SIDE = 3.50

# Aynı sembolde sinyal gönderimleri arasındaki minimum süre
SIGNAL_COOLDOWN_SECONDS = 900

# Scanner'ın kaç saniyede bir kontrol edeceği
LOOP_SECONDS = 30


# ============================================================
# SYMBOLS — 6 PARİTE
# ============================================================

SYMBOL_CONFIG = {

    "EURUSD": {
        "yf": "EURUSD=X",
        "sl_atr": 1.5,
        "tp_atr": 3.0,
        "digits": 5,
        "contract_size": 100000
    },

    "GBPUSD": {
        "yf": "GBPUSD=X",
        "sl_atr": 1.5,
        "tp_atr": 3.0,
        "digits": 5,
        "contract_size": 100000
    },

    "USDJPY": {
        "yf": "USDJPY=X",
        "sl_atr": 1.5,
        "tp_atr": 3.0,
        "digits": 3,
        "contract_size": 100000
    },

    "USDCAD": {
        "yf": "USDCAD=X",
        "sl_atr": 1.5,
        "tp_atr": 3.0,
        "digits": 5,
        "contract_size": 100000
    },

    "USDCHF": {
        "yf": "USDCHF=X",
        "sl_atr": 1.5,
        "tp_atr": 3.0,
        "digits": 5,
        "contract_size": 100000
    },

    "XAUUSD": {
        "yf": "GC=F",
        "sl_atr": 1.2,
        "tp_atr": 2.5,
        "digits": 2,
        "contract_size": 100
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

if not logger.handlers:
    logger.addHandler(_console)

_file = RotatingFileHandler(
    "scalpbot.log",
    maxBytes=2_000_000,
    backupCount=3,
    encoding="utf-8"
)

_file.setFormatter(_formatter)

if not any(isinstance(h, RotatingFileHandler) for h in logger.handlers):
    logger.addHandler(_file)

if not logger_strategy.handlers:
    logger_strategy.addHandler(_console)
    logger_strategy.addHandler(_file)


# ============================================================
# APP / DATABASE
# ============================================================

app = Flask(__name__)

DB_LOCK = threading.RLock()


def now_istanbul():
    return dt.datetime.now(TZ)


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
# STATE
# ============================================================

def get_state(key, default=0.0):

    with DB_LOCK:

        conn = db_connect()

        try:
            row = conn.execute(
                "SELECT value FROM state WHERE key = ?",
                (key,)
            ).fetchone()

        finally:
            conn.close()

    if row is None or row[0] is None:
        return default

    try:
        return float(row[0])

    except (TypeError, ValueError):
        return default


def set_state(key, value):

    with DB_LOCK:

        conn = db_connect()

        try:

            conn.execute("""
                INSERT INTO state(key, value)
                VALUES(?, ?)
                ON CONFLICT(key)
                DO UPDATE SET value = excluded.value
            """, (
                key,
                float(value)
            ))

            conn.commit()

        finally:
            conn.close()


def get_open_position_stats():

    with DB_LOCK:

        conn = db_connect()

        try:

            row = conn.execute("""
                SELECT COUNT(*),
                       COALESCE(SUM(risk), 0)
                FROM positions
                WHERE status = 'OPEN'
            """).fetchone()

        finally:
            conn.close()

    if not row:
        return 0, 0.0

    return (
        int(row[0] or 0),
        float(row[1] or 0.0)
    )


# ============================================================
# PROCESSED BAR SYSTEM
# ============================================================

def get_processed_bar(symbol):

    with DB_LOCK:

        conn = db_connect()

        try:

            row = conn.execute("""
                SELECT bar_time
                FROM processed_bars
                WHERE symbol = ?
            """, (symbol,)).fetchone()

        finally:
            conn.close()

    if not row:
        return None

    return row[0]


def mark_bar_processed(symbol, bar_time):

    with DB_LOCK:

        conn = db_connect()

        try:

            conn.execute("""
                INSERT INTO processed_bars(symbol, bar_time)
                VALUES(?, ?)

                ON CONFLICT(symbol)
                DO UPDATE SET bar_time = excluded.bar_time
            """, (
                symbol,
                str(bar_time)
            ))

            conn.commit()

        finally:
            conn.close()


# ============================================================
# TELEGRAM
# ============================================================

def parse_allowed_ids():

    result = set()

    for item in ALLOWED_TELEGRAM_IDS.split(","):

        item = item.strip()

        if not item:
            continue

        try:
            result.add(int(item))

        except ValueError:

            logger.warning(
                "ALLOWED_TELEGRAM_IDS geçersiz değer: %s",
                item
            )

    return result


ALLOWED_IDS = parse_allowed_ids()


def is_authorized(chat_id):

    if not ALLOWED_IDS or chat_id is None:
        return False

    try:
        return int(chat_id) in ALLOWED_IDS

    except (TypeError, ValueError):
        return False


def telegram_send(message, chat_id=None):

    if not TELEGRAM_TOKEN:

        logger.error(
            "TELEGRAM_TOKEN tanımlı değil."
        )

        return False

    target_chat = (
        chat_id
        if chat_id is not None
        else TELEGRAM_CHAT_ID
    )

    if not str(target_chat).strip():

        logger.error(
            "Telegram hedef chat ID tanımlı değil."
        )

        return False

    url = (
        f"https://api.telegram.org/"
        f"bot{TELEGRAM_TOKEN}/sendMessage"
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
            timeout=20
        )

        if response.ok:
            return True

        logger.error(
            "Telegram gönderim hatası HTTP %s: %s",
            response.status_code,
            response.text[:500]
        )

    except requests.RequestException:

        logger.exception(
            "Telegram gönderim bağlantı hatası"
        )

    return False


# ============================================================
# TELEGRAM COMMAND MENU
# ============================================================

def set_telegram_commands():

    if not TELEGRAM_TOKEN:

        logger.warning(
            "Komut menüsü kurulamadı: TELEGRAM_TOKEN yok."
        )

        return False

    url = (
        f"https://api.telegram.org/"
        f"bot{TELEGRAM_TOKEN}/setMyCommands"
    )

    commands = {
        "commands": [

            {
                "command": "start",
                "description": "🤖 Botu başlat"
            },

            {
                "command": "durum",
                "description": "📡 Sistem durumunu göster"
            },

            {
                "command": "oto",
                "description": "🤖 Otomatik taramayı aç/kapat"
            },

            {
                "command": "bakiye",
                "description": "💰 Demo bakiyeyi göster"
            },

            {
                "command": "istatistik",
                "description": "📊 İstatistikleri göster"
            },

            {
                "command": "risk",
                "description": "🛡️ Risk durumunu göster"
            },

            {
                "command": "pozisyonlar",
                "description": "📂 Açık pozisyonları göster"
            },

            {
                "command": "fiyat",
                "description": "💹 Güncel fiyatları göster"
            },

            {
                "command": "sinyaller",
                "description": "📈 Sinyal sistemini göster"
            },

            {
                "command": "test",
                "description": "🔎 Şimdi manuel tarama yap"
            },

            {
                "command": "reset",
                "description": "♻️ Sistemi yeniden aktif et"
            },
        ]
    }

    try:

        response = requests.post(
            url,
            json=commands,
            timeout=15
        )

        if not response.ok:

            logger.error(
                "setMyCommands başarısız HTTP %s: %s",
                response.status_code,
                response.text[:300]
            )

            return False

        data = response.json()

        if not data.get("ok"):

            logger.error(
                "setMyCommands Telegram cevabı: %s",
                data
            )

            return False

        logger.info(
            "Telegram komut menüsü başarıyla güncellendi."
        )

        return True

    except (requests.RequestException, ValueError):

        logger.exception(
            "Telegram komut menüsü ayarlanamadı"
        )

        return False


# ============================================================
# FORMATTING
# ============================================================

def format_price(value, digits=5):

    try:
        return f"{float(value):.{digits}f}"

    except (TypeError, ValueError):
        return "-"


def format_signed_pnl(value):

    try:

        value = float(value)

        if value > 0:
            return f"+${value:.2f}"

        return f"${value:.2f}"

    except (TypeError, ValueError):

        return "$0.00"


# ============================================================
# LOT CALCULATION
# ============================================================

def calculate_position_size(symbol, entry, sl):

    try:

        balance = float(
            get_state(
                "balance",
                INITIAL_BALANCE
            )
        )

        risk_cash = (
            balance *
            ACCOUNT_RISK_PERCENT
        )

        cfg = SYMBOL_CONFIG[symbol]

        contract = float(
            cfg["contract_size"]
        )

        distance = abs(
            float(entry) -
            float(sl)
        )

        if distance <= 0 or balance <= 0:
            return 0.01

        if symbol in (
            "EURUSD",
            "GBPUSD",
            "AUDUSD",
            "NZDUSD"
        ):

            loss_per_lot_usd = (
                distance *
                contract
            )

        elif symbol in (
            "USDJPY",
            "USDCAD",
            "USDCHF"
        ):

            loss_per_lot_usd = (
                distance *
                contract /
                max(float(entry), 1e-9)
            )

        elif symbol == "XAUUSD":

            loss_per_lot_usd = (
                distance *
                contract
            )

        else:

            return 0.01

        if (
            loss_per_lot_usd <= 0
            or not np.isfinite(loss_per_lot_usd)
        ):
            return 0.01

        raw_lot = (
            risk_cash /
            loss_per_lot_usd
        )

        lot = (
            np.floor(raw_lot * 100) /
            100
        )

        return float(
            max(0.01, lot)
        )

    except Exception:

        logger.exception(
            "Lot hesaplama hatası (%s)",
            symbol
        )

        return 0.01


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

    except Exception:

        logger_strategy.exception(
            "%s veri çekme hatası",
            symbol
        )

        return None

    if df is None or df.empty:

        logger_strategy.warning(
            "%s için veri yok (%s, %s)",
            symbol,
            interval,
            period
        )

        return None

    if isinstance(
        df.columns,
        pd.MultiIndex
    ):

        df.columns = (
            df.columns
            .get_level_values(0)
        )

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

                logger_strategy.warning(
                    "%s verisinde %s sütunu yok",
                    symbol,
                    col
                )

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

        logger_strategy.warning(
            "%s veri sayısı yetersiz: %s",
            symbol,
            len(df)
        )

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


def calculate_rsi(
    series,
    period=14
):

    delta = series.diff()

    gain = delta.clip(
        lower=0
    )

    loss = -delta.clip(
        upper=0
    )

    avg_gain = gain.ewm(
        alpha=1 / period,
        adjust=False
    ).mean()

    avg_loss = loss.ewm(
        alpha=1 / period,
        adjust=False
    ).mean()

    rs = (
        avg_gain /
        avg_loss.replace(
            0,
            np.nan
        )
    )

    return (
        100 -
        100 / (1 + rs)
    ).fillna(50)


def calculate_macd(
    series,
    fast=12,
    slow=26,
    signal=9
):

    macd_line = (
        ema(series, fast) -
        ema(series, slow)
    )

    signal_line = ema(
        macd_line,
        signal
    )

    histogram = (
        macd_line -
        signal_line
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

    previous_close = (
        df["Close"].shift(1)
    )

    tr = pd.concat(
        [
            df["High"] - df["Low"],

            (
                df["High"] -
                previous_close
            ).abs(),

            (
                df["Low"] -
                previous_close
            ).abs(),
        ],
        axis=1
    ).max(axis=1)

    return tr.ewm(
        alpha=1 / period,
        adjust=False
    ).mean()


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
# HIGHER TIMEFRAME TREND
# ============================================================

def get_higher_timeframe_trend(symbol):

    df = fetch_market_data(
        symbol,
        interval="1h",
        period="30d"
    )

    if df is None or len(df) < 50:
        return "UNKNOWN"

    df = add_indicators(df)

    # Mümkünse kapanmış 1H mumunu kullan
    if len(df) >= 2:
        last = df.iloc[-2]
    else:
        last = df.iloc[-1]

    e9 = float(last["EMA9"])
    e21 = float(last["EMA21"])

    if e9 > e21:
        return "BULLISH"

    if e9 < e21:
        return "BEARISH"

    return "NEUTRAL"


# ============================================================
# COOLDOWN
# ============================================================

def can_send_signal(symbol):

    with DB_LOCK:

        conn = db_connect()

        try:

            row = conn.execute(
                """
                SELECT last_signal
                FROM signal_cooldown
                WHERE symbol = ?
                """,
                (symbol,)
            ).fetchone()

        finally:

            conn.close()

    if not row or row[0] is None:
        return True

    try:

        return (
            int(time.time()) -
            int(row[0])
        ) >= SIGNAL_COOLDOWN_SECONDS

    except (TypeError, ValueError):

        return True


def mark_signal_sent(symbol):

    with DB_LOCK:

        conn = db_connect()

        try:

            conn.execute(
                """
                INSERT INTO signal_cooldown(
                    symbol,
                    last_signal
                )
                VALUES(?, ?)

                ON CONFLICT(symbol)
                DO UPDATE SET
                    last_signal =
                    excluded.last_signal
                """,
                (
                    symbol,
                    int(time.time())
                )
            )

            conn.commit()

        finally:

            conn.close()


# ============================================================
# SIGNAL GENERATOR
# ============================================================

def generate_signal(symbol):

    try:

        df = fetch_market_data(
            symbol,
            interval="5m",
            period="5d"
        )

        if df is None:
            return None

        df = add_indicators(df)

        # ----------------------------------------------------
        # ÖNEMLİ:
        # Son mum halen oluşuyor olabilir.
        # Sinyal için bir önceki, kapanmış M5 mumunu kullanıyoruz.
        # ----------------------------------------------------

        if len(df) < 3:
            return None

        last = df.iloc[-2]

        price = float(
            last["Close"]
        )

        e9 = float(
            last["EMA9"]
        )

        e21 = float(
            last["EMA21"]
        )

        rsi = float(
            last["RSI14"]
        )

        macd_hist = float(
            last["MACD_HIST"]
        )

        atr = float(
            last["ATR14"]
        )

        bar_time = last.name

        if not all(
            np.isfinite(x)
            for x in (
                price,
                e9,
                e21,
                rsi,
                macd_hist,
                atr
            )
        ):

            return None

        if (
            price <= 0
            or atr <= 0
        ):
            return None

        # ----------------------------------------------------
        # HIGHER TIMEFRAME
        # ----------------------------------------------------

        trend = get_higher_timeframe_trend(
            symbol
        )

        buy_score = 0
        sell_score = 0

        # EMA
        if e9 > e21:

            buy_score += 1

        elif e9 < e21:

            sell_score += 1

        # RSI
        if 50 <= rsi <= 70:

            buy_score += 1

        elif 30 <= rsi < 50:

            sell_score += 1

        # MACD
        if macd_hist > 0:

            buy_score += 1

        elif macd_hist < 0:

            sell_score += 1

        # 1H Trend
        if trend == "BULLISH":

            buy_score += 1

        elif trend == "BEARISH":

            sell_score += 1

        # ----------------------------------------------------
        # ACTION
        # ----------------------------------------------------

        if (
            buy_score >= 3
            and buy_score > sell_score
        ):

            action = "BUY"

        elif (
            sell_score >= 3
            and sell_score > buy_score
        ):

            action = "SELL"

        else:

            return {
                "_no_signal": True,
                "bar_time": str(bar_time)
            }

        # ----------------------------------------------------
        # SL / TP
        # ----------------------------------------------------

        cfg = SYMBOL_CONFIG[symbol]

        sl_distance = (
            atr *
            cfg["sl_atr"]
        )

        tp_distance = (
            atr *
            cfg["tp_atr"]
        )

        if action == "BUY":

            sl = (
                price -
                sl_distance
            )

            tp = (
                price +
                tp_distance
            )

        else:

            sl = (
                price +
                sl_distance
            )

            tp = (
                price -
                tp_distance
            )

        # ----------------------------------------------------
        # LOT
        # ----------------------------------------------------

        lot = calculate_position_size(
            symbol,
            price,
            sl
        )

        digits = cfg["digits"]

        return {

            "symbol": symbol,

            "action": action,

            "price": round(
                price,
                digits
            ),

            "sl": round(
                sl,
                digits
            ),

            "tp": round(
                tp,
                digits
            ),

            "lot": lot,

            "rsi": round(
                rsi,
                2
            ),

            "ema9": round(
                e9,
                digits
            ),

            "ema21": round(
                e21,
                digits
            ),

            "macd_hist": macd_hist,

            "atr": atr,

            "trend": trend,

            "buy_score": buy_score,

            "sell_score": sell_score,

            "bar_time": str(
                bar_time
            ),

            "time": now_istanbul().strftime(
                "%d.%m.%Y %H:%M:%S"
            ),
        }

    except Exception:

        logger_strategy.exception(
            "%s generate_signal hatası",
            symbol
        )

        return None


# ============================================================
# SIGNAL MESSAGE
# ============================================================

def format_signal_message(signal):

    symbol = signal["symbol"]

    digits = (
        SYMBOL_CONFIG[
            symbol
        ]["digits"]
    )

    direction = (
        "🟢 BUY"
        if signal["action"] == "BUY"
        else "🔴 SELL"
    )

    score = max(
        signal["buy_score"],
        signal["sell_score"]
    )

    return f"""
🚨 <b>SCALPRADAR PRO</b>

{direction}

💱 <b>Sembol:</b> {html.escape(symbol)}
⏱ <b>Timeframe:</b> M5
🕐 <b>Zaman:</b> {html.escape(signal["time"])}

💰 <b>Entry:</b> {format_price(signal["price"], digits)}
🛑 <b>SL:</b> {format_price(signal["sl"], digits)}
🎯 <b>TP:</b> {format_price(signal["tp"], digits)}
📦 <b>Yaklaşık Lot:</b> {signal["lot"]:.2f}

📊 <b>Sinyal Skoru:</b> {score}/4

📈 <b>EMA9:</b> {format_price(signal["ema9"], digits)}
📉 <b>EMA21:</b> {format_price(signal["ema21"], digits)}
〽️ <b>RSI14:</b> {signal["rsi"]:.2f}
📊 <b>MACD:</b> {signal["macd_hist"]:.6f}
〰️ <b>ATR14:</b> {signal["atr"]:.6f}

🕐 <b>1H Trend:</b> {signal["trend"]}

━━━━━━━━━━━━━━━━━━
🧪 <b>DEMO / SİNYAL MODU</b>
⚠️ Bot gerçek emir göndermez.
⚠️ Lot yaklaşık hesaplamadır.
⚠️ Yahoo Finance fiyatı broker fiyatından farklı olabilir.
""".strip()


# ============================================================
# MANUAL TEST
# ============================================================

def get_signal_preview():

    signals = []

    for symbol in SYMBOL_CONFIG:

        signal = generate_signal(
            symbol
        )

        if (
            signal is not None
            and not signal.get(
                "_no_signal",
                False
            )
        ):

            signals.append(signal)

    return signals


# ============================================================
# MARKET STATUS
# ============================================================

def get_market_status(symbol):

    try:

        if now_istanbul().weekday() >= 5:

            return (
                "KAPALI",
                "Hafta sonu"
            )

        if symbol in SYMBOL_CONFIG:

            return (
                "AÇIK",
                "Hafta içi kontrolü"
            )

        return (
            "BİLİNMİYOR",
            "Tanımsız sembol"
        )

    except Exception as exc:

        logger.exception(
            "Piyasa durumu hatası"
        )

        return (
            "BİLİNMİYOR",
            str(exc)
        )


# ============================================================
# TELEGRAM COMMAND HANDLER
# ============================================================

def handle_telegram_command(
    chat_id,
    command,
    args=""
):

    clean = (
        command
        .split("@")[0]
        .lower()
        .strip()
    )

    logger.info(
        "Komut alındı: %s | chat_id=%s",
        clean,
        chat_id
    )

    if not is_authorized(chat_id):

        telegram_send(
            "⛔ <b>Yetkiniz bulunmuyor.</b>",
            chat_id
        )

        return

    try:

        # ====================================================
        # START
        # ====================================================

        if clean == "/start":

            auto_scan = (
                get_state(
                    "auto_scan",
                    1.0
                ) == 1.0
            )

            auto_text = (
                "🟢 AKTİF"
                if auto_scan
                else "🔴 KAPALI"
            )

            telegram_send(

                "╭━━━ 🤖 <b>SCALPRADAR PRO</b> ━━━╮\n"
                "┃  📡 <b>Akıllı Sinyal Paneli</b>\n"
                "╰━━━━━━━━━━━━━━━━━━━━╯\n\n"

                "🟢 <b>Sistem:</b> Aktif\n"
                f"📡 <b>Otomatik Tarama:</b> {auto_text}\n"
                "🧪 <b>Mod:</b> Demo / Sinyal\n"
                "🛑 <b>Gerçek Emir:</b> Kapalı\n\n"

                "💱 <b>Takip Edilen 6 Sembol</b>\n"
                "EURUSD · GBPUSD · USDJPY\n"
                "USDCAD · USDCHF · XAUUSD\n\n"

                "<b>🧭 KOMUT MERKEZİ</b>\n\n"

                "💹 /fiyat — Güncel fiyatlar\n"
                "🔎 /test — Manuel tarama\n"
                "🤖 /oto — Otomatik tarama\n"
                "📡 /durum — Sistem durumu\n"
                "📈 /sinyaller — Strateji\n"
                "💰 /bakiye — Demo bakiye\n"
                "🛡️ /risk — Risk merkezi\n"
                "📂 /pozisyonlar — Açık kayıtlar\n"
                "📊 /istatistik — İstatistikler\n"
                "♻️ /reset — Sistemi aktif et\n\n"

                "━━━━━━━━━━━━━━━━━━\n"
                "ℹ️ <i>Fiyatlar Yahoo Finance kaynaklıdır. "
                "Broker kotasyonundan farklı olabilir.</i>",

                chat_id
            )


        # ====================================================
        # DURUM
        # ====================================================

        elif clean == "/durum":

            paused = (
                get_state(
                    "paused",
                    0.0
                ) == 1.0
            )

            auto_scan = (
                get_state(
                    "auto_scan",
                    1.0
                ) == 1.0
            )

            count, risk = (
                get_open_position_stats()
            )

            system_text = (
                "🔴 DURAKLATILDI"
                if paused
                else "🟢 AKTİF"
            )

            scanner_text = (
                "🟢 ÇALIŞIYOR"
                if auto_scan and not paused
                else "🔴 KAPALI"
            )

            telegram_send(

                f"📡 <b>SCALPRADAR DURUM</b>\n\n"

                f"🤖 <b>Sistem:</b> {system_text}\n"
                f"📡 <b>Otomatik Scanner:</b> {scanner_text}\n"
                f"🔄 <b>Tarama Aralığı:</b> {LOOP_SECONDS} sn\n"
                f"🕯️ <b>Timeframe:</b> M5\n"
                f"💱 <b>Parite Sayısı:</b> {len(SYMBOL_CONFIG)}\n\n"

                f"📂 <b>Açık Kayıt:</b> {count}/{MAX_OPEN_POSITIONS}\n"
                f"🛡️ <b>Kayıtlı Risk:</b> ${risk:.2f}\n"
                f"💵 <b>Mod:</b> DEMO\n"
                f"🛑 <b>Gerçek Emir:</b> KAPALI",

                chat_id
            )


        # ====================================================
        # OTO
        # ====================================================

        elif clean == "/oto":

            current = (
                get_state(
                    "auto_scan",
                    1.0
                ) == 1.0
            )

            new_state = not current

            set_state(
                "auto_scan",
                1 if new_state else 0
            )

            if new_state:

                telegram_send(

                    "🤖 <b>OTOMATİK TARAMA</b>\n\n"
                    "🟢 <b>AKTİF</b>\n\n"
                    "📡 Bot artık 6 sembolü otomatik "
                    "olarak tarayacak.\n\n"
                    "⏱️ Tarama aralığı: "
                    f"{LOOP_SECONDS} saniye\n"
                    "🕯️ Timeframe: M5\n"
                    "🛑 Gerçek emir: Kapalı",

                    chat_id
                )

            else:

                telegram_send(

                    "🤖 <b>OTOMATİK TARAMA</b>\n\n"
                    "🔴 <b>KAPALI</b>\n\n"
                    "Bot otomatik sinyal taramasını "
                    "durdurdu.\n\n"
                    "🔎 Manuel kontrol için "
                    "/test kullanabilirsin.",

                    chat_id
                )


        # ====================================================
        # BAKİYE
        # ====================================================

        elif clean == "/bakiye":

            balance = get_state(
                "balance",
                INITIAL_BALANCE
            )

            telegram_send(

                f"💰 <b>DEMO BAKİYE</b>\n\n"
                f"💵 <b>${balance:.2f}</b>\n\n"
                "🧪 Gerçek hesap değildir.",

                chat_id
            )


        # ====================================================
        # RISK
        # ====================================================

        elif clean == "/risk":

            count, risk = (
                get_open_position_stats()
            )

            balance = get_state(
                "balance",
                INITIAL_BALANCE
            )

            telegram_send(

                "🛡️ <b>RİSK MERKEZİ</b>\n\n"

                f"💰 Bakiye: ${balance:.2f}\n"
                f"🎯 İşlem başı risk: %{ACCOUNT_RISK_PERCENT * 100:.2f}\n"
                f"📂 Açık kayıt: {count}/{MAX_OPEN_POSITIONS}\n"
                f"⚠️ Açık kayıtlı risk: ${risk:.2f}\n"
                f"🛡️ Toplam risk limiti: ${MAX_TOTAL_OPEN_RISK:.2f}\n"
                f"📉 Günlük zarar limiti: ${MAX_DAILY_LOSS:.2f}\n\n"

                "ℹ️ Bu değerler yerel demo kayıtlarıdır.",

                chat_id
            )


        # ====================================================
        # POZİSYONLAR
        # ====================================================

        elif clean == "/pozisyonlar":

            with DB_LOCK:

                conn = db_connect()

                try:

                    rows = conn.execute(
                        """
                        SELECT
                            symbol,
                            side,
                            entry,
                            sl,
                            tp,
                            risk

                        FROM positions

                        WHERE status = 'OPEN'

                        ORDER BY id DESC
                        """
                    ).fetchall()

                finally:

                    conn.close()

            if not rows:

                telegram_send(
                    "📂 <b>AÇIK POZİSYONLAR</b>\n\n"
                    "Kayıtlı açık pozisyon yok.",
                    chat_id
                )

                return

            text = (
                "📂 <b>AÇIK POZİSYONLAR</b>\n\n"
            )

            for (
                symbol,
                side,
                entry,
                sl,
                tp,
                risk
            ) in rows:

                digits = (
                    SYMBOL_CONFIG
                    .get(
                        symbol,
                        {}
                    )
                    .get(
                        "digits",
                        5
                    )
                )

                icon = (
                    "🟢"
                    if side == "BUY"
                    else "🔴"
                )

                text += (

                    f"{icon} <b>{html.escape(str(symbol))}</b>\n"

                    f"📌 Yön: {html.escape(str(side))}\n"

                    f"💰 Entry: "
                    f"{format_price(entry, digits)}\n"

                    f"🛑 SL: "
                    f"{format_price(sl, digits)}\n"

                    f"🎯 TP: "
                    f"{format_price(tp, digits)}\n"

                    f"⚠️ Risk: "
                    f"${float(risk or 0):.2f}\n\n"
                )

            telegram_send(
                text,
                chat_id
            )


        # ====================================================
        # FIYAT
        # ====================================================

        elif clean == "/fiyat":

            telegram_send(
                "💹 <b>FİYATLAR</b>\n\n"
                "📡 Güncel veriler alınıyor...",
                chat_id
            )

            lines = []

            for symbol, cfg in SYMBOL_CONFIG.items():

                try:

                    data = yf.download(
                        cfg["yf"],
                        period="1d",
                        interval="1m",
                        progress=False,
                        auto_adjust=False,
                        threads=False
                    )

                    if (
                        data is None
                        or data.empty
                    ):

                        lines.append(
                            f"⚪ <b>{symbol}</b>: veri yok"
                        )

                        continue

                    if isinstance(
                        data.columns,
                        pd.MultiIndex
                    ):

                        data.columns = (
                            data.columns
                            .get_level_values(0)
                        )

                    close = (
                        data["Close"]
                        .dropna()
                    )

                    if close.empty:

                        lines.append(
                            f"⚪ <b>{symbol}</b>: veri yok"
                        )

                    else:

                        lines.append(

                            f"💱 <b>{symbol}</b>: "
                            f"{format_price(close.iloc[-1], cfg['digits'])}"
                        )

                except Exception:

                    logger.exception(
                        "/fiyat veri hatası: %s",
                        symbol
                    )

                    lines.append(
                        f"⚠️ <b>{symbol}</b>: hata"
                    )

            telegram_send(

                "💹 <b>GÜNCEL FİYATLAR</b>\n\n" +
                "\n".join(lines),

                chat_id
            )


        # ====================================================
        # SINYALLER
        # ====================================================

        elif clean == "/sinyaller":

            telegram_send(

                "📡 <b>SİNYAL MOTORU</b>\n\n"

                "📊 EMA 9/21\n"
                "〽️ RSI 14\n"
                "📈 MACD\n"
                "🕐 1H Trend\n\n"

                "🎯 En az 3/4 teknik kontrol "
                "aynı yöndeyse sinyal üretilir.\n\n"

                "🕯️ Sinyal hesabında kapanmış "
                "M5 mum kullanılır.\n\n"

                "⚠️ Bu sistem backtest veya "
                "kârlılık garantisi vermez.",

                chat_id
            )


        # ====================================================
        # TEST
        # ====================================================

        elif clean == "/test":

            telegram_send(

                "🔎 <b>MANUEL TARAMA</b>\n\n"
                "📡 6 sembol kontrol ediliyor...\n"
                "⏳ Lütfen bekle.",

                chat_id
            )

            signals = (
                get_signal_preview()
            )

            if not signals:

                telegram_send(

                    "ℹ️ <b>TARAMA SONUCU</b>\n\n"
                    "Şu anda şartları sağlayan "
                    "sinyal bulunamadı.\n\n"
                    "📡 Otomatik scanner çalışmaya "
                    "devam edebilir.",

                    chat_id
                )

            else:

                telegram_send(

                    f"🚨 <b>{len(signals)} SİNYAL BULUNDU</b>",

                    chat_id
                )

                for signal in signals:

                    telegram_send(
                        format_signal_message(signal),
                        chat_id
                    )

                    time.sleep(0.4)


        # ====================================================
        # ISTATISTIK
        # ====================================================

        elif clean == "/istatistik":

            with DB_LOCK:

                conn = db_connect()

                try:

                    row = conn.execute(
                        """
                        SELECT
                            COUNT(*),
                            COALESCE(SUM(pnl), 0)

                        FROM closed_trades
                        """
                    ).fetchone()

                finally:

                    conn.close()

            trades = (
                int(row[0] or 0)
                if row else 0
            )

            pnl = (
                float(row[1] or 0.0)
                if row else 0.0
            )

            telegram_send(

                "📊 <b>İSTATİSTİK</b>\n\n"

                f"📂 Kapanan kayıt: {trades}\n"
                f"💵 Toplam P&amp;L: "
                f"{format_signed_pnl(pnl)}\n\n"

                "ℹ️ Bu veriler yalnızca "
                "yerel veritabanındaki kayıtları gösterir.",

                chat_id
            )


        # ====================================================
        # RESET
        # ====================================================

        elif clean == "/reset":

            set_state(
                "paused",
                0
            )

            set_state(
                "auto_scan",
                1
            )

            telegram_send(

                "♻️ <b>SİSTEM YENİLENDİ</b>\n\n"
                "🟢 Sistem aktif.\n"
                "📡 Otomatik tarama aktif.\n"
                "🔄 6 sembol taranıyor.\n"
                "🛑 Gerçek emir kapalı.",

                chat_id
            )


        # ====================================================
        # UNKNOWN
        # ====================================================

        else:

            telegram_send(

                "❓ <b>Bilinmeyen komut.</b>\n\n"
                "🧭 Komutları görmek için "
                "/start yaz.",

                chat_id
            )

    except Exception:

        logger.exception(
            "Komut işleme hatası: %s",
            clean
        )

        telegram_send(

            "⚠️ <b>Komut işlenirken hata oluştu.</b>\n"
            "Render Logs bölümünü kontrol et.",

            chat_id
        )


# ============================================================
# TELEGRAM POLLER
# ============================================================

def telegram_poller():

    offset = None

    session = requests.Session()

    while True:

        if not TELEGRAM_TOKEN:

            logger.error(
                "Telegram poller beklemede: "
                "TELEGRAM_TOKEN yok."
            )

            time.sleep(30)

            continue

        try:

            url = (
                f"https://api.telegram.org/"
                f"bot{TELEGRAM_TOKEN}/getUpdates"
            )

            params = {
                "timeout": 25
            }

            if offset is not None:

                params["offset"] = offset

            response = session.get(
                url,
                params=params,
                timeout=35
            )

            if response.status_code == 429:

                try:

                    retry_after = int(
                        response.json()
                        .get(
                            "parameters",
                            {}
                        )
                        .get(
                            "retry_after",
                            10
                        )
                    )

                except (
                    ValueError,
                    TypeError
                ):

                    retry_after = 10

                logger.warning(
                    "Telegram 429; %s sn bekleniyor.",
                    retry_after
                )

                time.sleep(
                    max(
                        5,
                        min(
                            retry_after,
                            120
                        )
                    )
                )

                continue

            response.raise_for_status()

            data = response.json()

            if not data.get("ok"):

                logger.error(
                    "getUpdates Telegram hatası: %s",
                    data
                )

                time.sleep(5)

                continue

            for update in data.get(
                "result",
                []
            ):

                offset = (
                    update["update_id"] +
                    1
                )

                message = update.get(
                    "message"
                )

                if not message:
                    continue

                chat_id = (
                    message
                    .get("chat", {})
                    .get("id")
                )

                text = (
                    message
                    .get("text") or ""
                ).strip()

                if not text.startswith("/"):
                    continue

                parts = text.split(
                    maxsplit=1
                )

                args = (
                    parts[1]
                    if len(parts) > 1
                    else ""
                )

                handle_telegram_command(
                    chat_id,
                    parts[0],
                    args
                )

        except requests.RequestException:

            logger.exception(
                "Telegram poller ağ/HTTP hatası"
            )

            time.sleep(8)

        except Exception:

            logger.exception(
                "Telegram poller beklenmeyen hata"
            )

            time.sleep(8)


# ============================================================
# AUTOMATIC SCANNER
# ============================================================

def bot_loop():

    logger.info(
        "📡 Otomatik strateji scanner başladı."
    )

    logger.info(
        "💱 Takip edilen semboller: %s",
        ", ".join(SYMBOL_CONFIG.keys())
    )

    logger.info(
        "⏱️ Scanner aralığı: %s saniye",
        LOOP_SECONDS
    )

    while True:

        try:

            # ------------------------------------------------
            # PAUSED KONTROLÜ
            # ------------------------------------------------

            if (
                get_state(
                    "paused",
                    0.0
                ) == 1.0
            ):

                time.sleep(
                    LOOP_SECONDS
                )

                continue

            # ------------------------------------------------
            # AUTO SCAN KONTROLÜ
            # ------------------------------------------------

            if (
                get_state(
                    "auto_scan",
                    1.0
                ) != 1.0
            ):

                time.sleep(
                    LOOP_SECONDS
                )

                continue

            # ------------------------------------------------
            # 6 SEMBOLÜ TARA
            # ------------------------------------------------

            for symbol in SYMBOL_CONFIG:

                try:

                    market_status, reason = (
                        get_market_status(
                            symbol
                        )
                    )

                    if (
                        market_status ==
                        "KAPALI"
                    ):

                        logger.debug(
                            "%s taranmadı: %s",
                            symbol,
                            reason
                        )

                        continue

                    # ----------------------------------------
                    # SİNYAL ÜRET
                    # ----------------------------------------

                    signal = generate_signal(
                        symbol
                    )

                    if signal is None:

                        continue

                    # ----------------------------------------
                    # BU MUMDA SİNYAL YOKSA
                    # BİR SONRAKİ MUMA KADAR BEKLE
                    # ----------------------------------------

                    if signal.get(
                        "_no_signal",
                        False
                    ):

                        continue

                    bar_time = signal.get(
                        "bar_time"
                    )

                    if not bar_time:

                        continue

                    # ----------------------------------------
                    # AYNI M5 MUMUNU DAHA ÖNCE İŞLEDİ Mİ?
                    # ----------------------------------------

                    previous_bar = (
                        get_processed_bar(
                            symbol
                        )
                    )

                    if (
                        previous_bar ==
                        str(bar_time)
                    ):

                        continue

                    # ----------------------------------------
                    # COOLDOWN
                    # ----------------------------------------

                    if not can_send_signal(
                        symbol
                    ):

                        # Mumu yine de işaretle.
                        # Böylece aynı mum tekrar tekrar
                        # kontrol edilmez.
                        mark_bar_processed(
                            symbol,
                            bar_time
                        )

                        logger.debug(
                            "%s cooldown aktif.",
                            symbol
                        )

                        continue

                    # ----------------------------------------
                    # TELEGRAM
                    # ----------------------------------------

                    success = telegram_send(
                        format_signal_message(
                            signal
                        )
                    )

                    if success:

                        mark_signal_sent(
                            symbol
                        )

                        mark_bar_processed(
                            symbol,
                            bar_time
                        )

                        logger.info(

                            "🚨 %s %s sinyali gönderildi | "
                            "Mum: %s",

                            symbol,
                            signal["action"],
                            bar_time
                        )

                    else:

                        logger.error(

                            "%s sinyali gönderilemedi. "
                            "Cooldown işaretlenmedi.",

                            symbol
                        )

                except Exception:

                    logger.exception(
                        "%s otomatik tarama hatası",
                        symbol
                    )

            # ------------------------------------------------
            # BİR SONRAKİ TUR
            # ------------------------------------------------

        except Exception:

            logger.exception(
                "Ana otomatik scanner hatası"
            )

        time.sleep(
            LOOP_SECONDS
        )


# ============================================================
# FLASK
# ============================================================

@app.route(
    "/",
    methods=["GET"]
)
def home():

    return jsonify({

        "bot": APP_NAME,

        "version": VERSION,

        "status": "online",

        "auto_scanner":
            get_state(
                "auto_scan",
                1.0
            ) == 1.0,

        "symbols":
            list(SYMBOL_CONFIG.keys()),

        "time":
            now_istanbul().isoformat(),

    }), 200


@app.route(
    "/ping",
    methods=["GET"]
)
def ping():

    return jsonify({

        "status": "ok",

        "bot": APP_NAME,

        "time":
            now_istanbul().isoformat()

    }), 200


@app.route(
    "/health",
    methods=["GET"]
)
def health():

    return jsonify({

        "status": "ok",

        "bot": APP_NAME,

        "version": VERSION,

        "simulation_mode":
            SIMULATION_MODE,

        "auto_scanner":
            get_state(
                "auto_scan",
                1.0
            ) == 1.0,

        "time":
            now_istanbul().isoformat(),

    }), 200


# ============================================================
# STARTUP
# ============================================================

_bg_started = False

_bg_lock = threading.Lock()


def start_background_services():

    global _bg_started

    with _bg_lock:

        if _bg_started:
            return

        # -----------------------------------------------
        # AUTOMATIC SCANNER
        # -----------------------------------------------

        threading.Thread(
            target=bot_loop,
            daemon=True,
            name="strategy-loop"
        ).start()

        # -----------------------------------------------
        # TELEGRAM
        # -----------------------------------------------

        threading.Thread(
            target=telegram_poller,
            daemon=True,
            name="telegram-poller"
        ).start()

        _bg_started = True

        logger.info(
            "🚀 Arka plan servisleri başlatıldı."
        )


def startup():

    # -----------------------------------------------
    # DATABASE
    # -----------------------------------------------

    init_db()

    # -----------------------------------------------
    # BALANCE
    # -----------------------------------------------

    if get_state(
        "balance",
        None
    ) is None:

        set_state(
            "balance",
            INITIAL_BALANCE
        )

    # -----------------------------------------------
    # AUTO SCANNER DEFAULT
    # -----------------------------------------------

    if get_state(
        "auto_scan",
        None
    ) is None:

        set_state(
            "auto_scan",
            1
        )

    # -----------------------------------------------
    # PAUSED DEFAULT
    # -----------------------------------------------

    if get_state(
        "paused",
        None
    ) is None:

        set_state(
            "paused",
            0
        )

    # -----------------------------------------------
    # TELEGRAM MENU
    # -----------------------------------------------

    set_telegram_commands()

    # -----------------------------------------------
    # BACKGROUND
    # -----------------------------------------------

    start_background_services()


# ============================================================
# RUN
# ============================================================

if __name__ == "__main__":

    startup()

    app.run(
        host=WEB_HOST,
        port=WEB_PORT,
        debug=False,
        use_reloader=False
    )

else:

    # Gunicorn / Render import ettiğinde
    # background servislerini de başlat.
    startup()
