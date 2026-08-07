#include <WiFi.h>
#include <WiFiUdp.h>
#include <WebSocketsClient.h>
#include <WebServer.h>
#include <DNSServer.h>
#include <Preferences.h>
#include <Wire.h>
#include <string.h>
#include <time.h>
#include <sys/time.h>
#include <stdlib.h>
#include "XPowersLib.h"
#include <driver/i2s.h>
#include "HWCDC.h"
#include <Arduino_GFX_Library.h>

#if __has_include("wifi_local.h")
#include "wifi_local.h"
#endif

#ifndef WIFI_SSID
#define WIFI_SSID ""
#endif
#ifndef WIFI_PASS
#define WIFI_PASS ""
#endif
#ifndef WS_HOST
#define WS_HOST "192.168.1.100"
#endif
#ifndef WS_PORT
#define WS_PORT 8001
#endif
#ifndef AP_SSID
#define AP_SSID "MEB-AI-Setup"
#endif
#ifndef AP_PASS
#define AP_PASS "setup1234"
#endif

#define BLACK   0x0000
#define WHITE   0xFFFF
#define GREEN   0x07E0
#define CYAN    0x07FF
#define ORANGE  0xFD20
#define BG_DEEP   0x0169
#define BG_MID    0x12B4
#define ACCENT    0x07FD
#define AMBER     0xFDC0
#define MINT      0x2FEA
#define MUTED     0x7BEF
#define CHIP_ON   0x07F9
#define CHIP_OFF  0x2945

enum DeviceState {
  STATE_UNKNOWN,
  STATE_IDLE,
  STATE_LISTENING,
  STATE_THINKING,
  STATE_SPEAKING
};

HWCDC USBSerial;
XPowersAXP2101 PMIC;
WebSocketsClient webSocket;
Preferences prefs;
WebServer configServer(80);
DNSServer dnsServer;
WiFiUDP g_discoverUdp;

char wifi_ssid[48] = WIFI_SSID;
char wifi_pass[64] = WIFI_PASS;
char ws_server[48] = WS_HOST;
int  ws_port = WS_PORT;
const char* ws_path = "/ws/device";
bool g_configMode = false;

#ifndef LANG_START_ENGLISH
#define LANG_START_ENGLISH 0
#endif
#define BTN_BOOT 0
#if LANG_START_ENGLISH
char dil_ayari[16] = "English";
#else
char dil_ayari[16] = "Turkce";
#endif

#define I2C_SDA_PIN   15
#define I2C_SCL_PIN   14
#define I2S_MCLK_PIN  16
#define I2S_BCLK_PIN  9
#define I2S_LRCK_PIN  45
#define I2S_DOUT_PIN  8
#define I2S_DIN_PIN   10
#define PA_PIN        46
#define ES8311_ADDR   0x18
#define ES7210_ADDR   0x40
#define SAMPLE_RATE   16000
#define I2S_READ_BYTES 1024

#define TFT_CS    5
#define TFT_DC    4
#define TFT_RST   38
#define TFT_BL    40
#define TFT_MOSI  7
#define TFT_SCLK  6

Arduino_DataBus *bus = new Arduino_ESP32SPI(TFT_DC, TFT_CS, TFT_SCLK, TFT_MOSI, GFX_NOT_DEFINED);
Arduino_GFX *gfx = new Arduino_ST7789(bus, TFT_RST, 0, true, 240, 284, 0, 0);

DeviceState currentState = STATE_UNKNOWN;

#define AEC_REF_DELAY      240
#define AEC_SUBTRACT_GAIN  0.20f
#define PLAY_RING_SIZE     (160 * 1024)
#define PLAY_PREBUFFER     (20 * 1024)
#define CST816_ADDR        0x15
#define UI_PAGE_HOME       0
#define UI_PAGE_ASK        1
#define UI_PAGE_CALENDAR   2
#define UI_PAGE_WIFI       3
#define UI_PAGE_SETTINGS   4
#define UI_PAGE_SINIF      5
#define UI_PAGE_EKRAN      6
#define UI_PAGE_COUNT      7

volatile bool g_playbackActive     = false;
volatile bool g_micTransmitAllowed = true;
volatile bool g_serverThinking     = false;
volatile bool g_streamComplete     = false;
volatile uint32_t g_micCooldownUntil = 0;
volatile uint16_t g_micLevel       = 0;
bool g_timeSynced = false;
bool g_screenOff = false;
bool g_listenPaused = false;
bool g_textAskPending = false;
bool g_askShowAnswer = false;
int8_t g_uiPage = UI_PAGE_HOME;
int8_t g_bgTheme = 0;
int8_t g_uiBand = 2;
int8_t g_sinifNo = 10;
uint16_t g_bgColor = BG_DEEP;
char g_lastSoru[180] = "";
char g_lastCevap[420] = "";
char g_ogrenciAd[48] = "";

uint8_t playRing[PLAY_RING_SIZE];
volatile size_t playHead = 0;
volatile size_t playTail = 0;

int16_t g_refRing[AEC_REF_DELAY];
size_t  g_refRingIdx = 0;

void setDeviceState(DeviceState newState);
void startSpeaking();
void stopSpeaking();
void handleServerText(const char* text);
static void speakerEnable(bool on);
static bool dilIngilizceMi();
static void sendDilConfig();
static void setDilEnglish(bool en);

static void refRingPush(int16_t sample) {
  g_refRing[g_refRingIdx] = sample;
  g_refRingIdx = (g_refRingIdx + 1) % AEC_REF_DELAY;
}

static int16_t refRingGetDelayed(size_t delaySamples) {
  size_t idx = (g_refRingIdx + AEC_REF_DELAY - delaySamples) % AEC_REF_DELAY;
  return g_refRing[idx];
}

static int16_t applySoftwareAEC(int16_t micSample) {
  int32_t ref = (int32_t)(refRingGetDelayed(AEC_REF_DELAY / 2) * AEC_SUBTRACT_GAIN);
  int32_t out = (int32_t)micSample - ref;
  if (out > 32767)  out = 32767;
  if (out < -32768) out = -32768;
  return (int16_t)out;
}

static void flushMicDma() {
  int16_t dump[256];
  size_t bytes_read = 0;
  for (int i = 0; i < 6; i++) {
    i2s_read(I2S_NUM_0, dump, sizeof(dump), &bytes_read, 0);
  }
}

static void speakerEnable(bool on) {
  digitalWrite(PA_PIN, on ? HIGH : LOW);
}

static size_t playRingFree() {
  size_t h = playHead;
  size_t t = playTail;
  if (h >= t) return PLAY_RING_SIZE - 1 - (h - t);
  return t - h - 1;
}

static size_t playRingUsed() {
  size_t h = playHead;
  size_t t = playTail;
  if (h >= t) return h - t;
  return PLAY_RING_SIZE - (t - h);
}

static void playRingClear() {
  playHead = 0;
  playTail = 0;
}

static void enqueuePlayback(const uint8_t* data, size_t len) {
  if (len & 1) len--;
  size_t i = 0;
  while (i + 1 < len) {
    if (playRingFree() < 2) break;
    playRing[playHead] = data[i++];
    playHead = (playHead + 1) % PLAY_RING_SIZE;
    playRing[playHead] = data[i++];
    playHead = (playHead + 1) % PLAY_RING_SIZE;
  }
}

static bool dilIngilizceMi() {
  return (dil_ayari[0] == 'E' || dil_ayari[0] == 'e');
}

void drawFace(DeviceState state);
void pollDilControls();
void animateFaceIfNeeded();
void ui_on_pmic_key();
void reconnectWebSocket();

void saveNetPrefsPublic(const String& ssid, const String& pass, const String& host, int port);
void startConfigPortalPublic();
void loadNetPrefs();
void saveBgTheme(int8_t idx);
void syncNtpTime();
bool dilIngilizceMiPublic();
void processPlayback();
void webSocketEvent(WStype_t type, uint8_t* payload, size_t length);
static bool applyHostAndConnect(const String& host, int port) {
  if (host.length() < 7) return false;
  USBSerial.printf("[DISCOVER] sunucu = %s:%d\n", host.c_str(), port);
  saveNetPrefsPublic(String(wifi_ssid), String(wifi_pass), host, port);
  reconnectWebSocket();
  return true;
}

static bool probeHost8001(const IPAddress& ip) {
  WiFiClient c;
  c.setTimeout(150);
  if (!c.connect(ip, 8001, 180)) return false;
  c.stop();
  return true;
}

static bool scanSubnetForBackend() {
  IPAddress ip = WiFi.localIP();
  USBSerial.printf("[DISCOVER] subnet taraniyor %d.%d.%d.x:8001\n", ip[0], ip[1], ip[2]);
  const int prefer[] = {1, 101, 102, 108, 100, 137, 43, 50, 20, 10};
  for (unsigned k = 0; k < sizeof(prefer) / sizeof(prefer[0]); k++) {
    int i = prefer[k];
    if (i == ip[3]) continue;
    IPAddress t(ip[0], ip[1], ip[2], (uint8_t)i);
    if (probeHost8001(t)) {
      return applyHostAndConnect(t.toString(), 8001);
    }
    yield();
  }
  for (int i = 1; i < 255; i++) {
    if (i == ip[3]) continue;
    bool skip = false;
    for (unsigned k = 0; k < sizeof(prefer) / sizeof(prefer[0]); k++) {
      if (prefer[k] == i) { skip = true; break; }
    }
    if (skip) continue;
    IPAddress t(ip[0], ip[1], ip[2], (uint8_t)i);
    if (probeHost8001(t)) {
      return applyHostAndConnect(t.toString(), 8001);
    }
    if ((i % 20) == 0) yield();
  }
  return false;
}

bool discoverServerPublic() {
  if (WiFi.status() != WL_CONNECTED) {
    USBSerial.println("[DISCOVER] Once WiFi baglan");
    return false;
  }

  {
    IPAddress saved;
    if (saved.fromString(String(ws_server)) && probeHost8001(saved)) {
      return applyHostAndConnect(String(ws_server), ws_port > 0 ? ws_port : 8001);
    }
  }

  g_discoverUdp.stop();
  if (g_discoverUdp.begin(0)) {
    const char* req = "MEB_AI_DISCOVER";
    g_discoverUdp.beginPacket(IPAddress(255, 255, 255, 255), 8002);
    g_discoverUdp.write((const uint8_t*)req, strlen(req));
    g_discoverUdp.endPacket();
    g_discoverUdp.beginPacket(WiFi.broadcastIP(), 8002);
    g_discoverUdp.write((const uint8_t*)req, strlen(req));
    g_discoverUdp.endPacket();
    uint32_t t0 = millis();
    char buf[72];
    while (millis() - t0 < 2000) {
      int n = g_discoverUdp.parsePacket();
      if (n > 0) {
        int len = g_discoverUdp.read(buf, sizeof(buf) - 1);
        if (len < 0) len = 0;
        buf[len] = 0;
        if (strncmp(buf, "MEB_AI_HOST:", 12) == 0) {
          char* host = buf + 12;
          char* colon = strchr(host, ':');
          int port = 8001;
          if (colon) {
            *colon = 0;
            int p = atoi(colon + 1);
            if (p > 0) port = p;
          }
          g_discoverUdp.stop();
          return applyHostAndConnect(String(host), port);
        }
      }
      delay(20);
      yield();
    }
    g_discoverUdp.stop();
  }

  IPAddress gw = WiFi.gatewayIP();
  if (gw != IPAddress(0, 0, 0, 0) && gw != WiFi.localIP() && probeHost8001(gw)) {
    return applyHostAndConnect(gw.toString(), 8001);
  }

  if (probeHost8001(IPAddress(192, 168, 137, 1))) {
    return applyHostAndConnect("192.168.137.1", 8001);
  }

  if (scanSubnetForBackend()) return true;

  USBSerial.println("[DISCOVER] bulunamadi — PC ayni WiFi/hotspot + BASLAT?");
  return false;
}
static void sendDilConfig() {
  if (!webSocket.isConnected()) return;
  String cfg = String("{\"type\":\"config\",\"dil\":\"") + dil_ayari + "\"}";
  webSocket.sendTXT(cfg);
}

void sendListenConfig(bool on) {
  if (!webSocket.isConnected()) return;
  webSocket.sendTXT(on ? "{\"type\":\"config\",\"listen\":true}"
                       : "{\"type\":\"config\",\"listen\":false}");
  USBSerial.printf("[MIC] dinleme=%s\n", on ? "ACIK" : "KAPALI");
}

void sendSinifConfig(int sinif) {
  if (sinif < 0) sinif = 0;
  if (sinif > 12) sinif = 12;
  g_sinifNo = (int8_t)sinif;
  if (sinif == 0) g_uiBand = 2;
  else if (sinif <= 4) g_uiBand = 0;
  else if (sinif <= 8) g_uiBand = 1;
  else g_uiBand = 2;
  if (!webSocket.isConnected()) return;
  char cfg[48];
  snprintf(cfg, sizeof(cfg), "{\"type\":\"config\",\"sinif\":%d}", sinif);
  webSocket.sendTXT(cfg);
  USBSerial.printf("[UI] sinif gonderildi: %d\n", sinif);
}

void setDilEnglishPublic(bool en) {
  strncpy(dil_ayari, en ? "English" : "Turkce", sizeof(dil_ayari) - 1);
  dil_ayari[sizeof(dil_ayari) - 1] = 0;
  sendDilConfig();
  drawFace(currentState == STATE_UNKNOWN ? STATE_IDLE : currentState);
}

static void setDilEnglish(bool en) { setDilEnglishPublic(en); }

bool readTouchXYPublic(int16_t &x, int16_t &y) {
  Wire.beginTransmission(CST816_ADDR);
  Wire.write(0x02);
  if (Wire.endTransmission(false) != 0) return false;
  if (Wire.requestFrom((uint8_t)CST816_ADDR, (uint8_t)5) < 5) return false;
  uint8_t fingers = Wire.read();
  uint8_t xh = Wire.read();
  uint8_t xl = Wire.read();
  uint8_t yh = Wire.read();
  uint8_t yl = Wire.read();
  if (fingers == 0 || fingers > 5) return false;
  x = (int16_t)(((xh & 0x0F) << 8) | xl);
  y = (int16_t)(((yh & 0x0F) << 8) | yl);
  return (x >= 0 && y >= 0 && x < 240 && y < 284);
}

void reconnectWebSocket() {
  webSocket.disconnect();
  webSocket.begin(ws_server, ws_port, ws_path);
  webSocket.onEvent(webSocketEvent);
  webSocket.setReconnectInterval(3000);
}

static void lcd_init() {
  gfx->begin();
  gfx->fillScreen(BLACK);
  pinMode(TFT_BL, OUTPUT);
  digitalWrite(TFT_BL, HIGH);
  setDeviceState(STATE_IDLE);
  USBSerial.println("[OK] LCD baslatildi");
}

void setDeviceState(DeviceState newState) {
  if (currentState == newState) return;
  currentState = newState;
  drawFace(newState);
}

void startSpeaking() {
  g_playbackActive = true;
  g_micTransmitAllowed = false;
  speakerEnable(true);
  setDeviceState(STATE_SPEAKING);
}
void stopSpeaking() {
  g_playbackActive = false;
  g_streamComplete = false;
  playRingClear();
  speakerEnable(false);
  g_micCooldownUntil = millis() + 1200;
  g_micTransmitAllowed = false;
  if (webSocket.isConnected()) setDeviceState(STATE_LISTENING);
  else setDeviceState(STATE_IDLE);
}

void processPlayback() {
  size_t used = playRingUsed();
  static uint32_t emptySince = 0;
  if (used < 4) {
    if (g_playbackActive && g_streamComplete) {
      if (!emptySince) emptySince = millis();
      if (millis() - emptySince > 80) { emptySince = 0; stopSpeaking(); }
    }
    return;
  }
  emptySince = 0;
  if (!g_playbackActive) {
    if (used < PLAY_PREBUFFER && !g_streamComplete) return;
    startSpeaking();
  }
  int16_t stereo[512];
  size_t frames = min((size_t)256, used / 2);
  for (size_t i = 0; i < frames; i++) {
    uint8_t b0 = playRing[playTail]; playTail = (playTail + 1) % PLAY_RING_SIZE;
    uint8_t b1 = playRing[playTail]; playTail = (playTail + 1) % PLAY_RING_SIZE;
    int16_t s = (int16_t)(b0 | ((uint16_t)b1 << 8));
    stereo[i * 2] = s; stereo[i * 2 + 1] = s;
    refRingPush(s);
  }
  size_t need = frames * 2 * sizeof(int16_t);
  size_t written = 0;
  uint8_t* ptr = (uint8_t*)stereo;
  while (written < need) {
    size_t w = 0;
    if (i2s_write(I2S_NUM_0, ptr + written, need - written, &w, pdMS_TO_TICKS(80)) != ESP_OK || !w) break;
    written += w;
  }
}

static bool jsonContains(const char* text, const char* key, const char* value) {
  char needle[96];
  snprintf(needle, sizeof(needle), "\"%s\":\"%s\"", key, value);
  if (strstr(text, needle)) return true;
  snprintf(needle, sizeof(needle), "\"%s\": \"%s\"", key, value);
  return strstr(text, needle) != nullptr;
}
static bool jsonExtractString(const char* text, const char* key, char* out, size_t outLen) {
  char needle[48];
  snprintf(needle, sizeof(needle), "\"%s\":\"", key);
  const char* p = strstr(text, needle);
  if (!p) return false;
  p += strlen(needle);
  size_t i = 0;
  while (*p && *p != '"' && i + 1 < outLen) {
    if (*p == '\\' && p[1]) { p++; out[i++] = (*p == 'n') ? ' ' : *p; p++; continue; }
    out[i++] = *p++;
  }
  out[i] = 0;
  return i > 0;
}

static void trUtf8ToLcd(const char* in, char* out, size_t outLen) {
  if (!out || outLen == 0) return;
  size_t j = 0;
  const unsigned char* p = (const unsigned char*)in;
  while (p && *p && j + 1 < outLen) {
    if (*p < 0x80) {
      out[j++] = (char)*p++;
      continue;
    }
    if (p[1] == 0) break;
    unsigned char c0 = p[0], c1 = p[1];
    char rep = 0;
    if (c0 == 0xC3) {
      if (c1 == 0xA7 || c1 == 0x87) rep = (c1 == 0x87) ? 'C' : 'c';
      else if (c1 == 0xB6 || c1 == 0x96) rep = (c1 == 0x96) ? 'O' : 'o';
      else if (c1 == 0xBC || c1 == 0x9C) rep = (c1 == 0x9C) ? 'U' : 'u';
    } else if (c0 == 0xC4) {
      if (c1 == 0x9F || c1 == 0x9E) rep = (c1 == 0x9E) ? 'G' : 'g';
      else if (c1 == 0xB1) rep = 'i';
      else if (c1 == 0xB0) rep = 'I';
    } else if (c0 == 0xC5) {
      if (c1 == 0x9F || c1 == 0x9E) rep = (c1 == 0x9E) ? 'S' : 's';
    }
    if (rep) {
      out[j++] = rep;
      p += 2;
      continue;
    }
    if ((c0 & 0xE0) == 0xC0) p += 2;
    else if ((c0 & 0xF0) == 0xE0) p += 3;
    else if ((c0 & 0xF8) == 0xF0) p += 4;
    else p++;
  }
  out[j] = 0;
}
static bool jsonExtractLong(const char* text, const char* key, long* out) {
  char needle[40];
  snprintf(needle, sizeof(needle), "\"%s\":", key);
  const char* p = strstr(text, needle);
  if (!p) return false;
  p += strlen(needle);
  while (*p == ' ') p++;
  char* end = nullptr;
  long v = strtol(p, &end, 10);
  if (end == p) return false;
  *out = v;
  return true;
}

void syncNtpTime() {
  configTime(3 * 3600, 0, "pool.ntp.org", "time.google.com", "time.cloudflare.com");
  struct tm ti;
  if (getLocalTime(&ti, 5000)) { g_timeSynced = true; USBSerial.println("[TIME] NTP OK"); }
  else USBSerial.println("[TIME] NTP yok");
}

static void applyServerEpoch(long epochUtc) {
  if (epochUtc < 1700000000L) return;
  setenv("TZ", "UTC-3", 1); tzset();
  struct timeval tv{}; tv.tv_sec = (time_t)epochUtc; tv.tv_usec = 0;
  settimeofday(&tv, nullptr);
  g_timeSynced = true;
  drawFace(currentState == STATE_UNKNOWN ? STATE_IDLE : currentState);
}

void handleServerText(const char* text) {
  if (!g_playbackActive && currentState != STATE_SPEAKING) USBSerial.printf("[WS] %s\n", text);
  if (jsonContains(text, "type", "student") || jsonContains(text, "type", "settings")) {
    long band = g_uiBand, sinif = g_sinifNo;
    if (jsonExtractLong(text, "sinif", &sinif) && sinif >= 0 && sinif <= 12) {
      g_sinifNo = (int8_t)sinif;
      if (sinif == 0) g_uiBand = 2;
      else if (sinif <= 4) g_uiBand = 0;
      else if (sinif <= 8) g_uiBand = 1;
      else g_uiBand = 2;
    } else if (jsonExtractLong(text, "band", &band) && band >= 0 && band <= 2) {
      g_uiBand = (int8_t)band;
    }
    char ad[48];
    if (jsonExtractString(text, "ad", ad, sizeof(ad))) {
      trUtf8ToLcd(ad, g_ogrenciAd, sizeof(g_ogrenciAd));
    }
    USBSerial.printf("[UI] ogrenci sinif=%d band=%d ad=%s\n", (int)g_sinifNo, (int)g_uiBand, g_ogrenciAd);
    if (!g_screenOff) drawFace(currentState == STATE_UNKNOWN ? STATE_IDLE : currentState);
    return;
  }
  if (jsonContains(text, "type", "time")) {
    long epoch = 0;
    if (jsonExtractLong(text, "epoch", &epoch)) applyServerEpoch(epoch);
    return;
  }
  if (jsonContains(text, "type", "done") || jsonContains(text, "type", "error")) {
    g_streamComplete = true;
    char soruBuf[180], cevapBuf[420];
    if (jsonExtractString(text, "soru", soruBuf, sizeof(soruBuf))) strncpy(g_lastSoru, soruBuf, sizeof(g_lastSoru)-1);
    if (jsonExtractString(text, "cevap", cevapBuf, sizeof(cevapBuf))) strncpy(g_lastCevap, cevapBuf, sizeof(g_lastCevap)-1);
    if (g_textAskPending || jsonContains(text, "mod", "yazi")) {
      g_textAskPending = false; g_askShowAnswer = true; g_uiPage = UI_PAGE_ASK;
      drawFace(STATE_IDLE);
    }
    return;
  }
  if (jsonContains(text, "type", "status")) {
    if (jsonContains(text, "value", "speaking")) {
      g_serverThinking = false; g_micTransmitAllowed = false; g_streamComplete = false;
      setDeviceState(STATE_SPEAKING);
    } else if (jsonContains(text, "value", "thinking")) {
      if (g_playbackActive || currentState == STATE_SPEAKING) return;
      g_serverThinking = true; g_micTransmitAllowed = false; g_streamComplete = false;
      setDeviceState(STATE_THINKING);
    } else if (jsonContains(text, "value", "listening")) {
      g_serverThinking = false;
      if (g_listenPaused || g_screenOff) return;
      if (!g_playbackActive && currentState != STATE_SPEAKING) {
        setDeviceState(STATE_LISTENING);
        if (g_micCooldownUntil < millis()) {
          g_micCooldownUntil = millis() + 500;
        }
      }
    } else if (jsonContains(text, "value", "idle")) {
      g_serverThinking = false;
      if (!g_playbackActive) setDeviceState(STATE_IDLE);
    }
  }
}

void webSocketEvent(WStype_t type, uint8_t* payload, size_t length) {
  switch (type) {
    case WStype_CONNECTED:
      USBSerial.println("[WS] baglandi");
      sendDilConfig();
      setDeviceState(STATE_LISTENING);
      break;
    case WStype_TEXT: {
      char* txt = (char*)malloc(length + 1);
      if (!txt) break;
      memcpy(txt, payload, length); txt[length] = 0;
      handleServerText(txt);
      free(txt);
      break;
    }
    case WStype_BIN:
      enqueuePlayback(payload, length);
      break;
    case WStype_DISCONNECTED:
      USBSerial.println("[WS] koptu");
      setDeviceState(STATE_IDLE);
      break;
    default: break;
  }
}

static bool i2c_probe(uint8_t addr) {
  Wire.beginTransmission(addr);
  return Wire.endTransmission() == 0;
}

static void i2c_write8(uint8_t addr, uint8_t reg, uint8_t val) {
  Wire.beginTransmission(addr);
  Wire.write(reg);
  Wire.write(val);
  Wire.endTransmission();
}

static uint8_t i2c_read8(uint8_t addr, uint8_t reg) {
  Wire.beginTransmission(addr);
  Wire.write(reg);
  Wire.endTransmission(false);
  Wire.requestFrom(addr, (uint8_t)1);
  return Wire.available() ? Wire.read() : 0;
}

static void i2c_update8(uint8_t addr, uint8_t reg, uint8_t mask, uint8_t val) {
  uint8_t v = i2c_read8(addr, reg);
  v = (v & ~mask) | (mask & val);
  i2c_write8(addr, reg, v);
}

static void pmic_init_for_audio() {
  if (!PMIC.begin(Wire, AXP2101_SLAVE_ADDRESS, I2C_SDA_PIN, I2C_SCL_PIN)) {
    USBSerial.println("[HATA] AXP2101 bulunamadi!");
    return;
  }
  USBSerial.println("[OK] AXP2101 bulundu");
  PMIC.setALDO1Voltage(3300); PMIC.enableALDO1();
  PMIC.setALDO2Voltage(3300); PMIC.enableALDO2();
  PMIC.setALDO3Voltage(3300); PMIC.enableALDO3();
  PMIC.setBLDO1Voltage(3300); PMIC.enableBLDO1();
  PMIC.setBLDO2Voltage(3300); PMIC.enableBLDO2();
  PMIC.clearIrqStatus();
  PMIC.enableIRQ(XPOWERS_AXP2101_PKEY_SHORT_IRQ | XPOWERS_AXP2101_PKEY_LONG_IRQ);
}

static void es8311_init_dac() {
  if (!i2c_probe(ES8311_ADDR)) {
    USBSerial.println("[HATA] ES8311 bulunamadi!");
    return;
  }
  USBSerial.println("[OK] ES8311 bulundu - DAC baslatiliyor");

  i2c_write8(ES8311_ADDR, 0x00, 0x1F);
  delay(20);
  i2c_write8(ES8311_ADDR, 0x00, 0x00);

  i2c_write8(ES8311_ADDR, 0x0D, 0xFA);
  i2c_write8(ES8311_ADDR, 0x44, 0x08);
  i2c_write8(ES8311_ADDR, 0x01, 0x30);
  i2c_write8(ES8311_ADDR, 0x02, 0x00);
  i2c_write8(ES8311_ADDR, 0x03, 0x10);
  i2c_write8(ES8311_ADDR, 0x16, 0x24);
  i2c_write8(ES8311_ADDR, 0x04, 0x10);
  i2c_write8(ES8311_ADDR, 0x05, 0x00);
  i2c_write8(ES8311_ADDR, 0x0B, 0x00);
  i2c_write8(ES8311_ADDR, 0x0C, 0x00);
  i2c_write8(ES8311_ADDR, 0x10, 0x1F);
  i2c_write8(ES8311_ADDR, 0x11, 0x7F);
  i2c_write8(ES8311_ADDR, 0x00, 0x80);
  i2c_write8(ES8311_ADDR, 0x01, 0x3F);
  i2c_write8(ES8311_ADDR, 0x13, 0x10);
  i2c_write8(ES8311_ADDR, 0x1B, 0x0A);
  i2c_write8(ES8311_ADDR, 0x1C, 0x6A);
  i2c_write8(ES8311_ADDR, 0x44, 0x58);

  i2c_write8(ES8311_ADDR, 0x09, 0x0C);
  i2c_write8(ES8311_ADDR, 0x0A, 0x0C);

  i2c_write8(ES8311_ADDR, 0x17, 0xBF);
  i2c_write8(ES8311_ADDR, 0x0E, 0x02);
  i2c_write8(ES8311_ADDR, 0x12, 0x00);
  i2c_write8(ES8311_ADDR, 0x14, 0x1A);
  i2c_write8(ES8311_ADDR, 0x0D, 0x01);
  i2c_write8(ES8311_ADDR, 0x15, 0x40);
  i2c_write8(ES8311_ADDR, 0x37, 0x08);
  i2c_write8(ES8311_ADDR, 0x45, 0x00);

  i2c_write8(ES8311_ADDR, 0x32, 0xBF);
  i2c_write8(ES8311_ADDR, 0x31, 0x00);

  pinMode(PA_PIN, OUTPUT);
  speakerEnable(false);
  USBSerial.println("[OK] ES8311 DAC hazir (volume 0dB)");
}

static uint8_t es7210_off_reg = 0x3F;

static void es7210_mic_select() {
  i2c_update8(ES7210_ADDR, 0x43, 0x0F, 0x0F);
  i2c_update8(ES7210_ADDR, 0x43, 0x10, 0x10);
  i2c_update8(ES7210_ADDR, 0x44, 0x0F, 0x0F);
  i2c_update8(ES7210_ADDR, 0x44, 0x10, 0x10);
  i2c_write8(ES7210_ADDR, 0x4B, 0x00);
  i2c_write8(ES7210_ADDR, 0x4C, 0xFF);
  i2c_update8(ES7210_ADDR, 0x01, 0x0B, 0x00);
  i2c_write8(ES7210_ADDR, 0x12, 0x00);
}

static void es7210_set_sample_rate_16k() {
  i2c_write8(ES7210_ADDR, 0x02, 0xC1);
  i2c_write8(ES7210_ADDR, 0x07, 0x20);
  i2c_write8(ES7210_ADDR, 0x04, 0x01);
  i2c_write8(ES7210_ADDR, 0x05, 0x00);
  i2c_write8(ES7210_ADDR, 0x11, 0x60);
}

static void es7210_start_adc() {
  i2c_write8(ES7210_ADDR, 0x01, es7210_off_reg);
  i2c_write8(ES7210_ADDR, 0x06, 0x00);
  i2c_write8(ES7210_ADDR, 0x40, 0x43);
  i2c_write8(ES7210_ADDR, 0x47, 0x08);
  i2c_write8(ES7210_ADDR, 0x48, 0x08);
  i2c_write8(ES7210_ADDR, 0x49, 0xFF);
  i2c_write8(ES7210_ADDR, 0x4A, 0xFF);
  es7210_mic_select();
  i2c_write8(ES7210_ADDR, 0x00, 0x71);
  i2c_write8(ES7210_ADDR, 0x00, 0x41);
}

static void es7210_init_full() {
  if (!i2c_probe(ES7210_ADDR)) {
    USBSerial.println("[HATA] ES7210 bulunamadi!");
    return;
  }
  USBSerial.println("[OK] ES7210 bulundu");
  i2c_write8(ES7210_ADDR, 0x00, 0xFF);
  i2c_write8(ES7210_ADDR, 0x00, 0x41);
  i2c_write8(ES7210_ADDR, 0x01, 0x3F);
  i2c_write8(ES7210_ADDR, 0x09, 0x30);
  i2c_write8(ES7210_ADDR, 0x0A, 0x30);
  i2c_write8(ES7210_ADDR, 0x23, 0x2A);
  i2c_write8(ES7210_ADDR, 0x22, 0x0A);
  i2c_write8(ES7210_ADDR, 0x20, 0x0A);
  i2c_write8(ES7210_ADDR, 0x21, 0x2A);
  i2c_update8(ES7210_ADDR, 0x08, 0x01, 0x00);
  i2c_write8(ES7210_ADDR, 0x40, 0x43);
  i2c_write8(ES7210_ADDR, 0x41, 0x88);
  i2c_write8(ES7210_ADDR, 0x42, 0x88);
  i2c_write8(ES7210_ADDR, 0x07, 0x20);
  i2c_write8(ES7210_ADDR, 0x02, 0xC1);
  es7210_mic_select();
  es7210_off_reg = i2c_read8(ES7210_ADDR, 0x01);
  es7210_set_sample_rate_16k();
  es7210_start_adc();
  USBSerial.println("[OK] ES7210 ADC baslatildi");
}

static void i2s_init_mic() {
  i2s_config_t cfg = {
    .mode = (i2s_mode_t)(I2S_MODE_MASTER | I2S_MODE_RX | I2S_MODE_TX),
    .sample_rate = SAMPLE_RATE,
    .bits_per_sample = I2S_BITS_PER_SAMPLE_16BIT,
    .channel_format = I2S_CHANNEL_FMT_RIGHT_LEFT,
    .communication_format = I2S_COMM_FORMAT_STAND_I2S,
    .intr_alloc_flags = ESP_INTR_FLAG_LEVEL1,
    .dma_buf_count = 12,
    .dma_buf_len = 512,
    .use_apll = true,
    .tx_desc_auto_clear = true,
    .fixed_mclk = SAMPLE_RATE * 256
  };
  i2s_pin_config_t pins = {
    .mck_io_num   = I2S_MCLK_PIN,
    .bck_io_num   = I2S_BCLK_PIN,
    .ws_io_num    = I2S_LRCK_PIN,
    .data_out_num = I2S_DOUT_PIN,
    .data_in_num  = I2S_DIN_PIN
  };
  i2s_driver_install(I2S_NUM_0, &cfg, 0, NULL);
  i2s_set_pin(I2S_NUM_0, &pins);
  i2s_set_clk(I2S_NUM_0, SAMPLE_RATE, I2S_BITS_PER_SAMPLE_16BIT, I2S_CHANNEL_STEREO);
  USBSerial.println("[OK] I2S kuruldu");
}

static const uint16_t kBgThemes[] = {0x0169, 0x0000, 0x10B4, 0x0320, 0x480A};
void saveBgTheme(int8_t idx) {
  if (idx < 0) idx = 0;
  if (idx > 4) idx = 4;
  g_bgTheme = idx; g_bgColor = kBgThemes[idx];
  prefs.begin("mebai", false); prefs.putInt("bgTheme", g_bgTheme); prefs.end();
}
void loadNetPrefs() {
  prefs.begin("mebai", true);
  if (prefs.isKey("ssid")) {
    strlcpy(wifi_ssid, prefs.getString("ssid", wifi_ssid).c_str(), sizeof(wifi_ssid));
    strlcpy(wifi_pass, prefs.getString("pass", wifi_pass).c_str(), sizeof(wifi_pass));
    strlcpy(ws_server, prefs.getString("host", ws_server).c_str(), sizeof(ws_server));
    ws_port = prefs.getInt("port", ws_port);
  }
  int th = prefs.getInt("bgTheme", 0);
  prefs.end();
  if (th < 0) th = 0; if (th > 4) th = 4;
  g_bgTheme = (int8_t)th; g_bgColor = kBgThemes[th];
}
void saveNetPrefsPublic(const String& ssid, const String& pass, const String& host, int port) {
  if (port <= 0) port = 8001;
  prefs.begin("mebai", false);
  prefs.putString("ssid", ssid); prefs.putString("pass", pass);
  prefs.putString("host", host); prefs.putInt("port", port);
  prefs.end();
  strlcpy(wifi_ssid, ssid.c_str(), sizeof(wifi_ssid));
  strlcpy(wifi_pass, pass.c_str(), sizeof(wifi_pass));
  strlcpy(ws_server, host.c_str(), sizeof(ws_server));
  ws_port = port;
}

static void handleConfigRoot() {
  String html = String("<!DOCTYPE html><html><head><meta charset=utf-8><meta name=viewport content='width=device-width,initial-scale=1'>")
    + "<title>MEB AI</title><style>body{font-family:sans-serif;background:#061a22;color:#fff;padding:20px}"
    + "input{width:100%;padding:10px;margin:8px 0;border-radius:8px;border:0}button{width:100%;padding:12px;background:#2ec4b6;border:0;border-radius:8px}</style></head><body>"
    + "<h3>MEB AI WiFi</h3><form method=POST action=/save>"
    + "<label>SSID</label><input name=ssid value='" + String(wifi_ssid) + "'>"
    + "<label>Sifre</label><input name=pass value='" + String(wifi_pass) + "'>"
    + "<label>Sunucu IP</label><input name=host value='" + String(ws_server) + "'>"
    + "<label>Port</label><input name=port value='" + String(ws_port) + "'>"
    + "<button type=submit>Kaydet</button></form></body></html>";
  configServer.send(200, "text/html", html);
}
static void handleConfigSave() {
  saveNetPrefsPublic(configServer.arg("ssid"), configServer.arg("pass"), configServer.arg("host"), configServer.arg("port").toInt());
  configServer.send(200, "text/html", "<html><body style='background:#061a22;color:#fff;padding:24px'><h3>Kaydedildi...</h3></body></html>");
  delay(600); ESP.restart();
}
void startConfigPortalPublic() {
  g_configMode = true;
  webSocket.disconnect(); WiFi.disconnect(true); delay(80);
  WiFi.mode(WIFI_AP); WiFi.softAP(AP_SSID, AP_PASS);
  dnsServer.stop(); dnsServer.start(53, "*", WiFi.softAPIP());
  configServer.stop();
  configServer.on("/", handleConfigRoot);
  configServer.on("/save", HTTP_POST, handleConfigSave);
  configServer.onNotFound(handleConfigRoot);
  configServer.begin();
  g_uiPage = UI_PAGE_WIFI; drawFace(STATE_IDLE);
  USBSerial.printf("[WIFI] AP %s\n", AP_SSID);
}

bool dilIngilizceMiPublic() { return dilIngilizceMi(); }

void setup() {
  USBSerial.begin(115200);
  delay(400);
  USBSerial.println("\n--- MEB AI Asistan | Tablet UI ---");
  USBSerial.println("[UI] Kaydir: Ana | Yaz | Takvim | WiFi | Ayarlar | Sinif | Ekran");
  USBSerial.println("[UI] Yan PWR: ayarlar | Ekran kapat: son sayfa (buyuk tus)");

  pinMode(BTN_BOOT, INPUT_PULLUP);
  loadNetPrefs();

  Wire.begin(I2C_SDA_PIN, I2C_SCL_PIN);
  Wire.setClock(100000);

  pmic_init_for_audio();
  lcd_init();
  es8311_init_dac();
  es7210_init_full();
  i2s_init_mic();

  WiFi.mode(WIFI_STA);
  WiFi.begin(wifi_ssid, wifi_pass);
  uint32_t t0 = millis();
  while (WiFi.status() != WL_CONNECTED && millis() - t0 < 12000) {
    delay(300);
    USBSerial.print(".");
  }
  if (WiFi.status() == WL_CONNECTED) {
    USBSerial.printf("\n[OK] WiFi IP: %s\n", WiFi.localIP().toString().c_str());
    syncNtpTime();
    USBSerial.println("[DISCOVER] sunucu araniyor...");
    if (discoverServerPublic()) {
      USBSerial.println("[DISCOVER] otomatik baglanti OK");
    } else {
      webSocket.begin(ws_server, ws_port, ws_path);
      webSocket.onEvent(webSocketEvent);
      webSocket.setReconnectInterval(3000);
    }
    g_uiPage = UI_PAGE_HOME;
  } else {
    USBSerial.printf("\n[WIFI] SoftAP %s\n", AP_SSID);
    startConfigPortalPublic();
  }
  drawFace(STATE_IDLE);
}

void loop() {
  PMIC.getIrqStatus();
  if (PMIC.isPekeyShortPressIrq() || PMIC.isPekeyLongPressIrq()) {
    ui_on_pmic_key();
    PMIC.clearIrqStatus();
  } else {
    PMIC.clearIrqStatus();
  }

  if (g_configMode) {
    dnsServer.processNextRequest();
    configServer.handleClient();
    pollDilControls();
    return;
  }

  if (g_screenOff || g_listenPaused) {
    webSocket.loop();
    pollDilControls();
    delay(30);
    return;
  }

  bool audioPath = g_playbackActive || currentState == STATE_SPEAKING || playRingUsed() > 0;
  if (audioPath) {
    for (int i = 0; i < 16; i++) {
      webSocket.loop();
      processPlayback();
    }
    int16_t trash[128];
    size_t br = 0;
    i2s_read(I2S_NUM_0, trash, sizeof(trash), &br, 0);
    return;
  }

  pollDilControls();
  animateFaceIfNeeded();
  webSocket.loop();
  processPlayback();

  if (!webSocket.isConnected()) {
    setDeviceState(STATE_IDLE);
    static uint32_t lastDiscover = 0;
    if (WiFi.status() == WL_CONNECTED && millis() - lastDiscover > 12000) {
      lastDiscover = millis();
      USBSerial.println("[DISCOVER] tekrar deneniyor...");
      discoverServerPublic();
    }
    return;
  }

  static uint32_t thinkingSince = 0;
  if (currentState == STATE_THINKING || g_serverThinking) {
    if (!thinkingSince) thinkingSince = millis();
    if (millis() - thinkingSince > 50000UL) {
      USBSerial.println("[UI] thinking timeout → listening");
      g_serverThinking = false;
      g_micTransmitAllowed = true;
      g_micCooldownUntil = millis() + 400;
      thinkingSince = 0;
      setDeviceState(STATE_LISTENING);
    }
  } else {
    thinkingSince = 0;
  }

  if (!g_playbackActive && !g_serverThinking && currentState != STATE_SPEAKING) {
    if (currentState != STATE_THINKING) {
      setDeviceState(STATE_LISTENING);
    }
  }

  if (g_micCooldownUntil != 0 && (int32_t)(millis() - g_micCooldownUntil) >= 0) {
    g_micCooldownUntil = 0;
    if (!g_playbackActive && !g_serverThinking) {
      g_micTransmitAllowed = true;
      flushMicDma();
    }
  }

  if (!g_micTransmitAllowed || g_serverThinking || g_micCooldownUntil != 0) {
    int16_t trash[128];
    size_t bytes_read = 0;
    i2s_read(I2S_NUM_0, trash, sizeof(trash), &bytes_read, 0);
    return;
  }

  static int16_t stereo_buf[I2S_READ_BYTES / 2];
  static int16_t mono_buf[I2S_READ_BYTES / 4];
  size_t bytes_read = 0;

  esp_err_t err = i2s_read(I2S_NUM_0, stereo_buf, sizeof(stereo_buf), &bytes_read, pdMS_TO_TICKS(30));
  if (err != ESP_OK || bytes_read == 0) return;

  size_t samples = bytes_read / sizeof(int16_t);
  size_t frames  = samples / 2;
  uint32_t absAcc = 0;
  for (size_t i = 0; i < frames; i++) {
    int32_t s = applySoftwareAEC(stereo_buf[i * 2]);
    s = (s * 3);
    if (s > 32767) s = 32767;
    if (s < -32768) s = -32768;
    mono_buf[i] = (int16_t)s;
    int32_t a = s;
    if (a < 0) a = -a;
    absAcc += (uint32_t)a;
  }
  if (frames > 0) {
    uint32_t avg = absAcc / (uint32_t)frames;
    uint16_t lvl = (uint16_t)(avg / 60);
    if (lvl > 100) lvl = 100;
    g_micLevel = lvl;
  }

  webSocket.sendBIN((uint8_t*)mono_buf, frames * sizeof(int16_t));
}

