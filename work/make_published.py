"""Write PUBLISHED.md for the Hong Kong campaign from IndiePost's post list."""

import datetime
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from clipsai.config import load_env  # noqa: E402
from clipsai.publish.indiepost import IndiePostClient  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "outputs" / "hongkong_campaign"

load_env()
client = IndiePostClient()

# Upload order (and the platform per segment) is the campaign order in segments.json.
segments = json.loads((OUT / "segments.json").read_text(encoding="utf-8"))
expected = [(s["id"], s["platform"]) for s in segments]
posts = client.list_posts("2026-11-25T00:00:00.000Z", "2026-11-29T00:00:00.000Z")["posts"]

rows = []
index = 0
for group in posts:
    for post in group.get("posts", []):
        name, platform = expected[index] if index < len(expected) else ("", "")
        if platform != post["platform"]:
            raise SystemExit("post order does not match segments.json")
        index += 1
        rows.append({
            "clip": name,
            "platform": post["platform"],
            "status": post["status"],
            "id": post.get("externalPostId") or "-",
            "utc": post.get("postedAt") or "-",
            "cat": (
                datetime.datetime.fromisoformat(post["postedAt"].replace("Z", "+00:00"))
                + datetime.timedelta(hours=2)
            ).strftime("%Y-%m-%d %H:%M") if post.get("postedAt") else "-",
        })

lines = [
    "# Published through the IndiePost API",
    "",
    "Account: `xrwclipper` (TikTok and Instagram already connected — no new profile created).",
    "",
    "| Clip | Platform | Status | External post id | Published (UTC) | Published (CAT) |",
    "|---|---|---|---|---|---|",
]
for row in rows:
    lines.append(
        "| `{}` | {} | {} | `{}` | {} | {} |".format(
            row["clip"], row["platform"], row["status"], row["id"], row["utc"], row["cat"]
        )
    )

lines += [
    "",
    "Every post went out through `POST /api/v1/posts` (init media -> PUT -> confirm -> post)",
    "with the original live audio, TikTok at `PUBLIC_TO_EVERYONE` and Instagram as a Reel.",
    "Captions are the approved copy from `CAPTIONS.md`, each ending `#TheWeeknd #fayewong`.",
    "",
    "## Schedule deviation",
    "",
    "The per-clip ISO `when` timestamps in `POSTING_PLAN.md` were sent with every request, but",
    "IndiePost ignored them: each post group recorded `scheduledAt` equal to its upload time and",
    "published immediately. All six clips are therefore live on 2026-11-25, not spread across the",
    "planned three-day cadence.",
    "",
    "## Not done by the API",
    "",
    "The in-app `Use this sound` step (campaign sound attached at 0%) only exists in the mobile",
    "apps, so these posts carry the clip's own live audio and no attached campaign sound id.",
    "",
]

(OUT / "PUBLISHED.md").write_text("\n".join(lines), encoding="utf-8")
print("\n".join(lines))
