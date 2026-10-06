import pygame
import lcd

screen = lcd.init()
font = pygame.font.Font(None, 18)
clock = pygame.time.Clock()
x, y = 64, 64
last = "-"
running = True
while running:
    for ev in pygame.event.get():
        if ev.type == pygame.KEYDOWN:
            last = pygame.key.name(ev.key)
            if ev.key == pygame.K_3:
                running = False
    screen.fill((0, 0, 0))
    # orientation / offset test: 1px border R, G corner marks
    pygame.draw.rect(screen, (255, 0, 0), (0, 0, 128, 128), 1)
    pygame.draw.rect(screen, (0, 255, 0), (0, 0, 10, 10))          # top-left = green
    pygame.draw.rect(screen, (0, 0, 255), (118, 118, 10, 10))      # bottom-right = blue
    screen.blit(font.render("TOP", True, (255, 255, 255)), (50, 4))
    screen.blit(font.render("key: " + last, True, (255, 255, 0)), (8, 100))
    screen.blit(font.render(lcd.BACK + " = exit", True, (120, 120, 120)), (8, 112))
    pygame.draw.circle(screen, (255, 128, 0), (x, y), 6)
    lcd.flip()
    clock.tick(30)
    if last == "up": y = max(6, y - 2)
    elif last == "down": y = min(121, y + 2)
    elif last == "left": x = max(6, x - 2)
    elif last == "right": x = min(121, x + 2)
lcd.quit()
