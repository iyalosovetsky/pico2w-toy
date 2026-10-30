"""Screensaver - the animations of our Raspberry Pi Pico W DVI LCD dashboard (pico-dvi-python,
picodvi.julia / picodvi.effect) on the whole screen: a Julia set with a turning c, a plasma, a lava lamp
(metaballs), water ripples and a kaleidoscope flower, 2.5 minutes each at half the dashboard's pace, the
same palettes; the time and the date in a strip at the bottom.

The same integer formulas as the C module, done with numpy on a 128x128 picture (the HAT's own size;
smoothly scaled up on the PicoCalc). The menu starts it after a while without a key
(~/.config/lcdtoy/screensaver: seconds, 0 - never; 180 by default) or from its own item; any key or
button - back to the menu.
"""
import math
import sys
import time

import numpy as np
import pygame
import lcd

R = 128                      # the animations' own resolution
SWITCH_S = 150               # seconds per animation (2.5 minutes; the dashboard's slot uses 20)
SPEED = 0.5                  # of the dashboard's pace: a screensaver should drift, not hurry
FPS = 20
NAMES = ["Julia", "плазма", "лава-лампа", "хвилі", "квітка"]
DAYS = ["Понеділок", "Вівторок", "Середа", "Четвер", "П'ятниця", "Субота", "Неділя"]
MONTHS = ["січня", "лютого", "березня", "квітня", "травня", "червня", "липня", "серпня", "вересня",
          "жовтня", "листопада", "грудня"]
BG = (14, 17, 22)

screen = lcd.init()
clock = pygame.time.Clock()
NW, NH = lcd.NATIVE_W, lcd.NATIVE_H
FONT_DIR = "/usr/share/fonts/truetype/dejavu/"
BIG = lcd.S > 1


def font(name, px):
    size = px / lcd.S if lcd.S != 1 else px
    try:
        return pygame.font.Font(FONT_DIR + name, size)
    except (FileNotFoundError, OSError):
        return pygame.font.Font(None, size)


f_clock = font("DejaVuSans.ttf", 46 if BIG else 22)
f_date = font("DejaVuSans.ttf", 15 if BIG else 8)
f_name = font("DejaVuSans.ttf", 10 if BIG else 6)


# ---------------------------------------------------------------- palettes (screen.make_palette)

def make_palette(stops, cyclic=True):
    """256 colours through the stops, smoothstep between them (cyclic, or a linear ramp)."""
    n = len(stops) if cyclic else len(stops) - 1
    out = np.zeros((256, 3), np.uint8)
    for i in range(256):
        f = i * n / (256 if cyclic else 255)
        k = int(f) if cyclic else min(int(f), n - 1)
        t = f - k
        t = t * t * (3 - 2 * t)
        a, b = stops[k % len(stops)], stops[(k + 1) % len(stops)]
        out[i] = [int(a[j] + (b[j] - a[j]) * t) for j in range(3)]
    return out


PAL_SKY = make_palette(((20, 24, 70), (64, 40, 160), (190, 70, 200), (255, 140, 120), (80, 200, 255), (30, 90, 200)))
PAL_PLASMA = make_palette(((40, 10, 90), (200, 40, 160), (255, 150, 60), (255, 230, 120), (60, 200, 220),
                           (20, 60, 160)))
PAL_LAVA = make_palette(((14, 17, 22), (50, 8, 40), (120, 20, 60), (200, 40, 50), (250, 120, 40), (255, 200, 80),
                         (255, 245, 200)), False)
PAL_OCEAN = make_palette(((5, 20, 60), (10, 80, 150), (40, 170, 220), (200, 245, 255), (40, 170, 220),
                          (10, 80, 150)))

# ---------------------------------------------------------------- the C module's helpers

SIN8 = (127.0 * np.sin(np.arange(256) * 2 * np.pi / 256)).astype(np.int32)   # sin8[] in modpicodvi.c
J, I = np.mgrid[0:R, 0:R].astype(np.int32)       # row j, column i of every pixel


def isin(a):
    return SIN8[np.asarray(a) & 255]


def isqrt(v):
    return np.sqrt(v).astype(np.int32)


_dx, _dy = I - R // 2 + 0.5, J - R // 2 + 0.5   # the polar coordinates (polar_init)
_a = np.arctan2(_dy, _dx) * (256.0 / (2 * np.pi))
POLAR_A = np.where(_a < 0, _a + 256, _a).astype(np.int32) & 255
POLAR_R = np.minimum(np.sqrt(_dx * _dx + _dy * _dy), 255).astype(np.int32)


def sources(t, nb):
    """The moving centres (bx, by) of the plasma / lava lamp / ripples - Lissajous paths."""
    bx, by = [], []
    for k in range(nb):
        ph = k * 51
        bx.append(R // 2 + int(SIN8[((t >> (4 + (k & 1))) + ph) & 255]) * (R // 2 - 6) // 127)
        by.append(R // 2 + int(SIN8[((t >> 5) * (k + 2) // 2 + ph * 3 + 64) & 255]) * (R // 2 - 6) // 127)
    return bx, by


# ---------------------------------------------------------------- the five animations

def julia(t):
    """z -> z^2 + c, c = 0.7885 e^(ia) turning once in 9 s; colour = iterations * 10 + a shift."""
    a = (t % 9000) * (2 * math.pi / 9000)
    c = complex(0.7885 * math.cos(a), 0.7885 * math.sin(a))
    step = 2.7 / R                                    # the dashboard's span (230 / 8192 over 96 px)
    z = ((I - R // 2) * step + 1j * (J - R // 2) * step).astype(np.complex64).ravel()
    it = np.full(z.shape, 40, np.int32)               # 40 = maxit: never escaped
    alive = np.arange(z.size)
    for n in range(40):
        z = z * z + c
        out = (z.real * z.real + z.imag * z.imag) > 4.0
        if out.any():
            it[alive[out]] = n
            keep = ~out
            z, alive = z[keep], alive[keep]
            if not alive.size:
                break
    shift = (t // 30) & 255
    img = PAL_SKY[(it * 10 + shift) & 255]
    img[it >= 40] = BG
    return img.reshape(R, R, 3)


def plasma(t):
    tt = t >> 4
    bx, by = sources(t, 3)
    d = isqrt((I - bx[0]) ** 2 + (J - by[0]) ** 2)
    v = isin(I * 3 + tt) + isin(J * 4 - tt * 2 // 3) + isin((I + J) * 2 + tt // 2) + isin(d * 6 - tt)
    v = ((v + 508) >> 2) + (tt >> 1)
    return PAL_PLASMA[v & 255]


def lava(t):
    bx, by = sources(t, 5)
    f = np.zeros((R, R), np.int32)
    for k in range(5):
        f += (150 * 1024) // ((I - bx[k]) ** 2 + (J - by[k]) ** 2 + 1)
    v = np.where(f >= 1024, 190 + np.minimum(65, (f - 1024) >> 6), (f * 150) >> 10)
    return PAL_LAVA[v & 255]


def ripples(t):
    tt = t >> 4
    bx, by = sources(t, 3)
    v = np.zeros((R, R), np.int32)
    for k in range(3):
        v += isin(isqrt((I - bx[k]) ** 2 + (J - by[k]) ** 2) * 7 - tt * 3)
    v = (v + 381) * 255 // 762
    return PAL_OCEAN[v & 255]


def bloom(t):
    """The kaleidoscope flower: two counter-rotating petal layers, glowing rims, rays, green filaments."""
    tt = t >> 4
    a, r = POLAR_A, POLAR_R
    Rr = R // 2
    b1 = Rr * 3 // 4 + ((isin(a * 8 + tt) * Rr // 6) >> 7)
    b2 = Rr * 2 // 5 + ((isin(a * 12 - tt * 2) * Rr // 9) >> 7)
    d1, d2 = np.abs(r - b1), np.abs(r - b2)
    blue = np.zeros((R, R), np.int32)
    red = np.zeros((R, R), np.int32)
    green = np.zeros((R, R), np.int32)
    inner = r < b1
    blue += np.where(inner, 50 + r * 90 // (b1 + 1), 0)
    speck = inner & (isin(a * 20 + r * 9 + tt) * isin(r * 13 - a * 6 - tt) > 7000)
    green += np.where(speck, 110, 0)
    rim = d1 < 4
    blue += np.where(rim, (4 - d1) * 45, 0)
    red += np.where(rim, (4 - d1) * 30, 0)
    blue += np.where(r < b2, 40, 0)
    rim2 = d2 < 3
    blue += np.where(rim2, (3 - d2) * 60, 0)
    green += np.where(rim2, (3 - d2) * 25, 0)
    core = Rr // 3
    rays = (r < core) & (isin(a * 24 + tt * 3) > 70)
    blue += np.where(rays, (core - r) * 200 // core, 0)
    red += np.where(rays, (core - r) * 70 // core, 0)
    centre = r < 4
    blue += np.where(centre, 255, 0)
    red += np.where(centre, 120, 0)
    green += np.where(centre, 60, 0)
    fade = 150 - (r - b1) * 10
    fil = (r > b1 + 2) & (fade > 0) & (isin(a * 48 + r * 6 - tt * 2) > 105)
    green += np.where(fil, fade, 0)
    blue += np.where(fil, fade // 4, 0)
    img = np.stack([red, green + blue // 6, blue], -1)
    return np.minimum(img, 255).astype(np.uint8)


ANIMS = [julia, plasma, lava, ripples, bloom]


# ---------------------------------------------------------------- the screen

small = pygame.Surface((R, R))


def show(img):
    """A 128x128 picture onto the whole screen (smoothly scaled on the PicoCalc)."""
    pygame.surfarray.blit_array(small, img.swapaxes(0, 1))
    big = pygame.transform.smoothscale(small, (NW, NH)) if NW != R else small
    pygame.Surface.blit(screen, big, (0, 0))


_strip = None


def clock_strip(name):
    """The time, the day and the date over a darkened strip at the bottom; the animation's name above it."""
    global _strip
    h = int(NH * 0.34)
    if _strip is None:
        _strip = pygame.Surface((NW, h), pygame.SRCALPHA)
        _strip.fill((0, 0, 0, 140))
    pygame.Surface.blit(screen, _strip, (0, NH - h))
    now = time.localtime()
    top = 128 - h / lcd.S
    t_img = f_clock.render(time.strftime("%H:%M", now), True, (236, 239, 244))
    screen.blit(t_img, (64 - t_img.get_width() / 2, top + 1))
    d = "%s, %d %s" % (DAYS[now.tm_wday], now.tm_mday, MONTHS[now.tm_mon - 1])
    d_img = f_date.render(d, True, (150, 162, 176))
    screen.blit(d_img, (64 - d_img.get_width() / 2, top + t_img.get_height()))
    pygame.draw.rect(screen, (40, 46, 56), (14, 126, 100, 1))          # the seconds, like the dashboard's bar
    pygame.draw.rect(screen, (79, 195, 247), (14, 126, 100 * now.tm_sec / 60.0, 1))
    n_img = f_name.render(name, True, (200, 200, 210))
    screen.blit(n_img, (126 - n_img.get_width(), top - n_img.get_height()))


def keys_pressed():
    out = False
    for ev in pygame.event.get():
        if ev.type in (pygame.QUIT, pygame.KEYDOWN):
            out = True
    return out


def main(seconds=None, switch=SWITCH_S):
    """Until a key; seconds / switch - for the GIF recorder (each animation for a while, then stop)."""
    pygame.event.clear()
    t0 = time.monotonic()
    while True:
        now = time.monotonic()
        if seconds is not None and now - t0 > seconds:
            return "timeout"
        # ms, like the dashboard's ticks; kept small - numpy 2 refuses int32 maths with bigger Python ints
        t = int(now * 1000 * SPEED) % (1 << 27)
        kind = int((now - t0) // switch) % len(ANIMS)
        show(ANIMS[kind](t))
        clock_strip(NAMES[kind])
        lcd.flip()
        if keys_pressed():
            return
        clock.tick(FPS)


if __name__ == "__main__":
    # screensaver.py [seconds]: the menu's turn - after that, exit code 3 (the menu goes on to the next one)
    code = 0
    try:
        turn = float(sys.argv[1]) if len(sys.argv) > 1 else None
        code = 3 if main(turn) == "timeout" else 0
    finally:
        screen.fill((0, 0, 0))
        lcd.flip()
        lcd.quit()
    sys.exit(code)
