"""SDR: a radio receiver for an RTL2832U stick (RTL-SDR Blog V4 and others) - spectrum, waterfall,
WFM / NFM / AM / USB / LSB demodulation to the speaker.

rtl_tcp (from the rtl-sdr package) owns the stick; this app talks to it over a local socket, so
retuning, gain and the sample rate change at once. The DSP is numpy: 240 k samples/s IQ ->
channel filter -> demodulator -> 48 kHz audio (aplay); the "wide" view runs the stick at
2.048 M samples/s for a 2 MHz spectrum without audio.

Keys: UP / DOWN - parameter (frequency, mode, step, gain, volume, squelch, view, memory),
LEFT / RIGHT - change it (held: repeats; on "frequency" it tunes by the step), digits and "." +
Enter - frequency in MHz, Enter - sound on / off, + / - - volume, s - remember the station,
Del - forget it (on "memory"), Esc - exit. HAT: KEY1 / KEY2 - tune up / down, PRESS - sound,
KEY3 - exit.
"""
import json
import math
import os
import queue
import shutil
import socket
import struct
import subprocess
import sys
import threading
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
os.environ["LCD_SOUND"] = "0"   # the speaker goes to aplay; pygame must not hold the sound card

import numpy as np  # noqa: E402
import pygame  # noqa: E402
import lcd  # noqa: E402


def free_port():
    """A free local TCP port: never talk to an rtl_tcp left over from something else."""
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port

SR_NARROW, SR_WIDE = 240000, 2048000
AUDIO_SR = 48000
CHUNK_S = 0.05
OFFSET = 60000            # narrow modes: the stick is tuned this much above, away from its DC spike
FMIN, FMAX = 0.5e6, 1766e6
STATE_FILE = os.path.expanduser("~/.config/lcdtoy/sdr.json")
GAINS = [0, 9, 14, 27, 37, 77, 87, 125, 144, 157, 166, 197, 207, 229, 254, 280, 297, 328, 338, 364, 372,
         386, 402, 421, 434, 439, 445, 480, 496]     # R820T / R828D, tenths of dB; index -1 = auto
MODES = ["WFM", "NFM", "AM", "USB", "LSB"]
STEPS = [100, 1000, 5000, 8333, 10000, 12500, 25000, 100000, 1000000]
SQUELCH = [0, 3, 6, 10, 15, 20]               # dB above the noise floor; 0 = open
PRESETS = [   # (name, Hz, mode, step)
    ("FM 101.5", 101.5e6, "WFM", 100000), ("FM 94.5", 94.5e6, "WFM", 100000),
    ("Авіа 118-137", 124.0e6, "AM", 25000), ("PMR446 к1", 446.00625e6, "NFM", 12500),
    ("LPD 433 к1", 433.075e6, "NFM", 25000), ("2 м 145.500", 145.5e6, "NFM", 12500),
    ("70 см 433.500", 433.5e6, "NFM", 12500), ("Морський 16", 156.8e6, "NFM", 25000),
    ("NOAA 137.1", 137.1e6, "WFM", 10000), ("CB 27.135", 27.135e6, "AM", 10000),
    ("40 м 7.100", 7.1e6, "LSB", 1000), ("20 м 14.200", 14.2e6, "USB", 1000),
    ("ADS-B 1090", 1090e6, "AM", 100000),
]
PARAMS = ["Частота", "Режим", "Крок", "Підсилення", "Гучність", "Шумодав", "Огляд", "Пам'ять"]
P_FREQ, P_MODE, P_STEP, P_GAIN, P_VOL, P_SQ, P_VIEW, P_MEM = range(8)

BG, FG, DIM = (0, 0, 0), (235, 235, 235), (140, 140, 140)
ACCENT, RED, GREEN, BLUE = (255, 200, 0), (240, 90, 80), (90, 220, 110), (110, 170, 255)
FONT_DIR = "/usr/share/fonts/truetype/dejavu/"


# ---------------------------------------------------------------- DSP blocks

def lowpass(cutoff, fs, n):
    k = np.arange(n) - (n - 1) / 2
    h = np.sinc(2 * cutoff / fs * k) * np.hamming(n)
    return (h / h.sum()).astype(np.float32)


class Fir:
    """FIR filter (+ decimation) that keeps its state between chunks."""

    def __init__(self, taps, decim=1, dtype=np.complex64):
        self.taps, self.decim = taps, decim
        self.hist = np.zeros(len(taps) - 1, dtype)
        self.phase = 0

    def __call__(self, x):
        xx = np.concatenate((self.hist, x))
        self.hist = xx[len(xx) - len(self.taps) + 1:]
        y = np.convolve(xx, self.taps, "valid")
        if self.decim > 1:
            y = y[self.phase::self.decim]
            self.phase = (self.phase - len(x)) % self.decim
        return y


class Mixer:
    """Multiply by exp(j 2 pi f t), with the phase carried between chunks."""

    def __init__(self, f, fs):
        self.w, self.ph = 2 * math.pi * f / fs, 0.0

    def __call__(self, x):
        if not self.w:
            return x
        n = np.arange(len(x))
        y = x * np.exp(1j * (self.ph + self.w * n)).astype(np.complex64)
        self.ph = (self.ph + self.w * len(x)) % (2 * math.pi)
        return y


class Demod:
    """One mode's chain: IQ at SR_NARROW (signal at baseband offset fb) -> 48 kHz float audio."""

    def __init__(self, mode, fb):
        self.mode = mode
        dec = SR_NARROW // AUDIO_SR
        self.mix = Mixer(-fb, SR_NARROW)
        self.prev = 0j
        self.agc = 0.05
        self.dc = 0.0
        if mode == "WFM":
            self.pre = Fir(lowpass(16000, SR_NARROW, 41), dec, np.float32)
            self.post = Fir(lowpass(15000, AUDIO_SR, 63), 1, np.float32)
            a = math.exp(-1 / (AUDIO_SR * 50e-6))          # 50 us de-emphasis (Europe)
            self.deemph = Fir(((1 - a) * a ** np.arange(32)).astype(np.float32), 1, np.float32)
        else:
            bw = {"NFM": 7000, "AM": 5000, "USB": 3500, "LSB": 3500}[mode]
            self.chan = Fir(lowpass(bw, SR_NARROW, 81), dec)
            self.post = Fir(lowpass(3800 if mode == "NFM" else 4500, AUDIO_SR, 47), 1, np.float32)
            if mode in ("USB", "LSB"):
                s = 1 if mode == "USB" else -1
                self.ssb_in, self.ssb_out = Mixer(-s * 1700, AUDIO_SR), Mixer(s * 1700, AUDIO_SR)
                self.ssb = Fir(lowpass(1400, AUDIO_SR, 191))

    def __call__(self, iq):
        x = self.mix(iq)
        if self.mode == "WFM":
            xx = np.concatenate(([self.prev], x))
            self.prev = x[-1]
            d = np.angle(xx[1:] * np.conj(xx[:-1])).astype(np.float32)
            return self.deemph(self.post(self.pre(d))) * 0.35
        y = self.chan(x)
        if self.mode == "NFM":
            yy = np.concatenate(([self.prev], y))
            self.prev = y[-1]
            a = np.angle(yy[1:] * np.conj(yy[:-1])).astype(np.float32)
            return self.post(a) * 0.9
        if self.mode == "AM":
            a = np.abs(y).astype(np.float32)
        else:
            a = (self.ssb_out(self.ssb(self.ssb_in(y))).real * 2).astype(np.float32)
        self.dc = 0.95 * self.dc + 0.05 * float(a.mean()) if self.mode == "AM" else 0.0
        a = a - self.dc
        self.agc = 0.8 * self.agc + 0.2 * max(float(np.abs(a).mean()), 1e-5)
        return self.post(a) * (0.12 / self.agc)


# ---------------------------------------------------------------- the radio (rtl_tcp + DSP thread)

class Radio:
    def __init__(self):
        self.proc = self.sock = None
        self.lock = threading.Lock()
        self.running = False
        self.error = None
        self.spectrum = None        # dB per bin, fftshifted
        self.floor = -60.0
        self.snr = 0.0
        self.sq_open = True
        self.water_rows = queue.Queue(maxsize=64)
        self.audio = queue.Queue(maxsize=6)
        self.cfg = None
        self.applied = None
        self.audio_ok = True

    def start(self):
        if not shutil.which("rtl_tcp"):
            self.error = "немає rtl_tcp: sudo apt install rtl-sdr"
            return False
        # an rtl_tcp left by an earlier run of this app (exactly its command line) still holds the stick
        subprocess.run(["pkill", "-9", "-u", str(os.getuid()), "-f", r"^rtl_tcp -a 127\.0\.0\.1 -p [0-9]+ -s %d$" % SR_NARROW],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        time.sleep(0.3)
        port = free_port()
        self.proc = subprocess.Popen(["rtl_tcp", "-a", "127.0.0.1", "-p", str(port), "-s", str(SR_NARROW)],
                                     stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
        end = time.monotonic() + 6
        while time.monotonic() < end:
            if self.proc.poll() is not None:
                err = self.proc.stderr.read().decode("utf-8", "replace")
                self.error = ("приймач не знайдено (USB?)" if "No supported devices" in err else
                              "приймач зайнятий іншою програмою" if "Failed to open" in err or "usb_claim" in err
                              else "rtl_tcp: " + (err.strip().splitlines() or ["?"])[-1][:60])
                return False
            try:
                self.sock = socket.create_connection(("127.0.0.1", port), timeout=1)
                break
            except OSError:
                time.sleep(0.2)
        if not self.sock:
            self.error = "rtl_tcp не відповідає"
            return False
        self.sock.settimeout(3)
        self.sock.recv(12)          # "RTL0", tuner type, gain count
        self.running = True
        threading.Thread(target=self.dsp, daemon=True).start()
        threading.Thread(target=self.player, daemon=True).start()
        return True

    def stop(self):
        self.running = False
        try:
            self.sock.close()
        except Exception:
            pass
        if self.proc:   # rtl_tcp may ignore SIGTERM and keep the stick: then SIGKILL
            self.proc.terminate()
            try:
                self.proc.wait(1.5)
            except subprocess.TimeoutExpired:
                self.proc.kill()
                try:
                    self.proc.wait(2)
                except subprocess.TimeoutExpired:
                    pass

    def cmd(self, code, value):
        try:
            self.sock.sendall(struct.pack(">BI", code, int(value) & 0xFFFFFFFF))
        except OSError:
            pass

    def configure(self, cfg):
        """cfg: dict freq, mode, gain (index, -1 auto), wide, vol, sq, sound."""
        with self.lock:
            self.cfg = dict(cfg)

    def _apply(self, cfg):
        """Send what changed to the stick; returns the demodulator (None in the wide view)."""
        old = self.applied or {}
        sr = SR_WIDE if cfg["wide"] else SR_NARROW
        offset = 0 if cfg["wide"] or cfg["mode"] == "WFM" else OFFSET
        center = cfg["freq"] + offset
        if old.get("sr") != sr:
            self.cmd(0x02, sr)
        if old.get("center") != center:
            self.cmd(0x01, center)
        if old.get("gain") != cfg["gain"]:
            if cfg["gain"] < 0:
                self.cmd(0x03, 0)
            else:
                self.cmd(0x03, 1)
                self.cmd(0x04, GAINS[cfg["gain"]])
        self.applied = {"sr": sr, "center": center, "gain": cfg["gain"]}
        self.sr, self.fb = sr, -offset
        return None if cfg["wide"] else Demod(cfg["mode"], -offset)

    def _recv(self, n):
        buf = bytearray()
        while len(buf) < n:
            part = self.sock.recv(min(262144, n - len(buf)))
            if not part:
                raise OSError("rtl_tcp closed")
            buf += part
        return buf

    def dsp(self):
        demod, key, last_row = None, None, 0
        nfft = 512
        win = np.hanning(nfft).astype(np.float32)
        avg = None
        try:
            while self.running:
                with self.lock:
                    cfg = self.cfg
                if cfg is None:
                    time.sleep(0.05)
                    continue
                k = (cfg["freq"], cfg["mode"], cfg["gain"], cfg["wide"])
                if k != key:
                    demod, key = self._apply(cfg), k
                    nfft = 1024 if cfg["wide"] else 512
                    win = np.hanning(nfft).astype(np.float32)
                    avg = None
                    self._recv(int(self.sr * 2 * 0.02))    # drop what was in flight
                n = int(self.sr * CHUNK_S)
                raw = self._recv(2 * n)
                iq = np.frombuffer(raw, np.uint8).astype(np.float32).view(np.complex64)
                iq = (iq - (127.5 + 127.5j)) * (1 / 127.5)
                # spectrum: the mean of a few windowed FFTs
                segs = min(8, n // nfft)
                blocks = iq[:segs * nfft].reshape(segs, nfft) * win
                p = (np.abs(np.fft.fft(blocks, axis=1)) ** 2).mean(axis=0)
                db = 10 * np.log10(np.fft.fftshift(p) / (nfft * nfft) + 1e-12)
                if self.fb:   # narrow modes: the stick's own spike at its centre is not a signal - hide it
                    c = nfft // 2
                    db[c - 2:c + 3] = np.median(np.concatenate((db[c - 8:c - 3], db[c + 3:c + 8])))
                avg = db if avg is None or len(avg) != len(db) else 0.6 * avg + 0.4 * db
                self.spectrum = avg
                floor = float(np.median(avg))
                self.floor = floor
                # the channel's level above the noise floor
                bw = {"WFM": 90000, "NFM": 6000, "AM": 4000, "USB": 3000, "LSB": 3000}[cfg["mode"]]
                fc = 0 if cfg["wide"] else self.fb + (bw / 2 if cfg["mode"] == "USB" else
                                                      -bw / 2 if cfg["mode"] == "LSB" else 0)
                i0 = int((fc - bw / 2) / self.sr * nfft + nfft / 2)
                i1 = int((fc + bw / 2) / self.sr * nfft + nfft / 2) + 1
                ch = avg[max(0, i0):min(nfft, max(i1, i0 + 1))]
                self.snr = float(10 * np.log10(np.mean(10 ** (ch / 10)))) - floor if len(ch) else 0.0
                now = time.monotonic()
                if now - last_row > 0.1:
                    last_row = now
                    try:
                        self.water_rows.put_nowait(avg.copy())
                    except queue.Full:
                        pass
                if demod is None or not cfg["sound"]:
                    continue
                self.sq_open = not cfg["sq"] or self.snr >= SQUELCH[cfg["sq"]]
                audio = demod(iq)
                if not self.sq_open:
                    audio = np.zeros_like(audio)
                pcm = np.clip(audio * (cfg["vol"] / 100) * 32767, -32767, 32767).astype(np.int16).tobytes()
                try:
                    self.audio.put_nowait(pcm)
                except queue.Full:          # the sound card is slower than the stick: drop one
                    try:
                        self.audio.get_nowait()
                    except queue.Empty:
                        pass
        except (OSError, ValueError) as e:
            self.error = "зв'язок з rtl_tcp: %s" % e
            self.running = False

    def player(self):
        ap = None
        while self.running:
            try:
                pcm = self.audio.get(timeout=0.5)
            except queue.Empty:
                if ap and not (self.cfg or {}).get("sound"):
                    ap.stdin.close()
                    ap.wait()
                    ap = None
                continue
            if ap is None:
                try:
                    ap = subprocess.Popen(["aplay", "-q", "-t", "raw", "-f", "S16_LE", "-r", str(AUDIO_SR), "-c", "1",
                                           "-B", "200000"], stdin=subprocess.PIPE, stderr=subprocess.DEVNULL)
                except OSError:
                    self.audio_ok = False
                    continue
            try:
                ap.stdin.write(pcm)
                ap.stdin.flush()
            except (BrokenPipeError, OSError):
                self.audio_ok = False
                ap = None
                time.sleep(1)
        if ap:
            try:
                ap.stdin.close()
                ap.terminate()
            except OSError:
                pass


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
f_freq = font("DejaVuSansMono-Bold.ttf", 30 if BIG else 13)
f_small = font("DejaVuSans.ttf", 13 if BIG else 7)
f_bold = font("DejaVuSans-Bold.ttf", 14 if BIG else 8)
HAT = lcd.DEVICE == "hat144"

SPEC_Y, SPEC_H = 38, 30
WF_Y, WF_H = 69, 48
X0, W = 2, 124


def text(s, pos, color, f, right=False, center=False):
    img = f.render(s, True, color)
    x, y = pos
    if right:
        x -= img.get_width()
    elif center:
        x -= img.get_width() / 2
    screen.blit(img, (x, y))


def palette():
    stops = [(0, 0, 0), (0, 0, 140), (0, 150, 255), (0, 230, 120), (255, 230, 0), (255, 60, 0), (255, 255, 255)]
    lut = np.zeros((256, 3), np.uint8)
    for i in range(256):
        t = i / 255 * (len(stops) - 1)
        j = min(int(t), len(stops) - 2)
        f = t - j
        lut[i] = [stops[j][c] + (stops[j + 1][c] - stops[j][c]) * f for c in range(3)]
    return lut


LUT = palette()
WF_PX = (lcd.sc(W), lcd.sc(WF_H))          # the waterfall in native pixels
water = np.zeros((WF_PX[0], WF_PX[1], 3), np.uint8)   # (x, y, rgb) for surfarray
wf_surf = pygame.Surface(WF_PX)


def resample(db, n):
    """dB bins -> n columns (max per column, so narrow carriers stay visible)."""
    if n >= len(db):
        return db[(np.arange(n) * len(db) // n)]
    return np.maximum.reduceat(db, (np.arange(n) * len(db) // n))


def fmt_freq(f, step):
    if step < 1000:
        return "%.4f" % (f / 1e6)
    return "%.3f" % (f / 1e6)


def fmt_step(s):
    return "%g кГц" % (s / 1000) if s >= 1000 else "%d Гц" % s


def draw(radio, st, sel, typing, note):
    screen.fill(BG)
    cfg = st
    # frequency, mode
    ftxt = (typing + "_") if typing is not None else fmt_freq(cfg["freq"], cfg["step"])
    text(ftxt, (2, 0), ACCENT if typing is not None else FG, f_freq)
    text("МГц", (2 + f_freq.size(ftxt)[0] + 2, 4), DIM, f_small)
    text(cfg["mode"], (126, 0), BLUE, f_bold, right=True)
    snd = "♪" if cfg["sound"] and not cfg["wide"] else "×"
    text(snd, (126, 9), GREEN if snd == "♪" and radio.sq_open else DIM, f_bold, right=True)
    # S-meter: the channel above the noise floor
    snr = max(0.0, radio.snr)
    y = 17
    pygame.draw.rect(screen, (40, 40, 40), (2, y + 1, 78, 5))
    pygame.draw.rect(screen, GREEN if snr < 20 else ACCENT, (2, y + 1, min(78, snr * 78 / 40), 5))
    if cfg["sq"]:
        x = 2 + min(78, SQUELCH[cfg["sq"]] * 78 / 40)
        pygame.draw.line(screen, RED, (x, y), (x, y + 7))
    text("%+.0f дБ" % radio.snr, (126, y - 1), FG, f_small, right=True)
    # the selected parameter
    vals = [fmt_freq(cfg["freq"], cfg["step"]) + " МГц", cfg["mode"], fmt_step(cfg["step"]),
            "авто" if cfg["gain"] < 0 else "%.1f дБ" % (GAINS[cfg["gain"]] / 10), "%d %%" % cfg["vol"],
            "вимк" if not cfg["sq"] else "+%d дБ" % SQUELCH[cfg["sq"]],
            "2 МГц, без звуку" if cfg["wide"] else "240 кГц", st.get("mem_name", "—")]
    y = 26
    pygame.draw.rect(screen, (50, 40, 0), (1, y, 126, 10), border_radius=2)
    text("%s:" % PARAMS[sel], (4, y + 1), ACCENT, f_small)
    text("◀ %s ▶" % vals[sel], (124, y + 1), FG, f_bold, right=True)
    # spectrum
    db = radio.spectrum
    lo, hi = radio.floor - 5, radio.floor + 45
    pygame.draw.rect(screen, (25, 25, 25), (X0, SPEC_Y, W, SPEC_H))
    sr = SR_WIDE if cfg["wide"] else SR_NARROW
    if db is not None:
        cols = resample(db, W)
        pts = [(X0 + i + 0.5, SPEC_Y + SPEC_H - 1 - max(0, min(1, (v - lo) / (hi - lo))) * (SPEC_H - 2))
               for i, v in enumerate(cols)]
        pygame.draw.lines(screen, GREEN, False, pts)
    # the channel: where the signal is in the view (narrow modes sit OFFSET below the centre)
    fb = 0 if cfg["wide"] or cfg["mode"] == "WFM" else -OFFSET
    bw = {"WFM": 180000, "NFM": 12500, "AM": 9000, "USB": 3000, "LSB": 3000}[cfg["mode"]]
    lo_f = fb - bw / 2 + (bw / 2 if cfg["mode"] == "USB" else -bw / 2 if cfg["mode"] == "LSB" else 0)
    xa = X0 + (lo_f / sr + 0.5) * W
    xb = X0 + ((lo_f + bw) / sr + 0.5) * W
    xc = X0 + (fb / sr + 0.5) * W
    shade = pygame.Surface((max(1, lcd.sc(xb - xa)), lcd.sc(SPEC_H)), pygame.SRCALPHA)
    shade.fill((255, 200, 0, 50))
    screen.blit(shade, (xa, SPEC_Y))
    pygame.draw.line(screen, RED, (xc, SPEC_Y), (xc, SPEC_Y + SPEC_H - 1))
    # waterfall rows from the DSP thread
    global water
    while not radio.water_rows.empty():
        row = radio.water_rows.get_nowait()
        v = resample(row, WF_PX[0])
        idx = np.clip((v - lo) / (hi - lo) * 255, 0, 255).astype(np.uint8)
        water = np.roll(water, 2, axis=1)
        water[:, 0] = water[:, 1] = LUT[idx]
    pygame.surfarray.blit_array(wf_surf, water)
    screen.blit(wf_surf, (X0, WF_Y))
    pygame.draw.line(screen, (255, 80, 60), (xc, WF_Y), (xc, WF_Y + 2))
    # bottom line: the span / note / hint
    if note:
        text(note, (64, 118), RED, f_small, center=True)
    elif typing is not None:
        text("частота в МГц, Enter", (64, 118), DIM, f_small, center=True)
    else:
        text("±%g кГц" % (sr / 2000), (2, 118), DIM, f_small)
        text(("KEY1/2 тюн, натиск ♪" if HAT else "↑↓ ←→  цифри  Enter ♪  s"), (126, 118), DIM, f_small,
             right=True)
    lcd.flip()


def message(*lines):
    screen.fill(BG)
    text("SDR", (64, 4), ACCENT, f_bold, center=True)
    for i, line in enumerate(lines):
        text(line, (64, 40 + i * 12), RED if i == 0 else DIM, f_small, center=True)
    lcd.flip()


# ---------------------------------------------------------------- state

def load_state():
    st = {"freq": 101.5e6, "mode": "WFM", "step": 100000, "gain": 16, "vol": 60, "sq": 0, "wide": False,
          "sound": True, "memory": []}
    try:
        with open(STATE_FILE, encoding="utf-8") as f:
            st.update(json.load(f))
    except (OSError, ValueError):
        pass
    return st


def save_state(st):
    try:
        os.makedirs(os.path.dirname(STATE_FILE), exist_ok=True)
        keep = {k: st[k] for k in ("freq", "mode", "step", "gain", "vol", "sq", "wide", "sound", "memory")}
        with open(STATE_FILE, "w", encoding="utf-8") as f:
            json.dump(keep, f, ensure_ascii=False, indent=1)
    except OSError:
        pass


def memories(st):
    """User stations first, then the built-in presets: (name, Hz, mode, step, user?)."""
    return ([(m["name"], m["freq"], m["mode"], m.get("step", 12500), True) for m in st["memory"]] +
            [p + (False,) for p in PRESETS])


def main():
    st = load_state()
    st["mem"] = 0
    st["mem_name"] = "—"
    radio = Radio()
    message("запускаю приймач…")
    if not radio.start():
        message(radio.error, "RTL-SDR у USB?", ("KEY3" if HAT else "Esc") + " - назад")
        end = time.monotonic() + 30
        while time.monotonic() < end:
            if any(e.type in (pygame.KEYDOWN, pygame.QUIT) for e in pygame.event.get()):
                break
            clock.tick(10)
        radio.stop()
        return
    sel, typing, note, note_until = P_FREQ, None, "", 0
    held, next_rep = None, 0

    def push():
        radio.configure({k: st[k] for k in ("freq", "mode", "gain", "wide", "vol", "sq", "sound")})

    def tune(sign, mult=1):
        st["freq"] = min(FMAX, max(FMIN, round((st["freq"] + sign * st["step"] * mult) / st["step"]) * st["step"]))

    def change(sign):
        nonlocal note, note_until
        if sel == P_FREQ:
            tune(sign)
        elif sel == P_MODE:
            st["mode"] = MODES[(MODES.index(st["mode"]) + sign) % len(MODES)]
        elif sel == P_STEP:
            st["step"] = STEPS[(STEPS.index(st["step"]) + sign) % len(STEPS)] if st["step"] in STEPS else 12500
        elif sel == P_GAIN:
            st["gain"] = min(len(GAINS) - 1, max(-1, st["gain"] + sign))
        elif sel == P_VOL:
            st["vol"] = min(100, max(0, st["vol"] + 5 * sign))
        elif sel == P_SQ:
            st["sq"] = min(len(SQUELCH) - 1, max(0, st["sq"] + sign))
        elif sel == P_VIEW:
            st["wide"] = not st["wide"]
        elif sel == P_MEM:
            mem = memories(st)
            st["mem"] = (st["mem"] + sign) % len(mem)
            name, f, mode, step, _ = mem[st["mem"]]
            st.update(freq=f, mode=mode, step=step, mem_name=name)
        push()

    push()
    try:
        while radio.running:
            now = time.monotonic()
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
                ch = getattr(ev, "unicode", "") if not hat else ""
                held = None
                if k == pygame.K_ESCAPE or (hat and k == pygame.K_3):
                    if typing is not None:
                        typing = None
                        continue
                    return
                if ch and (ch.isdigit() or (ch in ".," and typing is not None)):
                    typing = ((typing or "") + ("." if ch == "," else ch))[:12]
                    continue
                if typing is not None and k == pygame.K_BACKSPACE:
                    typing = typing[:-1] or None
                    continue
                if k in (pygame.K_RETURN, pygame.K_KP_ENTER):
                    if typing is not None:
                        try:
                            f = float(typing) * 1e6
                            if not FMIN <= f <= FMAX:
                                raise ValueError
                            st["freq"] = f
                            push()
                        except ValueError:
                            note, note_until = "0,5 - 1766 МГц", now + 3
                        typing = None
                        continue
                    st["sound"] = not st["sound"]
                    push()
                    continue
                if hat and k in (pygame.K_1, pygame.K_2):
                    tune(1 if k == pygame.K_1 else -1)
                    push()
                    held, next_rep = k, now + 0.4
                    continue
                if k == pygame.K_UP:
                    sel = (sel - 1) % len(PARAMS)
                elif k == pygame.K_DOWN:
                    sel = (sel + 1) % len(PARAMS)
                elif k in (pygame.K_LEFT, pygame.K_RIGHT):
                    change(1 if k == pygame.K_RIGHT else -1)
                    held, next_rep = k, now + 0.4
                elif ch == "+" or k in (pygame.K_EQUALS, pygame.K_KP_PLUS):
                    st["vol"] = min(100, st["vol"] + 5)
                    push()
                elif ch == "-" or k in (pygame.K_MINUS, pygame.K_KP_MINUS):
                    st["vol"] = max(0, st["vol"] - 5)
                    push()
                elif ch in ("s", "S"):
                    name = "%s %s" % (fmt_freq(st["freq"], st["step"]), st["mode"])
                    st["memory"] = [m for m in st["memory"] if m["name"] != name][-29:] + [
                        {"name": name, "freq": st["freq"], "mode": st["mode"], "step": st["step"]}]
                    save_state(st)
                    note, note_until = "", 0
                    st["mem"], st["mem_name"] = len(st["memory"]) - 1, name
                elif k == pygame.K_DELETE and sel == P_MEM:
                    mem = memories(st)
                    if mem[st["mem"]][4]:
                        del st["memory"][st["mem"]]
                        st["mem"], st["mem_name"] = 0, "—"
                        save_state(st)
            # held arrows / KEY1-2 repeat (tuning gets faster the longer it is held)
            if held is not None and now >= next_rep:
                if held in (pygame.K_LEFT, pygame.K_RIGHT) and held not in lcd._held_arrows and not HAT:
                    held = None
                elif held in (pygame.K_1, pygame.K_2):
                    tune(1 if held == pygame.K_1 else -1)
                    push()
                    next_rep = now + 0.08
                elif sel in (P_FREQ, P_GAIN, P_VOL, P_MEM):
                    change(1 if held == pygame.K_RIGHT else -1)
                    next_rep = now + (0.08 if sel == P_FREQ else 0.15)
            if note and now > note_until:
                note = ""
            if radio.error and not note:
                note, note_until = radio.error, now + 5
            if not radio.audio_ok and st["sound"] and not st["wide"]:
                note, note_until = "звук недоступний (aplay)", now + 3
            draw(radio, st, sel, typing, note)
            clock.tick(10)
        message(radio.error or "приймач зупинився", "RTL-SDR від'єднано?")
        time.sleep(3)
    finally:
        save_state(st)
        radio.stop()


if __name__ == "__main__":
    try:
        main()
    finally:
        screen.fill(BG)
        lcd.flip()
        lcd.quit()
