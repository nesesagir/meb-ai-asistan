import asyncio
import wave

import websockets

ses_verisi = bytearray()


async def audio_server(websocket):
    print("client connected")
    try:
        async for message in websocket:
            if isinstance(message, bytes):
                if all(b == 0 for b in message):
                    print("[warn] empty pcm frame", end="\r")
                else:
                    ses_verisi.extend(message)
                    print(f"receiving... {len(ses_verisi)} bytes", end="\r")
    except websockets.exceptions.ConnectionClosed:
        pass


async def main():
    print("listening on :8080")
    async with websockets.serve(audio_server, "0.0.0.0", 8080):
        await asyncio.Future()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print(f"\ndisconnected, {len(ses_verisi)} bytes")
        if len(ses_verisi) > 0:
            with wave.open("SON_KAYIT.wav", "wb") as f:
                f.setnchannels(1)
                f.setsampwidth(2)
                f.setframerate(16000)
                f.writeframes(ses_verisi)
            print("wrote SON_KAYIT.wav")
        else:
            print("no audio captured")
