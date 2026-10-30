"""Launcher menu for the Waveshare 1.44\" LCD HAT: Pong / Tetris / Poker / Chess / Preferans / Doom / AI chat / Console / HDMI / Power off.

The items are in folders (menufolders.py): their icons down the left, the chosen folder's items on the right.
Joystick UP/DOWN - choose, LEFT/RIGHT - folder, PRESS - run (held - the folder dialog), KEY1 - help.
Keyboard: arrows, Enter / Space - run (Enter held - the folder dialog), F1 - help; letters - search every folder.
Games return here when they exit; CONSOLE ends the menu and opens the LCD
console (tty7); HDMI lends the USB keyboard to the HDMI console (tty1) until KEY3.
"""
import glob
import math
import os
import socket
import subprocess
import time

import pygame
import lcd
import help as helptext

HERE = os.path.dirname(os.path.abspath(__file__))
ITEMS = [
    ("PONG", "vs AI", ["/usr/bin/python3", HERE + "/pong.py"], HERE),
    ("TETRIS", "", ["/usr/bin/python3", HERE + "/tetris.py"], HERE),
    ("POKER", "hold'em", ["/usr/bin/python3", HERE + "/poker.py"], HERE),
    ("CHESS", "stockfish", ["/usr/bin/python3", HERE + "/chessgame.py"], HERE),
    ("PREFERANS", "", ["/usr/bin/python3", HERE + "/preferans.py"], HERE),
    ("BOOKS", "epub fb2", ["/usr/bin/python3", HERE + "/reader.py"], HERE),
    ("DOOM", "E1", [HERE + "/doom/doomlcd", "-iwad", "/usr/share/games/doom/doom1.wad"], HERE + "/doom"),
    ("PICO RUSH", "outrun", ["/usr/bin/python3", HERE + "/racer.py"], HERE),
    ("STAR TRADER", "elite", ["/usr/bin/python3", HERE + "/startrader.py"], HERE),
    ("GENERATOR", "", ["/usr/bin/python3", HERE + "/siggen.py"], HERE),
    ("SERIAL", "grblHAL", ["/usr/bin/python3", HERE + "/serialterm.py"], HERE),
    ("CALC", "apcalc", ["/usr/bin/python3", HERE + "/calcpad.py"], HERE),
    ("SYNTH", "", ["/usr/bin/python3", HERE + "/synth.py"], HERE),
    ("RADIO", "online", ["/usr/bin/python3", HERE + "/radio.py"], HERE),
    ("SDR", "rtl-sdr", ["/usr/bin/python3", HERE + "/sdr.py"], HERE),
    ("FLIPPER", "scan", ["/usr/bin/python3", HERE + "/flipper.py"], HERE),
    ("BLUETOOTH", "gamepads", ["/usr/bin/python3", HERE + "/bluetooth.py"], HERE),
    ("SCREENSAVER", "demo", ["/usr/bin/python3", HERE + "/screensaver.py"], HERE),
    ("AQUARIUM", "demo", ["/usr/bin/python3", HERE + "/aquarium.py"], HERE),
    ("AI CHAT", "", "aichat", None),
    ("PYTHON", "bpython", "term:python", None),
    ("BASIC", "MMBasic", "term:basic", None),
    ("EDIT", "micro", "term:edit", None),
    ("CONSOLE", "tty", None, None),
    ("HDMI", "keyboard", "hdmi", None),
    ("SOUND", "", "sound", None),
    ("POWER OFF", "", "poweroff", None),
]


def _ai_provider():
    """The AI chat's current provider (~/.config/lcdtoy/ai-chat.json), shown in the menu."""
    import json
    try:
        with open(os.path.expanduser("~/.config/lcdtoy/ai-chat.json"), encoding="utf-8") as f:
            return json.load(f).get("provider", "")
    except (OSError, ValueError):
        return "zen4"


def _has_hdmi_fb():
    for path in glob.glob("/sys/class/graphics/fb[0-9]*/name"):
        try:
            with open(path) as f:
                if "vc4" in f.read():
                    return True
        except OSError:
            pass
    return False


ITEMS = [(n, _ai_provider() if c == "aichat" else h, c, d) for n, h, c, d in ITEMS]

# console tools (PicoCalc): only where install.sh set up lcd-term@.service
if not os.path.exists("/etc/systemd/system/lcd-term@.service"):
    ITEMS = [it for it in ITEMS if not str(it[2]).startswith("term:")]

# the SDR item: where the rtl-sdr package (rtl_tcp) is installed
if not os.path.exists("/usr/bin/rtl_tcp"):
    ITEMS = [it for it in ITEMS if it[0] != "SDR"]

# the generator board talks over the GPIO 14/15 UART or USB: only where one of them is there
if not os.path.exists("/dev/serial0") and not glob.glob("/dev/ttyACM*"):
    ITEMS = [it for it in ITEMS if it[0] != "GENERATOR"]

if not os.path.exists("/usr/bin/bluetoothctl"):
    ITEMS = [it for it in ITEMS if it[0] != "BLUETOOTH"]

if not _has_hdmi_fb():  # no monitor framebuffer (e.g. PicoCalc): nothing to lend the keyboard to
    ITEMS = [it for it in ITEMS if it[2] != "hdmi"]
POWEROFF_CMD = ["sudo", "-n", "/usr/bin/systemctl", "poweroff"]
SAVER_FILE = os.path.expanduser("~/.config/lcdtoy/screensaver")   # seconds without a key; 0 - never
AQUARIUM_BOOT_FILE = os.path.expanduser("~/.config/lcdtoy/aquarium-on-boot")   # 0 - no aquarium at boot
BOOTED_FLAG = "/dev/shm/lcdtoy-booted"   # tmpfs: gone after a reboot, kept while the menu restarts


def aquarium_at_boot():
    """True once per boot (the menu's first start after the device is switched on), unless turned off."""
    if os.path.exists(BOOTED_FLAG):
        return False
    try:
        open(BOOTED_FLAG, "w").close()
    except OSError:
        return False
    try:
        with open(AQUARIUM_BOOT_FILE) as f:
            return f.read().strip() != "0"
    except OSError:
        return True


_saver = {"t": -99.0, "value": 180}


def saver_after():
    """Seconds of no keys before the screensaver starts (180 by default, 0 - off); read every 10 s."""
    if time.monotonic() - _saver["t"] > 10:
        _saver["t"] = time.monotonic()
        try:
            with open(SAVER_FILE) as f:
                _saver["value"] = max(0, int(float(f.read().strip() or 0)))
        except (OSError, ValueError):
            _saver["value"] = 180
    return _saver["value"]

BG = (0, 0, 0)
FG = (220, 220, 220)
DIM = (110, 110, 110)
ACCENT = (255, 200, 0)

screen = lcd.init()
if not lcd.sound_available():
    ITEMS = [it for it in ITEMS if it[2] != "sound" and it[0] not in ("SYNTH", "RADIO")]
# PicoCalc battery (its firmware driver): percent, or 128 + percent while charging
BATTERY_FILE = "/sys/firmware/picocalc/battery_percent"
HAS_BATTERY = os.path.exists(BATTERY_FILE)
_battery = {"t": 0, "value": None}


def battery():
    """(percent, charging) or None; read every 10 s."""
    now = time.monotonic()
    if now - _battery["t"] > 10:
        _battery["t"] = now
        try:
            with open(BATTERY_FILE) as f:
                v = int(f.read().strip())
            _battery["value"] = (min(100, v - 128), True) if v > 100 else (v, False)
        except (OSError, ValueError):
            _battery["value"] = None
    return _battery["value"]


font_title = pygame.font.Font(None, 22)
TITLE = socket.gethostname().split(".")[0].upper()  # the menu header shows the hostname
TITLE_W = 84 if HAS_BATTERY else 120  # the battery takes the right of the header
while font_title.size(TITLE)[0] > TITLE_W and font_title.get_height() > 10:  # long names: smaller font
    font_title = pygame.font.Font(None, font_title.get_height() - 2)
font_item = pygame.font.Font(None, 20)
font_item_narrow = pygame.font.Font(None, 18)
VISIBLE = 5     # rows on screen; the list scrolls
ROW_H = 20
top = 0         # first visible row
font_small = pygame.font.Font(None, 14)
clock = pygame.time.Clock()
import menufolders  # noqa: E402  (its fonts need pygame started by lcd.init)
folders = menufolders.Folders([it[0] for it in ITEMS])
LONG_PRESS = 0.6  # s of OK held: the folder dialog instead of running the item


def draw_battery(pct_room=99):
    """Percent and a battery icon at the right of the header; a bolt while charging. The percent only
    where it fits (pct_room - the pixels left of the icon)."""
    b = battery()
    if b is None:
        return
    pct, charging = b
    color = (90, 200, 90) if pct > 50 else ACCENT if pct > 20 else (230, 60, 50)
    x, y = 107, 8  # icon body 12 x 7
    pygame.draw.rect(screen, FG, (x, y, 12, 7), 1)
    pygame.draw.rect(screen, FG, (x + 12, y + 2, 1, 3))
    fill = round(10 * max(0, min(100, pct)) / 100)
    if fill:
        pygame.draw.rect(screen, color, (x + 1, y + 1, fill, 5))
    if charging:
        pygame.draw.polygon(screen, (80, 200, 255), [(x + 7, y - 1), (x + 3, y + 4), (x + 6, y + 4),
                                                     (x + 5, y + 8), (x + 9, y + 3), (x + 6, y + 3)])
    t = font_small.render("%d%%" % pct, True, FG)
    if t.get_width() + 2 <= pct_room:
        screen.blit(t, (x - 2 - t.get_width(), y - 1))


def search(q):
    """Items in every folder whose name has the typed letters in that order, not necessarily together
    (B, K - BOOKS): the most run first, then the names starting with the first letter."""
    q = q.lower().replace(" ", "")
    found = []
    for k, (name, _, _, _) in enumerate(ITEMS):
        n = name.lower()
        rest = iter(n)
        if all(c in rest for c in q):            # each letter found after the one before
            found.append((-folders.launches.get(name, 0.0), not n.startswith(q[:1]), k))
    return [k for _, _, k in sorted(found)]


def draw_magnifier(x, y, color):
    pygame.draw.circle(screen, color, (x + 4, y + 4), 3.6, 1)
    pygame.draw.line(screen, color, (x + 6.5, y + 6.5), (x + 9.5, y + 9.5), 2)


def draw(sel, shown, query=""):
    """The folder's name over its items (or the search over what it found); the folders' icons down the left."""
    global top
    top = min(max(top, sel - VISIBLE + 1), sel)  # keep the selection on screen
    screen.fill(BG)
    name = folders.name(folders.current) if not query else query + ("_" if time.monotonic() % 1 < 0.5 else " ")
    if HAS_BATTERY:
        room = 105 - 26                                    # up to the battery's icon
        draw_battery(room - menufolders.f_head.size(name)[0] - 4)
    else:
        h = font_small.render(TITLE.lower(), True, DIM)
        room = 124 - 26
        if menufolders.f_head.size(name)[0] + 6 + h.get_width() <= room:   # the hostname where it fits
            screen.blit(h, (124 - h.get_width(), 8))
    x = 26
    if query:
        draw_magnifier(x, 6, ACCENT)
        x += 13
        room -= 13
    f = menufolders.f_head if menufolders.f_head.size(name)[0] <= room else menufolders.f_bold
    t = f.render(menufolders._fit(name, f, room), True, FG if query else ACCENT)
    screen.blit(t, (x, 11 - t.get_height() / 2))
    pygame.draw.line(screen, DIM, (24, 22), (124, 22))
    menufolders.column(screen, folders, -1 if query else folders.current, 24, 104)
    for i in range(top, min(top + VISIBLE, len(shown))):
        name, hint, cmd, _ = ITEMS[shown[i]]
        if cmd == "sound":
            hint = "on" if lcd.sound_enabled() else "off"
        y = 28 + (i - top) * ROW_H
        if i == sel:
            pygame.draw.rect(screen, ACCENT, (24, y - 3, 103, ROW_H - 1), border_radius=4)
            name_c, hint_c = BG, (60, 60, 60)
        else:
            name_c, hint_c = FG, DIM
        n = font_item.render(name, True, name_c)
        if n.get_width() > 96:                                # SCREENSAVER: a size smaller
            n = font_item_narrow.render(name, True, name_c)
        screen.blit(n, (28, y))
        h = font_small.render(hint, True, hint_c)
        if 28 + n.get_width() + 4 + h.get_width() <= 124:     # the hint only where it fits beside the name
            screen.blit(h, (124 - h.get_width(), y + 4))
    if not shown:
        lines = ("нічого не знайдено", "", "Esc - назад") if query else \
            ("тут з'являться", "програми, які", "ви часто запускаєте") if folders.current == folders.fav() \
            else ("порожньо", "утримуйте %s -" % lcd.OK, "дії з теками")
        for k, line in enumerate(lines):
            s_ = menufolders.f_small.render(line, True, DIM)
            screen.blit(s_, (76 - s_.get_width() / 2, 50 + k * 11))
    # scroll indicators
    if top > 0:
        pygame.draw.polygon(screen, DIM, [(120, 18), (124, 23), (116, 23)])
    if top + VISIBLE < len(shown):
        pygame.draw.polygon(screen, DIM, [(120, 127), (124, 122), (116, 122)])
    lcd.flip()


def _dejavu(name, px):
    """DejaVu font px native pixels high (the default pygame font has no Cyrillic)."""
    size = px / lcd.S if lcd.S != 1 else int(px)
    try:
        return pygame.font.Font("/usr/share/fonts/truetype/dejavu/" + name, size)
    except (FileNotFoundError, OSError):
        return pygame.font.Font(None, size)


# the PicoCalc's J703 (left side of the case, the upper row of 8; pin 1 at the top - from the
# mainboard V2.0 Gerbers) as wired for the signal generator board
# the colours are those of a standard ribbon cable: 1 red ... 8 white
J703_PINS = [("3,3 В", "черв.", (220, 40, 40)), ("ген. · BL GP6", "оранж.", (255, 140, 0)),
             ("MOSI GP3", "жовт.", (240, 220, 0)), ("MISO SDA GP4", "зел.", (40, 180, 60)),
             ("CS SCL GP5", "син.", (40, 110, 255)), ("SCK GP2", "фіол.", (160, 70, 230)),
             ("АЦП GP26", "сірий", (150, 150, 150)), ("GND", "білий", (240, 240, 240))]


def j703_image(f, fb):
    """A drawing of J703 for the help: the left edge of the case, pins top to bottom."""
    pitch = max(f.get_linesize(), 9) + 1
    head = fb.get_linesize() + 2
    h = head + pitch * len(J703_PINS) + 4
    img = lcd.Surface((120, h)) if lcd.S != 1 else pygame.Surface((120, h))
    img.fill(BG)
    img.blit(fb.render("↑ екран", True, DIM), (16, 0))
    # the case edge and the header strip
    pygame.draw.line(img, DIM, (6, head - 1), (6, h - 1), 2)
    pygame.draw.rect(img, (70, 70, 70), (8, head, 9, pitch * len(J703_PINS)), border_radius=2)
    for i, (gp, use, color) in enumerate(J703_PINS):
        y = head + i * pitch
        cy = y + pitch / 2
        if i == 0:  # pin 1: square
            pygame.draw.rect(img, color, (10, cy - 2.5, 5, 5))
        else:
            pygame.draw.circle(img, color, (12.5, cy), 2.5)
        img.blit(fb.render(str(i + 1), True, color), (20, y))
        img.blit(f.render(gp, True, color), (30, y))   # the function in its wire's colour
        name = f.render(use, True, color)
        img.blit(name, (118 - name.get_width(), y))
    return img


def show_help(item):
    """Help for a menu item: UP/DOWN scroll, any other key closes."""
    f = _dejavu("DejaVuSans.ttf", 13 if lcd.S > 1 else 8)
    fb = _dejavu("DejaVuSans-Bold.ttf", 13 if lcd.S > 1 else 8)
    ft = _dejavu("DejaVuSans-Bold.ttf", 17 if lcd.S > 1 else 10)
    width = 120
    rows = []  # (text, font, color)
    line_h = f.get_linesize()
    for line in helptext.lines(item, lcd.DEVICE):
        if line == "@j703":  # a drawing, taking as many rows as its height
            img = j703_image(f, fb)
            n = int(math.ceil(img.get_height() / line_h))
            rows.append((img, None, None))
            rows += [("", f, FG)] * (n - 1)
            continue
        bold = line.startswith("# ")
        text = line[2:] if bold else line
        style = (fb, ACCENT) if bold else (f, FG)
        cur = ""
        for w in text.split(" "):
            cand = w if not cur else cur + " " + w
            if cur and style[0].size(cand)[0] > width:
                rows.append((cur, *style))
                cur = "  " + w  # continuation lines are indented
            else:
                cur = cand
        rows.append((cur, *style))
    top_y = ft.get_linesize() + 4
    visible = int((128 - top_y - 2) // line_h)
    top = 0
    lcd.play("select")
    while True:
        screen.fill(BG)
        for i, (text, font, color) in enumerate(rows):
            y = top_y + (i - top) * line_h
            if font is None:  # a drawing: may start above the window and show partly
                if y + text.get_height() > top_y and y < 128:
                    screen.blit(text, (4, y))
            elif top <= i < top + visible:
                screen.blit(font.render(text, True, color), (4, y))
        screen.fill(BG, (0, 0, 128, top_y - 1))  # the title over anything scrolled up
        t = ft.render(item, True, ACCENT)
        screen.blit(t, ((128 - t.get_width()) / 2, 1))
        pygame.draw.line(screen, DIM, (4, top_y - 2), (124, top_y - 2))
        if top > 0:
            pygame.draw.polygon(screen, DIM, [(122, top_y + 1), (126, top_y + 5), (118, top_y + 5)])
        if top + visible < len(rows):
            pygame.draw.polygon(screen, DIM, [(122, 127), (126, 123), (118, 123)])
        lcd.flip()
        for ev in pygame.event.get():
            if ev.type == pygame.QUIT:
                return False
            if ev.type == pygame.KEYDOWN:
                if ev.key == pygame.K_UP:
                    top = max(0, top - 1)
                elif ev.key == pygame.K_DOWN:
                    top = min(max(0, len(rows) - visible), top + 1)
                else:
                    return True
        clock.tick(20)


def message(title, *lines, color=ACCENT):
    screen.fill(BG)
    t = font_item.render(title, True, color)
    screen.blit(t, ((128 - t.get_width()) // 2, 30))
    for i, line in enumerate(lines):
        s = font_small.render(line, True, FG)
        screen.blit(s, ((128 - s.get_width()) // 2, 62 + i * 14))
    lcd.flip()


def hdmi_console():
    """Give the USB keyboard to the HDMI console until KEY3 on the HAT.

    The HAT buttons stay with the menu so they can't type into the shell.
    Returns False if the menu was asked to quit meanwhile.
    """
    lcd.release_keyboards()
    subprocess.run(["sudo", "-n", "/bin/chvt", "1"])
    message("HDMI", "keyboard -> HDMI", "console (tty1)", "", lcd.BACK + ": back")
    try:
        while True:
            for ev in pygame.event.get():
                if ev.type == pygame.QUIT:
                    return False
                if ev.type == pygame.KEYDOWN and getattr(ev, "hat", False) and ev.key == pygame.K_3:
                    return True
            clock.tick(20)
    finally:
        lcd.grab_inputs()
        lcd.flush_buttons()


def confirm_poweroff():
    """Ask for confirmation; True only for PRESS / KEY1 / Enter."""
    message("POWER OFF?", lcd.OK + ": yes", "other key: cancel", color=(255, 80, 80))
    while True:
        for ev in pygame.event.get():
            if ev.type == pygame.QUIT:
                return False
            if ev.type == pygame.KEYDOWN:
                return ev.key in (pygame.K_RETURN, pygame.K_1, pygame.K_SPACE)
        clock.tick(20)


def poweroff():
    message("BYE", "shutting down...", "unplug when the", "green LED is off")
    if subprocess.run(POWEROFF_CMD).returncode != 0:
        message("ERROR", "poweroff failed", color=(255, 80, 80))
        pygame.time.wait(2000)
        return False
    # keep the goodbye screen until systemd stops us during shutdown
    while True:
        for ev in pygame.event.get():
            if ev.type == pygame.QUIT:
                os._exit(0)
        clock.tick(5)


def run(cmd, cwd, env=None):
    """Run a program on the screen; its exit code."""
    screen.fill(BG)
    lcd.flip()
    lcd.release_inputs()  # the game grabs the keys itself
    lcd.release_audio()   # ... and opens the sound card
    rc = subprocess.run(cmd, cwd=cwd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                        env=dict(os.environ, **env) if env else None).returncode
    lcd.resume_audio()
    lcd.grab_inputs()
    lcd.flush_buttons()
    global idle_t
    idle_t = time.monotonic()   # the time in the app was not idle time: back in the menu, the count starts anew
    return rc


def launch(item):
    """Run a menu item; False when the menu is to end. Counted for the favourites."""
    _, _, cmd, cwd = item
    lcd.play("select")
    folders.launched(item[0])
    if cmd is None:
        return False
    if cmd == "aichat":
        # runs on the LCD text console (tty7); systemd stops this menu
        # and brings it back when the chat ends
        message("AI CHAT", "starting...")
        subprocess.run(["sudo", "-n", "/usr/bin/systemctl", "start",
                        "--no-block", "ai-chat.service"])
    elif str(cmd).startswith("term:"):
        # like the AI chat: a text-console tool on tty7, back to the menu on exit
        tool = cmd.split(":", 1)[1]
        message(item[0], "starting...")
        subprocess.run(["sudo", "-n", "/usr/bin/systemctl", "start",
                        "--no-block", "lcd-term@%s.service" % tool])
    elif cmd == "hdmi":
        return hdmi_console()
    elif cmd == "sound":
        lcd.set_sound(not lcd.sound_enabled())
        lcd.play("select")
    elif cmd == "poweroff":
        if confirm_poweroff():
            poweroff()
    else:
        run(cmd, cwd)
    return True


def launch_at(here, sel):
    """Run the folder's item at sel: (go on, where that item now is - the favourites re-sort by the runs)."""
    k = here[sel]
    go = launch(ITEMS[k])
    now = folders.items(folders.current)
    return go, now.index(k) if k in now else min(sel, max(0, len(now) - 1))


sel_in = {}     # the selection in each folder, kept while moving between them
sel = 0
running = True
press_t = None  # when OK went down: a short press runs the item, a long one opens the folder dialog
query = ""      # letters typed: the items found in every folder instead of the folder's
idle_t = time.monotonic()   # the last key: the screensaver after saver_after() seconds without one
SAVER = next((it for it in ITEMS if it[0] == "SCREENSAVER"), None)
# the screensavers take turns, SAVER_TURN seconds each (exit code 3 - the turn is over): the fractals and STAR
# TRADER playing itself (its sounds turned down)
SAVER_TURN = 300
SAVERS = ([(SAVER[2], SAVER[3], None)] if SAVER else []) + \
    [(["/usr/bin/python3", HERE + "/startrader.py", "--demo"], HERE, None) for it in ITEMS if it[0] == "STAR TRADER"]
saver_i = 0
AQUARIUM = next((it for it in ITEMS if it[0] == "AQUARIUM"), None)
if AQUARIUM and aquarium_at_boot():   # the device has just been switched on: the tank first, the menu after
    run(AQUARIUM[2], AQUARIUM[3])
    idle_t = time.monotonic()
shown = None    # what is on the screen: redraw only when it changes (a full frame cost 40-60 % of
                # a core on the PicoCalc at 20 fps on an unchanging screen)
OK_KEYS = (pygame.K_RETURN, pygame.K_KP_ENTER)
while running:
    keyed = False
    here = search(query) if query else folders.items(folders.current)
    sel = max(0, min(sel, len(here) - 1))
    for ev in pygame.event.get():
        if ev.type == pygame.QUIT:  # SIGTERM from systemctl stop
            running = False
        elif ev.type == pygame.KEYUP and ev.key in OK_KEYS and press_t is not None:
            press_t = None          # a short press: run it
            keyed = True
            shown = None
            if here:
                running, sel = launch_at(here, sel)
                if query:                       # back from the program: the folder, not the search
                    query, sel = "", 0
        elif ev.type == pygame.KEYDOWN:
            idle_t = time.monotonic()
            keyed = True
            shown = None            # a key (and whatever it opened - an app, help) may change the screen
            ch = "" if getattr(ev, "hat", False) else (getattr(ev, "unicode", "") or "")
            if (ch.isalpha() and ch.isascii()) or (query and ch.isdigit()):
                query = (query + ch.upper())[:12]       # letters: search every folder as they come
                sel, top = 0, 0
                here = search(query)
            elif query and ev.key == pygame.K_BACKSPACE:
                query = query[:-1]
                sel, top = 0, 0
                here = search(query) if query else folders.items(folders.current)
            elif query and ev.key == pygame.K_ESCAPE:
                query, sel, top = "", sel_in.get(folders.current, 0), 0
                here = folders.items(folders.current)
            elif ev.key == pygame.K_UP and here:
                sel = (sel - 1) % len(here)
                lcd.play("click")
            elif ev.key == pygame.K_DOWN and here:
                sel = (sel + 1) % len(here)
                lcd.play("click")
            elif ev.key in (pygame.K_LEFT, pygame.K_RIGHT, pygame.K_TAB):
                if query:                       # out of the search, on to a folder
                    query, sel = "", sel_in.get(folders.current, 0)
                sel_in[folders.current] = sel
                step = -1 if ev.key == pygame.K_LEFT else 1
                folders.current = (folders.current + step) % folders.count()
                folders.save()
                sel, top = sel_in.get(folders.current, 0), 0
                here = folders.items(folders.current)
                lcd.play("click")
            elif ev.key == pygame.K_F1 or (ev.key == pygame.K_1 and getattr(ev, "hat", False)):
                # F1 (keyboard) / KEY1 (HAT): help for the selected item
                if here:
                    running = show_help(ITEMS[here[sel]][0])
            elif ev.key in OK_KEYS:
                press_t = time.monotonic()      # run on the release, unless it is held
            elif ev.key in (pygame.K_1, pygame.K_SPACE) and here:
                running, sel = launch_at(here, sel)
                query = ""
    if press_t is not None and time.monotonic() - press_t > LONG_PRESS:
        press_t = None
        lcd.play("select")
        menufolders.dialog(screen, clock, folders, ITEMS[here[sel]][0] if here else None)
        query = ""
        here = folders.items(folders.current)
        sel = min(sel, max(0, len(here) - 1))
        keyed = True
        shown = None
    if keyed:
        idle_t = time.monotonic()   # after what the key opened (an app, the help): idle starts from now
    wait = saver_after()
    if SAVERS and wait and time.monotonic() - idle_t > wait:
        while True:                     # any key ends one and comes back here; its time up - the next one
            cmd, cwd, env = SAVERS[saver_i % len(SAVERS)]
            saver_i += 1
            if len(SAVERS) == 1:
                run(cmd, cwd, env)
                break
            if run(cmd + [str(SAVER_TURN)], cwd, env) != 3:
                break
        idle_t = time.monotonic()
        shown = None
    state = (folders.current, sel, battery() if HAS_BATTERY else None, lcd.sound_enabled(),
             press_t is not None, query, query and time.monotonic() % 1 < 0.5)   # the search's cursor blinks
    if state != shown:
        draw(sel, search(query) if query else folders.items(folders.current), query)
        shown = state
    clock.tick(20)

screen.fill(BG)
lcd.flip()
lcd.quit()
