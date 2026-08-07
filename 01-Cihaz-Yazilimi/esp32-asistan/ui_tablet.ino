/*
 * MEB AI — Tablet arayuz (ayri dosya)
 * Sayfalar: Ana | Yaz (soru) | Takvim | WiFi | Ayarlar
 * Kaydir / noktalara dokun / BOOT kisa = sonraki sayfa
 * Yan PWR kisa = Ayarlar | Ekran kapat = Sinif'tan sonraki sayfa
 */

static String uiSsid;
static String uiPass;
static String uiHost;
static String uiAskText;
static int uiField = 0;
static bool uiKbUpper = false;
static bool uiKbSymbol = false;
static bool uiWifiKbOpen = false;
static String uiStatusMsg = "";
static int uiLastMin = -1;
static uint32_t uiScreenOffArmMs = 0;

static void uiChip(int x, int y, int w, int h, uint16_t fill, uint16_t border) {
  gfx->fillRoundRect(x, y, w, h, 10, fill);
  gfx->drawRoundRect(x, y, w, h, 10, border);
}

static void uiResumeListen() {
  g_listenPaused = false;
  g_micTransmitAllowed = true;
  g_micCooldownUntil = millis() + 400;
  sendListenConfig(true);
  if (webSocket.isConnected()) setDeviceState(STATE_LISTENING);
}

static void uiScreenOn() {
  g_screenOff = false;
  digitalWrite(TFT_BL, HIGH);
  drawFace(currentState == STATE_UNKNOWN ? STATE_IDLE : currentState);
}

static void uiScreenOff() {
  g_screenOff = true;
  g_listenPaused = true;
  g_micTransmitAllowed = false;
  g_playbackActive = false;
  digitalWrite(TFT_BL, LOW);
  sendListenConfig(false);
  setDeviceState(STATE_IDLE);
  USBSerial.println("[UI] Ekran+dinleme KAPALI — ayar tusu (kisa PWR) ile ac");
}

void ui_on_pmic_key() {
  static uint32_t lastKeyMs = 0;
  uint32_t now = millis();
  if (now - lastKeyMs < 400) return;

  bool isShort = PMIC.isPekeyShortPressIrq();
  bool isLong = PMIC.isPekeyLongPressIrq();

  if (g_screenOff || g_listenPaused) {
    if (isShort || isLong) {
      lastKeyMs = now;
      uiScreenOn();
      g_uiPage = UI_PAGE_SETTINGS;
      uiResumeListen();
      drawFace(currentState == STATE_UNKNOWN ? STATE_LISTENING : currentState);
      USBSerial.println("[UI] Ayar tusu: dinleme yeniden acildi");
    }
    return;
  }

  if (isShort || (isLong && isShort)) {
    lastKeyMs = now;
    g_uiPage = UI_PAGE_SETTINGS;
    drawFace(currentState == STATE_UNKNOWN ? STATE_IDLE : currentState);
    return;
  }
  if (isLong) {
    USBSerial.println("[UI] PWR long yok sayildi (ekran kapatma sadece Ayarlar)");
  }
}

static void uiTopBar() {
  gfx->fillRect(0, 0, 240, 36, g_bgColor);
  gfx->drawFastHLine(0, 35, 240, 0x0A2A);

  gfx->setTextSize(1);
  gfx->setTextColor(WHITE);
  gfx->setCursor(12, 14);
  gfx->print("MEB");
  gfx->setTextColor(ACCENT);
  gfx->print(" AI");
  gfx->setTextColor(MUTED);
  gfx->print("  Asistan");

  char saat[8] = "--:--";
  struct tm ti;
  if (g_timeSynced && getLocalTime(&ti, 0)) {
    snprintf(saat, sizeof(saat), "%02d:%02d", ti.tm_hour, ti.tm_min);
  }
  gfx->setTextSize(1);
  gfx->setTextColor(WHITE);
  gfx->setCursor(188, 14);
  gfx->print(saat);
}

static void uiDots(int active) {
  gfx->fillRect(0, 258, 240, 26, g_bgColor);
  int start = 120 - (UI_PAGE_COUNT * 12);
  for (int i = 0; i < UI_PAGE_COUNT; i++) {
    int x = start + i * 24;
    if (i == active) gfx->fillCircle(x, 268, 5, ACCENT);
    else gfx->drawCircle(x, 268, 4, MUTED);
  }
}

static void uiHome(DeviceState state) {
  gfx->fillRoundRect(40, 55, 160, 130, 20, 0x0A2A);
  gfx->drawRoundRect(40, 55, 160, 130, 20, CHIP_OFF);

  if (g_uiBand == 0) {
    uint16_t face = (state == STATE_THINKING) ? AMBER
                   : (state == STATE_SPEAKING) ? MINT
                   : (state == STATE_LISTENING) ? ACCENT : 0xFE60;
    gfx->fillCircle(120, 105, 42, face);
    gfx->fillCircle(92, 112, 7, 0xFBAE);
    gfx->fillCircle(148, 112, 7, 0xFBAE);
    gfx->fillCircle(105, 96, 5, BG_DEEP);
    gfx->fillCircle(135, 96, 5, BG_DEEP);
    gfx->fillCircle(106, 95, 2, WHITE);
    gfx->fillCircle(136, 95, 2, WHITE);
    for (int i = -16; i <= 16; i++) {
      int y = 132 - (i * i) / 22;
      gfx->drawPixel(120 + i, y, BG_DEEP);
      gfx->drawPixel(120 + i, y + 1, BG_DEEP);
      gfx->drawPixel(120 + i, y + 2, BG_DEEP);
    }
    if (state == STATE_LISTENING) {
      gfx->drawCircle(120, 105, 48, WHITE);
      gfx->drawCircle(120, 105, 52, ACCENT);
    } else if (state == STATE_THINKING) {
      gfx->fillCircle(150, 72, 5, WHITE);
      gfx->fillCircle(160, 62, 3, WHITE);
    } else if (state == STATE_SPEAKING) {
      gfx->fillCircle(120, 105, 6, WHITE);
    }
    gfx->setTextColor(face);
  } else if (g_uiBand == 1) {
    if (state == STATE_LISTENING) {
      gfx->drawCircle(120, 110, 36, ACCENT);
      gfx->drawCircle(120, 110, 28, 0x07FF);
      gfx->fillCircle(120, 110, 14, ACCENT);
      gfx->fillCircle(120, 110, 6, WHITE);
      gfx->setTextColor(ACCENT);
    } else if (state == STATE_THINKING) {
      gfx->drawCircle(120, 110, 34, AMBER);
      gfx->fillCircle(120, 82, 7, AMBER);
      gfx->fillCircle(146, 118, 7, AMBER);
      gfx->fillCircle(94, 118, 7, AMBER);
      gfx->setTextColor(AMBER);
    } else if (state == STATE_SPEAKING) {
      for (int i = 0; i < 6; i++) {
        int h = 18 + ((i * 17) % 40);
        gfx->fillRoundRect(78 + i * 14, 110 - h / 2, 10, h, 4, MINT);
      }
      gfx->setTextColor(MINT);
    } else {
      gfx->drawCircle(120, 108, 32, MUTED);
      gfx->fillCircle(108, 100, 4, MUTED);
      gfx->fillCircle(132, 100, 4, MUTED);
      for (int i = -10; i <= 10; i++) {
        int y = 124 - (i * i) / 18;
        gfx->drawPixel(120 + i, y, MUTED);
      }
      gfx->setTextColor(MUTED);
    }
  } else {
    if (state == STATE_LISTENING) {
      gfx->fillCircle(120, 105, 28, ACCENT);
      gfx->fillRoundRect(108, 85, 24, 32, 8, WHITE);
      gfx->drawCircle(120, 125, 14, WHITE);
      gfx->setTextColor(ACCENT);
    } else if (state == STATE_THINKING) {
      gfx->fillCircle(120, 110, 26, AMBER);
      gfx->fillCircle(100, 110, 6, WHITE);
      gfx->fillCircle(120, 110, 6, WHITE);
      gfx->fillCircle(140, 110, 6, WHITE);
      gfx->setTextColor(AMBER);
    } else if (state == STATE_SPEAKING) {
      for (int i = 0; i < 5; i++) {
        int h = 20 + (i % 3) * 12;
        gfx->fillRoundRect(80 + i * 16, 110 - h / 2, 10, h, 3, MINT);
      }
      gfx->setTextColor(MINT);
    } else {
      gfx->fillCircle(100, 100, 8, MUTED);
      gfx->fillCircle(140, 100, 8, MUTED);
      gfx->drawCircle(120, 130, 16, MUTED);
      gfx->setTextColor(MUTED);
    }
  }

  gfx->setTextSize(1);
  const char* msg = "Hazir";
  if (state == STATE_LISTENING) msg = dilIngilizceMiPublic() ? "Listening" : "Dinliyorum";
  else if (state == STATE_THINKING) msg = dilIngilizceMiPublic() ? "Thinking" : "Dusunuyorum";
  else if (state == STATE_SPEAKING) msg = dilIngilizceMiPublic() ? "Speaking" : "Konusuyorum";
  else msg = dilIngilizceMiPublic() ? "Ready" : "Hazirim";
  int w = (int)strlen(msg) * 6;
  gfx->setCursor(120 - w / 2, 198);
  gfx->print(msg);
  if (g_ogrenciAd[0]) {
    char line[40];
    snprintf(line, sizeof(line), "%s", g_ogrenciAd);
    if (strlen(line) > 18) {
      line[18] = 0;
      line[17] = '.';
    }
    gfx->setTextColor(ACCENT);
    int aw = (int)strlen(line) * 6;
    gfx->setCursor(120 - aw / 2, 216);
    gfx->print(line);
  }
}

static void uiSinifPage() {
  gfx->setTextSize(2);
  gfx->setTextColor(WHITE);
  const char* baslik = dilIngilizceMiPublic() ? "Grade" : "Sinif";
  int baslikW = (int)strlen(baslik) * 12;
  gfx->setCursor(120 - baslikW / 2, 42);
  gfx->print(baslik);

  char cur[28];
  if (g_sinifNo == 0) snprintf(cur, sizeof(cur), "%s", dilIngilizceMiPublic() ? "All grades" : "Tumu");
  else snprintf(cur, sizeof(cur), "%d. sinif", (int)g_sinifNo);
  gfx->setTextSize(1);
  gfx->setTextColor(ACCENT);
  int cw = (int)strlen(cur) * 6;
  gfx->setCursor(120 - cw / 2, 68);
  gfx->print(cur);

  const char* band =
    g_sinifNo == 0 ? (dilIngilizceMiPublic() ? "Mixed books" : "Karisik kitaplar") :
    g_uiBand == 0 ? (dilIngilizceMiPublic() ? "Primary" : "Ilkokul") :
    g_uiBand == 1 ? (dilIngilizceMiPublic() ? "Middle" : "Ortaokul") :
                    (dilIngilizceMiPublic() ? "High" : "Lise");
  gfx->setTextColor(MUTED);
  int bw = (int)strlen(band) * 6;
  gfx->setCursor(120 - bw / 2, 84);
  gfx->print(band);

  bool tumuOn = (g_sinifNo == 0);
  const int chipX = 40, chipW = 160;
  uiChip(chipX, 100, chipW, 28, tumuOn ? 0x0A2A : 0x0841, tumuOn ? ACCENT : CHIP_OFF);
  gfx->setTextColor(tumuOn ? ACCENT : WHITE);
  const char* tumuTxt = dilIngilizceMiPublic() ? "ALL" : "TUMU";
  int tw = (int)strlen(tumuTxt) * 6;
  gfx->setCursor(chipX + (chipW - tw) / 2, 108);
  gfx->print(tumuTxt);

  for (int i = 0; i < 12; i++) {
    int col = i % 4;
    int row = i / 4;
    int x = 28 + col * 48;
    int y = 138 + row * 36;
    int sn = i + 1;
    bool on = (sn == g_sinifNo);
    uiChip(x, y, 40, 30, on ? 0x0A2A : 0x0841, on ? ACCENT : CHIP_OFF);
    gfx->setTextSize(1);
    gfx->setTextColor(on ? ACCENT : WHITE);
    char t[4];
    snprintf(t, sizeof(t), "%d", sn);
    gfx->setCursor(x + (sn < 10 ? 16 : 12), y + 10);
    gfx->print(t);
  }
}

static bool uiHandleSinifTap(int16_t x, int16_t y) {
  if (x >= 40 && x < 200 && y >= 100 && y < 128) {
    sendSinifConfig(0);
    return true;
  }
  for (int i = 0; i < 12; i++) {
    int col = i % 4;
    int row = i / 4;
    int bx = 28 + col * 48;
    int by = 138 + row * 36;
    if (x >= bx && x < bx + 40 && y >= by && y < by + 30) {
      sendSinifConfig(i + 1);
      return true;
    }
  }
  return false;
}

static void uiCalendar() {
  struct tm ti;
  bool ok = g_timeSynced && getLocalTime(&ti, 0);
  int year = ok ? (ti.tm_year + 1900) : 2026;
  int month = ok ? (ti.tm_mon + 1) : 8;
  int today = ok ? ti.tm_mday : 1;

  gfx->setTextSize(2);
  gfx->setTextColor(WHITE);
  gfx->setCursor(60, 50);
  char title[24];
  snprintf(title, sizeof(title), "%02d / %d", month, year);
  gfx->print(title);

  struct tm t0 = {};
  t0.tm_year = year - 1900;
  t0.tm_mon = month - 1;
  t0.tm_mday = 1;
  time_t e = mktime(&t0);
  struct tm* p = localtime(&e);
  int startW = p ? p->tm_wday : 0;
  static const int mdays[] = {31,28,31,30,31,30,31,31,30,31,30,31};
  int dim = mdays[month - 1];
  if (month == 2 && ((year % 4) == 0)) dim = 29;

  const char* wd = "P S C P C C P";
  gfx->setTextSize(1);
  gfx->setTextColor(MUTED);
  gfx->setCursor(28, 80);
  gfx->print(wd);

  int day = 1;
  for (int row = 0; row < 6; row++) {
    for (int col = 0; col < 7; col++) {
      int idx = row * 7 + col;
      if (idx < startW || day > dim) continue;
      int x = 24 + col * 28;
      int y = 100 + row * 22;
      if (day == today) {
        gfx->fillRoundRect(x - 4, y - 2, 22, 18, 4, ACCENT);
        gfx->setTextColor(0x0126);
      } else {
        gfx->setTextColor(WHITE);
      }
      gfx->setCursor(x, y);
      gfx->print(day);
      day++;
    }
  }
}

static void uiEnsureWifiFields() {
  if (uiSsid.length() == 0 && uiHost.length() == 0) {
    uiSsid = String(wifi_ssid);
    uiPass = String(wifi_pass);
    uiHost = String(ws_server);
  }
}

static void uiDrawKeyboard(int y0) {
  const char* rows[3];
  if (uiKbSymbol) {
    rows[0] = "1234567890";
    rows[1] = "-/:;()$&@\"";
    rows[2] = ".,?!'_+=#*";
  } else if (uiKbUpper) {
    rows[0] = "QWERTYUIOP";
    rows[1] = "ASDFGHJKL";
    rows[2] = "ZXCVBNM";
  } else {
    rows[0] = "qwertyuiop";
    rows[1] = "asdfghjkl";
    rows[2] = "zxcvbnm";
  }

  for (int r = 0; r < 3; r++) {
    int n = (int)strlen(rows[r]);
    int kw = 22;
    int total = n * kw;
    int x0 = (240 - total) / 2;
    for (int i = 0; i < n; i++) {
      int x = x0 + i * kw;
      int y = y0 + r * 22;
      gfx->fillRoundRect(x + 1, y, kw - 2, 20, 3, 0x2945);
      gfx->setTextSize(1);
      gfx->setTextColor(WHITE);
      gfx->setCursor(x + 7, y + 6);
      gfx->print(rows[r][i]);
    }
  }
  int y = y0 + 66;
  uiChip(8, y, 50, 22, CHIP_OFF, MUTED);
  gfx->setTextColor(WHITE);
  gfx->setCursor(18, y + 7);
  gfx->print(uiKbSymbol ? "ABC" : "123");

  uiChip(62, y, 50, 22, CHIP_OFF, MUTED);
  gfx->setCursor(72, y + 7);
  gfx->print(uiKbUpper ? "abc" : "ABC");

  uiChip(116, y, 60, 22, CHIP_OFF, MUTED);
  gfx->setCursor(128, y + 7);
  gfx->print("space");

  uiChip(180, y, 52, 22, AMBER, WHITE);
  gfx->setCursor(192, y + 7);
  gfx->print("<--");
}

static bool uiKeyboardTap(int16_t x, int16_t y, int y0, String* target) {
  const char* rows[3];
  if (uiKbSymbol) {
    rows[0] = "1234567890";
    rows[1] = "-/:;()$&@\"";
    rows[2] = ".,?!'_+=#*";
  } else if (uiKbUpper) {
    rows[0] = "QWERTYUIOP";
    rows[1] = "ASDFGHJKL";
    rows[2] = "ZXCVBNM";
  } else {
    rows[0] = "qwertyuiop";
    rows[1] = "asdfghjkl";
    rows[2] = "zxcvbnm";
  }
  for (int r = 0; r < 3; r++) {
    int n = (int)strlen(rows[r]);
    int kw = 22;
    int total = n * kw;
    int x0 = (240 - total) / 2;
    int rowY = y0 + r * 22;
    if (y < rowY || y >= rowY + 22) continue;
    int i = (x - x0) / kw;
    if (i >= 0 && i < n) {
      if (target->length() < 160) *target += rows[r][i];
      return true;
    }
  }
  int fy = y0 + 66;
  if (y >= fy && y < fy + 24) {
    if (x < 58) { uiKbSymbol = !uiKbSymbol; return true; }
    if (x < 112) { uiKbUpper = !uiKbUpper; uiKbSymbol = false; return true; }
    if (x < 176) {
      if (target->length() < 160) *target += ' ';
      return true;
    }
    if (target->length()) target->remove(target->length() - 1);
    return true;
  }
  return false;
}

static void uiAskSend() {
  uiAskText.trim();
  if (uiAskText.length() < 2) return;
  if (!webSocket.isConnected()) {
    strncpy(g_lastCevap, dilIngilizceMiPublic() ? "Not connected to server." : "Sunucuya bagli degil.", sizeof(g_lastCevap) - 1);
    g_askShowAnswer = true;
    drawFace(STATE_IDLE);
    return;
  }
  g_textAskPending = true;
  g_askShowAnswer = false;
  strncpy(g_lastSoru, uiAskText.c_str(), sizeof(g_lastSoru) - 1);
  g_lastSoru[sizeof(g_lastSoru) - 1] = 0;
  g_lastCevap[0] = 0;

  String esc;
  for (unsigned i = 0; i < uiAskText.length(); i++) {
    char c = uiAskText[i];
    if (c == '"' || c == '\\') esc += '\\';
    if (c == '\n') { esc += ' '; continue; }
    esc += c;
  }
  String msg = String("{\"type\":\"ask\",\"soru\":\"") + esc +
               "\",\"dil\":\"" + dil_ayari + "\"}";
  webSocket.sendTXT(msg);
  setDeviceState(STATE_THINKING);
  USBSerial.printf("[ASK] gonderildi: %s\n", uiAskText.c_str());
}

static void uiAskPage() {
  gfx->setTextSize(2);
  gfx->setTextColor(WHITE);
  gfx->setCursor(78, 42);
  gfx->print(dilIngilizceMiPublic() ? "Ask" : "Yaz");

  if (g_askShowAnswer && g_lastCevap[0]) {
    uiChip(12, 68, 216, 120, 0x0A2A, ACCENT);
    gfx->setTextSize(1);
    gfx->setTextColor(MUTED);
    gfx->setCursor(20, 76);
    gfx->print(dilIngilizceMiPublic() ? "Q:" : "Soru:");
    gfx->setTextColor(WHITE);
    gfx->setCursor(20, 90);
    String qs = String(g_lastSoru);
    if (qs.length() > 34) qs = qs.substring(0, 34) + "..";
    gfx->print(qs);
    gfx->setTextColor(MUTED);
    gfx->setCursor(20, 110);
    gfx->print(dilIngilizceMiPublic() ? "A:" : "Cevap:");
    gfx->setTextColor(WHITE);
    String a = String(g_lastCevap);
    int line = 0;
    while (a.length() && line < 5) {
      String chunk = a.substring(0, 34);
      int sp = chunk.lastIndexOf(' ');
      if (sp > 20 && a.length() > 34) {
        chunk = a.substring(0, sp);
        a = a.substring(sp + 1);
      } else {
        a = a.substring(chunk.length());
      }
      gfx->setCursor(20, 124 + line * 12);
      gfx->print(chunk);
      line++;
    }
    uiChip(20, 200, 90, 36, CHIP_OFF, WHITE);
    gfx->setTextColor(WHITE);
    gfx->setCursor(38, 212);
    gfx->print(dilIngilizceMiPublic() ? "New" : "Yeni");
    uiChip(130, 200, 90, 36, CHIP_ON, WHITE);
    gfx->setTextColor(0x0126);
    gfx->setCursor(148, 212);
    gfx->print(dilIngilizceMiPublic() ? "Again" : "Tekrar");
    return;
  }

  uiChip(12, 68, 216, 40, 0x0A2A, ACCENT);
  gfx->setTextSize(1);
  gfx->setTextColor(MUTED);
  gfx->setCursor(20, 74);
  gfx->print(dilIngilizceMiPublic() ? "Your question" : "Sorunu yaz");
  gfx->setTextColor(WHITE);
  gfx->setCursor(20, 90);
  String show = uiAskText;
  if (show.length() > 34) show = show.substring(show.length() - 34);
  gfx->print(show.length() ? show : "|");

  uiChip(150, 114, 78, 26, CHIP_ON, WHITE);
  gfx->setTextColor(0x0126);
  gfx->setCursor(168, 122);
  gfx->print("SOR");

  if (g_textAskPending || currentState == STATE_THINKING) {
    gfx->setTextColor(AMBER);
    gfx->setCursor(20, 122);
    gfx->print(dilIngilizceMiPublic() ? "Thinking..." : "Dusunuyor...");
  }

  uiDrawKeyboard(148);
}

static void uiWifiPage() {
  uiEnsureWifiFields();
  bool ok = WiFi.status() == WL_CONNECTED;

  gfx->setTextSize(2);
  gfx->setTextColor(WHITE);
  gfx->setCursor(80, 44);
  gfx->print("WiFi");

  if (g_configMode) {
    uiChip(12, 70, 216, 160, 0x0A2A, ACCENT);
    gfx->setTextSize(1);
    gfx->setTextColor(MINT);
    gfx->setCursor(24, 88);
    gfx->print("PORTAL ACIK");
    gfx->setTextColor(WHITE);
    gfx->setCursor(24, 112);
    gfx->print("Telefonda WiFi:");
    gfx->setTextColor(ACCENT);
    gfx->setCursor(24, 132);
    gfx->print(AP_SSID);
    gfx->setTextColor(WHITE);
    gfx->setCursor(24, 152);
    gfx->printf("Pass: %s", AP_PASS);
    gfx->setCursor(24, 176);
    gfx->print("Sonra tarayici:");
    gfx->setCursor(24, 196);
    gfx->print("192.168.4.1");
    return;
  }

  if (uiWifiKbOpen) {
    const char* lab =
      uiField == 1 ? (dilIngilizceMiPublic() ? "Password" : "Sifre") :
      uiField == 2 ? (dilIngilizceMiPublic() ? "Server IP" : "Sunucu IP") :
                     "SSID";
    String val = uiField == 1 ? uiPass : (uiField == 2 ? uiHost : uiSsid);

    uiChip(12, 68, 150, 40, 0x0A2A, ACCENT);
    gfx->setTextSize(1);
    gfx->setTextColor(MUTED);
    gfx->setCursor(20, 74);
    gfx->print(lab);
    gfx->setTextColor(WHITE);
    gfx->setCursor(20, 90);
    if (uiField == 1 && val.length()) {
      for (unsigned i = 0; i < val.length() && i < 18; i++) gfx->print('*');
    } else {
      if (val.length() > 22) val = val.substring(val.length() - 22);
      gfx->print(val.length() ? val : "|");
    }

    uiChip(168, 68, 60, 40, CHIP_ON, WHITE);
    gfx->setTextColor(0x0126);
    gfx->setCursor(178, 82);
    gfx->print("OK");

    uiDrawKeyboard(148);
    return;
  }

  auto field = [&](int idx, int y, const char* label, const String& val, bool mask) {
    bool sel = (uiField == idx);
    uiChip(12, y, 216, 28, sel ? 0x0E3A : 0x0A2A, sel ? ACCENT : MUTED);
    gfx->setTextSize(1);
    gfx->setTextColor(MUTED);
    gfx->setCursor(20, y + 4);
    gfx->print(label);
    gfx->setTextColor(WHITE);
    gfx->setCursor(20, y + 15);
    if (mask && val.length()) {
      for (unsigned i = 0; i < val.length() && i < 18; i++) gfx->print('*');
    } else {
      String v = val;
      if (v.length() > 22) v = v.substring(0, 22);
      gfx->print(v.length() ? v : (dilIngilizceMiPublic() ? "tap to type" : "yazmak icin dokun"));
    }
  };

  field(0, 68, "SSID (ag adi)", uiSsid, false);
  field(1, 100, "Sifre", uiPass, true);
  field(2, 132, "Sunucu IP (opsiyonel)", uiHost, false);

  gfx->setTextSize(1);
  gfx->setTextColor(ok ? MINT : AMBER);
  gfx->setCursor(14, 166);
  if (uiStatusMsg.length()) gfx->print(uiStatusMsg.substring(0, 34));
  else gfx->print(ok ? "Bagli" : "Alanlara dokun, sonra BAGLAN");

  uiChip(12, 182, 100, 32, CHIP_ON, WHITE);
  gfx->setTextColor(0x0126);
  gfx->setCursor(32, 192);
  gfx->print("BAGLAN");

  uiChip(120, 182, 108, 32, ACCENT, WHITE);
  gfx->setTextColor(0x0126);
  gfx->setCursor(132, 192);
  gfx->print(dilIngilizceMiPublic() ? "FIND PC" : "SUNUCUYU BUL");

  uiChip(12, 220, 216, 30, CHIP_OFF, MUTED);
  gfx->setTextColor(MUTED);
  gfx->setCursor(40, 230);
  gfx->print(dilIngilizceMiPublic() ? "Phone portal (easy setup)" : "Telefon portal (kolay kurulum)");
}

static const uint16_t kUiBgSwatch[] = {
  0x0169, 0x0000, 0x10B4, 0x0320, 0x480A
};

static void uiSettings() {
  gfx->setTextSize(2);
  gfx->setTextColor(WHITE);
  gfx->setCursor(60, 44);
  gfx->print(dilIngilizceMiPublic() ? "Settings" : "Ayarlar");

  uiChip(20, 72, 90, 34, dilIngilizceMiPublic() ? CHIP_OFF : CHIP_ON, WHITE);
  gfx->setTextSize(2);
  gfx->setTextColor(WHITE);
  gfx->setCursor(48, 82);
  gfx->print("TR");

  uiChip(130, 72, 90, 34, dilIngilizceMiPublic() ? CHIP_ON : CHIP_OFF, WHITE);
  gfx->setCursor(158, 82);
  gfx->print("EN");

  gfx->setTextSize(1);
  gfx->setTextColor(MUTED);
  gfx->setCursor(20, 118);
  gfx->print(dilIngilizceMiPublic() ? "Background" : "Arka plan rengi");
  for (int i = 0; i < 5; i++) {
    int x = 20 + i * 40;
    gfx->fillRoundRect(x, 134, 34, 34, 8, kUiBgSwatch[i]);
    if (i == g_bgTheme) {
      gfx->drawRoundRect(x, 134, 34, 34, 8, WHITE);
      gfx->drawRoundRect(x + 1, 135, 32, 32, 7, ACCENT);
    } else {
      gfx->drawRoundRect(x, 134, 34, 34, 8, MUTED);
    }
  }

  uiChip(12, 178, 216, 70, CHIP_ON, WHITE);
  gfx->setTextSize(2);
  gfx->setTextColor(0x0126);
  gfx->setCursor(28, 192);
  gfx->print(dilIngilizceMiPublic() ? "PHONE PORTAL" : "TELEFON PORTAL");
  gfx->setTextSize(1);
  gfx->setTextColor(0x0126);
  gfx->setCursor(28, 218);
  gfx->print(dilIngilizceMiPublic() ? "Opens setup WiFi AP" : "Kurulum WiFi AP acar");
  gfx->setCursor(28, 232);
  gfx->print(dilIngilizceMiPublic() ? "Tap here to start" : "Baslatmak icin dokun");
}

static void uiEkranPage() {
  gfx->setTextSize(2);
  gfx->setTextColor(WHITE);
  gfx->setCursor(58, 48);
  gfx->print(dilIngilizceMiPublic() ? "Screen" : "Ekran");

  gfx->setTextSize(1);
  gfx->setTextColor(MUTED);
  const char* hint = dilIngilizceMiPublic()
    ? "Turns off display + mic"
    : "Ekran ve dinlemeyi kapatir";
  int hw = (int)strlen(hint) * 6;
  gfx->setCursor(120 - hw / 2, 78);
  gfx->print(hint);

  bool armed = uiScreenOffArmMs != 0 && (millis() - uiScreenOffArmMs) < 2500;
  uiChip(16, 110, 208, 100, armed ? AMBER : 0x0A2A, armed ? WHITE : AMBER);
  gfx->setTextSize(2);
  gfx->setTextColor(armed ? BLACK : AMBER);
  if (armed) {
    gfx->setCursor(28, 148);
    gfx->print(dilIngilizceMiPublic() ? "Tap again!" : "Tekrar dokun!");
  } else {
    gfx->setCursor(36, 140);
    gfx->print(dilIngilizceMiPublic() ? "SCREEN OFF" : "EKRANI KAPAT");
    gfx->setTextSize(1);
    gfx->setTextColor(MUTED);
    gfx->setCursor(52, 172);
    gfx->print(dilIngilizceMiPublic() ? "Large button — tap twice" : "Buyuk tus — iki kez dokun");
  }
}

static bool uiHandleEkranTap(int16_t x, int16_t y) {
  if (x < 16 || x > 224 || y < 110 || y > 210) return false;
  uint32_t now = millis();
  if (uiScreenOffArmMs != 0 && (now - uiScreenOffArmMs) < 2500) {
    uiScreenOffArmMs = 0;
    uiScreenOff();
  } else {
    uiScreenOffArmMs = now;
  }
  return true;
}

void drawFace(DeviceState state) {
  if (g_screenOff) return;
  if (g_uiPage != UI_PAGE_WIFI) uiWifiKbOpen = false;
  gfx->fillScreen(g_bgColor);
  uiTopBar();

  if (g_uiPage == UI_PAGE_ASK) uiAskPage();
  else if (g_uiPage == UI_PAGE_CALENDAR) uiCalendar();
  else if (g_uiPage == UI_PAGE_WIFI) uiWifiPage();
  else if (g_uiPage == UI_PAGE_SETTINGS) uiSettings();
  else if (g_uiPage == UI_PAGE_SINIF) uiSinifPage();
  else if (g_uiPage == UI_PAGE_EKRAN) uiEkranPage();
  else uiHome(state);

  uiDots(g_uiPage);
}

static void uiWifiConnect() {
  uiStatusMsg = "Baglaniyor...";
  drawFace(STATE_IDLE);
  saveNetPrefsPublic(uiSsid, uiPass, uiHost, ws_port);
  WiFi.disconnect(true);
  delay(100);
  WiFi.mode(WIFI_STA);
  WiFi.begin(wifi_ssid, wifi_pass);
  uint32_t t0 = millis();
  while (WiFi.status() != WL_CONNECTED && millis() - t0 < 15000) {
    delay(250);
  }
  if (WiFi.status() == WL_CONNECTED) {
    uiStatusMsg = "Sunucu araniyor...";
    drawFace(STATE_IDLE);
    syncNtpTime();
    if (discoverServerPublic()) {
      uiHost = String(ws_server);
      uiStatusMsg = "Sunucu bulundu!";
    } else {
      reconnectWebSocket();
      uiStatusMsg = "Baglandi (eski IP)";
    }
    g_uiPage = UI_PAGE_HOME;
  } else {
    uiStatusMsg = "Basarisiz — sifreyi kontrol et";
  }
  drawFace(STATE_IDLE);
}

static bool uiHandleAskTap(int16_t x, int16_t y) {
  if (g_askShowAnswer && g_lastCevap[0]) {
    if (y >= 200 && y <= 240) {
      if (x < 120) {
        g_askShowAnswer = false;
        uiAskText = "";
        return true;
      }
      uiAskText = String(g_lastSoru);
      g_askShowAnswer = false;
      uiAskSend();
      return false;
    }
    return false;
  }
  if (y >= 114 && y < 142 && x >= 148) {
    uiAskSend();
    return false;
  }
  return uiKeyboardTap(x, y, 148, &uiAskText);
}

static bool uiHandleWifiTap(int16_t x, int16_t y) {
  if (g_configMode) return false;

  if (uiWifiKbOpen) {
    if (y >= 68 && y < 110 && x >= 168) {
      uiWifiKbOpen = false;
      return true;
    }
    String* t = &uiSsid;
    if (uiField == 1) t = &uiPass;
    else if (uiField == 2) t = &uiHost;
    return uiKeyboardTap(x, y, 148, t);
  }

  if (y >= 182 && y < 216 && x < 118) {
    uiWifiConnect();
    return false;
  }
  if (y >= 182 && y < 216 && x >= 118) {
    uiStatusMsg = "Araniyor...";
    drawFace(STATE_IDLE);
    if (discoverServerPublic()) {
      uiHost = String(ws_server);
      uiStatusMsg = "Sunucu bulundu!";
      g_uiPage = UI_PAGE_HOME;
    } else {
      uiStatusMsg = "Bulunamadi — uvicorn?";
    }
    drawFace(STATE_IDLE);
    return false;
  }
  if (y >= 220 && y < 252) {
    uiStatusMsg = "Portal aciliyor...";
    startConfigPortalPublic();
    return false;
  }
  if (y >= 68 && y < 96) { uiField = 0; uiWifiKbOpen = true; return true; }
  if (y >= 100 && y < 128) { uiField = 1; uiWifiKbOpen = true; return true; }
  if (y >= 132 && y < 160) { uiField = 2; uiWifiKbOpen = true; return true; }
  return false;
}

static void uiHandleSettingsTap(int16_t x, int16_t y) {
  if (y >= 72 && y <= 106) {
    if (x < 120) setDilEnglishPublic(false);
    else setDilEnglishPublic(true);
    return;
  }
  if (y >= 134 && y <= 168) {
    for (int i = 0; i < 5; i++) {
      int bx = 20 + i * 40;
      if (x >= bx && x < bx + 34) {
        saveBgTheme((int8_t)i);
        drawFace(currentState == STATE_UNKNOWN ? STATE_IDLE : currentState);
        return;
      }
    }
  }
  if (y >= 178 && y <= 248 && x >= 12 && x <= 228) {
    uiStatusMsg = "Portal aciliyor...";
    startConfigPortalPublic();
  }
}

void pollDilControls() {
  while (USBSerial.available() > 0) {
    String cmd = USBSerial.readStringUntil('\n');
    cmd.trim();
    if (cmd.equalsIgnoreCase("EN")) setDilEnglishPublic(true);
    else if (cmd.equalsIgnoreCase("TR")) setDilEnglishPublic(false);
  }

  static bool touching = false;
  static int16_t startX = 0, startY = 0, lastX = 0, lastY = 0;
  static uint32_t lastTap = 0;
  int16_t tx = 0, ty = 0;
  bool down = readTouchXYPublic(tx, ty);

  if (g_screenOff) {
    if (down) uiScreenOn();
    return;
  }

  if (down) {
    if (!touching) {
      touching = true;
      startX = lastX = tx;
      startY = lastY = ty;
    } else {
      lastX = tx;
      lastY = ty;
    }
  } else if (touching) {
    touching = false;
    int dx = lastX - startX;
    int dy = lastY - startY;
    int adx = dx < 0 ? -dx : dx;
    int ady = dy < 0 ? -dy : dy;

    if (adx > 50 && adx > ady && !g_playbackActive) {
      if (dx < 0 && g_uiPage < UI_PAGE_COUNT - 1) g_uiPage++;
      else if (dx > 0 && g_uiPage > 0) g_uiPage--;
      drawFace(currentState == STATE_UNKNOWN ? STATE_IDLE : currentState);
      return;
    }

    if (adx < 22 && ady < 22 && (millis() - lastTap) > 280) {
      lastTap = millis();
      if (lastY >= 255) {
        int slot = lastX / (240 / UI_PAGE_COUNT);
        if (slot < 0) slot = 0;
        if (slot >= UI_PAGE_COUNT) slot = UI_PAGE_COUNT - 1;
        g_uiPage = slot;
        drawFace(currentState == STATE_UNKNOWN ? STATE_IDLE : currentState);
        return;
      }
      if (g_uiPage == UI_PAGE_ASK) {
        if (uiHandleAskTap(lastX, lastY)) {
          drawFace(currentState == STATE_UNKNOWN ? STATE_IDLE : currentState);
        }
      } else if (g_uiPage == UI_PAGE_WIFI) {
        if (uiHandleWifiTap(lastX, lastY)) {
          drawFace(currentState == STATE_UNKNOWN ? STATE_IDLE : currentState);
        }
      } else if (g_uiPage == UI_PAGE_SETTINGS) {
        uiHandleSettingsTap(lastX, lastY);
      } else if (g_uiPage == UI_PAGE_SINIF) {
        if (uiHandleSinifTap(lastX, lastY)) {
          drawFace(currentState == STATE_UNKNOWN ? STATE_IDLE : currentState);
        }
      } else if (g_uiPage == UI_PAGE_EKRAN) {
        if (uiHandleEkranTap(lastX, lastY)) {
          if (!g_screenOff) {
            drawFace(currentState == STATE_UNKNOWN ? STATE_IDLE : currentState);
          }
        }
      }
    }
  }

  static bool lastBoot = true;
  static uint32_t bootDownAt = 0;
  bool boot = digitalRead(BTN_BOOT);
  if (lastBoot && !boot) bootDownAt = millis();
  if (!lastBoot && boot && bootDownAt > 0) {
    uint32_t held = millis() - bootDownAt;
    if (held > 40 && held < 1200 && !g_playbackActive) {
      g_uiPage = (g_uiPage + 1) % UI_PAGE_COUNT;
      drawFace(currentState == STATE_UNKNOWN ? STATE_IDLE : currentState);
    }
    bootDownAt = 0;
  }
  if (boot) bootDownAt = 0;
  lastBoot = boot;
}

void animateFaceIfNeeded() {
  if (g_screenOff || g_uiPage != UI_PAGE_HOME) return;
  if (g_playbackActive || currentState == STATE_SPEAKING) return;
  struct tm ti;
  if (!(g_timeSynced && getLocalTime(&ti, 0))) return;
  if (ti.tm_min == uiLastMin) return;
  uiLastMin = ti.tm_min;
  drawFace(currentState == STATE_UNKNOWN ? STATE_IDLE : currentState);
}
