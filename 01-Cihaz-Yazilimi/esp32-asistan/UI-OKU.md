# Device UI

Sketch files in this folder are compiled together in Arduino IDE.

| File | Role |
|------|------|
| `esp32-asistan.ino` | Wi-Fi, audio, WebSocket, power |
| `ui_tablet.ino` | Touch UI pages |
| `wifi_local.h.example` | Copy to `wifi_local.h` for local credentials |

## Pages

Home · Ask · Calendar · Wi-Fi · Settings · Grade · Screen off

Network credentials are loaded from `wifi_local.h` (gitignored) or the on-device setup AP.
