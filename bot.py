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

# --- KONFIGURACJA ---
INITIAL_CAPITAL = 1000.0       
TRADE_AMOUNT_USDC = 20.0     # Kwota jednego zakupu
RSI_BUY_THRESHOLD = 35         
RSI_SELL_THRESHOLD = 58        
COOLDOWN_MINUTES = 30        

# Inicjalizacja MEXC
mexc = ccxt.mexc({
    'apiKey': os.getenv('MEXC_API_KEY'),
    'secret': os.getenv('MEXC_SECRET_KEY'),
    'options': {'defaultType': 'spot'},
    'enableRateLimit': True
})

# Kluczowe: Ładowanie rynków przy starcie
try:
    mexc.load_markets()
    print("✅ Rynki MEXC załadowane poprawnie.")
except Exception as e:
    print(f"❌ BŁĄD krytyczny przy łączeniu z MEXC: {e}")

groq_client = Groq(api_key=os.getenv('GROQ_KEY'))

display_state = {
    "usdc": 0.0, "total": 1000.0, "profit": 0.0,
    "buy_count": 0, "sell_count": 0,
    "last_action": "Inicjalizacja...",
    "assets": {"BTC": {"amount":0, "rsi":50}, "ETH": {"amount":0, "rsi":50}}
}

avg_buy_prices = {"BTC": 0.0, "ETH": 0.0}
last_buy_time = {
    "BTC": datetime.now() - timedelta(minutes=COOLDOWN_MINUTES), 
    "ETH": datetime.now() - timedelta(minutes=COOLDOWN_MINUTES)
}

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
    except: return True 

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
    global display_state, avg_buy_prices, last_buy_time
    try:
        balance = mexc.fetch_balance()
        usdc_free = float(balance.get('USDC', {}).get('free', 0.0))
        calculated_total = float(balance.get('USDC', {}).get('total', 0.0))
        
        assets_update = {}
        ai_reports = []

        for symbol in ["BTC", "ETH"]:
            pair = f"{symbol}/USDC"
            ticker = mexc.fetch_ticker(pair)
            price = float(ticker['last'])
            total_amt = float(balance.get(symbol, {}).get('total', 0.0))
            calculated_total += (total_amt * price)
            
            rsi_val = calculate_rsi(symbol)
            assets_update[symbol] = {"amount": round(total_amt, 6), "rsi": rsi_val}

            # Sprawdzenie blokady czasowej
            time_diff = datetime.now() - last_buy_time[symbol]
            can_buy = time_diff > timedelta(minutes=COOLDOWN_MINUTES)

            # --- KUPNO ---
            if rsi_val < RSI_BUY_THRESHOLD and usdc_free >= TRADE_AMOUNT_USDC and can_buy:
                if ask_ai_decision(symbol, price, rsi_val):
                    try:
                        # Obliczamy ilość i wymuszamy precyzję giełdy
                        qty = float(mexc.amount_to_precision(pair, TRADE_AMOUNT_USDC / price))
                        
                        print(f" Spróbuję kupić {qty} {symbol} po cenie {price}")
                        mexc.create_order(pair, 'market', 'buy', qty)
                        
                        last_buy_time[symbol] = datetime.now()
                        avg_buy_prices[symbol] = price # Uproszczone dla bezpieczeństwa
                        display_state["buy_count"] += 1
                        ai_reports.append(f"🤖 KUPNO {symbol}")
                    except Exception as e:
                        print(f"❌ BŁĄD zlecenia {symbol}: {e}")
                        ai_reports.append(f"❌ BŁĄD {symbol}")

            # --- SPRZEDAŻ ---
            elif rsi_val > RSI_SELL_THRESHOLD and total_amt > 0:
                try:
                    qty_sell = float(mexc.amount_to_precision(pair, total_amt))
                    if qty_sell > 0:
                        mexc.create_order(pair, 'market', 'sell', qty_sell)
                        display_state["sell_count"] += 1
                        ai_reports.append(f"💰 SPRZEDAŻ {symbol}")
                        avg_buy_prices[symbol] = 0.0
                except Exception as e:
                    print(f"❌ BŁĄD sprzedaży {symbol}: {e}")

        display_state.update({
            "usdc": round(usdc_free, 2),
            "total": round(calculated_total, 2),
            "profit": round(calculated_total - INITIAL_CAPITAL, 2),
            "last_action": " | ".join(ai_reports) if ai_reports else f"Skanowanie {datetime.now().strftime('%H:%M:%S')}",
            "assets": assets_update
        })
        save_history(calculated_total)
    except Exception as e: 
        print(f"🚨 Błąd pętli głównej: {e}")

@app.route('/api/data/<range_type>')
def get_data(range_type):
    if not os.path.exists(STATS_FILE): return jsonify({"state": display_state, "history": []})
    with open(STATS_FILE, 'r') as f:
        try: history = json.load(f)
        except: history = []
    return jsonify({"state": display_state, "history": history[-100:]})

@app.route('/')
def home():
    return render_template_string("""
    <!DOCTYPE html><html><head><title>AI TRADER v11.1</title>
    <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <style>
        body { background: #0b0e11; color: white; font-family: sans-serif; padding: 10px; margin: 0; }
        .grid { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; max-width: 600px; margin: auto; }
        .card { background: #1e2329; padding: 15px; border-radius: 10px; text-align: center; border: 1px solid #2b3139; }
        .value { font-size: 1.2em; font-weight: bold; color: #f3ba2f; }
        .ai-box { max-width: 600px; margin: 15px auto; padding: 10px; background: rgba(243,186,47,0.1); border: 1px solid #f3ba2f; border-radius: 5px; text-align: center; }
    </style></head>
    <body>
        <h3 style="text-align:center;">🧠 AI TRADER v11.1</h3>
        <div class="grid">
            <div class="card">USDC<br><span class="value" id="usdc">--</span></div>
            <div class="card">PORTFEL<br><span class="value" id="total">--</span></div>
            <div class="card">ZYSK<br><span id="profit" class="value">--</span></div>
            <div class="card">AKCJE<br>K: <span id="b_count">0</span> | S: <span id="s_count">0</span></div>
        </div>
        <div class="ai-box" id="ai_action">Inicjalizacja...</div>
        <div class="grid">
            <div class="card">BTC RSI: <span id="btc_rsi">--</span><br><small id="btc_amt">--</small></div>
            <div class="card">ETH RSI: <span id="eth_rsi">--</span><br><small id="eth_amt">--</small></div>
        </div>
        <script>
            async function update() {
                try {
                    const res = await fetch('/api/data/day');
                    const d = await res.json();
                    document.getElementById('usdc').innerText = d.state.usdc + ' $';
                    document.getElementById('total').innerText = d.state.total + ' $';
                    document.getElementById('profit').innerText = d.state.profit + ' $';
                    document.getElementById('b_count').innerText = d.state.buy_count;
                    document.getElementById('s_count').innerText = d.state.sell_count;
                    document.getElementById('ai_action').innerText = d.state.last_action;
                    document.getElementById('btc_rsi').innerText = d.state.assets.BTC.rsi;
                    document.getElementById('eth_rsi').innerText = d.state.assets.ETH.rsi;
                    document.getElementById('btc_amt').innerText = d.state.assets.BTC.amount + ' BTC';
                    document.getElementById('eth_amt').innerText = d.state.assets.ETH.amount + ' ETH';
                } catch(e) {}
            }
            setInterval(update, 5000); update();
        </script>
    </body></html>
    """)

if __name__ == "__main__":
    scheduler = BackgroundScheduler()
    scheduler.add_job(func=run_loop, trigger="interval", seconds=30)
    scheduler.start()
    run_loop()
    app.run(host='0.0.0.0', port=10000)
