"""Launcher menu for the Waveshare 1.44\" LCD HAT: Pong / Tetris / Poker / Chess / Preferans / Doom / AI chat / Console / HDMI / Power off.

Joystick UP/DOWN - choose, PRESS or RIGHT - run, KEY1 - help for the item.
Keyboard: arrows, Enter / Space - run, F1 - help.
Games return here when they exit; CONSOLE ends the menu and opens the LCD
console (tty7); HDMI lends the USB keyboard to the HDMI console (tty1) until KEY3.
"""
import glob
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
    ("AI CHAT", "zen4", "aichat", None),
    ("PYTHON", "bpython", "term:python", None),
    ("BASIC", "MMBasic", "term:basic", None),
    ("EDIT", "micro", "term:edit", None),
    ("CONSOLE", "tty", None, None),
    ("HDMI", "keyboard", "hdmi", None),
    ("SOUND", "", "sound", None),
    ("POWER OFF", "", "poweroff", None),
]


def _has_hdmi_fb():
    for path in glob.glob("/sys/class/graphics/fb[0-9]*/name"):
        try:
            with open(path) as f:
                if "vc4" in f.read():
                    return True
        except OSError:
            pass
    return False


# console tools (PicoCalc): only where install.sh set up lcd-term@.service
if not os.path.exists("/etc/systemd/system/lcd-term@.service"):
    ITEMS = [it for it in ITEMS if not str(it[2]).startswith("term:")]

if not _has_hdmi_fb():  # no monitor framebuffer (e.g. PicoCalc): nothing to lend the keyboard to
    ITEMS = [it for it in ITEMS if it[2] != "hdmi"]
POWEROFF_CMD = ["sudo", "-n", "/usr/bin/systemctl", "poweroff"]

BG = (0, 0, 0)
FG = (220, 220, 220)
DIM = (110, 110, 110)
ACCENT = (255, 200, 0)

screen = lcd.init()
if not lcd.sound_available():
    ITEMS = [it for it in ITEMS if it[2] != "sound"]
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
VISIBLE = 5     # rows on screen; the list scrolls
ROW_H = 20
top = 0         # first visible row
font_small = pygame.font.Font(None, 14)
clock = pygame.time.Clock()


def draw_battery():
    """Percent and a battery icon at the right of the header; a bolt while charging."""
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
    screen.blit(t, (x - 2 - t.get_width(), y - 1))


def draw(sel):
    global top
    top = min(max(top, sel - VISIBLE + 1), sel)  # keep the selection on screen
    screen.fill(BG)
    t = font_title.render(TITLE, True, ACCENT)
    if HAS_BATTERY:
        screen.blit(t, (8, 5))
        draw_battery()
    else:
        screen.blit(t, ((128 - t.get_width()) // 2, 5))
    pygame.draw.line(screen, DIM, (8, 22), (119, 22))
    for i in range(top, min(top + VISIBLE, len(ITEMS))):
        name, hint, cmd, _ = ITEMS[i]
        if cmd == "sound":
            hint = "on" if lcd.sound_enabled() else "off"
        y = 28 + (i - top) * ROW_H
        if i == sel:
            pygame.draw.rect(screen, ACCENT, (6, y - 3, 116, ROW_H - 1), border_radius=4)
            name_c, hint_c = BG, (60, 60, 60)
        else:
            name_c, hint_c = FG, DIM
        screen.blit(font_item.render(name, True, name_c), (12, y))
        h = font_small.render(hint, True, hint_c)
        screen.blit(h, (118 - h.get_width(), y + 4))
    # scroll indicators
    if top > 0:
        pygame.draw.polygon(screen, DIM, [(120, 18), (124, 23), (116, 23)])
    if top + VISIBLE < len(ITEMS):
        pygame.draw.polygon(screen, DIM, [(120, 127), (124, 122), (116, 122)])
    lcd.flip()


def _dejavu(name, px):
    """DejaVu font px native pixels high (the default pygame font has no Cyrillic)."""
    size = px / lcd.S if lcd.S != 1 else int(px)
    try:
        return pygame.font.Font("/usr/share/fonts/truetype/dejavu/" + name, size)
    except (FileNotFoundError, OSError):
        return pygame.font.Font(None, size)


def show_help(item):
    """Help for a menu item: UP/DOWN scroll, any other key closes."""
    f = _dejavu("DejaVuSans.ttf", 13 if lcd.S > 1 else 8)
    fb = _dejavu("DejaVuSans-Bold.ttf", 13 if lcd.S > 1 else 8)
    ft = _dejavu("DejaVuSans-Bold.ttf", 17 if lcd.S > 1 else 10)
    width = 120
    rows = []  # (text, font, color)
    for line in helptext.lines(item, lcd.DEVICE):
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
    line_h = f.get_linesize()
    top_y = ft.get_linesize() + 4
    visible = int((128 - top_y - 2) // line_h)
    top = 0
    lcd.play("select")
    while True:
        screen.fill(BG)
        t = ft.render(item, True, ACCENT)
        screen.blit(t, ((128 - t.get_width()) / 2, 1))
        pygame.draw.line(screen, DIM, (4, top_y - 2), (124, top_y - 2))
        for i, (text, font, color) in enumerate(rows[top:top + visible]):
            screen.blit(font.render(text, True, color), (4, top_y + i * line_h))
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


def run(cmd, cwd):
    screen.fill(BG)
    lcd.flip()
    lcd.release_inputs()  # the game grabs the keys itself
    lcd.release_audio()   # ... and opens the sound card
    subprocess.run(cmd, cwd=cwd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    lcd.resume_audio()
    lcd.grab_inputs()
    lcd.flush_buttons()


sel = 0
running = True
while running:
    for ev in pygame.event.get():
        if ev.type == pygame.QUIT:  # SIGTERM from systemctl stop
            running = False
        elif ev.type == pygame.KEYDOWN:
            if ev.key == pygame.K_UP:
                sel = (sel - 1) % len(ITEMS)
                lcd.play("click")
            elif ev.key == pygame.K_DOWN:
                sel = (sel + 1) % len(ITEMS)
                lcd.play("click")
            elif ev.key == pygame.K_F1 or (ev.key == pygame.K_1 and getattr(ev, "hat", False)):
                # F1 (keyboard) / KEY1 (HAT): help for the selected item
                running = show_help(ITEMS[sel][0])
            elif ev.key in (pygame.K_RETURN, pygame.K_1, pygame.K_RIGHT, pygame.K_SPACE):
                lcd.play("select")
                _, _, cmd, cwd = ITEMS[sel]
                if cmd is None:
                    running = False
                elif cmd == "aichat":
                    # runs on the LCD text console (tty7); systemd stops this menu
                    # and brings it back when the chat ends
                    message("AI CHAT", "starting...")
                    subprocess.run(["sudo", "-n", "/usr/bin/systemctl", "start",
                                    "--no-block", "ai-chat.service"])
                elif str(cmd).startswith("term:"):
                    # like the AI chat: a text-console tool on tty7, back to the menu on exit
                    tool = cmd.split(":", 1)[1]
                    message(ITEMS[sel][0], "starting...")
                    subprocess.run(["sudo", "-n", "/usr/bin/systemctl", "start",
                                    "--no-block", "lcd-term@%s.service" % tool])
                elif cmd == "hdmi":
                    running = hdmi_console()
                elif cmd == "sound":
                    lcd.set_sound(not lcd.sound_enabled())
                    lcd.play("select")
                elif cmd == "poweroff":
                    if confirm_poweroff():
                        poweroff()
                else:
                    run(cmd, cwd)
    draw(sel)
    clock.tick(20)

screen.fill(BG)
lcd.flip()
lcd.quit()
