"""ЗОРЯНИЙ ТОРГОВЕЦЬ sound: the hull knocks, the explosions, the laser, hits, the missile and its lock; the docking computer's waltz - the opening theme of Johann Strauss II's
"The Blue Danube" (1866, public domain), our own small arrangement: a soft melody over an oom-pah-pah of
bass and chords, synthesized with numpy (no recordings).
"""
import hashlib
import os

import numpy as np
import pygame

import lcd

RATE = lcd.RATE
CACHE = os.path.expanduser("~/.cache/lcdtoy")
BEAT = 0.46                           # a quarter at ~130 a minute: an unhurried waltz
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
        k = min(1.0, 400.0 / f)        # the higher the note, the fewer overtones: no squeak
        y = np.sin(ph) + 0.18 * k * np.sin(2 * ph) + 0.05 * k * np.sin(3 * ph)
        env = np.minimum(1, t / 0.045) * (0.7 + 0.3 * np.exp(-t * 3))
        rel = min(n, int(0.09 * RATE))
        env[-rel:] *= np.linspace(1, 0, rel)
    elif kind == "bass":               # a plucked low note
        ph = 2 * np.pi * f * t
        y = np.sin(ph) + 0.45 * np.sin(2 * ph) + 0.2 * np.sin(3 * ph)
        env = np.minimum(1, t / 0.008) * np.exp(-t * 5)
    else:                              # the "pah": short and light
        ph = 2 * np.pi * f * t
        y = np.sin(ph) + 0.08 * np.sin(2 * ph)
        env = np.minimum(1, t / 0.01) * np.exp(-t * 9)
    return y * env


def danube():
    """The whole theme as one buffer (it loops), about 36 seconds."""
    notes = [(a, float(b)) for a, b in (w.split(":") for w in THEME.split())]
    # the answers up in the fifth and sixth octaves come down one: on a small speaker they only squeak
    notes = [(n[:-1] + str(int(n[-1]) - 1) if n != "r" and int(n[-1]) >= 5 and n[:-1] not in ("C", "C#") and
              not (n[-1] == "5" and n[:-1] in ("D", "E")) else n, b) for n, b in notes]
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
    f = np.fft.rfft(out)                               # a gentle roll-off above ~3 kHz
    hz = np.fft.rfftfreq(len(out), 1.0 / RATE)
    f *= 1 / (1 + (hz / 3000.0) ** 4)
    out = np.fft.irfft(f, len(out)).astype(np.float32)
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


# the 8-bit chips' noise: a 15-bit shift register (tap bits 0 and 1) - "white" - or a short loop - "periodic"
_lfsr = {}


def lfsr(periodic=False):
    if periodic not in _lfsr:
        if periodic:
            seq = np.array([1.0] + [-1.0] * 15)
        else:
            r, out = 0x4000, []
            for _ in range(32767):
                bit = (r ^ (r >> 1)) & 1
                r = (r >> 1) | (bit << 14)
                out.append(1.0 if r & 1 else -1.0)
            seq = np.array(out)
        _lfsr[periodic] = seq
    return _lfsr[periodic]


def chip_noise(clock, periodic=False):
    """The register shifted at clock(t) Hz (an array a sample)."""
    seq = lfsr(periodic)
    idx = (np.cumsum(clock) / RATE).astype(np.int64)
    return seq[idx % len(seq)]


def stepped(x, frame=1 / 50.0):
    """Hold each value for a 50 Hz frame, as the old games set their sound chips once a frame."""
    k = max(1, int(frame * RATE))
    return np.repeat(x[::k], k)[:len(x)]


def chip_vol(level):
    """A chip's 4-bit volume: 2 dB a step, 15 - loud, 0 - silent."""
    level = np.clip(np.round(level), 0, 15)
    return np.where(level > 0, 10 ** (-(15 - level) * 2 / 20), 0.0)


def crash_chip():
    """The station knock the 8-bit way: a crunch of white noise sliding down in steps, a square-wave thump,
    a rattle of periodic noise - every value changed once a frame, the volume in 2 dB steps."""
    n = int(1.3 * RATE)
    t = np.arange(n) / RATE
    clock = stepped(9000 * np.exp(-t * 3.2) + 350)
    crunch = chip_noise(clock) * chip_vol(stepped(15 - t * 15 / 1.1))
    tf = stepped(140 * np.exp(-t * 7) + 32)
    thump = np.sign(np.sin(2 * np.pi * np.cumsum(tf) / RATE)) * chip_vol(stepped(15 - t * 15 / 0.42))
    late = np.clip(t - 0.1, 0, None)
    rattle = chip_noise(stepped(1800 * np.exp(-late * 4) + 120), True) * chip_vol(stepped(np.where(t < 0.1, 0, 12 - late * 12 / 0.6)))
    y = 0.55 * crunch + 0.5 * thump + 0.3 * rattle
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


def hyper():
    """Into hyperspace: a swirl of tones climbing and spreading, a rising hiss, a thump at the end."""
    rnd = np.random.default_rng(8)
    n = int(2.9 * RATE)
    t = np.arange(n) / RATE
    y = np.zeros(n)
    for k, d in enumerate((1.0, 1.26, 1.5, 2.0)):
        f = (180 + 900 * (t / 2.9) ** 2) * d * (1 + 0.02 * np.sin(2 * np.pi * (5 + k) * t))
        y += np.sin(2 * np.pi * np.cumsum(f) / RATE) * (0.5 / (k + 1))
    y *= np.clip(t / 0.4, 0, 1) * np.clip((2.9 - t) / 0.3, 0, 1)
    hiss = band(rnd.uniform(-1, 1, n), 1500, 7000) * (t / 2.9) ** 2 * 0.8
    thump = np.sin(2 * np.pi * 60 * np.clip(t - 2.55, 0, None)) * np.exp(-np.clip(t - 2.55, 0, None) * 9) * (t > 2.55)
    y = y + hiss + thump * 1.4
    return y / np.abs(y).max()


def jump():
    """The jump drive kicking in: a low surge and a whoosh that fades."""
    rnd = np.random.default_rng(9)
    n = int(1.4 * RATE)
    t = np.arange(n) / RATE
    f = 70 + 160 * (1 - np.exp(-t * 4))
    surge = np.sin(2 * np.pi * np.cumsum(f) / RATE) * np.exp(-t * 1.6)
    whoosh = band(rnd.uniform(-1, 1, n), 300, 3000) * np.sin(np.pi * np.clip(t / 1.4, 0, 1)) * 0.9
    y = surge + whoosh
    y[:int(0.01 * RATE)] *= np.linspace(0, 1, int(0.01 * RATE))
    return y / np.abs(y).max()


def scoop():
    """A canister taken aboard: a clunk of the hatch and a rising chirp."""
    n = int(0.35 * RATE)
    t = np.arange(n) / RATE
    clunk = np.sin(2 * np.pi * 140 * t) * np.exp(-t * 30) + 0.4 * band(np.random.default_rng(10).uniform(-1, 1, n),
                                                                      200, 1500) * np.exp(-t * 40)
    f = 600 + 1400 * np.clip((t - 0.08) / 0.2, 0, 1)
    chirp = np.sin(2 * np.pi * np.cumsum(f) / RATE) * ((t > 0.08) & (t < 0.3)) * 0.5
    y = clunk + chirp
    return y / np.abs(y).max()


def elaser():
    """Their laser: lower and harsher than ours."""
    n = int(0.2 * RATE)
    t = np.arange(n) / RATE
    f = 900 * np.exp(-t * 9) + 140
    ph = 2 * np.pi * np.cumsum(f) / RATE
    y = np.sign(np.sin(ph)) * 0.5 + 0.5 * np.sin(1.5 * ph)
    y *= np.minimum(1, t / 0.004) * np.exp(-t * 9)
    return y / np.abs(y).max() * 0.8


def shield():
    """A hit on our shield, the 8-bit way: a short crunch falling in steps, a buzz under it."""
    n = int(0.32 * RATE)
    t = np.arange(n) / RATE
    crunch = chip_noise(stepped(7000 * np.exp(-t * 7) + 500)) * chip_vol(stepped(15 - t * 15 / 0.3))
    buzz = np.sign(np.sin(2 * np.pi * np.cumsum(stepped(220 - 300 * t)) / RATE)) * chip_vol(stepped(12 - t * 12 / 0.2))
    y = 0.7 * crunch + 0.35 * buzz
    return y / np.abs(y).max()


def ecm():
    """The countermeasures: a warbling 8-bit sweep up and down."""
    n = int(0.7 * RATE)
    t = np.arange(n) / RATE
    f = stepped(900 + 700 * np.sin(2 * np.pi * 6 * t))
    y = np.sign(np.sin(2 * np.pi * np.cumsum(f) / RATE)) * chip_vol(stepped(14 - t * 14 / 0.7))
    return y * 0.7


def lock():
    """A target locked: two short rising beeps."""
    out = []
    for f in (1400, 1900):
        t = np.arange(int(0.05 * RATE)) / RATE
        out += [np.sin(2 * np.pi * f * t) * np.minimum(1, (0.05 - t) / 0.01), np.zeros(int(0.03 * RATE))]
    return np.concatenate(out) * 0.6


class Sfx:
    """The game's own effects, made on first use and kept."""

    MAKERS = {"crash_heavy": crash_chip, "crash": lambda: crash(False), "explosion": explosion,
              "boom": lambda: explosion(7, 1.7), "laser": laser, "zap": zap, "missile": missile, "lock": lock,
              "hyper": hyper, "jump": jump, "scoop": scoop, "elaser": elaser, "shield": shield, "ecm": ecm}

    def __init__(self):
        self.snd = {}

    def load(self, bufs):
        """The sounds from buffers() (made in a worker, turned into mixer sounds here)."""
        if lcd.sound_enabled():
            pygame.mixer.set_num_channels(16)           # lasers, hits and blasts overlap
            for name in self.MAKERS:
                if name in bufs and name not in self.snd:
                    self.snd[name] = pygame.mixer.Sound(buffer=bufs[name].tobytes())

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

    def load(self, bufs):
        if self.snd is None and lcd.sound_enabled() and "danube" in bufs:
            self.snd = pygame.mixer.Sound(buffer=bufs["danube"].tobytes())

    def ready(self):
        """The buffer, made now if the loader has not brought it (about a second on the Zero)."""
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


def buffers():
    """Every sound as int16 samples: from the disk cache, or made (many seconds on the Zero: the 15-bit noise
    register alone is 32767 steps of Python) and saved there for the next start. Numpy only - a worker
    thread may run it. The cache's name has a hash of this file and the volume: change a sound, it is remade."""
    with open(__file__, "rb") as f:
        key = hashlib.sha1(f.read() + repr((lcd.VOLUME, RATE)).encode()).hexdigest()[:12]
    path = os.path.join(CACHE, "startrader-sounds-%s.npz" % key)
    try:
        with np.load(path) as z:
            return {k: z[k] for k in z.files}
    except (OSError, ValueError, KeyError):
        pass
    out = {name: (np.clip(make() * 0.9 * lcd.VOLUME, -1, 1) * 32000).astype(np.int16)
           for name, make in Sfx.MAKERS.items()}
    out["danube"] = (np.clip(danube(), -1, 1) * 32000).astype(np.int16)
    try:
        os.makedirs(CACHE, exist_ok=True)
        for old in os.listdir(CACHE):                  # an older version's cache
            if old.startswith("startrader-sounds-") and old != os.path.basename(path):
                os.remove(os.path.join(CACHE, old))
        np.savez(path + ".tmp.npz", **out)
        os.replace(path + ".tmp.npz", path)
    except OSError:
        pass
    return out
