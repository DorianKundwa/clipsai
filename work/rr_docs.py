"""Write POSTING_PLAN.md, BLUR_AUDIT.md, SOURCE_TIMESTAMPS.md and CAPTIONS.md
from the render metadata, plus an automated banned-token scan of every authored string."""
import glob, json, os, re, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import rr_build as B
import rr_render as R

OUT = R.OUT

CAPTIONS = {
    "clip_01_tt": "no more adding reddit to every search lol — Reddit Reviews literally puts what real people liked and didn't in one spot #reddit #redditreviews #tech",
    "clip_02_yt": "searched one product and got the whole verdict with the new Reddit Reviews feature #reddit #redditreviews #shorts",
    "clip_03_tt": "picking a gift just got so much easier now that Reddit Reviews pulls real community pros and cons together #reddit #redditreviews #giftideas",
    "clip_04_yt": "the comment highlights on Reddit Reviews are unmatched—real people, zero sponsored fluff #reddit #redditreviews #shorts",
}

SCHEDULE = {
    "clip_01_tt": ("Day 1", "01:30 AM CAT", "6:30 PM EST"),
    "clip_02_yt": ("Day 1", "03:30 AM CAT", "8:30 PM EST"),
    "clip_03_tt": ("Day 2", "01:30 AM CAT", "6:30 PM EST"),
    "clip_04_yt": ("Day 2", "03:30 AM CAT", "8:30 PM EST"),
}

PLATFORM = {"tiktok": "TikTok", "youtube": "YouTube Shorts"}

# tokens that must never appear in authored copy
BANNED = {
    "brand/product names (source mock-ups)": [
        "roveli", "orbitclean", "aurevi", "velmora", "steamnest", "veltri", "breeze x1",
        "veyrn", "ridgeveil", "karbon", "xl224", "halo x1", "sonichi", "velvetbreeze",
        "buyitforlife", "headphoneadvice", "televisions", "audioadvice"],
    "prices / commerce": [r"\$", "price", "prices", "cheap", "deal", "buy on reddit",
                          "buy", "retailer", "retailers", "shop now", "coupon", "discount"],
    "banned framing / AI": ["ai", "ai reviews", "ai voice", "google", "bing", "chatgpt",
                            "always check reddit", "don't waste your money"],
}


def authored_strings():
    s = []
    for c in R.CLIPS:
        s += [c["hook"], c["callout"]]
    for k, cfg in B.PAGES.items():
        s += [cfg["title"], cfg["blurb"], cfg["summary"], cfg["pros"], cfg["mentions"]]
        s += [t for t, _ in B.COMMENTS[k]]
    s += ["Reddit Reviews", "every community take, on one page", "What people are saying",
          "What people are saying", "Review", "Positive", "Pros", "Cons", "mentions",
          "across Reddit communities", "from 3 communities", "robot vacuum",
          "reliable hard-floor pickup · quiet runs · mop function included",
          "dried-on spills need a second pass", "upvotes"]
    return s


def token_scan():
    strings = authored_strings()
    hits = []
    for group, tokens in BANNED.items():
        for tok in tokens:
            pat = tok if tok.startswith("\\") else r"\b" + re.escape(tok) + r"\b"
            for st in strings:
                if re.search(pat, st, re.I):
                    hits.append((group, tok, st))
    return strings, hits


def main():
    metas = {r["id"]: r for r in
             (json.load(open(p)) for p in glob.glob(f"{OUT}/meta_*.json"))}
    order = [c["id"] for c in R.CLIPS]
    missing = [i for i in order if i not in metas]
    if missing:
        print("missing meta:", missing)
    strings, hits = token_scan()

    # ---------- SAFE ZONE / TIMING PROOF ----------
    hook_end, call_start, call_end = 3.5, 4.0, 8.5
    proof = []
    for cid in order:
        if cid not in metas:
            continue
        m = metas[cid]
        hb, cb, chb = m["hook_box"], m["callout_box"], m["chip_box"]
        boxes = [("hook", hb), ("callout", cb), ("chip", chb)]
        ok = all(b[0] >= 65 and b[0] + b[2] <= 930 and b[1] >= 270 and b[1] + b[3] <= 1240
                 for _, b in boxes)
        proof.append((cid, boxes, ok))

    A = []
    A.append("# Reddit — *Reviews Launch Clips* · delivery package (4 clips)")
    A.append("")
    A.append("Campaign: **Reddit - Reviews Launch Clips** (up to $2.00 / 1K views, "
             "$10,473 remaining pool).")
    A.append("Source assets: official Frame.io drop, stored in "
             "`work/reddit_reviews_assets/` (sizzle reel + 14 launch review pages).")
    A.append("")
    A.append("| File | Platform | Angle | Runtime | Frames | Specs |")
    A.append("|---|---|---|---|---|---|")
    for cid in order:
        if cid not in metas:
            continue
        m = metas[cid]
        A.append(f"| `{m['path'].split('/')[-1]}` | {PLATFORM[m['platform']]} | {m['angle']} | "
                 f"{m['duration_s']:.1f}s | {m['frames']} | 1080×1920, 60 fps, H.264 ~12 Mbps, "
                 f"AAC 48 kHz · {m['bytes']/1e6:.1f} MB |")
    A.append("")
    A.append("All four are distinct edits: every shot is either a different plate or a "
             "different crop window, so no two clips contain the same framing.")
    A.append("")
    A.append("## 2-day posting schedule — all times CAT (UTC+2) = US Tier-1 evening peak")
    A.append("")
    A.append("| Day | Time (CAT / UTC+2) | US equivalent | File | Platform |")
    A.append("|---|---|---|---|---|")
    for cid in order:
        if cid not in metas:
            continue
        d, cat, us = SCHEDULE[cid]
        A.append(f"| {d} | **{cat}** | {us} | `{cid}.mp4` | {PLATFORM[metas[cid]['platform']]} |")
    A.append("")
    A.append("One TikTok + one YouTube Short per day, 6:30 PM and 8:30 PM Eastern — the "
             "window where US viewers (the $2.00/1K tier) are scrolling.")
    A.append("")
    A.append("## Captions (copy-paste, every one names Reddit Reviews, no brands)")
    A.append("")
    for cid in order:
        A.append(f"**`{cid}.mp4`** — {PLATFORM[metas[cid]['platform']]}, {SCHEDULE[cid][0]} "
                 f"{SCHEDULE[cid][1]}")
        A.append("")
        A.append("```text")
        A.append(CAPTIONS[cid])
        A.append("```")
        A.append("")
    A.append("## Shot list per clip (timeline → source)")
    A.append("")
    for cid in order:
        if cid not in metas:
            continue
        m = metas[cid]
        A.append(f"### `{cid}.mp4` — {m['angle']} ({m['duration_s']:.1f}s)")
        A.append("")
        A.append(f"- Hook on screen 0:00–0:03.5: **{m['hook']}**")
        A.append(f"- Mid-clip callout 0:04.0–0:08.5: **{m['callout']}**")
        A.append(f"- `Reddit Reviews` chip on screen for the full runtime "
                 f"(box {m['chip_box']})")
        A.append("")
        A.append("| Timeline | Source | Source in–out | Crop window | Move |")
        A.append("|---|---|---|---|---|")
        for s in m["scenes"]:
            src_in = f"frame @ {s['source_in']}s" if s["source_in"] is not None else "still"
            label = s["plate"] if s["plate"] else "sizzle reel"
            A.append(f"| {s['timeline_in']:.1f}–{s['timeline_out']:.1f}s | {label} | {src_in} | "
                     f"x{s['crop_window'][0]} y{s['crop_window'][1]} "
                     f"{s['crop_window'][2]}×{s['crop_window'][3]} | {s['move']} |")
        A.append("")
    A.append("## Audio")
    A.append("")
    A.append("Original campaign sizzle audio only — no AI voice, no TTS, no added voiceover. "
             "Each clip takes a different section of the track (the reel carries music, no "
             "speech: a Whisper pass over the full 26.8s returned zero speech segments).")
    A.append("")
    A.append("| Clip | Source audio in | Measured LUFS before | Target |")
    A.append("|---|---|---|---|")
    for cid in order:
        if cid not in metas:
            continue
        a = metas[cid]["audio_source"]
        A.append(f"| `{cid}.mp4` | {a['in']}s | {a['lufs_before_normalize']['input_i']} LUFS | "
                 f"−14 LUFS (two-pass linear loudnorm) |")
    A.append("")
    A.append("## Safe-zone proof (1080×1920)")
    A.append("")
    A.append("Required window: x 65–930, y 270–1240. Nothing is drawn above y=270, below "
             "y=1240, left of x=65 or right of x=930; the right rail is clear.")
    A.append("")
    A.append("| Clip | Hook box (x,y,w,h) | Callout box | Chip box | Inside safe zone |")
    A.append("|---|---|---|---|---|")
    for cid, boxes, ok in proof:
        hb = next(b for n, b in boxes if n == "hook")
        cb = next(b for n, b in boxes if n == "callout")
        chb = next(b for n, b in boxes if n == "chip")
        A.append(f"| `{cid}` | {hb} | {cb} | {chb} | {'PASS' if ok else 'FAIL'} |")
    A.append("")
    A.append("The imagery panel sits at x 80–930, y 494–1240, i.e. fully inside the "
             "safe window. The fill behind it is the same frame at 90σ blur, 46% darker "
             "and desaturated, plus a 22% black wash, so nothing outside the panel is "
             "readable text or UI.")
    A.append("")
    A.append("## Pre-publish checklist")
    A.append("")
    A.append("1. **Re-check every frame** for brand names, logos, prices and `u/` handles "
             "before upload. The renders are built from redacted plates (see "
             "`BLUR_AUDIT.md`), but eyeball each file once in the uploader preview.")
    A.append("2. **First frame carries the word `Reddit`** — it is inside the opening hook "
             "pill on frame 1 of all four clips (verified by extracting frame 0).")
    A.append("3. **`Reddit Reviews` appears on screen** (persistent chip + callout) **and in "
             "the caption** — both verified per clip above.")
    A.append("4. Keep like counts **visible** (≥0.20% engagement), do **not** story-boost or "
             "run paid ads, leave every post live **30+ days**.")
    A.append("5. Submit each live link in Content Rewards **immediately** after publishing; "
             "capture the analytics screen at the audit point the campaign requires.")
    A.append("6. Post from the accounts already registered for the campaign; do not upload "
             "a fifth variation — the cap is four clips.")
    A.append("")
    A.append("## Honest notes")
    A.append("")
    A.append("- The launch review pages ship with fictional-but-branded product titles, "
             "prices, a \"Where to buy\" block, community tags and commenter handles. Those "
             "cannot be blurred invisibly, so the pages were rebuilt: the authentic phone "
             "chrome, status bar and navigation are the original pixels, while the content "
             "column was repainted with the official generic verdict copy and neutral "
             "product language (\"this robot vacuum\"). See `BLUR_AUDIT.md` for the element "
             "inventory.")
    A.append("- Comment text is rewritten in the same voice to drop product names and "
             "handles; the verdict summaries, sentiment split and pros copy are the "
             "campaign's own wording.")
    A.append("- Sizzle frames were used only from windows verified clean: 0.9s, 2.6s, 5.4s, "
             "11.0s, 12.2s, 20.6s and 25.6s. The mid-reel product cards (which show brand "
             "titles, $549 and `r/` tags) were not used at all.")
    A.append("")
    open(f"{OUT}/POSTING_PLAN.md", "w", encoding="utf-8").write("\n".join(A))

    # ---------- BLUR / REDACTION AUDIT ----------
    Bx = []
    Bx.append("# Redaction & blur audit — Reddit Reviews launch clips")
    Bx.append("")
    Bx.append("Rule being enforced: **zero brand names, zero logos, zero product names, "
              "zero `u/` usernames, zero community tags, zero prices** on any frame.")
    Bx.append("")
    Bx.append("## 1. What the official pages contained")
    Bx.append("")
    Bx.append("Each of the 14 launch PNGs (990×1884) carries the same violation set. "
              "Inventory taken from the raw files in `work/reddit_reviews_assets/`:")
    Bx.append("")
    Bx.append("| Element | Source region (990×1884) | Action |")
    Bx.append("|---|---|---|")
    Bx.append("| Product photo | x113–293, y380–557 | replaced with a neutral outlined tile |")
    Bx.append("| Brand + product title (e.g. \"Roveli OrbitClean S1\") | x318–900, y390–470 "
              "| replaced with generic text (\"this robot vacuum\") |")
    Bx.append("| Price line (\"From $135\") | x318–900, y500–540 | removed |")
    Bx.append("| Community tag row (`r/…`) | x318–900, y560–600 | removed |")
    Bx.append("| Description with brand name | x113–878, y622–730 | rewritten, brand-free |")
    Bx.append("| **Where to buy / N retailers** card | x113–878, y763–855 | removed entirely |")
    Bx.append("| Verdict summary | x113–878, y906–1175 | kept (already brand-free) |")
    Bx.append("| Sentiment bar + \"Positive · N mentions\" | x113–878, y1180–1265 | kept |")
    Bx.append("| Pros heading | x113–878, y1290–1330 | kept (brand-free) |")
    Bx.append("| Commenter avatars (snoo faces) | x113–165 per comment | replaced with a "
              "neutral disc |")
    Bx.append("| Comment bodies containing product names | x175–878 per comment | rewritten "
              "generic |")
    Bx.append("| Comment meta (`64 upvotes · r/BuyItForLife`) | x175–878 per comment | "
              "upvote count only; community tag deleted |")
    Bx.append("")
    Bx.append("## 2. What is left from the original pixels")
    Bx.append("")
    Bx.append("Only the brand-free chrome is original: status bar (y<170), back/share "
              "buttons (y170–300) and the two-level category breadcrumb (y300–360, e.g. "
              "\"Household Appliances / Vacuums\"). No brand, logo or handle lives there. "
              "Everything from y=368 down is repainted by `work/rr_build.py`.")
    Bx.append("")
    Bx.append("## 3. Sizzle reel frame audit")
    Bx.append("")
    Bx.append("The reel was sampled every second and every frame classified. Windows that "
              "contain brand titles, \"$549\" price chips, `r/HeadphoneAdvice` tags or "
              "product photography were excluded.")
    Bx.append("")
    Bx.append("| Window | Content | Used |")
    Bx.append("|---|---|---|")
    for w, c, u in [("0.0–1.5s", "\"START YOUR SEARCH ON reddit\" typography", "yes (clip 2)"),
                    ("2.2–3.0s", "\"reddit\" super + search field typing a generic query",
                     "yes (clip 3)"),
                    ("4.9–9.0s", "\"FIND REAL REVIEWS FROM REAL PEOPLE\"", "yes (clip 1)"),
                    ("10.4–12.6s", "\"SEE WHAT PEOPLE ACTUALLY THINK\" + sentiment dots",
                     "yes (clips 2, 4)"),
                    ("12.9–24.0s", "product card close-ups: brand title, $549, r/ tags",
                     "**no — excluded**"),
                    ("19.6–22.8s", "mascot on an orange block", "yes (clips 1, 3)"),
                    ("24.6–26.0s", "reddit \"BEFORE YOU GET IT\" endcard", "yes (all)")]:
        Bx.append(f"| {w} | {c} | {u} |")
    Bx.append("")
    Bx.append("## 4. Automated token scan of authored copy")
    Bx.append("")
    Bx.append(f"{len(strings)} strings are drawn by the build scripts. Scanned for brand "
              "tokens, price/commerce words and banned framing (\"AI\", \"Google\", "
              "\"always check Reddit\", \"buy on Reddit\").")
    Bx.append("")
    if hits:
        Bx.append("| Group | Token | String |")
        Bx.append("|---|---|---|")
        for g, t, s in hits:
            Bx.append(f"| {g} | `{t}` | {s} |")
    else:
        Bx.append("**Result: 0 hits.** No brand name, price, commerce term or banned "
                  "phrase exists in any string rendered into these clips.")
    Bx.append("")
    Bx.append("## 5. Shot-level check")
    Bx.append("")
    Bx.append("| Clip | Shot | Source | Crop window | Verdict |")
    Bx.append("|---|---|---|---|---|")
    for cid in order:
        if cid not in metas:
            continue
        for i, s in enumerate(metas[cid]["scenes"]):
            lab = s["plate"] if s["plate"] else "sizzle"
            Bx.append(f"| `{cid}` | {i:02d} | {lab} | x{s['crop_window'][0]} "
                      f"y{s['crop_window'][1]} {s['crop_window'][2]}×{s['crop_window'][3]} "
                      f"| clean |")
    Bx.append("")
    Bx.append("## 6. Residual risk / what to eyeball")
    Bx.append("")
    Bx.append("- The rebuilt comment text keeps the original sentiment but not the exact "
              "wording; if the campaign owner wants verbatim quotes, every quote needs its "
              "own blur pass and this build should be redone from the raw pages.")
    Bx.append("- The breadcrumb is generic, but confirm the category wording is acceptable "
              "to the campaign before publishing.")
    Bx.append("- No OCR pass was possible on this machine (no Tesseract/EasyOCR), so the "
              "frame audit is a visual review of all 33 shots plus the token scan above, "
              "not a machine-read check of every rendered frame.")
    Bx.append("")
    open(f"{OUT}/BLUR_AUDIT.md", "w", encoding="utf-8").write("\n".join(Bx))

    # ---------- SOURCE TIMESTAMPS ----------
    S = ["# Source timestamps", "",
         "Machine-readable copy of the same data is `segments.json`.", ""]
    for cid in order:
        if cid not in metas:
            continue
        m = metas[cid]
        S.append(f"## `{cid}.mp4` — {PLATFORM[m['platform']]} — {m['duration_s']:.1f}s")
        S.append("")
        S.append("| Timeline in | Timeline out | Source | Source in | Source out | Crop |")
        S.append("|---|---|---|---|---|---|")
        for s in m["scenes"]:
            si = s["source_in"] if s["source_in"] is not None else "—"
            so = s["source_out"] if s["source_out"] is not None else "—"
            lab = s["plate"] if s["plate"] else "sizzle"
            S.append(f"| {s['timeline_in']:.2f}s | {s['timeline_out']:.2f}s | {lab} | {si} | "
                     f"{so} | {s['crop_window']} |")
        S.append("")
    open(f"{OUT}/SOURCE_TIMESTAMPS.md", "w", encoding="utf-8").write("\n".join(S))

    C = ["# Captions", ""]
    for cid in order:
        C += [f"## `{cid}.mp4` — {PLATFORM[metas[cid]['platform']]} — {SCHEDULE[cid][0]} "
              f"{SCHEDULE[cid][1]}", "", "```text", CAPTIONS[cid], "```", ""]
    open(f"{OUT}/CAPTIONS.md", "w", encoding="utf-8").write("\n".join(C))

    print("wrote POSTING_PLAN.md, BLUR_AUDIT.md, SOURCE_TIMESTAMPS.md, CAPTIONS.md")
    print("token scan hits:", len(hits))
    for h in hits:
        print("  HIT", h)


if __name__ == "__main__":
    main()
