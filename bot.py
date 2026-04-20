import requests
import ccxt
import json
import time
import os
import threading
from flask import Flask

# --- KONFIGURACJA SERWERA WWW (DLA RENDERA) ---
app = Flask('')

@app.route('/')
def home():
    return "Bot is running and healthy!"

def run_web():
    # Pobieramy port przypisany przez Render
    port = int(os.environ.get('PORT', 8080))
    # Wyłączamy reloader, aby nie blokować głównej pętli
    app.run(host='0.0.0.0', port=port, debug=False, use_reloader=False)

# --- KONFIGURACJA BOTA ---
CONFIG = {
    "gemini_key": os.getenv("GEMINI_KEY"),
    "symbol": "BTC/USDT",
    "check_interval": 300,  # Analiza co 5 minut
    "tg_token": os.getenv("TG_TOKEN"),
    "tg_chat_id": os.getenv("TG_CHAT_ID")
}

def send_telegram(message):
    print(f"📤 Próba wysyłki: {message[:40]}...")
    if CONFIG["tg_token"] and CONFIG["tg_chat_id"]:
        try:
            url = f"https://api.telegram.org/bot{CONFIG['tg_token']}/sendMessage"
            payload = {
                "chat_id": CONFIG["tg_chat_id"],
                "text": message,
                "parse_mode": "Markdown"
            }
            r = requests.post(url, json=payload, timeout=15)
            print(f"📩 Status wysyłki Telegram: {r.status_code}")
        except Exception as e:
            print(f"❌ Błąd wysyłki Telegram: {e}")
    else:
        print("⚠️ Brak TG_TOKEN lub TG_CHAT_ID w Environment Variables!")

def run_bot():
    print("🚀 Główna pętla bota wystartowała!")
    send_telegram("✅ **Bot Tradingowy AI wystartował na Renderze!**\nMonitoruję rynek 24/7.")
    
    # Adres API Gemini
    api_url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent?key={CONFIG['gemini_key']}"

    while True:
        try:
            print(f"🔍 Pobieranie ceny dla {CONFIG['symbol']}...")
            exchange = ccxt.mexc()
            ticker = exchange.fetch_ticker(CONFIG["symbol"])
            price = ticker['last']
            
            prompt = (
                f"Aktualna cena {CONFIG['symbol']} to {price} USDT. "
                "Jako ekspert tradingu, podaj decyzję: KUP, SPRZEDAJ lub CZEKAJ. "
                "Podaj powód w jednym krótkim zdaniu po polsku. "
                "Zwróć odpowiedź WYŁĄCZNIE w formacie JSON: {\"decyzja\": \"...\", \"powod\": \"...\"}"
            )
            
            response = requests.post(api_url, json={"contents": [{"parts": [{"text": prompt}]}]}, timeout=30)
            
            if response.status_code == 200:
                raw_text = response.json()['candidates'][0]['content']['parts'][0]['text']
                # Oczyszczanie JSONa z ewentualnych tagów ```json
                clean_json = raw_text.replace('```json', '').replace('```', '').strip()
                data = json.loads(clean_json)
                
                status_msg = (
                    f"💰 **Para:** {CONFIG['symbol']}\n"
                    f"💵 **Cena:** {price} USDT\n"
                    f"🤖 **AI:** {data['decyzja']}\n"
                    f"📝 **Powód:** {data['powod']}"
                )
                send_telegram(status_msg)
            else:
                print(f"⚠️ Błąd Gemini API (Status {response.status_code}): {response.text}")
            
            print(f"😴 Śpię przez {CONFIG['check_interval']} sekund...")
            time.sleep(CONFIG["check_interval"])
            
        except Exception as e:
            print(f"❌ Błąd w pętli bota: {e}")
            time.sleep(60)

# --- START APLIKACJI ---
if __name__ == "__main__":
    print("🛠️ Inicjalizacja usług...")
    
    # 1. Odpalamy serwer Flask w osobnym wątku (tło)
    try:
        t = threading.Thread(target=run_web)
        t.daemon = True
        t.start()
        print("✅ Serwer Flask wystartował w tle.")
    except Exception as e:
        print(f"❌ Błąd startu serwera Flask: {e}")

    # 2. Krótka przerwa na ustabilizowanie
    time.sleep(5)
    
    # 3. Odpalamy bota (Główny proces)
    print("🚀 Przechodzę do uruchomienia pętli bota...")
    run_bot()
