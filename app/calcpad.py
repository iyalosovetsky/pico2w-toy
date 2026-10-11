"""Calculator: a front end for calc (apcalc, arbitrary precision) with 2D / 3D plots.

One calc session (`calc -q -p`) lives as long as the app: variables, matrices and functions
(define) stay. Every input line goes to calc as eval("..."), the answer is shown under it.
The front end adds its own commands:

  plot EXPR             a vector -> line, an N x 2 matrix -> x,y line, a matrix -> heat map
  plot EXPR(x), a, b    a function of x on [a, b] (default -10 .. 10)
  heat EXPR             a matrix as a heat map
  plot3d EXPR           a matrix as a surface z = M[i,j] (rotatable wireframe)
  plot3d EXPR(x,y), a, b   a function of x and y on [a, b] x [a, b] (default -5 .. 5)
  plot                  the last plot again;  clear - the screen;  reset - a new calc session;  help

Keys: typing + Enter - evaluate, UP / DOWN - history, LEFT / RIGHT / Home / End / Backspace /
Del - edit, PgUp / PgDn - scroll the output, Esc - clear the line / stop a long computation / exit.
In a plot: arrows move the cursor (2D) or rotate (3D), + / - zoom, Enter - filled / wireframe
(3D), Esc - back. HAT: UP / DOWN - history, KEY1 / KEY2 - next / previous example,
PRESS - evaluate, KEY3 - exit.
"""
import math
import os
import re
import select
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import pygame  # noqa: E402
import lcd  # noqa: E402

MARK = "@@END"
HISTORY_FILE = os.path.expanduser("~/.config/lcdtoy/calc-history")
HISTORY_MAX = 300
N2D = 161     # samples of a function plot
N3D = 25      # grid of a function surface
DIGITS = 16   # calc's config("display"): fits a line of the PicoCalc; config("display", 50) for more
EXAMPLES = [
    "2^100", "sqrt(2)", "pi(1e-30)", "fact(30)", "exp(1)", "sin(pi()/6)",
    "mat A[3,3] = {2,1,0, 1,3,1, 0,1,4}", "det(A)", "inverse(A)", "A * A",
    "define f(x) = x^3 - 2*x", "f(1.5)", "plot sin(x)*x, -10, 10", "plot f(x), -2, 2",
    "mat V[20]; for (i=0; i<20; i++) V[i] = i^2", "plot V", "heat A",
    "plot3d sin(x)*cos(y), -3, 3", "plot3d A", "ln(2)", "isprime(2^61-1)",
]

BG, FG, DIM = (0, 0, 0), (225, 225, 225), (110, 110, 110)
ACCENT, RED, GREEN, BLUE = (255, 200, 0), (240, 90, 80), (90, 200, 90), (110, 170, 255)
FONT_DIR = "/usr/share/fonts/truetype/dejavu/"
STOPS = [(68, 1, 84), (59, 82, 139), (33, 145, 140), (94, 201, 98), (253, 231, 37)]  # viridis


def cmap(t):
    if t != t:  # nan
        return (60, 60, 60)
    t = min(1.0, max(0.0, t)) * (len(STOPS) - 1)
    i = min(int(t), len(STOPS) - 2)
    f = t - i
    a, b = STOPS[i], STOPS[i + 1]
    return tuple(int(a[k] + (b[k] - a[k]) * f) for k in range(3))


# ---------------------------------------------------------------- the calc session

class Calc:
    """calc -q -p in a pipe; send() a statement, poll() until its output is complete."""

    def __init__(self):
        self.p = None
        self.start()

    def start(self):
        if self.p:
            self.p.kill()
            self.p.wait()
        self.p = subprocess.Popen(["calc", "-q", "-p"], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                  stderr=subprocess.STDOUT, bufsize=0)
        self.buf = b""
        self.lines = []
        self.busy = False
        self.run('config("display", %d),;' % DIGITS)

    def send(self, text):
        self.buf, self.lines, self.busy = b"", [], True
        try:
            self.p.stdin.write((text + '\n;print "%s"\n' % MARK).encode())
        except (BrokenPipeError, OSError):
            self.start()
            self.p.stdin.write((text + '\n;print "%s"\n' % MARK).encode())

    def poll(self, timeout=0.0):
        """The output lines once the statement is done, else None."""
        if not self.busy:
            return None
        end = time.monotonic() + timeout
        while True:
            left = max(0.0, end - time.monotonic())
            if not select.select([self.p.stdout], [], [], left)[0]:
                return None
            data = os.read(self.p.stdout.fileno(), 65536)
            if not data:  # calc died
                self.start()
                return ["calc завершився - нова сесія"]
            self.buf += data
            *done, self.buf = self.buf.split(b"\n")
            for raw in done:
                line = raw.decode("utf-8", "replace").rstrip("\r")
                if line == MARK:
                    self.busy = False
                    out, self.lines = self.lines, []
                    return out
                self.lines.append(line)

    def run(self, text, timeout=30.0):
        """Blocking send + poll (used for plot data)."""
        self.send(text)
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            out = self.poll(0.1)
            if out is not None:
                return out
            for ev in pygame.event.get(pygame.KEYDOWN):
                if ev.key == pygame.K_ESCAPE or (ev.hat and ev.key == pygame.K_3):
                    break
            else:
                continue
            break
        self.start()
        raise CalcError("перервано - нова сесія calc, змінні втрачено")


class CalcError(Exception):
    pass


def quote(text):
    return '"' + text.replace("\\", "\\\\").replace('"', '\\"') + '"'


def balanced(text):
    """Brackets and quotes balanced (a raw statement would swallow the end marker otherwise)."""
    depth, q = [], None
    pairs = {")": "(", "]": "[", "}": "{"}
    i = 0
    while i < len(text):
        c = text[i]
        if q:
            if c == "\\":
                i += 1
            elif c == q:
                q = None
        elif c in "\"'":
            q = c
        elif c in "([{":
            depth.append(c)
        elif c in ")]}":
            if not depth or depth.pop() != pairs[c]:
                return False
        i += 1
    return not depth and q is None


def split_args(text):
    """Split at top-level commas."""
    parts, depth, cur, q = [], 0, "", None
    for c in text:
        if q:
            q = None if c == q else q
        elif c in "\"'":
            q = c
        elif c in "([{":
            depth += 1
        elif c in ")]}":
            depth -= 1
        elif c == "," and depth == 0:
            parts.append(cur.strip())
            cur = ""
            continue
        cur += c
    parts.append(cur.strip())
    return parts


def evaluate_line(calc, line):
    """Send a user line: eval("...") (define goes raw - eval cannot define)."""
    if re.match(r"\s*define\b", line):
        if not balanced(line):
            return None
        calc.send(line)
    else:
        calc.send("eval(%s)" % quote(line))
    return True


def tidy(lines):
    """calc output -> (lines, is_error)."""
    err = any(re.match(r"\s*Error E_|.*undefined|Missing|Bad |Unterminated", l) for l in lines)
    # calc marks inexact numbers with "~", which looks like a minus in a small font
    lines = [re.sub(r"~(?=[-\d.])", "≈", l) for l in lines if l.strip() != "Error E_EVAL"]
    while lines and not lines[0].strip():
        lines.pop(0)
    while lines and not lines[-1].strip():
        lines.pop()
    return lines, err


DUMP = ('__om = config("mode", "exp"),; for (__i = 0; __i < size(__p); __i++) '
        '{__v = __p[[__i]]; if (isnum(__v)) print re(__v); else print "nan";} '
        'config("mode", __om),;')


def numbers(lines):
    vals = []
    for l in lines:
        l = l.strip().lstrip("~")
        if not l:
            continue
        try:
            vals.append(float(l.replace("~", "")))
        except ValueError:
            if l == "nan":
                vals.append(float("nan"))
            else:
                raise CalcError(l)
    return vals


def fetch_value(calc, expr):
    """A calc expression -> ("mat", dims, values) or ("num", (), [v]); CalcError if not."""
    out = calc.run('__p = eval(%s),; if (ismat(__p)) {print "MAT", matdim(__p),; '
                   'for (__d = 1; __d <= matdim(__p); __d++) print "", matmin(__p, __d), '
                   'matmax(__p, __d),; print;} else if (isnum(__p)) print "NUM"; '
                   'else print "BAD";' % quote(expr))
    head = [l for l in out if l.startswith(("MAT", "NUM", "BAD"))]
    msgs = [l for l in out if l.strip() and l not in head and l.strip() != "Error E_EVAL"]
    if not head or head[0].startswith("BAD"):
        raise CalcError(msgs[0] if msgs else "не число і не матриця")
    if head[0].startswith("NUM"):
        return "num", (), numbers(calc.run('print re(__p);'))
    f = [int(v) for v in head[0].split()[1:]]
    dims = tuple(f[2 + 2 * k] - f[1 + 2 * k] + 1 for k in range(f[0]))
    vals = numbers(calc.run(DUMP))
    if len(dims) > 2:
        raise CalcError("матриця %d-вимірна: малюю тільки 1D і 2D" % len(dims))
    return "mat", dims, vals


def fetch_function(calc, expr, args, a, b, n):
    """Values of EXPR (a function of args) on a grid over [a, b] (per argument)."""
    if not balanced(expr):
        raise CalcError("незбалансовані дужки")
    out = calc.run("define __f(%s) = (%s);" % (", ".join(args), expr))
    msgs = [l for l in out if l.strip() and "defined" not in l]
    if msgs:
        raise CalcError(msgs[0])
    lo_hi = numbers(calc.run("print re(eval(%s)); print re(eval(%s));" % (quote(a), quote(b))))
    lo, hi = lo_hi
    if len(args) == 1:
        call = "__f(__a + (__b - __a) * __k / %d)" % (n - 1)
        loop = "for (__k = 0; __k < %d; __k++) {__v = %s; " % (n, call)
    else:
        call = "__f(__a + (__b - __a) * __k / %d, __a + (__b - __a) * __j / %d)" % (n - 1, n - 1)
        loop = ("for (__j = 0; __j < %d; __j++) for (__k = 0; __k < %d; __k++) {__v = %s; "
                % (n, n, call))
    code = ('__a = %r; __b = %r; __om = config("mode", "exp"),; %s'
            'if (isnum(__v)) print re(__v); else print "nan";} config("mode", __om),;'
            % (lo, hi, loop))
    return lo, hi, numbers(calc.run(code, timeout=120))


# ---------------------------------------------------------------- screen

screen = lcd.init()
clock = pygame.time.Clock()


def font(name, px):
    size = px / lcd.S if lcd.S != 1 else int(px)
    try:
        return pygame.font.Font(FONT_DIR + name, size)
    except (FileNotFoundError, OSError):
        return pygame.font.Font(None, size)


BIG = lcd.S > 1
f_mono = font("DejaVuSansMono.ttf", 12 if BIG else 7)
f_small = font("DejaVuSans.ttf", 11 if BIG else 7)
LINE_H = f_mono.get_linesize()
CHAR_W = f_mono.size("0")[0]
COLS = max(10, int((128 - 3) / CHAR_W))


def fmt(v):
    if v != v:
        return "nan"
    if v == 0 or 1e-3 <= abs(v) < 1e5:
        return ("%.4f" % v).rstrip("0").rstrip(".")
    return "%.3g" % v


def nice_range(vals, pad=0.05):
    good = [v for v in vals if v == v and abs(v) != float("inf")]
    if not good:
        return 0.0, 1.0
    lo, hi = min(good), max(good)
    if len(good) > 40:  # poles (tan, 1/x): ignore the far 4 % on both sides
        s = sorted(good)
        k = len(s) // 25
        plo, phi = s[k], s[-1 - k]
        if phi > plo and (hi - lo) > 20 * (phi - plo):
            lo, hi = plo, phi
    if hi == lo:
        lo, hi = lo - 1, hi + 1
    pad = (hi - lo) * pad
    return lo - pad, hi + pad


class Plot2D:
    """Line plot (xs, ys) with a cursor."""

    def __init__(self, title, xs, ys):
        self.title, self.xs, self.ys = title, xs, ys
        self.i = len(xs) // 2
        self.ylo, self.yhi = nice_range(ys)
        self.xlo, self.xhi = min(xs), max(xs)
        if self.xhi == self.xlo:
            self.xhi += 1
        self.zoom = 1.0

    def key(self, k, step):
        if k == pygame.K_LEFT:
            self.i = max(0, self.i - step)
        elif k == pygame.K_RIGHT:
            self.i = min(len(self.xs) - 1, self.i + step)
        elif k in (pygame.K_EQUALS, pygame.K_KP_PLUS, pygame.K_UP):
            self.zoom = min(64.0, self.zoom * 1.5)
        elif k in (pygame.K_MINUS, pygame.K_KP_MINUS, pygame.K_DOWN):
            self.zoom = max(1.0, self.zoom / 1.5)
        else:
            return False
        return True

    def draw(self):
        screen.fill(BG)
        top, bot, left, right = 10 + LINE_H, 120, 4, 124
        # y range zoomed around the cursor value
        cy = self.ys[self.i] if self.ys[self.i] == self.ys[self.i] else (self.ylo + self.yhi) / 2
        half = (self.yhi - self.ylo) / 2 / self.zoom
        mid = (self.ylo + self.yhi) / 2 if self.zoom == 1 else min(max(cy, self.ylo + half), self.yhi - half)
        ylo, yhi = mid - half, mid + half

        def px(x):
            return left + (x - self.xlo) / (self.xhi - self.xlo) * (right - left)

        def py(y):
            return bot - (y - ylo) / (yhi - ylo) * (bot - top)
        pygame.draw.rect(screen, (40, 40, 40), (left, top, right - left, bot - top), 1)
        if ylo < 0 < yhi:
            pygame.draw.line(screen, DIM, (left, py(0)), (right, py(0)))
        if self.xlo < 0 < self.xhi:
            pygame.draw.line(screen, DIM, (px(0), top), (px(0), bot))
        seg = []
        for x, y in zip(self.xs, self.ys):
            if y == y and abs(y) != float("inf") and ylo - (yhi - ylo) < y < yhi + (yhi - ylo):
                seg.append((px(x), min(max(py(y), top - 1), bot + 1)))
            else:
                if len(seg) > 1:
                    pygame.draw.lines(screen, GREEN, False, seg)
                seg = []
        if len(seg) > 1:
            pygame.draw.lines(screen, GREEN, False, seg)
        elif len(seg) == 1:
            pygame.draw.circle(screen, GREEN, (int(seg[0][0]), int(seg[0][1])), 1)
        if len(self.xs) <= 40:
            for x, y in zip(self.xs, self.ys):
                if y == y and ylo <= y <= yhi:
                    pygame.draw.circle(screen, GREEN, (int(px(x)), int(py(y))), 1)
        cx = px(self.xs[self.i])
        pygame.draw.line(screen, ACCENT, (cx, top), (cx, bot))
        y = self.ys[self.i]
        if y == y and ylo <= y <= yhi:
            pygame.draw.circle(screen, ACCENT, (int(cx), int(py(y))), 2, 1)
        title(self.title)
        screen.blit(f_small.render("x=%s  y=%s" % (fmt(self.xs[self.i]), fmt(y)), True, ACCENT), (4, 10))
        screen.blit(f_small.render(fmt(yhi), True, DIM), (left + 2, top))
        screen.blit(f_small.render(fmt(ylo), True, DIM), (left + 2, bot - f_small.get_linesize()))
        lo_s, hi_s = f_small.render(fmt(self.xlo), True, DIM), f_small.render(fmt(self.xhi), True, DIM)
        screen.blit(lo_s, (left, bot))
        screen.blit(hi_s, (right - hi_s.get_width(), bot))


class Heat:
    """A matrix as colored cells, with a cell cursor."""

    def __init__(self, title, rows, cols, vals):
        self.title, self.rows, self.cols, self.vals = title, rows, cols, vals
        self.lo, self.hi = nice_range(vals, 0)
        self.r = self.c = 0

    def key(self, k, step):
        if k == pygame.K_LEFT:
            self.c = max(0, self.c - step)
        elif k == pygame.K_RIGHT:
            self.c = min(self.cols - 1, self.c + step)
        elif k == pygame.K_UP:
            self.r = max(0, self.r - step)
        elif k == pygame.K_DOWN:
            self.r = min(self.rows - 1, self.r + step)
        else:
            return False
        return True

    def draw(self):
        screen.fill(BG)
        top, bot, left, right = 10 + LINE_H, 128 - f_small.get_linesize(), 4, 114
        cw = (right - left) / self.cols
        ch = (bot - top) / self.rows
        side = min(cw, ch)
        x0 = left + (right - left - side * self.cols) / 2
        y0 = top + (bot - top - side * self.rows) / 2
        span = self.hi - self.lo
        for r in range(self.rows):
            for c in range(self.cols):
                v = self.vals[r * self.cols + c]
                pygame.draw.rect(screen, cmap((v - self.lo) / span),
                                 (x0 + c * side, y0 + r * side, side + 0.5, side + 0.5))
        if side >= 9 and self.rows * self.cols <= 64:  # small matrices: the numbers too
            for r in range(self.rows):
                for c in range(self.cols):
                    v = self.vals[r * self.cols + c]
                    t = f_small.render(fmt(v), True, (0, 0, 0) if (v - self.lo) / span > 0.6 else FG)
                    if t.get_width() <= side - 1:
                        screen.blit(t, (x0 + c * side + (side - t.get_width()) / 2,
                                        y0 + r * side + (side - t.get_height()) / 2))
        pygame.draw.rect(screen, ACCENT, (x0 + self.c * side, y0 + self.r * side, side, side), 1)
        for k in range(40):  # color bar
            pygame.draw.rect(screen, cmap(1 - k / 39), (118, top + k * (bot - top) / 40, 6, (bot - top) / 40 + 0.5))
        t = f_small.render("%dx%d   %s .. %s" % (self.rows, self.cols, fmt(self.lo), fmt(self.hi)), True, DIM)
        screen.blit(t, (4, 128 - f_small.get_linesize()))
        title(self.title)
        v = self.vals[self.r * self.cols + self.c]
        screen.blit(f_small.render("[%d,%d] = %s" % (self.r, self.c, fmt(v)), True, ACCENT), (4, 10))


class Surface3D:
    """z over a grid as a rotatable wireframe (or filled quads, painter's order)."""

    def __init__(self, title, rows, cols, vals, xr=None, yr=None):
        self.title, self.rows, self.cols, self.vals = title, rows, cols, vals
        self.lo, self.hi = nice_range(vals, 0)
        self.xr, self.yr = xr, yr
        self.yaw, self.pitch, self.zoom, self.filled = -0.6, 0.6, 1.0, False

    def key(self, k, step):
        if k == pygame.K_LEFT:
            self.yaw -= 0.08 * step
        elif k == pygame.K_RIGHT:
            self.yaw += 0.08 * step
        elif k == pygame.K_UP:
            self.pitch = max(-1.5, self.pitch - 0.08 * step)
        elif k == pygame.K_DOWN:
            self.pitch = min(1.5, self.pitch + 0.08 * step)
        elif k in (pygame.K_EQUALS, pygame.K_KP_PLUS):
            self.zoom = min(4.0, self.zoom * 1.2)
        elif k in (pygame.K_MINUS, pygame.K_KP_MINUS):
            self.zoom = max(0.3, self.zoom / 1.2)
        elif k in (pygame.K_RETURN, pygame.K_SPACE):
            self.filled = not self.filled
        else:
            return False
        return True

    def project(self, x, y, z):
        cy, sy, cp, sp = math.cos(self.yaw), math.sin(self.yaw), math.cos(self.pitch), math.sin(self.pitch)
        x1, y1 = x * cy - y * sy, x * sy + y * cy
        y2, z2 = y1 * cp - z * sp, y1 * sp + z * cp   # y2: depth
        k = 38 * self.zoom
        return 64 + x1 * k, 70 - z2 * k, y2

    def draw(self):
        screen.fill(BG)
        span = self.hi - self.lo
        R, C = self.rows, self.cols
        pts, ts = [], []
        for r in range(R):
            for c in range(C):
                v = self.vals[r * C + c]
                t = (v - self.lo) / span if v == v else float("nan")
                z = (min(max(t, -0.2), 1.2) - 0.5) if t == t else 0.0
                x = (c / (C - 1) - 0.5) * 2 if C > 1 else 0.0
                y = (r / (R - 1) - 0.5) * 2 if R > 1 else 0.0
                pts.append(self.project(x, y, z * 1.2))
                ts.append(t)
        # the box floor and the axes
        corners = [self.project(x, y, -0.6) for x, y in ((-1, -1), (1, -1), (1, 1), (-1, 1))]
        pygame.draw.lines(screen, (50, 50, 50), True, [p[:2] for p in corners])
        for (ax, ay, name) in ((1.15, -1, "x"), (-1, 1.15, "y")):
            p = self.project(ax, ay, -0.6)
            screen.blit(f_small.render(name, True, DIM), (p[0] - 2, p[1] - 4))
        top_p = self.project(-1, -1, 0.7)
        pygame.draw.line(screen, (50, 50, 50), corners[0][:2], top_p[:2])
        screen.blit(f_small.render("z", True, DIM), (top_p[0] - 2, top_p[1] - 8))
        if self.filled and R > 1 and C > 1:
            quads = []
            for r in range(R - 1):
                for c in range(C - 1):
                    i = r * C + c
                    q = (i, i + 1, i + C + 1, i + C)
                    t = [ts[j] for j in q if ts[j] == ts[j]]
                    if len(t) < 4:
                        continue
                    quads.append((sum(pts[j][2] for j in q), q, sum(t) / 4))
            quads.sort(key=lambda e: -e[0])
            for _, q, t in quads:
                poly = [pts[j][:2] for j in q]
                pygame.draw.polygon(screen, cmap(t), poly)
                pygame.draw.polygon(screen, (20, 20, 20), poly, 1)
        else:
            for r in range(R):
                for c in range(C):
                    i = r * C + c
                    if ts[i] != ts[i]:
                        continue
                    for j in ((i + 1) if c + 1 < C else None, (i + C) if r + 1 < R else None):
                        if j is not None and ts[j] == ts[j]:
                            pygame.draw.line(screen, cmap((ts[i] + ts[j]) / 2), pts[i][:2], pts[j][:2])
            if R == 1 or C == 1:
                for i, p in enumerate(pts):
                    pygame.draw.circle(screen, cmap(ts[i]), (int(p[0]), int(p[1])), 1)
        title(self.title)
        info = "z %s .. %s" % (fmt(self.lo), fmt(self.hi))
        if self.xr:
            info += "   x,y %s .. %s" % (fmt(self.xr[0]), fmt(self.xr[1]))
        screen.blit(f_small.render(info, True, DIM), (4, 10))
        screen.blit(f_small.render("%dx%d" % (R, C), True, DIM), (4, 128 - f_small.get_linesize()))


def title(text):
    t = f_small.render(text[:60], True, ACCENT)
    if t.get_width() > 124:
        while text and f_small.size(text + "…")[0] > 124:
            text = text[:-1]
        t = f_small.render(text + "…", True, ACCENT)
    screen.blit(t, (2, 0))


def show_plot(view):
    """Run a plot view until Esc / KEY3; arrows repeat while held."""
    held, since, last = None, 0.0, 0.0
    dirty = True
    while True:
        for ev in pygame.event.get():
            if ev.type == pygame.QUIT:
                return False
            if ev.type == pygame.KEYDOWN:
                if ev.key in (pygame.K_ESCAPE, pygame.K_BACKSPACE) or (ev.hat and ev.key == pygame.K_3):
                    return True
                k = ev.key
                if ev.hat and k == pygame.K_1:
                    k = pygame.K_EQUALS
                elif ev.hat and k == pygame.K_2:
                    k = pygame.K_MINUS
                elif ev.unicode == "+":
                    k = pygame.K_EQUALS
                if view.key(k, 1):
                    dirty = True
                if k in (pygame.K_LEFT, pygame.K_RIGHT, pygame.K_UP, pygame.K_DOWN):
                    held, since = k, time.monotonic()
            elif ev.type == pygame.KEYUP and ev.key == held:
                held = None
        now = time.monotonic()
        if held and now - since > 0.35 and now - last > 0.05:
            if view.key(held, 2 if now - since > 1.5 else 1):
                dirty = True
            last = now
        if dirty:
            view.draw()
            lcd.flip()
            dirty = False
        clock.tick(30)


# ---------------------------------------------------------------- plot commands

def make_plot(calc, cmd, arg):
    """'plot' / 'heat' / 'plot3d' + its argument -> a view (CalcError on a problem)."""
    parts = split_args(arg)
    expr = parts[0]
    if not expr:
        raise CalcError("що малювати? напр. plot sin(x), -5, 5")
    rng = parts[1:3] if len(parts) >= 3 else None
    if cmd == "plot3d":
        if rng or re.search(r"\b[xy]\b", expr):
            a, b = rng or ("-5", "5")
            lo, hi, vals = fetch_function(calc, expr, ("x", "y"), a, b, N3D)
            return Surface3D(expr, N3D, N3D, vals, (lo, hi), (lo, hi))
        kind, dims, vals = fetch_value(calc, expr)
        if kind == "num":
            raise CalcError("це число, а не матриця")
        rows, cols = (1, dims[0]) if len(dims) == 1 else dims
        if rows * cols < 2:
            raise CalcError("замало точок")
        return Surface3D(expr, rows, cols, vals)
    if rng or (cmd == "plot" and re.search(r"\bx\b", expr)):
        a, b = rng or ("-10", "10")
        lo, hi, vals = fetch_function(calc, expr, ("x",), a, b, N2D)
        xs = [lo + (hi - lo) * k / (N2D - 1) for k in range(N2D)]
        return Plot2D(expr, xs, vals)
    kind, dims, vals = fetch_value(calc, expr)
    if kind == "num":
        raise CalcError("це число; для функції: plot f(x), a, b")
    if len(dims) == 1 or (cmd == "plot" and 1 in dims):
        return Plot2D(expr, list(range(len(vals))), vals)
    rows, cols = dims
    if cmd == "plot" and cols == 2 and rows > 2:
        return Plot2D(expr, vals[0::2], vals[1::2])
    return Heat(expr, rows, cols, vals)


# ---------------------------------------------------------------- the console

def load_history():
    try:
        with open(HISTORY_FILE, encoding="utf-8") as f:
            return [l.rstrip("\n") for l in f if l.strip()][-HISTORY_MAX:]
    except OSError:
        return []


def save_history(hist):
    try:
        os.makedirs(os.path.dirname(HISTORY_FILE), exist_ok=True)
        with open(HISTORY_FILE, "w", encoding="utf-8") as f:
            f.write("\n".join(hist[-HISTORY_MAX:]) + "\n")
    except OSError:
        pass


HELP = [
    "calc: довільна точність. Приклади:",
    "  2^100   sqrt(2)   pi(1e-30)",
    "  mat A[2,2] = {1,2,3,4}",
    "  det(A)   inverse(A)   A*A",
    "  define f(x) = x^2 - 2",
    "Графіки:",
    "  plot sin(x), -5, 5   plot V",
    "  heat A   plot3d A",
    "  plot3d sin(x)*cos(y), -3, 3",
    "  plot - останній графік знову",
    "config(\"display\", 50) - більше знаків",
    "clear - очистити, reset - нова сесія",
    "↑↓ історія, PgUp/PgDn прокрутка, Esc",
]


class Console:
    def __init__(self):
        self.out = []          # (kind, text): kind in in / out / err / info
        self.hist = load_history()
        self.h = len(self.hist)
        self.line, self.cur = "", 0
        self.scroll = 0         # wrapped lines scrolled up from the bottom
        self.example = -1
        self.last_plot = None
        self.add("info", "КАЛЬКУЛЯТОР (calc). help - підказка")

    def add(self, kind, text):
        self.out.append((kind, text))
        self.out = self.out[-500:]
        self.scroll = 0

    def wrapped(self):
        rows = []
        for kind, text in self.out:
            text = ("> " + text) if kind == "in" else text
            rows.append((kind, text[:COLS]))
            text = text[COLS:]
            while text:  # continuation lines of input / messages are indented
                pre = "" if kind == "out" else "  "
                rows.append((kind, pre + text[:COLS - len(pre)]))
                text = text[COLS - len(pre):]
        return rows

    def draw(self, busy):
        screen.fill(BG)
        # the input line: scrolled sideways to keep the cursor in view
        prompt = "> "
        width = COLS - len(prompt)
        start = max(0, self.cur - width + 1)
        shown = self.line[start:start + width]
        in_y = 128 - LINE_H - 1
        pygame.draw.line(screen, (60, 60, 60), (0, in_y - 1), (128, in_y - 1))
        screen.blit(f_mono.render(prompt + shown, True, FG), (2, in_y))
        if busy:
            dots = "." * (int(time.monotonic() * 3) % 4)
            screen.blit(f_mono.render("рахую" + dots + " (Esc - стоп)", True, ACCENT), (2, in_y))
        elif int(time.monotonic() * 2) % 2 == 0:
            cx = 2 + (len(prompt) + self.cur - start) * CHAR_W
            pygame.draw.rect(screen, ACCENT, (cx, in_y, max(1, CHAR_W / 4), LINE_H - 1))
        rows = self.wrapped()
        n = int((in_y - 2) // LINE_H)
        self.scroll = min(self.scroll, max(0, len(rows) - n))
        view = rows[max(0, len(rows) - n - self.scroll):len(rows) - self.scroll]
        colors = {"in": BLUE, "out": FG, "err": RED, "info": DIM}
        for i, (kind, text) in enumerate(view):
            screen.blit(f_mono.render(text, True, colors[kind]), (2, 1 + i * LINE_H))
        if self.scroll:
            pygame.draw.polygon(screen, ACCENT, [(122, in_y - 7), (126, in_y - 3), (118, in_y - 3)])

    # editing
    def insert(self, s):
        self.line = self.line[:self.cur] + s + self.line[self.cur:]
        self.cur += len(s)

    def set_line(self, s):
        self.line, self.cur = s, len(s)


def main():
    if not os.path.exists("/usr/bin/calc"):
        con = Console()
        con.add("err", "немає calc: sudo apt install apcalc")
        con.draw(False)
        lcd.flip()
        time.sleep(4)
        lcd.quit()
        return
    calc = Calc()
    con = Console()
    pending = None   # the input line whose answer calc is computing
    dirty, blink = True, -1
    running = True
    while running:
        for ev in pygame.event.get():
            if ev.type == pygame.QUIT:
                running = False
                break
            if ev.type != pygame.KEYDOWN:
                continue
            dirty = True
            k = ev.key
            if pending is not None:  # computing: only Esc
                if k == pygame.K_ESCAPE or (ev.hat and k == pygame.K_3):
                    calc.start()
                    con.add("err", "перервано - нова сесія calc, змінні втрачено")
                    pending = None
                continue
            if ev.hat:  # HAT buttons: no keyboard - examples instead of typing
                if k == pygame.K_3:
                    running = False
                elif k in (pygame.K_1, pygame.K_2):
                    con.example = (con.example + (1 if k == pygame.K_1 else -1)) % len(EXAMPLES)
                    con.set_line(EXAMPLES[con.example])
                    continue
                elif k == pygame.K_LEFT:
                    con.scroll += 3
                    continue
                elif k == pygame.K_RIGHT:
                    con.scroll = max(0, con.scroll - 3)
                    continue
                elif k not in (pygame.K_UP, pygame.K_DOWN, pygame.K_RETURN):
                    continue
            if k == pygame.K_ESCAPE:
                if con.line:
                    con.set_line("")
                else:
                    running = False
            elif k == pygame.K_RETURN:
                line = con.line.strip()
                con.set_line("")
                if not line:
                    continue
                if not con.hist or con.hist[-1] != line:
                    con.hist.append(line)
                con.h = len(con.hist)
                con.add("in", line)
                word, _, arg = line.partition(" ")
                if line == "clear":
                    con.out = []
                elif line == "help":
                    for l in HELP:
                        con.add("info", l)
                elif line == "reset":
                    calc.start()
                    con.add("info", "нова сесія calc")
                elif word in ("plot", "heat", "plot3d"):
                    if not arg.strip() and word == "plot":
                        view = con.last_plot
                        if view is None:
                            con.add("err", "ще не було графіка")
                            continue
                    else:
                        con.draw(True)
                        lcd.flip()
                        try:
                            view = make_plot(calc, word, arg.strip())
                        except CalcError as e:
                            con.add("err", str(e))
                            continue
                        con.last_plot = view
                    if not show_plot(view):
                        running = False
                    lcd.flush_buttons()
                else:
                    if evaluate_line(calc, line) is None:
                        con.add("err", "незбалансовані дужки")
                    else:
                        pending = line
            elif k == pygame.K_UP:
                if con.h > 0:
                    con.h -= 1
                    con.set_line(con.hist[con.h])
            elif k == pygame.K_DOWN:
                if con.h < len(con.hist) - 1:
                    con.h += 1
                    con.set_line(con.hist[con.h])
                else:
                    con.h = len(con.hist)
                    con.set_line("")
            elif k == pygame.K_LEFT:
                con.cur = max(0, con.cur - 1)
            elif k == pygame.K_RIGHT:
                con.cur = min(len(con.line), con.cur + 1)
            elif k == pygame.K_HOME:
                con.cur = 0
            elif k == pygame.K_END:
                con.cur = len(con.line)
            elif k == pygame.K_BACKSPACE:
                if con.cur:
                    con.line = con.line[:con.cur - 1] + con.line[con.cur:]
                    con.cur -= 1
            elif k == pygame.K_DELETE:
                con.line = con.line[:con.cur] + con.line[con.cur + 1:]
            elif k == pygame.K_PAGEUP:
                con.scroll += 5
            elif k == pygame.K_PAGEDOWN:
                con.scroll = max(0, con.scroll - 5)
            elif ev.unicode and ev.unicode.isprintable():
                con.insert(ev.unicode)
        if pending is not None:
            out = calc.poll(0.02)
            if out is not None:
                lines, err = tidy(out)
                for l in lines:
                    con.add("err" if err else "out", l)
                pending = None
                dirty = True
            elif int(time.monotonic() * 3) != blink:
                blink, dirty = int(time.monotonic() * 3), True
        elif int(time.monotonic() * 2) != blink:  # the cursor blinks
            blink, dirty = int(time.monotonic() * 2), True
        if dirty:
            con.draw(pending is not None)
            lcd.flip()
            dirty = False
        clock.tick(30)
    save_history(con.hist)
    calc.p.kill()
    lcd.quit()


if __name__ == "__main__":
    main()
