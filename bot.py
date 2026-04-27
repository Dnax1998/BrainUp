import os
import json
import ccxt
import pandas as pd
from groq import Groq
from flask import Flask, render_template_string, jsonify
from apscheduler.schedulers.background import BackgroundScheduler
from datetime import datetime, timedelta

app = Flask('')
start_time = datetime.now()
STATS_FILE = 'balance_history.json'
INITIAL_CAPITAL = 1000.0 

# --- KONFIGURACJA v8.5 PLATINUM ---
TRADE_AMOUNT_USDC = 100.0
STOP_LOSS_PCT = 0.05
TRAILING_ACTIVATE_PCT = 0.015

mexc = ccxt.mexc({
    'apiKey': os.getenv('MEXC_API_KEY'),
    'secret': os.getenv('MEXC_SECRET_KEY'),
    'options': {'defaultType': 'spot'},
    'enableRateLimit': True
})
client = Groq(api_key=os.getenv('GROQ_KEY'))

display_state = {
    "usdc": 0.0, "total": 1000.0, "profit": 0.0,
    "buy_count": 0, "sell_count": 0,
    "last_action": "v8.5 Platinum Online",
    "assets": {"BTC": {"amount":0, "rsi":50, "entry":0.0}, "ETH": {"amount":0, "rsi":50, "entry":0.0}}
}

def run_loop():
    global display_state
    try:
        balance = mexc.fetch_balance()
        usdc_free = float(balance.get('USDC', {}).get('free', 0.0))
        current_total_value = usdc_free
        assets_update = {}
        ai_thoughts = []

        for symbol in ["BTC", "ETH"]:
            pair = f"{symbol}/USDC"
            ticker = mexc.fetch_ticker(pair)
            price = float(ticker['last'])
            amt = float(balance.get(symbol, {}).get('free', 0.0))
            current_total_value += (amt * price)
            
            bars = mexc.fetch_ohlcv(pair, timeframe='1m', limit=30)
            df = pd.DataFrame(bars, columns=['ts','o','h','l','c','v'])
            delta = df['c'].diff()
            gain = (delta.where(delta > 0, 0)).rolling(14).mean().iloc[-1]
            loss = (-delta.where(delta < 0, 0)).rolling(14).mean().iloc[-1]
            rsi_val = round(100 - (100 / (1 + (gain/loss))), 1) if loss > 0 else 50
            
            entry = display_state["assets"].get(symbol, {}).get("entry", 0.0)
            
            # Sprzedaż: Profit, SL lub wysokie RSI
            if amt > 0.0001 and entry > 0:
                change = (price - entry) / entry
                if change <= -STOP_LOSS_PCT or rsi_val > 72 or (change > TRAILING_ACTIVATE_PCT and rsi_val < 62):
                    mexc.create_order(pair, 'limit', 'sell', amt, round(price * 0.999, 2))
                    display_state["sell_count"] += 1
                    entry = 0
                    ai_thoughts.append(f"Zysk/SL {symbol}")

            # Kupno DCA (pakiety 100$)
            if usdc_free >= TRADE_AMOUNT_USDC and rsi_val < 42:
                buy_qty = round(TRADE_AMOUNT_USDC / price, 6)
                mexc.create_order(pair, 'limit', 'buy', buy_qty, round(price * 1.0005, 2))
                entry = ((amt * entry) + (buy_qty * price)) / (amt + buy_qty) if amt > 0 else price
                display_state["buy_count"] += 1
                ai_thoughts.append(f"Kupno {symbol}")

            assets_update[symbol] = {"amount": round(amt, 6), "rsi": rsi_val, "entry": round(entry, 2)}

        profit = current_total_value - INITIAL_CAPITAL
        display_state.update({"usdc": round(usdc_free, 2), "total": round(current_total_value, 2), "profit": round(profit, 2), "assets": assets_update})
        if ai_thoughts: display_state["last_action"] = " | ".join(ai_thoughts)

        # Historia dla wykresów
        h_item = {"t": datetime.now().isoformat(), "v": round(current_total_value, 2)}
        history = []
        if os.path.exists(STATS_FILE):
            with open(STATS_FILE, 'r') as f: history = json.load(f)
        history.append(h_item)
        with open(STATS_FILE, 'w') as f: json.dump(history[-20000:], f)

    except Exception as e: display_state["last_action"] = f"Błąd: {str(e)}"

scheduler = BackgroundScheduler()
scheduler.add_job(run_loop, 'interval', minutes=2)
scheduler.start()

@app.route('/api/data/<range_type>')
def get_data(range_type):
    history = []
    if os.path.exists(STATS_FILE):
        with open(STATS_FILE, 'r') as f: history = json.load(f)
    deltas = {'day': 1, 'week': 7, 'month': 30}
    limit = datetime.now() - timedelta(days=deltas.get(range_type, 1))
    filtered = [h for h in history if datetime.fromisoformat(h['t']) > limit]
    step = max(1, len(filtered) // 60)
    return jsonify({"state": display_state, "history": filtered[::step]})

@app.route('/')
def home():
    return render_template_string("""
    <!DOCTYPE html><html><head><title>AI v8.5</title>
    <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <style>
        body { background: #0b0e11; color: white; font-family: sans-serif; padding: 10px; margin: 0; }
        .grid { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; max-width: 600px; margin: auto; }
        .card { background: #1e2329; padding: 12px; border-radius: 10px; border: 1px solid #2b3139; text-align: center; }
        .label { color: #848e9c; font-size: 0.7em; text-transform: uppercase; }
        .value { font-size: 1.1em; font-weight: bold; margin-top: 4px; }
        .btn-group { display: flex; justify-content: center; gap: 10px; margin: 15px 0; }
        button { background: #2b3139; color: #848e9c; border: none; padding: 8px 16px; border-radius: 5px; cursor: pointer; }
        button.active { background: #f3ba2f; color: black; font-weight: bold; }
        .chart-wrap { background: #1e2329; border-radius: 10px; padding: 10px; max-width: 600px; margin: auto; border: 1px solid #2b3139; }
        #status { text-align: center; color: #f3ba2f; font-size: 0.8em; margin: 10px 0; padding: 8px; background: rgba(243,186,47,0.1); border-radius: 5px; }
    </style></head>
    <body>
        <h3 style="text-align:center; color:#f3ba2f;">🛡️ AI TRADER v8.5 PLATINUM</h3>
        <div class="grid">
            <div class="card"><div class="label">Portfel</div><div id="total" class="value">--</div></div>
            <div class="card"><div class="label">Zysk</div><div id="profit" class="value">--</div></div>
            <div class="card"><div class="label">USDC</div><div id="usdc" class="value">--</div></div>
            <div class="card"><div class="label">Akcje</div><div id="cnt" class="value">--</div></div>
        </div>
        <div id="status">Inicjalizacja...</div>
        <div class="btn-group">
            <button id="b-day" onclick="load('day')" class="active">Dzień</button>
            <button id="b-week" onclick="load('week')">Tydzień</button>
            <button id="b-month" onclick="load('month')">Miesiąc</button>
        </div>
        <div class="chart-wrap"><canvas id="chart"></canvas></div>
        <div class="grid" style="margin-top:10px;">
            <div class="card"><div class="label">BTC Średnia</div><div id="btc_e" class="value">--</div></div>
            <div class="card"><div class="label">ETH Średnia</div><div id="eth_e" class="value">--</div></div>
        </div>
        <script>
            let chart;
            async function load(range) {
                document.querySelectorAll('button').forEach(b => b.classList.remove('active'));
                document.getElementById('b-'+range).classList.add('active');
                try {
                    const r = await fetch('/api/data/'+range);
                    const d = await r.json();
                    document.getElementById('total').innerText = d.state.total + ' $';
                    document.getElementById('profit').innerText = (d.state.profit>=0?'+':'')+d.state.profit + ' $';
                    document.getElementById('usdc').innerText = d.state.usdc;
                    document.getElementById('cnt').innerText = 'B:'+d.state.buy_count+' S:'+d.state.sell_count;
                    document.getElementById('status').innerText = d.state.last_action;
                    document.getElementById('btc_e').innerText = d.state.assets.BTC.entry;
                    document.getElementById('eth_e').innerText = d.state.assets.ETH.entry;
                    
                    const labels = d.history.map(h => {
                        const dt = new Date(h.t);
                        return range === 'day' ? dt.getHours()+':'+dt.getMinutes() : dt.getDate()+'/'+(dt.getMonth()+1);
                    });
                    if(chart) chart.destroy();
                    chart = new Chart(document.getElementById('chart'), {
                        type: 'line',
                        data: { labels: labels, datasets: [{ data: d.history.map(h=>h.v), borderColor: '#f3ba2f', tension: 0.2, fill: true, backgroundColor: 'rgba(243,186,47,0.05)' }] },
                        options: { responsive: true, plugins: { legend: { display: false } } }
                    });
                } catch(e) {}
            }
            setInterval(() => load(document.querySelector('button.active').id.split('-')[1]), 30000);
            load('day');
        </script>
    </body></html>
    """)

if __name__ == "__main__":
    run_loop()
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 10000)))
