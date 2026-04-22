import os
import time
import json
import ccxt
from groq import Groq
from flask import Flask, render_template_string
from apscheduler.schedulers.background import BackgroundScheduler

app = Flask('')

# Rozbudowany stan bota
state = {
    "usdt": 1000.0, 
    "btc": 0.0, 
    "total": 1000.0, 
    "history": [],
    "buy_count": 0,
    "sell_count": 0,
    "avg_price": 0.0
}

client = Groq(api_key=os.getenv('GROQ_KEY'))

HTML_TEMPLATE = """
<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <title>AI TRADER PRO | Stats & 20% Strategy</title>
    <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css" rel="stylesheet">
    <style>
        body { background: #0b0e11; color: white; padding: 20px; font-family: 'Segoe UI', sans-serif; }
        .stat-card { background: #1e2329; border: 1px solid #2b3139; border-radius: 12px; padding: 15px; text-align: center; height: 100%; }
        .history-item { background: #1e2329; border-left: 4px solid #00f2ff; margin-top: 8px; padding: 12px; border-radius: 4px; }
        .action-KUPNO { border-left-color: #02c076; }
        .action-SPRZEDAŻ { border-left-color: #f84960; }
        .text-profit { color: #02c076; font-weight: bold; }
    </style>
</head>
<body>
    <div class="container">
        <h2 class="text-center mb-4" style="color: #00f2ff;">🚀 DASHBOARD HANDLOWY AI</h2>
        
        <div class="row g-3 mb-4">
            <div class="col-md-3"><div class="stat-card"><small class="text-secondary">USDT</small><h4>{{ usdt|round(2) }}</h4></div></div>
            <div class="col-md-3"><div class="stat-card"><small class="text-secondary">WARTOŚĆ BTC</small><h4>{{ (btc * history[-1].price if history else 0)|round(2) }}</h4></div></div>
            <div class="col-md-3"><div class="stat-card"><small class="text-secondary">ŁĄCZNIE (USDT)</small><h4 class="text-profit">{{ total|round(2) }}</h4></div></div>
            <div class="col-md-3"><div class="stat-card"><small class="text-secondary">ZYSK/STRATA</small><h4>{{ (total - 1000)|round(2) }} USDT</h4></div></div>
        </div>

        <div class="row g-3 mb-4 text-center">
            <div class="col-4"><div class="p-2 border border-secondary rounded">🛒 Zakupy: <strong>{{ buy_count }}</strong></div></div>
            <div class="col-4"><div class="p-2 border border-secondary rounded">💰 Sprzedaże: <strong>{{ sell_count }}</strong></div></div>
            <div class="col-4"><div class="p-2 border border-secondary rounded">📉 Śr. Cena: <strong>{{ avg_price|round(2) }}</strong></div></div>
        </div>

        <h5>Ostatnie Operacje:</h5>
        <div class="mt-2">
            {% for t in history[::-1][:20] %}
            <div class="history-item action-{{ t.action }}">
                <div class="d-flex justify-content-between align-items-center">
                    <span class="badge {% if t.action=='KUPNO' %}bg-success{% elif t.action=='SPRZEDAŻ' %}bg-danger{% else %}bg-secondary{% endif %}">{{ t.action }}</span>
                    <span class="text-white-50" style="font-size: 0.8rem;">{{ t.time }}</span>
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

def run_analysis():
    try:
        ex = ccxt.mexc()
        ticker = ex.fetch_ticker("BTC/USDT")
        price = ticker['last']
        
        system_prompt = (
            "Jesteś agresywnym traderem. Zarządzasz kapitałem w pakietach po 20% (200 USDT). "
            "Gdy masz BTC, decyduj o SPRZEDAŻY (SELL) tylko gdy widzisz zysk lub ryzyko spadku. "
            "Odpowiadaj tylko JSON: {\"decision\": \"BUY/SELL/WAIT\", \"reason\": \"...\"}"
        )
        
        chat_completion = client.chat.completions.create(
            messages=[{"role": "system", "content": system_prompt}, {"role": "user", "content": f"Cena: {price}. Portfel: {state['usdt']}u, {state['btc']}b. Decyzja?"}],
            model="llama-3.1-8b-instant",
            response_format={"type": "json_object"}
        )
        
        res = json.loads(chat_completion.choices[0].message.content)
        decision = res.get('decision', 'WAIT').upper()
        reason = res.get('reason', '...')
        act_name = "CZEKANIE"

        if "BUY" in decision and state['usdt'] >= 200:
            # Obliczanie nowej średniej ceny zakupu
            new_btc = 200 / price
            total_btc = state['btc'] + new_btc
            state['avg_price'] = ((state['btc'] * state['avg_price']) + (new_btc * price)) / total_btc
            
            state['btc'] += new_btc
            state['usdt'] -= 200
            state['buy_count'] += 1
            act_name = "KUPNO"
        
        elif "SELL" in decision and state['btc'] > 0:
            state['usdt'] += state['btc'] * price
            state['btc'] = 0.0
            state['avg_price'] = 0.0
            state['sell_count'] += 1
            act_name = "SPRZEDAŻ"

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
