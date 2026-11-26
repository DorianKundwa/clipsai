"""Contact sheet of candidate sizzle frames with the 1080x948 panel crop overlaid."""
import subprocess
from PIL import Image, ImageDraw, ImageFont

SZ = "work/reddit_reviews_assets/Sizzle Video.mp4"
MONTO = "openshorts/fonts/Montserrat-ExtraBold.ttf"
CANDS = [(0.9, 250), (1.4, 250), (2.6, 250), (3.6, 250), (5.4, 300), (6.4, 300),
         (11.6, 200), (12.3, 200), (20.4, 700), (21.4, 700), (24.6, 970), (25.4, 970)]

cells, tw = [], 210
th = int(tw * 1920 / 1080)
for t, cy in CANDS:
    p = f"work/rr_scenes/_sz_{t}.png"
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-ss", f"{t}", "-i", SZ,
                    "-frames:v", "1", p], check=True)
    im = Image.open(p).convert("RGB")
    d = ImageDraw.Draw(im)
    d.rectangle([0, cy, 1079, cy + 948], outline=(255, 0, 255), width=8)
    d.rectangle([65, 270, 930, 1240], outline=(0, 255, 255), width=4)
    cells.append((im.resize((tw, th)), t, cy))

cols = 6
rows = (len(cells) + cols - 1) // cols
sheet = Image.new("RGB", (cols * tw, rows * (th + 22)), (20, 20, 24))
ds = ImageDraw.Draw(sheet)
f = ImageFont.truetype(MONTO, 13)
for i, (im, t, cy) in enumerate(cells):
    x, y = (i % cols) * tw, (i // cols) * (th + 22)
    sheet.paste(im, (x, y + 22))
    ds.text((x + 4, y + 4), f"t={t}s cy={cy}", font=f, fill=(255, 255, 255))
sheet.save("work/rr_scenes/_szcheck.png")
print("ok", sheet.size)
