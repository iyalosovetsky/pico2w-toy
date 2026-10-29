"""ЗОРЯНИЙ ТОРГОВЕЦЬ sound: the hull knocks, the explosions, the laser, hits, the missile and its lock; the docking computer's waltz - the opening theme of Johann Strauss II's
"The Blue Danube" (1866, public domain), our own small arrangement: a soft melody over an oom-pah-pah of
bass and chords, synthesized with numpy (no recordings).
"""
import numpy as np
import pygame

import lcd

RATE = lcd.RATE
BEAT = 0.34                           # a quarter at ~176 a minute: a lively Viennese waltz
NOTES = {"C": 0, "C#": 1, "D": 2, "D#": 3, "E": 4, "F": 5, "F#": 6, "G": 7, "G#": 8, "A": 9, "A#": 10, "B": 11}

# the melody, note:beats (r - a rest); 3 beats a bar
THEME = """
D4:1 D4:1 F#4:1 A4:3 r:1 A5:1 A5:1 r:1 F#5:1 F#5:1
D4:1 D4:1 F#4:1 A4:3 r:1 B5:1 B5:1 r:1 G5:1 G5:1
C#4:1 C#4:1 E4:1 B4:3 r:1 B5:1 B5:1 r:1 G5:1 G5:1
C#4:1 C#4:1 E4:1 B4:3 r:1 A5:1 A5:1 r:1 F#5:1 F#5:1
D4:1 D4:1 F#4:1 A4:1 D5:2 r:1 D6:1 D6:1 r:1 A5:1 A5:1
D4:1 D4:1 F#4:1 A4:1 D5:2 r:1 D6:1 D6:1 r:1 B5:1 B5:1
E4:1 E4:1 G4:1 B4:3 B4:2 G#4:1 A4:3 F#5:2 D5:1 D5:2 F#4:1 F#4:2 E4:1 B4:2 A4:1 D4:3 r:3
"""
# a chord a bar
BARS = "D D D D  D D A7 A7  A7 A7 A7 A7  A7 A7 D D  D D D D  D D G G  Em Em A7 A7 D D A7 A7 D D"
CHORDS = {"D": ("D3", ("A3", "D4", "F#4")), "A7": ("A2", ("G3", "C#4", "E4")),
          "G": ("G2", ("G3", "B3", "D4")), "Em": ("E3", ("G3", "B3", "E4"))}


def freq(name):
    midi = 12 * (int(name[-1]) + 1) + NOTES[name[:-1]]
    return 440.0 * 2 ** ((midi - 69) / 12.0)


def voice(f, secs, kind):
    n = int(secs * RATE)
    t = np.arange(n) / RATE
    if kind == "lead":                 # a soft flute-and-strings: a little vibrato that comes in late
        vib = 1 + 0.004 * np.sin(2 * np.pi * 5.2 * t) * np.clip((t - 0.25) * 3, 0, 1)
        ph = 2 * np.pi * f * np.cumsum(vib) / RATE
        y = np.sin(ph) + 0.28 * np.sin(2 * ph) + 0.1 * np.sin(3 * ph)
        env = np.minimum(1, t / 0.02) * (0.65 + 0.35 * np.exp(-t * 4))
        rel = min(n, int(0.06 * RATE))
        env[-rel:] *= np.linspace(1, 0, rel)
    elif kind == "bass":               # a plucked low note
        ph = 2 * np.pi * f * t
        y = np.sin(ph) + 0.45 * np.sin(2 * ph) + 0.2 * np.sin(3 * ph)
        env = np.minimum(1, t / 0.008) * np.exp(-t * 5)
    else:                              # the "pah": short and light
        ph = 2 * np.pi * f * t
        y = np.sin(ph) + 0.2 * np.sin(3 * ph)
        env = np.minimum(1, t / 0.006) * np.exp(-t * 11)
    return y * env


def danube():
    """The whole theme as one buffer (it loops), about 36 seconds."""
    notes = [(a, float(b)) for a, b in (w.split(":") for w in THEME.split())]
    total = sum(b for _, b in notes)
    out = np.zeros(int((total * BEAT + 1) * RATE), np.float32)
    pos = 0.0
    for name, beats in notes:
        if name != "r":
            y = voice(freq(name), beats * BEAT * 0.96, "lead") * 0.5
            i = int(pos * BEAT * RATE)
            out[i:i + len(y)] += y
        pos += beats
    for bar, ch in enumerate(BARS.split()):
        root, tri = CHORDS[ch]
        i = int(bar * 3 * BEAT * RATE)
        y = voice(freq(root), BEAT * 1.2, "bass") * 0.42
        y += voice(freq(root) * 2, BEAT * 1.2, "bass") * 0.12        # the octave: the speaker is small
        out[i:i + len(y)] += y[:len(out) - i]
        for beat in (1, 2):
            j = i + int(beat * BEAT * RATE)
            for nm in tri:
                z = voice(freq(nm), BEAT * 0.6, "chord") * 0.1
                out[j:j + len(z)] += z[:max(0, len(out) - j)]
    out = out[:int(total * BEAT * RATE)]
    out *= 0.85 / max(1e-6, np.abs(out).max()) * lcd.VOLUME
    return out


# ---------------------------------------------------------------- sound effects

def band(y, lo, hi):
    """Keep lo..hi Hz (an FFT mask: the buffers are short)."""
    f = np.fft.rfft(y)
    hz = np.fft.rfftfreq(len(y), 1.0 / RATE)
    f[(hz < lo) | (hz > hi)] = 0
    return np.fft.irfft(f, len(y))


def crash(heavy, seed=1):
    """A hull knock: a low thud, the metal ringing (inharmonic partials, each fading at its own rate),
    a scrape of plating and a hiss of debris; heavy - the station: lower, longer, more scrape."""
    rnd = np.random.default_rng(seed)
    secs = 2.0 if heavy else 0.9
    n = int(secs * RATE)
    t = np.arange(n) / RATE
    k = 0.5 if heavy else 1.25                      # the pitch of the metal
    f0 = (75 if heavy else 160) * np.exp(-t * 6) + (36 if heavy else 45)
    thud = np.sin(2 * np.pi * np.cumsum(f0) / RATE) * np.exp(-t * (7 if heavy else 11))
    thud += 0.5 * np.sin(2 * 2 * np.pi * np.cumsum(f0) / RATE) * np.exp(-t * 12)
    ring = np.zeros(n)
    for f, d, a in ((287, 2.2, 0.5), (461, 3.0, 0.45), (733, 3.8, 0.4), (1013, 5.0, 0.3), (1391, 6.5, 0.25),
                    (1877, 8.0, 0.2), (2469, 10.0, 0.12)):
        f = f * k * (1 + rnd.uniform(-0.01, 0.01))
        ring += a * np.sin(2 * np.pi * f * t + rnd.uniform(0, 6.3)) * np.exp(-t * d * (0.8 if heavy else 1.3)) \
            * (1 + 0.25 * np.sin(2 * np.pi * rnd.uniform(3, 7) * t))           # a slow beating
    if heavy:                                       # the big hull booming: low modes, slow to die
        for f, d, a in ((96, 2.5, 0.7), (143, 3.2, 0.5), (191, 4.0, 0.35)):
            ring += a * np.sin(2 * np.pi * f * t + rnd.uniform(0, 6.3)) * np.exp(-t * d)
    hiss = band(rnd.uniform(-1, 1, n), 800, 6000) * np.exp(-t * 14) * 1.6
    scrape = band(rnd.uniform(-1, 1, n), 150 if heavy else 300, 1100 if heavy else 1800) * np.clip(1 - t / (0.7 if heavy else 0.3), 0, 1) ** 1.5
    scrape *= 0.6 + 0.4 * np.sign(np.sin(2 * np.pi * 23 * t + 2 * np.sin(2 * np.pi * 7 * t)))   # judder
    y = (1.3 if heavy else 1.0) * thud + 0.55 * ring + (0.2 if heavy else 0.35) * hiss + (0.45 if heavy else 0.2) * scrape
    y[:int(0.002 * RATE)] *= np.linspace(0, 1, int(0.002 * RATE))
    return y / np.abs(y).max()


def explosion(seed=2, secs=2.6):
    """A blast: a noise burst falling from bright to a rumble, crackles of debris after it."""
    rnd = np.random.default_rng(seed)
    n = int(secs * RATE)
    t = np.arange(n) / RATE
    noise = rnd.uniform(-1, 1, n)
    bright = band(noise, 400, 7000) * np.exp(-t * 7)
    rumble = band(noise, 30, 400) * np.exp(-t * 1.6) * 2.5
    f0 = 70 * np.exp(-t * 2) + 30
    boom = np.sin(2 * np.pi * np.cumsum(f0) / RATE) * np.exp(-t * 3)
    crackle = np.zeros(n)
    for _ in range(60):
        i = int(rnd.uniform(0.15, 2.2) * RATE)
        m = int(rnd.uniform(0.004, 0.02) * RATE)
        i = min(i, n - m - 1)
        crackle[i:i + m] += rnd.uniform(-1, 1, m) * rnd.uniform(0.3, 1) * np.exp(-(i / RATE) * 1.2)
    y = bright + rumble + boom + 0.5 * band(crackle, 1000, 8000)
    y[:int(0.003 * RATE)] *= np.linspace(0, 1, int(0.003 * RATE))
    return y / np.abs(y).max()


def laser():
    """A pulse laser's "pew": a bright buzz falling fast, a breath of noise."""
    n = int(0.17 * RATE)
    t = np.arange(n) / RATE
    f = 1900 * np.exp(-t * 14) + 260
    ph = 2 * np.pi * np.cumsum(f) / RATE
    y = 0.6 * np.sin(ph) + 0.3 * np.sign(np.sin(ph)) + 0.15 * np.sin(2.01 * ph)
    y += 0.25 * band(np.random.default_rng(4).uniform(-1, 1, n), 2000, 8000) * np.exp(-t * 40)
    y *= np.minimum(1, t / 0.003) * np.exp(-t * 11)
    return y / np.abs(y).max()


def zap():
    """A hit: sparks off a shield - a crackle and a high blip."""
    n = int(0.14 * RATE)
    t = np.arange(n) / RATE
    y = band(np.random.default_rng(5).uniform(-1, 1, n), 1800, 9000) * np.exp(-t * 30) * 1.5
    y += 0.5 * np.sin(2 * np.pi * (3200 - 9000 * t) * t) * np.exp(-t * 45)
    return y / np.abs(y).max()


def missile():
    """A missile away: an ignition pop, a hiss rising from dull to bright, the motor's rumble trailing off."""
    rnd = np.random.default_rng(6)
    n = int(1.5 * RATE)
    t = np.arange(n) / RATE
    noise = rnd.uniform(-1, 1, n)
    dull = band(noise, 150, 900) * np.clip(1 - t / 0.5, 0, 1)
    bright = band(noise, 900, 6000) * np.clip(t / 0.35, 0, 1) * np.exp(-np.clip(t - 0.35, 0, None) * 2.6)
    rumble = band(noise, 35, 220) * np.exp(-t * 1.8) * 2.2
    f0 = 55 + 25 * np.sin(2 * np.pi * 7 * t)
    roar = np.sin(2 * np.pi * np.cumsum(f0) / RATE) * np.exp(-t * 2.2) * 0.6
    pop = np.sin(2 * np.pi * 180 * t) * np.exp(-t * 60) * 1.5
    y = dull + 1.2 * bright + rumble + roar + pop
    y[:int(0.002 * RATE)] *= np.linspace(0, 1, int(0.002 * RATE))
    return y / np.abs(y).max()


def lock():
    """A target locked: two short rising beeps."""
    out = []
    for f in (1400, 1900):
        t = np.arange(int(0.05 * RATE)) / RATE
        out += [np.sin(2 * np.pi * f * t) * np.minimum(1, (0.05 - t) / 0.01), np.zeros(int(0.03 * RATE))]
    return np.concatenate(out) * 0.6


class Sfx:
    """The game's own effects, made on first use and kept."""

    MAKERS = {"crash_heavy": lambda: crash(True), "crash": lambda: crash(False), "explosion": explosion,
              "boom": lambda: explosion(7, 1.7), "laser": laser, "zap": zap, "missile": missile, "lock": lock}

    def __init__(self):
        self.snd = {}

    def ready(self):
        if lcd.sound_enabled():
            pygame.mixer.set_num_channels(16)           # lasers, hits and blasts overlap
            for name in self.MAKERS:
                self.get(name)

    def get(self, name):
        if name not in self.snd:
            y = self.MAKERS[name]() * 0.9 * lcd.VOLUME
            self.snd[name] = pygame.mixer.Sound(buffer=(np.clip(y, -1, 1) * 32000).astype(np.int16).tobytes())
        return self.snd[name]

    def play(self, name):
        if lcd.sound_enabled():
            self.get(name).play()


class Music:
    """The waltz on its own channel: start (it loops), fade out."""

    def __init__(self):
        self.snd = None
        self.chan = None

    def ready(self):
        """Make the buffer (about a second on the Zero) - call it while a title shows."""
        if self.snd is None and lcd.sound_enabled():
            y = danube()
            self.snd = pygame.mixer.Sound(buffer=(np.clip(y, -1, 1) * 32000).astype(np.int16).tobytes())
        return self.snd is not None

    def playing(self):
        return self.chan is not None and self.chan.get_busy()

    def start(self):
        if not self.ready() or self.playing():
            return
        self.chan = pygame.mixer.Channel(5)
        self.chan.play(self.snd, loops=-1, fade_ms=400)

    def stop(self, ms=1200):
        if self.playing():
            self.chan.fadeout(ms)
