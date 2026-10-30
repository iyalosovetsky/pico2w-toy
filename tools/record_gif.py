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



def stable_grab(tries=4):
    """A frame read twice the same: a read while an app writes the framebuffer gets the top
    of the new picture over the bottom of the old one."""
    img = grab()
    for _ in range(tries):
        again = grab()
        if again.tobytes() == img.tobytes():
            break
        img = again
    return img


def mem_free_mb():
    try:
        with open("/proc/meminfo") as f:
            for line in f:
                if line.startswith("MemAvailable:"):
                    return int(line.split()[1]) // 1024
    except OSError:
        pass
    return 1 << 20


# each frame kept as it comes: repeated ones merged (their time on screen added up), the rest scaled and
# quantized at once - a 320x320 frame is 300 KB in RGB, 100 KB as 128 colours (a long recording of the full
# frames once took all of a Zero 2 W's memory and hung it)
out, shown = [], []                  # the distinct frames and when each came on the screen
last_raw = None
start = time.monotonic()
while time.monotonic() - start < args.seconds:
    t = time.monotonic()
    img = stable_grab()
    raw = img.tobytes()
    if raw != last_raw:
        last_raw = raw
        w, h = img.size
        scale = args.scale if w <= 128 else 1  # the 320x320 PicoCalc is recorded 1:1
        out.append(img.resize((w * scale, h * scale), Image.NEAREST).quantize(colors=128, dither=Image.Dither.NONE))
        shown.append(t)
    if mem_free_mb() < 60:
        print("stopping early: little memory left", file=sys.stderr)
        break
    time.sleep(max(0, 1 / args.fps - (time.monotonic() - t)))
end = time.monotonic()
durations = [int((b - a) * 1000) for a, b in zip(shown, shown[1:] + [end])]
out[0].save(args.out, save_all=True, append_images=out[1:], duration=durations, loop=0, optimize=True)
print("%s: %d frames, %.1f KB" % (args.out, len(out), os.path.getsize(args.out) / 1024))
