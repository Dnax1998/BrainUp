import os
import time
import json
import ccxt
from groq import Groq
from flask import Flask, render_template_string
from apscheduler.schedulers.background import BackgroundScheduler

app = Flask('')

# Stan bota (zwiększamy limit historii do 100, żeby widzieć więcej ruchów)
state = {"usdt": 1000.0, "btc": 0.0, "total": 1000.0, "history": []}

client = Groq(api_key=os.getenv('GROQ_KEY'))

HTML_TEMPLATE = """
<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <title>AI TRADER GROQ v2.2 | 20% Strategia</title>
    <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css" rel="stylesheet">
    <style>
        body { background: #0b0e11; color: white; padding: 20px; font-family: sans-serif; }
        .stat-card { background: #1e2329; border: 1px solid #2b3139; border-radius: 12px; padding: 15px; text-align: center; }
        .history-item { background: #1e2329; border-left: 4px solid #00f2ff; margin-top: 10px; padding: 10px; border: 1px solid #2b3139; }
        .action-KUPNO { border-left-color: #02c076; }
        .action-SPRZEDAŻ { border-left-color: #f84960; }
        .action-CZEKANIE { border-left-color: #707a8a; }
        .badge-KUPNO { background-color: #02c076; }
        .badge-SPRZEDAŻ { background-color: #f84960; }
        .badge-CZEKANIE { background-color: #474d57; }
    </style>
</head>
<body>
    <div class="container">
        <h2 class="text-center mb-4" style="color: #00f2ff;">⚡ AI TRADER - STRATEGIA 20%</h2>
        
        <div class="row g-2">
            <div class="col-4"><div class="stat-card"><small class="text-secondary">PORTFEL USDT</small><h4>{{ usdt|round(2) }}</h4></div></div>
            <div class="col-4"><div class="stat-card"><small class="text-secondary">STAN BTC</small><h4>{{ btc|round(6) }}</h4></div></div>
            <div class="col-4"><div class="stat-card"><small class="text-secondary">SUMA (WARTOŚĆ)</small><h4 style="color:#02c076">{{ total|round(2) }}</h4></div></div>
        </div>

        <div class="mt-4">
            <h5>Dziennik Operacji (Analiza 1min | Pakiety 20%):</h5>
            {% for t in history[::-1][:30] %}
            <div class="history-item action-{{ t.action }}">
                <div class="d-flex justify-content-between">
                    <span class="badge badge-{{ t.action }}">{{ t.action }}</span>
                    <span class="text-white-50 small">{{ t.time }}</span>
                </div>
                <div class="mt-2">
                    <strong>Cena BTC: {{ t.price }} USDT</strong><br>
                    <small class="text-secondary">{{ t.reason }}</small>
                </div>
            </div>
            {% endfor %}
        </div>
    </div>
    <script>
        setTimeout(() => location.reload(), 5000);
    </script>
</body>
</html>
"""

def run_analysis():
    try:
        ex = ccxt.mexc()
        ticker = ex.fetch_ticker("BTC/USDT")
        price = ticker['last']
        
        # PROMPT informujący o strategii 20%
        system_prompt = (
            "Jesteś ekspertem tradingu. Zarządzasz kapitałem dzieląc go na 5 części. "
            "Każda Twoja decyzja o KUPNIE (BUY) dotyczy 20% całkowitego kapitału początkowego (czyli 200 USDT). "
            "Możesz kupować wielokrotnie, jeśli uważasz, że cena spadła i warto dokupić. "
            "Decyzja SPRZEDAJ (SELL) oznacza sprzedaż CAŁEGO posiadanego BTC. "
            "Odpowiadaj TYLKO w JSON: {\"decision\": \"BUY/SELL/WAIT\", \"reason\": \"...\"}"
        )
        
        user_prompt = f"Cena BTC: {price} USDT. Masz: {state['usdt']} USDT i {state['btc']} BTC. Decyzja?"

        chat_completion = client.chat.completions.create(
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            model="llama-3.1-8b-instant",
            response_format={"type": "json_object"}
        )
        
        ai_response = json.loads(chat_completion.choices[0].message.content)
        decision = ai_response.get('decision', 'WAIT').upper()
        reason = ai_response.get('reason', '...')

        act_name = "CZEKANIE"
        amount_to_spend = 200.0  # Stała kwota 20% z początkowego 1000

        # LOGIKA KUPNA (pakiety 200 USDT)
        if "BUY" in decision and state['usdt'] >= amount_to_spend:
            btc_bought = amount_to_spend / price
            state['btc'] += btc_bought
            state['usdt'] -= amount_to_spend
            act_name = "KUPNO"
            reason = f"[PAKIET 20%] {reason}"
        
        # LOGIKA SPRZEDAŻY (całość BTC)
        elif "SELL" in decision and state['btc'] > 0:
            state['usdt'] += state['btc'] * price
            state['btc'] = 0.0
            act_name = "SPRZEDAŻ"
            reason = f"[CAŁOŚĆ] {reason}"

        state['total'] = state['usdt'] + (state['btc'] * price)
        state['history'].append({
            "time": time.strftime("%H:%M:%S"),
            "action": act_name,
            "price": price,
            "reason": reason
        })

        if len(state['history']) > 100:
            state['history'].pop(0)

    except Exception as e:
        print(f"Błąd: {e}")

scheduler = BackgroundScheduler()
scheduler.add_job(func=run_analysis, trigger="interval", minutes=1)
scheduler.start()

@app.route('/')
def home():
    return render_template_string(HTML_TEMPLATE, **state)

if __name__ == "__main__":
    port = int(os.environ.get('PORT', 10000))
    app.run(host='0.0.0.0', port=port, use_reloader=False)
