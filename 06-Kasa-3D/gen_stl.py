#!/usr/bin/env python3
"""ASCII STL: on_kapak.stl + arka_kapak.stl (mm). OpenSCAD gerekmez."""
from __future__ import annotations

import math
from pathlib import Path

OUT = Path(__file__).resolve().parent

W, L, T = 58.0, 90.0, 20.0
WALL, FRONT_T = 1.4, 5.0
BACK_T = T - FRONT_T
PCB_W, PCB_L = 50.0, 72.0
PCB_X, PCB_Y = (W - PCB_W) / 2, WALL
POST_H = 6.5
HOLES = [(4.0, 10.0), (46.0, 10.0), (4.0, 50.0), (46.0, 50.0)]
SCR = (PCB_X + (PCB_W - 50.4) / 2, PCB_Y + (PCB_L - 69.6) / 2, 50.4, 69.6)
WIN = (SCR[0] + (50.4 - 44.5) / 2, SCR[1] + (69.6 - 59.0) / 2, 44.5, 59.0)
USB = (PCB_X + 25.0 - 9.2 / 2, 9.2, 3.4, 4.2)
BAT = (PCB_X + (PCB_W - 35.0) / 2, PCB_Y + 13.0, 35.0, 34.0, 6.5)


def nrm(a, b, c):
    ux, uy, uz = b[0] - a[0], b[1] - a[1], b[2] - a[2]
    vx, vy, vz = c[0] - a[0], c[1] - a[1], c[2] - a[2]
    nx = uy * vz - uz * vy
    ny = uz * vx - ux * vz
    nz = ux * vy - uy * vx
    mag = math.sqrt(nx * nx + ny * ny + nz * nz) or 1.0
    return nx / mag, ny / mag, nz / mag


class Mesh:
    def __init__(self) -> None:
        self.f: list[tuple] = []

    def tri(self, a, b, c) -> None:
        self.f.append((a, b, c))

    def quad(self, a, b, c, d) -> None:
        self.tri(a, b, c)
        self.tri(a, c, d)

    def box(self, x, y, z, dx, dy, dz) -> None:
        x2, y2, z2 = x + dx, y + dy, z + dz
        p = [
            (x, y, z),
            (x2, y, z),
            (x2, y2, z),
            (x, y2, z),
            (x, y, z2),
            (x2, y, z2),
            (x2, y2, z2),
            (x, y2, z2),
        ]
        self.quad(p[0], p[3], p[2], p[1])
        self.quad(p[4], p[5], p[6], p[7])
        self.quad(p[0], p[1], p[5], p[4])
        self.quad(p[1], p[2], p[6], p[5])
        self.quad(p[2], p[3], p[7], p[6])
        self.quad(p[3], p[0], p[4], p[7])

    def tube(self, cx, cy, z0, h, r_out, r_in, n=16) -> None:
        z1 = z0 + h
        for i in range(n):
            a0 = 2 * math.pi * i / n
            a1 = 2 * math.pi * (i + 1) / n
            o0 = (cx + r_out * math.cos(a0), cy + r_out * math.sin(a0), z0)
            o1 = (cx + r_out * math.cos(a1), cy + r_out * math.sin(a1), z0)
            o2 = (cx + r_out * math.cos(a1), cy + r_out * math.sin(a1), z1)
            o3 = (cx + r_out * math.cos(a0), cy + r_out * math.sin(a0), z1)
            i0 = (cx + r_in * math.cos(a0), cy + r_in * math.sin(a0), z0)
            i1 = (cx + r_in * math.cos(a1), cy + r_in * math.sin(a1), z0)
            i2 = (cx + r_in * math.cos(a1), cy + r_in * math.sin(a1), z1)
            i3 = (cx + r_in * math.cos(a0), cy + r_in * math.sin(a0), z1)
            self.quad(o0, o1, o2, o3)
            self.quad(i1, i0, i3, i2)
            self.quad(o3, o2, i2, i3)
            self.quad(o1, o0, i0, i1)

    def write(self, path: Path) -> None:
        lines = ["solid kasa"]
        for a, b, c in self.f:
            nx, ny, nz = nrm(a, b, c)
            lines.append(f"  facet normal {nx:.6f} {ny:.6f} {nz:.6f}")
            lines.append("    outer loop")
            for p in (a, b, c):
                lines.append(f"      vertex {p[0]:.4f} {p[1]:.4f} {p[2]:.4f}")
            lines.append("    endloop")
            lines.append("  endfacet")
        lines.append("endsolid kasa")
        path.write_text("\n".join(lines), encoding="ascii")
        print("OK", path, "tris", len(self.f))


def front() -> Mesh:
    m = Mesh()
    x, y, ww, ll = WIN
    m.box(0, 0, 0, W, y, FRONT_T)
    m.box(0, y + ll, 0, W, L - (y + ll), FRONT_T)
    m.box(0, y, 0, x, ll, FRONT_T)
    m.box(x + ww, y, 0, W - (x + ww), ll, FRONT_T)
    sx, sy, sw, sl = SCR
    t = 1.0
    m.box(sx, sy, WALL, sw, t, 3.6)
    m.box(sx, sy + sl - t, WALL, sw, t, 3.6)
    m.box(sx, sy, WALL, t, sl, 3.6)
    m.box(sx + sw - t, sy, WALL, t, sl, 3.6)
    return m


def back() -> Mesh:
    m = Mesh()
    m.box(0, 0, 0, W, L, WALL)
    m.box(0, 0, 0, WALL, L, BACK_T)
    m.box(W - WALL, 0, 0, WALL, L, BACK_T)
    m.box(0, L - WALL, 0, W, WALL, BACK_T)
    ux, uw, uh, uz = USB
    m.box(0, 0, 0, ux, WALL, BACK_T)
    m.box(ux + uw, 0, 0, W - (ux + uw), WALL, BACK_T)
    m.box(ux, 0, 0, uw, WALL, uz)
    m.box(ux, 0, uz + uh, uw, WALL, BACK_T - (uz + uh))
    bx, by, bw, bl, bh = BAT
    t = 0.8
    m.box(bx - t, by - t, WALL, bw + 2 * t, t, bh)
    m.box(bx - t, by + bl, WALL, bw + 2 * t, t, bh)
    m.box(bx - t, by - t, WALL, t, bl + 2 * t, bh)
    m.box(bx + bw, by - t, WALL, t, bl + 2 * t, bh)
    for hx, hy in HOLES:
        m.tube(PCB_X + hx, PCB_Y + hy, WALL, POST_H, 2.2, 1.1)
    return m


def main() -> None:
    front().write(OUT / "on_kapak.stl")
    back().write(OUT / "arka_kapak.stl")


if __name__ == "__main__":
    main()
