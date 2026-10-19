"""Text for the shape editor: letters from a TrueType font fitted into a frame (a rectangle or a circle),
turned by an angle, and their toolpaths - filled (rings from the edge inwards, half the tool inside the
letter, the next ring a stepover further) or along the outline.

fontTools reads the glyph outlines (quadratic / cubic curves cut into chords), pyclipper does the
union of the contours and the offsets. "|" in the text starts a new line.
"""
import math
import os

FONT_DIR = "/usr/share/fonts/truetype/dejavu/"
FONTS = ["DejaVuSans-Bold", "DejaVuSans", "DejaVuSerif-Bold", "DejaVuSerif", "DejaVuSansMono-Bold", "DejaVuSansMono"]
# filled letters; along the outline (its centre line - a V-bit); outside / inside the letters by the tool's radius
FILLS = ["заливка", "по контуру", "зовні", "всередині"]
OLD_FILLS = {"контур": "по контуру"}
FRAMES = ["прямокутник", "по дузі"]    # fitted into a rectangle / written along an arc (360° - a circle)
DIRS = ["зверху, за год.", "знизу, проти год."]   # along the arc: letters outward (top) / inward (bottom)
SCALE = 1000.0                         # pyclipper works in integers: µm
CHORD = 0.03                           # a curve chord, in em (fine enough for letters a few mm high)

# the Ukrainian layout over the US keys (the editor's text field: Tab switches)
UA = dict(zip("qwertyuiop[]asdfghjkl;'zxcvbnm,./`\\QWERTYUIOP{}ASDFGHJKL:\"ZXCVBNM<>?~|",
              "йцукенгшщзхїфівапролджєячсмитьбю.'ґЙЦУКЕНГШЩЗХЇФІВАПРОЛДЖЄЯЧСМИТЬБЮ,'Ґ"))

_fonts = {}
_cache = {}
_paths_cache = {}

try:
    import pyclipper
    from fontTools.pens.basePen import BasePen
    from fontTools.ttLib import TTFont
    AVAILABLE = True
except ImportError:                    # without the packages the text tool says so
    AVAILABLE = False
    BasePen = object


class _Pen(BasePen):
    """Glyph outlines as polygons (font units)."""

    def __init__(self, glyphset):
        super().__init__(glyphset)
        self.polys, self.cur = [], []

    def _moveTo(self, p):
        self.cur = [p]

    def _lineTo(self, p):
        self.cur.append(p)

    def _curveToOne(self, p1, p2, p3):
        p0 = self.cur[-1]
        n = 8
        for k in range(1, n + 1):
            t = k / n
            u = 1 - t
            self.cur.append((u ** 3 * p0[0] + 3 * u * u * t * p1[0] + 3 * u * t * t * p2[0] + t ** 3 * p3[0],
                             u ** 3 * p0[1] + 3 * u * u * t * p1[1] + 3 * u * t * t * p2[1] + t ** 3 * p3[1]))

    def _qCurveToOne(self, p1, p2):
        p0 = self.cur[-1]
        n = 6
        for k in range(1, n + 1):
            t = k / n
            u = 1 - t
            self.cur.append((u * u * p0[0] + 2 * u * t * p1[0] + t * t * p2[0],
                             u * u * p0[1] + 2 * u * t * p1[1] + t * t * p2[1]))

    def _closePath(self):
        if len(self.cur) > 2:
            self.polys.append(self.cur)
        self.cur = []

    _endPath = _closePath


def font(name):
    if name not in _fonts:
        path = os.path.join(FONT_DIR, name + ".ttf")
        if not os.path.exists(path):
            path = os.path.join(FONT_DIR, "DejaVuSans.ttf")
        f = TTFont(path, lazy=True)
        _fonts[name] = (f, f.getGlyphSet(), f.getBestCmap(), f["hmtx"], f["head"].unitsPerEm)
    return _fonts[name]


def layout(text, name):
    """The text's contours in em (y up, the first line's baseline at 0), lines centred; and their box."""
    f, gs, cmap, hmtx, upem = font(name)
    lines = (text or " ").split("|")
    polys, widths, line_polys = [], [], []
    for i, line in enumerate(lines):
        x, lp = 0.0, []
        for ch in line:
            g = cmap.get(ord(ch)) or cmap.get(ord("?"))
            if g is None:
                continue
            pen = _Pen(gs)
            gs[g].draw(pen)
            for poly in pen.polys:
                lp.append([(x + px / upem, py / upem - 1.25 * i) for px, py in poly])
            x += hmtx[g][0] / upem
        widths.append(x)
        line_polys.append(lp)
    wmax = max(widths) if widths else 0
    for w, lp in zip(widths, line_polys):
        dx = (wmax - w) / 2
        polys += [[(x + dx, y) for x, y in poly] for poly in lp]
    if not polys:
        return [], (0, 0, 0, 0)
    xs = [x for p in polys for x, _ in p]
    ys = [y for p in polys for _, y in p]
    return polys, (min(xs), min(ys), max(xs), max(ys))


def placed(sh):
    """The text's contours in mm, fitted into its frame and turned by its angle (cached by the shape)."""
    if not AVAILABLE:
        return []
    key = (sh.get("text"), sh.get("font"), sh.get("frame"), sh.get("angle"), sh.get("x"), sh.get("y"), sh.get("w"),
           sh.get("h"), sh.get("cx"), sh.get("cy"), sh.get("r"), sh.get("span"), sh.get("size"), sh.get("dir"))
    if key in _cache:
        return _cache[key]
    polys, (x0, y0, x1, y1) = layout(sh.get("text", ""), sh.get("font", FONTS[0]))
    if not polys:
        _cache[key] = []
        return []
    if sh.get("frame") != FRAMES[0]:                 # along an arc (an old "коло" drawing too)
        out = along_arc(sh, polys, (x0, y0, x1, y1))
        if len(_cache) > 64:
            _cache.clear()
        _cache[key] = out
        return out
    a = math.radians(sh.get("angle", 0.0) or 0.0)
    ca, sa = math.cos(a), math.sin(a)
    mx, my = (x0 + x1) / 2, (y0 + y1) / 2
    corners = [((x - mx) * ca - (y - my) * sa, (x - mx) * sa + (y - my) * ca) for x, y in
               ((x0, y0), (x1, y0), (x1, y1), (x0, y1))]
    cx, cy = sh["x"] + sh["w"] / 2, sh["y"] + sh["h"] / 2
    bw = max(x for x, _ in corners) - min(x for x, _ in corners) or 1
    bh = max(y for _, y in corners) - min(y for _, y in corners) or 1
    k = min(sh["w"] / bw, sh["h"] / bh)
    out = [[(cx + k * ((x - mx) * ca - (y - my) * sa), cy + k * ((x - mx) * sa + (y - my) * ca)) for x, y in poly]
           for poly in polys]
    if len(_cache) > 64:
        _cache.clear()
    _cache[key] = out
    return out


def densify(poly, step):
    """Straight edges cut into pieces (they bend when the text follows an arc)."""
    out = [poly[0]]
    for p in poly[1:] + [poly[0]]:
        a = out[-1]
        n = max(1, int(math.dist(a, p) / step))
        out += [(a[0] + (p[0] - a[0]) * j / n, a[1] + (p[1] - a[1]) * j / n) for j in range(1, n + 1)]
    return out[:-1]


def along_arc(sh, polys, box):
    """The letters on an arc: the baseline on the circle (cx, cy, r), the text's middle at "angle"
    (90 - the top); "span" degrees > 0 - the letters scaled to fill that much of the arc, else "size" mm high.
    The top way reads clockwise with the letters outward, the bottom way counter-clockwise, letters inward."""
    x0, y0, x1, y1 = box
    cx, cy, r = sh["cx"], sh["cy"], max(0.01, sh["r"])
    width = max(x1 - x0, 1e-6)
    span = abs(sh.get("span", 0.0) or 0.0)
    k = math.radians(min(span, 359.0)) * r / width if span else max(0.01, sh.get("size", r / 4) or r / 4)
    mid = (x0 + x1) / 2
    theta = math.radians(sh.get("angle", 90.0) if sh.get("angle") is not None else 90.0)
    top = sh.get("dir", DIRS[0]) != DIRS[1]
    out = []
    for poly in polys:
        q = []
        for x, y in densify(poly, 0.04):
            s_ = (x - mid) * k                       # along the baseline, mm
            h = y * k                                # above it, mm
            phi = theta - s_ / r if top else theta + s_ / r
            rho = r + h if top else r - h
            q.append((cx + rho * math.cos(phi), cy + rho * math.sin(phi)))
        out.append(q)
    return out


def _paths(tree):
    return [[(x / SCALE, y / SCALE) for x, y in p] for p in tree]


def toolpaths(sh, tool, stepover):
    """Closed polylines (mm) to cut: filled - rings from half a tool inside the letters inwards;
    outline - the letters' own contours. Ordered to keep the moves between them short. Cached: the editor
    saves a second after every change, and an unchanged text costs nothing then."""
    key = (repr(sorted((k, v) for k, v in sh.items() if k != "depth")), tool, stepover)
    if key in _paths_cache:
        return _paths_cache[key]
    out = _toolpaths(sh, tool, stepover)
    if len(_paths_cache) > 32:
        _paths_cache.clear()
    _paths_cache[key] = out
    return out


def _toolpaths(sh, tool, stepover):
    polys = placed(sh)
    if not polys:
        return []
    pc = pyclipper.Pyclipper()
    pc.AddPaths([[(round(x * SCALE), round(y * SCALE)) for x, y in p] for p in polys], pyclipper.PT_SUBJECT, True)
    shape = pc.Execute(pyclipper.CT_UNION, pyclipper.PFT_NONZERO, pyclipper.PFT_NONZERO)
    rings = []
    fill = OLD_FILLS.get(sh.get("fill"), sh.get("fill", FILLS[0]))

    def offset(d):
        off = pyclipper.PyclipperOffset()
        off.AddPaths(shape, pyclipper.JT_ROUND, pyclipper.ET_CLOSEDPOLYGON)
        return off.Execute(d * SCALE)
    if fill == FILLS[1] or tool <= 0:                # on the line
        rings = _paths(shape)
    elif fill == FILLS[2]:                           # outside: the letters keep their size
        rings = _paths(offset(tool / 2))
    elif fill == FILLS[3]:                           # inside: the tool stays within the strokes
        rings = _paths(offset(-tool / 2)) or _paths(shape)
    else:
        step = max(0.02, tool * min(max(stepover, 5.0), 100.0) / 100.0)
        k = tool / 2
        while True:
            off = pyclipper.PyclipperOffset()
            off.AddPaths(shape, pyclipper.JT_ROUND, pyclipper.ET_CLOSEDPOLYGON)
            got = off.Execute(-k * SCALE)
            if not got:
                break
            rings += _paths(got)
            k += step
            if k > 1000:
                break
        if not rings:                                # thinner than the tool: at least the outline
            rings = _paths(shape)
    rings = [r + [r[0]] for r in rings if len(r) > 2]
    order, pos = [], (0.0, 0.0)                      # nearest next ring
    while rings:
        j = min(range(len(rings)), key=lambda i: math.dist(pos, rings[i][0]))
        r = rings.pop(j)
        order.append(r)
        pos = r[-1]
    return order


def offset_poly(pts, d):
    """A closed polyline moved d mm outwards (d < 0: inwards) - for imported outlines; [] when it vanishes."""
    if not AVAILABLE:
        return []
    off = pyclipper.PyclipperOffset()
    off.AddPath([(round(x * SCALE), round(y * SCALE)) for x, y in pts], pyclipper.JT_ROUND, pyclipper.ET_CLOSEDPOLYGON)
    return [r + [r[0]] for r in _paths(off.Execute(d * SCALE)) if len(r) > 2]
