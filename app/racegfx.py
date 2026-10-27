"""PICO RUSH graphics: the sky, roadside sprites, cars and the HUD - all drawn in code (no image files),
big and smooth once, then cached at the sizes the road asks for.

Sizes are native pixels; K = screen width / 320 (1 on the PicoCalc, 0.4 on the HAT).
"""
import bisect
import math
import random

import numpy as np
import pygame

import lcd

FD = "/usr/share/fonts/truetype/dejavu/"
# lcd.init() swaps pygame.font.Font for a class that scales to the logical 128x128 screen; the game draws
# in native pixels, so it uses the original class
_FontCls = lcd._Font.__bases__[0] if hasattr(lcd, "_Font") else pygame.font.Font
# ... and swaps pygame.draw for scaling wrappers: keep the originals (this module is imported before init)
poly, line, rect, circle = pygame.draw.polygon, pygame.draw.line, pygame.draw.rect, pygame.draw.circle
KEY = (255, 0, 255)                   # the colour key: keyed sprites blit several times faster than alpha ones
FOG_OF = lambda world_h, height: 0.0  # the racer sets it: the haze of a sprite that big (so: far)


def lerp(a, b, t):
    t = 0.0 if t < 0 else 1.0 if t > 1 else t
    return tuple(int(a[i] + (b[i] - a[i]) * t) for i in range(len(a)))


def font(name, px):
    try:
        return _FontCls(FD + name, max(6, int(px)))
    except (FileNotFoundError, OSError):
        return _FontCls(None, max(6, int(px)))


def bezier(p0, p1, p2, p3, n=14):
    out = []
    for i in range(n + 1):
        t = i / n
        u = 1 - t
        out.append((u ** 3 * p0[0] + 3 * u * u * t * p1[0] + 3 * u * t * t * p2[0] + t ** 3 * p3[0],
                    u ** 3 * p0[1] + 3 * u * u * t * p1[1] + 3 * u * t * t * p2[1] + t ** 3 * p3[1]))
    return out


# ---------------------------------------------------------------- the sky

def make_sky(w, hor, seed=11):
    """A blue gradient, cumulus piles, a far city on the right and a headland on the left (2x wide: it
    scrolls with the curves)."""
    sw = w * 2
    s = pygame.Surface((sw, hor + 2))
    for y in range(hor + 2):
        s.fill(lerp((40, 110, 220), (176, 214, 246), (y / (hor + 1)) ** 0.9), (0, y, sw, 1))
    rnd = random.Random(seed)
    k = w / 320
    for _ in range(9):
        cx, cy, sz = rnd.uniform(0, sw), rnd.uniform(hor * 0.12, hor * 0.7), rnd.uniform(0.7, 1.6)
        for _ in range(int(24 * sz)):
            r = max(2, int(rnd.randint(6, int(18 * sz)) * k))
            x, y = cx + rnd.gauss(0, 22 * sz * k), cy + abs(rnd.gauss(0, 7 * sz * k))
            puff = pygame.Surface((2 * r, 2 * r), pygame.SRCALPHA)
            pygame.draw.circle(puff, (255, 255, 255, 58), (r, r), r)
            pygame.draw.circle(puff, (255, 255, 255, 86), (r - r // 4, r - r // 4), max(1, r * 2 // 3))
            s.blit(puff, (x - r, y - r))
            if x - r < 0:
                s.blit(puff, (x - r + sw, y - r))
            if x + r > sw:
                s.blit(puff, (x - r - sw, y - r))
    # the far city
    x = 0.0
    while x < sw:
        if (x // (w * 0.5)) % 2 == 1:                  # skyline blocks every other half screen
            bw, bh = rnd.uniform(8, 18) * k, rnd.uniform(8, 34) * k
            col = rnd.choice([(196, 186, 170), (170, 168, 172), (214, 204, 186), (150, 160, 176)])
            c = lerp(col, (180, 205, 235), 0.5)
            pygame.draw.rect(s, c, (x, hor - bh, bw, bh + 2))
            for wy in range(int(hor - bh + 3 * k), hor, max(2, int(4 * k))):
                pygame.draw.line(s, lerp(c, (120, 140, 170), 0.5), (x + 2 * k, wy), (x + bw - 3 * k, wy), 1)
            x += bw + rnd.uniform(0, 3) * k
        else:
            pts = [(x, hor)]
            for i in range(9):
                pts.append((x + i * w * 0.0625, hor - (math.sin(i / 8 * math.pi) * 16 + rnd.uniform(0, 4)) * k))
            pts.append((x + w * 0.5, hor))
            pygame.draw.polygon(s, (150, 128, 158), pts)
            x += w * 0.5
    return s


# ---------------------------------------------------------------- sprites (masters drawn big)

def _palm(h):
    w = int(h * 0.7)
    s = pygame.Surface((w, h), pygame.SRCALPHA)
    cx = w * 0.5
    pts = [(cx + math.sin(t / 10 * 1.6) * w * 0.1, h - t / 10 * h * 0.8) for t in range(11)]
    for i in range(10):
        c = lerp((156, 124, 84), (112, 88, 60), i % 2)
        pygame.draw.line(s, c, pts[i], pts[i + 1], max(2, int(h * 0.045 * (1 - i / 16))))
    top = pts[-1]
    for k in range(9):
        a = math.radians(-170 + k * 40)
        L = w * 0.5
        p = [top]
        for j in range(1, 7):
            t = j / 6
            p.append((top[0] + math.cos(a) * L * t, top[1] + math.sin(a) * L * t * 0.4 + L * 0.42 * t * t))
        pygame.draw.lines(s, (36, 116, 48), False, p, max(2, int(h * 0.04)))
        pygame.draw.lines(s, (92, 172, 72), False, p[:4], max(1, int(h * 0.02)))
    return s


def _building(h, variant):
    rnd = random.Random(variant * 7 + 3)
    w = int(h * (0.55 + 0.3 * rnd.random()))
    s = pygame.Surface((w, h), pygame.SRCALPHA)
    base = [(216, 206, 186), (196, 190, 196), (226, 214, 190), (180, 196, 214), (232, 222, 208),
            (206, 180, 160)][variant % 6]
    s.fill(base + (255,))
    pygame.draw.rect(s, lerp(base, (0, 0, 0), 0.25), (w * 0.82, 0, w * 0.18, h))
    pygame.draw.rect(s, lerp(base, (255, 255, 255), 0.4), (0, 0, w, max(2, h // 40)))
    rows = 6 + variant % 5
    for r in range(1, rows):
        y = h * r / rows
        for c in range(5):
            x = w * (0.06 + c * 0.155)
            pygame.draw.rect(s, lerp((70, 92, 124), (190, 216, 244), rnd.random() * 0.55),
                             (x, y, w * 0.1, h / rows * 0.55))
    if variant % 3 == 0:                               # balconies
        for r in range(1, rows):
            pygame.draw.line(s, lerp(base, (0, 0, 0), 0.3), (0, h * r / rows + h / rows * 0.6),
                             (w * 0.82, h * r / rows + h / rows * 0.6), max(1, h // 120))
    pygame.draw.rect(s, lerp(base, (0, 0, 0), 0.35), (0, h * 0.92, w, h * 0.08))
    return s


def _lamp(h):
    w = int(h * 0.42)
    s = pygame.Surface((w, h), pygame.SRCALPHA)
    pole = (120, 126, 134)
    pygame.draw.line(s, pole, (w * 0.82, h), (w * 0.82, h * 0.06), max(2, int(h * 0.025)))
    pygame.draw.line(s, pole, (w * 0.82, h * 0.06), (w * 0.12, h * 0.1), max(2, int(h * 0.02)))
    pygame.draw.ellipse(s, (226, 230, 236), (0, h * 0.08, w * 0.3, h * 0.04))
    return s


def _sign(h, variant):
    w = int(h * 1.1)
    s = pygame.Surface((w, h), pygame.SRCALPHA)
    pygame.draw.line(s, (90, 96, 104), (w * 0.2, h), (w * 0.2, h * 0.4), max(2, int(h * 0.04)))
    pygame.draw.line(s, (90, 96, 104), (w * 0.8, h), (w * 0.8, h * 0.4), max(2, int(h * 0.04)))
    board = [((24, 110, 200), "PICO RUSH"), ((220, 60, 40), "ZERO 2 W"), ((30, 150, 90), "COAST 1")][variant % 3]
    pygame.draw.rect(s, board[0], (0, 0, w, h * 0.45), border_radius=int(h * 0.04))
    pygame.draw.rect(s, (255, 255, 255), (0, 0, w, h * 0.45), max(1, int(h * 0.02)), border_radius=int(h * 0.04))
    f = font("DejaVuSans-BoldOblique.ttf", h * 0.2)
    t = f.render(board[1], True, (255, 255, 255))
    s.blit(t, (w / 2 - t.get_width() / 2, h * 0.225 - t.get_height() / 2))
    return s


def _umbrella(h, variant):
    w = int(h * 1.0)
    s = pygame.Surface((w, h), pygame.SRCALPHA)
    pygame.draw.line(s, (240, 240, 240), (w / 2, h), (w / 2, h * 0.2), max(1, int(h * 0.04)))
    col = [(240, 70, 60), (40, 140, 230), (250, 200, 40)][variant % 3]
    pts = [(w * 0.02, h * 0.34)] + bezier((w * 0.02, h * 0.34), (w * 0.2, 0), (w * 0.8, 0), (w * 0.98, h * 0.34)) + [(w * 0.98, h * 0.34)]
    pygame.draw.polygon(s, col, pts)
    for i in range(1, 4):
        pygame.draw.line(s, (255, 255, 255), (w / 2, h * 0.08), (w * i / 4, h * 0.34), max(1, int(h * 0.02)))
    return s


# world sizes (road half width = 1000): height of the sprite, and a painter
KINDS = {
    "palm": (2600, lambda h, v: _palm(h)),
    "building": (5200, _building),
    "lamp": (2600, lambda h, v: _lamp(h)),
    "sign": (1400, _sign),
    "umbrella": (900, _umbrella),
}
LEVELS = sorted(set(int(3 * 1.09 ** i) for i in range(60) if 3 * 1.09 ** i <= 330))   # 3 .. 330 px, 9 % apart
_masters = {}
_cache = {}


def level(px):
    i = bisect.bisect_left(LEVELS, px)
    if i >= len(LEVELS):
        return LEVELS[-1]
    if i and px - LEVELS[i - 1] < LEVELS[i] - px:
        return LEVELS[i - 1]
    return LEVELS[i]


def keyed(img, haze=None, fog=0.0, opaque=False):
    """A fast surface: hazed, its soft edges cut at half alpha, transparent by the colour key."""
    if fog > 0.02 and haze is not None:
        img = img.copy()
        img.fill(lerp((255, 255, 255), haze, fog * 0.8) + (255,), special_flags=pygame.BLEND_RGBA_MULT)
        add = pygame.Surface(img.get_size(), pygame.SRCALPHA)
        add.fill(tuple(int(c * fog * 0.5) for c in haze) + (0,))
        img.blit(add, (0, 0), special_flags=pygame.BLEND_RGB_ADD)
    if opaque:
        out = pygame.Surface(img.get_size())
        out.blit(img, (0, 0))
        return out
    a = pygame.surfarray.pixels_alpha(img)
    a[:] = np.where(a >= 110, 255, 0).astype(np.uint8)
    del a
    out = pygame.Surface(img.get_size())
    out.fill(KEY)
    out.blit(img, (0, 0))
    out.set_colorkey(KEY, pygame.RLEACCEL)
    return out


def sprite(kind, variant, height, haze):
    """The sprite at about `height` px (hazed as far as that size means); cached by size level."""
    if height < 3:
        return None
    lv = level(height)
    key = (kind, variant, lv)
    img = _cache.get(key)
    if img is None:
        mk = (kind, variant)
        master = _masters.get(mk)
        if master is None:
            master = KINDS[kind][1](360, variant)
            _masters[mk] = master
        w = max(1, int(master.get_width() * lv / master.get_height()))
        img = keyed(pygame.transform.smoothscale(master, (w, lv)), haze, FOG_OF(KINDS[kind][0], lv),
                    opaque=(kind == "building"))
        _cache[key] = img
    return img


# ---------------------------------------------------------------- cars (rear view)

def _shade(mask, rect, top, mid, bottom):
    x, y, w, h = rect
    g = pygame.Surface(mask.get_size(), pygame.SRCALPHA)
    for yy in range(int(y), int(y + h)):
        t = (yy - y) / max(1, h)
        c = lerp(top, mid, t / 0.45) if t < 0.45 else lerp(mid, bottom, (t - 0.45) / 0.55)
        g.fill(c + (255,), (0, yy, g.get_width(), 1))
    g.blit(mask, (0, 0), special_flags=pygame.BLEND_RGBA_MULT)
    return g


def car_master(width, body, lean=0.0, brake=False, convertible=True, van=False):
    """A rounded rear view drawn 3x big, smoothly scaled to `width`."""
    S = 3
    w = width * S
    h = int(width * (0.8 if van else 0.66)) * S
    img = pygame.Surface((w, h), pygame.SRCALPHA)
    for k in range(10):
        pygame.draw.ellipse(img, (0, 0, 0, 14), (w * 0.02 + k * w * 0.008, h * 0.80 + k * h * 0.004,
                                                 w * 0.96 - k * w * 0.016, h * 0.2 - k * h * 0.008))
    for x0 in (0.04, 0.78):
        pygame.draw.rect(img, (22, 22, 26), (w * x0, h * 0.66, w * 0.18, h * 0.26), border_radius=int(w * 0.03))
        pygame.draw.rect(img, (52, 52, 58), (w * (x0 + 0.02), h * 0.68, w * 0.05, h * 0.2), border_radius=int(w * 0.02))
    off = lean * w * 0.03
    hi = lerp(body, (255, 255, 255), 0.45)
    lo = lerp(body, (0, 0, 0), 0.55)
    if van:                                            # a delivery van: a tall box with round corners
        box = pygame.Surface((w, h), pygame.SRCALPHA)
        pygame.draw.rect(box, (255, 255, 255, 255), (w * 0.04, h * 0.04, w * 0.92, h * 0.8), border_radius=int(w * 0.06))
        img.blit(_shade(box, (0, h * 0.04, w, h * 0.8), hi, body, lo), (0, 0))
        pygame.draw.line(img, lo, (w * 0.5, h * 0.1), (w * 0.5, h * 0.62), max(2, int(w * 0.01)))
        for cx in (0.12, 0.88):
            pygame.draw.rect(img, (200, 20, 26), (w * cx - w * 0.04, h * 0.5, w * 0.08, h * 0.12), border_radius=int(w * 0.01))
        pygame.draw.rect(img, (238, 238, 232), (w * 0.4, h * 0.68, w * 0.2, h * 0.07))
        pygame.draw.rect(img, (30, 30, 34), (w * 0.08, h * 0.78, w * 0.84, h * 0.07))
        return pygame.transform.smoothscale(img, (width, h // S))
    outline = []
    outline += bezier((w * 0.03, h * 0.78), (w * 0.0, h * 0.55), (w * 0.02, h * 0.36), (w * 0.14, h * 0.32))
    outline += bezier((w * 0.14, h * 0.32), (w * 0.26, h * 0.28), (w * 0.3 + off, h * 0.34), (w * 0.5 + off, h * 0.34))
    outline += bezier((w * 0.5 + off, h * 0.34), (w * 0.7 + off, h * 0.34), (w * 0.74, h * 0.28), (w * 0.86, h * 0.32))
    outline += bezier((w * 0.86, h * 0.32), (w * 0.98, h * 0.36), (w * 1.0, h * 0.55), (w * 0.97, h * 0.78))
    outline += bezier((w * 0.97, h * 0.78), (w * 0.8, h * 0.86), (w * 0.2, h * 0.86), (w * 0.03, h * 0.78))
    mask = pygame.Surface((w, h), pygame.SRCALPHA)
    pygame.draw.polygon(mask, (255, 255, 255, 255), outline)
    img.blit(_shade(mask, (0, h * 0.28, w, h * 0.6), hi, body, lo), (0, 0))
    for side in (0, 1):
        pts = bezier((w * (0.05 if not side else 0.95), h * 0.5), (w * (0.06 if not side else 0.94), h * 0.36),
                     (w * (0.14 if not side else 0.86), h * 0.33), (w * (0.26 if not side else 0.74), h * 0.33), 10)
        pygame.draw.lines(img, lerp(body, (255, 255, 255), 0.75), False, pts, max(2, int(w * 0.008)))
    if convertible:
        pygame.draw.polygon(img, (26, 24, 28), [(w * 0.24 + off, h * 0.34), (w * 0.76 + off, h * 0.34),
                                                (w * 0.7 + off * 1.6, h * 0.2), (w * 0.3 + off * 1.6, h * 0.2)])
        for x0 in (0.3, 0.56):
            pygame.draw.ellipse(img, (40, 36, 40), (w * x0 + off * 1.8, h * 0.13, w * 0.14, h * 0.14))
            pygame.draw.ellipse(img, (70, 66, 70), (w * (x0 + 0.02) + off * 1.8, h * 0.14, w * 0.06, h * 0.05))
        pygame.draw.line(img, (40, 40, 44), (w * 0.27 + off * 2, h * 0.1), (w * 0.73 + off * 2, h * 0.1), max(2, int(w * 0.01)))
    else:
        roof = [(w * 0.2 + off, h * 0.34), (w * 0.8 + off, h * 0.34), (w * 0.7 + off * 1.6, h * 0.1), (w * 0.3 + off * 1.6, h * 0.1)]
        pygame.draw.polygon(img, lerp(body, (0, 0, 0), 0.25), roof)
        glass = [(w * 0.25 + off, h * 0.33), (w * 0.75 + off, h * 0.33), (w * 0.67 + off * 1.6, h * 0.13), (w * 0.33 + off * 1.6, h * 0.13)]
        pygame.draw.polygon(img, (34, 44, 66), glass)
        pygame.draw.line(img, (110, 130, 170), (w * 0.36 + off * 1.6, h * 0.15), (w * 0.45 + off * 1.3, h * 0.31), max(2, int(w * 0.008)))
    pygame.draw.polygon(img, (24, 22, 24), [(w * 0.1, h * 0.48), (w * 0.9, h * 0.48), (w * 0.88, h * 0.62), (w * 0.12, h * 0.62)])
    for cx in (0.18, 0.3, 0.7, 0.82):
        r = w * 0.045
        core = (255, 70, 56) if brake else (200, 20, 26)
        if brake:
            glow = pygame.Surface((int(r * 6), int(r * 6)), pygame.SRCALPHA)
            for k in range(int(r * 3), 0, -max(1, int(r * 0.3))):
                pygame.draw.circle(glow, (255, 40, 40, 12), (int(r * 3), int(r * 3)), k)
            img.blit(glow, (w * cx - r * 3, h * 0.55 - r * 3))
        pygame.draw.circle(img, (60, 10, 12), (w * cx, h * 0.55), r)
        pygame.draw.circle(img, core, (w * cx, h * 0.55), r * 0.8)
        pygame.draw.circle(img, lerp(core, (255, 255, 255), 0.6), (w * cx - r * 0.25, h * 0.55 - r * 0.25), r * 0.25)
    gx0, gx1, gy0, gy1 = w * 0.38, w * 0.62, h * 0.5, h * 0.6
    pygame.draw.rect(img, (50, 50, 54), (gx0, gy0, gx1 - gx0, gy1 - gy0), border_radius=int(w * 0.01))
    for i in range(1, 9):
        x = gx0 + (gx1 - gx0) * i / 9
        pygame.draw.line(img, (20, 20, 22), (x, gy0 + 2), (x, gy1 - 2), max(1, int(w * 0.004)))
    pygame.draw.rect(img, (238, 238, 232), (w * 0.4, h * 0.64, w * 0.2, h * 0.07), border_radius=int(w * 0.006))
    pygame.draw.polygon(img, (30, 30, 34), [(w * 0.14, h * 0.76), (w * 0.86, h * 0.76), (w * 0.8, h * 0.83), (w * 0.2, h * 0.83)])
    for cx in (0.43, 0.57):
        pygame.draw.circle(img, (190, 190, 196), (w * cx, h * 0.79), w * 0.024)
        pygame.draw.circle(img, (40, 40, 44), (w * cx, h * 0.79), w * 0.015)
    return pygame.transform.smoothscale(img, (width, h // S))


TRAFFIC = [  # body colour, convertible, van
    ((240, 240, 236), False, False), ((40, 90, 200), False, False), ((250, 200, 40), False, False),
    ((30, 30, 36), False, False), ((60, 160, 90), False, False), ((230, 230, 232), False, True),
    ((200, 120, 40), False, True), ((150, 30, 40), True, False),
]
_car_cache = {}


CAR_WORLD_W = 940.0                  # = the player car (150 px at its distance): a lane is ~1330 wide


def traffic_car(variant, width, haze):
    if width < 4:
        return None
    lv = level(width)
    key = (variant, lv)
    img = _car_cache.get(key)
    if img is None:
        body, conv, van = TRAFFIC[variant % len(TRAFFIC)]
        mk = ("car", variant)
        master = _masters.get(mk)
        if master is None:
            master = car_master(240, body, convertible=conv, van=van)
            _masters[mk] = master
        img = keyed(pygame.transform.smoothscale(master, (lv, max(1, int(master.get_height() * lv / master.get_width())))),
                    haze, FOG_OF(CAR_WORLD_W, lv))
        _car_cache[key] = img
    return img


VARIANTS = {"palm": 1, "building": 6, "lamp": 1, "sign": 3, "umbrella": 3}


def prewarm_jobs(haze, scale=1.0):
    """Every sprite and car size the road can ask for (up to the screen's size), as small jobs to run while
    the title shows - so the race never stops to scale a picture."""
    top = 330 * scale + 2
    jobs = []
    for lv in LEVELS:
        if lv > top:
            break
        for kind, n in VARIANTS.items():
            for v in range(n):
                jobs.append((sprite, (kind, v, lv, haze)))
        for v in range(len(TRAFFIC)):
            jobs.append((traffic_car, (v, lv, haze)))
    return jobs


# ---------------------------------------------------------------- the HUD

def fancy(text, f, top, bottom, outline=(10, 10, 20), o=2):
    """Outlined text with a vertical gradient fill (the OutRun 2 look)."""
    base = f.render(text, True, (255, 255, 255))
    w, h = base.get_width() + 2 * o, base.get_height() + 2 * o
    out = pygame.Surface((w, h), pygame.SRCALPHA)
    sh = f.render(text, True, outline)
    for dx in range(-o, o + 1):
        for dy in range(-o, o + 1):
            if dx * dx + dy * dy <= o * o + 1:
                out.blit(sh, (o + dx, o + dy))
    g = pygame.Surface(base.get_size(), pygame.SRCALPHA)
    for y in range(base.get_height()):
        g.fill(lerp(top, bottom, y / max(1, base.get_height() - 1)) + (255,), (0, y, base.get_width(), 1))
    g.blit(base, (0, 0), special_flags=pygame.BLEND_RGBA_MULT)
    out.blit(g, (o, o))
    return out


class Digits:
    """Fancy glyphs rendered once; strings of digits and marks are put together from them."""

    def __init__(self, f, top, bottom, o=2, chars="0123456789'\".:-x+"):
        self.g = {c: fancy(c, f, top, bottom, o=o) for c in chars}
        self.adv = max(self.g[c].get_width() for c in "0123456789") - 2 * o
        self.o = o
        self.h = self.g["0"].get_height()

    def width(self, s):
        return sum((self.adv if c.isdigit() else self.g[c].get_width() - 2 * self.o) for c in s if c in self.g) + 2 * self.o

    def draw(self, surf, s, x, y, align="left"):
        if align == "center":
            x -= self.width(s) / 2
        elif align == "right":
            x -= self.width(s)
        for c in s:
            g = self.g.get(c)
            if g is None:
                continue
            adv = self.adv if c.isdigit() else g.get_width() - 2 * self.o
            surf.blit(g, (x + (adv - (g.get_width() - 2 * self.o)) / 2, y))
            x += adv


def emblem(text, K):
    """The label with a dashed ring and a fading bar."""
    f = font("DejaVuSans-BoldOblique.ttf", 13 * K)
    t = fancy(text, f, (255, 250, 170), (255, 170, 20), o=max(1, int(2 * K)))
    w = int(max(124 * K, t.get_width() + 24 * K))
    s = pygame.Surface((w, int(22 * K)), pygame.SRCALPHA)
    bar = pygame.Surface((int(110 * K), int(14 * K)), pygame.SRCALPHA)
    for x in range(bar.get_width()):
        bar.fill((255, 255, 255, int(150 * (1 - x / bar.get_width()))), (x, 0, 1, bar.get_height()))
    s.blit(bar, (14 * K, 4 * K))
    c = (int(9 * K), int(10 * K))
    pygame.draw.circle(s, (255, 255, 255), c, max(2, int(9 * K)), max(1, int(2 * K)))
    for i in range(1, 12, 2):
        a = math.radians(i * 30)
        pygame.draw.circle(s, (40, 120, 220), (c[0] + math.cos(a) * 9 * K, c[1] + math.sin(a) * 9 * K), max(1, int(2 * K)))
    s.blit(t, (20 * K, 1 * K))
    return s


def gauge_face(R, K):
    s = pygame.Surface((2 * R + 2, 2 * R + 2), pygame.SRCALPHA)
    c = (R + 1, R + 1)
    for k in range(R, 0, -1):
        pygame.draw.circle(s, lerp((76, 78, 86), (18, 20, 26), k / R) + (235,), c, k)
    pygame.draw.circle(s, (230, 232, 238), c, R, max(1, int(2 * K)))
    f = font("DejaVuSansCondensed-Bold.ttf", 9 * K)
    for i in range(11):
        a = math.radians(225 - i * 27)
        p1 = (c[0] + math.cos(a) * (R - 3 * K), c[1] - math.sin(a) * (R - 3 * K))
        p2 = (c[0] + math.cos(a) * (R - 8 * K), c[1] - math.sin(a) * (R - 8 * K))
        pygame.draw.line(s, (255, 70, 60) if i >= 9 else (240, 240, 240), p1, p2, max(1, int(2 * K)))
        if i % 2 == 0:
            t = f.render(str(i * 3) if i else "0", True, (240, 240, 240))
            s.blit(t, (c[0] + math.cos(a) * (R - 15 * K) - t.get_width() / 2,
                       c[1] - math.sin(a) * (R - 15 * K) - t.get_height() / 2))
    t = f.render("×10", True, (180, 180, 190))
    s.blit(t, (c[0] - t.get_width() / 2, c[1] - R * 0.52))
    return s
