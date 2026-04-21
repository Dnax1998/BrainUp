import os
import time
import json
import ccxt
from groq import Groq
from flask import Flask, render_template_string
from apscheduler.schedulers.background import BackgroundScheduler

app = Flask('')

# Stan bota (pamięć tymczasowa)
state = {"usdt": 1000.0, "btc": 0.0, "total": 1000.0, "history": []}

# Inicjalizacja klienta Groq
client = Groq(api_key=os.getenv('GROQ_KEY'))

HTML_TEMPLATE = """
<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <title>AI Trader Pro | Groq Llama 3.1</title>
    <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css" rel="stylesheet">
    <style>
        body { background: #0b0e11; color: white; padding: 20px; font-family: sans-serif; }
        .stat-card { background: #1e2329; border: 1px solid #2b3139; border-radius: 12px; padding: 15px; text-align: center; }
        .history-item { background: #1e2329; border-left: 4px solid #00f2ff; margin-top: 10px; padding: 10px; border: 1px solid #2b3139; }
        .action-buy { color: #02c076; font-weight: bold; }
        .action-sell { color: #f84960; font-weight: bold; }
    </style>
</head>
<body>
    <div class="container">
        <h2 class="text-center mb-4" style="color: #00f2ff;">⚡ AI TRADER GROQ v2 (LIVE)</h2>
        
        <div class="row g-2">
            <div class="col-4"><div class="stat-card"><small class="text-secondary">USDT</small><h4>{{ usdt|round(2) }}</h4></div></div>
            <div class="col-4"><div class="stat-card"><small class="text-secondary">BTC</small><h4>{{ btc|round(6) }}</h4></div></div>
            <div class="col-4"><div class="stat-card"><small class="text-secondary">SUMA</small><h4 style="color:#02c076">{{ total|round(2) }}</h4></div></div>
        </div>

        <div class="mt-4">
            <h5>Dziennik Operacji (Autoodświeżanie 1min):</h5>
            {% for t in history[::-1][:20] %}
            <div class="history-item">
                <div class="d-flex justify-content-between">
                    <span class="badge bg-info text-dark">{{ t.action }}</span>
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
        // Strona odświeża widok co 5 sekund, żebyś widział postępy pracy w tle
        setTimeout(() => location.reload(), 5000);
    </script>
</body>
</html>
"""

def run_analysis():
    """Funkcja analizy rynkowej uruchamiana automatycznie w tle."""
    try:
        ex = ccxt.mexc()
        ticker = ex.fetch_ticker("BTC/USDT")
        price = ticker['last']
        
        # Zapytanie do modelu Llama 3.1
        chat_completion = client.chat.completions.create(
            messages=[{
                "role": "system",
                "content": "Jesteś ekspertem tradingu. Odpowiadasz tylko w formacie JSON."
            }, {
                "role": "user",
                "content": f"Cena BTC: {price}. Portfel: {state['usdt']} USDT, {state['btc']} BTC. KUP (BUY), SPRZEDAJ (SELL) czy CZEKAJ (WAIT)? JSON: {{\"decision\":\"...\", \"reason\":\"...\"}}"
            }],
            model="llama-3.1-8b-instant",
            response_format={"type": "json_object"}
        )
        
        ai_response = json.loads(chat_completion.choices[0].message.content)
        decision = ai_response.get('decision', 'WAIT').upper()
        reason = ai_response.get('reason', 'Brak powodu')

        # Logika transakcji
        if "BUY" in decision and state['usdt'] > 10:
            state['btc'] = state['usdt'] / price
            state['usdt'] = 0.0
            act_name = "KUPNO"
        elif "SELL" in decision and state['btc'] > 0.0001:
            state['usdt'] = state['btc'] * price
            state['btc'] = 0.0
            act_name = "SPRZEDAŻ"
        else:
            act_name = "CZEKANIE"

        state['total'] = state['usdt'] + (state['btc'] * price)
        state['history'].append({
            "time": time.strftime("%H:%M:%S"),
            "action": act_name,
            "price": price,
            "reason": reason
        })

        # Utrzymywanie historii na poziomie ostatnich 50 wpisów, by nie zapchać RAMu
        if len(state['history']) > 50:
            state['history'].pop(0)

    except Exception as e:
        print(f"Błąd w tle: {e}")

# Uruchomienie automatycznego sprawdzania ceny co 1 minutę
scheduler = BackgroundScheduler()
scheduler.add_job(func=run_analysis, trigger="interval", minutes=1)
scheduler.start()

@app.route('/')
def home():
    # Strona główna tylko wyświetla wyniki (analiza dzieje się w tle)
    return render_template_string(HTML_TEMPLATE, **state)

if __name__ == "__main__":
    port = int(os.environ.get('PORT', 10000))
    # use_reloader=False jest konieczne, żeby pętla w tle nie uruchomiła się dwa razy
    app.run(host='0.0.0.0', port=port, use_reloader=False)
