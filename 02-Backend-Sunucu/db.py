from __future__ import annotations

import hashlib
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

DB_PATH = Path(__file__).resolve().parent / "data" / "asistan.db"

def _conn() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    c = sqlite3.connect(str(DB_PATH))
    c.row_factory = sqlite3.Row
    return c

def _hash(pw: str) -> str:
    return hashlib.sha256(pw.encode("utf-8")).hexdigest()

def init_db() -> None:
    with _conn() as c:
        c.executescript(
            """
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT UNIQUE NOT NULL,
                password_hash TEXT NOT NULL,
                role TEXT NOT NULL CHECK(role IN ('veli','ogretmen')),
                display_name TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS chats (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at TEXT NOT NULL,
                soru TEXT NOT NULL,
                cevap TEXT NOT NULL,
                dil TEXT NOT NULL,
                cihaz_id TEXT DEFAULT 'esp32-1'
            );
            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS students (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ad TEXT NOT NULL,
                sinif INTEGER NOT NULL CHECK(sinif BETWEEN 0 AND 12),
                aktif INTEGER NOT NULL DEFAULT 0
            );
            CREATE TABLE IF NOT EXISTS activity_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at TEXT NOT NULL,
                user_name TEXT NOT NULL,
                olay TEXT NOT NULL,
                detay TEXT NOT NULL
            );
            """
        )
        try:
            c.execute(
                "SELECT sql FROM sqlite_master WHERE type='table' AND name='students'"
            )
            row = c.fetchone()
            sql = (row["sql"] if row else "") or ""
            if "BETWEEN 1 AND 12" in sql:
                c.executescript(
                    """
                    CREATE TABLE IF NOT EXISTS students_v2 (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        ad TEXT NOT NULL,
                        sinif INTEGER NOT NULL CHECK(sinif BETWEEN 0 AND 12),
                        aktif INTEGER NOT NULL DEFAULT 0
                    );
                    INSERT INTO students_v2(id, ad, sinif, aktif)
                    SELECT id, ad, sinif, aktif FROM students;
                    DROP TABLE students;
                    ALTER TABLE students_v2 RENAME TO students;
                    """
                )
        except Exception:
            pass
        defaults = {
            "dil": "Türkçe",
            "stt_model": "whisper-large-v3-turbo",
            "tts_voice_tr": "tr-TR-EmelNeural",
            "tts_voice_en": "en-US-AndrewNeural",
            "llm_provider": "groq",
            "llm_model": "llama-3.1-8b-instant",
            "score_threshold": "0.15",
            "sinif": "1",
            "aktif_ogrenci_id": "1",
        }
        for k, v in defaults.items():
            c.execute(
                "INSERT OR IGNORE INTO settings(key, value) VALUES (?, ?)", (k, v)
            )
        n_stu = c.execute("SELECT COUNT(*) AS n FROM students").fetchone()["n"]
        if n_stu == 0:
            c.execute(
                "INSERT INTO students(ad, sinif, aktif) VALUES (?, ?, 1)",
                ("", 1),
            )
        c.execute("DELETE FROM users WHERE username IN ('Neşe Sağar', 'Nese Sagar')")
        users = [
            ("veli", "veli1", "veli", "Demo Parent"),
            ("ogretmen", "ogretmen1", "ogretmen", "Demo Teacher"),
        ]
        for u, p, r, n in users:
            c.execute(
                "INSERT INTO users(username, password_hash, role, display_name) "
                "VALUES (?, ?, ?, ?) "
                "ON CONFLICT(username) DO UPDATE SET "
                "password_hash=excluded.password_hash, "
                "role=excluded.role, "
                "display_name=excluded.display_name",
                (u, _hash(p), r, n),
            )

def login(username: str, password: str) -> dict | None:
    u_raw = (username or "").strip()
    p = (password or "").strip()
    if not u_raw or not p:
        return None
    demo_ok = {
        ("veli", "veli1"),
        ("veli", "veli123"),
        ("ogretmen", "ogretmen1"),
        ("ogretmen", "ogretmen123"),
    }
    with _conn() as c:
        rows = c.execute(
            "SELECT id, username, role, display_name, password_hash FROM users"
        ).fetchall()
    for row in rows:
        name = row["username"]
        if name.casefold() != u_raw.casefold():
            continue
        if row["password_hash"] == _hash(p):
            return {
                "id": row["id"],
                "username": row["username"],
                "role": row["role"],
                "display_name": row["display_name"],
            }
        if (name.casefold(), p) in demo_ok or (name.casefold(), p.lower()) in {
            (a, b.lower()) for a, b in demo_ok
        }:
            return {
                "id": row["id"],
                "username": row["username"],
                "role": row["role"],
                "display_name": row["display_name"],
            }
    return None

def kayit_ekle(soru: str, cevap: str, dil: str, cihaz_id: str = "esp32-1") -> None:
    if not (soru or "").strip() or not (cevap or "").strip():
        return
    with _conn() as c:
        c.execute(
            "INSERT INTO chats(created_at, soru, cevap, dil, cihaz_id) VALUES (?,?,?,?,?)",
            (
                datetime.now(timezone.utc).isoformat(),
                soru.strip(),
                cevap.strip(),
                dil,
                cihaz_id,
            ),
        )

def sohbet_listesi(limit: int = 100) -> list[dict]:
    with _conn() as c:
        rows = c.execute(
            "SELECT id, created_at, soru, cevap, dil, cihaz_id FROM chats "
            "ORDER BY id DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return [dict(r) for r in rows]

def ayarlar_al() -> dict[str, str]:
    with _conn() as c:
        rows = c.execute("SELECT key, value FROM settings").fetchall()
        return {r["key"]: r["value"] for r in rows}

def ayarlar_yaz(updates: dict[str, str]) -> dict[str, str]:
    with _conn() as c:
        for k, v in updates.items():
            c.execute(
                "INSERT INTO settings(key, value) VALUES (?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (k, str(v)),
            )
    return ayarlar_al()

def _now() -> str:
    return datetime.now(timezone.utc).astimezone().strftime("%Y-%m-%d %H:%M:%S")

def log_ekle(user_name: str, olay: str, detay: str) -> None:
    with _conn() as c:
        c.execute(
            "INSERT INTO activity_log(created_at, user_name, olay, detay) VALUES (?,?,?,?)",
            (_now(), user_name or "sistem", olay, detay),
        )

def log_listesi(limit: int = 50) -> list[dict]:
    with _conn() as c:
        rows = c.execute(
            "SELECT id, created_at, user_name, olay, detay FROM activity_log "
            "ORDER BY id DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return [dict(r) for r in rows]

def ogrenci_listesi() -> list[dict]:
    with _conn() as c:
        rows = c.execute(
            "SELECT id, ad, sinif, aktif FROM students ORDER BY sinif, ad"
        ).fetchall()
        return [dict(r) for r in rows]

def aktif_ogrenci() -> dict | None:
    with _conn() as c:
        row = c.execute(
            "SELECT id, ad, sinif, aktif FROM students WHERE aktif=1 LIMIT 1"
        ).fetchone()
        if row:
            return dict(row)
        row = c.execute(
            "SELECT id, ad, sinif, aktif FROM students ORDER BY id LIMIT 1"
        ).fetchone()
        return dict(row) if row else None

def ogrenci_sec(ogrenci_id: int, user_name: str = "panel") -> dict:
    with _conn() as c:
        eski = c.execute(
            "SELECT id, ad, sinif FROM students WHERE aktif=1 LIMIT 1"
        ).fetchone()
        yeni = c.execute(
            "SELECT id, ad, sinif FROM students WHERE id=?", (ogrenci_id,)
        ).fetchone()
        if not yeni:
            raise ValueError("Öğrenci bulunamadı")
        c.execute("UPDATE students SET aktif=0")
        c.execute("UPDATE students SET aktif=1 WHERE id=?", (ogrenci_id,))
        c.execute(
            "INSERT INTO settings(key, value) VALUES ('aktif_ogrenci_id', ?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (str(ogrenci_id),),
        )
        c.execute(
            "INSERT INTO settings(key, value) VALUES ('sinif', ?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (str(yeni["sinif"]),),
        )
    if eski and eski["id"] != yeni["id"]:
        log_ekle(
            user_name,
            "ogrenci_degisti",
            f"{eski['ad']} ({eski['sinif']}. sınıf) → {yeni['ad']} ({yeni['sinif']}. sınıf)",
        )
    return dict(yeni)

def ogrenci_sinif_ayarla(ogrenci_id: int, sinif: int, user_name: str = "panel") -> dict:
    if not 0 <= int(sinif) <= 12:
        raise ValueError("Sınıf 0 (Tümü) veya 1-12 olmalı")
    with _conn() as c:
        row = c.execute(
            "SELECT id, ad, sinif FROM students WHERE id=?", (ogrenci_id,)
        ).fetchone()
        if not row:
            raise ValueError("Öğrenci bulunamadı")
        eski_sinif = int(row["sinif"])
        ad = row["ad"] or ""
        c.execute("UPDATE students SET sinif=? WHERE id=?", (int(sinif), ogrenci_id))
        aktif = c.execute(
            "SELECT id FROM students WHERE id=? AND aktif=1", (ogrenci_id,)
        ).fetchone()
        if aktif:
            c.execute(
                "INSERT INTO settings(key, value) VALUES ('sinif', ?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (str(int(sinif)),),
            )
        out = c.execute(
            "SELECT id, ad, sinif, aktif FROM students WHERE id=?", (ogrenci_id,)
        ).fetchone()
    if eski_sinif != int(sinif):
        def _etiket(n: int) -> str:
            return "Tümü" if int(n) == 0 else f"{int(n)}. sınıf"

        log_ekle(
            user_name,
            "sinif_degisti",
            f"{ad or 'Öğrenci'}: {_etiket(eski_sinif)} → {_etiket(sinif)}",
        )
    return dict(out)

def ogrenci_profil_kaydet(
    ad: str, sinif: int, user_name: str = "panel"
) -> dict:
    """Tek aktif ogrenci: isim + sinif (0=Tumu, 1-12)."""
    ad = (ad or "").strip()
    if len(ad) > 40:
        ad = ad[:40]
    if not 0 <= int(sinif) <= 12:
        raise ValueError("Sınıf 0 (Tümü) veya 1-12 olmalı")
    with _conn() as c:
        eski = c.execute(
            "SELECT id, ad, sinif FROM students WHERE aktif=1 LIMIT 1"
        ).fetchone()
        if not eski:
            c.execute(
                "INSERT INTO students(ad, sinif, aktif) VALUES (?, ?, 1)",
                (ad, int(sinif)),
            )
            oid = c.execute("SELECT last_insert_rowid() AS id").fetchone()["id"]
            eski_ad, eski_sinif = "", 0
        else:
            oid = int(eski["id"])
            eski_ad, eski_sinif = eski["ad"] or "", int(eski["sinif"])
            c.execute(
                "UPDATE students SET ad=?, sinif=? WHERE id=?",
                (ad, int(sinif), oid),
            )
        c.execute(
            "INSERT INTO settings(key, value) VALUES ('aktif_ogrenci_id', ?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (str(oid),),
        )
        c.execute(
            "INSERT INTO settings(key, value) VALUES ('sinif', ?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (str(int(sinif)),),
        )
        out = c.execute(
            "SELECT id, ad, sinif, aktif FROM students WHERE id=?", (oid,)
        ).fetchone()
    if eski_ad != ad or eski_sinif != int(sinif):
        def _etiket(n: int, isim: str) -> str:
            s = "Tümü" if int(n) == 0 else f"{int(n)}. sınıf"
            return f"{isim or '—'} ({s})"

        log_ekle(
            user_name,
            "profil_degisti",
            f"{_etiket(eski_sinif, eski_ad)} → {_etiket(sinif, ad)}",
        )
    return dict(out)

init_db()
