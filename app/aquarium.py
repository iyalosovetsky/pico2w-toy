"""Planted freshwater aquarium; Esc / KEY3 returns to the menu."""
import math
import random
import time
import pygame
import pygame.gfxdraw
import lcd


def stroke(width):
    return max(1, round(width)) if lcd.S == 1 else width


class Aquarium:
    def __init__(self, screen):
        self.screen = screen
        rng = random.Random(731)
        self.back = lcd.Surface((128, 128)) if lcd.S != 1 else pygame.Surface((128, 128))
        for y in range(128):
            pygame.draw.rect(self.back, (5, 88-y//2, 105-y//2), (0,y,128,1))
        for i in range(45):
            x, h = rng.uniform(0,128), rng.uniform(20,90)
            pygame.draw.lines(self.back,(8,43+i%13,30),False,[(x,120),(x+3,120-h/2),(x-3,120-h)],2)
        pygame.draw.polygon(self.back,(65,59,38),[(0,116),(40,119),(88,115),(128,118),(128,128),(0,128)])
        for _ in range(1000):
            c = rng.choice([(92,81,51),(118,103,66),(45,47,31),(140,122,82)])
            pygame.draw.circle(self.back,c,(rng.uniform(0,128),rng.uniform(119,128)),rng.uniform(.2,.6))
        # Dark stems on the left, broad leaves and a grassy centre as in the reference.
        self.plants = [(x,rng.uniform(55,104),rng.random()*6.28,1+i%2)
                       for i,x in enumerate([2,7,13,19,25,108,115,123,127,103])]
        self.plants += [(40,44,1,3), (53,36,3,3), (75,34,2,0), (113,43,4,3)]
        for x,y,w,h in [(27,118,22,10),(57,121,18,15),(81,124,13,7),(46,125,8,5)]:
            pygame.draw.ellipse(self.back,(91,92,60),(x-w/2,y-h/2,w,h))
            pygame.draw.ellipse(self.back,(155,147,104),(x-w/2+1,y-h/2,w-3,h-3))
            for _ in range(35):
                dx,dy = rng.uniform(-.42,.42)*w,rng.uniform(-.3,.3)*h
                pygame.draw.circle(self.back,(112,114,75),(x+dx,y+dy),.35)
        self.bubbles = [(rng.random(),rng.uniform(-2,2),rng.uniform(.5,1.2)) for _ in range(34)]

    def plant(self, x,h,phase,kind,t):
        s = self.screen
        color = (24,106,44) if kind else (39,132,49)
        if kind == 3:
            for j in range(7):
                side = -1 if j % 2 else 1
                py = 113-h*(.2+j*.11)
                px = x+side*(5+j*.8)+math.sin(t*.55+phase+j)*1.3
                pygame.draw.line(s,(58,113,30),(x,120),(px,py),stroke(.5))
                base = (x, py+6)
                tip = (px+side*7, py-4)
                # Two curved edges meet at the tip without angular notches.
                points = []
                for a, b, control in (
                    (base, tip, (px-side*2, py-12)),
                    (tip, base, (px+side*9, py+7)),
                ):
                    for step in range(13):
                        u = step/12
                        points.append(tuple((1-u)**2*a[i]+2*u*(1-u)*control[i]+u*u*b[i]
                                            for i in (0, 1)))
                scale = lcd.S if isinstance(s, lcd.Surface) else 1
                native = [(round(a*scale), round(b*scale)) for a,b in points]
                color = (57+j*5,119+j*5,27)
                pygame.gfxdraw.filled_polygon(s, native, color)
                pygame.gfxdraw.aapolygon(s, native, color)
                pygame.draw.aaline(s,(130,167,57),
                                   tuple(v*scale for v in base),
                                   tuple(v*scale for v in tip))
        elif kind == 0:
            for j in range(9):
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
        # Narrow to an edge-on silhouette before changing direction.
        turn = max(.06, abs(math.cos(t*.13+phase)))
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
        gold = phase < 1 or phase > 4
        poly((196,166,80) if gold else (172,191,173),[(-11,0),(-6,-8),(1,-10),(7,-5),(10,-1),(8,3),(3,9),(-5,7)])
        poly((231,194,100) if gold else (207,213,187),[(-6,-5),(1,-9),(7,-4),(8,-1),(0,1),(-7,2)])
        for a in (-6,0,5):
            poly((92,76,39) if gold else (39,58,57),[(a-1,-7),(a+1,-6),(a+2,6),(a,7)])
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
            pygame.draw.line(s,(14,83,93),(x,3),(x-12,65),stroke(.35))
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
        pygame.event.clear()
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
