import os
import json
import ccxt
import pandas as pd
from groq import Groq
from flask import Flask, render_template_string, jsonify
from apscheduler.schedulers.background import BackgroundScheduler
from datetime import datetime, timedelta

app = Flask('')
start_time = datetime.now()
STATS_FILE = 'balance_history.json'
INITIAL_CAPITAL = 1000.0 

# --- PARAMETRY v8.4 ---
TRADE_AMOUNT_USDC = 100.0  # Kwota jednego pakietu
STOP_LOSS_PCT = 0.05       # 5% straty od średniej ceny = ewakuacja
TRAILING_ACTIVATE_PCT = 0.015 

# --- KONFIGURACJA ---
mexc = ccxt.mexc({
    'apiKey': os.getenv('MEXC_API_KEY'),
    'secret': os.getenv('MEXC_SECRET_KEY'),
    'options': {'defaultType': 'spot'},
    'enableRateLimit': True
})
client = Groq(api_key=os.getenv('GROQ_KEY'))

display_state = {
    "usdc": 0.0, "total": 1000.0, "profit": 0.0,
    "buy_count": 0, "sell_count": 0,
    "last_action": "System v8.4 DCA ready...",
    "assets": {"BTC": {"amount":0, "rsi":50, "entry":0.0}, "ETH": {"amount":0, "rsi":50, "entry":0.0}}
}

def calculate_indicators(df):
    delta = df['c'].diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
    rs = gain / loss
    df['rsi'] = 100 - (100 / (1 + rs))
    df['change'] = df['c'].pct_change(5) * 100
    return df

def run_loop():
    global display_state
    try:
        balance = mexc.fetch_balance()
        usdc_free = float(balance.get('USDC', {}).get('free', 0.0))
        current_total_value = usdc_free
        assets_update = {}
        ai_thoughts = []

        for symbol in ["BTC", "ETH"]:
            pair = f"{symbol}/USDC"
            ticker = mexc.fetch_ticker(pair)
            price = float(ticker['last'])
            amt = float(balance.get(symbol, {}).get('free', 0.0))
            current_total_value += (amt * price)
            
            bars = mexc.fetch_ohlcv(pair, timeframe='1m', limit=50)
            df = calculate_indicators(pd.DataFrame(bars, columns=['ts', 'o', 'h', 'l', 'c', 'v']))
            rsi_val = round(df['rsi'].iloc[-1], 1)
            volatility = round(df['change'].iloc[-1], 2)
            
            # Pobieramy średnią cenę wejścia z pamięci bota
            entry_price = display_state["assets"].get(symbol, {}).get("entry", 0.0)
            executed_protection = False

            # --- LOGIKA SPRZEDAŻY (Stop Loss / Trailing / RSI) ---
            if amt > 0.0001 and entry_price > 0:
                price_change = (price - entry_price) / entry_price
                
                if price_change <= -STOP_LOSS_PCT:
                    mexc.create_order(pair, 'limit', 'sell', amt, round(price * 0.998, 2))
                    display_state["sell_count"] += 1
                    entry_price = 0
                    ai_thoughts.append(f"STOP LOSS {symbol}")
                    executed_protection = True
                elif price_change >= TRAILING_ACTIVATE_PCT and rsi_val < 60:
                    mexc.create_order(pair, 'limit', 'sell', amt, round(price * 0.999, 2))
                    display_state["sell_count"] += 1
                    entry_price = 0
                    ai_thoughts.append(f"TAKE PROFIT {symbol}")
                    executed_protection = True
                elif rsi_val > 70:
                    mexc.create_order(pair, 'limit', 'sell', amt, round(price * 0.999, 2))
                    display_state["sell_count"] += 1
                    entry_price = 0
                    ai_thoughts.append(f"RSI SELL {symbol}")
                    executed_protection = True

            # --- LOGIKA KUPNA (Pakiety po 100 USDC) ---
            if not executed_protection:
                sys_prompt = f"Expert. RSI:{rsi_val}, Vol:{volatility}%. JSON: {{\"decision\": \"BUY/WAIT\"}}"
                chat = client.chat.completions.create(
                    messages=[{"role":"system","content":sys_prompt}], 
                    model="llama-3.1-8b-instant", 
                    response_format={"type":"json_object"}
                )
                decision = json.loads(chat.choices[0].message.content).get('decision', 'WAIT')

                # Kupujemy kolejny pakiet, jeśli mamy kasę i RSI jest niskie
                if decision == "BUY" and rsi_val < 45 and usdc_free >= TRADE_AMOUNT_USDC:
                    buy_qty = round(TRADE_AMOUNT_USDC / price, 6)
                    mexc.create_order(pair, 'limit', 'buy', buy_qty, round(price * 1.0005, 2))
                    
                    # Wyliczanie nowej średniej ceny wejścia
                    new_total_amt = amt + buy_qty
                    if amt == 0:
                        entry_price = price
                    else:
                        entry_price = ((amt * entry_price) + (buy_qty * price)) / new_total_amt
                    
                    display_state["buy_count"] += 1
                    ai_thoughts.append(f"Pakiet {symbol} KUPIONY")
                else:
                    ai_thoughts.append(f"{symbol}:{rsi_val}")

            assets_update[symbol] = {"amount": round(amt, 6), "rsi": rsi_val, "entry": round(entry_price, 2)}

        profit = current_total_value - INITIAL_CAPITAL
        display_state.update({
            "usdc": round(usdc_free, 2), "total": round(current_total_value, 2), 
            "profit": round(profit, 2), "last_action": " | ".join(ai_thoughts),
            "assets": assets_update
        })
        
        history = []
        if os.path.exists(STATS_FILE):
            with open(STATS_FILE, 'r') as f: history = json.load(f)
        history.append({"t": datetime.now().isoformat(), "v": round(current_total_value, 2)})
        with open(STATS_FILE, 'w') as f: json.dump(history[-10000:], f)

    except Exception as e:
        display_state["last_action"] = f"Błąd: {str(e)}"

scheduler = BackgroundScheduler()
scheduler.add_job(func=run_loop, trigger="interval", minutes=2)
scheduler.start()

@app.route('/api/data/<range_type>')
def get_data(range_type):
    history = []
    if os.path.exists(STATS_FILE):
        with open(STATS_FILE, 'r') as f: history = json.load(f)
    now = datetime.now()
    filtered = [h for h in history if datetime.fromisoformat(h['t']) > now - timedelta(days=1 if range_type=='day' else 7 if range_type=='week' else 30)]
    step = max(1, len(filtered) // 60)
    return jsonify({"state": display_state, "history": filtered[::step]})

@app.route('/')
def home():
    uptime = f"{(datetime.now() - start_time).seconds // 3600}h {((datetime.now() - start_time).seconds // 60) % 60}m"
    return render_template_string("""
    <!DOCTYPE html>
    <html>
    <head>
        <title>AI Trader v8.4 DCA</title>
        <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
        <meta name="viewport" content="width=device-width, initial-scale=1">
        <style>
            body { background: #0b0e11; color: white; font-family: sans-serif; padding: 15px; margin: 0; }
            .grid { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; max-width: 600px; margin: auto; }
            .card { background: #1e2329; padding: 15px; border-radius: 12px; border: 1px solid #2b3139; text-align: center; }
            .label { color: #848e9c; font-size: 0.75em; text-transform: uppercase; }
            .value { font-size: 1.2em; font-weight: bold; margin-top: 5px; }
            .profit-plus { color: #0ecb81; } .profit-minus { color: #f6465d; }
            .ai-box { max-width: 600px; margin: 15px auto; padding: 12px; background: rgba(243, 186, 47, 0.1); border: 1px solid #f3ba2f; border-radius: 8px; font-size: 0.85em; text-align: center; color: #f3ba2f; }
            .chart-container { max-width: 600px; margin: auto; background: #1e2329; border-radius: 12px; padding: 10px; border: 1px solid #2b3139; }
            .btn-group { display: flex; justify-content: center; gap: 5px; margin-bottom: 10px; }
            button { background: #2b3139; color: #848e9c; border: none; padding: 6px 12px; border-radius: 4px; cursor: pointer; }
            button.active { background: #f3ba2f; color: black; font-weight: bold; }
        </style>
    </head>
    <body>
        <h3 style="color:#f3ba2f; text-align:center;">💎 AI TRADER v8.4 (DCA MODE)</h3>
        <div class="grid">
            <div class="card"><div class="label">USDC Wolne</div><div class="value" id="usdc">--</div></div>
            <div class="card"><div class="label">Uptime</div><div class="value">"""+uptime+"""</div></div>
            <div class="card"><div class="label">Zysk (Real)</div><div id="profit" class="value">--</div></div>
            <div class="card"><div class="label">Portfel</div><div id="total" class="value">--</div></div>
        </div>
        <div class="ai-box"><b>Status:</b> <span id="ai_action">Inicjalizacja...</span></div>
        <div class="chart-container">
            <div class="btn-group">
                <button id="btn-day" onclick="setRange('day')" class="active">Dzień</button>
                <button id="btn-week" onclick="setRange('week')">Tydzień</button>
            </div>
            <canvas id="myChart"></canvas>
        </div>
        <div class="grid" style="margin-top:15px;">
            <div class="card"><div class="label">BTC Średnia</div><div id="btc_entry" class="value" style="color:#f3ba2f">--</div></div>
            <div class="card"><div class="label">ETH Średnia</div><div id="eth_entry" class="value" style="color:#f3ba2f">--</div></div>
        </div>
        <script>
            let chart; let currentRange = 'day';
            async function update() {
                const res = await fetch('/api/data/' + currentRange);
                const data = await res.json();
                document.getElementById('usdc').innerText = data.state.usdc;
                document.getElementById('total').innerText = data.state.total;
                document.getElementById('ai_action').innerText = data.state.last_action;
                document.getElementById('btc_entry').innerText = data.state.assets.BTC.entry;
                document.getElementById('eth_entry').innerText = data.state.assets.ETH.entry;
                const p = data.state.profit;
                document.getElementById('profit').innerText = (p>=0?'+':'')+p+' $';
                document.getElementById('profit').className = 'value ' + (p>=0?'profit-plus':'profit-minus');
                const labels = data.history.map(h => new Date(h.t).toLocaleTimeString([], {hour:'2-digit', minute:'2-digit'}));
                const values = data.history.map(h => h.v);
                if(!chart) {
                    chart = new Chart(document.getElementById('myChart'), {
                        type:'line', data:{labels, datasets:[{data:values, borderColor:'#f3ba2f', fill:true, backgroundColor:'rgba(243,186,47,0.05)'}]},
                        options:{animation:false, plugins:{legend:{display:false}}, scales:{x:{display:false}}}
                    });
                } else { chart.data.labels = labels; chart.data.datasets[0].data = values; chart.update('none'); }
            }
            function setRange(r) { currentRange=r; update(); }
            setInterval(update, 30000); update();
        </script>
    </body>
    </html>
    """)

if __name__ == "__main__":
    run_loop()
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 10000)))
