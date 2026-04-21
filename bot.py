import os
import time
import json
import ccxt
import google.generativeai as genai
from flask import Flask, render_template_string

app = Flask('')

state = {"usdt": 1000.0, "btc": 0.0, "total": 1000.0, "history": []}

# Konfiguracja SDK Google
genai.configure(api_key=os.getenv('GEMINI_KEY'))

HTML_TEMPLATE = """
<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <title>AI Trader Pro | SDK Mode</title>
    <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css" rel="stylesheet">
    <style>
        body { background: #0b0e11; color: white; padding: 20px; font-family: sans-serif; }
        .stat-card { background: #1e2329; border: 1px solid #2b3139; border-radius: 12px; padding: 15px; text-align: center; }
        .history-item { background: #1e2329; border-left: 4px solid #f0b90b; margin-top: 10px; padding: 10px; border: 1px solid #2b3139; }
    </style>
</head>
<body>
    <div class="container">
        <h2 class="text-center mb-4" style="color: #f0b90b;">🤖 AI TRADER SDK</h2>
        <div class="row g-2">
            <div class="col-4"><div class="stat-card"><small>USDT</small><h4>{{ usdt|round(2) }}</h4></div></div>
            <div class="col-4"><div class="stat-card"><small>BTC</small><h4>{{ btc|round(6) }}</h4></div></div>
            <div class="col-4"><div class="stat-card"><small>SUMA</small><h4 style="color:#02c076">{{ total|round(2) }}</h4></div></div>
        </div>
        <div class="mt-4">
            <h5>Dziennik:</h5>
            {% for t in history[::-1] %}
            <div class="history-item">
                <span class="badge bg-primary">{{ t.action }}</span> <strong>{{ t.price }} USDT</strong><br>
                <small class="text-secondary">{{ t.time }} | {{ t.reason }}</small>
            </div>
            {% endfor %}
        </div>
    </div>
    <script>setTimeout(() => location.reload(), 30000);</script>
</body>
</html>
"""

def run_analysis():
    try:
        ex = ccxt.mexc()
        price = ex.fetch_ticker("BTC/USDT")['last']
        
        # Próba użycia modelu przez oficjalne SDK
        model = genai.GenerativeModel('gemini-1.5-flash')
        prompt = f"BTC price: {price}. Wallet: {state['usdt']} USDT, {state['btc']} BTC. Act: BUY, SELL, WAIT. Reply ONLY JSON: {{\"decision\":\"...\",\"reason\":\"...\"}}"
        
        response = model.generate_content(prompt)
        
        # Wyciąganie tekstu z odpowiedzi SDK
        txt = response.text
        clean = txt.replace('```json', '').replace('```', '').strip()
        ai = json.loads(clean)
        
        dec = ai['decision'].upper()
        if "BUY" in dec and state['usdt'] > 10:
            state['btc'], state['usdt'] = state['usdt'] / price, 0.0
        elif "SELL" in dec and state['btc'] > 0.0001:
            state['usdt'], state['btc'] = state['btc'] * price, 0.0

        state['total'] = state['usdt'] + (state['btc'] * price)
        state['history'].append({"time": time.strftime("%H:%M:%S"), "action": dec, "price": price, "reason": ai['reason']})

    except Exception as e:
        # Wyświetlamy konkretny błąd z SDK, żeby wiedzieć czy to region, czy brak API
        state['history'].append({"time": time.strftime("%H:%M:%S"), "action": "BŁĄD SDK", "price": 0, "reason": str(e)})

@app.route('/')
def home():
    run_analysis()
    return render_template_string(HTML_TEMPLATE, **state)

if __name__ == "__main__":
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 10000)))
