import os
import time
import json
import ccxt
import pandas as pd
from groq import Groq
from flask import Flask, render_template_string
from apscheduler.schedulers.background import BackgroundScheduler
from datetime import datetime

app = Flask('')
start_time = datetime.now()
STATS_FILE = 'balance_history.json'

# Inicjalizacja MEXC
mexc = ccxt.mexc({
    'apiKey': os.getenv('MEXC_API_KEY'),
    'secret': os.getenv('MEXC_SECRET_KEY'),
    'options': {'defaultType': 'spot'}
})

client = Groq(api_key=os.getenv('GROQ_KEY'))

# Stan początkowy (żeby Dashboard nie był "pusty" na starcie)
display_state = {
    "usdt": 0.0,
    "total": 0.0,
    "assets": {
        "BTC": {"amount": 0.0, "rsi": 0, "price": 0.0},
        "ETH": {"amount": 0.0, "rsi": 0, "price": 0.0}
    },
    "history": []
}

def get_real_state():
    try:
        balance = mexc.fetch_balance()
        usdc = float(balance['total'].get('USDC', 0.0))
        btc_amt = float(balance['total'].get('BTC', 0.0))
        eth_amt = float(balance['total'].get('ETH', 0.0))
        
        btc_p = float(mexc.fetch_ticker('BTC/USDC')['last'])
        eth_p = float(mexc.fetch_ticker('ETH/USDC')['last'])
        
        total = usdc + (btc_amt * btc_p) + (eth_amt * eth_p)
        
        return {
            "usdt": usdc,
            "assets": {
                "BTC": {"amount": btc_amt, "rsi": 0, "price": btc_p},
                "ETH": {"amount": eth_amt, "rsi": 0, "price": eth_p}
            },
            "total": total
        }
    except Exception as e:
        print(f"Błąd portfela: {e}")
        return None

HTML_TEMPLATE = """
<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <title>AI TRADER v6.1 LIVE</title>
    <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css" rel="stylesheet">
    <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
    <style>
        body { background: #0b0e11; color: white; padding: 20px; font-family: 'Segoe UI', sans-serif; }
        .stat-card { background: #1e2329; border: 1px solid #2b3139; border-radius: 12px; padding: 15px; text-align: center; margin-bottom: 15px; }
        .chart-container { background: #1e2329; border-radius: 12px; padding: 20px; margin-bottom: 20px; border: 1px solid #2b3139; }
        .coin-box { background: #181a20; border: 1px solid #2b3139; border-radius: 10px; padding: 10px; }
    </style>
</head>
<body>
    <div class="container">
        <div class="text-center mb-4">
            <h2 style="color: #f3ba2f;">🔴 LIVE: AI TRADER v6.1</h2>
            <span class="badge border border-warning text-warning">Konto Realne MEXC</span>
        </div>
        
        <div class="row g-3 mb-4">
            <div class="col-4"><div class="stat-card"><small class="text-secondary">USDC</small><br><strong>{{ usdt|default(0)|round(2) }}</strong></div></div>
            <div class="col-4"><div class="stat-card"><small class="text-secondary">UPTIME</small><br><strong>{{ uptime }}</strong></div></div>
            <div class="col-4"><div class="stat-card"><small class="text-secondary">ŁĄCZNIE $</small><br><strong>{{ total|default(0)|round(2) }}</strong></div></div>
        </div>

        <div class="chart-container">
            <h6>Trend Portfela</h6>
            <canvas id="balanceChart" height="100"></canvas>
        </div>

        <div class="row g-3 mb-4">
            {% for coin, data in assets.items() %}
            <div class="col-6">
                <div class="coin-box text-center">
                    <strong style="color:#f3ba2f">{{ coin }}</strong><br>
                    <span style="font-size: 1.2rem;">{{ data.amount|default(0)|round(6) }}</span><br>
                    <small class="text-secondary">RSI: {{ data.rsi|default(0)|round(1) }}</small>
                </div>
            </div>
            {% endfor %}
        </div>
    </div>
    <script>
        const ctx = document.getElementById('balanceChart').getContext('2d');
        let chartData = [];
        try { chartData = JSON.parse('{{ chart_json|safe }}'); } catch(e) {}
        
        if(chartData.length > 0) {
            new Chart(ctx, {
                type: 'line',
                data: {
                    labels: chartData.map(d => new Date(d.timestamp).getHours() + ":" + new Date(d.timestamp).getMinutes()),
                    datasets: [{
                        label: 'Saldo USDC',
                        data: chartData.map(d => d.balance),
                        borderColor: '#f3ba2f',
                        fill: true, tension: 0.3, pointRadius: 1
                    }]
                },
                options: { plugins: { legend: { display: false } }, scales: { y: { grid: { color: '#222' } } } }
            });
        }
        setTimeout(() => location.reload(), 30000);
    </script>
</body>
</html>
"""

def save_balance(val):
    try:
        data = []
        if os.path.exists(STATS_FILE):
            with open(STATS_FILE, 'r') as f: data = json.load(f)
        data.append({"timestamp": datetime.now().isoformat(), "balance": round(val, 2)})
        with open(STATS_FILE, 'w') as f: json.dump(data[-1000:], f)
    except: pass

def calculate_rsi(prices, period=14):
    if len(prices) < period: return 50.0
    delta = prices.diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=period).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
    rs = gain / loss
    return 100 - (100 / (1 + rs.iloc[-1]))

def run_loop():
    global display_state
    try:
        live = get_real_state()
        if not live: return
        
        for symbol in ["BTC", "ETH"]:
            pair = f"{symbol}/USDC"
            bars = mexc.fetch_ohlcv(pair, timeframe='1m', limit=50)
            df = pd.DataFrame(bars, columns=['ts', 'o', 'h', 'l', 'c', 'v'])
            rsi_val = calculate_rsi(df['c'])
            live['assets'][symbol]['rsi'] = rsi_val
            
            # AI
            sys_p = f"Trader MEXC. RSI={rsi_val:.1f}. Kupuj RSI<45, Sprzedaj RSI>65."
            chat = client.chat.completions.create(
                messages=[{"role": "system", "content": sys_p}, 
                          {"role": "user", "content": f"Cena: {live['assets'][symbol]['price']}. Masz {live['assets'][symbol]['amount']} {symbol}"}],
                model="llama-3.1-8b-instant", response_format={"type": "json_object"}
            )
            res = json.loads(chat.choices[0].message.content)
            
            if res.get('decision') == "BUY" and rsi_val < 45 and live['usdt'] >= 50:
                mexc.create_market_buy_order(pair, 50)
            elif res.get('decision') == "SELL" and live['assets'][symbol]['amount'] > 0 and rsi_val > 55:
                mexc.create_market_sell_order(pair, live['assets'][symbol]['amount'])
        
        save_balance(live['total'])
        display_state = live
    except Exception as e:
        print(f"Loop error: {e}")

scheduler = BackgroundScheduler()
scheduler.add_job(func=run_loop, trigger="interval", minutes=2)
scheduler.start()

@app.route('/')
def home():
    chart_data = []
    if os.path.exists(STATS_FILE):
        with open(STATS_FILE, 'r') as f: chart_data = json.load(f)
    
    uptime = f"{(datetime.now() - start_time).seconds // 3600}h {((datetime.now() - start_time).seconds // 60) % 60}m"
    # Bezpieczne przekazanie danych do template
    return render_template_string(HTML_TEMPLATE, **display_state, uptime=uptime, chart_json=json.dumps(chart_data))

if __name__ == "__main__":
    # Pierwszy odczyt danych przy starcie, żeby Dashboard nie był pusty
    run_loop()
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 10000)))
