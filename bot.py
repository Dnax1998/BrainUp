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

# --- KONFIGURACJA ---
mexc = ccxt.mexc({
    'apiKey': os.getenv('MEXC_API_KEY'),
    'secret': os.getenv('MEXC_SECRET_KEY'),
    'options': {'defaultType': 'spot'},
    'enableRateLimit': True
})
client = Groq(api_key=os.getenv('GROQ_KEY'))

display_state = {
    "usdt": 0.0, "total": 0.0,
    "assets": {
        "BTC": {"amount": 0.0, "rsi": 0, "price": 0.0},
        "ETH": {"amount": 0.0, "rsi": 0, "price": 0.0}
    }
}

def fetch_data_from_mexc():
    try:
        balance = mexc.fetch_balance()
        # Precyzyjne szukanie USDC w portfelu Spot
        usdc_total = 0.0
        if 'USDC' in balance['total']:
            usdc_total = float(balance['total']['USDC'])
        elif 'USDC' in balance:
            usdc_total = float(balance['USDC'].get('total', 0.0))

        btc_amt = float(balance['total'].get('BTC', 0.0))
        eth_amt = float(balance['total'].get('ETH', 0.0))
        
        btc_p = float(mexc.fetch_ticker('BTC/USDC')['last'])
        eth_p = float(mexc.fetch_ticker('ETH/USDC')['last'])
        
        total_val = usdc_total + (btc_amt * btc_p) + (eth_amt * eth_p)
        print(f"✅ Połączono! Saldo portfela: {total_val} USDC")
        return {
            "usdt": usdc_total,
            "assets": {
                "BTC": {"amount": btc_amt, "rsi": 0, "price": btc_p},
                "ETH": {"amount": eth_amt, "rsi": 0, "price": eth_p}
            },
            "total": total_val
        }
    except Exception as e:
        print(f"❌ Błąd komunikacji z MEXC: {str(e)}")
        return None

def calculate_rsi(prices, period=14):
    if len(prices) < period: return 50.0
    delta = prices.diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=period).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
    if loss.iloc[-1] == 0: return 100.0
    return 100 - (100 / (1 + (gain.iloc[-1] / loss.iloc[-1])))

HTML_TEMPLATE = """
<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <title>AI TRADER v6.4 LIVE</title>
    <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css" rel="stylesheet">
    <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
    <style>
        body { background: #0b0e11; color: white; padding: 20px; font-family: 'Segoe UI', sans-serif; }
        .stat-card { background: #1e2329; border: 1px solid #2b3139; border-radius: 12px; padding: 15px; text-align: center; margin-bottom: 15px; }
        .chart-container { background: #1e2329; border-radius: 12px; padding: 20px; margin-bottom: 20px; border: 1px solid #2b3139; }
        .coin-box { background: #181a20; border: 1px solid #2b3139; border-radius: 10px; padding: 10px; border-left: 4px solid #f3ba2f; }
    </style>
</head>
<body>
    <div class="container text-center">
        <h2 style="color: #f3ba2f; margin-bottom: 5px;">🔴 AI TRADER v6.4</h2>
        <p class="text-success small">LIVE MEXC CONNECTED</p>
        
        <div class="row g-3 mb-4">
            <div class="col-4"><div class="stat-card"><small class="text-secondary">PORTFEL USDC</small><br><strong style="font-size: 1.4rem;">{{ usdt|round(2) }}</strong></div></div>
            <div class="col-4"><div class="stat-card"><small class="text-secondary">UPTIME</small><br><strong>{{ uptime }}</strong></div></div>
            <div class="col-4"><div class="stat-card"><small class="text-secondary">TOTAL VALUE $</small><br><strong style="font-size: 1.4rem;">{{ total|round(2) }}</strong></div></div>
        </div>

        <div class="row g-3 mb-4">
            {% for coin, data in assets.items() %}
            <div class="col-6">
                <div class="coin-box">
                    <strong style="color:#f3ba2f">{{ coin }}</strong><br>
                    <span style="font-size: 1.2rem;">{{ data.amount|round(6) }}</span><br>
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
        let chartData = [];
        try { chartData = JSON.parse('{{ chart_json|safe }}'); } catch(e) { console.log(e); }
        
        if(chartData.length > 0) {
            new Chart(ctx, {
                type: 'line',
                data: {
                    labels: chartData.map(d => new Date(d.timestamp).toLocaleTimeString()),
                    datasets: [{ label: 'Saldo Total', data: chartData.map(d => d.balance), borderColor: '#f3ba2f', tension: 0.3, fill: true, backgroundColor: 'rgba(243, 186, 47, 0.1)' }]
                },
                options: { plugins: { legend: { display: false } }, scales: { y: { grid: { color: '#2b3139' } }, x: { grid: { display: false } } } }
            });
        }
        setTimeout(() => location.reload(), 30000);
    </script>
</body>
</html>
"""

def run_loop():
    global display_state
    data = fetch_data_from_mexc()
    if data:
        for symbol in ["BTC", "ETH"]:
            pair = f"{symbol}/USDC"
            try:
                bars = mexc.fetch_ohlcv(pair, timeframe='1m', limit=50)
                df = pd.DataFrame(bars, columns=['ts', 'o', 'h', 'l', 'c', 'v'])
                rsi_val = calculate_rsi(df['c'])
                data['assets'][symbol]['rsi'] = rsi_val
                
                # POPRAWKA BŁĘDU 400: Dodano słowo "json" w system prompt
                sys_p = f"Analizuj rynek. RSI={rsi_val:.1f}. Twoja odpowiedź musi być w formacie json. Kupuj RSI<45, sprzedawaj RSI>65."
                
                chat = client.chat.completions.create(
                    messages=[{"role": "system", "content": sys_p}, 
                              {"role": "user", "content": f"Decyzja dla {symbol} przy cenie {data['assets'][symbol]['price']}"}],
                    model="llama-3.1-8b-instant", 
                    response_format={"type": "json_object"}
                )
                res = json.loads(chat.choices[0].message.content)
                decision = res.get('decision', 'WAIT').upper()
                
                if decision == "BUY" and rsi_val < 45 and data['usdt'] >= 50:
                    print(f"🚀 KUPUJĘ {symbol}")
                    mexc.create_market_buy_order(pair, 50)
                elif decision == "SELL" and data['assets'][symbol]['amount'] > 0 and rsi_val > 55:
                    print(f"💰 SPRZEDAJĘ {symbol}")
                    mexc.create_market_sell_order(pair, data['assets'][symbol]['amount'])
            except Exception as e:
                print(f"Błąd pętli dla {symbol}: {e}")
        
        # Zapis historii salda
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
        try:
            with open(STATS_FILE, 'r') as f: h_data = json.load(f)
        except: pass
    uptime = f"{(datetime.now() - start_time).seconds // 3600}h {((datetime.now() - start_time).seconds // 60) % 60}m"
    return render_template_string(HTML_TEMPLATE, **display_state, uptime=uptime, chart_json=json.dumps(h_data))

if __name__ == "__main__":
    run_loop() # Inicjalizacja danych przy starcie
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 10000)))
