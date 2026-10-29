"""ЗОРЯНИЙ ТОРГОВЕЦЬ music: the docking computer's waltz - the opening theme of Johann Strauss II's
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
