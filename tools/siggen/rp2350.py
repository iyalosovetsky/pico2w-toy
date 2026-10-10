# pico2w-toy: signal generator on a Pimoroni Tiny 2350 (RP2350), driven from the Zero 2 W.
#
# Commands come over UART0 (GP0 TX -> Zero GPIO 15, GP1 RX <- Zero GPIO 14, /dev/serial0,
# 115200 8N1) or over USB (/dev/ttyACM0).
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
#   power        whether the board dozes (48 MHz after 30 s idle with the output off); doze - now
#   adc          voltages on GP26-GP29 (ADC0-3; GP26 = the PicoCalc's J703.7), 64-sample mean
#   scope <rate> [level]   oscilloscope on GP26: 256 8-bit samples at <rate> samples/s
#                (500 .. 500 k; each sample is the mean of the ~500 k/s conversions in its
#                interval), lined up on a rising edge through <level> volts (default 1.65)
#                if there is one; answers
#                "ok scope rate=.. n=256 trig=1|0 data=<hex>", 0..255 = 0..3.3 V
#   logic <rate> [ch]   logic analyzer on the J703 lines (bit 0..5 = J703.2..7 = GP6 GP3 GP4 GP5
#                GP2 GP26): 512 samples at <rate> (2.5 k .. 25 M samples/s, a PIO state machine +
#                DMA), lined up on a rising edge of channel <ch> (0..5, default 0) if there is
#                one; answers "ok logic rate=.. n=512 trig=1|0 data=<hex, a byte per sample>"
#   decode uart <baud> [pin] [test] | decode i2c [test] | decode spi <mode 0-3> [test]
#                protocol decoder on the J703 lines: waits (2 s) for the first falling edge -
#                UART start bit on <pin> (GPIO, default GP4 = J703.4), I2C SDA (GP4 = J703.4,
#                SCL GP5 = J703.5), SPI CS (GP5; SCK GP2, MOSI GP3, MISO GP4) - captures 32768
#                samples with PIO + DMA and decodes them; "test" makes the board send its own
#                UART / I2C / SPI traffic on those pins meanwhile. Answers "ok decode <proto>
#                <tokens>" (UART: hex bytes; I2C: S, addr:W/R, bytes, A/N, P; SPI: mosi/miso
#                per byte, | between CS frames) or "ok decode <proto> none"
#   lcd <model> [all|colors|bars|grid|text] [w=.. h=.. x=.. y=.. r=0|90|180|270]   display
#                tester on J703 (w / h: the panel size, x / y: the window offset - in the
#                controller's portrait frame, instead of the model's; r: rotation; b: TFT
#                backlight 0..100 % on J703.2)
#   bl <0..100>  TFT backlight brightness on J703.2 (PWM; the generator output goes off): SPI SCK .6 MOSI .3 CS .5
#                DC .4 RST .7 (e-Paper BUSY .2), I2C SDA .4 SCL .5; models: st7789-240x240,
#                -240x320, -135x240, -170x320, -172x320, -240x280, ili9341, ili9488, epd7in5v2,
#                ssd1306-128x64, ssd1306-128x32, sh1106
#   put <file> <bytes>   answers "ok send", then takes that many raw bytes: replaces a file
#                        (program updates over the UART: siggen flash)
import array
import binascii
import math
import micropython
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

uart = UART(0, baudrate=115200, tx=Pin(0), rx=Pin(1), rxbuf=2048, txbuf=1024)
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


ADCS = [machine.ADC(Pin(p)) for p in (26, 27, 28, 29)]


_adc_pins_taken = [False]   # the display tester drives GP26 (RST): back to analog before measuring


def adc_ready():
    if _adc_pins_taken[0]:
        ADCS[0] = machine.ADC(Pin(26))
        _adc_pins_taken[0] = False


def adc():
    """Mean of 64 readings per ADC input, in volts (3.3 V reference)."""
    adc_ready()
    out = []
    for p, a in zip((26, 27, 28, 29), ADCS):
        total = 0
        for _ in range(64):
            total += a.read_u16()
        out.append("gp%d=%.3f" % (p, total / 64 * 3.3 / 65535))
    return "ok adc " + " ".join(out)


ADC_BASE = 0x400a0000          # CS, RESULT, FCS, FIFO, DIV
SCOPE_N = 256
_scope = bytearray(2 * SCOPE_N)


@micropython.viper
def _capture(buf: ptr8, n: int, k: int):
    """n samples from the ADC FIFO (8 bit), each the mean of k conversions. Takes everything
    the FIFO holds at each look, so the loop keeps up with 500 k conversions/s."""
    fcs = ptr32(0x400a0008)
    fifo = ptr32(0x400a000c)
    i = 0
    acc = 0
    j = 0
    while i < n:
        lvl = (fcs[0] >> 16) & 0xF
        while lvl > 0 and i < n:
            acc += fifo[0] & 0xFF
            lvl -= 1
            j += 1
            if j == k:
                buf[i] = acc // k
                i += 1
                acc = 0
                j = 0


def scope(rate, level=1.65):
    rate = float(rate)
    if not 500 <= rate <= 500000:
        return "err scope rate 500..500000"
    # "high-res": the ADC runs near its 500 k/s and every point is the mean of the conversions
    # in its interval - an anti-alias filter that also smooths the DDS shapes' 586 kHz PWM
    k = max(1, int(500000 / rate))
    adc_ready()
    ADCS[0].read_u16()                         # GP26 set up as an analog input
    mem32[ADC_BASE] = 1                        # EN, AINSEL 0 = GP26
    while not mem32[ADC_BASE] & 0x100:
        pass
    mem32[ADC_BASE + 8] = 1 | 2 | 3 << 10      # FIFO on, 8-bit results, clear under/overflow
    while mem32[ADC_BASE + 8] & 0xF << 16:
        mem32[ADC_BASE + 0xC]
    d = 48000000 / (rate * k) - 1
    mem32[ADC_BASE + 0x10] = int(d) << 8 | int((d - int(d)) * 256)
    mem32[ADC_BASE] = 1 | 8                    # START_MANY
    _capture(_scope, 2 * SCOPE_N, k)
    mem32[ADC_BASE] = 1
    while not mem32[ADC_BASE] & 0x100:
        pass
    over = mem32[ADC_BASE + 8] >> 11 & 1
    mem32[ADC_BASE + 8] = 3 << 10
    while mem32[ADC_BASE + 8] & 0xF << 16:
        mem32[ADC_BASE + 0xC]
    mem32[ADC_BASE + 8] = 0
    mem32[ADC_BASE + 0x10] = 0
    # trigger: the first rising crossing of the level, with 1/8 of the window before it
    lv = int(level / 3.3 * 255)
    pre = SCOPE_N // 8
    start, trig = 0, 0
    for i in range(pre + 1, SCOPE_N + pre):
        if _scope[i - 1] < lv <= _scope[i]:
            start, trig = i - pre, 1
            break
    data = binascii.hexlify(_scope[start:start + SCOPE_N]).decode()
    return "ok scope rate=%g n=%d trig=%d over=%d data=%s" % (rate, SCOPE_N, trig, over, data)


LOGIC_PINS = (6, 3, 4, 5, 2, 26)   # J703.2 .. J703.7
LOGIC_N = 512
_logic = array.array("I", [0] * (2 * LOGIC_N))
_logic_out = bytearray(LOGIC_N)
PIO1_RXF0 = 0x50300020
DREQ_PIO1_RX0 = 12


@rp2.asm_pio(in_shiftdir=rp2.PIO.SHIFT_LEFT, autopush=True, push_thresh=32, fifo_join=rp2.PIO.JOIN_RX)
def _la_prog():
    in_(pins, 32)


@micropython.viper
def _pack(src: ptr32, dst: ptr8, start: int, n: int):
    """The six J703 lines of each sampled GPIO word into a byte (bit 0 = J703.2)."""
    i = 0
    while i < n:
        w = src[start + i]
        dst[i] = ((w >> 6) & 1) | ((w >> 2) & 2) | ((w >> 2) & 4) | ((w >> 2) & 8) | ((w << 2) & 16) | ((w >> 21) & 32)
        i += 1


def logic(rate, ch=0):
    rate = float(rate)
    if not 2500 <= rate <= 25000000:     # the PIO clock divider stops at 150 MHz / 65536
        return "err logic rate 2500..25000000"
    if not 0 <= ch < len(LOGIC_PINS):
        return "err logic channel 0..5"
    for p in LOGIC_PINS:            # inputs readable: our own output (GP6) keeps driving
        if p != OUT_PIN:
            Pin(p, Pin.IN)
        mem32[0x40038000 + 4 + 4 * p] = (mem32[0x40038000 + 4 + 4 * p] | 1 << 6) & ~(1 << 8)  # IE on, ISO off
    sm = rp2.StateMachine(4, _la_prog, freq=int(rate), in_base=Pin(0))
    dma2 = rp2.DMA()
    try:
        ctrl = dma2.pack_ctrl(size=2, inc_read=False, inc_write=True, treq_sel=DREQ_PIO1_RX0)
        dma2.config(read=PIO1_RXF0, write=_logic, count=2 * LOGIC_N, ctrl=ctrl, trigger=True)
        sm.active(1)
        end = time.ticks_add(time.ticks_ms(), int(2 * LOGIC_N / rate * 1000) + 500)
        while dma2.active() and time.ticks_diff(end, time.ticks_ms()) > 0:
            pass
        done = not dma2.active()
    finally:
        sm.active(0)
        dma2.active(0)
        dma2.close()
    if not done:
        return "err logic: capture timed out"
    # trigger: the first rising edge of the channel, with 1/8 of the window before it
    pre, bit, start, trig = LOGIC_N // 8, 1 << LOGIC_PINS[ch], 0, 0
    for i in range(pre + 1, LOGIC_N + pre):
        if not _logic[i - 1] & bit and _logic[i] & bit:
            start, trig = i - pre, 1
            break
    _pack(_logic, _logic_out, start, LOGIC_N)
    return "ok logic rate=%g n=%d trig=%d data=%s" % (rate, LOGIC_N, trig, binascii.hexlify(_logic_out).decode())


DEC_WORDS = 8192                 # x 4 samples (8 lines, GP0-7, a byte each)
_dec = array.array("I", [0] * DEC_WORDS)
_dec_b = uctypes.bytearray_at(uctypes.addressof(_dec), 4 * DEC_WORDS)
_dec_progs = {}
_edges = array.array("I", [0] * 4096)


def _dec_prog(pin):
    """Wait for <pin> to go low, then sample GP0-7 every cycle (1 byte per sample)."""
    if pin not in _dec_progs:
        @rp2.asm_pio(in_shiftdir=rp2.PIO.SHIFT_RIGHT, autopush=True, push_thresh=32,
                     fifo_join=rp2.PIO.JOIN_RX)
        def prog():
            wait(0, gpio, pin)
            wrap_target()
            in_(pins, 8)
            wrap()
        _dec_progs[pin] = prog
    return _dec_progs[pin]


@micropython.viper
def _find_edges(buf: ptr8, n: int, mask: int, out: ptr32, cap: int) -> int:
    """Indexes where (sample & mask) changes; returns how many (at most cap)."""
    k = 0
    prev = buf[0] & mask
    i = 1
    while i < n and k < cap:
        v = buf[i] & mask
        if v != prev:
            out[k] = i
            k += 1
            prev = v
        i += 1
    return k


def _capture_decode(trig_pin, rate, traffic):
    for p in (2, 3, 4, 5):
        Pin(p, Pin.IN)
        mem32[0x40038000 + 4 + 4 * p] = (mem32[0x40038000 + 4 + 4 * p] | 1 << 6) & ~(1 << 8)
    sm = rp2.StateMachine(4, _dec_prog(trig_pin), freq=int(rate), in_base=Pin(0))
    dma2 = rp2.DMA()
    try:
        ctrl = dma2.pack_ctrl(size=2, inc_read=False, inc_write=True, treq_sel=DREQ_PIO1_RX0)
        dma2.config(read=PIO1_RXF0, write=_dec, count=DEC_WORDS, ctrl=ctrl, trigger=True)
        sm.active(1)
        if traffic:
            traffic()
        end = time.ticks_add(time.ticks_ms(), 2000 + int(4 * DEC_WORDS / rate * 1000))
        while dma2.active() and time.ticks_diff(end, time.ticks_ms()) > 0:
            pass
        words = DEC_WORDS - (dma2.count if dma2.active() else 0)
    finally:
        sm.active(0)
        dma2.active(0)
        dma2.close()
        for p in (2, 3, 4, 5):
            Pin(p, Pin.IN)
    return 4 * words


def _uart_traffic(baud, pin):
    def go():
        time.sleep_ms(2)
        u = UART(1, baudrate=baud, tx=Pin(pin))
        u.write(b"Hi PicoCalc!")
        u.flush()
        time.sleep_ms(2)
        u.deinit()
    return go


def _i2c_traffic():
    from machine import I2C
    i2c = I2C(0, sda=Pin(4), scl=Pin(5), freq=100000)
    for p in (4, 5):  # no pull-ups on the J703 lines: use the internal ones
        mem32[0x40038000 + 4 + 4 * p] = (mem32[0x40038000 + 4 + 4 * p] | 1 << 3) & ~(1 << 2)
    try:
        i2c.writeto(0x3C, b"\x00\xAF")
    except OSError:
        pass
    try:
        i2c.readfrom(0x50, 2)
    except OSError:
        pass


def _spi_traffic(mode):
    from machine import SPI
    cs = Pin(5, Pin.OUT, value=1)
    spi = SPI(0, baudrate=500000, polarity=mode >> 1, phase=mode & 1, sck=Pin(2), mosi=Pin(3), miso=Pin(4))
    rx = bytearray(4)
    for frame in (b"\xA5\x5A\x01\x02", b"\x9F\x00\x00\x00"):
        cs(0)
        spi.write_readinto(frame, rx)
        cs(1)
        time.sleep_us(20)
    spi.deinit()


def _bit(n, t, b):
    return _dec_b[t] >> b & 1 if t < n else 1


def _dec_uart(n, baud, pin, rate):
    period = rate / baud
    out, t = [], 0
    nedge = _find_edges(_dec_b, n, 1 << pin, _edges, len(_edges))
    e = 0
    # the capture starts on the start bit itself
    starts = [0]
    while starts and len(out) < 200:
        t0 = starts.pop()
        if t0 + 10 * period >= n:
            break
        v = 0
        for i in range(8):
            v |= _bit(n, int(t0 + (1.5 + i) * period), pin) << i
        out.append("%02X" % v if _bit(n, int(t0 + 9.5 * period), pin) else "%02X!" % v)
        # next start bit: the first falling edge after the stop bit
        after = t0 + 9.5 * period
        while e < nedge and (_edges[e] < after or _dec_b[_edges[e]] >> pin & 1):
            e += 1
        if e < nedge:
            starts.append(_edges[e])
    return out


def _dec_i2c(n):
    SDA, SCL = 4, 5
    nedge = _find_edges(_dec_b, n, 1 << SDA | 1 << SCL, _edges, len(_edges))
    out, bits, pv = ["S"], [], _dec_b[0]
    for k in range(nedge):
        t = _edges[k]
        v = _dec_b[t]
        sda, scl = v >> SDA & 1, v >> SCL & 1
        psda, pscl = pv >> SDA & 1, pv >> SCL & 1
        if scl and pscl and sda != psda:          # SDA changed while SCL high: START / STOP
            out.append("P" if sda else ("S" if out and out[-1] == "P" else "Sr"))
            bits = []
        elif scl and not pscl:                    # SCL rising: a data bit
            bits.append(sda)
            if len(bits) == 9:
                b = 0
                for x in bits[:8]:
                    b = b << 1 | x
                first = len(out) and out[-1] in ("S", "Sr")
                out.append(("%02X:%s" % (b >> 1, "R" if b & 1 else "W")) if first else "%02X" % b)
                out.append("N" if bits[8] else "A")
                bits = []
        pv = v
        if len(out) > 200:
            break
    return out


def _dec_spi(n, mode):
    SCK, MOSI, MISO, CS = 2, 3, 4, 5
    nedge = _find_edges(_dec_b, n, 1 << SCK | 1 << CS, _edges, len(_edges))
    sample_rising = mode in (0, 3)
    out, mo, mi, cnt, pv = [], 0, 0, 0, _dec_b[0]
    for k in range(nedge):
        t = _edges[k]
        v = _dec_b[t]
        if v >> CS & 1 and not pv >> CS & 1:      # CS released: end of a frame
            out.append("|")
            cnt = mo = mi = 0
        elif not v >> CS & 1:
            sck, psck = v >> SCK & 1, pv >> SCK & 1
            if sck != psck and (sck == 1) == sample_rising:
                mo = mo << 1 | (v >> MOSI & 1)
                mi = mi << 1 | (v >> MISO & 1)
                cnt += 1
                if cnt == 8:
                    out.append("%02X/%02X" % (mo, mi))
                    cnt = mo = mi = 0
        pv = v
        if len(out) > 200:
            break
    return out


def decode(args):
    proto = args[0].lower() if args else ""
    test = "test" in args
    args = [a for a in args[1:] if a != "test"]
    if proto == "uart":
        baud = int(number(args[0])) if args else 9600
        pin = int(args[1]) if len(args) > 1 else 4
        if not 300 <= baud <= 1000000 or pin not in (2, 3, 4, 5):
            return "err decode uart <baud 300..1M> [pin 2-5]"
        if test and pin != 4:
            return "err decode uart test: the board sends on GP4 only (UART1 TX)"
        rate = min(16 * baud, 25000000)
        n = _capture_decode(pin, rate, _uart_traffic(baud, pin) if test else None)
        out = _dec_uart(n, baud, pin, rate) if n else []
    elif proto == "i2c":
        rate = 4000000
        n = _capture_decode(4, rate, _i2c_traffic if test else None)
        out = _dec_i2c(n) if n else []
    elif proto == "spi":
        mode = int(args[0]) if args else 0
        if mode not in (0, 1, 2, 3):
            return "err decode spi <mode 0-3>"
        rate = 10000000
        n = _capture_decode(5, rate, (lambda: _spi_traffic(mode)) if test else None)
        out = _dec_spi(n, mode) if n else []
    else:
        return "err decode uart|i2c|spi"
    return "ok decode %s %s" % (proto, " ".join(out) if out else "none")


# ---------------------------------------------------------------- display tester
# Wiring on J703: SPI SCK GP2 (.6), MOSI GP3 (.3), CS GP5 (.5), DC GP4 (.4), RST GP26 (.7),
# TFT backlight BL GP6 (.2, PWM) / e-Paper BUSY GP6 - the generator output, switched off for them;
# I2C SDA GP4 (.4), SCL GP5 (.5).
D_SCK, D_MOSI, D_CS, D_DC, D_RST, D_BUSY, D_SDA, D_SCL, D_BL = 2, 3, 5, 4, 26, 6, 4, 5, 6


def backlight(percent):
    """TFT backlight on J703.2: a 1 kHz PWM on the generator's pin (the generator goes off)."""
    if state["on"]:
        state["on"] = False
        apply()
    pwm.init(freq=1000, duty_u16=round(65535 * min(100, max(0, percent)) / 100))
    show()

# model -> (driver, width, height, x offset, y offset)
DISPLAYS = {
    "st7789-240x240": ("st7789", 240, 240, 0, 0),
    "st7789-240x320": ("st7789", 240, 320, 0, 0),
    "st7789-135x240": ("st7789", 135, 240, 52, 40),
    "st7789-170x320": ("st7789", 170, 320, 35, 0),
    "st7789-172x320": ("st7789", 172, 320, 34, 0),
    "st7789-240x280": ("st7789", 240, 280, 0, 20),
    "ili9341": ("ili9341", 240, 320, 0, 0),
    "ili9488": ("ili9488", 320, 480, 0, 0),
    "epd7in5v2": ("epd", 800, 480, 0, 0),
    "ssd1306-128x64": ("ssd1306", 128, 64, 0, 0),
    "ssd1306-128x32": ("ssd1306", 128, 32, 0, 0),
    "sh1106": ("sh1106", 128, 64, 2, 0),
}
PATTERNS = ("all", "colors", "bars", "grid", "text")
RGB = {"black": (0, 0, 0), "white": (255, 255, 255), "red": (255, 0, 0), "green": (0, 255, 0),
       "blue": (0, 0, 255), "yellow": (255, 255, 0), "cyan": (0, 255, 255), "magenta": (255, 0, 255)}
BARS = ("white", "yellow", "cyan", "green", "magenta", "red", "blue", "black")

ILI9341_INIT = (
    (0xEF, b"\x03\x80\x02"), (0xCF, b"\x00\xC1\x30"), (0xED, b"\x64\x03\x12\x81"),
    (0xE8, b"\x85\x00\x78"), (0xCB, b"\x39\x2C\x00\x34\x02"), (0xF7, b"\x20"), (0xEA, b"\x00\x00"),
    (0xC0, b"\x23"), (0xC1, b"\x10"), (0xC5, b"\x3E\x28"), (0xC7, b"\x86"), (0x36, b"\x48"),
    (0x37, b"\x00"), (0x3A, b"\x55"), (0xB1, b"\x00\x18"), (0xB6, b"\x08\x82\x27"), (0xF2, b"\x00"),
    (0x26, b"\x01"),
    (0xE0, b"\x0F\x31\x2B\x0C\x0E\x08\x4E\xF1\x37\x07\x10\x03\x0E\x09\x00"),
    (0xE1, b"\x00\x0E\x14\x03\x11\x07\x31\xC1\x48\x08\x0F\x0C\x31\x36\x0F"))
ILI9488_INIT = (
    (0xE0, b"\x00\x03\x09\x08\x16\x0A\x3F\x78\x4C\x09\x0A\x08\x16\x1A\x0F"),
    (0xE1, b"\x00\x16\x19\x03\x0F\x05\x32\x45\x46\x04\x0E\x0D\x35\x37\x0F"),
    (0xC0, b"\x17\x15"), (0xC1, b"\x41"), (0xC5, b"\x00\x12\x80"), (0x36, b"\x48"), (0x3A, b"\x66"),
    (0xB0, b"\x00"), (0xB1, b"\xA0"), (0xB4, b"\x02"), (0xB6, b"\x02\x02"), (0xE9, b"\x00"),
    (0xF7, b"\xA9\x51\x2C\x82"))
SSD1306_INIT = (0xAE, 0xD5, 0x80, 0xA8, None, 0xD3, 0x00, 0x40, 0x8D, 0x14, 0x20, 0x00, 0xA1, 0xC8,
                0xDA, None, 0x81, 0xCF, 0xD9, 0xF1, 0xDB, 0x40, 0xA4, 0xA6, 0xAF)
SH1106_INIT = (0xAE, 0xD5, 0x80, 0xA8, 0x3F, 0xD3, 0x00, 0x40, 0xAD, 0x8B, 0xA1, 0xC8, 0xDA, 0x12,
               0x81, 0x80, 0xD9, 0x22, 0xDB, 0x35, 0xA4, 0xA6, 0xAF)


class Tft:
    """ST7789 / ILI9341 (RGB565) and ILI9488 (RGB666 over SPI) - just enough for test pictures."""

    RAM = {"st7789": (240, 320), "ili9341": (240, 320), "ili9488": (320, 480)}
    # MADCTL for 0 / 90 / 180 / 270 degrees (MY 0x80, MX 0x40, MV 0x20, BGR 0x08)
    MADCTL = {"st7789": {0: 0x00, 90: 0x60, 180: 0xC0, 270: 0xA0},
              "ili9341": {0: 0x48, 90: 0x28, 180: 0x88, 270: 0xE8}}

    def __init__(self, kind, w, h, xo, yo, rot=0):
        """w, h, xo, yo: the panel and its window offset in the controller's portrait frame."""
        from machine import SPI
        rw, rh = self.RAM[kind]
        # the offsets move with the rotation (e.g. a 135x240 at 52/40 becomes 40/53, 53/40, 40/52)
        xo, yo = {0: (xo, yo), 90: (yo, rw - w - xo), 180: (rw - w - xo, rh - h - yo),
                  270: (rh - h - yo, xo)}[rot]
        if rot in (90, 270):
            w, h = h, w
        self.kind, self.w, self.h, self.xo, self.yo = kind, w, h, max(0, xo), max(0, yo)
        self.madctl = self.MADCTL["st7789" if kind == "st7789" else "ili9341"][rot]
        self.bpp = 3 if kind == "ili9488" else 2
        mode = 3 if kind == "st7789" else 0       # CS-less ST7789 modules need mode 3
        self.spi = SPI(0, baudrate=20000000, polarity=mode >> 1, phase=mode & 1,
                       sck=Pin(D_SCK), mosi=Pin(D_MOSI))
        self.cs, self.dc, self.rst = Pin(D_CS, Pin.OUT, value=1), Pin(D_DC, Pin.OUT), Pin(D_RST, Pin.OUT, value=1)
        self.rst(0)
        time.sleep_ms(20)
        self.rst(1)
        time.sleep_ms(150)
        self.cmd(0x01)
        time.sleep_ms(150)
        if kind == "ili9341":
            for c, d in ILI9341_INIT:
                self.cmd(c, d)
        elif kind == "ili9488":
            for c, d in ILI9488_INIT:
                self.cmd(c, d)
        else:
            self.cmd(0x3A, b"\x55")
            self.cmd(0x36, b"\x00")
            self.cmd(0x21)                       # ST7789 panels are inverted
            self.cmd(0x13)
        self.cmd(0x36, bytes((self.madctl,)))
        self.cmd(0x11)
        time.sleep_ms(120)
        self.cmd(0x29)
        time.sleep_ms(20)

    def cmd(self, c, data=None):
        self.cs(0)
        self.dc(0)
        self.spi.write(bytes((c,)))
        if data:
            self.dc(1)
            self.spi.write(data)
        self.cs(1)

    def color(self, name):
        r, g, b = RGB[name]
        if self.bpp == 3:
            return bytes((r & 0xFC, g & 0xFC, b & 0xFC))
        v = (r & 0xF8) << 8 | (g & 0xFC) << 3 | b >> 3
        return bytes((v >> 8, v & 0xFF))

    def window(self, x, y, w, h):
        x0, y0 = x + self.xo, y + self.yo
        self.cmd(0x2A, bytes((x0 >> 8, x0 & 0xFF, (x0 + w - 1) >> 8, (x0 + w - 1) & 0xFF)))
        self.cmd(0x2B, bytes((y0 >> 8, y0 & 0xFF, (y0 + h - 1) >> 8, (y0 + h - 1) & 0xFF)))

    def fill_rect(self, x, y, w, h, name):
        if w <= 0 or h <= 0:
            return
        self.window(x, y, w, h)
        px = self.color(name)
        line = px * w
        self.cs(0)
        self.dc(0)
        self.spi.write(b"\x2C")
        self.dc(1)
        for _ in range(h):
            self.spi.write(line)
        self.cs(1)

    def text(self, s, x, y, scale, fg, bg):
        import framebuf
        w, h = 8 * len(s), 8
        fb = framebuf.FrameBuffer(bytearray(w * h // 8 + 8), w, h, framebuf.MONO_HLSB)
        fb.fill(0)
        fb.text(s, 0, 0, 1)
        fgc, bgc = self.color(fg), self.color(bg)
        self.window(x, y, w * scale, h * scale)
        self.cs(0)
        self.dc(0)
        self.spi.write(b"\x2C")
        self.dc(1)
        for row in range(h):
            line = b"".join((fgc if fb.pixel(col, row) else bgc) * scale for col in range(w))
            for _ in range(scale):
                self.spi.write(line)
        self.cs(1)

    def show(self, pattern, label):
        w, h = self.w, self.h
        if pattern in ("all", "colors"):
            for c in ("red", "green", "blue", "white", "black"):
                self.fill_rect(0, 0, w, h, c)
                time.sleep_ms(350)
        if pattern in ("all", "bars"):
            bw = w // len(BARS)
            for i, c in enumerate(BARS):
                self.fill_rect(i * bw, 0, w - i * bw if i == len(BARS) - 1 else bw, h, c)
            if pattern == "all":
                time.sleep_ms(700)
        if pattern in ("all", "grid"):
            self.fill_rect(0, 0, w, h, "black")
            for x in range(0, w, 20):
                self.fill_rect(x, 0, 1, h, "blue")
            for y in range(0, h, 20):
                self.fill_rect(0, y, w, 1, "blue")
            for x, y, ww, hh in ((0, 0, w, 1), (0, h - 1, w, 1), (0, 0, 1, h), (w - 1, 0, 1, h)):
                self.fill_rect(x, y, ww, hh, "white")      # the border: shows offset errors
            for x, y, c in ((0, 0, "red"), (w - 10, 0, "green"), (0, h - 10, "blue"), (w - 10, h - 10, "yellow")):
                self.fill_rect(x, y, 10, 10, c)            # corners: red TL, green TR, blue BL, yellow BR
        if pattern in ("all", "text"):
            if pattern == "text":
                self.fill_rect(0, 0, w, h, "black")
            sc = max(1, min(3, w // 80))
            for i, (s, c) in enumerate((("PicoCalc", "yellow"), (label, "white"), ("%dx%d" % (w, h), "cyan"))):
                tw = 8 * len(s) * sc
                self.text(s, max(1, (w - tw) // 2), h // 2 - 20 * sc + i * 12 * sc, sc, c, "black")

    def close(self):
        self.spi.deinit()


@micropython.viper
def _rot_hlsb(src: ptr8, sw: int, sh: int, dst: ptr8, dw: int, mode: int):
    """Rotate a MONO_HLSB picture (sw x sh) into dst (dw wide, cleared): mode 1 = 90, 2 = 180,
    3 = 270 degrees."""
    sb = sw >> 3
    db = dw >> 3
    sy = 0
    while sy < sh:
        sx = 0
        while sx < sw:
            if src[sy * sb + (sx >> 3)] & (0x80 >> (sx & 7)):
                if mode == 1:
                    px = sh - 1 - sy
                    py = sx
                elif mode == 2:
                    px = sw - 1 - sx
                    py = sh - 1 - sy
                else:
                    px = sy
                    py = sw - 1 - sx
                dst[py * db + (px >> 3)] |= 0x80 >> (px & 7)
            sx += 1
        sy += 1


class Epd:
    """Waveshare 7.5" e-Paper V2 (800 x 480, UC8179): one full refresh with the test picture."""

    def __init__(self, w, h, rot=0):
        from machine import SPI
        self.w, self.h, self.rot = w, h, rot
        self.spi = SPI(0, baudrate=4000000, polarity=0, phase=0, sck=Pin(D_SCK), mosi=Pin(D_MOSI))
        self.cs, self.dc, self.rst = Pin(D_CS, Pin.OUT, value=1), Pin(D_DC, Pin.OUT), Pin(D_RST, Pin.OUT, value=1)
        self.busy = Pin(D_BUSY, Pin.IN)
        for v, ms in ((1, 20), (0, 2), (1, 20)):
            self.rst(v)
            time.sleep_ms(ms)
        self.cmd(0x01, b"\x07\x07\x3F\x3F")    # power setting
        self.cmd(0x06, b"\x17\x17\x28\x17")    # booster soft start
        self.cmd(0x04)                          # power on
        time.sleep_ms(100)
        self.wait()
        self.cmd(0x00, b"\x1F")                 # panel setting: KW, OTP LUT
        self.cmd(0x61, bytes((w >> 8, w & 0xFF, h >> 8, h & 0xFF)))
        self.cmd(0x15, b"\x00")
        self.cmd(0x50, b"\x10\x07")
        self.cmd(0x60, b"\x22")

    def cmd(self, c, data=None):
        self.cs(0)
        self.dc(0)
        self.spi.write(bytes((c,)))
        if data:
            self.dc(1)
            self.spi.write(data)
        self.cs(1)

    def data(self, buf):
        self.cs(0)
        self.dc(1)
        self.spi.write(buf)
        self.cs(1)

    def wait(self, timeout=30000):
        """BUSY is low while the panel works."""
        end = time.ticks_add(time.ticks_ms(), timeout)
        self.cmd(0x71)
        while not self.busy() and time.ticks_diff(end, time.ticks_ms()) > 0:
            time.sleep_ms(20)
            self.cmd(0x71)
        if not self.busy():
            raise OSError("e-Paper BUSY stuck low")

    def show(self, pattern, label):
        import framebuf
        w, h = (self.h, self.w) if self.rot in (90, 270) else (self.w, self.h)   # as seen
        buf = bytearray(w * h // 8)
        fb = framebuf.FrameBuffer(buf, w, h, framebuf.MONO_HLSB)   # 1 = white
        fb.fill(1)
        if pattern in ("all", "bars", "colors"):
            for i in range(8):
                if i % 2:
                    fb.fill_rect(i * w // 8, 0, w // 8, h // 2 if pattern == "all" else h, 0)
        if pattern in ("all", "grid"):
            for x in range(0, w, 40):
                fb.vline(x, 0, h, 0)
            for y in range(0, h, 40):
                fb.hline(0, y, w, 0)
            fb.rect(0, 0, w, h, 0)
            fb.rect(2, 2, w - 4, h - 4, 0)
        if pattern in ("all", "text"):
            for i, s in enumerate(("PicoCalc display tester", label, "%dx%d" % (w, h))):
                fb.fill_rect(w // 2 - 4 * len(s) - 4, h // 2 - 20 + 16 * i - 3, 8 * len(s) + 8, 14, 1)
                fb.text(s, w // 2 - 4 * len(s), h // 2 - 20 + 16 * i, 0)
        if self.rot:
            panel = bytearray(len(buf))
            _rot_hlsb(buf, w, h, panel, self.w, self.rot // 90)
            buf = panel
        self.cmd(0x10)
        self.data(buf)
        for i in range(len(buf)):
            buf[i] ^= 0xFF
        self.cmd(0x13)
        self.data(buf)
        self.cmd(0x12)                          # refresh
        time.sleep_ms(100)
        self.wait()

    def close(self):
        self.cmd(0x50, b"\xF7")
        self.cmd(0x02)                          # power off
        try:
            self.wait(5000)
        except OSError:
            pass
        self.cmd(0x07, b"\xA5")                 # deep sleep: the picture stays
        self.spi.deinit()


class Oled:
    """SSD1306 (128x64 / 128x32) and SH1106 (128x64, column offset 2) over I2C."""

    def __init__(self, kind, w, h, xo, rot=0):
        from machine import I2C
        self.kind, self.w, self.h, self.xo, self.rot = kind, w, h, xo, rot
        self.i2c = I2C(0, sda=Pin(D_SDA), scl=Pin(D_SCL), freq=400000)
        for p in (D_SDA, D_SCL):   # internal pull-ups help when the module has none
            mem32[0x40038000 + 4 + 4 * p] = (mem32[0x40038000 + 4 + 4 * p] | 1 << 3) & ~(1 << 2)
        found = [a for a in self.i2c.scan() if a in (0x3C, 0x3D)]
        if not found:
            raise OSError("no display at I2C 0x3C / 0x3D (found: %s)" %
                          (" ".join("%02X" % a for a in self.i2c.scan()) or "nothing"))
        self.addr = found[0]
        if kind == "sh1106":
            init = SH1106_INIT
        else:
            init = tuple((0x3F if h == 64 else 0x1F) if i == 4 else (0x12 if h == 64 else 0x02) if i == 15 else c
                         for i, c in enumerate(SSD1306_INIT))
        if rot == 180:   # segment remap A0 instead of A1, COM scan C0 instead of C8
            init = tuple({0xA1: 0xA0, 0xC8: 0xC0}.get(c, c) for c in init)
        for c in init:
            self.i2c.writeto(self.addr, bytes((0x00, c)))

    def flush_view(self, vbuf, vw, vh):
        """The picture as seen; 90 / 270 degrees are turned in software."""
        if self.rot not in (90, 270):
            self.flush(vbuf)
            return
        import framebuf
        vfb = framebuf.FrameBuffer(vbuf, vw, vh, framebuf.MONO_VLSB)
        buf = bytearray(self.w * self.h // 8)
        pfb = framebuf.FrameBuffer(buf, self.w, self.h, framebuf.MONO_VLSB)
        for vy in range(vh):
            for vx in range(vw):
                if vfb.pixel(vx, vy):
                    if self.rot == 90:
                        pfb.pixel(vh - 1 - vy, vx, 1)
                    else:
                        pfb.pixel(vy, vw - 1 - vx, 1)
        self.flush(buf)

    def flush(self, buf):
        pages = self.h // 8
        if self.kind == "sh1106":
            for p in range(pages):
                for c in (0xB0 + p, self.xo & 0x0F, 0x10 | self.xo >> 4):
                    self.i2c.writeto(self.addr, bytes((0x00, c)))
                self.i2c.writeto(self.addr, b"\x40" + buf[p * self.w:(p + 1) * self.w])
        else:
            for c in (0x21, self.xo, self.xo + self.w - 1, 0x22, 0, pages - 1):
                self.i2c.writeto(self.addr, bytes((0x00, c)))
            for i in range(0, len(buf), 64):
                self.i2c.writeto(self.addr, b"\x40" + buf[i:i + 64])

    def show(self, pattern, label):
        import framebuf
        w, h = (self.h, self.w) if self.rot in (90, 270) else (self.w, self.h)   # as seen
        buf = bytearray(w * h // 8 + 8)
        fb = framebuf.FrameBuffer(buf, w, h, framebuf.MONO_VLSB)
        if pattern in ("all", "colors"):
            for v in (1, 0, 1, 0):
                fb.fill(v)
                self.flush_view(buf, w, h)
                time.sleep_ms(300)
        if pattern in ("all", "bars"):
            fb.fill(0)
            for i in range(0, 8, 2):
                fb.fill_rect(i * w // 8, 0, w // 8, h, 1)
            self.flush_view(buf, w, h)
            if pattern == "all":
                time.sleep_ms(600)
        if pattern in ("all", "grid", "text"):
            fb.fill(0)
        if pattern in ("all", "grid"):
            for x in range(0, w, 16):
                fb.vline(x, 0, h, 1)
            for y in range(0, h, 16):
                fb.hline(0, y, w, 1)
            fb.rect(0, 0, w, h, 1)
        if pattern in ("all", "text"):
            for i, s in enumerate(("PicoCalc", label[:w // 8], "%dx%d" % (w, h), "%02X" % self.addr)):
                y = h // 2 - 20 + 10 * i if h >= 64 else 1 + 10 * i
                if y + 8 > h:
                    break
                s = s[:w // 8]
                fb.fill_rect(w // 2 - 4 * len(s) - 1, y - 1, 8 * len(s) + 2, 10, 0)
                fb.text(s, w // 2 - 4 * len(s), y, 1)
        if pattern != "colors":
            self.flush_view(buf, w, h)

    def close(self):
        pass


def lcd_test(args):
    if not args or args[0] not in DISPLAYS:
        return "err lcd <model>: " + " ".join(sorted(DISPLAYS))
    model = args[0]
    opts = dict(a.split("=", 1) for a in args[1:] if "=" in a)
    rest = [a for a in args[1:] if "=" not in a]
    pattern = rest[0] if rest else "all"
    if pattern not in PATTERNS:
        return "err lcd pattern: " + " ".join(PATTERNS)
    kind, w, h, xo, yo = DISPLAYS[model]
    try:   # w= h= x= y=: a panel size / window offset other than the model's default
        w, h = int(opts.get("w", w)), int(opts.get("h", h))
        xo, yo = int(opts.get("x", xo)), int(opts.get("y", yo))
        rot = int(opts.get("r", 0))
    except ValueError:
        return "err lcd: w= h= x= y= r= take numbers"
    if rot not in (0, 90, 180, 270):
        return "err lcd rotation: r=0, 90, 180 or 270"
    limit = {"st7789": (320, 320), "ili9341": (320, 320), "ili9488": (480, 480), "epd": (800, 800),
             "ssd1306": (128, 64), "sh1106": (132, 64)}[kind]
    if not (8 <= w <= limit[0] and 8 <= h <= max(limit) and 0 <= xo < 320 and 0 <= yo < 320):
        return "err lcd size: w 8..%d, h 8..%d, x / y 0..319" % (limit[0], max(limit))
    if kind in ("ssd1306", "sh1106") and h % 8 or kind == "epd" and w % 8:
        return "err lcd size: %s" % ("h - a multiple of 8" if kind != "epd" else "w - a multiple of 8")
    t = time.ticks_ms()
    _adc_pins_taken[0] = True
    try:
        bl = int(opts.get("b", 15))     # a dim backlight unless asked for more
    except ValueError:
        return "err lcd: b= takes 0..100"
    if kind == "epd" and state["on"]:   # BUSY is on the generator's pin
        state["on"] = False
        apply()
    if kind in ("st7789", "ili9341", "ili9488"):
        backlight(bl)
    if kind in ("st7789", "ili9341", "ili9488"):
        d = Tft(kind, w, h, xo, yo, rot)
    elif kind == "epd":
        d = Epd(w, h, rot)
    else:
        d = Oled(kind, w, h, xo, rot)
    try:
        d.show(pattern, model)
    finally:
        d.close()
    extra = (" addr=%02X" % d.addr) if kind in ("ssd1306", "sh1106") else ""
    sw, sh = (h, w) if rot in (90, 270) else (w, h)   # as seen
    return "ok lcd %s %dx%d %s %d ms r=%d%s" % (model, sw, sh, pattern, time.ticks_diff(time.ticks_ms(), t), rot, extra)


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
        if cmd == "power":
            return power_status()
        if cmd == "clocks":              # diagnostics: clk_peri / clk_usb / clk_adc CTRL and DIV
            c = 0x40010000
            return "ok clocks sys=%d %s" % (machine.freq(), " ".join(
                "%s=%08x/%08x" % (n, mem32[c + o], mem32[c + o + 4]) for n, o in (("peri", 0x48), ("usb", 0x60), ("adc", 0x6C))))
        if cmd == "doze":                # for testing: doze now
            doze()
            return power_status()
        if cmd == "get":
            return status()
        if cmd == "reset":
            return "reset"
        if cmd == "probe":
            return probe()
        if cmd == "adc":
            return adc()
        if cmd == "lcd":
            return lcd_test(args)
        if cmd == "bl" and len(args) == 1:
            backlight(int(number(args[0])))
            return "ok bl %d" % int(number(args[0]))
        if cmd == "decode":
            return decode(args)
        if cmd == "logic" and 1 <= len(args) <= 2:
            return logic(number(args[0]), int(args[1]) if len(args) > 1 else 0)
        if cmd == "scope" and 1 <= len(args) <= 2:
            return scope(number(args[0]), float(args[1]) if len(args) > 1 else 1.65)
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
                # handshake: the sender waits for "ok send", so the file never arrives before
                # this line was understood (and its lines are never taken as commands)
                self.write(b"ok send\n")
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


def uart_write(data):
    """uart.write() takes only what fits in the TX buffer: write until all of it went out."""
    mv, sent = memoryview(data), 0
    while sent < len(data):
        sent += uart.write(mv[sent:]) or 0


def usb_read(n):
    return sys.stdin.buffer.read(1)  # one byte at a time: never blocks after poll()


streams = [Stream(lambda n: uart.read(min(n, uart.any())), uart_write, uart.any),
           Stream(usb_read, sys.stdout.buffer.write, lambda: usb.poll(0))]

# ---------------------------------------------------------------- saving power when idle
# After IDLE_MS without a command, with the generator output off, the board slows its clock to
# DOZE_HZ and polls less often; any command brings 150 MHz back (the output's PWM / DMA timing
# needs it, so with the output on the board never dozes).
IDLE_MS, DOZE_HZ = 30000, 48000000
power = {"dozing": False, "last": time.ticks_ms()}


def wake():
    power["last"] = time.ticks_ms()
    if power["dozing"]:
        machine.freq(CLK)
        power["dozing"] = False


def doze():
    if not power["dozing"] and not state["on"]:
        machine.freq(DOZE_HZ)
        power["dozing"] = True


def power_status():
    return "ok power dozing=%d freq=%d idle_after=%d s" % (power["dozing"], machine.freq(), IDLE_MS // 1000)


apply()
while True:
    for s in streams:
        if s.avail():
            wake()
            s.poll()
    if not power["dozing"] and time.ticks_diff(time.ticks_ms(), power["last"]) > IDLE_MS:
        doze()
    time.sleep_ms(10 if power["dozing"] else 1)
