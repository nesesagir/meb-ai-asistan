#!/usr/bin/env python3
"""Create simple arrow list with shortened power/GND nets."""

from __future__ import annotations

import re
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "easyeda" / "MEB-AI-Asistan-Altium.NET"
OUT = Path(__file__).resolve().parents[1] / "easyeda" / "Pin-Baglanti-TAM-KisaGuc.txt"

NAMES = {
    "U1": "ESP32",
    "U2": "AXP2101",
    "U3": "ES7210",
    "U4": "ES8311",
    "U5": "NS4150",
    "J1": "USB-C Konnektor",
    "J2": "LCD/Dokunmatik Konnektor",
    "MK1": "Mikrofon-1",
    "MK2": "Mikrofon-2",
    "L1": "1uH Bobin",
    "R1": "10k Direnc R1",
    "R2": "10k Direnc R2",
    "R3": "10k Direnc R3",
    "R4": "5.1k Direnc R4",
    "R5": "5.1k Direnc R5",
    "R6": "4.7k Direnc R6",
    "R7": "4.7k Direnc R7",
    "R8": "10k Direnc R8",
    "R9": "10k Direnc R9",
    "C1": "1uF Kondansator C1",
    "C2": "10uF Kondansator C2",
    "C3": "22uF Kondansator C3",
    "C4": "1uF Kondansator C4",
    "C5": "10uF Kondansator C5",
    "C6": "10uF Kondansator C6",
    "C7": "1uF Kondansator C7",
    "C8": "1uF Kondansator C8",
    "C9": "1uF Kondansator C9",
    "C10": "1uF Kondansator C10",
    "C11": "100nF Kondansator C11",
    "C12": "100nF Kondansator C12",
    "C13": "10uF Kondansator C13",
}

POWER_NETS = {
    "GND",
    "3V3",
    "5V",
    "VBUS",
    "VBAT",
    "SYS",
    "AUD_3V3",
    "MIC_3V3",
    "LCD_3V3",
    "CTP_3V3",
    "MICBIAS",
}


def sort_key(ref: str, pin: str) -> tuple[tuple[str, int], str]:
    m = re.match(r"([A-Z]+)(\d+)$", ref)
    if m:
        return ((m.group(1), int(m.group(2))), str(pin))
    return ((ref, 999), str(pin))


def pin_text(ref: str, pin: str) -> str:
    return f"{NAMES.get(ref, ref)} Pin {pin}"


def main() -> None:
    lines = SRC.read_text(encoding="utf-8").splitlines()
    nets: dict[str, list[tuple[str, str]]] = {}
    in_wire = False
    current = None
    for line in lines:
        s = line.strip()
        if s == "<<< Wire List >>>":
            in_wire = True
            continue
        if not in_wire or not s or s.startswith("NODE "):
            continue
        m = re.match(r"^\[(\d+)\]\s+(.+)$", s)
        if m:
            current = m.group(2)
            nets[current] = []
            continue
        parts = s.split()
        if len(parts) >= 2 and current:
            nets[current].append((parts[0], parts[1]))

    out_lines = []
    for net_name, pins in nets.items():
        uniq = []
        seen = set()
        for rp in pins:
            if rp in seen:
                continue
            seen.add(rp)
            uniq.append(rp)
        uniq.sort(key=lambda x: sort_key(x[0], x[1]))

        if net_name.startswith("NC__"):
            for ref, pin in uniq:
                out_lines.append(f"{pin_text(ref, pin)} -> NC (Baglanmayacak)")
            continue

        if net_name in POWER_NETS:
            for ref, pin in uniq:
                out_lines.append(f"{pin_text(ref, pin)} -> {net_name}")
            continue

        if len(uniq) == 1:
            ref, pin = uniq[0]
            out_lines.append(f"{pin_text(ref, pin)} -> {net_name} (Tek Uclu)")
            continue

        for ref, pin in uniq:
            others = ", ".join(pin_text(r, p) for r, p in uniq if not (r == ref and p == pin))
            out_lines.append(f"{pin_text(ref, pin)} -> {others}")

    out_lines.sort(
        key=lambda line: sort_key(
            line.split(" Pin ", 1)[0].split()[-1] if " Pin " in line else "ZZZ",
            line.split(" Pin ", 1)[1].split()[0] if " Pin " in line else "999",
        )
    )
    OUT.write_text("\n".join(out_lines), encoding="utf-8")
    print(f"WROTE {OUT}")
    print(f"LINES {len(out_lines)}")


if __name__ == "__main__":
    main()
