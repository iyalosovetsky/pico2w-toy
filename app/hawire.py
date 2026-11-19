"""ДІМ: the house plan (the house3d plan server) and Home Assistant over its WebSocket API - no pygame here.

The WebSocket is a small client on the standard library (socket + ssl): the PicoCalc has no websocket
package, and the API needs only text frames. One connection: auth with a long-lived token, the states and
the registries once (to place the devices by their HA areas, like the 3D model does), then
subscribe_entities for the placed entities only (their changes as compressed diffs) and call_service.

The plan and the layout come from GET <plan server>/plan and /layout (the home LAN, no auth) and are kept
in ~/.config/lcdtoy/house-plan.json; the placed devices and their names in house-ha.json - the plan and
the devices are there without the network too.
"""
import base64
import itertools
import json
import math
import os
import re
import socket
import ssl
import struct
import threading
import time
import urllib.request
from urllib.parse import urlsplit

CONF_DIR = os.path.expanduser("~/.config/lcdtoy")
ENV_FILE = os.environ.get("HOUSE_ENV", os.path.join(CONF_DIR, "house.env"))
PLAN_CACHE = os.path.join(CONF_DIR, "house-plan.json")
HA_CACHE = os.path.join(CONF_DIR, "house-ha.json")
PLAN_URL = "http://10.80.39.14:8095"


def read_env(path=ENV_FILE):
    """KEY=VALUE lines (# comments, optional quotes) -> dict; {} without the file."""
    out = {}
    try:
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, v = line.split("=", 1)
                out[k.strip()] = v.strip().strip("'\"")
    except OSError:
        pass
    return out


def _load(path):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def _save(path, data):
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path + ".tmp", "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False)
        os.replace(path + ".tmp", path)
    except OSError:
        pass


# ---------------------------------------------------------------- the plan server

class PlanSource:
    """The plan and the layout: the cache at once, the server's copy in a thread (fetch())."""

    def __init__(self, base=None):
        self.base = (base or PLAN_URL).rstrip("/")
        c = _load(PLAN_CACHE) or {}
        self.plan, self.layout, self.at = c.get("plan"), c.get("layout") or {}, c.get("at")
        self.gen = 1 if self.plan else 0       # bumped when a new plan arrives
        self.status = "cache" if self.plan else "none"
        self.error = None

    def fetch(self):
        threading.Thread(target=self._fetch, daemon=True).start()

    def _get(self, path):
        with urllib.request.urlopen(self.base + path, timeout=8) as r:
            return json.loads(r.read().decode("utf-8"))

    def _fetch(self):
        self.status = "loading"
        try:
            plan = self._get("/plan").get("plan")
            if not isinstance(plan, dict) or not isinstance(plan.get("rooms"), list):
                raise ValueError("no plan")
            try:
                layout = self._get("/layout").get("layout") or {}
            except (OSError, ValueError):
                layout = self.layout or {}
        except (OSError, ValueError) as e:
            self.error = str(e)
            self.status = "cache" if self.plan else "none"
            return
        self.plan, self.layout, self.at = plan, layout, time.time()
        _save(PLAN_CACHE, {"plan": plan, "layout": layout, "at": self.at})
        self.status = "live"
        self.gen += 1


# ---------------------------------------------------------------- WebSocket (RFC 6455, client side)

class WS:
    def __init__(self, url, timeout=8):
        u = urlsplit(url)
        secure = u.scheme in ("https", "wss")
        host, port = u.hostname, u.port or (443 if secure else 80)
        sock = socket.create_connection((host, port), timeout)
        if secure:
            sock = ssl.create_default_context().wrap_socket(sock, server_hostname=host)
        key = base64.b64encode(os.urandom(16)).decode()
        path = u.path.rstrip("/") + "/api/websocket"
        sock.sendall(("GET %s HTTP/1.1\r\nHost: %s\r\nUpgrade: websocket\r\nConnection: Upgrade\r\n"
                      "Sec-WebSocket-Key: %s\r\nSec-WebSocket-Version: 13\r\n\r\n" % (path, u.netloc, key)).encode())
        buf = b""
        while b"\r\n\r\n" not in buf:
            chunk = sock.recv(4096)
            if not chunk:
                raise ConnectionError("closed during the handshake")
            buf += chunk
            if len(buf) > 65536:
                raise ConnectionError("bad handshake")
        head, rest = buf.split(b"\r\n\r\n", 1)
        status = head.split(b"\r\n", 1)[0].decode("latin-1")
        if " 101" not in status:
            raise ConnectionError(status)
        self.sock = sock
        self.buf = bytearray(rest)
        self.lock = threading.Lock()
        self.parts = []

    def _frame(self):
        """One whole frame from the buffer (opcode, fin, payload), or None - nothing consumed then."""
        b = self.buf
        if len(b) < 2:
            return None
        fin, op, n, at = b[0] & 0x80, b[0] & 0x0F, b[1] & 0x7F, 2
        masked = b[1] & 0x80
        if n == 126:
            if len(b) < 4:
                return None
            n, at = struct.unpack(">H", b[2:4])[0], 4
        elif n == 127:
            if len(b) < 10:
                return None
            n, at = struct.unpack(">Q", b[2:10])[0], 10
        mask = None
        if masked:
            if len(b) < at + 4:
                return None
            mask, at = bytes(b[at:at + 4]), at + 4
        if len(b) < at + n:
            return None
        data = bytes(b[at:at + n])
        del b[:at + n]
        if mask:
            data = _xor(data, mask)
        return op, fin, data

    def recv(self):
        """The next text message (str); socket.timeout when none came in the socket's timeout."""
        while True:
            fr = self._frame()
            if fr is None:
                chunk = self.sock.recv(65536)
                if not chunk:
                    raise ConnectionError("closed")
                self.buf += chunk
                continue
            op, fin, data = fr
            if op == 8:
                raise ConnectionError("closed by the server")
            if op == 9:
                self._send(10, data)
                continue
            if op == 10:
                continue
            if op in (0, 1, 2):
                self.parts.append(data)
                if fin:
                    msg, self.parts = b"".join(self.parts), []
                    return msg.decode("utf-8", "replace")

    def _send(self, op, data):
        mask = os.urandom(4)
        n = len(data)
        head = bytes([0x80 | op])
        if n < 126:
            head += bytes([0x80 | n])
        elif n < 65536:
            head += bytes([0x80 | 126]) + struct.pack(">H", n)
        else:
            head += bytes([0x80 | 127]) + struct.pack(">Q", n)
        with self.lock:
            self.sock.sendall(head + mask + _xor(data, mask))

    def send(self, text):
        self._send(1, text.encode("utf-8"))

    def close(self):
        try:
            self._send(8, b"")
        except OSError:
            pass
        try:
            self.sock.close()
        except OSError:
            pass


def _xor(data, mask):
    if not data:
        return b""
    n = len(data)
    m = (mask * (n // 4 + 1))[:n]
    return (int.from_bytes(data, "big") ^ int.from_bytes(m, "big")).to_bytes(n, "big")


# ---------------------------------------------------------------- Home Assistant

class HA:
    """The connection in a thread, reconnecting. states: {eid: {"state", "attributes"}} (under lock);
    status: none (no token) / connecting / loading / connected / error; gen - bumped on each change;
    reg_gen - bumped when the states and the registries have come (time to place the devices)."""

    def __init__(self, urls, token):
        self.urls = [u.strip().rstrip("/") for u in urls if u.strip()]
        self.token = token
        self.lock = threading.Lock()
        self.states = {}
        self.areas, self.ent_area, self.dev_area, self.hidden = {}, {}, {}, set()
        self.status = "none" if not (token and self.urls) else "connecting"
        self.error = None
        self.notice = None                      # (text, time): a failed call, shown by the app
        self.gen = 0
        self.reg_gen = 0
        self.url = None
        self.ws = None
        self._ids = itertools.count(1)          # next() is atomic: the app and the thread both send
        self._cb = {}
        self._sub = None
        self.want = []                          # entity ids to subscribe to
        self.alive = True
        if self.status != "none":
            threading.Thread(target=self._run, daemon=True).start()

    # -- requests
    def _req(self, msg, cb=None):
        ws = self.ws
        if ws is None:
            return None
        msg["id"] = i = next(self._ids)
        if cb:
            self._cb[i] = cb
        try:
            ws.send(json.dumps(msg))
        except OSError:
            return None
        return i

    def call(self, domain, service, eid, **data):
        """call_service; False when there is no connection. A failure comes back as a notice."""
        if self.status != "connected":
            return False

        def done(m):
            if not m.get("success"):
                err = m.get("error") or {}
                self.notice = ("HA: " + str(err.get("message") or err.get("code") or "помилка"), time.monotonic())
        return self._req({"type": "call_service", "domain": domain, "service": service,
                          "service_data": data, "target": {"entity_id": eid}}, done) is not None

    def subscribe(self, eids):
        eids = sorted(set(eids))
        if eids == self.want:
            return
        self.want = eids
        if self.status == "connected":
            self._resubscribe()

    def _resubscribe(self):
        if self._sub is not None:
            self._req({"type": "unsubscribe_events", "subscription": self._sub})
            self._sub = None
        if self.want:
            self._sub = self._req({"type": "subscribe_entities", "entity_ids": self.want})

    def area_of(self, eid):
        a = self.ent_area.get(eid)
        if a is None:
            return None
        return a or None

    # -- the thread
    def _run(self):
        delay = 2
        k = 0
        while self.alive:
            url = self.urls[k % len(self.urls)]
            try:
                self._session(url)
                delay = 2
            except (OSError, ValueError, ConnectionError, ssl.SSLError) as e:
                if self.status != "auth":                       # a wrong token stays «auth»
                    self.error = str(e) or e.__class__.__name__
                    self.status = "error"
            self.ws = None
            self._sub = None
            self._cb.clear()
            self.gen += 1
            if self.status == "auth":
                delay = 60                                        # a wrong token: not every two seconds
            k += 1
            time.sleep(delay if k % len(self.urls) == 0 else 0.2)
            delay = min(30, delay * 2)

    def _session(self, url):
        self.status = "connecting"
        self.gen += 1
        ws = WS(url)
        ws.sock.settimeout(10)
        m = json.loads(ws.recv())
        if m.get("type") != "auth_required":
            raise ConnectionError("not Home Assistant")
        ws.send(json.dumps({"type": "auth", "access_token": self.token}))
        m = json.loads(ws.recv())
        if m.get("type") != "auth_ok":
            self.status = "auth"
            self.error = "невірний токен"
            ws.close()
            raise ConnectionError("auth")
        self.ws, self.url = ws, url
        self.status = "loading"
        self.gen += 1
        got = {}

        def keep(name):
            def cb(m):
                got[name] = m.get("result") if m.get("success") else None
                if len(got) == 4:
                    self._loaded(got)
            return cb
        self._req({"type": "get_states"}, keep("states"))
        self._req({"type": "config/area_registry/list"}, keep("areas"))
        self._req({"type": "config/entity_registry/list_for_display"}, keep("ents"))
        self._req({"type": "config/device_registry/list"}, keep("devs"))
        ws.sock.settimeout(30)
        quiet = 0
        while self.alive:
            try:
                raw = ws.recv()
            except socket.timeout:
                quiet += 1
                if quiet > 1:
                    raise ConnectionError("no answer")
                self._req({"type": "ping"})
                continue
            quiet = 0
            m = json.loads(raw)
            cb = self._cb.pop(m.get("id"), None) if m.get("type") == "result" else None
            if cb:
                cb(m)
            elif m.get("type") == "event" and m.get("id") == self._sub:
                self._event(m.get("event") or {})

    def _loaded(self, got):
        states = {s["entity_id"]: {"state": s.get("state"), "attributes": s.get("attributes") or {}}
                  for s in (got.get("states") or []) if "entity_id" in s}
        areas = {a["area_id"]: a.get("name", a["area_id"]) for a in (got.get("areas") or [])}
        dev_area = {d["id"]: d.get("area_id") for d in (got.get("devs") or []) if "id" in d}
        ents = got.get("ents") or {}
        ent_area, hidden = {}, set()
        for e in (ents.get("entities") if isinstance(ents, dict) else ents) or []:
            eid = e.get("ei") or e.get("entity_id")
            if not eid:
                continue
            ent_area[eid] = e.get("ai") or e.get("area_id") or dev_area.get(e.get("di") or e.get("device_id")) or ""
            if e.get("hb") or e.get("hidden_by") or e.get("ec") is not None or e.get("entity_category"):
                hidden.add(eid)
        with self.lock:
            self.states = states
        self.areas, self.dev_area, self.ent_area, self.hidden = areas, dev_area, ent_area, hidden
        self.status = "connected"
        self.reg_gen += 1
        self.gen += 1
        self._resubscribe()

    def _event(self, ev):
        with self.lock:
            for eid, s in (ev.get("a") or {}).items():
                self.states[eid] = {"state": s.get("s"), "attributes": s.get("a") or {}}
            for eid, d in (ev.get("c") or {}).items():
                st = self.states.setdefault(eid, {"state": None, "attributes": {}})
                plus, minus = d.get("+") or {}, d.get("-") or {}
                if "s" in plus:
                    st["state"] = plus["s"]
                if "a" in plus:
                    st["attributes"] = dict(st["attributes"], **plus["a"])
                for k in minus.get("a") or []:
                    st["attributes"].pop(k, None)
            for eid in ev.get("r") or []:
                self.states.pop(eid, None)
        self.gen += 1

    def snapshot(self):
        with self.lock:
            return {k: {"state": v["state"], "attributes": dict(v["attributes"])} for k, v in self.states.items()}

    def get(self, eid):
        with self.lock:
            return self.states.get(eid)

    def close(self):
        self.alive = False
        if self.ws:
            self.ws.close()


# ---------------------------------------------------------------- placing the devices (as js/devices.js does)

LAMP_MODELS = ("track", "spot", "strip", "linear")
AUTO_DOMAINS = {"light", "switch", "fan", "cover", "climate", "media_player", "sensor", "binary_sensor", "lock",
                "vacuum", "humidifier", "water_heater", "alarm_control_panel", "valve", "input_boolean"}
SENSOR_DC = {"temperature"}
PRESENCE_DC = {"motion", "occupancy", "presence"}
BIN_DC = {"door", "window", "garage_door", "opening", "motion", "occupancy", "presence", "moisture", "smoke", "gas",
          "carbon_monoxide"}
WALL_DOMAINS = {"sensor", "binary_sensor", "switch", "input_boolean", "lock"}
DOMAIN_ORDER = ["light", "climate", "media_player", "cover", "switch", "fan", "sensor", "binary_sensor", "lock"]
LAMP_WORDS = re.compile(r"lamp|light|lustr|svitl|led|світл|люстр|плафон|ламп|бра\b|підсвіт", re.I)


def domain(eid):
    return eid.split(".", 1)[0]


def _slug(s):
    return re.sub(r"^_+|_+$", "", re.sub(r"[^a-z0-9а-яіїєґ]+", "_", str(s or "").lower()))


def resolve(states, ref):
    """A plan's entity id -> the real one: the same id, else in the same domain by the name
    (gercon_cellar -> gercon_cellar_contact, or a friendly name that is the id)."""
    if not ref or not states or ref in states or "." not in ref:
        return ref
    dom, base = ref.split(".", 1)[0] + ".", _slug(ref.split(".", 1)[1])
    stem = base[:base.rfind("_")] if "_" in base else ""
    best = None
    if len(base) >= 4:
        for eid, st in states.items():
            if not eid.startswith(dom):
                continue
            i, nm = _slug(eid[len(dom):]), _slug(st["attributes"].get("friendly_name"))
            score = 4 if nm == base else 3 if i.startswith(base + "_") else 2 if nm.startswith(base + "_") else \
                1 if base.startswith(i + "_") or (nm and base.startswith(nm + "_")) or \
                (len(stem) >= 6 and (nm.startswith(stem + "_") or i.startswith(stem + "_"))) else 0
            pres = 1 if st["attributes"].get("device_class") in PRESENCE_DC else 0
            if score and (best is None or (score, pres, -len(eid)) > best[0]):
                best = ((score, pres, -len(eid)), eid)
    return best[1] if best else ref


def eligible(eid, st, hidden):
    d = domain(eid)
    if d not in AUTO_DOMAINS or eid in hidden:
        return False
    dc = st["attributes"].get("device_class")
    if d == "sensor":
        return dc in SENSOR_DC
    if d == "binary_sensor":
        return dc in BIN_DC
    return True


def _grid(room, n, inset):
    iw, id_ = max(0.2, room["w"] - 2 * inset), max(0.2, room["d"] - 2 * inset)
    cols = max(1, round(math.sqrt(n * iw / id_)))
    rows = math.ceil(n / cols)
    return [(room["x"] + inset + ((i % cols) + 0.5) * iw / cols, room["z"] + inset + (i // cols + 0.5) * id_ / rows)
            for i in range(n)]


def _windows(plan, room, fid, first):
    out = []
    for w in plan.get("windows") or []:
        if (w.get("floor") or first) != fid:
            continue
        near = lambda a, b: abs(a - b) < 0.06   # noqa: E731
        inx = room["x"] < w.get("x", -99) < room["x"] + room["w"]
        inz = room["z"] < w.get("z", -99) < room["z"] + room["d"]
        if near(w.get("z", -99), room["z"]) and inx:
            out.append((w["x"], room["z"] + 0.1))
        elif near(w.get("z", -99), room["z"] + room["d"]) and inx:
            out.append((w["x"], room["z"] + room["d"] - 0.1))
        elif near(w.get("x", -99), room["x"]) and inz:
            out.append((room["x"] + 0.1, w["z"]))
        elif near(w.get("x", -99), room["x"] + room["w"]) and inz:
            out.append((room["x"] + room["w"] - 0.1, w["z"]))
    return out


def _free_spot(plan, room, fid, first, x, z, taken):
    boxes = [o for o in (plan.get("furniture") or []) + (plan.get("stairs") or [])
             if (o.get("floor") or first) == fid and (o.get("y") or 0) < 1.6 and "x" in o and "w" in o]

    def ok(px, pz):
        if not (room["x"] + 0.3 < px < room["x"] + room["w"] - 0.3 and room["z"] + 0.3 < pz < room["z"] + room["d"] - 0.3):
            return False
        for b in boxes:
            if b.get("rot"):
                if math.hypot(px - (b["x"] + b["w"] / 2), pz - (b["z"] + b["d"] / 2)) < math.hypot(b["w"], b["d"]) / 2 + 0.25:
                    return False
            elif b["x"] - 0.25 < px < b["x"] + b["w"] + 0.25 and b["z"] - 0.25 < pz < b["z"] + b["d"] + 0.25:
                return False
        return not any(math.hypot(tx - px, tz - pz) < 0.45 for tx, tz in taken)
    r = 0.0
    while r <= max(room["w"], room["d"]):
        for k in range(16):
            a = k * math.pi / 8
            px, pz = x + math.cos(a) * r, z + math.sin(a) * r
            if ok(px, pz):
                return px, pz
            if r == 0:
                break
        r += 0.25
    return x, z


def placements(plan, layout, states, area_of, hidden=()):
    """{eid: {"f": floor, "x", "z", "model", "lamp"}} - where the 3D model shows each device: the plan's
    devices, the entities bound to furniture (lamps, curtains, the screen) at its middle, the rest of HA by
    its area in the room with that area (lights in a grid, covers at the windows, the others by the walls),
    the layout's moves on top, the hidden ones out."""
    floors = plan.get("floors") or []
    first = floors[0]["id"] if floors else None
    out = {}
    for d in plan.get("devices") or []:
        p = d.get("pos") or [0, 0, 0]
        out[resolve(states, d.get("entity_id"))] = {"f": d.get("floor") or first, "x": p[0], "z": p[2],
                                                    "model": d.get("model")}
    for f in plan.get("furniture") or []:
        for key in ("entity", "cover"):
            if f.get(key) and "x" in f:
                out[resolve(states, f[key])] = {"f": f.get("floor") or first, "x": f["x"] + f.get("w", 0) / 2,
                                                "z": f["z"] + f.get("d", 0) / 2,
                                                "lamp": key == "entity" and domain(f[key]) in ("light", "switch")}
    by_area = {}
    for r in plan.get("rooms") or []:
        if r.get("area") and r["area"] not in by_area:
            by_area[r["area"]] = r
    pos = (layout or {}).get("pos") or {}
    per_room = {}
    for eid, st in states.items():
        if eid in out or eid in pos or not eligible(eid, st, hidden):
            continue
        room = by_area.get(area_of(eid))
        if room:
            per_room.setdefault(room["id"], (room, []))[1].append(eid)
    order = lambda e: (DOMAIN_ORDER.index(domain(e)) if domain(e) in DOMAIN_ORDER else 99, e)   # noqa: E731
    for room, lst in per_room.values():
        fid = room.get("floor") or first
        lst.sort(key=order)
        lights = [e for e in lst if domain(e) == "light"]
        covers = [e for e in lst if domain(e) == "cover"]
        rest = [e for e in lst if domain(e) not in ("light", "cover")]
        lp = [(room["x"] + room["w"] / 2, room["z"] + room["d"] / 2)] if len(lights) == 1 else \
            _grid(room, len(lights), min(room["w"], room["d"]) * 0.25)
        for e, (x, z) in zip(lights, lp):
            out[e] = {"f": fid, "x": x, "z": z}
        wins = _windows(plan, room, fid, first)
        for i, e in enumerate(covers):
            if i < len(wins):
                out[e] = {"f": fid, "x": wins[i][0], "z": wins[i][1]}
            else:
                rest.append(e)
        taken = []
        for e, (x, z) in zip(rest, _grid(room, len(rest), 0.6)):
            x, z = _free_spot(plan, room, fid, first, x, z, taken)
            if domain(e) in WALL_DOMAINS:                       # by the nearest wall
                t = (plan.get("wallThickness") or 0.12) / 2 + 0.03
                opts = [(x - room["x"], room["x"] + t, z), (room["x"] + room["w"] - x, room["x"] + room["w"] - t, z),
                        (z - room["z"], x, room["z"] + t), (room["z"] + room["d"] - z, x, room["z"] + room["d"] - t)]
                _, x, z = min(opts)
            taken.append((x, z))
            out[e] = {"f": fid, "x": x, "z": z}
    for eid, v in pos.items():
        p = v.get("p") or [0, 0, 0]
        out[eid] = dict(out.get(eid) or {}, f=v.get("f") or (out.get(eid) or {}).get("f") or first, x=p[0], z=p[2],
                        **({"model": v["model"]} if v.get("model") else {}))
    for eid in (layout or {}).get("hidden") or []:
        out.pop(eid, None)
    for eid, v in out.items():
        st = states.get(eid)
        name = (st or {}).get("attributes", {}).get("friendly_name", "") if st else ""
        v["lamp"] = bool(v.get("lamp")) or domain(eid) == "light" or v.get("model") in LAMP_MODELS or \
            (domain(eid) == "switch" and bool(LAMP_WORDS.search(eid + " " + name)))
    return out


def save_ha_cache(places, states):
    _save(HA_CACHE, {"at": time.time(), "places": places,
                     "names": {e: (states.get(e) or {}).get("attributes", {}).get("friendly_name") for e in places},
                     "classes": {e: (states.get(e) or {}).get("attributes", {}).get("device_class") for e in places}})


def load_ha_cache():
    return _load(HA_CACHE) or {}
