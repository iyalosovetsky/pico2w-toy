"""ЗОРЯНИЙ ТОРГОВЕЦЬ sound: the hull knocks, the explosions, the laser, hits, the missile and its lock; the docking computer's waltz - the opening theme of Johann Strauss II's
"The Blue Danube" (1866, public domain), our own small arrangement: a soft melody over an oom-pah-pah of
bass and chords, synthesized with numpy (no recordings).
"""
import hashlib
import os
import time

import numpy as np
import pygame

import lcd

RATE = lcd.RATE
CACHE = os.path.expanduser("~/.cache/lcdtoy")
BEAT = 0.42                           # a quarter at ~143 a minute: an easy Viennese waltz
NOTES = {"C": 0, "C#": 1, "D": 2, "D#": 3, "E": 4, "F": 5, "F#": 6, "G": 7, "G#": 8, "A": 9, "A#": 10, "B": 11}

# the first waltz in D (the main theme checked against the Mutopia Project's piano score, piece 519; the
# second strain read from J. S. Seredy's piano-conductor score, Carl Fischer 1890 - public domain): note:beats,
# r - a rest, a+b - two notes together (the answers come as thirds); 3 beats a bar. The main theme, then the
# second strain in A twice (its first and second endings), and round again - the pick-up D at the very end.
THEME_A = """
D4:1 F#4:1 A4:1  A4:2 F#5+A5:1  F#5+A5:2 D5+F#5:1  D5+F#5:2 D4:1
D4:1 F#4:1 A4:1  A4:2 G5+A5:1  G5+A5:2 C#5+G5:1  C#5+G5:2 C#4:1
C#4:1 E4:1 B4:1  B4:2 G5+B5:1  G5+B5:2 C#5+G5:1  C#5+G5:2 C#4:1
C#4:1 E4:1 B4:1  B4:2 F#5+B5:1  F#5+B5:2 D5+F#5:1  D5+F#5:2 D4:1
D4:1 F#4:1 A4:1  D5:2 A5+D6:1  A5+D6:2 F#5+A5:1  F#5+A5:2 D4:1
D4:1 F#4:1 A4:1  D5:2 B5+D6:1  B5+D6:2 G5+B5:1  G5+B5:2 E4:1
E4:1 G4:1 B4:1  B4:3  B4:1 G#4:1 A4:1  F#5:3  F#5:1 D5:1 F#4:1  F#4:2 E4:1  B4:2 A4:1
D4:1.5 D5:0.5 D5:1  D5:1 D6:0.5 r:0.5 C#6:0.5 r:0.5
"""
# the second strain's short notes: an eighth and an eighth's rest
_B = """
C#6:.5 r:.5 B5:.5 r:.5 B5:.5 r:.5   r:1 B5:.5 r:.5 A#5:.5 r:.5   A#5:.5 r:.5 B5:.5 r:.5 B5:.5 r:.5
r:1 E5:.5 r:.5 E5:.5 r:.5   F#5:2 E5:1   r:1 E5:.5 r:.5 E5:.5 r:.5   B5:2 A5:1   r:1 D6:.5 r:.5 C#6:.5 r:.5
C#6:.5 r:.5 B5:.5 r:.5 B5:.5 r:.5   r:1 B5:.5 r:.5 C#6:.5 r:.5   E6:.5 r:.5 D6:.5 r:.5 C#6:.5 r:.5
r:1 G#5:.5 r:.5 A5:.5 r:.5   A5:3   G#5:1.5 F#5:.5 D5:.5 B4:.5   F#5:.5 F#5:.5 F#5:1 E5:1
"""
THEME = THEME_A + _B + "A4:1 D6:.5 r:.5 C#6:.5 r:.5" + _B + "A4:1 r:1 D4:1"
# a chord a bar
_BARS_B = "E7 E7 E7 E7 E7 E7 A A E7 E7 A E7 D E7 E7 A "
BARS = "D D D D D D A7 A7 A7 A7 A7 A7 A7 A7 A7 D D D D D D D G G Em Em E7 D D A7 A7 D D " + _BARS_B * 2
CHORDS = {"D": ("D3", ("A3", "D4", "F#4")), "A7": ("A2", ("G3", "C#4", "E4")), "A": ("A2", ("A3", "C#4", "E4")),
          "G": ("G2", ("G3", "B3", "D4")), "Em": ("E3", ("G3", "B3", "E4")), "E7": ("E3", ("G#3", "B3", "D4"))}


def freq(name):
    midi = 12 * (int(name[-1]) + 1) + NOTES[name[:-1]]
    return 440.0 * 2 ** ((midi - 69) / 12.0)


def voice(f, secs, kind):
    n = max(1, int(secs * RATE))
    t = np.arange(n) / RATE
    if kind == "horn":                 # warm and round, slow to speak: the low rising arpeggio
        ph = 2 * np.pi * f * np.cumsum(1 + 0.003 * np.sin(2 * np.pi * 4.8 * t) * np.clip(t - 0.4, 0, 1)) / RATE
        y = np.sin(ph) + 0.45 * np.sin(2 * ph) + 0.22 * np.sin(3 * ph) + 0.08 * np.sin(4 * ph)
        env = np.minimum(1, t / 0.07) ** 2 * (0.85 + 0.15 * np.exp(-t * 2))
        rel = min(n, int(0.12 * RATE))
        env[-rel:] *= np.linspace(1, 0, rel)
        return y * env
    if kind == "violin":               # bowed: a soft start, vibrato that grows, a little bow noise
        vib = 1 + 0.0055 * np.sin(2 * np.pi * 5.6 * t) * np.clip((t - 0.15) * 2.5, 0, 1)
        ph = 2 * np.pi * f * np.cumsum(vib) / RATE
        k = min(1.0, 500.0 / f)
        y = np.sin(ph) + 0.32 * k * np.sin(2 * ph) + 0.16 * k * np.sin(3 * ph) + 0.07 * k * np.sin(4 * ph)
        env = np.minimum(1, t / 0.06) * (0.8 + 0.2 * np.exp(-t * 3))
        rel = min(n, int(0.1 * RATE))
        env[-rel:] *= np.linspace(1, 0, rel)
        return y * env
    if kind == "pizz":                 # plucked strings: the second strain's short notes
        ph = 2 * np.pi * f * t
        y = np.sin(ph) + 0.35 * np.sin(2 * ph) * np.exp(-t * 20) + 0.1 * np.sin(3 * ph) * np.exp(-t * 30)
        return y * np.minimum(1, t / 0.004) * np.exp(-t * 7)
    if kind == "pad":                  # the string section under it all: three slightly apart voices
        y = sum(np.sin(2 * np.pi * f * d * t + o) for d, o in ((1.0, 0.0), (1.003, 1.3), (0.997, 2.1)))
        y = y * (1 + 0.15 * np.sin(2 * np.pi * 0.7 * t))
        env = np.minimum(1, t / 0.3) * np.minimum(1, (secs - t) / 0.25).clip(0, 1)
        return y * env / 3
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


def reverb(x, secs=1.1, wet=0.22, seed=12):
    """A hall: the dry sound plus its convolution with a decaying burst of noise, done in blocks (the Zero
    has little memory to spare)."""
    rnd = np.random.default_rng(seed)
    n = int(secs * RATE)
    t = np.arange(n) / RATE
    ir = rnd.uniform(-1, 1, n) * np.exp(-t / (secs / 5.0))
    ir = band(ir, 120, 5000)
    ir[:int(0.012 * RATE)] = 0                          # the first reflections come a little late
    ir /= np.sqrt(np.sum(ir * ir))
    block = 1 << 16
    size = 1 << int(np.ceil(np.log2(block + n)))
    H = np.fft.rfft(ir, size)
    out = np.zeros(len(x) + n, np.float32)
    for i in range(0, len(x), block):
        seg = x[i:i + block]
        y = np.fft.irfft(np.fft.rfft(seg, size) * H, size)[:len(seg) + n]
        out[i:i + len(y)] += y.astype(np.float32)
    return x + wet * out[:len(x)] * 3.0


def danube():
    """The whole waltz as one buffer, arranged: horns for the low rising theme, violins for the answers and
    the long notes, pizzicato for the second strain's short ones, a string pad on the chords, plucked bass,
    soft "pah-pah" - and a touch of hall. About 82 seconds."""
    notes = [(a, float(b)) for a, b in (w.split(":") for w in THEME.split())]
    total = sum(b for _, b in notes)
    out = np.zeros(int((total * BEAT + 2) * RATE), np.float32)

    def put(y, at):
        i = int(at * RATE)
        out[i:i + len(y)] += y[:max(0, len(out) - i)]
    made = {}

    def v(f, secs, kind):
        """A note once made is reused: the tune repeats itself a lot (the Zero makes each in ~50 ms)."""
        key = (round(f, 2), round(secs, 3), kind)
        if key not in made:
            made[key] = voice(f, secs, kind).astype(np.float32)
        return made[key]
    pos = 0.0
    for name, beats in notes:
        if name != "r":
            parts = name.split("+")
            for nm in parts:
                f = freq(nm)
                if beats <= 0.5:
                    kind, vol = "pizz", 0.55
                elif f < 520:                          # below C5: the horns' arpeggio
                    kind, vol = "horn", 0.42
                else:
                    kind, vol = "violin", 0.42
                vol *= 1.0 if len(parts) == 1 else 0.66
                put(v(f, beats * BEAT * 0.97, kind) * vol, pos * BEAT)
        pos += beats
    for bar, ch in enumerate(BARS.split()):
        root, tri = CHORDS[ch]
        at = bar * 3 * BEAT
        put(v(freq(root), BEAT * 1.2, "bass") * 0.36 + v(freq(root) * 2, BEAT * 1.2, "bass") * 0.1, at)
        for nm in tri:                                 # the pad, an octave under the chord, the whole bar
            put(v(freq(nm) / 2, 3 * BEAT + 0.15, "pad") * 0.07, at)
        for beat in (1, 2):
            for nm in tri:
                put(v(freq(nm), BEAT * 0.5, "chord") * 0.07, at + beat * BEAT)
    out = out[:int((total * BEAT + 1.2) * RATE)]
    out = reverb(out)
    # a gentle roll-off above ~3.5 kHz; the transform padded to a power of two: at an awkward length numpy's
    # FFT falls back to a method that wanted 600 MB and the PicoCalc's kernel killed us
    size = 1 << int(np.ceil(np.log2(len(out))))
    f = np.fft.rfft(out, size)
    f *= (1 / (1 + (np.fft.rfftfreq(size, 1.0 / RATE) / 3500.0) ** 4)).astype(np.float32)
    out = np.fft.irfft(f, size)[:len(out)].astype(np.float32)
    # loud enough beside the game's sounds: a soft compressor (tanh) lifts the quiet passages - the pad and the
    # hall had left the peaks where they were and everything else lower
    out /= max(1e-6, np.abs(out).max())
    out = np.tanh(1.7 * out) / np.tanh(1.7)
    return out * 0.92 * lcd.VOLUME


# ---------------------------------------------------------------- sound effects

def band(y, lo, hi):
    """Keep lo..hi Hz (an FFT mask; padded to a power of two - see danube())."""
    size = 1 << int(np.ceil(np.log2(max(2, len(y)))))
    f = np.fft.rfft(y, size)
    hz = np.fft.rfftfreq(size, 1.0 / RATE)
    f[(hz < lo) | (hz > hi)] = 0
    return np.fft.irfft(f, size)[:len(y)]


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


ENGINE_STEPS = 12


def engine_loop(k):
    """The drive at step k (0 - idling .. 11 - flat out), pitched for a small speaker (it plays next to nothing
    under ~150 Hz): a tone at 90..220 Hz with its overtones, a throb, turbine noise at 400..1000 Hz and a soft
    whine climbing with the speed - all periodic in the loop, so it has no seam."""
    rnd = np.random.default_rng(20 + k)
    x = k / (ENGINE_STEPS - 1.0)
    f = 90.0 + 130.0 * x
    periods = max(8, int(round(f * 0.8)))                # about 0.8 s, a whole number of the tone's periods
    n = int(round(periods * RATE / f))
    dur = n / RATE
    t = np.arange(n) / RATE

    def per(hz):                                         # the nearest frequency that fits the loop exactly
        return max(1, round(hz * dur)) / dur
    ff = per(f)
    tone = sum(a * np.sin(2 * np.pi * h * ff * t) for h, a in ((1, 1.0), (2, 0.6), (3, 0.4), (4, 0.25)))
    spec = np.fft.rfft(rnd.normal(0, 1, n))              # periodic noise: shaped in the loop's own spectrum
    hz = np.fft.rfftfreq(n, 1.0 / RATE)
    spec *= np.exp(-((hz - (400 + 600 * x)) / (300 + 200 * x)) ** 2)
    noise = np.fft.irfft(spec, n)
    noise /= max(1e-6, np.abs(noise).max())
    whine = np.sin(2 * np.pi * per(700 + 900 * x) * t)
    throb = 1 + 0.2 * np.sin(2 * np.pi * per(ff / 4) * t)
    y = (0.5 * tone / 2.25 + (0.45 + 0.25 * x) * noise + (0.08 + 0.12 * x) * whine) * throb
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

    MAKERS = {"crash_heavy": crash_chip, "crash": lambda: crash(False), "explosion": explosion,
              "boom": lambda: explosion(7, 1.7), "laser": laser, "zap": zap, "missile": missile, "lock": lock,
              "hyper": hyper, "jump": jump, "scoop": scoop, "elaser": elaser, "shield": shield, "ecm": ecm,
              **{"engine%d" % k: (lambda k=k: engine_loop(k)) for k in range(ENGINE_STEPS)}}

    def __init__(self):
        self.snd = {}

    def load(self, bufs):
        """The sounds from buffers() (made in a worker, turned into mixer sounds here)."""
        if lcd.sound_enabled():
            pygame.mixer.set_num_channels(16)           # lasers, hits and blasts overlap
            pygame.mixer.set_reserved(8)                # 5 - the waltz, 6 and 7 - the engine: effects take 8..15
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


class Engine:
    """The drive's hum on two channels of its own: a loop a speed step, a quick crossfade between steps,
    louder the faster we go."""

    def __init__(self, sfx):
        self.sfx = sfx
        self.cur = -1
        self.which = 0
        self.chans = None

    def set(self, level, on=True):
        if not lcd.sound_enabled():
            return
        if self.chans is None:
            self.chans = [pygame.mixer.Channel(6), pygame.mixer.Channel(7)]
        if not on:
            if self.cur >= 0:
                for c in self.chans:
                    c.fadeout(250)
            self.cur = -1
            return
        level = max(0.0, min(1.0, level))
        k = int(round(level * (ENGINE_STEPS - 1)))
        vol = 0.32 + 0.55 * level
        if k != self.cur:
            snd = self.sfx.get("engine%d" % k)
            old = self.chans[self.which]
            self.which ^= 1
            self.chans[self.which].play(snd, loops=-1, fade_ms=80)
            if self.cur >= 0:
                old.fadeout(120)
            self.cur = k
        self.chans[self.which].set_volume(vol)

    def stop(self):
        self.set(0, on=False)


class Music:
    """The waltz on its own channel: once through (it never loops - round and round it would soon grate),
    a fade out; serenade() - now and then on the title."""
    PAUSE = 180                        # seconds of quiet between plays on the title
    TIMES = 5                          # and then no more

    def __init__(self):
        self.snd = None
        self.chan = None
        self.plays = 0
        self.last = 0.0

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
        self.chan.play(self.snd, fade_ms=400)

    def stop(self, ms=1200):
        if self.playing():
            self.chan.fadeout(ms)

    def serenade(self):
        """Call it every frame on the title: the waltz once, a few minutes' quiet, again - five times at most."""
        now = time.monotonic()
        if self.playing():
            self.last = now
            return
        if self.plays < self.TIMES and (self.plays == 0 or now - self.last >= self.PAUSE) and self.ready():
            self.start()
            self.plays += 1
            self.last = now


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
