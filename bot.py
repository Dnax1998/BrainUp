import  os
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

# --- KONFIGURACJA ---
INITIAL_CAPITAL = 1000.0       
TRADE_AMOUNT_USDC = 20     
RSI_BUY_THRESHOLD = 35         
RSI_SELL_THRESHOLD = 58        

mexc = ccxt.mexc({
    'apiKey': os.getenv('MEXC_API_KEY'),
    'secret': os.getenv('MEXC_SECRET_KEY'),
    'options': {'defaultType': 'spot'},
    'enableRateLimit': True
})

groq_client = Groq(api_key=os.getenv('GROQ_KEY'))

display_state = {
    "usdc": 0.0, "total": 1000.0, "profit": 0.0,
    "buy_count": 0, "sell_count": 0,
    "last_action": "Inicjalizacja AI...",
    "assets": {"BTC": {"amount":0, "rsi":50}, "ETH": {"amount":0, "rsi":50}}
}

avg_buy_prices = {"BTC": 0.0, "ETH": 0.0}

def ask_ai_decision(symbol, price, rsi):
    try:
        prompt = f"Analiza techniczna {symbol}: Cena {price}, RSI {rsi}. Czy to bezpieczny moment na zakup w strategii DCA? Odpowiedz tylko jednym słowem: TAK lub NIE."
        completion = groq_client.chat.completions.create(
            model="llama3-8b-8192",
            messages=[{"role": "user", "content": prompt}],
            max_tokens=5
        )
        answer = completion.choices[0].message.content.strip().upper()
        return "TAK" in answer
    except:
        return True 

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
        current_time = datetime.now().strftime("%H:%M")
        balance = mexc.fetch_balance()
        
        usdc_total_balance = float(balance.get('USDC', {}).get('total', 0.0))
        usdc_free = float(balance.get('USDC', {}).get('free', 0.0))
        
        calculated_total = usdc_total_balance 
        assets_update = {}
        ai_reports = []

        for symbol in ["BTC", "ETH"]:
            pair = f"{symbol}/USDC"
            ticker = mexc.fetch_ticker(pair)
            price = float(ticker['last'])
            total_amt = float(balance.get(symbol, {}).get('total', 0.0))
            calculated_total += (total_amt * price)
            
            rsi_val = calculate_rsi(symbol)
            
            if rsi_val < RSI_BUY_THRESHOLD and usdc_free >= TRADE_AMOUNT_USDC:
                if ask_ai_decision(symbol, price, rsi_val):
                    qty = round(TRADE_AMOUNT_USDC / price, 6)
                    mexc.create_order(pair, 'limit', 'buy', qty, price)
                    current_val = total_amt * avg_buy_prices[symbol]
                    new_val = qty * price
                    avg_buy_prices[symbol] = (current_val + new_val) / (total_amt + qty)
                    display_state["buy_count"] += 1
                    ai_reports.append(f"🤖 KUPNO {symbol}")
                    usdc_free -= TRADE_AMOUNT_USDC
            
            elif rsi_val > RSI_SELL_THRESHOLD and total_amt > 0:
                if price > avg_buy_prices[symbol]:
                    mexc.create_order(pair, 'limit', 'sell', total_amt, price)
                    display_state["sell_count"] += 1
                    ai_reports.append(f"💰 SPRZEDAŻ {symbol}")
                    avg_buy_prices[symbol] = 0.0

            assets_update[symbol] = {"amount": round(total_amt, 6), "rsi": rsi_val}

        display_state.update({
            "usdc": round(usdc_free, 2),
            "total": round(calculated_total, 2),
            "profit": round(calculated_total - INITIAL_CAPITAL, 2),
            "last_action": " | ".join(ai_reports) if ai_reports else f"[{current_time}] Skanowanie... (Sal.: {round(calculated_total, 1)}$)",
            "assets": assets_update
        })
        save_history(calculated_total)
    except Exception as e: 
        print(f"Błąd pętli: {e}")

@app.route('/api/data/<range_type>')
def get_data(range_type):
    if not os.path.exists(STATS_FILE): return jsonify({"state": display_state, "history": []})
    with open(STATS_FILE, 'r') as f:
        try: history = json.load(f)
        except: history = []
    now = datetime.now()
    points = []
    if range_type == 'day':
        for i in range(23, -1, -1):
            target = now - timedelta(hours=i)
            match = min(history, key=lambda x: abs((datetime.fromisoformat(x['t']) - target).total_seconds()))
            points.append({"t": target.strftime("%H:00"), "v": match['v']})
    elif range_type == 'week':
        for i in range(13, -1, -1):
            target = now - timedelta(hours=i*12)
            match = min(history, key=lambda x: abs((datetime.fromisoformat(x['t']) - target).total_seconds()))
            points.append({"t": target.strftime("%d/%m"), "v": match['v']})
    elif range_type == 'month':
        for i in range(29, -1, -1):
            target = (now - timedelta(days=i)).replace(hour=12, minute=0)
            match = min(history, key=lambda x: abs((datetime.fromisoformat(x['t']) - target).total_seconds()))
            points.append({"t": target.strftime("%d/%m"), "v": match['v']})
    return jsonify({"state": display_state, "history": points})

@app.route('/')
def home():
    delta = datetime.now() - start_time
    days = delta.days
    hours = delta.seconds // 3600
    minutes = (delta.seconds // 60) % 60
    uptime_str = f"{days}d {hours}h {minutes}m" if days > 0 else f"{hours}h {minutes}m"

    return render_template_string("""
    <!DOCTYPE html><html><head><title>AI TRADER v11.0 SAFE</title>
    <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <style>
        body { background: #0b0e11; color: white; font-family: sans-serif; padding: 15px; margin: 0; }
        .grid { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; max-width: 600px; margin: auto; }
        .card { background: #1e2329; padding: 15px; border-radius: 12px; border: 1px solid #2b3139; text-align: center; }
        .label { color: #848e9c; font-size: 0.75em; text-transform: uppercase; }
        .value { font-size: 1.2em; font-weight: bold; margin-top: 5px; }
        .sub-label { font-size: 0.72em; color: #f3ba2f; margin-top: 8px; border-top: 1px solid #2b3139; padding-top: 5px; }
        .chart-container { max-width: 600px; margin: 15px auto; background: #1e2329; border-radius: 12px; padding: 15px; border: 1px solid #2b3139; }
        #timer { position: fixed; top: 10px; right: 10px; background: #f3ba2f; color: black; padding: 3px 10px; border-radius: 20px; font-size: 0.75em; font-weight: bold; z-index: 100; }
        .ai-box { max-width: 600px; margin: 15px auto; padding: 12px; background: rgba(243, 186, 47, 0.1); border: 1px solid #f3ba2f; border-radius: 8px; font-size: 0.85em; text-align: center; color: #f3ba2f; }
        .asset-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; max-width: 600px; margin: 15px auto; }
        button { background: #2b3139; color: #848e9c; border: none; padding: 6px 12px; border-radius: 4px; cursor: pointer; }
        button.active { background: #f3ba2f; color: black; font-weight: bold; }
    </style></head>
    <body>
        <div id="timer">Odświeżanie: 30s</div>
        <h3 style="color: #f3ba2f; text-align:center;">🧠 AI TRADER v11.0 SAFE</h3>
        <div class="grid">
            <div class="card"><div class="label">USDC Wolne</div><div class="value" id="usdc">--</div></div>
            <div class="card"><div class="label">Uptime</div><div class="value">"""+uptime_str+"""</div></div>
            <div class="card"><div class="label">Zysk (Realny)</div><div id="profit" class="value">--</div><div class="sub-label">Sprzedaże: <b id="s_count" style="color:white;">0</b></div></div>
            <div class="card"><div class="label">Wartość Portfela</div><div id="total" class="value">--</div><div class="sub-label">Kupna: <b id="b_count" style="color:white;">0</b></div></div>
        </div>
        <div class="ai-box"><b>Llama 3 Active Decision:</b><br><span id="ai_action">Skanowanie...</span></div>
        <div class="chart-container">
            <div style="display:flex; justify-content:center; gap:5px; margin-bottom:15px;">
                <button id="b-day" onclick="changeRange('day')" class="active">Dzień</button>
                <button id="b-week" onclick="changeRange('week')">Tydzień</button>
                <button id="b-month" onclick="changeRange('month')">Miesiąc</button>
            </div>
            <canvas id="myChart"></canvas>
        </div>
        <div class="asset-grid">
            <div class="card"><div style="color:#f3ba2f;">BTC</div><div id="btc_amt" class="value">--</div></div>
            <div class="card"><div style="color:#f3ba2f;">ETH</div><div id="eth_amt" class="value">--</div></div>
        </div>
        <script>
            let chart; let currentRange = 'day'; let timeLeft = 30;
            function changeRange(r) { currentRange = r; update(); }
            async function update() {
                const res = await fetch('/api/data/'+currentRange); const d = await res.json();
                document.getElementById('usdc').innerText = d.state.usdc + ' $';
                document.getElementById('total').innerText = d.state.total + ' $';
                document.getElementById('b_count').innerText = d.state.buy_count;
                document.getElementById('s_count').innerText = d.state.sell_count;
                document.getElementById('ai_action').innerText = d.state.last_action;
                document.getElementById('btc_amt').innerText = d.state.assets.BTC.amount;
                document.getElementById('eth_amt').innerText = d.state.assets.ETH.amount;
                const pEl = document.getElementById('profit');
                pEl.innerText = (d.state.profit>=0?'+':'') + d.state.profit + ' $';
                pEl.style.color = d.state.profit>=0?'#0ecb81':'#f6465d';
                timeLeft = 30;
                document.querySelectorAll('button').forEach(b => b.classList.remove('active'));
                document.getElementById('b-'+currentRange).classList.add('active');
                const chartData = {
                    labels: d.history.map(h => h.t),
                    datasets: [{
                        data: d.history.map(h => h.v),
                        borderColor: '#f3ba2f',
                        backgroundColor: 'rgba(243, 186, 47, 0.1)',
                        borderWidth: 2, tension: 0.1, fill: true
                    }]
                };
                if(!chart) {
                    chart = new Chart(document.getElementById('myChart'), {
                        type: 'line', data: chartData,
                        options: { animation: false, plugins: { legend: { display: false } }, scales: { y: { grid: { color: '#2b3139' }, ticks: { color: '#848e9c' } }, x: { grid: { display: true, color: '#2b3139' }, ticks: { color: '#848e9c' } } } }
                    });
                } else { chart.data = chartData; chart.update(); }
            }
            setInterval(() => {
                timeLeft--;
                document.getElementById('timer').innerText = 'Odświeżanie: ' + timeLeft + 's';
                if(timeLeft <= 0) update();
            }, 1000);
            update();
        </script>
    </body></html>
    """)

if __name__ == "__main__":
    # --- DODANO HARMONOGRAM ---
    scheduler = BackgroundScheduler()
    scheduler.add_job(func=run_loop, trigger="interval", seconds=30)
    scheduler.start()
    
    # Uruchomienie pierwszy raz ręcznie
    run_loop()
    
    app.run(host='0.0.0.0', port=10000)
