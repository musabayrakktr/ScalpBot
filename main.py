import os
import time
import sqlite3
import threading
import logging
from datetime import datetime, timezone, timedelta

import requests
import yfinance as yf
import pandas as pd
import ta

from flask import Flask, jsonify


# ============================================================
# LOGGING
# ============================================================

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s"
)

logger = logging.getLogger("ScalpBot")


# ============================================================
# FLASK
# ============================================================

app = Flask(__name__)


@app.route("/")
def home():
    return jsonify({
        "status": "active",
        "bot": "ScalpBot V2",
        "time": datetime.now(timezone.utc).isoformat()
    }), 200


@app.route("/health")
def health():
    return jsonify({
        "status": "healthy"
    }), 200


# ============================================================
# GÜVENLİ AYARLAR
# ============================================================

TELEGRAM_TOKEN = YENİ_BOT_TOKENIN
CHAT_ID = 8982017587


# ============================================================
# HESAP / RİSK
# ============================================================

HESAP_BAKIYESI = 3000.0
RISK_YUZDESI = 0.01

AUTO_TRADE_AKTIF = False

MAX_GUNLUK_SINYAL = 10
COOLDOWN_SURESI = 900  # 15 dakika

TIMEFRAME = "5m"

# Aynı anda kaç farklı işlem tutulabilir?
MAX_AKTIF_ISLEM = 3


# ============================================================
# PARİTELER
# ============================================================

FOREX_PARITELERI = {

    "EURUSD=X": (
        "EUR/USD",
        "FX:EURUSD"
    ),

    "GBPUSD=X": (
        "GBP/USD",
        "FX:GBPUSD"
    ),

    "GC=F": (
        "ALTIN / GC FUTURES",
        "COMEX:GC1!"
    ),

    "JPY=X": (
        "USD/JPY",
        "FX:USDJPY"
    ),

    "AUDUSD=X": (
        "AUD/USD",
        "FX:AUDUSD"
    )
}


# ============================================================
# GLOBAL DURUM
# ============================================================

SON_SINYALLER = {}

GUNLUK_SINYAL_SAYISI = 0
GUNLUK_KAPANAN_ISLEM = 0
GUNLUK_KAZANC = 0.0

RAPOR_GONDERILDI = False

LAST_UPDATE_ID = 0

ACILIS_UYARI_LONDRA = False
ACILIS_UYARI_NY = False

LOCK = threading.Lock()


# ============================================================
# DATABASE
# ============================================================

DB_NAME = "scalping.db"


def db_init():

    conn = sqlite3.connect(DB_NAME)

    cursor = conn.cursor()

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS trades (

            id INTEGER PRIMARY KEY AUTOINCREMENT,

            ticker TEXT NOT NULL,

            isim TEXT NOT NULL,

            yon TEXT NOT NULL,

            entry REAL NOT NULL,

            sl REAL NOT NULL,

            tp1 REAL NOT NULL,
            tp2 REAL NOT NULL,
            tp3 REAL NOT NULL,

            lot REAL NOT NULL,

            tp1_hit INTEGER DEFAULT 0,
            tp2_hit INTEGER DEFAULT 0,
            tp3_hit INTEGER DEFAULT 0,

            status TEXT DEFAULT 'OPEN',

            result_r REAL DEFAULT 0,

            created_at TEXT NOT NULL,
            closed_at TEXT

        )
    """)

    conn.commit()
    conn.close()


def db_get_open_trade(ticker):

    conn = sqlite3.connect(DB_NAME)

    cursor = conn.cursor()

    cursor.execute("""
        SELECT
            id,
            ticker,
            isim,
            yon,
            entry,
            sl,
            tp1,
            tp2,
            tp3,
            lot,
            tp1_hit,
            tp2_hit,
            tp3_hit
        FROM trades
        WHERE ticker = ?
        AND status = 'OPEN'
        ORDER BY id DESC
        LIMIT 1
    """, (ticker,))

    row = cursor.fetchone()

    conn.close()

    if not row:
        return None

    return {
        "id": row[0],
        "ticker": row[1],
        "isim": row[2],
        "yon": row[3],
        "entry": row[4],
        "sl": row[5],
        "tp1": row[6],
        "tp2": row[7],
        "tp3": row[8],
        "lot": row[9],
        "tp1_hit": bool(row[10]),
        "tp2_hit": bool(row[11]),
        "tp3_hit": bool(row[12])
    }


def db_open_trade(
    ticker,
    isim,
    yon,
    entry,
    sl,
    tp1,
    tp2,
    tp3,
    lot
):

    conn = sqlite3.connect(DB_NAME)

    cursor = conn.cursor()

    cursor.execute("""
        INSERT INTO trades (
            ticker,
            isim,
            yon,
            entry,
            sl,
            tp1,
            tp2,
            tp3,
            lot,
            created_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        ticker,
        isim,
        yon,
        entry,
        sl,
        tp1,
        tp2,
        tp3,
        lot,
        datetime.now(timezone.utc).isoformat()
    ))

    conn.commit()
    conn.close()


def db_update_tp(trade_id, field):

    conn = sqlite3.connect(DB_NAME)

    cursor = conn.cursor()

    cursor.execute(
        f"UPDATE trades SET {field} = 1 WHERE id = ?",
        (trade_id,)
    )

    conn.commit()
    conn.close()


def db_close_trade(trade_id, result_r):

    conn = sqlite3.connect(DB_NAME)

    cursor = conn.cursor()

    cursor.execute("""
        UPDATE trades
        SET
            status = 'CLOSED',
            result_r = ?,
            closed_at = ?
        WHERE id = ?
    """, (
        result_r,
        datetime.now(timezone.utc).isoformat(),
        trade_id
    ))

    conn.commit()
    conn.close()


def db_count_open():

    conn = sqlite3.connect(DB_NAME)

    cursor = conn.cursor()

    cursor.execute("""
        SELECT COUNT(*)
        FROM trades
        WHERE status = 'OPEN'
    """)

    result = cursor.fetchone()[0]

    conn.close()

    return result


# ============================================================
# TELEGRAM
# ============================================================

def telegram_mesaj_gonder(mesaj):

    if not TELEGRAM_TOKEN or not CHAT_ID:
        logger.warning("Telegram ayarları eksik.")
        return False

    url = (
        f"https://api.telegram.org/"
        f"bot{TELEGRAM_TOKEN}/sendMessage"
    )

    payload = {
        "chat_id": CHAT_ID,
        "text": mesaj,
        "parse_mode": "Markdown",
        "disable_web_page_preview": True
    }

    try:

        response = requests.post(
            url,
            json=payload,
            timeout=10
        )

        if response.status_code != 200:
            logger.warning(
                "Telegram HTTP %s: %s",
                response.status_code,
                response.text
            )

            return False

        return True

    except Exception as e:

        logger.error(
            "Telegram mesaj hatası: %s",
            e
        )

        return False


def telegram_komutlari_ayarla():

    if not TELEGRAM_TOKEN:
        return

    url = (
        f"https://api.telegram.org/"
        f"bot{TELEGRAM_TOKEN}/setMyCommands"
    )

    commands = [

        {
            "command": "start",
            "description": "🚀 Kontrol Paneli"
        },

        {
            "command": "fiyat",
            "description": "📊 Canlı Fiyatlar"
        },

        {
            "command": "durum",
            "description": "⚡ Bot Durumu"
        },

        {
            "command": "oto",
            "description": "🤖 Paper/Auto Durumu"
        },

        {
            "command": "tv",
            "description": "🌐 TradingView"
        },

        {
            "command": "bakiye",
            "description": "💰 Demo Bakiye"
        },

        {
            "command": "pozisyon",
            "description": "📌 Aktif Pozisyon"
        }
    ]

    try:

        requests.post(
            url,
            json={"commands": commands},
            timeout=10
        )

    except Exception as e:

        logger.error(
            "Telegram komut ayarlama hatası: %s",
            e
        )


# ============================================================
# FİYAT
# ============================================================

def veri_getir(ticker_symbol):

    try:

        ticker = yf.Ticker(ticker_symbol)

        df = ticker.history(
            period="2d",
            interval=TIMEFRAME,
            auto_adjust=False
        )

        if df.empty:
            return None

        df = df.dropna(
            subset=["Close"]
        )

        if len(df) < 50:
            return None

        return df

    except Exception as e:

        logger.error(
            "%s veri hatası: %s",
            ticker_symbol,
            e
        )

        return None


# ============================================================
# LOT HESAPLAMA
# ============================================================

def lot_hesapla(
    fiyat,
    sl,
    ticker_symbol
):

    risk_para = (
        HESAP_BAKIYESI *
        RISK_YUZDESI
    )

    stop_mesafesi = abs(
        fiyat - sl
    )

    if stop_mesafesi <= 0:
        return 0.01

    # ALTIN
    #
    # GC futures için yaklaşık
    # contract size = 100 oz.
    #
    if ticker_symbol == "GC=F":

        zarar_1_lot = (
            stop_mesafesi *
            100
        )

    # USD/JPY
    #
    # Yaklaşık USD dönüşümü.
    elif ticker_symbol == "JPY=X":

        zarar_jpy = (
            stop_mesafesi *
            100000
        )

        # JPY -> USD yaklaşık
        # USDJPY = fiyat
        zarar_1_lot = (
            zarar_jpy /
            fiyat
        )

    # EURUSD / GBPUSD / AUDUSD
    #
    # USD quote currency.
    else:

        zarar_1_lot = (
            stop_mesafesi *
            100000
        )

    if zarar_1_lot <= 0:
        return 0.01

    lot = (
        risk_para /
        zarar_1_lot
    )

    # Broker lot adımına göre
    # iki basamaklı yuvarlama
    lot = round(lot, 2)

    return max(
        lot,
        0.01
    )


# ============================================================
# GÖSTERGE HESAPLAMA
# ============================================================

def indikatörleri_hesapla(df):

    df = df.copy()

    df["EMA9"] = ta.trend.ema_indicator(
        df["Close"],
        window=9
    )

    df["EMA21"] = ta.trend.ema_indicator(
        df["Close"],
        window=21
    )

    df["RSI"] = ta.momentum.rsi(
        df["Close"],
        window=14
    )

    macd = ta.trend.MACD(
        df["Close"],
        window_fast=12,
        window_slow=26,
        window_sign=9
    )

    df["MACD"] = macd.macd()

    df["MACD_SIGNAL"] = (
        macd.macd_signal()
    )

    df["MACD_DIFF"] = (
        macd.macd_diff()
    )

    return df.dropna()


# ============================================================
# SİNYAL
# ============================================================

def sinyal_uret(df):

    if len(df) < 3:
        return None

    son = df.iloc[-1]
    onceki = df.iloc[-2]

    buy = (

        onceki["EMA9"] <=
        onceki["EMA21"]

        and

        son["EMA9"] >
        son["EMA21"]

        and

        son["RSI"] > 50

        and

        son["MACD_DIFF"] > 0
    )

    sell = (

        onceki["EMA9"] >=
        onceki["EMA21"]

        and

        son["EMA9"] <
        son["EMA21"]

        and

        son["RSI"] < 50

        and

        son["MACD_DIFF"] < 0
    )

    if buy:
        return "BUY"

    if sell:
        return "SELL"

    return None


# ============================================================
# TP / SL
# ============================================================

def tp_sl_olustur(
    fiyat,
    yon,
    ticker_symbol
):

    # Altın daha geniş stop
    if ticker_symbol == "GC=F":

        sl_rate = 0.0030

    else:

        sl_rate = 0.0015


    if yon == "BUY":

        sl = fiyat * (
            1 - sl_rate
        )

        risk = (
            fiyat - sl
        )

        tp1 = fiyat + risk
        tp2 = fiyat + risk * 2
        tp3 = fiyat + risk * 3

    else:

        sl = fiyat * (
            1 + sl_rate
        )

        risk = (
            sl - fiyat
        )

        tp1 = fiyat - risk
        tp2 = fiyat - risk * 2
        tp3 = fiyat - risk * 3


    # Altın / FX hassasiyeti
    if ticker_symbol == "GC=F":

        precision = 2

    else:

        precision = 4


    return (
        round(sl, precision),
        round(tp1, precision),
        round(tp2, precision),
        round(tp3, precision)
    )


# ============================================================
# AKTİF POZİSYON TAKİBİ
# ============================================================

def tp_sl_kontrol_et(
    ticker,
    fiyat
):

    trade = db_get_open_trade(
        ticker
    )

    if not trade:
        return


    yon = trade["yon"]

    isim = trade["isim"]

    trade_id = trade["id"]


    # ========================================================
    # BUY
    # ========================================================

    if yon == "BUY":

        # TP1
        if (
            fiyat >= trade["tp1"]
            and not trade["tp1_hit"]
        ):

            db_update_tp(
                trade_id,
                "tp1_hit"
            )

            telegram_mesaj_gonder(
                f"🎯 *TP1 GELDİ!*\n\n"
                f"📌 {isim}\n"
                f"💰 Fiyat: `{fiyat}`\n\n"
                f"🛡️ Stop Loss'u girişe "
                f"`{trade['entry']}` çek."
            )

            return


        # TP2
        if (
            fiyat >= trade["tp2"]
            and not trade["tp2_hit"]
        ):

            db_update_tp(
                trade_id,
                "tp2_hit"
            )

            telegram_mesaj_gonder(
                f"🚀 *TP2 GELDİ!*\n\n"
                f"📌 {isim}\n"
                f"💰 Fiyat: `{fiyat}`\n\n"
                f"🎯 2R hedef gerçekleşti."
            )

            return


        # TP3
        if (
            fiyat >= trade["tp3"]
            and not trade["tp3_hit"]
        ):

            db_update_tp(
                trade_id,
                "tp3_hit"
            )

            db_close_trade(
                trade_id,
                3.0
            )

            telegram_mesaj_gonder(
                f"🔥 *TP3 GELDİ!*\n\n"
                f"📌 {isim}\n"
                f"💰 Fiyat: `{fiyat}`\n"
                f"🏆 Son hedef gerçekleşti.\n"
                f"📈 Sonuç: `+3R`"
            )

            return


        # STOP
        if fiyat <= trade["sl"]:

            db_close_trade(
                trade_id,
                -1.0
            )

            telegram_mesaj_gonder(
                f"🔴 *STOP LOSS!*\n\n"
                f"📌 {isim}\n"
                f"📉 Fiyat: `{fiyat}`\n"
                f"❌ Sonuç: `-1R`"
            )

            return


    # ========================================================
    # SELL
    # ========================================================

    else:

        # TP1
        if (
            fiyat <= trade["tp1"]
            and not trade["tp1_hit"]
        ):

            db_update_tp(
                trade_id,
                "tp1_hit"
            )

            telegram_mesaj_gonder(
                f"🎯 *TP1 GELDİ!*\n\n"
                f"📌 {isim}\n"
                f"💰 Fiyat: `{fiyat}`\n\n"
                f"🛡️ Stop Loss'u girişe "
                f"`{trade['entry']}` çek."
            )

            return


        # TP2
        if (
            fiyat <= trade["tp2"]
            and not trade["tp2_hit"]
        ):

            db_update_tp(
                trade_id,
                "tp2_hit"
            )

            telegram_mesaj_gonder(
                f"🚀 *TP2 GELDİ!*\n\n"
                f"📌 {isim}\n"
                f"💰 Fiyat: `{fiyat}`\n\n"
                f"🎯 2R hedef gerçekleşti."
            )

            return


        # TP3
        if (
            fiyat <= trade["tp3"]
            and not trade["tp3_hit"]
        ):

            db_update_tp(
                trade_id,
                "tp3_hit"
            )

            db_close_trade(
                trade_id,
                3.0
            )

            telegram_mesaj_gonder(
                f"🔥 *TP3 GELDİ!*\n\n"
                f"📌 {isim}\n"
                f"💰 Fiyat: `{fiyat}`\n"
                f"🏆 Son hedef gerçekleşti.\n"
                f"📈 Sonuç: `+3R`"
            )

            return


        # STOP
        if fiyat >= trade["sl"]:

            db_close_trade(
                trade_id,
                -1.0
            )

            telegram_mesaj_gonder(
                f"🔴 *STOP LOSS!*\n\n"
                f"📌 {isim}\n"
                f"📈 Fiyat: `{fiyat}`\n"
                f"❌ Sonuç: `-1R`"
            )

            return


# ============================================================
# PARİTE TARAMA
# ============================================================

def forex_parite_tara(
    ticker_symbol,
    isim_tuple
):

    global GUNLUK_SINYAL_SAYISI

    isim, tv_symbol = isim_tuple

    try:

        df = veri_getir(
            ticker_symbol
        )

        if df is None:
            return


        fiyat = float(
            df["Close"].iloc[-1]
        )


        if ticker_symbol == "GC=F":

            fiyat = round(
                fiyat,
                2
            )

        else:

            fiyat = round(
                fiyat,
                5
            )


        # ----------------------------------------------------
        # ÖNCE AKTİF POZİSYONU KONTROL ET
        # ----------------------------------------------------

        tp_sl_kontrol_et(
            ticker_symbol,
            fiyat
        )


        # ----------------------------------------------------
        # AKTİF POZİSYON VARSA YENİ SİNYAL ÜRETME
        # ----------------------------------------------------

        if db_get_open_trade(
            ticker_symbol
        ):

            return


        # ----------------------------------------------------
        # COOLDOWN
        # ----------------------------------------------------

        simdi = time.time()

        if (
            ticker_symbol in SON_SINYALLER
            and
            simdi -
            SON_SINYALLER[ticker_symbol]
            < COOLDOWN_SURESI
        ):

            return


        # ----------------------------------------------------
        # GÜNLÜK SİNYAL SINIRI
        # ----------------------------------------------------

        if (
            GUNLUK_SINYAL_SAYISI
            >= MAX_GUNLUK_SINYAL
        ):

            return


        # ----------------------------------------------------
        # İNDİKATÖRLER
        # ----------------------------------------------------

        df = indikatörleri_hesapla(
            df
        )

        yon = sinyal_uret(
            df
        )

        if not yon:
            return


        # ----------------------------------------------------
        # TP / SL
        # ----------------------------------------------------

        sl, tp1, tp2, tp3 = (
            tp_sl_olustur(
                fiyat,
                yon,
                ticker_symbol
            )
        )


        # ----------------------------------------------------
        # LOT
        # ----------------------------------------------------

        lot = lot_hesapla(
            fiyat,
            sl,
            ticker_symbol
        )


        rsi = round(
            float(df["RSI"].iloc[-1]),
            2
        )


        # ----------------------------------------------------
        # HACİM ZAMANI
        # ----------------------------------------------------

        simdi_tr = (
            datetime.now(timezone.utc)
            +
            timedelta(hours=3)
        )

        hacim_etiketi = ""

        if simdi_tr.hour in [
            10,
            11,
            15,
            16,
            17
        ]:

            hacim_etiketi = (
                " 🔥 *[AKTİF SAAT]*"
            )


        tv_link = (
            f"https://www.tradingview.com/"
            f"chart/?symbol={tv_symbol}"
        )


        # ----------------------------------------------------
        # MESAJ
        # ----------------------------------------------------

        if yon == "BUY":

            mesaj = (
                f"🚨 *SCALP SİNYALİ — LONG*"
                f"{hacim_etiketi}\n\n"

                f"📌 *Parite:* {isim}\n"

                f"🟢 *Giriş:* `{fiyat}`\n"

                f"💵 *Lot:* `{lot}`\n"

                f"🛑 *SL:* `{sl}`\n\n"

                f"🎯 *TP1:* `{tp1}`\n"
                f"🎯 *TP2:* `{tp2}`\n"
                f"🎯 *TP3:* `{tp3}`\n\n"

                f"📊 *RSI:* `{rsi}`\n"

                f"⚠️ *Risk:* "
                f"`%{RISK_YUZDESI * 100:.1f}`\n\n"

                f"🔗 [TradingView]({tv_link})"
            )

        else:

            mesaj = (
                f"🚨 *SCALP SİNYALİ — SHORT*"
                f"{hacim_etiketi}\n\n"

                f"📌 *Parite:* {isim}\n"

                f"🔴 *Giriş:* `{fiyat}`\n"

                f"💵 *Lot:* `{lot}`\n"

                f"🛑 *SL:* `{sl}`\n\n"

                f"🎯 *TP1:* `{tp1}`\n"
                f"🎯 *TP2:* `{tp2}`\n"
                f"🎯 *TP3:* `{tp3}`\n\n"

                f"📊 *RSI:* `{rsi}`\n"

                f"⚠️ *Risk:* "
                f"`%{RISK_YUZDESI * 100:.1f}`\n\n"

                f"🔗 [TradingView]({tv_link})"
            )


        telegram_mesaj_gonder(
            mesaj
        )


        # ----------------------------------------------------
        # DATABASE
        # ----------------------------------------------------

        db_open_trade(
            ticker_symbol,
            isim,
            yon,
            fiyat,
            sl,
            tp1,
            tp2,
            tp3,
            lot
        )


        SON_SINYALLER[
            ticker_symbol
        ] = simdi


        GUNLUK_SINYAL_SAYISI += 1


        logger.info(
            "Sinyal: %s %s @ %s",
            isim,
            yon,
            fiyat
        )


    except Exception as e:

        logger.exception(
            "%s tarama hatası: %s",
            isim,
            e
        )


# ============================================================
# DURUM RAPORU
# ============================================================

def anlik_durum_raporu():

    oto_durum = (
        "🟢 AÇIK"
        if AUTO_TRADE_AKTIF
        else
        "🔴 KAPALI"
    )

    rapor = (
        f"📊 *SCALPBOT CANLI DURUM*\n\n"
        f"💰 Bakiye: `${HESAP_BAKIYESI:.2f}`\n"
        f"🤖 Oto İşlem: {oto_durum}\n"
        f"📌 Açık İşlem: `{db_count_open()}`\n"
        f"📈 Günlük Sinyal: "
        f"`{GUNLUK_SINYAL_SAYISI}`\n\n"
    )


    for ticker, info in FOREX_PARITELERI.items():

        isim, _ = info

        try:

            df = veri_getir(
                ticker
            )

            if df is None:
                rapor += (
                    f"⚠️ *{isim}:* "
                    f"Veri yok\n"
                )

                continue


            fiyat = float(
                df["Close"].iloc[-1]
            )

            rsi = float(
                ta.momentum.rsi(
                    df["Close"],
                    window=14
                ).iloc[-1]
            )


            rapor += (
                f"📌 *{isim}*\n"
                f"💰 `{fiyat:.5f}`\n"
                f"📊 RSI: `{rsi:.2f}`\n\n"
            )


        except Exception:

            rapor += (
                f"⚠️ *{isim}:* "
                f"Veri alınamadı\n"
            )


    return rapor


# ============================================================
# POZİSYON RAPORU
# ============================================================

def pozisyon_raporu():

    conn = sqlite3.connect(
        DB_NAME
    )

    cursor = conn.cursor()

    cursor.execute("""
        SELECT
            isim,
            yon,
            entry,
            sl,
            tp1,
            tp2,
            tp3,
            lot
        FROM trades
        WHERE status = 'OPEN'
    """)

    rows = cursor.fetchall()

    conn.close()


    if not rows:

        return (
            "📌 *Aktif Pozisyon Yok.*"
        )


    mesaj = (
        "📌 *AKTİF POZİSYONLAR*\n\n"
    )


    for row in rows:

        (
            isim,
            yon,
            entry,
            sl,
            tp1,
            tp2,
            tp3,
            lot
        ) = row

        emoji = (
            "🟢"
            if yon == "BUY"
            else
            "🔴"
        )

        mesaj += (
            f"{emoji} *{isim} — {yon}*\n"
            f"Entry: `{entry}`\n"
            f"SL: `{sl}`\n"
            f"TP1: `{tp1}`\n"
            f"TP2: `{tp2}`\n"
            f"TP3: `{tp3}`\n"
            f"Lot: `{lot}`\n\n"
        )


    return mesaj


# ============================================================
# TELEGRAM KOMUT DİNLEYİCİ
# ============================================================

def telegram_komut_dinleyici():

    global LAST_UPDATE_ID
    global HESAP_BAKIYESI
    global AUTO_TRADE_AKTIF

    if not TELEGRAM_TOKEN:
        return


    url = (
        f"https://api.telegram.org/"
        f"bot{TELEGRAM_TOKEN}/getUpdates"
    )


    while True:

        try:

            response = requests.get(
                url,
                params={
                    "offset":
                    LAST_UPDATE_ID + 1,

                    "timeout": 5
                },
                timeout=10
            )


            data = response.json()


            for update in data.get(
                "result",
                []
            ):

                LAST_UPDATE_ID = (
                    update["update_id"]
                )


                message = update.get(
                    "message"
                )

                if not message:
                    continue


                text = message.get(
                    "text",
                    ""
                ).strip()


                # ==================================================
                # START
                # ==================================================

                if text in [
                    "/start",
                    "/menu"
                ]:

                    telegram_mesaj_gonder(
                        f"🤖 *ScalpBot V2*\n\n"

                        f"💰 Bakiye: "
                        f"`${HESAP_BAKIYESI:.2f}`\n"

                        f"📌 Açık işlem: "
                        f"`{db_count_open()}`\n"

                        f"📈 Günlük sinyal: "
                        f"`{GUNLUK_SINYAL_SAYISI}`\n\n"

                        f"/fiyat — Canlı fiyatlar\n"
                        f"/durum — Bot durumu\n"
                        f"/pozisyon — Açık işlemler\n"
                        f"/tv — TradingView\n"
                        f"/bakiye 3000 — Bakiye değiştir\n"
                        f"/oto — Sistem durumu"
                    )


                # ==================================================
                # FİYAT
                # ==================================================

                elif text in [
                    "/fiyat",
                    "/analiz"
                ]:

                    telegram_mesaj_gonder(
                        anlik_durum_raporu()
                    )


                # ==================================================
                # DURUM
                # ==================================================

                elif text == "/durum":

                    telegram_mesaj_gonder(

                        f"⚡ *BOT DURUMU*\n\n"

                        f"🟢 Sistem: Aktif\n"

                        f"💰 Bakiye: "
                        f"`${HESAP_BAKIYESI:.2f}`\n"

                        f"📌 Açık işlem: "
                        f"`{db_count_open()}`\n"

                        f"📈 Günlük sinyal: "
                        f"`{GUNLUK_SINYAL_SAYISI}`\n"

                        f"🛡️ Risk: "
                        f"`%{RISK_YUZDESI * 100:.1f}`"
                    )


                # ==================================================
                # POZİSYON
                # ==================================================

                elif text == "/pozisyon":

                    telegram_mesaj_gonder(
                        pozisyon_raporu()
                    )


                # ==================================================
                # TRADINGVIEW
                # ==================================================

                elif text == "/tv":

                    links = (
                        "🌐 *TRADINGVIEW*\n\n"
                    )

                    for ticker, info in (
                        FOREX_PARITELERI.items()
                    ):

                        isim, symbol = info

                        link = (
                            f"https://www.tradingview.com/"
                            f"chart/?symbol={symbol}"
                        )

                        links += (
                            f"📌 [{isim}]"
                            f"({link})\n"
                        )


                    telegram_mesaj_gonder(
                        links
                    )


                # ==================================================
                # OTO
                # ==================================================

                elif text.startswith("/oto"):

                    parts = text.split()


                    if (
                        len(parts) > 1
                        and
                        parts[1].lower()
                        in [
                            "ac",
                            "aç",
                            "on"
                        ]
                    ):

                        AUTO_TRADE_AKTIF = True

                        telegram_mesaj_gonder(
                            "🤖 *Oto mod aktif.*\n\n"
                            "⚠️ Bu V2 sürümünde "
                            "broker'a gerçek emir gönderilmez. "
                            "Sinyal/paper-trading modu aktiftir."
                        )


                    elif (
                        len(parts) > 1
                        and
                        parts[1].lower()
                        in [
                            "kapat",
                            "off"
                        ]
                    ):

                        AUTO_TRADE_AKTIF = False

                        telegram_mesaj_gonder(
                            "🔴 *Oto mod kapatıldı.*"
                        )


                    else:

                        durum = (
                            "AÇIK 🟢"
                            if AUTO_TRADE_AKTIF
                            else
                            "KAPALI 🔴"
                        )

                        telegram_mesaj_gonder(
                            f"🤖 Oto mod: *{durum}*\n\n"
                            f"/oto ac\n"
                            f"/oto kapat"
                        )


                # ==================================================
                # BAKİYE
                # ==================================================

                elif text.startswith(
                    "/bakiye"
                ):

                    try:

                        yeni_bakiye = float(
                            text.split()[1]
                        )


                        if yeni_bakiye <= 0:

                            raise ValueError


                        HESAP_BAKIYESI = (
                            yeni_bakiye
                        )


                        telegram_mesaj_gonder(
                            f"✅ *Bakiye güncellendi.*\n\n"
                            f"💰 Yeni bakiye: "
                            f"`${HESAP_BAKIYESI:.2f}`\n"
                            f"🛡️ Risk: "
                            f"`%{RISK_YUZDESI * 100:.1f}`"
                        )


                    except Exception:

                        telegram_mesaj_gonder(
                            "⚠️ Örnek:\n"
                            "`/bakiye 3000`"
                        )


        except Exception as e:

            logger.error(
                "Telegram listener hatası: %s",
                e
            )


        time.sleep(1)


# ============================================================
# LONDRA / NEW YORK AÇILIŞ UYARISI
# ============================================================

def borsa_acilis_kontrol():

    global ACILIS_UYARI_LONDRA
    global ACILIS_UYARI_NY


    now_utc = datetime.now(
        timezone.utc
    )


    # Türkiye saati
    now_tr = (
        now_utc +
        timedelta(hours=3)
    )


    # Yaklaşık piyasa açılış pencereleri.
    #
    # Not:
    # Londra ve New York yaz/kış saati
    # nedeniyle sabit UTC değildir.


    # Londra:
    # UTC+1 yaz,
    # UTC kış
    #
    # Bu yüzden basit olarak
    # Avrupa saati hesabı yapıyoruz.

    month = now_utc.month


    # Yaklaşık DST
    # Mart-Ekim
    london_offset = (
        1
        if 3 <= month <= 10
        else 0
    )


    london_time = (
        now_utc +
        timedelta(hours=london_offset)
    )


    # Londra 08:00
    if (
        london_time.hour == 7
        and
        45 <= london_time.minute <= 59
    ):

        if not ACILIS_UYARI_LONDRA:

            telegram_mesaj_gonder(
                "🚨 *LONDRA AÇILIŞI YAKLAŞIYOR*\n\n"
                "Yaklaşık 15 dakika kaldı."
            )

            ACILIS_UYARI_LONDRA = True

    else:

        if london_time.hour != 7:

            ACILIS_UYARI_LONDRA = False


    # New York 09:30
    #
    # ABD DST:
    # Mart-Kasım yaklaşık UTC-4
    # kışın UTC-5

    ny_offset = (
        -4
        if 3 <= month <= 11
        else -5
    )


    ny_time = (
        now_utc +
        timedelta(hours=ny_offset)
    )


    if (
        ny_time.hour == 9
        and
        15 <= ny_time.minute <= 29
    ):

        if not ACILIS_UYARI_NY:

            telegram_mesaj_gonder(
                "🚨 *NEW YORK AÇILIŞI YAKLAŞIYOR*\n\n"
                "Yaklaşık 15 dakika kaldı."
            )

            ACILIS_UYARI_NY = True

    else:

        if ny_time.hour != 9:

            ACILIS_UYARI_NY = False


# ============================================================
# HAFTA SONU
# ============================================================

def hafta_sonu_mu():

    now = datetime.now(
        timezone.utc
    )

    weekday = now.weekday()

    # Cumartesi
    if weekday == 5:
        return True

    # Pazar
    if weekday == 6:
        return True

    # Cuma gece
    if (
        weekday == 4
        and
        now.hour >= 22
    ):
        return True

    return False


# ============================================================
# GÜNLÜK RAPOR
# ============================================================

def gunluk_rapor():

    global GUNLUK_SINYAL_SAYISI

    telegram_mesaj_gonder(

        f"📊 *GÜNLÜK RAPOR*\n\n"

        f"📈 Üretilen sinyal: "
        f"`{GUNLUK_SINYAL_SAYISI}`\n"

        f"📌 Açık işlem: "
        f"`{db_count_open()}`\n\n"

        f"⚠️ Bu istatistik "
        f"paper/sinyal takibidir."
    )


# ============================================================
# ANA WORKER
# ============================================================

def background_worker():

    global GUNLUK_SINYAL_SAYISI
    global RAPOR_GONDERILDI


    telegram_komutlari_ayarla()


    telegram_mesaj_gonder(
        "🚀 *ScalpBot V2 BAŞLADI!*\n\n"
        "📊 Teknik sinyal motoru aktif.\n"
        "🎯 TP/SL takip aktif.\n"
        "💾 SQLite pozisyon hafızası aktif.\n"
        "🛡️ %1 risk sistemi aktif.\n"
        "🤖 Gerçek emir gönderimi KAPALI."
    )


    while True:

        try:

            now_tr = (
                datetime.now(
                    timezone.utc
                )
                +
                timedelta(hours=3)
            )


            borsa_acilis_kontrol()


            # ==================================================
            # GÜNLÜK RAPOR
            # ==================================================

            if (
                now_tr.hour == 22
                and
                not RAPOR_GONDERILDI
            ):

                gunluk_rapor()

                RAPOR_GONDERILDI = True

            elif now_tr.hour != 22:

                RAPOR_GONDERILDI = False


            # ==================================================
            # HAFTA SONU
            # ==================================================

            if hafta_sonu_mu():

                time.sleep(60)

                continue


            # ==================================================
            # PARİTELER
            # ==================================================

            for ticker, info in (
                FOREX_PARITELERI.items()
            ):

                forex_parite_tara(
                    ticker,
                    info
                )

                time.sleep(2)


        except Exception as e:

            logger.exception(
                "Worker hatası: %s",
                e
            )


        # 30 saniyede bir tarama
        time.sleep(30)


# ============================================================
# MAIN
# ============================================================

if __name__ == "__main__":

    db_init()


    # Telegram
    threading.Thread(
        target=telegram_komut_dinleyici,
        daemon=True
    ).start()


    # Trading motoru
    threading.Thread(
        target=background_worker,
        daemon=True
    ).start()


    # Flask / Render
    port = int(
        os.environ.get(
            "PORT",
            10000
        )
    )


    app.run(
        host="0.0.0.0",
        port=port,
        debug=False,
        use_reloader=False
    )

@app.route("/health")
def health():
    return jsonify({
        "status": "ok",
        "bot": "ScalpBot Pro"
    }), 200
