#!/usr/bin/env python3
"""EasyEDA Std PCB: 50x72 mm outline, Type-C, M2 holes, antenna keep-out."""
from __future__ import annotations

import json
from pathlib import Path

OUT = Path(__file__).resolve().parents[1] / "easyeda"
OUT.mkdir(parents=True, exist_ok=True)

# EasyEDA Std PCB unit = 10 mil = 0.254 mm
U = 0.254
OX, OY = 4000.0, 3000.0  # board bottom-left
W_MM, H_MM = 50.0, 72.0
W, H = W_MM / U, H_MM / U  # 196.850, 283.465

_ID = 2000


def gid() -> str:
    global _ID
    _ID += 1
    return f"gge{_ID}"


def mm(x: float, y: float) -> tuple[float, float]:
    return round(OX + x / U, 3), round(OY + y / U, 3)


def main() -> None:
    x0, y0 = mm(0, 0)
    x1, y1 = mm(W_MM, H_MM)
    shapes = []

    # Board outline (layer 10)
    pts = f"{x0} {y0} {x1} {y0} {x1} {y1} {x0} {y1} {x0} {y0}"
    shapes.append(f"TRACK~0.2~10~~{pts}~{gid()}~0")

    # Antenna keep-out: top 15 mm, silk
    kx0, ky0 = mm(0, H_MM - 15)
    kx1, ky1 = mm(W_MM, H_MM)
    shapes.append(
        f"TRACK~0.15~3~~{kx0} {ky0} {kx1} {ky0} {kx1} {ky1} {kx0} {ky1} {kx0} {ky0}~{gid()}~0"
    )

    # Type-C marker: bottom center, 9 x 7 mm tongue on edge
    cx, cy = mm(25.0, 0.0)
    tw, td = 9.0 / U, 7.0 / U
    tx0, ty0 = round(cx - tw / 2, 3), y0
    tx1, ty1 = round(cx + tw / 2, 3), round(y0 + td, 3)
    shapes.append(
        f"TRACK~0.15~3~~{tx0} {ty0} {tx1} {ty0} {tx1} {ty1} {tx0} {ty1} {tx0} {ty0}~{gid()}~0"
    )

    # M2 NPTH 2.2 mm
    hole_d = round(2.2 / U, 3)
    holes_mm = [(4.0, 10.0), (46.0, 10.0), (4.0, 50.0), (46.0, 50.0)]
    for hx, hy in holes_mm:
        px, py = mm(hx, hy)
        shapes.append(f"HOLE~{px}~{py}~{hole_d}~{gid()}~0")
        # CIRCLE: cx cy r strokeWidth layer
        shapes.append(f"CIRCLE~{px}~{py}~{round(1.6 / U, 3)}~0.2~3~{gid()}~0~~")

    layers = [
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
    objects = [
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
    cx0, cy0 = mm(W_MM / 2, H_MM / 2)
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
        "layers": layers,
        "objects": objects,
        "BBox": {"x": x0, "y": y0, "width": W, "height": H},
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
    (OUT / "07-PCB-OUTLINE.json").write_text(
        json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    notes = f"""MEB AI Asistan PCB — kilitli mekanik

Kart: {W_MM:.0f} x {H_MM:.0f} x 1.6 mm, 4 katman
Orijin: sol-alt kosesi (Type-C kenari = alt)

Type-C: alt orta, X=25.0 mm, Y=0 (konnektor disari)
ESP32 anten: ust kenar, 15 mm keep-out (metal/batarya yok)

M2 vida (NPTH 2.2 mm), sol-alt orijine gore:
  H1  4.0, 10.0
  H2 46.0, 10.0
  H3  4.0, 50.0
  H4 46.0, 50.0

Kasa hedef: 58 x 90 x 20 mm. Batarya 35 x 34 x 6.5 mm, arka yuz.
"""
    (OUT / "PCB-OLCULER.txt").write_text(notes, encoding="utf-8")
    print("OK", OUT / "07-PCB-OUTLINE.json")


if __name__ == "__main__":
    main()
