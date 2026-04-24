import os
import time
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
INITIAL_CAPITAL = 1000.0  # Kwota startowa do liczenia zysku

# --- KONFIGURACJA ---
mexc = ccxt.mexc({
    'apiKey': os.getenv('MEXC_API_KEY'),
    'secret': os.getenv('MEXC_SECRET_KEY'),
    'options': {'defaultType': 'spot'},
    'enableRateLimit': True
})
client = Groq(api_key=os.getenv('GROQ_KEY'))

# Globalny stan bota
display_state = {
    "usdc": 0.0, 
    "total": 1000.0, 
    "profit": 0.0, 
    "assets": {
        "BTC": {"amount":0, "rsi":50, "price":0}, 
        "ETH": {"amount":0, "rsi":50, "price":0}
    }
}

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
            
            # --- LOGIKA HANDLU (100 USDC) ---
            sys_prompt = f"Trader. RSI={rsi_val:.1f}. Kupuj < 45, Sprzedaj > 65. JSON: {{\"decision\": \"BUY/SELL/WAIT\"}}"
            chat = client.chat.completions.create(
                messages=[{"role":"system","content":sys_prompt}], 
                model="llama-3.1-8b-instant", 
                response_format={"type":"json_object"}
            )
            decision = json.loads(chat.choices[0].message.content).get('decision', 'WAIT')
            
            if decision == "BUY" and rsi_val < 48 and usdc_free >= 100:
                p = round(price * 1.001, 2)
                mexc.create_order(pair, 'limit', 'buy', round(100/p, 6), p)
                print(f"🛒 Kupiono {symbol} za 100 USDC")
            elif decision == "SELL" and amt > 0 and rsi_val > 65:
                mexc.create_market_sell_order(pair, amt)
                print(f"💸 Sprzedano {symbol}")

            assets_update[symbol] = {"amount": round(amt, 6), "rsi": round(rsi_val, 1), "price": price}

        profit = current_total - INITIAL_CAPITAL
        display_state = {
            "usdc": round(usdc_free, 2), 
            "total": round(current_total, 2), 
            "profit": round(profit, 2), 
            "assets": assets_update
        }
        
        history = []
        if os.path.exists(STATS_FILE):
            with open(STATS_FILE, 'r') as f: history = json.load(f)
        history.append({"t": datetime.now().isoformat(), "v": round(current_total, 2)})
        with open(STATS_FILE, 'w') as f: json.dump(history[-5000:], f)

    except Exception as e:
        print(f"Błąd pętli: {e}")

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
        <title>AI Trader Pro v7.6</title>
        <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
        <meta name="viewport" content="width=device-width, initial-scale=1">
        <style>
            body { background: #0b0e11; color: white; font-family: 'Segoe UI', sans-serif; margin: 0; padding: 15px; }
            .grid { display: grid; grid-template-columns: repeat(2, 1fr); gap: 10px; max-width: 600px; margin: auto; }
            .card { background: #1e2329; padding: 15px; border-radius: 12px; border: 1px solid #2b3139; text-align: center; }
            .label { color: #848e9c; font-size: 0.75em; text-transform: uppercase; margin-bottom: 5px; }
            .value { font-size: 1.2em; font-weight: bold; }
            .profit-plus { color: #0ecb81; } .profit-minus { color: #f6465d; }
            .chart-btn-group { margin: 15px auto; display: flex; justify-content: center; gap: 5px; }
            .chart-btn { background: #2b3139; border: none; color: white; padding: 6px 15px; border-radius: 6px; cursor: pointer; font-size: 0.8em; }
            .chart-btn.active { background: #f3ba2f; color: black; font-weight: bold; }
            .chart-container { max-width: 600px; margin: auto; background: #1e2329; border-radius: 12px; padding: 10px; border: 1px solid #2b3139; }
            .status-line { color: #0ecb81; font-size: 0.8em; font-weight: bold; margin-bottom: 15px; text-align: center; }
        </style>
    </head>
    <body>
        <h3 style="color: #f3ba2f; text-align:center; margin-bottom: 5px;">🔴 AI TRADER v7.6 LIVE</h3>
        <div class="status-line">● POŁĄCZONO Z MEXC (Trade: 100 USDC)</div>
        
        <div class="grid">
            <div class="card"><div class="label">Dostępne USDC</div><div class="value" id="usdc">--</div></div>
            <div class="card"><div class="label">Uptime</div><div class="value">"""+uptime+"""</div></div>
            <div class="card"><div class="label">Zysk / Strata</div><div class="value" id="profit">--</div></div>
            <div class="card"><div class="label">Wartość Portfela</div><div class="value" id="total">--</div></div>
        </div>

        <div class="chart-btn-group">
            <button class="chart-btn active" onclick="setPeriod('D')">Dzień</button>
            <button class="chart-btn" onclick="setPeriod('W')">Tydzień</button>
            <button class="chart-btn" onclick="setPeriod('M')">Miesiąc</button>
        </div>
        
        <div class="chart-container">
            <canvas id="myChart"></canvas>
        </div>

        <script>
            let chart; 
            let currentPeriod = 'D';

            function setPeriod(p) {
                currentPeriod = p;
                document.querySelectorAll('.chart-btn').forEach(b => b.classList.remove('active'));
                event.target.classList.add('active');
                update();
            }

            async function update() {
                const res = await fetch('/api/data');
                const data = await res.json();
                
                document.getElementById('usdc').innerText = data.state.usdc;
                document.getElementById('total').innerText = data.state.total;
                const pElem = document.getElementById('profit');
                pElem.innerText = (data.state.profit >= 0 ? '+' : '') + data.state.profit + ' $';
                pElem.className = 'value ' + (data.state.profit >= 0 ? 'profit-plus' : 'profit-minus');

                let filteredHistory = data.history;
                const now = new Date();
                
                if(currentPeriod === 'D') {
                    filteredHistory = data.history.filter(h => (now - new Date(h.t)) < 86400000);
                } else if(currentPeriod === 'W') {
                    filteredHistory = data.history.filter(h => (now - new Date(h.t)) < 604800000);
                } else if(currentPeriod === 'M') {
                    filteredHistory = data.history.filter(h => (now - new Date(h.t)) < 2592000000);
                }

                const labels = filteredHistory.map(h => {
                    let d = new Date(h.t);
                    return currentPeriod === 'D' ? d.toLocaleTimeString([], {hour: '2-digit', minute:'2-digit'}) : d.toLocaleDateString([], {day: 'numeric', month:'short'});
                });
                const values = filteredHistory.map(h => h.v);

                if (!chart) {
                    const ctx = document.getElementById('myChart').getContext('2d');
                    chart = new Chart(ctx, {
                        type: 'line',
                        data: { 
                            labels: labels, 
                            datasets: [{ 
                                label: 'Total Value', 
                                data: values, 
                                borderColor: '#f3ba2f', 
                                tension: 0.3, 
                                fill: true, 
                                backgroundColor: 'rgba(243, 186, 47, 0.05)',
                                pointRadius: 2
                            }] 
                        },
                        options: { 
                            plugins: { legend: { display: false } }, 
                            scales: { 
                                y: { grid: { color: '#2b3139' }, ticks: { color: '#848e9c' } }, 
                                x: { grid: { display: false }, ticks: { color: '#848e9c', maxRotation: 0 } } 
                            } 
                        }
                    });
                } else {
                    chart.data.labels = labels; 
                    chart.data.datasets[0].data = values; 
                    chart.update();
                }
            }
            setInterval(update, 30000); 
            update();
        </script>
    </body>
    </html>
    """)

if __name__ == "__main__":
    run_loop()
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 10000)))
