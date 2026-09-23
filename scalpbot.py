# ============================================================
# SCALPBOT PRO — TELEGRAM SIGNAL BOT v4.3 (PATCHED)
# Sinyal botu; gerçek emir göndermez.
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
VERSION = "4.3-SIGNAL-LOT-PATCHED"
SIMULATION_MODE = True

TIMEZONE = "Europe/Istanbul"
TZ = ZoneInfo(TIMEZONE)
DB_FILE = os.getenv("DB_FILE", "scalpbot.db")

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN", "").strip()
ALLOWED_TELEGRAM_IDS = os.getenv("ALLOWED_TELEGRAM_IDS", "").strip()
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "").strip()

WEB_HOST = "0.0.0.0"
WEB_PORT = int(os.getenv("PORT", "10000"))

INITIAL_BALANCE = 3000.0
ACCOUNT_RISK_PERCENT = 0.01
MAX_DAILY_LOSS = 150.0
MAX_OPEN_POSITIONS = 3
MAX_TOTAL_OPEN_RISK = 300.0
COMMISSION_PER_SIDE = 3.50
SIGNAL_COOLDOWN_SECONDS = 900
LOOP_SECONDS = 30

SYMBOL_CONFIG = {
    "EURUSD": {"yf": "EURUSD=X", "sl_atr": 1.5, "tp_atr": 3.0, "digits": 5, "contract_size": 100000},
    "GBPUSD": {"yf": "GBPUSD=X", "sl_atr": 1.5, "tp_atr": 3.0, "digits": 5, "contract_size": 100000},
    "USDJPY": {"yf": "USDJPY=X", "sl_atr": 1.5, "tp_atr": 3.0, "digits": 3, "contract_size": 100000},
    "AUDUSD": {"yf": "AUDUSD=X", "sl_atr": 1.5, "tp_atr": 3.0, "digits": 5, "contract_size": 100000},
    "USDCAD": {"yf": "USDCAD=X", "sl_atr": 1.5, "tp_atr": 3.0, "digits": 5, "contract_size": 100000},
    "USDCHF": {"yf": "USDCHF=X", "sl_atr": 1.5, "tp_atr": 3.0, "digits": 5, "contract_size": 100000},
    "NZDUSD": {"yf": "NZDUSD=X", "sl_atr": 1.5, "tp_atr": 3.0, "digits": 5, "contract_size": 100000},
    "XAUUSD": {"yf": "GC=F", "sl_atr": 1.2, "tp_atr": 2.5, "digits": 2, "contract_size": 100},
}

# ============================================================
# LOGGING
# ============================================================

logger = logging.getLogger("scalpbot")
logger_strategy = logging.getLogger("strategy")
logger.setLevel(logging.INFO)
logger_strategy.setLevel(logging.INFO)

_formatter = logging.Formatter("%(asctime)s | %(levelname)s | %(name)s | %(message)s")
_console = logging.StreamHandler()
_console.setFormatter(_formatter)

if not logger.handlers:
    logger.addHandler(_console)

_file = RotatingFileHandler("scalpbot.log", maxBytes=2_000_000, backupCount=3, encoding="utf-8")
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
    conn = sqlite3.connect(DB_FILE, timeout=30, check_same_thread=False)
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def init_db():
    with DB_LOCK:
        conn = db_connect()
        cur = conn.cursor()
        cur.execute("CREATE TABLE IF NOT EXISTS state (key TEXT PRIMARY KEY, value REAL)")
        cur.execute("CREATE TABLE IF NOT EXISTS state_str (key TEXT PRIMARY KEY, value TEXT)")
        cur.execute("""CREATE TABLE IF NOT EXISTS positions (
            id INTEGER PRIMARY KEY AUTOINCREMENT, symbol TEXT, side TEXT,
            entry REAL, sl REAL, tp REAL, risk REAL, opened_at TEXT,
            status TEXT DEFAULT 'OPEN')""")
        cur.execute("""CREATE TABLE IF NOT EXISTS closed_trades (
            id INTEGER PRIMARY KEY AUTOINCREMENT, symbol TEXT, side TEXT,
            entry REAL, exit REAL, pnl REAL, opened_at TEXT, closed_at TEXT)""")
        cur.execute("CREATE TABLE IF NOT EXISTS signal_cooldown (symbol TEXT PRIMARY KEY, last_signal INTEGER)")
        cur.execute("CREATE TABLE IF NOT EXISTS processed_bars (symbol TEXT PRIMARY KEY, bar_time TEXT)")
        cur.execute("""CREATE TABLE IF NOT EXISTS market_health (
            symbol TEXT PRIMARY KEY, status TEXT, message TEXT, updated_at TEXT)""")
        conn.commit()
        conn.close()


def get_state(key, default=0.0):
    with DB_LOCK:
        conn = db_connect()
        try:
            row = conn.execute("SELECT value FROM state WHERE key = ?", (key,)).fetchone()
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
            conn.execute("""INSERT INTO state(key, value) VALUES(?, ?)
                ON CONFLICT(key) DO UPDATE SET value = excluded.value""", (key, float(value)))
            conn.commit()
        finally:
            conn.close()


def get_open_position_stats():
    with DB_LOCK:
        conn = db_connect()
        try:
            row = conn.execute("""SELECT COUNT(*), COALESCE(SUM(risk), 0)
                FROM positions WHERE status = 'OPEN'""").fetchone()
        finally:
            conn.close()
    if not row:
        return 0, 0.0
    return int(row[0] or 0), float(row[1] or 0.0)

# ============================================================
# TELEGRAM HELPERS
# ============================================================

def parse_allowed_ids():
    result = set()
    for item in ALLOWED_TELEGRAM_IDS.split(","):
        item = item.strip()
        if item:
            try:
                result.add(int(item))
            except ValueError:
                logger.warning("ALLOWED_TELEGRAM_IDS içinde geçersiz değer: %s", item)
    return result


ALLOWED_IDS = parse_allowed_ids()


def is_authorized(chat_id):
    # Güvenlik için boş allowlist durumunda herkese izin verilmez.
    if not ALLOWED_IDS or chat_id is None:
        return False
    try:
        return int(chat_id) in ALLOWED_IDS
    except (TypeError, ValueError):
        return False


def telegram_send(message, chat_id=None):
    if not TELEGRAM_TOKEN:
        logger.error("TELEGRAM_TOKEN tanımlı değil.")
        return False

    target_chat = chat_id if chat_id is not None else TELEGRAM_CHAT_ID
    if not str(target_chat).strip():
        logger.error("Telegram hedef chat ID tanımlı değil.")
        return False

    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {
        "chat_id": target_chat,
        "text": message,
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
    }
    try:
        response = requests.post(url, json=payload, timeout=20)
        if response.ok:
            return True
        logger.error("Telegram gönderim hatası HTTP %s: %s", response.status_code, response.text[:500])
    except requests.RequestException:
        logger.exception("Telegram gönderim bağlantı hatası")
    return False


def set_telegram_commands():
    if not TELEGRAM_TOKEN:
        logger.warning("Komut menüsü kurulamadı: TELEGRAM_TOKEN yok.")
        return False
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/setMyCommands"
    commands = {"commands": [
        {"command": "start", "description": "Botu başlat"},
        {"command": "durum", "description": "Sistem durumu"},
        {"command": "bakiye", "description": "Demo bakiye"},
        {"command": "istatistik", "description": "İstatistikler"},
        {"command": "risk", "description": "Risk durumu"},
        {"command": "pozisyonlar", "description": "Açık pozisyonlar"},
        {"command": "fiyat", "description": "Güncel fiyatlar"},
        {"command": "sinyaller", "description": "Sinyal kuralı"},
        {"command": "test", "description": "Anlık tarama"},
        {"command": "reset", "description": "Botu aktif et"},
    ]}
    try:
        response = requests.post(url, json=commands, timeout=15)
        if not response.ok:
            logger.error("setMyCommands başarısız HTTP %s: %s", response.status_code, response.text[:300])
            return False
        data = response.json()
        if not data.get("ok"):
            logger.error("setMyCommands Telegram cevabı: %s", data)
            return False
        return True
    except (requests.RequestException, ValueError):
        logger.exception("Telegram komut menüsü ayarlanamadı")
        return False

# ============================================================
# FORMATTING / LOT ESTIMATE
# ============================================================

def format_price(value, digits=5):
    try:
        return f"{float(value):.{digits}f}"
    except (TypeError, ValueError):
        return "-"


def format_signed_pnl(value):
    try:
        value = float(value)
        return f"+${value:.2f}" if value > 0 else f"${value:.2f}"
    except (TypeError, ValueError):
        return "$0.00"


def calculate_position_size(symbol, entry, sl):
    """Yaklaşık lot önerisi. Broker sözleşme özellikleri ve hesap para birimiyle doğrulanmalıdır."""
    try:
        balance = float(get_state("balance", INITIAL_BALANCE))
        risk_cash = balance * ACCOUNT_RISK_PERCENT
        cfg = SYMBOL_CONFIG[symbol]
        contract = float(cfg["contract_size"])
        distance = abs(float(entry) - float(sl))
        if distance <= 0 or balance <= 0:
            return 0.01

        # Bu kaba hesap yalnızca USD-quote FX çiftleri ve XAUUSD varsayımı içindir.
        # USDJPY, USDCAD, USDCHF ve XAUUSD için dönüşüm/contract şartları brokerdan brokera değişir.
        if symbol in ("EURUSD", "GBPUSD", "AUDUSD", "NZDUSD"):
            loss_per_lot_usd = distance * contract
        elif symbol == "USDJPY":
            loss_per_lot_usd = distance * contract / max(float(entry), 1e-9)
        elif symbol == "USDCAD":
            loss_per_lot_usd = distance * contract / max(float(entry), 1e-9)
        elif symbol == "USDCHF":
            loss_per_lot_usd = distance * contract / max(float(entry), 1e-9)
        elif symbol == "XAUUSD":
            loss_per_lot_usd = distance * contract
        else:
            return 0.01

        if loss_per_lot_usd <= 0 or not np.isfinite(loss_per_lot_usd):
            return 0.01

        raw_lot = risk_cash / loss_per_lot_usd
        # Aşağı yuvarlama: risk hedefini aşmamak için; broker min lot/step ayrıca kontrol edilmeli.
        lot = np.floor(raw_lot * 100) / 100
        return float(max(0.01, lot))
    except Exception:
        logger.exception("Lot hesaplama hatası (%s)", symbol)
        return 0.01

# ============================================================
# MARKET DATA / INDICATORS
# ============================================================

def fetch_market_data(symbol, interval="5m", period="5d"):
    if symbol not in SYMBOL_CONFIG:
        raise ValueError(f"Bilinmeyen sembol: {symbol}")
    ticker = SYMBOL_CONFIG[symbol]["yf"]
    try:
        df = yf.download(ticker, interval=interval, period=period, progress=False,
                         auto_adjust=False, threads=False)
    except Exception:
        logger_strategy.exception("%s veri çekme hatası", symbol)
        return None
    if df is None or df.empty:
        logger_strategy.warning("%s için veri yok (%s, %s)", symbol, interval, period)
        return None
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    required = ["Open", "High", "Low", "Close", "Volume"]
    for col in required:
        if col not in df.columns:
            if col == "Volume":
                df[col] = 0
            else:
                logger_strategy.warning("%s verisinde %s sütunu yok", symbol, col)
                return None
    df = df[required].copy()
    for col in required:
        df[col] = pd.to_numeric(df[col], errors="coerce")
    df.dropna(subset=["Open", "High", "Low", "Close"], inplace=True)
    if len(df) < 100:
        logger_strategy.warning("%s veri sayısı yetersiz: %s", symbol, len(df))
        return None
    return df


def ema(series, period):
    return series.ewm(span=period, adjust=False).mean()


def calculate_rsi(series, period=14):
    delta = series.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(alpha=1 / period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1 / period, adjust=False).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    return (100 - 100 / (1 + rs)).fillna(50)


def calculate_macd(series, fast=12, slow=26, signal=9):
    macd_line = ema(series, fast) - ema(series, slow)
    signal_line = ema(macd_line, signal)
    return macd_line, signal_line, macd_line - signal_line


def calculate_atr(df, period=14):
    previous_close = df["Close"].shift(1)
    tr = pd.concat([
        df["High"] - df["Low"],
        (df["High"] - previous_close).abs(),
        (df["Low"] - previous_close).abs(),
    ], axis=1).max(axis=1)
    return tr.ewm(alpha=1 / period, adjust=False).mean()


def add_indicators(df):
    df = df.copy()
    df["EMA9"] = ema(df["Close"], 9)
    df["EMA21"] = ema(df["Close"], 21)
    df["RSI14"] = calculate_rsi(df["Close"], 14)
    df["MACD"], df["MACD_SIGNAL"], df["MACD_HIST"] = calculate_macd(df["Close"])
    df["ATR14"] = calculate_atr(df, 14)
    return df


def get_higher_timeframe_trend(symbol):
    df = fetch_market_data(symbol, interval="1h", period="30d")
    if df is None or len(df) < 50:
        return "UNKNOWN"
    last = add_indicators(df).iloc[-1]
    e9, e21 = float(last["EMA9"]), float(last["EMA21"])
    if e9 > e21:
        return "BULLISH"
    if e9 < e21:
        return "BEARISH"
    return "NEUTRAL"

# ============================================================
# SIGNAL COOLDOWN / STRATEGY
# ============================================================

def can_send_signal(symbol):
    with DB_LOCK:
        conn = db_connect()
        try:
            row = conn.execute("SELECT last_signal FROM signal_cooldown WHERE symbol = ?", (symbol,)).fetchone()
        finally:
            conn.close()
    if not row or row[0] is None:
        return True
    try:
        return int(time.time()) - int(row[0]) >= SIGNAL_COOLDOWN_SECONDS
    except (TypeError, ValueError):
        return True


def mark_signal_sent(symbol):
    with DB_LOCK:
        conn = db_connect()
        try:
            conn.execute("""INSERT INTO signal_cooldown(symbol, last_signal) VALUES(?, ?)
                ON CONFLICT(symbol) DO UPDATE SET last_signal = excluded.last_signal""",
                (symbol, int(time.time())))
            conn.commit()
        finally:
            conn.close()


def generate_signal(symbol):
    try:
        df = fetch_market_data(symbol, interval="5m", period="5d")
        if df is None:
            return None
        df = add_indicators(df)
        last = df.iloc[-1]
        price, e9, e21 = float(last["Close"]), float(last["EMA9"]), float(last["EMA21"])
        rsi, macd_hist, atr = float(last["RSI14"]), float(last["MACD_HIST"]), float(last["ATR14"])
        if not all(np.isfinite(x) for x in (price, e9, e21, rsi, macd_hist, atr)) or price <= 0 or atr <= 0:
            return None

        trend = get_higher_timeframe_trend(symbol)
        buy_score = sell_score = 0

        if e9 > e21:
            buy_score += 1
        elif e9 < e21:
            sell_score += 1

        if 50 <= rsi <= 70:
            buy_score += 1
        elif 30 <= rsi < 50:
            sell_score += 1

        if macd_hist > 0:
            buy_score += 1
        elif macd_hist < 0:
            sell_score += 1

        if trend == "BULLISH":
            buy_score += 1
        elif trend == "BEARISH":
            sell_score += 1

        if buy_score >= 3 and buy_score > sell_score:
            action = "BUY"
        elif sell_score >= 3 and sell_score > buy_score:
            action = "SELL"
        else:
            return None

        cfg = SYMBOL_CONFIG[symbol]
        sl_distance = atr * cfg["sl_atr"]
        tp_distance = atr * cfg["tp_atr"]
        sl, tp = (price - sl_distance, price + tp_distance) if action == "BUY" else (price + sl_distance, price - tp_distance)
        lot = calculate_position_size(symbol, price, sl)
        digits = cfg["digits"]

        return {
            "symbol": symbol, "action": action,
            "price": round(price, digits), "sl": round(sl, digits), "tp": round(tp, digits),
            "lot": lot, "rsi": round(rsi, 2), "ema9": round(e9, digits), "ema21": round(e21, digits),
            "macd_hist": macd_hist, "atr": atr, "trend": trend,
            "buy_score": buy_score, "sell_score": sell_score,
            "time": now_istanbul().strftime("%d.%m.%Y %H:%M:%S"),
        }
    except Exception:
        logger_strategy.exception("%s generate_signal hatası", symbol)
        return None


def format_signal_message(signal):
    symbol = signal["symbol"]
    digits = SYMBOL_CONFIG[symbol]["digits"]
    direction = "🟢 BUY" if signal["action"] == "BUY" else "🔴 SELL"
    score = max(signal["buy_score"], signal["sell_score"])
    return f"""
🚨 <b>SCALPRADAR SİNYAL</b>

{direction}

💱 <b>Sembol:</b> {html.escape(symbol)}
⏱ <b>Timeframe:</b> M5
🕐 <b>Zaman:</b> {html.escape(signal["time"])}

💰 <b>Entry:</b> {format_price(signal["price"], digits)}
🛑 <b>SL:</b> {format_price(signal["sl"], digits)}
🎯 <b>TP:</b> {format_price(signal["tp"], digits)}
📦 <b>Yaklaşık lot:</b> {signal["lot"]:.2f}

📊 <b>Skor:</b> {score}/4
EMA9: {format_price(signal["ema9"], digits)}
EMA21: {format_price(signal["ema21"], digits)}
RSI14: {signal["rsi"]:.2f}
MACD: {signal["macd_hist"]:.6f}
ATR14: {signal["atr"]:.6f}
🕐 <b>1H Trend:</b> {signal["trend"]}

━━━━━━━━━━━━━━━━━━
⚠️ <b>MANUEL / DEMO SİNYAL</b> — Bot emir göndermez.
⚠️ Lot yaklaşık tahmindir; MT5 broker sözleşme bilgileriyle doğrula.
""".strip()


def get_signal_preview():
    signals = []
    for symbol in SYMBOL_CONFIG:
        signal = generate_signal(symbol)
        if signal is not None:
            signals.append(signal)
    return signals

# ============================================================
# MARKET STATUS / COMMANDS
# ============================================================

def get_market_status(symbol):
    # Basit hafta içi göstergesi; brokerın kesin seans saatlerini temsil etmez.
    try:
        if now_istanbul().weekday() >= 5:
            return "KAPALI", "Hafta sonu"
        if symbol in SYMBOL_CONFIG:
            return "AÇIK", "Hafta içi kontrolü; broker seansı doğrulanmadı"
        return "BİLİNMİYOR", "Tanımsız sembol"
    except Exception as exc:
        logger.exception("Piyasa durumu hatası")
        return "BİLİNMİYOR", str(exc)


def handle_telegram_command(chat_id, command, args=""):
    clean = command.split("@")[0].lower().strip()
    logger.info("Komut alındı: %s | chat_id=%s", clean, chat_id)

    if not is_authorized(chat_id):
        telegram_send("⛔ <b>Yetkiniz bulunmuyor.</b>", chat_id)
        return

    try:
        if clean == "/start":
            telegram_send("🤖 <b>SCALPRADAR v4.3</b>\n🟢 Sinyal motoru: çalışıyor\n📦 Lot: yaklaşık tahmin\n🧪 Mod: sinyal/demo; gerçek emir yok.", chat_id)

        elif clean == "/durum":
            paused = get_state("paused", 0.0) == 1.0
            count, risk = get_open_position_stats()
            state_text = "🔴 DURAKLATILDI" if paused else "🟢 AKTİF"
            telegram_send(f"📡 <b>DURUM</b>\nBot: {state_text}\nAçık pozisyon: {count}\nAçık kayıtlı risk: ${risk:.2f}\nTarama döngüsü: {LOOP_SECONDS} sn\nMod: Sinyal / manuel", chat_id)

        elif clean == "/bakiye":
            balance = get_state("balance", INITIAL_BALANCE)
            telegram_send(f"💰 <b>DEMO BAKİYE:</b> ${balance:.2f}", chat_id)

        elif clean == "/risk":
            count, risk = get_open_position_stats()
            balance = get_state("balance", INITIAL_BALANCE)
            telegram_send(
                f"🛡️ <b>RİSK MERKEZİ</b>\nBakiye: ${balance:.2f}\nİşlem başı hedef risk: %{ACCOUNT_RISK_PERCENT * 100:.2f}\nAçık kayıt: {count}/{MAX_OPEN_POSITIONS}\nAçık kayıtlı risk: ${risk:.2f}\nYapılandırılmış toplam risk sınırı: ${MAX_TOTAL_OPEN_RISK:.2f}\nGünlük zarar sınırı (ayar): ${MAX_DAILY_LOSS:.2f}\nℹ️ Bot gerçek emir/hesap takibi yapmadığından bu değerler yalnızca yerel kayıtları gösterir.",
                chat_id
            )

        elif clean == "/pozisyonlar":
            with DB_LOCK:
                conn = db_connect()
                try:
                    rows = conn.execute("""SELECT symbol, side, entry, sl, tp, risk
                        FROM positions WHERE status = 'OPEN' ORDER BY id DESC""").fetchall()
                finally:
                    conn.close()
            if not rows:
                telegram_send("📂 <b>AÇIK POZİSYONLAR</b>\nKayıtlı açık pozisyon yok.", chat_id)
                return
            text = "📂 <b>KAYITLI AÇIK POZİSYONLAR</b>\n\n"
            for symbol, side, entry, sl, tp, risk in rows:
                digits = SYMBOL_CONFIG.get(symbol, {}).get("digits", 5)
                icon = "🟢" if side == "BUY" else "🔴"
                text += (f"{icon} <b>{html.escape(str(symbol))}</b> | {html.escape(str(side))}\n"
                         f"Entry: {format_price(entry, digits)} | SL: {format_price(sl, digits)} | TP: {format_price(tp, digits)}\n"
                         f"Risk kaydı: ${float(risk or 0):.2f}\n\n")
            telegram_send(text, chat_id)

        elif clean == "/fiyat":
            telegram_send("💹 Fiyatlar alınıyor; Yahoo Finance verileri broker kotasyonundan farklı olabilir.", chat_id)
            lines = []
            for symbol, cfg in SYMBOL_CONFIG.items():
                try:
                    data = yf.download(cfg["yf"], period="1d", interval="1m", progress=False,
                                       auto_adjust=False, threads=False)
                    if data is None or data.empty:
                        lines.append(f"⚪ <b>{symbol}</b>: veri yok")
                        continue
                    if isinstance(data.columns, pd.MultiIndex):
                        data.columns = data.columns.get_level_values(0)
                    close = data["Close"].dropna()
                    if close.empty:
                        lines.append(f"⚪ <b>{symbol}</b>: veri yok")
                    else:
                        lines.append(f"💱 <b>{symbol}</b>: {format_price(close.iloc[-1], cfg['digits'])}")
                except Exception:
                    logger.exception("/fiyat veri hatası: %s", symbol)
                    lines.append(f"⚠️ <b>{symbol}</b>: hata")
            telegram_send("💹 <b>GÜNCEL FİYATLAR</b>\n\n" + "\n".join(lines), chat_id)

        elif clean == "/sinyaller":
            telegram_send("📡 <b>SİNYAL MOTORU</b>\n4 teknik kontrolden en az 3'ü aynı yöndeyse sinyal üretir: EMA, RSI, MACD ve 1H trend. Bu prototip backtest/doğrulama garantisi vermez.", chat_id)

        elif clean == "/test":
            telegram_send("🔎 <b>8 sembol için tarama başladı.</b> Veri sağlayıcısına bağlı olarak biraz sürebilir.", chat_id)
            signals = get_signal_preview()
            if not signals:
                telegram_send("ℹ️ <b>Sonuç:</b> Şartları sağlayan sinyal bulunamadı veya veri alınamadı. Render loglarını kontrol et.", chat_id)
            else:
                for signal in signals:
                    telegram_send(format_signal_message(signal), chat_id)
                    time.sleep(0.4)

        elif clean == "/istatistik":
            with DB_LOCK:
                conn = db_connect()
                try:
                    row = conn.execute("SELECT COUNT(*), COALESCE(SUM(pnl), 0) FROM closed_trades").fetchone()
                finally:
                    conn.close()
            trades = int(row[0] or 0) if row else 0
            pnl = float(row[1] or 0.0) if row else 0.0
            telegram_send(f"📊 <b>İSTATİSTİK</b>\nKapanan kayıtlı işlem: {trades}\nToplam kayıtlı P&amp;L: {format_signed_pnl(pnl)}\nℹ️ MT5 işlemleri otomatik içe aktarılmadığından bu, yalnızca veritabanındaki işlemlerdir.", chat_id)

        elif clean == "/reset":
            set_state("paused", 0)
            telegram_send("♻️ <b>SİSTEM</b>: Tarama duraklatma bayrağı kaldırıldı.", chat_id)

        else:
            telegram_send("❓ Bilinmeyen komut. /start yazabilirsin.", chat_id)

    except Exception:
        logger.exception("Komut işleme hatası: %s", clean)
        telegram_send("⚠️ Komut işlenirken hata oluştu. Render Logs bölümünü kontrol et.", chat_id)

# ============================================================
# TELEGRAM POLLER
# ============================================================

def telegram_poller():
    offset = None
    session = requests.Session()
    while True:
        if not TELEGRAM_TOKEN:
            logger.error("Telegram poller beklemede: TELEGRAM_TOKEN yok.")
            time.sleep(30)
            continue
        try:
            url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/getUpdates"
            params = {"timeout": 25}
            if offset is not None:
                params["offset"] = offset
            response = session.get(url, params=params, timeout=35)
            if response.status_code == 429:
                try:
                    retry_after = int(response.json().get("parameters", {}).get("retry_after", 10))
                except (ValueError, TypeError):
                    retry_after = 10
                logger.warning("Telegram poller 429; %s sn bekleniyor.", retry_after)
                time.sleep(max(5, min(retry_after, 120)))
                continue
            response.raise_for_status()
            data = response.json()
            if not data.get("ok"):
                logger.error("getUpdates Telegram hatası: %s", data)
                time.sleep(5)
                continue
            for update in data.get("result", []):
                offset = update["update_id"] + 1
                message = update.get("message")
                if not message:
                    continue
                chat_id = message.get("chat", {}).get("id")
                text = (message.get("text") or "").strip()
                if not text.startswith("/"):
                    continue
                parts = text.split(maxsplit=1)
                args = parts[1] if len(parts) > 1 else ""
                handle_telegram_command(chat_id, parts[0], args)
        except requests.RequestException:
            logger.exception("Telegram poller ağ/HTTP hatası")
            time.sleep(8)
        except Exception:
            logger.exception("Telegram poller beklenmeyen hata")
            time.sleep(8)

# ============================================================
# STRATEGY LOOP
# ============================================================

def bot_loop():
    logger.info("Strateji döngüsü başladı.")
    while True:
        try:
            if get_state("paused", 0.0) == 1.0:
                time.sleep(LOOP_SECONDS)
                continue

            for symbol in SYMBOL_CONFIG:
                try:
                    market_status, reason = get_market_status(symbol)
                    if market_status == "KAPALI":
                        logger.info("%s taranmadı: %s", symbol, reason)
                        continue
                    signal = generate_signal(symbol)
                    if signal is None:
                        continue
                    if not can_send_signal(symbol):
                        continue
                    if telegram_send(format_signal_message(signal)):
                        mark_signal_sent(symbol)
                        logger.info("%s %s sinyali Telegram'a gönderildi.", symbol, signal["action"])
                    else:
                        logger.error("%s sinyali gönderilemedi; cooldown işaretlenmedi.", symbol)
                except Exception:
                    logger.exception("%s tarama hatası", symbol)
        except Exception:
            logger.exception("Ana strateji döngüsü hatası")
        time.sleep(LOOP_SECONDS)

# ============================================================
# FLASK ROUTES — health sadece bir kez tanımlı
# ============================================================

@app.route("/", methods=["GET"])
def home():
    return jsonify({"bot": APP_NAME, "version": VERSION, "status": "online"}), 200


@app.route("/ping", methods=["GET"])
def ping():
    return jsonify({"status": "ok", "bot": APP_NAME, "time": now_istanbul().isoformat()}), 200


@app.route("/health", methods=["GET"])
def health():
    return jsonify({
        "status": "ok",
        "bot": APP_NAME,
        "version": VERSION,
        "simulation_mode": SIMULATION_MODE,
        "time": now_istanbul().isoformat(),
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
        threading.Thread(target=bot_loop, daemon=True, name="strategy-loop").start()
        threading.Thread(target=telegram_poller, daemon=True, name="telegram-poller").start()
        _bg_started = True
        logger.info("Arka plan servisleri başlatıldı.")


def startup():
    init_db()
    if get_state("balance", None) is None:
        set_state("balance", INITIAL_BALANCE)
    set_telegram_commands()
    start_background_services()


if __name__ == "__main__":
    startup()
    app.run(host=WEB_HOST, port=WEB_PORT, debug=False, use_reloader=False)
else:
    # Gunicorn/Render import ettiğinde de servisleri başlat.
    startup()
