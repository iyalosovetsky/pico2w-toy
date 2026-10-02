"""Texas Hold'em, heads-up against the computer, for the Waveshare 1.44" LCD HAT.

Joystick LEFT/RIGHT - choose action, UP/DOWN - raise amount,
PRESS / KEY1 - confirm, KEY2 - all-in amount, KEY3 - exit.
Keyboard: arrows, Enter / Space - confirm, 2 - all-in amount, Esc - exit.
"""
import random

import pygame
import lcd

START_CHIPS = 1000
BLINDS = [(10, 20), (20, 40), (30, 60), (50, 100), (100, 200), (200, 400), (500, 1000)]
HANDS_PER_LEVEL = 10
SIMS = 400          # Monte Carlo rollouts for the AI's hand strength
AI_DELAY = 900      # ms before the AI acts, so its moves can be followed

HAND_NAMES = ["HIGH CARD", "PAIR", "TWO PAIR", "TRIPS", "STRAIGHT",
              "FLUSH", "FULL HOUSE", "QUADS", "STR FLUSH"]
RANK_LABEL = {10: "10", 11: "J", 12: "Q", 13: "K", 14: "A"}
DECK = [(r, s) for r in range(2, 15) for s in range(4)]  # suits: 0 spade, 1 heart, 2 diamond, 3 club

BG = (0, 70, 35)
WHITE, GREY, YELLOW, RED, GREEN = (255, 255, 255), (170, 190, 175), (255, 210, 0), (210, 20, 30), (120, 255, 140)
BLACK = (0, 0, 0)

screen = lcd.init()
font = pygame.font.Font(None, 14)
font_card = pygame.font.Font(None, 17)
font_big = pygame.font.Font(None, 20)
clock = pygame.time.Clock()


# ---------------------------------------------------------------- hand evaluation

def straight_high(ranks):
    if 14 in ranks:
        ranks = ranks | {1}  # A-2-3-4-5
    run = 0
    for r in range(14, 0, -1):
        if r in ranks:
            run += 1
            if run == 5:
                return r + 4
        else:
            run = 0
    return 0


def evaluate(cards):
    """Value of the best 5-card hand among up to 7 cards, as a comparable tuple."""
    by_suit = {}
    for r, s in cards:
        by_suit.setdefault(s, []).append(r)
    flush = None
    for ranks in by_suit.values():
        if len(ranks) >= 5:
            sf = straight_high(set(ranks))
            if sf:
                return (8, sf)
            flush = (5, *sorted(ranks, reverse=True)[:5])
    counts = {}
    for r, _ in cards:
        counts[r] = counts.get(r, 0) + 1
    groups = sorted(counts.items(), key=lambda rc: (rc[1], rc[0]), reverse=True)
    top, top_n = groups[0]
    if top_n == 4:
        return (7, top, max((r for r in counts if r != top), default=0))
    if top_n == 3 and len(groups) > 1 and groups[1][1] >= 2:
        return (6, top, groups[1][0])
    if flush:
        return flush
    st = straight_high(set(counts))
    if st:
        return (4, st)
    others = sorted((r for r in counts if r != top), reverse=True)
    if top_n == 3:
        return (3, top, *others[:2])
    if top_n == 2 and len(groups) > 1 and groups[1][1] == 2:
        second = groups[1][0]
        return (2, top, second, max((r for r in counts if r not in (top, second)), default=0))
    if top_n == 2:
        return (1, top, *others[:3])
    return (0, *sorted(counts, reverse=True)[:5])


def equity(hole, board, sims=SIMS):
    """Chance to win against a random hand (ties count half)."""
    deck = [c for c in DECK if c not in hole and c not in board]
    need = 5 - len(board)
    score = 0.0
    for _ in range(sims):
        draw = random.sample(deck, 2 + need)
        full = board + draw[2:]
        a, b = evaluate(hole + full), evaluate(draw[:2] + full)
        score += 1 if a > b else 0.5 if a == b else 0
    return score / sims


# ---------------------------------------------------------------- game logic

class Player:
    def __init__(self, name):
        self.name = name
        self.stack = START_CHIPS
        self.reset()

    def reset(self):
        self.hole = []
        self.bet = 0        # chips put in on the current street
        self.folded = False
        self.acted = False
        self.last = ""      # last action, shown on screen

    def put(self, amount):
        amount = min(amount, self.stack)
        self.stack -= amount
        self.bet += amount
        return amount


class Table:
    def __init__(self):
        self.you, self.ai = Player("YOU"), Player("AI")
        self.players = [self.you, self.ai]
        self.button = random.randrange(2)
        self.hand_no = 0
        self.new_hand()

    def other(self, p):
        return self.ai if p is self.you else self.you

    @property
    def blinds(self):
        return BLINDS[min(self.hand_no // HANDS_PER_LEVEL, len(BLINDS) - 1)]

    def new_hand(self):
        self.hand_no += 1
        self.button ^= 1
        self.deck = DECK[:]
        random.shuffle(self.deck)
        self.board = []
        self.pot = 0
        self.result = []
        for p in self.players:
            p.reset()
            p.hole = [self.deck.pop(), self.deck.pop()]
        sb, bb = self.blinds
        dealer = self.players[self.button]  # heads-up: dealer posts the small blind
        big = self.other(dealer)
        dealer.put(sb)
        big.put(bb)
        dealer.last, big.last = "SB %d" % dealer.bet, "BB %d" % big.bet
        self.current_bet = max(dealer.bet, big.bet)
        self.min_raise = bb
        self.street = 0
        self.turn = dealer
        self.after_action()

    # ---- betting helpers
    def to_call(self, p):
        return max(0, self.current_bet - p.bet)

    def max_raise_to(self, p):
        o = self.other(p)
        return min(p.stack + p.bet, o.stack + o.bet)  # no one can bet more than the other can cover

    def can_raise(self, p):
        o = self.other(p)
        return o.stack > 0 and self.max_raise_to(p) > self.current_bet

    def min_raise_to(self, p):
        return min(self.current_bet + self.min_raise, self.max_raise_to(p))

    # ---- actions
    def act(self, p, action, amount=0):
        o = self.other(p)
        if action == "fold":
            p.folded = True
            p.last = "FOLD"
        elif action == "call":
            need = self.to_call(p)
            p.put(need)
            p.last = "CALL %d" % need if need else "CHECK"
            if p.stack == 0 and need:
                p.last = "ALL-IN"
        else:  # raise to `amount`
            amount = max(self.min_raise_to(p), min(amount, self.max_raise_to(p)))
            self.min_raise = max(self.min_raise, amount - self.current_bet)
            p.put(amount - p.bet)
            p.last = ("BET %d" if self.current_bet == 0 else "RAISE %d") % amount
            if p.stack == 0:
                p.last = "ALL-IN"
            self.current_bet = amount
            o.acted = False
        p.acted = True
        self.turn = o
        self.after_action()

    def street_done(self):
        if any(p.folded for p in self.players):
            return True
        for p in self.players:
            o = self.other(p)
            if p.stack == 0:
                continue
            if p.bet < o.bet:
                return False
            if not p.acted and o.stack > 0:
                return False
        return True

    def after_action(self):
        if not self.street_done():
            self.mode = "you" if self.turn is self.you else "ai"
            if self.mode == "ai":
                self.ai_time = pygame.time.get_ticks() + AI_DELAY
            return
        self.collect()
        folded = [p for p in self.players if p.folded]
        if folded:
            winner = self.other(folded[0])
            self.result = ["%s WIN%s %d" % (winner.name, "" if winner is self.you else "S", self.pot),
                           "%s FOLD%s" % (folded[0].name, "" if folded[0] is self.you else "S")]
            winner.stack += self.pot
            self.pot = 0
            self.mode = "result"
            return
        if self.street == 3 or any(p.stack == 0 for p in self.players):
            while len(self.board) < 5:  # all-in: run out the board
                self.board.append(self.deck.pop())
            self.showdown()
            return
        self.street += 1
        self.board += [self.deck.pop() for _ in range(3 if self.street == 1 else 1)]
        for p in self.players:
            p.acted = False
            p.last = ""
        self.current_bet = 0
        self.min_raise = self.blinds[1]
        self.turn = self.other(self.players[self.button])  # big blind acts first after the flop
        self.after_action()

    def collect(self):
        a, b = self.players
        if a.bet != b.bet:  # return the part of a bet that could not be called
            hi, lo = (a, b) if a.bet > b.bet else (b, a)
            if lo.stack == 0 or lo.folded:
                excess = hi.bet - lo.bet if not lo.folded else 0
                hi.stack += excess
                hi.bet -= excess
        for p in self.players:
            self.pot += p.bet
            p.bet = 0

    def showdown(self):
        vy, va = evaluate(self.you.hole + self.board), evaluate(self.ai.hole + self.board)
        names = "%s / %s" % (HAND_NAMES[vy[0]], HAND_NAMES[va[0]])
        if vy > va:
            self.you.stack += self.pot
            self.result = ["YOU WIN %d" % self.pot, names]
        elif va > vy:
            self.ai.stack += self.pot
            self.result = ["AI WINS %d" % self.pot, names]
        else:
            half = self.pot // 2
            self.you.stack += self.pot - half
            self.ai.stack += half
            self.result = ["SPLIT POT", names]
        self.pot = 0
        self.mode = "result"

    def next_hand(self):
        if self.you.stack == 0 or self.ai.stack == 0:
            self.mode = "over"
        else:
            self.new_hand()

    # ---- computer player
    def ai_act(self):
        p, o = self.ai, self.you
        need = self.to_call(p)
        pot = self.pot + p.bet + o.bet
        eq = equity(p.hole, self.board) + random.uniform(-0.05, 0.05)
        odds = need / (pot + need) if need else 0
        r = random.random()
        if self.can_raise(p) and (eq > 0.8 or (eq > 0.65 and r < 0.6) or (need == 0 and r < 0.08)
                                  or (r < 0.03 and eq > 0.3)):  # value bets plus the odd bluff
            size = pot * (1.0 if eq > 0.8 else 0.6)
            self.act(p, "raise", self.current_bet + max(self.min_raise, int(size)))
        elif need == 0:
            self.act(p, "call")
        elif eq >= odds + 0.05 or (need <= self.blinds[1] and eq > 0.35):
            self.act(p, "call")
        else:
            self.act(p, "fold")


# ---------------------------------------------------------------- drawing

def draw_suit(s, cx, cy, color):
    if s == 0:    # spade
        pygame.draw.polygon(screen, color, [(cx, cy - 5), (cx - 5, cy + 1), (cx + 5, cy + 1)])
        pygame.draw.circle(screen, color, (cx - 3, cy + 1), 3)
        pygame.draw.circle(screen, color, (cx + 3, cy + 1), 3)
        pygame.draw.polygon(screen, color, [(cx, cy + 1), (cx - 2, cy + 5), (cx + 2, cy + 5)])
    elif s == 1:  # heart
        pygame.draw.circle(screen, color, (cx - 3, cy - 2), 3)
        pygame.draw.circle(screen, color, (cx + 3, cy - 2), 3)
        pygame.draw.polygon(screen, color, [(cx - 6, cy - 1), (cx + 6, cy - 1), (cx, cy + 5)])
    elif s == 2:  # diamond
        pygame.draw.polygon(screen, color, [(cx, cy - 6), (cx + 4, cy), (cx, cy + 6), (cx - 4, cy)])
    else:         # club
        for dx, dy in ((0, -3), (-3, 1), (3, 1)):
            pygame.draw.circle(screen, color, (cx + dx, cy + dy), 3)
        pygame.draw.polygon(screen, color, [(cx, cy), (cx - 2, cy + 5), (cx + 2, cy + 5)])


def draw_card(x, y, card, hidden=False):
    rect = pygame.Rect(x, y, 22, 28)
    if hidden:
        pygame.draw.rect(screen, (30, 60, 170), rect, border_radius=3)
        pygame.draw.rect(screen, WHITE, rect.inflate(-4, -4), 1, border_radius=2)
        return
    pygame.draw.rect(screen, WHITE, rect, border_radius=3)
    r, s = card
    color = RED if s in (1, 2) else BLACK
    screen.blit(font_card.render(RANK_LABEL.get(r, str(r)), True, color), (x + 2, y + 1))
    draw_suit(s, x + 13, y + 19, color)


def text(s, pos, color=WHITE, f=font, center=False):
    img = f.render(s, True, color)
    x, y = pos
    if center:
        x -= img.get_width() // 2
    screen.blit(img, (x, y))


def player_options(t):
    p = t.you
    need = t.to_call(p)
    opts = []
    if need:
        opts.append(("fold", "FOLD"))
    opts.append(("call", "CALL %d" % min(need, p.stack) if need else "CHECK"))
    if t.can_raise(p):
        opts.append(("raise", None))
    return opts


def draw(t, sel, raise_to):
    screen.fill(BG)
    you, ai = t.you, t.ai
    reveal = t.mode in ("result", "over") and not any(p.folded for p in t.players)
    dealer = t.players[t.button]

    # AI area
    text("AI %d%s" % (ai.stack, " (D)" if dealer is ai else ""), (2, 1))
    text(ai.last, (126 - font.size(ai.last)[0], 1), YELLOW)
    draw_card(2, 12, ai.hole[0], hidden=not reveal)
    draw_card(26, 12, ai.hole[1], hidden=not reveal)
    if ai.bet:
        text("bet %d" % ai.bet, (52, 22), YELLOW)
    if reveal:
        text(HAND_NAMES[evaluate(ai.hole + t.board)[0]], (52, 32), GREY)
    sb, bb = t.blinds
    text("%d/%d" % (sb, bb), (126 - font.size("%d/%d" % (sb, bb))[0], 12), GREY)

    # board
    for i in range(5):
        x = 2 + i * 25
        if i < len(t.board):
            draw_card(x, 44, t.board[i])
        else:
            pygame.draw.rect(screen, (0, 95, 50), (x, 44, 22, 28), 1, border_radius=3)
    text("POT %d" % (t.pot + you.bet + ai.bet), (64, 74), WHITE, center=True)

    # your area
    draw_card(2, 86, you.hole[0])
    draw_card(26, 86, you.hole[1])
    text("YOU %d%s" % (you.stack, " (D)" if dealer is you else ""), (52, 86))
    text(HAND_NAMES[evaluate(you.hole + t.board)[0]], (52, 96), GREEN)
    if you.bet:
        text("bet %d" % you.bet, (52, 106), YELLOW)

    # bottom bar
    bar = pygame.Rect(0, 115, 128, 13)
    if t.mode == "you":
        opts = player_options(t)
        w = 128 // len(opts)
        for i, (kind, label) in enumerate(opts):
            if kind == "raise":
                allin = raise_to >= t.max_raise_to(you)
                label = "ALL-IN" if allin else ("RAISE %d" if t.current_bet else "BET %d") % raise_to
            box = pygame.Rect(i * w + 1, 115, w - 2, 13)
            selected = i == sel
            pygame.draw.rect(screen, YELLOW if selected else (0, 45, 22), box, border_radius=3)
            text(label, (box.centerx, 116), BLACK if selected else WHITE, center=True)
    elif t.mode == "ai":
        text("AI is thinking...", (64, 116), GREY, center=True)
    elif t.mode == "result":
        pygame.draw.rect(screen, BLACK, (0, 74, 128, 11))
        text(t.result[0], (64, 74), YELLOW, center=True)
        pygame.draw.rect(screen, BLACK, bar)
        text(t.result[1] if len(t.result) > 1 else "", (64, 116), WHITE, center=True)
    elif t.mode == "over":
        box = pygame.Rect(8, 40, 112, 40)
        pygame.draw.rect(screen, BLACK, box)
        pygame.draw.rect(screen, YELLOW, box, 1)
        text("YOU WIN!" if you.stack else "AI WINS", (64, 45), YELLOW, font_big, center=True)
        text("PRESS: new game", (64, 64), WHITE, center=True)
    lcd.flip()


# ---------------------------------------------------------------- main loop

table = Table()
sel = 1
raise_to = 0
running = True


def reset_choice():
    global sel, raise_to
    opts = player_options(table)
    sel = [k for k, _ in opts].index("call")  # default: check / call
    raise_to = table.min_raise_to(table.you)


reset_choice()
while running:
    for ev in pygame.event.get():
        if ev.type == pygame.QUIT:  # SIGTERM from systemctl stop
            running = False
        elif ev.type == pygame.KEYDOWN:
            k = ev.key
            confirm = k in (pygame.K_RETURN, pygame.K_1, pygame.K_SPACE)
            if k in (pygame.K_3, pygame.K_ESCAPE):
                running = False
            elif table.mode == "result" and confirm:
                table.next_hand()
                reset_choice()
            elif table.mode == "over" and confirm:
                table = Table()
                reset_choice()
            elif table.mode == "you":
                opts = player_options(table)
                you = table.you
                step = table.blinds[1]
                if k == pygame.K_LEFT:
                    sel = (sel - 1) % len(opts)
                elif k == pygame.K_RIGHT:
                    sel = (sel + 1) % len(opts)
                elif k in (pygame.K_UP, pygame.K_DOWN, pygame.K_2) and opts[-1][0] == "raise":
                    if k == pygame.K_2:
                        raise_to = table.max_raise_to(you)
                    else:
                        raise_to += step if k == pygame.K_UP else -step
                    raise_to = max(table.min_raise_to(you), min(raise_to, table.max_raise_to(you)))
                    sel = len(opts) - 1
                elif confirm:
                    kind = opts[min(sel, len(opts) - 1)][0]
                    table.act(you, kind, raise_to)
                    reset_choice()
    if table.mode == "ai" and pygame.time.get_ticks() >= table.ai_time:
        table.ai_act()
        if table.mode == "you":
            reset_choice()
    draw(table, sel, raise_to)
    clock.tick(20)

screen.fill(BLACK)
lcd.flip()
lcd.quit()
