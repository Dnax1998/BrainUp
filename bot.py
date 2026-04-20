import requests
import ccxt
import json
import time
import os
import threading
from flask import Flask, render_template_string, request

app = Flask('')

# --- STAN PORTFELA ---
state = {
    "usdt": 1000.0,
    "btc": 0.0,
    "total": 1000.0,
    "last_run": 0,
    "history": []
}

# --- ESTETYCZNY DARK DASHBOARD ---
HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="pl">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>AI Trader Pro | Terminal</title>
    <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css" rel="stylesheet">
    <style>
        :root { --bg: #0b0e11; --card: #1e2329; --accent: #f0b90b; --text: #eaecef; }
        body { background-color: var(--bg); color: var(--text); font-family: 'Segoe UI', sans-serif; padding: 20px; }
        .stat-card { background: var(--card); border-radius: 12px; padding: 20px; border: 1px solid #2b3139; text-align: center; }
        .label { color: #848e9c; font-size: 0.75rem; text-transform: uppercase; letter-spacing: 1px; }
        .value { font-size: 1.6rem; font-weight: bold; margin-top: 5px; }
        .history-card { background: var(--card); border-radius: 12px; border: 1px solid #2b3139; margin-top: 20px; overflow: hidden; }
        .trade-item { padding: 15px; border-bottom: 1px solid #2b3139; transition: 0.3s; }
        .trade-item:hover { background: rgba(255,255,255,0.02); }
        .badge-buy { background-color: #02c076; color: white; }
        .badge-sell { background-color: #cf304a; color: white; }
        .badge-wait { background-color: #474d57; color: white; }
    </style>
</head>
<body>
    <div class="container">
        <h2 class="text-center mb-4" style="color: var(--accent);">🤖 AI TRADER <span style="color:white">PRO</span></h2>
        
        <div class="row g-3">
            <div class="col-4"><div class="stat-card"><div class="label">Dostępne USDT</div><div class="value">{{ usdt|round(2) }}</div></div></div>
            <div class="col-4"><div class="stat-card"><div class="label">Posiadane BTC</div><div class="value" style="color:var(--accent)">{{ btc|round(6) }}</div></div></div>
            <div class="col-4"><div class="stat-card"><div class="label">Łączna Wartość</div><div class="value" style="color:#02c076">{{ total|round(2) }}</div></div></div>
        </div>

        <div class="history-card">
            <div class="p-3 border-bottom border-secondary">
                <h5 class="mb-0">Dziennik Operacji AI</h5>
            </div>
            {% if not history %}
            <div class="p-4 text-center text-muted">Inicjalizacja... Pierwsza analiza za chwilę.</div>
            {% endif %}
            {% for t in history[::-1] %}
            <div class="trade-item">
                <div class="d-flex justify-content-between">
                    <span class="badge {% if 'KUP' in t.action %}badge-buy{% elif 'SPRZEDAJ' in t.action %}badge-sell{% else %}badge-wait{% endif %} px-3 py-2">
                        {{ t.action }}
                    </span>
                    <span class="fw-bold">{{ t.price }} USDT</span>
                </div>
                <div class="mt-2 small text-secondary">
                    <span class="text-white-50">{{ t.time }}</span> | {{ t.reason }}
                </div>
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
    if now - state["last_run"] < 120: return 
    
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
        
        if len(state['history']) > 15: state['history'].pop(0)

        # Powiadomienie Telegram
        msg = f"🤖 AI: {dec}\n💰 Portfel: {state['total']:.2f} USDT\n📈 Kurs: {price}\n💬 {data['powod']}"
        requests.post(f"https://api.telegram.org/bot{os.getenv('TG_TOKEN')}/sendMessage", 
                     json={"chat_id": os.getenv("TG_CHAT_ID"), "text": msg})
    except Exception as e:
        print(f"Błąd analizy: {e}")

@app.route('/')
def home():
    run_analysis()
    return render_template_string(HTML_TEMPLATE, **state)

@app.route('/webhook', methods=['POST'])
def webhook():
    data = request.get_json()
    if "message" in data:
        chat_id = str(data["message"]["chat"]["id"])
        text = data["message"].get("text", "").lower()
        
        if chat_id == os.getenv("TG_CHAT_ID"):
            reply = ""
            if text == "/saldo":
                reply = f"💰 Suma: {state['total']:.2f} USDT\n💵 Gotówka: {state['usdt']:.2f}\n₿ BTC: {state['btc']:.6f}"
            elif text == "/trade":
                state['last_run'] = 0
                run_analysis()
                reply = "⚙️ Wymuszono nową analizę..."
            elif text == "/start":
                reply = "🤖 Bot aktywny!\n/saldo - stan konta\n/trade - wymuś analizę"

            if reply:
                requests.post(f"https://api.telegram.org/bot{os.getenv('TG_TOKEN')}/sendMessage", 
                             json={"chat_id": chat_id, "text": reply})
    return "OK", 200

def self_ping():
    time.sleep(20)
    base_url = "https://brainup-eh8e.onrender.com"
    # Ustawienie Webhooka raz przy starcie
    requests.get(f"https://api.telegram.org/bot{os.getenv('TG_TOKEN')}/setWebhook?url={base_url}/webhook")
    while True:
        try:
            requests.get(base_url, timeout=10)
            print("🕒 Self-ping wysłany.")
        except: pass
        time.sleep(600)

if __name__ == "__main__":
    threading.Thread(target=self_ping, daemon=True).start()
    port = int(os.environ.get('PORT', 10000))
    app.run(host='0.0.0.0', port=port)
