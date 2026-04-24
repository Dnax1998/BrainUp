import os
import time
import json
import ccxt
import pandas as pd
from groq import Groq
from flask import Flask, render_template_string, jsonify
from apscheduler.schedulers.background import BackgroundScheduler
from datetime import datetime

app = Flask('')
start_time = datetime.now()
STATS_FILE = 'balance_history.json'

# --- KONFIGURACJA GIEŁDY ---
mexc = ccxt.mexc({
    'apiKey': os.getenv('MEXC_API_KEY'),
    'secret': os.getenv('MEXC_SECRET_KEY'),
    'options': {'defaultType': 'spot'},
    'enableRateLimit': True
})
client = Groq(api_key=os.getenv('GROQ_KEY'))

# Stan bota
display_state = {"usdc": 0.0, "total": 1000.0, "assets": {"BTC": {"amount":0, "rsi":50, "price":0}, "ETH": {"amount":0, "rsi":50, "price":0}}}

def log_to_console(msg):
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}", flush=True)

def calculate_rsi(prices, period=14):
    if len(prices) < period: return 50.0
    delta = prices.diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=period).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
    if loss.iloc[-1] == 0: return 100.0
    rs = gain.iloc[-1] / loss.iloc[-1]
    return 100 - (100 / (1 + rs))

def run_loop():
    global display_state
    try:
        balance = mexc.fetch_balance()
        usdc_free = float(balance.get('USDC', {}).get('free', 0.0))
        current_total = usdc_free
        assets_update = {}

        for symbol in ["BTC", "ETH"]:
            pair = f"{symbol}/USDC"
            ticker = mexc.fetch_ticker(pair)
            price = float(ticker['last'])
            bars = mexc.fetch_ohlcv(pair, timeframe='1m', limit=50)
            df = pd.DataFrame(bars, columns=['ts', 'o', 'h', 'l', 'c', 'v'])
            rsi_val = calculate_rsi(df['c'])
            amt = float(balance.get(symbol, {}).get('total', 0.0))
            current_total += (amt * price)

            # Konsultacja AI
            sys_prompt = f"Trader. RSI={rsi_val:.1f}. Kupuj < 45, Sprzedaj > 65. Zwróć JSON: {{\"decision\": \"BUY/SELL/WAIT\"}}"
            chat = client.chat.completions.create(
                messages=[{"role": "system", "content": sys_prompt}],
                model="llama-3.1-8b-instant",
                response_format={"type": "json_object"}
            )
            decision = json.loads(chat.choices[0].message.content).get('decision', 'WAIT')
            
            # Handel (LIMIT dla kupna)
            if decision == "BUY" and rsi_val < 48 and usdc_free >= 50:
                buy_price = round(price * 1.001, 2)
                mexc.create_order(pair, 'limit', 'buy', round(50/buy_price, 6), buy_price)
                log_to_console(f"✅ Kupiono {symbol}")
            elif decision == "SELL" and amt > 0 and rsi_val > 65:
                mexc.create_market_sell_order(pair, amt)
                log_to_console(f"✅ Sprzedano {symbol}")

            assets_update[symbol] = {"amount": round(amt, 6), "rsi": round(rsi_val, 1), "price": price}

        display_state = {"usdc": round(usdc_free, 2), "total": round(current_total, 2), "assets": assets_update}
        
        # Historia do wykresu
        history = []
        if os.path.exists(STATS_FILE):
            with open(STATS_FILE, 'r') as f: history = json.load(f)
        history.append({"t": datetime.now().strftime('%H:%M:%S'), "v": round(current_total, 2)})
        with open(STATS_FILE, 'w') as f: json.dump(history[-20:], f)

    except Exception as e:
        log_to_console(f"Błąd: {e}")

scheduler = BackgroundScheduler()
scheduler.add_job(func=run_loop, trigger="interval", minutes=2)
scheduler.start()

@app.route('/api/data')
def get_data():
    history = []
    if os.path.exists(STATS_FILE):
        with open(STATS_FILE, 'r') as f: history = json.load(f)
    return jsonify({"state": display_state, "history": history})

@app.route('/')
def home():
    uptime = f"{(datetime.now() - start_time).seconds // 3600}h {((datetime.now() - start_time).seconds // 60) % 60}m"
    return render_template_string("""
    <!DOCTYPE html>
    <html>
    <head>
        <title>AI Trader Live</title>
        <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
        <meta name="viewport" content="width=device-width, initial-scale=1">
        <style>
            body { background: #0b0e11; color: white; font-family: 'Segoe UI', sans-serif; margin: 0; padding: 20px; text-align: center; }
            .grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr)); gap: 15px; max-width: 800px; margin: 20px auto; }
            .card { background: #1e2329; padding: 20px; border-radius: 12px; border: 1px solid #2b3139; }
            .label { color: #848e9c; font-size: 0.8em; text-transform: uppercase; margin-bottom: 8px; }
            .value { font-size: 1.4em; font-weight: bold; }
            .btc-eth { display: grid; grid-template-columns: 1fr 1fr; gap: 15px; max-width: 800px; margin: auto; }
            .asset-card { background: #1e2329; padding: 15px; border-radius: 12px; }
            .rsi-bar { color: #f3ba2f; font-size: 0.9em; margin-top: 5px; }
            .chart-container { max-width: 800px; margin: 30px auto; background: #1e2329; padding: 20px; border-radius: 15px; }
            .status { color: #0ecb81; font-weight: bold; margin-bottom: 20px; display: block; }
        </style>
    </head>
    <body>
        <h2 style="color: #f3ba2f; margin-bottom: 5px;">🔴 AI TRADER v7.2 LIVE</h2>
        <span class="status">● POŁĄCZONO Z MEXC</span>

        <div class="grid">
            <div class="card"><div class="label">USDC</div><div class="value" id="usdc">--</div></div>
            <div class="card"><div class="label">Uptime</div><div class="value">"""+uptime+"""</div></div>
            <div class="card"><div class="label">Total $</div><div class="value" id="total">--</div></div>
        </div>

        <div class="btc-eth">
            <div class="asset-card">
                <div style="color:#f3ba2f; font-weight:bold;">BTC</div>
                <div id="btc_amt" class="value">0.0</div>
                <div id="btc_rsi" class="rsi-bar">RSI: --</div>
            </div>
            <div class="asset-card">
                <div style="color:#f3ba2f; font-weight:bold;">ETH</div>
                <div id="eth_amt" class="value">0.0</div>
                <div id="eth_rsi" class="rsi-bar">RSI: --</div>
            </div>
        </div>

        <div class="chart-container">
            <canvas id="myChart"></canvas>
        </div>

        <script>
            let chart;
            async function update() {
                const res = await fetch('/api/data');
                const data = await res.json();
                
                document.getElementById('usdc').innerText = data.state.usdc;
                document.getElementById('total').innerText = data.state.total;
                document.getElementById('btc_amt').innerText = data.state.assets.BTC.amount;
                document.getElementById('btc_rsi').innerText = 'RSI: ' + data.state.assets.BTC.rsi;
                document.getElementById('eth_amt').innerText = data.state.assets.ETH.amount;
                document.getElementById('eth_rsi').innerText = 'RSI: ' + data.state.assets.ETH.rsi;

                const labels = data.history.map(h => h.t);
                const values = data.history.map(h => h.v);

                if (!chart) {
                    const ctx = document.getElementById('myChart').getContext('2d');
                    chart = new Chart(ctx, {
                        type: 'line',
                        data: {
                            labels: labels,
                            datasets: [{
                                label: 'Total Value (USDC)',
                                data: values,
                                borderColor: '#f3ba2f',
                                tension: 0.3,
                                fill: false
                            }]
                        },
                        options: { scales: { y: { beginAtZero: false } } }
                    });
                } else {
                    chart.data.labels = labels;
                    chart.data.datasets[0].data = values;
                    chart.update();
                }
            }
            setInterval(update, 10000);
            update();
        </script>
    </body>
    </html>
    """)

if __name__ == "__main__":
    run_loop()
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 10000)))
