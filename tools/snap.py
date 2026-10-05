#!/usr/bin/env python3
"""Save what is on the LCD (panel-mipi-dbi framebuffer, 128x128 RGB565) as a PNG.

    python3 tools/snap.py shot.png [scale]
"""
import glob
import os
import sys

import numpy as np
from PIL import Image


def lcd_fb():
    """The LCD's /dev/fbN (HDMI may be fb0 when it is connected)."""
    for path in sorted(glob.glob("/sys/class/graphics/fb[0-9]*")):
        with open(path + "/name") as f:
            if "mipi" in f.read():
                return "/dev/" + os.path.basename(path)
    raise RuntimeError("LCD framebuffer not found")


def grab(fb=None, size=128):
    with open(fb or lcd_fb(), "rb") as f:
        raw = f.read(size * size * 2)
    px = np.frombuffer(raw, dtype="<u2").reshape(size, size)
    rgb = np.dstack([(px >> 11 & 31) << 3, (px >> 5 & 63) << 2, (px & 31) << 3]).astype(np.uint8)
    return Image.fromarray(rgb)


if __name__ == "__main__":
    scale = int(sys.argv[2]) if len(sys.argv) > 2 else 3
    img = grab()
    img.resize((img.width * scale, img.height * scale), Image.NEAREST).save(sys.argv[1])
