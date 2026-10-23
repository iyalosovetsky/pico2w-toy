"""Aquarium - our planted tank: two silver and one golden angelfish, neon tetras, GloFish tetras in four colours,
a golden platy, stem plants,
a red bush, a hair-grass tuft, round stones and pebbles, the castle ruins, an air stone, rubber ducks.

It starts like a real tank being switched on: dark water, the lamp clicks and flickers on, then the air
pump starts and the bubbles rise. The still scene (backdrop, plants, stones, castle) is drawn once at double
resolution and smoothed down, then cached (~/.cache/lcdtoy/), so later starts are instant; the fish are
pre-rendered antialiased sprites with a few tilts; the hair grass and the surface move every frame.

Keys (PicoCalc / HAT):
    the lamp runs on a timer like ours: 07:00 it comes on slowly, full light by day, from 19:00 it dims and
    turns green, from 21:30 a dim green evening, at 23:30 off for the night (AQUARIUM_CLOCK=HH:MM and
    AQUARIUM_CLOCK_SPEED=600 try it out)
    1 / KEY1      - the lamp on/off by hand until the timer's next change (in the dark the neons, the GloFish and the fluorescent stones glow;
                    the stones charge in the light and fade slowly in the dark)
    2 / KEY2      - the air pump on/off
    on a monitor (LCD_DISPLAY=kms LCD_SIZE=1024x640 - the tank as wide as the screen, the time and the day cut
    into the castle) a touch at the top drops food there, in the middle shows the camera full screen
    (AQUARIUM_CAMERA=rtsp://...; another touch or a key - back), at the bottom the fish come up to it
    any key        - someone is at the tank: the angelfish come up to the front glass and wait there (~25 s)
    arrows / joystick - a fingertip on the glass: the fish come up to look at it
    T, 4          - knock on the glass at the finger: the fish nearby dart away
    Enter, Space / PRESS - feed the fish (at the finger if it is shown; the fish go after the flakes)
    Esc / KEY3    - back to the menu

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
W, H = lcd.SCREEN_W, 128          # the logical tank: 128 x 128 on the LCDs, wider on a monitor
XS = W / 128                    # how much wider than the square scene it was drawn for
DC = max(0.0, W - 138)          # the castle (with the heater and the air stone) by the right wall, all of it in view
DB = max(0.0, DC - 12)          # the round-leaved bush in front of it, a little apart (the day cut in the castle shows)
SURFACE_Y = 9                   # the water line
FONT_DIR = "/usr/share/fonts/truetype/dejavu/"
CACHE = os.path.expanduser("~/.cache/lcdtoy")
SCENE_VERSION = 21               # bump when the still scene changes (the cache is keyed on it)
rng = random.Random()

canvas = pygame.Surface((NW, NH))   # everything is drawn here in native pixels, then shown at once


def P(x, y):
    """A logical point -> native pixels."""
    return (x * S, y * S)


def X(x):
    """Where something placed at x in the square scene goes in a wider tank (spread out evenly)."""
    return x * XS


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


def smooth_noise(r, w, h, cells):
    """Smooth value noise 0..1, h rows of w, from a cells x cells random grid."""
    vals = (r.random((cells, cells)) * 255).astype(np.uint8)
    small = pygame.surfarray.make_surface(np.repeat(vals[..., None], 3, axis=2))
    big = pygame.transform.smoothscale(pygame.transform.smoothscale(small, (cells * 4, cells * 4)), (w, h))
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
    sw, sh = int(W * k), int(H * k)
    r = random.Random(11)
    nr = np.random.default_rng(5)

    # the blue backdrop with a soft stone-and-water pattern, lighter up under the lamp
    yy = np.linspace(0, 1, sh, dtype=np.float32)[:, None]
    base_top, base_bot = np.array([104, 186, 232], np.float32), np.array([30, 104, 176], np.float32)
    img = base_top * (1 - yy[..., None]) + base_bot * yy[..., None]
    tex = smooth_noise(nr, sw, sh, 10) * 0.6 + smooth_noise(nr, sw, sh, 28) * 0.4
    waves = np.sin(np.arange(sh, dtype=np.float32)[:, None] / k * 0.55 + tex * 9) * 0.5 + 0.5
    img = img * (0.78 + 0.32 * tex[..., None]) + 18 * (waves[..., None] - 0.5)
    xx = np.linspace(-1, 1, sw, dtype=np.float32)[None, :, None]
    img *= 1 - 0.18 * xx ** 2

    # the gravel: dark, speckled, lighter towards the front glass
    gl = np.array([ground_line(x / k) * k for x in range(sw)], np.float32)
    row = np.arange(sh, dtype=np.float32)[:, None]
    below = row >= gl[None, :]
    depth = np.clip((row - gl[None, :]) / ((H - 100) * k), 0, 1)[..., None]
    gravel = np.array([58, 54, 46], np.float32) * (1 - depth) + np.array([104, 96, 80], np.float32) * depth
    grain = nr.random((sh, sw))
    speck = np.where(grain[..., None] > 0.82, np.array([150, 140, 120], np.float32),
                     np.where(grain[..., None] < 0.15, np.array([30, 28, 24], np.float32), gravel))
    gravel = gravel * 0.45 + speck * 0.55
    img[below] = gravel[below]
    surf = pygame.Surface((sw, sh))
    pygame.surfarray.blit_array(surf, np.clip(img, 0, 255).astype(np.uint8).swapaxes(0, 1))
    pen = Pen(surf, k)

    # the lamp's reflection just under the surface
    band = pygame.Surface((sw, int(6 * k)), pygame.SRCALPHA)
    for i in range(int(6 * k)):
        pygame.draw.line(band, (230, 250, 255, int(110 * (1 - i / (6 * k)) ** 2)), (0, i), (sw, i))
    surf.blit(band, (0, int(SURFACE_Y * k)))

    # far stem plants, bluish and pale (depth)
    far = pygame.Surface((sw, sh), pygame.SRCALPHA)
    fpen = Pen(far, k)
    for _ in range(int(16 * XS)):
        stem_plant(fpen, X(r.uniform(36, 96)), ground_line(X(60)) - 2, r.uniform(26, 54), r.uniform(-5, 5),
                   (60, 150, 130), (120, 200, 170), r, alpha=120)
    surf.blit(far, (0, 0))

    # the heater, small, at the back: its top with the thermostat lamp shows above the tower
    for c, x0, x1, y0, y1 in (((176, 206, 218), 108.6, 110.8, 30, 66), ((96, 102, 108), 109.3, 110.1, 36, 64),
                              ((44, 48, 54), 108.2, 111.2, 28, 31)):
        pen.poly(c, [(x0 + DC, y0), (x1 + DC, y0), (x1 + DC, y1), (x0 + DC, y1)])
    surf.blit(castle_layer(sw, sh, k, DC), (0, 0))


    # the plants that sway: each group on its own layer (moved in bands every frame, see Sway)
    def layer():
        lay = pygame.Surface((sw, sh), pygame.SRCALPHA)
        return lay, Pen(lay, k)
    layers = {}

    # the dense stem plants on the left, up to the surface
    lay, lp = layer()
    n = int(18 * XS)
    for i in range(n):
        x = r.uniform(1, 40) if i < n * 14 // 18 else r.uniform(40, 52)
        stem_plant(lp, X(x), ground_line(X(x)) + 1, r.uniform(48, 92) if x < 36 else r.uniform(26, 40), r.uniform(-7, 7),
                   (34, 112, 46), (132, 208, 92), r)
    layers["stem"] = lay

    # the lemon plant (Nomaphila) in the middle: thick stems with pairs of ovate light-green leaves, big low down,
    # smaller and lighter up top, veined, a little wavy; the stem at the back darker
    lay, lp = layer()
    for x0, h, z in ((52.0, 44.0, 0.0), (43.5, 38.0, 0.55), (48.5, 32.0, 1.0)):
        x0 = X(x0)
        base_y = ground_line(x0) + 1
        far = 1 - z
        stem_c = mix((112, 132, 66), (58, 84, 46), far * 0.8)            # thick, brownish green
        lean = r.uniform(-2, 2)
        top = (x0 + lean, base_y - h)
        lp.line(stem_c, (x0, base_y), top, 0.9)
        pairs = int(h / 7.5) + 1
        for i in range(pairs):
            t = (i + 0.5) / pairs
            sx, sy = x0 + lean * t, base_y - h * t
            ln = (15.0 - 6.5 * t) * r.uniform(0.9, 1.1)
            wd = ln * 0.72
            if i % 2 == 0:                       # a pair spreading out, the low ones hanging down
                for side in (-1, 1):
                    lemon_leaf(lp, sx, sy, ln, wd, side * r.uniform(1.1, 1.45), z, t, r, droop=(1.0 - t) * 1.5)
            else:                                # the next pair turned 90 degrees: one leaf towards you, foreshortened
                lemon_leaf(lp, sx, sy, ln * 0.55, wd * 1.15, math.pi + r.uniform(-0.4, 0.4), min(1.0, z + 0.2), t, r)
        for side in (-1, 1):                     # the young pair at the top, standing up
            lemon_leaf(lp, *top, 6.0, 3.0, side * 0.5, z, 1.0, r)
    layers["broad"] = lay

    # the round-leaved bush by the castle (pennywort), in depth: the far leaves small, dark and hazed with the
    # water's blue-green, high up at the back; the near ones three to four times bigger, light and juicy, low in front
    lay, lp = layer()
    leaves = []
    for _ in range(70):
        z = r.random() ** 1.4                            # 0 far .. 1 near (more far leaves than near ones)
        x = r.uniform(80, 104) + (r.uniform(-3, 3) * z) + DB
        y = 70 + 14 * z + r.uniform(0, 16 - 4 * z)       # far ones high at the back, near ones low in front
        leaves.append((z, x, y))
    leaves.sort()
    haze = (44, 96, 98)                                  # the water between you and the far leaves
    for z, x, y in leaves:
        rad = (0.9 + 3.4 * z ** 1.3) * r.uniform(0.9, 1.1)
        tilt = 0.62 + 0.16 * z
        far = 1 - z
        base = mix(mix((92, 186, 68), (34, 92, 46), far), haze, 0.45 * far)
        light = mix(mix((168, 232, 116), (52, 118, 60), far), haze, 0.4 * far)
        rim = mix(mix((44, 116, 42), (20, 54, 34), far), haze, 0.45 * far)
        stalk = mix(mix((76, 150, 60), (26, 66, 40), far), haze, 0.45 * far)
        lp.line(stalk, (x + r.uniform(-1, 1), ground_line(x) + 1), (x, y + rad * tilt * 0.3), 0.25 + 0.35 * z)
        lp.ellipse(rim, x, y, rad, rad * tilt)
        lp.ellipse(base, x - rad * 0.05, y - rad * tilt * 0.05, rad * 0.9, rad * tilt * 0.88)
        lp.ellipse(light, x - rad * 0.22, y - rad * tilt * 0.24, rad * 0.55, rad * tilt * 0.5)
        if z > 0.5:                                      # veins only where you can see them
            cx, cy = x + rad * 0.05, y + rad * tilt * 0.12
            vein = mix(base, (190, 236, 150), 0.25)
            for j in range(7):
                a = j / 7 * 2 * math.pi + 0.3
                lp.line(vein, (cx, cy), (cx + math.cos(a) * rad * 0.78, cy + math.sin(a) * rad * tilt * 0.78), 0.12)
    layers["round"] = lay

    # the red-purple bush at the bottom left
    lay, lp = layer()
    for _ in range(26):
        x0 = X(r.uniform(16, 34))
        base = ground_line(x0)
        h = r.uniform(10, 22)
        lean = r.uniform(-5, 5)
        lp.line((90, 40, 60), (x0, base), (x0 + lean, base - h), 0.4)
        for j in range(6):
            t = (j + 1) / 7
            cx, cy = x0 + lean * t, base - h * t
            for side in (-1, 1):
                pts = leaf_pts(cx, cy, r.uniform(2.6, 3.8), r.uniform(1.4, 2.0), side * r.uniform(0.7, 1.4))
                lp.poly(r.choice(((150, 40, 92), (124, 32, 84), (178, 66, 112), (100, 58, 72))), pts)
    layers["red"] = lay

    # the stones over the plants' feet: a dark mossy one with pits and a light rounded one
    d1, d2 = X(34) - 34, X(60) - 60
    layers["stones"] = shaded_layer(sw, sh, k, [
        (34 + d1, 100, 11, 8, (34, 48, 32), (120, 142, 92),
         [(29 + d1, 98, 1.6), (36 + d1, 96, 1.2), (40 + d1, 101, 1.5), (31 + d1, 103, 1.0)]),
        (60 + d2, 99, 8.5, 7.5, (130, 120, 86), (236, 226, 190), []),
    ], seed=2)

    # the front pebbles: over the fish swimming low
    pebbles = []
    for _ in range(int(60 * XS)):
        x = r.uniform(14, X(96))
        y = r.uniform(ground_line(x) + 3, 124)
        rad = r.uniform(1.8, 3.6) * (0.75 + 0.4 * (y - 104) / 20)
        lo, hi = r.choice((((70, 86, 64), (178, 196, 160)), ((112, 104, 84), (232, 222, 192)),
                           ((90, 92, 86), (196, 198, 186))))
        pebbles.append((x, y, rad, rad * 0.75, lo, hi, []))
    front = shaded_layer(sw, sh, k, pebbles, seed=3)
    # the fluorescent ones: a bluish and the usual phosphor green, about two thirds of the pebbles
    PHOSPHOR, BLUE = (150, 255, 100), (70, 190, 255)
    glowing = [(x, y, rx, ry, r.choice((PHOSPHOR, PHOSPHOR, BLUE))) for x, y, rx, ry, *_ in pebbles if r.random() < 0.65]
    glowing.append((X(60), 99, 8.5, 7.5, BLUE))                                # the light round stone
    layers["glow"] = glow_layer(sw, sh, k, glowing)
    shipwreck(Pen(front, k), r)
    layers["front"] = front

    native = (NW, NH)
    out = {"bg": pygame.transform.smoothscale(surf, native)}
    for name, lay in layers.items():
        out[name] = pygame.transform.smoothscale(lay, native)
    return out


def shipwreck(pen, r):
    """The little wreck in the front left corner, like ours: a weathered cream hull, its bow raised to the
    upper left and the stern sunk in the gravel, a deckhouse with dark windows, a rail along the bow deck,
    a broken orange mast, a hole in the side, patches of algae."""
    ax, ay, ang = 4.0, 103.0, math.radians(-24)          # where the bow's deck line starts, and the tilt
    ca, sa = math.cos(ang), math.sin(ang)

    def q(x, y):                                         # ship coords (x: bow 0 -> stern 20, y: down) -> tank
        return (ax + x * ca - y * sa, ay + x * sa + y * ca)

    def poly(c, pts):
        pen.poly(c, [q(*p) for p in pts])

    def line(c, a, b, w):
        pen.line(c, q(*a), q(*b), w)
    cream, light, shade, plank = (206, 198, 168), (232, 226, 200), (150, 142, 116), (172, 164, 136)
    hull = [(0, -0.6), (20, 0), (20.4, 5.6), (16.5, 8.6), (5, 8.2), (1.2, 3.2)]
    poly(shade, hull)
    poly(cream, [(0, -0.6), (20, 0), (20.2, 3.4), (1.0, 2.2)])                    # the lit upper strakes
    for y in (1.8, 3.6, 5.4, 7.0):                                                # the planks
        line(plank, (1.2 + y * 0.25, y), (20.2, y + 0.1), 0.25)
    for x in (5, 9.5, 14, 18):
        line(plank, (x, 0.2), (x - 0.3, 8.2), 0.2)
    pen.ellipse((34, 30, 26), *q(14.2, 5.0), 1.7, 2.1)                            # the hole in the side
    poly((30, 26, 22), [(8.5, 6.2), (10.2, 6.0), (10.0, 8.0), (8.4, 8.1)])
    # the deckhouse at the stern with its dark windows
    poly(shade, [(9.5, 0.1), (19.2, 0.4), (19.6, -6.2), (10.0, -6.6)])
    poly(light, [(9.5, 0.1), (17.8, 0.35), (18.1, -6.25), (10.0, -6.6)])
    for wx in (11.0, 13.4, 15.8):
        poly((40, 34, 28), [(wx, -1.4), (wx + 1.5, -1.35), (wx + 1.55, -4.6), (wx + 0.05, -4.7)])
    line(light, (9.6, -7.2), (19.8, -6.8), 0.45)                                  # the roof rail
    for x in (10.2, 12.6, 15.0, 17.4, 19.6):
        line(light, (x, -6.7), (x, -7.2), 0.3)
    # the rail along the bow deck: a little white fence
    line(light, (0.6, -2.6), (9.4, -2.3), 0.4)
    for x in (0.9, 2.6, 4.3, 6.0, 7.7, 9.2):
        line(light, (x, -0.4), (x, -2.6), 0.4)
    # the broken mast
    poly((190, 112, 56), [(6.2, -0.4), (7.4, -0.4), (7.6, -6.0), (7.0, -7.4), (6.6, -6.2), (6.0, -6.6)])
    line((226, 150, 86), (6.5, -0.5), (6.8, -6.2), 0.25)
    # algae patches, thicker low on the hull
    for _ in range(26):
        x, y = r.uniform(1.5, 20), r.uniform(-6, 8)
        if y > 2 or r.random() < 0.35:
            pen.circle(r.choice(((74, 128, 58), (96, 150, 70), (60, 104, 48))), q(x, y), r.uniform(0.35, 0.9))


def shaded_layer(sw, sh, k, stones, seed):
    """Shaded round stones on a transparent layer (supersampled: smooth edges once scaled down)."""
    lay = pygame.Surface((sw, sh), pygame.SRCALPHA)
    arr = np.zeros((sh, sw, 3), np.float32)
    shade_ellipses(arr, k, stones, seed=seed)
    mask = np.zeros((sh, sw), bool)
    yy, xx = np.ogrid[:sh, :sw]
    for cx, cy, rx, ry, *_ in stones:
        mask |= (((xx / k - cx) / rx) ** 2 + ((yy / k - cy) / ry) ** 2) < 1
    pygame.surfarray.blit_array(lay, np.clip(arr, 0, 255).astype(np.uint8).swapaxes(0, 1))
    a = pygame.surfarray.pixels_alpha(lay)
    a[:] = (mask.T * 255).astype(np.uint8)
    del a
    return lay


def lemon_leaf(pen, x, y, length, width, angle, z, t, r, droop=0.0):
    """A Nomaphila leaf as in our tank: long ovate with a pointed tip, glossy and a little convex (a light band
    along the midrib), light yellow-green veins, a slightly wavy edge; droop - how much the tip curves down.
    z - how near it is, t - how high up the stem (young leaves are lighter)."""
    far = 1 - z
    body = mix(mix((100, 166, 56), (54, 106, 44), far * 0.8), (146, 204, 84), t * 0.3)
    q = r.uniform(-1, 1)                                   # each leaf its own tone: yellow-green .. dark green
    body = mix(body, (168, 196, 70), q * 0.4) if q > 0 else mix(body, (40, 84, 38), -q * 0.35)
    lit = mix(body, (190, 226, 120), 0.22)                 # the half facing the lamp
    edge = mix(body, (34, 70, 30), 0.4)
    shine = mix(body, (200, 236, 140), 0.35)
    vein = mix(body, (196, 226, 128), 0.45)
    sa, ca = math.sin(angle), -math.cos(angle)
    left, right, mid = [], [], []
    ph = r.uniform(0, 6.3)
    for k in range(15):
        u = k / 14
        hw = width / 2 * math.sin(math.pi * min(1.0, u * 1.02)) ** 0.7 * (1.15 - 0.35 * u)   # round, widest low, a point
        hw *= 1 + 0.05 * math.sin(u * 15 + ph)
        ax = x + sa * length * u
        ay = y + ca * length * u + droop * length * u * u * 0.45          # the tip hanging down
        mid.append((ax, ay))
        left.append((ax - ca * hw, ay + sa * hw))
        right.append((ax + ca * hw, ay - sa * hw))
    pen.poly(edge, left + right[::-1])
    inner = [(ax + (lx - ax) * 0.9, ay + (ly - ay) * 0.9) for (ax, ay), (lx, ly) in zip(mid, left)] + \
            [(ax + (rx - ax) * 0.9, ay + (ry - ay) * 0.9) for (ax, ay), (rx, ry) in zip(mid, right)][::-1]
    pen.poly(body, inner)
    half = [(ax + (lx - ax) * 0.9, ay + (ly - ay) * 0.9) for (ax, ay), (lx, ly) in zip(mid, left)] + mid[::-1]
    pen.poly(lit, half)
    # the gloss: a light band along the midrib on the upper half
    band = [(ax + (lx - ax) * 0.38, ay + (ly - ay) * 0.38) for (ax, ay), (lx, ly) in zip(mid[1:12], left[1:12])] + mid[1:12][::-1]
    pen.poly(shine, band)
    for i in range(len(mid) - 2):
        pen.line(vein, mid[i], mid[i + 1], 0.2)
    for j in range(2, 12, 2):                                              # side veins curving towards the tip
        ax, ay = mid[j]
        for side_pts in (left, right):
            ex, ey = side_pts[min(14, j + 3)]
            mx, my = (ax + ex) / 2 + (mid[min(14, j + 2)][0] - ax) * 0.3, (ay + ey) / 2 + (mid[min(14, j + 2)][1] - ay) * 0.3
            pen.line(vein, (ax, ay), (mx, my), 0.12)
            pen.line(vein, (mx, my), (ax + (ex - ax) * 0.86, ay + (ey - ay) * 0.86), 0.1)


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


# how far down we look at the castle: only a little (about 10 degrees) - in the real tank the water and the bowed front
# glass flatten the view a lot, so the tops show as narrow ellipses
VIEW_DOWN = 0.17


def castle_layer(sw, sh, k, dx=0.0, seed=4):
    """Our castle ruins: sculpted sandstone-like ceramic, several round towers of different heights - a tall
    one at the back with a wavy petal rim, a wide base with arches, a lower one in front on the left; each
    shaded as a cylinder lit from the front left, with a bumpy moulded surface, deep arches and moss."""
    nr = np.random.default_rng(seed)
    rgb = np.zeros((sh, sw, 3), np.float32)
    alpha = np.zeros((sh, sw), np.float32)
    yy, xx = np.mgrid[0:sh, 0:sw].astype(np.float32) / k
    sand = np.array([234, 186, 116], np.float32)
    bumps = smooth_noise(nr, sw, sh, 34) * 0.6 + smooth_noise(nr, sw, sh, 70) * 0.4      # the moulded relief
    grain = 1 + nr.normal(0, 0.04, (sh, sw)).astype(np.float32)
    mossmap = smooth_noise(nr, sw, sh, 26)

    # its shadow on the gravel
    shadow = (((xx - 112 - dx) / 19) ** 2 + ((yy - 104.6) / 2.8) ** 2) < 1
    alpha[shadow], rgb[shadow] = 0.42, 0

    def tower(cx, rad, top, base, petals, arches, cap="open"):
        """One round tower seen a little from above: its top an ellipse (the wall's rim and the dark inside
        of the ruin, or a flat roof), the foot, the bands and the arches curving round it.
        top - the height of the rim ellipse's centre; base - where the front of its foot meets the ground."""
        cx += dx
        arches = [(ax + dx, ay, aw, ah) for ax, ay, aw, ah in arches]
        e = rad * VIEW_DOWN                                  # the ellipses' half height (the view from above)
        u = (xx - cx) / rad
        inx = np.abs(u) < 1
        theta = np.arcsin(np.clip(u, -1, 1))
        nz = np.sqrt(np.clip(1 - u * u, 0, 1))
        lit = np.clip(-0.55 * u + 0.83 * nz, 0, 1)
        wav = 1.5 * np.abs(np.sin(theta * petals / 2 + 0.6)) ** 0.7 if cap == "open" else 0.0   # the petal rim
        front_top = top + e * nz - wav                     # the near edge of the rim (curving down at the middle)
        foot = base - e + e * nz                             # the foot: lowest in the middle, nearest to you
        body = inx & (yy >= front_top) & (yy <= foot)
        relief = (bumps - 0.5) * 0.5 + 0.05 * np.sin(theta * 9)
        shade = (0.38 + 0.72 * lit) * (1 + relief) * grain
        band_y = top + 3.4 + e * nz                          # a moulded band under the rim, curving round
        band = np.abs(yy - band_y) < 0.7
        shade = np.where(band, shade * (1.12 - 0.3 * (yy - band_y + 0.6)), shade)
        shade *= 1 - 0.3 * np.clip((yy - (foot - 5)) / 5, 0, 1)
        col = np.minimum(sand[None, None, :] * shade[..., None], 255)
        for ax, ay, aw, ah in arches:                        # arched openings, following the curve
            ar = aw / 2
            ua = np.clip((ax - cx) / rad, -0.99, 0.99)
            ay = ay + e * math.sqrt(1 - ua * ua)
            hole = ((np.abs(xx - ax) < ar) & (yy > ay - ah / 2 + ar) & (yy < ay + ah / 2)) | \
                   ((((xx - ax) ** 2 + (yy - (ay - ah / 2 + ar)) ** 2) < ar * ar) & (yy <= ay - ah / 2 + ar))
            hole &= body
            depth = np.clip((yy - (ay - ah / 2)) / ah, 0, 1)
            col[hole] = np.array([40, 30, 22], np.float32) * (0.8 + 0.5 * depth[hole, None])
            edge = (np.abs(xx - (ax + ar - 0.35)) < 0.4) & (yy > ay - ah / 2 + ar) & (yy < ay + ah / 2) & body
            col[edge] = sand * 1.05
            lip = (((xx - ax) ** 2 + (yy - (ay - ah / 2 + ar)) ** 2) < (ar + 0.7) ** 2) & ~hole & body & (yy < ay - ah / 2 + ar)
            col[lip] = np.minimum(col[lip] * 1.18, 255)
        moss = body & (mossmap > 0.58) & (nr.random((sh, sw)) < 0.6)
        col[moss] = np.array([136, 150, 64], np.float32) * (0.6 + 0.6 * lit[moss, None])
        rgb[body], alpha[body] = col[body], 1
        # the top, seen from above: an ellipse
        r = np.sqrt(u * u + ((yy - top) / e) ** 2)
        if cap == "open":                                    # the wall's rim, then the dark inside of the ruin
            back_top = top - e * nz - wav
            cap_m = inx & (r < 1.0) & (yy >= back_top) & (yy < front_top + 0.01)
            rim = cap_m & (r > 0.8)
            inside = cap_m & (r <= 0.8)
            rimcol = np.minimum(sand * (1.05 + 0.25 * (1 - (yy - top + e) / (2 * e)))[..., None] * grain[..., None], 255)
            rgb[rim], alpha[rim] = rimcol[rim], 1
            dark = sand * 0.28 * (1 + 0.8 * np.clip((yy - (top - e)) / (2 * e), 0, 1))[..., None]   # lighter low in front
            rgb[inside], alpha[inside] = dark[inside], 1
        else:                                                # a flat roof, lit
            cap_m = inx & (r < 1.0)
            roof = np.minimum(sand * (1.12 + 0.18 * (bumps[..., None] - 0.5)) * grain[..., None], 255)
            rgb[cap_m], alpha[cap_m] = roof[cap_m], 1
            edge = cap_m & (r > 0.93)
            rgb[edge] = sand * 0.85

    # the wide base with a flat roof, the tall tower standing on it, the lower tower in front on the left
    tower(112.0, 16.5, 74.0, 104.0, 9, [(104.5, 89, 4.6, 10), (115.5, 91, 5.2, 11), (124.5, 88, 3.6, 8)], cap="flat")
    tower(113.5, 10.5, 46.0, 75.5, 7, [(110.0, 58, 4.0, 8.5), (118.4, 60, 3.2, 7)])
    tower(92.0, 7.5, 80.0, 104.0, 6, [(91.0, 92, 3.4, 7.5)])
    lay = pygame.Surface((sw, sh), pygame.SRCALPHA)
    pygame.surfarray.blit_array(lay, np.clip(rgb, 0, 255).astype(np.uint8).swapaxes(0, 1))
    a = pygame.surfarray.pixels_alpha(lay)
    a[:] = (np.clip(alpha, 0, 1) * 255).astype(np.uint8).T
    del a
    return lay


def glow_layer(sw, sh, k, stones):
    """What the fluorescent stones give off in the dark - like glass beads lit from inside: their own colour,
    deep at the rim and lighter towards the middle (a little up and to the left), a small soft highlight, and
    only a faint halo of the same colour on the gravel round them (no white: the colour stays)."""
    core = np.zeros((sh, sw, 3), np.float32)
    for cx, cy, rx, ry, color in stones:
        x0, x1 = max(0, int((cx - rx - 1) * k)), min(sw, int((cx + rx + 1) * k) + 1)
        y0, y1 = max(0, int((cy - ry - 1) * k)), min(sh, int((cy + ry + 1) * k) + 1)
        yy, xx = np.mgrid[y0:y1, x0:x1].astype(np.float32)
        u, v = (xx / k - cx) / rx, (yy / k - cy) / ry
        m = u * u + v * v < 1
        inner = np.clip(1 - ((u + 0.22) ** 2 + (v + 0.28) ** 2) / 1.45, 0, 1) ** 1.1
        c = np.array(color, np.float32) * (0.38 + 0.62 * inner)[..., None]
        spec = np.clip(1 - ((u + 0.4) ** 2 + (v + 0.48) ** 2) / 0.05, 0, 1) ** 2 * 0.3
        c += (255 - c) * spec[..., None]
        reg = core[y0:y1, x0:x1]
        reg[m] = c[m]
    small = pygame.surfarray.make_surface(np.clip(core, 0, 255).astype(np.uint8).swapaxes(0, 1))
    q = max(8, sw // 40) * 2
    qh = max(1, q * sh // sw)
    halo = pygame.transform.smoothscale(pygame.transform.smoothscale(small, (q, qh)), (sw, sh))
    h = pygame.surfarray.array3d(halo).swapaxes(0, 1).astype(np.float32)
    hl = h.max(axis=2)
    inside = core.max(axis=2) > 0
    # laid over the stones (not added to them: the pale stone under it would wash the colour out)
    rgb = np.where(inside[..., None], core, h * (190 / np.maximum(hl, 1))[..., None])
    alpha = np.where(inside, 240, np.clip(hl * 0.75, 0, 90))
    lay = pygame.Surface((sw, sh), pygame.SRCALPHA)
    pygame.surfarray.blit_array(lay, np.clip(rgb, 0, 255).astype(np.uint8).swapaxes(0, 1))
    a = pygame.surfarray.pixels_alpha(lay)
    a[:] = alpha.astype(np.uint8).T
    del a
    return lay


LAYERS = ("bg", "stem", "broad", "round", "red", "stones", "front", "glow")


def load_scene():
    """The still scene's layers from the cache, or built (a few seconds on the Zero) and cached."""
    name = os.path.join(CACHE, "aquarium-v%d-%dx%d" % (SCENE_VERSION, NW, NH))
    try:
        return {n: pygame.image.load("%s-%s.png" % (name, n)) for n in LAYERS}
    except (pygame.error, FileNotFoundError, OSError):
        pass
    out = build_scene()
    try:
        os.makedirs(CACHE, exist_ok=True)
        for n in LAYERS:
            pygame.image.save(out[n], "%s-%s.png" % (name, n))
    except (pygame.error, OSError):
        pass
    return out


def build_rays():
    """Two layers of soft light rays from the lamp (their brightness pulses in turn)."""
    layers = []
    fade = np.clip(1 - np.linspace(0, 1, NH) * 1.2, 0, 1) ** 1.5
    for xs in ((24, 60, 98), (40, 80, 112)):
        s = pygame.Surface((NW, NH), pygame.SRCALPHA)
        for x in xs:
            x = X(x)
            pygame.draw.polygon(s, (240, 255, 255, 40), [P(x - 3, 0), P(x + 4, 0), P(x + 14, 108), P(x - 2, 108)])
        a = pygame.surfarray.pixels_alpha(s)
        a[:] = (a * fade[None, :]).astype(np.uint8)
        del a
        layers.append(s)
    return layers


_scene = load_scene()
BACKGROUND = _scene["bg"]
# the light rays are baked into the backdrop (two full-screen alpha layers per frame were too slow on the Zero)
for _layer in build_rays():
    _layer.set_alpha(190)
    BACKGROUND.blit(_layer, (0, 0))
BACKGROUND = BACKGROUND.convert(canvas)            # the canvas' pixel format: no conversion on every blit


class Layer:
    """A still layer cut to what it covers (blending a whole transparent screen is slow on the Zero)."""

    def __init__(self, surf):
        surf = surf.convert_alpha()
        self.rect = surf.get_bounding_rect()
        self.img = surf.subsurface(self.rect).copy()

    def draw(self, dst):
        dst.blit(self.img, self.rect.topleft)


class Sway(Layer):
    """A plant group swaying in the current: drawn in horizontal bands, each shifted more the higher it is,
    with the phase lagging upwards - a slow wave runs up the stems."""
    BAND = 6                                       # native pixels per band

    def __init__(self, surf, base, height, amp, speed, phase):
        super().__init__(surf)
        self.base, self.height = base * S, height * S
        self.amp, self.speed, self.phase = amp * S, speed, phase

    def draw(self, dst, t=0.0):
        x0, y0 = self.rect.topleft
        w, h = self.img.get_size()
        for r in range(0, h, self.BAND):
            f = min(1.0, max(0.0, (self.base - (y0 + r + self.BAND / 2)) / self.height))
            dx = self.amp * f ** 1.6 * (math.sin(t * self.speed + self.phase - f * 1.4)
                                        + 0.3 * math.sin(t * self.speed * 2.3 + self.phase * 1.7 - f * 2.0))
            dst.blit(self.img, (x0 + dx, y0 + r), (0, r, w, min(self.BAND, h - r)))


PLANTS = [Sway(_scene["stem"], 104, 95, 2.4, 0.55, 0.0), Sway(_scene["broad"], 104, 54, 1.3, 0.7, 1.3),
          Sway(_scene["red"], 104, 24, 0.9, 0.8, 2.1), Sway(_scene["round"], 103, 36, 1.0, 0.85, 3.0)]
STONES = Layer(_scene["stones"])
FRONT = Layer(_scene["front"])
GLOW = Layer(_scene["glow"])                        # laid over the stones in the dark, more the darker it is
del _scene
SCENE_EVERY = 0.15                                 # seconds between re-composing the swaying plants
HAT_DIM = None
if lcd.DEVICE == "hat144":                          # 30 % darker on the 1.44" HAT (its LCD is very bright)
    HAT_DIM = pygame.Surface((NW, NH)).convert(canvas)
    HAT_DIM.fill((0, 0, 0))
    HAT_DIM.set_alpha(int(255 * 0.30))
NIGHT = pygame.Surface((NW, NH)).convert(canvas)
NIGHT.fill((2, 6, 18))
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


GRASS = [Grass(X(73), 30), Grass(X(80), 18)]


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
    X0, X1, Y0, Y1 = -14, 9, -18, 27
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
    # the ventral fins: two long thin feelers from under the chest, past the anal fin, curving back
    feeler = (*((255, 244, 226) if gold else (244, 240, 226)), 235)
    for j, dx in enumerate((0.0, 1.1)):
        sw = tail * 0.8 * (1 if j else 0.7)
        pts = []
        for i in range(9):
            u = i / 8
            pts.append(T(2.6 + dx - 3.2 * u - 2.6 * u * u + sw * u * u, 5.0 + 20.5 * u + dx * 0.8 * u))
        # a thin dark edge first, so the pale feeler reads on the light water too
        pygame.draw.lines(surf, (70, 82, 96, 190), False, pts, max(2, int(1.05 * k)))
        pygame.draw.lines(surf, feeler, False, pts, max(1, int(0.6 * k)))
        pygame.draw.circle(surf, feeler, pts[-1], max(1, 0.4 * k))
    pygame.draw.circle(surf, (196, 60, 34), T(4.9, -1.7), 1.25 * k)
    pygame.draw.circle(surf, (10, 10, 10), T(5.0, -1.7), 0.62 * k)
    pygame.draw.circle(surf, (255, 255, 255), T(5.25, -2.0), 0.2 * k)
    pygame.draw.line(surf, (90, 70, 50), T(7.2, 0.1), T(6.4, 0.5), max(1, int(0.3 * k)))
    return finish(surf, size, X0, X1, Y0, Y1)


ANGEL_BOX = (-14, 9, -18, 27)    # the angelfish sprite's extent (logical, facing right)


def far_eye(size):
    """The other eye, seen past the snout when an angelfish turns three quarters to you."""
    surf, T, k = sprite_canvas(-1.2, 1.2, -1.2, 1.2, size)
    pygame.draw.circle(surf, (196, 60, 34), T(0, 0), 1.0 * k)
    pygame.draw.circle(surf, (10, 10, 10), T(0.15, 0), 0.52 * k)
    pygame.draw.circle(surf, (255, 255, 255), T(-0.1, -0.3), 0.17 * k)
    return finish(surf, size, -1.2, 1.2, -1.2, 1.2)


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
    pygame.draw.lines(surf, (110, 240, 250, 230), False, stripe[: len(xs[4:-6])], max(1, int(0.22 * k)))
    pygame.draw.circle(surf, (200, 210, 220), T(2.55, -0.25), 0.62 * k)
    pygame.draw.circle(surf, (8, 8, 12), T(2.6, -0.25), 0.4 * k)
    return finish(surf, size, X0, X1, Y0, Y1)


# our GloFish: coral orange, lime, hot pink and a pale pearly pink (each glows its own colour in the dark)
GLO_ORANGE, GLO_LIME, GLO_PINK, GLO_ROSE = (255, 108, 62), (212, 226, 64), (255, 92, 168), (230, 156, 182)


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
        pygame.draw.polygon(surf, (*mix(color, (255, 255, 255), 0.08), 255), [T(*p) for p in body])
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

    def __init__(self, sprites, x, y, speed, zone, margin=4, nose=4.0, low=None):
        self.right, self.left = sprites
        self.nose = nose                 # from its centre to its mouth (logical): where it pecks with
        self.low = margin if low is None else low   # how close to the gravel it may come while pecking
        self.forage = None               # pecking at something: {"x", "y", "kind", "t", "pecks", ...}
        self.face_lock = None            # faces this way while pecking (it backs off without turning)
        self.turn_rate = rng.uniform(1.4, 3.0)    # each fish turns at its own pace ...
        self.activity = 1.0              # 1 by day; at night the fish nearly sleep (see Tank.update)
        self.depth = 1.0                 # > 1 - up at the front glass (drawn a little bigger)
        self.front, self.front_target, self.eye2 = 0.0, 0.0, None   # 1 - turned three quarters to you
        self.flip_at = rng.uniform(0.6, 1.8)      # ... and only once it really swims the other way
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
        self.rest = rng.uniform(0.3, 2.5) / max(0.15, self.activity) ** 1.5

    def steer(self, tx, ty, dt, speed, accel=1.6):
        dx, dy = tx - self.x, ty - self.y
        d = math.hypot(dx, dy) or 1
        want = min(speed * self.activity, d * 1.2)
        self.vx += (dx / d * want - self.vx) * min(1, accel * dt)
        self.vy += (dy / d * want * 0.55 - self.vy) * min(1, accel * dt)
        return d

    def start_forage(self, x, y, kind):
        """Swim to (x, y) and peck at it a few times: kind 'ground' (sand puffs), 'stone' or 'plant'."""
        self.forage = {"x": x, "y": y, "kind": kind, "t": 0.0, "pecks": rng.randint(2, 5), "phase": 0,
                       "pt": 0.0, "touch": False}
        self.rest = 0

    def forage_step(self, dt):
        F = self.forage
        F["t"] += dt
        side = 1 if self.x < F["x"] else -1 if F["phase"] == 0 else self.face_lock
        tx, ty = F["x"] - side * self.nose, F["y"] + (1.2 if F["kind"] != "plant" else 0.3)
        if F["phase"] == 0:                                  # swim up to it
            if self.steer(tx, ty, dt, self.speed * 0.8, 2.2) < 1.6 or F["t"] > 9:
                F["phase"], self.face_lock = 1, side
        else:                                                # peck: in, back a little, in again
            F["pt"] += dt
            touch = F["pt"] % 0.6 < 0.28
            if touch and not F["touch"]:
                F["pecks"] -= 1
                if F["kind"] == "ground":
                    for _ in range(4):
                        PUFFS.append([F["x"] + rng.uniform(-1, 1), F["y"], rng.uniform(-3, 3), rng.uniform(-5, -2), 1.2])
            F["touch"] = touch
            if touch:
                self.steer(tx, ty, dt, self.speed * 0.7, 6)
            else:
                self.steer(tx - side * 2.2, ty - 0.8, dt, self.speed * 0.5, 5)
            if F["pecks"] <= 0 and not touch:
                self.forage, self.face_lock = None, None
                self.pick_target()
        if self.forage is not None and F["t"] > 14:          # gave up
            self.forage, self.face_lock = None, None

    def update(self, dt, food):
        if self.forage is not None:
            if food:
                self.forage, self.face_lock = None, None
            else:
                self.forage_step(dt)
                self.move(dt)
                return
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
        self.x = max(6, min(W - 6, self.x))
        low = self.low if self.forage is not None else self.margin
        self.y = max(SURFACE_Y + self.margin, min(ground_line(self.x) - low, self.y))
        want = 1.0 if self.vx > self.flip_at else -1.0 if self.vx < -self.flip_at else (1.0 if self.face >= 0 else -1.0)
        if self.face_lock:
            want = self.face_lock
        self.face += max(-dt * self.turn_rate, min(dt * self.turn_rate, want - self.face))
        climb = max(-1.0, min(1.0, self.vy / max(3.0, abs(self.vx) + 1.0)))
        if self.forage is not None and self.forage["phase"] == 1:   # nose down to peck
            climb = 0.85 if self.forage["kind"] != "plant" else 0.4
        self.tilt += (climb - self.tilt) * min(1, dt * 3)
        self.tail += dt * ((0.6 + 1.6 * self.activity) + abs(self.vx) * 0.3 + abs(self.vy) * 0.2)

    def tilt_row(self, rows):
        return rows[min(len(rows) - 1, max(0, int(round((self.tilt + 1) / 2 * (len(rows) - 1)))))]

    def image(self):
        row = self.tilt_row(self.right if self.face >= 0 else self.left)
        img = row[int(self.tail) % TAIL_FRAMES]
        wscale = abs(self.face)
        if wscale < 0.97:                                   # turning: narrower
            img = pygame.transform.smoothscale(img, (max(1, int(img.get_width() * max(0.2, wscale))), img.get_height()))
        return img

    def draw(self, surf):
        img = self.image()
        if self.eye2 is not None and self.front > 0.02:
            # turning three quarters to you: the body foreshortens, the far eye shows past the snout
            img = pygame.transform.smoothscale(img, (max(1, int(img.get_width() * (1 - 0.4 * self.front))), img.get_height()))
            if self.front > 0.45:
                x0, x1, y0, y1 = ANGEL_BOX
                ex = (5.7 - x0) / (x1 - x0) * img.get_width()
                if self.face < 0:
                    ex = img.get_width() - ex
                ey = (-2.6 - y0) / (y1 - y0) * img.get_height()
                img = img.copy()
                self.eye2.set_alpha(int(255 * min(1.0, (self.front - 0.45) * 2.5)))
                img.blit(self.eye2, (ex - self.eye2.get_width() / 2, ey - self.eye2.get_height() / 2))
        if abs(self.depth - 1) > 0.01:
            img = pygame.transform.smoothscale(img, (int(img.get_width() * self.depth), int(img.get_height() * self.depth)))
        surf.blit(img, (self.x * S - img.get_width() / 2, self.y * S - img.get_height() / 2))
        return img


PUFFS = []          # sand grains stirred up by pecking at the gravel: [x, y, vx, vy, life]


def peck_spot(x, y, kinds):
    """Somewhere to peck at near (x, y): the gravel, the top of a stone, a leaf."""
    cands = []
    if "ground" in kinds:
        for _ in range(4):
            gx = max(14, min(X(100), x + rng.uniform(-30, 30)))
            if not (abs(gx - X(34)) < 10 or abs(gx - X(60)) < 8):     # not under the stones
                cands.append((gx, ground_line(gx) - 0.3, "ground"))
    if "stone" in kinds:
        cands += [(X(34) + rng.uniform(-5, 5), 92.5 + rng.uniform(0, 1.5), "stone"),
                  (X(60) + rng.uniform(-4, 4), 92 + rng.uniform(0, 1.5), "stone")]
    if "plant" in kinds:
        cands += [(X(rng.uniform(6, 34)), rng.uniform(44, 92), "plant"), (X(rng.uniform(40, 56)), rng.uniform(82, 94), "plant"),
                  (X(rng.uniform(18, 32)), rng.uniform(84, 96), "plant"), (rng.uniform(84, 98) + DB, rng.uniform(86, 98), "plant")]
    return min(cands, key=lambda c: (c[0] - x) ** 2 + (c[1] - y) ** 2 + rng.uniform(0, 900))


class School:
    """A shoal: a leader wanders, the others keep their place around it with a little jitter.

    members - [(sprite frames, glow sprite (right, left) or None)]; the glow is what is still seen
    when the lamp is off (the neons' blue stripe, the GloFish's whole fluorescent body)."""

    def __init__(self, members, start, zone, speed, spread):
        self.leader = Fish(([[None]], [[None]]), *start, speed * 0.8, zone)
        self.glow = [g for _, g, _ in members]
        self.fish = []
        self.next_forage = rng.uniform(4, 9)
        self.hist = []                  # (t, x, y) of the leader: each fish follows it with its own lag
        for frames_, _, nose in members:
            f = Fish(frames_, start[0] + rng.uniform(-10, 10), start[1] + rng.uniform(-6, 6), speed, zone,
                     nose=nose, low=1.5)
            f.off = (rng.uniform(-spread[0], spread[0]), rng.uniform(-spread[1], spread[1]))
            f.lag = rng.uniform(0.05, 1.3)
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
        self.hist.append((t, L.x, L.y))
        if len(self.hist) > 40 and self.hist[0][0] < t - 1.6:
            del self.hist[:10]
        # now and then one fish drops out of the shoal to peck at something near it, then catches up
        self.next_forage -= dt * self.leader.activity ** 2
        if self.next_forage <= 0 and not food:
            self.next_forage = rng.uniform(5, 12)
            idle = [f for f in self.fish if f.forage is None]
            if idle and sum(f.forage is not None for f in self.fish) < 2:
                f = rng.choice(idle)
                f.start_forage(*peck_spot(f.x, f.y, ("ground", "stone", "plant")))
        for f in self.fish:
            if f.forage is not None or (food and any((p.x - f.x) ** 2 + (p.y - f.y) ** 2 < 40 ** 2 for p in food)):
                f.update(dt, food)
                continue
            ox = f.off[0] + 2.5 * math.sin(t * 0.7 + f.jit)
            oy = f.off[1] + 1.8 * math.sin(t * 1.1 + f.jit * 1.3)
            lx, ly = L.x, L.y
            for ht, hx, hy in reversed(self.hist):            # where the leader was f.lag seconds ago
                lx, ly = hx, hy
                if ht <= t - f.lag:
                    break
            f.steer(lx + ox, ly + oy, dt, f.speed, rng.uniform(1.8, 2.8))
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
            g = f.tilt_row(gs[0] if f.face >= 0 else gs[1])
            if img.get_width() != g.get_width():
                g = pygame.transform.smoothscale(g, (img.get_width(), g.get_height()))
            g.set_alpha(int(255 * strength))
            surf.blit(g, (f.x * S - g.get_width() / 2, f.y * S - g.get_height() / 2))


def glow_frames(img):
    """The glow sprite at each tilt: ([right per tilt], [left per tilt])."""
    right = [pygame.transform.rotozoom(img, -deg, 1) if deg else img for deg in TILTS]
    return right, [pygame.transform.flip(g, True, False) for g in right]


def neon_school(n):
    members = []
    for _ in range(n):
        s = rng.uniform(0.85, 1.1)
        members.append((tilted_frames(neon_sprite, s), glow_frames(neon_sprite(s, 0, True)), 4.6 * s))
    return School(members, (X(66), 82), (14, 56, W - 16, 98), 19, (16, 8))


def glofish_school(colors):
    members = []
    for c in colors:
        s = rng.uniform(0.9, 1.05)
        members.append((tilted_frames(glofish_sprite, s, c), glow_frames(glofish_sprite(s, c, 0, True)), 5.0 * s))
    return School(members, (X(40), 60), (14, 34, X(100), 86), 14, (10, 7))


# ---------------------------------------------------------------- air, food, the surface, the ducks

STONE = (88 + DC, 106)      # the air stone (logical): bubbles come from here


class Bubble:
    """Rises from the air stone; grows on the way up and wobbles wider and wider (after Codex's version)."""

    def __init__(self, x, y):
        self.x0, self.y0, self.y = x, y, y
        self.r0 = rng.uniform(0.5, 1.2)
        self.v = rng.uniform(14, 20)
        self.ph = rng.uniform(0, 6.3)
        self.x, self.r = x, self.r0

    def update(self, dt):
        self.y -= self.v * dt
        age = (self.y0 - self.y) / (self.y0 - SURFACE_Y)
        self.ph += dt * 1.6
        self.r = self.r0 * (0.6 + age * 0.65)
        self.x = self.x0 + math.sin(age * 15 + self.ph) * (1 + age * 2.5)
        return self.y > SURFACE_Y + 1


class Flake:
    """A flake of food: floats on the surface a moment, then sinks tumbling and swaying."""

    def __init__(self, x=None):
        self.x = X(rng.uniform(30, 100)) if x is None else max(8, min(W - 8, x + rng.uniform(-7, 7)))
        self.y = SURFACE_Y - 0.5
        self.c = rng.choice(((222, 124, 52), (200, 72, 44), (232, 188, 84), (186, 96, 52), (150, 170, 70)))
        self.edge = mix(self.c, (255, 240, 200), 0.45)
        self.size = rng.uniform(1.4, 2.4)
        n = 6
        self.shape = [(math.cos(2 * math.pi * i / n) * rng.uniform(0.6, 1.0), math.sin(2 * math.pi * i / n) * rng.uniform(0.35, 0.7))
                      for i in range(n)]
        self.ph = rng.uniform(0, 6.3)
        self.spin = rng.uniform(-2.5, 2.5)
        self.float_for = rng.uniform(1.0, 2.5)
        self.age = 0.0

    def update(self, dt):
        self.age += dt
        floor = ground_line(self.x) - 0.6
        if self.age < self.float_for:                       # on the surface, bobbing with it
            self.x += math.sin(self.age * 1.3 + self.ph) * 1.2 * dt
            self.y = surface_y(self.x, self.age + self.ph) + 0.4
        elif self.y < floor:
            self.y += 4.2 * dt
            self.x += math.sin(self.age * 2.2 + self.ph) * 4 * dt
            self.ph += self.spin * dt
        return self.age < 40

    def draw(self, surf):
        a = self.ph if self.age >= self.float_for else 0.0
        flat = 0.45 + 0.55 * abs(math.cos(a)) if self.age >= self.float_for else 1.0   # tumbling: edge-on now and then
        ca, sa = math.cos(a * 0.7), math.sin(a * 0.7)
        pts = [P(self.x + (px * ca - py * sa) * self.size, self.y + (px * sa + py * ca) * self.size * flat)
               for px, py in self.shape]
        pygame.draw.polygon(surf, self.c, pts)
        pygame.draw.aalines(surf, self.edge, True, pts)


def build_beam():
    """At night the bubble stream catches what light there is: a faint bluish column round it, widening as the
    bubbles spread, brighter up towards the surface, and a soft light patch on the surface where they burst."""
    x0, x1 = STONE[0] - 16, STONE[0] + 16
    y0, y1 = SURFACE_Y - 3, STONE[1]
    w, h = int((x1 - x0) * S), int((y1 - y0) * S)
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float32) / S
    xx += x0
    yy += y0
    age = np.clip((STONE[1] - yy) / (STONE[1] - SURFACE_Y), 0, 1)
    spread = 2.2 + 3.2 * age
    col = np.exp(-((xx - STONE[0]) / spread) ** 2) * (0.25 + 0.75 * age ** 1.5)
    top = np.exp(-((xx - STONE[0]) / 11) ** 2 - ((yy - SURFACE_Y) / 2.2) ** 2) * 0.9
    v = np.clip(col + top, 0, 1.2)
    rgb = v[..., None] * np.array([34, 86, 150], np.float32)
    lay = pygame.Surface((w, h))
    pygame.surfarray.blit_array(lay, np.clip(rgb, 0, 255).astype(np.uint8).swapaxes(0, 1))
    return lay, (int(x0 * S), int(y0 * S))


BEAM, BEAM_AT = build_beam()
BEAM_CACHE = {}


def draw_air_gear(surf):
    """The air stone on the gravel (its tube runs behind the castle)."""
    pygame.draw.ellipse(surf, (78, 86, 96), (*P(STONE[0] - 4, STONE[1] - 1.8), 8 * S, 3.6 * S))
    pygame.draw.ellipse(surf, (122, 130, 140), (*P(STONE[0] - 3, STONE[1] - 1.5), 5 * S, 1.6 * S))


HEATER_LED = (109.7 + DC, 33)


def finger_sprite():
    """A fingertip pressed to the front glass: pale, with a lighter middle and a few ridges."""
    surf, T, k = sprite_canvas(-6, 6, -7, 7, 1)
    pygame.draw.ellipse(surf, (236, 198, 182, 120), (*T(-5, -6.4), 10 * k, 12.8 * k))
    pygame.draw.ellipse(surf, (248, 222, 210, 120), (*T(-3.2, -4.6), 6.4 * k, 8.4 * k))
    for i in range(4):
        rr = 1.2 + i * 1.1
        pygame.draw.arc(surf, (214, 170, 156, 110), (*T(-rr, -rr * 1.2), 2 * rr * k, 2.4 * rr * k), 0.3, 2.8, max(1, int(0.25 * k)))
    pygame.draw.ellipse(surf, (196, 150, 136, 160), (*T(-5, -6.4), 10 * k, 12.8 * k), max(1, int(0.35 * k)))
    return finish(surf, 1, -6, 6, -7, 7)


FINGER = finger_sprite()


def draw_heater_led(surf, on, light=1.0):
    """The heater's thermostat lamp: orange with a little halo while it heats."""
    x, y = P(*HEATER_LED)
    if on:
        for rr, a in ((2.0, 40), (1.3, 80), (0.8, 160)):
            g = pygame.Surface((int(rr * 2 * S) + 2, int(rr * 2 * S) + 2), pygame.SRCALPHA)
            pygame.draw.circle(g, (255, 150, 40, a), (g.get_width() / 2, g.get_height() / 2), rr * S)
            surf.blit(g, (x - g.get_width() / 2, y - g.get_height() / 2))
        pygame.draw.circle(surf, (255, 230, 150), (x, y), max(1, 0.42 * S))
    else:
        pygame.draw.circle(surf, mix((24, 16, 14), (110, 60, 40), light), (x, y), max(1, 0.42 * S))


def surface_y(x, t):
    return SURFACE_Y - 1.0 + 0.6 * math.sin(x * 0.16 + t * 1.6) + 0.35 * math.sin(x * 0.33 - t * 1.1)


def draw_surface(surf, t, light):
    pts = [P(0, 0)] + [P(k * 4, surface_y(k * 4, t)) for k in range(int(W / 4) + 2)] + [P(W + 4, 0)]
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

# the lamp's timer, like ours, in hours of the day: (from, to, light from -> to, green from -> to);
# a smooth curve inside each stretch
SCHEDULE = [
    (0.0, 7.0, 0.0, 0.0, 1.0, 1.0),       # night: off
    (7.0, 7.5, 0.0, 1.0, 1.0, 0.0),       # 07:00 the lamp comes on slowly
    (7.5, 19.0, 1.0, 1.0, 0.0, 0.0),      # day: full light
    (19.0, 21.5, 1.0, 0.38, 0.0, 1.0),    # 19:00 dimming, turning green
    (21.5, 23.5, 0.38, 0.38, 1.0, 1.0),   # 21:30 a dim green evening light
    (23.5, 23.6, 0.38, 0.0, 1.0, 1.0),    # 23:30 off for the night
    (23.6, 24.0, 0.0, 0.0, 1.0, 1.0),
]


def timer_light(h):
    """(light 0..1, green 0..1, which stretch, when it ends) at hour h."""
    for i, (a, b, l0, l1, g0, g1) in enumerate(SCHEDULE):
        if a <= h < b:
            u = (h - a) / (b - a)
            u = u * u * (3 - 2 * u)
            return l0 + (l1 - l0) * u, g0 + (g1 - g0) * u, i, b
    return 0.0, 1.0, 0, 7.0


class Tank:
    def __init__(self):
        kinds = (("silver", 1.0, (40, 40)), ("gold", 0.95, (84, 30)), ("silver", 0.88, (62, 58)))
        self.angels = [Fish(tilted_frames(angelfish_sprite, size, kind), X(x), y, 8.5, (16, 28, W - 16, 80), margin=15,
                            nose=9.5 * size, low=11) for kind, size, (x, y) in kinds]
        self.angel_peck = rng.uniform(8, 16)
        for f, (kind, size, _) in zip(self.angels, kinds):
            f.others = [g for g in self.angels if g is not f]
            f.pick_target()
            f.eye2 = far_eye(size * 0.95)
        self.school = neon_school(11)
        self.glofish = glofish_school((GLO_ORANGE, GLO_LIME, GLO_PINK, GLO_ROSE, GLO_ORANGE))
        self.platy = Fish(tilted_frames(platy_sprite, 1.0), X(30), 88, 9, (12, 64, X(70), 100), margin=4, nose=5.6, low=1.5)
        self.platy_peck = rng.uniform(4, 9)
        self.bubbles, self.food = [], []
        self.light, self.light_on, self.green = 0.0, True, 0.0
        self.manual = None              # (on, the timer's stretch): the 1 key overrides it until the next stretch
        start = os.environ.get("AQUARIUM_CLOCK")       # "HH:MM" - start the clock there (to try the timer)
        lt = time.localtime()
        self.clock0 = (int(start[:2]) + int(start[3:5]) / 60) if start else lt.tm_hour + lt.tm_min / 60 + lt.tm_sec / 3600
        self.clock_speed = float(os.environ.get("AQUARIUM_CLOCK_SPEED", "1"))
        self.air_on, self.air_level = True, 0.0
        self.emit = 0.0
        self.flicker_until = 0.0
        self.t0 = time.monotonic()
        self.air_after = 2.2           # the pump starts a moment after the lamp
        self.scene, self.scene_t = None, -1.0
        self.activity = 1.0
        self.visitor_t = 0.0            # when someone was last at the tank (a key; the start counts too)
        self.want_camera = False
        self.finger, self.finger_t, self.held = [W / 2, 60.0], -99.0, set()   # the fingertip on the glass
        self.calm_t = -99.0             # after a tap the fish are too scared to be curious for a while
        self.taps = []                  # (x, y, when): rings spreading from a tap on the glass
        self.splashes = []              # (x, when): rings on the surface where food was dropped
        self.toast = None               # (text, when): a short note on the screen after a key
        self.charge = 0.6               # how much light the fluorescent stones have stored
        self.heater_on, self.heater_next = False, 8.0

    def hours(self, now):
        return (self.clock0 + (now - self.t0) * self.clock_speed / 3600) % 24

    def lamp(self, on, now):
        """The 1 key: the lamp on / off by hand until the timer's next stretch."""
        _, _, stretch, until = timer_light(self.hours(now))
        self.manual = (on, stretch)
        self.light_on = on
        if on:
            self.flicker_until = now + 0.9
        lcd.play("click")
        return until

    def say(self, text, t):
        self.toast = (text, t)

    def fishes(self):
        return self.angels + [self.platy] + self.school.fish + self.glofish.fish + [self.school.leader, self.glofish.leader]

    def finger_shown(self, t):
        return t - self.finger_t < 5.5

    def tap(self, t):
        """A knock on the glass at the finger: a ring spreads, the fish nearby dart away."""
        x, y = self.finger
        self.taps.append((x, y, t))
        self.finger_t, self.calm_t = t, t
        for f in self.fishes():
            dx, dy = f.x - x, f.y - y
            d = math.hypot(dx, dy) or 0.1
            if d < 48:
                f.forage, f.face_lock = None, None
                kick = 40 * (1 - d / 48) + 8
                f.vx += dx / d * kick
                f.vy += dy / d * kick * 0.7
                f.pick_target()
                f.rest = 0
        lcd.play("hit")

    def feed(self, t, x=None):
        if x is None and self.finger_shown(t):
            x = self.finger[0]
        new = [Flake(x) for _ in range(10)]
        self.food += new
        cx = sum(f.x for f in new) / len(new)
        self.splashes += [(cx + rng.uniform(-4, 4), t + i * 0.15) for i in range(3)]
        lcd.play("chip")

    def touch(self, x, y, t):
        """A touch on the monitor: at the top - food falls in there, in the middle - the camera (if there is
        one), at the bottom - a fingertip on the glass there and the fish come up to look."""
        self.visitor_t = t
        if y < H / 3:
            self.feed(t, x)
        elif y < H * 2 / 3 and CAMERA_URL and lcd.DISPLAY_MODE:
            self.want_camera = True
        else:
            self.finger[:] = [max(6, min(W - 6, x)), max(SURFACE_Y + 6, min(118, y))]
            self.finger_t = t

    def update(self, now, dt):
        t = now - self.t0
        # the finger moves while an arrow is held; the fish come up to look at it when it is still
        if self.held:
            sp = 46 * dt
            self.finger[0] = max(6, min(W - 6, self.finger[0] + sp * ((pygame.K_RIGHT in self.held) - (pygame.K_LEFT in self.held))))
            self.finger[1] = max(SURFACE_Y + 6, min(118, self.finger[1] + sp * ((pygame.K_DOWN in self.held) - (pygame.K_UP in self.held))))
            self.finger_t = t
        if self.finger_shown(t) and not self.food and t - self.calm_t > 3:
            fx, fy = self.finger
            for i, f in enumerate(self.angels):              # each at its own height beside the finger
                f.forage, f.face_lock = None, None
                side = 1 if f.x > fx else -1
                f.tx, f.ty, f.rest = fx + side * (10 + 6 * (i % 2)), fy + (i - 1) * 17, 0
            self.platy.tx, self.platy.ty, self.platy.rest = fx + (7 if self.platy.x > fx else -7), fy + 6, 0
            for school in (self.school, self.glofish):
                school.leader.tx, school.leader.ty, school.leader.rest = fx + (14 if school.leader.x > fx else -14), fy, 0
        self.taps = [tp for tp in self.taps if t - tp[2] < 0.8]
        self.splashes = [sp for sp in self.splashes if t - sp[1] < 1.3]
        # the fluorescent stones charge in the light and fade slowly in the dark (over some twenty minutes,
        # never quite out: the evening light and the room keep them glowing faintly)
        if self.light > 0.5:
            self.charge += (1 - self.charge) * dt / 25
        else:
            self.charge -= (self.charge - 0.4) * dt / 1200
        # the heater's thermostat switches it on now and then
        if t >= self.heater_next:
            self.heater_on = not self.heater_on
            self.heater_next = t + (rng.uniform(12, 35) if self.heater_on else rng.uniform(25, 80))
        # the lamp follows the timer (or the 1 key until the timer's next stretch); when it comes on from
        # dark it flickers like a fluorescent tube
        lit, green, stretch, _ = timer_light(self.hours(now))
        if self.manual and self.manual[1] != stretch:
            self.manual = None
        if self.manual:
            lit = 1.0 if self.manual[0] else 0.0
            green = 0.0 if self.manual[0] else green
        self.light_on = lit > 0.5
        if t < 0.7:
            target = 0.0
        elif lit > 0.5 and now < max(self.flicker_until, self.t0 + 1.6):
            target = lit if rng.random() < 0.45 else 0.15
        else:
            target = lit
        if t > 0.7 and t - dt <= 0.7 and lit > 0.5:
            lcd.play("click")
        self.green += (green - self.green) * min(1, dt * 2)
        # how lively the fish are: by day 1, in the green evening sleepy, at night they nearly hang in the water
        # (food, a tap or the finger wake them up for a while)
        want = 0.16 + 0.84 * min(1.0, max(0.0, (self.light - 0.05) / 0.85))
        if self.food or t - self.calm_t < 6 or self.finger_shown(t):
            want = max(want, 0.85)
        self.activity += (want - self.activity) * min(1, dt * 0.6)
        for f in self.fishes():
            f.activity = self.activity
        # the shoals sleep deeper: another 1.5 times slower at night (unless woken up)
        night = 1 - min(1.0, max(0.0, (self.light - 0.05) / 0.85))
        if not (self.food or t - self.calm_t < 6 or self.finger_shown(t)):
            for school in (self.school, self.glofish):
                for f in school.fish + [school.leader]:
                    f.activity = self.activity / (1 + 0.5 * night)
        self.light += (target - self.light) * min(1, dt * (14 if target > self.light else 3))
        # the pump
        if t > self.air_after and t - dt <= self.air_after:
            lcd.play("move")
        want = 1.0 if (self.air_on and t > self.air_after) else 0.0
        self.air_level += (want - self.air_level) * min(1, dt * 1.5)
        self.emit += dt * 9 * self.air_level
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
        # the angelfish and the platy peck too: the angelfish at leaves and the tops of the stones
        self.angel_peck -= dt * self.activity ** 2
        if self.angel_peck <= 0 and not self.food:
            self.angel_peck = rng.uniform(10, 22)
            f = rng.choice(self.angels)
            if f.forage is None:
                f.start_forage(*peck_spot(f.x, f.y, ("stone", "plant")))
        self.platy_peck -= dt * self.activity ** 2
        if self.platy_peck <= 0 and not self.food and self.platy.forage is None:
            self.platy_peck = rng.uniform(6, 14)
            self.platy.start_forage(*peck_spot(self.platy.x, self.platy.y, ("ground", "stone", "plant")))
        # the angelfish know people: while someone is at the tank they come up to the front glass and wait
        visiting = t - self.visitor_t < 25 and not self.food and not self.finger_shown(t) and t - self.calm_t > 3
        for i, f in enumerate(sorted(self.angels, key=lambda a: a.x)):
            if visiting:
                f.forage, f.face_lock = None, None
                f.tx = W / 2 - 20 + i * 20 + 3 * math.sin(t * 0.4 + i * 2)
                f.ty = 44 + (i % 2) * 12 + 4 * math.sin(t * 0.6 + i)
                f.rest = 0
                f.activity = max(f.activity, 0.7)
            near = visiting and math.hypot(f.x - f.tx, f.y - f.ty) < 5
            f.depth += ((1.14 if visiting and abs(f.x - f.tx) < 8 else 1.0) - f.depth) * min(1, dt * 0.7)
            f.front_target = 1.0 if near else 0.0            # at the glass it turns three quarters to you
            f.front += max(-dt * 1.4, min(dt * 1.4, f.front_target - f.front))
            if f.front > 0.3:                                # while looking at you it hardly moves
                f.vx *= 1 - min(1, dt * 3)
                f.vy *= 1 - min(1, dt * 3)
        self.school.update(dt, t, self.food)
        self.glofish.update(dt, t, self.food)
        self.platy.update(dt, self.food)
        for p in PUFFS:                                       # sand grains drift up a little and settle
            p[0] += p[2] * dt
            p[1] += p[3] * dt
            p[3] += 9 * dt
            p[4] -= dt
        PUFFS[:] = [p for p in PUFFS if p[4] > 0 and p[1] <= ground_line(p[0]) + 0.5]

    def draw(self, now):
        t = now - self.t0
        surf = canvas
        if t - self.scene_t >= SCENE_EVERY or self.scene is None:
            # the swaying plants change slowly: the backdrop with them and the stones is composed a few times
            # a second, ordinary frames copy it in one opaque blit (sway on every frame cost 13 ms on the Zero)
            self.scene_t = t
            if self.scene is None:
                self.scene = BACKGROUND.copy()
                if CLOCK:
                    CLOCK.draw(self.scene)
            else:
                self.scene.blit(BACKGROUND, (0, 0))
            if CLOCK:
                CLOCK.draw(self.scene)
            for plant in PLANTS:
                plant.draw(self.scene, t)
            STONES.draw(self.scene)
        surf.blit(self.scene, (0, 0))
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
        for p in PUFFS:
            pygame.draw.circle(surf, (150, 140, 118), P(p[0], p[1]), max(1, 0.4 * S))
        for fl in self.food:
            fl.draw(surf)
        for x, t0 in self.splashes:                           # rings where the food hit the surface
            age = (t - t0) / 1.2
            if 0 < age < 1:
                w, h = (2 + age * 12) * S, (0.8 + age * 2.2) * S
                pygame.draw.ellipse(surf, mix((60, 100, 120), (236, 252, 255), (1 - age) * self.light),
                                    (x * S - w / 2, (SURFACE_Y + 0.4) * S - h / 2, w, h), max(1, int(0.35 * S)))
        for b in self.bubbles:
            r = b.r * S
            pygame.draw.circle(surf, (196, 234, 248), P(b.x, b.y), max(r, 1.2), max(1, int(0.5 * S)))
            pygame.draw.circle(surf, (248, 254, 255), (b.x * S - r * 0.3, b.y * S - r * 0.4), max(1, 0.3 * S))
        FRONT.draw(surf)
        draw_surface(surf, t, self.light)
        draw_ducks(surf, t)
        if self.light < 0.999:                               # night: an opaque dark-blue sheet, whole-surface alpha
            col = mix((2, 6, 18), (6, 30, 12), self.green)    # evening green from the timer, night blue
            if col != getattr(self, "night_col", None):
                NIGHT.fill(col)
                self.night_col = col
            NIGHT.set_alpha(int(178 * (1 - self.light)))      # (2 ms on the Zero; per-pixel alpha took 32 ms)
            surf.blit(NIGHT, (0, 0))
        if self.light < 0.5:                                 # only the neons' stripes are seen in the dark
            self.school.draw_glow(surf, 1 - self.light * 2)
            self.glofish.draw_glow(surf, (1 - self.light * 2) * 0.38)
        glow = self.charge * (1 - self.light) ** 1.5
        if glow > 0.02:                                      # the fluorescent stones
            GLOW.img.set_alpha(int(255 * min(1.0, glow * (0.94 + 0.06 * math.sin(t * 1.3)))) // 6 * 6)
            GLOW.draw(surf)
        dark = 1 - min(1.0, self.light / 0.6)
        if CLOCK and dark > 0.02:
            CLOCK.draw_dark(surf, dark)
        if dark > 0.02:                                      # the bubbles in the dark, catching the light
            lv = int(255 * dark * self.air_level) // 16 * 16
            if lv > 0:
                beam = BEAM_CACHE.get(lv)
                if beam is None:
                    beam = BEAM.copy()
                    beam.fill((lv, lv, lv), special_flags=pygame.BLEND_RGB_MULT)
                    BEAM_CACHE[lv] = beam
                surf.blit(beam, BEAM_AT, special_flags=pygame.BLEND_RGB_ADD)
            rim = mix((44, 66, 86), (150, 206, 255), dark)
            spark = mix((60, 80, 96), (236, 248, 255), dark)
            for b in self.bubbles:
                r = b.r * S
                pygame.draw.circle(surf, rim, P(b.x, b.y), max(r, 1.2), max(1, int(0.45 * S)))
                pygame.draw.circle(surf, spark, (b.x * S - r * 0.3, b.y * S - r * 0.4), max(1, 0.3 * S))
        draw_heater_led(surf, self.heater_on, self.light)
        for x, y, t0 in self.taps:                           # the knock: rings on the glass
            age = (t - t0) / 0.8
            for j in range(2):
                a = age - j * 0.2
                if 0 < a < 1:
                    pygame.draw.circle(surf, mix((40, 60, 80), (235, 248, 255), (1 - a) * max(0.4, self.light)),
                                       P(x, y), (3 + a * 16) * S, max(1, int(0.4 * S)))
        if self.finger_shown(t):
            fade = min(1.0, max(0.0, (5.5 - (t - self.finger_t)) / 1.5))
            img = FINGER.copy()
            img.set_alpha(int(255 * fade * max(0.35, self.light)))
            surf.blit(img, (self.finger[0] * S - img.get_width() / 2, self.finger[1] * S - img.get_height() / 2))


def draw_hud(tank, now):
    """The name and the keys for the first seconds; a short note after the lamp / air keys."""
    t = now - tank.t0
    if tank.toast and t - tank.toast[1] < 1.8:
        text, t0 = tank.toast
        img = f_hint.render(text, True, (240, 246, 244))
        a = min(1.0, (1.8 - (t - t0)) / 0.5)
        w, h = img.get_width() + 6, img.get_height() + 2
        box = pygame.Surface((max(1, int(w * S)), max(1, int(h * S))))
        box.fill((4, 14, 20))
        box.set_alpha(int(170 * a))
        pygame.Surface.blit(screen, box, (int((W / 2 - w / 2) * S), int(60 * S)))
        (img.img if hasattr(img, "img") else img).set_alpha(int(255 * a))
        screen.blit(img, (W / 2 - img.get_width() / 2, 61))
    a = 1.0 if t < 5 else max(0.0, 1 - (t - 5) / 1.5)
    if a <= 0:
        return
    if 1.0 < t < 6.5:
        title = f_title.render("АКВАРІУМ", True, (250, 252, 250))
        (title.img if hasattr(title, "img") else title).set_alpha(int(255 * min(1.0, (t - 1.0) / 0.8) * a))
        screen.blit(title, ((W - title.get_width()) / 2, 24))
    if lcd.DEVICE == "picocalc":
        hints = ("1 світло  2 повітря  T постукати", "стрілки - палець  Enter - корм  Esc")
    else:
        hints = ("K1 світло  K2 повітря", "джойстик палець  OK корм  K3")
    imgs = [f_hint.render(h, True, (226, 236, 232)) for h in hints]
    lh = imgs[0].get_height()
    top = 128 - lh * len(imgs) - 2
    STRIP.set_alpha(int(150 * a))
    pygame.Surface.blit(screen, STRIP, (0, int(top * S)))
    for k, img in enumerate(imgs):
        (img.img if hasattr(img, "img") else img).set_alpha(int(240 * a))
        screen.blit(img, ((W - img.get_width()) / 2, top + 1 + k * lh))


# ---------------------------------------------------------------- the camera (on a monitor with a touch screen)

CAMERA_URL = os.environ.get("AQUARIUM_CAMERA", "")   # e.g. rtsp://10.80.39.161:8888/stream1; a touch shows it
CAMERA_FOR = 180                                     # seconds before it goes back to the tank by itself
CAM_W, CAM_H = 1280, 800


def show_camera():
    """The camera full screen until a touch or a key (or CAMERA_FOR seconds): ffmpeg decodes the stream
    (RTSP over TCP: on WiFi lost UDP packets froze it; 5 s to connect) into raw frames we show."""
    import subprocess
    import threading
    disp = pygame.display.set_mode((CAM_W, CAM_H), pygame.SCALED | (pygame.FULLSCREEN if lcd.DISPLAY_MODE == "kms" else 0))
    pygame.mouse.set_visible(False)
    # RTSP over TCP, 5 s to connect; no long probing (at night the camera gives 1 frame a second: 28 s -> 7 s)
    rtsp = ["-rtsp_transport", "tcp", "-timeout", "5000000", "-analyzeduration", "0", "-probesize", "32"] \
        if CAMERA_URL.startswith("rtsp") else []
    cmd = ["ffmpeg", "-loglevel", "error", *rtsp, "-reorder_queue_size", "4000", "-max_delay", "10000000",
           "-fflags", "nobuffer", "-flags", "low_delay", "-i", CAMERA_URL, "-an",
           "-vf", "scale=%d:%d:force_original_aspect_ratio=decrease,pad=%d:%d:(ow-iw)/2:(oh-ih)/2" % (CAM_W, CAM_H, CAM_W, CAM_H),
           "-pix_fmt", "rgb24", "-f", "rawvideo", "pipe:1"]
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, bufsize=0)
    latest = {"frame": None, "n": 0}
    size = CAM_W * CAM_H * 3

    def reader():
        buf = bytearray()
        while True:
            chunk = proc.stdout.read(size - len(buf))
            if not chunk:
                return
            buf += chunk
            if len(buf) == size:
                latest["frame"], latest["n"] = bytes(buf), latest["n"] + 1
                buf = bytearray()
    threading.Thread(target=reader, daemon=True).start()
    Font = pygame.font.Font.__bases__[0] if S != 1 else pygame.font.Font   # the plain font: this screen is not scaled
    f_msg = Font(FONT_DIR + "DejaVuSans.ttf", 28) if os.path.exists(FONT_DIR + "DejaVuSans.ttf") else Font(None, 32)
    t0 = time.monotonic()
    shown = -1
    pygame.event.clear()
    try:
        while time.monotonic() - t0 < CAMERA_FOR:
            for ev in pygame.event.get():
                if ev.type == pygame.QUIT:
                    return False
                if ev.type in (pygame.KEYDOWN, pygame.MOUSEBUTTONDOWN, pygame.FINGERDOWN) and time.monotonic() - t0 > 0.6:
                    return True
            if latest["n"] != shown and latest["frame"] is not None:
                shown = latest["n"]
                pygame.Surface.blit(disp, pygame.image.frombuffer(latest["frame"], (CAM_W, CAM_H), "RGB"), (0, 0))
                pygame.display.flip()
            elif latest["frame"] is None:
                disp.fill((0, 0, 0))
                text = "камера: з'єднання..." if proc.poll() is None else "камера недоступна"
                img = Font.render(f_msg, text, True, (220, 230, 230))
                pygame.Surface.blit(disp, img, ((CAM_W - img.get_width()) // 2, (CAM_H - img.get_height()) // 2))
                pygame.display.flip()
                if proc.poll() is not None and time.monotonic() - t0 > 4:
                    return True
            clock.tick(30)
        return True
    finally:
        proc.kill()
        proc.wait()
        lcd.reopen_display()
        pygame.event.clear()


# ---------------------------------------------------------------- the clock cut into the castle (on a monitor)

CASTLE_CLOCK = bool(lcd.DISPLAY_MODE) or os.environ.get("AQUARIUM_CASTLE_CLOCK") == "1"
DAYS = ["понеділок", "вівторок", "середа", "четвер", "п'ятниця", "субота", "неділя"]


def plain_font(name, px):
    """A font in native pixels (the app's fonts are scaled by S)."""
    Font = pygame.font.Font.__bases__[0] if S != 1 else pygame.font.Font
    try:
        return Font(FONT_DIR + name, max(1, int(px)))
    except (FileNotFoundError, OSError):
        return Font(None, max(1, int(px)))


def carve(text, px, cx, cy, rad, condense):
    """Text moulded on a round tower's wall: wrapped round the cylinder (narrower to the sides, the line
    curving down in the middle like the tower's bands), the letters lighter than the wall and a little
    raised - their upper left edge catching the lamp, a thin shadow below and to the right; the wall's
    own relief shows through. px - the letters' size, (cx, cy) - the middle of the line, rad - the tower's
    radius (logical). -> (a layer to multiply the wall by, a layer to add, the letters' own faint glow in
    the dark, where they go in native pixels)"""
    f = plain_font("DejaVuSans-Bold.ttf", px * S)
    m = pygame.surfarray.array_alpha(f.render(text, True, (255, 255, 255))).T.astype(np.float32) / 255
    h, w = m.shape
    R = rad * S
    th_max = min(1.3, w * condense / 2 / R)              # how far round the wall the line reaches
    half = R * math.sin(th_max)
    dw = int(2 * half) + 1
    u = (np.arange(dw, dtype=np.float32) - half) / R
    th = np.arcsin(np.clip(u, -1, 1))
    nz = np.cos(th)
    src = np.clip(((th / th_max) * 0.5 + 0.5) * (w - 1), 0, w - 1).astype(int)
    e = rad * VIEW_DOWN * S
    pad = int(e) + 3
    out = np.zeros((h + pad + 2, dw), np.float32)
    for j in range(dw):                                   # each column down by the wall's curve
        y0 = pad + int(round(e * (nz[j] - 1)))
        out[y0:y0 + h, j] = m[:, src[j]]
    d = max(1, int(round(0.3 * S)))
    ul = np.zeros_like(out)
    ul[d:, d:] = out[:-d, :-d]                            # the neighbour up and to the left
    dr = np.zeros_like(out)
    dr[:-d, :-d] = out[d:, d:]                            # ... down and to the right
    lit = np.clip(-0.55 * u + 0.83 * nz, 0, 1)[None, :]  # the tower's light, as in castle_layer
    edge = np.clip(out - ul, 0, 1)                        # the upper left rim of each letter, lit
    shadow = np.clip(dr - out, 0, 1)                      # what they cast down and to the right
    mul = np.clip(1 - shadow * 0.45, 0, 1)[..., None] * np.ones(3) * 255
    add = (out * (0.55 + 0.45 * lit))[..., None] * np.array([96, 88, 66]) \
        + (edge * (0.35 + 0.65 * lit))[..., None] * np.array([70, 66, 56])
    glow = out[..., None] * np.array([150, 170, 130])     # the letters in the dark (like the stones, faintly)
    layers = []
    for arr in (mul, add, glow):
        lay = pygame.Surface((dw, out.shape[0]))
        pygame.surfarray.blit_array(lay, np.clip(arr, 0, 255).swapaxes(0, 1).astype(np.uint8))
        layers.append(lay)
    top = cy * S - (f.get_ascent() - 0.36 * px * S) - pad
    return layers[0], layers[1], layers[2], (int(cx * S - half), int(top))


class CastleClock:
    """The time on the tall tower above the roof, the day under it on the wide base."""

    def __init__(self):
        self.key, self.parts, self.night = None, [], {}

    def draw(self, dst):
        now = time.localtime()
        key = (now.tm_hour, now.tm_min, now.tm_mday)
        if key != self.key:
            self.key = key
            self.night = {}
            self.parts = [carve(time.strftime("%H:%M", now), 8.0, 113.5 + DC, 69.6, 10.5, 0.78),
                          carve("%s, %d" % (DAYS[now.tm_wday], now.tm_mday), 4.4, 112.0 + DC, 83.7, 16.5, 0.85)]
        for mul, add, _, pos in self.parts:
            dst.blit(mul, pos, special_flags=pygame.BLEND_RGB_MULT)
            dst.blit(add, pos, special_flags=pygame.BLEND_RGB_ADD)

    def draw_dark(self, dst, dark):
        """Over the night: the letters still readable, faintly glowing."""
        lv = int(255 * dark * 0.26) // 8 * 8
        if lv <= 0 or not self.parts:
            return
        for i, (_, _, glow, pos) in enumerate(self.parts):
            g = self.night.get((i, lv))
            if g is None:
                g = glow.copy()
                g.fill((lv, lv, lv), special_flags=pygame.BLEND_RGB_MULT)
                self.night[(i, lv)] = g
            dst.blit(g, pos, special_flags=pygame.BLEND_RGB_ADD)


CLOCK = CastleClock() if CASTLE_CLOCK else None


ARROWS = (pygame.K_LEFT, pygame.K_RIGHT, pygame.K_UP, pygame.K_DOWN)


def handle_keys(tank, now):
    t = now - tank.t0
    for ev in pygame.event.get():
        if ev.type == pygame.QUIT:
            return False
        if ev.type == pygame.KEYUP:
            tank.held.discard(ev.key)
            continue
        if ev.type == pygame.MOUSEBUTTONDOWN:                # a touch on the monitor (or a click)
            tank.touch(*lcd.logical_pos(ev.pos), t)
            continue
        if ev.type == pygame.FINGERDOWN:
            tank.touch(ev.x * W, ev.y * H, t)
            continue
        if ev.type != pygame.KEYDOWN:
            continue
        tank.visitor_t = t                                   # someone is at the tank
        if ev.key in (pygame.K_ESCAPE, pygame.K_BACKSPACE, pygame.K_q) or (ev.key == pygame.K_3 and getattr(ev, "hat", False)):
            return False
        if ev.key in ARROWS:                                 # the finger on the glass
            tank.held.add(ev.key)
            tank.finger_t = t
        elif ev.key in (pygame.K_1, pygame.K_l):
            until = tank.lamp(not tank.light_on, now)
            hh = int(until) % 24
            tank.say("світло %s до %02d:%02d" % ("увімкнено" if tank.light_on else "вимкнено", hh, round((until - int(until)) * 60)), t)
        elif ev.key == pygame.K_2:
            tank.air_on = not tank.air_on
            tank.say("повітря увімкнено" if tank.air_on else "повітря вимкнено", t)
            lcd.play("move")
        elif ev.key in (pygame.K_t, pygame.K_4):
            tank.tap(t)
        elif ev.key in (pygame.K_RETURN, pygame.K_SPACE, pygame.K_f):
            tank.feed(t)
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
        if HAT_DIM:                                     # the HAT's panel is much brighter: tone the tank down
            canvas.blit(HAT_DIM, (0, 0))
        pygame.Surface.blit(screen, canvas, (0, 0))
        draw_hud(tank, now)
        lcd.flip()
        if not handle_keys(tank, now):
            return
        if tank.want_camera:
            tank.want_camera = False
            if not show_camera():
                return
            last = time.monotonic()
        clock.tick(FPS)


if __name__ == "__main__":
    try:
        main()
    finally:
        screen.fill((0, 0, 0))
        lcd.flip()
        lcd.quit()
