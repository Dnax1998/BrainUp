import os
import time
import json
import ccxt
import pandas as pd
from groq import Groq
from flask import Flask, render_template_string
from apscheduler.schedulers.background import BackgroundScheduler

app = Flask('')

# Rozbudowany stan bota (z licznikami)
state = {
    "usdt": 1000.0, 
    "btc": 0.0, 
    "total": 1000.0, 
    "history": [],
    "buy_count": 0,
    "sell_count": 0,
    "last_rsi": 50.0
}

client = Groq(api_key=os.getenv('GROQ_KEY'))

def calculate_rsi(prices, period=14):
    if len(prices) < period: return 50.0
    delta = prices.diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=period).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
    rs = gain / loss
    return 100 - (100 / (1 + rs.iloc[-1]))

HTML_TEMPLATE = """
<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <title>AI TRADER ULTRA v3.3</title>
    <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css" rel="stylesheet">
    <style>
        body { background: #0b0e11; color: white; padding: 20px; font-family: 'Segoe UI', sans-serif; }
        .stat-card { background: #1e2329; border: 1px solid #2b3139; border-radius: 12px; padding: 15px; text-align: center; }
        .history-item { background: #1e2329; border-left: 4px solid #00f2ff; margin-top: 8px; padding: 12px; border-radius: 4px; }
        .action-KUPNO { border-left-color: #02c076; }
        .action-SPRZEDAŻ { border-left-color: #f84960; }
        .val-profit { color: #02c076; font-weight: bold; }
    </style>
</head>
<body>
    <div class="container">
        <h2 class="text-center mb-4" style="color: #00f2ff;">🛡️ AI TRADER ULTRA v3.3</h2>
        
        <div class="row g-3 mb-4">
            <div class="col-md-3 col-6"><div class="stat-card"><small class="text-secondary">PORTFEL USDT</small><h4>{{ usdt|round(2) }}</h4></div></div>
            <div class="col-md-3 col-6"><div class="stat-card"><small class="text-secondary">ZYSK/STRATA</small><h4 class="val-profit">{{ (total - 1000)|round(2) }}</h4></div></div>
            <div class="col-md-3 col-6"><div class="stat-card"><small class="text-secondary">OBECNE RSI</small><h4 style="color: #f3ba2f">{{ last_rsi|round(2) }}</h4></div></div>
            <div class="col-md-3 col-6"><div class="stat-card"><small class="text-secondary">AKTYWNE BTC</small><h4>{{ btc|round(6) }}</h4></div></div>
        </div>

        <div class="row g-2 mb-4 text-center">
            <div class="col-6"><div class="p-2 border border-secondary rounded">🛒 Zakupy: <strong>{{ buy_count }}</strong></div></div>
            <div class="col-6"><div class="p-2 border border-secondary rounded">💰 Sprzedaże: <strong>{{ sell_count }}</strong></div></div>
        </div>

        <h5>Dziennik Operacji:</h5>
        {% for t in history[::-1][:25] %}
        <div class="history-item action-{{ t.action }}">
            <div class="d-flex justify-content-between">
                <span class="badge {% if t.action=='KUPNO' %}bg-success{% elif t.action=='SPRZEDAŻ' %}bg-danger{% else %}bg-secondary{% endif %}">{{ t.action }}</span>
                <span class="text-white-50" style="font-size: 0.75rem;">{{ t.time }}</span>
            </div>
            <p class="mt-2 mb-0"><strong>Cena: {{ t.price }} USDT</strong><br><small class="text-secondary">{{ t.reason }}</small></p>
        </div>
        {% endfor %}
    </div>
    <script>setTimeout(() => location.reload(), 10000);</script>
</body>
</html>
"""

def run_analysis():
    try:
        ex = ccxt.mexc()
        bars = ex.fetch_ohlcv("BTC/USDT", timeframe='1m', limit=50)
        df = pd.DataFrame(bars, columns=['ts', 'o', 'h', 'l', 'c', 'v'])
        
        rsi_val = calculate_rsi(df['c'])
        price = float(df['c'].iloc[-1])
        state['last_rsi'] = rsi_val
        
        system_prompt = (
            f"Jesteś traderem. RSI={rsi_val:.1f}. Sentyment Twittera: Byczy. "
            "Kupuj pakiety 200 USDT jeśli RSI < 40. Sprzedaj wszystko jeśli RSI > 65 lub masz zysk. "
            "Graj agresywnie. Odpowiadaj tylko JSON: {\"decision\": \"BUY/SELL/WAIT\", \"reason\": \"...\"}"
        )

        chat_completion = client.chat.completions.create(
            messages=[{"role": "system", "content": system_prompt}, {"role": "user", "content": f"Cena: {price}. Portfel: {state['usdt']}u, {state['btc']}b."}],
            model="llama-3.1-8b-instant",
            response_format={"type": "json_object"}
        )
        
        res = json.loads(chat_completion.choices[0].message.content)
        decision = res.get('decision', 'WAIT').upper()
        reason = res.get('reason', '...')
        act_name = "CZEKANIE"

        if "BUY" in decision and state['usdt'] >= 200:
            state['btc'] += (200 / price)
            state['usdt'] -= 200
            state['buy_count'] += 1
            act_name = "KUPNO"
        elif "SELL" in decision and state['btc'] > 0.00001:
            state['usdt'] += state['btc'] * price
            state['btc'] = 0.0
            state['sell_count'] += 1
            act_name = "SPRZEDAŻ"

        state['total'] = state['usdt'] + (state['btc'] * price)
        state['history'].append({"time": time.strftime("%H:%M:%S"), "action": act_name, "price": price, "reason": f"RSI: {rsi_val:.1f} | {reason}"})
        if len(state['history']) > 50: state['history'].pop(0)

    except Exception as e:
        print(f"Error: {e}")

scheduler = BackgroundScheduler()
scheduler.add_job(func=run_analysis, trigger="interval", minutes=1)
scheduler.start()

@app.route('/')
def home(): return render_template_string(HTML_TEMPLATE, **state)

if __name__ == "__main__":
    port = int(os.environ.get('PORT', 10000))
    app.run(host='0.0.0.0', port=port, use_reloader=False)
