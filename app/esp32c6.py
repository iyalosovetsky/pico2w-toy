"""Square wave generator on the ESP32-C6-Zero (tools/esp32c6/main.py), driven over the UART.

UP / DOWN - row (frequency, duty, signal), LEFT / RIGHT - change (held: repeats),
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

PORT = os.environ.get("ESP32C6_PORT", "/dev/serial0")
FMIN, FMAX = 2, 1000000           # as in tools/esp32c6/main.py
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
    """'ok freq=1000 duty=50 out=on' -> dict, or None."""
    if not reply or not reply.startswith("ok "):
        return None
    kv = dict(w.split("=", 1) for w in reply[3:].split() if "=" in w)
    try:
        return {"freq": int(kv["freq"]), "duty": float(kv["duty"]), "on": kv.get("out") == "on"}
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
    pos = math.log10(st["freq"] / FMIN) / math.log10(FMAX / FMIN)
    h = (270 * pos % 360) / 60
    v = 255 * max(st["duty"], 8) / 100  # brighter than the LED itself, so it shows on the LCD
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

ROWS = ["Частота", "Скважність", "Сигнал"]
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
    text("ГЕНЕРАТОР ESP32-C6", (64, 2), ACCENT, f_title, center=True)
    if st is None:
        text("ESP32-C6 не відповідає", (64, 44), RED, f_label, center=True)
        text(PORT, (64, 58), DIM, f_small, center=True)
        text("перевірте дроти TX/RX", (64, 70), DIM, f_small, center=True)
        text(("KEY3" if HAT else "Esc") + " - назад", (64, 114), DIM, f_small, center=True)
        lcd.flip()
        return
    values = [freq_text(st["freq"]), "%g %%" % st["duty"], "УВІМК" if st["on"] else "ВИМК"]
    for i, name in enumerate(ROWS):
        y = 15 + i * 20
        sel = i == row
        if sel:
            pygame.draw.rect(screen, ACCENT, (2, y - 1, 124, 19), border_radius=3)
        text(name, (6, y + 4), BG if sel else DIM, f_label)
        value = typing + "_" if sel and typing is not None else values[i]
        color = BG if sel else (GREEN if i == 2 and st["on"] else RED if i == 2 else FG)
        text(value, (122, y + 1), color, f_value, right=True)
    # the wave: three periods with the duty cycle, in the LED's colour
    color = led_color(st)
    wave = color if st["on"] else DIM
    x0, x1, lo, hi = 22, 124, 90, 76
    period = (x1 - x0) / 3
    pts = [(x0, lo)]
    for k in range(3):
        a = x0 + k * period
        b = a + period * st["duty"] / 100 if st["on"] else a
        pts += [(a, lo), (a, hi), (b, hi), (b, lo)] if st["on"] and st["duty"] > 0 else [(a, lo)]
    pts.append((x1, lo))
    pygame.draw.lines(screen, wave, False, pts, 2 if BIG else 1)
    pygame.draw.circle(screen, color, (10, 83), 6)        # the LED
    pygame.draw.circle(screen, DIM, (10, 83), 6, 1)
    if note:
        text(note, (64, 96), note_color, f_small, center=True)
    if HAT:
        hints = ["←/→ змінити, KEY1/2 точно", "натиск - сигнал, KEY3 - назад"]
    else:
        hints = ["←/→ змінити, +/- точно, цифри", "Enter - сигнал, Esc - назад"]
    text(hints[0], (64, 106), DIM, f_small, center=True)
    text(hints[1], (64, 116), DIM, f_small, center=True)
    lcd.flip()


DIGITS = {getattr(pygame, "K_%d" % d): str(d) for d in range(10)}
DIGITS.update({pygame.K_PERIOD: ".", pygame.K_KP_PERIOD: ".", pygame.K_k: "k", pygame.K_m: "M"})


def main():
    try:
        link = Link(PORT)
    except OSError:
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
        if row == 0:
            f = st["freq"]
            new = f + sign * max(1, round(f * 0.01)) if fine else freq_step(f, sign > 0)
            send("freq %d" % min(FMAX, max(FMIN, new)))
        elif row == 1:
            send("duty %g" % min(100, max(0, st["duty"] + sign * (1 if fine else 5))))
        else:
            send("on" if sign > 0 else "off")

    while True:
        now = time.monotonic()
        if st is None and link and now - last_try > 1.5:  # (re)connect
            last_try = now
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
            if k in DIGITS and not hat and row < 2:
                if DIGITS[k] in "kM" and row != 0:
                    continue
                typing = (typing or "") + DIGITS[k]
            elif k == pygame.K_BACKSPACE and typing is not None:
                typing = typing[:-1] or None
            elif k in (pygame.K_RETURN, pygame.K_KP_ENTER, pygame.K_SPACE):
                if typing is not None:
                    try:
                        v = number(typing)
                        send(("freq %d" % round(v)) if row == 0 else ("duty %g" % v))
                    except ValueError:
                        note, note_color, note_until = "не число: " + typing, RED, now + 3
                    typing = None
                else:
                    send("off" if st["on"] else "on")
                    lcd.play("select")
            elif k == pygame.K_UP:
                row, typing = (row - 1) % 3, None
                lcd.play("click")
            elif k == pygame.K_DOWN:
                row, typing = (row + 1) % 3, None
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
        if held and st and time.monotonic() >= next_repeat and row < 2:  # held arrow repeats
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
