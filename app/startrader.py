"""ЗОРЯНИЙ ТОРГОВЕЦЬ - a space trader in the spirit of the old 8-bit space-trading classics, our own ships
and names, drawn the modern way (dark solid hulls with light trims, glowing lights, lit planets) or the
classic way (white wireframe, a planet of dots); Tab switches.

Stage 1: the flight (roll and pitch, the speed), the cockpit with its dashboard and the scanner, the system's
planet and sun, the station that turns about its slot, traffic coming and going, docking by hand (match the
station's turn, fly in slowly) or by the docking computer - to a waltz, the opening of Strauss's "The Blue
Danube" (public domain, our own synthesized arrangement).

Stage 2: the galaxy - 256 systems, each its own planet, sun and station; the market, fuel, the 3D chart, the
system data, hyperspace with a countdown, the in-system jump drive, a save at every docking. Ships blown
up leave cargo canisters to scoop; our own end - the camera circles the wreck and draws away.

Stage 3-4: pirates (by how lawless the system is) who come in on our tail, shoot and sometimes fire a
missile; bounties, crimes and the police, combat ranks; misjumps into deep space with an alien hive and its
drones; the equipment shop (missiles, the big bay, the ECM, beam and military lasers, the energy unit, the
escape capsule).

Keys: ← → (or [ ]) - roll, ↑ ↓ - pitch (↑ dives, like a stick; i - the other way), Space / = - faster,
/ / - - slower, a / Enter - the laser, m - a missile at the ship in the sights, c - the docking computer,
e - the ECM, g - the chart, h - hyperspace, j - the jump drive, Tab - the look, Esc - the pause menu. HAT: the joystick, KEY1 faster,
KEY2 slower, KEY3 - the menu.
"""
import json
import math
import os
import random
import threading
import time

import numpy as np
import pygame
import stargfx as gfx                 # before lcd.init(): it keeps pygame's own draw and font
import lcd
import starmusic
import stargalaxy as galaxy

screen = lcd.init()
clock = pygame.time.Clock()
W, H, VH = gfx.W, gfx.H, gfx.VH
frame = pygame.Surface((W, H))
OUT = min(lcd.NATIVE_W, lcd.NATIVE_H)
CONF = os.path.expanduser("~/.config/lcdtoy/startrader.json")

F = 240.0                             # the focal length (pixels): a 67 degree view across
CX, CY = W / 2, VH / 2
MAX_SPEED = 1600.0                    # world units a second (the trader is 250 wide, the station 1200)
ACCEL = 900.0
ROLL_MAX, PITCH_MAX = 1.7, 0.95       # rad / s
ROLL_ACC, PITCH_ACC = 5.0, 3.0
PLANET_R = 24000.0
STATION_R = 600.0
STATION_SPIN = 2 * math.pi / 50       # one turn in 50 s
DOCK_SPEED = 0.35 * MAX_SPEED
SAFE_ZONE = 30000.0
SCAN_RANGE = 12000.0
SUN_DIST, SUN_R = 2.5e6, 1.2e5

STYLE_NAMES = {"modern": "сучасний", "wire": "класичний"}
VIEWS = ["Передній огляд", "Задній огляд", "Лівий огляд", "Правий огляд"]
# each view's camera axes (right, up, forward as columns) in the ship's frame
VIEW_ROT = [np.eye(3), np.array([[-1.0, 0, 0], [0, 1, 0], [0, 0, -1]]),
            np.array([[0, 0, -1.0], [0, 1, 0], [1, 0, 0]]), np.array([[0, 0, 1.0], [0, 1, 0], [-1, 0, 0]])]
HP = {"groza": 30, "osa": 3, "sokil": 5, "chumak": 4, "mazha": 6, "shulika": 6, "vulyk": 12, "truten": 1, "rocket": 1,
      "kapsula": 1, "kontejner": 1, "asteroid": 3}                 # laser hits a ship takes
LASER_RANGE = 7000.0
LASER_EVERY = 0.16                    # seconds between pulses
MISSILES = 3
MISSILES_MAX = 4
# the shop: key, name, price, the least tech level that sells it, what it does
EQUIPMENT = [
    ("missile", "Ракета", 30, 1, "самонавідна, до 4 на борту"),
    ("fuel", "Повний бак", 0, 1, "паливо на 7 світлових років"),
    ("bay", "Великий трюм", 400, 2, "+15 т вантажу"),
    ("ecm", "Система РЕБ", 600, 3, "e - знищує ракети поблизу"),
    ("beam", "Променевий лазер", 1000, 4, "частіше й холодніше"),
    ("energy", "Енергоблок", 1500, 8, "банки й щити заряджаються вдвічі швидше"),
    ("capsule", "Рятувальна капсула", 1000, 6, "переживе загибель корабля (вантаж - ні)"),
    ("scoop", "Паливозбірник", 525, 5, "біля сонця набирає паливо"),
    ("military", "Військовий лазер", 6000, 10, "удвічі сильніший і холодніший"),
    ("galhyper", "Галактичний гіперпривід", 5000, 10, "один стрибок у наступну галактику"),
]
# the lasers: seconds between pulses, damage, heat a pulse
LASERS = {"pulse": (LASER_EVERY, 1, 0.065), "beam": (0.1, 1, 0.045), "military": (0.09, 2, 0.035)}
RANKS = [(0, "Нешкідливий"), (5, "Майже нешкідливий"), (12, "Слабкий"), (25, "Середній"), (50, "Вище середнього"),
         (100, "Вправний"), (250, "Небезпечний"), (600, "Смертоносний"), (1500, "ЕЛІТА")]
BOUNTY = {"shulika": (30, 70), "osa": (12, 30), "truten": (5, 10), "vulyk": (200, 400)}
TURN_RATE = {"groza": 2.1, "osa": 1.6, "shulika": 1.25, "sokil": 1.5, "truten": 2.0, "vulyk": 0.6}
CARGO_MAX = 20                        # tonnes (every unit of any good takes a place); +15 with the big bay
JUMP_SPEED = 26000.0                  # the in-system jump drive: world units a second
HYPER_COUNT = 10                      # seconds of the hyperspace countdown
SAVE = os.path.expanduser("~/.config/lcdtoy/startrader-save.json")
MISJUMP = float(os.environ.get("STAR_MISJUMP", "0.06"))   # a hyperspace jump going wrong: out between the stars


def cross(a, b):
    """np.cross is slow for single 3-vectors (it goes through moveaxis)."""
    a0, a1, a2 = float(a[0]), float(a[1]), float(a[2])
    b0, b1, b2 = float(b[0]), float(b[1]), float(b[2])
    return np.array((a1 * b2 - a2 * b1, a2 * b0 - a0 * b2, a0 * b1 - a1 * b0))


def length(v):
    return math.sqrt(float(np.dot(v, v)))


def unit(v):
    n = length(v)
    return v / n if n > 1e-9 else v


def basis(fwd, up_hint):
    """A rotation (columns: right, up, forward) looking along fwd."""
    f = unit(np.asarray(fwd, float))
    r = cross(up_hint, f)
    if length(r) < 1e-6:
        r = cross((1.0, 0, 0), f)
    r = unit(r)
    return np.array((r, cross(f, r), f)).T


def rodrigues(k, a):
    c, s = math.cos(a), math.sin(a)
    x, y, z = k
    return np.array([[c + x * x * (1 - c), x * y * (1 - c) - z * s, x * z * (1 - c) + y * s],
                     [y * x * (1 - c) + z * s, c + y * y * (1 - c), y * z * (1 - c) - x * s],
                     [z * x * (1 - c) - y * s, z * y * (1 - c) + x * s, c + z * z * (1 - c)]])


def turn(R, roll, pitch, yaw):
    """Rotate a frame about its own axes: roll right, pitch the nose up, yaw the nose right (radians)."""
    r, u, f = R[:, 0], R[:, 1], R[:, 2]
    if roll:
        c, s = math.cos(roll), math.sin(roll)
        r, u = r * c - u * s, u * c + r * s
    if pitch:
        c, s = math.cos(pitch), math.sin(pitch)
        f, u = f * c + u * s, u * c - f * s
    if yaw:
        c, s = math.cos(yaw), math.sin(yaw)
        f, r = f * c + r * s, r * c - f * s
    f = unit(f)
    r = unit(r - f * np.dot(r, f))
    return np.array((r, cross(f, r), f)).T


def turn_to(R, d, rate, dt, roll=0.0):
    """Swing the nose towards the direction d at most rate rad/s (an AI ship: it may yaw)."""
    f = R[:, 2]
    axis = cross(f, d)
    s = length(axis)
    c = float(np.dot(f, d))
    if s > 1e-6:
        R = rodrigues(axis / s, min(math.atan2(s, c), rate * dt)) @ R
    if roll:
        R = turn(R, roll * dt, 0, 0)
    return R


def clamp(v, lo, hi):
    return lo if v < lo else hi if v > hi else v


def load_conf():
    try:
        with open(CONF) as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def save_conf(conf):
    try:
        os.makedirs(os.path.dirname(CONF), exist_ok=True)
        with open(CONF, "w") as f:
            json.dump(conf, f)
    except OSError:
        pass


def show():
    """The frame onto the LCD (scaled down on the HAT, centred on a wide monitor)."""
    if OUT != W:
        img = pygame.transform.smoothscale(frame, (OUT, OUT))
    else:
        img = frame
    pygame.Surface.blit(screen, img, ((lcd.NATIVE_W - OUT) // 2, 0))
    lcd.flip()


# ---------------------------------------------------------------- the world

class Ship:
    """An AI ship: flies to its target; roles - "depart" (out of the slot and away), "arrive" (to the slot
    and in), "patrol" (round the station), "drift" (asteroids, cargo)."""

    def __init__(self, kind, pos, R, speed, role):
        self.kind = kind
        self.me = gfx.mesh(kind)
        self.pos = np.array(pos, float)
        self.R = R
        self.speed = speed
        self.role = role
        self.age = 0.0
        self.spin = (0.0, 0.0, 0.0)
        self.phase = 0
        self.wp = None
        self.gone = False
        self.colour = gfx.TYPES[kind][4]
        self.hp = HP.get(kind, 3)
        self.max_hp = self.hp
        self.pod = None                       # an escape capsule: "pirate" or "civil" - who sits in it
        self.target = None
        self.hostile = False                  # attacks the player
        self.mode = "attack"
        self.break_t = 0.0
        self.break_dir = None
        self.fire_t = 1.5
        self.bounty = 0
        self.mission = None
        self.missile = False                  # a pirate's one missile
        self.by_player = False                # the player's laser or missile hit it last


class Blast:
    """A ship blown apart: its faces fly off spinning and cool down, small shards with them, a fireball
    (modern) or a cloud of dots (classic) in the middle."""
    LIFE = 4.0

    def __init__(self, ship, rnd, life=None, spread=1.0):
        me = ship.me
        self.life = life or self.LIFE
        self.pos = ship.pos.copy()
        self.vel = ship.R[:, 2] * ship.speed * 0.4
        self.size = me.radius
        self.age = 0.0
        V = me.pts[:me.nv] @ ship.R.T + ship.pos
        N = me.normals @ ship.R.T
        self.frags = []
        for i, f in enumerate(me.faces):
            P = V[f]
            c = P.mean(axis=0)
            v = self.vel + (N[i] * rnd.uniform(60, 260) + np.array([rnd.uniform(-60, 60) for _ in range(3)])) * spread
            x, y, z = unit(np.array([rnd.gauss(0, 1) for _ in range(3)]))
            K = np.array([[0, -z, y], [z, 0, -x], [-y, x, 0]])           # R(a) = I + sin a K + (1 - cos a) K^2
            self.frags.append((c, P - c, v, K, K @ K, rnd.uniform(1.5, 6.0), me.base[i]))
        self.dots = np.array([unit(np.array([rnd.gauss(0, 1) for _ in range(3)])) * rnd.uniform(0.3, 1.0)
                              for _ in range(70)]) * self.size * 2.2
        # shards: tiny triangles turning in the screen's plane (cheap), flying out faster than the faces
        self.shards = []
        sv = []
        for _ in range(26):
            sv.append(self.vel + unit(np.array([rnd.gauss(0, 1) for _ in range(3)])) * rnd.uniform(150, 420) * spread)
            shape = [(math.cos(a) * rnd.uniform(0.5, 1), math.sin(a) * rnd.uniform(0.5, 1))
                     for a in (0, 2.1 + rnd.uniform(-0.4, 0.4), 4.2 + rnd.uniform(-0.4, 0.4))]
            self.shards.append((shape, rnd.uniform(-9, 9), self.size * rnd.uniform(0.05, 0.12),
                                me.base[rnd.randrange(len(me.base))]))
        self.shard_v = np.array(sv)


class Loader(threading.Thread):
    """What takes seconds on the Zero, done behind the title's animation: the sounds (from the disk cache
    after the first start) and the planet's lit masters - numpy only, the mixer sounds made in the main
    thread by Game.poll_loader()."""

    def __init__(self, game):
        super().__init__(daemon=True)
        self.game = game
        self.bufs = None
        self.done = False

    def run(self):
        try:
            if lcd.sound_enabled():
                self.bufs = starmusic.buffers()
            p = self.game.world.planet
            while p is not None and not p.prewarm():
                pass
        except Exception:                              # a loader that fails leaves the old make-on-demand way
            pass
        self.done = True


class World:
    """One star system: its planet at the origin (size and look from the galaxy), the sun, the station in
    orbit with its slot facing away from the planet, the traffic."""

    def __init__(self, system=None, seed=7, deep=False):
        self.system = system
        self.deep = deep                  # a misjump: no planet, no station, no sun - the aliens' hunting ground
        if system is not None:
            seed = system.seed
        self.rnd = random.Random(seed)
        r = random.Random(seed + 1)

        def rand_dir():
            return unit(np.array([r.gauss(0, 1) for _ in range(3)]))
        home = system is None or system.name == galaxy.START
        self.planet_r = PLANET_R if home else system.radius_km * 4.6
        self.sun_dir = unit(np.array((0.9, 0.55, -0.35))) if home else rand_dir()
        self.sun_pos = self.sun_dir * SUN_DIST
        # the station on the sunny side, mostly: its slot is lit as we come in
        self.st_dir = unit(np.array((0.35, 0.25, -1.0))) if home else unit(self.sun_dir * 0.8 + rand_dir())
        self.arrive_dir = unit(self.st_dir + rand_dir() * 0.35)
        self.st_pos = self.st_dir * (self.planet_r * 2.17)
        self.st_base = basis(-self.st_dir, np.array((0.0, 1.0, 0.0)))   # the model's +z to the planet
        self.slot_n = self.st_dir.copy()                                # the slot looks away from it
        self.st_angle = 0.0
        self.st_R = self.st_base
        self.station = gfx.mesh("station")
        self.planet = None if deep else gfx.Planet("earth", 11) if home else gfx.Planet(system.kind, seed % 997)
        self.stars = gfx.starfield(3 if home else seed % 991)
        self.ships = []
        self.blasts = []
        self.events = []                  # ("boom", ship) - for the game's sounds and messages
        self.spawn_t = 2.0
        self.pirate_t = 8.0
        if deep:
            self.spawn_t = self.pirate_t = 1e9
            self.deep_pos = self.arrive_dir * 5e7
            p = self.deep_pos + unit(np.array([r.gauss(0, 1) for _ in range(3)])) * 4000
            v = Ship("vulyk", p, basis(self.deep_pos - p, np.array((0, 1.0, 0))), 500.0, "alien")
            v.hostile = True
            v.bounty = r.randint(*BOUNTY["vulyk"])
            v.drone_t = 3.0
            self.ships.append(v)
            return
        for k in range(4):                                              # asteroids out in the dark
            d = unit(np.array([self.rnd.uniform(-1, 1) for _ in range(3)]))
            p = self.st_pos + self.slot_n * 9000 + d * self.rnd.uniform(5000, 14000)
            a = Ship("asteroid", p, basis(d, np.array((0, 1.0, 0))), 0.0, "drift")
            a.spin = tuple(self.rnd.uniform(-0.3, 0.3) for _ in range(3))
            self.ships.append(a)
        for k in range(2):
            self.ships.append(self.new_police(k))
        first = self.new_departing(6.0)
        first.pos = self.slot_mouth(2600)
        self.ships.append(first)

    def call_police(self, n=2):
        """The station sends its patrol after an outlaw, and more out of the slot."""
        for s in self.ships:
            if s.kind == "sokil":
                s.hostile = True
        for k in range(n):
            sh = self.new_departing()
            sh.kind, sh.me, sh.colour = "sokil", gfx.mesh("sokil"), gfx.TYPES["sokil"][4]
            sh.hp = HP["sokil"]
            sh.hostile = True
            sh.pos = self.slot_mouth(400 + k * 500)
            self.ships.append(sh)

    def update(self, dt):
        self.st_angle = (self.st_angle + STATION_SPIN * dt) % (2 * math.pi)
        c, s = math.cos(self.st_angle), math.sin(self.st_angle)
        self.st_R = self.st_base @ np.array([[c, -s, 0], [s, c, 0], [0, 0, 1.0]])

    # -- traffic

    def slot_mouth(self, out=STATION_R + 160):
        return self.st_pos + self.slot_n * out

    def new_departing(self, age=0.0):
        kind = self.rnd.choice(("chumak", "chumak", "mazha", "osa"))
        R = np.array((self.st_R[:, 0], cross(self.slot_n, self.st_R[:, 0]), self.slot_n)).T
        sh = Ship(kind, self.slot_mouth(), R, 300.0, "depart")
        d = unit(self.slot_n + np.array([self.rnd.uniform(-0.8, 0.8) for _ in range(3)]))
        sh.wp = self.st_pos + d * 60000
        sh.age = age
        return sh

    def new_arriving(self, player_pos):
        kind = self.rnd.choice(("chumak", "mazha", "mazha", "osa"))
        for _ in range(10):
            d = unit(self.slot_n * 0.8 + np.array([self.rnd.uniform(-1, 1) for _ in range(3)]))
            p = self.st_pos + d * self.rnd.uniform(16000, 24000)
            if length(p - player_pos) > 8000 and length(p) > self.planet_r * 1.3:
                break
        sh = Ship(kind, p, basis(self.slot_mouth(3000) - p, np.array((0, 1.0, 0))), 1100.0, "arrive")
        sh.wp = self.slot_mouth(3000)
        return sh

    def new_police(self, k):
        a = self.rnd.uniform(0, 2 * math.pi)
        sh = Ship("sokil", self.st_pos, self.st_R.copy(), 700.0, "patrol")
        sh.phase = a
        sh.pos = self.patrol_point(a + k * math.pi)
        sh.R = basis(self.patrol_point(a + k * math.pi + 0.3) - sh.pos, np.array((0, 1.0, 0)))
        sh.phase = a + k * math.pi
        return sh

    def patrol_point(self, a):
        u, v = self.st_base[:, 0], self.st_base[:, 1]
        return self.st_pos + self.slot_n * 2500 + (u * math.cos(a) + v * math.sin(a)) * 3800

    def danger(self):
        """0 (a corporate state) .. 1 (an anarchy): how often pirates come."""
        return 0.25 if self.system is None else (7 - self.system.gov) / 7.0

    def pirates(self, pl):
        """A pack turns up some way off - more and more often in lawless systems."""
        r = self.rnd
        n = 1 + (r.random() < self.danger()) + (r.random() < self.danger() * 0.5)
        side = unit(np.array([r.gauss(0, 1) for _ in range(3)]))
        centre = pl.pos + side * r.uniform(8000, 11000)
        for k in range(n):
            kind = "shulika" if r.random() < 0.6 else "osa"
            p = centre + unit(np.array([r.gauss(0, 1) for _ in range(3)])) * 600
            s = Ship(kind, p, basis(pl.pos - p, np.array((0, 1.0, 0))), 1000.0, "pirate")
            s.hostile = True
            s.bounty = r.randint(*BOUNTY[kind])
            s.fire_t = r.uniform(1.0, 3.0)
            s.missile = r.random() < 0.45
            self.ships.append(s)
        self.events.append(("pirates", n))

    def run_away(self, s, dt, pl, top):
        """Flee: nose away from the player (a little off his line), all the speed it has; far enough - gone."""
        d = s.pos - pl.pos
        dist = length(d)
        if s.break_dir is None:
            s.break_dir = unit(np.array([self.rnd.gauss(0, 1) for _ in range(3)])) * 0.3
        s.R = turn_to(s.R, unit(unit(d) + s.break_dir), TURN_RATE.get(s.kind, 1.0) * 0.9, dt, 0.6)
        s.speed = min(top, s.speed + 500 * dt)
        if dist > 14000:
            s.gone = True
            self.events.append(("escaped", s))

    def dogfight(self, s, dt, pl):
        """Come in on the player's tail (aiming ahead of him), shoot when lined up, break off when too close,
        come round again; badly hit - run for it."""
        d = pl.pos - s.pos
        dist = length(d)
        rate = TURN_RATE.get(s.kind, 1.2)
        if s.mode == "flee":
            self.run_away(s, dt, pl, 1450.0)
            return
        if s.hp <= s.max_hp * (0.15 if s.kind == "groza" else 0.35) and s.kind not in ("truten", "vulyk", "sokil"):
            s.mode = "flee"
            s.break_dir = None
            self.events.append(("flee", s))
            return
        if s.mode == "break":
            s.break_t -= dt
            s.R = turn_to(s.R, s.break_dir, rate, dt, 1.2)
            s.speed = min(1400.0, s.speed + 400 * dt)
            if s.break_t <= 0 or dist > 6000:
                s.mode = "attack"
            return
        lead = pl.pos + pl.R[:, 2] * pl.speed * min(1.5, dist / 2200.0)
        want = unit(lead - s.pos)
        s.R = turn_to(s.R, want, rate, dt)
        top = 1500.0 if s.kind == "groza" else 1300.0
        s.speed += clamp((top if dist > 2500 else top * 0.65) - s.speed, -500 * dt, 400 * dt)
        head_on = float(np.dot(s.R[:, 2], pl.R[:, 2])) < -0.6           # coming at each other
        if dist < 700 or (head_on and dist < 1400):
            s.mode = "break"
            s.break_t = self.rnd.uniform(1.8, 3.2)
            side = cross(want, np.array([self.rnd.gauss(0, 1) for _ in range(3)]))
            s.break_dir = unit(unit(side) - want * 0.4)
            return
        s.fire_t -= dt
        if s.kind in ("shulika", "groza") and s.missile and 2500 < dist < 7000 and self.rnd.random() < 0.15 * dt:
            s.missile = False                                          # one missile a pirate, sometimes
            m = Ship("rocket", s.pos + s.R[:, 2] * 120, s.R.copy(), s.speed + 400, "emissile")
            self.ships.append(m)
            self.events.append(("incoming", m))
        if s.fire_t <= 0 and dist < 5500 and float(np.dot(s.R[:, 2], d)) > dist * 0.996:
            s.fire_t = self.rnd.uniform(0.5, 1.1)
            hit = self.rnd.random() < 0.8 * (1 - dist / 6500.0)
            self.events.append(("shot", s, hit))

    def update_ships(self, dt, player_pos, pl=None):
        if pl is not None:
            self.pirate_t -= dt
            if self.pirate_t <= 0:
                self.pirate_t = self.rnd.uniform(35, 70)
                far = length(player_pos - self.st_pos) > SAFE_ZONE
                packs = sum(1 for s in self.ships if s.role == "pirate")
                if far and packs == 0 and self.rnd.random() < 0.15 + 0.7 * self.danger():
                    self.pirates(pl)
        self.spawn_t -= dt
        traffic = sum(1 for s in self.ships if s.role in ("depart", "arrive"))
        if self.spawn_t <= 0:
            self.spawn_t = self.rnd.uniform(10, 22)
            if traffic < 4:
                if self.rnd.random() < 0.5:
                    if length(player_pos - self.slot_mouth(1500)) < 4000:   # not into our face
                        self.spawn_t = 3.0
                    else:
                        self.ships.append(self.new_departing())
                else:
                    self.ships.append(self.new_arriving(player_pos))
        for s in self.ships:
            s.age += dt
            if s.hostile and pl is not None and not pl.dead:
                if s.role == "pirate" and length(s.pos - self.st_pos) < SAFE_ZONE * 0.7:
                    s.hostile = False                                  # pirates keep out of the police's zone
                    s.role = "depart"
                    s.wp = s.pos + unit(s.pos - self.st_pos) * 60000
                    s.age = 5
                else:
                    self.dogfight(s, dt, pl)
                if s.kind == "vulyk":                                  # the hive sends out its drones
                    s.drone_t -= dt
                    if s.drone_t <= 0 and sum(1 for x in self.ships if x.kind == "truten") < 4:
                        s.drone_t = self.rnd.uniform(4, 7)
                        d = unit(np.array([self.rnd.gauss(0, 1) for _ in range(3)]))
                        t = Ship("truten", s.pos + d * 140, basis(d, np.array((0, 1.0, 0))), 900.0, "alien")
                        t.hostile = True
                        t.bounty = self.rnd.randint(*BOUNTY["truten"])
                        t.fire_t = self.rnd.uniform(1, 2.5)
                        self.ships.append(t)
            elif s.role in ("drift", "cargo"):
                if s.role == "cargo":                                  # canisters tumble and drift away
                    if s.age > 150 or length(s.pos - player_pos) > 40000:
                        s.gone = True
                s.R = turn(s.R, s.spin[0] * dt, s.spin[1] * dt, s.spin[2] * dt)
            elif s.role == "depart":
                if s.age > 4:
                    s.R = turn_to(s.R, unit(s.wp - s.pos), 0.5, dt, 0.3)
                    s.speed = min(1300.0, s.speed + 200 * dt)
                if length(s.pos - player_pos) > 45000:
                    s.gone = True
            elif s.role == "arrive":
                if s.phase == 0:
                    s.R = turn_to(s.R, unit(s.wp - s.pos), 0.6, dt)
                    if length(s.wp - s.pos) < 500:
                        s.phase = 1
                else:
                    s.R = turn_to(s.R, unit(self.st_pos - s.pos), 0.6, dt)
                    rel = player_pos - self.st_pos
                    ps = float(np.dot(rel, self.slot_n))
                    ss = float(np.dot(s.pos - self.st_pos, self.slot_n))
                    if STATION_R * 0.8 < ps < ss + 300 and length(rel - self.slot_n * ps) < 900:
                        s.speed = max(0.0, s.speed - 600 * dt)                 # we are docking: wait
                    else:
                        s.speed = max(300.0, min(600.0, s.speed + 200 * dt) if s.speed < 300 else s.speed - 400 * dt)
                    q = self.st_R.T @ (s.pos - self.st_pos)
                    if q[2] > -STATION_R:                              # in through the slot
                        s.gone = True
            elif s.role == "flee" and pl is not None:                  # a trader we shot at
                self.run_away(s, dt, pl, 900.0 if s.kind == "mazha" else 1250.0)
            elif s.role == "missile":
                tg = s.target
                if tg is None or tg.gone or s.age > 14:
                    self.destroy(s)                                    # lost its target: self-destructs
                    continue
                s.R = turn_to(s.R, unit(tg.pos - s.pos), 2.4, dt)
                s.speed = min(3000.0, s.speed + 1800 * dt)
                if length(tg.pos - s.pos) < tg.me.radius * 0.8 + 60:
                    tg.by_player = tg.by_player or s.by_player
                    self.destroy(tg)
                    self.destroy(s)
                    continue
            elif s.role == "emissile" and pl is not None:              # a pirate's missile, after us
                if s.age > 16:
                    self.destroy(s)
                    continue
                s.R = turn_to(s.R, unit(pl.pos - s.pos), 1.9, dt)
                s.speed = min(2700.0, s.speed + 1500 * dt)
                if length(pl.pos - s.pos) < 130:
                    self.events.append(("mhit", s))
                    self.destroy(s)
                    continue
            elif s.role == "patrol":
                s.phase += dt * 700 / 3800
                s.R = turn_to(s.R, unit(self.patrol_point(s.phase + 0.35) - s.pos), 0.8, dt)
            if s.role not in ("drift", "missile", "cargo", "flee") and not s.hostile:   # keep clear of the player
                d = player_pos - s.pos
                dist = length(d)
                if dist < 1000 and np.dot(d, s.R[:, 2]) > 0:
                    s.R = turn_to(s.R, unit(-d + s.R[:, 2] * dist * 0.5), 1.4, dt)
            if s.role == "cargo":
                s.pos = s.pos + s.drift * dt
            else:
                s.pos = s.pos + s.R[:, 2] * s.speed * dt
        self.ships = [s for s in self.ships if not s.gone]
        self.update_blasts(dt)

    def destroy(self, s):
        if s.gone:
            return
        s.gone = True
        self.ships = [x for x in self.ships if not x.gone]
        self.blasts.append(Blast(s, self.rnd))
        self.events.append(("boom", s))
        if s.kind in ("chumak", "mazha", "osa", "shulika", "sokil", "groza") and self.rnd.random() < 0.45:
            d = unit(np.array([self.rnd.gauss(0, 1) for _ in range(3)]))      # the pilot ejects
            c = Ship("kapsula", s.pos + d * s.me.radius * 0.6, basis(d, np.array((0, 1.0, 0))), 0.0, "cargo")
            c.spin = (0.0, 0.0, self.rnd.uniform(-2, 2))
            c.drift = d * 260 + s.R[:, 2] * s.speed * 0.3
            c.pod = "pirate" if (s.hostile and s.kind != "sokil") or s.bounty else "civil"
            self.ships.append(c)
            self.events.append(("pod", c))
        n = {"mazha": (1, 3), "chumak": (0, 2), "osa": (0, 1), "shulika": (0, 2), "asteroid": (0, 1)}.get(s.kind, (0, 0))
        for _ in range(self.rnd.randint(*n)):                          # what it carried, in canisters
            d = unit(np.array([self.rnd.gauss(0, 1) for _ in range(3)]))
            c = Ship("kontejner", s.pos + d * s.me.radius * 0.5, basis(d, np.array((0, 1.0, 0))),
                     self.rnd.uniform(20, 70), "cargo")
            c.spin = tuple(self.rnd.uniform(-1.2, 1.2) for _ in range(3))
            c.drift = d * c.speed + s.R[:, 2] * s.speed * 0.3
            goods = galaxy.GOODS
            c.item = 12 if s.kind == "asteroid" else \
                self.rnd.choices(range(len(goods)), [g[4] for g in goods])[0]
            self.ships.append(c)

    def update_blasts(self, dt):
        for b in self.blasts:
            b.age += dt
        self.blasts = [b for b in self.blasts if b.age < b.life]

    # -- geometry

    def in_station(self, p, margin=0.0):
        q = self.st_R.T @ (p - self.st_pos)
        r = STATION_R + margin
        a = np.abs(q)
        return a.max() < r and a.sum() < 2 * r, q


# ---------------------------------------------------------------- the player's ship and the flight

class Game:
    def __init__(self):
        self.conf = load_conf()
        self.style = self.conf.get("style", "modern")
        self.invert = bool(self.conf.get("invert", False))
        self.dash = {s: gfx.Dashboard(s == "modern") for s in ("modern", "wire")}
        self.fonts = {
            "label": gfx.font("DejaVuSans-Bold.ttf", 10),
            "msg": gfx.font("DejaVuSans-Bold.ttf", 12),
            "small": gfx.font("DejaVuSansCondensed.ttf", 10),
            "mono": gfx.font("DejaVuSansMono-Bold.ttf", 9),
        }
        self.galnum = 0
        self.gal, self.start = galaxy.generate(0)
        self.new_game()
        self.music = starmusic.Music()
        self.sfx = starmusic.Sfx()
        self.engine = starmusic.Engine(self.sfx)
        self.loader = Loader(self)
        self.loader.start()
        self.loaded = False
        self.dust = gfx.stardust_init()
        self.keys = set()
        self.reset_ship()

    def reset_ship(self):
        w = self.world
        self.pos = w.slot_mouth(STATION_R + 300)
        self.R = np.array((w.st_R[:, 0], cross(w.slot_n, w.st_R[:, 0]), w.slot_n)).T
        self.speed = 0.3 * MAX_SPEED
        self.roll = self.pitch = self.yaw = 0.0
        self.fs = self.as_ = 1.0
        self.energy = 4.0
        self.autodock = False
        self.ap_phase = 0
        self.msg, self.msg_t = "", 0.0
        self.t = 0.0
        self.dead = False
        self.hit_t = -9.0
        self.slow = 0.0
        self.view = 0
        self.laser_temp = 0.0
        self.overheat = False
        self.fire_t = 0.0
        self.beam_t = -1.0
        self.beam_end = None
        self.beam_hit = False
        self.lock = None
        self.hyper_t = None
        self.jump_t = 0.0
        self.dock_music = False
        self.enemy_beams = []
        self.prisoners = {}
        self.flash_t = -1.0
        self.flash_front = True
        self.police_called = False

    def poll_loader(self):
        """True once the loader is through (its sounds handed to the mixer)."""
        if self.loaded:
            return True
        if self.loader.done:
            if self.loader.bufs:
                self.sfx.load(self.loader.bufs)
                self.music.load(self.loader.bufs)
            self.loaded = True
        return self.loaded

    # -- the commander

    def set_galaxy(self, n):
        if n != self.galnum:
            self.galnum = n
            self.gal, self.start = galaxy.generate(n)

    def new_game(self):
        self.set_galaxy(0)
        self.here = self.start
        self.target = None
        self.credits = 100.0
        self.cargo = [0] * len(galaxy.GOODS)
        self.fuel = galaxy.JUMP_MAX
        self.visits = {}
        self.market = None
        self.kills = 0
        self.legal = 0
        self.rank_name = RANKS[0][1]
        self.missions = {}                             # "groza", "docs": {"state": ..., "sys": index}
        self.notices = []                              # (title, text) to show at the station
        self.missiles = MISSILES
        self.equip = set()
        self.laser = "pulse"
        self.world = World(self.gal[self.here])

    def system(self):
        return self.gal[self.here]

    def held(self):
        return sum(self.cargo)

    def cargo_max(self):
        return CARGO_MAX + (15 if "bay" in self.equip else 0)

    def save(self):
        data = {"galaxy": self.galnum, "here": self.here, "target": self.target, "credits": round(self.credits, 1), "cargo": self.cargo,
                "kills": self.kills, "legal": self.legal, "missions": self.missions, "missiles": self.missiles, "equip": sorted(self.equip),
                "laser": self.laser,
                "fuel": round(self.fuel, 2), "visits": {str(k): v for k, v in self.visits.items()}}
        try:
            os.makedirs(os.path.dirname(SAVE), exist_ok=True)
            with open(SAVE + ".tmp", "w") as f:
                json.dump(data, f)
            os.replace(SAVE + ".tmp", SAVE)
        except OSError:
            pass

    @staticmethod
    def saved():
        try:
            with open(SAVE) as f:
                return json.load(f)
        except (OSError, ValueError):
            return None

    def load(self):
        d = self.saved()
        if not d:
            self.new_game()
            return
        self.set_galaxy(int(d.get("galaxy", 0)) % galaxy.GALAXIES)
        self.here = int(d.get("here", self.start)) % len(self.gal)
        self.target = d.get("target")
        self.credits = float(d.get("credits", 100.0))
        cargo = list(d.get("cargo", []))
        self.cargo = (cargo + [0] * len(galaxy.GOODS))[:len(galaxy.GOODS)]
        self.fuel = float(d.get("fuel", galaxy.JUMP_MAX))
        self.visits = {int(k): v for k, v in d.get("visits", {}).items()}
        self.kills = int(d.get("kills", 0))
        self.legal = int(d.get("legal", 0))
        self.missions = dict(d.get("missions", {}))
        self.notices = []
        self.missiles = int(d.get("missiles", MISSILES))
        self.equip = set(d.get("equip", []))
        self.laser = d.get("laser", "pulse") if d.get("laser") in LASERS else "pulse"
        self.rank_name = self.rank()
        self.world = World(self.gal[self.here])

    def dock(self):
        """At the station: the police look in the hold (strict states), missions move on, a fresh market for
        this visit, the game saved (the old way: only when docked)."""
        self.visits[self.here] = self.visits.get(self.here, 0) + 1
        self.market = [list(x) for x in galaxy.market(self.system(), self.visits[self.here])]
        self.inspect()
        self.hand_over()
        self.mission_step()
        self.save()

    def hand_over(self):
        """The capsules we picked up: pirates to the police (60 Cr each), the rescued home (25 Cr each)."""
        pr = getattr(self, "prisoners", {})
        p, c = pr.get("pirate", 0), pr.get("civil", 0)
        if not p and not c:
            return
        pay = p * 60 + c * 25
        self.credits += pay
        parts = []
        if p:
            parts.append("пілотів-піратів передано поліції: %d" % p)
        if c:
            parts.append("врятованих пілотів відправлено додому: %d" % c)
        self.notices.append(("КАПСУЛИ", "%s. Винагорода - %d Кр." % ("; ".join(parts).capitalize(), pay)))
        self.prisoners = {}

    def inspect(self):
        """A strict state's customs: illegal goods taken, a fine of 25 Cr a tonne, a mark on the record."""
        if self.system().gov < 5 or random.random() > 0.8:
            return
        bad = [(i, n) for i, n in enumerate(self.cargo) if n and not galaxy.GOODS[i][6]]
        if not bad:
            return
        tons = sum(n for _, n in bad)
        fine = min(self.credits, tons * 25.0)
        self.credits -= fine
        for i, _ in bad:
            self.cargo[i] = 0
        self.legal = min(255, self.legal + 10)
        goods = ", ".join("%s %d т" % (galaxy.GOODS[i][0], n) for i, n in bad)
        self.notices.append(("МИТНИЙ ОГЛЯД", "Поліція станції «%s» оглянула трюм. Конфісковано: %s. Штраф %.0f Кр. "
                             "Відтепер ви на обліку: %s." % (self.system().name, goods, fine, self.legal_name())))

    def pick_system(self, lo, hi):
        """A system lo..hi light years away (reachable, not this one) for a mission."""
        here = self.system()
        far = [s for s in self.gal if lo <= here.dist(s) <= hi]
        return random.choice(far).idx if far else random.choice([s for s in self.gal if s is not here]).idx

    def mission_step(self):
        """The two missions: offered once the commander has some fights behind him, paid at the next station."""
        g = self.missions.setdefault("groza", {"state": "none"})
        d = self.missions.setdefault("docs", {"state": "none"})
        if g["state"] == "none" and self.kills >= 8:
            g.update(state="active", sys=self.pick_system(6, 20))
            self.notices.append(("ВИКРАДЕНО ПРОТОТИП", "Увага, командире! З військової верфі викрадено прототип "
                                 "винищувача «Гроза» - швидкий, важко броньований, з новим лазером. Розвідка бачила "
                                 "його в системі %s. Знайдіть і знищіть його. Нагорода - 5000 Кр. Систему позначено "
                                 "на галактичній карті." % self.gal[g["sys"]].name))
        elif g["state"] == "killed":
            g["state"] = "done"
            self.credits += 5000
            self.notices.append(("ПОДЯКА ФЛОТУ", "«Гроза» знищена. Флот вдячний вам, командире: на ваш рахунок "
                                 "переказано 5000 Кр."))
        if d["state"] == "none" and g["state"] == "done" and self.kills >= 30:
            d.update(state="active", sys=self.pick_system(14, 26))
            self.notices.append(("ТАЄМНІ ДОКУМЕНТИ", "Командире, розвідка добула плани вулика чужинців. Доставте "
                                 "документи на станцію системи %s. Чужинці знають про них і полюватимуть на вас у "
                                 "гіперпросторі - стрибки зриватимуться частіше. Нагорода - 10000 Кр і військовий "
                                 "лазер." % self.gal[d["sys"]].name))
        elif d["state"] == "active" and self.here == d.get("sys"):
            d["state"] = "done"
            self.credits += 10000
            self.laser = "military"
            self.notices.append(("ДОКУМЕНТИ ДОСТАВЛЕНО", "Документи в руках розвідки. 10000 Кр на вашому рахунку, "
                                 "у вашому кораблі - військовий лазер. Чужинцям доведеться шукати вас ще довше."))

    def mission_target(self):
        """The system a mission sends us to, if any."""
        for key in ("groza", "docs"):
            m = self.missions.get(key, {})
            if m.get("state") == "active":
                return m.get("sys")
        return None

    def arrive(self):
        """Out of hyperspace: far out, the planet ahead (the station near it, beyond the jump drive's reach)."""
        w = self.world
        if w.deep:
            self.pos = w.deep_pos.copy()
            self.R = basis(w.ships[0].pos - self.pos, np.array((0.0, 1.0, 0.0)))
        else:
            self.pos = w.arrive_dir * w.planet_r * 6.2
            self.R = basis(-self.pos, np.array((0.0, 1.0, 0.0)))
        self.speed = 0.5 * MAX_SPEED
        self.roll = self.pitch = self.yaw = 0.0
        self.autodock = False
        self.hyper_t = None
        self.jump_t = 0.0
        self.lock = None
        g = self.missions.get("groza", {})
        if not w.deep and g.get("state") == "active" and g.get("sys") == self.here:
            d = unit(self.R[:, 2] * 0.7 + np.array([random.gauss(0, 0.5) for _ in range(3)]))
            p = self.pos + d * 7000
            sh = Ship("groza", p, basis(self.pos - p, np.array((0, 1.0, 0))), 1200.0, "pirate")
            sh.hostile = True
            sh.mission = "groza"
            sh.missile = True
            w.ships.append(sh)
        self.beam_end = None
        self.enemy_beams = []
        self.police_called = False
        self.legal = max(0, self.legal - 16)           # a new system: the old record fades

    def sun_alt(self):
        """Height above the sun's surface (deep space: none)."""
        w = self.world
        return 1e12 if w.deep else length(self.pos - w.sun_pos) - SUN_R

    def heat(self):
        """The cabin temperature from the sun: 0 far off, 1 at its surface."""
        return clamp(1 - self.sun_alt() / (0.6 * SUN_R), 0.0, 1.0)

    def jump_speed(self):
        """The jump drive opens up in empty space: a third of the clearance to the nearest big thing a second
        (never past it in one frame), at least JUMP_SPEED."""
        w = self.world
        if w.deep:
            return JUMP_SPEED
        clear = min(length(self.pos) - w.planet_r * 1.5, length(self.pos - w.st_pos) - 24000,
                    self.sun_alt() - 0.3 * SUN_R)
        return clamp(clear / 3.0, JUMP_SPEED, JUMP_SPEED * 12)      # capped: flying away it would run off

    def mass_locked(self):
        """The jump drive will not start near anything big."""
        w = self.world
        if length(self.pos - w.st_pos) < 24000 or length(self.pos) < w.planet_r * 1.5 or self.sun_alt() < 0.3 * SUN_R:
            return True
        return any(s.role not in ("drift", "missile") and length(s.pos - self.pos) < 9000 for s in w.ships)

    @property
    def VR(self):
        """The camera: the ship's frame turned to the view we look through."""
        return self.R @ VIEW_ROT[self.view]

    def set_view(self, v):
        if v != self.view:
            self.view = v % 4
            lcd.play("move")

    def say(self, text, secs=3.0):
        self.msg, self.msg_t = text, self.t + secs

    def set_style(self, style):
        self.style = style
        self.conf["style"] = style
        save_conf(self.conf)

    def toggle_style(self):
        self.set_style("wire" if self.style == "modern" else "modern")
        lcd.play("click")

    # -- input to rates

    def controls(self, dt):
        k = self.keys
        roll_t = ((pygame.K_RIGHT in k) - (pygame.K_LEFT in k)) * ROLL_MAX
        pitch_t = ((pygame.K_DOWN in k) - (pygame.K_UP in k)) * PITCH_MAX
        if self.invert:
            pitch_t = -pitch_t
        if roll_t or pitch_t:
            if self.autodock:
                self.autodock = False
                self.say("Комп'ютер стикування вимкнено")
        if self.autodock:
            return self.autopilot(dt)
        self.roll += clamp(roll_t - self.roll, -ROLL_ACC * dt, ROLL_ACC * dt)
        self.pitch += clamp(pitch_t - self.pitch, -PITCH_ACC * dt, PITCH_ACC * dt)
        self.yaw = 0.0
        if "fast" in k:
            self.speed = min(MAX_SPEED, self.speed + ACCEL * dt)
        if "slow" in k:
            self.speed = max(0.0, self.speed - ACCEL * dt)

    def autopilot(self, dt):
        """Out in front of the slot first (round the station if we are behind it), then in along its axis,
        rolled to the slot and turning with it."""
        w = self.world
        rel = self.pos - w.st_pos
        s = float(np.dot(rel, w.slot_n))
        lat = rel - w.slot_n * s
        latd = length(lat)
        if self.ap_phase == 0:
            target = w.slot_mouth(3200)
            if s < STATION_R * 2.2 and latd < STATION_R * 3:          # behind or beside it: go round
                side = lat / latd if latd > 1 else w.st_base[:, 0]
                target = w.st_pos + side * STATION_R * 4 + w.slot_n * max(s + 1500, 0)
            want = min(MAX_SPEED, length(target - self.pos) / 2.5 + 200)
            if s > 1500 and latd < 220:
                self.ap_phase = 1
            elif length(w.slot_mouth(3200) - self.pos) < 350:
                self.ap_phase = 1
        else:
            target = w.st_pos + w.slot_n * max(0.0, s - 900)
            want = DOCK_SPEED * 0.75
            if latd > 700:
                self.ap_phase = 0
        tc = self.R.T @ (target - self.pos)
        yaw_t = clamp(2.2 * math.atan2(tc[0], tc[2]), -PITCH_MAX, PITCH_MAX)
        pitch_t = clamp(2.2 * math.atan2(tc[1], tc[2]), -PITCH_MAX, PITCH_MAX)
        roll_t = 0.0
        if self.ap_phase == 1 or s < 6000:
            u = w.st_R[:, 0]
            up_ = u - self.R[:, 2] * np.dot(u, self.R[:, 2])
            e = math.atan2(np.dot(up_, self.R[:, 1]), np.dot(up_, self.R[:, 0]))
            if e > math.pi / 2:
                e -= math.pi
            elif e < -math.pi / 2:
                e += math.pi
            roll_t = clamp(-3.0 * e - STATION_SPIN * np.sign(np.dot(self.R[:, 2], -w.slot_n)), -ROLL_MAX, ROLL_MAX)
        self.roll += clamp(roll_t - self.roll, -ROLL_ACC * dt, ROLL_ACC * dt)
        self.pitch += clamp(pitch_t - self.pitch, -PITCH_ACC * dt, PITCH_ACC * dt)
        self.yaw += clamp(yaw_t - self.yaw, -PITCH_ACC * dt, PITCH_ACC * dt)
        self.speed += clamp(want - self.speed, -ACCEL * dt, ACCEL * dt)

    # -- one step

    def update(self, dt):
        """Returns None, "docked" or "dead"."""
        self.t += dt
        w = self.world
        w.update(dt)
        self.controls(dt)
        self.R = turn(self.R, self.roll * dt, self.pitch * dt, self.yaw * dt)
        old = self.pos
        self.pos = self.pos + self.R[:, 2] * self.speed * dt
        if self.jump_t > 0:
            self.jump_t -= dt
            if self.mass_locked():
                self.jump_t = 0.0
                self.say("Масова блокада", 1.5)
            else:
                self.pos = self.pos + self.R[:, 2] * self.jump_speed() * dt
        if self.hyper_t is not None and self.t >= self.hyper_t:
            self.hyper_t = None
            return "hyper"
        w.update_ships(dt, self.pos, self)
        self.weapons(dt)
        if self.dead:
            return "dead"
        # recharge: the banks slowly, the shields from the banks
        boost = 2.0 if "energy" in self.equip else 1.0
        self.energy = min(4.0, self.energy + 0.03 * boost * dt)
        for sh in ("fs", "as_"):
            v = getattr(self, sh)
            if v < 1 and self.energy > 0.2:
                d = min(1 - v, 0.04 * boost * dt)
                setattr(self, sh, v + d)
                self.energy -= d * 0.5
        # the slot, the station's hull
        inside, q = w.in_station(self.pos, 40)
        q_old = w.st_R.T @ (old - w.st_pos)
        sx, sy = w.station.slot_size
        mouth = abs(q[0]) < sx * 1.25 and abs(q[1]) < sy * 2.2      # in line with the slot
        if q_old[2] < -STATION_R and q[2] >= -STATION_R - 1:
            if mouth:
                f = w.st_R.T @ self.R[:, 2]
                r = w.st_R.T @ self.R[:, 0]
                if f[2] > math.cos(math.radians(30)) and abs(r[0]) > math.cos(math.radians(24)) \
                        and self.speed <= DOCK_SPEED:
                    return "docked"
                why = "Заскоро!" if self.speed > DOCK_SPEED else "Не в оберт щілини!" \
                    if abs(r[0]) <= math.cos(math.radians(24)) else "Криво в щілину!"
                self.pos = old - self.R[:, 2] * 40
                self.speed = 0.0
                return self.hit(0.55, True, why, "crash_heavy")
        if inside and not (mouth and q[2] < -STATION_R):
            self.pos = old + unit(old - w.st_pos) * 40
            self.speed = 0.0
            return self.hit(0.25 + 0.6 * self.speed / MAX_SPEED, np.dot(self.R[:, 2], w.st_pos - old) > 0,
                            "Удар об станцію!", "crash_heavy")
        # ships
        for s in w.ships:
            if s.role == "missile":
                continue
            if s.role == "cargo":
                d = s.pos - self.pos
                if np.dot(d, d) < 150 ** 2:
                    self.scoop(s, np.dot(d, self.R[:, 2]) > 0)
                continue
            d = s.pos - self.pos
            reach = s.me.radius * 0.75 + 80
            if np.dot(d, d) < reach * reach:
                front = np.dot(d, self.R[:, 2]) > 0
                s.pos = s.pos + unit(d) * reach * 0.5
                self.pos = self.pos - unit(d) * reach * 0.3
                if s.role == "drift":
                    s.speed = max(s.speed, 60.0)
                    s.R = basis(d, s.R[:, 1])
                return self.hit(0.2 + 0.4 * self.speed / MAX_SPEED, front, "Зіткнення!")
        # the sun: hot near it, fuel for the scoops, death at its surface
        ht = self.heat()
        if ht > 0:
            if self.sun_alt() < 0:
                self.dead = True
                return "dead"
            if "scoop" in self.equip and ht > 0.35 and self.speed > 200 and self.fuel < galaxy.JUMP_MAX:
                self.fuel = min(galaxy.JUMP_MAX, self.fuel + 0.2 * dt)
                if self.msg_t < self.t:
                    self.say("Паливозбірник: %.1f св. р." % self.fuel, 0.6)
            if ht > 0.8:
                self.energy -= (ht - 0.8) * 1.2 * dt
                if self.msg_t < self.t:
                    self.say("Перегрів кабіни!", 0.8)
                    lcd.play("error")
                if self.energy <= 0:
                    self.dead = True
                    return "dead"
        # the planet
        alt = length(self.pos) - w.planet_r
        if alt < 60:
            self.dead = True
            return "dead"
        if alt < 2500 and int(self.t * 2) % 4 == 0 and self.msg_t < self.t:
            self.say("Мала висота!", 1.0)
        return None

    # -- weapons

    def in_sights(self, cone=0.94, reach=SCAN_RANGE):
        """The ship nearest the crosshair within the cone (a missile's lock)."""
        best, bc = None, cone
        for s in self.world.ships:
            if s.role in ("missile", "cargo"):
                continue
            d = s.pos - self.pos
            L = length(d)
            if L < 1 or L > reach:
                continue
            c = float(np.dot(d, self.VR[:, 2])) / L
            if c > bc:
                best, bc = s, c
        return best

    def weapons(self, dt):
        w = self.world
        self.laser_temp = max(0.0, self.laser_temp - 0.22 * dt)
        if self.overheat and self.laser_temp < 0.5:
            self.overheat = False
        self.fire_t -= dt
        if "fire" in self.keys and self.fire_t <= 0:
            if self.overheat:
                if self.msg_t < self.t:
                    self.say("Лазер перегрівся!", 1.0)
            elif self.energy > 0.3:
                self.shoot()
        lock = self.in_sights() if self.missiles else None
        if lock is not None and lock is not self.lock:
            self.sfx.play("lock")
        self.lock = lock
        for ev in w.events:                            # what happened out there since the last step
            kind, ship = ev[0], ev[1]
            if kind == "boom":
                self.sfx.play("boom" if ship.kind not in ("rocket", "kontejner") else "zap")
                if ship.kind not in ("rocket", "kontejner"):
                    self.say("Знищено: %s" % gfx.TYPES[ship.kind][0], 2)
                if ship.mission == "groza" and ship.by_player:
                    self.missions["groza"]["state"] = "killed"
                    self.say("«Гроза» знищена! Нагорода - на станції", 4)
                if ship.by_player and ship.kind not in ("rocket", "kontejner", "asteroid"):
                    self.kills += 1
                    if ship.bounty:
                        self.credits += ship.bounty
                        self.say("Знищено: %s · нагорода %d Кр" % (gfx.TYPES[ship.kind][0], ship.bounty), 3)
                    elif not ship.hostile:
                        self.crime(40 if ship.kind == "sokil" else 15)
                    if self.rank_name != self.rank():
                        self.rank_name = self.rank()
                        self.say("Новий ранг: %s!" % self.rank_name, 4)
                        self.sfx.play("lock")
            elif kind == "shot":
                self.enemy_fire(ship, ev[2])
            elif kind == "flee":
                self.say("%s тікає!" % gfx.TYPES[ship.kind][0], 2)
            elif kind == "escaped":
                if ship.hostile:
                    self.say("%s утік" % gfx.TYPES[ship.kind][0], 2)
            elif kind == "pod":
                if self.msg_t < self.t + 1:
                    self.say("Рятувальна капсула!", 1.5)
            elif kind == "incoming":
                self.say("УВАГА: ракета! " + ("e - РЕБ" if "ecm" in self.equip else "збийте її!"), 3)
                lcd.play("error")
            elif kind == "mhit":
                d = ship.pos - self.pos
                front = float(np.dot(d, self.R[:, 2])) > 0
                sh = "fs" if front else "as_"
                v = getattr(self, sh) - 1.3
                setattr(self, sh, max(0.0, v))
                if v < 0:
                    self.energy += v * 1.5
                self.flash_t, self.flash_front = self.t + 0.3, front
                self.sfx.play("explosion")
                self.say("Влучила ракета!", 2)
                if self.energy <= 0:
                    self.dead = True
            elif kind == "pirates":
                self.say("УВАГА: пірати! (%d)" % ship, 3)
                lcd.play("error")
        w.events.clear()

    def rank(self):
        name = RANKS[0][1]
        for k, n in RANKS:
            if self.kills >= k:
                name = n
        return name

    def legal_name(self):
        return "Чистий" if self.legal == 0 else "Підозрюваний" if self.legal < 50 else "Злочинець"

    def crime(self, n):
        """Shooting the innocent: the record darkens; near the station (or once wanted) the police come."""
        was = self.legal
        near = length(self.pos - self.world.st_pos) < SAFE_ZONE
        self.legal = min(255, self.legal + (n * 2 if near else n))
        if (near or self.legal >= 50) and not self.police_called:
            self.police_called = True
            self.world.call_police(2 if self.legal < 50 else 3)
            self.say("Поліція: ви порушник! Зупиніться!", 3)
        elif was == 0:
            self.say("Ваш статус: %s" % self.legal_name(), 2)

    def enemy_fire(self, s, hit):
        """A shot at us: its beam for a moment; a hit takes a shield (front or aft, by where it came from),
        through it the energy banks."""
        self.enemy_beams.append((s, self.t + 0.09))
        self.sfx.play("elaser")
        if not hit:
            return
        d = s.pos - self.pos
        front = float(np.dot(d, self.R[:, 2])) > 0
        dmg = {"osa": 0.1, "truten": 0.08, "vulyk": 0.25, "groza": 0.22}.get(s.kind, 0.16)
        sh = "fs" if front else "as_"
        v = getattr(self, sh) - dmg
        setattr(self, sh, max(0.0, v))
        if v < 0:
            self.energy += v * 1.5
        self.flash_t = self.t + 0.12
        self.flash_front = front
        self.sfx.play("shield")
        self.autodock = False
        if self.energy <= 0:
            self.dead = True

    def shoot(self):
        """One pulse: along the nose, the nearest ship it passes through takes a hit (the station stops it)."""
        every, dmg, heat = LASERS[self.laser]
        self.fire_t = every
        self.laser_temp += heat
        if self.laser_temp >= 1.0:
            self.overheat = True
            self.say("Лазер перегрівся!", 1.5)
        self.energy -= 0.012
        self.sfx.play("laser")
        RT = self.VR.T
        best, bz = None, LASER_RANGE
        for s in self.world.ships:
            if s.role == "missile":
                continue
            c = RT @ (s.pos - self.pos)
            r = s.me.radius * 0.75
            if 0 < c[2] < bz and c[0] * c[0] + c[1] * c[1] < r * r:
                best, bz = s, float(c[2])
        c = RT @ (self.world.st_pos - self.pos)
        if 0 < c[2] < bz + STATION_R and c[0] * c[0] + c[1] * c[1] < (STATION_R * 0.9) ** 2:
            best, bz = None, float(c[2]) - STATION_R * 0.8
            if self.msg_t < self.t:
                self.say("Не стріляйте по станції!", 1.5)
        self.beam_t = self.t + 0.08
        self.beam_end = self.pos + self.VR[:, 2] * bz
        self.beam_hit = best is not None or bz < LASER_RANGE
        if best is not None:
            best.hp -= dmg
            best.by_player = True
            self.sfx.play("zap")
            if best.pod == "civil":
                self.crime(10)
            elif not best.hostile and best.kind not in ("asteroid", "kontejner", "kapsula"):
                self.crime(3)
                if best.kind == "sokil" or best.role in ("depart", "arrive"):
                    best.hostile = best.kind in ("sokil", "osa", "shulika")   # fighters shoot back
                if not best.hostile and best.role in ("depart", "arrive", "patrol"):
                    best.role = "flee"                                       # the rest run
                    best.break_dir = None
            if best.hp <= 0:
                self.world.destroy(best)

    def scoop(self, c, front):
        """Fly into a canister slowly, nose first: it goes into the hold (if there is room)."""
        w = self.world
        if c.pod:
            if not front or self.speed > 0.45 * MAX_SPEED:
                return                                     # a capsule just bounces off: slower, nose first
            c.gone = True
            w.ships = [x for x in w.ships if not x.gone]
            self.prisoners[c.pod] = self.prisoners.get(c.pod, 0) + 1
            self.sfx.play("scoop")
            self.say("Капсула на борту: %s" % ("пілот-пірат" if c.pod == "pirate" else "врятований пілот"), 2.5)
            return
        name, unit_ = galaxy.GOODS[c.item][:2]
        if not front or self.speed > 0.45 * MAX_SPEED:
            c.hp = 0
            w.destroy(c)
            self.say("Контейнер розбито - заскоро", 2)
            return
        if self.held() >= self.cargo_max():
            if self.msg_t < self.t:
                self.say("Трюм повний", 1.5)
                lcd.play("error")
            return
        c.gone = True
        w.ships = [x for x in w.ships if not x.gone]
        self.cargo[c.item] += 1
        self.sfx.play("scoop")
        self.say("Підібрано: %s, 1 %s" % (name, unit_), 2)

    def ecm(self):
        """The electronic countermeasures: every missile within reach blows up."""
        if "ecm" not in self.equip:
            self.say("Немає системи РЕБ", 1.5)
            lcd.play("error")
            return
        if self.energy < 0.4:
            return
        self.energy -= 0.25
        self.sfx.play("ecm")
        self.flash_t, self.flash_front = self.t + 0.15, True
        n = 0
        for s in list(self.world.ships):
            if s.role in ("missile", "emissile") and length(s.pos - self.pos) < 12000:
                self.world.destroy(s)
                n += 1
        self.say("РЕБ: знищено ракет - %d" % n if n else "РЕБ: ракет поблизу немає", 2)

    def fire_missile(self):
        if not self.missiles:
            self.say("Ракет немає", 1.5)
            lcd.play("error")
            return
        tg = self.in_sights()
        if tg is None:
            self.say("Немає цілі в прицілі", 1.5)
            lcd.play("error")
            return
        m = Ship("rocket", self.pos + self.VR[:, 2] * 140 - self.VR[:, 1] * 30, self.VR.copy(),
                 self.speed + 500, "missile")
        m.target = tg
        m.by_player = True
        self.world.ships.append(m)
        self.missiles -= 1
        self.sfx.play("missile")
        self.say("Ракета пішла: %s" % gfx.TYPES[tg.kind][0], 2)

    def hit(self, dmg, front, why, sound="crash"):
        """Damage to a shield, through it to the banks; out of energy - the end."""
        if self.t - self.hit_t < 0.7:                       # still scraping: one knock, not one a frame
            return None
        self.hit_t = self.t
        self.sfx.play(sound)
        self.speed *= 0.2
        self.roll *= -0.5
        self.pitch *= -0.5
        self.autodock = False
        sh = "fs" if front else "as_"
        v = getattr(self, sh) - dmg
        setattr(self, sh, max(0.0, v))
        if v < 0:
            self.energy += v * 2
        self.say(why, 2.5)
        if self.energy <= 0:
            self.dead = True
            return "dead"
        return None

    # -- drawing

    def obj(self, pos, R):
        VT = self.VR.T
        return VT @ R, VT @ (pos - self.pos)

    def hidden_by_planet(self, p):
        d = p - self.pos
        L = length(d)
        if L < 1:
            return False
        u = d / L
        tca = -np.dot(self.pos, u)                 # the planet is at the origin
        if tca < 0 or tca > L:
            return False
        d2 = np.dot(self.pos, self.pos) - tca * tca
        return d2 < self.world.planet_r ** 2

    def draw_view(self, surf, dt, overlay=True):
        st = self.style
        w = self.world
        spin = abs(self.roll) / ROLL_MAX + abs(self.pitch) / PITCH_MAX + abs(self.yaw) / PITCH_MAX
        self.slow = 0.8 * self.slow + 0.2 * (dt > 0.045)
        rough = spin > 0.6 or self.slow > 0.5
        if w.planet is not None:
            w.planet.gap = 0.3 if rough else 0.12
        surf.fill((0, 0, 0) if st == "wire" else (3, 3, 10), (0, 0, W, VH))
        view = surf.subsurface((0, 0, W, VH))
        VR = self.VR
        gfx.draw_stars(view, w.stars, VR, F, CX, CY, st)
        RT = VR.T
        # the sun, unless the planet is in the way
        sc = RT @ (w.sun_pos - self.pos)
        sd = length(sc) if not w.deep else 0.0
        # in front only (near 90 degrees off the nose x / z blows up: a glow ten thousand pixels wide once
        # froze the game for seconds), its true size from the distance, and only when it is on the screen
        if not w.deep and sc[2] > sd * 0.3 and not self.hidden_by_planet(w.sun_pos):
            sx, sy, sr = CX + sc[0] * F / sc[2], CY - sc[1] * F / sc[2], SUN_R * F / sd
            if -5 * sr - 40 < sx < W + 5 * sr + 40 and -5 * sr - 40 < sy < VH + 5 * sr + 40:
                gfx.draw_sun(view, sx, sy, sr, st, self.t)
        # the planet
        pc = RT @ (-self.pos)
        dist = length(pc)
        if pc[2] > 0 and not w.deep:
            pr = w.planet_r
            r = pr * F / math.sqrt(max(dist * dist - pr * pr, 1.0)) if dist > pr else 1e5
            Ls = RT @ w.sun_dir                    # from the planet towards the sun
            w.planet.draw(view, CX + pc[0] * F / pc[2], CY - pc[1] * F / pc[2], min(r, 4000), Ls, st)
        # the station and the ships, far to near
        objs = []
        for s in w.ships:
            objs.append((s.me, s.pos, s.R))
        if not w.deep:
            objs.append((w.station, w.st_pos, w.st_R))
        drawn = []
        for me, p, R in objs:
            d = p - self.pos
            dd = float(np.dot(d, d))
            if dd > 60000.0 ** 2:
                continue
            drawn.append((dd, me, p, R))
        drawn.sort(key=lambda t: -t[0])
        for _, me, p, R in drawn:
            if self.hidden_by_planet(p):
                continue
            M, t = self.obj(p, R)
            Lc = RT @ unit(p - w.sun_pos)
            gfx.draw_mesh(view, me, M, t, F, CX, CY, Lc, st, detail=not rough)
        for b in w.blasts:
            self.draw_blast(view, b)
        gfx.stardust(view, self.dust, dt, self.speed + (JUMP_SPEED if self.jump_t > 0 else 0),
                     self.roll, self.pitch, self.yaw, F, CX, CY, st, VIEW_ROT[self.view])
        if not overlay:
            return
        self.draw_beams(view)
        self.draw_enemy_fire(view)
        self.draw_lock(view)
        col = gfx.WIRE if st == "wire" else (220, 225, 235)
        for dx, dy in ((-1, 0), (1, 0), (0, -1), (0, 1)):
            gfx.line(view, col, (CX + dx * 6, CY + dy * 6), (CX + dx * 16, CY + dy * 16))
        y = 4
        if not gfx.HAT:                                 # no room for it on the HAT
            img = self.fonts["label"].render(VIEWS[self.view], True, col)
            view.blit(img, (W / 2 - img.get_width() / 2, y))
            y += img.get_height()
        hint = self.draw_dock_hint(view) if self.view == 0 else 30
        if gfx.HAT and self.view:
            img = self.fonts["small"].render(VIEWS[self.view].split()[0].upper(), True, col)
            view.blit(img, (4, 4))
        if self.msg and self.t < self.msg_t:
            img = gfx.fit(self.fonts["msg"].render(self.msg, True, (255, 210, 90) if st != "wire" else gfx.WIRE))
            view.blit(img, (W / 2 - img.get_width() / 2, VH - img.get_height() - (hint + 4)))
        for on, text, c in ((self.autodock, "КОМП'ЮТЕР СТИКУВАННЯ", (120, 220, 255)),
                            (self.hyper_t is not None, "Гіперстрибок до %s: %d" % (
                                self.gal[self.target].name if self.target is not None else "?",
                                max(0, int(math.ceil((self.hyper_t or 0) - self.t)))), (255, 200, 90)),
                            (self.jump_t > 0, "СТРИБКОВИЙ ДВИГУН", (120, 220, 255))):
            if on:
                img = gfx.fit(self.fonts["small"].render(text, True, c if st != "wire" else gfx.WIRE))
                view.blit(img, (W / 2 - img.get_width() / 2, y))
                y += img.get_height()

    def project(self, p):
        c = self.VR.T @ (p - self.pos)
        if c[2] < gfx.NEAR:
            return None
        return CX + c[0] * F / c[2], CY - c[1] * F / c[2], float(c[2])

    def draw_blast(self, view, b):
        wire = self.style == "wire"
        VR = self.VR
        a = b.age
        life = b.life
        centre = b.pos + b.vel * a
        pc = self.project(centre)
        if pc is None or pc[2] > 40000:
            return
        if wire:                                       # the old way: a cloud of dots flying apart
            col = gfx.WIRE if a < life * 0.6 else gfx.WIRE_DIM
            P = (centre + b.dots * (0.25 + a)) - self.pos
            C = P @ VR
            ok = C[:, 2] > gfx.NEAR
            for x, y, z in C[ok].tolist():
                sx, sy = CX + x * F / z, CY - y * F / z
                if 0 <= sx < W and 0 <= sy < VH:
                    view.fill(col, (int(sx), int(sy), 2, 2))
        fade = 1 - a / life
        I3 = np.eye(3)
        for c0, offs, v, K, K2, spin, base in b.frags:
            Rm = I3 + math.sin(spin * a) * K + (1 - math.cos(spin * a)) * K2
            P = (c0 + v * a) + offs @ Rm.T - self.pos
            C = P @ VR
            if C[:, 2].min() < gfx.NEAR:
                continue
            pts = [(CX + x * F / z, CY - y * F / z) for x, y, z in C.tolist()]
            if wire:
                gfx.lines(view, gfx.WIRE if a < life * 0.6 else gfx.WIRE_DIM, True, pts, 1)
            else:
                hot = gfx.mix((255, 190, 90), base, a / 0.7)
                gfx.fill_poly(view, gfx.shade(hot, 0.35 + 0.9 * fade), pts)
                gfx.lines(view, gfx.shade(gfx.mix((255, 220, 150), (220, 210, 188), a / 0.7), 0.25 + 0.6 * fade),
                          True, pts, 1)                  # the hull's light trims on the broken plates
        k = max(0.0, 1 - a / life)
        C = (b.pos + b.shard_v * a - self.pos) @ VR
        for (shape, spin, sz, base), (cx_, cy_, cz) in zip(b.shards, C.tolist()):
            if cz < gfx.NEAR:
                continue
            p = (CX + cx_ * F / cz, CY - cy_ * F / cz)
            r = sz * F / cz
            if r < 0.4:
                continue
            ang = spin * a
            ca, sa = math.cos(ang), math.sin(ang)
            pts = [(p[0] + (x * ca - y * sa) * r, p[1] + (x * sa + y * ca) * r) for x, y in shape]
            if wire:
                gfx.lines(view, gfx.WIRE if a < life * 0.6 else gfx.WIRE_DIM, True, pts, 1)
            else:
                gfx.fill_poly(view, gfx.shade(gfx.mix((255, 210, 120), base, a / 0.5), 0.3 + 0.9 * k), pts)
        if not wire and a < 0.9:                       # the fireball
            k = 1 - a / 0.9
            step = int(a / 0.9 * 6)
            col = gfx.shade(gfx.mix((255, 220, 150), (200, 60, 10), step / 6), 0.3 + 0.7 * k)
            r = b.size * (0.5 + 2.5 * a) * F / pc[2]
            gfx.glow(view, (pc[0], pc[1]), col, min(r, 90))

    def draw_beams(self, view):
        """The two beams from the lower corners to where the pulse ends, while it lasts."""
        if self.t > self.beam_t or self.beam_end is None:
            return
        pe = self.project(self.beam_end)
        end = (pe[0], pe[1]) if pe else (CX, CY)
        wire = self.style == "wire"
        for x0 in (W * 0.16, W * 0.84):
            if wire:
                gfx.line(view, gfx.WIRE, (x0, VH), end, 1)
            else:
                gfx.line(view, (120, 20, 10), (x0, VH), end, 5)
                gfx.line(view, (255, 90, 40), (x0, VH), end, 3)
                gfx.line(view, (255, 230, 200), (x0, VH), end, 1)
        if self.beam_hit:
            if wire:
                for dx, dy in ((-4, -4), (4, 4), (-4, 4), (4, -4)):
                    gfx.line(view, gfx.WIRE, end, (end[0] + dx, end[1] + dy))
            else:
                gfx.glow(view, end, (255, 140, 70), 9)

    def draw_enemy_fire(self, view):
        """Their beams: from the ship (on screen or off it) towards us; a hit flashes the screen's edge."""
        wire = self.style == "wire"
        self.enemy_beams = [(s, until) for s, until in self.enemy_beams if self.t < until and not s.gone]
        for s, _ in self.enemy_beams:
            c = self.VR.T @ (s.pos - self.pos)
            if c[2] > gfx.NEAR:
                a = (CX + c[0] * F / c[2], CY - c[1] * F / c[2])
            else:                                      # from behind: in from the edge it is nearest
                k = 400.0 / max(1.0, math.hypot(c[0], c[1]))
                a = (CX + c[0] * k, CY - c[1] * k)
            b = (CX + (c[0] > 0) * 30 - 15, VH - 2)
            if wire:
                gfx.line(view, gfx.WIRE, a, b, 1)
            else:
                gfx.line(view, (60, 120, 30), a, b, 4)
                gfx.line(view, (170, 255, 90), a, b, 2)
        if self.t < self.flash_t:
            if wire:
                gfx.rect(view, gfx.WIRE, (0, 0, W, VH), 4)
            else:
                view.fill((90, 20, 10) if self.flash_front else (60, 20, 50), special_flags=pygame.BLEND_ADD)

    def draw_lock(self, view):
        """A missile's lock: a bracket round the ship in the sights."""
        s = self.lock
        if s is None or s.gone:
            return
        pc = self.project(s.pos)
        if pc is None:
            return
        r = max(8, s.me.radius * F / pc[2] * 0.9)
        x, y = pc[0], pc[1]
        col = gfx.WIRE if self.style == "wire" else (255, 80, 60)
        for sx, sy in ((-1, -1), (1, -1), (-1, 1), (1, 1)):
            cx, cy = x + sx * r, y + sy * r
            gfx.line(view, col, (cx, cy), (cx - sx * r * 0.4, cy), 1)
            gfx.line(view, col, (cx, cy), (cx, cy - sy * r * 0.4), 1)

    def draw_dock_hint(self, view):
        """In front of the slot: how far off its turn we are (the arc), the speed check."""
        w = self.world
        rel = self.pos - w.st_pos
        s = float(np.dot(rel, w.slot_n))
        if not (STATION_R < s < 5000) or length(rel - w.slot_n * s) > 1500:
            return 30
        if np.dot(self.R[:, 2], -w.slot_n) < 0.7:
            return 30
        u = w.st_R[:, 0]
        up_ = u - self.R[:, 2] * np.dot(u, self.R[:, 2])
        e = math.atan2(np.dot(up_, self.R[:, 1]), np.dot(up_, self.R[:, 0]))
        if e > math.pi / 2:
            e -= math.pi
        elif e < -math.pi / 2:
            e += math.pi
        ok_roll = abs(e) < math.radians(24)
        ok_speed = self.speed <= DOCK_SPEED
        wire = self.style == "wire"
        good, bad = ((gfx.WIRE, gfx.WIRE) if wire else ((120, 255, 140), (255, 120, 90)))
        cx, cy, r = W / 2, VH - 4, 30
        gfx.arc(view, (90, 190, 255) if not wire else gfx.WIRE, (cx - r, cy - r, 2 * r, 2 * r),
                math.pi * 0.25, math.pi * 0.75, 1)
        a = math.pi / 2 + clamp(e, -math.pi / 4, math.pi / 4)
        gfx.line(view, good if ok_roll else bad, (cx, cy), (cx + r * math.cos(a), cy - r * math.sin(a)), 2)
        f = self.fonts["mono"]
        t1 = f.render("ОБЕРТ " + ("✓" if ok_roll else "%+d°" % round(math.degrees(e))), True, good if ok_roll else bad)
        t2 = f.render("ШВИДК " + ("✓" if ok_speed else "↓"), True, good if ok_speed else bad)
        if gfx.HAT:                                    # side by side above the arc
            y = VH - r - t1.get_height() - 2
            view.blit(t1, (4, y))
            view.blit(t2, (W - 4 - t2.get_width(), y))
            return r + t1.get_height() + 4
        view.blit(t1, (cx - r - 6 - t1.get_width(), VH - 14))
        view.blit(t2, (cx + r + 6, VH - 14))
        return 30

    def dash_state(self):
        w = self.world
        RT = self.R.T
        blips = []
        for s in w.ships + [None]:
            p, col = (s.pos, (255, 60, 50) if s.hostile else s.colour) if s else (w.st_pos, (120, 255, 140))
            c = RT @ (p - self.pos)
            bx, by = c[0] / SCAN_RANGE, -c[2] / SCAN_RANGE
            if bx * bx + by * by < 1:
                blips.append((bx, by, c[1] / SCAN_RANGE, col if self.style != "wire" else
                              ((190, 255, 200) if s is None else gfx.WIRE)))
        dist_st = length(w.st_pos - self.pos)
        safe = dist_st < SAFE_ZONE
        tgt = w.st_pos if safe else np.zeros(3)
        d = unit(RT @ (tgt - self.pos))
        if w.deep:
            safe = False
        alt = (length(self.pos) - w.planet_r) / w.planet_r
        en = [clamp(self.energy - i, 0, 1) for i in range(4)]
        return dict(fs=self.fs, as_=self.as_, fv=self.fuel / galaxy.JUMP_MAX, ct=max(0.08, self.heat()), lt=min(1.0, self.laser_temp), al=clamp(alt, 0, 1),
                    sp=self.speed / MAX_SPEED, missiles=self.missiles,
                    rl=self.roll / ROLL_MAX, dc=self.pitch / PITCH_MAX, en=en, blips=blips,
                    compass=None if w.deep else (d[0], d[1], d[2] > 0), safe=safe, t=self.t, **{"as": self.as_})

    def draw(self, dt):
        self.draw_view(frame, dt)
        self.dash[self.style].draw(frame, self.dash_state())
        show()


# ---------------------------------------------------------------- the screens

def tunnel(game, inward, secs=1.4):
    """The launch / docking tunnel: rings of the slot rushing by."""
    t0 = time.monotonic()
    wire = game.style == "wire"
    lcd.play("select")
    while True:
        t = time.monotonic() - t0
        if t > secs:
            return
        pygame.event.pump()
        frame.fill((0, 0, 0) if wire else (3, 3, 10), (0, 0, W, VH))
        view = frame.subsurface((0, 0, W, VH))
        for k in range(14):
            z = ((k / 14.0) + (t * 1.6 if not inward else -t * 1.6)) % 1.0
            z = 0.05 + z
            sx, sy = 130 / z * 0.25, 40 / z * 0.25
            c = gfx.WIRE if wire else gfx.mix((20, 40, 80), (120, 210, 255), 1 - z)
            gfx.rect(view, c, (CX - sx, CY - sy, 2 * sx, 2 * sy), 1)
        game.dash[game.style].draw(frame, game.dash_state())
        show()
        clock.tick(30)


def draw_list(items, sel, top, bottom, f, colours, centre=True):
    """Menu rows from top to bottom, scrolled to keep the selected one in view."""
    row = f.get_height() + 2
    fits = max(1, int((bottom - top) // row))
    first = min(max(0, sel - fits // 2), max(0, len(items) - fits))
    for k, i in enumerate(range(first, min(len(items), first + fits))):
        on = i == sel
        img = gfx.fit(f.render(("▶ " if on else "") + items[i], True, colours[0] if on else colours[1]))
        frame.blit(img, ((W - img.get_width()) / 2 if centre else 8, top + k * row))
    if first > 0:
        gfx.poly(frame, colours[1], [(W - 10, top + 2), (W - 4, top + 2), (W - 7, top - 3)])
    if first + fits < len(items):
        gfx.poly(frame, colours[1], [(W - 10, bottom - 4), (W - 4, bottom - 4), (W - 7, bottom + 1)])


def ask(game, items, title=None, sel=0, back=None):
    """A small menu over the current frame; returns the chosen index or back (Esc)."""
    snap = frame.copy()
    f = gfx.font("DejaVuSans-Bold.ttf", 12)
    wire = game.style == "wire"
    while True:
        frame.blit(snap, (0, 0))
        row = f.get_height() + 2
        h = min(H - 8, 16 + row * (len(items) + (1 if title else 0)))
        bw = 240 if not gfx.HAT else W - 8
        box = pygame.Rect(W / 2 - bw / 2, max(4, VH / 2 - h / 2) if not gfx.HAT else 4, bw, h)
        sh = pygame.Surface(box.size, pygame.SRCALPHA)
        sh.fill((0, 0, 0, 220) if wire else (8, 12, 26, 225))
        frame.blit(sh, box.topleft)
        gfx.rect(frame, gfx.WIRE if wire else (90, 190, 255), box, 1)
        y = box.y + 8
        if title:
            img = f.render(title, True, gfx.WIRE if wire else (240, 232, 214))
            frame.blit(img, (W / 2 - img.get_width() / 2, y))
            y += row
        draw_list(items, sel, y, box.bottom - 6, f, ((gfx.WIRE, gfx.WIRE_DIM) if wire else
                                                       ((255, 210, 90), (170, 190, 220))))
        show()
        for ev in pygame.event.get():
            if ev.type == pygame.QUIT:
                return back
            if ev.type != pygame.KEYDOWN:
                continue
            hat = getattr(ev, "hat", False)
            if ev.key == pygame.K_UP:
                sel = (sel - 1) % len(items)
                lcd.play("click")
            elif ev.key == pygame.K_DOWN:
                sel = (sel + 1) % len(items)
                lcd.play("click")
            elif ev.key in (pygame.K_RETURN, pygame.K_KP_ENTER, pygame.K_SPACE) or (hat and ev.key == pygame.K_1):
                lcd.play("select")
                return sel
            elif ev.key == pygame.K_ESCAPE or (hat and ev.key == pygame.K_3):
                return back
        clock.tick(20)


HANGAR_L = gfx.norm((0.5, -0.6, 0.6))


def spin_matrix(t, tilt=-0.42):
    a = t * 0.6
    ca, sa = math.cos(a), math.sin(a)
    yaw = np.array([[ca, 0, sa], [0, 1, 0], [-sa, 0, ca]])
    ct, st = math.cos(tilt), math.sin(tilt)
    pitch = np.array([[1, 0, 0], [0, ct, -st], [0, st, ct]])
    return pitch @ yaw


def draw_backdrop(game, t):
    wire = game.style == "wire"
    if wire:
        frame.fill((0, 0, 0))
        return
    frame.fill((3, 3, 10))
    gfx.draw_stars(frame, game.world.stars, np.eye(3), F, W / 2, H / 2, "modern")


def title(game):
    """The title: the trader flies in from afar and turns in the frame, the name comes after it; the loader
    works behind it all (a thin "підготовка" line until it is through). Enter - continue (or a new game),
    N - a new game, Tab - the look, Esc - out."""
    t0 = time.monotonic()
    me = gfx.mesh("chumak")
    fbig = gfx.font("DejaVuSans-Bold.ttf", 19)
    fmono = gfx.font("DejaVuSansMono-Bold.ttf", 13)
    fs = gfx.font("DejaVuSansCondensed-Bold.ttf", 12)
    fm = gfx.font("DejaVuSansMono.ttf", 11)
    fl = gfx.font("DejaVuSansCondensed.ttf", 10)
    saved = game.saved()
    if saved:
        sgal = game.gal if int(saved.get("galaxy", 0)) == game.galnum else galaxy.generate(int(saved.get("galaxy", 0)))[0]
        sname = sgal[int(saved.get("here", 0)) % len(sgal)].name
        prompt = ("Enter - продовжити: %s, %.1f Кр" % (sname, saved.get("credits", 0)), "N - нова гра · Tab - вигляд")
    else:
        prompt = ("Натисніть пробіл, командире", "Tab - вигляд · Esc - вихід")
    want = None
    while True:
        for ev in pygame.event.get():
            if ev.type == pygame.QUIT:
                return "quit"
            if ev.type != pygame.KEYDOWN:
                continue
            hat = getattr(ev, "hat", False)
            if ev.key in (pygame.K_RETURN, pygame.K_KP_ENTER, pygame.K_SPACE) or (hat and ev.key == pygame.K_1):
                lcd.play("select")
                want = "continue" if saved else "new"
            elif ev.key == pygame.K_n and saved:
                lcd.play("select")
                want = "new"
            elif ev.key == pygame.K_TAB or (hat and ev.key == pygame.K_2):
                game.toggle_style()
            elif ev.key == pygame.K_ESCAPE or (hat and ev.key == pygame.K_3):
                game.music.stop(300)
                return "quit"
        ready = game.poll_loader()
        if ready and not want:
            game.music.serenade()                      # the Blue Danube over the title now and then, the old way
        if want and ready:
            game.music.stop(900)
            return want
        t = time.monotonic() - t0
        wire = game.style == "wire"
        draw_backdrop(game, t)
        k = min(1.0, t / 2.6)                          # the fly-in: from a speck to the frame, slowing down
        k = 1 - (1 - k) ** 3
        z = 300 + 5200 * (1 - k)
        tilt = -0.42 - 0.6 * (1 - k)
        if not wire and ready and game.world.planet is not None:      # the planet once it is lit
            Ls = gfx.norm((-0.8, 0.5, -0.2))
            game.world.planet.draw(frame, 300, 300, 120, Ls, "modern")
        gfx.draw_mesh(frame, me, spin_matrix(t + 2.0 * (1 - k), tilt), np.array((0.0, 0.0, z)), F, W / 2,
                      H / 2 + 6 - 40 * (1 - k), np.array(HANGAR_L), game.style)
        show_text = t > 1.4
        if wire:
            gfx.rect(frame, gfx.WIRE, (8, 8, W - 16, H - 16), 1)
            if show_text:
                img = gfx.fit(fmono.render("--- ЗОРЯНИЙ ТОРГОВЕЦЬ ---", True, gfx.WIRE), W - 24)
                frame.blit(img, (W / 2 - img.get_width() / 2, 20))
        else:
            gfx.rect(frame, (200, 196, 180), (8, 8, W - 16, H - 16), 1)
            if show_text:
                a = min(1.0, (t - 1.4) / 0.8)
                img = gfx.fit(fbig.render("ЗОРЯНИЙ ТОРГОВЕЦЬ", True, gfx.mix((3, 3, 10), (240, 232, 214), a)), W - 24)
                frame.blit(img, (W / 2 - img.get_width() / 2, 20))
                ly = 24 + img.get_height()
                for x in range(30, int(30 + (W - 60) * a), 6):
                    gfx.line(frame, (90, 190, 255), (x, ly), (x + 3, ly))
        if t > 2.4:
            for i, s_ in enumerate(prompt):
                if wire:
                    img = gfx.fit(fm.render(s_, True, gfx.WIRE), W - 24)
                else:
                    img = gfx.fit(fs.render(s_, True, (230, 230, 240) if i == 0 else (150, 200, 240)), W - 24)
                frame.blit(img, (W / 2 - img.get_width() / 2, H - 14 - (len(prompt) - i) * (img.get_height() + 2)))
        if not ready and (want or t > 2.4):            # still busy behind the scenes
            dots = "." * (1 + int(t * 3) % 3)
            img = fl.render("підготовка" + dots, True, gfx.WIRE_DIM if wire else (110, 130, 160))
            frame.blit(img, (W / 2 - img.get_width() / 2, H - 12 - img.get_height() // 2 - 2 if not want else
                             H / 2 + 70))
        show()
        clock.tick(30)


def ships_book(game):
    """The ship identification: each type turning, its name and role; ← → - the next, ↑ ↓ (held) - turn it
    over about the horizontal axis, Esc - back."""
    kinds = list(gfx.TYPES)
    i = 0
    t0 = time.monotonic()
    fn = gfx.font("DejaVuSans-Bold.ttf", 16)
    fs = gfx.font("DejaVuSansCondensed.ttf", 11)
    tilt = -0.35
    held = set()
    last = time.monotonic()
    while True:
        now = time.monotonic()
        dt = min(0.1, now - last)
        last = now
        for ev in pygame.event.get():
            if ev.type == pygame.QUIT:
                return
            if ev.type == pygame.KEYUP:
                held.discard(ev.key)
                continue
            if ev.type != pygame.KEYDOWN:
                continue
            hat = getattr(ev, "hat", False)
            if ev.key in (pygame.K_UP, pygame.K_DOWN):
                held.add(ev.key)
            elif ev.key in (pygame.K_RIGHT, pygame.K_RIGHTBRACKET):
                i = (i + 1) % len(kinds)
                lcd.play("click")
            elif ev.key in (pygame.K_LEFT, pygame.K_LEFTBRACKET):
                i = (i - 1) % len(kinds)
                lcd.play("click")
            elif ev.key == pygame.K_TAB or (hat and ev.key == pygame.K_2):
                game.toggle_style()
            elif ev.key in (pygame.K_ESCAPE, pygame.K_RETURN, pygame.K_KP_ENTER) or (hat and ev.key in (pygame.K_3, pygame.K_1)):
                return
        t = time.monotonic() - t0
        wire = game.style == "wire"
        draw_backdrop(game, t)
        me = gfx.mesh(kinds[i])
        z = me.radius * F / 105
        tilt += ((pygame.K_DOWN in held) - (pygame.K_UP in held)) * 1.6 * dt     # ↑ tips the nose away
        gfx.draw_mesh(frame, me, spin_matrix(t, tilt), np.array((0.0, 0.0, z)), F, W / 2, H / 2 - 10,
                      np.array(HANGAR_L), game.style)
        name, role = gfx.TYPES[kinds[i]][:2]
        hdr = gfx.fit(fs.render("РОЗПІЗНАВАННЯ КОРАБЛІВ  %d / %d" % (i + 1, len(kinds)), True,
                                gfx.WIRE if wire else (150, 200, 240)))
        frame.blit(hdr, (W / 2 - hdr.get_width() / 2, 10))
        y = H - 4
        for text, ff, col in reversed(((name, fn, gfx.WIRE if wire else (240, 232, 214)),
                                       (role, fs, gfx.WIRE if wire else (170, 190, 220)),
                                       ("← → інший · ↑ ↓ нахил · Esc назад", fs,
                                        gfx.WIRE_DIM if wire else (110, 130, 160)))):
            if gfx.HAT and ff is fs and text.startswith("←"):
                continue
            img = gfx.fit(ff.render(text, True, col))
            y -= img.get_height() + 2
            frame.blit(img, (W / 2 - img.get_width() / 2, y))
        show()
        clock.tick(30)


def station_screen(game):
    """Docked: the station, the system, our ship in the hangar, money, fuel and hold; launch / the market /
    fuel / the galaxy / the system's data / the ship book / the look / out. Returns "launch" or "quit"."""
    sel = 0
    game.music.stop(2500)                              # the waltz fades as we roll into the hangar
    while game.notices:
        notice_screen(game, *game.notices.pop(0))
    t0 = time.monotonic()
    me = gfx.mesh("chumak")
    fn = gfx.font("DejaVuSans-Bold.ttf", 15)
    fi = gfx.font("DejaVuSansCondensed.ttf", 11)
    fm = gfx.font("DejaVuSans-Bold.ttf", 11)
    while True:
        sys_ = game.system()
        need = galaxy.JUMP_MAX - game.fuel
        items = ["Злетіти", "Ринок", "Обладнання", "Заправитись" + (" (%.1f Кр)" % (need * galaxy.FUEL_PRICE) if need > 0.05 else " - повний бак"),
                 "Галактична карта", "Дані про систему", "Статус командира", "Розпізнавання кораблів",
                 "Вигляд: " + STYLE_NAMES[game.style], "Вийти"]
        for ev in pygame.event.get():
            if ev.type == pygame.QUIT:
                return "quit"
            if ev.type != pygame.KEYDOWN:
                continue
            hat = getattr(ev, "hat", False)
            if ev.key == pygame.K_UP:
                sel = (sel - 1) % len(items)
                lcd.play("click")
            elif ev.key == pygame.K_DOWN:
                sel = (sel + 1) % len(items)
                lcd.play("click")
            elif ev.key == pygame.K_TAB:
                game.toggle_style()
            elif ev.key in (pygame.K_RETURN, pygame.K_KP_ENTER, pygame.K_SPACE) or (hat and ev.key == pygame.K_1):
                lcd.play("select")
                if sel == 0:
                    return "launch"
                if sel == 1:
                    market_screen(game)
                elif sel == 2:
                    shop_screen(game)
                elif sel == 3:
                    refuel(game)
                elif sel == 4:
                    chart(game)
                elif sel == 5:
                    data_screen(game, game.here)
                elif sel == 6:
                    status_screen(game)
                elif sel == 7:
                    ships_book(game)
                elif sel == 8:
                    game.toggle_style()
                else:
                    return "quit"
                game.save()
            elif ev.key == pygame.K_ESCAPE or (hat and ev.key == pygame.K_3):
                return "quit"
        game.poll_loader()
        t = time.monotonic() - t0
        wire = game.style == "wire"
        draw_backdrop(game, t)
        if not wire:                                   # the hangar's floor: a lit grid
            for k in range(9):
                y = 130 + k * k * 1.3
                gfx.line(frame, (24 + k * 3, 34 + k * 4, 60 + k * 5), (0, y), (W, y))
            for k in range(-8, 9):
                gfx.line(frame, (30, 44, 74), (W / 2 + k * 6, 130), (W / 2 + k * 40, 240))
        hi, lo = (gfx.WIRE, gfx.WIRE) if wire else ((240, 232, 214), (150, 200, 240))
        mc = (gfx.WIRE, gfx.WIRE_DIM) if wire else ((255, 210, 90), (170, 190, 220))
        if gfx.HAT:                                    # no hangar: the name, the purse, the menu
            y = 4
            for text, ff, col in (("«%s»" % sys_.name, fn, hi),
                                  ("%.1f Кр · %.1f св. р. · %d/%d т" % (game.credits, game.fuel, game.held(), game.cargo_max()),
                                   fi, lo)):
                img = gfx.fit(ff.render(text, True, col))
                frame.blit(img, (W / 2 - img.get_width() / 2, y))
                y += img.get_height() + 2
            draw_list(items, sel, y + 6, H - 4, fm, mc)
            show()
            clock.tick(30)
            continue
        gfx.draw_mesh(frame, me, spin_matrix(t), np.array((0.0, 0.0, 360.0)), F, W / 2, 112,
                      np.array(HANGAR_L), game.style)
        hdr = fn.render("Станція «%s»" % sys_.name, True, hi)
        frame.blit(hdr, (W / 2 - hdr.get_width() / 2, 8))
        img = fi.render("%s · %s · тех. %d" % (galaxy.ECONOMY[sys_.econ], galaxy.GOVERNMENT[sys_.gov], sys_.tech),
                        True, lo)
        frame.blit(img, (W / 2 - img.get_width() / 2, 27))
        img = fi.render("%.1f Кр · паливо %.1f св. р. · трюм %d/%d т" % (game.credits, game.fuel, game.held(),
                                                                        game.cargo_max()), True, hi)
        frame.blit(img, (W / 2 - img.get_width() / 2, 42))
        if game.target is not None:
            tg = game.gal[game.target]
            img = fi.render("Ціль: %s, %.1f св. р." % (tg.name, sys_.dist(tg)), True, lo)
            frame.blit(img, (W / 2 - img.get_width() / 2, 56))
        draw_list(items, sel, 196, H - 2, fm, mc)
        show()
        clock.tick(30)


def notice_screen(game, title, text):
    """A message at the station - customs, a mission's briefing, a reward: the text types itself out."""
    f = gfx.font("DejaVuSansCondensed.ttf", 12)
    fh = gfx.font("DejaVuSans-Bold.ttf", 15)
    t0 = time.monotonic()
    lcd.play("check")
    lines_ = wrap(f, text, W - 24)
    total = sum(len(l) for l in lines_)
    while True:
        n = int((time.monotonic() - t0) * 45)              # letters so far
        for ev in pygame.event.get():
            if ev.type == pygame.QUIT:
                return
            if ev.type == pygame.KEYDOWN:
                if n < total:
                    t0 -= 1000                             # the first key shows it all, the next goes on
                else:
                    return
        c = screen_colours(game)
        frame.fill(c["bg"])
        gfx.rect(frame, c["lo"], (6, 6, W - 12, H - 12), 1)
        img = gfx.fit(fh.render(title, True, c["sel"]), W - 24)
        frame.blit(img, (W / 2 - img.get_width() / 2, 16))
        y = 24 + img.get_height() + 8
        left = n
        for ln in lines_:
            if left <= 0 or y > H - 40:
                break
            frame.blit(f.render(ln[:left], True, c["hi"]), (12, y))
            left -= len(ln)
            y += f.get_height() + 2
        if n >= total and int(time.monotonic() * 2) % 2:
            img = f.render("Enter - далі", True, c["lo"])
            frame.blit(img, (W / 2 - img.get_width() / 2, H - 26))
        show()
        clock.tick(30)


def refuel(game):
    need = galaxy.JUMP_MAX - game.fuel
    if need < 0.05:
        game.sfx.play("lock")
        return
    buy = min(need, game.credits / galaxy.FUEL_PRICE)
    if buy < 0.05:
        lcd.play("error")
        return
    game.fuel += buy
    game.credits -= buy * galaxy.FUEL_PRICE
    lcd.play("point")


def screen_colours(game):
    wire = game.style == "wire"
    if wire:
        return dict(bg=(0, 0, 0), hi=gfx.WIRE, lo=gfx.WIRE_DIM, sel=gfx.WIRE, bar=(0, 60, 20), warn=gfx.WIRE,
                    ok=gfx.WIRE)
    return dict(bg=(6, 8, 18), hi=(240, 232, 214), lo=(150, 170, 200), sel=(255, 210, 90), bar=(30, 40, 70),
                warn=(255, 110, 90), ok=(120, 230, 140))


def market_screen(game):
    """Buy and sell: ↑ ↓ - the good, → - buy one, ← - sell one, Enter - buy all you can, Backspace - sell all."""
    goods = galaxy.GOODS
    sel = 0
    big = 1.0 if gfx.HAT else 1.5                      # the PicoCalc's market in bigger letters (the HAT's are doubled)
    f = gfx.font("DejaVuSansCondensed.ttf", 11 * big)
    fb = gfx.font("DejaVuSansCondensed-Bold.ttf", 11 * big)
    fh = gfx.font("DejaVuSans-Bold.ttf", 13 * big)
    row = 14
    top = 40
    while True:
        for ev in pygame.event.get():
            if ev.type == pygame.QUIT:
                return
            if ev.type != pygame.KEYDOWN:
                continue
            hat = getattr(ev, "hat", False)
            price, stock = game.market[sel]
            if ev.key == pygame.K_UP:
                sel = (sel - 1) % len(goods)
            elif ev.key == pygame.K_DOWN:
                sel = (sel + 1) % len(goods)
            elif ev.key in (pygame.K_RIGHT, pygame.K_RIGHTBRACKET, pygame.K_EQUALS, pygame.K_RETURN, pygame.K_KP_ENTER) \
                    or (hat and ev.key == pygame.K_1):
                n = 1 if ev.key in (pygame.K_RIGHT, pygame.K_RIGHTBRACKET, pygame.K_EQUALS) or hat else 999
                n = min(n, stock, game.cargo_max() - game.held(), int(game.credits // price) if price > 0 else 0)
                if n > 0:
                    game.cargo[sel] += n
                    game.market[sel][1] -= n
                    game.credits -= n * price
                    lcd.play("chip")
                else:
                    lcd.play("error")
            elif ev.key in (pygame.K_LEFT, pygame.K_LEFTBRACKET, pygame.K_MINUS, pygame.K_BACKSPACE, pygame.K_DELETE) \
                    or (hat and ev.key == pygame.K_2):
                n = 1 if ev.key in (pygame.K_LEFT, pygame.K_LEFTBRACKET, pygame.K_MINUS) or hat else game.cargo[sel]
                n = min(n, game.cargo[sel])
                if n > 0:
                    game.cargo[sel] -= n
                    game.market[sel][1] += n
                    game.credits += n * price
                    lcd.play("chip")
                else:
                    lcd.play("error")
            elif ev.key in (pygame.K_ESCAPE, pygame.K_TAB) or (hat and ev.key == pygame.K_3):
                if ev.key == pygame.K_TAB:
                    game.toggle_style()
                    continue
                return
        c = screen_colours(game)
        frame.fill(c["bg"])
        img = gfx.fit(fh.render("РИНОК · %s" % game.system().name, True, c["hi"]))
        frame.blit(img, (W / 2 - img.get_width() / 2, 4))
        y0 = 8 + img.get_height()
        hat = gfx.HAT
        # columns: name, price, (the stock - not on the HAT: it shows the chosen one's below), in the hold
        cols = ((6, "товар", 0), (W - 70, "ціна", 1), (W - 4, "трюм", 1)) if hat else \
            ((6, "товар", 0), (W - 104, "ціна", 1), (W - 56, "є", 1), (W - 4, "трюм", 1))
        for x, t, al in cols:
            img = f.render(t, True, c["lo"])
            frame.blit(img, (x - img.get_width() if al else x + (f.get_height() + 6 if x < 20 else 0), y0))
        top = y0 + f.get_height() + 2
        row = f.get_height() + (1 if not hat else 2)
        foot = 3 * (f.get_height() + 2) + 6
        fits = int((H - foot - top) // row)
        first = min(max(0, sel - fits // 2), max(0, len(goods) - fits))
        for k, i in enumerate(range(first, min(len(goods), first + fits))):
            y = top + k * row
            price, stock = game.market[i]
            if i == sel:
                gfx.rect(frame, c["bar"], (2, y - 1, W - 4, row))
            col = c["sel"] if i == sel else (c["hi"] if game.cargo[i] else c["lo"])
            ff = fb if i == sel else f
            name = goods[i][0] + ("" if goods[i][6] else " ⚠")
            ic = gfx.goods_icon(i, row - 2, game.style == "wire")
            frame.blit(ic, (5, y))
            frame.blit(gfx.fit(ff.render(name, True, col), (W - 130 - row) if hat else W - 160 - row), (8 + row, y))
            img = ff.render("%.1f" % price, True, col)
            frame.blit(img, (cols[1][0] - img.get_width(), y))
            if not hat:
                img = ff.render(("%d" % stock) if stock else "-", True, col)
                frame.blit(img, (cols[2][0] - img.get_width(), y))
            if game.cargo[i]:
                img = ff.render("%d" % game.cargo[i], True, c["sel"])
                frame.blit(img, (cols[-1][0] - img.get_width(), y))
        y = H - foot + 4
        price, stock = game.market[sel]
        lines_ = ["%.1f Кр · трюм %d/%d т" % (game.credits, game.held(), game.cargo_max())]
        if hat:
            lines_ += ["є: %d %s · → купити ← продати" % (stock, goods[sel][1]) if stock else
                       "немає в продажу · ← продати"]
        else:
            lines_ += ["є %d %s · → купити ← продати" % (stock, goods[sel][1]) if stock else "немає · ← продати",
                       "Enter - скільки влізе · ⌫ - продати все"]
        for k, t in enumerate(lines_):
            img = gfx.fit((fb if k == 0 else f).render(t, True, c["hi"] if k == 0 else c["lo"]))
            frame.blit(img, (W / 2 - img.get_width() / 2, y))
            y += img.get_height() + 2
        if not goods[sel][6] and not hat:
            img = f.render("⚠ заборонено в суворих державах", True, c["warn"])
            frame.blit(img, (W / 2 - img.get_width() / 2, 4 + 14))
        show()
        clock.tick(30)


def owned(game, key):
    if key == "missile":
        return game.missiles >= MISSILES_MAX
    if key == "fuel":
        return game.fuel >= galaxy.JUMP_MAX - 0.05
    if key in LASERS:
        return game.laser == key or (key == "beam" and game.laser == "military")
    return key in game.equip


def shop_screen(game):
    """Equipment: ↑ ↓ - the item, Enter - buy it (what this station's tech level sells)."""
    sel = 0
    big = 1.0 if gfx.HAT else 1.5                      # the PicoCalc's market in bigger letters (the HAT's are doubled)
    f = gfx.font("DejaVuSansCondensed.ttf", 11 * big)
    fb = gfx.font("DejaVuSansCondensed-Bold.ttf", 11 * big)
    fh = gfx.font("DejaVuSans-Bold.ttf", 13 * big)
    while True:
        tech = game.system().tech
        sold = [e for e in EQUIPMENT if e[3] <= tech]
        sel = min(sel, len(sold) - 1)
        for ev in pygame.event.get():
            if ev.type == pygame.QUIT:
                return
            if ev.type != pygame.KEYDOWN:
                continue
            hat = getattr(ev, "hat", False)
            if ev.key == pygame.K_UP:
                sel = (sel - 1) % len(sold)
            elif ev.key == pygame.K_DOWN:
                sel = (sel + 1) % len(sold)
            elif ev.key == pygame.K_TAB:
                game.toggle_style()
            elif ev.key in (pygame.K_RETURN, pygame.K_KP_ENTER, pygame.K_SPACE, pygame.K_RIGHT) or (hat and ev.key == pygame.K_1):
                buy(game, sold[sel])
            elif ev.key == pygame.K_ESCAPE or (hat and ev.key == pygame.K_3):
                return
        c = screen_colours(game)
        frame.fill(c["bg"])
        img = gfx.fit(fh.render("ОБЛАДНАННЯ · тех. %d" % tech, True, c["hi"]))
        frame.blit(img, (W / 2 - img.get_width() / 2, 4))
        top = 10 + img.get_height()
        row = f.get_height() + 3
        foot = 3 * (f.get_height() + 2) + 6
        fits = int((H - foot - top) // row)
        first = min(max(0, sel - fits // 2), max(0, len(sold) - fits))
        for k, i in enumerate(range(first, min(len(sold), first + fits))):
            key, name, price, _, what = sold[i]
            y = top + k * row
            if i == sel:
                gfx.rect(frame, c["bar"], (2, y - 1, W - 4, row))
            have = owned(game, key)
            col = c["sel"] if i == sel else (c["lo"] if have else c["hi"])
            ff = fb if i == sel else f
            label = name + (" (%d/%d)" % (game.missiles, MISSILES_MAX) if key == "missile" else "")
            frame.blit(gfx.fit(ff.render(label, True, col), W - 110), (8, y))
            if key == "fuel":
                p = (galaxy.JUMP_MAX - game.fuel) * galaxy.FUEL_PRICE
                price_s = "є" if have else "%.1f" % p
            else:
                price_s = "✓ є" if have else "%d Кр" % price
            img = ff.render(price_s, True, col)
            frame.blit(img, (W - 8 - img.get_width(), y))
        y = H - foot + 4
        key, name, price, _, what = sold[sel]
        for k, t in enumerate((what, "%.1f Кр · Enter - купити · Esc" % game.credits)):
            img = gfx.fit((f if k == 0 else fb).render(t, True, c["lo"] if k == 0 else c["hi"]))
            frame.blit(img, (W / 2 - img.get_width() / 2, y))
            y += img.get_height() + 3
        show()
        clock.tick(30)


def buy(game, item):
    key, name, price, _, _ = item
    if key == "fuel":
        refuel(game)
        return
    if owned(game, key):
        lcd.play("error")
        return
    if game.credits < price:
        lcd.play("error")
        return
    game.credits -= price
    if key == "missile":
        game.missiles += 1
    elif key in LASERS:
        game.laser = key
    else:
        game.equip.add(key)
    lcd.play("point")


def status_screen(game):
    """The commander: where, money, fuel, the record with the law, the combat rank, the kills, the hold."""
    f = gfx.font("DejaVuSansCondensed.ttf", 12)
    fb = gfx.font("DejaVuSansCondensed-Bold.ttf", 12)
    fh = gfx.font("DejaVuSans-Bold.ttf", 15)
    while True:
        for ev in pygame.event.get():
            if ev.type == pygame.QUIT:
                return
            if ev.type == pygame.KEYDOWN:
                if ev.key == pygame.K_TAB:
                    game.toggle_style()
                else:
                    return
        c = screen_colours(game)
        frame.fill(c["bg"])
        img = gfx.fit(fh.render("СТАТУС КОМАНДИРА", True, c["hi"]))
        frame.blit(img, (W / 2 - img.get_width() / 2, 6))
        y = 14 + img.get_height()
        legal = game.legal_name()
        rows = [("Система", game.system().name), ("Кредити", "%.1f Кр" % game.credits),
                ("Паливо", "%.1f св. р." % game.fuel), ("Закон", legal), ("Ранг", game.rank()),
                ("Знищено", "%d" % game.kills), ("Лазер", {"pulse": "імпульсний", "beam": "променевий",
                                                             "military": "військовий"}[game.laser]),
                ("Ракети", "%d" % game.missiles)] + [(e[1], "✓") for e in EQUIPMENT
                                                     if e[0] in game.equip]
        for key, name in (("groza", "Місія «Гроза»"), ("docs", "Місія «Документи»")):
            m = game.missions.get(key, {})
            if m.get("state") in ("active", "killed"):
                rows.append((name, game.gal[m["sys"]].name if m["state"] == "active" else "звітуйте на станції"))
            elif m.get("state") == "done":
                rows.append((name, "виконано"))
        for k, v in rows:
            col = c["warn"] if k == "Закон" and game.legal else (c["sel"] if k == "Ранг" else c["hi"])
            frame.blit(f.render(k, True, c["lo"]), (10, y))
            img = fb.render(v, True, col)
            frame.blit(img, (W - 10 - img.get_width(), y))
            y += f.get_height() + 3
        y += 6
        frame.blit(fb.render("Трюм: %d/%d т" % (game.held(), game.cargo_max()), True, c["hi"]), (10, y))
        y += f.get_height() + 3
        held = [(galaxy.GOODS[i][0], n, galaxy.GOODS[i][1]) for i, n in enumerate(game.cargo) if n]
        if not held:
            frame.blit(f.render("порожньо", True, c["lo"]), (20, y))
        for name, n, unit_ in held:
            if y > H - f.get_height() - 4:
                break
            frame.blit(f.render(name, True, c["lo"]), (20, y))
            img = f.render("%d %s" % (n, unit_), True, c["hi"])
            frame.blit(img, (W - 10 - img.get_width(), y))
            y += f.get_height() + 1
        show()
        clock.tick(20)


_previews = {}


def planet_preview(sys_, size=110):
    """A small lit planet of a system for its data screen (made once, ~0.1 s)."""
    key = (sys_.idx, size)
    if key not in _previews:
        tex, air = gfx.planet_texture(sys_.kind, sys_.seed % 997, 128, 64)
        _previews[key] = gfx.sphere(tex, air, size, (0.65, 0.45, 0.62))
    return _previews[key]


def wrap(f, text, width):
    out, cur = [], ""
    for w in text.split():
        t = (cur + " " + w).strip()
        if f.size(t)[0] > width and cur:
            out.append(cur)
            cur = w
        else:
            cur = t
    if cur:
        out.append(cur)
    return out


def data_screen(game, idx):
    """A system's data: its planet, economy, government, tech, people, wealth, size and what it is known for."""
    sys_ = game.gal[idx]
    here = game.system()
    f = gfx.font("DejaVuSansCondensed.ttf", 12)
    fb = gfx.font("DejaVuSansCondensed-Bold.ttf", 12)
    fh = gfx.font("DejaVuSans-Bold.ttf", 16)
    t0 = time.monotonic()
    while True:
        for ev in pygame.event.get():
            if ev.type == pygame.QUIT:
                return
            if ev.type == pygame.KEYDOWN:
                if ev.key == pygame.K_TAB:
                    game.toggle_style()
                else:
                    return
        c = screen_colours(game)
        wire = game.style == "wire"
        frame.fill(c["bg"])
        d = here.dist(sys_)
        if gfx.HAT:
            y = 4
            facts = [(sys_.name, fh, c["hi"]), ("тут" if idx == game.here else "%.1f св. р." % d, f, c["lo"]),
                     (galaxy.ECONOMY[sys_.econ], fb, c["hi"]), (galaxy.GOVERNMENT[sys_.gov], fb, c["hi"]),
                     ("тех. %d · %.1f млрд" % (sys_.tech, sys_.pop), fb, c["hi"])]
            for text, ff, col in facts:
                img = gfx.fit(ff.render(text, True, col))
                frame.blit(img, (8, y))
                y += img.get_height() + 1
            for ln in wrap(f, sys_.desc, W - 16):
                if y > H - f.get_height():
                    break
                frame.blit(f.render(ln, True, c["lo"]), (8, y))
                y += f.get_height()
            show()
            clock.tick(20)
            continue
        if wire:
            r = 52
            gfx.circle(frame, gfx.WIRE, (W - 70, 74), r, 1)
            gfx.ellipse(frame, gfx.WIRE, (W - 70 - r, 74 - r * 0.25, 2 * r, r * 0.5), 1)
        else:
            img = planet_preview(sys_)
            frame.blit(img, (W - 70 - img.get_width() / 2, 74 - img.get_height() / 2))
        img = fh.render(sys_.name, True, c["hi"])
        frame.blit(img, (10, 10))
        y = 36
        for k, v in (("Відстань", "тут" if idx == game.here else "%.1f св. р." % d),
                     ("Економіка", galaxy.ECONOMY[sys_.econ]), ("Влада", galaxy.GOVERNMENT[sys_.gov]),
                     ("Тех. рівень", "%d" % sys_.tech)):
            frame.blit(f.render(k, True, c["lo"]), (10, y))
            frame.blit(fb.render(v, True, c["hi"]), (10, y + 13))
            y += 29
        y += 4
        for k, v in (("Населення", "%.1f млрд" % sys_.pop), ("Валовий продукт", "%d млн Кр" % sys_.prod),
                     ("Радіус", "%d км" % sys_.radius_km)):
            frame.blit(f.render(k, True, c["lo"]), (10, y))
            img = fb.render(v, True, c["hi"])
            frame.blit(img, (W - 10 - img.get_width(), y))
            y += 16
        y += 8
        for ln in wrap(f, sys_.desc, W - 20):
            frame.blit(f.render(ln, True, c["hi"]), (10, y))
            y += 16
        img = f.render("будь-яка клавіша - назад", True, c["lo"])
        frame.blit(img, (W / 2 - img.get_width() / 2, H - 18))
        show()
        clock.tick(20)


class ChartCam:
    def __init__(self):
        self.yaw, self.pitch, self.dist = 0.5, 0.95, 230.0
        self.at = np.zeros(3)
        self.f = 230.0

    def project(self, P):
        """Points (n, 3) -> screen x, y and depth arrays."""
        Q = P - self.at
        c, s = math.cos(self.yaw), math.sin(self.yaw)
        x, z = Q[:, 0] * c - Q[:, 2] * s, Q[:, 0] * s + Q[:, 2] * c
        c, s = math.cos(self.pitch), math.sin(self.pitch)
        y, z = Q[:, 1] * c - z * s, Q[:, 1] * s + z * c
        z = z + self.dist
        z = np.maximum(z, 1.0)
        return W / 2 + x * self.f / z, 150 - y * self.f / z, z


def chart(game):
    """The galaxy in 3D: a tilted spiral turning slowly; stalks from the stars near us to the plane, the jump
    range as a ring round us, the chosen star with a line to it. ← → - the next star by distance, ↑ ↓ - tilt,
    z - the whole galaxy / round us, i - the star's data, Enter - make it the hyperspace target, Esc - back."""
    S = game.gal
    here = S[game.here]
    P = np.array([s.pos for s in S])
    order = sorted(range(len(S)), key=lambda i: here.dist(S[i]))[1:]
    sel = order.index(game.target) if game.target in order else 0
    cam = ChartCam()
    zoom = 1                                            # 0 - the galaxy, 1 - round us
    names = {}
    f = gfx.font("DejaVuSansCondensed.ttf", 10)
    fb = gfx.font("DejaVuSansCondensed-Bold.ttf", 11)
    fh = gfx.font("DejaVuSans-Bold.ttf", 12)
    keys = set()
    last = time.monotonic()
    while True:
        now = time.monotonic()
        dt = min(0.1, now - last)
        last = now
        for ev in pygame.event.get():
            if ev.type == pygame.QUIT:
                return
            if ev.type == pygame.KEYUP:
                keys.discard(ev.key)
                continue
            if ev.type != pygame.KEYDOWN:
                continue
            hat = getattr(ev, "hat", False)
            keys.add(ev.key)
            if ev.key in (pygame.K_RIGHT, pygame.K_RIGHTBRACKET):
                sel = (sel + 1) % len(order)
                lcd.play("click")
            elif ev.key in (pygame.K_LEFT, pygame.K_LEFTBRACKET):
                sel = (sel - 1) % len(order)
                lcd.play("click")
            elif ev.key == pygame.K_z or (hat and ev.key == pygame.K_2):
                zoom ^= 1
                lcd.play("move")
            elif ev.key == pygame.K_i:
                data_screen(game, order[sel])
            elif ev.key == pygame.K_TAB:
                game.toggle_style()
            elif ev.key in (pygame.K_RETURN, pygame.K_KP_ENTER, pygame.K_SPACE) or (hat and ev.key == pygame.K_1):
                game.target = order[sel]
                game.sfx.play("lock")
                return
            elif ev.key == pygame.K_ESCAPE or (hat and ev.key == pygame.K_3):
                return
        if pygame.K_UP in keys:
            cam.pitch = clamp(cam.pitch + 1.2 * dt, 0.1, 1.5)
        if pygame.K_DOWN in keys:
            cam.pitch = clamp(cam.pitch - 1.2 * dt, 0.1, 1.5)
        cam.yaw += 0.12 * dt
        want_at = np.array(here.pos) if zoom else np.zeros(3)
        cam.at += (want_at - cam.at) * min(1.0, dt * 4)
        cam.dist += ((24.0 if zoom else 235.0) - cam.dist) * min(1.0, dt * 4)
        c = screen_colours(game)
        wire = game.style == "wire"
        frame.fill(c["bg"])
        tgt = S[order[sel]]
        # rings on the plane: the galaxy's, or the reach of a full tank and of the fuel we have
        ringc = (30, 50, 90) if not wire else gfx.WIRE_DIM
        circles = [(15, ringc), (30, ringc), (45, ringc)] if not zoom else []
        circles += [(galaxy.JUMP_MAX, (60, 100, 160) if not wire else gfx.WIRE_DIM),
                    (game.fuel, (90, 200, 255) if not wire else gfx.WIRE)]
        for r, col in circles:
            ctr = np.zeros(3) if r in (15, 30, 45) and not zoom else np.array(here.pos)
            a = np.linspace(0, 2 * math.pi, 49)
            ring = np.stack([ctr[0] + r * np.cos(a), np.full_like(a, ctr[1]), ctr[2] + r * np.sin(a)], 1)
            x, y, z = cam.project(ring)
            pts = list(zip(x.tolist(), y.tolist()))
            for k in range(0, 48, 1 if r <= galaxy.JUMP_MAX else 2):
                gfx.line(frame, col, pts[k], pts[k + 1])
        x, y, z = cam.project(P)
        base = cam.project(np.column_stack([P[:, 0], np.full(len(P), here.y if zoom else 0.0), P[:, 2]]))
        near = {i for i in order if here.dist(S[i]) <= galaxy.JUMP_MAX} | {game.here}
        labels = []                                     # placed name boxes: no two overlap
        depth = np.argsort(-z)
        for i in depth.tolist():
            sx, sy = x[i], y[i]
            if not (-10 < sx < W + 10 and -10 < sy < 250):
                continue
            s_ = S[i]
            if i in near:
                gfx.line(frame, (70, 100, 150) if not wire else gfx.WIRE_DIM, (sx, sy), (base[0][i], base[1][i]))
            size = int(clamp(2.6 * cam.f / z[i], 1, 4))
            col = gfx.WIRE if wire else s_.sun
            if not wire and size > 1:
                gfx.glow(frame, (sx, sy), tuple(v // 4 for v in s_.sun), size * 1.6)
            frame.fill(col, (int(sx - size / 2), int(sy - size / 2), size, size))
        for i in sorted(near, key=lambda i: (i != order[sel], here.dist(S[i]))) if zoom and not gfx.HAT else ():
            img = names.get(i)
            if img is None:
                img = names[i] = f.render(S[i].name, True, (180, 190, 210) if not wire else gfx.WIRE)
            box = pygame.Rect(x[i] + 5, y[i] - 6, img.get_width(), img.get_height())
            if box.bottom < 250 and box.collidelist(labels) < 0:
                labels.append(box)
                frame.blit(img, box)
        hx, hy = x[game.here], y[game.here]
        tx, ty = x[order[sel]], y[order[sel]]
        d = here.dist(tgt)
        reach = d <= game.fuel
        lc = (c["ok"] if reach else c["warn"])
        gfx.line(frame, lc, (hx, hy), (tx, ty), 1)
        gfx.circle(frame, (90, 200, 255) if not wire else gfx.WIRE, (hx, hy), 6, 1)
        gfx.rect(frame, c["sel"], (tx - 7, ty - 7, 14, 14), 1)
        if game.target is not None and game.target != order[sel]:
            gx, gy = x[game.target], y[game.target]
            gfx.rect(frame, c["lo"], (gx - 5, gy - 5, 10, 10), 1)
        mt = game.mission_target()
        if mt is not None:                             # the mission's system: a pulsing diamond
            mx, my = x[mt], y[mt]
            r = 7 + 3 * math.sin(time.monotonic() * 5)
            col = (255, 90, 200) if not wire else gfx.WIRE
            gfx.lines(frame, col, True, [(mx, my - r), (mx + r, my), (mx, my + r), (mx - r, my)], 2)
        # the panel
        if gfx.HAT:
            t1 = gfx.fit(fh.render("%s %.1f св.р." % (tgt.name, d), True, lc))
            t2 = gfx.fit(f.render("%s · тех. %d" % (galaxy.ECONOMY[tgt.econ], tgt.tech), True, c["hi"]))
            py = H - t1.get_height() - t2.get_height() - 6
            gfx.rect(frame, c["bg"], (0, py, W, H - py))
            gfx.line(frame, c["lo"], (0, py), (W, py))
            frame.blit(t1, (6, py + 3))
            frame.blit(t2, (6, py + 4 + t1.get_height()))
        else:
            gfx.rect(frame, c["bg"], (0, 252, W, H - 252))
            gfx.line(frame, c["lo"], (0, 252), (W, 252))
            img = fh.render("ГАЛАКТИКА %d" % (game.galnum + 1) + ("" if not zoom else " · поруч з %s" % here.name), True,
                        c["hi"])
            frame.blit(img, (W / 2 - img.get_width() / 2, 4))
            img = fh.render("%s  %.1f св. р." % (tgt.name, d), True, c["sel"])
            frame.blit(img, (8, 257))
            img = f.render("досяжна" if reach else ("далеко: паливо %.1f" % game.fuel), True, lc)
            frame.blit(img, (W - 8 - img.get_width(), 260))
            img = f.render("%s · %s · тех. %d" % (galaxy.ECONOMY[tgt.econ], galaxy.GOVERNMENT[tgt.gov], tgt.tech),
                           True, c["hi"])
            frame.blit(img, (8, 275))
            img = f.render("← → зірка · ↑ ↓ нахил · z масштаб · i дані · Enter - ціль · Esc", True, c["lo"])
            frame.blit(img, (W / 2 - img.get_width() / 2, 300))
        show()
        clock.tick(30)


def hyperspace(game, galactic=False):
    """Through hyperspace: rings rushing by while the next system is built, then out far from its planet.
    galactic - the galactic hyperdrive: into the next galaxy, near the same place in it, no fuel used."""
    if galactic:
        old = game.system()
        game.set_galaxy((game.galnum + 1) % galaxy.GALAXIES)
        game.target = min(range(len(game.gal)), key=lambda i: game.gal[i].dist(old))
        game.here = game.target
        misjump = False
    else:
        d = jump_dist(game)
        hunted = game.missions.get("docs", {}).get("state") == "active"
        misjump = not game.world.deep and random.random() < (0.3 if hunted else MISJUMP)
        game.fuel = max(0.0, game.fuel - (d * 0.5 if misjump else d))
    game.music.stop(200)
    game.sfx.play("hyper")
    wire = game.style == "wire"
    t0 = time.monotonic()
    nxt = game.system() if misjump else game.gal[game.target]
    box = {}

    def build():                       # numpy only (no pygame surfaces): it lets go of the interpreter
        try:
            wd = World(nxt, deep=misjump)
            while wd.planet is not None and not wd.planet.prewarm():
                pass
            box["world"] = wd
        except Exception as e:         # a broken worker must not leave us in hyperspace for ever
            box["error"] = e
    th = threading.Thread(target=build, daemon=True)
    th.start()
    while True:
        t = time.monotonic() - t0
        pygame.event.pump()
        frame.fill((0, 0, 0) if wire else (3, 3, 10), (0, 0, W, VH))
        view = frame.subsurface((0, 0, W, VH))
        for k in range(16):
            z = (k / 16.0 + t * 0.9) % 1.0
            r = 4 + 220 * z * z
            if wire:
                col = gfx.WIRE if k % 2 else gfx.WIRE_DIM
            else:
                h = (k * 0.13 + t * 0.4) % 1.0
                col = tuple(int(90 + 160 * max(0.0, math.sin(2 * math.pi * (h + o)))) for o in (0, 1 / 3, 2 / 3))
            gfx.circle(view, col, (CX, CY), r, 1 if wire else 2)
        game.dash[game.style].draw(frame, game.dash_state())
        show()
        clock.tick(30)
        if ("world" in box or "error" in box) and t > 2.6:
            break
        if t > 25:                                     # the worker is stuck: build it here
            box["error"] = TimeoutError()
            break
    if misjump:                                        # stuck between the stars, the target still ahead
        game.world = box["world"] if "world" in box else World(nxt, deep=True)
        game.arrive()
        game.say("ЗБІЙ ГІПЕРСТРИБКА! Чужинці!", 4)
        lcd.play("error")
        return
    game.here = game.target
    game.target = None
    game.world = box["world"] if "world" in box else World(game.system())
    game.arrive()
    if galactic:
        game.say("Галактика %d! Система %s" % (game.galnum + 1, game.system().name), 5)
    elif any(sh.mission == "groza" for sh in game.world.ships):
        game.say("Система %s · УВАГА: тут «Гроза»!" % game.system().name, 5)
    else:
        game.say("Ласкаво просимо до системи %s" % game.system().name, 4)


def flight(game):
    """Out of the slot, fly until docked, dead, rescued or quit (the engine's hum stops with it)."""
    try:
        return _flight(game)
    finally:
        game.engine.stop()


def _flight(game):
    game.reset_ship()
    game.keys.clear()
    while not game.world.planet.prewarm():
        pygame.event.pump()
    tunnel(game, False)
    game.say("Вільний політ. Щасти, командире!", 3)
    last = time.monotonic()
    while True:
        now = time.monotonic()
        dt = min(0.08, now - last)
        last = now
        for ev in pygame.event.get():
            if ev.type == pygame.QUIT:
                return "quit"
            hat = getattr(ev, "hat", False)
            key = ev.key if ev.type in (pygame.KEYDOWN, pygame.KEYUP) else None
            if key in (pygame.K_SPACE, pygame.K_EQUALS) or (hat and key == pygame.K_1):
                key = "fast"
            elif key in (pygame.K_SLASH, pygame.K_MINUS) or (hat and key == pygame.K_2):
                key = "slow"
            elif key == pygame.K_LEFTBRACKET:
                key = pygame.K_LEFT
            elif key == pygame.K_RIGHTBRACKET:
                key = pygame.K_RIGHT
            elif key in (pygame.K_a, pygame.K_RETURN, pygame.K_KP_ENTER):
                key = "fire"
            if ev.type == pygame.KEYDOWN:
                if key == pygame.K_ESCAPE or (hat and ev.key == pygame.K_3):
                    game.keys.clear()
                    game.music.stop(300)
                    game.engine.stop()
                    r = pause(game)
                    last = time.monotonic()
                    if r == "quit":
                        return "quit"
                elif key == pygame.K_TAB:
                    game.toggle_style()
                elif key == pygame.K_c:
                    toggle_autodock(game)
                elif key == pygame.K_m:
                    game.fire_missile()
                elif key == pygame.K_e:
                    game.ecm()
                elif key == pygame.K_v:
                    game.set_view(game.view + 1)
                elif key in (pygame.K_F1, pygame.K_F2, pygame.K_F3, pygame.K_F4):
                    game.set_view((pygame.K_F1, pygame.K_F2, pygame.K_F3, pygame.K_F4).index(key))
                elif key == pygame.K_g:
                    game.keys.clear()
                    game.engine.stop()
                    chart(game)
                    last = time.monotonic()
                elif key == pygame.K_h:
                    start_hyper(game)
                elif key == pygame.K_j:
                    start_jump(game)
                elif key == pygame.K_i:
                    game.invert = not game.invert
                    game.conf["invert"] = game.invert
                    save_conf(game.conf)
                    game.say("Тангаж: " + ("↑ - ніс угору" if game.invert else "↑ - ніс униз"), 2)
                else:
                    game.keys.add(key)
            elif ev.type == pygame.KEYUP:
                game.keys.discard(key)
        r = game.update(dt)
        game.engine.set(1.0 if game.jump_t > 0 else game.speed / MAX_SPEED, on=r is None)
        if r == "hyper":
            hyperspace(game)
            last = time.monotonic()
            continue
        if game.autodock:
            if not game.dock_music:                    # the waltz once from the start for this approach
                game.music.start()
                game.dock_music = True
        else:
            game.dock_music = False
            if r != "docked":
                game.music.stop()
        if r == "docked":
            lcd.play("win")
            tunnel(game, True)
            return "docked"
        if r == "dead":
            explode(game)
            if "capsule" in game.equip:
                rescued(game)
                return "rescued"
            return "dead"
        game.draw(dt)
        clock.tick(30)


def rescued(game):
    """The escape capsule got us out: a new ship from the insurance, the cargo and the capsule lost."""
    game.equip.discard("capsule")
    game.cargo = [0] * len(galaxy.GOODS)
    if game.world.deep:
        game.world = World(game.system())
    t0 = time.monotonic()
    f = gfx.font("DejaVuSans-Bold.ttf", 14)
    fs = gfx.font("DejaVuSansCondensed.ttf", 11)
    while time.monotonic() - t0 < 3.5:
        pygame.event.pump()
        c = screen_colours(game)
        frame.fill(c["bg"])
        y = 100
        for text, ff, col in (("РЯТУВАЛЬНА КАПСУЛА", f, c["sel"]), ("Вас підібрали й доставили на станцію", fs, c["hi"]),
                              ("«%s». Страховка дала новий корабель;" % game.system().name, fs, c["hi"]),
                              ("вантаж і капсула втрачені.", fs, c["lo"])):
            img = gfx.fit(ff.render(text, True, col))
            frame.blit(img, (W / 2 - img.get_width() / 2, y))
            y += img.get_height() + 6
        show()
        clock.tick(10)


def jump_dist(game):
    """Light years to the target - from between the stars, half the way is behind us."""
    d = game.system().dist(game.gal[game.target])
    return d * 0.5 if game.world.deep else d


def start_hyper(game):
    if game.hyper_t is not None:
        game.hyper_t = None
        game.say("Гіперстрибок скасовано", 2)
        return
    if game.target is None:
        game.say("Оберіть ціль на карті: g", 2)
        lcd.play("error")
        return
    d = jump_dist(game)
    if d > game.fuel:
        game.say("Замало палива: %.1f з %.1f св. р." % (game.fuel, d), 2.5)
        lcd.play("error")
        return
    game.hyper_t = game.t + HYPER_COUNT
    game.sfx.play("lock")


def galactic_jump(game):
    if "galhyper" not in game.equip:
        game.say("Немає галактичного гіперприводу", 2)
        lcd.play("error")
        return
    game.equip.discard("galhyper")
    hyperspace(game, galactic=True)


def start_jump(game):
    if game.mass_locked():
        game.say("Масова блокада: поруч щось велике", 2)
        lcd.play("error")
        return
    game.jump_t = 8.0
    game.sfx.play("jump")


def toggle_autodock(game):
    game.autodock = not game.autodock
    game.ap_phase = 0
    if game.autodock:
        if length(game.world.st_pos - game.pos) > SAFE_ZONE:
            game.autodock = False
            game.say("Станція поза зоною", 2)
            lcd.play("error")
            return
        game.say("Комп'ютер стикування увімкнено", 2)
        lcd.play("check")
    else:
        game.say("Комп'ютер стикування вимкнено", 2)


def pause(game):
    while True:
        items = ["Продовжити", "Огляд: " + VIEWS[game.view].split()[0].lower(),
                 "Комп'ютер стикування: " + ("увімк" if game.autodock else "вимк"),
                 "Галактична карта", "Гіперстрибок" + (" - скасувати" if game.hyper_t is not None else ""),
                 "Стрибковий двигун"] + (["Галактичний стрибок"] if "galhyper" in game.equip else []) + [
                 "Вигляд: " + STYLE_NAMES[game.style],
                 "Тангаж: " + ("↑ угору" if game.invert else "↑ униз"), "Вийти в меню"]
        r = ask(game, items, "ПАУЗА", back=0)
        if r in (0, None):
            return None
        if r == 1:
            game.set_view(game.view + 1)
            game.draw(0.0)
            continue
        if r == 2:
            toggle_autodock(game)
            return None
        if r == 3:
            chart(game)
            return None
        if r == 4:
            start_hyper(game)
            return None
        if r == 5:
            start_jump(game)
            return None
        if "galhyper" in game.equip:
            if r == 6:
                galactic_jump(game)
                return None
            r -= 1
        if r == 6:
            game.toggle_style()
            game.draw(0.0)
        elif r == 7:
            game.invert = not game.invert
            game.conf["invert"] = game.invert
            save_conf(game.conf)
        elif r == 8:
            return "quit"


def explode(game):
    """Our ship blows apart; the camera leaves it, circles the wreck from all sides, then draws back while
    what is left of the ship drifts off into the dark."""
    game.music.stop(200)
    game.sfx.play("explosion")
    w = game.world
    me = Ship("chumak", game.pos, game.R.copy(), game.speed * 0.3, "wreck")
    blast = Blast(me, random.Random(int(game.t * 1000)), life=12.0, spread=0.35)   # the wreck stays together
    w.blasts.append(blast)
    up = game.R[:, 1].copy()
    side, back = game.R[:, 0].copy(), -game.R[:, 2].copy()
    f = gfx.font("DejaVuSans-Bold.ttf", 16)
    fs = gfx.font("DejaVuSansCondensed.ttf", 11)
    game.keys.clear()
    game.autodock = False
    game.view = 0                                      # the circling camera is a front view
    game.speed = 0.0
    game.roll = game.pitch = game.yaw = 0.0
    t0 = time.monotonic()
    last = t0
    while True:
        now = time.monotonic()
        t, dt = now - t0, min(0.08, now - last)
        last = now
        skip = False
        for ev in pygame.event.get():
            if ev.type == pygame.KEYDOWN and t > 2.5:
                skip = True
        if t > 9.0 or skip:
            break
        w.update(dt)
        w.update_ships(dt, game.pos)
        game.t += dt
        centre = blast.pos + blast.vel * blast.age
        th = 0.6 + t * 0.75                                  # round the wreck...
        d = 260 + 50 * t + max(0.0, t - 4.5) ** 2 * 200      # ...then away from it
        cam = centre + (side * math.cos(th) + back * math.sin(th)) * d + up * d * (0.25 + 0.2 * math.sin(t * 0.6))
        game.pos = cam
        game.R = basis(centre - cam, up)
        frame.fill((0, 0, 0))
        game.draw_view(frame, dt, overlay=False)
        view = frame.subsurface((0, 0, W, VH))
        if t < 0.15:
            view.fill((255, 255, 255) if game.style == "wire" else (255, 220, 160), special_flags=pygame.BLEND_ADD)
        if t > 0.8:
            img = gfx.fit(f.render("КОРАБЕЛЬ ЗНИЩЕНО", True, (255, 120, 90) if game.style != "wire" else gfx.WIRE))
            view.blit(img, (W / 2 - img.get_width() / 2, 8))
        if t > 2.5:
            img = gfx.fit(fs.render("будь-яка клавіша", True, (150, 160, 190) if game.style != "wire" else gfx.WIRE_DIM))
            view.blit(img, (W / 2 - img.get_width() / 2, VH - img.get_height() - 2))
        game.dash[game.style].draw(frame, game.dash_state())
        show()
        clock.tick(30)


def splash():
    """The name at once, before the second or two the galaxy takes to grow."""
    frame.fill((3, 3, 10))
    img = gfx.fit(gfx.font("DejaVuSans-Bold.ttf", 19).render("ЗОРЯНИЙ ТОРГОВЕЦЬ", True, (120, 130, 150)), W - 24)
    frame.blit(img, (W / 2 - img.get_width() / 2, H / 2 - img.get_height() / 2))
    show()


def main():
    splash()
    game = Game()
    while True:
        r = title(game)
        if r == "quit":
            return
        game.new_game() if r == "new" else game.load()
        game.dock()
        while True:
            if station_screen(game) == "quit":
                game.save()
                break
            r = flight(game)
            if r == "rescued":
                game.dock()
                continue
            if r in ("quit", "dead"):                  # what happened since the last docking is lost
                if game.world.deep:
                    game.world = World(game.system())
                break
            game.dock()


if __name__ == "__main__":
    try:
        main()
    finally:
        screen.fill((0, 0, 0))
        lcd.flip()
        lcd.quit()
