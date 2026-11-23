#!/usr/bin/env python3
"""THE WORLD IN ONE DAY - Monday 23 November 2026.

A one-page newspaper front page summing up 23 November 2026's world
news as a single 1024x1024 PNG. Pure Python standard library only:
this file parses TrueType fonts by hand, turns glyph outlines into
pixels with its own scanline rasterizer, lays out the page, and writes
the PNG with zlib. No Pillow, no network, deterministic output.

Fonts are vendored in repo/fonts/ and resolved relative to this file,
never from the system font directory.
"""

import binascii
import os
import struct
import zlib
from pathlib import Path

HERE = Path(__file__).resolve().parent
FONT_DIR = HERE / "fonts"

PAGE_W = 1024
PAGE_H = 1024

PAPER = (248, 244, 233)
INK = (22, 22, 22)
RED = (164, 30, 34)
GREY = (90, 86, 78)
RULE = (60, 58, 52)

MARGIN = 30
CONTENT_W = PAGE_W - 2 * MARGIN


# ---------------------------------------------------------------- PNG writer
def _chunk(tag, payload):
    """One PNG chunk: length, tag, payload, CRC32."""
    body = tag + payload
    return struct.pack(">I", len(payload)) + body + struct.pack(
        ">I", binascii.crc32(body) & 0xFFFFFFFF
    )


def encode_png(width, height, rgb):
    """Encode a raw RGB byte string (width*height*3 bytes) as PNG bytes.

    Every scanline uses filter type 0 (None); zlib level 6 keeps the
    output deterministic across runs and machines.
    """
    header = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    raw = bytearray()
    stride = width * 3
    for row in range(height):
        raw.append(0)
        raw += rgb[row * stride:(row + 1) * stride]
    blob = zlib.compress(bytes(raw), 6)
    return (
        b"\x89PNG\r\n\x1a\n"
        + _chunk(b"IHDR", header)
        + _chunk(b"IDAT", blob)
        + _chunk(b"IEND", b"")
    )


# ------------------------------------------------------------------- canvas
class Sheet:
    """An RGB pixel buffer with tiny painting helpers."""

    def __init__(self, width, height, background):
        self.width = width
        self.height = height
        self.pixels = bytearray(background * (width * height))

    def fill_rect(self, x, y, w, h, color):
        x0 = max(0, x)
        y0 = max(0, y)
        x1 = min(self.width, x + w)
        y1 = min(self.height, y + h)
        if x1 <= x0 or y1 <= y0:
            return
        r, g, b = color
        row = bytes((r, g, b)) * (x1 - x0)
        for yy in range(y0, y1):
            base = (yy * self.width + x0) * 3
            self.pixels[base:base + len(row)] = row

    def fill_hline(self, x0, x1, y, thickness, color):
        self.fill_rect(x0, y, x1 - x0, thickness, color)

    def stamp(self, alpha, bw, bh, x, y, color):
        """Blend a greyscale alpha bitmap onto the sheet at (x, y)."""
        if bw <= 0 or bh <= 0:
            return
        r, g, b = color
        for row in range(bh):
            py = y + row
            if py < 0 or py >= self.height:
                continue
            for col in range(bw):
                px = x + col
                if px < 0 or px >= self.width:
                    continue
                a = alpha[row * bw + col]
                if a == 0:
                    continue
                base = (py * self.width + px) * 3
                if a == 255:
                    self.pixels[base] = r
                    self.pixels[base + 1] = g
                    self.pixels[base + 2] = b
                else:
                    inv = 255 - a
                    self.pixels[base] = (r * a + self.pixels[base] * inv) // 255
                    self.pixels[base + 1] = (
                        g * a + self.pixels[base + 1] * inv
                    ) // 255
                    self.pixels[base + 2] = (
                        b * a + self.pixels[base + 2] * inv
                    ) // 255

    def png_bytes(self):
        return encode_png(self.width, self.height, bytes(self.pixels))


# ------------------------------------------------------- TrueType parsing
def _u16(data, off):
    return struct.unpack_from(">H", data, off)[0]


def _i16(data, off):
    return struct.unpack_from(">h", data, off)[0]


def _u32(data, off):
    return struct.unpack_from(">I", data, off)[0]


class Face:
    """A minimal TrueType reader: cmap, advances, glyph outlines.

    Only the tables needed for rendering are parsed. Supports cmap
    formats 4 and 12, simple glyphs and compound glyphs.
    """

    def __init__(self, path):
        self.data = Path(path).read_bytes()
        data = self.data
        count = _u16(data, 4)
        self.tables = {}
        for i in range(count):
            rec = 12 + i * 16
            tag = data[rec:rec + 4].decode("latin-1")
            self.tables[tag] = (
                _u32(data, rec + 8),
                _u32(data, rec + 12),
            )
        head = self._table("head")
        self.units_per_em = _u16(head, 18)
        self.loc_format = _i16(head, 50)
        self.glyph_count = _u16(self._table("maxp"), 4)
        hhea = self._table("hhea")
        self.metric_count = _u16(hhea, 34)
        self._build_cmap()
        self._build_loca()

    def _table(self, tag):
        off, length = self.tables[tag]
        return self.data[off:off + length]

    # -- character map ---------------------------------------------------
    def _build_cmap(self):
        cmap = self._table("cmap")
        n = _u16(cmap, 2)
        best = None
        fallback = None
        for i in range(n):
            rec = 4 + i * 8
            platform = _u16(cmap, rec)
            encoding = _u16(cmap, rec + 2)
            sub = _u32(cmap, rec + 4)
            fmt = _u16(cmap, sub)
            if fmt not in (4, 12):
                continue
            if platform == 3 and encoding == 10 and fmt == 12:
                best = (fmt, cmap[sub:])
                break
            if platform == 3 and encoding == 1 and fmt == 4 and best is None:
                best = (fmt, cmap[sub:])
            if fallback is None:
                fallback = (fmt, cmap[sub:])
        if best is None:
            best = fallback
        if best is None:
            raise ValueError("no usable cmap subtable")
        self.cmap_fmt, self.cmap = best
        if self.cmap_fmt == 4:
            c = self.cmap
            self.seg_count = _u16(c, 6) // 2
            base = 14
            self.end_codes = [
                _u16(c, base + 2 * i) for i in range(self.seg_count)
            ]
            base += 2 * self.seg_count + 2
            self.start_codes = [
                _u16(c, base + 2 * i) for i in range(self.seg_count)
            ]
            base += 2 * self.seg_count
            self.deltas = [
                _i16(c, base + 2 * i) for i in range(self.seg_count)
            ]
            base += 2 * self.seg_count
            self.range_offsets = [
                _u16(c, base + 2 * i) for i in range(self.seg_count)
            ]
            self.range_base = base
            self.glyph_ids = c[base + 2 * self.seg_count:]
        else:
            self.groups = []
            c = self.cmap
            n_groups = _u32(c, 12)
            for i in range(n_groups):
                g = 16 + i * 12
                self.groups.append(
                    (_u32(c, g), _u32(c, g + 4), _u32(c, g + 8))
                )

    def glyph_index(self, codepoint):
        if self.cmap_fmt == 4:
            for i in range(self.seg_count):
                if self.end_codes[i] < codepoint:
                    continue
                if self.start_codes[i] > codepoint:
                    return 0
                if self.range_offsets[i] == 0:
                    return (codepoint + self.deltas[i]) & 0xFFFF
                pos = (
                    self.range_base
                    + 2 * i
                    + self.range_offsets[i]
                    + 2 * (codepoint - self.start_codes[i])
                )
                gid = _u16(self.glyph_ids, pos - (self.range_base + 2 * self.seg_count))
                if gid == 0:
                    return 0
                return (gid + self.deltas[i]) & 0xFFFF
            return 0
        for start, end, first_gid in self.groups:
            if start <= codepoint <= end:
                return first_gid + (codepoint - start)
        return 0

    # -- glyph locations -------------------------------------------------
    def _build_loca(self):
        loca = self._table("loca")
        self.loca = []
        if self.loc_format == 0:
            for i in range(self.glyph_count + 1):
                self.loca.append(_u16(loca, 2 * i) * 2)
        else:
            for i in range(self.glyph_count + 1):
                self.loca.append(_u32(loca, 4 * i))

    # -- advances --------------------------------------------------------
    def advance(self, glyph_id):
        hmtx = self._table("hmtx")
        if glyph_id < self.metric_count:
            return _u16(hmtx, glyph_id * 4)
        return _u16(hmtx, (self.metric_count - 1) * 4)


    # -- glyph outlines --------------------------------------------------
    def outline_segments(self, glyph_id, depth=0):
        """Return a list of contours; each contour is a list of straight
        segments (x0, y0, x1, y1) in font units, y pointing up."""
        if depth > 4 or glyph_id >= self.glyph_count:
            return []
        glyf = self._table("glyf")
        start = self.loca[glyph_id]
        end = self.loca[glyph_id + 1]
        if end <= start:
            return []
        g = glyf[start:end]
        contours = _i16(g, 0)
        if contours >= 0:
            return self._simple_outline(g, contours)
        return self._compound_outline(g, depth)

    def _simple_outline(self, g, contour_count):
        end_pts = [_u16(g, 10 + 2 * i) for i in range(contour_count)]
        point_total = end_pts[-1] + 1
        ins_len = _u16(g, 10 + 2 * contour_count)
        pos = 10 + 2 * contour_count + 2 + ins_len
        flags = []
        while len(flags) < point_total:
            flag = g[pos]
            pos += 1
            flags.append(flag)
            if flag & 0x08:
                repeat = g[pos]
                pos += 1
                flags.extend([flag] * repeat)
        flags = flags[:point_total]
        xs = []
        x = 0
        for flag in flags:
            if flag & 0x02:
                step = g[pos]
                pos += 1
                x += step if flag & 0x10 else -step
            elif flag & 0x10:
                pass
            else:
                x += _i16(g, pos)
                pos += 2
            xs.append(x)
        ys = []
        y = 0
        for flag in flags:
            if flag & 0x04:
                step = g[pos]
                pos += 1
                y += step if flag & 0x20 else -step
            elif flag & 0x20:
                pass
            else:
                y += _i16(g, pos)
                pos += 2
            ys.append(y)
        points = [
            (xs[i], ys[i], bool(flags[i] & 0x01)) for i in range(point_total)
        ]
        out = []
        begin = 0
        for last in end_pts:
            out.extend(_contour_segments(points[begin:last + 1]))
            begin = last + 1
        return out

    def _compound_outline(self, g, depth):
        pos = 10
        contours = []
        while True:
            flags = _u16(g, pos)
            comp = _u16(g, pos + 2)
            pos += 4
            if flags & 0x0001:
                dx = _i16(g, pos)
                dy = _i16(g, pos + 2)
                pos += 4
            else:
                dx = struct.unpack_from(">b", g, pos)[0]
                dy = struct.unpack_from(">b", g, pos + 1)[0]
                pos += 2
            if flags & 0x0008:
                s = _i16(g, pos) / 16384.0
                pos += 2
                a, b, c, d = s, 0.0, 0.0, s
            elif flags & 0x0040:
                a = _i16(g, pos) / 16384.0
                d = _i16(g, pos + 2) / 16384.0
                pos += 4
                b, c = 0.0, 0.0
            elif flags & 0x0080:
                a = _i16(g, pos) / 16384.0
                b = _i16(g, pos + 2) / 16384.0
                c = _i16(g, pos + 4) / 16384.0
                d = _i16(g, pos + 6) / 16384.0
                pos += 8
            else:
                a, b, c, d = 1.0, 0.0, 0.0, 1.0
            if flags & 0x0800:
                dx = dx * a
                dy = dy * d
            for contour in self.outline_segments(comp, depth + 1):
                moved = []
                for (x0, y0, x1, y1) in contour:
                    moved.append(
                        (
                            a * x0 + c * y0 + dx,
                            b * x0 + d * y0 + dy,
                            a * x1 + c * y1 + dx,
                            b * x1 + d * y1 + dy,
                        )
                    )
                contours.append(moved)
            if not (flags & 0x0020):
                break
        return contours


def _mid(p, q):
    return ((p[0] + q[0]) / 2.0, (p[1] + q[1]) / 2.0)


def _flatten_quad(p0, ctrl, p1, out, tolerance=6.0, depth=0):
    """Split a quadratic Bezier into short straight pieces."""
    mx = (p0[0] + 2 * ctrl[0] + p1[0]) / 4.0
    my = (p0[1] + 2 * ctrl[1] + p1[1]) / 4.0
    chord_x = p1[0] - p0[0]
    chord_y = p1[1] - p0[1]
    chord_len = (chord_x * chord_x + chord_y * chord_y) ** 0.5
    if chord_len == 0:
        dev = ((ctrl[0] - p0[0]) ** 2 + (ctrl[1] - p0[1]) ** 2) ** 0.5
    else:
        dev = abs(
            (mx - p0[0]) * chord_y - (my - p0[1]) * chord_x
        ) / chord_len
    if dev <= tolerance or depth >= 8:
        out.append((p0[0], p0[1], p1[0], p1[1]))
        return
    q0 = _mid(p0, ctrl)
    q1 = _mid(ctrl, p1)
    mid = _mid(q0, q1)
    _flatten_quad(p0, q0, mid, out, tolerance, depth + 1)
    _flatten_quad(mid, q1, p1, out, tolerance, depth + 1)


def _contour_segments(points):
    """Turn one contour's points into straight segments.

    Off-curve points are quadratic control points; two off-curve
    points in a row imply an on-curve point at their midpoint.
    Returns a list of contours, each a list of (x0, y0, x1, y1).
    """
    n = len(points)
    if n < 2:
        return []
    expanded = []
    for i in range(n):
        expanded.append(points[i])
        nxt = points[(i + 1) % n]
        if not points[i][2] and not nxt[2]:
            mx, my = _mid(points[i], nxt)
            expanded.append((mx, my, True))
    m = len(expanded)
    first_on = None
    for i in range(m):
        if expanded[i][2]:
            first_on = i
            break
    if first_on is None:
        return []
    start = expanded[first_on][:2]
    segments = []
    cursor = start
    # Walk the loop exactly once: each on-curve point consumes one
    # step, each off-curve point plus its following on-curve point
    # consumes two, so the walk ends after m steps. (A plain
    # "until i wraps back" test can skip the start index when the last
    # step jumps by two, and loop forever.)
    steps = 0
    i = (first_on + 1) % m
    while steps < m:
        p = expanded[i]
        if p[2]:
            segments.append((cursor[0], cursor[1], p[0], p[1]))
            cursor = p[:2]
            i = (i + 1) % m
            steps += 1
        else:
            nxt = expanded[(i + 1) % m]
            piece = []
            _flatten_quad(cursor, p[:2], nxt[:2], piece)
            segments.extend(piece)
            cursor = nxt[:2]
            i = (i + 2) % m
            steps += 2
    return [segments]


# ------------------------------------------------------------ rasterizing
SUBROWS = 4  # vertical supersampling steps per pixel row


class GlyphCache:
    """Renders each (face, size, codepoint) once and keeps the bitmap."""

    def __init__(self):
        self.store = {}

    def fetch(self, face, size, codepoint):
        key = (id(face), size, codepoint)
        hit = self.store.get(key)
        if hit is not None:
            return hit
        made = self._render(face, size, codepoint)
        self.store[key] = made
        return made

    def _render(self, face, size, codepoint):
        glyph_id = face.glyph_index(codepoint)
        advance = face.advance(glyph_id) * size / face.units_per_em
        contours = face.outline_segments(glyph_id)
        if not contours:
            return (b"", 0, 0, 0, 0, advance)
        scale = size / face.units_per_em
        flat = []
        for contour in contours:
            for (x0, y0, x1, y1) in contour:
                flat.append((x0 * scale, -y0 * scale, x1 * scale, -y1 * scale))
        xs = [s[0] for s in flat] + [s[2] for s in flat]
        ys = [s[1] for s in flat] + [s[3] for s in flat]
        left = int(min(xs) // 1)
        top = int(min(ys) // 1)
        right = int(max(xs) // 1) + 1
        bottom = int(max(ys) // 1) + 1
        width = right - left
        height = bottom - top
        cover = [0.0] * (width * height)
        for row in range(height):
            for sub in range(SUBROWS):
                y = top + row + (sub + 0.5) / SUBROWS
                hits = []
                for (x0, y0, x1, y1) in flat:
                    if (y0 <= y < y1) or (y1 <= y < y0):
                        xi = x0 + (y - y0) * (x1 - x0) / (y1 - y0)
                        hits.append((xi, 1 if y1 > y0 else -1))
                if not hits:
                    continue
                hits.sort()
                winding = 0
                prev_x = None
                for xi, direction in hits:
                    if winding != 0 and prev_x is not None:
                        lo = max(prev_x, left)
                        hi = min(xi, right)
                        first = int(lo // 1)
                        last = int(hi // 1)
                        for col in range(first, last + 1):
                            cell_lo = max(lo, float(col))
                            cell_hi = min(hi, float(col + 1))
                            if cell_hi > cell_lo:
                                cover[row * width + (col - left)] += (
                                    cell_hi - cell_lo
                                ) / SUBROWS
                    winding += direction
                    prev_x = xi
        alpha = bytes(
            max(0, min(255, int(round(v * 255)))) for v in cover
        )
        return (alpha, width, height, left, top, advance)


class Pen:
    """Draws text with a Face at one pixel size, via a GlyphCache."""

    def __init__(self, cache, face, size):
        self.cache = cache
        self.face = face
        self.size = size

    def width(self, text):
        total = 0.0
        for ch in text:
            total += self.cache.fetch(self.face, self.size, ord(ch))[5]
        return total

    def draw(self, sheet, x, baseline, text, color):
        cursor = float(x)
        for ch in text:
            alpha, w, h, left, top, adv = self.cache.fetch(
                self.face, self.size, ord(ch)
            )
            if w > 0 and h > 0:
                sheet.stamp(
                    alpha, w, h, int(round(cursor)) + left,
                    int(round(baseline)) + top, color,
                )
            cursor += adv
        return cursor

    def flow(self, text, max_width):
        """Greedy word wrap; returns a list of lines."""
        lines = []
        current = ""
        for word in text.split(" "):
            trial = (current + " " + word).strip()
            if self.width(trial) <= max_width or not current:
                current = trial
            else:
                lines.append(current)
                current = word
        if current:
            lines.append(current)
        return lines


def load_faces():
    return {
        "serif": Face(FONT_DIR / "DejaVuSerif.ttf"),
        "serif_b": Face(FONT_DIR / "DejaVuSerif-Bold.ttf"),
        "sans": Face(FONT_DIR / "DejaVuSans.ttf"),
        "sans_b": Face(FONT_DIR / "DejaVuSans-Bold.ttf"),
    }


# ------------------------------------------------------------------ layout
def paint_centered(sheet, pen, baseline, text, color):
    x = (PAGE_W - pen.width(text)) / 2.0
    pen.draw(sheet, x, baseline, text, color)


def paint_para(sheet, pen, x, baseline, text, max_w, leading, color):
    """Draw a wrapped paragraph; return the next baseline slot below it."""
    y = baseline
    for line in pen.flow(text, max_w):
        pen.draw(sheet, x, y, line, color)
        y += leading
    return y


LEAD_BODY = (
    "United Nations climate talks in Antalya ended on Sunday with no "
    "political deal, the first such failure since Copenhagen in 2009. "
    "The final draft left out any mention of fossil fuels. The European "
    "Union refused to back it, while Saudi Arabia and other big oil "
    "producers objected to naming fossil fuels. UN chief Antonio "
    "Guterres said he was deeply disappointed."
)

PANELS = [
    (
        "THE GULF  |  HORMUZ",
        "GULF WAR HEATS UP",
        "Houthi drones and missiles hit Saudi Arabia for a third day in "
        "a row on Sunday; all were intercepted. Iran's Revolutionary "
        "Guard says it destroyed two Patriot radars at a US base in "
        "Bahrain. At least 25 tankers have been struck in or near the "
        "Strait of Hormuz in a week, and Gulf oil flows have dropped "
        "sharply.",
    ),
    (
        "SPACE  |  MERCURY",
        "BEPICOLOMBO REACHES MERCURY",
        "After an eight-year trip, the ESA and JAXA spacecraft slipped "
        "into orbit around Mercury on Saturday, only the second mission "
        "ever to do so after NASA's MESSENGER. A software fault cut a "
        "thruster burn short on Sunday, but the craft is safe. Science "
        "work starts in April 2027.",
    ),
    (
        "UKRAINE  |  THE BALTIC",
        "RUSSIAN SHIP STILL BURNING",
        "A Russian cargo ship was still on fire off Finland after an "
        "attack, as Ukrainian drones struck and at least 14 people were "
        "reported missing after a Russian drone hit a building near "
        "Kyiv. In Indonesia, a factory fire left 7 dead and 50 missing.",
    ),
]

ALSO = [
    ("NEPAL - INDIA", "PM Balendra Shah meets Modi in New Delhi"),
    ("WASHINGTON", "Democrats win a historic House majority, 258 seats"),
    ("MARKETS", "Anthropic's Nasdaq debut is the biggest IPO yet"),
    ("CRICKET", "India posts a record 720 for 9 in Wellington"),
]


def paint_masthead(sheet, pens):
    paint_centered(
        sheet, pens["title"], 92, "THE WORLD IN ONE DAY", INK
    )
    sheet.fill_hline(MARGIN, PAGE_W - MARGIN, 108, 3, RULE)
    sheet.fill_hline(MARGIN, PAGE_W - MARGIN, 113, 1, RULE)
    paint_centered(
        sheet, pens["date"], 149, "MONDAY, 23 NOVEMBER 2026", RED
    )
    paint_centered(
        sheet,
        pens["tag"],
        174,
        "The whole world, in one picture  |  All stories verified "
        "23 November 2026",
        GREY,
    )


def paint_lead(sheet, pens, top):
    kicker = pens["kick"]
    kicker.draw(sheet, MARGIN, top + 22, "CLIMATE  |  ANTALYA, TURKIYE", RED)
    head = pens["head"]
    head.draw(sheet, MARGIN, top + 80, "COP31 COLLAPSES", INK)
    head.draw(sheet, MARGIN, top + 140, "WITHOUT A DEAL", INK)
    rule_y = top + 152
    sheet.fill_hline(MARGIN, PAGE_W - MARGIN, rule_y, 1, RULE)
    body = pens["body"]
    return paint_para(
        sheet, body, MARGIN, rule_y + 30, LEAD_BODY, CONTENT_W, 26, INK
    )


def paint_panels(sheet, pens, top):
    gap = 24
    col_w = (CONTENT_W - 2 * gap) // 3
    kick = pens["col_kick"]
    head = pens["col_head"]
    body = pens["col_body"]
    deepest = top
    for i, (kicker, headline, text) in enumerate(PANELS):
        x = MARGIN + i * (col_w + gap)
        sheet.fill_rect(x, top, col_w, 5, RED)
        y = top + 33
        kick.draw(sheet, x, y, kicker, RED)
        y += 30
        for line in head.flow(headline, col_w):
            head.draw(sheet, x, y, line, INK)
            y += 27
        y += 4
        y = paint_para(sheet, body, x, y, text, col_w, 22, INK)
        deepest = max(deepest, y)
        if i < 2:
            sheet.fill_rect(
                x + col_w + gap // 2, top + 10, 1, 300, RULE
            )
    return deepest


def paint_also_today(sheet, pens, top):
    sheet.fill_hline(MARGIN, PAGE_W - MARGIN, top, 3, RULE)
    pens["also_title"].draw(sheet, MARGIN, top + 30, "ALSO TODAY", RED)
    gap = 20
    col_w = (CONTENT_W - 3 * gap) // 4
    kick = pens["also_kick"]
    body = pens["also_body"]
    y = top + 60
    deepest = y
    for i, (kicker, text) in enumerate(ALSO):
        x = MARGIN + i * (col_w + gap)
        kick.draw(sheet, x, y, kicker, GREY)
        end = paint_para(sheet, body, x, y + 22, text, col_w, 19, INK)
        deepest = max(deepest, end)
    return deepest


def paint_footer(sheet, pens):
    paint_centered(
        sheet,
        pens["foot"],
        PAGE_H - 30,
        "THE WORLD IN ONE DAY  |  Monday 23 November 2026  |  COP31  -  "
        "Hormuz  -  Mercury  -  Kyiv",
        GREY,
    )


def build_pens(cache, faces):
    return {
        "title": Pen(cache, faces["serif_b"], 62),
        "date": Pen(cache, faces["sans_b"], 25),
        "tag": Pen(cache, faces["sans"], 16),
        "kick": Pen(cache, faces["sans_b"], 19),
        "head": Pen(cache, faces["serif_b"], 54),
        "body": Pen(cache, faces["sans"], 20),
        "col_kick": Pen(cache, faces["sans_b"], 16),
        "col_head": Pen(cache, faces["sans_b"], 23),
        "col_body": Pen(cache, faces["sans"], 17),
        "also_title": Pen(cache, faces["sans_b"], 20),
        "also_kick": Pen(cache, faces["sans_b"], 14),
        "also_body": Pen(cache, faces["sans"], 15),
        "foot": Pen(cache, faces["sans"], 14),
    }


def build_page():
    cache = GlyphCache()
    faces = load_faces()
    pens = build_pens(cache, faces)
    sheet = Sheet(PAGE_W, PAGE_H, PAPER)
    paint_masthead(sheet, pens)
    y = paint_lead(sheet, pens, 190)
    sheet.fill_hline(MARGIN, PAGE_W - MARGIN, y + 8, 2, RULE)
    y = paint_panels(sheet, pens, y + 22)
    y = paint_also_today(sheet, pens, y + 10)
    paint_footer(sheet, pens)
    return sheet


def main():
    sheet = build_page()
    out_dir = os.environ.get("MAKEFUN_OUTPUT_DIR") or "/output"
    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, "entry.png")
    with open(out_path, "wb") as fh:
        fh.write(sheet.png_bytes())
    print("wrote", out_path, (PAGE_W, PAGE_H))


if __name__ == "__main__":
    main()
