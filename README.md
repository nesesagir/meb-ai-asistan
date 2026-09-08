# MEB AI Asistan

End-to-end voice assistant prototype for education content: ESP32 client, FastAPI backend with RAG, and a small web dashboard.

## Architecture

```
ESP32 (mic / speaker / UI)
        │ WebSocket
        ▼
FastAPI  →  STT → RAG (Qdrant) → LLM → TTS
        │
        ▼
Web dashboard (parent / teacher)
```

| Path | Role |
|------|------|
| `01-Cihaz-Yazilimi/` | ESP32 firmware |
| `02-Backend-Sunucu/` | API, voice pipeline, dashboard host |
| `03-Veri-RAG/dokumantasyon/` | How book data is prepared |
| `04-Dashboard-Web/` | Dashboard UI |
| `05-Donanim-PCB/` | Custom 50×72 mm PCB (EasyEDA Standard) |
| `06-Kasa-3D/` | 58×90×20 mm case (OpenSCAD / STL) |

Large book/vector dumps are not in this repo; rebuild them locally when needed.

There is no hosted demo. Run the backend locally and flash the ESP32 to try the assistant.

## On the device

ESP32 client on hardware (prototype photos):

| Ready | Type a question | Grade |
| --- | --- | --- |
| ![Hazırım](docs/cihaz/hazirim.png) | ![Yaz](docs/cihaz/yaz.png) | ![Sınıf](docs/cihaz/sinif.png) |

## Setup

### Backend

1. Copy `02-Backend-Sunucu/.env.example` → `.env` and set `GROQ_API_KEY`
2. Start Qdrant on `localhost:6333`
3. Create a venv, install `requirements.txt`
4. Run:

```bash
uvicorn main:app --host 0.0.0.0 --port 8001
```

Dashboard: `http://127.0.0.1:8001/dashboard/`

### Device

1. Copy `01-Cihaz-Yazilimi/esp32-asistan/wifi_local.h.example` → `wifi_local.h`
2. Fill Wi-Fi SSID/password and backend host IP
3. Flash `esp32-asistan` with Arduino IDE

`wifi_local.h` and `.env` are gitignored.

## Hardware

Custom board, not a devkit. Locked envelope:

- PCB **50 × 72 × 1.6 mm**, 4 layers, Type-C on the bottom edge (center)
- ESP32-S3-WROOM-1 on the **top / screen** side; antenna keep-out is the top 15 mm
- M2 holes Ø2.2 mm at (4,10) (46,10) (4,50) (46,50) from the Type-C bottom-left origin
- Case target **58 × 90 × 20 mm**; battery **35 × 34 × 6.5 mm** on the back, between the four bosses
- Mechanical check file: `05-Donanim-PCB/easyeda/MEB-AI-Asistan-PCB-mekanik.scad`

Production Gerbers live at JLCPCB, not in this repo.

## Stack

Python · FastAPI · Qdrant · Groq · Edge TTS · ESP32 · EasyEDA · OpenSCAD · JavaScript
