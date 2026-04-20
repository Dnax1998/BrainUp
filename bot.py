import requests
import ccxt
import json
import time
import os
from flask import Flask, render_template_string

app = Flask('')

# --- STAN PORTFELA ---
state = {
    "usdt": 1000.0,
    "btc": 0.0,
    "total": 1000.0,
    "last_run": 0,
    "history": []
}

HTML_TEMPLATE = """
<!DOCTYPE html>
<html>
<head>
    <title>AI Trader Dashboard</title>
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css" rel="stylesheet">
    <style>
        body { background: #0b0e11; color: white; font-family: sans-serif; padding: 20px; }
        .card { background: #1e2329; border: none; border-radius: 10px; margin-bottom: 15px; }
        .status-up { color: #02c076; font-size: 1.8rem; font-weight: bold; }
        .trade-row { border-bottom: 1px solid #2b3139; padding: 10px; }
    </style>
</head>
<body>
    <div class="container">
        <h2 class="text-center mb-4">🚀 AI TRADER LIVE</h2>
        <div class="row text-center mb-4">
            <div class="col-4"><div class="card p-3"><h6>USDT</h6><div class="status-up">{{ usdt|round(2) }}</div></div></div>
            <div class="col-4"><div class="card p-3"><h6>BTC</h6><div>{{ btc|round(6) }}</div></div></div>
            <div class="col-4"><div class="card p-3"><h6>TOTAL</h6><div class="text-info">{{ total|round(2) }}</div></div></div>
        </div>
        <div class="card p-3">
            <h5>Historia (Ostatnie 5 min):</h5>
            {% if not hist %}<p class="text-muted">Analiza w toku... Odśwież stronę za 10 sekund.</p>{% endif %}
            {% for t in hist[::-1] %}
            <div class="trade-row">
                <span class="badge {% if 'KUP' in t.action %}bg-success{% elif 'SPRZEDAJ' in t.action %}bg-danger{% else %}bg-secondary{% endif %}">{{ t.action }}</span>
                <span class="ms-2 small">{{ t.time }}</span>
                <div class="mt-1"><b>Cena: {{ t.price }} USDT</b><br><small class="text-secondary">{{ t.reason }}</small></div>
            </div>
            {% endfor %}
        </div>
    </div>
    <script>setTimeout(() => location.reload(), 30000);</script>
</body>
</html>
"""

def run_analysis():
    now = time.time()
    # Wykonuj analizę nie częściej niż co 3 minuty
    if now - state["last_run"] < 180:
        return

    print("🔍 URUCHAMIAM ANALIZĘ RYNKU...")
    state["last_run"] = now
    
    try:
        ex = ccxt.mexc()
        price = ex.fetch_ticker("BTC/USDT")['last']
        
        url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent?key={os.getenv('GEMINI_KEY')}"
        prompt = f"BTC: {price}. Portfel: {state['usdt']} USDT, {state['btc']} BTC. KUP, SPRZEDAJ lub CZEKAJ. JSON: {{\"decyzja\":\"...\",\"powod\":\"...\"}}"
        
        res = requests.post(url, json={"contents": [{"parts": [{"text": prompt}]}]}, timeout=15).json()
        raw = res['candidates'][0]['content']['parts'][0]['text']
        data = json.loads(raw.replace('```json', '').replace('```', '').strip())
        
        dec = data['decyzja'].upper()
        if "KUP" in dec and state['usdt'] > 10:
            state['btc'], state['usdt'] = state['usdt'] / price, 0.0
        elif "SPRZEDAJ" in dec and state['btc'] > 0:
            state['usdt'], state['btc'] = state['btc'] * price, 0.0

        state['total'] = state['usdt'] + (state['btc'] * price)
        state['history'].append({"time": time.strftime("%H:%M:%S"), "action": dec, "price": price, "reason": data['powod']})
        
        if len(state['history']) > 5: state['history'].pop(0)

        # Telegram
        requests.post(f"https://api.telegram.org/bot{os.getenv('TG_TOKEN')}/sendMessage", 
                     json={"chat_id": os.getenv("TG_CHAT_ID"), "text": f"🤖 AI: {dec} | Total: {state['total']:.2f} USDT"})
        print(f"✅ ANALIZA OK: {dec}")

    except Exception as e:
        print(f"❌ BŁĄD: {e}")

@app.route('/')
def home():
    run_analysis() # Bot sprawdza rynek przy każdym wejściu na stronę
    return render_template_string(HTML_TEMPLATE, usdt=state['usdt'], btc=state['btc'], total=state['total'], hist=state['history'])

if __name__ == "__main__":
    port = int(os.environ.get('PORT', 10000))
    app.run(host='0.0.0.0', port=port)
