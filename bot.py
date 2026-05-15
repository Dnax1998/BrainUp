import os, json, ccxt, pandas as pd
from flask import Flask, render_template_string, jsonify
from apscheduler.schedulers.background import BackgroundScheduler
from datetime import datetime, timedelta
from groq import Groq

app = Flask('')
# Plik do przechowywania historii salda, aby wykres nie znikał po restarcie
STATS_FILE = 'balance_history.json'

# --- KONFIGURACJA ---
INITIAL_CAPITAL = 1000.0
TRADE_AMOUNT_USDC = 40
RSI_BUY_THRESHOLD = 35
RSI_SELL_THRESHOLD = 58
COOLDOWN_MINUTES = 15

mexc = ccxt.mexc({
    'apiKey': os.getenv('MEXC_API_KEY'),
    'secret': os.getenv('MEXC_SECRET_KEY'),
    'options': {'defaultType': 'spot'},
    'enableRateLimit': True
})

groq_client = Groq(api_key=os.getenv('GROQ_KEY'))

state = {
    "usdc": 0.0, "total": 0.0, "profit": 0.0,
    "buy_count": 0, "sell_count": 0,
    "last_action": "System Ready",
    "assets": {"BTC": {"amount":0, "rsi":50}, "ETH": {"amount":0, "rsi":50}}
}

last_buy_time = {"BTC": datetime.now() - timedelta(hours=1), "ETH": datetime.now() - timedelta(hours=1)}

def save_to_history(total_val):
    history = []
    if os.path.exists(STATS_FILE):
        with open(STATS_FILE, 'r') as f:
            try: history = json.load(f)
            except: history = []
    
    # Dodajemy nowy punkt: czas (timestamp) i wartość
    history.append({"t": datetime.now().strftime("%H:%M"), "v": round(total_val, 2)})
    
    # Zachowujemy ostatnie 100 pomiarów, by nie zapchać pamięci
    with open(STATS_FILE, 'w') as f:
        json.dump(history[-100:], f)

def get_rsi(symbol):
    try:
        bars = mexc.fetch_ohlcv(f"{symbol}/USDC", timeframe='1m', limit=50)
        df = pd.DataFrame(bars, columns=['ts', 'o', 'h', 'l', 'c', 'v'])
        delta = df['c'].diff()
        gain = (delta.where(delta > 0, 0)).rolling(14).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(14).mean()
        rsi = 100 - (100 / (1 + (gain / loss)))
        return round(rsi.iloc[-1], 1)
    except: return 50.0

def trade_logic():
    global state, last_buy_time
    try:
        mexc.load_markets()
        balance = mexc.fetch_balance()
        usdc_now = float(balance.get('USDC', {}).get('free', 0.0))
        total_val = float(balance.get('USDC', {}).get('total', 0.0))
        
        actions = []

        for sym in ["BTC", "ETH"]:
            pair = f"{sym}/USDC"
            ticker = mexc.fetch_ticker(pair)
            price = float(ticker['last'])
            owned = float(balance.get(sym, {}).get('total', 0.0))
            total_val += (owned * price)
            
            rsi = get_rsi(sym)
            state["assets"][sym] = {"amount": round(owned, 6), "rsi": rsi}

            if rsi < RSI_BUY_THRESHOLD and usdc_now >= TRADE_AMOUNT_USDC:
                if datetime.now() - last_buy_time[sym] > timedelta(minutes=COOLDOWN_MINUTES):
                    try:
                        buy_price = price * 1.001 
                        qty = TRADE_AMOUNT_USDC / buy_price
                        prec_price = mexc.price_to_precision(pair, buy_price)
                        prec_qty = mexc.amount_to_precision(pair, qty)
                        mexc.create_order(pair, 'limit', 'buy', prec_qty, prec_price)
                        last_buy_time[sym] = datetime.now()
                        state["buy_count"] += 1
                        actions.append(f"✅ BUY {sym}")
                    except Exception as e:
                        actions.append(f"❌ ERR {sym}")

            elif rsi > RSI_SELL_THRESHOLD and owned > 0:
                try:
                    sell_price = price * 0.999
                    prec_price = mexc.price_to_precision(pair, sell_price)
                    prec_qty = mexc.amount_to_precision(pair, owned)
                    mexc.create_order(pair, 'limit', 'sell', prec_qty, prec_price)
                    state["sell_count"] += 1
                    actions.append(f"💰 SELL {sym}")
                except Exception as e:
                    actions.append(f"❌ SELL ERR {sym}")

        state.update({
            "usdc": round(usdc_now, 2),
            "total": round(total_val, 2),
            "profit": round(total_val - INITIAL_CAPITAL, 2),
            "last_action": " | ".join(actions) if actions else f"Scanning... ({datetime.now().strftime('%H:%M')})"
        })
        save_to_history(total_val)
    except Exception as e:
        state["last_action"] = f"CRITICAL ERR: {str(e)[:30]}"

@app.route('/api/data')
def get_data():
    history = []
    if os.path.exists(STATS_FILE):
        with open(STATS_FILE, 'r') as f:
            history = json.load(f)
    return jsonify({"state": state, "history": history})

@app.route('/')
def home():
    return render_template_string("""
    <!DOCTYPE html><html><head>
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
    <style>
        body { background: #050505; color: #00ff41; font-family: 'Courier New', monospace; padding: 20px; }
        .card { border: 2px solid #00ff41; padding: 15px; margin-bottom: 15px; background: #000; box-shadow: 0 0 10px #00ff41; }
        .label { color: #888; font-size: 0.8em; }
        .val { font-size: 1.4em; display: block; }
        .status { color: #ffbc00; border-color: #ffbc00; box-shadow: 0 0 10px #ffbc00; }
        .asset-row { display: flex; justify-content: space-between; border-bottom: 1px solid #222; padding: 5px 0; }
        .chart-box { height: 200px; margin-top: 10px; }
    </style></head>
    <body>
        <div class="card">
            <span class="label">TOTAL EQUITY</span>
            <span class="val" id="total">0.00</span>
            <div class="chart-box"><canvas id="balanceChart"></canvas></div>
        </div>
        <div class="card">
            <span class="label">WALLET (USDC)</span>
            <span id="usdc" class="val">0.00</span>
        </div>
        <div class="card status">
            <span class="label" style="color:#ffbc00">SYSTEM LOG</span>
            <span class="val" id="log">INITIALIZING...</span>
        </div>
        <div class="card">
            <div class="asset-row"><b>ASSET</b><b>RSI</b><b>HOLDING</b></div>
            <div class="asset-row"><span>BTC</span><span id="btc_rsi">--</span><span id="btc_amt">--</span></div>
            <div class="asset-row"><span>ETH</span><span id="eth_rsi">--</span><span id="eth_amt">--</span></div>
        </div>
        <script>
            let chart;
            async function update() {
                try {
                    const r = await fetch('/api/data'); const d = await r.json();
                    document.getElementById('usdc').innerText = d.state.usdc + ' $';
                    document.getElementById('total').innerText = d.state.total + ' $';
                    document.getElementById('log').innerText = d.state.last_action;
                    document.getElementById('btc_rsi').innerText = d.state.assets.BTC.rsi;
                    document.getElementById('eth_rsi').innerText = d.state.assets.ETH.rsi;
                    document.getElementById('btc_amt').innerText = d.state.assets.BTC.amount;
                    document.getElementById('eth_amt').innerText = d.state.assets.ETH.amount;

                    const ctx = document.getElementById('balanceChart').getContext('2d');
                    const labels = d.history.map(h => h.t);
                    const values = d.history.map(h => h.v);

                    if(!chart) {
                        chart = new Chart(ctx, {
                            type: 'line',
                            data: {
                                labels: labels,
                                datasets: [{ label: 'Total Value', data: values, borderColor: '#00ff41', tension: 0.3, fill: false }]
                            },
                            options: { responsive: true, maintainAspectRatio: false, plugins: { legend: { display: false } }, scales: { x: { display: false }, y: { grid: { color: '#111' } } } }
                        });
                    } else {
                        chart.data.labels = labels;
                        chart.data.datasets[0].data = values;
                        chart.update();
                    }
                } catch(e) {}
            }
            setInterval(update, 5000); update();
        </script>
    </body></html>
    """)

if __name__ == "__main__":
    scheduler = BackgroundScheduler()
    scheduler.add_job(func=trade_logic, trigger="interval", seconds=30)
    scheduler.start()
    trade_logic()
    app.run(host='0.0.0.0', port=10000)
