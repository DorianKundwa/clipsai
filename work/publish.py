"""Publish the Hong Kong campaign clips through the IndiePost API.

Each clip goes to the platform in its own filename (tt -> TikTok, ig -> Instagram
Reels), at the timestamp from POSTING_PLAN.md. Scheduling uses IndiePost's `when`
ISO timestamp so nothing posts off-plan.

Usage:
    python work/publish.py --dry-run
    python work/publish.py clip_01_tt
    python work/publish.py            # all six
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from clipsai.config import load_env  # noqa: E402
from clipsai.publish.indiepost import IndiePostClient, publish_items  # noqa: E402
from clipsai.publish.models import PlatformOptions, PublishItem  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
SEGMENTS = ROOT / "outputs" / "hongkong_campaign" / "segments.json"

# CAT (UTC+2) slot -> UTC instant. Day 1 is tonight, 25 Nov.
SCHEDULE = {
    "clip_01_tt": "2026-11-25T23:30:00.000Z",  # Day 1 01:30 CAT
    "clip_02_ig": "2026-11-26T01:00:00.000Z",  # Day 1 03:00 CAT
    "clip_03_tt": "2026-11-27T00:00:00.000Z",  # Day 2 02:00 CAT
    "clip_04_ig": "2026-11-27T02:00:00.000Z",  # Day 2 04:00 CAT
    "clip_05_tt": "2026-11-27T23:30:00.000Z",  # Day 3 01:30 CAT
    "clip_06_ig": "2026-11-28T01:30:00.000Z",  # Day 3 03:30 CAT
}


def _options(platform: str) -> PlatformOptions:
    return PlatformOptions(
        tiktok_privacy="PUBLIC_TO_EVERYONE",
        instagram_format="reel" if platform == "instagram" else None,
    )


def main(argv):
    dry_run = "--dry-run" in argv
    wanted = [a for a in argv if not a.startswith("-")]
    rows = json.loads(SEGMENTS.read_text(encoding="utf-8"))
    rows = [r for r in rows if not wanted or r["id"] in wanted]
    if not rows:
        raise SystemExit("No matching clips.")

    if dry_run:
        for row in rows:
            item = PublishItem(
                path=str(ROOT / row["file"]),
                caption=row["caption"],
                index=int(row["id"].split("_")[1]),
                options=_options(row["platform"]),
            )
            print(json.dumps({
                "id": row["id"],
                "platform": item.options.instagram_format or row["platform"],
                "when": SCHEDULE[row["id"]],
                "path": item.path,
                "caption": item.caption,
            }, indent=1))
        return 0

    load_env()
    client = IndiePostClient()
    client.assert_ready()

    for row in rows:
        item = PublishItem(
            path=str(ROOT / row["file"]),
            caption=row["caption"],
            index=int(row["id"].split("_")[1]),
            options=_options(row["platform"]),
        )
        print("\n=== {} -> {} at {}".format(row["id"], row["platform"], SCHEDULE[row["id"]]))
        try:
            result = publish_items(
                client,
                [item],
                [row["platform"]],
                when=SCHEDULE[row["id"]],
                job_id="hk-campaign-2026-11",
            )[0]
        except Exception as exc:  # noqa: BLE001 - report and keep going
            print("FAILED:", type(exc).__name__, str(exc)[:400])
            continue
        print(json.dumps({
            "media_id": result.get("media_id"),
            "idempotency_key": result.get("idempotency_key"),
            "post": result.get("post"),
            "external_ids": result.get("external_ids"),
        }, indent=1)[:1500])
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
