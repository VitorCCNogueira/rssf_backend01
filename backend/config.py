import os
from dotenv import load_dotenv

load_dotenv()

DEFAULT_GATEWAY_ID = os.getenv('DEFAULT_GATEWAY_ID', 'gateway_unknown')

DB_CONFIG = {
    'host':     os.getenv('MYSQLHOST'),
    'user':     os.getenv('MYSQLUSER'),
    'password': os.getenv('MYSQLPASSWORD'),
    'database': os.getenv('MYSQLDATABASE'),
    'port':     int(os.getenv('MYSQLPORT', 3306)),
    'use_pure': True
}

SERVER_HOST = '0.0.0.0'
SERVER_PORT = int(os.getenv('PORT', 5000))

# Buffer E220: 16 amostras a cada 30 minutos; tolerancia de 1h no status.
STATUS_ONLINE_MINUTES = int(os.getenv('STATUS_ONLINE_MINUTES', 540))
STATUS_OFFLINE_MINUTES = int(os.getenv('STATUS_OFFLINE_MINUTES', 1440))
if not 0 < STATUS_ONLINE_MINUTES < STATUS_OFFLINE_MINUTES:
    raise ValueError('Status exige 0 < STATUS_ONLINE_MINUTES < STATUS_OFFLINE_MINUTES')
