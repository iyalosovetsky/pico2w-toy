"""SYNTH: a small music synthesizer - piano, organ, strings, winds, mallets, guitar... and drums.

Every sound is synthesized with numpy when an instrument (or octave) is chosen - additive
harmonics with their own envelopes, FM for the electric piano and bells, Karplus-Strong for the
guitar, shaped noise for the drums - and played by pygame's mixer (polyphonic, 24 channels).

Keys like a tracker: the lower octave on z s x d c v g b h n j m (white / black keys), then , l . ; /;
the upper one on q 2 w 3 e r 5 t 6 y 7 u, then i 9 o 0 p. A rhythm machine plays along.
UP / DOWN - row (instrument, octave, volume, rhythm, tempo), LEFT / RIGHT - change it,
Space - rhythm on / off, Esc - exit.
"""
import math
import os
import sys
import threading
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import numpy as np  # noqa: E402
import pygame  # noqa: E402
import lcd  # noqa: E402

SR = 22050           # plenty for the PicoCalc's speaker, and half the work
LOWER = "zsxdcvgbhnjm,l.;/"          # semitones 0..16 from the octave's C
UPPER = "q2w3er5t6y7ui9o0p"          # semitones 12..28
KEYS = {ch: i for i, ch in enumerate(LOWER)}
KEYS.update({ch: 12 + i for i, ch in enumerate(UPPER)})
NSEMI = 29
BLACK = {1, 3, 6, 8, 10}

BG, FG, DIM = (0, 0, 0), (235, 235, 235), (140, 140, 140)
ACCENT, GREEN, BLUE, RED = (255, 200, 0), (90, 220, 110), (110, 170, 255), (240, 90, 80)
FONT_DIR = "/usr/share/fonts/truetype/dejavu/"
RNG = np.random.default_rng(7)


def midi_hz(m):
    return 440.0 * 2 ** ((m - 69) / 12)


# ---------------------------------------------------------------- building blocks
# Sounds are rendered from wavetables: the sum of a note's harmonics is computed once over one period
# (TABLE points), then read at the note's phase - the cost does not grow with the number of harmonics
# (a Zero 2 W took ~1 s a note with one sin() per harmonic). Harmonics that decay differently go to
# separate tables (2-3 groups).

TABLE = 2048
_X = np.arange(TABLE) / TABLE


def tvec(dur):
    return np.arange(int(SR * dur), dtype=np.float32) / SR


def env_adsr(n, a, d, s):
    """Attack (s), decay (s) to the sustain level, held; a gentle fade over the last 40 ms."""
    t = np.arange(n, dtype=np.float32) / SR
    e = np.where(t < a, t / max(a, 1e-4), s + (1 - s) * np.exp(-(t - a) / max(d, 1e-4)))
    tail = min(n, int(0.04 * SR))
    e[-tail:] *= np.linspace(1, 0, tail)
    return e.astype(np.float32)


def fade_end(y, ms=30):
    k = min(len(y), int(SR * ms / 1000))
    y[-k:] *= np.linspace(1, 0, k, dtype=np.float32)
    return y


def table(f, amps, ratios=None):
    """One period of sum(a_k sin(2 pi r_k x)), harmonics above Nyquist left out (no aliasing)."""
    y = np.zeros(TABLE, np.float32)
    for k, a in enumerate(amps, 1):
        r = ratios[k - 1] if ratios else k
        if a and r * f < SR / 2.2:
            y += a * np.sin(2 * np.pi * r * _X).astype(np.float32)
    return y


def cycles(f, t, vib=None):
    """The phase in periods: f t, with vibrato (rate Hz, depth fraction, delay s) easing in."""
    c = f * t
    if vib:
        rate, depth, delay = vib
        ramp = np.clip((t - delay) / 0.3, 0, 1)
        c = c - f * depth * ramp * np.cos(2 * np.pi * rate * t) / (2 * np.pi * rate)
    return c


def read(tab, c):
    return tab[((c % 1.0) * TABLE).astype(np.int32) % TABLE]


_NOISE = RNG.uniform(-1, 1, SR * 4).astype(np.float32)


def noise(n):
    start = int(RNG.integers(0, len(_NOISE) - n)) if n < len(_NOISE) else 0
    return _NOISE[start:start + n].copy()


def band(x, lo, hi):
    """Band-pass by FFT (for short bursts and the drums, rendered once)."""
    X = np.fft.rfft(x)
    f = np.fft.rfftfreq(len(x), 1 / SR)
    w = np.clip((f - lo * 0.8) / (lo * 0.2 + 1), 0, 1) * np.clip((hi * 1.2 - f) / (hi * 0.2 + 1), 0, 1)
    return np.fft.irfft(X * w, len(x)).astype(np.float32)


_BANDS = {}


def band_noise(lo, hi, n):
    """A slice of band-passed noise (each band computed once)."""
    key = (lo, hi)
    if key not in _BANDS:
        _BANDS[key] = band(RNG.uniform(-1, 1, SR * 3).astype(np.float32), lo, hi)
    src = _BANDS[key]
    if n <= len(src):
        return src[:n].copy()
    return np.resize(src, n)


# ---------------------------------------------------------------- instruments: f -> samples

def piano(f):
    t = tvec(2.2 if f < 400 else 1.6)
    base = 0.9 + f / 900                       # higher notes die faster
    c = cycles(f, t)
    y = read(table(f, [1, 0.6, 0.35]), c) * np.exp(-base * t)
    y += read(table(f, [1, 0.6, 0.35]), c * 1.0012) * np.exp(-base * t) * 0.5      # a second string
    y += read(table(f, [0, 0, 0, 0.25, 0.18, 0.12]), c) * np.exp(-base * 2.8 * t)
    y += read(table(f, [0] * 6 + [0.08, 0.06, 0.04, 0.03]), c) * np.exp(-base * 4.5 * t)
    k = int(0.015 * SR)
    y[:k] += band_noise(1500, 6000, k) * np.linspace(0.15, 0, k)                  # the hammer
    return y * np.minimum(t / 0.004, 1)


def epiano(f):                                 # FM "tine": modulator at f, index decaying
    t = tvec(1.8)
    idx = 1.6 * np.exp(-t * 4) + 0.2
    w = 2 * np.pi * f * t
    y = np.sin(w + idx * np.sin(w))
    if 14 * f < SR / 2.2:
        y += 0.25 * np.sin(14 * w) * np.exp(-t * 30)                              # the tine's bark
    return y * np.exp(-t * (1.2 + f / 1500)) * np.minimum(t / 0.003, 1)


def organ(f):
    t = tvec(2.5)
    # drawbars 16' 8' 4' 2 2/3' 2' 1 1/3' 1': harmonics of f/2
    tab = table(f / 2, [0.25, 1, 0, 0.8, 0, 0.5, 0, 0.4, 0, 0, 0, 0.2, 0, 0, 0, 0.15])
    y = read(tab, cycles(f / 2, t)) * (1 + 0.12 * np.sin(2 * np.pi * 6.2 * t))   # a Leslie's tremolo
    k = int(0.006 * SR)
    y[:k] += band_noise(2000, 8000, k) * 0.2
    return y * env_adsr(len(t), 0.006, 0.05, 1.0)


def violin(f):
    amps = [1 / k for k in range(1, 16)]
    for k in range(15):                         # the body's resonances around 3 kHz
        amps[k] *= 1 + 1.2 * math.exp(-(((k + 1) * f - 3000) / 1200) ** 2)
    t = tvec(2.5)
    y = read(table(f, amps), cycles(f, t, (5.5, 0.006, 0.25)))
    y += 0.03 * band_noise(2000, 7000, len(t))                                   # bow noise
    return y * env_adsr(len(t), 0.12, 0.3, 0.85)


def strings(f):                                 # an ensemble: three detuned saws, a slow swell
    t = tvec(2.6)
    tab = table(f, [1 / k for k in range(1, 12)])
    y = sum(read(tab, cycles(f * (1 + d), t, (5 + i, 0.004, 0.1))) for i, d in enumerate((-0.004, 0, 0.005)))
    return y * env_adsr(len(t), 0.35, 0.5, 0.9)


def brass(f):
    t = tvec(2.3)
    e = env_adsr(len(t), 0.05, 0.4, 0.75)
    c = cycles(f, t) - 0.01 * f * (1 - np.exp(-t * 25)) / 25      # a small scoop into the note
    dark = read(table(f, [math.exp(-k / 2) for k in range(1, 18)]), c)
    bright = read(table(f, [math.exp(-k / 8) for k in range(1, 18)]), c)
    return (dark * (1 - e) + bright * e) * e                       # brighter while it is louder


def flute(f):
    t = tvec(2.3)
    y = read(table(f, [1, 0.25, 0.08, 0.03]), cycles(f, t, (5, 0.004, 0.3)))
    lo = 400 if f < 400 else 1000 if f < 1000 else 2000
    y += 0.08 * band_noise(lo, lo * 6, len(t))                                    # breath
    return y * env_adsr(len(t), 0.07, 0.3, 0.85)


def clarinet(f):
    t = tvec(2.3)
    y = read(table(f, [1, 0.02, 0.55, 0.02, 0.3, 0.02, 0.18, 0, 0.1, 0, 0.06]), cycles(f, t, (4.5, 0.002, 0.4)))
    return y * env_adsr(len(t), 0.04, 0.3, 0.8)


def xylophone(f):
    t = tvec(0.9)
    y = np.sin(2 * np.pi * f * t) * np.exp(-t * (6 + f / 400))
    if 3 * f < SR / 2.2:
        y += 0.4 * np.sin(2 * np.pi * 3.0 * f * t) * np.exp(-t * 18)
    if 6 * f < SR / 2.2:
        y += 0.15 * np.sin(2 * np.pi * 6.0 * f * t) * np.exp(-t * 35)
    k = int(0.004 * SR)
    y[:k] += band_noise(2000, 9000, k) * 0.4                                      # the mallet
    return y


def marimba(f):
    t = tvec(1.4)
    y = np.sin(2 * np.pi * f * t) * np.exp(-t * (2.5 + f / 600))
    if 4 * f < SR / 2.2:
        y += 0.25 * np.sin(2 * np.pi * 4.0 * f * t) * np.exp(-t * 12)
    if 10 * f < SR / 2.2:
        y += 0.08 * np.sin(2 * np.pi * 10.0 * f * t) * np.exp(-t * 30)
    return y * np.minimum(t / 0.002, 1)


def bells(f):                                   # glockenspiel-like: inharmonic partials
    t = tvec(2.0)
    y = np.zeros_like(t)
    for r, a, d in ((1, 1, 1.5), (2.76, 0.5, 3), (5.4, 0.25, 5), (8.93, 0.12, 8)):
        if r * f < SR / 2.2:
            y += a * np.sin(2 * np.pi * r * f * t) * np.exp(-d * t)
    return y * np.minimum(t / 0.001, 1)


def guitar(f):
    """Karplus-Strong, rendered at a rate where the loop is a whole number of samples, resampled."""
    dur = 1.8
    N = int(math.ceil(SR / f))
    sr = (N + 0.5) * f                 # the two-point average adds half a sample to the loop
    n = int(sr * dur)
    y = np.zeros(n + N + 1, np.float32)
    # a softer pluck: smoothed noise plus one sawtooth period, so the fundamental is always there
    burst = 0.6 * np.convolve(noise(N), [0.5, 0.5], "same") + 0.8 * np.linspace(-1, 1, N, dtype=np.float32)
    y[:N] = burst - burst.mean()                                # no DC: the loop would keep it
    g = 0.996 - f / 40000
    for start in range(N, n, N):
        idx = np.arange(start, min(start + N, n))
        y[idx] = g * 0.5 * (y[idx - N] + y[idx - N - 1])
    y = y[:n]
    return np.interp(np.arange(int(SR * dur)) * (sr / SR), np.arange(n), y).astype(np.float32)


def bass(f):
    t = tvec(1.4)
    c = cycles(f, t)
    y = read(table(f, [1, 0.5, 0.33]), c) * np.exp(-3 * t)
    y += read(table(f, [0, 0, 0] + [1 / k for k in range(4, 12)]), c) * np.exp(-9 * t)
    return y * np.minimum(t / 0.005, 1)


def synth(f):
    t = tvec(1.8)
    tab = table(f, [1 / k for k in range(1, 20)])
    c = cycles(f, t)
    y = 0.5 * (read(tab, c) + read(tab, c * 1.004))
    return y * env_adsr(len(t), 0.01, 0.4, 0.6)


INSTRUMENTS = [("Піаніно", piano, 0.25), ("Електропіаніно", epiano, 0.15), ("Орган", organ, 0.15),
               ("Скрипка", violin, 0.15), ("Струнні", strings, 0.25), ("Труба", brass, 0.12),
               ("Флейта", flute, 0.12), ("Кларнет", clarinet, 0.12), ("Ксилофон", xylophone, None),
               ("Маримба", marimba, None), ("Дзвіночки", bells, None), ("Гітара", guitar, 0.4),
               ("Бас", bass, 0.15), ("Синт", synth, 0.12), ("Ударні", None, None)]
# the third field: fade-out on key release (s); None - the sound rings on (mallets)


# ---------------------------------------------------------------- drums

def drum_sounds():
    def t_(d):
        return tvec(d)
    s = {}
    t = t_(0.5)
    s["kick"] = np.sin(2 * np.pi * np.cumsum(45 + 110 * np.exp(-t * 35)) / SR) * np.exp(-t * 7)
    s["kick"][:80] += noise(80) * 0.3
    t = t_(0.35)
    s["snare"] = 0.5 * np.sin(2 * np.pi * 185 * t) * np.exp(-t * 20) + band(noise(len(t)), 1000, 8000) * np.exp(-t * 14) * 1.2
    t = t_(0.12)
    s["hat"] = band(noise(len(t)), 7000, 15000) * np.exp(-t * 60) * 1.5
    t = t_(0.6)
    s["open hat"] = band(noise(len(t)), 6500, 15000) * np.exp(-t * 7) * 1.2
    t = t_(0.35)
    clap = band(noise(len(t)), 900, 3200)
    envc = np.exp(-t * 18)
    for d in (0.01, 0.02):
        envc += (t >= d) * (t < d + 0.008) * 0.8
    s["clap"] = clap * envc * 1.3
    for name, f0 in (("tom low", 90), ("tom mid", 125), ("tom high", 165)):
        t = t_(0.5)
        s[name] = np.sin(2 * np.pi * np.cumsum(f0 * (0.7 + 0.3 * np.exp(-t * 8))) / SR) * np.exp(-t * 9)
    t = t_(2.0)
    metal = sum(np.sin(2 * np.pi * fr * t) for fr in (3220, 4170, 5310, 6890, 8430)) / 5
    s["crash"] = (band(noise(len(t)), 4000, 16000) * 0.9 + metal * 0.4) * np.exp(-t * 2.5)
    t = t_(1.4)
    s["ride"] = (sum(np.sin(2 * np.pi * fr * t) for fr in (2900, 3760, 5180, 6440)) / 4 * 0.6 +
                 band(noise(len(t)), 5000, 14000) * 0.25) * np.exp(-t * 3)
    t = t_(0.3)
    sq = np.sign(np.sin(2 * np.pi * 540 * t)) + np.sign(np.sin(2 * np.pi * 800 * t))
    s["cowbell"] = band(sq.astype(np.float32), 400, 2500) * np.exp(-t * 12) * 0.6
    t = t_(0.04)
    s["rim"] = np.sin(2 * np.pi * 1700 * t) * np.exp(-t * 120) + band(noise(len(t)), 2000, 8000) * np.exp(-t * 150) * 0.5
    return {k: fade_end(v.astype(np.float32), 10) for k, v in s.items()}


DRUM_KEYS = ["kick", "rim", "snare", "clap", "hat", "tom low", "open hat", "tom mid", "cowbell",
             "tom high", "ride", "crash"]          # semitones 0..11 of either row (z.. / q..)
DRUM_SHORT = {"kick": "БД", "snare": "МБ", "hat": "ХХ", "open hat": "ВХ", "clap": "КЛ", "tom low": "Т1",
              "tom mid": "Т2", "tom high": "Т3", "crash": "КР", "ride": "РАЙД", "cowbell": "КБ", "rim": "РІМ"}

# rhythms: 16 sixteenths (12 for the waltz); a step is a set of drum names
def _pat(steps, **lines):
    out = [set() for _ in range(steps)]
    for name, hits in lines.items():
        for i in hits:
            out[i].add(name.replace("_", " "))
    return out


RHYTHMS = [
    ("вимк", None),
    ("Рок", _pat(16, kick=[0, 8, 10], snare=[4, 12], hat=range(0, 16, 2))),
    ("Диско", _pat(16, kick=[0, 4, 8, 12], snare=[4, 12], hat=[0, 4, 8, 12], open_hat=[2, 6, 10, 14])),
    ("Хіп-хоп", _pat(16, kick=[0, 3, 10], snare=[4, 12], hat=range(0, 16, 2), open_hat=[14])),
    ("Фанк", _pat(16, kick=[0, 6, 10], snare=[4, 12, 15], hat=range(16))),
    ("Босанова", _pat(16, kick=[0, 3, 8, 11], rim=[0, 3, 6, 10, 13], hat=range(0, 16, 2))),
    ("Регі", _pat(16, kick=[8], rim=[8], hat=range(2, 16, 4))),
    ("Вальс", _pat(12, kick=[0], hat=[4, 8], snare=[4, 8])),
    ("Марш", _pat(16, kick=[0, 8], snare=[4, 6, 7, 12, 14, 15], crash=[0])),
]


class Rhythm(threading.Thread):
    """Plays the pattern on its own thread (steady timing while the screen redraws)."""

    def __init__(self, sounds):
        super().__init__(daemon=True)
        self.sounds, self.pattern, self.bpm, self.vol = sounds, None, 100, 0.7
        self.step = 0
        self.running = True

    def run(self):
        nxt = time.monotonic()
        while self.running:
            pat = self.pattern
            if pat is None:
                self.step = 0
                time.sleep(0.02)
                nxt = time.monotonic()
                continue
            now = time.monotonic()
            if now < nxt:
                time.sleep(min(0.005, nxt - now))
                continue
            for name in pat[self.step % len(pat)]:
                ch = self.sounds[name].play()
                if ch:
                    ch.set_volume(self.vol * (0.75 if self.step % 4 else 1.0))
            self.step = (self.step + 1) % len(pat)
            nxt += 60 / self.bpm / (3 if len(pat) == 12 else 4)
            if now - nxt > 0.2:     # fell far behind (e.g. a busy moment): re-sync
                nxt = now


# ---------------------------------------------------------------- the sound bank

class Bank:
    """Notes of the current instrument and octave as pygame Sounds, rendered in the background."""

    def __init__(self):
        self.cache = {}
        self.lock = threading.Lock()
        self.job = None
        self.progress = 1.0

    def want(self, inst, octave):
        """Render this instrument's notes for the octave (in a thread)."""
        name, fn, _ = INSTRUMENTS[inst]
        if fn is None:
            self.progress = 1.0
            return
        base = 12 * (octave + 1)
        todo = [base + i for i in range(NSEMI) if (inst, base + i) not in self.cache]
        job = object()
        self.job = job
        self.progress = 0.0 if todo else 1.0

        def work():
            for k, m in enumerate(todo):
                if self.job is not job:
                    return
                self.get(inst, m)
                self.progress = (k + 1) / len(todo)
            # keep memory bounded: only this instrument's notes
            with self.lock:
                for key in [key for key in self.cache if key[0] != inst]:
                    del self.cache[key]
        threading.Thread(target=work, daemon=True).start()

    def get(self, inst, m):
        key = (inst, m)
        with self.lock:
            snd = self.cache.get(key)
        if snd is None:
            y = INSTRUMENTS[inst][1](midi_hz(m)).astype(np.float32)
            y = fade_end(y)
            peak = float(np.max(np.abs(y))) or 1.0
            pcm = (y / peak * 0.85 * 30000).astype(np.int16)
            snd = pygame.mixer.Sound(buffer=pcm.tobytes())
            with self.lock:
                self.cache[key] = snd
        return snd


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
f_title = font("DejaVuSans-Bold.ttf", 16 if BIG else 8)
f_inst = font("DejaVuSans-Bold.ttf", 22 if BIG else 10)
f_label = font("DejaVuSans.ttf", 14 if BIG else 8)
f_bold = font("DejaVuSans-Bold.ttf", 14 if BIG else 8)
f_key = font("DejaVuSansMono.ttf", 10 if BIG else 6)
ROWS = ["Інструмент", "Октава", "Гучність", "Ритм", "Темп"]
NOTE_NAMES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]


def text(s, pos, color, f, right=False, center=False):
    img = f.render(s, True, color)
    x, y = pos
    if right:
        x -= img.get_width()
    elif center:
        x -= img.get_width() / 2
    screen.blit(img, (x, y))


def draw(st, row, held, bank, rhythm):
    screen.fill(BG)
    text("SYNTH", (64, 0), ACCENT, f_title, center=True)
    name = INSTRUMENTS[st["inst"]][0]
    text("◀ %s ▶" % name if row == 0 else name, (64, 10), FG, f_inst, center=True)
    vals = [None, "C%d - E%d" % (st["oct"], st["oct"] + 2), "%d %%" % st["vol"],
            RHYTHMS[st["rhythm"]][0] + (" ▶" if rhythm.pattern is not None else ""), "%d BPM" % st["bpm"]]
    y = 25
    for i in range(1, len(ROWS)):
        sel = i == row
        x = 2 + (i - 1) % 2 * 63
        yy = y + (i - 1) // 2 * 10
        if sel:
            pygame.draw.rect(screen, ACCENT, (x - 1, yy - 1, 62, 10), border_radius=2)
        text(ROWS[i] + ":", (x + 1, yy), BG if sel else DIM, f_label)
        text(vals[i], (x + 60, yy), BG if sel else FG, f_bold, right=True)
    # rhythm step lights
    pat = RHYTHMS[st["rhythm"]][1]
    if pat is not None:
        n = len(pat)
        for i in range(n):
            on = rhythm.pattern is not None and (rhythm.step - 1) % n == i
            c = ACCENT if on else ((90, 90, 90) if i % (3 if n == 12 else 4) == 0 else (45, 45, 45))
            pygame.draw.rect(screen, c, (66 + i * 60 / n, 46, 60 / n - 1, 3))
    if bank.progress < 1:
        pygame.draw.rect(screen, (40, 40, 40), (2, 46, 60, 3))
        pygame.draw.rect(screen, GREEN, (2, 46, 60 * bank.progress, 3))
    # the keyboard: 17 white keys (C..E two octaves up), black keys on top
    drums = INSTRUMENTS[st["inst"]][1] is None
    whites = [i for i in range(NSEMI) if i % 12 not in BLACK]
    kw = 124 / len(whites)
    ky, kh = 54, 50
    xs = {}
    for j, i in enumerate(whites):
        x = 2 + j * kw
        xs[i] = x
        lit = i in held
        pygame.draw.rect(screen, ACCENT if lit else (225, 225, 225), (x, ky, kw - 0.6, kh))
    for i in range(NSEMI):
        if i % 12 in BLACK:
            x = xs[i - 1] + kw * 0.62
            xs[i] = x
            pygame.draw.rect(screen, ACCENT if i in held else (25, 25, 25), (x, ky, kw * 0.72, kh * 0.6))
    # the computer keys on each piano key: C4..E4 can be played from both rows - upper row's key on top
    lh = f_key.get_linesize()
    for i in range(NSEMI):
        black = i % 12 in BLACK
        chars = [c for c in UPPER + LOWER if KEYS[c] == i]          # upper row first
        x = xs[i] + (kw * 0.36 if black else kw / 2)
        y0 = ky + (kh * 0.6 if black else kh) - 1 - lh * len(chars)
        for k, c in enumerate(chars):
            text(c, (x, y0 + k * lh), (200, 200, 200) if black else (60, 60, 60), f_key, center=True)
    if drums:   # the kit: one octave of keys, the same on both rows
        items = ["%s %s" % (LOWER[j], DRUM_SHORT[DRUM_KEYS[j]]) for j in range(12)]
        text("  ".join(items[:6]), (64, ky + kh + 1), BLUE, f_key, center=True)
        text("  ".join(items[6:]), (64, ky + kh + 1 + lh), BLUE, f_key, center=True)
    if not drums:
        text("C%d" % st["oct"], (xs[0] + 1, ky + 2), (120, 120, 120), f_key)
        text("C%d" % (st["oct"] + 1), (xs[12] + 1, ky + 2), (120, 120, 120), f_key)
    hint = "z..m / q..u - ноти   Space - ритм   Esc"
    text(hint, (64, 118), (150, 150, 150), f_label, center=True)
    lcd.flip()


def main():
    if not lcd.sound_available():
        screen.fill(BG)
        text("SYNTH", (64, 4), ACCENT, f_title, center=True)
        text("тут немає динаміка", (64, 50), RED, f_label, center=True)
        lcd.flip()
        time.sleep(3)
        return
    # our own mixer: a smaller buffer for less latency, and sound even if the menu's effects are off
    pygame.mixer.quit()
    try:
        pygame.mixer.init(SR, -16, 1, 1024)
    except pygame.error:
        pygame.mixer.init(SR, -16, 1, 2048)
    pygame.mixer.set_num_channels(32)
    drums = {k: pygame.mixer.Sound(buffer=(v / max(1e-6, float(np.max(np.abs(v)))) * 0.9 * 30000).astype(np.int16).tobytes())
             for k, v in drum_sounds().items()}
    st = {"inst": 0, "oct": 3, "vol": 80, "rhythm": 1, "bpm": 100}
    row = 0
    bank = Bank()
    bank.want(st["inst"], st["oct"])
    rhythm = Rhythm(drums)
    rhythm.start()
    playing = {}          # evdev code -> (semitone, channel)
    held = set()
    while True:
        for ev in pygame.event.get():
            if ev.type == pygame.QUIT:
                return
            if ev.type not in (pygame.KEYDOWN, pygame.KEYUP):
                continue
            code = getattr(ev, "scancode", 0)
            ch = lcd.CHARS.get(code, ("",))[0] if not getattr(ev, "hat", False) else ""
            semi = KEYS.get(ch)
            if ev.type == pygame.KEYUP:
                if code in playing:
                    s, chan = playing.pop(code)
                    held.discard(s)
                    rel = INSTRUMENTS[st["inst"]][2]
                    if chan is not None and rel is not None:
                        chan.fadeout(int(rel * 1000))
                continue
            k = ev.key
            if semi is not None:
                if code in playing:
                    continue
                vol = st["vol"] / 100
                if INSTRUMENTS[st["inst"]][1] is None:
                    chan = drums[DRUM_KEYS[semi % 12]].play()
                    if chan:
                        chan.set_volume(vol)
                    chan = None      # drums ring out
                else:
                    snd = bank.get(st["inst"], 12 * (st["oct"] + 1) + semi)
                    chan = snd.play()
                    if chan:
                        chan.set_volume(vol * 0.8)
                playing[code] = (semi, chan)
                held.add(semi)
                continue
            if k == pygame.K_ESCAPE or (getattr(ev, "hat", False) and k == pygame.K_3):
                return
            if k == pygame.K_SPACE:
                if rhythm.pattern is None and RHYTHMS[st["rhythm"]][1] is None:
                    st["rhythm"] = 1
                rhythm.step = 0
                rhythm.pattern = None if rhythm.pattern is not None else RHYTHMS[st["rhythm"]][1]
            elif k == pygame.K_UP:
                row = (row - 1) % len(ROWS)
            elif k == pygame.K_DOWN:
                row = (row + 1) % len(ROWS)
            elif k in (pygame.K_LEFT, pygame.K_RIGHT):
                sign = 1 if k == pygame.K_RIGHT else -1
                if row == 0:
                    st["inst"] = (st["inst"] + sign) % len(INSTRUMENTS)
                    bank.want(st["inst"], st["oct"])
                elif row == 1:
                    st["oct"] = min(6, max(1, st["oct"] + sign))
                    bank.want(st["inst"], st["oct"])
                elif row == 2:
                    st["vol"] = min(100, max(0, st["vol"] + 10 * sign))
                elif row == 3:
                    st["rhythm"] = (st["rhythm"] + sign) % len(RHYTHMS)
                    if rhythm.pattern is not None:
                        rhythm.pattern = RHYTHMS[st["rhythm"]][1]
                elif row == 4:
                    st["bpm"] = min(220, max(50, st["bpm"] + 5 * sign))
        rhythm.bpm = st["bpm"]
        rhythm.vol = 0.7 * st["vol"] / 100
        draw(st, row, held, bank, rhythm)
        clock.tick(30)


if __name__ == "__main__":
    try:
        main()
    finally:
        pygame.mixer.stop()
        screen.fill(BG)
        lcd.flip()
        lcd.quit()
