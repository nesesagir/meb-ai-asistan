#!/usr/bin/env python3
"""EasyEDA Std PCB: 50x72 mm + USB-C charging island already routed.

User does not draw CC/VBUS/GND. Import 08-PCB-USB-CC.json as a new document.
"""
from __future__ import annotations

import json
import re
import ssl
import urllib.request
from pathlib import Path

OUT = Path(__file__).resolve().parents[1] / "easyeda"
CACHE = Path(__file__).resolve().parent / "_cache"
OUT.mkdir(parents=True, exist_ok=True)
CACHE.mkdir(parents=True, exist_ok=True)

U = 0.254
OX, OY = 4000.0, 3000.0
W_MM, H_MM = 50.0, 72.0
W, H = W_MM / U, H_MM / U

CTX = ssl.create_default_context()
_ID = 8000

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
    "B8": "",
    "A8": "",
    "13": "GND",
    "14": "GND",
}


def gid() -> str:
    global _ID
    _ID += 1
    return f"gge{_ID}"


def uniquify(text: str) -> str:
    return re.sub(r"gge\d+", lambda _m: gid(), text)


def mm(x: float, y: float) -> tuple[float, float]:
    return round(OX + x / U, 3), round(OY + y / U, 3)


def ascii_val(v) -> str:
    s = str(v)
    return "".join(ch if ord(ch) < 128 else "" for ch in s).strip()


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


def c_para_str(c_para: dict, ref: str, lcsc: str) -> str:
    keep = ("package", "pre", "Contributor", "Supplier", "Supplier Part", "Manufacturer", "Manufacturer Part")
    d = {k: ascii_val(v) for k, v in (c_para or {}).items() if k in keep}
    d["pre"] = ref
    d["Supplier"] = "LCSC"
    d["Supplier Part"] = lcsc
    return "`".join(f"{k}`{v}" for k, v in d.items())


def shift_pairs(text: str, dx: float, dy: float) -> str:
    toks = text.replace(",", " ").split()
    out: list[str] = []
    i = 0
    while i < len(toks):
        try:
            x = float(toks[i]) + dx
            y = float(toks[i + 1]) + dy
            out.append(f"{round(x, 4)} {round(y, 4)}")
            i += 2
        except (ValueError, IndexError):
            out.append(toks[i])
            i += 1
    return " ".join(out)


def shift_svg_path(path: str, dx: float, dy: float) -> str:
    def repl(m: re.Match) -> str:
        cmd, x, y = m.group(1), float(m.group(2)), float(m.group(3))
        return f"{cmd} {round(x + dx, 4)} {round(y + dy, 4)}"

    return re.sub(r"([ML])\s+(-?\d+\.?\d*)\s+(-?\d+\.?\d*)", repl, path)


def translate_pcb_shape(s: str, dx: float, dy: float, pin_nets: dict[str, str] | None = None) -> str | None:
    cmd = s.split("~", 1)[0]
    if cmd == "SVGNODE":
        return None
    if cmd == "PAD":
        p = s.split("~")
        p[2] = str(round(float(p[2]) + dx, 4))
        p[3] = str(round(float(p[3]) + dy, 4))
        if len(p) > 10 and p[10]:
            p[10] = shift_pairs(p[10], dx, dy)
        if len(p) > 13 and p[13] and " " in p[13]:
            p[13] = shift_pairs(p[13], dx, dy)
        if p[-1] and "," in p[-1]:
            a, b = p[-1].split(",", 1)
            try:
                p[-1] = f"{round(float(a) + dx, 4)},{round(float(b) + dy, 4)}"
            except ValueError:
                pass
        pin = p[8] if len(p) > 8 else ""
        if pin_nets is not None and pin in pin_nets:
            p[7] = pin_nets[pin]
        return "~".join(p)
    if cmd == "TRACK":
        p = s.split("~")
        if len(p) > 4:
            p[4] = shift_pairs(p[4], dx, dy)
        return "~".join(p)
    if cmd == "HOLE":
        p = s.split("~")
        p[1] = str(round(float(p[1]) + dx, 4))
        p[2] = str(round(float(p[2]) + dy, 4))
        return "~".join(p)
    if cmd == "CIRCLE":
        p = s.split("~")
        p[1] = str(round(float(p[1]) + dx, 4))
        p[2] = str(round(float(p[2]) + dy, 4))
        return "~".join(p)
    if cmd == "SOLIDREGION":
        p = s.split("~")
        if len(p) > 3:
            p[3] = shift_svg_path(p[3], dx, dy)
        return "~".join(p)
    if cmd == "ARC":
        p = s.split("~")
        if len(p) > 4:
            p[4] = shift_svg_path(p[4], dx, dy)
        return "~".join(p)
    if cmd == "TEXT":
        p = s.split("~")
        if len(p) > 2:
            try:
                p[1] = str(round(float(p[1]) + dx, 4))
                p[2] = str(round(float(p[2]) + dy, 4))
            except ValueError:
                pass
        return "~".join(p)
    return s


def parse_pads(shapes: list[str]) -> dict[str, list[tuple[float, float]]]:
    pads: dict[str, list[tuple[float, float]]] = {}
    for s in shapes:
        if not s.startswith("PAD~"):
            continue
        p = s.split("~")
        num = p[8]
        pads.setdefault(num, []).append((float(p[2]), float(p[3])))
    return pads


def place_lib(product: dict, ref: str, lcsc: str, tx: float, ty: float, pin_nets: dict[str, str] | None = None) -> tuple[str, dict[str, list[tuple[float, float]]]]:
    pkg = product["result"]["packageDetail"]
    ds = pkg["dataStr"]
    head = ds["head"]
    ox = float(head.get("x") or 0)
    oy = float(head.get("y") or 0)
    dx, dy = tx - ox, ty - oy
    inner: list[str] = []
    for raw in ds.get("shape") or []:
        t = translate_pcb_shape(raw, dx, dy, pin_nets)
        if t:
            inner.append(uniquify(t))
    attr = c_para_str(head.get("c_para") or {}, ref, lcsc)
    uuid = head.get("uuid") or pkg.get("uuid") or ""
    lib_id = gid()
    prefix = (
        f"TEXT~{round(tx, 3)}~{round(ty - 8, 3)}~0~1.2~#FFFF00~3~~none~{ref}~{gid()}~0"
    )
    lib = (
        f"LIB~{round(tx, 3)}~{round(ty, 3)}~{attr}~~0~{lib_id}~{uuid}"
        f"#@${prefix}#@$" + "#@$".join(inner)
    )
    return uniquify(lib), parse_pads(inner)


def track(pts: list[tuple[float, float]], net: str, width: float) -> str:
    body = " ".join(f"{round(x, 3)} {round(y, 3)}" for x, y in pts)
    return f"TRACK~{width}~1~{net}~{body}~{gid()}~0"


def first(pads: dict[str, list[tuple[float, float]]], num: str) -> tuple[float, float]:
    return pads[num][0]


def layers() -> list[str]:
    return [
        "1~TopLayer~#FF0000~true~true~true~",
        "2~BottomLayer~#0000FF~true~false~true~",
        "3~TopSilkLayer~#FFCC00~true~false~true~",
        "4~BottomSilkLayer~#66CC33~true~false~true~",
        "5~TopPasteMaskLayer~#808080~true~false~true~",
        "6~BottomPasteMaskLayer~#800000~true~false~true~",
        "7~TopSolderMaskLayer~#800080~true~false~true~0.3",
        "8~BottomSolderMaskLayer~#AA00FF~true~false~true~0.3",
        "10~BoardOutLine~#FF00FF~true~false~true~",
        "11~Multi-Layer~#C0C0C0~true~false~true~",
        "12~Document~#FFFFFF~true~false~true~",
        "13~TopAssembly~#33CC99~true~false~true~",
        "15~Mechanical~#F022F0~true~false~true~",
        "21~Inner1~#999966~true~false~true~",
        "22~Inner2~#008000~true~false~true~",
    ]


def objects() -> list[str]:
    return [
        "All~true~false",
        "Component~true~true",
        "Prefix~true~true",
        "Name~true~false",
        "Track~true~true",
        "Pad~true~true",
        "Via~true~true",
        "Hole~true~true",
        "Copper_Area~true~true",
        "Circle~true~true",
        "Arc~true~true",
        "Solid_Region~true~true",
        "Text~true~true",
        "Image~true~true",
        "Rect~true~true",
        "Dimension~true~true",
        "Protractor~true~true",
    ]


def outline_shapes() -> list[str]:
    x0, y0 = mm(0, 0)
    x1, y1 = mm(W_MM, H_MM)
    shapes = [f"TRACK~0.2~10~~{x0} {y0} {x1} {y0} {x1} {y1} {x0} {y1} {x0} {y0}~{gid()}~0"]
    kx0, ky0 = mm(0, H_MM - 15)
    kx1, ky1 = mm(W_MM, H_MM)
    shapes.append(
        f"TRACK~0.15~3~~{kx0} {ky0} {kx1} {ky0} {kx1} {ky1} {kx0} {ky1} {kx0} {ky0}~{gid()}~0"
    )
    hole_d = round(2.2 / U, 3)
    for hx, hy in [(4.0, 10.0), (46.0, 10.0), (4.0, 50.0), (46.0, 50.0)]:
        px, py = mm(hx, hy)
        shapes.append(f"HOLE~{px}~{py}~{hole_d}~{gid()}~0")
        shapes.append(f"CIRCLE~{px}~{py}~{round(1.6 / U, 3)}~0.2~3~{gid()}~0~~")
    return shapes


def main() -> None:
    usbc = fetch_product("C2765186")
    r510 = fetch_product("C25911")
    c10u = fetch_product("C19702")

    usb_tx, usb_ty = mm(25.0, 3.0)
    j1, jpads = place_lib(usbc, "J1", "C2765186", usb_tx, usb_ty, USB_NET)

    a5 = first(jpads, "A5")
    b5 = first(jpads, "B5")
    a4 = first(jpads, "A4B9")
    b4 = first(jpads, "B4A9")
    a1 = first(jpads, "A1B12")
    b1 = first(jpads, "B1A12")
    gnd_l = max(jpads["13"], key=lambda p: p[1])
    gnd_r = max(jpads["14"], key=lambda p: p[1])

    # 0402: pad1 = origin-1.704, pad2 = origin+1.704 (package units)
    r4_tx = a5[0] - 1.704
    r4_ty = a5[1] + 7.0
    r5_tx = b5[0] + 1.704
    r5_ty = b5[1] + 7.0
    r4, r4p = place_lib(r510, "R4", "C25911", r4_tx, r4_ty, {"1": "GND", "2": "CC1"})
    r5, r5p = place_lib(r510, "R5", "C25911", r5_tx, r5_ty, {"1": "CC2", "2": "GND"})

    c2_tx = (a4[0] + b4[0]) / 2
    c2_ty = a5[1] + 18.0
    c2, c2p = place_lib(c10u, "C2", "C19702", c2_tx, c2_ty, {"1": "VBUS", "2": "GND"})

    r4_1, r4_2 = first(r4p, "1"), first(r4p, "2")
    r5_1, r5_2 = first(r5p, "1"), first(r5p, "2")
    c2_1, c2_2 = first(c2p, "1"), first(c2p, "2")

    y_bus = a5[1] + 12.0
    y_gnd = gnd_l[1]
    traces = [
        # CC1 / CC2: vertical off the pin, then shell GND on the inner tabs
        track([a5, r4_2], "CC1", 0.8),
        track([r4_1, (r4_1[0], y_gnd), gnd_l], "GND", 0.8),
        track([b5, r5_1], "CC2", 0.8),
        track([r5_2, (r5_2[0], y_gnd), gnd_r], "GND", 0.8),
        # VBUS inward of the pin row, then 10uF
        track([a4, (a4[0], y_bus), (b4[0], y_bus), b4], "VBUS", 1.4),
        track([(c2_tx, y_bus), c2_1], "VBUS", 1.4),
        track([c2_2, (c2_2[0], y_gnd), gnd_r], "GND", 1.2),
        track([a1, (a1[0], y_gnd), gnd_l], "GND", 1.2),
        track([b1, (b1[0], y_gnd), gnd_r], "GND", 1.2),
    ]

    shapes = outline_shapes() + [j1, r4, r5, c2] + traces
    cx0, cy0 = mm(W_MM / 2, 12.0)
    doc = {
        "head": {
            "docType": "3",
            "editorVersion": "6.5.46",
            "c_para": {},
            "x": str(int(OX)),
            "y": str(int(OY)),
            "hasIdFlag": True,
            "newgId": True,
            "importFlag": 0,
        },
        "canvas": (
            f"CA~1000~1000~#000000~yes~#FFFFFF~10~1000~1000~line~0.5~mil~1~45~~0.5~"
            f"{cx0}~{cy0}~0~yes"
        ),
        "shape": shapes,
        "layers": layers(),
        "objects": objects(),
        "BBox": {"x": mm(0, 0)[0], "y": mm(0, 0)[1], "width": W, "height": H},
        "preference": {"hideFootprints": "", "hideNets": ""},
        "DRCRULE": {
            "Default": {
                "trackWidth": 1,
                "clearance": 0.6,
                "viaHoleDiameter": 2.4,
                "viaHoleD": 1.2,
            },
            "isRealtime": False,
            "isDrcOnRoutingOrPlaceVia": False,
            "checkObjectToCopperarea": True,
            "showDRCRangeLine": True,
        },
        "netColors": {},
    }
    dest = OUT / "08-PCB-USB-CC.json"
    dest.write_text(json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8")
    (OUT / "ICE-AKTAR-USB.txt").write_text(
        """EasyEDA Std - USB sarj adasi (cizgi CIZME)

Eski PCB-50x72 yi SILME. Sadece kenara al.

1. 08-PCB-USB-CC.json dosyasini ac, Ctrl+A, Ctrl+C (ilk { dahil).
2. EasyEDA: Dosya > Dosya Kaynagi...
3. Kutuyu sil, Ctrl+V.
4. Uygula DEGIL. "Yeni Belge Olustur".
5. + ile yakinlastir. Alt ortada USB + 2 direnc + 1 kondansator, kirmizi yollar HAZIR.

Cizgi cekme. Parca tasima. Kaydet: Dosya > Kaydet, ad: PCB-USB-CC.

Gormelisin: 50x72 cerceve, 4 vida, USB alt orta, A5/B5 altinda R4/R5.
""",
        encoding="utf-8",
    )
    print("OK", dest)


if __name__ == "__main__":
    main()
