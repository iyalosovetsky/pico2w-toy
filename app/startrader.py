"""ЗОРЯНИЙ ТОРГОВЕЦЬ - a space trader in the spirit of the old 8-bit space-trading classics, our own ships
and names, drawn the modern way (dark solid hulls with light trims, glowing lights, lit planets) or the
classic way (white wireframe, a planet of dots); Tab switches.

Stage 1: the flight (roll and pitch, the speed), the cockpit with its dashboard and the scanner, the system's
planet and sun, the station that turns about its slot, traffic coming and going, docking by hand (match the
station's turn, fly in slowly) or by the docking computer - to a waltz, the opening of Strauss's "The Blue
Danube" (public domain, our own synthesized arrangement).

Keys: ← → (or [ ]) - roll, ↑ ↓ - pitch (↑ dives, like a stick; i - the other way), Space / = - faster,
/ / - - slower, a / Enter - the laser, m - a missile at the ship in the sights, c - the docking computer,
Tab - the look, Esc - the pause menu. HAT: the joystick, KEY1 faster,
KEY2 slower, KEY3 - the menu.
"""
import json
import math
import os
import random
import time

import numpy as np
import pygame
import stargfx as gfx                 # before lcd.init(): it keeps pygame's own draw and font
import lcd
import starmusic

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
HP = {"osa": 2, "sokil": 3, "chumak": 4, "mazha": 6, "shulika": 3, "vulyk": 12, "truten": 1, "rocket": 1,
      "kapsula": 1, "kontejner": 1, "asteroid": 3}                 # laser hits a ship takes
LASER_RANGE = 7000.0
LASER_EVERY = 0.16                    # seconds between pulses
MISSILES = 3
SYSTEM = "Ортея"
SYSTEM_INFO = "Сільськогосподарська · Демократія · Тех. рівень 7"


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
        self.target = None


class Blast:
    """A ship blown apart: its faces fly off spinning and cool down, a fireball (modern) or a cloud of dots
    (classic) in the middle."""
    LIFE = 2.2

    def __init__(self, ship, rnd):
        me = ship.me
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
            v = self.vel + N[i] * rnd.uniform(60, 260) + np.array([rnd.uniform(-60, 60) for _ in range(3)])
            ax = unit(np.array([rnd.gauss(0, 1) for _ in range(3)]))
            self.frags.append((c, P - c, v, ax, rnd.uniform(1.5, 6.0), me.base[i]))
        self.dots = np.array([unit(np.array([rnd.gauss(0, 1) for _ in range(3)])) * rnd.uniform(0.3, 1.0)
                              for _ in range(70)]) * self.size * 2.2


class World:
    def __init__(self, seed=7):
        self.rnd = random.Random(seed)
        self.sun_dir = unit(np.array((0.9, 0.55, -0.35)))
        self.sun_pos = self.sun_dir * SUN_DIST
        self.st_dir = unit(np.array((0.35, 0.25, -1.0)))
        self.st_pos = self.st_dir * (PLANET_R + 28000)
        self.st_base = basis(-self.st_dir, np.array((0.0, 1.0, 0.0)))   # the model's +z to the planet
        self.slot_n = self.st_dir.copy()                                # the slot looks away from it
        self.st_angle = 0.0
        self.st_R = self.st_base
        self.station = gfx.mesh("station")
        self.planet = gfx.Planet("earth", 11)
        self.stars = gfx.starfield()
        self.ships = []
        self.blasts = []
        self.events = []                  # ("boom", ship) - for the game's sounds and messages
        self.spawn_t = 2.0
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
            if length(p - player_pos) > 8000 and length(p) > PLANET_R * 1.3:
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

    def update_ships(self, dt, player_pos):
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
            if s.role == "drift":
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
            elif s.role == "missile":
                tg = s.target
                if tg is None or tg.gone or s.age > 14:
                    self.destroy(s)                                    # lost its target: self-destructs
                    continue
                s.R = turn_to(s.R, unit(tg.pos - s.pos), 2.4, dt)
                s.speed = min(3000.0, s.speed + 1800 * dt)
                if length(tg.pos - s.pos) < tg.me.radius * 0.8 + 60:
                    self.destroy(tg)
                    self.destroy(s)
                    continue
            elif s.role == "patrol":
                s.phase += dt * 700 / 3800
                s.R = turn_to(s.R, unit(self.patrol_point(s.phase + 0.35) - s.pos), 0.8, dt)
            if s.role not in ("drift", "missile"):                         # keep clear of the player
                d = player_pos - s.pos
                dist = length(d)
                if dist < 1000 and np.dot(d, s.R[:, 2]) > 0:
                    s.R = turn_to(s.R, unit(-d + s.R[:, 2] * dist * 0.5), 1.4, dt)
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

    def update_blasts(self, dt):
        for b in self.blasts:
            b.age += dt
        self.blasts = [b for b in self.blasts if b.age < Blast.LIFE]

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
        self.world = World()
        self.music = starmusic.Music()
        self.sfx = starmusic.Sfx()
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
        self.laser_temp = 0.0
        self.overheat = False
        self.fire_t = 0.0
        self.beam_t = -1.0
        self.beam_end = None
        self.beam_hit = False
        self.missiles = MISSILES
        self.lock = None

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
        w.update_ships(dt, self.pos)
        self.weapons(dt)
        # recharge: the banks slowly, the shields from the banks
        self.energy = min(4.0, self.energy + 0.03 * dt)
        for sh in ("fs", "as_"):
            v = getattr(self, sh)
            if v < 1 and self.energy > 0.2:
                d = min(1 - v, 0.06 * dt)
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
        # the planet
        alt = length(self.pos) - PLANET_R
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
            if s.role == "missile":
                continue
            d = s.pos - self.pos
            L = length(d)
            if L < 1 or L > reach:
                continue
            c = float(np.dot(d, self.R[:, 2])) / L
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
        for kind, ship in w.events:                    # what blew up since the last step
            if kind == "boom":
                self.sfx.play("boom" if ship.kind != "rocket" else "zap")
                if ship.kind != "rocket":
                    self.say("Знищено: %s" % gfx.TYPES[ship.kind][0], 2)
        w.events.clear()

    def shoot(self):
        """One pulse: along the nose, the nearest ship it passes through takes a hit (the station stops it)."""
        self.fire_t = LASER_EVERY
        self.laser_temp += 0.065
        if self.laser_temp >= 1.0:
            self.overheat = True
            self.say("Лазер перегрівся!", 1.5)
        self.energy -= 0.012
        self.sfx.play("laser")
        RT = self.R.T
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
        self.beam_end = self.pos + self.R[:, 2] * bz
        self.beam_hit = best is not None or bz < LASER_RANGE
        if best is not None:
            best.hp -= 1
            self.sfx.play("zap")
            if best.hp <= 0:
                self.world.destroy(best)

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
        m = Ship("rocket", self.pos + self.R[:, 2] * 140 - self.R[:, 1] * 30, self.R.copy(),
                 self.speed + 500, "missile")
        m.target = tg
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
        return self.R.T @ R, self.R.T @ (pos - self.pos)

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
        return d2 < PLANET_R * PLANET_R

    def draw_view(self, surf, dt, overlay=True):
        st = self.style
        w = self.world
        spin = abs(self.roll) / ROLL_MAX + abs(self.pitch) / PITCH_MAX + abs(self.yaw) / PITCH_MAX
        self.slow = 0.8 * self.slow + 0.2 * (dt > 0.045)
        rough = spin > 0.6 or self.slow > 0.5
        w.planet.gap = 0.3 if rough else 0.12
        surf.fill((0, 0, 0) if st == "wire" else (3, 3, 10), (0, 0, W, VH))
        view = surf.subsurface((0, 0, W, VH))
        gfx.draw_stars(view, w.stars, self.R, F, CX, CY, st)
        RT = self.R.T
        # the sun, unless the planet is in the way
        sc = RT @ (w.sun_pos - self.pos)
        sd = length(sc)
        # in front only (near 90 degrees off the nose x / z blows up: a glow ten thousand pixels wide once
        # froze the game for seconds), its true size from the distance, and only when it is on the screen
        if sc[2] > sd * 0.3 and not self.hidden_by_planet(w.sun_pos):
            sx, sy, sr = CX + sc[0] * F / sc[2], CY - sc[1] * F / sc[2], SUN_R * F / sd
            if -5 * sr - 40 < sx < W + 5 * sr + 40 and -5 * sr - 40 < sy < VH + 5 * sr + 40:
                gfx.draw_sun(view, sx, sy, sr, st, self.t)
        # the planet
        pc = RT @ (-self.pos)
        dist = length(pc)
        if pc[2] > 0:
            r = PLANET_R * F / math.sqrt(max(dist * dist - PLANET_R * PLANET_R, 1.0)) if dist > PLANET_R else 1e5
            Ls = RT @ w.sun_dir                    # from the planet towards the sun
            w.planet.draw(view, CX + pc[0] * F / pc[2], CY - pc[1] * F / pc[2], min(r, 4000), Ls, st)
        # the station and the ships, far to near
        objs = []
        for s in w.ships:
            objs.append((s.me, s.pos, s.R))
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
        gfx.stardust(view, self.dust, dt, self.speed, self.roll, self.pitch, self.yaw, F, CX, CY, st)
        if not overlay:
            return
        self.draw_beams(view)
        self.draw_lock(view)
        col = gfx.WIRE if st == "wire" else (220, 225, 235)
        for dx, dy in ((-1, 0), (1, 0), (0, -1), (0, 1)):
            gfx.line(view, col, (CX + dx * 6, CY + dy * 6), (CX + dx * 16, CY + dy * 16))
        img = self.fonts["label"].render("Передній огляд", True, col)
        view.blit(img, (W / 2 - img.get_width() / 2, 4))
        self.draw_dock_hint(view)
        if self.msg and self.t < self.msg_t:
            img = self.fonts["msg"].render(self.msg, True, (255, 210, 90) if st != "wire" else gfx.WIRE)
            view.blit(img, (W / 2 - img.get_width() / 2, VH - 34))
        if self.autodock:
            img = self.fonts["small"].render("КОМП'ЮТЕР СТИКУВАННЯ", True, (120, 220, 255) if st != "wire" else gfx.WIRE)
            view.blit(img, (W / 2 - img.get_width() / 2, 18))

    def project(self, p):
        c = self.R.T @ (p - self.pos)
        if c[2] < gfx.NEAR:
            return None
        return CX + c[0] * F / c[2], CY - c[1] * F / c[2], float(c[2])

    def draw_blast(self, view, b):
        wire = self.style == "wire"
        a = b.age
        life = Blast.LIFE
        centre = b.pos + b.vel * a
        pc = self.project(centre)
        if pc is None or pc[2] > 40000:
            return
        if wire:                                       # the old way: a cloud of dots flying apart
            col = gfx.WIRE if a < life * 0.6 else gfx.WIRE_DIM
            P = (centre + b.dots * (0.25 + a)) - self.pos
            C = P @ self.R
            ok = C[:, 2] > gfx.NEAR
            for x, y, z in C[ok].tolist():
                sx, sy = CX + x * F / z, CY - y * F / z
                if 0 <= sx < W and 0 <= sy < VH:
                    view.fill(col, (int(sx), int(sy), 2, 2))
        fade = 1 - a / life
        for c0, offs, v, ax, spin, base in b.frags:
            Rm = rodrigues(ax, spin * a)
            P = (c0 + v * a) + offs @ Rm.T - self.pos
            C = P @ self.R
            if C[:, 2].min() < gfx.NEAR:
                continue
            pts = [(CX + x * F / z, CY - y * F / z) for x, y, z in C.tolist()]
            if wire:
                gfx.lines(view, gfx.WIRE if a < life * 0.6 else gfx.WIRE_DIM, True, pts, 1)
            else:
                hot = gfx.mix((255, 190, 90), base, a / 0.7)
                gfx.fill_poly(view, gfx.shade(hot, 0.25 + 0.9 * fade), pts)
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
            return
        if np.dot(self.R[:, 2], -w.slot_n) < 0.7:
            return
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
        view.blit(t1, (cx - r - 6 - t1.get_width(), VH - 14))
        view.blit(t2, (cx + r + 6, VH - 14))

    def dash_state(self):
        w = self.world
        RT = self.R.T
        blips = []
        for s in w.ships + [None]:
            p, col = (s.pos, s.colour) if s else (w.st_pos, (120, 255, 140))
            c = RT @ (p - self.pos)
            bx, by = c[0] / SCAN_RANGE, -c[2] / SCAN_RANGE
            if bx * bx + by * by < 1:
                blips.append((bx, by, c[1] / SCAN_RANGE, col if self.style != "wire" else
                              ((190, 255, 200) if s is None else gfx.WIRE)))
        dist_st = length(w.st_pos - self.pos)
        safe = dist_st < SAFE_ZONE
        tgt = w.st_pos if safe else np.zeros(3)
        d = unit(RT @ (tgt - self.pos))
        alt = (length(self.pos) - PLANET_R) / PLANET_R
        en = [clamp(self.energy - i, 0, 1) for i in range(4)]
        return dict(fs=self.fs, as_=self.as_, fv=1.0, ct=0.1, lt=min(1.0, self.laser_temp), al=clamp(alt, 0, 1),
                    sp=self.speed / MAX_SPEED, missiles=self.missiles,
                    rl=self.roll / ROLL_MAX, dc=self.pitch / PITCH_MAX, en=en, blips=blips,
                    compass=(d[0], d[1], d[2] > 0), safe=safe, t=self.t, **{"as": self.as_})

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


def ask(game, items, title=None, sel=0, back=None):
    """A small menu over the current frame; returns the chosen index or back (Esc)."""
    snap = frame.copy()
    f = gfx.font("DejaVuSans-Bold.ttf", 12)
    wire = game.style == "wire"
    while True:
        frame.blit(snap, (0, 0))
        h = 28 + 22 * len(items)
        box = pygame.Rect(W / 2 - 120, VH / 2 - h / 2, 240, h)
        sh = pygame.Surface(box.size, pygame.SRCALPHA)
        sh.fill((0, 0, 0, 220) if wire else (8, 12, 26, 225))
        frame.blit(sh, box.topleft)
        gfx.rect(frame, gfx.WIRE if wire else (90, 190, 255), box, 1)
        y = box.y + 8
        if title:
            img = f.render(title, True, gfx.WIRE if wire else (240, 232, 214))
            frame.blit(img, (W / 2 - img.get_width() / 2, y))
            y += 20
        for i, it in enumerate(items):
            col = (gfx.WIRE if wire else (255, 210, 90)) if i == sel else (gfx.WIRE_DIM if wire else (170, 190, 220))
            img = f.render(("▶ " if i == sel else "") + it, True, col)
            frame.blit(img, (W / 2 - img.get_width() / 2, y + i * 22))
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
    """The title: the trader turning in the frame, the name; Enter - start, Tab - the look, Esc - out."""
    t0 = time.monotonic()
    me = gfx.mesh("chumak")
    fbig = gfx.font("DejaVuSans-Bold.ttf", 19)
    fmono = gfx.font("DejaVuSansMono-Bold.ttf", 13)
    fs = gfx.font("DejaVuSansCondensed-Bold.ttf", 12)
    fm = gfx.font("DejaVuSansMono.ttf", 11)
    while True:
        for ev in pygame.event.get():
            if ev.type == pygame.QUIT:
                return "quit"
            if ev.type != pygame.KEYDOWN:
                continue
            hat = getattr(ev, "hat", False)
            if ev.key in (pygame.K_RETURN, pygame.K_KP_ENTER, pygame.K_SPACE) or (hat and ev.key == pygame.K_1):
                lcd.play("select")
                return "start"
            if ev.key == pygame.K_TAB or (hat and ev.key == pygame.K_2):
                game.toggle_style()
            elif ev.key == pygame.K_ESCAPE or (hat and ev.key == pygame.K_3):
                return "quit"
        if game.world.planet.prewarm():                # the planet's lit masters, one a frame, then the sounds
            game.music.ready()
            game.sfx.ready()
        t = time.monotonic() - t0
        wire = game.style == "wire"
        draw_backdrop(game, t)
        if not wire:
            Ls = gfx.norm((-0.8, 0.5, -0.2))
            game.world.planet.draw(frame, 300, 300, 120, Ls, "modern")
        gfx.draw_mesh(frame, me, spin_matrix(t), np.array((0.0, 0.0, 300.0)), F, W / 2, H / 2 + 6,
                      np.array(HANGAR_L), game.style)
        if wire:
            gfx.rect(frame, gfx.WIRE, (8, 8, W - 16, H - 16), 1)
            img = fmono.render("--- ЗОРЯНИЙ ТОРГОВЕЦЬ ---", True, gfx.WIRE)
            frame.blit(img, (W / 2 - img.get_width() / 2, 20))
            for i, s in enumerate(("Натисніть пробіл, командире", "Tab - сучасний вигляд")):
                img = fm.render(s, True, gfx.WIRE)
                frame.blit(img, (W / 2 - img.get_width() / 2, H - 52 + i * 16))
        else:
            gfx.rect(frame, (200, 196, 180), (8, 8, W - 16, H - 16), 1)
            img = fbig.render("ЗОРЯНИЙ ТОРГОВЕЦЬ", True, (240, 232, 214))
            frame.blit(img, (W / 2 - img.get_width() / 2, 20))
            for x in range(30, W - 30, 6):
                gfx.line(frame, (90, 190, 255), (x, 46), (x + 3, 46))
            for i, s in enumerate(("Натисніть пробіл, командире", "Tab - класичний вигляд · Esc - вихід")):
                img = fs.render(s, True, (230, 230, 240) if i == 0 else (150, 200, 240))
                frame.blit(img, (W / 2 - img.get_width() / 2, H - 52 + i * 18))
        show()
        clock.tick(30)


def ships_book(game):
    """The ship identification: each type turning, its name and role; ← → - the next, Esc - back."""
    kinds = list(gfx.TYPES)
    i = 0
    t0 = time.monotonic()
    fn = gfx.font("DejaVuSans-Bold.ttf", 16)
    fs = gfx.font("DejaVuSansCondensed.ttf", 11)
    while True:
        for ev in pygame.event.get():
            if ev.type == pygame.QUIT:
                return
            if ev.type != pygame.KEYDOWN:
                continue
            hat = getattr(ev, "hat", False)
            if ev.key in (pygame.K_RIGHT, pygame.K_DOWN, pygame.K_RIGHTBRACKET):
                i = (i + 1) % len(kinds)
                lcd.play("click")
            elif ev.key in (pygame.K_LEFT, pygame.K_UP, pygame.K_LEFTBRACKET):
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
        gfx.draw_mesh(frame, me, spin_matrix(t, -0.35), np.array((0.0, 0.0, z)), F, W / 2, H / 2 - 10,
                      np.array(HANGAR_L), game.style)
        name, role = gfx.TYPES[kinds[i]][:2]
        hdr = fs.render("РОЗПІЗНАВАННЯ КОРАБЛІВ  %d / %d" % (i + 1, len(kinds)), True,
                        gfx.WIRE if wire else (150, 200, 240))
        frame.blit(hdr, (W / 2 - hdr.get_width() / 2, 10))
        img = fn.render(name, True, gfx.WIRE if wire else (240, 232, 214))
        frame.blit(img, (W / 2 - img.get_width() / 2, H - 70))
        img = fs.render(role, True, gfx.WIRE if wire else (170, 190, 220))
        frame.blit(img, (W / 2 - img.get_width() / 2, H - 48))
        img = fs.render("← → - інший · Esc - назад", True, gfx.WIRE_DIM if wire else (110, 130, 160))
        frame.blit(img, (W / 2 - img.get_width() / 2, H - 22))
        show()
        clock.tick(30)


def station_screen(game):
    """Docked: the station's name and the system, our ship in the hangar; launch / the ship book / the look /
    out. Returns "launch" or "quit"."""
    sel = 0
    t0 = time.monotonic()
    game.music.stop(2500)                              # the waltz fades as we roll into the hangar
    me = gfx.mesh("chumak")
    fn = gfx.font("DejaVuSans-Bold.ttf", 15)
    fi = gfx.font("DejaVuSansCondensed.ttf", 11)
    fm = gfx.font("DejaVuSans-Bold.ttf", 12)
    while True:
        items = ["Злетіти", "Розпізнавання кораблів", "Вигляд: " + STYLE_NAMES[game.style], "Вийти"]
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
                    ships_book(game)
                elif sel == 2:
                    game.toggle_style()
                else:
                    return "quit"
            elif ev.key == pygame.K_ESCAPE or (hat and ev.key == pygame.K_3):
                return "quit"
        if game.world.planet.prewarm():
            game.music.ready()
            game.sfx.ready()
        t = time.monotonic() - t0
        wire = game.style == "wire"
        draw_backdrop(game, t)
        if not wire:                                   # the hangar's floor: a lit grid
            for k in range(9):
                y = 150 + k * k * 1.6
                gfx.line(frame, (24 + k * 3, 34 + k * 4, 60 + k * 5), (0, y), (W, y))
            for k in range(-8, 9):
                gfx.line(frame, (30, 44, 74), (W / 2 + k * 6, 150), (W / 2 + k * 40, 280))
        gfx.draw_mesh(frame, me, spin_matrix(t), np.array((0.0, 0.0, 330.0)), F, W / 2, 130,
                      np.array(HANGAR_L), game.style)
        hdr = fn.render("Станція «%s»" % SYSTEM, True, gfx.WIRE if wire else (240, 232, 214))
        frame.blit(hdr, (W / 2 - hdr.get_width() / 2, 10))
        img = fi.render(SYSTEM_INFO, True, gfx.WIRE if wire else (150, 200, 240))
        frame.blit(img, (W / 2 - img.get_width() / 2, 30))
        for i, it in enumerate(items):
            on = i == sel
            col = (gfx.WIRE if wire else (255, 210, 90)) if on else (gfx.WIRE_DIM if wire else (170, 190, 220))
            img = fm.render(("▶ " if on else "") + it, True, col)
            frame.blit(img, (W / 2 - img.get_width() / 2, 214 + i * 22))
        show()
        clock.tick(30)


def flight(game):
    """Out of the slot, fly until docked (True) or dead / quit to the menu (False)."""
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
        if game.autodock:
            game.music.start()
        elif r != "docked":
            game.music.stop()
        if r == "docked":
            lcd.play("win")
            tunnel(game, True)
            return "docked"
        if r == "dead":
            game.draw(dt)
            explode(game)
            return "dead"
        game.draw(dt)
        clock.tick(30)


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
        items = ["Продовжити", "Комп'ютер стикування: " + ("увімк" if game.autodock else "вимк"),
                 "Вигляд: " + STYLE_NAMES[game.style], "Тангаж: " + ("↑ угору" if game.invert else "↑ униз"),
                 "Вийти в меню"]
        r = ask(game, items, "ПАУЗА", back=0)
        if r in (0, None):
            return None
        if r == 1:
            toggle_autodock(game)
            return None
        if r == 2:
            game.toggle_style()
            game.draw(0.0)
        elif r == 3:
            game.invert = not game.invert
            game.conf["invert"] = game.invert
            save_conf(game.conf)
        elif r == 4:
            return "quit"


def explode(game):
    game.music.stop(200)
    game.sfx.play("explosion")
    t0 = time.monotonic()
    snap = frame.copy()
    f = gfx.font("DejaVuSans-Bold.ttf", 16)
    rnd = random.Random(3)
    bits = [(rnd.uniform(-1, 1), rnd.uniform(-1, 1), rnd.uniform(40, 160)) for _ in range(60)]
    while time.monotonic() - t0 < 3.0:
        pygame.event.pump()
        t = time.monotonic() - t0
        frame.blit(snap, (0, 0))
        view = frame.subsurface((0, 0, W, VH))
        if t < 0.25:
            view.fill((255, 255, 255) if game.style == "wire" else (255, 220, 160))
        for x, y, v in bits:
            p = (CX + x * v * t, CY + y * v * t * 0.7)
            c = gfx.WIRE if game.style == "wire" else gfx.mix((255, 230, 120), (120, 30, 10), t / 3)
            view.fill(c, (int(p[0]), int(p[1]), 2, 2))
        img = f.render("КОРАБЕЛЬ ЗНИЩЕНО", True, (255, 120, 90) if game.style != "wire" else gfx.WIRE)
        view.blit(img, (W / 2 - img.get_width() / 2, VH / 2 - 10))
        show()
        clock.tick(30)


def main():
    game = Game()
    while True:
        if title(game) == "quit":
            return
        while True:
            if station_screen(game) == "quit":
                break
            r = flight(game)
            if r == "quit":
                break
            if r == "dead":
                game.world = World()
                break


if __name__ == "__main__":
    try:
        main()
    finally:
        screen.fill((0, 0, 0))
        lcd.flip()
        lcd.quit()
