"""Launcher menu for the Waveshare 1.44\" LCD HAT: Pong / Tetris / Poker / Chess / Doom / AI chat / Console / Power off.

Joystick UP/DOWN - choose, PRESS or KEY1 - run.
USB keyboard: arrows, Enter / Space - run.
Games return here when they exit; CONSOLE ends the menu and gives tty1 back.
"""
import os
import subprocess

import pygame
import lcd

HERE = os.path.dirname(os.path.abspath(__file__))
ITEMS = [
    ("PONG", "vs AI", ["/usr/bin/python3", HERE + "/pong.py"], HERE),
    ("TETRIS", "", ["/usr/bin/python3", HERE + "/tetris.py"], HERE),
    ("POKER", "hold'em", ["/usr/bin/python3", HERE + "/poker.py"], HERE),
    ("CHESS", "stockfish", ["/usr/bin/python3", HERE + "/chessgame.py"], HERE),
    ("DOOM", "E1", [HERE + "/doom/doomlcd", "-iwad", "/usr/share/games/doom/doom1.wad"], HERE + "/doom"),
    ("AI CHAT", "zen4", "aichat", None),
    ("CONSOLE", "tty", None, None),
    ("POWER OFF", "", "poweroff", None),
]
POWEROFF_CMD = ["sudo", "-n", "/usr/bin/systemctl", "poweroff"]

BG = (0, 0, 0)
FG = (220, 220, 220)
DIM = (110, 110, 110)
ACCENT = (255, 200, 0)

screen = lcd.init()
font_title = pygame.font.Font(None, 22)
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
    t = font_title.render("ZEROSEED", True, ACCENT)
    screen.blit(t, ((128 - t.get_width()) // 2, 5))
    pygame.draw.line(screen, DIM, (8, 22), (119, 22))
    for i in range(top, min(top + VISIBLE, len(ITEMS))):
        name, hint, _, _ = ITEMS[i]
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


def confirm_poweroff():
    """Ask for confirmation; True only for PRESS / KEY1."""
    message("POWER OFF?", "PRESS / KEY1 / Enter: yes", "other key: cancel", color=(255, 80, 80))
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
    subprocess.run(cmd, cwd=cwd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
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
            elif ev.key == pygame.K_DOWN:
                sel = (sel + 1) % len(ITEMS)
            elif ev.key in (pygame.K_RETURN, pygame.K_1, pygame.K_RIGHT, pygame.K_SPACE):
                _, _, cmd, cwd = ITEMS[sel]
                if cmd is None:
                    running = False
                elif cmd == "aichat":
                    # runs on the text console (tty1); systemd stops this menu
                    # and brings it back when the chat ends
                    message("AI CHAT", "starting...")
                    subprocess.run(["sudo", "-n", "/usr/bin/systemctl", "start",
                                    "--no-block", "ai-chat.service"])
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
