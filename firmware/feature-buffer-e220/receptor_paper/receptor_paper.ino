#include <Arduino.h>

#include <LoRa_E220.h>
#include <WiFi.h>
#include <HTTPClient.h>
#include <ArduinoJson.h>

// Pinagem da PCB RSSF r0.3. Primeiro argumento da biblioteca = ESP32 RX
// ligado ao TXD do E220; segundo = ESP32 TX ligado ao RXD do E220.
#define RADIO_TXD_ESP_RX_PIN 17
#define RADIO_RXD_ESP_TX_PIN 16
#define AUX_PIN 5
#define M0_PIN 2
#define M1_PIN 4

#define BUFFER_SIZE 16

// Deve ser identico a LAB_GATEWAY_ID no backend.
const char* LAB_GATEWAY_ID = "gateway_lab_01";

// Precisa bater com o CHANNEL do transmissor: ele retuna pra esse canal so
// durante o envio (sendFixedMessage), entao o receptor tem que estar
// escutando nele - nao basta usar a config default/residual do modulo.
#define CHANNEL 0x0F

// estrutura dos subpacotes
struct __attribute__((__packed__)) SubPacket{
  int16_t digTemperature[6];
};

// estrutura do pacote principal
struct __attribute__((__packed__)) Packet {
  uint16_t senderAddress;
  uint8_t qntd_medicoes;
  SubPacket subpacket[BUFFER_SIZE];
};

LoRa_E220 e220((byte)RADIO_TXD_ESP_RX_PIN, (byte)RADIO_RXD_ESP_TX_PIN,
                 &Serial2, (byte)AUX_PIN, (byte)M0_PIN, (byte)M1_PIN,
                 UART_BPS_RATE_9600, SERIAL_8N1);
const char* serverURL = "https://rssf-production.up.railway.app/api/salvar_dados";

void setup() {
  Serial.begin(115200);
  WiFi.begin("LSP-UEMA", "Asfaltosolos123");
  while (WiFi.status() != WL_CONNECTED) delay(500);

  Serial.println("[DEBUG] setup() iniciou");

  bool beginOk = e220.begin();
  Serial.printf("[DEBUG] e220.begin() = %s\n", beginOk ? "OK" : "FALHOU");

  // Grava o canal no modulo em vez de confiar no que ja estava salvo nele
  ResponseStructContainer c = e220.getConfiguration();
  Serial.printf("[DEBUG] getConfiguration() status = %s\n", c.status.getResponseDescription().c_str());
  Configuration configuration = *(Configuration*)c.data;
  Serial.printf("[DEBUG] canal atual = %d (esperado %d) | ADDH=%d ADDL=%d (esperado %d/%d, broadcast) | AirDataRate=%s\n",
                configuration.CHAN, CHANNEL, configuration.ADDH, configuration.ADDL, BROADCAST_ADDRESS, BROADCAST_ADDRESS,
                configuration.SPED.getAirDataRateDescription().c_str());
  // O transmissor manda em broadcast (sendFixedMessage com BROADCAST_ADDRESS),
  // entao o receptor so recebe se o proprio endereco dele tambem for broadcast -
  // senao o modulo filtra e descarta o pacote mesmo estando no canal certo.
  if (configuration.CHAN != CHANNEL || configuration.ADDH != BROADCAST_ADDRESS || configuration.ADDL != BROADCAST_ADDRESS) {
    configuration.CHAN = CHANNEL;
    configuration.ADDH = BROADCAST_ADDRESS;
    configuration.ADDL = BROADCAST_ADDRESS;
    ResponseStatus rs = e220.setConfiguration(configuration, WRITE_CFG_PWR_DWN_SAVE);
    Serial.printf("[DEBUG] setConfiguration() status = %s\n", rs.getResponseDescription().c_str());
  } else {
    Serial.println("[DEBUG] canal e endereco ja estavam corretos, nao precisou regravar");
  }
  c.close();

  // Receptor alimentado pela rede: escuta continua dispensa o duty-cycle do WOR
  e220.setMode(MODE_0_NORMAL);
  Serial.println("[DEBUG] setup() concluido, modo NORMAL ativado, aguardando pacotes...");
}

void loop() {
  if (e220.available() > 0) {
    ResponseStructContainer rc = e220.receiveMessageRSSI(sizeof(Packet));
    if (rc.status.code == E220_SUCCESS) {
      Packet packet = *(Packet*)rc.data;
      float rssi = (120.0 / 255.0) * rc.rssi - 120.0;

      Serial.printf("[RX] Pacote recebido: no=%u, medicoes=%u\n", packet.senderAddress, packet.qntd_medicoes);

      // JsonDocument (ArduinoJson v7) cresce sob demanda: 16 medicoes x 6 temperaturas
      // nao cabem nos 512 bytes do StaticJsonDocument antigo
      JsonDocument doc;
      doc["senderAddress"] = packet.senderAddress;
      doc["gateway_id"] = LAB_GATEWAY_ID;
      doc["rssi"] = rssi;

      // Intervalo entre medicoes no transmissor (SAMPLE_TIME = 30 min)
      const int INTERVALO_MIN = 30;

      // Nunca le alem do vetor, mesmo que qntd_medicoes chegue corrompido
      int qntd = packet.qntd_medicoes;
      if (qntd < 1 || qntd > BUFFER_SIZE) {
        Serial.println("[RX] Quantidade invalida; pacote descartado.");
        rc.close();
        return;
      }

      // Tratamento de dados da temperatura - no pacote, a temperatura vem como int16_t, representada
      // em quantidades de frações de 1/128 graus Celsius
      JsonArray medicoes = doc["medicoes"].to<JsonArray>();
      for (int j = 0; j < qntd; j++) {
        JsonObject m = medicoes.add<JsonObject>();
        // medicao j foi feita (qntd-1-j) ciclos antes da chegada do pacote
        m["idade_min"] = (qntd - 1 - j) * INTERVALO_MIN;
        for (int i = 0; i < 6; i++) {
          String key = "temp_ds" + String(i + 1);
          m[key] = packet.subpacket[j].digTemperature[i] / 128.0f;
        }
      }

      HTTPClient http;
      http.begin(serverURL);
      http.addHeader("Content-Type", "application/json");

      String json;
      serializeJson(doc, json);
      int httpCode = http.POST(json);

      Serial.printf("[HTTP] no=%u gateway=%s medicoes=%d status=%d\n",
                    packet.senderAddress, LAB_GATEWAY_ID, qntd, httpCode);
      if (httpCode == 201) {
        Serial.println("[HTTP] Gravacao confirmada pelo backend. Confira o ponto no dashboard.");
      } else {
        Serial.println("[HTTP] Sem confirmacao de gravacao. Confira rede, LAB_SENSOR_ID e LAB_GATEWAY_ID.");
        if (httpCode > 0) Serial.println(http.getString());
      }
      http.end();
    }
    rc.close();
  }
}
