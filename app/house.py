"""ДІМ: the house plan from above, floor by floor, with the Home Assistant devices on it.

The rooms come from the house3d plan server (the same plan as the 3D model, kept on the device for the
times without the network), the devices sit where the 3D model shows them; their states and the
controls - Home Assistant over its WebSocket API (hawire.py). A room glows while a lamp in it is on.

The HA address and a long-lived token: ~/.config/lcdtoy/house.env (mode 600, see config/house.env.example):
    HA_URL=http://10.80.39.78:8123,https://hass.ibotz.space     (tried in turn)
    HA_TOKEN=...                 (better from an HA user without admin rights)
    PLAN_URL=http://10.80.39.14:8095
    CONFIRM=switch.some_gate     (more entities that ask before they act)

Keys: arrows - the device that way, Enter - its action (toggle; a cover - open / close; media - play /
pause), Space or i - details (brightness, position, volume, temperature: ← → there), Tab / PgDn / PgUp or
0-3 - the floor, r - reload the plan, F1 - keys, Esc - exit. HAT: the stick, PRESS - the action, KEY1 - the
floor, KEY2 - details, KEY3 - exit. Gates, doors and locks ask first («Ні» chosen until ← →).
"""
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
            "playing": "грає", "paused": "пауза", "idle": "очікує", "standby": "сплячий", "buffering": "буферизація",
            "locked": "зачинено", "unlocked": "відчинено", "locking": "зачиняється", "unlocking": "відчиняється",
            "jammed": "заклинило", "heat": "обігрів", "cool": "охолодження", "auto": "авто", "dry": "осушення",
            "fan_only": "вентилятор", "heat_cool": "авто", "armed_away": "охорона", "armed_home": "охорона вдома",
            "disarmed": "знято з охорони", "triggered": "ТРИВОГА", "docked": "на базі", "cleaning": "прибирає",
            "returning": "повертається"}
BIN_UK = {"motion": ("рух", "тихо"), "occupancy": ("є хтось", "нікого"), "presence": ("є хтось", "нікого"),
          "door": ("відчинено", "зачинено"), "window": ("відчинено", "зачинено"), "opening": ("відчинено", "зачинено"),
          "garage_door": ("відчинено", "зачинено"), "moisture": ("ПРОТІКАННЯ", "сухо"), "smoke": ("ДИМ", "норма"),
          "gas": ("ГАЗ", "норма"), "carbon_monoxide": ("CO!", "норма")}
TOGGLE = {"light", "switch", "fan", "input_boolean", "humidifier"}
DANGER_WORDS = ("vorot", "gate", "garage_door", "ворот", "door", "двер", "хвірт", "lock", "замок")


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


def friendly(eid, st, names):
    n = (st or {}).get("attributes", {}).get("friendly_name") if st else None
    return n or names.get(eid) or eid.split(".", 1)[-1].replace("_", " ")


def state_text(eid, st, dc=None):
    if not st:
        return "немає даних"
    s, a, d = st.get("state"), st.get("attributes") or {}, domain(eid)
    if s in ("unavailable", "unknown", None):
        return STATE_UK.get(s, "невідомо")
    if d == "sensor":
        try:
            v = float(s)
            s = ("%.1f" % v).rstrip("0").rstrip(".") if abs(v) < 1000 else "%d" % v
        except ValueError:
            pass
        return "%s %s" % (s, a.get("unit_of_measurement", "")) if a.get("unit_of_measurement") else s
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
    if d == "media_player" and s == "playing" and a.get("media_title"):
        out += ": " + str(a["media_title"])
    return out


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
        self.plan_gen = self.reg_gen = -1
        self.floor = 0
        self.sel = {}                              # floor id -> the selected entity
        self.view = "map"                          # map / details / confirm / help
        self.confirm = None                        # (question, domain, service, eid, data)
        self.choice = 0
        self.toast = None
        self.pending = {}                          # eid -> when an action was sent (drawn as «...»)
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
            self.places = {e: v for e, v in self.places.items() if e in states}
            hawire.save_ha_cache(self.places, states)
            self.names = {e: states[e]["attributes"].get("friendly_name") for e in self.places}
            self.classes = {e: states[e]["attributes"].get("device_class") for e in self.places}
            self.ha.subscribe(list(self.places))
        elif not self.places:                      # no HA yet and nothing cached: the plan's own devices
            self.places = hawire.placements(self.plan, self.plans.layout, {}, lambda e: None)
        self.rooms_cache = {}
        self.dirty = True

    def devices(self, fid):
        return [(e, v) for e, v in self.places.items() if v.get("f") == fid]

    def rooms(self, fid):
        return [r for r in self.plan.get("rooms") or [] if r.get("floor") == fid and "x" in r and "w" in r]

    def selected(self):
        fid = self.fid()
        devs = dict(self.devices(fid))
        e = self.sel.get(fid)
        if e not in devs and devs:
            rooms = self.rooms(fid)
            cx = sum(r["x"] + r["w"] / 2 for r in rooms) / max(1, len(rooms))
            cz = sum(r["z"] + r["d"] / 2 for r in rooms) / max(1, len(rooms))
            e = min(devs, key=lambda k: math.hypot(devs[k]["x"] - cx, devs[k]["z"] - cz))
            self.sel[fid] = e
        return e if e in devs else None

    def state(self, eid):
        return self.ha.get(eid)

    def lit_groups(self, fid):
        """The rooms (their groups) with a lamp on."""
        lit = set()
        rooms = self.rooms(fid)
        for e, v in self.devices(fid):
            if not v.get("lamp") or not is_on(e, self.state(e)):
                continue
            for r in rooms:
                if r["x"] - 0.05 <= v["x"] <= r["x"] + r["w"] + 0.05 and r["z"] - 0.05 <= v["z"] <= r["z"] + r["d"] + 0.05:
                    lit.add(r.get("group") or r["id"])
                    break
        return lit

    def danger(self, eid):
        st = self.state(eid) or {}
        if eid in self.confirm_ids or domain(eid) in ("lock", "alarm_control_panel"):
            return True
        dc = st.get("attributes", {}).get("device_class") or self.classes.get(eid)
        if domain(eid) == "cover" and dc in ("garage", "gate", "door"):
            return True
        text = (eid + " " + friendly(eid, st, self.names)).lower()
        return domain(eid) in ("cover", "switch", "button") and any(w in text for w in DANGER_WORDS)

    # ---------------------------------------------------------------- the geometry
    def transform(self, fid):
        rooms = self.rooms(fid)
        if not rooms:
            return lambda x, z: (64, 64), 1
        x0 = min(r["x"] for r in rooms)
        x1 = max(r["x"] + r["w"] for r in rooms)
        z0 = min(r["z"] for r in rooms)
        z1 = max(r["z"] + r["d"] for r in rooms)
        aw, ah = 124, BAR - TOP - 4
        k = min(aw / max(0.5, x1 - x0), ah / max(0.5, z1 - z0))
        ox = 2 + (aw - (x1 - x0) * k) / 2 - x0 * k
        oz = TOP + 2 + (ah - (z1 - z0) * k) / 2 - z0 * k
        return (lambda x, z: (ox + x * k, oz + z * k)), k

    # ---------------------------------------------------------------- actions
    def action(self, eid):
        st = self.state(eid)
        d = domain(eid)
        if self.ha.status != "connected":
            return self.say(self.offline_text(), RED)
        if not st or st.get("state") == "unavailable":
            return self.say("пристрій недоступний", RED)
        s = st.get("state")
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
            self.view = "details"                   # sensors, climate: nothing to switch - the details
            return
        self.ask_or_call(eid, *call)

    def ask_or_call(self, eid, dom, service, data):
        if self.danger(eid):
            verb = {"open_cover": "Відкрити", "close_cover": "Закрити", "unlock": "Відчинити", "lock": "Зачинити",
                    "turn_on": "Увімкнути", "turn_off": "Вимкнути", "press": "Натиснути",
                    "stop_cover": "Зупинити"}.get(service, service)
            self.confirm = ("%s «%s»?" % (verb, friendly(eid, self.state(eid), self.names)), dom, service, eid, data)
            self.choice = 0
            self.back_to = self.view
            self.view = "confirm"
            return
        self.send(dom, service, eid, data)

    def send(self, dom, service, eid, data):
        if self.ha.call(dom, service, eid, **data):
            self.pending[eid] = time.monotonic()
            lcd.play("select")
        else:
            self.say(self.offline_text(), RED)

    def offline_text(self):
        return {"none": "немає токена HA (house.env)", "auth": "HA: невірний токен",
                "connecting": "з'єднання з HA…", "loading": "завантаження з HA…"}.get(self.ha.status, "немає зв'язку з HA")

    def say(self, text, color=FG):
        self.toast = (text, color, time.monotonic())
        self.dirty = True

    def adjust(self, eid, step):
        """← → in the details: brightness, volume, the target temperature, the cover's position."""
        st = self.state(eid) or {}
        a, d = st.get("attributes") or {}, domain(eid)
        if d == "light" and ("brightness" in a or a.get("supported_color_modes", ["onoff"]) != ["onoff"]):
            pct = round((a.get("brightness") or 0) * 100 / 255) if st.get("state") == "on" else 0
            pct = max(0, min(100, (pct // 10 + step) * 10 if step > 0 else math.ceil(pct / 10 + step) * 10))
            if pct == 0:
                self.send(d, "turn_off", eid, {})
            else:
                self.send(d, "turn_on", eid, {"brightness_pct": pct})
        elif d == "media_player" and a.get("volume_level") is not None:
            v = max(0.0, min(1.0, round(a["volume_level"] * 20 + step) / 20))
            self.send(d, "volume_set", eid, {"volume_level": v})
        elif d == "climate" and a.get("temperature") is not None:
            t = a["temperature"] + step * (a.get("target_temp_step") or 0.5)
            t = max(a.get("min_temp", 5), min(a.get("max_temp", 35), t))
            self.send(d, "set_temperature", eid, {"temperature": t})
        elif d == "cover" and a.get("current_position") is not None:
            p = max(0, min(100, (a["current_position"] // 10 + step) * 10))
            self.ask_or_call(eid, d, "set_cover_position", {"position": p})

    def move(self, dx, dz):
        """The nearest device that way (straight ahead counts more than aside)."""
        fid = self.fid()
        cur = self.selected()
        if cur is None:
            return
        devs = self.devices(fid)
        here = self.places[cur]
        best = None
        for e, v in devs:
            if e == cur:
                continue
            vx, vz = v["x"] - here["x"], v["z"] - here["z"]
            ahead = vx * dx + vz * dz
            if ahead <= 0.05:
                continue
            side = abs(vx * dz - vz * dx)
            score = ahead + side * 2.2
            if best is None or score < best[0]:
                best = (score, e)
        if best:
            self.sel[fid] = best[1]
            self.dirty = True

    # ---------------------------------------------------------------- keys
    def key(self, ev):
        k, hat = ev.key, getattr(ev, "hat", False)
        self.dirty = True
        if self.view == "help":
            self.view = "map"
            return True
        if self.view == "confirm":
            if k in (pygame.K_LEFT, pygame.K_RIGHT, pygame.K_UP, pygame.K_DOWN, pygame.K_TAB):
                self.choice ^= 1
            elif k in (pygame.K_RETURN, pygame.K_SPACE) or (hat and k == pygame.K_2):
                if self.choice == 1:
                    _, dom, service, eid, data = self.confirm
                    self.send(dom, service, eid, data)
                self.view = self.back_to
            elif k == pygame.K_y:
                _, dom, service, eid, data = self.confirm
                self.send(dom, service, eid, data)
                self.view = self.back_to
            elif k in (pygame.K_ESCAPE, pygame.K_BACKSPACE, pygame.K_n) or (hat and k == pygame.K_3):
                self.view = self.back_to
            return True
        eid = self.selected()
        if self.view == "details":
            if k in (pygame.K_ESCAPE, pygame.K_BACKSPACE, pygame.K_SPACE, pygame.K_i) or (hat and k in (pygame.K_2, pygame.K_3)):
                self.view = "map"
            elif eid and k == pygame.K_RETURN:
                if domain(eid) == "climate":
                    st = self.state(eid) or {}
                    self.ask_or_call(eid, "climate", "turn_off" if st.get("state") not in ("off", None) else "turn_on", {})
                else:
                    self.action(eid)
            elif eid and k in (pygame.K_LEFT, pygame.K_RIGHT, pygame.K_MINUS, pygame.K_EQUALS):
                self.adjust(eid, 1 if k in (pygame.K_RIGHT, pygame.K_EQUALS) else -1)
            elif eid and domain(eid) == "cover" and k in (pygame.K_UP, pygame.K_DOWN, pygame.K_s):
                service = {pygame.K_UP: "open_cover", pygame.K_DOWN: "close_cover", pygame.K_s: "stop_cover"}[k]
                self.ask_or_call(eid, "cover", service, {}) if service != "stop_cover" else \
                    self.send("cover", service, eid, {})
            elif eid and domain(eid) == "media_player" and k in (pygame.K_UP, pygame.K_DOWN):
                self.send("media_player", "media_next_track" if k == pygame.K_UP else "media_previous_track", eid, {})
            return True
        # the map
        if k == pygame.K_ESCAPE or (hat and k == pygame.K_3):
            return False
        if k == pygame.K_UP:
            self.move(0, -1)
        elif k == pygame.K_DOWN:
            self.move(0, 1)
        elif k == pygame.K_LEFT:
            self.move(-1, 0)
        elif k == pygame.K_RIGHT:
            self.move(1, 0)
        elif k == pygame.K_RETURN:
            if eid:
                self.action(eid)
        elif k in (pygame.K_SPACE, pygame.K_i) or (hat and k == pygame.K_2):
            if eid:
                self.view = "details"
        elif k in (pygame.K_TAB, pygame.K_PAGEDOWN, pygame.K_f) or (hat and k == pygame.K_1):
            self.floor = (self.floor + 1) % max(1, len(self.floors()))
        elif k == pygame.K_PAGEUP:
            self.floor = (self.floor - 1) % max(1, len(self.floors()))
        elif k in (pygame.K_0, pygame.K_1, pygame.K_2, pygame.K_3) and not hat:
            n = k - pygame.K_0
            for i, f in enumerate(self.floors()):
                if (n == 0 and f.get("elevation", 0) < 0) or (n and f.get("name", "").startswith(str(n))):
                    self.floor = i
        elif k == pygame.K_r:
            self.plans.fetch()
            self.say("оновлюю план…")
        elif k == pygame.K_F1:
            self.view = "help"
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
        lcd.flip()

    def draw_tabs(self, fid):
        s = self.screen
        x = 1
        names = [f.get("name") or f["id"] for f in self.floors()]
        if sum(f_tab.size(n)[0] + 7 for n in names) > 104:      # the HAT: «П», «1», «2»
            names = [n.split()[0] if n[:1].isdigit() else n[:1] for n in names]
        for f, name in zip(self.floors(), names):
            w = f_tab.size(name)[0] + 5
            if f["id"] == fid:
                pygame.draw.rect(s, ACCENT, (x, 1, w, 11), border_radius=3)
                col = BG
            else:
                pygame.draw.rect(s, (50, 50, 55), (x, 1, w, 11), 1 if BIG else 1, border_radius=3)
                col = DIM
            t = f_tab.render(name, True, col)
            s.blit(t, (x + 2.5, 6.5 - t.get_height() / 2))
            x += w + 2
        # how many lamps are on here, and the link to HA
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
        th = 0.5 if BIG else 1
        rects = []
        for r in rooms:
            (x0, y0), (x1, y1) = tf(r["x"], r["z"]), tf(r["x"] + r["w"], r["z"] + r["d"])
            g = r.get("group") or r["id"]
            outdoor = r.get("walls") in (False, "railing")
            fill, edge = (LIT, LIT_EDGE) if g in lit else (OUT, OUT_EDGE) if outdoor else (ROOM, ROOM_EDGE)
            rects.append((r, g, (x0, y0, x1 - x0, y1 - y0), fill, edge))
        for r, g, rc, fill, edge in rects:
            pygame.draw.rect(s, fill, rc)
            pygame.draw.rect(s, edge, rc, th if not BIG else 1)
        # the parts of one room (a group) without the line between them
        for i, (r, g, rc, fill, _) in enumerate(rects):
            for r2, g2, rc2, _, _ in rects[i + 1:]:
                if g2 != g or not r.get("group"):
                    continue
                for a, b in ((rc, rc2), (rc2, rc)):
                    if abs(a[0] + a[2] - b[0]) < 0.6:                # side by side
                        y0, y1 = max(a[1], b[1]) + 1, min(a[1] + a[3], b[1] + b[3]) - 1
                        if y1 > y0:
                            pygame.draw.line(s, fill, (b[0], y0), (b[0], y1), 1)
                    if abs(a[1] + a[3] - b[1]) < 0.6:                # one above the other
                        x0, x1 = max(a[0], b[0]) + 1, min(a[0] + a[2], b[0] + b[2]) - 1
                        if x1 > x0:
                            pygame.draw.line(s, fill, (x0, b[1]), (x1, b[1]), 1)
        # names: one per room, on its biggest part
        best = {}
        for r, g, rc, fill, edge in rects:
            if r.get("name") and (g not in best or rc[2] * rc[3] > best[g][1][2] * best[g][1][3]):
                best[g] = (r, rc)
        for g, (r, rc) in best.items():
            col = LIT_TEXT if g in lit else ROOM_TEXT if r.get("walls") not in (False, "railing") else (140, 125, 105)
            self.label(r["name"], rc, col)

    def label(self, name, rc, col):
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
            self.screen.blit(t, (x + (w - t.get_width()) / 2, y0))
            y0 += lh

    def draw_devices(self, fid):
        s = self.screen
        tf, k = self.transform(fid)
        cur = self.selected()
        blink = time.monotonic() % 1 < 0.6
        for e, v in sorted(self.devices(fid), key=lambda ev: ev[0] == cur):
            x, y = tf(v["x"], v["z"])
            st = self.state(e)
            icon(s, e, v, st, x, y, self.classes.get(e))
            if e in self.pending:
                pygame.draw.circle(s, FG, (x, y), 4, 1)
        if cur:
            x, y = tf(self.places[cur]["x"], self.places[cur]["z"])
            pygame.draw.circle(s, ACCENT if blink else (140, 110, 0), (x, y), 5.2, 1)

    def draw_bar(self):
        s = self.screen
        pygame.draw.line(s, (60, 60, 66), (0, BAR + 1), (128, BAR + 1))
        if self.toast and time.monotonic() - self.toast[2] < 3:
            t = f_text.render(fit(self.toast[0], f_text, 124), True, self.toast[1])
            s.blit(t, (2, BAR + 3))
            return
        notice = self.ha.notice
        if notice and time.monotonic() - notice[1] < 4:
            t = f_text.render(fit(notice[0], f_text, 124), True, RED)
            s.blit(t, (2, BAR + 3))
            return
        eid = self.selected()
        if not eid:
            t = f_text.render("на цьому поверсі немає пристроїв", True, DIM)
            s.blit(t, (2, BAR + 3))
            return
        st = self.state(eid)
        name = friendly(eid, st, self.names)
        if self.ha.status != "connected" and not st:
            state, col = self.offline_text(), DIM
        else:
            state = state_text(eid, st, self.classes.get(eid))
            col = ACCENT if is_on(eid, st) else (RED if (st or {}).get("state") == "unavailable" else FG)
        t = f_name.render(fit(name, f_name, 124), True, FG)
        s.blit(t, (2, BAR + 2))
        t2 = f_text.render(fit(state, f_text, 124), True, col)
        s.blit(t2, (2, BAR + 2 + t.get_height()))

    def panel(self, x, y, w, h):
        pygame.draw.rect(self.screen, (14, 16, 22), (x, y, w, h), border_radius=4)
        pygame.draw.rect(self.screen, (90, 95, 110), (x, y, w, h), 1, border_radius=4)

    def draw_details(self):
        s = self.screen
        eid = self.selected()
        if not eid:
            self.view = "map"
            return
        st = self.state(eid) or {}
        a, d = st.get("attributes") or {}, domain(eid)
        self.panel(4, 16, 120, 108)
        x, y = 8, 19
        name = friendly(eid, st, self.names)
        for ln in wrap(name, f_name, 112)[:2]:
            t = f_name.render(ln, True, ACCENT)
            s.blit(t, (x, y))
            y += t.get_height()
        t = f_small.render(fit(eid, f_small, 112), True, DIM)
        s.blit(t, (x, y))
        y += t.get_height() + 2
        rows = [("Стан", state_text(eid, st, self.classes.get(eid)) if st else self.offline_text())]
        hints = []
        bar = None
        if d == "light":
            if a.get("brightness") is not None or st.get("state") == "off":
                pct = round((a.get("brightness") or 0) * 100 / 255) if st.get("state") == "on" else 0
                bar = ("Яскравість", pct / 100, "%d%%" % pct)
            if a.get("color_temp_kelvin"):
                rows.append(("Колір", "%d K" % a["color_temp_kelvin"]))
            hints = ["Enter - увімк./вимк.", "← → - яскравість"]
        elif d == "cover":
            if a.get("current_position") is not None:
                bar = ("Відкрито", a["current_position"] / 100, "%s%%" % a["current_position"])
            hints = ["Enter / ↑ ↓ - відкрити / закрити", "s - стоп" + (", ← → - на 10%" if bar else "")]
        elif d == "media_player":
            if a.get("media_title"):
                rows.append(("Грає", str(a["media_title"])))
            if a.get("media_artist"):
                rows.append(("Виконавець", str(a["media_artist"])))
            if a.get("source"):
                rows.append(("Джерело", str(a["source"])))
            if a.get("volume_level") is not None:
                bar = ("Гучність", a["volume_level"], "%d%%" % round(a["volume_level"] * 100))
            hints = ["Enter - пауза / грати", "← → - гучність, ↑ ↓ - трек"]
        elif d == "climate":
            if a.get("current_temperature") is not None:
                rows.append(("Зараз", "%s°" % a["current_temperature"]))
            if a.get("temperature") is not None:
                rows.append(("Ціль", "%s°" % a["temperature"]))
            if a.get("current_humidity") is not None:
                rows.append(("Вологість", "%s%%" % a["current_humidity"]))
            hints = ["Enter - увімк./вимк.", "← → - ціль ±%s°" % (a.get("target_temp_step") or 0.5)]
        elif d in ("sensor", "binary_sensor"):
            if a.get("device_class"):
                rows.append(("Тип", str(a["device_class"])))
        elif d in TOGGLE or d in ("lock", "valve"):
            hints = ["Enter - " + ("зачинити / відчинити" if d == "lock" else "увімк./вимк.")]
        if self.danger(eid):
            hints.append("з підтвердженням")
        for label, val in rows:
            t = f_text.render(label + ":", True, DIM)
            s.blit(t, (x, y))
            vx = x + t.get_width() + 2
            col = ACCENT if label == "Стан" and is_on(eid, st) else FG
            for i, ln in enumerate(wrap(val, f_text, 120 - vx)[:2]):
                tv = f_text.render(ln, True, col)
                s.blit(tv, (vx if i == 0 else x + 4, y))
                y += tv.get_height()
        if d == "sensor" and st.get("state") not in (None, "unavailable", "unknown"):
            t = f_big.render(state_text(eid, st), True, ACCENT)
            s.blit(t, (64 - t.get_width() / 2, y + 2))
            y += t.get_height() + 4
        if bar:
            label, frac, txt = bar
            y += 2
            t = f_text.render(label, True, DIM)
            s.blit(t, (x, y))
            tv = f_text.render(txt, True, FG)
            s.blit(tv, (120 - tv.get_width(), y))
            y += t.get_height() + 1
            pygame.draw.rect(s, (45, 48, 58), (x, y, 112, 5), border_radius=2)
            if frac > 0:
                pygame.draw.rect(s, ACCENT, (x, y, max(2, 112 * min(1, frac)), 5), border_radius=2)
            y += 8
        yb = 122
        for h in reversed(hints + ["Esc - назад"]):
            t = f_small.render(fit(h, f_small, 112), True, DIM)
            yb -= t.get_height()
            if yb < y:
                break
            s.blit(t, (x, yb))

    def draw_confirm(self):
        s = self.screen
        q = self.confirm[0]
        self.panel(8, 38, 112, 54)
        lines = wrap(q, f_name, 104)[:3]
        y = 42
        for ln in lines:
            t = f_name.render(ln, True, FG)
            s.blit(t, (64 - t.get_width() / 2, y))
            y += t.get_height()
        for i, lab in enumerate(("Ні", "Так")):
            bx = 22 + i * 46
            on = self.choice == i
            pygame.draw.rect(s, (RED if i else ACCENT) if on else (40, 42, 50), (bx, 76, 38, 12), border_radius=3)
            t = f_name.render(lab, True, BG if on else DIM)
            s.blit(t, (bx + 19 - t.get_width() / 2, 82 - t.get_height() / 2))

    def draw_help(self):
        lines = ["# ДІМ - клавіші", "стрілки - пристрій", "Enter - дія (увімк./вимк.,", "  штори, пауза)",
                 "Пробіл / i - деталі", "Tab, PgUp/PgDn, 0-3 - поверх", "r - оновити план", "Esc - вихід",
                 "", "Ворота, двері, замки -", "з підтвердженням"]
        self.panel(4, 4, 120, 120)
        y = 8
        for ln in lines:
            f = f_name if ln.startswith("#") else f_text
            t = f.render(ln.lstrip("# "), True, ACCENT if ln.startswith("#") else FG)
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
            for e in list(self.pending):           # a state change came: the «...» goes
                if now - self.pending[e] > 0.3:
                    del self.pending[e]
            self.dirty = True
        blink = int(now / 0.5)
        if blink != getattr(self, "_blink", None):
            self._blink = blink
            self.dirty = True
        d, self.dirty = self.dirty, False
        return d


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


def bulb(s, x, y, r, on):
    if on:
        pygame.draw.circle(s, (120, 95, 20), (x, y), r + 1.3)
    pygame.draw.circle(s, (255, 214, 90) if on else (55, 55, 60), (x, y), r)
    if not on:
        pygame.draw.circle(s, (150, 150, 155), (x, y), r, 1)


def icon(s, eid, v, st, x, y, dc=None):
    """The device's mark on the plan, coloured by its state."""
    d = domain(eid)
    state = (st or {}).get("state")
    gone = st is not None and state in ("unavailable", "unknown")
    on = is_on(eid, st)
    grey = (85, 85, 90)
    if v.get("lamp"):
        bulb(s, x, y, 2.2, on and not gone)
        if gone:
            pygame.draw.line(s, grey, (x - 1.5, y - 1.5), (x + 1.5, y + 1.5), 1)
    elif d == "sensor":
        a = (st or {}).get("attributes") or {}
        try:
            val = float(state)
            txt = "%d°" % round(val) if a.get("unit_of_measurement", "°C").startswith("°") else "%g" % val
            col = BLUE if val < 18 else GREEN if val < 25 else (255, 150, 60)
        except (TypeError, ValueError):
            txt, col = "?°", grey
        t = f_val.render(txt, True, col)
        w, h = t.get_width() + 2, t.get_height()
        pygame.draw.rect(s, (10, 12, 16), (x - w / 2, y - h / 2, w, h), border_radius=2)
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
        pygame.draw.rect(s, (10, 12, 16), (x - 3, y - 2.5, 6, 5))
        for i in range(3):
            pygame.draw.line(s, col, (x - 2.5, y - 1.7 + i * 1.7), (x + 2.5, y - 1.7 + i * 1.7), 1)
    elif d == "media_player":
        col = GREEN if state == "playing" else ACCENT if on else (120, 120, 128)
        if gone:
            col = grey
        pygame.draw.polygon(s, col, [(x - 2, y - 2.5), (x - 2, y + 2.5), (x + 2.6, y)])
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
