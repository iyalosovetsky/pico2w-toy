"""ЗОРЯНИЙ ТОРГОВЕЦЬ graphics: the ships and the station (convex hulls built in code), the flat-shaded
3D renderer in two looks - modern (dark hulls, light trim stripes, lights that glow) and classic (white
wireframe with hidden lines), the planets, the sun, the stardust and the dashboard.

Everything is drawn at 320x320 (the PicoCalc's pixels); the game scales the frame down on the HAT.
Camera space: x right, y up, z forward; the screen point is (cx + x f / z, cy - y f / z).
"""
import itertools
import math
import random
import time

import numpy as np
import pygame

import lcd

W = H = 320
VH = 214                              # the view; the dashboard below it
FD = "/usr/share/fonts/truetype/dejavu/"
# lcd.init() swaps pygame.font.Font and pygame.draw for scaling wrappers; the game draws in native
# pixels, so it keeps the originals (this module is imported before init)
_FontCls = lcd._Font.__bases__[0] if hasattr(lcd, "_Font") else pygame.font.Font
poly, lines, line, circle = pygame.draw.polygon, pygame.draw.lines, pygame.draw.line, pygame.draw.circle
rect, ellipse, arc = pygame.draw.rect, pygame.draw.ellipse, pygame.draw.arc
NEAR = 6.0
WHITE = (255, 255, 255)
WIRE, WIRE_DIM = (60, 255, 90), (24, 120, 44)   # the classic look: a green monochrome screen


# the HAT's 128x128 shows the 320x320 frame at 0.4: its text is drawn twice as big (and laid out for it)
UI = 2.0 if lcd.NATIVE_H < 200 else 1.0
HAT = UI > 1


def font(name, px):
    try:
        return _FontCls(FD + name, max(6, int(px * UI)))
    except (FileNotFoundError, OSError):
        return _FontCls(None, max(6, int(px * UI)))


def fit(img, maxw=W - 8):
    """Text wider than maxw squeezed to it (the HAT's big letters)."""
    if img.get_width() <= maxw:
        return img
    return pygame.transform.smoothscale(img, (int(maxw), img.get_height()))


def add(a, b): return (a[0] + b[0], a[1] + b[1], a[2] + b[2])
def sub(a, b): return (a[0] - b[0], a[1] - b[1], a[2] - b[2])
def mul(a, k): return (a[0] * k, a[1] * k, a[2] * k)
def cross(a, b): return (a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0])
def dot(a, b): return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def norm(a):
    n = math.sqrt(dot(a, a)) or 1.0
    return (a[0] / n, a[1] / n, a[2] / n)


def shade(c, k):
    return (min(255, int(c[0] * k)), min(255, int(c[1] * k)), min(255, int(c[2] * k)))


def mix(a, b, t):
    t = 0.0 if t < 0 else 1.0 if t > 1 else t
    return tuple(int(a[i] + (b[i] - a[i]) * t) for i in range(3))


# ---------------------------------------------------------------- models

def hull(points):
    """Faces of the convex hull, coplanar triangles merged into polygons, wound outwards."""
    n = len(points)
    planes = {}
    for i, j, k in itertools.combinations(range(n), 3):
        a, b, c = points[i], points[j], points[k]
        nn = cross(sub(b, a), sub(c, a))
        if math.sqrt(dot(nn, nn)) < 1e-6:
            continue
        nn = norm(nn)
        d = dot(nn, a)
        dist = [dot(nn, p) - d for p in points]
        if all(x <= 1e-4 for x in dist):
            pass
        elif all(x >= -1e-4 for x in dist):
            nn, d = mul(nn, -1), -d
        else:
            continue
        key = (round(nn[0], 3), round(nn[1], 3), round(nn[2], 3), round(d, 2))
        if key in planes:
            continue
        on = [m for m in range(n) if abs(dot(nn, points[m]) - d) < 1e-3]
        c = mul(tuple(sum(points[m][q] for m in on) for q in range(3)), 1.0 / len(on))
        u = norm(sub(points[on[0]], c))
        v = cross(nn, u)
        on.sort(key=lambda m: math.atan2(dot(sub(points[m], c), v), dot(sub(points[m], c), u)))
        planes[key] = on
    return list(planes.values())


class Model:
    """Vertices, outward faces, a material per face, decals per face (drawn right after it):
    ("poly", pts, mat, detail) filled, ("line", pts, mat) a stripe, ("light", centre, colour, size)."""

    def __init__(self, v, faces, mats=None, trim=True):
        self.v = [tuple(float(x) for x in p) for p in v]
        self.faces = faces
        self.decals = [[] for _ in faces]
        self.trim = trim
        if mats is None:
            mats = []
            for i in range(len(faces)):
                n = self.frame(i)[3]
                mats.append("stern" if n[2] < -0.75 else "hull" if n[1] > 0.3 else "dark" if n[1] < -0.3 else "hull2")
        self.mats = mats

    @classmethod
    def build(cls, parts, mats=None, trim=True):
        v, faces = [], []
        for pts in parts:
            base = len(v)
            v += pts
            faces += [[base + i for i in f] for f in hull(pts)]
        return cls(v, faces, mats, trim)

    def frame(self, fi):
        """The face's centre, two in-plane axes and the outward normal (model space). The first axis runs
        along the ship's span (x) where the face allows: decals on a slanted face stay level and symmetric."""
        pts = [self.v[i] for i in self.faces[fi]]
        c = mul(tuple(sum(p[k] for p in pts) for k in range(3)), 1.0 / len(pts))
        n = norm(cross(sub(pts[1], pts[0]), sub(pts[2], pts[0])))
        if abs(n[0]) < 0.9:
            u = norm(sub((1.0, 0.0, 0.0), mul(n, n[0])))
        else:
            u = norm(sub(pts[1], pts[0]))
        return c, u, cross(n, u), n

    def on(self, fi, uv, lift=0.4):
        c, u, v, n = self.frame(fi)
        return [add(add(add(c, mul(u, a)), mul(v, b)), mul(n, lift)) for a, b in uv]

    def inset(self, fi, k, lift=0.3):
        c, _, _, n = self.frame(fi)
        return [add(add(c, mul(sub(self.v[i], c), k)), mul(n, lift)) for i in self.faces[fi]]

    def best_face(self, d):
        d = norm(d)
        return max(range(len(self.faces)), key=lambda i: dot(self.frame(i)[3], d))


class Mesh:
    """A model baked with its palette into numpy arrays for drawing: all points (vertices, trim insets,
    decal points) transform in one go."""

    def __init__(self, m, pal, name=""):
        self.name = name
        pts = list(m.v)
        self.nv = len(pts)
        self.faces = m.faces
        self.first = np.array([f[0] for f in m.faces])
        frames = [m.frame(i) for i in range(len(m.faces))]
        self.normals = np.array([fr[3] for fr in frames])
        self.cent = np.array([fr[0] for fr in frames])
        self.base = [pal[mt] for mt in m.mats]
        self.radius = max(math.sqrt(dot(p, p)) for p in m.v)
        self.trim_col = pal.get("trim") if m.trim else None
        self.trim_w = self.radius * 0.013
        self.trims = []
        self.decals = []
        self.marks = []               # the decals the wireframe look outlines too (windows, the slot)
        for i in range(len(m.faces)):
            if self.trim_col:
                ins = m.inset(i, 0.9, 0.3)
                self.trims.append(list(range(len(pts), len(pts) + len(ins))))
                pts += ins
            else:
                self.trims.append(None)
            ds, mk = [], []
            for d in m.decals[i]:
                kind = d[0]
                if kind == "light":
                    ds.append(("light", [len(pts)], d[2], False, d[3]))
                    pts.append(d[1])
                    continue
                idx = list(range(len(pts), len(pts) + len(d[1])))
                pts += d[1]
                mat = d[2]
                lit = mat not in ("window", "engine", "slot", "strip", "slotrim")
                detail = len(d) > 3 and d[3]
                ds.append((kind, idx, pal[mat], lit, detail))
                if mat in ("window", "slot", "engine", "slotrim"):
                    mk.append((kind == "poly", idx))
            self.decals.append(ds)
            self.marks.append(mk)
        self.pts = np.array(pts, float)


def ring_pts(nn, r, y, phase=0.0, z=0.0):
    return [(r * math.cos(phase + 2 * math.pi * i / nn), y, z + r * math.sin(phase + 2 * math.pi * i / nn))
            for i in range(nn)]


def add_engines(m, k=0.45, col=(90, 190, 255), size=6.0):
    fi = m.best_face((0, 0, -1))
    if m.frame(fi)[3][2] > -0.6:
        return
    m.decals[fi] += [("poly", m.inset(fi, k, 0.4), "engine"), ("light", m.inset(fi, 0.01, 0.6)[0], col, size)]


def add_window(m, size=5, d=(0, 1, 0.8)):
    fi = m.best_face(d)
    m.decals[fi].append(("poly", m.on(fi, [(-size, -size * 0.5), (size, -size * 0.5), (size * 0.7, size * 0.5),
                                           (-size * 0.7, size * 0.5)]), "window"))


def chumak():
    """The trader: wide and flat, a wedge front edge, swept wing tips, a raised deck, a wide stern."""
    P = dict(FL=(-34, 0, 46), FR=(34, 0, 46), TL=(-126, -2, -12), TR=(126, -2, -12),
             RTL=(-88, 13, -40), RTR=(88, 13, -40), RBL=(-88, -11, -40), RBR=(88, -11, -40),
             DL=(-30, 21, -6), DR=(30, 21, -6), DRL=(-36, 20, -40), DRR=(36, 20, -40),
             BL=(-30, -15, -4), BR=(30, -15, -4))
    names = list(P)
    i = {k: n for n, k in enumerate(names)}
    F = [("FL FR DR DL", "glass"), ("DL DR DRR DRL", "hull"),
         ("FL DL TL", "hull"), ("DL DRL RTL", "hull"), ("DL RTL TL", "hull"),
         ("FR TR DR", "hull"), ("DR RTR DRR", "hull"), ("DR TR RTR", "hull"),
         ("FL BL BR FR", "dark"), ("BL RBL RBR BR", "dark"),
         ("FL TL BL", "dark"), ("BL TL RBL", "dark"), ("FR BR TR", "dark"), ("BR RBR TR", "dark"),
         ("RTL DRL DRR RTR RBR RBL", "stern"), ("TL RTL RBL", "hull"), ("TR RBR RTR", "hull")]
    v = [P[k] for k in names]
    faces = [[i[k] for k in s.split()] for s, _ in F]
    cen = mul(tuple(sum(p[k] for p in v) for k in range(3)), 1.0 / len(v))
    for n, f in enumerate(faces):                   # outward winding
        a, b, c = v[f[0]], v[f[1]], v[f[2]]
        fc = mul(tuple(sum(v[j][k] for j in f) for k in range(3)), 1.0 / len(f))
        if dot(cross(sub(b, a), sub(c, a)), sub(fc, cen)) < 0:
            faces[n] = f[::-1]
    m = Model(v, faces, [mt for _, mt in F])
    m.decals[0] += [("poly", m.on(0, [(-20, -14), (-4, -14), (-5, -2), (-17, -2)]), "window"),
                    ("poly", m.on(0, [(4, -14), (20, -14), (17, -2), (5, -2)]), "window")]
    ins = m.inset(1, 0.8)
    m.decals[1] += [("line", [ins[0], ins[2]], "trim"), ("line", [ins[1], ins[3]], "trim"),
                    ("poly", m.on(1, [(-8, -6), (8, -6), (8, 6), (-8, 6)]), "panel")]
    for s in (-1, 1):
        m.decals[9].append(("poly", m.on(9, [(s * 10, -8), (s * 46, -8), (s * 40, 10), (s * 10, 10)]), "grille"))
    for s in (-1, 1):
        m.decals[14] += [("poly", m.on(14, [(s * 18, -6), (s * 56, -6), (s * 56, 5), (s * 18, 5)]), "engine"),
                         ("light", m.on(14, [(s * 37, 0)])[0], (90, 190, 255), 7.0)]
    m.decals[15].append(("light", m.inset(15, 0.6)[0], (90, 200, 255), 3.0))
    m.decals[16].append(("light", m.inset(16, 0.6)[0], (90, 200, 255), 3.0))
    return m


def station(r=600):
    """The station: a cuboctahedron, the docking slot in the square face towards -z (long side along x)."""
    v = []
    for a in (-1, 1):
        for b in (-1, 1):
            v += [(a * r, b * r, 0), (a * r, 0, b * r), (0, a * r, b * r)]

    def find(p):
        return min(range(len(v)), key=lambda k: sum((v[k][j] - p[j]) ** 2 for j in range(3)))
    F, mats = [], []
    for sx in (-1, 1):
        for sy in (-1, 1):
            for sz in (-1, 1):
                F.append([find((sx * r, sy * r, 0)), find((sx * r, 0, sz * r)), find((0, sy * r, sz * r))])
                mats.append("hull")
    slot = None
    for axis in range(3):
        for s in (-1, 1):
            q = [k for k, p in enumerate(v) if abs(p[axis] - s * r) < 1e-6]
            c = [sum(v[k][j] for k in q) / 4 for j in range(3)]
            o = [j for j in range(3) if j != axis]
            q.sort(key=lambda k: math.atan2(v[k][o[1]] - c[o[1]], v[k][o[0]] - c[o[0]]))
            if axis == 2 and s == -1:
                slot = len(F)
            F.append(q)
            mats.append("hull2")
    for n, f in enumerate(F):                       # outward winding
        a, b, c = v[f[0]], v[f[1]], v[f[2]]
        fc = mul(tuple(sum(v[j][k] for j in f) for k in range(3)), 1.0 / len(f))
        if dot(cross(sub(b, a), sub(c, a)), fc) < 0:
            F[n] = f[::-1]
    m = Model(v, F, mats)
    rnd = random.Random(7)
    for fi in range(len(F)):
        if fi == slot:
            continue
        for _ in range(8 if len(F[fi]) == 3 else 5):          # greebles: small dark and light blocks
            a, b = rnd.uniform(-0.3, 0.3) * r, rnd.uniform(-0.3, 0.3) * r
            sz = rnd.uniform(0.04, 0.1) * r
            m.decals[fi].append(("poly", m.on(fi, [(a, b), (a + sz * 1.6, b), (a + sz * 1.6, b + sz), (a, b + sz)], 2),
                                 rnd.choice(("panel", "grille", "panel2")), True))
        pts = m.inset(fi, 0.78, 3)
        for k in range(len(pts)):                               # blue light strips along the edges
            p, q = pts[k], pts[(k + 1) % len(pts)]
            if rnd.random() < 0.6:
                t0 = rnd.uniform(0.1, 0.5)
                m.decals[fi].append(("line", [add(p, mul(sub(q, p), t0)), add(p, mul(sub(q, p), t0 + 0.3))], "strip"))
    for fi in range(len(F)):                                    # the square faces' corner pyramids
        if len(F[fi]) != 4:
            continue
        c0, _, _, n0 = m.frame(fi)
        for p in m.inset(fi, 0.86, 4):
            d = mul(norm(sub(c0, p)), r * 0.09)
            e = mul(norm(cross(n0, d)), r * 0.09)
            m.decals[fi].append(("poly", [p, add(add(p, d), e), add(p, mul(d, 2)), add(add(p, d), mul(e, -1))], "trim"))
    circ = [(math.cos(a), math.sin(a)) for a in np.linspace(0, 2 * math.pi, 25)]
    m.decals[slot].insert(0, ("poly", m.on(slot, [(0.62 * r * x, 0.62 * r * y) for x, y in circ], 2), "ringface"))
    for k, (rad, mat) in enumerate(((0.62, "trim"), (0.5, "strip"), (0.36, "trim"))):
        m.decals[slot].append(("line", m.on(slot, [(rad * r * x, rad * r * y) for x, y in circ], 3 + k), mat))
    # the slot: its long side along the model's x
    c0, u0, v0, n0 = m.frame(slot)
    sx, sy = 0.27 * r, 0.08 * r
    rectp = [add(add(add(c0, (-sx, -sy, 0)), (0, 0, 0)), mul(n0, 6)), add(c0, add((sx, -sy, 0), mul(n0, 6))),
             add(c0, add((sx, sy, 0), mul(n0, 6))), add(c0, add((-sx, sy, 0), mul(n0, 6)))]
    m.decals[slot] += [("poly", rectp, "slot"), ("line", rectp + [rectp[0]], "slotrim")]
    m.slot = slot
    m.slot_size = (sx, sy)
    return m


def osa():
    m = Model.build([[(0, 0, 46), (-50, 0, -12), (50, 0, -12), (-22, 3, -26), (22, 3, -26), (-22, -3, -26),
                      (22, -3, -26), (0, 9, -6), (0, -6, -10)]])
    add_window(m, 4)
    add_engines(m, 0.5, size=4)
    return m


def sokil():
    m = Model.build([[(0, 0, 62), (-32, -4, -26), (32, -4, -26), (0, 13, -22), (0, -9, -26), (-12, 4, -30),
                      (12, 4, -30)]])
    add_window(m, 4, (0, 1, 1))
    add_engines(m, 0.5, size=4)
    return m


def shulika():
    m = Model.build([[(0, 0, 64), (-78, -4, -34), (78, -4, -34), (-22, 14, -34), (22, 14, -34), (0, -12, -30)]])
    add_window(m, 6, (0, 1, 0.4))
    add_engines(m, 0.4, (255, 150, 60), 6)
    return m


def mazha():
    pts = [(0, 2, 124)]
    for z, w, h, lo in ((40, 30, 22, -18), (-70, 40, 28, -22)):
        pts += [(-w, h, z), (w, h, z), (-w * 1.45, 0, z), (w * 1.45, 0, z), (-w, lo, z), (w, lo, z)]
    pts.append((0, 40, -50))
    m = Model.build([pts])
    add_window(m, 7, (0, 1, 0.5))
    add_engines(m, 0.55, size=9)
    return m


def vulyk():
    m = Model.build([ring_pts(7, 62, -14) + ring_pts(7, 92, 0) + ring_pts(7, 48, 22)])
    for fi in range(len(m.faces)):
        n = m.frame(fi)[3]
        if abs(n[1]) < 0.8 and n[1] > 0:
            m.decals[fi].append(("line", m.inset(fi, 0.55, 0.5)[:2], "strip"))
        elif n[1] < -0.9:
            m.decals[fi].append(("light", m.frame(fi)[0], (120, 255, 140), 7))
    return m


def groza():
    """The stolen prototype: a long dagger with swept fins and a raised canopy, twin engines."""
    body = [(0, 0, 80), (-16, 0, -40), (16, 0, -40), (0, 10, -30), (0, -8, -36), (-8, 6, 20), (8, 6, 20),
            (0, 12, 5)]
    fins = []
    for s_ in (-1, 1):
        fins.append([(s_ * 10, 0, -10), (s_ * 62, -4, -46), (s_ * 14, 0, -42), (s_ * 10, 2, -12), (s_ * 58, -2, -44),
                     (s_ * 14, 2, -40)])
    m = Model.build([body] + fins)
    add_window(m, 5, (0, 1, 0.6))
    add_engines(m, 0.55, (255, 120, 220), 6)
    return m


def truten():
    m = Model.build([ring_pts(5, 28, -8) + ring_pts(5, 16, 12, math.pi / 5, -4)])
    for fi in range(len(m.faces)):
        if m.frame(fi)[3][1] > 0.9:
            m.decals[fi].append(("light", m.frame(fi)[0], (120, 255, 140), 2))
    return m


def rocket():
    body = [(x, y, z) for z in (-40, 30) for x, y in ((-5, -5), (5, -5), (5, 5), (-5, 5))] + [(0, 0, 48)]
    parts = [body]
    for a in range(4):
        c, s = math.cos(a * math.pi / 2), math.sin(a * math.pi / 2)
        part = []
        for x, y, z in ((5, 0, -40), (18, 0, -46), (5, 0, -18)):
            for t in (-1, 1):
                part.append((x * c - (y + t) * s, x * s + (y + t) * c, z))
        parts.append(part)
    m = Model.build(parts)
    add_engines(m, 0.6, (255, 170, 80), 4)
    return m


def kapsula():
    m = Model.build([[(0, 0, 32), (-13, -8, -14), (13, -8, -14), (0, 13, -14)]])
    add_engines(m, 0.4, (255, 170, 80), 3)
    return m


def kontejner():
    m = Model.build([[(r * math.cos(a), r * math.sin(a), z) for z, r in ((-26, 20), (26, 20), (-32, 14), (32, 14))
                      for a in (math.pi * i / 3 + math.pi / 6 for i in range(6))]])
    for fi in range(len(m.faces)):
        if abs(m.frame(fi)[3][2]) < 0.2:
            m.decals[fi].append(("line", m.inset(fi, 0.7, 0.4)[:2], "trim"))
    return m


def asteroid(seed=3, size=55):
    rnd = random.Random(seed)
    pts = []
    for _ in range(16):
        z = rnd.uniform(-1, 1)
        a = rnd.uniform(0, 2 * math.pi)
        r = rnd.uniform(0.85, 1.12) * size
        q = math.sqrt(1 - z * z)
        pts.append((r * q * math.cos(a), r * q * math.sin(a) * 0.8, r * z))
    m = Model.build([pts], trim=False)
    m.mats = ["hull"] * len(m.faces)
    return m


DARK = {"hull": (78, 80, 88), "hull2": (70, 72, 80), "dark": (44, 46, 52), "stern": (40, 42, 48),
        "glass": (60, 66, 78), "window": (150, 205, 255), "engine": (120, 210, 255), "trim": (220, 210, 188),
        "panel": (40, 42, 48), "panel2": (100, 102, 110), "grille": (30, 26, 28), "strip": (90, 190, 255),
        "slot": (150, 220, 255), "slotrim": (230, 240, 255), "ringface": (52, 54, 62)}

# name, role, the model, its palette, the scanner colour
TYPES = {
    "chumak": ("Чумак", "торговець · наш корабель", chumak, DARK, (255, 220, 80)),
    "osa": ("Оса", "легкий винищувач", osa,
            dict(DARK, hull=(80, 96, 124), hull2=(70, 84, 110), dark=(40, 46, 60)), (255, 220, 80)),
    "sokil": ("Сокіл", "поліцейський перехоплювач", sokil,
              dict(DARK, hull=(170, 176, 190), hull2=(140, 146, 162), dark=(70, 76, 96), trim=(90, 170, 255)),
              (90, 170, 255)),
    "shulika": ("Шуліка", "пірат", shulika,
                dict(DARK, hull=(124, 50, 46), hull2=(104, 40, 40), dark=(58, 28, 28), trim=(240, 190, 120)),
                (255, 80, 60)),
    "mazha": ("Віз", "важкий вантажовоз", mazha,
              dict(DARK, hull=(132, 112, 80), hull2=(112, 94, 68), dark=(60, 52, 40)), (255, 220, 80)),
    "vulyk": ("Вулик", "чужинці · матка", vulyk,
              dict(DARK, hull=(44, 82, 62), hull2=(36, 70, 54), dark=(22, 40, 32), stern=(36, 70, 54),
                   trim=(140, 255, 160), strip=(120, 255, 140)), (120, 255, 140)),
    "groza": ("Гроза", "викрадений прототип", groza,
              dict(DARK, hull=(40, 38, 46), hull2=(30, 28, 36), dark=(20, 18, 24), stern=(26, 24, 30),
                   trim=(230, 190, 90), window=(255, 120, 220)), (255, 80, 200)),
    "truten": ("Трутень", "чужинці · дрон", truten,
               dict(DARK, hull=(54, 96, 72), hull2=(44, 80, 60), dark=(26, 46, 36), stern=(44, 80, 60),
                    trim=(140, 255, 160)), (120, 255, 140)),
    "station": ("Станція", "кубооктаедр зі щілиною", station,
                dict(DARK, hull=(64, 66, 74), hull2=(74, 76, 86)), (120, 255, 140)),
    "rocket": ("Ракета", "самонавідна", rocket,
               dict(DARK, hull=(190, 192, 200), hull2=(160, 162, 170), trim=(230, 70, 60)), (255, 255, 255)),
    "kapsula": ("Капсула", "рятувальна", kapsula,
                dict(DARK, hull=(220, 130, 50), hull2=(190, 110, 40), dark=(110, 64, 30)), (255, 255, 255)),
    "kontejner": ("Контейнер", "вантаж у космосі", kontejner,
                  dict(DARK, hull=(150, 140, 100), hull2=(130, 120, 86), dark=(80, 74, 54), stern=(110, 100, 74),
                       trim=(240, 200, 60)), (230, 230, 230)),
    "asteroid": ("Астероїд", "можна добувати руду", asteroid, dict(DARK, hull=(72, 71, 70)), (200, 200, 200)),
}
_meshes = {}


def mesh(kind):
    if kind not in _meshes:
        name, _, make, pal, _ = TYPES[kind]
        m = make()
        me = Mesh(m, pal, name)
        if kind == "station":
            me.slot_size = m.slot_size
        _meshes[kind] = me
    return _meshes[kind]


# ---------------------------------------------------------------- glows

_glows = {}


def glow(surf, p, col, rad):
    """An additive soft dot (a premultiplied sprite: black is no light)."""
    rq = max(2, int(min(rad, 90) + 0.5))     # never a giant picture, whatever asks for it
    if rq > 12:
        rq = rq // 4 * 4                     # fewer sizes to cache for the big ones
    key = (col, rq)
    g = _glows.get(key)
    if g is None:
        if len(_glows) > 120:
            _glows.clear()
        n = rq * 2 + 1
        yy, xx = np.mgrid[0:n, 0:n].astype(np.float32) - rq
        k = np.clip(1 - np.sqrt(xx * xx + yy * yy) / rq, 0, 1) ** 2
        img = (k[..., None] * np.array(col, np.float32)).astype(np.uint8)
        g = pygame.Surface((n, n))
        pygame.surfarray.blit_array(g, img.swapaxes(0, 1))
        _glows[key] = g
    surf.blit(g, (p[0] - rq, p[1] - rq), special_flags=pygame.BLEND_ADD)


# ---------------------------------------------------------------- the renderer

def clip_near(P):
    out = []
    n = len(P)
    for i in range(n):
        a, b = P[i], P[(i + 1) % n]
        ain, bin_ = a[2] >= NEAR, b[2] >= NEAR
        if ain:
            out.append(a)
        if ain != bin_:
            t = (NEAR - a[2]) / (b[2] - a[2])
            out.append(a + (b - a) * t)
    return out


def clip_rect(pts, x0, y0, x1, y1):
    """Sutherland-Hodgman against a rectangle: pygame's polygon fill crawls over huge off-screen
    coordinates (a face next to the camera projects to tens of thousands of pixels)."""
    for axis, lim, keep_lt in ((0, x0, False), (0, x1, True), (1, y0, False), (1, y1, True)):
        if not pts:
            return pts
        out = []
        n = len(pts)
        for i in range(n):
            a, b = pts[i], pts[(i + 1) % n]
            ain = (a[axis] <= lim) if keep_lt else (a[axis] >= lim)
            bin_ = (b[axis] <= lim) if keep_lt else (b[axis] >= lim)
            if ain:
                out.append(a)
            if ain != bin_:
                t = (lim - a[axis]) / (b[axis] - a[axis])
                out.append((a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t))
        pts = out
    return pts


def fill_poly(surf, col, pts):
    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    h = surf.get_height()
    if min(xs) < -64 or max(xs) > W + 64 or min(ys) < -64 or max(ys) > h + 64:
        if max(xs) < 0 or min(xs) > W or max(ys) < 0 or min(ys) > h:
            return
        pts = clip_rect(pts, -2, -2, W + 2, h + 2)
        if len(pts) < 3:
            return
    poly(surf, col, pts)


def draw_mesh(surf, me, M, t, f, cx, cy, Lc, style, detail=True):
    """One object: M (3x3) and t take its model points to camera space; Lc - the light's direction
    (from the sun) in camera space."""
    tz = t[2]
    if tz < -me.radius:
        return
    if tz > NEAR:
        pr = me.radius * f / tz
        sx, sy = cx + t[0] * f / tz, cy - t[1] * f / tz
        if sx + pr < 0 or sx - pr > W or sy + pr < 0 or sy - pr > surf.get_height():
            return
        if pr < 1.6:
            c = WIRE if style == "wire" else shade(me.base[0], 1.6)
            surf.fill(c, (int(sx), int(sy), 1, 1))
            return
        detail = detail and pr > 60
    P = me.pts @ M.T + t
    z = P[:, 2]
    Nc = me.normals @ M.T
    v0 = P[me.first]
    vis = np.einsum("ij,ij->i", Nc, v0) < 0
    idx = np.nonzero(vis)[0]
    if not len(idx):
        return
    C = me.cent[idx] @ M.T + t
    order = idx[np.argsort(-C[:, 2])]
    lit = np.clip(-(Nc @ Lc), 0, 1).tolist()
    zs = np.maximum(z, NEAR)
    S = np.stack([cx + P[:, 0] * f / zs, cy - P[:, 1] * f / zs], 1).tolist()
    zl = z.tolist()
    wire = style == "wire"
    lights = []
    for i in order.tolist():
        fc = me.faces[i]
        clipped = False
        if min(zl[k] for k in fc) < NEAR:
            cp = clip_near([P[k] for k in fc])
            if len(cp) < 3:
                continue
            pts = [(cx + q[0] * f / q[2], cy - q[1] * f / q[2]) for q in cp]
            clipped = True
        else:
            pts = [S[k] for k in fc]
        if wire:
            fill_poly(surf, (0, 0, 0), pts)
            lines(surf, WIRE, True, pts, 1)
            if not clipped:
                for closed, ix in me.marks[i]:
                    lines(surf, WIRE, closed, [S[k] for k in ix], 1)
            continue
        li = lit[i]
        k = 0.26 + 0.95 * li
        base = me.base[i]
        fill_poly(surf, shade(base, k), pts)
        if clipped:
            continue
        dist = sum(zl[q] for q in fc) / len(fc)
        if me.trim_col:
            lw = min(6, max(1, int(me.trim_w * f / dist + 0.5)))   # right by the camera it would be 300 px
            lines(surf, shade(me.trim_col, 0.35 + 0.75 * li), True, [S[q] for q in me.trims[i]], lw)
            lines(surf, shade(base, k * 1.25 + 0.1), True, pts, 1)
        for kind, ix, col, shaded, det in me.decals[i]:
            if kind == "light":
                if zl[ix[0]] > NEAR:
                    lights.append((S[ix[0]], col, det * f / zl[ix[0]]))
                continue
            if det and not detail:
                continue
            if min(zl[q] for q in ix) < NEAR:
                continue
            c = shade(col, 0.35 + 0.8 * li) if shaded else col
            q = [S[j] for j in ix]
            if kind == "poly":
                fill_poly(surf, c, q)
            else:
                lines(surf, c, False, q, min(5, max(1, int(me.trim_w * 0.8 * f / dist + 0.5))))
    h = surf.get_height()
    for p, col, rad in lights:
        # a light passing by the camera would want a glow hundreds of pixels wide - a new numpy picture
        # each frame (seconds on the Zero); capped, and none for lights off the screen
        rad = min(rad, 16.0)
        if rad > 0.6 and -2 * rad < p[0] < W + 2 * rad and -2 * rad < p[1] < h + 2 * rad:
            glow(surf, p, col, rad * 2.2)
            circle(surf, (230, 245, 255), p, max(1, rad * 0.4))


# ---------------------------------------------------------------- planets, the sun

def noise(u, v, freq, seed):
    rnd = np.random.default_rng(seed)
    g = rnd.random((freq + 1, freq + 1)).astype(np.float32)
    g[:, -1] = g[:, 0]
    x, y = (u % 1) * freq, np.clip(v, 0, 0.999) * freq
    i, j = x.astype(int), y.astype(int)
    fx, fy = x - i, y - j
    fx, fy = fx * fx * (3 - 2 * fx), fy * fy * (3 - 2 * fy)
    a, b = g[j, i], g[j, i + 1]
    c, d = g[j + 1, i], g[j + 1, i + 1]
    top = a + (b - a) * fx
    return top + ((c + (d - c) * fx) - top) * fy


def fbm(u, v, seed, octaves=5, f0=4):
    out, amp, tot = 0, 1.0, 0
    for k in range(octaves):
        out = out + noise(u, v, f0 << k, seed + k) * amp
        tot += amp
        amp *= 0.5
    return out / tot


def planet_texture(kind, seed, tw=384, th=192):
    """An equirectangular colour map (th, tw, 3) and the atmosphere's colour."""
    vv, uu = np.mgrid[0:th, 0:tw].astype(np.float32)
    u, v = uu / tw, vv / th
    def ramp(h, stops):
        """Colours along a height ramp: [(h, (r, g, b)), ...]."""
        hs = [p for p, _ in stops]
        return np.stack([np.interp(h, hs, [c[i] for _, c in stops]) for i in range(3)], -1).astype(np.float32)
    if kind in ("earth", "ocean"):
        h = fbm(u, v, seed)
        sea = 0.53 if kind == "earth" else 0.66
        ocean = np.array((20, 50, 120), np.float32)
        land = np.where((h > sea + 0.09)[..., None], np.array((150, 130, 95), np.float32), np.array((60, 100, 55), np.float32))
        c = np.where((h > sea)[..., None], land, ocean * (0.7 + 0.6 * h[..., None]))
        cl = np.clip((fbm(u + v * 0.3, v, seed + 29, 4, 6) - 0.55) * 4, 0, 1)
        c = c * (1 - cl[..., None]) + np.array((230, 232, 240), np.float32) * cl[..., None]
        ice = np.clip((np.abs(v - 0.5) - 0.42) * 30, 0, 1)
        c = c * (1 - ice[..., None]) + 235 * ice[..., None]
        return c, (60, 140, 255)
    if kind == "desert":
        h = fbm(u, v, seed, 6, 4)
        dunes = 0.5 + 0.5 * np.sin((v * 90 + fbm(u, v, seed + 5, 3, 6) * 20))
        c = ramp(h + 0.05 * dunes, [(0.2, (120, 70, 40)), (0.45, (200, 140, 80)), (0.6, (225, 180, 120)),
                                    (0.8, (170, 110, 70))])
        return c, (230, 170, 110)
    if kind == "ice":
        h = fbm(u, v, seed, 6, 4)
        c = ramp(h, [(0.25, (90, 120, 160)), (0.45, (180, 205, 230)), (0.6, (235, 242, 250)), (0.8, (200, 215, 235))])
        cracks = np.abs(fbm(u, v, seed + 3, 4, 8) - 0.5) < 0.012
        c = np.where(cracks[..., None], np.array((70, 110, 150), np.float32), c)
        return c, (170, 210, 255)
    if kind == "lava":
        h = fbm(u, v, seed, 6, 4)
        c = ramp(h, [(0.2, (30, 20, 20)), (0.5, (60, 40, 35)), (0.75, (90, 70, 60))])
        flow = np.abs(fbm(u, v, seed + 7, 5, 5) - 0.5) < 0.03
        c = np.where(flow[..., None], np.array((255, 120, 30), np.float32), c)
        return c, (255, 110, 50)
    h = fbm(u, v, seed + 10, 6, 5)
    c = np.repeat((70 + 120 * h)[..., None], 3, -1) * np.array((1.0, 0.98, 0.95), np.float32)
    rnd = np.random.default_rng(seed)
    for _ in range(40):                     # craters: each worked out on its own patch only
        cu, cv, cr = rnd.random(), rnd.uniform(0.15, 0.85), rnd.uniform(0.008, 0.04)
        j0, j1 = max(0, int((cv - cr * 1.2) * th)), min(th, int((cv + cr * 1.2) * th) + 2)
        half = cr * 1.2 / max(0.2, math.sin(cv * math.pi))
        cols = np.arange(int((cu - half) * tw), int((cu + half) * tw) + 2) % tw
        rows = np.arange(j0, j1)
        uu, vv = u[np.ix_(rows, cols)], v[np.ix_(rows, cols)]
        du = (uu - cu + 0.5) % 1 - 0.5
        dd = np.sqrt((du * np.sin(vv * np.pi)) ** 2 + (vv - cv) ** 2) / cr
        patch = c[np.ix_(rows, cols)]
        c[np.ix_(rows, cols)] = patch * np.where(dd < 1, 0.8, 1)[..., None] + \
            np.where((dd > 0.9) & (dd < 1.15), 25, 0)[..., None]
    return c, (120, 120, 130)


def sphere(tex, air, size, L, scale=1):
    """A lit ball, the texture wrapped on it (screen-fixed), light L in screen axes (x right, y up, z to us):
    an RGBA surface size x size (each pixel `scale` screen pixels)."""
    return to_surface(*sphere_arrays(tex, air, size, L, scale))


def to_surface(img, alpha):
    s = pygame.Surface(img.shape[1::-1], pygame.SRCALPHA)
    pygame.surfarray.pixels3d(s)[:] = img.swapaxes(0, 1)
    pygame.surfarray.pixels_alpha(s)[:] = alpha.swapaxes(0, 1)
    return s


def sphere_arrays(tex, air, size, L, scale=1):
    """The lit ball as numpy arrays (colour, alpha) - no pygame: safe in a worker thread."""
    r = size / 2 - 3
    yy, xx = np.mgrid[0:size, 0:size].astype(np.float32) - size / 2 + 0.5
    d2 = xx * xx + yy * yy
    dist = np.sqrt(d2)
    inside = d2 <= r * r
    z = np.sqrt(np.maximum(r * r - d2, 0))
    nx, ny, nz = xx / r, -yy / r, z / r
    lit = np.clip(nx * L[0] + ny * L[1] + nz * L[2], 0, 1)
    th, tw = tex.shape[:2]
    u = (np.arctan2(nx, nz) / (2 * np.pi) + 0.5) * (tw - 1)
    v = np.arccos(np.clip(ny, -1, 1)) / np.pi * (th - 1)
    c = tex[v.astype(int), u.astype(int)]
    img = c * (0.03 + lit[..., None] ** 0.8)
    rim = np.clip((dist - r * 0.82) / (r * 0.18), 0, 1) ** 2 * lit ** 0.5
    img += rim[..., None] * np.array(air, np.float32) * 0.8
    alpha = np.where(inside, 255.0, 0.0)
    halo = max(2.0, 4.0 / scale)
    out = (~inside) & (dist < r + halo)
    hl = np.clip(1 - (dist - r) / halo, 0, 1) * np.clip((nx * L[0] + ny * L[1]) * 1.4 + 0.2, 0, 1)
    img = np.where(out[..., None], np.array(air, np.float32), img)
    alpha = np.where(out, hl * 170, alpha)
    edge = inside & (dist > r - 1)
    alpha = np.where(edge, 255 * np.clip(r - dist + 1, 0, 1), alpha)
    return np.clip(img, 0, 255).astype(np.uint8), alpha.astype(np.uint8)


PKEY = (0, 0, 1)                       # space behind a planet sprite: almost black, keyed out


class Planet:
    """Drawn from pre-lit masters (one per phase, the light from the right) turned to the sun and scaled,
    cached; when it fills the view - straight from the texture at a third of the resolution."""
    PHASES = 9
    MASTER = 300

    def __init__(self, kind="earth", seed=11):
        self.tex, self.air = planet_texture(kind, seed)
        self.masters = [None] * self.PHASES          # pictures, made from the arrays when first drawn
        self.arrays = [None] * self.PHASES           # the lit masters as numpy (prewarm, maybe in a thread)
        self.cache = {}                              # (phase, angle, size) -> a keyed picture, oldest first
        self.scaled = {}                             # (phase, size) -> the master scaled
        self.pixels = 0
        self.made = 0.0
        self.gap = 0.12                              # seconds between new pictures (the game sets it)
        rnd = random.Random(seed)
        dots = []                                       # the classic look: dots on the disc
        for _ in range(2400):
            x, y = rnd.uniform(-1, 1), rnd.uniform(-1, 1)
            if x * x + y * y < 1:
                dots.append((x, y, math.sqrt(1 - x * x - y * y), rnd.random()))
        self.dots = np.array(dots)

    def master(self, i):
        if self.masters[i] is None:
            if self.arrays[i] is None:
                self.prewarm_one(i)
            self.masters[i] = to_surface(*self.arrays[i])
            self.arrays[i] = None
        return self.masters[i]

    def prewarm_one(self, i):
        th = math.pi * i / (self.PHASES - 1)
        self.arrays[i] = sphere_arrays(self.tex, self.air, self.MASTER, (math.sin(th), 0, math.cos(th)))

    def prewarm(self):
        """Light one missing master (numpy only: it may run in a worker thread); False while some are left."""
        for i in range(self.PHASES):
            if self.masters[i] is None and self.arrays[i] is None:
                self.prewarm_one(i)
                return False
        return True

    def draw(self, surf, cx, cy, r, Ls, style):
        """Ls - the direction from the planet to the sun in camera axes."""
        if r < 1.5:
            surf.fill(WIRE if style == "wire" else (120, 160, 220), (int(cx), int(cy), 1, 1))
            return
        if style == "wire":
            self.draw_dots(surf, cx, cy, r, Ls)
            return
        if r > 260:
            self.draw_near(surf, cx, cy, r, Ls)
            return
        th = math.acos(max(-1.0, min(1.0, -Ls[2])))
        ph = int(round(th / math.pi * (self.PHASES - 1)))
        ang = int(round(math.degrees(math.atan2(Ls[1], Ls[0])) / 6.0)) * 6 % 360
        rq = int(round(math.log(r) / math.log(1.035)))              # sizes 3.5 % apart
        key = (ph, ang, rq)
        s = self.cache.get(key)
        if s is None:
            # turning fast every few degrees want a new picture: make at most one now and then,
            # meanwhile show the nearest one made (nobody sees the terminator lag in a spin)
            now = time.monotonic()
            if now - self.made < self.gap:
                s = self.nearest(ph, ang, rq)
            if s is None:
                s = self.make(ph, ang, rq, r)
                self.made = now
        else:
            self.cache[key] = self.cache.pop(key)                    # recently used: to the end
        surf.blit(s, (cx - s.get_width() / 2, cy - s.get_height() / 2))

    def nearest(self, ph, ang, rq):
        best, bs = None, 1e9
        for (p, a, q), s in self.cache.items():
            if abs(q - rq) > 3:
                continue
            d = abs((a - ang + 180) % 360 - 180) + 25 * abs(p - ph) + 10 * abs(q - rq)
            if d < bs:
                best, bs = s, d
        return best

    def make(self, ph, ang, rq, r):
        """Scale the lit master once per size, turn that (cheap, unfiltered), flatten over a key colour:
        a keyed blit is several times faster than a per-pixel alpha one."""
        size = max(4, int(2 * r + 6))
        sk = (ph, rq)
        sc = self.scaled.get(sk)
        if sc is None:
            if len(self.scaled) > 12:
                self.scaled.pop(next(iter(self.scaled)))
            sc = pygame.transform.smoothscale(self.master(ph), (size, size))
            self.scaled[sk] = sc
        a = pygame.transform.rotate(sc, ang)
        s = pygame.Surface(a.get_size())
        s.fill(PKEY)
        s.blit(a, (0, 0))
        s.set_colorkey(PKEY, pygame.RLEACCEL)
        self.cache[(ph, ang, rq)] = s
        self.pixels += s.get_width() * s.get_height()
        while self.pixels > 3_000_000 and len(self.cache) > 1:     # ~12 MB of pictures at most
            old = self.cache.pop(next(iter(self.cache)))
            self.pixels -= old.get_width() * old.get_height()
        return s

    def draw_near(self, surf, cx, cy, r, Ls):
        q = 3
        h = surf.get_height()
        x0, x1 = max(0, int(cx - r - 4)), min(W, int(cx + r + 4))
        y0, y1 = max(0, int(cy - r - 4)), min(h, int(cy + r + 4))
        if x1 <= x0 or y1 <= y0:
            return
        sw, sh = (x1 - x0 + q - 1) // q, (y1 - y0 + q - 1) // q
        yy, xx = np.mgrid[0:sh, 0:sw].astype(np.float32)
        xx = (x0 + xx * q + q / 2 - cx) / r
        yy = (y0 + yy * q + q / 2 - cy) / r
        d2 = xx * xx + yy * yy
        inside = d2 <= 1
        nz = np.sqrt(np.maximum(1 - d2, 0))
        nx, ny = xx, -yy
        lit = np.clip(nx * Ls[0] + ny * Ls[1] - nz * Ls[2], 0, 1)
        th, tw = self.tex.shape[:2]
        u = (np.arctan2(nx, nz) / (2 * np.pi) + 0.5) * (tw - 1)
        v = np.arccos(np.clip(ny, -1, 1)) / np.pi * (th - 1)
        c = self.tex[v.astype(int), u.astype(int)] * (0.03 + lit[..., None] ** 0.8)
        rim = np.clip((np.sqrt(d2) - 0.82) / 0.18, 0, 1) ** 2 * lit ** 0.5
        c += rim[..., None] * np.array(self.air, np.float32) * 0.8
        img = pygame.Surface((sw, sh), pygame.SRCALPHA)
        pygame.surfarray.pixels3d(img)[:] = np.clip(c, 0, 255).astype(np.uint8).swapaxes(0, 1)
        pygame.surfarray.pixels_alpha(img)[:] = np.where(inside, 255, 0).astype(np.uint8).swapaxes(0, 1)
        surf.blit(pygame.transform.scale(img, (sw * q, sh * q)), (x0, y0))

    def draw_dots(self, surf, cx, cy, r, Ls):
        circle(surf, (0, 0, 0), (cx, cy), r)
        if r < 3000:
            circle(surf, WIRE, (cx, cy), r, 1)
        n = min(len(self.dots), int(r * r * 0.35) + 30)
        d = self.dots[:n]
        lit = np.clip(d[:, 0] * Ls[0] - d[:, 1] * Ls[1] - d[:, 2] * Ls[2], 0, 1)
        px = (cx + d[:, 0] * r).astype(int)
        py = (cy + d[:, 1] * r).astype(int)
        h = surf.get_height()
        m = (d[:, 3] < lit ** 1.3) & (px >= 0) & (px < W) & (py >= 0) & (py < h)
        arr = pygame.surfarray.pixels2d(surf)
        arr[px[m], py[m]] = surf.map_rgb(WIRE)
        del arr


def draw_sun(surf, cx, cy, r, style, t):
    if r < 1:
        r = 1
    if style == "wire":
        circle(surf, (0, 0, 0), (cx, cy), r)
        rnd = random.Random(int(t * 12))
        for y in range(int(-r), int(r) + 1, 2):
            w = math.sqrt(max(0, r * r - y * y)) * rnd.uniform(0.85, 1.0)
            line(surf, WIRE, (cx - w, cy + y), (cx + w, cy + y))
        return
    glow(surf, (cx, cy), (110, 80, 30), r * 4 + 6)
    glow(surf, (cx, cy), (180, 150, 80), r * 2 + 3)
    circle(surf, (255, 240, 200), (cx, cy), r)


# ---------------------------------------------------------------- the starfield and the dust

def starfield(seed=3):
    """A sky map: (direction unit vectors, colours) of the far stars."""
    rnd = random.Random(seed)
    dirs, cols = [], []
    for _ in range(260):
        z = rnd.uniform(-1, 1)
        a = rnd.uniform(0, 2 * math.pi)
        q = math.sqrt(1 - z * z)
        dirs.append((q * math.cos(a), q * math.sin(a), z))
        cols.append(rnd.choice([(255, 255, 255), (200, 220, 255), (255, 230, 200), (140, 150, 190), (110, 120, 160)]))
    return np.array(dirs), cols


def draw_stars(surf, stars, R, f, cx, cy, style):
    dirs, cols = stars
    D = dirs @ R                                        # world -> camera (R's columns: right, up, forward)
    h = surf.get_height()
    ok = D[:, 2] > 0.05
    z = np.where(ok, D[:, 2], 1)
    sx = (cx + D[:, 0] * f / z).astype(int)
    sy = (cy - D[:, 1] * f / z).astype(int)
    ok &= (sx >= 0) & (sx < W) & (sy >= 0) & (sy < h)
    fill = surf.fill
    for i in np.nonzero(ok)[0].tolist():
        fill(WIRE if style == "wire" else cols[i], (sx[i], sy[i], 1, 1))


# ---------------------------------------------------------------- the goods' little pictures

def _icon_paint(i, c):
    """Good i drawn on a 48x48 canvas c (the order of stargalaxy.GOODS)."""
    def P(*pts):
        return [(x, y) for x, y in pts]
    dark = (30, 30, 34)
    if i == 0:                                         # food: a loaf
        ellipse(c, (150, 95, 40), (4, 14, 40, 26))
        ellipse(c, (205, 145, 70), (6, 12, 36, 22))
        for x in (14, 22, 30):
            line(c, (150, 95, 40), (x, 16), (x + 5, 26), 3)
    elif i == 1:                                       # textiles: a bolt of cloth
        rect(c, (70, 110, 200), (8, 14, 30, 24))
        for y in (18, 24, 30):
            line(c, (110, 150, 235), (8, y), (38, y), 2)
        ellipse(c, (50, 85, 165), (32, 14, 12, 24))
        ellipse(c, (110, 150, 235), (35, 21, 6, 10))
    elif i == 2:                                       # radioactives: the trefoil
        circle(c, (240, 210, 40), (24, 24), 21)
        for k in range(3):
            a0 = math.radians(90 + k * 120)
            pts = [(24, 24)] + [(24 + 18 * math.cos(a0 + d), 24 - 18 * math.sin(a0 + d))
                                for d in np.linspace(-0.5, 0.5, 6)]
            poly(c, dark, pts)
        circle(c, (240, 210, 40), (24, 24), 6)
        circle(c, dark, (24, 24), 4)
    elif i == 3:                                       # robots: a head
        line(c, (150, 155, 165), (24, 4), (24, 12), 2)
        circle(c, (240, 80, 60), (24, 4), 3)
        rect(c, (150, 155, 165), (8, 12, 32, 28), border_radius=6)
        rect(c, (40, 44, 52), (12, 18, 24, 10), border_radius=3)
        circle(c, (90, 220, 255), (18, 23), 3)
        circle(c, (90, 220, 255), (30, 23), 3)
        rect(c, (90, 95, 105), (16, 32, 16, 4))
    elif i == 4:                                       # drinks: a bottle
        poly(c, (40, 140, 70), P((20, 4), (28, 4), (28, 14), (34, 20), (34, 44), (14, 44), (14, 20), (20, 14)))
        rect(c, (235, 225, 190), (15, 26, 18, 10))
        rect(c, (200, 60, 50), (20, 2, 8, 4))
    elif i == 5:                                       # luxuries: a crown
        poly(c, (235, 190, 50), P((6, 38), (6, 14), (15, 26), (24, 8), (33, 26), (42, 14), (42, 38)))
        rect(c, (200, 150, 30), (6, 36, 36, 6))
        for x, col in ((15, (220, 40, 60)), (24, (60, 120, 240)), (33, (40, 190, 90))):
            circle(c, col, (x, 31), 3)
    elif i == 6:                                       # stimulants: a capsule
        poly(c, (220, 50, 60), P((10, 30), (24, 16), (30, 22), (16, 36)))
        circle(c, (220, 50, 60), (13, 33), 5)
        poly(c, (240, 240, 240), P((24, 16), (32, 8), (38, 14), (30, 22)))
        circle(c, (240, 240, 240), (35, 11), 5)
    elif i == 7:                                       # computers: a chip
        for k in range(5):
            line(c, (190, 190, 200), (12 + k * 6, 4), (12 + k * 6, 44), 2)
            line(c, (190, 190, 200), (4, 12 + k * 6), (44, 12 + k * 6), 2)
        rect(c, (35, 40, 50), (9, 9, 30, 30))
        rect(c, (60, 180, 120), (16, 16, 16, 16), 2)
    elif i == 8:                                       # machinery: a gear
        pts = []
        for k in range(16):
            a0 = math.pi * 2 * k / 16
            r = 21 if k % 2 == 0 else 15
            pts.append((24 + r * math.cos(a0), 24 + r * math.sin(a0)))
        poly(c, (150, 160, 175), pts)
        circle(c, (95, 105, 120), (24, 24), 9)
        circle(c, (0, 0, 0, 0), (24, 24), 4)
    elif i in (9, 13, 14):                             # alloys (a stack), gold and platinum: bars
        col = {9: ((120, 135, 150), (165, 180, 195)), 13: ((210, 160, 40), (250, 215, 90)),
               14: ((175, 180, 190), (225, 230, 240))}[i]
        bars = ((6, 30), (22, 30), (14, 18)) if i == 9 else ((8, 24),)
        for x, y in bars:
            w = 20 if i == 9 else 32
            poly(c, col[0], P((x, y + 12), (x + w, y + 12), (x + w - 4, y), (x + 4, y)))
            poly(c, col[1], P((x + 4, y), (x + w - 4, y), (x + w - 7, y - 4), (x + 7, y - 4)))
    elif i == 10:                                      # firearms: a blaster
        poly(c, (70, 75, 85), P((4, 16), (36, 16), (40, 20), (40, 24), (22, 24), (18, 40), (8, 40), (10, 24), (4, 24)))
        rect(c, (240, 90, 40), (36, 18, 8, 4))
        rect(c, (110, 115, 125), (8, 18, 22, 3))
    elif i == 11:                                      # furs: a pelt
        for k in range(14):
            a0 = math.pi * 2 * k / 14
            circle(c, (120, 80, 45), (24 + 15 * math.cos(a0), 24 + 13 * math.sin(a0)), 7)
        ellipse(c, (160, 115, 70), (10, 12, 28, 24))
        for x in (16, 24, 32):
            line(c, (120, 80, 45), (x, 16), (x - 2, 32), 2)
    elif i == 12:                                      # minerals: rocks with a crystal
        poly(c, (115, 105, 95), P((4, 40), (10, 26), (22, 22), (28, 34), (22, 42)))
        poly(c, (90, 82, 75), P((22, 42), (28, 30), (40, 32), (44, 42)))
        poly(c, (150, 120, 200), P((26, 30), (30, 8), (36, 6), (36, 30)))
        poly(c, (190, 160, 240), P((30, 8), (33, 4), (36, 6)))
    else:                                              # gems: a cut stone
        poly(c, (80, 200, 240), P((10, 18), (16, 10), (32, 10), (38, 18), (24, 40)))
        poly(c, (170, 235, 255), P((16, 10), (24, 18), (32, 10)))
        poly(c, (40, 150, 200), P((10, 18), (24, 18), (24, 40)))
        poly(c, (120, 220, 250), P((24, 18), (38, 18), (24, 40)))


_icons = {}


def goods_icon(i, size, wire=False):
    """Good i's little picture, size pixels square: painted big, scaled down smoothly; the classic look
    turns it to green shades."""
    key = (i, int(size), wire)
    if key not in _icons:
        c = pygame.Surface((48, 48), pygame.SRCALPHA)
        _icon_paint(i, c)
        if wire:
            rgb = pygame.surfarray.pixels3d(c)
            lum = (rgb[..., 0] * 0.3 + rgb[..., 1] * 0.59 + rgb[..., 2] * 0.11) / 255.0
            lum = 0.35 + 0.65 * lum
            for k, v in enumerate(WIRE):
                rgb[..., k] = (lum * v).astype(np.uint8)
            del rgb
        _icons[key] = pygame.transform.smoothscale(c, (int(size), int(size)))
    return _icons[key]


# ---------------------------------------------------------------- the dashboard

YEL, RED, MAG, GRN, CYA = (240, 225, 40), (230, 40, 30), (230, 50, 230), (50, 230, 60), (60, 230, 240)
DH = H - VH
SC_X, SC_Y, SC_RX, SC_RY = W / 2, VH + 58, 80, 30          # the scanner ellipse
L_COL, R_COL = 68, W - 68
ROWS = 7
BH = (DH - 6) / ROWS


def bevel(s, r, light=(200, 204, 210), dark=(70, 72, 80), face=(120, 124, 132), w=3):
    x, y, ww, hh = r
    rect(s, face, r, w)
    for k in range(w):
        line(s, light, (x + k, y + k), (x + ww - 1 - k, y + k))
        line(s, light, (x + k, y + k), (x + k, y + hh - 1 - k))
        line(s, dark, (x + k, y + hh - 1 - k), (x + ww - 1 - k, y + hh - 1 - k))
        line(s, dark, (x + ww - 1 - k, y + k), (x + ww - 1 - k, y + hh - 1 - k))


class Dashboard:
    """The old layout: gauges left (FS AS FV CT LT AL) and right (SP RL DC 1-4), the scanner ellipse with
    its dashed grid in the middle, the compass in the corner. The frame and the grid are drawn once."""

    def __init__(self, modern):
        self.modern = modern
        self.f = font("DejaVuSansMono-Bold.ttf", 9)
        if modern:
            self.mag, self.yel, self.grn = (255, 170, 40), (255, 200, 60), (120, 230, 90)
            self.lab, self.frame, self.ell, self.dim, self.mark = CYA, YEL, RED, (150, 20, 15), WHITE
        else:
            self.mag = self.yel = self.grn = self.lab = self.frame = self.ell = self.mark = WIRE
            self.dim = WIRE_DIM
        self.bg = pygame.Surface((W, DH))
        self.strips = {}
        self.paint_bg()

    def paint_bg(self):
        s = self.bg
        m = self.modern
        s.fill((0, 0, 0))
        y0 = 0
        cx, cy, rx, ry = SC_X, SC_Y - VH, SC_RX, SC_RY
        for i, lab in enumerate(("FS", "AS", "FV", "CT", "LT", "AL")):
            y = y0 + 4 + i * BH
            if not HAT:
                s.blit(self.f.render(lab, True, self.lab), (3, y))
            line(s, (30, 70, 40) if m else (0, 120, 0), (20, y + BH - 2), (L_COL - 3, y + BH - 2))
        for i, lab in enumerate(("SP", "RL", "DC", "1", "2", "3", "4")):
            y = y0 + 3 + i * BH
            if not HAT:
                img = self.f.render(lab, True, self.lab if i < 3 else self.mag)
                s.blit(img, (W - 3 - img.get_width(), y))
            line(s, (30, 70, 40) if m else (0, 120, 0), (R_COL + 3, y + BH - 2), (W - 20, y + BH - 2))
        if m:
            e = pygame.Surface((2 * rx + 20, 2 * ry + 20))
            for k in range(5):
                ellipse(e, (5 + k * 2, 1, 1), e.get_rect().inflate(-k * 8, -k * 4))
            s.blit(e, (cx - rx - 10, cy - ry - 10), special_flags=pygame.BLEND_ADD)
            for k in range(-6, 7):
                for j in range(-3, 4):
                    x, y = cx + k * rx / 7, cy + j * ry / 4
                    if ((x - cx) / rx) ** 2 + ((y - cy) / ry) ** 2 < 0.95:
                        s.set_at((int(x), int(y)), (120, 24, 18))

        def dashed(a, b, col, n=9):
            for k in range(0, n, 2):
                p = (a[0] + (b[0] - a[0]) * k / n, a[1] + (b[1] - a[1]) * k / n)
                q = (a[0] + (b[0] - a[0]) * (k + 1) / n, a[1] + (b[1] - a[1]) * (k + 1) / n)
                line(s, col, p, q, 2 if m else 1)
        dim = self.dim
        for t in (-0.5, 0, 0.5):
            dashed((cx + rx * t * 0.62, cy - ry * 0.98), (cx + rx * t * 1.05, cy + ry * 0.98), dim)
        for t in (-0.85, 0.85):
            dashed((cx + rx * t * 0.62, cy - ry * 0.6), (cx + rx * t * 0.95, cy + ry * 0.75), dim, 7)
        dashed((cx - rx * 0.92, cy), (cx + rx * 0.92, cy), dim, 15)
        dashed((cx - rx * 0.78, cy - ry * 0.55), (cx + rx * 0.78, cy - ry * 0.55), dim, 13)
        dashed((cx - rx * 0.78, cy + ry * 0.55), (cx + rx * 0.78, cy + ry * 0.55), dim, 13)
        ellipse(s, self.ell, (cx - rx, cy - ry, 2 * rx, 2 * ry), 2 if m else 1)
        lines(s, (60, 140, 60) if m else WIRE_DIM, False,
              [(cx - rx * 0.62, cy - ry * 0.95), (cx, cy), (cx + rx * 0.62, cy - ry * 0.95)])
        L, R = L_COL, R_COL
        if m:
            bevel(s, (0, 0, L + 3, DH))
            bevel(s, (R - 3, 0, W - R + 3, DH))
            line(s, (90, 92, 100), (R, 3 * BH + 3), (W - 3, 3 * BH + 3), 2)
            for k in range(6):
                c = mix((60, 62, 70), (220, 224, 230), 1 - abs(k - 2) / 3)
                arc(s, c, (cx - rx - 6, cy - ry + 4 + k, 2 * rx + 12, 2 * ry + 4), math.pi * 1.02, math.pi * 1.98, 1)
            ccx, ccy = R - 18, 18
            circle(s, (10, 10, 30), (ccx, ccy), 14)
            circle(s, (60, 90, 220), (ccx, ccy), 14, 2)
            circle(s, (200, 200, 220), (ccx, ccy), 12, 1)
            for d in range(-10, 11, 3):
                s.set_at((ccx + d, ccy), (120, 140, 255))
                s.set_at((ccx, ccy + d), (120, 140, 255))
            for k in range(4):
                line(s, mix((200, 204, 210), (20, 20, 26), k / 3), (L + 3, k), (R - 4, k))
        else:
            fr = self.frame
            rect(s, fr, (0, 0, W, DH), 1)
            line(s, fr, (L, 0), (L, DH))
            line(s, fr, (R, 0), (R, DH))
            circle(s, (0, 0, 0), (R - 14, 13), 12)
            circle(s, fr, (R - 14, 13), 12, 1)
            line(s, fr, (R - 28, 1), (R - 28, 25))
            line(s, fr, (R - 28, 25), (R, 25))

    def compass_centre(self):
        return (R_COL - 18, VH + 18) if self.modern else (R_COL - 14, VH + 13)

    def bar(self, s, x, y, w, v, col):
        v = max(0.0, min(1.0, v))
        if v <= 0:
            return
        if self.modern:
            key = (col, w)
            strip = self.strips.get(key)
            if strip is None:                    # a gradient strip, made once per colour
                strip = pygame.Surface((w, int(BH - 5)))
                strip.fill((0, 0, 0))
                for k in range(0, w, 2):
                    line(strip, mix(shade(col, 0.45), col, k / max(1, w) * 1.4), (k, 0), (k, BH - 6), 2)
                line(strip, mix(col, WHITE, 0.5), (0, 0), (w - 1, 0))
                self.strips[key] = strip
            s.blit(strip, (x, y), (0, 0, int(w * v), strip.get_height()))
        else:
            rect(s, col, (x, y, w * v, BH - 5))

    def draw(self, s, st):
        """st: fs as fv ct lt al sp rl dc (rl, dc -1..1), en [4], blips [(x, y, h, col)] in -1..1 of the range,
        compass (x, y, front) or None, safe, missiles, warn."""
        s.blit(self.bg, (0, VH))
        y0 = VH
        mag, yel, grn = self.mag, self.yel, self.grn
        for i, (key, col) in enumerate((("fs", mag), ("as", mag), ("fv", yel), ("ct", grn), ("lt", grn),
                                        ("al", yel))):
            v = st.get(key, 0)
            c = RED if key in ("fs", "as") and v < 0.25 and int(st.get("t", 0) * 4) % 2 else col
            self.bar(s, 20, y0 + 6 + i * BH, L_COL - 24, v, c)
        for i in range(st.get("missiles", 0)):
            rect(s, self.grn, (6 + i * 12, H - 12, 9, 8))
        self.bar(s, R_COL + 3, y0 + 5, W - 24 - R_COL, st.get("sp", 0), yel)
        for i, key in enumerate(("rl", "dc")):
            y = y0 + 3 + (i + 1) * BH
            x = R_COL + 3 + (W - 23 - R_COL) * (0.5 + 0.5 * max(-1, min(1, st.get(key, 0))))
            line(s, self.mark, (x, y + 1), (x, y + BH - 3), 2)
        for i, v in enumerate(st.get("en", (1, 1, 1, 1))):
            self.bar(s, R_COL + 3, y0 + 5 + (i + 3) * BH, W - 24 - R_COL, v, mag)
        cx, cy, rx, ry = SC_X, SC_Y, SC_RX, SC_RY
        for bx, by, h, col in st.get("blips", ()):
            px, py = cx + bx * rx, cy + by * ry
            ty = py - h * ry * 1.2
            line(s, col, (px, py), (px, ty), 1)
            rect(s, col, (px - 2, ty - 1, 5, 3))
        comp = st.get("compass")
        ccx, ccy = self.compass_centre()
        if comp:
            x, y, front = comp
            p = (ccx + x * 9, ccy - y * 9)
            if self.modern:
                circle(s, (230, 40, 40) if front else (255, 255, 255), p, 3, 0 if front else 1)
            else:
                rect(s, WIRE, (p[0] - 1, p[1] - 1, 3, 3), 0 if front else 1)
        if st.get("safe"):
            img = font("DejaVuSansMono-Bold.ttf", 13).render("S", True, self.mark)
            s.blit(img, (R_COL - 4 - img.get_width(), H - 2 - img.get_height()))


def stardust_init(n=80, seed=5):
    """Dust all round the ship, in the ship's own frame (x right, y up, z ahead), in a box that wraps."""
    rnd = random.Random(seed)
    return [[rnd.uniform(-DX, DX), rnd.uniform(-DY, DY), rnd.uniform(-DZ, DZ)] for _ in range(n)]


DX, DY, DZ = 700.0, 520.0, 1600.0


def stardust(surf, dust, dt, speed, roll, pitch, yaw, f, cx, cy, style, V=None):
    """The dust drifts by: turns against the ship (roll about z, pitch about x, yaw about y), slides back by
    the speed, wraps round the box; drawn through the view V (the camera's axes in the ship's frame - the
    rear and side views see it pass the other way)."""
    h = surf.get_height()
    cr, sr = math.cos(roll * dt), math.sin(roll * dt)
    cp, sp = math.cos(pitch * dt), math.sin(pitch * dt)
    cy_, sy_ = math.cos(-yaw * dt), math.sin(-yaw * dt)
    col = WIRE_DIM if style == "wire" else (160, 175, 220)
    if V is None:
        V = np.eye(3)
    (a0, a1, a2), (b0, b1, b2), (c0, c1, c2) = V.T.tolist()      # rows: camera x, y, z in ship axes
    for d in dust:
        x, y, z = d
        ox, oy, oz = a0 * x + a1 * y + a2 * z, b0 * x + b1 * y + b2 * z, c0 * x + c1 * y + c2 * z
        x, y = x * cr - y * sr, x * sr + y * cr
        y, z = y * cp - z * sp, y * sp + z * cp
        x, z = x * cy_ + z * sy_, -x * sy_ + z * cy_
        z -= speed * dt
        wrapped = False
        for i, (v, lim) in enumerate(((x, DX), (y, DY), (z, DZ))):
            if v < -lim or v > lim:
                wrapped = True
        if wrapped:
            x = (x + DX) % (2 * DX) - DX
            y = (y + DY) % (2 * DY) - DY
            z = (z + DZ) % (2 * DZ) - DZ
        d[:] = [x, y, z]
        qx, qy, qz = a0 * x + a1 * y + a2 * z, b0 * x + b1 * y + b2 * z, c0 * x + c1 * y + c2 * z
        if qz < 40:
            continue
        px, py = cx + qx * f / qz, cy - qy * f / qz
        if 0 <= px < W and 0 <= py < h:
            if not wrapped and oz > 40:
                ox_, oy_ = cx + ox * f / oz, cy - oy * f / oz
                if abs(px - ox_) + abs(py - oy_) < 40:
                    line(surf, col, (ox_, oy_), (px, py))
                    continue
            surf.fill(col, (int(px), int(py), 1, 1))

