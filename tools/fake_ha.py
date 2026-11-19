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
ap.add_argument("--plan", default=hawire.PLAN_URL, help="the plan server, or a plan .json file")
ap.add_argument("--layout", default=None, help="a layout .json file (by default from the plan server)")
ap.add_argument("--token", default="test")
args = ap.parse_args()

LAYOUT = {}
if os.path.exists(args.plan):
    with open(args.plan, encoding="utf-8") as f:
        PLAN = json.load(f)
    PLAN = PLAN.get("plan", PLAN)
else:
    with urllib.request.urlopen(args.plan.rstrip("/") + "/plan", timeout=10) as r:
        PLAN = json.loads(r.read().decode())["plan"]
    try:
        with urllib.request.urlopen(args.plan.rstrip("/") + "/layout", timeout=10) as r:
            LAYOUT = json.loads(r.read().decode()).get("layout") or {}
    except (OSError, ValueError):
        pass
if args.layout:
    with open(args.layout, encoding="utf-8") as f:
        LAYOUT = json.load(f)
    LAYOUT = LAYOUT.get("layout", LAYOUT)

NAMES = {"light": "Світло", "cover": "Штори", "sensor": "Температура", "media_player": "Колонка"}
states, areas, ents = {}, {}, []
rnd = random.Random(7)


def add(eid, state, area=None, **attrs):
    if eid in states:
        return
    states[eid] = {"entity_id": eid, "state": state, "attributes": attrs,
                   "last_changed": time.strftime("%Y-%m-%dT%H:%M:%S+00:00", time.gmtime(time.time() - 3600))}
    ents.append({"ei": eid, "ai": area})


MEDIA = 0x1FFFFF                       # every media_player feature
# the house's own AV, under their real names: the smart speaker, the projector (two entities from two
# integrations, as in HA), its screen with the «follow the projector» switch, the soundbar; TTS, the weather
add("media_player.audio", "idle", friendly_name="audio", device_class="speaker", supported_features=MEDIA,
    volume_level=0.3, is_volume_muted=False, app_name="Default Media Receiver")
add("media_player.pidval_the_freestyle", "on", friendly_name="The Freestyle", device_class="projector",
    supported_features=89533, source="digital_tv", sound_mode="Стандарт.",
    sound_mode_list=["Адаптивний звук", "Підсил.", "Стандарт."], volume_level=0.12, is_volume_muted=False)
add("media_player.the_freestyle_3", "off", friendly_name="The Freestyle", device_class="tv", supported_features=24381,
    source_list=["TV", "HDMI"])
add("media_player.pidval_samsung_soundbar_q990b", "on", friendly_name="Samsung Soundbar Q990B", device_class="speaker",
    supported_features=87437 | 2048, source="digital", source_list=["digital", "HDMI", "bluetooth", "wifi"],
    sound_mode="surround", sound_mode_list=["standard", "surround", "game", "adaptive_sound"], volume_level=0.16,
    is_volume_muted=False)
add("cover.pidval_pult_ekrana_proiektora_projector_screen", "closed", friendly_name="Екран проектора Projector screen",
    device_class="shade", current_position=0, supported_features=15)          # «closed» - let down
add("switch.pidval_ekran_proektora_follow_projector", "on", friendly_name="Екран проектора Follow projector")
add("tts.google_translate_en_com", "2026-11-19T07:24:58+00:00", friendly_name="Google Translate en com")
add("weather.forecast_golovna", "cloudy", friendly_name="Головна", temperature=4.5)
# the Deye inverter (ha-solarman), as the 3D model's energy finds it: the battery charging, the grid on
for eid, st, unit, name in (("sensor.inverter_battery", "78", "%", "Inverter Battery"),
                            ("sensor.inverter_battery_power", "-1240", "W", "Inverter Battery Power"),
                            ("sensor.inverter_battery_state", "charging", None, "Inverter Battery State"),
                            ("sensor.inverter_battery_voltage", "52.8", "V", "Inverter Battery Voltage"),
                            ("sensor.inverter_grid_power", "2210", "W", "Inverter Grid Power"),
                            ("sensor.inverter_grid_l1_voltage", "224.1", "V", "Inverter Grid L1 Voltage"),
                            ("sensor.inverter_load_power", "947", "W", "Inverter Load Power"),
                            ("sensor.inverter_pv1_power", "0", "W", "Inverter PV1 Power"),
                            ("sensor.inverter_pv2_power", "0", "W", "Inverter PV2 Power"),
                            ("sensor.inverter_generator_power", "0", "W", "Inverter Generator Power")):
    add(eid, st, friendly_name=name, **({"unit_of_measurement": unit} if unit else {}))
add("binary_sensor.inverter_grid", "on", friendly_name="Inverter Grid")
add("sensor.0x00158d008b69d59f_humidity", "86", friendly_name="Надворі вологість", device_class="humidity",
    unit_of_measurement="%")
add("sensor.0x00158d008b69d59f_pressure", "1012.4", friendly_name="Надворі тиск", device_class="pressure",
    unit_of_measurement="hPa")


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
            elif eid.startswith("light."):
                add(eid, "on", friendly_name=(f.get("name") or eid).strip(), brightness=180, rgb_color=[60, 120, 255],
                    supported_color_modes=["rgb"])
            else:
                add(eid, rnd.choice(["on", "off", "off"]), friendly_name=(f.get("name") or eid).strip())
for eid, v in (LAYOUT.get("pos") or {}).items():          # what the layout placed (the speaker, the sensors)
    dom = eid.split(".")[0]
    if dom == "binary_sensor":
        add(eid, "off", friendly_name=eid.split(".", 1)[1].replace("_", " "),
            device_class="door" if "contact" in eid else "occupancy")
    elif dom == "sensor":
        add(eid, "%.1f" % rnd.uniform(5, 24), friendly_name=eid.split(".", 1)[1].replace("_", " "),
            device_class="temperature", unit_of_measurement="°C")
    elif dom in ("switch", "light"):
        add(eid, "off", friendly_name=eid.split(".", 1)[1].replace("_", " "))
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
    return {"s": s["state"], "a": s["attributes"], "lc": s.get("lc", time.time() - 3600)}


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
    if state is not None and state != s["state"]:
        s["state"] = state
        s["lc"] = time.time()
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


def speak(eid, message):
    """The TTS phrase plays on the speaker for a few seconds."""
    set_state(eid, "playing", media_title=message, media_artist="TTS")
    time.sleep(4)
    if states[eid]["attributes"].get("media_artist") == "TTS":
        set_state(eid, "idle", media_title=None, media_artist=None)


def service(dom, srv, eid, data):
    if dom == "tts":
        mp = data.get("media_player_entity_id") if srv == "speak" else eid
        if mp in states:
            threading.Thread(target=speak, args=(mp, data.get("message", "")), daemon=True).start()
            return True
        return False
    if eid not in states:
        return False
    s = states[eid]
    if srv == "toggle":
        srv = "turn_off" if s["state"] == "on" else "turn_on"
    if dom == "light" and srv == "turn_on":
        b = round(data["brightness_pct"] * 2.55) if "brightness_pct" in data else s["attributes"].get("brightness") or 255
        extra = {k: data[k] for k in ("rgb_color", "color_temp_kelvin") if k in data}
        set_state(eid, "on", brightness=b, **extra)
    elif dom == "light" and srv == "turn_off":
        set_state(eid, "off", brightness=None)
    elif srv in ("turn_on", "turn_off") and dom in ("switch", "fan", "input_boolean", "light"):
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
        elif srv == "volume_mute":
            set_state(eid, None, is_volume_muted=data["is_volume_muted"])
        elif srv in ("turn_on", "turn_off"):
            set_state(eid, "on" if srv == "turn_on" else "off")
        elif srv == "media_pause":
            set_state(eid, "paused")
        elif srv == "media_play":
            set_state(eid, "playing")
        elif srv == "play_media":
            set_state(eid, "playing", media_title=(data.get("extra") or {}).get("title") or data.get("media_content_id"),
                      media_artist=None, media_content_id=data.get("media_content_id"))
        elif srv in ("media_next_track", "media_previous_track"):
            pass
        elif srv == "select_source":
            set_state(eid, None, source=data["source"])
        elif srv == "select_sound_mode":
            set_state(eid, None, sound_mode=data["sound_mode"])
        else:
            return False
    elif dom == "climate":
        if srv == "set_temperature":
            set_state(eid, None, temperature=data["temperature"])
        elif srv in ("turn_on", "turn_off"):
            set_state(eid, "cool" if srv == "turn_on" else "off")
        elif srv == "set_hvac_mode":
            set_state(eid, data["hvac_mode"])
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
            elif t == "history/history_during_period":
                res = {}
                for e in m.get("entity_ids") or []:
                    try:
                        v0 = float(states[e]["state"])
                    except (KeyError, ValueError):
                        continue
                    now, R = time.time(), random.Random(e)
                    res[e] = [{"s": "%.2f" % (v0 + 3 * __import__("math").sin(i / 9) + R.uniform(-0.4, 0.4) - 3 * __import__("math").sin(48 / 9)),
                               "lu": now - 86400 + i * 1800} for i in range(48)]
            elif t == "call_service" and m.get("domain") == "weather":
                day = lambda n: time.strftime("%Y-%m-%dT10:00:00+00:00", time.gmtime(time.time() + n * 86400))   # noqa: E731
                eid = (m.get("target") or {}).get("entity_id")
                res = {"context": {}, "response": {eid: {"forecast": [
                    {"datetime": day(0), "condition": "cloudy", "temperature": 6, "templow": 1},
                    {"datetime": day(1), "condition": "snowy", "temperature": 2, "templow": -3}]}}}
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
