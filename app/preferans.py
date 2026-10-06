"""Preferans for the Waveshare 1.44" LCD HAT - a pygame front-end for the PyPref engine.

The game logic and computer players are Python Pref (PyPref) 2.34 - based on
kpref by Azarniy I.V. and OpenPref, by Alexander aka amigo and Vadim Zapletin,
GNU GPL - ported to Python 3 in prefgame/. Rules: Sochi (default) or Leningrad,
chosen when a new pulka starts; pulka to 20.

You are at the bottom, West (left) and East (right) are the computer.
Joystick LEFT/RIGHT - choose a card / bid, UP/DOWN - bid by level (and DOWN takes
back a discarded card), PRESS or KEY1 - confirm, KEY2 - score sheet,
KEY3 - exit (the pulka is saved after every deal).
Keyboard: arrows, Enter / Space, 2, Esc.
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import pygame  # noqa: E402
import lcd  # noqa: E402
from prefgame import cardlist  # noqa: E402
from prefgame.desktop import TDeskTop  # noqa: E402
from prefgame.ncounter import Tncounter  # noqa: E402
from prefgame.plscore import TPlScore  # noqa: E402
from prefgame.prfconst import *  # noqa: E402,F401,F403

SAVE_FILE = os.path.join(HERE, "preferans_save.json")
FONT = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
FONT_BOLD = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
FONT_MONO_BOLD = "/usr/share/fonts/truetype/dejavu/DejaVuSansMono-Bold.ttf"
BULLET = 20

NAMES = {1: "Ви", 2: "Захід", 3: "Схід"}
RULES = [("СОЧИНКА", Sochi), ("ЛЕНІНГРАДКА", Peter)]
RULE_NAMES = {Sochi: "СОЧИНКА", Peter: "ЛЕНІНГРАДКА"}
SUIT_CH = {1: "♠", 2: "♣", 3: "♦", 4: "♥", 5: "БК"}
RANK_CH = {7: "7", 8: "8", 9: "9", 10: "10", 11: "В", 12: "Д", 13: "К", 14: "Т"}
# PyPref options (index -> value); defaults from its pypref.cfg
OPT_DEFAULT = [0, 0, 0, 0, 0, 0, 0, 2, 1, 2, 2, 0, 1, 1, 1, 1, 0, 0, 0, 1, 1, 0, 0, 0]

AI_DELAY = 0.6      # s after a computer card / bid
TRICK_PAUSE = 0.9   # s the full trick stays on the table

GREEN = (0, 80, 40)
WHITE, BLACK, GREY, LIGHT = (255, 255, 255), (0, 0, 0), (150, 170, 155), (210, 225, 215)
YELLOW, RED, CARD_RED = (255, 210, 0), (230, 60, 50), (200, 20, 30)

CONFIRM = (pygame.K_RETURN, pygame.K_1, pygame.K_SPACE)


class Quit(Exception):
    """KEY3 / Esc / SIGTERM: leave the game from anywhere inside the engine."""


def game_name(g):
    special = {pas: "пас", vist: "віст", halfvist: "пів-віст", g86: "мізер", g86catch: "ловлю",
               bez3: "без 3", raspas: "розпаси", undefined: ""}
    if g in special:
        return special[g]
    if g is None or g < g61:
        return ""
    return "%d%s" % (g // 10, SUIT_CH[g % 10])


class PrefGUI:
    def __init__(self):
        self.screen = lcd.init()
        self.f8 = pygame.font.Font(FONT, 8)
        self.f9 = pygame.font.Font(FONT, 9)
        self.f10 = pygame.font.Font(FONT, 10)
        self.f10b = pygame.font.Font(FONT_BOLD, 10)
        self.f12b = pygame.font.Font(FONT_BOLD, 12)
        self.f14b = pygame.font.Font(FONT_BOLD, 14)
        self.rank_small = pygame.font.Font(FONT_MONO_BOLD, 9)  # clearest 7/8/9 at this size
        self.clock = pygame.time.Clock()
        self.opt = list(OPT_DEFAULT) + [None]
        self.set_rules(Sochi)
        cardlist.TCardList(sort=self.Sort)
        self.app = None
        self.reset_table()
        self.show_sheet = False
        self.prompt = None       # (title, label) of an open choice
        self.select = None       # (gamer, index, Min, Max) while choosing a card
        self.status = ""
        self.paper_mode = False
        self.discarding = False  # show the discarded cards in the middle

    # ---------------------------------------------------------------- helpers
    def set_rules(self, rules):
        """Sochi or Peter (Leningrad), with PyPref's PrefGUI.DefaultOpt() for them."""
        self.opt[scorerules] = rules
        sochi = 1 if rules == Sochi else 0
        self.opt[pastalon] = self.opt[pasprogress] = 1
        self.opt[greedywhist] = self.opt[responsible] = sochi

    def Sort(self, a, b):
        morder = self.opt[sorder] and [1, 2, 3, 4] or [1, 3, 2, 4]
        ka, kb = morder.index(a.CMast), morder.index(b.CMast)
        if ka != kb:
            return (ka > kb) - (ka < kb)
        if self.opt[corder]:
            return (a.CName > b.CName) - (a.CName < b.CName)
        return (b.CName > a.CName) - (b.CName < a.CName)

    def reset_table(self):
        self.labels = {1: "", 2: "", 3: ""}
        self.desk = {}           # gamer number -> card in the current trick
        self.prikup = (0, None, None)
        self.open_hands = set()  # computer hands shown face up

    def events(self):
        """Pump input; returns the list of pressed keys. Raises Quit."""
        keys = []
        for ev in pygame.event.get():
            if ev.type == pygame.QUIT:
                raise Quit
            if ev.type == pygame.KEYDOWN:
                if ev.key in (pygame.K_3, pygame.K_ESCAPE):
                    raise Quit
                if ev.key == pygame.K_2:
                    self.show_sheet = not self.show_sheet
                    continue
                if self.show_sheet:
                    self.show_sheet = False  # any key closes the sheet
                    continue
                keys.append(ev.key)
        return keys

    def frame(self):
        self.draw()
        self.clock.tick(20)

    def sleep(self, seconds):
        end = pygame.time.get_ticks() + int(seconds * 1000)
        while pygame.time.get_ticks() < end:
            self.events()
            self.frame()

    def wait_confirm(self, status=None):
        old = self.status
        if status is not None:
            self.status = status
        while True:
            if any(k in CONFIRM for k in self.events()):
                break
            self.frame()
        self.status = old

    # ---------------------------------------------------------------- engine callbacks
    def Clear(self, ngamer=None, what="c"):
        if ngamer is None:
            self.reset_table()
        else:
            self.prikup = (0, None, None)

    def ShowHand(self, gamer, idx=-1, hint=None, hint1=None, counter=None):
        if gamer.nGamer != 1 and idx == -2:
            if gamer.closed:
                self.open_hands.discard(gamer.nGamer)
            else:
                self.open_hands.add(gamer.nGamer)
        self.frame()

    def ShowMove(self, card=None, gamer=None):
        if len(self.desk) >= 3:
            self.desk = {}
        self.desk[gamer.nGamer] = card
        self.prikup = (0, None, None)
        lcd.play("card")
        computer = not (gamer.human and self.app.mode != demo)
        if len(self.desk) == 3:
            self.sleep(TRICK_PAUSE)
        elif computer:
            self.sleep(AI_DELAY)
        else:
            self.frame()

    def ShowGame(self, gamer, game=None, nMove=0, hint=None):
        if game is not None:
            self.labels[gamer.nGamer] = game_name(game)
            if gamer.nGamer != 1 and game not in (undefined,) and nMove != -1:
                self.sleep(AI_DELAY)
                return
        self.frame()

    def HitReturn(self, forcekey=False, ok=True, anytap=False):
        self.wait_confirm(lcd.OK + " - далі")

    def ShowPrikup(self, n, card1=None, card2=None):
        self.prikup = (n, card1, card2)
        if card1 and card2:
            self.desk = {}
            self.HitReturn(anytap=True)
        else:
            self.frame()

    def StopGame(self):
        self.events()
        return False

    def AskOpen(self):
        return self.choose("Відкрити карти?", ["так", "ні"], [True, False])

    def ShowPaper(self, forcekey=None, load=None):
        save_pulka(self.app)
        self.paper_mode = True
        self.show_sheet = True
        while self.show_sheet:
            keys = self.events()
            if any(k in CONFIRM for k in keys):
                self.show_sheet = False
            self.frame()
        self.paper_mode = False
        return True

    def choose(self, title, labels, values, start=0, jumps=None):
        """Generic left/right chooser; jumps(index, up) -> new index for UP/DOWN."""
        i = start
        while True:
            self.prompt = (title, labels[i])
            for k in self.events():
                if k == pygame.K_LEFT:
                    i = (i - 1) % len(labels)
                    lcd.play("click")
                elif k == pygame.K_RIGHT:
                    i = (i + 1) % len(labels)
                    lcd.play("click")
                elif k in (pygame.K_UP, pygame.K_DOWN) and jumps:
                    i = jumps(i, k == pygame.K_UP)
                    lcd.play("click")
                elif k in CONFIRM:
                    self.prompt = None
                    lcd.play("select")
                    return values[i]
            self.frame()

    def MakeGame(self, gamer, game=None, vistpas=False, hint=None):
        """Bidding / contract / whist choice - list built as in PyPref's PrefGUI."""
        app = self.app
        val = 0
        if vistpas:
            lst = [vist, pas]
            if self.opt[halfwhist] and nGetMinCard4Vist(game) >= 2:
                nRight = gamer.nGamer == 1 and 3 or (gamer.nGamer == 2 and 1 or 2)
                if app.Gamer(nRight).GamesType == pas:
                    lst = [halfvist, vist]
            title = "%s?" % game_name(app.CurrentGame)
        else:
            lst = []
            if game:
                lst.append(pas)
                val += 1
                if gamer.GamesType == undefined and game < g91:
                    lst.insert(0, g86)
                    val += 1
                nRight = gamer.nGamer == 1 and 3 or (gamer.nGamer == 2 and 1 or 2)
                nLeft = gamer.nGamer == 1 and 2 or (gamer.nGamer == 2 and 3 or 1)
                if game >= g61 and game != g86 and (app.Gamer(nRight).GamesType == pas or app.Gamer(nLeft).GamesType == pas):
                    if app.Gamer(nRight).GamesType == pas and nRight == app.nCurrentStart.nValue \
                            or gamer.nGamer == app.nCurrentStart.nValue:
                        lst.append(game)
                if game < g61:
                    game = gamer.MinTricks() * 10 + 1
                    lst.append(game)
                title = "Торг"
            else:
                game = gamer.GamesType
                if game == g86:
                    return g86
                if self.opt[without3]:
                    lst.append(bez3)
                    val += 1
                lst.append(game)
                title = "Ваша гра"
            while True:
                game = NextGame(game)
                lst.append(game)
                if game == g105:
                    break
        base = game

        def jumps(i, up):  # UP/DOWN: next/previous level with the same suit
            cur = lst[i]
            if cur < g61 or cur == g86:
                return i
            target = cur + 10 if up else cur - 10
            if target in lst:
                return lst.index(target)
            return i
        labels = [game_name(g).upper() for g in lst]
        return self.choose(title, labels, lst, start=min(val, len(lst) - 1), jumps=jumps if base else None)

    def MakeMove(self, gamer, card=None, hint=None, hint1=None, out=None):
        """Choose a card: to play, or (out=count) to discard after taking the talon."""
        n = gamer.aCards.Count()
        if n == 1 and not out:
            return gamer.aCards.At(0)
        app = self.app
        lo, hi = 0, n - 1
        if card:  # must follow suit, else trump
            for mast in (card.CMast, app.CurrentGame % 10):
                c = self.opt[corder] and gamer.aCards.MinCard(mast) or gamer.aCards.MaxCard(mast)
                if c:
                    lo = gamer.aCards.IndexOf(c)
                    hi = gamer.aCards.IndexOf(self.opt[corder] and gamer.aCards.MaxCard(mast) or gamer.aCards.MinCard(mast))
                    break
        i = getattr(self, "_last_index", lo)
        i = min(max(i, lo), hi)
        old_status = self.status
        if out is not None:
            self.discarding = True
            self.status = "Знесіть 2 (%d/2)" % out if out < 2 else lcd.OK + " - знос, ↓ - назад"
        elif gamer.nGamer != 1:
            self.status = "Хід за %s" % NAMES[gamer.nGamer]
        else:
            self.status = "Ваш хід"
        try:
            while True:
                self.select = (gamer.nGamer, i, lo, hi) if out != 2 else None
                for k in self.events():
                    if k == pygame.K_LEFT:
                        i = hi if i <= lo else i - 1
                    elif k == pygame.K_RIGHT:
                        i = lo if i >= hi else i + 1
                    elif k == pygame.K_DOWN and out:
                        return None          # take back the last discarded card
                    elif k in CONFIRM:
                        if out == 2:
                            self.discarding = False
                            return False     # discard confirmed
                        self._last_index = i
                        return gamer.aCards.At(i)
                self.frame()
        finally:
            self.select = None
            self.status = old_status

    # ---------------------------------------------------------------- drawing
    def text(self, s, pos, color=WHITE, font=None, center=False, right=False):
        img = (font or self.f9).render(str(s), True, color)
        x, y = pos
        if center:
            x -= img.get_width() // 2
        elif right:
            x -= img.get_width()
        self.screen.blit(img, (x, y))
        return img.get_width()

    def draw_card(self, x, y, card, small=True, border=None, dim=False):
        w, h = (12, 19) if small else (16, 23)
        rect = pygame.Rect(x, y, w, h)
        pygame.draw.rect(self.screen, (215, 215, 215) if dim else WHITE, rect, border_radius=2)
        color = (150, 150, 150) if dim else (CARD_RED if card.CMast in (3, 4) else BLACK)
        fr, fs = (self.rank_small, self.f9) if small else (self.f10b, self.f12b)
        label = fr.render(RANK_CH[card.CName], True, color)
        self.screen.blit(label, (x + (w - label.get_width()) // 2, y - 1))
        suit = fs.render(SUIT_CH[card.CMast], True, color)
        self.screen.blit(suit, (x + (w - suit.get_width()) // 2, y + h - suit.get_height()))
        if border:
            pygame.draw.rect(self.screen, border, rect, 1, border_radius=2)

    def draw_back(self, x, y):
        rect = pygame.Rect(x, y, 10, 14)
        pygame.draw.rect(self.screen, (40, 70, 170), rect, border_radius=2)
        pygame.draw.rect(self.screen, LIGHT, rect, 1, border_radius=2)

    def draw_open_hand(self, g, right):
        """A computer hand face up, as 4 short lines: suit + ranks."""
        cards = g.aCards.items
        sel = self.select if self.select and self.select[0] == g.nGamer else None
        for row, mast in enumerate((1, 3, 2, 4)):
            y = 30 + row * 9
            in_suit = [c for c in cards if c.CMast == mast]
            color = CARD_RED if mast in (3, 4) else WHITE
            parts = [(SUIT_CH[mast], None)] + [(RANK_CH[c.CName], c) for c in in_suit]
            width = sum(self.f8.size(p)[0] + 1 for p, _ in parts)
            x = 126 - width if right else 2
            for label, c in parts:
                w = self.f8.size(label)[0]
                if c is not None and sel and cards.index(c) == sel[1]:
                    pygame.draw.rect(self.screen, YELLOW, (x - 1, y, w + 2, 10))
                    self.text(label, (x, y), BLACK, self.f8)
                else:
                    dim = sel and c is not None and not (sel[2] <= cards.index(c) <= sel[3])
                    self.text(label, (x, y), GREY if dim else color, self.f8)
                x += w + 1

    def draw_players(self):
        app = self.app
        for n, x, right in ((2, 2, False), (3, 126, True)):
            g = app.Gamer(n)
            mover = app.nCurrentMove.nValue == n and self.desk.get(n) is None and app.CurrentGame != undefined
            self.text(NAMES[n], (x, 1), YELLOW if mover else WHITE, self.f9, right=right)
            self.text(self.labels.get(n, ""), (x, 11), YELLOW, self.f9, right=right)
            if g.nGetsCard:
                self.text("взят %d" % g.nGetsCard, (x, 21), LIGHT, self.f8, right=right)
            if n in self.open_hands:
                self.draw_open_hand(g, right)
            else:
                for i in range(min(g.aCards.Count(), 10)):
                    self.draw_back(x + i * 3 if not right else x - 10 - i * 3, 32)

    def draw_table(self):
        app = self.app
        self.screen.fill(GREEN)
        self.draw_players()
        cg = app.CurrentGame
        if cg not in (None, undefined):
            if cg == raspas:
                top = "розпаси"
            else:
                dec = [n for n in (1, 2, 3) if app.Gamer(n).GamesType == cg]
                top = "%s %s" % (game_name(cg), NAMES[dec[0]][:5] if dec else "")
            self.text(top, (64, 1), GREY, self.f8, center=True)
        me = app.Gamer(1)
        if self.labels.get(1):
            self.text(self.labels[1], (64, 11), YELLOW, self.f9, center=True)
        if me.nGetsCard:
            self.text("взят %d" % me.nGetsCard, (64, 21), LIGHT, self.f8, center=True)
        # trick / talon row
        spots = {2: 30, 1: 56, 3: 82}
        if self.desk:
            for n, c in self.desk.items():
                if c is not None:
                    self.draw_card(spots[n], 68, c, small=False)
        else:
            cnt, c1, c2 = self.prikup
            shown = [c for c in (c1, c2) if c] or (me.aOut.items if self.discarding else [])
            for i, c in enumerate(shown):
                self.draw_card(46 + i * 20, 68, c, small=False)
            for i in range(cnt - len(shown)):
                pygame.draw.rect(self.screen, (40, 70, 170), (46 + i * 20, 68, 16, 23), border_radius=2)
        if self.status:
            self.text(self.status, (64, 92), YELLOW, self.f9, center=True)
        self.draw_hand(me)
        if self.prompt:
            title, label = self.prompt
            rect = pygame.Rect(16, 40, 96, 38)
            pygame.draw.rect(self.screen, BLACK, rect, border_radius=3)
            pygame.draw.rect(self.screen, YELLOW, rect, 1, border_radius=3)
            self.text(title, (64, 43), LIGHT, self.f9, center=True)
            self.text("<", (21, 58), GREY, self.f12b)
            self.text(">", (99, 58), GREY, self.f12b)
            self.text(label, (64, 57), YELLOW, self.f12b, center=True)

    def draw_hand(self, me):
        cards = me.aCards.items
        n = len(cards)
        if not n:
            return
        step = min(12, (126 - 12) // max(1, n - 1)) if n > 1 else 12
        x0 = (128 - (step * (n - 1) + 12)) // 2
        sel = self.select if self.select and self.select[0] == 1 else None
        for i, c in enumerate(cards):
            raised = sel and i == sel[1]
            dim = sel and not (sel[2] <= i <= sel[3])
            self.draw_card(x0 + i * step, 106 - (4 if raised else 0), c,
                           border=YELLOW if raised else None, dim=dim)

    def draw_sheet(self):
        self.screen.fill(GREEN)
        app = self.app
        self.text("%s до %d" % (RULE_NAMES[self.opt[scorerules]], app.nBulletScore), (64, 2), YELLOW, self.f10b, center=True)
        for x, label in ((54, "пуля"), (80, "гора"), (126, "вісти")):
            self.text(label, (x, 17), GREY, self.f8, right=True)
        for row, n in enumerate((1, 2, 3)):
            s = app.Gamer(n).aScore
            y = 30 + row * 15
            self.text(NAMES[n], (2, y), WHITE, self.f10)
            self.text(s.nGetBull(), (54, y), YELLOW, self.f10b, right=True)
            self.text(s.nGetMount(), (80, y), RED if s.nGetMount() else LIGHT, self.f10b, right=True)
            self.text("%+d" % s.Vists, (126, y), WHITE, self.f10, right=True)
        self.text("вісти - баланс, як при закритті", (64, 78), GREY, self.f8, center=True)
        done = lcd.OK + " - далі" if self.paper_mode else "будь-яка кнопка - назад"
        self.text(done, (64, 112), LIGHT, self.f8, center=True)

    def draw(self):
        if self.app is None:
            return
        if self.show_sheet:
            self.draw_sheet()
        else:
            self.draw_table()
        lcd.flip()


# ---------------------------------------------------------------- saving the pulka between deals

def save_pulka(app):
    if app.EndOfGame():
        delete_save()
        return
    data = {"rules": "leningrad" if TPlScore.rule == Peter else "sochi",
            "bullet": app.nBulletScore, "start": app.nCurrentStart.nValue, "rcnt": TPlScore.rcnt,
            "scores": [[app.Gamer(i).aScore.Bullet.items, app.Gamer(i).aScore.Mountan.items,
                        app.Gamer(i).aScore.LeftVists.items, app.Gamer(i).aScore.RightVists.items]
                       for i in (1, 2, 3)]}
    try:
        with open(SAVE_FILE, "w") as f:
            json.dump(data, f)
    except OSError:
        pass


def saved_rules():
    try:
        with open(SAVE_FILE) as f:
            return Peter if json.load(f).get("rules") == "leningrad" else Sochi
    except (OSError, ValueError):
        return None


def load_pulka(app):
    with open(SAVE_FILE) as f:
        data = json.load(f)
    app.nBulletScore = data["bullet"]
    app.nCurrentStart.nValue = data["start"]
    TPlScore.rcnt = data.get("rcnt", 0)
    for i, (b, m, lv, rv) in zip((1, 2, 3), data["scores"]):
        s = app.Gamer(i).aScore
        s.Bullet.Set(b)
        s.Mountan.Set(m)
        s.LeftVists.Set(lv)
        s.RightVists.Set(rv)
    app.CloseBullet()


def delete_save():
    try:
        os.remove(SAVE_FILE)
    except OSError:
        pass


# ---------------------------------------------------------------- start / end screens

def start_screen(gui):
    """Returns (resume, rules). The rules row toggles Сочинка / Ленінградка for a new pulka."""
    saved = saved_rules()
    rows = (["resume"] if saved is not None else []) + ["rules", "new"]
    i = 0
    rules = 0  # index into RULES: Сочинка by default
    while True:
        for k in gui.events():
            if k == pygame.K_UP:
                i = (i - 1) % len(rows)
            elif k == pygame.K_DOWN:
                i = (i + 1) % len(rows)
            elif rows[i] == "rules" and (k in (pygame.K_LEFT, pygame.K_RIGHT) or k in CONFIRM):
                rules = (rules + 1) % len(RULES)
            elif k in CONFIRM:
                if rows[i] == "resume":
                    return True, saved
                return False, RULES[rules][1]
        s = gui.screen
        s.fill(GREEN)
        gui.text("ПРЕФЕРАНС", (64, 10), YELLOW, gui.f14b, center=True)
        gui.text("пулька до %d" % BULLET, (64, 30), LIGHT, gui.f9, center=True)
        for r, row in enumerate(rows):
            y = 48 + r * 19
            sel = r == i
            if sel:
                pygame.draw.rect(s, YELLOW, (8, y - 2, 112, 16), border_radius=4)
            color = BLACK if sel else WHITE
            if row == "resume":
                gui.text("ПРОДОВЖИТИ", (64, y), color, gui.f10b, center=True)
            elif row == "new":
                gui.text("НОВА ПУЛЬКА", (64, y), color, gui.f10b, center=True)
            else:
                gui.text(RULES[rules][0], (64, y), color, gui.f10b, center=True)
                gui.text("<", (12, y - 1), color if sel else GREY, gui.f10b)
                gui.text(">", (110, y - 1), color if sel else GREY, gui.f10b)
        gui.text("PyPref engine (GPL)", (64, 104), GREY, gui.f8, center=True)
        gui.text("kpref / OpenPref AI", (64, 114), GREY, gui.f8, center=True)
        lcd.flip()
        gui.clock.tick(20)


def final_screen(gui):
    app = gui.app
    res = sorted((app.Gamer(n).aScore.Vists, n) for n in (1, 2, 3))[::-1]
    lcd.play("win" if res[0][1] == 1 else "lose")
    while True:
        if any(k in CONFIRM for k in gui.events()):
            return
        s = gui.screen
        s.fill(GREEN)
        gui.text("ПУЛЬКУ ЗАКРИТО", (64, 10), YELLOW, gui.f10b, center=True)
        for r, (v, n) in enumerate(res):
            y = 36 + r * 16
            gui.text(NAMES[n], (12, y), WHITE, gui.f10)
            gui.text("%+d" % v, (116, y), YELLOW if v > 0 else LIGHT, gui.f10b, right=True)
        gui.text(lcd.OK + " - нова пулька", (64, 104), LIGHT, gui.f8, center=True)
        lcd.flip()
        gui.clock.tick(20)


def main():
    gui = PrefGUI()
    try:
        while True:
            resume, rules = start_screen(gui)
            gui.set_rules(rules)
            app = TDeskTop(gui)
            gui.app = app
            app.nBulletScore = BULLET
            TPlScore.rcnt = 0
            if resume:
                load_pulka(app)
                app.RunGame(run, loaded=True)
            else:
                delete_save()
                app.RunGame(run)
            if app.EndOfGame():
                delete_save()
                final_screen(gui)
    except Quit:
        pass
    gui.screen.fill(BLACK)
    lcd.flip()
    lcd.quit()


if __name__ == "__main__":
    main()
