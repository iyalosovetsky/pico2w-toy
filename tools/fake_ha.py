#!/usr/bin/env python3
"""A pretend Home Assistant for ДІМ (app/house.py): its WebSocket API on a port, the entities taken from
the house plan (the plan's devices, the lamps bound to furniture, a few by the rooms' HA areas) - to test
and to record the GIF without touching the real house.

    python3 tools/fake_ha.py [--port 8123] [--plan URL|file.json] [--token test]
    HOUSE_ENV=/tmp/h.env python3 app/house.py        # h.env: HA_URL=http://127.0.0.1:8123, HA_TOKEN=test

What it speaks: auth, get_states, config/area_registry/list, config/entity_registry/list_for_display,
config/device_registry/list, subscribe_entities (with entity_ids; compressed diffs), unsubscribe_events,
call_service (turn_on / turn_off / toggle, covers, media, climate, locks), ping. Covers move over 3 s.
"""
import argparse
import base64
import hashlib
import json
import os
import random
import socket
import struct
import sys
import threading
import time
import urllib.request

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "app"))
import hawire  # noqa: E402

ap = argparse.ArgumentParser()
ap.add_argument("--port", type=int, default=8123)
ap.add_argument("--plan", default=hawire.PLAN_URL)
ap.add_argument("--token", default="test")
args = ap.parse_args()

if os.path.exists(args.plan):
    with open(args.plan, encoding="utf-8") as f:
        PLAN = json.load(f)
    PLAN = PLAN.get("plan", PLAN)
else:
    with urllib.request.urlopen(args.plan.rstrip("/") + "/plan", timeout=10) as r:
        PLAN = json.loads(r.read().decode())["plan"]

NAMES = {"light": "Світло", "cover": "Штори", "sensor": "Температура", "media_player": "Колонка"}
states, areas, ents = {}, {}, []
rnd = random.Random(7)


def add(eid, state, area=None, **attrs):
    states[eid] = {"entity_id": eid, "state": state, "attributes": attrs}
    ents.append({"ei": eid, "ai": area})


for d in PLAN.get("devices") or []:
    eid = d["entity_id"]
    dom = eid.split(".")[0]
    name = eid.split(".", 1)[1].replace("_", " ")
    if dom == "binary_sensor":
        add(eid, rnd.choice(["off", "off", "on"]), friendly_name=name,
            device_class="door" if "gercon" in eid else "occupancy")
    elif dom == "cover":
        add(eid, "closed", friendly_name="Ворота гаража" if "vorota" in eid else name, device_class="garage",
            current_position=0)
    elif dom == "media_player":
        add(eid, "playing", friendly_name="Телевізор", device_class="tv", volume_level=0.2, media_title="Новини")
    elif dom == "climate":
        add(eid, "cool", friendly_name="Кондиціонер", current_temperature=23.5, temperature=22, min_temp=16,
            max_temp=30, target_temp_step=0.5)
    elif dom == "light":
        add(eid, "off", friendly_name="Більярд", brightness=None, supported_color_modes=["brightness"])
    else:
        add(eid, rnd.choice(["on", "off"]), friendly_name=name)
for f in PLAN.get("furniture") or []:
    for key in ("entity", "cover"):
        eid = f.get(key)
        if eid and eid not in states:
            if eid.startswith("sensor."):
                add(eid, "4.5", friendly_name="Надворі", device_class="temperature", unit_of_measurement="°C")
            elif key == "cover":
                add(eid, "open", friendly_name=f.get("name") or eid, current_position=100)
            else:
                add(eid, rnd.choice(["on", "off", "off"]), friendly_name=(f.get("name") or eid).strip())
for r in PLAN.get("rooms") or []:
    a = r.get("area")
    if not a or a in areas:
        continue
    areas[a] = r.get("name") or a
    if r.get("walls") in (False, "railing"):
        continue
    add("light.%s_ceiling" % a, rnd.choice(["on", "off", "off"]), a, friendly_name="Стеля - " + areas[a],
        brightness=rnd.choice([80, 160, 255]), supported_color_modes=["brightness"])
    add("sensor.%s_temperature" % a, "%.1f" % rnd.uniform(17, 26), a, friendly_name="Температура - " + areas[a],
        device_class="temperature", unit_of_measurement="°C")
    if a in ("bedroom", "big_room", "son_room"):
        add("cover.%s_curtains" % a, "open", a, friendly_name="Штори - " + areas[a], current_position=100,
            device_class="curtain")
    if a == "billiard":
        add("cover.projector_screen", "open", a, friendly_name="Екран проектора", current_position=100,
            device_class="shade")
        add("media_player.projector", "paused", a, friendly_name="Проектор", volume_level=0.12,
            media_title="Фільм", device_class="tv")
    if a == "kitchen":
        add("lock.back_door", "locked", a, friendly_name="Задні двері")

clients = []
lock = threading.Lock()


class Client:
    def __init__(self, sock):
        self.sock, self.buf, self.subs = sock, bytearray(), {}
        self.wlock = threading.Lock()

    def send(self, obj):
        data = json.dumps(obj, ensure_ascii=False).encode()
        n = len(data)
        head = b"\x81" + (bytes([n]) if n < 126 else b"\x7e" + struct.pack(">H", n) if n < 65536
                          else b"\x7f" + struct.pack(">Q", n))
        with self.wlock:
            self.sock.sendall(head + data)

    def recv(self):
        while True:
            fr = self.frame()
            if fr is not None:
                op, data = fr
                if op == 8:
                    raise ConnectionError
                if op == 1:
                    return json.loads(data)
                continue
            c = self.sock.recv(65536)
            if not c:
                raise ConnectionError
            self.buf += c

    def frame(self):
        b = self.buf
        if len(b) < 2:
            return None
        op, n, at = b[0] & 15, b[1] & 127, 2
        if n == 126:
            if len(b) < 4:
                return None
            n, at = struct.unpack(">H", b[2:4])[0], 4
        elif n == 127:
            if len(b) < 10:
                return None
            n, at = struct.unpack(">Q", b[2:10])[0], 10
        if len(b) < at + 4 + n:
            return None
        mask = b[at:at + 4]
        data = bytes(x ^ mask[i % 4] for i, x in enumerate(b[at + 4:at + 4 + n]))
        del b[:at + 4 + n]
        return op, data


def compressed(eid):
    s = states[eid]
    return {"s": s["state"], "a": s["attributes"], "lc": time.time()}


def changed(eid):
    with lock:
        cl = list(clients)
    for c in cl:
        for sid, eids in list(c.subs.items()):
            if eids is None or eid in eids:
                try:
                    c.send({"id": sid, "type": "event", "event": {"c": {eid: {"+": compressed(eid)}}}})
                except OSError:
                    pass


def set_state(eid, state=None, **attrs):
    s = states[eid]
    if state is not None:
        s["state"] = state
    s["attributes"].update(attrs)
    changed(eid)


def move_cover(eid, target):
    s = states[eid]
    cur = s["attributes"].get("current_position", 0)
    set_state(eid, "opening" if target > cur else "closing")
    for i in range(1, 7):
        time.sleep(0.5)
        set_state(eid, None, current_position=round(cur + (target - cur) * i / 6))
    set_state(eid, "open" if target > 0 else "closed")


def service(dom, srv, eid, data):
    if eid not in states:
        return False
    s = states[eid]
    if srv == "toggle":
        srv = "turn_off" if s["state"] == "on" else "turn_on"
    if dom == "light" and srv == "turn_on":
        b = round(data["brightness_pct"] * 2.55) if "brightness_pct" in data else s["attributes"].get("brightness") or 255
        set_state(eid, "on", brightness=b)
    elif dom == "light" and srv == "turn_off":
        set_state(eid, "off", brightness=None)
    elif srv in ("turn_on", "turn_off") and dom in ("switch", "fan", "input_boolean"):
        set_state(eid, "on" if srv == "turn_on" else "off")
    elif dom == "cover":
        target = {"open_cover": 100, "close_cover": 0}.get(srv, data.get("position"))
        if target is not None:
            threading.Thread(target=move_cover, args=(eid, target), daemon=True).start()
    elif dom == "media_player":
        if srv == "media_play_pause":
            set_state(eid, "paused" if s["state"] == "playing" else "playing")
        elif srv == "volume_set":
            set_state(eid, None, volume_level=data["volume_level"])
        elif srv in ("turn_on", "turn_off"):
            set_state(eid, "on" if srv == "turn_on" else "off")
    elif dom == "climate":
        if srv == "set_temperature":
            set_state(eid, None, temperature=data["temperature"])
        elif srv in ("turn_on", "turn_off"):
            set_state(eid, "cool" if srv == "turn_on" else "off")
    elif dom == "lock" and srv in ("lock", "unlock"):
        set_state(eid, "locked" if srv == "lock" else "unlocked")
    else:
        return False
    return True


def handle(sock):
    try:
        req = b""
        while b"\r\n\r\n" not in req:
            c = sock.recv(4096)
            if not c:
                return
            req += c
        key = next(ln.split(b":", 1)[1].strip() for ln in req.split(b"\r\n") if ln.lower().startswith(b"sec-websocket-key"))
        acc = base64.b64encode(hashlib.sha1(key + b"258EAFA5-E914-47DA-95CA-C5AB0DC85B11").digest()).decode()
        sock.sendall(("HTTP/1.1 101 Switching Protocols\r\nUpgrade: websocket\r\nConnection: Upgrade\r\n"
                      "Sec-WebSocket-Accept: %s\r\n\r\n" % acc).encode())
        c = Client(sock)
        c.send({"type": "auth_required", "ha_version": "fake"})
        m = c.recv()
        if m.get("access_token") != args.token:
            c.send({"type": "auth_invalid", "message": "bad token"})
            return
        c.send({"type": "auth_ok", "ha_version": "fake"})
        with lock:
            clients.append(c)
        while True:
            m = c.recv()
            t, i = m.get("type"), m.get("id")
            res = None
            if t == "get_states":
                res = list(states.values())
            elif t == "config/area_registry/list":
                res = [{"area_id": a, "name": n} for a, n in areas.items()]
            elif t == "config/entity_registry/list_for_display":
                res = {"entities": ents, "entity_categories": {}}
            elif t == "config/device_registry/list":
                res = []
            elif t == "subscribe_entities":
                eids = set(m["entity_ids"]) if m.get("entity_ids") else None
                c.subs[i] = eids
                c.send({"id": i, "type": "result", "success": True, "result": None})
                c.send({"id": i, "type": "event", "event": {"a": {e: compressed(e) for e in states
                                                                  if eids is None or e in eids}}})
                continue
            elif t == "unsubscribe_events":
                c.subs.pop(m.get("subscription"), None)
            elif t == "ping":
                c.send({"id": i, "type": "pong"})
                continue
            elif t == "call_service":
                eid = (m.get("target") or {}).get("entity_id")
                ok = service(m["domain"], m["service"], eid, m.get("service_data") or {})
                print("call", m["domain"], m["service"], eid, m.get("service_data"), "ok" if ok else "FAILED", flush=True)
                if not ok:
                    c.send({"id": i, "type": "result", "success": False,
                            "error": {"code": "not_found", "message": "Service not found"}})
                    continue
                res = {"context": {}}
            c.send({"id": i, "type": "result", "success": True, "result": res})
    except (ConnectionError, OSError, ValueError, StopIteration):
        pass
    finally:
        with lock:
            clients[:] = [c for c in clients if c.sock is not sock]
        sock.close()


srv = socket.socket()
srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
srv.bind(("127.0.0.1", args.port))
srv.listen(4)
print("fake HA: %d entities, %d areas on ws://127.0.0.1:%d/api/websocket" % (len(states), len(areas), args.port),
      flush=True)
while True:
    s, _ = srv.accept()
    threading.Thread(target=handle, args=(s,), daemon=True).start()
