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
    # Render automatycznie przypisuje port, musimy go pobrać
    port = int(os.environ.get('PORT', 8080))
    # Wyłączamy debug i reloader, aby nie blokować pętli bota
    app.run(host='0.0.0.0', port=port, debug=False, use_reloader=False)

# --- KONFIGURACJA BOTA ---
CONFIG = {
    "gemini_key": os.getenv("GEMINI_KEY"),
    "symbol": "BTC/USDT",
    "check_interval": 300,  # Sprawdzanie co 5 minut
    "tg_token": os.getenv("TG_TOKEN"),
    "tg_chat_id": os.getenv("TG_CHAT_ID")
}

def send_telegram(message):
    print(f"📤 Próba wysyłki na Telegram: {message[:30]}...")
    if CONFIG["tg_token"] and CONFIG["tg_chat_id"]:
        try:
            url = f"https://api.telegram.org/bot{CONFIG['tg_token']}/sendMessage"
            payload = {
                "chat_id": CONFIG["tg_chat_id"],
                "text": message,
                "parse_mode": "Markdown"
            }
            r = requests.post(url, json=payload, timeout=10)
            print(f"📩 Status wysyłki: {r.status_code}")
        except Exception as e:
            print(f"❌ Błąd wysyłki Telegram: {e}")
    else:
        print("⚠️ Brak tokena lub ID czatu w zmiennych środowiskowych!")

def run_bot():
    print("🚀 Główna pętla bota wystartowała!")
    send_telegram("✅ **Bot Tradingowy AI wystartował!**\nMonitoruję BTC/USDT co 5 minut.")
    
    model = "gemini-1.5-flash"  # Upewnij się, że używasz poprawnej nazwy modelu
    api_url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={CONFIG['gemini_key']}"

    while True:
        try:
            print(f"🔍 Pobieranie danych z rynku dla {CONFIG['symbol']}...")
            exchange = ccxt.mexc()
            ticker = exchange.fetch_ticker(CONFIG["symbol"])
            price = ticker['last']
            
            prompt = (
                f"Aktualna cena {CONFIG['symbol']} to {price} USDT. "
                "Jako ekspert tradingu, podaj krótką decyzję: KUP, SPRZEDAJ lub CZEKAJ. "
                "Podaj powód w jednym krótkim zdaniu po polsku. "
                "Zwróć odpowiedź w formacie JSON: {\"decyzja\": \"...\", \"powod\": \"...\"}"
            )
            
            response = requests.post(api_url, json={"contents": [{"parts": [{"text": prompt}]}]}, timeout=30)
            
            if response.status_code == 200:
                raw_text = response.json()['candidates'][0]['content']['parts'][0]['text']
                # Czyszczenie odpowiedzi JSON z ewentualnych znaczników markdown
                clean_json = raw_text.replace('```json', '').replace('```', '').strip()
                data = json.loads(clean_json)
                
                msg = f"💰 **Para:** {CONFIG['symbol']}\n💵 **Cena:** {price} USDT\n🤖 **AI:** {data['decyzja']}\n📝 **Powód:** {data['powod']}"
                send_telegram(msg)
            else:
                print(f"⚠️ Błąd Gemini API: {response.status_code}")
                
            time.sleep(CONFIG["check_interval"])
            
        except Exception as e:
            print(f"❌ Błąd w pętli bota: {e}")
            time.sleep(60) # Czekaj minutę w przypadku błędu i spróbuj ponownie

# --- START APLIKACJI ---
if __name__ == "__main__":
    print("🛠️ Inicjalizacja usług...")
    
    # 1. Odpalamy serwer Flask w osobnym wątku (tło)
    web_thread = threading.Thread(target=run_web)
    web_thread.daemon = True
    web_thread.start()
    
    # 2. Czekamy chwilę na rozruch serwera
    time.sleep(5)
    
    # 3. Odpalamy bota w głównym procesie
    run_bot()
