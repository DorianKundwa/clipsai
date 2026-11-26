"""Build the posting plan + captions from the render log."""
import json
from campaign import CLIPS, OUT

SCHEDULE = {
    "clip_01_tt": ("Day 1", "01:30 CAT", "6:30 PM EST / 11:30 PM GMT"),
    "clip_02_ig": ("Day 1", "03:00 CAT", "8:00 PM EST / 1:00 AM GMT"),
    "clip_03_tt": ("Day 2", "02:00 CAT", "7:00 PM EST / 12:00 AM GMT"),
    "clip_04_ig": ("Day 2", "04:00 CAT", "9:00 PM EST / 2:00 AM GMT"),
    "clip_05_tt": ("Day 3", "01:30 CAT", "6:30 PM EST / 11:30 PM GMT"),
    "clip_06_ig": ("Day 3", "03:30 CAT", "8:30 PM EST / 1:30 AM GMT"),
}

TT_AUDIO = "7702836179004868609"
IG_AUDIO = "2188669935047731"

PLATFORM = {"tiktok": "TikTok", "instagram": "Instagram Reels"}
AUDIO_FOR = {"tiktok": TT_AUDIO, "instagram": IG_AUDIO}

data = {r["id"]: r for r in json.load(open(f"{OUT}/segments.json"))}

lines = []
A = lines.append
A("# The Weeknd — Hong Kong Performance | 6-Clip Vertical Campaign")
A("")
A("Source: `Video 02-11-2026, 10 19 21 AM.mp4` — 1920x1080, 23.976 fps, 3:41.")
A(f"Deliverables: 6 x 1080x1920, 60 fps, H.264 ~12 Mbps, AAC 256 kbps, −14 LUFS live audio.")
A("")
A("All six cuts use the clean original live audio (no added music). Text is English only,")
A("inside the vertical safe zone, no lyrics and no aggressive wording.")
A("")
A("## Posting schedule (all times CAT / UTC+2)")
A("")
A("| Day | Time CAT | Tier-1 equivalent | File | Platform | Angle |")
A("|---|---|---|---|---|---|")
for c in CLIPS:
    d, cat, t1 = SCHEDULE[c["id"]]
    A(f"| {d} | {cat} | {t1} | `{c['id']}.mp4` | {PLATFORM[c['platform']]} | {c['angle']} |")
A("")
A("## Clip cards")
A("")
for c in CLIPS:
    r = data[c["id"]]
    d, cat, t1 = SCHEDULE[c["id"]]
    A(f"### `{c['id']}.mp4` — {c['angle']}")
    A("")
    A(f"- **Platform / slot:** {PLATFORM[c['platform']]} — {d}, {cat} ({t1})")
    A(f"- **Runtime:** {c['dur']}s | **Size:** {r['bytes'] / 1e6:.1f} MB")
    A(f"- **Hook text (on screen):** {c['hook']}")
    A(f"- **Caption:** {c['caption']}")
    A("")
    A("| Timeline | Source in–out | Framing | Move |")
    A("|---|---|---|---|")
    for s in r["shots"]:
        move = "slow zoom 100→108%" if s["slow_zoom"] else "static"
        A(f"| {s['timeline_in']:>4.1f}–{s['timeline_out']:<4.1f}s | "
          f"{s['source_in']:>6.1f}–{s['source_out']:<6.1f}s | {s['frame']} | {move} |")
    A("")
    A(f"> **Pre-publish:** attach the official {PLATFORM[c['platform']]} sound "
      f"`{AUDIO_FOR[c['platform']]}` at **0% volume**, keep this clip's original live audio at "
      f"**100%**, likes and comments **ON**, then screen-record watch time / view graph / "
      f"locations at 1,000 views with ≥1% engagement and a Tier-1 majority.")
    A("")
A("## Pre-publish checklist (every clip)")
A("")
A(f"1. **Attach the official campaign sound in-app** — TikTok `{TT_AUDIO}`, Instagram `{IG_AUDIO}`.")
A("2. Set the added campaign sound volume to **0%**; keep the clip's **original live audio at 100%**.")
A("3. Confirm likes and comments are **ON**; no paid-partnership label unless the brief requires it.")
A("4. Post only from the existing music / pop / R&B / live-performance page for that platform.")
A("   No new Weeknd-only accounts, no collab posts, no story boosting, no duplicate uploads.")
A("5. Check the exported file plays with **audio, no black bars**, and the hook text is fully")
A("   visible before the first frame of UI overlay.")
A("6. At **1,000 views** with **≥1% engagement** and a **>50% Tier-1 audience**, immediately")
A("   screen-record the video-specific analytics: retention/watch-time graph, view graph and")
A("   the audience-locations breakdown. Save as `<clip_id>_audit.png` and attach to the campaign report.")
A("")
A("## Quality targets")
A("")
A("- Recap pacing, 24–26 s runtime, hook inside 0:00–0:02, loopable final cut.")
A("- Engagement: 1.0% minimum (10 likes / 1,000 views), 3% stretch target.")
A("- Geography: majority US / UK / CA / AU at the 1,000-view audit.")
A("")
A("## Scale-up (Days 4–5, only if Day 1–2 clips clear the audit)")
A("")
A("Reuse the same slots and structure with new combinations of unused segments:")
A("`30–40s` daytime bay, `48–56s` market interiors, `84–96s` light-orb / bridge,")
A("`128–150s` tunnel and long-street shots, `176–186s` highway aerials,")
A("`198–206s` facade windows. Keep each cut 18–28 s, one new hook text, one new caption.")
A("")
A("## Production notes")
A("")
A("- The camera is locked off on the arena screen for the whole recording, so \"close-ups\"")
A("  are 4:5 punch-ins on the projected film and on the artist's stair platform, not optical zooms.")
A("- No stage pyro is visible in this file: the fire burst used in `clip_04_ig` is the")
A("  projection content at 2:02.")
A("- All cuts are centred 4:5 frames over a Gaussian-blurred fill of the same frame (no black bars).")
A("- Source is 23.976 fps; the 60 fps deliverables use frame duplication, so motion is identical")
A("  to the original capture (no interpolation artefacts).")
A("- A Faye Wong cover could not be confirmed in the audio (Whisper transcripts the whole set as")
A("  English lyrics). `clip_03_tt` carries the Hong Kong crossover angle visually — the HONG KONG")
A("  title sequence and the city/neon footage — and the required `#fayewong` tag; if the actual")
A("  tribute moment exists, give me its timestamp and I will recut that clip around it.")
A("")

open(f"{OUT}/POSTING_PLAN.md", "w", encoding="utf-8").write("\n".join(lines))

captions = ["# Captions", ""]
for c in CLIPS:
    d, cat, t1 = SCHEDULE[c["id"]]
    captions += [f"## {c['id']} — {d} {cat}", "", f"**Hook:** {c['hook']}", "",
                 c["caption"], "",
                 f"`{c['id']}.mp4` · {c['dur']}s · {PLATFORM[c['platform']]}", ""]
open(f"{OUT}/CAPTIONS.md", "w", encoding="utf-8").write("\n".join(captions))
print("wrote POSTING_PLAN.md and CAPTIONS.md")
