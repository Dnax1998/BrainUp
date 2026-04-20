import requests
import ccxt
import json
import time
import os
import threading
from flask import Flask, render_template_string

# --- KONFIGURACJA ---
CONFIG = {
    "gemini": os.getenv("GEMINI_KEY"),
    "token": os.getenv("TG_TOKEN"),
    "chat": os.getenv("TG_CHAT_ID")
}

app = Flask('')
portfolio = {"usdt": 1000.0, "btc": 0.0, "total": 1000.0}
history = []

@app.route('/')
def home():
    # Prosta strona statusu
    return render_template_string("""
    <html><body style="background:#0b0e11;color:white;font-family:sans-serif;padding:20px;">
        <h2>🚀 AI Trading Bot Status</h2>
        <div style="background:#1e2329;padding:15px;border-radius:10px;">
            <p>TOTAL VALUE: <b style="color:#02c076;">{{total}} USDT</b></p>
            <p>USDT: {{usdt}} | BTC: {{btc}}</p>
        </div>
        <hr>
        <h3>Ostatnie akcje:</h3>
        {% for t in hist[::-1] %}
            <p style="border-bottom:1px solid #2b3139;padding:5px;">
                [{{t.time}}] <b>{{t.action}}</b> - {{t.price}} USDT<br>
                <small style="color:#848e9c;">{{t.reason}}</small>
            </p>
        {% endfor %}
        <script>setTimeout(() => location.reload(), 30000);</script>
    </body></html>
    """, total=round(portfolio['total'], 2), usdt=round(portfolio['usdt'], 2), 
       btc=round(portfolio['btc'], 6), hist=history)

def bot_logic():
    print("🤖 STARTUJĘ PĘTLĘ BOTA...")
    while True:
        try:
            print("🔍 Pobieram cenę i analizuję...")
            ex = ccxt.mexc()
            price = ex.fetch_ticker("BTC/USDT")['last']
            
            url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent?key={CONFIG['gemini']}"
            prompt = f"BTC: {price}. Portfel: {portfolio['usdt']} USDT, {portfolio['btc']} BTC. KUP, SPRZEDAJ czy CZEKAJ? Odpowiedz tylko JSON: {{\"decyzja\":\"...\",\"powod\":\"...\"}}"
            
            res = requests.post(url, json={"contents": [{"parts": [{"text": prompt}]}]}, timeout=15).json()
            raw_content = res['candidates'][0]['content']['parts'][0]['text']
            
            # Czyszczenie odpowiedzi AI
            clean_json = raw_content.replace('```json', '').replace('```', '').strip()
            data = json.loads(clean_json)
            
            dec = data['decyzja'].upper()
            if "KUP" in dec and portfolio['usdt'] > 10:
                portfolio['btc'], portfolio['usdt'] = portfolio['usdt'] / price, 0.0
            elif "SPRZEDAJ" in dec and portfolio['btc'] > 0:
                portfolio['usdt'], portfolio['btc'] = portfolio['btc'] * price, 0.0

            portfolio['total'] = portfolio['usdt'] + (portfolio['btc'] * price)
            history.append({"time": time.strftime("%H:%M:%S"), "action": dec, "price": price, "reason": data['powod']})
            if len(history) > 10: history.pop(0)

            # Wysyłka na Telegram
            tg_url = f"https://api.telegram.org/bot{CONFIG['token']}/sendMessage"
            requests.post(tg_url, json={"chat_id": CONFIG['chat'], "text": f"🤖 AI: {dec}\nWartość: {portfolio['total']:.2f} USDT"})
            print(f"✅ Cykl zakończony. Cena: {price}")
            
        except Exception as e:
            print(f"❌ BŁĄD BOTA: {e}")
        
        # Czekaj 120 sekund przed kolejną próbą
        time.sleep(120)

if __name__ == "__main__":
    # Uruchomienie bota w osobnym wątku przed startem serwera
    t = threading.Thread(target=bot_logic)
    t.daemon = True
    t.start()
    
    # Render wymaga bindowania do portu 10000
    port = int(os.environ.get('PORT', 10000))
    app.run(host='0.0.0.0', port=port)
