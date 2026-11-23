#!/usr/bin/env python3
"""THE WORLD IN ONE DAY - Monday 23 November 2026.

Draws a one-page newspaper front page summing up 23 November 2026's
world news as a single 1024x1024 PNG. Deterministic, no network,
fonts vendored in repo/fonts/ (never /usr/share/fonts).
"""
import os
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

BASE = Path(__file__).resolve().parent
FONTS = BASE / "fonts"

W, H = 1024, 1024
PAPER = (248, 244, 233)
INK = (22, 22, 22)
RED = (164, 30, 34)
GREY = (90, 86, 78)
RULE = (60, 58, 52)

MARGIN = 30
CONTENT_W = W - 2 * MARGIN


def font(name, size):
    return ImageFont.truetype(str(FONTS / name), size)


SERIF = "DejaVuSerif.ttf"
SERIF_B = "DejaVuSerif-Bold.ttf"
SANS = "DejaVuSans.ttf"
SANS_B = "DejaVuSans-Bold.ttf"


def wrap(draw, text, fnt, max_w):
    """Greedy word wrap; returns list of lines."""
    lines, cur = [], ""
    for word in text.split(" "):
        trial = (cur + " " + word).strip()
        if draw.textlength(trial, font=fnt) <= max_w:
            cur = trial
        else:
            if cur:
                lines.append(cur)
            cur = word
    if cur:
        lines.append(cur)
    return lines


def draw_wrapped(draw, x, y, text, fnt, max_w, fill, leading):
    lines = wrap(draw, text, fnt, max_w)
    for line in lines:
        draw.text((x, y), line, font=fnt, fill=fill)
        y += leading
    return y


def rule(draw, x0, x1, y, width=2, fill=RULE):
    draw.line([(x0, y), (x1, y)], fill=fill, width=width)


def masthead(draw):
    title = "THE WORLD IN ONE DAY"
    f_title = font(SERIF_B, 62)
    tw = draw.textlength(title, font=f_title)
    draw.text(((W - tw) / 2, 30), title, font=f_title, fill=INK)
    rule(draw, MARGIN, W - MARGIN, 108, width=3)
    rule(draw, MARGIN, W - MARGIN, 113, width=1)
    f_date = font(SANS_B, 25)
    date = "MONDAY, 23 NOVEMBER 2026"
    dw = draw.textlength(date, font=f_date)
    draw.text(((W - dw) / 2, 124), date, font=f_date, fill=RED)
    f_tag = font(SANS, 16)
    tag = "The whole world, in one picture  |  All stories verified 23 November 2026"
    gw = draw.textlength(tag, font=f_tag)
    draw.text(((W - gw) / 2, 158), tag, font=f_tag, fill=GREY)


def lead_panel(draw):
    y0 = 196
    kicker = "CLIMATE  |  ANTALYA, TURKIYE"
    f_kick = font(SANS_B, 19)
    draw.text((MARGIN, y0), kicker, font=f_kick, fill=RED)
    y = y0 + 30
    f_head = font(SERIF_B, 54)
    for line in ["COP31 COLLAPSES", "WITHOUT A DEAL"]:
        draw.text((MARGIN, y), line, font=f_head, fill=INK)
        y += 62
    y += 6
    rule(draw, MARGIN, W - MARGIN, y, width=1)
    y += 14
    body = (
        "United Nations climate talks in Antalya ended on Sunday with no political "
        "agreement - the first failure since Copenhagen in 2009. The final draft "
        "did not mention fossil fuels at all. The EU refused to endorse it, while "
        "Saudi Arabia and big oil producers objected to naming fossil fuels. "
        "UN chief Antonio Guterres said he was \u201cdeeply disappointed\u201d."
    )
    y = draw_wrapped(draw, MARGIN, y, body, font(SANS, 20), CONTENT_W, INK, 27)
    return y


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


def columns(draw, y0):
    gap = 24
    col_w = (CONTENT_W - 2 * gap) // 3
    f_kick = font(SANS_B, 16)
    f_head = font(SANS_B, 23)
    f_body = font(SANS, 17)
    for i, (kicker, headline, body) in enumerate(PANELS):
        x = MARGIN + i * (col_w + gap)
        draw.rectangle([x, y0, x + col_w, y0 + 5], fill=RED)
        y = y0 + 16
        draw.text((x, y), kicker, font=f_kick, fill=RED)
        y += 26
        y = draw_wrapped(draw, x, y, headline, f_head, col_w, INK, 28)
        y += 8
        draw_wrapped(draw, x, y, body, f_body, col_w, INK, 23)
        if i < 2:
            draw.line(
                [(x + col_w + gap // 2, y0 + 10), (x + col_w + gap // 2, y0 + 300)],
                fill=RULE,
                width=1,
            )
    return y0 + 312


ALSO = [
    ("NEPAL - INDIA", "PM Balendra Shah meets Modi in New Delhi"),
    ("WASHINGTON", "Democrats take historic House majority - 258 seats"),
    ("MARKETS", "Anthropic's Nasdaq debut is the biggest IPO yet"),
    ("CRICKET", "India smashes record 720/9 declared in Wellington Test"),
]


def also_today(draw, y0):
    rule(draw, MARGIN, W - MARGIN, y0, width=3)
    f_title = font(SANS_B, 20)
    draw.text((MARGIN, y0 + 12), "ALSO TODAY", font=f_title, fill=RED)
    y = y0 + 46
    gap = 20
    col_w = (CONTENT_W - 3 * gap) // 4
    f_kick = font(SANS_B, 14)
    f_body = font(SANS, 15)
    for i, (kicker, text) in enumerate(ALSO):
        x = MARGIN + i * (col_w + gap)
        draw.text((x, y), kicker, font=f_kick, fill=GREY)
        draw_wrapped(draw, x, y + 22, text, f_body, col_w, INK, 20)
    return y + 96


def main():
    img = Image.new("RGB", (W, H), PAPER)
    draw = ImageDraw.Draw(img)
    masthead(draw)
    y = lead_panel(draw)
    rule(draw, MARGIN, W - MARGIN, y + 12, width=2)
    y = columns(draw, y + 28)
    y = also_today(draw, y + 14)
    f_foot = font(SANS, 14)
    foot = "THE WORLD IN ONE DAY  |  Monday 23 November 2026  |  COP31  -  Hormuz  -  Mercury  -  Kyiv"
    fw = draw.textlength(foot, font=f_foot)
    draw.text(((W - fw) / 2, H - 30), foot, font=f_foot, fill=GREY)
    out_dir = os.environ.get("MAKEFUN_OUTPUT_DIR") or "/output"
    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, "entry.png")
    img.save(out_path, "PNG", optimize=True)
    print("wrote", out_path, img.size)


if __name__ == "__main__":
    main()
