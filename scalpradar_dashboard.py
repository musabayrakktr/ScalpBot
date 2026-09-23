from flask import Flask, jsonify, render_template_string
from datetime import datetime

app = Flask(__name__)

# ------------------------------------------------------------
# SCALPRADAR PRO — DASHBOARD STARTER
# Demo-only sample data. Replace these values with your bot data
# when connecting the existing signal engine.
# ------------------------------------------------------------

MARKETS = [
    {"symbol": "EURUSD", "signal": "BUY",  "confidence": 87, "price": "1.17420", "change": "+0.32%"},
    {"symbol": "GBPUSD", "signal": "SELL", "confidence": 81, "price": "1.35180", "change": "-0.27%"},
    {"symbol": "XAUUSD", "signal": "BUY",  "confidence": 93, "price": "3,xxx.xx", "change": "+0.74%"},
    {"symbol": "USDJPY", "signal": "WAIT", "confidence": 64, "price": "148.620", "change": "+0.08%"},
    {"symbol": "AUDUSD", "signal": "BUY",  "confidence": 79, "price": "0.65210", "change": "+0.19%"},
    {"symbol": "BTCUSD", "signal": "WAIT", "confidence": 61, "price": "78,506.00", "change": "-0.41%"},
]

RECENT_SIGNALS = [
    {"time": "23:41:08", "symbol": "XAUUSD", "signal": "BUY", "confidence": 93, "status": "DEMO"},
    {"time": "23:17:42", "symbol": "EURUSD", "signal": "SELL", "confidence": 87, "status": "DEMO"},
    {"time": "22:54:19", "symbol": "GBPUSD", "signal": "SELL", "confidence": 81, "status": "DEMO"},
    {"time": "22:31:03", "symbol": "AUDUSD", "signal": "BUY", "confidence": 79, "status": "DEMO"},
]

DASHBOARD_DATA = {
    "bot_status": "ONLINE",
    "market_status": "LIVE",
    "sentiment": 72,
    "sentiment_label": "BULLISH",
    "balance": 3428.72,
    "pnl": 428.72,
    "pnl_percent": 14.29,
    "win_rate": 68.4,
    "total_trades": 127,
    "open_trades": 2,
    "last_update": datetime.now().strftime("%H:%M:%S"),
    "markets": MARKETS,
    "recent_signals": RECENT_SIGNALS,
}

HTML = r"""
<!doctype html>
<html lang="tr">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>SCALPRADAR PRO | Trading Terminal</title>
  <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
  <style>
    :root {
      --bg:#090d14; --panel:#101722; --panel2:#0d141e; --line:#202b3a;
      --text:#edf2f8; --muted:#8492a6; --green:#25d695; --red:#ff647c;
      --yellow:#f4c45e; --blue:#6da8ff; --purple:#a58bfa;
    }
    * { box-sizing:border-box }
    body { margin:0; background:var(--bg); color:var(--text); font:14px/1.45 Inter,system-ui,-apple-system,Segoe UI,sans-serif }
    button { font:inherit; cursor:pointer }
    .app { min-height:100vh; display:grid; grid-template-columns:230px minmax(0,1fr) }
    aside { background:#0b111a; border-right:1px solid var(--line); padding:25px 15px; display:flex; flex-direction:column; gap:30px }
    .brand { padding:0 12px; font-weight:850; letter-spacing:1.3px; font-size:17px }
    .brand span { color:var(--blue) }
    .brand small { display:block; color:var(--muted); font-size:9px; letter-spacing:3px; margin-top:5px }
    .nav-label { color:#58677b; font-size:10px; font-weight:800; letter-spacing:1.6px; padding:0 12px; margin-bottom:8px }
    nav { display:grid; gap:5px }
    .nav-item { color:#9ba9bc; text-decoration:none; padding:11px 12px; border-radius:9px; display:flex; gap:12px; align-items:center }
    .nav-item.active,.nav-item:hover { background:#172437; color:#fff }
    .nav-item.active { box-shadow:inset 3px 0 var(--blue) }
    .side-bottom { margin-top:auto; border:1px solid var(--line); background:var(--panel2); border-radius:12px; padding:14px }
    .tiny { color:var(--muted); font-size:11px }
    main { min-width:0; padding:24px clamp(15px,2.4vw,36px) 36px }
    .topbar { display:flex; align-items:center; justify-content:space-between; gap:15px; margin-bottom:25px }
    h1 { font-size:22px; margin:0; letter-spacing:-.5px }
    .subtitle { color:var(--muted); font-size:12px; margin-top:4px }
    .top-actions { display:flex; align-items:center; gap:10px }
    .pill { border:1px solid var(--line); border-radius:30px; padding:8px 12px; color:#c2ccda; background:var(--panel2); font-size:11px }
    .dot { display:inline-block; width:7px; height:7px; border-radius:50%; background:var(--green); margin-right:7px; box-shadow:0 0 10px #25d69555 }
    .section-head { display:flex; justify-content:space-between; align-items:center; gap:10px; margin:24px 0 12px }
    h2 { font-size:13px; letter-spacing:.7px; margin:0; text-transform:uppercase }
    .tag { color:var(--blue); font-size:10px; letter-spacing:1px; font-weight:800 }
    .grid { display:grid; gap:14px }
    .overview { grid-template-columns:1.4fr 1fr 1fr 1fr }
    .card { background:linear-gradient(145deg,var(--panel),#0e1520); border:1px solid var(--line); border-radius:14px; padding:17px; min-width:0 }
    .card-label { color:var(--muted); font-size:11px; font-weight:700; letter-spacing:.7px; text-transform:uppercase }
    .big { font-size:27px; font-weight:800; letter-spacing:-.8px; margin:8px 0 4px }
    .green { color:var(--green) } .red { color:var(--red) } .yellow { color:var(--yellow) } .muted { color:var(--muted) }
    .sentiment-row { display:flex; justify-content:space-between; align-items:center; gap:10px }
    .meter { height:6px; background:#263142; border-radius:9px; overflow:hidden; margin:13px 0 10px }
    .meter span { display:block; height:100%; width:72%; background:linear-gradient(90deg,#4d9cff,#25d695); border-radius:9px }
    .micro-grid { display:grid; grid-template-columns:repeat(3,1fr); gap:8px; margin-top:12px }
    .micro { background:#0b121c; border:1px solid #1b2736; border-radius:8px; padding:8px }
    .micro b { display:block; font-size:11px; margin-top:4px }
    .markets { grid-template-columns:repeat(6,minmax(0,1fr)) }
    .market-card { padding:14px; transition:.15s ease }
    .market-card:hover { transform:translateY(-2px); border-color:#405777 }
    .market-top { display:flex; justify-content:space-between; align-items:center; gap:5px }
    .symbol { font-size:12px; font-weight:800; letter-spacing:.3px }
    .signal { font-size:9px; font-weight:900; letter-spacing:.8px; padding:4px 7px; border-radius:5px; background:#183b32; color:var(--green) }
    .signal.sell { color:var(--red); background:#3d202a }
    .signal.wait { color:var(--yellow); background:#3a3220 }
    .price { font-size:18px; font-weight:750; margin:13px 0 3px }
    .market-foot { display:flex; justify-content:space-between; gap:5px; color:var(--muted); font-size:10px }
    .confidence { height:4px; border-radius:5px; background:#263142; margin-top:12px; overflow:hidden }
    .confidence span { display:block; height:100%; background:var(--blue) }
    .main-grid { grid-template-columns:minmax(0,1.65fr) minmax(280px,1fr); align-items:stretch }
    .chart-wrap { height:270px; position:relative; margin-top:15px }
    .timeframes { display:flex; gap:5px }
    .timeframes button { color:var(--muted); border:1px solid transparent; background:transparent; border-radius:6px; padding:5px 8px; font-size:10px }
    .timeframes button.active,.timeframes button:hover { color:#fff; background:#1b2a3e; border-color:#2c405b }
    .signal-title { display:flex; justify-content:space-between; align-items:center; gap:8px }
    .trade-symbol { font-size:24px; font-weight:850; margin-top:12px }
    .confidence-number { font-size:31px; font-weight:850; color:var(--green) }
    .levels { display:grid; grid-template-columns:1fr 1fr; gap:8px; margin:15px 0 }
    .level { background:#0b121c; border:1px solid #1d2938; border-radius:8px; padding:10px }
    .level span { display:block; color:var(--muted); font-size:10px; margin-bottom:4px }
    .level b { font-size:13px }
    .reason { display:flex; gap:8px; color:#b8c4d3; font-size:11px; margin:8px 0 }
    .check { color:var(--green); font-weight:900 }
    .lower { grid-template-columns:1.1fr 1.9fr 1fr }
    .stat-line { display:flex; justify-content:space-between; padding:9px 0; border-bottom:1px solid #1c2735; font-size:12px }
    .stat-line:last-child { border:0 }
    .status-line { display:flex; justify-content:space-between; gap:10px; padding:9px 0; border-bottom:1px solid #1c2735; font-size:11px }
    .status-line:last-child { border:0 }
    table { width:100%; border-collapse:collapse; font-size:11px; white-space:nowrap }
    th { color:#73839a; text-align:left; font-size:9px; letter-spacing:.8px; padding:11px 8px; border-bottom:1px solid var(--line) }
    td { padding:12px 8px; border-bottom:1px solid #1b2634; color:#c4cedb }
    tr:last-child td { border-bottom:0 }
    .table-scroll { overflow:auto }
    .demo-note { color:#8c7b4d; background:#292416; border:1px solid #4a3d20; border-radius:8px; padding:9px 11px; font-size:10px; margin-top:14px }
    .footer { text-align:center; color:#536176; font-size:10px; margin-top:24px }
    @media(max-width:1200px) { .markets { grid-template-columns:repeat(3,minmax(0,1fr)) } .overview { grid-template-columns:repeat(2,minmax(0,1fr)) } .lower { grid-template-columns:1fr 1fr } .lower .history { grid-column:1/-1 } }
    @media(max-width:760px) { .app { grid-template-columns:1fr } aside { display:none } main { padding:17px 12px 25px } .topbar { align-items:flex-start } .top-actions .pill:not(:first-child) { display:none } .main-grid,.lower { grid-template-columns:1fr } .lower .history { grid-column:auto } .markets { grid-template-columns:repeat(2,minmax(0,1fr)); gap:8px } .overview { gap:8px } .card { padding:13px } .big { font-size:23px } .chart-wrap { height:230px } }
  </style>
</head>
<body>
<div class="app">
  <aside>
    <div class="brand">SCALP<span>RADAR</span> PRO<small>AI TRADING TERMINAL</small></div>
    <div>
      <div class="nav-label">WORKSPACE</div>
      <nav>
        <a class="nav-item active" href="#dashboard">▦ <span>Dashboard</span></a>
        <a class="nav-item" href="#signals">⌁ <span>Signals</span></a>
        <a class="nav-item" href="#markets">◷ <span>Markets</span></a>
        <a class="nav-item" href="#portfolio">▤ <span>Portfolio</span></a>
        <a class="nav-item" href="#history">↻ <span>History</span></a>
      </nav>
    </div>
    <div>
      <div class="nav-label">INTELLIGENCE</div>
      <nav>
        <a class="nav-item" href="#ai">✧ <span>AI Lab</span></a>
        <a class="nav-item" href="#settings">⚙ <span>Settings</span></a>
      </nav>
    </div>
    <div class="side-bottom">
      <div class="tiny">SYSTEM STATUS</div>
      <div style="font-weight:800;margin:7px 0"><span class="dot"></span>All systems operational</div>
      <div class="tiny">Dashboard prototype · v0.1</div>
    </div>
  </aside>

  <main id="dashboard">
    <header class="topbar">
      <div><h1>Trading Overview</h1><div class="subtitle">Piyasa, sinyaller ve sistem performansı tek ekranda.</div></div>
      <div class="top-actions">
        <div class="pill"><span class="dot"></span>MARKET LIVE</div>
        <div class="pill">DEMO ACCOUNT</div>
        <div class="pill" id="clock">--:--:--</div>
      </div>
    </header>

    <div class="section-head"><h2>AI Market Overview</h2><span class="tag">SCALPRADAR INTELLIGENCE</span></div>
    <section class="grid overview">
      <div class="card">
        <div class="sentiment-row"><div class="card-label">Market sentiment</div><span class="signal">BULLISH</span></div>
        <div class="big">72 <span class="muted" style="font-size:14px">/ 100</span></div>
        <div class="meter"><span></span></div>
        <div class="tiny">Örnek gösterge · gerçek AI skoru henüz bağlanmadı.</div>
      </div>
      <div class="card"><div class="card-label">Demo balance</div><div class="big">$3,428.72</div><div class="green">+$428.72 <span class="tiny">(+14.29%)</span></div></div>
      <div class="card"><div class="card-label">Win rate</div><div class="big">68.4<span style="font-size:16px">%</span></div><div class="tiny">127 örnek işlem · demo veri</div></div>
      <div class="card"><div class="card-label">Open trades</div><div class="big">02</div><div class="tiny">Demo gösterim · gerçek pozisyon değil</div></div>
    </section>

    <div class="section-head" id="markets"><h2>Markets Watchlist</h2><span class="tag">6 INSTRUMENTS</span></div>
    <section class="grid markets" id="marketCards">
      {% for m in markets %}
      <div class="card market-card">
        <div class="market-top"><span class="symbol">{{m.symbol}}</span><span class="signal {{'sell' if m.signal=='SELL' else 'wait' if m.signal=='WAIT' else ''}}">{{m.signal}}</span></div>
        <div class="price">{{m.price}}</div>
        <div class="market-foot"><span class="{{'green' if m.change.startswith('+') else 'red'}}">{{m.change}}</span><span>{{m.confidence}}% score</span></div>
        <div class="confidence"><span style="width:{{m.confidence}}%"></span></div>
      </div>
      {% endfor %}
    </section>

    <div class="section-head"><h2>Market Analysis</h2><span class="tag">CHART PREVIEW</span></div>
    <section class="grid main-grid">
      <div class="card">
        <div class="signal-title">
          <div><div class="card-label">Instrument · illustrative chart</div><div class="trade-symbol">XAUUSD <span class="green" style="font-size:12px">▲ +0.74%</span></div></div>
          <div class="timeframes"><button>1m</button><button class="active">5m</button><button>15m</button><button>1H</button><button>4H</button></div>
        </div>
        <div class="chart-wrap"><canvas id="priceChart"></canvas></div>
        <div class="tiny">Grafik şu an temsili veriler kullanır; canlı fiyat akışı bağlı değildir.</div>
      </div>

      <div class="card" id="signals">
        <div class="signal-title"><div class="card-label">Top signal · sample</div><span class="signal">BUY</span></div>
        <div class="trade-symbol">XAUUSD</div>
        <div style="display:flex;justify-content:space-between;align-items:end;margin-top:5px"><span class="tiny">SAMPLE CONFIDENCE</span><span class="confidence-number">93%</span></div>
        <div class="levels">
          <div class="level"><span>ENTRY</span><b>—</b></div>
          <div class="level"><span>STOP LOSS</span><b class="red">—</b></div>
          <div class="level"><span>TAKE PROFIT 1</span><b class="green">—</b></div>
          <div class="level"><span>TAKE PROFIT 2 / 3</span><b class="green">— / —</b></div>
        </div>
        <div class="card-label" id="ai">Signal reasoning · preview</div>
        <div class="reason"><span class="check">✓</span> EMA 9/21 trend check</div>
        <div class="reason"><span class="check">✓</span> RSI momentum check</div>
        <div class="reason"><span class="check">✓</span> MACD confirmation check</div>
        <div class="reason"><span class="check">✓</span> Market structure review</div>
        <div class="demo-note">Örnek sinyal kartı. Bu ekran emir göndermez ve yatırım tavsiyesi değildir.</div>
      </div>
    </section>

    <div class="section-head" id="portfolio"><h2>Performance & System</h2><span class="tag">DEMO MODE</span></div>
    <section class="grid lower">
      <div class="card">
        <div class="card-label">Performance summary</div>
        <div class="big">$3,428.72</div><div class="green" style="font-weight:750">+$428.72 · +14.29%</div>
        <div style="margin-top:12px">
          <div class="stat-line"><span class="muted">Win rate</span><b>68.4%</b></div>
          <div class="stat-line"><span class="muted">Total trades</span><b>127</b></div>
          <div class="stat-line"><span class="muted">Profit factor</span><b>1.84</b></div>
        </div>
        <div class="tiny" style="margin-top:8px">Tamamı örnek değerlerdir.</div>
      </div>

      <div class="card history" id="history">
        <div class="signal-title"><div class="card-label">Recent signals</div><span class="tag">LATEST ACTIVITY</span></div>
        <div class="table-scroll">
          <table>
            <thead><tr><th>TIME</th><th>SYMBOL</th><th>SIGNAL</th><th>SCORE</th><th>MODE</th></tr></thead>
            <tbody>
            {% for s in recent_signals %}
              <tr><td>{{s.time}}</td><td><b>{{s.symbol}}</b></td><td class="{{'green' if s.signal=='BUY' else 'red' if s.signal=='SELL' else 'yellow'}}">{{s.signal}}</td><td>{{s.confidence}}%</td><td>{{s.status}}</td></tr>
            {% endfor %}
            </tbody>
          </table>
        </div>
      </div>

      <div class="card" id="settings">
        <div class="signal-title"><div class="card-label">Bot status</div><span class="signal">ONLINE*</span></div>
        <div class="stat-line"><span class="muted">Signal engine</span><b class="green">● Demo</b></div>
        <div class="stat-line"><span class="muted">AI analyzer</span><b class="yellow">● Not connected</b></div>
        <div class="stat-line"><span class="muted">Telegram</span><b class="yellow">● Not connected</b></div>
        <div class="stat-line"><span class="muted">Market data</span><b class="yellow">● Sample data</b></div>
        <div class="stat-line"><span class="muted">Risk manager</span><b class="yellow">● Not connected</b></div>
        <div class="tiny" style="margin-top:10px">*Bu durum tasarım örneğidir; çalışan botun gerçek durumunu yansıtmaz.</div>
      </div>
    </section>
    <div class="footer">SCALPRADAR PRO · Dashboard Prototype v0.1 · Demo data only</div>
  </main>
</div>
<script>
  const ctx = document.getElementById('priceChart');
  const labels = Array.from({length:30}, (_,i) => `${String(10 + Math.floor(i/6)).padStart(2,'0')}:${String((i%6)*10).padStart(2,'0')}`);
  const prices = [3312,3317,3314,3320,3318,3325,3322,3329,3327,3324,3331,3335,3330,3338,3336,3342,3339,3345,3341,3348,3352,3347,3355,3351,3358,3354,3360,3357,3364,3368];
  new Chart(ctx, {
    type:'line',
    data:{labels,datasets:[{data:prices,borderColor:'#6da8ff',backgroundColor:'rgba(109,168,255,.08)',fill:true,tension:.28,pointRadius:0,borderWidth:2}]},
    options:{responsive:true,maintainAspectRatio:false,plugins:{legend:{display:false},tooltip:{mode:'index',intersect:false}},interaction:{mode:'index',intersect:false},
      scales:{x:{grid:{color:'rgba(120,140,165,.08)'},ticks:{color:'#718198',maxTicksLimit:7,font:{size:9}}},
      y:{grid:{color:'rgba(120,140,165,.08)'},ticks:{color:'#718198',font:{size:9}}}}}
  });
  function updateClock(){ document.getElementById('clock').textContent = new Date().toLocaleTimeString('tr-TR'); }
  updateClock(); setInterval(updateClock,1000);
</script>
</body>
</html>
"""

@app.route("/")
def dashboard():
    return render_template_string(HTML, markets=MARKETS, recent_signals=RECENT_SIGNALS)

@app.route("/api/dashboard")
def dashboard_api():
    """JSON endpoint for the frontend; replace sample payload with real bot state."""
    payload = dict(DASHBOARD_DATA)
    payload["last_update"] = datetime.now().strftime("%H:%M:%S")
    return jsonify(payload)

@app.route("/health")
def health():
    return jsonify({"status": "ok", "app": "SCALPRADAR PRO dashboard", "mode": "demo"})

if __name__ == "__main__":
    # Local development only. For deployment, use a production WSGI server.
    app.run(host="127.0.0.1", port=5000, debug=True)
