"""Preview every scene crop as a labeled contact sheet (no encoding)."""
import os
from PIL import Image, ImageDraw, ImageFont
import rr_render as R

os.makedirs(R.SCN, exist_ok=True)
cells = []
for clip in R.CLIPS:
    for i, sc in enumerate(clip["scenes"]):
        p = f"{R.SCN}/prev_{clip['id']}_{i:02d}.png"
        if sc["kind"] == "plate":
            R.plate_still(sc["name"], sc["cy"], sc["w"], p)
            label = f"{clip['id'][:7]} #{i} {sc['name']} cy{sc['cy']} w{sc['w']}"
        else:
            R.sizzle_still(sc["t_in"], p)
            label = f"{clip['id'][:7]} #{i} SZ {sc['t_in']}s"
        cells.append((p, label))

cols, tw = 5, 320
th = int(tw * R.PH / R.PW)
rows = (len(cells) + cols - 1) // cols
sheet = Image.new("RGB", (cols * tw, rows * (th + 24)), (24, 24, 28))
d = ImageDraw.Draw(sheet)
f = ImageFont.truetype(R.MONTO, 13)
for i, (p, label) in enumerate(cells):
    x, y = (i % cols) * tw, (i // cols) * (th + 24)
    sheet.paste(Image.open(p).convert("RGB").resize((tw, th), Image.LANCZOS), (x, y + 24))
    d.text((x + 4, y + 5), label, font=f, fill=(255, 255, 255))
sheet.save(f"{R.SCN}/_contact.png")
print("cells", len(cells), "->", f"{R.SCN}/_contact.png")
