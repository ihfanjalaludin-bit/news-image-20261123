#!/usr/bin/env python3
"""THE WORLD IN ONE DAY - Monday 23 November 2026.

Draws a one-page newspaper front page summing up 23 November 2026's
world news as a single 1024x1024 PNG. Pure Python 3 standard library:
it reads the vendored DejaVu TrueType fonts itself, rasterises their
glyph outlines, and writes the PNG with zlib. No third-party packages,
no network, no randomness, no timestamps. Fonts live in repo/fonts/
and are resolved relative to this file, never from the system.
"""

import math
import os
import struct
import zlib

W, H = 1024, 1024
PAPER = (248, 244, 233)
INK = (22, 22, 22)
RED = (164, 30, 34)
GREY = (90, 86, 78)
RULE = (60, 58, 52)

MARGIN = 30
CONTENT_W = W - 2 * MARGIN

_HERE = os.path.dirname(os.path.abspath(__file__))


def _u16(b, o):
    return struct.unpack_from(">H", b, o)[0]


def _i16(b, o):
    return struct.unpack_from(">h", b, o)[0]


def _u32(b, o):
    return struct.unpack_from(">I", b, o)[0]


def _i8(b, o):
    return struct.unpack_from(">b", b, o)[0]


def _f2dot14(b, o):
    return _i16(b, o) / 16384.0


FONT_FILES = {
    "serif": os.path.join(_HERE, "fonts", "DejaVuSerif.ttf"),
    "serif_bold": os.path.join(_HERE, "fonts", "DejaVuSerif-Bold.ttf"),
    "sans": os.path.join(_HERE, "fonts", "DejaVuSans.ttf"),
    "sans_bold": os.path.join(_HERE, "fonts", "DejaVuSans-Bold.ttf"),
}


class TruetypeFont:
    """Small reader for the TrueType tables we need: cmap, hmtx, loca,
    glyf, head and hhea. Only the glyph outlines and advances are used."""

    def __init__(self, path):
        with open(path, "rb") as fh:
            self.blob = fh.read()
        data = self.blob
        n_tables = _u16(data, 4)
        self.tables = {}
        for i in range(n_tables):
            base = 12 + 16 * i
            tag = data[base:base + 4].decode("latin-1")
            self.tables[tag] = (_u32(data, base + 8), _u32(data, base + 12))
        head, _ = self.tables["head"]
        self.units = _u16(data, head + 18)
        self.loc_fmt = _i16(data, head + 50)
        hhea, _ = self.tables["hhea"]
        self.ascent = _i16(data, hhea + 4)
        self.descent = _i16(data, hhea + 6)
        self.n_hmtx = _u16(data, hhea + 34)
        maxp, _ = self.tables["maxp"]
        self.n_glyphs = _u16(data, maxp + 4)
        self._cmap = self._load_cmap()
        self._loca = self._load_loca()

    def _load_cmap(self):
        data = self.blob
        off, _ = self.tables["cmap"]
        n_sub = _u16(data, off + 2)
        fmt4 = None
        fmt12 = None
        for i in range(n_sub):
            plat = _u16(data, off + 4 + 8 * i)
            enc = _u16(data, off + 6 + 8 * i)
            sub = _u32(data, off + 8 + 8 * i)
            fmt = _u16(data, off + sub)
            if fmt == 4 and fmt4 is None and (plat, enc) in (
                    (3, 1), (0, 3), (0, 4), (0, 0)):
                fmt4 = off + sub
            elif fmt == 12 and fmt12 is None:
                fmt12 = off + sub
        if fmt4 is not None:
            seg_count = _u16(data, fmt4 + 6) // 2
            ends = fmt4 + 14
            starts = ends + 2 * seg_count + 2
            deltas = starts + 2 * seg_count
            ranges = deltas + 2 * seg_count
            segs = []
            for i in range(seg_count):
                segs.append((
                    _u16(data, starts + 2 * i),
                    _u16(data, ends + 2 * i),
                    _i16(data, deltas + 2 * i),
                    _u16(data, ranges + 2 * i),
                    ranges + 2 * i,
                ))
            return ("fmt4", segs)
        if fmt12 is not None:
            n_groups = _u32(data, fmt12 + 12)
            groups = []
            for i in range(n_groups):
                g = fmt12 + 16 + 12 * i
                groups.append((_u32(data, g), _u32(data, g + 4),
                               _u32(data, g + 8)))
            return ("fmt12", groups)
        raise ValueError("no usable cmap subtable in font")

    def _load_loca(self):
        data = self.blob
        off, _ = self.tables["loca"]
        if self.loc_fmt == 0:
            return [_u16(data, off + 2 * i) * 2
                    for i in range(self.n_glyphs + 1)]
        return [_u32(data, off + 4 * i)
                for i in range(self.n_glyphs + 1)]

    def glyph_id(self, codepoint):
        kind, table = self._cmap
        if kind == "fmt4":
            for start, end, delta, roff, roff_pos in table:
                if start <= codepoint <= end:
                    if roff == 0:
                        return (codepoint + delta) % 65536
                    idx = roff_pos + roff + 2 * (codepoint - start)
                    return (_u16(self.blob, idx) + delta) % 65536
            return 0
        for start, end, first in table:
            if start <= codepoint <= end:
                return first + (codepoint - start)
        return 0

    def advance(self, gid):
        off, _ = self.tables["hmtx"]
        if gid < self.n_hmtx:
            return _u16(self.blob, off + 4 * gid)
        return _u16(self.blob, off + 4 * (self.n_hmtx - 1))

    def contours(self, gid):
        data = self.blob
        off, _ = self.tables["glyf"]
        g0 = self._loca[gid]
        g1 = self._loca[gid + 1]
        if g0 == g1:
            return []
        p = off + g0
        if _i16(data, p) >= 0:
            return self._simple_contours(p)
        return self._composite_contours(p)

    def _simple_contours(self, p):
        data = self.blob
        n_cont = _i16(data, p)
        ends = [_u16(data, p + 10 + 2 * i) for i in range(n_cont)]
        instr_len = _u16(data, p + 10 + 2 * n_cont)
        q = p + 12 + 2 * n_cont + instr_len
        n_pts = ends[-1] + 1
        flags = []
        while len(flags) < n_pts:
            f = data[q]
            q += 1
            flags.append(f)
            if f & 0x08:
                rep = data[q]
                q += 1
                flags.extend([f] * rep)
        xs = []
        x = 0
        for f in flags:
            if f & 0x02:
                dx = data[q]
                q += 1
                x += dx if (f & 0x10) else -dx
            elif not (f & 0x10):
                x += _i16(data, q)
                q += 2
            xs.append(x)
        ys = []
        y = 0
        for f in flags:
            if f & 0x04:
                dy = data[q]
                q += 1
                y += dy if (f & 0x20) else -dy
            elif not (f & 0x20):
                y += _i16(data, q)
                q += 2
            ys.append(y)
        pts = [(xs[i], ys[i], bool(flags[i] & 0x01)) for i in range(n_pts)]
        contours = []
        start = 0
        for end in ends:
            contours.append(pts[start:end + 1])
            start = end + 1
        return contours

    def _composite_contours(self, p):
        data = self.blob
        q = p + 10
        out = []
        while True:
            flags = _u16(data, q)
            comp_gid = _u16(data, q + 2)
            q += 4
            if flags & 0x0001:
                arg1 = _i16(data, q)
                arg2 = _i16(data, q + 2)
                q += 4
            else:
                arg1 = _i8(data, q)
                arg2 = _i8(data, q + 1)
                q += 2
            if flags & 0x0008:
                s = _f2dot14(data, q)
                q += 2
                m = (s, 0.0, 0.0, s)
            elif flags & 0x0040:
                m = (_f2dot14(data, q), 0.0, 0.0,
                     _f2dot14(data, q + 2))
                q += 4
            elif flags & 0x0080:
                m = (_f2dot14(data, q), _f2dot14(data, q + 2),
                     _f2dot14(data, q + 4), _f2dot14(data, q + 6))
                q += 8
            else:
                m = (1.0, 0.0, 0.0, 1.0)
            dx, dy = (arg1, arg2) if (flags & 0x0002) else (0, 0)
            for contour in self.contours(comp_gid):
                out.append([
                    (x * m[0] + y * m[2] + dx,
                     x * m[1] + y * m[3] + dy, on)
                    for (x, y, on) in contour])
            if not (flags & 0x0020):
                break
        return out


def _flatten(points):
    """Turn one contour of on/off-curve points into a polygon."""
    pts = list(points)
    if not pts:
        return []
    if not pts[0][2]:
        if pts[-1][2]:
            pts = [pts[-1]] + pts[:-1]
        else:
            mx = (pts[-1][0] + pts[0][0]) * 0.5
            my = (pts[-1][1] + pts[0][1]) * 0.5
            pts = [(mx, my, True)] + pts
    poly = [(pts[0][0], pts[0][1])]
    i = 1
    n = len(pts)
    while i < n:
        x0, y0 = poly[-1]
        if pts[i][2]:
            poly.append((pts[i][0], pts[i][1]))
            i += 1
        else:
            cx, cy = pts[i][0], pts[i][1]
            if i + 1 < n:
                if pts[i + 1][2]:
                    ex, ey = pts[i + 1][0], pts[i + 1][1]
                    i += 2
                else:
                    ex = (cx + pts[i + 1][0]) * 0.5
                    ey = (cy + pts[i + 1][1]) * 0.5
                    i += 1
            else:
                ex, ey = pts[0][0], pts[0][1]
                i += 1
            steps = 10
            for s in range(1, steps + 1):
                t = s / steps
                mt = 1.0 - t
                poly.append((mt * mt * x0 + 2 * mt * t * cx + t * t * ex,
                             mt * mt * y0 + 2 * mt * t * cy + t * t * ey))
    return poly


_SS = 4  # supersampling factor for glyph antialiasing


def _rasterize(font, gid, size):
    """Render one glyph to a grayscale alpha bitmap.

    Returns (min_x, min_y, width, height, alpha) where min_x/min_y are
    offsets from the pen position / baseline in pixels.
    """
    contours = font.contours(gid)
    if not contours:
        return None
    scale = size / font.units
    polys = []
    for contour in contours:
        poly = _flatten(contour)
        if len(poly) >= 2:
            polys.append([(x * scale, -y * scale) for (x, y) in poly])
    if not polys:
        return None
    all_x = [x for poly in polys for (x, _y) in poly]
    all_y = [y for poly in polys for (_x, y) in poly]
    min_x = math.floor(min(all_x))
    max_x = math.ceil(max(all_x))
    min_y = math.floor(min(all_y))
    max_y = math.ceil(max(all_y))
    w = max_x - min_x
    h = max_y - min_y
    if w <= 0 or h <= 0:
        return None
    hits = bytearray(w * h)
    for sy in range(h * _SS):
        y = min_y + (sy + 0.5) / _SS
        crossings = []
        for poly in polys:
            m = len(poly)
            for k in range(m):
                x1, y1 = poly[k]
                x2, y2 = poly[(k + 1) % m]
                if (y1 <= y < y2) or (y2 <= y < y1):
                    t = (y - y1) / (y2 - y1)
                    crossings.append(x1 + t * (x2 - x1))
        crossings.sort()
        row = sy // _SS
        for j in range(0, len(crossings) - 1, 2):
            x0 = crossings[j]
            x1 = crossings[j + 1]
            sx0 = max(0, int(math.floor((x0 - min_x) * _SS)))
            sx1 = min(w * _SS, int(math.ceil((x1 - min_x) * _SS)))
            for sx in range(sx0, sx1):
                cx = min_x + (sx + 0.5) / _SS
                if x0 <= cx < x1:
                    hits[row * w + sx // _SS] += 1
    full = _SS * _SS
    alpha = bytes((c * 255) // full for c in hits)
    return (min_x, min_y, w, h, alpha)


class TextEngine:
    def __init__(self):
        self.fonts = {name: TruetypeFont(path)
                      for name, path in FONT_FILES.items()}
        self._cache = {}

    def _bitmap(self, name, size, ch):
        key = (name, size, ch)
        bmp = self._cache.get(key)
        if bmp is None:
            font = self.fonts[name]
            gid = font.glyph_id(ord(ch))
            bmp = _rasterize(font, gid, size) if gid else False
            self._cache[key] = bmp
        return bmp

    def width(self, name, size, text):
        font = self.fonts[name]
        scale = size / font.units
        total = 0.0
        for ch in text:
            total += font.advance(font.glyph_id(ord(ch))) * scale
        return total

    def ascent(self, name, size):
        font = self.fonts[name]
        return font.ascent * size / font.units

    def draw(self, canvas, name, size, x, y_top, text, color,
             align="left"):
        """Draw text; (x, y_top) is the left edge and the top of the
        line."""
        if align == "center":
            x -= self.width(name, size, text) / 2.0
        elif align == "right":
            x -= self.width(name, size, text)
        font = self.fonts[name]
        baseline = y_top + self.ascent(name, size)
        pen = float(x)
        for ch in text:
            gid = font.glyph_id(ord(ch))
            if gid:
                bmp = self._bitmap(name, size, ch)
                if bmp:
                    bx, by, w, h, alpha = bmp
                    canvas.blit_alpha(int(round(pen)) + bx,
                                      int(round(baseline)) + by,
                                      w, h, alpha, color)
                pen += font.advance(gid) * size / font.units
            else:
                pen += font.advance(0) * size / font.units

    def wrap(self, name, size, text, max_w):
        lines = []
        cur = ""
        for word in text.split(" "):
            trial = word if not cur else cur + " " + word
            if self.width(name, size, trial) <= max_w or not cur:
                cur = trial
            else:
                lines.append(cur)
                cur = word
        if cur:
            lines.append(cur)
        return lines


class Canvas:
    def __init__(self, w, h, bg):
        self.w = w
        self.h = h
        self.px = bytearray(w * h * 3)
        row = bytes(bg) * w
        for yy in range(h):
            base = yy * w * 3
            self.px[base:base + len(row)] = row

    def fill_rect(self, x, y, w, h, color):
        x0 = max(0, int(x))
        y0 = max(0, int(y))
        x1 = min(self.w, int(x) + int(w))
        y1 = min(self.h, int(y) + int(h))
        if x1 <= x0 or y1 <= y0:
            return
        row = bytes(color) * (x1 - x0)
        for yy in range(y0, y1):
            base = (yy * self.w + x0) * 3
            self.px[base:base + len(row)] = row

    def fill_polygon(self, points, color):
        """Even-odd scanline fill of a polygon given in pixel coords."""
        if len(points) < 3:
            return
        ys = [p[1] for p in points]
        y0 = max(0, int(math.floor(min(ys))))
        y1 = min(self.h - 1, int(math.ceil(max(ys))))
        n = len(points)
        for yy in range(y0, y1 + 1):
            y = yy + 0.5
            xs = []
            for k in range(n):
                x1, y1p = points[k]
                x2, y2p = points[(k + 1) % n]
                if (y1p <= y < y2p) or (y2p <= y < y1p):
                    t = (y - y1p) / (y2p - y1p)
                    xs.append(x1 + t * (x2 - x1))
            xs.sort()
            for j in range(0, len(xs) - 1, 2):
                xa = max(0, int(math.ceil(xs[j])))
                xb = min(self.w, int(math.floor(xs[j + 1])))
                for xx in range(xa, xb):
                    idx = (yy * self.w + xx) * 3
                    self.px[idx] = color[0]
                    self.px[idx + 1] = color[1]
                    self.px[idx + 2] = color[2]

    def draw_line(self, x1, y1, x2, y2, width, color):
        dx = x2 - x1
        dy = y2 - y1
        length = math.hypot(dx, dy)
        if length == 0:
            return
        nx = -dy / length * width / 2.0
        ny = dx / length * width / 2.0
        self.fill_polygon([(x1 + nx, y1 + ny), (x2 + nx, y2 + ny),
                           (x2 - nx, y2 - ny), (x1 - nx, y1 - ny)],
                          color)

    def blit_alpha(self, x, y, w, h, alpha, color):
        for row in range(h):
            cy = y + row
            if cy < 0 or cy >= self.h:
                continue
            for col in range(w):
                a = alpha[row * w + col]
                if a == 0:
                    continue
                cx = x + col
                if cx < 0 or cx >= self.w:
                    continue
                idx = (cy * self.w + cx) * 3
                if a == 255:
                    self.px[idx] = color[0]
                    self.px[idx + 1] = color[1]
                    self.px[idx + 2] = color[2]
                else:
                    for ch in range(3):
                        self.px[idx + ch] = (
                            self.px[idx + ch] * (255 - a)
                            + color[ch] * a) // 255


def _png_chunk(tag, data):
    out = struct.pack(">I", len(data)) + tag + data
    out += struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)
    return out


def write_png(path, canvas):
    raw = bytearray()
    for y in range(canvas.h):
        raw.append(0)
        raw += canvas.px[y * canvas.w * 3:(y + 1) * canvas.w * 3]
    comp = zlib.compress(bytes(raw), 9)
    ihdr = struct.pack(">IIBBBBB", canvas.w, canvas.h, 8, 2, 0, 0, 0)
    png = (b"\x89PNG\r\n\x1a\n" + _png_chunk(b"IHDR", ihdr)
           + _png_chunk(b"IDAT", comp) + _png_chunk(b"IEND", b""))
    with open(path, "wb") as fh:
        fh.write(png)


# ------------------------------------------------------------------ page

PANELS = [
    (
        "THE GULF  |  HORMUZ",
        "GULF WAR HEATS UP",
        "Houthi drones and missiles struck Saudi Arabia for a third straight "
        "day; all were intercepted. Iran's IRGC says it destroyed two Patriot "
        "radars at a US base in Bahrain. At least 25 tankers have been hit in "
        "or near the Strait of Hormuz in seven days, and Gulf oil flows have "
        "fallen sharply.",
    ),
    (
        "SPACE  |  MERCURY",
        "BEPICOLOMBO ENTERS MERCURY'S ORBIT",
        "After an eight-year journey, the ESA/JAXA spacecraft entered orbit "
        "around Mercury on Saturday - only the second mission ever to do so, "
        "after NASA's MESSENGER. A software glitch cut a thruster burn short "
        "on Sunday, but the craft is safe. Science begins in April 2027.",
    ),
    (
        "UKRAINE  |  THE BALTIC",
        "RUSSIAN SHIP STILL BURNING OFF FINLAND",
        "A Russian cargo ship was still ablaze off Finland after an attack, "
        "as Ukrainian drones struck and at least 14 people were reported "
        "missing after a Russian drone hit a building in the Kyiv region. "
        "In Indonesia, a factory fire left 7 dead and 50 missing.",
    ),
]

ALSO = [
    ("NEPAL - INDIA", "PM Balendra Shah meets Modi in New Delhi"),
    ("WASHINGTON", "Democrats take historic House majority - 258 seats"),
    ("MARKETS", "Anthropic's Nasdaq debut is the biggest IPO yet"),
    ("CRICKET", "India smashes record 720/9 declared in Wellington Test"),
]


def draw_wrapped(te, cv, x, y, text, name, size, max_w, color, leading):
    lines = te.wrap(name, size, text, max_w)
    for line in lines:
        te.draw(cv, name, size, x, y, line, color)
        y += leading
    return y


def rule(cv, x0, x1, y, width=2, color=RULE):
    cv.draw_line(x0, y, x1, y, width, color)


def masthead(cv, te):
    te.draw(cv, "serif_bold", 62, W // 2, 30, "THE WORLD IN ONE DAY",
            INK, align="center")
    rule(cv, MARGIN, W - MARGIN, 108, width=3)
    rule(cv, MARGIN, W - MARGIN, 113, width=1)
    te.draw(cv, "sans_bold", 25, W // 2, 124, "MONDAY, 23 NOVEMBER 2026",
            RED, align="center")
    te.draw(cv, "sans", 16, W // 2, 158,
            "The whole world, in one picture  |  "
            "All stories verified 23 November 2026",
            GREY, align="center")


def lead_panel(cv, te):
    y0 = 196
    te.draw(cv, "sans_bold", 19, MARGIN, y0, "CLIMATE  |  ANTALYA, TURKIYE",
            RED)
    y = y0 + 30
    for line in ["COP31 COLLAPSES", "WITHOUT A DEAL"]:
        te.draw(cv, "serif_bold", 54, MARGIN, y, line, INK)
        y += 62
    y += 6
    rule(cv, MARGIN, W - MARGIN, y, width=1)
    y += 14
    body = (
        "United Nations climate talks in Antalya ended on Sunday with no political "
        "agreement - the first failure since Copenhagen in 2009. The final draft "
        "did not mention fossil fuels at all. The EU refused to endorse it, while "
        "Saudi Arabia and big oil producers objected to naming fossil fuels. "
        "UN chief Antonio Guterres said he was \u201cdeeply disappointed\u201d."
    )
    y = draw_wrapped(te, cv, MARGIN, y, body, "sans", 20, CONTENT_W,
                     INK, 27)
    return y


def columns(cv, te, y0):
    gap = 24
    col_w = (CONTENT_W - 2 * gap) // 3
    for i, (kicker, headline, body) in enumerate(PANELS):
        x = MARGIN + i * (col_w + gap)
        cv.fill_rect(x, y0, col_w, 5, RED)
        y = y0 + 16
        te.draw(cv, "sans_bold", 16, x, y, kicker, RED)
        y += 26
        y = draw_wrapped(te, cv, x, y, headline, "sans_bold", 23, col_w,
                         INK, 28)
        y += 8
        draw_wrapped(te, cv, x, y, body, "sans", 17, col_w, INK, 23)
        if i < 2:
            cv.draw_line(x + col_w + gap // 2, y0 + 10,
                         x + col_w + gap // 2, y0 + 300, 1, RULE)
    return y0 + 312


def also_today(cv, te, y0):
    rule(cv, MARGIN, W - MARGIN, y0, width=3)
    te.draw(cv, "sans_bold", 20, MARGIN, y0 + 12, "ALSO TODAY", RED)
    y = y0 + 46
    gap = 20
    col_w = (CONTENT_W - 3 * gap) // 4
    for i, (kicker, text) in enumerate(ALSO):
        x = MARGIN + i * (col_w + gap)
        te.draw(cv, "sans_bold", 14, x, y, kicker, GREY)
        draw_wrapped(te, cv, x, y + 22, text, "sans", 15, col_w, INK, 20)
    return y + 96


def build_page():
    cv = Canvas(W, H, PAPER)
    te = TextEngine()
    masthead(cv, te)
    y = lead_panel(cv, te)
    rule(cv, MARGIN, W - MARGIN, y + 12, width=2)
    y = columns(cv, te, y + 28)
    y = also_today(cv, te, y + 14)
    te.draw(cv, "sans", 14, W // 2, H - 30,
            "THE WORLD IN ONE DAY  |  Monday 23 November 2026  |  "
            "COP31  -  Hormuz  -  Mercury  -  Kyiv",
            GREY, align="center")
    return cv


def main():
    out_dir = os.environ.get("MAKEFUN_OUTPUT_DIR") or "/output"
    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, "entry.png")
    write_png(out_path, build_page())
    print("wrote", out_path, os.path.getsize(out_path), "bytes")


if __name__ == "__main__":
    main()
