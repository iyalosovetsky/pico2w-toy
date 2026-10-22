"""Planted freshwater aquarium; Esc / KEY3 returns to the menu."""
import math
import random
import time
import pygame
import lcd


def stroke(width):
    return max(1, round(width)) if lcd.S == 1 else width


class Aquarium:
    def __init__(self, screen):
        self.screen = screen
        rng = random.Random(731)
        self.back = lcd.Surface((128, 128)) if lcd.S != 1 else pygame.Surface((128, 128))
        for y in range(128):
            pygame.draw.rect(self.back, (4, 38-y//5, 48-y//4), (0,y,128,1))
        for i in range(45):
            x, h = rng.uniform(0,128), rng.uniform(20,90)
            pygame.draw.lines(self.back,(8,43+i%13,30),False,[(x,120),(x+3,120-h/2),(x-3,120-h)],2)
        pygame.draw.polygon(self.back,(65,59,38),[(0,116),(40,119),(88,115),(128,118),(128,128),(0,128)])
        for _ in range(1000):
            c = rng.choice([(92,81,51),(118,103,66),(45,47,31),(140,122,82)])
            pygame.draw.circle(self.back,c,(rng.uniform(0,128),rng.uniform(119,128)),rng.uniform(.2,.6))
        self.plants = [(x,rng.uniform(43,96),rng.random()*6.28,i%3) for i,x in enumerate([2,8,15,22,28,102,108,115,122,127,35,94])]
        self.bubbles = [(rng.random(),rng.uniform(-2,2),rng.uniform(.5,1.2)) for _ in range(34)]

    def plant(self, x,h,phase,kind,t):
        s = self.screen
        color = (24,106,44) if kind else (39,132,49)
        if kind == 0:
            for j in range(4):
                top = (x+j*2+math.sin(t*.65+phase)*3-4,119-h*(.65+j*.12))
                mid = (x+j+2,119-h*.4)
                pygame.draw.polygon(s,color,[(x+j,120),mid,top,(mid[0]-2,mid[1])])
                pygame.draw.lines(s,(70,157,57),False,[(x+j,120),mid,top],stroke(.35))
        else:
            points = [(x+math.sin(t*.65+phase+k*.25)*k*.25,119-h*k/7) for k in range(8)]
            pygame.draw.lines(s,(33,101,38),False,points,stroke(.6))
            for k,(px,py) in enumerate(points[1:],1):
                for side in (-1,1):
                    length = (8 if kind == 1 else 5)*(1-k*.06)
                    tip = (px+side*length,py-4)
                    pygame.draw.polygon(s,color,[(px,py),(px+side*length*.45,py-5),tip,(px+side*length*.65,py+.4)])
                    pygame.draw.line(s,(75,151,56),(px,py),tip,stroke(.35))

    def angel(self,x,y,size,direction,t,phase):
        s = self.screen
        turn = .4+.6*abs(math.cos(t*.13+phase))
        def p(a,b):
            return x+a*size*direction*turn,y+b*size
        def poly(c,pts):
            pygame.draw.polygon(s,c,[p(a,b) for a,b in pts])
        wave = math.sin(t*3+phase)
        poly((99,132,132),[(-3,-3),(-5,-22),(3,-10),(8,-2)])
        poly((112,141,137),[(-4,4),(-5,22),(4,11),(8,2)])
        poly((137,158,145),[(-9,0),(-17,-7-wave),(-16,7+wave)])
        for k in range(4):
            pygame.draw.line(s,(66,102,102),p(-4,-19+k*3),p(4,-4+k),stroke(.35))
        poly((172,191,173),[(-11,0),(-6,-8),(1,-10),(7,-5),(10,-1),(8,3),(3,9),(-5,7)])
        poly((207,213,187),[(-6,-5),(1,-9),(7,-4),(8,-1),(0,1),(-7,2)])
        for a in (-6,0,5):
            poly((39,58,57),[(a-1,-7),(a+1,-6),(a+2,6),(a,7)])
        for a in (0,3):
            pygame.draw.lines(s,(181,199,170),False,[p(a,6),p(a,16),p(a+3+wave,25)],stroke(.4))
        pygame.draw.line(s,(224,216,165),p(2,0),p(-4,3+wave),stroke(.7))
        pygame.draw.circle(s,(222,163,63),p(6,-2),1.2*size)
        pygame.draw.circle(s,(10,17,16),p(6.3,-2),.55*size)

    def draw(self,t):
        s = self.screen
        s.blit(self.back,(0,0))
        for x,h,ph,k in self.plants[:10]:
            self.plant(x,h,ph,k,t)
        for i in range(6):
            x = 10+i*22+math.sin(t*.4+i)*3
            pygame.draw.line(s,(15,52,55),(x,3),(x-12,65),stroke(.35))
        for i in range(3):
            ph = i*2.1
            x = 64+math.sin(t*.13+ph)*37
            y = 44+i*14+math.sin(t*.31+ph)*5
            d = 1 if math.cos(t*.13+ph)>=0 else -1
            self.angel(x,y,[.9,.72,1][i],d,t,ph)
        d = 1 if math.cos(t*.22)>=0 else -1
        for i in range(13):
            x = 64+math.sin(t*.22)*36+(i%5-2)*7+math.sin(t*1.1+i)*2
            y = 85+(i//5)*7+math.sin(t*.8+i*.7)*3
            w = math.sin(t*9+i)*.7
            pygame.draw.polygon(s,(38,91,106),[(x-d*3,y),(x-d*6,y-2-w),(x-d*6,y+2+w)])
            pygame.draw.ellipse(s,(112,151,148),(x-4,y-1.5,8,3))
            pygame.draw.line(s,(232,40,52),(x-d*3,y+1),(x,y+1),1)
            pygame.draw.line(s,(21,130,186),(x-d*3.5,y-.7),(x+d*3,y-.7),stroke(1.3))
            pygame.draw.line(s,(83,238,246),(x-d*3,y-1),(x+d*3,y-1),stroke(.4))
            pygame.draw.circle(s,(8,17,20),(x+d*2.7,y),.5)
        pygame.draw.line(s,(32,44,39),(91,128),(88,118),stroke(1.5))
        pygame.draw.ellipse(s,(85,91,77),(82,115,12,4))
        for ph,dx,r in self.bubbles:
            age = (t*.15+ph)%1
            y = 115-age*113
            x = 88+dx+math.sin(age*15+t*.8+ph*7)*(1+age*2.5)
            radius = r*(.6+age*.65)
            pygame.draw.circle(s,(81,139,145),(x,y),radius,stroke(.35))
            pygame.draw.circle(s,(172,213,207),(x-radius*.3,y-radius*.4),.25)
        for x,h,ph,k in self.plants[10:]:
            self.plant(x,h*.6,ph,k,t)
        for j in range(3):
            pts = [(x,2+j*1.3+math.sin(x*.16+t*1.6+j)*.7) for x in range(129)]
            pygame.draw.lines(s,(34+j*9,88+j*9,87+j*8),False,pts,stroke(.4))


def main(seconds=None):
    screen = lcd.init()
    clock = pygame.time.Clock()
    scene = Aquarium(screen)
    start = time.monotonic()
    try:
        while True:
            t = time.monotonic()-start
            if seconds is not None and t >= seconds:
                break
            for ev in pygame.event.get():
                if ev.type == pygame.QUIT or (ev.type == pygame.KEYDOWN and
                    (ev.key == pygame.K_ESCAPE or (ev.key == pygame.K_3 and getattr(ev,'hat',False)))):
                    return
            scene.draw(t)
            lcd.flip()
            clock.tick(20)
    finally:
        lcd.quit()


if __name__ == '__main__':
    main()
