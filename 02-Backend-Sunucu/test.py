import requests

try:
    response = requests.post("http://127.0.0.1:8000/sor", json={"soru": "Ders nedir?"})
    print("Yapay Zekanın Cevabı:", response.json())
except Exception as e:
    print("Hata:", e)