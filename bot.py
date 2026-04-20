import requests
import ccxt
import json
import time
import os
import threading
from flask import Flask

# --- KONFIGURACJA SERWERA WWW ---
app = Flask('')

@app.route('/')
def home():
    return "Bot is alive!"

def run_web():
    port = int(os.environ.get('PORT', 8080))
    print(f"🌐 Startuję serwer WWW na porcie {port}...")
    app.run(host='0.0.0.0', port=port)

# --- KONFIGURACJA BOTA ---
CONFIG = {
    "gemini_key": os.getenv("GEMINI_KEY"),
    "tg_token": os.getenv("TG_TOKEN"),
    "tg_chat_id": os.getenv("TG_CHAT_ID"),
    "symbol": "BTC/USDT"
}

def send_telegram(message):
    print(f"📤 Wysyłam do TG: {message[:30]}...")
    url = f"https://api.telegram.org/bot{CONFIG['tg_token']}/sendMessage"
    try:
        res = requests.post(url, json={"chat_id": CONFIG["tg_chat_id"], "text": message, "parse_mode": "Markdown"}, timeout=10)
        print(f"📩 Status TG: {res.status_code}")
    except Exception as e:
        print(f"❌ Błąd wysyłki: {e}")

def run_bot():
    print("🚀 START PĘTLI BOTA")
    send_telegram("✅ **Bot uruchomiony pomyślnie!** Sprawdzam rynek...")
    
    api_url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent?key={CONFIG['gemini_key']}"

    while True:
        try:
            print(f"🔍 Sprawdzam cenę {CONFIG['symbol']}...")
            exchange = ccxt.mexc()
            ticker = exchange.fetch_ticker(CONFIG["symbol"])
            price = ticker['last']
            
            prompt = (
                f"Cena {CONFIG['symbol']} to {price} USDT. "
                "Podaj decyzję: KUP, SPRZEDAJ lub CZEKAJ i powód w 1 zdaniu. "
                "Format JSON: {\"decyzja\": \"...\", \"powod\": \"...\"}"
            )
            
            response = requests.post(api_url, json={"contents": [{"parts": [{"text": prompt}]}]}, timeout=30)
            
            if response.status_code == 200:
                raw = response.json()['candidates'][0]['content']['parts'][0]['text']
                clean = raw.replace('```json', '').replace('```', '').strip()
                data = json.loads(clean)
                
                msg = f"💰 **BTC:** {price} USDT\n🤖 **AI:** {data['decyzja']}\n📝 {data['powod']}"
                send_telegram(msg)
            else:
                print(f"⚠️ Błąd Gemini API: {response.status_code}")

        except Exception as e:
            print(f"❌ Błąd w pętli: {e}")
        
        print("😴 Śpię 5 minut...")
        time.sleep(300)

# --- URUCHOMIENIE ---
if __name__ == "__main__":
    print("🛠️ Inicjalizacja...")
    
    # Najpierw sprawdzamy czy mamy zmienne
    if not CONFIG["tg_token"] or not CONFIG["tg_chat_id"]:
        print("❌ BRAK ZMIENNYCH TG_TOKEN LUB TG_CHAT_ID!")
    
    # Odpalamy serwer w osobnym wątku
    t = threading.Thread(target=run_web, daemon=True)
    t.start()
    
    # Odpalamy bota w głównym wątku
    run_bot()
