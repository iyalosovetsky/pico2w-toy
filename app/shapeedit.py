"""SERIAL's shape editor: circles, ellipses, rectangles (sharp or rounded), arcs and lines drawn with
the keyboard. A drawing is an SVG file (~/gcode/shapes/NAME.svg - opens in any viewer or Inkscape) with
its G-code next to it (NAME.nc); both are written by themselves a second after each change.

The canvas is the work area in millimetres with the work zero at the bottom left. A cross-hair
moves on a grid (arrows; held - faster and faster); a tool key starts a shape and Enter places its points,
"n" opens the numbers of the selected shape for exact values, "p" the machining parameters
(depth, step down, feeds, tool, which side of the line). Saving writes ~/gcode/shapes/NAME.nc,
which SERIAL then opens: the toolpath view, the bounds, the run.
"""
import json
import math
import os
import re
import time
import xml.etree.ElementTree as ET

import svgimport

import pygame

SHAPES_DIR = os.path.expanduser("~/gcode/shapes")
DEFAULT = "shape"           # a new drawing's name until "Зберегти як" (then shape-2, shape-3 ... if taken)
AUTOSAVE_S = 1.0
GRID_STEPS = [0.1, 0.5, 1.0, 2.0, 5.0, 10.0]
SIDES = ["по лінії", "зовні", "всередині", "карман"]     # карман (a pocket): all the inside cleared
POCKET = SIDES[3]
TOOLS = {"c": "circle", "e": "ellipse", "r": "rect", "a": "arc", "l": "line"}
NAMES = {"circle": "коло", "ellipse": "еліпс", "rect": "прямокутник", "arc": "дуга", "line": "лінія",
         "poly": "контур"}           # poly: a polyline imported from an SVG (curves as chords)
# the points each tool asks for, in order
STEPS = {"circle": ["центр", "точка на колі"], "ellipse": ["центр", "кут рамки (rx, ry)"],
         "rect": ["перший кут", "протилежний кут"], "arc": ["центр", "початок", "кінець"],
         "line": ["початок", "кінець"]}
# the fields of each shape in the numbers form: (key, label)
FIELDS = {"circle": [("cx", "Центр X"), ("cy", "Центр Y"), ("r", "Радіус"), ("side", "Сторона")],
          "ellipse": [("cx", "Центр X"), ("cy", "Центр Y"), ("rx", "Піввісь X"), ("ry", "Піввісь Y"),
                      ("side", "Сторона")],
          "rect": [("x", "Кут X"), ("y", "Кут Y"), ("w", "Ширина"), ("h", "Висота"), ("rad", "Радіус кутів"),
                   ("side", "Сторона")],
          "arc": [("cx", "Центр X"), ("cy", "Центр Y"), ("r", "Радіус"), ("a0", "Початок, °"), ("a1", "Кінець, °"),
                  ("ccw", "Напрям")],
          "line": [("x0", "Початок X"), ("y0", "Початок Y"), ("x1", "Кінець X"), ("y1", "Кінець Y")]}
PARAMS = [("safe_z", "Безпечна висота Z", 5.0), ("depth", "Глибина, мм", 1.0), ("step", "Крок по глибині", 0.5),
          ("feed", "Подача XY, мм/хв", 600.0), ("plunge", "Подача Z, мм/хв", 200.0),
          ("tool", "Діаметр фрези", 3.175), ("stepover", "Карман: крок, % фрези", 40.0),
          ("spindle", "Оберти S (0 - без M3)", 12000.0),
          ("width", "Поле, ширина X", 200.0), ("height", "Поле, висота Y", 200.0)]


HELP = [
    "# Хрестик",
    "Стрілки - на крок сітки; утримання - повторює, через 1,5 с утричі швидше.",
    "g / G - крок сітки 0,1 / 0,5 / 1 / 2 / 5 / 10 мм (підбирається сам під масштаб).",
    "+ / - - масштаб (навколо хрестика), 0 - усе поле, h - хрестик у нуль (0, 0).",
    "# Фігури",
    "c - коло: центр, точка на колі. e - еліпс: центр, кут рамки.",
    "r - прямокутник: два кути (радіус кутів - у числах).",
    "a - дуга: центр, початок, кінець; d - напрям. l - лінія: два кінці.",
    "Enter - поставити точку, Backspace - прибрати останню, Esc - кінець інструмента.",
    "# Готова фігура",
    "Наведіть хрестик на лінію фігури (вона жовтіє) або Tab - хрестик на наступну фігуру (Shift+Tab - попередню).",
    "Enter - редагувати точки, як при малюванні: квадратики - точки фігури (кути, центр, точка радіуса, кінці);",
    "  хрестик на точку (Tab - наступна), Enter - взяти, стрілки - тягнути, Enter - покласти, Esc - повернути як було.",
    "  Центр (або середина) переносить усю фігуру. Esc - вийти з редагування.",
    "Пробіл (або n) - числа: прив'язка X / Y - лівий нижній кут (описаного прямокутника для кола й еліпса) або центр,",
    "  розміри, радіус кутів, кути дуги; фігура змінюється наживо, s або Enter на останньому - готово, Esc - ні.",
    "  Обробка (замкнені фігури): по лінії / зовні / всередині (фреза зсунута на радіус) / карман - вибрати все всередині:",
    "  кільця від центру назовні з кроком «Карман: крок, % фрези» (p), останнє - по стінці.",
    "  Глибина - своя для фігури (0 - загальна з p); над фігурою вгорі видно ↓глибину.",
    "Del / Backspace - видалити фігуру, u - скасувати останню зміну.",
    "# Файл",
    "p - обробка: безпечна Z, загальна глибина, крок по глибині, подачі, діаметр фрези (Ø угорі), крок карману, оберти, поле.",
    "Креслення - ~/gcode/shapes/НАЗВА.svg (відкривається будь-де, напр. в Inkscape) і поруч НАЗВА.nc (G-code).",
    "Зберігається саме за секунду після кожної зміни: ● - ще ні, ✓ - збережено. Нове креслення - shape (shape-2 …).",
    "s - зберегти як: нова назва (робоче shape просто перейменовується). o - відкрити: список креслень, «+ нове».",
    "i - імпорт SVG (з Inkscape тощо; ~/gcode, ~/Downloads, ~): фігури додаються лівим нижнім кутом у хрестик,",
    "  у справжніх мм (одиниці й viewBox файлу); криві й складні фігури стають контурами (ламана, хорди ~0,3 мм).",
    "  Контур: Enter - точки (середина - перенести, правий верхній кут - масштаб), пробіл - X / Y, ширина, висота.",
    "Esc двічі (за 2 с) - вийти: креслення збережене, його G-code відкривається в SERIAL (F4 - перегляд, межі, запуск).",
    "Редактор відкриває креслення відкритого в SERIAL файлу, інакше останнє.",
]


def fmt(v):
    return ("%.3f" % v).rstrip("0").rstrip(".") if isinstance(v, float) else str(v)


# ---------------------------------------------------------------- geometry

def closed(sh):
    return sh["type"] in ("circle", "ellipse", "rect")


def offset(sh, tool):
    """The shape moved half the tool's width outwards / inwards (closed shapes; side)."""
    side = sh.get("side", SIDES[0])
    if not closed(sh) or side == SIDES[0] or tool <= 0:
        return dict(sh)
    o = tool / 2 if side == SIDES[1] else -tool / 2     # inside / a pocket: its last ring
    s = dict(sh)
    if sh["type"] == "circle":
        s["r"] = max(0.01, sh["r"] + o)
    elif sh["type"] == "ellipse":
        s["rx"], s["ry"] = max(0.01, sh["rx"] + o), max(0.01, sh["ry"] + o)
    else:
        s["x"], s["y"] = sh["x"] - o, sh["y"] - o
        s["w"], s["h"] = max(0.01, sh["w"] + 2 * o), max(0.01, sh["h"] + 2 * o)
        s["rad"] = max(0.0, sh.get("rad", 0.0) + o)
    return s


def norm_rect(sh):
    rad = min(max(0.0, sh.get("rad", 0.0)), sh["w"] / 2, sh["h"] / 2)
    return sh["x"], sh["y"], sh["w"], sh["h"], rad


def arc_sweep(sh):
    a0, a1 = math.radians(sh["a0"]), math.radians(sh["a1"])
    sw = a1 - a0
    if sh.get("ccw", "проти год.") == "проти год.":
        while sw <= 0:
            sw += 2 * math.pi
    else:
        while sw >= 0:
            sw -= 2 * math.pi
    return a0, sw


def points(sh, n=48):
    """The shape as a polyline (for drawing)."""
    t = sh["type"]
    if t == "poly":
        return [tuple(p) for p in sh["pts"]]
    if t == "circle":
        return [(sh["cx"] + sh["r"] * math.cos(2 * math.pi * k / n), sh["cy"] + sh["r"] * math.sin(2 * math.pi * k / n))
                for k in range(n + 1)]
    if t == "ellipse":
        return [(sh["cx"] + sh["rx"] * math.cos(2 * math.pi * k / n), sh["cy"] + sh["ry"] * math.sin(2 * math.pi * k / n))
                for k in range(n + 1)]
    if t == "line":
        return [(sh["x0"], sh["y0"]), (sh["x1"], sh["y1"])]
    if t == "arc":
        a0, sw = arc_sweep(sh)
        m = max(2, int(abs(sw) / (2 * math.pi) * n))
        return [(sh["cx"] + sh["r"] * math.cos(a0 + sw * k / m), sh["cy"] + sh["r"] * math.sin(a0 + sw * k / m))
                for k in range(m + 1)]
    x, y, w, h, rad = norm_rect(sh)
    if rad <= 0:
        return [(x, y), (x, y + h), (x + w, y + h), (x + w, y), (x, y)]
    out = []
    for cx, cy, a in ((x + rad, y + h - rad, 180), (x + w - rad, y + h - rad, 90), (x + w - rad, y + rad, 0),
                      (x + rad, y + rad, -90)):
        for k in range(7):                       # each corner clockwise, 90 degrees
            ang = math.radians(a - 90 * k / 6)
            out.append((cx + rad * math.cos(ang), cy + rad * math.sin(ang)))
    out.append(out[0])
    return out


def bounds(shapes):
    xs, ys = [], []
    for sh in shapes:
        for x, y in points(sh, 24):
            xs.append(x)
            ys.append(y)
    return (min(xs), min(ys), max(xs), max(ys)) if xs else None


# ---------------------------------------------------------------- G-code

def path_moves(sh, reverse=False):
    """(start point, [G-code moves]) of one pass along a shape; open shapes can go backwards."""
    t = sh["type"]
    f = "%.3f"
    if t == "poly":
        pts = sh["pts"][::-1] if reverse and not sh.get("closed") else sh["pts"]
        return tuple(pts[0]), ["G1 X%s Y%s" % (f % x, f % y) for x, y in pts[1:]]
    if t == "circle":
        cx, cy, r = sh["cx"], sh["cy"], sh["r"]
        return (cx - r, cy), ["G2 X%s Y%s I%s J0" % (f % (cx - r), f % cy, f % r)]
    if t == "ellipse":
        n = 96
        pts = [(sh["cx"] + sh["rx"] * math.cos(-2 * math.pi * k / n), sh["cy"] + sh["ry"] * math.sin(-2 * math.pi * k / n))
               for k in range(n + 1)]
        return pts[0], ["G1 X%s Y%s" % (f % x, f % y) for x, y in pts[1:]]
    if t == "line":
        a, b = (sh["x0"], sh["y0"]), (sh["x1"], sh["y1"])
        if reverse:
            a, b = b, a
        return a, ["G1 X%s Y%s" % (f % b[0], f % b[1])]
    if t == "arc":
        a0, sw = arc_sweep(sh)
        cx, cy, r = sh["cx"], sh["cy"], sh["r"]
        p0 = (cx + r * math.cos(a0), cy + r * math.sin(a0))
        p1 = (cx + r * math.cos(a0 + sw), cy + r * math.sin(a0 + sw))
        ccw = sw > 0
        if reverse:
            p0, p1, ccw = p1, p0, not ccw
        return p0, ["%s X%s Y%s I%s J%s" % ("G3" if ccw else "G2", f % p1[0], f % p1[1], f % (cx - p0[0]),
                                           f % (cy - p0[1]))]
    x, y, w, h, rad = norm_rect(sh)                 # clockwise from the left side
    if rad <= 0:
        return (x, y), ["G1 X%s Y%s" % (f % px, f % py) for px, py in ((x, y + h), (x + w, y + h), (x + w, y), (x, y))]
    m = ["G1 X%s Y%s" % (f % x, f % (y + h - rad)),
         "G2 X%s Y%s I%s J0" % (f % (x + rad), f % (y + h), f % rad),
         "G1 X%s Y%s" % (f % (x + w - rad), f % (y + h)),
         "G2 X%s Y%s I0 J%s" % (f % (x + w), f % (y + h - rad), f % -rad),
         "G1 X%s Y%s" % (f % (x + w), f % (y + rad)),
         "G2 X%s Y%s I%s J0" % (f % (x + w - rad), f % y, f % -rad),
         "G1 X%s Y%s" % (f % (x + rad), f % y),
         "G2 X%s Y%s I0 J%s" % (f % x, f % (y + rad), f % rad)]
    return (x, y + rad), m


def inset(sh, k):
    """The closed shape shrunk by k all round, or None when nothing is left."""
    t = sh["type"]
    s = dict(sh)
    if t == "circle":
        if sh["r"] - k <= 1e-6:
            return None
        s["r"] = sh["r"] - k
    elif t == "ellipse":
        if min(sh["rx"], sh["ry"]) - k <= 1e-6:
            return None
        s["rx"], s["ry"] = sh["rx"] - k, sh["ry"] - k
    else:
        if min(sh["w"], sh["h"]) - 2 * k <= 1e-6:
            return None
        s.update(x=sh["x"] + k, y=sh["y"] + k, w=sh["w"] - 2 * k, h=sh["h"] - 2 * k, rad=max(0.0, sh.get("rad", 0.0) - k))
    s["side"] = SIDES[0]
    return s


def pocket(sh, tool, stepover):
    """A pocket's passes, inside out: [the centre line (a "line" shape) or None, rings...]; the last ring is
    the wall (half the tool in from the line). The centre line clears what the innermost ring leaves."""
    r = tool / 2
    step = max(0.05, tool * min(max(stepover, 5.0), 100.0) / 100.0)
    rings, k = [], r
    while True:
        ring = inset(sh, k)
        if ring is None:
            break
        rings.append(ring)
        k += step
    t = sh["type"]
    # the centre: what the tool reaches when the shape is shrunk by the tool's radius to a line / a point
    if t == "rect":
        w, h = sh["w"] - 2 * r, sh["h"] - 2 * r
        cx, cy = sh["x"] + sh["w"] / 2, sh["y"] + sh["h"] / 2
    elif t == "ellipse":
        w, h = 2 * (sh["rx"] - r), 2 * (sh["ry"] - r)
        cx, cy = sh["cx"], sh["cy"]
    else:
        w = h = 2 * (sh["r"] - r)
        cx, cy = sh["cx"], sh["cy"]
    half = max(0.0, (max(w, h) - min(w, h)) / 2) if min(w, h) >= 0 else 0.0
    if w >= h:
        centre = {"type": "line", "x0": cx - half, "y0": cy, "x1": cx + half, "y1": cy}
    else:
        centre = {"type": "line", "x0": cx, "y0": cy - half, "x1": cx, "y1": cy + half}
    return centre, rings[::-1]


def gcode(shapes, p, title="shapes"):
    """The whole job: each shape cut in passes down to its depth (its own, else the common one), lifting to
    the safe height between shapes; a pocket clears its inside ring by ring, from the centre out."""
    f = "%.3f"
    step = max(0.01, abs(p["step"]))
    out = ["(pico2w-toy shape editor: %s, %d shapes, depth %s, step %s, tool %s)" %
           (title, len(shapes), fmt(abs(p["depth"])), fmt(step), fmt(p["tool"])), "G21 G90 G17",
           "G0 Z%s" % (f % p["safe_z"])]
    if p["spindle"] > 0:
        out.append("M3 S%d" % p["spindle"])
        out.append("G4 P2")
    for i, sh in enumerate(shapes):
        depth = abs(sh.get("depth") or 0.0) or abs(p["depth"])
        n = max(1, int(math.ceil(depth / step - 1e-9)))
        levels = [min(depth, step * (j + 1)) for j in range(n)]
        out.append("(%d: %s, depth %s%s)" % (i + 1, NAMES[sh["type"]], fmt(depth),
                                            ", pocket" if sh.get("side") == POCKET else ""))
        if sh.get("side") == POCKET and closed(sh):
            centre, rings = pocket(sh, p["tool"], p.get("stepover", 40.0))
            a = (centre["x0"], centre["y0"])
            out.append("G0 X%s Y%s" % (f % a[0], f % a[1]))
            for z in levels:
                out.append("G1 X%s Y%s F%d" % (f % a[0], f % a[1], p["feed"]))   # back over the cleared floor
                out.append("G1 Z%s F%d" % (f % -z, p["plunge"]))
                out.append("G1 X%s Y%s F%d" % (f % centre["x1"], f % centre["y1"], p["feed"]))
                for ring in rings:
                    start, moves = path_moves(ring)
                    out.append("G1 X%s Y%s" % (f % start[0], f % start[1]))
                    out += moves
            out.append("G0 Z%s" % (f % p["safe_z"]))
            continue
        geo = offset(sh, p["tool"])
        start, _ = path_moves(geo)
        out.append("G0 X%s Y%s" % (f % start[0], f % start[1]))
        for k, z in enumerate(levels):
            rev = not closed(geo) and k % 2 == 1        # open shapes: back and forth
            pos, moves = path_moves(geo, rev)
            out.append("G1 Z%s F%d" % (f % -z, p["plunge"]))
            out.append(moves[0] + " F%d" % p["feed"])
            out += moves[1:]
        out.append("G0 Z%s" % (f % p["safe_z"]))
    if p["spindle"] > 0:
        out.append("M5")
    out.append("G0 X0 Y0")
    return out


def safe_name(s):
    s = re.sub(r"[^\w.-]+", "_", s.strip()).strip("._")
    for ext in (".svg", ".nc", ".shapes.json"):
        if s.lower().endswith(ext):
            s = s[:-len(ext)]
    return s or DEFAULT


def doc_path(name):
    return os.path.join(SHAPES_DIR, safe_name(name) + ".svg")


def untitled(name):
    return re.fullmatch(re.escape(DEFAULT) + r"(-\d+)?", name) is not None


def free_untitled():
    """shape, else shape-2, shape-3 ... - the first name with no drawing yet."""
    n = 1
    while True:
        name = DEFAULT if n == 1 else "%s-%d" % (DEFAULT, n)
        if not os.path.exists(doc_path(name)):
            return name
        n += 1


def svg_text(shapes, params):
    """The drawing as SVG in millimetres; y goes up as on the machine (a flipping group)."""
    w, h = params.get("width", 200.0), params.get("height", 200.0)
    f = lambda v: fmt(round(float(v), 4))
    out = ['<?xml version="1.0" encoding="UTF-8"?>',
           '<svg xmlns="http://www.w3.org/2000/svg" width="%smm" height="%smm" viewBox="0 0 %s %s">' % (f(w), f(h), f(w), f(h)),
           '<metadata id="pico2w-toy">%s</metadata>' % json.dumps(params, ensure_ascii=False).replace("&", "&amp;").replace("<", "&lt;"),
           '<g id="shapes" transform="translate(0,%s) scale(1,-1)" fill="none" stroke="#0080ff" stroke-width="0.3">' % f(h)]
    for sh in shapes:
        t = sh["type"]
        side = ' data-side="%s"' % sh.get("side", SIDES[0]) if closed(sh) else ""
        if sh.get("depth"):
            side += ' data-depth="%s"' % f(sh["depth"])
        if t == "circle":
            out.append('<circle cx="%s" cy="%s" r="%s"%s/>' % (f(sh["cx"]), f(sh["cy"]), f(sh["r"]), side))
        elif t == "ellipse":
            out.append('<ellipse cx="%s" cy="%s" rx="%s" ry="%s"%s/>' % (f(sh["cx"]), f(sh["cy"]), f(sh["rx"]),
                                                                         f(sh["ry"]), side))
        elif t == "rect":
            rad = min(sh.get("rad", 0.0), sh["w"] / 2, sh["h"] / 2)
            out.append('<rect x="%s" y="%s" width="%s" height="%s" rx="%s" ry="%s"%s/>' % (
                f(sh["x"]), f(sh["y"]), f(sh["w"]), f(sh["h"]), f(rad), f(rad), side))
        elif t == "poly":
            pts = sh["pts"][:-1] if sh.get("closed") and len(sh["pts"]) > 2 and sh["pts"][0] == sh["pts"][-1] else sh["pts"]
            out.append('<%s points="%s"%s/>' % ("polygon" if sh.get("closed") else "polyline",
                                                " ".join("%s,%s" % (f(x), f(y)) for x, y in pts), side))
        elif t == "line":
            out.append('<line x1="%s" y1="%s" x2="%s" y2="%s"%s/>' % (f(sh["x0"]), f(sh["y0"]), f(sh["x1"]), f(sh["y1"]),
                                                                    side))
        else:
            a0, sw = arc_sweep(sh)
            cx, cy, r = sh["cx"], sh["cy"], sh["r"]
            p0 = (cx + r * math.cos(a0), cy + r * math.sin(a0))
            p1 = (cx + r * math.cos(a0 + sw), cy + r * math.sin(a0 + sw))
            data = json.dumps({k: sh[k] for k in ("cx", "cy", "r", "a0", "a1", "ccw")}, ensure_ascii=False)
            out.append('<path d="M %s %s A %s %s 0 %d %d %s %s" data-arc=\'%s\'%s/>' % (
                f(p0[0]), f(p0[1]), f(r), f(r), 1 if abs(sw) > math.pi else 0, 1 if sw > 0 else 0,
                f(p1[0]), f(p1[1]), data, side))
    out += ["</g>", "</svg>"]
    return "\n".join(out) + "\n"


def save(name, shapes, params):
    """NAME.svg (the drawing) and NAME.nc (its G-code); returns the .nc path."""
    os.makedirs(SHAPES_DIR, exist_ok=True)
    base = os.path.join(SHAPES_DIR, safe_name(name))
    for ext, data in ((".svg", svg_text(shapes, params)),
                      (".nc", "\n".join(gcode(shapes, params, os.path.basename(base))) + "\n")):
        tmp = base + ext + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            fh.write(data)
        os.replace(tmp, base + ext)                     # never half a file
    return base + ".nc"


def remove(name):
    for ext in (".svg", ".nc"):
        try:
            os.remove(os.path.join(SHAPES_DIR, safe_name(name) + ext))
        except OSError:
            pass


def load(path):
    """(shapes, params) from our SVG (or a plain one: circle / ellipse / rect / line), or an old .shapes.json."""
    if path.endswith(".json"):
        with open(path, encoding="utf-8") as fh:
            d = json.load(fh)
        return d.get("shapes", []), d.get("params", {})
    root = ET.parse(path).getroot()
    ns = "{http://www.w3.org/2000/svg}"
    params, ours = {}, False
    for el in root.iter(ns + "metadata"):
        if el.get("id") == "pico2w-toy" and el.text:
            params, ours = json.loads(el.text), True
    if not ours:                                        # drawn elsewhere: units, transforms, curves
        return svgimport.import_svg(path), {}
    vb = (root.get("viewBox") or "").split()
    height = float(vb[3]) if len(vb) == 4 else float(re.sub(r"[^\d.]", "", root.get("height", "200")) or 200)
    flip = (lambda y: y) if ours else (lambda y: height - y)   # a foreign SVG has y going down
    num = lambda el, k, d=0.0: float(re.sub(r"[^\d.eE+-]", "", el.get(k, str(d))) or d)
    shapes = []
    for el in root.iter():
        tag = el.tag.replace(ns, "")
        side = el.get("data-side", SIDES[0])
        if tag == "circle":
            shapes.append({"type": "circle", "cx": num(el, "cx"), "cy": flip(num(el, "cy")), "r": num(el, "r"), "side": side})
        elif tag == "ellipse":
            shapes.append({"type": "ellipse", "cx": num(el, "cx"), "cy": flip(num(el, "cy")), "rx": num(el, "rx"),
                           "ry": num(el, "ry"), "side": side})
        elif tag == "rect":
            y = num(el, "y") if ours else height - num(el, "y") - num(el, "height")
            shapes.append({"type": "rect", "x": num(el, "x"), "y": y, "w": num(el, "width"), "h": num(el, "height"),
                           "rad": num(el, "rx"), "side": side})
        elif tag == "line":
            shapes.append({"type": "line", "x0": num(el, "x1"), "y0": flip(num(el, "y1")), "x1": num(el, "x2"),
                           "y1": flip(num(el, "y2"))})
        elif tag == "path" and el.get("data-arc"):
            d = json.loads(el.get("data-arc"))
            d["type"] = "arc"
            shapes.append(d)
        elif tag in ("polyline", "polygon"):
            v = [float(x) for x in re.findall(r"[-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?", el.get("points") or "")]
            pts = [[x, y] for x, y in zip(v[0::2], v[1::2])]
            if tag == "polygon" and pts:
                pts.append(list(pts[0]))
            shapes.append({"type": "poly", "pts": pts, "closed": tag == "polygon"})
        else:
            continue
        if el.get("data-depth"):
            shapes[-1]["depth"] = float(el.get("data-depth"))
    return shapes, params


def import_sources():
    """SVG files to import from: ~/gcode (and its folders), ~/Downloads, home - newest first."""
    home = os.path.expanduser("~")
    found = {}
    for d in (os.path.join(home, "gcode"), os.path.join(home, "Downloads"), home):
        try:
            entries = os.listdir(d)
        except OSError:
            continue
        for f in entries:
            full = os.path.join(d, f)
            if f.lower().endswith(".svg"):
                found[full] = full
            elif d.endswith("gcode") and os.path.isdir(full) and not f.startswith("."):
                try:
                    for g in os.listdir(full):
                        if g.lower().endswith(".svg"):
                            found[os.path.join(full, g)] = os.path.join(full, g)
                except OSError:
                    pass
    items = [(p.replace(home, "~"), p) for p in found]
    return sorted(items, key=lambda kv: os.path.getmtime(kv[1]), reverse=True)


def drawings():
    """The saved drawings, newest first: [(name, path)] (.svg, and old .shapes.json without an .svg)."""
    try:
        files = os.listdir(SHAPES_DIR)
    except OSError:
        return []
    out = {}
    for f in files:
        if f.endswith(".svg"):
            out[f[:-4]] = os.path.join(SHAPES_DIR, f)
        elif f.endswith(".shapes.json") and f[:-12] + ".svg" not in files:
            out[f[:-12]] = os.path.join(SHAPES_DIR, f)
    return sorted(out.items(), key=lambda kv: os.path.getmtime(kv[1]), reverse=True)


# ---------------------------------------------------------------- the editor

ANCHORS = ["лівий нижній кут", "центр"]
HIT_PX = 4          # the cross-hair "touches" a line / a point this close (logical px; ~10 on the PicoCalc)


def seg_dist(p, a, b):
    ax, ay = a
    bx, by = b
    dx, dy = bx - ax, by - ay
    L = dx * dx + dy * dy
    t = 0.0 if L == 0 else max(0.0, min(1.0, ((p[0] - ax) * dx + (p[1] - ay) * dy) / L))
    return math.hypot(p[0] - ax - t * dx, p[1] - ay - t * dy)


def shape_dist(sh, p):
    pts = points(sh, 72)
    return min(seg_dist(p, pts[i], pts[i + 1]) for i in range(len(pts) - 1))


def handles(sh):
    """The points that shape a figure: (name, (x, y)); "move" drags the whole figure."""
    t = sh["type"]
    if t == "poly":                                     # the middle moves it, the top right corner scales it
        xs, ys = [p[0] for p in sh["pts"]], [p[1] for p in sh["pts"]]
        return [("move", ((min(xs) + max(xs)) / 2, (min(ys) + max(ys)) / 2)), ("scale", (max(xs), max(ys)))]
    if t == "circle":
        return [("move", (sh["cx"], sh["cy"])), ("r", (sh["cx"] + sh["r"], sh["cy"]))]
    if t == "ellipse":
        return [("move", (sh["cx"], sh["cy"])), ("size", (sh["cx"] + sh["rx"], sh["cy"] + sh["ry"]))]
    if t == "rect":
        x, y, w, h = sh["x"], sh["y"], sh["w"], sh["h"]
        return [("c00", (x, y)), ("c01", (x, y + h)), ("c11", (x + w, y + h)), ("c10", (x + w, y)),
                ("move", (x + w / 2, y + h / 2))]
    if t == "arc":
        a0, sw = arc_sweep(sh)
        cx, cy, r = sh["cx"], sh["cy"], sh["r"]
        return [("move", (cx, cy)), ("a0", (cx + r * math.cos(a0), cy + r * math.sin(a0))),
                ("a1", (cx + r * math.cos(a0 + sw), cy + r * math.sin(a0 + sw)))]
    return [("p0", (sh["x0"], sh["y0"])), ("p1", (sh["x1"], sh["y1"])),
            ("move", ((sh["x0"] + sh["x1"]) / 2, (sh["y0"] + sh["y1"]) / 2))]


def set_handle(orig, name, p):
    """The figure with one of its points (from handles()) moved to p; orig - as it was when grabbed."""
    sh = dict(orig)
    t = sh["type"]
    if name == "move":
        hx, hy = dict(handles(orig))["move"]
        dx, dy = p[0] - hx, p[1] - hy
        for kx, ky in (("cx", "cy"), ("x", "y"), ("x0", "y0"), ("x1", "y1")):
            if kx in sh:
                sh[kx] += dx
                sh[ky] += dy
        if t == "poly":
            sh["pts"] = [[x + dx, y + dy] for x, y in orig["pts"]]
    elif name == "scale":                               # evenly, from the bottom left corner
        xs, ys = [q[0] for q in orig["pts"]], [q[1] for q in orig["pts"]]
        x0, y0, x1, y1 = min(xs), min(ys), max(xs), max(ys)
        k = max(0.01, max((p[0] - x0) / max(x1 - x0, 1e-9), (p[1] - y0) / max(y1 - y0, 1e-9)))
        sh["pts"] = [[x0 + (x - x0) * k, y0 + (y - y0) * k] for x, y in orig["pts"]]
    elif name == "r":
        sh["r"] = math.dist((sh["cx"], sh["cy"]), p)
    elif name == "size":
        sh["rx"], sh["ry"] = abs(p[0] - sh["cx"]), abs(p[1] - sh["cy"])
    elif t == "rect":                                   # a corner: the opposite one stays
        x, y, w, h = orig["x"], orig["y"], orig["w"], orig["h"]
        ox = x if name[1] == "1" else x + w
        oy = y if name[2] == "1" else y + h
        sh["x"], sh["y"], sh["w"], sh["h"] = min(ox, p[0]), min(oy, p[1]), abs(p[0] - ox), abs(p[1] - oy)
    elif name == "a0":
        sh["r"] = math.dist((sh["cx"], sh["cy"]), p)
        sh["a0"] = round(math.degrees(math.atan2(p[1] - sh["cy"], p[0] - sh["cx"])), 3)
    elif name == "a1":
        sh["a1"] = round(math.degrees(math.atan2(p[1] - sh["cy"], p[0] - sh["cx"])), 3)
    elif name in ("p0", "p1"):
        sh["x" + name[1]], sh["y" + name[1]] = p
    return sh


def shape_rows(sh, anchor):
    """The numbers form of a figure: [key, label, value, choices]; X / Y by the anchor (corner / centre)."""
    t = sh["type"]
    if t == "poly":
        xs, ys = [p[0] for p in sh["pts"]], [p[1] for p in sh["pts"]]
        w, h = max(xs) - min(xs), max(ys) - min(ys)
        x, y = ((min(xs) + max(xs)) / 2, (min(ys) + max(ys)) / 2) if anchor == ANCHORS[1] else (min(xs), min(ys))
        return [["anchor", "Прив'язка X / Y", anchor, ANCHORS], ["X", "X", round(x, 4), None],
                ["Y", "Y", round(y, 4), None], ["w", "Ширина", round(w, 4), None], ["h", "Висота", round(h, 4), None],
                ["depth", "Глибина (0 - загальна)", sh.get("depth", 0.0), None]]
    if t in ("rect", "circle", "ellipse"):
        if t == "rect":
            w, h = sh["w"], sh["h"]
            cx, cy = sh["x"] + w / 2, sh["y"] + h / 2
        elif t == "circle":
            w = h = 2 * sh["r"]
            cx, cy = sh["cx"], sh["cy"]
        else:
            w, h = 2 * sh["rx"], 2 * sh["ry"]
            cx, cy = sh["cx"], sh["cy"]
        x, y = (cx, cy) if anchor == ANCHORS[1] else (cx - w / 2, cy - h / 2)
        rows = [["anchor", "Прив'язка X / Y", anchor, ANCHORS], ["X", "X", round(x, 4), None],
                ["Y", "Y", round(y, 4), None]]
        if t == "circle":
            rows.append(["d", "Діаметр", round(w, 4), None])
        else:
            rows += [["w", "Ширина", round(w, 4), None], ["h", "Висота", round(h, 4), None]]
        if t == "rect":
            rows.append(["rad", "Радіус кутів", sh.get("rad", 0.0), None])
        rows.append(["side", "Обробка", sh.get("side", SIDES[0]), SIDES])
        rows.append(["depth", "Глибина (0 - загальна)", sh.get("depth", 0.0), None])
        return rows
    if t == "arc":
        return [["cx", "Центр X", sh["cx"], None], ["cy", "Центр Y", sh["cy"], None], ["r", "Радіус", sh["r"], None],
                ["a0", "Початок, °", sh["a0"], None], ["a1", "Кінець, °", sh["a1"], None],
                ["ccw", "Напрям", sh.get("ccw", "проти год."), ["проти год.", "за год."]],
                ["depth", "Глибина (0 - загальна)", sh.get("depth", 0.0), None]]
    return [["x0", "Початок X", sh["x0"], None], ["y0", "Початок Y", sh["y0"], None],
            ["x1", "Кінець X", sh["x1"], None], ["y1", "Кінець Y", sh["y1"], None],
            ["depth", "Глибина (0 - загальна)", sh.get("depth", 0.0), None]]


def rows_shape(sh, vals):
    """The figure from the form's values (the inverse of shape_rows)."""
    out = dict(sh)
    t = sh["type"]
    if t == "poly":                                     # moved and scaled to the new box
        xs, ys = [p[0] for p in sh["pts"]], [p[1] for p in sh["pts"]]
        x0, y0, w0, h0 = min(xs), min(ys), max(xs) - min(xs), max(ys) - min(ys)
        w, h = abs(vals["w"]), abs(vals["h"])
        nx, ny = (vals["X"] - w / 2, vals["Y"] - h / 2) if vals["anchor"] == ANCHORS[1] else (vals["X"], vals["Y"])
        kx, ky = (w / w0 if w0 else 1.0), (h / h0 if h0 else 1.0)
        out["pts"] = [[nx + (x - x0) * kx, ny + (y - y0) * ky] for x, y in sh["pts"]]
        out["depth"] = abs(vals.get("depth", 0.0))
        return out
    if t in ("rect", "circle", "ellipse"):
        w = abs(vals.get("d", vals.get("w", 0.0)))
        h = abs(vals.get("d", vals.get("h", 0.0)))
        cx, cy = (vals["X"], vals["Y"]) if vals["anchor"] == ANCHORS[1] else (vals["X"] + w / 2, vals["Y"] + h / 2)
        if t == "rect":
            out.update(x=cx - w / 2, y=cy - h / 2, w=w, h=h, rad=max(0.0, vals["rad"]))
        elif t == "circle":
            out.update(cx=cx, cy=cy, r=w / 2)
        else:
            out.update(cx=cx, cy=cy, rx=w / 2, ry=h / 2)
        out["side"] = vals["side"]
        out["depth"] = abs(vals.get("depth", 0.0))
        return out
    out.update({k: v for k, v in vals.items()})
    return out


class Form:
    """A list of (label, value) to edit: ↑↓ - field, digits - type a number, ←→ / Enter - a choice."""

    def __init__(self, title, rows, on_done, on_change=None, bottom=False):
        self.title, self.rows, self.on_done = title, rows, on_done   # rows: [key, label, value, choices or None]
        self.on_change, self.bottom = on_change, bottom             # on_change(form, row index, old value)
        self.sel, self.top, self.typing = 0, 0, None

    def changed(self, i, old):
        if self.on_change and self.rows[i][2] != old:
            self.on_change(self, i, old)

    def key(self, k, ch):
        row = self.rows[self.sel]
        if self.typing is not None:
            if k in (pygame.K_RETURN, pygame.K_KP_ENTER, pygame.K_UP, pygame.K_DOWN, pygame.K_TAB):
                old = row[2]
                try:
                    row[2] = float(self.typing.replace(",", "."))
                except ValueError:
                    pass
                self.typing = None
                self.changed(self.sel, old)
                if k in (pygame.K_RETURN, pygame.K_KP_ENTER):
                    return None
            elif k == pygame.K_ESCAPE:
                self.typing = None
                return None
            elif k == pygame.K_BACKSPACE:
                self.typing = self.typing[:-1]
                return None
            elif ch and (ch.isdigit() or ch in ".,-"):
                self.typing += ch
                return None
            else:
                return None
        if k == pygame.K_UP:
            self.sel = (self.sel - 1) % len(self.rows)
        elif k in (pygame.K_DOWN, pygame.K_TAB):
            self.sel = (self.sel + 1) % len(self.rows)
        elif k == pygame.K_ESCAPE:
            return "cancel"
        elif row[3] and k in (pygame.K_LEFT, pygame.K_RIGHT, pygame.K_RETURN, pygame.K_KP_ENTER):
            i = row[3].index(row[2]) if row[2] in row[3] else 0
            old = row[2]
            row[2] = row[3][(i + (-1 if k == pygame.K_LEFT else 1)) % len(row[3])]
            self.changed(self.sel, old)
        elif k in (pygame.K_RETURN, pygame.K_KP_ENTER) or (ch and ch in "sS"):
            if k in (pygame.K_RETURN, pygame.K_KP_ENTER) and self.sel < len(self.rows) - 1:
                self.sel += 1                        # Enter walks down; on the last field - done
                return None
            self.on_done({r[0]: r[2] for r in self.rows})
            return "done"
        elif not row[3] and ch and (ch.isdigit() or ch in ".-"):
            self.typing = ch
        return None

    def draw(self, ui):
        screen, text, fit = ui.screen, ui.text, ui.fit
        lh = ui.f_small.get_linesize() + 0.5
        n = min(len(self.rows), 9)
        h = 12 + n * lh + 12
        y0 = 118 - h if self.bottom else max(10, (128 - h) / 2)   # bottom: the figure stays in sight
        pygame.draw.rect(screen, (20, 20, 30), (4, y0, 120, h), border_radius=3)
        pygame.draw.rect(screen, ui.ACCENT, (4, y0, 120, h), 1, border_radius=3)
        text(self.title, (64, y0 + 1), ui.ACCENT, ui.f_bold, center=True)
        self.top = min(max(self.top, self.sel - n + 1), self.sel)
        for i in range(self.top, min(len(self.rows), self.top + n)):
            key, label, val, choices = self.rows[i]
            y = y0 + 11 + (i - self.top) * lh
            if i == self.sel:
                pygame.draw.rect(screen, (70, 60, 15), (6, y, 116, lh))
            vs = fmt(val)
            if i == self.sel and self.typing is not None:
                vs = self.typing + "▏"
            text(fit(label, ui.f_small, 70), (8, y), ui.FG, ui.f_small)
            text(fit(vs, ui.f_small, 46), (120, y), ui.CYAN, ui.f_small, right=True)
        text("цифри - число, ←→ - вибір, s - готово", (64, y0 + h - 10), ui.DIM, ui.f_small, center=True)


class Editor:
    """The editor window; key() returns "close" or ("load", path of the saved G-code)."""

    AREA = (0, 10, 128, 108)

    def __init__(self, ui, t, path=None):
        self.ui, self.t = ui, t
        self.shapes, self.undo = [], []
        self.params = {k: v for k, _, v in PARAMS}
        saved = t.prof.get("shape_params") or {}
        if not saved:                                   # the first time: the machine's travel, its spindle
            for key, sid in (("width", 130), ("height", 131)):
                if isinstance(t.settings.get(sid), float) and t.settings[sid] > 0:
                    self.params[key] = min(t.settings[sid], 1000.0)
            self.params["spindle"] = float(t.spindle) if t.prof.get("spindle", True) else 0.0
        self.params.update({k: v for k, v in saved.items() if k in self.params})
        self.arc_dir = "проти год."
        self.name = None
        self.msg = ""
        # the drawing: the one of the G-code file open in SERIAL, else the last one, else a new "shape"
        svg = path[:-3] + ".svg" if path and path.endswith(".nc") else path
        last = t.prof.get("shape_doc")
        for cand in (svg, doc_path(last) if last else None):
            if cand and os.path.exists(cand):
                try:
                    self.open(cand)
                    break
                except (OSError, ValueError, ET.ParseError) as e:
                    self.msg = "не відкрито: %s" % e
        if not self.name:
            self.name = free_untitled()
        self.saved = self.sig()
        self.changed_t = None
        self.confirm = None       # "Зберегти як" onto an existing name: the second Enter replaces it
        self.cur = [0.0, 0.0]
        self.grid_i = 2
        self.tool = None          # the shape being placed
        self.pts = []             # its points so far
        self.edit = None          # editing a figure's points: {"i", "grab": {"name", "orig"} or None}
        self.preview = None       # (index, figure) while its numbers form is open
        self.form = None
        self.ask = None           # typing a new name ("Зберегти як")
        self.files = None         # the open / import list: ([(name, path)], index)
        self.files_mode = "open"
        self.esc_t = 0.0          # the first Esc of the two that leave
        self.mod = 0
        self.hold = None          # a held arrow: {"key", "t0", "next"}
        self.help = None
        self.fit()

    # -- view
    def fit(self):
        b = bounds(self.shapes)
        w, h = self.params["width"], self.params["height"]
        x0, y0, x1, y1 = (min(0, b[0]), min(0, b[1]), max(w, b[2]), max(h, b[3])) if b else (0, 0, w, h)
        ax, ay, aw, ah = self.AREA
        self.scale = min((aw - 4) / max(x1 - x0, 1), (ah - 4) / max(y1 - y0, 1))
        self.vx, self.vy = (x0 + x1) / 2, (y0 + y1) / 2
        self.auto_grid()

    def auto_grid(self):
        """The grid step that moves the cross-hair a visible 1.5+ px (the user can still pick with g / G)."""
        for i, g in enumerate(GRID_STEPS):
            if g * self.scale >= 1.5:
                self.grid_i = i
                return
        self.grid_i = len(GRID_STEPS) - 1

    def px(self, x, y):
        ax, ay, aw, ah = self.AREA
        return ax + aw / 2 + (x - self.vx) * self.scale, ay + ah / 2 - (y - self.vy) * self.scale

    def follow(self):
        """Keep the cross-hair on the canvas."""
        ax, ay, aw, ah = self.AREA
        x, y = self.px(*self.cur)
        if not (ax + 4 <= x <= ax + aw - 4):
            self.vx = self.cur[0]
        if not (ay + 4 <= y <= ay + ah - 4):
            self.vy = self.cur[1]

    # -- shapes
    def grid(self):
        return GRID_STEPS[self.grid_i]

    def push_undo(self):
        self.undo = (self.undo + [json.dumps(self.shapes)])[-30:]

    def make(self, kind, pts, c):
        """The shape from its placed points and the cross-hair (the last point, live)."""
        p = pts + [tuple(c)]
        if kind == "circle":
            return {"type": kind, "cx": p[0][0], "cy": p[0][1], "r": math.dist(p[0], p[1]) if len(p) > 1 else 0.0,
                    "side": SIDES[0]}
        if kind == "ellipse":
            return {"type": kind, "cx": p[0][0], "cy": p[0][1], "rx": abs(p[1][0] - p[0][0]) if len(p) > 1 else 0.0,
                    "ry": abs(p[1][1] - p[0][1]) if len(p) > 1 else 0.0, "side": SIDES[0]}
        if kind == "rect":
            (x0, y0), (x1, y1) = p[0], p[1] if len(p) > 1 else p[0]
            return {"type": kind, "x": min(x0, x1), "y": min(y0, y1), "w": abs(x1 - x0), "h": abs(y1 - y0),
                    "rad": self.t.prof.get("rect_rad", 0.0), "side": SIDES[0]}
        if kind == "line":
            return {"type": kind, "x0": p[0][0], "y0": p[0][1], "x1": p[-1][0], "y1": p[-1][1]}
        cx, cy = p[0]                                       # arc: centre, start, end
        sx, sy = p[1] if len(p) > 1 else (cx + 1, cy)
        ex, ey = p[2] if len(p) > 2 else (sx, sy)
        r = math.hypot(sx - cx, sy - cy)
        return {"type": kind, "cx": cx, "cy": cy, "r": r, "a0": round(math.degrees(math.atan2(sy - cy, sx - cx)), 3),
                "a1": round(math.degrees(math.atan2(ey - cy, ex - cx)), 3), "ccw": self.arc_dir}

    def valid(self, sh):
        t = sh["type"]
        return {"circle": lambda: sh["r"] > 0, "ellipse": lambda: sh["rx"] > 0 and sh["ry"] > 0,
                "rect": lambda: sh["w"] > 0 and sh["h"] > 0, "arc": lambda: sh["r"] > 0 and sh["a0"] != sh["a1"],
                "line": lambda: (sh["x0"], sh["y0"]) != (sh["x1"], sh["y1"]),
                "poly": lambda: len(sh["pts"]) > 1}[t]()

    def hover(self):
        """The figure whose line is within HIT_PX of the cross-hair (the nearest one), or None."""
        best, bi = HIT_PX / self.scale, None
        for i, sh in enumerate(self.shapes):
            d = shape_dist(sh, self.cur)
            if d <= best:
                best, bi = d, i
        return bi

    def near_handle(self, sh):
        best, name = HIT_PX / self.scale, None
        for n, p in handles(sh):
            d = math.dist(p, self.cur)
            if d <= best:
                best, name = d, n
        return name

    def jump(self, p):
        self.cur = [round(p[0], 4), round(p[1], 4)]
        self.follow()
        self.tick_grab()

    def start_edit(self, i):
        self.edit = {"i": i, "grab": None, "h": 0}
        sh = self.shapes[i]
        hs = handles(sh)                              # the cross-hair onto the nearest point
        n = min(range(len(hs)), key=lambda j: math.dist(hs[j][1], self.cur))
        self.edit["h"] = n
        self.jump(hs[n][1])

    def shape_form(self, i):
        """The figure's numbers (Space): exact position, sizes; previewed live, applied on s / the last Enter."""
        base = self.shapes[i]
        anchor = self.t.prof.get("anchor", ANCHORS[0])
        if anchor not in ANCHORS:
            anchor = ANCHORS[0]
        self.preview = (i, dict(base))

        def vals(form):
            return {r[0]: r[2] for r in form.rows}

        def change(form, idx, old):
            row = form.rows[idx]
            if row[0] == "anchor":                    # the same figure, X / Y told the other way
                v = vals(form)
                v["anchor"] = old
                fig = rows_shape(base, v)
                new = {r[0]: r[2] for r in shape_rows(fig, row[2])}
                for r in form.rows:
                    if r[0] in ("X", "Y"):
                        r[2] = new[r[0]]
                self.t.prof["anchor"] = row[2]
            self.preview = (i, rows_shape(base, vals(form)))

        def done(v):
            self.push_undo()
            self.shapes[i] = rows_shape(base, v)
            sh = self.shapes[i]
            if sh.get("side") == POCKET and not pocket(sh, self.params["tool"], self.params.get("stepover", 40.0))[1]:
                self.msg = "фреза Ø%s завелика для цього карману" % fmt(self.params["tool"])
            if base["type"] == "rect":
                self.t.prof["rect_rad"] = self.shapes[i].get("rad", 0.0)
        self.form = Form("%d: %s" % (i + 1, NAMES[base["type"]]), shape_rows(base, anchor), done, change, bottom=True)

    def param_form(self):
        def done(vals):
            self.params.update(vals)
            self.t.prof["shape_params"] = dict(self.params)
            self.t.save_cfg()
            self.fit()
        self.form = Form("Параметри обробки", [[k, label, self.params[k], None] for k, label, _ in PARAMS], done)

    def open(self, path):
        shapes, params = load(path)
        self.shapes = shapes
        self.params.update({k: float(v) for k, v in params.items() if k in self.params})
        self.name = safe_name(os.path.basename(path))
        self.t.prof["shape_doc"] = self.name

    # -- saving: by itself a second after a change; "Зберегти як" renames
    def sig(self):
        return json.dumps([self.shapes, self.params], sort_keys=True)

    def flush(self):
        """Write NAME.svg + NAME.nc now if anything changed (nothing for an empty new drawing)."""
        if self.sig() == self.saved:
            return True
        if not self.shapes and not os.path.exists(doc_path(self.name)):
            self.saved = self.sig()
            return True
        try:
            save(self.name, self.shapes, self.params)
        except OSError as e:
            self.msg = "не збережено: %s" % (e.strerror or e)
            return False
        self.saved, self.changed_t = self.sig(), None
        self.t.prof["shape_doc"] = self.name
        self.t.save_cfg()
        return True

    def save_as(self, name):
        new = safe_name(name)
        if new == self.name:
            self.saved = None                       # write it anyway
            self.flush()
            self.msg = "збережено: %s" % new
            return
        old = self.name
        self.name = new
        self.saved = None
        if self.flush():
            if untitled(old):                       # "shape" was only a working name: renamed, not copied
                remove(old)
            self.msg = "збережено як %s.svg / .nc" % new
        else:
            self.name = old

    def new_drawing(self):
        self.flush()
        self.name = free_untitled()
        self.shapes, self.undo, self.edit = [], [], None
        self.saved = self.sig()
        self.t.prof["shape_doc"] = self.name
        self.fit()

    # -- keys
    def move(self, k, n=1):
        g0 = self.grid()
        dx, dy = {pygame.K_LEFT: (-1, 0), pygame.K_RIGHT: (1, 0), pygame.K_UP: (0, 1), pygame.K_DOWN: (0, -1)}[k]
        # on the grid (a point typed off it snaps back)
        w, h = self.params["width"], self.params["height"]
        self.cur = [min(w, max(-w, round(round((self.cur[0] + dx * n * g0) / g0) * g0, 4))),
                    min(h, max(-h, round(round((self.cur[1] + dy * n * g0) / g0) * g0, 4)))]
        self.follow()
        self.tick_grab()

    def keyup(self, k):
        if self.hold and self.hold["key"] == k:
            self.hold = None

    def tick(self):
        """A held arrow repeats: after 0.35 s, one grid step every 60 ms, three after 1.5 s."""
        now = time.monotonic()
        if self.sig() != self.saved and not (self.edit and self.edit["grab"]) and not self.form:
            if self.changed_t is None:
                self.changed_t = now
            elif now - self.changed_t >= AUTOSAVE_S:
                self.flush()
        h = self.hold
        if not h or now < h["next"] or self.form or self.ask is not None or self.files is not None or self.help:
            return
        held = now - h["t0"]
        self.move(h["key"], 3 if held > 1.5 else 1)
        h["next"] = now + 0.06

    def key(self, k, hat=False, ch=""):
        self.msg = ""
        if self.help:
            if self.help.key(k) == "close":
                self.help = None
            return None
        if k == pygame.K_F1:
            self.help = self.ui.TextPopup("Редактор фігур", HELP)
            return None
        if self.form:
            r = self.form.key(k, ch)
            if r in ("done", "cancel"):
                self.form, self.preview = None, None
            return None
        if self.ask is not None:                       # "Зберегти як": the new name
            if k in (pygame.K_RETURN, pygame.K_KP_ENTER):
                if not self.ask.strip():
                    self.ask = None
                    return None
                new = safe_name(self.ask)
                if new != self.name and os.path.exists(doc_path(new)) and self.confirm != new:
                    self.confirm = new
                    self.msg = "%s вже є - Enter ще раз замінить" % new
                    return None
                self.ask, self.confirm = None, None
                self.save_as(new)
                return None
            self.confirm = None
            if k == pygame.K_ESCAPE:
                self.ask = None
            elif k == pygame.K_BACKSPACE:
                self.ask = self.ask[:-1]
            elif ch and ch.isprintable():
                self.ask += ch
            return None
        if self.files is not None:                     # the open list
            paths, i = self.files
            if k == pygame.K_UP:
                self.files = (paths, (i - 1) % len(paths))
            elif k == pygame.K_DOWN:
                self.files = (paths, (i + 1) % len(paths))
            elif k in (pygame.K_RETURN, pygame.K_KP_ENTER) and self.files_mode == "import":
                name, path = paths[i]
                self.files = None
                try:
                    new = load(path)[0]
                except (OSError, ValueError, ET.ParseError) as e:
                    self.msg = "не прочитано: %s" % e
                    return None
                b = bounds(new)
                if not b:
                    self.msg = "у файлі немає фігур"
                    return None
                dx, dy = self.cur[0] - b[0], self.cur[1] - b[1]     # its bottom left onto the cross-hair
                for sh in new:
                    for kx, ky in (("cx", "cy"), ("x", "y"), ("x0", "y0"), ("x1", "y1")):
                        if kx in sh:
                            sh[kx] += dx
                            sh[ky] += dy
                    if sh["type"] == "poly":
                        sh["pts"] = [[x + dx, y + dy] for x, y in sh["pts"]]
                self.push_undo()
                self.shapes += new
                polys = sum(1 for sh in new if sh["type"] == "poly")
                self.msg = "додано %d фігур (%d контурів), %s×%s мм" % (len(new), polys, fmt(round(b[2] - b[0], 2)),
                                                                       fmt(round(b[3] - b[1], 2)))
                self.fit()
                return None
            elif k in (pygame.K_RETURN, pygame.K_KP_ENTER):
                name, path = paths[i]
                self.files = None
                if path is None:
                    self.new_drawing()
                    self.msg = "нове креслення: %s" % self.name
                    return None
                self.flush()
                try:
                    self.open(path)
                    self.saved = self.sig() if path.endswith(".svg") else None   # an old .json: write its .svg
                    self.undo, self.edit = [], None
                    self.fit()
                except (OSError, ValueError, ET.ParseError) as e:
                    self.msg = "не відкрито: %s" % e
                return None
            else:
                self.files = None
            return None
        enter = k in (pygame.K_RETURN, pygame.K_KP_ENTER)
        if hat:
            if k == pygame.K_3:
                k = pygame.K_ESCAPE
            elif k == pygame.K_1:
                ch = "c" if not self.tool else ""
            elif k == pygame.K_2:
                ch = " "
        if k in (pygame.K_LEFT, pygame.K_RIGHT, pygame.K_UP, pygame.K_DOWN):
            self.move(k)
            self.hold = {"key": k, "t0": time.monotonic(), "next": time.monotonic() + 0.35}
            return None
        if self.edit:                                   # editing a figure's points
            e = self.edit
            sh = self.shapes[e["i"]]
            if enter:
                if e["grab"]:
                    e["grab"] = None                    # dropped where it is
                else:
                    name = self.near_handle(sh)
                    if name:
                        self.push_undo()
                        e["grab"] = {"name": name, "orig": dict(sh)}
                    else:
                        self.msg = "наведіть хрестик на точку (Tab - наступна)"
            elif k == pygame.K_ESCAPE:
                if e["grab"]:
                    self.shapes[e["i"]] = e["grab"]["orig"]
                    self.undo.pop()
                    e["grab"] = None
                else:
                    self.edit = None
            elif k == pygame.K_TAB and not e["grab"]:
                hs = handles(sh)
                e["h"] = (e["h"] + (-1 if self.mod & pygame.KMOD_SHIFT else 1)) % len(hs)
                self.jump(hs[e["h"]][1])
            elif ch in (" ", "n") and not e["grab"]:
                self.shape_form(e["i"])
            elif k in (pygame.K_DELETE, pygame.K_BACKSPACE) and not e["grab"]:
                self.push_undo()
                del self.shapes[e["i"]]
                self.edit = None
            elif ch == "u" and self.undo and not e["grab"]:
                self.shapes = json.loads(self.undo.pop())
                self.edit = None
            return None
        if enter and self.tool:
            self.pts.append(tuple(self.cur))
            if len(self.pts) == len(STEPS[self.tool]):
                sh = self.make(self.tool, self.pts[:-1], self.pts[-1])
                if self.valid(sh):
                    self.push_undo()
                    self.shapes.append(sh)
                    self.msg = "%s готово (пробіл - числа)" % NAMES[self.tool]
                else:
                    self.msg = "нульовий розмір - не додано"
                self.pts = []                           # the same tool again
        elif enter or ch in (" ", "n") or k in (pygame.K_DELETE, pygame.K_BACKSPACE):
            if ch == "n":
                ch = " "                                # n - the same as Space (numbers)
            if self.tool and k == pygame.K_BACKSPACE:
                if self.pts:
                    self.pts.pop()
                return None
            if self.tool and ch == " " and not self.pts:
                self.tool = None                        # Space near a figure while a tool waits: its numbers
            if self.tool:
                return None
            i = self.hover()
            if i is None:
                self.msg = "поруч немає фігури - наведіть хрестик на лінію"
            elif enter:
                self.start_edit(i)
            elif ch == " ":
                self.shape_form(i)
            else:
                self.push_undo()
                del self.shapes[i]
        elif k == pygame.K_ESCAPE:
            if self.tool:
                self.tool, self.pts = None, []
            elif time.monotonic() - self.esc_t > 2.0:   # one Esc never leaves: a second one within 2 s does
                self.esc_t = time.monotonic()
                self.flush()
                self.msg = "Esc ще раз - вийти (креслення збережено)"
            else:                                       # leave: saved, and the G-code opens in SERIAL
                self.flush()
                return ("load", os.path.join(SHAPES_DIR, self.name + ".nc")) if self.shapes else "close"
        elif k == pygame.K_TAB and self.shapes:          # the cross-hair onto the next figure
            self.tab = (getattr(self, "tab", -1) + (-1 if self.mod & pygame.KMOD_SHIFT else 1)) % len(self.shapes)
            self.tool, self.pts = None, []
            self.jump(points(self.shapes[self.tab], 8)[0])
        elif ch in TOOLS:
            self.tool, self.pts = TOOLS[ch], []
        elif ch == "d" and self.tool == "arc":
            self.arc_dir = "за год." if self.arc_dir == "проти год." else "проти год."
        elif ch == "p":
            self.param_form()
        elif ch == "g":
            self.grid_i = (self.grid_i + 1) % len(GRID_STEPS)
        elif ch == "G":
            self.grid_i = (self.grid_i - 1) % len(GRID_STEPS)
        elif ch in ("+", "="):
            self.scale *= 1.5
            self.vx, self.vy = self.cur
            self.auto_grid()
        elif ch in ("-", "_"):
            self.scale /= 1.5
            self.auto_grid()
        elif ch == "0":
            self.fit()
        elif ch == "h":
            self.jump((0.0, 0.0))
        elif ch == "u" and self.undo:
            self.shapes = json.loads(self.undo.pop())
        elif ch == "s":
            self.ask = "" if untitled(self.name) else self.name
        elif ch == "o":
            self.flush()
            self.files, self.files_mode = ([("+ нове креслення", None)] + drawings(), 0), "open"
        elif ch == "i":
            src = import_sources()
            if src:
                self.files, self.files_mode = (src, 0), "import"
            else:
                self.msg = "немає .svg у ~/gcode, ~/Downloads, ~"
        return None

    def tick_grab(self):
        """A grabbed point follows the cross-hair."""
        e = self.edit
        if e and e["grab"]:
            sh = set_handle(e["grab"]["orig"], e["grab"]["name"], tuple(self.cur))
            if self.valid(sh):
                self.shapes[e["i"]] = sh

    def state(self):
        """What the screen shows (SERIAL redraws only when it changes)."""
        f = self.form
        return repr((self.cur, self.tool, self.pts, self.edit and (self.edit["i"], bool(self.edit["grab"])),
                     self.preview, json.dumps(self.shapes)[-200:], len(self.shapes), self.undo[-1:], self.scale, self.vx,
                     self.vy, self.grid_i, self.msg, self.ask, self.files and self.files[1], self.arc_dir,
                     f and (f.sel, f.typing, [r[2] for r in f.rows]), self.params,
                     self.help and self.help.top, self.sig() == self.saved, self.name))

    # -- drawing
    def draw(self):
        ui = self.ui
        screen, text, fit = ui.screen, ui.text, ui.fit
        screen.fill(ui.BG)
        ax, ay, aw, ah = self.AREA
        # the grid: lines every 1 / 10 / 100 mm, whichever is at least 4 px apart
        for unit, color in ((1, (22, 22, 30)), (10, (36, 36, 50)), (100, (55, 55, 75))):
            if unit * self.scale < 4:
                continue
            x0 = math.floor((self.vx - aw / 2 / self.scale) / unit) * unit
            x = x0
            while True:
                sx, _ = self.px(x, 0)
                if sx > ax + aw:
                    break
                if sx >= ax:
                    pygame.draw.line(screen, color, (sx, ay), (sx, ay + ah))
                x += unit
            y = math.floor((self.vy - ah / 2 / self.scale) / unit) * unit
            while True:
                _, sy = self.px(0, y)
                if sy < ay:
                    break
                if sy <= ay + ah:
                    pygame.draw.line(screen, color, (ax, sy), (ax + aw, sy))
                y += unit
        # the field and the work zero
        x0, y0 = self.px(0, 0)
        x1, y1 = self.px(self.params["width"], self.params["height"])
        pygame.draw.rect(screen, (70, 70, 110), (x0, y1, x1 - x0, y0 - y1), 1)
        pygame.draw.line(screen, (200, 80, 80), (x0, y0), (x0 + 8, y0))
        pygame.draw.line(screen, (80, 200, 80), (x0, y0), (x0, y0 - 8))
        # the shapes; the selected one yellow; the tool's path (offset) dotted
        hov = None if (self.tool or self.edit or self.form) else self.hover()
        cur_i = self.edit["i"] if self.edit else self.preview[0] if self.preview else hov
        for i, sh in enumerate(self.shapes):
            if self.preview and i == self.preview[0]:   # the numbers form: the old figure dim, the new bright
                pts = [self.px(*p) for p in points(sh)]
                pygame.draw.lines(screen, (70, 90, 90), False, pts)
                sh = self.preview[1]
            col = ui.ACCENT if i == cur_i else ui.CYAN
            pts = [self.px(*p) for p in points(sh)]
            if len(pts) > 1:
                pygame.draw.lines(screen, col, False, pts, 2 if i == cur_i else 1)
            if closed(sh) and sh.get("side") == POCKET:   # a pocket: its rings, dim
                centre, rings = pocket(sh, self.params["tool"], self.params.get("stepover", 40.0))
                for ring in rings:
                    pygame.draw.lines(screen, (40, 95, 60), False, [self.px(*p) for p in points(ring, 36)])
                pygame.draw.line(screen, (40, 95, 60), self.px(centre["x0"], centre["y0"]),
                                 self.px(centre["x1"], centre["y1"]))
            elif closed(sh) and sh.get("side", SIDES[0]) != SIDES[0]:
                off = [self.px(*p) for p in points(offset(sh, self.params["tool"]))]
                for a in off[::2]:
                    pygame.draw.rect(screen, (110, 170, 110), (a[0] - 0.4, a[1] - 0.4, 0.8, 0.8))
        if self.tool:                                   # the shape being placed, live
            if self.pts:
                sh = self.make(self.tool, self.pts, self.cur)
                pts = [self.px(*p) for p in points(sh)]
                if len(pts) > 1:
                    pygame.draw.lines(screen, ui.GREEN, False, pts)
                for p in self.pts:
                    sx, sy = self.px(*p)
                    pygame.draw.circle(screen, ui.GREEN, (sx, sy), 1.2)
        if self.edit:                                   # its points: squares; the one under the cross-hair bigger
            sh = self.shapes[self.edit["i"]]
            near = self.near_handle(sh)
            for n, p in handles(sh):
                sx, sy = self.px(*p)
                grab = self.edit["grab"] and self.edit["grab"]["name"] == n
                r = 2.2 if n == near or grab else 1.4
                pygame.draw.rect(screen, ui.GREEN if grab else ui.ACCENT, (sx - r, sy - r, 2 * r, 2 * r),
                                 0 if grab else 1)
        cx, cy = self.px(*self.cur)                     # the cross-hair
        pygame.draw.line(screen, ui.ORANGE, (cx - 4, cy), (cx + 4, cy))
        pygame.draw.line(screen, ui.ORANGE, (cx, cy - 4), (cx, cy + 4))
        pygame.draw.rect(screen, ui.BG, (0, 0, 128, 10))
        pygame.draw.rect(screen, ui.BG, (0, 118, 128, 10))
        # top: the tool and what to place next, or the selection
        if self.tool:
            step = STEPS[self.tool][min(len(self.pts), len(STEPS[self.tool]) - 1)]
            extra = (" (%s, d)" % self.arc_dir) if self.tool == "arc" else ""
            text(fit("%s: %s%s" % (NAMES[self.tool], step, extra), ui.f_bold, 124), (2, 0), ui.GREEN, ui.f_bold)
        elif self.edit:
            sh = self.shapes[self.edit["i"]]
            s = ("%s: тягніть, Enter - покласти, Esc - назад" if self.edit["grab"] else
                 "%s: Enter на точці - взяти, Tab, пробіл, Esc") % NAMES[sh["type"]]
            text(fit(s, ui.f_small, 124), (2, 1), ui.ACCENT, ui.f_small)
        elif hov is not None:
            sh = self.shapes[hov]
            d = abs(sh.get("depth") or 0.0) or self.params["depth"]
            kind = NAMES[sh["type"]] + (" (карман)" if sh.get("side") == POCKET else "")
            text(fit("%s ↓%s: Enter - точки, пробіл - числа, Del" % (kind, fmt(d)), ui.f_small, 124),
                 (2, 1), ui.ACCENT, ui.f_small)
        else:
            mark = "✓" if self.sig() == self.saved else "●"     # saved / to be saved in a second
            text(fit("%s %s · %d" % (self.name, mark, len(self.shapes)), ui.f_bold, 70), (2, 0), ui.ACCENT,
                 ui.f_bold)
            text("Ø%s ↓%s F1" % (fmt(self.params["tool"]), fmt(self.params["depth"])), (126, 1), ui.DIM,
                 ui.f_small, right=True)
        # bottom: the cross-hair, the grid, a live size
        info = "X%s Y%s  крок %s" % (fmt(round(self.cur[0], 3)), fmt(round(self.cur[1], 3)), fmt(self.grid()))
        if self.tool and self.pts:
            sh = self.make(self.tool, self.pts, self.cur)
            info += "  " + {"circle": lambda: "R%s" % fmt(round(sh["r"], 3)),
                            "ellipse": lambda: "%s×%s" % (fmt(round(sh["rx"], 3)), fmt(round(sh["ry"], 3))),
                            "rect": lambda: "%s×%s" % (fmt(round(sh["w"], 3)), fmt(round(sh["h"], 3))),
                            "arc": lambda: "R%s" % fmt(round(sh["r"], 3)),
                            "line": lambda: "L%s" % fmt(round(math.dist((sh["x0"], sh["y0"]), (sh["x1"], sh["y1"])), 3))
                            }[self.tool]()
        text(fit(self.msg or info, ui.f_small, 124), (2, 119), ui.ACCENT if self.msg else ui.FG, ui.f_small)
        if self.form:
            self.form.draw(ui)
        if self.ask is not None:
            pygame.draw.rect(screen, (40, 40, 10), (0, 100, 128, 28))
            text("зберегти як (~/gcode/shapes/…svg + .nc)", (2, 101), ui.ACCENT, ui.f_small)
            s = self.ask + "▏"
            text(fit(s, ui.f_mono, 124), (2, 112), ui.FG, ui.f_mono)
        if self.help:
            self.help.draw()
        if self.files is not None:
            paths, i = self.files
            lh = ui.f_small.get_linesize()
            n = min(len(paths), 10)
            h = 12 + n * lh + 3
            yy = max(10, (128 - h) / 2)
            pygame.draw.rect(screen, (20, 20, 30), (6, yy, 116, h), border_radius=3)
            pygame.draw.rect(screen, ui.ACCENT, (6, yy, 116, h), 1, border_radius=3)
            text("Відкрити" if self.files_mode == "open" else "Імпорт SVG у хрестик", (64, yy + 1), ui.ACCENT,
                 ui.f_bold, center=True)
            top = min(max(0, i - n + 1), max(0, len(paths) - n))
            for j in range(top, min(len(paths), top + n)):
                y = yy + 11 + (j - top) * lh
                if j == i:
                    pygame.draw.rect(screen, (70, 60, 15), (8, y, 112, lh))
                name, path = paths[j]
                when = time.strftime(" %d.%m %H:%M", time.localtime(os.path.getmtime(path))) if path else ""
                wd = ui.f_small.size(when)[0]
                text(fit(name, ui.f_small, 106 - wd), (10, y), ui.GREEN if path is None else
                     ui.ACCENT if name == self.name else ui.FG, ui.f_small)
                if when:
                    text(when, (118, y), ui.DIM, ui.f_small, right=True)
