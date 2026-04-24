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
display_state = {"usdc": 0.0, "total": 0.0, "assets": {}}

def log_to_console(msg):
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
    log_to_console("🚀 START ANALIZY v7.1 (Pełny wygląd + Skuteczne API)...")
    
    try:
        # 1. Pobranie salda
        balance = mexc.fetch_balance()
        usdc_free = float(balance.get('USDC', {}).get('free', 0.0))
        log_to_console(f"💰 Wolne środki: {usdc_free} USDC")

        assets_update = {}
        current_total = usdc_free

        for symbol in ["BTC", "ETH"]:
            pair = f"{symbol}/USDC"
            
            # 2. Dane rynkowe
            ticker = mexc.fetch_ticker(pair)
            price = float(ticker['last'])
            bars = mexc.fetch_ohlcv(pair, timeframe='1m', limit=50)
            df = pd.DataFrame(bars, columns=['ts', 'o', 'h', 'l', 'c', 'v'])
            rsi_val = calculate_rsi(df['c'])
            
            amt = float(balance.get(symbol, {}).get('total', 0.0))
            current_total += (amt * price)
            
            # 3. Konsultacja AI
            sys_prompt = f"Trader. RSI={rsi_val:.1f}. Kupuj < 45, Sprzedaj > 65. Zwróć JSON: {{\"decision\": \"BUY/SELL/WAIT\"}}"
            chat = client.chat.completions.create(
                messages=[{"role": "system", "content": sys_prompt}],
                model="llama-3.1-8b-instant",
                response_format={"type": "json_object"}
            )
            decision = json.loads(chat.choices[0].message.content).get('decision', 'WAIT')
            log_to_console(f"📊 {symbol}: RSI={rsi_val:.2f} | AI: {decision}")

            # 4. TRANSAKCJE (LIMIT BUY - to co zadziałało!)
            if decision == "BUY" and rsi_val < 48 and usdc_free >= 50:
                buy_price = round(price * 1.001, 2) 
                amount_to_buy = round(50 / buy_price, 6)
                log_to_console(f"🛒 Kupuję {symbol} (Zlecenie LIMIT za 50 USDC)...")
                try:
                    mexc.create_order(pair, 'limit', 'buy', amount_to_buy, buy_price)
                    log_to_console(f"✅ SUKCES!")
                except Exception as e:
                    log_to_console(f"❌ BŁĄD: {e}")

            elif decision == "SELL" and amt > 0 and rsi_val > 65:
                log_to_console(f"💸 Sprzedaję {symbol}...")
                try:
                    mexc.create_market_sell_order(pair, amt)
                    log_to_console(f"✅ Sprzedano!")
                except Exception as e:
                    log_to_console(f"❌ BŁĄD: {e}")

            assets_update[symbol] = {
                "amount": round(amt, 6),
                "rsi": round(rsi_val, 2),
                "price": price,
                "value": round(amt * price, 2),
                "decision": decision
            }

        display_state = {"usdc": round(usdc_free, 2), "assets": assets_update, "total": round(current_total, 2)}
        log_to_console("✅ KONIEC CYKLU.")

    except Exception as e:
        log_to_console(f"❌ BŁĄD KRYTYCZNY: {e}")

scheduler = BackgroundScheduler()
scheduler.add_job(func=run_loop, trigger="interval", minutes=2)
scheduler.start()

@app.route('/')
def home():
    uptime = f"{(datetime.now() - start_time).seconds // 60} min"
    
    # Budowanie tabeli aktywów
    assets_html = ""
    for sym, data in display_state['assets'].items():
        color = "#0ecb81" if data['decision'] == "BUY" else "#f6465d" if data['decision'] == "SELL" else "#848e9c"
        assets_html += f"""
        <div style="background:#1e2329; padding:15px; border-radius:10px; margin:10px 0; display:flex; justify-content:space-between; align-items:center;">
            <div>
                <span style="font-size:1.2em; font-weight:bold;">{sym}</span><br>
                <span style="color:#848e9c; font-size:0.9em;">Ilość: {data['amount']}</span>
            </div>
            <div style="text-align:center;">
                <span style="color:{color}; font-weight:bold;">RSI: {data['rsi']}</span><br>
                <span style="font-size:0.8em; color:#848e9c;">AI: {data['decision']}</span>
            </div>
            <div style="text-align:right;">
                <span style="font-weight:bold;">{data['value']} USDC</span><br>
                <span style="color:#848e9c; font-size:0.8em;">${data['price']}</span>
            </div>
        </div>
        """

    return f"""
    <body style="background:#0b0e11; color:white; font-family:sans-serif; margin:0; padding:20px;">
        <div style="max-width:500px; margin:auto;">
            <div style="text-align:center; padding:20px 0;">
                <h1 style="color:#f3ba2f; margin:0;">AI TRADER v7.1</h1>
                <p style="color:#848e9c; margin:5px 0;">Status: <span style="color:#0ecb81;">● LIVE</span> | Uptime: {uptime}</p>
            </div>
            
            <div style="background:#1e2329; padding:20px; border-radius:15px; text-align:center; margin-bottom:20px; border:1px solid #2b3139;">
                <span style="color:#848e9c; font-size:0.9em;">CAŁKOWITA WARTOŚĆ</span>
                <h2 style="font-size:2.5em; margin:10px 0;">{display_state.get('total', 0)} <span style="font-size:0.4em; color:#848e9c;">USDC</span></h2>
                <div style="color:#0ecb81; font-size:0.9em;">Dostępne: {display_state.get('usdc', 0)} USDC</div>
            </div>

            <h3 style="color:#f3ba2f; font-size:1.1em; margin-left:5px;">TWOJE AKTYWA</h3>
            {assets_html}

            <p style="text-align:center; color:#474d57; font-size:0.8em; margin-top:30px;">
                Aktualizacja co 2 minuty. Ostatnia: {datetime.now().strftime('%H:%M:%S')}<br>
                Kod v7.1 (Fix 30029 + Dashboard)
            </p>
        </div>
        <script>setTimeout(() => location.reload(), 30000);</script>
    </body>
    """

if __name__ == "__main__":
    run_loop()
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 10000)))
