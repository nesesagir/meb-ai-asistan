#!/usr/bin/env python3
"""Build EasyEDA Std schematic JSON from LCSC symbols + firmware net map."""
from __future__ import annotations

import json
import re
import ssl
import urllib.request
from pathlib import Path

OUT = Path(__file__).resolve().parents[1] / "easyeda"
CACHE = Path(__file__).resolve().parent / "_cache"
CACHE.mkdir(parents=True, exist_ok=True)
OUT.mkdir(parents=True, exist_ok=True)

CTX = ssl.create_default_context()
_ID = 1000


def gid() -> str:
    global _ID
    _ID += 1
    return f"gge{_ID}"


def uniquify(text: str) -> str:
    def repl(_m):
        return gid()

    return re.sub(r"gge\d+", repl, text)


def http_json(url: str) -> dict:
    req = urllib.request.Request(url, headers={"User-Agent": "MEB-AI-Asistan-PCB/1.0"})
    with urllib.request.urlopen(req, context=CTX, timeout=45) as resp:
        return json.loads(resp.read().decode("utf-8"))


def fetch_product(lcsc: str) -> dict:
    path = CACHE / f"{lcsc}.json"
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    data = http_json(f"https://easyeda.com/api/products/{lcsc}/components?version=6.4.7")
    if not data.get("success"):
        raise RuntimeError(f"{lcsc}: {data}")
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    return data


def parse_pin(shape: str) -> dict | None:
    if not shape.startswith("P~"):
        return None
    parts = shape.split("^^")
    head = parts[0].split("~")
    # P show elec num x y rot id ...
    try:
        num = head[3]
        x = float(head[4])
        y = float(head[5])
        rot = head[6] if len(head) > 6 else "0"
    except (IndexError, ValueError):
        return None
    if rot in ("", "null", "None"):
        rot = "0"
    name = ""
    if len(parts) >= 4:
        np = parts[3].split("~")
        if len(np) >= 5:
            name = np[4]
    if len(parts) >= 2:
        dot = parts[1].split("~")
        if len(dot) >= 2:
            try:
                x, y = float(dot[0]), float(dot[1])
            except ValueError:
                pass
    return {"num": num, "name": name, "x": x, "y": y, "rot": rot}


def ascii_val(v) -> str:
    s = str(v)
    return "".join(ch if ord(ch) < 128 else "" for ch in s).strip()


def c_para_str(c_para: dict, ref: str, extra: dict | None = None) -> str:
    d = {k: ascii_val(v) for k, v in (c_para or {}).items()}
    d["pre"] = ref
    if extra:
        d.update(extra)
    bits = [f"{k}`{v}" for k, v in d.items()]
    return "`".join(bits)


def symbol_to_lib(product: dict, ref: str, dx: float = 0, dy: float = 0) -> tuple[str, list[dict], dict]:
    result = product["result"]
    ds = result["dataStr"]
    head = ds["head"]
    ox = float(head.get("x", 0))
    oy = float(head.get("y", 0))
    c_para = head.get("c_para") or {}
    pins = []
    shapes = []
    for raw in ds.get("shape") or []:
        s = translate_shape(raw, dx, dy)
        shapes.append(s)
        pin = parse_pin(s)
        if pin:
            pins.append(pin)
    attr = c_para_str(c_para, ref)
    lib_id = gid()
    puuid = head.get("puuid") or result.get("packageDetail", {}).get("uuid") or ""
    uuid = head.get("uuid") or result.get("uuid") or ""
    inner = "#@$".join(uniquify(s) for s in shapes)
    prefix = (
        f"T~P~{ox + dx}~{oy + dy - 18}~0~#000080~Arial~~~~~comment~{ref}~1~start~{gid()}~0~"
    )
    name = c_para.get("name") or c_para.get("Manufacturer Part") or ref
    ntxt = (
        f"T~N~{ox + dx}~{oy + dy - 8}~0~#000080~Arial~~~~~comment~{name}~1~start~{gid()}~0~"
    )
    lib = (
        f"LIB~{ox + dx}~{oy + dy}~{attr}~~0~{lib_id}~{puuid}~{uuid}~0~~yes~yes"
        f"#@${prefix}#@${ntxt}#@${inner}"
    )
    return uniquify(lib), pins, {"ox": ox + dx, "oy": oy + dy, "c_para": c_para}


def add_xy_path(path: str, dx: float, dy: float) -> str:
    def repl_comma(m):
        return f"{m.group(1)}{float(m.group(2)) + dx},{float(m.group(3)) + dy}"

    def repl_space(m):
        return f"{m.group(1)} {float(m.group(2)) + dx} {float(m.group(3)) + dy}"

    path = re.sub(r"([ML])(-?\d+\.?\d*),(-?\d+\.?\d*)", repl_comma, path)
    path = re.sub(r"([ML])\s+(-?\d+\.?\d*)\s+(-?\d+\.?\d*)", repl_space, path)
    return path


def _shift_xy_fields(seg: str, dx: float, dy: float, xi: int, yi: int) -> str:
    p = seg.split("~")
    if len(p) > max(xi, yi):
        try:
            p[xi] = str(float(p[xi]) + dx)
            p[yi] = str(float(p[yi]) + dy)
        except ValueError:
            return seg
    return "~".join(p)


def translate_shape(s: str, dx: float, dy: float) -> str:
    if dx == 0 and dy == 0:
        return s
    cmd = s.split("~", 1)[0]
    if cmd == "P":
        parts = s.split("^^")
        h = parts[0].split("~")
        h[4] = str(float(h[4]) + dx)
        h[5] = str(float(h[5]) + dy)
        parts[0] = "~".join(h)
        if len(parts) > 1:
            parts[1] = _shift_xy_fields(parts[1], dx, dy, 0, 1)
        if len(parts) > 2:
            segs = parts[2].split("~")
            segs[0] = add_xy_path(segs[0], dx, dy)
            parts[2] = "~".join(segs)
        if len(parts) > 3:
            parts[3] = _shift_xy_fields(parts[3], dx, dy, 1, 2)
        if len(parts) > 4:
            parts[4] = _shift_xy_fields(parts[4], dx, dy, 1, 2)
        if len(parts) > 5:
            parts[5] = _shift_xy_fields(parts[5], dx, dy, 1, 2)
        if len(parts) > 6:
            head, _, tail = parts[6].partition("~")
            parts[6] = head + "~" + add_xy_path(tail, dx, dy) if tail else add_xy_path(parts[6], dx, dy)
        return "^^".join(parts)
    if cmd == "R":
        p = s.split("~")
        p[1] = str(float(p[1]) + dx)
        p[2] = str(float(p[2]) + dy)
        return "~".join(p)
    if cmd == "E":
        p = s.split("~")
        p[1] = str(float(p[1]) + dx)
        p[2] = str(float(p[2]) + dy)
        return "~".join(p)
    if cmd == "C":
        p = s.split("~")
        p[1] = str(float(p[1]) + dx)
        p[2] = str(float(p[2]) + dy)
        return "~".join(p)
    if cmd == "T":
        p = s.split("~")
        p[2] = str(float(p[2]) + dx)
        p[3] = str(float(p[3]) + dy)
        return "~".join(p)
    if cmd in ("PL", "W", "B"):
        p = s.split("~")
        pts = p[1].split()
        out = []
        i = 0
        while i + 1 < len(pts):
            try:
                out.append(str(float(pts[i]) + dx))
                out.append(str(float(pts[i + 1]) + dy))
                i += 2
            except ValueError:
                out.append(pts[i])
                i += 1
        p[1] = " ".join(out)
        return "~".join(p)
    if cmd == "PT":
        p = s.split("~")
        p[1] = add_xy_path(p[1], dx, dy)
        return "~".join(p)
    return s


def netlabel(x: float, y: float, name: str, rot) -> str:
    try:
        r = int(float(rot)) if rot not in ("", "null") else 0
    except ValueError:
        r = 0
    if r % 360 == 180:
        anchor, tx, ty = "end", x - 2, y
    elif r % 360 == 270:
        anchor, tx, ty = "start", x, y + 12
    elif r % 360 == 90:
        anchor, tx, ty = "start", x, y - 4
    else:
        anchor, tx, ty = "start", x + 2, y
    color = "#CC0000" if name == "GND" else "#000080"
    return f"N~{x}~{y}~{r}~{color}~{name}~{gid()}~{anchor}~{tx}~{ty}~Times New Roman~7pt~0"


def noconnect(x: float, y: float) -> str:
    return (
        f"O~{x}~{y}~{gid()}~"
        f"M{x-4} {y-4}L{x+4} {y+4}M{x+4} {y-4}L{x-4} {y+4}~#FF0000~0"
    )


def title(x: float, y: float, text: str, size: str = "14pt") -> str:
    return (
        f"T~L~{x}~{y}~0~#000000~Arial~{size}~bold~normal~~comment~{text}~1~start~{gid()}~0~"
    )


def note(x: float, y: float, text: str) -> str:
    return (
        f"T~L~{x}~{y}~0~#333333~Arial~9pt~normal~normal~~comment~{text}~1~start~{gid()}~0~"
    )


def norm(s: str) -> str:
    return re.sub(r"[^A-Z0-9+]+", "", (s or "").upper())


def match_net(pin_name: str, rules: list[tuple[str, str]]) -> str | None:
    n = norm(pin_name)
    if not n:
        return None
    exact = {norm(p): net for p, net in rules}
    if n in exact:
        return exact[n]
    aliases = {
        "USBDP": "USB_DP", "DP": "USB_DP", "DPLUS": "USB_DP",
        "USBDM": "USB_DM", "DM": "USB_DM", "DMINUS": "USB_DM",
        "USBD+": "USB_DP", "USBD-": "USB_DM",
        "A5": "CC1", "B5": "CC2",
        "A6": "USB_DP", "A7": "USB_DM", "B6": "USB_DP", "B7": "USB_DM",
        "A4": "VBUS", "A9": "VBUS", "B4": "VBUS", "B9": "VBUS",
        "A1": "GND", "A12": "GND", "B1": "GND", "B12": "GND",
    }
    if n in aliases:
        wanted = aliases[n]
        for _p, net in rules:
            if net == wanted:
                return net
        return wanted
    return None


def labels_for_pins(pins: list[dict], rules: list[tuple[str, str]]) -> list[str]:
    out = []
    used = set()
    for pin in pins:
        key = (round(pin["x"], 2), round(pin["y"], 2), pin["name"])
        if key in used:
            continue
        used.add(key)
        net = match_net(pin["name"], rules)
        if net == "NC" or net is None:
            if net == "NC":
                out.append(noconnect(pin["x"], pin["y"]))
            continue
        out.append(netlabel(pin["x"], pin["y"], net, pin["rot"]))
    return out


# EasyEDA Std default view is around 4000,3000. Content at 0,0 looks like an empty sheet.
OX, OY = 3560.0, 2725.0


def sheet(title_txt: str, shapes: list[str], ox: float = 4000, oy: float = 3000) -> dict:
    return {
        "head": {
            "docType": "1",
            "editorVersion": "6.5.46",
            "c_para": {},
            "x": str(int(ox)),
            "y": str(int(oy)),
            "hasIdFlag": True,
            "newgId": True,
            "importFlag": 0,
            "transformList": "",
            "c_spiceCmd": "",
            "isSheet": True,
        },
        "canvas": (
            f"CA~1000~1000~#FFFFFF~yes~#CCCCCC~5~1000~1000~line~5~pixel~5~{int(ox)}~{int(oy)}"
        ),
        "shape": shapes,
        "BBox": {"x": int(ox) - 250, "y": int(oy) - 220, "width": 700, "height": 550},
        "colors": [],
    }


ESP32_RULES = [
    ("GND", "GND"),
    ("3V3", "3V3"),
    ("EN", "ESP_EN"),
    ("IO4", "TFT_DC"),
    ("IO5", "TFT_CS"),
    ("IO6", "TFT_SCLK"),
    ("IO7", "TFT_MOSI"),
    ("IO15", "I2C_SDA"),
    ("IO16", "I2S_MCLK"),
    ("IO8", "I2S_DOUT"),
    ("IO19", "USB_DM"),
    ("IO20", "USB_DP"),
    ("IO46", "PA_CTRL"),
    ("IO9", "I2S_BCLK"),
    ("IO10", "I2S_DIN"),
    ("IO14", "I2C_SCL"),
    ("IO21", "CTP_INT"),
    ("IO47", "CTP_RST"),
    ("IO48", "AXP_IRQ"),
    ("IO45", "I2S_LRCK"),
    ("IO0", "BOOT"),
    ("IO38", "TFT_RST"),
    ("IO40", "TFT_BL"),
    ("RXD0", "UART_RXD"),
    ("TXD0", "UART_TXD"),
    ("IO35", "NC"),
    ("IO36", "NC"),
    ("IO37", "NC"),
    ("IO17", "NC"),
    ("IO18", "NC"),
    ("IO3", "NC"),
    ("IO11", "NC"),
    ("IO12", "NC"),
    ("IO13", "NC"),
    ("IO39", "NC"),
    ("IO41", "NC"),
    ("IO42", "NC"),
    ("IO2", "NC"),
    ("IO1", "NC"),
]

USBC_RULES = [
    ("A1B12", "GND"),
    ("B1A12", "GND"),
    ("A4B9", "VBUS"),
    ("B4A9", "VBUS"),
    ("A5", "CC1"),
    ("B5", "CC2"),
    ("Dp1", "USB_DP"),
    ("Dn1", "USB_DM"),
    ("Dp2", "USB_DP"),
    ("Dn2", "USB_DM"),
    ("SBU1", "NC"),
    ("SBU2", "NC"),
    ("EH", "GND"),
    ("GND", "GND"),
    ("VBUS", "VBUS"),
    ("CC1", "CC1"),
    ("CC2", "CC2"),
]

AXP_RULES = [
    ("PWRON", "PWRON"),
    ("IRQ", "AXP_IRQ"),
    ("SDA", "I2C_SDA"),
    ("SCK", "I2C_SCL"),
    ("TS", "BAT_NTC"),
    ("BAT", "VBAT"),
    ("VSYS", "SYS"),
    ("VIN1", "SYS"),
    ("VIN2", "SYS"),
    ("VIN3", "SYS"),
    ("VIN4", "SYS"),
    ("VBUS", "VBUS"),
    ("LX1", "DCDC1_LX"),
    ("FB1", "3V3"),
    ("PWROK", "ESP_EN"),
    ("GND", "GND"),
    ("EP", "GND"),
    ("ALDO1", "AUD_3V3"),
    ("ALDO2", "MIC_3V3"),
    ("ALDO3", "LCD_3V3"),
    ("ALDO4", "NC"),
    ("ALDOIN", "SYS"),
    ("BLDO1", "CTP_3V3"),
    ("BLDO2", "3V3"),
    ("BLDOIN", "SYS"),
    ("CHGLED", "NC"),
    ("VREF", "AXP_VREF"),
    ("SW", "NC"),
    ("VMID", "AXP_VMID"),
    ("VBACKUP", "NC"),
    ("VRTC", "NC"),
    ("CPULDOS", "NC"),
    ("DLDO1/DC1SW", "NC"),
    ("DLDO2/DC4SW", "NC"),
    ("GPIO1/FB5/RTC/LDO2", "NC"),
    ("LX2", "NC"),
    ("FB2", "NC"),
    ("LX3", "NC"),
    ("FB3", "NC"),
    ("LX4", "NC"),
    ("FB4", "NC"),
]

ES8311_RULES = [
    ("MCLK", "I2S_MCLK"),
    ("SCLK/DMIC_SCL", "I2S_BCLK"),
    ("LRCK", "I2S_LRCK"),
    ("DSDIN", "I2S_DOUT"),
    ("ASDOUT", "NC"),
    ("CCLK", "I2C_SCL"),
    ("CDATA", "I2C_SDA"),
    ("OUTP", "DAC_P"),
    ("OUTN", "DAC_N"),
    ("DVDD", "AUD_3V3"),
    ("PVDD", "AUD_3V3"),
    ("AVDD", "AUD_3V3"),
    ("AGND", "GND"),
    ("DGND", "GND"),
    ("EP", "GND"),
    ("VMID", "ES8311_VMID"),
    ("DACVREF", "ES8311_DACVREF"),
    ("ADCVREF", "ES8311_ADCVREF"),
    ("CE", "AUD_3V3"),
    ("MIC1N", "NC"),
    ("MIC1P/DMIC_SDA", "NC"),
]

ES7210_RULES = [
    ("MCLK", "I2S_MCLK"),
    ("SCLK", "I2S_BCLK"),
    ("LRCK", "I2S_LRCK"),
    ("SDOUT1/TDMOUT", "I2S_DIN"),
    ("SDOUT2/TDMIN", "NC"),
    ("CCLK", "I2C_SCL"),
    ("CDATA", "I2C_SDA"),
    ("MIC1P", "MIC1P"),
    ("MIC1N", "MIC1N"),
    ("MIC2P", "MIC2P"),
    ("MIC2N", "MIC2N"),
    ("MIC3P", "AEC_P"),
    ("MIC3N", "AEC_N"),
    ("MIC4P", "NC"),
    ("MIC4N", "NC"),
    ("VDDD", "MIC_3V3"),
    ("VDDA", "MIC_3V3"),
    ("VDDP", "MIC_3V3"),
    ("VDDM", "MIC_3V3"),
    ("GNDD", "GND"),
    ("GNDA", "GND"),
    ("EP", "GND"),
    ("MICBIAS12", "MICBIAS"),
    ("MICBIAS34", "NC"),
    ("INT", "NC"),
    ("AD0", "GND"),
    ("AD1", "GND"),
    ("DMIC_CLK", "NC"),
    ("REFP12", "ES7210_REFP12"),
    ("REFQ12", "ES7210_REFQ12"),
    ("REFP34", "NC"),
    ("REFQ34", "NC"),
    ("REFQM", "ES7210_REFQM"),
]

NS4150_RULES = [
    ("INP", "DAC_P"),
    ("INN", "DAC_N"),
    ("CTRL", "PA_CTRL"),
    ("VoP", "SPK_P"),
    ("VON", "SPK_N"),
    ("VCC", "VBAT"),
    ("GND", "GND"),
    ("Bypass", "NS4150_BYP"),
]

MIC_RULES = [
    ("OUT", "MIC_SIG"),
    ("OUTPUT", "MIC_SIG"),
    ("VDD", "MICBIAS"),
    ("VDD", "MIC_3V3"),
    ("GND", "GND"),
]


def dump_pins(tag: str, pins: list[dict]) -> None:
    lines = [f"{p['num']:>4}  {p['name']}" for p in pins]
    (CACHE / f"pins_{tag}.txt").write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    parts = {
        "esp32": "C2913202",
        "usbc": "C2765186",
        "axp": "C3036461",
        "es8311": "C962342",
        "es7210": "C365743",
        "ns4150": "C189961",
        "mic": "C111990",
    }
    fetched = {k: fetch_product(v) for k, v in parts.items()}

    # --- Sheet 1: MCU + USB ---
    s1 = [
        title(OX - 200, OY - 230, "MEB AI Asistan - 1/5  MCU + USB-C"),
        note(OX - 200, OY - 210, "Firmware pinleri kilitli. Ayni isimli net etiketleri tum sayfalarda ortaktir."),
        note(OX - 200, OY - 194, "IO35/36/37 = octal PSRAM, baglama. Type-C: CC1 ve CC2 ye 5.1k GND (sonraki adimda pasifler)."),
    ]
    lib, pins, _ = symbol_to_lib(fetched["esp32"], "U1", OX, OY)
    dump_pins("esp32", pins)
    s1.append(lib)
    s1.extend(labels_for_pins(pins, ESP32_RULES))

    lib, pins, meta = symbol_to_lib(fetched["usbc"], "J1", OX - 280, OY + 40)
    dump_pins("usbc", pins)
    s1.append(lib)
    s1.extend(labels_for_pins(pins, USBC_RULES))
    s1.append(note(OX - 200, OY + 220, "U1 ESP32-S3-WROOM-1-N16R8  C2913202    J1 TYPE-C 16P  C2765186"))

    # --- Sheet 2: AXP2101 (native LCSC coords — File Source accepts this) ---
    s2 = [
        title(80, 40, "MEB AI Asistan - 2/5  AXP2101 guc"),
        note(80, 60, "DCDC1 -> 3V3 (ESP32). ALDO1 ses, ALDO2 mik, ALDO3 LCD, BLDO1 dokunma."),
        note(80, 76, "Bobin/kapasitorleri AXP2101 typical application ile sonraki adimda. Net isimleri kilitli."),
        note(80, 92, "PWRON: power tusu (GND). VBAT: Li-Po. VBUS: Type-C. PWROK -> ESP_EN."),
    ]
    lib, pins, _ = symbol_to_lib(fetched["axp"], "U2", 0, 0)
    dump_pins("axp", pins)
    s2.append(lib)
    s2.extend(labels_for_pins(pins, AXP_RULES))

    s2_simple = [
        title(4000, 2780, "MEB AI Asistan - 2/5  AXP2101  C3036461"),
        note(4000, 2800, "Sol: LCSC Parcalari kutusuna C3036461 yaz, U2 olarak yerlestir."),
        note(4000, 2816, "DCDC1 -> 3V3. ALDO1 AUD_3V3. ALDO2 MIC_3V3. ALDO3 LCD_3V3. BLDO1 CTP_3V3."),
        note(4000, 2832, "VBUS Type-C. BAT Li-Po. PWROK -> ESP_EN. SDA/SCK -> I2C."),
    ]
    for net, y in [
        ("VBUS", 2880), ("VBAT", 2900), ("SYS", 2920), ("3V3", 2940),
        ("ESP_EN", 2960), ("I2C_SDA", 2980), ("I2C_SCL", 3000),
        ("AUD_3V3", 3020), ("MIC_3V3", 3040), ("LCD_3V3", 3060),
        ("CTP_3V3", 3080), ("PWRON", 3100), ("GND", 3120),
    ]:
        s2_simple.append(netlabel(4000, y, net, 0))

    # --- Sheet 3: ES7210 (native LCSC coords, same method as 02) ---
    s3 = [
        title(80, 40, "MEB AI Asistan - 3/5  ES7210 mikrofon ADC"),
        note(80, 60, "I2S saatleri ES8311 ile ortak. SDOUT -> I2S_DIN (GPIO10). Adres 0x40."),
        note(80, 76, "MK1/MK2 MEMS mik C111990. LCSC Parcalari kutusuna C111990 yaz, iki tane koy."),
        note(80, 92, "MIC1P/MIC2P -> ES7210. MICBIAS <- MICBIAS12. GND ortak."),
    ]
    lib, pins, _ = symbol_to_lib(fetched["es7210"], "U3", 0, 0)
    dump_pins("es7210", pins)
    s3.append(lib)
    s3.extend(labels_for_pins(pins, ES7210_RULES))

    # --- Sheet 4: ES8311 native + NS4150 slightly to the right ---
    s4 = [
        title(80, 40, "MEB AI Asistan - 4/5  ES8311 + NS4150 hoparlor"),
        note(80, 60, "DSDIN <- I2S_DOUT (GPIO8). PA_CTRL = GPIO46, boot'ta LOW (10k pulldown). Adres 0x18."),
        note(80, 76, "OUTP/OUTN -> NS4150 IN. Hoparlor 8 ohm. PVDD = VBAT."),
    ]
    lib, pins, _ = symbol_to_lib(fetched["es8311"], "U4", 0, 0)
    dump_pins("es8311", pins)
    s4.append(lib)
    s4.extend(labels_for_pins(pins, ES8311_RULES))
    lib, pins, _ = symbol_to_lib(fetched["ns4150"], "U5", 280, 0)
    dump_pins("ns4150", pins)
    s4.append(lib)
    s4.extend(labels_for_pins(pins, NS4150_RULES))

    # --- Sheet 5: Display notes (no LCSC LIB) ---
    s5 = [
        title(80, 40, "MEB AI Asistan - 5/5  2.8 inc SPI + kapasitif dokunma"),
        note(80, 70, "Kartta 0.5mm 14P FPC konnektor kullan. Panel pin sirasi ureticiye gore dogrulanacak."),
        note(80, 100, "J2 LCD VCC     <- LCD_3V3"),
        note(80, 118, "J2 GND         <- GND"),
        note(80, 136, "J2 LCD_CS      <- TFT_CS     GPIO5"),
        note(80, 154, "J2 LCD_RST     <- TFT_RST    GPIO38"),
        note(80, 172, "J2 LCD_DC      <- TFT_DC     GPIO4"),
        note(80, 190, "J2 MOSI        <- TFT_MOSI   GPIO7"),
        note(80, 208, "J2 SCK         <- TFT_SCLK   GPIO6"),
        note(80, 226, "J2 LED/BL      <- TFT_BL     GPIO40"),
        note(80, 244, "J2 MISO        NC"),
        note(80, 262, "J2 CTP_SCL     <- I2C_SCL    GPIO14"),
        note(80, 280, "J2 CTP_SDA     <- I2C_SDA    GPIO15"),
        note(80, 298, "J2 CTP_RST     <- CTP_RST    GPIO47"),
        note(80, 316, "J2 CTP_INT     <- CTP_INT    GPIO21"),
        note(80, 350, "I2C pull-up: 4.7k SDA ve SCL -> 3V3 (BLDO2)."),
        note(80, 368, "Dokunma CI: CST816 (0x15) veya FT6336 (0x38). Firmware simdilik 0x15."),
        note(80, 400, "Cozunurluk 240x320 (ILI9341 veya ST7789)."),
    ]
    for net, y in [
        ("LCD_3V3", 460),
        ("TFT_CS", 480),
        ("TFT_RST", 500),
        ("TFT_DC", 520),
        ("TFT_MOSI", 540),
        ("TFT_SCLK", 560),
        ("TFT_BL", 580),
        ("I2C_SCL", 600),
        ("I2C_SDA", 620),
        ("CTP_RST", 640),
        ("CTP_INT", 660),
        ("GND", 680),
    ]:
        s5.append(netlabel(120, y, net, 0))

    # --- Sheet 6: passives (recipe, same import as 05) ---
    s6 = [
        title(80, 40, "MEB AI Asistan - 6/6  Pasifler  (JLCPCB Basic)"),
        note(80, 64, "Bu sayfa yerlestirme listesi. Parcayi sol LCSC Parcalari kutusuna C kodu yazarak koy."),
        note(80, 92, "MCU / USB  (sayfa 1)"),
        note(80, 110, "R1  10k   C25744   IO0 BOOT -> 3V3"),
        note(80, 128, "R2  10k   C25744   ESP_EN -> 3V3"),
        note(80, 146, "C1  1uF   C15849   ESP_EN -> GND   (reset gecikmesi)"),
        note(80, 164, "R3  10k   C25744   PA_CTRL GPIO46 -> GND   (boot'ta LOW sart)"),
        note(80, 182, "R4  5.1k  C25911   CC1 -> GND"),
        note(80, 200, "R5  5.1k  C25911   CC2 -> GND"),
        note(80, 218, "C2  10uF  C19702   VBUS -> GND  (16V 0805)"),
        note(80, 246, "I2C"),
        note(80, 264, "R6  4.7k  C25905   I2C_SDA -> 3V3"),
        note(80, 282, "R7  4.7k  C25905   I2C_SCL -> 3V3"),
        note(80, 310, "AXP2101  (sayfa 2)  DCDC2/3/4 kullanma, LX/FB bos"),
        note(80, 328, "L1  1uH 2A  C167265   LX1 --L1-- 3V3/FB1"),
        note(80, 346, "C3  22uF  C45783   VSYS -> GND"),
        note(80, 364, "C4  1uF   C15849   VBAT -> GND"),
        note(80, 382, "C5  10uF  C19702   3V3 -> GND  (DCDC1 cikis)"),
        note(80, 400, "C6  10uF  C19702   VBUS -> GND  (AXP yaninda)"),
        note(80, 418, "C7  1uF   C15849   AUD_3V3 -> GND"),
        note(80, 436, "C8  1uF   C15849   MIC_3V3 -> GND"),
        note(80, 454, "C9  1uF   C15849   LCD_3V3 -> GND"),
        note(80, 472, "C10 1uF   C15849   CTP_3V3 -> GND"),
        note(80, 490, "R8  10k   C25744   AXP_IRQ -> 3V3"),
        note(80, 508, "R9  10k   C25744   BAT_NTC/TS -> GND  (NTC yoksa)"),
        note(80, 536, "Ses / mik"),
        note(80, 554, "C11 100n  C14663   MIC_3V3 -> GND"),
        note(80, 572, "C12 100n  C14663   AUD_3V3 -> GND"),
        note(80, 590, "C13 10uF  C19702   VBAT -> GND  (NS4150 yaninda)"),
        note(80, 618, "PWRON: buton -> GND. DCDC1: 1uH, Isat > 2A."),
    ]

    sheets = [
        ("01-MCU-USB.json", "1 MCU USB", s1, 4000, 3000),
        ("02-AXP2101.json", "2 AXP2101", s2, 400, 300),
        ("03-ES7210-MIC.json", "3 ES7210", s3, 400, 300),
        ("04-ES8311-PA.json", "4 ES8311", s4, 400, 300),
        ("05-DISPLAY.json", "5 Display", s5, 400, 300),
        ("06-PASIFLER.json", "6 Pasifler", s6, 400, 300),
    ]
    index = []
    for fname, _title, shapes, ox, oy in sheets:
        doc = sheet(_title, shapes, ox, oy)
        (OUT / fname).write_text(json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8")
        index.append(fname)
    (OUT / "02-AXP2101-basit.json").write_text(
        json.dumps(sheet("2 AXP2101", s2_simple, 4000, 3000), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    bom = """Designator,LCSC,Value,Package,Function
U1,C2913202,ESP32-S3-WROOM-1-N16R8,module,MCU
U2,C3036461,AXP2101,QFN-40,PMIC
U3,C365743,ES7210,QFN-32,Mic ADC
U4,C962342,ES8311,QFN-20,Codec
U5,C189961,NS4150B,SOP-8,Speaker amp
J1,C2765186,TYPE-C 16PIN,SMD,USB-C
MK1,C111990,SPH1642HT5H-1,MEMS,Mic
MK2,C111990,SPH1642HT5H-1,MEMS,Mic
R1,C25744,10k,0402,BOOT pullup
R2,C25744,10k,0402,EN pullup
R3,C25744,10k,0402,PA_CTRL pulldown
R4,C25911,5.1k,0402,CC1
R5,C25911,5.1k,0402,CC2
R6,C25905,4.7k,0402,I2C SDA
R7,C25905,4.7k,0402,I2C SCL
R8,C25744,10k,0402,AXP IRQ
R9,C25744,10k,0402,TS no-NTC
C1,C15849,1uF,0402,EN delay
C2,C19702,10uF 16V,0805,VBUS
C3,C45783,22uF 16V,0805,VSYS
C4,C15849,1uF,0402,VBAT
C5,C19702,10uF 16V,0805,3V3
C6,C19702,10uF 16V,0805,VBUS AXP
C7,C15849,1uF,0402,AUD_3V3
C8,C15849,1uF,0402,MIC_3V3
C9,C15849,1uF,0402,LCD_3V3
C10,C15849,1uF,0402,CTP_3V3
C11,C14663,100nF,0402,MIC decouple
C12,C14663,100nF,0402,AUD decouple
C13,C19702,10uF 16V,0805,NS4150 PVDD
L1,C167265,1uH 2A,inductor,DCDC1
"""
    (OUT / "BOM-JLCPCB.csv").write_text(bom, encoding="utf-8")
    (OUT / "SHEETS.txt").write_text("\n".join(index), encoding="utf-8")
    print("OK", OUT)
    for p in CACHE.glob("pins_*.txt"):
        print("---", p.name)
        print(p.read_text(encoding="utf-8")[:800])


if __name__ == "__main__":
    main()
