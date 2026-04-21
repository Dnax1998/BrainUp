import requests
import ccxt
import json
import time
import os
from flask import Flask, render_template_string

app = Flask('')

state = {"usdt": 1000.0, "btc": 0.0, "total": 1000.0, "history": []}

HTML_TEMPLATE = """
<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <title>AI Trader Terminal</title>
    <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css" rel="stylesheet">
    <style>
        body { background: #0b0e11; color: white; padding: 20px; font-family: sans-serif; }
        .stat-card { background: #1e2329; border: 1px solid #2b3139; border-radius: 12px; padding: 15px; text-align: center; }
        .history-item { background: #1e2329; border-left: 4px solid #f0b90b; margin-top: 10px; padding: 10px; border: 1px solid #2b3139; }
    </style>
</head>
<body>
    <div class="container">
        <h2 class="text-center mb-4" style="color: #f0b90b;">🤖 AI TRADER RESTART</h2>
        <div class="row g-2">
            <div class="col-4"><div class="stat-card"><small>USDT</small><h4>{{ usdt|round(2) }}</h4></div></div>
            <div class="col-4"><div class="stat-card"><small>BTC</small><h4>{{ btc|round(6) }}</h4></div></div>
            <div class="col-4"><div class="stat-card"><small>SUMA</small><h4 style="color:#02c076">{{ total|round(2) }}</h4></div></div>
        </div>
        <div class="mt-4">
            <h5>Dziennik Operacji:</h5>
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
        key = os.getenv('GEMINI_KEY')
        
        # --- ZMIANA: Model gemini-1.0-pro (największa kompatybilność) ---
        url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-1.0-pro:generateContent?key={key}"
        
        payload = {
            "contents": [{"parts": [{"text": f"BTC: {price}. Portfel: {state['usdt']} USDT, {state['btc']} BTC. KUP, SPRZEDAJ czy CZEKAJ? Odpisz TYLKO JSON: {{\"decyzja\":\"...\",\"powod\":\"...\"}}"}]}]
        }
        
        res = requests.post(url, json=payload, timeout=15)
        data = res.json()
        
        if 'candidates' in data:
            txt = data['candidates'][0]['content']['parts'][0]['text']
            clean = txt.replace('```json', '').replace('```', '').strip()
            ai = json.loads(clean)
            
            dec = ai['decyzja'].upper()
            if "KUP" in dec and state['usdt'] > 10:
                state['btc'], state['usdt'] = state['usdt'] / price, 0.0
            elif "SPRZEDAJ" in dec and state['btc'] > 0.0001:
                state['usdt'], state['btc'] = state['btc'] * price, 0.0

            state['total'] = state['usdt'] + (state['btc'] * price)
            state['history'].append({"time": time.strftime("%H:%M:%S"), "action": dec, "price": price, "reason": ai['powod']})
            
            tk, cid = os.getenv('TG_TOKEN'), os.getenv('TG_CHAT_ID')
            if tk and cid:
                requests.post(f"https://api.telegram.org/bot{tk}/sendMessage", json={"chat_id": cid, "text": f"🤖 AI: {dec} | {state['total']:.2f} USDT"})
        else:
            # Rejestracja błędu w tabeli
            msg = data.get('error', {}).get('message', 'Nadal brak dostępu do modeli.')
            state['history'].append({"time": time.strftime("%H:%M:%S"), "action": "BŁĄD", "price": price, "reason": msg})

    except Exception as e:
        state['history'].append({"time": time.strftime("%H:%M:%S"), "action": "CRASH", "price": 0, "reason": str(e)})

@app.route('/')
def home():
    run_analysis()
    return render_template_string(HTML_TEMPLATE, **state)

if __name__ == "__main__":
    port = int(os.environ.get('PORT', 10000))
    app.run(host='0.0.0.0', port=port)
