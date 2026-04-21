import os
import time
import json
import ccxt
from groq import Groq
from flask import Flask, render_template_string

app = Flask('')

# Stan bota
state = {"usdt": 1000.0, "btc": 0.0, "total": 1000.0, "history": []}

# Inicjalizacja klienta Groq
# Pamiętaj, aby na Renderze w Environment dodać zmienną GROQ_KEY
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
        .action-wait { color: #848e9c; }
    </style>
</head>
<body>
    <div class="container">
        <h2 class="text-center mb-4" style="color: #00f2ff;">⚡ AI TRADER GROQ v2</h2>
        
        <div class="row g-2">
            <div class="col-4">
                <div class="stat-card">
                    <small class="text-secondary">PORTFEL USDT</small>
                    <h4>{{ usdt|round(2) }}</h4>
                </div>
            </div>
            <div class="col-4">
                <div class="stat-card">
                    <small class="text-secondary">STAN BTC</small>
                    <h4>{{ btc|round(6) }}</h4>
                </div>
            </div>
            <div class="col-4">
                <div class="stat-card">
                    <small class="text-secondary">SUMA (USDT)</small>
                    <h4 style="color:#02c076">{{ total|round(2) }}</h4>
                </div>
            </div>
        </div>

        <div class="mt-4">
            <h5>Dziennik Operacji:</h5>
            {% if not history %}
                <p class="text-secondary">Czekam na pierwszą analizę...</p>
            {% endif %}
            {% for t in history[::-1] %}
            <div class="history-item">
                <div class="d-flex justify-content-between">
                    <span class="badge bg-info text-dark">{{ t.action }}</span>
                    <span class="text-white-50 small">{{ t.time }}</span>
                </div>
                <div class="mt-2">
                    <strong>Cena BTC: {{ t.price }} USDT</strong><br>
                    <small class="text-secondary">Powód: {{ t.reason }}</small>
                </div>
            </div>
            {% endfor %}
        </div>
    </div>
    <script>
        // Odświeżaj stronę co 30 sekund, aby zobaczyć nowe decyzje
        setTimeout(() => location.reload(), 30000);
    </script>
</body>
</html>
"""

def run_analysis():
    try:
        # 1. Pobierz cenę z giełdy MEXC
        ex = ccxt.mexc()
        ticker = ex.fetch_ticker("BTC/USDT")
        price = ticker['last']
        
        # 2. Wyślij zapytanie do Groq (używając Llama 3.1)
        # Model llama-3.1-8b-instant zastępuje wycofany model llama3-8b-8192
        chat_completion = client.chat.completions.create(
            messages=[{
                "role": "system",
                "content": "Jesteś ekspertem tradingu. Odpowiadasz tylko w formacie JSON."
            }, {
                "role": "user",
                "content": f"Aktualna cena BTC: {price} USDT. Masz w portfelu: {state['usdt']} USDT i {state['btc']} BTC. Czy powiniem KUPIC (BUY), SPRZEDAC (SELL) czy CZEKAC (WAIT)? Odpisz TYLKO JSON: {{\"decision\":\"BUY/SELL/WAIT\", \"reason\":\"krótkie uzasadnienie\"}}"
            }],
            model="llama-3.1-8b-instant",
            response_format={"type": "json_object"}
        )
        
        # 3. Przetwórz odpowiedź AI
        ai_response = json.loads(chat_completion.choices[0].message.content)
        decision = ai_response.get('decision', 'WAIT').upper()
        reason = ai_response.get('reason', 'Brak uzasadnienia')

        # 4. Wykonaj wirtualną transakcję
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

        # 5. Aktualizuj stan i historię
        state['total'] = state['usdt'] + (state['btc'] * price)
        state['history'].append({
            "time": time.strftime("%H:%M:%S"),
            "action": act_name,
            "price": price,
            "reason": reason
        })

    except Exception as e:
        state['history'].append({
            "time": time.strftime("%H:%M:%S"),
            "action": "BŁĄD SYSTEMU",
            "price": 0,
            "reason": str(e)
        })

@app.route('/')
def home():
    run_analysis()
    return render_template_string(HTML_TEMPLATE, **state)

if __name__ == "__main__":
    # Render używa zmiennej środowiskowej PORT
    port = int(os.environ.get('PORT', 10000))
    app.run(host='0.0.0.0', port=port)
