"""Pong vs AI for the Waveshare 1.44" LCD HAT.

Joystick UP/DOWN - move paddle, PRESS / KEY1 - start / pause,
KEY2 - change AI difficulty, KEY3 - exit.
Keyboard: arrows, Enter/Space - start / pause, 2 - difficulty, Esc - exit.
"""
import random

import pygame
import lcd

W = H = 128
PAD_W, PAD_H = 3, 22
BALL = 3
WIN_SCORE = 7
PLAYER_SPEED = 2.6
LEVELS = [  # name, AI max speed, reaction error (px), reaction delay (frames)
    ("EASY", 1.4, 14, 10),
    ("NORMAL", 1.9, 8, 6),
    ("HARD", 2.6, 3, 2),
]

WHITE = (255, 255, 255)
GREY = (90, 90, 90)
GREEN = (0, 220, 120)
RED = (255, 70, 70)
YELLOW = (255, 220, 0)

screen = lcd.init()
font_big = pygame.font.Font(None, 28)
font = pygame.font.Font(None, 16)
clock = pygame.time.Clock()


class Game:
    def __init__(self):
        self.level = 1
        self.new_match()

    def new_match(self):
        self.score = [0, 0]  # player, ai
        self.player_y = self.ai_y = (H - PAD_H) / 2
        self.state = "title"  # title, play, pause, point, over
        self.serve(direction=random.choice((-1, 1)))

    def serve(self, direction):
        self.bx, self.by = W / 2, H / 2
        speed = 1.8
        self.vx = speed * direction
        self.vy = random.uniform(-1.2, 1.2)
        self.ai_target = H / 2
        self.ai_timer = 0
        self.wait = 40  # frames before the ball moves

    def update(self, held):
        if self.state != "play":
            return
        # player
        if pygame.K_UP in held:
            self.player_y -= PLAYER_SPEED
        if pygame.K_DOWN in held:
            self.player_y += PLAYER_SPEED
        self.player_y = max(0, min(H - PAD_H, self.player_y))

        # AI: re-aims every few frames with some error, limited speed
        _, ai_speed, err, delay = LEVELS[self.level]
        self.ai_timer -= 1
        if self.ai_timer <= 0:
            self.ai_timer = delay
            if self.vx > 0:
                self.ai_target = self.predict_y() + random.uniform(-err, err)
            else:
                self.ai_target = H / 2
        centre = self.ai_y + PAD_H / 2
        dy = self.ai_target - centre
        self.ai_y += max(-ai_speed, min(ai_speed, dy))
        self.ai_y = max(0, min(H - PAD_H, self.ai_y))

        if self.wait > 0:
            self.wait -= 1
            return

        # ball
        self.bx += self.vx
        self.by += self.vy
        if self.by <= 0:
            self.by, self.vy = 0, abs(self.vy)
            lcd.play("wall")
        elif self.by >= H - BALL:
            self.by, self.vy = H - BALL, -abs(self.vy)
            lcd.play("wall")

        if self.vx < 0 and self.bx <= 2 + PAD_W and self.bx >= 0:
            self.hit(self.player_y, 1)
        elif self.vx > 0 and self.bx + BALL >= W - 2 - PAD_W and self.bx + BALL <= W:
            self.hit(self.ai_y, -1)

        if self.bx < -BALL:
            self.point(1)
        elif self.bx > W:
            self.point(0)

    def hit(self, pad_y, direction):
        if pad_y - BALL <= self.by <= pad_y + PAD_H:
            # bounce angle depends on where the ball hits the paddle
            rel = (self.by + BALL / 2 - (pad_y + PAD_H / 2)) / (PAD_H / 2)
            speed = min(abs(self.vx) * 1.06, 4.0)
            self.vx = speed * direction
            self.vy = rel * 2.2 + random.uniform(-0.2, 0.2)
            self.bx = 2 + PAD_W if direction > 0 else W - 2 - PAD_W - BALL
            lcd.play("hit")

    def predict_y(self):
        """Where the ball will cross the AI paddle line (with wall bounces)."""
        if self.vx <= 0:
            return H / 2
        t = (W - 2 - PAD_W - BALL - self.bx) / self.vx
        y = self.by + self.vy * t
        span = H - BALL
        y %= 2 * span
        if y > span:
            y = 2 * span - y
        return y + BALL / 2

    def point(self, who):
        self.score[who] += 1
        if self.score[who] >= WIN_SCORE:
            self.state = "over"
            lcd.play("win" if who == 0 else "lose")
        else:
            lcd.play("point" if who == 0 else "score")
            self.serve(direction=-1 if who == 0 else 1)

    def draw(self):
        screen.fill((0, 0, 0))
        for y in range(0, H, 8):
            pygame.draw.rect(screen, GREY, (W // 2 - 1, y, 2, 4))
        s = font_big.render(str(self.score[0]), True, GREY)
        screen.blit(s, (W // 2 - 10 - s.get_width(), 4))
        s = font_big.render(str(self.score[1]), True, GREY)
        screen.blit(s, (W // 2 + 10, 4))

        pygame.draw.rect(screen, GREEN, (2, round(self.player_y), PAD_W, PAD_H))
        pygame.draw.rect(screen, RED, (W - 2 - PAD_W, round(self.ai_y), PAD_W, PAD_H))
        if self.state in ("play", "pause"):
            pygame.draw.rect(screen, WHITE, (round(self.bx), round(self.by), BALL, BALL))

        if self.state == "title":
            self.banner("PONG", lcd.OK + ": start", lcd.ALT + ": " + LEVELS[self.level][0])
        elif self.state == "pause":
            self.banner("PAUSE", lcd.OK + ": resume", lcd.BACK + ": exit")
        elif self.state == "over":
            won = self.score[0] > self.score[1]
            self.banner("YOU WIN!" if won else "AI WINS", lcd.OK + ": again", lcd.ALT + ": " + LEVELS[self.level][0])
        lcd.flip()

    def banner(self, title, *lines):
        box = pygame.Rect(10, 36, W - 20, 58)
        pygame.draw.rect(screen, (0, 0, 0), box)
        pygame.draw.rect(screen, YELLOW, box, 1)
        t = font_big.render(title, True, YELLOW)
        screen.blit(t, ((W - t.get_width()) // 2, 41))
        for i, line in enumerate(lines):
            s = font.render(line, True, WHITE)
            screen.blit(s, ((W - s.get_width()) // 2, 64 + i * 13))


game = Game()
held = set()
running = True
while running:
    for ev in pygame.event.get():
        if ev.type == pygame.QUIT:  # SIGTERM from systemctl stop
            running = False
        elif ev.type == pygame.KEYDOWN:
            held.add(ev.key)
            if ev.key in (pygame.K_3, pygame.K_ESCAPE):
                running = False
            elif ev.key in (pygame.K_RETURN, pygame.K_1, pygame.K_SPACE):
                if game.state == "play":
                    game.state = "pause"
                elif game.state in ("pause", "title"):
                    game.state = "play"
                elif game.state == "over":
                    game.new_match()
                    game.state = "play"
            elif ev.key == pygame.K_2 and game.state in ("title", "over", "pause"):
                game.level = (game.level + 1) % len(LEVELS)
        elif ev.type == pygame.KEYUP:
            held.discard(ev.key)
    game.update(held)
    game.draw()
    clock.tick(50)

screen.fill((0, 0, 0))
lcd.flip()
lcd.quit()
