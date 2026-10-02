"""Tetris for the Waveshare 1.44" LCD HAT.

Joystick LEFT/RIGHT - move, DOWN - soft drop, UP / PRESS - rotate,
KEY1 - hard drop, KEY2 - pause, KEY3 - exit.
Keyboard: arrows, Enter - rotate, Space - hard drop, 2 - pause, Esc - exit.
"""
import os
import random

import pygame
import lcd

COLS, ROWS = 10, 20
CELL = 6
BX, BY = 4, 4  # board origin on screen
HI_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "tetris_hi.txt")

SHAPES = {
    "I": [(0, 1), (1, 1), (2, 1), (3, 1)],
    "O": [(1, 0), (2, 0), (1, 1), (2, 1)],
    "T": [(1, 0), (0, 1), (1, 1), (2, 1)],
    "S": [(1, 0), (2, 0), (0, 1), (1, 1)],
    "Z": [(0, 0), (1, 0), (1, 1), (2, 1)],
    "J": [(0, 0), (0, 1), (1, 1), (2, 1)],
    "L": [(2, 0), (0, 1), (1, 1), (2, 1)],
}
COLORS = {
    "I": (0, 220, 230), "O": (240, 220, 0), "T": (180, 70, 230), "S": (60, 220, 60),
    "Z": (240, 50, 50), "J": (50, 100, 255), "L": (255, 150, 0),
}
LINE_SCORE = [0, 100, 300, 500, 800]
DAS, ARR = 10, 3  # frames before auto-repeat, frames between repeats (at 50 fps)

WHITE, GREY, DARK = (255, 255, 255), (120, 120, 120), (80, 80, 80)

screen = lcd.init()
font = pygame.font.Font(None, 14)
font_big = pygame.font.Font(None, 22)
clock = pygame.time.Clock()


def rotate(cells, kind):
    if kind == "O":
        return cells
    size = 4 if kind == "I" else 3
    return [(size - 1 - y, x) for x, y in cells]


def gravity_frames(level):
    return max(2, 48 - level * 5)


def load_hi():
    try:
        with open(HI_FILE) as f:
            return int(f.read().strip() or 0)
    except (OSError, ValueError):
        return 0


def save_hi(score):
    try:
        with open(HI_FILE, "w") as f:
            f.write(str(score))
    except OSError:
        pass


class Game:
    def __init__(self):
        self.hi = load_hi()
        self.reset()

    def reset(self):
        self.board = [[None] * COLS for _ in range(ROWS)]
        self.bag = []
        self.next = self.from_bag()
        self.score = self.lines = 0
        self.level = 1
        self.state = "play"  # play, pause, over
        self.clearing = []   # rows flashing before removal
        self.flash = 0
        self.spawn()

    def from_bag(self):
        if not self.bag:
            self.bag = list(SHAPES)
            random.shuffle(self.bag)
        return self.bag.pop()

    def spawn(self):
        self.kind = self.next
        self.next = self.from_bag()
        self.cells = list(SHAPES[self.kind])
        self.px, self.py = 3, 0
        self.fall = 0
        if self.collides(self.cells, self.px, self.py):
            self.state = "over"
            if self.score > self.hi:
                self.hi = self.score
                save_hi(self.hi)

    def collides(self, cells, px, py):
        for x, y in cells:
            x, y = x + px, y + py
            if x < 0 or x >= COLS or y >= ROWS or (y >= 0 and self.board[y][x]):
                return True
        return False

    def move(self, dx, dy):
        if not self.collides(self.cells, self.px + dx, self.py + dy):
            self.px += dx
            self.py += dy
            return True
        return False

    def turn(self):
        new = rotate(self.cells, self.kind)
        for kick in (0, -1, 1, -2, 2):  # simple wall kicks
            if not self.collides(new, self.px + kick, self.py):
                self.cells, self.px = new, self.px + kick
                return

    def hard_drop(self):
        dropped = 0
        while self.move(0, 1):
            dropped += 1
        self.score += dropped * 2
        self.lock()

    def ghost_y(self):
        y = self.py
        while not self.collides(self.cells, self.px, y + 1):
            y += 1
        return y

    def lock(self):
        for x, y in self.cells:
            if self.py + y >= 0:
                self.board[self.py + y][self.px + x] = self.kind
        self.clearing = [r for r in range(ROWS) if all(self.board[r])]
        if self.clearing:
            self.flash = 12
        else:
            self.spawn()

    def finish_clear(self):
        n = len(self.clearing)
        for r in self.clearing:
            del self.board[r]
            self.board.insert(0, [None] * COLS)
        self.clearing = []
        self.lines += n
        self.score += LINE_SCORE[n] * self.level
        self.level = 1 + self.lines // 10
        self.spawn()

    def update(self, soft_drop):
        if self.state != "play":
            return
        if self.clearing:
            self.flash -= 1
            if self.flash <= 0:
                self.finish_clear()
            return
        self.fall += 1
        speed = 2 if soft_drop else gravity_frames(self.level)
        if self.fall >= speed:
            self.fall = 0
            if self.move(0, 1):
                if soft_drop:
                    self.score += 1
            else:
                self.lock()

    def draw_cell(self, x, y, color, outline=False):
        r = pygame.Rect(BX + x * CELL, BY + y * CELL, CELL, CELL)
        if outline:
            pygame.draw.rect(screen, color, r, 1)
        else:
            pygame.draw.rect(screen, color, r.inflate(-1, -1))

    def draw(self):
        screen.fill((0, 0, 0))
        pygame.draw.rect(screen, GREY, (BX - 2, BY - 2, COLS * CELL + 4, ROWS * CELL + 4), 1)
        for y, row in enumerate(self.board):
            for x, kind in enumerate(row):
                if kind:
                    color = WHITE if y in self.clearing and self.flash % 4 < 2 else COLORS[kind]
                    self.draw_cell(x, y, color)
        if self.state != "over" and not self.clearing:
            gy = self.ghost_y()
            for x, y in self.cells:
                if gy + y >= 0:
                    self.draw_cell(self.px + x, gy + y, DARK, outline=True)
            for x, y in self.cells:
                if self.py + y >= 0:
                    self.draw_cell(self.px + x, self.py + y, COLORS[self.kind])

        # side panel
        sx = BX + COLS * CELL + 8
        screen.blit(font.render("NEXT", True, GREY), (sx, 4))
        for x, y in SHAPES[self.next]:
            pygame.draw.rect(screen, COLORS[self.next], (sx + 2 + x * 6, 16 + y * 6, 5, 5))
        for i, (label, value) in enumerate((("SCORE", self.score), ("LINES", self.lines),
                                            ("LEVEL", self.level), ("BEST", self.hi))):
            y = 34 + i * 23
            screen.blit(font.render(label, True, GREY), (sx, y))
            screen.blit(font.render(str(value), True, WHITE), (sx, y + 10))

        if self.state == "pause":
            self.banner("PAUSE", "KEY2: resume")
        elif self.state == "over":
            self.banner("GAME OVER", "PRESS: again")
        lcd.flip()

    def banner(self, title, hint):
        box = pygame.Rect(6, 46, 116, 36)
        pygame.draw.rect(screen, (0, 0, 0), box)
        pygame.draw.rect(screen, (255, 200, 0), box, 1)
        t = font_big.render(title, True, (255, 200, 0))
        screen.blit(t, ((128 - t.get_width()) // 2, 50))
        h = font.render(hint, True, WHITE)
        screen.blit(h, ((128 - h.get_width()) // 2, 68))


game = Game()
held = set()
repeat = {pygame.K_LEFT: 0, pygame.K_RIGHT: 0}
running = True
while running:
    for ev in pygame.event.get():
        if ev.type == pygame.QUIT:  # SIGTERM from systemctl stop
            running = False
        elif ev.type == pygame.KEYDOWN:
            held.add(ev.key)
            k = ev.key
            if k in (pygame.K_3, pygame.K_ESCAPE):
                running = False
            elif game.state == "over":
                if k in (pygame.K_RETURN, pygame.K_1, pygame.K_SPACE):
                    game.reset()
            elif k == pygame.K_2:
                game.state = "play" if game.state == "pause" else "pause"
            elif game.state == "play" and not game.clearing:
                if k == pygame.K_LEFT:
                    game.move(-1, 0)
                    repeat[k] = 0
                elif k == pygame.K_RIGHT:
                    game.move(1, 0)
                    repeat[k] = 0
                elif k in (pygame.K_UP, pygame.K_RETURN):
                    game.turn()
                elif k in (pygame.K_1, pygame.K_SPACE):
                    game.hard_drop()
        elif ev.type == pygame.KEYUP:
            held.discard(ev.key)

    # auto-repeat for held left/right
    if game.state == "play" and not game.clearing:
        for k, dx in ((pygame.K_LEFT, -1), (pygame.K_RIGHT, 1)):
            if k in held:
                repeat[k] += 1
                if repeat[k] >= DAS and (repeat[k] - DAS) % ARR == 0:
                    game.move(dx, 0)

    game.update(pygame.K_DOWN in held)
    game.draw()
    clock.tick(50)

if game.score > game.hi:
    save_hi(game.score)
screen.fill((0, 0, 0))
lcd.flip()
lcd.quit()
