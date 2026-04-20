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

# --- NOWOCZESNY DESIGN (DARK MODE PRO) ---
HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="pl">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>AI Trader Pro | Terminal</title>
    <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css" rel="stylesheet">
    <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/bootstrap-icons@1.10.0/font/bootstrap-icons.css">
    <style>
        :root { --bg: #0b0e11; --card: #1e2329; --text: #eaecef; --accent: #f0b90b; --green: #02c076; --red: #cf304a; }
        body { background-color: var(--bg); color: var(--text); font-family: 'Segoe UI', Tahoma, sans-serif; }
        .navbar { background-color: var(--card); border-bottom: 1px solid #333; }
        .stat-card { background: var(--card); border-radius: 12px; padding: 20px; border: 1px solid #2b3139; transition: 0.3s; }
        .stat-card:hover { border-color: var(--accent); }
        .label { color: #848e9c; font-size: 0.85rem; text-transform: uppercase; letter-spacing: 1px; }
        .value { font-size: 1.6rem; font-weight: 700; margin-top: 5px; }
        .btc-val { color: var(--accent); }
        .total-val { color: var(--green); }
        .history-card { background: var(--card); border-radius: 12px; border: 1px solid #2b3139; overflow: hidden; }
        .history-header { background: rgba(255,255,255,0.03); padding: 15px 20px; border-bottom: 1px solid #2b3139; }
        .trade-item { padding: 15px 20px; border-bottom: 1px solid #2b3139; animation: fadeIn 0.5s ease-in; }
        .trade-item:last-child { border-bottom: none; }
        .badge-buy { background-color: var(--green); color: white; }
        .badge-sell { background-color: var(--red); color: white; }
        .badge-wait { background-color: #474d57; color: white; }
        @keyframes fadeIn { from { opacity: 0; transform: translateY(10px); } to { opacity: 1; transform: translateY(0); } }
    </style>
</head>
<body>
    <nav class="navbar mb-4">
        <div class="container">
            <span class="navbar-brand mb-0 h1 text-white">
                <i class="bi bi-robot me-2"></i>AI TRADER <span style="color: var(--accent)">PRO</span>
            </span>
            <span class="badge bg-outline-secondary border text-muted">LIVE FEED</span>
        </div>
    </nav>

    <div class="container">
        <div class="row g-3 mb-4">
            <div class="col-md-4">
                <div class="stat-card">
                    <div class="label"><i class="bi bi-wallet2 me-2"></i>Saldo USDT</div>
                    <div class="value">{{ usdt|round(2) }}</div>
                </div>
            </div>
            <div class="col-md-4">
                <div class="stat-card">
                    <div class="label"><i class="bi bi-currency-bitcoin me-2"></i>Posiadane BTC</div>
                    <div class="value btc-val">{{ btc|round(6) }}</div>
                </div>
            </div>
            <div class="col-md-4">
                <div class="stat-card">
                    <div class="label"><i class="bi bi-graph-up-arrow me-2"></i>Łączna Wartość</div>
                    <div class="value total-val">{{ total|round(2) }} USDT</div>
                </div>
            </div>
        </div>

        <div class="history-card">
            <div class="history-header d-flex justify-content-between align-items-center">
                <h5 class="mb-0">Dziennik Operacji AI</h5>
                <small class="text-muted">Auto-odświeżanie: 30s</small>
            </div>
            <div class="history-list">
                {% if not hist %}
                <div class="p-5 text-center text-muted">
                    <div class="spinner-border text-warning mb-3" role="status"></div>
                    <p>Inicjalizacja pierwszej analizy... Proszę czekać.</p>
                </div>
                {% endif %}
                {% for t in hist[::-1] %}
                <div class="trade-item">
                    <div class="d-flex justify-content-between align-items-start">
                        <div>
                            <span class="badge {% if 'KUP' in t.action %}badge-buy{% elif 'SPRZEDAJ' in t.action %}badge-sell{% else %}badge-wait{% endif %} px-3 py-2">
                                {{ t.action }}
                            </span>
                            <span class="ms-3 fw-bold">{{ t.price }} USDT</span>
                        </div>
                        <small class="text-muted">{{ t.time }}</small>
                    </div>
                    <div class="mt-2 text-secondary italic" style="font-size: 0.9rem;">
                        <i class="bi bi-chat-left-dots me-2"></i>{{ t.reason }}
                    </div>
                </div>
                {% endfor %}
            </div>
        </div>
    </div>

    <script>setTimeout(() => location.reload(), 30000);</script>
</body>
</html>
"""

def run_analysis():
    now = time.time()
    # Analiza max co 3 minuty
    if now - state["last_run"] < 180:
        return

    state["last_run"] = now
    try:
        ex = ccxt.mexc()
        price = ex.fetch_ticker("BTC/USDT")['last']
        
        # Zapytanie do Gemini API
        url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent?key={os.getenv('GEMINI_KEY')}"
        prompt = f"BTC: {price}. Portfel: {state['usdt']} USDT, {state['btc']} BTC. KUP, SPRZEDAJ lub CZEKAJ. JSON: {{\"decyzja\":\"...\",\"powod\":\"...\"}}"
        
        res = requests.post(url, json={"contents": [{"parts": [{"text": prompt}]}]}, timeout=15).json()
        raw = res['candidates'][0]['content']['parts'][0]['text']
        data = json.loads(raw.replace('```json', '').replace('```', '').strip())
        
        dec = data['decyzja'].upper()
        # Logika handlu wirtualnego
        if "KUP" in dec and state['usdt'] > 10:
            state['btc'], state['usdt'] = state['usdt'] / price, 0.0
        elif "SPRZEDAJ" in dec and state['btc'] > 0:
            state['usdt'], state['btc'] = state['btc'] * price, 0.0

        state['total'] = state['usdt'] + (state['btc'] * price)
        state['history'].append({"time": time.strftime("%H:%M:%S"), "action": dec, "price": price, "reason": data['powod']})
        
        if len(state['history']) > 8: state['history'].pop(0)

        # Telegram
        requests.post(f"https://api.telegram.org/bot{os.getenv('TG_TOKEN')}/sendMessage", 
                     json={"chat_id": os.getenv("TG_CHAT_ID"), "text": f"🤖 AI Decyzja: {dec}\n💰 Wartość portfela: {state['total']:.2f} USDT"})
    except Exception as e:
        print(f"Błąd analizy: {e}")

@app.route('/')
def home():
    run_analysis() # Analiza przy każdym odświeżeniu
    return render_template_string(HTML_TEMPLATE, usdt=state['usdt'], btc=state['btc'], total=state['total'], hist=state['history'])

if __name__ == "__main__":
    port = int(os.environ.get('PORT', 10000)) # Render port 10000
    app.run(host='0.0.0.0', port=port)
