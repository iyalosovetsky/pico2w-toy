"""Signal generator board (tools/siggen: a Pimoroni Tiny 2350 running rp2350.py as its main.py),
driven over the UART (/dev/serial0) or USB (/dev/ttyACM*) - whichever answers.

Five modes (the first row): generator, voltmeter (the board's ADC inputs, GP26 = J703.7 in
the PicoCalc; min / max and a 10 s graph) and oscilloscope (GP26: 256 points per sweep, time base
100 us .. 50 ms per division, rising-edge trigger, frequency and peak-to-peak measured; Enter
pauses) and logic analyzer (the six J703 lines, 512 samples per sweep, 5 us .. 20 ms per
division, rising-edge trigger on a chosen line, its frequency and duty; Enter pauses) and
protocol decoder (UART / I2C / SPI on the J703 lines, decoded by the board; Enter captures once,
"test" makes the board send its own traffic).
The generator keeps running in all of them, so its output can go to the inputs.
UP / DOWN - row (mode, shape, frequency, duty, signal / mode, input), LEFT / RIGHT - change (held: repeats),
+ / - (KEY1 / KEY2 on the HAT) - fine step, PRESS / Enter - signal on / off,
keyboard digits (and k / M for the frequency) + Enter - exact value, KEY3 / Esc - exit.
Every change is sent at once; the screen shows what the board answered.
"""
import math
import os
import select
import sys
import termios
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import pygame  # noqa: E402
import lcd  # noqa: E402

PORTS = os.environ.get("SIGGEN_PORT", "").split() or ["/dev/serial0", "/dev/ttyACM0", "/dev/ttyACM1"]
FMIN, FMAX = 1, 1000000           # widest range; the board answers its limit for the shape (fmax)
SHAPES = ["square", "sine", "triangle", "saw"]
SHAPE_NAMES = {"square": "меандр", "sine": "синус", "triangle": "трикутник", "saw": "пила"}
SERIES = [1, 1.2, 1.5, 2, 2.5, 3, 4, 5, 6, 8]  # coarse frequency steps in a decade
LED_MAX = 80

BG, FG, DIM = (0, 0, 0), (225, 225, 225), (110, 110, 110)
ACCENT, RED, GREEN = (255, 200, 0), (230, 60, 50), (90, 200, 90)
FONT_DIR = "/usr/share/fonts/truetype/dejavu/"


# ---------------------------------------------------------------- the UART link

class Link:
    def __init__(self, path):
        self.fd = os.open(path, os.O_RDWR | os.O_NOCTTY | os.O_NONBLOCK)
        attr = termios.tcgetattr(self.fd)
        attr[0] = attr[1] = attr[3] = 0                       # raw: no iflag / oflag / lflag
        attr[2] = termios.CS8 | termios.CREAD | termios.CLOCAL
        attr[4] = attr[5] = termios.B115200
        termios.tcsetattr(self.fd, termios.TCSANOW, attr)
        termios.tcflush(self.fd, termios.TCIOFLUSH)
        self.buf = b""

    def ask(self, line, timeout=0.6):
        """Send a command, return the answer line or None."""
        try:
            while os.read(self.fd, 4096):  # drop anything stale
                pass
        except BlockingIOError:
            pass
        self.buf = b""
        os.write(self.fd, (line + "\n").encode())
        end = time.monotonic() + timeout
        while b"\n" not in self.buf:
            left = end - time.monotonic()
            if left <= 0 or not select.select([self.fd], [], [], left)[0]:
                return None
            try:
                self.buf += os.read(self.fd, 4096)
            except BlockingIOError:
                pass
        return self.buf.split(b"\n", 1)[0].decode("utf-8", "replace").strip()


def parse(reply):
    """'ok shape=sine freq=1000 duty=50 out=on fmax=1000' -> dict, or None."""
    if not reply or not reply.startswith("ok "):
        return None
    kv = dict(w.split("=", 1) for w in reply[3:].split() if "=" in w)
    try:
        shape = kv.get("shape", "square")  # an older main.py has square only
        return {"shape": shape, "freq": int(kv["freq"]), "duty": float(kv["duty"]),
                "on": kv.get("out") == "on", "fmax": int(kv.get("fmax", FMAX)),
                "fmin": int(kv.get("fmin", 2 if shape == "square" else 1)),
                "board": kv.get("board", "").upper()}
    except (KeyError, ValueError):
        return None


# ---------------------------------------------------------------- values

def freq_step(f, up):
    """Next / previous value of the 1-1.2-1.5-2-2.5-3-4-5-6-8 series."""
    values = [round(s * 10 ** e) for e in range(0, 7) for s in SERIES]
    values = [v for v in values if FMIN <= v <= FMAX] + [FMAX]
    if up:
        return next((v for v in values if v > f), FMAX)
    return next((v for v in reversed(values) if v < f), FMIN)


def freq_text(f):
    if f >= 1000000:
        return "%g МГц" % (f / 1000000)
    if f >= 1000:
        return "%g кГц" % round(f / 1000, 3)
    return "%d Гц" % f


def number(s):
    s = s.strip().lower()
    mult = {"k": 1000, "m": 1000000}.get(s[-1:], 1)
    return float(s[:-1] if mult > 1 else s) * mult


def led_color(st):
    """The colour the board's LED shows (main.py: hue by log frequency, value by duty)."""
    if not st["on"]:
        return (0, 0, 0)
    pos = math.log10(max(st["freq"], 2) / 2) / math.log10(FMAX / 2)
    h = (270 * pos % 360) / 60
    duty = st["duty"] if st["shape"] == "square" else 50
    v = 255 * max(duty, 8) / 100  # brighter than the LED itself, so it shows on the LCD
    i, f = int(h), h - int(h)
    p, q, t = 0, v * (1 - f), v * f
    return tuple(int(c) for c in [(v, t, p), (q, v, p), (p, v, t), (p, q, v), (t, p, v), (v, p, q)][i % 6])


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
f_small = font("DejaVuSans.ttf", 12 if BIG else 7)
f_label = font("DejaVuSans.ttf", 15 if BIG else 8)
f_value = font("DejaVuSans-Bold.ttf", 24 if BIG else 11)
f_title = font("DejaVuSans-Bold.ttf", 16 if BIG else 8)
f_big = font("DejaVuSans-Bold.ttf", 40 if BIG else 18)

ROWS = ["Режим", "Форма", "Частота", "Скважність", "Сигнал"]
R_MODE, R_SHAPE, R_FREQ, R_DUTY, R_OUT = range(5)
VROWS = ["Режим", "Вхід"]
R_INPUT = 1
ROW_H = 14
ADC_INPUTS = [("gp26", "J703.7"), ("gp27", "GP27"), ("gp28", "GP28"), ("gp29", "GP29")]
VMAX = 3.3
HISTORY = 100  # samples in the graph (0.1 s apart)
SROWS = ["Режим", "Час/под", "Синхр."]
R_TIME, R_TRIG = 1, 2
TIMEBASES = [100e-6, 200e-6, 500e-6, 1e-3, 2e-3, 5e-3, 10e-3, 20e-3, 50e-3]  # s per division
SCOPE_N, SCOPE_DIVS = 256, 10
MODES = ["gen", "volt", "scope", "logic", "decode"]
DROWS = ["Режим", "Протокол", "Параметр", "Джерело"]
R_PROTO, R_PARAM, R_SOURCE = 1, 2, 3
PROTOS = ["uart", "i2c", "spi"]
BAUDS = [9600, 19200, 38400, 57600, 115200, 230400, 300, 1200, 2400, 4800]
PROTO_PINS = {"uart": "RX - J703.4", "i2c": "SDA - J703.4, SCL - J703.5",
              "spi": "SCK .6  MOSI .3  MISO .4  CS .5"}
LTIMEBASES = [5e-6, 10e-6, 20e-6, 50e-6, 100e-6, 200e-6, 500e-6, 1e-3, 2e-3, 5e-3, 10e-3, 20e-3]
LOGIC_N = 512
LOGIC_CH = ["2", "3", "4", "5", "6", "7"]   # J703 pins: GP6 GP3 GP4 GP5 GP2 GP26
HAT = lcd.DEVICE == "hat144"


def text(s, pos, color, f, right=False, center=False):
    img = f.render(s, True, color)
    x, y = pos
    if right:
        x -= img.get_width()
    elif center:
        x -= img.get_width() / 2
    screen.blit(img, (x, y))


def draw(st, row, typing, note, note_color):
    screen.fill(BG)
    title = "ГЕНЕРАТОР " + (st["board"] if st else "")
    text(title.strip(), (64, 2), ACCENT, f_title, center=True)
    if st is None:
        text("плата не відповідає", (64, 40), RED, f_label, center=True)
        text("UART /dev/serial0 або USB", (64, 56), DIM, f_small, center=True)
        text("перевірте дроти TX/RX", (64, 68), DIM, f_small, center=True)
        text(("KEY3" if HAT else "Esc") + " - назад", (64, 114), DIM, f_small, center=True)
        lcd.flip()
        return
    square = st["shape"] == "square"
    values = ["генератор", SHAPE_NAMES.get(st["shape"], st["shape"]), freq_text(st["freq"]),
              "%g %%" % st["duty"] if square else "—", "УВІМК" if st["on"] else "ВИМК"]
    for i, name in enumerate(ROWS):
        y = 13 + i * ROW_H
        sel = i == row
        if sel:
            pygame.draw.rect(screen, ACCENT, (2, y - 1, 124, ROW_H - 1), border_radius=3)
        text(name, (6, y + 2), BG if sel else DIM, f_label)
        value = typing + "_" if sel and typing is not None else values[i]
        if sel:
            color = BG
        elif i == R_OUT:
            color = GREEN if st["on"] else RED
        else:
            color = DIM if i == R_DUTY and not square else FG
        text(value, (122, y), color, f_value, right=True)
    # the wave: three periods of the shape, in the LED's colour
    color = led_color(st)
    wave = color if st["on"] else DIM
    x0, x1, lo, hi = 22, 124, 98, 86
    period = (x1 - x0) / 3
    if not st["on"]:
        pts = [(x0, lo), (x1, lo)]
    elif square:
        pts = [(x0, lo)]
        for k in range(3):
            a = x0 + k * period
            b = a + period * st["duty"] / 100
            pts += [(a, lo), (a, hi), (b, hi), (b, lo)] if st["duty"] > 0 else [(a, lo)]
        pts.append((x1, lo))
    else:
        level = {"sine": lambda t: 0.5 + 0.5 * math.sin(2 * math.pi * t),
                 "triangle": lambda t: 2 * t if t < 0.5 else 2 - 2 * t,
                 "saw": lambda t: t}.get(st["shape"], lambda t: 0.5)
        pts = []
        for i in range(61):
            t = i / 60 * 3
            v = level(t % 1) if not (st["shape"] == "saw" and i and t % 1 == 0) else 1
            pts.append((x0 + (x1 - x0) * i / 60, lo - (lo - hi) * v))
            if st["shape"] == "saw" and i and t % 1 == 0 and i < 60:
                pts.append((x0 + (x1 - x0) * i / 60, lo))  # the drop of the saw
    pygame.draw.lines(screen, wave, False, pts, 2 if BIG else 1)
    pygame.draw.circle(screen, color, (10, 92), 5)        # the LED
    pygame.draw.circle(screen, DIM, (10, 92), 5, 1)
    if note:
        text(note, (64, 99), note_color, f_small, center=True)
    if HAT:
        hints = ["←/→ змінити, KEY1/2 точно", "натиск - сигнал, KEY3 - назад"]
    else:
        hints = ["←/→ змінити, +/- точно, цифри", "Enter - сигнал, Esc - назад"]
    text(hints[0], (64, 106), DIM, f_small, center=True)
    text(hints[1], (64, 116), DIM, f_small, center=True)
    lcd.flip()


def draw_volt(st, row, vm, note, note_color):
    """Voltmeter: the selected ADC input, min / max, a graph of the last 10 s."""
    screen.fill(BG)
    text("ВОЛЬТМЕТР " + st["board"], (64, 2), ACCENT, f_title, center=True)
    key, label = ADC_INPUTS[vm["input"]]
    for i, (name, value) in enumerate(zip(VROWS, ["вольтметр", label if label == key.upper() else "%s (%s)" % (label, key.upper())])):
        y = 13 + i * ROW_H
        sel = i == row
        if sel:
            pygame.draw.rect(screen, ACCENT, (2, y - 1, 124, ROW_H - 1), border_radius=3)
        text(name, (6, y + 2), BG if sel else DIM, f_label)
        text(value, (122, y), BG if sel else FG, f_value, right=True)
    v = vm["value"]
    if v is None:
        text("—", (64, 44), DIM, f_big, center=True)
    else:
        text("%.3f В" % v, (64, 42), GREEN, f_big, center=True)
    if vm["min"] is not None:
        text("мін %.3f   макс %.3f" % (vm["min"], vm["max"]), (64, 64), FG, f_small, center=True)
    # graph, 0 .. 3.3 V
    gx0, gx1, gy0, gy1 = 4, 124, 74, 102
    pygame.draw.rect(screen, (40, 40, 40), (gx0, gy0, gx1 - gx0, gy1 - gy0), 1)
    for level in (1, 2, 3):
        y = gy1 - (gy1 - gy0) * level / VMAX
        pygame.draw.line(screen, (35, 35, 35), (gx0 + 1, y), (gx1 - 2, y))
        text("%d" % level, (gx0 + 2, y - 4), (70, 70, 70), f_small)
    hist = vm["history"]
    if len(hist) > 1:
        step = (gx1 - gx0 - 2) / (HISTORY - 1)
        x_start = gx1 - 1 - step * (len(hist) - 1)
        pts = [(x_start + i * step, gy1 - 1 - (gy1 - gy0 - 2) * min(max(h, 0), VMAX) / VMAX)
               for i, h in enumerate(hist)]
        pygame.draw.lines(screen, GREEN, False, pts, 2 if BIG else 1)
    if note:
        text(note, (64, 64), note_color, f_small, center=True)
    if HAT:
        hints = ["←/→ змінити, натиск - скинути", "мін / макс, KEY3 - назад"]
    else:
        hints = ["←/→ змінити, Enter - скинути", "мін / макс, Esc - назад"]
    text(hints[0], (64, 106), DIM, f_small, center=True)
    text(hints[1], (64, 116), DIM, f_small, center=True)
    lcd.flip()


def time_text(t):
    return ("%g мкс" % round(t * 1e6, 3)) if t < 1e-3 else ("%g мс" % round(t * 1e3, 3))


def parse_scope(reply):
    """'ok scope rate=.. n=256 trig=1 over=0 data=<hex>' -> (rate, trig, [0..255, ...]) or None."""
    if not reply or not reply.startswith("ok scope"):
        return None
    try:
        kv = dict(w.split("=", 1) for w in reply.split()[2:])
        return float(kv["rate"]), kv.get("trig") == "1", list(bytes.fromhex(kv["data"]))
    except (KeyError, ValueError):
        return None


def measure_wave(data, rate):
    """(frequency or None, peak-to-peak volts) from a sweep: rising crossings of the middle."""
    lo, hi = min(data), max(data)
    vpp = (hi - lo) * VMAX / 255
    if hi - lo < 20:
        return None, vpp
    # smoothed over 3 points, with a wide hysteresis: the PWM steps of the DDS shapes at fast
    # sweeps must not count as extra crossings
    smooth = [(data[max(i - 1, 0)] + data[i] + data[min(i + 1, len(data) - 1)]) / 3 for i in range(len(data))]
    mid, hyst = (lo + hi) / 2, (hi - lo) / 4
    armed, rises = False, []
    for i, v in enumerate(smooth):
        if v < mid - hyst:
            armed = True
        elif armed and v > mid + hyst:
            rises.append(i)
            armed = False
    if len(rises) < 2:
        return None, vpp
    return (len(rises) - 1) * rate / (rises[-1] - rises[0]), vpp


def draw_scope(st, row, sc, note, note_color):
    screen.fill(BG)
    text("ОСЦИЛОГРАФ " + st["board"], (64, 2), ACCENT, f_title, center=True)
    tdiv = TIMEBASES[sc["tb"]]
    values = ["осцилограф", time_text(tdiv), "%.1f В ↑" % sc["level"]]
    for i, (name, value) in enumerate(zip(SROWS, values)):
        y = 13 + i * ROW_H
        sel = i == row
        if sel:
            pygame.draw.rect(screen, ACCENT, (2, y - 1, 124, ROW_H - 1), border_radius=3)
        text(name, (6, y + 2), BG if sel else DIM, f_label)
        text(value, (122, y), BG if sel else FG, f_value, right=True)
    gx0, gx1, gy0, gy1 = 2, 126, 55, 103
    w, h = gx1 - gx0, gy1 - gy0
    pygame.draw.rect(screen, (60, 60, 60), (gx0, gy0, w, h), 1)
    for i in range(1, SCOPE_DIVS):
        x = gx0 + w * i / SCOPE_DIVS
        pygame.draw.line(screen, (32, 32, 32), (x, gy0 + 1), (x, gy1 - 2))
    for v in (1.1, 2.2):
        y = gy1 - h * v / VMAX
        pygame.draw.line(screen, (32, 32, 32), (gx0 + 1, y), (gx1 - 2, y))
    ty = gy1 - h * sc["level"] / VMAX
    for x in range(gx0 + 2, gx1 - 2, 4):  # the trigger level, dashed
        pygame.draw.line(screen, (90, 70, 0), (x, ty), (x + 1.5, ty))
    data = sc["data"]
    if data:
        n = len(data)
        pts = [(gx0 + 1 + (w - 2) * i / (n - 1), gy1 - 1 - (h - 2) * v / 255) for i, v in enumerate(data)]
        pygame.draw.lines(screen, GREEN, False, pts, 2 if BIG else 1)
        f, vpp = measure_wave(data, sc["rate"])
        ftxt = freq_text(round(f)) if f and f >= 1 else "—"
        info = "f %s   розмах %.2f В" % (ftxt, vpp)
        if sc["paused"]:
            info += "   пауза"
        elif not sc["trig"]:
            info += "   без синхр."
        text(info, (64, 105), FG, f_small, center=True)
    elif note:
        text(note, (64, 105), note_color, f_small, center=True)
    hint = "←/→, натиск - пауза, KEY3 - назад" if HAT else "←/→ змінити, Enter - пауза, Esc - назад"
    text(hint, (64, 116), DIM, f_small, center=True)
    lcd.flip()


def parse_logic(reply):
    """'ok logic rate=.. n=512 trig=1 data=<hex>' -> (rate, trig, bytes) or None."""
    if not reply or not reply.startswith("ok logic"):
        return None
    try:
        kv = dict(w.split("=", 1) for w in reply.split()[2:])
        return float(kv["rate"]), kv.get("trig") == "1", bytes.fromhex(kv["data"])
    except (KeyError, ValueError):
        return None


def measure_bits(bits, rate):
    """(frequency or None, duty %) of a 0/1 list: from its rising edges."""
    rises = [i for i in range(1, len(bits)) if bits[i] and not bits[i - 1]]
    duty = 100 * sum(bits) / len(bits)
    if len(rises) < 2:
        return None, duty
    a, b = rises[0], rises[-1]
    return (len(rises) - 1) * rate / (b - a), 100 * sum(bits[a:b]) / (b - a)


def draw_logic(st, row, la, note, note_color):
    screen.fill(BG)
    text("АНАЛІЗАТОР " + st["board"], (64, 2), ACCENT, f_title, center=True)
    values = ["аналізатор", time_text(LTIMEBASES[la["tb"]]), "J703.%s ↑" % LOGIC_CH[la["ch"]]]
    for i, (name, value) in enumerate(zip(SROWS, values)):
        y = 13 + i * ROW_H
        sel = i == row
        if sel:
            pygame.draw.rect(screen, ACCENT, (2, y - 1, 124, ROW_H - 1), border_radius=3)
        text(name, (6, y + 2), BG if sel else DIM, f_label)
        text(value, (122, y), BG if sel else FG, f_value, right=True)
    gx0, gx1, gy0, gy1 = 10, 126, 55, 103
    w = gx1 - gx0
    lane = (gy1 - gy0) / len(LOGIC_CH)
    pygame.draw.rect(screen, (60, 60, 60), (gx0, gy0, w, gy1 - gy0), 1)
    for i in range(1, SCOPE_DIVS):
        x = gx0 + w * i / SCOPE_DIVS
        pygame.draw.line(screen, (32, 32, 32), (x, gy0 + 1), (x, gy1 - 2))
    data = la["data"]
    for c, name in enumerate(LOGIC_CH):
        top = gy0 + c * lane
        color = ACCENT if c == la["ch"] else GREEN
        text(name, (2, top + lane / 2 - 4), color, f_small)
        if not data:
            continue
        hi_y, lo_y = top + 1.5, top + lane - 1.5
        n = len(data)
        xs = lambda i: gx0 + 1 + (w - 2) * i / (n - 1)
        prev = data[0] >> c & 1
        pts = [(xs(0), hi_y if prev else lo_y)]
        for i in range(1, n):
            v = data[i] >> c & 1
            if v != prev:
                pts += [(xs(i), hi_y if prev else lo_y), (xs(i), hi_y if v else lo_y)]
                prev = v
        pts.append((xs(n - 1), hi_y if prev else lo_y))
        pygame.draw.lines(screen, color, False, pts, 1)
    if data:
        f, duty = measure_bits([v >> la["ch"] & 1 for v in data], la["rate"])
        info = "J703.%s: f %s   %.0f %%" % (LOGIC_CH[la["ch"]], freq_text(round(f)) if f and f >= 1 else "—", duty)
        if la["paused"]:
            info += "   пауза"
        elif not la["trig"]:
            info += "   без синхр."
        text(info, (64, 105), FG, f_small, center=True)
    elif note:
        text(note, (64, 105), note_color, f_small, center=True)
    hint = "←/→, натиск - пауза, KEY3 - назад" if HAT else "←/→ змінити, Enter - пауза, Esc - назад"
    text(hint, (64, 116), DIM, f_small, center=True)
    lcd.flip()


def wrap_words(words, f, width):
    lines, cur = [], ""
    for w in words:
        t = (cur + " " + w).strip()
        if f.size(t)[0] > width and cur:
            lines.append(cur)
            cur = w
        else:
            cur = t
    if cur:
        lines.append(cur)
    return lines


def decode_lines(proto, tokens):
    """The board's tokens as screen lines."""
    if tokens == ["none"]:
        return ["нічого: за 2 с не було трафіку"]
    if proto == "uart":
        text_ = "".join(chr(int(t[:2], 16)) if 32 <= int(t[:2], 16) < 127 else "." for t in tokens)
        return wrap_words(tokens, f_small, 120) + ["«%s»" % text_]
    if proto == "spi":
        mosi, miso = ["MOSI"], ["MISO"]
        for t in tokens:
            if t == "|":
                mosi.append("|")
                miso.append("|")
            else:
                a, b = t.split("/")
                mosi.append(a)
                miso.append(b)
        return wrap_words(mosi, f_small, 120) + wrap_words(miso, f_small, 120)
    return wrap_words(tokens, f_small, 120)


def draw_decode(st, row, dc, note, note_color):
    screen.fill(BG)
    text("ДЕКОДЕР " + st["board"], (64, 2), ACCENT, f_title, center=True)
    proto = PROTOS[dc["proto"]]
    param = {"uart": "%d бод" % BAUDS[dc["baud"]], "i2c": "—", "spi": "режим %d" % dc["spi"]}[proto]
    values = ["декодер", proto.upper(), param, "тест" if dc["test"] else "зовнішнє"]
    for i, (name, value) in enumerate(zip(DROWS, values)):
        y = 13 + i * ROW_H
        sel = i == row
        if sel:
            pygame.draw.rect(screen, ACCENT, (2, y - 1, 124, ROW_H - 1), border_radius=3)
        text(name, (6, y + 2), BG if sel else DIM, f_label)
        text(value, (122, y), BG if sel else FG, f_value, right=True)
    y = 70
    text(PROTO_PINS[proto], (64, y), DIM, f_small, center=True)
    y += f_small.get_linesize()
    if dc["busy"]:
        text("чекаю на трафік…", (64, y + 4), ACCENT, f_small, center=True)
    elif dc["lines"]:
        for line in dc["lines"][:4]:
            text(line, (64, y), GREEN, f_small, center=True)
            y += f_small.get_linesize()
    elif note:
        text(note, (64, y + 4), note_color, f_small, center=True)
    hint = "←/→ змінити, натиск - захопити, KEY3" if HAT else "←/→ змінити, Enter - захопити, Esc - назад"
    text(hint, (64, 116), DIM, f_small, center=True)
    lcd.flip()


def parse_adc(reply):
    """'ok adc gp26=0.531 gp27=0.713 ...' -> {'gp26': 0.531, ...} or None."""
    if not reply or not reply.startswith("ok adc"):
        return None
    try:
        return {k: float(v) for k, v in (w.split("=", 1) for w in reply.split()[2:])}
    except ValueError:
        return None


DIGITS = {getattr(pygame, "K_%d" % d): str(d) for d in range(10)}
DIGITS.update({pygame.K_PERIOD: ".", pygame.K_KP_PERIOD: ".", pygame.K_k: "k", pygame.K_m: "M"})


def connect():
    """The first port whose board answers ping."""
    for path in PORTS:
        try:
            link = Link(path)
        except OSError:
            continue
        if link.ask("ping", 0.4) == "pong":
            return link
        os.close(link.fd)
    return None


def main():
    link = None
    st, row, typing = None, 0, None
    note, note_color, note_until = "", DIM, 0
    held, held_hat, next_repeat = None, False, 0
    last_try = 0
    mode = "gen"
    vm = {"input": 0, "value": None, "min": None, "max": None, "history": [], "next": 0}
    sc = {"tb": 3, "level": 1.6, "data": None, "rate": 1, "trig": False, "paused": False}
    la = {"tb": 4, "ch": 0, "data": None, "rate": 1, "trig": False, "paused": False}
    dc = {"proto": 0, "baud": 0, "spi": 0, "test": True, "lines": None, "busy": False}

    def run_decode():
        nonlocal note, note_color, note_until
        proto = PROTOS[dc["proto"]]
        cmd = {"uart": "decode uart %d 4" % BAUDS[dc["baud"]], "i2c": "decode i2c",
               "spi": "decode spi %d" % dc["spi"]}[proto] + (" test" if dc["test"] else "")
        dc["busy"], dc["lines"] = True, None
        draw_decode(st, min(row, len(DROWS) - 1), dc, note, note_color)
        reply = link.ask(cmd, 6) if link else None
        dc["busy"] = False
        if reply and reply.startswith("ok decode"):
            dc["lines"] = decode_lines(proto, reply.split()[3:] or ["none"])
        else:
            note, note_color, note_until = (reply[4:] if reply and reply.startswith("err") else
                                            "немає відповіді"), RED, time.monotonic() + 4

    def capture_logic():
        nonlocal note, note_color, note_until
        rate = LOGIC_N / SCOPE_DIVS / LTIMEBASES[la["tb"]]
        reply = link.ask("logic %g %d" % (rate, la["ch"]), 2 * LOGIC_N / rate + 1.5) if link else None
        got = parse_logic(reply)
        if got is None:
            la["data"] = None
            note, note_color, note_until = ("у плати немає аналізатора" if reply and reply.startswith("err")
                                            else "немає відповіді"), RED, time.monotonic() + 3
            return
        la["rate"], la["trig"], la["data"] = got

    def sweep():
        nonlocal note, note_color, note_until
        tdiv = TIMEBASES[sc["tb"]]
        rate = SCOPE_N / SCOPE_DIVS / tdiv
        reply = link.ask("scope %g %.2f" % (rate, sc["level"]), 2 * SCOPE_N / rate + 1.5) if link else None
        got = parse_scope(reply)
        if got is None:
            sc["data"] = None
            note, note_color, note_until = ("у плати немає осцилографа" if reply and reply.startswith("err")
                                            else "немає відповіді"), RED, time.monotonic() + 3
            return
        sc["rate"], sc["trig"], sc["data"] = got

    def reset_volt():
        vm.update(value=None, min=None, max=None, history=[])

    def measure():
        nonlocal note, note_color, note_until
        reply = link.ask("adc") if link else None
        got = parse_adc(reply)
        if got is None:
            if reply and reply.startswith("err"):
                note, note_color, note_until = "у плати немає АЦП", RED, time.monotonic() + 3
            return
        v = got.get(ADC_INPUTS[vm["input"]][0])
        if v is None:
            return
        vm["value"] = v
        vm["min"] = v if vm["min"] is None else min(vm["min"], v)
        vm["max"] = v if vm["max"] is None else max(vm["max"], v)
        vm["history"] = (vm["history"] + [v])[-HISTORY:]

    def send(cmd):
        nonlocal st, note, note_color, note_until
        reply = link.ask(cmd) if link else None
        got = parse(reply)
        if got:
            st = got
            note = ""
        elif reply and reply.startswith("err"):
            note, note_color, note_until = reply[4:], RED, time.monotonic() + 3
        else:
            st = None
        return got

    def change(sign, fine):
        nonlocal mode, row
        if row == R_MODE:
            mode = MODES[(MODES.index(mode) + sign) % len(MODES)]
            reset_volt()
            sc["data"], sc["paused"] = None, False
            la["data"], la["paused"] = None, False
            return
        if mode == "decode":
            if row == R_PROTO:
                dc["proto"] = (dc["proto"] + sign) % len(PROTOS)
            elif row == R_PARAM:
                if PROTOS[dc["proto"]] == "uart":
                    dc["baud"] = (dc["baud"] + sign) % len(BAUDS)
                elif PROTOS[dc["proto"]] == "spi":
                    dc["spi"] = (dc["spi"] + sign) % 4
            elif row == R_SOURCE:
                dc["test"] = not dc["test"]
            dc["lines"] = None
            return
        if mode == "logic":
            if row == R_TIME:
                la["tb"] = min(max(0, la["tb"] + sign), len(LTIMEBASES) - 1)
            elif row == R_TRIG:
                la["ch"] = (la["ch"] + sign) % len(LOGIC_CH)
            la["paused"] = False
            return
        if mode == "scope":
            if row == R_TIME:
                sc["tb"] = min(max(0, sc["tb"] + sign), len(TIMEBASES) - 1)
            elif row == R_TRIG:
                sc["level"] = round(min(max(0.1, sc["level"] + sign * 0.1), 3.2), 1)
            sc["paused"] = False
            return
        if mode == "volt":
            if row == R_INPUT:
                vm["input"] = (vm["input"] + sign) % len(ADC_INPUTS)
                reset_volt()
            return
        if row == R_SHAPE:
            i = SHAPES.index(st["shape"]) if st["shape"] in SHAPES else 0
            send("shape " + SHAPES[(i + sign) % len(SHAPES)])
        elif row == R_FREQ:
            f = st["freq"]
            new = f + sign * max(1, round(f * 0.01)) if fine else freq_step(f, sign > 0)
            send("freq %d" % min(st["fmax"], max(st["fmin"], new)))
        elif row == R_DUTY:
            if st["shape"] != "square":
                return
            send("duty %g" % min(100, max(0, st["duty"] + sign * (1 if fine else 5))))
        else:
            send("on" if sign > 0 else "off")

    while True:
        now = time.monotonic()
        if st is None and now - last_try > 1.5:  # (re)connect
            last_try = now
            if link is None or not send("get"):
                if link:
                    os.close(link.fd)
                link = connect()
                if link:
                    send("get")
        for ev in pygame.event.get():
            if ev.type == pygame.QUIT:
                return
            if ev.type == pygame.KEYUP:
                if ev.key == held:
                    held = None
                continue
            if ev.type != pygame.KEYDOWN:
                continue
            k, hat = ev.key, getattr(ev, "hat", False)
            held = None  # any key press ends a repeat
            if k == pygame.K_ESCAPE or (k == pygame.K_3 and hat):
                if typing is not None:
                    typing = None
                    continue
                return
            if st is None:
                continue
            rows = {"gen": ROWS, "volt": VROWS, "scope": SROWS, "logic": SROWS, "decode": DROWS}[mode]
            if mode == "decode" and k in (pygame.K_RETURN, pygame.K_KP_ENTER, pygame.K_SPACE):
                lcd.play("select")
                run_decode()
                continue
            if mode == "volt" and k in (pygame.K_RETURN, pygame.K_KP_ENTER, pygame.K_SPACE):
                reset_volt()
                lcd.play("select")
                continue
            if mode in ("scope", "logic") and k in (pygame.K_RETURN, pygame.K_KP_ENTER, pygame.K_SPACE):
                state = sc if mode == "scope" else la
                state["paused"] = not state["paused"]
                lcd.play("select")
                continue
            if mode != "gen" and k in DIGITS and not hat:
                continue
            if k in DIGITS and not hat and row in (R_FREQ, R_DUTY):
                if DIGITS[k] in "kM" and row != R_FREQ:
                    continue
                typing = (typing or "") + DIGITS[k]
            elif k == pygame.K_BACKSPACE and typing is not None:
                typing = typing[:-1] or None
            elif k in (pygame.K_RETURN, pygame.K_KP_ENTER, pygame.K_SPACE):
                if typing is not None:
                    try:
                        v = number(typing)
                        send(("freq %d" % round(v)) if row == R_FREQ else ("duty %g" % v))
                    except ValueError:
                        note, note_color, note_until = "не число: " + typing, RED, now + 3
                    typing = None
                else:
                    send("off" if st["on"] else "on")
                    lcd.play("select")
            elif k == pygame.K_UP:
                row, typing = (row - 1) % len(rows), None
                lcd.play("click")
            elif k == pygame.K_DOWN:
                row, typing = (row + 1) % len(rows), None
                lcd.play("click")
            elif k in (pygame.K_LEFT, pygame.K_RIGHT):
                typing = None
                change(1 if k == pygame.K_RIGHT else -1, False)
                held, held_hat, next_repeat = k, hat, now + 0.4
            elif k in (pygame.K_EQUALS, pygame.K_PLUS, pygame.K_KP_PLUS) or (k == pygame.K_1 and hat):
                change(1, True)
            elif k in (pygame.K_MINUS, pygame.K_KP_MINUS) or (k == pygame.K_2 and hat):
                change(-1, True)
        if held and not held_hat and held not in lcd._held_arrows:  # a keyboard says it's up
            held = None
        if held and st and mode == "gen" and time.monotonic() >= next_repeat and row in (R_FREQ, R_DUTY):
            change(1 if held == pygame.K_RIGHT else -1, False)
            next_repeat = time.monotonic() + 0.12
        if note and time.monotonic() > note_until and note_color == RED:
            note = ""
        if mode == "volt" and st and link and time.monotonic() >= vm["next"]:
            vm["next"] = time.monotonic() + 0.1
            measure()
        if mode == "scope" and st and link and not sc["paused"]:
            sweep()
        if mode == "logic" and st and link and not la["paused"]:
            capture_logic()
        if mode == "volt" and st:
            draw_volt(st, min(row, len(VROWS) - 1), vm, note, note_color)
        elif mode == "scope" and st:
            draw_scope(st, min(row, len(SROWS) - 1), sc, note, note_color)
        elif mode == "logic" and st:
            draw_logic(st, min(row, len(SROWS) - 1), la, note, note_color)
        elif mode == "decode" and st:
            draw_decode(st, min(row, len(DROWS) - 1), dc, note, note_color)
        else:
            draw(st, row, typing, note, note_color)
        clock.tick(20)


try:
    main()
finally:
    screen.fill(BG)
    lcd.flip()
    lcd.quit()
