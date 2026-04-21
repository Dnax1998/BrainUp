import os
import time
import json
import ccxt
from groq import Groq
from flask import Flask, render_template_string
from apscheduler.schedulers.background import BackgroundScheduler

app = Flask('')

# Stan bota (pamięć tymczasowa - zresetuje się po wdrożeniu)
state = {"usdt": 1000.0, "btc": 0.0, "total": 1000.0, "history": []}

# Inicjalizacja klienta Groq
client = Groq(api_key=os.getenv('GROQ_KEY'))

HTML_TEMPLATE = """
<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <title>AI TRADER GROQ v2 (AGRESYWNY)</title>
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
        <h2 class="text-center mb-4" style="color: #00f2ff;">⚡ AI TRADER AGRESSIVE v2.1</h2>
        
        <div class="row g-2">
            <div class="col-4"><div class="stat-card"><small class="text-secondary">USDT</small><h4>{{ usdt|round(2) }}</h4></div></div>
            <div class="col-4"><div class="stat-card"><small class="text-secondary">BTC</small><h4>{{ btc|round(6) }}</h4></div></div>
            <div class="col-4"><div class="stat-card"><small class="text-secondary">SUMA</small><h4 style="color:#02c076">{{ total|round(2) }}</h4></div></div>
        </div>

        <div class="mt-4">
            <h5>Dziennik Operacji (Analiza co 1min):</h5>
            {% for t in history[::-1][:20] %}
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
        
        # AGRESYWNY PROMPT - wymusza handel na małym kapitale
        system_prompt = (
            "Jesteś agresywnym ekspertem day-tradingu. Ignoruj zasady o dużym kapitale. "
            "Twoim celem jest pomnażanie 1000 USDT. Masz zawsze grać CAŁOŚCIĄ portfela (ALL-IN). "
            "Odpowiadaj WYŁĄCZNIE w formacie JSON: {\"decision\": \"BUY/SELL/WAIT\", \"reason\": \"krótki powód\"}"
        )
        
        user_prompt = f"Cena BTC: {price} USDT. Portfel: {state['usdt']} USDT, {state['btc']} BTC. Decyzja?"

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
        reason = ai_response.get('reason', 'Analiza rynkowa...')

        act_name = "CZEKANIE"

        # Logika KUPNA (tylko jeśli mamy USDT)
        if "BUY" in decision and state['usdt'] > 5:
            state['btc'] = state['usdt'] / price
            state['usdt'] = 0.0
            act_name = "KUPNO"
        
        # Logika SPRZEDAŻY (tylko jeśli mamy BTC)
        elif "SELL" in decision and state['btc'] > 0.0001:
            state['usdt'] = state['btc'] * price
            state['btc'] = 0.0
            act_name = "SPRZEDAŻ"

        state['total'] = state['usdt'] + (state['btc'] * price)
        state['history'].append({
            "time": time.strftime("%H:%M:%S"),
            "action": act_name,
            "price": price,
            "reason": reason
        })

        if len(state['history']) > 50:
            state['history'].pop(0)

    except Exception as e:
        print(f"Błąd: {e}")

# Scheduler - sprawdza cenę co 1 minutę
scheduler = BackgroundScheduler()
scheduler.add_job(func=run_analysis, trigger="interval", minutes=1)
scheduler.start()

@app.route('/')
def home():
    return render_template_string(HTML_TEMPLATE, **state)

if __name__ == "__main__":
    port = int(os.environ.get('PORT', 10000))
    app.run(host='0.0.0.0', port=port, use_reloader=False)
