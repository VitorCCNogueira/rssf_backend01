import paho.mqtt.client as mqtt
import logging 
import json
import queue #evita problemas em caso de tráfego lento
import threading
from models.medicao import MedicaoModel

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

def on_connect(client, userdata, flags, reason_code, properties): #conexao com o mqtt
    if reason_code == 0:
        logging.info(f"Conexão bem-estabelecida: {reason_code}")
        client.subscribe("rssf/#") # entra em todos os tópicos
    else:
        logging.error(f"Erro ao conectar. Codigo: {reason_code}")

def on_subscribe(client, userdata, mid, reason_code_list, properties): #inscricao no topico
    if reason_code_list[0].is_failure:
        logging.error(f"Broker não aceitou a inscrição: {reason_code_list[0]}")
    else:
        logging.info(f"Broker informou o seguinte QoS: {reason_code_list[0].value}")


fila = queue.Queue(maxsize=2000) #nao comecei com ele

def on_worker():
    while True:
        gateway_id, dados = fila.get()
        try:
            MedicaoModel.salvar_lote(dados,gateway_id)
            logging.info(f"{len(dados['medicoes'])} medições de {gateway_id} gravadas")
        except Exception:
            logging.exception(f"Falha ao gravar dados de {gateway_id}")
        finally:
            fila.task_done()

def on_message(client, userdata, msg): #mensagens recebidas pelo mqtt
    try:
        payload = msg.payload.decode('utf-8')

        partes = msg.topic.split('/')
        gateway_id,tipo = partes[1], partes[2]

        if tipo == "status":
            logging.info(f"Status de {gateway_id}: {payload}")
            return

        if tipo != "telemetria":
            logging.info(f"Tópico ignorado: {msg.topic}")
            return
        
        dados = json.loads(payload)
        gateway_id = dados.get('gateway_id') or gateway_id
        fila.put_nowait((gateway_id,dados))

    except UnicodeDecodeError:
        logging.error("Falha ao decodificar: Payload não é UTF-8.")
    except json.JSONDecodeError:
        logging.error(f"Falha de JSON: O conteúdo não é um JSON válido. Payload: {payload}")
    except queue.Full:
        logging.error(f"Fila cheia: pacote de {gateway_id} descartado")
    except Exception:
        logging.exception(f"Falha inesperada ao processar o tópico {msg.topic}")
    
def iniciar_worker():
    threading.Thread(target=on_worker, daemon=True).start() #faz funcionar em paralelo