import os
import json
import ccxt
import pandas as pd
from flask import Flask, render_template_string, jsonify
from apscheduler.schedulers.background import BackgroundScheduler
from datetime import datetime, timedelta
from groq import Groq

app = Flask('')
start_time = datetime.now()
STATS_FILE = 'balance_history.json'

# --- KONFIGURACJA ---
INITIAL_CAPITAL = 1000.0       
TRADE_AMOUNT_USDC = 120.0      
RSI_BUY_THRESHOLD = 50         
RSI_SELL_THRESHOLD = 58        

mexc = ccxt.mexc({
    'apiKey': os.getenv('MEXC_API_KEY'),
    'secret': os.getenv('MEXC_SECRET_KEY'),
    'options': {'defaultType': 'spot'},
    'enableRateLimit': True
})

groq_client = Groq(api_key=os.getenv('GROQ_KEY'))

display_state = {
    "usdc": 0.0, "total": 1000.0, "profit": 0.0,
    "buy_count": 0, "sell_count": 0,
    "last_action": "Synchronizacja...",
    "assets": {"BTC": {"amount":0, "rsi":50}, "ETH": {"amount":0, "rsi":50}}
}

def calculate_rsi(symbol):
    try:
        pair = f"{symbol}/USDC"
        bars = mexc.fetch_ohlcv(pair, timeframe='1m', limit=50)
        df = pd.DataFrame(bars, columns=['ts', 'o', 'h', 'l', 'c', 'v'])
        delta = df['c'].diff()
        gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
        rsi = 100 - (100 / (1 + (gain / loss)))
        return round(rsi.iloc[-1], 1)
    except: return 50.0

def ask_ai_decision(symbol, price, rsi):
    try:
        prompt = f"Analyze {symbol}: Price {price}, RSI {rsi}. Is it a good buy opportunity? Answer ONLY 'BUY' or 'WAIT'."
        completion = groq_client.chat.completions.create(
            model="llama3-8b-8192",
            messages=[{"role": "user", "content": prompt}],
            max_tokens=10
        )
        res = completion.choices[0].message.content.strip().upper()
        return "BUY" in res
    except: return False

def run_loop():
    global display_state
    try:
        balance = mexc.fetch_balance()
        usdc_free = float(balance.get('USDC', {}).get('free', 0.0))
        
        # LICZNIK STARTUJE OD WOLNYCH DOLARÓW
        current_total = usdc_free 
        assets_update = {}
        ai_reports = []

        for symbol in ["BTC", "ETH"]:
            pair = f"{symbol}/USDC"
            ticker = mexc.fetch_ticker(pair)
            price = float(ticker['last'])
            
            # POPRAWKA: Pobieramy 'total' (wolne + zablokowane w zleceniach)
            amt = float(balance.get(symbol, {}).get('total', 0.0))
            
            # DODAJEMY WARTOŚĆ MONETY DO SALDA CAŁKOWITEGO
            current_total += (amt * price)
            
            rsi_val = calculate_rsi(symbol)
            
            # HANDEL LIMIT (Naprawa błędu 30041)
            if amt * price < 10.0: 
                if rsi_val < 35:
                    qty = round(TRADE_AMOUNT_USDC / price, 6)
                    if usdc_free >= TRADE_AMOUNT_USDC:
                        mexc.create_order(pair, 'limit', 'buy', qty, price)
                        display_state["buy_count"] += 1
                        ai_reports.append(f"🛡️ {symbol}: KUPNO (RSI {rsi_val})")
            else: 
                if rsi_val > RSI_SELL_THRESHOLD:
                    mexc.create_order(pair, 'limit', 'sell', amt, price)
                    display_state["sell_count"] += 1
                    ai_reports.append(f"💰 {symbol}: SPRZEDAŻ (RSI {rsi_val})")

            assets_update[symbol] = {"amount": round(amt, 6), "rsi": rsi_val}

        # FINALNA AKTUALIZACJA INTERFEJSU
        display_state.update({
            "usdc": round(usdc_free, 2),
            "total": round(current_total, 2),
            "profit": round(current_total - INITIAL_CAPITAL, 2),
            "last_action": " | ".join(ai_reports) if ai_reports else "Rynek stabilny",
            "assets": assets_update
        })
        
        # ZAPIS DO WYKRESU
        history = []
        if os.path.exists(STATS_FILE):
            with open(STATS_FILE, 'r') as f:
                try: history = json.load(f)
                except: history = []
        history.append({"t": datetime.now().isoformat(), "v": round(current_total, 2)})
        with open(STATS_FILE, 'w') as f: json.dump(history[-20000:], f)

    except Exception as e: 
        display_state["last_action"] = f"Błąd: {str(e)}"

scheduler = BackgroundScheduler()
scheduler.add_job(run_loop, 'interval', minutes=1)
scheduler.start()

@app.route('/api/data/<range_type>')
def get_data(range_type):
    if not os.path.exists(STATS_FILE): return jsonify({"state": display_state, "history": []})
    with open(STATS_FILE, 'r') as f:
        try: history = json.load(f)
        except: history = []
    if not history: return jsonify({"state": display_state, "history": []})
    now = datetime.now()
    points = []
    if range_type == 'day':
        for i in range(23, -1, -1):
            target = now - timedelta(hours=i)
            match = min(history, key=lambda x: abs((datetime.fromisoformat(x['t']) - target).total_seconds()))
            points.append({"t": target.strftime("%H:00"), "v": match['v']})
    elif range_type == 'week':
        for i in range(13, -1, -1):
            target = now - timedelta(hours=i*12)
            match = min(history, key=lambda x: abs((datetime.fromisoformat(x['t']) - target).total_seconds()))
            points.append({"t": target.strftime("%d/%m %Hh"), "v": match['v']})
    elif range_type == 'month':
        for i in range(29, -1, -1):
            target = (now - timedelta(days=i)).replace(hour=0, minute=0, second=0)
            match = min(history, key=lambda x: abs((datetime.fromisoformat(x['t']) - target).total_seconds()))
            points.append({"t": target.strftime("%d/%m"), "v": match['v']})
    return jsonify({"state": display_state, "history": points})

@app.route('/')
def home():
    uptime = f"{(datetime.now() - start_time).seconds // 3600}h {((datetime.now() - start_time).seconds // 60) % 60}m"
    return render_template_string("""
    <!DOCTYPE html><html><head><title>BrainUp v10.2 Platinum</title>
    <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <style>
        body { background: #0b0e11; color: white; font-family: sans-serif; padding: 15px; margin: 0; }
        .grid { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; max-width: 600px; margin: auto; }
        .card { background: #1e2329; padding: 15px; border-radius: 12px; border: 1px solid #2b3139; text-align: center; }
        .label { color: #848e9c; font-size: 0.75em; text-transform: uppercase; margin-bottom: 5px; }
        .value { font-size: 1.2em; font-weight: bold; }
        .sub-label { font-size: 0.72em; color: #f3ba2f; margin-top: 8px; border-top: 1px solid #2b3139; padding-top: 5px; }
        .ai-box { max-width: 600px; margin: 15px auto; padding: 12px; background: rgba(243, 186, 47, 0.1); border: 1px solid #f3ba2f; border-radius: 8px; font-size: 0.82em; text-align: center; color: #f3ba2f; line-height: 1.4; }
        .chart-container { max-width: 600px; margin: auto; background: #1e2329; border-radius: 12px; padding: 10px; border: 1px solid #2b3139; }
        .btn-group { display: flex; justify-content: center; gap: 5px; margin-bottom: 10px; }
        button { background: #2b3139; color: #848e9c; border: none; padding: 6px 12px; border-radius: 4px; cursor: pointer; }
        button.active { background: #f3ba2f; color: black; font-weight: bold; }
        .asset-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; max-width: 600px; margin: 15px auto; }
    </style></head>
    <body>
        <h3 style="color: #f3ba2f; text-align:center;">🧠 AI TRADER v10.2 PLATINUM</h3>
        <div class="grid">
            <div class="card"><div class="label">USDC Wolne</div><div class="value" id="usdc">--</div></div>
            <div class="card"><div class="label">Uptime</div><div class="value">"""+uptime+"""</div></div>
            <div class="card"><div class="label">Zysk / Strata</div><div id="profit" class="value">--</div><div class="sub-label">Sprzedaże: <b id="s_count" style="color:white;">0</b></div></div>
            <div class="card"><div class="label">Wartość Portfela</div><div id="total" class="value">--</div><div class="sub-label">Kupna: <b id="b_count" style="color:white;">0</b></div></div>
        </div>
        <div class="ai-box"><b>Llama 3 Analytics:</b><br><span id="ai_action">Skanowanie...</span></div>
        <div class="chart-container">
            <div class="btn-group">
                <button id="b-day" onclick="changeRange('day')" class="active">Dzień</button>
                <button id="b-week" onclick="changeRange('week')">Tydzień</button>
                <button id="b-month" onclick="changeRange('month')">Miesiąc</button>
            </div>
            <canvas id="myChart"></canvas>
        </div>
        <div class="asset-grid">
            <div class="card"><div style="color:#f3ba2f; font-weight:bold;">BTC</div><div id="btc_amt" class="value">--</div></div>
            <div class="card"><div style="color:#f3ba2f; font-weight:bold;">ETH</div><div id="eth_amt" class="value">--</div></div>
        </div>
        <script>
            let chart; let currentRange = 'day';
            function changeRange(r) { currentRange = r; update(); }
            async function update() {
                document.querySelectorAll('button').forEach(b => b.classList.remove('active'));
                document.getElementById('b-'+currentRange).classList.add('active');
                const res = await fetch('/api/data/'+currentRange); const d = await res.json();
                document.getElementById('usdc').innerText = d.state.usdc + ' $';
                document.getElementById('total').innerText = d.state.total + ' $';
                document.getElementById('b_count').innerText = d.state.buy_count;
                document.getElementById('s_count').innerText = d.state.sell_count;
                document.getElementById('ai_action').innerText = d.state.last_action;
                document.getElementById('btc_amt').innerText = d.state.assets.BTC.amount;
                document.getElementById('eth_amt').innerText = d.state.assets.ETH.amount;
                const pEl = document.getElementById('profit');
                pEl.innerText = (d.state.profit>=0?'+':'') + d.state.profit + ' $';
                pEl.style.color = d.state.profit>=0?'#0ecb81':'#f6465d';
                if(!chart) {
                    chart = new Chart(document.getElementById('myChart'), {
                        type:'line', data:{labels:d.history.map(h=>h.t), datasets:[{data:d.history.map(h=>h.v), borderColor:'#f3ba2f', tension:0.4, fill:true, backgroundColor:'rgba(243,186,47,0.1)'}]},
                        options:{animation:false, plugins:{legend:{display:false}}, scales:{y:{grid:{color:'#2b3139'}}, x:{grid:{display:false}}}}
                    });
                } else { chart.data.labels = d.history.map(h=>h.t); chart.data.datasets[0].data = d.history.map(h=>h.v); chart.update(); }
            }
            setInterval(update, 30000); update();
        </script>
    </body></html>
    """)

if __name__ == "__main__":
    run_loop(); app.run(host='0.0.0.0', port=10000)
