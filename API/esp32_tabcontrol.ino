/*
  TabControl - firmware do leitor RFID (ESP32 + PN532)
  Equipe Brokers - Implementacao de Negocios Inovadores

  O que faz: le o UID de cracha/tag, envia ao servidor (POST /api/leitura) e mostra
  o resultado em LED e buzzer. Quem decide se e retirada, devolucao ou negado e o
  SERVIDOR - o ESP32 so le e informa.

  ATENCAO: este codigo NAO foi testado em hardware (foi escrito sem acesso ao ESP32).
  Teste primeiro na bancada (Fase 0) e ajuste os pinos se necessario.

  Bibliotecas (Arduino IDE > Gerenciar Bibliotecas):
    - "Adafruit PN532"   (instala junto a Adafruit BusIO)
    - "ArduinoJson"      (Benoit Blanchon, versao 7.x)
  Placa: "ESP32 Dev Module" (pacote "esp32" da Espressif).

  Ligacao (PN532 em modo I2C - confira as chaves/DIP do modulo: SEL0=ON, SEL1=OFF):
    PN532 SDA -> GPIO 21        PN532 SCL -> GPIO 22
    PN532 IRQ -> GPIO 4         PN532 RSTO/RESET -> GPIO 5
    PN532 VCC -> 3V3 (ou 5V conforme o modulo)   GND -> GND
    LED verde   -> GPIO 26 (com resistor 220R)   LED vermelho -> GPIO 27 (com resistor 220R)
    Buzzer      -> GPIO 25
*/

#include <WiFi.h>
#include <HTTPClient.h>
#include <Wire.h>
#include <Adafruit_PN532.h>
#include <ArduinoJson.h>

// ======================= CONFIGURE AQUI =======================
const char* WIFI_SSID    = "NOME_DA_REDE";
const char* WIFI_SENHA   = "SENHA_DA_REDE";            // WPA2 pessoal. Rede corporativa (802.1X) exige outro codigo.
const char* SERVIDOR_URL = "http://192.168.0.10:8000"; // IP que o Servidor.py mostra ao iniciar
const char* API_KEY      = "COLE_AQUI_A_CHAVE_DO_.env"; // = TABCONTROL_API_KEY
const char* DISPOSITIVO  = "armario-01";               // nome deste leitor (aparece no painel)
// ==============================================================

const int PIN_PN532_IRQ   = 4;
const int PIN_PN532_RESET = 5;
const int PIN_LED_VERDE   = 26;
const int PIN_LED_VERMELHO = 27;
const int PIN_BUZZER      = 25;

const unsigned long INTERVALO_PING_MS    = 30000;  // sinal de vida para o painel
const unsigned long REPETICAO_LOCAL_MS   = 2000;   // ignora a mesma tag lida de novo em menos de 2 s
const int           TENTATIVAS_ENVIO     = 3;

Adafruit_PN532 nfc(PIN_PN532_IRQ, PIN_PN532_RESET);

unsigned long ultimoPing = 0;
unsigned long ultimaLeitura = 0;
String ultimoUid = "";

// ---------------------- sinais (LED / buzzer) ----------------------
void bip(int ms) {
  digitalWrite(PIN_BUZZER, HIGH);
  delay(ms);
  digitalWrite(PIN_BUZZER, LOW);
}

void sinalSucesso() {          // retirada / devolucao: verde fixo + 2 bipes curtos
  digitalWrite(PIN_LED_VERDE, HIGH);
  bip(120); delay(100); bip(120);
  delay(700);
  digitalWrite(PIN_LED_VERDE, LOW);
}

void sinalAguardando() {       // cracha aceito, aguardando a tag do tablet: verde piscando + 1 bipe
  bip(100);
  for (int i = 0; i < 3; i++) {
    digitalWrite(PIN_LED_VERDE, HIGH); delay(150);
    digitalWrite(PIN_LED_VERDE, LOW);  delay(150);
  }
}

void sinalNegado() {           // negado / tag desconhecida: vermelho fixo + bipe longo
  digitalWrite(PIN_LED_VERMELHO, HIGH);
  bip(600);
  delay(400);
  digitalWrite(PIN_LED_VERMELHO, LOW);
}

void sinalErroRede() {         // sem comunicacao com o servidor: vermelho piscando 3x
  for (int i = 0; i < 3; i++) {
    digitalWrite(PIN_LED_VERMELHO, HIGH); bip(80);
    digitalWrite(PIN_LED_VERMELHO, LOW);  delay(150);
  }
}

// ---------------------- Wi-Fi ----------------------
bool garantirWifi() {
  if (WiFi.status() == WL_CONNECTED) return true;
  Serial.println("Conectando ao Wi-Fi...");
  WiFi.mode(WIFI_STA);
  WiFi.begin(WIFI_SSID, WIFI_SENHA);
  unsigned long inicio = millis();
  while (WiFi.status() != WL_CONNECTED && millis() - inicio < 10000) {
    delay(250);
  }
  if (WiFi.status() == WL_CONNECTED) {
    Serial.print("Wi-Fi OK. IP: ");
    Serial.println(WiFi.localIP());
    return true;
  }
  Serial.println("Falha no Wi-Fi.");
  return false;
}

// ---------------------- HTTP ----------------------
// Retorna o codigo HTTP (0 se nao conseguiu falar com o servidor) e preenche 'resposta'.
int postar(const String& rota, const String& corpo, String& resposta) {
  if (!garantirWifi()) return 0;
  HTTPClient http;
  http.setTimeout(4000);
  http.begin(String(SERVIDOR_URL) + rota);
  http.addHeader("Content-Type", "application/json");
  http.addHeader("X-API-Key", API_KEY);
  int codigo = http.POST(corpo);
  if (codigo > 0) resposta = http.getString();
  http.end();
  return codigo;
}

void enviarPing() {
  String resp;
  String corpo = String("{\"dispositivo\":\"") + DISPOSITIVO + "\"}";
  int codigo = postar("/api/ping", corpo, resp);
  Serial.printf("ping -> %d\n", codigo);
}

void enviarLeitura(const String& uid) {
  String corpo = String("{\"dispositivo\":\"") + DISPOSITIVO + "\",\"uid\":\"" + uid + "\"}";
  String resp;
  int codigo = 0;
  // Tenta ate 3 vezes. Se o servidor ja processou e so a resposta se perdeu, a nova
  // tentativa volta como "ignorada" (o servidor ignora a mesma tag em poucos segundos).
  for (int t = 1; t <= TENTATIVAS_ENVIO; t++) {
    codigo = postar("/api/leitura", corpo, resp);
    if (codigo == 200) break;
    if (codigo == 401) break;                      // chave errada: repetir nao adianta
    Serial.printf("tentativa %d falhou (%d)\n", t, codigo);
    delay(800);
  }

  if (codigo == 401) {
    Serial.println("Servidor recusou a chave (API_KEY errada).");
    sinalNegado();
    return;
  }
  if (codigo != 200) {
    Serial.println("Sem resposta do servidor. Leitura NAO registrada.");
    sinalErroRede();
    return;
  }

  JsonDocument doc;
  if (deserializeJson(doc, resp)) {
    Serial.println("Resposta invalida do servidor.");
    sinalErroRede();
    return;
  }
  const char* acao = doc["acao"] | "";
  const char* msg  = doc["msg"]  | "";
  Serial.printf("%s | %s\n", acao, msg);

  if (strcmp(acao, "aguardando_tablet") == 0)                          sinalAguardando();
  else if (strcmp(acao, "retirada") == 0 || strcmp(acao, "devolucao") == 0) sinalSucesso();
  else if (strcmp(acao, "ignorada") == 0)                              { /* repeticao: sem sinal */ }
  else                                                                 sinalNegado();
}

// ---------------------- setup / loop ----------------------
String uidParaTexto(uint8_t* uid, uint8_t tamanho) {
  String s = "";
  for (uint8_t i = 0; i < tamanho; i++) {
    if (uid[i] < 0x10) s += "0";
    s += String(uid[i], HEX);
  }
  s.toUpperCase();
  return s;
}

void setup() {
  Serial.begin(115200);
  pinMode(PIN_LED_VERDE, OUTPUT);
  pinMode(PIN_LED_VERMELHO, OUTPUT);
  pinMode(PIN_BUZZER, OUTPUT);

  Wire.begin(21, 22);
  nfc.begin();
  uint32_t versao = nfc.getFirmwareVersion();
  if (!versao) {
    Serial.println("PN532 nao encontrado. Confira fiacao e chaves I2C do modulo.");
    while (true) { sinalErroRede(); delay(1000); }
  }
  Serial.printf("PN532 firmware %d.%d\n", (versao >> 16) & 0xFF, (versao >> 8) & 0xFF);
  nfc.SAMConfig();

  garantirWifi();
  enviarPing();
  ultimoPing = millis();
  Serial.println("Pronto. Aproxime um cracha ou tag.");
}

void loop() {
  if (millis() - ultimoPing > INTERVALO_PING_MS) {
    enviarPing();
    ultimoPing = millis();
  }

  uint8_t uid[7];
  uint8_t tamanho;
  // espera ate 100 ms por uma tag (Mifare/NTAG 13,56 MHz)
  if (nfc.readPassiveTargetID(PN532_MIFARE_ISO14443A, uid, &tamanho, 100)) {
    String texto = uidParaTexto(uid, tamanho);
    if (texto == ultimoUid && millis() - ultimaLeitura < REPETICAO_LOCAL_MS) {
      return;  // a mesma tag ainda esta perto do leitor
    }
    ultimoUid = texto;
    ultimaLeitura = millis();
    Serial.println("UID: " + texto);
    enviarLeitura(texto);
  }
}
