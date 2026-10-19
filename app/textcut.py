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
FILLS = ["заливка", "контур"]          # filled letters / along the outline (a V-bit)
FRAMES = ["прямокутник", "коло"]
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
           sh.get("h"), sh.get("cx"), sh.get("cy"), sh.get("r"))
    if key in _cache:
        return _cache[key]
    polys, (x0, y0, x1, y1) = layout(sh.get("text", ""), sh.get("font", FONTS[0]))
    if not polys:
        _cache[key] = []
        return []
    a = math.radians(sh.get("angle", 0.0) or 0.0)
    ca, sa = math.cos(a), math.sin(a)
    mx, my = (x0 + x1) / 2, (y0 + y1) / 2
    corners = [((x - mx) * ca - (y - my) * sa, (x - mx) * sa + (y - my) * ca) for x, y in
               ((x0, y0), (x1, y0), (x1, y1), (x0, y1))]
    if sh.get("frame") == FRAMES[1]:                 # a circle: the turned box's corners inside it
        cx, cy = sh["cx"], sh["cy"]
        far = max(math.hypot(x, y) for x, y in corners) or 1
        k = sh["r"] * 0.98 / far
    else:
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
    if sh.get("fill", FILLS[0]) == FILLS[1] or tool <= 0:
        rings = _paths(shape)
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
