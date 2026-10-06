#!/usr/bin/env python3
"""Save what is on the LCD (panel-mipi-dbi framebuffer, RGB565) as a PNG.

    python3 tools/snap.py shot.png [scale]     # default scale: 3 on the 128x128 HAT, 1 otherwise
"""
import glob
import os
import sys

import numpy as np
from PIL import Image


def lcd_fb():
    """The LCD's /dev/fbN (HDMI may be fb0 when it is connected) and its size."""
    for path in sorted(glob.glob("/sys/class/graphics/fb[0-9]*")):
        with open(path + "/name") as f:
            if "mipi" in f.read():
                with open(path + "/virtual_size") as f2:
                    w, h = (int(v) for v in f2.read().split(","))
                return "/dev/" + os.path.basename(path), (w, h)
    raise RuntimeError("LCD framebuffer not found")


def grab():
    fb, (w, h) = lcd_fb()
    with open(fb, "rb") as f:
        raw = f.read(w * h * 2)
    px = np.frombuffer(raw, dtype="<u2").reshape(h, w)
    rgb = np.dstack([(px >> 11 & 31) << 3, (px >> 5 & 63) << 2, (px & 31) << 3]).astype(np.uint8)
    return Image.fromarray(rgb)


if __name__ == "__main__":
    img = grab()
    scale = int(sys.argv[2]) if len(sys.argv) > 2 else (3 if img.width <= 128 else 1)
    img.resize((img.width * scale, img.height * scale), Image.NEAREST).save(sys.argv[1])
