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
            hint = "Enter - наст. рядок" if job and job.mode == "step" else "F1 довідка  ^P порт  ^O файл  ^G grbl"
        s = "> " + t.input[-(COLS - 3):]
        text(s, (2, in_y), FG, f_mono)
        if int(time.monotonic() * 2) % 2 == 0:
            pygame.draw.rect(screen, ACCENT, (2 + len(s) * CW, in_y, max(1, CW / 3), LH - 1))
        if hint:
            text(hint, (126, in_y + 1), (100, 100, 100), f_small, right=True)
    if popup:
        popup.draw()
    lcd.flip()


class Popup:
    """A list to choose from: UP / DOWN, Enter, Esc."""

    def __init__(self, title, items, on_pick, sel=0):
        self.title, self.items, self.on_pick, self.sel, self.top = title, items, on_pick, sel, 0

    def key(self, k):
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
        "Esc - очистити рядок / вихід"]


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

    running = True
    shown_key = None
    while running:
        for ev in pygame.event.get():
            if ev.type == pygame.QUIT:
                running = False
                break
            if ev.type != pygame.KEYDOWN:
                continue
            shown_key = None
            k = ev.key
            hat = getattr(ev, "hat", False)
            ch = getattr(ev, "unicode", "") if not hat else ""
            if popup:
                r = popup.key(k)
                if r == "close":
                    popup = None
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
            if k == pygame.K_F1:
                popup = help_popup()
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
            elif k == pygame.K_ESCAPE or (hat and k == pygame.K_3):
                if t.input:
                    t.input = ""
                else:
                    running = False
            elif k in (pygame.K_RETURN, pygame.K_KP_ENTER):
                line = t.input
                if not line and t.job and t.job.mode == "step":
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
               t.job and (t.job.pos, t.job.mode, t.job.paused), t.note, int(time.monotonic() * 2))
        if key != shown_key:
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
