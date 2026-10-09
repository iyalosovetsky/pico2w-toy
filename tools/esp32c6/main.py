# pico2w-toy: ESP32-C6-Zero square wave generator, driven from the Zero 2 W over UART.
#
# Pins: TX (GPIO16) / RX (GPIO17) -> Zero 2 W GPIO 15 / 14 (/dev/serial0), 115200 8N1.
# Output: square wave on GPIO19. The onboard WS2812 (GPIO8) shows it: brightness = duty,
# colour = frequency on a log scale (2 Hz red ... 1 MHz violet).
#
# Commands, one per line; every command answers one line "ok freq=<Hz> duty=<%> out=<on|off>"
# or "err <reason>":
#   freq <Hz>     2 .. 1000000, also 2.5k / 1M
#   duty <%>      0 .. 100
#   on / off      start / stop the output (LED off while stopped)
#   get           current settings
#   ping          answers "pong"
import math
import time

import neopixel
from machine import Pin, PWM, UART

OUT_PIN, LED_PIN = 19, 8
FMIN, FMAX = 2, 1000000  # the PWM (LEDC) can't go below 2 Hz
LED_MAX = 80  # WS2812 brightness at 100 % duty (255 is blinding)

uart = UART(1, baudrate=115200, tx=16, rx=17)
led = neopixel.NeoPixel(Pin(LED_PIN), 1)
pwm = PWM(Pin(OUT_PIN), freq=1000, duty_u16=32768)
state = {"freq": 1000, "duty": 50.0, "on": True}


def hsv(h, v):
    """Hue 0..360, value 0..255 -> (r, g, b) at full saturation."""
    h = (h % 360) / 60
    i, f = int(h), h - int(h)
    p, q, t = 0, int(v * (1 - f)), int(v * f)
    v = int(v)
    return [(v, t, p), (q, v, p), (p, v, t), (p, q, v), (t, p, v), (v, p, q)][i % 6]


def show():
    if not state["on"]:
        led[0] = (0, 0, 0)
    else:
        pos = math.log10(state["freq"] / FMIN) / math.log10(FMAX / FMIN)  # 0..1
        led[0] = hsv(270 * pos, LED_MAX * state["duty"] / 100)
    led.write()


def apply():
    if state["on"]:
        pwm.init(freq=state["freq"], duty_u16=round(65535 * state["duty"] / 100))
    else:
        pwm.deinit()
        Pin(OUT_PIN, Pin.OUT, value=0)
    show()


def number(s):
    s = s.strip().lower()
    mult = {"k": 1000, "m": 1000000}.get(s[-1:], 1)
    return float(s[:-1] if mult > 1 else s) * mult


def status():
    return "ok freq=%d duty=%g out=%s" % (state["freq"], state["duty"], "on" if state["on"] else "off")


def command(line):
    words = line.split()
    if not words:
        return None
    cmd, args = words[0].lower(), words[1:]
    old = dict(state)
    try:
        if cmd == "ping":
            return "pong"
        if cmd == "get":
            return status()
        if cmd == "freq" and len(args) == 1:
            f = round(number(args[0]))
            if not FMIN <= f <= FMAX:
                return "err freq %d..%d" % (FMIN, FMAX)
            state["freq"] = f
        elif cmd == "duty" and len(args) == 1:
            d = number(args[0].rstrip("%"))
            if not 0 <= d <= 100:
                return "err duty 0..100"
            state["duty"] = d
        elif cmd in ("on", "off") and not args:
            state["on"] = cmd == "on"
        else:
            return "err unknown command: " + line
        apply()
        return status()
    except Exception as e:  # bad number, or a frequency the PWM can't make
        state.update(old)
        apply()
        return "err %s" % e


apply()
buf = b""
while True:
    if uart.any():
        buf += uart.read()
        while b"\n" in buf:
            line, buf = buf.split(b"\n", 1)
            reply = command(line.decode("utf-8", "replace").strip())
            if reply:
                uart.write(reply + "\n")
                print(line, "->", reply)
    time.sleep_ms(5)
