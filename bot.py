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

# --- INICJALIZACJA ---
def get_mexc_client():
    return ccxt.mexc({
        'apiKey': os.getenv('MEXC_API_KEY'),
        'secret': os.getenv('MEXC_SECRET_KEY'),
        'options': {'defaultType': 'spot'},
        'enableRateLimit': True
    })

mexc = get_mexc_client()
client = Groq(api_key=os.getenv('GROQ_KEY'))

# Stan globalny
display_state = {
    "usdt": 0.0,
    "total": 0.0,
    "assets": {
        "BTC": {"amount": 0.0, "rsi": 0, "price": 0.0},
        "ETH": {"amount": 0.0, "rsi": 0, "price": 0.0}
    }
}

def fetch_data_from_mexc():
    try:
        # Próba pobrania salda
        balance = mexc.fetch_balance()
        
        # Wyciąganie USDC - MEXC czasem trzyma to w 'free' lub 'total'
        usdc_total = float(balance.get('USDC', {}).get('total', 0.0))
        btc_amt = float(balance.get('BTC', {}).get('total', 0.0))
        eth_amt = float(balance.get('ETH', {}).get('total', 0.0))
        
        # Pobieranie cen
        btc_p = float(mexc.fetch_ticker('BTC/USDC')['last'])
        eth_p = float(mexc.fetch_ticker('ETH/USDC')['last'])
        
        total_val = usdc_total + (btc_amt * btc_p) + (eth_amt * eth_p)
        
        print(f"✅ Dane pobrane! Total: {total_val} USDC")
        
        return {
            "usdt": usdc_total,
            "assets": {
                "BTC": {"amount": btc_amt, "rsi": 0, "price": btc_p},
                "ETH": {"amount": eth_amt, "rsi": 0, "price": eth_p}
            },
            "total": total_val
        }
    except Exception as e:
        print(f"❌ Błąd fetch_data: {str(e)}")
        return None

# --- HTML TEMPLATE (Ten sam co v6.2 z drobną poprawką filtrów) ---
HTML_TEMPLATE = """
<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <title>AI TRADER v6.3 LIVE</title>
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
    <div class="container text-center">
        <h2 style="color: #f3ba2f;">🔴 AI TRADER v6.3</h2>
        <span class="badge bg-success mb-4">LIVE MEXC CONNECTED</span>
        
        <div class="row g-3 mb-4">
            <div class="col-4"><div class="stat-card"><small>PORTFEL USDC</small><br><strong>{{ usdt|round(2) }}</strong></div></div>
            <div class="col-4"><div class="stat-card"><small>UPTIME</small><br><strong>{{ uptime }}</strong></div></div>
            <div class="col-4"><div class="stat-card"><small>TOTAL VALUE</small><br><strong>{{ total|round(2) }}</strong></div></div>
        </div>

        <div class="row g-3 mb-4">
            {% for coin, data in assets.items() %}
            <div class="col-6">
                <div class="coin-box">
                    <strong style="color:#f3ba2f">{{ coin }}</strong><br>
                    <span>{{ data.amount|round(6) }}</span><br>
                    <small class="text-secondary">RSI: {{ data.rsi|round(1) }}</small>
                </div>
            </div>
            {% endfor %}
        </div>
        
        <div class="chart-container">
            <canvas id="balanceChart" height="100"></canvas>
        </div>
    </div>
    <script>
        const ctx = document.getElementById('balanceChart').getContext('2d');
        let chartData = JSON.parse('{{ chart_json|safe }}');
        if(chartData.length > 0) {
            new Chart(ctx, {
                type: 'line',
                data: {
                    labels: chartData.map(d => new Date(d.timestamp).toLocaleTimeString()),
                    datasets: [{ label: 'USDC', data: chartData.map(d => d.balance), borderColor: '#f3ba2f', tension: 0.3 }]
                }
            });
        }
        setTimeout(() => location.reload(), 30000);
    </script>
</body>
</html>
"""

def calculate_rsi(prices, period=14):
    if len(prices) < period: return 50.0
    delta = prices.diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=period).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
    if loss.iloc[-1] == 0: return 100.0
    return 100 - (100 / (1 + (gain.iloc[-1] / loss.iloc[-1])))

def run_loop():
    global display_state
    data = fetch_data_from_mexc()
    if data:
        for symbol in ["BTC", "ETH"]:
            pair = f"{symbol}/USDC"
            bars = mexc.fetch_ohlcv(pair, timeframe='1m', limit=50)
            df = pd.DataFrame(bars, columns=['ts', 'o', 'h', 'l', 'c', 'v'])
            rsi_val = calculate_rsi(df['c'])
            data['assets'][symbol]['rsi'] = rsi_val
            
            # AI Decision
            sys_p = f"Trader. RSI={rsi_val:.1f}. Kupuj RSI<45, Sprzedaj RSI>65."
            chat = client.chat.completions.create(
                messages=[{"role": "system", "content": sys_p}, {"role": "user", "content": f"Cena: {data['assets'][symbol]['price']}"}],
                model="llama-3.1-8b-instant", response_format={"type": "json_object"}
            )
            res = json.loads(chat.choices[0].message.content)
            
            if res.get('decision') == "BUY" and rsi_val < 45 and data['usdt'] >= 50:
                mexc.create_market_buy_order(pair, 50)
            elif res.get('decision') == "SELL" and data['assets'][symbol]['amount'] > 0 and rsi_val > 55:
                mexc.create_market_sell_order(pair, data['assets'][symbol]['amount'])
        
        # Save history
        try:
            h_data = []
            if os.path.exists(STATS_FILE):
                with open(STATS_FILE, 'r') as f: h_data = json.load(f)
            h_data.append({"timestamp": datetime.now().isoformat(), "balance": round(data['total'], 2)})
            with open(STATS_FILE, 'w') as f: json.dump(h_data[-500:], f)
        except: pass
        
        display_state = data

scheduler = BackgroundScheduler()
scheduler.add_job(func=run_loop, trigger="interval", minutes=2)
scheduler.start()

@app.route('/')
def home():
    h_data = []
    if os.path.exists(STATS_FILE):
        with open(STATS_FILE, 'r') as f: h_data = json.load(f)
    uptime = f"{(datetime.now() - start_time).seconds // 3600}h {((datetime.now() - start_time).seconds // 60) % 60}m"
    return render_template_string(HTML_TEMPLATE, **display_state, uptime=uptime, chart_json=json.dumps(h_data))

if __name__ == "__main__":
    run_loop() # Pierwszy strzał danych
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 10000)))
