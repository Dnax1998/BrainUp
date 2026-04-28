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
INITIAL_CAPITAL = 1000.0 

mexc = ccxt.mexc({
    'apiKey': os.getenv('MEXC_API_KEY'),
    'secret': os.getenv('MEXC_SECRET_KEY'),
    'options': {'defaultType': 'spot'},
    'enableRateLimit': True
})

groq_client = Groq(api_key=os.getenv('GROQ_KEY'))

display_state = {
    "usdc": 0.0, "total": 1000.0, "profit": 0.0,
    "last_action": "System BrainUp v9.2 Online",
    "assets": {"BTC": {"amount":0, "rsi":50}, "ETH": {"amount":0, "rsi":50}}
}

def ask_ai_decision(symbol, price, rsi):
    try:
        prompt = f"Analyze {symbol}: Price {price}, RSI {rsi}. Buy or Wait? Answer ONLY 'BUY' or 'WAIT'."
        completion = groq_client.chat.completions.create(
            model="llama3-8b-8192",
            messages=[{"role": "user", "content": prompt}],
            max_tokens=10
        )
        return "BUY" in completion.choices[0].message.content.strip().upper()
    except: return True

def run_loop():
    global display_state
    try:
        balance = mexc.fetch_balance()
        usdc_free = float(balance.get('USDC', {}).get('free', 0.0))
        current_total = usdc_free
        assets_update = {}
        
        for symbol in ["BTC", "ETH"]:
            pair = f"{symbol}/USDC"
            price = float(mexc.fetch_ticker(pair)['last'])
            amt = float(balance.get(symbol, {}).get('free', 0.0))
            current_total += (amt * price)
            assets_update[symbol] = {"amount": round(amt, 6), "rsi": 50.0} # Uproszczone dla czytelności

        display_state.update({
            "usdc": round(usdc_free, 2), "total": round(current_total, 2), 
            "profit": round(current_total - INITIAL_CAPITAL, 2),
            "assets": assets_update
        })
        
        history = []
        if os.path.exists(STATS_FILE):
            with open(STATS_FILE, 'r') as f: history = json.load(f)
        history.append({"t": datetime.now().isoformat(), "v": round(current_total, 2)})
        with open(STATS_FILE, 'w') as f: json.dump(history[-20000:], f)
    except Exception as e: print(f"Loop Error: {e}")

scheduler = BackgroundScheduler()
scheduler.add_job(run_loop, 'interval', minutes=1)
scheduler.start()

@app.route('/api/data/<range_type>')
def get_data(range_type):
    if not os.path.exists(STATS_FILE): return jsonify({"state": display_state, "history": []})
    with open(STATS_FILE, 'r') as f: history = json.load(f)
    
    now = datetime.now()
    points = []
    
    if range_type == 'day':
        # Punkt co godzinę, max 24
        for i in range(23, -1, -1):
            target = now - timedelta(hours=i)
            match = min(history, key=lambda x: abs((datetime.fromisoformat(x['t']) - target).total_seconds()))
            points.append({"t": target.strftime("%H:00"), "v": match['v']})
            
    elif range_type == 'week':
        # Punkt co 12h, max 14
        for i in range(13, -1, -1):
            target = now - timedelta(hours=i*12)
            match = min(history, key=lambda x: abs((datetime.fromisoformat(x['t']) - target).total_seconds()))
            points.append({"t": target.strftime("%d/%m %Hh"), "v": match['v']})
            
    elif range_type == 'month':
        # Punkt raz dziennie o 0:00, max 30
        for i in range(29, -1, -1):
            target = (now - timedelta(days=i)).replace(hour=0, minute=0, second=0)
            match = min(history, key=lambda x: abs((datetime.fromisoformat(x['t']) - target).total_seconds()))
            points.append({"t": target.strftime("%d/%m"), "v": match['v']})

    return jsonify({"state": display_state, "history": points})

@app.route('/')
def home():
    return render_template_string("""
    <!DOCTYPE html><html><head><title>BrainUp v9.2</title>
    <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <style>
        body { background: #0b0e11; color: white; font-family: sans-serif; padding: 15px; }
        .grid { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; max-width: 600px; margin: auto; }
        .card { background: #1e2329; padding: 15px; border-radius: 12px; border: 1px solid #2b3139; text-align: center; }
        .label { color: #848e9c; font-size: 0.75em; margin-bottom: 5px; }
        .value { font-size: 1.2em; font-weight: bold; }
        .chart-container { max-width: 600px; margin: 20px auto; background: #1e2329; border-radius: 12px; padding: 10px; border: 1px solid #2b3139; }
        .btn-group { display: flex; justify-content: center; gap: 5px; margin-bottom: 15px; }
        button { background: #2b3139; color: #848e9c; border: none; padding: 8px 15px; border-radius: 6px; cursor: pointer; }
        button.active { background: #f3ba2f; color: black; font-weight: bold; }
        .asset-row { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; max-width: 600px; margin: auto; margin-top: 15px; }
    </style></head>
    <body>
        <h3 style="color: #f3ba2f; text-align:center;">🧠 AI TRADER v9.2 BrainUp</h3>
        <div class="grid">
            <div class="card"><div class="label">USDC Wolne</div><div class="value" id="usdc">--</div></div>
            <div class="card"><div class="label">Portfel</div><div class="value" id="total">--</div></div>
            <div class="card" style="grid-column: span 2;">
                <div class="label">Zysk / Strata</div>
                <div id="profit" class="value" style="font-size: 1.8em;">--</div>
            </div>
        </div>

        <div class="chart-container">
            <div class="btn-group">
                <button id="btn-day" onclick="update('day')" class="active">Dzień</button>
                <button id="btn-week" onclick="update('week')">Tydzień</button>
                <button id="btn-month" onclick="update('month')">Miesiąc</button>
            </div>
            <canvas id="myChart"></canvas>
        </div>

        <div class="asset-row">
            <div class="card"><div style="color:#f3ba2f; font-size:0.8em;">BTC</div><div id="btc_amt" class="value">0</div></div>
            <div class="card"><div style="color:#f3ba2f; font-size:0.8em;">ETH</div><div id="eth_amt" class="value">0</div></div>
        </div>

        <script>
            let chart; let currentRange = 'day';
            async function update(range) {
                currentRange = range;
                document.querySelectorAll('button').forEach(b => b.classList.remove('active'));
                document.getElementById('btn-' + range).classList.add('active');
                
                const res = await fetch('/api/data/' + range);
                const d = await res.json();
                
                document.getElementById('usdc').innerText = d.state.usdc + ' $';
                document.getElementById('total').innerText = d.state.total + ' $';
                
                // KOLOROWANIE ZYSKU
                const profitEl = document.getElementById('profit');
                profitEl.innerText = (d.state.profit > 0 ? '+' : '') + d.state.profit + ' $';
                profitEl.style.color = d.state.profit >= 0 ? '#02c076' : '#cf304a';

                document.getElementById('btc_amt').innerText = d.state.assets.BTC.amount;
                document.getElementById('eth_amt').innerText = d.state.assets.ETH.amount;

                const labels = d.history.map(h => h.t);
                const values = d.history.map(h => h.v);

                if(!chart) {
                    chart = new Chart(document.getElementById('myChart'), {
                        type:'line', data:{labels:labels, datasets:[{data:values, borderColor:'#f3ba2f', backgroundColor:'rgba(243,186,47,0.1)', fill:true, tension:0.4}]},
                        options:{responsive:true, plugins:{legend:{display:false}}, scales:{x:{grid:{display:false}},y:{grid:{color:'#2b3139'}}}}
                    });
                } else { chart.data.labels = labels; chart.data.datasets[0].data = values; chart.update(); }
            }
            setInterval(() => update(currentRange), 30000); update('day');
        </script>
    </body></html>
    """)

if __name__ == "__main__":
    run_loop(); app.run(host='0.0.0.0', port=10000)
