import requests
import ccxt
import json
import time
import os
from flask import Flask, render_template_string

app = Flask('')

# --- STAN SYSTEMU ---
state = {"usdt": 1000.0, "btc": 0.0, "total": 1000.0, "history": []}

@app.route('/')
def home():
    # TEST: Czy serwer w ogóle widzi Twoje klucze?
    gemini_ok = "TAK" if os.getenv("GEMINI_KEY") else "BRAK KLUCZA"
    tg_ok = "TAK" if os.getenv("TG_TOKEN") else "BRAK TOKENA"
    
    return f"""
    <html><body style="background:black;color:white;padding:20px;">
        <h1>Diagnostyka Bota</h1>
        <p>Klucz Gemini: {gemini_ok}</p>
        <p>Token Telegram: {tg_ok}</p>
        <p>ID Czatu: {os.getenv("TG_CHAT_ID")}</p>
        <hr>
        <button onclick="location.href='/test'">KLIKNIJ TUTAJ, ABY WYMUSIĆ TEST</button>
    </body></html>
    """

@app.route('/test')
def manual_test():
    results = []
    try:
        # 1. Test Giełdy
        ex = ccxt.mexc()
        price = ex.fetch_ticker("BTC/USDT")['last']
        results.append(f"✅ Cena BTC pobrana: {price}")

        # 2. Test Telegrama
        tg_url = f"https://api.telegram.org/bot{os.getenv('TG_TOKEN')}/sendMessage"
        tg_res = requests.post(tg_url, json={"chat_id": os.getenv("TG_CHAT_ID"), "text": "🔔 Test połączenia bota!"})
        results.append(f"✅ Telegram status: {tg_res.status_code}")

        # 3. Test Gemini
        g_url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent?key={os.getenv('GEMINI_KEY')}"
        g_res = requests.post(g_url, json={"contents": [{"parts": [{"text": "Napisz słowo TEST"}]}]}, timeout=10)
        results.append(f"✅ Gemini status: {g_res.status_code}")
        
    except Exception as e:
        results.append(f"❌ BŁĄD: {str(e)}")

    return "<br>".join(results) + "<br><br><a href='/'>Wróć</a>"

if __name__ == "__main__":
    port = int(os.environ.get('PORT', 10000))
    app.run(host='0.0.0.0', port=port)
