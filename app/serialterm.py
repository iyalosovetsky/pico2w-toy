"""SERIAL: a terminal for serial devices, made for grblHAL (and fine for anything else).

The port: the first /dev/ttyACM*, else /dev/ttyUSB*, else a list to choose from (F3); it is
reopened when the device comes back (a grblHAL board resets on connect). Two panes: the upper one
holds what you typed with the first 1-2 lines of each answer (and ok / error / ALARM), the lower
one everything the device sent - F2 / Tab hides or shows it. grblHAL: the status line comes from
the "<...>" reports (they go to the full output only), ? ! ~ on an empty line are sent at once
(real-time commands), F5 - status polling, soft reset, unlock, home; error and alarm codes are
explained. F4 - a G-code file from ~/gcode: run it all (the next line after each "ok", a pause on
an error) or step by step (Enter sends the next line), pause / resume / stop. F3 also hands the
port over to the real minicom on the text console.
"""
import glob
import json
import os
import re
import select
import subprocess
import sys
import termios
import threading
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import pygame  # noqa: E402
import lcd  # noqa: E402

CONFIG = os.path.expanduser("~/.config/lcdtoy/serial.json")
HISTORY_FILE = os.path.expanduser("~/.config/lcdtoy/serial-history")
GCODE_DIR = os.path.expanduser("~/gcode")
GCODE_EXT = (".nc", ".gcode", ".ngc", ".tap", ".gc", ".cnc", ".txt")
BAUDS = [115200, 250000, 230400, 500000, 921600, 1000000, 57600, 38400, 19200, 9600]
EOLS = [("\n", "LF"), ("\r", "CR"), ("\r\n", "CRLF")]
FULL_MAX = 3000
CMD_MAX = 400
SHOW_LINES = 2          # answer lines kept in the upper pane per command
POLL_S = 0.25
PENDANT_POLL_S = 0.2
JOG_STEPS = [0.01, 0.1, 1.0, 10.0, 100.0]               # mm per tap
JOG_FEEDS = {0.01: 60, 0.1: 200, 1.0: 600, 10.0: 1500, 100.0: 3000}   # mm/min (also while held)
JOG_HOLD_S = 0.35                                       # held longer: continuous
JOG_TICK_S = 0.1                                        # continuous jog: a short increment this often
SPINDLE_SPEEDS = [1000, 3000, 6000, 8000, 10000, 12000, 15000, 18000, 24000]

BG, FG, DIM = (0, 0, 0), (230, 230, 230), (130, 130, 130)
ACCENT, GREEN, RED, BLUE, CYAN, ORANGE = (255, 200, 0), (90, 220, 110), (240, 90, 80), (110, 170, 255), \
    (80, 220, 220), (255, 150, 40)
FONT_DIR = "/usr/share/fonts/truetype/dejavu/"
STATE_COLORS = {"Idle": GREEN, "Run": BLUE, "Hold": ACCENT, "Jog": CYAN, "Alarm": RED, "Door": ORANGE,
                "Check": DIM, "Home": CYAN, "Sleep": DIM, "Tool": ORANGE}

GRBL_ERRORS = {
    1: "немає літери команди", 2: "неправильне число", 3: "невідома $-команда", 4: "від'ємне значення",
    5: "хомінг вимкнено ($22)", 6: "імпульс кроку < 3 мкс", 7: "помилка читання налаштувань",
    8: "$-команда лише в Idle", 9: "заблоковано: ALARM або двері", 10: "м'які межі без хомінгу",
    11: "рядок задовгий", 12: "крок перевищує макс. швидкість", 13: "двері відчинені",
    14: "рядок збірки задовгий", 15: "jog за м'які межі", 16: "неправильна jog-команда",
    17: "лазер вимагає PWM", 18: "немає хомінгу для осі", 20: "непідтримувана команда",
    21: "дві команди однієї групи", 22: "не задано подачу F", 23: "потрібне ціле число",
    24: "кілька команд для осей", 25: "повтор слова", 26: "немає осей", 27: "неправильний номер рядка",
    28: "бракує значення", 29: "G59.x не підтримується", 30: "G53 лише з G0 / G1", 31: "зайві осі",
    32: "дуга без осей площини", 33: "неправильна ціль руху", 34: "дуга: радіус не сходиться",
    35: "дуга: немає I J K", 36: "зайві слова", 37: "G43.1 без осі", 38: "неправильний інструмент",
    39: "значення поза межами", 40: "немає двигуна шпинделя", 60: "SD: не змонтована",
    79: "потрібен хомінг"}
GRBL_ALARMS = {
    1: "жорсткий кінцевик", 2: "ціль за м'якими межами", 3: "скидання під час руху",
    4: "проба: неправильний стан", 5: "проба не спрацювала", 6: "хомінг: скидання",
    7: "хомінг: відчинені двері", 8: "хомінг: не відійшов від кінцевика", 9: "хомінг: кінцевик не знайдено",
    10: "аварійна зупинка (E-stop)", 11: "потрібен хомінг", 12: "помилка обмеження",
    13: "шпиндель не стартував", 14: "кінцевик спрацював при старті", 15: "двигун: помилка драйвера",
    17: "кінцевик активний"}


# ---------------------------------------------------------------- ports

def port_info(dev):
    name = os.path.basename(dev)
    sysdev = "/sys/class/tty/%s/device" % name
    if os.path.exists(sysdev):
        usb = os.path.realpath(sysdev + "/..")
        parts = []
        for f in ("manufacturer", "product"):
            try:
                with open(os.path.join(usb, f)) as fh:
                    v = fh.read().strip()
                if v and v not in parts:
                    parts.append(v)
            except OSError:
                pass
        if parts:
            return " ".join(parts)
    return {"serial0": "UART GPIO 14/15"}.get(name, "")


def list_ports():
    found = sorted(glob.glob("/dev/ttyACM*")) + sorted(glob.glob("/dev/ttyUSB*"))
    if os.path.exists("/dev/serial0"):
        found.append("/dev/serial0")
    found += sorted(glob.glob("/dev/ttyAMA[0-9]*"))
    return found


def default_port():
    for pat in ("/dev/ttyACM*", "/dev/ttyUSB*"):
        ports = sorted(glob.glob(pat))
        if ports:
            return ports[0]
    return None


SPEEDS = {b: getattr(termios, "B%d" % b) for b in BAUDS if hasattr(termios, "B%d" % b)}


class Port:
    """A raw serial port with a reader thread that splits lines (status reports included)."""

    def __init__(self, dev, baud):
        self.dev, self.baud = dev, baud
        self.fd = os.open(dev, os.O_RDWR | os.O_NOCTTY | os.O_NONBLOCK)
        a = termios.tcgetattr(self.fd)
        a[0] = a[1] = a[3] = 0
        a[2] = termios.CS8 | termios.CREAD | termios.CLOCAL
        a[4] = a[5] = SPEEDS.get(baud, termios.B115200)
        a[6][termios.VMIN], a[6][termios.VTIME] = 0, 0
        termios.tcsetattr(self.fd, termios.TCSANOW, a)
        self.lines = []
        self.lock = threading.Lock()
        self.alive = True
        self.buf = b""
        self.t_buf = 0.0
        threading.Thread(target=self._reader, daemon=True).start()

    def _reader(self):
        while self.alive:
            try:
                if not select.select([self.fd], [], [], 0.1)[0]:
                    if self.buf and time.monotonic() - self.t_buf > 0.3:    # a prompt without a newline
                        self._push(self.buf)
                        self.buf = b""
                    continue
                data = os.read(self.fd, 4096)
                if not data:
                    raise OSError("closed")
            except BlockingIOError:
                continue
            except OSError:
                self.alive = False
                break
            self.buf += data
            self.t_buf = time.monotonic()
            *done, self.buf = self.buf.split(b"\n")
            for raw in done:
                self._push(raw)

    def _push(self, raw):
        line = raw.decode("utf-8", "replace").replace("\r", "")
        with self.lock:
            self.lines.append(line)

    def take(self):
        with self.lock:
            out, self.lines = self.lines, []
        return out

    def write(self, data):
        if isinstance(data, str):
            data = data.encode("utf-8", "replace")
        try:
            while data:
                n = os.write(self.fd, data)
                data = data[n:]
        except BlockingIOError:
            time.sleep(0.01)
            self.write(data)
        except OSError:
            self.alive = False

    def close(self):
        self.alive = False
        try:
            os.close(self.fd)
        except OSError:
            pass


# ---------------------------------------------------------------- G-code

def load_gcode(path):
    """(original line number, cleaned line) for every line that sends something."""
    out = []
    with open(path, encoding="utf-8", errors="replace") as f:
        for n, line in enumerate(f, 1):
            line = re.sub(r"\(.*?\)", "", line.split(";", 1)[0]).strip()
            if line and line != "%":
                out.append((n, line))
    return out


class Job:
    def __init__(self, path):
        self.path = path
        self.name = os.path.basename(path)
        self.lines = load_gcode(path)
        self.pos = 0            # next line to send
        self.mode = None        # "run" / "step" / None (loaded, idle)
        self.waiting = False    # a line was sent, its ok has not come
        self.paused = False
        self.started = 0.0
        self.error = ""

    def done(self):
        return self.pos >= len(self.lines) and not self.waiting


# ---------------------------------------------------------------- screen

screen = lcd.init()
clock = pygame.time.Clock()


def font(name, px):
    size = px / lcd.S if lcd.S != 1 else int(px)
    try:
        return pygame.font.Font(FONT_DIR + name, size)
    except (FileNotFoundError, OSError):
        return pygame.font.Font(None, size)


BIG = lcd.S > 1
f_mono = font("DejaVuSansMono.ttf", 11 if BIG else 6)
f_small = font("DejaVuSans.ttf", 11 if BIG else 7)
f_bold = font("DejaVuSans-Bold.ttf", 12 if BIG else 7)
f_big = font("DejaVuSansMono-Bold.ttf", 22 if BIG else 9)
LH = f_mono.get_linesize()
CW = f_mono.size("0")[0]
COLS = int(124 / CW)


def text(s, pos, color, f, right=False, center=False):
    img = f.render(s, True, color)
    x, y = pos
    if right:
        x -= img.get_width()
    elif center:
        x -= img.get_width() / 2
    screen.blit(img, (x, y))


def fit(s, f, width):
    if f.size(s)[0] <= width:
        return s
    while s and f.size(s + "…")[0] > width:
        s = s[:-1]
    return s + "…"


def wrap(s, cols):
    out = []
    while len(s) > cols:
        out.append(s[:cols])
        s = "  " + s[cols:]
    out.append(s)
    return out


def explain(line):
    """'error:22' -> 'error:22 не задано подачу F'; the same for ALARM."""
    m = re.match(r"^(error|ALARM):(\d+)", line)
    if m:
        table = GRBL_ERRORS if m.group(1) == "error" else GRBL_ALARMS
        desc = table.get(int(m.group(2)))
        if desc and desc not in line:
            return line + " - " + desc
    return line


# ---------------------------------------------------------------- the terminal

class Term:
    def __init__(self):
        self.cfg = self.load_cfg()
        self.port = None
        self.dev = None
        self.baud = self.cfg.get("baud", 115200)
        self.eol = self.cfg.get("eol", "\n")
        self.cmd = []            # (kind, text): in / resp / more / sys / err
        self.full = []           # (kind, text): rx / tx / status
        self.show_full = self.cfg.get("show_full", True)
        self.poll = False
        self.status_in_full = self.cfg.get("status_in_full", True)
        self.status = None       # (state, rest)
        self.wco = None          # the work coordinate offset (from reports that carry WCO)
        self.pendant = False
        self.step_i = 2
        self.jog = None          # {"key", "axis", "sign", "t0", "cont", "next"}
        self.spindle = self.cfg.get("spindle", 12000)
        self.spin_armed = 0.0
        self.last_poll = 0.0
        self.pending = None      # an answer being collected: {"shown", "more", "idx"}
        self.input = ""
        self.hist = self.load_hist()
        self.h = len(self.hist)
        self.scroll = 0          # lines scrolled up in the full pane (or the upper pane when it is alone)
        self.job = None
        self.note, self.note_t = "", 0.0
        self.retry_t = 0.0
        self.want_dev = self.cfg.get("port")      # chosen in F3; else ACM / USB

    # -- config
    @staticmethod
    def load_cfg():
        try:
            with open(CONFIG, encoding="utf-8") as f:
                return json.load(f)
        except (OSError, ValueError):
            return {}

    def save_cfg(self):
        self.cfg.update(baud=self.baud, eol=self.eol, show_full=self.show_full, status_in_full=self.status_in_full,
                        port=self.want_dev)
        try:
            os.makedirs(os.path.dirname(CONFIG), exist_ok=True)
            with open(CONFIG, "w", encoding="utf-8") as f:
                json.dump(self.cfg, f, indent=1)
        except OSError:
            pass

    @staticmethod
    def load_hist():
        try:
            with open(HISTORY_FILE, encoding="utf-8") as f:
                return [l.rstrip("\n") for l in f if l.strip()][-300:]
        except OSError:
            return []

    def save_hist(self):
        try:
            with open(HISTORY_FILE, "w", encoding="utf-8") as f:
                f.write("\n".join(self.hist[-300:]) + "\n")
        except OSError:
            pass

    # -- the port
    def say(self, kind, s):
        self.cmd.append((kind, s))
        del self.cmd[:-CMD_MAX]

    def flash(self, s):
        self.note, self.note_t = s, time.monotonic() + 3

    def connect(self, dev=None):
        self.disconnect()
        dev = dev or (self.want_dev if self.want_dev and os.path.exists(self.want_dev) else default_port())
        if not dev:
            return False
        try:
            self.port = Port(dev, self.baud)
            self.dev = dev
            self.say("sys", "під'єднано %s %d (%s)" % (dev, self.baud, port_info(dev) or "?"))
            return True
        except OSError as e:
            self.say("err", "%s: %s" % (dev, e.strerror or e))
            self.port = None
            return False

    def disconnect(self):
        if self.port:
            self.port.close()
        self.port = None

    def send(self, line, log=True, realtime=False):
        if not (self.port and self.port.alive):
            self.flash("порт не під'єднано (F3)")
            return False
        self.port.write(line if realtime else line + self.eol)
        shown = {"\x18": "Ctrl-X (скидання)", "\x85": "jog cancel"}.get(line, line)
        if len(shown) == 1 and ord(shown) < 32:
            shown = "Ctrl-" + chr(ord(shown) + 64)
        self.full.append(("tx", "> " + shown))
        if log:
            self.say("in", shown)
            self.pending = {"shown": 0, "more": 0, "idx": None}
        return True

    # -- received lines
    def feed(self):
        if not self.port:
            return
        for line in self.port.take():
            if not line.strip():
                continue
            is_status = line.startswith("<") and line.rstrip().endswith(">")
            if is_status:
                body = line.strip()[1:-1].split("|")
                self.status = (body[0].split(":")[0], body[1:])
                for part in body[1:]:
                    if part.startswith("WCO:"):
                        try:
                            self.wco = [float(v) for v in part[4:].split(",")]
                        except ValueError:
                            pass
                if self.status_in_full:
                    self.full.append(("status", line))
            else:
                self.full.append(("rx", line))
                self.on_line(line.strip())
            del self.full[:-FULL_MAX]

    def on_line(self, line):
        job = self.job
        final = line == "ok" or line.startswith("error") or line.startswith("ALARM")
        if job and job.waiting and (line == "ok" or line.startswith("error")):
            job.waiting = False
            if line.startswith("error"):
                n, src = job.lines[job.pos - 1]
                job.error = "рядок %d: %s - %s" % (n, explain(line), src)
                self.say("err", job.error)
                job.paused = True
            elif job.mode == "step":
                self.say("resp", line)
            if job.done():
                self.finish_job()
            return
        if self.pending is not None:
            p = self.pending
            if final:
                self.say("err" if line != "ok" else "resp", explain(line))
                self.pending = None
            elif p["shown"] < SHOW_LINES:
                self.say("resp", line)
                p["shown"] += 1
            else:                     # the rest only in the full output; one counter line here
                p["more"] += 1
                txt = "… ще %d (у повному виводі)" % p["more"]
                if p["idx"] is None:
                    self.say("more", txt)
                    p["idx"] = len(self.cmd) - 1
                elif p["idx"] < len(self.cmd):
                    self.cmd[p["idx"]] = ("more", txt)
            return
        # unsolicited: the important ones up here too
        if line.startswith(("ALARM", "error", "Grbl", "GrblHAL", "[MSG", "[HLP")) or "grbl" in line.lower()[:12]:
            self.say("err" if line.startswith(("ALARM", "error")) else "sys", explain(line))

    # -- G-code
    def finish_job(self):
        job = self.job
        if job and job.mode:
            dt = time.monotonic() - job.started
            self.say("sys", "■ %s: %d рядків за %d:%02d" % (job.name, len(job.lines), dt // 60, dt % 60))
            job.mode = None
            job.pos = 0

    def pump_job(self):
        job = self.job
        if not job or not job.mode or job.waiting or job.paused or job.done():
            return
        if job.mode == "run":
            n, line = job.lines[job.pos]
            if self.send(line, log=False):
                job.pos += 1
                job.waiting = True

    def step(self):
        job = self.job
        if not job or job.waiting:
            return
        if job.done() and job.mode is None:
            job.pos = 0
        if job.mode is None:
            job.mode, job.started, job.error = "step", time.monotonic(), ""
        job.paused = False
        if job.pos < len(job.lines):
            n, line = job.lines[job.pos]
            if self.send("%s" % line, log=False):
                self.say("in", "%d: %s" % (n, line))
                job.pos += 1
                job.waiting = True

    def run_all(self):
        job = self.job
        if not job:
            return
        if job.mode is None:
            job.pos = 0 if job.done() or job.pos == 0 else job.pos
            job.started = time.monotonic()
        job.mode, job.paused, job.error = "run", False, ""
        self.say("sys", "▶ %s: %d рядків" % (job.name, len(job.lines)))

    def stop_job(self, reset=True):
        if self.job and self.job.mode:
            self.say("sys", "■ зупинено на рядку %d" % (self.job.lines[max(0, self.job.pos - 1)][0]))
        if self.job:
            self.job.mode, self.job.waiting, self.job.paused, self.job.pos = None, False, False, 0
        if reset and self.port:
            self.send("\x18", log=False, realtime=True)   # grbl drops its buffers and stops

    # -- the pendant
    def positions(self):
        """(work, machine) coordinate lists from the last report (one computed through WCO)."""
        if not self.status:
            return None, None
        kv = dict(p.split(":", 1) for p in self.status[1] if ":" in p)
        try:
            mpos = [float(v) for v in kv["MPos"].split(",")] if "MPos" in kv else None
            wpos = [float(v) for v in kv["WPos"].split(",")] if "WPos" in kv else None
        except ValueError:
            return None, None
        if self.wco:
            if mpos and not wpos:
                wpos = [m - o for m, o in zip(mpos, self.wco)]
            elif wpos and not mpos:
                mpos = [w + o for w, o in zip(wpos, self.wco)]
        return wpos, mpos

    def jog_once(self, axis, dist, feed):
        self.send("$J=G91 G21 %s%.4f F%d" % (axis, dist, feed), log=False)

    def jog_start(self, key, axis, sign):
        step = JOG_STEPS[self.step_i]
        self.jog_once(axis, sign * step, JOG_FEEDS[step])
        now = time.monotonic()
        self.jog = {"key": key, "axis": axis, "sign": sign, "t0": now, "cont": False, "next": now + JOG_HOLD_S}

    def jog_tick(self, now):
        """Held: keep a little more motion queued (short increments - no far target past the soft limits)."""
        j = self.jog
        if not j or now < j["next"]:
            return
        feed = JOG_FEEDS[JOG_STEPS[self.step_i]]
        dist = feed / 60.0 * JOG_TICK_S * 1.3
        self.jog_once(j["axis"], j["sign"] * dist, feed)
        j["cont"], j["next"] = True, now + JOG_TICK_S

    def jog_stop(self, key):
        j = self.jog
        if j and j["key"] == key:
            if j["cont"] and self.port:
                self.send("\x85", log=False, realtime=True)     # jog cancel: stops at once
            self.jog = None

    def set_zero(self, axes):
        self.send("G10 L20 P0 " + " ".join("%s0" % a for a in axes), log=False)
        self.say("sys", "нуль: " + " ".join(axes))

    def spindle_on(self):
        st = self.status[1] if self.status else []
        acc = dict(p.split(":", 1) for p in st if ":" in p).get("A", "")
        return "S" in acc or "C" in acc

    def toggle_spindle(self):
        now = time.monotonic()
        if self.spindle_on():
            self.send("M5", log=False)
            self.say("sys", "шпиндель: вимк (M5)")
            self.spin_armed = 0
        elif now - self.spin_armed < 2.0:
            self.send("M3 S%d" % self.spindle, log=False)
            self.say("sys", "шпиндель: увімк M3 S%d" % self.spindle)
            self.spin_armed = 0
        else:
            self.spin_armed = now
            self.flash("s ще раз - увімкнути шпиндель S%d" % self.spindle)

    def estop(self):
        """Software emergency stop: jog cancel + grbl's soft reset - motion, spindle and coolant stop."""
        if self.port:
            self.port.write(b"\x85\x18")
            self.full.append(("tx", "> АВАРІЙНА ЗУПИНКА (jog cancel + Ctrl-X)"))
        self.jog = None
        if self.job and self.job.mode:
            self.job.mode, self.job.waiting, self.job.paused, self.job.pos = None, False, False, 0
        self.say("err", "■ АВАРІЙНА ЗУПИНКА - далі $X (F5), щоб розблокувати")

    def tick(self):
        now = time.monotonic()
        if self.port and not self.port.alive:
            self.say("err", "порт %s зник" % self.dev)
            if self.job and self.job.mode:
                self.job.paused, self.job.waiting = True, False
            self.disconnect()
            self.retry_t = now + 1
        if not self.port and now > self.retry_t:
            self.retry_t = now + 1.5
            dev = self.dev or self.want_dev
            if dev and os.path.exists(dev):          # the same device came back
                self.connect(dev)
            elif not self.dev and default_port():
                self.connect()
        self.feed()
        if self.pendant and self.port and now - self.last_poll > PENDANT_POLL_S:
            self.last_poll = now
            self.port.write("?")
        self.jog_tick(now)
        if self.poll and self.port and now - self.last_poll > POLL_S:
            self.last_poll = now
            self.port.write("?")
        self.pump_job()


# ---------------------------------------------------------------- drawing

def draw(t, popup):
    screen.fill(BG)
    # header: port, then the grbl status or the job
    port = "%s %d" % (os.path.basename(t.dev), t.baud) if t.port else "немає порту (F3)"
    text(port, (2, 0), GREEN if t.port else RED, f_bold)
    flags = ("?" if t.poll else "") + ("" if t.show_full else " ▤")
    text(flags, (126, 0), ACCENT, f_bold, right=True)
    y = 9
    if t.status:
        state, rest = t.status
        kv = dict(p.split(":", 1) for p in rest if ":" in p)
        pos = kv.get("WPos") or kv.get("MPos") or ""
        axes = " ".join("%s%s" % (a, v) for a, v in zip("XYZABC", pos.split(","))) if pos else ""
        text(state, (2, y), STATE_COLORS.get(state.split(":")[0], FG), f_bold)
        text(fit(axes, f_mono, 100), (32, y + 1), FG, f_mono)
        fs = kv.get("FS") or kv.get("F") or ""
        if fs:
            text("F/S " + fs, (126, y + 1), DIM, f_mono, right=True)
        y += 9
        # the rest: plugin fields (e.g. TBL / ST3215), pins, overrides - not the buffer or the offsets
        extra = ["%s:%s" % (k, v) for k, v in kv.items() if k not in ("MPos", "WPos", "FS", "F", "Bf", "WCO", "Ln")
                 and not (k == "Ov" and v == "100,100,100")]
        if extra:
            text(fit("  ".join(extra), f_mono, 124), (2, y), (170, 170, 120), f_mono)
            y += LH
    job = t.job
    if job:
        n = len(job.lines)
        frac = job.pos / n if n else 0
        pygame.draw.rect(screen, (40, 40, 40), (2, y + 1, 124, 7))
        pygame.draw.rect(screen, ACCENT if job.paused else BLUE if job.mode == "run" else (70, 110, 160),
                         (2, y + 1, 124 * frac, 7))
        mode = {"run": "▶", "step": "крок", None: "файл"}[job.mode] + (" ‖" if job.paused else "")
        text(fit("%s %s %d/%d" % (mode, job.name, job.pos, n), f_mono, 122), (4, y + 1), FG, f_mono)
        y += 9
    in_y = 128 - LH - 1
    top = y + 1
    if t.show_full:
        split = top + int((in_y - top) * 0.45)
    else:
        split = in_y - 1
    # upper pane: commands and their first answer lines
    colors = {"in": BLUE, "resp": FG, "more": DIM, "sys": CYAN, "err": RED}
    rows = []
    for kind, s in t.cmd:
        for w in wrap(("> " + s) if kind == "in" else s, COLS):
            rows.append((kind, w))
    n_up = int((split - top) // LH)
    off = t.scroll if not t.show_full else 0
    shown = rows[max(0, len(rows) - n_up - off):len(rows) - off]
    for i, (kind, s) in enumerate(shown):
        text(s, (2, top + i * LH), colors[kind], f_mono)
    # lower pane: everything
    if t.show_full:
        pygame.draw.line(screen, (70, 70, 70), (0, split), (128, split))
        text("повний вивід", (126, split - 1), (90, 90, 90), f_small, right=True)
        fcol = {"rx": (200, 200, 200), "tx": BLUE, "status": (110, 140, 110)}
        frows = []
        for kind, s in t.full[-400:]:
            for w in wrap(s, COLS):
                frows.append((kind, w))
        n_lo = int((in_y - split - 2) // LH)
        t.scroll = min(t.scroll, max(0, len(frows) - n_lo))
        part = frows[max(0, len(frows) - n_lo - t.scroll):len(frows) - t.scroll]
        for i, (kind, s) in enumerate(part):
            text(fit(s, f_mono, 124), (2, split + 2 + i * LH), fcol[kind], f_mono)
        if t.scroll:
            text("↑%d" % t.scroll, (126, in_y - LH), ACCENT, f_mono, right=True)
    # the input line
    pygame.draw.line(screen, (70, 70, 70), (0, in_y - 1), (128, in_y - 1))
    if t.note and time.monotonic() < t.note_t:
        text(fit(t.note, f_small, 124), (2, in_y), ACCENT, f_small)
    else:
        hint = ""
        if not t.input:
            hint = "Enter - наст. рядок" if job and job.mode == "step" else "F1 меню  ^P порт  ^O файл  quit"
        s = "> " + t.input[-(COLS - 3):]
        text(s, (2, in_y), FG, f_mono)
        if int(time.monotonic() * 2) % 2 == 0:
            pygame.draw.rect(screen, ACCENT, (2 + len(s) * CW, in_y, max(1, CW / 3), LH - 1))
        if hint:
            text(hint, (126, in_y + 1), (100, 100, 100), f_small, right=True)
    if popup:
        popup.draw()
    lcd.flip()


def draw_pendant(t, popup):
    screen.fill(BG)
    state = t.status[0] if t.status else "?"
    text("ПУЛЬТ", (2, 0), ACCENT, f_bold)
    text(state, (126, 0), STATE_COLORS.get(state.split(":")[0], FG) if t.status else DIM, f_bold, right=True)
    wpos, mpos = t.positions()
    text("робочі", (60, 10), DIM, f_small, right=True)
    text("машинні", (126, 10), DIM, f_small, right=True)
    y = 19
    for i, ax in enumerate("XYZ"):
        w = "%9.3f" % wpos[i] if wpos and i < len(wpos) else "      —"
        m = "%9.3f" % mpos[i] if mpos and i < len(mpos) else "      —"
        jog = t.jog and t.jog["axis"] == ax
        text(ax, (2, y), ACCENT if jog else BLUE, f_big)
        text(w, (60, y), FG, f_big, right=True)
        text(m, (126, y + 4), (160, 160, 160), f_mono, right=True)
        y += 15
    kv = dict(p.split(":", 1) for p in (t.status[1] if t.status else []) if ":" in p)
    fs = (kv.get("FS") or kv.get("F") or "").split(",")
    spin = t.spindle_on()
    text("F %s" % (fs[0] if fs and fs[0] else "—"), (2, y), DIM, f_small)
    text(("шпиндель ON %s" % (fs[1] if len(fs) > 1 else "")) if spin else "шпиндель off", (64, y), RED if spin else DIM,
         f_small, center=True)
    text("S %d" % t.spindle, (126, y), DIM, f_small, right=True)
    y += 10
    step = JOG_STEPS[t.step_i]
    pygame.draw.rect(screen, (50, 40, 0), (1, y, 126, 10), border_radius=2)
    text("крок %g мм   подача %d мм/хв" % (step, JOG_FEEDS[step]), (64, y + 1), ACCENT, f_small, center=True)
    y += 12
    if t.note and time.monotonic() < t.note_t:
        text(fit(t.note, f_small, 124), (64, y), ACCENT, f_small, center=True)
    elif t.cmd and t.cmd[-1][0] in ("err", "sys"):
        kind, s = t.cmd[-1]
        text(fit(s, f_small, 124), (64, y), RED if kind == "err" else CYAN, f_small, center=True)
    if lcd.DEVICE == "hat144":
        hints = ["джойст. X/Y  KEY1/2 Z  натиск - крок", "KEY3 - СТОП (ще раз - вихід)"]
    else:
        hints = ["←→ X  ↑↓ Y  PgUp/Dn Z  +- крок  x y z 0 нуль", "s шпиндель  , . оберти  ПРОБІЛ - СТОП  Esc"]
    for i, h in enumerate(hints):
        text(fit(h, f_small, 126), (64, 128 - (2 - i) * 9), (150, 150, 150), f_small, center=True)
    if popup:
        popup.draw()
    lcd.flip()


class Popup:
    """A list to choose from: UP / DOWN, Enter, Esc."""

    def __init__(self, title, items, on_pick, sel=0):
        self.title, self.items, self.on_pick, self.sel, self.top = title, items, on_pick, sel, 0

    def key(self, k, hat=False):
        if hat and k == pygame.K_3:          # HAT KEY3: close
            return "close"
        if k == pygame.K_UP:
            self.sel = (self.sel - 1) % len(self.items)
        elif k == pygame.K_DOWN:
            self.sel = (self.sel + 1) % len(self.items)
        elif k in (pygame.K_PAGEUP,):
            self.sel = max(0, self.sel - 8)
        elif k in (pygame.K_PAGEDOWN,):
            self.sel = min(len(self.items) - 1, self.sel + 8)
        elif k in (pygame.K_RETURN, pygame.K_KP_ENTER):
            return self.on_pick(self.sel)
        elif k in (pygame.K_ESCAPE, pygame.K_F1, pygame.K_F2, pygame.K_F3, pygame.K_F4, pygame.K_F5):
            return "close"
        return None

    def draw(self):
        lh = f_small.get_linesize()
        n = min(len(self.items), 10)
        h = 12 + n * lh + 3
        y0 = max(8, (128 - h) / 2)
        pygame.draw.rect(screen, (20, 20, 30), (6, y0, 116, h), border_radius=3)
        pygame.draw.rect(screen, ACCENT, (6, y0, 116, h), 1, border_radius=3)
        text(self.title, (64, y0 + 1), ACCENT, f_bold, center=True)
        self.top = min(max(self.top, self.sel - n + 1), self.sel)
        for i in range(self.top, min(len(self.items), self.top + n)):
            y = y0 + 11 + (i - self.top) * lh
            if i == self.sel:
                pygame.draw.rect(screen, (70, 60, 15), (8, y, 112, lh))
            text(fit(self.items[i], f_small, 108), (10, y), FG, f_small)


HELP = ["Введення + Enter - надіслати рядок", "↑/↓ - історія, PgUp/PgDn - прокрутка",
        "F2 / Tab - сховати / показати повний вивід", "F3 / Ctrl+P - порт, швидкість, кінець рядка, minicom",
        "F4 / Ctrl+O - файл G-code: відкрити, весь, кроками, пауза, стоп",
        "F5 / Ctrl+G - grbl: опитування ?, скидання, $X, $H",
        "? ! ~ на порожньому рядку - одразу (grbl)", "Ctrl+X - скидання, Ctrl+C / D - байт",
        "Esc - очистити рядок, закрити меню", "quit + Enter або F1 → Вихід - вийти",
        "HAT: KEY3 - меню, джойстик - вибір"]


def file_list(path):
    """Directories first, then G-code files."""
    try:
        names = sorted(os.listdir(path), key=str.lower)
    except OSError:
        return []
    dirs = [n + "/" for n in names if os.path.isdir(os.path.join(path, n)) and not n.startswith(".")]
    files = [n for n in names if n.lower().endswith(GCODE_EXT)]
    return ([".."] if path != "/" else []) + dirs + files


def main():
    t = Term()
    popup = None
    os.makedirs(GCODE_DIR, exist_ok=True)
    if not t.connect():
        t.say("sys", "немає /dev/ttyACM* і /dev/ttyUSB* - виберіть порт (F3)")
    browse = {"dir": t.cfg.get("gcode_dir", GCODE_DIR)}

    def port_menu():
        ports = list_ports()
        items = ["%s  %s" % (os.path.basename(p), port_info(p)) for p in ports]
        items += ["Швидкість: %d" % t.baud, "Кінець рядка: %s" % dict(EOLS)[t.eol],
                  "Відкрити в minicom", "Від'єднати"]

        def pick(i):
            nonlocal popup
            if i < len(ports):
                t.want_dev = ports[i]
                t.dev = None
                t.connect(ports[i])
                t.save_cfg()
                return "close"
            what = items[i]
            if what.startswith("Швидкість"):
                t.baud = BAUDS[(BAUDS.index(t.baud) + 1) % len(BAUDS)] if t.baud in BAUDS else 115200
                if t.dev:
                    t.connect(t.dev)
                t.save_cfg()
                popup = port_menu()
                popup.sel = i
                return None
            if what.startswith("Кінець"):
                keys = [e for e, _ in EOLS]
                t.eol = keys[(keys.index(t.eol) + 1) % len(keys)]
                t.save_cfg()
                popup = port_menu()
                popup.sel = i
                return None
            if what.startswith("Відкрити в minicom"):
                if not (t.dev or t.want_dev):
                    t.flash("спершу виберіть порт")
                    return "close"
                t.want_dev = t.dev or t.want_dev
                t.save_cfg()
                t.disconnect()
                return "minicom"
            t.disconnect()
            t.dev = None
            t.say("sys", "від'єднано")
            return "close"
        return Popup("Порт", items, pick)

    def file_menu():
        items = ["Відкрити файл…"]
        if t.job:
            items += ["Запустити весь", "Покроково (Enter - рядок)", "Пауза / продовжити", "Стоп (скидання)",
                      "Закрити файл"]

        def pick(i):
            nonlocal popup
            what = items[i]
            if what.startswith("Відкрити"):
                popup = browser()
                return None
            if what.startswith("Запустити"):
                t.run_all()
            elif what.startswith("Покроково"):
                t.job.mode, t.job.paused = None, False
                t.step()
            elif what.startswith("Пауза"):
                if t.job.mode == "run" and not t.job.paused:
                    t.job.paused = True
                    t.send("!", log=False, realtime=True)            # feed hold
                    t.say("sys", "‖ пауза (feed hold)")
                else:
                    t.job.paused = False
                    t.send("~", log=False, realtime=True)            # cycle start
                    t.say("sys", "▶ продовжити")
            elif what.startswith("Стоп"):
                t.stop_job()
            elif what.startswith("Закрити"):
                t.stop_job(reset=False)
                t.job = None
            return "close"
        return Popup("G-code" + (": " + t.job.name if t.job else ""), items, pick)

    def browser():
        path = browse["dir"]
        names = file_list(path)
        if not names:
            names = [".."]

        def pick(i):
            nonlocal popup
            n = names[i]
            if n == "..":
                browse["dir"] = os.path.dirname(path.rstrip("/")) or "/"
                popup = browser()
                return None
            full = os.path.join(path, n.rstrip("/"))
            if n.endswith("/"):
                browse["dir"] = full
                popup = browser()
                return None
            try:
                t.stop_job(reset=False)
                t.job = Job(full)
                t.cfg["gcode_dir"] = path
                t.save_cfg()
                t.say("sys", "файл %s: %d рядків G-code (F4 - запуск)" % (t.job.name, len(t.job.lines)))
            except OSError as e:
                t.say("err", "%s: %s" % (n, e.strerror or e))
            return "close"
        title = path.replace(os.path.expanduser("~"), "~")
        return Popup(fit(title, f_bold, 110), names, pick)

    def grbl_menu():
        items = ["Опитування стану ?: %s" % ("так" if t.poll else "ні"), "Стан у повному виводі: %s" %
                 ("так" if t.status_in_full else "ні"), "? - стан один раз", "Ctrl-X - програмне скидання",
                 "$X - зняти блокування", "$H - хомінг", "$$ - налаштування", "$G - стан парсера",
                 "$I - про плату", "! - пауза", "~ - продовжити"]

        def pick(i):
            nonlocal popup
            if i == 0:
                t.poll = not t.poll
                popup = grbl_menu()
                popup.sel = i
                return None
            if i == 1:
                t.status_in_full = not t.status_in_full
                t.save_cfg()
                popup = grbl_menu()
                popup.sel = i
                return None
            cmd = items[i].split(" - ")[0]
            if cmd == "Ctrl-X":
                t.send("\x18", log=True, realtime=True)
                t.pending = None
            elif cmd in ("?", "!", "~"):
                t.send(cmd, log=cmd != "?", realtime=True)
                t.pending = None
            else:
                t.send(cmd)
            return "close"
        return Popup("grblHAL", items, pick)

    def help_popup():
        return Popup("Довідка", HELP, lambda i: "close")

    def main_menu():
        items = ["Пульт (pendant)", "Порт…", "Файл G-code…", "grblHAL…",
                 "Повний вивід: %s" % ("сховати" if t.show_full else "показати"), "Довідка", "Вихід"]

        def pick(i):
            nonlocal popup
            i -= 1
            if i == -1:
                t.pendant = True
                t.wco = None
                return "close"
            if i == 0:
                popup = port_menu()
            elif i == 1:
                popup = file_menu()
            elif i == 2:
                popup = grbl_menu()
            elif i == 3:
                t.show_full = not t.show_full
                t.scroll = 0
                t.save_cfg()
                return "close"
            elif i == 4:
                popup = help_popup()
            else:
                return "quit"
            return None
        return Popup("Меню", items, pick)

    hat_stop = {"t": 0.0}
    JOG_KEYS = {pygame.K_LEFT: ("X", -1), pygame.K_RIGHT: ("X", 1), pygame.K_UP: ("Y", 1),
                pygame.K_DOWN: ("Y", -1), pygame.K_PAGEUP: ("Z", 1), pygame.K_PAGEDOWN: ("Z", -1)}

    def pendant_key(k, ch, hat):
        """The pendant's keys; returns "menu" to open the main menu."""
        if hat and k == pygame.K_3:                  # HAT KEY3: stop; again within 2 s - leave
            if time.monotonic() - hat_stop["t"] < 2.0:
                t.pendant = False
                return None
            t.estop()
            hat_stop["t"] = time.monotonic()
            t.flash("KEY3 ще раз - вийти з пульта")
            return None
        if hat and k in (pygame.K_1, pygame.K_2):    # HAT KEY1 / KEY2: Z up / down
            t.jog_start(k, "Z", 1 if k == pygame.K_1 else -1)
            return None
        if hat and k == pygame.K_RETURN:             # HAT press: the next step size
            t.step_i = (t.step_i + 1) % len(JOG_STEPS)
            return None
        if k == pygame.K_SPACE:
            t.estop()
        elif k == pygame.K_ESCAPE:
            if t.jog:
                t.jog_stop(t.jog["key"])
            t.pendant = False
        elif k == pygame.K_F1:
            return "menu"
        elif k in JOG_KEYS:
            if not t.jog:
                axis, sign = JOG_KEYS[k]
                t.jog_start(k, axis, sign)
        elif ch in ("+", "=") or k in (pygame.K_EQUALS, pygame.K_KP_PLUS):
            t.step_i = min(len(JOG_STEPS) - 1, t.step_i + 1)
        elif ch in ("-", "_") or k in (pygame.K_MINUS, pygame.K_KP_MINUS):
            t.step_i = max(0, t.step_i - 1)
        elif ch in ("x", "y", "z", "X", "Y", "Z"):
            t.set_zero([ch.upper()])
        elif ch == "0":
            t.set_zero(["X", "Y", "Z"])
        elif ch in ("s", "S"):
            t.toggle_spindle()
        elif ch in (",", "<", ".", ">"):
            i = SPINDLE_SPEEDS.index(t.spindle) if t.spindle in SPINDLE_SPEEDS else 5
            i = max(0, i - 1) if ch in (",", "<") else min(len(SPINDLE_SPEEDS) - 1, i + 1)
            t.spindle = SPINDLE_SPEEDS[i]
            t.cfg["spindle"] = t.spindle
            t.save_cfg()
            if t.spindle_on():                       # running: the new speed at once
                t.send("S%d" % t.spindle, log=False)
        elif ch == "\x18":                          # Ctrl-X works here too
            t.estop()
        return None

    running = True
    shown_key = None
    while running:
        for ev in pygame.event.get():
            if ev.type == pygame.QUIT:
                running = False
                break
            if ev.type == pygame.KEYUP and t.pendant:
                t.jog_stop(ev.key)                 # a held jog key let go: stop at once
                continue
            if ev.type != pygame.KEYDOWN:
                continue
            shown_key = None
            k = ev.key
            hat = getattr(ev, "hat", False)
            ch = getattr(ev, "unicode", "") if not hat else ""
            if t.pendant and not popup:
                r = pendant_key(k, ch, hat)
                if r == "menu":
                    popup = main_menu()
                continue
            if popup:
                r = popup.key(k, hat)
                if r == "close":
                    popup = None
                elif r == "quit":
                    popup = None
                    running = False
                elif r == "minicom":
                    popup = None
                    running = False
                    t.save_cfg()
                    subprocess.run(["sudo", "-n", "/usr/bin/systemctl", "start", "--no-block", "lcd-term@minicom.service"])
                continue
            # Ctrl+P / Ctrl+O / Ctrl+G - the same menus as F3 / F4 / F5 (keyboards without them)
            menu_key = {"\x10": pygame.K_F3, "\x0f": pygame.K_F4, "\x07": pygame.K_F5}.get(ch)
            if menu_key:
                k, ch = menu_key, ""
            if ch == "\x14":                       # Ctrl+T: the pendant
                t.pendant, t.wco = True, None
                continue
            if k == pygame.K_F1 or (hat and k == pygame.K_3):
                popup = main_menu()
            elif k in (pygame.K_F2, pygame.K_TAB):
                t.show_full = not t.show_full
                t.scroll = 0
                t.save_cfg()
            elif k == pygame.K_F3:
                popup = port_menu()
            elif k == pygame.K_F4:
                popup = file_menu()
            elif k == pygame.K_F5:
                popup = grbl_menu()
            elif k == pygame.K_ESCAPE:
                t.input = ""                      # Esc never leaves: quit + Enter or the menu does
            elif k in (pygame.K_RETURN, pygame.K_KP_ENTER):
                line = t.input
                if line.strip().lower() == "quit":    # leave (not sent to the device)
                    running = False
                    t.input = ""
                elif not line and t.job and t.job.mode == "step":
                    t.step()
                elif line:
                    if t.send(line):
                        if not t.hist or t.hist[-1] != line:
                            t.hist.append(line)
                        t.h = len(t.hist)
                        t.input = ""
                        t.scroll = 0

            elif k == pygame.K_BACKSPACE:
                t.input = t.input[:-1]
            elif k == pygame.K_UP:
                if t.h > 0:
                    t.h -= 1
                    t.input = t.hist[t.h]
            elif k == pygame.K_DOWN:
                if t.h < len(t.hist) - 1:
                    t.h += 1
                    t.input = t.hist[t.h]
                else:
                    t.h, t.input = len(t.hist), ""
            elif k == pygame.K_PAGEUP:
                t.scroll += 6
            elif k == pygame.K_PAGEDOWN:
                t.scroll = max(0, t.scroll - 6)
            elif ch and len(ch) == 1 and ord(ch) < 32:     # Ctrl+letter: that control byte, at once
                if ch == "\x18" and t.job and t.job.mode:
                    t.stop_job()                           # Ctrl-X: grbl's soft reset - the job is over
                else:
                    t.send(ch, log=True, realtime=True)
                    t.pending = None
            elif ch and ch.isprintable():
                if not t.input and ch in "?!~":       # grbl real-time commands
                    t.send(ch, log=ch != "?", realtime=True)
                    if ch == "?":
                        t.pending = None
                else:
                    t.input += ch
        t.tick()
        # redraw at most ~12 times a second, and only when something changed
        key = (len(t.cmd), t.cmd[-1] if t.cmd else None, len(t.full), t.full[-1] if t.full else None, t.input,
               t.status, t.scroll, t.show_full, t.poll, popup and (popup.sel, id(popup)), t.port is not None,
               t.job and (t.job.pos, t.job.mode, t.job.paused), t.note, int(time.monotonic() * 2),
               t.pendant, t.step_i, t.spindle, t.jog and t.jog["axis"], str(t.wco))
        if key != shown_key:
            (draw_pendant if t.pendant else draw)(t, popup)
            shown_key = key
        clock.tick(30)
    t.save_hist()
    t.save_cfg()
    if t.job and t.job.mode == "run":
        t.stop_job()
    t.disconnect()


if __name__ == "__main__":
    try:
        main()
    finally:
        screen.fill(BG)
        lcd.flip()
        lcd.quit()
