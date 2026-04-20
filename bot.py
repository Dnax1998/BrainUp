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

# --- DESIGN DASHBOARDU ---
HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="pl">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>AI Trader Pro | Terminal</title>
    <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css" rel="stylesheet">
    <style>
        body { background-color: #0b0e11; color: #eaecef; font-family: sans-serif; padding: 20px; }
        .stat-card { background: #1e2329; border-radius: 12px; padding: 20px; border: 1px solid #2b3139; text-align: center; }
        .label { color: #848e9c; font-size: 0.75rem; text-transform: uppercase; }
        .value { font-size: 1.6rem; font-weight: bold; margin-top: 5px; color: #f0b90b; }
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
            <div class="col-4"><div class="stat-card"><div class="label">BTC</div><div class="value" style="color:white">{{ btc|round(6) }}</div></div></div>
            <div class="col-4"><div class="stat-card"><div class="label">SUMA</div><div class="value" style="color:#02c076">{{ total|round(2) }}</div></div></div>
        </div>
        <div class="history-card p-3">
            <h5>Dziennik Operacji:</h5>
            {% if not history %}<p class="text-muted small">Czekam na pierwszą analizę rynku...</p>{% endif %}
            {% for t in history[::-1] %}
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
    # WYMUSZONE LOGOWANIE NA SAMYM POCZĄTKU
    print(f"🔍 [DEBUG] Funkcja run_analysis URUCHOMIONA o {time.strftime('%H:%M:%S')}")
    
    try:
        # 1. Pobieranie ceny
        ex = ccxt.mexc()
        price = ex.fetch_ticker("BTC/USDT")['last']
        print(f"📈 [DEBUG] Cena pobrana: {price}")
        
        # 2. Zapytanie do AI
        key = os.getenv('GEMINI_KEY')
        if not key:
            print("❌ [DEBUG] BŁĄD: Brak klucza GEMINI_KEY!")
            return

        url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent?key={key}"
        prompt = f"BTC: {price}. Portfel: {state['usdt']} USDT, {state['btc']} BTC. KUP, SPRZEDAJ lub CZEKAJ? JSON: {{\"decyzja\":\"...\",\"powod\":\"...\"}}"
        
        res = requests.post(url, json={"contents": [{"parts": [{"text": prompt}]}]}, timeout=15)
        print(f"📡 [DEBUG] Status API Gemini: {res.status_code}")
        
        data_raw = res.json()
        if 'candidates' not in data_raw:
            print(f"❌ [DEBUG] Gemini błąd: {data_raw}")
            return

        raw_text = data_raw['candidates'][0]['content']['parts'][0]['text']
        clean_text = raw_text.replace('```json', '').replace('```', '').strip()
        data = json.loads(clean_text)
        
        dec = data['decyzja'].upper()
        print(f"✅ [DEBUG] AI wybrało: {dec}")

        # 3. Logika handlu
        if "KUP" in dec and state['usdt'] > 10:
            state['btc'], state['usdt'] = state['usdt'] / price, 0.0
        elif "SPRZEDAJ" in dec and state['btc'] > 0:
            state['usdt'], state['btc'] = state['btc'] * price, 0.0

        state['total'] = state['usdt'] + (state['btc'] * price)
        state['history'].append({
            "time": time.strftime("%H:%M:%S"), 
            "action": dec, 
            "price": price, 
            "reason": data.get('powod', 'Brak uzasadnienia')
        })
        
        if len(state['history']) > 15: state['history'].pop(0)

    except Exception as e:
        print(f"❌ [DEBUG] BŁĄD KRYTYCZNY: {str(e)}")

@app.route('/')
def home():
    print("🏠 [DEBUG] Ktoś wszedł na stronę główną!")
    run_analysis()
    return render_template_string(HTML_TEMPLATE, **state)

@app.route('/webhook', methods=['POST'])
def webhook():
    data = request.get_json()
    print("📩 [DEBUG] Odebrano Webhook z Telegrama")
    if data and "message" in data:
        chat_id = str(data["message"]["chat"]["id"])
        text = data["message"].get("text", "").lower()
        if chat_id == os.getenv("TG_CHAT_ID"):
            if text == "/saldo":
                msg = f"💰 Twoje saldo: {state['total']:.2f} USDT"
                requests.post(f"https://api.telegram.org/bot{os.getenv('TG_TOKEN')}/sendMessage", 
                             json={"chat_id": chat_id, "text": msg})
    return "OK", 200

def self_ping():
    time.sleep(15)
    base_url = "https://brainup-eh8e.onrender.com"
    requests.get(f"https://api.telegram.org/bot{os.getenv('TG_TOKEN')}/setWebhook?url={base_url}/webhook")
    while True:
        try:
            requests.get(base_url, timeout=10)
            print("🕒 [DEBUG] Self-ping wykonany")
        except: pass
        time.sleep(600)

if __name__ == "__main__":
    threading.Thread(target=self_ping, daemon=True).start()
    port = int(os.environ.get('PORT', 10000))
    app.run(host='0.0.0.0', port=port)
