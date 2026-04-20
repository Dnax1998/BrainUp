import requests
import ccxt
import json
import time
import os
import threading
from flask import Flask

# --- KONFIGURACJA SERWERA ---
app = Flask('')
@app.route('/')
def home(): return "Virtual Trader is Running!"

def run_web():
    port = int(os.environ.get('PORT', 8080))
    app.run(host='0.0.0.0', port=port)

# --- KONFIGURACJA BOTA I PORTFELA ---
CONFIG = {
    "gemini_key": os.getenv("GEMINI_KEY"),
    "tg_token": os.getenv("TG_TOKEN"),
    "tg_chat_id": os.getenv("TG_CHAT_ID"),
    "symbol": "BTC/USDT"
}

# Wirtualny portfel (startujemy z 1000 USDT)
portfolio = {
    "usdt": 1000.0,
    "btc": 0.0,
    "last_buy_price": 0.0
}

def send_telegram(message):
    url = f"https://api.telegram.org/bot{CONFIG['tg_token']}/sendMessage"
    try:
        requests.post(url, json={"chat_id": CONFIG["tg_chat_id"], "text": message, "parse_mode": "Markdown"}, timeout=10)
    except: pass

def run_bot():
    print("🚀 START WIRTUALNEGO TRADERA")
    send_telegram(f"🤖 **Bot Handlowy AI Startuje!**\n💰 Portfel początkowy: {portfolio['usdt']} USDT")
    
    api_url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent?key={CONFIG['gemini_key']}"

    while True:
        try:
            exchange = ccxt.mexc()
            ticker = exchange.fetch_ticker(CONFIG["symbol"])
            price = ticker['last']
            
            prompt = (
                f"Cena {CONFIG['symbol']} to {price} USDT. "
                f"Masz w portfelu: {portfolio['usdt']:.2f} USDT i {portfolio['btc']:.4f} BTC. "
                "Podaj decyzję: KUP (jeśli masz USDT), SPRZEDAJ (jeśli masz BTC) lub CZEKAJ. "
                "Zwróć TYLKO JSON: {\"decyzja\": \"KUP/SPRZEDAJ/CZEKAJ\", \"powod\": \"...\"}"
            )
            
            response = requests.post(api_url, json={"contents": [{"parts": [{"text": prompt}]}]}, timeout=30)
            if response.status_code == 200:
                raw = response.json()['candidates'][0]['content']['parts'][0]['text']
                data = json.loads(raw.replace('```json', '').replace('```', '').strip())
                decyzja = data['decyzja'].upper()
                
                trade_info = ""
                
                # --- LOGIKA WIRTUALNEGO HANDLU ---
                if "KUP" in decyzja and portfolio['usdt'] > 10:
                    portfolio['btc'] = portfolio['usdt'] / price
                    portfolio['last_buy_price'] = price
                    portfolio['usdt'] = 0.0
                    trade_info = f"🛒 **KUPIONO BTC** po {price} USDT"
                    
                elif "SPRZEDAJ" in decyzja and portfolio['btc'] > 0:
                    portfolio['usdt'] = portfolio['btc'] * price
                    profit = ((price - portfolio['last_buy_price']) / portfolio['last_buy_price']) * 100 if portfolio['last_buy_price'] > 0 else 0
                    trade_info = f"💰 **SPRZEDANO BTC** po {price} USDT\n📈 Zysk/Strata: {profit:.2f}%"
                    portfolio['btc'] = 0.0
                
                else:
                    trade_info = "⏳ **CZEKAM** (brak akcji)"

                # Podsumowanie stanu posiadania
                total_value = portfolio['usdt'] + (portfolio['btc'] * price)
                msg = (
                    f"{trade_info}\n\n"
                    f"💵 **Cena:** {price} USDT\n"
                    f"📝 **AI:** {data['powod']}\n"
                    f"📊 **Wartość portfela:** {total_value:.2f} USDT"
                )
                send_telegram(msg)
                
        except Exception as e:
            print(f"Błąd: {e}")
        
        time.sleep(300) # Sprawdzaj co 5 minut

if __name__ == "__main__":
    threading.Thread(target=run_web, daemon=True).start()
    run_bot()a
