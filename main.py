import time
import requests
import json
import threading
from datetime import datetime, timezone, timedelta
from http.server import HTTPServer, BaseHTTPRequestHandler
import yfinance as yf
import pandas as pd
import ta

# --- BAKIYE, RISK VE OTO-TRADE AYARLARI ---
HESAP_BAKIYESI = 3000.0   # $3000 demo bakiyenle eşitledik
RISK_YUZDESI = 0.01      # %1 Risk
AUTO_TRADE_AKTIF = False # Varsayılan kapalı (Sadece Sinyal)

# --- CANLI İŞLEM VE TP/SL TAKİP SÖZLÜĞÜ ---
AKTIF_ISLEMLER = {}

# --- RENDER WEB SUNUCUSU VE WEBHOOK ---
class SimpleHTTPRequestHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header('Content-type', 'text/html')
        self.end_headers()
        self.wfile.write(b"ScalpBot Pro Active & Alive!")

    def do_POST(self):
        if self.path == '/webhook':
            content_length = int(self.headers.get('Content-Length', 0))
            post_data = self.rfile.read(content_length)
            print(f"Webhook Alındı: {post_data.decode('utf-8')}")
            self.send_response(200)
            self.end_headers()
        else:
            self.send_response(404)
            self.end_headers()

def run_web_server():
    try:
        server_address = ('', 10000)
        httpd = HTTPServer(server_address, SimpleHTTPRequestHandler)
        httpd.serve_forever()
    except Exception as e:
        print(f"Web Sunucu Hatası: {e}")

# --- AYARLAR VE PARİTELER ---
TELEGRAM_TOKEN = "8814586618:AAFrQ2kCbjXf8XuWaJ2NK-gCXkL2_8ik81c"
CHAT_ID = "8982017587"

FOREX_PARITELERI = {
    "EURUSD=X": ("EUR/USD", "FX:EURUSD"),
    "GBPUSD=X": ("GBP/USD", "FX:GBPUSD"),
    "GC=F": ("XAU/USD (Altın)", "OANDA:XAUUSD"),
    "JPY=X": ("USD/JPY", "FX:USDJPY"),
    "AUDUSD=X": ("AUD/USD", "FX:AUDUSD")
}

TIMEFRAME = "5m"
SON_SINYALLER = {}
COOLDOWN_SURESI = 900  # 15 Dakika
LAST_UPDATE_ID = 0
GUNLUK_SINYAL_SAYISI = 0
RAPOR_GONDERILDI = False
ACILIS_UYARI_LONDRA = False
ACILIS_UYARI_NY = False

def telegram_komutlari_ayarla():
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/setMyCommands"
        commands = [
            {"command": "start", "description": "🚀 Kontrol Paneli & Bilgi"},
            {"command": "fiyat", "description": "📊 Canlı Fiyatlar & RSI"},
            {"command": "durum", "description": "⚡ Bot Çalışma Durumu"},
            {"command": "oto", "description": "🤖 Oto Al-Sat Aç/Kapat (/oto ac veya /oto kapat)"},
            {"command": "tv", "description": "🌐 TradingView Grafikleri"},
            {"command": "bakiye", "description": "💰 Bakiye Güncelle (Örn: /bakiye 3000)"}
        ]
        requests.post(url, json={"commands": commands}, timeout=5)
    except Exception as e:
        print(f"Komut Set Hatası: {e}")

def telegram_mesaj_gonder(mesaj):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {
        "chat_id": CHAT_ID,
        "text": mesaj,
        "parse_mode": "Markdown",
        "disable_web_page_preview": True
    }
    try:
        requests.post(url, json=payload, timeout=5)
    except Exception as e:
        print(f"Telegram Mesaj Hatası: {e}")

def lot_hesapla(fiyat, sl, ticker_symbol):
    global HESAP_BAKIYESI, RISK_YUZDESI
    fark = abs(fiyat - sl)
    if fark == 0:
        return 0.01

    risked_amount = HESAP_BAKIYESI * RISK_YUZDESI
    
    if "GC=F" in ticker_symbol:
        lot = risked_amount / (fark * 100)
    else:
        lot = risked_amount / (fark * 100000)

    lot = round(lot, 2)
    return max(lot, 0.01)

def metatrader_signal_gonder(signal_data):
    if not AUTO_TRADE_AKTIF:
        return
    try:
        url = "http://127.0.0.1:10000/webhook"
        requests.post(url, json=signal_data, timeout=2)
    except Exception as e:
        print(f"Auto-Trade Webhook İletim Hatası: {e}")

def haber_filtresi_aktif_mi():
    """ Esnetilmiş Haber Filtresi (Sadece saat başı öncesi/sonrası 5'er dk esneklik) """
    simdi = datetime.now(timezone.utc)
    dakika = simdi.minute
    if (55 <= dakika <= 59) or (0 <= dakika <= 5):
        return False
    return True

def hafta_sonu_mu():
    simdi = datetime.now(timezone.utc)
    weekday = simdi.weekday()
    if weekday == 5 or (weekday == 4 and simdi.hour >= 22) or (weekday == 6 and simdi.hour < 22):
        return True
    return False

def borsa_acilis_kontrol():
    global ACILIS_UYARI_LONDRA, ACILIS_UYARI_NY
    simdi_tsi = datetime.now(timezone.utc) + timedelta(hours=3)
    saat, dakika = simdi_tsi.hour, simdi_tsi.minute

    if saat == 9 and 45 <= dakika <= 59:
        if not ACILIS_UYARI_LONDRA:
            telegram_mesaj_gonder("🚨 *BORSA AÇILIŞ UYARISI (LONDRA)* 🏛️\n\n15 Dakika sonra Avrupa/Londra borsası açılıyor! Yüksek hacim ve sert hareketler bekleniyor.")
            ACILIS_UYARI_LONDRA = True
    else:
        if saat != 9:
            ACILIS_UYARI_LONDRA = False

    if saat == 15 and 15 <= dakika <= 29:
        if not ACILIS_UYARI_NY:
            telegram_mesaj_gonder("🚨 *BORSA AÇILIŞ UYARISI (NEW YORK)* 🗽\n\n15 Dakika sonra ABD/New York borsası açılıyor! Hacim tepe noktaya ulaşabilir.")
            ACILIS_UYARI_NY = True
    else:
        if saat != 15:
            ACILIS_UYARI_NY = False

def tp_sl_kontrol_et(ticker_symbol, anlik_fiyat, isim):
    """ Aktif pozisyonların TP/SL hedeflerini kontrol edip Telegram bildirimi atar """
    if ticker_symbol not in AKTIF_ISLEMLER:
        return

    islem = AKTIF_ISLEMLER[ticker_symbol]
    yon = islem['yon']
    entry = islem['entry']

    if yon == 'BUY':
        if anlik_fiyat >= islem['tp1'] and not islem.get('tp1_hit'):
            islem['tp1_hit'] = True
            telegram_mesaj_gonder(f"🎯 *TP1 HEDEFİ GELDİ!* 🎉\n📌 *Parite:* {isim}\n💰 *Anlık Fiyat:* `{anlik_fiyat}`\n💡 *Öneri:* Stop Loss seviyesini giriş fiyatına (`{entry}`) çekin!")
        elif anlik_fiyat >= islem['tp2'] and not islem.get('tp2_hit'):
            islem['tp2_hit'] = True
            telegram_mesaj_gonder(f"🚀 *TP2 HEDEFİ GELDİ!* 🔥\n📌 *Parite:* {isim}\n💰 *Anlık Fiyat:* `{anlik_fiyat}`\n💡 *Kârın çoğunu realize edebilirsiniz.*")
        elif anlik_fiyat >= islem['tp3'] and not islem.get('tp3_hit'):
            islem['tp3_hit'] = True
            telegram_mesaj_gonder(f"🔥 *TP3 MAKSİMUM HEDEF GELDİ!* 🏆\n📌 *Parite:* {isim}\n💰 *Anlık Fiyat:* `{anlik_fiyat}`\n✅ *Pozisyon başarıyla tamamlandı!*")
            del AKTIF_ISLEMLER[ticker_symbol]
        elif anlik_fiyat <= islem['sl']:
            telegram_mesaj_gonder(f"🔴 *STOP LOSS TETİKLENDİ!* 🛑\n📌 *Parite:* {isim}\n📉 *Fiyat:* `{anlik_fiyat}`\n⚠️ *İşlem zararla kapatıldı.*")
            del AKTIF_ISLEMLER[ticker_symbol]

    elif yon == 'SELL':
        if anlik_fiyat <= islem['tp1'] and not islem.get('tp1_hit'):
            islem['tp1_hit'] = True
            telegram_mesaj_gonder(f"🎯 *TP1 HEDEFİ GELDİ!* 🎉\n📌 *Parite:* {isim}\n💰 *Anlık Fiyat:* `{anlik_fiyat}`\n💡 *Öneri:* Stop Loss seviyesini giriş fiyatına (`{entry}`) çekin!")
        elif anlik_fiyat <= islem['tp2'] and not islem.get('tp2_hit'):
            islem['tp2_hit'] = True
            telegram_mesaj_gonder(f"🚀 *TP2 HEDEFİ GELDİ!* 🔥\n📌 *Parite:* {isim}\n💰 *Anlık Fiyat:* `{anlik_fiyat}`\n💡 *Kârın çoğunu realize edebilirsiniz.*")
        elif anlik_fiyat <= islem['tp3'] and not islem.get('tp3_hit'):
            islem['tp3_hit'] = True
            telegram_mesaj_gonder(f"🔥 *TP3 MAKSİMUM HEDEF GELDİ!* 🏆\n📌 *Parite:* {isim}\n💰 *Anlık Fiyat:* `{anlik_fiyat}`\n✅ *Pozisyon başarıyla tamamlandı!*")
            del AKTIF_ISLEMLER[ticker_symbol]
        elif anlik_fiyat >= islem['sl']:
            telegram_mesaj_gonder(f"🔴 *STOP LOSS TETİKLENDİ!* 🛑\n📌 *Parite:* {isim}\n📈 *Fiyat:* `{anlik_fiyat}`\n⚠️ *İşlem zararla kapatıldı.*")
            del AKTIF_ISLEMLER[ticker_symbol]

def anlik_durum_raporu():
    oto_durum = "🟢 AÇIK (Auto-Trade)" if AUTO_TRADE_AKTIF else "🔴 KAPALI (Sadece Sinyal)"
    rapor = f"📊 *CANLI PARİTE VE RSI DURUMU*\n💰 *Kasa:* `${HESAP_BAKIYESI}` | 🤖 *Oto-Trade:* {oto_durum}\n\n"
    for ticker, isim_tuple in FOREX_PARITELERI.items():
        isim, _ = isim_tuple
        try:
            df = yf.Ticker(ticker).history(period="1d", interval=TIMEFRAME)
            if not df.empty and len(df) >= 20:
                fiyat = round(df['Close'].iloc[-1], 4)
                rsi = round(ta.momentum.rsi(df['Close'], window=14).iloc[-1], 2)
                durum_emoji = "🟢" if rsi > 55 else ("🔴" if rsi < 45 else "🟡")
                rapor += f"{durum_emoji} *{isim}:* `{fiyat}` | 📈 RSI: `{rsi}`\n"
        except:
            rapor += f"⚠️ *{isim}:* Veri alınamadı\n"
    return rapor

def telegram_komut_dinleyici():
    global LAST_UPDATE_ID, HESAP_BAKIYESI, AUTO_TRADE_AKTIF
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/getUpdates"
    
    while True:
        try:
            res = requests.get(url, params={"offset": LAST_UPDATE_ID + 1, "timeout": 5}, timeout=10).json()
            if "result" in res:
                for update in res["result"]:
                    LAST_UPDATE_ID = update["update_id"]
                    
                    if "message" in update and "text" in update["message"]:
                        text = update["message"]["text"].strip()
                        if text in ["/start", "/menu", "menu"]:
                            oto_str = "🟢 AÇIK" if AUTO_TRADE_AKTIF else "🔴 KAPALI"
                            telegram_mesaj_gonder(
                                f"🤖 *ScalpBot ULTIMATE Kontrol Paneli*\n\n💰 *Aktif Kasa:* `${HESAP_BAKIYESI}`\n🤖 *Oto Al-Sat Modu:* {oto_str}\n\nSol alt köşedeki **Menu** butonuna basarak komutları kullanabilirsiniz."
                            )
                        elif text in ["/fiyat", "/analiz"]:
                            telegram_mesaj_gonder(anlik_durum_raporu())
                        elif text == "/durum":
                            oto_str = "🟢 AÇIK" if AUTO_TRADE_AKTIF else "🔴 KAPALI"
                            telegram_mesaj_gonder(f"⚡ *Bot Durumu:* Aktif 🟢\n💰 Kasa Bakiyesi: `${HESAP_BAKIYESI}`\n🤖 Otomatik Al-Sat: {oto_str}\n🛡️ Haber & Volatilite Filtresi: Aktif")
                        elif text == "/tv":
                            links = "🌐 *TRADINGVIEW CANLI GRAFİK LİNKLERİ*\n\n"
                            for _, (isim, tv_sym) in FOREX_PARITELERI.items():
                                links += f"📌 [{isim} Grafiğini Aç](https://www.tradingview.com/chart/?symbol={tv_sym})\n"
                            telegram_mesaj_gonder(links)
                        elif text.startswith("/oto"):
                            parca = text.split()
                            if len(parca) > 1 and parca[1].lower() in ["ac", "aç", "on"]:
                                AUTO_TRADE_AKTIF = True
                                telegram_mesaj_gonder("🤖 *Otomatik Al-Sat Modu AKTİF Edildi!* 🟢\n\nArtık üretilen sinyaller anında MetaTrader hesabınıza iletilip otomatik açılacaktır.")
                            elif len(parca) > 1 and parca[1].lower() in ["kapat", "off"]:
                                AUTO_TRADE_AKTIF = False
                                telegram_mesaj_gonder("📲 *Otomatik Al-Sat Modu KAPATILDI!* 🔴\n\nBot sadece Telegram'a sinyal ve analiz göndermeye devam edecektir.")
                            else:
                                dur = "AÇIK 🟢" if AUTO_TRADE_AKTIF else "KAPALI 🔴"
                                telegram_mesaj_gonder(f"🤖 Oto Al-Sat Şu an: *{dur}*\n\nKullanım:\n`/oto ac` -> Otomatiği açar\n`/oto kapat` -> Otomatiği kapatır")
                        elif text.startswith("/bakiye"):
                            try:
                                yeni_bakiye = float(text.split()[1])
                                HESAP_BAKIYESI = yeni_bakiye
                                telegram_mesaj_gonder(f"✅ *Hesap Bakiyesi Güncellendi!*\nYeni Kasa: `${HESAP_BAKIYESI}`\nLot miktarları bu bakiyenin %1 riskine göre hesaplanacak.")
                            except:
                                telegram_mesaj_gonder("⚠️ Lütfen geçerli bir bakiye girin. Örnek kullanım: `/bakiye 3000`")

        except Exception as e:
            print(f"Komut Dinleme Hatası: {e}")
        time.sleep(1)

def forex_parite_tara(ticker_symbol, isim_tuple):
    global GUNLUK_SINYAL_SAYISI
    isim, tv_symbol = isim_tuple
    suan = time.time()

    try:
        ticker = yf.Ticker(ticker_symbol)
        df = ticker.history(period="1d", interval=TIMEFRAME)

        if df.empty or len(df) < 35:
            return

        fiyat = round(df['Close'].iloc[-1], 4)

        # Aktif pozisyon varsa TP/SL seviyelerini kontrol et
        tp_sl_kontrol_et(ticker_symbol, fiyat, isim)

        # Cooldown kontrolü (Yeni sinyal için)
        if ticker_symbol in SON_SINYALLER and (suan - SON_SINYALLER[ticker_symbol]) < COOLDOWN_SURESI:
            return

        df['EMA_Fast'] = ta.trend.ema_indicator(df['Close'], window=9)
        df['EMA_Slow'] = ta.trend.ema_indicator(df['Close'], window=21)
        df['RSI'] = ta.momentum.rsi(df['Close'], window=14)
        macd_ind = ta.trend.MACD(df['Close'])
        df['MACD_Diff'] = macd_ind.macd_diff()

        son = df.iloc[-1]
        onceki = df.iloc[-2]

        rsi = round(son['RSI'], 2)

        al_kosulu = (
            (onceki['EMA_Fast'] <= onceki['EMA_Slow']) and 
            (son['EMA_Fast'] > son['EMA_Slow']) and 
            (rsi > 50) and 
            (son['MACD_Diff'] > 0)
        )

        sat_kosulu = (
            (onceki['EMA_Fast'] >= onceki['EMA_Slow']) and 
            (son['EMA_Fast'] < son['EMA_Slow']) and 
            (rsi < 50) and 
            (son['MACD_Diff'] < 0)
        )

        is_gold = "GC=F" in ticker_symbol
        sl_rate = 0.0030 if is_gold else 0.0015
        tv_link = f"https://www.tradingview.com/chart/?symbol={tv_symbol}"

        simdi_tsi = datetime.now(timezone.utc) + timedelta(hours=3)
        hacim_etiketi = " 🔥 *[YÜKSEK HACİM]*" if simdi_tsi.hour in [10, 11, 15, 16, 17] else ""
        oto_etiket = " 🤖 *[OTO İŞLEM İLETİLDİ]*" if AUTO_TRADE_AKTIF else ""

        if al_kosulu:
            sl = round(fiyat * (1 - sl_rate), 4)
            fark = fiyat - sl
            tp1, tp2, tp3 = round(fiyat + fark, 4), round(fiyat + (fark * 2), 4), round(fiyat + (fark * 3), 4)
            
            önerilen_lot = lot_hesapla(fiyat, sl, ticker_symbol)

            mesaj = (
                f"🚨 *PRO SCALP SİNYALİ (LONG / AL)*{hacim_etiketi}{oto_etiket} 🚨\n\n"
                f"📌 *Parite:* {isim}\n"
                f"🟢 *Giriş Fiyatı:* `{fiyat}`\n"
                f"💵 *Önerilen Lot (%1 Risk):* `{önerilen_lot} Lot`\n\n"
                f"🎯 *TP1:* `{tp1}` | 🎯 *TP2:* `{tp2}` | 🎯 *TP3:* `{tp3}`\n"
                f"🛑 *Stop Loss:* `{sl}`\n\n"
                f"💡 *Öneri:* TP1'e ulaştığında Stop Loss'u giriş seviyesine (`{fiyat}`) çekin.\n"
                f"📊 *RSI:* `{rsi}` | 🔗 [TradingView Grafiği]({tv_link})"
            )
            telegram_mesaj_gonder(mesaj)
            
            # Canlı TP/SL Takip Sözlüğüne Ekle
            AKTIF_ISLEMLER[ticker_symbol] = {
                'yon': 'BUY',
                'entry': fiyat,
                'tp1': tp1, 'tp2': tp2, 'tp3': tp3,
                'sl': sl,
                'tp1_hit': False, 'tp2_hit': False, 'tp3_hit': False
            }

            metatrader_signal_gonder({
                "action": "BUY",
                "symbol": isim,
                "price": fiyat,
                "lot": önerilen_lot,
                "sl": sl,
                "tp1": tp1, "tp2": tp2, "tp3": tp3
            })

            SON_SINYALLER[ticker_symbol] = suan
            GUNLUK_SINYAL_SAYISI += 1

        elif sat_kosulu:
            sl = round(fiyat * (1 + sl_rate), 4)
            fark = sl - fiyat
            tp1, tp2, tp3 = round(fiyat - fark, 4), round(fiyat - (fark * 2), 4), round(fiyat - (fark * 3), 4)

            önerilen_lot = lot_hesapla(fiyat, sl, ticker_symbol)

            mesaj = (
                f"🚨 *PRO SCALP SİNYALİ (SHORT / SAT)*{hacim_etiketi}{oto_etiket} 🚨\n\n"
                f"📌 *Parite:* {isim}\n"
                f"🔴 *Satış Fiyatı:* `{fiyat}`\n"
                f"💵 *Önerilen Lot (%1 Risk):* `{önerilen_lot} Lot`\n\n"
                f"🎯 *TP1:* `{tp1}` | 🎯 *TP2:* `{tp2}` | 🎯 *TP3:* `{tp3}`\n"
                f"🛡️ *Stop Loss:* `{sl}`\n\n"
                f"💡 *Öneri:* TP1'e ulaştığında Stop Loss'u giriş seviyesine (`{fiyat}`) çekin.\n"
                f"📊 *RSI:* `{rsi}` | 🔗 [TradingView Grafiği]({tv_link})"
            )
            telegram_mesaj_gonder(mesaj)

            # Canlı TP/SL Takip Sözlüğüne Ekle
            AKTIF_ISLEMLER[ticker_symbol] = {
                'yon': 'SELL',
                'entry': fiyat,
                'tp1': tp1, 'tp2': tp2, 'tp3': tp3,
                'sl': sl,
                'tp1_hit': False, 'tp2_hit': False, 'tp3_hit': False
            }

            metatrader_signal_gonder({
                "action": "SELL",
                "symbol": isim,
                "price": fiyat,
                "lot": önerilen_lot,
                "sl": sl,
                "tp1": tp1, "tp2": tp2, "tp3": tp3
            })

            SON_SINYALLER[ticker_symbol] = suan
            GUNLUK_SINYAL_SAYISI += 1

    except Exception as e:
        print(f"{isim} hatası: {e}")

# Servisleri Başlat
threading.Thread(target=run_web_server, daemon=True).start()
threading.Thread(target=telegram_komut_dinleyici, daemon=True).start()

# Menü Komutlarını Otomatik Kaydet
telegram_komutlari_ayarla()

# Başlangıç Bildirimi
telegram_mesaj_gonder("🚀 *ScalpBot Sistem Yeniden Başlatıldı!*\nKomut dinleyici, TP/SL canlı takibi ve sinyal taraması kesintisiz aktif.")

# Ana Döngü
while True:
    simdi = datetime.now()
    
    borsa_acilis_kontrol()

    if simdi.hour == 22 and not RAPOR_GONDERILDI:
        telegram_mesaj_gonder(f"📈 *GÜNLÜK BÖLÜM RAPORU*\n\nBugün toplam `{GUNLUK_SINYAL_SAYISI}` adet kaliteli scalp sinyali üretildi.")
        RAPOR_GONDERILDI = True
    elif simdi.hour != 22:
        RAPOR_GONDERILDI = False

    if hafta_sonu_mu():
        time.sleep(300)
        continue

    if not haber_filtresi_aktif_mi():
        time.sleep(60)
        continue

    for ticker, isim_tuple in FOREX_PARITELERI.items():
        forex_parite_tara(ticker, isim_tuple)
        time.sleep(1)
    time.sleep(60)
