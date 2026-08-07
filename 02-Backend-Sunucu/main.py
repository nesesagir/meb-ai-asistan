from __future__ import annotations

import array
import asyncio
import json
import os
import secrets
import socket
import threading
import time
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, File, Header, HTTPException, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

load_dotenv(Path(__file__).resolve().parent / ".env")

import db as chat_db
import pipeline as pl

app = FastAPI(title="MEB AI Asistan", version="0.5.0")

_sessions: dict[str, dict] = {}
_device_status = {"value": "idle", "updated": 0.0}
_device_ws: WebSocket | None = None
_device_listen = True

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

SAMPLE_RATE = 16000
SILENCE_RMS = float(os.getenv("SILENCE_RMS", "70"))
SILENCE_MS = int(os.getenv("SILENCE_MS", "650"))
MIN_SPEECH_BYTES = int(os.getenv("MIN_SPEECH_BYTES", str(int(SAMPLE_RATE * 2 * 0.7))))
MAX_UTTERANCE_BYTES = SAMPLE_RATE * 2 * 8  # 8 sn sert tavan
PCM_CHUNK = 4096
POST_SPEECH_IGNORE_MS = int(os.getenv("POST_SPEECH_IGNORE_MS", "1800"))
MIN_VOICED_CHUNKS = int(os.getenv("MIN_VOICED_CHUNKS", "16"))  # ~0.25 sn
SPEECH_PEAK_MIN = float(os.getenv("SPEECH_PEAK_MIN", "55"))  # sadece tam sessizligi at

class SoruIstegi(BaseModel):
    soru: str
    dil: str = "Türkçe"

class LoginIstegi(BaseModel):
    username: str
    password: str

class AyarIstegi(BaseModel):
    dil: str | None = None
    stt_model: str | None = None
    tts_voice_tr: str | None = None
    tts_voice_en: str | None = None
    llm_provider: str | None = None
    llm_model: str | None = None
    score_threshold: str | None = None
    sinif: str | None = None

class ProfilIstegi(BaseModel):
    ad: str = ""
    sinif: int = 1

class OgrenciSecIstegi(BaseModel):
    ogrenci_id: int

class SinifIstegi(BaseModel):
    ogrenci_id: int
    sinif: int

def _user_from_auth(authorization: str | None) -> dict:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Giris gerekli")
    token = authorization.removeprefix("Bearer ").strip()
    user = _sessions.get(token)
    if not user:
        raise HTTPException(status_code=401, detail="Oturum gecersiz")
    return user

def _apply_settings_to_runtime(ayarlar: dict[str, str]) -> None:
    if "score_threshold" in ayarlar:
        try:
            pl.SCORE_THRESHOLD = float(ayarlar["score_threshold"])
        except ValueError:
            pass
    if ayarlar.get("llm_provider"):
        pl.LLM_PROVIDER = ayarlar["llm_provider"].strip().lower()
    if ayarlar.get("llm_model"):
        pl.GROQ_LLM_MODEL = ayarlar["llm_model"]
    if ayarlar.get("tts_voice_tr"):
        pl.TTS_VOICE_TR = ayarlar["tts_voice_tr"]
    if ayarlar.get("tts_voice_en"):
        pl.TTS_VOICE_EN = ayarlar["tts_voice_en"]

def _student_payload() -> dict:
    o = chat_db.aktif_ogrenci() or {}
    sinif = int(o.get("sinif") if o.get("sinif") is not None else chat_db.ayarlar_al().get("sinif") or 0)
    if sinif == 0:
        band = 2  # tumu: lise tarzi UI
    elif sinif <= 4:
        band = 0
    elif sinif <= 8:
        band = 1
    else:
        band = 2
    return {
        "type": "student",
        "sinif": sinif,
        "band": band,
        "ad": o.get("ad") or "",
        "ogrenci_id": o.get("id") or 0,
        "tumu": sinif == 0,
    }

async def _push_student_to_device() -> None:
    global _device_ws
    if _device_ws is None:
        return
    try:
        await _ws_send_json(_device_ws, _student_payload())
    except Exception as e:
        print(f"[WS] ogrenci bildirimi gonderilemedi: {e}", flush=True)

def _lan_ip() -> str:
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
    except Exception:
        ip = "127.0.0.1"
    finally:
        s.close()
    return ip

def _discovery_loop() -> None:
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind(("0.0.0.0", 8002))
    except OSError as e:
        print(f"[DISCOVER] UDP 8002 acilamadi: {e}", flush=True)
        return
    print("[DISCOVER] UDP 8002 dinleniyor (ESP SUNUCUYU BUL)", flush=True)
    while True:
        try:
            data, addr = sock.recvfrom(256)
            if b"MEB_AI_DISCOVER" in data:
                msg = f"MEB_AI_HOST:{_lan_ip()}:8001".encode("utf-8")
                sock.sendto(msg, addr)
                print(f"[DISCOVER] cevap -> {addr[0]} ({msg.decode()})", flush=True)
        except Exception:
            pass

@app.on_event("startup")
def _startup() -> None:
    chat_db.init_db()
    _apply_settings_to_runtime(chat_db.ayarlar_al())
    threading.Thread(target=_discovery_loop, daemon=True).start()

DASHBOARD_DIR = Path(__file__).resolve().parent.parent / "04-Dashboard-Web"

@app.get("/")
def anasayfa():
    return RedirectResponse(url="/dashboard/")

@app.get("/api/health")
def health():
    return {
        "mesaj": "AI Asistan Çalışıyor!",
        "websocket": "/ws/device",
        "dashboard": "/dashboard/",
        "rest": ["/sor", "/api/login", "/api/chats", "/api/settings"],
    }

@app.post("/api/login")
def api_login(istek: LoginIstegi):
    user = chat_db.login(istek.username.strip(), istek.password)
    if not user:
        raise HTTPException(status_code=400, detail="Kullanıcı adı veya şifre hatalı")
    token = secrets.token_urlsafe(24)
    _sessions[token] = user
    return {"token": token, "user": user}

@app.get("/api/chats")
def api_chats(authorization: str | None = Header(default=None), limit: int = 100):
    _user_from_auth(authorization)
    return {"chats": chat_db.sohbet_listesi(limit=min(limit, 500))}

@app.get("/api/settings")
def api_settings_get(authorization: str | None = Header(default=None)):
    _user_from_auth(authorization)
    return {"settings": chat_db.ayarlar_al()}

@app.put("/api/settings")
async def api_settings_put(
    istek: AyarIstegi, authorization: str | None = Header(default=None)
):
    user = _user_from_auth(authorization)
    updates = {k: v for k, v in istek.model_dump().items() if v is not None}
    if "sinif" in updates:
        try:
            n = int(str(updates["sinif"]))
            o = chat_db.aktif_ogrenci()
            if o:
                chat_db.ogrenci_sinif_ayarla(
                    int(o["id"]), n, user.get("display_name") or user.get("username")
                )
            updates["sinif"] = str(n)
        except (ValueError, TypeError) as e:
            raise HTTPException(status_code=400, detail=str(e)) from e
    ayarlar = chat_db.ayarlar_yaz(updates)
    _apply_settings_to_runtime(ayarlar)
    await _push_student_to_device()
    return {"settings": ayarlar, "ogrenci": chat_db.aktif_ogrenci()}

@app.get("/api/students")
def api_students(authorization: str | None = Header(default=None)):
    _user_from_auth(authorization)
    return {
        "students": chat_db.ogrenci_listesi(),
        "aktif": chat_db.aktif_ogrenci(),
        "log": chat_db.log_listesi(40),
    }

@app.put("/api/students/profile")
async def api_students_profile(
    istek: ProfilIstegi, authorization: str | None = Header(default=None)
):
    user = _user_from_auth(authorization)
    try:
        o = chat_db.ogrenci_profil_kaydet(
            istek.ad,
            istek.sinif,
            user.get("display_name") or user.get("username"),
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    await _push_student_to_device()
    return {
        "aktif": o,
        "students": chat_db.ogrenci_listesi(),
        "log": chat_db.log_listesi(40),
        "settings": chat_db.ayarlar_al(),
    }

@app.post("/api/students/select")
async def api_students_select(
    istek: OgrenciSecIstegi, authorization: str | None = Header(default=None)
):
    user = _user_from_auth(authorization)
    try:
        o = chat_db.ogrenci_sec(
            istek.ogrenci_id, user.get("display_name") or user.get("username")
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    await _push_student_to_device()
    return {
        "aktif": o,
        "students": chat_db.ogrenci_listesi(),
        "log": chat_db.log_listesi(40),
    }

@app.put("/api/students/grade")
async def api_students_grade(
    istek: SinifIstegi, authorization: str | None = Header(default=None)
):
    user = _user_from_auth(authorization)
    try:
        o = chat_db.ogrenci_sinif_ayarla(
            istek.ogrenci_id,
            istek.sinif,
            user.get("display_name") or user.get("username"),
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    await _push_student_to_device()
    return {
        "aktif": o,
        "students": chat_db.ogrenci_listesi(),
        "log": chat_db.log_listesi(40),
        "settings": chat_db.ayarlar_al(),
    }

@app.get("/api/activity")
def api_activity(authorization: str | None = Header(default=None), limit: int = 40):
    _user_from_auth(authorization)
    return {"log": chat_db.log_listesi(min(limit, 100))}

@app.get("/api/device/status")
def api_device_status(authorization: str | None = Header(default=None)):
    _user_from_auth(authorization)
    return _device_status

@app.post("/sor")
async def soru_sor(istek: SoruIstegi):
    return pl.metinden_cevap(istek.soru, istek.dil)

@app.post("/reset")
def sohbet_sifirla():
    pl.reset_sohbet()
    return {"durum": "ok", "oturum_selamlandi": False}

@app.post("/ses-cevir")
async def sesi_metne_cevir(ses_dosyasi: UploadFile = File(...)):
    try:
        icerik = await ses_dosyasi.read()
        metin = pl.stt_upload_bytes(icerik, ses_dosyasi.filename or "ses.wav")
        return {"durum": "basarili", "metin": metin}
    except Exception as e:
        return {"durum": "hata", "detay": str(e)}

@app.post("/metin-seslendir")
async def metin_seslendir(metin: str):
    try:
        dosya = await pl.tts_to_mp3(metin, "Türkçe", "robot_sesi.mp3")
        return FileResponse(dosya, media_type="audio/mpeg", filename=dosya)
    except Exception as e:
        return {"durum": "hata", "detay": str(e)}

@app.post("/asistan-ile-konus")
async def asistan_ile_konus(ses_dosyasi: UploadFile = File(...), dil: str = "Türkçe"):
    try:
        icerik = await ses_dosyasi.read()
        soru = pl.stt_upload_bytes(icerik, ses_dosyasi.filename or "ses.wav", dil=dil)
        kaynak, skor, meta = pl.rag_ara(soru)
        if (
            skor < pl.SCORE_THRESHOLD
            or not kaynak.strip()
            or not pl.kaynak_soruya_uygun_mu(soru, kaynak, skor=skor)
        ):
            cevap = pl.bulunamadi_mesaji(dil)
        else:
            cevap = pl.llm_cevapla(soru, dil, kaynak, meta=meta, sesli=True)
            if not pl.cevap_kaynaga_dayali_mi(cevap, kaynak):
                cevap = pl.bulunamadi_mesaji(dil)
        dosya = await pl.tts_to_mp3(cevap, dil, "asistan_cevabi.mp3")
        return FileResponse(dosya, media_type="audio/mpeg", filename=dosya)
    except Exception as e:
        print(f"[HATA] /asistan-ile-konus: {e}")
        return {"durum": "hata", "detay": str(e)}

def _pcm_rms(pcm: bytes) -> float:
    if len(pcm) < 2:
        return 0.0
    if len(pcm) % 2:
        pcm = pcm[:-1]
    samples = array.array("h")
    samples.frombytes(pcm)
    if not samples:
        return 0.0
    acc = 0
    for s in samples:
        acc += s * s
    return (acc / len(samples)) ** 0.5

async def _ws_send_json(ws: WebSocket, payload: dict) -> None:
    await ws.send_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")))

async def _ws_send_pcm(ws: WebSocket, pcm: bytes) -> None:
    if len(pcm) % 2:
        pcm = pcm[:-1]
    bytes_per_sec = SAMPLE_RATE * 2
    speed = 1.35
    step = PCM_CHUNK if PCM_CHUNK % 2 == 0 else PCM_CHUNK - 1
    burst_left = min(len(pcm), 20 * 1024)  # ~0.6 sn @ 16kHz mono 16-bit
    sent = 0
    for i in range(0, len(pcm), step):
        chunk = pcm[i : i + step]
        if len(chunk) % 2:
            chunk = chunk[:-1]
        if not chunk:
            continue
        await ws.send_bytes(chunk)
        sent += len(chunk)
        if sent < burst_left:
            continue  # prebuffer icin bekleme yok
        await asyncio.sleep(len(chunk) / (bytes_per_sec * speed))

@app.websocket("/ws/device")
async def ws_device(websocket: WebSocket):
    """
    ESP32 protokolü:
    - Client → binary: 16-bit mono PCM @ 16 kHz
    - Client → text JSON: {"type":"config","dil":"Türkçe"} veya {"type":"end"}
    - Server → text JSON: {"type":"status","value":"listening|thinking|speaking"}
    - Server → binary: cevap PCM parçaları
    - Server → text JSON: {"type":"done","soru":"...","cevap":"..."}
    """
    global _device_ws, _device_listen
    await websocket.accept()
    _device_ws = websocket
    _device_listen = True
    dil = chat_db.ayarlar_al().get("dil") or "Türkçe"
    buf = bytearray()
    speech_started = False
    last_voice_t = 0.0
    speech_start_t = 0.0
    _device_status.update({"value": "listening", "updated": time.time()})
    voiced_chunks = 0
    pcm_chunks = 0
    rms_peak = 0.0
    last_pcm_log = 0.0
    busy = False
    phase = "idle"  # idle | thinking | speaking
    closed = False
    work_task: asyncio.Task | None = None
    ignore_audio_until = 0.0

    pl.reset_sohbet()
    print(
        f"[WS] ESP32 bağlandı | VAD rms>={SILENCE_RMS} silence={SILENCE_MS}ms",
        flush=True,
    )
    await _ws_send_json(
        websocket,
        {"type": "time", "epoch": int(time.time()), "tz": "UTC-3"},
    )
    await _ws_send_json(websocket, _student_payload())
    await _ws_send_json(websocket, {"type": "status", "value": "listening"})

    async def keepalive() -> None:
        while not closed:
            await asyncio.sleep(5.0)
            if phase == "thinking" and not closed:
                try:
                    await _ws_send_json(
                        websocket, {"type": "status", "value": "thinking"}
                    )
                except Exception:
                    break

    async def run_utterance(pcm_bytes: bytes, dil_now: str) -> None:
        nonlocal busy, phase, ignore_audio_until, speech_started, last_voice_t
        nonlocal voiced_chunks, speech_start_t, pcm_chunks, rms_peak
        try:
            await _process_utterance(websocket, pcm_bytes, dil_now, phase_setter)
        except Exception as e:
            print(f"[WS] Utterance task hata: {e}", flush=True)
        finally:
            busy = False
            phase = "idle"
            ignore_audio_until = time.monotonic() + (POST_SPEECH_IGNORE_MS / 1000.0)
            buf.clear()
            speech_started = False
            last_voice_t = 0.0
            speech_start_t = 0.0
            voiced_chunks = 0
            pcm_chunks = 0
            rms_peak = 0.0

    def phase_setter(p: str) -> None:
        nonlocal phase
        phase = p

    def _reset_vad() -> None:
        nonlocal speech_started, last_voice_t, speech_start_t, voiced_chunks
        nonlocal rms_peak, pcm_chunks
        buf.clear()
        speech_started = False
        last_voice_t = 0.0
        speech_start_t = 0.0
        voiced_chunks = 0
        rms_peak = 0.0
        pcm_chunks = 0

    def start_utterance() -> None:
        nonlocal busy, speech_started, last_voice_t, work_task, voiced_chunks
        nonlocal speech_start_t, rms_peak
        if busy or len(buf) < MIN_SPEECH_BYTES or voiced_chunks < MIN_VOICED_CHUNKS:
            return
        if time.monotonic() < ignore_audio_until:
            _reset_vad()
            return
        if rms_peak < SPEECH_PEAK_MIN:
            print(
                f"[WS] Zayif peak={rms_peak:.0f} (<{SPEECH_PEAK_MIN:.0f}) — atildi",
                flush=True,
            )
            _reset_vad()
            return
        busy = True
        phase_setter("thinking")
        pcm_snap = bytes(buf[:MAX_UTTERANCE_BYTES])
        print(
            f"[WS] Tetik: {len(pcm_snap)} byte | voiced={voiced_chunks} peak_rms={rms_peak:.0f}",
            flush=True,
        )
        _reset_vad()
        work_task = asyncio.create_task(run_utterance(pcm_snap, dil))

    ka_task = asyncio.create_task(keepalive())

    try:
        while True:
            msg = await websocket.receive()

            if msg.get("type") == "websocket.disconnect":
                break

            if "text" in msg and msg["text"] is not None:
                try:
                    data = json.loads(msg["text"])
                except json.JSONDecodeError:
                    continue

                if data.get("type") == "config":
                    if data.get("dil"):
                        dil = str(data["dil"])
                    if data.get("sinif") is not None:
                        try:
                            n = int(data.get("sinif"))
                            o = chat_db.aktif_ogrenci()
                            if o:
                                chat_db.ogrenci_sinif_ayarla(
                                    int(o["id"]), n, "cihaz"
                                )
                            else:
                                chat_db.ogrenci_profil_kaydet("", n, "cihaz")
                            await _ws_send_json(websocket, _student_payload())
                            print(f"[WS] cihazda sinif={n}", flush=True)
                        except Exception as e:
                            print(f"[WS] sinif ayar hatasi: {e}", flush=True)
                    if "listen" in data:
                        _device_listen = bool(data.get("listen"))
                        if not _device_listen:
                            buf.clear()
                            speech_started = False
                            voiced_chunks = 0
                            _device_status.update(
                                {"value": "idle", "updated": time.time()}
                            )
                            await _ws_send_json(
                                websocket, {"type": "status", "value": "idle"}
                            )
                            print("[WS] dinleme KAPALI (ekran kapali)", flush=True)
                            continue
                        _device_status.update(
                            {"value": "listening", "updated": time.time()}
                        )
                        await _ws_send_json(
                            websocket, {"type": "status", "value": "listening"}
                        )
                        print("[WS] dinleme ACIK", flush=True)
                        continue
                    if data.get("dil"):
                        await _ws_send_json(
                            websocket,
                            {"type": "status", "value": "listening", "dil": dil},
                        )
                    continue

                if data.get("type") == "ask":
                    soru = str(data.get("soru") or "").strip()
                    if data.get("dil"):
                        dil = str(data["dil"])
                    if not soru or busy:
                        continue
                    busy = True
                    phase_setter("thinking")

                    async def run_text_ask(soru_now: str, dil_now: str) -> None:
                        nonlocal busy, phase, ignore_audio_until
                        try:
                            await _process_text_ask(
                                websocket, soru_now, dil_now, phase_setter
                            )
                        except Exception as e:
                            print(f"[WS] Text ask hata: {e}", flush=True)
                        finally:
                            busy = False
                            phase = "idle"
                            ignore_audio_until = time.monotonic() + (
                                POST_SPEECH_IGNORE_MS / 1000.0
                            )

                    work_task = asyncio.create_task(run_text_ask(soru, dil))
                    continue

                if data.get("type") == "end":
                    start_utterance()
                continue

            if "bytes" in msg and msg["bytes"] is not None:
                if busy or not _device_listen:
                    continue
                now = time.monotonic()
                if now < ignore_audio_until:
                    continue

                chunk = msg["bytes"]
                buf.extend(chunk)
                pcm_chunks += 1
                if len(buf) > MAX_UTTERANCE_BYTES:
                    del buf[: len(buf) - MAX_UTTERANCE_BYTES]

                rms = _pcm_rms(chunk)
                if rms > rms_peak:
                    rms_peak = rms

                if now - last_pcm_log >= 2.0:
                    last_pcm_log = now
                    print(
                        f"[WS] pcm: chunks={pcm_chunks} buf={len(buf)} "
                        f"rms={rms:.0f} peak={rms_peak:.0f} voiced={voiced_chunks}",
                        flush=True,
                    )

                if rms >= SILENCE_RMS:
                    speech_started = True
                    last_voice_t = now
                    voiced_chunks += 1

                if (
                    speech_started
                    and last_voice_t > 0
                    and (now - last_voice_t) * 1000 >= SILENCE_MS
                    and len(buf) >= MIN_SPEECH_BYTES
                    and voiced_chunks >= MIN_VOICED_CHUNKS
                ):
                    start_utterance()
                elif len(buf) >= MAX_UTTERANCE_BYTES and voiced_chunks >= MIN_VOICED_CHUNKS:
                    start_utterance()

    except WebSocketDisconnect:
        print("[WS] ESP32 bağlantısı koptu", flush=True)
    except Exception as e:
        print(f"[WS] Hata: {type(e).__name__}: {e}", flush=True)
    finally:
        closed = True
        if _device_ws is websocket:
            _device_ws = None
        ka_task.cancel()
        if work_task and not work_task.done():
            work_task.cancel()

async def _process_utterance(ws: WebSocket, pcm: bytes, dil: str, set_phase) -> None:
    print(f"[WS] Isleniyor: {len(pcm)} byte PCM", flush=True)
    set_phase("thinking")
    _device_status.update({"value": "thinking", "updated": time.time()})
    try:
        await _ws_send_json(ws, {"type": "status", "value": "thinking"})
    except Exception as e:
        print(f"[WS] thinking gonderilemedi: {e}", flush=True)
        return

    try:
        async def _stream_cevap() -> tuple[str, str, int]:
            soru_l, cevap_l, pcm_total_l = "", "", 0
            async for item in pl.sesli_pipeline_stream(pcm, dil):
                kind = item[0]
                if kind == "meta":
                    soru_l, cevap_l = item[1], item[2]
                    if not (cevap_l or "").strip():
                        return soru_l, "", 0
                    set_phase("speaking")
                    _device_status.update(
                        {"value": "speaking", "updated": time.time()}
                    )
                    await _ws_send_json(ws, {"type": "status", "value": "speaking"})
                elif kind == "pcm":
                    pcm_chunk = item[1]
                    pcm_total_l += len(pcm_chunk)
                    await _ws_send_pcm(ws, pcm_chunk)
                elif kind == "end":
                    break
            return soru_l, cevap_l, pcm_total_l

        try:
            soru, cevap, pcm_total = await asyncio.wait_for(
                _stream_cevap(), timeout=55.0
            )
        except asyncio.TimeoutError:
            print("[WS] Pipeline timeout (55s)", flush=True)
            cevap = (
                "Sorry, that took too long. Please try again."
                if pl.dil_ingilizce_mi(dil)
                else "Üzgünüm, işlem uzun sürdü. Tekrar dener misin?"
            )
            soru = ""
            set_phase("speaking")
            await _ws_send_json(ws, {"type": "status", "value": "speaking"})
            await _ws_send_pcm(ws, await pl.tts_to_pcm16(cevap, dil))
            pcm_total = 1

        if not (cevap or "").strip():
            print(f"[WS] Sessiz gecildi (soru degil/gurultu): {soru!r}", flush=True)
            await _ws_send_json(ws, {"type": "status", "value": "listening"})
            _device_status.update({"value": "listening", "updated": time.time()})
            return

        print(f"[WS] PCM hazir: {pcm_total} byte | soru={soru!r}", flush=True)
        await _ws_send_json(ws, {"type": "done", "soru": soru, "cevap": cevap})
        print("[WS] Cevap gonderildi", flush=True)
    except (WebSocketDisconnect, RuntimeError) as e:
        print(f"[WS] Gonderim kesildi: {type(e).__name__}: {e}", flush=True)
        return
    except Exception as e:
        print(f"[WS] Pipeline hatasi: {type(e).__name__}: {e}", flush=True)
        hata = (
            "Sorry, something went wrong."
            if pl.dil_ingilizce_mi(dil)
            else "Üzgünüm, bir hata oluştu. Tekrar dener misin?"
        )
        try:
            set_phase("speaking")
            pcm_out = await pl.tts_to_pcm16(hata, dil)
            await _ws_send_json(ws, {"type": "status", "value": "speaking"})
            await _ws_send_pcm(ws, pcm_out)
            await _ws_send_json(ws, {"type": "error", "detail": str(e)})
        except Exception as e2:
            print(f"[WS] Hata cevabi da gonderilemedi: {e2}", flush=True)
            try:
                await _ws_send_json(ws, {"type": "status", "value": "listening"})
            except Exception:
                pass
            return

    try:
        _device_status.update({"value": "listening", "updated": time.time()})
        await _ws_send_json(ws, {"type": "status", "value": "listening"})
    except Exception:
        pass

async def _process_text_ask(ws: WebSocket, soru: str, dil: str, set_phase) -> None:
    print(f"[WS] Yazili soru: {soru!r}", flush=True)
    set_phase("thinking")
    _device_status.update({"value": "thinking", "updated": time.time()})
    try:
        await _ws_send_json(ws, {"type": "status", "value": "thinking"})
    except Exception as e:
        print(f"[WS] thinking gonderilemedi: {e}", flush=True)
        return

    try:
        sonuc = await asyncio.to_thread(pl.metinden_cevap, soru, dil)
        cevap = str(sonuc.get("cevap") or "").strip()
        if not cevap:
            cevap = pl.bulunamadi_mesaji(dil)

        set_phase("speaking")
        _device_status.update({"value": "speaking", "updated": time.time()})
        await _ws_send_json(ws, {"type": "status", "value": "speaking"})

        for cumle in pl._cumlelere_bol(cevap):
            pcm_chunk = await pl.tts_to_pcm16(cumle, pl._tts_dil_sec(dil, cevap))
            if pcm_chunk:
                await _ws_send_pcm(ws, pcm_chunk)

        await _ws_send_json(
            ws, {"type": "done", "soru": soru, "cevap": cevap, "mod": "yazi"}
        )
        print("[WS] Yazili cevap gonderildi", flush=True)
    except (WebSocketDisconnect, RuntimeError) as e:
        print(f"[WS] Yazili gonderim kesildi: {type(e).__name__}: {e}", flush=True)
        return
    except Exception as e:
        print(f"[WS] Yazili pipeline hata: {e}", flush=True)
        try:
            hata = (
                "Sorry, something went wrong."
                if pl.dil_ingilizce_mi(dil)
                else "Üzgünüm, bir hata oluştu."
            )
            set_phase("speaking")
            await _ws_send_json(ws, {"type": "status", "value": "speaking"})
            await _ws_send_pcm(ws, await pl.tts_to_pcm16(hata, dil))
            await _ws_send_json(ws, {"type": "error", "detail": str(e)})
        except Exception:
            return

    try:
        _device_status.update({"value": "listening", "updated": time.time()})
        await _ws_send_json(ws, {"type": "status", "value": "listening"})
    except Exception:
        pass

if DASHBOARD_DIR.is_dir():
    app.mount(
        "/dashboard",
        StaticFiles(directory=str(DASHBOARD_DIR), html=True),
        name="dashboard",
    )
