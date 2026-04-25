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
    "last_action": "System v8.1 gotowy...",
    "assets": {"BTC": {"amount":0, "rsi":50}, "ETH": {"amount":0, "rsi":50}}
}

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
            
            # Pobieranie realnego salda (naprawa błędu 30004)
            amt = float(balance.get(symbol, {}).get('free', 0.0))
            current_total_value += (amt * price)
            
            bars = mexc.fetch_ohlcv(pair, timeframe='1m', limit=50)
            df = pd.DataFrame(bars, columns=['ts', 'o', 'h', 'l', 'c', 'v'])
            rsi_val = calculate_rsi(df['c'])
            
            sys_prompt = f"Trader AI. RSI={rsi_val:.1f}. Kupuj < 45, Sprzedaj > 65. JSON: {{\"decision\": \"BUY/SELL/WAIT\"}}"
            chat = client.chat.completions.create(
                messages=[{"role":"system","content":sys_prompt}], 
                model="llama-3.1-8b-instant", 
                response_format={"type":"json_object"}
            )
            decision = json.loads(chat.choices[0].message.content).get('decision', 'WAIT')
            
            # Kupno (Limit Order)
            if decision == "BUY" and rsi_val < 48 and usdc_free >= 100:
                p_buy = round(price * 1.0005, 2)
                mexc.create_order(pair, 'limit', 'buy', round(100/p_buy, 6), p_buy)
                ai_thoughts.append(f"Kupno {symbol}")
            
            # Sprzedaż (Limit Order - naprawa błędu 30041)
            elif decision == "SELL" and amt > 0.0001 and rsi_val > 65:
                p_sell = round(price * 0.999, 2) 
                mexc.create_order(pair, 'limit', 'sell', amt, p_sell)
                ai_thoughts.append(f"Sprzedaż {symbol}")
            else:
                ai_thoughts.append(f"{symbol}: RSI {rsi_val:.1f}")

            assets_update[symbol] = {"amount": round(amt, 6), "rsi": round(rsi_val, 1)}

        profit = current_total_value - INITIAL_CAPITAL
        display_state = {
            "usdc": round(usdc_free, 2), "total": round(current_total_value, 2), 
            "profit": round(profit, 2), "last_action": " | ".join(ai_thoughts),
            "assets": assets_update
        }
        
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
    if range_type == 'day':
        filtered = [h for h in history if datetime.fromisoformat(h['t']) > now - timedelta(days=1)]
        step = max(1, len(filtered) // 60)
    elif range_type == 'week':
        filtered = [h for h in history if datetime.fromisoformat(h['t']) > now - timedelta(days=7)]
        step = max(1, len(filtered) // 80)
    else: # month
        filtered = [h for h in history if datetime.fromisoformat(h['t']) > now - timedelta(days=30)]
        step = max(1, len(filtered) // 100)
        
    return jsonify({"state": display_state, "history": filtered[::step]})

@app.route('/')
def home():
    uptime = f"{(datetime.now() - start_time).seconds // 3600}h {((datetime.now() - start_time).seconds // 60) % 60}m"
    return render_template_string("""
    <!DOCTYPE html>
    <html>
    <head>
        <title>AI Trader v8.1</title>
        <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
        <meta name="viewport" content="width=device-width, initial-scale=1">
        <style>
            body { background: #0b0e11; color: white; font-family: sans-serif; margin: 0; padding: 15px; }
            .grid { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; max-width: 600px; margin: auto; }
            .card { background: #1e2329; padding: 15px; border-radius: 12px; border: 1px solid #2b3139; text-align: center; }
            .label { color: #848e9c; font-size: 0.75em; text-transform: uppercase; margin-bottom: 5px; }
            .value { font-size: 1.2em; font-weight: bold; }
            .profit-plus { color: #0ecb81; } .profit-minus { color: #f6465d; }
            .ai-box { max-width: 600px; margin: 15px auto; padding: 12px; background: rgba(243, 186, 47, 0.1); border: 1px solid #f3ba2f; border-radius: 8px; font-size: 0.85em; text-align: center; }
            .chart-container { max-width: 600px; margin: auto; background: #1e2329; border-radius: 12px; padding: 10px; border: 1px solid #2b3139; }
            .btn-group { display: flex; justify-content: center; gap: 5px; margin-bottom: 10px; }
            button { background: #2b3139; color: #848e9c; border: none; padding: 6px 12px; border-radius: 4px; cursor: pointer; font-size: 0.75em; }
            button.active { background: #f3ba2f; color: black; font-weight: bold; }
            .asset-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 15px; max-width: 600px; margin: 15px auto; }
            .asset-card { background: #1e2329; padding: 15px; border-radius: 12px; border: 1px solid #2b3139; text-align: center;}
        </style>
    </head>
    <body>
        <h3 style="color: #f3ba2f; text-align:center; margin-bottom: 15px;">🔴 AI TRADER v8.1</h3>
        <div class="grid">
            <div class="card"><div class="label">USDC</div><div class="value" id="usdc">--</div></div>
            <div class="card"><div class="label">Uptime</div><div class="value">"""+uptime+"""</div></div>
            <div class="card"><div class="label">Zysk (Real)</div><div class="value" id="profit">--</div></div>
            <div class="card"><div class="label">Portfel</div><div class="value" id="total">--</div></div>
        </div>
        <div class="ai-box"><div id="ai_action">Ładowanie v8.1...</div></div>
        
        <div class="chart-container">
            <div class="btn-group">
                <button id="btn-day" onclick="setRange('day')" class="active">Dzień</button>
                <button id="btn-week" onclick="setRange('week')">Tydzień</button>
                <button id="btn-month" onclick="setRange('month')">Miesiąc</button>
            </div>
            <canvas id="myChart"></canvas>
        </div>

        <div class="asset-grid">
            <div class="asset-card"><div style="color:#f3ba2f; font-weight:bold;">BTC</div><div id="btc_amt" class="value">--</div><div id="btc_rsi" style="color:#848e9c; font-size:0.8em;">RSI: --</div></div>
            <div class="asset-card"><div style="color:#f3ba2f; font-weight:bold;">ETH</div><div id="eth_amt" class="value">--</div><div id="eth_rsi" style="color:#848e9c; font-size:0.8em;">RSI: --</div></div>
        </div>

        <script>
            let chart;
            let currentRange = 'day';

            function setRange(range) {
                currentRange = range;
                document.querySelectorAll('button').forEach(b => b.classList.remove('active'));
                document.getElementById('btn-' + range).classList.add('active');
                update();
            }

            async function update() {
                try {
                    const res = await fetch('/api/data/' + currentRange);
                    const data = await res.json();
                    
                    document.getElementById('usdc').innerText = data.state.usdc;
                    document.getElementById('total').innerText = data.state.total;
                    document.getElementById('ai_action').innerText = data.state.last_action;
                    document.getElementById('btc_amt').innerText = data.state.assets.BTC.amount;
                    document.getElementById('btc_rsi').innerText = 'RSI: ' + data.state.assets.BTC.rsi;
                    document.getElementById('eth_amt').innerText = data.state.assets.ETH.amount;
                    document.getElementById('eth_rsi').innerText = 'RSI: ' + data.state.assets.ETH.rsi;
                    
                    const pElem = document.getElementById('profit');
                    pElem.innerText = (data.state.profit >= 0 ? '+' : '') + data.state.profit + ' $';
                    pElem.className = 'value ' + (data.state.profit >= 0 ? 'profit-plus' : 'profit-minus');

                    const labels = data.history.map(h => {
                        const d = new Date(h.t);
                        return currentRange === 'day' ? d.toLocaleTimeString([], {hour:'2-digit', minute:'2-digit'}) : d.toLocaleDateString([], {day:'numeric', month:'short'});
                    });
                    const values = data.history.map(h => h.v);

                    if (!chart) {
                        chart = new Chart(document.getElementById('myChart').getContext('2d'), {
                            type: 'line',
                            data: { labels: labels, datasets: [{ data: values, borderColor: '#f3ba2f', tension: 0.3, fill: true, backgroundColor: 'rgba(243, 186, 47, 0.05)', pointRadius: 1 }] },
                            options: { animation: false, plugins: { legend: { display: false } }, scales: { y: { grid: { color: '#2b3139' } }, x: { grid: { display: false } } } }
                        });
                    } else { 
                        chart.data.labels = labels; 
                        chart.data.datasets[0].data = values; 
                        chart.update('none'); 
                    }
                } catch(e) {}
            }
            setInterval(update, 30000); update();
        </script>
    </body>
    </html>
    """)

if __name__ == "__main__":
    run_loop()
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 10000)))
