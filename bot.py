import os
import json
import ccxt
import pandas as pd
from groq import Groq
from flask import Flask, render_template_string, jsonify
from apscheduler.schedulers.background import BackgroundScheduler
from datetime import datetime, timedelta

# --- INICJALIZACJA SYSTEMU ---
app = Flask('')
start_time = datetime.now()
STATS_FILE = 'balance_history.json'
INITIAL_CAPITAL = 1000.0 

# --- KONFIGURACJA AGRESYWNA v8.6 (ZGODNIE Z TWOIMI PROŚBAMI) ---
TRADE_AMOUNT_USDC = 250.0      # Kwota pojedynczego zakupu (zwiększona dla większego zysku)
STOP_LOSS_PCT = 0.04           # Automatyczna sprzedaż przy stracie 4%
TRAILING_ACTIVATE_PCT = 0.025  # Aktywacja śledzenia zysku po osiągnięciu 2.5%
RSI_BUY_THRESHOLD = 50         # Kupuj częściej (RSI poniżej 50)
RSI_SELL_THRESHOLD = 65        # Sprzedawaj szybciej (RSI powyżej 65)

# --- POŁĄCZENIE Z GIEŁDĄ MEXC ---
mexc = ccxt.mexc({
    'apiKey': os.getenv('MEXC_API_KEY'),
    'secret': os.getenv('MEXC_SECRET_KEY'),
    'options': {'defaultType': 'spot'},
    'enableRateLimit': True
})
client = Groq(api_key=os.getenv('GROQ_KEY'))

# --- STAN SYSTEMU ---
display_state = {
    "usdc": 0.0,
    "total": 1000.0,
    "profit": 0.0,
    "buy_count": 0,
    "sell_count": 0,
    "last_action": "Inicjalizacja v8.6 Platinum...",
    "assets": {
        "BTC": {"amount": 0, "rsi": 50, "entry": 0.0},
        "ETH": {"amount": 0, "rsi": 50, "entry": 0.0}
    }
}

# --- FUNKCJA ANALIZY TECHNICZNEJ ---
def get_indicators(symbol):
    pair = f"{symbol}/USDC"
    bars = mexc.fetch_ohlcv(pair, timeframe='1m', limit=50)
    df = pd.DataFrame(bars, columns=['ts', 'o', 'h', 'l', 'c', 'v'])
    
    delta = df['c'].diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
    
    rs = gain / loss
    rsi = 100 - (100 / (1 + rs))
    return round(rsi.iloc[-1], 2)

# --- GŁÓWNA LOGIKA HANDLOWA ---
def trading_engine():
    global display_state
    try:
        balance = mexc.fetch_balance()
        usdc_free = float(balance.get('USDC', {}).get('free', 0.0))
        current_portfolio_value = usdc_free
        temp_assets = {}
        log_actions = []

        for symbol in ["BTC", "ETH"]:
            pair = f"{symbol}/USDC"
            ticker = mexc.fetch_ticker(pair)
            current_price = float(ticker['last'])
            crypto_amount = float(balance.get(symbol, {}).get('free', 0.0))
            
            # Aktualizacja wartości całkowitej
            current_portfolio_value += (crypto_amount * current_price)
            
            # Pobieranie RSI
            current_rsi = get_indicators(symbol)
            
            # Pobieranie ceny wejścia z pamięci
            entry_price = display_state["assets"].get(symbol, {}).get("entry", 0.0)
            
            # --- LOGIKA SPRZEDAŻY ---
            if crypto_amount > 0.00001 and entry_price > 0:
                profit_pct = (current_price - entry_price) / entry_price
                
                # Warunki: Stop Loss LUB Wysokie RSI LUB Trailing Profit
                if profit_pct <= -STOP_LOSS_PCT or current_rsi > RSI_SELL_THRESHOLD or (profit_pct > TRAILING_ACTIVATE_PCT and current_rsi < 55):
                    mexc.create_order(pair, 'limit', 'sell', crypto_amount, round(current_price * 0.999, 2))
                    display_state["sell_count"] += 1
                    entry_price = 0
                    log_actions.append(f"SPRZEDAŻ {symbol}")

            # --- LOGIKA KUPNA (DCA) ---
            if usdc_free >= TRADE_AMOUNT_USDC and current_rsi < RSI_BUY_THRESHOLD:
                buy_quantity = round(TRADE_AMOUNT_USDC / current_price, 6)
                mexc.create_order(pair, 'limit', 'buy', buy_quantity, round(current_price * 1.0005, 2))
                
                # Uśrednianie ceny wejścia
                new_entry = ((crypto_amount * entry_price) + (buy_quantity * current_price)) / (crypto_amount + buy_quantity) if crypto_amount > 0 else current_price
                entry_price = new_entry
                display_state["buy_count"] += 1
                log_actions.append(f"ZAKUP {symbol}")

            temp_assets[symbol] = {
                "amount": round(crypto_amount, 6),
                "rsi": current_rsi,
                "entry": round(entry_price, 2)
            }

        # Aktualizacja stanu wyświetlania
        display_state.update({
            "usdc": round(usdc_free, 2),
            "total": round(current_portfolio_value, 2),
            "profit": round(current_portfolio_value - INITIAL_CAPITAL, 2),
            "assets": temp_assets
        })
        
        if log_actions:
            display_state["last_action"] = " | ".join(log_actions)

        # Zapisywanie historii do wykresu
        history_entry = {"t": datetime.now().isoformat(), "v": round(current_portfolio_value, 2)}
        history_data = []
        if os.path.exists(STATS_FILE):
            with open(STATS_FILE, 'r') as f: history_data = json.load(f)
        history_data.append(history_entry)
        with open(STATS_FILE, 'w') as f: json.dump(history_data[-5000:], f)

    except Exception as e:
        display_state["last_action"] = f"Błąd: {str(e)}"

# --- HARMONOGRAM I SERWER ---
scheduler = BackgroundScheduler()
scheduler.add_job(trading_engine, 'interval', minutes=2)
scheduler.start()

@app.route('/api/data/<range_type>')
def api_data(range_type):
    history = []
    if os.path.exists(STATS_FILE):
        with open(STATS_FILE, 'r') as f: history = json.load(f)
    return jsonify({"state": display_state, "history": history})

@app.route('/')
def index():
    return render_template_string("""
    <!DOCTYPE html><html><head><title>AI v8.6 Platinum</title>
    <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <style>
        body { background: #0b0e11; color: white; font-family: 'Segoe UI', sans-serif; padding: 20px; }
        .container { max-width: 800px; margin: auto; }
        .grid { display: grid; grid-template-columns: 1fr 1fr; gap: 15px; margin-bottom: 20px; }
        .card { background: #1e2329; padding: 20px; border-radius: 15px; border: 1px solid #2b3139; text-align: center; }
        .label { color: #848e9c; font-size: 0.8em; margin-bottom: 5px; }
        .value { font-size: 1.4em; font-weight: bold; }
        .status { color: #f3ba2f; background: rgba(243,186,47,0.1); padding: 10px; border-radius: 10px; margin-bottom: 20px; text-align: center; font-size: 0.9em; }
        .chart-box { background: #1e2329; padding: 15px; border-radius: 15px; border: 1px solid #2b3139; }
    </style></head>
    <body>
        <div class="container">
            <h2 style="text-align:center; color:#f3ba2f;">🛡️ AI TRADER v8.6 PLATINUM</h2>
            <div class="status" id="action">Czekam na dane...</div>
            <div class="grid">
                <div class="card"><div class="label">WARTOŚĆ PORTFELA</div><div id="total" class="value">--</div></div>
                <div class="card"><div class="label">ZYSK/STRATA</div><div id="profit" class="value">--</div></div>
                <div class="card"><div class="label">DOSTĘPNE USDC</div><div id="usdc" class="value">--</div></div>
                <div class="card"><div class="label">OPERACJE (K/S)</div><div id="ops" class="value">--</div></div>
            </div>
            <div class="chart-box"><canvas id="mainChart"></canvas></div>
        </div>
        <script>
            let myChart;
            async function refresh() {
                const response = await fetch('/api/data/day');
                const data = await response.json();
                document.getElementById('total').innerText = data.state.total + ' $';
                document.getElementById('usdc').innerText = data.state.usdc + ' $';
                document.getElementById('profit').innerText = (data.state.profit > 0 ? '+' : '') + data.state.profit + ' $';
                document.getElementById('profit').style.color = data.state.profit >= 0 ? '#0ecb81' : '#f6465d';
                document.getElementById('ops').innerText = data.state.buy_count + ' / ' + data.state.sell_count;
                document.getElementById('action').innerText = "OSTATNIA AKCJA: " + data.state.last_action;
                
                const labels = data.history.map(h => new Date(h.t).toLocaleTimeString());
                const values = data.history.map(h => h.v);
                if(myChart) myChart.destroy();
                myChart = new Chart(document.getElementById('mainChart'), {
                    type: 'line',
                    data: { labels: labels, datasets: [{ data: values, borderColor: '#f3ba2f', tension: 0.3, fill: true, backgroundColor: 'rgba(243,186,47,0.05)' }] },
                    options: { responsive: true, plugins: { legend: { display: false } } }
                });
            }
            setInterval(refresh, 30000); refresh();
        </script>
    </body></html>
    """)

if __name__ == "__main__":
    trading_engine()
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 10000)))
