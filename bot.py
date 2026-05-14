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
TRADE_AMOUNT_USDC = 20.0     
RSI_BUY_THRESHOLD = 35         
RSI_SELL_THRESHOLD = 58        
COOLDOWN_MINUTES = 20  

mexc = ccxt.mexc({
    'apiKey': os.getenv('MEXC_API_KEY'),
    'secret': os.getenv('MEXC_SECRET_KEY'),
    'options': {'defaultType': 'spot'},
    'enableRateLimit': True
})

groq_client = Groq(api_key=os.getenv('GROQ_KEY'))

display_state = {
    "usdc": 0.0, "total": 0.0, "profit": 0.0,
    "buy_count": 0, "sell_count": 0,
    "last_action": "System Start...",
    "assets": {"BTC": {"amount":0, "rsi":50}, "ETH": {"amount":0, "rsi":50}}
}

avg_buy_prices = {"BTC": 0.0, "ETH": 0.0}
last_buy_time = {"BTC": datetime.now() - timedelta(hours=1), "ETH": datetime.now() - timedelta(hours=1)}

def ask_ai_decision(symbol, price, rsi):
    try:
        prompt = f"Analiza {symbol}: Cena {price}, RSI {rsi}. Kupujemy? Odpowiedz tylko TAK lub NIE."
        completion = groq_client.chat.completions.create(
            model="llama3-8b-8192", messages=[{"role": "user", "content": prompt}], max_tokens=5
        )
        return "TAK" in completion.choices[0].message.content.strip().upper()
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

def run_loop():
    global display_state, avg_buy_prices, last_buy_time
    try:
        mexc.load_markets() # Odświeżanie limitów giełdy co cykl
        balance = mexc.fetch_balance()
        usdc_free = float(balance.get('USDC', {}).get('free', 0.0))
        calculated_total = float(balance.get('USDC', {}).get('total', 0.0))
        
        reports = []
        for symbol in ["BTC", "ETH"]:
            pair = f"{symbol}/USDC"
            ticker = mexc.fetch_ticker(pair)
            price = float(ticker['last'])
            total_amt = float(balance.get(symbol, {}).get('total', 0.0))
            calculated_total += (total_amt * price)
            rsi_val = calculate_rsi(symbol)
            
            # Logika KUPNA
            if rsi_val < RSI_BUY_THRESHOLD and usdc_free >= TRADE_AMOUNT_USDC:
                if (datetime.now() - last_buy_time[symbol]) > timedelta(minutes=COOLDOWN_MINUTES):
                    if ask_ai_decision(symbol, price, rsi_val):
                        try:
                            # KLUCZOWA NAPRAWA: Precyzja ilości dla ETH
                            amount = TRADE_AMOUNT_USDC / price
                            precision = mexc.markets[pair]['precision']['amount']
                            qty = float(mexc.amount_to_precision(pair, amount))
                            
                            mexc.create_market_buy_order(pair, qty)
                            
                            last_buy_time[symbol] = datetime.now()
                            avg_buy_prices[symbol] = price
                            display_state["buy_count"] += 1
                            reports.append(f"✅ KUPIONO {symbol}")
                        except Exception as e:
                            print(f"Błąd kupna {symbol}: {e}")
                            reports.append(f"❌ BŁĄD {symbol}")

            # Logika SPRZEDAŻY
            elif rsi_val > RSI_SELL_THRESHOLD and total_amt > 0:
                if price > (avg_buy_prices[symbol] * 1.005): # Min. 0.5% zysku
                    try:
                        qty_sell = float(mexc.amount_to_precision(pair, total_amt))
                        mexc.create_market_sell_order(pair, qty_sell)
                        display_state["sell_count"] += 1
                        reports.append(f"💰 SPRZEDANO {symbol}")
                    except Exception as e:
                        print(f"Błąd sprzedaży {symbol}: {e}")

            display_state["assets"][symbol] = {"amount": round(total_amt, 6), "rsi": rsi_val}

        display_state.update({
            "usdc": round(usdc_free, 2),
            "total": round(calculated_total, 2),
            "profit": round(calculated_total - INITIAL_CAPITAL, 2),
            "last_action": " | ".join(reports) if reports else f"Skanowanie {datetime.now().strftime('%H:%M')}"
        })
    except Exception as e: print(f"Pętla: {e}")

@app.route('/api/data')
def get_data(): return jsonify(display_state)

@app.route('/')
def home():
    return render_template_string("""
    <!DOCTYPE html><html><head>
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <style>
        body { background: #000; color: #0f0; font-family: monospace; padding: 20px; }
        .box { border: 1px solid #0f0; padding: 15px; margin-bottom: 10px; border-radius: 5px; }
        .val { color: #fff; font-size: 1.5em; }
        .ai { color: #f3ba2f; font-weight: bold; border-color: #f3ba2f; }
    </style></head>
    <body>
        <h2>V12.0 TERMINAL</h2>
        <div class="box">USDC: <span class="val" id="usdc">--</span></div>
        <div class="box">TOTAL: <span class="val" id="total">--</span></div>
        <div class="box ai">STATUS: <br><span id="action">--</span></div>
        <div class="box">
            BTC: <span id="btc_rsi">--</span> RSI | <span id="btc_amt">--</span><br>
            ETH: <span id="eth_rsi">--</span> RSI | <span id="eth_amt">--</span>
        </div>
        <script>
            async function upd() {
                const r = await fetch('/api/data'); const d = await r.json();
                document.getElementById('usdc').innerText = d.usdc + ' $';
                document.getElementById('total').innerText = d.total + ' $';
                document.getElementById('action').innerText = d.last_action;
                document.getElementById('btc_rsi').innerText = d.assets.BTC.rsi;
                document.getElementById('eth_rsi').innerText = d.assets.ETH.rsi;
                document.getElementById('btc_amt').innerText = d.assets.BTC.amount + ' BTC';
                document.getElementById('eth_amt').innerText = d.assets.ETH.amount + ' ETH';
            }
            setInterval(upd, 5000); upd();
        </script>
    </body></html>
    """)

if __name__ == "__main__":
    scheduler = BackgroundScheduler()
    scheduler.add_job(func=run_loop, trigger="interval", seconds=30)
    scheduler.start()
    run_loop()
    app.run(host='0.0.0.0', port=10000)
