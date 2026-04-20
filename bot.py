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
    "history": []
}

HTML_TEMPLATE = """
<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <title>AI Trader Pro | Terminal</title>
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css" rel="stylesheet">
    <style>
        body { background: #0b0e11; color: white; padding: 20px; font-family: sans-serif; }
        .card-custom { background: #1e2329; border: 1px solid #2b3139; border-radius: 12px; padding: 15px; text-align: center; }
        .history-item { background: #1e2329; border-left: 4px solid #f0b90b; margin-top: 10px; padding: 10px; border-radius: 4px; border: 1px solid #2b3139; }
        .badge-buy { background: #02c076; color: white; }
        .badge-sell { background: #cf304a; color: white; }
        .badge-wait { background: #848e9c; color: white; }
        .badge-error { background: #5a0000; color: white; }
    </style>
</head>
<body>
    <div class="container">
        <h2 class="text-center mb-4" style="color: #f0b90b;">🤖 AI TRADER TERMINAL</h2>
        <div class="row g-2">
            <div class="col-4"><div class="card-custom"><small style="color:#848e9c">USDT</small><h4>{{ usdt|round(2) }}</h4></div></div>
            <div class="col-4"><div class="card-custom"><small style="color:#848e9c">BTC</small><h4>{{ btc|round(6) }}</h4></div></div>
            <div class="col-4"><div class="card-custom"><small style="color:#848e9c">SUMA</small><h4 style="color:#02c076">{{ total|round(2) }}</h4></div></div>
        </div>
        
        <div class="mt-4">
            <h5>Dziennik Operacji:</h5>
            {% if not history %}<div class="alert alert-info">Czekam na pierwszą analizę...</div>{% endif %}
            {% for t in history[::-1] %}
            <div class="history-item">
                <span class="badge {% if t.action == 'KUP' %}badge-buy{% elif t.action == 'SPRZEDAJ' %}badge-sell{% elif t.action == 'CZEKAJ' %}badge-wait{% else %}badge-error{% endif %}">
                    {{ t.action }}
                </span>
                <span class="ms-2 fw-bold">{{ t.price }} USDT</span>
                <div class="mt-1 small text-secondary">{{ t.time }} | {{ t.reason }}</div>
            </div>
            {% endfor %}
        </div>
    </div>
    <script>setTimeout(() => location.reload(), 20000);</script>
</body>
</html>
"""

def run_analysis():
    print("🚀 [LOG] Start analizy...")
    try:
        # 1. Cena z giełdy
        ex = ccxt.mexc()
        price = ex.fetch_ticker("BTC/USDT")['last']
        
        gemini_key = os.getenv('GEMINI_KEY')
        tg_token = os.getenv('TG_TOKEN')
        tg_chat = os.getenv('TG_CHAT_ID')

        # 2. ZMIANA: Używamy najbardziej stabilnego modelu 'gemini-pro' w wersji 'v1'
        url = f"https://generativelanguage.googleapis.com/v1/models/gemini-pro:generateContent?key={gemini_key}"
        
        payload = {
            "contents": [{
                "parts": [{
                    "text": f"Cena BTC: {price} USDT. Portfel: {state['usdt']} USDT i {state['btc']} BTC. Decyzja: KUP, SPRZEDAJ lub CZEKAJ. Odpowiedz tylko w formacie JSON: {{\"decyzja\":\"...\",\"powod\":\"...\"}}"
                }]
            }]
        }
        
        res = requests.post(url, json=payload, timeout=15)
        data = res.json()
        
        if 'candidates' in data:
            raw_text = data['candidates'][0]['content']['parts'][0]['text']
            # Usuwanie markdownów ```json ... ```
            clean_json = raw_text.replace('```json', '').replace('```', '').strip()
            ai_res = json.loads(clean_json)
            
            decyzja = ai_res['decyzja'].upper()
            powod = ai_res.get('powod', 'Analiza AI wykonana.')

            # Handel
            if "KUP" in decyzja and state['usdt'] > 10:
                state['btc'], state['usdt'] = state['usdt'] / price, 0.0
            elif "SPRZEDAJ" in decyzja and state['btc'] > 0.0001:
                state['usdt'], state['btc'] = state['btc'] * price, 0.0

            state['total'] = state['usdt'] + (state['btc'] * price)
            state['history'].append({"time": time.strftime("%H:%M:%S"), "action": decyzja, "price": price, "reason": powod})
            
            if tg_token and tg_chat:
                try:
                    msg = f"🤖 AI: {decyzja}\n💰 Saldo: {state['total']:.2f} USDT\n📈 Kurs: {price}\n💬 {powod}"
                    requests.post(f"https://api.telegram.org/bot{tg_token}/sendMessage", json={"chat_id": tg_chat, "text": msg})
                except: pass
        else:
            # Rejestrowanie błędu w tabeli zamiast crashu
            error_msg = data.get('error', {}).get('message', 'API nie zwróciło odpowiedzi (Candidates Empty)')
            state['history'].append({"time": time.strftime("%H:%M:%S"), "action": "BŁĄD AI", "price": price, "reason": error_msg})

    except Exception as e:
        print(f"❌ [CRASH] {str(e)}")
        state['history'].append({"time": time.strftime("%H:%M:%S"), "action": "CRASH", "price": 0, "reason": str(e)})

@app.route('/')
def home():
    run_analysis()
    return render_template_string(HTML_TEMPLATE, **state)

if __name__ == "__main__":
    port = int(os.environ.get('PORT', 10000))
    app.run(host='0.0.0.0', port=port)
