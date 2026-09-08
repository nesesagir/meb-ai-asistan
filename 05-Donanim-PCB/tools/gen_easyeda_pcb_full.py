#!/usr/bin/env python3
"""Aşama 2 PCB: kilitli yerleşim + USB şarj yolları + yerleşim haritası PNG."""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import gen_easyeda_sch as sch
import pcb_lib as pcb
import route_pcb
from PIL import Image, ImageDraw, ImageFont

USB_NET = {
    "A1B12": "GND",
    "B1A12": "GND",
    "A4B9": "VBUS",
    "B4A9": "VBUS",
    "A5": "CC1",
    "B5": "CC2",
    "A6": "USB_DP",
    "B6": "USB_DP",
    "A7": "USB_DM",
    "B7": "USB_DM",
    "13": "GND",
    "14": "GND",
}

# (ref, name, x_mm, y_mm, w, h)  origin = bottom-left, Type-C = alt
MAP = [
    ("J1", "USB-C", 16.0, 0.0, 18.0, 8.0),
    ("U1", "ESP32-S3 anten ustte", 16.0, 41.25, 18.0, 25.5),
    ("U2", "AXP2101 guc", 22.0, 30.0, 8.0, 8.0),
    ("U3", "ES7210 mik ADC", 36.5, 30.5, 7.0, 7.0),
    ("U4", "ES8311 codec", 11.0, 31.0, 6.0, 6.0),
    ("U5", "NS4150 hoparlor", 4.0, 16.0, 8.0, 8.0),
    ("MK1", "MEMS mik 1", 39.5, 14.0, 5.0, 4.0),
    ("MK2", "MEMS mik 2", 33.5, 14.0, 5.0, 4.0),
    ("L1", "1uH DCDC1", 11.0, 39.5, 6.0, 5.0),
    ("J2", "FPC 14P ekran", 3.0, 41.0, 10.0, 6.0),
    ("R4", "5.1k CC1", 20.5, 7.0, 2.5, 2.0),
    ("R5", "5.1k CC2", 27.0, 7.0, 2.5, 2.0),
    ("pasifler", "R/C seridi", 8.0, 25.0, 38.0, 4.0),
]


def pin_nets(product: dict, rules: list) -> dict[str, str]:
    nets: dict[str, str] = {}
    for raw in product["result"]["dataStr"].get("shape") or []:
        pin = sch.parse_pin(raw)
        if not pin:
            continue
        net = sch.match_net(pin["name"], rules)
        if net == "NC":
            nets[pin["num"]] = ""
        elif net:
            nets[pin["num"]] = net
    return nets


def draw_preview(path: Path) -> None:
    scale = 16
    pad = 40
    img = Image.new("RGB", (50 * scale + pad * 2, 72 * scale + pad * 2), (18, 18, 22))
    d = ImageDraw.Draw(img)

    def xy(x: float, y: float) -> tuple[int, int]:
        # SVG-like: y=0 at bottom of board -> image y grows down from top
        return int(pad + x * scale), int(pad + (72 - y) * scale)

    # board
    d.rectangle([xy(0, 72), xy(50, 0)], outline=(180, 80, 220), width=3)
    d.rectangle([xy(0, 72), xy(50, 57)], outline=(255, 200, 60), width=2)
    d.text((pad + 8, pad + 8), "anten keep-out 15 mm", fill=(255, 200, 60))
    for hx, hy in [(4, 10), (46, 10), (4, 50), (46, 50)]:
        cx, cy = xy(hx, hy)
        r = int(1.6 * scale)
        d.ellipse([cx - r, cy - r, cx + r, cy + r], outline=(160, 160, 160), width=2)
    colors = {
        "U1": (80, 180, 255),
        "U2": (255, 140, 80),
        "U3": (120, 220, 140),
        "U4": (180, 140, 255),
        "U5": (255, 90, 90),
        "J1": (255, 220, 80),
        "MK1": (80, 220, 220),
        "MK2": (80, 220, 220),
        "L1": (200, 200, 200),
        "J2": (255, 180, 120),
    }
    try:
        font = ImageFont.truetype("arial.ttf", 14)
        font_s = ImageFont.truetype("arial.ttf", 12)
    except OSError:
        font = ImageFont.load_default()
        font_s = font
    for ref, name, x, y, w, h in MAP:
        p0, p1 = xy(x, y + h), xy(x + w, y)
        col = colors.get(ref, (200, 200, 200))
        d.rectangle([p0, p1], outline=col, width=2)
        d.text((p0[0] + 4, p0[1] + 4), f"{ref} {name}", fill=col, font=font_s)
    # passives as dots
    d.text((pad, img.height - 28), "MEB AI Asistan  PCB 50x72 mm  Aşama 2 yerleşim", fill=(220, 220, 220), font=font)
    img.save(path)


def main() -> None:
    F = pcb.fetch_product
    usbc, esp, axp = F("C2765186"), F("C2913202"), F("C3036461")
    es7210, es8311, ns4150, mic = F("C365743"), F("C962342"), F("C189961"), F("C111990")
    r10k, r51k, r47k = F("C25744"), F("C25911"), F("C25905")
    c1u, c10u, c100n, c22u, l1p = F("C15849"), F("C19702"), F("C14663"), F("C45783"), F("C167265")
    fpc = F("C375915")
    J2_NET = {
        "1": "LCD_3V3",
        "2": "GND",
        "3": "TFT_CS",
        "4": "TFT_RST",
        "5": "TFT_DC",
        "6": "TFT_MOSI",
        "7": "TFT_SCLK",
        "8": "TFT_BL",
        "9": "",
        "10": "I2C_SCL",
        "11": "I2C_SDA",
        "12": "CTP_RST",
        "13": "CTP_INT",
        "14": "GND",
        "15": "GND",
        "16": "GND",
    }

    libs: list[str] = []
    all_pads: list[dict] = []

    def add(prod, ref, lcsc, xmm, ymm, nets, rot=0):
        lib, pads = pcb.place_lib(prod, ref, lcsc, *pcb.mm(xmm, ymm), nets, rot=rot)
        libs.append(lib)
        all_pads.extend(pcb.pads_from_lib(lib))
        return pads

    jp = add(usbc, "J1", "C2765186", 25.0, 3.0, USB_NET)
    ep = add(esp, "U1", "C2913202", 25.0, 54.0, pin_nets(esp, sch.ESP32_RULES), rot=180)
    add(axp, "U2", "C3036461", 24.0, 34.0, pin_nets(axp, sch.AXP_RULES))
    add(es7210, "U3", "C365743", 10.0, 34.0, pin_nets(es7210, sch.ES7210_RULES))
    add(es8311, "U4", "C962342", 36.0, 34.0, pin_nets(es8311, sch.ES8311_RULES))
    add(ns4150, "U5", "C189961", 42.0, 20.0, pin_nets(ns4150, sch.NS4150_RULES))
    add(mic, "MK1", "C111990", 8.0, 16.0, {"1": "GND", "2": "GND", "3": "GND", "4": "MIC1P", "6": "MICBIAS"}, rot=90)
    add(mic, "MK2", "C111990", 14.0, 16.0, {"1": "GND", "2": "GND", "3": "GND", "4": "MIC2P", "6": "MICBIAS"}, rot=90)
    add(l1p, "L1", "C167265", 14.0, 42.0, {"1": "DCDC1_LX", "2": "3V3"})
    add(fpc, "J2", "C375915", 42.0, 44.0, J2_NET, rot=90)

    def r(prod, ref, lcsc, xmm, ymm, n1, n2):
        return add(prod, ref, lcsc, xmm, ymm, {"1": n1, "2": n2})

    # USB CC + VBUS cap
    r4p = r(r51k, "R4", "C25911", 22.0, 8.0, "GND", "CC1")
    r5p = r(r51k, "R5", "C25911", 28.0, 8.0, "CC2", "GND")
    c2p = r(c10u, "C2", "C19702", 25.0, 11.0, "VBUS", "GND")
    # ESP
    r(r10k, "R1", "C25744", 36.0, 48.0, "BOOT", "3V3")
    r(r10k, "R2", "C25744", 36.0, 50.5, "ESP_EN", "3V3")
    r(c1u, "C1", "C15849", 36.0, 45.5, "ESP_EN", "GND")
    # AXP / rails
    r(c22u, "C3", "C45783", 24.0, 28.0, "SYS", "GND")
    r(c1u, "C4", "C15849", 27.5, 28.0, "VBAT", "GND")
    r(c10u, "C5", "C19702", 31.0, 28.0, "3V3", "GND")
    r(c10u, "C6", "C19702", 20.5, 28.0, "VBUS", "GND")
    r(r10k, "R8", "C25744", 18.0, 28.0, "AXP_IRQ", "3V3")
    r(r10k, "R9", "C25744", 15.5, 28.0, "BAT_NTC", "GND")
    r(r47k, "R6", "C25905", 13.0, 28.0, "I2C_SDA", "3V3")
    r(r47k, "R7", "C25905", 10.5, 28.0, "I2C_SCL", "3V3")
    # audio
    r(c1u, "C7", "C15849", 36.0, 26.0, "AUD_3V3", "GND")
    r(c100n, "C12", "C14663", 39.0, 26.0, "AUD_3V3", "GND")
    r(c1u, "C8", "C15849", 8.0, 26.0, "MIC_3V3", "GND")
    r(c100n, "C11", "C14663", 11.0, 26.0, "MIC_3V3", "GND")
    r(c10u, "C13", "C19702", 42.0, 26.0, "VBAT", "GND")
    r(r10k, "R3", "C25744", 42.0, 13.0, "PA_CTRL", "GND")
    r(c1u, "C9", "C15849", 40.0, 42.0, "LCD_3V3", "GND")
    r(c1u, "C10", "C15849", 43.0, 42.0, "CTP_3V3", "GND")

    a5, b5 = pcb.first(jp, "A5"), pcb.first(jp, "B5")
    a4, b4 = pcb.first(jp, "A4B9"), pcb.first(jp, "B4A9")
    a1, b1 = pcb.first(jp, "A1B12"), pcb.first(jp, "B1A12")
    a6, b6 = pcb.first(jp, "A6"), pcb.first(jp, "B6")
    a7, b7 = pcb.first(jp, "A7"), pcb.first(jp, "B7")
    gnd_l = max(jp["13"], key=lambda p: p[1])
    gnd_r = max(jp["14"], key=lambda p: p[1])
    y_bus = a5[1] + 10.0
    y_gnd = gnd_l[1]
    r4_cc, r5_cc = pcb.first(r4p, "2"), pcb.first(r5p, "1")
    c2_v = pcb.first(c2p, "1")
    traces = [
        # USB island = 08-PCB-USB-CC (CC stubs stop below the VBUS bar)
        pcb.track([(4093.505, 3002.461), (4093.505, 3009.461)], "CC1", 0.8),
        pcb.track([(4105.315, 3002.461), (4105.315, 3009.461)], "CC2", 0.8),
        pcb.track(
            [(4088.977, 3002.461), (4088.977, 3014.461), (4107.874, 3014.461), (4107.874, 3002.461)],
            "VBUS",
            1.4,
        ),
        pcb.track([(4098.426, 3014.461), (4095.669, 3020.461)], "VBUS", 1.4),
        pcb.track([(4085.827, 3002.461), (4085.827, 3021.162), (4081.398, 3021.162)], "GND", 1.2),
        pcb.track([(4111.024, 3002.461), (4111.024, 3021.162), (4115.453, 3021.162)], "GND", 1.2),
        pcb.track([a1, (a1[0], y_gnd), gnd_l], "GND", 1.2),
        pcb.track([b1, (b1[0], y_gnd), gnd_r], "GND", 1.2),
    ]

    def mm_track(pts: list[tuple[float, float]], net: str, w: float, layer: str = "2") -> str:
        return pcb.track([pcb.mm(x, y) for x, y in pts], net, w, layer)

    traces += [
        mm_track([(33.75, 47.65), (8.0, 47.65)], "USB_DM", 0.8, "2"),
        mm_track([(8.0, 47.65), (8.0, 8.0)], "USB_DM", 0.8, "1"),
        mm_track([(8.0, 8.0), (25.25, 8.0)], "USB_DM", 0.8, "2"),
        mm_track([(33.75, 46.38), (10.0, 44.0)], "USB_DP", 0.8, "2"),
        mm_track([(10.0, 44.0), (10.0, 9.5)], "USB_DP", 0.8, "1"),
        mm_track([(10.0, 9.5), (24.75, 9.5)], "USB_DP", 0.8, "2"),
    ]
    traces += [
        pcb.via(*pcb.mm(8.0, 47.65), "USB_DM"),
        pcb.via(*pcb.mm(8.0, 8.0), "USB_DM"),
        pcb.via(*pcb.mm(33.75, 47.65), "USB_DM"),
        pcb.via(*pcb.mm(10.0, 44.0), "USB_DP"),
        pcb.via(*pcb.mm(10.0, 9.5), "USB_DP"),
        pcb.via(*pcb.mm(33.75, 46.38), "USB_DP"),
    ]
    routed, stats = route_pcb.route(all_pads, traces)
    print("route", stats["ok"], "ok,", len(stats["fail"]), "fail, vias", stats.get("vias"), flush=True)
    if stats["fail"]:
        print("FAIL", stats["fail"], flush=True)
    copper_shapes = [s for s in traces + routed if s.startswith(("TRACK", "VIA"))]
    drc = route_pcb.clearance_errors(copper_shapes, all_pads)
    print("drc", len(drc), flush=True)
    for line in drc[:40]:
        print(" ", line, flush=True)

    shapes = pcb.outline_shapes() + libs + traces + routed
    dest = pcb.OUT / "09-PCB-TAM.json"
    dest.write_text(json.dumps(pcb.pcb_doc(shapes), ensure_ascii=False, indent=2), encoding="utf-8")
    tv = route_pcb.tv_from_shapes(pcb.outline_shapes() + traces + routed)
    (pcb.OUT / "_tv.json").write_text(json.dumps(tv, ensure_ascii=False), encoding="utf-8")
    print("tv", len(tv["TRACK"]), "tracks", len(tv["VIA"]), "vias", len(tv["COPPERAREA"]), "pours", flush=True)
    png = pcb.OUT / "A2-YERLESIM.png"
    draw_preview(png)
    notes = """MEB AI Asistan PCB — kilitli mekanik

Kart: 50 x 72 x 1.6 mm, 4 katman. Orijin sol-alt, Type-C = alt.

Parça merkezleri (mm), ekran yüzü = Top:
  J1 USB-C          25.0,  3.0
  U1 ESP32-S3       25.0, 54.0  (anten üst, keep-out y=57..72)
  U2 AXP2101        26.0, 34.0
  U3 ES7210         40.0, 34.0
  U4 ES8311         14.0, 34.0
  U5 NS4150          8.0, 20.0
  MK1 / MK2         42.0 / 36.0, 16.0  (sağ)
  L1 1uH            14.0, 42.0
  J2 FPC 14P         8.0, 44.0  (sol, LCD+CTP)

M2 NPTH Ø2.2 mm: (4,10) (46,10) (4,50) (46,50)
Kasa hedef: 58 x 90 x 20 mm. Batarya 35 x 34 x 6.5 mm.

Dosya: 09-PCB-TAM.json
Harita: A2-YERLESIM.png
"""
    (pcb.OUT / "PCB-OLCULER.txt").write_text(notes, encoding="utf-8")
    print("OK", dest, "libs", len(libs), "png", png)


if __name__ == "__main__":
    main()
