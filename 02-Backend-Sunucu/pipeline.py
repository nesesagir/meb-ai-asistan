from __future__ import annotations

import asyncio
import io
import os
import re
import tempfile
import wave
from typing import Any

import edge_tts
import ollama
from fastembed import SparseTextEmbedding, TextEmbedding
from groq import Groq
from qdrant_client import QdrantClient
from qdrant_client.http import models

QDRANT_URL = os.getenv("QDRANT_URL", "http://localhost:6333")
QDRANT_COLLECTION = os.getenv("QDRANT_COLLECTION", "meb-books-v2")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "llama3")
GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
GROQ_LLM_MODEL = os.getenv("GROQ_LLM_MODEL", "llama-3.1-8b-instant")
LLM_PROVIDER = os.getenv("LLM_PROVIDER", "groq").strip().lower()  # groq | ollama
SCORE_THRESHOLD = float(os.getenv("SCORE_THRESHOLD", "0.2"))
TTS_VOICE_TR = os.getenv("TTS_VOICE_TR", "tr-TR-EmelNeural")
TTS_VOICE_EN = os.getenv("TTS_VOICE_EN", "en-US-AndrewNeural")
VOICE_MAX_CHARS = int(os.getenv("VOICE_MAX_CHARS", "320"))

dense_model = TextEmbedding(model_name="intfloat/multilingual-e5-large")
sparse_model = SparseTextEmbedding(model_name="Qdrant/bm25")
qdrant = QdrantClient(QDRANT_URL)
groq_client = Groq(api_key=GROQ_API_KEY) if GROQ_API_KEY else None

sohbet_gecmisi: list[dict[str, str]] = []
oturum_selamlandi: bool = False

def reset_sohbet() -> None:
    global oturum_selamlandi
    sohbet_gecmisi.clear()
    oturum_selamlandi = False

def dil_ingilizce_mi(dil: str) -> bool:
    d = dil.strip().lower().replace("ı", "i").replace("İ", "i")
    return d in {
        "ingilizce",
        "english",
        "en",
        "en-us",
        "en_us",
    }

def bulunamadi_mesaji(dil: str) -> str:
    sn = panel_sinif_no()
    if dil_ingilizce_mi(dil):
        if sn is not None:
            return (
                f"This topic is not in the grade {sn} textbooks, "
                "so I can only answer from your class books."
            )
        return (
            "This information is not available in the textbooks, "
            "so I cannot answer that question."
        )
    if sn is not None:
        return (
            f"Bu konu {sn}. sınıf ders kitaplarında yok; "
            "sadece kendi sınıfının kitaplarından yanıt verebiliyorum."
        )
    return (
        "Bu bilgi ders kitaplarında mevcut değil, bu yüzden yanıtını veremiyorum."
    )

_STOP_TR = {
    "nedir",
    "nasil",
    "nasıl",
    "neden",
    "nicin",
    "niçin",
    "niye",
    "hangi",
    "icin",
    "için",
    "gibi",
    "veya",
    "ile",
    "bir",
    "bu",
    "şu",
    "o",
    "de",
    "da",
    "mi",
    "mı",
    "mu",
    "mü",
    "midir",
    "mıdır",
    "yapilir",
    "yapılır",
    "yapmak",
    "edilir",
    "nelerdir",
    "what",
    "why",
    "how",
    "which",
    "does",
    "mean",
    "make",
    "made",
    "the",
    "and",
    "for",
}

def _norm_tr(s: str) -> str:
    return (
        (s or "")
        .lower()
        .replace("ı", "i")
        .replace("İ", "i")
        .replace("ş", "s")
        .replace("ğ", "g")
        .replace("ü", "u")
        .replace("ö", "o")
        .replace("ç", "c")
    )

def _kelime_kaynakta(w: str, kaynak_l: str) -> bool:
    w = _norm_tr(w)
    k = _norm_tr(kaynak_l)
    if len(w) < 4:
        return False
    if w in k:
        return True
    if len(w) >= 5 and w[:5] in k:
        return True
    if len(w) >= 6 and w[:-1] in k:
        return True
    if len(w) >= 7 and w[:-2] in k:
        return True
    return False

def _soru_ana_kelimeler(soru: str) -> list[str]:
    return [
        w
        for w in re.findall(r"[a-zA-ZçğıöşüÇĞİÖŞÜ]{4,}", soru.lower())
        if _norm_tr(w) not in _STOP_TR
    ]

def _yemek_tarif_sorusu_mu(soru: str) -> bool:
    s = _norm_tr(soru)
    ipuclari = (
        "nasil yapilir",
        "how to make",
        "how do you make",
        "tarifi",
        "yemek tarifi",
        "malzeme",
        "soslu",
        "pisir",
        "pişir",
    )
    return any(x in s for x in ipuclari)

def _kaynakta_yemek_baglami_var_mi(kaynak: str) -> bool:
    k = _norm_tr(kaynak)
    return any(
        x in k
        for x in (
            "tarif",
            "malzeme",
            "pisir",
            "pişir",
            "yemek",
            "kasik",
            "kaşık",
            "firin",
            "gram",
        )
    )

def _kelime_hit_sayisi(soru: str, kaynak: str) -> tuple[list[str], int]:
    words = _soru_ana_kelimeler(soru)
    hits = sum(1 for w in words if _kelime_kaynakta(w, kaynak))
    return words, hits

def kaynak_soruya_uygun_mu(soru: str, kaynak: str, skor: float = -1.0) -> bool:
    if not (kaynak or "").strip():
        return False
    words, hits = _kelime_hit_sayisi(soru, kaynak)
    if not words:
        return False

    if _yemek_tarif_sorusu_mu(soru) and not _kaynakta_yemek_baglami_var_mi(kaynak):
        return False

    anchor = max(words, key=lambda w: len(_norm_tr(w)))
    if not _kelime_kaynakta(anchor, kaynak):
        return False

    if len(words) == 1:
        return True
    need = max(1, (len(words) + 1) // 2)
    if hits >= need:
        return True
    if skor >= 0.35 and hits >= 1:
        return True
    return False

_UYDURMA_IPUCU = (
    "tarif",
    "malzeme",
    "kasik",
    "kaşık",
    "firin",
    "fırın",
    "pisir",
    "pişir",
    "gram ",
    "ml ",
    "soslu",
    "yemek tarifi",
    "adim 1",
    "adım 1",
)

def cevap_kaynaga_dayali_mi(cevap: str, kaynak: str) -> bool:
    if not cevap or not kaynak:
        return False
    cl = _norm_tr(cevap)
    if "mevcut degil" in cl or "not available in the textbooks" in cl:
        return True
    if any(x in cl for x in _UYDURMA_IPUCU) and not any(
        x in _norm_tr(kaynak) for x in _UYDURMA_IPUCU
    ):
        return False
    temiz = re.sub(r"^(merhaba|hello|hi)[!.,\s]*", "", cevap.strip(), flags=re.I)
    words = [
        w
        for w in re.findall(r"[a-zA-ZçğıöşüÇĞİÖŞÜ]{5,}", temiz.lower())
        if _norm_tr(w) not in _STOP_TR
    ]
    if len(words) < 6:
        return True
    hits = sum(1 for w in words if _kelime_kaynakta(w, kaynak))
    return hits >= 1

_JUNK_STT = (
    "izlediğiniz için",
    "izlediginiz icin",
    "altyazı",
    "altyazi",
    "subscribe",
    "thank you for watching",
    "türkçe konuşuyor",
    "turkce konusuyor",
    "özenle hazırlanmıştır",
)

_TR_SORU = (
    "nedir",
    "nasıl",
    "neden",
    "niçin",
    "niye",
    "hangi",
    "kaç",
    "kim",
    "ne demek",
    "anlat",
    "açıkla",
    "acikla",
    "örnek",
    "ornek",
)
_EN_SORU = (
    "what",
    "why",
    "how",
    "who",
    "when",
    "where",
    "which",
    "explain",
    "tell me",
    "define",
    "describe",
)

def soru_gecerli_mi(soru: str) -> bool:
    s = (soru or "").strip()
    if len(s) < 4:
        return False
    letters = sum(1 for c in s if c.isalpha())
    if letters < 3:
        return False
    if re.fullmatch(r"[\s\.\,\!\?…\-]+", s):
        return False
    return True

def selamlama_mu(soru: str) -> bool:
    s = _norm_tr(soru)
    s = re.sub(r"[^\w\s]", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    if not s:
        return False
    tam = {
        "merhaba",
        "selam",
        "hey",
        "hello",
        "hi",
        "hello there",
        "hi there",
        "good morning",
        "good afternoon",
        "good evening",
        "gunaydin",
        "iyi gunler",
        "iyi aksamlar",
        "nasilsin",
        "nasilsiniz",
        "naber",
        "ne haber",
        "merhaba nasilsin",
        "selam nasilsin",
        "hello how are you",
        "hi how are you",
        "how are you",
        "how are you doing",
    }
    if s in tam:
        return True
    if s.startswith("merhaba") and len(s.split()) <= 5:
        return True
    if s.startswith("selam") and len(s.split()) <= 5:
        return True
    if s.startswith("hello") and len(s.split()) <= 5:
        return True
    if s.startswith("hi ") and len(s.split()) <= 5:
        return True
    if s == "hi":
        return True
    if "nasilsin" in s and len(s.split()) <= 6:
        return True
    if "how are you" in s and len(s.split()) <= 7:
        return True
    return False

def _selam_dil_coz(dil: str, soru: str) -> bool:
    s = _norm_tr(soru)
    en_ipucu = (
        "hello",
        "hi ",
        "hey",
        "how are you",
        "good morning",
        "good afternoon",
        "good evening",
    )
    tr_ipucu = ("merhaba", "selam", "nasilsin", "gunaydin", "iyi gunler")
    if s == "hi" or any(x in s for x in en_ipucu):
        return True
    if any(x in s for x in tr_ipucu):
        return False
    return dil_ingilizce_mi(dil)

def tesekkur_mu(soru: str) -> bool:
    s = _norm_tr(soru)
    s = re.sub(r"[^\w\s]", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    if not s:
        return False
    anahtar = (
        "tesekkur",
        "tesekkurler",
        "tesekkur ederim",
        "cok tesekkur",
        "sag ol",
        "sagol",
        "eyvallah",
        "thanks",
        "thank you",
        "thx",
        "ty",
    )
    if s in anahtar:
        return True
    if any(k in s for k in ("tesekkur", "thank you", "thanks")) and len(s.split()) <= 6:
        return True
    return False

def tesekkur_cevabi(dil: str, soru: str = "") -> str:
    ad = panel_ogrenci_adi()
    if dil_ingilizce_mi(dil) or "thank" in _norm_tr(soru):
        if ad:
            return f"You're welcome, {ad}! You can ask another question anytime."
        return "You're welcome! You can ask another question anytime."
    if ad:
        return f"Rica ederim, {ad}! İstersen başka bir soru da sorabilirsin."
    return "Rica ederim! İstersen başka bir soru da sorabilirsin."

def panel_sinif_no() -> int | None:
    try:
        import db as chat_db

        o = chat_db.aktif_ogrenci()
        if o is not None and o.get("sinif") is not None:
            n = int(o["sinif"])
            if n == 0:
                return None
            if 1 <= n <= 12:
                return n
        s = str(chat_db.ayarlar_al().get("sinif") or "").strip()
        if s in ("0", "tumu", "Tümü", "all"):
            return None
        return _sinif_numarasi(s)
    except Exception:
        return None

def panel_sinif_al() -> str:
    try:
        import db as chat_db

        o = chat_db.aktif_ogrenci()
        if o is not None and o.get("sinif") is not None:
            n = int(o["sinif"])
            if n == 0:
                return "Tümü"
            if 1 <= n <= 12:
                return f"{n}.Sınıf"
        s = str(chat_db.ayarlar_al().get("sinif") or "").strip()
        if s in ("0", "tumu", "Tümü", "all"):
            return "Tümü"
        n = _sinif_numarasi(s)
        if n:
            return f"{n}.Sınıf"
    except Exception:
        pass
    return "Tümü"

def panel_ogrenci_adi() -> str:
    try:
        import db as chat_db

        o = chat_db.aktif_ogrenci()
        ad = (o or {}).get("ad") or ""
        return str(ad).strip()
    except Exception:
        return ""

def selamlama_cevabi(dil: str, soru: str = "") -> str:
    s = _norm_tr(soru)
    ad = panel_ogrenci_adi()
    hale_sordu = any(
        x in s
        for x in (
            "nasilsin",
            "nasilsiniz",
            "naber",
            "ne haber",
            "how are you",
            "how r you",
        )
    )
    en = _selam_dil_coz(dil, soru)
    if not hale_sordu:
        if en:
            if ad:
                return f"Hello, {ad}! You can ask me a question from your lesson books."
            return "Hello! You can ask me a question from your lesson books."
        if ad:
            return f"Merhaba, {ad}! Ders kitaplarınla ilgili bir soru sorabilirsin."
        return "Merhaba! Ders kitaplarınla ilgili bir soru sorabilirsin."

    ilk = not oturum_selamlandi
    if en:
        govde = (
            "I'm fine, thank you! "
            "You can ask me a question from your lesson books."
        )
        if ad:
            return (f"Hello, {ad}! " + govde) if ilk else govde
        return ("Hello! " + govde) if ilk else govde
    govde = (
        "İyiyim, teşekkür ederim! "
        "Ders kitaplarınla ilgili bir soru sorabilirsin."
    )
    if ad:
        return (f"Merhaba, {ad}! " + govde) if ilk else govde
    return ("Merhaba! " + govde) if ilk else govde

def _stt_junk_mu(soru: str) -> bool:
    s = soru.strip().lower()
    s_norm = _norm_tr(s)
    for j in _JUNK_STT:
        if j in s or j in s_norm:
            return True
    if s.count("turkce") + s.count("türkçe") >= 2:
        return True
    if "masha" in s_norm or "altyaz" in s_norm:
        return True
    return False

def sesli_soru_mu(soru: str, dil: str) -> bool:
    if not soru_gecerli_mi(soru):
        return False
    if _stt_junk_mu(soru):
        return False

    s = soru.strip().lower()
    s_norm = _norm_tr(s)

    sadece = re.sub(r"[^\wçğıöşüÇĞİÖŞÜ\s]", "", s).strip()
    belirsiz = {
        "nedir",
        "nedir?",
        "ne",
        "ne?",
        "ne demek",
        "ne demek?",
        "nasil",
        "nasıl",
        "evet",
        "hayir",
        "hayır",
        "tamam",
        "what",
        "what?",
        "why",
        "how",
    }
    if sadece in belirsiz:
        return False

    words = [w for w in re.split(r"\s+", sadece) if w]
    letters = sum(1 for c in sadece if c.isalpha())
    if len(words) == 1 and letters >= 6:
        return True
    if len(words) < 2:
        return False
    if letters < 8:
        return False

    if "?" in soru:
        return True

    if dil_ingilizce_mi(dil):
        if any(w in s_norm for w in _EN_SORU):
            return True
        if re.search(r"\b(is|are|do|does|can|could|would)\b", s_norm):
            return True
        return letters >= 10

    if any(w in s for w in _TR_SORU) or any(w in s_norm for w in (
        "nedir", "nasil", "neden", "nicin", "niye", "hangi", "kac", "kim", "ne demek",
    )):
        return True
    if re.search(r"\b(mi|mı|mu|mü|midir|mıdır|mudur|müdür)\b", s):
        return True
    return letters >= 10

def net_duyamadim_mesaji(dil: str) -> str:
    if dil_ingilizce_mi(dil):
        return "I couldn't hear a clear question. Please ask a short lesson question."
    return "Seni net duyamadım. Lütfen kısa bir ders sorusu sorar mısın?"

def _sinif_numarasi(grade: str) -> int | None:
    m = re.search(r"(\d{1,2})", grade or "")
    if not m:
        return None
    n = int(m.group(1))
    return n if 1 <= n <= 12 else None

def _grade_filter_values(n: int) -> list[str]:
    return [
        f"{n}.Sınıf",
        f"{n}.Sinif",
        f"{n}. sınıf",
        f"{n}. sinif",
        str(n),
    ]

def _seviye_talimati(grade: str) -> str:
    n = _sinif_numarasi(grade)
    if n is None:
        pn = panel_sinif_no()
        if pn is None:
            return (
                "Öğrenci tüm sınıflardan soru sorabilir. "
                "Kaynak hangi seviyedeyse o seviyeye uygun anlat."
            )
        n = pn
        grade = grade or panel_sinif_al() or "seviye"
    if n is None:
        return "Ortaokul seviyesinde net ve anlaşılır konuş."
    if n <= 4:
        return (
            f"Öğrenci {grade} (ilkokul). Samimi, kısa ve basit cümleler; "
            "tatlı ama saygılı çocuk diline yakın üslup. "
            "SADECE bu sınıf seviyesindeki kitap bilgisiyle cevap ver."
        )
    if n <= 8:
        return (
            f"Öğrenci {grade} (ortaokul). Net, teşvik edici; çocukça olmayan "
            "ama sıcak bir dil kullan. SADECE bu sınıf seviyesindeki kitap bilgisiyle cevap ver."
        )
    return (
        f"Öğrenci {grade} (lise). Daha ciddi ve akademik ama anlaşılır anlat. "
        "SADECE bu sınıf seviyesindeki kitap bilgisiyle cevap ver."
    )

def rag_ara(soru: str, max_chars: int = 3500) -> tuple[str, float, dict[str, str]]:
    from concurrent.futures import ThreadPoolExecutor

    with ThreadPoolExecutor(max_workers=2) as pool:
        f_dense = pool.submit(lambda: list(dense_model.embed([soru]))[0])
        f_sparse = pool.submit(lambda: list(sparse_model.embed([soru]))[0])
        query_dense = f_dense.result()
        query_sparse = f_sparse.result()

    query_filter = None
    hedef = panel_sinif_no()
    if hedef is not None:
        query_filter = models.Filter(
            must=[
                models.FieldCondition(
                    key="grade",
                    match=models.MatchAny(any=_grade_filter_values(hedef)),
                )
            ]
        )
        print(f"[RAG] sinif filtresi: {hedef}.Sınıf", flush=True)
    else:
        print("[RAG] sinif filtresi: TUMU", flush=True)

    cevap = qdrant.query_points(
        collection_name=QDRANT_COLLECTION,
        prefetch=[
            models.Prefetch(
                query=query_dense.tolist(),
                using="dense",
                limit=5,
                filter=query_filter,
            ),
            models.Prefetch(
                query=models.SparseVector(
                    indices=query_sparse.indices.tolist(),
                    values=query_sparse.values.tolist(),
                ),
                using="sparse",
                limit=5,
                filter=query_filter,
            ),
        ],
        query=models.FusionQuery(fusion=models.Fusion.RRF),
        query_filter=query_filter,
        limit=4,
    )

    ilgili = ""
    skor = -1.0
    meta: dict[str, str] = {"grade": "", "subject": "", "source_file": ""}
    if not cevap.points:
        return "", skor, meta

    hedef = panel_sinif_no()
    ranked: list[tuple[float, Any]] = []
    for p in cevap.points:
        payload = p.payload or {}
        if hedef is not None:
            gnum = _sinif_numarasi(str(payload.get("grade") or ""))
            if gnum != hedef:
                continue
        metin = str(payload.get("text") or payload.get("chunk_text") or "")
        _, hits = _kelime_hit_sayisi(soru, metin)
        combined = hits * 10.0 + float(p.score or 0.0)
        ranked.append((combined, p))
    ranked.sort(key=lambda x: x[0], reverse=True)

    best_p = ranked[0][1]
    skor = float(best_p.score or 0.0)
    p0 = best_p.payload or {}
    meta = {
        "grade": str(p0.get("grade") or ""),
        "subject": str(p0.get("subject") or ""),
        "source_file": str(p0.get("source_file") or ""),
    }
    for _, p in ranked[:4]:
        payload = p.payload or {}
        metin = str(payload.get("text") or payload.get("chunk_text") or "")
        kaynak_adi = payload.get("source_file") or ""
        if kaynak_adi:
            ilgili += f"[Kaynak: {kaynak_adi}]\n"
        ilgili += metin + "\n\n"
        if len(ilgili) >= max_chars:
            break
    return ilgili.strip()[:max_chars], skor, meta

def _cumle_sinirinda_kirp(metin: str, max_chars: int) -> str:
    metin = (metin or "").strip()
    if len(metin) <= max_chars:
        return metin
    cut = metin[:max_chars]
    best = -1
    for sep in (". ", "! ", "? ", ".\n", "!\n", "?\n", "."):
        idx = cut.rfind(sep)
        if idx > max_chars // 4:
            best = max(best, idx + len(sep.rstrip()))
    if best > 0:
        return cut[:best].strip()
    if " " in cut:
        return cut.rsplit(" ", 1)[0].rstrip(",;:") + "."
    return cut.rstrip(",;:") + "."

def _llm_chat(messages: list[dict[str, Any]], sesli: bool) -> str:
    max_tokens = 160 if sesli else 350
    temperature = 0.0 if sesli else 0.1

    use_groq = LLM_PROVIDER == "groq" and groq_client is not None
    if use_groq:
        kwargs: dict[str, Any] = {
            "model": GROQ_LLM_MODEL,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "top_p": 1,
        }
        try:
            kwargs["seed"] = 42
            r = groq_client.chat.completions.create(**kwargs)
        except Exception:
            kwargs.pop("seed", None)
            r = groq_client.chat.completions.create(**kwargs)
        return (r.choices[0].message.content or "").strip()

    options: dict[str, Any] = {
        "num_predict": max_tokens,
        "temperature": temperature,
        "seed": 42,
    }
    cevap = ollama.chat(model=OLLAMA_MODEL, messages=messages, options=options)
    return (cevap["message"]["content"] or "").strip()

def _selam_ekle(metin: str, dil: str) -> str:
    global oturum_selamlandi
    if oturum_selamlandi:
        return metin
    ad = panel_ogrenci_adi()
    low = metin.lower().lstrip()
    if dil_ingilizce_mi(dil):
        if not (low.startswith("hello") or low.startswith("hi")):
            metin = (f"Hello, {ad}! " if ad else "Hello! ") + metin.lstrip()
    else:
        if not low.startswith("merhaba"):
            metin = (f"Merhaba, {ad}! " if ad else "Merhaba! ") + metin.lstrip()
    oturum_selamlandi = True
    print(f"[SELAM] eklendi | oturum_selamlandi=True", flush=True)
    return metin

def llm_cevapla(
    soru: str,
    dil: str,
    kaynak: str,
    meta: dict[str, str] | None = None,
    sesli: bool = False,
) -> str:
    meta = meta or {}
    ilk_mesaj_mi = not oturum_selamlandi
    grade = meta.get("grade") or panel_sinif_al()
    seviye = _seviye_talimati(grade)

    if ilk_mesaj_mi:
        karsilama = (
            "Bu İLK sorudur. İlk kelimen MUTLAKA 'Merhaba!' olsun, "
            "sonra sınıf seviyesine uygun tek kısa giriş cümlesi, sonra cevap."
        )
    else:
        karsilama = (
            "Devam eden sohbet. ASLA merhaba veya selam deme; doğrudan cevaba gir."
        )

    ekstra = ""
    if sesli:
        ekstra = (
            "\n5. SESLİ okunacak: 2-3 TAM cümle. Cümleyi yarıda bırakma. "
            "Madde işareti yok. Aynı soruya her seferinde aynı öz tanımı ver."
        )

    system_prompt = f"""
Sen MEB ders kitaplarına bağlı bir eğitim asistanısın. Yanıtını SADECE {dil} dilinde ver.
Meta konuşma yazma.

KURALLAR:
1. {karsilama}
2. {seviye}
3. YALNIZCA KAYNAK METİN'e dayan. Kaynak soruyu doğrudan CEVAPLAMIYORSA
   (yemek tarifi, spor takımı, güncel olay, genel kültür vb. kaynakta yoksa)
   UYDURMA; yalnızca şu cümleyi yaz: "{bulunamadi_mesaji(dil)}"
4. Kaynakta olmayan adım/malzeme/bilgi ekleme YASAK (halüsinasyon yasağı).
5. "Oğlum", "Kızım", "Abicim" yasak.
6. Cevabı bölme; yarım cümle bırakma.
7. Kaynaktaki tanımı sadık aktar.{ekstra}
"""

    user_prompt = f"""
KAYNAK METİN:
{kaynak}

DERS/SINIF: {meta.get('subject', '')} / {meta.get('grade', '')}
KİTAP: {meta.get('source_file', '')}

SORU: {soru}
"""

    gecmis = sohbet_gecmisi[-2:] if sesli else sohbet_gecmisi[-8:]
    messages: list[dict[str, Any]] = [
        {"role": "system", "content": system_prompt},
        *gecmis,
        {"role": "user", "content": user_prompt},
    ]

    try:
        metin = _llm_chat(messages, sesli=sesli)
    except Exception as e:
        print(f"[LLM] birincil hata ({LLM_PROVIDER}): {e}", flush=True)
        try:
            cevap = ollama.chat(
                model=OLLAMA_MODEL,
                messages=messages,
                options={"num_predict": 160 if sesli else 350, "temperature": 0.0, "seed": 42},
            )
            metin = (cevap["message"]["content"] or "").strip()
        except Exception as e2:
            metin = f"Model hatası: {e2}"

    if sesli:
        metin = _cumle_sinirinda_kirp(metin, max(80, VOICE_MAX_CHARS - 12))

    sohbet_gecmisi.append({"role": "user", "content": soru})
    sohbet_gecmisi.append({"role": "assistant", "content": metin})
    if len(sohbet_gecmisi) > 20:
        del sohbet_gecmisi[:-20]
    return metin

def metinden_cevap(soru: str, dil: str = "Türkçe") -> dict[str, Any]:
    def _sonuc(**kwargs: Any) -> dict[str, Any]:
        out = {"soru": soru, "dil": dil, **kwargs}
        try:
            import db as chat_db

            if out.get("cevap"):
                chat_db.kayit_ekle(soru, str(out["cevap"]), dil)
        except Exception:
            pass
        return out

    if selamlama_mu(soru):
        global oturum_selamlandi
        cevap = selamlama_cevabi(dil, soru)
        oturum_selamlandi = True
        return _sonuc(arama_skoru=0.0, cevap=cevap)
    if tesekkur_mu(soru):
        return _sonuc(arama_skoru=0.0, cevap=tesekkur_cevabi(dil, soru))
    if not soru_gecerli_mi(soru):
        return _sonuc(
            arama_skoru=0.0,
            cevap=(
                "Seni net duyamadım, lütfen sorunu tekrar eder misin?"
                if not dil_ingilizce_mi(dil)
                else "I couldn't hear a clear question. Please try again."
            ),
        )

    kaynak, skor, meta = rag_ara(soru)
    if (
        skor < SCORE_THRESHOLD
        or not kaynak.strip()
        or not kaynak_soruya_uygun_mu(soru, kaynak, skor=skor)
    ):
        cevap = _selam_ekle(bulunamadi_mesaji(dil), dil)
        return _sonuc(
            arama_skoru=skor,
            kaynak_dosya=meta.get("source_file", ""),
            sinif=meta.get("grade", ""),
            cevap=cevap,
        )
    cevap = llm_cevapla(soru, dil, kaynak, meta=meta, sesli=False)
    if not cevap_kaynaga_dayali_mi(cevap, kaynak):
        cevap = bulunamadi_mesaji(dil)
    cevap = _selam_ekle(cevap, dil)
    return _sonuc(
        arama_skoru=skor,
        kaynak_dosya=meta.get("source_file", ""),
        sinif=meta.get("grade", ""),
        llm=LLM_PROVIDER,
        cevap=cevap,
    )

def pcm16_to_wav_bytes(pcm: bytes, sample_rate: int = 16000) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes(pcm)
    return buf.getvalue()

def _stt_lang(dil: str) -> str:
    return "en" if dil_ingilizce_mi(dil) else "tr"

def stt_pcm(pcm: bytes, sample_rate: int = 16000, dil: str = "Türkçe") -> str:
    if not groq_client:
        raise RuntimeError("GROQ_API_KEY tanımlı değil (.env dosyasına ekleyin)")
    wav = pcm16_to_wav_bytes(pcm, sample_rate)
    sonuc = groq_client.audio.transcriptions.create(
        file=("konusma.wav", wav),
        model="whisper-large-v3-turbo",
        language=_stt_lang(dil),
        response_format="json",
        temperature=0.0,
    )
    return (sonuc.text or "").strip()

def stt_upload_bytes(data: bytes, filename: str = "ses.wav", dil: str = "Türkçe") -> str:
    if not groq_client:
        raise RuntimeError("GROQ_API_KEY tanımlı değil (.env dosyasına ekleyin)")
    sonuc = groq_client.audio.transcriptions.create(
        file=(filename, data),
        model="whisper-large-v3-turbo",
        language=_stt_lang(dil),
        response_format="json",
        temperature=0.0,
    )
    return (sonuc.text or "").strip()

async def tts_to_mp3(metin: str, dil: str, dosya: str | None = None) -> str:
    voice = TTS_VOICE_EN if dil_ingilizce_mi(dil) else TTS_VOICE_TR
    if not dosya:
        fd, dosya = tempfile.mkstemp(suffix=".mp3", prefix="tts_")
        os.close(fd)
    print(f"[TTS] edge-tts basliyor ({len(metin)} karakter)", flush=True)
    await edge_tts.Communicate(metin, voice).save(dosya)
    print(f"[TTS] mp3 kaydedildi: {dosya}", flush=True)
    return dosya

def _mp3_to_pcm16(mp3_path: str, sample_rate: int = 16000) -> bytes:
    try:
        from pydub import AudioSegment

        seg = AudioSegment.from_mp3(mp3_path)
        seg = seg.set_frame_rate(sample_rate).set_channels(1).set_sample_width(2)
        raw = bytes(seg.raw_data)
        if len(raw) % 2:
            raw = raw[:-1]
        return raw
    except Exception as e_pydub:
        try:
            import miniaudio

            decoded = miniaudio.decode_file(
                mp3_path,
                nchannels=1,
                sample_rate=sample_rate,
                output_format=miniaudio.SampleFormat.SIGNED16,
            )
            raw = bytes(decoded.samples)
            if len(raw) % 2:
                raw = raw[:-1]
            return raw
        except Exception as e:
            raise RuntimeError(
                "MP3->PCM dönüşümü başarısız. ffmpeg kurulu pydub veya miniaudio gerekli. "
                f"Detay: pydub={e_pydub} | miniaudio={e}"
            ) from e

async def tts_to_pcm16(metin: str, dil: str, sample_rate: int = 16000) -> bytes:
    mp3_path = await tts_to_mp3(metin, dil)
    try:
        pcm = await asyncio.to_thread(_mp3_to_pcm16, mp3_path, sample_rate)
        print(f"[TTS] pcm hazir: {len(pcm)} byte", flush=True)
        return pcm
    finally:
        try:
            os.remove(mp3_path)
        except OSError:
            pass

def _sesli_anlama_ve_cevap(pcm: bytes, dil: str) -> tuple[str, str | None]:
    max_pcm = 16000 * 2 * 6
    if len(pcm) > max_pcm:
        print(f"[STT] uzun kayit kirpildi: {len(pcm)} -> {max_pcm}", flush=True)
        pcm = pcm[-max_pcm:]

    soru = stt_pcm(pcm, dil=dil)
    try:
        print(f"[STT] dil={dil} | {soru}", flush=True)
    except UnicodeEncodeError:
        print("[STT] (unicode log skip)", flush=True)

    if selamlama_mu(soru):
        global oturum_selamlandi
        cevap = selamlama_cevabi(dil, soru)  # icinde Merhaba! var
        oturum_selamlandi = True
        try:
            print(f"[SELAM] yanit: {cevap[:80]}", flush=True)
        except UnicodeEncodeError:
            print("[SELAM] yanit verildi", flush=True)
        return soru, cevap

    if tesekkur_mu(soru):
        cevap = tesekkur_cevabi(dil, soru)
        print(f"[TESEKKUR] yanit: {cevap}", flush=True)
        return soru, cevap

    if not (soru or "").strip() or not soru_gecerli_mi(soru) or _stt_junk_mu(soru):
        print("[STT] bos/junk — sessiz gecildi", flush=True)
        return soru or "", None

    if not sesli_soru_mu(soru, dil):
        print("[STT] belirsiz ifade — sessiz gecildi", flush=True)
        return soru, None

    kaynak, skor, meta = rag_ara(soru, max_chars=2200)
    uygun = kaynak_soruya_uygun_mu(soru, kaynak, skor=skor)
    print(
        f"[RAG] skor={skor:.3f} uygun={uygun} grade={meta.get('grade')} "
        f"src={meta.get('source_file')} llm={LLM_PROVIDER}",
        flush=True,
    )

    if skor < SCORE_THRESHOLD or not kaynak.strip() or not uygun:
        print("[RAG] kaynak yok/uygunsuz — bulunamadi mesaji", flush=True)
        cevap = bulunamadi_mesaji(dil)
    else:
        cevap = llm_cevapla(soru, dil, kaynak, meta=meta, sesli=True)
        cl = _norm_tr(cevap)
        if (
            "mevcut degil" in cl
            or "not available in the textbooks" in cl
            or "ders notlarimda bulamadim" in cl
        ):
            cevap = bulunamadi_mesaji(dil)
        elif not cevap_kaynaga_dayali_mi(cevap, kaynak):
            print("[RAG] cevap kaynaga dayanmiyor — bulunamadi mesaji", flush=True)
            cevap = bulunamadi_mesaji(dil)

    cevap = _selam_ekle(cevap, dil)

    try:
        print(f"[LLM] {cevap[:120]}...", flush=True)
    except UnicodeEncodeError:
        print("[LLM] (unicode log skip)", flush=True)
    return soru, cevap

def _tts_dil_sec(dil: str, cevap: str) -> str:
    c = (cevap or "").lstrip().lower()
    if c.startswith("hello"):
        return "English"
    if c.startswith("merhaba"):
        return "Türkçe"
    return dil

def _cumlelere_bol(metin: str) -> list[str]:
    metin = (metin or "").strip()
    if not metin:
        return []
    parts = re.split(r"(?<=[\.\!\?])\s+", metin)
    out = [p.strip() for p in parts if p.strip()]
    return out or [metin]

async def sesli_pipeline(pcm: bytes, dil: str = "Türkçe") -> tuple[str, str, bytes]:
    soru, cevap = await asyncio.to_thread(_sesli_anlama_ve_cevap, pcm, dil)
    if cevap is None:
        return soru, "", b""
    try:
        import db as chat_db

        chat_db.kayit_ekle(soru, cevap, dil)
    except Exception:
        pass
    pcm_out = await tts_to_pcm16(cevap, _tts_dil_sec(dil, cevap))
    return soru, cevap, pcm_out

async def sesli_pipeline_stream(pcm: bytes, dil: str = "Türkçe"):
    soru, cevap = await asyncio.to_thread(_sesli_anlama_ve_cevap, pcm, dil)
    if not (cevap or "").strip():
        yield ("meta", soru, "")
        yield ("end",)
        return
    try:
        import db as chat_db

        chat_db.kayit_ekle(soru, cevap, dil)
    except Exception:
        pass
    yield ("meta", soru, cevap)
    tts_dil = _tts_dil_sec(dil, cevap)
    for cumle in _cumlelere_bol(cevap):
        chunk = await tts_to_pcm16(cumle, tts_dil)
        if chunk:
            yield ("pcm", chunk)
    yield ("end",)
