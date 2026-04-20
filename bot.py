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

# --- NOWOCZESNY DESIGN ---
HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="pl">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>AI Trader Pro</title>
    <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css" rel="stylesheet">
    <style>
        body { background-color: #0b0e11; color: #eaecef; font-family: sans-serif; padding: 20px; }
        .stat-card { background: #1e2329; border-radius: 12px; padding: 20px; border: 1px solid #2b3139; text-align: center; }
        .label { color: #848e9c; font-size: 0.8rem; text-transform: uppercase; }
        .value { font-size: 1.5rem; font-weight: bold; margin-top: 5px; }
        .history-card { background: #1e2329; border-radius: 12px; border: 1px solid #2b3139; margin-top: 20px; }
        .trade-item { padding: 15px; border-bottom: 1px solid #2b3139; }
        .badge-buy { background-color: #02c076; }
        .badge-sell { background-color: #cf304a; }
    </style>
</head>
<body>
    <div class="container">
        <h2 class="text-center mb-4" style="color: #f0b90b;">🤖 AI TRADER PRO</h2>
        <div class="row g-3">
            <div class="col-4"><div class="stat-card"><div class="label">USDT</div><div class="value">{{ usdt|round(2) }}</div></div></div>
            <div class="col-4"><div class="stat-card"><div class="label">BTC</div><div class="value">{{ btc|round(6) }}</div></div></div>
            <div class="col-4"><div class="stat-card"><div class="label">SUMA</div><div class="value" style="color:#02c076">{{ total|round(2) }}</div></div></div>
        </div>
        <div class="history-card p-3">
            <h5>Ostatnie Akcje:</h5>
            {% if not hist %}<p class="text-muted">Inicjalizacja... Odśwież za 15 sekund.</p>{% endif %}
            {% for t in hist[::-1] %}
            <div class="trade-item">
                <span class="badge {% if 'KUP' in t.action %}badge-buy{% elif 'SPRZEDAJ' in t.action %}badge-sell{% else %}bg-secondary{% endif %}">{{ t.action }}</span>
                <span class="ms-2 fw-bold">{{ t.price }} USDT</span>
                <div class="mt-1 small text-secondary">{{ t.time }} | {{ t.reason }}</div>
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
    if now - state["last_run"] < 120: return # Max co 2 minuty

    print("🔍 URUCHAMIAM ANALIZĘ RYNKU...")
    state["last_run"] = now
    try:
        ex = ccxt.mexc()
        price = ex.fetch_ticker("BTC/USDT")['last']
        
        url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent?key={os.getenv('GEMINI_KEY')}"
        prompt = f"BTC: {price}. Portfel: {state['usdt']} USDT, {state['btc']} BTC. KUP, SPRZEDAJ lub CZEKAJ? JSON: {{\"decyzja\":\"...\",\"powod\":\"...\"}}"
        
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
        if len(state['history']) > 10: state['history'].pop(0)

        # Telegram
        requests.post(f"https://api.telegram.org/bot{os.getenv('TG_TOKEN')}/sendMessage", 
                     json={"chat_id": os.getenv("TG_CHAT_ID"), "text": f"🤖 AI: {dec} | Total: {state['total']:.2f} USDT"})
        print(f"✅ SUKCES: {dec}")
    except Exception as e:
        print(f"❌ BŁĄD: {e}")

@app.route('/')
def home():
    run_analysis()
    return render_template_string(HTML_TEMPLATE, usdt=state['usdt'], btc=state['btc'], total=state['total'], hist=state['history'])

if __name__ == "__main__":
    # Render port binding
    port = int(os.environ.get('PORT', 10000))
    app.run(host='0.0.0.0', port=port)
