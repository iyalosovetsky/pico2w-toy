"""G-code analysis for SERIAL: the toolpath as segments, its bounds, length and a rough run time.

analyze(lines) takes the cleaned lines of a file (comments stripped, as Job keeps them) and follows
the modal state grbl does: G0 / G1 / G2 / G3, G90 / G91, G20 / G21, G17 arcs (I J or R), G4 dwells,
F. G53 moves (machine coordinates) and G28 / G30 are not drawn; G10 / G92 change offsets the file
cannot know, so they only add a warning. Positions are work coordinates; an axis the file has not
set yet stays unknown (grbl would start from wherever the machine is).
"""
import math
import re

WORD = re.compile(r"([A-Z])\s*([-+]?(?:\d+\.?\d*|\.\d+))")
ARC_STEP = math.radians(6)          # arcs become chords of at most this angle


class Info:
    def __init__(self):
        self.segs = []              # (x0, y0, z0, x1, y1, z1, rapid, line index)
        self.lo = [None, None, None]
        self.hi = [None, None, None]
        self.feed_mm = 0.0
        self.rapid_mm = 0.0
        self.time_s = 0.0
        self.line_t = []            # the estimated time at the end of each line (progress / ETA)
        self.warnings = []
        self.no_feed = False

    def size(self):
        return [(h - l) if l is not None else None for l, h in zip(self.lo, self.hi)]


def _grow(info, p):
    for i in range(3):
        v = p[i]
        if v is None:
            continue
        if info.lo[i] is None or v < info.lo[i]:
            info.lo[i] = v
        if info.hi[i] is None or v > info.hi[i]:
            info.hi[i] = v


def _arc_points(p0, p1, cw, i, j, r):
    """Points along a G17 arc from p0 to p1 (x, y, z; z goes linearly: a helix)."""
    x0, y0, z0 = p0
    x1, y1, z1 = p1
    if r is not None:                   # radius form: the centre as grbl computes it
        dx, dy = x1 - x0, y1 - y0
        d2 = 4 * r * r - dx * dx - dy * dy
        d = math.hypot(dx, dy)
        if d == 0 or d2 < -1e-6:
            return [p1], math.dist(p0, p1)
        h = -math.sqrt(max(0.0, d2)) / d
        if not cw:
            h = -h
        if r < 0:
            h = -h
        cx, cy = x0 + 0.5 * (dx - dy * h), y0 + 0.5 * (dy + dx * h)
    else:
        cx, cy = x0 + (i or 0.0), y0 + (j or 0.0)
    rad = math.hypot(x0 - cx, y0 - cy)
    a0 = math.atan2(y0 - cy, x0 - cx)
    a1 = math.atan2(y1 - cy, x1 - cx)
    sweep = a1 - a0
    if cw:
        if sweep >= -1e-9:
            sweep -= 2 * math.pi
    else:
        if sweep <= 1e-9:
            sweep += 2 * math.pi
    n = max(1, int(abs(sweep) / ARC_STEP + 0.999))
    out = []
    for k in range(1, n + 1):
        a = a0 + sweep * k / n
        out.append((cx + rad * math.cos(a), cy + rad * math.sin(a), z0 + (z1 - z0) * k / n))
    out[-1] = (x1, y1, z1)
    return out, rad * abs(sweep)


def analyze(lines, rapids=(3000.0, 3000.0, 1000.0)):
    """lines: cleaned G-code strings; rapids: mm/min per axis ($110-$112) for the time estimate."""
    info = Info()
    pos = [None, None, None]
    motion, absolute, arc_abs, scale, feed = 0, True, False, 1.0, 0.0
    warned = set()
    for idx, line in enumerate(lines):
        words = WORD.findall(line.upper())
        if not words or line.lstrip().startswith("$"):
            info.line_t.append(info.time_s)
            continue
        gs = [float(v) for k, v in words if k == "G"]
        vals = {k: float(v) for k, v in words if k != "G"}
        one_shot = None
        for g in gs:
            if g in (0, 1, 2, 3):
                motion = int(g)
            elif g == 90:
                absolute = True
            elif g == 91:
                absolute = False
            elif g == 90.1:
                arc_abs = True
            elif g == 91.1:
                arc_abs = False
            elif g == 20:
                scale = 25.4
            elif g == 21:
                scale = 1.0
            elif g in (53, 28, 30, 28.1, 30.1):
                one_shot = g
            elif g in (10, 92, 92.1, 92.2, 92.3) and g not in warned:
                warned.add(g)
                info.warnings.append("G%g змінює зміщення - межі можуть бути неточні" % g)
            elif g in (18, 19) and g not in warned:
                warned.add(g)
                info.warnings.append("дуги G%g показано прямими" % g)
            elif g == 4:
                p = vals.get("P", 0.0)
                info.time_s += p
                one_shot = 4
        if "F" in vals:
            feed = vals["F"] * scale
        if any(g in (10, 92) for g in gs):
            # G92 / G10 L20: the current position gets these work coordinates; nothing moves
            if 92 in gs or vals.get("L") == 20:
                for i, a in enumerate("XYZ"):
                    if a in vals:
                        pos[i] = vals[a] * scale
            info.line_t.append(info.time_s)
            continue
        if one_shot is not None:
            if one_shot in (53, 28, 30) and any(a in vals for a in "XYZ"):
                # a move in machine coordinates: the work position after it is unknown
                for i, a in enumerate("XYZ"):
                    if a in vals:
                        pos[i] = None
            info.line_t.append(info.time_s)
            continue
        if not any(a in vals for a in "XYZ"):
            info.line_t.append(info.time_s)
            continue
        new = list(pos)
        for i, a in enumerate("XYZ"):
            if a in vals:
                v = vals[a] * scale
                if absolute:
                    new[i] = v
                elif pos[i] is not None:
                    new[i] = pos[i] + v
                else:
                    new[i] = None
        known = all(v is not None for v in pos) and all(v is not None for v in new)
        if known:
            if motion in (2, 3) and any(k in vals for k in "IJR"):
                ii, jj = vals.get("I"), vals.get("J")
                if arc_abs:
                    ii = ii * scale - pos[0] if ii is not None else None
                    jj = jj * scale - pos[1] if jj is not None else None
                else:
                    ii = ii * scale if ii is not None else None
                    jj = jj * scale if jj is not None else None
                r = vals["R"] * scale if "R" in vals else None
                pts, length = _arc_points(tuple(pos), tuple(new), motion == 2, ii, jj, r)
                prev = tuple(pos)
                for p in pts:
                    info.segs.append(prev + tuple(p) + (False, idx))
                    _grow(info, p)
                    prev = p
                rapid = False
            else:
                rapid = motion == 0
                length = math.dist(pos, new)
                info.segs.append(tuple(pos) + tuple(new) + (rapid, idx))
                _grow(info, pos)
                _grow(info, new)
            if rapid:
                info.rapid_mm += length
                d = [abs(b - a) for a, b in zip(pos, new)]
                info.time_s += max(d[i] / max(rapids[i], 1.0) for i in range(3)) * 60
            else:
                info.feed_mm += length
                if feed > 0:
                    info.time_s += length / feed * 60
                else:
                    info.no_feed = True
        else:
            _grow(info, new)
        pos = new
        info.line_t.append(info.time_s)
    if info.no_feed:
        info.warnings.append("є рухи G1 / G2 / G3 без подачі F")
    return info


def envelope(settings, axis):
    """The machine coordinate range grblHAL allows for an axis after homing, or None.

    settings: {id: value} from $$. $130.. - travel; $22 bit 3 - force the origin to 0 (then $23,
    the homing direction mask, decides the side); otherwise the range is [-travel, 0].
    """
    travel = settings.get(130 + axis)
    if travel is None:
        return None
    flags = int(settings.get(22, 0))
    if flags & 8 and int(settings.get(23, 0)) & (1 << axis):
        return 0.0, abs(travel)
    return -abs(travel), 0.0


def fits(info, wco, settings):
    """[(axis letter, how far below the range, how far above)] for the axes that do not fit."""
    out = []
    for i, a in enumerate("XYZ"):
        env = envelope(settings, i)
        if env is None or info.lo[i] is None or wco is None or i >= len(wco):
            continue
        lo, hi = info.lo[i] + wco[i], info.hi[i] + wco[i]
        under, over = max(0.0, env[0] - lo), max(0.0, hi - env[1])
        if under > 0.01 or over > 0.01:
            out.append((a, under, over))
    return out
