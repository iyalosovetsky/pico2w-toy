"""Launcher menu for the Waveshare 1.44\" LCD HAT: Pong / Tetris / Poker / Chess / Preferans / Doom / AI chat / Console / HDMI / Power off.

Joystick UP/DOWN - choose, PRESS or KEY1 - run.
USB keyboard: arrows, Enter / Space - run.
Games return here when they exit; CONSOLE ends the menu and opens the LCD
console (tty7); HDMI lends the USB keyboard to the HDMI console (tty1) until KEY3.
"""
import glob
import os
import socket
import subprocess

import pygame
import lcd

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
font_title = pygame.font.Font(None, 22)
TITLE = socket.gethostname().split(".")[0].upper()  # the menu header shows the hostname
while font_title.size(TITLE)[0] > 120 and font_title.get_height() > 10:  # long names: smaller font
    font_title = pygame.font.Font(None, font_title.get_height() - 2)
font_item = pygame.font.Font(None, 20)
VISIBLE = 5     # rows on screen; the list scrolls
ROW_H = 20
top = 0         # first visible row
font_small = pygame.font.Font(None, 14)
clock = pygame.time.Clock()


def draw(sel):
    global top
    top = min(max(top, sel - VISIBLE + 1), sel)  # keep the selection on screen
    screen.fill(BG)
    t = font_title.render(TITLE, True, ACCENT)
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
