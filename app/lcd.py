"""Pygame output + buttons for the Waveshare 1.44" LCD HAT (panel-mipi-dbi driver).

Usage:
    import lcd, pygame
    screen = lcd.init()          # 128x128 pygame Surface
    while True:
        for ev in pygame.event.get(): ...   # buttons arrive as KEYDOWN/KEYUP
        ... draw on screen ...
        lcd.flip()
"""
import glob
import os
import struct
import select
import time

import numpy as np

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
import pygame  # noqa: E402

WIDTH = HEIGHT = 128

# evdev keycode -> pygame key
KEYMAP = {
    103: pygame.K_UP, 108: pygame.K_DOWN, 105: pygame.K_LEFT, 106: pygame.K_RIGHT,
    28: pygame.K_RETURN, 2: pygame.K_1, 3: pygame.K_2, 4: pygame.K_3,
    # extra keys from a USB keyboard
    1: pygame.K_ESCAPE, 57: pygame.K_SPACE, 96: pygame.K_RETURN,
}

_fb = None
_screen = None
_inputs = []
_input_paths = {}  # fd -> /dev/input/eventN
_last_scan = 0.0
RESCAN_SECONDS = 2  # pick up keyboards plugged in later
_EVENT = struct.Struct("llHHi")  # struct input_event


def _find_fb():
    for path in sorted(glob.glob("/sys/class/graphics/fb[0-9]*")):
        with open(path + "/name") as f:
            if "mipi" in f.read():
                return "/dev/" + os.path.basename(path)
    raise RuntimeError("LCD framebuffer not found (is the mipi-dbi-spi overlay loaded?)")


def _is_keyboard(path):
    """True if the evdev device has letter keys and Enter (i.e. a real keyboard)."""
    try:
        with open(path + "/device/capabilities/key") as f:
            words = f.read().split()
    except OSError:
        return False
    bits = 0
    for w in words:  # most significant word first, one C long each
        bits = (bits << (struct.calcsize("l") * 8)) | int(w, 16)
    return all(bits >> code & 1 for code in (28, 30, 44))  # ENTER, A, Z


def _scan_inputs():
    """Open HAT buttons and USB keyboards that are not open yet."""
    global _last_scan
    _last_scan = time.monotonic()
    known = set(_input_paths.values())
    for path in glob.glob("/sys/class/input/event*"):
        dev = "/dev/input/" + os.path.basename(path)
        if dev in known:
            continue
        try:
            with open(path + "/device/name") as f:
                name = f.read().strip()
            if name.startswith("button@") or _is_keyboard(path):  # HAT buttons or USB keyboard
                fd = os.open(dev, os.O_RDONLY | os.O_NONBLOCK)
                _inputs.append(fd)
                _input_paths[fd] = dev
        except OSError:
            pass  # device vanished or not accessible (yet)


def _pump_buttons():
    if time.monotonic() - _last_scan > RESCAN_SECONDS:
        _scan_inputs()
    if not _inputs:
        return
    ready, _, _ = select.select(_inputs, [], [], 0)
    for fd in ready:
        try:
            data = os.read(fd, _EVENT.size * 32)
        except BlockingIOError:
            continue
        except OSError:  # device went away
            _drop_input(fd)
            continue
        for i in range(0, len(data) - _EVENT.size + 1, _EVENT.size):
            _, _, etype, code, value = _EVENT.unpack_from(data, i)
            if etype == 1 and code in KEYMAP and value in (0, 1):  # EV_KEY, no autorepeat
                kind = pygame.KEYDOWN if value else pygame.KEYUP
                pygame.event.post(pygame.event.Event(kind, key=KEYMAP[code], mod=0, unicode="", scancode=code))


def init():
    global _fb, _screen, _inputs
    pygame.init()
    pygame.display.set_mode((1, 1))
    _fb = open(_find_fb(), "r+b", buffering=0)
    _scan_inputs()
    _screen = pygame.Surface((WIDTH, HEIGHT))
    # hide blinking console cursor on the LCD
    try:
        with open("/sys/class/graphics/fbcon/cursor_blink", "w") as f:
            f.write("0")
    except OSError:
        pass
    _orig_get = pygame.event.get

    def get(*a, **kw):
        _pump_buttons()
        return _orig_get(*a, **kw)
    pygame.event.get = get
    return _screen


def flip():
    rgb = pygame.surfarray.pixels3d(_screen).swapaxes(0, 1).astype(np.uint16)
    px = ((rgb[..., 0] >> 3) << 11) | ((rgb[..., 1] >> 2) << 5) | (rgb[..., 2] >> 3)
    _fb.seek(0)
    _fb.write(px.astype("<u2").tobytes())


def quit():
    if _fb:
        _fb.close()
    for fd in _inputs:
        os.close(fd)
    pygame.quit()


def flush_buttons():
    """Drop button events queued while another program was using the HAT."""
    for fd in list(_inputs):
        try:
            while os.read(fd, 4096):
                pass
        except BlockingIOError:
            pass
        except OSError:  # device went away
            _drop_input(fd)
    pygame.event.clear()


def _drop_input(fd):
    _inputs.remove(fd)
    _input_paths.pop(fd, None)
    os.close(fd)
