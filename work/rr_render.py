"""Render the four 9:16 Reddit Reviews launch clips.

Layout contract (1080x1920):
  pill band  y 280..460   (hook 0.0-3.5s, callout 4.0-8.5s)   x 84..930
  chip       y 436..484   "Reddit Reviews" every frame        x 84..
  panel      x 80..930, y 494..1240  (all UI / sizzle imagery)
Nothing above y=270, below y=1240 or right of x=930 is ever drawn on.
"""
import json, os, re, subprocess, sys
from PIL import Image, ImageDraw, ImageFilter, ImageFont

ROOT = os.path.dirname(os.path.abspath(__file__))
PLATES = f"{ROOT}/rr_plates"
SIZZLE = f"{ROOT}/reddit_reviews_assets/Sizzle Video.mp4"
SCN = f"{ROOT}/rr_scenes"
OVER = f"{ROOT}/rr_overlays"
AUD = f"{ROOT}/rr_audio"
OUT = f"{ROOT}/../outputs/reddit_reviews_campaign"

W, H, FPS = 1080, 1920, 60
PILL_BAND_Y = 280
CHIP_Y = 436
PANEL = (80, 494, 930, 1240)
PW, PH = PANEL[2] - PANEL[0], PANEL[3] - PANEL[1]   # 850 x 746
PLATE_W, PLATE_H = 990, 1884

MONTO = f"{ROOT}/../openshorts/fonts/Montserrat-ExtraBold.ttf"
EMOJI = "/c/Windows/Fonts/seguiemj.ttf"
WHITE = (255, 255, 255, 255)
ORANGE = (255, 69, 0, 255)
PILL_FILL = (15, 15, 18, 209)
TEXT_PX = 52


def P(dur, name, cy, w=850):
    return {"kind": "plate", "dur": dur, "name": name, "cy": cy, "w": w}


def S(dur, t_in):
    return {"kind": "sizzle", "dur": dur, "t_in": t_in}


CLIPS = [
    dict(id="clip_01_tt", platform="tiktok", angle="Quick reveal",
         hook="reddit just dropped reviews?? \U0001F440",
         callout="Reddit Reviews pulls real pros & cons in one spot",
         audio_start=0.0,
         scenes=[S(1.8, 5.4), P(2.4, "search", 200), P(2.6, "vacuum", 752, 900),
                 P(2.2, "vacuum", 1180, 800), P(2.2, "tv", 700),
                 P(2.4, "steam", 1150, 760), P(2.2, "phone", 800, 820),
                 S(1.6, 20.6), S(1.8, 25.6)]),
    dict(id="clip_02_yt", platform="youtube", angle="Search habit",
         hook="pov: you stop adding 'reddit' to every search",
         callout="new Reddit Reviews shows what real people actually liked",
         audio_start=3.0,
         scenes=[S(2.2, 0.9), P(2.6, "search", 60, 820), P(2.6, "vacuum", 300),
                 P(2.6, "vacuum", 900, 780), P(2.6, "phone", 752, 860),
                 P(2.2, "phone", 1150, 830), S(1.6, 11.0), S(1.6, 25.6)]),
    dict(id="clip_03_tt", platform="tiktok", angle="Holiday gift / home",
         hook="how Reddit Reviews saves holiday gift shopping",
         callout="real pros and cons from Reddit communities",
         audio_start=1.5,
         scenes=[S(2.0, 2.6), P(2.0, "tv", 300, 840), P(2.4, "tv", 752, 880),
                 P(2.2, "tv", 1140, 790), P(2.2, "steam", 730, 830),
                 P(2.2, "steam", 1160, 810), P(2.0, "phone", 480), S(2.6, 20.6)]),
    dict(id="clip_04_yt", platform="youtube", angle="Comment section verdict",
         hook="what reddit really thinks before you pick anything",
         callout="Reddit Reviews puts the whole verdict on one page",
         audio_start=5.0,
         scenes=[P(2.0, "vacuum", 1180, 760), P(2.2, "phone", 1180, 780),
                 P(2.2, "tv", 1180, 780), P(2.2, "steam", 1136, 850),
                 P(2.2, "vacuum", 1050, 800), P(2.2, "phone", 1050, 860),
                 S(1.8, 12.2), S(2.0, 25.6)]),
]

EMOJI_RE = re.compile("[\U0001F000-\U0001FAFF\u2600-\u27BF]")


def run(cmd, ok_msg=None):
    p = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if p.returncode != 0:
        print(p.stderr[-2500:])
        raise SystemExit("failed: " + " ".join(str(c) for c in cmd[:8]))
    if ok_msg:
        print(ok_msg)
    return p


def font(size, path=MONTO):
    return ImageFont.truetype(path, size)


def rich_runs(text):
    out, buf, i = [], "", 0
    while i < len(text):
        ch = text[i]
        if EMOJI_RE.match(ch):
            if buf:
                out.append((buf, False)); buf = ""
            run_em, j = ch, i + 1
            while j < len(text) and text[j] in "\uFE0F\u200D":
                run_em += text[j]; j += 1
            out.append((run_em, True))
            i = j
        else:
            buf += ch; i += 1
    if buf:
        out.append((buf, False))
    return out


def measure(text, f, ef):
    return sum((ef if em else f).getlength(r) for r, em in rich_runs(text))


def draw_rich(d, xy, text, f, ef, fill):
    x, y = xy
    for r, em in rich_runs(text):
        if em:
            d.text((x, y + f.size * 0.14), r, font=ef, embedded_color=True)
            x += ef.getlength(r)
        else:
            d.text((x, y), r, font=f, fill=fill)
            x += f.getlength(r)


def wrap_rich(text, f, ef, max_w):
    words, lines, cur = text.split(" "), [], ""
    for w in words:
        t = (cur + " " + w).strip()
        if measure(t, f, ef) <= max_w or not cur:
            cur = t
        else:
            lines.append(cur); cur = w
    if cur:
        lines.append(cur)
    return lines


def pill(text, out_path, y=PILL_BAND_Y, size=TEXT_PX):
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    f, ef = font(size), font(size, EMOJI)
    pad_x, pad_y, lh = 34, 20, int(size * 1.16)
    lines = wrap_rich(text, f, ef, 846 - 2 * pad_x)
    tw = max(measure(l, f, ef) for l in lines)
    bh = lh * len(lines) + 2 * pad_y
    box = [84, y, 84 + tw + 2 * pad_x, y + bh]
    shadow = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    ImageDraw.Draw(shadow).rounded_rectangle([box[0] + 3, box[1] + 7, box[2] + 3, box[3] + 7],
                                            radius=26, fill=(0, 0, 0, 105))
    img.alpha_composite(shadow.filter(ImageFilter.GaussianBlur(12)))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle(box, radius=26, fill=PILL_FILL)
    d.rounded_rectangle(box, radius=26, outline=ORANGE, width=3)
    ty = y + pad_y
    for line in lines:
        draw_rich(d, (84 + pad_x, ty), line, f, ef, WHITE)
        ty += lh
    img.save(out_path)
    return {"text": text, "box": [box[0], box[1], round(box[2] - box[0]), round(bh)],
            "lines": len(lines), "px": size}


def chip(out_path):
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    f = font(30)
    label = "Reddit Reviews"
    tw = f.getlength(label)
    box = [84, CHIP_Y, 84 + 46 + tw + 28, CHIP_Y + 48]
    d.rounded_rectangle(box, radius=24, fill=(15, 15, 18, 216))
    d.rounded_rectangle(box, radius=24, outline=ORANGE, width=3)
    d.ellipse([box[0] + 14, CHIP_Y + 15, box[0] + 32, CHIP_Y + 33], fill=ORANGE)
    d.text((box[0] + 42, CHIP_Y + 9), label, font=f, fill=WHITE)
    img.save(out_path)
    return [box[0], box[1], box[2] - box[0], box[3] - box[1]]


def plate_still(name, cy, cw, dst):
    src = Image.open(f"{PLATES}/{name}.png").convert("RGB")
    ch = int(round(cw * PH / PW))
    cy = max(0, min(cy, PLATE_H - ch))
    cx = (PLATE_W - cw) // 2
    crop = src.crop((cx, cy, cx + cw, cy + ch))
    crop.resize((PW * 2, PH * 2), Image.LANCZOS).save(dst)
    return {"source": f"reddit_reviews_assets -> rr_plates/{name}.png",
            "crop_window": [cx, cy, cw, ch], "zoom_vs_plate": round(850 / cw, 3)}


def sizzle_still(t_in, dst):
    tmp = f"{SCN}/_sz.png"
    run(["ffmpeg", "-y", "-v", "error", "-ss", f"{t_in}", "-i", SIZZLE, "-frames:v", "1", tmp])
    img = Image.open(tmp).convert("RGB")
    g = img.convert("L").point(lambda v: 255 if v < 246 else 0)
    bbox = g.getbbox() or (0, 0, 1080, 1920)
    bcx, bcy = (bbox[0] + bbox[2]) / 2, (bbox[1] + bbox[3]) / 2
    bw, bh = bbox[2] - bbox[0], bbox[3] - bbox[1]
    cw = int(max(PW * 0.72, min(1080, max(bw * 1.28, bh * PW / PH * 1.16))))
    ch = int(round(cw * PH / PW))
    cx = int(max(0, min(1080 - cw, bcx - cw / 2)))
    cy = int(max(0, min(1920 - ch, bcy - ch / 2)))
    crop = img.crop((cx, cy, cx + cw, cy + ch))
    crop.resize((PW * 2, PH * 2), Image.LANCZOS).save(dst)
    return {"source": "reddit_reviews_assets/Sizzle Video.mp4",
            "crop_window": [cx, cy, cw, ch], "content_bbox": list(bbox)}


def scene_video(still, frames, zoom, dst):
    z = (f"zoompan=z='1.02+0.05*on/{max(frames - 1, 1)}':"
         f"x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d=1:s={PW}x{PH}:fps={FPS}"
         if zoom else f"scale={PW}:{PH},fps={FPS}")
    run(["ffmpeg", "-y", "-v", "error", "-loop", "1", "-framerate", str(FPS), "-i", still,
         "-vf", f"{z},format=yuv420p", "-frames:v", str(frames), "-r", str(FPS),
         "-c:v", "libx264", "-crf", "14", "-preset", "veryfast", "-pix_fmt", "yuv420p", dst])


def norm_audio(start, dur, dst):
    p = run(["ffmpeg", "-hide_banner", "-ss", f"{start}", "-t", f"{dur}", "-i", SIZZLE,
             "-vn", "-af", "loudnorm=I=-14:TP=-1.5:LRA=11:print_format=json", "-f", "null", "-"])
    m = re.search(r"\{[^{}]*\"input_i\"[^{}]*\}", p.stderr, re.S)
    meas = json.loads(m.group(0))
    af = ("loudnorm=I=-14:TP=-1.5:LRA=11"
          f":measured_I={meas['input_i']}:measured_TP={meas['input_tp']}"
          f":measured_LRA={meas['input_lra']}:measured_thresh={meas['input_thresh']}"
          f":offset={meas['target_offset']}:linear=true")
    run(["ffmpeg", "-y", "-v", "error", "-ss", f"{start}", "-t", f"{dur}", "-i", SIZZLE,
         "-vn", "-af", af, "-ar", "48000", "-ac", "2", "-c:a", "pcm_s16le", dst])
    return {k: float(meas[k]) for k in ("input_i", "input_tp", "input_lra")}


def make_mask(dst):
    m = Image.new("L", (PW, PH), 0)
    ImageDraw.Draw(m).rounded_rectangle([0, 0, PW - 1, PH - 1], radius=30, fill=255)
    m.save(dst)


def compose(panel_mp4, audio, hook_png, call_png, chip_png, mask, dur, fcpath, dst):
    fc = (
        "[0:v]split=2[bg0][fg0];"
        f"[bg0]scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},"
        "gblur=sigma=90,eq=brightness=-0.46:saturation=0.55:contrast=0.92,"
        "drawbox=x=0:y=0:w=iw:h=ih:color=black@0.22:t=fill[bgb];"
        "[fg0]format=rgba[fg1];[fg1][2:v]alphamerge[fga];"
        f"[bgb][fga]overlay={PANEL[0]}:{PANEL[1]}:format=auto[comp];"
        "[comp][3:v]overlay=0:0:enable='between(t,0,3.5)'[v1];"
        "[v1][4:v]overlay=0:0:enable='between(t,4.0,8.5)'[v2];"
        "[v2][5:v]overlay=0:0[v3];"
        f"[v3]vignette=angle=PI/5,fps={FPS},format=yuv420p[vout]"
    )
    open(fcpath, "w").write(fc)
    run(["ffmpeg", "-y", "-v", "error", "-i", panel_mp4, "-i", audio,
         "-loop", "1", "-i", mask, "-loop", "1", "-i", hook_png,
         "-loop", "1", "-i", call_png, "-loop", "1", "-i", chip_png,
         "-filter_complex_script", fcpath, "-map", "[vout]", "-map", "1:a",
         "-t", f"{dur}", "-shortest",
         "-c:v", "libx264", "-preset", "medium", "-b:v", "12M", "-minrate", "8M",
         "-maxrate", "16M", "-bufsize", "24M",
         "-x264-params", "nal-hrd=cbr:force-cfr=1", "-profile:v", "high", "-level", "4.2",
         "-g", "120", "-pix_fmt", "yuv420p",
         "-c:a", "aac", "-b:a", "256k", "-ar", "48000", "-movflags", "+faststart", dst])


def build(clip, encode=True):
    cid = clip["id"]
    for d in (SCN, OVER, AUD, OUT):
        os.makedirs(d, exist_ok=True)
    hook = pill(clip["hook"], f"{OVER}/{cid}_hook.png")
    call = pill(clip["callout"], f"{OVER}/{cid}_call.png")
    chipbox = chip(f"{OVER}/{cid}_chip.png")
    mask = f"{OVER}/mask.png"
    make_mask(mask)

    files, log, t = [], [], 0.0
    for i, sc in enumerate(clip["scenes"]):
        dur = sc["dur"]
        frames = int(round(dur * FPS))
        still = f"{SCN}/{cid}_{i:02d}.png"
        if sc["kind"] == "plate":
            meta = plate_still(sc["name"], sc["cy"], sc["w"], still)
            zoom, sin, sout = True, None, None
        else:
            meta = sizzle_still(sc["t_in"], still)
            zoom, sin, sout = False, sc["t_in"], round(sc["t_in"] + dur, 3)
        seg = f"{SCN}/{cid}_{i:02d}.mp4"
        if encode:
            scene_video(still, frames, zoom, seg)
        files.append(seg)
        log.append({"timeline_in": round(t, 3), "timeline_out": round(t + dur, 3),
                    "duration_s": dur, "kind": sc["kind"], "source": meta["source"],
                    "source_in": sin, "source_out": sout,
                    "crop_window": meta["crop_window"],
                    "zoom_vs_plate": meta.get("zoom_vs_plate"),
                    "move": "punch-in 102% -> 107%" if zoom else "native sizzle motion",
                    "plate": sc.get("name")})
        t += dur

    dur = round(sum(s["dur"] for s in clip["scenes"]), 3)
    aud = f"{AUD}/{cid}.wav"
    stats = norm_audio(clip["audio_start"], dur + 0.3, aud)
    dst = f"{OUT}/{cid}.mp4"
    if encode:
        lst = f"{SCN}/{cid}_concat.txt"
        with open(lst, "w") as fh:
            for p in files:
                fh.write("file '{}'\n".format(os.path.abspath(p).replace("\\", "/")))
        panel = f"{SCN}/{cid}_panel.mp4"
        run(["ffmpeg", "-y", "-v", "error", "-f", "concat", "-safe", "0", "-i", lst,
             "-c", "copy", panel])
        compose(panel, aud, f"{OVER}/{cid}_hook.png", f"{OVER}/{cid}_call.png",
                f"{OVER}/{cid}_chip.png", mask, dur, f"{SCN}/fc_{cid}.txt", dst)
    return {"id": cid, "platform": clip["platform"], "angle": clip["angle"],
            "hook": clip["hook"], "callout": clip["callout"],
            "duration_s": dur, "frames": int(round(dur * FPS)),
            "bytes": os.path.getsize(dst), "path": f"outputs/reddit_reviews_campaign/{cid}.mp4",
            "audio_source": {"file": "Sizzle Video.mp4", "in": clip["audio_start"],
                             "lufs_before_normalize": stats},
            "hook_box": hook["box"], "callout_box": call["box"], "chip_box": chipbox,
            "scenes": log}


def write_meta(info):
    json.dump(info, open(f"{OUT}/meta_{info['id']}.json", "w"), indent=2)


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if a != "--meta"]
    encode = "--meta" not in sys.argv[1:]
    only = args or [c["id"] for c in CLIPS]
    report = []
    for c in CLIPS:
        if c["id"] not in only:
            continue
        print("building", c["id"], "encode" if encode else "(metadata only)", "...", flush=True)
        info = build(c, encode=encode)
        write_meta(info)
        print(f"  ok {info['path']} {info['duration_s']}s {info['bytes']/1e6:.1f} MB", flush=True)
        report.append(info)
    import glob
    allmeta = [json.load(open(p)) for p in glob.glob(f"{OUT}/meta_*.json")]
    json.dump(sorted(allmeta, key=lambda r: r["id"]), open(f"{OUT}/segments.json", "w"), indent=2)
    print("wrote segments.json", len(allmeta), "clips")
