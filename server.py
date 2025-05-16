from flask import Flask, request, jsonify, send_from_directory
import mercadopago
import uuid
import sqlite3
import time
import os

app = Flask(__name__, static_folder='public')

DB_FILE = 'trade_simulator.db'

# Inicializa banco de dados e cria tabelas se não existirem
def init_db():
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()

    c.execute('''
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY,
            balance REAL DEFAULT 0
        )
    ''')
    c.execute('''
        CREATE TABLE IF NOT EXISTS bets (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            direction TEXT,
            amount REAL,
            timestamp INTEGER
        )
    ''')

    # Usuário único id=1
    c.execute('SELECT * FROM users WHERE id = 1')
    if c.fetchone() is None:
        c.execute('INSERT INTO users (id, balance) VALUES (1, 0)')

    conn.commit()
    conn.close()

init_db()

# SDK Mercado Pago com token direto (somente para testes!)
MP_TOKEN = "APP_USR-960048901481072-051515-493dbb1ec5bc6efb85383b9413065362-2439306283"
sdk = mercadopago.SDK(MP_TOKEN)

# Serve index.html e assets
@app.route('/')
def index():
    return send_from_directory('public', 'index.html')

@app.route('/<path:path>')
def static_files(path):
    return send_from_directory('public', path)

# Consultar saldo
@app.route('/saldo/<usuario_id>', methods=['GET'])
def get_saldo(usuario_id):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute('SELECT balance FROM users WHERE id = 1')
    saldo = c.fetchone()
    conn.close()
    return jsonify({'saldo': saldo[0] if saldo else 0})

# Registrar aposta
@app.route('/bet', methods=['POST'])
def bet():
    data = request.json
    direction = data.get('direction')
    amount = float(data.get('amount'))

    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute('SELECT balance FROM users WHERE id = 1')
    saldo = c.fetchone()[0]

    if amount > saldo:
        conn.close()
        return jsonify({'error': 'Saldo insuficiente'}), 400

    c.execute('UPDATE users SET balance = balance - ? WHERE id = 1', (amount,))
    timestamp = int(time.time())
    c.execute('INSERT INTO bets (direction, amount, timestamp) VALUES (?, ?, ?)',
              (direction, amount, timestamp))
    conn.commit()
    conn.close()

    return jsonify({'message': 'Aposta registrada', 'balance': saldo - amount})

# Criar pagamento via PIX
@app.route('/criar_pix', methods=['POST'])
def criar_pix():
    data = request.json
    try:
        valor = float(data['valor'])
    except:
        return jsonify({'erro': 'Valor inválido'}), 400

    txid = str(uuid.uuid4())
    payment_data = {
        "transaction_amount": valor,
        "description": "Depósito para usuário 1",
        "payment_method_id": "pix",
        "payer": {
            "email": "usuario@exemplo.com",
            "first_name": "Usuário",
            "last_name": "Simulador"
        },
        "external_reference": f"1|{txid}"
    }

    try:
        response = sdk.payment().create(payment_data)["response"]
        qr_code = response["point_of_interaction"]["transaction_data"]["qr_code_base64"]
        return jsonify({
            "qr_code_base64": qr_code,
            "txid": txid
        })
    except KeyError:
        print("Erro: Resposta inesperada do Mercado Pago:", response)
        return jsonify({
            'erro': 'Erro ao gerar QR Code. Verifique se o PIX está ativo na sua conta Mercado Pago.'
        }), 500

# Webhook de pagamento
@app.route('/webhook_pix', methods=['POST'])
def webhook_pix():
    data = request.json
    print("WEBHOOK DATA:", data)  # <-- Adicione isso
    if data.get("type") == "payment":
        payment_id = data["data"]["id"]
        payment_info = sdk.payment().get(payment_id)["response"]

        if payment_info["status"] == "approved":
            external_ref = payment_info.get("external_reference", "")
            if "|" not in external_ref:
                return "OK", 200

            usuario_id_str, txid = external_ref.split("|")
            try:
                usuario_id = int(usuario_id_str)
                valor = float(payment_info["transaction_amount"])
            except:
                return "OK", 200

            conn = sqlite3.connect(DB_FILE)
            c = conn.cursor()
            c.execute("UPDATE users SET balance = balance + ? WHERE id = ?", (valor, usuario_id))
            conn.commit()
            conn.close()

            print(f"[PIX] Depósito de R${valor:.2f} confirmado para usuário {usuario_id}")

    return "OK", 200

# Solicitar saque
@app.route('/sacar', methods=['POST'])
def sacar():
    data = request.json
    valor = float(data.get('valor', 0))

    if valor <= 0:
        return jsonify({'erro': 'Valor inválido'}), 400

    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute('SELECT balance FROM users WHERE id = 1')
    saldo = c.fetchone()[0]

    if valor > saldo:
        conn.close()
        return jsonify({'erro': 'Saldo insuficiente'}), 400

    c.execute('UPDATE users SET balance = balance - ? WHERE id = 1', (valor,))
    conn.commit()
    conn.close()

    return jsonify({'mensagem': 'Saque solicitado, finalize o pagamento manualmente.'})

if __name__ == '__main__':
    app.run(debug=True, port=5000)
