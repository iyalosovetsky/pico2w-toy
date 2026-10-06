"""Chess against Stockfish for the Waveshare 1.44" LCD HAT.

Joystick - move the cursor, PRESS / KEY1 - pick up / put down a piece,
KEY2 - game menu (undo, new game), KEY3 - exit (the game is saved).
Keyboard: arrows, Enter / Space, 2 - game menu, Esc - exit.
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "vendor"))  # python-chess lives here

import chess  # noqa: E402
import chess.engine  # noqa: E402
import pygame  # noqa: E402
import lcd  # noqa: E402

STOCKFISH = "/usr/games/stockfish"
SAVE_FILE = os.path.join(HERE, "chess_save.json")
FONT_FILE = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
LEVELS = [  # (Stockfish skill level, seconds per move)
    (0, 0.1), (2, 0.15), (4, 0.2), (6, 0.3), (9, 0.4), (12, 0.6), (16, 0.8), (20, 1.0),
]
SQ = 16  # square size in pixels; the board fills the whole screen

LIGHT, DARK = (238, 216, 180), (170, 120, 80)
CURSOR, SELECT, LAST = (255, 230, 0), (60, 200, 90), (205, 210, 90)
CHECK = (230, 60, 50)
WHITE, BLACK, GREY, YELLOW = (255, 255, 255), (0, 0, 0), (150, 150, 150), (255, 210, 0)
GLYPHS = {chess.KING: "♚", chess.QUEEN: "♛", chess.ROOK: "♜",
          chess.BISHOP: "♝", chess.KNIGHT: "♞", chess.PAWN: "♟"}

screen = lcd.init()
font = pygame.font.Font(None, 15)
font_big = pygame.font.Font(None, 22)
clock = pygame.time.Clock()


def make_piece_images():
    """Filled chess glyphs with a contrasting outline, one per piece and colour."""
    glyph_font = pygame.font.Font(FONT_FILE, 15)
    images = {}
    for piece_type, ch in GLYPHS.items():
        for color in (chess.WHITE, chess.BLACK):
            fill, edge = ((250, 250, 250), (20, 20, 20)) if color else ((15, 15, 15), (235, 235, 235))
            base = glyph_font.render(ch, True, fill)
            outline = glyph_font.render(ch, True, edge)
            img = lcd.Surface((base.get_width() + 2, base.get_height() + 2), pygame.SRCALPHA)
            for dx, dy in ((0, 1), (2, 1), (1, 0), (1, 2)):
                img.blit(outline, (dx, dy))
            img.blit(base, (1, 1))
            images[(piece_type, color)] = img
    return images


PIECES = make_piece_images()


class Game:
    def __init__(self):
        self.engine = None
        self.player = chess.WHITE
        self.level = 3  # index into LEVELS (shown as 1..8)
        self.board = chess.Board()
        self.state = "setup"  # setup, play, promote, menu, over
        self.setup_row = 0
        self.menu_row = 0
        self.cursor = (4, 6)  # screen column, row
        self.selected = None
        self.promo_move = None
        self.promo_idx = 0
        self.has_save = os.path.exists(SAVE_FILE)

    # ---- persistence
    def save(self):
        if self.board.is_game_over(claim_draw=True):
            self.delete_save()
            return
        data = {"moves": [m.uci() for m in self.board.move_stack],
                "player": "white" if self.player else "black", "level": self.level}
        try:
            with open(SAVE_FILE, "w") as f:
                json.dump(data, f)
        except OSError:
            pass

    def delete_save(self):
        try:
            os.remove(SAVE_FILE)
        except OSError:
            pass
        self.has_save = False

    def load(self):
        with open(SAVE_FILE) as f:
            data = json.load(f)
        self.player = chess.WHITE if data["player"] == "white" else chess.BLACK
        self.level = data["level"]
        self.board = chess.Board()
        for uci in data["moves"]:
            self.board.push_uci(uci)

    # ---- coordinates (board is drawn from the player's side)
    def square_at(self, col, row):
        if self.player == chess.WHITE:
            return chess.square(col, 7 - row)
        return chess.square(7 - col, row)

    def screen_pos(self, sq):
        f, r = chess.square_file(sq), chess.square_rank(sq)
        return (f, 7 - r) if self.player == chess.WHITE else (7 - f, r)

    # ---- flow
    def start(self, resume=False):
        if resume:
            self.load()
        else:
            self.board = chess.Board()
            self.delete_save()
        if self.engine is None:
            self.engine = chess.engine.SimpleEngine.popen_uci(STOCKFISH)
            self.engine.configure({"Threads": 1, "Hash": 16})
        self.engine.configure({"Skill Level": LEVELS[self.level][0]})
        self.selected = None
        self.cursor = (4, 6)
        self.state = "play"
        self.check_over()
        self.save()

    def check_over(self):
        if self.board.is_game_over(claim_draw=True):
            self.state = "over"
            self.delete_save()
            winner = self.board.outcome(claim_draw=True).winner
            lcd.play("click" if winner is None else "win" if winner == self.player else "lose")

    def push(self, move):
        """Make a move with a sound: capture, check or a plain move."""
        capture = self.board.is_capture(move)
        self.board.push(move)
        lcd.play("check" if self.board.is_check() else "hit" if capture else "move")

    def ai_turn(self):
        """Let Stockfish move if it is its turn (blocks for up to a second)."""
        if self.state != "play" or self.board.turn == self.player:
            return
        draw(self, thinking=True)
        result = self.engine.play(self.board, chess.engine.Limit(time=LEVELS[self.level][1]))
        self.push(result.move)
        self.check_over()
        self.save()

    def press(self):
        sq = self.square_at(*self.cursor)
        piece = self.board.piece_at(sq)
        if self.board.turn != self.player:
            return
        if self.selected is not None:
            moves = [m for m in self.board.legal_moves if m.from_square == self.selected and m.to_square == sq]
            if moves:
                if len(moves) > 1:  # promotion: let the player choose the piece
                    self.promo_move = moves[0]
                    self.promo_idx = 0
                    self.state = "promote"
                else:
                    self.make_move(moves[0])
                return
            if sq == self.selected:
                self.selected = None
                return
        if piece and piece.color == self.player and any(m.from_square == sq for m in self.board.legal_moves):
            self.selected = sq

    def make_move(self, move):
        self.push(move)
        self.selected = None
        self.check_over()
        self.save()

    def undo(self):
        """Take back the last move pair so it is the player's turn again."""
        if len(self.board.move_stack) < 1:
            return
        self.board.pop()
        if self.board.turn != self.player and self.board.move_stack:
            self.board.pop()
        self.selected = None
        self.state = "play"
        self.save()

    def result_text(self):
        outcome = self.board.outcome(claim_draw=True)
        if outcome is None:
            return "GAME OVER", ""
        if outcome.winner is None:
            reason = {chess.Termination.STALEMATE: "stalemate",
                      chess.Termination.INSUFFICIENT_MATERIAL: "no material",
                      chess.Termination.THREEFOLD_REPETITION: "repetition",
                      chess.Termination.FIFTY_MOVES: "50 moves"}.get(outcome.termination, "")
            return "DRAW", reason
        return ("YOU WIN!" if outcome.winner == self.player else "AI WINS"), "checkmate"

    def quit(self):
        if self.engine:
            self.engine.quit()


# ---------------------------------------------------------------- drawing

def banner(lines, title_color=YELLOW, top=34):
    h = 18 + 13 * (len(lines) - 1)
    box = pygame.Rect(6, top, 116, h + 10)
    pygame.draw.rect(screen, BLACK, box)
    pygame.draw.rect(screen, title_color, box, 1)
    for i, (text, color, selected) in enumerate(lines):
        f = font_big if i == 0 else font
        y = top + 5 if i == 0 else top + 10 + 13 * i
        if selected:
            pygame.draw.rect(screen, YELLOW, (10, y - 1, 108, 12), border_radius=3)
            color = BLACK
        img = f.render(text, True, color)
        screen.blit(img, ((128 - img.get_width()) // 2, y))


def draw_board(g, thinking=False):
    b = g.board
    last = b.peek() if b.move_stack else None
    king_in_check = b.king(b.turn) if b.is_check() else None
    legal_targets = {m.to_square for m in b.legal_moves if m.from_square == g.selected} if g.selected is not None else set()
    for row in range(8):
        for col in range(8):
            sq = g.square_at(col, row)
            rect = pygame.Rect(col * SQ, row * SQ, SQ, SQ)
            color = LIGHT if (col + row) % 2 == 0 else DARK
            if last and sq in (last.from_square, last.to_square):
                color = LAST
            if sq == king_in_check:
                color = CHECK
            pygame.draw.rect(screen, color, rect)
            if sq == g.selected:
                pygame.draw.rect(screen, SELECT, rect)
            piece = b.piece_at(sq)
            if piece:
                img = PIECES[(piece.piece_type, piece.color)]
                screen.blit(img, (rect.centerx - img.get_width() // 2, rect.centery - img.get_height() // 2 + 1))
            if sq in legal_targets:
                if piece:
                    pygame.draw.rect(screen, SELECT, rect, 2)
                else:
                    pygame.draw.circle(screen, SELECT, rect.center, 3)
    if g.state == "play" and not thinking:
        col, row = g.cursor
        pygame.draw.rect(screen, CURSOR, (col * SQ, row * SQ, SQ, SQ), 2)
    if thinking:
        pygame.draw.rect(screen, BLACK, (44, 58, 40, 12))
        img = font.render("AI...", True, YELLOW)
        screen.blit(img, (64 - img.get_width() // 2, 59))


def draw(g, thinking=False):
    if g.state == "setup":
        screen.fill((25, 25, 35))
        title = font_big.render("CHESS", True, YELLOW)
        screen.blit(title, ((128 - title.get_width()) // 2, 6))
        rows = setup_rows(g)
        for i, label in enumerate(rows):
            y = 32 + i * 18
            if i == g.setup_row:
                pygame.draw.rect(screen, YELLOW, (6, y - 3, 116, 16), border_radius=4)
            img = font.render(label, True, BLACK if i == g.setup_row else WHITE)
            screen.blit(img, ((128 - img.get_width()) // 2, y))
        hint = font.render("<  >  change", True, GREY)
        screen.blit(hint, ((128 - hint.get_width()) // 2, 114))
        lcd.flip()
        return
    draw_board(g, thinking)
    if g.state == "promote":
        pygame.draw.rect(screen, BLACK, (20, 50, 88, 28))
        pygame.draw.rect(screen, YELLOW, (20, 50, 88, 28), 1)
        for i, pt in enumerate(PROMO_PIECES):
            rect = pygame.Rect(24 + i * 20, 54, 20, 20)
            pygame.draw.rect(screen, YELLOW if i == g.promo_idx else LIGHT, rect)
            img = PIECES[(pt, g.player)]
            screen.blit(img, (rect.centerx - img.get_width() // 2, rect.centery - img.get_height() // 2 + 1))
    elif g.state == "menu":
        banner([("MENU", YELLOW, False)] +
               [(label, WHITE, i == g.menu_row) for i, label in enumerate(GAME_MENU)])
    elif g.state == "over":
        title, reason = g.result_text()
        banner([(title, YELLOW, False), (reason, WHITE, False), (lcd.OK + ": new game", GREY, False)])
    lcd.flip()


PROMO_PIECES = [chess.QUEEN, chess.ROOK, chess.BISHOP, chess.KNIGHT]
GAME_MENU = ["RESUME", "UNDO MOVE", "NEW GAME"]


def setup_rows(g):
    rows = []
    if g.has_save:
        rows.append("CONTINUE")
    rows += ["COLOR: " + ("WHITE" if g.player else "BLACK"),
             "LEVEL: %d / %d" % (g.level + 1, len(LEVELS)),
             "NEW GAME"]
    return rows


# ---------------------------------------------------------------- main loop

def handle_setup(g, k):
    rows = setup_rows(g)
    label = rows[g.setup_row]
    if k == pygame.K_UP:
        g.setup_row = (g.setup_row - 1) % len(rows)
    elif k == pygame.K_DOWN:
        g.setup_row = (g.setup_row + 1) % len(rows)
    elif k in (pygame.K_LEFT, pygame.K_RIGHT):
        step = 1 if k == pygame.K_RIGHT else -1
        if label.startswith("COLOR"):
            g.player = not g.player
        elif label.startswith("LEVEL"):
            g.level = (g.level + step) % len(LEVELS)
    elif k in CONFIRM:
        if label == "CONTINUE":
            g.start(resume=True)
        elif label == "NEW GAME":
            g.start()
        elif label.startswith("COLOR"):
            g.player = not g.player
        elif label.startswith("LEVEL"):
            g.level = (g.level + 1) % len(LEVELS)


CONFIRM = (pygame.K_RETURN, pygame.K_1, pygame.K_SPACE)
game = Game()
running = True
while running:
    for ev in pygame.event.get():
        if ev.type == pygame.QUIT:  # SIGTERM from systemctl stop
            running = False
        elif ev.type == pygame.KEYDOWN:
            k = ev.key
            if k in (pygame.K_3, pygame.K_ESCAPE):
                running = False
            elif game.state == "setup":
                handle_setup(game, k)
            elif game.state == "play":
                col, row = game.cursor
                if k == pygame.K_LEFT:
                    game.cursor = ((col - 1) % 8, row)
                elif k == pygame.K_RIGHT:
                    game.cursor = ((col + 1) % 8, row)
                elif k == pygame.K_UP:
                    game.cursor = (col, (row - 1) % 8)
                elif k == pygame.K_DOWN:
                    game.cursor = (col, (row + 1) % 8)
                elif k in CONFIRM:
                    game.press()
                elif k == pygame.K_2:
                    game.state, game.menu_row = "menu", 0
            elif game.state == "promote":
                if k == pygame.K_LEFT:
                    game.promo_idx = (game.promo_idx - 1) % 4
                elif k == pygame.K_RIGHT:
                    game.promo_idx = (game.promo_idx + 1) % 4
                elif k in CONFIRM:
                    move = chess.Move(game.promo_move.from_square, game.promo_move.to_square,
                                      promotion=PROMO_PIECES[game.promo_idx])
                    game.state = "play"
                    game.make_move(move)
                elif k == pygame.K_2:
                    game.state = "play"
            elif game.state == "menu":
                if k == pygame.K_UP:
                    game.menu_row = (game.menu_row - 1) % len(GAME_MENU)
                elif k == pygame.K_DOWN:
                    game.menu_row = (game.menu_row + 1) % len(GAME_MENU)
                elif k == pygame.K_2:
                    game.state = "play"
                elif k in CONFIRM:
                    choice = GAME_MENU[game.menu_row]
                    if choice == "RESUME":
                        game.state = "play"
                    elif choice == "UNDO MOVE":
                        game.undo()
                    else:
                        game.save()
                        game.has_save = os.path.exists(SAVE_FILE)
                        game.state, game.setup_row = "setup", 0
            elif game.state == "over" and k in CONFIRM:
                game.state, game.setup_row = "setup", 0
    game.ai_turn()
    draw(game)
    clock.tick(20)

game.quit()
screen.fill(BLACK)
lcd.flip()
lcd.quit()
