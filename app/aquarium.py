"""Aquarium - our planted tank: two silver and one golden angelfish, neon tetras, red GloFish tetras,
a golden platy, stem plants,
a red bush, a hair-grass tuft, round stones and pebbles, the castle ruins, an air stone, rubber ducks.

It starts like a real tank being switched on: dark water, the lamp clicks and flickers on, then the air
pump starts and the bubbles rise. The still scene (backdrop, plants, stones, castle) is drawn once at double
resolution and smoothed down, then cached (~/.cache/lcdtoy/), so later starts are instant; the fish are
pre-rendered antialiased sprites with a few tilts; the hair grass and the surface move every frame.

Keys (PicoCalc / HAT):
    1 / KEY1      - the lamp on/off (in the dark the neons' blue stripe still glows)
    2 / KEY2      - the air pump on/off
    Enter, Space / PRESS - feed the fish (flakes sink, the fish go after them)
    Esc, 3 / KEY3 - back to the menu

The menu runs it from its own item and once after the device boots (see menu.py); the file
~/.config/lcdtoy/aquarium-on-boot with 0 in it turns the boot start off.
"""
import math
import os
import random
import time

import numpy as np
import pygame
import lcd

FPS = 20
screen = lcd.init()
clock = pygame.time.Clock()
NW, NH = lcd.NATIVE_W, lcd.NATIVE_H
S = lcd.S                       # native pixels per logical one (1 on the HAT, 2.5 on the PicoCalc)
W = H = 128                     # the logical tank
SURFACE_Y = 9                   # the water line
FONT_DIR = "/usr/share/fonts/truetype/dejavu/"
CACHE = os.path.expanduser("~/.cache/lcdtoy")
SCENE_VERSION = 4               # bump when the still scene changes (the cache is keyed on it)
rng = random.Random()

canvas = pygame.Surface((NW, NH))   # everything is drawn here in native pixels, then shown at once


def P(x, y):
    """A logical point -> native pixels."""
    return (x * S, y * S)


def font(name, px):
    size = px / S if S != 1 else px
    try:
        return pygame.font.Font(FONT_DIR + name, size)
    except (FileNotFoundError, OSError):
        return pygame.font.Font(None, size)


BIG = S > 1
f_title = font("DejaVuSans-Bold.ttf", 26 if BIG else 13)
f_hint = font("DejaVuSans.ttf", 12 if BIG else 7)


def mix(a, b, t):
    return tuple(int(a[i] + (b[i] - a[i]) * t) for i in range(3))


def ground_line(x):
    """The top of the gravel at logical x (a little higher at the back corners)."""
    return 103 + 1.6 * math.sin(x * 0.06 + 0.4) + 1.0 * math.sin(x * 0.19 + 1.1)


# ---------------------------------------------------------------- the still scene (built once, cached)

class Pen:
    """Draws in logical coordinates on a supersampled surface."""

    def __init__(self, surf, k):
        self.s, self.k = surf, k

    def p(self, x, y):
        return (x * self.k, y * self.k)

    def w(self, v):
        return max(1, int(round(v * self.k)))

    def line(self, c, a, b, width):
        pygame.draw.line(self.s, c, self.p(*a), self.p(*b), self.w(width))

    def poly(self, c, pts):
        pygame.draw.polygon(self.s, c, [self.p(*q) for q in pts])

    def circle(self, c, xy, r):
        pygame.draw.circle(self.s, c, self.p(*xy), max(1, r * self.k))

    def ellipse(self, c, x, y, rx, ry):
        pygame.draw.ellipse(self.s, c, (*self.p(x - rx, y - ry), 2 * rx * self.k, 2 * ry * self.k))


def leaf_pts(cx, cy, length, width, angle, bend=0.0):
    """A lens-shaped leaf from (cx, cy) along angle (radians, 0 = up), slightly bent."""
    pts_l, pts_r = [], []
    sa, ca = math.sin(angle), -math.cos(angle)
    for k in range(9):
        t = k / 8
        ax = cx + sa * length * t + bend * t * t * math.cos(angle)
        ay = cy + ca * length * t + bend * t * t * math.sin(angle)
        hw = width / 2 * math.sin(math.pi * t) ** 0.8
        pts_l.append((ax - ca * hw, ay + sa * hw))
        pts_r.append((ax + ca * hw, ay - sa * hw))
    return pts_l + pts_r[::-1]


def smooth_noise(r, size, cells):
    """Smooth value noise 0..1 of size x size from a cells x cells random grid."""
    vals = (r.random((cells, cells)) * 255).astype(np.uint8)
    small = pygame.surfarray.make_surface(np.repeat(vals[..., None], 3, axis=2))
    big = pygame.transform.smoothscale(pygame.transform.smoothscale(small, (cells * 4, cells * 4)), (size, size))
    return pygame.surfarray.array3d(big)[..., 0].T.astype(np.float32) / 255


def shade_ellipses(arr, k, stones, light=(-0.45, -0.65, 0.62), seed=1):
    """Round stones / pebbles with sphere shading and grain, straight into an (H, W, 3) float array."""
    r = np.random.default_rng(seed)
    lx, ly, lz = light
    for cx, cy, rx, ry, lo, hi, holes in stones:
        x0, x1 = int((cx - rx - 1) * k), int((cx + rx + 1) * k) + 1
        y0, y1 = int((cy - ry - 1) * k), int((cy + ry + 1) * k) + 1
        x0, y0 = max(0, x0), max(0, y0)
        x1, y1 = min(arr.shape[1], x1), min(arr.shape[0], y1)
        yy, xx = np.mgrid[y0:y1, x0:x1].astype(np.float32)
        u, v = (xx / k - cx) / rx, (yy / k - cy) / ry
        r2 = u * u + v * v
        inside = r2 < 1
        nz = np.sqrt(np.clip(1 - r2, 0, 1))
        lit = np.clip(u * lx + v * ly + nz * lz, 0, 1) ** 1.2
        lo_, hi_ = np.array(lo, np.float32), np.array(hi, np.float32)
        col = lo_ + (hi_ - lo_) * lit[..., None]
        col *= (1 + r.normal(0, 0.06, col.shape[:2]))[..., None]
        for hx, hy, hr in holes:                         # dark pits (the mossy stone)
            d = ((xx / k - hx) ** 2 + (yy / k - hy) ** 2) / (hr * hr)
            col *= np.clip(0.35 + 0.65 * d, 0.35, 1)[..., None]
        reg = arr[y0:y1, x0:x1]
        reg[inside] = col[inside]


def build_scene():
    """The backdrop, the plants that stay still, the castle, the stones; and the front pebbles (alpha)."""
    SS = 2
    k = S * SS
    size = int(W * k)
    r = random.Random(11)
    nr = np.random.default_rng(5)

    # the blue backdrop with a soft stone-and-water pattern, lighter up under the lamp
    yy = np.linspace(0, 1, size, dtype=np.float32)[:, None]
    base_top, base_bot = np.array([104, 186, 232], np.float32), np.array([30, 104, 176], np.float32)
    img = base_top * (1 - yy[..., None]) + base_bot * yy[..., None]
    tex = smooth_noise(nr, size, 10) * 0.6 + smooth_noise(nr, size, 28) * 0.4
    waves = np.sin(np.arange(size, dtype=np.float32)[:, None] / k * 0.55 + tex * 9) * 0.5 + 0.5
    img = img * (0.78 + 0.32 * tex[..., None]) + 18 * (waves[..., None] - 0.5)
    xx = np.linspace(-1, 1, size, dtype=np.float32)[None, :, None]
    img *= 1 - 0.18 * xx ** 2

    # the gravel: dark, speckled, lighter towards the front glass
    gl = np.array([ground_line(x / k) * k for x in range(size)], np.float32)
    row = np.arange(size, dtype=np.float32)[:, None]
    below = row >= gl[None, :]
    depth = np.clip((row - gl[None, :]) / ((W - 100) * k), 0, 1)[..., None]
    gravel = np.array([58, 54, 46], np.float32) * (1 - depth) + np.array([104, 96, 80], np.float32) * depth
    grain = nr.random((size, size))
    speck = np.where(grain[..., None] > 0.82, np.array([150, 140, 120], np.float32),
                     np.where(grain[..., None] < 0.15, np.array([30, 28, 24], np.float32), gravel))
    gravel = gravel * 0.45 + speck * 0.55
    img[below] = gravel[below]
    surf = pygame.Surface((size, size))
    pygame.surfarray.blit_array(surf, np.clip(img, 0, 255).astype(np.uint8).swapaxes(0, 1))
    pen = Pen(surf, k)

    # the lamp's reflection just under the surface
    band = pygame.Surface((size, int(6 * k)), pygame.SRCALPHA)
    for i in range(int(6 * k)):
        pygame.draw.line(band, (230, 250, 255, int(110 * (1 - i / (6 * k)) ** 2)), (0, i), (size, i))
    surf.blit(band, (0, int(SURFACE_Y * k)))

    # far stem plants, bluish and pale (depth)
    far = pygame.Surface((size, size), pygame.SRCALPHA)
    fpen = Pen(far, k)
    for _ in range(16):
        stem_plant(fpen, r.uniform(36, 96), ground_line(60) - 2, r.uniform(26, 54), r.uniform(-5, 5),
                   (60, 150, 130), (120, 200, 170), r, alpha=120)
    surf.blit(far, (0, 0))

    castle(pen, r)

    # the heater in the back right corner
    pen.poly((190, 220, 230), [(119.5, 14), (122.5, 14), (122.5, 66), (119.5, 66)])
    pen.poly((90, 96, 100), [(120.4, 22), (121.6, 22), (121.6, 62), (120.4, 62)])
    pen.poly((40, 44, 50), [(119, 12), (123, 12), (123, 16), (119, 16)])

    # the dense stem plants on the left, up to the surface
    for i in range(18):
        x = r.uniform(1, 40) if i < 14 else r.uniform(40, 52)
        stem_plant(pen, x, ground_line(x) + 1, r.uniform(48, 92) if x < 36 else r.uniform(26, 40), r.uniform(-7, 7),
                   (34, 112, 46), (132, 208, 92), r)

    # broad-leaved plants in the middle (anubias-like)
    for _ in range(14):
        a = r.uniform(-1.1, 1.1)
        x0 = r.uniform(40, 54)
        base = ground_line(x0)
        ln = r.uniform(5, 13)
        tip = (x0 + math.sin(a) * ln, base - math.cos(a) * ln)
        pen.line((46, 110, 50), (x0, base), tip, 0.5)
        lp = leaf_pts(*tip, r.uniform(8, 12), r.uniform(3.6, 5.0), a * 0.8, r.uniform(-1.5, 1.5))
        pen.poly(r.choice(((38, 124, 52), (50, 140, 60), (30, 104, 46))), lp)
        pygame.draw.aalines(surf, (100, 176, 90), False, [pen.p(*q) for q in lp[:9]])

    # small round leaves by the castle
    for _ in range(40):
        x, y = r.uniform(84, 100), r.uniform(84, 102)
        pen.line((60, 130, 60), (x, ground_line(x)), (x, y), 0.3)
        pen.circle(r.choice(((86, 182, 72), (70, 164, 64), (110, 200, 90))), (x, y), r.uniform(1.3, 2.1))

    # the red-purple bush at the bottom left
    for _ in range(26):
        x0 = r.uniform(16, 34)
        base = ground_line(x0)
        h = r.uniform(10, 22)
        lean = r.uniform(-5, 5)
        pen.line((90, 40, 60), (x0, base), (x0 + lean, base - h), 0.4)
        for j in range(6):
            t = (j + 1) / 7
            cx, cy = x0 + lean * t, base - h * t
            for side in (-1, 1):
                lp = leaf_pts(cx, cy, r.uniform(2.6, 3.8), r.uniform(1.4, 2.0), side * r.uniform(0.7, 1.4))
                pen.poly(r.choice(((150, 40, 92), (124, 32, 84), (178, 66, 112), (100, 58, 72))), lp)

    # the stones: a dark mossy one with pits and a light rounded one
    arr = pygame.surfarray.pixels3d(surf).swapaxes(0, 1).astype(np.float32)
    shade_ellipses(arr, k, [
        (34, 100, 11, 8, (34, 48, 32), (120, 142, 92), [(29, 98, 1.6), (36, 96, 1.2), (40, 101, 1.5), (31, 103, 1.0)]),
        (60, 99, 8.5, 7.5, (130, 120, 86), (236, 226, 190), []),
    ], seed=2)
    pygame.surfarray.blit_array(surf, np.clip(arr, 0, 255).astype(np.uint8).swapaxes(0, 1))

    # the front pebbles: a separate layer over the fish swimming low
    front = pygame.Surface((size, size), pygame.SRCALPHA)
    farr = np.zeros((size, size, 3), np.float32)
    mask = np.zeros((size, size), bool)
    pebbles = []
    for _ in range(60):
        x = r.uniform(14, 96)
        y = r.uniform(ground_line(x) + 3, 124)
        rad = r.uniform(1.8, 3.6) * (0.75 + 0.4 * (y - 104) / 20)
        lo, hi = r.choice((((70, 86, 64), (178, 196, 160)), ((112, 104, 84), (232, 222, 192)),
                           ((90, 92, 86), (196, 198, 186))))
        pebbles.append((x, y, rad, rad * 0.75, lo, hi, []))
    shade_ellipses(farr, k, pebbles, seed=3)
    for cx, cy, rx, ry, *_ in pebbles:
        yy2, xx2 = np.ogrid[:size, :size]
        mask |= (((xx2 / k - cx) / rx) ** 2 + ((yy2 / k - cy) / ry) ** 2) < 1
    pygame.surfarray.blit_array(front, np.clip(farr, 0, 255).astype(np.uint8).swapaxes(0, 1))
    a = pygame.surfarray.pixels_alpha(front)
    a[:] = (mask.T * 255).astype(np.uint8)
    del a
    # the little shipwreck in the front left corner, lying on its side
    fpen2 = Pen(front, k)
    hull = [(3, 116), (5, 111), (13, 108), (19, 110), (17, 115), (9, 119)]
    fpen2.poly((214, 212, 200), hull)
    fpen2.poly((160, 158, 146), [(9, 119), (17, 115), (19, 110), (18.5, 113), (16, 117)])
    fpen2.poly((120, 84, 54), [(6, 112.5), (12, 110.5), (12.5, 111.6), (6.5, 113.6)])      # the deck rail
    fpen2.line((150, 110, 70), (10, 110), (12, 101), 0.6)                               # a broken mast
    fpen2.line((150, 110, 70), (11.4, 104), (14.5, 104.6), 0.4)
    for wx, wy in ((8, 115), (11, 114), (14, 112.6)):                                    # portholes
        fpen2.circle((60, 60, 64), (wx, wy), 0.7)
    fpen2.poly((80, 140, 70), [(4, 116.5), (6, 114), (7, 116.5)])                        # moss

    native = (NW, NH)
    return pygame.transform.smoothscale(surf, native), pygame.transform.smoothscale(front, native)


def stem_plant(pen, x, y0, h, lean, dark, light, r, alpha=255):
    """A stem with whorls of fine needle leaves (cabomba / ambulia), lighter at the young top."""
    nodes = max(4, int(h / 2.3))
    prev = (x, y0)
    for i in range(nodes + 1):
        t = i / nodes
        cx = x + lean * t * t + math.sin(t * 5 + x) * 0.8
        cy = y0 - h * t
        c = mix(dark, light, t ** 1.4)
        pen.line((*mix(dark, (20, 60, 30), 0.3), alpha), prev, (cx, cy), 0.35)
        prev = (cx, cy)
        ln = 2.2 + 1.8 * math.sin(math.pi * min(1, t * 1.3)) * (1 - 0.5 * t)
        n = 7
        rot = r.uniform(0, 1)
        for j in range(n):
            ang = (j + rot) / n * 2 * math.pi
            dx = math.cos(ang) * ln
            dy = math.sin(ang) * ln * 0.45 - ln * 0.35        # flattened whorl, needles bend upwards
            cc = mix(c, (200, 240, 160), r.uniform(0, 0.25)) if r.random() < 0.3 else c
            pen.line((*cc, alpha), (cx, cy), (cx + dx, cy + dy), 0.3)


def castle(pen, r):
    """The ruins of a castle on the right: a tall tower and a lower wall, with arches and moss."""
    stone, dark, line, shade = (196, 176, 128), (52, 46, 38), (160, 140, 100), (150, 130, 94)
    # the low wall in front-left of the tower
    pen.poly(shade, [(84, 104), (84, 84), (87, 82), (90, 84), (93, 82), (96, 84), (98, 83), (98, 104)])
    pen.poly(stone, [(84.5, 104), (84.5, 85), (87, 83), (90, 85), (93, 83), (95.5, 85), (95.5, 104)])
    # the tower
    tw = [(96, 104), (96, 60), (98, 60), (98, 57), (101, 57), (101, 60), (104, 60), (104, 57), (107, 57),
          (107, 60), (110, 60), (110, 57), (113, 57), (113, 60), (116, 60), (116, 104)]
    pen.poly(stone, tw)
    pen.poly(shade, [(111, 60), (116, 60), (116, 104), (111, 104)])
    for y in range(62, 104, 4):                           # the stone courses
        pen.line(line, (96, y), (116, y), 0.3)
        off = 0 if (y // 4) % 2 else 2.5
        for x in range(96, 116, 5):
            pen.line(line, (x + off, y), (x + off, y + 4), 0.3)
    for y in range(87, 104, 4):
        pen.line(line, (84.5, y), (95.5, y), 0.3)
    # arched windows and a door
    for cx, cy, w, h in ((106, 70, 4, 7), (101, 84, 3.2, 5.5), (110, 88, 3.2, 5.5), (90, 96, 4, 8)):
        pen.poly(dark, [(cx - w / 2, cy + h / 2), (cx - w / 2, cy - h / 2 + w / 2), (cx + w / 2, cy - h / 2 + w / 2),
                        (cx + w / 2, cy + h / 2)])
        pen.circle(dark, (cx, cy - h / 2 + w / 2), w / 2)
    # a broken top edge and moss
    pen.poly((70, 150, 70), [(96, 60), (99, 59), (101, 62), (97, 64)])
    for _ in range(30):
        x, y = r.uniform(96, 111), r.uniform(58, 104)
        if r.random() < 0.5:
            pen.circle(r.choice(((80, 150, 70), (60, 130, 60))), (x, y), r.uniform(0.4, 1.0))


def load_scene():
    """The still scene from the cache, or built (a few seconds on the Zero) and cached."""
    name = os.path.join(CACHE, "aquarium-v%d-%dx%d" % (SCENE_VERSION, NW, NH))
    try:
        return pygame.image.load(name + "-bg.png"), pygame.image.load(name + "-front.png")
    except (pygame.error, FileNotFoundError, OSError):
        pass
    bg, front = build_scene()
    try:
        os.makedirs(CACHE, exist_ok=True)
        pygame.image.save(bg, name + "-bg.png")
        pygame.image.save(front, name + "-front.png")
    except (pygame.error, OSError):
        pass
    return bg, front


def build_rays():
    """Two layers of soft light rays from the lamp (their brightness pulses in turn)."""
    layers = []
    fade = np.clip(1 - np.linspace(0, 1, NH) * 1.2, 0, 1) ** 1.5
    for xs in ((24, 60, 98), (40, 80, 112)):
        s = pygame.Surface((NW, NH), pygame.SRCALPHA)
        for x in xs:
            pygame.draw.polygon(s, (240, 255, 255, 40), [P(x - 3, 0), P(x + 4, 0), P(x + 14, 108), P(x - 2, 108)])
        a = pygame.surfarray.pixels_alpha(s)
        a[:] = (a * fade[None, :]).astype(np.uint8)
        del a
        layers.append(s)
    return layers


BACKGROUND, FRONT = load_scene()
# the light rays are baked into the backdrop (two full-screen alpha layers per frame were too slow on the Zero)
for _layer in build_rays():
    _layer.set_alpha(190)
    BACKGROUND.blit(_layer, (0, 0))
BACKGROUND = BACKGROUND.convert(canvas)            # the canvas' pixel format: no conversion on every blit
FRONT = FRONT.convert_alpha()
FRONT_RECT = FRONT.get_bounding_rect()             # the pebbles cover only the bottom: blend just that
FRONT = FRONT.subsurface(FRONT_RECT).copy()
DARK = pygame.Surface((NW, NH), pygame.SRCALPHA)
STRIP = pygame.Surface((NW, NH // 4))              # the dark strip under the key hints
STRIP.fill((4, 14, 20))


# ---------------------------------------------------------------- the hair-grass tuft (moves every frame)

class Grass:
    """Thin bright blades fanning out of one clump between the stones and the castle."""

    def __init__(self, x, n):
        self.x = x
        self.base = ground_line(x) + 1
        self.blades = []
        for i in range(n):
            a = -0.9 + 1.8 * i / (n - 1) + rng.uniform(-0.08, 0.08)
            self.blades.append((a, rng.uniform(12, 24) * (1 - 0.35 * abs(a)), rng.uniform(0, 6.3),
                                rng.choice(((96, 196, 70), (120, 214, 86), (72, 170, 58), (140, 220, 100)))))

    def draw(self, surf, t):
        w = max(1, int(round(0.45 * S)))
        for a, ln, ph, c in self.blades:
            pts = []
            sway = 0.12 * math.sin(t * 0.8 + ph) + 0.05 * math.sin(t * 1.9 + ph * 1.3)
            for k in range(6):
                s = k / 5
                ang = a * (0.6 + 0.7 * s) + sway * s * s
                pts.append(P(self.x + a * 3 + math.sin(ang) * ln * s, self.base - math.cos(ang) * ln * s))
            pygame.draw.lines(surf, c, False, pts, w)


GRASS = [Grass(73, 30), Grass(80, 18)]


# ---------------------------------------------------------------- fish sprites (antialiased, built once)

SS = 3          # supersampling for the sprites
TAIL_FRAMES = 6
TILTS = (-14, -7, 0, 7, 14)     # degrees, nose up .. nose down (facing right)


def sprite_canvas(xmin, xmax, ymin, ymax, size):
    k = S * SS * size
    surf = pygame.Surface((max(1, int((xmax - xmin) * k)), max(1, int((ymax - ymin) * k))), pygame.SRCALPHA)

    def T(x, y):
        return ((x - xmin) * k, (y - ymin) * k)
    return surf, T, k


def finish(surf, size, xmin, xmax, ymin, ymax):
    w, h = max(1, int((xmax - xmin) * S * size)), max(1, int((ymax - ymin) * S * size))
    return pygame.transform.smoothscale(surf, (w, h))


def angelfish_sprite(size, kind, tail):
    """An angelfish facing right; kind 'silver' (black bars) or 'gold' (koi: orange with black blotches)."""
    X0, X1, Y0, Y1 = -14, 9, -18, 19
    surf, T, k = sprite_canvas(X0, X1, Y0, Y1, size)

    def body_h(x):
        v = 6.9 * math.sqrt(max(0.0, 1 - ((x + 0.3) / 7.1) ** 2))
        return v * (1 - 0.4 * max(0, (x - 3.8) / 3.2))

    gold = kind == "gold"
    fin = (244, 232, 214, 165) if gold else (226, 228, 216, 165)
    a = tail * 0.26

    def rot(x, y):
        dx, dy = x + 6, y
        return (-6 + dx * math.cos(a) - dy * math.sin(a), dx * math.sin(a) + dy * math.cos(a))
    tail_pts = [rot(*p) for p in ((-5.8, -2.6), (-12.5, -6.8), (-10.4, -1.2), (-10.9, 0), (-10.4, 1.2),
                                  (-12.5, 6.8), (-5.8, 2.6))]
    dorsal = [(3.6, -5.0), (1.2, -9.6), (-2.8, -14.4), (-7.0, -16.8), (-5.6, -11.4), (-4.9, -6.6)]
    anal = [(2.4, 5.1), (0.2, 10.0), (-3.4, 14.8), (-7.6, 17.8), (-5.8, 11.8), (-5.0, 6.4)]
    xs = [x / 4 for x in range(-24, 29)]
    top = [(x, -body_h(x) - 0.25) for x in xs]
    bot = [(x, body_h(x) * 0.95) for x in xs]
    body = top + bot[::-1]
    for poly in (tail_pts, dorsal, anal):
        pygame.draw.polygon(surf, fin, [T(*p) for p in poly])
    # fin rays
    for poly in (dorsal, anal):
        for j in range(1, 4):
            q = poly[j]
            pygame.draw.line(surf, (*mix(fin[:3], (120, 110, 90), 0.3), 120), T(*poly[0]), T(*q), max(1, int(0.18 * k)))
    if gold:
        # pearly white body, the head and the front orange, blending through gold into the white
        def gold_col(x):
            u = max(0.0, min(1.0, (x + 1.5) / 5.5))            # 0 at the back, 1 at the head
            if u > 0.55:
                return mix((255, 196, 70), (246, 120, 30), (u - 0.55) / 0.45)
            return mix((240, 236, 226), (255, 196, 70), (u / 0.55) ** 1.6)
        for i in range(len(xs) - 1):
            xa, xb = xs[i], xs[i + 1]
            pygame.draw.polygon(surf, gold_col((xa + xb) / 2), [T(xa, -body_h(xa) - 0.25), T(xb + 0.05, -body_h(xb) - 0.25),
                                                               T(xb + 0.05, body_h(xb) * 0.95), T(xa, body_h(xa) * 0.95)])
        mark = (30, 24, 24, 220)
        # black only at the fins' trailing edges and on the tail, a thin streak along the back
        pygame.draw.polygon(surf, mark, [T(*p) for p in ((-3.0, -12.6), (-6.8, -16.6), (-5.7, -12.0), (-4.6, -9.0))])
        pygame.draw.polygon(surf, mark, [T(*p) for p in ((-3.6, 13.6), (-7.4, 17.6), (-5.9, 12.2), (-4.9, 9.4))])
        pygame.draw.polygon(surf, mark, [T(*rot(*p)) for p in ((-10.4, 1.4), (-12.4, 6.6), (-9.6, 3.6))])
        pygame.draw.line(surf, (60, 40, 30, 150), T(-1.5, -6.0), T(-4.6, -5.0), max(1, int(0.5 * k)))
    else:
        pygame.draw.polygon(surf, (206, 210, 200), [T(*p) for p in body])
        pygame.draw.polygon(surf, (176, 178, 156), [T(x, y) for x, y in top]
                            + [T(x, -body_h(x) * 0.45) for x in xs[::-1]])
        pygame.draw.polygon(surf, (238, 240, 234), [T(x, body_h(x) * 0.25) for x in xs[6:-6]]
                            + [T(x, body_h(x) * 0.8) for x in xs[6:-6][::-1]])
        bar = (28, 28, 32, 235)
        for bx, bw, up, down in ((4.5, 0.9, None, None), (-0.6, 1.5, -10.6, 11.4), (-4.4, 1.3, -14.8, 15.8)):
            y_top = -body_h(bx) - 0.2 if up is None else up
            y_bot = body_h(bx) * 0.95 if down is None else down
            pygame.draw.polygon(surf, bar, [T(bx - bw / 2 + 0.4, y_top), T(bx + bw / 2 + 0.4, y_top),
                                            T(bx + bw / 2 - 0.3, y_bot), T(bx - bw / 2 - 0.3, y_bot)])
    # nothing outside the fish's outline
    shape = pygame.Surface(surf.get_size(), pygame.SRCALPHA)
    for poly in (body, dorsal, anal, tail_pts):
        pygame.draw.polygon(shape, (255, 255, 255, 255), [T(*p) for p in poly])
    alpha = pygame.surfarray.pixels_alpha(surf)
    alpha[:] = np.minimum(alpha, pygame.surfarray.pixels_alpha(shape))
    del alpha
    # a soft outline, the ventral filaments, the eye and the mouth
    pygame.draw.aalines(surf, (150, 120, 90) if gold else (120, 124, 116), True, [T(*p) for p in body])
    for dx in (0, 0.9):
        pygame.draw.line(surf, (*((252, 236, 210) if gold else (236, 228, 204)), 220), T(2.4 + dx, 4.6),
                         T(0.2 + dx, 15.5 + dx), max(1, int(0.42 * k)))
    pygame.draw.circle(surf, (196, 60, 34), T(4.9, -1.7), 1.25 * k)
    pygame.draw.circle(surf, (10, 10, 10), T(5.0, -1.7), 0.62 * k)
    pygame.draw.circle(surf, (255, 255, 255), T(5.25, -2.0), 0.2 * k)
    pygame.draw.line(surf, (90, 70, 50), T(7.2, 0.1), T(6.4, 0.5), max(1, int(0.3 * k)))
    return finish(surf, size, X0, X1, Y0, Y1)


def neon_sprite(size, tail, glow=False):
    """A neon tetra facing right; glow - only its blue stripe (shown when the lamp is off)."""
    X0, X1, Y0, Y1 = -5.2, 4, -1.8, 1.8
    surf, T, k = sprite_canvas(X0, X1, Y0, Y1, size)

    def h(x):
        return 1.35 * math.sqrt(max(0.0, 1 - ((x + 0.2) / 3.75) ** 2))
    xs = [x / 8 for x in range(-28, 29)]
    stripe = [T(x, -0.42 * h(x) - 0.22) for x in xs[4:-6]] + [T(x, 0.05 * h(x) + 0.08) for x in xs[4:-6][::-1]]
    if glow:
        pygame.draw.polygon(surf, (40, 200, 255, 255), stripe)
        return finish(surf, size, X0, X1, Y0, Y1)
    a = tail * 0.35
    tail_pts = [(-3.6, -0.5), (-5.0 + abs(a), -1.4 + a), (-4.5, a * 0.5), (-5.0 + abs(a), 1.4 + a), (-3.6, 0.5)]
    pygame.draw.polygon(surf, (210, 214, 220, 120), [T(*p) for p in tail_pts])
    body = [(x, -h(x)) for x in xs] + [(x, h(x)) for x in xs[::-1]]
    pygame.draw.polygon(surf, (196, 204, 212, 235), [T(*p) for p in body])
    pygame.draw.polygon(surf, (222, 34, 48, 245), [T(x, 0.15) for x in xs[2:30]] + [T(x, h(x) * 0.92) for x in xs[2:30][::-1]])
    pygame.draw.polygon(surf, (30, 190, 255, 255), stripe)
    pygame.draw.circle(surf, (200, 210, 220), T(2.55, -0.25), 0.62 * k)
    pygame.draw.circle(surf, (8, 8, 12), T(2.6, -0.25), 0.4 * k)
    return finish(surf, size, X0, X1, Y0, Y1)


GLO_RED, GLO_PINK = (255, 76, 64), (255, 96, 170)


def glofish_sprite(size, color, tail, glow=False):
    """A GloFish (black skirt) tetra facing right: a tall diamond body in a fluorescent colour, the high
    dorsal fin and the long anal fin; glow - the body alone, a little brighter (seen in the dark)."""
    X0, X1, Y0, Y1 = -6.0, 4.0, -4.6, 4.4
    surf, T, k = sprite_canvas(X0, X1, Y0, Y1, size)

    def h(x):                                            # the body's half height: tall at the front third
        u = (x + 0.6) / 3.6
        return 2.5 * max(0.0, 1 - abs(u) ** 1.7) ** 0.75
    xs = [x / 8 for x in range(-29, 30)]
    body = [(x, -h(x) * (1.05 if x > -1 else 0.9)) for x in xs] + [(x, h(x) * 0.95) for x in xs[::-1]]
    fin = (*mix(color, (255, 255, 255), 0.15), 170)
    if glow:
        pygame.draw.polygon(surf, (*mix(color, (255, 255, 255), 0.25), 255), [T(*p) for p in body])
        return finish(surf, size, X0, X1, Y0, Y1)
    a = tail * 0.35
    pygame.draw.polygon(surf, fin, [T(*p) for p in ((-3.6, -0.5), (-5.6 + abs(a), -2.2 + a), (-4.7, a * 0.4),
                                                       (-5.6 + abs(a), 2.2 + a), (-3.6, 0.5))])
    pygame.draw.polygon(surf, fin, [T(*p) for p in ((0.2, -2.3), (-0.6, -4.4), (-2.2, -4.0), (-1.8, -2.0))])
    pygame.draw.polygon(surf, (*mix(color, (90, 30, 50), 0.18), 150),
                        [T(*p) for p in ((0.6, 2.2), (-0.8, 4.0), (-3.4, 3.2), (-3.4, 1.0))])
    pygame.draw.polygon(surf, color, [T(*p) for p in body])
    pygame.draw.polygon(surf, (*mix(color, (255, 255, 255), 0.3), 110), [T(x, -h(x) * 0.15) for x in xs[14:-12]]
                        + [T(x, h(x) * 0.45) for x in xs[14:-12][::-1]])
    pygame.draw.line(surf, (*mix(color, (40, 10, 20), 0.4), 150), T(1.2, -2.0), T(0.9, 1.8), max(1, int(0.25 * k)))  # the bar
    pygame.draw.circle(surf, (230, 230, 230), T(2.2, -0.5), 0.75 * k)
    pygame.draw.circle(surf, (10, 10, 12), T(2.3, -0.5), 0.45 * k)
    return finish(surf, size, X0, X1, Y0, Y1)


def platy_sprite(size, tail):
    """A golden platy facing right: a round yellow body, an orange fan tail."""
    X0, X1, Y0, Y1 = -7.0, 4.2, -3.4, 3.0
    surf, T, k = sprite_canvas(X0, X1, Y0, Y1, size)

    def h(x):
        return 2.1 * math.sqrt(max(0.0, 1 - ((x + 0.3) / 4.0) ** 2))
    xs = [x / 8 for x in range(-34, 31)]
    a = tail * 0.3
    tail_pts = [(-3.8, -0.9), (-6.6 + abs(a), -2.6 + a), (-6.9, a), (-6.6 + abs(a), 2.6 + a), (-3.8, 0.9)]
    pygame.draw.polygon(surf, (250, 140, 40, 210), [T(*p) for p in tail_pts])
    pygame.draw.polygon(surf, (250, 170, 50, 200), [T(*p) for p in ((1.0, -1.9), (0.0, -3.3), (-2.4, -2.9), (-2.6, -1.6))])
    body = [(x, -h(x) * 1.05) for x in xs] + [(x, h(x)) for x in xs[::-1]]
    pygame.draw.polygon(surf, (252, 196, 48), [T(*p) for p in body])
    pygame.draw.polygon(surf, (255, 230, 130), [T(x, h(x) * 0.15) for x in xs[8:-8]] + [T(x, h(x) * 0.85) for x in xs[8:-8][::-1]])
    pygame.draw.polygon(surf, (240, 150, 40), [T(x, -h(x) * 1.05) for x in xs[4:-10]] + [T(x, -h(x) * 0.5) for x in xs[4:-10][::-1]])
    pygame.draw.circle(surf, (40, 30, 20), T(2.5, -0.5), 0.6 * k)
    pygame.draw.circle(surf, (255, 255, 255), T(2.65, -0.7), 0.18 * k)
    return finish(surf, size, X0, X1, Y0, Y1)


def tilted_frames(make, *args):
    """[facing 0=right 1=left][tilt][tail] sprites."""
    base = [make(*args, math.sin(2 * math.pi * i / TAIL_FRAMES)) for i in range(TAIL_FRAMES)]
    right = [[pygame.transform.rotozoom(f, -deg, 1) if deg else f for f in base] for deg in TILTS]
    left = [[pygame.transform.flip(f, True, False) for f in row] for row in right]
    return right, left


def plain_frames(make, *args):
    base = [make(*args, math.sin(2 * math.pi * i / TAIL_FRAMES)) for i in range(TAIL_FRAMES)]
    return [base], [[pygame.transform.flip(f, True, False) for f in base]]


def duck_sprite():
    surf, T, k = sprite_canvas(-3.2, 3.4, -3.6, 1.6, 1)
    pygame.draw.ellipse(surf, (250, 214, 40), (*T(-3, -1.4), 5.4 * k, 2.8 * k))
    pygame.draw.circle(surf, (250, 220, 50), T(1.4, -2.0), 1.4 * k)
    pygame.draw.polygon(surf, (240, 120, 30), [T(2.6, -2.1), T(3.4, -1.7), T(2.6, -1.4)])
    pygame.draw.circle(surf, (20, 20, 20), T(1.8, -2.4), 0.28 * k)
    pygame.draw.ellipse(surf, (230, 90, 150), (*T(0.2, -3.6), 1.6 * k, 0.9 * k))   # the pink bow
    return finish(surf, 1, -3.2, 3.4, -3.6, 1.6)


DUCK = duck_sprite()


# ---------------------------------------------------------------- fish

class Fish:
    """Glides towards a target point; tilts with its climb, turns round smoothly (narrows, flips, widens)."""

    def __init__(self, sprites, x, y, speed, zone, margin=4):
        self.right, self.left = sprites
        self.margin = margin             # half its height: how close it may come to the surface / the gravel
        self.others = []                 # fish it keeps away from when choosing where to swim
        self.x, self.y = x, y
        self.vx, self.vy = 0.0, 0.0
        self.speed = speed
        self.zone = zone                 # (x0, y0, x1, y1) where it likes to swim
        self.face = 1.0                  # -1 .. 1: which way it faces, through 0 while turning
        self.tilt = 0.0
        self.tail = rng.uniform(0, TAIL_FRAMES)
        self.pick_target()

    def pick_target(self):
        x0, y0, x1, y1 = self.zone
        for _ in range(8):                                   # somewhere the others are not heading to
            self.tx, self.ty = rng.uniform(x0, x1), rng.uniform(y0, y1)
            if all(((o.tx - self.tx) / 26) ** 2 + ((o.ty - self.ty) / 30) ** 2 > 1 for o in self.others):
                break
        self.rest = rng.uniform(0.3, 2.5)

    def steer(self, tx, ty, dt, speed, accel=1.6):
        dx, dy = tx - self.x, ty - self.y
        d = math.hypot(dx, dy) or 1
        want = min(speed, d * 1.2)
        self.vx += (dx / d * want - self.vx) * min(1, accel * dt)
        self.vy += (dy / d * want * 0.55 - self.vy) * min(1, accel * dt)
        return d

    def update(self, dt, food):
        target = None
        if food:
            near = min(food, key=lambda f: (f.x - self.x) ** 2 + (f.y - self.y) ** 2)
            if (near.x - self.x) ** 2 + (near.y - self.y) ** 2 < 60 ** 2:
                target = near
        if target:
            if self.steer(target.x, target.y, dt, self.speed * 1.8, 2.6) < 2.5:
                food.remove(target)
        else:
            if self.rest > 0:
                self.rest -= dt
                self.vx *= 1 - min(1, 0.9 * dt)
                self.vy *= 1 - min(1, 0.9 * dt)
            elif self.steer(self.tx, self.ty, dt, self.speed) < 3:
                self.pick_target()
        self.move(dt)

    def move(self, dt):
        self.x += self.vx * dt
        self.y += self.vy * dt
        self.x = max(6, min(122, self.x))
        self.y = max(SURFACE_Y + self.margin, min(ground_line(self.x) - self.margin, self.y))
        want = 1.0 if self.vx > 0.5 else -1.0 if self.vx < -0.5 else (1.0 if self.face >= 0 else -1.0)
        self.face += max(-dt * 2.2, min(dt * 2.2, want - self.face))
        climb = max(-1.0, min(1.0, self.vy / max(3.0, abs(self.vx) + 1.0)))
        self.tilt += (climb - self.tilt) * min(1, dt * 3)
        self.tail += dt * (2.2 + abs(self.vx) * 0.3 + abs(self.vy) * 0.2)

    def image(self):
        side = self.right if self.face >= 0 else self.left
        row = side[min(len(side) - 1, max(0, int(round((self.tilt + 1) / 2 * (len(side) - 1)))))]
        img = row[int(self.tail) % TAIL_FRAMES]
        wscale = abs(self.face)
        if wscale < 0.97:                                   # turning: narrower
            img = pygame.transform.smoothscale(img, (max(1, int(img.get_width() * max(0.2, wscale))), img.get_height()))
        return img

    def draw(self, surf):
        img = self.image()
        surf.blit(img, (self.x * S - img.get_width() / 2, self.y * S - img.get_height() / 2))
        return img


class School:
    """A shoal: a leader wanders, the others keep their place around it with a little jitter.

    members - [(sprite frames, glow sprite (right, left) or None)]; the glow is what is still seen
    when the lamp is off (the neons' blue stripe, the GloFish's whole fluorescent body)."""

    def __init__(self, members, start, zone, speed, spread):
        self.leader = Fish(([[None]], [[None]]), *start, speed * 0.8, zone)
        self.glow = [g for _, g in members]
        self.fish = []
        for frames_, _ in members:
            f = Fish(frames_, start[0] + rng.uniform(-10, 10), start[1] + rng.uniform(-6, 6), speed, zone)
            f.off = (rng.uniform(-spread[0], spread[0]), rng.uniform(-spread[1], spread[1]))
            f.jit = rng.uniform(0, 6.3)
            self.fish.append(f)

    def update(self, dt, t, food):
        L = self.leader
        if L.rest > 0:
            L.rest -= dt
        elif L.steer(L.tx, L.ty, dt, L.speed) < 4:
            L.pick_target()
            L.rest = rng.uniform(0, 0.8)
        L.x += L.vx * dt
        L.y += L.vy * dt
        for f in self.fish:
            if food and any((p.x - f.x) ** 2 + (p.y - f.y) ** 2 < 40 ** 2 for p in food):
                f.update(dt, food)
                continue
            ox = f.off[0] + 2.5 * math.sin(t * 0.7 + f.jit)
            oy = f.off[1] + 1.8 * math.sin(t * 1.1 + f.jit * 1.3)
            f.steer(L.x + ox, L.y + oy, dt, f.speed, 2.4)
            for g in self.fish:                              # keep apart a little
                if g is not f:
                    dx, dy = f.x - g.x, f.y - g.y
                    d2 = dx * dx + dy * dy
                    if 0 < d2 < 30:
                        f.vx += dx / d2 * 60 * dt
                        f.vy += dy / d2 * 60 * dt
            f.move(dt)

    def draw(self, surf):
        for f in self.fish:
            f.draw(surf)

    def draw_glow(self, surf, strength):
        for f, gs in zip(self.fish, self.glow):
            if gs is None:
                continue
            img = f.image()
            g = gs[0] if f.face >= 0 else gs[1]
            if img.get_width() != g.get_width():
                g = pygame.transform.smoothscale(g, (img.get_width(), g.get_height()))
            g = g.copy()
            g.set_alpha(int(255 * strength))
            surf.blit(g, (f.x * S - g.get_width() / 2, f.y * S - g.get_height() / 2))


def neon_school(n):
    members = []
    for _ in range(n):
        s = rng.uniform(0.85, 1.1)
        g = neon_sprite(s, 0, True)
        members.append((plain_frames(neon_sprite, s), (g, pygame.transform.flip(g, True, False))))
    return School(members, (66, 82), (14, 56, 112, 98), 19, (16, 8))


def glofish_school(colors):
    members = []
    for c in colors:
        s = rng.uniform(0.9, 1.05)
        fr = plain_frames(glofish_sprite, s, c)
        g = glofish_sprite(s, c, 0, True)
        members.append((fr, (g, pygame.transform.flip(g, True, False))))
    return School(members, (40, 60), (14, 34, 100, 86), 14, (10, 7))


# ---------------------------------------------------------------- air, food, the surface, the ducks

STONE = (88, 106)           # the air stone (logical): bubbles come from here


class Bubble:
    def __init__(self, x, y):
        self.x0, self.y = x, y
        self.r = rng.uniform(0.45, 1.0)
        self.v = rng.uniform(16, 24)
        self.ph = rng.uniform(0, 6.3)
        self.x = x

    def update(self, dt):
        self.y -= self.v * dt
        self.r += dt * 0.12
        self.ph += dt * 7
        self.x = self.x0 + math.sin(self.ph) * 0.7 + (106 - self.y) * 0.03
        return self.y > SURFACE_Y + 1


class Flake:
    def __init__(self):
        self.x = rng.uniform(30, 100)
        self.y = SURFACE_Y + rng.uniform(-1, 2)
        self.c = rng.choice(((214, 120, 50), (196, 70, 44), (226, 182, 82)))
        self.ph = rng.uniform(0, 6.3)
        self.age = 0.0

    def update(self, dt):
        self.age += dt
        floor = ground_line(self.x) - 0.5
        if self.y < floor:
            self.y += (5 if self.age > 1.2 else 1.5) * dt
            self.x += math.sin(self.age * 2 + self.ph) * 3 * dt
        return self.age < 30


def draw_air_gear(surf):
    w = max(1, int(0.7 * S))
    pygame.draw.line(surf, (200, 230, 236), P(118, 0), P(118, 104), w)
    pygame.draw.line(surf, (200, 230, 236), P(118, 104), P(STONE[0] + 3, STONE[1]), w)
    pygame.draw.ellipse(surf, (78, 86, 96), (*P(STONE[0] - 4, STONE[1] - 1.8), 8 * S, 3.6 * S))
    pygame.draw.ellipse(surf, (122, 130, 140), (*P(STONE[0] - 3, STONE[1] - 1.5), 5 * S, 1.6 * S))


def surface_y(x, t):
    return SURFACE_Y - 1.0 + 0.6 * math.sin(x * 0.16 + t * 1.6) + 0.35 * math.sin(x * 0.33 - t * 1.1)


def draw_surface(surf, t, light):
    pts = [P(0, 0)] + [P(k * 4, surface_y(k * 4, t)) for k in range(33)] + [P(128, 0)]
    pygame.draw.polygon(surf, mix((26, 56, 70), (150, 214, 236), light), pts)
    pygame.draw.aalines(surf, mix((50, 90, 110), (236, 252, 255), light), False, pts[1:-1])


def draw_ducks(surf, t):
    for i, x in enumerate((10, 17, 24, 31, 38)):
        y = surface_y(x, t) - 0.9 + 0.25 * math.sin(t * 2 + i)
        img = DUCK
        if i % 2:
            img = pygame.transform.flip(DUCK, True, False)
        surf.blit(img, (x * S - img.get_width() / 2, y * S - img.get_height() * 0.65))


# ---------------------------------------------------------------- the tank

class Tank:
    def __init__(self):
        kinds = (("silver", 1.0, (40, 40)), ("gold", 0.95, (84, 30)), ("silver", 0.88, (62, 58)))
        self.angels = [Fish(tilted_frames(angelfish_sprite, size, kind), x, y, 8.5, (16, 28, 112, 80), margin=15)
                       for kind, size, (x, y) in kinds]
        for f in self.angels:
            f.others = [g for g in self.angels if g is not f]
            f.pick_target()
        self.school = neon_school(11)
        self.glofish = glofish_school((GLO_RED, GLO_RED, GLO_RED, GLO_PINK, GLO_RED))
        self.platy = Fish(tilted_frames(platy_sprite, 1.0), 30, 88, 9, (12, 64, 70, 100), margin=4)
        self.bubbles, self.food = [], []
        self.light, self.light_on = 0.0, True
        self.air_on, self.air_level = True, 0.0
        self.emit = 0.0
        self.flicker_until = 0.0
        self.t0 = time.monotonic()
        self.air_after = 2.2           # the pump starts a moment after the lamp

    def lamp(self, on, now):
        self.light_on = on
        if on:
            self.flicker_until = now + 0.9
        lcd.play("click")

    def update(self, now, dt):
        t = now - self.t0
        # the lamp: off at first, then a fluorescent flicker, then steady
        if t < 0.7:
            target = 0.0
        elif self.light_on and now < max(self.flicker_until, self.t0 + 1.6):
            target = 1.0 if rng.random() < 0.45 else 0.15
        else:
            target = 1.0 if self.light_on else 0.0
        if t > 0.7 and t - dt <= 0.7:
            lcd.play("click")
        self.light += (target - self.light) * min(1, dt * (14 if target > self.light else 3))
        # the pump
        if t > self.air_after and t - dt <= self.air_after:
            lcd.play("move")
        want = 1.0 if (self.air_on and t > self.air_after) else 0.0
        self.air_level += (want - self.air_level) * min(1, dt * 1.5)
        self.emit += dt * 14 * self.air_level
        while self.emit >= 1:
            self.emit -= 1
            self.bubbles.append(Bubble(STONE[0] + rng.uniform(-2.5, 2.5), STONE[1] - 1.5))
        self.bubbles = [b for b in self.bubbles if b.update(dt)]
        self.food = [f for f in self.food if f.update(dt)]
        for f in self.angels:
            f.update(dt, self.food)
        for i, f in enumerate(self.angels):                  # angelfish keep their distance
            for g in self.angels[i + 1:]:
                ux, uy = (f.x - g.x) / 24, (f.y - g.y) / 32      # tall fish: the vertical gap counts less
                d = math.hypot(ux, uy) or 0.01
                if d < 1:
                    push = (1 - d) * 34 * dt
                    f.vx += ux / d * push
                    f.vy += uy / d * push * 1.3
                    g.vx -= ux / d * push
                    g.vy -= uy / d * push * 1.3
                    if d < 0.6 and rng.random() < dt * 2:    # too close for long: one swims elsewhere
                        g.pick_target()
        self.school.update(dt, t, self.food)
        self.glofish.update(dt, t, self.food)
        self.platy.update(dt, self.food)

    def draw(self, now):
        t = now - self.t0
        surf = canvas
        surf.blit(BACKGROUND, (0, 0))
        draw_air_gear(surf)
        order = sorted(self.angels, key=lambda f: f.y)
        order[0].draw(surf)                                  # the highest one swims behind the neons
        self.glofish.draw(surf)
        self.school.draw(surf)
        self.platy.draw(surf)
        for f in order[1:]:
            f.draw(surf)
        for g in GRASS:
            g.draw(surf, t)
        for fl in self.food:
            pygame.draw.rect(surf, fl.c, (*P(fl.x - 0.6, fl.y - 0.4), max(1, 1.3 * S), max(1, 0.9 * S)))
        for b in self.bubbles:
            r = b.r * S
            pygame.draw.circle(surf, (206, 236, 250), P(b.x, b.y), r, max(1, int(r * 0.3)))
            pygame.draw.circle(surf, (250, 255, 255), (b.x * S - r * 0.35, b.y * S - r * 0.35), max(1, r * 0.25))
        surf.blit(FRONT, FRONT_RECT.topleft)
        draw_surface(surf, t, self.light)
        draw_ducks(surf, t)
        if self.light < 0.999:
            DARK.fill((2, 6, 16, int(225 * (1 - self.light))))
            surf.blit(DARK, (0, 0))
        if self.light < 0.5:                                 # only the neons' stripes are seen in the dark
            self.school.draw_glow(surf, 1 - self.light * 2)
            self.glofish.draw_glow(surf, (1 - self.light * 2) * 0.75)


def draw_hud(tank, now):
    """The name and the keys for the first seconds."""
    t = now - tank.t0
    a = 1.0 if t < 5 else max(0.0, 1 - (t - 5) / 1.5)
    if a <= 0:
        return
    if 1.0 < t < 6.5:
        title = f_title.render("АКВАРІУМ", True, (250, 252, 250))
        (title.img if hasattr(title, "img") else title).set_alpha(int(255 * min(1.0, (t - 1.0) / 0.8) * a))
        screen.blit(title, ((128 - title.get_width()) / 2, 24))
    if lcd.DEVICE == "picocalc":
        hints = ("1 - світло   2 - повітря", "Enter - годувати   Esc - меню")
    else:
        hints = ("K1 світло  K2 повітря", "OK годувати  K3 меню")
    imgs = [f_hint.render(h, True, (226, 236, 232)) for h in hints]
    lh = imgs[0].get_height()
    top = 128 - lh * len(imgs) - 2
    STRIP.set_alpha(int(150 * a))
    pygame.Surface.blit(screen, STRIP, (0, int(top * S)))
    for k, img in enumerate(imgs):
        (img.img if hasattr(img, "img") else img).set_alpha(int(240 * a))
        screen.blit(img, ((128 - img.get_width()) / 2, top + 1 + k * lh))


def handle_keys(tank, now):
    for ev in pygame.event.get():
        if ev.type == pygame.QUIT:
            return False
        if ev.type != pygame.KEYDOWN:
            continue
        if ev.key in (pygame.K_ESCAPE, pygame.K_3, pygame.K_BACKSPACE, pygame.K_q):
            return False
        if ev.key in (pygame.K_1, pygame.K_l):
            tank.lamp(not tank.light_on, now)
        elif ev.key in (pygame.K_2, pygame.K_a):
            tank.air_on = not tank.air_on
            lcd.play("move")
        elif ev.key in (pygame.K_RETURN, pygame.K_SPACE, pygame.K_f, pygame.K_RIGHT):
            tank.food += [Flake() for _ in range(6)]
            lcd.play("chip")
    return True


def main(seconds=None):
    """Until Esc / KEY3; seconds - stop by itself (for the GIF recorder)."""
    pygame.event.clear()
    tank = Tank()
    last = time.monotonic()
    while True:
        now = time.monotonic()
        dt = min(0.1, now - last)
        last = now
        if seconds is not None and now - tank.t0 > seconds:
            return
        tank.update(now, dt)
        tank.draw(now)
        pygame.Surface.blit(screen, canvas, (0, 0))
        draw_hud(tank, now)
        lcd.flip()
        if not handle_keys(tank, now):
            return
        clock.tick(FPS)


if __name__ == "__main__":
    try:
        main()
    finally:
        screen.fill((0, 0, 0))
        lcd.flip()
        lcd.quit()
