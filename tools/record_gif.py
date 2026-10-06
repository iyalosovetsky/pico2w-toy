#!/usr/bin/env python3
"""Record the LCD into an animated GIF (what the README shows).

    python3 tools/record_gif.py out.gif --seconds 12 --fps 10 --scale 2

Pair it with tools/vkeys.py to drive the menu/games while recording.
"""
import argparse
import os
import sys
import time

from PIL import Image

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from snap import grab  # noqa: E402

ap = argparse.ArgumentParser()
ap.add_argument("out")
ap.add_argument("--seconds", type=float, default=10)
ap.add_argument("--fps", type=float, default=10)
ap.add_argument("--scale", type=int, default=2)
args = ap.parse_args()

frames, stamps = [], []
start = time.monotonic()
while time.monotonic() - start < args.seconds:
    t = time.monotonic()
    frames.append(grab())
    stamps.append(t)
    time.sleep(max(0, 1 / args.fps - (time.monotonic() - t)))

# drop repeated frames, keeping their time on screen
out, durations = [], []
for img, t, t_next in zip(frames, stamps, stamps[1:] + [start + args.seconds]):
    ms = int((t_next - t) * 1000)
    if out and img.tobytes() == out[-1].tobytes():
        durations[-1] += ms
        continue
    out.append(img)
    durations.append(ms)
w, h = out[0].size
scale = args.scale if w <= 128 else 1  # the 320x320 PicoCalc is recorded 1:1
out = [img.resize((w * scale, h * scale), Image.NEAREST).quantize(colors=128, dither=Image.Dither.NONE) for img in out]
out[0].save(args.out, save_all=True, append_images=out[1:], duration=durations, loop=0, optimize=True)
print("%s: %d frames, %.1f KB" % (args.out, len(out), os.path.getsize(args.out) / 1024))
