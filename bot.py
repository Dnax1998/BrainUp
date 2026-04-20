import requests
import ccxt
import json
import time
import os
import threading
from flask import Flask
from datetime import datetime

# --- MINI SERWER DLA RENDERA ---
app = Flask('')

@app.route('/')
def home():
    return "Bot is alive!"

def run_web():
    # Render wymaga przypisania portu
    port = int(os.environ.get('PORT', 8080))
    app.run(host='0.0.0.0', port=port)

# --- KONFIGURACJA BOTA ---
CONFIG = {
    "gemini_key": os.getenv("GEMINI_KEY"),
    "symbol": "BTC/USDT",
    "check_interval": 300, # 5 minut
    "tg_token": os.getenv("TG_TOKEN"),
    "tg_chat_id": os.getenv("TG_CHAT_ID")
}

def send_telegram(message):
    if CONFIG["tg_token"] and CONFIG["tg_chat_id"]:
        try:
            url = f"https://api.telegram.org/bot{CONFIG['tg_token']}/sendMessage"
            requests.post(url, data={"chat_id": CONFIG["tg_chat_id"], "text": message}, timeout=10)
        except:
            pass

def run_bot():
    print("🚀 Bot startuje...")
    send_telegram("✅ Bot uruchomiony na Renderze (24/7)!")
    
    model = "gemini-2.5-flash"
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={CONFIG['gemini_key']}"

    while True:
        try:
            exchange = ccxt.mexc()
            ticker = exchange.fetch_ticker(CONFIG["symbol"])
            price = ticker['last']
            
            prompt = f"Price: {price} USDT. Decision (BUY/SELL/HOLD) + short reason in Polish. JSON: {{\"decyzja\": \"...\", \"powod\": \"...\"}}"
            
            r = requests.post(url, json={"contents": [{"parts": [{"text": prompt}]}]}, timeout=30)
            
            if r.status_code == 200:
                data = json.loads(r.json()['candidates'][0]['content']['parts'][0]['text'].replace('```json', '').replace('```', '').strip())
                msg = f"💰 Cena: {price} USDT\n🤖 AI: {data['decyzja']}\n📝 {data['powod']}"
                send_telegram(msg)
                time.sleep(CONFIG["check_interval"])
            elif r.status_code == 429:
                time.sleep(600)
            else:
                time.sleep(60)
        except Exception as e:
            print(f"Error: {e}")
            time.sleep(60)

if __name__ == "__main__":
    # Uruchamiamy serwer www w tle
    threading.Thread(target=run_web).start()
    # Uruchamiamy bota
    run_bot()
