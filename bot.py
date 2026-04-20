import requests
import ccxt
import json
import time
import os
import threading
from flask import Flask, render_template_string

# --- KONFIGURACJA SERWERA I DANYCH ---
app = Flask('')

# Pamięć bota (zniknie po restarcie serwera)
history = [] 
portfolio = {"usdt": 1000.0, "btc": 0.0, "total": 1000.0}

HTML_TEMPLATE = """
<!DOCTYPE html>
<html>
<head>
    <title>AI Trader Dashboard</title>
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css" rel="stylesheet">
    <style>
        body { background: #121212; color: white; font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; }
        .card { background: #1e1e1e; border: 1px solid #333; color: white; margin-bottom: 20px; box-shadow: 0 4px 15px rgba(0,0,0,0.5); }
        .status-up { color: #00ff88; font-weight: bold; }
        .text-info { color: #00d4ff !important; }
        .trade-row { border-bottom: 1px solid #333; padding: 15px 0; }
        .trade-row:last-child { border-bottom: none; }
        .badge-buy { background-color: #28a745; }
        .badge-sell { background-color: #dc3545; }
        .badge-wait { background-color: #6c757d; }
    </style>
</head>
<body>
    <div class="container mt-5">
        <h2 class="mb-4 text-center text-uppercase">🤖 AI Crypto Trader Dashboard</h2>
        
        <div class="row">
            <div class="col-md-4">
                <div class="card p-4 text-center">
                    <h6 class="text-muted">SALDO USDT</h6>
                    <h3 class="status-up">{{ portfolio.usdt|round(2) }}</h3>
                </div>
            </div>
            <div class="col-md-4">
                <div class="card p-4 text-center">
                    <h6 class="text-muted">POSIADANE BTC</h6>
                    <h3>{{ portfolio.btc|round(6) }}</h3>
                </div>
            </div>
            <div class="col-md-4">
                <div class="card p-4 text-center">
                    <h6 class="text-muted">ŁĄCZNA WARTOŚĆ</h6>
                    <h2 class="text-info">{{ portfolio.total|round(2) }} USDT</h2>
                </div>
            </div>
        </div>

        <div class="card p-4">
            <h5 class="mb-3 text-center">Ostatnie Akcje (Historia)</h5>
            <div id="history-container">
                {% if not history %}
                    <p class="text-muted text-center italic">Czekam na pierwszą analizę rynku (odśwież za chwilę)...</p>
                {% endif %}
                {% for trade in history[::-1] %}
                <div class="trade-row">
                    <span class="badge {% if 'KUP' in trade.action %}badge-buy{% elif 'SPRZEDAJ' in trade.action %}badge-sell{% else %}badge-wait{% endif %}">
                        {{ trade.action }}
                    </span>
                    <small class="ms-2 text-muted">{{ trade.time }}</small>
                    <div class="mt-2 fw-bold text-light">Cena: {{ trade.price }} USDT</div>
                    <div class="mt-1 small text-secondary italic">Powód: {{ trade.reason }}</div>
                </div>
                {% endfor %}
            </div>
        </div>
    </div>
    <script>
        setTimeout(function(){ location.reload(); }, 60000);
    </script>
</body>
</html>
"""

@app.route('/')
def home():
    return render_template_string(HTML_TEMPLATE, portfolio=portfolio, history=history)

def run_web():
    port = int(os.environ.get('PORT', 8080))
    print(f"🌐 Serwer WWW startuje na porcie {port}")
    app.run(host='0.0.0.0', port=port, debug=False, use_reloader=False)

# --- LOGIKA BOTA ---
CONFIG = {
    "gemini_key": os.getenv("GEMINI_KEY"),
    "tg_token": os.getenv("TG_TOKEN"),
    "tg_chat_id": os.getenv("TG_CHAT_ID"),
    "symbol": "BTC/USDT"
}

def send_telegram(message):
    url = f"https://api.telegram.org/bot{CONFIG['tg_token']}/sendMessage"
    try:
        requests.post(url, json={"chat_id": CONFIG["tg_chat_id"], "text": message, "parse_mode": "Markdown"}, timeout=10)
    except Exception as e:
        print(f"❌ Błąd Telegram: {e}")

def run_bot():
    print("🚀 Pętla bota aktywowana!")
    send_telegram("✅ **Virtual AI Trader ONLINE**\nZaczynamy z saldem 1000 USDT.")
    
    api_url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent?key={CONFIG['gemini_key']}"

    while True:
        try:
            print("🔍 Analizuję rynek...")
            exchange = ccxt.mexc()
            ticker = exchange.fetch_ticker(CONFIG["symbol"])
            price = ticker['last']
            print(f"📈 Aktualna cena {CONFIG['symbol']}: {price} USDT")
            
            prompt = (
                f"Aktualna cena BTC: {price} USDT. "
                f"Twój portfel: {portfolio['usdt']:.2f} USDT i {portfolio['btc']:.6f} BTC. "
                "Podaj decyzję: KUP (jeśli masz USDT), SPRZEDAJ (jeśli masz BTC) lub CZEKAJ. "
                "Zwróć odpowiedź WYŁĄCZNIE jako JSON: {\"decyzja\": \"KUP/SPRZEDAJ/CZEKAJ\", \"powod\": \"krótkie zdanie po polsku\"}"
            )
            
            response = requests.post(api_url, json={"contents": [{"parts": [{"text": prompt}]}]}, timeout=30)
            
            if response.status_code == 200:
                res_data = response.json()
                raw_text = res_data['candidates'][0]['content']['parts'][0]['text']
                print(f"🤖 Odpowiedź AI (raw): {raw_text}")
                
                # Ulepszone wycinanie JSON-a
                clean_json = raw_text.strip()
                if "```json" in clean_json:
                    clean_json = clean_json.split("```json")[1].split("```")[0].strip()
                elif "```" in clean_json:
                    clean_json = clean_json.split("```")[1].split("```")[0].strip()
                
                data = json.loads(clean_json)
                decyzja = data.get('decyzja', 'CZEKAJ').upper()
                powod = data.get('powod', 'Brak powodu')
                
                # Mechanizm handlu
                if "KUP" in decyzja and portfolio['usdt'] > 10:
                    portfolio['btc'] = portfolio['usdt'] / price
                    portfolio['usdt'] = 0.0
                    print("💰 AKCJA: KUPIONO")
                elif "SPRZEDAJ" in decyzja and portfolio['btc'] > 0:
                    portfolio['usdt'] = portfolio['btc'] * price
                    portfolio['btc'] = 0.0
                    print("💰 AKCJA: SPRZEDANO")
                
                portfolio['total'] = portfolio['usdt'] + (portfolio['btc'] * price)
                
                # Historia do dashboardu
                history.append({
                    "time": time.strftime("%H:%M:%S"),
                    "action": decyzja,
                    "price": price,
                    "reason": powod
                })
                if len(history) > 10: history.pop(0)
                
                send_telegram(f"🤖 **AI:** {decyzja}\n💰 **Wartość:** {portfolio['total']:.2f} USDT\n📝 {powod}")
                print(f"✅ Analiza zakończona sukcesem. Stan konta: {portfolio['total']:.2f}")
            else:
                print(f"❌ Błąd Gemini API: {response.status_code} - {response.text}")

        except Exception as e:
            print(f"❌ Błąd krytyczny w run_bot: {e}")
        
        print("😴 Śpię 5 minut...")
        time.sleep(300)

if __name__ == "__main__":
    print("🛠️ System startuje...")
    t = threading.Thread(target=run_web, daemon=True)
    t.start()
    run_bot()
