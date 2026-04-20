import requests
import ccxt
import json
import time
import os
import threading
from flask import Flask, render_template_string

app = Flask('')

# --- DANE PORTFELA ---
portfolio = {"usdt": 1000.0, "btc": 0.0, "total": 1000.0}
history = []

# --- DASHBOARD HTML ---
HTML_TEMPLATE = """
<!DOCTYPE html>
<html>
<head>
    <title>AI Trader Dashboard</title>
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css" rel="stylesheet">
    <style>
        body { background: #0b0e11; color: #eaecef; font-family: sans-serif; }
        .card { background: #1e2329; border: none; border-radius: 10px; margin-bottom: 20px; box-shadow: 0 4px 10px rgba(0,0,0,0.3); }
        .status-up { color: #02c076; font-size: 1.5rem; font-weight: bold; }
        .trade-row { border-bottom: 1px solid #2b3139; padding: 12px; }
        .badge-buy { background: #02c076; } .badge-sell { background: #cf304a; }
    </style>
</head>
<body>
    <div class="container mt-5">
        <h2 class="text-center mb-4">🚀 AI CRYPTO TRADER</h2>
        <div class="row text-center">
            <div class="col-md-4"><div class="card p-3"><h6>USDT</h6><div class="status-up">{{ portfolio.usdt|round(2) }}</div></div></div>
            <div class="col-md-4"><div class="card p-3"><h6>BTC</h6><div>{{ portfolio.btc|round(6) }}</div></div></div>
            <div class="col-md-4"><div class="card p-3"><h6>TOTAL</h6><div class="text-info font-weight-bold">{{ portfolio.total|round(2) }}</div></div></div>
        </div>
        <div class="card p-4">
            <h5>Historia Transakcji</h5>
            <div id="content">
                {% if not history %}<p class="text-muted">Inicjalizacja pierwszej analizy... Czekaj 60 sekund.</p>{% endif %}
                {% for t in history[::-1] %}
                <div class="trade-row">
                    <span class="badge {% if 'KUP' in t.action %}badge-buy{% elif 'SPRZEDAJ' in t.action %}badge-sell{% else %}bg-secondary{% endif %}">{{ t.action }}</span>
                    <span class="ms-2 small text-muted">{{ t.time }}</span>
                    <div class="mt-1"><b>Cena: {{ t.price }}</b> | {{ t.reason }}</div>
                </div>
                {% endfor %}
            </div>
        </div>
    </div>
    <script>setTimeout(function(){ location.reload(); }, 30000);</script>
</body>
</html>
"""

@app.route('/')
def home():
    return render_template_string(HTML_TEMPLATE, portfolio=portfolio, history=history)

# --- FUNKCJA BOTA ---
def run_bot_logic():
    print("🤖 WĄTEK BOTA: URUCHOMIONY")
    # Czekamy chwilę, żeby serwer Flask zdążył wstać
    time.sleep(10)
    
    CONFIG = {
        "gemini": os.getenv("GEMINI_KEY"),
        "token": os.getenv("TG_TOKEN"),
        "chat": os.getenv("TG_CHAT_ID")
    }

    while True:
        try:
            print("🔍 Analiza rynku w toku...")
            ex = ccxt.mexc()
            price = ex.fetch_ticker("BTC/USDT")['last']
            print(f"💰 Cena: {price}")

            url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent?key={CONFIG['gemini']}"
            prompt = f"BTC: {price} USDT. Portfel: {portfolio['usdt']} USDT, {portfolio['btc']} BTC. KUP, SPRZEDAJ czy CZEKAJ? Odpowiedz JSON: {{\"decyzja\":\"...\",\"powod\":\"...\"}}"
            
            res = requests.post(url, json={"contents": [{"parts": [{"text": prompt}]}]}, timeout=20).json()
            raw = res['candidates'][0]['content']['parts'][0]['text']
            # Wyciąganie JSON
            data = json.loads(raw.replace('```json', '').replace('```', '').strip())
            
            decyzja = data['decyzja'].upper()
            if "KUP" in decyzja and portfolio['usdt'] > 10:
                portfolio['btc'] = portfolio['usdt'] / price
                portfolio['usdt'] = 0.0
            elif "SPRZEDAJ" in decyzja and portfolio['btc'] > 0:
                portfolio['usdt'] = portfolio['btc'] * price
                portfolio['btc'] = 0.0

            portfolio['total'] = portfolio['usdt'] + (portfolio['btc'] * price)
            
            history.append({"time": time.strftime("%H:%M:%S"), "action": decyzja, "price": price, "reason": data['powod']})
            if len(history) > 10: history.pop(0)

            # Powiadomienie TG
            requests.post(f"https://api.telegram.org/bot{CONFIG['token']}/sendMessage", 
                         json={"chat_id": CONFIG['chat'], "text": f"🤖 AI: {decyzja}\nWartość: {portfolio['total']:.2f} USDT"})
            
            print(f"✅ Sukces. Następna analiza za 2 minuty.")
        except Exception as e:
            print(f"❌ Błąd pętli: {e}")

        time.sleep(120) # Zmniejszyłem do 2 minut, żeby szybciej widzieć efekty

if __name__ == "__main__":
    # KLUCZOWA ZMIANA: Serwer w głównym wątku, bot w tle
    print("🛠️ Startuję system...")
    bot_thread = threading.Thread(target=run_bot_logic, daemon=True)
    bot_thread.start()
    
    port = int(os.environ.get('PORT', 8080))
    app.run(host='0.0.0.0', port=port)
