"""PICO RUSH - a pseudo-3D racer in the OutRun 2 style for the PicoCalc (and the HAT).

The road is Jake Gordon's segment technique (javascript-racer, MIT): the track is a list of short
segments with a curve and a height; each frame the visible ones are projected and painted far to near,
roadside sprites and traffic with them. Stage 1: the coast - the sea and a beach on the left, a city and
palms on the right. Time attack: the clock runs down, checkpoints add time, overtakes add score.

Keys: Up - gas, Down - brake, [ / ] (or Left / Right) - steer, Esc - pause. HAT: joystick, KEY1 gas, KEY2 brake,
KEY3 pause.
"""
import json
import math
import os
import random
import time

import numpy as np
import pygame
import lcd
import racegfx as gfx

screen = lcd.init()
clock = pygame.time.Clock()
W, H = lcd.NATIVE_W, lcd.NATIVE_H
K = W / 320.0
HOR = int(H * 0.40)                   # the horizon line
frame = pygame.Surface((W, H))        # everything is drawn here in native pixels, then shown

RECORDS = os.path.expanduser("~/.config/lcdtoy/racer.json")

# ---------------------------------------------------------------- the world

SEG = 200.0                           # segment length
ROAD = 2000.0                         # half the road's width
CAM_H = 1000.0
DEPTH = 1.0                           # 1 / tan(fov / 2), fov 90 degrees
PLAYER_Z = CAM_H * DEPTH              # the car's distance in front of the camera
DRAW = 90                             # segments drawn ahead
MAX_SPEED = SEG * 60                  # world units / s (shown as 290 km/h)
ACCEL, BRAKE = MAX_SPEED / 4.5, -MAX_SPEED
DECEL = -MAX_SPEED / 22               # coasting off the gas: a slow roll-out (~13 km/h a second)
GRAVITY = MAX_SPEED * 0.22            # a slope pulls: uphill slows, downhill speeds up
OFFROAD_DECEL, OFFROAD_LIMIT = -MAX_SPEED / 2, MAX_SPEED / 4
CENTRIFUGAL = 0.3
REVERSE_MAX, REVERSE_ACCEL = MAX_SPEED / 10, MAX_SPEED / 6   # the reverse gear: up to ~30 km/h
SOLID = ("palm", "lamp", "sign", "boulder", "chevron")
CAR_LEN = 300.0                       # a car's length (world units): the bumper-to-bumper reach
CAR_W = 0.235                         # a car's half width, in road half widths (150 px of a 320 px half road)
HAZE = (190, 215, 240)
KMH = 290


class Seg:
    __slots__ = ("i", "z", "y1", "y2", "curve", "sprites", "cars", "check", "stripe")

    def __init__(self, i, y1, y2, curve):
        self.i, self.z, self.y1, self.y2, self.curve = i, i * SEG, y1, y2, curve
        self.sprites, self.cars, self.check = [], [], False
        self.stripe = (i // 3) % 2


def ease_in(a, b, p):
    return a + (b - a) * p * p


def ease_inout(a, b, p):
    return a + (b - a) * (-math.cos(p * math.pi) / 2 + 0.5)


class Track:
    """A stage: segments with curves and heights, its sprites, checkpoints, how it is painted."""
    key, name = "", ""
    lanes = (-2 / 3, 0.0, 2 / 3)
    n_cars, start_time, bonus = 26, 45.0, 20.0
    kinds = ()
    walls = (-3.0, 3.0)                   # where the car cannot go (road half widths): rails, rocks, water

    def __init__(self, seed=1):
        self.segs = []
        self.rnd = random.Random(seed)
        self.build()
        self.length = len(self.segs) * SEG
        n = len(self.segs)
        for k in (1, 2, 3):
            self.segs[int(n * k / 4)].check = True
        self.decorate()
        for sg in self.segs:
            sg.sprites.sort(key=lambda sp: -abs(sp[2]))

    def last_y(self):
        return self.segs[-1].y2 if self.segs else 0.0

    def add_road(self, enter, hold, leave, curve, height):
        y0 = self.last_y()
        y1 = y0 + height * SEG
        total = enter + hold + leave
        for i in range(total):
            if i < enter:
                c = ease_in(0, curve, i / enter)
            elif i < enter + hold:
                c = curve
            else:
                c = ease_inout(curve, 0, (i - enter - hold) / leave)
            ya = ease_inout(y0, y1, i / total)
            yb = ease_inout(y0, y1, (i + 1) / total)
            self.segs.append(Seg(len(self.segs), ya, yb, c))

    def s_bends(self, k=1.0, h=10):
        for c, hh in ((-2, 0), (3, h), (2, 0), (-3, -h), (-2, 0)):
            self.add_road(25, 25, 25, c * k, hh)

    def find(self, z):
        return self.segs[int(z // SEG) % len(self.segs)]


class Coast(Track):
    """Stage 1, the coast: sweeping curves, S-bends, gentle hills; the sea on the left, a city on the right."""
    key, name = "coast", "УЗБЕРЕЖЖЯ"
    walls = (-2.3, 1.33)                  # the sea beyond the beach, the railing
    kinds = ("palm", "building", "lamp", "sign", "umbrella")

    def build(self):
        add = self.add_road
        add(40, 40, 40, 0, 0)                          # the start straight
        add(50, 60, 50, 2, 10)
        add(30, 30, 30, 0, 0)
        add(40, 80, 40, -3, -10)
        add(40, 40, 40, 0, 20)
        self.s_bends()
        add(50, 100, 50, 4, 0)
        add(30, 40, 30, 0, -20)
        add(40, 60, 40, -2, 10)
        self.s_bends()
        add(60, 120, 60, 3, 0)
        add(30, 30, 30, 0, -10)
        add(50, 80, 50, -4, 20)
        add(40, 60, 40, 0, -20)
        self.s_bends()
        add(50, 100, 50, -3, 0)
        add(40, 50, 40, 2, 10)
        add(50, 60, 50, 0, -10)                        # the finish straight

    def decorate(self):
        """Palms on both sides, buildings and lamps on the right, umbrellas on the beach, signs."""
        rnd = self.rnd
        for i, s in enumerate(self.segs):
            city = (i // 160) % 3 != 2                 # city blocks, then a palm boulevard
            if i % 6 == 0:
                s.sprites.append(("palm", 0, 1.35 + rnd.uniform(0, 0.15)))
            if i % 12 == 3:
                s.sprites.append(("lamp", 0, 1.22))
            if city and i % 9 == 4:
                s.sprites.append(("building", rnd.randrange(6), 2.0 + rnd.uniform(0.1, 0.9)))
            if i % 14 == 7:
                s.sprites.append(("palm", 0, -2.0 - rnd.uniform(0, 1.2)))
            if i % 10 == 2:
                s.sprites.append(("umbrella", rnd.randrange(3), -1.6 - rnd.uniform(0, 1.0)))
            if i % 150 == 75:
                s.sprites.append(("sign", rnd.randrange(3), -1.45))

    def paint(self, f, n, s, x1, y1, k1, x2, y2, k2):
        paint_coast(f, n, s, x1, y1, k1, x2, y2, k2)


class Mountains(Track):
    """Stage 2, a mountain pass: steep climbs and drops, hairpins, a cliff on the left, a guard rail, pines and
    the valley on the right; a two-lane road with a yellow centre line."""
    key, name = "mountains", "ГОРИ"
    walls = (-1.23, 1.18)                 # the rock face, the guard rail
    lanes = (-0.5, 0.5)
    n_cars, start_time, bonus = 16, 50.0, 22.0
    kinds = ("pine", "boulder", "chevron", "sign")

    def build(self):
        add = self.add_road
        add(30, 30, 30, 0, 0)                          # the start
        add(40, 60, 40, 2, 40)                         # a long climb round to the right
        add(30, 30, 30, -3, 20)
        self.hairpins(3)
        add(40, 40, 40, 0, -50)                        # over the crest and down
        add(40, 80, 40, -4, -20)
        add(30, 30, 30, 3, 30)
        self.s_bends(1.6, 25)
        add(50, 60, 50, 5, 40)
        add(30, 30, 30, 0, -60)                        # a big drop
        self.hairpins(2)
        add(40, 60, 40, -3, 30)
        add(30, 30, 30, 4, -20)
        self.s_bends(1.8, 30)
        add(40, 80, 40, -5, -30)
        add(40, 40, 40, 2, 50)
        self.hairpins(2)
        add(40, 50, 40, 0, -70)                        # down to the finish
        add(40, 40, 40, 0, 0)

    def hairpins(self, n):
        for i in range(n):
            c = 6 if i % 2 == 0 else -6
            self.add_road(25, 45, 25, c, 12)

    def decorate(self):
        """Pines down the valley side, boulders at the cliff, chevrons round sharp bends, pass signs."""
        rnd = self.rnd
        for i, s in enumerate(self.segs):
            if i % 4 == 0:
                s.sprites.append(("pine", 0, 1.55 + rnd.uniform(0, 1.6)))
            if i % 7 == 1:
                s.sprites.append(("pine", 0, 2.6 + rnd.uniform(0, 1.8)))
            if i % 23 == 9:
                s.sprites.append(("boulder", rnd.randrange(2), -1.18))
            if abs(s.curve) >= 4.5 and i % 7 == 0:     # chevrons on the outside of a sharp bend
                side = -1.14 if s.curve > 0 else 1.14
                s.sprites.append(("chevron", 0 if s.curve > 0 else 1, side))
            if i % 260 == 130:
                s.sprites.append(("sign", 3 + rnd.randrange(2), 1.3))

    def paint(self, f, n, s, x1, y1, k1, x2, y2, k2):
        paint_mountains(f, n, s, x1, y1, k1, x2, y2, k2)


TRACKS = [Coast, Mountains]


# ---------------------------------------------------------------- traffic

class Car:
    __slots__ = ("z", "x", "speed", "variant", "passed")

    def __init__(self, z, x, speed, variant):
        self.z, self.x, self.speed, self.variant, self.passed = z, x, speed, variant, False


def make_traffic(track, seed=2):
    n = track.n_cars
    rnd = random.Random(seed)
    for s in track.segs:                              # the last game's cars off the road
        s.cars.clear()
    cars = []
    for i in range(n):
        z = (i + 1) / (n + 1) * track.length + rnd.uniform(-400, 400)
        cars.append(Car(z % track.length, rnd.choice(track.lanes), MAX_SPEED * rnd.uniform(0.32, 0.55),
                        rnd.randrange(len(gfx.TRAFFIC))))
    return cars


# ---------------------------------------------------------------- the engine sound

class Engine:
    """Loops at stepped pitches; switching crossfades between two channels."""

    def __init__(self):
        self.ok = lcd.sound_enabled()
        self.cur = -1
        self.chan = None
        if not self.ok:
            return
        rate = 44100
        self.loops = []
        for i in range(18):
            f = 46 + i * 9.0                               # 46 .. 199 Hz fundamental
            n = int(rate / f) * max(2, int(f / 12))
            t = np.arange(n) / rate
            ph = 2 * np.pi * f * t
            y = (0.55 * np.sin(ph) + 0.3 * np.sin(2 * ph + 0.3) + 0.2 * np.sin(3 * ph + 1.1)
                 + 0.12 * np.sign(np.sin(ph * 0.5)) + 0.05 * np.random.uniform(-1, 1, n))
            y *= 0.22 * lcd.VOLUME
            self.loops.append(pygame.mixer.Sound(buffer=(np.clip(y, -1, 1) * 32000).astype(np.int16).tobytes()))
        self.chans = [pygame.mixer.Channel(6), pygame.mixer.Channel(7)]
        self.which = 0

    def set(self, rpm, on=True):
        if not self.ok:
            return
        if not on:
            for c in self.chans:
                c.fadeout(200)
            self.cur = -1
            return
        i = max(0, min(len(self.loops) - 1, int(rpm * (len(self.loops) - 1))))
        if i == self.cur:
            return
        old = self.chans[self.which]
        self.which ^= 1
        self.chans[self.which].play(self.loops[i], loops=-1, fade_ms=40)
        old.fadeout(60)
        self.cur = i

    def stop(self):
        self.set(0, on=False)


def gear_rpm(speed):
    """An automatic gearbox: (gear, rpm 0..1) from the speed; "R" backing up."""
    if speed < -1:
        return "R", 0.25 + 0.75 * (-speed / REVERSE_MAX)
    p = speed / MAX_SPEED
    edges = (0, 0.12, 0.26, 0.42, 0.6, 0.8, 1.01)
    for g in range(6):
        if p < edges[g + 1]:
            lo, hi = edges[g], edges[g + 1]
            return g + 1, 0.25 + 0.75 * (p - lo) / (hi - lo)
    return 6, 1.0


# ---------------------------------------------------------------- drawing the road

def fogs():
    return [min(1.0, (n / DRAW) ** 1.8) for n in range(DRAW + 1)]


FOG = fogs()


def fog_of(world_h, height):
    """The haze for a sprite of world height world_h drawn `height` px tall: that size means a distance."""
    z = DEPTH * W / 2 * world_h / max(1, height)
    return FOG[min(DRAW, int(z / SEG))]


gfx.FOG_OF = fog_of


def pal(c_near, c_far=None):
    """A colour for every distance (the haze mixed in)."""
    out = []
    for n in range(DRAW + 1):
        base = c_near if c_far is None else gfx.lerp(c_near, c_far, min(1.0, n / 30))
        out.append(gfx.lerp(base, HAZE, FOG[n] * 0.85))
    return out


SEA = pal((40, 190, 200), (20, 120, 190))
FOAM = pal((235, 250, 250))
SAND = pal((236, 214, 170))
SAND_HI = pal((250, 236, 200))
PAVE = [pal((186, 182, 176)), pal((176, 172, 166))]
ASPHALT = [pal((112, 118, 126)), pal((104, 110, 118))]
KERB = pal((232, 232, 232))
RAIL = pal((70, 74, 80))
CHECK = pal((40, 200, 255))
GRASS = [pal((86, 136, 64)), pal((78, 126, 58))]
VALLEY = pal((46, 86, 50), (60, 96, 70))
ROCK = [pal((138, 126, 112)), pal((124, 112, 100))]
ROCK_TOP = pal((176, 166, 150))
ROCK_DARK = pal((92, 84, 76))
ASPHALT_M = [pal((92, 96, 104)), pal((86, 90, 98))]
YELLOW = pal((240, 196, 40))
METAL = pal((210, 216, 224))
METAL_D = pal((116, 122, 130))


def render_road(track, cars, pos, player_x, player_y):
    """Project the visible segments, then paint them far to near with their sprites and cars."""
    f = frame
    segs = track.segs
    nseg = len(segs)
    base = track.find(pos)
    percent = (pos % SEG) / SEG
    cam_x = player_x * ROAD
    cam_y = player_y + CAM_H
    x, dx = 0.0, -(base.curve * percent)
    proj = [None] * DRAW
    for n in range(DRAW):
        s = segs[(base.i + n) % nseg]
        cz = pos - (track.length if s.i < base.i else 0)
        z1, z2 = s.z - cz, s.z + SEG - cz
        if z1 <= 1:
            x += dx
            dx += s.curve
            continue
        k1, k2 = DEPTH / z1, DEPTH / z2
        x1 = W / 2 + k1 * (x - cam_x) * W / 2
        x2 = W / 2 + k2 * (x + dx - cam_x) * W / 2
        y1 = HOR - k1 * (s.y1 - cam_y) * H / 2
        y2 = HOR - k2 * (s.y2 - cam_y) * H / 2
        proj[n] = (s, x1, y1, k1 * W / 2, x2, y2, k2 * W / 2)
        x += dx
        dx += s.curve
    fill, poly, line = f.fill, gfx.poly, gfx.line
    for n in range(DRAW - 1, -1, -1):
        p = proj[n]
        if p is None:
            continue
        s, x1, y1, k1, x2, y2, k2 = p
        if y2 >= y1 or y2 > H:
            draw_sprites(s, x1, y1, k1, n, cars, pos)
            continue
        track.paint(f, n, s, x1, y1, k1, x2, y2, k2)
        draw_sprites(s, x1, y1, k1, n, cars, pos)


def paint_coast(f, n, s, x1, y1, k1, x2, y2, k2):
    fill, poly, line = f.fill, gfx.poly, gfx.line
    st = s.stripe
    w1, w2 = ROAD * k1, ROAD * k2
    h = y1 - y2 + 1
    fill(SEA[n], (0, y2, W, h))
    if n % 5 == 0 and n > 4:
        line(f, FOAM[n], (x1 - w1 * 3.2, y1), (x2 - w2 * 3.2, y2), 1)
    sx1, sx2 = x1 - w1 * 2.4, x2 - w2 * 2.4
    poly(f, SAND[n], ((sx1, y1), (x1 - w1 * 1.05, y1), (x2 - w2 * 1.05, y2), (sx2, y2)))
    poly(f, SAND_HI[n], ((sx1, y1), (sx1 + w1 * 0.25, y1), (sx2 + w2 * 0.25, y2), (sx2, y2)))
    rx = min(x1 + w1 * 1.05, x2 + w2 * 1.05)
    if rx < W:
        poly(f, PAVE[(s.i // 2) % 2][n], ((x1 + w1 * 1.05, y1), (W, y1), (W, y2), (x2 + w2 * 1.05, y2)))
    poly(f, ASPHALT[st][n], ((x1 - w1 * 1.05, y1), (x1 + w1 * 1.05, y1), (x2 + w2 * 1.05, y2), (x2 - w2 * 1.05, y2)))
    kc = KERB[n]
    if n < 70:
        for e in (-1.05, 1.05):
            a1, a2 = x1 + w1 * e, x2 + w2 * e
            poly(f, kc, ((a1 - w1 * 0.02, y1), (a1 + w1 * 0.02, y1), (a2 + w2 * 0.02, y2), (a2 - w2 * 0.02, y2)))
        if (s.i // 2) % 3 and n < 55:
            for e in (-1 / 3, 1 / 3):
                a1, a2 = x1 + w1 * e, x2 + w2 * e
                l1, l2 = w1 * 0.013, w2 * 0.013
                poly(f, kc, ((a1 - l1, y1), (a1 + l1, y1), (a2 + l2, y2), (a2 - l2, y2)))
    if s.check:                                    # a checkpoint stripe across the road
        poly(f, CHECK[n], ((x1 - w1, y1), (x1 + w1, y1), (x2 + w2, y2), (x2 - w2, y2)))
    r1, r2 = 380 * k1, 380 * k2
    rx1, rx2 = x1 + w1 * 1.35, x2 + w2 * 1.35
    line(f, RAIL[n], (rx1, y1 - r1), (rx2, y2 - r2), max(1, int(k1 * 40)))
    if s.i % 2 == 0 and n < 60:
        line(f, RAIL[n], (rx1, y1), (rx1, y1 - r1), max(1, int(k1 * 30)))


def paint_mountains(f, n, s, x1, y1, k1, x2, y2, k2):
    """Grass, the valley on the right beyond a guard rail, a rock face on the left, a two-lane road."""
    fill, poly, line = f.fill, gfx.poly, gfx.line
    st = s.stripe
    w1, w2 = ROAD * k1, ROAD * k2
    fill(GRASS[st][n], (0, y2, W, y1 - y2 + 1))
    if x2 + w2 * 1.7 < W:
        poly(f, VALLEY[n], ((x1 + w1 * 1.7, y1), (W, y1), (W, y2), (x2 + w2 * 1.7, y2)))
    poly(f, ASPHALT_M[st][n], ((x1 - w1, y1), (x1 + w1, y1), (x2 + w2, y2), (x2 - w2, y2)))
    if n < 70:
        kc = KERB[n]
        for e in (-0.95, 0.95):                        # white edge lines
            a1, a2 = x1 + w1 * e, x2 + w2 * e
            poly(f, kc, ((a1 - w1 * 0.018, y1), (a1 + w1 * 0.018, y1), (a2 + w2 * 0.018, y2), (a2 - w2 * 0.018, y2)))
        if (s.i // 2) % 3 and n < 60:                  # the yellow centre line, dashed
            l1, l2 = w1 * 0.016, w2 * 0.016
            poly(f, YELLOW[n], ((x1 - l1, y1), (x1 + l1, y1), (x2 + l2, y2), (x2 - l2, y2)))
    if s.check:
        poly(f, CHECK[n], ((x1 - w1, y1), (x1 + w1, y1), (x2 + w2, y2), (x2 - w2, y2)))
    # the rock face on the left: a wall with ledges
    bx1, bx2 = x1 - w1 * 1.25, x2 - w2 * 1.25
    h1, h2 = 2300 * k1, 2300 * k2
    poly(f, ROCK[(s.i // 4) % 2][n], ((bx1, y1), (bx2, y2), (bx2 - w2 * 0.5, y2 - h2), (bx1 - w1 * 0.5, y1 - h1)))
    line(f, ROCK_TOP[n], (bx1 - w1 * 0.5, y1 - h1), (bx2 - w2 * 0.5, y2 - h2), max(1, int(k1 * 70)))
    if s.i % 6 < 2 and n < 50:
        line(f, ROCK_DARK[n], (bx1 - w1 * 0.2, y1 - h1 * 0.4), (bx2 - w2 * 0.2, y2 - h2 * 0.4), max(1, int(k1 * 50)))
    # the guard rail on the right
    rx1, rx2 = x1 + w1 * 1.2, x2 + w2 * 1.2
    r1, r2 = 420 * k1, 420 * k2
    poly(f, METAL[n], ((rx1, y1 - r1), (rx2, y2 - r2), (rx2, y2 - r2 * 0.6), (rx1, y1 - r1 * 0.6)))
    line(f, METAL_D[n], (rx1, y1 - r1 * 0.6), (rx2, y2 - r2 * 0.6), max(1, int(k1 * 30)))
    if s.i % 2 == 0 and n < 60:
        line(f, METAL_D[n], (rx1, y1), (rx1, y1 - r1 * 0.6), max(1, int(k1 * 45)))


def draw_sprites(s, x1, y1, k1, n, cars, pos):
    for kind, variant, off in s.sprites:
        hgt = gfx.KINDS[kind][0] * k1
        if hgt < 5 and kind != "building":
            continue                                  # a few pixels far away: not worth a blit
        img = gfx.sprite(kind, variant, hgt, HAZE)
        if img is None:
            continue
        x = x1 + off * ROAD * k1
        if kind == "building":
            frame.blit(img, (x, y1 - img.get_height()))
        else:
            frame.blit(img, (x - img.get_width() / 2, y1 - img.get_height()))
    for c in s.cars:
        img = gfx.traffic_car(c.variant, gfx.CAR_WORLD_W * k1, HAZE)
        if img is not None:
            frame.blit(img, (x1 + c.x * ROAD * k1 - img.get_width() / 2, y1 - img.get_height()))


# ---------------------------------------------------------------- the game

def load_records():
    try:
        with open(RECORDS, encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return {}


def save_records(r):
    try:
        os.makedirs(os.path.dirname(RECORDS), exist_ok=True)
        with open(RECORDS, "w", encoding="utf-8") as fh:
            json.dump(r, fh, indent=1)
    except OSError:
        pass


def fmt_total(t):
    m, s = divmod(t, 60)
    return "%d'%02d\"%03d" % (m, int(s), int((s - int(s)) * 1000))


STEER = {pygame.K_LEFTBRACKET: pygame.K_LEFT, pygame.K_RIGHTBRACKET: pygame.K_RIGHT}


class Hud:
    def __init__(self):
        o = max(1, int(2 * K))
        yel, cyan, white = ((255, 250, 170), (255, 160, 10)), ((210, 250, 255), (40, 160, 230)), ((255, 255, 255), (190, 200, 220))
        self.lab_total = gfx.emblem("ЗАГ. ЧАС", K)
        self.lab_time = gfx.emblem("ЧАС", K)
        self.lab_score = gfx.emblem("ОЧКИ", K)
        self.d_total = gfx.Digits(gfx.font("DejaVuSans-BoldOblique.ttf", 16 * K), *white, o=o)
        self.d_time = gfx.Digits(gfx.font("DejaVuSans-BoldOblique.ttf", 40 * K), *yel, o=max(1, int(3 * K)))
        self.d_score = gfx.Digits(gfx.font("DejaVuSans-BoldOblique.ttf", 16 * K), *white, o=o)
        self.d_speed = gfx.Digits(gfx.font("DejaVuSans-BoldOblique.ttf", 30 * K), *cyan, o=o)
        self.d_gear = gfx.Digits(gfx.font("DejaVuSans-BoldOblique.ttf", 12 * K), (255, 250, 170), (255, 160, 10), o=1,
                                 chars="0123456789R")
        self.kmh = gfx.fancy("км/г", gfx.font("DejaVuSans-BoldOblique.ttf", 12 * K), *cyan, o=max(1, int(K)))
        self.R = int(36 * K)
        self.face = gfx.gauge_face(self.R, K)
        self.f_msg = gfx.font("DejaVuSans-BoldOblique.ttf", 26 * K)
        self.msgs = {}

    def message(self, text, colour="yellow"):
        key = (text, colour)
        if key not in self.msgs:
            cols = {"yellow": ((255, 250, 170), (255, 160, 10)), "cyan": ((220, 250, 255), (40, 160, 230)),
                    "red": ((255, 200, 200), (230, 30, 40))}[colour]
            self.msgs[key] = gfx.fancy(text, self.f_msg, *cols, o=max(1, int(3 * K)))
        return self.msgs[key]

    def draw(self, f, total, left, score, speed, gear):
        f.blit(self.lab_total, (4 * K, 2 * K))
        self.d_total.draw(f, fmt_total(total), 14 * K, 21 * K)
        f.blit(self.lab_time, (W / 2 - 44 * K, 2 * K))
        self.d_time.draw(f, "%d" % max(0, math.ceil(left)), W / 2 + 6 * K, 16 * K, "center")
        f.blit(self.lab_score, (W - 108 * K, 2 * K))
        self.d_score.draw(f, "%07d" % score, W - 6 * K, 21 * K, "right")
        R = self.R
        cx, cy = int(46 * K), H - int(46 * K)
        f.blit(self.face, (cx - R - 1, cy - R - 1))
        kmh = abs(speed) / MAX_SPEED * KMH
        a = math.radians(225 - min(1.0, kmh / 300) * 270)
        gfx.line(f, (255, 255, 255), (cx, cy), (cx + math.cos(a) * (R - 6 * K), cy - math.sin(a) * (R - 6 * K)), max(1, int(3 * K)))
        gfx.circle(f, (200, 30, 30), (cx, cy), max(2, int(4 * K)))
        self.d_speed.draw(f, "%d" % kmh, 88 * K, H - 42 * K)
        f.blit(self.kmh, (92 * K + self.d_speed.width("%d" % kmh), H - 22 * K))
        self.d_gear.draw(f, str(gear), cx, cy + R * 0.32, "center")


class Game:
    def __init__(self):
        self.tracks = {}
        self.skies = {}
        self.choose(TRACKS[0])
        self.hud = Hud()
        self.engine = Engine()
        self.records = load_records()
        self.cars_img = {}
        for lean in (-1, 0, 1):
            for brake in (False, True):
                self.cars_img[(lean, brake)] = gfx.car_master(int(150 * K), (214, 22, 34), lean=lean, brake=brake)
        self.reset()

    def choose(self, cls):
        """Switch to a stage (built once), its sky, and queue the sprite sizes it needs."""
        if cls.key not in self.tracks:
            self.tracks[cls.key] = cls()
            self.skies[cls.key] = (gfx.make_sky_mountains if cls is Mountains else gfx.make_sky)(W, HOR)
        self.track = self.tracks[cls.key]
        self.sky = self.skies[cls.key]
        self.cars = make_traffic(self.track)
        self.jobs = gfx.prewarm_jobs(HAZE, K, self.track.kinds)
        self.jobs_total = max(1, len(self.jobs))

    def prewarm(self, budget):
        """Make cached sprite sizes for up to `budget` seconds; True when all are made."""
        end = time.monotonic() + budget
        while self.jobs and time.monotonic() < end:
            fn, args = self.jobs.pop(0)
            fn(*args)
        return not self.jobs

    def reset(self):
        self.pos = 0.0
        self.x = 0.0
        self.speed = 0.0
        self.sky_off = 0.0
        self.cars = make_traffic(self.track)
        self.left = self.track.start_time
        self.total = 0.0
        self.score = 0
        self.state = "countdown"
        self.t_state = time.monotonic()
        self.msg = None
        self.msg_t = 0.0
        self.shake = 0.0
        self.passed_check = set()
        self.hit_t = 0.0
        self.top_speed = 0.0
        self.crashes = 0
        self.overtakes = 0
        self.lap_done = False
        self.keys = set()

    def say(self, text, colour="yellow", secs=1.6):
        self.msg, self.msg_t = self.hud.message(text, colour), time.monotonic() + secs

    # -- physics
    def update(self, dt):
        tr = self.track
        racing = self.state == "race"
        up = racing and (pygame.K_UP in self.keys or "gas" in self.keys)
        down = racing and (pygame.K_DOWN in self.keys or "brake" in self.keys)
        left = pygame.K_LEFT in self.keys
        right = pygame.K_RIGHT in self.keys
        pseg = tr.find(self.pos + PLAYER_Z)
        sp = abs(self.speed) / MAX_SPEED
        # steering needs motion, but a little works even crawling (to get round what you hit)
        dx = dt * 2.2 * max(sp, 0.06 if (up or down) else 0.0)
        old_pos = self.pos
        self.pos = (self.pos + dt * self.speed) % tr.length
        if racing:
            self.x += (-dx if left else 0) + (dx if right else 0)
        self.x -= dx * sp * pseg.curve * CENTRIFUGAL * (1 if self.speed >= 0 else 0)
        if up:
            if self.speed < 0:
                self.speed += -BRAKE * dt                  # stop reversing first
            else:
                self.speed += ACCEL * dt * (1 - 0.5 * sp)
        elif down:
            if self.speed > 0:
                self.speed += BRAKE * dt
            else:
                self.speed -= REVERSE_ACCEL * dt           # standing: Down backs up
        elif self.speed > 0:
            self.speed = max(0.0, self.speed + DECEL * dt)
        else:
            self.speed = min(0.0, self.speed - DECEL * dt)
        if self.speed > 0 or not down:                  # the hill: downhill rolls faster, uphill holds back
            slope = (pseg.y2 - pseg.y1) / SEG
            self.speed -= slope * GRAVITY * dt
        if abs(self.x) > 1.05 and self.speed > OFFROAD_LIMIT:   # off the road: the sand / the pavement
            self.speed += OFFROAD_DECEL * dt
        # collisions over the whole way travelled this frame (at speed that is 2-3 segments - checking only
        # the one under the car let it pass through cars and posts)
        oz = old_pos + PLAYER_Z
        moved = (self.pos - old_pos) % tr.length if self.speed > 0 else 0.0
        if self.speed > 0:
            i0 = int(oz // SEG)
            hit = None
            for j in range(int(moved // SEG) + 2):
                sg = tr.segs[(i0 + j) % len(tr.segs)]
                for kind, variant, off in sg.sprites:   # a palm, a lamp post, a sign, a boulder: stop in front
                    if kind in SOLID and abs(self.x - off) < CAR_W + 0.08:
                        hit = sg
                        break
                if hit:
                    break
            now = time.monotonic()
            if hit and now - self.hit_t > 0.6:            # a knock: much slower, pushed back towards the road
                self.hit_t = now
                self.crash(max(MAX_SPEED * 0.12, self.speed * 0.45))
                self.x += 0.18 if self.x < 0 else -0.18
        for c in self.cars:                             # rear-ending a car
            rel = (c.z - oz) % tr.length
            if rel < moved + CAR_LEN and self.speed > c.speed and abs(self.x - c.x) < CAR_W * 1.8:
                if self.speed - c.speed > MAX_SPEED * 0.1:
                    self.crash(c.speed * 0.7)           # a real knock
                else:
                    self.speed = c.speed * 0.9          # just touching: stay behind it
                self.pos = (c.z - PLAYER_Z - CAR_LEN) % tr.length
                break
        lo, hi = tr.walls                               # the railing / the guard rail / the rock / the sea
        if self.x - CAR_W < lo or self.x + CAR_W > hi:
            self.x = lo + CAR_W + 0.03 if self.x - CAR_W < lo else hi - CAR_W - 0.03
            if self.speed > MAX_SPEED * 0.25:
                self.speed = max(MAX_SPEED * 0.25, self.speed - MAX_SPEED * 0.9 * dt)   # scraping along it
                self.shake = max(self.shake, 0.35)
                now = time.monotonic()
                if now - getattr(self, "_scrape_t", 0) > 0.5:
                    self._scrape_t = now
                    lcd.play("wall")
        self.x = max(-3.0, min(3.0, self.x))
        self.speed = max(-REVERSE_MAX, min(MAX_SPEED, self.speed))
        self.top_speed = max(self.top_speed, self.speed)
        self.sky_off = (self.sky_off + pseg.curve * sp * dt * 12) % (W * 2)
        # traffic: move, overtakes
        player_z = self.pos + PLAYER_Z
        for c in self.cars:
            seg = tr.find(c.z)
            if c in seg.cars:
                seg.cars.remove(c)
            c.z = (c.z + dt * c.speed) % tr.length
            tr.find(c.z).cars.append(c)
            ahead = (c.z - player_z) % tr.length
            if racing and not c.passed and ahead > tr.length - 3 * SEG:
                c.passed = True
                self.overtakes += 1
                self.score += 1000
            if ahead < tr.length / 2 and ahead > 8 * SEG:
                c.passed = False
        if racing:
            self.score += int(max(0.0, self.speed) / MAX_SPEED * 80 * dt * 60)
            self.left -= dt
            self.total += dt
            seg = tr.find(self.pos + PLAYER_Z)
            if seg.check and seg.i not in self.passed_check:
                self.passed_check.add(seg.i)
                self.left += self.track.bonus
                self.say("CHECKPOINT +%d" % self.track.bonus, "cyan")
                lcd.play("point")
            # the finish: the position wrapped from the track's end to its start (not a crash's step back)
            if old_pos > tr.length * 0.9 and self.pos < tr.length * 0.1:
                self.finish()
            elif self.left <= 0:
                self.left = 0
                self.state = "over"
                self.t_state = time.monotonic()
                self.say("ЧАС ВИЙШОВ", "red", 4)
                lcd.play("lose")
        self.shake = max(0.0, self.shake - dt * 3)

    def crash(self, to_speed):
        self.speed = to_speed
        self.shake = 1.0
        self.crashes += 1
        lcd.play("hit")

    def finish(self):
        self.state = "finish"
        self.t_state = time.monotonic()
        rec = self.records.setdefault(self.track.key, {})
        best = rec.get("best")
        self.new_record = best is None or self.total < best
        if self.new_record:
            rec["best"] = round(self.total, 3)
        rec["score"] = max(rec.get("score", 0), self.score)
        save_records(self.records)
        self.say("ФІНІШ!", "yellow", 5)
        lcd.play("win")

    # -- drawing
    def draw(self):
        f = frame
        tr = self.track
        pseg = tr.find(self.pos + PLAYER_Z)
        pp = ((self.pos + PLAYER_Z) % SEG) / SEG
        py = pseg.y1 + (pseg.y2 - pseg.y1) * pp
        off = int(self.sky_off)
        f.blit(self.sky, (-off, 0))
        if off > W:
            f.blit(self.sky, (2 * W - off, 0))
        render_road(tr, self.cars, self.pos, self.x, py)
        # the player's car: leans with the steering, brake lights, a little bounce
        lean = (pygame.K_RIGHT in self.keys) - (pygame.K_LEFT in self.keys)
        brake = pygame.K_DOWN in self.keys or "brake" in self.keys
        img = self.cars_img[(lean, brake)]
        bounce = (random.random() - 0.5) * (2 * K if abs(self.x) > 1.05 else 0.8 * K) * (self.speed > 100)
        sx = (random.random() - 0.5) * self.shake * 8 * K
        f.blit(img, (W / 2 - img.get_width() / 2 + sx, H - img.get_height() - 6 * K + bounce))
        g, _ = gear_rpm(self.speed)
        self.hud.draw(f, self.total, self.left, self.score, self.speed, g)
        now = time.monotonic()
        if self.state == "countdown":
            n = 3 - int(now - self.t_state)
            m = self.hud.message(str(n) if n > 0 else "GO!", "yellow")
            f.blit(m, (W / 2 - m.get_width() / 2, H * 0.36))
        elif self.msg and now < self.msg_t:
            f.blit(self.msg, (W / 2 - self.msg.get_width() / 2, H * 0.3))
        if self.state in ("finish", "over") and now - self.t_state > 1.5:
            self.draw_results(f)
        pygame.Surface.blit(screen, f, (0, 0))
        lcd.flip()

    def draw_results(self, f):
        box = pygame.Surface((int(W - 40 * K), int(170 * K)), pygame.SRCALPHA)
        box.fill((10, 20, 50, 200))
        pygame.draw.rect(box, (255, 200, 40), box.get_rect(), max(1, int(2 * K)), border_radius=int(8 * K))
        f.blit(box, (20 * K, 80 * K))
        fm = gfx.font("DejaVuSansCondensed-Bold.ttf", 14 * K)
        rec = self.records.get(self.track.key, {})
        rows = [("Час", fmt_total(self.total) if self.state == "finish" else "-"),
                ("Рекорд", fmt_total(rec["best"]) if rec.get("best") else "-"),
                ("Очки", "%d" % self.score), ("Обгони", "%d" % self.overtakes),
                ("Макс. швидкість", "%d км/г" % (self.top_speed / MAX_SPEED * KMH)), ("Аварії", "%d" % self.crashes)]
        for i, (a, b) in enumerate(rows):
            f.blit(fm.render(a, True, (220, 230, 255)), (34 * K, 92 * K + i * 21 * K))
            t = fm.render(b, True, (255, 220, 80))
            f.blit(t, (W - 34 * K - t.get_width(), 92 * K + i * 21 * K))
        h = gfx.font("DejaVuSansCondensed.ttf", 11 * K).render("Enter - ще раз · Esc - меню", True, (200, 210, 255))
        f.blit(h, (W / 2 - h.get_width() / 2, 232 * K))

    # -- the loop
    def run(self):
        """One game until Esc in the pause or after the results; returns True to quit the app."""
        self.reset()
        last = time.monotonic()
        paused = False
        while True:
            now = time.monotonic()
            dt = min(0.05, now - last)
            last = now
            for ev in pygame.event.get():
                if ev.type == pygame.QUIT:
                    self.engine.stop()
                    return True
                hat = getattr(ev, "hat", False)
                key = ev.key if ev.type in (pygame.KEYDOWN, pygame.KEYUP) else None
                if hat and key == pygame.K_1:
                    key = "gas"
                elif hat and key == pygame.K_2:
                    key = "brake"
                elif key in STEER:                     # [ and ] steer too (handier than the d-pad on the PicoCalc)
                    key = STEER[key]
                if ev.type == pygame.KEYDOWN:
                    if key == pygame.K_ESCAPE or (hat and ev.key == pygame.K_3):
                        if self.state in ("finish", "over"):
                            self.engine.stop()
                            return False
                        paused = not paused
                        if paused:
                            self.engine.stop()
                    elif paused and key in (pygame.K_RETURN, pygame.K_KP_ENTER):
                        paused = False
                    elif paused and key == pygame.K_q:
                        self.engine.stop()
                        return False
                    elif self.state in ("finish", "over") and key in (pygame.K_RETURN, pygame.K_KP_ENTER) \
                            and time.monotonic() - self.t_state > 1.5:
                        self.reset()
                    else:
                        self.keys.add(key)
                elif ev.type == pygame.KEYUP:
                    self.keys.discard(key)
            if paused:
                self.draw_pause()
                clock.tick(10)
                continue
            if self.state == "countdown":
                n = 3 - int(now - self.t_state)
                if n != getattr(self, "_cd", None):
                    self._cd = n
                    lcd.play("select" if n <= 0 else "move")
                if now - self.t_state >= 3:
                    self.state = "race"
            self.update(dt)
            g, rpm = gear_rpm(self.speed)
            self.engine.set(rpm if abs(self.speed) > 50 or self.state == "race" else 0.0,
                            on=self.state in ("race", "countdown"))
            self.draw()
            clock.tick(30)

    def draw_pause(self):
        f = frame
        box = pygame.Surface((int(200 * K), int(90 * K)), pygame.SRCALPHA)
        box.fill((10, 20, 50, 220))
        pygame.draw.rect(box, (255, 200, 40), box.get_rect(), max(1, int(2 * K)), border_radius=int(8 * K))
        f.blit(box, (W / 2 - box.get_width() / 2, H / 2 - box.get_height() / 2))
        m = self.hud.message("ПАУЗА", "yellow")
        f.blit(m, (W / 2 - m.get_width() / 2, H / 2 - 40 * K))
        h = gfx.font("DejaVuSansCondensed.ttf", 11 * K).render("Enter / Esc - далі · q - у меню", True, (220, 230, 255))
        f.blit(h, (W / 2 - h.get_width() / 2, H / 2 + 14 * K))
        pygame.Surface.blit(screen, f, (0, 0))
        lcd.flip()


def title(game):
    """The title: the coast drifting by, the logo, the menu. Returns "start" or "quit"."""
    items = ["СТАРТ: " + cls.name for cls in TRACKS] + ["ВИХІД"]
    sel = [c.key for c in TRACKS].index(game.track.key)
    big = gfx.font("DejaVuSans-BoldOblique.ttf", 54 * K)
    logo1 = gfx.fancy("PICO", big, (255, 250, 200), (255, 90, 150), o=max(1, int(4 * K)))
    logo2 = gfx.fancy("RUSH", big, (120, 230, 255), (255, 255, 255), o=max(1, int(4 * K)))
    fm = gfx.font("DejaVuSans-BoldOblique.ttf", 17 * K)
    fs = gfx.font("DejaVuSansCondensed.ttf", 11 * K)
    pos, x = 0.0, 0.0
    t0 = time.monotonic()
    while True:
        for ev in pygame.event.get():
            if ev.type == pygame.QUIT:
                return "quit"
            if ev.type != pygame.KEYDOWN:
                continue
            hat = getattr(ev, "hat", False)
            if ev.key in (pygame.K_UP, pygame.K_DOWN):
                sel = (sel + (-1 if ev.key == pygame.K_UP else 1)) % len(items)
                lcd.play("click")
                if sel < len(TRACKS) and game.track.key != TRACKS[sel].key:
                    game.choose(TRACKS[sel])           # the title shows that stage
                    pos = 0.0
            elif ev.key in (pygame.K_RETURN, pygame.K_KP_ENTER, pygame.K_SPACE) or (hat and ev.key == pygame.K_1):
                lcd.play("select")
                return "start" if sel < len(TRACKS) else "quit"
            elif ev.key == pygame.K_ESCAPE or (hat and ev.key == pygame.K_3):
                return "quit"
        tr = game.track
        pos = (pos + 2600 / 30) % tr.length                # an easy cruise behind the logo
        seg = tr.find(pos + PLAYER_Z)
        x -= 0.003 * seg.curve * 0.3
        x = max(-0.6, min(0.6, x))
        game.sky_off = (game.sky_off + seg.curve * 0.08) % (W * 2)
        frame.blit(game.sky, (-int(game.sky_off), 0))
        if game.sky_off > W:
            frame.blit(game.sky, (2 * W - int(game.sky_off), 0))
        py = seg.y1
        render_road(tr, game.cars, pos, x, py)
        bob = math.sin((time.monotonic() - t0) * 2) * 3 * K
        frame.blit(logo1, (W / 2 - logo1.get_width() / 2, 24 * K + bob))
        frame.blit(logo2, (W / 2 - logo2.get_width() / 2, 78 * K + bob))
        for i, it in enumerate(items):
            col = ((255, 250, 170), (255, 160, 10)) if i == sel else ((240, 240, 255), (170, 180, 210))
            t = gfx.fancy(("▶ " if i == sel else "") + it, fm, *col, o=max(1, int(2 * K)))
            frame.blit(t, (W / 2 - t.get_width() / 2, 170 * K + i * 25 * K))
        if not game.prewarm(0.022):                       # the sprites get ready while the title runs
            pct = 100 - 100 * len(game.jobs) // max(1, game.jobs_total)
            t = fs.render("підготовка графіки %d%%" % pct, True, (255, 255, 255))
            frame.blit(t, (W / 2 - t.get_width() / 2, 256 * K))
        rec = game.records.get(game.track.key, {})
        if rec.get("best"):
            t = gfx.fancy("РЕКОРД  " + fmt_total(rec["best"]), fs, (255, 255, 255), (200, 210, 230), o=1)
            frame.blit(t, (W / 2 - t.get_width() / 2, 240 * K))
        h = fs.render("↑ газ  ↓ гальмо  [ ] кермо  Esc пауза", True, (255, 255, 255))
        frame.blit(h, (W / 2 - h.get_width() / 2, H - 16 * K))
        pygame.Surface.blit(screen, frame, (0, 0))
        lcd.flip()
        clock.tick(30)


def finish_prewarm(game):
    f = gfx.font("DejaVuSans-BoldOblique.ttf", 16 * K)
    while not game.prewarm(0.08):
        pygame.event.pump()
        frame.fill((14, 20, 40))
        t = gfx.fancy("ЗАВАНТАЖЕННЯ", f, (255, 250, 170), (255, 160, 10), o=max(1, int(2 * K)))
        frame.blit(t, (W / 2 - t.get_width() / 2, H / 2 - 30 * K))
        p = 1 - len(game.jobs) / max(1, game.jobs_total)
        gfx.rect(frame, (60, 70, 100), (W * 0.15, H / 2, W * 0.7, 8 * K), border_radius=int(4 * K))
        gfx.rect(frame, (255, 190, 40), (W * 0.15, H / 2, W * 0.7 * p, 8 * K), border_radius=int(4 * K))
        pygame.Surface.blit(screen, frame, (0, 0))
        lcd.flip()


def main():
    game = Game()
    while True:
        if title(game) == "quit":
            return
        finish_prewarm(game)
        if game.run():
            return


if __name__ == "__main__":
    try:
        main()
    finally:
        screen.fill((0, 0, 0))
        lcd.flip()
        lcd.quit()
