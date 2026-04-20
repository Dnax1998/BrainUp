import requests
import ccxt
import json
import time
import os
import threading
from flask import Flask, render_template_string

# Konfiguracja
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
    return render_template_string("""
    <html><body style="background:#0b0e11;color:white;font-family:sans-serif;padding:20px;">
        <h2>🚀 AI Dashboard</h2>
        <p>TOTAL: <b>{{total}} USDT</b> | USDT: {{usdt}} | BTC: {{btc}}</p>
        <hr>
        {% for t in hist[::-1] %}
            <p>[{{t.time}}] <b>{{t.action}}</b> - {{t.price}} USDT<br><small>{{t.reason}}</small></p>
        {% endfor %}
        <script>setTimeout(() => location.reload(), 30000);</script>
    </body></html>
    """, total=round(portfolio['total'], 2), usdt=round(portfolio['usdt'], 2), 
       btc=round(portfolio['btc'], 6), hist=history)

def bot_cycle():
    while True:
        try:
            print("🔍 START ANALIZY...")
            ex = ccxt.mexc()
            price = ex.fetch_ticker("BTC/USDT")['last']
            
            url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent?key={CONFIG['gemini']}"
            prompt = f"BTC: {price}. Portfel: {portfolio['usdt']} USDT, {portfolio['btc']} BTC. KUP, SPRZEDAJ czy CZEKAJ? JSON: {{\"decyzja\":\"...\",\"powod\":\"...\"}}"
            
            res = requests.post(url, json={"contents": [{"parts": [{"text": prompt}]}]}, timeout=15).json()
            raw = res['candidates'][0]['content']['parts'][0]['text']
            data = json.loads(raw.replace('```json', '').replace('```', '').strip())
            
            dec = data['decyzja'].upper()
            if "KUP" in dec and portfolio['usdt'] > 10:
                portfolio['btc'], portfolio['usdt'] = portfolio['usdt'] / price, 0.0
            elif "SPRZEDAJ" in dec and portfolio['btc'] > 0:
                portfolio['usdt'], portfolio['btc'] = portfolio['btc'] * price, 0.0

            portfolio['total'] = portfolio['usdt'] + (portfolio['btc'] * price)
            history.append({"time": time.strftime("%H:%M:%S"), "action": dec, "price": price, "reason": data['powod']})
            if len(history) > 10: history.pop(0)

            requests.post(f"https://api.telegram.org/bot{CONFIG['token']}/sendMessage", 
                         json={"chat_id": CONFIG['chat'], "text": f"🤖 {dec} | Total: {portfolio['total']:.2f} USDT"})
            print(f"✅ KONIEC CYKLU. Cena: {price}")
        except Exception as e:
            print(f"❌ BLAD: {e}")
        
        time.sleep(120)

if __name__ == "__main__":
    # Odpalamy bota w tle, ale serwer Flask musi być 'lekki'
    threading.Thread(target=bot_cycle, daemon=True).start()
    port = int(os.environ.get('PORT', 8080))
    app.run(host='0.0.0.0', port=port)
