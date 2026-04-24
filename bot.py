import os
import time
import json
import ccxt
import pandas as pd
from groq import Groq
from flask import Flask, render_template_string
from apscheduler.schedulers.background import BackgroundScheduler
from datetime import datetime

app = Flask('')
start_time = datetime.now()
STATS_FILE = 'balance_history.json'

# --- KONFIGURACJA GIEŁDY ---
mexc = ccxt.mexc({
    'apiKey': os.getenv('MEXC_API_KEY'),
    'secret': os.getenv('MEXC_SECRET_KEY'),
    'options': {'defaultType': 'spot'},
    'enableRateLimit': True
})

client = Groq(api_key=os.getenv('GROQ_KEY'))

# Globalny stan dla Dashboardu
display_state = {
    "usdt": 0.0,
    "total": 0.0,
    "assets": {
        "BTC": {"amount": 0.0, "rsi": 0, "price": 0.0},
        "ETH": {"amount": 0.0, "rsi": 0, "price": 0.0}
    }
}

def log_to_console(msg):
    """Wypisuje logi natychmiast widoczne w panelu Render"""
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}", flush=True)

def calculate_rsi(prices, period=14):
    if len(prices) < period: return 50.0
    delta = prices.diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=period).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
    if loss.iloc[-1] == 0: return 100.0
    rs = gain.iloc[-1] / loss.iloc[-1]
    return 100 - (100 / (1 + rs))

def run_loop():
    global display_state
    log_to_console("🚀 ROZPOCZYNAM ANALIZĘ RYNKU...")
    
    try:
        # 1. Pobranie salda z MEXC
        balance = mexc.fetch_balance()
        # Wyciągamy USDC (MEXC trzyma to w 'total')
        usdc = float(balance.get('USDC', {}).get('total', 0.0))
        log_to_console(f"💰 Twoje saldo: {usdc} USDC")

        assets_update = {}
        current_total = usdc

        for symbol in ["BTC", "ETH"]:
            pair = f"{symbol}/USDC"
            
            # 2. Pobranie cen i danych do RSI
            ticker = mexc.fetch_ticker(pair)
            price = float(ticker['last'])
            bars = mexc.fetch_ohlcv(pair, timeframe='1m', limit=50)
            df = pd.DataFrame(bars, columns=['ts', 'o', 'h', 'l', 'c', 'v'])
            rsi_val = calculate_rsi(df['c'])
            
            amt = float(balance.get(symbol, {}).get('total', 0.0))
            current_total += (amt * price)
            
            assets_update[symbol] = {"amount": amt, "rsi": rsi_val, "price": price}
            log_to_console(f"📊 {symbol}: Cena={price}, RSI={rsi_val:.2f}, Posiadasz={amt}")

            # 3. Konsultacja z AI (Groq)
            sys_prompt = (
                f"Jesteś traderem krypto. RSI={rsi_val:.1f}. "
                "Zasada: Kupuj gdy RSI < 45, Sprzedaj gdy RSI > 65. "
                "Zwróć TYLKO JSON: {\"decision\": \"BUY\"/\"SELL\"/\"WAIT\", \"reason\": \"krótko po polsku\"}"
            )
            
            chat = client.chat.completions.create(
                messages=[{"role": "system", "content": sys_prompt}, 
                          {"role": "user", "content": f"Analizuj {pair} przy cenie {price}"}],
                model="llama-3.1-8b-instant",
                response_format={"type": "json_object"}
            )
            
            ai_res = json.loads(chat.choices[0].message.content)
            decision = ai_res.get('decision', 'WAIT')
            log_to_console(f"🤖 AI dla {symbol}: {decision} ({ai_res.get('reason')})")

            # 4. REALNA TRANSAKCJA
            # Kupujemy jeśli AI tak powie, RSI jest niskie i mamy min. 50 USDC
            if decision == "BUY" and rsi_val < 45 and usdc >= 50:
                log_to_console(f"🔥 WARUNKI SPEŁNIONE! KUPUJĘ {symbol} ZA 50 USDC...")
                try:
                    mexc.create_market_buy_order(pair, 50)
                    log_to_console("✅ Zlecenie kupna wykonane pomyślnie!")
                except Exception as e:
                    log_to_console(f"❌ BŁĄD TRANSAKCJI (Sprawdź uprawnienia API!): {e}")

            # Sprzedajemy jeśli mamy co i RSI jest wysokie
            elif decision == "SELL" and amt > 0 and rsi_val > 60:
                log_to_console(f"💸 WARUNKI SPEŁNIONE! SPRZEDAJĘ {symbol}...")
                try:
                    mexc.create_market_sell_order(pair, amt)
                    log_to_console("✅ Zlecenie sprzedaży wykonane pomyślnie!")
                except Exception as e:
                    log_to_console(f"❌ BŁĄD TRANSAKCJI: {e}")

        # Aktualizacja stanu dla strony WWW
        display_state = {
            "usdt": usdc,
            "assets": assets_update,
            "total": current_total
        }

        # Zapis historii do wykresu
        history = []
        if os.path.exists(STATS_FILE):
            with open(STATS_FILE, 'r') as f: history = json.load(f)
        history.append({"timestamp": datetime.now().isoformat(), "balance": round(current_total, 2)})
        with open(STATS_FILE, 'w') as f: json.dump(history[-500:], f)
        
        log_to_console("✅ KONIEC CYKLU ANALIZY.")

    except Exception as e:
        log_to_console(f"❌ KRYTYCZNY BŁĄD W PĘTLI: {str(e)}")

# --- HARMONOGRAM ---
scheduler = BackgroundScheduler()
scheduler.add_job(func=run_loop, trigger="interval", minutes=2)
scheduler.start()

# --- DASHBOARD (HTML) ---
HTML_TEMPLATE = """
<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <title>AI TRADER v6.5 LIVE</title>
    <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css" rel="stylesheet">
    <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
    <style>
        body { background: #0b0e11; color: white; padding: 20px; font-family: 'Segoe UI', sans-serif; }
        .stat-card { background: #1e2329; border: 1px solid #2b3139; border-radius: 12px; padding: 15px; text-align: center; margin-bottom: 15px; }
        .coin-box { background: #181a20; border: 1px solid #2b3139; border-radius: 10px; padding: 10px; }
    </style>
</head>
<body>
    <div class="container text-center">
        <h2 style="color: #f3ba2f;">🔴 AI TRADER v6.5 LIVE</h2>
        <div class="mb-4"><span class="badge bg-success">POŁĄCZONO Z MEXC</span></div>
        
        <div class="row g-3 mb-4">
            <div class="col-4"><div class="stat-card"><small class="text-secondary">USDC</small><br><strong>{{ usdt|round(2) }}</strong></div></div>
            <div class="col-4"><div class="stat-card"><small class="text-secondary">UPTIME</small><br><strong>{{ uptime }}</strong></div></div>
            <div class="col-4"><div class="stat-card"><small class="text-secondary">TOTAL $</small><br><strong>{{ total|round(2) }}</strong></div></div>
        </div>

        <div class="row g-3 mb-4">
            {% for coin, data in assets.items() %}
            <div class="col-6">
                <div class="coin-box">
                    <strong style="color:#f3ba2f">{{ coin }}</strong><br>
                    <span>{{ data.amount|round(6) }}</span><br>
                    <small class="text-secondary">RSI: {{ data.rsi|round(1) }}</small>
                </div>
            </div>
            {% endfor %}
        </div>

        <div style="background: #1e2329; border-radius: 12px; padding: 15px;">
            <canvas id="balanceChart" height="120"></canvas>
        </div>
    </div>
    <script>
        const ctx = document.getElementById('balanceChart').getContext('2d');
        const h = JSON.parse('{{ chart_json|safe }}');
        new Chart(ctx, {
            type: 'line',
            data: {
                labels: h.map(x => new Date(x.timestamp).toLocaleTimeString()),
                datasets: [{ label: 'Total Value', data: h.map(x => x.balance), borderColor: '#f3ba2f', tension: 0.3 }]
            },
            options: { scales: { y: { grid: { color: '#222' } } } }
        });
        setTimeout(() => location.reload(), 30000);
    </script>
</body>
</html>
"""

@app.route('/')
def home():
    h_data = []
    if os.path.exists(STATS_FILE):
        with open(STATS_FILE, 'r') as f: h_data = json.load(f)
    uptime = f"{(datetime.now() - start_time).seconds // 3600}h {((datetime.now() - start_time).seconds // 60) % 60}m"
    return render_template_string(HTML_TEMPLATE, **display_state, uptime=uptime, chart_json=json.dumps(h_data))

if __name__ == "__main__":
    run_loop() # Pierwszy start danych
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 10000)))
