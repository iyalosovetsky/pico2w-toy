"""Book reader (EPUB / FB2 / TXT, also zipped, and PDF) for the LCD - library in ~/books.

Library: UP/DOWN choose, PRESS / Enter open, KEY3 / Esc exit.
Reading: RIGHT / DOWN / PRESS / Space / PgDn - next page, LEFT / UP / PgUp - previous,
KEY2 / 2 / Tab - menu (contents, font size, theme, library), KEY3 / Esc - library,
+ / - font size, Home / End chapter start / end (keyboard). The position in every book is saved
(~/.config/lcdtoy/reader.json) as a place in the text, so it survives font changes.

PDF (rendered by poppler's pdftoppm, white margins cropped) - fragments: UP / DOWN page,
LEFT / RIGHT the zoomed fragments of the page (up to 3 x 3, in reading order), + / - zoom
(KEY1 / KEY2 on the HAT), PRESS / Enter / Space - scroll the fragment smoothly with the arrows,
KEY3 / Esc - back to the fragments, then to the library. Page, zoom, fragment and the scroll
position are saved too.
"""
import io
import math
import json
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import pygame  # noqa: E402
import lcd  # noqa: E402
import books  # noqa: E402
import pdfdoc  # noqa: E402

BOOKS_DIR = os.path.expanduser(os.environ.get("LCD_BOOKS", "~/books"))
STATE_FILE = os.path.expanduser("~/.config/lcdtoy/reader.json")
FONT_DIR = "/usr/share/fonts/truetype/dejavu/"
SERIF, SERIF_BOLD, SANS = (FONT_DIR + n for n in ("DejaVuSerif.ttf", "DejaVuSerif-Bold.ttf", "DejaVuSans.ttf"))
# text sizes in native pixels: what is readable differs a lot between 128 and 320 px
SIZES = [13, 15, 17, 19, 22, 26] if lcd.S > 1 else [7, 8, 9, 10, 11, 12]
DEFAULT_SIZE = 2 if lcd.S > 1 else 2
THEMES = {
    "light": {"bg": (246, 240, 224), "fg": (25, 22, 18), "dim": (120, 110, 95), "accent": (150, 70, 20)},
    "dark": {"bg": (0, 0, 0), "fg": (215, 212, 200), "dim": (110, 110, 105), "accent": (230, 170, 40)},
}
M = 3                           # page margin (logical px)
NEXT = (pygame.K_RIGHT, pygame.K_DOWN, pygame.K_RETURN, pygame.K_SPACE, pygame.K_PAGEDOWN, pygame.K_1)
PREV = (pygame.K_LEFT, pygame.K_UP, pygame.K_PAGEUP, pygame.K_BACKSPACE)
MENU = (pygame.K_2, pygame.K_TAB)
BACK = (pygame.K_3, pygame.K_ESCAPE)
OK = (pygame.K_RETURN, pygame.K_SPACE, pygame.K_1, pygame.K_RIGHT)

screen = lcd.init()
clock = pygame.time.Clock()


def font(path, px):
    """A font px native pixels high (lcd scales logical sizes by lcd.S)."""
    size = px / lcd.S if lcd.S != 1 else int(px)
    try:
        return pygame.font.Font(path, size)
    except (FileNotFoundError, OSError):
        return pygame.font.Font(None, size * 1.3 if lcd.S != 1 else int(px * 1.3))


UI_PX = 14 if lcd.S > 1 else 8
ui = font(SANS, UI_PX)
ui_bold = font(SANS.replace("Sans.ttf", "Sans-Bold.ttf"), UI_PX + (2 if lcd.S > 1 else 1))


# ---------------------------------------------------------------- state

def load_state():
    try:
        with open(STATE_FILE) as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def save_state(state):
    try:
        os.makedirs(os.path.dirname(STATE_FILE), exist_ok=True)
        tmp = STATE_FILE + ".tmp"
        with open(tmp, "w") as f:
            json.dump(state, f, ensure_ascii=False)
        os.replace(tmp, STATE_FILE)
    except OSError:
        pass


state = load_state()
state.setdefault("books", {})
state.setdefault("size", DEFAULT_SIZE)
state.setdefault("theme", "light")


def theme():
    return THEMES.get(state["theme"], THEMES["light"])


# ---------------------------------------------------------------- drawing helpers

def text(s, pos, color, f=None, center=False, right=False):
    f = f or ui
    img = f.render(s, True, color)
    x, y = pos
    if center:
        x -= img.get_width() / 2
    elif right:
        x -= img.get_width()
    screen.blit(img, (x, y))
    return img.get_width()


def fit(s, f, width):
    """Shorten s with an ellipsis so it fits width (logical px)."""
    if f.size(s)[0] <= width:
        return s
    while s and f.size(s + "…")[0] > width:
        s = s[:-1]
    return s + "…"


def message(title, *lines):
    t = theme()
    screen.fill(t["bg"])
    text(title, (64, 40), t["accent"], ui_bold, center=True)
    for i, line in enumerate(lines):
        text(fit(line, ui, 120), (64, 58 + i * (ui.get_height() + 2)), t["fg"], center=True)
    lcd.flip()


# ---------------------------------------------------------------- hyphenation

VOWELS = set("аеєиіїоуюяыэёАЕЄИІЇОУЮЯЫЭЁaeiouyAEIOUY")
NO_LINE_START = set("ьъйЬЪЙ'’ʼ")
APOSTROPHES = set("'’ʼ")


def hyphen_points(word):
    """Simple syllable breaks (word[:p] | word[p:]), rightmost first: at least two
    letters and a vowel on each side, never before ь / й / an apostrophe; between a
    vowel and consonant+vowel, between two consonants, between two vowels, or after
    a hyphen already in the word."""
    pts = []
    letters = [c.isalpha() or c in APOSTROPHES for c in word]
    for p in range(1, len(word)):
        a, b = word[p - 1], word[p]
        if a == "-":
            if sum(letters[:p]) >= 2 and sum(letters[p:]) >= 2:
                pts.append(p)
            continue
        if not (letters[p - 1] and letters[p]) or b in NO_LINE_START or a in APOSTROPHES:
            continue
        left, right = word[:p], word[p:]
        if sum(c.isalpha() for c in left) < 2 or sum(c.isalpha() for c in right) < 2:
            continue  # never leave or carry a single letter
        if not any(c in VOWELS for c in left) or not any(c in VOWELS for c in right):
            continue
        c = word[p + 1] if p + 1 < len(word) else ""
        va, vb, vc = a in VOWELS, b in VOWELS, c in VOWELS
        if (va and not vb and vc) or (not va and not vb) or (va and vb):
            pts.append(p)
    return pts[::-1]


def hyphenate(word, fits):
    """Longest syllable prefix of word that fits(prefix + "-"): (chars, shown) or None."""
    for p in hyphen_points(word):
        shown = word[:p] if word[p - 1] == "-" else word[:p] + "-"
        if fits(shown):
            return p, shown
    return None


# ---------------------------------------------------------------- page layout

class Layout:
    """Lines of one chapter for the current font, split into pages.

    A line is (kind, data, height, pos): kind "t" text line (data = (str, x, font)),
    "i" image (data = (key, w, h)), "g" gap. pos = (block, char offset) it starts at.
    """

    def __init__(self, book, ci, px, images):
        self.book, self.ci = book, ci
        self.body = font(SERIF, px)
        self.head = font(SERIF_BOLD, px + max(1, px // 6))
        self.width = 128 - 2 * M
        self.page_h = 128 - M - status_height() - 1
        self.images = images
        self.lines = []
        self._build()
        self._paginate()

    def _wrap(self, s, f, width, indent):
        """Greedy word wrap with syllable hyphenation -> [(line, char offset)]."""
        out, line, start, off = [], "", 0, 0
        for word in s.split(" "):
            w_off, rest = off, word
            while rest:
                avail = width - (indent if not out else 0)
                cand = rest if not line else line + " " + rest
                if f.size(cand)[0] <= avail:
                    if not line:
                        start = w_off
                    line, rest = cand, ""
                    continue
                prefix = line + " " if line else ""
                cut = hyphenate(rest, lambda part: f.size(prefix + part)[0] <= avail)
                if cut:  # part of the word + "-" fits at the end of this line
                    k, shown = cut
                    out.append((prefix + shown, start if line else w_off))
                    line, rest, w_off = "", rest[k:], w_off + k
                elif line:  # move the whole word to the next line
                    out.append((line, start))
                    line = ""
                else:  # no syllable break fits: cut the over-long word anywhere
                    k = len(rest)
                    while k > 1 and f.size(rest[:k])[0] > avail:
                        k -= 1
                    out.append((rest[:k], w_off))
                    rest, w_off = rest[k:], w_off + k
            off += len(word) + 1
        if line:
            out.append((line, start))
        return out

    def _build(self):
        lh = self.body.get_linesize()
        add = self.lines.append
        for bi, (kind, val) in enumerate(self.book.chapters[self.ci].blocks):
            if kind == "p":
                indent = self.body.size("  ")[0] * 1.5
                for i, (s, off) in enumerate(self._wrap(val, self.body, self.width, indent)):
                    add(("t", (s, M + (indent if i == 0 else 0), self.body), lh, (bi, off)))
                add(("g", None, lh * 0.25, (bi, len(val))))
            elif kind == "h":
                if self.lines:
                    add(("g", None, lh * 0.6, (bi, 0)))
                hl = self.head.get_linesize()
                for s, off in self._wrap(val, self.head, self.width, 0):
                    x = M + (self.width - self.head.size(s)[0]) / 2
                    add(("t", (s, x, self.head), hl, (bi, off)))
                add(("g", None, lh * 0.5, (bi, len(val))))
            elif kind == "sep":
                add(("g", None, lh, (bi, 0)))
            elif kind == "img":
                size = self.images.size(self.book, val, self.width, self.page_h)
                if size:
                    add(("i", (val, size[0], size[1]), size[1] + 2, (bi, 0)))
                else:
                    add(("t", ("[зображення]", M, self.body), lh, (bi, 0)))

    def _paginate(self):
        self.pages = []
        y, start = None, 0
        for i, (kind, _, h, _) in enumerate(self.lines):
            if y is None:
                if kind == "g":
                    continue  # no gaps at the top of a page
                start, y = i, 0
            if y + h > self.page_h and i > start:
                self.pages.append(start)
                if kind == "g":
                    y = None
                    continue
                start, y = i, 0
            y += h
        if y is not None:
            self.pages.append(start)
        if not self.pages:
            self.pages = [0]

    def page_lines(self, pi):
        start = self.pages[pi]
        end = self.pages[pi + 1] if pi + 1 < len(self.pages) else len(self.lines)
        return self.lines[start:end]

    def page_pos(self, pi):
        if not self.lines:
            return (0, 0)
        return self.lines[self.pages[pi]][3]

    def page_of(self, pos):
        best = 0
        for pi, li in enumerate(self.pages):
            if self.lines[li][3] <= tuple(pos):
                best = pi
            else:
                break
        return best


def status_height():
    return ui.get_height() + 2


class Images:
    """Decodes book images on demand, scaled to the page; keeps a few in memory."""

    def __init__(self):
        self.sizes = {}    # (key, w, h box) -> (w, h) logical, or None if undecodable
        self.cache = {}    # (key, w, h) -> native surface
        self.order = []

    def _load(self, book, key):
        got = book.image_bytes(key)
        if not got:
            return None
        data, hint = got
        try:
            import io
            img = pygame.image.load(io.BytesIO(data), hint)
        except (pygame.error, ValueError):
            return None
        if img.get_bitsize() not in (24, 32):
            conv = pygame.Surface(img.get_size(), 0, 32)
            conv.blit(img, (0, 0))
            img = conv
        return img

    def size(self, book, key, box_w, box_h):
        k = (key, box_w, box_h)
        if k not in self.sizes:
            img = self._load(book, key)
            if img is None:
                self.sizes[k] = None
            else:
                w, h = img.get_width() / lcd.S, img.get_height() / lcd.S  # 1 image px = 1 screen px
                scale = min(box_w / w, (box_h - 2) / h, 2.0)
                self.sizes[k] = (max(1.0, w * scale), max(1.0, h * scale))
                self._store(key, self.sizes[k], img)
        return self.sizes[k]

    def _store(self, key, size, img):
        nw, nh = max(1, round(size[0] * lcd.S)), max(1, round(size[1] * lcd.S))
        surf = pygame.transform.smoothscale(img, (nw, nh))
        self.cache[(key, size)] = surf
        self.order.append((key, size))
        while len(self.order) > 6:
            self.cache.pop(self.order.pop(0), None)

    def surface(self, book, key, size):
        if (key, size) not in self.cache:
            img = self._load(book, key)
            if img is None:
                return None
            self._store(key, size, img)
        return self.cache[(key, size)]


# ---------------------------------------------------------------- reading a book

class Reader:
    def __init__(self, path):
        self.path = path
        self.book = books.load(path)
        self.images = Images()
        self.layouts = {}
        info = state["books"].setdefault(path, {})
        info["title"] = self.book.title
        info["author"] = self.book.author
        pos = info.get("pos", [0, 0, 0])
        self.ci = min(max(0, pos[0]), len(self.book.chapters) - 1)
        self.pi = self.layout(self.ci).page_of(pos[1:])
        self.done_before = [0]  # chars before each chapter, for the percentage
        for c in self.book.chapters:
            self.done_before.append(self.done_before[-1] + c.chars)

    def layout(self, ci):
        px = SIZES[state["size"]]
        key = (ci, px)
        if key not in self.layouts:
            if len(self.layouts) > 4:
                self.layouts.clear()
            self.layouts[key] = Layout(self.book, ci, px, self.images)
        return self.layouts[key]

    def position(self):
        b, off = self.layout(self.ci).page_pos(self.pi)
        return [self.ci, b, off]

    def percent(self):
        ci, b, off = self.position()
        blocks = self.book.chapters[ci].blocks
        done = self.done_before[ci] + sum(len(t) for k, t in blocks[:b] if k in ("p", "h")) + off
        return min(100, int(100 * done / max(1, self.book.total_chars)))

    def save(self):
        info = state["books"][self.path]
        info["pos"] = self.position()
        info["pct"] = self.percent()
        info["time"] = time.time()
        state["last"] = self.path
        save_state(state)

    def next_page(self):
        lay = self.layout(self.ci)
        if self.pi + 1 < len(lay.pages):
            self.pi += 1
        elif self.ci + 1 < len(self.book.chapters):
            self.ci, self.pi = self.ci + 1, 0
        else:
            return False
        return True

    def prev_page(self):
        if self.pi > 0:
            self.pi -= 1
        elif self.ci > 0:
            self.ci -= 1
            self.pi = len(self.layout(self.ci).pages) - 1
        else:
            return False
        return True

    def goto_chapter(self, ci):
        self.ci, self.pi = ci, 0

    def change_font(self, delta):
        pos = self.position()
        state["size"] = min(max(0, state["size"] + delta), len(SIZES) - 1)
        self.ci = pos[0]
        self.pi = self.layout(self.ci).page_of(pos[1:])

    def draw(self):
        t = theme()
        screen.fill(t["bg"])
        lay = self.layout(self.ci)
        y = M
        for kind, data, h, _ in lay.page_lines(self.pi):
            if kind == "t":
                s, x, f = data
                screen.blit(f.render(s, True, t["fg"]), (x, y))
            elif kind == "i":
                key, w, ih = data
                surf = self.images.surface(self.book, key, (w, ih))
                if surf is not None:
                    screen.blit(surf, (M + (lay.width - w) / 2, y + 1))
            y += h
        # status line: chapter title, page in chapter, percentage
        sy = 128 - status_height()
        pygame.draw.line(screen, t["dim"], (M, sy - 1), (125, sy - 1))
        right = "%d/%d  %d%%" % (self.pi + 1, len(lay.pages), self.percent())
        rw = ui.size(right)[0]
        text(fit(self.book.chapters[self.ci].title, ui, 128 - 2 * M - rw - 4), (M, sy), t["dim"])
        text(right, (125, sy), t["dim"], right=True)
        lcd.flip()


# ---------------------------------------------------------------- PDF

NW, NH = lcd.NATIVE_W, lcd.NATIVE_H  # screen in native pixels
# zoom levels: 0 = the whole page, else the page content is that many screens wide
ZOOMS = [0, 1, 1.5, 2, 2.5, 3, 4] if lcd.S > 1 else [0, 1, 1.5, 2, 3, 4, 6, 8]
DEFAULT_ZOOM = 3 if lcd.S > 1 else 5      # 2x / 4x: A4 text about readable
PLUS = (pygame.K_EQUALS, pygame.K_PLUS, pygame.K_KP_PLUS, pygame.K_1)
MINUS = (pygame.K_MINUS, pygame.K_KP_MINUS, pygame.K_2)
PAN_KEYS = {pygame.K_LEFT: (-1, 0), pygame.K_RIGHT: (1, 0), pygame.K_UP: (0, -1), pygame.K_DOWN: (0, 1)}
PDF_BG = (60, 60, 60)


def _axis(isz, ssz):
    """Fragment offsets along one axis: enough to cover the page, at most 3."""
    if isz <= ssz:
        return [(isz - ssz) // 2]  # smaller than the screen: centred
    n = min(3, math.ceil(isz / ssz - 0.05))
    if n == 1:
        return [(isz - ssz) // 2]
    return [round(i * (isz - ssz) / (n - 1)) for i in range(n)]


def _clamp(v, isz, ssz):
    return (isz - ssz) // 2 if isz <= ssz else int(min(max(0, v), isz - ssz))


class PdfView:
    def __init__(self, path):
        self.path = path
        self.doc = pdfdoc.PdfDoc(path)
        info = state["books"].setdefault(path, {})
        info["title"] = self.doc.title or os.path.basename(path).rsplit(".", 1)[0]
        info["author"] = self.doc.author
        v = info.get("pdf", {})
        self.page = min(max(1, v.get("page", 1)), self.doc.pages)
        self.zi = min(max(0, v.get("zoom", DEFAULT_ZOOM)), len(ZOOMS) - 1)
        self.frag = v.get("frag", 0)
        self.pan = v.get("mode") == "pan"
        self.img, self.key = None, None
        self.vx = self.vy = 0
        self.load()
        if self.pan:
            cx, cy = v.get("center", (0.5, 0.0))
            self.center_on(cx, cy)
        self.status_until = time.time() + 2

    # --- rendering
    def width(self):
        z = ZOOMS[self.zi]
        if z == 0:
            return max(16, int(min(NW, NH / self.doc.content_aspect(self.page))))
        return int(NW * z)

    def load(self):
        w = self.width()
        if (self.page, w) != self.key:
            if self.img is not None and not self.doc.cached(self.page, w):
                self.draw(busy=True)
            data = self.doc.render(self.page, w)
            self.img = pygame.image.load(io.BytesIO(data), "page.ppm")
            self.key = (self.page, w)
        if ZOOMS[self.zi] and self.page < self.doc.pages:
            self.doc.prefetch(self.page + 1, w)
        xs, ys = self.grid()
        if self.frag < 0:
            self.frag = len(xs) * len(ys) - 1
        self.frag = min(self.frag, len(xs) * len(ys) - 1)

    def grid(self):
        iw, ih = self.img.get_size()
        return _axis(iw, NW), _axis(ih, NH)

    def view(self):
        """Top-left of the screen in page pixels (negative: the page is centred)."""
        if self.pan:
            return self.vx, self.vy
        xs, ys = self.grid()
        f = min(max(0, self.frag), len(xs) * len(ys) - 1)
        return xs[f % len(xs)], ys[f // len(xs)]

    def center(self):
        vx, vy = self.view()
        iw, ih = self.img.get_size()
        return (vx + NW / 2) / iw, (vy + NH / 2) / ih

    def center_on(self, cx, cy):
        """Show the point (page fractions) in the middle: scroll there, or pick the nearest fragment."""
        iw, ih = self.img.get_size()
        px, py = cx * iw - NW / 2, cy * ih - NH / 2
        if self.pan:
            self.vx, self.vy = _clamp(px, iw, NW), _clamp(py, ih, NH)
        else:
            xs, ys = self.grid()
            col = min(range(len(xs)), key=lambda i: abs(xs[i] - px))
            row = min(range(len(ys)), key=lambda i: abs(ys[i] - py))
            self.frag = row * len(xs) + col

    # --- actions
    def goto(self, page, frag=0):
        if not 1 <= page <= self.doc.pages or page == self.page:
            return False
        self.page, self.frag = page, frag
        self.load()
        if self.pan:  # scrolling: the top of the new page
            iw, ih = self.img.get_size()
            self.vx, self.vy = _clamp(self.vx, iw, NW), _clamp(0, ih, NH)
        return True

    def step(self, d):
        """Next / previous fragment, over to the next / previous page."""
        xs, ys = self.grid()
        f = self.frag + d
        if 0 <= f < len(xs) * len(ys):
            self.frag = f
            return True
        return self.goto(self.page + d, 0 if d > 0 else -1)

    def zoom(self, d):
        zi = min(max(0, self.zi + d), len(ZOOMS) - 1)
        if zi == self.zi:
            return False
        c = self.center()
        self.zi = zi
        self.load()
        self.center_on(*c)
        return True

    def start_pan(self):
        self.vx, self.vy = self.view()
        iw, ih = self.img.get_size()
        self.vx, self.vy = _clamp(self.vx, iw, NW), _clamp(self.vy, ih, NH)
        self.pan = True

    def stop_pan(self):
        c = self.center()
        self.pan = False
        self.center_on(*c)

    def scroll(self, dx, dy):
        iw, ih = self.img.get_size()
        vx, vy = _clamp(self.vx + dx, iw, NW), _clamp(self.vy + dy, ih, NH)
        moved = (vx, vy) != (self.vx, self.vy)
        self.vx, self.vy = vx, vy
        return moved

    def save(self):
        info = state["books"][self.path]
        info["pdf"] = {"page": self.page, "zoom": self.zi, "frag": self.frag,
                       "mode": "pan" if self.pan else "frag", "center": list(self.center())}
        info["pct"] = int(100 * self.page / self.doc.pages)
        info["time"] = time.time()
        state["last"] = self.path
        save_state(state)

    # --- drawing
    def draw(self, busy=False):
        t = theme()
        screen.fill(PDF_BG)
        vx, vy = self.view()
        area = pygame.Rect(max(0, vx), max(0, vy), NW, NH)
        screen.blit(self.img, (max(0, -vx) / lcd.S, max(0, -vy) / lcd.S), area)
        if self.pan:
            pygame.draw.rect(screen, t["accent"], (0, 0, 128, 128), 1)
        if busy or time.time() < self.status_until:
            sh = status_height()
            sy = 128 - sh
            pygame.draw.rect(screen, t["bg"], (0, sy - 1, 128, sh + 1))
            z = ZOOMS[self.zi]
            zs = "сторінка" if z == 0 else ("%g×" % z)
            left = "%d/%d  %s" % (self.page, self.doc.pages, "…" if busy else zs)
            text(left, (M, sy), t["fg"])
            # the page in miniature with the part on the screen
            iw, ih = self.img.get_size()
            ph = sh - 2
            pw = max(3, ph * iw / ih)
            px, py = 125 - pw, sy + 1
            pygame.draw.rect(screen, t["dim"], (px, py, pw, ph), 1)
            fx, fy = max(0, vx) / iw, max(0, vy) / ih
            fw, fh = min(1, NW / iw), min(1, NH / ih)
            pygame.draw.rect(screen, t["accent"], (px + fx * pw, py + fy * ph, max(1, fw * pw), max(1, fh * ph)))
        lcd.flip()


def read_pdf(path):
    message("Відкриваю…", os.path.basename(path))
    try:
        v = PdfView(path)
    except FileNotFoundError:
        message("Немає pdftoppm", "sudo apt install poppler-utils")
        wait_key()
        return
    except Exception as e:  # broken file
        message("Не вдалося відкрити", os.path.basename(path), str(e)[:60])
        wait_key()
        return
    held = {}  # arrow -> time pressed (smooth scrolling)
    dirty, changed, last_save = True, False, time.time()
    status_shown = True
    while True:
        for ev in pygame.event.get():
            if ev.type == pygame.QUIT:
                v.save()
                raise SystemExit
            if ev.type == pygame.KEYUP:
                held.pop(ev.key, None)
                continue
            if ev.type != pygame.KEYDOWN:
                continue
            k = ev.key
            acted = True
            if k in BACK:
                if v.pan:
                    v.stop_pan()
                    held.clear()
                else:
                    v.save()
                    return
            elif k in PLUS:
                acted = v.zoom(+1)
            elif k in MINUS:
                acted = v.zoom(-1)
            elif k == pygame.K_PAGEDOWN:
                acted = v.goto(v.page + 1)
            elif k == pygame.K_PAGEUP:
                acted = v.goto(v.page - 1)
            elif k == pygame.K_HOME:
                acted = v.goto(1)
            elif k == pygame.K_END:
                acted = v.goto(v.doc.pages)
            elif v.pan:
                if k in PAN_KEYS:
                    held[k] = time.time()
                acted = False
            elif k in (pygame.K_RETURN, pygame.K_SPACE):
                v.start_pan()
            elif k == pygame.K_DOWN:
                acted = v.goto(v.page + 1)
            elif k == pygame.K_UP:
                acted = v.goto(v.page - 1)
            elif k == pygame.K_RIGHT:
                acted = v.step(+1)
            elif k == pygame.K_LEFT:
                acted = v.step(-1)
            else:
                acted = False
            if acted:
                dirty = changed = True
                v.status_until = time.time() + 1.5
        ms = clock.tick(30)
        if v.pan and held:
            now = time.time()
            dx = dy = 0.0
            for k, since in held.items():
                speed = NW * 0.7 * (1 + 2 * min(1.0, now - since))  # native px / s, speeding up
                dx += PAN_KEYS[k][0] * speed * ms / 1000
                dy += PAN_KEYS[k][1] * speed * ms / 1000
            if v.scroll(round(dx), round(dy)):
                dirty = changed = True
        shown = time.time() < v.status_until
        if shown != status_shown:
            dirty, status_shown = True, shown
        if dirty:
            v.draw()
            dirty = False
            if changed and time.time() - last_save > 5:
                v.save()
                changed, last_save = False, time.time()


def choose(title, items, sel=0, sub=None):
    """Scrolling list; returns the chosen index or None (KEY3 / Esc / 2)."""
    t = theme()
    row_h = ui.get_linesize() * (2.1 if sub else 1.25)
    head = ui_bold.get_linesize() + 4
    visible = max(1, int((128 - head - 2) // row_h))
    top = 0
    while True:
        for ev in pygame.event.get():
            if ev.type == pygame.QUIT:
                raise SystemExit
            if ev.type != pygame.KEYDOWN:
                continue
            if ev.key == pygame.K_UP:
                sel = (sel - 1) % len(items)
            elif ev.key == pygame.K_DOWN:
                sel = (sel + 1) % len(items)
            elif ev.key in (pygame.K_PAGEUP, pygame.K_LEFT):
                sel = max(0, sel - visible)
            elif ev.key in (pygame.K_PAGEDOWN,):
                sel = min(len(items) - 1, sel + visible)
            elif ev.key in (pygame.K_RETURN, pygame.K_SPACE, pygame.K_1, pygame.K_RIGHT):
                return sel
            elif ev.key in BACK + MENU:
                return None
        top = min(max(top, sel - visible + 1), sel)
        screen.fill(t["bg"])
        text(fit(title, ui_bold, 122), (64, 2), t["accent"], ui_bold, center=True)
        pygame.draw.line(screen, t["dim"], (M, head - 2), (125, head - 2))
        for i in range(top, min(top + visible, len(items))):
            y = head + (i - top) * row_h
            if i == sel:
                pygame.draw.rect(screen, t["accent"], (1, y - 1, 126, row_h), border_radius=3)
            color = t["bg"] if i == sel else t["fg"]
            text(fit(items[i], ui, 122), (M, y), color)
            if sub and sub[i]:
                text(fit(sub[i], ui, 122), (M, y + ui.get_linesize()), t["bg"] if i == sel else t["dim"])
        if top > 0:
            pygame.draw.polygon(screen, t["dim"], [(122, head + 2), (126, head + 6), (118, head + 6)])
        if top + visible < len(items):
            pygame.draw.polygon(screen, t["dim"], [(122, 127), (126, 123), (118, 123)])
        lcd.flip()
        clock.tick(20)


def read(path):
    if path.lower().endswith(".pdf"):
        return read_pdf(path)
    message("Відкриваю…", os.path.basename(path))
    try:
        r = Reader(path)
    except Exception as e:  # broken or unsupported file
        message("Не вдалося відкрити", os.path.basename(path), str(e)[:60])
        wait_key()
        return
    dirty, last_save = True, time.time()
    while True:
        for ev in pygame.event.get():
            if ev.type == pygame.QUIT:
                r.save()
                raise SystemExit
            if ev.type != pygame.KEYDOWN:
                continue
            k = ev.key
            if k in BACK:
                r.save()
                return
            if k in NEXT:
                dirty |= r.next_page()
            elif k in PREV:
                dirty |= r.prev_page()
            elif k == pygame.K_EQUALS:
                r.change_font(+1)
                dirty = True
            elif k == pygame.K_MINUS:
                r.change_font(-1)
                dirty = True
            elif k == pygame.K_HOME:   # start / end of the chapter
                r.pi, dirty = 0, True
            elif k == pygame.K_END:
                r.pi, dirty = len(r.layout(r.ci).pages) - 1, True
            elif k in MENU:
                if not book_menu(r):
                    r.save()
                    return
                dirty = True
        if dirty:
            r.draw()
            dirty = False
            if time.time() - last_save > 5:  # don't write the SD card on every page
                r.save()
                last_save = time.time()
        clock.tick(30)


def book_menu(r):
    """Returns False to go back to the library."""
    while True:
        dark = state["theme"] == "dark"
        items = ["Зміст", "Шрифт більший (%d)" % SIZES[state["size"]], "Шрифт менший",
                 "Тема: " + ("темна" if dark else "світла"), "До бібліотеки"]
        sel = choose(r.book.title, items)
        if sel is None:
            return True
        if sel == 0:
            ci = choose("Зміст", [c.title for c in r.book.chapters], r.ci)
            if ci is not None:
                r.goto_chapter(ci)
                return True
        elif sel == 1:
            r.change_font(+1)
        elif sel == 2:
            r.change_font(-1)
        elif sel == 3:
            state["theme"] = "light" if dark else "dark"
        else:
            return False


def wait_key():
    while True:
        for ev in pygame.event.get():
            if ev.type == pygame.QUIT:
                raise SystemExit
            if ev.type == pygame.KEYDOWN:
                return
        clock.tick(20)


# ---------------------------------------------------------------- library

def library():
    os.makedirs(BOOKS_DIR, exist_ok=True)
    sel = 0
    while True:
        files = []
        for root, _, names in os.walk(BOOKS_DIR):
            files += [os.path.join(root, n) for n in names if books.is_book(n)]
        info = state["books"]
        files.sort(key=lambda p: (-info.get(p, {}).get("time", 0), os.path.basename(p).lower()))
        if not files:
            message("Бібліотека порожня", "Покладіть .epub .fb2 .txt .pdf", "у теку " + BOOKS_DIR.replace(os.path.expanduser("~"), "~"))
            wait_key()
            return
        titles, subs = [], []
        for p in files:
            i = info.get(p, {})
            titles.append(i.get("title") or os.path.basename(p))
            extra = ("%d%%" % i["pct"]) if "pct" in i else "нова"
            subs.append(("%s · %s" % (i["author"], extra)) if i.get("author") else extra)
        if state.get("last") in files and sel == 0:
            sel = files.index(state["last"])
        sel = min(sel, len(files) - 1)
        choice = choose("Книжки (%d)" % len(files), titles, sel, subs)
        if choice is None:
            return
        sel = 0
        read(files[choice])


try:
    library()
except SystemExit:
    pass
save_state(state)
screen.fill((0, 0, 0))
lcd.flip()
lcd.quit()
