#!/usr/bin/env python3
"""Generate an Altium-style .NET netlist from EasyEDA PCB JSON."""

from __future__ import annotations

import json
import re
from pathlib import Path


SRC = Path(__file__).resolve().parents[1] / "easyeda" / "09-PCB-TAM.json"
OUT = Path(__file__).resolve().parents[1] / "easyeda" / "MEB-AI-Asistan-Altium.NET"


def parse_attrs(attr: str) -> dict[str, str]:
    parts = attr.split("`") if attr else []
    data: dict[str, str] = {}
    i = 0
    while i + 1 < len(parts):
        key = parts[i].strip()
        val = parts[i + 1].strip()
        if key:
            data[key] = val
        i += 2
    return data


def sort_ref_key(ref: str) -> tuple[str, int]:
    m = re.match(r"([A-Za-z]+)(\d+)$", ref)
    if m:
        return (m.group(1), int(m.group(2)))
    return (ref, 999999)


def main() -> None:
    obj = json.loads(SRC.read_text(encoding="utf-8"))
    shapes = obj.get("shape", [])

    components: dict[str, dict[str, str]] = {}
    nets: dict[str, list[tuple[str, str, str, str, str]]] = {}
    unconnected: list[tuple[str, str, str, str, str]] = []

    for shape in shapes:
        if not isinstance(shape, str) or not shape.startswith("LIB~"):
            continue
        chunks = shape.split("#@$")
        head = chunks[0].split("~")
        attrs = parse_attrs(head[3] if len(head) > 3 else "")
        ref = attrs.get("pre", "")
        if not ref:
            continue
        package = attrs.get("package", "NA")
        value = attrs.get("Supplier Part", "") or package
        components.setdefault(ref, {"value": value, "package": package})

        for chunk in chunks[1:]:
            if not chunk.startswith("PAD~"):
                continue
            fields = chunk.split("~")
            if len(fields) < 9:
                continue
            net = (fields[7] or "").strip()
            pin = (fields[8] or "").strip() or "?"
            pin_name = pin
            pin_type = "PASSIVE"
            row = (ref, pin, pin_name, pin_type, value)
            if net:
                nets.setdefault(net, []).append(row)
            else:
                unconnected.append(row)

    for net_name, rows in list(nets.items()):
        seen: set[tuple[str, str]] = set()
        uniq: list[tuple[str, str, str, str, str]] = []
        for row in rows:
            key = (row[0], row[1])
            if key in seen:
                continue
            seen.add(key)
            uniq.append(row)
        uniq.sort(key=lambda r: (sort_ref_key(r[0]), r[1]))
        nets[net_name] = uniq

    lines: list[str] = []
    lines.append("<<< Component List >>>")
    for ref, data in sorted(components.items(), key=lambda x: sort_ref_key(x[0])):
        lines.append(f"{data['value']} {ref} {data['package']}")

    lines.append("")
    lines.append("<<< Wire List >>>")
    lines.append("NODE REFERENCE PIN# PIN_NAME PIN_TYPE PART_VALUE")

    idx = 1
    for net_name in sorted(nets):
        lines.append(f"[{idx:05d}] {net_name}")
        for ref, pin, pin_name, pin_type, value in nets[net_name]:
            lines.append(f"{ref} {pin} {pin_name} {pin_type} {value}")
        lines.append("")
        idx += 1

    seen_nc: set[tuple[str, str]] = set()
    for ref, pin, pin_name, pin_type, value in unconnected:
        key = (ref, pin)
        if key in seen_nc:
            continue
        seen_nc.add(key)
        lines.append(f"[{idx:05d}] NC__{ref}__{pin}")
        lines.append(f"{ref} {pin} {pin_name} {pin_type} {value}")
        lines.append("")
        idx += 1

    OUT.write_text("\n".join(lines), encoding="utf-8")
    print(f"WROTE {OUT}")
    print(
        f"components={len(components)} nets={len(nets)} "
        f"unconnected_pins={len(seen_nc)} total_nodes={idx-1}"
    )


if __name__ == "__main__":
    main()
