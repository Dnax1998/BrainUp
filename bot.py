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
display_state = {"usdt": 0.0, "total": 0.0, "assets": {}}

def log_to_console(msg):
    """Wypisuje logi widoczne w panelu Render"""
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
    log_to_console("🚀 START ANALIZY v7.0 (Obejście błędu 30029)...")
    
    try:
        # 1. Pobranie salda
        balance = mexc.fetch_balance()
        usdc_balance = float(balance.get('USDC', {}).get('free', 0.0))
        log_to_console(f"💰 Wolne środki: {usdc_balance} USDC")

        assets_update = {}
        current_total = usdc_balance

        for symbol in ["BTC", "ETH"]:
            pair = f"{symbol}/USDC"
            
            # 2. Pobranie cen i RSI
            ticker = mexc.fetch_ticker(pair)
            price = float(ticker['last'])
            bars = mexc.fetch_ohlcv(pair, timeframe='1m', limit=50)
            df = pd.DataFrame(bars, columns=['ts', 'o', 'h', 'l', 'c', 'v'])
            rsi_val = calculate_rsi(df['c'])
            
            amt = float(balance.get(symbol, {}).get('total', 0.0))
            current_total += (amt * price)
            assets_update[symbol] = {"amount": amt, "rsi": rsi_val, "price": price}

            # 3. Konsultacja AI
            sys_prompt = f"Trader. RSI={rsi_val:.1f}. Kupuj < 45, Sprzedaj > 65. Zwróć JSON: {{\"decision\": \"BUY/SELL/WAIT\"}}"
            chat = client.chat.completions.create(
                messages=[{"role": "system", "content": sys_prompt}],
                model="llama-3.1-8b-instant",
                response_format={"type": "json_object"}
            )
            decision = json.loads(chat.choices[0].message.content).get('decision', 'WAIT')
            log_to_console(f"📊 {symbol}: RSI={rsi_val:.2f} | AI mówi: {decision}")

            # 4. TRANSAKCJA (ZMIANA NA LIMIT DLA OMINIĘCIA BŁĘDU 30029)
            if decision == "BUY" and rsi_val < 45 and usdc_balance >= 50:
                # Obliczamy cenę nieco wyższą, by zlecenie LIMIT weszło natychmiast
                buy_price = round(price * 1.001, 2) 
                amount_to_buy = round(50 / buy_price, 6)
                
                log_to_console(f"🛒 Próba zakupu {symbol} za 50 USDC (Cena Limit: {buy_price})...")
                try:
                    # Zamieniamy Market Buy na Limit Buy (lepsza akceptacja przez API MEXC)
                    mexc.create_order(pair, 'limit', 'buy', amount_to_buy, buy_price)
                    log_to_console(f"✅ SUKCES! Zlecenie LIMIT wysłane dla {symbol}")
                except Exception as e:
                    log_to_console(f"❌ BŁĄD TRANSAKCJI: {e}")

            elif decision == "SELL" and amt > 0 and rsi_val > 65:
                log_to_console(f"💸 Próba sprzedaży {symbol}...")
                try:
                    # Sprzedaż rynkowa zazwyczaj działa lepiej niż kupno, ale używamy safe-call
                    mexc.create_market_sell_order(pair, amt)
                    log_to_console(f"✅ Sprzedano {symbol}")
                except Exception as e:
                    log_to_console(f"❌ BŁĄD SPRZEDAŻY: {e}")

        # Aktualizacja stanu dla Dashboardu
        display_state = {"usdt": usdc_balance, "assets": assets_update, "total": current_total}
        
        # Zapis do historii
        history = []
        if os.path.exists(STATS_FILE):
            with open(STATS_FILE, 'r') as f: history = json.load(f)
        history.append({"timestamp": datetime.now().isoformat(), "balance": round(current_total, 2)})
        with open(STATS_FILE, 'w') as f: json.dump(history[-500:], f)
        
        log_to_console("✅ KONIEC CYKLU ANALIZY.")

    except Exception as e:
        log_to_console(f"❌ BŁĄD KRYTYCZNY: {e}")

# --- HARMONOGRAM ---
scheduler = BackgroundScheduler()
scheduler.add_job(func=run_loop, trigger="interval", minutes=2)
scheduler.start()

# --- PROSTY DASHBOARD ---
@app.route('/')
def home():
    uptime = f"{(datetime.now() - start_time).seconds // 60} min"
    return f"""
    <body style="background:#0b0e11; color:white; font-family:sans-serif; text-align:center; padding:50px;">
        <h1 style="color:#f3ba2f;">AI TRADER v7.0</h1>
        <p>Status: <span style="color:#0ecb81;">LIVE</span></p>
        <hr style="border:0.5px solid #2b3139; width:50%;">
        <h3>Saldo: {display_state.get('usdt', 0)} USDC</h3>
        <h3>Wartość portfela: {round(display_state.get('total', 0), 2)} USDC</h3>
        <p>Uptime: {uptime}</p>
        <p style="color:#848e9c;">Logi są dostępne w panelu Render.</p>
        <script>setTimeout(() => location.reload(), 30000);</script>
    </body>
    """

if __name__ == "__main__":
    run_loop() # Start pierwszej analizy
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 10000)))
