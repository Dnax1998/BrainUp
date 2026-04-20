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

# --- TEMPLATKA DASHBOARDU ---
HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="pl">
<head>
    <meta charset="UTF-8">
    <title>AI Trader Pro | Terminal</title>
    <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css" rel="stylesheet">
    <style>
        body { background: #0b0e11; color: white; padding: 20px; font-family: sans-serif; }
        .stat-card { background: #1e2329; padding: 20px; border-radius: 12px; border: 1px solid #2b3139; text-align: center; }
        .history-box { background: #1e2329; border-radius: 12px; margin-top: 20px; padding: 15px; border: 1px solid #2b3139; }
        .trade-row { border-bottom: 1px solid #2b3139; padding: 10px 0; }
    </style>
</head>
<body>
    <div class="container">
        <h2 class="text-center mb-4" style="color: #f0b90b;">🤖 AI TRADER TERMINAL</h2>
        <div class="row g-3">
            <div class="col-4"><div class="stat-card"><small style="color:#848e9c">USDT</small><h3>{{ usdt|round(2) }}</h3></div></div>
            <div class="col-4"><div class="stat-card"><small style="color:#848e9c">BTC</small><h3>{{ btc|round(6) }}</h3></div></div>
            <div class="col-4"><div class="stat-card"><small style="color:#848e9c">SUMA USDT</small><h3 style="color:#02c076">{{ total|round(2) }}</h3></div></div>
        </div>
        <div class="history-box">
            <h5>Ostatnie Akcje AI:</h5>
            {% if not history %}<p class="text-muted">Czekam na pierwszą analizę...</p>{% endif %}
            {% for t in history[::-1] %}
            <div class="trade-row">
                <span class="badge {% if 'KUP' in t.action %}bg-success{% elif 'SPRZEDAJ' in t.action %}bg-danger{% else %}bg-secondary{% endif %}">{{ t.action }}</span>
                <span class="ms-2">Cena: {{ t.price }} USDT</span>
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
    # WYMUSZONE LOGI DIAGNOSTYCZNE
    print(f"🚀 [CRITICAL] START ANALIZY: {time.strftime('%H:%M:%S')}")
    try:
        # 1. Kurs z giełdy
        ex = ccxt.mexc()
        price = ex.fetch_ticker("BTC/USDT")['last']
        print(f"📈 [INFO] Aktualna cena BTC: {price}")

        # 2. Konsultacja z Gemini AI
        key = os.getenv('GEMINI_KEY')
        if not key:
            print("❌ [ERROR] Brak GEMINI_KEY w Environment Variables!")
            return

        url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent?key={key}"
        prompt = f"BTC: {price}. Wallet: {state['usdt']} USDT, {state['btc']} BTC. Decision (KUP/SPRZEDAJ/CZEKAJ)? JSON: {{\"decyzja\":\"...\",\"powod\":\"...\"}}"
        
        res = requests.post(url, json={"contents": [{"parts": [{"text": prompt}]}]}, timeout=15)
        print(f"📡 [AI] Status API: {res.status_code}")
        
        data = res.json()
        if 'candidates' in data:
            raw_text = data['candidates'][0]['content']['parts'][0]['text']
            parsed = json.loads(raw_text.replace('```json', '').replace('```', '').strip())
            
            dec = parsed['decyzja'].upper()
            print(f"✅ [DECISION] AI wybrało: {dec}")

            # Handel (Wirtualny)
            if "KUP" in dec and state['usdt'] > 10:
                state['btc'], state['usdt'] = state['usdt'] / price, 0.0
            elif "SPRZEDAJ" in dec and state['btc'] > 0:
                state['usdt'], state['btc'] = state['btc'] * price, 0.0

            state['total'] = state['usdt'] + (state['btc'] * price)
            state['history'].append({
                "time": time.strftime("%H:%M:%S"), 
                "action": dec, 
                "price": price, 
                "reason": parsed.get('powod', 'Brak danych')
            })
            
            # Raport Telegram
            tg_token = os.getenv('TG_TOKEN')
            tg_chat = os.getenv('TG_CHAT_ID')
            if tg_token and tg_chat:
                msg = f"🤖 AI Decyzja: {dec}\n💰 Portfel: {state['total']:.2f} USDT\n💬 {parsed.get('powod', '')}"
                requests.post(f"https://api.telegram.org/bot{tg_token}/sendMessage", json={"chat_id": tg_chat, "text": msg})
        else:
            print(f"❌ [AI ERROR] Brak odpowiedzi candidates: {data}")

    except Exception as e:
        print(f"❌ [CRASH] Coś poszło nie tak: {str(e)}")

@app.route('/')
def home():
    print("🌐 [VISIT] Ktoś wszedł na dashboard!")
    run_analysis()
    return render_template_string(HTML_TEMPLATE, **state)

@app.route('/webhook', methods=['POST'])
def webhook():
    print("📩 [TG] Odebrano sygnał z Telegrama")
    return "OK", 200

def self_ping():
    time.sleep(20)
    # Rejestracja Webhooka
    base_url = "https://brainup-eh8e.onrender.com"
    requests.get(f"https://api.telegram.org/bot{os.getenv('TG_TOKEN')}/setWebhook?url={base_url}/webhook")
    
    while True:
        try:
            requests.get(base_url, timeout=10)
            print("🕒 [PING] Serwer podtrzymany.")
        except: pass
        time.sleep(600)

if __name__ == "__main__":
    threading.Thread(target=self_ping, daemon=True).start()
    port = int(os.environ.get('PORT', 10000))
    app.run(host='0.0.0.0', port=port)
