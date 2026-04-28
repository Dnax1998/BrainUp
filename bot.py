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
INITIAL_CAPITAL = 1000.0 

# --- KONFIGURACJA v9.0 BrainUp ---
TRADE_AMOUNT_USDC = 250.0      
STOP_LOSS_PCT = 0.04           
RSI_BUY_THRESHOLD = 50         
RSI_SELL_THRESHOLD = 65        

# Inicjalizacja klientów
mexc = ccxt.mexc({
    'apiKey': os.getenv('MEXC_API_KEY'),
    'secret': os.getenv('MEXC_SECRET_KEY'),
    'options': {'defaultType': 'spot'},
    'enableRateLimit': True
})

# Klient Groq AI
groq_client = Groq(api_key=os.getenv('GROQ_KEY'))

display_state = {
    "usdc": 0.0, "total": 1000.0, "profit": 0.0,
    "buy_count": 0, "sell_count": 0,
    "last_action": "Inicjalizacja v9.0 BrainUp (Llama 3)...",
    "assets": {"BTC": {"amount":0, "rsi":50, "entry":0.0}, "ETH": {"amount":0, "rsi":50, "entry":0.0}}
}

def ask_ai_decision(symbol, price, rsi):
    """Pyta model Llama 3 przez Groq o opinię na temat wejścia w pozycję."""
    try:
        prompt = f"Analyze {symbol} trade: Price {price}, RSI {rsi}. Is it a good buy opportunity? Answer ONLY 'BUY' or 'WAIT'."
        completion = groq_client.chat.completions.create(
            model="llama3-8b-8192",
            messages=[{"role": "user", "content": prompt}],
            max_tokens=10
        )
        decision = completion.choices[0].message.content.strip().upper()
        return "BUY" in decision
    except Exception as e:
        print(f"AI Error: {e}")
        return True # Jeśli AI zawiedzie, polegamy na samym RSI

def calculate_rsi(symbol):
    try:
        pair = f"{symbol}/USDC"
        bars = mexc.fetch_ohlcv(pair, timeframe='1m', limit=50)
        df = pd.DataFrame(bars, columns=['ts', 'o', 'h', 'l', 'c', 'v'])
        delta = df['c'].diff()
        gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
        rsi = 100 - (100 / (1 + (gain / loss)))
        return round(rsi.iloc[-1], 1)
    except: return 50.0

def run_loop():
    global display_state
    try:
        balance = mexc.fetch_balance()
        usdc_free = float(balance.get('USDC', {}).get('free', 0.0))
        current_total = usdc_free
        assets_update = {}
        actions = []

        for symbol in ["BTC", "ETH"]:
            pair = f"{symbol}/USDC"
            ticker = mexc.fetch_ticker(pair)
            price = float(ticker['last'])
            amt_on_exchange = float(balance.get(symbol, {}).get('free', 0.0))
            current_total += (amt_on_exchange * price)
            rsi_val = calculate_rsi(symbol)
            entry = display_state["assets"].get(symbol, {}).get("entry", 0.0)

            # --- LOGIKA SPRZEDAŻY ---
            if amt_on_exchange > 0.00001:
                if entry == 0: entry = price 
                change = (price - entry) / entry
                if change <= -STOP_LOSS_PCT or rsi_val > RSI_SELL_THRESHOLD:
                    mexc.create_order(pair, 'market', 'sell', amt_on_exchange)
                    display_state["sell_count"] += 1
                    entry = 0
                    actions.append(f"AI SELL {symbol}")

            # --- LOGIKA KUPNA (RSI + LLAMA 3) ---
            if usdc_free >= TRADE_AMOUNT_USDC and rsi_val < RSI_BUY_THRESHOLD and amt_on_exchange < 0.00001:
                # KROK 1: Sygnał techniczny (RSI)
                # KROK 2: Weryfikacja przez LLM
                if ask_ai_decision(symbol, price, rsi_val):
                    qty = round(TRADE_AMOUNT_USDC / price, 6)
                    mexc.create_order(pair, 'market', 'buy', qty)
                    entry = price
                    display_state["buy_count"] += 1
                    actions.append(f"AI BUY {symbol}")
                else:
                    actions.append(f"AI VETO: {symbol} (RSI OK, AI WAIT)")

            assets_update[symbol] = {"amount": round(amt_on_exchange, 6), "rsi": rsi_val, "entry": round(entry, 2)}

        display_state.update({
            "usdc": round(usdc_free, 2), "total": round(current_total, 2), 
            "profit": round(current_total - INITIAL_CAPITAL, 2),
            "last_action": " | ".join(actions) if actions else f"Mózg AI: Skanowanie trendów BTC/ETH",
            "assets": assets_update
        })
        
        history = []
        if os.path.exists(STATS_FILE):
            with open(STATS_FILE, 'r') as f: history = json.load(f)
        history.append({"t": datetime.now().isoformat(), "v": round(current_total, 2)})
        with open(STATS_FILE, 'w') as f: json.dump(history[-10000:], f)
    except Exception as e: 
        display_state["last_action"] = f"Błąd: {str(e)}"

# Scheduler co 1 minutę dla lepszej analizy AI
scheduler = BackgroundScheduler()
scheduler.add_job(run_loop, 'interval', minutes=1)
scheduler.start()

@app.route('/api/data/<range_type>')
def get_data(range_type):
    history = []
    if os.path.exists(STATS_FILE):
        with open(STATS_FILE, 'r') as f: history = json.load(f)
    if not history: return jsonify({"state": display_state, "history": []})
    now = datetime.now()
    final_history = []
    used_indices = set()

    def get_closest(target_time, margin_seconds):
        best_idx = -1; min_diff = margin_seconds
        for idx, item in enumerate(history):
            if idx in used_indices: continue
            diff = abs((datetime.fromisoformat(item['t']) - target_time).total_seconds())
            if diff < min_diff:
                min_diff = diff; best_idx = idx
        if best_idx != -1:
            used_indices.add(best_idx)
            return history[best_idx]
        return None

    if range_type == 'day':
        for i in range(23, -1, -1):
            t = now - timedelta(hours=i)
            p = get_closest(t, 3500)
            if p: final_history.append(p)
    elif range_type == 'week':
        for i in range(13, -1, -1):
            t = now - timedelta(hours=i*12)
            p = get_closest(t, 40000)
            if p: final_history.append(p)
    else: 
        for i in range(29, -1, -1):
            t = now - timedelta(days=i)
            p = get_closest(t, 80000)
            if p: final_history.append(p)
    return jsonify({"state": display_state, "history": final_history})

@app.route('/')
def home():
    uptime = f"{(datetime.now() - start_time).seconds // 3600}h {((datetime.now() - start_time).seconds // 60) % 60}m"
    return render_template_string("""
    <!DOCTYPE html><html><head><title>AI TRADER v9.0 BrainUp</title>
    <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <style>
        body { background: #0b0e11; color: white; font-family: sans-serif; padding: 15px; margin: 0; }
        .grid { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; max-width: 600px; margin: auto; }
        .card { background: #1e2329; padding: 15px; border-radius: 12px; border: 1px solid #2b3139; text-align: center; }
        .label { color: #848e9c; font-size: 0.75em; text-transform: uppercase; margin-bottom: 5px; }
        .value { font-size: 1.2em; font-weight: bold; }
        .ai-box { max-width: 600px; margin: 15px auto; padding: 12px; background: rgba(243, 186, 47, 0.1); border: 1px solid #f3ba2f; border-radius: 8px; font-size: 0.85em; text-align: center; color: #f3ba2f; }
        .chart-container { max-width: 600px; margin: auto; background: #1e2329; border-radius: 12px; padding: 10px; border: 1px solid #2b3139; }
        .btn-group { display: flex; justify-content: center; gap: 5px; margin-bottom: 10px; }
        button { background: #2b3139; color: #848e9c; border: none; padding: 6px 12px; border-radius: 4px; cursor: pointer; }
        button.active { background: #f3ba2f; color: black; font-weight: bold; }
        #timer { position: fixed; top: 10px; right: 10px; background: #f3ba2f; color: black; padding: 2px 8px; border-radius: 20px; font-size: 0.7em; font-weight: bold; }
    </style></head>
    <body>
        <div id="timer">Aktualizacja: 30s</div>
        <h3 style="color: #f3ba2f; text-align:center;">🧠 AI TRADER v9.0 BrainUp</h3>
        <div class="grid">
            <div class="card"><div class="label">USDC Wolne</div><div class="value" id="usdc">--</div></div>
            <div class="card"><div class="label">Uptime</div><div class="value">"""+uptime+"""</div></div>
            <div class="card"><div class="label">Zysk (Real)</div><div id="profit" class="value">--</div></div>
            <div class="card"><div class="label">Portfel</div><div id="total" class="value">--</div></div>
        </div>
        <div class="ai-box"><b>Llama 3 Analytics:</b> <span id="ai_action">Analiza danych...</span></div>
        <div class="chart-container">
            <div class="btn-group">
                <button id="b-day" onclick="changeRange('day')" class="active">Dzień</button>
                <button id="b-week" onclick="changeRange('week')">Tydzień</button>
                <button id="b-month" onclick="changeRange('month')">Miesiąc</button>
            </div>
            <canvas id="myChart"></canvas>
        </div>
        <script>
            let chart; let currentRange = 'day'; let timeLeft = 30;
            function startTimer() { setInterval(() => { timeLeft--; if(timeLeft <= 0) timeLeft = 30; document.getElementById('timer').innerText = 'Aktualizacja: ' + timeLeft + 's'; }, 1000); }
            function changeRange(r) { currentRange = r; document.querySelectorAll('button').forEach(b => b.classList.remove('active')); document.getElementById('b-'+r).classList.add('active'); update(); }
            async function update() {
                try {
                    const res = await fetch('/api/data/'+currentRange); const d = await res.json();
                    document.getElementById('usdc').innerText = d.state.usdc;
                    document.getElementById('total').innerText = d.state.total;
                    document.getElementById('profit').innerText = d.state.profit + ' $';
                    document.getElementById('ai_action').innerText = d.state.last_action;
                    const labels = d.history.map(h => {
                        const dt = new Date(h.t);
                        return currentRange === 'day' ? dt.getHours() + ':00' : dt.getDate() + '/' + (dt.getMonth()+1);
                    });
                    if(!chart) {
                        chart = new Chart(document.getElementById('myChart'), {
                            type:'line', data:{labels:labels, datasets:[{data:d.history.map(h=>h.v), borderColor:'#f3ba2f', tension:0.3, fill:true}]},
                            options:{animation:false, plugins:{legend:{display:false}}}
                        });
                    } else { chart.data.labels = labels; chart.data.datasets[0].data = d.history.map(h=>h.v); chart.update(); }
                } catch(e) {}
            }
            setInterval(update, 30000); update(); startTimer();
        </script>
    </body></html>
    """)

if __name__ == "__main__":
    run_loop(); app.run(host='0.0.0.0', port=10000)
