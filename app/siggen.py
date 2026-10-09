"""Signal generator board (tools/siggen: an RP2350 or an ESP32-C6 running rp2350.py / esp32c6.py
as its main.py), driven over the UART (/dev/serial0) or USB (/dev/ttyACM*) - whichever answers.

UP / DOWN - row (shape, frequency, duty, signal), LEFT / RIGHT - change (held: repeats),
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
                "board": kv.get("board", "esp32-c6").upper()}
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

ROWS = ["Форма", "Частота", "Скважність", "Сигнал"]
R_SHAPE, R_FREQ, R_DUTY, R_OUT = range(4)
ROW_H = 16
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
    values = [SHAPE_NAMES.get(st["shape"], st["shape"]), freq_text(st["freq"]),
              "%g %%" % st["duty"] if square else "—", "УВІМК" if st["on"] else "ВИМК"]
    for i, name in enumerate(ROWS):
        y = 14 + i * ROW_H
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
    x0, x1, lo, hi = 22, 124, 94, 80
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
    pygame.draw.circle(screen, color, (10, 87), 6)        # the LED
    pygame.draw.circle(screen, DIM, (10, 87), 6, 1)
    if note:
        text(note, (64, 97), note_color, f_small, center=True)
    if HAT:
        hints = ["←/→ змінити, KEY1/2 точно", "натиск - сигнал, KEY3 - назад"]
    else:
        hints = ["←/→ змінити, +/- точно, цифри", "Enter - сигнал, Esc - назад"]
    text(hints[0], (64, 106), DIM, f_small, center=True)
    text(hints[1], (64, 116), DIM, f_small, center=True)
    lcd.flip()


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
                row, typing = (row - 1) % len(ROWS), None
                lcd.play("click")
            elif k == pygame.K_DOWN:
                row, typing = (row + 1) % len(ROWS), None
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
        if held and st and time.monotonic() >= next_repeat and row in (R_FREQ, R_DUTY):  # repeats
            change(1 if held == pygame.K_RIGHT else -1, False)
            next_repeat = time.monotonic() + 0.12
        if note and time.monotonic() > note_until and note_color == RED:
            note = ""
        draw(st, row, typing, note, note_color)
        clock.tick(20)


try:
    main()
finally:
    screen.fill(BG)
    lcd.flip()
    lcd.quit()
