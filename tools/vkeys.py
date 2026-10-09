#!/usr/bin/env python3
"""Virtual keyboard: play a key script into the menu/games (needs root for /dev/uinput).

    sudo python3 tools/vkeys.py "wait 3; down down enter; wait 2; type hello; enter; esc"

Words: key names (up down left right enter esc space tab backspace ctrl alt caps key1 key2
key3, any letter/digit, combos like ctrl+d), "wait <sec>", "hold <key> <sec>",
"type <text>" (US layout). The HAT buttons
KEY1..KEY3 send the same codes as the keyboard digits 1..3.
Used to record the README GIFs and to test without touching the device.
"""
import fcntl
import os
import struct
import sys
import time

UI_SET_EVBIT, UI_SET_KEYBIT, UI_DEV_CREATE, UI_DEV_DESTROY = 0x40045564, 0x40045565, 0x5501, 0x5502
EV_SYN, EV_KEY = 0, 1
KEY_LEFTSHIFT = 42
NAMES = {"esc": 1, "backspace": 14, "tab": 15, "enter": 28, "space": 57,
         "up": 103, "down": 108, "left": 105, "right": 106,
         "key1": 2, "key2": 3, "key3": 4, "ctrl": 29, "alt": 56, "caps": 58, "shift": 42, "f1": 59}
CHARS = {}
for row, first in (("1234567890-=", 2), ("qwertyuiop[]", 16), ("asdfghjkl;'", 30), ("zxcvbnm,./", 44)):
    for i, ch in enumerate(row):
        CHARS[ch] = (first + i, False)
for plain, shifted in zip("1234567890-=[];',./", "!@#$%^&*()_+{}:\"<>?"):
    CHARS[shifted] = (CHARS[plain][0], True)
for ch in "abcdefghijklmnopqrstuvwxyz":
    CHARS[ch.upper()] = (CHARS[ch][0], True)
CHARS[" "] = (57, False)


class Keyboard:
    def __init__(self):
        self.fd = os.open("/dev/uinput", os.O_WRONLY)
        fcntl.ioctl(self.fd, UI_SET_EVBIT, EV_KEY)
        for code in range(1, 120):
            fcntl.ioctl(self.fd, UI_SET_KEYBIT, code)
        name = b"virtual-kbd".ljust(80, b"\0")
        os.write(self.fd, name + struct.pack("HHHHi", 3, 1, 1, 1, 0) + bytes(4 * 64 * 4))
        fcntl.ioctl(self.fd, UI_DEV_CREATE)
        time.sleep(3)  # let udev set permissions and the apps (re)scan input devices

    def _event(self, code, value):
        os.write(self.fd, struct.pack("llHHi", 0, 0, EV_KEY, code, value) +
                 struct.pack("llHHi", 0, 0, EV_SYN, 0, 0))

    def tap(self, code, shift=False):
        if shift:
            self._event(KEY_LEFTSHIFT, 1)
        self._event(code, 1)
        time.sleep(0.05)
        self._event(code, 0)
        if shift:
            self._event(KEY_LEFTSHIFT, 0)
        time.sleep(0.12)

    def press(self, code, seconds):
        self._event(code, 1)
        time.sleep(seconds)
        self._event(code, 0)
        time.sleep(0.12)

    def close(self):
        fcntl.ioctl(self.fd, UI_DEV_DESTROY)
        os.close(self.fd)


def run(script, kbd):
    for command in script.replace("\n", ";").split(";"):
        words = command.strip().split(" ", 1)
        if not words[0]:
            continue
        if words[0] == "wait":
            time.sleep(float(words[1]))
        elif words[0] == "hold":
            name, seconds = words[1].split()
            code = NAMES[name] if name in NAMES else CHARS[name][0]
            kbd.press(code, float(seconds))
        elif words[0] == "type":
            for ch in words[1]:
                kbd.tap(*CHARS[ch])
        else:
            for name in command.split():
                if "+" in name and len(name) > 1:  # combo: ctrl+d, alt+shift, ...
                    *mods, key = name.split("+")
                    for m in mods:
                        kbd._event(NAMES[m], 1)
                    kbd.tap(*(((NAMES[key],) if key in NAMES else CHARS[key][:1])))
                    for m in reversed(mods):
                        kbd._event(NAMES[m], 0)
                elif name in NAMES:
                    kbd.tap(NAMES[name])
                else:
                    kbd.tap(*CHARS[name])


if __name__ == "__main__":
    kbd = Keyboard()
    try:
        run(" ".join(sys.argv[1:]) or sys.stdin.read(), kbd)
    finally:
        kbd.close()
