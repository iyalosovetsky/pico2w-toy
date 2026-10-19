"""SVG drawn elsewhere (Inkscape, a CAD export) -> the shape editor's figures, in millimetres with y up.

Circles, ellipses and rectangles stay what they are while their transforms only move and scale them
evenly; anything else - paths (M L H V C S Q T A Z), polylines, polygons, rotated or skewed figures -
becomes a "poly" (a polyline, closed or open), its curves cut into chords about 0.3 mm long.
The size: the width / height units (mm, cm, in, pt, px = 1/96 in) over the viewBox.
"""
import math
import re
import xml.etree.ElementTree as ET

NS = "{http://www.w3.org/2000/svg}"
UNITS = {"mm": 1.0, "cm": 10.0, "in": 25.4, "pt": 25.4 / 72, "pc": 25.4 / 6, "px": 25.4 / 96, "": 25.4 / 96}
CHORD_MM = 0.3
SKIP = {"defs", "clipPath", "mask", "symbol", "marker", "pattern", "text", "title", "desc", "metadata", "style",
        "image", "linearGradient", "radialGradient", "filter"}
NUM = r"[-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?"


def length_mm(s, default=None):
    m = re.fullmatch(r"\s*(" + NUM + r")\s*([a-z%]*)\s*", s or "")
    if not m or m.group(2) == "%":
        return default
    return float(m.group(1)) * UNITS.get(m.group(2), UNITS["px"])


# ---------------------------------------------------------------- transforms (a b c d e f)

def mul(m, n):
    a, b, c, d, e, f = m
    a2, b2, c2, d2, e2, f2 = n
    return (a * a2 + c * b2, b * a2 + d * b2, a * c2 + c * d2, b * c2 + d * d2, a * e2 + c * f2 + e, b * e2 + d * f2 + f)


def parse_transform(s):
    m = (1.0, 0.0, 0.0, 1.0, 0.0, 0.0)
    for name, args in re.findall(r"(\w+)\s*\(([^)]*)\)", s or ""):
        v = [float(x) for x in re.findall(NUM, args)]
        if name == "matrix" and len(v) == 6:
            t = tuple(v)
        elif name == "translate":
            t = (1, 0, 0, 1, v[0] if v else 0, v[1] if len(v) > 1 else 0)
        elif name == "scale":
            sx = v[0] if v else 1
            t = (sx, 0, 0, v[1] if len(v) > 1 else sx, 0, 0)
        elif name == "rotate":
            a = math.radians(v[0] if v else 0)
            t = (math.cos(a), math.sin(a), -math.sin(a), math.cos(a), 0, 0)
            if len(v) == 3:
                t = mul(mul((1, 0, 0, 1, v[1], v[2]), t), (1, 0, 0, 1, -v[1], -v[2]))
        elif name == "skewX":
            t = (1, 0, math.tan(math.radians(v[0])), 1, 0, 0)
        elif name == "skewY":
            t = (1, math.tan(math.radians(v[0])), 0, 1, 0, 0)
        else:
            continue
        m = mul(m, t)
    return m


def apply(m, p):
    a, b, c, d, e, f = m
    return (a * p[0] + c * p[1] + e, b * p[0] + d * p[1] + f)


def plain(m):
    """True for a move + an even scale (no rotation, skew or mirror within the drawing)."""
    a, b, c, d, e, f = m
    return abs(b) < 1e-9 and abs(c) < 1e-9 and abs(abs(a) - abs(d)) < 1e-9 * max(1, abs(a))


# ---------------------------------------------------------------- path data

def flatten_path(d, scale):
    """[(points, closed)] for each subpath of an SVG path, curves as chords (scale: mm per unit)."""
    toks = re.findall(r"[MmLlHhVvCcSsQqTtAaZz]|" + NUM, d or "")
    out, pts = [], []
    cur, start, last_c, last_q = (0.0, 0.0), (0.0, 0.0), None, None
    cmd, i = None, 0

    def nums(k):
        nonlocal i
        v = [float(x) for x in toks[i:i + k]]
        i += k
        return v

    def segs(length):
        return max(2, min(200, int(math.ceil(length * scale / CHORD_MM))))

    def finish(closed=False):
        nonlocal pts
        if len(pts) > 1:
            out.append((pts, closed))
        pts = []

    while i < len(toks):
        if re.fullmatch(r"[A-Za-z]", toks[i]):
            cmd = toks[i]
            i += 1
            if cmd in "Zz":
                if pts:
                    if pts[-1] != start:
                        pts.append(start)
                    finish(True)
                cur, last_c, last_q = start, None, None
                continue
        if cmd is None:
            break
        rel = cmd.islower()
        c = cmd.upper()
        ox, oy = cur if rel else (0.0, 0.0)
        if c == "M":
            x, y = nums(2)
            finish()
            cur = start = (ox + x, oy + y)
            pts = [cur]
            cmd = "l" if rel else "L"                 # more pairs after M are lines
            last_c = last_q = None
            continue
        if not pts:
            pts = [cur]
        if c in "LHV":
            if c == "L":
                x, y = nums(2)
                p = (ox + x, oy + y)
            elif c == "H":
                p = ((ox if rel else 0) + nums(1)[0], cur[1])
            else:
                p = (cur[0], (oy if rel else 0) + nums(1)[0])
            pts.append(p)
            cur, last_c, last_q = p, None, None
        elif c in "CS":
            if c == "C":
                x1, y1, x2, y2, x, y = nums(6)
                p1 = (ox + x1, oy + y1)
            else:
                x2, y2, x, y = nums(4)
                p1 = (2 * cur[0] - last_c[0], 2 * cur[1] - last_c[1]) if last_c else cur
            p2, p3 = (ox + x2, oy + y2), (ox + x, oy + y)
            n = segs(math.dist(cur, p1) + math.dist(p1, p2) + math.dist(p2, p3))
            for k in range(1, n + 1):
                t = k / n
                u = 1 - t
                pts.append((u ** 3 * cur[0] + 3 * u * u * t * p1[0] + 3 * u * t * t * p2[0] + t ** 3 * p3[0],
                            u ** 3 * cur[1] + 3 * u * u * t * p1[1] + 3 * u * t * t * p2[1] + t ** 3 * p3[1]))
            cur, last_c, last_q = p3, p2, None
        elif c in "QT":
            if c == "Q":
                x1, y1, x, y = nums(4)
                p1 = (ox + x1, oy + y1)
            else:
                x, y = nums(2)
                p1 = (2 * cur[0] - last_q[0], 2 * cur[1] - last_q[1]) if last_q else cur
            p2 = (ox + x, oy + y)
            n = segs(math.dist(cur, p1) + math.dist(p1, p2))
            for k in range(1, n + 1):
                t = k / n
                u = 1 - t
                pts.append((u * u * cur[0] + 2 * u * t * p1[0] + t * t * p2[0],
                            u * u * cur[1] + 2 * u * t * p1[1] + t * t * p2[1]))
            cur, last_q, last_c = p2, p1, None
        elif c == "A":
            rx, ry, rot, large, sweep, x, y = nums(7)
            p = (ox + x, oy + y)
            pts += arc_points(cur, p, abs(rx), abs(ry), rot, int(large), int(sweep), segs)
            cur, last_c, last_q = p, None, None
        else:
            i += 1                                   # something unknown: skip a number
    finish()
    return out


def arc_points(p0, p1, rx, ry, rot, large, sweep, segs):
    """An SVG elliptical arc (endpoint form, SVG spec F.6.5) as points after p0."""
    if rx == 0 or ry == 0 or p0 == p1:
        return [p1]
    phi = math.radians(rot)
    cp, sp = math.cos(phi), math.sin(phi)
    dx, dy = (p0[0] - p1[0]) / 2, (p0[1] - p1[1]) / 2
    x1 = cp * dx + sp * dy
    y1 = -sp * dx + cp * dy
    lam = x1 * x1 / (rx * rx) + y1 * y1 / (ry * ry)
    if lam > 1:
        rx, ry = rx * math.sqrt(lam), ry * math.sqrt(lam)
    num = rx * rx * ry * ry - rx * rx * y1 * y1 - ry * ry * x1 * x1
    den = rx * rx * y1 * y1 + ry * ry * x1 * x1
    co = math.sqrt(max(0.0, num / den)) if den else 0.0
    if large == sweep:
        co = -co
    cx1, cy1 = co * rx * y1 / ry, -co * ry * x1 / rx
    cx = cp * cx1 - sp * cy1 + (p0[0] + p1[0]) / 2
    cy = sp * cx1 + cp * cy1 + (p0[1] + p1[1]) / 2

    def ang(ux, uy, vx, vy):
        a = math.atan2(ux * vy - uy * vx, ux * vx + uy * vy)
        return a
    t1 = ang(1, 0, (x1 - cx1) / rx, (y1 - cy1) / ry)
    dt = ang((x1 - cx1) / rx, (y1 - cy1) / ry, (-x1 - cx1) / rx, (-y1 - cy1) / ry)
    if not sweep and dt > 0:
        dt -= 2 * math.pi
    elif sweep and dt < 0:
        dt += 2 * math.pi
    n = segs(abs(dt) * max(rx, ry))
    out = []
    for k in range(1, n + 1):
        t = t1 + dt * k / n
        x, y = rx * math.cos(t), ry * math.sin(t)
        out.append((cp * x - sp * y + cx, sp * x + cp * y + cy))
    out[-1] = p1
    return out


# ---------------------------------------------------------------- the document

def import_svg(path):
    """[figures] from an SVG file, in mm, y up (the bottom left of the page = 0, 0)."""
    root = ET.parse(path).getroot()
    vb = [float(v) for v in re.findall(NUM, root.get("viewBox") or "")]
    w_mm, h_mm = length_mm(root.get("width")), length_mm(root.get("height"))
    if len(vb) == 4 and vb[2] > 0 and vb[3] > 0:
        sx = w_mm / vb[2] if w_mm else (h_mm / vb[3] if h_mm else UNITS["px"])
        sy = h_mm / vb[3] if h_mm else sx
        page_h = h_mm if h_mm else vb[3] * sy
        base = (sx, 0, 0, -sy, -vb[0] * sx, page_h + vb[1] * sy)    # user units -> mm, y up
    else:
        sx = sy = UNITS["px"]
        page_h = h_mm or 0.0
        base = (sx, 0, 0, -sy, 0, page_h)
    shapes = []

    def poly(pts, closed, m):
        q = [apply(m, p) for p in pts]
        clean = [q[0]]
        for p in q[1:]:
            if math.dist(p, clean[-1]) > 1e-6:
                clean.append(p)
        if len(clean) == 2 and not closed:
            (x0, y0), (x1, y1) = clean
            shapes.append({"type": "line", "x0": x0, "y0": y0, "x1": x1, "y1": y1})
        elif len(clean) > 1:
            shapes.append({"type": "poly", "pts": [[round(x, 4), round(y, 4)] for x, y in clean], "closed": closed})

    def num(el, k):
        return float((re.findall(NUM, el.get(k) or "0") or ["0"])[0])

    def walk(el, m):
        tag = el.tag.replace(NS, "") if isinstance(el.tag, str) else ""
        if tag in SKIP or "display:none" in (el.get("style") or "").replace(" ", "") or el.get("display") == "none":
            return
        m = mul(m, parse_transform(el.get("transform")))
        k = math.sqrt(abs(m[0] * m[3] - m[1] * m[2]))            # mm per unit (an average for odd transforms)
        if tag == "circle" or tag == "ellipse":
            cx, cy = num(el, "cx"), num(el, "cy")
            rx = num(el, "r") if tag == "circle" else num(el, "rx")
            ry = num(el, "r") if tag == "circle" else num(el, "ry")
            if plain(m):
                c = apply(m, (cx, cy))
                if tag == "circle" or abs(rx - ry) < 1e-9:
                    shapes.append({"type": "circle", "cx": c[0], "cy": c[1], "r": rx * abs(m[0]), "side": "по лінії"})
                else:
                    shapes.append({"type": "ellipse", "cx": c[0], "cy": c[1], "rx": rx * abs(m[0]),
                                   "ry": ry * abs(m[3]), "side": "по лінії"})
            else:
                n = 96
                poly([(cx + rx * math.cos(2 * math.pi * j / n), cy + ry * math.sin(2 * math.pi * j / n))
                      for j in range(n + 1)], True, m)
        elif tag == "rect":
            x, y, w, h = num(el, "x"), num(el, "y"), num(el, "width"), num(el, "height")
            r = num(el, "rx") or num(el, "ry")
            if plain(m):
                p0, p1 = apply(m, (x, y)), apply(m, (x + w, y + h))
                shapes.append({"type": "rect", "x": min(p0[0], p1[0]), "y": min(p0[1], p1[1]), "w": abs(p1[0] - p0[0]),
                               "h": abs(p1[1] - p0[1]), "rad": r * abs(m[0]), "side": "по лінії"})
            else:
                poly([(x, y), (x + w, y), (x + w, y + h), (x, y + h), (x, y)], True, m)
        elif tag == "line":
            poly([(num(el, "x1"), num(el, "y1")), (num(el, "x2"), num(el, "y2"))], False, m)
        elif tag in ("polyline", "polygon"):
            v = [float(x) for x in re.findall(NUM, el.get("points") or "")]
            pts = list(zip(v[0::2], v[1::2]))
            if pts:
                if tag == "polygon":
                    pts.append(pts[0])
                poly(pts, tag == "polygon", m)
        elif tag == "path":
            for pts, closed in flatten_path(el.get("d"), k or 1.0):
                poly(pts, closed, m)
        for child in el:
            walk(child, m)

    for child in root:
        walk(child, base)
    return shapes
