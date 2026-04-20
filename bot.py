import requests
import ccxt
import json
import time
import os
from flask import Flask, render_template_string

app = Flask('')

# --- GLOBALNY STAN (Resetuje się przy restarcie serwera) ---
state = {
    "usdt": 1000.0,
    "btc": 0.0,
    "total": 1000.0,
    "last_run": 0,
    "history": []
}

# --- STYLIZOWANY DASHBOARD ---
HTML_TEMPLATE = """
<!DOCTYPE html>
<html>
<head>
    <title>AI Trader Pro</title>
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css" rel="stylesheet">
    <style>
        body { background: #0b0e11; color: #eaecef; font-family: sans-serif; padding: 20px; }
        .card { background: #1e2329; border: none; border-radius: 12px; margin-bottom: 20px; box-shadow: 0 4px 10px rgba(0,0,0,0.5); }
        .val { font-size: 1.5rem; font-weight: bold; color: #f0b90b; }
        .trade-row { border-bottom: 1px solid #2b3139; padding: 10px; font-size: 0.9rem; }
        .badge-buy { background: #02c076; } .badge-sell { background: #cf304a; }
    </style>
</head>
<body>
    <div class="container">
        <h3 class="text-center mb-4">🤖 AI CRYPTO TRADER</h3>
        <div class="row text-center">
            <div class="col-4"><div class="card p-3"><h6>USDT</h6><div class="val">{{ usdt|round(2) }}</div></div></div>
            <div class="col-4"><div class="card p-3"><h6>BTC</h6><div class="val" style="color:white">{{ btc|round(6) }}</div></div></div>
            <div class="col-4"><div class="card p-3"><h6>TOTAL</h6><div class="val" style="color:#02c076">{{ total|round(2) }}</div></div></div>
        </div>
        <div class="card p-4">
            <h5>Historia i Logi:</h5>
            {% if not hist %}<p class="text-muted">Czekam na pierwszą analizę... (Odśwież za 10s)</p>{% endif %}
            {% for t in hist[::-1] %}
            <div class="trade-row">
                <span class="badge {% if 'KUP' in t.action %}badge-buy{% elif 'SPRZEDAJ' in t.action %}badge-sell{% else %}bg-secondary{% endif %}">{{ t.action }}</span>
                <span class="ms-2 text-muted">{{ t.time }}</span> | <b>{{ t.price }} USDT</b>
                <div class="mt-1 text-secondary"><i>{{ t.reason }}</i></div>
            </div>
            {% endfor %}
        </div>
    </div>
    <script>setTimeout(() => location.reload(), 30000);</script>
</body>
</html>
"""

def execute_ai_logic():
    now = time.time()
    # Nie analizuj częściej niż co 2 minuty
    if now - state["last_run"] < 120:
        return

    print("🔍 URUCHAMIAM ANALIZĘ RYNKU...")
    state["last_run"] = now
    
    try:
        # 1. Pobierz cenę
        ex = ccxt.mexc()
        ticker = ex.fetch_ticker("BTC/USDT")
        price = ticker['last']
        
        # 2. Zapytaj Gemini
        url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent?key={os.getenv('GEMINI_KEY')}"
        prompt = f"BTC: {price} USDT. Portfel: {state['usdt']} USDT i {state['btc']} BTC. KUP, SPRZEDAJ czy CZEKAJ? Odpowiedz TYLKO JSON: {{\"decyzja\":\"KUP/SPRZEDAJ/CZEKAJ\", \"powod\":\"krótko po polsku\"}}"
        
        res = requests.post(url, json={"contents": [{"parts": [{"text": prompt}]}]}, timeout=15).json()
        raw_text = res['candidates'][0]['content']['parts'][0]['text']
        
        # Oczyszczanie JSON
        clean_json = raw_text.replace('```json', '').replace('```', '').strip()
        data = json.loads(clean_json)
        
        dec = data.get('decyzja', 'CZEKAJ').upper()
        powod = data.get('powod', 'Brak powodu')

        # 3. Logika handlu
        if "KUP" in dec and state['usdt'] > 10:
            state['btc'] = state['usdt'] / price
            state['usdt'] = 0.0
        elif "SPRZEDAJ" in dec and state['btc'] > 0:
            state['usdt'] = state['btc'] * price
            state['btc'] = 0.0

        state['total'] = state['usdt'] + (state['btc'] * price)
        state['history'].append({"time": time.strftime("%H:%M:%S"), "action": dec, "price": price, "reason": powod})
        if len(state['history']) > 10: state['history'].pop(0)

        # 4. Telegram
        tg_msg = f"🤖 *AI:* {dec}\n💰 *Wartość:* {state['total']:.2f} USDT\n📈 *Cena:* {price}\n📝 {powod}"
        requests.post(f"https://api.telegram.org/bot{os.getenv('TG_TOKEN')}/sendMessage", 
                     json={"chat_id": os.getenv("TG_CHAT_ID"), "text": tg_msg, "parse_mode": "Markdown"})
        
        print(f"✅ Analiza zakończona: {dec}")

    except Exception as e:
        print(f"❌ BŁĄD: {e}")

@app.route('/')
def home():
    execute_ai_logic()
    return render_template_string(HTML_TEMPLATE, usdt=state['usdt'], btc=state['btc'], total=state['total'], hist=state['history'])

if __name__ == "__main__":
    # Render używa portu 10000
    port = int(os.environ.get('PORT', 10000))
    app.run(host='0.0.0.0', port=port)
