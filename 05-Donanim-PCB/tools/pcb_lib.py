#!/usr/bin/env python3
"""Shared EasyEDA Std PCB helpers (footprint place + tracks)."""
from __future__ import annotations

import json
import re
import ssl
import urllib.request
from pathlib import Path

U = 0.254
OX, OY = 4000.0, 3000.0
W_MM, H_MM = 50.0, 72.0
W, H = W_MM / U, H_MM / U

OUT = Path(__file__).resolve().parents[1] / "easyeda"
CACHE = Path(__file__).resolve().parent / "_cache"
OUT.mkdir(parents=True, exist_ok=True)
CACHE.mkdir(parents=True, exist_ok=True)

CTX = ssl.create_default_context()
_ID = 9000


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
    keep = (
        "package",
        "pre",
        "Contributor",
        "Supplier",
        "Supplier Part",
        "Manufacturer",
        "Manufacturer Part",
    )
    d = {k: ascii_val(v) for k, v in (c_para or {}).items() if k in keep}
    d["pre"] = ref
    d["Supplier"] = "LCSC"
    d["Supplier Part"] = lcsc
    return "`".join(f"{k}`{v}" for k, v in d.items())


def shift_pairs(text: str, fn) -> str:
    toks = text.replace(",", " ").split()
    out: list[str] = []
    i = 0
    while i < len(toks):
        try:
            x, y = fn(float(toks[i]), float(toks[i + 1]))
            out.append(f"{round(x, 4)} {round(y, 4)}")
            i += 2
        except (ValueError, IndexError):
            out.append(toks[i])
            i += 1
    return " ".join(out)


def shift_svg_path(path: str, fn) -> str:
    def repl(m: re.Match) -> str:
        cmd = m.group(1)
        x, y = fn(float(m.group(2)), float(m.group(3)))
        return f"{cmd} {round(x, 4)} {round(y, 4)}"

    return re.sub(r"([ML])\s+(-?\d+\.?\d*)\s+(-?\d+\.?\d*)", repl, path)


def apply_xy(s: str, fn, pin_nets: dict[str, str] | None = None) -> str | None:
    cmd = s.split("~", 1)[0]
    if cmd == "SVGNODE":
        return None
    if cmd == "PAD":
        p = s.split("~")
        x, y = fn(float(p[2]), float(p[3]))
        p[2], p[3] = str(round(x, 4)), str(round(y, 4))
        if len(p) > 10 and p[10]:
            p[10] = shift_pairs(p[10], fn)
        if len(p) > 13 and p[13] and " " in p[13]:
            p[13] = shift_pairs(p[13], fn)
        if p[-1] and "," in p[-1]:
            a, b = p[-1].split(",", 1)
            try:
                nx, ny = fn(float(a), float(b))
                p[-1] = f"{round(nx, 4)},{round(ny, 4)}"
            except ValueError:
                pass
        pin = p[8] if len(p) > 8 else ""
        if pin_nets is not None and pin in pin_nets:
            p[7] = pin_nets[pin]
        return "~".join(p)
    if cmd == "TRACK":
        p = s.split("~")
        if len(p) > 4:
            p[4] = shift_pairs(p[4], fn)
        return "~".join(p)
    if cmd in ("HOLE", "CIRCLE"):
        p = s.split("~")
        x, y = fn(float(p[1]), float(p[2]))
        p[1], p[2] = str(round(x, 4)), str(round(y, 4))
        return "~".join(p)
    if cmd == "SOLIDREGION":
        p = s.split("~")
        if len(p) > 3:
            p[3] = shift_svg_path(p[3], fn)
        return "~".join(p)
    if cmd == "ARC":
        p = s.split("~")
        if len(p) > 4:
            p[4] = shift_svg_path(p[4], fn)
        return "~".join(p)
    if cmd == "TEXT":
        p = s.split("~")
        if len(p) > 2:
            try:
                x, y = fn(float(p[1]), float(p[2]))
                p[1], p[2] = str(round(x, 4)), str(round(y, 4))
            except ValueError:
                pass
        return "~".join(p)
    return s


def rot_fn(rot: int):
    r = rot % 360

    def fn(x: float, y: float) -> tuple[float, float]:
        if r == 0:
            return x, y
        if r == 180:
            return -x, -y
        if r == 90:
            return -y, x
        if r == 270:
            return y, -x
        return x, y

    return fn


def parse_pads(shapes: list[str]) -> dict[str, list[tuple[float, float]]]:
    pads: dict[str, list[tuple[float, float]]] = {}
    for s in shapes:
        if not s.startswith("PAD~"):
            continue
        p = s.split("~")
        pads.setdefault(p[8], []).append((float(p[2]), float(p[3])))
    return pads


def place_lib(
    product: dict,
    ref: str,
    lcsc: str,
    tx: float,
    ty: float,
    pin_nets: dict[str, str] | None = None,
    rot: int = 0,
) -> tuple[str, dict[str, list[tuple[float, float]]]]:
    pkg = product["result"]["packageDetail"]
    ds = pkg["dataStr"]
    head = ds["head"]
    ox = float(head.get("x") or 0)
    oy = float(head.get("y") or 0)
    rfn = rot_fn(rot)

    def to_board(x: float, y: float) -> tuple[float, float]:
        rx, ry = rfn(x - ox, y - oy)
        return rx + tx, ry + ty

    inner: list[str] = []
    for raw in ds.get("shape") or []:
        if raw.startswith("SOLIDREGION~") or raw.startswith("SVGNODE~"):
            continue
        t = apply_xy(raw, to_board, pin_nets)
        if t:
            inner.append(uniquify(t))
    attr = c_para_str(head.get("c_para") or {}, ref, lcsc)
    prefix = (
        f"TEXT~{round(tx, 3)}~{round(ty - 8, 3)}~0~1.2~#FFFF00~3~~none~{ref}~{gid()}~0"
    )
    lib = (
        f"LIB~{round(tx, 3)}~{round(ty, 3)}~{attr}~~0~{gid()}~0"
        f"#@${prefix}#@$" + "#@$".join(inner)
    )
    return uniquify(lib), parse_pads(inner)


def first(pads: dict[str, list[tuple[float, float]]], num: str) -> tuple[float, float]:
    return pads[num][0]


def track(pts: list[tuple[float, float]], net: str, width: float, layer: str = "1") -> str:
    body = " ".join(f"{round(x, 3)} {round(y, 3)}" for x, y in pts)
    return f"TRACK~{width}~{layer}~{net}~{body}~{gid()}~0"


def via(x: float, y: float, net: str, diameter: float = 2.4, hole: float = 1.2) -> str:
    return f"VIA~{round(x, 3)}~{round(y, 3)}~{diameter}~{net}~{hole}~{gid()}~0"


def copper_area(layer: str, net: str, pts: list[tuple[float, float]], clearance: float = 0.8) -> str:
    body = " ".join(f"{round(x, 3)} {round(y, 3)}" for x, y in pts)
    return f"COPPERAREA~1~{layer}~{net}~{body}~{clearance}~solid~{gid()}~spoke~yes~[]"


def pads_from_lib(lib: str) -> list[dict]:
    out: list[dict] = []
    for part in lib.split("#@$"):
        if not part.startswith("PAD~"):
            continue
        p = part.split("~")
        if len(p) < 9:
            continue
        net = p[7]
        if not net:
            continue
        out.append(
            {
                "x": float(p[2]),
                "y": float(p[3]),
                "w": float(p[4]),
                "h": float(p[5]),
                "layer": p[6],
                "net": net,
                "num": p[8],
            }
        )
    return out


def gnd_pour_rect() -> list[tuple[float, float]]:
    """Board copper except antenna keep-out (top 15 mm)."""
    x0, y0 = mm(0.4, 0.4)
    x1, y1 = mm(W_MM - 0.4, H_MM - 15.0)
    return [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]


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
        "9~Ratlines~#6464FF~true~false~false~",
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


def pcb_doc(shapes: list[str]) -> dict:
    cx0, cy0 = mm(W_MM / 2, H_MM / 2)
    return {
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
                "trackWidth": 0.6,
                "clearance": 0.6,
                "viaHoleDiameter": 2.4,
                "viaHoleD": 1.2,
            },
            "isRealtime": False,
            "isDrcOnRoutingOrPlaceVia": False,
            "checkObjectToCopperarea": False,
            "checkObjectToBoardOutline": False,
            "showDRCRangeLine": True,
        },
        "netColors": {},
    }
