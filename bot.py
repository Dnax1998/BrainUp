import os
import time
import json
import ccxt
import pandas as pd
from groq import Groq
from flask import Flask, render_template_string
from apscheduler.schedulers.background import BackgroundScheduler

app = Flask('')

state = {
    "usdt": 1000.0, 
    "assets": {
        "BTC": {"amount": 0.0, "rsi": 50.0},
        "ETH": {"amount": 0.0, "rsi": 50.0}
    },
    "total": 1000.0, 
    "history": []
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
    <title>AI TRADER v4.1 DISCIPLINED</title>
    <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css" rel="stylesheet">
    <style>
        body { background: #0b0e11; color: white; padding: 20px; font-family: 'Segoe UI', sans-serif; }
        .stat-card { background: #1e2329; border: 1px solid #2b3139; border-radius: 12px; padding: 15px; text-align: center; margin-bottom: 15px; }
        .history-item { background: #1e2329; border-left: 4px solid #00f2ff; margin-top: 8px; padding: 12px; border-radius: 4px; font-size: 0.9rem; }
        .action-KUPNO { border-left-color: #02c076; }
        .action-SPRZEDAŻ { border-left-color: #f84960; }
        .coin-tag { font-weight: bold; color: #f3ba2f; }
        .profit-plus { color: #02c076; }
        .profit-minus { color: #f84960; }
    </style>
</head>
<body>
    <div class="container">
        <h2 class="text-center mb-4" style="color: #f3ba2f;">🛡️ AI TRADER v4.1 (Full Power)</h2>
        
        <div class="row g-3">
            <div class="col-md-4"><div class="stat-card"><small class="text-secondary">GOTÓWKA USDT</small><h4>{{ usdt|round(2) }}</h4></div></div>
            <div class="col-md-4"><div class="stat-card"><small class="text-secondary">ZYSK/STRATA</small><h4 class="{% if total >= 1000 %}profit-plus{% else %}profit-minus{% endif %}">{{ (total - 1000)|round(2) }}</h4></div></div>
            <div class="col-md-4"><div class="stat-card"><small class="text-secondary">WARTOŚĆ KONTA</small><h4>{{ total|round(2) }}</h4></div></div>
        </div>

        <div class="row g-3 mb-4">
            {% for coin, data in assets.items() %}
            <div class="col-6">
                <div class="p-3 border border-secondary rounded bg-dark">
                    <span class="coin-tag">{{ coin }}</span> | RSI: <strong>{{ data.rsi|round(1) }}</strong><br>
                    <small>Posiadasz: {{ data.amount|round(6) }}</small>
                </div>
            </div>
            {% endfor %}
        </div>

        <h5>Dziennik Operacji:</h5>
        {% for t in history[::-1][:15] %}
        <div class="history-item action-{{ t.action }}">
            <div class="d-flex justify-content-between">
                <span><strong>{{ t.action }} {{ t.coin }}</strong> @ {{ t.price }}</span>
                <span class="text-white-50">{{ t.time }}</span>
            </div>
            <div class="small text-secondary">{{ t.reason }}</div>
        </div>
        {% endfor %}
    </div>
    <script>setTimeout(() => location.reload(), 20000);</script>
</body>
</html>
"""

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
            
            # Nowy, bardziej rygorystyczny prompt
            system_prompt = (
                f"Jesteś matematycznym traderem {symbol}. RSI={rsi_val:.1f}. "
                "ZASADY: 1. Kupuj tylko jeśli RSI < 45. 2. Sprzedawaj jeśli RSI > 65 lub masz zysk > 1%. "
                "3. Jeśli RSI > 60, kategoryczny ZAKAZ kupowania. "
                "Odpowiadaj tylko JSON: {\"decision\": \"BUY/SELL/WAIT\", \"reason\": \"...\"}"
            )

            chat_completion = client.chat.completions.create(
                messages=[{"role": "system", "content": system_prompt}, {"role": "user", "content": f"Cena: {price}. Masz: {state['assets'][symbol]['amount']}."}],
                model="llama-3.1-8b-instant",
                response_format={"type": "json_object"}
            )
            
            res = json.loads(chat_completion.choices[0].message.content)
            decision = res.get('decision', 'WAIT').upper()
            reason = res.get('reason', '...')
            
            # Logika wykonawcza z blokadą RSI
            if "BUY" in decision and rsi_val < 45 and state['usdt'] >= 100:
                state['assets'][symbol]['amount'] += (100 / price)
                state['usdt'] -= 100
                state['history'].append({"time": time.strftime("%H:%M"), "action": "KUPNO", "coin": symbol, "price": price, "reason": f"RSI {rsi_val:.1f}: {reason}"})
            
            elif "SELL" in decision and state['assets'][symbol]['amount'] > 0:
                # Sprzedaż tylko jeśli AI chce I warunki sprzyjają (RSI > 55 lub zysk)
                if rsi_val > 55 or "profit" in reason.lower():
                    state['usdt'] += state['assets'][symbol]['amount'] * price
                    state['assets'][symbol]['amount'] = 0.0
                    state['history'].append({"time": time.strftime("%H:%M"), "action": "SPRZEDAŻ", "coin": symbol, "price": price, "reason": f"RSI {rsi_val:.1f}: {reason}"})

        state['total'] = current_total
        if len(state['history']) > 50: state['history'].pop(0)

    except Exception as e:
        print(f"Error: {e}")

scheduler = BackgroundScheduler()
scheduler.add_job(func=run_multi_analysis, trigger="interval", minutes=1)
scheduler.start()

@app.route('/')
def home(): return render_template_string(HTML_TEMPLATE, **state)

if __name__ == "__main__":
    port = int(os.environ.get('PORT', 10000))
    app.run(host='0.0.0.0', port=port, use_reloader=False)
