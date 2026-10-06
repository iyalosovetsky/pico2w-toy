"""Pygame output, input and sound for small framebuffer LCDs (panel-mipi-dbi driver).

Supported devices (detected from the framebuffer size):
  * Waveshare 1.44" LCD HAT  - 128x128, joystick + KEY1-3 (gpio-key)
  * PicoCalc with a Zero 2 W - 320x320, I2C keyboard, PWM sound

Usage:
    import lcd, pygame
    screen = lcd.init()          # pygame Surface, always 128x128 *logical* pixels
    while True:
        for ev in pygame.event.get(): ...   # buttons / keyboard arrive as KEYDOWN/KEYUP
        ... draw on screen ...
        lcd.flip()
    lcd.play("hit")              # short sound effect (no-op without a speaker)

Apps draw in a 128x128 coordinate space. On a bigger display everything is
drawn at the real resolution (not upscaled): pygame.draw.*, Surface.blit/fill
and pygame.font.Font are wrapped so positions, sizes and fonts are multiplied
by lcd.S (2.5 on the PicoCalc). Images keep their native pixels; text and
lcd.Surface objects report their size in logical pixels.

While an app runs it grabs the buttons and keyboards (EVIOCGRAB), so key
presses don't also land in a text console.
"""
import fcntl
import glob
import os
import struct
import select
import time

import numpy as np

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")


def _find_fb():
    for path in sorted(glob.glob("/sys/class/graphics/fb[0-9]*")):
        try:
            with open(path + "/name") as f:
                if "mipi" in f.read():
                    return path
        except OSError:
            pass
    return None


def _fb_size(path):
    try:
        with open(path + "/virtual_size") as f:
            w, h = (int(v) for v in f.read().split(","))
        return w, h
    except (OSError, TypeError, ValueError):
        return 128, 128


_FB_SYS = _find_fb()
NATIVE_W, NATIVE_H = (int(v) for v in os.environ["LCD_SIZE"].split("x")) if "LCD_SIZE" in os.environ \
    else _fb_size(_FB_SYS)
WIDTH = HEIGHT = 128                     # logical size every app draws in
S = NATIVE_W / WIDTH                     # 1 on the HAT, 2.5 on the PicoCalc
DEVICE = "picocalc" if NATIVE_W >= 240 else "hat144"

# key names shown in on-screen hints
if DEVICE == "picocalc":
    OK, ALT, BACK = "Enter", "2", "Esc"
else:
    OK, ALT, BACK = "PRESS", "KEY2", "KEY3"

SOUND_FLAG = os.path.expanduser("~/.config/lcdtoy/sound-off")
SOUND = DEVICE == "picocalc" and os.environ.get("LCD_SOUND", "1") != "0"
VOLUME = float(os.environ.get("LCD_VOLUME", "0.5"))
os.environ.setdefault("SDL_AUDIODRIVER", "alsa" if SOUND else "dummy")
import pygame  # noqa: E402

# evdev keycode -> pygame key
KEYMAP = {
    103: pygame.K_UP, 108: pygame.K_DOWN, 105: pygame.K_LEFT, 106: pygame.K_RIGHT,
    28: pygame.K_RETURN, 2: pygame.K_1, 3: pygame.K_2, 4: pygame.K_3,
    # extra keys from a keyboard
    1: pygame.K_ESCAPE, 57: pygame.K_SPACE, 96: pygame.K_RETURN, 15: pygame.K_TAB,
    14: pygame.K_BACKSPACE,
}

_fb = None
_screen = None
_inputs = []
_input_paths = {}  # fd -> /dev/input/eventN
_last_scan = 0.0
RESCAN_SECONDS = 2  # pick up keyboards plugged in later
_EVENT = struct.Struct("llHHi")  # struct input_event
EVIOCGRAB = 0x40044590
_grabbing = True      # grab inputs at all (False while a child app runs)
_grab_keyboards = True  # False while the USB keyboard is lent to the HDMI console
_hat_fds = set()      # HAT buttons (gpio-key), as opposed to keyboards
_sounds = {}
_held_arrows = set()  # pygame arrow keys currently held on a keyboard
_sound_ok = False


# ---------------------------------------------------------------- scaling (S != 1)

def sc(v):
    """Logical length -> native pixels."""
    return int(round(v * S))


def _pt(p):
    return (int(round(p[0] * S)), int(round(p[1] * S)))


def _rect(r):
    r = pygame.Rect(r) if not isinstance(r, pygame.Rect) else r
    x0, y0 = int(round(r.x * S)), int(round(r.y * S))
    x1, y1 = int(round((r.x + r.w) * S)), int(round((r.y + r.h) * S))
    return pygame.Rect(x0, y0, x1 - x0, y1 - y0)


def _frect(x, y, w, h):
    """Like _rect, but keeps fractional logical coordinates (floats from games)."""
    x0, y0 = int(round(x * S)), int(round(y * S))
    return pygame.Rect(x0, y0, int(round((x + w) * S)) - x0, int(round((y + h) * S)) - y0)


def _width(w):
    return 0 if not w else max(1, int(round(w * S)))


class Surface(pygame.Surface):
    """A surface whose coordinates are logical: size, blit/fill positions and
    pygame.draw calls on it are scaled by S. The pixels are native."""

    def __init__(self, size, flags=0, *args, native=False):
        if not native:
            size = (max(1, sc(size[0])), max(1, sc(size[1])))
        super().__init__(size, flags, *args)

    def get_width(self):
        return super().get_width() / S

    def get_height(self):
        return super().get_height() / S

    def get_size(self):
        return (self.get_width(), self.get_height())

    def blit(self, source, dest, area=None, special_flags=0):
        if isinstance(source, Text):
            source = source.img
        if isinstance(dest, pygame.Rect) or (hasattr(dest, "__len__") and len(dest) == 4):
            dest = pygame.Rect(dest).topleft
        return super().blit(source, _pt(dest), area, special_flags)

    def fill(self, color, rect=None, special_flags=0):
        return super().fill(color, None if rect is None else _rect(rect), special_flags)


class Text:
    """Rendered text: native pixels, logical size."""

    def __init__(self, img):
        self.img = img

    def get_width(self):
        return self.img.get_width() / S

    def get_height(self):
        return self.img.get_height() / S

    def get_size(self):
        return (self.get_width(), self.get_height())


class _Font(pygame.font.Font):
    def __init__(self, path, size=12):
        super().__init__(path, max(1, int(round(size * S))))

    def render(self, text, antialias, color, background=None):
        return Text(super().render(text, antialias, color, background))

    def size(self, text):
        w, h = super().size(text)
        return (w / S, h / S)

    def get_height(self):
        return super().get_height() / S

    def get_linesize(self):
        return super().get_linesize() / S


def _install_scaling():
    """Wrap pygame.draw / pygame.font so logical coordinates work on any LCD."""
    d = pygame.draw
    orig = {n: getattr(d, n) for n in ("rect", "line", "circle", "polygon", "ellipse", "lines")}

    def rect(surf, color, r, width=0, border_radius=0, *a, **kw):
        if not isinstance(surf, Surface):
            return orig["rect"](surf, color, r, width, border_radius, *a, **kw)
        nr = _rect(r) if isinstance(r, pygame.Rect) else _frect(*r)
        return orig["rect"](surf, color, nr, _width(width), sc(border_radius) if border_radius else 0)

    def line(surf, color, a, b, width=1):
        if not isinstance(surf, Surface):
            return orig["line"](surf, color, a, b, width)
        return orig["line"](surf, color, _pt(a), _pt(b), _width(width))

    def lines(surf, color, closed, points, width=1):
        if not isinstance(surf, Surface):
            return orig["lines"](surf, color, closed, points, width)
        return orig["lines"](surf, color, closed, [_pt(p) for p in points], _width(width))

    def circle(surf, color, center, radius, width=0, *a, **kw):
        if not isinstance(surf, Surface):
            return orig["circle"](surf, color, center, radius, width, *a, **kw)
        return orig["circle"](surf, color, _pt(center), max(1, sc(radius)), _width(width))

    def polygon(surf, color, points, width=0):
        if not isinstance(surf, Surface):
            return orig["polygon"](surf, color, points, width)
        return orig["polygon"](surf, color, [_pt(p) for p in points], _width(width))

    def ellipse(surf, color, r, width=0):
        if not isinstance(surf, Surface):
            return orig["ellipse"](surf, color, r, width)
        return orig["ellipse"](surf, color, _frect(*r), _width(width))

    d.rect, d.line, d.lines, d.circle, d.polygon, d.ellipse = rect, line, lines, circle, polygon, ellipse
    pygame.font.Font = _Font


# ---------------------------------------------------------------- sound

RATE = 44100   # the PWM card's native rate: no resampling
BUFFER = 2048  # samples (~46 ms): smaller ones underrun while Python draws


def _tone(freq, ms, wave="square", vol=1.0, slide=0.0):
    rate = RATE
    n = max(1, int(rate * ms / 1000))
    t = np.arange(n) / rate
    f = freq + slide * t / max(t[-1], 1e-6)
    phase = 2 * np.pi * np.cumsum(f) / rate
    if wave == "square":
        y = np.sign(np.sin(phase))
    elif wave == "noise":
        y = np.random.uniform(-1, 1, n)
    else:
        y = np.sin(phase)
    env = np.linspace(1, 0.2, n) ** 1.5
    fade = min(n, 60)
    env[-fade:] *= np.linspace(1, 0, fade)
    return y * env * vol


SOUNDS = {  # name -> list of (freq Hz, ms, wave, volume, slide Hz)
    "click": [(1200, 18, "square", 0.25, 0)],
    "move": [(660, 25, "square", 0.25, 0)],
    "select": [(880, 40, "square", 0.3, 0), (1320, 50, "square", 0.3, 0)],
    "hit": [(520, 35, "square", 0.45, 0)],
    "wall": [(300, 25, "square", 0.35, 0)],
    "score": [(880, 70, "square", 0.4, 0), (660, 70, "square", 0.4, 0), (440, 120, "square", 0.4, 0)],
    "point": [(440, 60, "square", 0.4, 0), (880, 110, "square", 0.4, 0)],
    "drop": [(180, 50, "square", 0.45, -80)],
    "line": [(523, 60, "square", 0.4, 0), (659, 60, "square", 0.4, 0), (784, 60, "square", 0.4, 0),
             (1046, 120, "square", 0.4, 0)],
    "card": [(0, 35, "noise", 0.35, 0)],
    "chip": [(2200, 25, "sine", 0.45, 0), (1800, 40, "sine", 0.35, 0)],
    "win": [(523, 110, "square", 0.4, 0), (659, 110, "square", 0.4, 0), (784, 110, "square", 0.4, 0),
            (1046, 260, "square", 0.4, 0)],
    "lose": [(392, 160, "square", 0.4, 0), (330, 160, "square", 0.4, 0), (262, 320, "square", 0.4, -60)],
    "error": [(150, 120, "square", 0.4, 0)],
    "check": [(988, 60, "square", 0.35, 0), (988, 60, "square", 0.0, 0), (988, 90, "square", 0.35, 0)],
}


def _init_sound():
    global _sound_ok
    if not SOUND or os.path.exists(SOUND_FLAG):
        return
    try:
        pygame.mixer.init(RATE, -16, 1, BUFFER)
        _sound_ok = True
    except pygame.error:
        _sound_ok = False


def sound_available():
    return SOUND


def sound_enabled():
    return _sound_ok


def set_sound(on):
    """Turn effects on/off for all apps (remembered in ~/.config/lcdtoy/sound-off)."""
    global _sound_ok
    if on:
        try:
            os.remove(SOUND_FLAG)
        except OSError:
            pass
        if not _sound_ok:
            _init_sound()
    else:
        os.makedirs(os.path.dirname(SOUND_FLAG), exist_ok=True)
        open(SOUND_FLAG, "w").close()
        _sound_ok = False


def release_audio():
    """Free the sound card for a child program (the PWM card is single-user)."""
    global _sound_ok
    if _sound_ok:
        _sounds.clear()
        pygame.mixer.quit()
        _sound_ok = False


def resume_audio():
    """Take the sound card back after a child program exits."""
    if not _sound_ok:
        _init_sound()


def play(name):
    """Play a short sound effect by name (see SOUNDS); silent if there is no speaker."""
    if not _sound_ok:
        return
    snd = _sounds.get(name)
    if snd is None:
        parts = [_tone(f, ms, w, v, sl) for f, ms, w, v, sl in SOUNDS[name]]
        y = np.concatenate(parts) * VOLUME
        snd = pygame.mixer.Sound(buffer=(np.clip(y, -1, 1) * 32000).astype(np.int16).tobytes())
        _sounds[name] = snd
    snd.play()


# ---------------------------------------------------------------- input

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
    """Open HAT buttons and keyboards that are not open yet."""
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
            if name.startswith("button@") or _is_keyboard(path):  # HAT buttons or a keyboard
                fd = os.open(dev, os.O_RDONLY | os.O_NONBLOCK)
                _inputs.append(fd)
                _input_paths[fd] = dev
                if name.startswith("button@"):
                    _hat_fds.add(fd)
                if _grabbing and (fd in _hat_fds or _grab_keyboards):
                    _grab(fd, True)
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
            if etype == 2 and fd not in _hat_fds:
                # EV_REL from a keyboard: the PicoCalc's right Shift switched its driver
                # to mouse mode, arrows now move a pointer and their key-up never
                # comes - release the held ones so nothing stays pressed
                for key in list(_held_arrows):
                    pygame.event.post(pygame.event.Event(pygame.KEYUP, key=key, mod=0, unicode="",
                                                         scancode=0, hat=False))
                _held_arrows.clear()
            elif etype == 1 and code in KEYMAP and value in (0, 1):  # EV_KEY, no autorepeat
                key = KEYMAP[code]
                kind = pygame.KEYDOWN if value else pygame.KEYUP
                if fd not in _hat_fds and key in (pygame.K_UP, pygame.K_DOWN, pygame.K_LEFT, pygame.K_RIGHT):
                    (_held_arrows.add if value else _held_arrows.discard)(key)
                pygame.event.post(pygame.event.Event(kind, key=key, mod=0, unicode="",
                                                     scancode=code, hat=fd in _hat_fds))


# ---------------------------------------------------------------- display

def init():
    global _fb, _screen
    if S != 1:
        _install_scaling()
    pygame.init()
    pygame.display.set_mode((1, 1))
    if _FB_SYS is None and "LCD_SIZE" not in os.environ:
        raise RuntimeError("LCD framebuffer not found (is the mipi-dbi-spi overlay loaded?)")
    if _FB_SYS is not None:
        _fb = open("/dev/" + os.path.basename(_FB_SYS), "r+b", buffering=0)
    _scan_inputs()
    _init_sound()
    _screen = Surface((WIDTH, HEIGHT)) if S != 1 else pygame.Surface((WIDTH, HEIGHT))
    _orig_get = pygame.event.get

    def get(*a, **kw):
        _pump_buttons()
        return _orig_get(*a, **kw)
    pygame.event.get = get
    return _screen


def flip():
    if _fb is None:
        return
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
    """Drop button events queued while another program was using the keys."""
    for fd in list(_inputs):
        try:
            while os.read(fd, 4096):
                pass
        except BlockingIOError:
            pass
        except OSError:  # device went away
            _drop_input(fd)
    pygame.event.clear((pygame.KEYDOWN, pygame.KEYUP))  # keep QUIT (SIGTERM) pending


def _grab(fd, on):
    try:
        fcntl.ioctl(fd, EVIOCGRAB, 1 if on else 0)
    except OSError:
        pass  # already grabbed by someone else, or the device went away


def release_inputs():
    """Let a child program (a game) grab the buttons and keyboards itself."""
    global _grabbing
    _grabbing = False
    for fd in _inputs:
        _grab(fd, False)


def grab_inputs():
    """Take the buttons and keyboards back (exclusive) after a child exits."""
    global _grabbing, _grab_keyboards
    _grabbing = _grab_keyboards = True
    for fd in _inputs:
        _grab(fd, True)


def release_keyboards():
    """Lend the keyboards to the text console; keep the HAT buttons.

    Events keep coming in (with ev.hat telling HAT buttons apart), but the
    keyboards are no longer exclusive, so typing reaches the HDMI console too.
    """
    global _grab_keyboards
    _grab_keyboards = False
    for fd in _inputs:
        if fd not in _hat_fds:
            _grab(fd, False)


def _drop_input(fd):
    _inputs.remove(fd)
    _input_paths.pop(fd, None)
    _hat_fds.discard(fd)
    os.close(fd)
