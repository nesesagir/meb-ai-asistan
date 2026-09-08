import json
import math
from pathlib import Path

def parse_pcb(json_path):
    data = json.loads(Path(json_path).read_text(encoding='utf-8'))
    shapes = data['shape']
    
    pads = []
    tracks = []
    vias = []
    
    for s in shapes:
        parts = s.split('~')
        stype = parts[0]
        
        if stype == 'TRACK':
            width = float(parts[1])
            layer = parts[2]
            net = parts[3]
            coord_str = parts[4].split()
            pts = [(float(coord_str[i]), float(coord_str[i+1])) for i in range(0, len(coord_str), 2)]
            tracks.append({'width': width, 'layer': layer, 'net': net, 'pts': pts, 'id': parts[5]})
            
        elif stype == 'VIA':
            x, y = float(parts[1]), float(parts[2])
            d = float(parts[3])
            net = parts[4]
            hole_d = float(parts[5]) if len(parts) > 5 else 1.2
            vias.append({'x': x, 'y': y, 'd': d, 'hole_d': hole_d, 'net': net, 'id': parts[6] if len(parts)>6 else ''})
            
        elif stype == 'LIB':
            lib_parts = s.split('#@$')
            for lp in lib_parts[1:]:
                if lp.startswith('PAD~'):
                    pp = lp.split('~')
                    pshape = pp[1]
                    px, py = float(pp[2]), float(pp[3])
                    pw, ph = float(pp[4]), float(pp[5])
                    player = pp[6]
                    pnet = pp[7]
                    pnum = pp[8]
                    pads.append({'shape': pshape, 'x': px, 'y': py, 'w': pw, 'h': ph, 'layer': player, 'net': pnet, 'num': pnum})
                    
    return tracks, vias, pads

tracks, vias, pads = parse_pcb('09-PCB-TAM.json')
print(f"Loaded: {len(tracks)} tracks, {len(vias)} vias, {len(pads)} pads")

DRC_CLR = 0.6

def point_to_segment_dist(px, py, x1, y1, x2, y2):
    dx, dy = x2 - x1, y2 - y1
    if dx == 0 and dy == 0:
        return math.hypot(px - x1, py - y1)
    t = max(0, min(1, ((px - x1) * dx + (py - y1) * dy) / (dx * dx + dy * dy)))
    nx, ny = x1 + t * dx, y1 + t * dy
    return math.hypot(px - nx, py - ny)

errors = []

# Via vs Pad of different nets
for v in vias:
    for p in pads:
        if not p['net'] or v['net'] == p['net']:
            continue
        req = v['d']/2.0 + min(p['w'], p['h'])/2.0 + DRC_CLR
        d = math.hypot(v['x'] - p['x'], v['y'] - p['y'])
        if d < req:
            errors.append(f"Via-Pad clearance ({v['net']} via at {v['x']:.1f},{v['y']:.1f} vs pad {p['net']}): dist={d:.2f} < req={req:.2f}")

# Via vs Via of different nets
for i in range(len(vias)):
    v1 = vias[i]
    for j in range(i+1, len(vias)):
        v2 = vias[j]
        if v1['net'] == v2['net']:
            continue
        req = (v1['d'] + v2['d'])/2.0 + DRC_CLR
        d = math.hypot(v1['x'] - v2['x'], v1['y'] - v2['y'])
        if d < req:
            errors.append(f"Via-Via clearance ({v1['net']} vs {v2['net']}): dist={d:.2f} < req={req:.2f}")

print(f"Total Clearance Errors found: {len(errors)}")
for e in errors[:50]:
    print(" ", e)
