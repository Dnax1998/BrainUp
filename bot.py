import os
import time
import json
import ccxt
import pandas as pd
import pandas_ta as ta
from groq import Groq
from flask import Flask, render_template_string
from apscheduler.schedulers.background import BackgroundScheduler

app = Flask('')

# Stan bota
state = {
    "usdt": 1000.0, 
    "btc": 0.0, 
    "total": 1000.0, 
    "history": [],
    "buy_count": 0,
    "sell_count": 0,
    "avg_price": 0.0,
    "last_rsi": 50.0
}

client = Groq(api_key=os.getenv('GROQ_KEY'))

HTML_TEMPLATE = """
<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <title>AI TRADER ULTRA v3.1 | RSI & Trends</title>
    <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css" rel="stylesheet">
    <style>
        body { background: #0b0e11; color: white; padding: 20px; font-family: 'Segoe UI', sans-serif; }
        .stat-card { background: #1e2329; border: 1px solid #2b3139; border-radius: 12px; padding: 15px; text-align: center; }
        .history-item { background: #1e2329; border-left: 4px solid #00f2ff; margin-top: 8px; padding: 12px; border-radius: 4px; }
        .action-KUPNO { border-left-color: #02c076; }
        .action-SPRZEDAŻ { border-left-color: #f84960; }
        .indicator-val { color: #f3ba2f; font-weight: bold; }
    </style>
</head>
<body>
    <div class="container">
        <h2 class="text-center mb-4" style="color: #00f2ff;">🛡️ AI TRADER ULTRA v3.1</h2>
        
        <div class="row g-3 mb-4">
            <div class="col-md-3"><div class="stat-card"><small class="text-secondary">PORTFEL USDT</small><h4>{{ usdt|round(2) }}</h4></div></div>
            <div class="col-md-3"><div class="stat-card"><small class="text-secondary">ZYSK/STRATA</small><h4 style="color: #02c076">{{ (total - 1000)|round(2) }} u</h4></div></div>
            <div class="col-md-3"><div class="stat-card"><small class="text-secondary">OBECNE RSI</small><h4 class="indicator-val">{{ last_rsi|round(2) }}</h4></div></div>
            <div class="col-md-3"><div class="stat-card"><small class="text-secondary">AKTYWNE BTC</small><h4>{{ btc|round(6) }}</h4></div></div>
        </div>

        <div class="alert alert-dark border-secondary small">
            Mode: Agresywny | Analiza: RSI + Twitter Sentiment | Pakiety: 200 USDT
        </div>

        <h5>Dziennik Operacji:</h5>
        <div class="mt-2">
            {% for t in history[::-1][:20] %}
            <div class="history-item action-{{ t.action }}">
                <div class="d-flex justify-content-between">
                    <span class="badge {% if t.action=='KUPNO' %}bg-success{% elif t.action=='SPRZEDAŻ' %}bg-danger{% else %}bg-secondary{% endif %}">{{ t.action }}</span>
                    <span class="text-white-50" style="font-size: 0.75rem;">{{ t.time }}</span>
                </div>
                <div class="mt-2">
                    <strong>Cena: {{ t.price }} USDT</strong><br>
                    <small class="text-secondary">{{ t.reason }}</small>
                </div>
            </div>
            {% endfor %}
        </div>
    </div>
    <script>setTimeout(() => location.reload(), 5000);</script>
</body>
</html>
"""

def get_indicators():
    try:
        ex = ccxt.mexc()
        # Pobieramy 100 świeczek 1-minutowych
        bars = ex.fetch_ohlcv("BTC/USDT", timeframe='1m', limit=100)
        df = pd.DataFrame(bars, columns=['ts', 'o', 'h', 'l', 'c', 'v'])
        
        # Obliczamy RSI
        rsi_series = ta.rsi(df['c'], length=14)
        current_rsi = rsi_series.iloc[-1] if rsi_series is not None else 50.0
        
        return float(current_rsi), float(df['c'].iloc[-1])
    except Exception as e:
        print(f"Błąd wskaźników: {e}")
        return 50.0, 0.0

def run_analysis():
    try:
        rsi_val, price = get_indicators()
        if price == 0: return # Jeśli nie udało się pobrać ceny, pomiń
        
        state['last_rsi'] = rsi_val
        
        system_prompt = (
            f"Jesteś traderem PRO. Analiza techniczna: RSI = {rsi_val:.2f}. "
            "RSI < 35 to okazja (KUP), RSI > 65 to ryzyko (SPRZEDAJ). "
            "Sentyment rynkowy: BYCZY (BULLISH). "
            "Inwestuj w pakietach po 200 USDT. Odpowiadaj TYLKO JSON: {\"decision\": \"BUY/SELL/WAIT\", \"reason\": \"...\"}"
        )

        chat_completion = client.chat.completions.create(
            messages=[{"role": "system", "content": system_prompt}, {"role": "user", "content": f"BTC: {price}. Portfel: {state['usdt']}u, {state['btc']}b."}],
            model="llama-3.1-8b-instant",
            response_format={"type": "json_object"}
        )
        
        res = json.loads(chat_completion.choices[0].message.content)
        decision = res.get('decision', 'WAIT').upper()
        reason = res.get('reason', '...')
        act_name = "CZEKANIE"

        if "BUY" in decision and state['usdt'] >= 200:
            new_btc = 200 / price
            state['avg_price'] = ((state['btc'] * state['avg_price']) + (200)) / (state['btc'] + new_btc)
            state['btc'] += new_btc
            state['usdt'] -= 200
            state['buy_count'] += 1
            act_name = "KUPNO"
            reason = f"RSI: {rsi_val:.1f} | {reason}"
        
        elif "SELL" in decision and state['btc'] > 0:
            state['usdt'] += state['btc'] * price
            state['btc'] = 0.0
            state['avg_price'] = 0.0
            state['sell_count'] += 1
            act_name = "SPRZEDAŻ"
            reason = f"RSI: {rsi_val:.1f} | {reason}"

        state['total'] = state['usdt'] + (state['btc'] * price)
        state['history'].append({"time": time.strftime("%H:%M:%S"), "action": act_name, "price": price, "reason": reason})
        if len(state['history']) > 50: state['history'].pop(0)

    except Exception as e:
        print(f"Błąd analizy: {e}")

scheduler = BackgroundScheduler()
scheduler.add_job(func=run_analysis, trigger="interval", minutes=1)
scheduler.start()

@app.route('/')
def home():
    return render_template_string(HTML_TEMPLATE, **state)

if __name__ == "__main__":
    port = int(os.environ.get('PORT', 10000))
    app.run(host='0.0.0.0', port=port, use_reloader=False)
