import os
import sqlite3
import datetime as dt
from zoneinfo import ZoneInfo
from flask import Flask, jsonify, render_template_string, request, redirect, url_for

# v4.6 altyapınla aynı DB ve Config
DB_FILE = os.getenv("DB_FILE", "scalpbot.db")
TIMEZONE = "Europe/Istanbul"
TZ = ZoneInfo(TIMEZONE)
INITIAL_BALANCE = 3000.0

app = Flask(__name__)

def now_istanbul():
    return dt.datetime.now(TZ)

def db_connect():
    conn = sqlite3.connect(DB_FILE, timeout=30, check_same_thread=False)
    conn.execute("PRAGMA journal_mode=WAL")
    return conn

def get_state(key, default=0.0):
    conn = db_connect()
    try:
        row = conn.execute("SELECT value FROM state WHERE key = ?", (key,)).fetchone()
        return float(row[0]) if (row and row[0] is not None) else default
    finally:
        conn.close()

def get_open_position_stats():
    conn = db_connect()
    try:
        row = conn.execute("SELECT COUNT(*), COALESCE(SUM(risk), 0) FROM positions WHERE status = 'OPEN'").fetchone()
        return (int(row[0] or 0), float(row or 0.0)) if row else (0, 0.0)
    finally:
        conn.close()

def get_db_stats():
    conn = db_connect()
    try:
        closed = conn.execute("SELECT symbol, side, entry, exit, pnl, closed_at, reason FROM closed_trades ORDER BY id DESC LIMIT 50").fetchall()
        open_pos = conn.execute("SELECT id, symbol, side, entry, current_price, sl, tp, lot, risk FROM positions WHERE status = 'OPEN' ORDER BY id ASC").fetchall()
        return closed, open_pos
    finally:
        conn.close()

PRO_HTML = r"""
<!doctype html>
<html lang="tr">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>SCALPBOT PRO — AI Powered Trading Terminal</title>
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
    .btn { background:var(--blue); color:#fff; border:0; padding:6px 12px; border-radius:6px; font-weight:600; cursor:pointer; font-size:11px }
    .btn:hover { opacity:.9 }
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
      <div style="color:var(--muted);">API DURUMU</div>
      <div style="color:var(--green); font-weight:700; margin:4px 0;">● Bağlı (SQLite/v4.6)</div>
      <div style="font-size:10px; color:var(--muted);">Render + SQLite Sync</div>
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
      <div class="card"><div class="card-title">Günlük P&L</div><div class="card-value {{'green' if today_pnl >= 0 else 'red'}}">{{ "+$%.2f"|format(today_pnl) if today_pnl>=0 else "-$%.2f"|format(today_pnl|abs) }}</div><div class="card-title">Realize P&L</div></div>
      <div class="card"><div class="card-title">Açık Pozisyon</div><div class="card-value">{{open_count}} / 3</div><div class="card-title">Risk: ${{ "%.2f"|format(open_risk) }}</div></div>
      <div class="card"><div class="card-title">Mod / Durum</div><div class="card-value" style="font-size:18px; color:var(--blue);">DEMO / MANUAL</div><div class="card-title">Emirler Manuel</div></div>
      <div class="card"><div class="card-title">Sistem Loop</div><div class="card-value" style="font-size:18px; color:var(--green);">ONLINE</div><div class="card-title">Uptime Sağlam</div></div>
    </div>

    <!-- MAIN DASHBOARD AREA -->
    <div class="dashboard-grid">
      <!-- Grafik / İnceleme Alanı -->
      <div class="card">
        <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:10px;">
          <b style="font-size:14px;">XAUUSD / Fiyat & Görsel Takip Katmanı</b>
          <span class="card-title">TradingView / M5-M15 Sync</span>
        </div>
        <div style="height:280px; background:#080c12; border:1px solid var(--line); border-radius:8px; display:flex; align-items:center; justify-content:center; color:var(--muted); text-align:center; padding:20px;">
          <div>
            <div style="font-size:16px; font-weight:700; color:var(--text); margin-bottom:6px;">TradingView Görsel Katmanı Aktif</div>
            Canlı grafik izleme ve Long/Short kutu eşleşmeleri için TradingView tablet/ekranını bu metriklerle hizalamaya devam ediyorsun koç.
          </div>
        </div>
      </div>

      <!-- Açık Pozisyonlar Widget -->
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
                <td>{{p}}</td>
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
                <td style="font-size:10px; color:var(--muted);">{{t}}</td>
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

@app.route("/")
def dashboard():
    balance = get_state("balance", INITIAL_BALANCE)
    open_count, open_risk = get_open_position_stats()
    closed_trades, open_pos = get_db_stats()
    
    # Basit bugünki P&L hesaplama (veya get_today_pnl mantığı)
    today_pnl = sum([float(t[4] or 0) for t in closed_trades]) # Örnek kümülatif/güncel akış
    
    return render_template_string(
        PRO_HTML,
        balance=balance,
        today_pnl=today_pnl,
        open_count=open_count,
        open_risk=open_risk,
        open_pos=open_pos,
        closed_trades=closed_trades
    )

@app.route("/api/status")
def api_status():
    balance = get_state("balance", INITIAL_BALANCE)
    open_count, open_risk = get_open_position_stats()
    return jsonify({
        "balance": balance,
        "open_count": open_count,
        "open_risk": open_risk,
        "status": "online"
    })

if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000, debug=True)
