"""Generate a shareable Open Graph score card (1200x630 PNG) for an occupation.
Pure Pillow, no system libraries, so it builds on the slim Python image. The card
shows the brand, job title, the exposure score (coloured by level), an exposure bar,
and the timeline band, so a shared link renders a real visual card, not just text."""

import io
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

_FONTS = Path(__file__).resolve().parent / "static" / "fonts"

NAVY = (11, 26, 46)
PANEL = (23, 42, 66)
WHITE = (255, 255, 255)
ORANGE = (243, 163, 95)
MUTED = (159, 176, 196)
GREEN = (63, 182, 168)
AMBER = (231, 176, 72)
RED = (224, 85, 58)


def _font(bold, size):
    name = "DejaVuSans-Bold.ttf" if bold else "DejaVuSans.ttf"
    return ImageFont.truetype(str(_FONTS / name), size)


def _level_color(score):
    if score >= 66:
        return RED
    if score >= 40:
        return AMBER
    return GREEN


def _wrap(draw, text, font, max_w, max_lines=2):
    words, lines, cur = text.split(), [], ""
    for w in words:
        t = (cur + " " + w).strip()
        if draw.textlength(t, font=font) <= max_w:
            cur = t
        else:
            if cur:
                lines.append(cur)
            cur = w
        if len(lines) == max_lines:
            break
    if cur and len(lines) < max_lines:
        lines.append(cur)
    if len(lines) == max_lines and draw.textlength(lines[-1] + "...", font=font) <= max_w + 60:
        pass
    return lines[:max_lines]


def render_card(title, score, band_label):
    """Return PNG bytes for the given occupation title, 0-100 score, and timeline band label."""
    W, H = 1200, 630
    score = int(round(score or 0))
    img = Image.new("RGB", (W, H), NAVY)
    d = ImageDraw.Draw(img)
    pad = 72

    # brand
    bf = _font(True, 44)
    d.text((pad, 52), "Job", font=bf, fill=WHITE)
    jw = d.textlength("Job", font=bf)
    d.text((pad + jw, 52), "Break", font=bf, fill=ORANGE)

    # job title (up to 2 lines)
    tf = _font(True, 58)
    lines = _wrap(d, title, tf, W - 2 * pad, 2)
    y = 150
    for ln in lines:
        d.text((pad, y), ln, font=tf, fill=WHITE)
        y += 70

    # big score, coloured by level
    sc = _level_color(score)
    nf = _font(True, 168)
    y += 18
    num = str(score)
    d.text((pad, y), num, font=nf, fill=sc)
    nw = d.textlength(num, font=nf)
    d.text((pad + nw + 26, y + 34), "of 100", font=_font(False, 44), fill=MUTED)
    d.text((pad + nw + 26, y + 92), "automation exposure", font=_font(False, 38), fill=MUTED)

    # exposure bar
    bar_y = y + 196
    bar_w = W - 2 * pad
    d.rounded_rectangle([pad, bar_y, pad + bar_w, bar_y + 24], radius=12, fill=PANEL)
    fill_w = int(bar_w * min(100, max(0, score)) / 100)
    if fill_w > 0:
        d.rounded_rectangle([pad, bar_y, pad + max(24, fill_w), bar_y + 24], radius=12, fill=sc)

    # timeline band + footer
    if band_label:
        d.text((pad, bar_y + 44), band_label, font=_font(True, 38), fill=WHITE)
    d.text((pad, H - 68), "See your job's timeline at JobBreak", font=_font(False, 34), fill=ORANGE)

    buf = io.BytesIO()
    img.save(buf, "PNG")
    return buf.getvalue()
