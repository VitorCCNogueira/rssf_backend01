#include <Arduino.h>
#include <esp_system.h>
#include <esp_sleep.h>
#include <LoRa_E220.h>
#include <OneWire.h>
#include <DallasTemperature.h>

#define SAMPLE_TIME     1800000 // 30 min em ms (o deep sleep multiplica por 1000)
#define TX_PIN          16
#define RX_PIN          17
#define AUX_PIN         22
#define M1_PIN          4
#define M0_PIN          19
#define ONE_WIRE_BUS    15

#define CHANNEL         0x0F

#define BUFFER_SIZE 16

// Ensaio de laboratorio: envio inicial e, depois, lotes de 16 ciclos.

// variáveis para definir endereço do nó sensor
uint16_t NODE_ADDRESS;
uint8_t mac[6];

// --- ENDEREÇOS DOS SENSORES ---
DeviceAddress sensores[] = {
  { 0x28, 0x45, 0x42, 0x87, 0x00, 0x1B, 0x08, 0xB8 }, // S1
  { 0x28, 0x2D, 0x45, 0x87, 0x00, 0x0C, 0x38, 0xB7 }, // S2
  { 0x28, 0xAB, 0x8B, 0x87, 0x00, 0xC5, 0x7B, 0xCD }, // S3
  { 0x28, 0xDC, 0x95, 0x87, 0x00, 0x94, 0x66, 0xDD }, // S4
  { 0x28, 0xFA, 0x2A, 0x87, 0x00, 0x1E, 0x19, 0x88 }, // S5
  { 0x28, 0x74, 0x24, 0x87, 0x00, 0x9D, 0x66, 0x10 }  // S6
};


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

// declaracao em memoria RTC - resistente ao deepsleep
RTC_DATA_ATTR Packet packet;

OneWire oneWire(ONE_WIRE_BUS);
DallasTemperature sensors(&oneWire);

// Primeiro parametro e o pino ligado ao TX do modulo (RX do ESP32); inverter
// os dois faz a UART funcionar so num sentido.
LoRa_E220 e220((byte)TX_PIN, (byte)RX_PIN, &Serial2, (byte)AUX_PIN, (byte)M0_PIN, (byte)M1_PIN, UART_BPS_RATE_9600, SERIAL_8N1);

// Sucesso aqui confirma somente a operacao local do radio, nao o POST HTTP.
bool transmitPacket() {
  if (!e220.begin()) {
    Serial.println("[TX] Falha ao iniciar E220.");
    return false;
  }
  delay(300);
  unsigned long auxWaitStart = millis();
  while (digitalRead(AUX_PIN) == LOW && millis() - auxWaitStart < 1000) delay(5);
  if (digitalRead(AUX_PIN) == LOW) {
    Serial.println("[TX] E220 ocupado: envio cancelado.");
    return false;
  }
  delay(50);
  ResponseStructContainer c = e220.getConfiguration();
  if (c.status.code != E220_SUCCESS || c.data == nullptr) {
    Serial.println("[TX] Falha ao ler configuracao E220.");
    c.close();
    return false;
  }
  Configuration configuration = *(Configuration*)c.data;
  c.close();
  byte wantAddH = NODE_ADDRESS >> 8;
  byte wantAddL = NODE_ADDRESS & 0xFF;
  if (configuration.CHAN != CHANNEL || configuration.ADDH != wantAddH
      || configuration.ADDL != wantAddL
      || configuration.TRANSMISSION_MODE.fixedTransmission != FT_FIXED_TRANSMISSION
      || configuration.TRANSMISSION_MODE.enableRSSI != RSSI_ENABLED) {
    configuration.ADDH = wantAddH;
    configuration.ADDL = wantAddL;
    configuration.CHAN = CHANNEL;
    configuration.TRANSMISSION_MODE.fixedTransmission = FT_FIXED_TRANSMISSION;
    configuration.TRANSMISSION_MODE.enableRSSI = RSSI_ENABLED;
    ResponseStatus configResult = e220.setConfiguration(configuration, WRITE_CFG_PWR_DWN_SAVE);
    if (configResult.code != E220_SUCCESS) {
      Serial.println("[TX] Falha ao gravar configuracao E220.");
      return false;
    }
  }
  e220.setMode(MODE_0_NORMAL);
  ResponseStatus result = e220.sendFixedMessage(
      BROADCAST_ADDRESS, BROADCAST_ADDRESS, CHANNEL, &packet, sizeof(Packet));
  Serial.printf("[TX] Resultado local: %s; confira HTTP 201 no receptor e o dashboard.\n",
                result.getResponseDescription().c_str());
  return result.code == E220_SUCCESS;
}

void setup() {
  Serial.begin(115200);
  const bool startup = esp_reset_reason() != ESP_RST_DEEPSLEEP;
  // Reinicio interrompe o ensaio: descarte RTC antigo para nao atribuir idades falsas.
  if (startup || packet.qntd_medicoes >= BUFFER_SIZE) packet = {};

  // atribuição de endereço para o nó sensor via endereço MAC
  uint64_t chipmac = ESP.getEfuseMac();
  for (int i = 0; i < 6; i++) mac[i] = (chipmac >> (8 * i)) & 0xFF;

  NODE_ADDRESS = ((uint16_t)mac[4] << 8) | mac[5];
  if (NODE_ADDRESS == 0xFFFF) NODE_ADDRESS = 0xFFFE; // proteção contra envio broadcast
  if (NODE_ADDRESS == 0x0000) NODE_ADDRESS = 0x0001; // proteção contra possíveis erros de leitura
  packet.senderAddress = NODE_ADDRESS;
  
  sensors.begin();

  // Coleta de dados dos 6 sensores DS18B20
  sensors.requestTemperatures();

  
  if(packet.qntd_medicoes >= BUFFER_SIZE){
    // nada ocorre, nao devem ser armazenados mais do que 16 subpacotes no pacote 
  }
  else{
    for(int i = 0; i < 6; i++) {
      packet.subpacket[packet.qntd_medicoes].digTemperature[i] = sensors.getTemp(sensores[i]);
    }
    packet.qntd_medicoes++;
  }

  if (startup || packet.qntd_medicoes == BUFFER_SIZE) {
    Serial.printf("[TX] %s | senderAddress=%u | medicoes=%u\n",
                  startup ? "INICIAL" : "LOTE", NODE_ADDRESS, packet.qntd_medicoes);
    const bool sent = transmitPacket();
    if (!sent) Serial.println("[TX] Sem confirmacao local. Ligue o receptor e reinicie para testar novamente.");
    // Sem ACK/retry no protocolo atual. Nao reenvie amostras antigas como idade zero.
    packet.qntd_medicoes = 0;
    e220.setMode(MODE_3_SLEEP);
  }
  Serial.flush();

  esp_sleep_enable_timer_wakeup((uint64_t)SAMPLE_TIME * 1000ULL);
  esp_deep_sleep_start();
}

void loop() {
  // O código não chega aqui devido ao Deep Sleep
}
