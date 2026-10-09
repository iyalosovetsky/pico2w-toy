# pico2w-toy: ESP32-C6-Zero signal generator, driven from the Zero 2 W over UART.
#
# Pins: TX (GPIO16) / RX (GPIO17) -> Zero 2 W GPIO 15 / 14 (/dev/serial0), 115200 8N1.
# Output on GPIO19:
#   square              - hardware PWM, 2 Hz .. 1 MHz, duty 0..100 %
#   sine, triangle, saw - DDS: a 150 kHz 9-bit PWM carrier whose duty follows the wave (written
#                         straight into the LEDC registers by viper code, ~1.4 M updates/s, so
#                         the carrier is the sample rate); the ESP32-C6 has no DAC, so put an
#                         RC low-pass on the pin (e.g. 1 kOhm + 10 nF, ~16 kHz) to get the
#                         analog wave. 1 Hz .. 10 kHz.
# The onboard WS2812 (GPIO8) shows it: brightness = duty (square) / half (other shapes),
# colour = frequency on a log scale (2 Hz red ... 1 MHz violet).
#
# Commands, one per line; answers one line "ok shape=.. freq=.. duty=.. out=.. fmax=.." or "err ..":
#   shape square|sine|triangle|saw
#   freq <Hz>     also 2.5k / 1M
#   duty <%>      0 .. 100 (square)
#   on / off      start / stop the output
#   get           current settings
#   ping          answers "pong"
#   put <file> <bytes>   then exactly that many raw bytes: replaces a file on the board
#                        (esp32c6 flash main.py does this - updates without USB)
#   reset         restart the board (runs the new main.py)
import array
import math
import os
import time

import machine
import micropython  # noqa: F401 - @micropython.viper
import neopixel
from machine import Pin, PWM, UART, mem32

OUT_PIN, LED_PIN = 19, 8
SQ_FMIN, SQ_FMAX = 2, 1000000   # the PWM (LEDC) can't go below 2 Hz
DDS_FMIN, DDS_FMAX = 1, 10000
CARRIER = 150000                # PWM carrier of the DDS shapes, Hz (9-bit duty)
LEDC = 0x60007000               # ESP32-C6 LEDC registers (channel n at + 0x14 * n)
CHUNK = 20000                   # DDS updates between UART checks (~15 ms)
SHAPES = ("square", "sine", "triangle", "saw")
LED_MAX = 80                    # WS2812 brightness at 100 % duty (255 is blinding)
N = 256                         # samples in a wave table

uart = UART(1, baudrate=115200, tx=16, rx=17, rxbuf=2048)
led = neopixel.NeoPixel(Pin(LED_PIN), 1)
pwm = PWM(Pin(OUT_PIN), freq=1000, duty_u16=32768)
state = {"shape": "square", "freq": 1000, "duty": 50.0, "on": True}

LEVELS = {  # one period, 0..1
    "sine": lambda i: 0.5 + 0.5 * math.sin(2 * math.pi * i / N),
    "triangle": lambda i: 2 * i / N if i < N // 2 else 2 - 2 * i / N,
    "saw": lambda i: i / (N - 1),
}
# DDS state: the wave table in LEDC duty register units, [CONF1 start word, channel address],
# 28-bit phase, phase step per update and the measured updates per second
dds = {"table": None, "regs": array.array("I", [0x80000000 | 1 << 30 | 1 << 20 | 1 << 10, 0]),
       "ph": 0, "inc": 0, "rate": 1400000}


def limits():
    return (SQ_FMIN, SQ_FMAX) if state["shape"] == "square" else (DDS_FMIN, DDS_FMAX)


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
        pos = math.log10(max(state["freq"], SQ_FMIN) / SQ_FMIN) / math.log10(SQ_FMAX / SQ_FMIN)
        duty = state["duty"] if state["shape"] == "square" else 50
        led[0] = hsv(270 * pos, LED_MAX * duty / 100)
    led.write()


def apply():
    if not state["on"]:
        pwm.deinit()
        Pin(OUT_PIN, Pin.OUT, value=0)
    elif state["shape"] == "square":
        pwm.init(freq=state["freq"], duty_u16=round(65535 * state["duty"] / 100))
    else:
        dds_setup()
    show()


def dds_setup():
    """Carrier on, find MicroPython's LEDC channel and its full-scale duty, build the table."""
    pwm.init(freq=CARRIER, duty_u16=65535)
    ch = max(range(6), key=lambda c: mem32[LEDC + 0x14 * c + 8])
    full = mem32[LEDC + 0x14 * ch + 8] >> 4  # duty register = counts << 4
    level = LEVELS[state["shape"]]
    dds["table"] = array.array("I", (round(full * level(i)) << 4 for i in range(N)))
    dds["regs"][1] = LEDC + 0x14 * ch
    dds_freq()


def dds_freq():
    dds["inc"] = int(state["freq"] * 268435456 / dds["rate"])


@micropython.viper
def dds_run(table: ptr32, regs: ptr32, inc: int, count: int, ph: int) -> int:
    """count duty updates along the table; returns the phase. The LEDC takes a new duty at
    the end of each carrier period, so the carrier rate is the real sample rate."""
    ch = ptr32(regs[1])
    start = regs[0]
    for _ in range(count):
        ph = (ph + inc) & 0xFFFFFFF
        ch[2] = table[ph >> 20]      # DUTY
        ch[3] = start                # CONF1: duty_start
        ch[0] = ch[0] | 0x10         # CONF0: para_up
    return ph


def dds_chunk():
    t = time.ticks_us()
    dds["ph"] = dds_run(dds["table"], dds["regs"], dds["inc"], CHUNK, dds["ph"])
    dt = time.ticks_diff(time.ticks_us(), t)
    if dt > 0:  # keep the frequency right: follow the real loop speed
        dds["rate"] = (dds["rate"] * 3 + CHUNK * 1000000 // dt) // 4
        dds_freq()


def number(s):
    s = s.strip().lower()
    mult = {"k": 1000, "m": 1000000}.get(s[-1:], 1)
    return float(s[:-1] if mult > 1 else s) * mult


def status():
    return "ok shape=%s freq=%d duty=%g out=%s fmax=%d" % (
        state["shape"], state["freq"], state["duty"], "on" if state["on"] else "off", limits()[1])


def receive(name, size, head=b""):
    """put: size raw bytes (head = those already read) from the UART into name, via a temp file."""
    tmp = name + ".new"
    head = head[:size]
    got, end = len(head), time.ticks_add(time.ticks_ms(), 10000 + size // 5)
    with open(tmp, "wb") as f:
        f.write(head)
        while got < size and time.ticks_diff(end, time.ticks_ms()) > 0:
            n = uart.any()
            if n:
                data = uart.read(min(n, size - got))
                f.write(data)
                got += len(data)
            else:
                time.sleep_ms(2)
    if got != size:
        os.remove(tmp)
        return "err put: got %d of %d bytes" % (got, size)
    try:
        os.remove(name)
    except OSError:
        pass
    os.rename(tmp, name)
    return "ok put %s %d" % (name, size)


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
        if cmd == "reset":
            uart.write("ok reset\n")
            time.sleep_ms(50)
            machine.reset()
        if cmd == "shape" and len(args) == 1 and args[0].lower() in SHAPES:
            state["shape"] = args[0].lower()
            lo, hi = limits()
            state["freq"] = min(hi, max(lo, state["freq"]))
        elif cmd == "freq" and len(args) == 1:
            f = round(number(args[0]))
            lo, hi = limits()
            if not lo <= f <= hi:
                return "err freq %d..%d" % (lo, hi)
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
            words = line.decode("utf-8", "replace").split()
            if len(words) == 3 and words[0] == "put":  # the file follows right after this line
                try:
                    reply = receive(words[1], int(words[2]), buf)
                except Exception as e:
                    reply = "err put: %s" % e
                uart.write(reply + "\n")
                buf = b""
                continue
            reply = command(line.decode("utf-8", "replace").strip())
            if reply:
                uart.write(reply + "\n")
                print(line, "->", reply)
    if state["on"] and state["shape"] != "square":
        dds_chunk()
    else:
        time.sleep_ms(5)
