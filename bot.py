import requests
import ccxt
import json
import time
import os
from datetime import datetime

# Pobieranie kluczy z ustawień serwera (Environment Variables)
CONFIG = {
    "gemini_key": os.getenv("GEMINI_KEY"),
    "symbol": "BTC/USDT",
    "check_interval": 300, # 5 minut - bezpieczne dla darmowych serwerów
    "tg_token": os.getenv("TG_TOKEN"),
    "tg_chat_id": os.getenv("TG_CHAT_ID")
}

def send_telegram(message):
    if CONFIG["tg_token"] and CONFIG["tg_chat_id"]:
        try:
            url = f"https://api.telegram.org/bot{CONFIG['tg_token']}/sendMessage"
            requests.post(url, data={"chat_id": CONFIG["tg_chat_id"], "text": message})
        except Exception as e:
            print(f"Błąd Telegram: {e}")

def run_bot():
    print("🚀 Bot Railway wystartował!")
    send_telegram("✅ Bot Tradingowy odpalił na serwerze Railway!")
    
    # Próbujemy najpierw 2.5, potem 1.5
    model = "gemini-2.5-flash"
    
    while True:
        try:
            exchange = ccxt.mexc()
            price = exchange.fetch_ticker(CONFIG["symbol"])['last']
            
            url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={CONFIG['gemini_key']}"
            prompt = f"Cena BTC: {price} USDT. Podaj decyzję (KUPUJ/SPRZEDAWAJ/CZEKAJ) i powód po polsku w JSON: {{\"decyzja\": \"...\", \"powod\": \"...\"}}"
            
            r = requests.post(url, json={"contents": [{"parts": [{"text": prompt}]}]}, timeout=30)
            
            if r.status_code == 200:
                data = json.loads(r.json()['candidates'][0]['content']['parts'][0]['text'].replace('```json', '').replace('```', '').strip())
                msg = f"💰 Cena: {price} USDT\n🤖 AI: {data['decyzja']}\n📝 {data['powod']}"
                send_telegram(msg)
                time.sleep(CONFIG["check_interval"])
            elif r.status_code == 404 and model == "gemini-2.5-flash":
                model = "gemini-1.5-flash" # Auto-poprawka modelu
                continue
            elif r.status_code == 429:
                time.sleep(600) # Czekaj 10 min przy blokadzie
            else:
                time.sleep(60)
        except Exception as e:
            print(f"Błąd: {e}")
            time.sleep(60)

if __name__ == "__main__":
    run_bot()
