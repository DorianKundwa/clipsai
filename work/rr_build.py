"""Rebuild Reddit Reviews review pages with generic, brand-free copy.

Keeps the authentic phone chrome / status bar / chair iconography from the official
screenshots, but repaints the content column so that:
  * no brand or product names appear (generic: "this robot vacuum")
  * no prices and no "Where to buy" / retailer block
  * no u/ handles, no r/ community tags
Every string drawn here is authored in this file, so the plate itself is auditable.
"""
import os
from PIL import Image, ImageDraw, ImageFont

SRC = "work/reddit_reviews_assets"
OUT = "work/rr_plates"
W, H = 990, 1884

UI = "/c/Windows/Fonts/segoeui.ttf"
UIB = "/c/Windows/Fonts/segoeuib.ttf"
UISB = "/c/Windows/Fonts/segoeuisl.ttf"
MONTO = "openshorts/fonts/Montserrat-ExtraBold.ttf"

INK = (26, 26, 26)
SUB = (96, 100, 106)
LINE = (232, 234, 237)
GREEN = (24, 133, 62)
GOLD = (176, 136, 24)
GREY = (140, 152, 163)
CARD = (245, 246, 248)


def F(path, size):
    return ImageFont.truetype(path, size)


def wrap(d, text, font, max_w):
    out, cur = [], ""
    for word in text.split():
        t = (cur + " " + word).strip()
        if d.textlength(t, font=font) <= max_w or not cur:
            cur = t
        else:
            out.append(cur)
            cur = word
    if cur:
        out.append(cur)
    return out


def para(d, text, font, x, y, max_w, lh, fill=INK):
    for line in wrap(d, text, font, max_w):
        d.text((x, y), line, font=font, fill=fill)
        y += lh
    return y


def rr(d, box, r, fill):
    d.rounded_rectangle(box, radius=r, fill=fill)


def tag_icon(d, x, y, s=34):
    """Neutral 'review tag' glyph (own drawing, no borrowed artwork)."""
    d.rounded_rectangle([x, y, x + s, y + s * 0.86], radius=7, outline=(110, 118, 128), width=4)
    d.polygon([(x + s * 0.30, y + s * 0.86), (x + s * 0.30, y + s * 1.10),
               (x + s * 0.52, y + s * 0.86)], fill=(110, 118, 128))
    d.line([x + 7, y + s * 0.45, x + s * 0.32, y + s * 0.45], fill=(110, 118, 128), width=4)


def smiley(d, x, y, s=40, col=(24, 133, 62)):
    d.ellipse([x, y, x + s, y + s], outline=col, width=4)
    d.ellipse([x + s * 0.30, y + s * 0.34, x + s * 0.40, y + s * 0.44], fill=col)
    d.ellipse([x + s * 0.60, y + s * 0.34, x + s * 0.70, y + s * 0.44], fill=col)
    d.arc([x + s * 0.28, y + s * 0.44, x + s * 0.72, y + s * 0.78], 20, 160, fill=col, width=4)


def product_tile(d, x, y, s=180):
    rr(d, [x, y, x + s, y + s], 18, CARD)
    d.rounded_rectangle([x, y, x + s, y + s], radius=18, outline=(233, 235, 238), width=3)
    # generic "reviewed item" glyph: a plain box with a check tag
    cx, cy = x + s / 2, y + s / 2
    d.rounded_rectangle([cx - 40, cy - 34, cx + 40, cy + 30], radius=8,
                        outline=(158, 168, 178), width=4)
    d.line([cx - 40, cy - 8, cx + 40, cy - 8], fill=(158, 168, 178), width=4)
    d.line([cx - 40, cy + 12, cx - 12, cy + 12], fill=(158, 168, 178), width=4)


def sentiment_bar(d, x, y, w=770, h=16):
    rr(d, [x, y, x + w, y + h], h // 2, (200, 205, 210))
    rr(d, [x, y, x + int(w * 0.79), y + h], h // 2, GREEN)
    rr(d, [x + int(w * 0.79) + 6, y, x + int(w * 0.885), y + h], h // 2, (150, 170, 185))
    rr(d, [x + int(w * 0.885) + 6, y, x + w, y + h], h // 2, GOLD)


COMMENTS = {
    "vacuum": [
        ("ran this daily for three years and it still handles the hard floors "
         "without a single dropout.", 64),
        ("quiet enough to run while the kids nap, and the mop bit is the part "
         "nobody mentions.", 41),
    ],
    "tv": [
        ("the art mode is the whole reason — friends ask where the print came "
         "from before they spot it's a screen.", 64),
        ("bright room, no glare problems, and the frame looks like actual oak. "
         "dark scenes do soften a little.", 38),
    ],
    "steam": [
        ("dumplings on top, veg underneath, dinner sorted in one go. it gets "
         "used way more than i expected.", 64),
        ("refill the reservoir mid-cook on big batches and it's flawless. best "
         "counter upgrade this year.", 29),
    ],
    "phone": [
        ("gets me through a full day of calls, scrolling and music without "
         "reaching for a charger.", 64),
        ("battery still has life at bedtime even after a day of photos and "
         "video. low light is the one weak spot.", 41),
    ],
}


def build_page(base_file, kind, crumb, title, blurb, summary, pros, mentions):
    img = Image.open(f"{SRC}/{base_file}").convert("RGB")
    d = ImageDraw.Draw(img)
    # keep chrome: status bar (y<170), back/share (170..300), breadcrumb (300..360)
    d.rectangle([60, 368, 935, 1860], fill=(255, 255, 255))

    # authentic breadcrumb is kept from the source screenshot (category only)
    product_tile(d, 113, 380)
    d.text((322, 392), title, font=F(UISB, 42), fill=(20, 20, 22))
    d.text((322, 452), f"{mentions} mentions", font=F(UI, 28), fill=GREY)
    d.line([113, 470, 293, 470], fill=(0, 0, 0, 0))
    # small community row (own drawing: three neutral chips + count)
    for i, col in enumerate([(255, 186, 0), (255, 95, 60), (120, 190, 90)]):
        d.ellipse([322 + i * 26, 498, 322 + i * 26 + 26, 524], fill=col)
    d.text((322 + 84, 496), "across Reddit communities", font=F(UI, 27), fill=GREY)

    d.line([113, 596, 878, 596], fill=LINE, width=2)
    y = para(d, blurb, F(UI, 32), 113, 622, 770, 44, fill=(48, 50, 54))
    d.line([113, 740, 878, 740], fill=(222, 230, 236), width=10)

    tag_icon(d, 116, 776)
    d.text((166, 772), "Review", font=F(UI, 31), fill=(90, 94, 100))
    d.text((113, 838), "What people are saying", font=F(UIB, 44), fill=(15, 15, 17))
    y = para(d, summary, F(UI, 32), 113, 906, 770, 44, fill=(40, 42, 46))

    sentiment_bar(d, 113, y + 26)
    d.text((113, y + 58), "Positive", font=F(UIB, 29), fill=GREEN)
    d.text((242, y + 58), f"· {mentions} mentions", font=F(UI, 29), fill=GREY)
    d.line([113, y + 118, 878, y + 118], fill=LINE, width=2)

    hy = y + 152
    smiley(d, 113, hy + 4)
    d.text((168, hy), pros, font=F(UIB, 33), fill=(20, 20, 22))

    cy = hy + 92
    for i, (text, ups) in enumerate(COMMENTS[kind]):
        fade = i == 1
        col = (150, 154, 160) if fade else (58, 60, 64)
        # avatar = rounded neutral tile (no handle, no community art)
        rr(d, [113, cy + 4, 113 + 52, cy + 56], 26, (232, 235, 238) if not fade else (240, 242, 244))
        d.ellipse([113 + 16, cy + 20, 113 + 36, cy + 40], fill=(206, 210, 216))
        d.line([186, cy + 8, 186, cy + 96], fill=(226, 229, 233), width=4)
        end = para(d, text, F(UI, 31), 206, cy, 668, 42, fill=col)
        d.text((206, end + 6), f"{ups} upvotes", font=F(UI, 26),
               fill=(168, 172, 178) if fade else (140, 146, 152))
        cy = end + 76
    return img


PAGES = {
    "vacuum": dict(
        base_file="Robot_Vacuum_Review_Page.png", crumb="Household Appliances",
        title="this robot vacuum",
        blurb="A robot vacuum and mop with a multifunction dock, built for hard floors "
              "and daily scheduled runs.",
        summary="People love it for reliable hard-floor pickup, quiet cleaning and the "
                "handy mop function, though some say it struggles with dried-on spills.",
        pros="Holds up reliably over multiple years", mentions="488"),
    "tv": dict(
        base_file="Art_TV_Review_Page.png", crumb="Televisions",
        title="this art TV",
        blurb="A 4K mini-LED screen in a natural oak frame, made to display artwork when "
              "it is not playing anything.",
        summary="People love the art display, the oak frame and how bright the picture stays "
                "in sunny rooms, though the matte screen softens contrast in dark scenes.",
        pros="Convincing art display", mentions="438"),
    "steam": dict(
        base_file="Steam_Cooker_Review_Page.png", crumb="Kitchen Appliances",
        title="this steam cooker",
        blurb="A compact electric steamer with stacked baskets for vegetables, dumplings "
              "and one-pot dinners.",
        summary="People love the simple controls, the stacked baskets and dependable results, "
                "though some say the reservoir needs refilling on longer sessions.",
        pros="Cooks entire meals at once", mentions="576"),
    "phone": dict(
        base_file="Smartphone_Review_Page.png", crumb="Mobile & Smart Phones",
        title="this smartphone",
        blurb="A lightweight phone with a bright display and all-day battery, pitched at "
              "everyday use rather than specs.",
        summary="People love the lightweight build, bright display and dependable all-day "
                "battery, though photo fans say low-light shots lose detail.",
        pros="Lasts through the day", mentions="612"),
}


def build_search():
    img = Image.new("RGB", (W, H), (255, 255, 255))
    d = ImageDraw.Draw(img)
    d.rectangle([0, 0, W, H], fill=(255, 255, 255))
    # status bar
    d.text((188, 100), "9:41", font=F(UISB, 44), fill=(15, 15, 17))
    d.rounded_rectangle([368, 78, 622, 152], radius=38, fill=(10, 10, 12))
    # search field
    rr(d, [80, 220, 910, 320], 46, (243, 244, 246))
    d.ellipse([120, 258, 152, 290], outline=(120, 126, 134), width=4)
    d.line([146, 284, 160, 298], fill=(120, 126, 134), width=5)
    d.text((180, 254), "robot vacuum", font=F(UIB, 34), fill=(30, 32, 36))
    d.text((784, 254), "Reviews", font=F(UIB, 30), fill=(255, 69, 0))
    # section label
    d.text((80, 372), "Reddit Reviews", font=F(MONTO, 40), fill=(255, 69, 0))
    d.text((80, 428), "every community take, on one page", font=F(UI, 28), fill=GREY)

    rr(d, [80, 500, 910, 1500], 26, (255, 255, 255))
    d.rounded_rectangle([80, 500, 910, 1500], radius=26, outline=(228, 231, 235), width=3)
    product_tile(d, 120, 540, 150)
    d.text((300, 556), "this robot vacuum", font=F(UISB, 40), fill=(18, 18, 20))
    d.text((300, 606), "488 mentions", font=F(UI, 27), fill=GREY)
    for i, col in enumerate([(255, 186, 0), (255, 95, 60), (120, 190, 90)]):
        d.ellipse([300 + i * 24, 668, 300 + i * 24 + 24, 692], fill=col)
    d.text((380, 666), "from 3 communities", font=F(UI, 26), fill=GREY)

    d.line([120, 730, 870, 730], fill=LINE, width=2)
    tag_icon(d, 120, 762)
    d.text((168, 758), "Review", font=F(UI, 30), fill=(90, 94, 100))
    d.text((120, 820), "What people are saying", font=F(UIB, 42), fill=(15, 15, 17))
    y = para(d, "Users love it for its reliable hard-floor pickup, quiet cleaning and handy "
                "mop function, though some users say it struggles with dried-on spills.",
             F(UI, 31), 120, 886, 730, 43, fill=(40, 42, 46))
    sentiment_bar(d, 120, y + 24, w=740, h=15)
    d.text((120, y + 54), "Positive", font=F(UIB, 28), fill=GREEN)
    d.text((243, y + 54), "· 488 mentions", font=F(UI, 28), fill=GREY)
    d.line([120, y + 112, 870, y + 112], fill=LINE, width=2)
    smiley(d, 120, y + 146)
    d.text((174, y + 142), "Pros", font=F(UIB, 33), fill=(15, 15, 17))
    y = para(d, "reliable hard-floor pickup · quiet runs · mop function included",
             F(UI, 30), 120, y + 196, 730, 42, fill=(40, 42, 46))
    d.text((120, y + 20), "Cons", font=F(UIB, 33), fill=(150, 90, 20))
    para(d, "dried-on spills need a second pass", F(UI, 30), 120, y + 72, 730, 42,
         fill=(40, 42, 46))
    return img


if __name__ == "__main__":
    os.makedirs(OUT, exist_ok=True)
    for kind, cfg in PAGES.items():
        img = build_page(kind=kind, **cfg)
        p = f"{OUT}/{kind}.png"
        img.save(p)
        print("plate", p)
    p = f"{OUT}/search.png"
    build_search().save(p)
    print("plate", p)
