"""ДІМ: the house plan from above, floor by floor, with the Home Assistant devices on it.

The rooms and the furniture come from the house3d plan server (the same plan as the 3D model, kept on the
device for the times without the network), the devices sit where the 3D model shows them - the lamps,
the soundbar, the projector with its screen, the smart speaker, the weather board; their states and the
controls - Home Assistant over its WebSocket API (hawire.py). A room glows while a lamp in it is on, the
projector's beam reaches the screen while it is on.

The HA address and a long-lived token: ~/.config/lcdtoy/house.env (mode 600, see config/house.env.example):
    HA_URL=http://10.80.39.78:8123,https://hass.ibotz.space     (tried in turn)
    HA_TOKEN=...                 (better from an HA user without admin rights)
    PLAN_URL=http://10.80.39.14:8095
    CONFIRM=switch.some_gate     (more entities that ask before they act)

The floor: arrows - the room that way, Enter - into the room, Space - the room's lights on / off,
Tab / PgDn / PgUp or 0-3 - the floor, r - reload the plan, F1 - keys, Esc - exit.
In a room (drawn bigger): arrows or Tab / Shift+Tab - its devices, Space - the device's action (a lamp or a
socket - on / off; a cover - open / close; the speaker - as a tap on it in the 3D model: playing - pause, just
stopped - on, long quiet - it says the time, again - the radio; the projector, the soundbar - on / off),
+ / - - brightness, volume, position, the target temperature, Enter or i - the device's card, Esc - out.
The card: ↑ ↓ - a line, ← → or + - - its value (brightness, colour, volume, source, station, position, the
target temperature), Enter or Space - do it, Esc - back; sensors show their last 24 hours. «Сказати…» on a
speaker - type a phrase (Tab - УКР / ENG) and HA's TTS says it there.
HAT: the stick, PRESS - into the room / the card, KEY1 - the floor (in a room - the next device),
KEY2 - the action, KEY3 - back.
Gates, doors and locks ask first («Ні» chosen until ← →).
"""
import datetime
import math
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import pygame  # noqa: E402
import lcd  # noqa: E402
import hawire  # noqa: E402
from hawire import domain  # noqa: E402

BG, FG, DIM = (0, 0, 0), (230, 230, 230), (125, 125, 130)
ACCENT, RED, GREEN, BLUE, CYAN = (255, 200, 0), (240, 90, 80), (90, 215, 110), (100, 165, 255), (90, 210, 230)
ROOM, ROOM_EDGE, ROOM_TEXT = (26, 31, 40), (95, 105, 122), (150, 160, 175)
OUT, OUT_EDGE = (30, 26, 22), (80, 70, 58)
LIT, LIT_EDGE, LIT_TEXT = (88, 72, 26), (205, 170, 75), (255, 228, 150)
FONT_DIR = "/usr/share/fonts/truetype/dejavu/"
BIG = lcd.S > 1

TOP, BAR = 14, 111                     # the map between the floor tabs and the bottom bar (logical pixels)

STATE_UK = {"on": "увімк.", "off": "вимк.", "unavailable": "недоступний", "unknown": "невідомо",
            "open": "відкрито", "closed": "закрито", "opening": "відкривається", "closing": "закривається",
            "playing": "грає", "paused": "пауза", "idle": "тиша", "standby": "сплячий", "buffering": "буферизація",
            "locked": "зачинено", "unlocked": "відчинено", "locking": "зачиняється", "unlocking": "відчиняється",
            "jammed": "заклинило", "heat": "обігрів", "cool": "охолодження", "auto": "авто", "dry": "осушення",
            "fan_only": "вентилятор", "heat_cool": "авто", "armed_away": "охорона", "armed_home": "охорона вдома",
            "disarmed": "знято з охорони", "triggered": "ТРИВОГА", "docked": "на базі", "cleaning": "прибирає",
            "returning": "повертається"}
BIN_UK = {"motion": ("рух", "тихо"), "occupancy": ("є хтось", "нікого"), "presence": ("є хтось", "нікого"),
          "door": ("відчинено", "зачинено"), "window": ("відчинено", "зачинено"), "opening": ("відчинено", "зачинено"),
          "garage_door": ("відчинено", "зачинено"), "moisture": ("ПРОТІКАННЯ", "сухо"), "smoke": ("ДИМ", "норма"),
          "gas": ("ГАЗ", "норма"), "carbon_monoxide": ("CO!", "норма")}
HVAC_UK = {"off": "Вимк", "heat": "Обігрів", "cool": "Холод", "auto": "Авто", "heat_cool": "Авто", "dry": "Осуш.",
           "fan_only": "Вент."}
TOGGLE = {"light", "switch", "fan", "input_boolean", "humidifier"}
DANGER_WORDS = ("vorot", "gate", "garage_door", "ворот", "door", "двер", "хвірт", "lock", "замок")
COLOURS = [("теплий", (255, 147, 41)), ("білий", (255, 255, 255)), ("червоний", (255, 60, 60)),
           ("зелений", (60, 255, 120)), ("синій", (60, 120, 255)), ("фіолетовий", (200, 80, 255)),
           ("рожевий", (255, 80, 180))]
# the 3D model's stations (js/speaker.js); the plan's own list (plan.radio) when it has one
RADIO_DEFAULT = [
    {"name": "Radio ROKS — Classic Rock", "id": "https://online.radioroks.ua/RadioROKS_ClassicRock_HD"},
    {"name": "Radio ROKS", "id": "https://online.radioroks.ua/RadioROKS_HD"},
    {"name": "Radio ROKS — рок-балади", "id": "https://online.radioroks.ua/RadioROKS_Ballads_HD"},
    {"name": "Барди", "id": "https://russianbards.com/stream"},
    {"name": "Italo Disco 80s", "id": "https://cast1.torontocast.com:2130/stream"},
    {"name": "Italo Disco (laut.fm)", "id": "https://italo-disco.stream.laut.fm/italo-disco"},
    {"name": "Мелодія FM — диско", "id": "https://online.melodiafm.ua/MelodiaFM_Disco_HD"},
]
RECENT, SPEECH = 120, 12               # s: «just now»; the spoken time lasts about so long
# supported_features bits a projector's entity needs for a service (the 3D model's avPick)
AVF = {"turn_on": 128, "turn_off": 256, "volume_set": 4, "select_source": 2048, "select_sound_mode": 65536}
# the Ukrainian layout over the US keys: «Сказати…» typed on the PicoCalc
UA = dict(zip("qwertyuiop[]asdfghjkl;'zxcvbnm,./`", "йцукенгшщзхїфівапролджєячсмитьбю.'"))
UA.update({k.upper(): v.upper() for k, v in UA.items() if k.isalpha()})
UA.update({"{": "Х", "}": "Ї", ":": "Ж", '"': "Є", "<": "Б", ">": "Ю", "?": ",", "~": "₴"})
HOURS = ["нуль", "перша", "друга", "третя", "четверта", "п'ята", "шоста", "сьома", "восьма", "дев'ята", "десята",
         "одинадцята", "дванадцята", "тринадцята", "чотирнадцята", "п'ятнадцята", "шістнадцята", "сімнадцята",
         "вісімнадцята", "дев'ятнадцята", "двадцята", "двадцять перша", "двадцять друга", "двадцять третя"]
UNITS = ["", "одна", "дві", "три", "чотири", "п'ять", "шість", "сім", "вісім", "дев'ять", "десять", "одинадцять",
         "дванадцять", "тринадцять", "чотирнадцять", "п'ятнадцять", "шістнадцять", "сімнадцять", "вісімнадцять",
         "дев'ятнадцять"]
TENS = ["", "", "двадцять", "тридцять", "сорок", "п'ятдесят"]
OUTDOOR = {"tree", "path", "flowerbed", "paving", "rockery", "utilitypole", "pergola", "pool", "hangplant",
           "powerinlet", "balcony", "slats"}


def time_text(t=None):
    """«Зараз чотирнадцята година п'ять хвилин» - in words, as the 3D model's speaker says it."""
    d = datetime.datetime.fromtimestamp(t or time.time())
    hh, m = d.hour, d.minute
    hour = "нуль годин" if hh == 0 else HOURS[hh] + " година"
    if m == 0:
        return "Зараз %s рівно" % hour
    num = UNITS[m] if m < 20 else TENS[m // 10] + (" " + UNITS[m % 10] if m % 10 else "")
    u = m % 10
    word = "хвилина" if u == 1 and m != 11 else "хвилини" if 2 <= u <= 4 and not 12 <= m <= 14 else "хвилин"
    return "Зараз %s %s %s" % (hour, num, word)


def font(name, px):
    try:
        return pygame.font.Font(FONT_DIR + name, px / lcd.S if BIG else int(px))
    except (FileNotFoundError, OSError):
        return pygame.font.Font(None, px / lcd.S if BIG else int(px))


def init_fonts():
    """After lcd.init(): it wraps pygame.font for the PicoCalc's scale."""
    global f_tab, f_room, f_name, f_text, f_small, f_val, f_big
    f_tab = font("DejaVuSans-Bold.ttf", 12 if BIG else 7)
    f_room = font("DejaVuSans.ttf", 10 if BIG else 6)
    f_name = font("DejaVuSans-Bold.ttf", 13 if BIG else 8)
    f_text = font("DejaVuSans.ttf", 12 if BIG else 7)
    f_small = font("DejaVuSans.ttf", 10 if BIG else 6)
    f_val = font("DejaVuSans-Bold.ttf", 9 if BIG else 6)
    f_big = font("DejaVuSans-Bold.ttf", 22 if BIG else 12)


def fit(s, f, width):
    if f.size(s)[0] <= width:
        return s
    while s and f.size(s + "…")[0] > width:
        s = s[:-1]
    return s + "…"


def wrap(text, f, width):
    words, lines, cur = str(text).split(), [], ""
    for w in words:
        t = (cur + " " + w).strip()
        if f.size(t)[0] <= width or not cur:
            cur = t
        else:
            lines.append(cur)
            cur = w
    if cur:
        lines.append(cur)
    return [fit(ln, f, width) for ln in lines] or [""]


def friendly(eid, st, names):
    n = (st or {}).get("attributes", {}).get("friendly_name") if st else None
    return n or names.get(eid) or eid.split(".", 1)[-1].replace("_", " ")


def num(v, nd=1):
    try:
        x = float(v)
    except (TypeError, ValueError):
        return str(v)
    return ("%.*f" % (nd, x)).rstrip("0").rstrip(".") if abs(x) < 1000 else "%d" % x


def state_text(eid, st, dc=None, kind=None):
    if not st:
        return "немає даних"
    s, a, d = st.get("state"), st.get("attributes") or {}, domain(eid)
    if s in ("unavailable", "unknown", None):
        return STATE_UK.get(s, "невідомо")
    if kind == "screen":
        if s in ("opening", "closing"):
            return "піднімається" if s == "opening" else "опускається"
        return "опущено" if screen_down(st) else "піднято"
    if d == "sensor":
        unit = a.get("unit_of_measurement")
        return "%s %s" % (num(s), unit) if unit else num(s)
    if d == "binary_sensor":
        pair = BIN_UK.get(a.get("device_class") or dc)
        return (pair[0] if s == "on" else pair[1]) if pair else STATE_UK.get(s, s)
    out = STATE_UK.get(s, s)
    if d == "light" and s == "on" and a.get("brightness") is not None:
        out += " %d%%" % round(a["brightness"] * 100 / 255)
    if d == "cover" and a.get("current_position") is not None and s in ("open", "opening", "closing"):
        out += " %s%%" % a["current_position"]
    if d == "climate" and a.get("current_temperature") is not None:
        out += ", %s°" % a["current_temperature"]
    if d == "media_player" and s not in ("off", "standby"):
        extra = [x for x in (a.get("media_title"), a.get("media_artist"), a.get("source"), a.get("app_name"))
                 if x and x != "Default Media Receiver"]
        if extra:
            out += ": " + " · ".join(dict.fromkeys(str(x) for x in extra))
        if a.get("is_volume_muted"):
            out += " · без звуку"
    return out


def screen_down(st):
    """The projector's screen: «closed» in HA is let down (the 3D model's rollDown)."""
    if not st:
        return False
    p = (st.get("attributes") or {}).get("current_position")
    return p < 50 if p is not None else st.get("state") in ("closed", "closing")


def is_on(eid, st):
    s = (st or {}).get("state")
    d = domain(eid)
    if d == "cover":
        return s in ("open", "opening", "closing")
    if d == "media_player":
        return s not in ("off", "unavailable", "unknown", "standby", None)
    if d == "climate":
        return s not in ("off", "unavailable", "unknown", None)
    if d == "lock":
        return s == "unlocked"
    return s == "on"


def colour(spec, default=(120, 120, 120)):
    try:
        h = str(spec).split()[0].lstrip("#")
        return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4)) if len(h) >= 6 else default
    except (ValueError, IndexError):
        return default


def mix(a, b, k):
    return tuple(round(a[i] * k + b[i] * (1 - k)) for i in range(3))


ARROWS = {pygame.K_UP: (0, -1), pygame.K_DOWN: (0, 1), pygame.K_LEFT: (-1, 0), pygame.K_RIGHT: (1, 0)}


def plus_minus(ev):
    """+1 for «+» (and «=»), -1 for «-», else 0."""
    k, ch = ev.key, getattr(ev, "unicode", "") or ""
    if k in (pygame.K_PLUS, pygame.K_KP_PLUS, pygame.K_EQUALS) or ch == "+":
        return 1
    if k in (pygame.K_MINUS, pygame.K_KP_MINUS) or ch in ("-", "_"):
        return -1
    return 0


class Row:
    """A line of a device's card: «act» (Enter does it), «slider» (← → step it), «choice» (← → pick, Enter
    applies)."""

    def __init__(self, kind, label, **kw):
        self.kind, self.label = kind, label
        self.__dict__.update(kw)


class House:
    def __init__(self, screen):
        self.screen = screen
        init_fonts()
        env = hawire.read_env()
        self.env = env
        self.plans = hawire.PlanSource(env.get("PLAN_URL"))
        self.plans.fetch()
        self.ha = hawire.HA((env.get("HA_URL") or "").split(","), env.get("HA_TOKEN", ""))
        self.confirm_ids = {x.strip() for x in env.get("CONFIRM", "").split(",") if x.strip()}
        cache = hawire.load_ha_cache()
        self.places = cache.get("places") or {}
        self.names = cache.get("names") or {}
        self.classes = cache.get("classes") or {}
        self.roles = cache.get("roles") or {}
        self.plan_gen = self.reg_gen = -1
        self.floor = 0
        self.sel = {}                              # floor id -> the selected entity
        self.rsel = {}                             # floor id -> the selected room (its group)
        self.room = None                           # the room we are in, else None (choosing a room)
        self.view = "map"                          # map / details / confirm / help / say
        self.back_to = "map"
        self.confirm = None                        # (question, domain, service, eid, data)
        self.choice = 0
        self.row = 0                               # the card's line
        self.pick = {}                             # (eid, row label) -> the option being chosen with ← →
        self.toast = None
        self.pending = {}                          # eid -> when an action was sent (drawn as a ring)
        self.mem = {}                              # speaker -> {said, stopped, station}
        self.hist = {}                             # sensor -> {"at", "data": [(t, v)]}
        self.fcast = {"at": -1e9, "data": None}
        self.say_buf, self.say_ua, self.say_eid = "", True, None
        self.dirty = True
        self.last_gen = -1
        self.rebuild()

    # ---------------------------------------------------------------- the data
    @property
    def plan(self):
        return self.plans.plan or {}

    def floors(self):
        return self.plan.get("floors") or []

    def fid(self):
        fl = self.floors()
        return fl[self.floor % len(fl)]["id"] if fl else None

    def rebuild(self):
        """Place the devices again (a new plan, or HA's states and registries came)."""
        self.plan_gen, self.reg_gen = self.plans.gen, self.ha.reg_gen
        if not self.plans.plan:
            return
        if self.ha.reg_gen > 0:
            states = self.ha.snapshot()
            self.places = hawire.placements(self.plan, self.plans.layout, states, self.ha.area_of, self.ha.hidden)
            self.places = {e: v for e, v in self.places.items() if e in states or e.startswith("energy:")}
            self.roles = hawire.find_roles(states, self.plan.get("power"))
            hawire.save_ha_cache(self.places, states, self.roles)
            self.names = {e: v.get("name") or states.get(e, {}).get("attributes", {}).get("friendly_name")
                          for e, v in self.places.items()}
            self.classes = {e: states.get(e, {}).get("attributes", {}).get("device_class") for e in self.places}
            group = hawire.proj_group(states)
            self.ha.subscribe([e for e in self.places if not e.startswith("energy:")] + group +
                              [w for w in states if w.startswith("weather.")][:1] + [e for e in self.roles.values() if e])
        elif not self.places:                      # no HA yet and nothing cached: the plan's own devices
            self.places = hawire.placements(self.plan, self.plans.layout, {}, lambda e: None)
            self.names = {e: v["name"] for e, v in self.places.items() if v.get("name")}
        self.dirty = True

    def devices(self, fid):
        return [(e, v) for e, v in self.places.items() if v.get("f") == fid]

    def rooms(self, fid):
        return [r for r in self.plan.get("rooms") or [] if r.get("floor") == fid and "x" in r and "w" in r]

    def selected(self):
        fid = self.fid()
        devs = dict(self.devices(fid))
        u = self.units(fid).get(self.room) if self.room else None
        if u:
            devs = {e: devs[e] for e in self.members(fid).get(self.room, []) if e in devs}
        e = self.sel.get(fid)
        if e not in devs and devs:
            if u:
                cx, cz = u["cx"], u["cz"]
            else:
                rooms = self.rooms(fid)
                cx = sum(r["x"] + r["w"] / 2 for r in rooms) / max(1, len(rooms))
                cz = sum(r["z"] + r["d"] / 2 for r in rooms) / max(1, len(rooms))
            e = min(devs, key=lambda k: math.hypot(devs[k]["x"] - cx, devs[k]["z"] - cz))
            self.sel[fid] = e
        return e if e in devs else None

    # ---------------------------------------------------------------- the rooms
    def units(self, fid):
        """The rooms as one sees them (the parts of a group together): group -> {name, parts, the bbox, the centre}."""
        U = {}
        for r in self.rooms(fid):
            g = r.get("group") or r["id"]
            u = U.setdefault(g, {"id": g, "parts": [], "name": None, "big": -1})
            u["parts"].append(r)
            if r.get("name") and r["w"] * r["d"] > u["big"]:
                u["name"], u["big"] = r["name"], r["w"] * r["d"]
        for u in U.values():
            P = u["parts"]
            u["x0"], u["z0"] = min(p["x"] for p in P), min(p["z"] for p in P)
            u["x1"], u["z1"] = max(p["x"] + p["w"] for p in P), max(p["z"] + p["d"] for p in P)
            area = sum(p["w"] * p["d"] for p in P) or 1
            u["cx"] = sum((p["x"] + p["w"] / 2) * p["w"] * p["d"] for p in P) / area
            u["cz"] = sum((p["z"] + p["d"] / 2) * p["w"] * p["d"] for p in P) / area
            u["outdoor"] = all(p.get("walls") in (False, "railing") for p in P)
            u["name"] = u["name"] or ("Надворі" if u["outdoor"] else "Кімната")
        return U

    def members(self, fid):
        """Room (group) -> its devices: the room they stand in, else the nearest one."""
        rooms = self.rooms(fid)
        M = {}
        for e, v in self.devices(fid):
            r = self.room_at(rooms, v["x"], v["z"], 0.05)
            if not r and rooms:
                r = min(rooms, key=lambda r: math.hypot(max(r["x"] - v["x"], 0, v["x"] - r["x"] - r["w"]),
                                                        max(r["z"] - v["z"], 0, v["z"] - r["z"] - r["d"])))
            if r:
                M.setdefault(r.get("group") or r["id"], []).append(e)
        for L in M.values():
            L.sort(key=lambda e: (round(self.places[e]["z"] * 2), self.places[e]["x"]))
        return M

    def cur_room(self):
        """The room chosen on the floor (one with devices)."""
        fid = self.fid()
        M = self.members(fid)
        g = self.rsel.get(fid)
        if g not in M and M:
            e = self.sel.get(fid)
            g = next((k for k, L in M.items() if e in L), None) or max(M, key=lambda k: len(M[k]))
            self.rsel[fid] = g
        return g if g in M else None

    def move_room(self, dx, dz):
        fid = self.fid()
        cur = self.cur_room()
        if cur is None:
            return
        U, M = self.units(fid), self.members(fid)
        here = U[cur]
        best = None
        for g in M:
            if g == cur or g not in U:
                continue
            u = U[g]
            # how far the other room lies that way: between the nearest edges, else between the centres
            gap = (u["x0"] - here["x1"]) if dx > 0 else (here["x0"] - u["x1"]) if dx < 0 else \
                (u["z0"] - here["z1"]) if dz > 0 else (here["z0"] - u["z1"])
            vx, vz = u["cx"] - here["cx"], u["cz"] - here["cz"]
            ahead = vx * dx + vz * dz
            if ahead <= 0.1:
                continue
            side = abs(vx * dz - vz * dx)
            score = max(gap, 0) + ahead * 0.3 + side * 1.2
            if best is None or score < best[0]:
                best = (score, g)
        if best:
            self.rsel[fid] = best[1]
            self.dirty = True

    def enter_room(self):
        g = self.cur_room()
        if g is None:
            return self.say("на цьому поверсі немає пристроїв", DIM)
        self.room = g
        self.selected()
        lcd.play("select")

    def room_lights(self, g):
        """Space on a room: its lamps all off if any is on, else all on."""
        fid = self.fid()
        lamps = [e for e in self.members(fid).get(g, []) if self.places[e].get("lamp")]
        if not lamps:
            return self.say("у кімнаті немає світла", DIM)
        if self.ha.status != "connected":
            return self.say(self.offline_text(), RED)
        on = any(is_on(e, self.state(e)) for e in lamps)
        for e in lamps:
            if is_on(e, self.state(e)) == on:
                self.send(domain(e), "turn_off" if on else "turn_on", e, {})
        self.say("світло вимикається" if on else "світло вмикається")

    def room_text(self, g):
        """The room in a line: its lamps, the temperature, what plays, what is open."""
        fid = self.fid()
        L = self.members(fid).get(g, [])
        lamps = [e for e in L if self.places[e].get("lamp")]
        parts = []
        if lamps:
            n = sum(1 for e in lamps if is_on(e, self.state(e)))
            parts.append("світло %d/%d" % (n, len(lamps)) if n else "світло вимк.")
        for e in L:
            st = self.state(e) or {}
            if domain(e) == "sensor" and (st.get("attributes") or {}).get("device_class") == "temperature" \
                    and num(st.get("state")) is not None:
                parts.append("%s°" % num(st["state"]))
                break
        if any(e.startswith("energy:battery") for e in L):
            b = self.energy()["bat"]
            if b["soc"] is not None:
                parts.append("акум. %d%%" % round(b["soc"]))
        if any(domain(e) == "media_player" and (self.state(e) or {}).get("state") == "playing" for e in L):
            parts.append("грає")
        n = sum(1 for e in L if domain(e) == "cover" and self.kind(e) != "screen" and (self.state(e) or {}).get("state") == "open")
        if n:
            parts.append("відчинено %d" % n)
        parts.append("%d пристр." % len(L))
        return " · ".join(parts)

    def step(self, e, sign):
        """+ / - in a room: the device's first slider, else on / off, open / close."""
        if self.ha.status != "connected":
            return self.say(self.offline_text(), RED)
        if e.startswith("energy:"):
            return
        r = next((r for r in self.rows(e) if r.kind == "slider"), None)
        if r:
            r.step(sign)
            return self.say("%s %s" % (r.label, "+" if sign > 0 else "−"))
        d = domain(e)
        if d in TOGGLE or d == "media_player" and self.kind(e) not in ("projector", "soundbar"):
            self.ask_or_call(e, d, "turn_on" if sign > 0 else "turn_off", {})
        elif d == "media_player":
            if self.av_on(e) != (sign > 0):
                self.av_power(e)
        elif d == "cover":
            if self.kind(e) == "screen":
                self.send(d, "close_cover" if sign > 0 else "open_cover", e, {})      # + lets the screen down
            else:
                self.ask_or_call(e, d, "open_cover" if sign > 0 else "close_cover", {})
        elif d == "climate":
            self.ask_or_call(e, d, "turn_on" if sign > 0 else "turn_off", {})

    def state(self, eid):
        return self.ha.get(eid)

    def kind(self, eid):
        return (self.places.get(eid) or {}).get("kind")

    def group(self, eid):
        """The projector's entities (its one on the plan and the rest), else just this one."""
        if self.kind(eid) != "projector":
            return [eid]
        with self.ha.lock:
            g = hawire.proj_group(self.ha.states)
        return g or [eid]

    def av_pick(self, eid, service):
        """The entity of the projector's group that is available and can do the service."""
        bit = AVF.get(service)
        for e in [eid] + [g for g in self.group(eid) if g != eid]:
            st = self.state(e)
            if st and st.get("state") != "unavailable" and (not bit or st["attributes"].get("supported_features", 0) & bit):
                return e
        return None

    def av_on(self, eid):
        return any(is_on(e, self.state(e)) for e in self.group(eid))

    def energy(self):
        return hawire.energy(self.state, self.roles, (self.plan.get("power") or {}).get("batSign", 1))

    def energy_text(self, kind, en=None):
        """The battery, the grid or the generator in a line (as the 3D model's chips)."""
        en = en or self.energy()
        if kind == "battery":
            b = en["bat"]
            if b["soc"] is None and b["p"] is None and b["v"] is None:
                return "немає даних інвертора"
            d = "" if b["p"] is None or abs(b["p"]) < 20 else ("заряд " if b["p"] < 0 else "розряд ") + hawire.fmt_w(abs(b["p"]))
            return " · ".join(x for x in ("%d%%" % round(b["soc"]) if b["soc"] is not None else "", d,
                                          "%.1f В" % b["v"] if b["v"] is not None else "") if x)
        if kind == "grid":
            if en["grid"] is None:
                return "немає даних інвертора"
            if not en["grid"]:
                return "НЕМАЄ МЕРЕЖІ" + (" · дім " + hawire.fmt_w(en["load"]) if en["load"] is not None else "")
            gp = en["gp"]
            return " · ".join(x for x in ("мережа є", "" if gp is None else ("віддача " if gp < 0 else "з мережі ") + hawire.fmt_w(abs(gp)),
                                          "%d В" % round(en["gv"]) if en["gv"] is not None else "") if x)
        g = en["gen"]
        return "немає даних" if g is None else ("працює · " + hawire.fmt_w(g)) if g > 50 else "не працює"

    def screen_of(self, fid):
        return next(((e, v) for e, v in self.devices(fid) if v.get("kind") == "screen"), (None, None))

    def lit_groups(self, fid):
        """The rooms (their groups) with a lamp on."""
        lit = set()
        rooms = self.rooms(fid)
        for e, v in self.devices(fid):
            if not v.get("lamp") or not is_on(e, self.state(e)):
                continue
            r = self.room_at(rooms, v["x"], v["z"], 0.05)
            if r:
                lit.add(r.get("group") or r["id"])
        return lit

    @staticmethod
    def room_at(rooms, x, z, slack=0.0):
        for r in rooms:
            if r["x"] - slack <= x <= r["x"] + r["w"] + slack and r["z"] - slack <= z <= r["z"] + r["d"] + slack:
                return r
        return None

    def danger(self, eid):
        st = self.state(eid) or {}
        if eid in self.confirm_ids or domain(eid) in ("lock", "alarm_control_panel"):
            return True
        dc = st.get("attributes", {}).get("device_class") or self.classes.get(eid)
        if domain(eid) == "cover" and dc in ("garage", "gate", "door"):
            return True
        text = (eid + " " + friendly(eid, st, self.names)).lower()
        return domain(eid) in ("cover", "switch", "button") and self.kind(eid) != "screen" and \
            any(w in text for w in DANGER_WORDS)

    # ---------------------------------------------------------------- the geometry
    def transform(self, fid):
        """Plan metres -> the screen: the whole floor, or the room we are in, bigger (with a bit around it)."""
        rooms = self.rooms(fid)
        if not rooms:
            return lambda x, z: (64, 64), 1
        x0 = min(r["x"] for r in rooms)
        x1 = max(r["x"] + r["w"] for r in rooms)
        z0 = min(r["z"] for r in rooms)
        z1 = max(r["z"] + r["d"] for r in rooms)
        aw, ah = 124, BAR - TOP - 4
        kf = min(aw / max(0.5, x1 - x0), ah / max(0.5, z1 - z0))
        u = self.units(fid).get(self.room) if self.room else None
        if u:
            m = 0.35
            x0, x1, z0, z1 = u["x0"] - m, u["x1"] + m, u["z0"] - m, u["z1"] + m
            k = min(aw / max(0.5, x1 - x0), ah / max(0.5, z1 - z0), max(kf, 40))
            return self._tf(x0, x1, z0, z1, k, aw, ah), k
        k = kf
        return self._tf(x0, x1, z0, z1, k, aw, ah), k

    @staticmethod
    def _tf(x0, x1, z0, z1, k, aw, ah):
        ox = 2 + (aw - (x1 - x0) * k) / 2 - x0 * k
        oz = TOP + 2 + (ah - (z1 - z0) * k) / 2 - z0 * k
        return lambda x, z: (ox + x * k, oz + z * k)

    # ---------------------------------------------------------------- actions
    def action(self, eid):
        """Enter on the map."""
        st = self.state(eid)
        d, kind = domain(eid), self.kind(eid)
        if eid.startswith("energy:"):
            return self.open_card()
        if self.ha.status != "connected":
            return self.say(self.offline_text(), RED)
        if kind in ("projector", "soundbar"):
            return self.av_power(eid)
        if not st or st.get("state") == "unavailable":
            return self.say("пристрій недоступний", RED)
        s = st.get("state")
        if d == "media_player" and kind == "speaker":
            return self.speaker_tap(eid)
        if kind == "screen":
            down = screen_down(st)
            self.say("екран піднімається" if down else "екран опускається")
            return self.send("cover", "open_cover" if down else "close_cover", eid, {})
        if d in TOGGLE:
            call = (d, "turn_off" if s == "on" else "turn_on", {})
        elif d == "cover":
            call = (d, "close_cover" if s in ("open", "opening") else "open_cover", {})
        elif d == "media_player":
            call = (d, "turn_on", {}) if s in ("off", "standby") else (d, "media_play_pause", {})
        elif d == "lock":
            call = (d, "lock" if s == "unlocked" else "unlock", {})
        elif d in ("scene", "script"):
            call = (d, "turn_on", {})
        elif d == "button":
            call = (d, "press", {})
        elif d == "valve":
            call = (d, "close_valve" if s == "open" else "open_valve", {})
        else:
            return self.open_card()                 # sensors, climate: nothing to switch - the card
        self.ask_or_call(eid, *call)

    def open_card(self):
        self.view, self.row = "details", 0

    def av_power(self, eid):
        """The projector or the soundbar on / off (the projector: on if any of its entities says so)."""
        on = self.av_on(eid)
        service = "turn_off" if on else "turn_on"
        use = self.av_pick(eid, service)
        what = "Проєктор" if self.kind(eid) == "projector" else "Саундбар"
        if not use:
            return self.say("%s не %s по мережі" % (what, "вимикається" if on else "вмикається"), RED)
        self.say("%s %s" % (what, "вимикається" if on else "вмикається"))
        self.send("media_player", service, use, {}, mark=eid)

    def speaker_tap(self, eid):
        """As a tap on the speaker in the 3D model (js/speaker.js decideTap): playing - pause; just stopped
        - on again; long quiet - it says the time; right after the time - the radio."""
        st = self.state(eid) or {}
        mem = self.mem.setdefault(eid, {"said": 0, "stopped": 0, "station": 0})
        now = time.time()
        s, said, stopped = st.get("state"), now - mem["said"], now - mem["stopped"]
        since = now - (st.get("lc") or 0)
        if s in ("playing", "buffering"):
            if said < SPEECH:
                return self.play_station(eid, mem["station"])
            mem["stopped"] = now
            return self.send("media_player", "media_pause", eid, {})
        if said < RECENT or (s != "paused" and stopped < RECENT):
            return self.play_station(eid, mem["station"])
        if s == "paused" and (since < RECENT or stopped < RECENT):
            return self.send("media_player", "media_play", eid, {})
        self.say_time(eid)

    def radio(self):
        return self.plan.get("radio") or RADIO_DEFAULT

    def play_station(self, eid, i):
        L = self.radio()
        i %= len(L)
        r = L[i]
        mem = self.mem.setdefault(eid, {"said": 0, "stopped": 0, "station": 0})
        mem.update(station=i, said=0, stopped=0)
        self.say("радіо: " + r["name"], ACCENT)
        self.send("media_player", "play_media", eid, {"media_content_id": r["id"], "media_content_type": "music",
                                                     "extra": {"title": r["name"]}})

    def tts(self, eid, message, lang="uk"):
        """A phrase on the speaker through HA's TTS (Google first, as the 3D model)."""
        with self.ha.lock:
            engines = sorted((e for e in self.ha.states if e.startswith("tts.")),
                             key=lambda e: ("google" not in e, e))
        data = {"message": message, **({"language": lang} if lang else {})}
        if engines:
            ok = self.ha.call("tts", "speak", engines[0], media_player_entity_id=eid, cache=True, **data)
        else:
            ok = self.ha.call("tts", "google_translate_say", eid, **data)
        if not ok:
            return self.say(self.offline_text(), RED)
        self.pending[eid] = time.monotonic()
        self.say("каже: " + message, ACCENT)

    def say_time(self, eid):
        self.mem.setdefault(eid, {"said": 0, "stopped": 0, "station": 0})["said"] = time.time()
        self.tts(eid, time_text())

    def ask_or_call(self, eid, dom, service, data):
        if self.danger(eid):
            verb = {"open_cover": "Відкрити", "close_cover": "Закрити", "unlock": "Відчинити", "lock": "Зачинити",
                    "turn_on": "Увімкнути", "turn_off": "Вимкнути", "press": "Натиснути", "stop_cover": "Зупинити",
                    "set_cover_position": "Пересунути"}.get(service, service)
            self.confirm = ("%s «%s»?" % (verb, friendly(eid, self.state(eid), self.names)), dom, service, eid, data)
            self.choice = 0
            self.back_to = self.view
            self.view = "confirm"
            return
        self.send(dom, service, eid, data)

    def send(self, dom, service, eid, data, mark=None):
        if self.ha.call(dom, service, eid, **data):
            self.pending[mark or eid] = time.monotonic()
            lcd.play("select")
        else:
            self.say(self.offline_text(), RED)

    def offline_text(self):
        return {"none": "немає токена HA (house.env)", "auth": "HA: невірний токен",
                "connecting": "з'єднання з HA…", "loading": "завантаження з HA…"}.get(self.ha.status, "немає зв'язку з HA")

    def say(self, text, color=FG):
        self.toast = (text, color, time.monotonic())
        self.dirty = True

    def move(self, dx, dz):
        """The nearest device that way (straight ahead counts more than aside)."""
        fid = self.fid()
        cur = self.selected()
        if cur is None:
            return
        here = self.places[cur]
        best = None
        mine = set(self.members(fid).get(self.room, [])) if self.room else None
        for e, v in self.devices(fid):
            if e == cur or (mine is not None and e not in mine):
                continue
            vx, vz = v["x"] - here["x"], v["z"] - here["z"]
            ahead = vx * dx + vz * dz
            if ahead <= 0.05:
                continue
            score = ahead + abs(vx * dz - vz * dx) * 2.2
            if best is None or score < best[0]:
                best = (score, e)
        if best:
            self.sel[fid] = best[1]
            self.dirty = True

    # ---------------------------------------------------------------- the card's lines
    def rows(self, eid):
        st = self.state(eid) or {}
        a, d, kind, s = st.get("attributes") or {}, domain(eid), self.kind(eid), st.get("state")
        R = []
        call = lambda svc, **data: (lambda: self.ask_or_call(eid, d, svc, data))   # noqa: E731
        if not st or s == "unavailable":
            return R
        if d == "light":
            R.append(Row("act", "Вимкнути" if s == "on" else "Увімкнути", do=call("turn_off" if s == "on" else "turn_on")))
            modes = a.get("supported_color_modes") or []
            if any(m != "onoff" for m in modes):
                pct = round((a.get("brightness") or 0) * 100 / 255) if s == "on" else 0

                def bright(step, pct=pct):
                    p = max(0, min(100, (pct // 10 + step) * 10 if step > 0 else math.ceil(pct / 10 + step) * 10))
                    self.send(d, "turn_off" if p == 0 else "turn_on", eid, {} if p == 0 else {"brightness_pct": p})
                R.append(Row("slider", "Яскравість", frac=pct / 100, text="%d%%" % pct, step=bright))
            if "color_temp" in modes:
                lo, hi = a.get("min_color_temp_kelvin") or 2000, a.get("max_color_temp_kelvin") or 6500
                k = a.get("color_temp_kelvin") or (lo + hi) // 2
                R.append(Row("slider", "Тепло ↔ холодно", frac=(k - lo) / max(1, hi - lo), text="%d K" % k,
                             step=lambda st_, k=k, lo=lo, hi=hi: self.send(d, "turn_on", eid, {
                                 "color_temp_kelvin": max(lo, min(hi, k + st_ * 250))})))
            if any(m in ("hs", "rgb", "rgbw", "rgbww", "xy") for m in modes):
                R.append(Row("choice", "Колір", options=[n for n, _ in COLOURS], cur=-1,
                             apply=lambda i: self.send(d, "turn_on", eid, {"rgb_color": list(COLOURS[i][1])}),
                             swatch=[c for _, c in COLOURS]))
        elif d in TOGGLE:
            R.append(Row("act", "Вимкнути" if s == "on" else "Увімкнути", do=call("turn_off" if s == "on" else "turn_on")))
            if d == "fan" and a.get("percentage") is not None:
                p = a["percentage"]
                R.append(Row("slider", "Швидкість", frac=p / 100, text="%d%%" % p,
                             step=lambda st_, p=p: self.send(d, "set_percentage", eid, {"percentage": max(0, min(100, p + st_ * 10))})))
        elif kind == "screen":
            down = screen_down(st)
            R += [Row("act", "▲ Підняти" if down else "▼ Опустити", do=lambda: self.send(d, "open_cover" if down else "close_cover", eid, {})),
                  Row("act", "■ Стоп", do=lambda: self.send(d, "stop_cover", eid, {}))]
            if a.get("current_position") is not None:
                p = 100 - a["current_position"]
                R.append(Row("slider", "Опущено", frac=p / 100, text="%d%%" % p,
                             step=lambda st_, p=p: self.send(d, "set_cover_position", eid, {
                                 "position": 100 - max(0, min(100, (p // 10 + st_) * 10))})))
            f = next((e for e in self.ha.states if e.startswith("switch.") and "follow_projector" in e), None)
            if f:
                fs = (self.state(f) or {}).get("state")
                R.append(Row("act", "За проєктором: " + ("так" if fs == "on" else "ні"),
                             do=lambda: self.send("switch", "toggle", f, {})))
        elif d == "cover":
            R += [Row("act", "▲ Відкрити", do=call("open_cover")), Row("act", "■ Стоп", do=lambda: self.send(d, "stop_cover", eid, {})),
                  Row("act", "▼ Закрити", do=call("close_cover"))]
            if a.get("current_position") is not None:
                p = a["current_position"]
                R.append(Row("slider", "Положення", frac=p / 100, text="%s%%" % p,
                             step=lambda st_, p=p: self.ask_or_call(eid, d, "set_cover_position",
                                                                    {"position": max(0, min(100, (p // 10 + st_) * 10))})))
        elif d == "climate":
            R.append(Row("act", "Вимкнути" if s != "off" else "Увімкнути", do=call("turn_off" if s != "off" else "turn_on")))
            if a.get("temperature") is not None:
                t, stp = a["temperature"], a.get("target_temp_step") or 0.5
                R.append(Row("slider", "Ціль", frac=(t - a.get("min_temp", 7)) / max(1, a.get("max_temp", 35) - a.get("min_temp", 7)),
                             text="%s°" % num(t), step=lambda st_, t=t, stp=stp: self.send(d, "set_temperature", eid, {
                                 "temperature": max(a.get("min_temp", 7), min(a.get("max_temp", 35), t + st_ * stp))})))
            modes = a.get("hvac_modes") or []
            if modes:
                R.append(Row("choice", "Режим", options=[HVAC_UK.get(m, m) for m in modes],
                             cur=modes.index(s) if s in modes else -1,
                             apply=lambda i, modes=modes: self.send(d, "set_hvac_mode", eid, {"hvac_mode": modes[i]})))
        elif d == "media_player":
            R += self.media_rows(eid, st, a, kind)
        elif d == "lock":
            R += [Row("act", "Зачинити", do=call("lock")), Row("act", "Відчинити", do=call("unlock"))]
        elif d in ("scene", "script"):
            R.append(Row("act", "Запустити", do=call("turn_on")))
        elif d == "button":
            R.append(Row("act", "Натиснути", do=call("press")))
        return R

    def media_rows(self, eid, st, a, kind):
        R = []
        s = st.get("state")
        if kind in ("projector", "soundbar"):
            on = self.av_on(eid)
            R.append(Row("act", "Вимкнути" if on else "Увімкнути", do=lambda: self.av_power(eid)))
            src = next((e for e in [eid] + self.group(eid) if (self.state(e) or {}).get("state") not in (None, "unavailable")
                        and (self.state(e)["attributes"].get("source_list"))), None)   # who knows the sources
            if src:
                sa = self.state(src)["attributes"]
                if sa.get("source_list"):
                    L = sa["source_list"]
                    R.append(Row("choice", "Джерело", options=L, cur=L.index(sa.get("source")) if sa.get("source") in L else -1,
                                 apply=lambda i, L=L, src=src: self.send("media_player", "select_source", src, {"source": L[i]})))
            if a.get("sound_mode_list"):
                L = a["sound_mode_list"]
                R.append(Row("choice", "Звук", options=L, cur=L.index(a.get("sound_mode")) if a.get("sound_mode") in L else -1,
                             apply=lambda i, L=L: self.send("media_player", "select_sound_mode", eid, {"sound_mode": L[i]})))
            scr, _ = self.screen_of(self.places.get(eid, {}).get("f"))
            if kind == "projector" and scr:
                down = screen_down(self.state(scr))
                R.append(Row("act", "Екран: " + ("підняти" if down else "опустити"),
                             do=lambda: self.send("cover", "open_cover" if down else "close_cover", scr, {})))
        elif kind == "speaker":
            mem = self.mem.setdefault(eid, {"said": 0, "stopped": 0, "station": 0})
            playing = s in ("playing", "buffering")
            R.append(Row("act", "❚❚ Пауза" if playing else "▶ Грати" if s == "paused" else "▶ Радіо",
                         do=lambda: (self.send("media_player", "media_pause", eid, {}), mem.update(stopped=time.time()))
                         if playing else self.send("media_player", "media_play", eid, {}) if s == "paused"
                         else self.play_station(eid, mem["station"])))
            L = self.radio()
            R.append(Row("choice", "Радіо", options=[r["name"] for r in L], cur=mem["station"] if playing else -1,
                         apply=lambda i: self.play_station(eid, i)))
            R.append(Row("act", "Сказати час", do=lambda: self.say_time(eid)))
            R.append(Row("act", "Сказати…", do=lambda: self.start_say(eid)))
            if playing:
                R.append(Row("act", "▶▶ Далі", do=lambda: self.send("media_player", "media_next_track", eid, {})
                             if (a.get("media_duration") or 0) > 0 else self.play_station(eid, mem["station"] + 1)))
        else:                                                         # a TV and the rest
            R.append(Row("act", "❚❚ Пауза" if s == "playing" else "▶ Грати",
                         do=lambda: self.send("media_player", "media_play_pause", eid, {})))
            R.append(Row("act", "▶▶ Далі", do=lambda: self.send("media_player", "media_next_track", eid, {})))
            R.append(Row("act", ("Вимкнути" if is_on(eid, st) else "Увімкнути"),
                         do=lambda: self.send("media_player", "turn_off" if is_on(eid, st) else "turn_on", eid, {})))
            if a.get("source_list"):
                L = a["source_list"]
                R.append(Row("choice", "Джерело", options=L, cur=L.index(a.get("source")) if a.get("source") in L else -1,
                             apply=lambda i, L=L: self.send("media_player", "select_source", eid, {"source": L[i]})))
        vol_e = self.av_pick(eid, "volume_set") if kind == "projector" else eid
        va = (self.state(vol_e) or {}).get("attributes", {}) if vol_e else {}
        if va.get("volume_level") is not None:
            v = va["volume_level"]
            R.append(Row("slider", "Гучність", frac=v, text="%d%%" % round(v * 100),
                         step=lambda st_, v=v, e=vol_e: self.send("media_player", "volume_set", e, {
                             "volume_level": max(0.0, min(1.0, round(v * 20 + st_) / 20))})))
        if va.get("is_volume_muted") is not None:
            m = va["is_volume_muted"]
            R.append(Row("act", "Увімкнути звук" if m else "Без звуку",
                         do=lambda m=m, e=vol_e: self.send("media_player", "volume_mute", e, {"is_volume_muted": not m})))
        return R

    def start_say(self, eid):
        self.say_eid, self.say_buf = eid, ""
        self.view = "say"

    # ---------------------------------------------------------------- history and the forecast
    def history(self, eid):
        """The last 24 h of a sensor: [(t, value)], asked again after 5 minutes (None until it comes)."""
        h = self.hist.get(eid)
        now = time.time()
        if (h is None or now - h["at"] > 300) and self.ha.status == "connected" and not (h or {}).get("busy"):
            self.hist[eid] = h = {"at": now, "data": (h or {}).get("data"), "busy": True}
            start = datetime.datetime.fromtimestamp(now - 86400, datetime.timezone.utc).isoformat()

            def done(m, eid=eid):
                data = []
                for x in ((m.get("result") or {}).get(eid) or []) if m.get("success") else []:
                    try:
                        data.append((x.get("lu") or x.get("lc") or 0, float(x.get("s"))))
                    except (TypeError, ValueError):
                        pass
                self.hist[eid] = {"at": time.time(), "data": data, "busy": False}
                self.dirty = True
            self.ha.request({"type": "history/history_during_period", "start_time": start, "entity_ids": [eid],
                             "minimal_response": True, "no_attributes": True}, done)
        return (h or {}).get("data")

    def forecast(self):
        """Tomorrow from HA's weather entity: (condition, max, min) or None."""
        now = time.time()
        with self.ha.lock:
            w = next((e for e in sorted(self.ha.states) if e.startswith("weather.")), None)
        if w and now - self.fcast["at"] > 1800 and self.ha.status == "connected":
            self.fcast["at"] = now

            def done(m):
                f = ((((m.get("result") or {}).get("response") or {}).get(w) or {}).get("forecast")) or []
                self.fcast["data"] = f
                self.dirty = True
            self.ha.request({"type": "call_service", "domain": "weather", "service": "get_forecasts",
                             "service_data": {"type": "daily"}, "target": {"entity_id": w}, "return_response": True}, done)
        F = self.fcast["data"] or []
        tomorrow = (datetime.date.today() + datetime.timedelta(days=1)).isoformat()
        day = next((x for x in F if str(x.get("datetime", "")).startswith(tomorrow)), F[1] if len(F) > 1 else None)
        return (day.get("condition"), day.get("temperature"), day.get("templow")) if day else None

    # ---------------------------------------------------------------- keys
    def key(self, ev):
        k, hat = ev.key, getattr(ev, "hat", False)
        self.dirty = True
        if self.view == "help":
            self.view = "map"
            return True
        if self.view == "say":
            return self.key_say(ev)
        if self.view == "confirm":
            if k in (pygame.K_LEFT, pygame.K_RIGHT, pygame.K_UP, pygame.K_DOWN, pygame.K_TAB):
                self.choice ^= 1
            elif k in (pygame.K_RETURN, pygame.K_SPACE, pygame.K_y) or (hat and k == pygame.K_2):
                if self.choice == 1 or k == pygame.K_y:
                    _, dom, service, eid, data = self.confirm
                    self.send(dom, service, eid, data)
                self.view = self.back_to
            elif k in (pygame.K_ESCAPE, pygame.K_BACKSPACE, pygame.K_n) or (hat and k == pygame.K_3):
                self.view = self.back_to
            return True
        eid = self.selected()
        if self.view == "details":
            rows = self.rows(eid) if eid else []
            self.row = max(0, min(self.row, len(rows) - 1))
            r = rows[self.row] if rows else None
            if k in (pygame.K_ESCAPE, pygame.K_BACKSPACE, pygame.K_i) or (hat and k in (pygame.K_2, pygame.K_3)):
                self.view = "map"
            elif k == pygame.K_UP:
                self.row = max(0, self.row - 1)
            elif k == pygame.K_DOWN:
                self.row = min(len(rows) - 1, self.row + 1) if rows else 0
            elif r and (k in (pygame.K_LEFT, pygame.K_RIGHT) or plus_minus(ev)):
                step = 1 if k == pygame.K_RIGHT or plus_minus(ev) > 0 else -1
                if r.kind == "slider":
                    if self.ha.status != "connected":
                        self.say(self.offline_text(), RED)
                    else:
                        r.step(step)
                elif r.kind == "choice":
                    key = (eid, r.label)
                    cur = self.pick.get(key, r.cur)
                    n = len(r.options)
                    self.pick[key] = (cur + step) % n if cur >= 0 else (0 if step > 0 else n - 1)
            elif r and k in (pygame.K_RETURN, pygame.K_SPACE):
                if self.ha.status != "connected":
                    self.say(self.offline_text(), RED)
                elif r.kind == "act":
                    r.do()
                elif r.kind == "choice":
                    i = self.pick.pop((eid, r.label), r.cur)
                    if i >= 0:
                        r.apply(i)
            return True
        # the floor and the room
        fl = max(1, len(self.floors()))
        if k in (pygame.K_PAGEDOWN, pygame.K_f) or (k == pygame.K_TAB and not self.room) or (hat and k == pygame.K_1 and not self.room):
            self.floor, self.room = (self.floor + 1) % fl, None
        elif k == pygame.K_PAGEUP:
            self.floor, self.room = (self.floor - 1) % fl, None
        elif k in (pygame.K_0, pygame.K_1, pygame.K_2, pygame.K_3) and not hat:
            n = k - pygame.K_0
            for i, f in enumerate(self.floors()):
                if (n == 0 and f.get("elevation", 0) < 0) or (n and f.get("name", "").startswith(str(n))):
                    self.floor, self.room = i, None
        elif k == pygame.K_r:
            self.plans.fetch()
            self.say("оновлюю план…")
        elif k == pygame.K_F1:
            self.view = "help"
        elif not self.room:                                   # choosing a room
            if k == pygame.K_ESCAPE or (hat and k == pygame.K_3):
                return False
            if k in ARROWS:
                self.move_room(*ARROWS[k])
            elif k == pygame.K_RETURN:
                self.enter_room()
            elif k == pygame.K_SPACE or (hat and k == pygame.K_2):
                g = self.cur_room()
                if g:
                    self.room_lights(g)
        else:                                                 # in a room
            if k in (pygame.K_ESCAPE, pygame.K_BACKSPACE) or (hat and k == pygame.K_3):
                self.rsel[self.fid()] = self.room
                self.room = None
            elif k in ARROWS:
                self.move(*ARROWS[k])
            elif k == pygame.K_TAB or (hat and k == pygame.K_1):
                L = self.members(self.fid()).get(self.room, [])
                if eid in L:
                    back = bool(getattr(ev, "mod", 0) & pygame.KMOD_SHIFT)
                    self.sel[self.fid()] = L[(L.index(eid) + (-1 if back else 1)) % len(L)]
            elif eid and (k == pygame.K_SPACE or (hat and k == pygame.K_2)):
                self.action(eid)
            elif eid and plus_minus(ev):
                self.step(eid, plus_minus(ev))
            elif eid and k in (pygame.K_RETURN, pygame.K_i):
                self.open_card()
        return True

    def key_say(self, ev):
        k = ev.key
        if k == pygame.K_ESCAPE or (getattr(ev, "hat", False) and k == pygame.K_3):
            self.view = "details"
        elif k == pygame.K_TAB:
            self.say_ua = not self.say_ua
        elif k == pygame.K_BACKSPACE:
            self.say_buf = self.say_buf[:-1]
        elif k == pygame.K_RETURN:
            text = self.say_buf.strip()
            if text:
                self.tts(self.say_eid, text, "uk" if self.say_ua else "en")
                self.view = "details"
        else:
            ch = getattr(ev, "unicode", "") or ""
            if ch and ch.isprintable() and len(self.say_buf) < 120:
                self.say_buf += UA.get(ch, ch) if self.say_ua else ch
        return True

    # ---------------------------------------------------------------- drawing
    def draw(self):
        s = self.screen
        s.fill(BG)
        fid = self.fid()
        if not self.plans.plan:
            self.text_center(["немає плану будинку", "", "сервер плану:", self.plans.base,
                              "(%s)" % (self.plans.error or "завантаження…")], 40)
            lcd.flip()
            return
        self.draw_tabs(fid)
        self.draw_rooms(fid)
        self.draw_devices(fid)
        self.draw_bar()
        if self.view == "details":
            self.draw_details()
        elif self.view == "confirm":
            self.draw_confirm()
        elif self.view == "help":
            self.draw_help()
        elif self.view == "say":
            self.draw_say()
        lcd.flip()

    def draw_tabs(self, fid):
        s = self.screen
        x = 1
        names = [f.get("name") or f["id"] for f in self.floors()]
        if sum(f_tab.size(n)[0] + 7 for n in names) > 104:      # the HAT: «П», «1», «2»
            names = [n.split()[0] if n[:1].isdigit() else n[:1] for n in names]
        u = self.units(fid).get(self.room) if self.room else None
        if u:                                                   # in a room: «1 поверх › Кухня»
            short = [n.split()[0] if n[:1].isdigit() else n[:1] for n in names]
            name = next((n for f, n in zip(self.floors(), short) if f["id"] == fid), "")
            w = f_tab.size(name)[0] + 5
            pygame.draw.rect(s, (50, 50, 55), (x, 1, w, 11), 1, border_radius=3)
            t = f_tab.render(name, True, DIM)
            s.blit(t, (x + 2.5, 6.5 - t.get_height() / 2))
            x += w + 2
            t = f_tab.render(fit("› " + u["name"], f_tab, 108 - x), True, ACCENT)
            s.blit(t, (x, 6.5 - t.get_height() / 2))
        for f, name in zip(self.floors() if not u else [], names):
            w = f_tab.size(name)[0] + 5
            if f["id"] == fid:
                pygame.draw.rect(s, ACCENT, (x, 1, w, 11), border_radius=3)
                col = BG
            else:
                pygame.draw.rect(s, (50, 50, 55), (x, 1, w, 11), 1, border_radius=3)
                col = DIM
            t = f_tab.render(name, True, col)
            s.blit(t, (x + 2.5, 6.5 - t.get_height() / 2))
            x += w + 2
        n = sum(1 for e, v in self.devices(fid) if v.get("lamp") and is_on(e, self.state(e)))
        st = self.ha.status
        col = {"connected": GREEN, "loading": ACCENT, "connecting": ACCENT}.get(st, RED if st != "none" else DIM)
        pygame.draw.circle(s, col, (124, 6.5), 2.2)
        if n:
            t = f_tab.render(str(n), True, ACCENT)
            tx = 119 - t.get_width()
            s.blit(t, (tx, 6.5 - t.get_height() / 2))
            bulb(s, tx - 4, 6, 2.2, True)

    def draw_rooms(self, fid):
        s = self.screen
        tf, k = self.transform(fid)
        rooms = self.rooms(fid)
        lit = self.lit_groups(fid)
        inside = self.room
        chosen = None if inside else self.cur_room()
        pygame.Surface.set_clip(s, lcd._rect((0, TOP, 128, BAR + 1 - TOP)))
        rects = []
        for r in rooms:
            (x0, y0), (x1, y1) = tf(r["x"], r["z"]), tf(r["x"] + r["w"], r["z"] + r["d"])
            g = r.get("group") or r["id"]
            outdoor = r.get("walls") in (False, "railing")
            fill, edge = (LIT, LIT_EDGE) if g in lit else (OUT, OUT_EDGE) if outdoor else (ROOM, ROOM_EDGE)
            if inside and g != inside:                          # the rooms around: dim
                fill, edge = mix(fill, BG, 0.6), mix(edge, BG, 0.5)
            elif g == chosen and g not in lit:
                fill = mix(fill, ACCENT, 0.12)
            rects.append((r, g, (x0, y0, x1 - x0, y1 - y0), fill, edge))
        for r, g, rc, fill, edge in rects:
            pygame.draw.rect(s, fill, rc)
        self.draw_furniture(fid, tf, rooms, {r["id"]: fill for r, g, rc, fill, edge in rects})
        for r, g, rc, fill, edge in sorted(rects, key=lambda x: x[1] in (chosen, inside)):
            pygame.draw.rect(s, edge, rc, 1)
        # the parts of one room (a group) without the line between them
        for i, (r, g, rc, fill, _) in enumerate(rects):
            for r2, g2, rc2, _, _ in rects[i + 1:]:
                if g2 != g or not r.get("group"):
                    continue
                for a, b in ((rc, rc2), (rc2, rc)):
                    if abs(a[0] + a[2] - b[0]) < 0.6:
                        y0, y1 = max(a[1], b[1]) + 1, min(a[1] + a[3], b[1] + b[3]) - 1
                        if y1 > y0:
                            pygame.draw.line(s, fill, (b[0], y0), (b[0], y1), 1)
                    if abs(a[1] + a[3] - b[1]) < 0.6:
                        x0, x1 = max(a[0], b[0]) + 1, min(a[0] + a[2], b[0] + b[2]) - 1
                        if x1 > x0:
                            pygame.draw.line(s, fill, (x0, b[1]), (x1, b[1]), 1)
        if chosen:
            self.outline([rc for r, g, rc, fill, edge in rects if g == chosen], ACCENT, 1.6)
        best = {}
        for r, g, rc, fill, edge in rects:
            if r.get("name") and (g not in best or rc[2] * rc[3] > best[g][1][2] * best[g][1][3]):
                best[g] = (r, rc, fill)
        for g, (r, rc, fill) in best.items():
            col = LIT_TEXT if g in lit else ROOM_TEXT if r.get("walls") not in (False, "railing") else (140, 125, 105)
            if inside and g != inside:
                col = mix(col, BG, 0.5)
            self.label(r["name"], rc, col, fill)
        pygame.Surface.set_clip(s, None)

    def outline(self, parts, col, t):
        """The outer edge of a room made of parts (the lines between its parts left out), t thick, inside."""
        s = self.screen
        for i, (x, y, w, h) in enumerate(parts):
            others = [p for j, p in enumerate(parts) if j != i]
            for side in ("top", "bottom", "left", "right"):
                horiz = side in ("top", "bottom")
                at = y if side == "top" else y + h if side == "bottom" else x if side == "left" else x + w
                lo, hi = (x, x + w) if horiz else (y, y + h)
                cuts = []
                for ox, oy, ow, oh in others:
                    edge = (oy + oh if side == "top" else oy) if horiz else (ox + ow if side == "left" else ox)
                    if abs(edge - at) < 0.8:
                        cuts.append((ox, ox + ow) if horiz else (oy, oy + oh))
                segs = [(lo, hi)]
                for c0, c1 in cuts:
                    segs = [q for a, b in segs for q in ((a, min(b, c0)), (max(a, c1), b)) if q[1] - q[0] > 0.5]
                for a, b in segs:
                    if horiz:
                        pygame.draw.rect(s, col, (a, at if side == "top" else at - t, b - a, t))
                    else:
                        pygame.draw.rect(s, col, (at if side == "left" else at - t, a, t, b - a))

    def draw_furniture(self, fid, tf, rooms, fills):
        """The furniture as in the 3D model, from above: its footprint in its own colour, faded into the
        room's (lit rooms keep their glow). Things high on the walls and the ceiling are left out."""
        s = self.screen
        items = []
        for it in self.plan.get("furniture") or []:
            if (it.get("floor") or (self.floors()[0]["id"] if self.floors() else None)) != fid or "x" not in it:
                continue
            if it.get("shape") in OUTDOOR or (it.get("y") or 0) >= 1.4 or it.get("mount") == "wall":
                continue
            w, d = it.get("w", 0), it.get("d", 0)
            cx, cz = it["x"] + w / 2, it["z"] + d / 2
            r = self.room_at(rooms, cx, cz)
            if not r or w * d < 0.02:
                continue
            items.append((w * d, it, cx, cz, fills.get(r["id"], ROOM)))
        for _, it, cx, cz, fill in sorted(items, key=lambda x: -x[0]):
            a = math.radians(it.get("rot") or 0)
            ca, sa = math.cos(a), math.sin(a)
            hw, hd = it["w"] / 2, it["d"] / 2
            pts = [tf(cx + x * ca + z * sa, cz - x * sa + z * ca) for x, z in ((-hw, -hd), (hw, -hd), (hw, hd), (-hw, hd))]
            base = colour(it.get("color"))
            k = 0.5 if it.get("shape") in ("aquarium", "billiard", "car", "pool") else 0.38
            pygame.draw.polygon(s, mix(base, fill, k), pts)
            if it.get("shape") == "aquarium":
                pygame.draw.polygon(s, (60, 150, 220), pts, 1)

    def label(self, name, rc, col, fill):
        """The room's name: on one line, or on two where one is too wide, or cut short with «…»."""
        x, y, w, h = rc
        lh = f_room.get_linesize()
        if lh > h:
            return
        lines = [name]
        if f_room.size(name)[0] > w - 2 and " " in name and 2 * lh <= h - 1:
            words = name.split()
            cut = min(range(1, len(words)), key=lambda i: max(f_room.size(" ".join(words[:i]))[0],
                                                             f_room.size(" ".join(words[i:]))[0]))
            two = [" ".join(words[:cut]), " ".join(words[cut:])]
            if all(f_room.size(ln)[0] <= w - 2 for ln in two) or \
                    max(f_room.size(ln)[0] for ln in two) < f_room.size(name)[0] * 0.8:
                lines = two
        lines = [fit(ln, f_room, w - 2) for ln in lines]
        if any(ln.endswith("…") and len(ln) < 4 for ln in lines):
            return
        y0 = y + 1.5
        for ln in lines:
            t = f_room.render(ln, True, col)
            tx = x + (w - t.get_width()) / 2
            pygame.draw.rect(self.screen, fill, (tx - 0.5, y0, t.get_width() + 1, t.get_height() - 0.5))
            self.screen.blit(t, (tx, y0))
            y0 += lh

    def draw_devices(self, fid):
        s = self.screen
        tf, k = self.transform(fid)
        cur = self.selected() if self.room else None
        blink = time.monotonic() % 1 < 0.6
        mine = set(self.members(fid).get(self.room, [])) if self.room else None
        devices = [(e, v) for e, v in self.devices(fid) if mine is None or e in mine]
        pygame.Surface.set_clip(s, lcd._rect((0, TOP, 128, BAR + 1 - TOP)))
        # the projector's beam on the screen while it is on
        scr, sv = self.screen_of(fid)
        for e, v in devices:
            if v.get("kind") == "projector" and self.av_on(e):
                px, py = tf(v["x"], v["z"])
                if scr:
                    a = math.radians(sv.get("rot") or 0)
                    hw = max(sv.get("w", 0), sv.get("d", 0)) / 2
                    ax, az = (math.cos(a), -math.sin(a)) if sv.get("w", 0) >= sv.get("d", 0) else (math.sin(a), math.cos(a))
                    p1, p2 = tf(sv["x"] - ax * hw, sv["z"] - az * hw), tf(sv["x"] + ax * hw, sv["z"] + az * hw)
                else:
                    p1, p2 = (px - 8, py + 14), (px + 8, py + 14)
                pygame.draw.polygon(s, (75, 85, 110), [(px, py), p1, p2])
                pygame.draw.line(s, (200, 215, 255), p1, p2, 1)
        en = self.energy() if any(e.startswith("energy:") for e, _ in devices) else None
        for e, v in sorted(devices, key=lambda ev: ev[0] == cur):
            x, y = tf(v["x"], v["z"])
            if e.startswith("energy:"):
                energy_icon(s, v["kind"], en, x, y)
                continue
            icon(s, e, v, self.state(e), x, y, self.classes.get(e), self.av_on(e) if v.get("kind") in ("projector", "soundbar") else None)
            if e in self.pending:
                pygame.draw.circle(s, FG, (x, y), 4, 1)
        if cur:
            x, y = tf(self.places[cur]["x"], self.places[cur]["z"])
            pygame.draw.circle(s, ACCENT if blink else (140, 110, 0), (x, y), 5.2, 1)
        pygame.Surface.set_clip(s, None)

    def draw_bar(self):
        s = self.screen
        pygame.draw.line(s, (60, 60, 66), (0, BAR + 1), (128, BAR + 1))
        for msg in (self.toast, self.ha.notice and (self.ha.notice[0], RED, self.ha.notice[1])):
            if msg and time.monotonic() - msg[2] < 3.5:
                for i, ln in enumerate(wrap(msg[0], f_text, 124)[:2]):
                    s.blit(f_text.render(ln, True, msg[1]), (2, BAR + 2 + i * 7))
                return
        if not self.room:
            g = self.cur_room()
            if not g:
                s.blit(f_text.render("на цьому поверсі немає пристроїв", True, DIM), (2, BAR + 3))
                return
            t = f_name.render(fit(self.units(self.fid())[g]["name"], f_name, 124), True, FG)
            s.blit(t, (2, BAR + 2))
            tail = "Enter ›"
            tw = f_small.size(tail)[0]
            s.blit(f_small.render(tail, True, DIM), (126 - tw, BAR + 2.5))
            s.blit(f_text.render(fit(self.room_text(g), f_text, 124), True, ACCENT), (2, BAR + 2 + t.get_height()))
            return
        eid = self.selected()
        if not eid:
            s.blit(f_text.render("у кімнаті немає пристроїв", True, DIM), (2, BAR + 3))
            return
        st = self.state(eid)
        name = friendly(eid, st, self.names)
        if eid.startswith("energy:"):
            en = self.energy()
            txt = self.energy_text(self.kind(eid), en) if self.ha.status == "connected" else self.offline_text()
            bad = (self.kind(eid) == "grid" and en["grid"] is False)
            t = f_name.render(fit(name, f_name, 124), True, FG)
            s.blit(t, (2, BAR + 2))
            s.blit(f_text.render(fit(txt, f_text, 124), True, RED if bad else ACCENT), (2, BAR + 2 + t.get_height()))
            return
        if self.ha.status != "connected" and not st:
            state, col = self.offline_text(), DIM
        else:
            on = self.av_on(eid) if self.kind(eid) in ("projector", "soundbar") else is_on(eid, st)
            st2 = self.state(self.av_pick(eid, "") or eid) if self.kind(eid) == "projector" and on else st
            state = state_text(eid, st2, self.classes.get(eid), self.kind(eid))
            if self.kind(eid) == "screen":
                on = screen_down(st)
            col = ACCENT if on else (RED if (st or {}).get("state") == "unavailable" else FG)
        t = f_name.render(fit(name, f_name, 124), True, FG)
        s.blit(t, (2, BAR + 2))
        s.blit(f_text.render(fit(state, f_text, 124), True, col), (2, BAR + 2 + t.get_height()))

    def panel(self, x, y, w, h):
        pygame.draw.rect(self.screen, (14, 16, 22), (x, y, w, h), border_radius=4)
        pygame.draw.rect(self.screen, (90, 95, 110), (x, y, w, h), 1, border_radius=4)

    def draw_details(self):
        s = self.screen
        eid = self.selected()
        if not eid:
            self.view = "map"
            return
        if eid.startswith("energy:"):
            return self.draw_energy_card(eid)
        st = self.state(eid) or {}
        a, d, kind = st.get("attributes") or {}, domain(eid), self.kind(eid)
        self.panel(2, 15, 124, 112)
        x, y, W = 6, 17, 116
        name = friendly(eid, st, self.names)
        t = f_name.render(fit(name, f_name, W), True, ACCENT)
        s.blit(t, (x, y))
        y += t.get_height()
        on = self.av_on(eid) if kind in ("projector", "soundbar") else is_on(eid, st)
        stt = state_text(eid, self.state(self.av_pick(eid, "") or eid) if kind == "projector" and on else st,
                          self.classes.get(eid), kind) if st else self.offline_text()
        if kind == "screen":
            on = screen_down(st)
        for ln in wrap(stt, f_text, W)[:2]:
            t = f_text.render(ln, True, ACCENT if on else FG)
            s.blit(t, (x, y))
            y += t.get_height()
        y += 1
        if kind == "weather" or d == "sensor":
            y = self.draw_sensor_card(eid, st, x, y, W, kind == "weather")
        elif d == "binary_sensor" and st.get("lc"):
            t = f_small.render("змінився о " + time.strftime("%H:%M", time.localtime(st["lc"])), True, DIM)
            s.blit(t, (x, y))
            y += t.get_height() + 1
        rows = self.rows(eid) if st else []
        self.row = max(0, min(self.row, len(rows) - 1))
        lh = 7.4
        room = int((122 - 8 - y) // lh)
        top = max(0, min(self.row - room + 1, len(rows) - room)) if room > 0 else 0
        for i, r in enumerate(rows[top:top + max(0, room)]):
            i += top
            ry = y + (i - top) * lh
            sel = i == self.row
            if sel:
                pygame.draw.rect(s, (55, 48, 20), (x - 2, ry - 0.5, W + 4, lh - 0.4), border_radius=2)
            col = ACCENT if sel else FG
            if r.kind == "act":
                s.blit(f_text.render(fit(r.label, f_text, W), True, col), (x, ry))
            elif r.kind == "slider":
                t = f_text.render(r.label, True, col)
                s.blit(t, (x, ry))
                tv = f_text.render(r.text, True, FG)
                s.blit(tv, (x + W - tv.get_width(), ry))
                bx = x + t.get_width() + 3
                bw = W - t.get_width() - tv.get_width() - 7
                if bw > 8:
                    pygame.draw.rect(s, (45, 48, 58), (bx, ry + 2.3, bw, 2.6), border_radius=1)
                    pygame.draw.rect(s, ACCENT if sel else (170, 140, 40), (bx, ry + 2.3, max(1, bw * min(1, max(0, r.frac))), 2.6),
                                     border_radius=1)
            elif r.kind == "choice":
                t = f_text.render(r.label + ":", True, col)
                s.blit(t, (x, ry))
                i_ = self.pick.get((eid, r.label), r.cur)
                val = r.options[i_] if 0 <= i_ < len(r.options) else "—"
                changed = (eid, r.label) in self.pick
                vx = x + t.get_width() + 2
                if getattr(r, "swatch", None) and 0 <= i_ < len(r.swatch):
                    pygame.draw.rect(s, r.swatch[i_], (vx, ry + 1, 4, 4))
                    vx += 5
                txt = ("‹ %s ›" % val) if sel else val
                s.blit(f_text.render(fit(txt, f_text, x + W - vx), True, ACCENT if changed else FG), (vx, ry))
        if not rows and st.get("state") == "unavailable":
            s.blit(f_text.render("пристрій недоступний", True, RED), (x, y))
        hint = "↑↓ рядок · ←→ змінити · Enter · Esc" if rows else "Esc - назад"
        t = f_small.render(fit(hint, f_small, W), True, DIM)
        s.blit(t, (x, 124 - t.get_height()))

    def draw_energy_card(self, eid):
        """The battery, the grid and the generator together, as the 3D model's energy panel."""
        s = self.screen
        kind = self.kind(eid)
        en = self.energy()
        self.panel(2, 15, 124, 112)
        x, y, W = 6, 17, 116
        t = f_name.render(fit(friendly(eid, None, self.names), f_name, W), True, ACCENT)
        s.blit(t, (x, y))
        y += t.get_height() + 1
        b = en["bat"]
        if kind == "battery" and b["soc"] is not None:
            soc = b["soc"]
            col = GREEN if soc > 50 else ACCENT if soc > 20 else RED
            t = f_big.render("%d%%" % round(soc), True, col)
            s.blit(t, (x, y))
            bx = x + t.get_width() + 4
            battery_icon(s, bx + 9, y + t.get_height() / 2, soc, b["p"], 2.2)
            d = "" if b["p"] is None or abs(b["p"]) < 20 else ("заряджається " if b["p"] < 0 else "розряджається ") + hawire.fmt_w(abs(b["p"]))
            if d:
                tv = f_text.render(d, True, FG)
                s.blit(tv, (x + W - tv.get_width(), y + t.get_height() - tv.get_height()))
            y += t.get_height() + 1
            graph = self.roles.get("batSoc")
        elif kind == "grid":
            on = en["grid"]
            t = f_big.render("мережа є" if on else "немає мережі" if on is False else "мережа ?", True,
                             GREEN if on else RED if on is False else DIM)
            s.blit(t, (x, y))
            y += t.get_height() + 1
            graph = self.roles.get("gridPower")
        else:
            t = f_big.render(self.energy_text("generator", en), True, ACCENT if (en["gen"] or 0) > 50 else DIM)
            s.blit(t, (x, y))
            y += t.get_height() + 1
            graph = self.roles.get("genPower")
        data = self.history(graph) if graph else None
        if data and len(data) > 1:
            spark(s, data, x, y, W, 18, (120, 210, 120) if kind == "battery" else (110, 180, 255))
            y += 21
        lines = []
        if en["grid"] is not None:
            lines.append(("Мережа", self.energy_text("grid", en), RED if en["grid"] is False else FG))
        if en["load"] is not None:
            lines.append(("Будинок", hawire.fmt_w(en["load"]), FG))
        if b["soc"] is not None or b["p"] is not None:
            lines.append(("Акумулятор", self.energy_text("battery", en), FG))
        pv = [(k.upper(), w) for k, w in en["pv"].items() if w is not None]
        if pv:
            lines.append(("Сонце", " · ".join("%s %s" % (k, hawire.fmt_w(w)) for k, w in pv), ACCENT if any(w > 50 for _, w in pv) else FG))
        if en["gen"] is not None:
            lines.append(("Генератор", self.energy_text("generator", en), FG))
        if not lines:
            lines.append(("", "датчиків інвертора в HA не знайдено" if self.ha.status == "connected" else self.offline_text(), DIM))
        for label, val, col in lines:
            if y > 116:
                break
            tl = f_text.render(label + ":" if label else "", True, DIM)
            s.blit(tl, (x, y))
            vx = x + (tl.get_width() + 2 if label else 0)
            for i, ln in enumerate(wrap(val, f_text, x + W - vx)[:2]):
                s.blit(f_text.render(ln, True, col), (vx, y))
                y += 7
        t = f_small.render("Esc - назад", True, DIM)
        s.blit(t, (x, 124 - t.get_height()))

    def draw_sensor_card(self, eid, st, x, y, W, board):
        """The value big, and the last 24 h; the weather board also the humidity, the pressure and tomorrow."""
        s = self.screen
        if st.get("state") not in (None, "unavailable", "unknown"):
            t = f_big.render(state_text(eid, st), True, ACCENT)
            s.blit(t, (x, y))
            if board:
                extra = []
                for suf, unit in (("_humidity", "%"), ("_pressure", " гПа")):
                    o = self.state(eid.replace("_temperature", suf)) if eid.endswith("_temperature") else None
                    if o and o.get("state") not in ("unavailable", "unknown"):
                        extra.append(num(o["state"], 0) + unit)
                for i, e in enumerate(extra):
                    tv = f_text.render(e, True, FG)
                    s.blit(tv, (x + W - tv.get_width(), y + i * 7))
            y += t.get_height() + 1
        data = self.history(eid)
        if data and len(data) > 1:
            spark(s, data, x, y, W, 22, (255, 190, 80))
            y += 25
        elif data is None:
            s.blit(f_small.render("графік за добу…", True, DIM), (x, y))
            y += 7
        if board:
            p = eid.replace("_temperature", "_pressure")
            if eid.endswith("_temperature") and self.state(p):
                pd = self.history(p)
                if pd and len(pd) > 1:
                    spark(s, pd, x, y, W, 14, (110, 180, 255))
                    y += 17
            fc = self.forecast()
            if fc:
                cond, hi, lo = fc
                txt = "завтра: %s, %s° / %s°" % (COND_UK.get(cond, cond or ""), num(hi, 0), num(lo, 0))
                s.blit(f_text.render(fit(txt, f_text, W), True, FG), (x, y))
                y += 8
        return y

    def draw_confirm(self):
        s = self.screen
        self.panel(8, 38, 112, 54)
        y = 42
        for ln in wrap(self.confirm[0], f_name, 104)[:3]:
            t = f_name.render(ln, True, FG)
            s.blit(t, (64 - t.get_width() / 2, y))
            y += t.get_height()
        for i, lab in enumerate(("Ні", "Так")):
            bx = 22 + i * 46
            on = self.choice == i
            pygame.draw.rect(s, (RED if i else ACCENT) if on else (40, 42, 50), (bx, 76, 38, 12), border_radius=3)
            t = f_name.render(lab, True, BG if on else DIM)
            s.blit(t, (bx + 19 - t.get_width() / 2, 82 - t.get_height() / 2))

    def draw_say(self):
        s = self.screen
        self.panel(4, 30, 120, 66)
        name = friendly(self.say_eid, self.state(self.say_eid), self.names)
        s.blit(f_name.render(fit("Сказати на «%s»" % name, f_name, 112), True, ACCENT), (8, 33))
        lines = wrap(self.say_buf + ("_" if time.monotonic() % 1 < 0.6 else " "), f_text, 110)[-4:]
        for i, ln in enumerate(lines):
            s.blit(f_text.render(ln, True, FG), (8, 43 + i * 8))
        t = f_small.render(("УКР" if self.say_ua else "ENG") + " · Tab - мова · Enter - сказати · Esc", True, DIM)
        s.blit(t, (8, 94 - t.get_height()))

    def draw_help(self):
        lines = ["# ДІМ - клавіші", "Поверх: стрілки - кімната,", "  Enter - увійти, Пробіл - світло,",
                 "  Tab, 0-3 - поверх, Esc - вихід", "У кімнаті: стрілки, Tab - пристрій,",
                 "  Пробіл - дія, + / - - яскравість,", "  гучність; Enter - картка, Esc - назад",
                 "Картка: ↑↓ рядок, ←→ значення,", "  Enter - зробити", "r - оновити план",
                 "Ворота, двері, замки - з «Ні / Так»"]
        if not BIG:                                         # the HAT: its own keys, short
            lines = ["# ДІМ - клавіші", "стік - кімната / пристрій", "PRESS - увійти; картка",
                     "KEY2 - світло; дія", "KEY1 - поверх; пристрій", "KEY3 - назад", "картка: стік ↑↓ ←→,",
                     "  PRESS - зробити", "Ворота, замки - «Так»"]
        self.panel(4, 4, 120, 120)
        y = 8
        for ln in lines:
            f = f_name if ln.startswith("#") else f_text
            t = f.render(fit(ln[2:] if ln.startswith("# ") else ln, f, 112), True, ACCENT if ln.startswith("#") else FG)
            self.screen.blit(t, (9, y))
            y += t.get_height() + 0.5

    def text_center(self, lines, y):
        for ln in lines:
            t = f_text.render(fit(ln, f_text, 124), True, FG)
            self.screen.blit(t, (64 - t.get_width() / 2, y))
            y += t.get_height() + 1

    # ---------------------------------------------------------------- the loop
    def tick(self):
        """Pick up what came from the threads; True when the screen should be drawn again."""
        if self.plans.gen != self.plan_gen or self.ha.reg_gen != self.reg_gen:
            self.rebuild()
        now = time.monotonic()
        for e, t in list(self.pending.items()):
            if now - t > 3:
                del self.pending[e]
                self.dirty = True
        g = self.ha.gen
        if g != self.last_gen:
            self.last_gen = g
            for e in list(self.pending):
                if now - self.pending[e] > 0.3:
                    del self.pending[e]
            self.dirty = True
        blink = int(now / 0.5)
        if blink != getattr(self, "_blink", None):
            self._blink = blink
            self.dirty = True
        d, self.dirty = self.dirty, False
        return d


COND_UK = {"sunny": "сонячно", "clear-night": "ясно", "partlycloudy": "мінлива хмарність", "cloudy": "хмарно",
           "rainy": "дощ", "pouring": "злива", "snowy": "сніг", "snowy-rainy": "мокрий сніг", "fog": "туман",
           "windy": "вітер", "windy-variant": "вітер", "lightning": "гроза", "lightning-rainy": "гроза", "hail": "град",
           "exceptional": "негода"}


def spark(s, data, x, y, w, h, col):
    """The last 24 h as a line, with the lowest and the highest value."""
    t0 = time.time() - 86400
    pts = [(max(t, t0), v) for t, v in data]
    pts.append((time.time(), pts[-1][1]))
    lo, hi = min(v for _, v in pts), max(v for _, v in pts)
    span = (hi - lo) or 1
    pygame.draw.rect(s, (22, 25, 32), (x, y, w, h))
    xy = [(x + (t - t0) / 86400 * w, y + h - 1 - (v - lo) / span * (h - 2)) for t, v in pts]
    step = []
    for i, p in enumerate(xy):
        if i:
            step.append((p[0], step[-1][1]))
        step.append(p)
    if len(step) > 1:
        pygame.draw.lines(s, col, False, step, 1)
    for txt, ty in ((num(hi), y), (num(lo), y + h - 6)):
        t = f_val.render(txt, True, (170, 170, 175))
        s.blit(t, (x + w - t.get_width() - 1, ty))


def battery_icon(s, x, y, soc, p, k=1.0):
    """A battery filled to its charge: green / yellow / red; a bolt while it charges."""
    w, h = 7 * k, 4 * k
    pygame.draw.rect(s, (10, 12, 16), (x - w / 2 - 1, y - h / 2 - 1, w + 3, h + 2))
    col = (130, 130, 138) if soc is None else GREEN if soc > 50 else ACCENT if soc > 20 else RED
    pygame.draw.rect(s, col, (x - w / 2, y - h / 2, w, h), 1)
    pygame.draw.rect(s, col, (x + w / 2, y - h / 4, 0.8 * k, h / 2))
    if soc is not None:
        pygame.draw.rect(s, col, (x - w / 2 + 0.7, y - h / 2 + 0.7, max(0.5, (w - 1.4) * min(100, soc) / 100), h - 1.4))
    if p is not None and p < -20:
        pygame.draw.polygon(s, (255, 255, 255), [(x + 0.4 * k, y - h / 2 - 0.3), (x - 1.1 * k, y + 0.3 * k), (x + 0.2 * k, y + 0.3 * k),
                                                 (x - 0.4 * k, y + h / 2 + 0.3), (x + 1.1 * k, y - 0.3 * k), (x - 0.2 * k, y - 0.3 * k)])


def energy_icon(s, kind, en, x, y):
    if kind == "battery":
        b = (en or {}).get("bat") or {}
        battery_icon(s, x, y, b.get("soc"), b.get("p"))
        if b.get("soc") is not None:
            t = f_val.render("%d%%" % round(b["soc"]), True, FG)
            pygame.draw.rect(s, (10, 12, 16), (x + 4.5, y - t.get_height() / 2, t.get_width() + 1, t.get_height()))
            s.blit(t, (x + 5, y - t.get_height() / 2))
    elif kind == "grid":
        on = (en or {}).get("grid")
        col = CYAN if on else RED if on is False else (130, 130, 138)
        pygame.draw.circle(s, (10, 12, 16), (x, y), 3.3)
        pygame.draw.polygon(s, col, [(x + 0.8, y - 3), (x - 1.8, y + 0.4), (x - 0.1, y + 0.4), (x - 0.8, y + 3), (x + 1.8, y - 0.4), (x + 0.1, y - 0.4)])
    else:
        g = (en or {}).get("gen")
        col = ACCENT if (g or 0) > 50 else (130, 130, 138)
        pygame.draw.circle(s, (10, 12, 16), (x, y), 3.3)
        pygame.draw.circle(s, col, (x, y), 2.8, 1)
        t = f_val.render("G", True, col)
        s.blit(t, (x - t.get_width() / 2, y - t.get_height() / 2))


def bulb(s, x, y, r, on, rgb=None):
    """A lamp: lit (in its colour, if it has one) or dark."""
    lit = rgb or (255, 214, 90)
    if on:
        pygame.draw.circle(s, mix(lit, (0, 0, 0), 0.45), (x, y), r + 1.3)
    pygame.draw.circle(s, lit if on else (55, 55, 60), (x, y), r)
    if not on:
        pygame.draw.circle(s, (150, 150, 155), (x, y), r, 1)


def icon(s, eid, v, st, x, y, dc=None, av_on=None):
    """The device's mark on the plan, coloured by its state."""
    d, kind = domain(eid), v.get("kind")
    state = (st or {}).get("state")
    gone = st is not None and state in ("unavailable", "unknown")
    on = is_on(eid, st) if av_on is None else av_on
    grey = (85, 85, 90)
    dark = (10, 12, 16)
    if v.get("lamp"):
        rgb = ((st or {}).get("attributes") or {}).get("rgb_color")
        bulb(s, x, y, 2.2, on and not gone, tuple(rgb) if on and rgb and len(rgb) == 3 else None)
        if gone:
            pygame.draw.line(s, grey, (x - 1.5, y - 1.5), (x + 1.5, y + 1.5), 1)
    elif kind == "projector":
        col = (230, 235, 255) if on else (130, 130, 138)
        pygame.draw.rect(s, dark, (x - 3, y - 2.5, 6, 5))
        pygame.draw.rect(s, col, (x - 2.5, y - 2, 5, 4), border_radius=1)
        pygame.draw.circle(s, (90, 160, 255) if on else dark, (x, y), 1.2)
    elif kind == "soundbar":
        col = GREEN if on else (130, 130, 138)
        pygame.draw.rect(s, dark, (x - 4.5, y - 1.8, 9, 3.6))
        pygame.draw.rect(s, col, (x - 4, y - 1.2, 8, 2.4), border_radius=1)
    elif kind == "speaker":
        col = GREEN if state == "playing" else (255, 190, 80) if on and not gone else (130, 130, 138) if not gone else grey
        pygame.draw.circle(s, dark, (x, y), 3.2)
        pygame.draw.circle(s, col, (x, y), 2.6, 1)
        pygame.draw.circle(s, col, (x, y), 1)
    elif kind == "screen":
        on = screen_down(st)
        col = (235, 235, 235) if on else (110, 110, 118)
        a = math.radians(v.get("rot") or 0)
        pygame.draw.line(s, col, (x - 4 * math.cos(a), y + 4 * math.sin(a)), (x + 4 * math.cos(a), y - 4 * math.sin(a)), 2 if on else 1)
    elif d == "sensor" or kind == "weather":
        a = (st or {}).get("attributes") or {}
        try:
            val = float(state)
            txt = "%d°" % round(val) if a.get("unit_of_measurement", "°C").startswith("°") else "%g" % val
            col = BLUE if val < 18 else GREEN if val < 25 else (255, 150, 60)
        except (TypeError, ValueError):
            txt, col = "?°", grey
        t = f_val.render(txt, True, col)
        w, h = t.get_width() + 2, t.get_height()
        pygame.draw.rect(s, dark, (x - w / 2, y - h / 2, w, h), border_radius=2)
        if kind == "weather":
            pygame.draw.rect(s, (90, 140, 200), (x - w / 2, y - h / 2, w, h), 1, border_radius=2)
        s.blit(t, (x - t.get_width() / 2, y - h / 2))
    elif d == "binary_sensor":
        a = (st or {}).get("attributes") or {}
        cls = a.get("device_class") or dc
        col = (RED if cls in ("motion", "occupancy", "presence") else (255, 150, 60)) if on else (70, 72, 80)
        pygame.draw.circle(s, col, (x, y), 1.3)
    elif d == "cover":
        col = BLUE if on else ((255, 150, 60) if state in ("opening", "closing") else (120, 120, 128))
        if gone:
            col = grey
        pygame.draw.rect(s, dark, (x - 3, y - 2.5, 6, 5))
        for i in range(3):
            pygame.draw.line(s, col, (x - 2.5, y - 1.7 + i * 1.7), (x + 2.5, y - 1.7 + i * 1.7), 1)
    elif d == "media_player":                                    # a TV
        col = GREEN if state == "playing" else ACCENT if on else (120, 120, 128)
        if gone:
            col = grey
        pygame.draw.rect(s, dark, (x - 3.5, y - 2.8, 7, 5.6))
        pygame.draw.rect(s, col, (x - 3, y - 2.3, 6, 4), 1)
        pygame.draw.line(s, col, (x - 1.5, y + 2.6), (x + 1.5, y + 2.6), 1)
    elif d == "climate":
        col = CYAN if on else (120, 120, 128)
        for i in range(3):
            a = i * math.pi / 3
            pygame.draw.line(s, col, (x - 2.6 * math.cos(a), y - 2.6 * math.sin(a)),
                             (x + 2.6 * math.cos(a), y + 2.6 * math.sin(a)), 1)
    elif d == "lock":
        col = RED if state == "unlocked" else GREEN if state == "locked" else grey
        pygame.draw.rect(s, col, (x - 2, y - 0.5, 4, 3))
        pygame.draw.circle(s, col, (x, y - 0.8), 1.6, 1)
    else:
        col = GREEN if on else (55, 58, 64)
        if gone:
            col = (40, 40, 44)
        pygame.draw.rect(s, col, (x - 2, y - 2, 4, 4), border_radius=1)
        pygame.draw.rect(s, (160, 160, 165) if not on else (200, 255, 210), (x - 2, y - 2, 4, 4), 1, border_radius=1)


def main():
    screen = lcd.init()
    clock = pygame.time.Clock()
    app = House(screen)
    running = True
    while running:
        for ev in pygame.event.get():
            if ev.type == pygame.QUIT:
                running = False
            elif ev.type == pygame.KEYDOWN:
                running = app.key(ev) and running
        if app.tick():
            app.draw()
        clock.tick(20)
    app.ha.close()
    lcd.quit()


if __name__ == "__main__":
    main()
