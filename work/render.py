"""Render the six vertical campaign cuts (two-pass: shot cuts, then composite)."""
import json, os, re, subprocess, sys
from campaign import CLIPS, FRAMES, SRC, OUT

CARD_T = 4.2
SHOTS = "work/shots"


def run(cmd, quiet=True):
    p = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if p.returncode != 0:
        print(p.stderr[-3000:])
        raise SystemExit(f"failed: {' '.join(cmd[:6])}")
    return p


def normalize_audio(src, start, dur, dst):
    probe = run(["ffmpeg", "-hide_banner", "-ss", f"{start}", "-t", f"{dur}", "-i", src,
                 "-vn", "-af", "loudnorm=I=-14:TP=-1.5:LRA=11:print_format=json",
                 "-f", "null", "-"])
    m = re.search(r"\{[^{}]*\"input_i\"[^{}]*\}", probe.stderr, re.S)
    meas = json.loads(m.group(0))
    af = ("loudnorm=I=-14:TP=-1.5:LRA=11"
          f":measured_I={meas['input_i']}:measured_TP={meas['input_tp']}"
          f":measured_LRA={meas['input_lra']}:measured_thresh={meas['input_thresh']}"
          f":offset={meas['target_offset']}:linear=true")
    run(["ffmpeg", "-y", "-v", "error", "-ss", f"{start}", "-t", f"{dur}", "-i", src,
         "-vn", "-af", af, "-ar", "48000", "-ac", "2", "-c:a", "pcm_s16le", dst])
    return {k: meas[k] for k in ("input_i", "input_tp", "input_lra")}


def cut_shot(cid, i, s, d, frame, zoom):
    f = FRAMES[frame]
    out = f"{SHOTS}/{cid}_{i:02d}.mp4"
    vf = (f"crop={f['w']}:{f['h']}:{f['x']}:{f['y']},setsar=1,fps=24")
    if zoom:
        rate = 0.08 / (d * 24)
        vf += (f",scale={f['w'] * 2}:{f['h'] * 2}:flags=lanczos,"
               f"zoompan=z='min(1+{rate:.8f}*on,1.08)':x='iw/2-(iw/zoom/2)':"
               f"y='ih/2-(ih/zoom/2)':d=1:s=1080x1350:fps=24")
    else:
        vf += ",scale=1080:1350:flags=lanczos"
    run(["ffmpeg", "-y", "-v", "error", "-ss", f"{s}", "-t", f"{d}", "-i", SRC,
         "-vf", vf, "-an", "-c:v", "libx264", "-crf", "10", "-preset", "veryfast",
         "-pix_fmt", "yuv420p", "-r", "24", out])
    return out


def compose(clip, files, aud, dst):
    lst = f"{SHOTS}/{clip['id']}_concat.txt"
    with open(lst, "w") as fh:
        for p in files:
            fh.write("file '{}'\n".format(os.path.abspath(p).replace("\\", "/")))
    d = clip["dur"]
    fc = (
        "[0:v]split=2[fg0][bg0];"
        "[bg0]scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,"
        "gblur=sigma=50,eq=brightness=0.03:saturation=0.95[bg];"
        "[fg0]eq=contrast=1.05:saturation=1.10:brightness=0.035[vf];"
        "[bg][vf]overlay=0:285,vignette=angle=PI/6[ov];"
        f"[2:v]format=rgba,fade=t=in:st=0:d=0.25:alpha=1,"
        f"fade=t=out:st={CARD_T}:d=0.55:alpha=1[card];"
        "[ov][card]overlay=0:0:format=auto,fps=60,format=yuv420p[vout]"
    )
    fc_path = f"work/fc_{clip['id']}.txt"
    open(fc_path, "w").write(fc)
    run(["ffmpeg", "-y", "-v", "error", "-stats",
         "-f", "concat", "-safe", "0", "-i", lst,
         "-i", aud, "-loop", "1", "-framerate", "24", "-i", f"work/cards/{clip['id']}.png",
         "-filter_complex_script", fc_path,
         "-map", "[vout]", "-map", "1:a", "-t", str(d), "-shortest",
         "-c:v", "libx264", "-preset", "medium", "-b:v", "12M",
         "-minrate", "8M", "-maxrate", "16M", "-bufsize", "24M",
         "-x264-params", "nal-hrd=cbr:force-cfr=1", "-profile:v", "high",
         "-level", "4.2", "-g", "120", "-pix_fmt", "yuv420p",
         "-c:a", "aac", "-b:a", "256k", "-ar", "48000",
         "-movflags", "+faststart", dst])


def render(clip):
    cid = clip["id"]
    os.makedirs(SHOTS, exist_ok=True)
    os.makedirs("work/aud", exist_ok=True)
    os.makedirs("work/cards", exist_ok=True)
    os.makedirs(OUT, exist_ok=True)
    aud = f"work/aud/{cid}.wav"
    stats = normalize_audio(SRC, clip["audio_start"], clip["dur"], aud)
    files, log, t = [], [], 0.0
    for i, (s, d, fr, zoom) in enumerate(clip["shots"]):
        files.append(cut_shot(cid, i, s, d, fr, zoom))
        log.append({"timeline_in": round(t, 2), "timeline_out": round(t + d, 2),
                    "source_in": s, "source_out": round(s + d, 2),
                    "frame": fr, "slow_zoom": zoom})
        t += d
    dst = f"{OUT}/{cid}.mp4"
    compose(clip, files, aud, dst)
    return {"file": dst, "bytes": os.path.getsize(dst), "shots": log,
            "audio_lufs_before": stats}


if __name__ == "__main__":
    only = sys.argv[1:] or [c["id"] for c in CLIPS]
    report = []
    for c in CLIPS:
        if c["id"] not in only:
            continue
        print(f"rendering {c['id']} ...", flush=True)
        info = render(c)
        print(f"  done {info['file']} {info['bytes'] / 1e6:.1f} MB", flush=True)
        report.append({"id": c["id"], "platform": c["platform"], "angle": c["angle"],
                       "hook": c["hook"], "caption": c["caption"],
                       "audio_start": c["audio_start"], "duration": c["dur"], **info})
    old = []
    if os.path.exists(f"{OUT}/segments.json"):
        old = [r for r in json.load(open(f"{OUT}/segments.json")) if r["id"] not in only]
    json.dump(sorted(old + report, key=lambda r: r["id"]),
              open(f"{OUT}/segments.json", "w"), indent=2)
    print("segments.json updated")
