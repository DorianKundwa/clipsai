"""Render hook text cards (1080x1920 RGBA) for each clip."""
import os
from PIL import Image, ImageDraw, ImageFont
from campaign import CLIPS

FONT = "work/ab.ttf"
CARD = (1080, 1920)


def wrap(draw, text, font, max_w):
    words = text.split()
    lines, cur = [], ""
    for w in words:
        trial = (cur + " " + w).strip()
        if draw.textlength(trial, font=font) <= max_w or not cur:
            cur = trial
        else:
            lines.append(cur)
            cur = w
    if cur:
        lines.append(cur)
    return lines


def make_card(text, path):
    img = Image.new("RGBA", CARD, (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    size = 96
    max_w = 880
    while size > 52:
        font = ImageFont.truetype(FONT, size)
        lines = wrap(d, text, font, max_w)
        if len(lines) <= 2:
            break
        size -= 4
    font = ImageFont.truetype(FONT, size)
    lines = wrap(d, text, font, max_w)
    line_h = int(size * 1.14)
    block_h = line_h * len(lines)
    top = 470 - block_h // 2
    for i, line in enumerate(lines):
        w = d.textlength(line, font=font)
        x = (CARD[0] - w) / 2
        y = top + i * line_h
        # soft shadow
        shadow = Image.new("RGBA", CARD, (0, 0, 0, 0))
        sd = ImageDraw.Draw(shadow)
        sd.text((x + 5, y + 7), line, font=font, fill=(0, 0, 0, 165),
                stroke_width=10, stroke_fill=(0, 0, 0, 165))
        from PIL import ImageFilter
        img.alpha_composite(shadow.filter(ImageFilter.GaussianBlur(7)))
        d = ImageDraw.Draw(img)
        d.text((x, y), line, font=font, fill=(255, 255, 255, 255),
               stroke_width=5, stroke_fill=(0, 0, 0, 230))
    # accent rule under the block
    bar_w = 132
    y = top + block_h + 26
    d.rectangle([(CARD[0] - bar_w) / 2, y, (CARD[0] + bar_w) / 2, y + 6],
                fill=(255, 255, 255, 225))
    img.save(path)


if __name__ == "__main__":
    os.makedirs("work/cards", exist_ok=True)
    for c in CLIPS:
        p = f"work/cards/{c['id']}.png"
        make_card(c["hook"], p)
        print("card", p, c["hook"])
