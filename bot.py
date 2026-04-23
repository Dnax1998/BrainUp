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

state = {
    "usdt": 1000.0, 
    "assets": {"BTC": {"amount": 0.0, "rsi": 50.0}, "ETH": {"amount": 0.0, "rsi": 50.0}},
    "total": 1000.0, 
    "history": []
}

client = Groq(api_key=os.getenv('GROQ_KEY'))

def save_balance():
    try:
        data = []
        if os.path.exists(STATS_FILE):
            with open(STATS_FILE, 'r') as f: data = json.load(f)
        data.append({"timestamp": datetime.now().isoformat(), "balance": round(state['total'], 2)})
        with open(STATS_FILE, 'w') as f: json.dump(data[-2000:], f)
    except Exception as e: print(f"Błąd zapisu: {e}")

HTML_TEMPLATE = """
<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <title>AI TRADER v5.1 | WYKRES</title>
    <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css" rel="stylesheet">
    <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
    <style>
        body { background: #0b0e11; color: white; padding: 20px; font-family: 'Segoe UI', sans-serif; }
        .stat-card { background: #1e2329; border: 1px solid #2b3139; border-radius: 12px; padding: 15px; text-align: center; margin-bottom: 15px; }
        .chart-container { background: #1e2329; border-radius: 12px; padding: 20px; margin-bottom: 20px; border: 1px solid #2b3139; }
        .btn-group-sm .btn { color: #aaa; border-color: #444; }
        .btn-group-sm .btn.active { background: #f3ba2f; color: black; border-color: #f3ba2f; }
    </style>
</head>
<body>
    <div class="container">
        <div class="text-center mb-4">
            <h2 style="color: #f3ba2f;">🛡️ AI TRADER v5.1</h2>
            <span class="badge border border-info text-info">⏱️ Uptime: {{ uptime }}</span>
        </div>
        
        <div class="row g-3 mb-4">
            <div class="col-4"><div class="stat-card"><small class="text-secondary">USDT</small><br><strong>{{ usdt|round(2) }}</strong></div></div>
            <div class="col-4"><div class="stat-card"><small class="text-secondary">ZYSK</small><br><strong style="color:{% if total>=1000 %}#02c076{% else %}#f84960{% endif %}">{{ (total-1000)|round(2) }}</strong></div></div>
            <div class="col-4"><div class="stat-card"><small class="text-secondary">TOTAL</small><br><strong>{{ total|round(2) }}</strong></div></div>
        </div>

        <div class="chart-container">
            <div class="d-flex justify-content-between align-items-center mb-3">
                <h6 class="m-0">Krzywa Salda</h6>
                <div class="btn-group btn-group-sm">
                    <button class="btn btn-outline-secondary active" onclick="updateChart('1D')">1D</button>
                    <button class="btn btn-outline-secondary" onclick="updateChart('7D')">7D</button>
                    <button class="btn btn-outline-secondary" onclick="updateChart('30D')">30D</button>
                </div>
            </div>
            <canvas id="balanceChart" height="120"></canvas>
        </div>

        <div class="row g-3 mb-4">
            {% for coin, data in assets.items() %}
            <div class="col-6">
                <div class="p-2 border border-secondary rounded bg-dark text-center">
                    <small style="color:#f3ba2f">{{ coin }}</small> | <strong>RSI: {{ data.rsi|round(1) }}</strong>
                </div>
            </div>
            {% endfor %}
        </div>

        <h6>Dziennik:</h6>
        {% for t in history[::-1][:5] %}
        <div class="p-2 mb-1 rounded bg-dark border-start border-3 {% if t.action=='KUPNO' %}border-success{% else %}border-danger{% endif %}" style="font-size:0.8rem">
            <strong>{{ t.action }} {{ t.coin }}</strong> | {{ t.price }} | <span class="text-secondary">{{ t.time }}</span>
        </div>
        {% endfor %}
    </div>

    <script>
        let allData = JSON.parse('{{ chart_json|safe }}');
        let chart;

        function updateChart(range) {
            const now = new Date();
            let filtered = allData;
            
            if(range === '1D') filtered = allData.filter(d => (now - new Date(d.timestamp)) < 86400000);
            if(range === '7D') filtered = allData.filter(d => (now - new Date(d.timestamp)) < 604800000);
            
            const labels = filtered.map(d => {
                let dt = new Date(d.timestamp);
                return range === '1D' ? dt.getHours()+':'+dt.getMinutes() : dt.toLocaleDateString();
            });

            chart.data.labels = labels;
            chart.data.datasets[0].data = filtered.map(d => d.balance);
            chart.update();
            
            // Zmiana aktywnego przycisku
            document.querySelectorAll('.btn-group .btn').forEach(b => b.classList.remove('active'));
            event.target.classList.add('active');
        }

        const ctx = document.getElementById('balanceChart').getContext('2d');
        chart = new Chart(ctx, {
            type: 'line',
            data: {
                labels: [], 
                datasets: [{
                    label: 'Saldo $',
                    data: [],
                    borderColor: '#f3ba2f',
                    backgroundColor: 'rgba(243, 186, 47, 0.1)',
                    fill: true, tension: 0.3, pointRadius: 1
                }]
            },
            options: { plugins: { legend: { display: false } }, scales: { x: { ticks: { color: '#666', maxTicksLimit: 5 } }, y: { grid: { color: '#222' }, ticks: { color: '#666' } } } }
        });
        
        updateChart('1D');
        setTimeout(() => location.reload(), 60000);
    </script>
</body>
</html>
"""

def calculate_rsi(prices, period=14):
    if len(prices) < period: return 50.0
    delta = prices.diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=period).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
    rs = gain / loss
    return 100 - (100 / (1 + rs.iloc[-1]))

def run_multi_analysis():
    try:
        ex = ccxt.mexc()
        current_total = state['usdt']
        for symbol in ["BTC", "ETH"]:
            pair = f"{symbol}/USDT"
            bars = ex.fetch_ohlcv(pair, timeframe='1m', limit=50)
            df = pd.DataFrame(bars, columns=['ts', 'o', 'h', 'l', 'c', 'v'])
            rsi_val = calculate_rsi(df['c'])
            price = float(df['c'].iloc[-1])
            state['assets'][symbol]['rsi'] = rsi_val
            current_total += state['assets'][symbol]['amount'] * price
            
            sys_p = f"Trader {symbol}. RSI={rsi_val:.1f}. Kupuj RSI<45, Sprzedaj RSI>65 lub zysk. Zakaz kupna RSI>60. JSON: {{\"decision\": \"BUY/SELL/WAIT\", \"reason\": \"...\"}}"
            chat = client.chat.completions.create(messages=[{"role": "system", "content": sys_p}, {"role": "user", "content": f"Cena: {price}. Masz: {state['assets'][symbol]['amount']}"}], model="llama-3.1-8b-instant", response_format={"type": "json_object"})
            res = json.loads(chat.choices[0].message.content)
            decision = res.get('decision', 'WAIT').upper()
            
            if "BUY" in decision and rsi_val < 45 and state['usdt'] >= 100:
                state['assets'][symbol]['amount'] += (100 / price); state['usdt'] -= 100
                state['history'].append({"time": time.strftime("%H:%M"), "action": "KUPNO", "coin": symbol, "price": price, "reason": res.get('reason')})
            elif "SELL" in decision and state['assets'][symbol]['amount'] > 0 and (rsi_val > 55 or "profit" in res.get('reason').lower()):
                state['usdt'] += state['assets'][symbol]['amount'] * price; state['assets'][symbol]['amount'] = 0.0
                state['history'].append({"time": time.strftime("%H:%M"), "action": "SPRZEDAŻ", "coin": symbol, "price": price, "reason": res.get('reason')})
        
        state['total'] = current_total
        save_balance()
    except Exception as e: print(e)

scheduler = BackgroundScheduler()
scheduler.add_job(func=run_multi_analysis, trigger="interval", minutes=1)
scheduler.start()

@app.route('/')
def home():
    chart_data = []
    if os.path.exists(STATS_FILE):
        with open(STATS_FILE, 'r') as f: chart_data = json.load(f)
    uptime = f"{(datetime.now() - start_time).seconds // 3600}h {((datetime.now() - start_time).seconds // 60) % 60}m"
    return render_template_string(HTML_TEMPLATE, **state, uptime=uptime, chart_json=json.dumps(chart_data))

if __name__ == "__main__":
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 10000)))
