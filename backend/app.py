# app.py
import os
from flask import Flask
from flask_cors import CORS
from routes.medicoes import medicoes_bp
import mqtt.client

app = Flask(__name__)
CORS(app)

# Registrar as rotas
app.register_blueprint(medicoes_bp)

if __name__ == '__main__':
    port = int(os.getenv('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
