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
    <title>AI TRADER PRO v3 | RSI & Sentiment</title>
    <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css" rel="stylesheet">
    <style>
        body { background: #0b0e11; color: white; padding: 20px; font-family: 'Segoe UI', sans-serif; }
        .stat-card { background: #1e2329; border: 1px solid #2b3139; border-radius: 12px; padding: 15px; text-align: center; }
        .history-item { background: #1e2329; border-left: 4px solid #00f2ff; margin-top: 8px; padding: 12px; border-radius: 4px; }
        .indicator-badge { font-size: 0.8rem; padding: 5px 10px; border-radius: 20px; background: #2b3139; }
        .action-KUPNO { border-left-color: #02c076; }
        .action-SPRZEDAŻ { border-left-color: #f84960; }
    </style>
</head>
<body>
    <div class="container">
        <h2 class="text-center mb-4" style="color: #f3ba2f;">🛡️ AI TRADER ULTRA v3</h2>
        
        <div class="row g-3 mb-4">
            <div class="col-md-3"><div class="stat-card"><small class="text-secondary">USDT</small><h4>{{ usdt|round(2) }}</h4></div></div>
            <div class="col-md-3"><div class="stat-card"><small class="text-secondary">ZYSK/STRATA</small><h4 style="color: #02c076">{{ (total - 1000)|round(2) }} u</h4></div></div>
            <div class="col-md-3"><div class="stat-card"><small class="text-secondary">OBECNE RSI</small><h4>{{ last_rsi|round(2) }}</h4></div></div>
            <div class="col-md-3"><div class="stat-card"><small class="text-secondary">TRANSAKCJE</small><h4>{{ buy_count + sell_count }}</h4></div></div>
        </div>

        <div class="alert alert-dark border-secondary">
            <strong>Analiza techniczna:</strong> RSI {{ last_rsi|round(2) }} | Pakiety: 200 USDT | Śr. Cena: {{ avg_price|round(2) }}
        </div>

        <h5>Dziennik Operacji:</h5>
        <div class="mt-2">
            {% for t in history[::-1][:20] %}
            <div class="history-item action-{{ t.action }}">
                <div class="d-flex justify-content-between align-items-center">
                    <span class="badge {% if t.action=='KUPNO' %}bg-success{% elif t.action=='SPRZEDAŻ' %}bg-danger{% else %}bg-secondary{% endif %}">{{ t.action }}</span>
                    <span class="text-white-50" style="font-size: 0.8rem;">{{ t.time }}</span>
                </div>
                <div class="mt-2">
                    <strong>BTC: {{ t.price }} USDT</strong><br>
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
        bars = ex.fetch_ohlcv("BTC/USDT", timeframe='1m', limit=50)
        df = pd.DataFrame(bars, columns=['ts', 'o', 'h', 'l', 'c', 'v'])
        rsi = ta.rsi(df['c'], length=14)
        return rsi.iloc[-1], df['c'].iloc[-1]
    except:
        return 50.0, 0.0

def run_analysis():
    try:
        rsi_val, price = get_indicators()
        state['last_rsi'] = rsi_val
        
        # Symulacja sentymentu z sieci (Twitter/News) - AI wyciąga wnioski z trendów
        system_prompt = (
            f"Jesteś traderem PRO. Masz dane techniczne: RSI wynosi {rsi_val:.2f}. "
            "Pamiętaj: RSI < 30 to wyprzedanie (KUPUJ), RSI > 70 to wykupienie (SPRZEDAŻ). "
            "Dodatkowo z Twittera płynie sentyment 'BULLISH' (optymistyczny). "
            "Zarządzaj kapitałem 1000 USDT w pakietach po 200. "
            "Odpowiadaj TYLKO JSON: {\"decision\": \"BUY/SELL/WAIT\", \"reason\": \"...\"}"
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
            new_btc = 200 / price
            total_btc = state['btc'] + new_btc
            state['avg_price'] = ((state['btc'] * state['avg_price']) + (new_btc * price)) / total_btc if total_btc > 0 else price
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
        if len(state['history']) > 100: state['history'].pop(0)

    except Exception as e:
        print(f"Błąd: {e}")

scheduler = BackgroundScheduler()
scheduler.add_job(func=run_analysis, trigger="interval", minutes=1)
scheduler.start()

@app.route('/')
def home():
    return render_template_string(HTML_TEMPLATE, **state)

if __name__ == "__main__":
    port = int(os.environ.get('PORT', 10000))
    app.run(host='0.0.0.0', port=port, use_reloader=False)
