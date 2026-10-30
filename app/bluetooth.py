"""BLUETOOTH: gamepads (and other devices) - search, pair, connect, disconnect and forget, on each device
by itself (the HAT and the PicoCalc each keep their own list of paired devices).

It drives bluetoothctl: one interactive copy kept open (its agent says yes to a pairing and to the HID
service, so nothing waits for a typed answer), and short one-off calls every 1.5 s for the lists. If the
adapter is soft-blocked (rfkill) it is unblocked and powered on.

Keys: UP / DOWN - device, Enter - pair / connect / disconnect, s or Tab - search on / off, Del (twice) -
forget the device, Esc - exit. HAT: PRESS - the action, KEY1 - search, KEY2 (twice) - forget, KEY3 - exit.
A gamepad: cross - the action, triangle - search, circle - exit.
"""
import glob
import os
import re
import struct
import subprocess
import sys
import threading
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import pygame  # noqa: E402
import lcd  # noqa: E402

BTCTL = "/usr/bin/bluetoothctl"
SCAN_TIME = 120                      # s of searching, then it stops by itself
POLL = 1.5
GAMEPAD = re.compile(r"dualsense|dualshock|wireless controller|joy-con|switch pro|pxn|xbox|gamepad|controller|joy|8bitdo|"
                     r"pro controller|gamesir|stadia", re.I)
MAC = re.compile(r"^Device ((?:[0-9A-F]{2}:){5}[0-9A-F]{2}) (.*)$")
MODALIAS = re.compile(r"Modalias: \w+:v([0-9A-F]{4})p([0-9A-F]{4})", re.I)
# vendor:product (from the device's Modalias) -> a name to tell the gamepads apart: a DualSense and a
# DualShock 4 both call themselves "Wireless Controller"
PRODUCTS = {"054c:05c4": "DualShock 4 (PS4)", "054c:09cc": "DualShock 4 (PS4)", "054c:0ce6": "DualSense (PS5)",
            "054c:0df2": "DualSense Edge (PS5)", "057e:2009": "Switch Pro", "057e:2006": "Joy-Con (L)",
            "057e:2007": "Joy-Con (R)"}
VENDORS = {"045e": "Xbox"}
ANSI = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]|\x01|\x02")

BG, FG, DIM = (0, 0, 0), (235, 235, 235), (140, 140, 140)
ACCENT, RED, GREEN, BLUE = (255, 200, 0), (240, 90, 80), (90, 220, 110), (90, 160, 255)
FONT_DIR = "/usr/share/fonts/truetype/dejavu/"


def unblock():
    """Lift a soft rfkill block on Bluetooth: /dev/rfkill (the seat's user may write it), else sudo."""
    try:
        fd = os.open("/dev/rfkill", os.O_WRONLY)
        try:
            os.write(fd, struct.pack("IBBBB", 0, 2, 3, 0, 0))     # idx, RFKILL_TYPE_BLUETOOTH, OP_CHANGE_ALL, soft 0
        finally:
            os.close(fd)
        return
    except OSError:
        pass
    for path in glob.glob("/sys/class/rfkill/rfkill*"):
        try:
            with open(path + "/type") as f:
                if f.read().strip() != "bluetooth":
                    continue
        except OSError:
            continue
        subprocess.run(["sudo", "-n", "tee", path + "/soft"], input=b"0", stdout=subprocess.DEVNULL,
                       stderr=subprocess.DEVNULL, timeout=5)


def btctl(*args, timeout=5):
    try:
        out = subprocess.run([BTCTL] + list(args), capture_output=True, timeout=timeout).stdout
    except (OSError, subprocess.TimeoutExpired):
        return ""
    return ANSI.sub("", out.decode("utf-8", "replace"))


def devices(*filt):
    """{mac: name} from `bluetoothctl devices [Paired|Connected]`."""
    out = {}
    for line in btctl("devices", *filt).splitlines():
        m = MAC.match(line.strip())
        if m:
            out[m.group(1)] = m.group(2).strip()
    return out


def named(mac, name):
    """A device with a real name (not only its address, as bluez shows the nameless ones)."""
    return name and name.replace("-", ":").upper() != mac


class Bt:
    """The interactive bluetoothctl (the agent, the scan, the commands) and the device lists."""

    def __init__(self):
        self.lock = threading.Lock()
        self.lines = []
        self.alive = True
        self.powered = None
        self.discovering = False
        self.all, self.paired, self.connected = {}, {}, {}
        self.product = {}                    # mac -> the name by its USB ids (asked once per device)
        self.busy = None                     # what the running job does (shown), or None
        self.result = None                   # (text, colour) of the last job
        self.scan_until = 0.0
        self.proc = subprocess.Popen([BTCTL], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                     stderr=subprocess.STDOUT, bufsize=0)
        threading.Thread(target=self._reader, daemon=True).start()
        threading.Thread(target=self._poller, daemon=True).start()

    def send(self, cmd):
        try:
            self.proc.stdin.write((cmd + "\n").encode())
        except (OSError, ValueError):
            pass

    def _reader(self):
        buf = ""
        while self.alive:
            try:
                chunk = os.read(self.proc.stdout.fileno(), 4096)
            except OSError:
                break
            if not chunk:
                break
            buf += ANSI.sub("", chunk.decode("utf-8", "replace"))
            parts = re.split(r"[\r\n]+", buf)
            buf = parts.pop()
            # the agent's questions come without a newline: answer them here
            if re.search(r"\(yes/no\)", buf) or re.search(r"Authorize service|Request confirmation", buf):
                self.send("yes")
                parts.append(buf)
                buf = ""
            elif re.search(r"Enter (PIN|passkey)", buf):
                self.send("0000")
                parts.append(buf)
                buf = ""
            with self.lock:
                self.lines.extend(p.strip() for p in parts if p.strip())
                del self.lines[:-200]

    def _poller(self):
        unblocked = False
        while self.alive:
            show = btctl("show")
            powered = "Powered: yes" in show
            if not powered and not unblocked:
                unblocked = True
                unblock()
                btctl("power", "on")
                continue
            self.powered = powered
            self.discovering = "Discovering: yes" in show
            self.all = devices()
            self.paired = devices("Paired")
            self.connected = devices("Connected")
            for mac, name in self.all.items():
                if mac not in self.product and (mac in self.paired or GAMEPAD.search(name)):
                    m = MODALIAS.search(btctl("info", mac))
                    ids = (m.group(1) + ":" + m.group(2)).lower() if m else ""
                    self.product[mac] = PRODUCTS.get(ids) or VENDORS.get(ids[:4]) if ids else None
            if self.scan_until and time.monotonic() > self.scan_until:
                self.scan(False)
            time.sleep(POLL)

    def start(self):
        self.send("agent on")
        self.send("default-agent")
        self.send("pairable on")
        self.scan(True)

    def scan(self, on):
        self.scan_until = time.monotonic() + SCAN_TIME if on else 0.0
        self.send("scan on" if on else "scan off")

    def wait(self, mac, ok, bad, timeout):
        """Wait for a line matching `ok` (True) or `bad` (False) from the commands sent; None on a timeout.
        The neighbours' own [CHG] lines (their RSSI, their Connected) are not ours."""
        t_end = time.monotonic() + timeout
        seen = 0
        while time.monotonic() < t_end and self.alive:
            with self.lock:
                new = self.lines[seen:]
                seen = len(self.lines)
            for line in new:
                if line.startswith(("[CHG]", "[NEW]", "[DEL]")) and mac not in line:
                    continue
                if re.search(ok, line):
                    return True
                if re.search(bad, line):
                    return False
            time.sleep(0.1)
        return None

    def _mark(self):
        with self.lock:
            self.lines.clear()

    def job(self, fn, *args):
        if self.busy:
            return
        self.busy = "…"
        threading.Thread(target=self._run, args=(fn,) + args, daemon=True).start()

    def _run(self, fn, *args):
        try:
            self.result = fn(*args)
        finally:
            self.busy = None

    def act(self, mac, name):
        """Pair (a new device), connect (a paired one) or disconnect (a connected one)."""
        if mac in self.connected:
            self.busy = "від'єдную…"
            self._mark()
            self.send("disconnect " + mac)
            r = self.wait(mac, r"Successful disconnected|Connected: no", r"Failed to disconnect|not available", 8)
            return ("Від'єднано", DIM) if r is not False else ("Не вдалося від'єднати", RED)
        if mac not in self.paired:
            self.busy = "спарюю…"
            self.scan(False)
            time.sleep(0.8)
            self._mark()
            self.send("pair " + mac)
            r = self.wait(mac, r"Pairing successful|Paired: yes|AlreadyExists",
                          r"Failed to pair|AuthenticationFailed|AuthenticationCanceled|ConnectionAttemptFailed|"
                          r"not available", 25)
            if not r:
                return ("Не спарилось - тримайте джойстик у режимі спарювання", RED)
        self.busy = "під'єдную…"
        self._mark()
        self.send("trust " + mac)
        self.wait(mac, r"trust succeeded|Trusted: yes", r"Failed", 3)
        self._mark()
        self.send("connect " + mac)
        r = self.wait(mac, r"Connection successful|Connected: yes", r"Failed to connect|not available", 15)
        if r:
            return ("Під'єднано: " + name, GREEN)
        return ("Не під'єдналось - натисніть кнопку на джойстику", RED)

    def forget(self, mac, name):
        self.busy = "забуваю…"
        self._mark()
        self.send("remove " + mac)
        r = self.wait(mac, r"Device has been removed|DEL\] Device", r"Failed to remove|not available", 6)
        return ("Забуто: " + name, DIM) if r is not False else ("Не вдалося забути", RED)

    def close(self):
        self.alive = False
        self.send("scan off")
        self.send("quit")
        try:
            self.proc.wait(2)
        except subprocess.TimeoutExpired:
            self.proc.kill()


screen = lcd.init()
clock = pygame.time.Clock()


def font(name, px):
    size = px / lcd.S if lcd.S != 1 else int(px)
    try:
        return pygame.font.Font(FONT_DIR + name, size)
    except (FileNotFoundError, OSError):
        return pygame.font.Font(None, size)


BIG = lcd.S > 1
f_title = font("DejaVuSans-Bold.ttf", 16 if BIG else 8)
f_label = font("DejaVuSans.ttf", 18 if BIG else 8)
f_bold = font("DejaVuSans-Bold.ttf", 18 if BIG else 8)
f_small = font("DejaVuSans.ttf", 13 if BIG else 7)
HAT = lcd.DEVICE == "hat144"


def text(s, pos, color, f, right=False, center=False):
    img = f.render(s, True, color)
    x, y = pos
    if right:
        x -= img.get_width()
    elif center:
        x -= img.get_width() / 2
    screen.blit(img, (x, y))


def fit(s, f, width):
    if f.size(s)[0] <= width:
        return s
    while s and f.size(s + "…")[0] > width:
        s = s[:-1]
    return s + "…"


def wrap(s, f, width):
    lines, cur = [], ""
    for w in s.split():
        if cur and f.size(cur + " " + w)[0] > width:
            lines.append(cur)
            cur = w
        else:
            cur = (cur + " " + w).strip()
    return lines + [cur] if cur else lines


def label(bt, mac, name):
    """What the gamepad is (by its USB ids), else the name it gives itself."""
    p = bt.product.get(mac)
    if p == "Xbox" and "xbox" not in name.lower():
        return "Xbox " + name
    return p or name


def rows(bt):
    """[(mac, name, state)]: the paired devices (connected first), then the ones found nearby (gamepads first).
    Two that would look the same get the end of their address."""
    out = []
    paired = sorted(bt.paired.items(), key=lambda d: (d[0] not in bt.connected, label(bt, *d).lower()))
    for mac, name in paired:
        out.append((mac, label(bt, mac, name), "on" if mac in bt.connected else "paired"))
    new = [(m, label(bt, m, n)) for m, n in bt.all.items() if m not in bt.paired and named(m, n)]
    new.sort(key=lambda d: (not GAMEPAD.search(d[1]), d[1].lower()))
    for mac, name in new:
        out.append((mac, name, "new"))
    count = {}
    for _, name, _ in out:
        count[name] = count.get(name, 0) + 1
    return [(m, n + " · " + m[-5:] if count[n] > 1 else n, st) for m, n, st in out]


def draw(bt, items, sel, top, confirm):
    screen.fill(BG)
    text("BLUETOOTH", (64, 1), BLUE, f_title, center=True)
    lh = f_label.get_linesize() + 1
    y = 2 + f_title.get_linesize()
    if bt.busy:
        status, color = bt.busy, ACCENT
    elif confirm:
        status, color = "ще раз - забути «%s»" % confirm[1], RED
    elif bt.result:
        status, color = bt.result
    elif bt.powered is None:
        status, color = "вмикаю…", DIM
    elif not bt.powered:
        status, color = "адаптер вимкнено", RED
    elif bt.discovering or bt.scan_until > time.monotonic():      # asked for: bluez says so a moment later
        status, color = "пошук" + "." * (int(time.monotonic() * 2) % 4), GREEN
    else:
        status, color = "пошук зупинено", DIM
    text(fit(status, f_small, 124), (64, y), color, f_small, center=True)
    y += f_small.get_linesize() + 1
    pygame.draw.line(screen, (60, 60, 60), (2, y), (126, y))
    y += 2
    y0, bottom = y, 116 - f_small.get_linesize()
    visible = max(1, int((bottom - y0) // lh))
    shown_new = False
    for i in range(top, min(len(items), top + visible)):
        mac, name, state = items[i]
        if state == "new" and not shown_new and i > 0 and items[i - 1][2] != "new":
            y += 2
            pygame.draw.line(screen, (60, 60, 100), (8, y - 1), (120, y - 1))
        shown_new = state == "new"
        if i == sel:
            pygame.draw.rect(screen, ACCENT, (1, y, 126, lh), border_radius=2)
        mark, mc = {"on": ("●", GREEN), "paired": ("○", DIM), "new": ("+", BLUE)}[state]
        fg = BG if i == sel else (FG if state != "new" else (200, 210, 255))
        text(mark, (3, y), BG if i == sel else mc, f_bold)
        f = f_bold if GAMEPAD.search(name) else f_label
        text(fit(name, f, 114), (12, y), fg, f)
        y += lh
    if not items:
        yy = y0 + 4
        for tip in ("Увімкніть спарювання на джойстику:", "PS5 / PS4 - затисніть Share + PS,",
                    "PXN - Mode + Turbo, Xbox - кнопка зверху, 8BitDo - Start + Y / B"):
            for t in wrap(tip, f_small, 124):
                text(t, (64, yy), DIM, f_small, center=True)
                yy += f_small.get_linesize()
    elif not bt.busy and 0 <= sel < len(items):
        st = items[sel][2]
        what = {"on": "від'єднати", "paired": "під'єднати", "new": "спарити"}[st]
        key = "натиск" if HAT else "Enter"
        hint = "%s - %s" % (key, what)
        if st != "new":
            hint += ", %s ×2 - забути" % ("KEY2" if HAT else "Del")
        text(fit(hint, f_small, 126), (64, bottom - 1), (170, 170, 120), f_small, center=True)
    hint = "KEY1 пошук  KEY3 вихід" if HAT else "s пошук   Esc вихід"
    text(hint, (64, 118), (150, 150, 150), f_small, center=True)
    lcd.flip()
    return visible


def main():
    if not os.path.exists(BTCTL):
        return None
    bt = Bt()
    bt.start()
    sel, top, visible = 0, 0, 6
    confirm = None                           # (mac, name, until) - the first press of "forget"
    cur = None                               # the selected device's address, kept while the list changes
    while True:
        items = rows(bt)
        macs = [it[0] for it in items]
        if cur in macs:
            sel = macs.index(cur)
        sel = max(0, min(sel, len(items) - 1))
        for ev in pygame.event.get():
            if ev.type == pygame.QUIT:
                return bt
            if ev.type != pygame.KEYDOWN:
                continue
            k, hat = ev.key, getattr(ev, "hat", False)
            ch = getattr(ev, "unicode", "") if not hat else ""
            if k == pygame.K_ESCAPE or (hat and k == pygame.K_3):
                return bt
            bt.result = None if not bt.busy else bt.result
            if k == pygame.K_UP and items:
                sel = (sel - 1) % len(items)
                confirm = None
            elif k == pygame.K_DOWN and items:
                sel = (sel + 1) % len(items)
                confirm = None
            elif k == pygame.K_TAB or ch in ("s", "S", "і", "І") or (hat and k == pygame.K_1):
                bt.scan(not bt.discovering)
                lcd.play("select")
            elif k in (pygame.K_RETURN, pygame.K_KP_ENTER, pygame.K_SPACE) and items and not bt.busy:
                mac, name, _ = items[sel]
                confirm = None
                lcd.play("select")
                bt.job(bt.act, mac, name)
            elif (k in (pygame.K_DELETE, pygame.K_BACKSPACE) or (hat and k == pygame.K_2)) and items \
                    and not bt.busy and items[sel][2] != "new":
                mac, name, _ = items[sel]
                if confirm and confirm[0] == mac and time.monotonic() < confirm[2]:
                    confirm = None
                    bt.job(bt.forget, mac, name)
                else:
                    confirm = (mac, name, time.monotonic() + 4)
                    lcd.play("error")
        if items:
            cur = items[sel][0]
        if confirm and time.monotonic() > confirm[2]:
            confirm = None
        if sel < top:
            top = sel
        elif sel >= top + visible:
            top = sel - visible + 1
        visible = draw(bt, items, sel, top, confirm)
        clock.tick(15)


if __name__ == "__main__":
    bt = None
    try:
        bt = main()
    finally:
        if bt:
            bt.close()
        screen.fill(BG)
        lcd.flip()
        lcd.quit()
