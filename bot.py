import os
import json
import ccxt
import pandas as pd
from flask import Flask, render_template_string, jsonify
from apscheduler.schedulers.background import BackgroundScheduler
from datetime import datetime, timedelta
from groq import Groq

app = Flask('')
start_time = datetime.now()
STATS_FILE = 'balance_history.json'
STATE_FILE = 'bot_state.json'

# --- KONFIGURACJA ---
INITIAL_CAPITAL = 1000.0       
TRADE_AMOUNT_USDC = 200.0      
RSI_BUY_THRESHOLD = 35         
RSI_SELL_THRESHOLD = 58        

mexc = ccxt.mexc({'apiKey': os.getenv('MEXC_API_KEY'), 'secret': os.getenv('MEXC_SECRET_KEY'), 'options': {'defaultType': 'spot'}, 'enableRateLimit': True})
groq_client = Groq(api_key=os.getenv('GROQ_KEY'))

# --- ŁADOWANIE STANU (Persistence) ---
def load_state():
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, 'r') as f: return json.load(f)
        except: pass
    return {
        "avg_buy_prices": {"BTC": 0.0, "ETH": 0.0},
        "display_state": {
            "usdc": 0.0, "total": 1000.0, "profit": 0.0,
            "buy_count": 0, "sell_count": 0, "last_action": "Inicjalizacja...",
            "assets": {"BTC": {"amount":0}, "ETH": {"amount":0}}
        }
    }

data = load_state()
avg_buy_prices = data["avg_buy_prices"]
display_state = data["display_state"]

def save_state():
    with open(STATE_FILE, 'w') as f:
        json.dump({"avg_buy_prices": avg_buy_prices, "display_state": display_state}, f)

# --- LOGIKA BOTA ---
def ask_ai_decision(symbol, price, rsi):
    try:
        prompt = f"Analiza {symbol}: Cena {price}, RSI {rsi}. Czy kupować (DCA)? Odpowiedz jednym słowem: TAK lub NIE."
        completion = groq_client.chat.completions.create(model="llama3-8b-8192", messages=[{"role": "user", "content": prompt}], max_tokens=5)
        return "TAK" in completion.choices[0].message.content.strip().upper()
    except: return True 

def calculate_rsi(symbol):
    try:
        bars = mexc.fetch_ohlcv(f"{symbol}/USDC", timeframe='1m', limit=50)
        df = pd.DataFrame(bars, columns=['ts', 'o', 'h', 'l', 'c', 'v'])
        delta = df['c'].diff()
        gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
        rsi = 100 - (100 / (1 + (gain / loss)))
        return round(rsi.iloc[-1], 1)
    except: return 50.0

def save_history(val):
    history = []
    if os.path.exists(STATS_FILE):
        with open(STATS_FILE, 'r') as f:
            try: history = json.load(f)
            except: history = []
    history.append({"t": datetime.now().isoformat(), "v": round(val, 2)})
    with open(STATS_FILE, 'w') as f:
        json.dump(history[-20000:], f)

def run_loop():
    global display_state, avg_buy_prices
    try:
        balance = mexc.fetch_balance()
        if not balance or 'USDC' not in balance: return 

        usdc_free = float(balance.get('USDC', {}).get('free', 0.0))
        btc_amt = float(balance.get('BTC', {}).get('total', 0.0))
        eth_amt = float(balance.get('ETH', {}).get('total', 0.0))
        
        try:
            price_btc = float(mexc.fetch_ticker("BTC/USDC")['last'])
            price_eth = float(mexc.fetch_ticker("ETH/USDC")['last'])
        except: return

        calculated_total = usdc_free + (btc_amt * price_btc) + (eth_amt * price_eth)
        
        # Logika kupna/sprzedaży
        assets_info = {"BTC": {"amount": round(btc_amt, 6)}, "ETH": {"amount": round(eth_amt, 6)}}
        ai_reports = []
        
        for symbol, amt, price in [("BTC", btc_amt, price_btc), ("ETH", eth_amt, price_eth)]:
            rsi_val = calculate_rsi(symbol)
            if rsi_val < RSI_BUY_THRESHOLD and usdc_free >= TRADE_AMOUNT_USDC:
                if ask_ai_decision(symbol, price, rsi_val):
                    try:
                        mexc.create_order(f"{symbol}/USDC", 'limit', 'buy', round(TRADE_AMOUNT_USDC/price, 6), price)
                        avg_buy_prices[symbol] = price
                        display_state["buy_count"] += 1
                        usdc_free -= TRADE_AMOUNT_USDC
                        ai_reports.append(f"🤖 KUPNO {symbol}")
                    except: pass
            
            elif rsi_val > RSI_SELL_THRESHOLD and amt > 0:
                if price > avg_buy_prices.get(symbol, 0):
                    try:
                        mexc.create_order(f"{symbol}/USDC", 'limit', 'sell', amt, price)
                        display_state["sell_count"] += 1
                        avg_buy_prices[symbol] = 0.0
                        ai_reports.append(f"💰 SPRZEDAŻ {symbol}")
                    except: pass

        display_state.update({
            "usdc": round(usdc_free, 2), "total": round(calculated_total, 2),
            "profit": round(calculated_total - INITIAL_CAPITAL, 2),
            "last_action": " | ".join(ai_reports) if ai_reports else f"Skanowanie ({datetime.now().strftime('%H:%M')})",
            "assets": assets_info
        })
        save_history(calculated_total)
        save_state()
    except Exception as e: print(f"Błąd pętli: {e}")

# --- WEB UI & ROUTES ---
scheduler = BackgroundScheduler()
scheduler.add_job(run_loop, 'interval', minutes=1)
scheduler.start()

@app.route('/api/data/<range_type>')
def get_data(range_type):
    if not os.path.exists(STATS_FILE): return jsonify({"state": display_state, "history": []})
    with open(STATS_FILE, 'r') as f:
        try: history = json.load(f)
        except: history = []
    # Generowanie punktów dla wykresu
    now = datetime.now()
    points = []
    # Logika zakresów
    lookback = 24 if range_type == 'day' else (168 if range_type == 'week' else 720)
    for i in range(lookback, 0, -int(lookback/24)):
        target = now - timedelta(hours=i)
        match = min(history, key=lambda x: abs((datetime.fromisoformat(x['t']) - target).total_seconds()))
        points.append({"t": target.strftime("%H:%M" if range_type == 'day' else "%d/%m"), "v": match['v']})
    return jsonify({"state": display_state, "history": points})

@app.route('/')
def home():
    return render_template_string("""
    <!DOCTYPE html><html><head><title>AI TRADER FULL</title>
    <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
    <style>
        body { background: #0b0e11; color: white; font-family: sans-serif; padding: 10px; }
        .grid { display: grid; grid-template-columns: 1fr 1fr; gap: 8px; }
        .card { background: #1e2329; padding: 12px; border-radius: 8px; text-align: center; }
        .label { color: #848e9c; font-size: 0.7em; }
        .value { font-size: 1.1em; font-weight: bold; }
        .ai-box { margin-top: 10px; padding: 10px; background: #2b3139; border-radius: 8px; color: #f3ba2f; font-size: 0.9em; }
    </style></head>
    <body>
        <h3 style="text-align:center;">🧠 AI TRADER FULL</h3>
        <div class="grid">
            <div class="card"><div class="label">USDC</div><div class="value" id="usdc">--</div></div>
            <div class="card"><div class="label">Portfel</div><div class="value" id="total">--</div></div>
            <div class="card"><div class="label">ZYSK (REALNY)</div><div class="value" id="profit">--</div></div>
            <div class="card"><div class="label">Statystyki</div><div class="value" id="stats">K:0 | S:0</div></div>
        </div>
        <div class="ai-box" id="ai_action">Skanowanie...</div>
        <div class="card" style="margin-top:10px;">
            <div style="margin-bottom:10px;">
                <button onclick="updateData('day')">Dzień</button> <button onclick="updateData('week')">Tydzień</button> <button onclick="updateData('month')">Miesiąc</button>
            </div>
            <canvas id="myChart"></canvas>
        </div>
        <div class="grid" style="margin-top:10px;">
            <div class="card">BTC: <span id="btc_amt">0</span></div>
            <div class="card">ETH: <span id="eth_amt">0</span></div>
        </div>
        <script>
            let chart;
            async function updateData(range='day') {
                const res = await fetch('/api/data/'+range); const d = await res.json();
                document.getElementById('usdc').innerText = d.state.usdc + ' $';
                document.getElementById('total').innerText = d.state.total + ' $';
                document.getElementById('ai_action').innerText = d.state.last_action;
                document.getElementById('stats').innerText = 'K: ' + d.state.buy_count + ' | S: ' + d.state.sell_count;
                document.getElementById('btc_amt').innerText = d.state.assets.BTC.amount;
                document.getElementById('eth_amt').innerText = d.state.assets.ETH.amount;
                const pEl = document.getElementById('profit');
                pEl.innerText = d.state.profit + ' $';
                pEl.style.color = d.state.profit >= 0 ? '#0ecb81' : '#f6465d';
                if(!chart) { chart = new Chart(document.getElementById('myChart'), { type: 'line', data: { labels: d.history.map(h=>h.t), datasets: [{ data: d.history.map(h=>h.v), borderColor: '#f3ba2f' }] } }); }
                else { chart.data.labels = d.history.map(h=>h.t); chart.data.datasets[0].data = d.history.map(h=>h.v); chart.update(); }
            }
            setInterval(updateData, 30000); updateData();
        </script>
    </body></html>
    """)

if __name__ == "__main__":
    app.run(host='0.0.0.0', port=10000)
