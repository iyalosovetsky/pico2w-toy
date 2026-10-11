"""FLIPPER: scanning with a Flipper Zero on USB - its CLI receives and identifies, this app shows it.

Receive only: Sub-GHz (`subghz rx <Hz> 0` - decoded protocols), infrared (`ir rx` - remote
protocol, address, command), RFID 125 kHz (`rfid read` - tag type and ID) and NFC (`scanner` in
the nfc subshell - tag type). Nothing is sent, emulated or written.

Keys: UP / DOWN - row (mode, frequency), LEFT / RIGHT - change, Enter - start / stop scanning,
Del / c - clear the list, Esc - exit. HAT: PRESS - start / stop, KEY3 - exit.
"""
import glob
import os
import re
import select
import sys
import termios
import threading
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import pygame  # noqa: E402
import lcd  # noqa: E402

MODES = [("subghz", "Sub-GHz"), ("ir", "ІЧ"), ("rfid", "RFID 125 кГц"), ("nfc", "NFC")]
FREQS = [433920000, 315000000, 868350000, 390000000, 418000000, 300000000, 915000000, 434420000]
ROWS = ["Режим", "Частота"]
MAX_ITEMS = 60
LOG = os.environ.get("FLIPPER_LOG", "/tmp/flipper.log")   # the raw CLI output, for checking the parsing
HEADER = re.compile(r"^(.*?)([A-Z][\w\-\. ]*? \d+ ?bit)$")   # "KeeLoq 64bit", "Princeton 24bit"
# Sub-GHz protocol names (Flipper / Momentum), to split "MF:AN-MotorsKeeLoq 64bit" - a manufacturer line
# printed without its newline, glued to the next result's header
PROTOCOLS = ["KeeLoq", "Princeton", "CAME", "CAME TWEE", "CAME Atomo", "Nice FLO", "Nice FloR-S", "Holtek",
             "Holtek_HT12X", "GateTX", "Linear", "LinearDelta3", "Security+ 1.0", "Security+ 2.0", "Faac SLH",
             "Somfy Telis", "Somfy Keytis", "Star Line", "Scher-Khan", "Kia Seed", "Hormann HSM", "Marantec",
             "BETT", "Doitrand", "Phoenix_V2", "Honeywell", "Megacode", "Chamberlain_Code", "Ansonic", "SMC5326",
             "Power Smart", "Intertechno_V3", "Magellan", "Clemsa", "Dooya", "Alutech AT-4N", "Nero Radio",
             "Nero Sketch", "Hay21", "KingGates Stylo4k", "Mastercode", "Legrand", "Dickert_MAHS", "Feron",
             "Revers_RB2", "Roger", "Elplast", "Treadmill37", "Beninca", "Allmatic", "Centurion", "Hollarm",
             "Gangqi", "Marantec24", "Jarolift", "Keyfinder", "Holtek_HT640"]
ANSI = re.compile(r"\x1b\[[0-9;]*[A-Za-z]|\x1b\[\d*C")
# lines of the CLI's own chatter (not results)
NOISE = re.compile(r"^(>:|\[nfc\]>:|Press (CTRL|Ctrl)\+C|Listening at|Receiving|Reading|Usage|Cmd list|"
                   r"Load_keystore|Packets received|"
                   r"Welcome|Run `help`|Find out more|subghz |ir rx|rfid read|scanner|nfc$|exit$|\s*0+\s*$)")

BG, FG, DIM = (0, 0, 0), (235, 235, 235), (140, 140, 140)
ACCENT, RED, GREEN, ORANGE = (255, 200, 0), (240, 90, 80), (90, 220, 110), (255, 140, 0)
FONT_DIR = "/usr/share/fonts/truetype/dejavu/"


def find_flipper():
    """/dev/ttyACMx of a Flipper (by its USB manufacturer), or None."""
    for tty in sorted(glob.glob("/sys/class/tty/ttyACM*")):
        dev = os.path.realpath(tty + "/device/..")
        try:
            with open(dev + "/manufacturer") as f:
                if "Flipper" in f.read():
                    return "/dev/" + os.path.basename(tty)
        except OSError:
            pass
    return None


class Cli:
    """The Flipper's CLI over its USB serial port; a reader thread collects lines."""

    def __init__(self, path):
        self.fd = os.open(path, os.O_RDWR | os.O_NOCTTY | os.O_NONBLOCK)
        a = termios.tcgetattr(self.fd)
        a[0] = a[1] = a[3] = 0
        a[2] = termios.CS8 | termios.CREAD | termios.CLOCAL
        a[4] = a[5] = termios.B115200
        termios.tcsetattr(self.fd, termios.TCSANOW, a)
        self.lines = []
        self.lock = threading.Lock()
        self.alive = True
        self.buf = ""
        self.buf_t = 0.0
        threading.Thread(target=self._reader, daemon=True).start()

    def _reader(self):
        while self.alive:
            try:
                if not select.select([self.fd], [], [], 0.2)[0]:
                    # a line the Flipper did not end (it prints a result's last line without a newline
                    # until the next one): after a pause it is complete
                    if self.buf.strip() and time.monotonic() - self.buf_t > 0.4:
                        with self.lock:
                            self.lines.append(self.buf)
                        self.buf = ""
                    continue
                data = os.read(self.fd, 4096)
            except BlockingIOError:
                continue
            except OSError:          # unplugged
                self.alive = False
                break
            text_ = data.decode("utf-8", "replace")
            try:
                with open(LOG, "a", encoding="utf-8") as f:
                    f.write(text_)
            except OSError:
                pass
            self.buf += ANSI.sub("", text_).replace("\r", "")
            self.buf_t = time.monotonic()
            *done, self.buf = self.buf.split("\n")
            with self.lock:
                self.lines += done
            if self.buf.endswith((">: ", "]>: ")):      # a prompt: no newline after it
                with self.lock:
                    self.lines.append(self.buf.strip())
                self.buf = ""

    def take(self):
        with self.lock:
            out, self.lines = self.lines, []
        return out

    def send(self, text):
        try:
            os.write(self.fd, text.encode())
        except OSError:
            self.alive = False

    def wait_prompt(self, timeout=2.0):
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            with self.lock:
                if any(l.endswith(">:") for l in self.lines):
                    self.lines = []
                    return True
            time.sleep(0.05)
        return False

    def close(self):
        self.alive = False
        try:
            os.close(self.fd)
        except OSError:
            pass


def split_glued(line):
    """'MF:AN-MotorsKeeLoq 64bit' -> ('MF:AN-Motors', 'KeeLoq 64bit'); not glued -> (line, None)."""
    m = re.match(r"^(.*?)(\d+ ?bit)$", line)
    if not m:
        return line, None
    body = m.group(1).rstrip()
    for name in sorted(PROTOCOLS, key=len, reverse=True):
        if body.endswith(name) and len(body) > len(name) + 3:
            return body[:-len(name)], name + " " + m.group(2)
    return line, None


class Scanner:
    """Starts / stops one mode's receive command and turns its output into result entries."""

    def __init__(self, cli):
        self.cli = cli
        self.mode = None
        self.in_nfc = False
        self.items = []          # (time, text lines, color)
        self.pending = []
        self.nfc_busy = False    # a `scanner` is running (it blocks until a tag or Ctrl+C)
        self.done = False        # NFC: a tag was found - one scan per Enter

    def start(self, mode, freq):
        self.stop()
        self.cli.take()
        if mode == "subghz":
            self.cli.send("subghz rx %d 0\r" % freq)
        elif mode == "ir":
            self.cli.send("ir rx\r")
        elif mode == "rfid":
            self.cli.send("rfid read\r")
        elif mode == "nfc":
            self.cli.send("nfc\r")
            self.in_nfc = True
            self.cli.wait_prompt(3)
            self.cli.send("scanner\r")
            self.nfc_busy, self.done = True, False
        self.mode = mode

    def stop(self):
        if self.mode is None:
            return
        self.cli.send("\x03")
        self.drain(2)            # the last result's lines come just before the prompt: keep them
        if self.mode == "nfc":
            self.cli.send("exit\r")
            self.in_nfc = False
            self.cli.wait_prompt(2)
        self.flush()
        self.mode = None

    def drain(self, timeout):
        """Process output until the CLI's prompt."""
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            lines = self.cli.take()
            if self.feed(lines):
                return
            time.sleep(0.05)

    def flush(self):
        if self.pending:
            self.add(self.pending)
            self.pending = []

    def add(self, lines, color=GREEN):
        if self.mode == "ir" and lines and self.items:
            # a held remote button: "RC6, A:0x00, C:0x5A" then the same with " R" (repeat) many times -
            # one line with a count instead of a screenful
            key = re.sub(r"\s+R$", "", lines[0])
            t, last, c = self.items[0]
            m = re.match(r"^(.*?)(?:  ×(\d+))?$", last[0])
            if m.group(1) == key:
                n = int(m.group(2) or 1) + 1
                self.items[0] = (time.strftime("%H:%M:%S"), ["%s  ×%d" % (key, n)] + last[1:], c)
                return
            lines = [key] + lines[1:]
        if self.mode == "subghz" and lines and HEADER.match(lines[0]):
            # the header line: protocol · manufacturer · button
            mf, btn, rest = [], [], []
            for l in lines[1:]:
                if l.startswith("MF:"):
                    mf.append(l[3:].strip())
                    continue
                b = re.search(r"Btn:\s*(\w+)", l)
                if b:
                    btn.append("кн " + b.group(1))
                    l = re.sub(r"\s*Btn:\s*\w+", "", l)
                if l:
                    rest.append(l)
            lines = [" · ".join([lines[0]] + mf + btn)] + rest
        self.items.insert(0, (time.strftime("%H:%M:%S"), lines, color))
        del self.items[MAX_ITEMS:]

    def poll(self):
        """Read new output; group the lines of one result (a blank line or a prompt ends it)."""
        prompt = self.feed(self.cli.take())
        if self.pending and self.mode in ("subghz", "rfid") and len(self.pending) >= 6:
            self.flush()
        # NFC: `scanner` runs until it finds a tag, prints "Protocols detected: ..." and returns to the
        # prompt. One scan per Enter: the Flipper (Momentum, 2025-2026) crashes when the scanner polls an
        # ISO14443-4 card again and again, and typing into a running scanner crashed it too
        if self.mode == "nfc" and prompt and self.nfc_busy:
            self.nfc_busy = False
            self.done = True

    def feed(self, lines):
        """Group lines into results; True when a prompt came."""
        prompt = False
        for raw in lines:
            line = re.sub(r"\s{2,}", "  ", raw.strip())
            if not line or line.endswith(">:"):
                prompt = prompt or line.endswith(">:")
                self.flush()
                continue
            if NOISE.match(line):
                continue
            if line.startswith("Protocols detected"):    # NFC: an empty list = aborted, no tag
                found = line.split(":", 1)[1].strip()
                if found:
                    self.pending.append("NFC: " + found)
                    self.flush()
                continue
            if line.startswith("MF:") and HEADER.match(line):
                head, tail = split_glued(line)
                if tail:
                    self.pending.append(head)
                    line = tail
            if self.mode == "subghz" and HEADER.match(line):
                self.flush()
            self.pending.append(line)
            if self.mode == "ir":          # one line per received signal
                self.flush()
        return prompt


# ---------------------------------------------------------------- screen

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
f_label = font("DejaVuSans.ttf", 14 if BIG else 8)
f_bold = font("DejaVuSans-Bold.ttf", 14 if BIG else 8)
f_small = font("DejaVuSansMono.ttf", 12 if BIG else 7)
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


def draw(st, sc, row, status, status_color):
    screen.fill(BG)
    text("FLIPPER", (64, 1), ORANGE, f_title, center=True)
    mode = MODES[st["mode"]]
    values = [mode[1], "%.2f МГц" % (FREQS[st["freq"]] / 1e6) if mode[0] == "subghz" else "—"]
    for i, (name, value) in enumerate(zip(ROWS, values)):
        y = 12 + i * 11
        sel = i == row
        if sel:
            pygame.draw.rect(screen, ACCENT, (2, y - 1, 124, 10), border_radius=2)
        text(name, (6, y), BG if sel else DIM, f_label)
        text(value, (122, y), BG if sel else FG, f_bold, right=True)
    y = 35
    text(status, (64, y), status_color, f_label, center=True)
    y += f_label.get_linesize() + 1
    pygame.draw.line(screen, (60, 60, 60), (2, y - 1), (126, y - 1))
    lh = f_small.get_linesize()
    for t, lines, color in sc.items:
        if y + lh > 117:
            break
        text(t, (2, y), DIM, f_small)
        x0 = 2 + f_small.size(t + " ")[0]
        for k, line in enumerate(lines[:4]):
            if y + lh > 117:
                break
            text(fit(line, f_small, 126 - x0), (x0, y), color if k == 0 else FG, f_small)
            y += lh
        y += 1
    if not sc.items:
        text({"subghz": "брелоки, датчики, шлагбауми…", "ir": "наведіть пульт на Flipper",
              "rfid": "прикладіть мітку 125 кГц до спинки", "nfc": "прикладіть NFC-мітку до спинки"}[mode[0]],
             (64, 60), DIM, f_label, center=True)
    hint = "натиск - старт/стоп, KEY3" if HAT else "Enter старт/стоп   c очистити   Esc"
    text(hint, (64, 118), (150, 150, 150), f_label, center=True)
    lcd.flip()


def main():
    st = {"mode": 0, "freq": 0}
    row = 0
    cli = sc = None
    scanning = False
    last_try = 0
    while True:
        now = time.monotonic()
        if cli is None or not cli.alive:
            if sc:
                scanning = False
            cli = sc = None
            if now - last_try > 1.5:
                last_try = now
                path = find_flipper()
                if path:
                    try:
                        cli = Cli(path)
                        cli.send("\r")
                        cli.wait_prompt(2)
                        sc = Scanner(cli)
                    except OSError:
                        cli = None
        for ev in pygame.event.get():
            if ev.type == pygame.QUIT:
                return sc
            if ev.type != pygame.KEYDOWN:
                continue
            k, hat = ev.key, getattr(ev, "hat", False)
            ch = getattr(ev, "unicode", "") if not hat else ""
            if k == pygame.K_ESCAPE or (hat and k == pygame.K_3):
                return sc
            if k == pygame.K_UP:
                row = (row - 1) % len(ROWS)
            elif k == pygame.K_DOWN:
                row = (row + 1) % len(ROWS)
            elif k in (pygame.K_LEFT, pygame.K_RIGHT):
                sign = 1 if k == pygame.K_RIGHT else -1
                if row == 0:
                    st["mode"] = (st["mode"] + sign) % len(MODES)
                elif MODES[st["mode"]][0] == "subghz":
                    st["freq"] = (st["freq"] + sign) % len(FREQS)
                if scanning and sc:   # restart with the new setting
                    sc.start(MODES[st["mode"]][0], FREQS[st["freq"]])
            elif k in (pygame.K_RETURN, pygame.K_KP_ENTER, pygame.K_SPACE) and sc:
                scanning = not scanning
                if scanning:
                    sc.start(MODES[st["mode"]][0], FREQS[st["freq"]])
                else:
                    sc.stop()
                lcd.play("select")
            elif (k == pygame.K_DELETE or ch in ("c", "C")) and sc:
                sc.items = []
        if sc and scanning:
            n = len(sc.items)
            sc.poll()
            if len(sc.items) > n:
                lcd.play("chip")
            if sc.done:                    # NFC: the tag is read - this scan is over
                sc.stop()
                sc.done = False
                scanning = False
        if cli is None:
            status, color = "Flipper не підключено (USB)", RED
        elif scanning:
            status, color = "сканую" + "." * (int(now * 2) % 4), GREEN
        elif MODES[st["mode"]][0] == "nfc" and sc.items:
            status, color = "Enter - сканувати ще раз", DIM
        else:
            status, color = "Enter - почати сканування", DIM
        draw(st, sc or _Empty, row, status, color)
        clock.tick(15)


class _Empty:
    items = []


if __name__ == "__main__":
    scanner = None
    try:
        scanner = main()
    finally:
        if scanner:
            scanner.stop()
            scanner.cli.close()
        screen.fill(BG)
        lcd.flip()
        lcd.quit()
