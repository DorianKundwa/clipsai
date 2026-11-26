"""Campaign definition: 6 vertical cuts from the Hong Kong performance."""

SRC = "Video 02-11-2026, 10 19 21 AM.mp4"
OUT = "outputs/hongkong_campaign"

# Framing: 4:5 window sizes/offsets inside the 1920x1080 source, scaled to 1080x1350.
FRAMES = {
    "wide":   dict(w=864, h=1080, x=528, y=0),     # full 4:5 centre window
    "medium": dict(w=800, h=1000, x=560, y=60),
    "artist": dict(w=640, h=800,  x=640, y=280),   # tight on the stair platform
}

# Each shot: (source_start, duration, frame, zoom?)
CLIPS = [
    dict(
        id="clip_01_tt", platform="tiktok", dur=26, audio_start=154.0,
        angle="Best vocal climax edit",
        hook="THE HIGHEST NOTE OF THE NIGHT",
        caption="2:34 in Hong Kong and he still had another gear. Stay for the last run. "
                "Live vocals only. #TheWeeknd #fayewong",
        shots=[
            (163.0, 2.0, "wide", False),
            (174.0, 2.0, "wide", False),
            (122.0, 2.0, "wide", False),
            (150.0, 2.0, "wide", False),
            (186.0, 2.0, "wide", False),
            (164.0, 14.0, "wide", True),
            (161.0, 2.0, "wide", False),
        ],
    ),
    dict(
        id="clip_02_ig", platform="instagram", dur=24, audio_start=184.0,
        angle="Crowd sing-along & wide stage edit",
        hook="THE WHOLE ARENA SANG THIS ONE",
        caption="The whole arena took the chorus for him. Lights up, phones out, everyone singing. "
                "#TheWeeknd #fayewong",
        shots=[
            (9.2, 2.0, "wide", False),
            (108.0, 2.0, "wide", False),
            (68.0, 2.0, "wide", False),
            (188.0, 2.0, "wide", False),
            (44.0, 2.0, "wide", False),
            (194.0, 12.0, "wide", True),
            (7.2, 2.0, "wide", False),
        ],
    ),
    dict(
        id="clip_03_tt", platform="tiktok", dur=24, audio_start=96.0,
        angle="Hong Kong cultural crossover angle",
        hook="HONG KONG, THIS ONE IS YOURS",
        caption="Hong Kong on the screen, Hong Kong in the room. This city showed out tonight. "
                "#TheWeeknd #fayewong",
        shots=[
            (4.1, 2.0, "wide", False),
            (44.0, 2.0, "wide", False),
            (56.0, 2.0, "medium", False),
            (24.0, 2.0, "wide", False),
            (196.0, 2.0, "wide", False),
            (106.0, 12.0, "wide", True),
            (2.1, 2.0, "wide", False),
        ],
    ),
    dict(
        id="clip_04_ig", platform="instagram", dur=24, audio_start=66.0,
        angle="High-energy beat-drop recap montage",
        hook="THIS IS WHERE THE BEAT DROPS",
        caption="Beat drop, red lights, and a crowd that never sat down. Turn the sound up. "
                "#TheWeeknd #fayewong",
        shots=[
            (122.0, 2.0, "wide", False),
            (80.0, 2.0, "wide", False),
            (164.0, 2.0, "medium", False),
            (176.0, 2.0, "wide", False),
            (58.0, 2.0, "wide", False),
            (76.0, 12.0, "wide", True),
            (120.0, 2.0, "wide", False),
        ],
    ),
    dict(
        id="clip_05_tt", platform="tiktok", dur=24, audio_start=16.0,
        angle="Intimate close-up vocal run edit",
        hook="NO STUDIO. JUST HIS VOICE.",
        caption="Closest thing to front row: no studio, just a live vocal with the city behind him. "
                "#TheWeeknd #fayewong",
        shots=[
            (62.0, 2.0, "medium", False),
            (30.0, 2.0, "wide", False),
            (44.0, 2.0, "wide", False),
            (164.0, 2.0, "artist", False),
            (176.0, 2.0, "wide", False),
            (26.0, 12.0, "wide", True),
            (60.0, 2.0, "wide", False),
        ],
    ),
    dict(
        id="clip_06_ig", platform="instagram", dur=24, audio_start=196.0,
        angle="Full production lighting & outro loop edit",
        hook="STAY FOR THE LAST NOTE",
        caption="Save this one for the last note. The crowd carried it out of the building. "
                "#TheWeeknd #fayewong",
        shots=[
            (214.0, 2.0, "wide", False),
            (204.0, 2.0, "medium", False),
            (200.0, 2.0, "wide", False),
            (210.0, 2.0, "wide", False),
            (216.0, 2.0, "wide", False),
            (206.0, 12.0, "wide", True),
            (212.0, 2.0, "wide", False),
        ],
    ),
]
