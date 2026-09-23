# ============================================================
# SCALPBOT PRO — TELEGRAM SIGNAL BOT v4.6
# SELECTIVE STRATEGY + MANUAL POSITION TRACKER
# CLOSED BAR + ADX + ATR FILTER + TP/SL MONITOR
# ============================================================
#
# SİNYAL BOTUDUR.
# GERÇEK BROKER EMRİ GÖNDERMEZ.
#
# v4.6:
# - 6 sembol
# - Kapanmış M5 mum
# - 1H trend filtresi
# - EMA 9/21
# - RSI 14
# - MACD histogram yönü
# - ADX + DI trend gücü
# - ATR volatilite filtresi
# - Minimum 4/5 sinyal skoru
# - 5/5 güçlü sinyal
# - Minimum 1:2 R/R
# - Aynı M5 mumunda tekrar sinyal yok
# - 15 dk cooldown
# - Manuel pozisyon takip sistemi
# - TP/SL otomatik demo kapanış
# - Demo P&L
# - Risk limitleri
# - Telegram profesyonel menü
#
# ÖNEMLİ:
# BOT GERÇEK EMİR AÇMAZ/KAPATMAZ.
# POZİSYONU KULLANICI MANUEL OLARAK AÇAR.
# BOT SADECE YEREL DEMO KAYDI VE FİYAT TAKİBİ YAPAR.
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

from flask import Flask, jsonify, render_template_string



# ============================================================
# CONFIG
# ============================================================

APP_NAME = "ScalpBot Pro"

VERSION = "4.6-SELECTIVE-MANUAL"

SIMULATION_MODE = True

TIMEZONE = "Europe/Istanbul"

TZ = ZoneInfo(TIMEZONE)

DB_FILE = os.getenv(
    "DB_FILE",
    "scalpbot.db"
)

TELEGRAM_TOKEN = os.getenv(
    "TELEGRAM_TOKEN",
    ""
).strip()

ALLOWED_TELEGRAM_IDS = os.getenv(
    "ALLOWED_TELEGRAM_IDS",
    ""
).strip()

TELEGRAM_CHAT_ID = os.getenv(
    "TELEGRAM_CHAT_ID",
    ""
).strip()

WEB_HOST = "0.0.0.0"

WEB_PORT = int(
    os.getenv(
        "PORT",
        "10000"
    )
)


# ============================================================
# STRATEGY CONFIG
# ============================================================

# Ana timeframe
MAIN_TIMEFRAME = "5m"

# Üst timeframe
HIGHER_TIMEFRAME = "1h"


# ------------------------------------------------------------
# EMA
# ------------------------------------------------------------

EMA_FAST = 9
EMA_SLOW = 21


# ------------------------------------------------------------
# RSI
# ------------------------------------------------------------

RSI_PERIOD = 14

# BUY için momentum bölgesi
RSI_BUY_MIN = 52.0
RSI_BUY_MAX = 68.0

# SELL için momentum bölgesi
RSI_SELL_MIN = 32.0
RSI_SELL_MAX = 48.0


# ------------------------------------------------------------
# MACD
# ------------------------------------------------------------

MACD_FAST = 12
MACD_SLOW = 26
MACD_SIGNAL = 9


# ------------------------------------------------------------
# ATR
# ------------------------------------------------------------

ATR_PERIOD = 14

# ATR'nin son 50 mum ortalamasına oranı.
#
# 0.75 altı:
# Piyasa fazla cansız.
#
# 1.80 üstü:
# Piyasa aşırı hareketli olabilir.
#
# Bu değerler başlangıç filtresidir.
# Daha sonra backtest ile optimize edilebilir.
ATR_MIN_RATIO = 0.75
ATR_MAX_RATIO = 1.80

ATR_AVERAGE_PERIOD = 50


# ------------------------------------------------------------
# ADX
# ------------------------------------------------------------

ADX_PERIOD = 14

# ADX bu seviyenin altındaysa
# trend gücü yetersiz kabul edilir.
ADX_MIN = 22.0


# ------------------------------------------------------------
# SIGNAL SCORE
# ------------------------------------------------------------

TOTAL_SCORE = 5

# 5/5 = güçlü
# 4/5 = normal
# 3/5 ve altı = sinyal yok
MIN_SIGNAL_SCORE = 4

STRONG_SIGNAL_SCORE = 5


# ------------------------------------------------------------
# RISK / REWARD
# ------------------------------------------------------------

MIN_RR = 2.0


# ============================================================
# RISK
# ============================================================

INITIAL_BALANCE = 3000.0

ACCOUNT_RISK_PERCENT = 0.01

MAX_DAILY_LOSS = 150.0

MAX_OPEN_POSITIONS = 3

MAX_TOTAL_OPEN_RISK = 300.0

# 1.00 lot başına tek yön komisyon
COMMISSION_PER_SIDE = 3.50

# Aynı sembolde yeni sinyal için bekleme
SIGNAL_COOLDOWN_SECONDS = 900

# Ana loop
LOOP_SECONDS = 30


# ============================================================
# SYMBOLS — 6 SEMBOL
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

logger_strategy = logging.getLogger(
    "strategy"
)

logger.setLevel(
    logging.INFO
)

logger_strategy.setLevel(
    logging.INFO
)

_formatter = logging.Formatter(
    "%(asctime)s | %(levelname)s | "
    "%(name)s | %(message)s"
)

_console = logging.StreamHandler()

_console.setFormatter(
    _formatter
)

if not logger.handlers:

    logger.addHandler(
        _console
    )


_file = RotatingFileHandler(
    "scalpbot.log",
    maxBytes=2_000_000,
    backupCount=3,
    encoding="utf-8"
)

_file.setFormatter(
    _formatter
)

if not any(
    isinstance(
        h,
        RotatingFileHandler
    )
    for h in logger.handlers
):

    logger.addHandler(
        _file
    )


if not logger_strategy.handlers:

    logger_strategy.addHandler(
        _console
    )

    logger_strategy.addHandler(
        _file
    )


# ============================================================
# APP / DATABASE
# ============================================================

app = Flask(__name__)

DB_LOCK = threading.RLock()


def now_istanbul():

    return dt.datetime.now(
        TZ
    )


def db_connect():

    conn = sqlite3.connect(
        DB_FILE,
        timeout=30,
        check_same_thread=False
    )

    conn.execute(
        "PRAGMA journal_mode=WAL"
    )

    return conn


# ============================================================
# DATABASE INIT + MIGRATION
# ============================================================

def ensure_column(
    conn,
    table,
    column,
    definition
):

    try:

        columns = [
            row[1]
            for row in conn.execute(
                f"PRAGMA table_info({table})"
            ).fetchall()
        ]

        if column not in columns:

            conn.execute(
                f"""
                ALTER TABLE {table}
                ADD COLUMN {column} {definition}
                """
            )

            logger.info(
                "DB migration: %s.%s eklendi.",
                table,
                column
            )

    except Exception:

        logger.exception(
            "DB migration hatası: %s.%s",
            table,
            column
        )


def init_db():

    with DB_LOCK:

        conn = db_connect()

        cur = conn.cursor()

        # ----------------------------------------------------
        # STATE
        # ----------------------------------------------------

        cur.execute("""
            CREATE TABLE IF NOT EXISTS state (
                key TEXT PRIMARY KEY,
                value REAL
            )
        """)

        # ----------------------------------------------------
        # STRING STATE
        # ----------------------------------------------------

        cur.execute("""
            CREATE TABLE IF NOT EXISTS state_str (
                key TEXT PRIMARY KEY,
                value TEXT
            )
        """)

        # ----------------------------------------------------
        # OPEN POSITIONS
        # ----------------------------------------------------

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

        # ----------------------------------------------------
        # CLOSED TRADES
        # ----------------------------------------------------

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

        # ----------------------------------------------------
        # SIGNAL COOLDOWN
        # ----------------------------------------------------

        cur.execute("""
            CREATE TABLE IF NOT EXISTS signal_cooldown (
                symbol TEXT PRIMARY KEY,
                last_signal INTEGER
            )
        """)

        # ----------------------------------------------------
        # PROCESSED BARS
        # ----------------------------------------------------

        cur.execute("""
            CREATE TABLE IF NOT EXISTS processed_bars (
                symbol TEXT PRIMARY KEY,
                bar_time TEXT
            )
        """)

        # ----------------------------------------------------
        # MARKET HEALTH
        # ----------------------------------------------------

        cur.execute("""
            CREATE TABLE IF NOT EXISTS market_health (
                symbol TEXT PRIMARY KEY,
                status TEXT,
                message TEXT,
                updated_at TEXT
            )
        """)

        # ----------------------------------------------------
        # v4.5 MIGRATION
        # ----------------------------------------------------

        ensure_column(
            conn,
            "positions",
            "lot",
            "REAL DEFAULT 0.01"
        )

        ensure_column(
            conn,
            "positions",
            "current_price",
            "REAL"
        )

        ensure_column(
            conn,
            "closed_trades",
            "lot",
            "REAL DEFAULT 0.01"
        )

        ensure_column(
            conn,
            "closed_trades",
            "reason",
            "TEXT"
        )

        # ----------------------------------------------------
        # v4.6 STATISTICS MIGRATION
        # ----------------------------------------------------

        ensure_column(
            conn,
            "closed_trades",
            "rr",
            "REAL"
        )

        ensure_column(
            conn,
            "closed_trades",
            "strategy_score",
            "INTEGER"
        )

        ensure_column(
            conn,
            "closed_trades",
            "signal_time",
            "TEXT"
        )

        conn.commit()

        conn.close()


# ============================================================
# STATE
# ============================================================

def get_state(
    key,
    default=0.0
):

    with DB_LOCK:

        conn = db_connect()

        try:

            row = conn.execute(
                """
                SELECT value
                FROM state
                WHERE key = ?
                """,
                (key,)
            ).fetchone()

        finally:

            conn.close()

    if (
        row is None
        or row[0] is None
    ):

        return default

    try:

        return float(
            row[0]
        )

    except (
        TypeError,
        ValueError
    ):

        return default


def set_state(
    key,
    value
):

    with DB_LOCK:

        conn = db_connect()

        try:

            conn.execute(
                """
                INSERT INTO state(
                    key,
                    value
                )
                VALUES(?, ?)

                ON CONFLICT(key)
                DO UPDATE SET
                    value = excluded.value
                """,
                (
                    key,
                    float(value)
                )
            )

            conn.commit()

        finally:

            conn.close()


# ============================================================
# OPEN POSITION STATS
# ============================================================

def get_open_position_stats():

    with DB_LOCK:

        conn = db_connect()

        try:

            row = conn.execute(
                """
                SELECT
                    COUNT(*),
                    COALESCE(
                        SUM(risk),
                        0
                    )
                FROM positions
                WHERE status = 'OPEN'
                """
            ).fetchone()

        finally:

            conn.close()

    if not row:

        return (
            0,
            0.0
        )

    return (
        int(
            row[0] or 0
        ),
        float(
            row[1] or 0.0
        )
    )


def has_open_position(
    symbol
):

    with DB_LOCK:

        conn = db_connect()

        try:

            row = conn.execute(
                """
                SELECT id
                FROM positions
                WHERE symbol = ?
                  AND status = 'OPEN'
                LIMIT 1
                """,
                (symbol,)
            ).fetchone()

        finally:

            conn.close()

    return row is not None


# ============================================================
# DAILY PNL
# ============================================================

def get_today_pnl():

    today = (
        now_istanbul()
        .date()
        .isoformat()
    )

    with DB_LOCK:

        conn = db_connect()

        try:

            rows = conn.execute(
                """
                SELECT
                    closed_at,
                    pnl
                FROM closed_trades
                """
            ).fetchall()

        finally:

            conn.close()

    total = 0.0

    for closed_at, pnl in rows:

        if not closed_at:
            continue

        try:

            parsed = (
                dt.datetime
                .fromisoformat(
                    str(closed_at)
                )
            )

            if (
                parsed.date()
                .isoformat()
                == today
            ):

                total += float(
                    pnl or 0.0
                )

        except Exception:

            continue

    return total


# ============================================================
# PROCESSED BAR SYSTEM
# ============================================================

def get_processed_bar(
    symbol
):

    with DB_LOCK:

        conn = db_connect()

        try:

            row = conn.execute(
                """
                SELECT bar_time
                FROM processed_bars
                WHERE symbol = ?
                """,
                (symbol,)
            ).fetchone()

        finally:

            conn.close()

    if not row:

        return None

    return row[0]


def mark_bar_processed(
    symbol,
    bar_time
):

    with DB_LOCK:

        conn = db_connect()

        try:

            conn.execute(
                """
                INSERT INTO processed_bars(
                    symbol,
                    bar_time
                )
                VALUES(?, ?)

                ON CONFLICT(symbol)
                DO UPDATE SET
                    bar_time =
                    excluded.bar_time
                """,
                (
                    symbol,
                    str(bar_time)
                )
            )

            conn.commit()

        finally:

            conn.close()


# ============================================================
# TELEGRAM AUTH
# ============================================================

def parse_allowed_ids():

    result = set()

    for item in (
        ALLOWED_TELEGRAM_IDS
        .split(",")
    ):

        item = item.strip()

        if not item:
            continue

        try:

            result.add(
                int(item)
            )

        except ValueError:

            logger.warning(
                "ALLOWED_TELEGRAM_IDS "
                "geçersiz değer: %s",
                item
            )

    return result


ALLOWED_IDS = parse_allowed_ids()


def is_authorized(
    chat_id
):

    if (
        not ALLOWED_IDS
        or chat_id is None
    ):

        return False

    try:

        return (
            int(chat_id)
            in ALLOWED_IDS
        )

    except (
        TypeError,
        ValueError
    ):

        return False


# ============================================================
# TELEGRAM SEND
# ============================================================

def telegram_send(
    message,
    chat_id=None
):

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

    if not str(
        target_chat
    ).strip():

        logger.error(
            "Telegram hedef chat ID "
            "tanımlı değil."
        )

        return False

    url = (
        "https://api.telegram.org/"
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
            "Telegram gönderim hatası "
            "HTTP %s: %s",
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
            "Komut menüsü kurulamadı: "
            "TELEGRAM_TOKEN yok."
        )

        return False

    url = (
        "https://api.telegram.org/"
        f"bot{TELEGRAM_TOKEN}/setMyCommands"
    )

    commands = {

        "commands": [

            {
                "command": "start",
                "description":
                    "🤖 Ana paneli aç"
            },

            {
                "command": "durum",
                "description":
                    "📡 Sistem durumunu göster"
            },

            {
                "command": "oto",
                "description":
                    "🤖 Otomatik taramayı aç/kapat"
            },

            {
                "command": "bakiye",
                "description":
                    "💰 Demo bakiyeyi göster"
            },

            {
                "command": "istatistik",
                "description":
                    "📊 Performans istatistikleri"
            },

            {
                "command": "risk",
                "description":
                    "🛡️ Risk merkezini göster"
            },

            {
                "command": "pozisyonlar",
                "description":
                    "📂 Açık pozisyonları göster"
            },

            {
                "command": "pozisyon_ac",
                "description":
                    "🟢 Manuel pozisyon takip et"
            },

            {
                "command": "pozisyon_kapat",
                "description":
                    "🔒 Manuel takip kaydını kapat"
            },

            {
                "command": "fiyat",
                "description":
                    "💹 Güncel fiyatları göster"
            },

            {
                "command": "sinyaller",
                "description":
                    "🧠 Strateji filtrelerini göster"
            },

            {
                "command": "test",
                "description":
                    "🔎 6 sembolü şimdi tara"
            },

            {
                "command": "backtest",
                "description":
                    "🧪 Geçmiş veri testi"
            },

            {
                "command": "reset",
                "description":
                    "♻️ Sistemi yeniden aktif et"
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
                "setMyCommands başarısız "
                "HTTP %s: %s",
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
            "Telegram komut menüsü "
            "başarıyla güncellendi."
        )

        return True

    except (
        requests.RequestException,
        ValueError
    ):

        logger.exception(
            "Telegram komut menüsü ayarlanamadı"
        )

        return False


# ============================================================
# FORMATTING
# ============================================================

def format_price(
    value,
    digits=5
):

    try:

        return (
            f"{float(value):.{digits}f}"
        )

    except (
        TypeError,
        ValueError
    ):

        return "-"


def format_signed_pnl(
    value
):

    try:

        value = float(value)

        if value > 0:

            return (
                f"+${value:.2f}"
            )

        return (
            f"${value:.2f}"
        )

    except (
        TypeError,
        ValueError
    ):

        return "$0.00"


def signal_strength_text(
    score
):

    try:

        score = int(score)

    except (
        TypeError,
        ValueError
    ):

        score = 0

    if score >= 5:

        return (
            "🔥 GÜÇLÜ"
        )

    if score >= 4:

        return (
            "🟡 NORMAL"
        )

    return (
        "⚪ ZAYIF"
    )


# ============================================================
# LOT CALCULATION
# ============================================================

def calculate_position_size(
    symbol,
    entry,
    sl
):

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

        cfg = SYMBOL_CONFIG[
            symbol
        ]

        contract = float(
            cfg["contract_size"]
        )

        distance = abs(
            float(entry) -
            float(sl)
        )

        if (
            distance <= 0
            or balance <= 0
        ):

            return 0.01

        if symbol in (
            "EURUSD",
            "GBPUSD"
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
                max(
                    float(entry),
                    1e-9
                )
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
            or not np.isfinite(
                loss_per_lot_usd
            )
        ):

            return 0.01

        raw_lot = (
            risk_cash /
            loss_per_lot_usd
        )

        lot = (
            np.floor(
                raw_lot * 100
            ) /
            100
        )

        return float(
            max(
                0.01,
                lot
            )
        )

    except Exception:

        logger.exception(
            "Lot hesaplama hatası (%s)",
            symbol
        )

        return 0.01


# ============================================================
# TRADE PNL
# ============================================================

def calculate_trade_pnl(
    symbol,
    side,
    entry,
    exit_price,
    lot
):

    try:

        entry = float(entry)

        exit_price = float(
            exit_price
        )

        lot = float(lot)

        contract = float(
            SYMBOL_CONFIG[
                symbol
            ]["contract_size"]
        )

        if side == "BUY":

            price_difference = (
                exit_price -
                entry
            )

        else:

            price_difference = (
                entry -
                exit_price
            )

        if symbol in (
            "EURUSD",
            "GBPUSD"
        ):

            gross_pnl = (
                price_difference *
                contract *
                lot
            )

        elif symbol in (
            "USDJPY",
            "USDCAD",
            "USDCHF"
        ):

            gross_pnl = (
                price_difference *
                contract *
                lot /
                max(
                    exit_price,
                    1e-9
                )
            )

        elif symbol == "XAUUSD":

            gross_pnl = (
                price_difference *
                contract *
                lot
            )

        else:

            gross_pnl = 0.0

        commission = (
            COMMISSION_PER_SIDE *
            lot *
            2
        )

        return float(
            gross_pnl -
            commission
        )

    except Exception:

        logger.exception(
            "P&L hesaplama hatası: %s",
            symbol
        )

        return 0.0


# ============================================================
# STOP RISK
# ============================================================

def calculate_stop_risk(
    symbol,
    side,
    entry,
    sl,
    lot
):

    try:

        entry = float(entry)

        sl = float(sl)

        lot = float(lot)

        contract = float(
            SYMBOL_CONFIG[
                symbol
            ]["contract_size"]
        )

        distance = abs(
            entry - sl
        )

        if symbol in (
            "EURUSD",
            "GBPUSD"
        ):

            gross_risk = (
                distance *
                contract *
                lot
            )

        elif symbol in (
            "USDJPY",
            "USDCAD",
            "USDCHF"
        ):

            gross_risk = (
                distance *
                contract *
                lot /
                max(
                    entry,
                    1e-9
                )
            )

        elif symbol == "XAUUSD":

            gross_risk = (
                distance *
                contract *
                lot
            )

        else:

            gross_risk = 0.0

        commission = (
            COMMISSION_PER_SIDE *
            lot *
            2
        )

        return float(
            gross_risk +
            commission
        )

    except Exception:

        logger.exception(
            "Risk hesaplama hatası: %s",
            symbol
        )

        return 0.0


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

    ticker = SYMBOL_CONFIG[
        symbol
    ]["yf"]

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

    if (
        df is None
        or df.empty
    ):

        logger_strategy.warning(
            "%s için veri yok "
            "(%s, %s)",
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
                    "%s verisinde %s "
                    "sütunu yok",
                    symbol,
                    col
                )

                return None

    df = df[
        required
    ].copy()

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
# CURRENT PRICE / 1M DATA
# ============================================================

def fetch_latest_price_data(
    symbol
):

    if symbol not in SYMBOL_CONFIG:

        return None

    cfg = SYMBOL_CONFIG[
        symbol
    ]

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

            return None

        if isinstance(
            data.columns,
            pd.MultiIndex
        ):

            data.columns = (
                data.columns
                .get_level_values(0)
            )

        required = [
            "High",
            "Low",
            "Close"
        ]

        for col in required:

            if col not in data.columns:

                return None

            data[col] = pd.to_numeric(
                data[col],
                errors="coerce"
            )

        data.dropna(
            subset=required,
            inplace=True
        )

        if data.empty:

            return None

        last = data.iloc[-1]

        return {

            "high": float(
                last["High"]
            ),

            "low": float(
                last["Low"]
            ),

            "close": float(
                last["Close"]
            ),

            "time": str(
                data.index[-1]
            )
        }

    except Exception:

        logger.exception(
            "%s güncel fiyat "
            "alınamadı.",
            symbol
        )

        return None


# ============================================================
# INDICATORS
# ============================================================

def ema(
    series,
    period
):

    return series.ewm(
        span=period,
        adjust=False
    ).mean()


# ============================================================
# RSI
# ============================================================

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


# ============================================================
# MACD
# ============================================================

def calculate_macd(
    series,
    fast=12,
    slow=26,
    signal=9
):

    macd_line = (
        ema(
            series,
            fast
        )
        -
        ema(
            series,
            slow
        )
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


# ============================================================
# ATR
# ============================================================

def calculate_atr(
    df,
    period=14
):

    previous_close = (
        df["Close"].shift(1)
    )

    tr = pd.concat(
        [

            df["High"] -
            df["Low"],

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
    ).max(
        axis=1
    )

    return tr.ewm(
        alpha=1 / period,
        adjust=False
    ).mean()


# ============================================================
# ADX + DI
# ============================================================

def calculate_adx(
    df,
    period=14
):

    high = df["High"]

    low = df["Low"]

    close = df["Close"]

    # --------------------------------------------------------
    # DIRECTIONAL MOVEMENT
    # --------------------------------------------------------

    up_move = high.diff()

    down_move = -low.diff()

    plus_dm = pd.Series(
        np.where(
            (
                (up_move > down_move)
                &
                (up_move > 0)
            ),
            up_move,
            0.0
        ),
        index=df.index
    )

    minus_dm = pd.Series(
        np.where(
            (
                (down_move > up_move)
                &
                (down_move > 0)
            ),
            down_move,
            0.0
        ),
        index=df.index
    )

    # --------------------------------------------------------
    # TRUE RANGE
    # --------------------------------------------------------

    previous_close = (
        close.shift(1)
    )

    tr = pd.concat(
        [

            high - low,

            (
                high -
                previous_close
            ).abs(),

            (
                low -
                previous_close
            ).abs(),

        ],
        axis=1
    ).max(
        axis=1
    )

    # --------------------------------------------------------
    # WILDER STYLE SMOOTHING
    # --------------------------------------------------------

    smoothed_tr = tr.ewm(
        alpha=1 / period,
        adjust=False
    ).mean()

    smoothed_plus_dm = (
        plus_dm.ewm(
            alpha=1 / period,
            adjust=False
        ).mean()
    )

    smoothed_minus_dm = (
        minus_dm.ewm(
            alpha=1 / period,
            adjust=False
        ).mean()
    )

    # --------------------------------------------------------
    # DI
    # --------------------------------------------------------

    plus_di = (
        100 *
        smoothed_plus_dm /
        smoothed_tr.replace(
            0,
            np.nan
        )
    )

    minus_di = (
        100 *
        smoothed_minus_dm /
        smoothed_tr.replace(
            0,
            np.nan
        )
    )

    # --------------------------------------------------------
    # DX
    # --------------------------------------------------------

    di_sum = (
        plus_di +
        minus_di
    )

    di_difference = (
        plus_di -
        minus_di
    ).abs()

    dx = (
        100 *
        di_difference /
        di_sum.replace(
            0,
            np.nan
        )
    )

    # --------------------------------------------------------
    # ADX
    # --------------------------------------------------------

    adx = dx.ewm(
        alpha=1 / period,
        adjust=False
    ).mean()

    return (
        adx.fillna(0),
        plus_di.fillna(0),
        minus_di.fillna(0)
    )


# ============================================================
# ADD ALL INDICATORS
# ============================================================

def add_indicators(
    df
):

    df = df.copy()

    # --------------------------------------------------------
    # EMA
    # --------------------------------------------------------

    df["EMA9"] = ema(
        df["Close"],
        EMA_FAST
    )

    df["EMA21"] = ema(
        df["Close"],
        EMA_SLOW
    )

    # --------------------------------------------------------
    # RSI
    # --------------------------------------------------------

    df["RSI14"] = (
        calculate_rsi(
            df["Close"],
            RSI_PERIOD
        )
    )

    # --------------------------------------------------------
    # MACD
    # --------------------------------------------------------

    (
        df["MACD"],
        df["MACD_SIGNAL"],
        df["MACD_HIST"]
    ) = calculate_macd(
        df["Close"],
        MACD_FAST,
        MACD_SLOW,
        MACD_SIGNAL
    )

    # --------------------------------------------------------
    # ATR
    # --------------------------------------------------------

    df["ATR14"] = (
        calculate_atr(
            df,
            ATR_PERIOD
        )
    )

    # --------------------------------------------------------
    # ADX
    # --------------------------------------------------------

    (
        df["ADX14"],
        df["DI_PLUS"],
        df["DI_MINUS"]
    ) = calculate_adx(
        df,
        ADX_PERIOD
    )

    # --------------------------------------------------------
    # ATR RELATIVE VOLATILITY
    # --------------------------------------------------------

    df["ATR_AVG"] = (
        df["ATR14"]
        .rolling(
            ATR_AVERAGE_PERIOD
        )
        .mean()
    )

    df["ATR_RATIO"] = (
        df["ATR14"] /
        df["ATR_AVG"].replace(
            0,
            np.nan
        )
    )

    # --------------------------------------------------------
    # MACD HISTOGRAM DIRECTION
    # --------------------------------------------------------

    df["MACD_HIST_PREV"] = (
        df["MACD_HIST"].shift(1)
    )

    # --------------------------------------------------------
    # EMA DISTANCE
    # --------------------------------------------------------

    df["EMA21_DISTANCE_ATR"] = (
        (
            df["Close"] -
            df["EMA21"]
        ).abs() /
        df["ATR14"].replace(
            0,
            np.nan
        )
    )

    return df


# ============================================================
# HIGHER TIMEFRAME TREND
# ============================================================

def get_higher_timeframe_trend(
    symbol
):

    df = fetch_market_data(
        symbol,
        interval=HIGHER_TIMEFRAME,
        period="30d"
    )

    if (
        df is None
        or len(df) < 50
    ):

        return "UNKNOWN"

    df = add_indicators(
        df
    )

    # Kapanmış 1H mum
    last = df.iloc[-2]

    e9 = float(
        last["EMA9"]
    )

    e21 = float(
        last["EMA21"]
    )

    close = float(
        last["Close"]
    )

    if not all(
        np.isfinite(x)
        for x in (
            e9,
            e21,
            close
        )
    ):

        return "UNKNOWN"

    if (
        e9 > e21
        and close > e9
    ):

        return "BULLISH"

    if (
        e9 < e21
        and close < e9
    ):

        return "BEARISH"

    return "NEUTRAL"


# ============================================================
# COOLDOWN
# ============================================================

def can_send_signal(
    symbol
):

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

    if (
        not row
        or row[0] is None
    ):

        return True

    try:

        return (
            int(time.time()) -
            int(row[0])
        ) >= SIGNAL_COOLDOWN_SECONDS

    except (
        TypeError,
        ValueError
    ):

        return True


def mark_signal_sent(
    symbol
):

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
# RISK / REWARD CHECK
# ============================================================

def calculate_rr(
    entry,
    sl,
    tp
):

    try:

        entry = float(entry)

        sl = float(sl)

        tp = float(tp)

        risk_distance = abs(
            entry - sl
        )

        reward_distance = abs(
            tp - entry
        )

        if risk_distance <= 0:

            return 0.0

        return (
            reward_distance /
            risk_distance
        )

    except Exception:

        return 0.0


# ============================================================
# STRATEGY SCORE HELPERS
# ============================================================

def get_signal_score(
    row,
    trend
):

    """
    5 puanlık ana sistem:

    1️⃣ EMA trend hizası
    2️⃣ RSI momentum
    3️⃣ MACD yönü
    4️⃣ 1H trend
    5️⃣ ADX + DI yönü

    ATR filtre olarak kullanılır.
    """

    buy_score = 0

    sell_score = 0

    close = float(
        row["Close"]
    )

    ema9_value = float(
        row["EMA9"]
    )

    ema21_value = float(
        row["EMA21"]
    )

    rsi = float(
        row["RSI14"]
    )

    macd_hist = float(
        row["MACD_HIST"]
    )

    macd_prev = float(
        row["MACD_HIST_PREV"]
    )

    adx = float(
        row["ADX14"]
    )

    di_plus = float(
        row["DI_PLUS"]
    )

    di_minus = float(
        row["DI_MINUS"]
    )

    # --------------------------------------------------------
    # 1 — EMA
    # --------------------------------------------------------

    if (
        ema9_value > ema21_value
        and close > ema9_value
    ):

        buy_score += 1

    elif (
        ema9_value < ema21_value
        and close < ema9_value
    ):

        sell_score += 1

    # --------------------------------------------------------
    # 2 — RSI MOMENTUM
    # --------------------------------------------------------

    if (
        RSI_BUY_MIN <= rsi <= RSI_BUY_MAX
    ):

        buy_score += 1

    elif (
        RSI_SELL_MIN <= rsi <= RSI_SELL_MAX
    ):

        sell_score += 1

    # --------------------------------------------------------
    # 3 — MACD YÖNÜ
    # --------------------------------------------------------

    if (
        macd_hist > 0
        and macd_hist > macd_prev
    ):

        buy_score += 1

    elif (
        macd_hist < 0
        and macd_hist < macd_prev
    ):

        sell_score += 1

    # --------------------------------------------------------
    # 4 — 1H TREND
    # --------------------------------------------------------

    if trend == "BULLISH":

        buy_score += 1

    elif trend == "BEARISH":

        sell_score += 1

    # --------------------------------------------------------
    # 5 — ADX + DI
    # --------------------------------------------------------

    if (
        adx >= ADX_MIN
        and di_plus > di_minus
    ):

        buy_score += 1

    elif (
        adx >= ADX_MIN
        and di_minus > di_plus
    ):

        sell_score += 1

    return (
        buy_score,
        sell_score
    )
# ============================================================
# SCALPBOT PRO v4.6 — 2. KISIM
# ============================================================


# ============================================================
# NO SIGNAL HELPER
# ============================================================

def _no_signal(
    symbol,
    reason="Filtrelerden geçemedi"
):

    return {
        "symbol": symbol,
        "action": None,
        "reason": reason
    }


# ============================================================
# MAIN SIGNAL GENERATOR
# ============================================================

def generate_signal(symbol):

    try:

        df = fetch_market_data(
            symbol,
            interval=MAIN_TIMEFRAME,
            period="5d"
        )

        if df is None:
            return _no_signal(
                symbol,
                "M5 veri alınamadı"
            )

        df = add_indicators(df)

        if len(df) < 100:
            return _no_signal(
                symbol,
                "Yetersiz veri"
            )

        # ----------------------------------------------------
        # SADECE KAPANMIŞ MUM
        # ----------------------------------------------------

        row = df.iloc[-2]

        previous_row = df.iloc[-3]

        # ----------------------------------------------------
        # DEĞERLER
        # ----------------------------------------------------

        price = float(
            row["Close"]
        )

        ema9_value = float(
            row["EMA9"]
        )

        ema21_value = float(
            row["EMA21"]
        )

        rsi = float(
            row["RSI14"]
        )

        macd_hist = float(
            row["MACD_HIST"]
        )

        macd_prev = float(
            row["MACD_HIST_PREV"]
        )

        adx = float(
            row["ADX14"]
        )

        di_plus = float(
            row["DI_PLUS"]
        )

        di_minus = float(
            row["DI_MINUS"]
        )

        atr = float(
            row["ATR14"]
        )

        atr_ratio = float(
            row["ATR_RATIO"]
        )

        ema21_distance_atr = float(
            row["EMA21_DISTANCE_ATR"]
        )

        close = float(
            row["Close"]
        )

        # ----------------------------------------------------
        # SAYISAL KONTROL
        # ----------------------------------------------------

        values = [
            price,
            ema9_value,
            ema21_value,
            rsi,
            macd_hist,
            macd_prev,
            adx,
            di_plus,
            di_minus,
            atr,
            atr_ratio,
            ema21_distance_atr
        ]

        if not all(
            np.isfinite(x)
            for x in values
        ):

            return _no_signal(
                symbol,
                "İndikatör verisi geçersiz"
            )

        if atr <= 0:

            return _no_signal(
                symbol,
                "ATR geçersiz"
            )

        # ----------------------------------------------------
        # HIGHER TIMEFRAME
        # ----------------------------------------------------

        trend = get_higher_timeframe_trend(
            symbol
        )

        # ----------------------------------------------------
        # SCORE
        # ----------------------------------------------------

        buy_score, sell_score = (
            get_signal_score(
                row,
                trend
            )
        )

        # ----------------------------------------------------
        # ATR VOLATILITY FILTER
        # ----------------------------------------------------

        if (
            atr_ratio < ATR_MIN_RATIO
            or atr_ratio > ATR_MAX_RATIO
        ):

            return _no_signal(
                symbol,
                (
                    f"ATR volatilite filtresi "
                    f"uygunsuz ({atr_ratio:.2f})"
                )
            )

        # ----------------------------------------------------
        # ADX FILTER
        # ----------------------------------------------------

        if adx < ADX_MIN:

            return _no_signal(
                symbol,
                (
                    f"ADX düşük "
                    f"({adx:.1f} < {ADX_MIN:.1f})"
                )
            )

        # ----------------------------------------------------
        # EMA TREND DIRECTION
        # ----------------------------------------------------

        bullish_structure = (
            ema9_value > ema21_value
            and close > ema9_value
        )

        bearish_structure = (
            ema9_value < ema21_value
            and close < ema9_value
        )

        # ----------------------------------------------------
        # MACD MOMENTUM
        # ----------------------------------------------------

        bullish_macd = (
            macd_hist > 0
            and macd_hist > macd_prev
        )

        bearish_macd = (
            macd_hist < 0
            and macd_hist < macd_prev
        )

        # ----------------------------------------------------
        # DI DIRECTION
        # ----------------------------------------------------

        bullish_di = (
            di_plus > di_minus
        )

        bearish_di = (
            di_minus > di_plus
        )

        # ----------------------------------------------------
        # CANDLE CONFIRMATION
        # ----------------------------------------------------

        bullish_candle = (
            close > ema9_value
        )

        bearish_candle = (
            close < ema9_value
        )

        # ----------------------------------------------------
        # AŞIRI UZAMIŞ HAREKET FİLTRESİ
        #
        # Fiyat EMA21'den çok fazla uzaklaşmışsa
        # hareketin peşinden koşmuyoruz.
        # ----------------------------------------------------

        EXTENDED_ATR_LIMIT = 2.5

        if (
            ema21_distance_atr >
            EXTENDED_ATR_LIMIT
        ):

            return _no_signal(
                symbol,
                (
                    "Fiyat EMA21'den "
                    "fazla uzak"
                )
            )

        # ----------------------------------------------------
        # BUY / SELL DIRECTION
        # ----------------------------------------------------

        action = None

        score = 0

        # BUY
        if (
            buy_score >= MIN_SIGNAL_SCORE
            and buy_score > sell_score
            and bullish_structure
            and bullish_macd
            and bullish_di
            and trend == "BULLISH"
            and bullish_candle
        ):

            action = "BUY"

            score = buy_score

        # SELL
        elif (
            sell_score >= MIN_SIGNAL_SCORE
            and sell_score > buy_score
            and bearish_structure
            and bearish_macd
            and bearish_di
            and trend == "BEARISH"
            and bearish_candle
        ):

            action = "SELL"

            score = sell_score

        else:

            return _no_signal(
                symbol,
                (
                    f"Skor yetersiz "
                    f"B:{buy_score}/5 "
                    f"S:{sell_score}/5"
                )
            )

        # ----------------------------------------------------
        # ATR BASED SL / TP
        # ----------------------------------------------------

        cfg = SYMBOL_CONFIG[
            symbol
        ]

        sl_distance = (
            atr *
            float(cfg["sl_atr"])
        )

        tp_distance = (
            atr *
            float(cfg["tp_atr"])
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
        # R:R
        # ----------------------------------------------------

        rr = calculate_rr(
            price,
            sl,
            tp
        )

        if rr < MIN_RR:

            return _no_signal(
                symbol,
                (
                    f"R:R yetersiz "
                    f"({rr:.2f})"
                )
            )

        # ----------------------------------------------------
        # LOT
        # ----------------------------------------------------

        lot = calculate_position_size(
            symbol,
            price,
            sl
        )

        # ----------------------------------------------------
        # BAR TIME
        # ----------------------------------------------------

        bar_time = str(
            df.index[-2]
        )

        # ----------------------------------------------------
        # RESULT
        # ----------------------------------------------------

        signal = {

            "symbol": symbol,

            "action": action,

            "price": price,

            "sl": sl,

            "tp": tp,

            "lot": lot,

            "rsi": rsi,

            "ema9": ema9_value,

            "ema21": ema21_value,

            "macd_hist": macd_hist,

            "atr": atr,

            "atr_ratio": atr_ratio,

            "adx": adx,

            "di_plus": di_plus,

            "di_minus": di_minus,

            "trend": trend,

            "buy_score": buy_score,

            "sell_score": sell_score,

            "score": score,

            "strength": signal_strength_text(
                score
            ),

            "rr": rr,

            "bar_time": bar_time,

            "time": now_istanbul().isoformat()
        }

        logger_strategy.info(
            "%s %s | score=%s/5 | "
            "ADX=%.1f | ATR=%.2f | RR=%.2f",
            symbol,
            action,
            score,
            adx,
            atr_ratio,
            rr
        )

        return signal

    except Exception:

        logger_strategy.exception(
            "%s sinyal üretim hatası",
            symbol
        )

        return _no_signal(
            symbol,
            "Sinyal motoru hatası"
        )


# ============================================================
# SIGNAL MESSAGE
# ============================================================

def format_signal_message(
    signal
):

    symbol = signal["symbol"]

    action = signal["action"]

    cfg = SYMBOL_CONFIG[
        symbol
    ]

    digits = cfg["digits"]

    if action == "BUY":

        title_icon = "🟢"

    else:

        title_icon = "🔴"

    score = int(
        signal["score"]
    )

    if score >= 5:

        strength = "🔥 GÜÇLÜ SİNYAL"

    else:

        strength = "🟡 NORMAL SİNYAL"

    return f"""
<b>╔══════════════════════╗</b>
<b>   🧠 SCALPRADAR PRO</b>
<b>╚══════════════════════╝</b>

{title_icon} <b>{action} — {symbol}</b>

<b>📊 SİNYAL ANALİZİ</b>
━━━━━━━━━━━━━━━━━━━━
🎯 Güç: <b>{strength}</b>
🏆 Skor: <b>{score}/5</b>
📐 R:R: <b>1:{signal["rr"]:.2f}</b>

<b>💹 FİYAT</b>
━━━━━━━━━━━━━━━━━━━━
💰 Entry: <code>{format_price(signal["price"], digits)}</code>
🛑 SL: <code>{format_price(signal["sl"], digits)}</code>
🎯 TP: <code>{format_price(signal["tp"], digits)}</code>
📦 Lot: <code>{signal["lot"]:.2f}</code>

<b>📈 İNDİKATÖRLER</b>
━━━━━━━━━━━━━━━━━━━━
EMA9: <code>{signal["ema9"]:.{digits}f}</code>
EMA21: <code>{signal["ema21"]:.{digits}f}</code>
RSI14: <code>{signal["rsi"]:.1f}</code>
MACD: <code>{signal["macd_hist"]:.6f}</code>
ADX14: <code>{signal["adx"]:.1f}</code>
DI+: <code>{signal["di_plus"]:.1f}</code>
DI-: <code>{signal["di_minus"]:.1f}</code>
ATR: <code>{signal["atr"]:.{digits}f}</code>
ATR Oranı: <code>{signal["atr_ratio"]:.2f}</code>

<b>🕐 TREND</b>
━━━━━━━━━━━━━━━━━━━━
M5: <b>{action}</b>
1H: <b>{signal["trend"]}</b>

🧠 <b>Kapanmış mum</b> üzerinden hesaplandı.

<b>👤 MANUEL İŞLEM</b>
━━━━━━━━━━━━━━━━━━━━
Bot <b>GERÇEK EMİR AÇMAZ.</b>

Pozisyonu broker/demo hesabında
kendin açtıktan sonra botta takip
ettirebilirsin:

<code>/pozisyon_ac {symbol} {action} {signal["price"]:.{digits}f} {signal["sl"]:.{digits}f} {signal["tp"]:.{digits}f} {signal["lot"]:.2f}</code>

⚠️ Bu bir teknik analiz sinyalidir.
Kâr garantisi yoktur.
"""


# ============================================================
# SIGNAL PREVIEW
# ============================================================

def get_signal_preview():

    results = []

    for symbol in SYMBOL_CONFIG:

        signal = generate_signal(
            symbol
        )

        results.append(
            signal
        )

    return results


# ============================================================
# MARKET STATUS
# ============================================================

def get_market_status():

    now = now_istanbul()

    # Cumartesi
    if now.weekday() == 5:

        return (
            False,
            "Hafta sonu"
        )

    # Pazar
    if now.weekday() == 6:

        return (
            False,
            "Hafta sonu"
        )

    return (
        True,
        "Piyasa taraması aktif"
    )


def set_market_health(
    symbol,
    status,
    message
):

    with DB_LOCK:

        conn = db_connect()

        try:

            conn.execute(
                """
                INSERT INTO market_health(
                    symbol,
                    status,
                    message,
                    updated_at
                )
                VALUES(?, ?, ?, ?)

                ON CONFLICT(symbol)
                DO UPDATE SET
                    status =
                        excluded.status,
                    message =
                        excluded.message,
                    updated_at =
                        excluded.updated_at
                """,
                (
                    symbol,
                    status,
                    message,
                    now_istanbul().isoformat()
                )
            )

            conn.commit()

        finally:

            conn.close()


# ============================================================
# MANUAL POSITION
# ============================================================

def open_manual_position(
    symbol,
    side,
    entry,
    sl,
    tp,
    lot
):

    symbol = str(
        symbol
    ).upper().strip()

    side = str(
        side
    ).upper().strip()

    try:

        entry = float(entry)

        sl = float(sl)

        tp = float(tp)

        lot = float(lot)

    except (
        TypeError,
        ValueError
    ):

        return {
            "ok": False,
            "message":
                "Fiyat/lot değerleri geçersiz."
        }

    if symbol not in SYMBOL_CONFIG:

        return {
            "ok": False,
            "message":
                "Geçersiz sembol."
        }

    if side not in (
        "BUY",
        "SELL"
    ):

        return {
            "ok": False,
            "message":
                "Yön BUY veya SELL olmalı."
        }

    if (
        entry <= 0
        or sl <= 0
        or tp <= 0
        or lot <= 0
    ):

        return {
            "ok": False,
            "message":
                "Fiyat ve lot pozitif olmalı."
        }

    # --------------------------------------------------------
    # DIRECTION VALIDATION
    # --------------------------------------------------------

    if side == "BUY":

        if not (
            sl < entry < tp
        ):

            return {
                "ok": False,
                "message":
                    "BUY için SL < Entry < TP olmalı."
            }

    else:

        if not (
            tp < entry < sl
        ):

            return {
                "ok": False,
                "message":
                    "SELL için TP < Entry < SL olmalı."
            }

    # --------------------------------------------------------
    # RR
    # --------------------------------------------------------

    rr = calculate_rr(
        entry,
        sl,
        tp
    )

    if rr < MIN_RR:

        return {
            "ok": False,
            "message":
                (
                    f"R:R en az 1:{MIN_RR:.1f} "
                    f"olmalı. Mevcut: 1:{rr:.2f}"
                )
        }

    # --------------------------------------------------------
    # OPEN POSITION LIMIT
    # --------------------------------------------------------

    open_count, open_risk = (
        get_open_position_stats()
    )

    if (
        open_count >=
        MAX_OPEN_POSITIONS
    ):

        return {
            "ok": False,
            "message":
                (
                    f"Maksimum {MAX_OPEN_POSITIONS} "
                    "açık pozisyon sınırına ulaşıldı."
                )
        }

    # --------------------------------------------------------
    # SAME SYMBOL
    # --------------------------------------------------------

    if has_open_position(
        symbol
    ):

        return {
            "ok": False,
            "message":
                (
                    f"{symbol} üzerinde "
                    "zaten açık takip kaydı var."
                )
        }

    # --------------------------------------------------------
    # DAILY LOSS
    # --------------------------------------------------------

    today_pnl = get_today_pnl()

    if today_pnl <= -MAX_DAILY_LOSS:

        return {
            "ok": False,
            "message":
                "Günlük zarar limiti doldu."
        }

    # --------------------------------------------------------
    # RISK
    # --------------------------------------------------------

    risk = calculate_stop_risk(
        symbol,
        side,
        entry,
        sl,
        lot
    )

    if (
        open_risk +
        risk >
        MAX_TOTAL_OPEN_RISK
    ):

        return {
            "ok": False,
            "message":
                (
                    "Toplam açık risk limiti "
                    "aşılacak."
                )
        }

    # --------------------------------------------------------
    # DATABASE
    # --------------------------------------------------------

    opened_at = (
        now_istanbul()
        .isoformat()
    )

    with DB_LOCK:

        conn = db_connect()

        try:

            cur = conn.execute(
                """
                INSERT INTO positions(
                    symbol,
                    side,
                    entry,
                    sl,
                    tp,
                    risk,
                    opened_at,
                    status,
                    lot,
                    current_price
                )
                VALUES(
                    ?, ?, ?, ?, ?, ?,
                    ?, 'OPEN', ?, ?
                )
                """,
                (
                    symbol,
                    side,
                    entry,
                    sl,
                    tp,
                    risk,
                    opened_at,
                    lot,
                    entry
                )
            )

            position_id = cur.lastrowid

            conn.commit()

        finally:

            conn.close()

    return {
        "ok": True,
        "id": position_id,
        "symbol": symbol,
        "side": side,
        "entry": entry,
        "sl": sl,
        "tp": tp,
        "lot": lot,
        "risk": risk,
        "rr": rr,
        "opened_at": opened_at
    }


# ============================================================
# CLOSE POSITION
# ============================================================

def close_position(
    position_id,
    exit_price,
    reason="MANUAL"
):

    try:

        position_id = int(
            position_id
        )

        exit_price = float(
            exit_price
        )

    except (
        TypeError,
        ValueError
    ):

        return {
            "ok": False,
            "message":
                "ID veya çıkış fiyatı geçersiz."
        }

    with DB_LOCK:

        conn = db_connect()

        try:

            row = conn.execute(
                """
                SELECT
                    id,
                    symbol,
                    side,
                    entry,
                    sl,
                    tp,
                    risk,
                    opened_at,
                    lot,
                    status
                FROM positions
                WHERE id = ?
                """,
                (position_id,)
            ).fetchone()

            if not row:

                return {
                    "ok": False,
                    "message":
                        "Pozisyon bulunamadı."
                }

            (
                pid,
                symbol,
                side,
                entry,
                sl,
                tp,
                risk,
                opened_at,
                lot,
                status
            ) = row

            if status != "OPEN":

                return {
                    "ok": False,
                    "message":
                        "Pozisyon zaten kapalı."
                }

            pnl = calculate_trade_pnl(
                symbol,
                side,
                entry,
                exit_price,
                lot
            )

            closed_at = (
                now_istanbul()
                .isoformat()
            )

            rr = calculate_rr(
                entry,
                sl,
                tp
            )

            conn.execute(
                """
                INSERT INTO closed_trades(
                    symbol,
                    side,
                    entry,
                    exit,
                    pnl,
                    opened_at,
                    closed_at,
                    lot,
                    reason,
                    rr
                )
                VALUES(
                    ?, ?, ?, ?, ?, ?,
                    ?, ?, ?, ?
                )
                """,
                (
                    symbol,
                    side,
                    entry,
                    exit_price,
                    pnl,
                    opened_at,
                    closed_at,
                    lot,
                    reason,
                    rr
                )
            )

            conn.execute(
                """
                UPDATE positions
                SET status = 'CLOSED',
                    current_price = ?
                WHERE id = ?
                """,
                (
                    exit_price,
                    position_id
                )
            )

            current_balance = get_state(
                "balance",
                INITIAL_BALANCE
            )

            new_balance = (
                current_balance +
                pnl
            )

            conn.commit()

        finally:

            conn.close()

    set_state(
        "balance",
        new_balance
    )

    return {
        "ok": True,
        "id": position_id,
        "symbol": symbol,
        "side": side,
        "entry": entry,
        "exit": exit_price,
        "pnl": pnl,
        "balance": new_balance,
        "reason": reason,
        "lot": lot
    }


# ============================================================
# CHECK OPEN POSITIONS
# ============================================================

def check_open_positions():

    with DB_LOCK:

        conn = db_connect()

        try:

            rows = conn.execute(
                """
                SELECT
                    id,
                    symbol,
                    side,
                    entry,
                    sl,
                    tp,
                    lot
                FROM positions
                WHERE status = 'OPEN'
                ORDER BY id ASC
                """
            ).fetchall()

        finally:

            conn.close()

    for row in rows:

        (
            position_id,
            symbol,
            side,
            entry,
            sl,
            tp,
            lot
        ) = row

        market = (
            fetch_latest_price_data(
                symbol
            )
        )

        if not market:

            continue

        high = float(
            market["high"]
        )

        low = float(
            market["low"]
        )

        close = float(
            market["close"]
        )

        # ----------------------------------------------------
        # CURRENT PRICE UPDATE
        # ----------------------------------------------------

        with DB_LOCK:

            conn = db_connect()

            try:

                conn.execute(
                    """
                    UPDATE positions
                    SET current_price = ?
                    WHERE id = ?
                      AND status = 'OPEN'
                    """,
                    (
                        close,
                        position_id
                    )
                )

                conn.commit()

            finally:

                conn.close()

        reason = None

        exit_price = None

        # ----------------------------------------------------
        # BUY
        # ----------------------------------------------------

        if side == "BUY":

            sl_hit = (
                low <= sl
            )

            tp_hit = (
                high >= tp
            )

            # Aynı mumda ikisi de olmuşsa
            # muhafazakâr olarak SL.
            if (
                sl_hit
                and tp_hit
            ):

                reason = (
                    "SL_HIT_SAME_CANDLE"
                )

                exit_price = sl

            elif sl_hit:

                reason = "SL_HIT"

                exit_price = sl

            elif tp_hit:

                reason = "TP_HIT"

                exit_price = tp

        # ----------------------------------------------------
        # SELL
        # ----------------------------------------------------

        elif side == "SELL":

            sl_hit = (
                high >= sl
            )

            tp_hit = (
                low <= tp
            )

            if (
                sl_hit
                and tp_hit
            ):

                reason = (
                    "SL_HIT_SAME_CANDLE"
                )

                exit_price = sl

            elif sl_hit:

                reason = "SL_HIT"

                exit_price = sl

            elif tp_hit:

                reason = "TP_HIT"

                exit_price = tp

        # ----------------------------------------------------
        # CLOSE
        # ----------------------------------------------------

        if (
            reason
            and exit_price is not None
        ):

            result = close_position(
                position_id,
                exit_price,
                reason
            )

            if result.get("ok"):

                pnl_text = (
                    format_signed_pnl(
                        result["pnl"]
                    )
                )

                icon = (
                    "🟢"
                    if result["pnl"] > 0
                    else "🔴"
                )

                message = f"""
<b>🔔 POZİSYON SONUÇLANDI</b>

{icon} <b>{symbol} {side}</b>

🆔 ID: <code>{position_id}</code>
💰 Entry: <code>{entry}</code>
🏁 Exit: <code>{exit_price}</code>
📦 Lot: <code>{lot:.2f}</code>

📌 Sebep: <b>{reason}</b>
💵 P&L: <b>{pnl_text}</b>
💰 Demo Bakiye: <b>${result["balance"]:.2f}</b>

⚠️ Bu işlem broker hesabında
bot tarafından açılıp kapatılmadı.
Sadece lokal demo takip kaydıdır.
"""

                telegram_send(
                    message
                )


# ============================================================
# OPEN POSITIONS TEXT
# ============================================================

def get_open_positions_text():

    with DB_LOCK:

        conn = db_connect()

        try:

            rows = conn.execute(
                """
                SELECT
                    id,
                    symbol,
                    side,
                    entry,
                    current_price,
                    sl,
                    tp,
                    lot,
                    risk
                FROM positions
                WHERE status = 'OPEN'
                ORDER BY id ASC
                """
            ).fetchall()

        finally:

            conn.close()

    if not rows:

        return (
            "📂 <b>Açık pozisyon yok.</b>"
        )

    lines = [
        "<b>📂 AÇIK POZİSYONLAR</b>",
        "━━━━━━━━━━━━━━━━━━━━"
    ]

    for row in rows:

        (
            pid,
            symbol,
            side,
            entry,
            current_price,
            sl,
            tp,
            lot,
            risk
        ) = row

        icon = (
            "🟢"
            if side == "BUY"
            else "🔴"
        )

        current = (
            current_price
            if current_price is not None
            else entry
        )

        lines.append(
            f"""
{icon} <b>#{pid} {symbol} {side}</b>
💰 Entry: <code>{entry}</code>
📍 Current: <code>{current}</code>
🛑 SL: <code>{sl}</code>
🎯 TP: <code>{tp}</code>
📦 Lot: <code>{lot:.2f}</code>
🛡️ Risk: <code>${risk:.2f}</code>
"""
        )

    return "\n".join(
        lines
    )


# ============================================================
# ADVANCED STATISTICS
# ============================================================

def get_statistics():

    with DB_LOCK:

        conn = db_connect()

        try:

            rows = conn.execute(
                """
                SELECT
                    symbol,
                    side,
                    pnl,
                    lot
                FROM closed_trades
                ORDER BY id ASC
                """
            ).fetchall()

        finally:

            conn.close()

    if not rows:

        return {
            "count": 0,
            "wins": 0,
            "losses": 0,
            "win_rate": 0.0,
            "total_pnl": 0.0,
            "gross_profit": 0.0,
            "gross_loss": 0.0,
            "profit_factor": 0.0,
            "average_win": 0.0,
            "average_loss": 0.0,
            "max_drawdown": 0.0
        }

    pnls = [
        float(row[2] or 0)
        for row in rows
    ]

    wins = [
        x
        for x in pnls
        if x > 0
    ]

    losses = [
        x
        for x in pnls
        if x < 0
    ]

    gross_profit = sum(
        wins
    )

    gross_loss = abs(
        sum(losses)
    )

    if gross_loss > 0:

        profit_factor = (
            gross_profit /
            gross_loss
        )

    else:

        profit_factor = (
            float("inf")
            if gross_profit > 0
            else 0.0
        )

    # --------------------------------------------------------
    # MAX DRAWDOWN
    # --------------------------------------------------------

    equity = 0.0

    peak = 0.0

    max_drawdown = 0.0

    for pnl in pnls:

        equity += pnl

        peak = max(
            peak,
            equity
        )

        drawdown = (
            peak -
            equity
        )

        max_drawdown = max(
            max_drawdown,
            drawdown
        )

    count = len(
        pnls
    )

    return {
        "count": count,

        "wins": len(
            wins
        ),

        "losses": len(
            losses
        ),

        "win_rate": (
            len(wins) /
            count *
            100
        ),

        "total_pnl": sum(
            pnls
        ),

        "gross_profit":
            gross_profit,

        "gross_loss":
            gross_loss,

        "profit_factor":
            profit_factor,

        "average_win": (
            gross_profit /
            len(wins)
            if wins
            else 0.0
        ),

        "average_loss": (
            sum(losses) /
            len(losses)
            if losses
            else 0.0
        ),

        "max_drawdown":
            max_drawdown
    }


# ============================================================
# BACKTEST
# ============================================================

def run_backtest(
    symbol,
    period="30d"
):

    """
    Basit ve muhafazakâr backtest.

    Önemli:
    - Kapanmış mum kullanılır.
    - Gelecek veri kullanılmaz.
    - Giriş bir sonraki mumun açılışından yapılır.
    - TP/SL aynı mumda ikisi de görülürse SL kabul edilir.
    - Bu bir araştırma aracıdır.
    - Gerçek broker sonucu değildir.
    """

    if symbol not in SYMBOL_CONFIG:

        return {
            "ok": False,
            "message":
                "Geçersiz sembol."
        }

    try:

        df = fetch_market_data(
            symbol,
            interval="5m",
            period=period
        )

        if df is None:

            return {
                "ok": False,
                "message":
                    "Backtest verisi alınamadı."
            }

        df = add_indicators(
            df
        )

        if len(df) < 200:

            return {
                "ok": False,
                "message":
                    "Backtest için veri yetersiz."
            }

        cfg = SYMBOL_CONFIG[
            symbol
        ]

        trades = []

        i = 120

        while i < len(df) - 2:

            row = df.iloc[i]

            previous = df.iloc[i - 1]

            # ------------------------------------------------
            # HTF burada basitleştirilmiştir.
            # Aynı tarihsel bar için lookahead
            # oluşturmamak adına M5 trendi kullanılır.
            # ------------------------------------------------

            close = float(
                row["Close"]
            )

            e9 = float(
                row["EMA9"]
            )

            e21 = float(
                row["EMA21"]
            )

            rsi = float(
                row["RSI14"]
            )

            macd = float(
                row["MACD_HIST"]
            )

            macd_prev = float(
                row["MACD_HIST_PREV"]
            )

            adx = float(
                row["ADX14"]
            )

            di_plus = float(
                row["DI_PLUS"]
            )

            di_minus = float(
                row["DI_MINUS"]
            )

            atr = float(
                row["ATR14"]
            )

            atr_ratio = float(
                row["ATR_RATIO"]
            )

            if not all(
                np.isfinite(x)
                for x in [
                    close,
                    e9,
                    e21,
                    rsi,
                    macd,
                    macd_prev,
                    adx,
                    di_plus,
                    di_minus,
                    atr,
                    atr_ratio
                ]
            ):

                i += 1
                continue

            # ------------------------------------------------
            # VOLATILITY FILTER
            # ------------------------------------------------

            if not (
                ATR_MIN_RATIO
                <= atr_ratio
                <= ATR_MAX_RATIO
            ):

                i += 1
                continue

            if adx < ADX_MIN:

                i += 1
                continue

            buy = (

                e9 > e21

                and close > e9

                and RSI_BUY_MIN
                <= rsi
                <= RSI_BUY_MAX

                and macd > 0

                and macd > macd_prev

                and di_plus > di_minus
            )

            sell = (

                e9 < e21

                and close < e9

                and RSI_SELL_MIN
                <= rsi
                <= RSI_SELL_MAX

                and macd < 0

                and macd < macd_prev

                and di_minus > di_plus
            )

            if not (
                buy or sell
            ):

                i += 1
                continue

            # ------------------------------------------------
            # NEXT BAR OPEN ENTRY
            # ------------------------------------------------

            entry_bar = df.iloc[i + 1]

            entry = float(
                entry_bar["Open"]
            )

            if buy:

                side = "BUY"

                sl = (
                    entry -
                    atr *
                    float(cfg["sl_atr"])
                )

                tp = (
                    entry +
                    atr *
                    float(cfg["tp_atr"])
                )

            else:

                side = "SELL"

                sl = (
                    entry +
                    atr *
                    float(cfg["sl_atr"])
                )

                tp = (
                    entry -
                    atr *
                    float(cfg["tp_atr"])
                )

            rr = calculate_rr(
                entry,
                sl,
                tp
            )

            if rr < MIN_RR:

                i += 1
                continue

            # ------------------------------------------------
            # FIND EXIT
            # ------------------------------------------------

            exit_found = False

            exit_price = None

            exit_reason = None

            j = i + 1

            while j < len(df):

                candle = df.iloc[j]

                high = float(
                    candle["High"]
                )

                low = float(
                    candle["Low"]
                )

                if side == "BUY":

                    sl_hit = (
                        low <= sl
                    )

                    tp_hit = (
                        high >= tp
                    )

                else:

                    sl_hit = (
                        high >= sl
                    )

                    tp_hit = (
                        low <= tp
                    )

                if (
                    sl_hit
                    and tp_hit
                ):

                    exit_price = sl

                    exit_reason = (
                        "SL_SAME_CANDLE"
                    )

                    exit_found = True

                    break

                if sl_hit:

                    exit_price = sl

                    exit_reason = "SL"

                    exit_found = True

                    break

                if tp_hit:

                    exit_price = tp

                    exit_reason = "TP"

                    exit_found = True

                    break

                j += 1

            if not exit_found:

                break

            lot = 0.01

            pnl = calculate_trade_pnl(
                symbol,
                side,
                entry,
                exit_price,
                lot
            )

            trades.append(
                {
                    "side": side,
                    "entry": entry,
                    "exit": exit_price,
                    "pnl": pnl,
                    "reason": exit_reason
                }
            )

            # Exit barından sonra devam et.
            i = j + 1

        # ----------------------------------------------------
        # RESULTS
        # ----------------------------------------------------

        if not trades:

            return {
                "ok": True,
                "symbol": symbol,
                "trades": 0,
                "wins": 0,
                "losses": 0,
                "win_rate": 0.0,
                "pnl": 0.0,
                "message":
                    "Test döneminde sinyal bulunamadı."
            }

        pnls = [
            float(
                t["pnl"]
            )
            for t in trades
        ]

        wins = [
            x
            for x in pnls
            if x > 0
        ]

        losses = [
            x
            for x in pnls
            if x < 0
        ]

        total_pnl = sum(
            pnls
        )

        win_rate = (
            len(wins) /
            len(pnls) *
            100
        )

        return {
            "ok": True,

            "symbol": symbol,

            "trades":
                len(trades),

            "wins":
                len(wins),

            "losses":
                len(losses),

            "win_rate":
                win_rate,

            "pnl":
                total_pnl,

            "average_win":
                (
                    sum(wins) /
                    len(wins)
                    if wins
                    else 0
                ),

            "average_loss":
                (
                    sum(losses) /
                    len(losses)
                    if losses
                    else 0
                )
        }

    except Exception:

        logger.exception(
            "Backtest hatası: %s",
            symbol
        )

        return {
            "ok": False,
            "message":
                "Backtest sırasında hata oluştu."
        }


# ============================================================
# TELEGRAM POLLING
# ============================================================

def telegram_get_updates(
    offset=None
):

    if not TELEGRAM_TOKEN:

        return []

    url = (
        "https://api.telegram.org/"
        f"bot{TELEGRAM_TOKEN}/getUpdates"
    )

    params = {
        "timeout": 25
    }

    if offset is not None:

        params["offset"] = offset

    try:

        response = requests.get(
            url,
            params=params,
            timeout=35
        )

        if response.status_code == 429:

            retry_after = 5

            try:

                retry_after = int(
                    response.json()
                    .get(
                        "parameters",
                        {}
                    )
                    .get(
                        "retry_after",
                        5
                    )
                )

            except Exception:

                pass

            time.sleep(
                retry_after
            )

            return []

        response.raise_for_status()

        data = response.json()

        if not data.get("ok"):

            return []

        return data.get(
            "result",
            []
        )

    except Exception:

        logger.exception(
            "Telegram polling hatası"
        )

        time.sleep(3)

        return []


# ============================================================
# TELEGRAM COMMAND HANDLER
# ============================================================

def handle_telegram_update(
    update
):

    message = update.get(
        "message"
    )

    if not message:

        return

    chat = message.get(
        "chat",
        {}
    )

    chat_id = chat.get(
        "id"
    )

    if not is_authorized(
        chat_id
    ):

        logger.warning(
            "Yetkisiz Telegram ID: %s",
            chat_id
        )

        telegram_send(
            "⛔ Yetkiniz bulunmuyor.",
            chat_id
        )

        return

    text = (
        message.get(
            "text",
            ""
        )
        .strip()
    )

    if not text:

        return

    parts = text.split()

    command = (
        parts[0]
        .split("@")[0]
        .lower()
    )

    args = parts[1:]


    # ========================================================
    # /START
    # ========================================================

    if command == "/start":

        balance = get_state(
            "balance",
            INITIAL_BALANCE
        )

        auto_scan = int(
            get_state(
                "auto_scan",
                1
            )
        )

        open_count, open_risk = (
            get_open_position_stats()
        )

        status = (
            "🟢 AKTİF"
            if auto_scan
            else "⏸️ DURAKLATILDI"
        )

        msg = f"""
<b>╔════════════════════════════╗</b>
<b>       🤖 SCALPBOT PRO</b>
<b>          v4.6</b>
<b>╚════════════════════════════╝</b>

<b>🧠 SELECTIVE SIGNAL ENGINE</b>

📡 Sistem: <b>🟢 ONLINE</b>
🔎 Tarama: <b>{status}</b>
💼 Mod: <b>DEMO / MANUEL</b>

<b>📊 STRATEJİ</b>
━━━━━━━━━━━━━━━━━━━━
⏱️ M5 kapalı mum
📈 EMA 9 / 21
📊 RSI 14
📉 MACD momentum
💪 ADX + DI
⚡ ATR volatilite
🕐 1H trend filtresi
🎯 Minimum R:R 1:2
🏆 Minimum skor 4/5

<b>💹 SEMBOLLER</b>
━━━━━━━━━━━━━━━━━━━━
EURUSD • GBPUSD • USDJPY
USDCAD • USDCHF • XAUUSD

<b>💰 DEMO</b>
━━━━━━━━━━━━━━━━━━━━
Bakiye: <b>${balance:.2f}</b>
Açık: <b>{open_count}</b>
Risk: <b>${open_risk:.2f}</b>

<b>📋 KOMUTLAR</b>
━━━━━━━━━━━━━━━━━━━━
/durum — 📡 Sistem durumu
/oto — 🤖 Tarama aç/kapat
/bakiye — 💰 Bakiye
/istatistik — 📊 Performans
/risk — 🛡️ Risk merkezi
/pozisyonlar — 📂 Pozisyonlar
/pozisyon_ac — 🟢 Manuel takip
/pozisyon_kapat — 🔒 Pozisyon kapat
/fiyat — 💹 Fiyatlar
/sinyaller — 🧠 Strateji
/test — 🔎 Şimdi tara
/backtest — 🧪 Geçmiş test
/reset — ♻️ Sistemi aktif et

⚠️ <b>BOT GERÇEK EMİR GÖNDERMEZ.</b>
"""

        telegram_send(
            msg,
            chat_id
        )

        return


    # ========================================================
    # /DURUM
    # ========================================================

    if command == "/durum":

        auto_scan = int(
            get_state(
                "auto_scan",
                1
            )
        )

        balance = get_state(
            "balance",
            INITIAL_BALANCE
        )

        paused = int(
            get_state(
                "paused",
                0
            )
        )

        count, risk = (
            get_open_position_stats()
        )

        today_pnl = get_today_pnl()

        market_open, market_msg = (
            get_market_status()
        )

        msg = f"""
<b>📡 SCALPBOT DURUM MERKEZİ</b>

🟢 Sistem: <b>ONLINE</b>
🤖 Otomatik tarama:
<b>{"AÇIK" if auto_scan else "KAPALI"}</b>

⏸️ Sistem:
<b>{"DURAKLATILDI" if paused else "AKTİF"}</b>

🌐 Piyasa:
<b>{"AÇIK" if market_open else "KAPALI"}</b>
{market_msg}

⏱️ Ana TF: <b>M5</b>
🕐 Trend TF: <b>1H</b>
🔎 Sembol: <b>6</b>

📂 Açık pozisyon:
<b>{count}/{MAX_OPEN_POSITIONS}</b>

🛡️ Açık risk:
<b>${risk:.2f}</b>

💰 Demo bakiye:
<b>${balance:.2f}</b>

📅 Bugünkü P&L:
<b>{format_signed_pnl(today_pnl)}</b>

⚠️ Manuel işlem sistemi aktiftir.
"""

        telegram_send(
            msg,
            chat_id
        )

        return


    # ========================================================
    # /OTO
    # ========================================================

    if command == "/oto":

        current = int(
            get_state(
                "auto_scan",
                1
            )
        )

        new_value = (
            0
            if current
            else 1
        )

        set_state(
            "auto_scan",
            new_value
        )

        if new_value:

            msg = """
<b>🤖 OTOMATİK TARAMA AÇILDI</b>

🟢 6 sembol taranıyor.
🧠 Selective Strategy aktif.
🏆 Minimum 4/5 skor.
💪 ADX filtresi aktif.
⚡ ATR filtresi aktif.

⚠️ Gerçek emir açılmaz.
"""

        else:

            msg = """
<b>⏸️ OTOMATİK TARAMA KAPATILDI</b>

Bot yeni otomatik sinyal
göndermeyecek.

📂 Açık manuel takip kayıtlarının
TP/SL kontrolü devam eder.

🔎 İstersen /test ile
manuel tarama yapabilirsin.
"""

        telegram_send(
            msg,
            chat_id
        )

        return


    # ========================================================
    # /BAKİYE
    # ========================================================

    if command == "/bakiye":

        balance = get_state(
            "balance",
            INITIAL_BALANCE
        )

        today_pnl = get_today_pnl()

        msg = f"""
<b>💰 DEMO BAKİYE</b>

💵 Bakiye:
<b>${balance:.2f}</b>

📅 Bugünkü P&L:
<b>{format_signed_pnl(today_pnl)}</b>

🎯 Başlangıç:
<b>${INITIAL_BALANCE:.2f}</b>

⚠️ Bu gerçek para değildir.
"""

        telegram_send(
            msg,
            chat_id
        )

        return


    # ========================================================
    # /RİSK
    # ========================================================

    if command == "/risk":

        balance = get_state(
            "balance",
            INITIAL_BALANCE
        )

        count, open_risk = (
            get_open_position_stats()
        )

        today_pnl = get_today_pnl()

        available = max(
            0.0,
            MAX_TOTAL_OPEN_RISK -
            open_risk
        )

        msg = f"""
<b>🛡️ RİSK MERKEZİ</b>

💰 Bakiye:
<b>${balance:.2f}</b>

🎯 Hedef hesap riski:
<b>{ACCOUNT_RISK_PERCENT * 100:.1f}%</b>

📂 Açık pozisyon:
<b>{count}/{MAX_OPEN_POSITIONS}</b>

🛡️ Açık risk:
<b>${open_risk:.2f}</b>

🟢 Kullanılabilir risk:
<b>${available:.2f}</b>

🚧 Maksimum toplam risk:
<b>${MAX_TOTAL_OPEN_RISK:.2f}</b>

📉 Günlük zarar limiti:
<b>${MAX_DAILY_LOSS:.2f}</b>

📅 Bugünkü P&L:
<b>{format_signed_pnl(today_pnl)}</b>
"""

        telegram_send(
            msg,
            chat_id
        )

        return


    # ========================================================
    # /POZİSYONLAR
    # ========================================================

    if command == "/pozisyonlar":

        telegram_send(
            get_open_positions_text(),
            chat_id
        )

        return


    # ========================================================
    # /POZİSYON_AC
    # ========================================================

    if command == "/pozisyon_ac":

        if len(args) != 6:

            telegram_send(
                """
<b>🟢 MANUEL POZİSYON KULLANIMI</b>

<code>/pozisyon_ac
EURUSD BUY
1.17450
1.17250
1.17850
0.10</code>

Sıra:
SYMBOL SIDE ENTRY SL TP LOT

Örnek:
<code>/pozisyon_ac EURUSD BUY 1.17450 1.17250 1.17850 0.10</code>

⚠️ Bot broker emri göndermez.
Sadece demo takip kaydı oluşturur.
""",
                chat_id
            )

            return

        result = open_manual_position(
            args[0],
            args[1],
            args[2],
            args[3],
            args[4],
            args[5]
        )

        if result.get("ok"):

            msg = f"""
<b>🟢 POZİSYON TAKİBE ALINDI</b>

🆔 ID:
<code>{result["id"]}</code>

💹 {result["symbol"]}
📌 {result["side"]}

💰 Entry:
<code>{result["entry"]}</code>

🛑 SL:
<code>{result["sl"]}</code>

🎯 TP:
<code>{result["tp"]}</code>

📦 Lot:
<code>{result["lot"]:.2f}</code>

🛡️ Risk:
<code>${result["risk"]:.2f}</code>

📐 R:R:
<b>1:{result["rr"]:.2f}</b>

📡 TP/SL takip aktif.

⚠️ Gerçek broker emri gönderilmedi.
"""

        else:

            msg = (
                "❌ <b>POZİSYON EKLENEMEDİ</b>\n\n"
                +
                html.escape(
                    str(
                        result.get(
                            "message",
                            "Bilinmeyen hata"
                        )
                    )
                )
            )

        telegram_send(
            msg,
            chat_id
        )

        return


    # ========================================================
    # /POZİSYON_KAPAT
    # ========================================================

    if command == "/pozisyon_kapat":

        if len(args) != 2:

            telegram_send(
                """
<b>🔒 POZİSYON KAPAT</b>

Kullanım:

<code>/pozisyon_kapat ID EXIT_PRICE</code>

Örnek:

<code>/pozisyon_kapat 12 1.17800</code>
""",
                chat_id
            )

            return

        result = close_position(
            args[0],
            args[1],
            "MANUAL"
        )

        if result.get("ok"):

            icon = (
                "🟢"
                if result["pnl"] > 0
                else "🔴"
            )

            msg = f"""
<b>🔒 POZİSYON KAPATILDI</b>

{icon} {result["symbol"]} {result["side"]}

🆔 ID:
<code>{result["id"]}</code>

💰 Entry:
<code>{result["entry"]}</code>

🏁 Exit:
<code>{result["exit"]}</code>

💵 P&L:
<b>{format_signed_pnl(result["pnl"])}</b>

💰 Yeni bakiye:
<b>${result["balance"]:.2f}</b>

📌 Sebep:
<b>{result["reason"]}</b>
"""

        else:

            msg = (
                "❌ "
                +
                html.escape(
                    str(
                        result.get(
                            "message",
                            "Hata"
                        )
                    )
                )
            )

        telegram_send(
            msg,
            chat_id
        )

        return


    # ========================================================
    # /FİYAT
    # ========================================================

    if command == "/fiyat":

        lines = [
            "<b>💹 CANLI FİYATLAR</b>",
            "━━━━━━━━━━━━━━━━━━━━"
        ]

        for symbol, cfg in (
            SYMBOL_CONFIG.items()
        ):

            data = (
                fetch_latest_price_data(
                    symbol
                )
            )

            if data:

                price = format_price(
                    data["close"],
                    cfg["digits"]
                )

                lines.append(
                    f"💹 <b>{symbol}</b> "
                    f"<code>{price}</code>"
                )

            else:

                lines.append(
                    f"⚪ <b>{symbol}</b> "
                    f"<code>VERİ YOK</code>"
                )

        telegram_send(
            "\n".join(lines),
            chat_id
        )

        return


    # ========================================================
    # /SİNYALLER
    # ========================================================

    if command == "/sinyaller":

        msg = f"""
<b>🧠 SELECTIVE STRATEGY v4.6</b>

<b>🏆 5 PUANLIK SİSTEM</b>
━━━━━━━━━━━━━━━━━━━━

1️⃣ EMA 9/21 + fiyat konumu
2️⃣ RSI momentum
3️⃣ MACD histogram yönü
4️⃣ 1H trend
5️⃣ ADX + DI

<b>🚧 FİLTRELER</b>
━━━━━━━━━━━━━━━━━━━━

💪 ADX ≥ <b>{ADX_MIN:.0f}</b>
⚡ ATR oranı:
<b>{ATR_MIN_RATIO:.2f} — {ATR_MAX_RATIO:.2f}</b>

🏆 Minimum skor:
<b>{MIN_SIGNAL_SCORE}/5</b>

🔥 Güçlü:
<b>{STRONG_SIGNAL_SCORE}/5</b>

🎯 Minimum R:R:
<b>1:{MIN_RR:.1f}</b>

⏱️ Cooldown:
<b>{SIGNAL_COOLDOWN_SECONDS // 60} dakika</b>

🕯️ Sadece kapanmış M5 mum.

🚫 Aşırı uzamış hareketler filtrelenir.

⚠️ Amaç daha fazla sinyal değil,
<b>daha seçici sinyal</b> üretmektir.
"""

        telegram_send(
            msg,
            chat_id
        )

        return


    # ========================================================
    # /TEST
    # ========================================================

    if command == "/test":

        telegram_send(
            """
<b>🔎 SCALPRADAR TARAMASI</b>

6 sembol analiz ediliyor...
🧠 EMA + RSI + MACD
💪 ADX + DI
⚡ ATR
🕐 1H trend
🎯 R:R
""",
            chat_id
        )

        found = 0

        for symbol in SYMBOL_CONFIG:

            signal = generate_signal(
                symbol
            )

            if signal.get(
                "action"
            ):

                found += 1

                telegram_send(
                    format_signal_message(
                        signal
                    ),
                    chat_id
                )

            else:

                logger_strategy.info(
                    "TEST | %s | %s",
                    symbol,
                    signal.get(
                        "reason"
                    )
                )

        if found == 0:

            telegram_send(
                """
<b>🧊 TEMİZ TARAMA</b>

Şu anda 6 sembolün
hiçbiri bütün filtreleri
geçemedi.

Bu beklenen davranıştır.

🚫 Zayıf piyasada zorla
sinyal üretmiyoruz.
""",
                chat_id
            )

        else:

            telegram_send(
                f"""
<b>✅ TARAMA TAMAMLANDI</b>

🎯 Uygun sinyal:
<b>{found}</b>

⚠️ Sinyaller otomatik emir değildir.
""",
                chat_id
            )

        return


    # ========================================================
    # /BACKTEST
    # ========================================================

    if command == "/backtest":

        symbol = (
            args[0].upper()
            if args
            else None
        )

        if symbol:

            if symbol not in SYMBOL_CONFIG:

                telegram_send(
                    "❌ Geçersiz sembol.",
                    chat_id
                )

                return

            symbols = [
                symbol
            ]

        else:

            symbols = list(
                SYMBOL_CONFIG.keys()
            )

        telegram_send(
            """
<b>🧪 BACKTEST BAŞLADI</b>

📊 5M tarihsel veri
🧠 Selective Strategy
🎯 TP/SL simülasyonu
🛡️ Lookahead azaltılmış yapı

Biraz sürebilir...
""",
            chat_id
        )

        for sym in symbols:

            result = run_backtest(
                sym,
                "30d"
            )

            if not result.get(
                "ok"
            ):

                telegram_send(
                    f"""
❌ <b>{sym}</b>

{html.escape(
    str(
        result.get(
            "message",
            "Hata"
        )
    )
)}
""",
                    chat_id
                )

                continue

            if result.get(
                "trades",
                0
            ) == 0:

                telegram_send(
                    f"""
🧪 <b>{sym}</b>

Bu test döneminde
uygun işlem bulunamadı.
""",
                    chat_id
                )

                continue

            telegram_send(
                f"""
<b>🧪 BACKTEST — {sym}</b>

📊 İşlem:
<b>{result["trades"]}</b>

🟢 Kazanç:
<b>{result["wins"]}</b>

🔴 Zarar:
<b>{result["losses"]}</b>

🎯 Win Rate:
<b>{result["win_rate"]:.1f}%</b>

💵 Net P&L:
<b>{format_signed_pnl(result["pnl"])}</b>

📈 Ortalama Win:
<b>{format_signed_pnl(result["average_win"])}</b>

📉 Ortalama Loss:
<b>{format_signed_pnl(result["average_loss"])}</b>

⚠️ Bu sonuç tarihsel simülasyondur.
Gelecekte aynı sonucu verme garantisi yoktur.
""",
                chat_id
            )

        return


    # ========================================================
    # /İSTATİSTİK
    # ========================================================

    if command == "/istatistik":

        stats = get_statistics()

        if stats["count"] == 0:

            telegram_send(
                """
<b>📊 PERFORMANS</b>

Henüz kapanmış işlem yok.
""",
                chat_id
            )

            return

        pf = stats[
            "profit_factor"
        ]

        if np.isfinite(pf):

            pf_text = (
                f"{pf:.2f}"
            )

        else:

            pf_text = "∞"

        msg = f"""
<b>📊 PERFORMANS MERKEZİ</b>

━━━━━━━━━━━━━━━━━━━━

📌 Toplam işlem:
<b>{stats["count"]}</b>

🟢 Kazanç:
<b>{stats["wins"]}</b>

🔴 Zarar:
<b>{stats["losses"]}</b>

🎯 Win Rate:
<b>{stats["win_rate"]:.1f}%</b>

💵 Net P&L:
<b>{format_signed_pnl(stats["total_pnl"])}</b>

📈 Gross Profit:
<b>${stats["gross_profit"]:.2f}</b>

📉 Gross Loss:
<b>${stats["gross_loss"]:.2f}</b>

⚖️ Profit Factor:
<b>{pf_text}</b>

🟢 Ortalama Win:
<b>{format_signed_pnl(stats["average_win"])}</b>

🔴 Ortalama Loss:
<b>{format_signed_pnl(stats["average_loss"])}</b>

📉 Max Drawdown:
<b>${stats["max_drawdown"]:.2f}</b>
"""

        telegram_send(
            msg,
            chat_id
        )

        return


    # ========================================================
    # /RESET
    # ========================================================

    if command == "/reset":

        set_state(
            "paused",
            0
        )

        set_state(
            "auto_scan",
            1
        )

        telegram_send(
            """
<b>♻️ SİSTEM RESETLENDİ</b>

🟢 Sistem aktif
🤖 Otomatik tarama açık
🔎 6 sembol aktif
🧠 Selective Strategy aktif
📂 Manuel TP/SL takip aktif

⚠️ Açık pozisyon kayıtları
silinmedi.
""",
            chat_id
        )

        return


    # ========================================================
    # UNKNOWN
    # ========================================================

    telegram_send(
        """
❓ <b>Bilinmeyen komut.</b>

Komut listesini görmek için:

<code>/start</code>
""",
        chat_id
    )


# ============================================================
# TELEGRAM POLLER
# ============================================================

def telegram_poller():

    logger.info(
        "Telegram polling başlatılıyor..."
    )

    offset = None

    while True:

        try:

            updates = (
                telegram_get_updates(
                    offset
                )
            )

            for update in updates:

                try:

                    update_id = update.get(
                        "update_id"
                    )

                    if (
                        update_id
                        is not None
                    ):

                        offset = (
                            update_id + 1
                        )

                    handle_telegram_update(
                        update
                    )

                except Exception:

                    logger.exception(
                        "Telegram update işleme hatası"
                    )

        except Exception:

            logger.exception(
                "Telegram poller genel hata"
            )

            time.sleep(3)


# ============================================================
# SCAN SYMBOLS
# ============================================================

def scan_symbols():

    market_open, market_message = (
        get_market_status()
    )

    if not market_open:

        logger.info(
            "Market taraması pasif: %s",
            market_message
        )

        return

    for symbol in SYMBOL_CONFIG:

        try:

            signal = generate_signal(
                symbol
            )

            # ------------------------------------------------
            # SIGNAL YOK
            # ------------------------------------------------

            if not signal.get(
                "action"
            ):

                set_market_health(
                    symbol,
                    "WAIT",
                    signal.get(
                        "reason",
                        "Sinyal yok"
                    )
                )

                continue

            # ------------------------------------------------
            # SAME SYMBOL OPEN POSITION
            # ------------------------------------------------

            if has_open_position(
                symbol
            ):

                set_market_health(
                    symbol,
                    "BLOCKED",
                    "Açık pozisyon mevcut"
                )

                continue

            # ------------------------------------------------
            # PROCESSED BAR
            # ------------------------------------------------

            bar_time = signal[
                "bar_time"
            ]

            previous_bar = (
                get_processed_bar(
                    symbol
                )
            )

            if (
                previous_bar
                and str(
                    previous_bar
                ) == str(
                    bar_time
                )
            ):

                continue

            # ------------------------------------------------
            # COOLDOWN
            # ------------------------------------------------

            if not can_send_signal(
                symbol
            ):

                set_market_health(
                    symbol,
                    "COOLDOWN",
                    "Sinyal cooldown aktif"
                )

                continue

            # ------------------------------------------------
            # DAILY LOSS
            # ------------------------------------------------

            today_pnl = get_today_pnl()

            if today_pnl <= -MAX_DAILY_LOSS:

                logger.warning(
                    "Günlük zarar limiti "
                    "nedeniyle sinyal gönderilmedi."
                )

                set_market_health(
                    symbol,
                    "BLOCKED",
                    "Günlük zarar limiti"
                )

                continue

            # ------------------------------------------------
            # SEND SIGNAL
            # ------------------------------------------------

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

                mark_bar_processed(
                    symbol,
                    bar_time
                )

                set_market_health(
                    symbol,
                    "SIGNAL",
                    (
                        f'{signal["action"]} '
                        f'{signal["score"]}/5'
                    )
                )

                logger.info(
                    "SİNYAL GÖNDERİLDİ: "
                    "%s %s %s/5",
                    symbol,
                    signal["action"],
                    signal["score"]
                )

        except Exception:

            logger.exception(
                "Tarama hatası: %s",
                symbol
            )


# ============================================================
# BOT LOOP
# ============================================================

def bot_loop():

    logger.info(
        "Bot loop başlatıldı."
    )

    while True:

        try:

            # ------------------------------------------------
            # HER ZAMAN TP/SL TAKİBİ
            # ------------------------------------------------

            check_open_positions()

            # ------------------------------------------------
            # PAUSED
            # ------------------------------------------------

            paused = int(
                get_state(
                    "paused",
                    0
                )
            )

            if paused:

                time.sleep(
                    LOOP_SECONDS
                )

                continue

            # ------------------------------------------------
            # AUTO SCAN
            # ------------------------------------------------

            auto_scan = int(
                get_state(
                    "auto_scan",
                    1
                )
            )

            if auto_scan:

                scan_symbols()

            time.sleep(
                LOOP_SECONDS
            )

        except Exception:

            logger.exception(
                "Bot loop hatası"
            )

            time.sleep(5)


# ============================================================
# FLASK ROUTES
# ============================================================

@app.route("/")
def home():

    balance = get_state(
        "balance",
        INITIAL_BALANCE
    )

    count, risk = (
        get_open_position_stats()
    )

    return jsonify(
        {
            "app": APP_NAME,
            "version": VERSION,
            "status": "online",
            "simulation_mode":
                SIMULATION_MODE,
            "symbols":
                list(
                    SYMBOL_CONFIG.keys()
                ),
            "balance":
                balance,
            "open_positions":
                count,
            "open_risk":
                risk
        }
    )


@app.route("/ping")
def ping():

    return jsonify(
        {
            "status": "ok",
            "app": APP_NAME,
            "version": VERSION,
            "time":
                now_istanbul().isoformat()
        }
    )


@app.route("/health")
def health():

    count, risk = (
        get_open_position_stats()
    )

    return jsonify(
        {
            "status": "healthy",
            "version": VERSION,
            "telegram":
                bool(
                    TELEGRAM_TOKEN
                ),
            "database":
                os.path.exists(
                    DB_FILE
                ),
            "open_positions":
                count,
            "open_risk":
                risk,
            "time":
                now_istanbul().isoformat()
        }
    )


# ============================================================
# STARTUP
# ============================================================

def startup():

    logger.info(
        "========================================"
    )

    logger.info(
        "%s v%s başlatılıyor...",
        APP_NAME,
        VERSION
    )

    logger.info(
        "SIMULATION_MODE=%s",
        SIMULATION_MODE
    )

    logger.info(
        "Sembol sayısı=%s",
        len(SYMBOL_CONFIG)
    )

    logger.info(
        "Semboller=%s",
        ", ".join(
            SYMBOL_CONFIG.keys()
        )
    )

    # --------------------------------------------------------
    # DATABASE
    # --------------------------------------------------------

    init_db()

    # --------------------------------------------------------
    # DEFAULT BALANCE
    # --------------------------------------------------------

    current_balance = get_state(
        "balance",
        None
    )

    if current_balance is None:

        set_state(
            "balance",
            INITIAL_BALANCE
        )

        logger.info(
            "Demo bakiye oluşturuldu: %.2f",
            INITIAL_BALANCE
        )

    # --------------------------------------------------------
    # DEFAULT AUTO SCAN
    # --------------------------------------------------------

    existing_auto = get_state(
        "auto_scan",
        None
    )

    if existing_auto is None:

        set_state(
            "auto_scan",
            1
        )

    # --------------------------------------------------------
    # DEFAULT PAUSED
    # --------------------------------------------------------

    existing_paused = get_state(
        "paused",
        None
    )

    if existing_paused is None:

        set_state(
            "paused",
            0
        )

    # --------------------------------------------------------
    # TELEGRAM MENU
    # --------------------------------------------------------

    if TELEGRAM_TOKEN:

        set_telegram_commands()

    else:

        logger.warning(
            "TELEGRAM_TOKEN bulunamadı."
        )

    # --------------------------------------------------------
    # TELEGRAM THREAD
    # --------------------------------------------------------

    if TELEGRAM_TOKEN:

        telegram_thread = threading.Thread(
            target=telegram_poller,
            daemon=True,
            name="TelegramPoller"
        )

        telegram_thread.start()

    # --------------------------------------------------------
    # BOT THREAD
    # --------------------------------------------------------

    bot_thread = threading.Thread(
        target=bot_loop,
        daemon=True,
        name="BotLoop"
    )

    bot_thread.start()

    logger.info(
        "Background bot loop aktif."
    )

    logger.info(
        "========================================"
    )


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

    # Render / Gunicorn
    startup()

# ============================================================
# PRO DASHBOARD ENTEGRASYONU
# ============================================================

PRO_HTML = r"""
<!doctype html>
<html lang="tr">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>SCALPRADAR PRO — AI Powered Trading Terminal</title>
  <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
  <style>
    :root {
      --bg:#090d14; --panel:#101722; --panel2:#0d141e; --line:#202b3a;
      --text:#edf2f8; --muted:#8492a6; --green:#25d695; --red:#ff647c;
      --yellow:#f4c45e; --blue:#6da8ff; --purple:#a58bfa;
    }
    * { box-sizing:border-box }
    body { margin:0; background:var(--bg); color:var(--text); font:13px/1.4 Inter,system-ui,sans-serif }
    .layout { display:grid; grid-template-columns:220px 1fr; min-height:100vh }
    aside { background:#0a0f18; border-right:1px solid var(--line); padding:20px 12px; display:flex; flex-direction:column; gap:20px }
    .brand { font-weight:900; font-size:16px; letter-spacing:1px; padding:0 8px }
    .brand span { color:var(--blue) }
    .nav-grp { display:grid; gap:3px }
    .nav-label { color:#4e5e74; font-size:9px; font-weight:800; letter-spacing:1.5px; padding:0 8px; margin-bottom:5px }
    .nav-item { color:#8a9bb2; text-decoration:none; padding:9px 10px; border-radius:8px; display:flex; gap:10px; align-items:center; font-weight:500 }
    .nav-item.active, .nav-item:hover { background:#162336; color:#fff }
    main { padding:18px 24px; display:grid; gap:16px; max-width:1800px; margin:0 auto; width:100% }
    .topbar { display:flex; justify-content:space-between; align-items:center; background:var(--panel); border:1px solid var(--line); border-radius:12px; padding:10px 18px }
    .status-badge { display:inline-flex; align-items:center; gap:6px; background:#142621; color:var(--green); border:1px solid #1f3d32; padding:4px 10px; border-radius:20px; font-size:11px; font-weight:700 }
    .kpi-row { display:grid; grid-template-columns:repeat(5, 1fr); gap:12px }
    .card { background:linear-gradient(145deg, var(--panel), #0b111a); border:1px solid var(--line); border-radius:12px; padding:14px; min-width:0 }
    .card-title { color:var(--muted); font-size:10px; font-weight:700; text-transform:uppercase; letter-spacing:.5px }
    .card-value { font-size:22px; font-weight:800; margin:6px 0 2px }
    .dashboard-grid { display:grid; grid-template-columns:2.2fr 1fr; gap:16px }
    .sub-grid { display:grid; grid-template-columns:1fr 1fr; gap:16px }
    table { width:100%; border-collapse:collapse; font-size:11px }
    th { color:var(--muted); text-align:left; font-size:9px; padding:8px 6px; border-bottom:1px solid var(--line) }
    td { padding:8px 6px; border-bottom:1px solid #162232 }
    .green { color:var(--green) } .red { color:var(--red) } .yellow { color:var(--yellow) }
    .badge { padding:2px 6px; border-radius:4px; font-weight:700; font-size:9px }
    .badge.buy { background:#132e26; color:var(--green) }
    .badge.sell { background:#331a23; color:var(--red) }
    @media(max-width:1000px) { .layout { grid-template-columns:1fr } aside { display:none } .kpi-row { grid-template-columns:repeat(2,1fr) } .dashboard-grid { grid-template-columns:1fr } }
  </style>
</head>
<body>
<div class="layout">
  <aside>
    <div class="brand">SCALP<span>RADAR</span> PRO</div>
    <div>
      <div class="nav-label">TERMINAL</div>
      <div class="nav-grp">
        <a href="#" class="nav-item active">📊 Ana Sayfa</a>
        <a href="#positions" class="nav-item">📂 Açık Pozisyonlar</a>
        <a href="#history" class="nav-item">📜 İşlem Geçmişi</a>
      </div>
    </div>
    <div style="margin-top:auto; background:var(--panel2); border:1px solid var(--line); border-radius:10px; padding:12px; font-size:11px;">
      <div style="color:var(--muted);">SİSTEM DURUMU</div>
      <div style="color:var(--green); font-weight:700; margin:4px 0;">● Bot + Web Aktif</div>
      <div style="font-size:10px; color:var(--muted);">Monolithic v4.6</div>
    </div>
  </aside>

  <main>
    <div class="topbar">
      <div style="display:flex; align-items:center; gap:15px;">
        <span class="status-badge">● Bot Aktif v4.6</span>
        <span style="font-size:12px; color:var(--muted);">Zaman Dilimi: M5 / 1H Trend</span>
      </div>
      <div style="display:flex; gap:10px; align-items:center;">
        <span style="font-size:12px;" id="clock">--:--:--(TR)</span>
        <span class="badge buy">Demo Hesap</span>
      </div>
    </div>

    <!-- KPI STATS -->
    <div class="kpi-row">
      <div class="card"><div class="card-title">Toplam Bakiye</div><div class="card-value">${{"%.2f"|format(balance)}}</div><div class="card-title">Başlangıç: $3,000.00</div></div>
      <div class="card"><div class="card-title">Günlük P&L</div><div class="card-value {{'green' if today_pnl >= 0 else 'red'}}">{{ "+$%.2f"|format(today_pnl) if today_pnl>=0 else "-$%.2f"|format(today_pnl|abs) }}</div><div class="card-title">Bugünkü Realize</div></div>
      <div class="card"><div class="card-title">Açık Pozisyon</div><div class="card-value">{{open_count}} / 3</div><div class="card-title">Risk: ${{ "%.2f"|format(open_risk) }}</div></div>
      <div class="card"><div class="card-title">Mod / Durum</div><div class="card-value" style="font-size:18px; color:var(--blue);">DEMO / MANUAL</div><div class="card-title">Emirler Manuel</div></div>
      <div class="card"><div class="card-title">Sistem Loop</div><div class="card-value" style="font-size:18px; color:var(--green);">ONLINE</div><div class="card-title">Telegram Poller</div></div>
    </div>

    <!-- MAIN DASHBOARD AREA -->
    <div class="dashboard-grid">
      <div class="card">
        <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:10px;">
          <b style="font-size:14px;">XAUUSD / Fiyat & Görsel Takip Katmanı</b>
          <span class="card-title" style="color:var(--blue);">TradingView / M5-M15 Sync</span>
        </div>
        <div style="height:280px; background:#080c12; border:1px solid var(--line); border-radius:8px; display:flex; align-items:center; justify-content:center; color:var(--muted); text-align:center; padding:20px;">
          <div>
            <div style="font-size:16px; font-weight:700; color:var(--text); margin-bottom:6px;">TradingView Görsel Katmanı Aktif</div>
            Canlı fiyat izleme ve Long/Short kutu eşleşmeleri için TradingView tablet/ekranını bu metriklerle hizalamaya devam ediyorsun koç.
          </div>
        </div>
      </div>

      <div class="card" id="positions">
        <div class="card-title" style="margin-bottom:8px;">AÇIK TAKİP KAYITLARI (POSITIONS)</div>
        {% if open_pos %}
        <div style="overflow-x:auto;">
          <table>
            <thead><tr><th>ID</th><th>Sembol</th><th>Yön</th><th>Entry</th><th>SL / TP</th><th>Lot</th></tr></thead>
            <tbody>
              {% for p in open_pos %}
              <tr>
                <td>#{{p[0]}}</td>
                <td><b>{{p}}</b></td>
                <td><span class="badge {{p|lower}}">{{p}}</span></td>
                <td>{{p}}</td>
                <td><span class="red">{{p}}</span> / <span class="green">{{p}}</span></td>
                <td>{{p if p|length > 7 else '0.01'}}</td>
              </tr>
              {% endfor %}
            </tbody>
          </table>
        </div>
        {% else %}
        <div style="color:var(--muted); font-size:12px; padding:20px 0; text-align:center;">Şu an açık takip kaydı yok. 5/5 sinyal gelince /pozisyon_ac patlat.</div>
        {% endif %}
      </div>
    </div>

    <!-- LOWER SUB-GRID: CLOSED TRADES -->
    <div class="sub-grid" id="history">
      <div class="card">
        <div class="card-title" style="margin-bottom:10px;">SON KAPANAN İŞLEMLER (CLOSED TRADES)</div>
        <div style="max-height:220px; overflow-y:auto;">
          <table>
            <thead><tr><th>Sembol</th><th>Yön</th><th>Entry -> Exit</th><th>P&L</th><th>Sebep</th></tr></thead>
            <tbody>
              {% for t in closed_trades[:10] %}
              <tr>
                <td><b>{{t[0]}}</b></td>
                <td><span class="badge {{t|lower}}">{{t}}</span></td>
                <td>{{t}} -> {{t}}</td>
                <td class="{{'green' if t>=0 else 'red'}}">{{ "+$%.2f"|format(t) if t>=0 else "-$%.2f"|format(t|abs) }}</td>
                <td style="font-size:10px; color:var(--muted);">{{t if t|length > 6 else 'MANUAL'}}</td>
              </tr>
              {% else %}
              <tr><td colspan="5" style="color:var(--muted); text-align:center;">Henüz kapanmış işlem yok.</td></tr>
              {% endfor %}
            </tbody>
          </table>
        </div>
      </div>

      <div class="card">
        <div class="card-title" style="margin-bottom:10px;">HIZLI KOMUT / DURUM ÖZETİ</div>
        <div style="display:grid; gap:8px; font-size:12px;">
          <div style="display:flex; justify-content:space-between; padding:6px 0; border-bottom:1px solid var(--line);"><span>Strateji Motoru</span><b>Selective Strategy v4.6</b></div>
          <div style="display:flex; justify-content:space-between; padding:6px 0; border-bottom:1px solid var(--line);"><span>Min. Skor Eşiği</span><b>4/5 (5/5 Güçlü)</b></div>
          <div style="display:flex; justify-content:space-between; padding:6px 0; border-bottom:1px solid var(--line);"><span>Risk / Ödül Oranı</span><b>Min 1:2.00</b></div>
          <div style="display:flex; justify-content:space-between; padding:6px 0;"><span>Telegram Modülü</span><b class="green">● Aktif / Poller Çalışıyor</b></div>
        </div>
      </div>
    </div>
  </main>
</div>
<script>
  function updateClock(){ document.getElementById('clock').textContent = new Date().toLocaleTimeString('tr-TR') + ' (TR)'; }
  updateClock(); setInterval(updateClock,1000);
</script>
</body>
</html>
"""

def get_db_stats_for_web():
    with DB_LOCK:
        conn = db_connect()
        try:
            closed = conn.execute("SELECT symbol, side, entry, exit, pnl, closed_at, reason FROM closed_trades ORDER BY id DESC LIMIT 50").fetchall()
            open_pos = conn.execute("SELECT id, symbol, side, entry, current_price, sl, tp, lot, risk FROM positions WHERE status = 'OPEN' ORDER BY id ASC").fetchall()
            return closed, open_pos
        finally:
            conn.close()

@app.route("/terminal")
def pro_terminal():
    balance = get_state("balance", INITIAL_BALANCE)
    open_count, open_risk = get_open_position_stats()
    closed_trades, open_pos = get_db_stats_for_web()
    today_pnl = get_today_pnl()
    
    return render_template_string(
        PRO_HTML,
        balance=balance,
        today_pnl=today_pnl,
        open_count=open_count,
        open_risk=open_risk,
        open_pos=open_pos,
        closed_trades=closed_trades
    )
