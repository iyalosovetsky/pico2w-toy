"""SERIAL: a terminal for serial devices, made for grblHAL (and fine for anything else).

The port: the first /dev/ttyACM*, else /dev/ttyUSB*, else a list to choose from (F3); it is
reopened when the device comes back (a grblHAL board resets on connect). Two panes: the upper one
holds what you typed with the first 1-2 lines of each answer (and ok / error / ALARM), the lower
one everything the device sent - F2 / Tab hides or shows it. grblHAL: the status line comes from
the "<...>" reports (they go to the full output only), ? ! ~ on an empty line are sent at once
(real-time commands), F5 - status polling, soft reset, unlock, home; error and alarm codes are
explained. F4 - a G-code file from ~/gcode: run it all (the next line after each "ok", a pause on
an error) or step by step (Enter sends the next line), pause / resume / stop; its toolpath, bounds
(do they fit the travel), an outline, progress with the time left. F3 also hands the port over to
the real minicom on the text console.

Profiles: the 3D scanner (USB; a pendant for Y, the rotary table M102-M104 and the ST3215 servo
M101, a scan wizard writing G-code) and the CNC (grblHAL's telnet). Both: overrides, the input
signals (Pn:), the $-settings with the firmware's own names and descriptions.
"""
import glob
import json
import math
import os
import re
import select
import socket
import subprocess
import sys
import termios
import threading
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import pygame  # noqa: E402
import lcd  # noqa: E402
import gcodeinfo  # noqa: E402
import shapeedit  # noqa: E402

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
NET_RETRY_S = 5.0
OVERRIDES = {"feed100": 0x90, "feed+10": 0x91, "feed-10": 0x92, "feed+1": 0x93, "feed-1": 0x94,
             "rapid100": 0x95, "rapid50": 0x96, "rapid25": 0x97,
             "spin100": 0x99, "spin+10": 0x9A, "spin-10": 0x9B, "spin+1": 0x9C, "spin-1": 0x9D}
OVERRIDE_NAMES = {"feed100": "подача 100%", "feed+10": "подача +10%", "feed-10": "подача -10%",
                  "feed+1": "подача +1%", "feed-1": "подача -1%", "rapid100": "швидкі 100%",
                  "rapid50": "швидкі 50%", "rapid25": "швидкі 25%", "spin100": "оберти 100%",
                  "spin+10": "оберти +10%", "spin-10": "оберти -10%", "spin+1": "оберти +1%", "spin-1": "оберти -1%"}
PIN_NAMES = {"X": "кінцевик X", "Y": "кінцевик Y", "Z": "кінцевик Z", "A": "кінцевик A", "P": "щуп",
             "D": "двері", "H": "кнопка hold", "R": "кнопка reset", "S": "кнопка start", "E": "E-stop",
             "O": "щуп: перевантаження", "M": "двигун: помилка", "T": "вимкнення інструменту"}
TABLE_STEPS = [1, 5, 10, 15, 30, 45, 90]     # degrees per tap (the scanner)
SERVO_STEPS = [1, 5, 15]

# two kinds of machine: the 3D scanner (Y + the rotary table M102-M104 + the ST3215 servo M101, on USB)
# and the 3-axis CNC (over telnet); any number of profiles, each with its own connection
PROFILES = [
    {"name": "3D-сканер", "kind": "scanner", "link": "serial", "port": None, "baud": 115200, "eol": "\n",
     "axes": "Y", "spindle": False, "table_rate": 100, "table_steps_per_deg": 8.88889},
    {"name": "Верстат", "kind": "cnc", "link": "tcp", "host": "", "tcp_port": 23, "eol": "\n",
     "axes": "XYZ", "spindle": True},
]
KINDS = {"scanner": "3D-сканер", "cnc": "верстат"}

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

# what to do (the common ones)
ADVICE = {
    ("alarm", 1): "Відведіть вісь з кінцевика, $X, потім хомінг $H - позиція могла збитися.",
    ("alarm", 2): "Ціль за межами ходу: виправте програму / нуль; $X можна безпечно.",
    ("alarm", 3): "$X, потім хомінг $H: після скидання в русі позиція могла збитися.",
    ("alarm", 4): "Перевірте щуп (не замкнений до старту), $X.",
    ("alarm", 5): "Щуп не торкнувся: збільшіть хід проби або підведіть ближче, $X.",
    ("alarm", 6): "Хомінг перервано: $X, повторіть $H.",
    ("alarm", 7): "Закрийте двері, $X, повторіть $H.",
    ("alarm", 8): "Кінцевик не відпустило: перевірте $27 (відскок) і кінцевик, $X, $H.",
    ("alarm", 9): "Кінцевик не знайдено: перевірте проводку / $23 (напрям) / $25, $X, $H.",
    ("alarm", 10): "Відпустіть аварійну кнопку, Ctrl-X, потім $X.",
    ("alarm", 11): "Потрібен хомінг: $H (або $X, якщо впевнені в позиції).",
    ("alarm", 14): "Кінцевик активний при старті: відведіть вісь вручну, $X.",
    ("error", 8): "$-команди лише в стані Idle - дочекайтеся кінця руху.",
    ("error", 9): "Заблоковано (ALARM / двері): $X або $H.",
    ("error", 15): "Jog за м'які межі: зменшіть крок або перевірте нуль / хомінг.",
    ("error", 20): "Команда не підтримується цією збіркою grblHAL.",
    ("error", 22): "Задайте подачу: F<мм/хв> у рядку руху (G1 X10 F300).",
    ("error", 79): "Спершу зніміть критичну подію (E-stop / ALARM): Ctrl-X, $X.",
}


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


class Net:
    """grblHAL's telnet (a raw TCP stream) with the same interface as Port; connects in the background."""

    def __init__(self, host, port):
        self.dev, self.baud = "%s:%d" % (host, port), 0
        self.host, self.port = host, port
        self.lines = []
        self.lock = threading.Lock()
        self.alive = True
        self.connected = False
        self.error = ""
        self.sock = None
        self.buf = b""
        self.t_buf = 0.0
        threading.Thread(target=self._run, daemon=True).start()

    def _run(self):
        try:
            self.sock = socket.create_connection((self.host, self.port), timeout=4)
            self.sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
            self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)
            self.sock.settimeout(0.1)
            self.connected = True
        except OSError as e:
            self.error = e.strerror or str(e)
            self.alive = False
            return
        while self.alive:
            try:
                data = self.sock.recv(4096)
                if not data:
                    raise OSError("closed")
            except socket.timeout:
                if self.buf and time.monotonic() - self.t_buf > 0.3:
                    self._push(self.buf)
                    self.buf = b""
                continue
            except OSError as e:
                self.error = self.error or e.strerror or str(e)
                self.alive = False
                break
            if b"\xff" in data:                  # telnet negotiation (IAC ...): not ours
                data = re.sub(rb"\xff[\xfb-\xfe].|\xff[\xf0-\xfa]", b"", data)
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
        if not self.connected:
            return
        try:
            self.sock.sendall(data)
        except OSError as e:
            self.error = e.strerror or str(e)
            self.alive = False

    def close(self):
        self.alive = False
        try:
            if self.sock:
                self.sock.close()
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
    def __init__(self, path, rapids=(3000.0, 3000.0, 1000.0)):
        self.path = path
        self.name = os.path.basename(path)
        self.lines = load_gcode(path)
        self.info = gcodeinfo.analyze([l for _, l in self.lines], rapids)
        self.pos = 0            # next line to send
        self.mode = None        # "run" / "step" / None (loaded, idle)
        self.waiting = False    # a line was sent, its ok has not come
        self.paused = False
        self.started = 0.0
        self.error = ""

    def done(self):
        return self.pos >= len(self.lines) and not self.waiting

    def progress(self):
        """(fraction done by the estimated time, seconds since the start, seconds left or None)."""
        n, info = len(self.lines), self.info
        total = info.time_s
        done_t = info.line_t[self.pos - 1] if self.pos and self.pos <= len(info.line_t) else 0.0
        frac = done_t / total if total > 0 else (self.pos / n if n else 0.0)
        elapsed = time.monotonic() - self.started if self.mode and self.started else 0.0
        left = None
        if total > 0:
            left = total - done_t
            if done_t > 10 and elapsed > 0:          # the estimate knows no acceleration: scale it by reality
                left *= min(5.0, max(0.3, elapsed / done_t))
        return min(1.0, frac), elapsed, left


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
        self.profiles = self.load_profiles(self.cfg)
        self.pi = min(max(0, int(self.cfg.get("profile", 0))), len(self.profiles) - 1)
        self.port = None
        self.dev = None
        self.auto = True         # reconnect by itself (off after "Від'єднати")
        self.fail_msg = ""
        self.net_said = False
        self.cmd = []            # (kind, text): in / resp / more / sys / err
        self.full = []           # (kind, text): rx / tx / status
        self.show_full = self.cfg.get("show_full", True)
        self.poll = False
        self.status_in_full = self.cfg.get("status_in_full", True)
        self.status = None       # (state, rest)
        self.wco = None          # the work coordinate offset (from reports that carry WCO)
        self.alerts = []         # recent errors / alarms: {"kind", "code", "t", "ctx"}
        self.alert = None        # the one shown on the bar (or None)
        self.codes = {"error": {}, "alarm": {}}   # the device's own texts ($EE / $EA)
        self.codes_asked = False
        self.swallow_ok = 0      # "ok"s of our own empty lines (clearing grblHAL's error lock)
        self.status_n = 0        # status reports received (the pendant's indicator blinks on each)
        self.status_t = 0.0
        self.pendant = False
        self.step_i = 2
        self.tbl_i = 3           # the scanner: table step (TABLE_STEPS), servo step (SERVO_STEPS)
        self.srv_i = 1
        self.ask = None          # the input line asks for a value: {"prompt", "cb"}
        self.jog = None          # {"key", "axis", "sign", "t0", "cont", "next"}
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
        self.settings = {}       # $$ values {id: float or str}
        self.ov = None           # the overrides (feed, rapid, spindle %) from the last report that had them
        self.pins = ""           # Pn: the input signals now active
        self.queue = []          # lines to send one by one (outline)
        self.queue_wait = False
        self.apply_profile()

    # -- profiles
    @staticmethod
    def load_profiles(cfg):
        profs = cfg.get("profiles")
        if not isinstance(profs, list) or not profs:
            profs = json.loads(json.dumps(PROFILES))
            # the settings from before profiles belong to the first one (the USB device)
            for k in ("port", "baud", "eol"):
                if k in cfg:
                    profs[0][k] = cfg[k]
        for p in profs:
            base = next((d for d in PROFILES if d["kind"] == p.get("kind")), PROFILES[1])
            for k, v in base.items():
                p.setdefault(k, v)
        return profs

    @property
    def prof(self):
        return self.profiles[self.pi]

    def scanner(self):
        return self.prof.get("kind") == "scanner"

    def apply_profile(self):
        p = self.prof
        self.baud = int(p.get("baud") or 115200)
        self.eol = p.get("eol") or "\n"
        self.want_dev = p.get("port")
        self.spindle = int(p.get("spindle_s", 12000))
        self.axes = (p.get("axes") or "XYZ").upper()
        self.status, self.wco, self.ov, self.pins = None, None, None, ""
        self.settings = {}
        self.smeta, self.sgroups, self.sdescr = {}, {}, {}
        self.codes = {"error": {}, "alarm": {}}
        self.codes_asked = False
        self.fail_msg = ""

    def switch_profile(self, i):
        if i == self.pi:
            return
        if self.job and self.job.mode:
            self.stop_job(reset=False)
        self.job = None                               # a file belongs to its machine
        self.save_cfg()
        self.disconnect()
        self.pi, self.dev, self.auto = i, None, True
        self.apply_profile()
        self.say("sys", "профіль: %s (%s)" % (self.prof["name"], KINDS.get(self.prof["kind"], "")))
        self.save_cfg()
        if not self.connect():
            self.say("sys", self.no_link_hint())

    def no_link_hint(self):
        if self.prof.get("link") == "tcp":
            return "задайте адресу: telnet <IP> + Enter або F3 → Адреса" if not self.prof.get("host") else "немає зв'язку (F3)"
        return "немає /dev/ttyACM* і /dev/ttyUSB* - виберіть порт (F3)"

    # -- config
    @staticmethod
    def load_cfg():
        try:
            with open(CONFIG, encoding="utf-8") as f:
                return json.load(f)
        except (OSError, ValueError):
            return {}

    def save_cfg(self):
        self.prof.update(baud=self.baud, eol=self.eol, port=self.want_dev, spindle_s=self.spindle)
        for k in ("port", "baud", "eol", "spindle"):          # moved into the profiles
            self.cfg.pop(k, None)
        self.cfg.update(show_full=self.show_full, status_in_full=self.status_in_full, profiles=self.profiles,
                        profile=self.pi)
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
        if self.prof.get("link") == "tcp":
            host = (self.prof.get("host") or "").strip()
            if not host:
                return False
            self.port = Net(host, int(self.prof.get("tcp_port") or 23))
            self.dev, self.net_said = self.port.dev, False
            self.auto = True
            return True
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
        self.port.write(line.encode("latin-1") if realtime else line + self.eol)
        if line == "\x18":
            self.swallow_ok = 0                   # a soft reset: no answer to our empty line will come
        shown = {"\x18": "Ctrl-X (скидання)", "\x85": "jog cancel"}.get(line, line)
        if len(shown) == 1 and ord(shown) < 32:
            shown = "Ctrl-" + chr(ord(shown) + 64)
        self.full.append(("tx", "> " + shown))
        if log:
            self.say("in", shown)
            self.pending = {"shown": 0, "more": 0, "idx": None}
            if self.alert and self.alert["kind"] == "error":
                self.alert = None                 # a new command: the old error is history
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
                self.status_n += 1
                self.status_t = time.monotonic()
                a = self.alert
                if a and a["kind"] == "alarm" and self.status[0] != "Alarm" and time.time() - a["t"] > 1:
                    self.alert = None
                self.pins = ""                    # Pn: is left out when no input is active
                for part in body[1:]:
                    try:
                        if part.startswith("WCO:"):
                            self.wco = [float(v) for v in part[4:].split(",")]
                        elif part.startswith("Ov:"):
                            self.ov = [int(float(v)) for v in part[3:].split(",")][:3]
                        elif part.startswith("Pn:"):
                            self.pins = part[3:]
                    except ValueError:
                        pass
                if self.status_in_full:
                    self.full.append(("status", line))
            else:
                self.full.append(("rx", line))
                self.on_line(line.strip())
            del self.full[:-FULL_MAX]

    def note_alert(self, line, ctx=""):
        m = re.match(r"^(error|ALARM):(\d+)", line)
        if not m:
            return
        a = {"kind": m.group(1).lower(), "code": int(m.group(2)), "t": time.time(), "ctx": ctx}
        self.alerts = (self.alerts + [a])[-12:]
        self.alert = a
        lcd.play("lose" if a["kind"] == "alarm" else "error")
        if not self.codes_asked and not (self.job and self.job.mode == "run" and not self.job.paused):
            self.codes_asked = True               # the device's own explanations, once
            self.send("$EA", log=False)
            self.send("$EE", log=False)

    def code_text(self, kind, code):
        return self.codes[kind].get(code, "")

    def on_settings_line(self, line):
        """$$ / $ES / $EG / $SED answers -> settings, their details, groups, descriptions; True if it was one."""
        m = re.match(r"^\$(\d+)=(.*)$", line)
        if m:
            v = m.group(2).strip()
            try:
                self.settings[int(m.group(1))] = float(v)
            except ValueError:
                self.settings[int(m.group(1))] = v
            return True
        if line.startswith("[SETTING:") and line.endswith("]"):
            f = line[9:-1].split("|")
            if len(f) >= 8 and f[0].isdigit():
                self.smeta[int(f[0])] = {"group": int(f[1]) if f[1].isdigit() else 0, "name": f[2], "unit": f[3],
                                         "type": int(f[4]) if f[4].isdigit() else 6, "format": f[5],
                                         "min": f[6], "max": f[7], "reboot": len(f) > 8 and f[8] == "1"}
            return True
        if line.startswith("[SETTINGGROUP:") and line.endswith("]"):
            f = line[14:-1].split("|")
            if len(f) >= 3 and f[0].isdigit():
                self.sgroups[int(f[0])] = (int(f[1]) if f[1].isdigit() else 0, f[2])
            return True
        if line.startswith("[SETTINGDESCR:") and line.endswith("]"):
            f = line[14:-1].split("|", 1)
            if f[0].isdigit():
                self.sdescr[int(f[0])] = (f[1] if len(f) > 1 else "").replace("\\n", "\n")   # literal \n
            return True
        return False

    def on_line(self, line):
        m = re.match(r"^\[(ERROR|ALARM)CODE:(\d+)\|([^|]*)\|(.*)\]$", line)
        if m:                                     # $EE / $EA lines
            self.codes["error" if m.group(1) == "ERROR" else "alarm"][int(m.group(2))] = (m.group(4) or m.group(3)).strip()
            return
        if self.on_settings_line(line) and self.pending is None:
            return
        if line == "ok" and self.swallow_ok:           # the answer to our lock-clearing empty line
            self.swallow_ok -= 1
            return
        if line.startswith("error:") and self.port:
            # grblHAL (COMPATIBILITY_LEVEL 0) refuses every following G-code line with the same error
            # until an empty line, a $-command or a soft reset: send the empty line ourselves
            self.port.write(self.eol)
            self.swallow_ok += 1
            self.full.append(("tx", "> (порожній рядок - зняти блокування grblHAL після помилки)"))
        if line.startswith(("error:", "ALARM:")):
            ctx = ""
            if self.job and self.job.waiting and self.job.pos:
                n, src = self.job.lines[self.job.pos - 1]
                ctx = "рядок %d: %s" % (n, src)
            elif self.cmd:
                last_in = [s for k, s in self.cmd if k == "in"]
                ctx = last_in[-1] if last_in else ""
            self.note_alert(line, ctx)
        if line.startswith("[MSG:Caution: Unlocked") or line.startswith("[MSG:Unlocked"):
            if self.alert and self.alert["kind"] == "alarm":
                self.alert = None
        if self.queue_wait and (line == "ok" or line.startswith("error")):
            self.queue_wait = False
            if line.startswith("error"):
                self.queue = []                       # the rest makes no sense after an error
                self.say("err", explain(line))
            return
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
            lcd.play("win")
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
        self.swallow_ok = 0
        if self.port:
            self.port.write(b"\x85\x18")
            self.full.append(("tx", "> АВАРІЙНА ЗУПИНКА (jog cancel + Ctrl-X)"))
        self.jog = None
        if self.job and self.job.mode:
            self.job.mode, self.job.waiting, self.job.paused, self.job.pos = None, False, False, 0
        self.say("err", "■ АВАРІЙНА ЗУПИНКА - далі Backspace ($X), щоб розблокувати")

    def unlock(self):
        """$X: leave the Alarm state (Backspace in the pendants, or on an empty input line)."""
        if self.send("$X"):
            self.flash("$X - зняти блокування")

    # -- overrides (grblHAL real-time bytes)
    def override(self, what):
        code = OVERRIDES[what]
        if self.send(chr(code), log=False, realtime=True):
            self.full[-1] = ("tx", "> корекція: " + OVERRIDE_NAMES[what])

    def rapid_cycle(self):
        cur = self.ov[1] if self.ov else 100
        self.override({100: "rapid50", 50: "rapid25"}.get(cur, "rapid100"))

    # -- settings and the file's bounds
    def rapids(self):
        return tuple(float(self.settings.get(110 + i, d)) if isinstance(self.settings.get(110 + i, d), float) else d
                     for i, d in enumerate((3000.0, 3000.0, 1000.0)))

    def ask_settings(self, details=False):
        """$$ (and $EG / $ES for the settings window) without cluttering the upper pane."""
        if details:
            self.send("$EG", log=False)
            self.send("$ES", log=False)
        self.send("$$", log=False)

    def outline(self):
        """Trace the file's XY bounds with G0 at the current height, then come back."""
        info = self.job.info
        wpos, _ = self.positions()
        if info.lo[0] is None or info.lo[1] is None or not wpos:
            self.flash("немає меж X/Y або позиції (?)")
            return
        x0, y0, x1, y1 = info.lo[0], info.lo[1], info.hi[0], info.hi[1]
        moves = ["G90", "G0 X%.3f Y%.3f" % (x0, y0), "G0 X%.3f" % x1, "G0 Y%.3f" % y1, "G0 X%.3f" % x0,
                 "G0 Y%.3f" % y0, "G0 X%.3f Y%.3f" % (wpos[0], wpos[1])]
        self.queue += moves
        self.say("sys", "обвід X %.1f..%.1f  Y %.1f..%.1f на поточній Z" % (x0, x1, y0, y1))

    def pump_queue(self):
        """Lines sent one at a time, each after the previous one's ok (the outline, the scanner's moves)."""
        if self.queue and not self.queue_wait and not (self.job and self.job.mode):
            line = self.queue.pop(0)
            if self.send(line, log=False):
                self.queue_wait = True
                self.full[-1] = ("tx", "> " + line)
            else:
                self.queue = []

    # -- the 3D scanner: the rotary table (M102 / M103 / M104) and the ST3215 servo (M101)
    def scan_fields(self):
        kv = dict(p.split(":", 1) for p in (self.status[1] if self.status else []) if ":" in p)
        def num(k):
            try:
                return float(kv[k])
            except (KeyError, ValueError):
                return None
        return num("TBL"), num("TBLABS"), num("ST3215")

    def table_turn(self, deg):
        rate = int(self.prof.get("table_rate", 100))
        self.send("M104 Q%g S%d" % (deg, rate), log=False)
        self.say("sys", "стіл %+g°" % deg)

    def table_spin(self, ccw):
        rate = int(self.prof.get("table_rate", 100))
        self.send("M102 S%d P%d" % (rate, 1 if ccw else 0), log=False)
        self.say("sys", "стіл обертається %s" % ("проти год." if ccw else "за год."))

    def table_stop(self):
        self.send("M103", log=False)
        self.say("sys", "стіл: стоп")

    def servo_limits(self):
        lo, hi = self.settings.get(451), self.settings.get(452)
        return (lo if isinstance(lo, float) else 0.0), (hi if isinstance(hi, float) else 360.0)

    def servo_move(self, delta):
        cur = self.scan_fields()[2]
        if cur is None:
            self.flash("кут серво невідомий (немає ST3215 у ?)")
            return
        lo, hi = self.servo_limits()
        target = min(hi, max(lo, round(cur + delta, 1)))
        self.send("M101 Q%g" % target, log=False)
        self.say("sys", "серво → %g°" % target)

    def tick(self):
        now = time.monotonic()
        net = isinstance(self.port, Net)
        if net and self.port.connected and not self.net_said:
            self.net_said = True
            self.fail_msg = ""
            self.say("sys", "під'єднано telnet %s" % self.dev)
        if self.port and not self.port.alive:
            if net and not self.port.connected:       # could not connect: say it once, retry quietly
                msg = "%s: %s" % (self.dev, self.port.error or "не відповідає")
                if msg != self.fail_msg:
                    self.say("err", msg + " - повтор кожні %d с" % NET_RETRY_S)
                    self.fail_msg = msg
            else:
                self.say("err", "%s: зв'язок втрачено" % self.dev if net else "порт %s зник" % self.dev)
                if self.job and self.job.mode:
                    self.job.paused, self.job.waiting = True, False
            self.disconnect()
            self.retry_t = now + (NET_RETRY_S if net else 1)
        if not self.port and now > self.retry_t and self.auto:
            self.retry_t = now + 1.5
            if self.prof.get("link") == "tcp":
                if self.prof.get("host"):
                    self.connect()
            else:
                dev = self.dev or self.want_dev
                if dev and os.path.exists(dev):          # the same device came back
                    self.connect(dev)
                elif not self.dev and default_port():
                    self.connect()
        self.feed()
        if self.alert and self.alert["kind"] == "error" and time.time() - self.alert["t"] > 15:
            self.alert = None
        if self.pendant and self.port and now - self.last_poll > PENDANT_POLL_S:
            self.last_poll = now
            self.port.write("?")
        self.jog_tick(now)
        self.pump_queue()
        if self.poll and self.port and now - self.last_poll > POLL_S:
            self.last_poll = now
            self.port.write("?")
        self.pump_job()


# ---------------------------------------------------------------- drawing

def draw(t, popup):
    screen.fill(BG)
    # header: port, then the grbl status or the job
    name = t.prof["name"]
    text(name, (2, 0), ACCENT, f_bold)
    x = 5 + f_bold.size(name)[0]
    color = RED
    if isinstance(t.port, Net):
        port, color = t.dev, GREEN if t.port.connected else ORANGE
    elif t.port:
        port, color = "%s %d" % (os.path.basename(t.dev), t.baud), GREEN
    else:
        port = "немає зв'язку (F3)"
    flags = ("?" if t.poll else "") + ("" if t.show_full else " ▤")
    fw = f_bold.size(flags)[0] if flags else 0
    text(fit(port, f_small, 124 - x - fw), (x, 1), color, f_small)
    text(flags, (126, 0), ACCENT, f_bold, right=True)
    y = 9
    if t.status:
        state, rest = t.status
        kv = dict(p.split(":", 1) for p in rest if ":" in p)
        pos = kv.get("WPos") or kv.get("MPos") or ""
        axes = " ".join("%s%s" % (a, v) for a, v in zip("XYZABC", pos.split(","))) if pos else ""
        text(state, (2, y), STATE_COLORS.get(state.split(":")[0], FG), f_bold)
        fs = kv.get("FS") or kv.get("F") or ""
        fsw = f_mono.size("F/S " + fs)[0] + 3 if fs else 0
        text(fit(axes, f_mono, 94 - fsw), (32, y + 1), FG, f_mono)
        if fs:
            text("F/S " + fs, (126, y + 1), DIM, f_mono, right=True)
        y += 9
        # the rest: plugin fields (e.g. TBL / ST3215), pins, overrides - not the buffer or the offsets
        extra = ["%s:%s" % (k, v) for k, v in kv.items() if k not in ("MPos", "WPos", "FS", "F", "Bf", "WCO", "Ln",
                                                                       "Pn", "A")
                 and not (k == "Ov" and v == "100,100,100")]
        pins = ("входи " + " ".join(t.pins)) if t.pins else ""
        if extra or pins:
            pw = f_bold.size(pins)[0] + 3 if pins else 0
            text(fit("  ".join(extra), f_mono, 124 - pw), (2, y), (170, 170, 120), f_mono)
            if pins:
                text(pins, (126, y - 1), RED, f_bold, right=True)
            y += LH
    y += draw_alert(t, y, "⌫ $X  ^E" if t.alert and t.alert["kind"] == "alarm" else "^E пояснення")
    job = t.job
    if job:
        frac, mode, tail = job_line(job)
        pygame.draw.rect(screen, (40, 40, 40), (2, y + 1, 124, 7))
        pygame.draw.rect(screen, ACCENT if job.paused else BLUE if job.mode == "run" else (70, 110, 160),
                         (2, y + 1, 124 * frac, 7))
        tw = f_mono.size(tail)[0]
        text(fit("%s %s" % (mode, job.name), f_mono, 120 - tw), (4, y + 1), FG, f_mono)
        text(tail, (124, y + 1), FG, f_mono, right=True)
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
    if t.ask:
        pygame.draw.rect(screen, (40, 40, 10), (0, in_y - LH - 1, 128, LH * 2 + 2))
        text(fit(t.ask["prompt"] + " (Enter / Esc)", f_small, 124), (2, in_y - LH), ACCENT, f_small)
        s = t.input[-(COLS - 1):]
        text(s, (2, in_y), FG, f_mono)
        if int(time.monotonic() * 2) % 2 == 0:
            pygame.draw.rect(screen, ACCENT, (2 + len(s) * CW, in_y, max(1, CW / 3), LH - 1))
    elif t.note and time.monotonic() < t.note_t:
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


def alert_short(t, a):
    table = GRBL_ALARMS if a["kind"] == "alarm" else GRBL_ERRORS
    return table.get(a["code"]) or t.code_text(a["kind"], a["code"]) or "?"


def draw_alert(t, y, key_hint):
    """The red (ALARM) / orange (error) bar; returns the height it took."""
    a = t.alert
    if not a:
        return 0
    color = RED if a["kind"] == "alarm" else ORANGE
    pygame.draw.rect(screen, color, (0, y, 128, 10))
    s = "⚠ %s %d · %s" % ("ALARM" if a["kind"] == "alarm" else "error", a["code"], alert_short(t, a))
    hint_w = f_small.size(key_hint)[0]
    text(fit(s, f_bold, 124 - hint_w - 3), (2, y + 1), BG, f_bold)
    text(key_hint, (126, y + 1), BG, f_small, right=True)
    return 11


def explain_lines(t):
    """The explanation window's text: the last alert in detail, then the earlier ones."""
    if not t.alerts:
        return ["Помилок і аварій ще не було."]
    a = t.alerts[-1]
    kind = "ALARM" if a["kind"] == "alarm" else "error"
    out = ["# %s %d - %s" % (kind, a["code"], alert_short(t, a))]
    dev = t.code_text(a["kind"], a["code"])
    if dev:
        out.append("grblHAL: " + dev)
    elif t.codes_asked:
        out.append("grblHAL: (опис ще не надійшов)")
    adv = ADVICE.get((a["kind"], a["code"]))
    if adv:
        out.append("Що робити: " + adv)
    if a["ctx"]:
        out.append("Після: " + a["ctx"])
    out.append("Час: " + time.strftime("%H:%M:%S", time.localtime(a["t"])))
    if len(t.alerts) > 1:
        out.append("# Раніше")
        for b in reversed(t.alerts[:-1]):
            out.append("%s %s %d - %s" % (time.strftime("%H:%M:%S", time.localtime(b["t"])),
                                          "ALARM" if b["kind"] == "alarm" else "error", b["code"], alert_short(t, b)))
    return out


class TextPopup:
    """A scrollable text window (UP / DOWN), any other key closes."""

    @staticmethod
    def wrap_px(s, width, f=None):
        f = f or f_small
        rows, cur = [], ""
        for w in s.split(" "):
            cand = (cur + " " + w).strip()
            if cur and f.size(cand)[0] > width:
                rows.append(cur)
                cur = "  " + w
            else:
                cur = cand
        rows.append(cur)
        return rows

    def __init__(self, title, lines):
        self.title = title
        self.rows = []
        for line in lines:
            head = line.startswith("# ")
            s = line[2:] if head else line
            cur = ""
            for w in s.split(" "):
                cand = (cur + " " + w).strip()
                if cur and f_small.size(cand)[0] > 110:
                    self.rows.append((cur, head))
                    cur = "  " + w
                else:
                    cur = cand
            self.rows.append((cur, head))
        self.top = 0
        self.sel = 0

    def key(self, k, hat=False, ch=""):
        n = 11
        if k == pygame.K_UP:
            self.top = max(0, self.top - 1)
        elif k == pygame.K_DOWN:
            self.top = min(max(0, len(self.rows) - n), self.top + 1)
        else:
            return "close"
        self.sel = self.top
        return None

    def draw(self):
        lh = f_small.get_linesize()
        n = min(len(self.rows), 11)
        h = 12 + n * lh + 3
        y0 = max(4, (128 - h) / 2)
        pygame.draw.rect(screen, (20, 20, 30), (4, y0, 120, h), border_radius=3)
        pygame.draw.rect(screen, ACCENT, (4, y0, 120, h), 1, border_radius=3)
        text(self.title, (64, y0 + 1), ACCENT, f_bold, center=True)
        for i, (s, head) in enumerate(self.rows[self.top:self.top + n]):
            text(s, (8, y0 + 11 + i * lh), ACCENT if head else FG, f_bold if head else f_small)
        if self.top + n < len(self.rows):
            text("▼", (120, y0 + h - lh), DIM, f_small, right=True)


def draw_pendant(t, popup):
    screen.fill(BG)
    state = t.status[0] if t.status else "?"
    text("ПУЛЬТ", (2, 0), ACCENT, f_bold)
    # the "?" indicator: blinks on every status report; red when none came for a second
    x = 4 + f_bold.size("ПУЛЬТ")[0] + 4
    stale = time.monotonic() - t.status_t > 1.0
    color = RED if stale else ((120, 255, 140) if t.status_n % 2 else (30, 110, 50))
    pygame.draw.circle(screen, color, (x, 4.5), 2.5)
    if stale:
        text("немає ?", (x + 5, 0), RED, f_small)
    text(state, (126, 0), STATE_COLORS.get(state.split(":")[0], FG) if t.status else DIM, f_bold, right=True)
    wpos, mpos = t.positions()
    if t.alert:                                  # the bar takes the column titles' line
        draw_alert(t, 9, "⌫ $X  e" if t.alert["kind"] == "alarm" else "e - пояснення")
    else:
        text("робочі", (60, 10), DIM, f_small, right=True)
        text("машинні", (126, 10), DIM, f_small, right=True)
    y = 21
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
    if t.job and t.job.mode:
        frac, mode, tail = job_line(t.job)
        pygame.draw.rect(screen, (40, 40, 40), (2, y, 124, 8))
        pygame.draw.rect(screen, ACCENT if t.job.paused else BLUE, (2, y, 124 * frac, 8))
        text(fit(mode + tail, f_small, 122), (4, y), FG, f_small)
    elif t.note and time.monotonic() < t.note_t:
        text(fit(t.note, f_small, 124), (64, y), ACCENT, f_small, center=True)
    elif t.cmd and t.cmd[-1][0] in ("err", "sys"):
        kind, s = t.cmd[-1]
        text(fit(s, f_small, 124), (64, y), RED if kind == "err" else CYAN, f_small, center=True)
    draw_ov_pins(t, y + 10)
    if lcd.DEVICE == "hat144":
        hints = ["джойст. X/Y  KEY1/2 Z  натиск - крок", "KEY3 - СТОП (ще раз - вихід)"]
    else:
        hints = hint_page([["←→ X  ↑↓ Y  / \\ Z  +- крок", "ПРОБІЛ - СТОП  F1 довідка  Esc - вихід"],
                           ["x y z - нуль осі   0 - усіх", "s шпиндель (двічі)   , . оберти"],
                           ["F2 / F3 подача ±10%   F4 - 100%", "F5 - швидкі 100 / 50 / 25%   e - помилка"]])
    for i, h in enumerate(hints):
        text(fit(h, f_small, 126), (64, 128 - (2 - i) * 9), (150, 150, 150), f_small, center=True)
    if popup:
        popup.draw()
    lcd.flip()


class Popup:
    """A list to choose from: UP / DOWN, Enter, Esc."""

    def __init__(self, title, items, on_pick, sel=0):
        self.title, self.items, self.on_pick, self.sel, self.top = title, items, on_pick, sel, 0

    def key(self, k, hat=False, ch=""):
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


def hhmm(sec):
    sec = int(sec or 0)
    return "%d:%02d:%02d" % (sec // 3600, sec // 60 % 60, sec % 60) if sec >= 3600 else "%d:%02d" % (sec // 60, sec % 60)


def hint_page(pages):
    """Long key hints: one page at a time, the next every 3 seconds."""
    return pages[int(time.monotonic() / 3) % len(pages)]


def draw_ov_pins(t, y):
    """The overrides (when not 100 %) on the left, the active inputs (Pn:) on the right, in red."""
    pw = 0
    if t.pins:
        pins = ("входи: " if lcd.DEVICE != "hat144" else "") + " ".join(t.pins)
        pw = f_bold.size(pins)[0] + 3
        text(pins, (126, y), RED, f_bold, right=True)
    if t.ov:
        names = ("F", "R", "S") if t.prof.get("spindle", True) else ("F", "R")
        parts = ["%s%d%%" % (n, v) for n, v in zip(names, t.ov)]
        changed = any(v != 100 for v in t.ov[:len(names)])
        s = ("корекції " if lcd.DEVICE != "hat144" else "") + " ".join(parts)
        text(fit(s, f_small, 124 - pw), (2, y), ACCENT if changed else DIM, f_small)


def job_line(job):
    frac, elapsed, left = job.progress()
    mode = {"run": "▶", "step": "крок", None: "файл"}[job.mode] + (" ‖" if job.paused else "")
    tail = " %d%%" % round(frac * 100)
    if job.mode and elapsed:
        tail += " " + hhmm(elapsed)
    if left is not None:
        tail += " ≈" + hhmm(left) + (" лиш." if job.mode else "")
    return frac, mode, tail


def bounds_lines(t, job):
    """The bounds window: the size, the range per axis, the time; does it fit the machine's travel?"""
    info = job.info
    out = ["# Розміри (робочі координати)"]
    for i, a in enumerate("XYZ"):
        if info.lo[i] is not None:
            out.append("%s: %.2f … %.2f  (%.2f мм)" % (a, info.lo[i], info.hi[i], info.hi[i] - info.lo[i]))
    out.append("Рухи: подача %.0f мм, швидкі %.0f мм" % (info.feed_mm, info.rapid_mm))
    out.append("Час ≈ %s (без прискорень)" % hhmm(info.time_s))
    out.append("# Чи вміщується")
    if 130 not in t.settings:
        out.append("Хід осей ($130-$132) невідомий - $$ запитано, відкрийте ще раз." if t.port else "Немає зв'язку.")
        if t.port:
            t.ask_settings()
    elif not t.wco:
        out.append("Невідоме зміщення нуля (WCO): відкрийте пульт або надішліть ? кілька разів.")
    else:
        bad = gcodeinfo.fits(info, t.wco, t.settings)
        for i, a in enumerate("XYZ"):
            env = gcodeinfo.envelope(t.settings, i)
            if env and info.lo[i] is not None:
                out.append("%s машинні %.1f … %.1f, хід %.1f … %.1f" % (a, info.lo[i] + t.wco[i], info.hi[i] + t.wco[i],
                                                                       env[0], env[1]))
        if bad:
            for a, under, over in bad:
                out.append("✗ %s виходить %s на %.1f мм" % (a, "за мінімум" if under else "за максимум", under or over))
        else:
            out.append("✓ Вміщується в хід (якщо хомінг зроблено).")
    if info.warnings:
        out.append("# Зауваження")
        out += info.warnings
    return out


class PathView:
    """The file's toolpath: XY (or XZ) to scale; done lines green, the machine's position a cross. A cross-hair
    walks the path (the nearest move is lit, and its G-code line in the window below); Tab - into the
    G-code window: the arrows go line by line and light their moves on the path."""

    AREA = (0, 10, 128, 76)             # x, y, w, h (logical); the G-code window under it
    CODE_Y = 87

    def __init__(self, t, job):
        self.t, self.job = t, job
        self.view = "XY"
        self.cache_key, self.cache = None, None
        self.sel = 0
        self.focus = "path"             # path / code
        self.line = None                # the G-code line (an index into job.lines) lit
        self.hold = None
        self.mod = 0
        self.by_line = {}
        for i, sg in enumerate(job.info.segs):
            self.by_line.setdefault(sg[7], []).append(i)
        self.fit()
        self.cur = [self.cx, self.cy]

    def axes(self):
        return (0, 1) if self.view == "XY" else (0, 2)

    def fit(self):
        info = self.job.info
        a, b = self.axes()
        lo = [info.lo[a] if info.lo[a] is not None else 0.0, info.lo[b] if info.lo[b] is not None else 0.0]
        hi = [info.hi[a] if info.hi[a] is not None else 1.0, info.hi[b] if info.hi[b] is not None else 1.0]
        w, h = max(hi[0] - lo[0], 0.1), max(hi[1] - lo[1], 0.1)
        ax, ay, aw, ah = self.AREA
        self.scale = min((aw - 6) / w, (ah - 6) / h)
        self.cx, self.cy = (lo[0] + hi[0]) / 2, (lo[1] + hi[1]) / 2

    def to_px(self, x, y):
        ax, ay, aw, ah = self.AREA
        return ax + aw / 2 + (x - self.cx) * self.scale, ay + ah / 2 - (y - self.cy) * self.scale

    def follow(self):
        ax, ay, aw, ah = self.AREA
        x, y = self.to_px(*self.cur)
        if not (ax + 3 <= x <= ax + aw - 3):
            self.cx = self.cur[0]
        if not (ay + 3 <= y <= ay + ah - 3):
            self.cy = self.cur[1]

    def nearest(self):
        """The G-code line of the move nearest the cross-hair, within 5 px."""
        a, b = self.axes()
        best, line = 5.0 / self.scale, None
        px, py = self.cur
        for sg in self.job.info.segs:
            x0, y0, x1, y1 = sg[a], sg[b], sg[3 + a], sg[3 + b]
            dx, dy = x1 - x0, y1 - y0
            L = dx * dx + dy * dy
            u = 0.0 if L == 0 else max(0.0, min(1.0, ((px - x0) * dx + (py - y0) * dy) / L))
            dist = math.hypot(px - x0 - u * dx, py - y0 - u * dy)
            if dist <= best:
                best, line = dist, sg[7]
        return line

    def to_line(self, i):
        """Light G-code line i; the cross-hair to the end of its moves."""
        n = len(self.job.lines)
        if not n:
            return
        self.line = max(0, min(n - 1, i))
        segs = self.by_line.get(self.line)
        if segs:
            a, b = self.axes()
            sg = self.job.info.segs[segs[-1]]
            self.cur = [sg[3 + a], sg[3 + b]]
            self.follow()

    def step(self, k, n=1):
        d = n * 2.0 / self.scale                       # 2 px a step
        dx, dy = {pygame.K_LEFT: (-d, 0), pygame.K_RIGHT: (d, 0), pygame.K_UP: (0, d), pygame.K_DOWN: (0, -d)}[k]
        self.cur = [self.cur[0] + dx, self.cur[1] + dy]
        self.follow()
        line = self.nearest()
        if line is not None:
            self.line = line

    def keyup(self, k):
        if self.hold and self.hold["key"] == k:
            self.hold = None

    def tick(self):
        h = self.hold
        now = time.monotonic()
        if not h or now < h["next"]:
            return
        if self.focus == "path":
            self.step(h["key"], 3 if now - h["t0"] > 1.5 else 1)
        else:
            self.to_line((self.line or 0) + (1 if h["key"] == pygame.K_DOWN else -1))
        h["next"] = now + (0.06 if self.focus == "path" else 0.08)

    def key(self, k, hat=False, ch=""):
        arrows = (pygame.K_LEFT, pygame.K_RIGHT, pygame.K_UP, pygame.K_DOWN)
        if hat and k == pygame.K_3:
            return "close"
        if (hat and k == pygame.K_RETURN) or k == pygame.K_TAB:
            self.focus = "code" if self.focus == "path" else "path"
            if self.focus == "code" and self.line is None:
                self.to_line(0)
        elif k == pygame.K_ESCAPE or k in (pygame.K_F1, pygame.K_F2, pygame.K_F3, pygame.K_F4, pygame.K_F5):
            return "close"
        elif k in arrows and self.focus == "path":
            self.step(k)
            self.hold = {"key": k, "t0": time.monotonic(), "next": time.monotonic() + 0.35}
        elif k in (pygame.K_UP, pygame.K_DOWN):
            self.to_line((self.line or 0) + (1 if k == pygame.K_DOWN else -1))
            self.hold = {"key": k, "t0": time.monotonic(), "next": time.monotonic() + 0.4}
        elif k in (pygame.K_PAGEUP, pygame.K_PAGEDOWN) or (self.focus == "code" and k in (pygame.K_LEFT, pygame.K_RIGHT)):
            self.to_line((self.line or 0) + (5 if k in (pygame.K_PAGEDOWN, pygame.K_RIGHT) else -5))
        elif ch in ("+", "=") or k in (pygame.K_KP_PLUS,) or (hat and k == pygame.K_1):
            self.scale *= 1.5
            self.cx, self.cy = self.cur
        elif ch in ("-", "_") or k in (pygame.K_KP_MINUS,) or (hat and k == pygame.K_2):
            self.scale /= 1.5
        elif ch == "0" or k == pygame.K_HOME:
            self.fit()
        elif ch in ("v", "V"):
            a, b = self.axes()
            self.view = "XZ" if self.view == "XY" else "XY"
            self.fit()
            if self.line is not None:
                self.to_line(self.line)
            else:
                self.cur = [self.cx, self.cy]
        return None

    def state(self):
        return repr((self.focus, self.line, [round(v, 4) for v in self.cur], self.scale, self.cx, self.cy, self.view,
                     self.job.pos))

    def render(self, done):
        """The toolpath on a native surface (redrawn when the view or the done part changes)."""
        ax, ay, aw, ah = self.AREA
        surf = pygame.Surface((lcd.sc(aw), lcd.sc(ah)))
        surf.fill(BG)
        S = lcd.S
        info = self.job.info
        a, b = self.axes()
        zlo, zhi = info.lo[2], info.hi[2]
        span = (zhi - zlo) if zlo is not None and zhi is not None and zhi > zlo else 0
        ox, oy = aw / 2 - self.cx * self.scale, ah / 2 + self.cy * self.scale
        sx = self.scale * S
        draw_line = pygame.draw.line
        # the work origin
        x0, y0 = ox * S, oy * S
        draw_line(surf, (60, 60, 110), (x0 - 4 * S, y0), (x0 + 8 * S, y0))
        draw_line(surf, (60, 60, 110), (x0, y0 + 4 * S), (x0, y0 - 8 * S))
        for i, sg in enumerate(info.segs):
            p0 = (ox * S + sg[a] * sx, oy * S - sg[b] * sx)
            p1 = (ox * S + sg[3 + a] * sx, oy * S - sg[3 + b] * sx)
            if sg[7] < done:
                c = (40, 90, 50) if sg[6] else GREEN
            elif sg[6]:
                c = (85, 85, 85)
            elif span:
                f = (sg[5] - zlo) / span                 # deep = orange, high = cyan
                c = (int(255 + (80 - 255) * f), int(150 + (220 - 150) * f), int(40 + (220 - 40) * f))
            else:
                c = CYAN
            draw_line(surf, c, p0, p1)
        return surf

    def draw(self):
        t, job = self.t, self.job
        info = job.info
        screen.fill(BG)
        text(fit(job.name, f_bold, 80), (2, 0), ACCENT, f_bold)
        text(("Tab ↔  " if info.segs else "") + self.view, (126, 0), CYAN, f_bold, right=True)
        done = job.pos if job.mode or job.pos else 0
        n = max(1, len(info.segs))
        bucket = 0
        if info.segs and done:                    # redraw the done part in ~200 steps over a job
            idx = [sg[7] for sg in info.segs]
            k = next((i for i, v in enumerate(idx) if v >= done), len(idx))
            bucket = int(k * 200 / n)
        key = (self.view, self.scale, self.cx, self.cy, bucket)
        if key != self.cache_key:
            self.cache, self.cache_key = self.render(done), key
        ax, ay, aw, ah = self.AREA
        screen.blit(self.cache, (ax, ay))
        a, b = self.axes()
        if self.line is not None:                 # the lit line's moves, white and thick
            for i in self.by_line.get(self.line, []):
                sg = info.segs[i]
                pygame.draw.line(screen, (255, 255, 255), self.to_px(sg[a], sg[b]), self.to_px(sg[3 + a], sg[3 + b]), 2)
        pygame.draw.rect(screen, ACCENT if self.focus == "path" else (50, 50, 50), (ax, ay, aw, ah), 1)
        wpos, _ = t.positions()
        if wpos and len(wpos) > b:                # the machine
            px, py = self.to_px(wpos[a], wpos[b])
            if ax <= px <= ax + aw and ay <= py <= ay + ah:
                pygame.draw.circle(screen, ACCENT, (px, py), 2, 1)
        if info.segs:                             # the cross-hair
            px, py = self.to_px(*self.cur)
            pygame.draw.line(screen, ORANGE, (px - 4, py), (px + 4, py))
            pygame.draw.line(screen, ORANGE, (px, py - 4), (px, py + 4))
        else:
            text("немає рухів X/Y з відомим початком", (64, 45), DIM, f_small, center=True)
        # the G-code window
        y0 = self.CODE_Y
        h = 118 - y0
        pygame.draw.rect(screen, (12, 12, 20), (0, y0, 128, h))
        pygame.draw.rect(screen, ACCENT if self.focus == "code" else (50, 50, 50), (0, y0, 128, h), 1)
        rows = max(1, int((h - 2) // LH))
        lines = job.lines
        cur = self.line if self.line is not None else 0
        top = max(0, min(cur - rows // 2, len(lines) - rows))
        nw = len(str(lines[-1][0])) if lines else 1
        for j in range(top, min(len(lines), top + rows)):
            y = y0 + 1 + (j - top) * LH
            if j == self.line:
                pygame.draw.rect(screen, (70, 60, 15), (1, y, 126, LH))
            num, src = lines[j]
            color = (110, 170, 110) if j < done else FG if j in self.by_line else (150, 150, 150)
            text(fit("%*d %s" % (nw, num, src), f_mono, 124), (2, y), color, f_mono)
        # the bottom: the cross-hair's coordinates, or the sizes
        if self.line is not None and info.segs:
            info_s = "%s%.2f %s%.2f · рядок %d/%d" % ("XYZ"[a], self.cur[0], "XYZ"[b], self.cur[1],
                                                      lines[self.line][0] if lines else 0, len(lines))
        else:
            sz = info.size()
            info_s = "  ".join("%s %.1f" % (c, v) for c, v in zip("XYZ", sz) if v is not None) + "  ≈" + hhmm(info.time_s)
        text(fit(info_s, f_small, 124), (2, 119), FG, f_small)


class SettingsView:
    """grblHAL's $-settings by group, with the firmware's own names, units, ranges and descriptions."""

    def __init__(self, t):
        self.t = t
        self.level = "groups"        # groups / list / detail
        self.group = None
        self.sel, self.top = 0, 0
        self.gsel = 0
        self.filter = ""
        self.edit = None             # the text being typed for a new value
        self.sid = None
        self.msg = ""
        if not t.smeta or not t.settings:
            t.ask_settings(details=True)

    def groups(self):
        t = self.t
        used = {}
        for sid, m in t.smeta.items():
            used[m["group"]] = used.get(m["group"], 0) + 1
        out = [(None, "Усі (%d)" % len(t.settings))]
        for gid in sorted(used, key=lambda g: t.sgroups.get(g, (0, "%d" % g))[1].lower()):
            out.append((gid, "%s (%d)" % (t.sgroups.get(gid, (0, "група %d" % gid))[1], used[gid])))
        out.append(("save", "Зберегти всі в файл"))
        out.append(("restore", "Відновити з файлу…"))
        return out

    def items(self):
        t = self.t
        ids = sorted(t.settings)
        if self.group is not None:
            ids = [i for i in ids if t.smeta.get(i, {}).get("group") == self.group]
        if self.filter:
            f = self.filter.lower()
            ids = [i for i in ids if f in str(i) or f in t.smeta.get(i, {}).get("name", "").lower()]
        return ids

    def value_str(self, sid):
        v = self.t.settings.get(sid, "")
        m = self.t.smeta.get(sid, {})
        if isinstance(v, float):
            v = ("%d" % v) if v == int(v) and m.get("type") != 6 else ("%g" % v)
        if m.get("type") == 8:
            v = "••••"
        return "%s %s" % (v, m.get("unit", "")) if m.get("unit") else str(v)

    def save(self):
        t = self.t
        d = os.path.join(GCODE_DIR, "settings")
        os.makedirs(d, exist_ok=True)
        name = re.sub(r"[^\w.-]+", "_", t.prof["name"]) + time.strftime("-%Y%m%d-%H%M.txt")
        path = os.path.join(d, name)
        with open(path, "w", encoding="utf-8") as f:
            f.write("; grblHAL settings: %s, %s\n" % (t.prof["name"], time.strftime("%Y-%m-%d %H:%M")))
            for sid in sorted(t.settings):
                if t.smeta.get(sid, {}).get("type") == 8:      # passwords are not saved
                    continue
                m = t.smeta.get(sid, {})
                v = t.settings[sid]
                v = ("%d" % v if v == int(v) else "%g" % v) if isinstance(v, float) else v
                f.write("$%d=%s%s\n" % (sid, v, ("   ; " + m["name"]) if m.get("name") else ""))
        return path

    def key(self, k, hat=False, ch=""):
        t = self.t
        if self.edit is not None:                       # typing a new value
            if k in (pygame.K_RETURN, pygame.K_KP_ENTER):
                val = self.edit.strip()
                self.edit = None
                if val:
                    t.send("$%d=%s" % (self.sid, val))
                    t.send("$%d" % self.sid, log=False)          # read it back
                    self.msg = "надіслано $%d=%s" % (self.sid, val)
            elif k == pygame.K_ESCAPE:
                self.edit = None
            elif k == pygame.K_BACKSPACE:
                self.edit = self.edit[:-1]
            elif ch and ch.isprintable():
                self.edit += ch
            return None
        if hat and k == pygame.K_3:
            k = pygame.K_ESCAPE
        if self.level == "detail":
            if k in (pygame.K_RETURN, pygame.K_KP_ENTER):
                if t.job and t.job.mode:
                    self.msg = "не під час виконання файлу"
                elif t.smeta.get(self.sid, {}).get("type") == 8:
                    self.msg = "пароль тут не змінюється"
                else:
                    v = t.settings.get(self.sid, "")
                    self.edit = ("%d" % v if v == int(v) else "%g" % v) if isinstance(v, float) else str(v)
            elif k in (pygame.K_UP, pygame.K_DOWN, pygame.K_ESCAPE, pygame.K_LEFT, pygame.K_BACKSPACE):
                self.level, self.msg = "list", ""
            return None
        if self.level == "groups":
            gs = self.groups()
            if k == pygame.K_UP:
                self.gsel = (self.gsel - 1) % len(gs)
            elif k == pygame.K_DOWN:
                self.gsel = (self.gsel + 1) % len(gs)
            elif k in (pygame.K_RETURN, pygame.K_KP_ENTER, pygame.K_RIGHT):
                gid = gs[self.gsel][0]
                if gid == "save":
                    try:
                        self.msg = "збережено: " + self.save().replace(os.path.expanduser("~"), "~")
                    except OSError as e:
                        self.msg = "не збережено: %s" % (e.strerror or e)
                elif gid == "restore":
                    return "restore"
                else:
                    self.group, self.level, self.sel, self.top, self.filter = gid, "list", 0, 0, ""
            elif k == pygame.K_ESCAPE or k in (pygame.K_F1, pygame.K_F5):
                return "close"
            elif ch and ch.isprintable() and ch != " ":
                self.group, self.level, self.sel, self.top, self.filter = None, "list", 0, 0, ch
            return None
        ids = self.items()                                # the list
        if k == pygame.K_UP:
            self.sel = max(0, self.sel - 1)
        elif k == pygame.K_DOWN:
            self.sel = min(max(0, len(ids) - 1), self.sel + 1)
        elif k == pygame.K_PAGEUP:
            self.sel = max(0, self.sel - 8)
        elif k == pygame.K_PAGEDOWN:
            self.sel = min(max(0, len(ids) - 1), self.sel + 8)
        elif k in (pygame.K_RETURN, pygame.K_KP_ENTER, pygame.K_RIGHT) and ids:
            self.sid, self.level, self.msg = ids[self.sel], "detail", ""
            if self.sid not in t.sdescr:
                t.send("$SED=%d" % self.sid, log=False)
        elif k == pygame.K_BACKSPACE and self.filter:
            self.filter, self.sel = self.filter[:-1], 0
        elif k in (pygame.K_ESCAPE, pygame.K_LEFT):
            if self.filter:
                self.filter, self.sel = "", 0
            else:
                self.level = "groups"
        elif ch and ch.isprintable() and ch != " ":
            self.filter, self.sel = self.filter + ch, 0
        return None

    def frame(self, title):
        pygame.draw.rect(screen, (14, 14, 22), (0, 0, 128, 128))
        text(fit(title, f_bold, 124), (2, 0), ACCENT, f_bold)

    def draw(self):
        t = self.t
        lh = f_small.get_linesize()
        if not t.settings:
            self.frame("Налаштування $")
            text("завантаження $$ …" if t.port else "немає зв'язку", (64, 60), DIM, f_small, center=True)
            return
        if self.level == "groups":
            self.frame("Налаштування $ - групи")
            gs = self.groups()
            n = int((118 - 11) // lh)
            top = min(max(0, self.gsel - n + 1), max(0, len(gs) - n))
            top = min(top, self.gsel)
            for i, (gid, name) in enumerate(gs[top:top + n]):
                y = 11 + i * lh
                if top + i == self.gsel:
                    pygame.draw.rect(screen, (70, 60, 15), (1, y, 126, lh))
                text(fit(name, f_small, 122), (4, y), CYAN if gid in ("save", "restore") else FG, f_small)
            text(fit(self.msg or "Enter - відкрити, літери - пошук", f_small, 124), (2, 120), ACCENT if self.msg else DIM, f_small)
            return
        if self.level == "detail":
            sid = self.sid
            m = t.smeta.get(sid, {})
            self.frame("$%d %s" % (sid, m.get("name", "")))
            rows = [("Значення: " + self.value_str(sid), FG)]
            if m.get("min") or m.get("max"):
                rows.append(("Межі: %s … %s" % (m.get("min") or "-", m.get("max") or "-"), DIM))
            v = t.settings.get(sid)
            fmt = [x for x in (m.get("format") or "").split(",")]
            if m.get("type") in (1, 2, 4) and isinstance(v, float):     # bit fields: each bit by name
                names = fmt if m.get("type") != 4 else list("XYZABC")
                for b, nm in enumerate(names):
                    if nm and nm != "N/A":
                        rows.append(("%s %s" % ("■" if int(v) >> b & 1 else "□", nm), GREEN if int(v) >> b & 1 else DIM))
            elif m.get("type") == 3 and isinstance(v, float) and int(v) < len(fmt):
                rows.append(("Вибрано: " + fmt[int(v)], GREEN))
            if m.get("reboot"):
                rows.append(("Потрібен перезапуск плати", ORANGE))
            d = t.sdescr.get(sid)
            rows.append(("…" if d is None else (d or "(без опису)"), (190, 190, 150)))
            y = 11
            for s, c in rows:
                for w in [w for para in s.split("\n") if para.strip() for w in TextPopup.wrap_px(para, 122)]:
                    if y < 108:
                        text(w, (3, y), c, f_small)
                    y += lh
            if self.edit is not None:
                pygame.draw.rect(screen, (40, 40, 10), (0, 108, 128, 10))
                s = "= " + self.edit
                text(fit(s, f_mono, 120), (2, 109), ACCENT, f_mono)
                if int(time.monotonic() * 2) % 2 == 0:
                    pygame.draw.rect(screen, ACCENT, (3 + f_mono.size(s)[0], 109, 1.5, LH - 1))
                text("Enter - записати, Esc - ні", (64, 120), DIM, f_small, center=True)
            else:
                text(fit(self.msg or "Enter - змінити, Esc - назад", f_small, 124), (2, 120),
                     ACCENT if self.msg else DIM, f_small)
            return
        gname = "Усі" if self.group is None else t.sgroups.get(self.group, (0, "група %d" % self.group))[1]
        self.frame("$ " + gname + ("  /" + self.filter if self.filter else ""))
        ids = self.items()
        n = int((118 - 11) // lh)
        self.top = min(max(self.top, self.sel - n + 1), self.sel)
        for i, sid in enumerate(ids[self.top:self.top + n]):
            y = 11 + i * lh
            if self.top + i == self.sel:
                pygame.draw.rect(screen, (70, 60, 15), (1, y, 126, lh))
            val = self.value_str(sid)
            vw = min(60, f_small.size(val)[0])
            name = t.smeta.get(sid, {}).get("name", "")
            text(fit("%d %s" % (sid, name), f_small, 122 - vw - 3), (3, y), FG, f_small)
            text(fit(val, f_small, 60), (126, y), CYAN, f_small, right=True)
        if not ids:
            text("нічого не знайдено", (64, 50), DIM, f_small, center=True)
        text(fit(self.msg or "літери - пошук, Enter - деталі", f_small, 124), (2, 120), ACCENT if self.msg else DIM, f_small)


SCAN_FIELDS = [
    # key, label, choices (None = typed text), default
    ("n", "Позицій на оберт", [4, 6, 8, 12, 16, 18, 24, 30, 36, 48, 60, 72, 90, 120, 180, 360], 24),
    ("rate", "Швидкість столу, кроків/с", [25, 50, 100, 150, 200, 300, 400, 800], 100),
    ("settle", "Заспокоєння після повороту, с", [0, 0.2, 0.5, 1, 2, 3, 5], 0.5),
    ("action", "На кожній позиції", ["пауза", "M0 - чекати Enter", "вихід M64 / M65"], "пауза"),
    ("dwell", "Пауза / імпульс, с", [0.2, 0.5, 1, 2, 3, 5, 10], 1),
    ("out", "Номер виходу P", [0, 1, 2, 3, 4, 5, 6, 7], 0),
    ("tilts", "Кути серво (через кому)", None, ""),
    ("servo_wait", "Пауза після серво, с", [0.5, 1, 2, 3, 5], 2),
    ("heights", "Висоти Y (через кому)", None, ""),
    ("unwind", "Розкрутити стіл після оберту", ["так", "ні"], "так"),
]


def nums(s):
    out = []
    for part in re.split(r"[,; ]+", s or ""):
        try:
            out.append(float(part))
        except ValueError:
            pass
    return out


def scan_gcode(p, steps_per_deg):
    """The scan as G-code: for each height, each servo angle: N positions round the table."""
    n = int(p["n"])
    step = 360.0 / n
    rate = max(1, int(p["rate"]))
    turn = step * steps_per_deg / rate + float(p["settle"])
    tilts = nums(p["tilts"]) or [None]
    heights = nums(p["heights"]) or [None]
    total = n * len(tilts) * len(heights)
    out = ["(pico2w-toy 3D scan: %d x %g deg, S%d, servo %s, Y %s)" % (n, step, rate, p["tilts"] or "-",
                                                                   p["heights"] or "-"), "G21 G90"]
    k = 0
    for y in heights:
        if y is not None:
            out.append("G0 Y%g" % y)
        for tilt in tilts:
            if tilt is not None:
                out += ["M101 Q%g" % tilt, "G4 P%g" % float(p["servo_wait"])]
            for _ in range(n):
                k += 1
                out.append("(position %d / %d)" % (k, total))
                if p["action"].startswith("M0"):
                    out.append("M0")
                elif p["action"].startswith("вихід"):
                    out += ["M64 P%d" % int(p["out"]), "G4 P%g" % float(p["dwell"]), "M65 P%d" % int(p["out"])]
                else:
                    out.append("G4 P%g" % float(p["dwell"]))
                out += ["M104 Q%.4f S%d" % (step, rate), "G4 P%.3f" % turn]
            if p["unwind"] == "так":
                out += ["M104 Q-360 S%d" % rate, "G4 P%.3f" % (360 * steps_per_deg / rate + 0.3)]
    return out, total


class ScanForm:
    """The scan wizard: positions round the table, servo angles, heights -> a G-code file to run."""

    def __init__(self, t):
        self.t = t
        saved = t.prof.get("scan") or {}
        self.p = {k: saved.get(k, d) for k, _, _, d in SCAN_FIELDS}
        if "rate" not in saved:
            self.p["rate"] = int(t.prof.get("table_rate", 100))
        self.sel = 0
        self.top = 0
        self.buttons = ["Створити файл", "Створити й запустити"]

    def rows(self):
        return len(SCAN_FIELDS) + len(self.buttons)

    def key(self, k, hat=False, ch=""):
        if hat and k == pygame.K_3:
            return "close"
        if k == pygame.K_UP:
            self.sel = (self.sel - 1) % self.rows()
        elif k == pygame.K_DOWN:
            self.sel = (self.sel + 1) % self.rows()
        elif k == pygame.K_ESCAPE:
            return "close"
        elif self.sel >= len(SCAN_FIELDS):
            if k in (pygame.K_RETURN, pygame.K_KP_ENTER):
                self.t.prof["scan"] = dict(self.p)
                self.t.save_cfg()
                return "scan-run" if self.sel - len(SCAN_FIELDS) == 1 else "scan-make"
        else:
            key, _, choices, _ = SCAN_FIELDS[self.sel]
            if choices is None:                       # typed: numbers and commas
                if k == pygame.K_BACKSPACE:
                    self.p[key] = self.p[key][:-1]
                elif ch and (ch.isdigit() or ch in ",.- "):
                    self.p[key] += ch
            elif k in (pygame.K_LEFT, pygame.K_RIGHT, pygame.K_RETURN, pygame.K_KP_ENTER):
                cur = self.p[key]
                i = choices.index(cur) if cur in choices else 0
                i = (i + (-1 if k == pygame.K_LEFT else 1)) % len(choices)
                self.p[key] = choices[i]
        return None

    def draw(self):
        t = self.t
        pygame.draw.rect(screen, (14, 14, 22), (0, 0, 128, 128))
        text("Майстер сканування", (2, 0), ACCENT, f_bold)
        lh = f_small.get_linesize() + 0.6
        n = int((104 - 11) // lh)
        self.top = min(max(self.top, self.sel - n + 1), self.sel)
        labels = [(f[1], self.p[f[0]], f[2] is None) for f in SCAN_FIELDS] + [(b, None, False) for b in self.buttons]
        for i in range(self.top, min(len(labels), self.top + n)):
            y = 11 + (i - self.top) * lh
            label, val, typed = labels[i]
            if i == self.sel:
                pygame.draw.rect(screen, (70, 60, 15), (1, y, 126, lh))
            if val is None:
                text(label, (64, y), GREEN, f_bold, center=True)
                continue
            vs = ("%g" % val if isinstance(val, (int, float)) else str(val)) or "—"
            if typed and i == self.sel and int(time.monotonic() * 2) % 2 == 0:
                vs = (str(val) or "") + "▏"
            vw = min(56, f_small.size(vs)[0])
            text(fit(label, f_small, 124 - vw - 4), (3, y), FG, f_small)
            text(fit(vs, f_small, 56), (126, y), CYAN, f_small, right=True)
        lines, total = scan_gcode(self.p, float(t.prof.get("table_steps_per_deg", 8.88889)))
        info = gcodeinfo.analyze(lines)
        text("%d позицій · крок %g° · ≈%s" % (total, 360.0 / int(self.p["n"]), hhmm(info.time_s)),
             (64, 106), ACCENT, f_small, center=True)
        hint = "←→ / Enter - змінити, цифри - ввести" if SCAN_FIELDS[min(self.sel, len(SCAN_FIELDS) - 1)][2] is not None \
            or self.sel >= len(SCAN_FIELDS) else "цифри і коми, Backspace"
        text(hint, (64, 118), DIM, f_small, center=True)


def draw_scanner(t, popup):
    """The 3D scanner's pendant: Y, the rotary table, the servo."""
    screen.fill(BG)
    state = t.status[0] if t.status else "?"
    text("СКАНЕР", (2, 0), ACCENT, f_bold)
    x = 4 + f_bold.size("СКАНЕР")[0] + 4
    stale = time.monotonic() - t.status_t > 1.0
    pygame.draw.circle(screen, RED if stale else ((120, 255, 140) if t.status_n % 2 else (30, 110, 50)), (x, 4.5), 2.5)
    if stale:
        text("немає ?", (x + 5, 0), RED, f_small)
    text(state, (126, 0), STATE_COLORS.get(state.split(":")[0], FG) if t.status else DIM, f_bold, right=True)
    if t.alert:
        draw_alert(t, 9, "⌫ $X  e" if t.alert["kind"] == "alarm" else "e - пояснення")
    else:
        text("робочі", (60, 10), DIM, f_small, right=True)
        text("машинні", (126, 10), DIM, f_small, right=True)
    wpos, mpos = t.positions()
    y = 21
    for ax in t.axes:
        i = "XYZABC".index(ax)
        w = "%9.3f" % wpos[i] if wpos and i < len(wpos) else "      —"
        m = "%9.3f" % mpos[i] if mpos and i < len(mpos) else "      —"
        jog = t.jog and t.jog["axis"] == ax
        text(ax, (2, y), ACCENT if jog else BLUE, f_big)
        text(w, (60, y), FG, f_big, right=True)
        text(m, (126, y + 4), (160, 160, 160), f_mono, right=True)
        y += 15
    tbl, tabs, servo = t.scan_fields()
    text("стіл", (2, y + 3), BLUE, f_small)
    text("%7.2f°" % tbl if tbl is not None else "     —", (78, y), FG, f_big, right=True)
    if tabs is not None:
        text("абс %.1f°" % tabs, (126, y + 4), (160, 160, 160), f_small, right=True)
    y += 15
    text("серво", (2, y + 3), BLUE, f_small)
    text("%7.1f°" % servo if servo is not None else "     —", (78, y), FG, f_big, right=True)
    lo, hi = t.servo_limits()
    if 451 in t.settings:
        text("%g…%g°" % (lo, hi), (126, y + 4), (160, 160, 160), f_small, right=True)
    y += 15
    step = JOG_STEPS[t.step_i]
    pygame.draw.rect(screen, (50, 40, 0), (1, y, 126, 10), border_radius=2)
    text("Y %g мм · стіл %g° · серво %g°" % (step, TABLE_STEPS[t.tbl_i], SERVO_STEPS[t.srv_i]),
         (64, y + 1), ACCENT, f_small, center=True)
    y += 11
    rate = int(t.prof.get("table_rate", 100))
    text("стіл S%d = %.1f°/с" % (rate, rate / float(t.prof.get("table_steps_per_deg", 8.88889))), (2, y), DIM, f_small)
    if t.pins:
        text("входи: " + " ".join(t.pins), (126, y), RED, f_bold, right=True)
    y += 9
    if t.job and t.job.mode:
        frac, mode, tail = job_line(t.job)
        pygame.draw.rect(screen, (40, 40, 40), (2, y, 124, 8))
        pygame.draw.rect(screen, ACCENT if t.job.paused else BLUE, (2, y, 124 * frac, 8))
        text(fit(mode + tail, f_small, 122), (4, y), FG, f_small)
    elif t.note and time.monotonic() < t.note_t:
        text(fit(t.note, f_small, 124), (64, y), ACCENT, f_small, center=True)
    elif t.cmd and t.cmd[-1][0] in ("err", "sys"):
        kind, s = t.cmd[-1]
        text(fit(s, f_small, 124), (64, y), RED if kind == "err" else CYAN, f_small, center=True)
    if lcd.DEVICE == "hat144":
        pages = [["джойст. ↑↓ Y  ←→ стіл  KEY1/2 серво", "натиск - крок Y   KEY3 - СТОП"]]
    else:
        pages = [["↑↓ Y  ←→ стіл  / \\ серво", "ПРОБІЛ - СТОП  F1 довідка  Esc - вихід"],
                 ["+- крок Y  t крок столу  v крок серво", "r / l - крутити  o - стоп столу"],
                 ["y - нуль Y   w - майстер сканування", "F2/F3 подача  F4 100%  Enter - далі (M0)"]]
    for i, h in enumerate(hint_page(pages)):
        text(fit(h, f_small, 126), (64, 128 - (2 - i) * 9), (150, 150, 150), f_small, center=True)
    if popup:
        popup.draw()
    lcd.flip()


HELP = ["Введення + Enter - надіслати рядок", "↑/↓ - історія, PgUp/PgDn - прокрутка",
        "F1 → Профіль - сканер / верстат", "F2 / Tab - сховати / показати повний вивід",
        "F3 / Ctrl+P - порт або мережа, кінець рядка, minicom",
        "F4 / Ctrl+O - файл: запуск, кроки, перегляд, межі, обвід",
        "F5 / Ctrl+G - grbl: ?, скидання, $X, $H, налаштування $",
        "Ctrl+T - пульт: F2/F3 подача, F4 100%, F5 швидкі",
        "Backspace на порожньому рядку в Alarm - $X",
        "? ! ~ на порожньому рядку - одразу (grbl)", "Ctrl+X - скидання, Ctrl+C / D - байт",
        "telnet <IP> [порт] + Enter - профіль через мережу",
        "Esc - очистити рядок, закрити меню", "quit + Enter або F1 → Вихід - вийти",
        "HAT: KEY3 - меню, джойстик - вибір"]


PENDANT_HELP = [
    "# Переміщення",
    "←/→ - X, ↑/↓ - Y, / і \\ (або PgUp / PgDn) - Z. Натиск - крок, утримання - безперервно, відпустили - стоп.",
    "+ / - - крок 0,01 / 0,1 / 1 / 10 / 100 мм (подача під крок).",
    "# Нуль і шпиндель",
    "x / y / z - нуль осі (G10 L20 P0), 0 - усіх.",
    "s - шпиндель: увімкнути - двічі за 2 с, вимкнути - одразу; , / . - оберти.",
    "# Корекції",
    "F2 / F3 - подача -/+10 %, F4 - подача 100 %, F5 - швидкі 100 / 50 / 25 %.",
    "# Інше",
    "ПРОБІЛ або Ctrl+X - АВАРІЙНА ЗУПИНКА (програмна; далі $X).",
    "Backspace - $X, зняти блокування Alarm (і після аварійної зупинки).",
    "e - пояснення помилки / аварії. Esc - назад у термінал (там F1 - меню).",
    "HAT: джойстик - X / Y, KEY1 / KEY2 - Z, натиск - крок, KEY3 - стоп (двічі - вихід).",
]
SCANNER_HELP = [
    "# Рух",
    "↑/↓ - Y (крок + / -, утримання - безперервно).",
    "←/→ - стіл на крок (M104); t / T - крок 1 5 10 15 30 45 90°.",
    "r / l - крутити стіл за / проти год. (M102), o - зупинити (M103).",
    "/ і \\ (або PgUp / PgDn) - серво на крок (M101, у межах $451 / $452); v / V - крок 1 / 5 / 15°.",
    "# Інше",
    "y - нуль Y, 0 - нуль усіх осей.",
    "w - майстер сканування. Enter - продовжити після M0.",
    "F2 / F3 - подача -/+10 %, F4 - 100 %, F5 - швидкі 100 / 50 / 25 %.",
    "ПРОБІЛ або Ctrl+X - АВАРІЙНА ЗУПИНКА (зупиняє і стіл).",
    "Backspace - $X, зняти блокування Alarm.",
    "e - пояснення помилки. Esc - назад у термінал (там F1 - меню).",
    "HAT: джойстик ↑/↓ - Y, ←/→ - стіл, KEY1 / KEY2 - серво, натиск - крок Y, KEY3 - стоп (двічі - вихід).",
]


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
    t.say("sys", "профіль: %s (%s) - F1 → Профіль" % (t.prof["name"], KINDS.get(t.prof["kind"], "")))
    if not t.connect():
        t.say("sys", t.no_link_hint())
    browse = {"dir": t.prof.get("gcode_dir") or GCODE_DIR}

    def ask(prompt, initial, cb):
        """The input line asks for a value (Enter - cb(text), Esc - cancel)."""
        t.ask = {"prompt": prompt, "cb": cb, "saved": t.input}
        t.input = initial

    def net_menu():
        pr = t.prof
        state = ("під'єднано" if t.port.connected else "з'єднання…") if isinstance(t.port, Net) else "немає"
        items = ["Адреса: %s" % (pr.get("host") or "—"), "Порт TCP: %d" % int(pr.get("tcp_port") or 23),
                 "Стан: %s" % state, "Під'єднати", "Від'єднати", "Зв'язок: мережа → USB / UART",
                 "Кінець рядка: %s" % dict(EOLS)[t.eol]]

        def pick(i):
            nonlocal popup
            what = items[i]
            if what.startswith("Адреса"):
                def set_host(v):
                    pr["host"] = v.strip()
                    t.save_cfg()
                    t.connect()
                ask("адреса верстата (IP або ім'я)", pr.get("host") or "", set_host)
                return "close"
            if what.startswith("Порт TCP"):
                def set_port(v):
                    if v.strip().isdigit():
                        pr["tcp_port"] = int(v)
                        t.save_cfg()
                        t.connect()
                ask("порт telnet (grblHAL: 23)", str(pr.get("tcp_port") or 23), set_port)
                return "close"
            if what.startswith("Під'єднати") or what.startswith("Стан"):
                t.fail_msg = ""
                if not t.connect():
                    t.flash("спершу задайте адресу")
                return "close"
            if what.startswith("Від'єднати"):
                t.disconnect()
                t.auto, t.dev = False, None
                t.say("sys", "від'єднано")
                return "close"
            if what.startswith("Зв'язок"):
                t.disconnect()
                pr["link"], t.dev = "serial", None
                t.save_cfg()
                t.connect()
                popup = port_menu()
                return None
            if what.startswith("Кінець"):
                keys = [e for e, _ in EOLS]
                t.eol = keys[(keys.index(t.eol) + 1) % len(keys)]
                t.save_cfg()
                popup = net_menu()
                popup.sel = i
                return None
            return "close"
        return Popup("Мережа: " + pr["name"], items, pick)

    def port_menu():
        if t.prof.get("link") == "tcp":
            return net_menu()
        ports = list_ports()
        items = ["%s  %s" % (os.path.basename(p), port_info(p)) for p in ports]
        items += ["Швидкість: %d" % t.baud, "Кінець рядка: %s" % dict(EOLS)[t.eol],
                  "Відкрити в minicom", "Від'єднати", "Зв'язок: USB / UART → мережа"]

        def pick(i):
            nonlocal popup
            if i < len(ports):
                t.want_dev = ports[i]
                t.dev, t.auto = None, True
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
            if what.startswith("Зв'язок"):
                t.disconnect()
                t.prof["link"], t.dev = "tcp", None
                t.save_cfg()
                t.connect()
                popup = net_menu()
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
            t.dev, t.auto = None, False
            t.say("sys", "від'єднано")
            return "close"
        return Popup("Порт: " + t.prof["name"], items, pick)

    def file_menu():
        items = ["Відкрити файл…", "Майстер сканування…" if t.scanner() else "Редактор фігур…"]
        if t.job:
            items += ["Запустити весь", "Покроково (Enter - рядок)", "Пауза / продовжити", "Стоп (скидання)",
                      "Перегляд траєкторії", "Межі й перевірка", "Обвести межі (G0 на поточній Z)",
                      "Корекції подачі…", "Закрити файл"]

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
            elif what.startswith("Перегляд"):
                popup = PathView(t, t.job)
                return None
            elif what.startswith("Межі"):
                popup = TextPopup("Межі: " + t.job.name, bounds_lines(t, t.job))
                return None
            elif what.startswith("Обвести"):
                popup = confirm_outline()
                return None
            elif what.startswith("Корекції"):
                popup = ov_menu()
                return None
            elif what.startswith("Майстер"):
                popup = ScanForm(t)
                return None
            elif what.startswith("Редактор"):
                popup = editor()
                return None
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
            load_job(full)
            t.prof["gcode_dir"] = path
            t.save_cfg()
            return "close"
        title = path.replace(os.path.expanduser("~"), "~")
        return Popup(fit(title, f_bold, 110), names, pick)

    def load_job(full):
        try:
            t.stop_job(reset=False)
            t.job = Job(full, t.rapids())
            info = t.job.info
            sz = info.size()
            dims = " ".join("%s%.1f" % (c, v) for c, v in zip("XYZ", sz) if v is not None)
            t.say("sys", "файл %s: %d рядків%s ≈%s (F4)" % (t.job.name, len(t.job.lines),
                                                          (", " + dims) if dims else "", hhmm(info.time_s)))
            for w in info.warnings:
                t.say("sys", "  " + w)
            if 130 not in t.settings and t.port and not t.scanner():
                t.ask_settings()                      # the travel ($130..) for the bounds check
        except OSError as e:
            t.say("err", "%s: %s" % (os.path.basename(full), e.strerror or e))

    def confirm_outline():
        info = t.job.info
        if info.lo[0] is None or info.lo[1] is None:
            t.flash("у файлі немає меж X/Y")
            return None
        items = ["Ні", "Так: обвести X %.1f..%.1f  Y %.1f..%.1f" % (info.lo[0], info.hi[0], info.lo[1], info.hi[1])]

        def pick(i):
            if i == 1:
                if t.status and t.status[0] != "Idle":
                    t.flash("лише в стані Idle")
                else:
                    t.outline()
            return "close"
        return Popup("Інструмент над заготовкою?", items, pick)

    def ov_menu():
        items = ["Подача +10%", "Подача -10%", "Подача +1%", "Подача -1%", "Подача 100%",
                 "Швидкі 100%", "Швидкі 50%", "Швидкі 25%"]
        keys = ["feed+10", "feed-10", "feed+1", "feed-1", "feed100", "rapid100", "rapid50", "rapid25"]
        if t.prof.get("spindle", True):
            items += ["Оберти +10%", "Оберти -10%", "Оберти 100%"]
            keys += ["spin+10", "spin-10", "spin100"]

        def pick(i):
            t.override(keys[i])
            return None                                   # stays open: press again
        ov = t.ov or [100, 100, 100]
        return Popup("Корекції F%d R%d S%d" % tuple(ov[:3] + [100] * (3 - len(ov[:3]))), items, pick)

    def profile_menu():
        items = ["%s %s  (%s, %s)" % ("●" if i == t.pi else "○", p["name"], KINDS.get(p["kind"], p["kind"]),
                                       "мережа" if p.get("link") == "tcp" else "USB")
                 for i, p in enumerate(t.profiles)]
        items += ["Назва цього профілю…", "Тип: %s" % KINDS.get(t.prof["kind"]), "Осі: %s" % t.axes,
                  "Новий профіль"]
        n = len(t.profiles)

        def pick(i):
            nonlocal popup
            if i < n:
                t.switch_profile(i)
                browse["dir"] = t.prof.get("gcode_dir") or GCODE_DIR
                return "close"
            what = items[i]
            if what.startswith("Назва"):
                def set_name(v):
                    if v.strip():
                        t.prof["name"] = v.strip()
                        t.save_cfg()
                ask("назва профілю", t.prof["name"], set_name)
                return "close"
            if what.startswith("Тип"):
                t.prof["kind"] = "cnc" if t.scanner() else "scanner"
                t.prof["spindle"] = t.prof["kind"] == "cnc"
                t.save_cfg()
            elif what.startswith("Осі"):
                def set_axes(v):
                    v = "".join(c for c in v.upper() if c in "XYZABC")
                    if v:
                        t.prof["axes"] = t.axes = v
                        t.save_cfg()
                ask("осі пульта (напр. XYZ або Y)", t.axes, set_axes)
                return "close"
            elif what.startswith("Новий"):
                p = json.loads(json.dumps(PROFILES[1]))
                p["name"] = "Профіль %d" % (n + 1)
                t.profiles.append(p)
                t.save_cfg()
                t.switch_profile(n)
                return "close"
            popup = profile_menu()
            popup.sel = i
            return None
        return Popup("Профіль", items, pick, sel=t.pi)

    def grbl_menu():
        items = ["Опитування стану ?: %s" % ("так" if t.poll else "ні"), "Стан у повному виводі: %s" %
                 ("так" if t.status_in_full else "ні"), "? - стан один раз", "Ctrl-X - програмне скидання",
                 "$X - зняти блокування", "$H - хомінг", "$$ - налаштування", "$G - стан парсера",
                 "$I - про плату", "! - пауза", "~ - продовжити", "Налаштування $ з описами…", "Корекції…"]

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
            if items[i].startswith("Налаштування"):
                popup = SettingsView(t)
                return None
            if items[i].startswith("Корекції"):
                popup = ov_menu()
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

    def editor():
        return shapeedit.Editor(sys.modules[__name__], t, t.job.path if t.job else None)

    def main_menu():
        # a sensible order: the machine, the work, then the rest
        items = ["Пульт сканера" if t.scanner() else "Пульт (pendant)",
                 "Майстер сканування…" if t.scanner() else "Редактор фігур…", "Файл G-code…"]
        if t.job:
            items.append("Перегляд траєкторії")
        items += ["Порт…", "grblHAL…", "Налаштування $…", "Корекції…", "Профіль: %s…" % t.prof["name"],
                  "Повний вивід: %s" % ("сховати" if t.show_full else "показати"), "Пояснити помилку / аварію",
                  "Довідка", "Вихід"]

        def pick(i):
            nonlocal popup
            what = items[i]
            if what.startswith("Пульт"):
                t.pendant = True
                t.wco = None
                if t.scanner() and 451 not in t.settings and t.port:
                    t.ask_settings()                  # the servo's limits ($451 / $452)
                return "close"
            if what.startswith("Повний вивід"):
                t.show_full = not t.show_full
                t.scroll = 0
                t.save_cfg()
                return "close"
            if what == "Вихід":
                return "quit"
            popup = {"Редактор": editor, "Майстер": lambda: ScanForm(t), "Файл": file_menu,
                     "Перегляд": lambda: PathView(t, t.job), "Порт": port_menu, "grblHAL": grbl_menu,
                     "Налаштування": lambda: SettingsView(t), "Корекції": ov_menu, "Профіль": profile_menu,
                     "Пояснити": lambda: TextPopup("Помилки й аварії", explain_lines(t)),
                     "Довідка": help_popup}[what.split()[0].rstrip("…:")]()
            return None
        return Popup("Меню", items, pick)

    hat_stop = {"t": 0.0}
    # Z: PgUp / PgDn, or / and \ (the PicoCalc keyboard has no PgUp / PgDn)
    JOG_KEYS = {pygame.K_LEFT: ("X", -1), pygame.K_RIGHT: ("X", 1), pygame.K_UP: ("Y", 1),
                pygame.K_DOWN: ("Y", -1), pygame.K_PAGEUP: ("Z", 1), pygame.K_PAGEDOWN: ("Z", -1),
                pygame.K_SLASH: ("Z", 1), pygame.K_BACKSLASH: ("Z", -1)}

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
        if k in PENDANT_OV:
            if k == pygame.K_F5:
                t.rapid_cycle()
            else:
                t.override(PENDANT_OV[k])
            return None
        if t.scanner():
            return scanner_key(k, ch, hat)
        if k == pygame.K_SPACE:
            t.estop()
        elif k == pygame.K_ESCAPE:
            if t.jog:
                t.jog_stop(t.jog["key"])
            t.pendant = False
        elif k == pygame.K_F1:
            return "help"
        elif k == pygame.K_BACKSPACE:
            t.unlock()
        elif k in JOG_KEYS:
            if not t.jog and JOG_KEYS[k][0] in t.axes:
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
        elif ch in ("e", "E"):
            return "explain"
        elif ch in (",", "<", ".", ">"):
            i = SPINDLE_SPEEDS.index(t.spindle) if t.spindle in SPINDLE_SPEEDS else 5
            i = max(0, i - 1) if ch in (",", "<") else min(len(SPINDLE_SPEEDS) - 1, i + 1)
            t.spindle = SPINDLE_SPEEDS[i]
            t.save_cfg()
            if t.spindle_on():                       # running: the new speed at once
                t.send("S%d" % t.spindle, log=False)
        elif ch == "\x18":                          # Ctrl-X works here too
            t.estop()
        return None

    PENDANT_OV = {pygame.K_F2: "feed-10", pygame.K_F3: "feed+10", pygame.K_F4: "feed100", pygame.K_F5: "rapid"}

    def scanner_key(k, ch, hat):
        """The scanner pendant: Y jog, the table, the servo."""
        if hat:
            if k == pygame.K_3:                          # KEY3: stop; again within 2 s - leave
                if time.monotonic() - hat_stop["t"] < 2.0:
                    t.pendant = False
                    return None
                t.estop()
                hat_stop["t"] = time.monotonic()
                t.flash("KEY3 ще раз - вийти з пульта")
            elif k in (pygame.K_1, pygame.K_2):
                t.servo_move(SERVO_STEPS[t.srv_i] * (1 if k == pygame.K_1 else -1))
            elif k == pygame.K_RETURN:
                t.step_i = (t.step_i + 1) % len(JOG_STEPS)
            elif k in (pygame.K_LEFT, pygame.K_RIGHT):
                t.table_turn(TABLE_STEPS[t.tbl_i] * (1 if k == pygame.K_RIGHT else -1))
            elif k in (pygame.K_UP, pygame.K_DOWN) and not t.jog:
                t.jog_start(k, "Y", 1 if k == pygame.K_UP else -1)
            return None
        if k == pygame.K_SPACE or ch == "\x18":
            t.estop()
        elif k == pygame.K_ESCAPE:
            if t.jog:
                t.jog_stop(t.jog["key"])
            t.pendant = False
        elif k == pygame.K_F1:
            return "help"
        elif k == pygame.K_BACKSPACE:
            t.unlock()
        elif k in (pygame.K_UP, pygame.K_DOWN):
            ax = "Y" if "Y" in t.axes else t.axes[0]
            if not t.jog:
                t.jog_start(k, ax, 1 if k == pygame.K_UP else -1)
        elif k in (pygame.K_LEFT, pygame.K_RIGHT):
            t.table_turn(TABLE_STEPS[t.tbl_i] * (1 if k == pygame.K_RIGHT else -1))
        elif k in (pygame.K_PAGEUP, pygame.K_PAGEDOWN, pygame.K_SLASH, pygame.K_BACKSLASH):
            t.servo_move(SERVO_STEPS[t.srv_i] * (1 if k in (pygame.K_PAGEUP, pygame.K_SLASH) else -1))
        elif k in (pygame.K_RETURN, pygame.K_KP_ENTER):
            if t.status and t.status[0].startswith("Hold"):
                t.send("~", log=False, realtime=True)   # M0 / feed hold: go on
                t.say("sys", "▶ далі")
        elif ch in ("+", "="):
            t.step_i = min(len(JOG_STEPS) - 1, t.step_i + 1)
        elif ch in ("-", "_"):
            t.step_i = max(0, t.step_i - 1)
        elif ch == "t":
            t.tbl_i = (t.tbl_i + 1) % len(TABLE_STEPS)
        elif ch == "T":
            t.tbl_i = (t.tbl_i - 1) % len(TABLE_STEPS)
        elif ch in ("v", "V"):
            t.srv_i = (t.srv_i + (1 if ch == "v" else -1)) % len(SERVO_STEPS)
        elif ch in ("r", "R"):
            t.table_spin(False)
        elif ch in ("l", "L"):
            t.table_spin(True)
        elif ch in ("o", "O"):
            t.table_stop()
        elif ch in ("y", "Y"):
            t.set_zero(["Y"])
        elif ch == "0":
            t.set_zero(list(t.axes))
        elif ch in ("w", "W"):
            return "scan"
        elif ch in ("e", "E"):
            return "explain"
        return None

    def popup_result(r):
        """What a window's key handler asked for."""
        nonlocal popup, running
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
        elif r == "restore":
            browse["dir"] = os.path.join(GCODE_DIR, "settings")
            popup = browser()
            t.flash("файл налаштувань: потім F4 → Запустити весь")
        elif isinstance(r, tuple) and r[0] == "load":       # the shape editor saved its G-code
            popup = None
            load_job(r[1])
            t.say("sys", "креслення %s.svg, G-code .nc - F4: перегляд, межі, запуск" %
                  r[1][:-3].replace(os.path.expanduser("~"), "~"))
        elif r in ("scan-make", "scan-run"):
            lines, total = scan_gcode(popup.p, float(t.prof.get("table_steps_per_deg", 8.88889)))
            d = os.path.join(GCODE_DIR, "scan")
            os.makedirs(d, exist_ok=True)
            p = popup.p
            name = "scan-%dx%s%s.nc" % (int(p["n"]), ("-s" + "_".join("%g" % v for v in nums(p["tilts"])))
                                        if nums(p["tilts"]) else "", ("-y" + "_".join("%g" % v for v in nums(p["heights"])))
                                        if nums(p["heights"]) else "")
            path = os.path.join(d, name)
            with open(path, "w", encoding="utf-8") as f:
                f.write("\n".join(lines) + "\n")
            popup = None
            load_job(path)
            if r == "scan-run" and t.job:
                t.run_all()

    running = True
    shown_key = None
    while running:
        for ev in pygame.event.get():
            if ev.type == pygame.QUIT:
                running = False
                break
            if ev.type == pygame.KEYUP and popup and hasattr(popup, "keyup"):
                popup.keyup(ev.key)                # the shape editor: a held arrow let go
                continue
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
                if r == "help":
                    popup = TextPopup("Пульт сканера" if t.scanner() else "Пульт",
                                      SCANNER_HELP if t.scanner() else PENDANT_HELP)
                elif r == "explain":
                    popup = TextPopup("Помилки й аварії", explain_lines(t))
                elif r == "scan":
                    popup = ScanForm(t)
                continue
            if popup:
                popup.mod = getattr(ev, "mod", 0)
                popup_result(popup.key(k, hat, ch))
                continue
            if t.ask:                              # the input line asks for a value
                if k in (pygame.K_RETURN, pygame.K_KP_ENTER):
                    a, t.ask = t.ask, None
                    v, t.input = t.input, a["saved"]
                    a["cb"](v)
                elif k == pygame.K_ESCAPE:
                    t.input, t.ask = t.ask["saved"], None
                elif k == pygame.K_BACKSPACE:
                    t.input = t.input[:-1]
                elif ch and ch.isprintable():
                    t.input += ch
                continue
            # Ctrl+P / Ctrl+O / Ctrl+G - the same menus as F3 / F4 / F5 (keyboards without them)
            menu_key = {"\x10": pygame.K_F3, "\x0f": pygame.K_F4, "\x07": pygame.K_F5}.get(ch)
            if menu_key:
                k, ch = menu_key, ""
            if ch == "\x05":                       # Ctrl+E: explain the last error / alarm
                popup = TextPopup("Помилки й аварії", explain_lines(t))
                continue
            if ch == "\x14":                       # Ctrl+T: the pendant
                t.pendant, t.wco = True, None
                if t.scanner() and 451 not in t.settings and t.port:
                    t.ask_settings()                  # the servo's limits ($451 / $452)
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
                m = re.match(r"^\s*telnet\s+([\w.-]+)(?:[\s:]+(\d+))?\s*$", line, re.I)
                if line.strip().lower() == "quit":    # leave (not sent to the device)
                    running = False
                    t.input = ""
                elif m:                               # telnet <host> [port]: this profile goes over the network
                    t.prof.update(link="tcp", host=m.group(1), tcp_port=int(m.group(2) or 23))
                    t.fail_msg = ""
                    t.save_cfg()
                    t.say("sys", "з'єднуюсь з %s:%d…" % (m.group(1), int(m.group(2) or 23)))
                    t.connect()
                    t.input = ""
                elif not line and t.job and t.job.mode == "step":
                    t.step()
                elif not line and t.job and t.job.mode == "run" and t.status and t.status[0].startswith("Hold"):
                    t.send("~", log=False, realtime=True)     # M0 / feed hold: go on
                    t.job.paused = False
                    t.say("sys", "▶ далі")
                elif line:
                    if t.send(line):
                        if not t.hist or t.hist[-1] != line:
                            t.hist.append(line)
                        t.h = len(t.hist)
                        t.input = ""
                        t.scroll = 0

            elif k == pygame.K_BACKSPACE:
                if not t.input and t.status and t.status[0].startswith("Alarm"):
                    t.unlock()                        # an empty line in Alarm: Backspace = $X
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
        if popup and hasattr(popup, "tick"):
            popup.tick()
        # redraw at most ~12 times a second, and only when something changed
        key = (len(t.cmd), t.cmd[-1] if t.cmd else None, len(t.full), t.full[-1] if t.full else None, t.input,
               t.status, t.scroll, t.show_full, t.poll, popup and (getattr(popup, "sel", None), id(popup)), t.port is not None,
               t.job and (t.job.pos, t.job.mode, t.job.paused), t.note, int(time.monotonic() * 2),
               t.pendant, t.step_i, t.spindle, t.jog and t.jog["axis"], str(t.wco),
               t.pendant and (t.status_n, time.monotonic() - t.status_t > 1.0), str(t.alert),
               popup and getattr(popup, "top", 0), t.ov and tuple(t.ov), t.pins, t.ask and t.ask["prompt"],
               len(t.settings), len(t.smeta), len(t.sdescr), t.tbl_i, t.srv_i,
               popup and (popup.state() if hasattr(popup, "state") else
                          str([getattr(popup, a, None) for a in ("level", "edit", "filter", "scale", "cx", "cy",
                                                                 "view", "msg", "gsel", "p")])))
        if key != shown_key:
            if t.pendant:
                (draw_scanner if t.scanner() else draw_pendant)(t, popup)
            else:
                draw(t, popup)
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
