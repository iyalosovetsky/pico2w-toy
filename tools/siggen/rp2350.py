# pico2w-toy: signal generator on a Pimoroni Tiny 2350 (RP2350), driven from the Zero 2 W.
#
# Commands come over UART0 (GP0 TX -> Zero GPIO 15, GP1 RX <- Zero GPIO 14, /dev/serial0,
# 115200 8N1) or over USB (/dev/ttyACM0) - the same protocol as esp32c6.py.
# Output on GP6 (PWM slice 3 - the RGB LED uses slices 1 and 2):
#   square              - hardware PWM, 10 Hz .. 10 MHz (duty steps get coarse above ~1 MHz);
#                         below 10 Hz it comes from the DMA path below, 1 Hz up
#   sine, triangle, saw - a 586 kHz 8-bit PWM (TOP 255 at 150 MHz) whose duty a DMA channel
#                         writes from a wave table, paced by a DMA timer (150 MHz * X / Y), so
#                         the frequency is exact to ~1e-5 and the CPU is free. No DAC on the
#                         RP2350: put an RC low-pass on GP6 (e.g. 1 kOhm + 4.7 nF, ~34 kHz)
#                         for the analog wave. 1 Hz .. 20 kHz.
# The RGB LED (GP18-20, active low) shows it: brightness = duty (square) / half (other shapes),
# colour = frequency on a log scale (red ... violet).
#
# Commands, one per line; answer: "ok board=rp2350 shape=.. freq=.. duty=.. out=.. fmin=.. fmax=.."
# or "err ...":
#   shape square|sine|triangle|saw     freq <Hz> (2.5k, 1M)     duty <%> (square)
#   on / off     get     ping     reset
#   probe        self-check: the mean level of the output in ten 0.1 s slices (0..100 %)
#   put <file> <bytes>   then the raw bytes: replaces a file (program updates over the UART)
import array
import math
import os
import select
import sys
import time
import uctypes

import machine
import rp2
from machine import Pin, PWM, UART, mem32

OUT_PIN = 6
SQ_FMIN, SQ_FMAX = 1, 10000000
DDS_FMIN, DDS_FMAX = 1, 20000
SQ_PWM_MIN = 10                 # below this the square wave comes from the DMA path
SHAPES = ("square", "sine", "triangle", "saw")
CLK = 150000000
TOP = 255                       # DDS carrier: 8 bits, CLK / 256 = 586 kHz
PWM_SLICE = 0x400a8000 + 0x14 * ((OUT_PIN >> 1) & 7)    # CSR, DIV, CTR, CC, TOP (RP2350A)
PWM_CC = PWM_SLICE + 0x0C       # 16-bit DMA writes land in both A and B
DMA_TIMER0 = 0x50000440         # X << 16 | Y (RP2350; 0x420 on the RP2040)
DREQ_DMA_TIMER0 = 59
NMAX = 4096                     # samples in a wave table (16 bit -> 8 KB ring)
LED_MAX = 0.35                  # LED brightness at 100 % duty (full is blinding)

uart = UART(0, baudrate=115200, tx=Pin(0), rx=Pin(1), rxbuf=2048)
usb = select.poll()
usb.register(sys.stdin, select.POLLIN)
leds = [PWM(Pin(p), freq=1000, duty_u16=65535) for p in (18, 19, 20)]  # R G B, active low
pwm = PWM(Pin(OUT_PIN), freq=1000, duty_u16=32768)
dma = rp2.DMA()
state = {"shape": "square", "freq": 1000, "duty": 50.0, "on": True}

# the DMA ring has to sit on an address aligned to its size
_ring_mem = bytearray(4 * NMAX)
RING = (uctypes.addressof(_ring_mem) + 2 * NMAX - 1) & ~(2 * NMAX - 1)
ring = uctypes.bytearray_at(RING, 2 * NMAX)


def limits():
    return (SQ_FMIN, SQ_FMAX) if state["shape"] == "square" else (DDS_FMIN, DDS_FMAX)


def hsv(h, v):
    h = (h % 360) / 60
    i, f = int(h), h - int(h)
    p, q, t = 0, v * (1 - f), v * f
    return [(v, t, p), (q, v, p), (p, v, t), (p, q, v), (t, p, v), (v, p, q)][i % 6]


def show():
    if not state["on"]:
        rgb = (0, 0, 0)
    else:
        pos = math.log10(max(state["freq"], 2) / 2) / math.log10(1000000 / 2)
        duty = state["duty"] if state["shape"] == "square" else 50
        rgb = hsv(270 * min(pos, 1), LED_MAX * duty / 100)
    for led, c in zip(leds, rgb):
        led.duty_u16(65535 - int(65535 * c))


def ratio(r, limit=65535):
    """Best X / Y (both <= limit) for r < 1: continued fractions."""
    best, h0, h1, k0, k1, x = (0, 1), 0, 1, 1, 0, r
    while True:
        a = int(x)
        h0, h1 = h1, a * h1 + h0
        k0, k1 = k1, a * k1 + k0
        if h1 > limit or k1 > limit:
            break
        best = (h1, k1)
        if x == a:
            break
        x = 1 / (x - a)
    return best


def stop_dma():
    dma.active(0)  # pauses the endless transfer; start_dds() re-arms it from the table start


def log2(n):
    k = 0
    while 1 << k < n:
        k += 1
    return k


def start_dds(level, freq):
    """DMA the wave table into the PWM duty, paced by the DMA timer."""
    stop_dma()
    pwm.init(freq=CLK // (TOP + 1), duty_u16=0)
    mem32[PWM_SLICE + 0x04] = 1 << 4        # DIV 1.0
    mem32[PWM_SLICE + 0x10] = TOP
    # table length: a power of two, as long as the DMA timer (<= CLK) can play it
    n = NMAX
    while n > 16 and n * freq > CLK / 2:
        n //= 2
    x, y = ratio(n * freq / CLK)
    if x == 0:
        raise ValueError("frequency too low")
    buf = array.array("H", (min(TOP + 1, round((TOP + 1) * level(i / n))) for i in range(n)))
    ring[:2 * n] = bytes(buf)
    mem32[DMA_TIMER0] = x << 16 | y
    ctrl = dma.pack_ctrl(size=1, inc_read=True, inc_write=False, ring_size=log2(2 * n),
                         ring_sel=False, treq_sel=DREQ_DMA_TIMER0)
    dma.config(read=RING, write=PWM_CC, count=1, ctrl=ctrl, trigger=False)
    dma.registers[2] = 0xF0000001           # TRANS_COUNT mode ENDLESS (RP2350)
    dma.registers[3] = ctrl                 # CTRL_TRIG: go
    return n, x, y


def apply():
    f, shape = state["freq"], state["shape"]
    if not state["on"]:
        stop_dma()
        pwm.duty_u16(0)
    elif shape == "square" and f >= SQ_PWM_MIN:
        stop_dma()
        pwm.init(freq=f, duty_u16=round(65535 * state["duty"] / 100))
    else:
        d = state["duty"] / 100
        level = {"square": lambda t: 1 if t < d else 0,
                 "sine": lambda t: 0.5 + 0.5 * math.sin(2 * math.pi * t),
                 "triangle": lambda t: 2 * t if t < 0.5 else 2 - 2 * t,
                 "saw": lambda t: t}[shape]
        start_dds(level, f)
    show()


def probe():
    """Read the output back (the pad input works on an output too): mean level per 0.1 s."""
    pin = Pin(OUT_PIN)
    mem32[0x40038000 + 4 + 4 * OUT_PIN] |= 1 << 6   # PADS_BANK0: input enable
    out = []
    for _ in range(10):
        hi = n = 0
        end = time.ticks_add(time.ticks_us(), 100000)
        while time.ticks_diff(end, time.ticks_us()) > 0:
            hi += pin.value()
            n += 1
        out.append("%d" % (100 * hi // max(n, 1)))
    return "ok probe " + " ".join(out)


def number(s):
    s = s.strip().lower()
    mult = {"k": 1000, "m": 1000000}.get(s[-1:], 1)
    return float(s[:-1] if mult > 1 else s) * mult


def status():
    lo, hi = limits()
    return "ok board=rp2350 shape=%s freq=%d duty=%g out=%s fmin=%d fmax=%d" % (
        state["shape"], state["freq"], state["duty"], "on" if state["on"] else "off", lo, hi)


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
            return "reset"
        if cmd == "probe":
            return probe()
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
    except Exception as e:
        state.update(old)
        apply()
        return "err %s" % e


class Stream:
    """A line-based command channel: the UART or the USB console."""

    def __init__(self, read, write, avail):
        self.read, self.write, self.avail = read, write, avail
        self.buf = b""

    def receive(self, name, size, head):
        """put: take the whole file into RAM first - writing the flash stalls the CPU long
        enough for the UART FIFO to overflow - then store it via a temporary file."""
        if size > 200000:
            return "err put: file too big"
        data = bytearray(size)
        head = head[:size]
        data[:len(head)] = head
        got, end = len(head), time.ticks_add(time.ticks_ms(), 10000 + size // 5)
        while got < size and time.ticks_diff(end, time.ticks_ms()) > 0:
            if self.avail():
                chunk = self.read(size - got)
                if chunk:
                    data[got:got + len(chunk)] = chunk
                    got += len(chunk)
            else:
                time.sleep_ms(1)
        if got != size:
            return "err put: got %d of %d bytes" % (got, size)
        tmp = name + ".new"
        with open(tmp, "wb") as f:
            f.write(data)
        try:
            os.remove(name)
        except OSError:
            pass
        os.rename(tmp, name)
        return "ok put %s %d" % (name, size)

    def poll(self):
        n = 0
        while n < 256 and self.avail():
            data = self.read(256)
            if not data:
                break
            self.buf += data
            n += len(data)
        while b"\n" in self.buf:
            line, self.buf = self.buf.split(b"\n", 1)
            words = line.decode("utf-8", "replace").split()
            if len(words) == 3 and words[0] == "put":
                try:
                    reply = self.receive(words[1], int(words[2]), self.buf)
                except Exception as e:
                    reply = "err put: %s" % e
                self.buf = b""
            else:
                reply = command(line.decode("utf-8", "replace").strip())
            if reply == "reset":
                self.write(b"ok reset\n")
                time.sleep_ms(50)
                machine.reset()
            if reply:
                self.write(reply.encode() + b"\n")


def usb_read(n):
    return sys.stdin.buffer.read(1)  # one byte at a time: never blocks after poll()


streams = [Stream(lambda n: uart.read(min(n, uart.any())), uart.write, uart.any),
           Stream(usb_read, sys.stdout.buffer.write, lambda: usb.poll(0))]

apply()
while True:
    for s in streams:
        s.poll()
    time.sleep_ms(1)
