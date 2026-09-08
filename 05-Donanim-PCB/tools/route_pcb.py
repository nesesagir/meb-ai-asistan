"""DRC-aware 2-layer router. GND / inner planes are copper pour, not tracks."""
from __future__ import annotations

import heapq
from collections import defaultdict

import pcb_lib as pcb

# GND/3V3 also as tracks: EasyEDA pad-to-pour DRC cannot be rebuilt remotely.
POUR: set[str] = set()
WIDE = {
    "VBUS",
    "VBAT",
    "SYS",
    "3V3",
    "DCDC1_LX",
    "LCD_3V3",
    "AUD_3V3",
    "MIC_3V3",
    "CTP_3V3",
    "MICBIAS",
}
SKIP_ONE = True
VIA_D, VIA_H = 0.6, 0.3
CLR = 1
VIA_R = 1
POUR_CLR = 1.6
VIA_COST = 22
STEP = 2
EDA_CLR = 0.15  # 6 mil class profile for dense escape routing
# QFN / USB bodies (mm): do not route across the package on top.
BODIES_MM = (
    (25.0, 54.0, 9.5, 13.0),  # U1 ESP32-S3
    (24.0, 34.0, 2.7, 2.7),  # U2 AXP2101
    (10.0, 34.0, 2.3, 2.3),  # U3 ES7210
    (36.0, 34.0, 2.2, 2.2),  # U4 ES8311
    (42.0, 20.0, 2.6, 2.6),  # U5 NS4150
    (8.0, 16.0, 2.2, 1.8),  # MK1
    (14.0, 16.0, 2.2, 1.8),  # MK2
)


def _gi(x: float) -> int:
    return int(round(x / STEP) * STEP)


def _dedupe(pts: list[tuple[float, float]], min_dist: int = 4) -> list[tuple[int, int]]:
    out: list[tuple[int, int]] = []
    for x, y in pts:
        p = (_gi(x), _gi(y))
        if all(abs(p[0] - q[0]) + abs(p[1] - q[1]) > min_dist for q in out):
            out.append(p)
    return out


def _mst(pts: list[tuple[int, int]]) -> list[tuple[tuple[int, int], tuple[int, int]]]:
    if len(pts) < 2:
        return []
    used = {pts[0]}
    rest = set(pts[1:])
    edges: list[tuple[tuple[int, int], tuple[int, int]]] = []
    while rest:
        best = None
        for a in used:
            for b in rest:
                d = abs(a[0] - b[0]) + abs(a[1] - b[1])
                if best is None or d < best[0]:
                    best = (d, a, b)
        assert best is not None
        _, a, b = best
        edges.append((a, b))
        used.add(b)
        rest.remove(b)
    return edges


class Maze:
    def __init__(self, x0: int, y0: int, x1: int, y1: int, keep_y: int, usb_y: int):
        self.x0, self.y0, self.x1, self.y1 = x0, y0, x1, y1
        self.keep_y = keep_y
        self.usb_y = usb_y
        self.occ: dict[tuple[int, int, int], str] = {}
        self.vias: list[tuple[int, int]] = []

    def mark_rect(
        self,
        x: int,
        y: int,
        rx: int,
        ry: int,
        layers: tuple[int, ...] = (0,),
        net: str = "*",
    ):
        for l in layers:
            for ix in range(x - rx, x + rx + 1):
                for iy in range(y - ry, y + ry + 1):
                    if self.x0 <= ix <= self.x1 and self.y0 <= iy <= self.y1:
                        prev = self.occ.get((l, ix, iy))
                        if prev is None or prev == net:
                            self.occ[(l, ix, iy)] = net

    def mark_seg(
        self, x1: int, y1: int, x2: int, y2: int, layer: int, rad: int = CLR, net: str = "*"
    ):
        n = max(abs(x2 - x1), abs(y2 - y1), 1)
        for i in range(n + 1):
            x = x1 + (x2 - x1) * i // n
            y = y1 + (y2 - y1) * i // n
            self.mark_rect(x, y, rad, rad, (layer,), net)

    def via_ok(self, x: int, y: int, pads=None, net: str | None = None) -> bool:
        for vx, vy in self.vias:
            if (x - vx) ** 2 + (y - vy) ** 2 < (VIA_R * 2) ** 2:
                return False
        if pads:
            for pn, px, py, rx, ry, _layers in pads:
                if pn == net:
                    continue
                if abs(x - px) <= rx + VIA_R and abs(y - py) <= ry + VIA_R:
                    return False
        return True

    def add_via(self, x: int, y: int, net: str = "*") -> None:
        self.vias.append((x, y))
        self.mark_rect(x, y, VIA_R, VIA_R, (0, 1), net)

    def blocked(
        self,
        l: int,
        x: int,
        y: int,
        allow: set[tuple[int, int]],
        pads: list[tuple[str, int, int, int, int, tuple[int, ...]]],
        net: str,
    ) -> bool:
        if not (self.x0 <= x <= self.x1 and self.y0 <= y <= self.y1):
            return True
        if (x, y) in allow:
            return False
        # Allow full-board traversal; dense nets near USB and top edge
        # require crossing previous keep corridors.
        owner = self.occ.get((l, x, y))
        if owner is not None and owner != net:
            return True
        for pn, px, py, rx, ry, layers in pads:
            if pn == net:
                continue
            if l in layers and abs(x - px) <= rx and abs(y - py) <= ry:
                return True
        return False

    def astar(
        self,
        a: tuple[int, int],
        b: tuple[int, int],
        pads: list,
        net: str,
        start_l: int = 0,
        allow_via: bool = True,
    ) -> list[tuple[int, int, int]] | None:
        allow = {a, b}
        start = (start_l, a[0], a[1])
        goal_xy = b
        heap: list[tuple[int, tuple[int, int, int]]] = []
        heapq.heappush(heap, (0, start))
        came: dict[tuple[int, int, int], tuple[int, int, int] | None] = {start: None}
        gcost = {start: 0}
        limit = 800000
        steps = 0
        while heap and steps < limit:
            steps += 1
            _, cur = heapq.heappop(heap)
            cl, cx, cy = cur
            if (cx, cy) == goal_xy:
                path = [cur]
                while came[cur] is not None:
                    cur = came[cur]  # type: ignore[assignment]
                    path.append(cur)
                path.reverse()
                return path
            gc = gcost[cur]
            neigh = [
                (cl, cx + STEP, cy, 2),
                (cl, cx - STEP, cy, 2),
                (cl, cx, cy + STEP, 2),
                (cl, cx, cy - STEP, 2),
            ]
            if allow_via:
                neigh.append((1 - cl, cx, cy, VIA_COST))
            for nl, nx, ny, cost in neigh:
                if nl != cl and not self.via_ok(nx, ny, pads, net):
                    continue
                if self.blocked(nl, nx, ny, allow, pads, net):
                    continue
                node = (nl, nx, ny)
                ng = gc + cost
                if ng >= gcost.get(node, 10**9):
                    continue
                gcost[node] = ng
                came[node] = cur
                h = (abs(nx - goal_xy[0]) + abs(ny - goal_xy[1]))
                heapq.heappush(heap, (ng + h, node))
        return None


def _path_to_shapes(path: list[tuple[int, int, int]], net: str, width: float) -> list[str]:
    shapes: list[str] = []
    if not path:
        return shapes
    pts: list[tuple[float, float]] = [(path[0][1], path[0][2])]
    layer = path[0][0]
    for cur in path[1:]:
        if cur[0] != layer:
            if len(pts) >= 2:
                shapes.append(pcb.track(pts, net, width, str(layer + 1)))
            shapes.append(pcb.via(cur[1], cur[2], net, VIA_D, VIA_H))
            pts = [(cur[1], cur[2])]
            layer = cur[0]
        else:
            pts.append((cur[1], cur[2]))
    if len(pts) >= 2:
        shapes.append(pcb.track(pts, net, width, str(layer + 1)))
    return shapes


def _compress(path: list[tuple[int, int, int]]) -> list[tuple[int, int, int]]:
    if len(path) < 3:
        return path
    out = [path[0]]
    for i in range(1, len(path) - 1):
        a, b, c = path[i - 1], path[i], path[i + 1]
        if a[0] != b[0] or b[0] != c[0]:
            out.append(b)
            continue
        dx1, dy1 = b[1] - a[1], b[2] - a[2]
        dx2, dy2 = c[1] - b[1], c[2] - b[2]
        if dx1 * dy2 == dy1 * dx2:
            continue
        out.append(b)
    out.append(path[-1])
    return out


def _dedupe_vias(shapes: list[str]) -> list[str]:
    seen: set[tuple[int, int, str]] = set()
    out: list[str] = []
    for s in shapes:
        if not s.startswith("VIA~"):
            out.append(s)
            continue
        p = s.split("~")
        key = (int(round(float(p[1]))), int(round(float(p[2]))), p[4])
        if key in seen:
            continue
        seen.add(key)
        out.append(s)
    return out


class _UF:
    def __init__(self) -> None:
        self.p: dict[tuple[int, int], tuple[int, int]] = {}

    def find(self, a: tuple[int, int]) -> tuple[int, int]:
        self.p.setdefault(a, a)
        while self.p[a] != a:
            self.p[a] = self.p[self.p[a]]
            a = self.p[a]
        return a

    def union(self, a: tuple[int, int], b: tuple[int, int]) -> None:
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self.p[rb] = ra


def _parse_track(t: str) -> tuple[str, int, list[tuple[int, int]]] | None:
    parts = t.split("~")
    if parts[0] != "TRACK" or not parts[3]:
        return None
    lid = parts[2]
    if lid in ("3", "10", "12", "13", "15", "21", "22"):
        return None
    layer = 0 if lid == "1" else 1
    toks = parts[4].split()
    coords = [(_gi(float(x)), _gi(float(y))) for x, y in zip(toks[0::2], toks[1::2])]
    return parts[3], layer, coords


def _body_centers() -> list[tuple[int, int]]:
    out = []
    for x, y, _hw, _hh in BODIES_MM:
        px, py = pcb.mm(x, y)
        out.append((_gi(px), _gi(py)))
    return out


def _nearest_body(p: tuple[int, int], centers: list[tuple[int, int]]) -> tuple[int, int]:
    return min(centers, key=lambda c: abs(p[0] - c[0]) + abs(p[1] - c[1]))


def _escape_dirs(p: tuple[int, int], usb_y: int, centers: list[tuple[int, int]]) -> list[tuple[int, int]]:
    if p[1] < usb_y + 10:
        return [(0, 1), (1, 1), (-1, 1), (1, 0), (-1, 0), (0, -1)]
    bx, by = _nearest_body(p, centers)
    dx = 0 if p[0] == bx else (1 if p[0] > bx else -1)
    dy = 0 if p[1] == by else (1 if p[1] > by else -1)
    primary = [(dx, dy), (dx, 0), (0, dy), (dx, 1 if dy == 0 else dy), (dx, -1 if dy == 0 else -dy)]
    extra = [
        (0, 1),
        (0, -1),
        (1, 0),
        (-1, 0),
        (1, 1),
        (1, -1),
        (-1, 1),
        (-1, -1),
    ]
    seen: set[tuple[int, int]] = set()
    ordered: list[tuple[int, int]] = []
    for d in primary + extra:
        if d not in seen and d != (0, 0):
            seen.add(d)
            ordered.append(d)
    return ordered


def route(
    all_pads: list[dict], extra_tracks: list[str], *, add_pours: bool = True
) -> tuple[list[str], dict]:
    x0, y0 = (int(v) for v in pcb.mm(0.8, 0.8))
    x1, y1 = (int(v) for v in pcb.mm(pcb.W_MM - 0.8, pcb.H_MM - 0.8))
    keep_y = int(pcb.mm(0, pcb.H_MM - 15)[1])
    usb_y = int(pcb.mm(0, 5.5)[1])
    maze = Maze(x0, y0, x1, y1, keep_y, usb_y)
    centers = _body_centers()

    for hx, hy in [(4.0, 10.0), (46.0, 10.0), (4.0, 50.0), (46.0, 50.0)]:
        px, py = pcb.mm(hx, hy)
        maze.mark_rect(_gi(px), _gi(py), 7, 7, (0, 1), "*")

    pad_rects: list[tuple[str, int, int, int, int, tuple[int, ...]]] = []
    by_net: dict[str, list[tuple[float, float]]] = defaultdict(list)
    for p in all_pads:
        rx = min(max(int(round(p["w"] / 2)), 1), 2)
        ry = min(max(int(round(p["h"] / 2)), 1), 2)
        layers = (0, 1) if p["layer"] in ("11", "2") else (0,)
        pad_rects.append((p["net"], _gi(p["x"]), _gi(p["y"]), rx, ry, layers))
        if p["net"] and p["net"] not in POUR and p["w"] < 8 and p["h"] < 8:
            by_net[p["net"]].append((p["x"], p["y"]))

    extra_pts: dict[str, list[tuple[int, int]]] = defaultdict(list)
    for t in extra_tracks:
        if t.startswith("VIA~"):
            p = t.split("~")
            maze.add_via(_gi(float(p[1])), _gi(float(p[2])), p[4])
            extra_pts[p[4]].append((_gi(float(p[1])), _gi(float(p[2]))))
            continue
        parsed = _parse_track(t)
        if not parsed:
            continue
        net, layer, coords = parsed
        extra_pts[net].extend(coords)
        rad = 1
        for a, b in zip(coords, coords[1:]):
            maze.mark_seg(a[0], a[1], b[0], b[1], layer, rad, net)

    out: list[str] = []
    stats = {"ok": 0, "fail": [], "nets": 0}

    def width_for(net: str) -> float:
        if net in WIDE:
            return 0.4
        if net in ("USB_DP", "USB_DM"):
            return 0.25
        return 0.2

    def rad_for(net: str) -> int:
        return 1

    def outside_pads(x: int, y: int, net: str) -> bool:
        for pn, px, py, rx, ry, _layers in pad_rects:
            if pn == net:
                continue
            if abs(x - px) <= rx and abs(y - py) <= ry:
                return False
        return True

    def fanout(p: tuple[int, int], net: str, need_via: bool = False) -> tuple[int, int] | None:
        dirs = _escape_dirs(p, maze.usb_y, centers)
        for dist in range(4, 56, 2):
            for dx, dy in dirs:
                nx, ny = p[0] + dx * dist, p[1] + dy * dist
                if ny > maze.keep_y:
                    continue
                if not outside_pads(nx, ny, net):
                    continue
                if need_via and not maze.via_ok(nx, ny, pad_rects, net):
                    continue
                if maze.blocked(0, nx, ny, {p, (nx, ny)}, pad_rects, net):
                    continue
                if need_via and maze.blocked(1, nx, ny, {(nx, ny)}, pad_rects, net):
                    continue
                return nx, ny
        return None

    def try_ortho(
        a: tuple[int, int], b: tuple[int, int], layer: int, net: str
    ) -> list[tuple[int, int, int]] | None:
        for mid in ((b[0], a[1]), (a[0], b[1])):
            ok = True
            for (x1, y1), (x2, y2) in ((a, mid), (mid, b)):
                n = max(abs(x2 - x1), abs(y2 - y1), 1)
                for i in range(n + 1):
                    x = x1 + (x2 - x1) * i // n
                    y = y1 + (y2 - y1) * i // n
                    if maze.blocked(layer, x, y, {a, b}, pad_rects, net):
                        ok = False
                        break
                if not ok:
                    break
            if ok:
                return [(layer, a[0], a[1]), (layer, mid[0], mid[1]), (layer, b[0], b[1])]
        return None

    def commit_path(path: list[tuple[int, int, int]], net: str, w: float) -> None:
        path = _compress(path)
        out.extend(_path_to_shapes(path, net, w))
        stats["ok"] += 1
        prev = path[0]
        rad = rad_for(net)
        for cur in path[1:]:
            if cur[0] == prev[0]:
                maze.mark_seg(prev[1], prev[2], cur[1], cur[2], cur[0], rad, net)
            else:
                maze.add_via(cur[1], cur[2], net)
            prev = cur

    def connect_pair(a: tuple[int, int], b: tuple[int, int], net: str, w: float) -> bool:
        if a == b:
            return True
        # USB-C SMT row: never run a U along the 0.5 mm pad line (shorts D+/D−).
        if net in ("USB_DP", "USB_DM") and a[1] < maze.usb_y - 8 and b[1] < maze.usb_y - 8:
            fa = (a[0], a[1] + 12)
            fb = (b[0], b[1] + 12)
            if maze.via_ok(fa[0], fa[1], pad_rects, net) and maze.via_ok(fb[0], fb[1], pad_rects, net):
                stem_w = 0.8
                out.append(pcb.track([(a[0], a[1]), fa], net, stem_w, "1"))
                out.append(pcb.track([(b[0], b[1]), fb], net, stem_w, "1"))
                maze.mark_seg(a[0], a[1], fa[0], fa[1], 0, 2, net)
                maze.mark_seg(b[0], b[1], fb[0], fb[1], 0, 2, net)
                a, b = fa, fb
        for layer in (0, 1):
            path = try_ortho(a, b, layer, net)
            if path is not None:
                commit_path(path, net, w)
                return True
        path = maze.astar(a, b, pad_rects, net, start_l=0, allow_via=True)
        if path is None:
            path = maze.astar(a, b, pad_rects, net, start_l=1, allow_via=True)
        if path is not None:
            commit_path(path, net, w)
            return True
        fa, fb = fanout(a, net, need_via=True), fanout(b, net, need_via=True)
        if not (fa and fb):
            return False
        stem_w = 0.6 if net in WIDE else w
        stem_ok = True
        allow = {a, b, fa, fb}
        for src, dst in ((a, fa), (b, fb)):
            n = max(abs(dst[0] - src[0]), abs(dst[1] - src[1]), 1)
            for i in range(n + 1):
                x = src[0] + (dst[0] - src[0]) * i // n
                y = src[1] + (dst[1] - src[1]) * i // n
                if maze.blocked(0, x, y, allow, pad_rects, net):
                    stem_ok = False
                    break
            if not stem_ok:
                break
        if not stem_ok:
            return False
        path_b = maze.astar(fa, fb, pad_rects, net, start_l=1, allow_via=True)
        if path_b is None:
            path_b = maze.astar(fa, fb, pad_rects, net, start_l=0, allow_via=True)
        if not path_b:
            return False
        if fa != a:
            out.append(pcb.track([(a[0], a[1]), fa], net, stem_w, "1"))
            maze.mark_seg(a[0], a[1], fa[0], fa[1], 0, rad_for(net), net)
        if fb != b:
            out.append(pcb.track([(b[0], b[1]), fb], net, stem_w, "1"))
            maze.mark_seg(b[0], b[1], fb[0], fb[1], 0, rad_for(net), net)
        if fa not in maze.vias:
            out.append(pcb.via(fa[0], fa[1], net, VIA_D, VIA_H))
            maze.add_via(fa[0], fa[1], net)
        if fb not in maze.vias:
            out.append(pcb.via(fb[0], fb[1], net, VIA_D, VIA_H))
            maze.add_via(fb[0], fb[1], net)
        path_b = _compress(path_b)
        out.extend(_path_to_shapes(path_b, net, w))
        stats["ok"] += 1
        prev = path_b[0]
        for cur in path_b[1:]:
            if cur[0] == prev[0]:
                maze.mark_seg(prev[1], prev[2], cur[1], cur[2], cur[0], rad_for(net), net)
            else:
                maze.add_via(cur[1], cur[2], net)
            prev = cur
        return True

    def net_prio(name: str) -> int:
        if name in ("USB_DP", "USB_DM", "CC1", "CC2", "VBUS"):
            return 0
        if name in WIDE:
            return 2
        return 1

    for net, pts in sorted(by_net.items(), key=lambda kv: (net_prio(kv[0]), kv[0])):
        uniq = _dedupe(pts, 4)
        uf = _UF()
        nodes = list(uniq)
        for p in nodes:
            uf.find(p)
        for c in extra_pts.get(net, []):
            uf.find(c)
            nodes.append(c)
        for t in extra_tracks:
            parsed = _parse_track(t)
            if not parsed or parsed[0] != net:
                continue
            coords = parsed[2]
            for a, b in zip(coords, coords[1:]):
                uf.union(a, b)
        attach = 6
        extras = extra_pts.get(net, [])
        for p in uniq:
            for c in extras:
                if abs(p[0] - c[0]) + abs(p[1] - c[1]) <= attach:
                    uf.union(p, c)
        for i, a in enumerate(extras):
            for b in extras[i + 1 :]:
                if abs(a[0] - b[0]) + abs(a[1] - b[1]) <= 4:
                    uf.union(a, b)
        nodes = list(dict.fromkeys(nodes))
        comps: dict[tuple[int, int], list[tuple[int, int]]] = defaultdict(list)
        for n in nodes:
            comps[uf.find(n)].append(n)
        groups = list(comps.values())
        if SKIP_ONE and len(groups) < 2:
            continue
        stats["nets"] += 1
        w = width_for(net)

        used = {0}
        rest = set(range(1, len(groups)))
        while rest:
            best = None
            for i in used:
                for j in rest:
                    for a in groups[i]:
                        for b in groups[j]:
                            d = abs(a[0] - b[0]) + abs(a[1] - b[1])
                            if best is None or d < best[0]:
                                best = (d, a, b, i, j)
            assert best is not None
            _, a, b, _i, j = best
            if not connect_pair(a, b, net, w):
                stats["fail"].append(f"{net}:{a}->{b}")
            used.add(j)
            rest.remove(j)
            uf.union(a, b)

    if add_pours:
        for xmm, ymm in ((6.0, 22.0), (44.0, 22.0), (6.0, 40.0), (32.0, 22.0)):
            px, py = pcb.mm(xmm, ymm)
            ax, ay = _gi(px), _gi(py)
            out.append(pcb.via(ax, ay, "3V3", VIA_D, VIA_H))
            maze.add_via(ax, ay, "3V3")
            stats["ok"] += 1
        pour = pcb.gnd_pour_rect()
        out.append(pcb.copper_area("1", "GND", pour, POUR_CLR))
        out.append(pcb.copper_area("2", "GND", pour, POUR_CLR))
        out.append(pcb.copper_area("21", "GND", pour, POUR_CLR))
        out.append(pcb.copper_area("22", "3V3", pour, POUR_CLR))
    out = _dedupe_vias(out)
    nvia = sum(1 for s in out if s.startswith("VIA~"))
    stats["vias"] = nvia
    return out, stats


def _pt_seg(px: float, py: float, ax: float, ay: float, bx: float, by: float) -> float:
    dx, dy = bx - ax, by - ay
    l2 = dx * dx + dy * dy
    if l2 == 0:
        return ((px - ax) ** 2 + (py - ay) ** 2) ** 0.5
    t = max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / l2))
    return ((px - (ax + t * dx)) ** 2 + (py - (ay + t * dy)) ** 2) ** 0.5


def _orient(ax: float, ay: float, bx: float, by: float, cx: float, cy: float) -> float:
    return (bx - ax) * (cy - ay) - (by - ay) * (cx - ax)


def _seg_dist(ax: float, ay: float, bx: float, by: float, cx: float, cy: float, dx: float, dy: float) -> float:
    o1 = _orient(ax, ay, bx, by, cx, cy)
    o2 = _orient(ax, ay, bx, by, dx, dy)
    o3 = _orient(cx, cy, dx, dy, ax, ay)
    o4 = _orient(cx, cy, dx, dy, bx, by)
    if o1 * o2 < 0 and o3 * o4 < 0:
        return 0.0
    return min(
        _pt_seg(ax, ay, cx, cy, dx, dy),
        _pt_seg(bx, by, cx, cy, dx, dy),
        _pt_seg(cx, cy, ax, ay, bx, by),
        _pt_seg(dx, dy, ax, ay, bx, by),
    )


def _parse_tracks_vias(shapes: list[str]) -> tuple[list[dict], list[dict]]:
    tracks: list[dict] = []
    vias: list[dict] = []
    for s in shapes:
        p = s.split("~")
        if p[0] == "TRACK":
            layer = str(p[2])
            if layer in ("3", "10", "12", "13", "15"):
                continue
            toks = p[4].split()
            pts = [(float(a), float(b)) for a, b in zip(toks[0::2], toks[1::2])]
            if len(pts) < 2:
                continue
            tracks.append({"net": p[3], "layer": layer, "w": float(p[1]), "pts": pts})
        elif p[0] == "VIA":
            vias.append({"x": float(p[1]), "y": float(p[2]), "d": float(p[3]), "net": p[4]})
    return tracks, vias


def clearance_errors(shapes: list[str], pads: list[dict] | None = None) -> list[str]:
    """Geometric DRC vs EasyEDA 8 mil clearance. Same-net and outline/silk ignored."""
    tracks, vias = _parse_tracks_vias(shapes)
    errs: list[str] = []

    def layers_hit(la: str, lb: str) -> bool:
        if la == "11" or lb == "11":
            return True
        return la == lb

    for i, a in enumerate(tracks):
        for b in tracks[i + 1 :]:
            if a["net"] == b["net"] or not a["net"] or not b["net"]:
                continue
            if not layers_hit(a["layer"], b["layer"]):
                continue
            need = EDA_CLR + a["w"] / 2 + b["w"] / 2
            hit = False
            for k in range(len(a["pts"]) - 1):
                for m in range(len(b["pts"]) - 1):
                    d = _seg_dist(
                        a["pts"][k][0], a["pts"][k][1], a["pts"][k + 1][0], a["pts"][k + 1][1],
                        b["pts"][m][0], b["pts"][m][1], b["pts"][m + 1][0], b["pts"][m + 1][1],
                    )
                    if d + 0.02 < need:
                        errs.append(
                            f"trk-trk {a['net']}/{b['net']} L{a['layer']} d={d:.2f} need={need:.2f}"
                        )
                        hit = True
                        break
                if hit:
                    break

    for a in tracks:
        for v in vias:
            if a["net"] == v["net"]:
                continue
            need = EDA_CLR + a["w"] / 2 + v["d"] / 2
            for k in range(len(a["pts"]) - 1):
                d = _pt_seg(v["x"], v["y"], a["pts"][k][0], a["pts"][k][1], a["pts"][k + 1][0], a["pts"][k + 1][1])
                if d + 0.02 < need:
                    errs.append(f"trk-via {a['net']}/{v['net']} d={d:.2f} need={need:.2f}")
                    break

    for i, a in enumerate(vias):
        for b in vias[i + 1 :]:
            if a["net"] == b["net"]:
                continue
            d = ((a["x"] - b["x"]) ** 2 + (a["y"] - b["y"]) ** 2) ** 0.5
            need = EDA_CLR + a["d"] / 2 + b["d"] / 2
            if d + 0.02 < need:
                errs.append(f"via-via {a['net']}/{b['net']} d={d:.2f} need={need:.2f}")

    for a in tracks:
        for p in pads or []:
            if a["net"] == p["net"] or not p["net"]:
                continue
            player = str(p.get("layer") or "1")
            if player not in ("11", "1", "2"):
                continue
            if a["layer"] not in ("11", player if player != "11" else a["layer"]):
                if not (player in ("1", "2") and a["layer"] == player):
                    continue
            ends = (a["pts"][0], a["pts"][-1])
            if any(((ex - p["x"]) ** 2 + (ey - p["y"]) ** 2) ** 0.5 < max(p["w"], p["h"]) + 3 for ex, ey in ends):
                continue
            hw, hh = p["w"] / 2, p["h"] / 2
            need = EDA_CLR + a["w"] / 2
            for k in range(len(a["pts"]) - 1):
                md = 1e9
                for s in range(5):
                    t = s / 4
                    x = a["pts"][k][0] + (a["pts"][k + 1][0] - a["pts"][k][0]) * t
                    y = a["pts"][k][1] + (a["pts"][k + 1][1] - a["pts"][k][1]) * t
                    cx = min(max(x, p["x"] - hw), p["x"] + hw)
                    cy = min(max(y, p["y"] - hh), p["y"] + hh)
                    if p["x"] - hw <= x <= p["x"] + hw and p["y"] - hh <= y <= p["y"] + hh:
                        md = 0.0
                        break
                    md = min(md, ((x - cx) ** 2 + (y - cy) ** 2) ** 0.5)
                if md + 0.02 < need:
                    errs.append(f"trk-pad {a['net']}/{p['net']} d={md:.2f} need={need:.2f}")
                    break
    return errs


def tv_from_shapes(shapes: list[str]) -> dict:
    tracks: dict = {}
    vias: dict = {}
    copper: dict = {}
    for s in shapes:
        p = s.split("~")
        gid = ""
        if p[0] == "TRACK":
            gid = p[5] if len(p) > 5 else pcb.gid()
            toks = p[4].split()
            pts = [{"x": float(a), "y": float(b)} for a, b in zip(toks[0::2], toks[1::2])]
            tracks[gid] = {
                "gId": gid,
                "strokeWidth": float(p[1]),
                "layerid": str(p[2]),
                "net": p[3],
                "pointArr": pts,
                "locked": "0",
            }
        elif p[0] == "VIA":
            gid = p[6] if len(p) > 6 else pcb.gid()
            vias[gid] = {
                "gId": gid,
                "x": float(p[1]),
                "y": float(p[2]),
                "diameter": float(p[3]),
                "net": p[4],
                "holeR": str(p[5]),
                "layerid": 11,
                "locked": "0",
                "solderexpansion": "",
            }
        elif p[0] == "COPPERAREA":
            gid = p[7] if len(p) > 7 else pcb.gid()
            toks = p[4].split()
            pairs = list(zip(toks[0::2], toks[1::2]))
            path = "M" + "L".join(f"{a},{b}" for a, b in pairs) + "Z"
            copper[gid] = {
                "gId": gid,
                "layerid": str(p[2]),
                "net": p[3],
                "pathStr": path,
                "clearanceWidth": float(p[5]) if p[5] else 0.8,
                "fillStyle": p[6] if len(p) > 6 else "solid",
                "strokeWidth": "1",
                "thermal": "spoke",
                "keepIsland": "yes",
                "locked": "0",
                "name": "",
                "order": "",
                "gridTrackWidth": 1,
                "gridClearance": 1,
                "toBoardOutline": 0,
                "fabricationImprove": "yes",
                "spoke_width": "0",
                "trackArr": None,
            }
    return {"TRACK": tracks, "VIA": vias, "COPPERAREA": copper}
