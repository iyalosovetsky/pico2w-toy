#!/usr/bin/env python3
"""Save what is on the LCD (/dev/fb0, 128x128 RGB565) as a PNG.

    python3 tools/snap.py shot.png [scale]
"""
import sys

import numpy as np
from PIL import Image


def grab(fb="/dev/fb0", size=128):
    with open(fb, "rb") as f:
        raw = f.read(size * size * 2)
    px = np.frombuffer(raw, dtype="<u2").reshape(size, size)
    rgb = np.dstack([(px >> 11 & 31) << 3, (px >> 5 & 63) << 2, (px & 31) << 3]).astype(np.uint8)
    return Image.fromarray(rgb)


if __name__ == "__main__":
    scale = int(sys.argv[2]) if len(sys.argv) > 2 else 3
    img = grab()
    img.resize((img.width * scale, img.height * scale), Image.NEAREST).save(sys.argv[1])
